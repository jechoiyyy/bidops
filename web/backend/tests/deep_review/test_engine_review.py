"""Tracking-entry review through the public API, isolated store and engine worker."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.db import get_db, init_db
from app.core.models import AuditEvent
from app.deep_review.models import (
    AttachmentFetch, CompanyKnowledgeBinding, ContentObjectLocation, ContentScan, DocumentBundle,
    DocumentBundleItem, DocumentStructure, DocumentVersion, EngineReviewAcknowledgment, EngineReviewApproval,
    EngineReviewPreview, EngineReviewRequest, EngineRun, PrespecOverviewRun, ProfileVersion, WorkJob,
)
from app.deep_review.routers.engine_review import router
from app.deep_review.schemas import engine_review as wire
from app.deep_review.services import engine_review as review, engine_review_inputs, engine_runs, overview_runs
from app.deep_review.services.deep_review_hooks import PreSpecAttachmentEligibilityHook
from app.deep_review.services.effective_grade import overview_eligible
from app.deep_review.services.prespec_attachments import SOURCE_SYSTEM, claim_next, refresh_fetch_eligibility
from app.lifecycle.models import Attachment, Company, Notice, NoticeObservation, Opportunity, OpportunityLink, Run
from tests.deep_review.engine_fixtures import seed_engine_input
from tests.deep_review.test_engine_runs import _bundle_dir
from tests.postgres import migrated_engine, requires_postgres


NOW = datetime(2026, 11, 24, 1, tzinfo=UTC)
HEADERS = {"X-BidOps-Actor-Name": "reviewer"}
BASE = "/api/pre-specs"


@pytest.fixture
def company_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("BIDOPS_TEST_MODE", "1")
    monkeypatch.setenv("BIDOPS_OBJECT_STORE_BACKEND", "filesystem")
    monkeypatch.setenv("BIDOPS_ATTACHMENTS_DIR", str(tmp_path))
    monkeypatch.setenv("BIDOPS_ENV", "mock")
    monkeypatch.setenv("BIDOPS_REFERENCE_WORKFLOW_MODE", "true")
    monkeypatch.setenv("BIDOPS_ENGINE_REVIEW_MODE", "mock_reference")
    monkeypatch.setenv("BIDOPS_ENGINE_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "false")
    path = _bundle_dir(tmp_path, monkeypatch)
    yield path
    get_settings.cache_clear()


@pytest.fixture
def clock(monkeypatch):
    moment = [NOW]
    monkeypatch.setattr(review, "_now", lambda: moment[0])
    return moment


@pytest.fixture
def bind(company_bundle, request):
    if getattr(request, "param", "sqlite") == "postgres":
        with migrated_engine() as engine:
            yield engine
        return
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db(bind):
    with Session(bind, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def linked(db, *, notice_id=None, tracking="계속 추적", source_type="pre_spec", registration=None):
    if notice_id is None:
        notice = Notice(
            notice_key=f"engine-review-fixture:{uuid4()}", source_type=source_type,
            deadline_at=NOW - timedelta(days=1), qualification_flags_json={"sw_business_status": "N"},
            lifecycle_json={"pre_spec_no": registration} if registration else None,
        )
        db.add(notice)
        db.flush()
        notice_id = notice.id
    owner = Opportunity(first_registered_stage="pre_spec")
    db.add(owner)
    db.flush()
    db.add(OpportunityLink(
        opportunity_id=owner.id, notice_id=notice_id, stage="notice", link_type="official", status="확정",
        evidence_external_no=f"fixture-{notice_id}",
    ))
    if tracking != "미선택":
        change_tracking(db, owner.id, tracking)
    db.commit()
    return notice_id, owner.id


def change_tracking(db, owner, tracking):
    row = db.get(Opportunity, owner)
    row.tracking_status = tracking
    row.tracking_selected_at = NOW if tracking != "미선택" else None
    row.tracking_selected_by = "tracker" if tracking != "미선택" else None
    row.tracking_reason = "검토" if tracking != "미선택" else None
    db.commit()


@pytest.fixture
def ready(db):
    seed = seed_engine_input(db, register_company=False)
    return linked(db, notice_id=seed["notice_id"])


def path(notice_id):
    return f"{BASE}/{notice_id}/engine-review"


def post(client, notice_id, command, *, actor=HEADERS, **payload):
    payload.setdefault("request_id", str(uuid4()))
    return client.post(f"{path(notice_id)}/{command}", json=payload, headers=actor)


def get_state(client, notice_id):
    result = client.get(path(notice_id))
    assert result.status_code == 200, result.text
    return result.json()


def error(response, status, reason):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == reason


def request(client, notice_id, **options):
    return post(client, notice_id, "requests", origin=options.pop("origin", "manual"), **options)


def preview(client, notice_id):
    response = post(client, notice_id, "previews")
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, notice_id, frozen, **options):
    return post(client, notice_id, "approvals", preview_id=frozen["preview_id"],
                manifest_sha256=frozen["manifest_sha256"], **options)


def ready_for_approval(client, notice_id):
    result = request(client, notice_id)
    assert result.status_code == 201, result.text
    return preview(client, notice_id)


def test_rule_1_ingest_overview_completion_and_tracking_hook_create_no_requests(db, ready, tmp_path):
    notice_id, owner_id = ready
    run = Run(id="review-ingest-fixture", generated_at=NOW)
    db.add(run)
    db.flush()
    db.add(NoticeObservation(notice_id=notice_id, run_id=run.id, observed_at=NOW))
    db.flush()
    hook = PreSpecAttachmentEligibilityHook()
    assert not hook.run_ingested(db, run.id, tmp_path).warnings
    document_id = db.scalar(select(DocumentVersion.id).where(DocumentVersion.notice_id == notice_id))
    job = WorkJob(job_type="prespec_overview", aggregate_type="prespec_overview_run",
                  aggregate_id=uuid4(), status="running")
    db.add(job)
    db.flush()
    row = PrespecOverviewRun(
        notice_id=notice_id, document_version_id=document_id, work_job_id=job.id,
        status="running", range_source="auto", range_reason_codes=[], policy_digest="0" * 64,
        model_name="test-model", warnings_json=[], reason_codes=[], call_count=0,
        raw_response_refs=[], started_at=NOW,
    )
    db.add(row)
    row.result_json = {}
    overview_runs._finish(db, row, "completed", (), lambda: NOW)
    hook.effective_grade_changed(db, [notice_id])
    hook.tracking_decision_changed(db, owner_id)
    db.commit()
    assert count(db, EngineReviewRequest) == 0


@pytest.mark.parametrize("case,code,status", [
    ("untracked", "tracking_required", 409),
    ("excluded", "review_excluded", 409),
    ("old", "notice_not_latest", 409),
    ("unset", "company_bundle_unavailable", 409),
    ("unreadable", "company_bundle_unavailable", 409),
    ("off", "engine_disabled", 503),
    ("mock_switch_off", "engine_disabled", 409),
])
def test_rule_3_request_eligibility(db, client, company_bundle, monkeypatch, case, code, status):
    notice_id, _ = linked(db, tracking="미선택" if case == "untracked" else "계속 추적",
                          registration="R123" if case == "old" else None)
    notice = db.get(Notice, notice_id)
    if case == "excluded":
        notice.review_exclusion_status = "excluded"
        notice.review_exclusion_actor_name = "author"
        notice.review_exclusion_reason = "제외"
        notice.review_exclusion_changed_at = NOW
        db.commit()
    if case == "old":
        linked(db, registration="R123")
    if case == "unset":
        monkeypatch.setenv("BIDOPS_ENGINE_COMPANY_BUNDLE_DIR", "")
    if case == "unreadable":
        (company_bundle / "acme.yaml").unlink()
    if case == "off":
        monkeypatch.setenv("BIDOPS_ENGINE_REVIEW_MODE", "off")
    if case == "mock_switch_off":
        monkeypatch.setenv("BIDOPS_ENGINE_ANALYSIS_ENABLED", "false")
    get_settings.cache_clear()
    error(request(client, notice_id), status, code)
    assert count(db, EngineReviewRequest) == 0


def test_rule_4_request_replay_and_other_request_id_return_one_receipt(db, client):
    notice_id, _ = linked(db)
    request_id = str(uuid4())
    first = request(client, notice_id, request_id=request_id)
    assert first.status_code == 201, first.text
    for retry in (request(client, notice_id, request_id=request_id), request(client, notice_id)):
        assert retry.status_code == 200, retry.text
        assert retry.json()["request"] == first.json()["request"]
    error(request(client, notice_id, request_id=request_id, actor={"X-BidOps-Actor-Name": "other"}),
          409, "idempotency_conflict")
    assert count(db, EngineReviewRequest) == 1


def add_attachment(db, notice_id):
    row = Attachment(notice_id=notice_id, source_system=SOURCE_SYSTEM,
                     source_attachment_key="rfp", source_url="https://example.invalid/rfp.hwpx",
                     file_ext="HWPX")
    db.add(row)
    db.commit()
    return row.id


def test_rule_5_open_request_enables_non_sw_fetch_and_claim_without_overview(db, client, monkeypatch):
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "true")
    get_settings.cache_clear()
    notice_id, owner_id = linked(db)
    attachment_id = add_attachment(db, notice_id)
    assert refresh_fetch_eligibility(db, notice_ids=[notice_id]) == 0
    assert not overview_eligible(db, [notice_id])
    assert request(client, notice_id).status_code == 201
    fetch = db.scalar(select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment_id))
    assert fetch.eligibility_reason == "engine_review_request"
    assert not overview_eligible(db, [notice_id])
    assert claim_next(db, worker_id="fixture", lease_seconds=30, notice_id=notice_id)
    assert count(db, WorkJob) == 0
    other, other_owner = linked(db)
    add_attachment(db, other)
    assert request(client, other).status_code == 201
    change_tracking(db, other_owner, "종료")
    assert claim_next(db, worker_id="fixture", lease_seconds=30, notice_id=other) is None
    assert db.get(Opportunity, owner_id).tracking_status == "계속 추적"


@pytest.mark.parametrize("case,code", [
    ("pending", "documents_pending"),
    ("no_hwp", "original_hwp_required"),
    ("missing_source", "original_hwp_required"),
    ("unsafe", "unsafe_document"),
    ("new_scan", "unsafe_document"),
    ("missing_structure", "structure_unavailable"),
    ("company_missing", "company_bundle_unavailable"),
    ("invalid_profile", "company_bundle_invalid"),
    ("invalid_wiki", "company_bundle_invalid"),
])
def test_rule_6_preview_checks_originals_safety_structure_and_company(
    db, client, company_bundle, case, code,
):
    if case in {"pending", "no_hwp"}:
        notice_id, _ = linked(db)
        if case == "pending":
            add_attachment(db, notice_id)
    else:
        notice_id, _ = linked(db, notice_id=seed_engine_input(db, register_company=False)["notice_id"])
    assert request(client, notice_id).status_code == 201
    if case == "missing_source":
        db.delete(db.scalar(select(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "source")))
    elif case == "unsafe":
        db.scalar(select(DocumentVersion)).safety_status = "blocked"
    elif case == "new_scan":
        document = db.scalar(select(DocumentVersion))
        db.add(ContentScan(
            content_object_id=document.content_object_id, scanner="fixture",
            scanner_version="2", status="infected", safe_result={},
        ))
    elif case == "missing_structure":
        db.delete(db.scalar(select(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "structure")))
    elif case == "company_missing":
        (company_bundle / "acme.yaml").unlink()
    elif case == "invalid_profile":
        (company_bundle / "acme.yaml").write_text("invalid:")
    elif case == "invalid_wiki":
        (company_bundle / "acme" / "categories" / "other.md").write_text("invalid wiki page")
    db.commit()
    error(post(client, notice_id, "previews"), 409, code)
    assert count(db, EngineReviewPreview) == count(db, EngineRun) == 0


@pytest.mark.parametrize("bind", ["sqlite", pytest.param("postgres", marks=requires_postgres)], indirect=True)
def test_preview_does_not_report_hwpx_section_count_as_page_count(db, client, ready, monkeypatch):
    notice_id, _ = ready
    structure = db.scalar(select(DocumentStructure))
    assert structure.media_type == "application/hwp+zip"
    assert structure.page_count > 0  # The bounded extractor counts XML sections here.

    with monkeypatch.context() as legacy:
        legacy.setattr(engine_review_inputs, "_is_hwp_original", lambda _: False)
        old_preview = ready_for_approval(client, notice_id)
        assert get_state(client, notice_id)["preview"]["preview_id"] == old_preview["preview_id"]
    assert old_preview["manifest"]["documents"][0]["page_count"] == structure.page_count
    assert get_state(client, notice_id)["preview"] is None
    error(approve(client, notice_id, old_preview), 409, "input_changed")

    renewed = preview(client, notice_id)
    assert renewed["preview_id"] != old_preview["preview_id"]
    manifest = renewed["manifest"]
    document, = manifest["documents"]
    assert document["page_count"] is None
    assert manifest["sections"] and all(
        section["page_start"] is None and section["page_end"] is None
        for section in manifest["sections"]
    )
    assert approve(client, notice_id, renewed).status_code == 202


def test_rule_6_same_manifest_reused_then_expires_and_can_be_renewed(db, client, ready, clock):
    notice_id, _ = ready
    frozen = ready_for_approval(client, notice_id)
    assert preview(client, notice_id) == frozen
    assert datetime.fromisoformat(frozen["expires_at"]) == NOW + timedelta(hours=24)
    clock[0] += timedelta(hours=24)
    assert get_state(client, notice_id)["preview"] is None
    error(approve(client, notice_id, frozen), 409, "preview_expired")
    renewed = preview(client, notice_id)
    assert renewed["manifest_sha256"] != frozen["manifest_sha256"]
    approved = approve(client, notice_id, renewed)
    assert approved.status_code == 202
    clock[0] += timedelta(hours=24)
    error(post(client, notice_id, "previews"), 409, "preview_expired")
    assert approve(client, notice_id, renewed).json() == approved.json()


@pytest.mark.parametrize("which", ["company", "source", "engine"])
def test_rule_6_changed_frozen_input_rejects_approval(db, client, ready, company_bundle, monkeypatch, which):
    notice_id, _ = ready
    frozen = ready_for_approval(client, notice_id)
    if which == "company":
        edit_wiki(company_bundle)
    if which == "source":
        db.scalar(select(DocumentVersion)).version += 1
        db.commit()
    if which == "engine":
        monkeypatch.setattr(engine_runs, "engine_digest", lambda: "0" * 64)
    error(approve(client, notice_id, frozen), 409, "input_changed")
    assert count(db, EngineReviewApproval) == count(db, EngineRun) == 0


@pytest.mark.parametrize("tracking", ["보류", "종료", "미선택"])
def test_rules_7_and_8_tracking_must_still_allow_approval_and_closure_is_lazy(db, client, ready, tracking):
    notice_id, owner_id = ready
    frozen = ready_for_approval(client, notice_id)
    change_tracking(db, owner_id, tracking)
    state = get_state(client, notice_id)
    assert state["next_action"] is None
    row = db.scalar(select(EngineReviewRequest))
    assert row.closed_at is None
    assert bool(state["request"]) == (tracking == "보류")
    if tracking == "보류":
        assert preview(client, notice_id) == frozen
    error(approve(client, notice_id, frozen), 409, "tracking_required")
    db.refresh(row)
    assert row.closed_reason == (None if tracking == "보류" else "tracking_ended")
    assert count(db, EngineRun) == 0


def test_rule_7_actor_scope_collision_and_identical_preview_replay(db, client, ready):
    notice_id, _ = ready
    frozen = ready_for_approval(client, notice_id)
    error(approve(client, notice_id, frozen, actor={}), 400, "actor_name_required")
    request_id = str(uuid4())
    first = approve(client, notice_id, frozen, request_id=request_id)
    assert first.status_code == 202, first.text
    assert approve(client, notice_id, frozen, request_id=request_id).json() == first.json()
    assert approve(client, notice_id, frozen).json() == first.json()
    error(approve(client, notice_id, frozen, request_id=request_id,
                  actor={"X-BidOps-Actor-Name": "different"}), 409, "idempotency_conflict")
    other, _ = linked(db)
    error(approve(client, other, frozen, request_id=request_id), 409, "idempotency_conflict")
    assert count(db, EngineReviewApproval) == count(db, EngineRun) == count(db, WorkJob) == 1


def test_rule_8_dismissal_replays_and_can_open_a_new_request(db, client, ready):
    notice_id, _ = ready
    frozen = ready_for_approval(client, notice_id)
    request_id = str(uuid4())
    first = post(client, notice_id, "dismissals", preview_id=frozen["preview_id"], request_id=request_id)
    assert first.status_code == 200, first.text
    assert first.json()["request"]["closed_reason"] == "dismissed"
    assert post(client, notice_id, "dismissals", preview_id=frozen["preview_id"],
                request_id=request_id).json() == first.json()
    assert get_state(client, notice_id)["state"] == "not_requested"
    assert request(client, notice_id).status_code == 201
    assert count(db, EngineReviewRequest) == 2 and count(db, EngineRun) == 0


def edit_wiki(path):
    original = path / "acme" / "portfolio" / "P2025-01.md"
    original.write_text(original.read_text() + "\n업무 근거를 추가했다.\n")


def test_rules_9_and_12_wiki_only_mock_runs_and_acknowledges_without_deciding_tracking(
    db, client, ready, company_bundle,
):
    notice_id, owner_id = ready
    assert all(count(db, table) == 0 for table in (Company, ProfileVersion, CompanyKnowledgeBinding))
    before = db.get(Opportunity, owner_id)
    tracking = before.tracking_status, before.tracking_selected_by, before.tracking_selected_at
    frozen = ready_for_approval(client, notice_id)
    manifest = frozen["manifest"]
    assert manifest["planned_calls"] == 0 and manifest["model"] == "mock_reference"
    assert manifest["wiki_pages"] and manifest["wiki_chars"] > 0 and manifest["sections"]
    assert "blocks" not in manifest and "company_bundle" not in manifest
    approved = approve(client, notice_id, frozen)
    assert approved.status_code == 202, approved.text
    run_id = approved.json()["run_id"]
    assert engine_runs.run_once(db, "review-test")
    result = get_state(client, notice_id)["current_result"]
    assert result["id"] == run_id and result["status"] == "partial"
    assert result["quality_status"] == "mock_reference" and result["input_currentness"] == "current"
    row = db.get(EngineRun, UUID(run_id))
    assert row.input_payload["schema_version"] == "bidops.engine-input.v3"
    assert row.input_payload["company_bundle"]["slug"] == result["company_bundle_slug"] == "acme"
    assert row.input_payload["company_name"] == "합성회사"
    assert manifest["wiki_pages"] == result["analysis"]["knowledge"]["pages"]
    for field in ("company_id", "profile_version_id", "profile_sha256", "graph_version_id", "graph_sha256"):
        assert result[field] is None and field not in row.input_payload
    ack_id = str(uuid4())
    ack = post(client, notice_id, "acknowledgments", result_id=run_id, request_id=ack_id)
    assert ack.status_code == 200, ack.text
    assert post(client, notice_id, "acknowledgments", result_id=run_id, request_id=ack_id).json() == ack.json()
    assert get_state(client, notice_id)["review_receipt"] == ack.json()
    db.refresh(before)
    assert (before.tracking_status, before.tracking_selected_by, before.tracking_selected_at) == tracking
    assert all(count(db, table) == 0 for table in (Company, ProfileVersion, CompanyKnowledgeBinding))
    review_events = db.scalars(select(AuditEvent).where(AuditEvent.action.like("engine_review.%"))).all()
    assert {event.action for event in review_events} == {
        "engine_review.requested", "engine_review.preview_created", "engine_review.approved", "engine_review.acknowledged"
    }
    assert all(event.actor_kind == "human" and event.claimed_name == "reviewer" for event in review_events)
    assert all("통합검색" not in str(event.safe_metadata) for event in review_events)
    edit_wiki(company_bundle)
    assert engine_runs.get_run(db, row.id).input_currentness == "stale"
    assert get_state(client, notice_id)["state"] == "stale"
    assert request(client, notice_id).status_code == 201
    assert db.scalar(select(func.count()).select_from(EngineReviewRequest)
                     .where(EngineReviewRequest.closed_reason == "superseded")) == 1


def test_wiki_bundle_unreadable_is_unknown_and_registered_v2_preserves_currentness(
    db, client, company_bundle,
):
    ids = seed_engine_input(db)
    from app.deep_review.schemas.engine_runs import EngineRunCreate

    v2 = engine_runs.create(
        db, company_id=ids["company_id"], notice_id=ids["notice_id"], actor="company",
        payload=EngineRunCreate(request_id=uuid4(), bundle_id=ids["bundle_id"]),
    )
    assert db.get(EngineRun, v2.id).input_payload["schema_version"] == "bidops.engine-input.v2"
    notice_id, _ = linked(db, notice_id=ids["notice_id"])
    v3 = approve(client, notice_id, ready_for_approval(client, notice_id))
    assert v3.status_code == 202, v3.text
    edit_wiki(company_bundle)
    assert engine_runs.get_run(db, v2.id).input_currentness == "current"
    assert engine_runs.get_run(db, UUID(v3.json()["run_id"])).input_currentness == "stale"
    (company_bundle / "acme.yaml").unlink()
    assert engine_runs.get_run(db, UUID(v3.json()["run_id"])).input_currentness == "unknown"
    assert engine_runs.get_run(db, v2.id).input_currentness == "current"


def test_rule_11_off_fails_closed_and_rule_12_live_needs_caps(db, client, ready, monkeypatch):
    # 2026-11-27 (ADR-0081): live previews are open once caps are configured; without them the
    # settings refuse to load, so nothing can be previewed or sent (tests/deep_review/test_engine_live.py).
    notice_id, _ = ready
    frozen = ready_for_approval(client, notice_id)
    monkeypatch.setenv("BIDOPS_ENGINE_REVIEW_MODE", "live")
    with pytest.raises(Exception, match="CAP"):
        Settings()
    for mode, code in (("off", "engine_disabled"),):
        monkeypatch.setenv("BIDOPS_ENGINE_REVIEW_MODE", mode)
        get_settings.cache_clear()
        error(post(client, notice_id, "previews"), 503, code)
        error(approve(client, notice_id, frozen), 503, code)
        if mode == "off":
            assert get_state(client, notice_id) == {
                "state": "not_requested", "next_action": None, "reason": code, "request": None,
                "preview": None, "current_result": None, "review_receipt": None,
            }
            error(request(client, notice_id), 503, code)
        else:
            other, _ = linked(db)
            assert request(client, other).status_code == 201
            assert get_state(client, other)["reason"] == code
    assert count(db, EngineRun) == 0


def test_unknown_review_mode_fails_settings_validation(monkeypatch):
    from pydantic import ValidationError

    monkeypatch.setenv("BIDOPS_ENGINE_REVIEW_MODE", "unknown")
    with pytest.raises(ValidationError, match="engine_review_mode|BIDOPS_ENGINE_REVIEW_MODE"):
        Settings()


def test_states_not_requested_preparing_blocked_and_awaiting_approval(db, client, ready):
    ready_id, _ = ready
    pending_id, _ = linked(db)
    blocked_id, _ = linked(db)
    add_attachment(db, pending_id)
    initial = get_state(client, ready_id)
    assert (initial["state"], initial["next_action"]) == ("not_requested", "request")
    assert request(client, pending_id).status_code == 201
    assert request(client, blocked_id).status_code == 201
    assert request(client, ready_id).status_code == 201
    pending = get_state(client, pending_id)
    blocked = get_state(client, blocked_id)
    awaiting = get_state(client, ready_id)
    assert (pending["state"], pending["reason"]) == ("preparing", "documents_pending")
    assert (blocked["state"], blocked["next_action"], blocked["reason"]) == (
        "blocked", "resolve_exception", "original_hwp_required",
    )
    assert (awaiting["state"], awaiting["next_action"], awaiting["preview"]) == (
        "awaiting_approval", "approve", None,
    )
    assert count(db, EngineReviewPreview) == count(db, WorkJob) == 0


def test_states_queued_running_result_ready_acknowledged_and_stale(db, client, ready, company_bundle):
    notice_id, _ = ready
    response = approve(client, notice_id, ready_for_approval(client, notice_id))
    assert response.status_code == 202, response.text
    assert get_state(client, notice_id)["state"] == "queued"

    def invoke(frozen):
        db.expire_all()
        assert review.review_state(db, notice_id).state == "running"
        return engine_runs.invoke_engine(frozen)

    assert engine_runs.run_once(db, "review-states", invoke=invoke)
    result = get_state(client, notice_id)
    assert (result["state"], result["next_action"]) == ("result_ready", "review_result")
    assert post(client, notice_id, "acknowledgments", result_id=response.json()["run_id"]).status_code == 200
    assert get_state(client, notice_id)["state"] == "acknowledged"
    edit_wiki(company_bundle)
    result = get_state(client, notice_id)
    assert (result["state"], result["next_action"], result["reason"]) == ("stale", "request", "input_changed")


def test_batch_limit_and_item_failure_isolation(db, client):
    notice_id, _ = linked(db)
    untracked, _ = linked(db, tracking="미선택")
    url = f"{BASE}/engine-review/requests:batch"
    batch = {"notice_ids": [untracked, notice_id], "request_id": str(uuid4()), "origin": "tracking_start"}
    result = client.post(url, json=batch, headers=HEADERS)
    assert result.status_code == 200, result.text
    assert [(item["notice_id"], item["outcome"], item["reason"]) for item in result.json()["items"]] == [
        (untracked, "ineligible", "tracking_required"), (notice_id, "requested", None),
    ]
    result = client.post(url, json=batch, headers=HEADERS)
    assert result.json()["items"][1]["outcome"] == "already_requested"
    assert client.post(url, json={**batch, "notice_ids": list(range(201))}, headers=HEADERS).status_code == 422
    assert client.post(url, json={**batch, "notice_ids": []}, headers=HEADERS).status_code == 422
    assert count(db, EngineReviewRequest) == 1 and count(db, EngineReviewApproval) == 0


def test_batch_read_query_count_is_constant_and_does_not_write(db, bind, client):
    ids = [linked(db)[0] for _ in range(12)]
    for notice_id in ids:
        add_attachment(db, notice_id)
        assert request(client, notice_id).status_code == 201
    queries = []

    def count_statements(*args):
        queries.append(args[2].lstrip().split(None, 1)[0].upper())

    event.listen(bind, "before_cursor_execute", count_statements)
    try:
        assert review.review_states(db, ids[:1])[ids[0]].state == "preparing"
        single_count = len(queries)
        queries.clear()
        assert len(review.review_states(db, ids)) == 12
        assert len(queries) == single_count
        assert set(queries) == {"SELECT"}
    finally:
        event.remove(bind, "before_cursor_execute", count_statements)


def test_engine_run_requires_registered_company_or_wiki_scope(db, ready):
    notice_id, _ = ready
    bundle = db.scalar(select(DocumentBundle))
    db.add(EngineRun(
        request_id=uuid4(), notice_id=notice_id, bundle_id=bundle.id,
        engine_version=engine_runs.ENGINE_VERSION, quality_status="mock_reference",
        status="queued", input_sha256="0" * 64, input_payload={}, created_by_name="reviewer",
    ))
    with pytest.raises(IntegrityError, match="ck_engine_run_company_scope"):
        db.flush()
    db.rollback()


@pytest.fixture
def pg(company_bundle):
    with migrated_engine() as engine:
        yield engine


@requires_postgres
def test_postgres_concurrent_requests_and_approvals_have_one_open_row_and_run(pg):
    with Session(pg) as session:
        notice_id, _ = linked(session, notice_id=seed_engine_input(session, register_company=False)["notice_id"])

    def concurrently(fn):
        gate = Barrier(2)

        def call():
            with Session(pg) as session:
                gate.wait(timeout=10)
                return fn(session)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(call) for _ in range(2)]
            return [future.result(timeout=30) for future in futures]

    receipts = concurrently(lambda session: review.request_review(
        session, notice_id, wire.RequestCommand(request_id=uuid4(), origin="manual"),
        "reviewer", include_state=False,
    ))
    assert receipts[0][0].id == receipts[1][0].id
    assert sorted(receipt[1] for receipt in receipts) == [False, True]
    with Session(pg) as session:
        frozen = review.create_preview(session, notice_id, wire.Command(request_id=uuid4()), "reviewer")
    receipts = concurrently(lambda session: review.approve(
        session, notice_id, wire.ApprovalCommand(
            request_id=uuid4(), preview_id=frozen.preview_id, manifest_sha256=frozen.manifest_sha256,
        ), "reviewer",
    ))
    assert receipts[0] == receipts[1]
    with Session(pg) as session:
        assert count(session, EngineReviewRequest) == count(session, EngineReviewApproval) == count(session, EngineRun) == 1
        assert count(session, WorkJob) == 1


@requires_postgres
def test_postgres_partial_unique_index_rejects_direct_open_request_race(pg):
    with Session(pg) as session:
        notice_id, owner_id = linked(session)

    gate = Barrier(2)

    def insert():
        with Session(pg) as session:
            session.add(EngineReviewRequest(
                notice_id=notice_id, opportunity_id=owner_id, company_bundle_slug="acme",
                origin="tracking_start", requested_by="reviewer", requested_at=NOW, request_id=uuid4(),
            ))
            gate.wait(timeout=10)
            try:
                session.commit()
                return "inserted"
            except IntegrityError as error:
                return error.orig.diag.constraint_name

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(insert) for _ in range(2)]
        assert sorted(f.result(timeout=15) for f in futures) == ["inserted", "uq_engine_review_open_notice"]


@requires_postgres
def test_postgres_receipts_are_immutable_and_request_can_only_close_once(pg):
    with Session(pg) as session:
        notice_id, owner_id = linked(session, notice_id=seed_engine_input(session, register_company=False)["notice_id"])
        row, _, _ = review.request_review(
            session, notice_id, wire.RequestCommand(request_id=uuid4(), origin="manual"), "reviewer",
        )
        frozen = review.create_preview(session, notice_id, wire.Command(request_id=uuid4()), "reviewer")
        approved = review.approve(session, notice_id, wire.ApprovalCommand(
            request_id=uuid4(), preview_id=frozen.preview_id, manifest_sha256=frozen.manifest_sha256,
        ), "reviewer")
        with pytest.raises(IntegrityError, match="ck_engine_run_company_scope"), session.begin_nested():
            session.execute(text("""
                INSERT INTO bidops.engine_run
                    (id, request_id, notice_id, bundle_id, engine_version, quality_status, status,
                     input_sha256, input_payload, created_by_name, created_at)
                SELECT :new_id, :request, notice_id, bundle_id, engine_version, quality_status, 'queued',
                       input_sha256, input_payload - 'company_bundle', 'reviewer', CURRENT_TIMESTAMP
                FROM bidops.engine_run WHERE id = :source_id
            """), {"new_id": uuid4(), "request": uuid4(), "source_id": approved.run_id})
        with pytest.raises(DBAPIError, match="engine input immutable"), session.begin_nested():
            session.execute(text(
                "UPDATE bidops.engine_run SET company_bundle_slug = 'wrong' WHERE id = :id"
            ), {"id": approved.run_id})
        assert engine_runs.run_once(session, "pg-review")
        acknowledged = review.acknowledge(
            session, notice_id, wire.AcknowledgmentCommand(request_id=uuid4(), result_id=approved.run_id), "reviewer",
        )
        for table, id_ in {
            "engine_review_preview": frozen.preview_id,
            "engine_review_approval": approved.approval_id,
            "engine_review_acknowledgment": acknowledged.acknowledgment_id,
        }.items():
            for command in (f"UPDATE bidops.{table} SET id = id", f"DELETE FROM bidops.{table}"):
                with pytest.raises(DBAPIError, match="engine review receipt immutable"), session.begin_nested():
                    session.execute(text(command + " WHERE id = :id"), {"id": id_})
        change_tracking(session, owner_id, "종료")
        with pytest.raises(engine_runs.EngineRunError, match="tracking_required"):
            review.create_preview(session, notice_id, wire.Command(request_id=uuid4()), "reviewer")
        session.rollback()
        assert session.get(EngineReviewRequest, row.id).closed_reason == "tracking_ended"
        for command in (
            "UPDATE bidops.engine_review_request SET closed_by = 'different'",
            "UPDATE bidops.engine_review_request SET closed_at = NULL, closed_by = NULL, closed_reason = NULL",
            "DELETE FROM bidops.engine_review_request",
        ):
            with pytest.raises(DBAPIError, match="engine review request immutable"), session.begin_nested():
                session.execute(text(command + " WHERE id = :id"), {"id": row.id})


def test_rule_5_request_prepares_acquired_documents_without_opening_overview(db, client, ready, monkeypatch):
    from app.deep_review.models import PrespecOverviewRun
    from app.deep_review.services import auto_preparation

    notice_id, _ = ready
    bundle = db.scalar(select(DocumentBundle).where(DocumentBundle.notice_id == notice_id))
    db.delete(db.scalar(select(DocumentBundleItem).where(DocumentBundleItem.bundle_id == bundle.id)))
    db.delete(bundle)
    db.flush()
    # Use a document already acquired and scanned. Its attachment carries the
    # source identity the preparation service uses for the ready bundle.
    document = db.scalar(select(DocumentVersion).where(DocumentVersion.notice_id == notice_id))
    attachment = Attachment(notice_id=notice_id, name=document.original_filename)
    db.add(attachment)
    db.flush()
    document.attachment_id = attachment.id
    db.commit()
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "true")
    get_settings.cache_clear()
    assert auto_preparation.maybe_auto_prepare(db, [notice_id])[0].reason == "grade_not_priority"
    assert request(client, notice_id).status_code == 201
    assert get_state(client, notice_id)["state"] == "awaiting_approval"
    assert count(db, PrespecOverviewRun) == 0


def test_rule_7_approval_and_engine_work_roll_back_together(db, client, ready):
    notice_id, _ = ready
    frozen = ready_for_approval(client, notice_id)
    command_id = str(uuid4())

    def fail_receipt(*_):
        raise RuntimeError("test receipt failure")

    event.listen(EngineReviewApproval, "before_insert", fail_receipt)
    try:
        error(approve(client, notice_id, frozen, request_id=command_id), 503, "engine_unavailable")
        assert count(db, EngineReviewApproval) == count(db, EngineRun) == count(db, WorkJob) == 0
    finally:
        event.remove(EngineReviewApproval, "before_insert", fail_receipt)
    assert approve(client, notice_id, frozen, request_id=command_id).status_code == 202
    assert count(db, EngineReviewApproval) == count(db, EngineRun) == count(db, WorkJob) == 1
