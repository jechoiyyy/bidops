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


def add_bid(session, owner, *, published=NOW, kind="official", status="확정", human=None):
    notice = Notice(notice_key=f"queue:{uuid4()}", source_type="bid_notice", published_at=published)
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


def test_workload_registration_counts_unlinked_non_sw_prespecs(queue_session, monkeypatch):
    from app.deep_review.services import auto_preparation
    # The ready/settled state is independent of screening availability and grade.
    monkeypatch.setattr(auto_preparation, "effective_grades", lambda _session, _ids: {})
    session = queue_session
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
    owner = opportunity(session)
    add_bid(session, owner)
    session.commit()
    projection = PreSpecOverviewDocumentProjection()
    assert projection.notice_ids_for_auto_preparation_status(session, [ready.id], "deep_review_ready_for_click") == [ready.id]
    registry = register_lifecycle_extensions(ExtensionRegistry())
    register_lifecycle_extensions(registry)
    counts = registry.workload_counts(session)
    assert counts == {"pre_spec_deep_review_ready": WorkloadCount(1), "bid_final_decision_pending": WorkloadCount(1)}
    assert registry.notice_ids_for_auto_preparation_status(session, [ready.id], "not_applicable") == []


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
    assert BidDeltaService().decision_queue(session)["total"] == 0


def test_workload_empty_counts_are_integer_zero(queue_session):
    counts = register_lifecycle_extensions(ExtensionRegistry()).workload_counts(queue_session)
    assert counts == {"pre_spec_deep_review_ready": WorkloadCount(0), "bid_final_decision_pending": WorkloadCount(0)}


def test_currentness_detects_new_bundle_version_without_new_revision(queue_session):
    session = queue_session
    owner = opportunity(session)
    compared, baseline, _bid = comparison(session, owner)
    baseline["bundle"].version = 2
    session.commit()
    assert BidDeltaService()._currentness(session, compared) == ("stale", ["newer_ready_document_version"])
