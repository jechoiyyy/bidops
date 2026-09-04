"""Focused T6 report/evidence API service coverage."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db, init_db
from app.core.models import AuditEvent
from app.deep_review.models import (
    ContentScan,
    DeepReview,
    DeepReviewAttempt,
    DocumentBundleItem,
    DocumentVersion,
    EvidenceRef,
    ReportRevision,
    ValidationRun,
    WorkJob,
)
from app.deep_review.schemas.document_bundles import DocumentStructurePageView
from app.deep_review.schemas.reports import FinalOpinionRequest, ReportRevisionRequest
from app.deep_review.services.evidence import EvidenceService, EvidenceServiceError, _safe_locator
from app.deep_review.services.deep_reviews import JobClaim, StaleFenceError
from app.deep_review.services.reports import ReportService, ReportServiceError
from app.deep_review.routers.reports import router as reports_router


@pytest.fixture
def report_context():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    now = datetime.now(UTC)
    review_id, bundle_id, profile_id, policy_id, attempt_id, job_id = (uuid4() for _ in range(6))
    stage_ids = [uuid4() for _ in range(3)]
    claim_id, evidence_id, profile_evidence_id, content_id = (uuid4() for _ in range(4))
    tables = Base.metadata.tables
    with engine.begin() as connection:
        connection.execute(tables["run"].insert(), {"id": "report-run", "generated_at": now, "timezone": "UTC", "status": "active"})
        connection.execute(tables["notice"].insert(), {"id": 1, "run_id": "report-run", "notice_key": "report-notice"})
        connection.execute(tables["document_bundle"].insert(), {"id": bundle_id, "notice_id": 1, "revision": 1, "version": 1, "status": "ready", "issues_snapshot": {}, "confirmed_by_name": "운영자", "confirmed_at": now})
        connection.execute(tables["profile_version"].insert(), {"id": profile_id, "version": 1, "label": "fixture", "profile_payload": {"facts": []}, "profile_sha256": "a" * 64, "source_kind": "fixture"})
        connection.execute(tables["analysis_policy_version"].insert(), {"id": policy_id, "version": 1, "label": "fixture", "model_endpoint_ref": "fixture", "model_name": "fixture", "prompts": {}, "validation_rules": {}, "policy_sha256": "b" * 64})
        connection.execute(tables["content_object"].insert(), {"id": content_id, "sha256": "c" * 64, "size_bytes": 1, "detected_mime": "text/plain", "retention_class": "fixture"})
        connection.execute(tables["profile_evidence"].insert(), {"id": profile_evidence_id, "profile_version_id": profile_id, "fact_key": "fixture.fact", "content_object_id": content_id, "source_sha256": "c" * 64, "locator_type": "profile_fact", "locator": {"fact_key": "fixture.fact"}, "quote": "확인된 fixture 사실", "confirmed_by_name": "운영자", "confirmed_at": now})
        connection.execute(tables["work_job"].insert(), {"id": job_id, "job_type": "deep_review", "aggregate_type": "deep_review", "aggregate_id": review_id, "status": "running", "lease_owner": "worker-report", "lease_expires_at": now + timedelta(minutes=5), "lease_fence": 1, "scheduled_at": now})
        connection.execute(tables["deep_review"].insert(), {"id": review_id, "notice_id": 1, "bundle_id": bundle_id, "profile_version_id": profile_id, "policy_version_id": policy_id, "effective_grade_at_start": "우선 검토", "status": "running", "current_attempt_id": attempt_id, "created_at": now})
        connection.execute(tables["deep_review_attempt"].insert(), {"id": attempt_id, "deep_review_id": review_id, "sequence": 1, "status": "running", "work_job_id": job_id, "lease_fence": 1, "started_at": now})
        stage_names = ["requirements_and_evaluation", "delivery_risk_economics", "synthesis_and_validation"]
        for sequence, (stage_id, stage_name) in enumerate(zip(stage_ids, stage_names), 1):
            connection.execute(tables["deep_review_stage"].insert(), {"id": stage_id, "attempt_id": attempt_id, "stage": stage_name, "sequence": sequence, "status": "completed", "structured_output": {"schema": "bidops.deep-review-stage.v1", "unknowns": [], "warnings": []}, "invocation_metadata": {}, "completed_at": now})
        connection.execute(tables["evidence_ref"].insert(), {"id": evidence_id, "deep_review_id": review_id, "source_kind": "profile", "notice_id": 1, "profile_version_id": profile_id, "profile_evidence_id": profile_evidence_id, "locator_type": "profile_fact", "locator": {"fact_key": "fixture.fact"}, "quote": "확인된 fixture 사실", "confidence": 0.9, "source_sha256": "c" * 64})
        connection.execute(tables["claim"].insert(), {"id": claim_id, "deep_review_id": review_id, "stage_id": stage_ids[0], "category": "eligibility", "claim_type": "fact", "body": "확인된 fixture 주장", "status": "supported", "premise_claim_ids": [], "reason": None})
        connection.execute(tables["claim_evidence"].insert(), {"deep_review_id": review_id, "claim_id": claim_id, "evidence_ref_id": evidence_id, "ordinal": 0})
    return {"engine": engine, "review_id": review_id, "bundle_id": bundle_id, "profile_id": profile_id, "profile_evidence_id": profile_evidence_id, "evidence_id": evidence_id, "policy_id": policy_id, "attempt_id": attempt_id, "job_id": job_id}


def materialize(context: dict[str, object]) -> dict[str, object]:
    with Session(context["engine"]) as session:
        if session.scalar(select(func.count()).select_from(ReportRevision)):
            return ReportService().get_report(session, context["review_id"])
        claim = JobClaim(context["job_id"], context["review_id"], context["attempt_id"], "worker-report", 1)
        view = ReportService().materialize_machine_report(session, claim)
        review = session.get(DeepReview, context["review_id"])
        attempt = session.get(DeepReviewAttempt, context["attempt_id"])
        job = session.get(WorkJob, context["job_id"])
        assert review is not None and attempt is not None and job is not None
        review.status = "completed"; review.completed_at = datetime.now(UTC)
        attempt.status = "completed"; attempt.completed_at = datetime.now(UTC)
        job.status = "completed"; job.completed_at = datetime.now(UTC); job.lease_expires_at = None
        session.commit()
        return ReportService().get_report(session, context["review_id"])


def revision_request(view: dict[str, object], evidence_id: UUID, *, request_id: UUID | None = None, reason: str = "근거를 보완했습니다") -> ReportRevisionRequest:
    report = deepcopy(view["report"])
    report["sections"][0]["blocks"][0]["body"] = "사람이 확인한 전체 snapshot 의견"
    return ReportRevisionRequest.model_validate({
        "request_id": request_id or uuid4(), "base_revision_id": view["current_revision_id"],
        "report": report, "reason": reason, "factual_change_evidence_ids": [str(evidence_id)],
    })


def test_machine_report_has_exact_sections_and_immutable_hash(report_context):
    first = materialize(report_context)
    assert len(first["report"]["sections"]) == 13
    assert {item["section_key"] for item in first["report"]["sections"]} == {
        "project_overview", "eligibility_matrix", "scope_deliverables", "requirements_matrix", "evaluation_strategy",
        "delivery_plan", "technical_integration_risks", "security_legal_contract_risks", "economics_scenarios",
        "competitive_proposal_strategy", "questions_internal_actions", "document_bundle_limitations", "decision_card",
    }
    expected_hash = hashlib.sha256(json.dumps(first["report"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with Session(report_context["engine"]) as session:
        row = session.get(ReportRevision, UUID(first["current_revision_id"]))
        assert row is not None and row.report_sha256 == expected_hash and row.origin == "machine"
        assert session.scalar(select(func.count()).select_from(ReportRevision)) == 1
        machine_audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "deep_review.report.machine_materialized"))
        assert machine_audit is not None and machine_audit.actor_kind == "system" and machine_audit.claimed_name is None
        assert set(machine_audit.safe_metadata) <= {
            "job_id", "review_id", "attempt_id", "lease_fence", "revision_id", "sequence",
            "report_sha256", "validation_run_id", "validation_status", "status",
        }
    second = materialize(report_context)
    assert second["current_revision_id"] == first["current_revision_id"]


def test_stage3_recommendation_is_resolved_without_default_invention():
    service = ReportService()
    stage = {
        "stage": "synthesis_and_validation",
        "claims": [{
            "category": "system_recommendation", "status": "supported",
            "body": "조건부 참여",
        }],
    }
    assert service._system_recommendation([stage], "passed") == ("조건부 추진 검토", None)
    assert service._system_recommendation([], "passed") == ("보류", "Stage 3 시스템 권고가 없습니다.")
    conflict = deepcopy(stage)
    conflict["claims"].append({
        "category": "시스템 권고", "status": "supported", "body": "검토 종료",
    })
    assert service._system_recommendation([conflict], "passed") == ("보류", "Stage 3 시스템 권고가 서로 충돌합니다.")
    assert service._system_recommendation([stage], "failed") == ("보류", None)


def test_get_report_is_read_only_and_never_lazy_materializes(report_context):
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        ReportService().get_report(session, report_context["review_id"])
    assert raised.value.code == "review_not_ready"
    with Session(report_context["engine"]) as session:
        assert session.scalar(select(func.count()).select_from(ReportRevision)) == 0
        assert session.scalar(select(func.count()).select_from(ValidationRun)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_stale_materialization_claim_writes_zero_report_validation_and_audit_rows(report_context):
    before = {}
    with Session(report_context["engine"]) as session:
        before = {
            "revisions": session.scalar(select(func.count()).select_from(ReportRevision)),
            "validations": session.scalar(select(func.count()).select_from(ValidationRun)),
            "evidence": session.scalar(select(func.count()).select_from(EvidenceRef)),
            "audits": session.scalar(select(func.count()).select_from(AuditEvent)),
        }
        stale = JobClaim(report_context["job_id"], report_context["review_id"], report_context["attempt_id"], "wrong-worker", 2)
        with pytest.raises(StaleFenceError):
            ReportService().materialize_machine_report(session, stale)
    with Session(report_context["engine"]) as session:
        assert {
            "revisions": session.scalar(select(func.count()).select_from(ReportRevision)),
            "validations": session.scalar(select(func.count()).select_from(ValidationRun)),
            "evidence": session.scalar(select(func.count()).select_from(EvidenceRef)),
            "audits": session.scalar(select(func.count()).select_from(AuditEvent)),
        } == before


def test_machine_materialization_replay_does_not_duplicate_audit(report_context):
    claim = JobClaim(report_context["job_id"], report_context["review_id"], report_context["attempt_id"], "worker-report", 1)
    with Session(report_context["engine"]) as session:
        first = ReportService().materialize_machine_report(session, claim)
        first_count = session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "deep_review.report.machine_materialized"))
        replay = ReportService().materialize_machine_report(session, claim)
        replay_count = session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "deep_review.report.machine_materialized"))
        assert replay["current_revision_id"] == first["current_revision_id"]
        assert first_count == replay_count == 1
        session.rollback()


def test_invalid_machine_report_is_rejected_before_revision_insert(report_context, monkeypatch):
    service = ReportService()
    monkeypatch.setattr(service, "_render_report", lambda *_args, **_kwargs: {"schema": "invalid"})
    claim = JobClaim(report_context["job_id"], report_context["review_id"], report_context["attempt_id"], "worker-report", 1)
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        service.materialize_machine_report(session, claim)
    assert raised.value.code == "validation_failed"
    with Session(report_context["engine"]) as session:
        assert session.scalar(select(func.count()).select_from(ReportRevision)) == 0
        assert session.scalar(select(func.count()).select_from(ValidationRun)) == 0


def test_claimed_actor_errors_are_not_500(report_context):
    view = materialize(report_context)
    request = revision_request(view, report_context["evidence_id"])
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        ReportService().create_revision(session, report_context["review_id"], None, request)
    assert raised.value.code == "actor_name_required" and raised.value.status_code == 400
    opinion = FinalOpinionRequest.model_validate({"request_id": str(uuid4()), "report_revision_id": view["current_revision_id"], "validation_run_id": view["validation"]["validation_run_id"], "value": "보류", "reason": "검토 대기", "acknowledged_validation_failure": False})
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        ReportService().create_final_opinion(session, report_context["review_id"], None, opinion)
    assert raised.value.code == "actor_name_required" and raised.value.status_code == 400


def test_stale_base_and_idempotency_replay_conflict(report_context):
    view = materialize(report_context)
    service = ReportService()
    stale = revision_request(view, report_context["evidence_id"])
    stale.base_revision_id = uuid4()
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        service.create_revision(session, report_context["review_id"], "담당자", stale)
    assert raised.value.code == "version_conflict"
    request = revision_request(view, report_context["evidence_id"], request_id=uuid4())
    with Session(report_context["engine"]) as session:
        first = service.create_revision(session, report_context["review_id"], "담당자", request)
    with Session(report_context["engine"]) as session:
        replay = service.create_revision(session, report_context["review_id"], "담당자", request)
    assert replay["current_revision_id"] == first["current_revision_id"]
    conflict = request.model_copy(update={"reason": "다른 사유"})
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        service.create_revision(session, report_context["review_id"], "담당자", conflict)
    assert raised.value.code == "idempotency_conflict"
    assert first["report"]["system_recommendation"] == view["report"]["system_recommendation"]
    with Session(report_context["engine"]) as session:
        audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "deep_review.report_revision.created"))
        assert audit is not None and audit.actor_kind == "human" and audit.claimed_name == "담당자"
        assert session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "deep_review.report_revision.created")) == 1
        assert "사람이 확인한" not in str(audit.safe_metadata) and "quote" not in str(audit.safe_metadata).lower()


def test_factual_evidence_scope_and_system_recommendation_immutability(report_context):
    view = materialize(report_context)
    service = ReportService()
    no_evidence = revision_request(view, report_context["evidence_id"])
    no_evidence.factual_change_evidence_ids = []
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        service.create_revision(session, report_context["review_id"], "담당자", no_evidence)
    assert raised.value.code == "factual_change_evidence_required"
    out_scope = revision_request(view, uuid4())
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        service.create_revision(session, report_context["review_id"], "담당자", out_scope)
    assert raised.value.code == "evidence_out_of_scope"
    changed = deepcopy(view["report"])
    changed["system_recommendation"] = "추진 검토"
    immutable = ReportRevisionRequest.model_validate({"request_id": str(uuid4()), "base_revision_id": view["current_revision_id"], "report": changed, "reason": "시스템 권고 변경", "factual_change_evidence_ids": [str(report_context["evidence_id"])]})
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        service.create_revision(session, report_context["review_id"], "담당자", immutable)
    assert raised.value.code == "validation_failed"


def test_presentational_titles_do_not_require_factual_evidence(report_context):
    view = materialize(report_context)
    report = deepcopy(view["report"])
    report["sections"][0]["title"] = "담당자 표시 제목"
    request = ReportRevisionRequest.model_validate({
        "request_id": str(uuid4()), "base_revision_id": view["current_revision_id"],
        "report": report, "reason": "표시 제목을 정리했습니다", "factual_change_evidence_ids": [],
    })
    with Session(report_context["engine"]) as session:
        revised = ReportService().create_revision(session, report_context["review_id"], "담당자", request)
    assert revised["report"]["sections"][0]["title"] == "담당자 표시 제목"


def test_validation_summary_without_failed_count_is_rejected(report_context):
    view = materialize(report_context)
    report = deepcopy(view["report"])
    report["validation_summary"] = {"status": "failed", "failed": 0, "warnings": 0, "passed": 1}
    request = ReportRevisionRequest.model_validate({
        "request_id": str(uuid4()), "base_revision_id": view["current_revision_id"],
        "report": report, "reason": "잘못된 validation 상태", "factual_change_evidence_ids": [str(report_context["evidence_id"])],
    })
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        ReportService().create_revision(session, report_context["review_id"], "담당자", request)
    assert raised.value.code == "validation_failed"


def test_same_base_revision_conflict_is_deterministic_on_sqlite(report_context):
    view = materialize(report_context)
    first_request = revision_request(view, report_context["evidence_id"], request_id=uuid4())
    second_request = revision_request(view, report_context["evidence_id"], request_id=uuid4())
    service = ReportService()
    with Session(report_context["engine"]) as session:
        service.create_revision(session, report_context["review_id"], "담당자", first_request)
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        service.create_revision(session, report_context["review_id"], "담당자", second_request)
    assert raised.value.code == "version_conflict"
    # SQLite's StaticPool serializes this deterministic check; PostgreSQL
    # coordinator tests cover true concurrent row locking.


def test_report_revision_and_human_opinion_do_not_inherit_between_reviews(report_context):
    ids = {key: uuid4() for key in ("review", "attempt", "job", "bundle", "claim", "evidence", "stage1", "stage2", "stage3")}
    now = datetime.now(UTC)
    tables = Base.metadata.tables
    with report_context["engine"].begin() as connection:
        connection.execute(tables["document_bundle"].insert(), {"id": ids["bundle"], "notice_id": 1, "revision": 2, "version": 1, "status": "ready", "issues_snapshot": {}, "confirmed_by_name": "운영자", "confirmed_at": now})
        connection.execute(tables["work_job"].insert(), {"id": ids["job"], "job_type": "deep_review", "aggregate_type": "deep_review", "aggregate_id": ids["review"], "status": "running", "lease_owner": "worker-two", "lease_expires_at": now + timedelta(minutes=5), "lease_fence": 1, "scheduled_at": now})
        connection.execute(tables["deep_review"].insert(), {"id": ids["review"], "notice_id": 1, "bundle_id": ids["bundle"], "profile_version_id": report_context["profile_id"], "policy_version_id": report_context["policy_id"], "effective_grade_at_start": "우선 검토", "status": "running", "current_attempt_id": ids["attempt"], "created_at": now})
        connection.execute(tables["deep_review_attempt"].insert(), {"id": ids["attempt"], "deep_review_id": ids["review"], "sequence": 1, "status": "running", "work_job_id": ids["job"], "lease_fence": 1, "started_at": now})
        for sequence, stage_name in enumerate(("requirements_and_evaluation", "delivery_risk_economics", "synthesis_and_validation"), 1):
            connection.execute(tables["deep_review_stage"].insert(), {"id": ids[f"stage{sequence}"], "attempt_id": ids["attempt"], "stage": stage_name, "sequence": sequence, "status": "completed", "structured_output": {"schema": "bidops.deep-review-stage.v1", "unknowns": [], "warnings": []}, "invocation_metadata": {}, "completed_at": now})
        connection.execute(tables["evidence_ref"].insert(), {"id": ids["evidence"], "deep_review_id": ids["review"], "source_kind": "profile", "notice_id": 1, "profile_version_id": report_context["profile_id"], "profile_evidence_id": report_context["profile_evidence_id"], "locator_type": "profile_fact", "locator": {"fact_key": "fixture.fact"}, "quote": "확인된 fixture 사실", "confidence": 0.9, "source_sha256": "c" * 64})
        connection.execute(tables["claim"].insert(), {"id": ids["claim"], "deep_review_id": ids["review"], "stage_id": ids["stage1"], "category": "eligibility", "claim_type": "fact", "body": "두 번째 review의 독립 주장", "status": "supported", "premise_claim_ids": [], "reason": None})
        connection.execute(tables["claim_evidence"].insert(), {"deep_review_id": ids["review"], "claim_id": ids["claim"], "evidence_ref_id": ids["evidence"], "ordinal": 0})
    with Session(report_context["engine"]) as session:
        claim = JobClaim(ids["job"], ids["review"], ids["attempt"], "worker-two", 1)
        view = ReportService().materialize_machine_report(session, claim)
        review = session.get(DeepReview, ids["review"]); attempt = session.get(DeepReviewAttempt, ids["attempt"]); job = session.get(WorkJob, ids["job"])
        assert review is not None and attempt is not None and job is not None
        review.status = "completed"; attempt.status = "completed"; attempt.completed_at = now; job.status = "completed"; job.completed_at = now; job.lease_expires_at = None
        session.commit()
        fresh = ReportService().get_report(session, ids["review"])
        assert fresh["current_revision_id"] == view["current_revision_id"]
        assert len(fresh["history"]) == 1
        assert fresh["final_opinion"] is None


def test_validation_failed_label_ack_history_and_final_opinion(report_context):
    view = materialize(report_context)
    report = deepcopy(view["report"])
    report["sections"][0]["blocks"][0]["body"] = "사람이 보완한 사실"
    report["validation_summary"] = {"status": "failed", "failed": 1, "warnings": 0, "passed": 0}
    request = ReportRevisionRequest.model_validate({"request_id": str(uuid4()), "base_revision_id": view["current_revision_id"], "report": report, "reason": "실패 label을 보존합니다", "factual_change_evidence_ids": [str(report_context["evidence_id"])]})
    with Session(report_context["engine"]) as session:
        revised = ReportService().create_revision(session, report_context["review_id"], "담당자", request)
    assert revised["validation"]["status"] == "failed" and len(revised["history"]) == 2
    no_ack = FinalOpinionRequest.model_validate({"request_id": str(uuid4()), "report_revision_id": revised["current_revision_id"], "validation_run_id": revised["validation"]["validation_run_id"], "value": "보류", "reason": "실패를 확인", "acknowledged_validation_failure": False})
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        ReportService().create_final_opinion(session, report_context["review_id"], "담당자", no_ack)
    assert raised.value.code == "validation_failed"
    blank_reason = no_ack.model_copy(update={"request_id": uuid4(), "reason": "  ", "acknowledged_validation_failure": True})
    with Session(report_context["engine"]) as session, pytest.raises(ReportServiceError) as raised:
        ReportService().create_final_opinion(session, report_context["review_id"], "담당자", blank_reason)
    assert raised.value.code == "final_opinion_reason_required"
    ack = no_ack.model_copy(update={"request_id": uuid4(), "acknowledged_validation_failure": True})
    with Session(report_context["engine"]) as session:
        opinion = ReportService().create_final_opinion(session, report_context["review_id"], "담당자", ack)
    assert opinion["validation_status_at_opinion"] == "failed" and opinion["acknowledged_validation_failure"] is True
    with Session(report_context["engine"]) as session:
        replay = ReportService().create_final_opinion(session, report_context["review_id"], "담당자", ack)
        assert replay["id"] == opinion["id"]
        final_audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "deep_review.final_opinion.created"))
        assert final_audit is not None and final_audit.actor_kind == "human" and final_audit.claimed_name == "담당자"
        assert session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "deep_review.final_opinion.created")) == 1
        assert set(final_audit.safe_metadata) <= {
            "review_id", "opinion_id", "report_revision_id", "validation_run_id", "sequence", "validation_status", "status",
        }
        assert "실패를 확인" not in str(final_audit.safe_metadata) and "reason" not in str(final_audit.safe_metadata).lower()


def test_report_revision_and_opinion_audits_inherit_deep_review_lineage(report_context):
    correlation = UUID("99999999-9999-9999-9999-999999999999")
    with Session(report_context["engine"]) as session:
        session.add(AuditEvent(
            actor_kind="human", claimed_name="담당자", action="deep_review.create",
            aggregate_type="deep_review", aggregate_id=str(report_context["review_id"]),
            safe_metadata={"correlation_id": str(correlation)},
            created_at=datetime.now(UTC) - timedelta(minutes=1),
        ))
        session.commit()

    view = materialize(report_context)
    with Session(report_context["engine"]) as session:
        machine_audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "deep_review.report.machine_materialized"))
        assert machine_audit is not None
        assert machine_audit.safe_metadata["correlation_id"] == str(correlation)

    request = revision_request(view, report_context["evidence_id"], request_id=uuid4(), reason="사람이 전체 snapshot을 보완했습니다")
    with Session(report_context["engine"]) as session:
        revised = ReportService().create_revision(session, report_context["review_id"], "담당자", request)
        opinion_request = FinalOpinionRequest.model_validate({
            "request_id": str(uuid4()),
            "report_revision_id": revised["current_revision_id"],
            "validation_run_id": revised["validation"]["validation_run_id"],
            "value": "보류",
            "reason": "사람이 최종 확인했습니다",
            "acknowledged_validation_failure": False,
        })
        ReportService().create_final_opinion(session, report_context["review_id"], "담당자", opinion_request)
        revision_audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "deep_review.report_revision.created"))
        opinion_audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "deep_review.final_opinion.created"))
        assert revision_audit is not None and revision_audit.safe_metadata["correlation_id"] == str(correlation)
        assert opinion_audit is not None and opinion_audit.safe_metadata["correlation_id"] == str(correlation)
        for audit in (revision_audit, opinion_audit):
            assert "사람이" not in str(audit.safe_metadata)
            assert "reason" not in str(audit.safe_metadata).lower()
            assert "quote" not in str(audit.safe_metadata).lower()


def test_evidence_union_locator_confidence_and_safety(report_context):
    assert _safe_locator("profile_fact", {"fact_key": "fixture.fact"}) == {"fact_key": "fixture.fact"}
    for locator in ({"fact_key": "fixture.fact", "extra": "no"}, {"fact_key": ""}, {"fact_key": 1}, {"page": 0}):
        with pytest.raises(EvidenceServiceError):
            _safe_locator("profile_fact", locator)
    with pytest.raises(EvidenceServiceError):
        _safe_locator("bbox", {"page": 1, "block_key": "b", "bbox": [0, 0, 1]})
    with Session(report_context["engine"]) as session:
        service = EvidenceService()
        profile_view = service.get(session, report_context["evidence_id"])
        assert profile_view["source_kind"] == "profile" and profile_view["page"] is None
        row = session.get(EvidenceRef, report_context["evidence_id"])
        assert row is not None
        row.confidence = 2
        with pytest.raises(EvidenceServiceError) as raised:
            service.get(session, report_context["evidence_id"])
        assert raised.value.code == "evidence_out_of_scope"
        row.confidence = 0.9
        row.locator = {"fact_key": "fixture.fact", "object_key": "secret"}
        with pytest.raises(EvidenceServiceError):
            service.get(session, report_context["evidence_id"])
        unsafe_document = EvidenceRef(
            id=uuid4(), deep_review_id=report_context["review_id"], source_kind="document", notice_id=1,
            bundle_id=uuid4(), document_version_id=uuid4(), structure_id=uuid4(), locator_type="page",
            locator={"page": 1}, quote="unsafe", confidence=0.5, source_sha256="d" * 64,
        )
        session.add(unsafe_document)
        session.flush()
        with pytest.raises(EvidenceServiceError) as raised:
            service.get(session, unsafe_document.id)
        assert raised.value.code == "evidence_out_of_scope"


def _seed_document_evidence(context: dict[str, object]) -> dict[str, UUID]:
    ids = {key: uuid4() for key in ("document_content", "payload_content", "document", "structure", "page", "paragraph", "table", "bbox")}
    now = datetime.now(UTC)
    tables = Base.metadata.tables
    with context["engine"].begin() as connection:
        connection.execute(tables["content_object"].insert(), {"id": ids["document_content"], "sha256": "d" * 64, "size_bytes": 10, "detected_mime": "application/pdf", "retention_class": "fixture"})
        connection.execute(tables["content_object"].insert(), {"id": ids["payload_content"], "sha256": "e" * 64, "size_bytes": 1, "detected_mime": "application/json", "retention_class": "fixture"})
        connection.execute(tables["content_scan"].insert(), {"id": uuid4(), "content_object_id": ids["document_content"], "scanner": "fixture", "scanner_version": "1", "status": "clean", "safe_result": {}, "scanned_at": now})
        connection.execute(tables["document_version"].insert(), {"id": ids["document"], "notice_id": 1, "content_object_id": ids["document_content"], "version": 1, "source_kind": "manual", "original_filename": "fixture.pdf", "role": "기타", "is_current": True, "safety_status": "safe", "created_at": now})
        connection.execute(tables["document_structure"].insert(), {"id": ids["structure"], "document_version_id": ids["document"], "source_sha256": "d" * 64, "media_type": "application/pdf", "extractor_name": "fixture", "extractor_version": "1", "payload_content_object_id": ids["payload_content"], "payload_sha256": "e" * 64, "page_count": 1, "block_count": 3, "validation_status": "ready", "created_at": now})
        connection.execute(tables["document_bundle_item"].insert(), {"bundle_id": context["bundle_id"], "document_version_id": ids["document"], "ordinal": 1, "document_version_version": 1, "content_object_id": ids["document_content"], "content_sha256": "d" * 64, "detected_mime": "application/pdf", "size_bytes": 10, "original_filename": "fixture.pdf", "source_kind": "manual", "role_at_confirmation": "기타", "is_current_at_confirmation": True, "safety_status_at_confirmation": "safe", "structure_id_at_confirmation": ids["structure"], "structure_payload_sha256": "e" * 64})
        blocks = [
            {"id": uuid4(), "structure_id": ids["structure"], "block_key": "p1", "block_type": "paragraph", "page": 1, "bbox": [0, 0, 100, 100], "content": "문서 단락 내용", "confidence": 0.91, "attributes": {"paragraph_key": "para-1"}},
            {"id": uuid4(), "structure_id": ids["structure"], "block_key": "t1", "block_type": "table_cell", "page": 1, "bbox": [0, 0, 100, 100], "content": "셀 내용", "confidence": 0.88, "attributes": {"table_key": "table-1", "row": 0, "column": 1}},
            {"id": uuid4(), "structure_id": ids["structure"], "block_key": "b1", "block_type": "paragraph", "page": 1, "bbox": [0, 0, 100, 100], "content": "bbox 내용", "confidence": 0.83, "attributes": {}},
        ]
        for block in blocks:
            connection.execute(tables["document_block"].insert(), block)
        for key, locator_type, locator, quote in (
            ("page", "page", {"page": 1}, "문서 단락 내용"),
            ("paragraph", "paragraph", {"page": 1, "block_key": "p1", "paragraph_key": "para-1", "text_start": 0, "text_end": 8}, "문서 단락 내용"),
            ("table", "table_cell", {"page": 1, "block_key": "t1", "table_key": "table-1", "row": 0, "column": 1}, "셀 내용"),
            ("bbox", "bbox", {"page": 1, "block_key": "b1", "bbox": [10, 10, 90, 90]}, "bbox 내용"),
        ):
            connection.execute(tables["evidence_ref"].insert(), {"id": ids[key], "deep_review_id": context["review_id"], "source_kind": "document", "notice_id": 1, "bundle_id": context["bundle_id"], "document_version_id": ids["document"], "structure_id": ids["structure"], "locator_type": locator_type, "locator": locator, "quote": quote, "confidence": 0.7, "source_sha256": "d" * 64})
    return ids


class _FixturePageService:
    def get_structure_page(self, session: Session, structure_id: UUID, page: int) -> DocumentStructurePageView:
        return DocumentStructurePageView.model_validate({
            "structure_id": str(structure_id), "page": page,
            "metadata": {"number": page, "width": 100, "height": 100, "image_content_object_id": str(uuid4())},
            "blocks": [
                {"block_key": "p1", "parent_block_key": None, "type": "paragraph", "page": page, "bbox": [0, 0, 100, 100], "text": "문서 단락 내용", "confidence": 0.91, "attributes": {"paragraph_key": "para-1"}},
                {"block_key": "t1", "parent_block_key": None, "type": "table_cell", "page": page, "bbox": [0, 0, 100, 100], "text": "셀 내용", "confidence": 0.88, "attributes": {"table_key": "table-1", "row": 0, "column": 1}},
                {"block_key": "b1", "parent_block_key": None, "type": "paragraph", "page": page, "bbox": [0, 0, 100, 100], "text": "bbox 내용", "confidence": 0.83, "attributes": {}},
            ],
        })


def test_document_evidence_reconciles_scope_and_exposes_safe_locator_projection(report_context):
    ids = _seed_document_evidence(report_context)
    service = EvidenceService(document_service=_FixturePageService())
    with Session(report_context["engine"]) as session:
        for key in ("page", "paragraph", "table", "bbox"):
            view = service.get(session, ids[key])
            assert view["source_kind"] == "document"
            assert view["page"]["metadata"]["image_content_object_id"] is None
            assert view["page"]["blocks"]
            assert all("object_key" not in str(block) and "path" not in str(block).lower() for block in view["page"]["blocks"])

        row = session.get(DocumentVersion, ids["document"])
        assert row is not None
        # Quarantine is represented by DocumentVersion safety_status; the
        # closed ContentScan enum represents unsafe latest scans explicitly.
        for safety_status in ("blocked", "quarantined"):
            row.safety_status = safety_status
            with pytest.raises(EvidenceServiceError) as raised:
                service.get(session, ids["paragraph"])
            assert raised.value.code == "unsafe_document"
        row.safety_status = "safe"
        scan = session.scalar(select(ContentScan).where(ContentScan.content_object_id == row.content_object_id))
        assert scan is not None
        for scan_status in ("unavailable", "infected", "error"):
            scan.status = scan_status
            with pytest.raises(EvidenceServiceError) as raised:
                service.get(session, ids["paragraph"])
            assert raised.value.code == "unsafe_document"
        scan.status = "clean"
        scan.status = "clean"
        item = session.scalar(select(DocumentBundleItem).where(
            DocumentBundleItem.bundle_id == report_context["bundle_id"],
            DocumentBundleItem.document_version_id == ids["document"],
        ))
        assert item is not None
        item.content_sha256 = "f" * 64
        with pytest.raises(EvidenceServiceError) as raised:
            service.get(session, ids["paragraph"])
        assert raised.value.code == "evidence_out_of_scope"


def test_reports_router_contract_is_exactly_four_routes_and_error_shape(report_context):
    app = FastAPI()
    app.include_router(reports_router)

    def override_db():
        with Session(report_context["engine"]) as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    def assert_error(response, status_code: int, code: str) -> None:
        assert response.status_code == status_code
        body = response.json()
        assert set(body) == {"error", "request_id"}
        assert set(body["error"]) == {"code", "message", "details"}
        assert body["error"]["code"] == code

    route_pairs = {
        (method, route.path)
        for route in reports_router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert route_pairs == {
        ("GET", "/api/deep-reviews/{deep_review_id}/report"),
        ("POST", "/api/deep-reviews/{deep_review_id}/report-revisions"),
        ("POST", "/api/deep-reviews/{deep_review_id}/final-opinions"),
        ("GET", "/api/evidence/{evidence_id}"),
    }
    with TestClient(app) as client:
        not_ready = client.get(f"/api/deep-reviews/{report_context['review_id']}/report")
        assert_error(not_ready, 409, "review_not_ready")
        not_found = client.get(f"/api/deep-reviews/{uuid4()}/report")
        assert_error(not_found, 404, "not_found")
        evidence_not_found = client.get(f"/api/evidence/{uuid4()}")
        assert_error(evidence_not_found, 404, "not_found")

    view = materialize(report_context)
    payload = revision_request(view, report_context["evidence_id"]).model_dump(mode="json")
    changed = deepcopy(payload["report"])
    changed["system_recommendation"] = "추진 검토"
    validation_payload = {**payload, "report": changed, "request_id": str(uuid4())}
    stale_payload = {**payload, "request_id": str(uuid4()), "base_revision_id": str(uuid4())}
    unsafe_id = uuid4()
    with Session(report_context["engine"]) as session:
        session.add(EvidenceRef(
            id=unsafe_id, deep_review_id=report_context["review_id"], source_kind="document", notice_id=1,
            bundle_id=uuid4(), document_version_id=uuid4(), structure_id=uuid4(), locator_type="page",
            locator={"page": 1}, quote="unsafe", confidence=0.5, source_sha256="d" * 64,
        ))
        session.commit()
    with TestClient(app) as client:
        actor_error = client.post(f"/api/deep-reviews/{report_context['review_id']}/report-revisions", json=payload)
        assert_error(actor_error, 400, "actor_name_required")
        report_success = client.get(f"/api/deep-reviews/{report_context['review_id']}/report")
        assert report_success.status_code == 200
        assert set(report_success.json()) == {"deep_review_id", "current_revision_id", "report", "validation", "history", "final_opinion"}
        evidence_success = client.get(f"/api/evidence/{report_context['evidence_id']}")
        assert evidence_success.status_code == 200
        assert set(evidence_success.json()) == {
            "evidence_id", "source_kind", "document_version_id", "structure_id", "profile_version_id",
            "profile_evidence_id", "locator_type", "locator", "quote", "confidence", "source_sha256", "page",
        }
        stale_error = client.post(
            f"/api/deep-reviews/{report_context['review_id']}/report-revisions",
            headers={"X-BidOps-Actor-Name": "reviewer"}, json=stale_payload,
        )
        assert_error(stale_error, 409, "version_conflict")
        validation_error = client.post(
            f"/api/deep-reviews/{report_context['review_id']}/report-revisions",
            headers={"X-BidOps-Actor-Name": "reviewer"}, json=validation_payload,
        )
        assert_error(validation_error, 409, "validation_failed")
        unsafe_error = client.get(f"/api/evidence/{unsafe_id}")
        assert_error(unsafe_error, 403, "evidence_out_of_scope")


def test_reports_router_agent_mutations_preserve_success_and_idempotent_replay(report_context):
    correlation_id = uuid4()
    with Session(report_context["engine"]) as session:
        session.add(AuditEvent(
            actor_kind="human",
            claimed_name="담당자",
            action="deep_review.create",
            aggregate_type="deep_review",
            aggregate_id=str(report_context["review_id"]),
            safe_metadata={"correlation_id": str(correlation_id)},
        ))
        session.commit()

    view = materialize(report_context)
    revision_payload = revision_request(
        view,
        report_context["evidence_id"],
        request_id=uuid4(),
        reason="router Agent replay 확인",
    ).model_dump(mode="json")
    app = FastAPI()
    app.include_router(reports_router)

    def override_db():
        with Session(report_context["engine"]) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    headers = {"X-BidOps-Actor-Name": "reviewer"}
    with TestClient(app) as client:
        first_revision = client.post(
            f"/api/deep-reviews/{report_context['review_id']}/report-revisions",
            headers=headers,
            json=revision_payload,
        )
        replay_revision = client.post(
            f"/api/deep-reviews/{report_context['review_id']}/report-revisions",
            headers=headers,
            json=revision_payload,
        )
        assert first_revision.status_code == replay_revision.status_code == 201
        assert first_revision.json()["current_revision_id"] == replay_revision.json()["current_revision_id"]

        revised = first_revision.json()
        opinion_payload = {
            "request_id": str(uuid4()),
            "report_revision_id": revised["current_revision_id"],
            "validation_run_id": revised["validation"]["validation_run_id"],
            "value": "보류",
            "reason": "router Agent 최종 확인",
            "acknowledged_validation_failure": False,
        }
        first_opinion = client.post(
            f"/api/deep-reviews/{report_context['review_id']}/final-opinions",
            headers=headers,
            json=opinion_payload,
        )
        replay_opinion = client.post(
            f"/api/deep-reviews/{report_context['review_id']}/final-opinions",
            headers=headers,
            json=opinion_payload,
        )
        assert first_opinion.status_code == replay_opinion.status_code == 201
        assert first_opinion.json()["id"] == replay_opinion.json()["id"]


def _creation_audit(context: dict[str, object], metadata: dict[str, object]) -> None:
    with Session(context["engine"]) as session:
        session.add(AuditEvent(
            actor_kind="human", claimed_name="담당자", action="deep_review.create",
            aggregate_type="deep_review", aggregate_id=str(context["review_id"]),
            safe_metadata=metadata,
        ))
        session.commit()


def test_report_without_a_creation_audit_has_no_quality_marker(report_context):
    view = materialize(report_context)
    assert view["report"]["quality_status"] is None


def test_report_quality_status_is_derived_from_the_creation_audit(report_context):
    _creation_audit(report_context, {
        "analysis_provider": "vllm-openai-compatible",
        "reference_workflow_mode": True,
        "policy_quality": {"status": "reference_workflow_unmeasured", "deployable": False},
    })
    view = materialize(report_context)
    assert view["report"]["quality_status"] == "unmeasured_reference"


def test_mock_creation_audit_produces_the_mock_reference_status(report_context):
    _creation_audit(report_context, {
        "analysis_provider": "mock-analysis",
        "reference_workflow_mode": True,
        "policy_quality": {"status": "reference_workflow_unmeasured", "deployable": False},
    })
    assert materialize(report_context)["report"]["quality_status"] == "mock_reference"


def test_measured_creation_audit_produces_the_measured_status(report_context):
    _creation_audit(report_context, {
        "analysis_provider": "vllm-openai-compatible",
        "reference_workflow_mode": False,
        "policy_quality": {"sample_hash": "b" * 64, "required_item_recall": 0.8, "human_agreement": 0.7, "unsupported_false_positive_rate": 0.1, "deployable": True},
    })
    assert materialize(report_context)["report"]["quality_status"] == "measured"


def test_measured_looking_audit_without_deployable_stays_unmarked(report_context):
    # 측정값이 있어도 배치 가능 판정이 없으면 `measured`로 승격하지 않는다.
    _creation_audit(report_context, {
        "analysis_provider": "vllm-openai-compatible",
        "reference_workflow_mode": False,
        "policy_quality": {"sample_hash": "b" * 64, "required_item_recall": 0.8},
    })
    assert materialize(report_context)["report"]["quality_status"] is None


def test_human_revision_keeps_the_server_derived_quality_marker(report_context):
    _creation_audit(report_context, {
        "analysis_provider": "vllm-openai-compatible",
        "reference_workflow_mode": True,
        "policy_quality": {"status": "reference_workflow_unmeasured", "deployable": False},
    })
    view = materialize(report_context)
    request = revision_request(view, report_context["evidence_id"])
    # 요청이 표식을 지워도 서버가 다시 붙인다. 참조 실행 배지는 사람 revision에서 사라지지 않는다.
    request.report.quality_status = None
    with Session(report_context["engine"]) as session:
        revised = ReportService().create_revision(session, report_context["review_id"], "담당자", request)
    assert revised["report"]["quality_status"] == "unmeasured_reference"
