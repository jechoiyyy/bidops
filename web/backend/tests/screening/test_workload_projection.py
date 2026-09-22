"""미답변 blocking 항목과 발주계획 업무 건수의 실제 screening 제공자."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle import ExtensionRegistry, WorkloadCount, WorkloadProjection
from app.lifecycle.models import Notice, Run
from app.screening import ScreeningJudgmentProjection, register_lifecycle_extensions
from app.screening.models import Judgment, Review, VerificationAnswer, VerificationItem
from app.screening.services.order_plan_screening import (
    OrderPlanScreeningError,
    OrderPlanScreeningService,
)
from tests.postgres import migrated_engine, requires_postgres
from tests.screening.test_order_plan_list_v2 import execution, feedback, owner, result
from tests.screening.test_order_plan_screening_service import _fixture

NOW = datetime(2026, 9, 2, tzinfo=UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def add_notice(session, run, key, items=(), answers=None):
    notice = Notice(run=run, notice_key=key)
    session.add(notice)
    session.flush()
    if items:
        judgment = Judgment(notice_id=notice.id, grade="우선 검토")
        judgment.verification_items = [
            VerificationItem(item=name, blocking=blocking, status=status)
            for name, blocking, status in items
        ]
        session.add(judgment)
    if answers is not None:
        review = Review(notice_id=notice.id, run_id=run.id)
        review.answers = [VerificationAnswer(item=name, answer=answer) for name, answer in answers]
        session.add(review)
    return notice


def check_blocking_semantics(session):
    run = Run(id="blocking-current", generated_at=NOW)
    other_run = Run(id="blocking-other", generated_at=NOW)
    session.add_all([run, other_run])
    first = add_notice(session, run, "blocking-first", [
        (" 참가자격 ", True, "미확인"), ("참가자격", True, "미확인"),
        ("실적", True, "확인 완료"), (None, True, None), ("", True, "unknown"),
        (" \t", True, None), ("\ufeff담당자\u00a0", True, "미확인"),
        ("\u0085별도\u0085", True, "미확인"),
        ("중복", True, None), ("중복", True, None), ("비차단", False, "미확인"),
    ], [("\t참가자격\n", None), ("담당자", ""), ("별도", "확인"), (None, "답변"), ("  ", "답변")])
    second = add_notice(session, run, "blocking-answered", [("해소", True, "unknown")], [("해소", "unknown")])
    third = add_notice(session, other_run, "blocking-elsewhere", [("다른 회차", True, "미확인")])
    absent = add_notice(session, run, "blocking-no-judgment", answers=[("이름", "답변")])
    session.commit()
    ids = [first.id, second.id, third.id, absent.id]
    projection = ScreeningJudgmentProjection()
    assert projection.open_blocking_item_counts(session, ids + [first.id]) == {
        first.id: 7, second.id: 0, third.id: 1, absent.id: 0,
    }
    assert set(projection.notice_ids_with_open_blocking_items(session)) == {first.id, third.id}
    assert projection.open_blocking_item_counts(session, [second.id, absent.id]) == {second.id: 0, absent.id: 0}
    assert projection.open_blocking_item_counts(session, []) == {}
    registry = register_lifecycle_extensions(ExtensionRegistry())
    assert registry.open_blocking_item_counts(session, ids) == projection.open_blocking_item_counts(session, ids)
    assert set(registry.notice_ids_with_open_blocking_items(session)) == {first.id, third.id}


def test_blocking_counts_preserve_existing_answer_presence_trim_and_duplicate_rules(session):
    check_blocking_semantics(session)


def check_query_count(session):
    run = Run(id="blocking-many", generated_at=NOW)
    session.add(run)
    ids = []
    for index in range(601):
        notice = add_notice(session, run, f"blocking-{index}", [
            ("답변 있음", True, "미확인"), ("답변 없음", True, "미확인"),
        ], [("답변 있음", None)])
        ids.append(notice.id)
    session.commit()
    projection = ScreeningJudgmentProjection()
    counts = []
    for size in (9, 601):
        session.expunge_all()
        statements = []
        def record(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        event.listen(session.bind, "before_cursor_execute", record)
        try:
            values = projection.open_blocking_item_counts(session, ids[:size])
        finally:
            event.remove(session.bind, "before_cursor_execute", record)
        assert values == {notice_id: 1 for notice_id in ids[:size]}
        counts.append(len(statements))
    assert counts[0] == counts[1]
    assert counts[0] <= 2
    assert set(projection.notice_ids_with_open_blocking_items(session)) == set(ids)


def test_blocking_query_count_is_constant_beyond_selectinload_chunk_boundary(session):
    check_query_count(session)


@requires_postgres
def test_postgres_blocking_semantics_and_query_count():
    with migrated_engine() as engine, Session(engine) as session:
        check_blocking_semantics(session)
    with migrated_engine() as engine, Session(engine) as session:
        check_query_count(session)


def test_registration_adds_only_screening_workload_and_preserves_missing_scope(tmp_path):
    _, session, _, _, _ = _fixture(tmp_path, count=1)
    registry = ExtensionRegistry()
    register_lifecycle_extensions(registry)
    register_lifecycle_extensions(registry)
    try:
        # 완료된 누적 실행이 없으면 screening이 소유한 두 키가 같은 사유로 `null`이다.
        # 그 사유를 0으로 접지 않는다.
        absent = WorkloadCount(None, "no_completed_execution")
        assert registry.workload_counts(session) == {
            "order_plan_pending": absent, "order_plan_new_priority": absent,
        }
        from app.screening import ScreeningWorkloadProjection
        assert isinstance(ScreeningWorkloadProjection(), WorkloadProjection)
    finally:
        session.close()
        session.bind.dispose()


def test_order_plan_pending_reuses_the_cumulative_scope_and_tracking_filters(tmp_path):
    settings, session, policy, _, plans = _fixture(tmp_path, count=9)
    service = OrderPlanScreeningService(settings)
    registry = register_lifecycle_extensions(ExtensionRegistry())
    first = execution(session, service, policy)
    for index, plan in enumerate(plans[:8]):
        if index == 3:
            result(session, first, plan, stage1="filtered_out", stage2="not_attempted")
        elif index == 7:
            result(session, first, plan, stage2="unknown")
        else:
            result(session, first, plan, relevance="uncertain" if index == 1 else "not_relevant" if index == 2 else "relevant")
    for index, plan in enumerate(plans):
        if index == 5:
            continue
        if index == 1:
            owner(session, plan, link_type="candidate", status="사람 확인 완료", decision="accepted")
        elif index == 6:
            owner(session, plan, link_type="candidate", status="후보 확인 대기")
        else:
            owner(session, plan, tracking="계속 추적" if index == 4 else "미선택")
    feedback(session, first, plans[0], relevance="not_relevant")
    session.commit()
    try:
        # 관측 시각이 2026-09-02이라 "전일 이후 처음 관측"에는 아무도 들지 않는다.
        assert registry.workload_counts(session) == {
            "order_plan_pending": WorkloadCount(2), "order_plan_new_priority": WorkloadCount(0),
        }
        execution(session, service, policy, status="실패", minute=2)
        assert registry.workload_counts(session)["order_plan_pending"] == WorkloadCount(2)
        latest = execution(session, service, policy, status="부분 성공", minute=3)
        result(session, latest, plans[8])
        result(session, latest, plans[0], relevance="not_relevant")
        session.commit()
        # 누적 범위: plans[1]은 첫 실행의 판정으로 남고, plans[0]은 최신 실행의 not_relevant로 빠지며 plans[8]이 더해진다.
        assert registry.workload_counts(session)["order_plan_pending"] == WorkloadCount(2)
        listing = service.list_order_plans(session, stage1_status="selected", qwen_relevance="relevant,uncertain", tracking_status="미선택", limit=1)
        assert listing["scope"]["mode"] == "cumulative"
        assert listing["total"] == 2
        assert listing["items"][0]["order_plan_pk"] == plans[1].id
        execution(session, service, policy, minute=4)
        assert registry.workload_counts(session)["order_plan_pending"] == WorkloadCount(2)
    finally:
        session.close()
        session.bind.dispose()


def test_new_priority_window_starts_at_yesterday_in_seoul_and_narrows_to_relevant(tmp_path):
    """`order_plan_new_priority`와 `first_observed_from`의 경계·모집단.

    창의 하한은 요청 시각 KST 일자의 전일 00:00이고 상한은 없다. 그래서 전일 도착분과
    당일 도착분이 함께 들고, 1마이크로초 앞선 관측은 빠진다. 관련성 축은
    `relevant` 하나라 `order_plan_pending`(`relevant,uncertain`)과 다른 값이다.
    """

    settings, session, policy, _, plans = _fixture(tmp_path, count=5)
    service = OrderPlanScreeningService(settings)
    registry = register_lifecycle_extensions(ExtensionRegistry())
    first = execution(session, service, policy)
    seoul = ZoneInfo("Asia/Seoul")
    yesterday = datetime.now(UTC).astimezone(seoul).date() - timedelta(days=1)
    boundary = datetime.combine(yesterday, time.min, tzinfo=seoul).astimezone(UTC)
    moments = (
        boundary,                                # 정확히 하한 — 든다
        boundary - timedelta(microseconds=1),    # 1마이크로초 앞 — 빠진다
        boundary + timedelta(hours=30),          # 당일 도착분 — 든다
        boundary,                                # 추적 선택됨 — 빠진다
        boundary,                                # uncertain — 빠진다
    )
    for plan, observed in zip(plans, moments):
        for observation in plan.observations:
            observation.observed_at = observed
    for index, plan in enumerate(plans):
        result(session, first, plan, relevance="uncertain" if index == 4 else "relevant")
        owner(session, plan, tracking="계속 추적" if index == 3 else "미선택")
    session.commit()
    try:
        counts = registry.workload_counts(session)
        assert counts["order_plan_new_priority"] == WorkloadCount(2)
        # 같은 인자의 목록과 모집단이 같다.
        listing = service.list_order_plans(
            session, qwen_relevance="relevant", tracking_status="미선택",
            first_observed_from=yesterday, limit=100,
        )
        assert listing["total"] == 2
        assert [item["order_plan_pk"] for item in listing["items"]] == [plans[0].id, plans[2].id]
        # 넓은 키와 좁은 키는 서로 대신하지 않는다.
        assert counts["order_plan_pending"] == WorkloadCount(4)
        # 인자를 주지 않으면 창이 없다.
        assert service.list_order_plans(
            session, qwen_relevance="relevant", tracking_status="미선택", limit=1,
        )["total"] == 3
        # 회차 모드에서도 "처음 관측"은 회차와 무관한 최소 시각이다.
        assert service.list_order_plans(
            session, source_run_id="run-c2", qwen_relevance="relevant",
            tracking_status="미선택", first_observed_from=yesterday, limit=1,
        )["total"] == 2
        # 문자열 날짜를 받고, 날짜가 아닌 값은 422다.
        assert service.list_order_plans(
            session, first_observed_from=yesterday.isoformat(), limit=1,
        )["total"] == 4
        for invalid in ("not-a-date", datetime.now(UTC)):
            with pytest.raises(OrderPlanScreeningError) as error:
                service.list_order_plans(session, first_observed_from=invalid, limit=1)
            assert error.value.status_code == 422
    finally:
        session.close()
        session.bind.dispose()
