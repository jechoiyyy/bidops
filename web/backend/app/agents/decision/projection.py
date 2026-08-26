"""Pure projection of the persisted decision workflow snapshot.

The decision agent owns no persistence.  Its state is derived from the
append-only report, validation, opinion, and audit rows supplied by the SQL
adapter.  Invalid lineage is represented as a safe failed run; the projection
never allocates identifiers, timestamps, or audit events.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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
    AgentStepStatus,
    AgentStepView,
    AgentWait,
    decision_run_id,
    latest_timestamp,
    make_safe_error,
    make_wait,
)


STEP_NAMES: tuple[str, ...] = (
    "await_machine_report",
    "review_report_and_evidence",
    "record_final_opinion",
)
_SHA256 = set("0123456789abcdef")


class DecisionProjectionError(ValueError):
    """A persisted decision graph cannot satisfy the closed agent contract."""


def _get(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _as_list(value: object) -> list[object]:
    if value is None or isinstance(value, Mapping) or isinstance(value, (str, bytes, bytearray)):
        return []
    return list(value)  # type: ignore[arg-type]


def _text(value: object, field_name: str) -> str:
    if value is None:
        raise DecisionProjectionError(f"{field_name} is missing")
    result = str(value)
    if not result.strip():
        raise DecisionProjectionError(f"{field_name} is blank")
    return result


def _uuid_text(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    try:
        return str(value if isinstance(value, UUID) else UUID(result))
    except (TypeError, ValueError, AttributeError) as exc:
        raise DecisionProjectionError(f"{field_name} is not a UUID") from exc


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DecisionProjectionError(f"{field_name} is invalid")
    return value


def _sha(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if len(result) != 64 or any(char not in _SHA256 for char in result):
        raise DecisionProjectionError(f"{field_name} is not a sha256")
    return result


def _timestamp(value: object, field_name: str, *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            raise DecisionProjectionError(f"{field_name} is missing")
        return None
    if not isinstance(value, datetime):
        raise DecisionProjectionError(f"{field_name} is not persisted")
    if value.tzinfo is None or value.utcoffset() is None:
        raise DecisionProjectionError(f"{field_name} is not timezone-aware")
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
    return str(value)


def canonical_json_hash(value: object) -> str:
    """Hash a JSON-compatible value with the repository canonical encoding."""

    encoded = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_parts(
    snapshot: Mapping[str, Any] | object,
    revisions: Iterable[object] | None = None,
    validations: Iterable[object] | None = None,
    validation_checks: Iterable[object] | None = None,
    revision_evidence: Iterable[object] | None = None,
    evidence: Iterable[object] | None = None,
    opinions: Iterable[object] | None = None,
    audits: Iterable[object] | None = None,
    *,
    checks: Iterable[object] | None = None,
    report_revision_evidence: Iterable[object] | None = None,
    final_opinions: Iterable[object] | None = None,
) -> dict[str, Any]:
    if isinstance(snapshot, Mapping) and "review" in snapshot:
        source = snapshot
        return {
            "review": source.get("review"),
            "revisions": _as_list(source.get("revisions")),
            "validations": _as_list(source.get("validations")),
            "validation_checks": _as_list(source.get("validation_checks", source.get("checks"))),
            "revision_evidence": _as_list(source.get("revision_evidence", source.get("report_revision_evidence"))),
            "evidence": _as_list(source.get("evidence")),
            "opinions": _as_list(source.get("opinions", source.get("final_opinions"))),
            "audits": _as_list(source.get("audits", source.get("review_audits"))),
        }
    return {
        "review": snapshot,
        "revisions": list(revisions or ()),
        "validations": list(validations or ()),
        "validation_checks": list(validation_checks or checks or ()),
        "revision_evidence": list(revision_evidence or report_revision_evidence or ()),
        "evidence": list(evidence or ()),
        "opinions": list(opinions or final_opinions or ()),
        "audits": list(audits or ()),
    }


def _audit_matches(audit: object, action: str, review_id: str) -> bool:
    return (
        _get(audit, "action") == action
        and _get(audit, "aggregate_type") == "deep_review"
        and str(_get(audit, "aggregate_id")) == review_id
    )


def _metadata(audit: object, field_name: str) -> Mapping[str, Any]:
    value = _get(audit, "safe_metadata", {})
    if not isinstance(value, Mapping):
        raise DecisionProjectionError(f"{field_name}.safe_metadata is invalid")
    return value


def _correlation(audit: object, field_name: str) -> UUID | None:
    metadata = _metadata(audit, field_name)
    if "correlation_id" not in metadata:
        # Older audit rows predate the correlation field.  They remain
        # explicitly lineage-less rather than receiving a generated value.
        return None
    value = metadata.get("correlation_id")
    if value is None:
        raise DecisionProjectionError(f"{field_name}.correlation_id is null")
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise DecisionProjectionError(f"{field_name}.correlation_id is invalid") from exc


def _ordered_rows(rows: Iterable[object], field_name: str, review_id: str) -> list[object]:
    result = list(rows)
    seen_ids: set[str] = set()
    seen_sequences: set[int] = set()
    for row in result:
        if str(_get(row, "deep_review_id")) != review_id:
            raise DecisionProjectionError(f"{field_name} is outside the deep review scope")
        row_id = _uuid_text(_get(row, "id"), f"{field_name}.id")
        if row_id in seen_ids:
            raise DecisionProjectionError(f"{field_name} is duplicated")
        seen_ids.add(row_id)
        sequence = _positive_int(_get(row, "sequence"), f"{field_name}.sequence")
        if sequence in seen_sequences:
            raise DecisionProjectionError(f"{field_name}.sequence is duplicated")
        seen_sequences.add(sequence)
    return sorted(result, key=lambda row: (int(_get(row, "sequence")), _uuid_text(_get(row, "id"), f"{field_name}.id")))


def _lineage(parts: Mapping[str, Any], review_id: str) -> tuple[object, UUID | None, datetime]:
    rows = [
        row for row in _as_list(parts.get("audits"))
        if _audit_matches(row, "deep_review.create", review_id)
    ]
    if len(rows) != 1:
        raise DecisionProjectionError("deep review creation audit is missing or duplicated")
    created_at = _timestamp(_get(rows[0], "created_at"), "deep_review.create.created_at", required=True)
    return rows[0], _correlation(rows[0], "deep_review.create"), created_at  # type: ignore[return-value]


def _failure_context(parts: Mapping[str, Any], review_id: str) -> tuple[datetime, UUID | None]:
    """Find only persisted data needed to render a safe failed run."""

    root_rows = [
        row for row in _as_list(parts.get("audits"))
        if _audit_matches(row, "deep_review.create", review_id)
    ]
    root_rows = sorted(root_rows, key=lambda row: (str(_get(row, "created_at", "")), str(_get(row, "id", ""))))
    if root_rows:
        root = root_rows[0]
        created_at = _timestamp(_get(root, "created_at"), "deep_review.create.created_at", required=True)
        if len(root_rows) != 1:
            return created_at, None
        try:
            lineage = _correlation(root, "deep_review.create")
        except DecisionProjectionError:
            lineage = None
        return created_at, lineage  # type: ignore[return-value]

    candidates: list[datetime] = []
    for collection, field_name in (
        (parts.get("audits"), "audit.created_at"),
        (parts.get("revisions"), "report_revision.created_at"),
        (parts.get("validations"), "validation_run.created_at"),
        (parts.get("opinions"), "final_opinion.created_at"),
    ):
        for row in _as_list(collection):
            value = _timestamp(_get(row, "created_at"), field_name)
            if value is not None:
                candidates.append(value)
    if not candidates:
        raise DecisionProjectionError("no persisted decision timestamp is available")
    return min(candidates), None


def _check_payload(check: object, field_name: str) -> dict[str, Any]:
    check_type = _text(_get(check, "check_type"), f"{field_name}.check_type")
    status = _text(_get(check, "status"), f"{field_name}.status")
    severity = _text(_get(check, "severity"), f"{field_name}.severity")
    message = _text(_get(check, "message"), f"{field_name}.message")
    related_claim_ids = _get(check, "related_claim_ids", [])
    related_evidence_ids = _get(check, "related_evidence_ids", [])
    if not isinstance(related_claim_ids, (list, tuple)) or not isinstance(related_evidence_ids, (list, tuple)):
        raise DecisionProjectionError(f"{field_name} related IDs are invalid")
    return {
        "check_type": check_type,
        "status": status,
        "severity": severity,
        "message": message,
        "related_claim_ids": _json_value(related_claim_ids),
        "related_evidence_ids": _json_value(related_evidence_ids),
    }


def validation_snapshot_payload(validation: object, checks: Iterable[object]) -> dict[str, Any]:
    """Return the stable public validation snapshot used for artifact hashing."""

    validation_id = _uuid_text(_get(validation, "id"), "validation_run.id")
    revision_id = _uuid_text(_get(validation, "report_revision_id"), "validation_run.report_revision_id")
    status = _text(_get(validation, "status"), "validation_run.status")
    if status not in {"passed", "failed"}:
        raise DecisionProjectionError("validation_run.status is invalid")
    created_at = _timestamp(_get(validation, "created_at"), "validation_run.created_at", required=True)
    check_payloads = [
        _check_payload(check, f"validation_check[{index}]")
        for index, check in enumerate(sorted(
            list(checks),
            key=lambda row: _uuid_text(_get(row, "id"), "validation_check.id") if _get(row, "id") is not None else "",
        ))
    ]
    return {
        "schema": "bidops.deep-review-validation.v1",
        "validation_run_id": validation_id,
        "report_revision_id": revision_id,
        "status": status,
        "checks": check_payloads,
        "created_at": created_at.isoformat(),
    }


def validation_snapshot_sha256(validation: object, checks: Iterable[object]) -> str:
    return canonical_json_hash(validation_snapshot_payload(validation, checks))


def _revision_ref(revision: object) -> AgentArtifactRef:
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.report_revision,
        artifact_id=_uuid_text(_get(revision, "id"), "report_revision.id"),
        version=_positive_int(_get(revision, "sequence"), "report_revision.sequence"),
        sha256=_sha(_get(revision, "report_sha256"), "report_revision.report_sha256"),
    )


def report_revision_artifact_ref(revision: object) -> AgentArtifactRef:
    return _revision_ref(revision)


def _validation_ref(validation: object, checks: Iterable[object]) -> AgentArtifactRef:
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.validation_run,
        artifact_id=_uuid_text(_get(validation, "id"), "validation_run.id"),
        version=_positive_int(_get(validation, "sequence"), "validation_run.sequence"),
        sha256=validation_snapshot_sha256(validation, checks),
    )


def validation_artifact_ref(validation: object, checks: Iterable[object] = ()) -> AgentArtifactRef:
    return _validation_ref(validation, checks)


def _evidence_ref(evidence: object) -> AgentArtifactRef:
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.evidence,
        artifact_id=_uuid_text(_get(evidence, "id", _get(evidence, "evidence_id")), "evidence.id"),
        version=None,
        sha256=_sha(_get(evidence, "source_sha256"), "evidence.source_sha256"),
    )


def evidence_artifact_ref(evidence: object) -> AgentArtifactRef:
    return _evidence_ref(evidence)


def final_opinion_snapshot_payload(opinion: object) -> dict[str, Any]:
    opinion_id = _uuid_text(_get(opinion, "id"), "final_opinion.id")
    sequence = _positive_int(_get(opinion, "sequence"), "final_opinion.sequence")
    value = _text(_get(opinion, "value"), "final_opinion.value")
    reason = _text(_get(opinion, "reason"), "final_opinion.reason")
    validation_status = _text(
        _get(opinion, "validation_status_at_opinion"),
        "final_opinion.validation_status_at_opinion",
    )
    if validation_status not in {"passed", "failed"}:
        raise DecisionProjectionError("final_opinion.validation_status_at_opinion is invalid")
    acknowledged = _get(opinion, "acknowledged_validation_failure")
    if not isinstance(acknowledged, bool):
        raise DecisionProjectionError("final_opinion.acknowledged_validation_failure is invalid")
    claimed_name = _text(_get(opinion, "claimed_name"), "final_opinion.claimed_name")
    created_at = _timestamp(_get(opinion, "created_at"), "final_opinion.created_at", required=True)
    return {
        "id": opinion_id,
        "sequence": sequence,
        "value": value,
        "reason": reason,
        "validation_status_at_opinion": validation_status,
        "acknowledged_validation_failure": acknowledged,
        "claimed_name": claimed_name,
        "created_at": created_at.isoformat(),
    }


def final_opinion_snapshot_sha256(opinion: object) -> str:
    return canonical_json_hash(final_opinion_snapshot_payload(opinion))


def _opinion_ref(opinion: object) -> AgentArtifactRef:
    payload = final_opinion_snapshot_payload(opinion)
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.final_opinion,
        artifact_id=payload["id"],
        version=payload["sequence"],
        sha256=canonical_json_hash(payload),
    )


def final_opinion_artifact_ref(opinion: object) -> AgentArtifactRef:
    return _opinion_ref(opinion)


def _revision_evidence(
    parts: Mapping[str, Any],
    review_id: str,
    revision_id: str,
) -> list[object]:
    links = [
        row for row in _as_list(parts.get("revision_evidence"))
        if str(_get(row, "deep_review_id")) == review_id
        and str(_get(row, "report_revision_id")) == revision_id
    ]
    link_ids: list[str] = []
    for link in links:
        evidence_id = _uuid_text(_get(link, "evidence_ref_id"), "report_revision_evidence.evidence_ref_id")
        if evidence_id in link_ids:
            raise DecisionProjectionError("report revision evidence is duplicated")
        link_ids.append(evidence_id)
    evidence_by_id: dict[str, object] = {}
    for row in _as_list(parts.get("evidence")):
        evidence_id = _uuid_text(_get(row, "id", _get(row, "evidence_id")), "evidence.id")
        if str(_get(row, "deep_review_id")) != review_id:
            raise DecisionProjectionError("evidence is outside the deep review scope")
        if evidence_id in evidence_by_id:
            raise DecisionProjectionError("evidence is duplicated")
        evidence_by_id[evidence_id] = row
    result: list[object] = []
    for evidence_id in sorted(link_ids):
        if evidence_id not in evidence_by_id:
            raise DecisionProjectionError("report revision evidence is missing")
        result.append(evidence_by_id[evidence_id])
    return result


def _audit_for_revision(
    parts: Mapping[str, Any],
    review_id: str,
    revision: object,
    validation: object | None,
    lineage: UUID | None,
) -> object:
    origin = _get(revision, "origin")
    if origin == "machine":
        action = "deep_review.report.machine_materialized"
    elif origin == "human":
        action = "deep_review.report_revision.created"
    else:
        raise DecisionProjectionError("report_revision.origin is invalid")
    revision_id = _uuid_text(_get(revision, "id"), "report_revision.id")
    rows = [row for row in _as_list(parts.get("audits")) if _audit_matches(row, action, review_id)]
    matching = [
        row for row in rows
        if str(_metadata(row, action).get("revision_id")) == revision_id
    ]
    if len(matching) != 1:
        raise DecisionProjectionError("report revision audit is missing or duplicated")
    metadata = _metadata(matching[0], action)
    if validation is not None:
        validation_id = _uuid_text(_get(validation, "id"), "validation_run.id")
        if "validation_run_id" in metadata and str(metadata.get("validation_run_id")) != validation_id:
            raise DecisionProjectionError("report revision audit validation mismatch")
    if "report_sha256" in metadata and str(metadata.get("report_sha256")) != str(_get(revision, "report_sha256")):
        raise DecisionProjectionError("report revision audit hash mismatch")
    if _correlation(matching[0], action) != lineage:
        raise DecisionProjectionError("report revision correlation lineage does not match")
    _timestamp(_get(matching[0], "created_at"), f"{action}.created_at", required=True)
    return matching[0]


def _audit_for_opinion(
    parts: Mapping[str, Any],
    review_id: str,
    opinion: object,
    lineage: UUID | None,
) -> object:
    action = "deep_review.final_opinion.created"
    opinion_id = _uuid_text(_get(opinion, "id"), "final_opinion.id")
    rows = [row for row in _as_list(parts.get("audits")) if _audit_matches(row, action, review_id)]
    matching = [
        row for row in rows
        if str(_metadata(row, action).get("opinion_id")) == opinion_id
    ]
    if len(matching) != 1:
        raise DecisionProjectionError("final opinion audit is missing or duplicated")
    metadata = _metadata(matching[0], action)
    for key, field_name in (
        ("report_revision_id", "report_revision_id"),
        ("validation_run_id", "validation_run_id"),
    ):
        if key in metadata and str(metadata.get(key)) != str(_get(opinion, field_name)):
            raise DecisionProjectionError("final opinion audit scope mismatch")
    if "validation_status" in metadata and str(metadata.get("validation_status")) != str(_get(opinion, "validation_status_at_opinion")):
        raise DecisionProjectionError("final opinion audit validation mismatch")
    if _correlation(matching[0], action) != lineage:
        raise DecisionProjectionError("final opinion correlation lineage does not match")
    _timestamp(_get(matching[0], "created_at"), f"{action}.created_at", required=True)
    return matching[0]


def _validate_audit_extras(parts: Mapping[str, Any], review_id: str, revisions: list[object], opinions: list[object]) -> None:
    revision_actions = {
        _uuid_text(_get(row, "id"), "report_revision.id"): (
            "deep_review.report.machine_materialized"
            if _get(row, "origin") == "machine"
            else "deep_review.report_revision.created"
        )
        for row in revisions
    }
    revision_ids = set(revision_actions)
    opinion_ids = {_uuid_text(_get(row, "id"), "final_opinion.id") for row in opinions}
    revision_audits = [
        row for row in _as_list(parts.get("audits"))
        if _audit_matches(row, "deep_review.report.machine_materialized", review_id)
        or _audit_matches(row, "deep_review.report_revision.created", review_id)
    ]
    seen_revision_audits: set[tuple[str, str]] = set()
    for row in revision_audits:
        action = str(_get(row, "action"))
        revision_id = str(_metadata(row, action).get("revision_id"))
        if revision_id not in revision_ids:
            raise DecisionProjectionError("report revision audit points outside history")
        if revision_actions[revision_id] != action:
            raise DecisionProjectionError("report revision audit origin mismatch")
        identity = (action, revision_id)
        if identity in seen_revision_audits:
            raise DecisionProjectionError("report revision audit is duplicated")
        seen_revision_audits.add(identity)
    opinion_audits = [
        row for row in _as_list(parts.get("audits"))
        if _audit_matches(row, "deep_review.final_opinion.created", review_id)
    ]
    seen_opinion_audits: set[str] = set()
    for row in opinion_audits:
        opinion_id = str(_metadata(row, "deep_review.final_opinion.created").get("opinion_id"))
        if opinion_id not in opinion_ids:
            raise DecisionProjectionError("final opinion audit points outside history")
        if opinion_id in seen_opinion_audits:
            raise DecisionProjectionError("final opinion audit is duplicated")
        seen_opinion_audits.add(opinion_id)


def _safe_error_view(
    review_id: str,
    created_at: datetime,
    parts: Mapping[str, Any],
    correlation_id: UUID | None,
) -> AgentRunView:
    timestamps: list[datetime] = [created_at]
    for collection, field_name in (
        (parts.get("audits"), "audit.created_at"),
        (parts.get("revisions"), "report_revision.created_at"),
        (parts.get("validations"), "validation_run.created_at"),
        (parts.get("opinions"), "final_opinion.created_at"),
    ):
        for row in _as_list(collection):
            value = _get(row, "created_at")
            if isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None:
                timestamps.append(value)
    updated_at = latest_timestamp(timestamps) or created_at
    steps = [
        AgentStepView(step_name=name, sequence=index, status=AgentStepStatus.failed if index == 1 else AgentStepStatus.queued)
        for index, name in enumerate(STEP_NAMES, start=1)
    ]
    return AgentRunView(
        schema="bidops.agent-run.v1",
        agent_name=AgentName.decision,
        run_id=decision_run_id(review_id),
        aggregate=AgentAggregateRef(aggregate_type=AgentAggregateType.deep_review, aggregate_id=review_id),
        execution_ref=None,
        status=AgentRunStatus.failed,
        outcome_code=None,
        current_step=None,
        steps=steps,
        input_refs=[],
        output_refs=[],
        wait=None,
        error=make_safe_error(AgentErrorCode.processing_failed),
        available_actions=[],
        correlation_id=correlation_id,
        created_at=created_at,
        started_at=None,
        updated_at=updated_at,
        completed_at=None,
    )


def _project_valid(parts: Mapping[str, Any], review_id: str, lineage: UUID | None, created_at: datetime) -> AgentRunView:
    revisions = _ordered_rows(parts.get("revisions", ()), "report_revision", review_id)
    validations = _ordered_rows(parts.get("validations", ()), "validation_run", review_id)
    opinions = _ordered_rows(parts.get("opinions", ()), "final_opinion", review_id)
    _validate_audit_extras(parts, review_id, revisions, opinions)

    if revisions:
        latest_revision_id = _uuid_text(_get(revisions[-1], "id"), "latest report_revision.id")
        latest_validation_rows = [
            row for row in validations
            if str(_get(row, "report_revision_id")) == latest_revision_id
        ]
        if len(latest_validation_rows) == 0:
            for revision in revisions:
                _revision_ref(revision)
                _timestamp(_get(revision, "created_at"), "report_revision.created_at", required=True)
                _audit_for_revision(parts, review_id, revision, None, lineage)
            return _run_view(
                review_id=review_id,
                status=AgentRunStatus.blocked,
                outcome=None,
                current_step=STEP_NAMES[0],
                steps_status=(AgentStepStatus.blocked, AgentStepStatus.queued, AgentStepStatus.queued),
                input_refs=[],
                output_refs=[],
                wait=make_wait("machine_report_required"),
                available_actions=[],
                lineage=lineage,
                created_at=created_at,
                updated_at=_updated_timestamp(parts, created_at),
                completed_at=None,
                started_at=created_at,
                step_timestamps=((created_at, None), (None, None), (None, None)),
            )
        if len(latest_validation_rows) > 1:
            raise DecisionProjectionError("latest report revision validation is duplicated")

    validation_by_id = {
        _uuid_text(_get(row, "id"), "validation_run.id"): row
        for row in validations
    }
    checks_by_validation: dict[str, list[object]] = {key: [] for key in validation_by_id}
    seen_check_ids: set[str] = set()
    for check in _as_list(parts.get("validation_checks")):
        validation_id = _uuid_text(_get(check, "validation_run_id"), "validation_check.validation_run_id")
        if validation_id not in checks_by_validation:
            raise DecisionProjectionError("validation check is outside validation history")
        if _get(check, "id") is not None:
            check_id = _uuid_text(_get(check, "id"), "validation_check.id")
            if check_id in seen_check_ids:
                raise DecisionProjectionError("validation check is duplicated")
            seen_check_ids.add(check_id)
        checks_by_validation[validation_id].append(check)

    revision_by_id: dict[str, object] = {}
    validation_by_revision: dict[str, object] = {}
    revision_refs: dict[str, AgentArtifactRef] = {}
    validation_refs: dict[str, AgentArtifactRef] = {}
    for revision_index, revision in enumerate(revisions):
        revision_id = _uuid_text(_get(revision, "id"), "report_revision.id")
        if revision_id in revision_by_id:
            raise DecisionProjectionError("report revision is duplicated")
        revision_by_id[revision_id] = revision
        matching = [
            row for row in validations
            if str(_get(row, "report_revision_id")) == revision_id
        ]
        if len(matching) != 1:
            raise DecisionProjectionError("report revision validation is missing or duplicated")
        validation = matching[0]
        validation_id = _uuid_text(_get(validation, "id"), "validation_run.id")
        if validation_id in validation_refs:
            raise DecisionProjectionError("validation run is duplicated")
        if _get(revision, "origin") not in {"machine", "human"}:
            raise DecisionProjectionError("report_revision.origin is invalid")
        if revision_index == 0 and _get(revision, "origin") != "machine":
            raise DecisionProjectionError("report history must begin with a machine revision")
        if revision_index > 0 and _get(revision, "origin") == "machine":
            raise DecisionProjectionError("machine report revision must be the first revision")
        if _get(revision, "origin") == "machine" and _get(revision, "parent_revision_id") is not None:
            raise DecisionProjectionError("machine report revision must not have a parent")
        if _get(revision, "origin") == "human":
            if _get(revision, "parent_revision_id") is None:
                raise DecisionProjectionError("human report revision parent is missing")
            parent_id = _uuid_text(_get(revision, "parent_revision_id"), "report_revision.parent_revision_id")
            expected_parent_id = _uuid_text(_get(revisions[revision_index - 1], "id"), "report_revision.parent_revision_id")
            if parent_id != expected_parent_id or parent_id not in revision_by_id:
                raise DecisionProjectionError("human report revision parent is not the previous revision")
        _timestamp(_get(revision, "created_at"), "report_revision.created_at", required=True)
        revision_refs[revision_id] = _revision_ref(revision)
        validation_refs[revision_id] = _validation_ref(validation, checks_by_validation[validation_id])
        validation_by_revision[revision_id] = validation
        _audit_for_revision(parts, review_id, revision, validation, lineage)

    for validation in validations:
        revision_id = _uuid_text(_get(validation, "report_revision_id"), "validation_run.report_revision_id")
        if revision_id not in revision_by_id:
            raise DecisionProjectionError("validation run points outside report history")

    opinion_by_id: dict[str, object] = {}
    for opinion in opinions:
        opinion_id = _uuid_text(_get(opinion, "id"), "final_opinion.id")
        if opinion_id in opinion_by_id:
            raise DecisionProjectionError("final opinion is duplicated")
        opinion_by_id[opinion_id] = opinion
        revision_id = _uuid_text(_get(opinion, "report_revision_id"), "final_opinion.report_revision_id")
        validation_id = _uuid_text(_get(opinion, "validation_run_id"), "final_opinion.validation_run_id")
        validation = validation_by_id.get(validation_id)
        if revision_id not in revision_by_id or validation is None:
            raise DecisionProjectionError("final opinion points outside report history")
        if str(_get(validation, "report_revision_id")) != revision_id:
            raise DecisionProjectionError("final opinion revision and validation mismatch")
        if str(_get(opinion, "validation_status_at_opinion")) != str(_get(validation, "status")):
            raise DecisionProjectionError("final opinion validation status mismatch")
        status = str(_get(validation, "status"))
        acknowledged = _get(opinion, "acknowledged_validation_failure")
        reason = _get(opinion, "reason")
        if status == "failed" and (acknowledged is not True or not isinstance(reason, str) or not reason.strip()):
            raise DecisionProjectionError("failed validation opinion acknowledgement is invalid")
        if status == "passed" and acknowledged is not False:
            raise DecisionProjectionError("passed validation opinion acknowledgement is invalid")
        final_opinion_snapshot_payload(opinion)
        _audit_for_opinion(parts, review_id, opinion, lineage)

    if not revisions:
        if validations or opinions or _as_list(parts.get("revision_evidence")):
            raise DecisionProjectionError("decision artifacts exist without a report revision")
        return _run_view(
            review_id=review_id,
            status=AgentRunStatus.blocked,
            outcome=None,
            current_step=STEP_NAMES[0],
            steps_status=(AgentStepStatus.blocked, AgentStepStatus.queued, AgentStepStatus.queued),
            input_refs=[],
            output_refs=[],
            wait=make_wait("machine_report_required"),
            available_actions=[],
            lineage=lineage,
            created_at=created_at,
            updated_at=_updated_timestamp(parts, created_at),
            completed_at=None,
            started_at=created_at,
            step_timestamps=(
                (created_at, None),
                (None, None),
                (None, None),
            ),
        )

    latest_revision = revisions[-1]
    latest_revision_id = _uuid_text(_get(latest_revision, "id"), "latest report_revision.id")
    latest_validation = validation_by_revision[latest_revision_id]
    latest_validation_id = _uuid_text(_get(latest_validation, "id"), "latest validation_run.id")
    evidence_rows = _revision_evidence(parts, review_id, latest_revision_id)
    input_refs = [revision_refs[latest_revision_id], validation_refs[latest_revision_id], *[_evidence_ref(row) for row in evidence_rows]]

    matching_opinions = [
        row for row in opinions
        if str(_get(row, "report_revision_id")) == latest_revision_id
        and str(_get(row, "validation_run_id")) == latest_validation_id
    ]
    final_opinion = matching_opinions[-1] if matching_opinions else None
    if final_opinion is not None:
        status = AgentRunStatus.completed
        outcome = AgentOutcomeCode.final_opinion_recorded
        current_step = None
        steps_status = (AgentStepStatus.completed,) * 3
        wait: AgentWait | None = None
        available_actions = [AgentAction.create_full_revision]
        output_refs = (
            [revision_refs[latest_revision_id], validation_refs[latest_revision_id]]
            if _get(latest_revision, "origin") == "human"
            else []
        )
        output_refs.append(_opinion_ref(final_opinion))
        completed_at = _timestamp(_get(final_opinion, "created_at"), "final_opinion.created_at", required=True)
        step_timestamps = (
            (_timestamp(_get(latest_revision, "created_at"), "report_revision.created_at", required=True), _timestamp(_get(latest_validation, "created_at"), "validation_run.created_at", required=True)),
            (_timestamp(_get(latest_revision, "created_at"), "report_revision.created_at", required=True), _timestamp(_get(latest_validation, "created_at"), "validation_run.created_at", required=True)),
            (_timestamp(_get(latest_validation, "created_at"), "validation_run.created_at", required=True), completed_at),
        )
    elif _get(latest_revision, "origin") == "human":
        status = AgentRunStatus.waiting_human
        outcome = None
        current_step = STEP_NAMES[2]
        steps_status = (AgentStepStatus.completed, AgentStepStatus.completed, AgentStepStatus.waiting_human)
        wait = make_wait("final_opinion_required")
        available_actions = [AgentAction.record_final_opinion]
        output_refs = [revision_refs[latest_revision_id], validation_refs[latest_revision_id]]
        completed_at = None
        revision_created = _timestamp(_get(latest_revision, "created_at"), "report_revision.created_at", required=True)
        validation_created = _timestamp(_get(latest_validation, "created_at"), "validation_run.created_at", required=True)
        step_timestamps = ((created_at, validation_created), (revision_created, validation_created), (validation_created, None))
    else:
        status = AgentRunStatus.waiting_human
        outcome = None
        current_step = STEP_NAMES[1]
        steps_status = (AgentStepStatus.completed, AgentStepStatus.waiting_human, AgentStepStatus.queued)
        wait = make_wait("report_review_required")
        available_actions = [AgentAction.create_full_revision, AgentAction.record_final_opinion]
        output_refs = []
        completed_at = None
        revision_created = _timestamp(_get(latest_revision, "created_at"), "report_revision.created_at", required=True)
        validation_created = _timestamp(_get(latest_validation, "created_at"), "validation_run.created_at", required=True)
        step_timestamps = ((created_at, validation_created), (revision_created, None), (None, None))

    return _run_view(
        review_id=review_id,
        status=status,
        outcome=outcome,
        current_step=current_step,
        steps_status=steps_status,
        input_refs=input_refs,
        output_refs=output_refs,
        wait=wait,
        available_actions=available_actions,
        lineage=lineage,
        created_at=created_at,
        updated_at=_updated_timestamp(parts, created_at),
        completed_at=completed_at,
        started_at=created_at,
        step_timestamps=step_timestamps,
    )


def _updated_timestamp(parts: Mapping[str, Any], created_at: datetime) -> datetime:
    values: list[datetime | None] = [created_at]
    for collection in (
        parts.get("audits"),
        parts.get("revisions"),
        parts.get("validations"),
        parts.get("opinions"),
    ):
        values.extend(_get(row, "created_at") for row in _as_list(collection))
    return latest_timestamp(values) or created_at


def _run_view(
    *,
    review_id: str,
    status: AgentRunStatus,
    outcome: AgentOutcomeCode | None,
    current_step: str | None,
    steps_status: tuple[AgentStepStatus, AgentStepStatus, AgentStepStatus],
    input_refs: list[AgentArtifactRef],
    output_refs: list[AgentArtifactRef],
    wait: AgentWait | None,
    available_actions: list[AgentAction],
    lineage: UUID | None,
    created_at: datetime,
    updated_at: datetime,
    completed_at: datetime | None,
    started_at: datetime | None,
    step_timestamps: tuple[tuple[datetime | None, datetime | None], ...],
) -> AgentRunView:
    steps = [
        AgentStepView(
            step_name=name,
            sequence=index,
            status=steps_status[index - 1],
            started_at=step_timestamps[index - 1][0] if index - 1 < len(step_timestamps) else None,
            completed_at=step_timestamps[index - 1][1] if index - 1 < len(step_timestamps) else None,
        )
        for index, name in enumerate(STEP_NAMES, start=1)
    ]
    return AgentRunView(
        schema="bidops.agent-run.v1",
        agent_name=AgentName.decision,
        run_id=decision_run_id(review_id),
        aggregate=AgentAggregateRef(aggregate_type=AgentAggregateType.deep_review, aggregate_id=review_id),
        execution_ref=None,
        status=status,
        outcome_code=outcome,
        current_step=current_step,
        steps=steps,
        input_refs=input_refs,
        output_refs=output_refs,
        wait=wait,
        error=None,
        available_actions=available_actions,
        correlation_id=lineage,
        created_at=created_at,
        started_at=started_at,
        updated_at=updated_at,
        completed_at=completed_at,
    )


def project_decision(
    snapshot: Mapping[str, Any] | object,
    revisions: Iterable[object] | None = None,
    validations: Iterable[object] | None = None,
    validation_checks: Iterable[object] | None = None,
    revision_evidence: Iterable[object] | None = None,
    evidence: Iterable[object] | None = None,
    opinions: Iterable[object] | None = None,
    audits: Iterable[object] | None = None,
    *,
    checks: Iterable[object] | None = None,
    report_revision_evidence: Iterable[object] | None = None,
    final_opinions: Iterable[object] | None = None,
) -> AgentRunView:
    """Project a complete persisted decision snapshot without side effects."""

    parts = _snapshot_parts(
        snapshot,
        revisions,
        validations,
        validation_checks,
        revision_evidence,
        evidence,
        opinions,
        audits,
        checks=checks,
        report_revision_evidence=report_revision_evidence,
        final_opinions=final_opinions,
    )
    review = parts.get("review")
    if review is None:
        raise DecisionProjectionError("deep review snapshot is missing")
    review_id = _uuid_text(_get(review, "id"), "deep_review.id")
    try:
        _create_audit, lineage, created_at = _lineage(parts, review_id)
        return _project_valid(parts, review_id, lineage, created_at)
    except (DecisionProjectionError, ValueError, TypeError, KeyError):
        try:
            created_at, lineage = _failure_context(parts, review_id)
        except (DecisionProjectionError, ValueError, TypeError, KeyError):
            # A completely absent/invalid root audit has no persisted decision
            # timestamp from which a valid AgentRunView can be built.  Raise
            # rather than using the review row or a runtime clock.
            raise
        return _safe_error_view(review_id, created_at, parts, lineage)


project_decision_run = project_decision
project_run = project_decision
project = project_decision
build_decision_run = project_decision


__all__ = [
    "DecisionProjectionError",
    "STEP_NAMES",
    "build_decision_run",
    "canonical_json_hash",
    "evidence_artifact_ref",
    "final_opinion_artifact_ref",
    "final_opinion_snapshot_payload",
    "final_opinion_snapshot_sha256",
    "project",
    "project_decision",
    "project_decision_run",
    "project_run",
    "report_revision_artifact_ref",
    "validation_artifact_ref",
    "validation_snapshot_payload",
    "validation_snapshot_sha256",
]
