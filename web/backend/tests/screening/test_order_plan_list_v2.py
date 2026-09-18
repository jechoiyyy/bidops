"""발주계획 목록의 실행 범위, SQL 필터와 추적 읽기 계약."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.lifecycle import WorkloadCount
from app.lifecycle import ingest_run
from app.lifecycle.models import Opportunity, OpportunityLink, OrderPlan, OrderPlanObservation, Run
from app.screening.models import (
    OrderPlanScreeningExecution,
    OrderPlanScreeningFeedback,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningResult,
)
from app.screening.projection import ScreeningWorkloadProjection
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


def test_cumulative_mode_projects_latest_result_per_plan_and_run_mode_narrows(listing):
    session, service, policy, plans, client = listing
    plans[0].source_url = "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=P-0"
    session.commit()
    old = execution(session, service, policy)
    result(session, old, plans[0])
    feedback(session, old, plans[0])
    run = Run(id="other", timezone="Asia/Seoul", generated_at=NOW)
    session.add(run)
    session.add(OrderPlanObservation(order_plan_id=plans[1].id, run=run, observed_at=NOW + timedelta(days=1)))
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
    assert body["schema_version"] == "order-plan-list-response.v4"
    assert body["scope"] == {"mode": "cumulative", "policy_versions": [policy]}
    assert len(body["items"]) == 9
    first, second, third = body["items"][:3]
    # 완료되지 않은 실행의 결과는 빌리지 않고, feedback은 실행과 무관하게 발주계획별 최신 1건이다.
    assert (first["qwen_relevance"], first["execution_id"], first["policy_version"]) == ("relevant", str(old.execution_id), policy)
    assert first["human_feedback"]["relevance"] == "not_relevant"
    assert first["source_url"] == "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=P-0"
    assert (second["qwen_relevance"], second["execution_id"]) == ("uncertain", str(latest.execution_id))
    assert second["source_run_id"] == "other"
    assert second["observed_at"] == "2026-09-03T00:00:00Z"
    assert second["first_observed_at"] == "2026-09-02T00:00:00Z"
    assert third["stage2_status"] is None and third["execution_id"] is None and third["policy_version"] is None
    scoped = client.get("/api/order-plans", params={"source_run_id": "run-c2"}).json()
    assert scoped["scope"] == {
        "mode": "run", "execution_id": str(old.execution_id), "source_run_id": "run-c2", "status": "성공",
        "finished_at": "2026-09-02T00:01:00Z", "policy_version": policy, "purpose": "operational",
    }
    assert scoped["items"][0]["qwen_relevance"] == "relevant"
    assert scoped["items"][0]["human_feedback"]["relevance"] == "not_relevant"
    assert scoped["items"][1]["stage2_status"] is None
    other = client.get("/api/order-plans", params={"source_run_id": "other"}).json()
    assert [item["order_plan_pk"] for item in other["items"]] == [plans[1].id]
    assert other["items"][0]["first_observed_at"] == "2026-09-02T00:00:00Z"


def test_no_completed_execution_keeps_original_items(listing):
    session, service, policy, plans, client = listing
    failed = execution(session, service, policy, status="실패")
    result(session, failed, plans[0], stage2="failed")
    feedback(session, failed, plans[0])
    session.commit()
    cumulative = client.get("/api/order-plans")
    assert len(ids(cumulative)) == 9
    assert cumulative.json()["scope"] == {"mode": "cumulative", "policy_versions": [policy]}
    run = client.get("/api/order-plans", params={"source_run_id": "run-c2"})
    assert len(ids(run)) == 9
    assert run.json()["scope"] is None
    for response in (cumulative, run):
        items = response.json()["items"]
        assert all(item["stage1_status"] is None and item["execution_id"] is None for item in items)
        # feedback은 실행과 무관한 발주계획별 최신 1건이다.
        assert items[0]["human_feedback"]["relevance"] == "relevant"
        assert all(item["human_feedback"] is None for item in items[1:])


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
        assert detail.json()["schema_version"] == "order-plan-detail-response.v3"
        assert detail.json()["source_url"] == plans[index].source_url
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


def test_selection_review_order_plan_pk_sort_and_pagination_keep_all_501_source_rows(
    tmp_path, monkeypatch,
):
    """The API keeps source PK ASC and exposes every row over a 500-page split."""

    settings, session, _policy, _binding, plans = _fixture(
        tmp_path / "selection-review-501", count=501
    )
    service = OrderPlanScreeningService(settings)
    monkeypatch.setattr(routes, "service", service)
    application = FastAPI()
    application.include_router(routes.router)
    application.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(application) as client:
            first_response = client.get("/api/order-plans", params={"limit": 500, "offset": 0})
            second_response = client.get("/api/order-plans", params={"limit": 500, "offset": 500})

        expected_ids = [plan.id for plan in plans]
        assert first_response.status_code == second_response.status_code == 200
        first = first_response.json()
        second = second_response.json()
        assert first["schema_version"] == "order-plan-list-response.v4"
        assert first["total"] == second["total"] == 501
        assert first["limit"] == second["limit"] == 500
        assert first["offset"] == 0
        assert second["offset"] == 500
        assert [item["order_plan_pk"] for item in first["items"]] == expected_ids[:500]
        assert [item["order_plan_pk"] for item in second["items"]] == expected_ids[500:]
        assert len(first["items"]) == 500
        assert len(second["items"]) == 1
        assert [item["order_plan_pk"] for item in first["items"] + second["items"]] == expected_ids
    finally:
        application.dependency_overrides.clear()
        session.close()
        session.bind.dispose()


def test_scope_ordering_uses_finished_then_execution_id(listing):
    session, service, policy, plans, client = listing
    first = execution(session, service, policy, minute=2, execution_id=UUID(int=1))
    by_queue = execution(session, service, policy, minute=2, execution_id=UUID(int=2))
    by_queue.queued_at = NOW + timedelta(seconds=1)
    by_id = execution(session, service, policy, minute=2, execution_id=UUID(int=3))
    by_id.queued_at = by_queue.queued_at
    older = execution(session, service, policy, minute=1, execution_id=UUID(int=4))
    older.queued_at = NOW + timedelta(seconds=2)
    result(session, first, plans[0], relevance="not_relevant")
    result(session, by_queue, plans[0], relevance="not_relevant")
    result(session, by_id, plans[0], relevance="uncertain")
    result(session, older, plans[0], relevance="not_relevant")
    session.commit()
    assert client.get("/api/order-plans", params={"source_run_id": "run-c2"}).json()["scope"]["execution_id"] == str(by_id.execution_id)
    item = client.get("/api/order-plans").json()["items"][0]
    assert (item["execution_id"], item["qwen_relevance"]) == (str(by_id.execution_id), "uncertain")
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
        missing = service.list_order_plans(session, source_run_id=source_run_id, stage1_status="missing", stage2_status="missing", qwen_relevance="missing")
        assert [row["order_plan_pk"] for row in missing["items"]] == [unreviewed.id]
        # 적재 fixture의 policy는 활성화된 적 없는 참조 policy라 누적 모드에는 결과가 없다.
        cumulative = service.list_order_plans(session, stage1_status="missing", stage2_status="missing", qwen_relevance="missing")
        assert cumulative["scope"] == {"mode": "cumulative", "policy_versions": []}
        assert [row["order_plan_pk"] for row in cumulative["items"]] == [plan.id, unreviewed.id]
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


DAY = timedelta(days=1)


def policy_row(session, version, status, activated_at=None):
    session.add(OrderPlanScreeningPolicy(
        id=uuid4(), policy_version=version, schema_version="bidops.order-plan-screening-policy.v1",
        producer="phase0-contracts", consumer="phase1-screening-pipeline", policy_status=status,
        decision_scope="c2_order_plan_first_pass", policy_payload_jsonb={}, binding_payload_jsonb={},
        policy_sha256="a" * 64, binding_sha256="b" * 64, activation_metadata_jsonb={},
        quality_gate_status="passed" if activated_at is not None else None,
        active_slot=1 if status == "active" else None, created_by="fixture", created_at=NOW,
        activated_by="approver" if activated_at is not None else None, activated_at=activated_at,
    ))
    session.flush()


def direct_execution(session, version, run_id, finished_at, *, status="성공", purpose="operational"):
    row = OrderPlanScreeningExecution(
        execution_id=uuid4(), request_id=uuid4(), schema_version="bidops.order-plan-screening-execution-row.v1",
        producer="screening-api", consumer="screening-worker-and-review-api", source_run_id=run_id,
        source_artifact_name="collected-order-plans.json", source_artifact_schema_version="bidops.collected-order-plans.v1",
        source_artifact_sha256="a" * 64, input_artifact_sha256="a" * 64, population_count=1, population_sha256="a" * 64,
        policy_version=version, policy_sha256="a" * 64, binding_sha256="b" * 64,
        stage1_binding_version="fixture", stage1_binding_sha256="c" * 64,
        stage2_binding_version="fixture", stage2_binding_sha256="d" * 64,
        status=status, requested_by="fixture", partial_artifact=status != "성공",
        queued_at=finished_at - timedelta(minutes=5), started_at=finished_at - timedelta(minutes=4),
        finished_at=finished_at, created_at=finished_at - timedelta(minutes=5), purpose=purpose,
    )
    session.add(row)
    session.flush()
    return row


def check_cumulative_projection(session):
    """어제·오늘 실행, policy 교체, 참조·측정 실행, 회차 선택, 실행 없는 날의 워크로드를 한 흐름으로 확인한다."""
    service = OrderPlanScreeningService()
    workload = ScreeningWorkloadProjection()
    runs = {name: Run(id=f"s8a-{name}", timezone="Asia/Seoul", generated_at=NOW) for name in ("day1", "day2", "ref", "gate")}
    session.add_all(runs.values())
    # v3은 어제 쓰이고 retire됐고 v4가 오늘 active다. 참조 policy는 한 번도 활성화된 적이 없다.
    policy_row(session, "s8a-v3", "retired", NOW)
    policy_row(session, "s8a-v4", "active", NOW + DAY)
    policy_row(session, "s8a-ref", "draft")
    plans = [OrderPlan(order_plan_unty_no=f"S8A-{index}", title=f"누적 투영 {index}") for index in range(4)]
    session.add_all(plans)
    session.flush()
    a, b, c, d = plans
    for plan, run, when in ((a, "day1", NOW), (a, "day2", NOW + DAY), (b, "gate", NOW - DAY), (b, "day2", NOW + DAY),
                            (c, "day1", NOW), (d, "ref", NOW)):
        session.add(OrderPlanObservation(order_plan_id=plan.id, run_id=runs[run].id, observed_at=when))
    owner(session, a)
    owner(session, b)
    reference = direct_execution(session, "s8a-ref", runs["ref"].id, NOW + 3 * DAY)
    result(session, reference, a, relevance="not_relevant")
    result(session, reference, d)
    gate = direct_execution(session, "s8a-v4", runs["gate"].id, NOW + 3 * DAY, purpose="gate_measurement")
    result(session, gate, b, relevance="not_relevant")
    session.commit()

    # 참조·측정 실행만 있으면 누적 범위가 비어 있고 워크로드는 null이다.
    empty = service.list_order_plans(session)
    assert empty["scope"] == {"mode": "cumulative", "policy_versions": ["s8a-v3", "s8a-v4"]}
    assert all(item["execution_id"] is None for item in empty["items"])
    assert workload.workload_counts(session) == {"order_plan_pending": WorkloadCount(None, "no_completed_execution")}

    yesterday = direct_execution(session, "s8a-v3", runs["day1"].id, NOW + timedelta(hours=1))
    result(session, yesterday, a)
    result(session, yesterday, c, relevance="not_relevant")
    feedback(session, yesterday, a, relevance="relevant")
    today = direct_execution(session, "s8a-v4", runs["day2"].id, NOW + DAY + timedelta(hours=1), status="부분 성공")
    result(session, today, a, relevance="uncertain")
    result(session, today, b)
    direct_execution(session, "s8a-v4", runs["day2"].id, NOW + 2 * DAY, status="실패")
    session.commit()

    listing = service.list_order_plans(session)
    assert listing["schema_version"] == "order-plan-list-response.v4"
    assert listing["scope"] == {"mode": "cumulative", "policy_versions": ["s8a-v3", "s8a-v4"]}
    rows = {item["order_plan_pk"]: item for item in listing["items"]}
    assert listing["total"] == 4
    # 오늘 실행의 판정과 어제 실행의 feedback이 같은 행에 함께 실린다.
    assert (rows[a.id]["execution_id"], rows[a.id]["policy_version"], rows[a.id]["qwen_relevance"]) == (today.execution_id, "s8a-v4", "uncertain")
    assert rows[a.id]["human_feedback"]["relevance"] == "relevant"
    assert rows[a.id]["source_run_id"] == runs["day2"].id
    assert rows[a.id]["first_observed_at"] == NOW
    assert rows[a.id]["observed_at"] == NOW + DAY
    assert (rows[b.id]["execution_id"], rows[b.id]["qwen_relevance"]) == (today.execution_id, "relevant")
    assert rows[b.id]["first_observed_at"] == NOW - DAY
    # retire된 v3의 판정이 누적에 남는다.
    assert (rows[c.id]["execution_id"], rows[c.id]["policy_version"], rows[c.id]["qwen_relevance"]) == (yesterday.execution_id, "s8a-v3", "not_relevant")
    # 참조 실행의 판정은 누적에 없다.
    assert rows[d.id]["execution_id"] is None and rows[d.id]["policy_version"] is None and rows[d.id]["qwen_relevance"] is None

    def pks(**params):
        return [item["order_plan_pk"] for item in service.list_order_plans(session, **params)["items"]]

    assert pks(qwen_relevance="relevant") == [b.id]
    assert pks(qwen_relevance="missing") == [d.id]
    assert pks(human_relevance="relevant") == [a.id]
    assert pks(stage1_status="selected", qwen_relevance="relevant,uncertain", tracking_status="미선택") == [a.id, b.id]
    page = service.list_order_plans(session, limit=1, offset=1)
    assert page["total"] == 4 and [item["order_plan_pk"] for item in page["items"]] == [b.id]

    # 회차 모드는 policy·purpose를 묻지 않고 그 회차의 최신 완료 실행 하나만 보인다.
    audit = service.list_order_plans(session, source_run_id=runs["ref"].id)
    assert audit["scope"]["mode"] == "run"
    assert (audit["scope"]["execution_id"], audit["scope"]["policy_version"], audit["scope"]["purpose"]) == (reference.execution_id, "s8a-ref", "operational")
    assert [(item["order_plan_pk"], item["qwen_relevance"], item["policy_version"]) for item in audit["items"]] == [(d.id, "relevant", "s8a-ref")]
    measured = service.list_order_plans(session, source_run_id=runs["gate"].id)
    assert (measured["scope"]["execution_id"], measured["scope"]["purpose"]) == (gate.execution_id, "gate_measurement")
    assert [(item["order_plan_pk"], item["qwen_relevance"]) for item in measured["items"]] == [(b.id, "not_relevant")]
    assert measured["items"][0]["observed_at"] == NOW - DAY
    day1 = service.list_order_plans(session, source_run_id=runs["day1"].id)
    assert day1["scope"]["execution_id"] == yesterday.execution_id
    assert [(item["order_plan_pk"], item["qwen_relevance"]) for item in day1["items"]] == [(a.id, "relevant"), (c.id, "not_relevant")]
    assert day1["items"][0]["first_observed_at"] == NOW

    # 워크로드는 누적 범위로 센다. 오늘 새 실행이 없어도(마지막 실행이 실패여도) null이 되지 않는다.
    assert workload.workload_counts(session) == {"order_plan_pending": WorkloadCount(2)}


def test_cumulative_projection_keeps_retired_policy_results_and_excludes_reference_and_gate(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            check_cumulative_projection(session)
    finally:
        engine.dispose()


@requires_postgres
def test_postgres_cumulative_projection(screening_extensions):
    with migrated_engine() as engine, Session(engine) as session:
        check_cumulative_projection(session)
