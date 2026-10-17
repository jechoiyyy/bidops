"""RL-00 T6·T7: single real-company context REST, demo guard, and re-registration (PostgreSQL)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

import app.main as main_module
from app.core.config import get_settings
from app.core.db import get_db
from app.deep_review.models import CompanyKnowledgeBinding, CompanyKnowledgeBindingEvent
from app.deep_review.services.company_knowledge import (
    activate_company_knowledge,
    import_company_knowledge,
)
from tests.deep_review.test_company_knowledge import (  # noqa: F401 - shared fixtures
    REAL_STATUS_COUNTS,
    _prepared,
    _prepared_real,
    fictional_import_demo,
    object_store,
)
from tests.postgres import migrated_engine, requires_postgres


pytestmark = requires_postgres

CONTEXT_KEYS = {"schema_version", "company", "expiry_warning_days", "active_graph_version"}
COMPANY_KEYS = {"company_id", "slug", "name", "is_fictional", "created_at"}
ATTENTION = REAL_STATUS_COUNTS["proposed"] + REAL_STATUS_COUNTS["unknown"]


@pytest.fixture
def pg_engine():
    with migrated_engine() as bind:
        yield bind


@contextmanager
def _client(bind, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, demo: bool = False):
    """Assembled app (lifecycle + deep_review) with a tiny built SPA mounted last."""

    sessions = sessionmaker(bind=bind, class_=Session, expire_on_commit=False)

    def request_session():
        with sessions() as session:
            yield session

    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(demo_enabled=demo))
    application = main_module.create_app(
        modules=("lifecycle", "deep_review"), mount_frontend=False
    )
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text("<!doctype html><title>spa</title>", encoding="utf-8")
    main_module.install_frontend(application, dist)
    application.dependency_overrides[get_db] = request_session
    with TestClient(application) as client:
        yield client, sessions


def _import(sessions, prepared, *, activate: bool = True):
    with sessions() as session:
        with session.begin():
            imported = import_company_knowledge(session, prepared, actor="등록 담당자")
            activation = None
            if activate:
                activation = activate_company_knowledge(
                    session,
                    company_id=imported.company_id,
                    graph_version_id=imported.graph_version_id,
                    actor="활성 담당자",
                )
    return imported, activation


def _workload(client) -> dict[str, tuple[int | None, str | None]]:
    response = client.get("/api/workload")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    # RL-01이 `company_attention` 뒤에 `briefing_pending`을 더했다(spec "최종 키 순서").
    assert [item["key"] for item in items[-2:]] == ["company_attention", "briefing_pending"]
    return {item["key"]: (item["count"], item["unavailable_reason"]) for item in items}


def test_t6_company_context_404_then_strict_shape_and_attention_count(
    pg_engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, empty_extensions
) -> None:
    monkeypatch.setenv("BIDOPS_COMPANY_EXPIRY_WARNING_DAYS", "45")
    get_settings.cache_clear()
    with _client(pg_engine, monkeypatch, tmp_path) as (client, sessions):
        missing = client.get("/api/company")
        assert missing.status_code == 404, missing.text
        assert missing.json() == {
            "error": {
                "code": "company_not_registered",
                "message": missing.json()["error"]["message"],
                "details": None,
            },
            "request_id": None,
        }
        assert missing.json()["error"]["message"]
        assert _workload(client)["company_attention"] == (None, "provider_absent")

        # Fictional rows alone are not "the company": still 404 and provider absent.
        _import(sessions, _prepared())
        assert client.get("/api/company").status_code == 404
        assert _workload(client)["company_attention"] == (None, "provider_absent")

        imported, _activation = _import(sessions, _prepared_real(), activate=False)
        unbound = client.get("/api/company")
        assert unbound.status_code == 200, unbound.text
        assert unbound.json()["active_graph_version"] is None
        assert _workload(client)["company_attention"] == (None, "company_profile_not_ready")

        with sessions() as session:
            with session.begin():
                activate_company_knowledge(
                    session,
                    company_id=imported.company_id,
                    graph_version_id=imported.graph_version_id,
                    actor="활성 담당자",
                )
        response = client.get("/api/company")
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == CONTEXT_KEYS
        assert body["schema_version"] == "bidops.company-context.v1"
        assert set(body["company"]) == COMPANY_KEYS
        assert body["company"]["company_id"] == str(imported.company_id)
        assert body["company"]["slug"] == "real-test-co"
        assert body["company"]["is_fictional"] is False
        assert body["expiry_warning_days"] == 45
        assert set(body["active_graph_version"]) == {"graph_version_id", "created_at"}
        assert body["active_graph_version"]["graph_version_id"] == str(imported.graph_version_id)
        assert body["active_graph_version"]["created_at"].endswith(("Z", "+00:00"))

        profile = client.get(f"/api/companies/{imported.company_id}/profile")
        assert profile.status_code == 200, profile.text
        facts = profile.json()["facts"]
        statuses = {fact["status"] for fact in facts}
        assert {"proposed", "unknown", "confirmed"} <= statuses
        assert {fact["origin"] for fact in facts} <= {
            "company_brochure", "homepage", "user_interview", "agent_proposal",
        }
        attention = sum(fact["status"] in {"proposed", "unknown"} for fact in facts)
        assert attention == ATTENTION
        assert _workload(client)["company_attention"] == (ATTENTION, None)
    get_settings.cache_clear()


def test_t6_demo_off_keeps_demo_company_paths_absent(
    pg_engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, empty_extensions
) -> None:
    with _client(pg_engine, monkeypatch, tmp_path, demo=False) as (client, sessions):
        imported, _activation = _import(sessions, _prepared_real())
        company_id = imported.company_id
        not_found = {"detail": "Not Found"}

        # The SPA still serves its own routes (proves the fallback is mounted) ...
        assert client.get("/company").status_code == 200
        # ... but the demo company UI and comparison stay absent before the fallback.
        for path in (
            "/companies",
            f"/companies/{company_id}",
            f"/companies/{company_id}/profile",
            "/pre-specs/1/company-comparison",
            "/api/pre-specs/1/company-comparison",
            f"/api/companies/{company_id}/pre-specs",
            f"/api/companies/{company_id}/pre-specs/1",
            f"/api/companies/{company_id}/opportunities/1/tracking",
        ):
            response = client.get(path)
            assert response.status_code == 404, path
            assert response.json() == not_found, path
        for path, body in (
            (f"/api/companies/{company_id}/pre-specs/1/deep-review-previews", {"bundle_id": str(uuid4())}),
            (f"/api/companies/{company_id}/pre-specs/1/deep-reviews", {"request_id": str(uuid4())}),
            (f"/api/companies/{company_id}/deep-reviews/{uuid4()}/attempts", {"request_id": str(uuid4())}),
        ):
            response = client.post(path, json=body)
            assert response.status_code == 404, path
            assert response.json() == not_found, path
        tracking = client.patch(
            f"/api/companies/{company_id}/opportunities/1/tracking",
            json={"tracking_status": "계속 추적", "reason": "x", "expected_revision": 0,
                  "request_id": str(uuid4())},
        )
        assert tracking.status_code == 404 and tracking.json() == not_found

        # The demo-independent company reads stay open.
        for path in (
            "/api/company",
            "/api/companies",
            f"/api/companies/{company_id}",
            f"/api/companies/{company_id}/profile",
            f"/api/companies/{company_id}/knowledge-graph",
        ):
            assert client.get(path).status_code == 200, path

    # With the demo on, the same SPA route is served again (guard only, no route change).
    with _client(pg_engine, monkeypatch, tmp_path, demo=True) as (client, _sessions):
        assert client.get("/companies").status_code == 200


def test_t7_reimport_creates_new_version_and_keeps_previous_readable(
    pg_engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, empty_extensions
) -> None:
    with _client(pg_engine, monkeypatch, tmp_path) as (client, sessions):
        first, first_activation = _import(sessions, _prepared_real())
        before = client.get("/api/company").json()
        first_profile = client.get(f"/api/companies/{first.company_id}/profile").json()
        assert first_activation.revision == 1

        second, second_activation = _import(sessions, _prepared_real(
            version="real-test-2026-10-17", credit_status="confirmed",
        ))
        assert second.created is True
        assert second.company_id == first.company_id
        assert second.graph_version_id != first.graph_version_id
        assert second.profile_version_id != first.profile_version_id
        assert second_activation.revision == first_activation.revision + 1

        after = client.get("/api/company").json()
        assert after["company"] == before["company"]
        assert after["active_graph_version"]["graph_version_id"] == str(second.graph_version_id)
        assert datetime.fromisoformat(after["active_graph_version"]["created_at"]) >= (
            datetime.fromisoformat(before["active_graph_version"]["created_at"])
        )

        current = client.get(f"/api/companies/{first.company_id}/profile").json()
        credit = {fact["fact_key"]: fact for fact in current["facts"]}["qual:credit"]
        assert credit["status"] == "confirmed" and credit["origin"] == "user_interview"
        assert _workload(client)["company_attention"] == (ATTENTION - 1, None)

        past = client.get(
            f"/api/companies/{first.company_id}/profile",
            params={"graph_version_id": str(first.graph_version_id)},
        )
        assert past.status_code == 200, past.text
        assert past.json() == first_profile
        past_credit = {fact["fact_key"]: fact for fact in past.json()["facts"]}["qual:credit"]
        assert past_credit["status"] == "proposed"

        with sessions() as session:
            binding = session.get(CompanyKnowledgeBinding, first.company_id)
            assert binding is not None and binding.revision == 2
            assert binding.graph_version_id == second.graph_version_id
            events = list(session.scalars(
                select(CompanyKnowledgeBindingEvent)
                .where(CompanyKnowledgeBindingEvent.company_id == first.company_id)
                .order_by(CompanyKnowledgeBindingEvent.revision)
            ))
            assert [(event.revision, event.previous_graph_version_id) for event in events] == [
                (1, None), (2, first.graph_version_id),
            ]
            assert session.scalar(
                select(func.count()).select_from(CompanyKnowledgeBindingEvent)
            ) == 2
        assert isinstance(UUID(after["active_graph_version"]["graph_version_id"]), UUID)
