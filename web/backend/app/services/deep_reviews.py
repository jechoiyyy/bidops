"""Deep-review lifecycle, bounded stage execution, and lease-fenced writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
import re
from copy import deepcopy
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    AnalysisPolicyVersion,
    AuditEvent,
    Claim,
    ClaimEvidence,
    ContentObject,
    ContentObjectLocation,
    DeepReview,
    DeepReviewAttempt,
    DeepReviewStage,
    EvidenceRef,
    IdempotencyRecord,
    Notice,
    ProfileVersion,
    WorkJob,
)
from ..config import get_settings
from .deep_review_validation import DeepReviewValidationError, merge_stage_chunks, validate_deep_review_stage
from .input_versions import (
    STAGES,
    GradeBasis,
    InputVersionError,
    bundle_context,
    canonical_json_bytes,
    effective_grade_basis,
    profile_context,
    policy_quality_snapshot,
    resolve_active_versions,
    validate_pinned_policy,
)
from .vllm_client import (
    APPROVED_RETRIES,
    APPROVED_TIMEOUT_SECONDS,
    EncryptedObjectStore,
    InvocationResult,
    VllmClient,
    VllmInvocationError,
)
from .codex_exec_client import CodexExecClient
from .mock_analysis_client import MockAnalysisClient
from .object_store import EncryptedModelResponseStore


STAGE_SEQUENCE = {name: index for index, name in enumerate(STAGES, start=1)}
MIN_LEASE_SECONDS = APPROVED_TIMEOUT_SECONDS * (APPROVED_RETRIES + 1) + 60
WORKER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
EMPTY_PRIOR_CLAIM_ID = uuid5(NAMESPACE_URL, "bidops.deep-review.empty-prior-claim")
_SAFE_INVOCATION_ATTEMPT_KEYS = frozenset({"retry_index", "status", "error_code", "latency_ms"})
_SAFE_INVOCATION_KEYS = frozenset({
    "slice_index", "input_slice_sha256", "prompt_sha256", "response_sha256",
    "model", "policy_sha256", "prompt_tokens", "output_tokens", "latency_ms",
    "status", "error_code", "retry_index", "fixed_input_hash", "safe",
    "attempts", "provider",
})


class DeepReviewServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400, request_id: UUID | None = None) -> None:
        self.code = code
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(message)


DeepReviewError = DeepReviewServiceError


class StaleFenceError(DeepReviewServiceError):
    def __init__(self) -> None:
        super().__init__("stale_fence", "분석 작업 lease가 더 이상 유효하지 않습니다", status_code=409)


class _MissingEncryptedStore:
    def put_encrypted(self, data: bytes, *, retention_days: int, content_type: str) -> Mapping[str, Any]:
        raise DeepReviewServiceError("service_unavailable", "암호화 model-response 저장소를 사용할 수 없습니다", status_code=503)


@dataclass(frozen=True)
class JobClaim:
    job_id: UUID
    deep_review_id: UUID
    attempt_id: UUID
    worker_id: str
    fence: int


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value if isinstance(value, Mapping) else {"value": value})).hexdigest()


def _validate_actor(actor: str | None) -> str:
    if actor is None or not actor.strip():
        raise DeepReviewServiceError("actor_name_required", "담당자 이름이 필요합니다", status_code=400)
    clean = actor.strip()
    if len(clean) > 128 or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in clean) or clean.lower() == "system":
        raise DeepReviewServiceError("actor_name_invalid", "담당자 이름이 올바르지 않습니다", status_code=400)
    return clean


def _validate_worker_id(worker_id: str) -> str:
    clean = worker_id.strip() if isinstance(worker_id, str) else ""
    if not WORKER_ID_RE.fullmatch(clean):
        raise DeepReviewServiceError("invalid_request", "worker_id 형식이 올바르지 않습니다", status_code=400)
    return clean


def _safe_invocation_attempt(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Keep only bounded provider observation fields in invocation metadata."""

    if not isinstance(value, Mapping):
        return {}
    return {key: value[key] for key in _SAFE_INVOCATION_ATTEMPT_KEYS if key in value}


def _safe_invocation_metadata(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Whitelist persisted invocation metadata; never persist model locators."""

    if not isinstance(value, Mapping):
        return {}
    output = {key: value[key] for key in _SAFE_INVOCATION_KEYS if key in value and key != "attempts"}
    attempts = value.get("attempts")
    if isinstance(attempts, Sequence) and not isinstance(attempts, (str, bytes, bytearray)):
        output["attempts"] = [_safe_invocation_attempt(item) for item in attempts]
    return output


def _resolve_exact_evidence_quotes(
    payload: Mapping[str, Any],
    structures: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve whitespace-normalized document quotes to one exact substring.

    PDF layout extractors commonly retain runs of spaces/newlines that a model
    collapses while copying.  A quote is repaired only when all non-whitespace
    characters are unchanged and the whitespace-flexible pattern resolves to
    exactly one source span inside the already-pinned locator scope.  Anything
    ambiguous or textually different is left untouched for fail-closed
    validation.
    """

    resolved = deepcopy(dict(payload))
    evidence_rows = resolved.get("evidence")
    if not isinstance(evidence_rows, list):
        return resolved
    for evidence in evidence_rows:
        if not isinstance(evidence, dict) or evidence.get("source_kind") != "document":
            continue
        quote = evidence.get("quote")
        locator = evidence.get("locator")
        structure = structures.get(str(evidence.get("structure_id")))
        if not isinstance(quote, str) or not quote.strip() or not isinstance(locator, Mapping) or not isinstance(structure, Mapping):
            continue
        page = locator.get("page")
        blocks = [
            block for block in structure.get("blocks", [])
            if isinstance(block, Mapping) and block.get("page") == page and isinstance(block.get("text"), str)
        ]
        if evidence.get("locator_type") != "page":
            blocks = [block for block in blocks if block.get("block_key") == locator.get("block_key")]
        texts = [str(block["text"]) for block in blocks]
        if any(quote in text for text in texts):
            continue
        tokens = re.findall(r"\S+", quote)
        if not tokens:
            continue
        pattern = re.compile(r"\s+".join(re.escape(token) for token in tokens))
        matches = [match.group(0) for text in texts for match in pattern.finditer(text)]
        if len(matches) == 1:
            evidence["quote"] = matches[0]
    return resolved


def _add_job_audit(
    session: Session,
    *,
    action: str,
    job_id: UUID | str,
    review_id: UUID | str | None,
    attempt_id: UUID | str | None,
    fence: int,
    status: str,
) -> None:
    """Append only safe system metadata inside the fenced transition txn."""

    session.add(AuditEvent(
        actor_kind="system",
        claimed_name=None,
        action=action,
        aggregate_type="work_job",
        aggregate_id=str(job_id),
        request_id=None,
        safe_metadata={
            "job_id": str(job_id),
            "review_id": str(review_id) if review_id is not None else None,
            "attempt_id": str(attempt_id) if attempt_id is not None else None,
            "lease_fence": int(fence),
            "status": status,
        },
    ))


def _idempotency_hash(operation: str, payload: Mapping[str, Any]) -> str:
    return _canonical_hash({"operation": operation, **dict(payload)})


def _policy_payload(policy: AnalysisPolicyVersion) -> dict[str, Any]:
    rules = dict(policy.validation_rules) if isinstance(policy.validation_rules, Mapping) else {}
    threshold_keys = {key: rules[key] for key in ("max_unsupported_false_positive_rate", "min_human_agreement", "min_required_item_recall") if key in rules}
    return {
        "schema": "bidops.analysis-policy.v1", "model_endpoint_ref": policy.model_endpoint_ref,
        "model_name": policy.model_name, "policy_sha256": policy.policy_sha256,
        "chunking": {"max_characters": 24000, "max_requirements": 20, "retries": 2, "timeout_seconds": 300,
                     "merge_order": ["stage_sequence", "document_ordinal", "page", "block_order", "requirement_id", "slice_index"]},
        "generation": rules.get("generation"),
        "stages": policy.prompts if isinstance(policy.prompts, list) else [],
        "validation": threshold_keys,
    }


def _audit_correlation_id(
    session: Session,
    *,
    action: str,
    aggregate_type: str,
    aggregate_id: str,
) -> UUID | None:
    """Read one immutable lineage value without backfilling legacy audits."""

    rows = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action == action,
            AuditEvent.aggregate_type == aggregate_type,
            AuditEvent.aggregate_id == aggregate_id,
        )
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .limit(2)
    ).all()
    if len(rows) > 1:
        raise DeepReviewServiceError("processing_failed", "deep review 계보를 확인할 수 없습니다", status_code=500)
    if not rows:
        return None
    metadata = rows[0].safe_metadata if isinstance(rows[0].safe_metadata, Mapping) else {}
    if "correlation_id" not in metadata:
        return None
    value = metadata.get("correlation_id")
    if value is None:
        raise DeepReviewServiceError("processing_failed", "deep review 계보를 확인할 수 없습니다", status_code=500)
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise DeepReviewServiceError("processing_failed", "deep review 계보를 확인할 수 없습니다", status_code=500) from exc


class DeepReviewService:
    """Owns review/attempt/job state while keeping model I/O transaction-free."""

    def __init__(
        self,
        *,
        client: VllmClient | Any | None = None,
        raw_response_store: EncryptedObjectStore | Any | None = None,
        structure_loader: Callable[[Session, Any], Mapping[str, Any]] | None = None,
        report_service: Any | None = None,
        lease_seconds: int = 300,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        settings = get_settings()
        if client is not None:
            self.client = client
        elif settings.analysis_provider == "mock":
            self.client = MockAnalysisClient()
        elif settings.analysis_provider == "codex-exec":
            self.client = CodexExecClient(
                enabled=settings.openai_enabled and settings.codex_exec_enabled,
                binary=settings.codex_exec_binary,
                model=settings.codex_exec_model,
                reasoning_effort=settings.codex_exec_reasoning_effort,
                approved_notice_ids=settings.approved_codex_notice_ids,
            )
        else:
            self.client = VllmClient(
                base_url=settings.vllm_base_url,
                api_key=settings.vllm_api_key.get_secret_value(),
                allowed_hosts=settings.vllm_allowed_hosts,
                model=settings.vllm_model,
            )
        self.reference_workflow_mode = bool(settings.reference_workflow_mode and (
            (
                settings.analysis_provider == "mock"
                and getattr(self.client, "provider_name", None) == "mock-analysis"
            )
            or (
                settings.analysis_provider == "codex-exec"
                and settings.openai_enabled
                and settings.codex_exec_enabled
                and getattr(self.client, "provider_name", None) == "codex-exec-reference"
            )
        ))
        # The configured store is lazy so module import remains usable for
        # isolated unit tests; production lifespan/worker startup validates
        # MinIO credentials and encryption key configuration before serving.
        self.raw_response_store = raw_response_store or EncryptedModelResponseStore(settings)
        self.structure_loader = structure_loader
        self.report_service = report_service
        # One initial 300-second invocation plus two retries needs one
        # budget plus margin.  A shorter lease would make a valid worker look
        # stale while vLLM is still processing the approved request.
        self.lease_seconds = max(int(lease_seconds), MIN_LEASE_SECONDS)
        self.clock = clock

    def _idempotent_response(self, session: Session, *, operation: str, aggregate_type: str, aggregate_id: str, actor: str, request_id: UUID, request_hash: str) -> dict[str, Any] | None:
        row = session.scalar(select(IdempotencyRecord).where(
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.aggregate_type == aggregate_type,
            IdempotencyRecord.aggregate_id == aggregate_id,
            IdempotencyRecord.claimed_name == actor,
            IdempotencyRecord.request_id == request_id,
        ).limit(1))
        if row is None:
            return None
        if row.request_sha256 != request_hash:
            raise DeepReviewServiceError("idempotency_conflict", "같은 request_id가 다른 요청에 사용되었습니다", status_code=409, request_id=request_id)
        return row.response_snapshot if isinstance(row.response_snapshot, Mapping) else None

    @staticmethod
    def _stages(session: Session, attempt_id: UUID) -> list[DeepReviewStage]:
        return session.scalars(select(DeepReviewStage).where(DeepReviewStage.attempt_id == attempt_id).order_by(DeepReviewStage.sequence.asc())).all()

    def _attempt_view(self, session: Session, attempt: DeepReviewAttempt) -> dict[str, Any]:
        stages = self._stages(session, attempt.id)
        last_error = None
        for stage in reversed(stages):
            metadata = stage.invocation_metadata
            entries = metadata if isinstance(metadata, list) else [metadata] if isinstance(metadata, Mapping) else []
            errors = [entry.get("error_code") or entry.get("last_error_code") for entry in entries if isinstance(entry, Mapping)]
            if any(errors):
                last_error = next(error for error in reversed(errors) if error)
                break
        return {
            "id": str(attempt.id), "sequence": attempt.sequence, "status": attempt.status,
            "stages": [{
                "stage": stage.stage, "sequence": stage.sequence, "status": stage.status,
                "started_at": stage.started_at.isoformat() if stage.started_at else None,
                "completed_at": stage.completed_at.isoformat() if stage.completed_at else None,
                "last_error_code": next((entry.get("error_code") or entry.get("last_error_code") for entry in reversed(stage.invocation_metadata if isinstance(stage.invocation_metadata, list) else [stage.invocation_metadata] if isinstance(stage.invocation_metadata, Mapping) else []) if isinstance(entry, Mapping) and (entry.get("error_code") or entry.get("last_error_code"))), None),
            } for stage in stages],
            "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
            "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
            "last_error_code": last_error,
        }

    def view(self, session: Session, review_id: UUID) -> dict[str, Any]:
        review = session.get(DeepReview, review_id)
        if review is None:
            raise DeepReviewServiceError("not_found", "deep review를 찾을 수 없습니다", status_code=404)
        attempts = session.scalars(select(DeepReviewAttempt).where(DeepReviewAttempt.deep_review_id == review.id).order_by(DeepReviewAttempt.sequence.asc())).all()
        current = next((attempt for attempt in attempts if attempt.id == review.current_attempt_id), None)
        return {
            "id": str(review.id), "notice_id": review.notice_id, "bundle_id": str(review.bundle_id),
            "status": review.status, "current_attempt": self._attempt_view(session, current) if current else None,
            "attempts": [self._attempt_view(session, attempt) for attempt in attempts],
            "created_at": review.created_at.isoformat(), "completed_at": review.completed_at.isoformat() if review.completed_at else None,
        }

    def _seed_attempt(self, session: Session, review: DeepReview, *, sequence: int, actor: str) -> DeepReviewAttempt:
        attempt = DeepReviewAttempt(id=uuid4(), deep_review_id=review.id, sequence=sequence, status="queued", lease_fence=0, requested_by_name=actor)
        session.add(attempt)
        session.flush()
        job = WorkJob(id=uuid4(), job_type="deep_review", aggregate_type="deep_review", aggregate_id=review.id, status="queued", priority=0, max_attempts=1)
        session.add(job)
        session.flush()
        attempt.work_job_id = job.id
        for stage, sequence_number in STAGE_SEQUENCE.items():
            session.add(DeepReviewStage(id=uuid4(), attempt_id=attempt.id, stage=stage, sequence=sequence_number, status="queued", structured_output={}, invocation_metadata={}))
        review.current_attempt_id = attempt.id
        review.status = "queued"
        return attempt

    def create_review(self, session: Session, notice_id: int, bundle_id: UUID, actor: str | None, request_id: UUID) -> dict[str, Any]:
        claimed_name = _validate_actor(actor)
        request_hash = _idempotency_hash("deep_review_create", {"notice_id": notice_id, "bundle_id": str(bundle_id)})
        try:
            # Notice is the aggregate root for the immutable grade/bundle /
            # active profile/policy snapshot.  Lock it before replay lookup so
            # concurrent same-key requests cannot create two reviews.
            notice = session.scalar(select(Notice).where(Notice.id == notice_id).with_for_update())
            if notice is None:
                raise InputVersionError("not_found", "공고를 찾을 수 없습니다")
            approval_check = getattr(self.client, "require_notice_approval", None)
            if callable(approval_check):
                try:
                    approval_check(notice_id)
                except VllmInvocationError as error:
                    raise DeepReviewServiceError(
                        error.code,
                        "외부 분석 provider 사용 승인이 없습니다",
                        status_code=403,
                        request_id=request_id,
                    ) from error
            duplicate = self._idempotent_response(session, operation="deep_review_create", aggregate_type="notice", aggregate_id=str(notice_id), actor=claimed_name, request_id=request_id, request_hash=request_hash)
            if duplicate is not None:
                session.commit()
                return dict(duplicate)
            profile, policy = resolve_active_versions(
                session,
                allow_unmeasured_reference=self.reference_workflow_mode,
            )
            runtime_provider = str(getattr(self.client, "provider_name", "injected-analysis-client"))
            runtime_model = str(getattr(self.client, "model", policy.model_name))
            quality_snapshot = (
                {"status": "reference_workflow_unmeasured", "deployable": False}
                if self.reference_workflow_mode
                else policy_quality_snapshot(policy)
            )
            basis = effective_grade_basis(session, notice_id)
            if basis.grade != "우선 검토":
                raise DeepReviewServiceError("effective_grade_ineligible", "우선 검토 공고만 심층 분석할 수 있습니다", status_code=403, request_id=request_id)
            try:
                bundle, _structures = bundle_context(session, bundle_id, structure_loader=self.structure_loader)
            except InputVersionError as error:
                # Endpoint #8 has one approved not-ready contract.  Internal
                # structure/unsafe-snapshot diagnostics must not leak as an
                # unapproved processing error through the router mapping.
                if error.code in {"structure_unavailable", "unsafe_document"}:
                    raise InputVersionError("bundle_not_ready", "ready document bundle이 필요합니다") from error
                raise
            except DeepReviewValidationError as error:
                raise InputVersionError("bundle_not_ready", "ready document bundle이 필요합니다") from error
            if bundle["notice_id"] != notice_id:
                raise DeepReviewServiceError("not_found", "공고와 document bundle이 일치하지 않습니다", status_code=404, request_id=request_id)
            bundle_correlation_id = _audit_correlation_id(
                session,
                action="document_bundle.create",
                aggregate_type="document_bundle",
                aggregate_id=str(bundle_id),
            )
            # The unique input tuple is authoritative; existing review rows are
            # returned only when they are the same immutable input set.
            existing = session.scalar(select(DeepReview).where(
                DeepReview.notice_id == notice_id, DeepReview.bundle_id == bundle_id,
                DeepReview.profile_version_id == profile.id, DeepReview.policy_version_id == policy.id,
            ).limit(1))
            if existing is not None:
                creation = session.scalar(select(AuditEvent).where(
                    AuditEvent.action == "deep_review.create",
                    AuditEvent.aggregate_type == "deep_review",
                    AuditEvent.aggregate_id == str(existing.id),
                ).order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc()).limit(1))
                metadata = creation.safe_metadata if creation is not None and isinstance(creation.safe_metadata, Mapping) else {}
                if metadata.get("analysis_provider") not in {None, runtime_provider} or metadata.get("runtime_model") not in {None, runtime_model}:
                    raise DeepReviewServiceError(
                        "provider_context_conflict",
                        "같은 입력의 기존 review가 다른 분석 provider로 생성되었습니다",
                        status_code=409,
                        request_id=request_id,
                    )
                response = self.view(session, existing.id)
                session.add(IdempotencyRecord(operation="deep_review_create", aggregate_type="notice", aggregate_id=str(notice_id), claimed_name=claimed_name, request_id=request_id, request_sha256=request_hash, response_status=202, response_snapshot=response))
                session.commit()
                return response
            review = DeepReview(id=uuid4(), notice_id=notice_id, bundle_id=bundle_id, profile_version_id=profile.id, policy_version_id=policy.id, effective_grade_at_start=basis.grade or "unknown", status="queued", requested_by_name=claimed_name)
            session.add(review)
            session.flush()
            self._seed_attempt(session, review, sequence=1, actor=claimed_name)
            session.flush()
            response = self.view(session, review.id)
            session.add(IdempotencyRecord(operation="deep_review_create", aggregate_type="notice", aggregate_id=str(notice_id), claimed_name=claimed_name, request_id=request_id, request_sha256=request_hash, response_status=202, response_snapshot=response))
            session.add(AuditEvent(actor_kind="human", claimed_name=claimed_name, action="deep_review.create", aggregate_type="deep_review", aggregate_id=str(review.id), request_id=str(request_id), safe_metadata={
                "notice_id": notice_id, "bundle_id": str(bundle_id), "profile_version_id": str(profile.id), "profile_sha256": profile.profile_sha256,
                "policy_version_id": str(policy.id), "policy_sha256": policy.policy_sha256, "policy_model_name": policy.model_name,
                "analysis_provider": runtime_provider, "runtime_model": runtime_model,
                "external_provider_approved": runtime_provider == "codex-exec-reference",
                "policy_quality": quality_snapshot,
                "reference_workflow_mode": self.reference_workflow_mode,
                "effective_grade": basis.grade,
                "grade_source": basis.source, "source_run_id": basis.run_id, "source_review_id": basis.review_id,
                **(
                    {"correlation_id": str(bundle_correlation_id)}
                    if bundle_correlation_id is not None
                    else {}
                ),
            }))
            session.commit()
            return response
        except (DeepReviewServiceError, InputVersionError):
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            # PostgreSQL's immutable-input unique constraint is the final
            # race fence.  It is a normal replay/conflict, never an opaque 500.
            duplicate = self._idempotent_response(session, operation="deep_review_create", aggregate_type="notice", aggregate_id=str(notice_id), actor=claimed_name, request_id=request_id, request_hash=request_hash)
            if duplicate is not None:
                return dict(duplicate)
            raise DeepReviewServiceError("idempotency_conflict", "동시 요청으로 deep review가 이미 생성되었습니다", status_code=409, request_id=request_id) from exc

    def create_attempt(self, session: Session, review_id: UUID, actor: str | None, request_id: UUID) -> dict[str, Any]:
        claimed_name = _validate_actor(actor)
        request_hash = _idempotency_hash("deep_review_attempt", {"review_id": str(review_id)})
        try:
            # Lock the review aggregate before idempotency replay and active
            # attempt checks.  This makes same-review retries serializable.
            review = session.scalar(select(DeepReview).where(DeepReview.id == review_id).with_for_update())
            if review is None:
                raise DeepReviewServiceError("not_found", "deep review를 찾을 수 없습니다", status_code=404, request_id=request_id)
            duplicate = self._idempotent_response(session, operation="deep_review_attempt", aggregate_type="deep_review", aggregate_id=str(review_id), actor=claimed_name, request_id=request_id, request_hash=request_hash)
            if duplicate is not None:
                session.commit()
                return dict(duplicate)
            if review.current_attempt_id is None:
                raise DeepReviewServiceError("review_not_ready", "재시도할 current attempt가 없습니다", status_code=409, request_id=request_id)
            current = session.get(DeepReviewAttempt, review.current_attempt_id)
            if current is None or current.deep_review_id != review.id or current.status == "superseded":
                raise DeepReviewServiceError("review_not_ready", "재시도할 current attempt가 없습니다", status_code=409, request_id=request_id)
            active = session.scalar(select(DeepReviewAttempt).where(DeepReviewAttempt.deep_review_id == review.id, DeepReviewAttempt.status.in_(("queued", "running"))).order_by(DeepReviewAttempt.sequence.desc()).limit(1))
            if active is not None:
                raise DeepReviewServiceError("active_attempt_exists", "이미 실행 중인 attempt가 있습니다", status_code=409, request_id=request_id)
            if current.status not in {"failed", "completed"}:
                raise DeepReviewServiceError("review_not_ready", "실패 또는 완료된 current attempt만 재시도할 수 있습니다", status_code=409, request_id=request_id)
            correlation_id = _audit_correlation_id(
                session,
                action="deep_review.create",
                aggregate_type="deep_review",
                aggregate_id=str(review.id),
            )
            bundle_correlation_id = _audit_correlation_id(
                session,
                action="document_bundle.create",
                aggregate_type="document_bundle",
                aggregate_id=str(review.bundle_id),
            )
            if correlation_id != bundle_correlation_id:
                raise DeepReviewServiceError("processing_failed", "deep review 계보를 확인할 수 없습니다", status_code=500, request_id=request_id)
            max_sequence = session.scalar(select(DeepReviewAttempt.sequence).where(DeepReviewAttempt.deep_review_id == review.id).order_by(DeepReviewAttempt.sequence.desc()).limit(1)) or 0
            # Completed attempts are immutable snapshots.  A retry may move
            # the review pointer to a new attempt, but never rewrites a
            # completed attempt to ``superseded``; only failed attempts can be
            # superseded as part of retry bookkeeping.
            if current.status == "failed":
                current.status = "superseded"
            attempt = self._seed_attempt(session, review, sequence=int(max_sequence) + 1, actor=claimed_name)
            session.flush()
            response = self._attempt_view(session, attempt)
            session.add(IdempotencyRecord(operation="deep_review_attempt", aggregate_type="deep_review", aggregate_id=str(review_id), claimed_name=claimed_name, request_id=request_id, request_sha256=request_hash, response_status=202, response_snapshot=response))
            session.add(AuditEvent(actor_kind="human", claimed_name=claimed_name, action="deep_review.attempt", aggregate_type="deep_review", aggregate_id=str(review.id), request_id=str(request_id), safe_metadata={
                "attempt_id": str(attempt.id), "sequence": attempt.sequence,
                **({"correlation_id": str(correlation_id)} if correlation_id is not None else {}),
            }))
            session.commit()
        except DeepReviewServiceError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise DeepReviewServiceError("active_attempt_exists", "이미 실행 중인 attempt가 있습니다", status_code=409, request_id=request_id) from exc
        return response

    def claim_next_job(self, session: Session, worker_id: str) -> JobClaim | None:
        """Claim one job using a short PostgreSQL SKIP LOCKED transaction."""

        worker_id = _validate_worker_id(worker_id)
        now = self.clock()
        # End any read transaction before beginning the short claim transaction.
        if session.in_transaction():
            session.commit()
        job = session.scalar(
            select(WorkJob)
            .where(
                WorkJob.job_type == "deep_review",
                or_(WorkJob.status == "queued", and_(WorkJob.status == "running", WorkJob.lease_expires_at < now)),
            )
            .order_by(WorkJob.priority.desc(), WorkJob.scheduled_at.asc(), WorkJob.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            session.commit()
            return None
        # WorkJob.aggregate_id is the review; resolve the review's current
        # attempt while the row lock is held.
        review = session.get(DeepReview, job.aggregate_id)
        if review is None or review.current_attempt_id is None:
            job.status = "failed"
            job.last_error_code = "review_scope_missing"
            _add_job_audit(
                session, action="deep_review.job.failed", job_id=job.id,
                review_id=job.aggregate_id, attempt_id=None, fence=int(job.lease_fence), status="failed",
            )
            session.commit()
            return None
        attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
        if attempt is None or attempt.work_job_id != job.id:
            job.status = "failed"
            job.last_error_code = "attempt_scope_missing"
            _add_job_audit(
                session, action="deep_review.job.failed", job_id=job.id,
                review_id=review.id, attempt_id=attempt.id if attempt is not None else None,
                fence=int(job.lease_fence), status="failed",
            )
            session.commit()
            return None
        if job.status == "running":
            # Reclaim is a deterministic recovery boundary.  Completed
            # stages remain immutable; only the interrupted in-flight stage is
            # returned to the queue so the new owner can make progress.
            stages = self._stages(session, attempt.id)
            if all(stage.status == "completed" for stage in stages) and len(stages) == len(STAGES):
                attempt.status = "completed"
                review.status = "completed"
                review.completed_at = review.completed_at or now
                job.status = "completed"
                job.completed_at = job.completed_at or now
                job.lease_expires_at = None
                _add_job_audit(
                    session, action="deep_review.job.completed", job_id=job.id,
                    review_id=review.id, attempt_id=attempt.id, fence=int(job.lease_fence), status="completed",
                )
                session.commit()
                return None
            if attempt.status not in {"queued", "running"} or review.status not in {"queued", "running"}:
                job.status = "failed"
                job.last_error_code = "expired_attempt_not_active"
                job.lease_expires_at = None
                _add_job_audit(
                    session, action="deep_review.job.failed", job_id=job.id,
                    review_id=review.id, attempt_id=attempt.id, fence=int(job.lease_fence), status="failed",
                )
                session.commit()
                return None
            for stage in stages:
                if stage.status == "running":
                    stage.status = "queued"
                    stage.started_at = None
                    stage.completed_at = None
                    prior_metadata = stage.invocation_metadata if isinstance(stage.invocation_metadata, list) else []
                    stage.invocation_metadata = [*prior_metadata, {"status": "reclaimed", "safe": True}]
        fence = int(job.lease_fence) + 1
        job.status = "running"
        job.lease_owner = worker_id
        job.lease_fence = fence
        job.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
        job.attempt_count = int(job.attempt_count) + 1
        attempt.lease_fence = fence
        attempt.status = "running"
        attempt.started_at = attempt.started_at or now
        review.status = "running"
        _add_job_audit(
            session,
            action="deep_review.job.reclaim" if job.attempt_count > 1 else "deep_review.job.claim",
            job_id=job.id,
            review_id=review.id,
            attempt_id=attempt.id,
            fence=fence,
            status="running",
        )
        session.commit()
        return JobClaim(job.id, review.id, attempt.id, worker_id, fence)

    def _renew_lease(self, session: Session, claim: JobClaim) -> None:
        """Renew exactly the current owner/fence before every model call."""

        if session.in_transaction():
            session.rollback()
        row = session.execute(
            update(WorkJob)
            .where(
                WorkJob.id == claim.job_id,
                WorkJob.lease_owner == claim.worker_id,
                WorkJob.lease_fence == claim.fence,
                WorkJob.status == "running",
            )
            .values(lease_expires_at=self.clock() + timedelta(seconds=self.lease_seconds))
        ).rowcount
        if row != 1:
            session.rollback()
            raise StaleFenceError()
        session.commit()

    def _fence_exists(self, session: Session, claim: JobClaim) -> bool:
        return session.scalar(select(exists().where(
            WorkJob.id == claim.job_id, WorkJob.lease_owner == claim.worker_id,
            WorkJob.lease_fence == claim.fence, WorkJob.status == "running",
        ))) is True

    def _lock_claim(self, session: Session, claim: JobClaim) -> bool:
        """Hold the claimed job row lock across one short conditional write."""

        row = session.scalar(select(WorkJob).where(
            WorkJob.id == claim.job_id, WorkJob.lease_owner == claim.worker_id,
            WorkJob.lease_fence == claim.fence, WorkJob.status == "running",
        ).with_for_update())
        return row is not None

    @staticmethod
    def _requirements(bundle: Mapping[str, Any], structures: Mapping[str, Mapping[str, Any]], *, max_characters: int = 24000, max_requirements: int = 20) -> list[list[dict[str, Any]]]:
        """Build bounded page excerpts for stage 1.

        Extractor blocks are source structure, not one requirement each.  HWP
        tables can contain thousands of tiny cells, so treating every block as
        a model invocation row caused hundreds of calls for one notice.  Page
        excerpts keep every source character while retaining a resolvable page
        locator from which the model must quote an exact block substring.
        """

        requirements: list[dict[str, Any]] = []
        for document in sorted(bundle.get("documents", []), key=lambda item: (item.get("ordinal", 0), item.get("document_version_id", ""))):
            structure = structures.get(document.get("structure_id_at_confirmation"), {})
            blocks = structure.get("blocks", []) if isinstance(structure, Mapping) else []
            by_page: dict[int, list[tuple[int, Mapping[str, Any]]]] = {}
            for block_order, block in enumerate(blocks):
                if isinstance(block, Mapping) and isinstance(block.get("text"), str) and block["text"].strip():
                    page = int(block.get("page", 1)) if isinstance(block.get("page", 1), int) else 1
                    by_page.setdefault(page, []).append((block_order, block))

            excerpt_limit = min(max(max_characters // 2, 1000), 8000)
            for page, page_blocks in sorted(by_page.items()):
                excerpts: list[tuple[int, int, str]] = []
                current_parts: list[str] = []
                current_start = 0
                current_end = 0
                current_chars = 0

                def flush_excerpt() -> None:
                    nonlocal current_parts, current_start, current_end, current_chars
                    if current_parts:
                        excerpts.append((current_start, current_end, "\n".join(current_parts)))
                    current_parts, current_chars = [], 0

                for block_order, block in page_blocks:
                    text = str(block["text"])
                    parts = [text[start:start + excerpt_limit] for start in range(0, len(text), excerpt_limit)]
                    for part in parts:
                        separator_chars = 1 if current_parts else 0
                        if current_parts and current_chars + separator_chars + len(part) > excerpt_limit:
                            flush_excerpt()
                        if not current_parts:
                            current_start = block_order
                        current_parts.append(part)
                        current_end = block_order
                        current_chars += separator_chars + len(part)
                flush_excerpt()

                for excerpt_index, (start_order, end_order, text) in enumerate(excerpts):
                    identity = f"{page}:{start_order}:{end_order}:{excerpt_index}"
                    requirements.append({
                        "requirement_id": f"req-{int(document.get('ordinal', 0)):04d}-{page:04d}-{start_order:06d}-{hashlib.sha256(identity.encode()).hexdigest()[:10]}",
                        "document_version_id": str(document.get("document_version_id", "")),
                        "structure_id": str(document.get("structure_id_at_confirmation", "")),
                        "source_sha256": str(document.get("content_sha256") or structure.get("source_sha256") or ""),
                        "document_ordinal": int(document.get("ordinal", 0)), "page": page,
                        "block_order": start_order, "locator_type": "page",
                        "locator": {"page": page}, "text": text,
                    })
        if not requirements:
            requirements = [{"requirement_id": "req-unknown-0000", "document_ordinal": 0, "page": 1, "block_order": 0, "locator_type": "page", "locator": {"page": 1}, "text": ""}]
        slices: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_chars = 0
        for item in requirements:
            item_chars = len(str(item.get("text", ""))) + len(json.dumps({key: value for key, value in item.items() if key != "text"}, ensure_ascii=False))
            if current and (len(current) >= max_requirements or current_chars + item_chars > max_characters):
                slices.append(current)
                current, current_chars = [], 0
            current.append(item)
            current_chars += item_chars
        if current:
            slices.append(current)
        return slices

    @staticmethod
    def _bounded_rows(rows: Sequence[Mapping[str, Any]], *, max_characters: int = 24000, max_rows: int = 20) -> list[list[Mapping[str, Any]]]:
        groups: list[list[Mapping[str, Any]]] = []
        current: list[Mapping[str, Any]] = []
        current_chars = 0
        for row in rows:
            row_chars = len(json.dumps(row, ensure_ascii=False, sort_keys=True))
            if row_chars > max_characters:
                raise DeepReviewServiceError("processing_failed", "bounded input item이 허용 크기를 초과했습니다", status_code=500)
            if current and (len(current) >= max_rows or current_chars + row_chars > max_characters):
                groups.append(current)
                current, current_chars = [], 0
            current.append(row)
            current_chars += row_chars
        if current:
            groups.append(current)
        return groups or [[]]

    def _stage_slices(self, stage: str, bundle: Mapping[str, Any], structures: Mapping[str, Mapping[str, Any]], profile: Mapping[str, Any], previous: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        # ``max_characters`` is a source-row budget, not the prompt budget.
        # Leave room for the closed output contract, stage metadata, IDs, and
        # stage-2 profile rows so the actual built prompt remains <=24,000.
        # Stage 2 also carries one bounded company-profile slice.  Reserve a
        # larger share of the 24K prompt envelope for legitimate profile facts
        # (some evidence-backed portfolio rows exceed 2K by themselves).
        requirement_budget = 18000 if stage == STAGES[0] else 15000
        requirements = self._requirements(bundle, structures, max_characters=requirement_budget)
        if stage == STAGES[0]:
            return [{"slice_index": index, "requirements": rows} for index, rows in enumerate(requirements)]
        if stage == STAGES[1]:
            facts = [fact for fact in profile.get("facts", []) if isinstance(fact, Mapping)] if isinstance(profile.get("facts"), list) else []
            evidence = [row for row in profile.get("evidence", []) if isinstance(row, Mapping)] if isinstance(profile.get("evidence"), list) else []
            evidence_by_fact: dict[str, list[Mapping[str, Any]]] = {}
            for row in evidence:
                key = row.get("fact_key")
                if isinstance(key, str):
                    evidence_by_fact.setdefault(key, []).append(row)
            profile_rows = [
                {"fact": fact, "evidence": evidence_by_fact.get(str(fact.get("fact_key")), [])}
                for fact in facts
            ]
            if not profile_rows:
                profile_rows = [{"fact": {"fact_key": "profile.unknown", "status": "unknown", "value": None}, "evidence": []}]
            profile_slices = self._bounded_rows(profile_rows, max_characters=4000, max_rows=8)
            output: list[dict[str, Any]] = []
            count = max(len(requirements), len(profile_slices))
            for index in range(count):
                requirement_rows = requirements[index] if index < len(requirements) else []
                rows = profile_slices[index] if index < len(profile_slices) else []
                output.append({
                    "slice_index": index,
                    "requirements": requirement_rows,
                    "profile_facts": [row["fact"] for row in rows],
                    "profile_evidence": [item for row in rows for item in row["evidence"]],
                })
            return output
        claims = [claim for stage_output in previous for claim in stage_output.get("claims", []) if isinstance(claim, Mapping)]
        prior_evidence = [item for stage_output in previous for item in stage_output.get("evidence", []) if isinstance(item, Mapping)]
        evidence_by_id = {str(item.get("evidence_id")): item for item in prior_evidence if item.get("evidence_id")}
        # A prior evidence ref may support several claims.  Keep every claim
        # while emitting each referenced evidence row once across bounded
        # stage-3 slices; claim.evidence_ids still preserves the association.
        seen_evidence_ids: set[str] = set()
        claim_rows: list[dict[str, Any]] = []
        for claim in claims:
            rows: list[Mapping[str, Any]] = []
            for evidence_id in claim.get("evidence_ids", []):
                evidence_key = str(evidence_id)
                if evidence_key in evidence_by_id and evidence_key not in seen_evidence_ids:
                    rows.append(evidence_by_id[evidence_key])
                    seen_evidence_ids.add(evidence_key)
            claim_rows.append({"claim": claim, "evidence": rows})
        if not claim_rows:
            claim_rows = [{"claim": {"claim_id": str(EMPTY_PRIOR_CLAIM_ID), "claim_type": "unknown", "body": "앞 단계의 검증된 claim이 없습니다", "status": "unknown", "evidence_ids": [], "premise_claim_ids": [], "formula": None, "reason": "prior stage unavailable", "category": "analysis"}, "evidence": []}]
        slices = self._bounded_rows(claim_rows, max_characters=15000)
        return [
            {
                "slice_index": index,
                "verified_claims": [row["claim"] for row in rows],
                "prior_evidence": [item for row in rows for item in row["evidence"]],
            }
            for index, rows in enumerate(slices)
        ]

    @staticmethod
    def _contiguous_completed_prefix(
        stages: Sequence[DeepReviewStage],
        *,
        bundle: Mapping[str, Any],
        profile: Mapping[str, Any],
        profile_version_id: str,
        review_id: str,
        structures: Mapping[str, Mapping[str, Any]],
        session: Session | None = None,
        attempt_id: str | None = None,
    ) -> tuple[list[Mapping[str, Any]], set[str], set[str]]:
        """Validate and return the immutable completed-stage prefix.

        Reclaim can resume only at the first queued stage.  A completed stage
        after a queued/running one indicates corrupted/non-contiguous state;
        silently skipping it would let later stages consume an unvalidated
        prefix.  Validation also reconstructs the known claim/evidence IDs so
        resumed stages retain the same scope rules as the original owner.
        """

        ordered = sorted(stages, key=lambda stage: stage.sequence)
        if len(ordered) != len(STAGES) or [stage.stage for stage in ordered] != list(STAGES):
            raise DeepReviewServiceError("processing_failed", "stage sequence가 올바르지 않습니다", status_code=500)
        outputs: list[Mapping[str, Any]] = []
        known_claim_ids: set[str] = set()
        known_evidence_ids: set[str] = set()
        prefix_closed = False
        for index, stage in enumerate(ordered):
            if stage.status == "completed":
                if prefix_closed:
                    raise DeepReviewServiceError("processing_failed", "completed stage prefix가 연속적이지 않습니다", status_code=500)
                if not isinstance(stage.structured_output, Mapping):
                    raise DeepReviewServiceError("processing_failed", "completed stage output이 올바르지 않습니다", status_code=500)
                if output_attempt_id := stage.structured_output.get("attempt_id"):
                    if attempt_id is None or str(output_attempt_id) != str(attempt_id):
                        raise DeepReviewServiceError("processing_failed", "completed stage attempt scope가 올바르지 않습니다", status_code=500)
                else:
                    raise DeepReviewServiceError("processing_failed", "completed stage attempt scope가 없습니다", status_code=500)
                if stage.structured_output.get("stage") != stage.stage:
                    raise DeepReviewServiceError("processing_failed", "completed stage name이 DB stage와 다릅니다", status_code=500)
                try:
                    output = validate_deep_review_stage(
                        stage.structured_output,
                        bundle=bundle,
                        profile=profile,
                        profile_version_id=profile_version_id,
                        expected_deep_review_id=review_id,
                        known_claim_ids=known_claim_ids,
                        known_evidence_ids=known_evidence_ids,
                        structures=structures,
                    )
                except DeepReviewValidationError as exc:
                    raise DeepReviewServiceError("processing_failed", "completed stage output 검증에 실패했습니다", status_code=500) from exc
                if session is not None:
                    try:
                        review_uuid = UUID(str(review_id))
                    except (TypeError, ValueError) as exc:
                        raise DeepReviewServiceError("processing_failed", "completed stage review scope가 올바르지 않습니다", status_code=500) from exc
                    output_claim_ids = {
                        str(item["claim_id"])
                        for item in output.get("claims", [])
                        if isinstance(item, Mapping) and item.get("claim_id")
                    }
                    db_claim_ids = {
                        str(value)
                        for value in session.scalars(select(Claim.id).where(
                            Claim.deep_review_id == review_uuid,
                            Claim.stage_id == stage.id,
                            Claim.id.in_([UUID(value) for value in output_claim_ids]),
                        )).all()
                    } if output_claim_ids else set()
                    if db_claim_ids != output_claim_ids:
                        raise DeepReviewServiceError("processing_failed", "completed stage claim projection이 일치하지 않습니다", status_code=500)
                    output_evidence_ids = {
                        str(item["evidence_id"])
                        for item in output.get("evidence", [])
                        if isinstance(item, Mapping) and item.get("evidence_id")
                    }
                    db_evidence_ids = {
                        str(value)
                        for value in session.scalars(select(EvidenceRef.id).where(
                            EvidenceRef.deep_review_id == review_uuid,
                            EvidenceRef.id.in_([UUID(value) for value in output_evidence_ids]),
                        )).all()
                    } if output_evidence_ids else set()
                    if db_evidence_ids != output_evidence_ids:
                        raise DeepReviewServiceError("processing_failed", "completed stage evidence projection이 일치하지 않습니다", status_code=500)
                outputs.append(deepcopy(output))
                known_claim_ids.update(str(item["claim_id"]) for item in output.get("claims", []) if isinstance(item, Mapping) and item.get("claim_id"))
                known_evidence_ids.update(str(item["evidence_id"]) for item in output.get("evidence", []) if isinstance(item, Mapping) and item.get("evidence_id"))
                continue
            if stage.status != "queued":
                raise DeepReviewServiceError("processing_failed", "재개할 stage 상태가 올바르지 않습니다", status_code=500)
            prefix_closed = True
        return outputs, known_claim_ids, known_evidence_ids

    @staticmethod
    def _raw_aggregate_bytes(raw_records: Sequence[tuple[InvocationResult, Mapping[str, Any]]]) -> bytes:
        """Build one deterministic stage object with response bytes and hashes."""

        responses: list[dict[str, Any]] = []
        ordered_records = sorted(
            enumerate(raw_records),
            key=lambda item: (item[1][1].get("slice_index", item[0]) if isinstance(item[1][1], Mapping) else item[0], item[0]),
        )
        for fallback_index, (_source_index, (result, metadata)) in enumerate(ordered_records):
            try:
                raw_text = result.raw_response.decode("utf-8")
            except (AttributeError, UnicodeDecodeError) as exc:
                raise DeepReviewServiceError("processing_failed", "model raw response가 UTF-8 JSON이 아닙니다", status_code=500) from exc
            slice_index = metadata.get("slice_index", fallback_index) if isinstance(metadata, Mapping) else fallback_index
            responses.append({"slice_index": slice_index, "response_sha256": hashlib.sha256(result.raw_response).hexdigest(), "raw_response": raw_text})
        return json.dumps({"schema": "bidops.model-response-aggregate.v1", "responses": responses}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _validate_raw_store_metadata(metadata: Mapping[str, Any], aggregate: bytes) -> dict[str, Any]:
        """Validate injected storage metadata before a DB transaction starts."""

        if any(alias in metadata for alias in ("key", "plaintext_sha", "sha256", "plaintext_size", "size_bytes")):
            raise DeepReviewServiceError("service_unavailable", "model raw response 저장소 metadata 필드가 올바르지 않습니다", status_code=503)
        if metadata.get("encrypted") is not True or not isinstance(metadata.get("encrypted"), bool):
            raise DeepReviewServiceError("service_unavailable", "model raw response 저장소가 암호화를 보장하지 않습니다", status_code=503)
        object_key = metadata.get("object_key")
        if not isinstance(object_key, str) or not object_key.startswith("model-response/") or not object_key.strip() or object_key != object_key.strip() or any(ord(char) < 32 or ord(char) == 127 for char in object_key) or "\\" in object_key or object_key.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[/\\]", object_key) or ".." in object_key.split("/"):
            raise DeepReviewServiceError("service_unavailable", "model raw response object locator가 안전하지 않습니다", status_code=503)
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", object_key) or re.search(r"(?:credential|secret|password|api[_-]?key|token|authorization|cookie)", object_key, re.I):
            raise DeepReviewServiceError("service_unavailable", "model raw response object locator가 안전하지 않습니다", status_code=503)
        digest = hashlib.sha256(aggregate).hexdigest()
        returned_digest = metadata.get("plaintext_sha256")
        returned_size = metadata.get("plaintext_size_bytes")
        key_ref = metadata.get("encryption_key_ref")
        if (
            not isinstance(returned_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", returned_digest)
            or not isinstance(returned_size, int)
            or isinstance(returned_size, bool)
            or not isinstance(key_ref, str)
            or not key_ref.strip()
            or key_ref != key_ref.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in key_ref)
            or "\\" in key_ref
            or key_ref.startswith(("/", "~"))
            or ".." in key_ref.split("/")
            or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", key_ref)
            or re.search(r"(?:credential|secret|password|token|api[_-]?key|authorization|cookie)", key_ref, re.I)
            or returned_digest != digest
            or returned_size != len(aggregate)
        ):
            raise DeepReviewServiceError("service_unavailable", "model raw response 저장소 plaintext metadata가 일치하지 않습니다", status_code=503)
        object_version_id = metadata.get("object_version_id")
        etag = metadata.get("etag")
        if object_version_id is not None and (not isinstance(object_version_id, str) or not object_version_id.strip()):
            raise DeepReviewServiceError("service_unavailable", "model raw response object version metadata가 올바르지 않습니다", status_code=503)
        if etag is not None and (not isinstance(etag, str) or not etag.strip()):
            raise DeepReviewServiceError("service_unavailable", "model raw response object etag metadata가 올바르지 않습니다", status_code=503)
        return {
            "object_key": object_key,
            "object_version_id": object_version_id,
            "etag": etag,
            "encrypted": True,
            "plaintext_sha256": digest,
            "plaintext_size_bytes": len(aggregate),
            "encryption_key_ref": key_ref,
        }

    def _store_raw_aggregate(self, raw_records: Sequence[tuple[InvocationResult, Mapping[str, Any]]]) -> tuple[bytes, Mapping[str, Any]]:
        aggregate = self._raw_aggregate_bytes(raw_records)
        try:
            retention_days = int(os.environ.get("BIDOPS_MODEL_RESPONSE_RETENTION_DAYS", "90"))
        except (TypeError, ValueError):
            retention_days = 90
        retention_days = min(max(retention_days, 1), 90)
        try:
            metadata = self.raw_response_store.put_encrypted(aggregate, retention_days=retention_days, content_type="application/json")
        except DeepReviewServiceError:
            raise
        except Exception as exc:
            raise DeepReviewServiceError("service_unavailable", "암호화 model-response 저장소를 사용할 수 없습니다", status_code=503) from exc
        if not isinstance(metadata, Mapping):
            raise DeepReviewServiceError("service_unavailable", "model raw response 저장소 metadata가 올바르지 않습니다", status_code=503)
        return aggregate, self._validate_raw_store_metadata(metadata, aggregate)

    def _raw_content_row(self, session: Session, aggregate: bytes, metadata: Mapping[str, Any]) -> ContentObject:
        digest = hashlib.sha256(aggregate).hexdigest()
        content = session.scalar(select(ContentObject).where(ContentObject.sha256 == digest).limit(1))
        object_key = str(metadata["object_key"])
        key_ref = str(metadata["encryption_key_ref"])
        object_version_id = metadata.get("object_version_id")
        object_etag = str(metadata.get("etag") or digest)
        # Object keys are globally unique within the model-response namespace.
        # Reusing one is safe only when the existing location is a verified
        # pointer to the exact bytes and encryption key; otherwise fail closed.
        location = session.scalar(select(ContentObjectLocation).where(
            ContentObjectLocation.namespace_key == "model-response",
            ContentObjectLocation.object_key == object_key,
        ).limit(1))
        if location is not None:
            linked_content = session.get(ContentObject, location.content_object_id)
            if (
                linked_content is None
                or linked_content.sha256 != digest
                or linked_content.size_bytes != len(aggregate)
                or content is not None and linked_content.id != content.id
                or location.status != "verified"
                or location.etag != object_etag
                or location.object_version_id != object_version_id
                or location.encryption_key_ref != key_ref
            ):
                raise DeepReviewServiceError("service_unavailable", "model raw response object location metadata가 일치하지 않습니다", status_code=503)
            return linked_content
        if content is None:
            content = ContentObject(id=uuid4(), sha256=digest, size_bytes=len(aggregate), detected_mime="application/json", retention_class="model-response-90d")
            session.add(content)
            session.flush()
        elif content.size_bytes != len(aggregate):
            raise DeepReviewServiceError("service_unavailable", "model raw response aggregate size가 일치하지 않습니다", status_code=503)
        session.add(ContentObjectLocation(
            id=uuid4(), content_object_id=content.id, namespace_key="model-response",
            object_key=object_key, object_version_id=object_version_id, status="verified", etag=object_etag,
            encryption_key_ref=key_ref, verified_at=self.clock(),
        ))
        return content

    def _persist_stage(
        self,
        session: Session,
        claim: JobClaim,
        stage: DeepReviewStage,
        merged: Mapping[str, Any],
        invocation_metadata: Any,
        raw_aggregate: tuple[bytes, Mapping[str, Any]] | None = None,
    ) -> None:
        if not self._lock_claim(session, claim):
            raise StaleFenceError()
        # The external encrypted object is written before this method, but its
        # DB ContentObject/Location metadata is created only after the fence
        # lock and inside this short transaction.  A stale worker therefore
        # cannot attach raw-response metadata to a new lease.
        raw_content = None
        if raw_aggregate is not None:
            raw_content = self._raw_content_row(session, raw_aggregate[0], raw_aggregate[1])
        values = {"status": "completed", "structured_output": dict(merged), "invocation_metadata": invocation_metadata, "completed_at": self.clock(), "raw_response_content_object_id": raw_content.id if raw_content else None}
        row = session.execute(update(DeepReviewStage).where(
            DeepReviewStage.id == stage.id, DeepReviewStage.attempt_id == claim.attempt_id,
            DeepReviewStage.status == "running",
            exists().where(WorkJob.id == claim.job_id, WorkJob.lease_owner == claim.worker_id, WorkJob.lease_fence == claim.fence, WorkJob.status == "running"),
        ).values(**values)).rowcount
        if row != 1:
            session.rollback()
            raise StaleFenceError()
        existing_claim_ids = {str(value) for value in session.scalars(select(Claim.id).where(Claim.deep_review_id == claim.deep_review_id)).all()}
        existing_evidence_ids = {str(value) for value in session.scalars(select(EvidenceRef.id).where(EvidenceRef.deep_review_id == claim.deep_review_id)).all()}
        for evidence in merged.get("evidence", []):
            evidence_id = UUID(str(evidence["evidence_id"]))
            if str(evidence_id) in existing_evidence_ids:
                continue
            source_kind = evidence["source_kind"]
            session.add(EvidenceRef(
                id=evidence_id, deep_review_id=claim.deep_review_id, source_kind=source_kind,
                notice_id=session.get(DeepReview, claim.deep_review_id).notice_id,
                bundle_id=UUID(str(merged.get("bundle_id"))) if source_kind == "document" and merged.get("bundle_id") else (session.get(DeepReview, claim.deep_review_id).bundle_id if source_kind == "document" else None),
                document_version_id=UUID(str(evidence["document_version_id"])) if evidence.get("document_version_id") else None,
                structure_id=UUID(str(evidence["structure_id"])) if evidence.get("structure_id") else None,
                profile_version_id=UUID(str(evidence["profile_version_id"])) if evidence.get("profile_version_id") else None,
                profile_evidence_id=UUID(str(evidence["profile_evidence_id"])) if evidence.get("profile_evidence_id") else None,
                locator_type=evidence["locator_type"], locator=evidence["locator"], quote=evidence["quote"], confidence=evidence.get("confidence"), source_sha256=evidence["source_sha256"],
            ))
            existing_evidence_ids.add(str(evidence_id))
        session.flush()
        for payload in merged.get("claims", []):
            claim_id = UUID(str(payload["claim_id"]))
            if str(claim_id) in existing_claim_ids:
                raise DeepReviewServiceError("processing_failed", "stage claim ID가 여러 stage에서 재사용되었습니다", status_code=500)
            session.add(Claim(id=claim_id, deep_review_id=claim.deep_review_id, stage_id=stage.id, category=payload["category"], claim_type=payload["claim_type"], body=payload["body"], status=payload["status"], formula=payload.get("formula"), premise_claim_ids=payload.get("premise_claim_ids", []), reason=payload.get("reason")))
            for ordinal, evidence_id in enumerate(payload.get("evidence_ids", [])):
                session.add(ClaimEvidence(deep_review_id=claim.deep_review_id, claim_id=claim_id, evidence_ref_id=UUID(str(evidence_id)), ordinal=ordinal))
            existing_claim_ids.add(str(claim_id))
        session.commit()

    def _mark_running(self, session: Session, claim: JobClaim, stage: DeepReviewStage) -> None:
        if not self._lock_claim(session, claim):
            raise StaleFenceError()
        row = session.execute(update(DeepReviewStage).where(DeepReviewStage.id == stage.id, DeepReviewStage.attempt_id == claim.attempt_id, DeepReviewStage.status == "queued", exists().where(WorkJob.id == claim.job_id, WorkJob.lease_owner == claim.worker_id, WorkJob.lease_fence == claim.fence, WorkJob.status == "running")).values(status="running", started_at=stage.started_at or self.clock())).rowcount
        if row != 1:
            raise StaleFenceError()
        session.commit()

    def _fail_claim(self, session: Session, claim: JobClaim, stage: DeepReviewStage | None, code: str, invocation_metadata: Sequence[Mapping[str, Any]] = ()) -> None:
        session.rollback()
        metadata = [_safe_invocation_metadata(item) for item in invocation_metadata]
        metadata.append({"status": "failed", "error_code": code, "safe": True})
        # Failure follows the same fence protocol as success: verify and lock
        # the running job first, update stage/attempt/review, then transition
        # the job last.  Every conditional UPDATE is a one-row assertion.
        if not self._lock_claim(session, claim):
            session.rollback()
            raise StaleFenceError()
        if stage is not None:
            current_stage = session.scalar(select(DeepReviewStage).where(DeepReviewStage.id == stage.id, DeepReviewStage.attempt_id == claim.attempt_id).with_for_update())
            if current_stage is None:
                session.rollback()
                raise StaleFenceError()
            if current_stage.status in {"queued", "running"}:
                stage_count = session.execute(update(DeepReviewStage).where(DeepReviewStage.id == stage.id, DeepReviewStage.attempt_id == claim.attempt_id, DeepReviewStage.status.in_(("queued", "running"))).values(status="failed", invocation_metadata=metadata, completed_at=self.clock())).rowcount
                if stage_count != 1:
                    session.rollback()
                    raise StaleFenceError()
            # A completed stage is immutable.  A genuine later failure still
            # fences and fails the attempt/review/job below.
        attempt_count = session.execute(update(DeepReviewAttempt).where(DeepReviewAttempt.id == claim.attempt_id, DeepReviewAttempt.lease_fence == claim.fence, DeepReviewAttempt.status == "running").values(status="failed", completed_at=self.clock())).rowcount
        if attempt_count != 1:
            session.rollback()
            raise StaleFenceError()
        review_count = session.execute(update(DeepReview).where(DeepReview.id == claim.deep_review_id, DeepReview.current_attempt_id == claim.attempt_id, DeepReview.status == "running").values(status="failed", completed_at=self.clock())).rowcount
        if review_count != 1:
            session.rollback()
            raise StaleFenceError()
        job_count = session.execute(update(WorkJob).where(WorkJob.id == claim.job_id, WorkJob.lease_owner == claim.worker_id, WorkJob.lease_fence == claim.fence, WorkJob.status == "running").values(status="failed", last_error_code=code, completed_at=self.clock(), lease_expires_at=None)).rowcount
        if job_count != 1:
            session.rollback()
            raise StaleFenceError()
        _add_job_audit(
            session, action="deep_review.job.failed", job_id=claim.job_id,
            review_id=claim.deep_review_id, attempt_id=claim.attempt_id,
            fence=claim.fence, status="failed",
        )
        session.commit()

    def _finish_claim(self, session: Session, claim: JobClaim) -> None:
        now = self.clock()
        if not self._lock_claim(session, claim):
            raise StaleFenceError()
        stage_count = session.query(DeepReviewStage).filter(DeepReviewStage.attempt_id == claim.attempt_id, DeepReviewStage.status == "completed").count()
        if stage_count != len(STAGES) or session.scalar(select(DeepReviewStage.id).where(DeepReviewStage.attempt_id == claim.attempt_id, DeepReviewStage.status != "completed").limit(1)) is not None:
            session.rollback()
            raise StaleFenceError()
        attempt_count = session.execute(update(DeepReviewAttempt).where(DeepReviewAttempt.id == claim.attempt_id, DeepReviewAttempt.deep_review_id == claim.deep_review_id, DeepReviewAttempt.lease_fence == claim.fence, DeepReviewAttempt.status == "running").values(status="completed", completed_at=now)).rowcount
        review_count = session.execute(update(DeepReview).where(DeepReview.id == claim.deep_review_id, DeepReview.current_attempt_id == claim.attempt_id, DeepReview.status == "running").values(status="completed", completed_at=now)).rowcount
        job_count = session.execute(update(WorkJob).where(WorkJob.id == claim.job_id, WorkJob.lease_owner == claim.worker_id, WorkJob.lease_fence == claim.fence, WorkJob.status == "running").values(status="completed", completed_at=now, lease_expires_at=None)).rowcount
        if attempt_count != 1 or review_count != 1 or job_count != 1:
            session.rollback()
            raise StaleFenceError()
        _add_job_audit(
            session, action="deep_review.job.completed", job_id=claim.job_id,
            review_id=claim.deep_review_id, attempt_id=claim.attempt_id,
            fence=claim.fence, status="completed",
        )
        session.commit()

    def run_claim(self, session: Session, claim: JobClaim) -> None:
        """Execute the three ordered business stages without an open I/O transaction."""

        stage_row: DeepReviewStage | None = None
        previous_outputs: list[Mapping[str, Any]] = []
        try:
            review = session.get(DeepReview, claim.deep_review_id)
            attempt = session.get(DeepReviewAttempt, claim.attempt_id)
            if review is None or attempt is None or attempt.lease_fence != claim.fence:
                raise StaleFenceError()
            profile = session.get(ProfileVersion, review.profile_version_id)
            policy = session.get(AnalysisPolicyVersion, review.policy_version_id)
            if profile is None or policy is None:
                raise DeepReviewServiceError("service_unavailable", "고정된 profile 또는 policy가 없습니다", status_code=503)
            validate_pinned_policy(policy, allow_unmeasured_reference=self.reference_workflow_mode)
            creation_audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "deep_review.create", AuditEvent.aggregate_type == "deep_review", AuditEvent.aggregate_id == str(review.id)).order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc()).limit(1))
            audit_snapshot = creation_audit.safe_metadata if creation_audit is not None and isinstance(creation_audit.safe_metadata, Mapping) else None
            if audit_snapshot is None:
                raise DeepReviewServiceError("service_unavailable", "deep review 입력 snapshot이 없습니다", status_code=503)
            if (
                audit_snapshot.get("profile_version_id") != str(profile.id)
                or audit_snapshot.get("profile_sha256") != profile.profile_sha256
                or audit_snapshot.get("policy_version_id") != str(policy.id)
                or audit_snapshot.get("policy_sha256") != policy.policy_sha256
                or audit_snapshot.get("policy_model_name") != policy.model_name
                or audit_snapshot.get("policy_quality") != (
                    {"status": "reference_workflow_unmeasured", "deployable": False}
                    if self.reference_workflow_mode
                    else policy_quality_snapshot(policy)
                )
                or bool(audit_snapshot.get("reference_workflow_mode", False)) != self.reference_workflow_mode
                or audit_snapshot.get("analysis_provider") not in {
                    None, str(getattr(self.client, "provider_name", "injected-analysis-client")),
                }
                or audit_snapshot.get("runtime_model") not in {
                    None, str(getattr(self.client, "model", policy.model_name)),
                }
            ):
                raise DeepReviewServiceError("service_unavailable", "pinned deep review 입력이 변경되었습니다", status_code=503)
            approval_check = getattr(self.client, "require_notice_approval", None)
            if callable(approval_check):
                try:
                    approval_check(review.notice_id)
                except VllmInvocationError as error:
                    raise DeepReviewServiceError(error.code, "외부 분석 provider 사용 승인이 없습니다", status_code=403) from error
            bundle, structures = bundle_context(session, review.bundle_id, structure_loader=self.structure_loader)
            profile_payload = profile_context(session, profile)
            policy_payload = _policy_payload(policy)
            # Commit plain deep-copied snapshots before any model I/O.  The
            # worker never rereads live projections while a review is running.
            bundle = deepcopy(bundle)
            structures = deepcopy(structures)
            profile_payload = deepcopy(profile_payload)
            policy_payload = deepcopy(policy_payload)
            prefix_outputs, prefix_claim_ids, prefix_evidence_ids = self._contiguous_completed_prefix(
                self._stages(session, claim.attempt_id), bundle=bundle, profile=profile_payload,
                profile_version_id=str(profile.id), review_id=str(review.id), structures=structures,
                session=session, attempt_id=str(claim.attempt_id),
            )
            review_id = review.id
            pinned_notice_id = review.notice_id
            attempt_id = attempt.id
            pinned_profile_id = str(profile.id)
            pinned_profile_sha256 = str(profile.profile_sha256)
            pinned_policy_sha256 = str(policy.policy_sha256)
            pinned_model_name = str(policy.model_name)
            session.commit()
            previous_outputs: list[Mapping[str, Any]] = prefix_outputs
            known_claim_ids: set[str] = prefix_claim_ids
            known_evidence_ids: set[str] = prefix_evidence_ids
            for stage_name in STAGES:
                stage_invocations: list[Mapping[str, Any]] = []
                stage_row = session.scalar(select(DeepReviewStage).where(DeepReviewStage.attempt_id == claim.attempt_id, DeepReviewStage.stage == stage_name).limit(1))
                if stage_row is None:
                    raise DeepReviewServiceError("processing_failed", "stage row가 없습니다", status_code=500)
                if stage_row.status == "completed":
                    # Reclaimed workers resume after immutable completed
                    # stages.  Keep their validated output as the prior-stage
                    # input for the next stage.
                    continue
                if stage_row.status != "queued":
                    raise DeepReviewServiceError("processing_failed", "stage 상태 전이가 올바르지 않습니다", status_code=500)
                self._mark_running(session, claim, stage_row)
                slices = self._stage_slices(stage_name, bundle, structures, profile_payload, previous_outputs)
                chunks: list[Mapping[str, Any]] = []
                invocation_metadata: list[dict[str, Any]] = []
                raw_records: list[tuple[InvocationResult, Mapping[str, Any]]] = []
                for slice_index, input_slice in enumerate(slices):
                    invocation_input = {
                        **input_slice,
                        "notice_id": pinned_notice_id,
                        "deep_review_id": str(review_id),
                        "attempt_id": str(attempt_id),
                        "stage": stage_name,
                    }
                    try:
                        self._renew_lease(session, claim)
                        result = self.client.invoke(
                            stage_name,
                            invocation_input,
                            policy_payload,
                            profile={"profile_version_id": pinned_profile_id, "profile_sha256": pinned_profile_sha256} if stage_name == STAGES[1] else None,
                            prior_stages=(),
                        )
                        chunk_output = _resolve_exact_evidence_quotes(result.structured_output, structures)
                        # Validate each untrusted chunk before paying for the
                        # next provider call.  The final merge repeats this
                        # check and adds cross-chunk duplicate/conflict rules.
                        # Same-chunk premise/evidence IDs are in scope; future
                        # chunks are deliberately not, so output cannot depend
                        # on model results that do not exist yet.
                        chunk_claim_ids = {
                            str(item.get("claim_id"))
                            for item in chunk_output.get("claims", [])
                            if isinstance(item, Mapping) and item.get("claim_id")
                        }
                        chunk_evidence_ids = {
                            str(item.get("evidence_id"))
                            for item in chunk_output.get("evidence", [])
                            if isinstance(item, Mapping) and item.get("evidence_id")
                        }
                        validate_deep_review_stage(
                            chunk_output,
                            bundle=bundle,
                            profile=profile_payload,
                            profile_version_id=pinned_profile_id,
                            expected_deep_review_id=str(review_id),
                            known_claim_ids=known_claim_ids | chunk_claim_ids,
                            known_evidence_ids=known_evidence_ids | chunk_evidence_ids,
                            structures=structures,
                        )
                        # Raw responses are persisted as one stage aggregate
                        # only after every invocation in this stage succeeds.
                        raw_records.append((result, {"slice_index": slice_index}))
                        safe_attempts = [_safe_invocation_attempt(item) for item in result.attempts]
                        invocation_metadata.append({
                            "slice_index": slice_index, "input_slice_sha256": _canonical_hash(invocation_input), "prompt_sha256": result.input_sha256,
                            "response_sha256": hashlib.sha256(result.raw_response).hexdigest(),
                            "provider": result.provider or str(getattr(self.client, "provider_name", "unknown")),
                            "model": result.model or pinned_model_name,
                            "policy_sha256": pinned_policy_sha256, "prompt_tokens": result.prompt_tokens,
                            "output_tokens": result.output_tokens, "latency_ms": result.latency_ms,
                            "status": "succeeded", "attempts": safe_attempts,
                        })
                        stage_invocations.extend(safe_attempts)
                        chunks.append(chunk_output)
                    except VllmInvocationError as error:
                        safe_attempts = [_safe_invocation_attempt(item) for item in error.attempts]
                        invocation_metadata.extend({"slice_index": slice_index, "input_slice_sha256": _canonical_hash(invocation_input), **item} for item in safe_attempts)
                        stage_invocations.extend({"slice_index": slice_index, "input_slice_sha256": _canonical_hash(invocation_input), **item} for item in safe_attempts)
                        raise DeepReviewServiceError(error.code, "승인된 model invocation이 실패했습니다", status_code=503)
                chunk_orders = {
                    id(chunk): (
                        STAGE_SEQUENCE[stage_name],
                        input_slice.get("requirements", [{}])[0].get("document_ordinal", 0) if input_slice.get("requirements") else 0,
                        input_slice.get("requirements", [{}])[0].get("page", 0) if input_slice.get("requirements") else 0,
                        input_slice.get("requirements", [{}])[0].get("block_order", 0) if input_slice.get("requirements") else 0,
                        input_slice.get("requirements", [{}])[0].get("requirement_id", "") if input_slice.get("requirements") else "",
                        input_slice.get("slice_index", 0),
                    )
                    for input_slice, chunk in zip(slices, chunks)
                }
                merged = merge_stage_chunks(chunks, bundle=bundle, profile=profile_payload, profile_version_id=pinned_profile_id, expected_deep_review_id=str(review_id), known_claim_ids=known_claim_ids, known_evidence_ids=known_evidence_ids, structures=structures, chunk_order_key=lambda chunk: chunk_orders.get(id(chunk), (STAGE_SEQUENCE[stage_name], 0, 0, 0, "", 0)))
                known_claim_ids.update(item["claim_id"] for item in merged.get("claims", []))
                known_evidence_ids.update(item["evidence_id"] for item in merged.get("evidence", []))
                invocation_doc = sorted(invocation_metadata, key=lambda item: (item.get("slice_index", 0), item.get("retry_index", 0)))
                if invocation_doc:
                    invocation_doc[0] = {
                        **invocation_doc[0],
                        "fixed_input_hash": _canonical_hash({"bundle": bundle, "profile_sha256": pinned_profile_sha256 if stage_name == STAGES[1] else None, "policy_sha256": pinned_policy_sha256, "stage": stage_name}),
                    }
                raw_aggregate = self._store_raw_aggregate(raw_records)
                self._persist_stage(session, claim, stage_row, merged, invocation_doc, raw_aggregate=raw_aggregate)
                previous_outputs.append(merged)
            # Report materialization and the terminal fence transition share
            # one transaction.  The materializer locks the pinned stage rows
            # and creates immutable report/validation/evidence/audit records;
            # _finish_claim then verifies the same lease before committing.
            from .reports import ReportService, ReportServiceError
            report_service = self.report_service
            if report_service is None:
                report_service = ReportService()
            try:
                report_service.materialize_machine_report(session, claim)
            except ReportServiceError as error:
                safe_code = "validation_failed" if error.code == "validation_failed" else "processing_failed"
                raise DeepReviewServiceError(safe_code, "machine report materialization failed", status_code=500) from error
            self._finish_claim(session, claim)
        except StaleFenceError:
            session.rollback()
            raise
        except DeepReviewValidationError as error:
            # Persist stable validator codes only.  Messages, quotes, locators,
            # and model content remain outside DB/audit failure metadata.
            diagnostics = tuple(
                {"status": "failed", "error_code": f"validation:{issue.code}"}
                for issue in error.issues[:20]
            )
            observations = tuple(stage_invocations if "stage_invocations" in locals() else ()) + diagnostics
            self._fail_claim(session, claim, stage_row, "validation_failed", observations)
            raise DeepReviewServiceError("processing_failed", "model 결과가 권위 schema를 통과하지 못했습니다", status_code=500)
        except DeepReviewServiceError as error:
            self._fail_claim(session, claim, stage_row, error.code, stage_invocations if "stage_invocations" in locals() else ())
            raise
        except Exception as error:
            self._fail_claim(session, claim, stage_row, "processing_failed")
            raise DeepReviewServiceError("processing_failed", "deep review 실행에 실패했습니다", status_code=500) from error


__all__ = ["DeepReviewError", "DeepReviewService", "DeepReviewServiceError", "JobClaim", "StaleFenceError"]
