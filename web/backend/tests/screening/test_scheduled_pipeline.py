from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event, Lock, Thread

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.db import Base
from app.lifecycle.models import Run
from app.screening.models import ScheduleExecution, ScheduleReservation, ScreeningExecution
from app.screening.services.scheduler import SchedulerService
from app.screening.services.scheduled_pipeline import ScheduledPipeline
from app.screening.orchestrator import ScreeningCreationError


class FakeOllama:
    def inspect_model(self, *, refresh=False):
        return {"model_name": "qwen3.8:27b", "digest": "a" * 64}


class ModeStages:
    def __init__(self, mode: str | None = None, *, judgment: dict | None = None):
        self.mode = mode
        self.judgment_result = judgment

    def _result(self, stage: str, value: dict):
        return {"status": "중단됨"} if self.mode == stage else value

    def collect(self, **kwargs):
        return self._result("collect", {"status": "success", "run_id": kwargs["run_key"]})

    def sample(self, **kwargs):
        return self._result("sample", {"status": "success", "candidate_count": 1})

    def judgment(self, **kwargs):
        if self.judgment_result is not None:
            return self.judgment_result
        return self._result("judgment", {"status": "success", "screening_execution_id": "scr-" + "a" * 32, "result_count": 1})

    def merge_load(self, **kwargs):
        return self._result("merge_load", {"status": "success", "candidate_count": 1, "result_count": 1})

    def report(self, **kwargs):
        return self._result("weekly_report" if kwargs.get("mode") == "weekly" else "report", {"status": "success"})


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
        def inspect_model(self, *, refresh=False):
            return {"model_name": "wrong", "digest": "b" * 64}
    pipeline = ScheduledPipeline(settings, session_factory=factory, pipeline=FakeStages(), ollama=WrongModel())
    result = pipeline.run_daily(execution.execution_id)
    assert result.status == "실패"
    assert result.failure_reason == "ollama_unavailable"
    with Session(engine) as session:
        assert session.scalar(select(ScreeningExecution)) is None


def test_interrupted_non_judgment_stages_never_flow_to_success(tmp_path: Path):
    for interrupted_stage, expected_reason, expected_status in (
        ("collect", "collect_interrupted", "실패"),
        ("sample", "sample_interrupted", "실패"),
        ("merge_load", "merge_load_interrupted", "부분 성공"),
        ("report", "report_interrupted", "부분 성공"),
    ):
        db = tmp_path / f"{interrupted_stage}.db"
        engine = create_engine(f"sqlite:///{db}", future=True)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with Session(engine) as session:
            session.add(Run(id="20260825-20260825", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", status="active"))
            session.commit()
        settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
        scheduler = SchedulerService(settings, session_factory=factory)
        execution = scheduler.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
        with Session(engine) as session:
            row = session.get(ScheduleExecution, execution.execution_id)
            row.model_name, row.model_digest = "qwen3.8:27b", "a" * 64
            session.commit()
        pipeline = ScheduledPipeline(settings, session_factory=factory, pipeline=ModeStages(interrupted_stage), ollama=FakeOllama())
        result = pipeline.run_daily(execution.execution_id)
        assert result.status == expected_status
        assert result.failure_reason == expected_reason


def test_judgment_without_worker_is_not_reported_as_success(tmp_path: Path):
    db = tmp_path / "no-worker.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as session:
        session.add(Run(id="20260825-20260825", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", status="active"))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
    scheduler = SchedulerService(settings, session_factory=factory)
    execution = scheduler.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
    with Session(engine) as session:
        row = session.get(ScheduleExecution, execution.execution_id)
        row.model_name, row.model_digest, row.policy_version = "qwen3.8:27b", "a" * 64, "policy-v1"
        session.commit()

    class FakeOrchestrator:
        def create_execution(self, **kwargs):
            return {"execution_id": "scr-" + "b" * 32}

    pipeline = ScheduledPipeline(settings, session_factory=factory, pipeline=ModeStages(), orchestrator=FakeOrchestrator(), ollama=FakeOllama())
    result = pipeline.run_daily(execution.execution_id)
    assert result.status == "실패"
    assert result.failure_reason == "judgment_incomplete"


def test_judgment_partial_counts_and_zeroes_are_preserved(tmp_path: Path):
    db = tmp_path / "partial.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as session:
        session.add(Run(id="20260825-20260825", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", status="active"))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
    scheduler = SchedulerService(settings, session_factory=factory)
    execution = scheduler.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
    with Session(engine) as session:
        row = session.get(ScheduleExecution, execution.execution_id)
        row.model_name, row.model_digest, row.policy_version = "qwen3.8:27b", "a" * 64, "policy-v1"
        session.commit()
    stages = ModeStages(judgment={"status": "부분 성공", "candidate_count": 0, "result_count": 0, "failure_count": 2, "partial_artifact": True})
    pipeline = ScheduledPipeline(settings, session_factory=factory, pipeline=stages, ollama=FakeOllama())
    result = pipeline.run_daily(execution.execution_id)
    assert result.status == "부분 성공"
    assert result.candidate_count == 0
    assert result.result_count == 0
    assert result.failure_count == 2
    assert result.partial_artifact is True


def test_precondition_failed_is_stable_ollama_unavailable(tmp_path: Path):
    db = tmp_path / "precondition.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as session:
        session.add(Run(id="20260825-20260825", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", status="active"))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
    scheduler = SchedulerService(settings, session_factory=factory)
    execution = scheduler.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
    with Session(engine) as session:
        row = session.get(ScheduleExecution, execution.execution_id)
        row.model_name, row.model_digest, row.policy_version = "qwen3.8:27b", "a" * 64, "policy-v1"
        session.commit()

    class PreconditionOrchestrator:
        def create_execution(self, **kwargs):
            raise ScreeningCreationError("precondition_failed")

    pipeline = ScheduledPipeline(settings, session_factory=factory, pipeline=ModeStages(), orchestrator=PreconditionOrchestrator(), ollama=FakeOllama())
    result = pipeline.run_daily(execution.execution_id)
    assert result.failure_reason == "ollama_unavailable"


def test_weekly_uses_one_latest_valid_daily_execution_per_date(tmp_path: Path):
    db = tmp_path / "weekly.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    start, end = date(2026, 8, 17), date(2026, 8, 23)
    with Session(engine) as session:
        session.add(ScheduleReservation(run_key="weekly:20260817-20260823", job_kind="weekly", window_from=start, window_to=end, timezone="Asia/Seoul", created_at=datetime(2026, 8, 24, tzinfo=timezone.utc)))
        for offset in range(7):
            day = start + timedelta(days=offset)
            key = f"{day:%Y%m%d}-{day:%Y%m%d}"
            session.add(ScheduleReservation(run_key=key, job_kind="daily", window_from=day, window_to=day, timezone="Asia/Seoul", created_at=datetime(2026, 8, 24, tzinfo=timezone.utc)))
            session.add(ScheduleExecution(execution_id="sched-" + f"{offset:02x}" * 16, run_key=key, job_kind="daily", trigger="schedule", status="부분 성공", requested_by="system:scheduler", finished_at=datetime(2026, 8, 25 + offset, tzinfo=timezone.utc), result_count=1))
        # A recovery success supersedes the original partial on the same day.
        session.add(ScheduleExecution(execution_id="sched-" + "f" * 32, run_key="20260817-20260817", job_kind="daily", trigger="manual", status="성공", recovery_of_execution_id="sched-" + "00" * 16, requested_by="operator", finished_at=datetime(2026, 9, 1, tzinfo=timezone.utc), result_count=2))
        # A later failure does not erase the last valid completed result.
        session.add(ScheduleExecution(execution_id="sched-" + "e" * 32, run_key="20260818-20260818", job_kind="daily", trigger="manual", status="실패", requested_by="operator", finished_at=datetime(2026, 9, 2, tzinfo=timezone.utc)))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
    pipeline = ScheduledPipeline(settings, session_factory=factory)
    weekly = ScheduleReservation(run_key="weekly:20260817-20260823", job_kind="weekly", window_from=start, window_to=end)
    # The helper only needs reservation identity and performs a fresh DB read.
    rows = pipeline._latest_completed_daily(weekly)
    assert len(rows) == 7
    assert rows[0].execution_id == "sched-" + "f" * 32
    assert rows[1].execution_id != "sched-" + "e" * 32


def test_weekly_report_interruption_never_flows_to_success(tmp_path: Path):
    db = tmp_path / "weekly-interrupted.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    start, end = date(2026, 8, 17), date(2026, 8, 23)
    weekly_key = "weekly:20260817-20260823"
    with Session(engine) as session:
        session.add(ScheduleReservation(run_key=weekly_key, job_kind="weekly", window_from=start, window_to=end, timezone="Asia/Seoul"))
        session.add(ScheduleExecution(execution_id="sched-" + "9" * 32, run_key=weekly_key, job_kind="weekly", trigger="schedule", status="예약", requested_by="system:scheduler"))
        for offset in range(7):
            day = start + timedelta(days=offset)
            key = f"{day:%Y%m%d}-{day:%Y%m%d}"
            session.add(ScheduleReservation(run_key=key, job_kind="daily", window_from=day, window_to=day, timezone="Asia/Seoul"))
            session.add(ScheduleExecution(execution_id="sched-" + f"{offset + 10:02x}" * 16, run_key=key, job_kind="daily", trigger="schedule", status="성공", requested_by="system:scheduler", finished_at=datetime(2026, 8, 25 + offset, tzinfo=timezone.utc), result_count=1))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
    pipeline = ScheduledPipeline(settings, session_factory=factory, pipeline=ModeStages("weekly_report"))
    result = pipeline.run_weekly("sched-" + "9" * 32)
    assert result.status == "부분 성공"
    assert result.failure_reason == "weekly_report_interrupted"


def test_concurrent_daily_claim_runs_stages_once_on_file_sqlite(tmp_path: Path):
    db = tmp_path / "concurrent.db"
    engine = create_engine(f"sqlite:///{db}", future=True, connect_args={"timeout": 5})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as session:
        session.add(Run(id="20260825-20260825", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", status="active"))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
    scheduler = SchedulerService(settings, session_factory=factory)
    execution = scheduler.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
    with Session(engine) as session:
        row = session.get(ScheduleExecution, execution.execution_id)
        row.model_name, row.model_digest = "qwen3.8:27b", "a" * 64
        session.commit()

    class BlockingStages(FakeStages):
        def __init__(self):
            self.calls = 0
            self.lock = Lock()
            self.claimed = Event()
            self.release = Event()

        def collect(self, **kwargs):
            with self.lock:
                self.calls += 1
            self.claimed.set()
            assert self.release.wait(5)
            return super().collect(**kwargs)

    stages = BlockingStages()
    first = ScheduledPipeline(settings, session_factory=factory, pipeline=stages, ollama=FakeOllama())
    second = ScheduledPipeline(settings, session_factory=factory, pipeline=stages, ollama=FakeOllama())
    barrier = Barrier(2)
    results = []

    def invoke(pipeline):
        barrier.wait()
        results.append(pipeline.run_daily(execution.execution_id))

    threads = [Thread(target=invoke, args=(pipeline,)) for pipeline in (first, second)]
    for thread in threads:
        thread.start()
    assert stages.claimed.wait(5)
    stages.release.set()
    for thread in threads:
        thread.join(10)
    assert all(not thread.is_alive() for thread in threads)
    assert stages.calls == 1
    assert len(results) == 2
    with Session(engine) as session:
        assert session.get(ScheduleExecution, execution.execution_id).status == "성공"


def test_failed_judgment_with_partial_artifact_finishes_partial_success(tmp_path: Path):
    db = tmp_path / "judgment-partial-failed.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as session:
        session.add(Run(id="20260825-20260825", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", status="active"))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
    scheduler = SchedulerService(settings, session_factory=factory)
    execution = scheduler.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
    with Session(engine) as session:
        row = session.get(ScheduleExecution, execution.execution_id)
        row.model_name, row.model_digest = "qwen3.8:27b", "a" * 64
        session.commit()
    stages = ModeStages(judgment={"status": "실패", "failure_reason": "judgment_failed", "candidate_count": 3, "result_count": 1, "failure_count": 2, "partial_artifact": True})
    result = ScheduledPipeline(settings, session_factory=factory, pipeline=stages, ollama=FakeOllama()).run_daily(execution.execution_id)
    assert result.status == "부분 성공"
    assert result.failure_reason == "judgment_failed"
    assert (result.candidate_count, result.result_count, result.failure_count, result.partial_artifact) == (3, 1, 2, True)


def test_zero_candidate_success_is_terminal_zero_result_failure(tmp_path: Path):
    db = tmp_path / "zero-candidate.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as session:
        session.add(Run(id="20260825-20260825", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", status="active"))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
    scheduler = SchedulerService(settings, session_factory=factory)
    execution = scheduler.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
    with Session(engine) as session:
        row = session.get(ScheduleExecution, execution.execution_id)
        row.model_name, row.model_digest = "qwen3.8:27b", "a" * 64
        session.commit()
    stages = ModeStages(judgment={"status": "성공", "candidate_count": 0, "result_count": 0, "failure_count": 0})
    result = ScheduledPipeline(settings, session_factory=factory, pipeline=stages, ollama=FakeOllama()).run_daily(execution.execution_id)
    assert result.status == "실패"
    assert result.failure_reason == "judgment_zero_result"
    assert (result.candidate_count, result.result_count, result.failure_count) == (0, 0, 0)


def test_model_inspection_creation_error_is_ollama_unavailable(tmp_path: Path):
    db = tmp_path / "model-inspection-error.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as session:
        session.add(Run(id="20260825-20260825", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", status="active"))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{db}", scheduler_enabled=False)
    scheduler = SchedulerService(settings, session_factory=factory)
    execution = scheduler.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
    with Session(engine) as session:
        row = session.get(ScheduleExecution, execution.execution_id)
        row.model_name, row.model_digest, row.policy_version = "qwen3.8:27b", "a" * 64, "policy-v1"
        session.commit()

    class ModelInspectionOrchestrator:
        def create_execution(self, **kwargs):
            raise ScreeningCreationError("model_inspection")

    result = ScheduledPipeline(settings, session_factory=factory, pipeline=ModeStages(), orchestrator=ModelInspectionOrchestrator(), ollama=FakeOllama()).run_daily(execution.execution_id)
    assert result.failure_reason == "ollama_unavailable"
    with Session(engine) as session:
        assert session.scalar(select(ScreeningExecution)) is None
