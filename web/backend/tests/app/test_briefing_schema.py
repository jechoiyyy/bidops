"""RL-01 브리핑 테이블의 CHECK·부분 UNIQUE가 models(SQLite `init_db`)와 migration
(PostgreSQL `0038_briefing`) 양쪽에서 같은 행을 거부한다.

`alembic check`는 CHECK 식과 부분 인덱스 조건을 비교하지 않으므로, drift 0만으로는
"같은 선언"이 증명되지 않는다. 여기서 위반 행을 실제로 넣어 본다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import ALEMBIC_HEAD, init_db
from app.lifecycle.models import (
    Briefing,
    BriefingItem,
    BriefingReactionEvent,
    Notice,
    Opportunity,
    OrderPlan,
)
from tests.postgres import migrated_engine, requires_postgres, run_alembic, temporary_database

NOW = datetime(2026, 10, 16, 22, 30, tzinfo=UTC)


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def engine(request):
    if request.param == "postgres":
        with migrated_engine() as bind:
            yield bind
        return
    bind = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(bind)
    try:
        yield bind
    finally:
        bind.dispose()


@pytest.fixture
def world(engine):
    with Session(engine) as session:
        notice = Notice(notice_key="briefing-schema-notice", source_type="pre_spec", title="사업")
        other_notice = Notice(notice_key="briefing-schema-notice-2", source_type="bid_notice", title="사업2")
        plan = OrderPlan(order_plan_unty_no="briefing-schema-plan", title="연차")
        opportunity = Opportunity(first_registered_stage="pre_spec")
        session.add_all([notice, other_notice, plan, opportunity])
        session.flush()
        briefing = Briefing(
            briefing_date=date(2026, 10, 17), status="generated", generated_at=NOW,
            policy_sha256="a" * 64, graph_version_id=uuid4(), item_count=1,
            excluded_counts={}, warnings=[], created_by="build-briefing",
        )
        session.add(briefing)
        session.commit()
        yield session, briefing.id, notice.id, other_notice.id, plan.id, opportunity.id


def _item(briefing_id, opportunity_id, **overrides) -> BriefingItem:
    values = dict(
        briefing_id=briefing_id, kind="recommendation", rank=1, stage="pre_spec",
        notice_id=None, order_plan_id=None, opportunity_id=opportunity_id,
        reasons=[], blocking=[], change_fields=[], reaction="대기",
    )
    values.update(overrides)
    return BriefingItem(**values)


def _rejected(session: Session, *rows) -> None:
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add_all(rows)
            session.flush()
    session.expunge_all()


def test_valid_rows_are_accepted_and_nullable_json_stays_sql_null(world) -> None:
    session, briefing_id, notice_id, other_id, plan_id, opportunity_id = world
    recommendation = _item(briefing_id, opportunity_id, notice_id=notice_id)
    tracked = _item(
        briefing_id, opportunity_id, kind="tracked_change", rank=None, reaction=None,
        stage="bid_notice", notice_id=other_id, change_fields=["deadline_at"],
    )
    plan_item = _item(
        briefing_id, opportunity_id, rank=2, stage="order_plan", order_plan_id=plan_id,
        deadline_kind="planned_month", planned_month="2027-01",
    )
    session.add_all([recommendation, tracked, plan_item])
    session.flush()
    session.add(BriefingReactionEvent(
        item_id=recommendation.id, revision=1, previous="대기", new="채택",
        actor="담당자", via="screen", request_id=uuid4(),
    ))
    session.commit()
    briefing = session.get(Briefing, briefing_id)
    assert briefing.slack_message_ts is None and briefing.tracked_change_message_ts is None
    assert recommendation.revision == 0 and tracked.score is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"notice_id": None, "order_plan_id": None},             # 대상 없음
        {"order_plan_id": "PLAN"},                               # 대상 둘
        {"kind": "summary"},
        {"stage": "notice"},
        {"deadline_kind": "close"},
        {"reaction": "보류"},
        {"reacted_via": "email", "reacted_by": "a", "reacted_at": NOW},
        {"rank": None},                                          # 추천인데 순위 없음
        {"reaction": None},                                      # 추천인데 반응 없음
        {"kind": "tracked_change", "rank": None},                # 추적 변화인데 반응 있음
        {"kind": "tracked_change", "reaction": None},            # 추적 변화인데 순위 있음
        {"reacted_by": "담당자"},                                 # 반응 기록 셋 중 하나만
        {"reacted_by": "담당자", "reacted_at": NOW},              # 셋 중 둘만
    ],
)
def test_each_check_rejects_its_row(world, overrides) -> None:
    session, briefing_id, notice_id, _other, plan_id, opportunity_id = world
    values = {"notice_id": notice_id, **overrides}
    if values.get("order_plan_id") == "PLAN":
        values["order_plan_id"] = plan_id
    _rejected(session, _item(briefing_id, opportunity_id, **values))


def test_briefing_status_and_date_are_constrained(world) -> None:
    session, *_ = world
    common = dict(
        generated_at=NOW, policy_sha256="b" * 64, graph_version_id=uuid4(), item_count=0,
        excluded_counts={}, warnings=[], created_by="build-briefing",
    )
    _rejected(session, Briefing(briefing_date=date(2026, 10, 20), status="failed", **common))
    _rejected(session, Briefing(briefing_date=date(2026, 10, 17), status="empty", **common))


def test_partial_unique_indexes_hold_per_briefing(world) -> None:
    session, briefing_id, notice_id, other_id, plan_id, opportunity_id = world
    session.add(_item(briefing_id, opportunity_id, notice_id=notice_id, rank=1))
    session.add(_item(briefing_id, opportunity_id, stage="order_plan", order_plan_id=plan_id, rank=2))
    session.commit()
    # 같은 공고 두 행(추천과 추적 변화라도), 같은 발주계획 두 행, 같은 순위 두 행은 거부된다.
    _rejected(session, _item(
        briefing_id, opportunity_id, kind="tracked_change", rank=None, reaction=None,
        notice_id=notice_id,
    ))
    _rejected(session, _item(briefing_id, opportunity_id, stage="order_plan", order_plan_id=plan_id, rank=3))
    _rejected(session, _item(briefing_id, opportunity_id, stage="bid_notice", notice_id=other_id, rank=1))
    # 순위가 없는 추적 변화 행은 여러 개여도 된다(rank 부분 UNIQUE 밖).
    session.add(_item(
        briefing_id, opportunity_id, kind="tracked_change", rank=None, reaction=None,
        stage="bid_notice", notice_id=other_id,
    ))
    session.commit()


def test_reaction_event_revision_is_unique_and_events_are_append_only(world) -> None:
    session, briefing_id, notice_id, _other, _plan, opportunity_id = world
    item = _item(briefing_id, opportunity_id, notice_id=notice_id)
    session.add(item)
    session.flush()
    event = BriefingReactionEvent(
        item_id=item.id, revision=1, previous="대기", new="채택",
        actor="담당자", via="slack", request_id=uuid4(),
    )
    session.add(event)
    session.commit()
    event_id = event.id
    _rejected(session, BriefingReactionEvent(
        item_id=item.id, revision=1, previous="채택", new="대기",
        actor="담당자", via="screen", request_id=uuid4(),
    ))
    stored = session.get(BriefingReactionEvent, event_id)
    stored.new = "무시"
    with pytest.raises(ValueError):
        session.flush()
    session.rollback()


@requires_postgres
def test_0038_downgrades_when_empty_refuses_with_history_and_upgrades_again() -> None:
    from sqlalchemy import text

    with temporary_database() as database_url:
        down = run_alembic(database_url, "downgrade", "0037_requirement_card_columns")
        assert down.returncode == 0, down.stderr
        up = run_alembic(database_url, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        engine = create_engine(database_url, future=True)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO bidops.briefing (id, briefing_date, status, generated_at, "
                    "policy_sha256, graph_version_id, item_count, excluded_counts, warnings, created_by) "
                    "VALUES (:id, '2026-10-17', 'empty', now(), :sha, :graph, 0, '{}', '[]', 'test')"
                ), {"id": str(uuid4()), "sha": "c" * 64, "graph": str(uuid4())})
            refused = run_alembic(database_url, "downgrade", "0037_requirement_card_columns")
            assert refused.returncode != 0
            assert "refuses to discard briefing history" in refused.stderr
            with engine.connect() as connection:
                # 한 번의 downgrade 실행은 한 transaction이다. 0038이 거부하면 그 위
                # revision(0039_opportunity_note·0040_card_analysis)의 downgrade도 함께 되돌아가 head에 남는다.
                assert connection.scalar(text("SELECT version_num FROM bidops.alembic_version")) == ALEMBIC_HEAD
        finally:
            engine.dispose()
