"""PostgreSQL evidence for the order-plan bulk tracking service.

Every test uses the disposable PostgreSQL 17 migration harness.  In
particular, SQLite is not used for lock ordering, JSONB receipt, or concurrent
request claims.
"""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
import logging
from threading import Barrier, Event, Thread, get_ident
from time import perf_counter
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.models import AuditEvent, IdempotencyRecord
from app.lifecycle.extensions import (
    extension_registry,
    reset_extension_registry,
    restore_extension_registry,
)
from app.lifecycle.models import Opportunity, OpportunityLink, OrderPlan
from app.lifecycle.services import order_plan_bulk_tracking as bulk
from app.lifecycle.services.opportunity_integrity import merge_opportunities
from app.lifecycle.services.opportunity_tracking import set_tracking_status
from tests.postgres import migrated_engine, requires_postgres


pytestmark = requires_postgres


# ---------------------------------------------------------------------------
# Fixture and small database helpers


def _seed(
    engine: Any,
    statuses: tuple[str, ...] = ("미선택",),
    *,
    plans_per_owner: int = 1,
    prefix: str = "bulk",
) -> tuple[list[int], list[int]]:
    """Create one authoritative order-plan link per plan.

    ``plans_per_owner`` is used by fan-out and scale tests.  All rows are
    inserted in one transaction so IDs and owner order are deterministic.
    """

    owners: list[Opportunity] = []
    plans: list[OrderPlan] = []
    links: list[OpportunityLink] = []
    selected_at = datetime(2026, 9, 1, 1, 2, 3, 123456, tzinfo=UTC)
    with Session(engine, expire_on_commit=False) as session:
        for owner_index, status in enumerate(statuses):
            owner = Opportunity(first_registered_stage="order_plan", tracking_status=status)
            if status != "미선택":
                owner.tracking_reason = f"기존 {status} 판단"
                owner.tracking_selected_by = "기존 담당자"
                owner.tracking_selected_at = selected_at
            owners.append(owner)
            for plan_index in range(plans_per_owner):
                plan = OrderPlan(
                    order_plan_unty_no=f"{prefix}-{owner_index}-{plan_index}",
                    title=f"테스트 발주계획 {owner_index}-{plan_index}",
                )
                plans.append(plan)
                links.append(
                    OpportunityLink(
                        opportunity=owner,
                        order_plan=plan,
                        stage="order_plan",
                        link_type="official",
                        status="확정",
                        evidence_external_no=plan.order_plan_unty_no,
                    )
                )
        session.add_all([*owners, *plans, *links])
        session.flush()
        session.commit()
    return [plan.id for plan in plans], [owner.id for owner in owners]


def _audit_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(AuditEvent)))


def _receipt_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(IdempotencyRecord)))


def _start(
    engine: Any,
    plan_ids: list[int],
    request_id,
    *,
    actor: str = "bulk-reviewer",
    reason: str = "공통 추적 사유",
):
    with Session(engine) as session:
        return bulk.start_order_plan_tracking(
            session,
            plan_ids,
            request_id=request_id,
            reason=reason,
            selected_by=actor,
        )


@pytest.fixture
def pg_engine():
    with migrated_engine() as engine:
        yield engine


@pytest.fixture(autouse=True)
def isolated_extensions():
    """Keep unrelated screening/deep-review hooks out of service tests."""

    original = extension_registry()
    reset_extension_registry()
    try:
        yield
    finally:
        restore_extension_registry(original)


# ---------------------------------------------------------------------------
# Basic state machine, ownership and savepoints


def test_preview_is_set_based_read_only_and_reports_statuses(pg_engine):
    plan_ids, _ = _seed(
        pg_engine,
        ("미선택", "계속 추적", "보류", "종료"),
        prefix="preview",
    )
    with Session(pg_engine) as session:
        before = (_audit_count(session), _receipt_count(session))
        preview = bulk.preview_order_plan_tracking(session, plan_ids + [999999])
        assert preview.selected_plan_count == 5
        assert preview.eligible_plan_count == 1
        assert preview.eligible_owner_count == 1
        assert preview.failure_plan_count == 1
        assert preview.unique_owner_count == 4
        assert preview.excluded_by_status["계속 추적"].plan_count == 1
        assert preview.excluded_by_status["보류"].plan_count == 1
        assert preview.excluded_by_status["종료"].plan_count == 1
        assert (_audit_count(session), _receipt_count(session)) == before


def test_shared_owner_is_decided_once_and_fanned_out(pg_engine):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), plans_per_owner=2, prefix="fanout")
    request_id = uuid4()
    result = _start(pg_engine, list(reversed(plan_ids)) + [plan_ids[0]], request_id)
    assert result.replayed is False
    assert [item.order_plan_id for item in result.response.items] == sorted(plan_ids)
    assert {item.outcome for item in result.response.items} == {"succeeded"}
    assert len({item.audit_event_id for item in result.response.items}) == 1
    assert result.response.summary.succeeded_plan_count == 2
    assert result.response.summary.succeeded_owner_count == 1
    with Session(pg_engine) as session:
        audits = session.scalars(
            select(AuditEvent).where(
                AuditEvent.aggregate_type == "opportunity",
                AuditEvent.aggregate_id == str(owner_ids[0]),
            )
        ).all()
        assert len(audits) == 1
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "계속 추적"


@pytest.mark.parametrize("failure_mode", ["runtime", "sql"])
def test_owner_savepoint_error_does_not_rollback_other_owner(
    failure_mode, monkeypatch, pg_engine
):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택", "미선택"), prefix="savepoint")
    original = bulk.set_tracking_status

    def fail_first(session, opportunity, **kwargs):
        if opportunity == owner_ids[0]:
            if failure_mode == "runtime":
                raise RuntimeError("isolated owner failure")
            original(session, opportunity, **kwargs)
            # Force the PostgreSQL transaction into an aborted state after the
            # decision and audit have been staged.  The nested savepoint must
            # roll both writes back before the next owner is processed.
            session.execute(text("SELECT 1 / 0"))
        return original(session, opportunity, **kwargs)

    monkeypatch.setattr(bulk, "set_tracking_status", fail_first)
    result = _start(pg_engine, plan_ids, uuid4())
    by_plan = {item.order_plan_id: item for item in result.response.items}
    assert by_plan[plan_ids[0]].outcome == "failed"
    assert by_plan[plan_ids[0]].code == "processing_failed"
    assert by_plan[plan_ids[1]].outcome == "succeeded"
    with Session(pg_engine) as session:
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "미선택"
        assert session.get(Opportunity, owner_ids[1]).tracking_status == "계속 추적"
        assert _audit_count(session) == 1
        assert _receipt_count(session) == 1


def test_merged_owner_is_fail_closed_as_owner_changed(monkeypatch, pg_engine):
    primary_id = _seed(pg_engine, ("미선택",), prefix="merge-primary")[1][0]
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), prefix="merge")
    original = bulk._ownership_snapshot
    merged = False

    def snapshot_then_merge(session, selected_ids):
        nonlocal merged
        value = original(session, selected_ids)
        if not merged:
            merged = True
            with Session(pg_engine) as merger:
                primary = merger.get(Opportunity, primary_id)
                secondary = merger.get(Opportunity, owner_ids[0])
                assert primary is not None and secondary is not None
                merge_opportunities(merger, [primary, secondary])
                merger.commit()
        return value

    monkeypatch.setattr(bulk, "_ownership_snapshot", snapshot_then_merge)
    result = _start(pg_engine, plan_ids, uuid4())
    item = result.response.items[0]
    assert item.outcome == "failed"
    assert item.code == "owner_changed"
    with Session(pg_engine) as session:
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "미선택"
        assert _audit_count(session) == 0
        assert _receipt_count(session) == 1


def test_changed_authoritative_link_is_fail_closed_without_following_replacement(
    monkeypatch, pg_engine
):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), prefix="changed-owner")
    with Session(pg_engine) as session:
        replacement = Opportunity(
            first_registered_stage="order_plan",
            tracking_status="미선택",
        )
        session.add(replacement)
        session.flush()
        replacement_id = replacement.id
        session.commit()

    original = bulk._ownership_snapshot
    changed = False

    def snapshot_then_change_link(session, selected_ids):
        nonlocal changed
        value = original(session, selected_ids)
        if not changed:
            changed = True
            with Session(pg_engine) as mover:
                link = mover.scalar(
                    select(OpportunityLink).where(
                        OpportunityLink.order_plan_id == plan_ids[0]
                    )
                )
                assert link is not None
                link.opportunity_id = replacement_id
                mover.commit()
        return value

    monkeypatch.setattr(bulk, "_ownership_snapshot", snapshot_then_change_link)
    result = _start(pg_engine, plan_ids, uuid4())
    item = result.response.items[0]
    assert item.outcome == "failed"
    assert item.code == "owner_changed"
    assert item.opportunity_id == owner_ids[0]
    with Session(pg_engine) as session:
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "미선택"
        assert session.get(Opportunity, replacement_id).tracking_status == "미선택"
        assert _audit_count(session) == 0


# ---------------------------------------------------------------------------
# Explicit cross-connection lock interleavings


@pytest.mark.parametrize("patch_status", ["계속 추적", "보류", "종료"])
def test_patch_locks_and_commits_before_bulk_fresh_read_excludes(
    patch_status, pg_engine
):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), prefix="patch-first")
    owner_id = owner_ids[0]
    request_id = uuid4()
    ready = Event()
    bulk_lock_requested = Event()
    allow_patch_commit = Event()
    barrier = Barrier(3)
    result: list[Any] = []
    errors: list[BaseException] = []
    bulk_thread_ident: list[int] = []
    connection_ids: list[int] = []

    def observe_bulk_lock_request(*_args) -> None:
        if bulk_thread_ident and get_ident() == bulk_thread_ident[0]:
            if "FOR UPDATE" in _args[2].upper():
                bulk_lock_requested.set()

    event.listen(pg_engine, "before_cursor_execute", observe_bulk_lock_request)

    def patch_writer() -> None:
        try:
            with Session(pg_engine) as session:
                connection_ids.append(id(session.connection().connection))
                owner = session.scalar(
                    select(Opportunity).where(Opportunity.id == owner_id).with_for_update()
                )
                assert owner is not None
                ready.set()
                barrier.wait(timeout=10)
                assert allow_patch_commit.wait(10)
                set_tracking_status(
                    session,
                    owner_id,
                    status=patch_status,
                    reason=f"PATCH 먼저 {patch_status} 확정",
                    selected_by="patch-reviewer",
                    selected_at=datetime.now(UTC),
                )
                session.commit()
        except BaseException as error:  # report thread failures in the test
            errors.append(error)

    def bulk_writer() -> None:
        try:
            ready.wait(10)
            barrier.wait(timeout=10)
            bulk_thread_ident.append(get_ident())
            with Session(pg_engine) as session:
                connection_ids.append(id(session.connection().connection))
                result.append(
                    bulk.start_order_plan_tracking(
                        session,
                        plan_ids,
                        request_id=request_id,
                        reason="bulk reason",
                        selected_by="bulk-reviewer",
                    )
                )
        except BaseException as error:
            errors.append(error)

    patch_thread = Thread(target=patch_writer)
    bulk_thread = Thread(target=bulk_writer)
    patch_thread.start()
    bulk_thread.start()
    assert ready.wait(10)
    barrier.wait(timeout=10)
    assert bulk_lock_requested.wait(10)
    allow_patch_commit.set()
    patch_thread.join(timeout=20)
    bulk_thread.join(timeout=20)
    event.remove(pg_engine, "before_cursor_execute", observe_bulk_lock_request)
    assert not patch_thread.is_alive() and not bulk_thread.is_alive()
    assert not errors
    assert len(set(connection_ids)) == 2
    assert len(result) == 1
    assert result[0].response.items[0].outcome == "excluded"
    assert result[0].response.items[0].status_at_decision == patch_status
    with Session(pg_engine) as session:
        assert session.get(Opportunity, owner_id).tracking_status == patch_status
        assert _audit_count(session) == 1


@pytest.mark.parametrize("patch_status", ["계속 추적", "보류", "종료"])
def test_bulk_locks_and_commits_before_waiting_patch_same_status_reselection(
    patch_status, monkeypatch, pg_engine
):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), prefix="bulk-first")
    owner_id = owner_ids[0]
    request_id = uuid4()
    original = bulk.set_tracking_status
    bulk_locked = Event()
    patch_attempted = Event()
    patch_lock_requested = Event()
    barrier = Barrier(2)
    bulk_result: list[Any] = []
    errors: list[BaseException] = []
    patch_thread_ident: list[int] = []
    connection_ids: list[int] = []

    def observe_patch_lock_request(*_args) -> None:
        if patch_thread_ident and get_ident() == patch_thread_ident[0]:
            if "FOR UPDATE" in _args[2].upper():
                patch_lock_requested.set()

    event.listen(pg_engine, "before_cursor_execute", observe_patch_lock_request)

    def hold_bulk_lock(session, opportunity, **kwargs):
        value = original(session, opportunity, **kwargs)
        bulk_locked.set()
        assert patch_attempted.wait(10)
        assert patch_lock_requested.wait(10)
        return value

    monkeypatch.setattr(bulk, "set_tracking_status", hold_bulk_lock)

    def bulk_writer() -> None:
        try:
            barrier.wait(timeout=10)
            with Session(pg_engine) as session:
                connection_ids.append(id(session.connection().connection))
                bulk_result.append(
                    bulk.start_order_plan_tracking(
                        session,
                        plan_ids,
                        request_id=request_id,
                        reason="bulk first",
                        selected_by="bulk-reviewer",
                    )
                )
        except BaseException as error:
            errors.append(error)

    def patch_writer() -> None:
        try:
            barrier.wait(timeout=10)
            assert bulk_locked.wait(10)
            patch_thread_ident.append(get_ident())
            with Session(pg_engine) as session:
                connection_ids.append(id(session.connection().connection))
                patch_attempted.set()
                set_tracking_status(
                    session,
                    owner_id,
                    status=patch_status,
                    reason=f"사람이 {patch_status} 상태를 다시 확인",
                    selected_by="patch-reviewer",
                    selected_at=datetime.now(UTC),
                )
                session.commit()
        except BaseException as error:
            errors.append(error)

    bulk_thread = Thread(target=bulk_writer)
    patch_thread = Thread(target=patch_writer)
    bulk_thread.start()
    patch_thread.start()
    bulk_thread.join(timeout=20)
    patch_thread.join(timeout=20)
    event.remove(pg_engine, "before_cursor_execute", observe_patch_lock_request)
    assert not bulk_thread.is_alive() and not patch_thread.is_alive()
    assert not errors
    assert len(set(connection_ids)) == 2
    assert len(bulk_result) == 1
    assert bulk_result[0].response.items[0].outcome == "succeeded"
    with Session(pg_engine) as session:
        audits = session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "opportunity.tracking_status.changed",
                AuditEvent.aggregate_id == str(owner_id),
            )
        ).all()
        assert len(audits) == 2
        assert session.get(Opportunity, owner_id).tracking_selected_by == "patch-reviewer"


# ---------------------------------------------------------------------------
# Deterministic receipt fence and concurrent requests


@pytest.mark.parametrize(
    "variant", ["identical", "different_actor", "different_reason", "different_ids"]
)
def test_same_key_concurrent_requests_have_one_winner_and_rollback_loser(
    variant: str, pg_engine
):
    seed_statuses = ("미선택", "미선택") if variant == "different_ids" else ("미선택",)
    plan_ids, owner_ids = _seed(
        pg_engine, seed_statuses, prefix=f"concurrent-{variant}"
    )
    request_id = uuid4()
    barrier = Barrier(2)
    values = [
        ("bulk-reviewer", "same reason"),
        (
            "bulk-reviewer" if variant != "different_actor" else "other-reviewer",
            "same reason" if variant != "different_reason" else "other reason",
        ),
    ]
    successes: list[Any] = []
    failures: list[BaseException] = []

    def invoke(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            with Session(pg_engine) as session:
                selected_ids = (
                    [plan_ids[index]]
                    if variant == "different_ids"
                    else plan_ids
                )
                value = bulk.start_order_plan_tracking(
                    session,
                    selected_ids,
                    request_id=request_id,
                    reason=values[index][1],
                    selected_by=values[index][0],
                )
                successes.append(value)
        except BaseException as error:
            failures.append(error)

    threads = [Thread(target=invoke, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert all(not thread.is_alive() for thread in threads)
    assert len(successes) == (2 if variant == "identical" else 1)
    if variant == "identical":
        assert sorted(result.replayed for result in successes) == [False, True]
    else:
        assert len(failures) == 1
        assert isinstance(failures[0], bulk.OrderPlanBulkTrackingError)
        assert failures[0].code == "idempotency_conflict"
    with Session(pg_engine) as session:
        assert _audit_count(session) == 1
        assert _receipt_count(session) == 1
        if variant == "different_ids":
            statuses = [
                session.get(Opportunity, owner_id).tracking_status
                for owner_id in owner_ids
            ]
            assert statuses.count("계속 추적") == 1
            assert statuses.count("미선택") == 1
        else:
            assert session.get(Opportunity, owner_ids[0]).tracking_status == "계속 추적"


def test_receipt_integrity_error_requires_actual_receipt_pk_constraint():
    receipt_error = IntegrityError(
        "duplicate",
        {},
        SimpleNamespace(
            sqlstate="23505",
            diag=SimpleNamespace(constraint_name="idempotency_record_pkey"),
        ),
    )
    unrelated_pg_error = IntegrityError(
        "duplicate",
        {},
        SimpleNamespace(
            sqlstate="23505",
            diag=SimpleNamespace(constraint_name="uq_order_plan_unty_no"),
        ),
    )
    unrelated_sqlite_error = IntegrityError(
        "duplicate",
        {},
        sqlite3.IntegrityError(
            "UNIQUE constraint failed: order_plan.order_plan_unty_no"
        ),
    )
    assert bulk._is_receipt_pk_conflict(receipt_error)
    assert not bulk._is_receipt_pk_conflict(unrelated_pg_error)
    assert not bulk._is_receipt_pk_conflict(unrelated_sqlite_error)


def test_unrelated_integrity_error_does_not_replay_existing_receipt(
    monkeypatch, pg_engine
):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), prefix="unrelated-integrity")
    unrelated = SimpleNamespace(
        sqlstate="23505",
        diag=SimpleNamespace(constraint_name="uq_unrelated_constraint"),
    )
    with Session(pg_engine) as session:
        original_flush = session.flush

        def fail_receipt_flush(*args, **kwargs):
            if any(isinstance(value, IdempotencyRecord) for value in session.new):
                raise IntegrityError("duplicate unrelated", {}, unrelated)
            return original_flush(*args, **kwargs)

        monkeypatch.setattr(session, "flush", fail_receipt_flush)
        with pytest.raises(bulk.OrderPlanBulkTrackingError) as raised:
            bulk.start_order_plan_tracking(
                session,
                plan_ids,
                request_id=uuid4(),
                reason="unrelated integrity",
                selected_by="bulk-reviewer",
            )
        assert raised.value.code == "temporarily_unavailable"
        assert raised.value.status_code == 503
        session.expire_all()
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "미선택"
        assert _audit_count(session) == 0
        assert _receipt_count(session) == 0


def test_receipt_jsonb_round_trip_replays_exactly_after_single_reset(
    monkeypatch, pg_engine
):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), prefix="jsonb")
    request_id = uuid4()
    initial_time = datetime(2026, 9, 13, 5, 6, 7, 123456, tzinfo=UTC)
    replay_time = datetime(2026, 9, 14, 6, 7, 8, 654321, tzinfo=UTC)

    class ControlledClock:
        current = initial_time

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(bulk, "datetime", ControlledClock)
    first = _start(pg_engine, plan_ids, request_id)
    with Session(pg_engine) as session:
        record = session.get(IdempotencyRecord, bulk.deterministic_receipt_id(request_id))
        assert record is not None
        snapshot = record.response_snapshot
        assert snapshot == first.snapshot
        assert isinstance(snapshot["request_id"], str)
        assert isinstance(snapshot["completed_at"], str)
        completed_at = datetime.fromisoformat(snapshot["completed_at"])
        assert completed_at.tzinfo is not None and completed_at.microsecond > 0
        assert completed_at == initial_time
        assert isinstance(snapshot["items"][0]["audit_event_id"], str)
        audits_before_reset = _audit_count(session)

    with Session(pg_engine) as session:
        set_tracking_status(
            session,
            owner_ids[0],
            status="미선택",
            reason="단건 명시 reset",
            selected_by="reset-reviewer",
            selected_at=datetime.now(UTC),
        )
        session.commit()
        audits_after_reset = _audit_count(session)

    ControlledClock.current = replay_time
    with Session(pg_engine) as session:
        replay = bulk.start_order_plan_tracking(
            session,
            plan_ids,
            request_id=request_id,
            reason="공통 추적 사유",
            selected_by="bulk-reviewer",
        )
        replay_audits = _audit_count(session)
    assert replay.replayed is True
    assert replay.snapshot == snapshot
    assert replay.snapshot["completed_at"] == "2026-09-13T05:06:07.123456Z"
    assert datetime.fromisoformat(replay.snapshot["completed_at"]) != replay_time
    assert replay_audits == audits_after_reset
    assert audits_after_reset == audits_before_reset + 1


def test_excluded_owner_preserves_nonnull_recheck_metadata(pg_engine):
    plan_ids, owner_ids = _seed(pg_engine, ("종료",), prefix="recheck-preserved")
    signal_at = datetime(2026, 9, 9, 4, 5, 6, 789012, tzinfo=UTC)
    with Session(pg_engine) as session:
        link = session.scalar(
            select(OpportunityLink).where(
                OpportunityLink.order_plan_id == plan_ids[0]
            )
        )
        owner = session.get(Opportunity, owner_ids[0])
        assert link is not None and owner is not None
        owner.recheck_signal_at = signal_at
        owner.recheck_signal_link_id = link.id
        session.commit()
        before = (
            owner.tracking_status,
            owner.tracking_reason,
            owner.tracking_selected_by,
            owner.tracking_selected_at,
            owner.recheck_signal_at,
            owner.recheck_signal_link_id,
        )

    result = _start(pg_engine, plan_ids, uuid4())
    assert result.response.items[0].outcome == "excluded"
    assert result.response.items[0].status_at_decision == "종료"
    with Session(pg_engine) as session:
        owner = session.get(Opportunity, owner_ids[0])
        assert owner is not None
        after = (
            owner.tracking_status,
            owner.tracking_reason,
            owner.tracking_selected_by,
            owner.tracking_selected_at,
            owner.recheck_signal_at,
            owner.recheck_signal_link_id,
        )
        assert after == before
        assert _audit_count(session) == 0


def test_corrupt_receipt_fails_closed_without_repair_or_reexecution(pg_engine):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), prefix="corrupt")
    request_id = uuid4()
    _start(pg_engine, plan_ids, request_id)
    with Session(pg_engine) as session:
        record = session.get(IdempotencyRecord, bulk.deterministic_receipt_id(request_id))
        assert record is not None
        corrupted = dict(record.response_snapshot)
        corrupted["completed_at"] = "not-an-aware-datetime"
        record.response_snapshot = corrupted
        session.commit()
        before_audits = _audit_count(session)

    with Session(pg_engine) as session:
        with pytest.raises(bulk.OrderPlanBulkTrackingError) as raised:
            bulk.start_order_plan_tracking(
                session,
                plan_ids,
                request_id=request_id,
                reason="공통 추적 사유",
                selected_by="bulk-reviewer",
            )
        assert raised.value.code == "processing_failed"
        assert raised.value.status_code == 500
        assert _audit_count(session) == before_audits
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "계속 추적"
        current = session.get(IdempotencyRecord, bulk.deterministic_receipt_id(request_id))
        assert current is not None and current.response_snapshot == corrupted


def test_corrupt_receipt_missing_nullable_key_fails_closed(pg_engine):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), prefix="corrupt-null")
    request_id = uuid4()
    _start(pg_engine, plan_ids, request_id)
    with Session(pg_engine) as session:
        record = session.get(IdempotencyRecord, bulk.deterministic_receipt_id(request_id))
        assert record is not None
        corrupted = deepcopy(record.response_snapshot)
        del corrupted["items"][0]["code"]
        record.response_snapshot = corrupted
        session.commit()
        before_audits = _audit_count(session)

    with Session(pg_engine) as session:
        stored = session.get(IdempotencyRecord, bulk.deterministic_receipt_id(request_id))
        assert stored is not None and "code" not in stored.response_snapshot["items"][0]
        with pytest.raises(bulk.OrderPlanBulkTrackingError) as raised:
            bulk.start_order_plan_tracking(
                session,
                plan_ids,
                request_id=request_id,
                reason="공통 추적 사유",
                selected_by="bulk-reviewer",
            )
        assert raised.value.code == "processing_failed"
        assert _audit_count(session) == before_audits
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "계속 추적"


def test_final_commit_failure_rolls_back_decision_audit_and_receipt(monkeypatch, pg_engine):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), prefix="commit-failure")
    with Session(pg_engine) as session:
        def fail_commit():
            raise SQLAlchemyError("isolated commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(bulk.OrderPlanBulkTrackingError) as raised:
            bulk.start_order_plan_tracking(
                session,
                plan_ids,
                request_id=uuid4(),
                reason="commit failure",
                selected_by="bulk-reviewer",
            )
        assert raised.value.code == "temporarily_unavailable"
        assert raised.value.status_code == 503
        session.expire_all()
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "미선택"
        assert _audit_count(session) == 0
        assert _receipt_count(session) == 0


def test_dto_serialization_failure_rolls_back_everything_before_receipt(monkeypatch, pg_engine):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택",), prefix="dto-failure")
    def fail_dump(self, *args, **kwargs):
        raise ValueError("receipt serialization failure")

    monkeypatch.setattr(bulk.OrderPlanBulkStartResponse, "model_dump", fail_dump)
    with Session(pg_engine) as session:
        with pytest.raises(bulk.OrderPlanBulkTrackingError) as raised:
            bulk.start_order_plan_tracking(
                session,
                plan_ids,
                request_id=uuid4(),
                reason="DTO failure",
                selected_by="bulk-reviewer",
            )
        assert raised.value.code == "processing_failed"
        session.expire_all()
        assert session.get(Opportunity, owner_ids[0]).tracking_status == "미선택"
        assert _audit_count(session) == 0
        assert _receipt_count(session) == 0


# ---------------------------------------------------------------------------
# Isolated post-commit hooks and measured larger populations


def test_hook_failure_isolated_per_owner_and_replay_does_not_call_hooks(monkeypatch, pg_engine):
    plan_ids, owner_ids = _seed(pg_engine, ("미선택", "미선택"), prefix="hooks")
    original_registry = extension_registry()
    registry = reset_extension_registry()

    class Hook:
        def __init__(self):
            self.calls: list[int] = []

        def tracking_decision_changed(self, session, opportunity_id):
            self.calls.append(opportunity_id)
            if opportunity_id == owner_ids[0]:
                raise RuntimeError("first hook fails")

    hook = Hook()
    registry.register_tracking_decision_hook(hook, owner="isolated-test")
    request_id = uuid4()
    try:
        first = _start(pg_engine, plan_ids, request_id)
        assert first.replayed is False
        assert hook.calls == owner_ids
        with Session(pg_engine) as session:
            replay = bulk.start_order_plan_tracking(
                session,
                plan_ids,
                request_id=request_id,
                reason="공통 추적 사유",
                selected_by="bulk-reviewer",
            )
        assert replay.replayed is True
        assert replay.snapshot == first.snapshot
        assert hook.calls == owner_ids
        with Session(pg_engine) as session:
            assert _audit_count(session) == 2
    finally:
        restore_extension_registry(original_registry)


def test_receipt_logs_are_allowlisted_and_mask_actor_reason(caplog, pg_engine):
    plan_ids, _owner_ids = _seed(pg_engine, ("미선택",), prefix="logs")
    request_id = uuid4()
    actor = "actor-secret-not-log"
    reason = "reason-secret-not-log"
    with caplog.at_level(logging.INFO, logger=bulk.logger.name):
        _start(
            pg_engine,
            plan_ids,
            request_id,
            actor=actor,
            reason=reason,
        )
        _start(
            pg_engine,
            plan_ids,
            request_id,
            actor=actor,
            reason=reason,
        )
        with pytest.raises(bulk.OrderPlanBulkTrackingError):
            _start(
                pg_engine,
                plan_ids,
                request_id,
                actor="other-actor-secret",
                reason=reason,
            )

    events = [
        record
        for record in caplog.records
        if isinstance(getattr(record, "bidops", None), dict)
        and str(record.bidops.get("event", "")).startswith(
            "order_plan.bulk_tracking."
        )
    ]
    names = {record.bidops["event"] for record in events}
    assert "order_plan.bulk_tracking.succeeded" in names
    assert "order_plan.bulk_tracking.replayed" in names
    assert "order_plan.bulk_tracking.conflict" in names
    allowed = {
        "event",
        "fence",
        "count",
        "duration_ms",
        "status",
        "error_code",
    }
    for record in events:
        assert set(record.bidops) <= allowed
        assert actor not in record.getMessage()
        assert reason not in record.getMessage()
        assert "other-actor-secret" not in record.getMessage()
        assert "actor-secret-not-log" not in repr(record.bidops)
        assert "reason-secret-not-log" not in repr(record.bidops)
        assert record.bidops["fence"] == str(request_id)
        assert set(record.bidops["count"]) == {
            "selected_plan_count",
            "succeeded_plan_count",
            "excluded_plan_count",
            "failed_plan_count",
            "unique_owner_count",
            "succeeded_owner_count",
        }
        if record.bidops["event"] != "order_plan.bulk_tracking.conflict":
            assert isinstance(record.bidops["duration_ms"], float)


@pytest.mark.parametrize("owner_count", [501, 1200, 2000])
def test_large_owner_population_records_linear_query_and_duration_evidence(
    owner_count: int, pg_engine, record_property
):
    plan_ids, _ = _seed(
        pg_engine,
        ("미선택",) * owner_count,
        prefix=f"scale-{owner_count}",
    )
    statement_count = 0
    savepoint_statement_count = 0

    def count_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal statement_count, savepoint_statement_count
        statement_count += 1
        if statement.lstrip().upper().startswith(("SAVEPOINT ", "RELEASE SAVEPOINT ")):
            savepoint_statement_count += 1

    event.listen(pg_engine, "before_cursor_execute", count_statement)
    started = perf_counter()
    try:
        result = _start(pg_engine, plan_ids, uuid4(), reason=f"scale {owner_count}")
    finally:
        elapsed = perf_counter() - started
        event.remove(pg_engine, "before_cursor_execute", count_statement)

    record_property("owner_count", owner_count)
    record_property("duration_ms", round(elapsed * 1000, 2))
    record_property("sql_statement_count", statement_count)
    record_property("savepoint_statement_count", savepoint_statement_count)
    assert result.response.summary.succeeded_owner_count == owner_count
    assert result.response.summary.succeeded_plan_count == owner_count
    # Each owner has two lock reads (bulk fence + the existing decision writer),
    # one link recheck, one UPDATE, one audit INSERT and one audit lookup.
    # Savepoint creation/release is measured separately, not mistaken for two
    # extra business-data queries. Preflight and receipt reads are fixed-cost.
    assert savepoint_statement_count == 2 * owner_count
    assert statement_count - savepoint_statement_count <= (6 * owner_count) + 32
