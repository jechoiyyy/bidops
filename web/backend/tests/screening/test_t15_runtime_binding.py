from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.db import Base
from app.lifecycle.models import Run
from app.screening.models import AlwaysOnState, ScheduleExecution, ScheduleReservation
from app.core.schema_base import _validate_generation_binding
from app.core.generation_config import legacy_generation_config
from app.screening.services.scheduled_pipeline import ScheduledPipeline
from app.screening.services.scheduler import ScheduleConflictError, SchedulerService


class _CountingInspector:
    def __init__(self) -> None:
        self.inspect_calls = 0

    def inspect_model(self, **_kwargs):
        self.inspect_calls += 1
        return {"model_name": "qwen3.8:27b", "digest": "a" * 64}


class _CountingOrchestrator:
    def __init__(self) -> None:
        self.create_calls = 0

    def create_execution(self, **_kwargs):
        self.create_calls += 1
        return {"execution_id": "scr-" + "b" * 32, "generation_config_digest": "b" * 64}


def _db(tmp_path: Path):
    database = tmp_path / "runtime-binding.db"
    engine = create_engine(f"sqlite:///{database}", future=True)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False), database


def test_scheduled_judgment_drift_is_before_inspection_or_model_queue(tmp_path: Path):
    engine, factory, database = _db(tmp_path)
    run_key = "20260825-20260825"
    with Session(engine) as session:
        session.add(Run(id=run_key, window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", status="active"))
        session.add(ScheduleReservation(run_key=run_key, job_kind="daily", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul"))
        execution = ScheduleExecution(
            execution_id="sched-" + "a" * 32,
            run_key=run_key,
            job_kind="daily",
            trigger="schedule",
            status="예약",
            requested_by="system:scheduler",
            policy_version="policy-v1",
            model_name="qwen3.8:27b",
            model_digest="a" * 64,
            generation_config_digest=legacy_generation_config().digest(),
        )
        session.add(execution)
        session.commit()
        execution_id = execution.execution_id

    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{database}", scheduler_enabled=True)
    inspector = _CountingInspector()
    orchestrator = _CountingOrchestrator()
    pipeline = ScheduledPipeline(settings, session_factory=factory, orchestrator=orchestrator, ollama=inspector)
    row = pipeline._execution(execution_id)
    result = pipeline._judgment(row, run_id=run_key)
    assert result.failure_reason == "generation_config_mismatch"
    assert inspector.inspect_calls == 0
    assert orchestrator.create_calls == 0


def test_enabled_schedule_rejects_drift_before_reservation(tmp_path: Path):
    engine, factory, database = _db(tmp_path)
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{database}", scheduler_enabled=True)
    service = SchedulerService(settings, session_factory=factory)
    with Session(engine) as session:
        session.add(AlwaysOnState(
            singleton_id=1,
            enabled=True,
            quality_gate_result_id="gateeval-" + "a" * 32,
            policy_version="policy-v1",
            model_name="qwen3.8:27b",
            model_digest="a" * 64,
            prompt_version="prompt-v1",
            company_profile_version="company-profile.sha256:" + "b" * 64,
            company_profile_digest="b" * 64,
            generation_config_digest=legacy_generation_config().digest(),
            updated_by="operator",
        ))
        session.commit()
    with pytest.raises(ScheduleConflictError, match="generation_config_mismatch"):
        service.reserve_daily(date(2026, 8, 25))
    with Session(engine) as session:
        assert session.scalar(select(ScheduleReservation)) is None
        assert session.scalar(select(ScheduleExecution)) is None


def test_response_roundtrip_requires_exact_canonical_generation_pair():
    config = legacy_generation_config().canonical_value()
    digest = legacy_generation_config().digest()
    assert _validate_generation_binding(config, digest, required=True) == config
    with pytest.raises(ValueError):
        _validate_generation_binding({**config, "num_ctx": 1}, digest, required=True)
    with pytest.raises(ValueError):
        _validate_generation_binding(config, "0" * 64, required=True)
