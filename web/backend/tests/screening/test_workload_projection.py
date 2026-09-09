"""미답변 blocking 항목과 발주계획 검토 대기의 실제 screening 제공자."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle import ExtensionRegistry, WorkloadCount, WorkloadProjection
from app.lifecycle.models import Notice, Run
from app.screening import ScreeningJudgmentProjection, register_lifecycle_extensions
from app.screening.models import Judgment, Review, VerificationAnswer, VerificationItem
from app.screening.services.order_plan_screening import OrderPlanScreeningService
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
        assert registry.workload_counts(session) == {"order_plan_pending": WorkloadCount(None, "no_completed_execution")}
        from app.screening import ScreeningWorkloadProjection
        assert isinstance(ScreeningWorkloadProjection(), WorkloadProjection)
    finally:
        session.close()
        session.bind.dispose()


def test_order_plan_pending_reuses_the_latest_completed_scope_and_tracking_filters(tmp_path):
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
        assert registry.workload_counts(session) == {"order_plan_pending": WorkloadCount(2)}
        execution(session, service, policy, status="실패", minute=2)
        assert registry.workload_counts(session)["order_plan_pending"] == WorkloadCount(2)
        latest = execution(session, service, policy, status="부분 성공", minute=3)
        result(session, latest, plans[8])
        session.commit()
        assert registry.workload_counts(session)["order_plan_pending"] == WorkloadCount(1)
        listing = service.list_order_plans(session, stage1_status="selected", qwen_relevance="relevant,uncertain", tracking_status="미선택", limit=1)
        assert listing["scope"]["execution_id"] == latest.execution_id
        assert listing["total"] == 1
        execution(session, service, policy, minute=4)
        assert registry.workload_counts(session)["order_plan_pending"] == WorkloadCount(0)
    finally:
        session.close()
        session.bind.dispose()
