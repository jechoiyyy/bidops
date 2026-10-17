from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.main import app
from app.core.models import AuditEvent
from app.lifecycle import ingest_run
from app.lifecycle.models import CollectedRecordIndex, Notice, Opportunity, OpportunityLink, OrderPlan
from app.lifecycle.routers import opportunities as opportunities_router
from app.lifecycle.services.opportunity_integrity import merge_opportunities
from app.lifecycle.services.opportunity_tracking import raise_recheck_signal, set_tracking_status


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
        budget="222000000.00",
        deadline_at=datetime(2026, 9, 25, 1, tzinfo=timezone.utc),
    )
    plan = OrderPlan(
        order_plan_unty_no="R26API0000001",
        title="사업기회 발주계획",
        agency_name="계획 기관",
        budget_amount="333000000.00",
        planned_order_year="2026",
        planned_order_month="2026-11",
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
    assert set(payload) == {"items", "total", "limit", "offset", "section_counts", "action_reason_counts"}
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


def test_opportunity_list_query_params_and_reason_fields(opportunity_api, monkeypatch):
    client, session, ended, plan_opportunity = opportunity_api
    now = datetime(2026, 9, 17, 3, 0, 0, 500000, tzinfo=timezone.utc)
    monkeypatch.setattr(opportunities_router, "_request_now", lambda: now)
    held = Opportunity(first_registered_stage="bid_notice", tracking_status="보류", tracking_reason="대기",
                       tracking_selected_by="담당자", tracking_selected_at=datetime(2026, 9, 3, 12, 0, 0, 500000,
                       tzinfo=timezone(timedelta(hours=9))))
    newcomer = Opportunity(first_registered_stage="bid_notice")
    session.add_all([held, newcomer])
    session.commit()

    listing = client.get("/api/opportunities").json()
    rows = {row["id"]: row for row in listing["items"]}
    assert set(rows[ended.id]) >= {"action_reasons", "hold_review_due_at"}
    assert rows[ended.id]["action_reasons"] == ["new_link"] and rows[ended.id]["section"] == "조치 필요"
    # +09:00 선택 시각 + 14일 = 요청 시각과 같은 순간이므로 기한 지남이다.
    assert datetime.fromisoformat(rows[held.id]["hold_review_due_at"]) == now
    assert rows[held.id]["action_reasons"] == ["hold_overdue"]
    assert rows[newcomer.id]["section"] == "신규 입찰공고" and rows[newcomer.id]["action_reasons"] == []
    assert listing["section_counts"] == {"조치 필요": 2, "추적 중": 0, "보류": 0, "추적 종료": 0,
                                         "신규 입찰공고": 1, "미결정": 1}
    assert listing["action_reason_counts"] == {"new_link": 1, "candidate_pending": 0,
                                               "merge_confirmation": 0, "blocking_item": 0, "hold_overdue": 1}
    detail = client.get(f"/api/opportunities/{held.id}").json()
    assert detail["action_reasons"] == ["hold_overdue"] and detail["hold_review_due_at"] == rows[held.id]["hold_review_due_at"]

    def ids(**params):
        response = client.get("/api/opportunities", params=params)
        assert response.status_code == 200, response.text
        return [row["id"] for row in response.json()["items"]]

    assert ids(reason="new_link") == [ended.id]
    assert ids(section="조치 필요", reason="hold_overdue") == [held.id]
    assert ids(hold_review="overdue") == [held.id]
    assert ids(hold_review="due_soon") == []
    assert ids(hold_review="attention", sort="hold_review_due_at", limit=5) == [held.id]
    assert ids(sort="hold_review_due_at")[0] == held.id
    assert ids(section="신규 입찰공고") == [newcomer.id]
    assert ids(q="사업기회 발주계획") == [plan_opportunity.id]
    assert ids(q="사업 기회발주 계획") == [plan_opportunity.id]
    assert ids(q="테스트  기관") == [ended.id]
    for params, code in (
        ({"section": "미결정"}, None), ({"reason": "unknown"}, None), ({"hold_review": "later"}, None),
        ({"sort": "due"}, None), ({"q": "a"}, "invalid_request"), ({"q": "x" * 101}, "invalid_request"),
    ):
        response = client.get("/api/opportunities", params=params)
        assert response.status_code == 422, params
        if code is not None:
            assert response.json()["error"]["code"] == code
    assert len(ids(q=" \u00a0\ufeff ")) == len(ids())


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


def test_opportunity_links_project_budget_and_deadline_per_target(opportunity_api):
    client, _session, ended, plan_opportunity = opportunity_api

    ended_detail = client.get(f"/api/opportunities/{ended.id}").json()
    links_by_id = {link["id"]: link for link in ended_detail["links"]}
    notice_link = next(link for link in links_by_id.values() if link["notice_id"] is not None)
    assert notice_link["budget"] == 222000000.0
    assert notice_link["deadline_at"] is not None
    # Notice-linked rows never project order-plan-only fields.
    assert notice_link["planned_order_year"] is None
    assert notice_link["planned_order_month"] is None
    # The candidate link has no resolved target; every new field stays null,
    # never inferred from the opportunity's other links.
    search_unconfirmed_link = next(link for link in links_by_id.values() if link["status"] == "검색 미확인")
    assert search_unconfirmed_link["budget"] is None
    assert search_unconfirmed_link["deadline_at"] is None

    plan_detail = client.get(f"/api/opportunities/{plan_opportunity.id}").json()
    plan_link = plan_detail["links"][0]
    assert plan_link["budget"] == 333000000.0
    assert plan_link["planned_order_year"] == "2026"
    assert plan_link["planned_order_month"] == "2026-11"
    # Order-plan-linked rows never project the notice-only deadline field.
    assert plan_link["deadline_at"] is None


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


# --- 재검토 신호 확인·병합 수락·추적 보충 (spec §3.3·§5·§6) ------------------


class _RecordingTrackingHook:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def tracking_decision_changed(self, session, opportunity_id) -> None:
        self.calls.append(opportunity_id)


def _ack(client, opportunity_id, body, actor="확인 담당자"):
    headers = {}
    if actor is not None:
        headers = {
            "X-BidOps-Actor-Name": f"UTF-8''{quote(actor, safe='')}",
            "X-BidOps-Actor-Name-Format": "utf-8-percent-v1",
        }
    return client.post(
        f"/api/opportunities/{opportunity_id}/recheck-acknowledgements",
        json=body,
        headers=headers,
    )


def test_recheck_acknowledgement_clears_signal_keeps_tracking_and_projects_history(
    opportunity_api,
):
    client, session, ended, _plan_opportunity = opportunity_api
    link_id = ended.recheck_signal_link_id
    before = (
        ended.tracking_status,
        ended.tracking_reason,
        ended.tracking_selected_by,
        ended.tracking_selected_at,
    )

    response = _ack(client, ended.id, {"expected_link_id": link_id, "note": "새 공고 비밀 메모"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == ended.id
    assert body["recheck_signal"] is False
    assert body["recheck_signal_at"] is None and body["recheck_signal_link_id"] is None
    assert body["tracking_status"] == "종료"
    session.expire_all()
    stored = session.get(Opportunity, ended.id)
    assert (
        stored.tracking_status,
        stored.tracking_reason,
        stored.tracking_selected_by,
        stored.tracking_selected_at,
    ) == before
    audit = session.scalars(
        select(AuditEvent).where(AuditEvent.action == "opportunity.recheck_signal.acknowledged")
    ).one()
    assert audit.actor_kind == "human"
    assert audit.claimed_name == "확인 담당자"
    assert audit.safe_metadata == {
        "opportunity_id": ended.id,
        "link_id": link_id,
        "note_present": True,
    }
    assert "비밀 메모" not in str(audit.safe_metadata)
    # Acknowledging is not a tracking decision.
    assert session.scalar(
        select(AuditEvent).where(AuditEvent.action == "opportunity.tracking_status.changed")
    ) is None

    history = client.get(f"/api/opportunities/{ended.id}/tracking-decisions")
    assert history.status_code == 200
    payload = history.json()
    assert payload["items"] == []
    events = payload["recheck_events"]
    assert [event["kind"] for event in events] == ["acknowledged", "created"]
    assert events[0] == {
        "kind": "acknowledged",
        "link_id": link_id,
        "actor_kind": "human",
        "claimed_name": "확인 담당자",
        "created_at": events[0]["created_at"],
        "note_present": True,
    }
    assert events[1]["actor_kind"] == "system" and events[1]["claimed_name"] is None
    assert events[1]["link_id"] == link_id and events[1]["note_present"] is False
    assert all(
        datetime.fromisoformat(event["created_at"]).tzinfo is not None for event in events
    )
    assert "비밀 메모" not in history.text

    absent = _ack(client, ended.id, {"expected_link_id": link_id})
    assert absent.status_code == 409
    assert absent.json()["error"] == {
        "code": "recheck_signal_absent",
        "message": "확인할 재검토 신호가 없습니다",
        "details": None,
    }


def test_recheck_acknowledgement_errors_leave_the_signal_untouched(opportunity_api):
    client, session, ended, plan_opportunity = opportunity_api
    link_id = ended.recheck_signal_link_id

    changed = _ack(client, ended.id, {"expected_link_id": link_id + 1000})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "recheck_signal_changed"
    assert changed.json()["error"]["details"] == {"current_link_id": link_id}

    missing = _ack(client, 999999, {"expected_link_id": link_id})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "opportunity_not_found"

    for body in (
        {},
        {"expected_link_id": "1"},
        {"expected_link_id": 0},
        {"expected_link_id": link_id, "note": "가" * 501},
        {"expected_link_id": link_id, "reason": "추가 필드"},
    ):
        assert _ack(client, ended.id, body).status_code == 422

    no_actor = _ack(client, ended.id, {"expected_link_id": link_id}, actor=None)
    assert no_actor.status_code == 400
    assert no_actor.json()["error"]["code"] == "actor_name_required"
    system_actor = client.post(
        f"/api/opportunities/{ended.id}/recheck-acknowledgements",
        json={"expected_link_id": link_id},
        headers={"X-BidOps-Actor-Name": "system"},
    )
    assert system_actor.status_code == 400
    assert system_actor.json()["error"]["code"] == "actor_name_invalid"

    session.expire_all()
    stored = session.get(Opportunity, ended.id)
    assert stored.recheck_signal_link_id == link_id and stored.recheck_signal_at is not None
    assert session.scalar(
        select(AuditEvent).where(AuditEvent.action == "opportunity.recheck_signal.acknowledged")
    ) is None

    merged_notice = Notice(notice_key="bid:ACK-MERGED:000", source_type="bid_notice")
    secondary = Opportunity(
        first_registered_stage="bid_notice",
        created_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    session.add_all([merged_notice, secondary])
    session.flush()
    session.add(
        OpportunityLink(
            opportunity=secondary,
            notice=merged_notice,
            stage="notice",
            link_type="official",
            status="확정",
            evidence_external_no="ACK-MERGED",
        )
    )
    session.flush()
    merge_opportunities(session, [plan_opportunity, secondary])
    session.commit()
    merged = _ack(client, secondary.id, {"expected_link_id": link_id})
    assert merged.status_code == 409
    assert merged.json()["error"]["code"] == "opportunity_merged"


def test_accepting_a_candidate_owned_elsewhere_merges_and_reruns_the_tracking_hook(
    opportunity_api, empty_extensions
):
    client, session, ended, plan_opportunity = opportunity_api
    hook = _RecordingTrackingHook()
    empty_extensions.register_tracking_decision_hook(hook, owner="test")
    target_notice_id = next(link.notice_id for link in ended.links if link.link_type == "official")
    signal_link_id = ended.recheck_signal_link_id
    candidate = OpportunityLink(
        opportunity=plan_opportunity,
        notice_id=target_notice_id,
        stage="notice",
        link_type="candidate",
        status="후보 확인 대기",
        search_strategy="full",
    )
    session.add(candidate)
    session.commit()

    request = {"decision": "accepted", "reason": "같은 사업으로 확인"}
    headers = {"X-BidOps-Actor-Name": "merge-reviewer"}
    response = client.patch(
        f"/api/opportunities/links/{candidate.id}/decision", json=request, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "사람 확인 병합"
    assert body["human_decision"] == "accepted"
    assert datetime.fromisoformat(body["reviewed_at"]).tzinfo is not None
    # Only the closed opportunity holds human state: it is retained as it was.
    assert hook.calls == [ended.id]
    session.expire_all()
    retained = session.get(Opportunity, ended.id)
    assert retained.merged_into_opportunity_id is None
    assert retained.tracking_status == "종료"
    assert retained.recheck_signal_link_id == signal_link_id
    assert session.get(Opportunity, plan_opportunity.id).merged_into_opportunity_id == ended.id
    assert session.get(OpportunityLink, candidate.id).opportunity_id == ended.id
    merged_audit = session.scalars(
        select(AuditEvent).where(AuditEvent.action == "opportunity.merged.human_confirmed")
    ).one()
    assert merged_audit.safe_metadata == {
        "retained_opportunity_id": ended.id,
        "secondary_opportunity_id": plan_opportunity.id,
        "opportunity_link_id": candidate.id,
    }
    detail = client.get(f"/api/opportunities/{ended.id}").json()
    assert {link["status"] for link in detail["links"]} >= {"확정", "사람 확인 병합"}

    replay = client.patch(
        f"/api/opportunities/links/{candidate.id}/decision", json=request, headers=headers
    )
    assert replay.status_code == 200
    assert replay.json()["reviewed_at"] == body["reviewed_at"]
    assert hook.calls == [ended.id]
    assert len(
        session.scalars(
            select(AuditEvent).where(AuditEvent.action == "opportunity.merged.human_confirmed")
        ).all()
    ) == 1


def test_accepting_a_candidate_between_two_human_states_returns_both_states(opportunity_api):
    client, session, ended, plan_opportunity = opportunity_api
    set_tracking_status(
        session,
        plan_opportunity,
        status="계속 추적",
        reason="계획 단계부터 추적",
        selected_by="계획 담당자",
        selected_at=datetime(2026, 8, 30, 3, 4, 5, 678901, tzinfo=timezone.utc),
    )
    target_notice_id = next(link.notice_id for link in ended.links if link.link_type == "official")
    candidate = OpportunityLink(
        opportunity=plan_opportunity,
        notice_id=target_notice_id,
        stage="notice",
        link_type="candidate",
        status="후보 확인 대기",
        search_strategy="full",
    )
    session.add(candidate)
    session.commit()

    response = client.patch(
        f"/api/opportunities/links/{candidate.id}/decision",
        json={"decision": "accepted", "reason": "같은 사업으로 확인"},
        headers={"X-BidOps-Actor-Name": "merge-reviewer"},
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "candidate_merge_state_conflict"
    assert error["details"] == {
        "opportunities": [
            {
                "id": plan_opportunity.id,
                "tracking_status": "계속 추적",
                "tracking_selected_by": "계획 담당자",
                "tracking_selected_at": "2026-08-30T03:04:05.678901+00:00",
                "recheck_signal": False,
                "recheck_signal_at": None,
            },
            {
                "id": ended.id,
                "tracking_status": "종료",
                "tracking_selected_by": "기존 담당자",
                "tracking_selected_at": "2026-08-29T01:00:00+00:00",
                "recheck_signal": True,
                "recheck_signal_at": "2026-08-29T02:00:00+00:00",
            },
        ]
    }
    session.expire_all()
    assert session.get(OpportunityLink, candidate.id).status == "후보 확인 대기"
    assert session.get(Opportunity, plan_opportunity.id).merged_into_opportunity_id is None


def test_accepting_a_candidate_between_two_same_states_merges_over_rest(opportunity_api):
    """ADR-0068: 상태가 같고 신호가 없으면 같은 요청이 409 대신 200이다."""

    client, session, ended, plan_opportunity = opportunity_api
    # 종료 상태를 다시 저장하면 fixture의 재검토 신호가 해소된다(spec §6.2).
    set_tracking_status(
        session,
        ended,
        status="종료",
        reason="신호 확인 후 종료 유지",
        selected_by="기존 담당자",
        selected_at=datetime(2026, 8, 30, 1, tzinfo=timezone.utc),
    )
    set_tracking_status(
        session,
        plan_opportunity,
        status="종료",
        reason="계획 단계에서 종료",
        selected_by="계획 담당자",
        selected_at=datetime(2026, 8, 30, 3, tzinfo=timezone.utc),
    )
    target_notice_id = next(link.notice_id for link in ended.links if link.link_type == "official")
    candidate = OpportunityLink(
        opportunity=plan_opportunity,
        notice_id=target_notice_id,
        stage="notice",
        link_type="candidate",
        status="후보 확인 대기",
        search_strategy="merge_confirmation",
    )
    session.add(candidate)
    session.commit()
    # fixture는 `ended`를 먼저 만든다 — 더 오래된 쪽(동률이면 작은 id)이 유지된다.
    retained_id, merged_id = ended.id, plan_opportunity.id
    assert retained_id < merged_id

    response = client.patch(
        f"/api/opportunities/links/{candidate.id}/decision",
        json={"decision": "accepted", "reason": "같은 사업으로 확인"},
        headers={"X-BidOps-Actor-Name": "merge-reviewer"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "사람 확인 병합"
    session.expire_all()
    assert session.get(Opportunity, retained_id).merged_into_opportunity_id is None
    assert session.get(Opportunity, merged_id).merged_into_opportunity_id == retained_id
    assert session.get(Opportunity, retained_id).tracking_status == "종료"
    merged_audit = session.scalars(
        select(AuditEvent).where(AuditEvent.action == "opportunity.merged.human_confirmed")
    ).one()
    states = merged_audit.safe_metadata["merged_human_states"]
    assert [state["id"] for state in states] == [merged_id]
    assert states[0]["tracking_selected_by"] in {"기존 담당자", "계획 담당자"}


def _write_collection_run(root, name, plan_no, bid_no):
    run_dir = root / "data" / "runs" / name
    run_dir.mkdir(parents=True)
    window = {"from": "2026-09-16", "to": "2026-09-16", "timezone": "Asia/Seoul"}
    (run_dir / "collected-order-plans.json").write_text(
        json.dumps(
            {
                "schema_version": "bidops.collected-order-plans.v1",
                "generated_at": "2026-09-16T00:00:00+00:00",
                "source_window": window,
                "counts": {"total": 1},
                "order_plans": [
                    {
                        "order_plan_unty_no": plan_no,
                        "title": "추적 보충 발주계획",
                        "agency_name": "보충 기관",
                        "published_at": "2026-09-10T09:00:00+09:00",
                        "source_sha256": "b" * 64,
                        "raw_source": "raw/page-00001.json",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "collected-notices.json").write_text(
        json.dumps(
            {
                "schema_version": "bidops.collected.v2",
                "generated_at": "2026-09-16T00:00:00+00:00",
                "source_window": window,
                "counts": {"total": 1, "candidate_pool": 0, "audit_pool": 1},
                "warnings": [],
                "metadata": {"sw_industry_1468": {"status": "complete", "total": 0, "pages": 1}},
                "notices": [
                    {
                        "notice_id": f"bid:{bid_no}:000",
                        "source_type": "bid_notice",
                        "title": "색인에만 있는 입찰공고",
                        "agency": "보충 기관",
                        "published_at": "2026-09-16T10:00:00+09:00",
                        "method": "일반경쟁",
                        "lifecycle": {"order_plan_no": plan_no},
                        "qualification_flags": {"sw_industry_1468": "N"},
                        "raw_source": "raw/bid-page-001.json",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return run_dir


def test_saving_a_tracked_status_backfills_index_only_records(
    opportunity_api, empty_extensions, monkeypatch, tmp_path
):
    client, session, _ended, _plan_opportunity = opportunity_api
    plan_no, bid_no = "R26DD20859001", "R26BK01699101"
    run_dir = _write_collection_run(tmp_path, "lifecycle-20260916-notices", plan_no, bid_no)
    ingest_run(run_dir, session, selection="collection")
    plan = session.scalar(select(OrderPlan).where(OrderPlan.order_plan_unty_no == plan_no))
    owner_id = session.scalar(
        select(OpportunityLink.opportunity_id).where(OpportunityLink.order_plan_id == plan.id)
    )
    assert session.scalar(select(Notice).where(Notice.notice_key == f"bid:{bid_no}:000")) is None
    monkeypatch.setattr(
        opportunities_router, "get_settings", lambda: SimpleNamespace(bidops_root=tmp_path)
    )

    response = client.patch(
        f"/api/opportunities/{owner_id}/tracking-status",
        json={"tracking_status": "보류", "reason": "공고 대기"},
        headers={"X-BidOps-Actor-Name": "tracker"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tracking_status"] == "보류"
    bid = session.scalar(select(Notice).where(Notice.notice_key == f"bid:{bid_no}:000"))
    assert bid is not None
    assert bid.id in {link["notice_id"] for link in body["links"]}
    row = session.scalar(
        select(CollectedRecordIndex).where(CollectedRecordIndex.record_key == f"bid:{bid_no}:000")
    )
    assert row.selection_reason == "tracked_backfill" and row.ingested_notice_id == bid.id
    # The backfilled bid joined a held opportunity automatically: new link signal.
    assert body["recheck_signal"] is True


def test_backfill_failure_after_tracking_save_keeps_the_decision(
    opportunity_api, empty_extensions, monkeypatch, caplog
):
    client, session, _ended, plan_opportunity = opportunity_api

    def fail(*_args, **_kwargs):
        raise RuntimeError("/private/runs secret")

    monkeypatch.setattr(opportunities_router, "tracked_backfill", fail)
    with caplog.at_level("WARNING"):
        response = client.patch(
            f"/api/opportunities/{plan_opportunity.id}/tracking-status",
            json={"tracking_status": "계속 추적", "reason": "추적 시작"},
            headers={"X-BidOps-Actor-Name": "tracker"},
        )

    assert response.status_code == 200
    assert response.json()["tracking_status"] == "계속 추적"
    session.expire_all()
    assert session.get(Opportunity, plan_opportunity.id).tracking_status == "계속 추적"
    events = [getattr(record, "bidops", {}) for record in caplog.records]
    assert {"event": "opportunity.tracked_backfill_failed", "failure_type": "RuntimeError"} in events
    assert "/private/runs" not in caplog.text


def _write_search_run(root, name, plan_no, pre_spec_no):
    """발주계획 하나와 SW사업대상이 아닌(색인에만 남는) 사전규격 하나."""

    run_dir = root / "data" / "runs" / name
    run_dir.mkdir(parents=True)
    window = {"from": "2026-09-16", "to": "2026-09-16", "timezone": "Asia/Seoul"}
    (run_dir / "collected-order-plans.json").write_text(
        json.dumps(
            {
                "schema_version": "bidops.collected-order-plans.v1",
                "generated_at": "2026-09-16T00:00:00+00:00",
                "source_window": window,
                "counts": {"total": 1},
                "order_plans": [
                    {
                        "order_plan_unty_no": plan_no,
                        "title": "지능형 민원 상담 플랫폼 구축",
                        "agency_name": "찾기 기관",
                        "published_at": "2026-09-10T09:00:00+09:00",
                        "planned_order_year": "2026",
                        "budget_amount": "250000000",
                        "source_sha256": "c" * 64,
                        "raw_source": "raw/page-00001.json",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "collected-notices.json").write_text(
        json.dumps(
            {
                "schema_version": "bidops.collected.v2",
                "generated_at": "2026-09-16T00:00:00+00:00",
                "source_window": window,
                "counts": {"total": 1, "candidate_pool": 0, "audit_pool": 1},
                "warnings": [],
                "metadata": {"sw_industry_1468": {"status": "complete", "total": 0, "pages": 1}},
                "notices": [
                    {
                        "notice_id": f"pre:{pre_spec_no}",
                        "source_type": "pre_spec",
                        "title": "2026 지능형 민원 상담 플랫폼 구축 사전규격",
                        "agency": "조달청",
                        "demand_agency": "찾기 기관",
                        "published_at": "2026-09-16T10:00:00+09:00",
                        "lifecycle": {"pre_spec_no": pre_spec_no},
                        "qualification_flags": {"sw_business_status": "N"},
                        "raw_source": "raw/prespec-page-001.json",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return run_dir


def test_search_endpoint_proposes_an_index_only_pre_spec_and_lists_it_on_the_pre_spec(
    opportunity_api, empty_extensions, monkeypatch, tmp_path
):
    client, session, ended, _plan_opportunity = opportunity_api
    plan_no, pre_spec_no = "R26DD20859701", "R26BD00279701"
    run_dir = _write_search_run(tmp_path, "lifecycle-20260916-notices", plan_no, pre_spec_no)
    ingest_run(run_dir, session, selection="collection")
    plan = session.scalar(select(OrderPlan).where(OrderPlan.order_plan_unty_no == plan_no))
    owner_id = session.scalar(
        select(OpportunityLink.opportunity_id).where(OpportunityLink.order_plan_id == plan.id)
    )
    assert session.scalar(select(Notice).where(Notice.notice_key == f"pre:{pre_spec_no}")) is None
    monkeypatch.setattr(
        opportunities_router, "get_settings", lambda: SimpleNamespace(bidops_root=tmp_path)
    )
    actor = "김도윤"
    headers = {
        "X-BidOps-Actor-Name": f"UTF-8''{quote(actor, safe='')}",
        "X-BidOps-Actor-Name-Format": "utf-8-percent-v1",
    }

    response = client.post(
        f"/api/opportunities/{owner_id}/searches", json={"target": "pre_spec"}, headers=headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"searched_at", "target", "attempted_strategies", "candidates", "search_unconfirmed"}
    assert body["target"] == "pre_spec" and body["search_unconfirmed"] is False
    assert body["attempted_strategies"] == ["full", "prefix12"]
    (candidate,) = body["candidates"]
    assert candidate["status"] == "후보 확인 대기" and candidate["link_type"] == "candidate"
    assert candidate["search_strategy"] == "full" and candidate["agency_match"] is True
    assert candidate["record_external_id"] == f"pre:{pre_spec_no}"
    audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "opportunity.search.performed"))
    assert audit.claimed_name == actor
    assert set(audit.safe_metadata) >= {"candidate_count", "loaded_count", "search_unconfirmed"}
    assert "지능형" not in json.dumps(audit.safe_metadata, ensure_ascii=False)

    pre_spec = session.scalar(select(Notice).where(Notice.notice_key == f"pre:{pre_spec_no}"))
    listed = client.get(f"/api/pre-specs/{pre_spec.id}/order-plan-candidates")
    assert listed.status_code == 200, listed.text
    listing = listed.json()
    assert listing["notice_pk"] == pre_spec.id
    (item,) = listing["items"]
    assert item["opportunity_id"] == owner_id and item["tracking_status"] == "미선택"
    assert item["link"]["id"] == candidate["id"]
    assert item["order_plans"] == [
        {
            "order_plan_id": plan.id,
            "order_plan_unty_no": plan_no,
            "title": "지능형 민원 상담 플랫폼 구축",
            "agency_name": "찾기 기관",
            "planned_order_year": "2026",
            "planned_order_month": None,
            "budget_amount": 250000000.0,
        }
    ]
    ended_notice_id = next(link.notice_id for link in ended.links if link.link_type == "official")
    assert client.get(f"/api/pre-specs/{ended_notice_id}/order-plan-candidates").status_code == 404
    assert client.get("/api/pre-specs/999999/order-plan-candidates").status_code == 404


def test_search_endpoint_errors_are_safe_and_write_nothing(opportunity_api, empty_extensions, monkeypatch, tmp_path):
    client, session, ended, plan_opportunity = opportunity_api
    monkeypatch.setattr(
        opportunities_router, "get_settings", lambda: SimpleNamespace(bidops_root=tmp_path)
    )
    headers = {"X-BidOps-Actor-Name": "searcher"}

    missing_actor = client.post(f"/api/opportunities/{ended.id}/searches", json={"target": "pre_spec"})
    assert missing_actor.status_code == 400
    assert missing_actor.json()["error"]["code"] == "actor_name_required"
    unknown = client.post("/api/opportunities/999999/searches", json={"target": "pre_spec"}, headers=headers)
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "opportunity_not_found"
    source = client.post(f"/api/opportunities/{ended.id}/searches", json={"target": "pre_spec"}, headers=headers)
    assert source.status_code == 422
    assert source.json()["error"] == {
        "code": "search_source_missing",
        "message": "찾아보기의 기준이 될 소유 발주계획 또는 사전규격이 없습니다",
        "details": {"target": "pre_spec"},
    }
    invalid = client.post(f"/api/opportunities/{ended.id}/searches", json={"target": "order_plan"}, headers=headers)
    assert invalid.status_code == 422
    merge_opportunities(session, [plan_opportunity, ended])
    session.commit()
    merged_id = plan_opportunity.id if plan_opportunity.merged_into_opportunity_id else ended.id
    merged = client.post(f"/api/opportunities/{merged_id}/searches", json={"target": "pre_spec"}, headers=headers)
    assert merged.status_code == 409 and merged.json()["error"]["code"] == "opportunity_merged"
    assert session.scalar(
        select(AuditEvent).where(AuditEvent.action == "opportunity.search.performed")
    ) is None

    # 찾은 것이 없으면 검색 미확인이다. 소유 발주계획이 기준이 된다.
    retained_id = ended.id if merged_id != ended.id else plan_opportunity.id
    unconfirmed = client.post(
        f"/api/opportunities/{retained_id}/searches", json={"target": "bid_notice"}, headers=headers
    )
    assert unconfirmed.status_code == 200, unconfirmed.text
    assert unconfirmed.json()["search_unconfirmed"] is True and unconfirmed.json()["candidates"] == []
    detail = client.get(f"/api/opportunities/{retained_id}").json()
    assert any(
        link["status"] == "검색 미확인"
        and link["last_searched_at"] is not None
        and link["search_target_kind"] == "bid_notice"
        for link in detail["links"]
    )


def test_deadline_within_days_window_and_deadline_sort(opportunity_api, monkeypatch):
    """마감 임박 추적 건의 창·모집단·정렬 (ADR-0067 결정 3·4·6).

    창은 링크 단위로 판정하고 사업을 돌려준다. 하한은 요청 시각, 상한은 요청 시각 KST
    일자 + N일의 끝(열린 경계)이다. 추적 대상(`계속 추적`·`보류`)만 들고, 확인 대기
    후보 연결의 마감은 사업을 올리지 않는다. `sort=deadline`은 창과 무관한 정렬 키다.
    """

    client, session, ended, plan_opportunity = opportunity_api
    now = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)  # KST 09-20 12:00
    monkeypatch.setattr(opportunities_router, "_request_now", lambda: now)

    def linked(label, *, tracking, deadline, link_type="official", status="확정"):
        selected = tracking != "미선택"
        opportunity = Opportunity(
            first_registered_stage="pre_spec", tracking_status=tracking,
            tracking_reason="사람 선택" if selected else None,
            tracking_selected_by="담당자" if selected else None,
            tracking_selected_at=now if selected else None,
        )
        notice = Notice(
            notice_key=f"pre:WINDOW-{label}", source_type="pre_spec",
            title=f"{label} 사전규격", agency="테스트 기관", deadline_at=deadline,
        )
        session.add_all([opportunity, notice])
        session.flush()
        session.add(OpportunityLink(
            opportunity=opportunity, notice=notice, stage="notice",
            link_type=link_type, status=status,
            evidence_external_no=f"PRE-{label}" if link_type == "official" else None,
        ))
        session.flush()
        return opportunity

    # KST 09-27 23:59:59 — 정확히 7일 뒤 날짜의 끝이라 창 안이다.
    tracked = linked("LAST-DAY", tracking="계속 추적", deadline=datetime(2026, 9, 27, 14, 59, 59, tzinfo=timezone.utc))
    at_now = linked("AT-NOW", tracking="보류", deadline=now)
    # KST 09-28 00:00 — 열린 상한이라 밖이다.
    after = linked("AFTER", tracking="계속 추적", deadline=datetime(2026, 9, 27, 15, 0, tzinfo=timezone.utc))
    passed = linked("PASSED", tracking="계속 추적", deadline=now - timedelta(microseconds=1))
    candidate = linked("CANDIDATE", tracking="계속 추적", deadline=now + timedelta(days=1),
                       link_type="candidate", status="후보 확인 대기")
    unselected = linked("UNSELECTED", tracking="미선택", deadline=datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc))
    session.commit()

    def ids(**params):
        response = client.get("/api/opportunities", params=params)
        assert response.status_code == 200, response.text
        return response.json()

    window = ids(deadline_within_days=7, sort="deadline")
    assert [row["id"] for row in window["items"]] == [at_now.id, tracked.id]
    assert window["total"] == 2
    # 건수와 목록이 같은 분류를 읽는다: `보류`는 보류 구역, 후보 대기가 없는 계속 추적은 추적 중.
    assert window["section_counts"]["보류"] == 1 and window["section_counts"]["추적 중"] == 1
    assert ids(deadline_within_days=1)["total"] == 1
    # 창은 정렬과 독립이다. 정렬 키는 아직 남은 권위 연결 마감 중 가장 이른 것이고,
    # 그런 마감이 없는 사업(후보 연결만·마감 경과·발주계획)은 맨 뒤다.
    ordered = [row["id"] for row in ids(sort="deadline", limit=500)["items"]]
    assert ordered[:5] == [at_now.id, ended.id, unselected.id, tracked.id, after.id]
    assert set(ordered[5:]) == {passed.id, candidate.id, plan_opportunity.id}
    # 인자가 없으면 창이 없다.
    assert ids()["total"] == len(ordered)
    for invalid in (0, -1, 366):
        assert client.get("/api/opportunities", params={"deadline_within_days": invalid}).status_code == 422


# --- RL-02 활동 피드 REST (`GET /api/opportunities/{id}/activity`) -------------

ACTIVITY_RESPONSE_KEYS = {
    "schema_version", "opportunity_id", "merged_into_opportunity_id", "title", "stages", "items", "next_before",
}
ACTIVITY_ITEM_KEYS = {"item_id", "kind", "at", "actor", "title", "detail", "link", "status_pill"}


def test_activity_feed_returns_the_v1_shape_with_title_stages_and_items(opportunity_api):
    client, _session, ended, plan_opportunity = opportunity_api
    (ended_link_id,) = [link.id for link in ended.links if link.link_type == "official"]
    (plan_link_id,) = [link.id for link in plan_opportunity.links]

    response = client.get(f"/api/opportunities/{ended.id}/activity")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == ACTIVITY_RESPONSE_KEYS
    assert payload["schema_version"] == "bidops.opportunity-activity.v1"
    assert payload["opportunity_id"] == ended.id
    assert payload["merged_into_opportunity_id"] is None
    assert payload["title"] == "사업기회 입찰공고"
    assert [stage["key"] for stage in payload["stages"]] == [
        "order_plan", "pre_spec", "bid_notice", "deadline", "opening", "contract",
    ]
    assert all(set(stage) == {"key", "state", "at", "link_id"} for stage in payload["stages"])
    # 대표 연결 id: 입찰공고와 그것을 따르는 마감·개찰만 값이 있고 `검색 미확인` 행은 대표가 아니다.
    assert [stage["link_id"] for stage in payload["stages"]] == [
        None, None, ended_link_id, ended_link_id, ended_link_id, None,
    ]
    # 마감(2026-09-25)이 지났으므로 입찰공고·마감은 done이고 건너뛴 앞 단계는 미확인이다.
    assert [stage["state"] for stage in payload["stages"]] == [
        "unknown", "unknown", "done", "done", "unknown", "unknown",
    ]
    assert payload["stages"][3]["at"] == "2026-09-25T01:00:00Z"
    assert all(set(item) == ACTIVITY_ITEM_KEYS for item in payload["items"])
    by_kind = {item["kind"]: item for item in payload["items"]}
    assert set(by_kind) == {"bid_posted", "recheck_signal"}
    assert by_kind["recheck_signal"] == {
        "item_id": by_kind["recheck_signal"]["item_id"],
        "kind": "recheck_signal",
        "at": "2026-08-29T02:00:00Z",
        "actor": None,
        "title": "재확인 신호",
        "detail": None,
        "link": None,
        "status_pill": None,
    }
    # 공고 URL이 없으면 링크를 만들지 않는다(내부 입찰공고 상세 라우트는 없다).
    assert by_kind["bid_posted"]["link"] is None
    assert payload["next_before"] is None

    plan_payload = client.get(f"/api/opportunities/{plan_opportunity.id}/activity").json()
    assert plan_payload["title"] == "사업기회 발주계획"
    assert [stage["state"] for stage in plan_payload["stages"]][:3] == ["current", "pending", "pending"]
    assert [stage["link_id"] for stage in plan_payload["stages"]] == [plan_link_id, None, None, None, None, None]
    (found,) = plan_payload["items"]
    assert (found["kind"], found["title"]) == ("order_plan_found", "발주계획 발견 · 계획 기관")
    assert found["link"]["path"].startswith("/order-plans/")


def test_activity_feed_pages_with_the_opaque_cursor_and_filters_kinds(opportunity_api):
    client, session, ended, _plan_opportunity = opportunity_api
    set_tracking_status(
        session, ended, status="보류", reason="예산 확인", selected_by="김담당",
        selected_at=datetime(2026, 9, 1, 1, tzinfo=timezone.utc),
    )
    session.commit()
    path = f"/api/opportunities/{ended.id}/activity"

    full = [item["item_id"] for item in client.get(path).json()["items"]]
    first = client.get(path, params={"limit": 2}).json()
    second = client.get(path, params={"limit": 2, "before": first["next_before"]}).json()
    filtered = client.get(path, params={"kinds": "tracking_decided,recheck_signal"}).json()

    assert len(full) == 3
    assert [item["item_id"] for item in first["items"]] + [item["item_id"] for item in second["items"]] == full
    assert first["next_before"] == f"{first['items'][-1]['at']}|{first['items'][-1]['item_id']}"
    assert second["next_before"] is None
    assert [item["kind"] for item in filtered["items"]] == ["tracking_decided", "recheck_signal"]
    assert filtered["items"][0]["title"] == "김담당이 보류로 결정"


def test_activity_feed_errors_are_safe(opportunity_api):
    client, _session, ended, _plan_opportunity = opportunity_api
    path = f"/api/opportunities/{ended.id}/activity"

    missing = client.get("/api/opportunities/999999/activity")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "opportunity_not_found"
    for params in ({"limit": 0}, {"limit": 201}, {"limit": "many"}):
        assert client.get(path, params=params).status_code == 422
    for params in ({"before": "bad"}, {"before": "2026-09-01T00:00:00|bid_posted:1"}, {"kinds": "run_ingested"}):
        response = client.get(path, params=params)
        assert response.status_code == 422, params
        assert response.json()["error"] == {
            "code": "invalid_request", "message": "요청이 올바르지 않습니다", "details": None,
        }


def test_activity_feed_serves_a_merged_opportunity_with_its_survivor(opportunity_api):
    client, session, ended, plan_opportunity = opportunity_api
    merged = Opportunity(
        first_registered_stage="order_plan",
        merged_into_opportunity_id=plan_opportunity.id,
        merged_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        merge_reason="합성 병합",
    )
    session.add(merged)
    session.commit()

    response = client.get(f"/api/opportunities/{merged.id}/activity")

    assert response.status_code == 200
    payload = response.json()
    assert payload["merged_into_opportunity_id"] == plan_opportunity.id
    assert payload["title"] == f"#{merged.id}"
    assert payload["items"] == []
