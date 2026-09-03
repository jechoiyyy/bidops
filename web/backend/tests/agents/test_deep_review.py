"""DeepReviewAgent command and persisted projection contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agents.common import AgentAction, AgentOutcomeCode, AgentRunStatus, AgentStepStatus
from app.agents.deep_review import (
    DeepReviewAgent,
    RetryAttemptCommand,
    StartReviewCommand,
    attempt_artifact_ref,
    bundle_artifact_ref,
    bundle_snapshot_sha256,
    project_deep_review,
)
from app.core.db import init_db
from app.models import (
    AnalysisPolicyVersion,
    AuditEvent,
    ContentObject,
    DeepReview,
    DeepReviewAttempt,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    Judgment,
    Notice,
    ProfileVersion,
    Run,
    WorkJob,
)
from app.services.deep_reviews import DeepReviewService
from app.services.input_versions import load_canonical_policy


NOW = datetime(2026, 8, 26, 1, 0, tzinfo=UTC)
STAGES = (
    "requirements_and_evaluation",
    "delivery_risk_economics",
    "synthesis_and_validation",
)


def _ids() -> dict[str, UUID]:
    return {name: uuid4() for name in ("review", "attempt", "bundle", "profile", "policy", "revision", "validation", "evidence")}


def _bundle(ids: dict[str, UUID]) -> dict[str, object]:
    value: dict[str, object] = {
        "id": ids["bundle"], "notice_id": 7, "revision": 1, "version": 3,
        "status": "ready", "issues_snapshot": [], "confirmed_by_name": "담당자",
        "confirmed_at": NOW, "created_at": NOW - timedelta(minutes=2),
    }
    value["sha256"] = bundle_snapshot_sha256(value)
    return value


def _stage(
    attempt_id: UUID,
    stage: str,
    sequence: int,
    *,
    status: str = "queued",
    error_code: str | None = None,
) -> dict[str, object]:
    return {
        "id": uuid4(), "attempt_id": attempt_id, "stage": stage, "sequence": sequence,
        "status": status,
        "structured_output": {"schema": "bidops.deep-review-stage.v1", "stage": stage, "safe": True},
        "invocation_metadata": ([{"error_code": error_code, "object_key": "must-not-leak"}] if error_code else {}),
        "started_at": NOW if status in {"running", "completed", "failed"} else None,
        "completed_at": NOW if status in {"completed", "failed"} else None,
    }


def _snapshot(
    *,
    status: str = "queued",
    attempt_status: str = "queued",
    stage_statuses: tuple[str, str, str] = ("queued", "queued", "queued"),
    error_stage: int | None = None,
    with_outputs: bool = False,
    validation_status: str = "passed",
    lineage: str | None = "11111111-1111-1111-1111-111111111111",
) -> tuple[dict[str, object], dict[str, UUID]]:
    ids = _ids()
    bundle = _bundle(ids)
    stages = [
        _stage(ids["attempt"], name, sequence, status=stage_statuses[sequence - 1], error_code="timeout" if error_stage == sequence else None)
        for sequence, name in enumerate(STAGES, 1)
    ]
    create_audit = {
        "action": "deep_review.create", "aggregate_type": "deep_review", "aggregate_id": str(ids["review"]),
        "safe_metadata": ({"correlation_id": lineage} if lineage is not None else {}),
        "created_at": NOW - timedelta(minutes=1),
    }
    bundle_audit = {
        "action": "document_bundle.create", "aggregate_type": "document_bundle", "aggregate_id": str(ids["bundle"]),
        "safe_metadata": ({"correlation_id": lineage} if lineage is not None else {}),
        "created_at": NOW - timedelta(minutes=2),
    }
    attempt = {
        "id": ids["attempt"], "deep_review_id": ids["review"], "sequence": 1, "status": attempt_status,
        "started_at": NOW if attempt_status in {"running", "completed", "failed", "superseded"} else None,
        "completed_at": NOW if attempt_status in {"completed", "failed", "superseded"} else None,
    }
    audits: list[dict[str, object]] = [create_audit]
    revisions: list[dict[str, object]] = []
    validations: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    revision_evidence: list[dict[str, object]] = []
    if with_outputs:
        revisions.append({
            "id": ids["revision"], "deep_review_id": ids["review"], "sequence": 1,
            "origin": "machine", "report_sha256": "b" * 64, "created_at": NOW + timedelta(seconds=1),
        })
        validations.append({
            "id": ids["validation"], "deep_review_id": ids["review"], "report_revision_id": ids["revision"],
            "sequence": 1, "status": validation_status, "created_at": NOW + timedelta(seconds=2),
        })
        evidence.append({"id": ids["evidence"], "deep_review_id": ids["review"], "source_sha256": "c" * 64})
        revision_evidence.append({
            "deep_review_id": ids["review"], "report_revision_id": ids["revision"], "evidence_ref_id": ids["evidence"],
        })
        audits.append({
            "action": "deep_review.report.machine_materialized", "aggregate_type": "deep_review", "aggregate_id": str(ids["review"]),
            "safe_metadata": {"attempt_id": str(ids["attempt"]), "revision_id": str(ids["revision"])},
            "created_at": NOW + timedelta(seconds=3),
        })
    snapshot: dict[str, object] = {
        "review": {
            "id": ids["review"], "notice_id": 7, "bundle_id": ids["bundle"],
            "profile_version_id": ids["profile"], "policy_version_id": ids["policy"],
            "status": status, "current_attempt_id": ids["attempt"],
            "created_at": NOW - timedelta(minutes=1), "completed_at": NOW if status == "completed" else None,
        },
        "attempts": [attempt], "stages": {str(ids["attempt"]): stages}, "bundle": bundle, "bundle_items": [],
        "profile": {"id": ids["profile"], "version": 4, "profile_sha256": "d" * 64},
        "policy": {"id": ids["policy"], "version": 5, "policy_sha256": "e" * 64},
        "audits": audits, "bundle_creation_audits": [bundle_audit], "revisions": revisions,
        "validations": validations, "validation_checks": [], "revision_evidence": revision_evidence,
        "evidence": evidence, "jobs": [],
    }
    return snapshot, ids


def _start_command(bundle: dict[str, object], *, notice_id: int = 7, request_id: UUID | None = None, use_request: bool = True, **overrides: object) -> StartReviewCommand:
    values: dict[str, object] = {
        "schema": "bidops.agent-command.v1", "agent_name": "deep_review", "action": "start_review",
        "aggregate": {"aggregate_type": "notice", "aggregate_id": str(notice_id)},
        "actor": {"actor_kind": "human", "claimed_name": "담당자"},
        "request_id": request_id or uuid4() if use_request else None, "expected_version": None,
        "input_refs": [bundle_artifact_ref(bundle)], "payload": {"bundle_id": bundle["id"]},
    }
    values.update(overrides)
    return StartReviewCommand(**values)


def _retry_command(ids: dict[str, UUID], attempt_ref: object, **overrides: object) -> RetryAttemptCommand:
    values: dict[str, object] = {
        "schema": "bidops.agent-command.v1", "agent_name": "deep_review", "action": "retry_attempt",
        "aggregate": {"aggregate_type": "deep_review", "aggregate_id": str(ids["review"])},
        "actor": {"actor_kind": "human", "claimed_name": "담당자"}, "request_id": uuid4(),
        "expected_version": None, "input_refs": [attempt_ref], "payload": {},
    }
    values.update(overrides)
    return RetryAttemptCommand(**values)


def test_strict_commands_close_action_scope_and_payload() -> None:
    snapshot, ids = _snapshot()
    bundle = snapshot["bundle"]
    assert isinstance(bundle, dict)
    command = _start_command(bundle)
    assert command.payload.bundle_id == ids["bundle"]
    with pytest.raises(ValidationError):
        _start_command(bundle, use_request=False)
    with pytest.raises(ValidationError):
        _start_command(bundle, payload={"bundle_id": ids["bundle"], "unexpected": "value"})
    with pytest.raises(ValidationError):
        StartReviewCommand.model_validate({**command.model_dump(), "actor": {"actor_kind": "system", "claimed_name": None}})
    with pytest.raises(ValidationError):
        StartReviewCommand.model_validate({**command.model_dump(), "input_refs": [{**command.input_refs[0].model_dump(), "artifact_id": str(uuid4())}]})

    attempt_ref = {"artifact_type": "deep_review_attempt", "artifact_id": str(ids["attempt"]), "version": 1, "sha256": None}
    retry = _retry_command(ids, attempt_ref)
    assert retry.payload.model_dump() == {}
    with pytest.raises(ValidationError):
        RetryAttemptCommand.model_validate({**retry.model_dump(), "aggregate": {"aggregate_type": "notice", "aggregate_id": "7"}})
    with pytest.raises(ValidationError):
        RetryAttemptCommand.model_validate({**retry.model_dump(), "input_refs": []})
    with pytest.raises(ValidationError):
        RetryAttemptCommand.model_validate({
            **retry.model_dump(),
            "input_refs": [{**retry.input_refs[0].model_dump(), "sha256": "f" * 64}],
        })


def test_queued_running_and_failed_projection_uses_only_saved_stage_state() -> None:
    queued, ids = _snapshot()
    first = project_deep_review(queued)
    second = project_deep_review(deepcopy(queued))
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.status is AgentRunStatus.queued and first.current_step == STAGES[0]
    assert first.wait is None
    assert [step.step_name for step in first.steps] == list(STAGES)
    assert [step.status for step in first.steps] == [AgentStepStatus.queued] * 3
    assert [ref.artifact_type.value for ref in first.input_refs] == ["document_bundle", "profile_version", "policy_version"]
    assert first.run_id == f"deep-review:{ids['review']}:attempt:{ids['attempt']}"

    running, _ = _snapshot(status="running", attempt_status="running", stage_statuses=("completed", "running", "queued"))
    running_view = project_deep_review(running)
    assert running_view.status is AgentRunStatus.running and running_view.current_step == STAGES[1]
    assert running_view.steps[0].status is AgentStepStatus.completed
    assert running_view.steps[1].status is AgentStepStatus.running and running_view.wait is None

    failed, _ = _snapshot(status="failed", attempt_status="failed", stage_statuses=("completed", "failed", "queued"), error_stage=2)
    failed_view = project_deep_review(failed)
    assert failed_view.status is AgentRunStatus.failed
    assert failed_view.error is not None and failed_view.error.code.value == "processing_failed"
    assert failed_view.current_step == STAGES[1] and failed_view.available_actions == [AgentAction.retry_attempt]
    assert len(failed_view.output_refs) == 1
    assert "must-not-leak" not in json.dumps(failed_view.model_dump(mode="json"))


@pytest.mark.parametrize("validation_status,outcome", [
    ("passed", AgentOutcomeCode.report_ready_validated),
    ("failed", AgentOutcomeCode.report_ready_validation_failed),
])
def test_completed_projection_orders_outputs_and_keeps_validation_failure_completed(validation_status: str, outcome: AgentOutcomeCode) -> None:
    snapshot, ids = _snapshot(status="completed", attempt_status="completed", stage_statuses=("completed",) * 3, with_outputs=True, validation_status=validation_status)
    view = project_deep_review(snapshot)
    assert view.status is AgentRunStatus.completed and view.outcome_code is outcome and view.error is None
    assert view.current_step is None and view.wait is None
    assert [ref.artifact_type.value for ref in view.output_refs] == [
        "deep_review_stage", "deep_review_stage", "deep_review_stage", "report_revision", "validation_run", "evidence",
    ]
    assert view.output_refs[3].artifact_id == str(ids["revision"])
    assert view.output_refs[4].artifact_id == str(ids["validation"])
    assert view.output_refs[5].artifact_id == str(ids["evidence"])


def test_missing_or_corrupt_stage_report_audit_fails_closed() -> None:
    missing, _ = _snapshot(status="completed", attempt_status="completed", stage_statuses=("completed",) * 3)
    missing_view = project_deep_review(missing)
    assert missing_view.status is AgentRunStatus.failed
    assert missing_view.error is not None and missing_view.error.code.value == "processing_failed"
    assert missing_view.current_step is None

    corrupt, _ = _snapshot()
    attempt_key = next(iter(corrupt["stages"]))
    corrupt["stages"][attempt_key][1]["sequence"] = 3  # type: ignore[index]
    corrupt_view = project_deep_review(corrupt)
    assert corrupt_view.status is AgentRunStatus.failed
    assert corrupt_view.error is not None and corrupt_view.error.code.value == "processing_failed"


def test_lineage_null_legacy_and_invalid_lineage_are_deterministic() -> None:
    legacy, _ = _snapshot(lineage=None)
    legacy_view = project_deep_review(legacy)
    assert legacy_view.correlation_id is None

    invalid, _ = _snapshot(lineage=None)
    invalid["bundle_creation_audits"][0]["safe_metadata"] = {"correlation_id": "not-a-uuid"}  # type: ignore[index]
    invalid_view = project_deep_review(invalid)
    assert invalid_view.status is AgentRunStatus.failed
    assert invalid_view.error is not None and invalid_view.error.code.value == "processing_failed"


def test_failed_retry_supersedes_only_failed_attempt_and_completed_retry_preserves_outputs() -> None:
    old, ids = _snapshot(status="failed", attempt_status="superseded", stage_statuses=("completed", "failed", "queued"), error_stage=2)
    new_attempt = uuid4()
    old["review"]["current_attempt_id"] = new_attempt  # type: ignore[index]
    old["review"]["status"] = "queued"  # type: ignore[index]
    old["attempts"].append({"id": new_attempt, "deep_review_id": ids["review"], "sequence": 2, "status": "queued", "started_at": None, "completed_at": None})  # type: ignore[union-attr]
    old["stages"][str(new_attempt)] = [_stage(new_attempt, name, sequence) for sequence, name in enumerate(STAGES, 1)]  # type: ignore[index]
    old["audits"].append({
        "action": "deep_review.attempt", "aggregate_type": "deep_review", "aggregate_id": str(ids["review"]),
        "safe_metadata": {"attempt_id": str(new_attempt), "correlation_id": "11111111-1111-1111-1111-111111111111"},
        "created_at": NOW + timedelta(minutes=1),
    })  # type: ignore[union-attr]
    old_view = project_deep_review(old, attempt_id=ids["attempt"])
    assert old_view.status is AgentRunStatus.superseded
    assert old_view.outcome_code is AgentOutcomeCode.superseded_by_retry
    assert old_view.current_step is None and old_view.error is not None
    assert [step.status for step in old_view.steps] == [AgentStepStatus.completed, AgentStepStatus.failed, AgentStepStatus.queued]
    assert [ref.artifact_type.value for ref in old_view.output_refs] == ["deep_review_stage"]
    assert old_view.available_actions == []

    completed, _ = _snapshot(status="completed", attempt_status="completed", stage_statuses=("completed",) * 3, with_outputs=True)
    completed_view = project_deep_review(completed)
    assert completed_view.status is AgentRunStatus.completed and completed_view.output_refs


def test_active_attempt_disables_retry_action() -> None:
    snapshot, ids = _snapshot(status="failed", attempt_status="failed", stage_statuses=("completed", "failed", "queued"), error_stage=2)
    active = uuid4()
    snapshot["attempts"].append({"id": active, "deep_review_id": ids["review"], "sequence": 2, "status": "running", "started_at": NOW, "completed_at": None})  # type: ignore[union-attr]
    snapshot["stages"][str(active)] = [_stage(active, name, sequence) for sequence, name in enumerate(STAGES, 1)]  # type: ignore[index]
    view = project_deep_review(snapshot)
    assert view.status is AgentRunStatus.failed and view.available_actions == []


def _fixture_structure(_session: Session, structure: DocumentStructure) -> dict[str, object]:
    return {
        "schema": "bidops.document-structure.v1", "structure_id": str(structure.id),
        "document_version_id": str(structure.document_version_id), "source_sha256": structure.source_sha256,
        "media_type": structure.media_type,
        "extractor": {"name": structure.extractor_name, "version": structure.extractor_version, "upstream_commit": structure.upstream_commit},
        "pages": [{"number": 1, "width": 612, "height": 792, "image_content_object_id": None}],
        "blocks": [], "warnings": [], "created_at": "2026-08-25T00:00:00+00:00",
    }


@pytest.fixture
def agent_context(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    # SQLite does not render PostgreSQL's partial index predicate from the
    # declarative model; mirror the production active-attempt invariant here.
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS uq_deep_review_attempt_active"))
        connection.execute(text("DROP INDEX IF EXISTS uq_work_job_active"))
        connection.execute(text("CREATE UNIQUE INDEX uq_deep_review_attempt_active ON deep_review_attempt (deep_review_id) WHERE status IN ('queued','running')"))
        connection.execute(text("CREATE UNIQUE INDEX uq_work_job_active ON work_job (job_type, aggregate_type, aggregate_id) WHERE status IN ('queued','running')"))
    ids = _ids()
    correlation = UUID("22222222-2222-2222-2222-222222222222")
    policy_payload, _canonical, policy_hash = load_canonical_policy()
    with Session(engine) as session:
        run = Run(id=f"agent-{uuid4()}")
        notice = Notice(run=run, notice_key=f"agent-notice-{uuid4()}")
        session.add(Judgment(notice=notice, grade="우선 검토", readiness="확인 완료"))
        session.add_all([run, notice])
        session.flush()
        content = ContentObject(id=uuid4(), sha256="f" * 64, size_bytes=0, detected_mime="application/json", retention_class="fixture")
        document = DocumentVersion(
            id=uuid4(), notice_id=notice.id, content_object_id=content.id, version=1, source_kind="manual",
            original_filename="fixture.pdf", role="기타", is_current=True, safety_status="safe",
        )
        structure = DocumentStructure(
            id=uuid4(), document_version_id=document.id, source_sha256=content.sha256, media_type="application/pdf",
            extractor_name="fixture", extractor_version="1", payload_content_object_id=content.id,
            payload_sha256="e" * 64, page_count=1, block_count=0, validation_status="ready",
        )
        bundle = DocumentBundle(
            id=ids["bundle"], notice_id=notice.id, revision=1, version=3, status="ready", issues_snapshot=[],
            confirmed_by_name="담당자", confirmed_at=NOW,
        )
        item = DocumentBundleItem(
            bundle_id=bundle.id, document_version_id=document.id, ordinal=0, document_version_version=1,
            content_object_id=content.id, content_sha256=content.sha256, detected_mime="application/pdf",
            size_bytes=0, original_filename="fixture.pdf", source_kind="manual", role_at_confirmation="기타",
            is_current_at_confirmation=True, safety_status_at_confirmation="safe", structure_id_at_confirmation=structure.id,
            structure_payload_sha256=structure.payload_sha256,
        )
        profile = ProfileVersion(
            id=ids["profile"], version=4, label="fixture", profile_payload={"schema": "bidops.company-profile.v1", "source_sha256": "d" * 64, "facts": []},
            profile_sha256="d" * 64, source_kind="fixture",
        )
        policy = AnalysisPolicyVersion(
            id=ids["policy"], version=5, label="fixture", model_endpoint_ref="vllm-openai-compatible",
            model_name=policy_payload["model_name"], prompts=policy_payload["stages"],
            validation_rules={**policy_payload["validation"], "generation": policy_payload["generation"], "sample_hash": "b" * 64,
                              "required_item_recall": .8, "human_agreement": .7, "unsupported_false_positive_rate": .1},
            policy_sha256=policy_hash,
        )
        session.add_all([run, notice, content, document, structure, bundle, item, profile, policy])
        session.flush()
        session.add(AuditEvent(
            actor_kind="human", claimed_name="담당자", action="document_bundle.create",
            aggregate_type="document_bundle", aggregate_id=str(bundle.id),
            safe_metadata={"correlation_id": str(correlation)}, created_at=NOW - timedelta(minutes=2),
        ))
        session.commit()
        notice_id = notice.id
    monkeypatch.setenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", str(ids["profile"]))
    monkeypatch.setenv("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID", str(ids["policy"]))
    return engine, notice_id, ids["bundle"], correlation


def test_agent_adapter_passes_existing_views_and_audit_lineage(agent_context) -> None:
    engine, notice_id, bundle_id, correlation = agent_context
    service = DeepReviewService(structure_loader=_fixture_structure)
    agent = DeepReviewAgent(service)
    with Session(engine) as session:
        bundle = session.get(DocumentBundle, bundle_id)
        assert bundle is not None
        items = session.scalars(select(DocumentBundleItem).where(DocumentBundleItem.bundle_id == bundle.id)).all()
        started = agent.start(session, _start_command({
            "id": bundle.id, "notice_id": bundle.notice_id, "revision": bundle.revision, "version": bundle.version,
            "status": bundle.status, "issues_snapshot": bundle.issues_snapshot, "confirmed_by_name": bundle.confirmed_by_name,
            "confirmed_at": bundle.confirmed_at, "created_at": bundle.created_at,
            "sha256": bundle_snapshot_sha256(bundle, items),
        }, notice_id=notice_id, correlation_id=correlation))
        from app.routers.deep_reviews import DeepReviewView

        assert isinstance(started.result, DeepReviewView)
        assert started.run.status is AgentRunStatus.queued
        assert started.run.correlation_id == correlation
        assert [ref.artifact_type.value for ref in started.run.input_refs] == ["document_bundle", "profile_version", "policy_version"]
        review = session.get(DeepReview, started.result.id)
        assert review is not None and review.current_attempt_id is not None
        creation = session.scalar(select(AuditEvent).where(AuditEvent.action == "deep_review.create", AuditEvent.aggregate_id == str(review.id)))
        assert creation is not None and creation.safe_metadata["correlation_id"] == str(correlation)

        attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
        job = session.get(WorkJob, attempt.work_job_id) if attempt is not None else None
        assert attempt is not None and job is not None
        attempt.status = "failed"
        review.status = "failed"
        job.status = "failed"
        session.commit()
        retry = agent.retry_attempt(session, _retry_command(ids={"review": review.id, "attempt": attempt.id}, attempt_ref=attempt_artifact_ref(attempt, agent._stages_for_attempt(session, attempt.id))))
        assert retry.run.status is AgentRunStatus.queued
        retry_audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "deep_review.attempt", AuditEvent.aggregate_id == str(review.id)))
        assert retry_audit is not None and retry_audit.safe_metadata["correlation_id"] == str(correlation)
