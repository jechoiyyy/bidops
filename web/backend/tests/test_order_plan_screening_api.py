from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import OrderPlanScreeningExecution, OrderPlanScreeningResult
from app.routers import order_plans as order_plans_router
from app.schemas.order_plans import ExecutionCreateRequest
from app.services.order_plan_screening import OrderPlanScreeningService
from tests.test_order_plan_screening_service import _fixture


def test_manual_execution_and_review_api_contract(tmp_path, monkeypatch) -> None:
    settings, session, policy_version, _, plans = _fixture(tmp_path)
    monkeypatch.setattr(order_plans_router, "service", OrderPlanScreeningService(settings))

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    request = ExecutionCreateRequest(
        schema_version="execution-create-request.v1",
        producer="human-review-client",
        consumer="screening-api",
        request_id=uuid4(),
        source_run_id="run-c2",
        policy_version=policy_version,
    )
    headers = {
        "X-BidOps-Actor-Name": "reviewer",
    }
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/order-plan-screening/executions",
                json=request.model_dump(mode="json"),
                headers=headers,
            )
            assert created.status_code == 202, created.text
            execution_id = created.json()["execution_id"]

            replay = client.post(
                "/api/order-plan-screening/executions",
                json=request.model_dump(mode="json"),
                headers=headers,
            )
            assert replay.status_code == 202 and replay.json() == created.json()

            listed = client.get("/api/order-plan-screening/executions?limit=10")
            assert listed.status_code == 200 and listed.json()["total"] == 1
            detail = client.get(f"/api/order-plan-screening/executions/{execution_id}")
            assert detail.status_code == 200
            assert detail.json()["heartbeat_at"] is None
            assert detail.json()["artifacts"][0]["kind"] == "screening_input"

            artifact = client.get(
                f"/api/order-plan-screening/executions/{execution_id}/artifacts/screening_input"
            )
            assert artifact.status_code == 200
            assert "path" not in artifact.json() and "body" not in artifact.json()

            plan_pk = plans[0].id
            execution = session.get(OrderPlanScreeningExecution, UUID(execution_id))
            assert execution is not None
            session.add(OrderPlanScreeningResult(
                id=uuid4(),
                execution_id=UUID(execution_id),
                source_run_id="run-c2",
                order_plan_id=plan_pk,
                schema_version="bidops.order-plan-screening-result-row.v1",
                producer="order-plan-screening-merge",
                consumer="postgres-loader-and-review-api",
                input_artifact_sha256="a" * 64,
                policy_version=policy_version,
                policy_sha256="b" * 64,
                binding_sha256="c" * 64,
                result_sha256="d" * 64,
                stage1_rank=1,
                stage1_score=1,
                nearest_capability="cap",
                stage1_status="selected",
                stage2_status="success",
                qwen_relevance="uncertain",
                qwen_score=.5,
                qwen_reason="사람 검토 필요",
                batch_id="batch-0001",
                attempt_no=1,
                failure_code=None,
                created_at=datetime.now(UTC),
            ))
            session.commit()
            feedback = {
                "schema_version": "feedback-create-request.v1",
                "producer": "human-review-client",
                "consumer": "review-api",
                "request_id": str(uuid4()),
                "execution_id": execution_id,
                "relevance": "uncertain",
                "priority": "medium",
                "memo": "사람 검토 필요",
                "expected_revision": 0,
            }
            saved = client.post(f"/api/order-plans/{plan_pk}/screening-feedback", json=feedback, headers=headers)
            assert saved.status_code == 201 and saved.json()["revision"] == 1, saved.text
            history = client.get(f"/api/order-plans/{plan_pk}/screening-feedback")
            assert history.status_code == 200 and len(history.json()["items"]) == 1
            plan_detail = client.get(f"/api/order-plans/{plan_pk}")
            assert plan_detail.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
