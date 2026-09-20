"""PostgreSQL evidence for the order-plan bulk tracking-end service.

The harness, seeding helper and isolated-extension fixture are imported from
the bulk-start module so both wire versions are exercised against exactly the
same fixture data.  The start receipts must stay byte-identical, so this file
also freezes the start canonical hash and receipt UUID.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import AuditEvent, IdempotencyRecord
from app.lifecycle.models import Opportunity, OpportunityLink, OrderPlan
from app.lifecycle.schemas.opportunities import (
    ORDER_PLAN_BULK_END_MAX_SELECTION,
    OrderPlanBulkEndRequest,
    OrderPlanBulkStartRequest,
)
from app.lifecycle.services import order_plan_bulk_tracking as bulk
from tests.postgres import requires_postgres

# Fixtures and helpers are shared with the bulk-start evidence file.
from tests.lifecycle.test_order_plan_bulk_tracking import (  # noqa: F401
    _audit_count,
    _receipt_count,
    _seed,
    _start,
    isolated_extensions,
    pg_engine,
)


FROZEN_START_REQUEST_ID = UUID("11111111-2222-3333-4444-555555555555")
FROZEN_START_PLAN_IDS = [7, 11, 13]
FROZEN_START_REASON = "고정 사유"
FROZEN_START_ACTOR = "고정 담당자"
FROZEN_START_REQUEST_SHA256 = (
    "b39730f057a2fcaf0478ea804c1ed52ed04eb34146e9a523ce4bcad89d0c1d57"
)
FROZEN_START_RECEIPT_ID = UUID("46287900-0ba5-5620-95ee-77a16e92fa1f")


def _end(
    engine: Any,
    plan_ids: list[int],
    request_id,
    *,
    actor: str = "bulk-reviewer",
    reason: str = "공통 종료 사유",
):
    with Session(engine) as session:
        return bulk.end_order_plan_tracking(
            session,
            plan_ids,
            request_id=request_id,
            reason=reason,
            selected_by=actor,
        )


def _orphan_plan(engine: Any, *, unty_no: str) -> int:
    """Insert one order plan that no opportunity link owns."""

    with Session(engine, expire_on_commit=False) as session:
        plan = OrderPlan(order_plan_unty_no=unty_no, title="소유 사업기회 없는 발주계획")
        session.add(plan)
        session.flush()
        session.commit()
        return plan.id


def _opportunity_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(Opportunity)))


# ---------------------------------------------------------------------------
# (a) unselected owners move to 종료 with one audited human decision each


@requires_postgres
def test_unselected_owners_are_ended_with_one_audit_each(pg_engine):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",) * 3, prefix="end-basic")
    result = _end(pg_engine, plan_ids, uuid4(), actor="종료 담당자", reason="검토 종료")

    assert result.replayed is False
    assert result.response.schema_version == "order-plan-bulk-end-response.v1"
    assert [item.order_plan_id for item in result.response.items] == sorted(plan_ids)
    assert {item.outcome for item in result.response.items} == {"succeeded"}
    assert {item.status_at_decision for item in result.response.items} == {"종료"}
    assert result.response.summary.succeeded_plan_count == 3
    assert result.response.summary.succeeded_owner_count == 3
    assert result.response.summary.excluded_plan_count == 0
    assert result.response.summary.failed_plan_count == 0
    assert result.snapshot["schema_version"] == "order-plan-bulk-end-response.v1"

    with Session(pg_engine) as session:
        for owner_id in owner_ids:
            owner = session.get(Opportunity, owner_id)
            assert owner is not None
            assert owner.tracking_status == "종료"
            assert owner.tracking_reason == "검토 종료"
            assert owner.tracking_selected_by == "종료 담당자"
            assert owner.tracking_selected_at is not None
            audits = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.aggregate_type == "opportunity",
                    AuditEvent.aggregate_id == str(owner_id),
                )
            ).all()
            assert len(audits) == 1
            audit = audits[0]
            assert audit.actor_kind == "human"
            assert audit.claimed_name == "종료 담당자"
            assert audit.action == "opportunity.tracking_status.changed"
            assert audit.safe_metadata["previous_tracking_status"] == "미선택"
            assert audit.safe_metadata["tracking_status"] == "종료"
            assert audit.safe_metadata["reason"] == "검토 종료"
        assert _audit_count(session) == 3
        assert _receipt_count(session) == 1
        record = session.scalar(select(IdempotencyRecord))
        assert record is not None
        assert record.operation == "order_plan_tracking_bulk_end"
        assert len(record.operation) <= 128


@requires_postgres
def test_shared_owner_end_is_decided_once_and_fanned_out(pg_engine):
    plan_ids, owner_ids = _seed(
        pg_engine, ("미선택",), plans_per_owner=2, prefix="end-fanout"
    )
    result = _end(pg_engine, list(reversed(plan_ids)) + [plan_ids[0]], uuid4())

    assert [item.order_plan_id for item in result.response.items] == sorted(plan_ids)
    assert len({item.audit_event_id for item in result.response.items}) == 1
    assert result.response.summary.succeeded_plan_count == 2
    assert result.response.summary.succeeded_owner_count == 1
    with Session(pg_engine) as session:
        assert _audit_count(session) == 1
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "종료"


# ---------------------------------------------------------------------------
# (b) mixed selection excludes every already-decided owner by status


@requires_postgres
def test_mixed_selection_excludes_each_decided_status(pg_engine):
    plan_ids, owner_ids = _seed(
        pg_engine, ("미선택", "계속 추적", "보류", "종료"), prefix="end-mixed"
    )
    with Session(pg_engine) as session:
        before = [
            (
                owner.tracking_status,
                owner.tracking_reason,
                owner.tracking_selected_by,
                owner.tracking_selected_at,
            )
            for owner in (session.get(Opportunity, pk) for pk in owner_ids[1:])
        ]

    result = _end(pg_engine, plan_ids, uuid4())
    items = {item.order_plan_id: item for item in result.response.items}
    summary = result.response.summary

    assert items[plan_ids[0]].outcome == "succeeded"
    assert items[plan_ids[0]].status_at_decision == "종료"
    assert summary.succeeded_plan_count == 1
    assert summary.excluded_plan_count == 3
    assert summary.failed_plan_count == 0
    for index, status in enumerate(("계속 추적", "보류", "종료"), start=1):
        assert items[plan_ids[index]].outcome == "excluded"
        assert items[plan_ids[index]].status_at_decision == status
        assert items[plan_ids[index]].audit_event_id is None
        assert summary.excluded_by_status[status].plan_count == 1
        assert summary.excluded_by_status[status].owner_count == 1

    with Session(pg_engine) as session:
        after = [
            (
                owner.tracking_status,
                owner.tracking_reason,
                owner.tracking_selected_by,
                owner.tracking_selected_at,
            )
            for owner in (session.get(Opportunity, pk) for pk in owner_ids[1:])
        ]
        assert after == before
        assert _audit_count(session) == 1


# ---------------------------------------------------------------------------
# (c) a plan without an authoritative owner never creates an opportunity


@requires_postgres
def test_missing_owner_fails_without_creating_an_opportunity(pg_engine):
    plan_ids, _owner_ids = _seed(pg_engine, ("미선택",), prefix="end-orphan")
    orphan_id = _orphan_plan(pg_engine, unty_no="end-orphan-no-owner")
    with Session(pg_engine) as session:
        before_opportunities = _opportunity_count(session)
        before_links = int(
            session.scalar(select(func.count()).select_from(OpportunityLink))
        )

    result = _end(pg_engine, [orphan_id, plan_ids[0], 999999], uuid4())
    items = {item.order_plan_id: item for item in result.response.items}

    assert items[orphan_id].outcome == "failed"
    assert items[orphan_id].code == "owning_opportunity_missing"
    assert items[orphan_id].opportunity_id is None
    assert items[orphan_id].audit_event_id is None
    assert items[999999].code == "order_plan_not_found"
    assert items[plan_ids[0]].outcome == "succeeded"
    assert result.response.summary.failed_plan_count == 2

    with Session(pg_engine) as session:
        assert _opportunity_count(session) == before_opportunities
        assert int(
            session.scalar(select(func.count()).select_from(OpportunityLink))
        ) == before_links


# ---------------------------------------------------------------------------
# (d)(e) idempotency fence


@requires_postgres
def test_same_request_and_payload_replays_the_stored_receipt(pg_engine):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), prefix="end-replay")
    request_id = uuid4()
    first = _end(pg_engine, plan_ids, request_id)
    with Session(pg_engine) as session:
        audits_after_first = _audit_count(session)
        stored = session.get(
            IdempotencyRecord,
            bulk.deterministic_receipt_id(request_id, bulk.ORDER_PLAN_BULK_END_OPERATION),
        )
        assert stored is not None
        assert stored.response_snapshot == first.snapshot

    replay = _end(pg_engine, list(reversed(plan_ids)), request_id)
    assert replay.replayed is True
    assert replay.snapshot == first.snapshot
    with Session(pg_engine) as session:
        assert _audit_count(session) == audits_after_first
        assert _receipt_count(session) == 1
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "종료"


@requires_postgres
@pytest.mark.parametrize("change", ["actor", "reason", "ids"])
def test_same_request_id_with_a_different_payload_conflicts(change, pg_engine):
    plan_ids, _owner_ids = _seed(
        pg_engine, ("미선택", "미선택"), prefix=f"end-conflict-{change}"
    )
    request_id = uuid4()
    _end(pg_engine, [plan_ids[0]], request_id)
    with Session(pg_engine) as session:
        before = _audit_count(session)

    kwargs: dict[str, Any] = {}
    selected = [plan_ids[0]]
    if change == "actor":
        kwargs["actor"] = "다른 담당자"
    elif change == "reason":
        kwargs["reason"] = "다른 종료 사유"
    else:
        selected = [plan_ids[1]]

    with pytest.raises(bulk.OrderPlanBulkTrackingError) as raised:
        _end(pg_engine, selected, request_id, **kwargs)
    assert raised.value.code == "idempotency_conflict"
    assert raised.value.status_code == 409
    with Session(pg_engine) as session:
        assert _audit_count(session) == before
        assert _receipt_count(session) == 1


# ---------------------------------------------------------------------------
# (f) the bulk-end selection cap is a request-schema constraint


def test_bulk_end_request_caps_the_selection_at_200():
    assert ORDER_PLAN_BULK_END_MAX_SELECTION == 200

    accepted = OrderPlanBulkEndRequest(
        schema_version="order-plan-bulk-end-request.v1",
        request_id=uuid4(),
        order_plan_ids=list(range(1, ORDER_PLAN_BULK_END_MAX_SELECTION + 1)),
        reason="상한 경계",
    )
    assert len(accepted.order_plan_ids) == ORDER_PLAN_BULK_END_MAX_SELECTION

    with pytest.raises(ValidationError) as raised:
        OrderPlanBulkEndRequest(
            schema_version="order-plan-bulk-end-request.v1",
            request_id=uuid4(),
            order_plan_ids=list(range(1, ORDER_PLAN_BULK_END_MAX_SELECTION + 2)),
            reason="상한 초과",
        )
    errors = raised.value.errors()
    assert [error["type"] for error in errors] == ["too_long"]
    assert errors[0]["loc"] == ("order_plan_ids",)


def test_bulk_start_request_keeps_its_v1_contract_without_a_cap():
    """The v1 start contract must not gain a new rejection."""

    request = OrderPlanBulkStartRequest(
        schema_version="order-plan-bulk-start-request.v1",
        request_id=uuid4(),
        order_plan_ids=list(range(1, ORDER_PLAN_BULK_END_MAX_SELECTION + 2)),
        reason="상한 없음",
    )
    assert len(request.order_plan_ids) == ORDER_PLAN_BULK_END_MAX_SELECTION + 1


# ---------------------------------------------------------------------------
# (g) actor and reason validation is shared with bulk start


@requires_postgres
@pytest.mark.parametrize(
    "actor,reason,code,status_code",
    [
        (None, "사유", "actor_name_required", 400),
        ("   ", "사유", "actor_name_required", 400),
        ("system", "사유", "actor_name_invalid", 400),
        ("담당자", "   ", "tracking_reason_required", 422),
    ],
)
def test_actor_and_reason_validation_matches_bulk_start(
    actor, reason, code, status_code, pg_engine
):
    plan_ids, _owner_ids = _seed(pg_engine, ("미선택",), prefix=f"end-validate-{code}")
    for operation in (bulk.start_order_plan_tracking, bulk.end_order_plan_tracking):
        with Session(pg_engine) as session:
            with pytest.raises(bulk.OrderPlanBulkTrackingError) as raised:
                operation(
                    session,
                    plan_ids,
                    request_id=uuid4(),
                    reason=reason,
                    selected_by=actor,
                )
        assert raised.value.code == code
        assert raised.value.status_code == status_code
    with Session(pg_engine) as session:
        assert _audit_count(session) == 0
        assert _receipt_count(session) == 0


# ---------------------------------------------------------------------------
# (h) the two operations never share a receipt


@requires_postgres
def test_start_and_end_receipts_do_not_interfere_for_one_request_id(pg_engine):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택", "미선택"), prefix="end-shared-key")
    request_id = uuid4()

    started = _start(pg_engine, [plan_ids[0]], request_id)
    ended = _end(pg_engine, [plan_ids[1]], request_id)

    assert started.replayed is False and ended.replayed is False
    assert started.snapshot["schema_version"] == "order-plan-bulk-start-response.v1"
    assert ended.snapshot["schema_version"] == "order-plan-bulk-end-response.v1"

    start_receipt = bulk.deterministic_receipt_id(request_id)
    end_receipt = bulk.deterministic_receipt_id(
        request_id, bulk.ORDER_PLAN_BULK_END_OPERATION
    )
    assert start_receipt != end_receipt

    with Session(pg_engine) as session:
        assert _receipt_count(session) == 2
        assert session.get(IdempotencyRecord, start_receipt).operation == (
            "order_plan_tracking_bulk_start"
        )
        assert session.get(IdempotencyRecord, end_receipt).operation == (
            "order_plan_tracking_bulk_end"
        )
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "계속 추적"
        assert session.get(Opportunity, owner_ids[1]).tracking_status == "종료"

    # Each operation still replays only its own receipt.
    assert _start(pg_engine, [plan_ids[0]], request_id).snapshot == started.snapshot
    assert _end(pg_engine, [plan_ids[1]], request_id).snapshot == ended.snapshot


# ---------------------------------------------------------------------------
# (i) the start fence values are frozen by this change


def test_bulk_start_canonical_hash_and_receipt_id_are_unchanged():
    assert (
        bulk._canonical_hash(
            schema_version="order-plan-bulk-start-request.v1",
            request_id=FROZEN_START_REQUEST_ID,
            plan_ids=FROZEN_START_PLAN_IDS,
            reason=FROZEN_START_REASON,
            actor=FROZEN_START_ACTOR,
        )
        == FROZEN_START_REQUEST_SHA256
    )
    assert bulk.deterministic_receipt_id(FROZEN_START_REQUEST_ID) == FROZEN_START_RECEIPT_ID


def test_bulk_end_fence_values_differ_from_bulk_start():
    end_hash = bulk._canonical_hash(
        schema_version="order-plan-bulk-end-request.v1",
        request_id=FROZEN_START_REQUEST_ID,
        plan_ids=FROZEN_START_PLAN_IDS,
        reason=FROZEN_START_REASON,
        actor=FROZEN_START_ACTOR,
        operation=bulk.ORDER_PLAN_BULK_END_OPERATION,
    )
    assert end_hash != FROZEN_START_REQUEST_SHA256
    assert (
        bulk.deterministic_receipt_id(
            FROZEN_START_REQUEST_ID, bulk.ORDER_PLAN_BULK_END_OPERATION
        )
        != FROZEN_START_RECEIPT_ID
    )
