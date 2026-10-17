"""평일 브리핑 REST·반응·Slack 미리보기·workload (RL-01 spec "REST", T6 기본, T7, T8 허용 키).

SQLite 격리 DB에서 조립 앱(lifecycle)을 띄워 실제 경로로 부른다. PostgreSQL 변형(strict
dict·권한·CHECK)은 `test_briefing_api_postgres.py`가 갖는다.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
import json
from urllib.parse import quote_from_bytes
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import get_db, init_db
from app.core.models import IdempotencyRecord
from app.lifecycle.models import (
    Briefing,
    BriefingItem,
    BriefingReactionEvent,
    CompanyOpportunityTracking,
    Opportunity,
)
from app.lifecycle.services.briefing import BriefingError, build_briefing, react_to_item
from app.lifecycle.services.briefing_policy import load_briefing_policy
from app.lifecycle.services.briefing_slack import SLACK_PAYLOAD_KEYS, SLACK_REACT_ACTION_ID
from app.main import create_app
from tests.lifecycle.briefing_fixtures import (
    BRIEFING_DATE,
    GRAPH,
    NEXT_BRIEFING_DATE,
    NOW,
    FakeOrderPlans,
    World,
    register_providers,
)

ACTOR = {"X-BidOps-Actor-Name": "kim"}
ITEM_KEYS = {
    "item_id", "kind", "rank", "stage", "notice_id", "order_plan_id", "opportunity_id", "title", "agency",
    "amount_krw", "deadline_at", "deadline_kind", "planned_month", "verdict_display", "reasons", "blocking",
    "change_fields", "reaction", "reacted_by", "reacted_at", "reacted_via", "revision", "record_path",
}
VIEW_KEYS = {
    "schema_version", "briefing_date", "status", "generated_at", "item_count", "slack_sent_at", "items",
    "tracked_changes", "collection_note",
}


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
    with Session(engine, expire_on_commit=False) as value:
        yield value
    engine.dispose()


@contextmanager
def client_for(session):
    application = create_app(modules=("lifecycle",), mount_frontend=False)
    application.dependency_overrides[get_db] = lambda: session
    with TestClient(application) as client:
        yield client


@pytest.fixture
def plans(empty_extensions):
    provider = FakeOrderPlans()
    register_providers(empty_extensions, plans=provider)
    return provider


def seed(session, plans):
    """추천 3건(사전규격·입찰공고·발주계획)과 추적 변화 1건."""

    world = World(session)
    world.collection_run()
    pre_spec = world.notice("홈페이지 유지관리 용역", deadline_at=NOW + timedelta(days=3),
                            estimated_price=2_500_000_000, agency="대구광역시")
    bid = world.notice("데이터 플랫폼 구축", source_type="bid_notice", sw=None,
                       deadline_at=NOW + timedelta(days=20), agency="경상북도")
    plan = world.plan("스마트 관광 플랫폼 고도화 용역 3차")
    plans.ids = [plan.id]
    tracked_owner = world.opportunity(tracking_status="계속 추적")
    tracked = world.notice("추적 중 통합 시스템", owner=tracked_owner, observed_at=NOW - timedelta(days=10),
                           deadline_at=NOW + timedelta(days=12))
    world.observe(tracked, NOW - timedelta(hours=1), ["deadline_at"])
    session.commit()
    result = build_briefing(session, BRIEFING_DATE, now=NOW)
    session.commit()
    assert (result.status, result.item_count, result.tracked_change_count) == ("generated", 3, 1)
    return {"pre_spec": pre_spec, "bid": bid, "plan": plan, "tracked": tracked, "tracked_owner": tracked_owner}


def _item(session, **where) -> BriefingItem:
    return session.scalars(select(BriefingItem).filter_by(**where)).one()


def _walk_keys(value, keys: set[str]) -> set[str]:
    if isinstance(value, dict):
        keys.update(value)
        for item in value.values():
            _walk_keys(item, keys)
    elif isinstance(value, list):
        for item in value:
            _walk_keys(item, keys)
    return keys


# --- 조회 ---------------------------------------------------------------------


def test_missing_briefing_is_404_envelope_and_bad_date_is_422(session, plans) -> None:
    with client_for(session) as client:
        for path in ("/api/briefings/latest", "/api/briefings/2026-10-16", "/api/briefings/2026-10-16/slack-preview"):
            response = client.get(path)
            assert response.status_code == 404, path
            assert response.json() == {
                "error": {"code": "briefing_not_found", "message": "브리핑을 찾을 수 없습니다", "details": None},
                "request_id": None,
            }
        for bad in ("2026-13-01", "20261016", "latest-ish"):
            response = client.get(f"/api/briefings/{bad}")
            assert response.status_code == 422
            assert "detail" in response.json()


def test_briefing_view_shape_and_operational_fields_are_not_exposed(session, plans) -> None:
    rows = seed(session, plans)
    briefing = session.scalar(select(Briefing))
    with client_for(session) as client:
        latest = client.get("/api/briefings/latest")
        by_date = client.get("/api/briefings/2026-10-16")
    assert latest.status_code == by_date.status_code == 200
    body = latest.json()
    assert body == by_date.json()
    assert set(body) == VIEW_KEYS
    assert (body["schema_version"], body["briefing_date"], body["status"], body["item_count"]) == (
        # RL-03 spec "연결": v1 → v2(키 동일, `verdict_display` 값 집합만 확장).
        "bidops.briefing.v2", "2026-10-16", "generated", 3,
    )
    assert body["slack_sent_at"] is None and body["collection_note"] is None
    # 운영 정보(점수·규칙 파일 sha·그래프 버전)는 키로도 값으로도 응답에 없다.
    raw = latest.text
    for forbidden in ("score", "policy_sha256", "graph_version_id", briefing.policy_sha256, str(GRAPH)):
        assert forbidden not in raw
    items = body["items"]
    assert all(set(item) == ITEM_KEYS for item in items + body["tracked_changes"])
    assert [item["rank"] for item in items] == [1, 2, 3]
    by_stage = {item["stage"]: item for item in items}
    first = by_stage["pre_spec"]
    assert (first["title"], first["agency"], first["amount_krw"], first["deadline_kind"]) == (
        "홈페이지 유지관리 용역", "대구광역시", 2_500_000_000, "opinion_close",
    )
    assert first["verdict_display"] == "분석 대기"
    assert first["reasons"] == [{"kind": "keyword", "text": "유지관리", "count": None}]
    assert [block["kind"] for block in first["blocking"]] == ["consortium_review", "deadline_short"]
    assert (first["reaction"], first["revision"], first["reacted_by"]) == ("대기", 0, None)
    assert first["record_path"] == f"/opportunities/{first['opportunity_id']}"
    plan = by_stage["order_plan"]
    assert (plan["verdict_display"], plan["deadline_kind"], plan["planned_month"], plan["notice_id"]) == (
        "연차 추적", "planned_month", "2027-02", None,
    )
    assert plan["order_plan_id"] == rows["plan"].id
    assert by_stage["bid_notice"]["deadline_kind"] == "bid_close"
    [change] = body["tracked_changes"]
    assert (change["kind"], change["rank"], change["reaction"], change["verdict_display"]) == (
        "tracked_change", None, None, "재검토 중",
    )
    assert change["change_fields"] == ["deadline_at"]
    assert change["opportunity_id"] == rows["tracked_owner"].id


def test_latest_is_the_most_recent_briefing_date(session, plans) -> None:
    seed(session, plans)
    later = build_briefing(session, NEXT_BRIEFING_DATE, now=NOW + timedelta(days=3))
    session.commit()
    assert later.created
    with client_for(session) as client:
        assert client.get("/api/briefings/latest").json()["briefing_date"] == "2026-10-19"
        assert client.get("/api/briefings/2026-10-16").json()["briefing_date"] == "2026-10-16"


def test_collection_note_is_exposed_only_for_incomplete_collection(session, plans) -> None:
    World(session).notice("홈페이지 유지관리 용역")
    session.commit()
    build_briefing(session, BRIEFING_DATE, now=NOW)
    session.commit()
    with client_for(session) as client:
        body = client.get("/api/briefings/latest").json()
    assert (body["status"], body["collection_note"], body["item_count"]) == (
        "collection_incomplete", "기준일 수집 회차 없음", 1,
    )


# --- Slack 미리보기 -------------------------------------------------------------


def test_slack_preview_uses_allowed_keys_and_only_item_summary_fields(session, plans, monkeypatch) -> None:
    seed(session, plans)
    briefing = session.scalar(select(Briefing))
    monkeypatch.setenv("BIDOPS_SLACK_BOT_TOKEN", "xoxb-should-never-appear")
    monkeypatch.delenv("BIDOPS_SLACK_CHANNEL_ID", raising=False)
    monkeypatch.setenv("BIDOPS_PUBLIC_BASE_URL", "https://bidops.example.invalid/")
    get_settings.cache_clear()
    try:
        with client_for(session) as client:
            response = client.get("/api/briefings/2026-10-16/slack-preview")
            monkeypatch.setenv("BIDOPS_SLACK_CHANNEL_ID", "C0FIXTURE")
            get_settings.cache_clear()
            with_channel = client.get("/api/briefings/2026-10-16/slack-preview").json()
            view = client.get("/api/briefings/2026-10-16").json()
    finally:
        get_settings.cache_clear()
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"schema_version", "channel_id_present", "blocks", "text"}
    assert body["schema_version"] == "bidops.briefing-slack-preview.v1"
    assert body["channel_id_present"] is False and with_channel["channel_id_present"] is True
    assert with_channel["blocks"] == body["blocks"]
    blocks = body["blocks"]
    assert _walk_keys(blocks, set()) <= SLACK_PAYLOAD_KEYS
    raw = json.dumps(body, ensure_ascii=False)
    for forbidden in ("xoxb-", "C0FIXTURE", "score", briefing.policy_sha256, str(GRAPH), "policy"):
        assert forbidden not in raw
    headers = [block["text"]["text"] for block in blocks if block["type"] == "header"]
    assert headers == ["오늘의 브리핑 · 10월 16일 (금) · 3건", "추적 중 사업 변화"]
    buttons = [element for block in blocks if block["type"] == "actions" for element in block["elements"]]
    item_ids = [item["item_id"] for item in view["items"]]
    assert [button["value"] for button in buttons] == [
        value for item_id in item_ids for value in (f"{item_id}:채택", f"{item_id}:무시")
    ]
    assert {button["action_id"] for button in buttons} == {SLACK_REACT_ACTION_ID}
    assert [button.get("style") for button in buttons[:2]] == ["primary", None]
    assert [button["text"]["text"] for button in buttons[:2]] == ["볼게요", "무시"]
    sections = [block["text"]["text"] for block in blocks if block["type"] == "section"]
    first = next(item for item in view["items"] if item["stage"] == "pre_spec")
    assert (
        f"*<https://bidops.example.invalid/opportunities/{first['opportunity_id']}|홈페이지 유지관리 용역>*\n"
        "대구광역시 · 25억 원 · *마감 D-3*"
    ) in sections
    assert any("경상북도 · 금액 미공개 · 마감 D-20" in section for section in sections)
    assert any("발주 예정 2027-02" in section for section in sections)
    assert sections.count("<https://bidops.example.invalid/briefing?date=2026-10-16|화면에서 보기>") == 2
    contexts = [element["text"] for block in blocks if block["type"] == "context" for element in block["elements"]]
    assert "키워드 · 유지관리" in contexts
    assert "20억 원 이상 · 컨소시엄 검토 · 마감 3일" in contexts
    assert "바뀐 항목: 마감" in contexts
    assert body["text"] == "오늘의 브리핑 · 10월 16일 (금) · 3건\n추적 중 사업 변화"


def test_slack_preview_of_an_empty_briefing_sends_nothing(session, plans) -> None:
    world = World(session)
    world.collection_run()
    world.notice("하드웨어 장비 구매")
    session.commit()
    assert build_briefing(session, BRIEFING_DATE, now=NOW).status == "empty"
    session.commit()
    with client_for(session) as client:
        body = client.get("/api/briefings/2026-10-16/slack-preview").json()
    assert (body["blocks"], body["text"]) == ([], "")


# --- 반응 ---------------------------------------------------------------------


def _patch(client, item_id, *, reaction="채택", expected_revision=0, request_id=None, headers=ACTOR):
    body = {"reaction": reaction, "expected_revision": expected_revision,
            "request_id": str(request_id or uuid4())}
    return client.patch(f"/api/briefings/items/{item_id}/reaction", json=body, headers=headers)


def _tracking_state(session):
    return [
        (row.id, row.tracking_status, row.tracking_reason, row.tracking_selected_by, row.tracking_selected_at)
        for row in session.scalars(select(Opportunity).order_by(Opportunity.id))
    ]


def test_reaction_patch_flow_appends_events_and_never_touches_tracking(session, plans) -> None:
    rows = seed(session, plans)
    target = _item(session, notice_id=rows["pre_spec"].id)
    tracked = _item(session, notice_id=rows["tracked"].id)
    before_tracking = _tracking_state(session)
    request_id = uuid4()
    with client_for(session) as client:
        missing_actor = _patch(client, target.id, headers={})
        bad_body = client.patch(f"/api/briefings/items/{target.id}/reaction",
                                json={"reaction": "좋아요", "expected_revision": 0, "request_id": str(uuid4())},
                                headers=ACTOR)
        unknown = _patch(client, uuid4())
        not_allowed = _patch(client, tracked.id)
        first = _patch(client, target.id, request_id=request_id)
        replay = _patch(client, target.id, request_id=request_id)
        conflict = _patch(client, target.id, reaction="무시", request_id=request_id)
        stale = _patch(client, target.id, reaction="무시", expected_revision=0)
        undo = _patch(client, target.id, reaction="대기", expected_revision=1)

    assert missing_actor.status_code == 400
    assert missing_actor.json()["error"]["code"] == "actor_name_required"
    assert bad_body.status_code == 422 and "detail" in bad_body.json()
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "briefing_item_not_found"
    assert not_allowed.status_code == 409 and not_allowed.json()["error"]["code"] == "reaction_not_allowed"
    assert first.status_code == 200
    accepted = first.json()
    assert set(accepted) == ITEM_KEYS
    assert (accepted["reaction"], accepted["revision"], accepted["reacted_by"], accepted["reacted_via"]) == (
        "채택", 1, "kim", "screen",
    )
    assert accepted["reacted_at"] is not None
    assert replay.status_code == 200 and replay.json() == accepted
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert conflict.json()["request_id"] == str(request_id)
    assert stale.status_code == 409
    assert stale.json()["error"] == {
        "code": "version_conflict", "message": "브리핑 항목이 변경되었습니다", "details": {"current_revision": 1},
    }
    assert undo.status_code == 200
    assert (undo.json()["reaction"], undo.json()["revision"]) == ("대기", 2)

    events = session.scalars(
        select(BriefingReactionEvent).where(BriefingReactionEvent.item_id == target.id)
        .order_by(BriefingReactionEvent.revision)
    ).all()
    assert [(event.revision, event.previous, event.new, event.actor, event.via) for event in events] == [
        (1, "대기", "채택", "kim", "screen"),
        (2, "채택", "대기", "kim", "screen"),
    ]
    assert events[0].request_id == request_id
    assert session.scalar(
        select(func.count(IdempotencyRecord.id)).where(IdempotencyRecord.operation == "briefing.react")
    ) == 2
    session.expire_all()
    refreshed = session.get(BriefingItem, target.id)
    assert (refreshed.reaction, refreshed.revision, refreshed.reacted_by) == ("대기", 2, "kim")
    assert session.get(BriefingItem, tracked.id).revision == 0
    # 반응은 추적 상태를 바꾸지 않는다(ux-review 결정 3, spec T6).
    assert _tracking_state(session) == before_tracking
    assert session.scalar(select(func.count()).select_from(CompanyOpportunityTracking)) == 0


def test_non_ascii_actor_uses_the_percent_format_header(session, plans) -> None:
    rows = seed(session, plans)
    target = _item(session, notice_id=rows["bid"].id)
    encoded = "UTF-8''" + quote_from_bytes("김담당".encode("utf-8"), safe="")
    headers = {"X-BidOps-Actor-Name": encoded, "X-BidOps-Actor-Name-Format": "utf-8-percent-v1"}
    with client_for(session) as client:
        response = _patch(client, target.id, reaction="나중에", headers=headers)
    assert response.status_code == 200
    assert (response.json()["reacted_by"], response.json()["reaction"]) == ("김담당", "나중에")


def test_slack_path_uses_the_same_service_with_via_slack(session, plans) -> None:
    rows = seed(session, plans)
    target = _item(session, order_plan_id=rows["plan"].id)
    request_id = uuid4()

    result = react_to_item(session, item_id=target.id, reaction="무시", expected_revision=0,
                           request_id=request_id, actor="slack-user", via="slack")
    session.commit()
    replay = react_to_item(session, item_id=target.id, reaction="무시", expected_revision=0,
                           request_id=request_id, actor="slack-user", via="slack")

    assert (result.response.reacted_via, result.response.reaction, result.replayed) == ("slack", "무시", False)
    assert replay.replayed and replay.snapshot == result.snapshot
    # 같은 request_id라도 via가 다르면 다른 요청이다(hash에 via가 든다).
    with pytest.raises(BriefingError) as raised:
        react_to_item(session, item_id=target.id, reaction="무시", expected_revision=0,
                      request_id=request_id, actor="slack-user", via="screen")
    assert raised.value.code == "idempotency_conflict"
    with pytest.raises(BriefingError) as invalid:
        react_to_item(session, item_id=target.id, reaction="무시", expected_revision=1,
                      request_id=uuid4(), actor="slack-user", via="email")
    assert invalid.value.code == "invalid_request"


# --- T7 workload ----------------------------------------------------------------


def _pending(client):
    items = client.get("/api/workload").json()["items"]
    assert [item["key"] for item in items][-2:] == ["company_attention", "briefing_pending"]
    [item] = [item for item in items if item["key"] == "briefing_pending"]
    return item["count"], item["unavailable_reason"]


def test_t7_briefing_pending_counts_waiting_recommendations_of_the_latest_briefing(session, plans) -> None:
    with client_for(session) as client:
        assert _pending(client) == (None, "provider_absent")
    rows = seed(session, plans)
    target = _item(session, notice_id=rows["pre_spec"].id)
    with client_for(session) as client:
        # 추적 변화 행은 반응이 없으므로 세지 않는다.
        assert _pending(client) == (3, None)
        assert _patch(client, target.id).status_code == 200
        assert _pending(client) == (2, None)
    later = build_briefing(session, NEXT_BRIEFING_DATE, now=NOW + timedelta(days=3))
    session.commit()
    with client_for(session) as client:
        # 가장 최근 브리핑(추천 0건)만 센다. 앞 브리핑의 대기 2건은 들지 않는다.
        assert later.item_count == 0
        assert _pending(client) == (0, None)


def test_policy_file_sha_is_pinned_on_the_row(session, plans) -> None:
    seed(session, plans)
    assert session.scalar(select(Briefing.policy_sha256)) == load_briefing_policy().sha256
    assert isinstance(session.scalar(select(Briefing.graph_version_id)), UUID)
