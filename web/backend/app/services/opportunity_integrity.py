"""Authoritative opportunity ownership and non-destructive merge rules.

This module is the single definition of an authoritative lifecycle link.  A
caller must not infer ownership from a candidate search result merely because
it points at a real record: only official confirmed links and explicitly
accepted human-reviewed candidates are authoritative.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ..core.models import AuditEvent, utc_now
from ..lifecycle.models import Opportunity, OpportunityLink
from .opportunity_tracking import _validate_human_name


CandidateDecision = Literal["accepted", "rejected"]
CANDIDATE_DECISION_ACTION = "opportunity_link.candidate_decision.recorded"
MERGE_REASON_OFFICIAL_LINK = "authoritative_lifecycle_link"


class OpportunityIntegrityError(ValueError):
    """A lifecycle ownership mutation could not be represented safely."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def authoritative_link_predicate(link: Any = OpportunityLink) -> ColumnElement[bool]:
    """Return the one SQL predicate that grants lifecycle ownership."""

    return or_(
        and_(link.link_type == "official", link.status == "확정"),
        and_(
            link.link_type == "candidate",
            link.status == "사람 확인 완료",
            link.human_decision == "accepted",
        ),
    )


def active_opportunity_predicate(
    opportunity: Any = Opportunity,
) -> ColumnElement[bool]:
    """Return the SQL predicate for a row that still owns lifecycle records."""

    return opportunity.merged_into_opportunity_id.is_(None)


def is_authoritative_link(link: OpportunityLink) -> bool:
    """Python counterpart to :func:`authoritative_link_predicate`."""

    return (link.link_type == "official" and link.status == "확정") or (
        link.link_type == "candidate"
        and link.status == "사람 확인 완료"
        and link.human_decision == "accepted"
    )


def _aware_utc(value: datetime | None) -> datetime:
    result = value or utc_now()
    if result.tzinfo is None or result.utcoffset() is None:
        raise OpportunityIntegrityError(
            "opportunity_merge_timestamp_invalid",
            "사업기회 병합 시각은 timezone-aware datetime이어야 합니다",
        )
    return result.astimezone(UTC)


def _merge_reason(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpportunityIntegrityError(
            "opportunity_merge_reason_required",
            "사업기회 병합 근거가 필요합니다",
        )
    return value.strip()


def merge_opportunities(
    session: Session,
    opportunities: Sequence[Opportunity],
    *,
    reason: str = MERGE_REASON_OFFICIAL_LINK,
    merged_at: datetime | None = None,
) -> Opportunity | None:
    """Merge active, untouched opportunities without deleting history rows.

    Every input is locked before the state fence is checked.  Automatic merge
    is allowed only while all rows still have the default human tracking state
    and no recheck signal.  Secondary rows remain addressable and point at the
    retained primary; all link rows, including rejected candidates, move to
    that primary in place.
    """

    unique_ids: set[int] = set()
    for opportunity in opportunities:
        if opportunity.id is None:
            session.flush()
        if opportunity.id is not None:
            unique_ids.add(int(opportunity.id))
    if not unique_ids:
        return None

    locked = session.scalars(
        select(Opportunity)
        .where(Opportunity.id.in_(sorted(unique_ids)))
        .order_by(Opportunity.id)
        .with_for_update()
    ).all()
    if len(locked) != len(unique_ids):
        raise OpportunityIntegrityError(
            "opportunity_not_found",
            "병합할 사업기회를 찾을 수 없습니다",
        )
    if len(locked) == 1:
        return locked[0]

    conflicting = [
        item.id
        for item in locked
        if item.merged_into_opportunity_id is not None
        or item.tracking_status != "미선택"
        or item.recheck_signal_at is not None
        or item.recheck_signal_link_id is not None
    ]
    if conflicting:
        raise OpportunityIntegrityError(
            "opportunity_merge_state_conflict",
            "사람 추적 선택 또는 재검토 상태가 있는 사업기회는 자동 병합할 수 없습니다",
        )

    primary = min(
        locked,
        key=lambda item: (
            item.created_at or datetime.max.replace(tzinfo=UTC),
            item.id,
        ),
    )
    event_at = _aware_utc(merged_at)
    clean_reason = _merge_reason(reason)
    for secondary in locked:
        if secondary is primary:
            continue
        for link in list(secondary.links):
            link.opportunity = primary
        secondary.merged_into_opportunity = primary
        secondary.merged_at = event_at
        secondary.merge_reason = clean_reason
    session.flush()
    return primary


def _candidate_reason(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpportunityIntegrityError(
            "candidate_decision_reason_required",
            "후보 연결 판정 이유가 필요합니다",
        )
    return value.strip()


def _candidate_target_already_owned(
    session: Session,
    link: OpportunityLink,
) -> bool:
    statement = (
        select(OpportunityLink.id)
        .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
        .where(
            OpportunityLink.id != link.id,
            authoritative_link_predicate(OpportunityLink),
            active_opportunity_predicate(Opportunity),
        )
        .limit(1)
    )
    if link.order_plan_id is not None:
        statement = statement.where(
            OpportunityLink.order_plan_id == link.order_plan_id
        )
    elif link.notice_id is not None:
        statement = statement.where(OpportunityLink.notice_id == link.notice_id)
    else:
        return False
    return session.scalar(statement) is not None


def decide_candidate_link(
    session: Session,
    link: OpportunityLink | int,
    *,
    decision: CandidateDecision,
    reason: str,
    reviewer_name: str,
    reviewed_at: datetime | None = None,
) -> OpportunityLink:
    """Accept or reject one pending candidate with audit and replay safety."""

    if decision not in {"accepted", "rejected"}:
        raise OpportunityIntegrityError(
            "candidate_decision_invalid", "지원하지 않는 후보 연결 판정입니다"
        )
    clean_reason = _candidate_reason(reason)
    clean_reviewer = _validate_human_name(reviewer_name)
    event_at = _aware_utc(reviewed_at)
    link_id = link.id if isinstance(link, OpportunityLink) else link
    if not isinstance(link_id, int) or isinstance(link_id, bool):
        raise OpportunityIntegrityError(
            "opportunity_link_invalid", "사업기회 연결 식별자가 올바르지 않습니다"
        )
    target = session.get(OpportunityLink, link_id, with_for_update=True)
    if target is None:
        raise OpportunityIntegrityError(
            "opportunity_link_not_found", "사업기회 연결을 찾을 수 없습니다"
        )

    # A later official key may promote an accepted candidate in place.  Its
    # retained review metadata still makes an exact replay idempotent, while a
    # different replay remains a conflict.
    if target.human_decision is not None:
        if (
            target.human_decision == decision
            and target.reviewer_name == clean_reviewer
            and target.review_reason == clean_reason
        ):
            return target
        raise OpportunityIntegrityError(
            "candidate_decision_conflict", "후보 연결에 이미 다른 판정이 있습니다"
        )
    if target.link_type != "candidate":
        raise OpportunityIntegrityError(
            "candidate_link_required", "후보 연결만 사람 판정할 수 있습니다"
        )
    if target.status != "후보 확인 대기" or target.human_decision is not None:
        raise OpportunityIntegrityError(
            "candidate_state_conflict", "현재 상태에서는 후보 연결을 판정할 수 없습니다"
        )
    if decision == "accepted":
        if target.order_plan_id is None and target.notice_id is None:
            raise OpportunityIntegrityError(
                "candidate_target_required", "수락할 후보 연결 대상이 필요합니다"
            )
        if _candidate_target_already_owned(session, target):
            raise OpportunityIntegrityError(
                "candidate_target_already_authoritative",
                "대상 레코드는 이미 확정된 사업기회에 연결되어 있습니다",
            )

    target.status = "사람 확인 완료"
    target.human_decision = decision
    target.reviewer_name = clean_reviewer
    target.reviewed_at = event_at
    target.review_reason = clean_reason
    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=clean_reviewer,
            action=CANDIDATE_DECISION_ACTION,
            aggregate_type="opportunity_link",
            aggregate_id=str(target.id),
            safe_metadata={
                "opportunity_link_id": target.id,
                "opportunity_id": target.opportunity_id,
                "decision": decision,
            },
            request_id=None,
            created_at=event_at,
        )
    )
    session.flush()
    return target


__all__ = [
    "CANDIDATE_DECISION_ACTION",
    "MERGE_REASON_OFFICIAL_LINK",
    "OpportunityIntegrityError",
    "active_opportunity_predicate",
    "authoritative_link_predicate",
    "decide_candidate_link",
    "is_authoritative_link",
    "merge_opportunities",
]
