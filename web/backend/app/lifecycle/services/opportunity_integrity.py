"""Authoritative opportunity ownership and non-destructive merge rules.

This module is the single definition of an authoritative lifecycle link.  A
caller must not infer ownership from a candidate search result merely because
it points at a real record: only official confirmed links and explicitly
accepted human-reviewed candidates are authoritative.

It is also the single definition of the merge rule (spec §3.2) shared by
automatic official-key merges and human candidate acceptance: among the
locked opportunities, the ones with human state (a tracking choice other than
``미선택`` or a recheck signal) decide which row is retained.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ...core.models import AuditEvent, utc_now
from ..models import Opportunity, OpportunityLink
from .opportunity_tracking import _validate_human_name


CandidateDecision = Literal["accepted", "rejected"]
CANDIDATE_DECISION_ACTION = "opportunity_link.candidate_decision.recorded"
HUMAN_MERGE_ACTION = "opportunity.merged.human_confirmed"
MERGE_REASON_OFFICIAL_LINK = "authoritative_lifecycle_link"
MERGE_REASON_HUMAN_CONFIRMED = "human_confirmed_candidate"
#: ``search_strategy`` of a candidate created because an automatic merge was
#: refused between two opportunities with human state (spec §3.2).
MERGE_CONFIRMATION_STRATEGY = "merge_confirmation"
#: Non-owning status of an accepted candidate whose acceptance merged two
#: opportunities (spec §3.3).  Ownership stays with the moved official link.
HUMAN_MERGED_LINK_STATUS = "사람 확인 병합"
#: Earliest first: a merged opportunity entered BidOps at its earliest stage.
FIRST_REGISTERED_STAGE_ORDER = ("order_plan", "pre_spec", "bid_notice")


class OpportunityIntegrityError(ValueError):
    """A lifecycle ownership mutation could not be represented safely.

    ``details`` carries only safe identifiers and state values that an API
    boundary may return verbatim.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.details = details
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


def has_human_state(opportunity: Opportunity) -> bool:
    """Spec §3.2 "사람 상태 보유": a human tracking choice or a recheck signal."""

    return (
        opportunity.tracking_status != "미선택"
        or opportunity.recheck_signal_at is not None
    )


@dataclass(frozen=True)
class MergeOutcome:
    """The result of applying the merge rule to one locked opportunity set.

    ``held`` lists every locked row with human state.  When two or more rows
    hold human state nothing is merged: ``primary`` is ``None`` and no row was
    changed, so the caller decides how to ask a person (spec §3.2 ``|H|≥2``).
    """

    primary: Opportunity | None
    secondaries: tuple[Opportunity, ...] = ()
    held: tuple[Opportunity, ...] = ()

    @property
    def refused(self) -> bool:
        return self.primary is None and len(self.held) >= 2


def _stage_rank(stage: str | None) -> int:
    try:
        return FIRST_REGISTERED_STAGE_ORDER.index(stage)  # type: ignore[arg-type]
    except ValueError:
        return len(FIRST_REGISTERED_STAGE_ORDER)


def apply_merge_rule(
    session: Session,
    opportunities: Sequence[Opportunity],
    *,
    reason: str = MERGE_REASON_OFFICIAL_LINK,
    merged_at: datetime | None = None,
) -> MergeOutcome:
    """Lock the opportunities and merge them by the spec §3.2 retain policy.

    With H = locked rows holding human state:

    - ``|H| = 0``: the oldest row is retained;
    - ``|H| = 1``: that row is retained and its human tracking and recheck
      columns are left exactly as they were;
    - ``|H| ≥ 2``: nothing is merged and nothing is written.

    Merging never deletes a row.  Each secondary keeps its own columns and
    points at the retained primary through ``merged_into_*``; every link row,
    including rejected candidates, moves to the primary in place.  The
    primary's ``first_registered_stage`` becomes the earliest stage among the
    merged rows.  Every input is locked before the rule is evaluated.
    """

    unique_ids: set[int] = set()
    for opportunity in opportunities:
        if opportunity.id is None:
            session.flush()
        if opportunity.id is not None:
            unique_ids.add(int(opportunity.id))
    if not unique_ids:
        return MergeOutcome(primary=None)

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
    if any(item.merged_into_opportunity_id is not None for item in locked):
        raise OpportunityIntegrityError(
            "opportunity_merged",
            "이미 병합된 사업기회는 다시 병합할 수 없습니다",
        )
    held = tuple(item for item in locked if has_human_state(item))
    if len(locked) == 1:
        return MergeOutcome(primary=locked[0], held=held)
    if len(held) >= 2:
        return MergeOutcome(primary=None, held=held)

    primary = held[0] if held else min(
        locked,
        key=lambda item: (
            item.created_at or datetime.max.replace(tzinfo=UTC),
            item.id,
        ),
    )
    event_at = _aware_utc(merged_at)
    clean_reason = _merge_reason(reason)
    earliest = min(locked, key=lambda item: _stage_rank(item.first_registered_stage))
    if _stage_rank(earliest.first_registered_stage) < _stage_rank(
        primary.first_registered_stage
    ):
        primary.first_registered_stage = earliest.first_registered_stage
    secondaries: list[Opportunity] = []
    for secondary in locked:
        if secondary is primary:
            continue
        for link in list(secondary.links):
            link.opportunity = primary
        secondary.merged_into_opportunity = primary
        secondary.merged_at = event_at
        secondary.merge_reason = clean_reason
        secondaries.append(secondary)
    session.flush()
    return MergeOutcome(primary=primary, secondaries=tuple(secondaries), held=held)


def merge_opportunities(
    session: Session,
    opportunities: Sequence[Opportunity],
    *,
    reason: str = MERGE_REASON_OFFICIAL_LINK,
    merged_at: datetime | None = None,
) -> Opportunity | None:
    """Merge by :func:`apply_merge_rule` and fail closed when it refuses.

    Returns the retained primary.  When two or more rows hold human state the
    rule refuses; this entry point raises ``opportunity_merge_state_conflict``
    without writing anything.  Callers that turn a refusal into a person's
    decision (ingest, candidate acceptance) use :func:`apply_merge_rule`.
    """

    outcome = apply_merge_rule(
        session, opportunities, reason=reason, merged_at=merged_at
    )
    if outcome.refused:
        raise OpportunityIntegrityError(
            "opportunity_merge_state_conflict",
            "사람 추적 선택 또는 재검토 신호가 있는 사업기회가 둘 이상이라 병합할 수 없습니다",
            details={"opportunity_ids": sorted(int(item.id) for item in outcome.held)},
        )
    return outcome.primary


def _candidate_reason(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpportunityIntegrityError(
            "candidate_decision_reason_required",
            "후보 연결 판정 이유가 필요합니다",
        )
    return value.strip()


def _candidate_target_owner(
    session: Session,
    link: OpportunityLink,
) -> Opportunity | None:
    """The active opportunity that authoritatively owns the candidate target."""

    statement = (
        select(Opportunity)
        .join(OpportunityLink, Opportunity.id == OpportunityLink.opportunity_id)
        .where(
            OpportunityLink.id != link.id,
            authoritative_link_predicate(OpportunityLink),
            active_opportunity_predicate(Opportunity),
        )
        .order_by(OpportunityLink.id)
        .limit(1)
    )
    if link.order_plan_id is not None:
        statement = statement.where(
            OpportunityLink.order_plan_id == link.order_plan_id
        )
    elif link.notice_id is not None:
        statement = statement.where(OpportunityLink.notice_id == link.notice_id)
    else:
        return None
    return session.scalar(statement)


def _merge_conflict_state(opportunity: Opportunity) -> dict[str, Any]:
    selected_at = opportunity.tracking_selected_at
    return {
        "id": opportunity.id,
        "tracking_status": opportunity.tracking_status,
        "tracking_selected_by": opportunity.tracking_selected_by,
        "tracking_selected_at": (
            selected_at.astimezone(UTC).isoformat() if selected_at is not None else None
        ),
        "recheck_signal": opportunity.recheck_signal_at is not None,
    }


@dataclass(frozen=True)
class CandidateDecisionOutcome:
    """One recorded (or replayed) candidate decision.

    ``retained_opportunity_id``/``secondary_opportunity_id`` are set only when
    this call merged two opportunities; an exact replay reports ``replayed``.
    """

    link: OpportunityLink
    retained_opportunity_id: int | None = None
    secondary_opportunity_id: int | None = None
    replayed: bool = False

    @property
    def merged(self) -> bool:
        return self.retained_opportunity_id is not None


def record_candidate_decision(
    session: Session,
    link: OpportunityLink | int,
    *,
    decision: CandidateDecision,
    reason: str,
    reviewer_name: str,
    reviewed_at: datetime | None = None,
) -> CandidateDecisionOutcome:
    """Accept or reject one pending candidate with audit and replay safety.

    Accepting a candidate whose target no active opportunity owns makes the
    candidate row the owner (``사람 확인 완료``).  Accepting one whose target
    another active opportunity owns applies the §3.2 rule to the candidate
    owner and the target owner (spec §3.3): with at most one of them holding
    human state they are merged and the candidate becomes ``사람 확인 병합``,
    a non-owning row, because ownership is carried by the moved official
    link; with both holding human state nothing changes and
    ``candidate_merge_state_conflict`` names both states.  A human-confirmed
    merge never raises a recheck signal.
    """

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

    # A later official key may promote an accepted candidate in place, and a
    # merged acceptance keeps its review metadata on a non-owning row.  Either
    # way the retained review metadata makes an exact replay idempotent, while
    # a different replay remains a conflict.
    if target.human_decision is not None:
        if (
            target.human_decision == decision
            and target.reviewer_name == clean_reviewer
            and target.review_reason == clean_reason
        ):
            return CandidateDecisionOutcome(link=target, replayed=True)
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
    decided_owner_id = target.opportunity_id
    status = "사람 확인 완료"
    merge: MergeOutcome | None = None
    if decision == "accepted":
        if target.order_plan_id is None and target.notice_id is None:
            raise OpportunityIntegrityError(
                "candidate_target_required", "수락할 후보 연결 대상이 필요합니다"
            )
        owner = target.opportunity
        if owner is None or owner.merged_into_opportunity_id is not None:
            raise OpportunityIntegrityError(
                "candidate_state_conflict",
                "현재 상태에서는 후보 연결을 판정할 수 없습니다",
            )
        target_owner = _candidate_target_owner(session, target)
        if target_owner is not None:
            if target_owner.id == owner.id:
                raise OpportunityIntegrityError(
                    "candidate_target_already_authoritative",
                    "대상 레코드는 이미 확정된 사업기회에 연결되어 있습니다",
                )
            merge = apply_merge_rule(
                session,
                [owner, target_owner],
                reason=MERGE_REASON_HUMAN_CONFIRMED,
                merged_at=event_at,
            )
            if merge.refused:
                raise OpportunityIntegrityError(
                    "candidate_merge_state_conflict",
                    "두 사업기회 모두 사람 추적 선택 또는 재검토 신호가 있어 병합할 수 없습니다",
                    details={
                        "opportunities": [
                            _merge_conflict_state(owner),
                            _merge_conflict_state(target_owner),
                        ]
                    },
                )
            status = HUMAN_MERGED_LINK_STATUS

    target.status = status
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
                "opportunity_id": decided_owner_id,
                "decision": decision,
            },
            request_id=None,
            created_at=event_at,
        )
    )
    if merge is None or merge.primary is None:
        session.flush()
        return CandidateDecisionOutcome(link=target)

    primary = merge.primary
    (secondary,) = merge.secondaries
    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=clean_reviewer,
            action=HUMAN_MERGE_ACTION,
            aggregate_type="opportunity",
            aggregate_id=str(primary.id),
            safe_metadata={
                "retained_opportunity_id": primary.id,
                "secondary_opportunity_id": secondary.id,
                "opportunity_link_id": target.id,
            },
            request_id=None,
            created_at=event_at,
        )
    )
    session.flush()
    return CandidateDecisionOutcome(
        link=target,
        retained_opportunity_id=primary.id,
        secondary_opportunity_id=secondary.id,
    )


def decide_candidate_link(
    session: Session,
    link: OpportunityLink | int,
    *,
    decision: CandidateDecision,
    reason: str,
    reviewer_name: str,
    reviewed_at: datetime | None = None,
) -> OpportunityLink:
    """Record one candidate decision and return the decided link row."""

    return record_candidate_decision(
        session,
        link,
        decision=decision,
        reason=reason,
        reviewer_name=reviewer_name,
        reviewed_at=reviewed_at,
    ).link


__all__ = [
    "CANDIDATE_DECISION_ACTION",
    "CandidateDecisionOutcome",
    "FIRST_REGISTERED_STAGE_ORDER",
    "HUMAN_MERGED_LINK_STATUS",
    "HUMAN_MERGE_ACTION",
    "MERGE_CONFIRMATION_STRATEGY",
    "MERGE_REASON_HUMAN_CONFIRMED",
    "MERGE_REASON_OFFICIAL_LINK",
    "MergeOutcome",
    "OpportunityIntegrityError",
    "active_opportunity_predicate",
    "apply_merge_rule",
    "authoritative_link_predicate",
    "decide_candidate_link",
    "has_human_state",
    "is_authoritative_link",
    "merge_opportunities",
    "record_candidate_decision",
]
