"""추적 선택 저장과 발주계획 선별 피드백 저장은 서로 다른 결정이다."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from uuid import uuid4

from app.core.db import get_db
from app.lifecycle import opportunities_router
from app.screening.models import OrderPlanScreeningFeedback, OrderPlanScreeningResult
from app.screening.routers import order_plans as routes
from app.screening.services.order_plan_screening import OrderPlanScreeningService
from tests.screening.test_order_plan_list_v2 import execution, feedback, owner, result
from tests.screening.test_order_plan_screening_service import _fixture


def test_tracking_patch_and_feedback_post_preserve_each_others_state(tmp_path, monkeypatch, empty_extensions):
    settings, session, policy, _, plans = _fixture(tmp_path, count=1)
    service = OrderPlanScreeningService(settings)
    monkeypatch.setattr(routes, "service", service)
    chosen = execution(session, service, policy)
    result_row = result(session, chosen, plans[0])
    feedback(session, chosen, plans[0], relevance="uncertain")
    opportunity = owner(session, plans[0])
    session.commit()
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(opportunities_router)
    app.dependency_overrides[get_db] = lambda: session
    headers = {"X-BidOps-Actor-Name": "reviewer"}
    path = f"/api/order-plans/{plans[0].id}"
    result_before = {column.name: getattr(result_row, column.name) for column in OrderPlanScreeningResult.__table__.columns}
    try:
        with TestClient(app) as client:
            before = client.get("/api/order-plans").json()["items"][0]
            changed = client.patch(
                f"/api/opportunities/{opportunity.id}/tracking-status",
                json={"tracking_status": "계속 추적", "reason": "사전규격 확인 예정"}, headers=headers,
            )
            assert changed.status_code == 200, changed.text
            after_tracking = client.get("/api/order-plans").json()["items"][0]
            assert after_tracking["tracking"]["tracking_status"] == "계속 추적"
            for field in ("stage1_status", "stage1_rank", "stage1_score", "nearest_capability", "stage2_status", "qwen_relevance", "qwen_score", "qwen_reason", "human_feedback"):
                assert after_tracking[field] == before[field]
            changed_feedback = client.post(
                f"{path}/screening-feedback",
                json={"schema_version": "feedback-create-request.v1", "producer": "human-review-client", "consumer": "review-api", "request_id": str(uuid4()), "execution_id": str(chosen.execution_id), "relevance": "not_relevant", "expected_revision": 1},
                headers=headers,
            )
            assert changed_feedback.status_code == 201, changed_feedback.text
            after_feedback = client.get("/api/order-plans").json()["items"][0]
            assert after_feedback["human_feedback"]["revision"] == 2
            assert after_feedback["human_feedback"]["relevance"] == "not_relevant"
            assert after_feedback["tracking"] == after_tracking["tracking"]
            assert client.get(path).json()["tracking"] == after_tracking["tracking"]
            session.refresh(result_row)
            assert {column.name: getattr(result_row, column.name) for column in OrderPlanScreeningResult.__table__.columns} == result_before
            revisions = session.scalars(select(OrderPlanScreeningFeedback).order_by(OrderPlanScreeningFeedback.revision)).all()
            assert [(row.revision, row.relevance) for row in revisions] == [(1, "uncertain"), (2, "not_relevant")]
    finally:
        session.close()
        session.bind.dispose()
