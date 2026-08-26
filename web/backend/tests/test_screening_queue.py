from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import CompanyProfileSnapshot, Notice, Run, ScreeningExecution, ScreeningPolicy
from app.screening.execution_store import ScreeningExecutionStore
from app.screening.generation_config import GenerationConfig
from app.screening.queue import ExecutionConflict, QueueValidationError


DIGEST = "a" * 64
PROFILE_VERSION = "company-profile.sha256:" + DIGEST
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_store(tmp_path, *, policy_status="activation_candidate"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'queue.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _wal(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
        dbapi_connection.execute("PRAGMA busy_timeout=5000")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Run(id="run-1", timezone="Asia/Seoul", generated_at=NOW, status="active"))
        session.add(Notice(run_id="run-1", notice_key="notice-1"))
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
                status=policy_status,
                active_slot=1 if policy_status == "active" else None,
                perspective_prompts_json={},
                counterargument_prompt_json={},
                synthesis_prompt_json={},
                candidate_selection_json={},
                thresholds_json={},
                created_at=NOW,
                created_by="tester",
                activated_at=NOW if policy_status == "active" else None,
                activated_by="tester" if policy_status == "active" else None,
                quality_gate_result_id="gateeval-1" if policy_status == "active" else None,
            )
        )
        session.commit()
    return engine, ScreeningExecutionStore(sessionmaker(bind=engine, expire_on_commit=False), now=lambda: NOW)


def enqueue(store, *, n=0, scope="full_run", trigger="manual_run", **extra):
    values = dict(
        trigger=trigger,
        source_run_id="run-1",
        scope=scope,
        requested_by="operator",
        policy_version="policy-1",
        prompt_version="prompt-1",
        model_name="qwen3.8:27b",
        model_digest=DIGEST,
        company_profile_version=PROFILE_VERSION,
        company_profile_digest=DIGEST,
        generation_config=GenerationConfig().canonical_value(),
        generation_config_digest=GenerationConfig().digest(),
        input_artifact_path=f"runs/input-{n}.json",
        input_artifact_digest=DIGEST,
        artifact_dir=f"runs/execution-{n}",
        candidate_count=0,
    )
    values.update(extra)
    return store.enqueue(**values)


def test_enqueue_validates_four_triggers_scope_and_fifo(tmp_path):
    _engine, store = make_store(tmp_path / "candidate")
    _active_engine, active_store = make_store(tmp_path / "active", policy_status="active")
    trigger_scopes = {
        "cli_single": "single_notice",
        "manual_run": "full_run",
        "quality_gate": "quality_sample",
        "schedule": "full_run",
    }
    rows = [
        enqueue(
            active_store,
            n=i,
            trigger=trigger,
            scope=trigger_scopes[trigger],
            **({"notice_pk": 1, "notice_id": "notice-1"} if trigger == "cli_single" else {}),
        )
        for i, trigger in enumerate(("cli_single", "manual_run", "quality_gate", "schedule"))
    ]
    assert [row.queue_no for row in rows] == [1, 2, 3, 4]
    assert all(row.status == "대기" and row.execution_id.startswith("scr-") for row in rows)
    assert all(len(row.execution_id) == 36 for row in rows)
    with pytest.raises(QueueValidationError):
        enqueue(store, n=10, trigger="unknown")
    with pytest.raises(QueueValidationError):
        enqueue(store, n=11, scope="single_notice")
    with pytest.raises(QueueValidationError):
        enqueue(store, n=12, scope="full_run", notice_pk=1, notice_id="notice")
    with pytest.raises(QueueValidationError):
        enqueue(store, n=13, input_artifact_path="../escape.json")
    with pytest.raises(QueueValidationError):
        enqueue(store, n=14, trigger="schedule", scope="full_run")
    running = active_store.claim(now=NOW)
    assert running is not None
    with pytest.raises(QueueValidationError):
        store.update_progress(running.execution_id, current_stage="unknown-stage")


def test_claim_is_fifo_and_one_global_active_slot_under_threads(tmp_path):
    engine, store = make_store(tmp_path)
    for i in range(8):
        enqueue(store, n=i, trigger="manual_run")
    claimed = []
    errors = []

    def worker():
        try:
            claimed.append(store.claim(now=NOW))
        except Exception as exc:  # a concurrency regression must be visible
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert sum(row is not None for row in claimed) == 1
    with Session(engine) as session:
        active = session.scalars(
            select(ScreeningExecution).where(ScreeningExecution.active_slot == 1)
        ).all()
        assert len(active) == 1
        assert active[0].queue_no == 1


def test_terminal_execution_cannot_revert_or_progress(tmp_path):
    _engine, store = make_store(tmp_path)
    row = enqueue(store)
    claimed = store.claim(now=NOW)
    assert claimed and claimed.execution_id == row.execution_id
    finished = store.finish_success(row.execution_id, candidate_count=1, completed_count=1, now=NOW)
    assert finished.status == "성공" and finished.active_slot is None
    with pytest.raises(ExecutionConflict):
        store.request_stop(row.execution_id, "operator")
    with pytest.raises(ExecutionConflict):
        store.update_progress(row.execution_id, completed_count=1)


def test_progress_summary_is_bounded_and_does_not_store_sensitive_body(tmp_path):
    engine, store = make_store(tmp_path)
    row = enqueue(store)
    store.claim(now=NOW)
    store.update_progress(
        row.execution_id,
        error_summary="TOP_SECRET_SENTINEL prompt and model response body should never persist",
    )
    with Session(engine) as session:
        saved = session.scalar(
            select(ScreeningExecution.error_summary).where(
                ScreeningExecution.execution_id == row.execution_id
            )
        )
    assert saved == "execution_failure"
    assert len(saved) <= 64
    store.update_progress(row.execution_id, error_summary="timeout")
    with Session(engine) as session:
        assert session.scalar(
            select(ScreeningExecution.error_summary).where(
                ScreeningExecution.execution_id == row.execution_id
            )
        ) == "timeout"


def test_transitions_preserve_all_immutable_binding_fields(tmp_path):
    engine, store = make_store(tmp_path)
    row = enqueue(store)
    immutable = {
        field: getattr(row, field)
        for field in (
            "execution_id",
            "queue_no",
            "trigger",
            "source_run_id",
            "scope",
            "notice_pk",
            "notice_id",
            "requested_by",
            "policy_version",
            "prompt_version",
            "model_name",
            "model_digest",
            "company_profile_version",
            "company_profile_digest",
            "input_artifact_path",
            "input_artifact_digest",
            "artifact_dir",
        )
    }
    store.claim(now=NOW)
    store.update_progress(row.execution_id, candidate_count=1, completed_count=1, current_stage="synthesis")
    store.request_stop(row.execution_id, "operator")
    store.update_progress(row.execution_id, current_stage="counterargument")
    store.finish_interrupted(row.execution_id, now=NOW + timedelta(seconds=1))
    with Session(engine) as session:
        final = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == row.execution_id))
        assert {field: getattr(final, field) for field in immutable} == immutable


def test_connection_bound_caller_session_is_rejected_without_rollback(tmp_path):
    engine, _store = make_store(tmp_path)
    with engine.connect() as connection:
        caller = Session(bind=connection)
        caller.add(Run(id="caller-unrelated", timezone="Asia/Seoul", generated_at=NOW, status="active"))
        caller.flush()
        with pytest.raises(TypeError):
            ScreeningExecutionStore(session=caller)
        assert caller.in_transaction()
        assert caller.scalar(select(Run.id).where(Run.id == "caller-unrelated")) == "caller-unrelated"
        caller.rollback()
