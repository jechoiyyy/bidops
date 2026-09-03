from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db, init_db
from app.main import app
from app.models import Attachment, Evidence, Judgment, Notice, Perspective, Run


@pytest.fixture
def api_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    with Session(engine) as session:
        run = Run(
            id="test-run",
            window_from=date(2026, 8, 17),
            window_to=date(2026, 8, 23),
            generated_at=datetime(2026, 8, 24, 0, tzinfo=timezone.utc),
            counts_json={"notices": 3, "judgments": 3},
        )
        selected = Notice(
            run=run,
            notice_key="bid:TEST:000",
            title="AI 플랫폼 구축",
            agency="테스트 기관",
            published_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
            deadline_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
            sample_role="analysis",
            sample_stratum="AI/데이터",
        )
        selected.attachments.append(Attachment(name="요청서.pdf", origin="g2b"))
        judgment = Judgment(
            notice=selected,
            schema_version="bidops.decisions.v2",
            grade="우선 검토",
            readiness="부분 확인 필요",
            primary_focus="AI/데이터",
            summary="검토 요약",
        )
        perspective = Perspective(
            judgment=judgment,
            position=1,
            name="기술 적합성",
            assessment="적합",
            reason="제목 신호",
        )
        perspective.evidence.append(
            Evidence(source="공고명", status="confirmed", fact="AI 플랫폼")
        )
        excluded = Notice(
            run=run,
            notice_key="bid:TEST:001",
            title="행사 운영",
            agency="테스트 기관",
            sample_role="analysis",
        )
        excluded_judgment = Judgment(
            notice=excluded,
            schema_version="bidops.decisions.v2",
            grade="제외",
            readiness="해당 없음",
        )
        audit = Notice(
            run=run,
            notice_key="bid:TEST:002",
            title="감사 공고",
            agency="다른 기관",
            sample_role="audit",
        )
        audit_judgment = Judgment(
            notice=audit,
            schema_version="bidops.decisions.v2",
            grade="우선 검토",
            readiness="부분 확인 필요",
        )
        # 판정은 공고 relationship 을 통해 저장되지 않으므로(명세 §4) 함께 넣는다.
        # 회차를 먼저 넣어 공고 식별자 순서를 이전과 같게 유지한다.
        session.add_all([run, judgment, excluded_judgment, audit_judgment])
        session.commit()

        def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def related_api_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    with Session(engine) as session:
        run = Run(
            id="related-run",
            window_from=date(2026, 8, 17),
            window_to=date(2026, 8, 23),
            generated_at=datetime(2026, 8, 24, 0, tzinfo=timezone.utc),
        )
        notices = [
            Notice(
                run=run,
                notice_key="bid:REL:000",
                bid_no="REL",
                bid_ord="000",
                title="관련 공고",
                published_at=datetime(2026, 8, 19, 1, tzinfo=timezone.utc),
                lifecycle_json={"unified_notice_no": "UNIFIED", "pre_spec_no": "PRE"},
                sample_role="analysis",
            ),
            Notice(
                run=run,
                notice_key="bid:REL:001",
                bid_no="REL",
                bid_ord="001",
                title="관련 공고 정정",
                published_at=datetime(2026, 8, 19, 2, tzinfo=timezone.utc),
                lifecycle_json={"unified_notice_no": "UNIFIED", "pre_spec_no": "PRE", "change_reason": "정정"},
                sample_role="analysis",
            ),
            Notice(
                run=run,
                notice_key="bid:OTHER:000",
                bid_no="OTHER",
                bid_ord="000",
                title="같은 사업 공고",
                published_at=datetime(2026, 8, 19, 3, tzinfo=timezone.utc),
                lifecycle_json={"unified_notice_no": "UNIFIED", "pre_spec_no": "OTHER-PRE"},
                sample_role="analysis",
            ),
            Notice(
                run=run,
                notice_key="bid:PRE:000",
                bid_no="PRE",
                bid_ord="000",
                title="사전규격 파생 공고",
                published_at=datetime(2026, 8, 19, 4, tzinfo=timezone.utc),
                lifecycle_json={"unified_notice_no": "OTHER-UNIFIED", "pre_spec_no": "PRE"},
                sample_role="analysis",
            ),
            Notice(
                run=run,
                notice_key="bid:BLANK:000",
                bid_no="BLANK",
                bid_ord="000",
                title="기준값 없는 공고",
                lifecycle_json={},
                sample_role="analysis",
            ),
        ]
        for notice in notices:
            session.add(Judgment(notice=notice, grade="관찰 대상", readiness="확인 완료"))
        session.add(run)
        session.commit()

        def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_notice_list_default_filters_and_paginates(api_client):
    response = api_client.get("/api/notices", params={"run_id": "test-run"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["filters"]["sample_role"] == "analysis"
    assert payload["items"][0]["grade"] == "우선 검토"


def test_notice_detail_includes_judgment_evidence_and_attachments(api_client):
    response = api_client.get("/api/notices/1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["judgment"]["perspectives"][0]["evidence"][0]["status"] == "confirmed"
    assert payload["attachments"][0]["origin"] == "g2b"
    assert payload["timezone"] == "Asia/Seoul"


def test_notice_history_and_missing_notice(api_client):
    assert api_client.get("/api/notices/1/history").json()["items"][0]["grade"] == "우선 검토"
    assert api_client.get("/api/notices/999").status_code == 404


def test_related_notices_uses_priority_and_same_run(related_api_client):
    listing = related_api_client.get("/api/notices", params={"run_id": "related-run", "grade": "all", "sample_role": "all"}).json()
    current_id = next(item["id"] for item in listing["items"] if item["notice_key"] == "bid:REL:000")

    response = related_api_client.get(f"/api/notices/{current_id}/related")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [(item["notice_key"], item["relation"]) for item in items] == [
        ("bid:REL:001", "ordinal"),
        ("bid:OTHER:000", "unified"),
        ("bid:PRE:000", "pre_spec"),
    ]
    assert items[0]["change_reason"] == "정정"


def test_related_notices_does_not_invent_empty_keys(related_api_client):
    listing = related_api_client.get("/api/notices", params={"run_id": "related-run", "grade": "all", "sample_role": "all"}).json()
    blank_id = next(item["id"] for item in listing["items"] if item["notice_key"] == "bid:BLANK:000")

    response = related_api_client.get(f"/api/notices/{blank_id}/related")

    assert response.status_code == 200
    assert response.json()["items"] == []
