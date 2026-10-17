"""평일 브리핑 REST·반응의 PostgreSQL 변형 (RL-01 spec T6, strict dict).

migration head(0038)와 `scripts/runtime-privileges.sql`을 적용한 일회용 PostgreSQL에서
runtime `app` 역할로 생성·조회·반응을 실제 경로로 부른다. 반응은 추적 상태
(`Opportunity.tracking_*`·`CompanyOpportunityTracking`)를 바꾸지 않아야 하고, CHECK·부분
UNIQUE를 어기는 행은 DB가 거부해야 한다.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4, uuid5

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.lifecycle.models import (
    Briefing,
    BriefingItem,
    BriefingReactionEvent,
    Company,
    CompanyOpportunityTracking,
    Opportunity,
)
from app.lifecycle.services import briefing as briefing_service
from app.lifecycle.services.briefing import build_briefing
from app.main import create_app
from tests.app.test_runtime_database_privileges import _ensure_roles
from tests.lifecycle.briefing_fixtures import BRIEFING_DATE, NOW, FakeOrderPlans, World, register_providers
from tests.postgres import migrated_engine, requires_postgres

pytestmark = requires_postgres

ROOT = Path(__file__).resolve().parents[4]
RUNTIME_POLICY = (ROOT / "scripts/runtime-privileges.sql").read_text(encoding="utf-8")
REACTED_AT = datetime(2026, 10, 15, 23, 5, 30, 123456, tzinfo=UTC)


@pytest.fixture(scope="module")
def pg_engine():
    with migrated_engine() as engine:
        _ensure_roles()
        with engine.connect() as connection:
            cursor = connection.connection.driver_connection.cursor()
            try:
                cursor.execute(RUNTIME_POLICY, prepare=False)
            finally:
                cursor.close()
        yield engine


@pytest.fixture
def session(pg_engine):
    with pg_engine.connect() as connection:
        outer = connection.begin()
        # router가 오류에서 rollback해도 바깥 transaction(과 `SET LOCAL ROLE`)이 살아 있게
        # session은 savepoint 안에서만 commit/rollback한다. 검사가 끝나면 바깥을 되돌린다.
        try:
            with Session(connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as value:
                yield value
        finally:
            outer.rollback()


@contextmanager
def client_for(session):
    application = create_app(modules=("lifecycle",), mount_frontend=False)
    application.dependency_overrides[get_db] = lambda: session
    with TestClient(application) as client:
        yield client


def _iso(value: datetime) -> str:
    """pydantic JSON 직렬화와 같은 표기(UTC는 `Z`)."""

    text = value.astimezone(UTC).isoformat()
    return text.replace("+00:00", "Z")


@pytest.fixture
def seeded(session, empty_extensions, monkeypatch):
    plans = FakeOrderPlans()
    register_providers(empty_extensions, plans=plans)
    world = World(session)
    world.collection_run()
    pre_spec = world.notice("홈페이지 유지관리 용역", deadline_at=NOW + timedelta(days=3, hours=1),
                            estimated_price=480_000_000, agency="대구광역시")
    tracked_owner = world.opportunity(tracking_status="계속 추적")
    tracked = world.notice("추적 중 통합 시스템", owner=tracked_owner, observed_at=NOW - timedelta(days=10),
                           deadline_at=NOW + timedelta(days=12))
    world.observe(tracked, NOW - timedelta(hours=1), ["deadline_at", "title"])
    recommended_owner = pre_spec.opportunity_links[0].opportunity
    company = Company(slug="briefing-pg", name="합성 회사", is_fictional=False)
    session.add(company)
    session.flush()
    session.add(CompanyOpportunityTracking(
        company_id=company.id, opportunity_id=recommended_owner.id, tracking_status="보류",
        reason="합성 보류", selected_by="추적 담당자", selected_at=NOW - timedelta(days=2), revision=1,
    ))
    session.flush()
    # 이후는 runtime 역할로 한다(생성·조회·반응 모두 web 경로의 권한).
    session.connection().exec_driver_sql("SET LOCAL ROLE app")
    result = build_briefing(session, BRIEFING_DATE, now=NOW)
    session.commit()
    assert (result.status, result.item_count, result.tracked_change_count) == ("generated", 1, 1)
    monkeypatch.setattr(briefing_service, "utc_now", lambda: REACTED_AT)
    return {
        "pre_spec": pre_spec, "tracked": tracked, "tracked_owner": tracked_owner,
        "recommended_owner": recommended_owner, "briefing_id": result.briefing_id,
    }


def _item(session, notice_id) -> BriefingItem:
    return session.scalars(select(BriefingItem).where(BriefingItem.notice_id == notice_id)).one()


def _tracking(session):
    opportunities = [
        (row.id, row.tracking_status, row.tracking_reason, row.tracking_selected_by, row.tracking_selected_at,
         row.recheck_signal_at)
        for row in session.scalars(select(Opportunity).order_by(Opportunity.id))
    ]
    company = [
        (row.company_id, row.opportunity_id, row.tracking_status, row.reason, row.selected_by, row.selected_at,
         row.revision)
        for row in session.scalars(select(CompanyOpportunityTracking))
    ]
    return opportunities, company


def test_t6_view_and_reaction_strict_dicts_replay_conflicts_and_tracking_unchanged(session, seeded) -> None:
    recommendation = _item(session, seeded["pre_spec"].id)
    change = _item(session, seeded["tracked"].id)
    briefing = session.get(Briefing, seeded["briefing_id"])
    before = _tracking(session)
    deadline = seeded["pre_spec"].deadline_at
    expected_item = {
        "item_id": str(recommendation.id),
        "kind": "recommendation",
        "rank": 1,
        "stage": "pre_spec",
        "notice_id": seeded["pre_spec"].id,
        "order_plan_id": None,
        "opportunity_id": seeded["recommended_owner"].id,
        "title": "홈페이지 유지관리 용역",
        "agency": "대구광역시",
        "amount_krw": 480_000_000,
        "deadline_at": _iso(deadline),
        "deadline_kind": "opinion_close",
        "planned_month": None,
        "verdict_display": "분석 대기",
        "reasons": [{"kind": "keyword", "text": "유지관리", "count": None}],
        "blocking": [{"kind": "deadline_short", "text": "마감 3일"}],
        "change_fields": [],
        "reaction": "대기",
        "reacted_by": None,
        "reacted_at": None,
        "reacted_via": None,
        "revision": 0,
        "record_path": f"/opportunities/{seeded['recommended_owner'].id}",
    }
    expected_change = {
        **expected_item,
        "item_id": str(change.id),
        "kind": "tracked_change",
        "rank": None,
        "notice_id": seeded["tracked"].id,
        "opportunity_id": seeded["tracked_owner"].id,
        "title": "추적 중 통합 시스템",
        "agency": "합성구청",
        "amount_krw": None,
        "deadline_at": _iso(seeded["tracked"].deadline_at),
        "verdict_display": "재검토 중",
        "reasons": [],
        "blocking": [],
        "change_fields": ["deadline_at", "title"],
        "reaction": None,
        "record_path": f"/opportunities/{seeded['tracked_owner'].id}",
    }
    request_id = uuid4()
    body = {"reaction": "채택", "expected_revision": 0, "request_id": str(request_id)}
    headers = {"X-BidOps-Actor-Name": "kim"}
    with client_for(session) as client:
        view = client.get("/api/briefings/2026-10-16")
        tracked_patch = client.patch(f"/api/briefings/items/{change.id}/reaction", json=body, headers=headers)
        first = client.patch(f"/api/briefings/items/{recommendation.id}/reaction", json=body, headers=headers)
        replay = client.patch(f"/api/briefings/items/{recommendation.id}/reaction", json=body, headers=headers)
        conflict = client.patch(
            f"/api/briefings/items/{recommendation.id}/reaction",
            json={**body, "reaction": "무시"}, headers=headers,
        )
        # 다른 사람이 같은 화면 상태(revision 0)로 늦게 누른다.
        stale = client.patch(
            f"/api/briefings/items/{recommendation.id}/reaction",
            json={"reaction": "무시", "expected_revision": 0, "request_id": str(uuid4())},
            headers={"X-BidOps-Actor-Name": "park"},
        )
        undo = client.patch(
            f"/api/briefings/items/{recommendation.id}/reaction",
            json={"reaction": "대기", "expected_revision": 1, "request_id": str(uuid4())}, headers=headers,
        )
        workload = client.get("/api/workload").json()

    assert view.status_code == 200
    assert view.json() == {
        "schema_version": "bidops.briefing.v1",
        "briefing_date": "2026-10-16",
        "status": "generated",
        "generated_at": _iso(briefing.generated_at),
        "item_count": 1,
        "slack_sent_at": None,
        "items": [expected_item],
        "tracked_changes": [expected_change],
        "collection_note": None,
    }
    assert tracked_patch.status_code == 409
    assert tracked_patch.json() == {
        "error": {
            "code": "reaction_not_allowed",
            "message": "추적 중 사업 변화 항목에는 반응을 남길 수 없습니다",
            "details": None,
        },
        "request_id": str(request_id),
    }
    accepted = {
        **expected_item, "reaction": "채택", "reacted_by": "kim", "reacted_at": _iso(REACTED_AT),
        "reacted_via": "screen", "revision": 1,
    }
    assert first.status_code == 200 and first.json() == accepted
    assert replay.status_code == 200 and replay.json() == accepted
    assert conflict.status_code == 409
    assert conflict.json() == {
        "error": {
            "code": "idempotency_conflict",
            "message": "같은 request_id가 다른 요청에 사용되었습니다",
            "details": None,
        },
        "request_id": str(request_id),
    }
    assert stale.status_code == 409
    assert stale.json()["error"] == {
        "code": "version_conflict", "message": "브리핑 항목이 변경되었습니다", "details": {"current_revision": 1},
    }
    assert undo.status_code == 200
    assert undo.json() == {**accepted, "reaction": "대기", "revision": 2}
    pending = [item for item in workload["items"] if item["key"] == "briefing_pending"]
    assert pending == [{"key": "briefing_pending", "count": 1, "unavailable_reason": None}]

    events = session.scalars(
        select(BriefingReactionEvent).where(BriefingReactionEvent.item_id == recommendation.id)
        .order_by(BriefingReactionEvent.revision)
    ).all()
    assert [(event.revision, event.previous, event.new, event.actor, event.via, event.created_at) for event in events] == [
        (1, "대기", "채택", "kim", "screen", REACTED_AT),
        (2, "채택", "대기", "kim", "screen", REACTED_AT),
    ]
    assert events[0].request_id == request_id
    assert session.scalar(select(func.count(BriefingReactionEvent.id)).where(
        BriefingReactionEvent.item_id == change.id)) == 0
    # 반응은 추적 상태를 바꾸지 않는다(사업기회·회사별 추적 모두).
    session.expire_all()
    assert _tracking(session) == before


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"kind": "tracked_change", "rank": None, "reaction": "대기"}, id="tracked-with-reaction"),
        pytest.param({"rank": None}, id="recommendation-without-rank"),
        pytest.param({"reaction": "좋아요"}, id="reaction-enum"),
        pytest.param({"reacted_by": "kim"}, id="reacted-triple"),
        pytest.param({"stage": "contract"}, id="stage-enum"),
        pytest.param({"deadline_kind": "someday"}, id="deadline-kind-enum"),
        pytest.param({"order_plan_id": "same-notice-and-plan"}, id="two-targets"),
        pytest.param({"rank": 1}, id="duplicate-rank"),
        pytest.param({"notice_id": "existing"}, id="duplicate-notice"),
    ],
)
def test_t6_database_rejects_check_and_partial_unique_violations(session, seeded, overrides) -> None:
    existing = _item(session, seeded["pre_spec"].id)
    world = World(session)
    session.connection().exec_driver_sql("RESET ROLE")
    other = world.notice("다른 합성 공고", observed_at=None, owner=False)
    plan = world.plan("다른 합성 발주계획", owner=False)
    session.connection().exec_driver_sql("SET LOCAL ROLE app")
    values = dict(
        briefing_id=seeded["briefing_id"], kind="recommendation", rank=5, stage="pre_spec",
        notice_id=other.id, order_plan_id=None, opportunity_id=existing.opportunity_id,
        reasons=[], blocking=[], change_fields=[], reaction="대기",
    )
    values.update(overrides)
    if values["order_plan_id"] == "same-notice-and-plan":
        values["order_plan_id"] = plan.id
    if values["notice_id"] == "existing":
        values["notice_id"] = existing.notice_id
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(BriefingItem(**values))
            session.flush()


def test_slack_worker_saves_a_reaction_with_the_worker_role_only(session, seeded) -> None:
    """slack-worker(worker 자격)가 반응 열·이벤트·멱등 영수증만으로 저장하고 메시지를 다시 그린다.

    worker 역할에는 `briefing_item`의 반응 열 UPDATE와 이벤트 INSERT만 있다(runtime-privileges.sql).
    Slack은 부르지 않는다 — 갱신 요청은 기록용 전송기가 받는다.
    """

    from app.lifecycle.slack_worker import SLACK_REACTION_NS, SlackReactionHandler

    sent_ts = "1760572800.000001"
    briefing = session.get(Briefing, seeded["briefing_id"])
    briefing.slack_message_ts = [sent_ts]  # web(app 역할)이 전송 뒤 남기는 값
    session.commit()
    item_id = _item(session, seeded["pre_spec"].id).id
    session.connection().exec_driver_sql("SET LOCAL ROLE worker")
    session.expire_all()

    class RecordingSender:
        channel_id = "C0FIXTURE"

        def __init__(self) -> None:
            self.updates: list[dict] = []

        def update_message(self, **kwargs) -> None:
            self.updates.append(kwargs)

    @contextmanager
    def same_session():
        yield session

    sender = RecordingSender()
    handler = SlackReactionHandler(sender, same_session, clock=lambda: REACTED_AT)
    trigger = "13345224609.738474920.pg-worker"
    payload = {
        "type": "block_actions",
        "user": {"id": "U0FIXTURE", "username": "kim", "name": "kim", "team_id": "T0FIXTURE"},
        "container": {"type": "message", "message_ts": sent_ts, "channel_id": "C0FIXTURE", "is_ephemeral": False},
        "trigger_id": trigger,
        "channel": {"id": "C0FIXTURE", "name": "bidops-briefing"},
        "message": {"type": "message", "ts": sent_ts, "blocks": []},
        "actions": [{"action_id": "briefing_react", "type": "button", "value": f"{item_id}:채택",
                     "block_id": "b1", "action_ts": "1760573000.1"}],
    }

    result = handler.handle_payload(payload)

    assert (result.status, result.updated) == ("saved", True)
    (update,) = sender.updates
    assert (update["channel"], update["ts"]) == ("C0FIXTURE", sent_ts)
    contexts = [element["text"] for block in update["blocks"] if block["type"] == "context"
                for element in block["elements"]]
    assert "✓ kim이 볼게요" in contexts
    # 같은 클릭의 재전달은 다시 저장·갱신하지 않는다(worker 역할 그대로).
    assert handler.handle_payload(payload).status == "duplicate"
    assert len(sender.updates) == 1

    session.connection().exec_driver_sql("RESET ROLE")
    item = session.get(BriefingItem, item_id, populate_existing=True)
    assert (item.reaction, item.reacted_by, item.reacted_via, item.revision) == ("채택", "kim", "slack", 1)
    events = session.scalars(select(BriefingReactionEvent).where(BriefingReactionEvent.item_id == item_id)).all()
    assert [(event.new, event.via, event.request_id) for event in events] == [
        ("채택", "slack", uuid5(SLACK_REACTION_NS, trigger)),
    ]
