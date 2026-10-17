"""단계 바 6단계·레코드 제목 규칙 (RL-02 spec "단계 바"·"레코드 헤더", T1).

순수 함수만 검사한다. 연결 조합(발주계획만 / 사전규격+공고 / 공고 마감 지남 / 개찰 키 유무)마다
6단계 state가 spec 표와 "그 밖" 규칙에 맞는지, 제목·현재 단계 선택이 맞는지 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.lifecycle.models import Notice, OpportunityLink, OrderPlan
from app.lifecycle.services import opportunity_stages
from app.lifecycle.services.opportunity_stages import (
    StageRecord,
    current_stage,
    opening_at_from_lifecycle,
    record_title,
    stage_records,
    stage_views,
)

NOW = datetime(2026, 10, 17, 3, 0, 0, 250000, tzinfo=UTC)
T_PLAN = datetime(2026, 3, 2, 1, tzinfo=UTC)
T_PRE = datetime(2026, 8, 3, 1, tzinfo=UTC)
T_BID = datetime(2026, 9, 21, 1, tzinfo=UTC)


def _plan(**extra) -> StageRecord:
    return StageRecord(stage="order_plan", link_id=1, linked_at=T_PLAN, title="발주계획 제목", **extra)


def _pre(**extra) -> StageRecord:
    return StageRecord(stage="pre_spec", link_id=2, linked_at=T_PRE, title="사전규격 제목", **extra)


def _bid(**extra) -> StageRecord:
    values = {"link_id": 3, "linked_at": T_BID, "title": "입찰공고 제목"}
    values.update(extra)
    return StageRecord(stage="bid_notice", **values)


def _states(records) -> list[tuple[str, str, datetime | None]]:
    return [(view.key, view.state, view.at) for view in stage_views(records, now=NOW)]


def test_order_plan_only_keeps_later_record_stages_pending_and_dates_unknown() -> None:
    records = [_plan()]

    assert _states(records) == [
        ("order_plan", "current", T_PLAN),
        ("pre_spec", "pending", None),
        ("bid_notice", "pending", None),
        ("deadline", "unknown", None),
        ("opening", "unknown", None),
        ("contract", "unknown", None),
    ]
    assert record_title(records) == "발주계획 제목"
    assert current_stage(records) == "order_plan"


def test_pre_spec_and_bid_notice_without_order_plan_mark_the_skipped_stage_unknown() -> None:
    deadline = NOW + timedelta(days=3)
    records = [_pre(), _bid(deadline_at=deadline)]

    assert _states(records) == [
        ("order_plan", "unknown", None),
        ("pre_spec", "done", T_PRE),
        ("bid_notice", "current", T_BID),
        ("deadline", "upcoming_deadline", deadline),
        ("opening", "unknown", None),
        ("contract", "unknown", None),
    ]
    assert record_title(records) == "입찰공고 제목"
    assert current_stage(records) == "bid_notice"


def test_bid_notice_without_pre_spec_marks_pre_spec_unknown() -> None:
    records = [_plan(), _bid(deadline_at=NOW + timedelta(hours=1))]

    states = _states(records)
    assert states[0] == ("order_plan", "done", T_PLAN)
    assert states[1] == ("pre_spec", "unknown", None)
    assert states[2] == ("bid_notice", "current", T_BID)


def test_passed_deadline_finishes_the_bid_notice_and_opening_follows_lifecycle_json() -> None:
    deadline = NOW - timedelta(days=1)
    opening = NOW - timedelta(hours=20)
    records = [_plan(), _pre(), _bid(deadline_at=deadline, opening_at=opening)]

    assert _states(records) == [
        ("order_plan", "done", T_PLAN),
        ("pre_spec", "done", T_PRE),
        ("bid_notice", "done", T_BID),
        ("deadline", "done", deadline),
        ("opening", "done", opening),
        ("contract", "unknown", None),
    ]
    # 마감이 지나도 제목·현재 단계는 가장 뒤 연결 단계다.
    assert record_title(records) == "입찰공고 제목"
    assert current_stage(records) == "bid_notice"


def test_future_opening_is_an_upcoming_date_and_deadline_equal_to_now_is_not_passed() -> None:
    opening = NOW + timedelta(days=2)
    records = [_bid(deadline_at=NOW, opening_at=opening)]

    states = dict((key, (state, at)) for key, state, at in _states(records))
    assert states["bid_notice"] == ("current", T_BID)
    assert states["deadline"] == ("upcoming_deadline", NOW)
    assert states["opening"] == ("upcoming_deadline", opening)


def test_bid_notice_without_deadline_stays_current_and_the_deadline_is_unknown() -> None:
    states = _states([_bid(deadline_at=None)])

    assert states[2] == ("bid_notice", "current", T_BID)
    assert states[3] == ("deadline", "unknown", None)
    assert states[4] == ("opening", "unknown", None)


def test_contract_is_always_unknown() -> None:
    records = [_plan(), _pre(), _bid(deadline_at=NOW - timedelta(days=9), opening_at=NOW - timedelta(days=8))]
    assert _states(records)[5] == ("contract", "unknown", None)
    assert _states([])[5] == ("contract", "unknown", None)


def test_no_authoritative_link_has_pending_record_stages_and_no_title() -> None:
    assert _states([]) == [
        ("order_plan", "pending", None),
        ("pre_spec", "pending", None),
        ("bid_notice", "pending", None),
        ("deadline", "unknown", None),
        ("opening", "unknown", None),
        ("contract", "unknown", None),
    ]
    assert record_title([]) is None
    assert current_stage([]) is None


def test_pre_spec_only_leaves_the_bid_notice_pending() -> None:
    states = _states([_pre()])
    assert states[:3] == [
        ("order_plan", "unknown", None),
        ("pre_spec", "current", T_PRE),
        ("bid_notice", "pending", None),
    ]


def test_latest_link_in_a_stage_represents_it_and_a_blank_title_is_no_title() -> None:
    older = _bid(link_id=7, linked_at=T_BID, title="1차 공고", deadline_at=NOW - timedelta(days=1))
    newer = _bid(link_id=8, linked_at=T_BID + timedelta(days=1), title="재공고", deadline_at=NOW + timedelta(days=5))
    tie = _bid(link_id=9, linked_at=T_BID + timedelta(days=1), title="재공고 2", deadline_at=NOW + timedelta(days=6))

    assert record_title([older, newer]) == "재공고"
    assert _states([older, newer])[3] == ("deadline", "upcoming_deadline", NOW + timedelta(days=5))
    # 같은 연결 시각이면 큰 연결 id가 대표다.
    assert record_title([newer, tie, older]) == "재공고 2"
    assert record_title([_plan(), _bid(title="   ")]) is None
    assert record_title([_plan(), _bid(title=None)]) is None


def _link_ids(records) -> list[tuple[str, int | None]]:
    return [(view.key, view.link_id) for view in stage_views(records, now=NOW)]


def test_stage_link_id_is_the_representative_and_deadline_opening_follow_the_bid_notice() -> None:
    older = _bid(link_id=7, linked_at=T_BID, deadline_at=NOW - timedelta(days=1))
    newer = _bid(link_id=8, linked_at=T_BID + timedelta(days=1), deadline_at=NOW + timedelta(days=5))
    tie = _bid(link_id=9, linked_at=T_BID + timedelta(days=1), deadline_at=NOW + timedelta(days=6))

    # 연결 시각이 늦은 쪽(id 8)이 대표이고, 같은 시각이면 큰 id(9)가 대표다. 입력 순서와 무관하다.
    assert _link_ids([newer, _plan(), older, _pre()]) == [
        ("order_plan", 1), ("pre_spec", 2), ("bid_notice", 8), ("deadline", 8), ("opening", 8), ("contract", None),
    ]
    assert _link_ids([tie, older, newer])[2:5] == [("bid_notice", 9), ("deadline", 9), ("opening", 9)]


def test_stage_link_id_is_null_for_missing_stages_and_without_a_bid_notice() -> None:
    assert _link_ids([]) == [
        ("order_plan", None), ("pre_spec", None), ("bid_notice", None),
        ("deadline", None), ("opening", None), ("contract", None),
    ]
    # 사전규격만 있으면 마감·개찰은 입찰공고가 없으므로 null이다(의견 마감은 마감 단계가 아니다).
    assert _link_ids([_pre(deadline_at=NOW + timedelta(days=2))]) == [
        ("order_plan", None), ("pre_spec", 2), ("bid_notice", None),
        ("deadline", None), ("opening", None), ("contract", None),
    ]
    # 입찰공고가 있으면 마감·개찰 값이 미확인이어도 그 입찰공고 연결을 가리킨다.
    views = {view.key: view for view in stage_views([_bid(deadline_at=None)], now=NOW)}
    assert (views["deadline"].state, views["deadline"].link_id) == ("unknown", 3)
    assert (views["opening"].state, views["opening"].link_id) == ("unknown", 3)


@pytest.mark.parametrize(
    ("lifecycle", "expected"),
    [
        ({"opening_at": "2026-10-20T11:00:00+09:00"}, datetime(2026, 10, 20, 2, tzinfo=UTC)),
        ({"opening_at": None}, None),
        ({}, None),
        (None, None),
        ([], None),
        ({"opening_at": "2026-10-20 11:00"}, None),
        ({"opening_at": "2026-10-20T11:00:00"}, None),
        ({"opening_at": "내일"}, None),
        ({"opening_at": 20261020}, None),
    ],
)
def test_opening_at_is_read_only_from_an_aware_iso_value(lifecycle, expected) -> None:
    assert opening_at_from_lifecycle(lifecycle) == expected


def _link(**values) -> OpportunityLink:
    defaults = {"stage": "notice", "link_type": "official", "status": "확정", "evidence_external_no": "X"}
    defaults.update(values)
    return OpportunityLink(**defaults)


def test_stage_records_keep_only_authoritative_links_with_a_known_record_stage() -> None:
    plan = OrderPlan(order_plan_unty_no="R1", title="계획", agency_name="기관")
    pre = Notice(notice_key="pre:1", source_type="pre_spec", title="사전")
    bid = Notice(
        notice_key="bid:1",
        source_type="bid_notice",
        title="공고",
        deadline_at=NOW + timedelta(days=1),
        lifecycle_json={"opening_at": "2026-10-19T02:00:00+00:00"},
        raw_source="/srv/bidops/data/runs/secret/raw.json",
    )
    other = Notice(notice_key="other:1", source_type="contract_result", title="기타")
    links = [
        _link(id=1, stage="order_plan", order_plan=plan, created_at=T_PLAN),
        _link(id=2, notice=pre, created_at=T_PRE),
        _link(
            id=3,
            notice=bid,
            link_type="candidate",
            status="사람 확인 완료",
            human_decision="accepted",
            reviewer_name="kim",
            reviewed_at=T_BID,
            review_reason="같은 사업",
            created_at=T_BID,
        ),
        # 확인 대기·거절 후보, 기타 공고 종류, 대상 없는 공식 연결은 단계가 아니다.
        _link(id=4, notice=Notice(notice_key="bid:2", source_type="bid_notice", title="후보"), link_type="candidate", status="후보 확인 대기", created_at=T_BID),
        _link(id=5, notice=Notice(notice_key="bid:3", source_type="bid_notice", title="거절"), link_type="candidate", status="후보 확인 대기", human_decision="rejected", created_at=T_BID),
        _link(id=6, notice=other, created_at=T_BID),
        _link(id=7, stage="order_plan", created_at=T_BID),
        _link(id=8, link_type="candidate", status="사람 확인 병합", human_decision="accepted", notice=Notice(notice_key="bid:4", source_type="bid_notice", title="병합"), created_at=T_BID),
    ]

    records = stage_records(links)

    assert [(record.stage, record.link_id, record.title) for record in records] == [
        ("order_plan", 1, "계획"),
        ("pre_spec", 2, "사전"),
        ("bid_notice", 3, "공고"),
    ]
    bid_record = records[2]
    assert bid_record.deadline_at == NOW + timedelta(days=1)
    assert bid_record.opening_at == datetime(2026, 10, 19, 2, tzinfo=UTC)
    assert "secret" not in repr(records)


def test_stage_module_never_reads_raw_source() -> None:
    source = Path(opportunity_stages.__file__).read_text(encoding="utf-8")
    assert "raw_source" not in source
