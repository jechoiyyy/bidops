from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.screening.routers.schedule import router


def _client() -> TestClient:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    application = FastAPI()
    application.include_router(router)

    def override_db():
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    return TestClient(application)


def test_schedule_settings_duplicate_audit_and_always_on_off() -> None:
    with _client() as client:
        settings = client.get("/api/schedule/settings")
        assert settings.status_code == 200
        assert settings.json()["timezone"] == "Asia/Seoul"
        changed = client.patch(
            "/api/schedule/settings",
            json={"daily_time": "03:15", "updated_by": "operator"},
        )
        assert changed.status_code == 200
        assert changed.json()["daily_time"] == "03:15"

        body = {
            "job_kind": "daily",
            "window_from": "2026-08-25",
            "window_to": "2026-08-25",
            "recovery_of_execution_id": None,
            "requested_by": "operator",
        }
        first = client.post("/api/schedule/executions", json=body)
        duplicate = client.post("/api/schedule/executions", json=body)
        assert first.status_code == duplicate.status_code == 202
        assert duplicate.json()["status"] == "건너뜀"
        assert duplicate.json()["duplicate_of_execution_id"] == first.json()["execution_id"]

        listed = client.get("/api/schedule/executions", params={"status": "건너뜀"})
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        off = client.put(
            "/api/schedule/always-on",
            json={"enabled": False, "confirmed_by": "operator", "quality_gate_result_id": None},
        )
        assert off.status_code == 200
        assert off.json()["configured_enabled"] is False


def test_schedule_window_validation_is_422() -> None:
    with _client() as client:
        response = client.post(
            "/api/schedule/executions",
            json={
                "job_kind": "weekly",
                "window_from": "2026-08-25",
                "window_to": "2026-08-31",
                "recovery_of_execution_id": None,
                "requested_by": "operator",
            },
        )
        assert response.status_code == 422
