"""평일 브리핑 생성 service (RL-01 spec T4·T5와 생성 경계).

lifecycle 단독 검사다. 회사 사실·발주계획 후보는 가짜 제공자로 넣고, 회차·공고·관측·
사업기회는 SQLite 격리 DB에 직접 심는다. 실제 deep_review·screening 제공자는
`tests/deep_review/test_company_facts_projection.py`·`tests/screening/
test_briefing_order_plan_candidates.py`와 CLI 진입점 검사가 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle.models import Briefing, BriefingItem
from app.lifecycle.services.briefing import (
    BriefingError,
    build_briefing,
    collection_run_patterns,
    get_briefing_view,
)
from app.lifecycle.services.briefing_policy import load_briefing_policy
from tests.lifecycle.briefing_fixtures import (
    BRIEFING_DATE,
    COLLECTION_RETRY_RUN,
    COLLECTION_RUN,
    GRAPH,
    NEXT_BRIEFING_DATE,
    NOW,
    SATURDAY,
    WINDOW_START,
    FakeOrderPlans,
    World,
    register_providers,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
    with Session(engine, expire_on_commit=False) as value:
        yield value
    engine.dispose()


@pytest.fixture
def world(session) -> World:
    return World(session)


@pytest.fixture
def plans(empty_extensions) -> FakeOrderPlans:
    provider = FakeOrderPlans()
    register_providers(empty_extensions, plans=provider)
    return provider


def _items(session, briefing_id):
    return session.scalars(
        select(BriefingItem).where(BriefingItem.briefing_id == briefing_id).order_by(BriefingItem.kind, BriefingItem.rank, BriefingItem.notice_id)
    ).all()


def _build(session, briefing_date=BRIEFING_DATE, *, now=NOW, **kwargs):
    result = build_briefing(session, briefing_date, now=now, **kwargs)
    session.commit()
    return result


# --- T4 ----------------------------------------------------------------------


def test_t4_first_run_window_starts_at_previous_kst_midnight_inclusive(session, world, plans) -> None:
    world.collection_run()
    on_boundary = world.notice("홈페이지 유지관리 용역", observed_at=WINDOW_START)
    just_before = world.notice("홈페이지 유지관리 2차", observed_at=WINDOW_START - timedelta(seconds=1))
    at_now = world.notice("데이터 플랫폼 구축", observed_at=NOW)
    after_now = world.notice("데이터 플랫폼 고도화", observed_at=NOW + timedelta(seconds=1))
    session.commit()

    result = _build(session)

    assert result.created is True and result.status == "generated"
    notice_ids = {item.notice_id for item in _items(session, result.briefing_id)}
    assert notice_ids == {on_boundary.id, at_now.id}
    assert just_before.id not in notice_ids and after_now.id not in notice_ids
    # 발주계획 확장점은 `> since`만 받으므로 포함 하한을 1µs 당겨 넘긴다.
    assert plans.calls == [(WINDOW_START - timedelta(microseconds=1), NOW)]


def test_t4_next_window_starts_after_the_previous_generated_at(session, world, plans) -> None:
    world.collection_run()
    world.notice("홈페이지 유지관리 용역", observed_at=NOW - timedelta(hours=1))
    session.commit()
    first = _build(session)
    later = NOW + timedelta(days=3)
    world.collection_run("lifecycle-20261018-notices--2026-10-18T21:00:00Z")
    at_previous = world.notice("데이터 플랫폼 구축", observed_at=NOW)
    after_previous = world.notice("데이터 플랫폼 2차", observed_at=NOW + timedelta(microseconds=1))
    session.commit()

    second = _build(session, NEXT_BRIEFING_DATE, now=later)

    assert first.created and second.created
    notice_ids = {item.notice_id for item in _items(session, second.briefing_id)}
    assert notice_ids == {after_previous.id}
    assert at_previous.id not in notice_ids
    assert plans.calls[-1] == (NOW, later)


def test_t4_same_day_rerun_is_idempotent_and_leaves_the_row_unchanged(session, world, plans) -> None:
    world.collection_run()
    world.notice("홈페이지 유지관리 용역")
    session.commit()
    first = _build(session)
    before = session.get(Briefing, first.briefing_id)
    snapshot = (before.status, before.generated_at, before.item_count, before.policy_sha256,
                before.excluded_counts, before.warnings)
    item_ids = [item.id for item in _items(session, first.briefing_id)]
    # 재실행 사이에 새 후보가 생겨도 같은 날 행은 다시 계산하지 않는다.
    world.notice("데이터 플랫폼 구축", observed_at=NOW + timedelta(minutes=5))
    session.commit()

    again = _build(session, now=NOW + timedelta(minutes=10))

    assert again.created is False
    assert again.briefing_id == first.briefing_id
    assert (again.status, again.item_count, again.excluded, again.warnings) == (
        first.status, first.item_count, first.excluded, first.warnings,
    )
    session.expire_all()
    after = session.get(Briefing, first.briefing_id)
    assert (after.status, after.generated_at, after.item_count, after.policy_sha256,
            after.excluded_counts, after.warnings) == snapshot
    assert [item.id for item in _items(session, first.briefing_id)] == item_ids
    assert session.scalar(select(func.count(Briefing.id))) == 1


def test_t4_already_itemized_notice_or_plan_is_never_recommended_again(session, world, plans) -> None:
    world.collection_run()
    repeated = world.notice("홈페이지 유지관리 용역", observed_at=NOW - timedelta(hours=1))
    plan = world.plan("스마트 관광 플랫폼 고도화 용역 3차")
    plans.ids = [plan.id]
    # 앞선 브리핑(예: 사람이 `--date`로 메운 날)이 같은 공고·발주계획을 이미 항목으로 가졌다.
    earlier = Briefing(
        briefing_date=BRIEFING_DATE - timedelta(days=1), status="generated",
        generated_at=WINDOW_START - timedelta(hours=1), policy_sha256="0" * 64, graph_version_id=GRAPH,
        item_count=2, excluded_counts={}, warnings=[], created_by="system:build-briefing",
    )
    session.add(earlier)
    session.flush()
    session.add_all([
        BriefingItem(briefing_id=earlier.id, kind="recommendation", rank=1, stage="pre_spec",
                     notice_id=repeated.id, opportunity_id=repeated.opportunity_links[0].opportunity_id,
                     reaction="대기"),
        BriefingItem(briefing_id=earlier.id, kind="recommendation", rank=2, stage="order_plan",
                     order_plan_id=plan.id, opportunity_id=plan.opportunity_links[0].opportunity_id,
                     reaction="대기"),
    ])
    fresh = world.notice("데이터 플랫폼 구축", observed_at=NOW - timedelta(hours=1))
    session.commit()

    result = _build(session)

    assert result.created
    items = _items(session, result.briefing_id)
    assert [(item.notice_id, item.order_plan_id) for item in items] == [(fresh.id, None)]


def test_t4_recommendation_and_tracked_change_on_one_notice_is_one_row(session, world, plans) -> None:
    world.collection_run()
    tracked_owner = world.opportunity(tracking_status="계속 추적")
    # 새로 관측된 공고(추천 후보)인데 같은 창 안 두 번째 관측에서 마감이 바뀌었다.
    both = world.notice("홈페이지 유지관리 용역", owner=tracked_owner, observed_at=NOW - timedelta(hours=5))
    world.observe(both, NOW - timedelta(hours=1), ["deadline_at"])
    # 추적 중인 옛 공고의 정정 → 추적 변화 행만.
    held_owner = world.opportunity(tracking_status="보류")
    old = world.notice("통합 정보시스템 운영", owner=held_owner, observed_at=NOW - timedelta(days=20),
                       deadline_at=NOW + timedelta(days=9), estimated_price=500_000_000)
    world.observe(old, NOW - timedelta(hours=2), ["title", "deadline_at", "agency"])
    world.observe(old, NOW - timedelta(hours=1), ["estimated_price"])
    # 미추적 사업의 변경은 묶음에 들지 않는다.
    untracked = world.notice("미추적 정보시스템", observed_at=NOW - timedelta(days=20))
    world.observe(untracked, NOW - timedelta(hours=1), ["deadline_at"])
    session.commit()

    result = _build(session)

    rows = _items(session, result.briefing_id)
    by_notice = {row.notice_id: row for row in rows}
    assert set(by_notice) == {both.id, old.id}
    assert len([row for row in rows if row.notice_id == both.id]) == 1
    merged = by_notice[both.id]
    assert (merged.kind, merged.rank, merged.reaction, merged.change_fields) == (
        "recommendation", 1, "대기", ["deadline_at"],
    )
    change = by_notice[old.id]
    assert (change.kind, change.rank, change.reaction, change.score) == ("tracked_change", None, None, None)
    # 바뀐 필드 합집합(규칙 파일 순서). 추적 필드 밖의 `agency`는 들지 않는다.
    assert change.change_fields == ["deadline_at", "title", "estimated_price"]
    assert (change.amount_krw, change.deadline_kind) == (500_000_000, "opinion_close")
    assert (result.item_count, result.tracked_change_count) == (1, 1)
    view = get_briefing_view(session, BRIEFING_DATE)
    assert [item.verdict_display for item in view.tracked_changes] == ["재검토 중"]
    assert [item.verdict_display for item in view.items] == ["분석 대기"]


# --- 모집단·저장 경계 ---------------------------------------------------------


def test_population_stage_rules_orphans_and_stored_operational_fields(session, world, plans) -> None:
    world.collection_run()
    pre_spec = world.notice("홈페이지 유지관리 용역", deadline_at=NOW + timedelta(days=3), estimated_price=2_500_000_000)
    world.notice("홈페이지 유지관리 SW 아님", sw="N")
    world.notice("홈페이지 유지관리 판단 없음", sw=None)
    world.notice("홈페이지 유지관리 검토 제외", review_exclusion_status="excluded")
    bid = world.notice("데이터 플랫폼 유지관리", source_type="bid_notice", sw=None, deadline_at=NOW + timedelta(days=20))
    world.notice("데이터 플랫폼 마감 지남", source_type="bid_notice", sw=None, deadline_at=NOW)
    world.notice("하드웨어 유지관리 장비", sw="Y")
    world.notice("홈페이지 유지관리 소유 없음", owner=None)
    repeat = world.plan("스마트 관광 플랫폼 고도화 용역 3차")
    not_repeat = world.plan("새 행정 시스템 구축", agency_name="다른 기관")
    orphan_plan = world.plan("스마트 관광 플랫폼 고도화 용역 4차", owner=False)
    plans.ids = [repeat.id, not_repeat.id, orphan_plan.id]
    session.commit()

    result = _build(session)

    rows = _items(session, result.briefing_id)
    assert {(row.stage, row.notice_id or row.order_plan_id) for row in rows} == {
        ("pre_spec", pre_spec.id), ("bid_notice", bid.id), ("order_plan", repeat.id),
    }
    assert result.excluded == {
        "hardware": 1, "election": 0, "design_only": 0, "staffing_only": 0, "region": 0, "amount_floor": 0,
    }
    assert result.warnings == ("orphan_candidate",)
    briefing = session.get(Briefing, result.briefing_id)
    assert briefing.policy_sha256 == load_briefing_policy().sha256
    assert briefing.graph_version_id == GRAPH
    assert briefing.excluded_counts == result.excluded
    assert briefing.warnings == ["orphan_candidate"]
    assert briefing.created_by == "system:build-briefing"
    assert briefing.generated_at == NOW
    by_id = {(row.stage, row.notice_id or row.order_plan_id): row for row in rows}
    first = by_id[("pre_spec", pre_spec.id)]
    assert (first.deadline_kind, first.amount_krw) == ("opinion_close", 2_500_000_000)
    assert first.blocking == [
        {"kind": "consortium_review", "text": "20억 원 이상 · 컨소시엄 검토"},
        {"kind": "deadline_short", "text": "마감 3일"},
    ]
    assert by_id[("bid_notice", bid.id)].deadline_kind == "bid_close"
    plan_row = by_id[("order_plan", repeat.id)]
    assert (plan_row.deadline_kind, plan_row.planned_month, plan_row.deadline_at) == ("planned_month", "2027-02", None)


def test_missing_order_plan_provider_is_a_warning_not_an_empty_success(session, world, empty_extensions) -> None:
    register_providers(empty_extensions, plans=None)
    world.collection_run()
    world.notice("홈페이지 유지관리 용역")
    session.commit()

    result = _build(session)

    assert result.created and result.warnings == ("order_plan_provider_absent",)


def test_weekend_creates_nothing(session, world, plans) -> None:
    world.notice("홈페이지 유지관리 용역")
    session.commit()

    result = _build(session, SATURDAY)

    assert (result.status, result.created, result.item_count, result.warnings) == (None, False, 0, ())
    assert session.scalar(select(func.count(Briefing.id))) == 0


def test_company_not_registered_fails_without_a_row(session, world, empty_extensions) -> None:
    world.collection_run()
    world.notice("홈페이지 유지관리 용역")
    session.commit()

    with pytest.raises(BriefingError) as raised:
        build_briefing(session, BRIEFING_DATE, now=NOW)
    session.rollback()

    assert raised.value.code == "company_not_registered"
    assert session.scalar(select(func.count(Briefing.id))) == 0


def test_no_recommendation_with_complete_collection_is_empty(session, world, plans) -> None:
    world.collection_run()
    world.notice("하드웨어 장비 구매")
    # 사전규격 SW=Y는 그 자체로 가중치가 있으므로 점수 0 후보는 관계없는 입찰공고로 만든다.
    world.notice("관계없는 청소 용역", source_type="bid_notice", sw=None, deadline_at=NOW + timedelta(days=5))
    session.commit()

    result = _build(session)

    assert (result.status, result.created, result.item_count) == ("empty", True, 0)
    assert get_briefing_view(session, BRIEFING_DATE).collection_note is None


def test_dry_run_computes_without_writing(session, world, plans) -> None:
    world.collection_run()
    world.notice("홈페이지 유지관리 용역")
    session.commit()

    result = build_briefing(session, BRIEFING_DATE, now=NOW, persist=False)
    session.rollback()

    assert (result.status, result.created, result.item_count) == ("generated", False, 1)
    assert session.scalar(select(func.count(Briefing.id))) == 0


# --- T5 ----------------------------------------------------------------------


def test_collection_run_patterns_use_the_previous_kst_day_and_retry_directories() -> None:
    assert collection_run_patterns(BRIEFING_DATE) == (
        "lifecycle-20261015-notices--%",
        "lifecycle-20261015-notices-retry%--%",
    )


@pytest.mark.parametrize(
    "runs, warnings, status, note, warning_codes",
    [
        ([], 0, "collection_incomplete", "기준일 수집 회차 없음", ("collection_run_missing",)),
        ([COLLECTION_RUN, COLLECTION_RETRY_RUN], 0, "collection_incomplete", "회차 중복", ("run_ambiguous",)),
        ([COLLECTION_RUN], 1, "collection_incomplete", "기준일 수집 회차에 적재 경고가 있습니다",
         ("collection_run_warnings",)),
        ([COLLECTION_RUN], 0, "generated", None, ()),
        ([COLLECTION_RETRY_RUN], 0, "generated", None, ()),
    ],
    ids=["no-run", "two-runs", "one-run-with-warning", "one-clean-run", "one-clean-retry-run"],
)
def test_t5_collection_state_marks_the_briefing_but_items_are_still_made(
    session, world, plans, runs, warnings, status, note, warning_codes
) -> None:
    for index, run_id in enumerate(runs):
        world.collection_run(run_id, warnings=warnings if index == 0 else 0)
    # 다른 날·다른 트랙 회차는 판정에 들지 않는다.
    world.run("lifecycle-20261014-notices--2026-10-14T21:00:00Z")
    world.run("lifecycle-20261015-order-plans--2026-10-15T21:00:00Z")
    notice = world.notice("홈페이지 유지관리 용역")
    session.commit()

    result = _build(session)

    assert (result.status, result.warnings, result.item_count) == (status, warning_codes, 1)
    assert [item.notice_id for item in _items(session, result.briefing_id)] == [notice.id]
    view = get_briefing_view(session, BRIEFING_DATE)
    assert (view.status, view.collection_note) == (status, note)


def test_concurrent_same_day_insert_returns_the_winner(session, world, plans, monkeypatch) -> None:
    world.collection_run()
    world.notice("홈페이지 유지관리 용역")
    session.commit()
    from app.lifecycle.services import briefing as service

    real_existing = service._existing
    calls = {"n": 0}

    def racing(current, briefing_date):
        calls["n"] += 1
        if calls["n"] == 1:
            # 첫 조회 직후 다른 프로세스가 같은 날 행을 넣었다.
            current.add(Briefing(
                briefing_date=briefing_date, status="empty", generated_at=NOW - timedelta(minutes=1),
                policy_sha256="f" * 64, graph_version_id=GRAPH, item_count=0, excluded_counts={},
                warnings=[], created_by="system:build-briefing",
            ))
            current.flush()
            return None
        return real_existing(current, briefing_date)

    monkeypatch.setattr(service, "_existing", racing)

    result = _build(session)

    assert result.created is False and result.status == "empty"
    assert session.scalar(select(func.count(Briefing.id))) == 1
    assert session.scalar(select(func.count(BriefingItem.id))) == 0


def test_generated_at_is_stored_in_utc(session, world, plans) -> None:
    world.collection_run()
    world.notice("홈페이지 유지관리 용역")
    session.commit()
    kst_now = NOW.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul"))

    result = _build(session, now=kst_now)

    assert session.get(Briefing, result.briefing_id).generated_at == datetime(2026, 10, 15, 22, 30, tzinfo=UTC)
