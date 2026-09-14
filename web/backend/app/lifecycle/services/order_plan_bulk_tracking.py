"""Atomic bulk tracking-start state machine for selected order plans.

The browser's selection is only a set of plan primary keys.  This service is
therefore the sole place that resolves authoritative ownership, checks the
latest locked status, writes the existing human tracking decision, and records
a final receipt.  The existing single-opportunity PATCH remains unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import logging
from time import perf_counter
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ...core.models import AuditEvent, IdempotencyRecord
from ..extensions import extension_registry
from ..models import Opportunity, OpportunityLink, OrderPlan
from ..schemas.opportunities import (
    OrderPlanBulkFailureCode,
    OrderPlanBulkPreviewItem,
    OrderPlanBulkPreviewResponse,
    OrderPlanBulkStartItem,
    OrderPlanBulkStartResponse,
    OrderPlanBulkStatusCount,
    OrderPlanBulkSummary,
)
from .opportunity_integrity import (
    active_opportunity_predicate,
    authoritative_link_predicate,
)
from .opportunity_tracking import (
    HUMAN_TRACKING_ACTION,
    OpportunityTrackingError,
    _validate_human_name,
    set_tracking_status,
)

logger = logging.getLogger(__name__)

ORDER_PLAN_BULK_PREVIEW_SCHEMA_VERSION = "order-plan-bulk-preview-response.v1"
ORDER_PLAN_BULK_START_SCHEMA_VERSION = "order-plan-bulk-start-response.v1"
ORDER_PLAN_BULK_START_OPERATION = "order_plan_tracking_bulk_start"
ORDER_PLAN_BULK_AGGREGATE_TYPE = "order_plan_bulk_tracking"
# A fixed namespace makes the request UUID the one deterministic identity
# fence, independent of actor or selected owner.  The payload hash below then
# rejects reuse of that UUID for a different request.
ORDER_PLAN_BULK_RECEIPT_NAMESPACE = uuid5(
    NAMESPACE_URL, "https://bidops.invalid/idempotency/order-plan-bulk-start/v1"
)
_EXCLUDED_STATUSES = ("계속 추적", "보류", "종료")
_RECEIPT_PK_CONSTRAINTS = frozenset(
    {"idempotency_record_pkey", "pk_idempotency_record"}
)


class OrderPlanBulkTrackingError(RuntimeError):
    """A safe request-level failure for preview or bulk start."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 500,
        request_id: UUID | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(message)


@dataclass(frozen=True)
class BulkStartResult:
    """The validated response plus the exact JSON body used as the receipt."""

    response: OrderPlanBulkStartResponse
    snapshot: dict[str, Any]
    response_status: int = 200
    replayed: bool = False


class _OwnerFailure(Exception):
    """Internal savepoint failure with a safe item-level code."""

    def __init__(self, code: OrderPlanBulkFailureCode, status: str | None = None) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


def _is_receipt_pk_conflict(error: IntegrityError) -> bool:
    """Identify only the deterministic receipt primary-key collision.

    A winner lookup is safe only after the database has told us the conflict
    was the receipt PK.  Other unique/check/FK failures must remain
    infrastructure failures instead of being misreported as a replay.
    """

    original = error.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate is not None:
        if sqlstate != "23505":
            return False
        diagnostic = getattr(original, "diag", None)
        return getattr(diagnostic, "constraint_name", None) in _RECEIPT_PK_CONSTRAINTS

    # sqlite3.IntegrityError exposes only its stable constraint text.
    text = str(original).lower()
    return "unique constraint failed: idempotency_record.id" in text


def _normalize_plan_ids(values: list[int] | tuple[int, ...] | Any) -> list[int]:
    if not isinstance(values, (list, tuple)) or not values:
        raise OrderPlanBulkTrackingError(
            "invalid_request", "발주계획 선택이 올바르지 않습니다", status_code=422
        )
    normalized: set[int] = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise OrderPlanBulkTrackingError(
                "invalid_request", "발주계획 선택이 올바르지 않습니다", status_code=422
            )
        normalized.add(value)
    if not normalized:
        raise OrderPlanBulkTrackingError(
            "invalid_request", "발주계획 선택이 올바르지 않습니다", status_code=422
        )
    return sorted(normalized)


def _validate_actor(value: str | None, request_id: UUID | None = None) -> str:
    try:
        return _validate_human_name(value)
    except OpportunityTrackingError as error:
        status = 400 if error.code in {"actor_name_required", "actor_name_invalid"} else 422
        raise OrderPlanBulkTrackingError(
            error.code, str(error), status_code=status, request_id=request_id
        ) from error


def _validate_reason(value: str | None, request_id: UUID | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OrderPlanBulkTrackingError(
            "tracking_reason_required",
            "추적 상태를 선택한 이유가 필요합니다",
            status_code=422,
            request_id=request_id,
        )
    return value.strip()


def _canonical_hash(
    *, schema_version: str, request_id: UUID, plan_ids: list[int], reason: str, actor: str
) -> str:
    payload = {
        "schema_version": schema_version,
        "operation": ORDER_PLAN_BULK_START_OPERATION,
        "request_id": str(request_id),
        "order_plan_ids": plan_ids,
        "reason": reason,
        "actor": actor,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def deterministic_receipt_id(request_id: UUID) -> UUID:
    """Return the deterministic UUIDv5 fence for one bulk request UUID."""

    if not isinstance(request_id, UUID):
        raise OrderPlanBulkTrackingError(
            "invalid_request", "request_id가 올바르지 않습니다", status_code=422
        )
    return uuid5(
        ORDER_PLAN_BULK_RECEIPT_NAMESPACE,
        f"{ORDER_PLAN_BULK_START_OPERATION}:{request_id}",
    )


def _json_primitives(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return not isinstance(value, float) or value == value and value not in {
            float("inf"),
            float("-inf"),
        }
    if isinstance(value, list):
        return all(_json_primitives(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_primitives(item) for key, item in value.items())
    return False


def _receipt_error(request_id: UUID, message: str = "저장된 작업 결과를 확인할 수 없습니다") -> OrderPlanBulkTrackingError:
    return OrderPlanBulkTrackingError(
        "processing_failed", message, status_code=500, request_id=request_id
    )


def _record_identity(
    record: IdempotencyRecord,
    *,
    receipt_id: UUID,
    request_id: UUID,
) -> bool:
    return (
        record.id == receipt_id
        and record.operation == ORDER_PLAN_BULK_START_OPERATION
        and record.aggregate_type == ORDER_PLAN_BULK_AGGREGATE_TYPE
        and record.aggregate_id == str(request_id)
        and record.request_id == request_id
    )


def _replay_record(
    record: IdempotencyRecord,
    *,
    request_id: UUID,
    receipt_id: UUID,
    request_hash: str,
) -> BulkStartResult:
    if not _record_identity(record, receipt_id=receipt_id, request_id=request_id):
        raise _receipt_error(request_id)
    if record.request_sha256 != request_hash:
        raise OrderPlanBulkTrackingError(
            "idempotency_conflict",
            "같은 request_id가 다른 요청에 사용되었습니다",
            status_code=409,
            request_id=request_id,
        )
    if record.response_status != 200 or not isinstance(record.response_snapshot, Mapping):
        raise _receipt_error(request_id)
    snapshot = dict(record.response_snapshot)
    if not _json_primitives(snapshot):
        raise _receipt_error(request_id)
    # JSONB must contain the wire representation, not a Python UUID/datetime
    # that a permissive SQLAlchemy serializer happened to coerce.  The model
    # validation below checks the values; these guards enforce their JSON
    # primitive *types* before Pydantic can coerce them.
    if (
        not isinstance(snapshot.get("request_id"), str)
        or not isinstance(snapshot.get("completed_at"), str)
        or not isinstance(snapshot.get("items"), list)
    ):
        raise _receipt_error(request_id)
    for item in snapshot["items"]:
        if not isinstance(item, dict):
            raise _receipt_error(request_id)
        audit_id = item.get("audit_event_id")
        if audit_id is not None and not isinstance(audit_id, str):
            raise _receipt_error(request_id)
    try:
        response = OrderPlanBulkStartResponse.model_validate(snapshot)
    except Exception as error:
        raise _receipt_error(request_id) from error
    if response.request_id != request_id:
        raise _receipt_error(request_id)
    # Do not call model_dump here.  Validation is an integrity check only;
    # replay uses the exact JSON values and array order committed originally.
    return BulkStartResult(
        response=response,
        snapshot=snapshot,
        response_status=record.response_status,
        replayed=True,
    )


def _existing_receipt(
    session: Session,
    *,
    request_id: UUID,
    receipt_id: UUID,
    request_hash: str,
) -> BulkStartResult | None:
    record = session.get(IdempotencyRecord, receipt_id)
    if record is None:
        return None
    return _replay_record(
        record,
        request_id=request_id,
        receipt_id=receipt_id,
        request_hash=request_hash,
    )


def _ownership_snapshot(
    session: Session, plan_ids: list[int]
) -> tuple[set[int], dict[int, list[int]], dict[int, str | None]]:
    """Read plans and authoritative active owners in two set queries."""

    existing = set(
        session.scalars(select(OrderPlan.id).where(OrderPlan.id.in_(plan_ids))).all()
    )
    rows = session.execute(
        select(
            OpportunityLink.order_plan_id,
            OpportunityLink.opportunity_id,
            Opportunity.tracking_status,
        )
        .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
        .where(
            OpportunityLink.order_plan_id.in_(plan_ids),
            authoritative_link_predicate(OpportunityLink),
            active_opportunity_predicate(Opportunity),
        )
    ).all()
    owners: dict[int, list[int]] = defaultdict(list)
    statuses: dict[int, str | None] = {}
    for plan_id, opportunity_id, status in rows:
        if plan_id is None or opportunity_id is None:
            continue
        owners[int(plan_id)].append(int(opportunity_id))
        statuses[int(plan_id)] = status
    return existing, owners, statuses


def _status_counts(items: list[OrderPlanBulkPreviewItem | OrderPlanBulkStartItem]) -> dict[str, OrderPlanBulkStatusCount]:
    result: dict[str, OrderPlanBulkStatusCount] = {}
    for status in _EXCLUDED_STATUSES:
        matching = [
            item
            for item in items
            if (
                getattr(item, "eligibility", None) == "excluded"
                or getattr(item, "outcome", None) == "excluded"
            )
            and (
                getattr(item, "tracking_status", None) == status
                or getattr(item, "status_at_decision", None) == status
            )
        ]
        result[status] = OrderPlanBulkStatusCount(
            plan_count=len(matching),
            owner_count=len(
                {
                    item.opportunity_id
                    for item in matching
                    if item.opportunity_id is not None
                }
            ),
        )
    return result


def _log_receipt_event(
    event: str,
    *,
    request_id: UUID,
    snapshot: Mapping[str, Any] | None = None,
    duration_ms: float | None = None,
) -> None:
    """Emit an allowlisted operational event without actor/reason/error text."""

    summary = snapshot.get("summary") if isinstance(snapshot, Mapping) else None
    count: dict[str, int | None] = {
        "selected_plan_count": (
            summary.get("selected_plan_count")
            if isinstance(summary, Mapping)
            else None
        ),
        "succeeded_plan_count": (
            summary.get("succeeded_plan_count")
            if isinstance(summary, Mapping)
            else None
        ),
        "excluded_plan_count": (
            summary.get("excluded_plan_count")
            if isinstance(summary, Mapping)
            else None
        ),
        "failed_plan_count": (
            summary.get("failed_plan_count")
            if isinstance(summary, Mapping)
            else None
        ),
        "unique_owner_count": (
            summary.get("unique_owner_count")
            if isinstance(summary, Mapping)
            else None
        ),
        "succeeded_owner_count": (
            summary.get("succeeded_owner_count")
            if isinstance(summary, Mapping)
            else None
        ),
    }
    values: dict[str, Any] = {
        "event": event,
        "fence": str(request_id),
        "count": count,
        "duration_ms": duration_ms,
        "status": (
            "conflict"
            if event.endswith("conflict")
            else "replayed"
            if event.endswith("replayed")
            else "succeeded"
        ),
        **(
            {"error_code": "idempotency_conflict"}
            if event.endswith("conflict")
            else {}
        ),
    }
    if event.endswith("conflict"):
        logger.warning("bulk tracking request conflict", extra={"bidops": values})
    else:
        logger.info("bulk tracking receipt", extra={"bidops": values})


def preview_order_plan_tracking(
    session: Session, order_plan_ids: list[int] | tuple[int, ...]
) -> OrderPlanBulkPreviewResponse:
    """Return a read-only, set-based eligibility preview."""

    plan_ids = _normalize_plan_ids(order_plan_ids)
    try:
        existing, owners, statuses = _ownership_snapshot(session, plan_ids)
        items: list[OrderPlanBulkPreviewItem] = []
        owner_ids: set[int] = set()
        eligible_owner_ids: set[int] = set()
        for plan_id in plan_ids:
            owner_list = owners.get(plan_id, [])
            if plan_id not in existing:
                items.append(
                    OrderPlanBulkPreviewItem(
                        order_plan_id=plan_id,
                        opportunity_id=None,
                        tracking_status=None,
                        eligibility="failed",
                        code="order_plan_not_found",
                    )
                )
                continue
            if len(set(owner_list)) != 1:
                items.append(
                    OrderPlanBulkPreviewItem(
                        order_plan_id=plan_id,
                        opportunity_id=None,
                        tracking_status=None,
                        eligibility="failed",
                        code=("owning_opportunity_missing" if not owner_list else "ownership_conflict"),
                    )
                )
                continue
            owner_id = owner_list[0]
            status = statuses.get(plan_id)
            owner_ids.add(owner_id)
            if status == "미선택":
                eligible_owner_ids.add(owner_id)
                items.append(
                    OrderPlanBulkPreviewItem(
                        order_plan_id=plan_id,
                        opportunity_id=owner_id,
                        tracking_status=status,
                        eligibility="eligible",
                        code=None,
                    )
                )
            elif status in _EXCLUDED_STATUSES:
                items.append(
                    OrderPlanBulkPreviewItem(
                        order_plan_id=plan_id,
                        opportunity_id=owner_id,
                        tracking_status=status,
                        eligibility="excluded",
                        code=None,
                    )
                )
            else:
                items.append(
                    OrderPlanBulkPreviewItem(
                        order_plan_id=plan_id,
                        opportunity_id=owner_id,
                        tracking_status=status,
                        eligibility="failed",
                        code="processing_failed",
                    )
                )
        eligible_items = [item for item in items if item.eligibility == "eligible"]
        failed_items = [item for item in items if item.eligibility == "failed"]
        response = OrderPlanBulkPreviewResponse(
            schema_version=ORDER_PLAN_BULK_PREVIEW_SCHEMA_VERSION,
            selected_plan_count=len(plan_ids),
            unique_owner_count=len(owner_ids),
            eligible_plan_count=len(eligible_items),
            eligible_owner_count=len(eligible_owner_ids),
            excluded_by_status=_status_counts(items),
            failure_plan_count=len(failed_items),
            items=items,
        )
        return response
    except OrderPlanBulkTrackingError:
        raise
    except SQLAlchemyError as error:
        session.rollback()
        raise OrderPlanBulkTrackingError(
            "temporarily_unavailable",
            "사업기회 작업을 일시적으로 사용할 수 없습니다",
            status_code=503,
        ) from error


def _owner_items(
    *,
    plan_ids: list[int],
    owner_id: int | None,
    outcome: str,
    status: str | None,
    code: str | None = None,
    audit_event_id: UUID | None = None,
) -> dict[int, OrderPlanBulkStartItem]:
    return {
        plan_id: OrderPlanBulkStartItem(
            order_plan_id=plan_id,
            opportunity_id=owner_id,
            outcome=outcome,
            status_at_decision=status,
            code=code,
            audit_event_id=audit_event_id,
        )
        for plan_id in plan_ids
    }


def _failure_items(
    *, plan_ids: list[int], owner_id: int | None, status: str | None, code: OrderPlanBulkFailureCode
) -> dict[int, OrderPlanBulkStartItem]:
    return _owner_items(
        plan_ids=plan_ids,
        owner_id=owner_id,
        outcome="failed",
        status=status,
        code=code,
    )


def _post_commit_hooks(session: Session, owner_ids: list[int]) -> None:
    """Run each owner's extension hook in an isolated transaction."""

    if not owner_ids:
        return
    bind = session.get_bind()
    for owner_id in owner_ids:
        hook_session: Session | None = None
        try:
            hook_session = Session(bind=bind, expire_on_commit=False)
            extension_registry().tracking_decision_changed(hook_session, owner_id)
            hook_session.commit()
        except Exception:  # hooks are best-effort post-commit work
            if hook_session is not None:
                hook_session.rollback()
            logger.warning(
                "bulk tracking extension hook failed",
                extra={
                    "bidops": {
                        "event": "extension.tracking_decision_hook_failed",
                        "status": "failed",
                        "error_code": "processing_failed",
                    }
                },
            )
        finally:
            if hook_session is not None:
                hook_session.close()


def start_order_plan_tracking(
    session: Session,
    order_plan_ids: list[int] | tuple[int, ...],
    *,
    request_id: UUID,
    reason: str,
    selected_by: str,
) -> BulkStartResult:
    """Atomically start tracking for each currently-unselected owner.

    Owner writes share one final transaction, while each owner is protected by
    a nested savepoint.  The deterministic receipt row is inserted in that
    same transaction; only after its commit are extension hooks invoked.
    """

    started = perf_counter()
    plan_ids = _normalize_plan_ids(order_plan_ids)
    if not isinstance(request_id, UUID):
        raise OrderPlanBulkTrackingError(
            "invalid_request", "request_id가 올바르지 않습니다", status_code=422
        )
    actor = _validate_actor(selected_by, request_id)
    clean_reason = _validate_reason(reason, request_id)
    request_hash = _canonical_hash(
        schema_version="order-plan-bulk-start-request.v1",
        request_id=request_id,
        plan_ids=plan_ids,
        reason=clean_reason,
        actor=actor,
    )
    receipt_id = deterministic_receipt_id(request_id)

    try:
        existing = _existing_receipt(
            session,
            request_id=request_id,
            receipt_id=receipt_id,
            request_hash=request_hash,
        )
    except OrderPlanBulkTrackingError as error:
        if error.code == "idempotency_conflict":
            _log_receipt_event(
                "order_plan.bulk_tracking.conflict",
                request_id=request_id,
                duration_ms=round((perf_counter() - started) * 1000, 3),
            )
        raise
    except SQLAlchemyError as error:
        session.rollback()
        raise OrderPlanBulkTrackingError(
            "temporarily_unavailable",
            "사업기회 작업을 일시적으로 확인할 수 없습니다",
            status_code=503,
            request_id=request_id,
        ) from error
    if existing is not None:
        _log_receipt_event(
            "order_plan.bulk_tracking.replayed",
            request_id=request_id,
            snapshot=existing.snapshot,
            duration_ms=round((perf_counter() - started) * 1000, 3),
        )
        return existing

    try:
        plan_exists, owners, _initial_statuses = _ownership_snapshot(session, plan_ids)
        items_by_plan: dict[int, OrderPlanBulkStartItem] = {}
        owner_plans: dict[int, list[int]] = defaultdict(list)
        for plan_id in plan_ids:
            owner_list = owners.get(plan_id, [])
            if plan_id not in plan_exists:
                items_by_plan.update(
                    _failure_items(
                        plan_ids=[plan_id], owner_id=None, status=None, code="order_plan_not_found"
                    )
                )
            elif len(set(owner_list)) != 1:
                items_by_plan.update(
                    _failure_items(
                        plan_ids=[plan_id],
                        owner_id=None,
                        status=None,
                        code=("owning_opportunity_missing" if not owner_list else "ownership_conflict"),
                    )
                )
            else:
                owner_plans[owner_list[0]].append(plan_id)

        succeeded_owner_ids: list[int] = []
        for owner_id in sorted(owner_plans):
            plans_for_owner = owner_plans[owner_id]
            try:
                with session.begin_nested():
                    owner = session.scalar(
                        select(Opportunity)
                        .where(Opportunity.id == owner_id)
                        .execution_options(populate_existing=True)
                        .with_for_update()
                    )
                    if owner is None or owner.merged_into_opportunity_id is not None:
                        raise _OwnerFailure("owner_changed", None)

                    # Re-read authoritative links after the owner lock.  We do
                    # not follow a replacement owner discovered in this query.
                    # Lock only the link rows here.  A joined ``FOR UPDATE``
                    # would also lock every joined opportunity, including a
                    # replacement owner, potentially out of the globally
                    # ascending owner order.  The owner row itself was locked
                    # above; any merge that could move these links is therefore
                    # serialized and surfaced below as ``owner_changed``.
                    current_links = session.scalars(
                        select(OpportunityLink)
                        .where(
                            OpportunityLink.order_plan_id.in_(plans_for_owner),
                            authoritative_link_predicate(OpportunityLink),
                        )
                        .execution_options(populate_existing=True)
                        .with_for_update(of=OpportunityLink)
                    ).all()
                    current_owners: dict[int, set[int]] = defaultdict(set)
                    for link in current_links:
                        if link.order_plan_id is not None and link.opportunity_id is not None:
                            current_owners[int(link.order_plan_id)].add(int(link.opportunity_id))
                    if any(
                        current_owners.get(plan_id, set()) != {owner_id}
                        for plan_id in plans_for_owner
                    ):
                        raise _OwnerFailure("owner_changed", owner.tracking_status)

                    current_status = owner.tracking_status
                    if current_status in _EXCLUDED_STATUSES:
                        owner_result = _owner_items(
                            plan_ids=plans_for_owner,
                            owner_id=owner_id,
                            outcome="excluded",
                            status=current_status,
                        )
                    elif current_status != "미선택":
                        raise _OwnerFailure("processing_failed", current_status)
                    else:
                        selected_at = datetime.now(UTC)
                        set_tracking_status(
                            session,
                            owner_id,
                            status="계속 추적",
                            reason=clean_reason,
                            selected_by=actor,
                            selected_at=selected_at,
                            request_id=request_id,
                        )
                        audit = session.scalar(
                            select(AuditEvent)
                            .where(
                                AuditEvent.action == HUMAN_TRACKING_ACTION,
                                AuditEvent.aggregate_type == "opportunity",
                                AuditEvent.aggregate_id == str(owner_id),
                                AuditEvent.request_id == str(request_id),
                            )
                            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                            .limit(1)
                        )
                        if audit is None or audit.id is None:
                            raise RuntimeError("tracking audit was not created")
                        owner_result = _owner_items(
                            plan_ids=plans_for_owner,
                            owner_id=owner_id,
                            outcome="succeeded",
                            status="계속 추적",
                            audit_event_id=audit.id,
                        )
                items_by_plan.update(owner_result)
                if owner_result[plans_for_owner[0]].outcome == "succeeded":
                    succeeded_owner_ids.append(owner_id)
            except _OwnerFailure as failure:
                items_by_plan.update(
                    _failure_items(
                        plan_ids=plans_for_owner,
                        owner_id=owner_id,
                        status=failure.status,
                        code=failure.code,
                    )
                )
            except Exception:
                # The nested context has rolled back this owner's writes.  Do
                # not let one malformed owner poison the rest of the batch.
                items_by_plan.update(
                    _failure_items(
                        plan_ids=plans_for_owner,
                        owner_id=owner_id,
                        status=None,
                        code="processing_failed",
                    )
                )

        items = [items_by_plan[plan_id] for plan_id in plan_ids]
        excluded_items = [item for item in items if item.outcome == "excluded"]
        summary = OrderPlanBulkSummary(
            selected_plan_count=len(plan_ids),
            unique_owner_count=len(
                {item.opportunity_id for item in items if item.opportunity_id is not None}
            ),
            succeeded_plan_count=sum(item.outcome == "succeeded" for item in items),
            succeeded_owner_count=len(
                {
                    item.opportunity_id
                    for item in items
                    if item.outcome == "succeeded" and item.opportunity_id is not None
                }
            ),
            excluded_plan_count=len(excluded_items),
            excluded_by_status=_status_counts(items),
            failed_plan_count=sum(item.outcome == "failed" for item in items),
        )
        try:
            final_result = {
                "schema_version": ORDER_PLAN_BULK_START_SCHEMA_VERSION,
                "request_id": request_id,
                "completed_at": datetime.now(UTC),
                "items": items,
                "summary": summary,
            }
            response = OrderPlanBulkStartResponse.model_validate(final_result)
            snapshot = response.model_dump(mode="json")
            if not _json_primitives(snapshot):
                raise ValueError("receipt contains a non-JSON value")
        except Exception as error:
            session.rollback()
            raise _receipt_error(request_id) from error

        session.add(
            IdempotencyRecord(
                id=receipt_id,
                operation=ORDER_PLAN_BULK_START_OPERATION,
                aggregate_type=ORDER_PLAN_BULK_AGGREGATE_TYPE,
                aggregate_id=str(request_id),
                claimed_name=actor,
                request_id=request_id,
                request_sha256=request_hash,
                response_status=200,
                response_snapshot=snapshot,
            )
        )
        try:
            session.flush()
            session.commit()
        except IntegrityError as error:
            session.rollback()
            # Only the deterministic receipt PK collision is a replay race.
            # Other integrity failures (including unrelated unique/check/FK
            # constraints) must not be masked by an existing row lookup.
            if not _is_receipt_pk_conflict(error):
                raise OrderPlanBulkTrackingError(
                    "temporarily_unavailable",
                    "사업기회 작업을 일시적으로 확인할 수 없습니다",
                    status_code=503,
                    request_id=request_id,
                ) from error
            winner = session.get(IdempotencyRecord, receipt_id)
            if winner is None:
                raise _receipt_error(request_id) from error
            try:
                replay = _replay_record(
                    winner,
                    request_id=request_id,
                    receipt_id=receipt_id,
                    request_hash=request_hash,
                )
            except OrderPlanBulkTrackingError as replay_error:
                if replay_error.code == "idempotency_conflict":
                    _log_receipt_event(
                        "order_plan.bulk_tracking.conflict",
                        request_id=request_id,
                        duration_ms=round((perf_counter() - started) * 1000, 3),
                    )
                raise
            _log_receipt_event(
                "order_plan.bulk_tracking.replayed",
                request_id=request_id,
                snapshot=replay.snapshot,
                duration_ms=round((perf_counter() - started) * 1000, 3),
            )
            return replay
        except SQLAlchemyError as error:
            session.rollback()
            raise OrderPlanBulkTrackingError(
                "temporarily_unavailable",
                "사업기회 작업을 일시적으로 확인할 수 없습니다",
                status_code=503,
                request_id=request_id,
            ) from error
        except Exception as error:
            session.rollback()
            raise OrderPlanBulkTrackingError(
                "processing_failed",
                "사업기회 작업을 완료할 수 없습니다",
                status_code=500,
                request_id=request_id,
            ) from error
    except OrderPlanBulkTrackingError:
        raise
    except SQLAlchemyError as error:
        session.rollback()
        raise OrderPlanBulkTrackingError(
            "temporarily_unavailable",
            "사업기회 작업을 일시적으로 사용할 수 없습니다",
            status_code=503,
            request_id=request_id,
        ) from error

    result = BulkStartResult(response=response, snapshot=snapshot)
    _log_receipt_event(
        "order_plan.bulk_tracking.succeeded",
        request_id=request_id,
        snapshot=snapshot,
        duration_ms=round((perf_counter() - started) * 1000, 3),
    )
    _post_commit_hooks(session, succeeded_owner_ids)
    return result


__all__ = [
    "BulkStartResult",
    "ORDER_PLAN_BULK_AGGREGATE_TYPE",
    "ORDER_PLAN_BULK_PREVIEW_SCHEMA_VERSION",
    "ORDER_PLAN_BULK_RECEIPT_NAMESPACE",
    "ORDER_PLAN_BULK_START_OPERATION",
    "ORDER_PLAN_BULK_START_SCHEMA_VERSION",
    "OrderPlanBulkTrackingError",
    "deterministic_receipt_id",
    "preview_order_plan_tracking",
    "start_order_plan_tracking",
]
