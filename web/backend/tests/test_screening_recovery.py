from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditEvent, CompanyProfileSnapshot, Run, ScreeningExecution, ScreeningPolicy
from app.db import _json_serializer
from app.screening.generation_config import register_sqlite_functions
from app.screening.execution_store import ScreeningExecutionStore
from app.screening.queue import INTERRUPTED
from test_screening_queue import DIGEST, NOW, PROFILE_VERSION, enqueue, make_store


def test_queued_stop_is_not_claimable_and_running_stop_finishes_at_boundary(tmp_path):
    _engine, store = make_store(tmp_path)
    queued = enqueue(store, n=1)
    store.request_stop(queued.execution_id, "operator")
    assert store.claim(now=NOW) is None

    running = enqueue(store, n=2)
    claimed = store.claim(now=NOW)
    assert claimed is not None and claimed.execution_id == running.execution_id
    requested = store.request_stop(running.execution_id, "operator")
    assert requested.status == "중지 요청" and requested.active_slot == 1
    assert store.should_stop(running.execution_id)
    progressed = store.update_progress(
        running.execution_id,
        candidate_count=2,
        completed_count=1,
        current_notice_id="notice-1",
        current_stage="synthesis",
    )
    assert progressed.status == "중지 요청" and progressed.stop_reason == "user_requested"
    interrupted = store.finish_interrupted(running.execution_id, now=NOW + timedelta(seconds=1))
    assert interrupted.status == INTERRUPTED and interrupted.active_slot is None
    assert interrupted.completed_count == 1 and interrupted.candidate_count == 2


def test_heartbeat_pump_uses_separate_session_and_stops_cleanly(tmp_path):
    _engine, store = make_store(tmp_path)
    store.now = lambda: datetime.now(timezone.utc)
    row = enqueue(store)
    claimed = store.claim(now=NOW)
    assert claimed is not None
    with store.heartbeat_pump(row.execution_id, interval=0.02) as pump:
        time.sleep(0.08)
        assert pump._thread is not None and pump._thread.is_alive()
        with Session(store.session_factory.kw["bind"]) as session:
            before = session.scalar(
                select(ScreeningExecution.heartbeat_at).where(
                    ScreeningExecution.execution_id == row.execution_id
                )
            )
        assert before is not None and before > NOW
    assert pump._thread is not None and not pump._thread.is_alive()


def test_heartbeat_is_monotonic_and_terminal_cannot_be_revived(tmp_path):
    engine, store = make_store(tmp_path)
    row = enqueue(store)
    store.claim(now=NOW)
    newer = NOW + timedelta(seconds=5)
    assert store.heartbeat(row.execution_id, now=newer)
    assert store.heartbeat(row.execution_id, now=NOW)
    with Session(engine) as session:
        assert session.scalar(
            select(ScreeningExecution.heartbeat_at).where(
                ScreeningExecution.execution_id == row.execution_id
            )
        ) == newer
    store.finish_success(row.execution_id, candidate_count=0, now=newer)
    assert not store.heartbeat(row.execution_id, now=newer + timedelta(seconds=1))


def test_heartbeat_pump_stops_under_held_write_lock(tmp_path):
    engine, store = make_store(tmp_path)
    row = enqueue(store)
    store.claim(now=NOW)
    lock = engine.connect()
    lock.exec_driver_sql("BEGIN IMMEDIATE")
    pump = store.heartbeat_pump(row.execution_id, interval=0.01, join_timeout=0.3).start()
    time.sleep(0.08)
    pump.stop(timeout=0.3)
    assert pump._thread is not None and not pump._thread.is_alive()
    lock.rollback()
    lock.close()


def test_stale_recovery_is_strict_and_preserves_progress(tmp_path):
    engine, store = make_store(tmp_path)
    # The settings object is intentionally tiny: the store only needs the
    # configured stale interval and does not depend on global process state.
    store.settings = type("Settings", (), {"stale_seconds": 10})()
    old = enqueue(store, n=1, candidate_count=4)
    store.claim(now=NOW)
    store.update_progress(old.execution_id, completed_count=2, failure_count=1)
    with Session(engine) as session:
        session.execute(
            ScreeningExecution.__table__.update()
            .where(ScreeningExecution.execution_id == old.execution_id)
            .values(heartbeat_at=NOW - timedelta(seconds=11), current_notice_id="n1", current_stage="synthesis")
        )
        session.commit()
    fresh = enqueue(store, n=2)
    recovered = store.recover_stale(now=NOW)
    assert recovered == [old.execution_id]
    with Session(engine) as session:
        interrupted = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == old.execution_id))
        assert interrupted.status == INTERRUPTED
        assert interrupted.stop_reason == "process_interrupted"
        assert interrupted.finished_at == NOW
        assert interrupted.active_slot is None
        assert interrupted.completed_count == 2 and interrupted.failure_count == 1
        assert interrupted.current_notice_id is None and interrupted.current_stage is None
        event = session.scalar(select(AuditEvent).where(AuditEvent.target_id == old.execution_id))
        assert event.actor == "system:screening-recovery"
        assert "prompt" not in str(event.details_json).lower()
    # The next FIFO row is now claimable and a second recovery is idempotent.
    claimed = store.claim(now=NOW)
    assert claimed is not None and claimed.execution_id == fresh.execution_id
    assert store.recover_stale(now=NOW) == []


def test_stale_equality_and_fresh_active_are_untouched(tmp_path):
    engine, store = make_store(tmp_path)
    store.settings = type("Settings", (), {"stale_seconds": 10})()
    equality = enqueue(store, n=1)
    store.claim(now=NOW)
    with Session(engine) as session:
        session.execute(
            ScreeningExecution.__table__.update()
            .where(ScreeningExecution.execution_id == equality.execution_id)
            .values(heartbeat_at=NOW - timedelta(seconds=10))
        )
        session.commit()
    assert store.recover_stale(now=NOW) == []
    with Session(engine) as session:
        row = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == equality.execution_id))
        assert row.status == "실행 중" and row.active_slot == 1


def test_actual_alembic_database_claim_stop_recovery_and_constraints(tmp_path):
    database = tmp_path / "alembic-runtime.db"
    backend = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    upgraded = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
        json_serializer=_json_serializer,
    )
    # Reproduce the application/Alembic SQLite connection contract on this
    # independently-created engine before ORM writes exercise the triggers.
    event.listen(engine, "connect", lambda dbapi_connection, _record: register_sqlite_functions(dbapi_connection))
    with Session(engine) as session:
        session.add(Run(id="run-1", timezone="Asia/Seoul", generated_at=NOW, status="active"))
        session.add(
            CompanyProfileSnapshot(
                digest=DIGEST,
                version=PROFILE_VERSION,
                source_kind="working_tree",
                source_ref="docs/reference/company-profile.md",
                artifact_path=f"web/data/profile-snapshots/{DIGEST}.md",
                created_at=NOW,
            )
        )
        session.add(
            ScreeningPolicy(
                policy_version="policy-1",
                prompt_version="prompt-1",
                content_digest=DIGEST,
                status="activation_candidate",
                perspective_prompts_json={},
                counterargument_prompt_json={},
                synthesis_prompt_json={},
                candidate_selection_json={},
                thresholds_json={},
                created_at=NOW,
                created_by="tester",
            )
        )
        session.commit()
    store = ScreeningExecutionStore(engine=engine, now=lambda: NOW)
    first = enqueue(store, n=1)
    assert store.claim(now=NOW).execution_id == first.execution_id
    store.request_stop(first.execution_id, "operator")
    store.update_progress(first.execution_id, candidate_count=1, completed_count=1, current_stage="synthesis")
    assert store.finish_interrupted(first.execution_id, now=NOW + timedelta(seconds=1)).status == INTERRUPTED

    second = enqueue(store, n=2)
    assert store.claim(now=NOW).execution_id == second.execution_id
    store.settings = type("Settings", (), {"stale_seconds": 10})()
    with Session(engine) as session:
        session.execute(
            update(ScreeningExecution)
            .where(ScreeningExecution.execution_id == second.execution_id)
            .values(heartbeat_at=NOW - timedelta(seconds=11))
        )
        session.commit()
    assert store.recover_stale(now=NOW) == [second.execution_id]
    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                update(ScreeningExecution)
                .where(ScreeningExecution.execution_id == second.execution_id)
                .values(status="bogus")
            )
