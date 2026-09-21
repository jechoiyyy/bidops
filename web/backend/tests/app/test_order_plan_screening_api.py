from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.screening.models import (
    OrderPlanScreeningBatchAttempt,
    OrderPlanScreeningExecution,
    OrderPlanScreeningResult,
)
from app.screening.routers import order_plans as order_plans_router
from app.screening.schemas.order_plans import ExecutionCreateRequest
from app.screening.services.order_plan_screening import OrderPlanScreeningService
from tests.screening.test_order_plan_screening_service import _fixture


def test_manual_execution_and_review_api_contract(tmp_path, monkeypatch) -> None:
    settings, session, policy_version, _, plans = _fixture(tmp_path)
    plans[0].budget_amount = Decimal("123456789.00")
    plans[0].agency_name = "고유 기관"
    plans[0].planned_order_year = "2027"
    plans[0].planned_order_month = "09"
    session.commit()
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
            # The trigger header is not part of the request hash.
            replay_with_header = client.post(
                "/api/order-plan-screening/executions",
                json=request.model_dump(mode="json"),
                headers={**headers, "X-BidOps-Trigger": "gate_measurement"},
            )
            assert replay_with_header.status_code == 202 and replay_with_header.json() == created.json()

            listed = client.get("/api/order-plan-screening/executions?limit=10")
            assert listed.status_code == 200 and listed.json()["total"] == 1
            assert listed.json()["schema_version"] == "execution-list-response.v2"
            assert listed.json()["items"][0]["purpose"] == "operational"
            session.add(OrderPlanScreeningBatchAttempt(
                attempt_id=uuid4(),
                execution_id=UUID(execution_id),
                batch_id="batch-0001",
                sequence=1,
                attempt_no=1,
                schema_version="bidops.order-plan-screening-batch-attempt-row.v1",
                producer="screening-worker",
                consumer="screening-merge-and-observability",
                plan_count=1,
                plan_ids_jsonb=[plans[0].id],
                plan_ids_sha256="a" * 64,
                model_name="qwen3.8-27B",
                model_digest="b" * 64,
                prompt_version="prompt-v3",
                prompt_sha256="c" * 64,
                company_profile_version="profile-v1",
                company_profile_sha256="d" * 64,
                generation_config_sha256="e" * 64,
                attempt_status="failed",
                failure_type="timeout",
                failure_code="qwen_timeout",
                response_object_ref="opaque-encrypted-reference",
                input_tokens=10,
                cached_input_tokens=2,
                output_tokens=3,
                total_tokens=13,
                duration_ms=100,
                started_at=datetime(2026, 9, 2, 0, 0, tzinfo=UTC),
                finished_at=datetime(2026, 9, 2, 0, 1, tzinfo=UTC),
                created_at=datetime(2026, 9, 2, 0, 1, tzinfo=UTC),
            ))
            session.commit()
            detail = client.get(f"/api/order-plan-screening/executions/{execution_id}")
            assert detail.status_code == 200
            assert detail.json()["schema_version"] == "execution-detail-response.v2"
            assert detail.json()["purpose"] == "operational"
            assert detail.json()["heartbeat_at"] is None
            assert detail.json()["artifacts"][0]["kind"] == "screening_input"
            assert detail.json()["attempts"][0]["batch_id"] == "batch-0001"
            assert detail.json()["attempts"][0]["model_name"] == "qwen3.8-27B"
            assert detail.json()["attempts"][0]["failure_code"] == "qwen_timeout"
            assert detail.json()["attempts"][0]["total_tokens"] == 13
            assert detail.json()["attempts"][0]["duration_ms"] == 100
            assert "response_object_ref" not in detail.json()["attempts"][0]
            assert "plan_ids_jsonb" not in detail.json()["attempts"][0]

            artifact = client.get(
                f"/api/order-plan-screening/executions/{execution_id}/artifacts/screening_input"
            )
            assert artifact.status_code == 200
            assert "path" not in artifact.json() and "body" not in artifact.json()

            plan_pk = plans[0].id
            execution = session.get(OrderPlanScreeningExecution, UUID(execution_id))
            assert execution is not None
            execution.status = "성공"
            execution.started_at = execution.queued_at
            execution.finished_at = datetime.now(UTC)
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
            plan_list = client.get("/api/order-plans?source_run_id=run-c2&limit=10")
            assert plan_list.status_code == 200
            assert plan_list.json()["schema_version"] == "order-plan-list-response.v4"
            assert plan_list.json()["scope"]["execution_id"] == execution_id
            assert plan_list.json()["scope"]["status"] == "성공"
            assert plan_list.json()["items"][0]["budget_amount"] == 123456789.0
            assert plan_list.json()["items"][0]["planned_order_year"] == "2027"
            assert plan_list.json()["items"][0]["planned_order_month"] == "09"
            assert plan_list.json()["items"][0]["nearest_capability"] == "cap"
            agency = plans[0].agency_name
            assert agency
            searched = client.get("/api/order-plans", params={
                "source_run_id": "run-c2", "q": agency[:1] + "\u00a0" + agency[1:],
            })
            assert searched.status_code == 200
            assert searched.json()["total"] == 1
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
            screening_history = client.get(f"/api/order-plans/{plan_pk}/screening-history")
            assert screening_history.status_code == 200
            assert screening_history.json()["items"][0]["nearest_capability"] == "cap"
            assert screening_history.json()["items"][0]["batch_id"] == "batch-0001"
            assert screening_history.json()["items"][0]["attempt_no"] == 1
            plan_detail = client.get(f"/api/order-plans/{plan_pk}")
            assert plan_detail.status_code == 200
            assert plan_detail.json()["budget_amount"] == 123456789.0
            assert plan_detail.json()["planned_order_year"] == "2027"
            assert plan_detail.json()["planned_order_month"] == "09"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_execution_trigger_header_errors(tmp_path, monkeypatch) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    monkeypatch.setattr(order_plans_router, "service", OrderPlanScreeningService(settings))

    def override_get_db():
        yield session

    def body() -> dict[str, object]:
        return ExecutionCreateRequest(
            schema_version="execution-create-request.v1",
            producer="human-review-client",
            consumer="screening-api",
            request_id=uuid4(),
            source_run_id="run-c2",
            policy_version=policy_version,
        ).model_dump(mode="json")

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            for value in ("", "cron"):
                rejected = client.post(
                    "/api/order-plan-screening/executions",
                    json=body(),
                    headers={"X-BidOps-Actor-Name": "reviewer", "X-BidOps-Trigger": value},
                )
                assert rejected.status_code == 422, (value, rejected.text)
                assert rejected.json()["error"]["code"] == "invalid_request"

            off = client.post(
                "/api/order-plan-screening/executions",
                json=body(),
                headers={"X-BidOps-Actor-Name": "reviewer", "X-BidOps-Trigger": "daily_script"},
            )
            assert off.status_code == 409, off.text
            assert off.json()["error"]["code"] == "daily_trigger_off"
            assert off.json()["error"]["details"] == {"reasons": ["env_cap_off", "switch_off"]}
            assert client.get("/api/order-plan-screening/executions").json()["total"] == 0
    finally:
        app.dependency_overrides.pop(get_db, None)
