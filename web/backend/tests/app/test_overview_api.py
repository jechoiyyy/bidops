"""사전규격 개요 검토 REST 세 endpoint (`bidops.prespec-overview.v1`).

seed 도우미는 `tests/deep_review/test_overview_runs.py`의 것을 그대로 쓴다 —
같은 스냅샷·묶음 모양을 두 벌 만들지 않는다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import Base, get_db
from app.deep_review.models import ContentScan, PrespecOverviewRun, WorkJob
from app.deep_review.routers import overviews
from app.deep_review.services import overview_runs
from app.deep_review.services.effective_grade import EffectiveGrade
from tests.deep_review.test_overview_runs import _FakeStore, seed


ACTOR = {"X-BidOps-Actor-Name": "checker"}


def _clean_scan(session, content_object_id) -> None:
    session.add(
        ContentScan(
            content_object_id=content_object_id, scanner="clamav", scanner_version="test",
            status="clean", safe_result={"verdict": "clean"},
        )
    )
    session.flush()


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        overview_runs, "effective_grades",
        lambda session, ids: {
            int(value): EffectiveGrade(int(value), "우선 검토", "screening_judgment")
            for value in ids
        },
    )
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    store = _FakeStore()
    # PDF 읽기는 서비스가 한다. 라우터는 ORM도 저장소도 직접 만지지 않는다.
    monkeypatch.setattr(overview_runs, "object_store", lambda **_kwargs: store)
    session = Session(engine)
    notice, document, snapshot = seed(session, store)
    _clean_scan(session, snapshot.source_content_object_id)
    session.commit()
    app = FastAPI()
    app.include_router(overviews.router)
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as client:
        yield client, session, notice, snapshot
    session.close()
    get_settings.cache_clear()
    engine.dispose()


def _completed_run(session, notice, snapshot) -> PrespecOverviewRun:
    job = WorkJob(
        id=uuid4(), job_type="prespec_overview", aggregate_type="prespec_overview_run",
        aggregate_id=uuid4(), status="completed",
    )
    session.add(job)
    session.flush()
    run = PrespecOverviewRun(
        id=job.aggregate_id, notice_id=notice.id, document_version_id=snapshot.document_version_id,
        snapshot_id=snapshot.id, work_job_id=job.id, status="completed", range_source="auto",
        page_start=1, page_end=1, range_reason_codes=[], policy_digest="0" * 64,
        model_name="test-overview", warnings_json=["quantity_unit_missing"], reason_codes=[],
        call_count=2, raw_response_refs=[{"stage": "draft", "sha256": "e" * 64}],
        result_json={
            "schema_version": "bidops.prespec-overview-page-review.v4",
            "business_overview": [{"claim_id": "c1", "text": "합성 사업개요 문장이다.",
                                   "evidence": [{"page": 1, "quote": "합성 사업개요 문장이다.",
                                                 "start_char": 0, "end_char": 12,
                                                 "page_text_sha256": "f" * 64}]}],
            "main_tasks": [], "budget_and_period": [], "important_conditions": [],
            "reviewer_analysis": [{"id": "a1", "text": "모의 분석", "supporting_claim_ids": ["c1"]}],
            "unknowns": ["회사 역량 대조는 수행하지 않았습니다."],
            "input_limitations": ["PDF 총 1페이지 중 선택된 1페이지만 검토했습니다."],
        },
        completed_at=datetime.now(UTC),
    )
    session.add(run)
    session.commit()
    return run


def test_overview_envelope_hides_raw_response_references(api):
    client, session, notice, snapshot = api
    run = _completed_run(session, notice, snapshot)

    response = client.get(f"/api/pre-specs/{notice.id}/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "bidops.prespec-overview.v1"
    assert body["current"]["id"] == str(run.id) and len(body["history"]) == 1
    assert body["current"]["warnings"] == ["quantity_unit_missing"]
    assert body["current"]["result"]["reviewer_analysis"] == [
        {"id": "a1", "text": "모의 분석", "supporting_claim_ids": ["c1"]}
    ]
    # 근거는 `{page, quote}`뿐이고 원응답 참조·내부 offset은 나가지 않는다.
    assert body["current"]["result"]["business_overview"][0]["evidence"] == [
        {"page": 1, "quote": "합성 사업개요 문장이다."}
    ]
    assert "raw_response_refs" not in response.text and "page_text_sha256" not in response.text


def test_range_confirmation_enqueues_one_run_even_with_the_flag_off(api):
    client, session, notice, _snapshot = api

    response = client.post(
        f"/api/pre-specs/{notice.id}/overview/range-confirmations",
        json={"page_start": 1, "page_end": 1, "note": "1쪽만 본다"},
        headers=ACTOR,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["attempt_enqueued"] is True
    run = session.get(PrespecOverviewRun, UUID(body["run_id"]))
    assert run.status == "queued" and run.range_source == "human" and run.actor_name == "checker"


def test_range_confirmation_conflicts_with_an_active_run(api):
    client, session, notice, _snapshot = api
    first = client.post(
        f"/api/pre-specs/{notice.id}/overview/range-confirmations",
        json={"page_start": 1, "page_end": 1}, headers=ACTOR,
    )
    assert first.status_code == 201

    response = client.post(
        f"/api/pre-specs/{notice.id}/overview/range-confirmations",
        json={"page_start": 1, "page_end": 1}, headers=ACTOR,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "run_active"


def test_range_confirmation_rejects_a_reversed_span(api):
    client, _session, notice, _snapshot = api

    response = client.post(
        f"/api/pre-specs/{notice.id}/overview/range-confirmations",
        json={"page_start": 3, "page_end": 1}, headers=ACTOR,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "range_invalid"


def test_run_pdf_streams_the_frozen_snapshot(api):
    client, session, notice, snapshot = api
    run = _completed_run(session, notice, snapshot)

    response = client.get(f"/api/pre-specs/{notice.id}/overview/runs/{run.id}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    missing = client.get(f"/api/pre-specs/{notice.id}/overview/runs/{uuid4()}/pdf")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
