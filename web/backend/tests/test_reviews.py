from datetime import date, datetime, timezone
import time

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.main import app
from app.models import Judgment, Notice, Review, Run, VerificationAnswer


@pytest.fixture
def reviews_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    with Session(engine) as session:
        run = Run(
            id="review-run",
            window_from=date(2026, 8, 17),
            window_to=date(2026, 8, 23),
            generated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )
        notice = Notice(
            run=run,
            notice_key="bid:REVIEW:000",
            title="리뷰 테스트 공고",
            sample_role="analysis",
        )
        notice.judgment = Judgment(grade="우선 검토", readiness="부분 확인 필요")
        session.add(run)
        session.commit()

        def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as client:
                yield client, session
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_review_save_and_update_is_idempotent_and_replaces_answers(reviews_client):
    client, session = reviews_client
    first = client.put(
        "/api/notices/1/review",
        json={
            "run_id": "review-run",
            "disposition": "심층 검토 진행",
            "system_judgment_review": "동의",
            "reason": "첫 번째 기록",
            "reviewer": "테스트 담당자",
            "verification_answers": [
                {"item": "참가자격", "answer": "확인 중"},
                {"item": "과업 범위", "answer": ""},
            ],
        },
    )
    assert first.status_code == 200
    first_payload = first.json()
    first_id = first_payload["id"]
    first_updated_at = first_payload["updated_at"]
    assert first_payload["reviewer"] == "테스트 담당자"
    assert first_payload["answers"][1]["answer"] is None

    time.sleep(0.001)
    second = client.put(
        "/api/notices/1/review",
        json={
            "run_id": "review-run",
            "disposition": "관찰",
            "system_judgment_review": "근거 부족",
            "corrected_grade": "검토 권장",
            "reason": "수정 기록",
            "reviewer": "테스트 담당자",
            "verification_answers": [{"item": "과업 범위", "answer": "확인 완료"}],
        },
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["id"] == first_id
    assert second_payload["updated_at"] != first_updated_at
    assert second_payload["answers"] == [
        {"id": second_payload["answers"][0]["id"], "item": "과업 범위", "answer": "확인 완료"}
    ]
    assert session.scalar(select(func.count()).select_from(Review)) == 1
    assert session.scalar(select(func.count()).select_from(VerificationAnswer)) == 1

    listed = client.get("/api/reviews", params={"run_id": "review-run"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == first_id


def test_review_export_preserves_feedback_v2_shape(reviews_client):
    client, _session = reviews_client
    client.put(
        "/api/notices/1/review",
        json={
            "run_id": "review-run",
            "disposition": "관찰",
            "reason": "메모",
            "reviewer": "테스트 담당자",
            "verification_answers": [{"item": "참가자격", "answer": "확인 완료"}],
        },
    )

    response = client.get("/api/reviews/export", params={"run_id": "review-run"})
    assert response.status_code == 200
    assert "review-feedback.yaml" in response.headers["content-disposition"]
    document = yaml.safe_load(response.text)
    assert document["schema_version"] == "bidops.feedback.v2"
    assert document["reviews"] == [
        {
            "notice_id": "bid:REVIEW:000",
            "disposition": "관찰",
            "system_judgment_review": None,
            "corrected_grade": None,
            "corrected_readiness": None,
            "weakest_perspective": None,
            "reason": "메모",
            "verification_answers": [{"item": "참가자격", "answer": "확인 완료"}],
        }
    ]
