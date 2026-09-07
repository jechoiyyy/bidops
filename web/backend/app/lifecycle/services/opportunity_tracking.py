"""Human tracking choices and system recheck signals for opportunities.

The two kinds of state deliberately have separate write paths.  Human
choices are written only by :func:`set_tracking_status`; ingestion may only
call :func:`raise_recheck_signal`, which changes the two recheck columns and
appends a system audit event.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ...core.models import AuditEvent, utc_now
from ..models import Opportunity, OpportunityLink


TRACKING_STATUSES = ("미선택", "계속 추적", "보류", "종료")
_TRACKING_STATUS_SET = frozenset(TRACKING_STATUSES)
HUMAN_TRACKING_ACTION = "opportunity.tracking_status.changed"
SYSTEM_RECHECK_ACTION = "opportunity.recheck_signal.created"


class OpportunityTrackingError(ValueError):
    """Raised when a tracking transition cannot be represented safely."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _validate_human_name(value: str | None) -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        raise OpportunityTrackingError("actor_name_required", "담당자 이름이 필요합니다")
    clean = value.strip()
    if len(clean) > 128 or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in clean):
        raise OpportunityTrackingError("actor_name_invalid", "담당자 이름이 올바르지 않습니다")
    if clean.casefold() == "system":
        raise OpportunityTrackingError("actor_name_invalid", "담당자 이름이 올바르지 않습니다")
    return clean


def _validate_reason(value: str | None) -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        raise OpportunityTrackingError("tracking_reason_required", "추적 상태를 선택한 이유가 필요합니다")
    return value.strip()


def _validate_timestamp(value: datetime | None) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OpportunityTrackingError(
            "tracking_timestamp_invalid",
            "추적 상태 시각은 timezone-aware datetime이어야 합니다",
        )
    return value.astimezone(UTC)


def _resolve_opportunity(
    session: Session,
    value: Opportunity | int,
    *,
    lock: bool = True,
) -> Opportunity:
    """Resolve an opportunity while keeping the service usable by ORM callers."""

    if isinstance(value, Opportunity):
        if value.id is None:
            session.flush()
        opportunity_id = value.id
    elif isinstance(value, int) and not isinstance(value, bool):
        opportunity_id = value
    else:
        raise OpportunityTrackingError("opportunity_invalid", "사업기회 식별자가 올바르지 않습니다")

    if opportunity_id is None:
        raise OpportunityTrackingError("opportunity_not_found", "사업기회를 찾을 수 없습니다")
    opportunity = session.get(
        Opportunity,
        opportunity_id,
        with_for_update=True if lock else None,
    )
    if opportunity is None:
        raise OpportunityTrackingError("opportunity_not_found", "사업기회를 찾을 수 없습니다")
    if opportunity.merged_into_opportunity_id is not None:
        raise OpportunityTrackingError(
            "opportunity_merged",
            "병합된 사업기회의 상태는 변경할 수 없습니다",
        )
    return opportunity


def _resolve_link(session: Session, value: OpportunityLink | int) -> OpportunityLink:
    if isinstance(value, OpportunityLink):
        if value.id is None:
            session.flush()
        link_id = value.id
    elif isinstance(value, int) and not isinstance(value, bool):
        link_id = value
    else:
        raise OpportunityTrackingError("link_invalid", "사업기회 연결 식별자가 올바르지 않습니다")

    if link_id is None:
        raise OpportunityTrackingError("link_not_found", "사업기회 연결을 찾을 수 없습니다")
    link = session.get(OpportunityLink, link_id, with_for_update=True)
    if link is None:
        raise OpportunityTrackingError("link_not_found", "사업기회 연결을 찾을 수 없습니다")
    return link


def set_tracking_status(
    session: Session,
    opportunity: Opportunity | int,
    *,
    status: str,
    reason: str,
    selected_by: str,
    selected_at: datetime,
    request_id: UUID | str | None = None,
) -> Opportunity:
    """Record one human tracking choice and append its audit event.

    ``미선택`` is a supported reset operation, but it still requires the
    human reason, name, and timestamp supplied by the caller.  The three
    values are then intentionally cleared from the current opportunity row
    because the database CHECK requires an unselected row to have no human
    selection metadata.  The audit event retains the actor and event time.

    The same status may be selected again.  It is treated as a new human
    assertion: the current reason/actor/time are replaced and another
    append-only audit event is written.  Saving resolves the current recheck signal.
    The caller owns the surrounding transaction; this function flushes so a
    caller can use the returned row and event before committing.
    """

    if not isinstance(status, str) or status not in _TRACKING_STATUS_SET:
        raise OpportunityTrackingError("tracking_status_invalid", "지원하지 않는 추적 상태입니다")
    clean_reason = _validate_reason(reason)
    clean_actor = _validate_human_name(selected_by)
    event_at = _validate_timestamp(selected_at)
    target = _resolve_opportunity(session, opportunity)
    previous_status = target.tracking_status
    previous_signal_link_id = target.recheck_signal_link_id
    had_signal = target.recheck_signal_at is not None
    if had_signal:
        target.recheck_signal_at = None
        target.recheck_signal_link_id = None

    # This is the only service path that writes the human tracking columns.
    # In particular, the system signal path below never assigns any of them.
    target.tracking_status = status
    if status == "미선택":
        target.tracking_reason = None
        target.tracking_selected_by = None
        target.tracking_selected_at = None
    else:
        target.tracking_reason = clean_reason
        target.tracking_selected_by = clean_actor
        target.tracking_selected_at = event_at

    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=clean_actor,
            action=HUMAN_TRACKING_ACTION,
            aggregate_type="opportunity",
            aggregate_id=str(target.id),
            safe_metadata={
                "opportunity_id": target.id,
                "previous_tracking_status": previous_status,
                "tracking_status": status,
                "reason": clean_reason,
                **({"cleared_recheck_signal_link_id": previous_signal_link_id} if had_signal else {}),
            },
            request_id=str(request_id) if request_id is not None else None,
            created_at=event_at,
        )
    )
    session.flush()
    return target


def raise_recheck_signal(
    session: Session,
    opportunity: Opportunity | int,
    link: OpportunityLink | int,
    *,
    signaled_at: datetime | None = None,
) -> bool:
    """Raise or refresh a recheck signal for one newly attached official link.

    Only an opportunity currently marked ``종료`` receives a signal.  A
    repeated observation of the same link is a no-op.  A different official
    link replaces the singular current signal with that newest evidence and
    appends another system audit event.  No human tracking column is assigned
    here.
    """

    target = _resolve_opportunity(session, opportunity)
    evidence_link = _resolve_link(session, link)
    if evidence_link.opportunity_id != target.id:
        raise OpportunityTrackingError(
            "link_opportunity_mismatch",
            "사업기회 연결이 대상 사업기회에 속하지 않습니다",
        )
    if evidence_link.link_type != "official" or evidence_link.status != "확정":
        raise OpportunityTrackingError(
            "link_not_official",
            "재검토 신호의 근거는 확정 공식 연결이어야 합니다",
        )
    if target.tracking_status != "종료":
        return False
    if (
        target.recheck_signal_link_id is not None
        and target.recheck_signal_link_id == evidence_link.id
    ):
        return False

    event_at = _validate_timestamp(signaled_at) if signaled_at is not None else utc_now()
    previous_link_id = target.recheck_signal_link_id
    target.recheck_signal_at = event_at
    target.recheck_signal_link_id = evidence_link.id

    metadata: dict[str, Any] = {
        "opportunity_id": target.id,
        "link_id": evidence_link.id,
        "stage": evidence_link.stage,
        "evidence_external_no": evidence_link.evidence_external_no,
        "tracking_status": target.tracking_status,
    }
    if previous_link_id is not None:
        metadata["previous_signal_link_id"] = previous_link_id
    session.add(
        AuditEvent(
            actor_kind="system",
            claimed_name=None,
            action=SYSTEM_RECHECK_ACTION,
            aggregate_type="opportunity",
            aggregate_id=str(target.id),
            safe_metadata=metadata,
            request_id=None,
            created_at=event_at,
        )
    )
    session.flush()
    return True


# These aliases keep the service discoverable under the verbs used by the
# tracking workstream while retaining one implementation and one write path.
change_tracking_status = set_tracking_status
select_tracking_status = set_tracking_status
update_tracking_status = set_tracking_status
record_recheck_signal = raise_recheck_signal
signal_recheck = raise_recheck_signal


class OpportunityTrackingService:
    """Thin object facade for callers that keep domain services as instances."""

    set_tracking_status = staticmethod(set_tracking_status)
    change_tracking_status = staticmethod(set_tracking_status)
    raise_recheck_signal = staticmethod(raise_recheck_signal)
    record_recheck_signal = staticmethod(raise_recheck_signal)
