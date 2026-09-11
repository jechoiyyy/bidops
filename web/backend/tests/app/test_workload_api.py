"""조립된 업무 제공자와 PostgreSQL 목록의 workload 계약을 대조한다."""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core import get_db
from app.lifecycle import WorkloadCount
from app.lifecycle.models import Notice, Opportunity, OpportunityLink, OrderPlan, OrderPlanObservation, Run
from app.main import create_app
from app.screening import ScreeningWorkloadProjection
from app.deep_review.services.prespec_projection import DeepReviewWorkloadProjection
from app.screening.models import Judgment, OrderPlanScreeningExecution, OrderPlanScreeningPolicy, VerificationItem
from app.deep_review.models import (
    ContentObject,
    DocumentBundle,
    DocumentVersion,
    PrespecOverviewRun,
    WorkJob,
)
from tests.postgres import migrated_engine, requires_postgres
from tests.screening.test_order_plan_list_v2 import owner, result
from tests.deep_review.decision_queue_fixtures import comparison, decide, opportunity

NOW = datetime(2026, 9, 7, tzinfo=UTC)
KEYS = ("order_plan_pending", "pre_spec_deep_review_ready", "tracking_action_required", "bid_final_decision_pending")
COMBINATIONS = (("lifecycle",), ("lifecycle", "screening"), ("lifecycle", "screening", "deep_review"))
pytestmark = requires_postgres


@pytest.fixture(scope="module")
def workload_engine():
    with migrated_engine() as engine:
        yield engine


@pytest.fixture
def workload_session(workload_engine):
    with workload_engine.connect() as connection, connection.begin():
        with Session(connection, expire_on_commit=False) as session:
            yield session
            session.rollback()


@contextmanager
def client_for(session, modules):
    application = create_app(modules=modules, mount_frontend=False)
    application.dependency_overrides[get_db] = lambda: session
    with TestClient(application) as client:
        yield client


def get_json(client, path, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def workload(client):
    before = datetime.now(UTC)
    body = get_json(client, "/api/workload")
    assert set(body) == {"generated_at", "items"}
    generated = datetime.fromisoformat(body["generated_at"].replace("Z", "+00:00"))
    assert generated.utcoffset() == timedelta(0)
    assert before <= generated <= datetime.now(UTC)
    assert [item["key"] for item in body["items"]] == list(KEYS)
    assert all(set(item) == {"key", "count", "unavailable_reason"} for item in body["items"])
    return {item["key"]: (item["count"], item["unavailable_reason"]) for item in body["items"]}


@pytest.mark.parametrize("modules", COMBINATIONS)
def test_workload_empty_module_combinations(workload_session, empty_extensions, modules):
    with client_for(workload_session, modules) as client:
        expected = dict.fromkeys(KEYS, (None, "provider_absent"))
        expected["tracking_action_required"] = (0, None)
        if "screening" in modules:
            expected["order_plan_pending"] = (None, "no_completed_execution")
        if "deep_review" in modules:
            expected["pre_spec_deep_review_ready"] = (0, None)
            expected["bid_final_decision_pending"] = (0, None)
        assert workload(client) == expected


@pytest.mark.parametrize("provided", [WorkloadCount(None), WorkloadCount(None, "fixture_unavailable"), WorkloadCount(0, "fixture_reason"), WorkloadCount(7)])
def test_workload_calls_each_provider_once_and_preserves_values(workload_session, empty_extensions, provided):
    calls = []
    class Provider:
        def __init__(self, name, counts):
            self.name, self.counts = name, counts
        def workload_counts(self, session):
            assert session is workload_session
            calls.append(self.name)
            return self.counts
    with client_for(workload_session, ("lifecycle",)) as client:
        empty_extensions.register_workload_projection(Provider("first", {KEYS[0]: provided}), owner="first")
        empty_extensions.register_workload_projection(Provider("second", {KEYS[1]: WorkloadCount(0), KEYS[3]: WorkloadCount(None, "fixture_pending")}), owner="second")
        for request_number in (1, 2):
            assert workload(client) == {
                KEYS[0]: (provided.count, provided.unavailable_reason), KEYS[1]: (0, None),
                KEYS[2]: (0, None), KEYS[3]: (None, "fixture_pending"),
            }
            assert calls == ["first", "second"] * request_number


def add_notice(session, kind, *, sw=None):
    row = Notice(notice_key=f"workload:{uuid4()}", source_type=kind, published_at=NOW,
        qualification_flags_json={"sw_business_status": sw} if sw else None)
    session.add(row)
    session.flush()
    return row


def link_notice(session, owned, notice, *, status="확정", kind="official"):
    row = OpportunityLink(opportunity_id=owned.id, notice_id=notice.id if notice else None,
        stage="notice", link_type=kind, status=status,
        evidence_external_no=notice.notice_key if notice and kind == "official" else None)
    session.add(row)
    session.flush()
    return row


def add_overview_run(session, notice, status):
    """종결된 개요 run 한 건과 그 실행 job·문서를 최소한으로 세운다."""

    content = ContentObject(sha256=f"{notice.id:064d}", size_bytes=1,
                            detected_mime="application/pdf", retention_class="document-source")
    session.add(content)
    session.flush()
    document = DocumentVersion(notice_id=notice.id, content_object_id=content.id, version=1,
                               source_kind="manual", original_filename="제안요청서.pdf", role="제안요청서",
                               is_current=True, safety_status="safe")
    job = WorkJob(job_type="prespec_overview", aggregate_type="prespec_overview_run",
                  aggregate_id=uuid4(), status="completed")
    session.add_all([document, job])
    session.flush()
    session.add(PrespecOverviewRun(
        notice_id=notice.id, document_version_id=document.id, work_job_id=job.id, status=status,
        range_source="auto", range_reason_codes=[], policy_digest="0" * 64, model_name="test-model",
        warnings_json=[], reason_codes=[], call_count=0, raw_response_refs=[],
    ))
    session.flush()


def add_prespec(session, sw, *, tracking=None):
    row = add_notice(session, "pre_spec", sw=sw)
    session.add(DocumentBundle(notice_id=row.id, revision=1, version=1, status="ready", issues_snapshot=[]))
    session.flush()
    add_overview_run(session, row, "failed")
    if tracking:
        link_notice(session, opportunity(session, tracking=tracking), row)
    session.flush()
    return row


def seed_sections(session):
    first = Opportunity(first_registered_stage="bid_notice")
    ordinary = Opportunity(first_registered_stage="order_plan")
    session.add_all([first, ordinary])
    session.flush()
    ended = opportunity(session, tracking="종료")
    recheck_link = link_notice(session, ended, add_notice(session, "bid_notice"))
    ended.recheck_signal_at, ended.recheck_signal_link_id = NOW, recheck_link.id
    pending = opportunity(session, tracking="보류")
    link_notice(session, pending, add_notice(session, "pre_spec"), status="후보 확인 대기", kind="candidate")
    searched = opportunity(session, tracking="미선택")
    link_notice(session, searched, None, status="검색 미확인", kind="candidate")
    blocked = opportunity(session, tracking="미선택")
    notice = add_notice(session, "pre_spec")
    run = Run(id=f"workload:{uuid4()}", generated_at=NOW)
    notice.run = run
    session.add(run)
    judgment = Judgment(notice_id=notice.id, grade="우선 검토")
    judgment.verification_items = [VerificationItem(item="확인 항목", blocking=True, status="미확인")]
    session.add(judgment)
    link_notice(session, blocked, notice)
    merged = Opportunity(first_registered_stage="bid_notice", merged_into_opportunity_id=first.id,
        merged_at=NOW, merge_reason="fixture")
    session.add(merged)
    session.flush()
    return {"first": first.id, "ended": ended.id, "pending": pending.id, "blocked": blocked.id}


def seed_execution(session, *, minute=1, status="성공"):
    run = Run(id=f"workload:{uuid4()}", generated_at=NOW)
    version = f"fixture:{uuid4()}"
    policy = OrderPlanScreeningPolicy(policy_version=version, schema_version="bidops.order-plan-screening-policy.v1",
        producer="phase0-contracts", consumer="phase1-screening-pipeline", policy_status="draft",
        decision_scope="c2_order_plan_first_pass", policy_payload_jsonb={}, binding_payload_jsonb={},
        policy_sha256="a"*64, binding_sha256="b"*64, activation_metadata_jsonb={}, created_by="fixture", created_at=NOW)
    session.add_all([run, policy])
    session.flush()
    row = OrderPlanScreeningExecution(request_id=uuid4(), schema_version="bidops.order-plan-screening-execution-row.v1",
        producer="screening-api", consumer="screening-worker-and-review-api", source_run_id=run.id,
        source_artifact_name="collected-order-plans.json", source_artifact_schema_version="bidops.collected-order-plans.v1",
        source_artifact_sha256="a"*64, input_artifact_sha256="a"*64, population_count=1, population_sha256="a"*64,
        policy_version=version, policy_sha256="a"*64, binding_sha256="b"*64,
        stage1_binding_version="fixture", stage1_binding_sha256="c"*64,
        stage2_binding_version="fixture", stage2_binding_sha256="d"*64,
        status=status, requested_by="fixture", partial_artifact=status != "성공",
        queued_at=NOW, started_at=NOW, finished_at=NOW+timedelta(minutes=minute), created_at=NOW)
    session.add(row)
    session.flush()
    return row


def add_plan(session, execution, *, tracking="미선택", relevance="relevant", selected=True):
    plan = OrderPlan(order_plan_unty_no=f"fixture:{uuid4()}", title="합성 발주계획")
    session.add(plan)
    session.flush()
    session.add(OrderPlanObservation(order_plan_id=plan.id, run_id=execution.source_run_id, observed_at=NOW))
    result(session, execution, plan, relevance=relevance,
        stage1="selected" if selected else "filtered_out", stage2="success" if selected else "not_attempted")
    if tracking is not None:
        owner(session, plan, tracking=tracking)
    session.flush()
    return plan


@pytest.mark.parametrize("modules", COMBINATIONS)
def test_workload_matches_real_list_totals_and_tracking_exceptions(workload_session, empty_extensions, modules, monkeypatch):
    session = workload_session
    calls = []
    for name, provider in (("screening", ScreeningWorkloadProjection), ("deep_review", DeepReviewWorkloadProjection)):
        original = provider.workload_counts
        def counted(self, current_session, original=original, name=name):
            calls.append(name)
            return original(self, current_session)
        monkeypatch.setattr(provider, "workload_counts", counted)
    sections = seed_sections(session)
    non_sw = add_prespec(session, "N")  # No opportunity or order-plan link at all.
    sw = add_prespec(session, "Y", tracking="종료")
    tracked_non_sw = add_prespec(session, "N")
    tracked_plan = OrderPlan(order_plan_unty_no=f"fixture:{uuid4()}", title="합성 추적 발주계획")
    session.add(tracked_plan)
    session.flush()
    tracked_owner = owner(session, tracked_plan, tracking="계속 추적")
    link_notice(session, tracked_owner, tracked_non_sw)
    old = seed_execution(session)
    add_plan(session, old)
    latest = seed_execution(session, minute=2, status="부분 성공")
    for tracking, relevance, selected in (("미선택", "relevant", True), ("미선택", "uncertain", True),
        ("계속 추적", "relevant", True), (None, "relevant", True), ("미선택", "not_relevant", True),
        ("미선택", "relevant", False)):
        add_plan(session, latest, tracking=tracking, relevance=relevance, selected=selected)
    seed_execution(session, minute=3, status="실패")
    current = opportunity(session)
    c, _, _ = comparison(session, current)
    decide(session, current, c)
    unknown = opportunity(session)
    u, _, bid = comparison(session, unknown)
    bid["notice"].published_at = None
    decide(session, unknown, u)
    stale = opportunity(session)
    s, _, _ = comparison(session, stale)
    decide(session, stale, s)
    newer = add_notice(session, "bid_notice")
    newer.published_at = NOW + timedelta(days=1)
    link_notice(session, stale, newer)
    undecided = opportunity(session)
    no_date = add_notice(session, "bid_notice")
    no_date.published_at = None
    link_notice(session, undecided, no_date)
    session.flush()
    with client_for(session, modules) as client:
        values = workload(client)
        assert calls == [name for name in modules if name != "lifecycle"]
        actions = get_json(client, "/api/opportunities", section="조치 필요", limit=1)
        expected_action = 4 if "screening" in modules else 3
        assert values[KEYS[2]] == (expected_action, None)
        assert actions["total"] == actions["section_counts"]["조치 필요"] == expected_action
        action_ids = {row["id"] for row in get_json(client, "/api/opportunities", section="조치 필요")["items"]}
        assert action_ids == {sections[key] for key in ("first", "ended", "pending", "blocked") if key != "blocked" or "screening" in modules}
        if "screening" in modules:
            listing = get_json(client, "/api/order-plans", stage1_status="selected", qwen_relevance="relevant,uncertain", tracking_status="미선택", limit=1)
            assert listing["scope"]["execution_id"] == str(latest.execution_id)
            assert values[KEYS[0]] == (listing["total"], None) == (2, None)
        else:
            assert values[KEYS[0]] == (None, "provider_absent")
        ready = get_json(client, "/api/pre-specs", auto_preparation_status="deep_review_ready_for_click", sw_only=False)
        if "deep_review" in modules:
            assert values[KEYS[1]] == (ready["total"], None) == (3, None)
            assert {row["notice_pk"] for row in ready["items"]} == {non_sw.id, sw.id, tracked_non_sw.id}
            assert get_json(client, "/api/pre-specs", auto_preparation_status="deep_review_ready_for_click", sw_only=True)["total"] == 2
            pending = get_json(client, "/api/bid-delta/decision-queue", status="pending", limit=1)
            assert values[KEYS[3]] == (pending["total"], None) == (2, None)
        else:
            assert ready["total"] == 0
            assert values[KEYS[1]] == values[KEYS[3]] == (None, "provider_absent")
        if "screening" in modules:
            seed_execution(session, minute=4)
            assert workload(client)[KEYS[0]] == (0, None)
            assert calls == [name for name in modules if name != "lifecycle"] * 2


@pytest.mark.parametrize("modules", COMBINATIONS)
def test_workload_query_count_is_constant_across_large_population(workload_session, empty_extensions, modules):
    session = workload_session
    execution = seed_execution(session)
    def add_batch(size):
        for _ in range(size):
            add_prespec(session, "N")
            add_plan(session, execution)
            link_notice(session, opportunity(session), add_notice(session, "bid_notice"))
            session.add(Opportunity(first_registered_stage="bid_notice"))
        session.flush()
    counts = []
    with client_for(session, modules) as client:
        for size, total in ((2, 2), (500, 502)):
            add_batch(size)
            session.expunge_all()
            statements = []
            def record(_connection, _cursor, statement, _parameters, _context, _many):
                statements.append(statement)
            event.listen(session.bind, "before_cursor_execute", record)
            try:
                values = workload(client)
            finally:
                event.remove(session.bind, "before_cursor_execute", record)
            assert values[KEYS[2]] == (total, None)
            if "screening" in modules:
                assert values[KEYS[0]] == (total, None)
            if "deep_review" in modules:
                assert values[KEYS[1]] == values[KEYS[3]] == (total, None)
            counts.append(len(statements))
    assert 0 < counts[0] == counts[1] <= 30
