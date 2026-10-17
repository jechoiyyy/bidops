"""사업기회 활동 피드 파생 (RL-02 spec "활동 피드", T2·T3).

SQLite 격리 DB에 lifecycle 원본(연결·관측·감사·반응·노트)을 심고 service를 직접 부른다.
kind별 파생·첫 관측 제외·정렬과 동률·커서 페이지(같은 시각 포함)·`kinds` 필터·시스템 사건
배제·확장점 제공자 없음/있음을 본다. REST 모양은 `tests/app/test_api_opportunities.py`가,
PostgreSQL strict dict는 `tests/app/test_opportunity_activity_postgres.py`가 갖는다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.core.models import AuditEvent
from app.lifecycle.extensions import extension_registry, reset_extension_registry, restore_extension_registry
from app.lifecycle.models import (
    Briefing,
    BriefingItem,
    BriefingReactionEvent,
    IngestWarning,
    Notice,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OpportunityNote,
    OrderPlan,
    Run,
)
from app.lifecycle.schemas.opportunity_activity import OPPORTUNITY_ACTIVITY_KINDS, ActivityItem
from app.lifecycle.services.opportunity_activity import (
    cursor_for,
    opportunity_activity,
    parse_cursor,
    parse_kinds,
)
from app.lifecycle.services.opportunity_integrity import record_candidate_decision
from app.lifecycle.services.opportunity_tracking import (
    OpportunityTrackingError,
    acknowledge_recheck_signal,
    raise_recheck_signal,
    set_tracking_status,
)

NOW = datetime(2026, 10, 17, 3, 0, tzinfo=UTC)
T0 = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
RUN_ID = "lifecycle-20261010-notices--2026-10-10T21:00:00Z"


def at(days: float, *, minutes: int = 0) -> datetime:
    return T0 + timedelta(days=days, minutes=minutes)


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
def registry():
    previous = extension_registry()
    try:
        yield reset_extension_registry()
    finally:
        restore_extension_registry(previous)


def _observation(session, notice: Notice, run: Run, observed_at: datetime, fields) -> NoticeObservation:
    row = NoticeObservation(notice_id=notice.id, run_id=run.id, observed_at=observed_at, changed_fields_json=fields)
    session.add(row)
    session.flush()
    return row


def _run(session, run_id: str, generated_at: datetime) -> Run:
    row = Run(id=run_id, generated_at=generated_at)
    session.add(row)
    session.flush()
    return row


def _world(session) -> dict:
    """사업 사건과 사람 행동이 모두 있는 사업기회 하나 + 시스템 사건 몇 개."""

    opportunity = Opportunity(first_registered_stage="order_plan", created_at=at(0))
    other = Opportunity(first_registered_stage="bid_notice", created_at=at(0))
    plan = OrderPlan(order_plan_unty_no="R26BK0001", title="홈페이지 고도화 발주계획", agency_name="대구테크노파크")
    pre = Notice(notice_key="pre:R26BD0001", source_type="pre_spec", title="홈페이지 고도화 사전규격",
                 url="https://www.g2b.go.kr/pre/1")
    bid = Notice(notice_key="bid:R26BK0001-000", source_type="bid_notice", title="홈페이지 고도화 용역",
                 url="https://www.g2b.go.kr/bid/1", deadline_at=NOW + timedelta(days=3))
    rejected_notice = Notice(notice_key="bid:R26BK9999-000", source_type="bid_notice", title="다른 사업")
    pending_notice = Notice(notice_key="bid:R26BK8888-000", source_type="bid_notice", title="대기 후보")
    session.add_all([opportunity, other, plan, pre, bid, rejected_notice, pending_notice])
    session.flush()

    plan_link = OpportunityLink(opportunity=opportunity, order_plan=plan, stage="order_plan", link_type="official",
                                status="확정", evidence_external_no=plan.order_plan_unty_no, created_at=at(1))
    pre_link = OpportunityLink(opportunity=opportunity, notice=pre, stage="notice", link_type="official",
                               status="확정", evidence_external_no="R26BD0001", created_at=at(2))
    bid_candidate = OpportunityLink(opportunity=opportunity, notice=bid, stage="notice", link_type="candidate",
                                    status="후보 확인 대기", search_strategy="full", created_at=at(4))
    rejected = OpportunityLink(opportunity=opportunity, notice=rejected_notice, stage="notice", link_type="candidate",
                               status="후보 확인 대기", search_strategy="normalized", created_at=at(4, minutes=1))
    pending = OpportunityLink(opportunity=opportunity, notice=pending_notice, stage="notice", link_type="candidate",
                              status="후보 확인 대기", search_strategy="prefix12", created_at=at(4, minutes=2))
    session.add_all([plan_link, pre_link, bid_candidate, rejected, pending])
    session.flush()
    record_candidate_decision(session, bid_candidate, decision="accepted", reason="같은 사업", reviewer_name="박검토",
                              reviewed_at=at(5))
    record_candidate_decision(session, rejected, decision="rejected", reason="다른 기관", reviewer_name="kim",
                              reviewed_at=at(5, minutes=5))

    # 관측: 사전규격 첫 관측은 추적 필드가 있어도 제외, 둘째는 마감 정정, 셋째는 추적 밖 필드만.
    first_run = _run(session, "lifecycle-20261002-notices--2026-10-02T21:00:00Z", at(2))
    second_run = _run(session, RUN_ID, at(10))
    third_run = _run(session, "lifecycle-20261011-notices--2026-10-11T21:00:00Z", at(11))
    first_obs = _observation(session, pre, first_run, at(2), ["deadline_at", "title"])
    deadline_obs = _observation(session, pre, second_run, at(10), ["attachments", "deadline_at"])
    _observation(session, pre, third_run, at(11), ["demand_agency"])
    bid_first = _observation(session, bid, second_run, at(10), [])
    bid_change = _observation(session, bid, third_run, at(11), {"method": {"old": "a"}, "title": {"old": "b"}})
    # 대기 후보 공고의 정정은 이 사업기회의 사건이 아니다.
    _observation(session, pending_notice, first_run, at(2), [])
    _observation(session, pending_notice, second_run, at(10), ["deadline_at"])

    # 추적 결정·재확인 신호(생성·확인)·되돌림.
    set_tracking_status(session, opportunity, status="계속 추적", reason="주력 분야", selected_by="김철수",
                        selected_at=at(6))
    raise_recheck_signal(session, opportunity, pre_link, signaled_at=at(7))
    acknowledge_recheck_signal(session, opportunity, expected_link_id=pre_link.id, acknowledged_by="lee",
                               acknowledged_at=at(8))
    set_tracking_status(session, opportunity, status="보류", reason="예산 확인", selected_by="lee", selected_at=at(9))
    set_tracking_status(session, opportunity, status="미선택", reason="사업 취소 공지", selected_by="lee",
                        selected_at=at(12))

    # 브리핑 반응: 대기로의 변화는 피드에 없다.
    briefing = Briefing(briefing_date=date(2026, 10, 13), status="generated", generated_at=at(12),
                        policy_sha256="a" * 64, graph_version_id=uuid4(), item_count=1, excluded_counts={},
                        warnings=[], created_by="system")
    session.add(briefing)
    session.flush()
    item = BriefingItem(briefing_id=briefing.id, kind="recommendation", rank=1, stage="bid_notice", notice_id=bid.id,
                        opportunity_id=opportunity.id, reaction="채택", reacted_by="최담당", reacted_at=at(12, minutes=30),
                        reacted_via="screen", revision=2)
    other_item = BriefingItem(briefing_id=briefing.id, kind="recommendation", rank=2, stage="bid_notice",
                              notice_id=rejected_notice.id, opportunity_id=other.id, reaction="무시",
                              reacted_by="최담당", reacted_at=at(12, minutes=31), reacted_via="slack", revision=1)
    session.add_all([item, other_item])
    session.flush()
    adopted = BriefingReactionEvent(item_id=item.id, revision=1, previous="대기", new="채택", actor="최담당", via="screen",
                                    request_id=uuid4(), created_at=at(12, minutes=20))
    back_to_wait = BriefingReactionEvent(item_id=item.id, revision=2, previous="채택", new="대기", actor="최담당",
                                         via="screen", request_id=uuid4(), created_at=at(12, minutes=25))
    others = BriefingReactionEvent(item_id=other_item.id, revision=1, previous="대기", new="무시", actor="최담당",
                                   via="slack", request_id=uuid4(), created_at=at(12, minutes=31))
    session.add_all([adopted, back_to_wait, others])

    # 노트·다음 행동.
    note = OpportunityNote(opportunity_id=opportunity.id, kind="note", body="발주처 담당자 통화\n다음 주 재문의",
                           actor="kim", owner="kim", created_at=at(13))
    action = OpportunityNote(opportunity_id=opportunity.id, kind="action", body="제안 일정 확인", actor="kim",
                             owner="박담당", created_at=at(13, minutes=10), done_at=at(14), done_by="박담당")
    open_action = OpportunityNote(opportunity_id=opportunity.id, kind="action", body="실적 증명서 준비", actor="lee",
                                  owner="lee", created_at=at(13, minutes=20))
    session.add_all([note, action, open_action])

    # 시스템 처리: 수집 경고, 찾아보기·병합 같은 다른 감사 action. 피드에 없어야 한다.
    session.add(IngestWarning(run_id=second_run.id, level="warning", code="partial_collection", message=RUN_ID))
    for action_name in ("opportunity.search.performed", "opportunity.merged.human_confirmed", "c2.policy.activated"):
        session.add(AuditEvent(actor_kind="system", claimed_name=None, action=action_name, aggregate_type="opportunity",
                               aggregate_id=str(opportunity.id), safe_metadata={"run_id": RUN_ID}, created_at=at(15)))
    session.flush()
    session.commit()
    return {
        "opportunity": opportunity,
        "plan_link": plan_link,
        "pre_link": pre_link,
        "bid_link": bid_candidate,
        "rejected_link": rejected,
        "pre": pre,
        "bid": bid,
        "first_obs": first_obs,
        "deadline_obs": deadline_obs,
        "bid_first": bid_first,
        "bid_change": bid_change,
        "item": item,
        "adopted": adopted,
        "note": note,
        "action": action,
        "open_action": open_action,
    }


def _feed(session, opportunity_id, **kwargs):
    kwargs.setdefault("now", NOW)
    return opportunity_activity(session, opportunity_id, **kwargs)


def _audit_id(session, action: str, created_at: datetime) -> UUID:
    from sqlalchemy import select

    return session.scalars(
        select(AuditEvent.id).where(AuditEvent.action == action, AuditEvent.created_at == created_at)
    ).one()


def test_t2_every_kind_is_derived_with_its_title_actor_link_and_time(session, registry) -> None:
    world = _world(session)
    opportunity = world["opportunity"]

    response = _feed(session, opportunity.id, limit=200)

    tracking = "opportunity.tracking_status.changed"
    expected = [
        ("action_done", f"action_done:{world['action'].id}", at(14), "박담당", "박담당이 완료: 제안 일정 확인", None, None, None),
        ("action_added", f"action_added:{world['open_action'].id}", at(13, minutes=20), "lee", "다음 행동: 실적 증명서 준비", "담당 lee", None, None),
        ("action_added", f"action_added:{world['action'].id}", at(13, minutes=10), "kim", "다음 행동: 제안 일정 확인", "담당 박담당", None, None),
        ("note_added", f"note_added:{world['note'].id}", at(13), "kim", "발주처 담당자 통화", None, None, None),
        ("briefing_reacted", f"briefing_reacted:{world['adopted'].id}", at(12, minutes=20), "최담당", "최담당이 채택", None,
         {"label": "브리핑 보기", "path": f"/briefing?date=2026-10-13&selected={world['item'].id}"}, "채택"),
        ("tracking_decided", f"tracking_decided:{_audit_id(session, tracking, at(12))}", at(12), "lee", "lee이 추적 되돌림", "사업 취소 공지", None, None),
        ("notice_corrected", f"notice_corrected:{world['bid_change'].id}", at(11), None, "정정 · 제목, 계약방법", None,
         {"label": "공고 원문", "path": "https://www.g2b.go.kr/bid/1"}, None),
        ("notice_corrected", f"notice_corrected:{world['deadline_obs'].id}", at(10), None, "정정 · 마감", None,
         {"label": "변경 이력", "path": f"/pre-specs/{world['pre'].id}#ps-record-history"}, None),
        ("tracking_decided", f"tracking_decided:{_audit_id(session, tracking, at(9))}", at(9), "lee", "lee이 보류로 결정", None, None, None),
        ("recheck_signal", f"recheck_signal:{_audit_id(session, 'opportunity.recheck_signal.acknowledged', at(8))}", at(8), "lee", "lee이 신호 확인", None, None, None),
        ("recheck_signal", f"recheck_signal:{_audit_id(session, 'opportunity.recheck_signal.created', at(7))}", at(7), None, "재확인 신호", None, None, None),
        ("tracking_decided", f"tracking_decided:{_audit_id(session, tracking, at(6))}", at(6), "김철수", "김철수가 계속 추적으로 결정", None, None, None),
        ("link_reviewed", f"link_reviewed:{world['rejected_link'].id}", at(5, minutes=5), "kim", "kim이 연결 후보 거절", None, None, None),
        ("link_reviewed", f"link_reviewed:{world['bid_link'].id}", at(5), "박검토", "박검토가 연결 후보 수락", None, None, None),
        ("bid_posted", f"bid_posted:{world['bid_link'].id}", at(4), None, "입찰공고 게시", None,
         {"label": "공고 원문", "path": "https://www.g2b.go.kr/bid/1"}, None),
        ("pre_spec_opened", f"pre_spec_opened:{world['pre_link'].id}", at(2), None, "사전규격 공개", None,
         {"label": "사전규격 보기", "path": f"/pre-specs/{world['pre'].id}"}, None),
        ("order_plan_found", f"order_plan_found:{world['plan_link'].id}", at(1), None, "발주계획 발견 · 대구테크노파크", None,
         {"label": "발주계획 보기", "path": f"/order-plans/{world['plan_link'].order_plan_id}"}, None),
    ]
    actual = [
        (
            item.kind,
            item.item_id,
            item.at,
            item.actor,
            item.title,
            item.detail,
            item.link.model_dump() if item.link is not None else None,
            item.status_pill,
        )
        for item in response.items
    ]
    assert actual == expected
    assert response.next_before is None
    assert response.merged_into_opportunity_id is None
    assert response.title == "홈페이지 고도화 용역"
    assert [(stage.key, stage.state, stage.link_id) for stage in response.stages] == [
        ("order_plan", "done", world["plan_link"].id),
        ("pre_spec", "done", world["pre_link"].id),
        ("bid_notice", "current", world["bid_link"].id),
        ("deadline", "upcoming_deadline", world["bid_link"].id),
        ("opening", "unknown", world["bid_link"].id),
        ("contract", "unknown", None),
    ]


def test_t2_first_observation_is_excluded_even_when_it_names_tracked_fields(session, registry) -> None:
    world = _world(session)

    items = _feed(session, world["opportunity"].id, kinds=("notice_corrected",)).items

    ids = {item.item_id for item in items}
    assert f"notice_corrected:{world['first_obs'].id}" not in ids
    assert f"notice_corrected:{world['bid_first'].id}" not in ids
    assert len(items) == 2


def test_t2_first_observation_is_the_first_loaded_one_even_when_an_older_run_arrives_later(session, registry) -> None:
    """적재기는 적재 순서로 `is_new`를 정한다. 늦게 적재된 옛 회차의 관측은 첫 관측이 아니다."""

    opportunity = Opportunity(first_registered_stage="bid_notice", created_at=at(0))
    notice = Notice(notice_key="bid:R26BK0500-000", source_type="bid_notice", title="재적재 공고",
                    url="https://www.g2b.go.kr/bid/500")
    session.add_all([opportunity, notice])
    session.flush()
    session.add(OpportunityLink(opportunity=opportunity, notice=notice, stage="notice", link_type="official",
                                status="확정", evidence_external_no="R26BK0500", created_at=at(1)))
    newer_run = _run(session, "lifecycle-20261010-notices--2026-10-10T21:00:00Z", at(10))
    older_run = _run(session, "lifecycle-20261005-notices--2026-10-05T21:00:00Z", at(5))
    # 새 회차가 먼저 적재돼 `is_new` 관측(id가 작다)이 되고, 옛 회차가 뒤에 적재돼 바뀐 필드를 남긴다.
    loaded_first = _observation(session, notice, newer_run, at(10), ["title"])
    loaded_later = _observation(session, notice, older_run, at(5), ["deadline_at"])
    assert loaded_first.id < loaded_later.id
    session.commit()

    items = _feed(session, opportunity.id, kinds=("notice_corrected",)).items

    assert [item.item_id for item in items] == [f"notice_corrected:{loaded_later.id}"]
    assert items[0].title == "정정 · 마감"


def test_t2_no_system_event_reaches_the_feed(session, registry) -> None:
    world = _world(session)

    items = _feed(session, world["opportunity"].id, limit=200).items

    assert {item.kind for item in items} <= set(OPPORTUNITY_ACTIVITY_KINDS)
    serialized = " ".join(item.model_dump_json() for item in items)
    for forbidden in (RUN_ID, "lifecycle-", "partial_collection", "c2.policy", "search.performed", "merged.human"):
        assert forbidden not in serialized
    # 판정·초안 kind는 제공자가 없으면 0건이다(T3).
    assert not [item for item in items if item.kind in {"verdict_completed", "draft_prepared"}]


def test_t2_equal_times_tie_break_on_item_id_descending(session, registry) -> None:
    opportunity = Opportunity(first_registered_stage="order_plan")
    session.add(opportunity)
    session.flush()
    notes = [
        OpportunityNote(id=UUID(f"00000000-0000-4000-8000-00000000000{index}"), opportunity_id=opportunity.id,
                        kind="note", body=f"메모 {index}", actor="kim", owner="kim", created_at=at(3))
        for index in (2, 5, 1, 4, 3)
    ]
    session.add_all(notes)
    session.commit()

    items = _feed(session, opportunity.id).items

    assert [item.title for item in items] == ["메모 5", "메모 4", "메모 3", "메모 2", "메모 1"]


def test_t2_cursor_pages_cover_everything_once_across_equal_timestamps(session, registry) -> None:
    opportunity = Opportunity(first_registered_stage="order_plan")
    session.add(opportunity)
    session.flush()
    # 같은 시각 4건 + 앞뒤 시각 각 1건. 페이지 경계가 같은 시각 묶음 가운데에 떨어진다.
    times = [at(2), at(3), at(3), at(3), at(3), at(4, minutes=0)]
    session.add_all(
        OpportunityNote(id=UUID(f"00000000-0000-4000-8000-00000000001{index}"), opportunity_id=opportunity.id,
                        kind="note", body=f"메모 {index}", actor="kim", owner="kim", created_at=value)
        for index, value in enumerate(times)
    )
    session.commit()

    full = [item.item_id for item in _feed(session, opportunity.id).items]
    pages: list[list[str]] = []
    before = None
    while True:
        page = _feed(session, opportunity.id, limit=2, before=before)
        pages.append([item.item_id for item in page.items])
        if page.next_before is None:
            break
        before = page.next_before
    assert [len(page) for page in pages] == [2, 2, 2]
    assert [item for page in pages for item in page] == full
    assert len(set(full)) == 6
    # 커서는 마지막 항목의 `"<at ISO>|<item_id>"`이다.
    # 첫 페이지 마지막 항목은 같은 시각(at(3)) 묶음의 첫 항목이다.
    first_page = _feed(session, opportunity.id, limit=2)
    assert first_page.items[-1].at == at(3)
    assert first_page.next_before == f"2026-10-04T00:00:00Z|{first_page.items[-1].item_id}"


def test_t2_cursor_round_trips_and_microseconds_survive(session, registry) -> None:
    item = ActivityItem(item_id="note_added:abc", kind="note_added", at=datetime(2026, 10, 1, 1, 2, 3, 456789, tzinfo=UTC),
                        title="메모")
    cursor = cursor_for(item)
    assert cursor == "2026-10-01T01:02:03.456789Z|note_added:abc"
    assert parse_cursor(cursor) == (item.at, "note_added:abc")
    assert parse_cursor("2026-10-01T10:02:03.456789+09:00|bid_posted:3") == (
        datetime(2026, 10, 1, 1, 2, 3, 456789, tzinfo=UTC),
        "bid_posted:3",
    )


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "2026-10-01T01:02:03Z",
        "2026-10-01T01:02:03|note_added:1",
        "어제|note_added:1",
        "2026-10-01T01:02:03Z|unknown_kind:1",
        "2026-10-01T01:02:03Z|note_added:",
        "2026-10-01T01:02:03Z|note_added",
        "2026-10-01T01:02:03Z|note_added:1|x",
    ],
)
def test_t2_bad_cursor_is_invalid_request(session, registry, cursor) -> None:
    opportunity = Opportunity(first_registered_stage="order_plan")
    session.add(opportunity)
    session.commit()
    with pytest.raises(OpportunityTrackingError) as error:
        _feed(session, opportunity.id, before=cursor)
    assert error.value.code == "invalid_request"


def test_t2_kinds_filter_and_parsing(session, registry) -> None:
    world = _world(session)

    items = _feed(session, world["opportunity"].id, kinds=("note_added", "action_done")).items

    assert [item.kind for item in items] == ["action_done", "note_added"]
    assert parse_kinds(None) is None
    assert parse_kinds("") is None
    assert parse_kinds(" note_added , action_done,note_added ") == ("note_added", "action_done")
    for bad in ("note", "note_added,run_ingested", ",", "verdict"):
        with pytest.raises(OpportunityTrackingError) as error:
            parse_kinds(bad)
        assert error.value.code == "invalid_request"


@pytest.mark.parametrize("limit", [0, 201, -1, True])
def test_t2_limit_outside_one_to_two_hundred_is_invalid(session, registry, limit) -> None:
    opportunity = Opportunity(first_registered_stage="order_plan")
    session.add(opportunity)
    session.commit()
    with pytest.raises(OpportunityTrackingError) as error:
        _feed(session, opportunity.id, limit=limit)
    assert error.value.code == "invalid_request"


def test_t2_missing_opportunity_is_not_found_and_merged_one_is_still_served(session, registry) -> None:
    survivor = Opportunity(first_registered_stage="bid_notice")
    session.add(survivor)
    session.flush()
    merged = Opportunity(first_registered_stage="bid_notice", merged_into_opportunity_id=survivor.id,
                         merged_at=at(3), merge_reason="합성 병합")
    session.add(merged)
    session.flush()
    session.add(OpportunityNote(opportunity_id=merged.id, kind="note", body="병합 전 메모", actor="kim", owner="kim",
                                created_at=at(2)))
    session.commit()

    response = _feed(session, merged.id)
    assert response.merged_into_opportunity_id == survivor.id
    assert response.title == f"#{merged.id}"
    assert [item.title for item in response.items] == ["병합 전 메모"]
    with pytest.raises(OpportunityTrackingError) as error:
        _feed(session, 999_999)
    assert error.value.code == "opportunity_not_found"


def test_t2_long_note_title_is_cut_to_120_characters_and_unsafe_urls_get_no_link(session, registry) -> None:
    opportunity = Opportunity(first_registered_stage="bid_notice")
    notice = Notice(notice_key="bid:X-000", source_type="bid_notice", title="공고", url="javascript:alert(1)")
    session.add_all([opportunity, notice])
    session.flush()
    session.add(OpportunityLink(opportunity=opportunity, notice=notice, stage="notice", link_type="official",
                                status="확정", evidence_external_no="X", created_at=at(1)))
    body = "가" * 130
    session.add(OpportunityNote(opportunity_id=opportunity.id, kind="note", body=body, actor="kim", owner="kim",
                                created_at=at(2)))
    session.commit()

    note, posted = _feed(session, opportunity.id).items
    assert (note.title, note.detail) == ("가" * 120, None)
    assert (posted.kind, posted.link) == ("bid_posted", None)


def test_t2_order_plan_without_agency_has_a_plain_title(session, registry) -> None:
    opportunity = Opportunity(first_registered_stage="order_plan")
    plan = OrderPlan(order_plan_unty_no="R26BK0002", title="계획", agency_name=None)
    session.add_all([opportunity, plan])
    session.flush()
    session.add(OpportunityLink(opportunity=opportunity, order_plan=plan, stage="order_plan", link_type="official",
                                status="확정", evidence_external_no="R26BK0002", created_at=at(1)))
    session.commit()

    (item,) = _feed(session, opportunity.id).items
    assert item.title == "발주계획 발견"


# --- T3 확장점 --------------------------------------------------------------


class _Provider:
    def __init__(self, *items: ActivityItem) -> None:
        self.items = items
        self.calls: list[int] = []

    def opportunity_activity_items(self, session, opportunity_id):
        self.calls.append(opportunity_id)
        return list(self.items)


def test_t3_without_a_provider_hook_kinds_have_no_items(session, registry) -> None:
    opportunity = Opportunity(first_registered_stage="order_plan")
    session.add(opportunity)
    session.commit()

    assert registry.opportunity_activity_items_provider_count == 0
    assert registry.opportunity_activity_items(session, opportunity.id) == []
    assert _feed(session, opportunity.id).items == []


def test_t3_providers_are_merged_in_registration_order_then_sorted_with_lifecycle_items(session, registry) -> None:
    opportunity = Opportunity(first_registered_stage="order_plan")
    session.add(opportunity)
    session.flush()
    session.add(OpportunityNote(opportunity_id=opportunity.id, kind="note", body="메모", actor="kim", owner="kim",
                                created_at=at(2)))
    session.commit()
    verdict = ActivityItem(item_id="verdict_completed:11", kind="verdict_completed", at=at(3), title="판정 완료",
                           link={"label": "판정 보기", "path": f"/opportunities/{opportunity.id}/verdict"})
    # +09:00 시각도 UTC로 맞춰 정렬한다.
    draft = ActivityItem(item_id="draft_prepared:7", kind="draft_prepared",
                         at=(at(1)).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul")), title="초안 준비")
    tie = ActivityItem(item_id="verdict_completed:12", kind="verdict_completed", at=at(3), title="판정 완료 2")
    first = _Provider(verdict, draft)
    second = _Provider(tie)
    registry.register_opportunity_activity_items(first, owner="deep_review")
    registry.register_opportunity_activity_items(second, owner="proposal")
    # 같은 owner 재등록은 제자리 교체이고 순서를 바꾸지 않는다.
    registry.register_opportunity_activity_items(first, owner="deep_review")

    assert [item.item_id for item in registry.opportunity_activity_items(session, opportunity.id)] == [
        "verdict_completed:11", "draft_prepared:7", "verdict_completed:12",
    ]
    response = _feed(session, opportunity.id)
    assert [item.item_id.split(":")[0] for item in response.items] == [
        "verdict_completed", "verdict_completed", "note_added", "draft_prepared",
    ]
    assert [item.item_id for item in response.items[:2]] == ["verdict_completed:12", "verdict_completed:11"]
    assert response.items[-1].at == at(1) and response.items[-1].at.utcoffset() == timedelta(0)
    assert first.calls[-1] == opportunity.id and second.calls[-1] == opportunity.id
    filtered = _feed(session, opportunity.id, kinds=("draft_prepared",))
    assert [item.item_id for item in filtered.items] == ["draft_prepared:7"]


def test_t3_a_provider_returning_something_else_is_an_assembly_error(session, registry) -> None:
    class _Broken:
        def opportunity_activity_items(self, session, opportunity_id):
            return [{"item_id": "verdict_completed:1"}]

    registry.register_opportunity_activity_items(_Broken(), owner="broken")
    with pytest.raises(TypeError):
        registry.opportunity_activity_items(None, 1)


def test_activity_item_id_must_name_its_kind() -> None:
    with pytest.raises(ValueError):
        ActivityItem(item_id="note_added:1", kind="action_done", at=at(1), title="x")
    with pytest.raises(ValueError):
        ActivityItem(item_id="note_added:1|2", kind="note_added", at=at(1), title="x")
