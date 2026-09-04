from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.db import Base, get_db
from app.lifecycle.models import Run
from app.screening.models import CompanyProfileSnapshot, ScreeningExecution, ScreeningPolicy
from app.routers.runs import router as runs_router
from app.screening.routers.screening import run_router as screening_run_router
from app.runtime import ApplicationRuntime


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def test_judgment_endpoint_enqueues_full_manual_run_without_waiting(tmp_path: Path) -> None:
    engine = _engine()
    now = datetime.now(timezone.utc)
    digest = "a" * 64
    execution_id = "scr-" + "1" * 32
    with Session(engine) as session:
        session.add(Run(id="run-1", window_from=date(2026, 8, 26), window_to=date(2026, 8, 26), generated_at=now, status="active"))
        session.add(ScreeningPolicy(
            policy_version="policy-1", schema_version="bidops.screening-policy.v1", prompt_version="prompt-1",
            content_digest=digest, status="activation_candidate", perspective_prompts_json={},
            counterargument_prompt_json={}, synthesis_prompt_json={}, candidate_selection_json={}, thresholds_json={},
            created_at=now, created_by="operator",
        ))
        session.add(CompanyProfileSnapshot(
            digest=digest, version=f"company-profile.sha256:{digest}", source_kind="working_tree",
            source_ref="docs/reference/company-profile.md", artifact_path=f"web/data/profile-snapshots/{digest}.md", created_at=now,
        ))
        session.add(ScreeningExecution(
            execution_id=execution_id, trigger="manual_run", source_run_id="run-1", scope="full_run", status="대기",
            requested_by="operator", policy_version="policy-1", prompt_version="prompt-1", model_name="qwen3.8:27b",
            model_digest=digest, company_profile_version=f"company-profile.sha256:{digest}", company_profile_digest=digest,
            input_artifact_path=f"data/screening-executions/{execution_id}/screening-input.json", input_artifact_digest=digest,
            artifact_dir=f"data/screening-executions/{execution_id}", queued_at=now,
        ))
        session.commit()
    with Session(engine) as session:
        assert session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id)) is not None

    class FakeOllama:
        def inspect_model(self, *, refresh: bool = False):
            assert refresh is True
            return SimpleNamespace(model_name="qwen3.8:27b", digest=digest)

    class FakeOrchestrator:
        ollama = FakeOllama()

        def create_execution(self, **kwargs):
            assert kwargs["scope"] == "full_run"
            assert kwargs["trigger"] == "manual_run"
            with Session(engine) as session:
                assert session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id)) is not None
            return SimpleNamespace(execution_id=execution_id)

    application = FastAPI()
    # 판정 실행 endpoint 의 제공 모듈은 screening 이다(명세 §5.3). 경로가 그대로
    # `/api/runs/...` 이므로, 회차 router 의 일반 단계 경로보다 먼저 등록한다.
    application.include_router(screening_run_router)
    application.include_router(runs_router)
    application.state.screening_orchestrator = FakeOrchestrator()

    def override_db():
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        response = client.post(
            "/api/runs/run-1/pipeline/judgment",
            json={"policy_version": "policy-1", "profile_source": "current", "requested_by": "operator"},
        )
    assert response.status_code == 202, response.text
    assert response.json()["execution_id"] == execution_id
    assert response.json()["scope"] == "full_run"


def test_runtime_recovers_stale_execution_and_worker_runs_when_scheduler_disabled(tmp_path: Path) -> None:
    engine = _engine()
    now = datetime.now(timezone.utc)
    digest = "b" * 64
    with Session(engine) as session:
        session.add(Run(id="run-1", generated_at=now, status="active"))
        session.add(ScreeningPolicy(
            policy_version="policy-1", schema_version="bidops.screening-policy.v1", prompt_version="prompt-1",
            content_digest=digest, status="activation_candidate", perspective_prompts_json={},
            counterargument_prompt_json={}, synthesis_prompt_json={}, candidate_selection_json={}, thresholds_json={},
            created_at=now, created_by="operator",
        ))
        session.add(CompanyProfileSnapshot(
            digest=digest, version=f"company-profile.sha256:{digest}", source_kind="working_tree",
            source_ref="docs/reference/company-profile.md", artifact_path=f"web/data/profile-snapshots/{digest}.md", created_at=now,
        ))
        session.add(ScreeningExecution(
            execution_id="scr-" + "2" * 32, trigger="manual_run", source_run_id="run-1", scope="full_run",
            status="실행 중", active_slot=1, requested_by="operator", policy_version="policy-1", prompt_version="prompt-1",
            model_name="qwen3.8:27b", model_digest=digest, company_profile_version=f"company-profile.sha256:{digest}",
            company_profile_digest=digest, input_artifact_path="data/screening-executions/scr-" + "2" * 32 + "/screening-input.json",
            input_artifact_digest=digest, artifact_dir="data/screening-executions/scr-" + "2" * 32,
            queued_at=now - timedelta(minutes=2), started_at=now - timedelta(minutes=2), heartbeat_at=now - timedelta(minutes=2),
        ))
        session.commit()
    settings = Settings(bidops_root=tmp_path, database_url="sqlite://", scheduler_enabled=False)
    factory = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)
    runtime = ApplicationRuntime(settings, session_factory=factory)
    runtime.start()
    try:
        with Session(engine) as session:
            row = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == "scr-" + "2" * 32))
            assert row is not None and row.status == "중단됨" and row.stop_reason == "process_interrupted"
        assert runtime.worker_thread is not None and runtime.worker_thread.is_alive()
        assert not runtime.scheduler_service.scheduler.running
    finally:
        runtime.shutdown()
        runtime.shutdown()
    assert runtime.stop_event.is_set()
