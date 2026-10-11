"""DEMO-03 STEP-005 company-scoped reads and comparison (spec T6·T7, contract §6·§9·§10).

The world is the STEP-003 company deep-review world (real DEMO-02 registration
of the frozen fixtures, completed v7 overview, ready bundle, demo Luna policy
row) plus extra SW사업대상=Y notices, the other two demo companies and
opportunity links.  Every read here is served from stored rows: fit attempts'
and approved previews' frozen provenance snapshots, never rebuilt.  No model,
transport or network is called (an autouse guard fails the test otherwise).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.model_client import ModelClient
from app.deep_review.models import (
    ContentObject,
    DeepReview,
    DeepReviewApproval,
    DeepReviewAttempt,
    DeepReviewPreview,
    DocumentBundle,
    DocumentBundleItem,
    DocumentVersion,
    EvidenceRef,
    PreSpecCompanyFitAttempt,
    ProfileEvidence,
    ReportRevision,
    ValidationRun,
    WorkJob,
)
from app.deep_review.services import company_fit as fit
from app.deep_review.services import company_projection as projection
from app.deep_review.services.input_versions import canonical_json_hash
from app.lifecycle import register_company
from app.lifecycle.models import Notice, Opportunity, OpportunityLink
from app.lifecycle.services.opportunity_tracking import set_company_tracking
from tests.app.test_company_deep_review_binding import (
    DeepWorld,
    create,
    deep_configure,
    deep_world,
    fail_current_attempt,
    preview,
    ready_bundle,
    retry,
    second_source,
    service,
)
from tests.deep_review.test_company_fit_enqueue import (  # noqa: F401 - shared fixtures
    configure,
    import_company,
    object_store,
    seed_notice,
)
from tests.postgres import migrated_engine, requires_postgres


def _sqlite_engine():
    from tests.app.test_company_deep_review_binding import _sqlite_engine as build

    return build()


@pytest.fixture
def sqlite_engine():
    bind = _sqlite_engine()
    try:
        yield bind
    finally:
        bind.dispose()


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def engine(request):
    if request.param == "postgres":
        with migrated_engine() as bind:
            yield bind
        return
    bind = _sqlite_engine()
    try:
        yield bind
    finally:
        bind.dispose()


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch):
    """Every model/transport entry point fails loudly; teardown asserts zero calls."""

    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("model")
        raise AssertionError("model transport called")

    from app.deep_review.services import luna_client

    monkeypatch.setattr(ModelClient, "for_purpose", classmethod(forbidden))
    monkeypatch.setattr(luna_client.LunaClient, "__init__", forbidden)
    yield calls
    assert calls == []
    get_settings.cache_clear()


# --- world helpers ------------------------------------------------------------------


def http_client(engine, monkeypatch) -> TestClient:
    from app.deep_review.routers import company_reads as router

    monkeypatch.setattr(router, "service", service())
    app = FastAPI()
    app.include_router(router.router)
    app.include_router(router.comparison_router)

    def db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    return TestClient(app)


def enqueue_fit(session: Session, company_id: UUID, notice_id: int) -> UUID:
    result = fit.enqueue_company_fit(session, company_id=company_id, notice_id=notice_id, actor="핏 담당자")
    session.commit()
    return result.attempt_id


def complete_fit(session: Session, attempt_id: UUID, decision: str = "matched") -> dict:
    """Store a valid v2 result as the (absent) worker would; returns the payload."""

    row = session.get(PreSpecCompanyFitAttempt, attempt_id)
    requirement = row.input_jsonb["requirements"][0]["id"]
    confirmed = next(f["fact_key"] for f in row.input_jsonb["profile_facts"]
                     if f["status"] == "confirmed" and f["value"] is not None)
    if decision == "matched":
        reasons = [{"kind": "scope_match", "explanation": "데이터 플랫폼 구축 역량이 있다.",
                    "notice_refs": [requirement], "company_refs": [confirmed], "graph_path_indexes": []}]
        verification = []
    elif decision == "mismatch":
        reasons = [{"kind": "scope_mismatch", "explanation": "주력 영역과 다르다.",
                    "notice_refs": [requirement], "company_refs": [confirmed], "graph_path_indexes": []}]
        verification = []
    else:
        reasons = [{"kind": "information_gap", "explanation": "근거를 확인해야 한다.",
                    "notice_refs": [requirement], "company_refs": [], "graph_path_indexes": []}]
        verification = ["자격 보유 여부 확인"]
    payload = {"schema_version": "bidops.prespec-company-fit-result.v2", "decision": decision,
               "summary": f"{decision} 요약", "reasons": reasons, "verification_items": verification}
    fit.validate_company_fit_result(payload, row.input_jsonb)
    # Same transitions as the worker (the PostgreSQL guard allows only
    # queued → running(lease) → completed).
    row.status, row.lease_owner = "running", "fixture-worker"
    row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=10)
    session.commit()
    session.refresh(row)  # the ORM guard reads the loaded previous status
    row.status, row.result_jsonb, row.result_sha256 = "completed", payload, fit.digest(payload)
    row.lease_owner, row.lease_expires_at, row.completed_at = None, None, datetime.now(UTC)
    session.commit()
    return payload


def fail_fit(session: Session, attempt_id: UUID) -> None:
    row = session.get(PreSpecCompanyFitAttempt, attempt_id)
    row.status, row.error_code, row.completed_at = "failed", "company_fit_execution_failed", datetime.now(UTC)
    session.commit()


def create_review(session: Session, svc, world: DeepWorld, *, company_id=None, notice_id=None, bundle_id=None) -> dict:
    target = DeepWorld(**{**world.__dict__, "company_id": company_id or world.company_id,
                          "notice_id": notice_id or world.notice_id, "bundle_id": bundle_id or world.bundle_id})
    return create(session, svc, target, preview(session, svc, target)["preview_id"])


def complete_review(session: Session, review_id) -> None:
    """Simulate the (STEP-006) worker finishing the current attempt."""

    review = session.get(DeepReview, UUID(str(review_id)))
    attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
    job = session.get(WorkJob, attempt.work_job_id)
    now = datetime.now(UTC)
    attempt.status = review.status = job.status = "completed"
    attempt.completed_at = review.completed_at = job.completed_at = now
    session.commit()


def materialize_report(session: Session, review_id) -> UUID:
    review = session.get(DeepReview, UUID(str(review_id)))
    payload = {
        "schema": "bidops.deep-review-report.v2", "deep_review_id": str(review.id),
        "notice_id": review.notice_id, "bundle_id": str(review.bundle_id),
        "profile_version_id": str(review.profile_version_id), "policy_version_id": str(review.policy_version_id),
        "sections": [], "system_recommendation": "보류", "claims": [], "unknowns": ["확인 필요"],
        "validation_summary": {"status": "passed", "failed": 0, "warnings": 0, "passed": 1},
        "created_at": "2026-10-10T00:00:00+00:00", "quality_status": "unmeasured_reference",
        "coverage": [], "analysis_limitations": [], "generator_version": "narrative-v2",
    }
    revision = ReportRevision(id=uuid4(), deep_review_id=review.id, sequence=1, origin="machine",
                              report_payload=payload, report_sha256=canonical_json_hash(payload))
    session.add(revision)
    session.flush()
    session.add(ValidationRun(id=uuid4(), deep_review_id=review.id, report_revision_id=revision.id,
                              sequence=1, status="passed"))
    session.commit()
    return revision.id


def profile_evidence_ref(session: Session, review_id) -> UUID:
    review = session.get(DeepReview, UUID(str(review_id)))
    row = session.scalars(select(ProfileEvidence).where(
        ProfileEvidence.profile_version_id == review.profile_version_id,
        ProfileEvidence.locator_type == "profile_fact",
    ).order_by(ProfileEvidence.fact_key)).first()
    evidence = EvidenceRef(
        id=uuid4(), deep_review_id=review.id, source_kind="profile", notice_id=review.notice_id,
        profile_version_id=review.profile_version_id, profile_evidence_id=row.id,
        locator_type="profile_fact", locator={"fact_key": row.fact_key}, quote=row.quote,
        source_sha256=row.source_sha256,
    )
    session.add(evidence)
    session.commit()
    return evidence.id


def add_document(session: Session, notice_id: int) -> DocumentVersion:
    content = ContentObject(id=uuid4(), sha256=uuid4().hex + uuid4().hex, size_bytes=10,
                            detected_mime="application/pdf", retention_class="document-source")
    session.add(content)
    session.flush()
    document = DocumentVersion(id=uuid4(), notice_id=notice_id, content_object_id=content.id, version=1,
                               source_kind="manual", original_filename="과업지시서.pdf", role="과업지시서",
                               is_current=True, safety_status="safe")
    session.add(document)
    session.commit()
    return document


def bundle_with_documents(session: Session, world: DeepWorld, document_ids, *, revision: int) -> UUID:
    """A new ready bundle revision over existing documents (one structure per document)."""

    from app.deep_review.models import DocumentStructure

    bundle = DocumentBundle(id=uuid4(), notice_id=world.notice_id, revision=revision, version=1, status="ready",
                            issues_snapshot=[], created_by_name="준비 담당자", confirmed_by_name="준비 담당자",
                            confirmed_at=datetime.now(UTC))
    session.add(bundle)
    session.flush()
    for ordinal, document_id in enumerate(document_ids):
        document = session.get(DocumentVersion, document_id)
        content = session.get(ContentObject, document.content_object_id)
        structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
        if structure is None:
            structure = DocumentStructure(
                id=uuid4(), document_version_id=document.id, source_sha256=content.sha256, payload_sha256="e" * 64,
                extractor_name="fixture", extractor_version="1", page_count=1, block_count=1,
                validation_status="ready", media_type="application/pdf", payload_content_object_id=content.id,
            )
            session.add(structure)
            session.flush()
        session.add(DocumentBundleItem(
            bundle_id=bundle.id, document_version_id=document.id, ordinal=ordinal, document_version_version=1,
            content_object_id=content.id, content_sha256=content.sha256, detected_mime="application/pdf",
            size_bytes=10, original_filename=document.original_filename, source_kind="manual",
            role_at_confirmation=document.role, is_current_at_confirmation=True,
            safety_status_at_confirmation="safe", structure_id_at_confirmation=structure.id,
            structure_payload_sha256=structure.payload_sha256,
        ))
    session.commit()
    return bundle.id


def link_opportunity(session: Session, notice_id: int) -> int:
    opportunity = Opportunity(first_registered_stage="pre_spec")
    session.add(opportunity)
    session.flush()
    session.add(OpportunityLink(opportunity_id=opportunity.id, notice_id=notice_id, stage="notice",
                                link_type="official", status="확정", evidence_external_no=f"fixture-{notice_id}"))
    session.commit()
    return opportunity.id


def decide(session: Session, company_id: UUID, opportunity_id: int, status: str, expected_revision: int = 0) -> None:
    set_company_tracking(session, company_id=company_id, opportunity_id=opportunity_id, status=status,
                         reason="데모 판단", expected_revision=expected_revision, request_id=uuid4(),
                         selected_by="추적 담당자")
    session.commit()


def extra_notice(session: Session, *, sw: str = "Y", title: str = "데모 사전규격", posted=None, deadline=None,
                 source_type: str = "pre_spec", bundle: bool = False) -> int:
    notice, document, _content, _run = seed_notice(session, sw=sw)
    notice.title, notice.published_at, notice.deadline_at, notice.source_type = title, posted, deadline, source_type
    session.flush()
    if bundle:
        ready_bundle(session, notice.id, document.id)
    session.commit()
    return notice.id


def _tamper(session: Session, statement: str, **params) -> None:
    session.execute(text(statement), params)
    session.commit()
    session.expire_all()


def list_ids(payload: dict) -> list[int]:
    return [item["notice_id"] for item in payload["items"]]


# --- T7: population, company scope, filters, order, pagination ------------------------


def test_t7_population_is_every_sw_y_pre_spec_and_never_mixes_companies(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        svc = service()
        other = import_company(session, "demo-public-si")
        session.commit()
        bare = extra_notice(session)  # SW=Y, no execution at all
        excluded = [extra_notice(session, sw="N"), extra_notice(session, sw="unknown"),
                    extra_notice(session, source_type="bid_notice")]
        other_fit = enqueue_fit(session, other.company_id, world.notice_id)
        other_review = create_review(session, svc, world, company_id=other.company_id)
        http = http_client(engine, monkeypatch)

        mine = http.get(f"/api/companies/{world.company_id}/pre-specs")
        assert mine.status_code == 200, mine.text
        body = mine.json()
        assert body["schema_version"] == "bidops.company-pre-spec-list.v1"
        assert sorted(list_ids(body)) == sorted([world.notice_id, bare]) and body["total"] == 2
        assert not set(excluded) & set(list_ids(body))
        assert all(item["fit"] is None and item["review"] is None and item["tracking"] is None
                   for item in body["items"])

        theirs = http.get(f"/api/companies/{other.company_id}/pre-specs").json()
        item = next(row for row in theirs["items"] if row["notice_id"] == world.notice_id)
        assert item["fit"]["attempt_id"] == str(other_fit) and item["fit"]["status"] == "queued"
        assert item["fit"]["decision"] is None and item["fit"]["is_current"] is True
        assert item["review"] == {"review_id": other_review["id"], "status": "queued", "is_current": True}

        own_fit = enqueue_fit(session, world.company_id, world.notice_id)
        own = next(row for row in http.get(f"/api/companies/{world.company_id}/pre-specs").json()["items"]
                   if row["notice_id"] == world.notice_id)
        assert own["fit"]["attempt_id"] == str(own_fit) and own["review"] is None


def test_t7_latest_execution_is_summarised_without_fallback(world_session_reads) -> None:
    session, world, svc, http = world_session_reads
    first = enqueue_fit(session, world.company_id, world.notice_id)
    complete_fit(session, first, "matched")
    base = f"/api/companies/{world.company_id}/pre-specs"
    item = http.get(base).json()["items"][0]
    assert item["fit"] == {"attempt_id": str(first), "status": "completed", "decision": "matched",
                           "summary": "matched 요약", "is_current": True}
    assert list_ids(http.get(base, params={"fit": "matched"}).json()) == [world.notice_id]
    newer = enqueue_fit(session, world.company_id, world.notice_id)
    fail_fit(session, newer)
    item = http.get(base).json()["items"][0]
    assert item["fit"] == {"attempt_id": str(newer), "status": "failed", "decision": None,
                           "summary": None, "is_current": True}
    # The failed latest attempt is not replaced by the older completed one.
    assert http.get(base, params={"fit": "matched"}).json() == {
        "schema_version": "bidops.company-pre-spec-list.v1", "items": [], "total": 0, "limit": 50, "offset": 0}
    # Reviews follow the same rule: latest-created review, its own status.
    first_review = create_review(session, svc, world)
    fail_current_attempt(session, first_review["id"])
    assert http.get(base).json()["items"][0]["review"]["status"] == "failed"


def test_t7_fit_filter_reads_only_current_completed_results(world_session_reads) -> None:
    session, world, _svc, http = world_session_reads
    attempt = enqueue_fit(session, world.company_id, world.notice_id)
    complete_fit(session, attempt, "mismatch")
    base = f"/api/companies/{world.company_id}/pre-specs"
    assert list_ids(http.get(base, params={"fit": "mismatch"}).json()) == [world.notice_id]
    import_company(session, raw=second_source())
    session.commit()
    # The stale completed result is still shown without a filter, never as a current decision.
    item = http.get(base).json()["items"][0]
    assert item["fit"]["decision"] == "mismatch" and item["fit"]["is_current"] is False
    assert http.get(base, params={"fit": "mismatch"}).json()["total"] == 0
    assert session.get(PreSpecCompanyFitAttempt, attempt).result_jsonb["decision"] == "mismatch"


def test_t7_tampered_completed_result_is_never_a_decision(world_session_reads) -> None:
    session, world, _svc, http = world_session_reads
    attempt = enqueue_fit(session, world.company_id, world.notice_id)
    payload = complete_fit(session, attempt, "matched")
    broken = deepcopy(payload)
    broken["summary"] = "다른 요약"
    _tamper(session, "UPDATE prespec_company_fit_attempt SET result_jsonb = :value WHERE id = :id",
            value=json.dumps(broken, ensure_ascii=False), id=attempt.hex)
    item = http.get(f"/api/companies/{world.company_id}/pre-specs").json()["items"][0]
    assert item["fit"]["status"] == "needs_human_review" and item["fit"]["decision"] is None
    view = http.get(f"/api/companies/{world.company_id}/pre-specs/{world.notice_id}/company-fit").json()
    assert view["attempts"][0]["status"] == "needs_human_review"
    assert view["attempts"][0]["error_code"] == "company_fit_validation_failed"
    assert view["attempts"][0]["result"] is None


def test_t7_filters_order_nulls_tiebreak_and_pagination_run_on_the_server(world_reads_any_engine) -> None:
    session, world, _svc, http = world_reads_any_engine
    day = datetime(2026, 10, 6, tzinfo=UTC)
    session.get(Notice, world.notice_id).published_at = day
    session.get(Notice, world.notice_id).deadline_at = day + timedelta(days=9)
    session.commit()
    a = extra_notice(session, title="클라우드 전환 사업", posted=day + timedelta(days=1), deadline=day + timedelta(days=3))
    b = extra_notice(session, title="데이터 품질 진단", posted=day + timedelta(days=1), deadline=None)
    c = extra_notice(session, title="ERP 고도화", posted=None, deadline=day + timedelta(days=3))
    base = f"/api/companies/{world.company_id}/pre-specs"

    # posted_at DESC, nulls last, notice_id DESC tie-break.
    assert list_ids(http.get(base).json()) == [max(a, b), min(a, b), world.notice_id, c]
    # deadline ASC, nulls last, notice_id DESC tie-break.
    assert list_ids(http.get(base, params={"sort": "deadline_asc"}).json()) == [max(a, c), min(a, c), world.notice_id, b]
    page = http.get(base, params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 4 and page["limit"] == 2 and page["offset"] == 1
    assert list_ids(page) == [min(a, b), world.notice_id]
    # q uses the existing list search rule (whitespace/ASCII case folded).
    assert list_ids(http.get(base, params={"q": "erp고도"}).json()) == [c]
    assert http.get(base, params={"q": "데이터 품질"}).json()["total"] == 1

    # tracking: only linked notices carry a company decision; filters before pagination.
    opp_a, opp_c = link_opportunity(session, a), link_opportunity(session, c)
    decide(session, world.company_id, opp_a, "계속 추적")
    other = import_company(session, "demo-public-si")
    session.commit()
    decide(session, other.company_id, opp_c, "보류")
    items = {row["notice_id"]: row for row in http.get(base).json()["items"]}
    assert items[a]["opportunity_id"] == opp_a and items[a]["tracking"]["tracking_status"] == "계속 추적"
    assert items[c]["tracking"]["tracking_status"] == "미선택" and items[c]["tracking"]["revision"] == 0
    assert items[b]["opportunity_id"] is None and items[b]["tracking"] is None
    assert items[a]["tracking"]["company_id"] == str(world.company_id)
    assert list_ids(http.get(base, params={"tracking_status": "계속 추적"}).json()) == [a]
    assert list_ids(http.get(base, params={"tracking_status": "보류"}).json()) == []
    assert list_ids(http.get(base, params={"tracking_status": "미선택"}).json()) == [c]
    other_list = http.get(f"/api/companies/{other.company_id}/pre-specs", params={"tracking_status": "보류"}).json()
    assert list_ids(other_list) == [c]

    # fit filter: current completed results only.
    complete_fit(session, enqueue_fit(session, world.company_id, world.notice_id), "unknown")
    assert list_ids(http.get(base, params={"fit": "unknown"}).json()) == [world.notice_id]
    assert http.get(base, params={"fit": "matched"}).json()["total"] == 0
    for bad in ({"fit": "maybe"}, {"tracking_status": "추적"}, {"sort": "title"}, {"limit": 0},
                {"limit": 501}, {"offset": -1}):
        assert http.get(base, params=bad).status_code == 422, bad


def test_t7_list_has_no_n_plus_one(sqlite_engine, monkeypatch) -> None:
    with Session(sqlite_engine) as session:
        world = deep_world(session, monkeypatch)
        svc = service()

        def add(count: int) -> None:
            for _ in range(count):
                notice_id = extra_notice(session, bundle=True)
                bundle_id = session.scalar(select(DocumentBundle.id).where(DocumentBundle.notice_id == notice_id))
                enqueue_fit(session, world.company_id, notice_id)
                create_review(session, svc, world, notice_id=notice_id, bundle_id=bundle_id)
                decide(session, world.company_id, link_opportunity(session, notice_id), "계속 추적")

        def measure() -> tuple[int, int]:
            statements: list[str] = []

            def count(_conn, _cursor, statement, *_args):
                statements.append(statement)

            event.listen(sqlite_engine, "before_cursor_execute", count)
            try:
                with Session(sqlite_engine) as fresh:
                    payload = projection.company_pre_spec_list(fresh, company_id=world.company_id)
            finally:
                event.remove(sqlite_engine, "before_cursor_execute", count)
            assert all(item["fit"] and item["review"] and item["tracking"] for item in payload["items"][:-1])
            return len(statements), payload["total"]

        add(2)
        small, small_total = measure()
        add(4)
        large, large_total = measure()
        assert (small_total, large_total) == (3, 7)
        assert small == large, (small, large)


# --- T7: comparison ------------------------------------------------------------------


def test_t7_comparison_statuses_priority_and_population(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        svc = service()
        public = import_company(session, "demo-public-si")
        cloud = import_company(session, "demo-cloud-si")
        register_company(session, slug="extra-si", name="추가 SI", is_fictional=True, actor="등록 담당자")
        session.commit()
        opportunity_id = link_opportunity(session, world.notice_id)
        decide(session, public.company_id, opportunity_id, "보류")
        http = http_client(engine, monkeypatch)
        path = f"/api/pre-specs/{world.notice_id}/company-comparison"

        def statuses() -> dict[str, str]:
            body = http.get(path).json()
            return {item["company"]["slug"]: item["comparison_status"] for item in body["items"]}

        body = http.get(path).json()
        assert body["schema_version"] == "bidops.company-comparison.v1" and body["notice_id"] == world.notice_id
        assert [item["company"]["slug"] for item in body["items"]] == ["demo-cloud-si", "demo-data-ai", "demo-public-si"]
        assert body["document_version_ids"] == [str(world.fit.document_id)]
        assert all(item["comparison_status"] == "missing" and item["fit"] is None and item["review"] is None
                   for item in body["items"])
        by_slug = {item["company"]["slug"]: item for item in body["items"]}
        assert by_slug["demo-public-si"]["tracking"]["tracking_status"] == "보류"
        assert by_slug["demo-data-ai"]["tracking"]["tracking_status"] == "미선택"
        assert by_slug["demo-cloud-si"]["graph_version_id"] == str(cloud.graph_version_id)
        assert "score" not in json.dumps(body) and "rank" not in json.dumps(body)

        enqueue_fit(session, world.company_id, world.notice_id)
        create_review(session, svc, world)
        enqueue_fit(session, public.company_id, world.notice_id)
        assert statuses() == {"demo-cloud-si": "missing", "demo-data-ai": "comparable", "demo-public-si": "missing"}
        item = next(i for i in http.get(path).json()["items"] if i["company"]["slug"] == "demo-data-ai")
        assert item["fit"]["status"] == "queued" and item["review"]["status"] == "queued"

        # A new binding makes this company's results stale (old results kept, not replaced).
        import_company(session, raw=second_source())
        session.commit()
        assert statuses()["demo-data-ai"] == "stale"
        # A new common document set outranks stale/missing for companies with executions.
        extra = add_document(session, world.notice_id)
        session.get(DocumentBundle, world.bundle_id).status = "superseded"
        session.commit()
        bundle_with_documents(session, world, [world.fit.document_id, extra.id], revision=2)
        body = http.get(path).json()
        assert body["document_version_ids"] == sorted([str(world.fit.document_id), str(extra.id)])
        assert {i["company"]["slug"]: i["comparison_status"] for i in body["items"]} == {
            "demo-cloud-si": "missing", "demo-data-ai": "different_input", "demo-public-si": "different_input"}


def test_t7_comparison_status_rule_priority() -> None:
    one, two = frozenset({uuid4()}), frozenset({uuid4()})
    rule = projection.comparison_status
    assert rule(one, [(one, True), (one, True)], fit_present=True, review_present=True) == "comparable"
    assert rule(one, [(one, True)], fit_present=True, review_present=False) == "missing"
    assert rule(one, [(one, False)], fit_present=True, review_present=False) == "stale"
    assert rule(one, [(two, True), (one, False)], fit_present=True, review_present=True) == "different_input"
    assert rule(one, [], fit_present=False, review_present=False) == "missing"


def test_t7_comparison_omits_unregistered_demo_slugs_and_unknown_notice(world_reads_any_engine) -> None:
    session, world, _svc, http = world_reads_any_engine
    body = http.get(f"/api/pre-specs/{world.notice_id}/company-comparison").json()
    assert [item["company"]["slug"] for item in body["items"]] == ["demo-data-ai"]
    reply = http.get("/api/pre-specs/999999/company-comparison")
    assert reply.status_code == 404 and reply.json()["error"]["code"] == "not_found"


# --- T7: frozen provenance on GET ----------------------------------------------------


def _identity(view: dict, provenance: dict) -> None:
    for key in ("company_id", "profile_version_id", "graph_version_id", "graph_sha256", "ontology_version",
                "input_sha256"):
        assert view[key] == provenance[key], key


def test_t7_queued_fit_attempt_get_serves_its_frozen_snapshot(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        attempt_id = enqueue_fit(session, world.company_id, world.notice_id)
        row = session.get(PreSpecCompanyFitAttempt, attempt_id)
        stored = deepcopy(row.provenance_jsonb)
        frozen_input = deepcopy(row.input_jsonb)
        http = http_client(engine, monkeypatch)
        reply = http.get(f"/api/companies/{world.company_id}/pre-specs/{world.notice_id}/company-fit")
        assert reply.status_code == 200, reply.text
        body = reply.json()
        assert body["company_id"] == str(world.company_id) and body["notice_id"] == world.notice_id
        view = body["attempts"][0]
        assert view["id"] == str(attempt_id) and view["status"] == "queued" and view["result"] is None
        assert view["provenance"] == json.loads(json.dumps(stored))
        _identity(view, view["provenance"])
        assert view["profile_sha256"] == stored["profile_sha256"] and view["overview_sha256"] == stored["overview_sha256"]
        assert view["model_revision"] is None and view["provenance"]["model_revision"] is None
        assert view["provenance"]["purpose"] == "company_fit" and view["provenance"]["bundle_id"] is None
        assert view["paths"] == frozen_input["graph_paths"] and view["is_current"] is True
        assert view["prompt_version"] == "prespec-company-fit-demo-v2"
        assert "input" not in view and "input_snapshot" not in json.dumps(body)
        # The detail view summarises the same attempt and the current analysis inputs.
        detail = http.get(f"/api/companies/{world.company_id}/pre-specs/{world.notice_id}").json()
        assert detail["fit"]["attempt_id"] == str(attempt_id) and detail["company_id"] == str(world.company_id)
        assert detail["overview_run_id"] == str(world.fit.run_id) and detail["bundle_id"] == str(world.bundle_id)
        assert detail["document_version_ids"] == [str(world.fit.document_id)]


def test_t7_completed_review_get_matches_the_approved_preview_snapshot(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        svc = service()
        frozen = preview(session, svc, world)
        created = create(session, svc, world, frozen["preview_id"])
        complete_review(session, created["id"])
        stored = deepcopy(session.get(DeepReviewPreview, UUID(frozen["preview_id"])).provenance_jsonb)
        http = http_client(engine, monkeypatch)
        reply = http.get(f"/api/companies/{world.company_id}/deep-reviews/{created['id']}")
        assert reply.status_code == 200, reply.text
        view = reply.json()
        assert view["status"] == "completed" and view["current_attempt"]["status"] == "completed"
        assert view["provenance"] == json.loads(json.dumps(stored))
        assert view["input_sha256"] == frozen["input_sha256"] == view["provenance"]["input_sha256"]
        _identity(view, view["provenance"])
        assert view["bundle_id"] == view["provenance"]["bundle_id"] == str(world.bundle_id)
        assert view["is_current"] is True and "input" not in view


def test_t7_identity_mismatch_is_processing_failed_never_repaired(world_session_reads) -> None:
    session, world, svc, http = world_session_reads
    attempt_id = enqueue_fit(session, world.company_id, world.notice_id)
    created = create_review(session, svc, world)
    fit_path = f"/api/companies/{world.company_id}/pre-specs/{world.notice_id}/company-fit"
    review_path = f"/api/companies/{world.company_id}/deep-reviews/{created['id']}"
    assert http.get(fit_path).status_code == 200 and http.get(review_path).status_code == 200

    provenance = deepcopy(session.get(PreSpecCompanyFitAttempt, attempt_id).provenance_jsonb)
    provenance["graph_sha256"] = "f" * 64
    _tamper(session, "UPDATE prespec_company_fit_attempt SET provenance_jsonb = :value WHERE id = :id",
            value=json.dumps(provenance), id=attempt_id.hex)
    reply = http.get(fit_path)
    assert reply.status_code == 500 and reply.json()["error"]["code"] == "processing_failed"
    assert session.get(PreSpecCompanyFitAttempt, attempt_id).provenance_jsonb["graph_sha256"] == "f" * 64

    pid = session.scalar(select(DeepReviewApproval.preview_id)).hex
    preview_provenance = deepcopy(session.get(DeepReviewPreview, UUID(pid)).provenance_jsonb)
    preview_provenance["profile_sha256"] = "e" * 64
    preview_provenance["input_sha256"] = "d" * 64
    _tamper(session, "UPDATE deep_review_preview SET provenance_jsonb = :value WHERE id = :id",
            value=json.dumps(preview_provenance), id=pid)
    reply = http.get(review_path)
    assert reply.status_code == 500 and reply.json() == {
        "error": {"code": "processing_failed", "message": "회사 분석 결과를 처리할 수 없습니다", "details": None},
        "request_id": None}

    # A frozen input whose hash no longer matches is refused the same way.
    restored = session.get(PreSpecCompanyFitAttempt, attempt_id)
    snapshot = deepcopy(restored.input_jsonb)
    snapshot["graph_paths"] = []
    provenance["graph_sha256"] = restored.input_jsonb["graph_sha256"]
    _tamper(session, "UPDATE prespec_company_fit_attempt SET provenance_jsonb = :p, input_jsonb = :i WHERE id = :id",
            p=json.dumps(provenance), i=json.dumps(snapshot, ensure_ascii=False), id=attempt_id.hex)
    assert http.get(fit_path).json()["error"]["code"] == "processing_failed"


# --- §9: foreign ids, DEMO flag, reference/Luna flags --------------------------------------


def test_t7_foreign_and_unknown_ids_are_not_found(world_session_reads) -> None:
    session, world, svc, http = world_session_reads
    other = import_company(session, "demo-public-si")
    session.commit()
    mine = create_review(session, svc, world)
    theirs = create_review(session, svc, world, company_id=other.company_id)
    enqueue_fit(session, other.company_id, world.notice_id)
    evidence = profile_evidence_ref(session, theirs["id"])
    base = f"/api/companies/{world.company_id}"

    def not_found(path: str) -> None:
        reply = http.get(path)
        assert reply.status_code == 404 and reply.json()["error"]["code"] == "not_found", (path, reply.text)

    not_found(f"{base}/deep-reviews/{theirs['id']}")
    not_found(f"{base}/deep-reviews/{theirs['id']}/report")
    not_found(f"{base}/deep-reviews/{mine['id']}/evidence/{evidence}")
    not_found(f"{base}/deep-reviews/{uuid4()}")
    not_found(f"/api/companies/{uuid4()}/pre-specs")
    not_found(f"/api/companies/{uuid4()}/deep-reviews/{mine['id']}")
    not_found(f"{base}/pre-specs/999999")
    not_found(f"{base}/pre-specs/999999/company-fit")
    # Another company's fit attempts never appear under this company.
    assert http.get(f"{base}/pre-specs/{world.notice_id}/company-fit").json()["attempts"] == []


def test_t7_demo_off_is_not_found_and_reads_ignore_reference_and_luna_flags(world_session_reads, monkeypatch) -> None:
    session, world, svc, http = world_session_reads
    attempt_id = enqueue_fit(session, world.company_id, world.notice_id)
    created = create_review(session, svc, world)
    paths = [
        f"/api/companies/{world.company_id}/pre-specs",
        f"/api/companies/{world.company_id}/pre-specs/{world.notice_id}",
        f"/api/companies/{world.company_id}/pre-specs/{world.notice_id}/company-fit",
        f"/api/companies/{world.company_id}/deep-reviews/{created['id']}",
        f"/api/pre-specs/{world.notice_id}/company-comparison",
    ]
    deep_configure(monkeypatch, world, BIDOPS_REFERENCE_WORKFLOW_MODE="false", BIDOPS_LUNA_DEEP_REVIEW_ENABLED="false",
                   BIDOPS_PRESPEC_COMPANY_FIT_ENABLED="false", BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID="")
    for path in paths:
        reply = http.get(path)
        assert reply.status_code == 200, (path, reply.text)
    stale = http.get(paths[3]).json()
    assert stale["is_current"] is False and stale["id"] == created["id"]
    assert http.get(paths[2]).json()["attempts"][0]["id"] == str(attempt_id)
    deep_configure(monkeypatch, world, BIDOPS_DEMO_ENABLED="false")
    for path in paths:
        reply = http.get(path)
        assert reply.status_code == 404 and reply.json()["error"]["code"] == "not_found", path


def test_assembled_app_registers_company_reads_and_hides_them_when_demo_disabled(monkeypatch) -> None:
    from app import deep_review, main as main_module
    from app.main import create_app

    registration = main_module._ROUTER_REGISTRATION
    assert ("deep_review", "company_reads_router") in registration
    assert ("deep_review", "company_comparison_router") in registration
    assert registration.index(("deep_review", "company_comparison_router")) < registration.index(
        ("lifecycle", "pre_specs_router"))
    assert {route.path for route in deep_review.company_reads_router.routes} == {
        "/api/companies/{company_id}/pre-specs",
        "/api/companies/{company_id}/pre-specs/{notice_id}",
        "/api/companies/{company_id}/pre-specs/{notice_id}/company-fit",
        "/api/companies/{company_id}/deep-reviews/{review_id}",
        "/api/companies/{company_id}/deep-reviews/{review_id}/report",
        "/api/companies/{company_id}/deep-reviews/{review_id}/evidence/{evidence_id}",
    }
    assert {route.path for route in deep_review.company_comparison_router.routes} == {
        "/api/pre-specs/{notice_id}/company-comparison"}
    assert {method for route in deep_review.company_reads_router.routes for method in route.methods} == {"GET"}
    configure(monkeypatch, BIDOPS_DEMO_ENABLED="false")
    http = TestClient(create_app(mount_frontend=False))
    for path in (f"/api/companies/{uuid4()}/pre-specs", "/api/pre-specs/1/company-comparison",
                 f"/api/companies/{uuid4()}/deep-reviews/{uuid4()}/report"):
        reply = http.get(path)
        assert reply.status_code == 404 and reply.json() == {"detail": "Not Found"}, path


# --- T6: retry and new binding on GET ----------------------------------------------------


def test_t6_retry_moves_current_attempt_and_its_provenance_while_replay_stays(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        svc = service()
        first = preview(session, svc, world)
        request_id = uuid4()
        created = create(session, svc, world, first["preview_id"], request_id=request_id)
        fail_current_attempt(session, created["id"])
        target = preview(session, svc, world, review_id=UUID(created["id"]))
        attempt = retry(session, svc, world, created["id"], target["preview_id"])
        http = http_client(engine, monkeypatch)
        view = http.get(f"/api/companies/{world.company_id}/deep-reviews/{created['id']}").json()
        assert view["current_attempt"]["id"] == attempt["id"] != created["current_attempt"]["id"]
        stored = session.get(DeepReviewPreview, UUID(target["preview_id"])).provenance_jsonb
        assert view["provenance"] == json.loads(json.dumps(stored))
        assert view["input_sha256"] == target["input_sha256"] != first["input_sha256"]
        # The exact create replay is the stored first response, not the latest GET.
        replay = create(session, svc, world, first["preview_id"], request_id=request_id)
        assert replay == created and replay["current_attempt"]["id"] != view["current_attempt"]["id"]
        assert replay["provenance"]["input_sha256"] == first["input_sha256"]


def test_t6_new_binding_marks_old_results_stale_and_keeps_returning_them(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        svc = service()
        attempt_id = enqueue_fit(session, world.company_id, world.notice_id)
        created = create_review(session, svc, world)
        http = http_client(engine, monkeypatch)
        base = f"/api/companies/{world.company_id}"
        before_fit = http.get(f"{base}/pre-specs/{world.notice_id}/company-fit").json()
        before_review = http.get(f"{base}/deep-reviews/{created['id']}").json()
        assert before_fit["attempts"][0]["is_current"] is True and before_review["is_current"] is True

        rebound = import_company(session, raw=second_source())
        session.commit()
        after_fit = http.get(f"{base}/pre-specs/{world.notice_id}/company-fit").json()
        after_review = http.get(f"{base}/deep-reviews/{created['id']}").json()
        assert after_fit["attempts"][0]["is_current"] is False and after_review["is_current"] is False
        assert {k: v for k, v in after_fit["attempts"][0].items() if k != "is_current"} == {
            k: v for k, v in before_fit["attempts"][0].items() if k != "is_current"}
        assert {k: v for k, v in after_review.items() if k != "is_current"} == {
            k: v for k, v in before_review.items() if k != "is_current"}
        assert after_review["graph_version_id"] == str(world.graph_version_id) != str(rebound.graph_version_id)
        item = http.get(f"{base}/pre-specs").json()["items"][0]
        assert item["fit"]["attempt_id"] == str(attempt_id) and item["fit"]["is_current"] is False
        assert item["review"] == {"review_id": created["id"], "status": "queued", "is_current": False}
        assert http.get(f"{base}/pre-specs", params={"fit": "unknown"}).json()["total"] == 0


# --- report wrapper and evidence -------------------------------------------------------


def test_report_wrapper_not_ready_and_evidence_scope(world_session_reads) -> None:
    session, world, svc, http = world_session_reads
    created = create_review(session, svc, world)
    base = f"/api/companies/{world.company_id}/deep-reviews/{created['id']}"
    reply = http.get(f"{base}/report")
    assert reply.status_code == 409 and reply.json()["error"]["code"] == "review_not_ready"
    complete_review(session, created["id"])
    revision_id = materialize_report(session, created["id"])
    reply = http.get(f"{base}/report")
    assert reply.status_code == 200, reply.text
    wrapper = reply.json()
    from app.deep_review.services.reports import ReportService
    from app.deep_review.schemas.reports import ReportView

    expected = ReportView.model_validate(ReportService().get_report(session, UUID(created["id"]))).model_dump(mode="json")
    assert wrapper == {
        "schema_version": "bidops.company-report-view.v1", "company_id": str(world.company_id),
        "graph_version_id": str(world.graph_version_id), "graph_sha256": created["graph_sha256"],
        "ontology_version": created["ontology_version"], "profile_version_id": str(world.profile_version_id),
        "view": expected,
    }
    assert wrapper["view"]["current_revision_id"] == str(revision_id)
    evidence = profile_evidence_ref(session, created["id"])
    reply = http.get(f"{base}/evidence/{evidence}")
    assert reply.status_code == 200, reply.text
    assert reply.json()["evidence_id"] == str(evidence) and reply.json()["source_kind"] == "profile"
    assert reply.json()["profile_version_id"] == str(world.profile_version_id)
    other = create_review(session, svc, world, company_id=import_company(session, "demo-cloud-si").company_id)
    foreign = profile_evidence_ref(session, other["id"])
    assert http.get(f"{base}/evidence/{foreign}").status_code == 404
    assert http.get(f"{base}/evidence/{uuid4()}").status_code == 404


def test_legacy_id_readers_refuse_company_rows(world_session_reads) -> None:
    from app.deep_review.routers import deep_reviews as legacy_reviews, reports as legacy_reports

    session, world, svc, _http = world_session_reads
    created = create_review(session, svc, world)
    complete_review(session, created["id"])
    materialize_report(session, created["id"])
    evidence = profile_evidence_ref(session, created["id"])
    app = FastAPI()
    app.include_router(legacy_reviews.router)
    app.include_router(legacy_reports.router)
    engine = session.get_bind()

    def db():
        with Session(engine) as fresh:
            yield fresh

    app.dependency_overrides[get_db] = db
    http = TestClient(app)
    for path in (f"/api/deep-reviews/{created['id']}", f"/api/deep-reviews/{created['id']}/report",
                 f"/api/evidence/{evidence}"):
        reply = http.get(path)
        assert reply.status_code == 404 and reply.json()["error"]["code"] == "not_found", (path, reply.text)


@pytest.fixture
def world_session_reads(sqlite_engine, monkeypatch):
    with Session(sqlite_engine) as session:
        world = deep_world(session, monkeypatch)
        yield session, world, service(), http_client(sqlite_engine, monkeypatch)


@pytest.fixture
def world_reads_any_engine(engine, monkeypatch):
    """Same world on SQLite and PostgreSQL: ordering/null handling is engine-sensitive."""

    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        yield session, world, service(), http_client(engine, monkeypatch)
