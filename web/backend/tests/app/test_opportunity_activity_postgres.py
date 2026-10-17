"""사업기회 활동 피드 REST의 PostgreSQL 변형 (RL-02 spec "활동 피드", strict dict).

migration head와 `scripts/runtime-privileges.sql`을 적용한 일회용 PostgreSQL에서 소유자 권한으로
원본(연결·관측·감사·반응·노트)을 심고, runtime `app` 역할로 `GET /api/opportunities/{id}/activity`를
실제 경로로 부른다. 응답 전체를 strict dict로 대조해 마이크로초·UTC `Z`·커서 모양과 `app` 역할의
읽기 권한(감사·관측·반응·노트)을 함께 고정한다.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.models import AuditEvent
from app.lifecycle.models import (
    Briefing,
    BriefingItem,
    BriefingReactionEvent,
    Notice,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OpportunityNote,
    OrderPlan,
    Run,
)
from app.lifecycle.routers import opportunities as opportunities_router
from app.lifecycle.services.opportunity_tracking import set_tracking_status
from app.main import create_app
from tests.app.test_runtime_database_privileges import _ensure_roles
from tests.postgres import migrated_engine, requires_postgres

pytestmark = requires_postgres

ROOT = Path(__file__).resolve().parents[4]
RUNTIME_POLICY = (ROOT / "scripts/runtime-privileges.sql").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 17, 3, 0, tzinfo=UTC)
T0 = datetime(2026, 10, 1, 0, 0, 0, 123456, tzinfo=UTC)


def at(days: int, minutes: int = 0) -> datetime:
    return T0 + timedelta(days=days, minutes=minutes)


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
        try:
            with Session(connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as value:
                yield value
        finally:
            outer.rollback()


@pytest.fixture
def seeded(session, monkeypatch):
    """소유자 권한으로 원본을 심은 뒤 runtime `app` 역할로 바꾼다."""

    monkeypatch.setattr(opportunities_router, "_request_now", lambda: NOW)
    opportunity = Opportunity(first_registered_stage="order_plan", created_at=at(0))
    plan = OrderPlan(order_plan_unty_no="R26BK0101", title="홈페이지 고도화 발주계획", agency_name="대구테크노파크")
    pre = Notice(notice_key="pre:R26BD0101", source_type="pre_spec", title="홈페이지 고도화 사전규격")
    bid = Notice(
        notice_key="bid:R26BK0101-000",
        source_type="bid_notice",
        title="홈페이지 고도화 용역",
        url="https://www.g2b.go.kr/bid/0101",
        deadline_at=NOW + timedelta(days=3),
        lifecycle_json={"opening_at": "2026-10-20T11:00:00+09:00"},
    )
    session.add_all([opportunity, plan, pre, bid])
    session.flush()
    plan_link = OpportunityLink(opportunity=opportunity, order_plan=plan, stage="order_plan", link_type="official",
                                status="확정", evidence_external_no="R26BK0101", created_at=at(1))
    pre_link = OpportunityLink(opportunity=opportunity, notice=pre, stage="notice", link_type="official",
                               status="확정", evidence_external_no="R26BD0101", created_at=at(2))
    bid_link = OpportunityLink(opportunity=opportunity, notice=bid, stage="notice", link_type="official",
                               status="확정", evidence_external_no="R26BK0101-000", created_at=at(4))
    session.add_all([plan_link, pre_link, bid_link])
    session.flush()
    first_run = Run(id="lifecycle-20261002-notices--2026-10-02T21:00:00Z", generated_at=at(2))
    second_run = Run(id="lifecycle-20261010-notices--2026-10-10T21:00:00Z", generated_at=at(10))
    session.add_all([first_run, second_run])
    session.flush()
    session.add_all([
        NoticeObservation(notice_id=pre.id, run_id=first_run.id, observed_at=at(2), changed_fields_json=["deadline_at"]),
        NoticeObservation(notice_id=pre.id, run_id=second_run.id, observed_at=at(10),
                          changed_fields_json=["budget", "deadline_at"]),
    ])
    set_tracking_status(session, opportunity, status="계속 추적", reason="주력 분야", selected_by="김철수",
                        selected_at=at(6))
    briefing = Briefing(briefing_date=date(2026, 10, 13), status="generated", generated_at=at(12),
                        policy_sha256="a" * 64, graph_version_id=UUID("11111111-2222-3333-4444-555555555555"),
                        item_count=1, excluded_counts={}, warnings=[], created_by="system")
    session.add(briefing)
    session.flush()
    item = BriefingItem(id=UUID("22222222-0000-4000-8000-000000000001"), briefing_id=briefing.id,
                        kind="recommendation", rank=1, stage="bid_notice", notice_id=bid.id,
                        opportunity_id=opportunity.id, reaction="채택", reacted_by="최담당",
                        reacted_at=at(12, 30), reacted_via="screen", revision=1)
    session.add(item)
    session.flush()
    reaction = BriefingReactionEvent(id=UUID("33333333-0000-4000-8000-000000000001"), item_id=item.id, revision=1,
                                     previous="대기", new="채택", actor="최담당", via="screen",
                                     request_id=UUID("44444444-0000-4000-8000-000000000001"),
                                     created_at=at(12, 30))
    action = OpportunityNote(id=UUID("55555555-0000-4000-8000-000000000001"), opportunity_id=opportunity.id,
                             kind="action", body="제안 일정 확인", actor="kim", owner="박담당",
                             created_at=at(13), done_at=at(14), done_by="박담당")
    session.add_all([reaction, action])
    session.flush()
    tracking_audit = session.scalars(
        select(AuditEvent.id).where(AuditEvent.action == "opportunity.tracking_status.changed")
    ).one()
    session.commit()
    session.connection().exec_driver_sql("SET LOCAL ROLE app")
    session.commit()
    return {
        "opportunity": opportunity, "plan": plan, "pre": pre, "plan_link": plan_link, "pre_link": pre_link,
        "bid_link": bid_link, "tracking_audit": tracking_audit,
    }


@contextmanager
def client_for(session):
    application = create_app(modules=("lifecycle",), mount_frontend=False)
    application.dependency_overrides[get_db] = lambda: session
    with TestClient(application) as client:
        yield client


def test_activity_feed_strict_dict_under_the_runtime_role(session, seeded) -> None:
    opportunity_id = seeded["opportunity"].id
    path = f"/api/opportunities/{opportunity_id}/activity"
    correction_id = session.scalars(
        select(NoticeObservation.id).where(NoticeObservation.observed_at == at(10))
    ).one()
    with client_for(session) as client:
        full = client.get(path)
        first = client.get(path, params={"limit": 3})
        second = client.get(path, params={"limit": 3, "before": first.json()["next_before"]})

    assert full.status_code == 200, full.text
    items = [
        {"item_id": "action_done:55555555-0000-4000-8000-000000000001", "kind": "action_done",
         "at": "2026-10-15T00:00:00.123456Z", "actor": "박담당", "title": "박담당이 완료: 제안 일정 확인",
         "detail": None, "link": None, "status_pill": None},
        {"item_id": "action_added:55555555-0000-4000-8000-000000000001", "kind": "action_added",
         "at": "2026-10-14T00:00:00.123456Z", "actor": "kim", "title": "다음 행동: 제안 일정 확인",
         "detail": "담당 박담당", "link": None, "status_pill": None},
        {"item_id": "briefing_reacted:33333333-0000-4000-8000-000000000001", "kind": "briefing_reacted",
         "at": "2026-10-13T00:30:00.123456Z", "actor": "최담당", "title": "최담당이 채택", "detail": None,
         "link": {"label": "브리핑 보기",
                  "path": "/briefing?date=2026-10-13&selected=22222222-0000-4000-8000-000000000001"},
         "status_pill": "채택"},
        {"item_id": f"notice_corrected:{correction_id}", "kind": "notice_corrected",
         "at": "2026-10-11T00:00:00.123456Z", "actor": None, "title": "정정 · 마감, 예산", "detail": None,
         "link": {"label": "변경 이력", "path": f"/pre-specs/{seeded['pre'].id}#ps-record-history"},
         "status_pill": None},
        {"item_id": f"tracking_decided:{seeded['tracking_audit']}", "kind": "tracking_decided",
         "at": "2026-10-07T00:00:00.123456Z", "actor": "김철수", "title": "김철수가 계속 추적으로 결정",
         "detail": None, "link": None, "status_pill": None},
        {"item_id": f"bid_posted:{seeded['bid_link'].id}", "kind": "bid_posted",
         "at": "2026-10-05T00:00:00.123456Z", "actor": None, "title": "입찰공고 게시", "detail": None,
         "link": {"label": "공고 원문", "path": "https://www.g2b.go.kr/bid/0101"}, "status_pill": None},
        {"item_id": f"pre_spec_opened:{seeded['pre_link'].id}", "kind": "pre_spec_opened",
         "at": "2026-10-03T00:00:00.123456Z", "actor": None, "title": "사전규격 공개", "detail": None,
         "link": {"label": "사전규격 보기", "path": f"/pre-specs/{seeded['pre'].id}"}, "status_pill": None},
        {"item_id": f"order_plan_found:{seeded['plan_link'].id}", "kind": "order_plan_found",
         "at": "2026-10-02T00:00:00.123456Z", "actor": None, "title": "발주계획 발견 · 대구테크노파크",
         "detail": None, "link": {"label": "발주계획 보기", "path": f"/order-plans/{seeded['plan'].id}"},
         "status_pill": None},
    ]
    assert full.json() == {
        "schema_version": "bidops.opportunity-activity.v1",
        "opportunity_id": opportunity_id,
        "merged_into_opportunity_id": None,
        "title": "홈페이지 고도화 용역",
        "stages": [
            {"key": "order_plan", "state": "done", "at": "2026-10-02T00:00:00.123456Z",
             "link_id": seeded["plan_link"].id},
            {"key": "pre_spec", "state": "done", "at": "2026-10-03T00:00:00.123456Z",
             "link_id": seeded["pre_link"].id},
            {"key": "bid_notice", "state": "current", "at": "2026-10-05T00:00:00.123456Z",
             "link_id": seeded["bid_link"].id},
            {"key": "deadline", "state": "upcoming_deadline", "at": "2026-10-20T03:00:00Z",
             "link_id": seeded["bid_link"].id},
            {"key": "opening", "state": "upcoming_deadline", "at": "2026-10-20T02:00:00Z",
             "link_id": seeded["bid_link"].id},
            {"key": "contract", "state": "unknown", "at": None, "link_id": None},
        ],
        "items": items,
        "next_before": None,
    }
    assert first.json()["items"] == items[:3]
    assert first.json()["next_before"] == f"2026-10-13T00:30:00.123456Z|{items[2]['item_id']}"
    assert second.json()["items"] == items[3:6]
    assert second.json()["next_before"] == f"2026-10-05T00:00:00.123456Z|{items[5]['item_id']}"
