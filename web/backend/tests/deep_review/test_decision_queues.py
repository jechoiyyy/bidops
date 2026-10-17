"""Decision work queues preserve human decisions and batch currentness."""
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.lifecycle import ExtensionRegistry, WorkloadCount
from app.lifecycle.models import Notice, OpportunityLink
from app.deep_review import register_lifecycle_extensions
from app.deep_review.models import (
    ContentObject,
    DocumentBundle,
    DocumentBundleItem,
    DocumentVersion,
    PrespecOverviewRun,
    WorkJob,
)
from app.deep_review.services.bid_delta import BidDeltaService
from app.deep_review.services.prespec_projection import PreSpecOverviewDocumentProjection
from tests.postgres import migrated_engine, requires_postgres
from .decision_queue_fixtures import NOW, opportunity, comparison, decide


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def queue_session(request):
    if request.param == "postgres":
        with migrated_engine() as engine, Session(engine) as session:
            yield session
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        init_db(engine)
        with Session(engine) as session:
            yield session
        engine.dispose()


@contextmanager
def counted(session):
    statements = []
    def record(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(session.bind, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(session.bind, "before_cursor_execute", record)


def add_bid(session, owner, *, published=NOW, kind="official", status="확정", human=None,
            deadline_at=None, budget=None, estimated_price=None):
    notice = Notice(notice_key=f"queue:{uuid4()}", source_type="bid_notice", published_at=published,
        deadline_at=deadline_at, budget=budget, estimated_price=estimated_price)
    session.add(notice)
    session.flush()
    link = OpportunityLink(opportunity_id=owner.id, notice_id=notice.id, stage="notice", link_type=kind,
        status=status, evidence_external_no=str(uuid4()), human_decision=human,
        reviewer_name="fixture" if human else None, reviewed_at=NOW if human else None,
        review_reason="fixture" if human else None)
    session.add(link)
    session.flush()
    return notice, link


def test_queue_filters_before_pagination_and_uses_latest_decision(queue_session):
    session = queue_session
    # First registered rows are already decided; pending must still reach later rows.
    current = opportunity(session, created_at=NOW + timedelta(days=2))
    c, _b, _n = comparison(session, current)
    earlier = decide(session, current, c)
    decide(session, current, c, sequence=2, supersedes=earlier.id, decision="no_go")
    unknown = opportunity(session, created_at=NOW + timedelta(days=1))
    u, _b, notice = comparison(session, unknown)
    notice["notice"].published_at = None
    decide(session, unknown, u)
    stale = opportunity(session)
    s, _b, _n = comparison(session, stale)
    decide(session, stale, s)
    add_bid(session, stale, published=NOW + timedelta(days=1))
    undecided = opportunity(session, created_at=NOW - timedelta(days=1))
    add_bid(session, undecided, published=None)
    unlinked = opportunity(session)
    candidate = opportunity(session)
    add_bid(session, candidate, kind="candidate", status="후보 확인 대기")
    accepted = opportunity(session)
    add_bid(session, accepted, kind="candidate", status="사람 확인 완료", human="accepted")
    ended = opportunity(session, tracking="종료")
    add_bid(session, ended)
    merged = opportunity(session)
    add_bid(session, merged)
    merged.merged_into_opportunity_id = current.id
    merged.merged_at, merged.merge_reason = NOW, "fixture"
    session.commit()
    service = BidDeltaService()
    pending = service.decision_queue(session, status="pending", limit=1, offset=0)
    assert pending["total"] == 3
    assert pending["items"][0]["opportunity_id"] == accepted.id
    second = service.decision_queue(session, status="pending", limit=1, offset=1)
    assert second["items"][0]["opportunity_id"] == undecided.id
    assert second["items"][0]["decision_currentness"] == "unknown"
    third = service.decision_queue(session, status="pending", limit=1, offset=2)
    assert third["items"][0]["opportunity_id"] == stale.id
    assert third["items"][0]["decision_currentness"] == "stale"
    all_rows = service.decision_queue(session, status="all", limit=500, offset=0)
    by_id = {row["opportunity_id"]: row for row in all_rows["items"]}
    assert set(by_id) == {current.id, unknown.id, stale.id, undecided.id, unlinked.id, candidate.id, accepted.id}
    assert by_id[current.id]["latest_final_decision"]["decision"] == "no_go"
    assert by_id[current.id]["comparison_count"] == 1
    assert by_id[unknown.id]["decision_currentness"] == "unknown"
    assert by_id[unlinked.id]["bid_notice_external_id"] is None
    assert by_id[candidate.id]["bid_notice_external_id"] is None
    assert service.decision_queue(session, status="pending", limit=1, offset=99)["items"] == []


def test_queue_query_count_is_constant_across_500_links(queue_session):
    session = queue_session
    owner = opportunity(session)
    compared, _baseline, _bid = comparison(session, owner)
    decide(session, owner, compared)
    session.commit()
    with counted(session) as small:
        assert BidDeltaService().decision_queue(session, status="all")["total"] == 1
    for _ in range(500):
        add_bid(session, owner)
    session.commit()
    with counted(session) as large:
        assert BidDeltaService().decision_queue(session, status="all")["total"] == 1
    assert len(small) == len(large)
    assert len(large) <= 10


def test_queue_http_validation_and_safe_empty_shape(queue_session):
    from app.deep_review.routers import bid_delta
    app = FastAPI()
    app.include_router(bid_delta.decision_queue_router)
    app.dependency_overrides[get_db] = lambda: queue_session
    with TestClient(app) as client:
        response = client.get("/api/bid-delta/decision-queue")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
        for query in ("status=bogus", "limit=0", "limit=501", "offset=-1"):
            assert client.get(f"/api/bid-delta/decision-queue?{query}").status_code == 422


def add_ready_prespec(session):
    """심층 검토 클릭 대기(`deep_review_ready_for_click`)가 되는 사전규격 한 건."""

    ready = Notice(notice_key=f"prespec:{uuid4()}", source_type="pre_spec",
        qualification_flags_json={"sw_business_status": "N"})
    session.add(ready)
    session.flush()
    session.add(DocumentBundle(notice_id=ready.id, revision=1, version=1, status="ready", issues_snapshot=[]))
    session.flush()
    # 종결된 개요 run이 있어야 그 묶음이 결정 대기(사람 클릭)로 센다.
    content = ContentObject(sha256=f"{ready.id:064d}", size_bytes=1,
                            detected_mime="application/pdf", retention_class="document-source")
    session.add(content)
    session.flush()
    document = DocumentVersion(notice_id=ready.id, content_object_id=content.id, version=1,
                               source_kind="manual", original_filename="제안요청서.pdf", role="제안요청서",
                               is_current=True, safety_status="safe")
    job = WorkJob(job_type="prespec_overview", aggregate_type="prespec_overview_run",
                  aggregate_id=uuid4(), status="completed")
    session.add_all([document, job])
    session.flush()
    session.add(PrespecOverviewRun(
        notice_id=ready.id, document_version_id=document.id, work_job_id=job.id, status="failed",
        range_source="auto", range_reason_codes=[], policy_digest="0" * 64, model_name="test-model",
        warnings_json=[], reason_codes=[], call_count=0, raw_response_refs=[],
    ))
    session.flush()
    return ready


def test_workload_registration_counts_unlinked_non_sw_prespecs(queue_session, monkeypatch):
    from app.deep_review.services import auto_preparation
    # The ready/settled state is independent of screening availability and grade.
    monkeypatch.setattr(auto_preparation, "effective_grades", lambda _session, _ids: {})
    session = queue_session
    ready = add_ready_prespec(session)
    owner = opportunity(session)
    add_bid(session, owner)
    session.commit()
    projection = PreSpecOverviewDocumentProjection()
    assert projection.notice_ids_for_auto_preparation_status(session, [ready.id], "deep_review_ready_for_click") == [ready.id]
    registry = register_lifecycle_extensions(ExtensionRegistry())
    register_lifecycle_extensions(registry)
    counts = registry.workload_counts(session)
    # 이 사전규격의 개요 run이 `failed`라 `사람 확인 필요`의 개요 하위 건수에도 든다.
    assert counts == {
        "pre_spec_deep_review_ready": WorkloadCount(1),
        "bid_final_decision_pending": WorkloadCount(1),
        "overview_human_review": WorkloadCount(1),
        # RL-00: deep_review가 값을 세는 `company_attention`. 실회사가 없으면 제공자 부재다.
        "company_attention": WorkloadCount(None, "provider_absent"),
    }
    assert registry.notice_ids_for_auto_preparation_status(session, [ready.id], "not_applicable") == []


@pytest.mark.parametrize("decided", ("보류", "계속 추적", "종료"))
def test_deep_review_ready_count_drops_human_tracking_decisions(queue_session, monkeypatch, decided):
    """2026-09-22 개정(시안 M7 ③): 타일 건수도 `검토할 항목`과 같은 추적 조건을 쓴다."""

    from app.deep_review.services import auto_preparation
    monkeypatch.setattr(auto_preparation, "effective_grades", lambda _session, _ids: {})
    session = queue_session
    ready = add_ready_prespec(session)
    owner = opportunity(session, tracking=decided)
    session.add(OpportunityLink(opportunity_id=owner.id, notice_id=ready.id, stage="notice",
                                link_type="official", status="확정",
                                evidence_external_no=ready.notice_key))
    session.commit()
    registry = register_lifecycle_extensions(ExtensionRegistry())

    # 자동 준비 상태 자체는 그대로다 — 빠지는 이유는 사람이 내린 추적 결정 하나다.
    projection = PreSpecOverviewDocumentProjection()
    assert projection.notice_ids_for_auto_preparation_status(
        session, [ready.id], "deep_review_ready_for_click") == [ready.id]
    assert registry.workload_counts(session)["pre_spec_deep_review_ready"] == WorkloadCount(0)

    # 미선택으로 되돌리면 다시 센다.
    owner.tracking_status = "미선택"
    owner.tracking_selected_by = None
    owner.tracking_selected_at = None
    session.commit()
    assert registry.workload_counts(session)["pre_spec_deep_review_ready"] == WorkloadCount(1)


def test_opportunity_review_list_includes_candidate_links_and_safe_history(queue_session):
    from app.core.models import AuditEvent
    from app.deep_review.models import (AnalysisPolicyVersion, ProfileVersion, DeepReview,
        DeepReviewAttempt, FinalOpinion, ReportRevision, ValidationRun)
    from app.deep_review.services.deep_reviews import DeepReviewService
    session = queue_session
    owner = opportunity(session)
    notice, link = add_bid(session, owner, kind="candidate", status="후보 확인 대기")
    profile = ProfileVersion(version=1, label="fixture", profile_payload={}, profile_sha256="a"*64, source_kind="fixture")
    policy = AnalysisPolicyVersion(version=1, label="fixture", model_endpoint_ref="fixture", model_name="fixture",
        prompts={}, validation_rules={}, policy_sha256="b"*64)
    session.add_all([profile, policy])
    session.flush()
    reviews = []
    for index in range(3):
        bundle = DocumentBundle(notice_id=notice.id, revision=index+1, version=1, status="ready", issues_snapshot=[])
        session.add(bundle)
        session.flush()
        review = DeepReview(notice_id=notice.id, bundle_id=bundle.id, profile_version_id=profile.id,
            policy_version_id=policy.id, effective_grade_at_start="우선 검토", status="queued",
            created_at=NOW + timedelta(minutes=index))
        session.add(review)
        session.flush()
        reviews.append(review)
    attempt = DeepReviewAttempt(deep_review_id=reviews[1].id, sequence=1, status="failed")
    session.add(attempt)
    session.flush()
    reviews[1].current_attempt_id = attempt.id
    for review, metadata in ((reviews[0], {"analysis_provider": "mock-analysis"}),
        (reviews[1], {"reference_workflow_mode": True})):
        session.add(AuditEvent(actor_kind="system", action="deep_review.auto_create", aggregate_type="deep_review",
            aggregate_id=str(review.id), safe_metadata={**metadata, "private_fixture": "raw-must-not-leak"}))
    revision = ReportRevision(deep_review_id=reviews[0].id, sequence=1, origin="machine", report_payload={}, report_sha256="c"*64)
    session.add(revision)
    session.flush()
    validation = ValidationRun(deep_review_id=reviews[0].id, report_revision_id=revision.id, sequence=1, status="passed")
    session.add(validation)
    session.flush()
    for sequence, value in ((1, "보류"), (2, "추진")):
        session.add(FinalOpinion(deep_review_id=reviews[0].id, report_revision_id=revision.id, sequence=sequence,
            value=value, reason="private-fixture-reason", validation_run_id=validation.id,
            validation_status_at_opinion="passed", claimed_name="fixture", created_at=NOW+timedelta(minutes=sequence)))
    session.commit()
    service = DeepReviewService()
    owner_id = owner.id
    with counted(session) as queries:
        result = service.opportunity_reviews(session, owner_id)
    assert len(queries) <= 5
    assert [item["deep_review_id"] for item in result["items"]] == [str(r.id) for r in reversed(reviews)]
    assert [item["quality_status"] for item in result["items"]] == [None, "unmeasured_reference", "mock_reference"]
    assert result["items"][1]["current_attempt_status"] == "failed"
    assert result["items"][0]["latest_final_opinion"] is None
    assert result["items"][2]["latest_final_opinion"]["value"] == "추진"
    assert "private" not in str(result)
    from app.deep_review.routers.deep_reviews import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    empty = opportunity(session)
    session.commit()
    with TestClient(app) as client:
        response = client.get(f"/api/opportunities/{owner.id}/deep-reviews")
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == 3
        assert client.get(f"/api/opportunities/{empty.id}/deep-reviews").json() == {"opportunity_id": empty.id, "items": []}
        assert client.get("/api/opportunities/999999999/deep-reviews").status_code == 404

    # More than 500 reviews cannot introduce relationship-loader query chunks.
    bundles = [DocumentBundle(notice_id=notice.id, revision=index+4, version=1, status="ready", issues_snapshot=[])
        for index in range(500)]
    session.add_all(bundles)
    session.flush()
    session.add_all([DeepReview(notice_id=notice.id, bundle_id=bundle.id, profile_version_id=profile.id,
        policy_version_id=policy.id, effective_grade_at_start="우선 검토", status="queued", created_at=NOW)
        for bundle in bundles])
    session.commit()
    with counted(session) as large:
        assert len(service.opportunity_reviews(session, owner_id)["items"]) == 503
    assert len(large) == len(queries)


@pytest.mark.parametrize("side_name,overrides,expected", [
    ("baseline", {}, "stale"), ("comparison", {}, "stale"),
    ("baseline", {"reuse_bundle": True}, "stale"),
    ("comparison", {"reuse_bundle": True, "document_version": 1}, "current"),
    ("baseline", {"bundle_status": "draft"}, "current"),
    ("comparison", {"role": "기타"}, "current"),
    ("baseline", {"role": "공고"}, "current"),
    ("comparison", {"role": "정정"}, "stale"),
    ("baseline", {"snapshot_safety": "blocked"}, "current"),
    ("comparison", {"document_safety": "blocked"}, "current"),
    ("baseline", {"structure_status": "failed"}, "current"),
    ("comparison", {"source_hash": "f"*64}, "current"),
    ("baseline", {"payload_hash": "f"*64}, "current"),
])
def test_currentness_preserves_every_ready_document_guard(queue_session, side_name, overrides, expected):
    from .decision_queue_fixtures import ready_candidate
    from app.deep_review.services.bid_delta_currentness import comparison_currentness
    session = queue_session
    owner = opportunity(session)
    compared, baseline, bid = comparison(session, owner)
    ready_candidate(session, baseline if side_name == "baseline" else bid, **overrides)
    session.commit()
    value = BidDeltaService()._currentness(session, compared)
    assert value == (expected, ["newer_ready_document_version"] if expected == "stale" else [])
    assert comparison_currentness(session, [owner.id])[compared.id] == value


def legacy_notice_currentness(session, compared):
    """The previous early-return rule, without assuming a database row order."""
    from app.deep_review.services.bid_delta import _is_authoritative
    from datetime import UTC
    captured = session.get(Notice, compared.comparison_notice_id)
    if captured is None or captured.published_at is None:
        return "unknown", ["ordering_unknown"]
    def aware(value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
    links = session.scalars(select(OpportunityLink).where(
        OpportunityLink.opportunity_id == compared.opportunity_id,
        OpportunityLink.notice_id.is_not(None))).all()
    for link in links:
        if not _is_authoritative(link):
            continue
        notice = session.get(Notice, link.notice_id)
        if notice is None or notice.source_type != "bid_notice":
            continue
        if notice.published_at is None:
            return "unknown", ["ordering_unknown"]
        if notice.id != captured.id and aware(notice.published_at) > aware(captured.published_at):
            return "stale", ["newer_bid_notice"]
    return "current", []


@pytest.mark.parametrize("dates", [[], [None], [NOW], [NOW+timedelta(days=1)],
    [None, NOW+timedelta(days=1)], [NOW+timedelta(days=1), None]])
def test_batch_and_single_keep_existing_notice_currentness(queue_session, dates):
    from app.deep_review.services.bid_delta_currentness import comparison_currentness
    session = queue_session
    owner = opportunity(session)
    compared, _baseline, _bid = comparison(session, owner)
    for date in dates:
        add_bid(session, owner, published=date)
    # Non-authoritative newer/unknown notices have no currentness effect.
    add_bid(session, owner, published=None, kind="candidate", status="후보 확인 대기")
    add_bid(session, owner, published=NOW+timedelta(days=2), kind="candidate", status="후보 확인 대기")
    session.commit()
    previous = legacy_notice_currentness(session, compared)
    assert BidDeltaService()._currentness(session, compared) == previous
    assert comparison_currentness(session, [owner.id])[compared.id] == previous


def test_queue_all_preserves_unlinked_order_plan_display_and_nulls(queue_session):
    from app.lifecycle.models import OrderPlan
    session = queue_session
    owner = opportunity(session)
    plan = OrderPlan(plan_id=f"plan:{uuid4()}", title="발주계획", agency_name="테스트 기관")
    session.add(plan)
    session.flush()
    session.add(OpportunityLink(opportunity_id=owner.id, order_plan_id=plan.id,
        stage="order_plan", link_type="official", status="확정", evidence_external_no=plan.plan_id))
    session.commit()
    result = BidDeltaService().decision_queue(session, status="all")
    assert result["items"][0]["title"] == "발주계획"
    assert result["items"][0]["agency"] == "테스트 기관"
    assert result["items"][0]["bid_notice_external_id"] is None
    assert result["items"][0]["comparison_count"] == 0
    assert result["items"][0]["latest_final_decision"] is None
    # No bid notice is selected for this opportunity; the three bid-notice
    # projections stay null rather than falling back to the order plan.
    assert result["items"][0]["deadline_at"] is None
    assert result["items"][0]["budget"] is None
    assert result["items"][0]["estimated_price"] is None
    assert BidDeltaService().decision_queue(session)["total"] == 0


def test_queue_projects_selected_bid_amounts_and_sorts_by_nearest_deadline(queue_session):
    session = queue_session
    near = opportunity(session, created_at=NOW)
    add_bid(session, near, deadline_at=NOW + timedelta(days=1), budget="1500000.00",
        estimated_price="1400000.50")
    unknown_deadline = opportunity(session, created_at=NOW + timedelta(days=1))
    add_bid(session, unknown_deadline, deadline_at=None)
    far = opportunity(session, created_at=NOW)
    add_bid(session, far, deadline_at=NOW + timedelta(days=5))
    session.commit()
    result = BidDeltaService().decision_queue(session, status="all")
    # Ascending deadline first; unknown deadlines sort after every known one,
    # not first and not excluded.
    assert [item["opportunity_id"] for item in result["items"]] == [near.id, far.id, unknown_deadline.id]
    near_item = next(item for item in result["items"] if item["opportunity_id"] == near.id)
    assert near_item["deadline_at"] is not None
    # Exact Decimal magnitude, not a float-rounded amount.
    assert near_item["budget"] == "1500000"
    assert near_item["estimated_price"] == "1400000.5"
    assert result["items"][-1]["deadline_at"] is None


def test_workload_empty_counts_are_integer_zero(queue_session):
    counts = register_lifecycle_extensions(ExtensionRegistry()).workload_counts(queue_session)
    # deep_review가 소유한 세 키다. 대상이 없으면 실제 0이며 제공자 부재(`null`)가 아니다.
    # RL-00 `company_attention`은 실회사 행이 없으면 0이 아니라 제공자 부재다(spec "REST").
    assert counts == {
        "pre_spec_deep_review_ready": WorkloadCount(0),
        "bid_final_decision_pending": WorkloadCount(0),
        "overview_human_review": WorkloadCount(0),
        "company_attention": WorkloadCount(None, "provider_absent"),
    }


def test_currentness_detects_new_bundle_version_without_new_revision(queue_session):
    session = queue_session
    owner = opportunity(session)
    compared, baseline, _bid = comparison(session, owner)
    baseline["bundle"].version = 2
    session.commit()
    assert BidDeltaService()._currentness(session, compared) == ("stale", ["newer_ready_document_version"])


# --- ADR-0058: 공고 조건 근거의 최종 결정 --------------------------------------

SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64
ACTOR = {"X-BidOps-Actor-Name": "reviewer"}


def observe(session, notice, sha, *, observed_at=NOW):
    from app.lifecycle.models import NoticeObservation, Run
    run = Run(id=f"fixture-run-{uuid4()}", generated_at=observed_at)
    session.add(run)
    session.flush()
    session.add(NoticeObservation(notice_id=notice.id, run_id=run.id, observed_at=observed_at,
        snapshot_schema_version="fixture.v1", snapshot_jsonb={"fixture": True}, source_sha256=sha))
    session.flush()


def linked_notice(session, owner, *, source_type="bid_notice", bid_no="R26BK01699", bid_ord="000",
                  published=NOW, sha=None, kind="official", status="확정", **columns):
    notice = Notice(notice_key=f"{source_type}:{bid_no}:{bid_ord}:{uuid4()}", source_type=source_type,
        bid_no=bid_no if source_type == "bid_notice" else None,
        bid_ord=bid_ord if source_type == "bid_notice" else None, published_at=published, **columns)
    session.add(notice)
    session.flush()
    session.add(OpportunityLink(opportunity_id=owner.id, notice_id=notice.id, stage="notice", link_type=kind,
        status=status, evidence_external_no=str(uuid4())))
    session.flush()
    if sha is not None:
        observe(session, notice, sha)
    return notice


def bid_delta_client(session):
    from app.deep_review.routers import bid_delta
    app = FastAPI()
    app.include_router(bid_delta.decision_queue_router)
    app.include_router(bid_delta.router)
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def decision_body(notice_id, sha, **overrides):
    body = {"request_id": str(uuid4()), "expected_notice_id": notice_id, "expected_observation_sha256": sha,
        "supersedes_final_decision_id": None, "decision": "go", "reason": "공고 조건 확인"}
    body.update(overrides)
    return body


def test_bid_conditions_summarize_each_ordinal_without_guessing(queue_session):
    from decimal import Decimal
    from app.deep_review.services.bid_conditions import CONDITION_FIELDS
    session = queue_session
    owner = opportunity(session)
    pre = linked_notice(session, owner, source_type="pre_spec", title="스마트 행정 시스템 구축",
        agency="발주기관", budget=Decimal("150000000.00"), deadline_at=NOW + timedelta(days=3))
    first = linked_notice(session, owner, bid_ord="000", sha=SHA_A, title="스마트 행정 시스템 구축",
        budget=Decimal("150000000.00"), deadline_at=NOW + timedelta(days=10), method="일반경쟁",
        qualification_flags_json={"participation_limited": "Y", "industry_limited": "Y", "sw_industry_1468": "Y",
            "joint_contract_method": "공동이행", "successful_bid_method": "협상에의한계약",
            "technical_evaluation_rate": "90"},
        region_limit_json={"basis": "본사소재지", "joint_contract_regions": ["서울"]},
        lifecycle_json={"opening_at": "2026-09-20T11:00:00+09:00", "re_notice": "N"})
    second = linked_notice(session, owner, bid_ord="001", published=NOW + timedelta(days=1),
        title="스마트 행정 시스템 구축(정정)", budget=Decimal("150000000"),
        deadline_at=NOW + timedelta(days=12), method="일반경쟁",
        qualification_flags_json={"participation_limited": "Y", "industry_limited": "Y",
            "joint_contract_method": "공동이행", "successful_bid_method": "협상에의한계약",
            "technical_evaluation_rate": "80"},
        region_limit_json={"basis": "본사소재지", "joint_contract_regions": ["서울"]},
        lifecycle_json={"opening_at": "2026-09-20T02:00:00+00:00", "re_notice": "N", "change_reason": "마감 연장"})
    observe(session, second, SHA_C, observed_at=NOW)
    observe(session, second, SHA_B, observed_at=NOW + timedelta(hours=1))
    linked_notice(session, owner, bid_ord="002", published=NOW + timedelta(days=2),
        kind="candidate", status="후보 확인 대기")
    empty = opportunity(session)
    merged = opportunity(session)
    merged.merged_into_opportunity_id = owner.id
    merged.merged_at, merged.merge_reason = NOW, "fixture"
    session.commit()

    with bid_delta_client(session) as client:
        body = client.get(f"/api/opportunities/{owner.id}/bid-conditions").json()
        assert set(body) == {"opportunity_id", "generated_at", "latest_notice_id", "latest_observation_sha256",
            "pre_spec", "bid_notices", "pre_spec_comparison", "not_comparable"}
        assert (body["latest_notice_id"], body["latest_observation_sha256"]) == (second.id, SHA_B)
        assert [row["notice_id"] for row in body["bid_notices"]] == [first.id, second.id]
        assert [row["observation_sha256"] for row in body["bid_notices"]] == [SHA_A, SHA_B]
        head, tail = body["bid_notices"]
        assert list(head["conditions"]) == list(CONDITION_FIELDS)
        assert head["changes_from_previous"] == []
        assert head["conditions"]["budget"] == "150000000"
        assert head["conditions"]["sw_industry_1468"] == "Y"
        assert head["conditions"]["joint_contract_regions"] == ["서울"]
        assert head["conditions"]["change_reason"] is None
        assert tail["conditions"]["sw_industry_1468"] is None
        assert [change["field"] for change in tail["changes_from_previous"]] == list(CONDITION_FIELDS)
        statuses = {change["field"]: change["status"] for change in tail["changes_from_previous"]}
        assert statuses == {
            "budget": "unchanged", "estimated_price": "unknown", "deadline_at": "changed",
            "opening_at": "unchanged", "method": "unchanged", "participation_limited": "unchanged",
            "industry_limited": "unchanged", "sw_industry_1468": "unknown",
            "joint_contract_method": "unchanged", "successful_bid_method": "unchanged",
            "technical_evaluation_rate": "changed", "region_limit_basis": "unchanged",
            "joint_contract_regions": "unchanged", "change_reason": "unknown", "re_notice": "unchanged",
        }
        rate = next(change for change in tail["changes_from_previous"] if change["field"] == "technical_evaluation_rate")
        assert (rate["before"], rate["after"]) == ("90", "80")
        assert body["pre_spec"] == {"notice_id": pre.id, "title": "스마트 행정 시스템 구축",
            "agency": "발주기관", "budget": "150000000"}
        assert body["pre_spec_comparison"] == [
            {"field": "budget", "status": "unchanged", "before": "150000000", "after": "150000000"},
            {"field": "title", "status": "changed", "before": "스마트 행정 시스템 구축",
             "after": "스마트 행정 시스템 구축(정정)"},
        ]
        assert body["not_comparable"] == ["deadline_at"]

        blank = client.get(f"/api/opportunities/{empty.id}/bid-conditions").json()
        assert (blank["bid_notices"], blank["pre_spec"], blank["pre_spec_comparison"]) == ([], None, [])
        assert (blank["latest_notice_id"], blank["latest_observation_sha256"]) == (None, None)
        missing = client.get("/api/opportunities/999999999/bid-conditions")
        assert (missing.status_code, missing.json()["error"]["code"]) == (404, "opportunity_not_found")
        folded = client.get(f"/api/opportunities/{merged.id}/bid-conditions")
        assert (folded.status_code, folded.json()["error"]["code"]) == (409, "opportunity_merged")


def test_bid_conditions_latest_fence_is_what_the_decision_endpoint_accepts(queue_session):
    """List order (bid_no, bid_ord) is display only; the latest fence follows published_at."""
    session = queue_session
    owner = opportunity(session)
    linked_notice(session, owner, source_type="pre_spec", title="최신 사업명")
    latest = linked_notice(session, owner, bid_no="R26BK00001", bid_ord="000",
        published=NOW + timedelta(days=1), sha=SHA_A, title="최신 사업명")
    listed_last = linked_notice(session, owner, bid_no="R26BK00002", bid_ord="000", published=NOW, sha=SHA_B,
        title="이전 사업명")
    session.commit()
    url = f"/api/opportunities/{owner.id}"

    with bid_delta_client(session) as client:
        body = client.get(f"{url}/bid-conditions").json()
        assert [row["notice_id"] for row in body["bid_notices"]] == [latest.id, listed_last.id]
        assert (body["latest_notice_id"], body["latest_observation_sha256"]) == (latest.id, SHA_A)
        assert body["pre_spec_comparison"][1] == {"field": "title", "status": "unchanged",
            "before": "최신 사업명", "after": "최신 사업명"}
        wrong = client.post(f"{url}/final-decisions", json=decision_body(listed_last.id, SHA_B), headers=ACTOR)
        assert (wrong.status_code, wrong.json()["error"]["code"]) == (409, "final_decision_notice_not_latest")
        accepted = client.post(f"{url}/final-decisions", json=decision_body(
            body["latest_notice_id"], body["latest_observation_sha256"]), headers=ACTOR)
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["basis_notice_id"] == latest.id

        # An order that cannot be determined is reported as null, never guessed.
        linked_notice(session, owner, bid_no="R26BK00003", bid_ord="000", published=None, sha=SHA_C)
        session.commit()
        unknown = client.get(f"{url}/bid-conditions").json()
        assert (unknown["latest_notice_id"], unknown["latest_observation_sha256"]) == (None, None)
        assert [(row["status"], row["after"]) for row in unknown["pre_spec_comparison"]] == [
            ("unknown", None), ("unknown", None)]


def test_notice_conditions_decision_is_fenced_replayed_and_superseded(queue_session):
    from app.core.models import AuditEvent
    from app.deep_review.models import BidFinalDecision
    session = queue_session
    owner = opportunity(session)
    pre = linked_notice(session, owner, source_type="pre_spec", sha=SHA_C)
    session.commit()
    url = f"/api/opportunities/{owner.id}/final-decisions"

    def error(response):
        return response.status_code, response.json()["error"]["code"]

    with bid_delta_client(session) as client:
        assert error(client.post(url, json=decision_body(pre.id, SHA_C), headers=ACTOR)) == (
            409, "final_decision_bid_notice_missing")
        bid = linked_notice(session, owner, published=None, sha=SHA_A)
        session.commit()
        assert error(client.post(url, json=decision_body(bid.id, SHA_A), headers=ACTOR)) == (
            503, "bid_delta_currentness_unavailable")
        bid.published_at = NOW
        session.commit()
        assert error(client.post(url, json=decision_body(pre.id, SHA_A), headers=ACTOR)) == (
            409, "final_decision_notice_not_latest")
        assert error(client.post(url, json=decision_body(bid.id, SHA_B), headers=ACTOR)) == (
            409, "final_decision_observation_changed")
        assert error(client.post(url, json=decision_body(bid.id, SHA_A))) == (400, "actor_name_required")
        assert error(client.post(url, json=decision_body(bid.id, SHA_A, reason="  "), headers=ACTOR)) == (
            400, "final_decision_reason_required")
        assert error(client.post(url, json=decision_body(bid.id, SHA_A, decision="hold"), headers=ACTOR)) == (
            422, "final_decision_value_invalid")
        assert client.post(url, json=decision_body(bid.id, "A" * 64), headers=ACTOR).status_code == 422
        assert session.scalar(select(BidFinalDecision.id)) is None

        payload = decision_body(bid.id, SHA_A)
        first = client.post(url, json=payload, headers=ACTOR)
        assert first.status_code == 201, first.text
        view = first.json()
        assert view["schema_version"] == "bidops.bid-final-decision.v2"
        assert view["basis_kind"] == "notice_conditions"
        assert (view["basis_notice_id"], view["basis_observation_sha256"]) == (bid.id, SHA_A)
        assert [view[key] for key in ("comparison_id", "comparison_version", "result_sha256",
            "baseline_document_version_id", "comparison_document_version_id")] == [None] * 5
        assert (view["sequence"], view["currentness"], view["currentness_reasons"]) == (1, "current", [])
        replay = client.post(url, json=payload, headers=ACTOR)
        assert (replay.status_code, replay.json()) == (201, view)
        assert error(client.post(url, json={**payload, "reason": "다른 사유"}, headers=ACTOR)) == (
            409, "idempotency_conflict")
        assert error(client.post(url, json=decision_body(bid.id, SHA_A), headers=ACTOR)) == (
            409, "final_decision_supersession_conflict")
        assert error(client.post(url, json=decision_body(bid.id, SHA_A, supersedes_final_decision_id=str(uuid4())),
            headers=ACTOR)) == (404, "final_decision_not_found")
        second = client.post(url, json=decision_body(bid.id, SHA_A, decision="no_go",
            supersedes_final_decision_id=view["id"]), headers=ACTOR)
        assert second.status_code == 201, second.text
        assert (second.json()["sequence"], second.json()["supersedes_final_decision_id"]) == (2, view["id"])

    rows = session.scalars(select(BidFinalDecision).order_by(BidFinalDecision.sequence)).all()
    assert [(row.sequence, row.decision, row.basis_kind) for row in rows] == [
        (1, "go", "notice_conditions"), (2, "no_go", "notice_conditions")]
    audits = session.scalars(select(AuditEvent).where(AuditEvent.action == "bid_final_decision.recorded")).all()
    assert len(audits) == 2
    assert {audit.safe_metadata["basis_kind"] for audit in audits} == {"notice_conditions"}
    assert all("공고 조건 확인" not in str(audit.safe_metadata) for audit in audits)


def test_notice_conditions_currentness_drives_queue_workspace_and_workload(queue_session, monkeypatch):
    from app.deep_review.models import BidFinalDecision
    from app.deep_review.services import auto_preparation
    # Only bid_final_decision_pending is under test. The pre-spec count reads the
    # screening grade seam, whose tables are absent when this file runs alone.
    monkeypatch.setattr(auto_preparation, "effective_grades", lambda _session, _ids: {})
    session = queue_session
    registry = register_lifecycle_extensions(ExtensionRegistry())
    compared_owner = opportunity(session, created_at=NOW - timedelta(days=1))
    compared, _baseline, _bid = comparison(session, compared_owner)
    decide(session, compared_owner, compared)
    owner = opportunity(session)
    first = linked_notice(session, owner, bid_ord="000", sha=SHA_A)
    session.commit()
    service = BidDeltaService()

    def queue_state():
        rows = {row["opportunity_id"]: row for row in service.decision_queue(session, status="all")["items"]}
        return rows[owner.id]["decision_currentness"], service.decision_queue(session)["total"]

    with bid_delta_client(session) as client:
        assert queue_state() == ("unknown", 1)
        recorded = client.post(f"/api/opportunities/{owner.id}/final-decisions",
            json=decision_body(first.id, SHA_A), headers=ACTOR)
        assert recorded.status_code == 201, recorded.text
        # Decided and current: neither the queue nor the workload count it as pending.
        assert queue_state() == ("current", 0)
        assert registry.workload_counts(session)["bid_final_decision_pending"] == WorkloadCount(0)
        rows = {row["opportunity_id"]: row for row in service.decision_queue(session, status="all")["items"]}
        assert rows[compared_owner.id]["decision_currentness"] == "current"
        assert rows[owner.id]["latest_final_decision"]["decision"] == "go"
        workspace = client.get(f"/api/opportunities/{owner.id}/bid-delta")
        assert workspace.status_code == 200, workspace.text
        assert workspace.json()["latest_final_decision"]["basis_kind"] == "notice_conditions"
        assert (workspace.json()["decision_currentness"], workspace.json()["currentness_reasons"]) == ("current", [])

        observe(session, first, SHA_B, observed_at=NOW + timedelta(hours=2))
        session.commit()
        assert client.get(f"/api/opportunities/{owner.id}/bid-delta").json()["currentness_reasons"] == [
            "notice_observation_changed"]
        second = linked_notice(session, owner, bid_ord="001", published=NOW + timedelta(days=1), sha=SHA_C)
        session.commit()
        stale = client.get(f"/api/opportunities/{owner.id}/bid-delta").json()
        assert (stale["decision_currentness"], stale["currentness_reasons"]) == (
            "stale", ["newer_bid_notice", "notice_observation_changed"])
        assert queue_state() == ("stale", 1)
        assert registry.workload_counts(session)["bid_final_decision_pending"] == WorkloadCount(1)

        renewed = client.post(f"/api/opportunities/{owner.id}/final-decisions", json=decision_body(
            second.id, SHA_C, supersedes_final_decision_id=recorded.json()["id"]), headers=ACTOR)
        assert renewed.status_code == 201, renewed.text
        assert queue_state() == ("current", 0)
        # An undated authoritative notice makes the order unknown, not current or stale.
        linked_notice(session, owner, bid_ord="002", published=None, sha=SHA_A)
        session.commit()
        assert client.get(f"/api/opportunities/{owner.id}/bid-delta").json()["currentness_reasons"] == [
            "ordering_unknown"]
        assert queue_state() == ("unknown", 0)

    # The shared rule stays a constant number of reads as decided opportunities grow.
    def add_decided(count):
        for _ in range(count):
            row = opportunity(session)
            notice = linked_notice(session, row, sha=SHA_A)
            session.add(BidFinalDecision(opportunity_id=row.id, sequence=1, basis_kind="notice_conditions",
                basis_notice_id=notice.id, basis_observation_sha256=SHA_A, decision="go", reason="fixture",
                claimed_name="reviewer", request_id=uuid4(), created_at=NOW))
        session.commit()

    add_decided(1)
    with counted(session) as small:
        service.decision_queue(session, status="all")
    add_decided(20)
    with counted(session) as large:
        service.decision_queue(session, status="all")
    assert len(small) == len(large)
