"""발주계획 목록의 실행 범위, SQL 필터와 추적 읽기 계약."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.lifecycle import ingest_run
from app.lifecycle.models import Opportunity, OpportunityLink, OrderPlan, OrderPlanObservation, Run
from app.screening.models import OrderPlanScreeningExecution, OrderPlanScreeningFeedback, OrderPlanScreeningResult
from app.screening.routers import order_plans as routes
from app.screening.services.order_plan_screening import OrderPlanScreeningService
from tests.c2_fixtures import write_c2_fixture
from tests.postgres import migrated_engine, requires_postgres
from tests.screening.test_order_plan_screening_service import _create, _fixture

NOW = datetime(2026, 9, 2, tzinfo=UTC)
UNICODE_SEARCH_CASES = (
    ("Straße 데이터 플랫폼 구축", "STRASSE"),
    ("ÜBERBLICK", "überblick"),
    ("ὈΔΥΣΣΕΎΣ", "ὀδυσσεύσ"),
    ("oﬃce", "OFFICE"),
    ("İstanbul", "i\u0307STANBUL"),
)


def execution(session, service, policy_version, *, status="성공", minute=1, source_run_id="run-c2", execution_id=None):
    response, _ = _create(service, session, policy_version)
    row = session.get(OrderPlanScreeningExecution, UUID(str(response["execution_id"])))
    row.status = status
    row.started_at = NOW
    row.finished_at = NOW + timedelta(minutes=minute)
    row.queued_at = NOW
    row.source_run_id = source_run_id
    row.partial_artifact = status != "성공"
    if execution_id is not None:
        row.execution_id = execution_id
    session.commit()
    return row


def result(session, execution, plan, *, stage1="selected", stage2="success", relevance="relevant", minute=1):
    selected = stage1 in {"selected", "filtered_out"}
    success = stage2 == "success"
    row = OrderPlanScreeningResult(
        id=uuid4(), execution_id=execution.execution_id, source_run_id=execution.source_run_id,
        order_plan_id=plan.id, schema_version="bidops.order-plan-screening-result-row.v1",
        producer="order-plan-screening-merge", consumer="postgres-loader-and-review-api",
        input_artifact_sha256="a" * 64, policy_version=execution.policy_version,
        policy_sha256="b" * 64, binding_sha256="c" * 64, result_sha256="d" * 64,
        stage1_status=stage1, stage1_rank=1 if selected else None,
        stage1_score=1 if selected else None, nearest_capability="데이터" if selected else None,
        stage2_status=stage2, qwen_relevance=relevance if success else None,
        qwen_score=.8 if success else None, qwen_reason="제목 근거" if success else None,
        batch_id="batch-1" if success else None, attempt_no=1 if success else None,
        failure_code="test_failure" if stage2 in {"failed", "rejected", "unknown"} else None,
        created_at=NOW + timedelta(minutes=minute),
    )
    session.add(row)
    session.flush()
    return row


def feedback(session, execution, plan, *, relevance="relevant", revision=1, minute=1):
    row = OrderPlanScreeningFeedback(
        feedback_id=uuid4(), execution_id=execution.execution_id, order_plan_id=plan.id,
        revision=revision, schema_version="bidops.order-plan-screening-feedback.v1",
        producer="human-review-api", consumer="postgres-review-history", actor_kind="human",
        claimed_name="reviewer", relevance=relevance, created_at=NOW + timedelta(minutes=minute),
    )
    session.add(row)
    session.flush()
    return row


def owner(session, plan, *, tracking="미선택", link_type="official", status="확정", decision=None, merged_into=None):
    opportunity = Opportunity(
        first_registered_stage="order_plan", tracking_status=tracking,
        tracking_reason="사람 선택" if tracking != "미선택" else None,
        tracking_selected_by="reviewer" if tracking != "미선택" else None,
        tracking_selected_at=NOW if tracking != "미선택" else None,
        merged_into_opportunity_id=merged_into,
        merged_at=NOW if merged_into else None, merge_reason="병합" if merged_into else None,
    )
    session.add(opportunity)
    session.flush()
    session.add(OpportunityLink(
        opportunity_id=opportunity.id, order_plan_id=plan.id, stage="order_plan",
        link_type=link_type, status=status, evidence_external_no=plan.order_plan_unty_no,
        human_decision=decision, reviewer_name="reviewer" if decision else None,
        reviewed_at=NOW if decision else None, review_reason="검토 근거" if decision else None,
    ))
    session.flush()
    return opportunity


@pytest.fixture
def listing(tmp_path: Path, monkeypatch):
    settings, session, policy_version, _, plans = _fixture(tmp_path, count=9)
    service = OrderPlanScreeningService(settings)
    monkeypatch.setattr(routes, "service", service)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as client:
        yield session, service, policy_version, plans, client
    session.close()
    session.bind.dispose()


def ids(response):
    assert response.status_code == 200, response.text
    return [item["order_plan_pk"] for item in response.json()["items"]]


def test_scope_is_one_completed_execution_and_never_borrows_results(listing):
    session, service, policy, plans, client = listing
    old = execution(session, service, policy)
    result(session, old, plans[0])
    feedback(session, old, plans[0])
    run = Run(id="other", timezone="Asia/Seoul", generated_at=NOW)
    session.add(run)
    session.add(OrderPlanObservation(order_plan_id=plans[1].id, run=run, observed_at=NOW))
    session.commit()
    latest = execution(session, service, policy, source_run_id="other", status="부분 성공", minute=2)
    result(session, latest, plans[1], relevance="uncertain")
    failed = execution(session, service, policy, status="실패", minute=3)
    result(session, failed, plans[0], stage2="failed", minute=3)
    stopped = execution(session, service, policy, status="중단됨", minute=4)
    result(session, stopped, plans[2], stage2="unknown", minute=4)
    feedback(session, stopped, plans[0], relevance="not_relevant", minute=4)
    session.commit()
    body = client.get("/api/order-plans").json()
    assert body["schema_version"] == "order-plan-list-response.v2"
    assert body["scope"] == {"execution_id": str(latest.execution_id), "source_run_id": "other", "status": "부분 성공", "finished_at": "2026-09-02T00:02:00Z"}
    assert len(body["items"]) == 9
    assert body["items"][0]["stage1_status"] is None
    assert body["items"][0]["stage2_status"] is None
    assert body["items"][0]["qwen_relevance"] is None
    assert body["items"][0]["human_feedback"] is None
    assert body["items"][1]["qwen_relevance"] == "uncertain"
    scoped = client.get("/api/order-plans", params={"source_run_id": "run-c2"}).json()
    assert scoped["scope"]["execution_id"] == str(old.execution_id)
    assert scoped["items"][0]["human_feedback"]["relevance"] == "relevant"
    assert scoped["items"][1]["stage2_status"] is None


def test_no_completed_execution_keeps_original_items_with_null_scope(listing):
    session, service, policy, plans, client = listing
    failed = execution(session, service, policy, status="실패")
    result(session, failed, plans[0], stage2="failed")
    feedback(session, failed, plans[0])
    session.commit()
    for params in ({}, {"source_run_id": "run-c2"}):
        response = client.get("/api/order-plans", params=params)
        assert len(ids(response)) == 9
        assert response.json()["scope"] is None
        assert all(item["stage1_status"] is None and item["human_feedback"] is None for item in response.json()["items"])


def test_multi_value_filters_missing_and_issue_are_independent_axes(listing):
    session, service, policy, plans, client = listing
    chosen = execution(session, service, policy, status="부분 성공")
    states = [("selected", "success", "relevant"), ("selected", "success", "uncertain"),
              ("filtered_out", "not_attempted", None), ("selected", "unknown", None),
              ("failed", "not_attempted", None), ("selected", "failed", None),
              ("rejected", "not_attempted", None), ("selected", "rejected", None)]
    for plan, (first, second, relevance) in zip(plans, states):
        result(session, chosen, plan, stage1=first, stage2=second, relevance=relevance)
    feedback(session, chosen, plans[0], relevance="not_relevant")
    feedback(session, chosen, plans[0], relevance="relevant", revision=2, minute=2)
    feedback(session, chosen, plans[1], relevance="uncertain")
    owner(session, plans[0], tracking="계속 추적")
    owner(session, plans[1], tracking="보류")
    session.commit()
    cases = [
        ({"stage1_status": "missing"}, [8]),
        ({"stage2_status": "missing"}, [8]),
        ({"stage2_status": "unknown"}, [3]),
        ({"stage2_status": "not_attempted"}, [2, 4, 6]),
        ({"qwen_relevance": "missing"}, [2, 3, 4, 5, 6, 7, 8]),
        ({"stage1_status": "selected,missing", "stage2_status": "success,missing"}, [0, 1, 8]),
        ({"human_relevance": "relevant,uncertain", "qwen_relevance": "relevant,uncertain", "tracking_status": "계속 추적,보류"}, [0, 1]),
        ({"human_relevance": "missing,uncertain"}, [1, 2, 3, 4, 5, 6, 7, 8]),
        ({"human_relevance": "not_relevant"}, []),
        ({"issue": "true"}, [4, 5, 6, 7]),
        ({"issue": "true", "stage1_status": "selected"}, [5, 7]),
        ({"issue": "true", "stage2_status": "not_attempted"}, [4, 6]),
        ({"issue": "false"}, list(range(9))),
    ]
    for params, expected in cases:
        assert ids(client.get("/api/order-plans", params=params)) == [plans[index].id for index in expected], params
    page = client.get("/api/order-plans", params={"issue": "true", "limit": 2, "offset": 1})
    assert ids(page) == [plans[5].id, plans[6].id]
    assert page.json()["total"] == 4
    assert client.get("/api/order-plans", params={"issue": "true", "offset": 99}).json()["total"] == 4


def test_tracking_only_projects_active_authoritative_owner(listing):
    session, _, _, plans, client = listing
    official = owner(session, plans[0], tracking="계속 추적")
    accepted = owner(session, plans[1], tracking="보류", link_type="candidate", status="사람 확인 완료", decision="accepted")
    owner(session, plans[0], tracking="종료", link_type="candidate", status="후보 확인 대기")
    owner(session, plans[0], tracking="보류", link_type="candidate", status="사람 확인 완료", decision="rejected")
    owner(session, plans[2], tracking="종료", link_type="candidate", status="사람 확인 완료", decision="rejected")
    owner(session, plans[3], link_type="candidate", status="후보 확인 대기")
    owner(session, plans[4], merged_into=official.id)
    unselected = owner(session, plans[5])
    owner(session, plans[6], tracking="종료")
    session.commit()
    body = client.get("/api/order-plans").json()
    assert body["total"] == 9 and len(body["items"]) == 9
    rows = body["items"]
    assert rows[0]["tracking"] == {"opportunity_id": official.id, "tracking_status": "계속 추적", "tracking_reason": "사람 선택", "tracking_selected_by": "reviewer", "tracking_selected_at": "2026-09-02T00:00:00Z"}
    assert rows[1]["tracking"]["opportunity_id"] == accepted.id
    assert rows[5]["tracking"]["opportunity_id"] == unselected.id
    assert all(rows[index]["tracking"] is None for index in (2, 3, 4, 7, 8))
    assert ids(client.get("/api/order-plans", params={"tracking_status": "미선택"})) == [plans[5].id]
    assert ids(client.get("/api/order-plans", params={"tracking_status": "미선택,계속 추적,보류,종료"})) == [plans[index].id for index in (0, 1, 5, 6)]
    for index in range(9):
        detail = client.get(f"/api/order-plans/{plans[index].id}")
        assert detail.status_code == 200
        assert detail.json()["schema_version"] == "order-plan-detail-response.v2"
        assert detail.json()["tracking"] == rows[index]["tracking"]
        assert "inherited_from_order_plan" not in str(detail.json())
    assert client.get("/api/order-plans/99999").status_code == 404


@pytest.mark.parametrize("parameter,value", [("stage1_status", "unknown"), ("stage1_status", "selected,bogus"), ("stage2_status", "missing,invalid"), ("qwen_relevance", "success"), ("human_relevance", "unknown"), ("tracking_status", "missing"), ("tracking_status", "계속 추적,잘못됨"), ("issue", "invalid"), ("stage1_status", ""), ("stage1_status", "selected,")])
def test_invalid_filters_return_422(listing, parameter, value):
    assert listing[-1].get("/api/order-plans", params={parameter: value}).status_code == 422


def test_search_escapes_sql_wildcards_and_paginates_in_sql(listing):
    session, _, _, plans, client = listing
    plans[0].title = "AI 데이터 100%_정확"
    plans[1].title = "AI 데이터 1000X정확"
    session.commit()
    assert ids(client.get("/api/order-plans", params={"q": "%_"})) == [plans[0].id]
    assert ids(client.get("/api/order-plans", params={"q": " ai "})) == [plans[0].id, plans[1].id]
    assert ids(client.get("/api/order-plans", params={"q": "p-3"})) == [plans[2].id]
    statements = []
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        response = client.get("/api/order-plans", params={"q": "데이터", "limit": 2, "offset": 2})
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert ids(response) == [plans[2].id, plans[3].id]
    assert response.json()["total"] == 9
    item_queries = [sql for sql in statements if "order_plan.title" in sql and "count(" not in sql.lower()]
    assert len(item_queries) == 1
    assert "LIMIT" in item_queries[0] and "OFFSET" in item_queries[0]


@pytest.mark.parametrize("title,query", UNICODE_SEARCH_CASES)
def test_search_preserves_unicode_casefold_with_sql_total_and_page(listing, title, query):
    session, _, _, plans, client = listing
    plans[0].title = title
    plans[1].title = title
    session.commit()
    response = client.get("/api/order-plans", params={"q": query, "limit": 1, "offset": 1})
    assert ids(response) == [plans[1].id]
    assert response.json()["total"] == 2


def test_query_count_does_not_grow_with_population(tmp_path):
    counts = []
    for size in (9, 21):
        settings, session, policy, _, plans = _fixture(tmp_path / str(size), count=size)
        service = OrderPlanScreeningService(settings)
        chosen = execution(session, service, policy)
        for plan in plans:
            result(session, chosen, plan)
            feedback(session, chosen, plan)
            owner(session, plan)
        session.commit()
        session.expunge_all()
        statements = []
        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        event.listen(session.bind, "before_cursor_execute", capture)
        try:
            response = service.list_order_plans(session)
        finally:
            event.remove(session.bind, "before_cursor_execute", capture)
            session.close()
            session.bind.dispose()
        assert len(response["items"]) == size
        counts.append(len(statements))
    assert counts[0] == counts[1]
    assert counts[0] <= 5


def test_scope_ordering_uses_finished_then_queued_then_execution_id(listing):
    session, service, policy, _, client = listing
    first = execution(session, service, policy, minute=2, execution_id=UUID(int=1))
    by_queue = execution(session, service, policy, minute=2, execution_id=UUID(int=2))
    by_queue.queued_at = NOW + timedelta(seconds=1)
    by_id = execution(session, service, policy, minute=2, execution_id=UUID(int=3))
    by_id.queued_at = by_queue.queued_at
    older = execution(session, service, policy, minute=1, execution_id=UUID(int=4))
    older.queued_at = NOW + timedelta(seconds=2)
    session.commit()
    for params in ({}, {"source_run_id": "run-c2"}):
        assert client.get("/api/order-plans", params=params).json()["scope"]["execution_id"] == str(by_id.execution_id)
    assert first.execution_id != by_id.execution_id


@requires_postgres
def test_postgres_list_filters_pagination_and_tracking_projection(tmp_path, screening_extensions):
    with migrated_engine() as engine, Session(engine) as session:
        run_dir, source_run_id = write_c2_fixture(tmp_path)
        session.add(Run(id=source_run_id, timezone="Asia/Seoul", generated_at=NOW))
        session.commit()
        ingest_run(run_dir, session)
        plan = session.scalar(select(OrderPlan))
        unreviewed = OrderPlan(order_plan_unty_no="P-no-result", title="아직 결과 없는 계획")
        session.add(unreviewed)
        session.flush()
        session.add(OrderPlanObservation(order_plan_id=unreviewed.id, run_id=source_run_id, observed_at=NOW))
        owners = session.scalars(select(OpportunityLink).where(OpportunityLink.order_plan_id == plan.id)).all()
        if not owners:
            owner(session, plan)
        session.commit()
        service = OrderPlanScreeningService()
        listing = service.list_order_plans(session, source_run_id=source_run_id, qwen_relevance="relevant", human_relevance="missing", tracking_status="미선택", q="데이터", limit=1)
        assert listing["scope"]["source_run_id"] == source_run_id
        assert listing["total"] == 1
        assert listing["items"][0]["order_plan_pk"] == plan.id
        assert listing["items"][0]["tracking"]["tracking_status"] == "미선택"
        missing = service.list_order_plans(session, stage1_status="missing", stage2_status="missing", qwen_relevance="missing")
        assert [row["order_plan_pk"] for row in missing["items"]] == [unreviewed.id]
        assert service.list_order_plans(session, issue=True)["total"] == 0
        beyond = service.list_order_plans(session, limit=1, offset=5)
        assert beyond["total"] == 2 and beyond["items"] == []

        for title, query in UNICODE_SEARCH_CASES:
            first = OrderPlan(order_plan_unty_no=str(uuid4()), title=title)
            second = OrderPlan(order_plan_unty_no=str(uuid4()), title=title)
            session.add_all([first, second])
            session.flush()
            for added in (first, second):
                session.add(OrderPlanObservation(order_plan_id=added.id, run_id=source_run_id, observed_at=NOW))
            session.commit()
            searched = service.list_order_plans(session, q=query, limit=1, offset=1)
            assert searched["total"] == 2
            assert [item["order_plan_pk"] for item in searched["items"]] == [second.id]
