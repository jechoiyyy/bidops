from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.routers.policies import router as policy_router
from app.routers.quality_gates import router as gate_router
from app.screening.policy import load_policy_file


def _client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    application = FastAPI()
    application.include_router(policy_router)
    application.include_router(gate_router)

    def override_db():
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    return TestClient(application)


def test_policy_create_candidate_and_duplicate_are_deterministic() -> None:
    body = load_policy_file()
    body = {**body, "policy_version": "api-policy-1"}
    body.pop("schema_version")
    payload = {**body, "created_by": " operator "}
    with _client() as client:
        created = client.post("/api/policies", json=payload)
        assert created.status_code == 201
        assert created.json()["status"] == "draft"
        duplicate = client.post("/api/policies", json=payload)
        assert duplicate.status_code == 409
        candidate = client.post(
            "/api/policies/api-policy-1/candidate",
            json={"confirmed_by": " operator "},
        )
        assert candidate.status_code == 200
        assert candidate.json()["status"] == "activation_candidate"
        again = client.post(
            "/api/policies/api-policy-1/candidate",
            json={"confirmed_by": "operator"},
        )
        assert again.status_code == 409


def test_quality_gate_purpose_profile_precondition_is_422_without_writes() -> None:
    with _client() as client:
        response = client.post(
            "/api/quality-gates",
            json={
                "purpose": "model_comparison",
                "policy_version": "missing",
                "profile_source": "current",
                "created_by": "operator",
            },
        )
        assert response.status_code == 422
