"""Pure projection of the persisted deep-review snapshot.

The SQL adapter assembles a read snapshot and this module only interprets it.
It deliberately has no SQLAlchemy, clock, UUID allocator, service, worker, or
report-materializer dependency.  A malformed persisted graph is represented
as a safe failed run instead of being silently promoted to a successful one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
import hashlib
import json
from typing import Any
from uuid import UUID

from ..common import (
    AgentAction,
    AgentAggregateRef,
    AgentAggregateType,
    AgentArtifactRef,
    AgentArtifactType,
    AgentErrorCode,
    AgentName,
    AgentOutcomeCode,
    AgentRunStatus,
    AgentRunView,
    AgentSafeError,
    AgentStepStatus,
    AgentStepView,
    classify_error_code,
    deep_review_run_id,
    latest_timestamp,
    make_safe_error,
)


STAGE_NAMES: tuple[str, ...] = (
    "requirements_and_evaluation",
    "delivery_risk_economics",
    "synthesis_and_validation",
)
STAGE_SEQUENCE = {name: index for index, name in enumerate(STAGE_NAMES, start=1)}
_SHA256 = set("0123456789abcdef")


class DeepReviewProjectionError(ValueError):
    """A persisted deep-review graph cannot satisfy the agent contract."""


def _get(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _text(value: object, field_name: str) -> str:
    if value is None:
        raise DeepReviewProjectionError(f"{field_name} is missing")
    result = str(value)
    if not result.strip():
        raise DeepReviewProjectionError(f"{field_name} is blank")
    return result


def _uuid_text(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    try:
        return str(value if isinstance(value, UUID) else UUID(result))
    except (TypeError, ValueError, AttributeError) as exc:
        raise DeepReviewProjectionError(f"{field_name} is not a UUID") from exc


def _sha(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if len(result) != 64 or any(char not in _SHA256 for char in result):
        raise DeepReviewProjectionError(f"{field_name} is not a sha256")
    return result


def _timestamp(value: object, field_name: str, *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            raise DeepReviewProjectionError(f"{field_name} is missing")
        return None
    if not isinstance(value, datetime):
        raise DeepReviewProjectionError(f"{field_name} is not persisted")
    if value.tzinfo is None or value.utcoffset() is None:
        raise DeepReviewProjectionError(f"{field_name} is not timezone-aware")
    return value


def _json_value(value: object) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # Decimal and other persisted scalar wrappers are represented by their
    # stable text form for hashing; they are never returned in the view.
    return str(value)


def _hash(value: object) -> str:
    encoded = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, Mapping) or isinstance(value, (str, bytes, bytearray)):
        return []
    return list(value)  # type: ignore[arg-type]


def _snapshot_parts(
    snapshot: Mapping[str, Any] | object,
    attempts: Iterable[object] | None = None,
    stages: object = None,
    *,
    bundle: object = None,
    bundle_items: Iterable[object] | None = None,
    profile: object = None,
    policy: object = None,
    audits: Iterable[object] | None = None,
    bundle_creation_audits: Iterable[object] | None = None,
    revisions: Iterable[object] | None = None,
    validations: Iterable[object] | None = None,
    validation_checks: Iterable[object] | None = None,
    revision_evidence: Iterable[object] | None = None,
    evidence: Iterable[object] | None = None,
    jobs: Iterable[object] | None = None,
) -> dict[str, Any]:
    if isinstance(snapshot, Mapping) and "review" in snapshot:
        source = snapshot
        review = source.get("review")
        return {
            "review": review,
            "attempts": _as_list(source.get("attempts")),
            "stages": source.get("stages", {}),
            "bundle": source.get("bundle"),
            "bundle_items": _as_list(source.get("bundle_items")),
            "profile": source.get("profile"),
            "policy": source.get("policy"),
            "audits": _as_list(source.get("audits", source.get("review_audits"))),
            "bundle_creation_audits": _as_list(source.get("bundle_creation_audits", source.get("bundle_creation_audit"))),
            "revisions": _as_list(source.get("revisions")),
            "validations": _as_list(source.get("validations")),
            "validation_checks": _as_list(source.get("validation_checks")),
            "revision_evidence": _as_list(source.get("revision_evidence")),
            "evidence": _as_list(source.get("evidence")),
            "jobs": _as_list(source.get("jobs")),
        }
    return {
        "review": snapshot,
        "attempts": list(attempts or ()),
        "stages": stages or {},
        "bundle": bundle,
        "bundle_items": list(bundle_items or ()),
        "profile": profile,
        "policy": policy,
        "audits": list(audits or ()),
        "bundle_creation_audits": list(bundle_creation_audits or ()),
        "revisions": list(revisions or ()),
        "validations": list(validations or ()),
        "validation_checks": list(validation_checks or ()),
        "revision_evidence": list(revision_evidence or ()),
        "evidence": list(evidence or ()),
        "jobs": list(jobs or ()),
    }


def _stages_for(parts: Mapping[str, Any], attempt_id: str) -> list[object]:
    source = parts.get("stages")
    if isinstance(source, Mapping):
        rows = source.get(attempt_id)
        if rows is None:
            rows = source.get(UUID(attempt_id)) if _is_uuid(attempt_id) else None
        return _as_list(rows)
    return [row for row in _as_list(source) if str(_get(row, "attempt_id")) == attempt_id]


def _is_uuid(value: object) -> bool:
    try:
        UUID(str(value))
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def _audit_action(audit: object, action: str, aggregate_id: str | None = None) -> bool:
    if _get(audit, "action") != action:
        return False
    expected_type = "document_bundle" if action == "document_bundle.create" else "deep_review"
    if _get(audit, "aggregate_type") != expected_type:
        return False
    if aggregate_id is not None and str(_get(audit, "aggregate_id")) != aggregate_id:
        return False
    return True


def _metadata(audit: object) -> Mapping[str, Any]:
    value = _get(audit, "safe_metadata", {})
    return value if isinstance(value, Mapping) else {}


def _correlation_from_audit(audit: object, *, field_name: str) -> UUID | None:
    metadata = _metadata(audit)
    if "correlation_id" not in metadata:
        return None
    value = metadata.get("correlation_id")
    if value is None:
        raise DeepReviewProjectionError(f"{field_name}.correlation_id is null")
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise DeepReviewProjectionError(f"{field_name}.correlation_id is invalid") from exc


def _lineage(parts: Mapping[str, Any], review_id: str, bundle_id: str) -> UUID | None:
    bundle_audits = [
        row for row in _as_list(parts.get("bundle_creation_audits"))
        if _audit_action(row, "document_bundle.create", bundle_id)
    ]
    if len(bundle_audits) > 1:
        raise DeepReviewProjectionError("document bundle creation audit is duplicated")
    bundle_lineage = _correlation_from_audit(bundle_audits[0], field_name="bundle audit") if bundle_audits else None

    create_audits = [
        row for row in _as_list(parts.get("audits"))
        if _audit_action(row, "deep_review.create", review_id)
    ]
    if len(create_audits) != 1:
        raise DeepReviewProjectionError("deep review creation audit is missing or duplicated")
    review_lineage = _correlation_from_audit(create_audits[0], field_name="review audit")
    if bundle_lineage != review_lineage:
        raise DeepReviewProjectionError("review correlation lineage does not match bundle lineage")

    attempt_audits = [
        row for row in _as_list(parts.get("audits"))
        if _audit_action(row, "deep_review.attempt", review_id)
    ]
    for row in attempt_audits:
        attempt_lineage = _correlation_from_audit(row, field_name="attempt audit")
        if attempt_lineage != review_lineage:
            raise DeepReviewProjectionError("attempt correlation lineage does not match review lineage")
    return review_lineage


def bundle_snapshot_sha256(bundle: object, items: Iterable[object] = ()) -> str:
    """Return the same immutable ready-bundle hash used by the handoff ref."""

    explicit = _get(bundle, "sha256")
    item_list = list(items)
    if explicit is not None and not item_list:
        return _sha(explicit, "bundle.sha256")
    documents = [
        {
            "document_version_id": str(_get(item, "document_version_id")),
            "document_version_version": _get(item, "document_version_version"),
            "ordinal": _get(item, "ordinal"),
            "content_sha256": _get(item, "content_sha256"),
            "detected_mime": _get(item, "detected_mime"),
            "size_bytes": _get(item, "size_bytes"),
            "role_at_confirmation": _get(item, "role_at_confirmation"),
            "effective_date_at_confirmation": _json_value(_get(item, "effective_date_at_confirmation")),
            "replaces_id_at_confirmation": _json_value(_get(item, "replaces_id_at_confirmation")),
            "is_current_at_confirmation": _get(item, "is_current_at_confirmation"),
            "safety_status_at_confirmation": _get(item, "safety_status_at_confirmation"),
            "structure_id_at_confirmation": _json_value(_get(item, "structure_id_at_confirmation")),
            "structure_payload_sha256": _get(item, "structure_payload_sha256"),
        }
        for item in sorted(item_list, key=lambda row: (int(_get(row, "ordinal", 0)), str(_get(row, "document_version_id", ""))))
    ]
    issues = _get(bundle, "issues_snapshot", _get(bundle, "issues", []))
    return _hash({
        "schema": "bidops.document-bundle.v1",
        "bundle_id": _json_value(_get(bundle, "id")),
        "notice_id": _get(bundle, "notice_id"),
        "revision": _get(bundle, "revision"),
        "version": _get(bundle, "version"),
        "status": "ready",
        "documents": documents,
        "issues": issues if isinstance(issues, list) else [],
        "confirmed_by": _get(bundle, "confirmed_by_name", _get(bundle, "confirmed_by")),
        "confirmed_at": _json_value(_get(bundle, "confirmed_at")),
        "created_at": _json_value(_get(bundle, "created_at")),
    })


def bundle_artifact_ref(bundle: object, items: Iterable[object] = ()) -> AgentArtifactRef:
    bundle_id = _uuid_text(_get(bundle, "id", _get(bundle, "bundle_id")), "bundle.id")
    version = _get(bundle, "version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise DeepReviewProjectionError("bundle.version is invalid")
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.document_bundle,
        artifact_id=bundle_id,
        version=version,
        sha256=bundle_snapshot_sha256(bundle, items),
    )


def _attempt_ref(attempt: object, stages: Sequence[object]) -> AgentArtifactRef:
    attempt_id = _uuid_text(_get(attempt, "id"), "attempt.id")
    sequence = _get(attempt, "sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise DeepReviewProjectionError("attempt.sequence is invalid")
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.deep_review_attempt,
        artifact_id=attempt_id,
        version=sequence,
        sha256=None,
    )


attempt_artifact_ref = _attempt_ref


def _stage_ref(stage: object) -> AgentArtifactRef:
    stage_id = _uuid_text(_get(stage, "id"), "stage.id")
    sequence = _get(stage, "sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise DeepReviewProjectionError("stage.sequence is invalid")
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.deep_review_stage,
        artifact_id=stage_id,
        version=sequence,
        sha256=_hash(_get(stage, "structured_output", {})),
    )


def _validation_ref(validation: object, checks: Sequence[object]) -> AgentArtifactRef:
    validation_id = _uuid_text(_get(validation, "id"), "validation.id")
    sequence = _get(validation, "sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise DeepReviewProjectionError("validation.sequence is invalid")
    payload = {
        "schema": "bidops.deep-review-validation.v1",
        "validation_run_id": validation_id,
        "report_revision_id": _uuid_text(_get(validation, "report_revision_id"), "validation.report_revision_id"),
        "status": _get(validation, "status"),
        "checks": [
            {
                "check_type": _get(check, "check_type"),
                "status": _get(check, "status"),
                "severity": _get(check, "severity"),
                "message": _get(check, "message"),
                "related_claim_ids": _json_value(_get(check, "related_claim_ids", [])),
                "related_evidence_ids": _json_value(_get(check, "related_evidence_ids", [])),
            }
            for check in checks
        ],
        "created_at": _timestamp(_get(validation, "created_at"), "validation.created_at", required=True).isoformat(),
    }
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.validation_run,
        artifact_id=validation_id,
        version=sequence,
        sha256=_hash(payload),
    )


def _revision_ref(revision: object) -> AgentArtifactRef:
    revision_id = _uuid_text(_get(revision, "id"), "report_revision.id")
    sequence = _get(revision, "sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise DeepReviewProjectionError("report revision sequence is invalid")
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.report_revision,
        artifact_id=revision_id,
        version=sequence,
        sha256=_sha(_get(revision, "report_sha256"), "report_revision.report_sha256"),
    )


def _evidence_ref(evidence: object) -> AgentArtifactRef:
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.evidence,
        artifact_id=_uuid_text(_get(evidence, "id", _get(evidence, "evidence_id")), "evidence.id"),
        version=None,
        sha256=_sha(_get(evidence, "source_sha256"), "evidence.source_sha256"),
    )


def _error_from_code(value: object) -> AgentErrorCode:
    return classify_error_code(value)


def _stage_error(stage: object) -> AgentErrorCode | None:
    metadata = _get(stage, "invocation_metadata", {})
    entries: list[object]
    if isinstance(metadata, list):
        entries = list(metadata)
    elif isinstance(metadata, Mapping):
        entries = [metadata]
    else:
        entries = []
    for entry in reversed(entries):
        if not isinstance(entry, Mapping):
            continue
        value = entry.get("error_code") or entry.get("last_error_code")
        if value:
            return _error_from_code(value)
    return None


def _job_error(parts: Mapping[str, Any], attempt_id: str) -> AgentErrorCode | None:
    attempt = next(
        (row for row in _as_list(parts.get("attempts")) if str(_get(row, "id")) == attempt_id),
        None,
    )
    work_job_id = str(_get(attempt, "work_job_id")) if attempt is not None else None
    for job in sorted(_as_list(parts.get("jobs")), key=lambda row: str(_get(row, "id", "")), reverse=True):
        if work_job_id is not None and str(_get(job, "id")) != work_job_id:
            continue
        if work_job_id is None and str(_get(job, "aggregate_id")) != str(_get(parts["review"], "id")):
            continue
        value = _get(job, "last_error_code")
        if value:
            return _error_from_code(value)
    return None


def _step_views(stages: Sequence[object], *, force_failure: bool = False) -> list[AgentStepView]:
    result: list[AgentStepView] = []
    for index, stage in enumerate(stages, start=1):
        name = str(_get(stage, "stage", f"invalid_stage_{index}"))
        status_value = str(_get(stage, "status", "failed"))
        try:
            status = AgentStepStatus(status_value)
        except ValueError:
            status = AgentStepStatus.failed
        result.append(AgentStepView(
            step_name=name,
            sequence=index,
            status=status,
            started_at=_timestamp(_get(stage, "started_at"), f"stage[{index}].started_at"),
            completed_at=_timestamp(_get(stage, "completed_at"), f"stage[{index}].completed_at"),
            last_error_code=_stage_error(stage) if status is AgentStepStatus.failed else None,
        ))
    return result


def _valid_stage_graph(stages: Sequence[object]) -> bool:
    if len(stages) != len(STAGE_NAMES):
        return False
    return (
        tuple(_get(stage, "stage") for stage in stages) == STAGE_NAMES
        and tuple(_get(stage, "sequence") for stage in stages) == (1, 2, 3)
        and all(str(_get(stage, "status")) in {"queued", "running", "completed", "failed"} for stage in stages)
    )


def _attempt_audit_created_at(parts: Mapping[str, Any], review_id: str, attempt: object) -> datetime:
    attempt_id = _uuid_text(_get(attempt, "id"), "attempt.id")
    sequence = _get(attempt, "sequence")
    if sequence == 1:
        rows = [
            row for row in _as_list(parts.get("audits"))
            if _audit_action(row, "deep_review.create", review_id)
        ]
    else:
        rows = [
            row for row in _as_list(parts.get("audits"))
            if _audit_action(row, "deep_review.attempt", review_id)
            and str(_metadata(row).get("attempt_id")) == attempt_id
        ]
    if len(rows) != 1:
        raise DeepReviewProjectionError("attempt creation audit is missing or duplicated")
    return _timestamp(_get(rows[0], "created_at"), "attempt creation audit.created_at", required=True)  # type: ignore[return-value]


def _machine_artifacts(parts: Mapping[str, Any], review_id: str, attempt_id: str) -> tuple[object, object, list[object], list[object]]:
    audits = [
        row for row in _as_list(parts.get("audits"))
        if _audit_action(row, "deep_review.report.machine_materialized", review_id)
        and str(_metadata(row).get("attempt_id")) == attempt_id
    ]
    if len(audits) != 1:
        raise DeepReviewProjectionError("machine report materialization audit is missing or duplicated")
    revision_id = _metadata(audits[0]).get("revision_id")
    revisions = [
        row for row in _as_list(parts.get("revisions"))
        if str(_get(row, "id")) == str(revision_id)
        and str(_get(row, "deep_review_id")) == review_id
        and _get(row, "origin") == "machine"
    ]
    if len(revisions) != 1:
        raise DeepReviewProjectionError("machine report revision is missing or invalid")
    revision = revisions[0]
    validations = [
        row for row in _as_list(parts.get("validations"))
        if str(_get(row, "deep_review_id")) == review_id
        and str(_get(row, "report_revision_id")) == str(_get(revision, "id"))
    ]
    if len(validations) != 1 or str(_get(validations[0], "status")) not in {"passed", "failed"}:
        raise DeepReviewProjectionError("machine report validation is missing or invalid")
    validation = validations[0]
    checks = sorted(
        [
            row for row in _as_list(parts.get("validation_checks"))
            if str(_get(row, "validation_run_id")) == str(_get(validation, "id"))
        ],
        key=lambda row: str(_get(row, "id", "")),
    )
    links = [
        row for row in _as_list(parts.get("revision_evidence"))
        if str(_get(row, "deep_review_id")) == review_id
        and str(_get(row, "report_revision_id")) == str(_get(revision, "id"))
    ]
    evidence_by_id = {
        str(_get(row, "id", _get(row, "evidence_id"))): row
        for row in _as_list(parts.get("evidence"))
        if _get(row, "id", _get(row, "evidence_id")) is not None
    }
    evidence_rows: list[object] = []
    for link in sorted(links, key=lambda row: str(_get(row, "evidence_ref_id"))):
        evidence_id = str(_get(link, "evidence_ref_id"))
        if evidence_id not in evidence_by_id:
            raise DeepReviewProjectionError("machine report evidence is out of scope")
        evidence_rows.append(evidence_by_id[evidence_id])
    return revision, validation, checks, evidence_rows


def _safe_created_fallback(review: object, attempt: object) -> datetime:
    for value in (
        _get(review, "created_at"),
        _get(attempt, "started_at"),
        _get(attempt, "completed_at"),
    ):
        timestamp = _timestamp(value, "fallback timestamp")
        if timestamp is not None:
            return timestamp
    raise DeepReviewProjectionError("no persisted timestamp is available")


def _projection_failure(
    *,
    review: object,
    attempt: object,
    stages: Sequence[object],
    parts: Mapping[str, Any],
    reason: object,
    created_at: datetime | None = None,
    correlation_id: UUID | None = None,
) -> AgentRunView:
    review_id = _uuid_text(_get(review, "id"), "review.id")
    attempt_id = _uuid_text(_get(attempt, "id"), "attempt.id")
    created = created_at or _safe_created_fallback(review, attempt)
    saved = [
        created,
        _timestamp(_get(review, "created_at"), "review.created_at"),
        _timestamp(_get(review, "completed_at"), "review.completed_at"),
        _timestamp(_get(attempt, "started_at"), "attempt.started_at"),
        _timestamp(_get(attempt, "completed_at"), "attempt.completed_at"),
        *(_timestamp(_get(stage, "started_at"), "stage.started_at") for stage in stages),
        *(_timestamp(_get(stage, "completed_at"), "stage.completed_at") for stage in stages),
        *(_timestamp(_get(row, "created_at"), "audit.created_at") for row in _as_list(parts.get("audits"))),
    ]
    updated = latest_timestamp(saved) or created
    error = make_safe_error(AgentErrorCode.processing_failed)
    return AgentRunView(
        schema="bidops.agent-run.v1",
        agent_name=AgentName.deep_review,
        run_id=deep_review_run_id(review_id, attempt_id),
        aggregate=AgentAggregateRef(aggregate_type=AgentAggregateType.deep_review, aggregate_id=review_id),
        execution_ref=None,
        status=AgentRunStatus.failed,
        outcome_code=None,
        current_step=None,
        steps=_step_views(stages),
        input_refs=[],
        output_refs=[],
        wait=None,
        error=error,
        available_actions=(
            [AgentAction.retry_attempt]
            if str(_get(_get(parts, "review"), "current_attempt_id")) == attempt_id
            and str(_get(attempt, "status")) in {"failed", "completed"}
            and not any(str(_get(row, "status")) in {"queued", "running"} for row in _as_list(parts.get("attempts")))
            else []
        ),
        correlation_id=correlation_id,
        created_at=created,
        started_at=_timestamp(_get(attempt, "started_at"), "attempt.started_at"),
        updated_at=updated,
        completed_at=_timestamp(_get(attempt, "completed_at"), "attempt.completed_at"),
    )


def project_deep_review(
    snapshot: Mapping[str, Any] | object,
    attempts: Iterable[object] | None = None,
    stages: object = None,
    *,
    attempt_id: UUID | str | None = None,
    bundle: object = None,
    bundle_items: Iterable[object] | None = None,
    profile: object = None,
    policy: object = None,
    audits: Iterable[object] | None = None,
    bundle_creation_audits: Iterable[object] | None = None,
    revisions: Iterable[object] | None = None,
    validations: Iterable[object] | None = None,
    validation_checks: Iterable[object] | None = None,
    revision_evidence: Iterable[object] | None = None,
    evidence: Iterable[object] | None = None,
    jobs: Iterable[object] | None = None,
) -> AgentRunView:
    """Project one persisted attempt into the common run contract.

    The preferred call passes one mapping containing the complete read
    snapshot.  Keyword arguments are retained for small pure unit fixtures
    and make the function convenient without introducing a database type.
    """

    parts = _snapshot_parts(
        snapshot,
        attempts,
        stages,
        bundle=bundle,
        bundle_items=bundle_items,
        profile=profile,
        policy=policy,
        audits=audits,
        bundle_creation_audits=bundle_creation_audits,
        revisions=revisions,
        validations=validations,
        validation_checks=validation_checks,
        revision_evidence=revision_evidence,
        evidence=evidence,
        jobs=jobs,
    )
    review = parts.get("review")
    if review is None:
        raise DeepReviewProjectionError("review snapshot is missing")
    review_id = _uuid_text(_get(review, "id"), "review.id")
    attempt_rows = sorted(
        _as_list(parts.get("attempts")),
        key=lambda row: (int(_get(row, "sequence", 0)), str(_get(row, "id", ""))),
    )
    current_id = str(attempt_id) if attempt_id is not None else str(_get(review, "current_attempt_id"))
    current = next((row for row in attempt_rows if str(_get(row, "id")) == current_id), None)
    invalid_current_pointer = current is None
    if current is None:
        if attempt_rows:
            current = attempt_rows[-1]
        else:
            raise DeepReviewProjectionError("current attempt snapshot is missing")
    current_id = _uuid_text(_get(current, "id"), "attempt.id")
    stage_rows = _stages_for(parts, current_id)

    try:
        lineage = _lineage(
            parts,
            review_id,
            _uuid_text(_get(review, "bundle_id"), "review.bundle_id"),
        )
        created_at = _attempt_audit_created_at(parts, review_id, current)
        if invalid_current_pointer:
            raise DeepReviewProjectionError("current attempt pointer is invalid")
        stage_graph_ok = _valid_stage_graph(stage_rows)
        if not stage_graph_ok:
            raise DeepReviewProjectionError("stage graph is not exactly the ordered three-stage contract")

        input_refs = [
            bundle_artifact_ref(parts.get("bundle"), parts.get("bundle_items", ())),
            AgentArtifactRef(
                artifact_type=AgentArtifactType.profile_version,
                artifact_id=_uuid_text(_get(parts.get("profile"), "id"), "profile.id"),
                version=int(_get(parts.get("profile"), "version")),
                sha256=_sha(_get(parts.get("profile"), "profile_sha256"), "profile.profile_sha256"),
            ),
            AgentArtifactRef(
                artifact_type=AgentArtifactType.policy_version,
                artifact_id=_uuid_text(_get(parts.get("policy"), "id"), "policy.id"),
                version=int(_get(parts.get("policy"), "version")),
                sha256=_sha(_get(parts.get("policy"), "policy_sha256"), "policy.policy_sha256"),
            ),
        ]
        execution_ref = _attempt_ref(current, stage_rows)
        attempt_status = str(_get(current, "status"))
        if attempt_status not in {"queued", "running", "failed", "completed", "superseded"}:
            raise DeepReviewProjectionError("attempt status is invalid")

        failed_stage = next((row for row in stage_rows if str(_get(row, "status")) == "failed"), None)
        persisted_error = _stage_error(failed_stage) if failed_stage is not None else _job_error(parts, current_id)
        if attempt_status == "completed":
            if any(str(_get(row, "status")) != "completed" for row in stage_rows):
                raise DeepReviewProjectionError("completed attempt has incomplete stages")
            revision, validation, validation_check_rows, evidence_rows = _machine_artifacts(parts, review_id, current_id)
            output_refs = [
                *[_stage_ref(row) for row in stage_rows],
                _revision_ref(revision),
                _validation_ref(validation, validation_check_rows),
                *[_evidence_ref(row) for row in evidence_rows],
            ]
            validation_status = str(_get(validation, "status"))
            outcome = (
                AgentOutcomeCode.report_ready_validated
                if validation_status == "passed"
                else AgentOutcomeCode.report_ready_validation_failed
            )
            run_status = AgentRunStatus.completed
            error = None
            current_step = None
        elif attempt_status == "superseded":
            if all(str(_get(row, "status")) == "completed" for row in stage_rows):
                raise DeepReviewProjectionError("completed attempts must not be superseded")
            output_refs = [_stage_ref(row) for row in stage_rows if str(_get(row, "status")) == "completed"]
            run_status = AgentRunStatus.superseded
            outcome = AgentOutcomeCode.superseded_by_retry
            error = make_safe_error(persisted_error or AgentErrorCode.processing_failed)
            current_step = None
        elif attempt_status == "failed":
            output_refs = [_stage_ref(row) for row in stage_rows if str(_get(row, "status")) == "completed"]
            run_status = AgentRunStatus.failed
            outcome = None
            error = make_safe_error(persisted_error or AgentErrorCode.processing_failed)
            current_step = str(_get(failed_stage, "stage")) if failed_stage is not None else None
        else:
            output_refs = [_stage_ref(row) for row in stage_rows if str(_get(row, "status")) == "completed"]
            run_status = AgentRunStatus(attempt_status)
            outcome = None
            error = None
            current_step = (
                str(_get(next((row for row in stage_rows if str(_get(row, "status")) == "running"), None), "stage"))
                if attempt_status == "running"
                else str(_get(next((row for row in stage_rows if str(_get(row, "status")) != "completed"), None), "stage"))
            )
            if current_step == "None":
                current_step = None

        active = any(
            str(_get(row, "status")) in {"queued", "running"}
            for row in attempt_rows
        )
        is_current = str(_get(review, "current_attempt_id")) == current_id
        available = [
            AgentAction.retry_attempt
        ] if is_current and str(_get(current, "status")) in {"failed", "completed"} and not active else []

        timestamps: list[datetime | None] = [
            created_at,
            _timestamp(_get(review, "created_at"), "review.created_at"),
            _timestamp(_get(review, "completed_at"), "review.completed_at"),
            _timestamp(_get(current, "started_at"), "attempt.started_at"),
            _timestamp(_get(current, "completed_at"), "attempt.completed_at"),
            *(_timestamp(_get(row, "started_at"), "stage.started_at") for row in stage_rows),
            *(_timestamp(_get(row, "completed_at"), "stage.completed_at") for row in stage_rows),
        ]
        if attempt_status == "completed":
            timestamps.extend([
                _timestamp(_get(revision, "created_at"), "revision.created_at"),
                _timestamp(_get(validation, "created_at"), "validation.created_at"),
            ])
        updated_at = latest_timestamp(timestamps) or created_at
        completed_at = _timestamp(_get(current, "completed_at"), "attempt.completed_at")
        steps = _step_views(stage_rows)
        return AgentRunView(
            schema="bidops.agent-run.v1",
            agent_name=AgentName.deep_review,
            run_id=deep_review_run_id(review_id, current_id),
            aggregate=AgentAggregateRef(aggregate_type=AgentAggregateType.deep_review, aggregate_id=review_id),
            execution_ref=execution_ref,
            status=run_status,
            outcome_code=outcome,
            current_step=current_step if run_status not in {AgentRunStatus.completed, AgentRunStatus.superseded} else None,
            steps=steps,
            input_refs=input_refs,
            output_refs=output_refs,
            wait=None,
            error=error,
            available_actions=available if run_status not in {AgentRunStatus.superseded} else [],
            correlation_id=lineage,
            created_at=created_at,
            started_at=_timestamp(_get(current, "started_at"), "attempt.started_at"),
            updated_at=updated_at,
            completed_at=completed_at,
        )
    except (DeepReviewProjectionError, ValueError, TypeError, KeyError):
        return _projection_failure(
            review=review,
            attempt=current,
            stages=stage_rows,
            parts=parts,
            reason="processing_failed",
        )


project_review = project_deep_review
project_run = project_deep_review
build_deep_review_run = project_deep_review
project = project_deep_review


__all__ = [
    "STAGE_NAMES",
    "STAGE_SEQUENCE",
    "DeepReviewProjectionError",
    "attempt_artifact_ref",
    "build_deep_review_run",
    "bundle_artifact_ref",
    "bundle_snapshot_sha256",
    "project",
    "project_deep_review",
    "project_review",
    "project_run",
]
