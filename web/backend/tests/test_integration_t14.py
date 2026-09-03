"""T14-A integration boundaries on a migrated PostgreSQL database.

These tests deliberately use the process-wide database configured by the
pytest harness.  Before pytest imports ``app.db``, the harness creates and
migrates a private database on a disposable PostgreSQL 17 server and supplies
isolated runtime paths.  Ollama is always a scripted transport; a regression
that opens a real socket therefore fails at the fake boundary instead of
making CI network-dependent.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app import main
from app.config import Settings, get_settings
from app.db import ALEMBIC_HEAD, SessionLocal, current_revision, ensure_database_current
from app.models import (
    AgencyPortal,
    AlwaysOnState,
    CompanyProfileSnapshot,
    Run,
    ScheduleExecution,
    ScreeningExecution,
    ScreeningPolicy,
)
from app.routers.runs import router as runs_router
from app.routers.screening import router as screening_router
from app.runtime import ApplicationRuntime
from app.screening.ollama import OllamaClient
from app.services.scheduler import SchedulerService
from tests.fakes.ollama import FakeOllamaTransport


DIGEST = "a" * 64
PROFILE_VERSION = f"company-profile.sha256:{DIGEST}"


def _application() -> FastAPI:
    application = FastAPI(lifespan=main.lifespan)
    application.include_router(runs_router)
    application.include_router(screening_router)
    return application


def _patch_ollama(monkeypatch: pytest.MonkeyPatch, transport: FakeOllamaTransport) -> None:
    """Make every runtime-owned Ollama client use the same fake transport."""

    def factory(settings: Settings | None = None, **_kwargs: object) -> OllamaClient:
        return OllamaClient(settings=settings, transport=transport)

    # ApplicationRuntime resolves this name when it constructs its one shared
    # client, which is then passed to both the orchestrator and worker.
    monkeypatch.setattr("app.runtime.OllamaClient", factory)


def _seed_run(run_id: str) -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        session.add(
            Run(
                id=run_id,
                window_from=date(2026, 8, 26),
                window_to=date(2026, 8, 26),
                timezone="Asia/Seoul",
                generated_at=now,
                status="active",
                counts_json={},
            )
        )
        session.commit()


def _seed_queue_dependencies(policy_version: str) -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        session.add(
            ScreeningPolicy(
                policy_version=policy_version,
                schema_version="bidops.screening-policy.v1",
                prompt_version="t14-prompt",
                content_digest=DIGEST,
                status="activation_candidate",
                perspective_prompts_json={},
                counterargument_prompt_json={},
                synthesis_prompt_json={},
                candidate_selection_json={},
                thresholds_json={},
                created_at=now,
                created_by="t14-test",
            )
        )
        session.add(
            CompanyProfileSnapshot(
                digest=DIGEST,
                version=PROFILE_VERSION,
                source_kind="working_tree",
                source_ref="docs/reference/company-profile.md",
                artifact_path=f"web/data/profile-snapshots/{DIGEST}.md",
                created_at=now,
            )
        )
        session.commit()


def test_migrated_database_is_at_head_before_lifespan() -> None:
    """The pytest harness proves migration before any app startup."""

    assert os.environ.get("BIDOPS_DATABASE_URL", "").startswith(("postgresql://", "postgresql+"))
    assert Path(os.environ["BIDOPS_ROOT"]).resolve() == Path(__file__).resolve().parents[3]
    assert current_revision() == ALEMBIC_HEAD


def test_full_lifespan_does_not_seed_portals_and_portal_api_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A head DB stays empty until an operator calls the portal API."""

    transport = FakeOllamaTransport()
    _patch_ollama(monkeypatch, transport)
    portal_id: int | None = None

    try:
        with TestClient(main.app) as client:
            with SessionLocal() as session:
                assert session.scalar(select(func.count()).select_from(AgencyPortal)) == 0

            created = client.post(
                "/api/portals",
                headers={"X-BidOps-Actor-Name": "t14-test"},
                json={
                    "agency_pattern": "T14 기관",
                    "system_name": "T14 조달",
                    "search_url_template": "https://example.invalid/search?q={query}",
                    "enabled": True,
                    "note": "explicit test fixture",
                },
            )
            assert created.status_code == 201, created.text
            portal_id = created.json()["id"]

            with SessionLocal() as session:
                assert session.scalar(select(func.count()).select_from(AgencyPortal)) == 1

        # A second complete lifespan does not reseed or duplicate the explicit row.
        with TestClient(main.app) as client:
            listed = client.get("/api/portals")
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()] == [portal_id]
            with SessionLocal() as session:
                assert session.scalar(select(func.count()).select_from(AgencyPortal)) == 1
    finally:
        # Keep the shared fresh runner database clean for later tests.
        if portal_id is not None:
            with SessionLocal() as session:
                session.query(AgencyPortal).filter(AgencyPortal.id == portal_id).delete()
                session.commit()


def test_lifespan_rejects_stale_unversioned_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stale_path = tmp_path / "stale.db"
    stale_engine = create_engine(f"sqlite:///{stale_path}")
    with stale_engine.begin() as connection:
        connection.execute(text("CREATE TABLE run (id TEXT PRIMARY KEY)"))

    monkeypatch.setattr(main, "init_db", lambda: ensure_database_current(stale_engine))
    application = FastAPI(lifespan=main.lifespan)
    with pytest.raises(RuntimeError, match="existing database is unversioned"):
        with TestClient(application):
            pass


def test_scheduler_disabled_still_starts_shared_worker_with_zero_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeOllamaTransport()
    _patch_ollama(monkeypatch, transport)
    application = _application()

    with TestClient(application):
        runtime = application.state.runtime
        assert get_settings().scheduler_enabled is False
        assert runtime.worker_thread is not None
        assert runtime.worker_thread.is_alive()
        assert runtime.scheduler_service.scheduler.running is False
        assert runtime.scheduler_service.scheduler.get_jobs() == []

    assert runtime.stop_event.is_set()
    assert runtime.worker_thread is not None
    assert not runtime.worker_thread.is_alive()
    assert not hasattr(application.state, "runtime")
    assert transport.generate_requests == []


def test_fastapi_enqueue_and_stop_share_runtime_queue_without_model_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "t14-api-queue"
    policy_version = "t14-policy-api"
    execution_id = "scr-" + "1" * 32
    _seed_run(run_id)
    _seed_queue_dependencies(policy_version)
    transport = FakeOllamaTransport()
    _patch_ollama(monkeypatch, transport)
    holder: dict[str, ApplicationRuntime] = {}

    def runtime_factory() -> ApplicationRuntime:
        runtime = ApplicationRuntime()

        # Keep this boundary test deterministic: the worker is the same
        # runtime-owned object and thread, but waits while the API exercises
        # the queued -> interrupted stop transition.
        def idle_worker(stop_event) -> None:  # type: ignore[no-untyped-def]
            stop_event.wait()

        runtime.worker.run_forever = idle_worker  # type: ignore[method-assign]
        holder["runtime"] = runtime
        return runtime

    application = _application()
    application.state.runtime_factory = runtime_factory
    with TestClient(application) as client:
        runtime = holder["runtime"]

        def create_execution(**kwargs: object) -> SimpleNamespace:
            row = runtime.store.enqueue(
                execution_id=execution_id,
                trigger="manual_run",
                source_run_id=str(kwargs["run_id"]),
                scope="full_run",
                requested_by=str(kwargs["requested_by"]),
                policy_version=policy_version,
                prompt_version="t14-prompt",
                model_name="qwen3.8:27b",
                model_digest=DIGEST,
                company_profile_version=PROFILE_VERSION,
                company_profile_digest=DIGEST,
                input_artifact_path=f"data/screening-executions/{execution_id}/screening-input.json",
                input_artifact_digest=DIGEST,
                artifact_dir=f"data/screening-executions/{execution_id}",
            )
            return SimpleNamespace(execution_id=row.execution_id)

        runtime.orchestrator.create_execution = create_execution  # type: ignore[method-assign]
        response = client.post(
            f"/api/runs/{run_id}/pipeline/judgment",
            json={
                "policy_version": policy_version,
                "profile_source": "current",
                "requested_by": "operator:t14",
            },
        )
        assert response.status_code == 202, response.text
        assert response.json()["execution_id"] == execution_id
        assert response.json()["status"] == "대기"
        assert application.state.screening_store is runtime.store

        stopped = client.post(
            f"/api/screening/executions/{execution_id}/stop",
            json={"requested_by": "operator:t14"},
        )
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["status"] == "중단됨"

    with SessionLocal() as session:
        row = session.scalar(
            select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id)
        )
        assert row is not None
        assert row.status == "중단됨"
    assert transport.generate_requests == []


def test_ollama_unavailable_is_exact_pre_enqueue_503_with_no_execution_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "t14-api-unavailable"
    _seed_run(run_id)
    secret = "t14-secret-must-not-escape"
    transport = FakeOllamaTransport(inspect_response=ConnectionError(secret))
    _patch_ollama(monkeypatch, transport)
    application = _application()

    with TestClient(application) as client:
        response = client.post(
            f"/api/runs/{run_id}/pipeline/judgment",
            json={
                "policy_version": "missing-policy-is-never-read",
                "profile_source": "current",
                "requested_by": "operator:t14",
            },
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "모델 사전 확인을 완료할 수 없습니다."}
        assert secret not in response.text

    with SessionLocal() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ScreeningExecution)
                .where(ScreeningExecution.source_run_id == run_id)
            )
            == 0
        )
    assert transport.generate_requests == []


def test_scheduler_env_true_but_database_switch_false_callback_is_noop(
) -> None:
    transport = FakeOllamaTransport()
    settings = Settings(
        bidops_root=Path(os.environ["BIDOPS_ROOT"]),
        data_dir=Path(os.environ["BIDOPS_DATA_DIR"]),
        attachments_dir=Path(os.environ["BIDOPS_ATTACHMENTS_DIR"]),
        database_url=os.environ["BIDOPS_DATABASE_URL"],
        scheduler_enabled=True,
    )
    callbacks: list[str] = []
    service = SchedulerService(
        settings,
        session_factory=SessionLocal,
        ollama=OllamaClient(settings=settings, transport=transport),
        on_daily=callbacks.append,
    )
    try:
        assert service._daily_callback() is None
        assert callbacks == []
        assert transport.requests == []
    finally:
        service.shutdown()

    with SessionLocal() as session:
        state = session.get(AlwaysOnState, 1)
        assert state is not None and state.enabled is False
        assert session.scalar(select(func.count()).select_from(ScheduleExecution)) == 0


def test_shutdown_cleans_runtime_thread_and_state(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeOllamaTransport()
    _patch_ollama(monkeypatch, transport)
    application = _application()
    with TestClient(application):
        runtime = application.state.runtime
        assert runtime.worker_thread is not None and runtime.worker_thread.is_alive()
    assert runtime.stop_event.is_set()
    assert runtime.worker_thread is not None and not runtime.worker_thread.is_alive()
    assert not hasattr(application.state, "screening_worker")
