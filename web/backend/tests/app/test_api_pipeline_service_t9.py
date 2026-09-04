from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.main import lifespan
from app.lifecycle.models import Run
from app.lifecycle.routers.runs import router as runs_router
from app.lifecycle.services.pipeline import PipelineExecution, PipelineLogLine


def _db_application() -> tuple[FastAPI, object, PipelineExecution]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(
            Run(
                id="run-1",
                window_from=date(2026, 8, 26),
                window_to=date(2026, 8, 26),
                timezone="Asia/Seoul",
                generated_at=now,
                status="active",
            )
        )
        session.commit()

    execution = PipelineExecution(
        execution_id="pipe-" + "1" * 32,
        source_run_id="run-1",
        stage="collect",
        command=("collect_notices.py",),
        target_directory=Path("data/runs/run-1"),
        status="running",
        started_at=now,
    )
    execution.lines.append(
        PipelineLogLine(
            timestamp=now,
            stream="stdout",
            level="info",
            message="pipeline is running",
        )
    )

    class FakePipeline:
        def latest_for(self, run_id: str, stage: str):
            return execution if run_id == "run-1" and stage == "collect" else None

        def logs_for(self, run_id: str, execution_id: str | None = None):
            if run_id != "run-1" or (execution_id and execution_id != execution.execution_id):
                return []
            return [execution]

        def start(self, run, stage: str, *, from_raw: bool = False):
            return execution

    application = FastAPI()
    application.include_router(runs_router)
    application.state.pipeline_service = FakePipeline()

    def override_db():
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    return application, engine, execution


def test_run_detail_and_logs_use_injected_app_pipeline_service() -> None:
    application, _engine, execution = _db_application()
    with TestClient(application) as client:
        detail = client.get("/api/runs/run-1")
        logs = client.get("/api/runs/run-1/pipeline/logs")

    assert detail.status_code == 200, detail.text
    collect = next(item for item in detail.json()["pipeline"] if item["name"] == "collect_normalize")
    assert collect["execution_id"] == execution.execution_id
    assert collect["status"] == "running"
    assert logs.status_code == 200, logs.text
    assert logs.json()["executions"][0]["execution_id"] == execution.execution_id
    assert logs.json()["items"][0]["message"] == "pipeline is running"


def test_repeated_lifespans_replace_and_clear_runtime_pipeline_service(monkeypatch) -> None:
    created: list[object] = []

    class FakeRuntime:
        def __init__(self) -> None:
            self.pipeline_service = object()
            self.started = False
            self.stopped = False
            created.append(self)

        def start(self) -> None:
            self.started = True

        def shutdown(self) -> None:
            self.stopped = True

    monkeypatch.setattr("app.main.init_db", lambda: None)
    application = FastAPI(lifespan=lifespan)
    application.state.runtime_factory = FakeRuntime
    # The lifespan intentionally sees an injected runtime and therefore does
    # not need a database dependency for this isolation test.
    with TestClient(application):
        first_service = application.state.pipeline_service
        assert created[0].started
    assert not hasattr(application.state, "pipeline_service")
    with TestClient(application):
        second_service = application.state.pipeline_service
        assert created[1].started
    assert first_service is not second_service
    assert all(runtime.stopped for runtime in created)
