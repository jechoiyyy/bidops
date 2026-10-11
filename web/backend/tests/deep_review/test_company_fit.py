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
from app.deep_review.models import (
    ContentObject,
    DeepReview,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    PreSpecCompanyFitAttempt,
    PrespecOverviewRun,
    ProfileEvidence,
    ProfileVersion,
    WorkJob,
)
from app.lifecycle.models import Notice
from app.deep_review.services import company_fit as fit, company_fit_runner as worker, effective_grade
from app.deep_review.services.auto_preparation import auto_preparation_fields
from app.deep_review.services.input_versions import import_policy_version, PROFILE_SOURCE_FILE
from app.deep_review.routers.deep_reviews import pre_spec_overview_router


class _FakeStore:
    """암호화 model-response 저장소의 계약만 흉내 내는 fake."""

    def __init__(self) -> None:
        self.calls: list[bytes] = []

    def put_encrypted(self, data: bytes, *, retention_days: int, content_type: str):
        import hashlib

        self.calls.append(data)
        return {
            "encrypted": True,
            "object_key": f"model-response/{uuid4().hex}.bin",
            "object_version_id": "v1",
            "etag": "etag-1",
            "encryption_key_ref": "test-key-ref",
            "plaintext_sha256": hashlib.sha256(data).hexdigest(),
            "plaintext_size_bytes": len(data),
        }


#: 완료된 개요 run의 결과. 회사 핏 입력이 읽는 절·인용 좌표만 담는다.
OVERVIEW_RESULT = {
    "schema_version": "bidops.prespec-overview-claims.v2",
    "business_overview": [{"claim_id": "c1", "text": "업무 시스템을 구축한다.",
                           "evidence": [{"page": 3, "quote": "업무 시스템을 구축한다."}]}],
    "main_tasks": [{"claim_id": "c2", "text": "업무 시스템 구축 과업을 수행한다.",
                    "evidence": [{"page": 3, "quote": "업무 시스템 구축 과업"}]}],
    "budget_and_period": [],
    "input_limitations": ["page_text_only"],
}


def seed_overview_run(session):
    """완료된 개요 run 한 건과 그 공고·문서를 세운다."""

    notice = Notice(notice_key=f"fit:{uuid4()}", source_type="pre_spec", title="합성 사전규격")
    session.add(notice)
    session.flush()
    content = ContentObject(id=uuid4(), sha256="a" * 64, size_bytes=10,
                            detected_mime="application/pdf", retention_class="document-source")
    session.add(content)
    session.flush()
    document = DocumentVersion(id=uuid4(), notice_id=notice.id, content_object_id=content.id, version=1,
                               source_kind="manual", original_filename="제안요청서.pdf", role="제안요청서",
                               is_current=True, safety_status="safe")
    job = WorkJob(job_type="prespec_overview", aggregate_type="prespec_overview_run",
                  aggregate_id=uuid4(), status="completed")
    session.add_all([document, job])
    session.flush()
    run = PrespecOverviewRun(
        id=uuid4(), notice_id=notice.id, document_version_id=document.id, work_job_id=job.id,
        status="completed", range_source="auto", range_reason_codes=[], policy_digest="0" * 64,
        model_name="test-overview", warnings_json=[], reason_codes=[], call_count=1,
        raw_response_refs=[], result_json=deepcopy(OVERVIEW_RESULT),
        checks_json={"overall": "passed"},
        completed_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    return run


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
    source = seed_overview_run(session)
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
        overview_run_id=UUID(inputs["overview_id"]), profile_version_id=UUID(inputs["profile_version_id"]),
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
    """`retry_result`를 주면 두 번째 호출부터 그 결과를 낸다."""

    def __init__(self, result, callback=None, *, retry_result=None, raw_prefix=""):
        self.result, self.calls, self.callback = result, 0, callback
        self.retry_result, self.raw_prefix = retry_result, raw_prefix
        self.seeds, self.corrections = [], []
    def verify_identity(self):
        return ModelIdentity("test-fit", "b" * 64)
    def invoke(self, stage, inputs, policy, *, seed=None, correction=None):
        self.calls += 1
        self.seeds.append(seed)
        self.corrections.append(correction)
        if self.callback:
            self.callback()
        result = self.result if self.calls == 1 or self.retry_result is None else self.retry_result
        return SimpleNamespace(structured_output=result,
                               raw_response=(self.raw_prefix + json.dumps(result)).encode(),
                               prompt_tokens=400, output_tokens=100, latency_ms=20)


def audit_metadata(session, row_id, status):
    """종결 상태를 기록한 감사 이벤트. id는 UUID라 순서 기준이 아니다."""

    from app.core.models import AuditEvent
    rows = [row.safe_metadata for row in session.scalars(select(AuditEvent).where(
        AuditEvent.action == "prespec_company_fit.attempt", AuditEvent.aggregate_id == str(row_id)
    )) if row.safe_metadata["status"] == status]
    assert len(rows) == 1
    return rows[0]


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


def _invalid():
    result = output()
    result["reasons"][0]["notice_refs"] = ["fabricated"]
    return result


def _prepared(session, monkeypatch, client, store=None):
    runner = worker.PreSpecCompanyFitRunner(client=client, raw_response_store=store)
    monkeypatch.setattr(runner, "_enqueue_one", lambda s: None)
    monkeypatch.setattr(runner, "_eligible", lambda s, row: True)
    monkeypatch.setattr(worker, "maybe_auto_start_deep_review", lambda *args: None)
    return runner


def test_invalid_model_response_never_reaches_decision(context, monkeypatch):
    session, inputs = context
    row = enqueue(session, inputs)
    store = _FakeStore()
    client = Client(_invalid())
    assert _prepared(session, monkeypatch, client, store).run_once(session, "test-worker")
    session.refresh(row)
    # 재시도까지 실패하면 자동 보정 없이 사람 검토로 남는다.
    assert row.status == "needs_human_review" and row.result_jsonb is None
    assert client.calls == 2 and client.seeds == [None, 1]
    assert "company_fit_validation_failed" in client.corrections[1]
    assert len(store.calls) == 2 and row.raw_response_sha256
    retry = audit_metadata(session, row.id, "needs_human_review")["validation_retry"]
    assert retry["count"] == 1 and retry["first_error_codes"] == ["company_fit_validation_failed"]
    assert retry["first_raw_response_sha256"] and retry["seed"] == 1


def test_thinking_prefixed_raw_response_is_not_a_mismatch(context, monkeypatch):
    session, inputs = context
    row = enqueue(session, inputs)
    client = Client(output(), raw_prefix="<think>먼저 과업을 읽는다</think>\n")
    assert _prepared(session, monkeypatch, client, _FakeStore()).run_once(session, "test-worker")
    session.refresh(row)
    assert row.status == "completed" and row.error_code is None and client.calls == 1
    assert audit_metadata(session, row.id, "completed")["validation_retry"] is None


def test_company_fit_validation_retry_completes_on_the_second_response(context, monkeypatch):
    session, inputs = context
    row = enqueue(session, inputs)
    store = _FakeStore()
    client = Client(_invalid(), retry_result=output())
    assert _prepared(session, monkeypatch, client, store).run_once(session, "test-worker")
    session.refresh(row)
    assert row.status == "completed" and row.error_code is None
    assert client.calls == 2 and client.seeds == [None, 1]
    # 마지막 응답이 행의 원본이고 첫 응답은 감사에만 남는다.
    assert len(store.calls) == 2 and store.calls[1] == json.dumps(output()).encode()
    retry = audit_metadata(session, row.id, "completed")["validation_retry"]
    assert retry["count"] == 1
    assert retry["first_raw_response_sha256"] != row.raw_response_sha256


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


@pytest.mark.parametrize("status", ["queued", "running", "failed", "cancelled", "needs_human_review"])
def test_a_noncompleted_current_run_blocks_the_fit_input(context, status):
    """현재 run이 완료가 아니면 옛 결과로 내려가지 않는다."""

    session, inputs = context
    row = enqueue(session, inputs)
    run = session.get(PrespecOverviewRun, UUID(inputs["overview_id"]))
    run.status = status
    run.result_json = None
    session.commit()

    assert fit.overview_inputs(session, [inputs["notice_id"]]) == {}
    assert fit.current_flags(session, [row])[row.id] is False
    assert fit.gate_reasons(session, [inputs["notice_id"]]) == {
        inputs["notice_id"]: "company_fit_stale"
    }


def test_the_latest_run_is_the_current_overview_even_with_older_history(context):
    """현재 개요는 `created_at` 최신 run 하나다. 옛 완료 run은 이력이다."""

    session, inputs = context
    current = session.get(PrespecOverviewRun, UUID(inputs["overview_id"]))
    job = WorkJob(job_type="prespec_overview", aggregate_type="prespec_overview_run",
                  aggregate_id=uuid4(), status="completed")
    session.add(job)
    session.flush()
    newer = PrespecOverviewRun(
        id=uuid4(), notice_id=current.notice_id, document_version_id=current.document_version_id,
        work_job_id=job.id, status="needs_human_review", range_source="auto", range_reason_codes=[],
        policy_digest="0" * 64, model_name="test-overview", warnings_json=[], reason_codes=[],
        call_count=1, raw_response_refs=[], result_json=None,
        created_at=current.created_at + timedelta(seconds=1),
    )
    session.add(newer)
    session.commit()

    assert fit.overview_inputs(session, [inputs["notice_id"]]) == {}
    newer.status, newer.result_json = "completed", deepcopy(OVERVIEW_RESULT)
    newer.checks_json = {"overall": "passed"}
    session.commit()
    assert fit.overview_inputs(session, [inputs["notice_id"]])[inputs["notice_id"]].id == newer.id


def test_a_missing_run_is_not_reported_as_a_completed_overview(context):
    """개요 run이 없으면 묶음은 `bundle_ready`에 머문다. 완료로 승격시키지 않는다."""

    session, inputs = context
    ready_bundle(session, inputs)
    session.delete(session.get(PrespecOverviewRun, UUID(inputs["overview_id"])))
    session.commit()

    fields = auto_preparation_fields(session, [inputs["notice_id"]])[inputs["notice_id"]]

    assert fields["grade"] is None
    assert fields["auto_preparation_status"] == "bundle_ready"
    assert fields["auto_preparation_reason"] is None


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
    # ADR-0069 made automatic deep-review start opt-in (default false); this
    # case exercises the opted-in automatic chain, so it states that explicitly.
    monkeypatch.setenv("BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED", "true")
    get_settings.cache_clear()
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
