"""판정 projection 제공자가 없을 때의 lifecycle API (명세 §6.1 "제공자 부재 시").

lifecycle router만으로 앱을 조립하고 registry를 비운다. 필드는 null, 분포는 빈
목록이며, 등급·준비·focus query 필터와 `sort=grade`는 422다. 필터가 없으면 기본
조건(`Judgment.grade != "제외"`)도 projection의 일부라 적용되지 않아 **전체 공고**가
보인다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.lifecycle.models import Attachment, Notice, NoticeObservation, Run
from app.routers.metrics import router as metrics_router
from app.routers.notices import router as notices_router
from app.routers.runs import router as runs_router

GENERATED_AT = datetime(2026, 8, 24, tzinfo=timezone.utc)


@pytest.fixture
def lifecycle_client(empty_extensions):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    with Session(engine) as session:
        previous = Run(id="lc-prev", window_from=date(2026, 8, 10), window_to=date(2026, 8, 16), generated_at=GENERATED_AT - timedelta(days=7))
        run = Run(
            id="lc-run",
            window_from=date(2026, 8, 17),
            window_to=date(2026, 8, 23),
            generated_at=GENERATED_AT,
            counts_json={"notices": 3, "judgments": 0, "collection": {"total": 10, "candidate_pool": 4}},
        )
        first = Notice(run=run, notice_key="bid:LC:000", bid_no="LC", bid_ord="000", title="AI 플랫폼", agency="기관", sample_role="analysis", deadline_at=GENERATED_AT + timedelta(days=2))
        first.attachments.append(Attachment(name="a.pdf", origin="g2b"))
        second = Notice(run=run, notice_key="bid:LC:001", bid_no="LC", bid_ord="001", title="AI 플랫폼 정정", agency="기관", sample_role="analysis", deadline_at=GENERATED_AT + timedelta(days=1))
        audit = Notice(run=run, notice_key="bid:LC:002", title="감사 공고", agency="기관", sample_role="audit")
        previous.notice_observations.append(NoticeObservation(notice=first, changed_fields_json=[]))
        session.add_all([previous, run, first, second, audit])
        session.commit()

        application = FastAPI()
        application.include_router(runs_router)
        application.include_router(notices_router)
        application.include_router(metrics_router)

        def override_db():
            yield session

        application.dependency_overrides[get_db] = override_db
        with TestClient(application) as client:
            yield client


def test_list_without_filters_shows_every_notice_with_null_judgment_fields(lifecycle_client):
    response = lifecycle_client.get("/api/notices", params={"run_id": "lc-run"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2  # sample_role=analysis 기본 필터만 남는다.
    assert [item["notice_key"] for item in payload["items"]] == ["bid:LC:001", "bid:LC:000"]
    assert all(item["grade"] is None and item["readiness"] is None and item["focus"] is None for item in payload["items"])

    everything = lifecycle_client.get("/api/notices", params={"run_id": "lc-run", "sample_role": "all"}).json()
    assert everything["total"] == 3


@pytest.mark.parametrize(
    "params",
    [
        {"grade": "우선 검토"},
        {"grade": "all"},
        {"readiness": "확인 완료"},
        {"focus": "AI/데이터"},
        {"sort": "grade"},
    ],
)
def test_judgment_filters_and_grade_sort_are_422_without_a_provider(lifecycle_client, params):
    response = lifecycle_client.get("/api/notices", params={"run_id": "lc-run", **params})

    assert response.status_code == 422, response.text


def test_detail_related_and_history_carry_null_judgment_and_empty_reviews(lifecycle_client):
    detail = lifecycle_client.get("/api/notices/1")
    assert detail.status_code == 200
    body = detail.json()
    assert body["judgment"] is None
    assert body["reviews"] == []
    assert body["grade"] is None and body["readiness"] is None and body["focus"] is None
    assert body["attachments"][0]["origin"] == "g2b"

    related = lifecycle_client.get("/api/notices/1/related").json()
    assert [(item["notice_key"], item["relation"], item["grade"]) for item in related["items"]] == [("bid:LC:001", "ordinal", None)]

    history = lifecycle_client.get("/api/notices/1/history").json()
    assert sorted(item["run_id"] for item in history["items"]) == ["lc-prev", "lc-run"]
    assert all(
        item["grade"] is None and item["summary"] is None and item["corrected_grade"] is None and item["review_reason"] is None
        for item in history["items"]
    )


def test_run_stats_have_empty_distributions_and_no_judgment_funnel_stage(lifecycle_client):
    response = lifecycle_client.get("/api/runs/lc-run/stats")

    assert response.status_code == 200
    stats = response.json()
    assert stats["sample_count"] == 3
    assert stats["collected_count"] == 10 and stats["candidate_count"] == 4
    assert stats["priority_review_count"] == 0 and stats["audit_missed_count"] == 0
    assert stats["grade_distribution"] == [] and stats["readiness_distribution"] == [] and stats["focus_distribution"] == []
    assert stats["verification_requests"] == []
    assert [item["key"] for item in stats["funnel"]] == ["collected", "candidate_pool", "sample"]
    assert [item["notice_key"] for item in stats["imminent_deadlines"]] == ["bid:LC:001", "bid:LC:000"]
    assert all(item["blocking_verification_items"] == [] and item["grade"] is None for item in stats["imminent_deadlines"])


def test_validation_metrics_are_not_measurable_without_a_provider(lifecycle_client):
    response = lifecycle_client.get("/api/metrics/validation", params={"run_id": "lc-run"})

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert [item["key"] for item in metrics] == [
        "reproducibility",
        "discriminative_power",
        "evidence_validity",
        "information_sufficiency",
        "perspective_split",
    ]
    assert all(item["status"] == "not_measurable" and item["value"] is None and item["reason"] for item in metrics)
