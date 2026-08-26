from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import Base, Run, ScheduleExecution
from app.services.scheduler import SchedulerService
from app.services.scheduled_pipeline import ScheduledPipeline


class FakeOllama:
    def inspect_model(self):
        return {"model_name": "qwen3.8:27b", "digest": "a" * 64}


class FakeStages:
    def collect(self, **kwargs):
        return {"status": "success", "run_id": kwargs["run_key"]}

    def sample(self, **kwargs):
        return {"status": "success", "candidate_count": 1}

    def judgment(self, **kwargs):
        return {"status": "success", "screening_execution_id": "scr-" + "a" * 32, "result_count": 1}

    def merge_load(self, **kwargs):
        return {"status": "success", "candidate_count": 1, "result_count": 1}

    def report(self, **kwargs):
        return {"status": "success"}


def test_daily_orders_stages_and_publishes_success(tmp_path: Path):
    db = tmp_path / "pipeline.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as session:
        session.add(Run(id="20260825-20260825", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", status="active"))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
    scheduler = SchedulerService(settings, session_factory=factory, clock=lambda: datetime(2026, 8, 26, 3, tzinfo=timezone.utc))
    execution = scheduler.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
    assert execution is not None
    # Bind the exact approved model identity on the schedule row as a gate
    # projection would do; no direct model call is made by the stage runner.
    with Session(engine) as session:
        row = session.get(ScheduleExecution, execution.execution_id)
        row.model_name = "qwen3.8:27b"
        row.model_digest = "a" * 64
        session.commit()
    pipeline = ScheduledPipeline(settings, session_factory=factory, pipeline=FakeStages(), ollama=FakeOllama(), clock=lambda: datetime(2026, 8, 26, 3, tzinfo=timezone.utc))
    result = pipeline.run_daily(execution.execution_id)
    assert result.status == "성공"
    with Session(engine) as session:
        assert session.get(ScheduleExecution, execution.execution_id).status == "성공"


def test_model_identity_failure_happens_before_judgment_enqueue(tmp_path: Path):
    db = tmp_path / "pipeline.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as session:
        session.add(Run(id="20260825-20260825", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", status="active"))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
    scheduler = SchedulerService(settings, session_factory=factory)
    execution = scheduler.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
    assert execution is not None
    with Session(engine) as session:
        row = session.get(ScheduleExecution, execution.execution_id)
        row.model_name = "qwen3.8:27b"
        row.model_digest = "a" * 64
        session.commit()
    class WrongModel(FakeOllama):
        def inspect_model(self):
            return {"model_name": "wrong", "digest": "b" * 64}
    pipeline = ScheduledPipeline(settings, session_factory=factory, pipeline=FakeStages(), ollama=WrongModel())
    result = pipeline.run_daily(execution.execution_id)
    assert result.status == "실패"
    assert result.failure_reason == "ollama_unavailable"
