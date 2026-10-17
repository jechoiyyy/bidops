"""조립된 업무 제공자와 PostgreSQL 목록의 workload 계약을 대조한다."""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

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
from tests.app.test_runtime_database_privileges import _ensure_roles
from tests.screening.test_order_plan_list_v2 import owner, result
from tests.deep_review.decision_queue_fixtures import comparison, decide, opportunity

NOW = datetime(2026, 9, 7, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[4]
RUNTIME_POLICY = (ROOT / "scripts/runtime-privileges.sql").read_text(encoding="utf-8")
KEYS = ("order_plan_pending", "pre_spec_deep_review_ready", "tracking_action_required",
        "tracking_hold_review_due", "bid_final_decision_pending",
        "tracking_deadline_imminent", "human_check_required", "overview_human_review",
        "blocking_items_open", "order_plan_new_priority", "company_attention", "briefing_pending")
(ORDER_PLAN, DEEP_REVIEW, ACTION, HOLD_DUE, FINAL_DECISION,
 IMMINENT, HUMAN_CHECK, OVERVIEW_HUMAN, BLOCKING_OPEN, NEW_PRIORITY, COMPANY_ATTENTION,
 BRIEFING_PENDING) = KEYS
#: lifecycle이 자기 테이블에서 직접 세는 키. 제공자 값으로 덮이지 않는다.
LIFECYCLE_OWNED = (ACTION, HOLD_DUE, IMMINENT, BLOCKING_OPEN)
COMBINATIONS = (("lifecycle",), ("lifecycle", "screening"), ("lifecycle", "screening", "deep_review"))
pytestmark = requires_postgres


@pytest.fixture(scope="module")
def workload_engine():
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
        for key in LIFECYCLE_OWNED:
            expected[key] = (0, None)
        # 개요 하위 건수의 제공자가 없으면 합계도 셀 수 없다 — 0으로 접지 않는다.
        expected[HUMAN_CHECK] = (None, "sub_count_unavailable")
        if "screening" in modules:
            # 누적 범위에 완료된 운영 실행이 없다는 사유는 두 발주계획 키에 같이 붙는다.
            expected[ORDER_PLAN] = expected[NEW_PRIORITY] = (None, "no_completed_execution")
        if "deep_review" in modules:
            expected[DEEP_REVIEW] = (0, None)
            expected[FINAL_DECISION] = (0, None)
            expected[OVERVIEW_HUMAN] = (0, None)
            expected[HUMAN_CHECK] = (0, None)
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
        empty_extensions.register_workload_projection(Provider("first", {ORDER_PLAN: provided}), owner="first")
        # lifecycle이 직접 세는 두 키는 제공자 값으로 덮이지 않는다.
        empty_extensions.register_workload_projection(Provider("second", {
            DEEP_REVIEW: WorkloadCount(0), FINAL_DECISION: WorkloadCount(None, "fixture_pending"),
            HOLD_DUE: WorkloadCount(99), BLOCKING_OPEN: WorkloadCount(99),
            # 합계 키를 제공자가 보내도 lifecycle이 두 하위의 합으로 다시 쓴다.
            HUMAN_CHECK: WorkloadCount(99), OVERVIEW_HUMAN: WorkloadCount(4),
        }), owner="second")
        for request_number in (1, 2):
            assert workload(client) == {
                ORDER_PLAN: (provided.count, provided.unavailable_reason), DEEP_REVIEW: (0, None),
                ACTION: (0, None), HOLD_DUE: (0, None), FINAL_DECISION: (None, "fixture_pending"),
                IMMINENT: (0, None), BLOCKING_OPEN: (0, None), OVERVIEW_HUMAN: (4, None),
                HUMAN_CHECK: (4, None), NEW_PRIORITY: (None, "provider_absent"),
                # RL-00: no registered provider and no real company -> absent.
                COMPANY_ATTENTION: (None, "provider_absent"),
                # RL-01: lifecycle이 직접 세지만 브리핑이 하나도 없으면 셀 대상이 없다.
                BRIEFING_PENDING: (None, "provider_absent"),
            }
            assert calls == ["first", "second"] * request_number


def add_notice(session, kind, *, sw=None, deadline_at=None):
    row = Notice(notice_key=f"workload:{uuid4()}", source_type=kind, published_at=NOW,
        deadline_at=deadline_at,
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


def overdue_hold(session, *, stage="bid_notice"):
    """실제 시계와 무관하게 기한이 지난 보류(workload는 요청 시각을 쓴다)."""

    row = Opportunity(first_registered_stage=stage, tracking_status="보류", tracking_reason="대기",
        tracking_selected_by="fixture", tracking_selected_at=datetime.now(UTC) - timedelta(days=30))
    session.add(row)
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
    # 대기 후보만으로 조치 필요다. 선택 시각은 요청 시각과 무관하게 기한 전으로 둔다.
    pending.tracking_selected_at = datetime.now(UTC) + timedelta(days=1)
    link_notice(session, pending, add_notice(session, "pre_spec"), status="후보 확인 대기", kind="candidate")
    overdue = overdue_hold(session)
    searched = opportunity(session, tracking="미선택")
    link_notice(session, searched, None, status="검색 미확인", kind="candidate")
    blocked = opportunity(session, tracking="계속 추적")
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
    return {"first": first.id, "ended": ended.id, "pending": pending.id, "overdue": overdue.id,
            "blocked": blocked.id}


def seed_execution(session, *, minute=1, status="성공"):
    run = Run(id=f"workload:{uuid4()}", generated_at=NOW)
    version = f"fixture:{uuid4()}"
    policy = OrderPlanScreeningPolicy(policy_version=version, schema_version="bidops.order-plan-screening-policy.v1",
        producer="phase0-contracts", consumer="phase1-screening-pipeline", policy_status="retired",
        decision_scope="c2_order_plan_first_pass", policy_payload_jsonb={}, binding_payload_jsonb={},
        policy_sha256="a"*64, binding_sha256="b"*64, activation_metadata_jsonb={}, created_by="fixture", created_at=NOW,
        activated_by="fixture", activated_at=NOW)
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


def add_plan(session, execution, *, tracking="미선택", relevance="relevant", selected=True, observed_at=NOW):
    plan = OrderPlan(order_plan_unty_no=f"fixture:{uuid4()}", title="합성 발주계획")
    session.add(plan)
    session.flush()
    session.add(OrderPlanObservation(order_plan_id=plan.id, run_id=execution.source_run_id, observed_at=observed_at))
    result(session, execution, plan, relevance=relevance,
        stage1="selected" if selected else "filtered_out", stage2="success" if selected else "not_attempted")
    if tracking is not None:
        owner(session, plan, tracking=tracking)
    session.flush()
    return plan


@pytest.mark.parametrize("modules", COMBINATIONS)
@pytest.mark.parametrize("runtime_role", (None, "app"), ids=("owner", "app"))
def test_workload_matches_real_list_totals_and_tracking_exceptions(
    workload_session, empty_extensions, modules, runtime_role, monkeypatch
):
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
    # 마감 임박 추적 건: 실제 시계 기준으로 창 안·창 밖·추적 미선택을 각각 세운다.
    # (workload와 목록이 둘 다 요청 시각을 쓰므로 고정 NOW를 쓸 수 없다.)
    real_now = datetime.now(UTC)
    imminent_owner = opportunity(session, tracking="계속 추적")
    link_notice(session, imminent_owner, add_notice(session, "pre_spec", deadline_at=real_now + timedelta(days=2)))
    far_owner = opportunity(session, tracking="보류")
    far_owner.tracking_selected_at = real_now + timedelta(days=1)
    link_notice(session, far_owner, add_notice(session, "bid_notice", deadline_at=real_now + timedelta(days=30)))
    unselected_owner = opportunity(session, tracking="미선택")
    link_notice(session, unselected_owner, add_notice(session, "bid_notice", deadline_at=real_now + timedelta(days=2)))
    # 새 우선 검토 발주계획: 전일 이후 처음 관측 + 모델 판단 관련 + 추적 미선택.
    new_plan = add_plan(session, latest, observed_at=real_now)
    add_plan(session, latest, observed_at=real_now, relevance="uncertain")
    session.flush()
    if runtime_role == "app":
        session.connection().exec_driver_sql("SET LOCAL ROLE app")
    with client_for(session, modules) as client:
        values = workload(client)
        assert calls == [name for name in modules if name != "lifecycle"]
        actions = get_json(client, "/api/opportunities", section="조치 필요", limit=1)
        # 입찰공고 최초 등록 미선택(first)은 신규 입찰공고로 분리된다. 차단 항목은
        # 판정 제공자가 있을 때만 계속 추적(blocked)을 올린다.
        expected_action = 4 if "screening" in modules else 3
        assert values[ACTION] == (expected_action, None)
        assert actions["total"] == actions["section_counts"]["조치 필요"] == expected_action
        action_ids = {row["id"] for row in get_json(client, "/api/opportunities", section="조치 필요")["items"]}
        assert action_ids == {sections[key] for key in ("ended", "pending", "overdue", "blocked") if key != "blocked" or "screening" in modules}
        newcomers = get_json(client, "/api/opportunities", section="신규 입찰공고")
        assert sections["first"] in {row["id"] for row in newcomers["items"]}
        due = get_json(client, "/api/opportunities", hold_review="overdue", limit=1)
        assert values[HOLD_DUE] == (due["total"], None) == (1, None)
        assert due["items"][0]["id"] == sections["overdue"]
        # 마감 임박 추적 건: 창(7일)·추적 대상 좁힘·정렬을 목록과 같은 모집단으로 읽는다.
        imminent = get_json(client, "/api/opportunities", deadline_within_days=7, sort="deadline")
        assert values[IMMINENT] == (imminent["total"], None) == (1, None)
        assert [row["id"] for row in imminent["items"]] == [imminent_owner.id]
        # 공고별 열린 확인 항목: 목록 `reason=blocking_item`과 같은 분류다. 판정 제공자가
        # 없으면 공고 집합이 비어 실제 0이 된다(`provider_absent`가 아니다).
        blocking = get_json(client, "/api/opportunities", reason="blocking_item", limit=1)
        expected_blocking = 1 if "screening" in modules else 0
        assert values[BLOCKING_OPEN] == (blocking["total"], None) == (expected_blocking, None)
        if "screening" in modules:
            listing = get_json(client, "/api/order-plans", stage1_status="selected", qwen_relevance="relevant,uncertain", tracking_status="미선택", limit=1)
            assert listing["scope"]["mode"] == "cumulative"
            # 누적 범위: 앞 실행(old)의 판정도 남는다.
            assert values[ORDER_PLAN] == (listing["total"], None) == (5, None)
            # 새 우선 검토: `relevant` 하나로 좁히고 전일 이후 처음 관측만 센다.
            yesterday = (real_now.astimezone(ZoneInfo("Asia/Seoul")).date() - timedelta(days=1)).isoformat()
            fresh = get_json(client, "/api/order-plans", qwen_relevance="relevant",
                             tracking_status="미선택", first_observed_from=yesterday)
            assert values[NEW_PRIORITY] == (fresh["total"], None) == (1, None)
            assert [row["order_plan_pk"] for row in fresh["items"]] == [new_plan.id]
        else:
            assert values[ORDER_PLAN] == values[NEW_PRIORITY] == (None, "provider_absent")
        ready = get_json(client, "/api/pre-specs", auto_preparation_status="deep_review_ready_for_click", sw_only=False)
        # 2026-09-22 개정(시안 M7 ③): 타일 건수의 모집단은 `검토할 항목`이다 — 사람이
        # 추적 결정을 내린 건(`종료`·`계속 추적`)은 누적 목록에는 남고 건수에서만 빠진다.
        actionable_ready = get_json(client, "/api/pre-specs", workspace="actionable",
                                    auto_preparation_status="deep_review_ready_for_click", sw_only=False)
        if "deep_review" in modules:
            assert {row["notice_pk"] for row in ready["items"]} == {non_sw.id, sw.id, tracked_non_sw.id}
            assert ready["total"] == 3
            assert values[DEEP_REVIEW] == (actionable_ready["total"], None) == (1, None)
            assert {row["notice_pk"] for row in actionable_ready["items"]} == {non_sw.id}
            assert get_json(client, "/api/pre-specs", auto_preparation_status="deep_review_ready_for_click", sw_only=True)["total"] == 2
            pending = get_json(client, "/api/bid-delta/decision-queue", status="pending", limit=1)
            assert values[FINAL_DECISION] == (pending["total"], None) == (2, None)
            # 개요 하위 건수는 배타적인 두 상태의 목록 `total` 합과 같다.
            failed = get_json(client, "/api/pre-specs", overview_view="failed", sw_only=False)
            attention = get_json(client, "/api/pre-specs", overview_view="attention", sw_only=False)
            assert values[OVERVIEW_HUMAN] == (failed["total"] + attention["total"], None) == (3, None)
            # 합계는 두 하위의 합이며 서로 다른 단위(공고·사업기회)를 섞는다는 사실이
            # 화면 바닥의 하위 건수 표시로 남는다.
            assert values[HUMAN_CHECK] == (values[OVERVIEW_HUMAN][0] + expected_blocking, None)
        else:
            assert ready["total"] == actionable_ready["total"] == 0
            assert values[DEEP_REVIEW] == values[FINAL_DECISION] == (None, "provider_absent")
            assert values[OVERVIEW_HUMAN] == (None, "provider_absent")
            assert values[HUMAN_CHECK] == (None, "sub_count_unavailable")
        if "screening" in modules:
            seed_execution(session, minute=4)
            assert workload(client)[ORDER_PLAN] == (5, None)
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
            overdue_hold(session)
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
            assert values[ACTION] == values[HOLD_DUE] == (total, None)
            # 마감·확인 항목이 없는 표본이라 두 키는 실제 0이다.
            assert values[IMMINENT] == values[BLOCKING_OPEN] == (0, None)
            if "screening" in modules:
                assert values[ORDER_PLAN] == (total, None)
                # 관측 시각이 2026-09-07이라 "전일 이후 처음 관측"은 없다.
                assert values[NEW_PRIORITY] == (0, None)
            if "deep_review" in modules:
                assert values[DEEP_REVIEW] == values[FINAL_DECISION] == (total, None)
                assert values[OVERVIEW_HUMAN] == (total, None)
                assert values[HUMAN_CHECK] == (total, None)
            else:
                assert values[HUMAN_CHECK] == (None, "sub_count_unavailable")
            counts.append(len(statements))
    assert 0 < counts[0] == counts[1] <= 40
