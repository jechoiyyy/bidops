"""Claim diagnostics, versioned readers and pinned failed-attempt PDF access."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.core.models import AuditEvent
from app.core.object_store import ObjectStoreError
from app.deep_review.models import (
    ContentScan, DocumentVersion, PreSpecPageOverview, PrespecOverviewVerification,
    PrespecV4Attempt, PrespecV4PdfSnapshot, WorkJob,
)
from app.deep_review.routers import deep_reviews
from app.deep_review.services import company_fit, prespec_v4_runner
from app.deep_review.services.page_overview import canonical, digest, verified_result_payload, PageOverviewError
from app.deep_review.services.prespec_overview_claim_policy import load_claims_policy
from app.deep_review.services.prespec_overview_claim_validation import (
    parse_claims_draft, validate_claims_deterministically, apply_semantic_review, compose_page_overview,
)
from app.lifecycle.models import Notice
from .test_prespec_v4_runner import _ready_target


@pytest.mark.parametrize("failure", [None, "source_scan", "pdf_scan", "pdf_bytes", "store_error"])
def test_prepared_target_pdf_without_attempt_preserves_safety_boundary(tmp_path, monkeypatch, failure):
    from sqlalchemy import select, func

    engine, session, store, target = _ready_target(tmp_path)
    snapshot = session.get(PrespecV4PdfSnapshot, target.snapshot_id)
    document = session.get(DocumentVersion, target.document_version_id)
    app = FastAPI()
    app.include_router(deep_reviews.pre_spec_overview_router)
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(deep_reviews, "object_store", lambda **_: store)
    if failure in {"source_scan", "pdf_scan"}:
        session.add(ContentScan(content_object_id=(document.content_object_id if failure == "source_scan" else snapshot.pdf_content_object_id),
            scanner="test", scanner_version="1", status="infected", safe_result={},
            scanned_at=datetime.now(UTC) + timedelta(seconds=1)))
        session.commit()
    elif failure == "pdf_bytes":
        original = store.get
        def corrupt(*args, **kwargs):
            data, meta = original(*args, **kwargs)
            return data + b"changed", meta
        monkeypatch.setattr(store, "get", corrupt)
    elif failure == "store_error":
        def unavailable(*args, **kwargs):
            raise ObjectStoreError("secret/path?credential=never-visible")
        monkeypatch.setattr(store, "get", unavailable)
    client = TestClient(app)
    path = f"/api/pre-specs/{target.notice_id}/overview-pages/targets/{target.id}/pdf"
    response = client.get(path)
    expected = 200 if failure is None else 409 if failure == "pdf_bytes" else 503
    assert response.status_code == expected
    if failure is None:
        assert response.content.startswith(b"%PDF-")
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
        other = Notice(notice_key="pre:other-target", title="other", source_type="pre_spec")
        session.add(other); session.commit()
        assert client.get(path.replace(f"/{target.notice_id}/", f"/{other.id}/")).status_code == 404
    else:
        assert "secret" not in response.text and "credential" not in response.text
    assert session.scalar(select(func.count()).select_from(PrespecV4Attempt)) == 0
    assert session.scalar(select(func.count()).select_from(PreSpecPageOverview)) == 0
    session.close(); engine.dispose()


@pytest.fixture
def claim_context(tmp_path, monkeypatch):
    engine, session, store, target = _ready_target(tmp_path)
    snapshot = session.get(PrespecV4PdfSnapshot, target.snapshot_id)
    policy = load_claims_policy()
    binding = prespec_v4_runner.V4ModelBinding(
        provider="test", model_name=policy.document["model_name"], model_digest="a" * 64,
        prompt_version=policy.document["prompt_version"], policy_digest=policy.digest, reference_only=True,
    )
    now = datetime.now(UTC)
    activation = AuditEvent(id=uuid4(), actor_kind="system", action="prespec_v4.activation",
        aggregate_type="prespec_v4_activation", aggregate_id="fixture", safe_metadata={})
    job = WorkJob(id=uuid4(), job_type="prespec_v4_overview", aggregate_type="prespec_v4_target",
        aggregate_id=target.id, status="running", lease_owner="fixture", lease_expires_at=now + timedelta(minutes=20))
    session.add_all([activation, job]); session.flush()
    attempt = PrespecV4Attempt(id=uuid4(), notice_id=target.notice_id, document_version_id=target.document_version_id,
        target_id=target.id, activation_id=activation.id, work_job_id=job.id, sequence=1,
        source_sha256=snapshot.source_sha256, pdf_sha256=snapshot.pdf_sha256,
        input_sha256=target.input_sha256, selection_manifest_sha256=target.selection_manifest_sha256,
        policy_digest=policy.digest, model_name=binding.model_name, model_digest=binding.model_digest,
        prompt_version=binding.prompt_version, provider=binding.provider, binding_digest=binding.binding_digest,
        reference_only=True, deployable=False, quality_status="unmeasured_reference", status="running",
        started_at=now, lease_owner="fixture", lease_expires_at=job.lease_expires_at)
    session.add(attempt); session.commit()
    monkeypatch.setattr(prespec_v4_runner, "resolve_model_endpoint", lambda _: SimpleNamespace(model_revision="a" * 64))
    app = FastAPI(); app.include_router(deep_reviews.pre_spec_overview_router)
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(deep_reviews, "object_store", lambda **_: store)
    yield SimpleNamespace(session=session, store=store, target=target, snapshot=snapshot,
        attempt=attempt, job=job, client=TestClient(app))
    session.close(); engine.dispose()


def finish_claims(ctx, *, passed):
    draft = parse_claims_draft({"schema_version": "bidops.prespec-overview-claims.v1", "claims": [
        {"id": "c1", "section": "business_overview", "text": "감리 개요", "evidence": [{"page": 2, "quote": "감리 개요"}], "quantities": []},
        {"id": "c2", "section": "main_tasks", "text": "감리 범위", "evidence": [{"page": 2, "quote": "감리 범위"}], "quantities": []},
    ], "analysis": [], "unknowns": []})
    pages = {2: "Ⅰ. 감리 개요\n1. 목적\n본문\n2. 범위\n감리 범위\nⅡ. 제안요청 사항\n다음 장"}
    a = ctx.attempt
    checks = validate_claims_deterministically(draft, pages, attempt_id=a.id, input_sha256=a.input_sha256,
        policy_digest=a.policy_digest, binding_digest=a.binding_digest)
    checks = apply_semantic_review(draft, checks, {"schema_version": "bidops.prespec-overview-semantic.v1",
        "checks": [{"claim_id": claim.id, "status": "supported" if passed else "insufficient",
                    "reason_codes": [] if passed else ["insufficient_evidence"]} for claim in draft.claims],
        "analysis_checks": [], "unknown_checks": []})
    verification = PrespecOverviewVerification(id=uuid4(), attempt_id=a.id, schema_version=checks.schema_version,
        draft_sha256=checks.draft_sha256, input_sha256=a.input_sha256, policy_digest=a.policy_digest,
        binding_digest=a.binding_digest, model_digest=a.model_digest, validator_version=checks.validator_version,
        payload_jsonb=checks.model_dump(mode="json"), payload_sha256=digest(canonical(checks.model_dump(mode="json"))), overall=checks.overall)
    ctx.session.add(verification); ctx.session.flush()
    result = None
    if passed:
        payload = compose_page_overview(draft, checks, verification_id=verification.id, input_limitations=["PDF 일부 검토"])
        value = payload.model_dump(mode="json")
        result = PreSpecPageOverview(id=uuid4(), run_id=a.id, notice_id=a.notice_id, document_version_id=a.document_version_id,
            pdf_location_id=ctx.snapshot.pdf_location_id, input_location_id=ctx.target.manifest_location_id,
            schema_version=payload.schema_version, source_sha256=a.source_sha256, pdf_sha256=a.pdf_sha256,
            payload_jsonb=value, payload_sha256=digest(canonical(value)), import_sha256=digest(canonical(value)),
            input_sha256=a.input_sha256, model_digest=a.model_digest, policy_digest=a.policy_digest,
            model_name=a.model_name, prompt_version=a.prompt_version, pdf_page_count=2, reviewed_pages=[2],
            validation_status="passed", validation_errors=[], evidence_check_status="passed", evidence_check_errors=[],
            validator_version=checks.validator_version, quality_status="unmeasured_reference",
            verification_id=verification.id, verification_sha256=verification.payload_sha256)
        ctx.session.add(result); ctx.session.flush()
        a.result_id, a.result_sha256 = result.id, result.payload_sha256
    a.status = "completed" if passed else "needs_human_review"
    a.completed_at = ctx.job.completed_at = datetime.now(UTC)
    a.lease_owner = ctx.job.lease_owner = None
    a.lease_expires_at = ctx.job.lease_expires_at = None
    ctx.job.status = "completed" if passed else "failed"
    ctx.job.last_error_code = None if passed else "claim_verification_required"
    a.error_code = ctx.job.last_error_code
    ctx.session.commit()
    return verification, result


def test_failed_claim_diagnostics_and_attempt_pdf_are_safe(claim_context, monkeypatch):
    ctx = claim_context
    verification, _ = finish_claims(ctx, passed=False)
    url = f"/api/pre-specs/{ctx.attempt.notice_id}/overview-pages"
    assert ctx.client.get(url).status_code == 409
    assert ctx.client.get(url).json()["error"]["code"] == "overview_contract_upgrade_required"
    response = ctx.client.get(url + "/v2")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["current"]["status"] == "needs_human_review"
    assert value["current"]["result_id"] is None and value["reviews"] == []
    assert value["verification"]["verification_id"] == str(verification.id)
    assert value["verification"]["claims"][0]["verified_evidence"][0]["page"] == 2
    assert "insufficient_evidence" in value["verification"]["claims"][0]["reason_codes"]
    for key in ("raw_response", "object_key", "model-response/", "input_location", "prompt_sha256"):
        assert key not in response.text
    pdf_url = url + f"/attempts/{ctx.attempt.id}/pdf"
    pdf = ctx.client.get(pdf_url)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert pdf.headers["cache-control"] == "private, no-store"
    other = Notice(notice_key="pre:other", source_type="pre_spec")
    ctx.session.add(other); ctx.session.commit()
    assert ctx.client.get(f"/api/pre-specs/{other.id}/overview-pages/attempts/{ctx.attempt.id}/pdf").status_code == 404
    def unavailable(*args, **kwargs):
        assert kwargs["version_id"] is not None
        raise ObjectStoreError("secret/token/internal-path")
    monkeypatch.setattr(ctx.store, "get", unavailable)
    failed = ctx.client.get(pdf_url)
    assert failed.status_code == 503 and "secret" not in failed.text


def test_verified_v4_is_shared_with_company_fit_and_tampering_is_closed(claim_context):
    ctx = claim_context
    verification, result = finish_claims(ctx, passed=True)
    response = ctx.client.get(f"/api/pre-specs/{result.notice_id}/overview-pages/v2")
    assert response.status_code == 200, response.text
    assert response.json()["current"]["status"] == "completed"
    assert response.json()["reviews"][0]["quality_status"] == "unmeasured_reference"
    facts = company_fit.overview_inputs(ctx.session, [result.notice_id])[result.notice_id].facts
    assert facts[0]["pages"] == [2] and facts[0]["text"] == "감리 개요"
    detached = SimpleNamespace(**{col.name: deepcopy(getattr(result, col.name)) for col in result.__table__.columns})
    detached.payload_jsonb["main_tasks"][0]["text"] = "검증 뒤 추가한 사실"
    detached.payload_sha256 = digest(canonical(detached.payload_jsonb))
    with pytest.raises(PageOverviewError, match="result_integrity_failed"):
        verified_result_payload(detached, verification)


def test_new_manual_range_keeps_old_verified_result_in_history_not_current(claim_context):
    from app.deep_review.services.prespec_v4_range import confirm_v4_range
    ctx = claim_context
    verification, result = finish_claims(ctx, passed=True)
    old = (ctx.attempt.status, ctx.attempt.result_id, result.payload_sha256, verification.payload_sha256)
    assert company_fit.overview_inputs(ctx.session, [result.notice_id])[result.notice_id] is not None
    confirmed = confirm_v4_range(ctx.session, ctx.store, notice_id=result.notice_id,
        target_id=ctx.target.id, actor="tester", first_page=2, last_page=2)
    ctx.session.commit()
    response = ctx.client.get(f"/api/pre-specs/{result.notice_id}/overview-pages/v2")
    assert response.status_code == 200
    value = response.json()
    assert value["current"]["status"] == "stale" and value["current"]["result_id"] is None
    assert value["current"]["reason_code"] == "target_superseded"
    assert value["current"]["verification_status"] is None and value["verification"] is None
    assert value["reviews"][0]["id"] == str(result.id)
    assert value["reviews"][0]["quality_status"] == "unmeasured_reference"
    assert value["range_review"]["target_id"] == str(confirmed.target_id)
    assert company_fit.overview_inputs(ctx.session, [result.notice_id]).get(result.notice_id) is None
    assert old == (ctx.attempt.status, ctx.attempt.result_id, result.payload_sha256, verification.payload_sha256)


def test_failed_attempt_pdf_rechecks_latest_scan(claim_context):
    ctx = claim_context
    finish_claims(ctx, passed=False)
    ctx.session.add(ContentScan(content_object_id=ctx.snapshot.pdf_content_object_id,
        scanner="test", scanner_version="2", status="infected", safe_result={}))
    ctx.session.commit()
    response = ctx.client.get(f"/api/pre-specs/{ctx.attempt.notice_id}/overview-pages/attempts/{ctx.attempt.id}/pdf")
    assert response.status_code == 503 and response.json()["error"]["code"] == "pdf_unavailable"


def test_input_capacity_failure_is_exposed_as_safe_failed_attempt(claim_context):
    ctx = claim_context
    ctx.session.refresh(ctx.attempt)
    ctx.session.refresh(ctx.job)
    ctx.attempt.status = "failed"
    ctx.attempt.error_code = "input_capacity_exceeded"
    ctx.attempt.completed_at = datetime.now(UTC)
    ctx.attempt.lease_owner = None
    ctx.attempt.lease_expires_at = None
    ctx.job.status = "failed"
    ctx.job.last_error_code = "input_capacity_exceeded"
    ctx.job.completed_at = ctx.attempt.completed_at
    ctx.job.lease_owner = None
    ctx.job.lease_expires_at = None
    ctx.session.commit()

    response = ctx.client.get(
        f"/api/pre-specs/{ctx.attempt.notice_id}/overview-pages/v2"
    )

    assert response.status_code == 200, response.text
    value = response.json()
    assert value["current"] == {
        "attempt_id": str(ctx.attempt.id),
        "status": "failed",
        "result_id": None,
        "reason_code": "input_capacity_exceeded",
        "prompt_version": ctx.attempt.prompt_version,
        "created_at": ctx.attempt.created_at.isoformat().replace("+00:00", "Z"),
        "verification_status": None,
    }
    assert value["reviews"] == []
    assert value["verification"] is None
    for forbidden in ("raw_response", "object_key", "model-response/", "input_location", "secret"):
        assert forbidden not in response.text
