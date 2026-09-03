from datetime import datetime, timezone
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.main import app
from app.models import AuditEvent, Notice, Opportunity, OpportunityLink, OrderPlan
from app.services.opportunity_integrity import merge_opportunities
from app.services.opportunity_tracking import raise_recheck_signal, set_tracking_status


@pytest.fixture
def opportunity_api():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    session = Session(engine)

    ended = Opportunity(
        first_registered_stage="bid_notice",
        tracking_status="종료",
        tracking_reason="현재 추적 종료",
        tracking_selected_by="기존 담당자",
        tracking_selected_at=datetime(2026, 8, 29, 1, tzinfo=timezone.utc),
    )
    order_plan_opportunity = Opportunity(first_registered_stage="order_plan")
    session.add_all([ended, order_plan_opportunity])
    session.flush()

    notice = Notice(
        notice_key="bid:API-TEST:000",
        source_type="bid_notice",
        title="사업기회 입찰공고",
        agency="테스트 기관",
    )
    plan = OrderPlan(
        order_plan_unty_no="R26API0000001",
        title="사업기회 발주계획",
        agency_name="계획 기관",
    )
    session.add_all([notice, plan])
    session.flush()

    ended_notice_link = OpportunityLink(
        opportunity=ended,
        notice=notice,
        stage="notice",
        link_type="official",
        status="확정",
        evidence_external_no="BID-API-TEST",
    )
    search_unconfirmed = OpportunityLink(
        opportunity=ended,
        stage="notice",
        link_type="candidate",
        status="검색 미확인",
        search_strategy="full",
        attempted_strategies_json=["full", "normalized"],
    )
    plan_link = OpportunityLink(
        opportunity=order_plan_opportunity,
        order_plan=plan,
        stage="order_plan",
        link_type="official",
        status="확정",
        evidence_external_no=plan.order_plan_unty_no,
    )
    session.add_all([ended_notice_link, search_unconfirmed, plan_link])
    session.flush()
    raise_recheck_signal(
        session,
        ended,
        ended_notice_link,
        signaled_at=datetime(2026, 8, 29, 2, tzinfo=timezone.utc),
    )
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, session, ended, order_plan_opportunity
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


def test_opportunity_list_includes_ended_by_default_and_uses_pagination_shape(opportunity_api):
    client, _session, _ended, _plan_opportunity = opportunity_api

    response = client.get("/api/opportunities", params={"limit": 1, "offset": 0})

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"items", "total", "limit", "offset"}
    assert payload["total"] == 2
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert any(item["tracking_status"] == "종료" for item in client.get("/api/opportunities").json()["items"])


def test_opportunity_list_filters_tracking_status_and_first_stage(opportunity_api):
    client, _session, _ended, _plan_opportunity = opportunity_api

    closed = client.get("/api/opportunities", params={"tracking_status": "종료"}).json()
    plans = client.get(
        "/api/opportunities",
        params={"first_registered_stage": "order_plan"},
    ).json()

    assert closed["total"] == 1
    assert [item["tracking_status"] for item in closed["items"]] == ["종료"]
    assert plans["total"] == 1
    assert [item["first_registered_stage"] for item in plans["items"]] == ["order_plan"]


def test_opportunity_detail_keeps_search_unconfirmed_link_and_recheck_evidence(opportunity_api):
    client, _session, ended, _plan_opportunity = opportunity_api

    response = client.get(f"/api/opportunities/{ended.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["recheck_signal"] is True
    signal_link_id = payload["recheck_signal_link_id"]
    assert payload["recheck_signal_at"] is not None
    links_by_id = {link["id"]: link for link in payload["links"]}
    assert signal_link_id in links_by_id
    assert links_by_id[signal_link_id]["status"] == "확정"
    assert any(link["status"] == "검색 미확인" for link in payload["links"])
    assert any(link["title"] == "사업기회 입찰공고" for link in payload["links"])


def test_tracking_status_change_uses_service_audit_and_header_actor(opportunity_api):
    client, session, _ended, plan_opportunity = opportunity_api

    response = client.patch(
        f"/api/opportunities/{plan_opportunity.id}/tracking-status",
        json={"tracking_status": "계속 추적", "reason": "공고 변화를 확인"},
        headers={"X-BidOps-Actor-Name": "reviewer-api"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tracking_status"] == "계속 추적"
    assert payload["tracking_selected_by"] == "reviewer-api"
    audit = session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "opportunity.tracking_status.changed",
            AuditEvent.aggregate_id == str(plan_opportunity.id),
        )
    )
    assert audit is not None
    assert audit.actor_kind == "human"
    assert audit.claimed_name == "reviewer-api"


def test_tracking_status_change_requires_actor_and_decodes_non_ascii_actor(opportunity_api):
    client, _session, _ended, plan_opportunity = opportunity_api

    missing = client.patch(
        f"/api/opportunities/{plan_opportunity.id}/tracking-status",
        json={"status": "보류", "reason": "정보 대기"},
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "actor_name_required"

    actor = "김도윤"
    encoded = f"UTF-8''{quote(actor, safe='')}"
    decoded = client.patch(
        f"/api/opportunities/{plan_opportunity.id}/tracking-status",
        json={"status": "보류", "reason": "정보 대기"},
        headers={
            "X-BidOps-Actor-Name": encoded,
            "X-BidOps-Actor-Name-Format": "utf-8-percent-v1",
        },
    )
    assert decoded.status_code == 200
    assert decoded.json()["tracking_selected_by"] == actor


def test_tracking_status_change_rejects_invalid_status_and_missing_opportunity(opportunity_api):
    client, _session, _ended, plan_opportunity = opportunity_api

    invalid = client.patch(
        f"/api/opportunities/{plan_opportunity.id}/tracking-status",
        json={"status": "관심 없음", "reason": "잘못된 값"},
        headers={"X-BidOps-Actor-Name": "reviewer"},
    )
    missing = client.get("/api/opportunities/999999")

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "tracking_status_invalid"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "opportunity_not_found"


def test_opportunity_api_does_not_expose_paths_or_credentials(opportunity_api):
    client, _session, _ended, _plan_opportunity = opportunity_api

    body = client.get("/api/opportunities").text

    for forbidden in ("/home/", "password", "secret", "API_KEY", "prompt", "raw_source"):
        assert forbidden not in body


@pytest.mark.parametrize("decision", ["accepted", "rejected"])
def test_candidate_decision_is_audited_and_exact_replay_is_idempotent(
    opportunity_api,
    decision,
):
    client, session, _ended, plan_opportunity = opportunity_api
    notice = Notice(
        notice_key=f"pre:DECISION-{decision}",
        source_type="pre_spec",
        title="사람 확인 후보",
    )
    session.add(notice)
    session.flush()
    candidate = OpportunityLink(
        opportunity=plan_opportunity,
        notice=notice,
        stage="notice",
        link_type="candidate",
        status="후보 확인 대기",
        search_strategy="full",
    )
    session.add(candidate)
    session.commit()

    request = {
        "decision": decision,
        "reason": "공식 정보와 기관·사업 범위를 대조함",
    }
    headers = {"X-BidOps-Actor-Name": "candidate-reviewer"}
    first = client.patch(
        f"/api/opportunities/links/{candidate.id}/decision",
        json=request,
        headers=headers,
    )
    replay = client.patch(
        f"/api/opportunities/links/{candidate.id}/decision",
        json=request,
        headers=headers,
    )

    assert first.status_code == replay.status_code == 200
    assert first.json()["status"] == "사람 확인 완료"
    assert first.json()["human_decision"] == decision
    assert replay.json()["reviewed_at"] == first.json()["reviewed_at"]
    audits = session.scalars(
        select(AuditEvent).where(
            AuditEvent.action == "opportunity_link.candidate_decision.recorded",
            AuditEvent.aggregate_id == str(candidate.id),
        )
    ).all()
    assert len(audits) == 1
    assert audits[0].claimed_name == "candidate-reviewer"
    assert audits[0].safe_metadata["decision"] == decision

    conflict = client.patch(
        f"/api/opportunities/links/{candidate.id}/decision",
        json={**request, "reason": "다른 판정 근거"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "candidate_decision_conflict"


def test_candidate_decision_requires_claimed_reviewer_name(opportunity_api):
    client, session, _ended, plan_opportunity = opportunity_api
    notice = Notice(notice_key="pre:ACTOR-REQUIRED", source_type="pre_spec")
    session.add(notice)
    session.flush()
    candidate = OpportunityLink(
        opportunity=plan_opportunity,
        notice=notice,
        stage="notice",
        link_type="candidate",
        status="후보 확인 대기",
    )
    session.add(candidate)
    session.commit()

    response = client.patch(
        f"/api/opportunities/links/{candidate.id}/decision",
        json={"decision": "accepted", "reason": "사람 확인"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "actor_name_required"


def test_active_list_excludes_merged_row_but_direct_detail_keeps_trace(opportunity_api):
    client, session, _ended, plan_opportunity = opportunity_api
    secondary_notice = Notice(
        notice_key="bid:MERGED-TRACE",
        source_type="bid_notice",
    )
    secondary = Opportunity(
        first_registered_stage="bid_notice",
        created_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    session.add_all([secondary_notice, secondary])
    session.flush()
    session.add(
        OpportunityLink(
            opportunity=secondary,
            notice=secondary_notice,
            stage="notice",
            link_type="official",
            status="확정",
            evidence_external_no="MERGED-TRACE",
        )
    )
    session.flush()
    retained = merge_opportunities(
        session,
        [plan_opportunity, secondary],
        merged_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    session.commit()
    assert retained is not None

    listed = client.get("/api/opportunities").json()
    traced = client.get(f"/api/opportunities/{secondary.id}")

    assert secondary.id not in {item["id"] for item in listed["items"]}
    assert traced.status_code == 200
    assert traced.json()["merged_into_opportunity_id"] == retained.id
    assert traced.json()["merge_reason"] == "authoritative_lifecycle_link"
