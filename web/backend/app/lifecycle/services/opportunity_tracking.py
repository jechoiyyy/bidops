"""Human tracking choices and system recheck signals for opportunities.

The two kinds of state deliberately have separate write paths.  Human
choices are written only by :func:`set_tracking_status`; ingestion may only
call :func:`raise_recheck_signal`, which changes the two recheck columns and
appends a system audit event.  A person may clear the signal without a new
tracking decision through :func:`acknowledge_recheck_signal`, which also
leaves the human tracking columns alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.idempotency_fence import (
    IdempotencyFenceError,
    json_primitives,
    load_receipt,
    new_receipt,
    receipt_id as fence_receipt_id,
    request_sha256,
)
from ...core.models import AuditEvent, utc_now
from ..models import (
    Company,
    CompanyOpportunityTracking,
    CompanyTrackingEvent,
    Opportunity,
    OpportunityLink,
)
from ..schemas.companies import CompanyTrackingDTO
from .company_context import _ensure_sqlite_outer_transaction


TRACKING_STATUSES = ("미선택", "계속 추적", "보류", "종료")
_TRACKING_STATUS_SET = frozenset(TRACKING_STATUSES)
#: 새 공식 연결이 재검토 신호를 켜는 추적 상태 (spec §6.1). ``미선택``은 아직 사람의
#: 시야 밖이므로 켜지 않는다.
RECHECK_SIGNAL_TRACKING_STATUSES = ("계속 추적", "보류", "종료")
HUMAN_TRACKING_ACTION = "opportunity.tracking_status.changed"
SYSTEM_RECHECK_ACTION = "opportunity.recheck_signal.created"
ACKNOWLEDGED_RECHECK_ACTION = "opportunity.recheck_signal.acknowledged"
RECHECK_NOTE_MAX_LENGTH = 500
COMPANY_TRACKING_OPERATION = "company_tracking.set"
COMPANY_TRACKING_AGGREGATE_TYPE = "company_opportunity_tracking"
_COMPANY_TRACKING_RECEIPT_NAMESPACE = uuid5(
    NAMESPACE_URL, "https://bidops.invalid/idempotency/company-tracking/v1"
)
_CURRENT_TRACKING_PK_CONSTRAINTS = frozenset(
    {"company_opportunity_tracking_pkey", "pk_company_opportunity_tracking"}
)


class OpportunityTrackingError(ValueError):
    """Raised when a tracking transition cannot be represented safely.

    ``details`` carries only safe identifiers or state values that an API
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


@dataclass(frozen=True)
class CompanyTrackingMutationResult:
    """Validated response plus the exact JSON snapshot stored for replay."""

    response: CompanyTrackingDTO
    snapshot: dict[str, Any]
    response_status: int = 200
    replayed: bool = False


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


def _company_tracking_aggregate_id(company_id: UUID, opportunity_id: int) -> str:
    return f"{company_id}:{opportunity_id}"


def _company_tracking_request_hash(
    *,
    company_id: UUID,
    opportunity_id: int,
    status: str,
    reason: str,
    expected_revision: int,
    actor: str,
) -> str:
    return request_sha256(
        {
            "operation": COMPANY_TRACKING_OPERATION,
            "company_id": str(company_id),
            "opportunity_id": opportunity_id,
            "tracking_status": status,
            "trimmed_reason": reason,
            "expected_revision": expected_revision,
            "decoded_actor": actor,
        }
    )


def _company_tracking_receipt_id(
    *, company_id: UUID, opportunity_id: int, actor: str, request_id: UUID
) -> UUID:
    return fence_receipt_id(
        _COMPANY_TRACKING_RECEIPT_NAMESPACE,
        operation=COMPANY_TRACKING_OPERATION,
        aggregate_type=COMPANY_TRACKING_AGGREGATE_TYPE,
        aggregate_id=_company_tracking_aggregate_id(company_id, opportunity_id),
        claimed_name=actor,
        request_id=request_id,
    )


def _company_tracking_processing_failed() -> OpportunityTrackingError:
    return OpportunityTrackingError(
        "processing_failed", "회사별 추적 상태를 확인할 수 없습니다"
    )


def _is_current_tracking_pk_conflict(error: IntegrityError) -> bool:
    """Accept only the expected missing-row insert race as a retry fence."""

    original = error.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate is not None:
        if sqlstate != "23505":
            return False
        diagnostic = getattr(original, "diag", None)
        return getattr(diagnostic, "constraint_name", None) in _CURRENT_TRACKING_PK_CONSTRAINTS
    message = str(original).lower()
    return (
        "unique constraint failed: company_opportunity_tracking.company_id, "
        "company_opportunity_tracking.opportunity_id"
    ) in message


def _tracking_dto(
    *,
    company_id: UUID,
    opportunity_id: int,
    current: CompanyOpportunityTracking | None,
) -> CompanyTrackingDTO:
    if current is None:
        return CompanyTrackingDTO(
            company_id=company_id,
            opportunity_id=opportunity_id,
            tracking_status="미선택",
            reason=None,
            selected_by=None,
            selected_at=None,
            revision=0,
        )
    return CompanyTrackingDTO(
        company_id=current.company_id,
        opportunity_id=current.opportunity_id,
        tracking_status=current.tracking_status,
        reason=current.reason,
        selected_by=current.selected_by,
        selected_at=current.selected_at,
        revision=current.revision,
    )


def _company_tracking_replay(
    snapshot: dict[str, Any], *, company_id: UUID, opportunity_id: int
) -> CompanyTrackingMutationResult:
    if (
        not isinstance(snapshot.get("company_id"), str)
        or not isinstance(snapshot.get("opportunity_id"), int)
        or isinstance(snapshot.get("opportunity_id"), bool)
        or not isinstance(snapshot.get("revision"), int)
        or isinstance(snapshot.get("revision"), bool)
        or (
            snapshot.get("selected_at") is not None
            and not isinstance(snapshot.get("selected_at"), str)
        )
    ):
        raise _company_tracking_processing_failed()
    try:
        response = CompanyTrackingDTO.model_validate(snapshot)
    except Exception as error:
        raise _company_tracking_processing_failed() from error
    if response.company_id != company_id or response.opportunity_id != opportunity_id:
        raise _company_tracking_processing_failed()
    return CompanyTrackingMutationResult(
        response=response,
        snapshot=snapshot,
        response_status=200,
        replayed=True,
    )


def _existing_company_tracking_receipt(
    session: Session,
    *,
    receipt_id: UUID,
    company_id: UUID,
    opportunity_id: int,
    actor: str,
    request_id: UUID,
    request_hash: str,
) -> CompanyTrackingMutationResult | None:
    try:
        snapshot = load_receipt(
            session,
            receipt=receipt_id,
            operation=COMPANY_TRACKING_OPERATION,
            aggregate_type=COMPANY_TRACKING_AGGREGATE_TYPE,
            aggregate_id=_company_tracking_aggregate_id(company_id, opportunity_id),
            claimed_name=actor,
            request_id=request_id,
            request_hash=request_hash,
        )
    except IdempotencyFenceError as error:
        if error.code == "idempotency_conflict":
            raise OpportunityTrackingError(
                "idempotency_conflict", "같은 request_id가 다른 요청에 사용되었습니다"
            ) from None
        raise _company_tracking_processing_failed() from None
    if snapshot is None:
        return None
    return _company_tracking_replay(
        snapshot, company_id=company_id, opportunity_id=opportunity_id
    )


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


def _validate_company_tracking_ids(
    company_id: UUID, opportunity_id: int
) -> tuple[UUID, int]:
    if not isinstance(company_id, UUID):
        raise OpportunityTrackingError("invalid_request", "회사 식별자가 올바르지 않습니다")
    if (
        not isinstance(opportunity_id, int)
        or isinstance(opportunity_id, bool)
        or opportunity_id < 1
    ):
        raise OpportunityTrackingError(
            "invalid_request", "사업기회 식별자가 올바르지 않습니다"
        )
    return company_id, opportunity_id


def _require_company_and_opportunity(
    session: Session, *, company_id: UUID, opportunity_id: int
) -> None:
    if session.get(Company, company_id) is None:
        raise OpportunityTrackingError("not_found", "회사를 찾을 수 없습니다")
    if session.get(Opportunity, opportunity_id) is None:
        raise OpportunityTrackingError("not_found", "사업기회를 찾을 수 없습니다")


def get_company_tracking(
    session: Session, *, company_id: UUID, opportunity_id: int
) -> CompanyTrackingDTO:
    """Read one company decision without materializing the default state."""

    company_id, opportunity_id = _validate_company_tracking_ids(
        company_id, opportunity_id
    )
    _require_company_and_opportunity(
        session, company_id=company_id, opportunity_id=opportunity_id
    )
    current = session.get(
        CompanyOpportunityTracking, (company_id, opportunity_id)
    )
    return _tracking_dto(
        company_id=company_id,
        opportunity_id=opportunity_id,
        current=current,
    )


def company_tracking_views(
    session: Session,
    *,
    company_ids: Sequence[UUID],
    opportunity_ids: Sequence[int],
) -> dict[tuple[UUID, int], CompanyTrackingDTO]:
    """Batched read of company decisions for every (company, opportunity) pair.

    One query regardless of the number of pairs (company-scoped list and
    comparison projections, DEMO contract §6).  A pair without a row is the
    §2 default (``미선택``/revision 0/metadata null), exactly as
    :func:`get_company_tracking`; nothing is materialized.  The caller passes
    ids it has already resolved; unknown ids are simply absent rows.
    """

    companies = tuple(dict.fromkeys(UUID(str(value)) for value in company_ids))
    opportunities = tuple(dict.fromkeys(int(value) for value in opportunity_ids))
    if not companies or not opportunities:
        return {}
    rows = {
        (row.company_id, row.opportunity_id): row
        for row in session.scalars(
            select(CompanyOpportunityTracking).where(
                CompanyOpportunityTracking.company_id.in_(companies),
                CompanyOpportunityTracking.opportunity_id.in_(opportunities),
            )
        )
    }
    return {
        (company_id, opportunity_id): _tracking_dto(
            company_id=company_id,
            opportunity_id=opportunity_id,
            current=rows.get((company_id, opportunity_id)),
        )
        for company_id in companies
        for opportunity_id in opportunities
    }


def _apply_company_tracking_current(
    current: CompanyOpportunityTracking,
    *,
    status: str,
    reason: str,
    actor: str,
    selected_at: datetime,
    revision: int,
) -> None:
    current.tracking_status = status
    current.revision = revision
    if status == "미선택":
        current.reason = None
        current.selected_by = None
        current.selected_at = None
    else:
        current.reason = reason
        current.selected_by = actor
        current.selected_at = selected_at


def set_company_tracking(
    session: Session,
    *,
    company_id: UUID,
    opportunity_id: int,
    status: str,
    reason: str,
    expected_revision: int,
    request_id: UUID,
    selected_by: str,
    selected_at: datetime | None = None,
) -> CompanyTrackingMutationResult:
    """Advance company-scoped tracking, event, and receipt in one transaction.

    The caller owns commit/rollback. Existing current rows are locked. For a
    missing row, the final revision-1 projection is inserted in a savepoint;
    only its composite-PK collision is treated as a concurrent winner. The
    winner receipt is checked again before the latest revision is evaluated.
    """

    company_id, opportunity_id = _validate_company_tracking_ids(
        company_id, opportunity_id
    )
    if not isinstance(status, str) or status not in _TRACKING_STATUS_SET:
        raise OpportunityTrackingError(
            "tracking_status_invalid", "지원하지 않는 추적 상태입니다"
        )
    clean_reason = _validate_reason(reason)
    if len(clean_reason) > 2000:
        raise OpportunityTrackingError("invalid_request", "추적 사유가 올바르지 않습니다")
    clean_actor = _validate_human_name(selected_by)
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 0
        or not isinstance(request_id, UUID)
    ):
        raise OpportunityTrackingError("invalid_request", "요청이 올바르지 않습니다")
    event_at = (
        _validate_timestamp(selected_at) if selected_at is not None else utc_now()
    )
    request_hash = _company_tracking_request_hash(
        company_id=company_id,
        opportunity_id=opportunity_id,
        status=status,
        reason=clean_reason,
        expected_revision=expected_revision,
        actor=clean_actor,
    )
    receipt_id = _company_tracking_receipt_id(
        company_id=company_id,
        opportunity_id=opportunity_id,
        actor=clean_actor,
        request_id=request_id,
    )
    replay = _existing_company_tracking_receipt(
        session,
        receipt_id=receipt_id,
        company_id=company_id,
        opportunity_id=opportunity_id,
        actor=clean_actor,
        request_id=request_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return replay

    _require_company_and_opportunity(
        session, company_id=company_id, opportunity_id=opportunity_id
    )
    current = session.get(
        CompanyOpportunityTracking,
        (company_id, opportunity_id),
        with_for_update=True,
    )
    inserted = False
    previous_status = "미선택"
    if current is None:
        if expected_revision != 0:
            raise OpportunityTrackingError(
                "version_conflict",
                "회사별 추적 상태가 변경되었습니다",
                details={"current_revision": 0},
            )
        _ensure_sqlite_outer_transaction(session)
        current = CompanyOpportunityTracking(
            company_id=company_id,
            opportunity_id=opportunity_id,
            tracking_status=status,
            reason=None,
            selected_by=None,
            selected_at=None,
            revision=1,
        )
        _apply_company_tracking_current(
            current,
            status=status,
            reason=clean_reason,
            actor=clean_actor,
            selected_at=event_at,
            revision=1,
        )
        try:
            with session.begin_nested():
                session.add(current)
                session.flush()
            inserted = True
        except IntegrityError as error:
            if not _is_current_tracking_pk_conflict(error):
                raise _company_tracking_processing_failed() from error
            current = session.get(
                CompanyOpportunityTracking,
                (company_id, opportunity_id),
                with_for_update=True,
                populate_existing=True,
            )
            if current is None:
                raise _company_tracking_processing_failed() from error
            replay = _existing_company_tracking_receipt(
                session,
                receipt_id=receipt_id,
                company_id=company_id,
                opportunity_id=opportunity_id,
                actor=clean_actor,
                request_id=request_id,
                request_hash=request_hash,
            )
            if replay is not None:
                return replay

    if not inserted:
        replay = _existing_company_tracking_receipt(
            session,
            receipt_id=receipt_id,
            company_id=company_id,
            opportunity_id=opportunity_id,
            actor=clean_actor,
            request_id=request_id,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        if current.revision != expected_revision:
            raise OpportunityTrackingError(
                "version_conflict",
                "회사별 추적 상태가 변경되었습니다",
                details={"current_revision": current.revision},
            )
        previous_status = current.tracking_status
        _apply_company_tracking_current(
            current,
            status=status,
            reason=clean_reason,
            actor=clean_actor,
            selected_at=event_at,
            revision=current.revision + 1,
        )

    response = _tracking_dto(
        company_id=company_id,
        opportunity_id=opportunity_id,
        current=current,
    )
    snapshot = response.model_dump(mode="json")
    if not json_primitives(snapshot):
        raise _company_tracking_processing_failed()
    session.add_all(
        [
            CompanyTrackingEvent(
                company_id=company_id,
                opportunity_id=opportunity_id,
                revision=current.revision,
                previous_status=previous_status,
                new_status=status,
                reason=clean_reason,
                actor=clean_actor,
                request_id=request_id,
                created_at=event_at,
            ),
            new_receipt(
                receipt=receipt_id,
                operation=COMPANY_TRACKING_OPERATION,
                aggregate_type=COMPANY_TRACKING_AGGREGATE_TYPE,
                aggregate_id=_company_tracking_aggregate_id(
                    company_id, opportunity_id
                ),
                claimed_name=clean_actor,
                request_id=request_id,
                request_hash=request_hash,
                snapshot=snapshot,
            ),
        ]
    )
    try:
        session.flush()
    except IntegrityError as error:
        raise _company_tracking_processing_failed() from error
    return CompanyTrackingMutationResult(response=response, snapshot=snapshot)


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

    An opportunity whose human tracking status is ``계속 추적``, ``보류`` or
    ``종료`` receives a signal (spec §6.1); ``미선택`` never does.  Callers
    raise it only for automatic linking or merging that brings a record into
    the opportunity; a human-confirmed merge does not.  A repeated observation
    of the same link is a no-op.  A different official link replaces the
    singular current signal with that newest evidence and appends another
    system audit event.  No human tracking column is assigned here.
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
    if target.tracking_status not in RECHECK_SIGNAL_TRACKING_STATUSES:
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


def _validate_note(value: str | None) -> bool:
    """Return whether a non-blank note was supplied; the text itself is not kept."""

    if value is None:
        return False
    if not isinstance(value, str) or len(value) > RECHECK_NOTE_MAX_LENGTH:
        raise OpportunityTrackingError("invalid_request", "요청이 올바르지 않습니다")
    return bool(value.strip())


def acknowledge_recheck_signal(
    session: Session,
    opportunity: Opportunity | int,
    *,
    expected_link_id: int,
    acknowledged_by: str,
    acknowledged_at: datetime,
    note: str | None = None,
) -> Opportunity:
    """Clear the current recheck signal without touching the human choice.

    The caller names the evidence link it looked at.  If the signal is gone,
    or now points at a different link, nothing changes and the caller must
    read the current state again (spec §6.2).  The audit event records the
    opportunity, the acknowledged link and whether a note was written; the
    note text is not stored anywhere.
    """

    if (
        not isinstance(expected_link_id, int)
        or isinstance(expected_link_id, bool)
        or expected_link_id < 1
    ):
        raise OpportunityTrackingError(
            "opportunity_link_invalid", "사업기회 연결 식별자가 올바르지 않습니다"
        )
    note_present = _validate_note(note)
    clean_actor = _validate_human_name(acknowledged_by)
    event_at = _validate_timestamp(acknowledged_at)
    target = _resolve_opportunity(session, opportunity)
    if target.recheck_signal_at is None or target.recheck_signal_link_id is None:
        raise OpportunityTrackingError(
            "recheck_signal_absent", "확인할 재검토 신호가 없습니다"
        )
    if target.recheck_signal_link_id != expected_link_id:
        raise OpportunityTrackingError(
            "recheck_signal_changed",
            "재검토 신호의 근거 연결이 바뀌었습니다",
            details={"current_link_id": target.recheck_signal_link_id},
        )

    link_id = target.recheck_signal_link_id
    target.recheck_signal_at = None
    target.recheck_signal_link_id = None
    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=clean_actor,
            action=ACKNOWLEDGED_RECHECK_ACTION,
            aggregate_type="opportunity",
            aggregate_id=str(target.id),
            safe_metadata={
                "opportunity_id": target.id,
                "link_id": link_id,
                "note_present": note_present,
            },
            request_id=None,
            created_at=event_at,
        )
    )
    session.flush()
    return target


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
    acknowledge_recheck_signal = staticmethod(acknowledge_recheck_signal)
