"""Deterministic projection for a persisted document bundle.

This module intentionally knows nothing about SQLAlchemy, object storage, or
the service that owns document transitions.  The adapter supplies a frozen
read snapshot and this module turns that snapshot into the common agent view.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
import hashlib
import json
import re
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
    AgentWait,
    AgentWaitReason,
    latest_timestamp,
    make_safe_error,
    make_wait,
    document_preparation_run_id,
)


STEP_NAMES: tuple[str, ...] = (
    "register_documents",
    "scan_and_structure",
    "review_metadata_and_issues",
    "confirm_ready",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE_ISSUES = frozenset(
    {
        "unsafe_document",
        "quarantine_document",
        "malware_detected",
        "mime_mismatch",
        "malformed_pdf",
        "malformed_archive",
        "archive_size_limit",
        "archive_ratio_limit",
        "archive_member_limit",
    }
)
_STRUCTURE_ISSUES = frozenset({"structure_unavailable", "structure_failed"})


def _get(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _text(value: object) -> str:
    return str(value)


def _sha(value: object) -> str | None:
    candidate = None if value is None else str(value)
    return candidate if candidate is not None and _SHA256.fullmatch(candidate) else None


def _safe_identifier(value: object, field_name: str) -> str:
    candidate = _text(value)
    if not candidate.strip():
        raise ValueError(f"{field_name} must be nonblank")
    return candidate


def _ordered_items(items: Iterable[object]) -> list[object]:
    materialized = list(items)

    def key(item: object) -> tuple[int, int, str, str]:
        ordinal = _get(item, "ordinal")
        document_id = _text(
            _get(item, "document_version_id", _get(item, "id", ""))
        )
        created_at = _get(item, "created_at")
        # An explicit ordinal is authoritative.  Missing ordinals use the
        # persisted creation time and ID, never a runtime sequence.
        if isinstance(ordinal, int) and not isinstance(ordinal, bool):
            return (0, ordinal, "", document_id)
        created_key = created_at.isoformat() if isinstance(created_at, datetime) else ""
        return (1, 0, created_key, document_id)

    return sorted(materialized, key=key)


def _structure_for(structures: object, document_id: object) -> object | None:
    if structures is None:
        return None
    key = _text(document_id)
    if isinstance(structures, Mapping):
        return structures.get(key) or structures.get(document_id)  # type: ignore[index]
    for structure in structures:  # type: ignore[union-attr]
        if _text(_get(structure, "document_version_id", "")) == key:
            return structure
    return None


def _document_id(document: object) -> str:
    return _safe_identifier(
        _get(document, "document_version_id", _get(document, "id")),
        "document_version_id",
    )


def _document_version(document: object) -> int | None:
    value = _get(document, "document_version_version", _get(document, "version"))
    if value is None:
        return None
    return int(value)


def _document_ref(document: object) -> AgentArtifactRef:
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.document_version,
        artifact_id=_document_id(document),
        version=_document_version(document),
        sha256=_sha(
            _get(
                document,
                "content_sha256",
                _get(document, "sha256", _get(document, "content_hash")),
            )
        ),
    )


def _item_document(item: object) -> dict[str, object]:
    """Expose only safe document-ref fields from a confirmation item."""

    return {
        "document_version_id": _get(item, "document_version_id"),
        "document_version_version": _get(item, "document_version_version"),
        "content_sha256": _get(item, "content_sha256"),
        "safety_status": _get(item, "safety_status_at_confirmation"),
        "structure_status": "ready" if _get(item, "structure_id_at_confirmation") and _get(item, "structure_payload_sha256") else "failed",
        "ordinal": _get(item, "ordinal"),
        "created_at": _get(item, "created_at"),
    }


def _issue_code(issue: object) -> str:
    return str(_get(issue, "code", ""))


def _is_blocking(issue: object) -> bool:
    return bool(_get(issue, "blocking", False))


def _document_status(document: object, structure: object | None) -> tuple[str | None, str | None]:
    safety = _get(document, "safety_status")
    structure_status = _get(document, "structure_status")
    if structure is not None:
        structure_status = _get(structure, "validation_status", structure_status)
    return (None if safety is None else str(safety), None if structure_status is None else str(structure_status))


def _error_code(
    documents: Sequence[object],
    structures: object,
    issues: Sequence[object],
    bundle_status: str,
) -> AgentErrorCode | None:
    """Choose a safe terminal error without copying domain text."""

    if bundle_status == "quarantined":
        return AgentErrorCode.unsafe_document
    for document in documents:
        structure = _structure_for(structures, _document_id(document))
        safety, structure_status = _document_status(document, structure)
        if safety == "blocked":
            return AgentErrorCode.unsafe_document
        if structure_status == "failed":
            return AgentErrorCode.structure_unavailable
    for issue in issues:
        code = _issue_code(issue)
        if code in _UNSAFE_ISSUES:
            return AgentErrorCode.unsafe_document
        if code in _STRUCTURE_ISSUES and all(
            _document_status(document, _structure_for(structures, _document_id(document)))[1]
            not in {"pending", "processing"}
            for document in documents
        ):
            return AgentErrorCode.structure_unavailable
    if bundle_status == "failed":
        # A failed bundle may have a safe worker code in its issue list, but
        # never expose that internal code as a public error.
        return AgentErrorCode.processing_failed
    return None


def _has_running_document(documents: Sequence[object], structures: object) -> bool:
    for document in documents:
        safety, structure_status = _document_status(
            document, _structure_for(structures, _document_id(document))
        )
        if safety in {"scanning", "quarantined"}:
            return True
        if structure_status in {"pending", "processing"}:
            return True
    return False


def _metadata_can_confirm(
    documents: Sequence[object], structures: object, issues: Sequence[object]
) -> bool:
    if not documents or any(_is_blocking(issue) for issue in issues):
        return False
    for document in documents:
        safety, structure_status = _document_status(
            document, _structure_for(structures, _document_id(document))
        )
        if safety != "safe" or structure_status != "ready":
            return False
        if bool(_get(document, "needs_human_review", False)):
            return False
    return True


def _input_refs(
    documents: Sequence[object],
    items: Sequence[object],
    bundle_status: str,
) -> list[AgentArtifactRef]:
    sources: list[object]
    if bundle_status in {"ready", "superseded"} and items:
        sources = [_item_document(item) for item in _ordered_items(items)]
    else:
        item_ordinals = {
            _text(_get(item, "document_version_id")): _get(item, "ordinal")
            for item in items
            if _get(item, "document_version_id") is not None
        }

        def document_key(document: object) -> tuple[int, int, str, str]:
            ordinal = item_ordinals.get(_document_id(document))
            if isinstance(ordinal, int) and not isinstance(ordinal, bool):
                return (0, ordinal, "", _document_id(document))
            created_at = _get(document, "created_at")
            created_key = created_at.isoformat() if isinstance(created_at, datetime) else ""
            return (1, 0, created_key, _document_id(document))

        sources = sorted(
            list(documents),
            key=document_key,
        )
    return [_document_ref(document) for document in sources]


def _output_refs(bundle: object, items: Sequence[object], bundle_status: str) -> list[AgentArtifactRef]:
    if bundle_status not in {"ready", "superseded"}:
        return []
    refs: list[AgentArtifactRef] = []
    for item in _ordered_items(items):
        structure_id = _get(item, "structure_id_at_confirmation")
        if structure_id is None:
            continue
        refs.append(
            AgentArtifactRef(
                artifact_type=AgentArtifactType.document_structure,
                artifact_id=_safe_identifier(structure_id, "structure_id"),
                version=None,
                sha256=_sha(_get(item, "structure_payload_sha256")),
            )
        )
    refs.append(
        AgentArtifactRef(
            artifact_type=AgentArtifactType.document_bundle,
            artifact_id=_safe_identifier(_get(bundle, "id"), "bundle_id"),
            version=int(_get(bundle, "version")),
            sha256=_sha(_get(bundle, "sha256")),
        )
    )
    return refs


def _step(
    name: str,
    sequence: int,
    status: AgentStepStatus,
    *,
    error_code: AgentErrorCode | None = None,
    completed_at: datetime | None = None,
) -> AgentStepView:
    return AgentStepView(
        step_name=name,
        sequence=sequence,
        status=status,
        started_at=None,
        completed_at=completed_at,
        last_error_code=error_code,
    )


def _steps(
    *,
    run_status: AgentRunStatus,
    current_step: str | None,
    error_code: AgentErrorCode | None,
    has_documents: bool,
    can_confirm: bool,
    scan_complete: bool,
    has_blocking_issues: bool,
    needs_human_review: bool,
    completed_at: datetime | None,
) -> list[AgentStepView]:
    if run_status in {AgentRunStatus.completed, AgentRunStatus.superseded}:
        return [_step(name, index, AgentStepStatus.completed, completed_at=completed_at) for index, name in enumerate(STEP_NAMES, 1)]
    if run_status is AgentRunStatus.failed:
        failure_index = {"register_documents": 1, "scan_and_structure": 2, "review_metadata_and_issues": 3}.get(current_step or "", 2)
        return [
            _step(
                name,
                index,
                AgentStepStatus.failed if index == failure_index else (AgentStepStatus.completed if index < failure_index else AgentStepStatus.blocked),
                error_code=error_code if index == failure_index else None,
            )
            for index, name in enumerate(STEP_NAMES, 1)
        ]
    if run_status is AgentRunStatus.running:
        return [
            _step(STEP_NAMES[0], 1, AgentStepStatus.completed if has_documents else AgentStepStatus.blocked),
            _step(STEP_NAMES[1], 2, AgentStepStatus.running),
            _step(STEP_NAMES[2], 3, AgentStepStatus.blocked),
            _step(STEP_NAMES[3], 4, AgentStepStatus.blocked),
        ]
    if run_status is AgentRunStatus.waiting_human:
        return [
            _step(STEP_NAMES[0], 1, AgentStepStatus.completed if has_documents else AgentStepStatus.waiting_human),
            _step(STEP_NAMES[1], 2, AgentStepStatus.completed if scan_complete else AgentStepStatus.blocked),
            _step(
                STEP_NAMES[2],
                3,
                AgentStepStatus.completed
                if can_confirm
                else AgentStepStatus.waiting_human
                if scan_complete and (has_blocking_issues or needs_human_review)
                else AgentStepStatus.blocked,
            ),
            _step(STEP_NAMES[3], 4, AgentStepStatus.waiting_human if can_confirm else AgentStepStatus.blocked),
        ]
    return [
        _step(STEP_NAMES[0], 1, AgentStepStatus.blocked),
        _step(STEP_NAMES[1], 2, AgentStepStatus.blocked),
        _step(STEP_NAMES[2], 3, AgentStepStatus.blocked),
        _step(STEP_NAMES[3], 4, AgentStepStatus.blocked),
    ]


def _effective_grade_ref(
    *,
    notice_id: object,
    effective_grade_at_start: str | None,
    effective_grade_snapshot_id: str | None,
) -> AgentArtifactRef | None:
    if effective_grade_at_start is None:
        return None
    if effective_grade_snapshot_id is None:
        raise ValueError("effective grade snapshot requires its creation audit ID")
    encoded = json.dumps(
        {"notice_id": notice_id, "effective_grade_at_start": effective_grade_at_start},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.effective_grade_snapshot,
        artifact_id=_safe_identifier(effective_grade_snapshot_id, "effective_grade_snapshot_id"),
        version=None,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )


def project_document_preparation(
    bundle: object,
    documents: Iterable[object] | None = None,
    structures: object = None,
    issues: Iterable[object] | None = None,
    *,
    bundle_items: Iterable[object] | None = None,
    creation_audit_id: str | None = None,
    effective_grade_at_start: str | None = None,
    effective_grade_snapshot_id: str | None = None,
    bundle_sha256: str | None = None,
    correlation_id: UUID | None = None,
    persisted_timestamps: Iterable[datetime | None] = (),
    timestamps: Iterable[datetime | None] | None = None,
) -> AgentRunView:
    """Project one bundle snapshot into the common ``AgentRunView``.

    ``documents``, ``structures``, ``issues``, and ``bundle_items`` are read
    inputs only.  No default timestamp, UUID, audit row, or mutation is
    created here.
    """

    bundle_id = _safe_identifier(_get(bundle, "id"), "bundle_id")
    notice_id = _get(bundle, "notice_id")
    bundle_status = str(_get(bundle, "status"))
    created_at = _get(bundle, "created_at")
    if not isinstance(created_at, datetime):
        raise ValueError("bundle.created_at must be persisted")
    confirmed_at = _get(bundle, "confirmed_at")
    if confirmed_at is not None and not isinstance(confirmed_at, datetime):
        raise ValueError("bundle.confirmed_at must be persisted")

    item_list = list(bundle_items or ())
    document_list = list(documents if documents is not None else (_get(bundle, "documents", ()) or ()))
    issue_list = list(issues if issues is not None else (_get(bundle, "issues", ()) or ()))

    # Confirmed bundles are projected from their immutable item rows.  The
    # service normally supplies the matching view documents as well, but the
    # item rows are the authoritative source for historical runs.
    if bundle_status in {"ready", "superseded"} and item_list:
        input_documents = [_item_document(item) for item in _ordered_items(item_list)]
    else:
        input_documents = document_list

    error_code = _error_code(input_documents, structures, issue_list, bundle_status)
    can_confirm = _metadata_can_confirm(input_documents, structures, issue_list)
    running = _has_running_document(input_documents, structures)
    has_documents = bool(input_documents)
    has_blocking_issues = any(_is_blocking(issue) for issue in issue_list)
    needs_human_review = any(bool(_get(document, "needs_human_review", False)) for document in input_documents)
    scan_complete = has_documents and not running and error_code is None and all(
        _document_status(document, _structure_for(structures, _document_id(document))) == ("safe", "ready")
        for document in input_documents
    )

    if bundle_status == "ready":
        run_status = AgentRunStatus.completed
        outcome = AgentOutcomeCode.ready_bundle
        current_step = None
        wait: AgentWait | None = None
        error: AgentSafeError | None = None
    elif bundle_status == "superseded":
        run_status = AgentRunStatus.superseded
        outcome = AgentOutcomeCode.superseded_by_new_bundle
        current_step = None
        wait = None
        error = None
    elif error_code is not None:
        run_status = AgentRunStatus.failed
        outcome = None
        current_step = "scan_and_structure" if error_code in {
            AgentErrorCode.unsafe_document,
            AgentErrorCode.structure_unavailable,
        } else "review_metadata_and_issues"
        wait = None
        error = make_safe_error(error_code)
    elif running or bundle_status == "processing":
        run_status = AgentRunStatus.running
        outcome = None
        current_step = "scan_and_structure"
        wait = None
        error = None
    elif not has_documents:
        run_status = AgentRunStatus.waiting_human
        outcome = None
        current_step = "register_documents"
        wait = make_wait(AgentWaitReason.document_registration_required)
        error = None
    elif has_blocking_issues or needs_human_review:
        run_status = AgentRunStatus.waiting_human
        outcome = None
        current_step = "review_metadata_and_issues"
        wait = make_wait(AgentWaitReason.document_blocking_issues_resolution_required)
        error = None
    elif can_confirm:
        run_status = AgentRunStatus.waiting_human
        outcome = None
        current_step = "confirm_ready"
        wait = make_wait(AgentWaitReason.document_metadata_confirmation_required)
        error = None
    else:
        run_status = AgentRunStatus.blocked
        outcome = None
        current_step = "register_documents"
        wait = None
        error = None

    grade_ref = _effective_grade_ref(
        notice_id=notice_id,
        effective_grade_at_start=effective_grade_at_start,
        effective_grade_snapshot_id=effective_grade_snapshot_id or creation_audit_id,
    )
    input_refs = ([] if grade_ref is None else [grade_ref]) + _input_refs(
        input_documents,
        item_list,
        bundle_status,
    )
    bundle_for_refs = {"id": bundle_id, "version": _get(bundle, "version"), "sha256": bundle_sha256}
    output_refs = _output_refs(bundle_for_refs, item_list, bundle_status)

    saved_times = [created_at, confirmed_at, *persisted_timestamps]
    if timestamps is not None:
        saved_times.extend(timestamps)
    updated_at = latest_timestamp(saved_times)
    if updated_at is None:  # created_at was already checked, retained for type narrowing
        updated_at = created_at

    step_views = _steps(
        run_status=run_status,
        current_step=current_step,
        error_code=error_code,
        has_documents=has_documents,
        can_confirm=can_confirm,
        scan_complete=scan_complete,
        has_blocking_issues=has_blocking_issues,
        needs_human_review=needs_human_review,
        completed_at=confirmed_at if run_status in {AgentRunStatus.completed, AgentRunStatus.superseded} else None,
    )
    return AgentRunView(
        schema="bidops.agent-run.v1",
        agent_name=AgentName.document_preparation,
        run_id=document_preparation_run_id(bundle_id),
        aggregate=AgentAggregateRef(
            aggregate_type=AgentAggregateType.document_bundle,
            aggregate_id=bundle_id,
        ),
        execution_ref=None,
        status=run_status,
        outcome_code=outcome,
        current_step=current_step,
        steps=step_views,
        input_refs=input_refs,
        output_refs=output_refs,
        wait=wait,
        error=error,
        available_actions=(
            []
            if run_status in {AgentRunStatus.completed, AgentRunStatus.failed, AgentRunStatus.superseded}
            else [
                AgentAction.register_document,
                *([AgentAction.update_document_metadata] if has_documents else []),
                *([AgentAction.confirm_ready] if can_confirm else []),
            ]
        ),
        correlation_id=correlation_id,
        created_at=created_at,
        started_at=min(
            (
                value
                for document in input_documents
                if isinstance((value := _get(document, "created_at")), datetime)
            ),
            default=None,
        ),
        updated_at=updated_at,
        completed_at=(
            confirmed_at
            if run_status in {AgentRunStatus.completed, AgentRunStatus.superseded}
            else updated_at
            if run_status is AgentRunStatus.failed
            else None
        ),
    )


project_bundle = project_document_preparation
project_run = project_document_preparation
build_document_preparation_run = project_document_preparation
project = project_document_preparation


__all__ = [
    "STEP_NAMES",
    "build_document_preparation_run",
    "project",
    "project_bundle",
    "project_document_preparation",
    "project_run",
]
