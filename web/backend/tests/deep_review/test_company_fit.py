"""Synthetic fit evidence, immutable input, queue and automatic-start contracts."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import Base, get_db
from app.core.model_client import ModelIdentity
from app.deep_review.models import ContentObject, ProfileVersion, ProfileEvidence, PreSpecCompanyFitAttempt, DocumentVersion, DocumentBundle, DocumentBundleItem, DocumentStructure, DeepReview
from app.lifecycle.models import Notice
from app.deep_review.services import company_fit as fit, company_fit_runner as worker, effective_grade
from app.deep_review.services.input_versions import import_policy_version, PROFILE_SOURCE_FILE
from app.deep_review.services.page_overview import import_page_overview
from app.deep_review.routers.deep_reviews import pre_spec_overview_router
from tests.deep_review.test_page_overview import seed, Scanner
from tests.deep_review.test_prespec_overview_runner import _FakeStore
from app.core.object_store import FilesystemObjectStore


def output(decision="matched"):
    kind = {"matched": "scope_match", "mismatch": "scope_mismatch", "unknown": "information_gap"}[decision]
    return {"schema_version": "bidops.prespec-company-fit-result.v1", "decision": decision,
        "summary": "업무 범위를 대조한 결과입니다.",
        "reasons": [{"kind": kind, "explanation": "공고 과업과 확인된 회사 업무 범위를 대조했습니다.",
                     "notice_refs": ["main_tasks:0"], "company_refs": ["company:0"]}],
        "verification_items": ["실제 수행 범위를 확인해 주세요."] if decision == "unknown" else []}


def setup_inputs(session, tmp_path, monkeypatch, *, unknown=False):
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_ENABLED", "true")
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_MODEL", "test-fit")
    monkeypatch.setenv("BIDOPS_REFERENCE_WORKFLOW_MODE", "true")
    monkeypatch.setenv("BIDOPS_VLLM_OVERVIEW_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("BIDOPS_VLLM_OVERVIEW_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("BIDOPS_VLLM_OVERVIEW_MODEL_REVISION", "b" * 64)
    get_settings.cache_clear()
    data = seed(session)
    data["outcome"].update(status="evidence_checks_passed", validation_errors=[])
    source, _ = import_page_overview(session, **data, store=FilesystemObjectStore(tmp_path), scanner=Scanner(), actor="tester")
    fact = {"fact_key": "scope", "status": "unknown" if unknown else "confirmed", "value": None if unknown else "업무 시스템 구축",
            "quote": "합성 회사 근거", "locator": {"fact_key": "scope"}}
    profile = ProfileVersion(id=uuid4(), version=1, label="synthetic", profile_sha256="f" * 64,
        profile_payload={"schema": "bidops.company-profile.v1", "source_file": PROFILE_SOURCE_FILE, "source_sha256": "f" * 64, "facts": [fact]},
        source_kind="company-profile-markdown", created_by_name="tester")
    session.add(profile)
    if not unknown:
        content = ContentObject(id=uuid4(), sha256="f" * 64, size_bytes=10, detected_mime="text/markdown", retention_class="profile-source")
        session.add(content); session.flush()
        session.add(ProfileEvidence(profile_version_id=profile.id, fact_key="scope", content_object_id=content.id,
            source_sha256="f" * 64, locator_type="profile_fact", locator={"fact_key": "scope"}, quote=fact["quote"],
            confirmed_by_name="tester", confirmed_at=datetime.now(UTC)))
    policy = import_policy_version(session, created_by_name="tester")
    monkeypatch.setenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", str(profile.id))
    monkeypatch.setenv("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID", str(policy.id))
    session.commit()
    inputs = fit.frozen_input(session, source.notice_id, fit.overview_inputs(session, [source.notice_id])[source.notice_id])
    return source, profile, policy, inputs


def enqueue(session, inputs):
    row = PreSpecCompanyFitAttempt(id=uuid4(), notice_id=inputs["notice_id"], document_version_id=UUID(inputs["document_version_id"]),
        page_overview_id=UUID(inputs["overview_id"]), profile_version_id=UUID(inputs["profile_version_id"]),
        deep_policy_version_id=UUID(inputs["deep_policy_version_id"]), input_jsonb=inputs, input_sha256=fit.digest(inputs),
        policy_digest=inputs["policy_digest"], model_name=inputs["model_name"], model_revision=inputs["model_revision"],
        quality_status=inputs["quality_status"], status="queued")
    session.add(row); session.commit()
    return row


@pytest.fixture
def context(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source, profile, policy, inputs = setup_inputs(session, tmp_path, monkeypatch)
        monkeypatch.setattr(effective_grade, "priority_notice_ids", lambda s, ids: frozenset(ids))
        monkeypatch.setattr(worker, "priority_notice_ids", lambda s, ids: frozenset(ids))
        from app.deep_review.services import auto_preparation
        monkeypatch.setattr(auto_preparation, "effective_grades", lambda s, ids: {})
        yield session, inputs
    get_settings.cache_clear()
    engine.dispose()


@pytest.mark.parametrize("change", [
    lambda r: r["reasons"][0].update(notice_refs=["other:0"]),
    lambda r: r["reasons"][0].update(company_refs=[]),
    lambda r: r["reasons"][0].update(company_refs=["company:99"]),
    lambda r: r["reasons"][0].update(explanation="수행 실적 999건이 있습니다."),
    lambda r: r.update(summary="회사 수행 실적 999건"),
    lambda r: r.update(decision="mismatch"),
])
def test_unsupported_claims_are_rejected(context, change):
    _, inputs = context
    result = output(); change(result)
    with pytest.raises(ValueError):
        fit.validate_result(result, inputs)


def test_unknown_profile_cannot_be_promoted_to_missing_capability(context):
    _, inputs = context
    inputs = deepcopy(inputs); inputs["company_facts"][0].update(status="unknown", value=None)
    with pytest.raises(ValueError, match="unconfirmed"):
        fit.validate_result(output("mismatch"), inputs)
    assert fit.validate_result(output("unknown"), inputs).decision == "unknown"
    inputs["company_facts"][0]["status"] = "confirmed"
    with pytest.raises(ValueError, match="unconfirmed"):
        fit.validate_result(output("matched"), inputs)
    assert "source_file" not in json.dumps(inputs) and "quote" not in json.dumps(inputs)


def test_number_substrings_and_blank_explanations_are_not_evidence(context):
    _, inputs = context
    inputs = deepcopy(inputs)
    inputs["notice_facts"] = [{"ref": "main_tasks:0", "text": "수행 기간은 60개월이다.", "pages": [3], "block_key": None}]
    result = output()
    result["reasons"][0]["explanation"] = "수행 기간은 6개월이다."
    with pytest.raises(ValueError, match="unsupported_number"):
        fit.validate_result(result, inputs)
    result["reasons"][0]["explanation"] = "   "
    with pytest.raises(ValueError, match="blank_reason"):
        fit.validate_result(result, inputs)


class Client:
    def __init__(self, result, callback=None):
        self.result, self.calls, self.callback = result, 0, callback
    def verify_identity(self):
        return ModelIdentity("test-fit", "b" * 64)
    def invoke(self, stage, inputs, policy):
        self.calls += 1
        if self.callback:
            self.callback()
        return SimpleNamespace(structured_output=self.result, raw_response=json.dumps(self.result).encode(),
                               prompt_tokens=400, output_tokens=100, latency_ms=20)


@pytest.mark.parametrize("decision,reason", [("matched", None), ("mismatch", "company_fit_mismatch"), ("unknown", "company_fit_unknown")])
def test_completed_result_is_immutable_and_gate_requires_current_match(context, monkeypatch, decision, reason):
    session, inputs = context
    row = enqueue(session, inputs)
    client = Client(output(decision))
    runner = worker.PreSpecCompanyFitRunner(client=client, raw_response_store=_FakeStore())
    monkeypatch.setattr(runner, "_enqueue_one", lambda s: None)
    monkeypatch.setattr(runner, "_eligible", lambda s, row: True)
    calls = []
    monkeypatch.setattr(worker, "maybe_auto_start_deep_review", lambda s, n: calls.append(fit.gate_reasons(s, [n])[n]))
    assert runner.run_once(session, "test-worker")
    session.refresh(row)
    assert row.status == "completed" and row.prompt_tokens == 400
    assert fit.gate_reasons(session, [row.notice_id])[row.notice_id] == reason
    assert calls == [reason]
    assert not runner.run_once(session, "test-worker") and client.calls == 1
    assert fit.current_flags(session, [row])[row.id]
    monkeypatch.setenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", str(uuid4()))
    assert fit.gate_reasons(session, [row.notice_id])[row.notice_id] == "company_fit_stale"
    row.error_code = "overwrite"
    with pytest.raises(ValueError, match="immutable"):
        session.flush()


def test_invalid_model_response_never_reaches_decision(context, monkeypatch):
    session, inputs = context
    row = enqueue(session, inputs)
    result = output(); result["reasons"][0]["notice_refs"] = ["fabricated"]
    store = _FakeStore()
    runner = worker.PreSpecCompanyFitRunner(client=Client(result), raw_response_store=store)
    monkeypatch.setattr(runner, "_enqueue_one", lambda s: None)
    monkeypatch.setattr(runner, "_eligible", lambda s, row: True)
    monkeypatch.setattr(worker, "maybe_auto_start_deep_review", lambda *args: None)
    assert runner.run_once(session, "test-worker")
    session.refresh(row)
    assert row.status == "needs_human_review" and row.result_jsonb is None
    assert len(store.calls) == 1 and row.raw_response_sha256


def test_expired_lease_is_terminal_without_retry(context, monkeypatch):
    session, inputs = context
    row = enqueue(session, inputs)
    row.status, row.lease_owner = "running", "lost-worker"
    row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    session.commit()
    runner = worker.PreSpecCompanyFitRunner(client=Client(output()))
    monkeypatch.setattr(runner, "_enqueue_one", lambda s: None)
    assert not runner.run_once(session, "new-worker")
    session.refresh(row)
    assert row.status == "failed" and row.error_code == "lease_expired"
    assert not runner.run_once(session, "new-worker")


def test_source_replacement_invalidates_previous_assessment(context):
    session, inputs = context
    row = enqueue(session, inputs)
    doc = session.get(DocumentVersion, row.document_version_id)
    doc.is_current = False; session.commit()
    assert not fit.current_flags(session, [row])[row.id]


def test_disabled_worker_performs_no_model_or_database_work(monkeypatch):
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_ENABLED", "false")
    get_settings.cache_clear()
    assert not worker.PreSpecCompanyFitRunner().run_once(None, "worker")
    get_settings.cache_clear()


def test_unmeasured_policy_cannot_enable_operating_automation(monkeypatch):
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_ENABLED", "true")
    monkeypatch.setenv("BIDOPS_REFERENCE_WORKFLOW_MODE", "false")
    get_settings.cache_clear()
    assert not worker.PreSpecCompanyFitRunner().run_once(None, "worker")
    assert fit.gate_reasons(None, [1]) == {1: "company_fit_reference_only"}
    get_settings.cache_clear()


def test_unknown_company_information_finishes_without_paying_for_a_model(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, _, inputs = setup_inputs(session, tmp_path, monkeypatch, unknown=True)
        row = enqueue(session, inputs)
        client = Client(output())
        runner = worker.PreSpecCompanyFitRunner(client=client)
        monkeypatch.setattr(runner, "_enqueue_one", lambda s: None)
        monkeypatch.setattr(runner, "_eligible", lambda s, r: True)
        monkeypatch.setattr(worker, "maybe_auto_start_deep_review", lambda *args: None)
        assert runner.run_once(session, "worker")
        session.refresh(row)
        assert row.result_jsonb["decision"] == "unknown" and client.calls == 0
        assert row.prompt_tokens is None and row.raw_response_sha256 is None
    engine.dispose()
    get_settings.cache_clear()


def test_safe_api_missing_pending_and_wrong_notice(context):
    session, inputs = context
    fit.company_fit_view(session, inputs["notice_id"])
    app = FastAPI(); app.include_router(pre_spec_overview_router)
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    assert client.get("/api/pre-specs/99999/company-fit").status_code == 404
    assert client.get("/api/pre-specs/0/company-fit").status_code == 422
    url = f'/api/pre-specs/{inputs["notice_id"]}/company-fit'
    assert client.get(url).json()["attempts"] == []
    enqueue(session, inputs)
    response = client.get(url)
    assert response.status_code == 200
    body = response.json()
    assert body["attempts"][0]["status"] == "queued"
    assert body["attempts"][0]["result"] is None
    assert not any(key in response.text for key in ("source_file", "source_path", "raw_response", "합성 회사 근거", "object_key"))


def ready_bundle(session, inputs):
    notice = session.get(Notice, inputs["notice_id"])
    notice.qualification_flags_json = {"sw_business_status": "Y"}
    doc = session.get(DocumentVersion, UUID(inputs["document_version_id"]))
    structure = DocumentStructure(id=uuid4(), document_version_id=doc.id, source_sha256="a"*64,
        payload_sha256="e"*64, extractor_name="test", extractor_version="v1", page_count=3, block_count=1,
        validation_status="ready", media_type="application/pdf", payload_content_object_id=doc.content_object_id)
    session.add(structure)
    bundle = DocumentBundle(id=uuid4(), notice_id=notice.id, revision=1, version=1, status="ready", issues_snapshot=[],
        created_by_name="auto-preparation", confirmed_by_name="auto-preparation", confirmed_at=datetime.now(UTC))
    session.add(bundle); session.flush()
    session.add(DocumentBundleItem(bundle_id=bundle.id, document_version_id=doc.id, ordinal=0,
        document_version_version=1, content_object_id=doc.content_object_id, content_sha256="a"*64,
        detected_mime="application/pdf", size_bytes=10, original_filename="test.pdf", source_kind="manual",
        role_at_confirmation="제안요청서", is_current_at_confirmation=True, safety_status_at_confirmation="safe",
        structure_id_at_confirmation=structure.id, structure_payload_sha256="e"*64))
    session.commit()
    return bundle


@pytest.mark.parametrize("decision", ["matched", "mismatch", "unknown"])
def test_automatic_queue_and_shared_creation_gate(context, monkeypatch, decision):
    session, inputs = context
    bundle = ready_bundle(session, inputs)
    from app.deep_review.services.auto_preparation import maybe_auto_start_deep_review
    class Service:
        def create_review(self, session, notice_id, bundle_id, actor, request_id, *, actor_kind):
            assert actor_kind == "system"
            review = DeepReview(id=uuid4(), notice_id=notice_id, bundle_id=bundle_id,
                profile_version_id=UUID(inputs["profile_version_id"]), policy_version_id=UUID(inputs["deep_policy_version_id"]),
                effective_grade_at_start="우선 검토", status="queued", requested_by_name=actor)
            session.add(review); session.commit()
            return {"id": str(review.id)}
    monkeypatch.setattr(worker, "maybe_auto_start_deep_review", lambda s, n: maybe_auto_start_deep_review(s, n, service=Service()))
    client = Client(output(decision))
    runner = worker.PreSpecCompanyFitRunner(client=client, raw_response_store=_FakeStore())
    assert runner.run_once(session, "worker")
    assert session.scalar(select(func.count()).select_from(PreSpecCompanyFitAttempt)) == 1
    row = session.scalar(select(PreSpecCompanyFitAttempt))
    assert row.status == "completed"
    assert session.scalar(select(func.count()).select_from(DeepReview)) == (1 if decision == "matched" else 0)
    assert not runner.run_once(session, "worker") and client.calls == 1
