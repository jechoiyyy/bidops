from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.models import (
    CompanyProfileSnapshot,
    QualityGate,
    QualityGateEvaluation,
    Run,
    ScreeningExecution,
    ScreeningPolicy,
)
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


def test_quality_gate_list_refreshes_stale_projection_before_filtering(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    digest = "a" * 64
    gate_id = "gate-" + "c" * 32
    pass_a = "scr-" + "a" * 32
    pass_b = "scr-" + "b" * 32
    evaluation_id = "gateeval-" + "d" * 32
    with Session(engine) as session:
        session.add(
            Run(
                id="quality-run",
                window_from=date(2026, 8, 17),
                window_to=date(2026, 8, 23),
                timezone="Asia/Seoul",
                generated_at=now,
                status="active",
                screening_basis="fixed",
                counts_json={},
            )
        )
        session.add(
            ScreeningPolicy(
                policy_version="quality-policy",
                schema_version="bidops.screening-policy.v1",
                prompt_version="quality-prompt",
                content_digest=digest,
                status="activation_candidate",
                perspective_prompts_json={},
                counterargument_prompt_json={},
                synthesis_prompt_json={},
                candidate_selection_json={},
                thresholds_json={},
                created_at=now,
                created_by="operator",
            )
        )
        session.add(
            CompanyProfileSnapshot(
                digest=digest,
                version=f"company-profile.sha256:{digest}",
                source_kind="working_tree",
                source_ref="docs/reference/company-profile.md",
                artifact_path=f"web/data/profile-snapshots/{digest}.md",
                created_at=now,
            )
        )
        session.flush()
        for execution_id in (pass_a, pass_b):
            session.add(
                ScreeningExecution(
                    execution_id=execution_id,
                    trigger="quality_gate",
                    source_run_id="quality-run",
                    scope="quality_sample",
                    status="성공",
                    requested_by="operator",
                    policy_version="quality-policy",
                    prompt_version="quality-prompt",
                    model_name="qwen3.8:27b",
                    model_digest=digest,
                    company_profile_version=f"company-profile.sha256:{digest}",
                    company_profile_digest=digest,
                    input_artifact_path=f"data/screening-executions/{execution_id}/screening-input.json",
                    input_artifact_digest=digest,
                    artifact_dir=f"data/screening-executions/{execution_id}",
                    queued_at=now,
                    started_at=now,
                    finished_at=now,
                    candidate_count=40,
                    completed_count=40,
                )
            )
        session.flush()
        session.add(
            QualityGate(
                gate_id=gate_id,
                purpose="operational_approval",
                execution_status="대기",
                result_status="미측정",
                baseline_run_id="quality-run",
                sample_artifact_path="data/runs/sample.json",
                sample_artifact_digest=digest,
                baseline_decisions_path="data/runs/baseline.json",
                baseline_decisions_digest=digest,
                policy_version="quality-policy",
                prompt_version="quality-prompt",
                model_name="qwen3.8:27b",
                model_digest=digest,
                company_profile_version=f"company-profile.sha256:{digest}",
                company_profile_digest=digest,
                pass_a_execution_id=pass_a,
                pass_b_execution_id=pass_b,
                created_at=now,
                metrics_json={},
                reasons_json=["execution_pending"],
                created_by="operator",
            )
        )
        session.add(
            QualityGateEvaluation(
                evaluation_id=evaluation_id,
                gate_id=gate_id,
                revision=1,
                result_status="미측정",
                metrics_json={},
                reasons_json=["execution_pending"],
                valid_review_count=0,
                distinct_notice_review_count=0,
                created_at=now,
            )
        )
        session.commit()

    import app.routers.quality_gates as quality_gates

    class RefreshingService:
        def __init__(self, **_kwargs):
            pass

        def refresh(self, current_gate_id: str):
            assert current_gate_id == gate_id
            with Session(engine) as refresh_session:
                gate = refresh_session.get(QualityGate, gate_id)
                gate.execution_status = "완료"
                gate.result_status = "미측정"
                gate.completed_at = now
                refresh_session.add(
                    QualityGateEvaluation(
                        evaluation_id="gateeval-" + "e" * 32,
                        gate_id=gate_id,
                        revision=2,
                        result_status="미측정",
                        metrics_json={},
                        reasons_json=["review_count_below_minimum"],
                        valid_review_count=0,
                        distinct_notice_review_count=0,
                        created_at=now,
                    )
                )
                refresh_session.commit()

    monkeypatch.setattr(quality_gates, "QualityGateService", RefreshingService)
    application = FastAPI()
    application.include_router(gate_router)

    def override_db():
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        response = client.get(
            "/api/quality-gates?execution_status=%EC%99%84%EB%A3%8C&result_status=%EB%AF%B8%EC%B8%A1%EC%A0%95"
        )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["execution_status"] == "완료"
    assert body["items"][0]["latest_evaluation_id"] == "gateeval-" + "e" * 32
