"""Small operator boundary for the opt-in prespec v4 cohort.

The PDF preparation tables deliberately contain no activation state.  This
module stores that state as append-only :class:`AuditEvent` metadata and keeps
the preparation worker separate from attachment download and model analysis.
It is intentionally a narrow service seam, rather than a generic scheduler or
registry.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import isolated_test_boundary_active
from ...core.model_client import (
    ModelEndpointError,
    ModelIdentityError,
    resolve_model_endpoint,
)
from ...core.models import AuditEvent
from ...core.object_store import ObjectStore, ObjectStoreError, MAX_OBJECT_BYTES
from ...lifecycle import lock_notice
from ...lifecycle.models import Attachment, Notice, NoticeObservation
from ..document_mcp.safety import ProcessorOptions
from ..models import (
    ContentObject,
    ContentObjectLocation,
    DocumentBundle,
    DocumentBundleItem,
    DocumentVersion,
    PrespecV4Attempt,
    PrespecV4PdfSnapshot,
    PrespecV4Target,
    WorkJob,
)
from .effective_grade import effective_grades
from .prespec_v4_gate import lock_v4_gate
from .prespec_v4 import (
    V4PreparationError,
    _canonical,
    _persist_artifact,
    _read_verified_artifact,
    build_v4_range_review_manifest,
    choose_rfp_document,
    freeze_v4_target,
    prepare_v4_pdf_snapshot,
    read_snapshot_section_candidates,
    select_v4_input_range,
)
from .prespec_v4_runner import (
    V4_LUNA_REFERENCE_MODEL,
    V4_LUNA_REFERENCE_PROVIDER,
    V4AttemptError,
    V4ModelBinding,
    approved_v4_binding,
    enqueue_v4_attempt,
    load_v4_policy,
    record_v4_preparation_failure,
)


LEGACY_ACTIVATION_SCHEMA = "bidops.prespec-v4-activation.v1"
ACTIVATION_SCHEMA = "bidops.prespec-v4-activation.v2"
ACTIVATION_ACTION = "prespec_v4.activation"
ACTIVATION_AGGREGATE = "prespec_v4_activation"
ACTIVATION_PATH = Path(__file__).resolve().parent.parent / "policies" / "prespec-v4-activation-v2.json"
V4_MAX_ACTIVATION_BYTES = 256 * 1024
_HEX64 = set("0123456789abcdef")


class V4OpsError(RuntimeError):
    """Stable safe error for the preparation/activation operator boundary."""

    def __init__(self, code: str) -> None:
        self.code = str(code or "v4_ops_failed")[:64]
        super().__init__(self.code)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256(_canonical(value))


def _now() -> datetime:
    return datetime.now(UTC)


def _mapping(value: Any, code: str = "activation_invalid") -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise V4OpsError(code)
    try:
        encoded = _canonical(dict(value))
    except V4PreparationError as error:
        raise V4OpsError(code) from error
    if len(encoded) > V4_MAX_ACTIVATION_BYTES:
        raise V4OpsError("activation_size_limit")
    return json.loads(encoded.decode("utf-8"))


@dataclass(frozen=True)
class V4Activation:
    activation_id: UUID
    mode: str
    artifact_sha256: str
    policy_digest: str
    binding: V4ModelBinding
    activated_at: datetime
    samples: tuple[dict[str, Any], ...]
    automatic_requirements: Mapping[str, Any]
    schema: str = LEGACY_ACTIVATION_SCHEMA


@dataclass(frozen=True)
class V4PreparationOutcome:
    notice_id: int
    status: str
    reason_code: str | None = None
    document_version_id: UUID | None = None
    snapshot_id: UUID | None = None
    target_id: UUID | None = None
    attempt_id: UUID | None = None


@dataclass(frozen=True)
class V4Deactivation:
    activation_id: UUID
    cancelled_attempts: int
    cancelled_jobs: int


def _artifact_bytes(value: Mapping[str, Any]) -> bytes:
    return _canonical(value)


def load_v4_activation_artifact(path: Path | None = None) -> tuple[dict[str, Any], str]:
    source = path or ACTIVATION_PATH
    try:
        raw = source.read_bytes()
        if len(raw) > V4_MAX_ACTIVATION_BYTES:
            raise V4OpsError("activation_size_limit")
        value = json.loads(raw)
    except V4OpsError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise V4OpsError("activation_unreadable") from error
    value = _mapping(value)
    versions = {LEGACY_ACTIVATION_SCHEMA: 1, ACTIVATION_SCHEMA: 2}
    if value.get("schema") not in versions or value.get("version") != versions[value["schema"]]:
        raise V4OpsError("activation_invalid")
    samples = value.get("samples")
    if not isinstance(samples, list) or any(not isinstance(item, Mapping) for item in samples):
        raise V4OpsError("activation_invalid")
    if value.get("automatic_requirements") is not None and not isinstance(value["automatic_requirements"], Mapping):
        raise V4OpsError("activation_invalid")
    # The digest is over canonical JSON, so insignificant source formatting
    # cannot create a second cohort identity.
    return value, _sha256_json(value)


def _policy_for(settings: Any | None = None):
    settings = settings or get_settings()
    path = getattr(settings, "prespec_overview_policy_path", None)
    return load_v4_policy(path)


def _binding_from(value: V4ModelBinding | Mapping[str, Any]) -> V4ModelBinding:
    if isinstance(value, V4ModelBinding):
        return value
    safe = _mapping(value, "binding_invalid")
    try:
        return V4ModelBinding(
            provider=str(safe["provider"]),
            model_name=str(safe["model_name"]),
            model_digest=str(safe["model_digest"]),
            prompt_version=str(safe["prompt_version"]),
            policy_digest=str(safe["policy_digest"]),
            reference_only=bool(safe.get("reference_only", True)),
            deployable=bool(safe.get("deployable", False)),
            binding_digest=safe.get("binding_digest"),
        )
    except (KeyError, TypeError, ValueError, V4AttemptError) as error:
        raise V4OpsError("binding_invalid") from error


def _safe_sample(value: Mapping[str, Any], *, pin_target: bool = False) -> dict[str, Any]:
    sample = _mapping(value, "activation_invalid")
    required = ("notice_id", "notice_key", "document_version_id", "source_sha256", "source_size_bytes")
    if any(key not in sample for key in required):
        raise V4OpsError("activation_invalid")
    try:
        notice_id = int(sample["notice_id"])
        size = int(sample["source_size_bytes"])
        document_id = UUID(str(sample["document_version_id"]))
    except (TypeError, ValueError) as error:
        raise V4OpsError("activation_invalid") from error
    source_sha = str(sample["source_sha256"])
    if len(source_sha) != 64 or any(char not in _HEX64 for char in source_sha):
        raise V4OpsError("activation_invalid")
    if notice_id < 1 or size < 1 or not str(sample["notice_key"]).strip():
        raise V4OpsError("activation_invalid")
    result = {
        "notice_id": notice_id,
        "notice_key": str(sample["notice_key"]),
        "document_version_id": str(document_id),
        "source_sha256": source_sha,
        "source_size_bytes": size,
        "original_filename": str(sample.get("original_filename", "")),
        "observation_kind": str(sample.get("observation_kind", "explicit_sample")),
    }
    # A source-only sample can authorize document preparation. It cannot
    # enqueue or dispatch until a later approval pins the resulting target.
    target_fields = ("target_id", "input_sha256", "selection_manifest_sha256", "pdf_sha256")
    if pin_target and any(key in sample for key in target_fields):
        try:
            result["target_id"] = str(UUID(str(sample["target_id"])))
            for key in ("input_sha256", "selection_manifest_sha256", "pdf_sha256"):
                digest = sample[key]
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ValueError("invalid_digest")
                result[key] = digest
        except (KeyError, TypeError, ValueError) as error:
            raise V4OpsError("activation_target_binding_required") from error
    return result


def _sample_entries(artifact: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    entries = tuple(_safe_sample(item, pin_target=artifact.get("schema") == ACTIVATION_SCHEMA)
                    for item in artifact.get("samples", []))
    seen: set[tuple[int, str]] = set()
    for item in entries:
        key = (item["notice_id"], item["document_version_id"])
        if key in seen:
            raise V4OpsError("activation_invalid")
        seen.add(key)
    return entries


def _execution_approval(policy: Any) -> dict[str, Any]:
    """Exact two-stage scope required in a v2 approval artifact."""
    return {
        "policy_schema": "bidops.prespec-overview-policy.v5",
        "policy_digest": policy.digest,
        "stages": ["prespec_overview_claims", "prespec_overview_semantic"],
        "max_model_calls": 3,
        "max_semantic_calls": 1,
        "call_timeout_seconds": 300,
        "lease_seconds": 1200,
    }


def preview_v4_activation(*, artifact_path: Path | None = None, settings: Any | None = None) -> dict[str, Any]:
    artifact, digest = load_v4_activation_artifact(artifact_path)
    policy = _policy_for(settings)
    return {
        "schema": artifact["schema"], "artifact_sha256": digest,
        "execution": _execution_approval(policy),
        "samples": list(_sample_entries(artifact)),
        "stage_policy_sha256": [
            {"stage": item["stage"], "sha256": _sha256_json(item)}
            for item in policy.document["stages"]
        ],
        "execution_approval_matches": artifact.get("schema") == ACTIVATION_SCHEMA
            and artifact.get("execution") == _execution_approval(policy),
        "activation_performed": False,
    }


def _binding_metadata(binding: V4ModelBinding) -> dict[str, Any]:
    return {
        "provider": binding.provider,
        "model_name": binding.model_name,
        "model_digest": binding.model_digest,
        "prompt_version": binding.prompt_version,
        "policy_digest": binding.policy_digest,
        "binding_digest": binding.binding_digest,
        "reference_only": bool(binding.reference_only),
        "deployable": bool(binding.deployable),
    }


def _binding_matches_policy(binding: V4ModelBinding, policy: Any) -> bool:
    """New claims use Qwen; the Luna exception belongs only to old v4 records."""

    if binding.policy_digest != policy.digest or binding.prompt_version != policy.prompt_version:
        return False
    if binding.model_name == policy.model_name:
        return True
    return (
        policy.document.get("schema") == "bidops.prespec-overview-policy.v4"
        and binding.provider == V4_LUNA_REFERENCE_PROVIDER
        and binding.model_name == V4_LUNA_REFERENCE_MODEL
        and binding.reference_only
        and not binding.deployable
    )


def _settings_reference_allowed(settings: Any) -> bool:
    return bool(getattr(settings, "reference_workflow_mode", False)) and getattr(settings, "analysis_provider", "vllm") == "vllm"


def resolve_v4_reference_binding(*, policy: Any | None = None, settings: Any | None = None) -> V4ModelBinding:
    settings = settings or get_settings()
    if not _settings_reference_allowed(settings):
        raise V4OpsError("reference_workflow_disabled")
    policy = policy or _policy_for(settings)
    try:
        endpoint = resolve_model_endpoint("overview", settings=settings)
    except (ModelEndpointError, ModelIdentityError, ValueError, OSError) as error:
        raise V4OpsError("model_binding_unavailable") from error
    binding = approved_v4_binding(policy=policy, identity=endpoint)
    if binding is None:
        raise V4OpsError("model_binding_unavailable")
    # A v4 activation is a reference run until a measured policy explicitly
    # promotes it.  It must never silently become a deployable binding.
    return V4ModelBinding(
        provider=binding.provider,
        model_name=binding.model_name,
        model_digest=binding.model_digest,
        prompt_version=binding.prompt_version,
        policy_digest=binding.policy_digest,
        reference_only=True,
        deployable=False,
    )


def _activation_timestamp(session: Session, requested: datetime | None) -> datetime:
    """Called under the gate: audit ordering must survive a tied/backward clock."""
    latest = session.scalar(select(AuditEvent.created_at).where(
        AuditEvent.action == ACTIVATION_ACTION, AuditEvent.aggregate_type == ACTIVATION_AGGREGATE,
    ).order_by(AuditEvent.created_at.desc()).limit(1))
    timestamp = requested or _now()
    if timestamp.tzinfo is None:
        raise V4OpsError("activation_time_invalid")
    return max(timestamp, latest + timedelta(microseconds=1)) if latest is not None else timestamp


def activate_v4(
    session: Session,
    *,
    actor: str,
    mode: str = "explicit_sample",
    artifact: Mapping[str, Any] | None = None,
    artifact_path: Path | None = None,
    binding: V4ModelBinding | Mapping[str, Any] | None = None,
    settings: Any | None = None,
    now: datetime | None = None,
) -> V4Activation:
    """Append an active cohort audit event; no scheduler or model call occurs."""

    if not isinstance(actor, str) or not actor.strip() or len(actor) > 128:
        raise V4OpsError("actor_required")
    if mode not in {"explicit_sample", "new_reference"}:
        raise V4OpsError("activation_mode_invalid")
    settings = settings or get_settings()
    if not _settings_reference_allowed(settings):
        raise V4OpsError("reference_workflow_disabled")
    if artifact is None:
        artifact, artifact_sha = load_v4_activation_artifact(artifact_path)
    else:
        artifact = _mapping(artifact)
        versions = {LEGACY_ACTIVATION_SCHEMA: 1, ACTIVATION_SCHEMA: 2}
        if artifact.get("schema") not in versions or artifact.get("version") != versions[artifact["schema"]]:
            raise V4OpsError("activation_invalid")
        artifact_sha = _sha256_json(artifact)
    samples = _sample_entries(artifact)
    if mode == "explicit_sample" and not samples:
        raise V4OpsError("activation_samples_missing")
    if mode == "new_reference" and samples:
        raise V4OpsError("activation_mode_sample_mismatch")
    policy = _policy_for(settings)
    is_v5 = policy.document.get("schema") == "bidops.prespec-overview-policy.v5"
    if is_v5 and (artifact.get("schema") != ACTIVATION_SCHEMA or artifact.get("execution") != _execution_approval(policy)):
        raise V4OpsError("activation_execution_approval_required")
    if not is_v5 and artifact.get("schema") != LEGACY_ACTIVATION_SCHEMA:
        raise V4OpsError("activation_policy_version_mismatch")
    selected_binding = _binding_from(binding) if binding is not None else resolve_v4_reference_binding(policy=policy, settings=settings)
    if not _binding_matches_policy(selected_binding, policy):
        raise V4OpsError("activation_binding_mismatch")
    if selected_binding.provider == V4_LUNA_REFERENCE_PROVIDER and mode != "explicit_sample":
        raise V4OpsError("luna_reference_requires_explicit_sample")
    if selected_binding.deployable or not selected_binding.reference_only:
        raise V4OpsError("reference_binding_required")
    lock_v4_gate(session)
    activation_id = uuid4()
    activated_at = _activation_timestamp(session, now)
    requirements = _mapping(artifact.get("automatic_requirements", {}), "activation_invalid")
    metadata = {
        "schema": artifact["schema"],
        "status": "active",
        "mode": mode,
        "artifact_sha256": artifact_sha,
        "policy_digest": policy.digest,
        "binding": _binding_metadata(selected_binding),
        "activated_at": activated_at.isoformat(),
        "samples": list(samples),
        "automatic_requirements": requirements,
        "quality_status": "unmeasured_reference",
    }
    if is_v5:
        metadata["execution"] = _execution_approval(policy)
    session.add(AuditEvent(
        id=activation_id,
        actor_kind="human",
        claimed_name=actor.strip(),
        action=ACTIVATION_ACTION,
        aggregate_type=ACTIVATION_AGGREGATE,
        aggregate_id=str(activation_id),
        safe_metadata=metadata,
        created_at=activated_at,
    ))
    session.flush()
    return V4Activation(activation_id, mode, artifact_sha, policy.digest, selected_binding, activated_at, samples, requirements, artifact["schema"])


def deactivate_v4(session: Session, *, actor: str, reason: str, now: datetime | None = None) -> V4Deactivation:
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 128 or not isinstance(reason, str) or not reason.strip():
        raise V4OpsError("actor_reason_required")
    lock_v4_gate(session)
    # Stop must work even if the prior policy is unavailable or an old artifact
    # can no longer authorize dispatch. The audit identity is sufficient here.
    previous = session.scalar(select(AuditEvent).where(
        AuditEvent.action == ACTIVATION_ACTION,
        AuditEvent.aggregate_type == ACTIVATION_AGGREGATE,
    ).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()))
    activation_id = uuid4()
    timestamp = _activation_timestamp(session, now)
    attempts = session.scalars(select(PrespecV4Attempt).where(
        PrespecV4Attempt.status.in_(("queued", "running")),
    ).order_by(PrespecV4Attempt.id).with_for_update()).all()
    job_ids = {attempt.work_job_id for attempt in attempts if attempt.work_job_id is not None}
    jobs = session.scalars(select(WorkJob).where(
        WorkJob.id.in_(job_ids), WorkJob.status.in_(("queued", "running")),
    ).order_by(WorkJob.id).with_for_update()).all() if job_ids else []
    for attempt in attempts:
        attempt.status = "cancelled"
        attempt.completed_at = timestamp
        attempt.error_code = "v4_deactivated"
        attempt.lease_owner = None
        attempt.lease_expires_at = None
    for job in jobs:
        job.status = "cancelled"
        job.completed_at = timestamp
        job.last_error_code = "v4_deactivated"
        job.lease_owner = None
        job.lease_expires_at = None
    # Free-form operator text must not become a path, URL or secret in audit.
    reason_code = reason if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason) else "operator_requested"
    session.add(AuditEvent(
        id=activation_id,
        actor_kind="human",
        claimed_name=actor.strip(),
        action=ACTIVATION_ACTION,
        aggregate_type=ACTIVATION_AGGREGATE,
        aggregate_id=str(activation_id),
        safe_metadata={
            "schema": ACTIVATION_SCHEMA,
            "status": "off",
            "reason_code": reason_code,
            "previous_activation_id": str(previous.id) if previous else None,
            "deactivated_at": timestamp.isoformat(),
            "cancelled_attempts": len(attempts),
            "cancelled_jobs": len(jobs),
        },
        created_at=timestamp,
    ))
    session.flush()
    return V4Deactivation(activation_id, len(attempts), len(jobs))


def _activation_from_event(event: AuditEvent, *, settings: Any | None = None) -> V4Activation | None:
    metadata = event.safe_metadata
    if not isinstance(metadata, Mapping) or metadata.get("status") != "active" or metadata.get("schema") not in {ACTIVATION_SCHEMA, LEGACY_ACTIVATION_SCHEMA}:
        return None
    try:
        policy = _policy_for(settings)
        if metadata.get("policy_digest") != policy.digest:
            return None
        if policy.document.get("schema") == "bidops.prespec-overview-policy.v5" and (
            metadata.get("schema") != ACTIVATION_SCHEMA or metadata.get("execution") != _execution_approval(policy)
        ):
            return None
        binding = _binding_from(metadata["binding"])
        if not _binding_matches_policy(binding, policy) or binding.deployable or not binding.reference_only:
            return None
        activated_at = datetime.fromisoformat(str(metadata["activated_at"]))
        if activated_at.tzinfo is None:
            return None
        samples = _sample_entries({"schema": metadata["schema"], "samples": metadata.get("samples", [])})
        requirements = _mapping(metadata.get("automatic_requirements", {}), "activation_invalid")
        artifact_sha = metadata.get("artifact_sha256")
        if not isinstance(artifact_sha, str) or len(artifact_sha) != 64 or any(c not in _HEX64 for c in artifact_sha):
            return None
        mode = metadata.get("mode")
        if mode not in {"explicit_sample", "new_reference"}:
            return None
        if binding.provider == V4_LUNA_REFERENCE_PROVIDER and mode != "explicit_sample":
            return None
        return V4Activation(event.id, mode, artifact_sha, policy.digest, binding, activated_at, samples, requirements, metadata["schema"])
    except (KeyError, TypeError, ValueError, V4OpsError):
        return None


def active_v4_activation(session: Session, *, settings: Any | None = None) -> V4Activation | None:
    """Read the latest activation/off audit event; malformed state fails closed."""

    event = session.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == ACTIVATION_ACTION, AuditEvent.aggregate_type == ACTIVATION_AGGREGATE)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    )
    if event is None or not isinstance(event.safe_metadata, Mapping):
        return None
    if event.safe_metadata.get("status") != "active":
        return None
    return _activation_from_event(event, settings=settings)


def v4_dispatch_enabled(session: Session, *, settings: Any | None = None) -> V4Activation | None:
    return active_v4_activation(session, settings=settings)


def _sample_for_target(activation: V4Activation, target: PrespecV4Target) -> dict[str, Any] | None:
    for sample in activation.samples:
        if sample["notice_id"] == target.notice_id and sample["document_version_id"] == str(target.document_version_id):
            return sample
    return None


def require_v4_enqueue_enabled(
    session: Session,
    *,
    target: PrespecV4Target,
    binding: V4ModelBinding,
    settings: Any | None = None,
) -> V4Activation:
    lock_v4_gate(session)
    activation = active_v4_activation(session, settings=settings)
    if activation is None:
        raise V4AttemptError("v4_disabled")
    if binding.binding_digest != activation.binding.binding_digest or binding.policy_digest != activation.policy_digest:
        raise V4AttemptError("activation_binding_mismatch")
    if activation.mode == "explicit_sample":
        sample = _sample_for_target(activation, target)
        if sample is None or target.observation_kind != "explicit_sample":
            raise V4AttemptError("target_outside_cohort")
        snapshot = session.get(PrespecV4PdfSnapshot, target.snapshot_id)
        if snapshot is None or snapshot.source_sha256 != sample["source_sha256"] or snapshot.source_size_bytes != sample["source_size_bytes"]:
            raise V4AttemptError("cohort_source_mismatch")
        if activation.schema == ACTIVATION_SCHEMA and (
            str(target.id) != sample.get("target_id")
            or target.input_sha256 != sample.get("input_sha256")
            or target.selection_manifest_sha256 != sample.get("selection_manifest_sha256")
            or snapshot.pdf_sha256 != sample.get("pdf_sha256")
        ):
            raise V4AttemptError("cohort_target_mismatch")
    elif target.observation_kind == "explicit_sample":
        raise V4AttemptError("target_outside_cohort")
    return activation


def _canonical_attachment(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("name"), item.get("source_url"), item.get("source_system"),
        item.get("source_attachment_key"), item.get("size_bytes"),
    )


def _attachment_set(snapshot: Any) -> tuple[tuple[Any, ...], ...]:
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("attachments"), list):
        return ()
    values = [_canonical_attachment(item) for item in snapshot["attachments"] if isinstance(item, Mapping)]
    return tuple(sorted(values, key=lambda item: repr(item)))


def _observation_candidate(
    session: Session,
    *,
    notice: Notice,
    document: DocumentVersion,
    activation: V4Activation,
) -> tuple[str, NoticeObservation, dict[str, Any]]:
    observations = session.scalars(
        select(NoticeObservation)
        .where(NoticeObservation.notice_id == notice.id)
        .order_by(NoticeObservation.observed_at.asc(), NoticeObservation.id.asc())
    ).all()
    current = [item for item in observations if item.observed_at > activation.activated_at]
    if not current:
        raise V4OpsError("observation_before_activation")
    observation = current[-1]
    snapshot = observation.snapshot_jsonb
    if not isinstance(snapshot, Mapping) or not observation.source_sha256 or not observation.snapshot_schema_version:
        raise V4OpsError("observation_evidence_missing")
    source = session.get(ContentObject, document.content_object_id)
    if source is None:
        raise V4OpsError("source_content_missing")
    attachments = snapshot.get("attachments")
    if not isinstance(attachments, list):
        raise V4OpsError("observation_attachments_missing")
    matching: list[Mapping[str, Any]] = []
    for item in attachments:
        if not isinstance(item, Mapping):
            continue
        if document.source_system and item.get("source_system") != document.source_system:
            continue
        if document.source_attachment_key and item.get("source_attachment_key") != document.source_attachment_key:
            continue
        if item.get("size_bytes") is not None and item.get("size_bytes") != source.size_bytes:
            continue
        matching.append(item)
    if document.source_kind == "provider" and len(matching) != 1:
        raise V4OpsError("observation_document_unbound")
    previous = observations[:-1]
    current_set = _attachment_set(snapshot)
    previous_set = _attachment_set(previous[-1].snapshot_jsonb) if previous else ()
    if not previous:
        kind = "first_observation"
    elif current_set != previous_set:
        kind = "attachment_change"
    else:
        raise V4OpsError("observation_unchanged")
    reference = {
        "kind": kind,
        "observation_id": observation.id,
        "observation_source_sha256": observation.source_sha256,
        "observation_schema": observation.snapshot_schema_version,
        "observed_at": observation.observed_at.isoformat(),
        "document_version_id": str(document.id),
        "document_source_sha256": source.sha256,
        "document_source_size_bytes": source.size_bytes,
        "attachment": dict(matching[0]) if matching else None,
        "attachment_changed": kind == "attachment_change",
        "current_attachment_fingerprint_sha256": _sha256_json(current_set),
        "previous_attachment_fingerprint_sha256": _sha256_json(previous_set) if previous else None,
    }
    return kind, observation, reference


def _source_location(session: Session, document: DocumentVersion) -> ContentObjectLocation:
    locations = session.scalars(
        select(ContentObjectLocation)
        .where(
            ContentObjectLocation.content_object_id == document.content_object_id,
            ContentObjectLocation.namespace_key == "source",
            ContentObjectLocation.status == "verified",
            ContentObjectLocation.purged_at.is_(None),
        )
        .order_by(ContentObjectLocation.created_at.desc(), ContentObjectLocation.id.desc())
    ).all()
    if len(locations) != 1:
        raise V4OpsError("source_location_ambiguous")
    return locations[0]


def _automatic_ready_bundle(session: Session, notice_id: int, document_id: UUID) -> bool:
    return session.scalar(
        select(DocumentBundleItem.bundle_id)
        .join(DocumentBundle, DocumentBundle.id == DocumentBundleItem.bundle_id)
        .where(
            DocumentBundle.notice_id == notice_id,
            DocumentBundle.status == "ready",
            DocumentBundle.confirmed_by_name == "auto-preparation",
            DocumentBundleItem.document_version_id == document_id,
        )
        .limit(1)
    ) is not None


def _check_automatic_eligibility(session: Session, notice: Notice, document: DocumentVersion, activation: V4Activation) -> None:
    if notice.source_type != "pre_spec":
        raise V4OpsError("not_pre_spec")
    flags = notice.qualification_flags_json
    if not isinstance(flags, Mapping) or flags.get("sw_business_status") != "Y":
        raise V4OpsError("sw_business_not_eligible")
    grades = effective_grades(session, [notice.id])
    grade = grades.get(notice.id)
    if grade is None or not grade.is_priority:
        raise V4OpsError("priority_grade_missing")
    if not _automatic_ready_bundle(session, notice.id, document.id):
        raise V4OpsError("auto_bundle_not_ready")
    if activation.mode != "new_reference":
        raise V4OpsError("activation_mode_mismatch")


def prepare_v4_notice(
    session: Session,
    *,
    notice_id: int,
    mode: str,
    store: ObjectStore,
    converter: Any,
    options: ProcessorOptions | Mapping[str, Any],
    renderer: Mapping[str, Any],
    font: Mapping[str, Any],
    config: Mapping[str, Any],
    scanner: Any | None = None,
    binding: V4ModelBinding | None = None,
    settings: Any | None = None,
    enqueue: bool = False,
) -> V4PreparationOutcome:
    """Prepare one explicit/automatic notice, freeze its manifest, optionally enqueue."""

    activation = active_v4_activation(session, settings=settings)
    if activation is None:
        raise V4OpsError("v4_disabled")
    if activation.mode != mode:
        raise V4OpsError("activation_mode_mismatch")
    notice = lock_notice(session, notice_id)
    if notice is None or notice.source_type != "pre_spec":
        raise V4OpsError("notice_not_found")
    documents = session.scalars(
        select(DocumentVersion).where(
            DocumentVersion.notice_id == notice_id,
            DocumentVersion.is_current.is_(True),
            DocumentVersion.safety_status == "safe",
            DocumentVersion.needs_human_review.is_(False),
        )
    ).all()
    selection = choose_rfp_document(documents)
    if selection.document is None:
        raise V4OpsError(selection.reason_code or "rfp_document_ambiguous")
    document = selection.document
    source = session.get(ContentObject, document.content_object_id)
    if source is None:
        raise V4OpsError("source_content_missing")
    if mode == "explicit_sample":
        sample = next(
            (
                item for item in activation.samples
                if item["notice_id"] == notice_id and item["document_version_id"] == str(document.id)
            ),
            None,
        )
        if sample is None or source.sha256 != sample["source_sha256"] or source.size_bytes != sample["source_size_bytes"]:
            raise V4OpsError("explicit_sample_mismatch")
        observation_kind = "explicit_sample"
        observation_id = None
        observation_reference: dict[str, Any] = {
            "kind": "explicit_sample",
            "sample": sample,
            "document_version_id": str(document.id),
            "source_sha256": source.sha256,
            "source_size_bytes": source.size_bytes,
        }
    else:
        _check_automatic_eligibility(session, notice, document, activation)
        observation_kind, observation, observation_reference = _observation_candidate(
            session, notice=notice, document=document, activation=activation
        )
        observation_id = observation.id
    location = _source_location(session, document)
    try:
        source_bytes = _read_verified_artifact(store, location, source, max_bytes=min(MAX_OBJECT_BYTES, source.size_bytes))
    except V4PreparationError as error:
        raise V4OpsError(error.code) from error
    try:
        snapshot = prepare_v4_pdf_snapshot(
            session,
            document_version_id=document.id,
            source_location_id=location.id,
            source_bytes=source_bytes,
            media_type=source.detected_mime,
            converter=converter,
            store=store,
            options=options,
            renderer=renderer,
            font=font,
            config=config,
            scanner=scanner,
        )
        page_text_content = session.get(ContentObject, snapshot.page_text_content_object_id)
        page_text_location = session.get(ContentObjectLocation, snapshot.page_text_location_id)
        if page_text_content is None or page_text_location is None:
            raise V4OpsError("page_text_unavailable")
        page_text_bytes = _read_verified_artifact(store, page_text_location, page_text_content, max_bytes=page_text_content.size_bytes)
        page_payload = json.loads(page_text_bytes)
        if not isinstance(page_payload, Mapping):
            raise V4OpsError("page_text_invalid")
        candidates = read_snapshot_section_candidates(session, store, snapshot)
        range_selection = select_v4_input_range({
            "document_version_id": str(document.id),
            "source_sha256": source.sha256,
            "pages": page_payload.get("pages"),
            "blocks": page_payload.get("blocks", []),
        }, candidates_complete=not bool(candidates and candidates.get("candidates_truncated")))
        if range_selection.status != "ready":
            # 결정적 선택기가 경계를 못 정한 것은 준비 실패가 아니다. 후보 목록을
            # 가리키는 검토 manifest를 남기고 사람 확정 대기 target을 동결한다.
            # attempt는 `--enqueue`에서도 만들지 않는다(자동 실행을 열지 않는다).
            _review_manifest, review_bytes = build_v4_range_review_manifest(
                range_selection,
                candidates_sha256=snapshot.section_candidates_sha256,
                candidate_count=len(candidates["sections"]) if candidates else 0,
            )
            _persist_artifact(
                session,
                store,
                namespace="structure",
                object_key=f"structure/prespec-v4/{document.id}/manifest-{_sha256(review_bytes)}.json",
                data=review_bytes,
                detected_mime="application/json",
                retention_class="prespec-v4-input",
            )
            review_target = freeze_v4_target(
                session,
                snapshot_id=snapshot.id,
                observation_kind=observation_kind,
                observation_id=observation_id,
                observation_reference=observation_reference,
                selection=range_selection,
            )
            return V4PreparationOutcome(
                notice_id=notice_id, status="needs_human_review",
                reason_code=range_selection.reason_code,
                document_version_id=document.id, snapshot_id=snapshot.id,
                target_id=review_target.id, attempt_id=None,
            )
        manifest_content, manifest_location = _persist_artifact(
            session,
            store,
            namespace="structure",
            object_key=f"structure/prespec-v4/{document.id}/manifest-{_sha256(range_selection.manifest_bytes)}.json",
            data=range_selection.manifest_bytes,
            detected_mime="application/json",
            retention_class="prespec-v4-input",
        )
        target = freeze_v4_target(
            session,
            snapshot_id=snapshot.id,
            observation_kind=observation_kind,
            observation_id=observation_id,
            observation_reference=observation_reference,
            selection=range_selection,
            manifest_content_object_id=manifest_content.id,
            manifest_location_id=manifest_location.id,
            manifest_bytes=range_selection.manifest_bytes,
        )
        attempt = None
        if enqueue:
            enqueue_binding = binding or resolve_v4_reference_binding(policy=_policy_for(settings), settings=settings)
            attempt = enqueue_v4_attempt(session, target_id=target.id, binding=enqueue_binding, quality_status="unmeasured_reference", settings=settings)
        return V4PreparationOutcome(
            notice_id=notice_id, status="queued" if attempt is not None else "ready",
            document_version_id=document.id, snapshot_id=snapshot.id, target_id=target.id,
            attempt_id=attempt.id if attempt is not None else None,
        )
    except (V4PreparationError, ObjectStoreError, ValueError, TypeError, json.JSONDecodeError) as error:
        if isinstance(error, V4PreparationError):
            raise V4OpsError(error.code) from error
        raise V4OpsError("v4_preparation_failed") from error


def prepare_v4_notice_once(session: Session, **kwargs: Any) -> V4PreparationOutcome:
    """Run one preparation and expose deterministic failures in current state.

    Eligibility/off decisions remain read-only failures.  Once an activated
    notice is eligible, a converter, source, or storage failure gets a terminal
    notice-scoped attempt so the API cannot present an old success as the
    current run.  An undecidable **range** is not such a failure: the selector
    freezes a `needs_human_review` target instead and this function passes that
    outcome through without creating an attempt (R7, ADR-RDP-004).
    """

    kwargs["session"] = session
    notice_id = kwargs.get("notice_id")
    try:
        return prepare_v4_notice(**kwargs)
    except V4OpsError as error:
        if error.code in {
            "v4_disabled", "activation_mode_mismatch", "not_pre_spec",
            "sw_business_not_eligible", "priority_grade_missing", "auto_bundle_not_ready",
            "observation_before_activation", "observation_unchanged", "observation_evidence_missing",
        }:
            raise
        if isinstance(notice_id, bool) or not isinstance(notice_id, int):
            raise
        failed = record_v4_preparation_failure(
            session,
            notice_id=notice_id,
            error_code=error.code,
        )
        return V4PreparationOutcome(notice_id=notice_id, status="failed", reason_code=error.code, attempt_id=failed.id)


def retry_v4_attempt(session: Session, *, target_id: UUID, binding: V4ModelBinding, settings: Any | None = None) -> PrespecV4Attempt:
    lock_v4_gate(session)
    target = session.get(PrespecV4Target, target_id)
    if target is None or target.selection_status != "ready":
        raise V4OpsError("target_not_ready")
    latest = session.scalar(
        select(PrespecV4Attempt)
        .where(PrespecV4Attempt.target_id == target.id)
        .order_by(PrespecV4Attempt.sequence.desc())
    )
    if latest is not None and latest.status in {"queued", "running"}:
        raise V4OpsError("attempt_active")
    if latest is None or latest.status not in {"failed", "cancelled", "needs_human_review"}:
        raise V4OpsError("retry_requires_terminal_failure")
    try:
        return enqueue_v4_attempt(session, target_id=target.id, binding=binding, quality_status="unmeasured_reference", settings=settings)
    except V4AttemptError as error:
        raise V4OpsError(error.code) from error


def dry_run_v4(session: Session, *, notice_ids: Sequence[int], mode: str, settings: Any | None = None) -> list[dict[str, Any]]:
    """Read-only plan.  It intentionally omits paths, URLs and source text."""

    activation = active_v4_activation(session, settings=settings)
    output: list[dict[str, Any]] = []
    for notice_id in tuple(dict.fromkeys(int(value) for value in notice_ids)):
        notice = session.get(Notice, notice_id)
        if notice is None:
            output.append({"notice_id": notice_id, "status": "failed", "reason_code": "notice_not_found"})
            continue
        if activation is None:
            output.append({"notice_id": notice_id, "status": "disabled", "reason_code": "v4_disabled"})
            continue
        if activation.mode != mode:
            output.append({"notice_id": notice_id, "status": "excluded", "reason_code": "activation_mode_mismatch"})
            continue
        docs = session.scalars(select(DocumentVersion).where(DocumentVersion.notice_id == notice_id, DocumentVersion.is_current.is_(True), DocumentVersion.safety_status == "safe")).all()
        selected = choose_rfp_document(docs)
        if selected.document is None:
            output.append({"notice_id": notice_id, "status": "needs_human_review", "reason_code": selected.reason_code or "rfp_document_ambiguous"})
            continue
        output.append({"notice_id": notice_id, "status": "eligible", "reason_code": None, "document_version_id": str(selected.document.id)})
    return output


__all__ = [
    "ACTIVATION_PATH", "ACTIVATION_SCHEMA", "V4Activation", "V4OpsError", "V4PreparationOutcome",
    "activate_v4", "active_v4_activation", "deactivate_v4", "dry_run_v4",
    "load_v4_activation_artifact", "prepare_v4_notice", "require_v4_enqueue_enabled",
    "resolve_v4_reference_binding", "retry_v4_attempt", "prepare_v4_notice_once", "v4_dispatch_enabled",
]
