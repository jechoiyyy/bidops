"""Real two-session stop/claim/publication ordering, with fake model transport."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.core.models import AuditEvent
from app.deep_review.models import (
    PreSpecPageOverview, PreSpecOverviewReview, PrespecOverviewCallEvent, PrespecOverviewVerification,
    PrespecV4Attempt, PrespecV4Target, WorkJob,
)
from app.deep_review.services import prespec_v4_runner as runtime
from app.deep_review.services.prespec_v4_gate import lock_v4_gate
from app.deep_review.services.prespec_v4_ops import deactivate_v4
from app.deep_review.services.prespec_v4_range import RANGE_CONFIRMED_ACTION, V4OpsError, confirm_v4_range
from tests.deep_review import test_prespec_v4_runner as fixtures
from tests.postgres import migrated_engine, requires_postgres

pytestmark = requires_postgres


@pytest.fixture
def pg_context(tmp_path, monkeypatch):
    with migrated_engine() as engine:
        monkeypatch.setattr(fixtures, "_engine", lambda: engine)
        monkeypatch.setattr(runtime, "resolve_model_endpoint", lambda *args, **kwargs: SimpleNamespace(model_revision="a" * 64))
        _, session, store, target, policy, binding, attempt = fixtures._queued_v5(tmp_path)
        target_id, attempt_id = target.id, attempt.id
        session.close()
        yield engine, store, target_id, attempt_id, policy, binding


@pytest.fixture
def pg_ready_context(tmp_path, monkeypatch):
    """One activated ready target with no execution, on disposable PostgreSQL."""

    with migrated_engine() as engine:
        monkeypatch.setattr(fixtures, "_engine", lambda: engine)
        _, session, store, target = fixtures._ready_target(tmp_path)
        policy = runtime.load_v4_policy()
        binding = runtime.V4ModelBinding(
            provider="test",
            model_name=policy.model_name,
            model_digest="a" * 64,
            prompt_version=policy.prompt_version,
            policy_digest=policy.digest,
            reference_only=True,
        )
        fixtures._activate_v5_for_target(session, target, binding, policy)
        target_id = target.id
        session.commit()
        session.close()
        yield engine, store, target_id, binding


def _run(context, client):
    engine, store, _target_id, _attempt_id, policy, binding = context
    with Session(engine) as session:
        runner = runtime.PrespecV4OverviewRunner(
            client=client, binding=binding, policy=policy,
            raw_response_store=fixtures._RawStore(), object_store=store,
        )
        client.session = session
        return runner.run_once(session, "pg-gate-worker")


def test_capacity_failure_closes_attempt_and_job_without_dispatch(pg_context):
    engine, _store, _target_id, attempt_id, _policy, _binding = pg_context
    client = fixtures._Client(fixtures._claims_draft(), fixtures._semantic())
    client.model_context_tokens = 1024
    outcome = _run(pg_context, client)
    assert outcome.status == "failed" and outcome.reason_code == "input_capacity_exceeded"
    assert client.calls == []
    with Session(engine) as session:
        attempt = session.get(PrespecV4Attempt, attempt_id)
        job = session.get(WorkJob, attempt.work_job_id)
        assert attempt.status == job.status == "failed"
        assert attempt.error_code == job.last_error_code == "input_capacity_exceeded"
        assert attempt.completed_at is not None and job.completed_at is not None
        assert attempt.lease_owner is None and job.lease_owner is None
        assert attempt.result_id is None
        for model in (PrespecOverviewCallEvent, PrespecOverviewVerification, PreSpecPageOverview):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_stop_commit_before_claim_prevents_any_dispatch(pg_context):
    engine, _store, _target_id, attempt_id, _policy, _binding = pg_context
    competing = Event()
    client = fixtures._Client(fixtures._claims_draft(), fixtures._semantic())

    def before_sql(conn, cursor, statement, parameters, context, executemany):
        if "pg_advisory_xact_lock" in statement and conn.info.get("competitor"):
            competing.set()

    def worker():
        with engine.connect() as conn:
            conn.info["competitor"] = True
            try:
                with Session(bind=conn) as session:
                    return runtime.PrespecV4OverviewRunner(
                        client=client, binding=pg_context[5], policy=pg_context[4],
                        raw_response_store=fixtures._RawStore(), object_store=pg_context[1],
                    ).run_once(session, "pg-gate-worker")
            finally:
                conn.info.pop("competitor", None)

    event.listen(engine, "before_cursor_execute", before_sql)
    try:
        with Session(engine) as operator, ThreadPoolExecutor(max_workers=1) as pool:
            lock_v4_gate(operator)
            future = pool.submit(worker)
            try:
                assert competing.wait(10), "worker did not reach the held PostgreSQL gate"
                stopped = deactivate_v4(operator, actor="tester", reason="operator_requested")
                operator.commit()
            finally:
                operator.rollback()
            result = future.result(timeout=10)
        assert stopped.cancelled_attempts == stopped.cancelled_jobs == 1
        assert result.claimed is False and client.calls == []
        with Session(engine) as session:
            assert session.get(PrespecV4Attempt, attempt_id).status == "cancelled"
            assert session.scalar(select(func.count()).select_from(PrespecOverviewCallEvent)) == 0
    finally:
        event.remove(engine, "before_cursor_execute", before_sql)


@pytest.mark.parametrize("stop_stage", ["prespec_overview_claims", "prespec_overview_semantic"])
def test_stop_and_reactivation_during_http_keep_only_late_call_history(pg_context, stop_stage):
    engine, _store, target_id, attempt_id, policy, binding = pg_context
    dispatched, respond = Event(), Event()

    class Client(fixtures._Client):
        def invoke(self, stage, *args, **kwargs):
            assert not self.session.in_transaction(), "HTTP must not hold a DB transaction"
            if stage == stop_stage:
                dispatched.set()
                assert respond.wait(10), "operator did not release fake response"
            return super().invoke(stage, *args, **kwargs)

    client = Client(fixtures._claims_draft(), fixtures._semantic())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run, pg_context, client)
        try:
            assert dispatched.wait(10), "runner did not reach fake HTTP"
            with Session(engine) as operator:
                old_activation = operator.get(PrespecV4Attempt, attempt_id).activation_id
                stopped = deactivate_v4(operator, actor="tester", reason="operator_requested")
                operator.commit()
                fixtures._activate_v5_for_target(operator, operator.get(PrespecV4Target, target_id), binding, policy)
                operator.commit()
                assert stopped.activation_id != old_activation
        finally:
            respond.set()
        result = future.result(timeout=10)
    assert result.status == "stale"
    with Session(engine) as session:
        attempt = session.get(PrespecV4Attempt, attempt_id)
        assert attempt.status == "cancelled" and attempt.result_id is None
        assert session.get(WorkJob, attempt.work_job_id).status == "cancelled"
        assert session.scalar(select(func.count()).select_from(PreSpecPageOverview)) == 0
        assert session.scalar(select(func.count()).select_from(PrespecOverviewVerification)) == 0
        events = session.scalars(select(PrespecOverviewCallEvent).order_by(PrespecOverviewCallEvent.ordinal)).all()
        expected_calls = 1 if stop_stage == "prespec_overview_claims" else 2
        assert len(client.calls) == expected_calls and len(events) == 2 * expected_calls
        assert sum(row.event_kind == "response" and row.raw_response_sha256 is not None for row in events) == expected_calls


def test_publication_holding_gate_commits_before_stop_and_history_survives(pg_context):
    engine, _store, _target_id, attempt_id, _policy, _binding = pg_context
    inserting, release_insert, stop_waiting = Event(), Event(), Event()

    def before_sql(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO bidops.prespec_page_overview"):
            inserting.set()
            assert release_insert.wait(10), "stop did not reach the held gate"
        if "pg_advisory_xact_lock" in statement and conn.info.get("stopper"):
            stop_waiting.set()

    def stop():
        with engine.connect() as conn:
            conn.info["stopper"] = True
            try:
                with Session(bind=conn) as session:
                    result = deactivate_v4(session, actor="tester", reason="operator_requested")
                    session.commit()
                    return result
            finally:
                conn.info.pop("stopper", None)

    event.listen(engine, "before_cursor_execute", before_sql)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            running = pool.submit(_run, pg_context, fixtures._Client(fixtures._claims_draft(), fixtures._semantic()))
            try:
                assert inserting.wait(10), "runner did not reach final publication"
                stopping = pool.submit(stop)
                assert stop_waiting.wait(10)
            finally:
                release_insert.set()
            assert running.result(timeout=10).status == "completed"
            stopped = stopping.result(timeout=10)
        assert stopped.cancelled_attempts == stopped.cancelled_jobs == 0
        with Session(engine) as session:
            attempt = session.get(PrespecV4Attempt, attempt_id)
            assert attempt.status == "completed" and attempt.result_id is not None
            assert session.get(WorkJob, attempt.work_job_id).status == "completed"
            assert session.scalar(select(func.count()).select_from(PrespecOverviewVerification)) == 1
            from app.deep_review.services.page_overview import list_page_overviews_v2
            response = list_page_overviews_v2(session, attempt.notice_id)
            assert response.current.status == "completed" and len(response.reviews) == 1
    finally:
        event.remove(engine, "before_cursor_execute", before_sql)


def test_range_confirmation_supersedes_an_enqueue_waiting_on_notice(pg_ready_context):
    engine, store, target_id, binding = pg_ready_context
    enqueue_waiting = Event()

    def before_sql(conn, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement and "notice" in statement and conn.info.get("old-target-enqueue"):
            enqueue_waiting.set()

    def enqueue_old_target():
        with engine.connect() as conn:
            conn.info["old-target-enqueue"] = True
            try:
                with Session(bind=conn) as session:
                    try:
                        runtime.enqueue_v4_attempt(session, target_id=target_id, binding=binding)
                        session.commit()
                    except runtime.V4AttemptError as error:
                        session.rollback()
                        return error.code
            finally:
                conn.info.pop("old-target-enqueue", None)
        return None

    event.listen(engine, "before_cursor_execute", before_sql)
    try:
        with Session(engine) as confirmer, ThreadPoolExecutor(max_workers=1) as pool:
            old = confirmer.get(PrespecV4Target, target_id)
            old_state = (
                old.selection_status,
                old.selection_strategy,
                old.input_sha256,
                old.selection_manifest_sha256,
                tuple(old.page_numbers_jsonb),
            )
            confirmed = confirm_v4_range(
                confirmer,
                store,
                notice_id=old.notice_id,
                target_id=old.id,
                actor="pg-range-test",
                first_page=2,
                last_page=2,
            )
            assert confirmed.target_id != old.id
            future = pool.submit(enqueue_old_target)
            assert enqueue_waiting.wait(10), "enqueue did not reach the held notice lock"
            confirmer.commit()
            assert future.result(timeout=10) == "target_superseded"

        with Session(engine) as session:
            old = session.get(PrespecV4Target, target_id)
            assert (
                old.selection_status,
                old.selection_strategy,
                old.input_sha256,
                old.selection_manifest_sha256,
                tuple(old.page_numbers_jsonb),
            ) == old_state
            assert session.scalar(select(func.count()).select_from(PrespecV4Target)) == 2
            assert session.scalar(select(func.count()).select_from(PrespecV4Attempt)) == 0
            assert session.scalar(select(func.count()).select_from(PreSpecPageOverview)) == 0
            assert session.scalar(select(func.count()).select_from(PreSpecOverviewReview)) == 0
            assert session.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == RANGE_CONFIRMED_ACTION,
            )) == 1
    finally:
        event.remove(engine, "before_cursor_execute", before_sql)


@pytest.mark.parametrize("status", ["queued", "running"])
def test_range_confirmation_rejects_an_active_attempt_without_new_history(pg_ready_context, status):
    engine, store, target_id, binding = pg_ready_context
    with Session(engine) as session:
        target = session.get(PrespecV4Target, target_id)
        attempt = runtime.enqueue_v4_attempt(session, target_id=target.id, binding=binding)
        session.commit()
        job = session.get(WorkJob, attempt.work_job_id)
        if status == "running":
            now = datetime.now(UTC)
            attempt.status = job.status = "running"
            attempt.started_at = now
            attempt.lease_owner = job.lease_owner = "pg-range-worker"
            attempt.lease_expires_at = job.lease_expires_at = now + timedelta(minutes=20)
            session.commit()

        before = {
            "targets": session.scalar(select(func.count()).select_from(PrespecV4Target)),
            "attempts": session.scalar(select(func.count()).select_from(PrespecV4Attempt)),
            "audits": session.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == RANGE_CONFIRMED_ACTION,
            )),
        }
        with pytest.raises(V4OpsError, match="target_execution_active") as caught:
            confirm_v4_range(
                session,
                store,
                notice_id=target.notice_id,
                target_id=target.id,
                actor="pg-range-test",
                first_page=2,
                last_page=2,
            )
        assert caught.value.code == "target_execution_active"
        session.rollback()
        assert session.get(PrespecV4Attempt, attempt.id).status == status
        assert session.scalar(select(func.count()).select_from(PrespecV4Target)) == before["targets"]
        assert session.scalar(select(func.count()).select_from(PrespecV4Attempt)) == before["attempts"]
        assert session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == RANGE_CONFIRMED_ACTION,
        )) == before["audits"]
