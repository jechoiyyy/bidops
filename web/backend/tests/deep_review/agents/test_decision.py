"""DecisionAgent command, projection, and immutable-lineage coverage."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.agents.common import (
    AgentAction,
    AgentArtifactType,
    AgentRunStatus,
    AgentStepStatus,
)
from app.agents.decision.commands import (
    CreateFullRevisionCommand,
    RecordFinalOpinionCommand,
)
from app.agents.decision.projection import (
    STEP_NAMES,
    final_opinion_snapshot_payload,
    project_decision,
    validation_snapshot_payload,
)
from app.schemas.reports import DeepReviewReport, ValidationSummary


NOW = datetime(2026, 8, 26, 1, 2, 3, tzinfo=UTC)
REVIEW = UUID("11111111-1111-1111-1111-111111111111")
MACHINE_REVISION = UUID("22222222-2222-2222-2222-222222222222")
HUMAN_REVISION = UUID("33333333-3333-3333-3333-333333333333")
MACHINE_VALIDATION = UUID("44444444-4444-4444-4444-444444444444")
HUMAN_VALIDATION = UUID("55555555-5555-5555-5555-555555555555")
NEW_REVISION = UUID("aaaaaaaa-bbbb-cccc-dddd-ffffffffffff")
NEW_VALIDATION = UUID("bbbbbbbb-cccc-dddd-eeee-ffffffffffff")
EVIDENCE_A = UUID("66666666-6666-6666-6666-666666666666")
EVIDENCE_B = UUID("77777777-7777-7777-7777-777777777777")
OPINION = UUID("88888888-8888-8888-8888-888888888888")
CORRELATION = UUID("99999999-9999-9999-9999-999999999999")


def _audit(action: str, *, metadata: dict[str, object], created_at: datetime, audit_id: UUID | None = None) -> dict[str, object]:
    return {
        "id": audit_id or uuid4(),
        "action": action,
        "aggregate_type": "deep_review",
        "aggregate_id": str(REVIEW),
        "safe_metadata": metadata,
        "created_at": created_at,
    }


def _base_snapshot(*, validation_status: str = "passed", with_machine: bool = True) -> dict[str, object]:
    audits: list[dict[str, object]] = [_audit("deep_review.create", metadata={"correlation_id": str(CORRELATION)}, created_at=NOW)]
    revisions: list[dict[str, object]] = []
    validations: list[dict[str, object]] = []
    checks: list[dict[str, object]] = []
    links: list[dict[str, object]] = []
    evidence = [
        {"id": EVIDENCE_B, "deep_review_id": REVIEW, "source_sha256": "b" * 64},
        {"id": EVIDENCE_A, "deep_review_id": REVIEW, "source_sha256": "a" * 64},
    ]
    if with_machine:
        revisions.append({
            "id": MACHINE_REVISION,
            "deep_review_id": REVIEW,
            "sequence": 1,
            "origin": "machine",
            "parent_revision_id": None,
            "report_sha256": "1" * 64,
            "created_at": NOW + timedelta(seconds=1),
        })
        validations.append({
            "id": MACHINE_VALIDATION,
            "deep_review_id": REVIEW,
            "report_revision_id": MACHINE_REVISION,
            "sequence": 1,
            "status": validation_status,
            "created_at": NOW + timedelta(seconds=2),
        })
        checks.append({
            "id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            "validation_run_id": MACHINE_VALIDATION,
            "check_type": "report_contract",
            "status": "passed" if validation_status == "passed" else "failed",
            "severity": "낮음" if validation_status == "passed" else "중대",
            "message": "fixture check",
            "related_claim_ids": [],
            "related_evidence_ids": [],
        })
        links.extend([
            {"deep_review_id": REVIEW, "report_revision_id": MACHINE_REVISION, "evidence_ref_id": EVIDENCE_B},
            {"deep_review_id": REVIEW, "report_revision_id": MACHINE_REVISION, "evidence_ref_id": EVIDENCE_A},
        ])
        audits.append(_audit(
            "deep_review.report.machine_materialized",
            metadata={"revision_id": str(MACHINE_REVISION), "validation_run_id": str(MACHINE_VALIDATION), "correlation_id": str(CORRELATION)},
            created_at=NOW + timedelta(seconds=3),
        ))
    return {
        "review": {"id": REVIEW, "created_at": NOW},
        "revisions": revisions,
        "validations": validations,
        "validation_checks": checks,
        "revision_evidence": links,
        "evidence": evidence,
        "opinions": [],
        "audits": audits,
    }


def _human_revision(
    snapshot: dict[str, object],
    *,
    validation_status: str = "passed",
    revision_id: UUID = HUMAN_REVISION,
    validation_id: UUID = HUMAN_VALIDATION,
) -> None:
    revisions = snapshot["revisions"]
    validations = snapshot["validations"]
    audits = snapshot["audits"]
    assert isinstance(revisions, list) and isinstance(validations, list) and isinstance(audits, list)
    sequence = len(revisions) + 1
    parent_revision_id = revisions[-1]["id"] if revisions else None
    revisions.append({
        "id": revision_id,
        "deep_review_id": REVIEW,
        "sequence": sequence,
        "origin": "human",
        "parent_revision_id": parent_revision_id,
        "report_sha256": "2" * 64,
        "created_at": NOW + timedelta(seconds=4),
    })
    validations.append({
        "id": validation_id,
        "deep_review_id": REVIEW,
        "report_revision_id": revision_id,
        "sequence": sequence,
        "status": validation_status,
        "created_at": NOW + timedelta(seconds=5),
    })
    audits.append(_audit(
        "deep_review.report_revision.created",
        metadata={"revision_id": str(revision_id), "validation_run_id": str(validation_id), "correlation_id": str(CORRELATION)},
        created_at=NOW + timedelta(seconds=6),
    ))


def _opinion(snapshot: dict[str, object], *, validation_status: str = "passed", acknowledged: bool = False, reason: str = "사람이 검토했습니다") -> None:
    opinions = snapshot["opinions"]
    audits = snapshot["audits"]
    assert isinstance(opinions, list) and isinstance(audits, list)
    revision_id = HUMAN_REVISION if any(row["id"] == HUMAN_REVISION for row in snapshot["revisions"]) else MACHINE_REVISION  # type: ignore[index]
    validation_id = HUMAN_VALIDATION if revision_id == HUMAN_REVISION else MACHINE_VALIDATION
    opinion = {
        "id": OPINION,
        "deep_review_id": REVIEW,
        "report_revision_id": revision_id,
        "sequence": 1,
        "value": "보류",
        "reason": reason,
        "validation_run_id": validation_id,
        "validation_status_at_opinion": validation_status,
        "acknowledged_validation_failure": acknowledged,
        "claimed_name": "담당자",
        "created_at": NOW + timedelta(seconds=7),
    }
    opinions.append(opinion)
    audits.append(_audit(
        "deep_review.final_opinion.created",
        metadata={
            "opinion_id": str(OPINION),
            "report_revision_id": str(revision_id),
            "validation_run_id": str(validation_id),
            "validation_status": validation_status,
            "correlation_id": str(CORRELATION),
        },
        created_at=NOW + timedelta(seconds=8),
    ))


def _report() -> DeepReviewReport:
    return DeepReviewReport.model_construct(
        schema="bidops.deep-review-report.v1",
        deep_review_id=REVIEW,
        notice_id=1,
        bundle_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        profile_version_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        policy_version_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        sections=[],
        system_recommendation="보류",
        claims=[],
        unknowns=[],
        validation_summary=ValidationSummary(status="passed", failed=0, warnings=0, passed=1),
        created_at=NOW,
    )


def _revision_command(snapshot: dict[str, object], **overrides: object) -> CreateFullRevisionCommand:
    values: dict[str, object] = {
        "schema": "bidops.agent-command.v1",
        "agent_name": "decision",
        "action": "create_full_revision",
        "aggregate": {"aggregate_type": "deep_review", "aggregate_id": str(REVIEW)},
        "actor": {"actor_kind": "human", "claimed_name": "담당자"},
        "request_id": uuid4(),
        "correlation_id": CORRELATION,
        "expected_version": None,
        "input_refs": [{"artifact_type": "report_revision", "artifact_id": str(MACHINE_REVISION), "version": 1, "sha256": "1" * 64}],
        "payload": {"base_revision_id": str(MACHINE_REVISION), "report": _report(), "reason": "사실을 보완했습니다", "factual_change_evidence_ids": [str(EVIDENCE_A)]},
    }
    values.update(overrides)
    return CreateFullRevisionCommand.model_validate(values)


def _opinion_command(snapshot: dict[str, object], **overrides: object) -> RecordFinalOpinionCommand:
    values: dict[str, object] = {
        "schema": "bidops.agent-command.v1",
        "agent_name": "decision",
        "action": "record_final_opinion",
        "aggregate": {"aggregate_type": "deep_review", "aggregate_id": str(REVIEW)},
        "actor": {"actor_kind": "human", "claimed_name": "담당자"},
        "request_id": uuid4(),
        "correlation_id": CORRELATION,
        "expected_version": None,
        "input_refs": [
            {"artifact_type": "report_revision", "artifact_id": str(MACHINE_REVISION), "version": 1, "sha256": "1" * 64},
            {"artifact_type": "validation_run", "artifact_id": str(MACHINE_VALIDATION), "version": 1, "sha256": "d" * 64},
        ],
        "payload": {
            "report_revision_id": str(MACHINE_REVISION),
            "validation_run_id": str(MACHINE_VALIDATION),
            "value": "보류",
            "reason": "검토했습니다",
            "acknowledged_validation_failure": False,
        },
    }
    values.update(overrides)
    return RecordFinalOpinionCommand.model_validate(values)


def test_blocked_projection_has_exact_steps_wait_and_no_refs_or_actions() -> None:
    view = project_decision(_base_snapshot(with_machine=False))
    assert view.status is AgentRunStatus.blocked
    assert view.current_step == "await_machine_report"
    assert view.wait is not None and view.wait.reason_code.value == "machine_report_required"
    assert view.input_refs == [] and view.output_refs == [] and view.available_actions == []
    assert [step.step_name for step in view.steps] == list(STEP_NAMES)
    assert [step.sequence for step in view.steps] == [1, 2, 3]
    assert [step.status for step in view.steps] == [AgentStepStatus.blocked] * 3
    assert view.created_at == NOW and view.started_at is None
    assert view.execution_ref is None and view.run_id == f"decision:{REVIEW}"


def test_waiting_machine_report_projection_orders_refs_and_hashes_without_leaking_content() -> None:
    snapshot = _base_snapshot()
    view = project_decision(snapshot)
    assert view.status is AgentRunStatus.waiting_human
    assert view.current_step == "review_report_and_evidence"
    assert view.available_actions == [AgentAction.create_full_revision, AgentAction.record_final_opinion]
    assert [ref.artifact_type for ref in view.input_refs] == [
        AgentArtifactType.report_revision,
        AgentArtifactType.validation_run,
        AgentArtifactType.evidence,
        AgentArtifactType.evidence,
    ]
    assert [ref.artifact_id for ref in view.input_refs[2:]] == [str(EVIDENCE_A), str(EVIDENCE_B)]
    assert view.output_refs == []
    dumped = json.dumps(view.model_dump(mode="json"), ensure_ascii=False)
    assert "fixture check" not in dumped and "확인된 원문" not in dumped and "secret" not in dumped
    validation = snapshot["validations"][0]  # type: ignore[index]
    checks = snapshot["validation_checks"]  # type: ignore[index]
    expected = hashlib.sha256(json.dumps(validation_snapshot_payload(validation, checks), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert view.input_refs[1].sha256 == expected


def test_human_revision_waits_for_opinion_then_completion_and_new_revision_reopens() -> None:
    snapshot = _base_snapshot()
    _human_revision(snapshot)
    waiting = project_decision(snapshot)
    assert waiting.status is AgentRunStatus.waiting_human
    assert waiting.current_step == "record_final_opinion"
    assert waiting.wait is not None and waiting.wait.reason_code.value == "final_opinion_required"
    assert waiting.available_actions == [AgentAction.create_full_revision, AgentAction.record_final_opinion]
    assert [ref.artifact_type for ref in waiting.output_refs] == [AgentArtifactType.report_revision, AgentArtifactType.validation_run]

    _opinion(snapshot)
    completed = project_decision(snapshot)
    assert completed.status is AgentRunStatus.completed
    assert completed.outcome_code is not None and completed.outcome_code.value == "final_opinion_recorded"
    assert completed.current_step is None and completed.wait is None
    assert completed.available_actions == [AgentAction.create_full_revision]
    assert completed.output_refs[-1].artifact_type is AgentArtifactType.final_opinion
    assert completed.completed_at == NOW + timedelta(seconds=7)
    assert completed.output_refs[-1].sha256 == hashlib.sha256(json.dumps(final_opinion_snapshot_payload(snapshot["opinions"][0]), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()  # type: ignore[index]

    _human_revision(snapshot, revision_id=NEW_REVISION, validation_id=NEW_VALIDATION)
    reopened = project_decision(snapshot)
    assert reopened.status is AgentRunStatus.waiting_human
    assert reopened.current_step == "record_final_opinion"
    assert reopened.available_actions == [AgentAction.create_full_revision, AgentAction.record_final_opinion]
    assert len(snapshot["revisions"]) == 3 and len(snapshot["opinions"]) == 1  # type: ignore[arg-type]


def test_strict_commands_require_human_actor_request_and_matching_refs() -> None:
    revision = _revision_command(_base_snapshot())
    assert revision.payload.base_revision_id == MACHINE_REVISION
    with pytest.raises(ValidationError):
        _revision_command(_base_snapshot(), actor={"actor_kind": "system", "claimed_name": None})
    with pytest.raises(ValidationError):
        _revision_command(_base_snapshot(), request_id=None)
    with pytest.raises(ValidationError):
        _revision_command(_base_snapshot(), input_refs=[{**revision.input_refs[0].model_dump(), "artifact_id": str(HUMAN_REVISION)}])
    with pytest.raises(ValidationError):
        _revision_command(_base_snapshot(), payload={**revision.payload.model_dump(), "unexpected": "secret"})

    opinion = _opinion_command(_base_snapshot())
    assert opinion.payload.value == "보류"
    with pytest.raises(ValidationError):
        _opinion_command(_base_snapshot(), input_refs=opinion.input_refs[:1])
    with pytest.raises(ValidationError):
        _opinion_command(_base_snapshot(), input_refs=[opinion.input_refs[0], {**opinion.input_refs[1].model_dump(), "artifact_id": str(HUMAN_VALIDATION)}])
    with pytest.raises(ValidationError):
        _opinion_command(_base_snapshot(), payload={**opinion.payload.model_dump(), "unexpected": True})


def test_failed_validation_requires_acknowledgement_and_nonblank_reason_in_persisted_opinion() -> None:
    snapshot = _base_snapshot(validation_status="failed")
    _opinion(snapshot, validation_status="failed", acknowledged=True, reason="실패를 확인했습니다")
    completed = project_decision(snapshot)
    assert completed.status is AgentRunStatus.completed
    invalid = deepcopy(snapshot)
    invalid["opinions"][0]["acknowledged_validation_failure"] = False  # type: ignore[index]
    failed = project_decision(invalid)
    assert failed.status is AgentRunStatus.failed
    assert failed.error is not None and failed.error.code.value == "processing_failed"


def test_lineage_legacy_null_and_invalid_duplicate_or_mismatch_fail_closed() -> None:
    legacy = _base_snapshot()
    legacy["audits"][0]["safe_metadata"] = {}  # type: ignore[index]
    legacy["audits"][1]["safe_metadata"] = {"revision_id": str(MACHINE_REVISION), "validation_run_id": str(MACHINE_VALIDATION)}  # type: ignore[index]
    legacy_view = project_decision(legacy)
    assert legacy_view.correlation_id is None

    invalid = _base_snapshot()
    invalid["audits"][0]["safe_metadata"] = {"correlation_id": "not-a-uuid"}  # type: ignore[index]
    invalid_view = project_decision(invalid)
    assert invalid_view.status is AgentRunStatus.failed

    duplicate = _base_snapshot()
    duplicate["audits"].append(deepcopy(duplicate["audits"][0]))  # type: ignore[index]
    duplicate_view = project_decision(duplicate)
    assert duplicate_view.status is AgentRunStatus.failed

    mismatch = _base_snapshot()
    mismatch["audits"][1]["safe_metadata"]["correlation_id"] = str(uuid4())  # type: ignore[index]
    mismatch_view = project_decision(mismatch)
    assert mismatch_view.status is AgentRunStatus.failed


def test_projection_is_deterministic_and_side_effect_free() -> None:
    snapshot = _base_snapshot()
    before = deepcopy(snapshot)
    first = project_decision(snapshot)
    second = project_decision(deepcopy(snapshot))
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert snapshot == before
    import app.agents.decision.projection as projection

    assert "uuid4" not in projection.__dict__
    assert "datetime_now" not in projection.__dict__
