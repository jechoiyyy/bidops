"""The bounded v4 page-overview model slot.

This runner consumes only the immutable v4 target manifest.  It never reads a
source object, touches the legacy recommendation tables, or starts deep
review.  A successful call appends the existing page-v3 result row; every
other outcome closes one attempt with a safe reason code and, when available,
an encrypted raw-response reference.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.model_client import (
    APPROVED_GENERATION,
    ModelClient,
    ModelEndpointError,
    ModelIdentityCheckState,
    ModelIdentityError,
    ModelInvocationError,
    RUNTIME_IDENTITY_ERROR_CODES,
    model_endpoint_configuration_fingerprint,
    model_identity_cache_key,
    resolve_model_endpoint,
    structured_request_capacity,
    StructuredOutputContract,
)
from ...core.models import AuditEvent
from ...core.object_store import EncryptedModelResponseStore, ObjectStore, ObjectStoreError
from ..models import (
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentVersion,
    PreSpecPageOverview,
    PrespecV4Attempt,
    PrespecV4PdfSnapshot,
    PrespecV4Target,
    PrespecOverviewCallEvent,
    PrespecOverviewVerification,
    PreSpecOverviewAttempt,
    PreSpecOverviewSnapshot,
    WorkJob,
)
from ..schemas.page_overview import PageOverviewPayload, PageOverviewPayloadV4
from .model_response_storage import store_raw_model_response
from .page_overview_validation import VALIDATOR_VERSION, validate_page_overview, validate_page_overview_detailed
from .prespec_overview_claim_policy import (
    CLAIMS_STAGE,
    ClaimsOverviewPolicy,
    LIMITS,
    SEMANTIC_STAGE,
    build_claims_prompt,
    build_claims_stage_input,
    canonical_sha256,
    load_claims_policy,
)
from .prespec_overview_claim_validation import (
    ClaimDraftError,
    SemanticResponseError,
    apply_semantic_review,
    build_input_limitations,
    compose_page_overview,
    draft_failure_checks,
    parse_claims_draft,
    validate_claims_deterministically,
    validate_composed_page_overview,
)
from .prespec_v4_gate import lock_v4_gate
from .prespec_v4 import (
    MAX_V4_MANIFEST_BYTES,
    V4_MANIFEST_SCHEMA,
    V4PreparationError,
    _canonical,
    _latest_clean_scan,
    _read_verified_artifact,
    _verified_location,
)


V4_STAGE = "prespec_overview"
V4_PROMPT_VERSION = "prespec-overview-v4"
V4_POLICY_SCHEMA = "bidops.prespec-overview-policy.v4"
V4_LEASE_SECONDS = 1_200
V4_DISPATCH_RESERVE_SECONDS = 360
# Historical Luna/reference readers import V4_POLICY_PATH directly and bind
# its bytes into their provenance.  Keep that public constant immutable while
# the operational runner defaults to the new claims policy.
V4_POLICY_PATH = Path(__file__).resolve().parent.parent / "policies" / "prespec-overview-policy-v4.json"
V4_LEGACY_POLICY_PATH = V4_POLICY_PATH
V4_CLAIMS_POLICY_PATH = Path(__file__).resolve().parent.parent / "policies" / "prespec-overview-policy-v5.json"
V4_MAX_INPUT_BYTES = 8 * 1024 * 1024
V4_LUNA_REFERENCE_PROVIDER = "luna-reference"
V4_LUNA_REFERENCE_MODEL = "gpt-5.6-luna"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNSET = object()
logger = logging.getLogger(__name__)

#: 결정적 검증이 실패했을 때 같은 입력으로 더 부르는 횟수. 정책의
#: `chunking.retries`(transport 재시도)와는 다른 축이고 정책 digest를 바꾸지
#: 않는다 — 검증 재시도는 호출 인자이지 정책 변경이 아니다.
VALIDATION_RETRY_LIMIT = 1
#: 재시도 호출이 쓰는 기준 seed. 승인 기본값(0)으로 같은 프롬프트를 다시
#: 보내면 결정적으로 같은 실패가 돌아온다.
VALIDATION_RETRY_SEED = 1
#: 같은 입력을 다시 보낼 가치가 있는 모델 실패 코드. timeout·provider·신원·
#: 프롬프트 상한 실패는 응답 내용의 문제가 아니므로 포함하지 않는다.
VALIDATION_RETRY_INVOCATION_CODES = frozenset({"malformed_json", "truncated_json"})
CLAIMS_TRANSPORT_FORMAT_RETRY_CODES = frozenset({"malformed_json", "truncated_json"})
CLAIMS_INPUT_CAPACITY_CODES = frozenset({
    "input_limit_exceeded", "input_too_large", "prompt_rejected",
})
#: 실패한 검사 코드만 채워 넣는 고정 문장. 원문·응답 본문을 담지 않으므로
#: digest만 감사에 남긴다.
CORRECTION_TEMPLATE = (
    "이전 응답은 다음 검증에 실패했다: {codes}. 같은 입력으로 output_contract의 JSON schema에 맞는 객체 하나만 다시 출력한다."
    " 원문에 없는 숫자·영문 용어·페이지 번호를 추가하지 않고, 사고 과정이나 설명 문장을 JSON 밖에 쓰지 않는다."
)


def build_correction(codes: Sequence[str]) -> str:
    """실패 코드만 치환한 보정 지시."""

    return CORRECTION_TEMPLATE.format(codes=", ".join(sorted({str(code) for code in codes if code})))


def validation_retry_metadata(codes: Sequence[str], correction: str, first_raw_sha256: str | None) -> dict[str, Any]:
    """감사에 남기는 재시도 사실. 코드·digest·seed뿐이며 본문은 없다."""

    return {
        "count": VALIDATION_RETRY_LIMIT,
        "first_error_codes": [str(code) for code in codes],
        "first_raw_response_sha256": first_raw_sha256,
        "seed": VALIDATION_RETRY_SEED,
        "correction_sha256": hashlib.sha256(correction.encode("utf-8")).hexdigest(),
    }


class V4AttemptError(RuntimeError):
    """Stable, non-sensitive v4 runner failure."""

    def __init__(self, code: str) -> None:
        self.code = str(code or "failed")[:64]
        super().__init__(self.code)


def _safe_error_code(value: Any, default: str) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) else default


@dataclass(frozen=True)
class V4OverviewPolicy:
    document: Mapping[str, Any]
    digest: str

    @property
    def model_name(self) -> str:
        return str(self.document["model_name"])

    @property
    def prompt_version(self) -> str:
        return str(self.document["prompt_version"])

    @property
    def stage(self) -> str:
        return str(self.document["stages"][0]["stage"])

    @property
    def output_contract(self) -> StructuredOutputContract:
        if self.document.get("schema") == "bidops.prespec-overview-policy.v5":
            return self.structured_output_contract(CLAIMS_STAGE)
        return StructuredOutputContract(
            name="bidops_prespec_overview_page_v3",
            schema=self.document["output_schema"],
            system_prompt=str(self.document["system_prompt"]),
        )

    def stage_policy(self, stage: str) -> dict[str, Any]:
        if self.document.get("schema") != "bidops.prespec-overview-policy.v5":
            if stage != self.stage:
                raise V4AttemptError("overview_stage_invalid")
            return dict(self.document)
        policy = ClaimsOverviewPolicy(dict(self.document), self.digest)
        if policy.digest != self.digest:
            raise V4AttemptError("policy_invalid")
        return policy.stage_policy(stage)

    def structured_output_contract(self, stage: str) -> StructuredOutputContract:
        if self.document.get("schema") != "bidops.prespec-overview-policy.v5":
            return self.output_contract
        policy = ClaimsOverviewPolicy(dict(self.document), self.digest)
        if policy.digest != self.digest:
            raise V4AttemptError("policy_invalid")
        return policy.structured_output_contract(stage)


@dataclass(frozen=True)
class V4ModelBinding:
    provider: str
    model_name: str
    model_digest: str
    prompt_version: str
    policy_digest: str
    reference_only: bool = False
    deployable: bool = False
    binding_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip() or len(self.provider) > 128:
            raise V4AttemptError("invalid_binding")
        if not self.model_name.strip() or len(self.model_name) > 255:
            raise V4AttemptError("invalid_binding")
        if not self.prompt_version.strip() or len(self.prompt_version) > 128:
            raise V4AttemptError("invalid_binding")
        if not _SHA256.fullmatch(self.model_digest) or not _SHA256.fullmatch(self.policy_digest):
            raise V4AttemptError("invalid_binding")
        if self.reference_only and self.deployable:
            raise V4AttemptError("invalid_binding")
        material = {
            "provider": self.provider.strip(),
            "model_name": self.model_name.strip(),
            "model_digest": self.model_digest,
            "prompt_version": self.prompt_version.strip(),
            "policy_digest": self.policy_digest,
            "reference_only": bool(self.reference_only),
            "deployable": bool(self.deployable),
        }
        calculated = _sha256_json(material)
        if self.binding_digest is not None and self.binding_digest != calculated:
            raise V4AttemptError("invalid_binding")
        object.__setattr__(self, "provider", self.provider.strip())
        object.__setattr__(self, "model_name", self.model_name.strip())
        object.__setattr__(self, "prompt_version", self.prompt_version.strip())
        object.__setattr__(self, "binding_digest", calculated)


@dataclass(frozen=True)
class V4RunResult:
    claimed: bool
    attempt_id: UUID | None = None
    status: str = "idle"
    reason_code: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical(value))


def load_v4_policy(path: Path | None = None) -> V4OverviewPolicy:
    source = path or V4_CLAIMS_POLICY_PATH
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise V4AttemptError("policy_unreadable") from error
    if not isinstance(document, Mapping):
        raise V4AttemptError("policy_invalid")
    if document.get("schema") == "bidops.prespec-overview-policy.v5":
        try:
            policy = load_claims_policy(source)
        except ValueError as error:
            raise V4AttemptError("policy_invalid") from error
        return V4OverviewPolicy(document=policy.document, digest=policy.digest)
    required = {
        "chunking", "generation", "model_endpoint_ref", "model_name", "output_schema",
        "prompt_version", "schema", "stages", "system_prompt",
    }
    if set(document) < required or document.get("schema") != V4_POLICY_SCHEMA:
        raise V4AttemptError("policy_invalid")
    if document.get("model_name") != "qwen3.8-27B" or document.get("prompt_version") != V4_PROMPT_VERSION:
        raise V4AttemptError("policy_invalid")
    if document.get("model_endpoint_ref") != "vllm-openai-compatible":
        raise V4AttemptError("policy_invalid")
    chunking = document.get("chunking")
    if not isinstance(chunking, Mapping) or chunking.get("retries") != 0 or chunking.get("timeout_seconds") != 300:
        raise V4AttemptError("policy_invalid")
    if document.get("generation") != APPROVED_GENERATION:
        raise V4AttemptError("policy_invalid")
    stages = document.get("stages")
    if not isinstance(stages, list) or len(stages) != 1 or not isinstance(stages[0], Mapping):
        raise V4AttemptError("policy_invalid")
    if stages[0].get("stage") != V4_STAGE or not isinstance(stages[0].get("instruction"), str) or not stages[0]["instruction"].strip():
        raise V4AttemptError("policy_invalid")
    if not isinstance(document.get("output_schema"), Mapping) or not isinstance(document.get("system_prompt"), str):
        raise V4AttemptError("policy_invalid")
    # The policy is the deployed contract, but keep the model-side schema
    # aligned with the server's Pydantic validator as a cheap fail-closed check.
    schema = document["output_schema"]
    if schema.get("properties", {}).get("schema_version", {}).get("const") != "bidops.prespec-overview-page-review.v3":
        raise V4AttemptError("policy_invalid")
    return V4OverviewPolicy(document=dict(document), digest=_sha256_json(document))


def approved_v4_binding(*, policy: V4OverviewPolicy, identity: Any) -> V4ModelBinding | None:
    try:
        resolved = identity() if callable(identity) else identity
    except (ModelEndpointError, ModelIdentityError, ValueError, OSError):
        return None
    revision = getattr(resolved, "revision", None)
    served = getattr(resolved, "model", None)
    if not isinstance(revision, str) or not _SHA256.fullmatch(revision):
        return None
    if served is not None and str(served) != policy.model_name:
        return None
    return V4ModelBinding(
        provider="openai-compatible",
        model_name=policy.model_name,
        model_digest=revision,
        prompt_version=policy.prompt_version,
        policy_digest=policy.digest,
        reference_only=True,
        deployable=False,
    )


def _next_sequence(session: Session, notice_id: int) -> int:
    value = session.scalar(select(func.max(PrespecV4Attempt.sequence)).where(PrespecV4Attempt.notice_id == notice_id))
    return int(value or 0) + 1


def _binding_fields(binding: V4ModelBinding) -> dict[str, Any]:
    return {
        "provider": binding.provider,
        "model_name": binding.model_name,
        "model_digest": binding.model_digest,
        "prompt_version": binding.prompt_version,
        "policy_digest": binding.policy_digest,
        "binding_digest": binding.binding_digest,
    }


def _policy_settings_for_binding(binding: V4ModelBinding, settings: Any | None = None) -> Any | None:
    """Keep explicitly pinned legacy v4 executions readable/runnable."""

    if settings is not None:
        return settings
    try:
        legacy = load_v4_policy(V4_LEGACY_POLICY_PATH)
    except V4AttemptError:
        return None
    if binding.policy_digest == legacy.digest:
        return SimpleNamespace(prespec_overview_policy_path=V4_LEGACY_POLICY_PATH)
    return None


def _legacy_excluded_documents(session: Session) -> set[UUID]:
    """Exclude every document ever admitted to the v4 target/attempt boundary."""

    try:
        target_ids = session.scalars(
            select(PrespecV4Target.document_version_id)
        ).all()
        attempt_ids = session.scalars(
            select(PrespecV4Attempt.document_version_id).where(
                PrespecV4Attempt.document_version_id.is_not(None),
            )
        ).all()
    except SQLAlchemyError as error:
        session.rollback()
        raise V4AttemptError("database_unavailable") from error
    return {value for value in (*target_ids, *attempt_ids) if value is not None}


def enqueue_v4_attempt(
    session: Session,
    *,
    target_id: UUID,
    binding: V4ModelBinding,
    work_job_id: UUID | None = None,
    quality_status: str = "unmeasured_reference",
    settings: Any | None = None,
) -> PrespecV4Attempt | None:
    """Append one queued attempt for a ready target, without auto-retry."""

    lock_v4_gate(session)
    target = session.get(PrespecV4Target, target_id)
    if target is None or target.selection_status != "ready":
        raise V4AttemptError("target_not_ready")
    snapshot = session.get(PrespecV4PdfSnapshot, target.snapshot_id)
    if snapshot is None or snapshot.document_version_id != target.document_version_id:
        raise V4AttemptError("snapshot_scope_mismatch")
    # Activation is an append-only audit decision, not an environment default.
    # Keep this gate before creating either the WorkJob or the attempt so an
    # off/malformed cohort cannot leave an executable orphan behind.
    from .prespec_v4_ops import require_v4_enqueue_enabled

    activation = require_v4_enqueue_enabled(
        session, target=target, binding=binding,
        settings=_policy_settings_for_binding(binding, settings),
    )
    from ...lifecycle import lock_notice

    notice = lock_notice(session, target.notice_id)
    if notice is None or notice.source_type != "pre_spec":
        raise V4AttemptError("notice_not_found")
    latest_target_id = session.scalar(select(PrespecV4Target.id).where(
        PrespecV4Target.notice_id == target.notice_id,
    ).order_by(PrespecV4Target.created_at.desc(), PrespecV4Target.id.desc()).limit(1))
    if latest_target_id != target.id:
        raise V4AttemptError("target_superseded")
    # The v4 slot is the sole overview consumer for a frozen target.  A
    # legacy queued/running attempt for the same document is a conflict, not a
    # reason to run both result contracts in parallel.
    legacy_active = session.scalar(
        select(PreSpecOverviewAttempt.id)
        .join(PreSpecOverviewSnapshot, PreSpecOverviewSnapshot.id == PreSpecOverviewAttempt.snapshot_id)
        .where(
            PreSpecOverviewAttempt.status.in_(("queued", "running")),
            PreSpecOverviewAttempt.review_id.is_not(None),
            PreSpecOverviewSnapshot.document_version_id == target.document_version_id,
        )
        .limit(1)
    )
    if legacy_active is not None:
        raise V4AttemptError("legacy_overview_active")
    active = session.scalar(select(PrespecV4Attempt).where(
        PrespecV4Attempt.target_id == target.id,
        PrespecV4Attempt.status.in_(("queued", "running")),
    ))
    if active is not None:
        return active
    latest = session.scalar(select(PrespecV4Attempt).where(
        PrespecV4Attempt.target_id == target.id,
        PrespecV4Attempt.status == "completed",
        PrespecV4Attempt.binding_digest == binding.binding_digest,
        PrespecV4Attempt.input_sha256 == target.input_sha256,
    ).order_by(PrespecV4Attempt.sequence.desc()))
    if latest is not None:
        return latest
    binding_settings = _policy_settings_for_binding(binding, settings)
    policy = load_v4_policy(
        getattr(binding_settings, "prespec_overview_policy_path", None)
        if binding_settings is not None else None
    )
    if policy.digest != binding.policy_digest:
        raise V4AttemptError("policy_binding_mismatch")
    if work_job_id is None:
        # A retry is new immutable execution history.  The partial unique
        # index permits a new active job after the previous job is terminal;
        # reopening the terminal row would erase its lifecycle provenance.
        job = WorkJob(
            id=uuid4(), job_type="prespec_v4_overview", aggregate_type="prespec_v4_target",
            aggregate_id=target.id, status="queued", priority=0, attempt_count=0,
            max_attempts=1, scheduled_at=_now(),
        )
        session.add(job)
        session.flush()
        work_job_id = job.id
    fields = _binding_fields(binding)
    generation = (
        {row["stage"]: dict(row["generation"]) for row in policy.document["stages"]}
        if policy.document.get("schema") == "bidops.prespec-overview-policy.v5"
        else dict(policy.document["generation"])
    )
    attempt = PrespecV4Attempt(
        id=uuid4(), notice_id=target.notice_id, document_version_id=target.document_version_id,
        target_id=target.id, work_job_id=work_job_id, sequence=_next_sequence(session, target.notice_id),
        activation_id=activation.activation_id,
        source_sha256=snapshot.source_sha256, pdf_sha256=snapshot.pdf_sha256,
        input_sha256=target.input_sha256, selection_manifest_sha256=target.selection_manifest_sha256,
        generation_jsonb=generation,
        quality_status=quality_status, reference_only=binding.reference_only, deployable=binding.deployable,
        **fields,
    )
    session.add(attempt)
    session.flush()
    return attempt


def record_v4_preparation_failure(
    session: Session,
    *,
    notice_id: int,
    error_code: str,
    document_version_id: UUID | None = None,
) -> PrespecV4Attempt:
    """Expose a preparation failure as a current, terminal attempt."""

    attempt = PrespecV4Attempt(
        id=uuid4(), notice_id=notice_id, document_version_id=document_version_id,
        target_id=None, sequence=_next_sequence(session, notice_id), status="failed",
        quality_status="unmeasured_reference", error_code=str(error_code or "preparation_failed")[:64],
        completed_at=_now(), created_at=_now(),
    )
    session.add(attempt)
    from .document_converter import SAFE_CONVERTER_CODES
    converter_code = error_code.removeprefix("pdf_preparation_failed:") if error_code.startswith("pdf_preparation_failed:") else None
    safe_metadata = {"notice_id": notice_id, "status": "failed", "reason_code": attempt.error_code}
    if converter_code in SAFE_CONVERTER_CODES:
        safe_metadata["converter_code"] = converter_code
    session.add(AuditEvent(actor_kind="system", claimed_name=None, action="prespec_v4.preparation_failed", aggregate_type="prespec_v4_attempt", aggregate_id=str(attempt.id), safe_metadata=safe_metadata))
    session.flush()
    return attempt


def _claim_v4_attempt(
    session: Session,
    worker_id: str,
    *,
    now: datetime,
    lease_seconds: int,
    activation_id: UUID,
    binding: V4ModelBinding,
) -> PrespecV4Attempt | None:
    lock_v4_gate(session)
    attempt = session.scalars(select(PrespecV4Attempt).where(
        PrespecV4Attempt.status == "queued",
        PrespecV4Attempt.target_id.is_not(None),
        PrespecV4Attempt.activation_id == activation_id,
        PrespecV4Attempt.binding_digest == binding.binding_digest,
        PrespecV4Attempt.policy_digest == binding.policy_digest,
    ).order_by(PrespecV4Attempt.created_at.asc(), PrespecV4Attempt.sequence.asc()).limit(1).with_for_update(skip_locked=True)).first()
    if attempt is None:
        return None
    attempt.status = "running"
    attempt.started_at = now
    attempt.lease_owner = worker_id
    attempt.lease_expires_at = now + timedelta(seconds=lease_seconds)
    if attempt.work_job_id is not None:
        job = session.get(WorkJob, attempt.work_job_id)
        if job is not None:
            job.status = "running"
            job.lease_owner = worker_id
            job.lease_expires_at = attempt.lease_expires_at
            job.lease_fence = int(job.lease_fence or 0) + 1
            job.attempt_count = int(job.attempt_count or 0) + 1
    session.flush()
    return attempt


def _expire_v4_attempts(session: Session, *, now: datetime) -> int:
    lock_v4_gate(session)
    rows = session.scalars(select(PrespecV4Attempt).where(
        PrespecV4Attempt.status == "running", PrespecV4Attempt.lease_expires_at <= now,
    ).with_for_update()).all()
    for attempt in rows:
        attempt.status = "failed"
        attempt.error_code = "lease_expired"
        attempt.completed_at = now
        attempt.lease_owner = None
        attempt.lease_expires_at = None
        if attempt.work_job_id is not None:
            job = session.get(WorkJob, attempt.work_job_id)
            if job is not None:
                job.status = "failed"
                job.last_error_code = "lease_expired"
                job.completed_at = now
                job.lease_owner = None
                job.lease_expires_at = None
    return len(rows)


def _load_manifest(session: Session, store: ObjectStore, target: PrespecV4Target) -> tuple[dict[str, Any], dict[int, str]]:
    if target.manifest_content_object_id is None or target.manifest_location_id is None or not target.selection_manifest_sha256:
        raise V4AttemptError("manifest_unavailable")
    content = session.get(ContentObject, target.manifest_content_object_id)
    if content is None or content.detected_mime != "application/json":
        raise V4AttemptError("manifest_unavailable")
    location = _verified_location(session, target.manifest_location_id, content.id)
    try:
        raw = _read_verified_artifact(store, location, content, max_bytes=min(MAX_V4_MANIFEST_BYTES, max(content.size_bytes, 1)), expected_mime=None)
    except V4PreparationError as error:
        raise V4AttemptError(error.code) from error
    if _sha256_bytes(raw) != target.selection_manifest_sha256 or len(raw) != target.input_byte_count:
        raise V4AttemptError("manifest_hash_mismatch")
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as error:
        raise V4AttemptError("manifest_invalid") from error
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != V4_MANIFEST_SCHEMA:
        raise V4AttemptError("manifest_invalid")
    pages = manifest.get("pages")
    if not isinstance(pages, list) or not pages or len(raw) > MAX_V4_MANIFEST_BYTES:
        raise V4AttemptError("manifest_invalid")
    page_text: dict[int, str] = {}
    for item in pages:
        if not isinstance(item, Mapping) or isinstance(item.get("number"), bool) or not isinstance(item.get("number"), int) or not isinstance(item.get("text"), str):
            raise V4AttemptError("manifest_invalid")
        number, text_value = int(item["number"]), item["text"]
        if number in page_text or item.get("text_sha256") != _sha256_bytes(text_value.encode()):
            raise V4AttemptError("manifest_invalid")
        page_text[number] = text_value
    if not any(text.strip() for text in page_text.values()):
        raise V4AttemptError("manifest_invalid")
    input_payload = {key: manifest.get(key) for key in ("schema_version", "document_version_id", "source_sha256", "pages", "block_keys", "start_locator", "end_locator", "input_limitations")}
    if _sha256_json(input_payload) != target.input_sha256:
        raise V4AttemptError("input_hash_mismatch")
    if str(manifest.get("document_version_id")) != str(target.document_version_id):
        raise V4AttemptError("manifest_scope_mismatch")
    return dict(manifest), page_text


def _model_input(manifest: Mapping[str, Any], pages: Mapping[int, str]) -> dict[str, Any]:
    # The v4 policy is authored for physical PDF blocks.  Keep the model seam
    # independent of our storage manifest's page/hash fields: only the selected
    # page text and its physical page number cross the model boundary.
    value = {
        "schema_version": V4_MANIFEST_SCHEMA,
        "blocks": [{"pdf_page": n, "text": pages[n]} for n in sorted(pages)],
        "input_limitations": manifest.get("input_limitations", []),
    }
    raw = _canonical(value)
    if len(raw) > V4_MAX_INPUT_BYTES:
        raise V4AttemptError("input_too_large")
    return value


def _response_parts(response: Any) -> tuple[Mapping[str, Any], bytes]:
    output = getattr(response, "structured_output", None)
    raw = getattr(response, "raw_response", None)
    if not isinstance(output, Mapping) or not isinstance(raw, (bytes, bytearray)):
        raise V4AttemptError("malformed_json")
    return output, bytes(raw)


class PrespecV4OverviewRunner:
    def __init__(
        self,
        *,
        client: Any | None = None,
        binding: V4ModelBinding | None | Any = _UNSET,
        policy: V4OverviewPolicy | None = None,
        raw_response_store: Any | None = None,
        object_store: ObjectStore | None = None,
        legacy_runner: Any | None = None,
        settings: Any | None = None,
        lease_seconds: int = V4_LEASE_SECONDS,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.client = client
        self.binding = binding
        self._policy = policy
        self._policy_loaded = policy is not None
        self.raw_response_store = raw_response_store
        self.object_store = object_store
        self.legacy_runner = legacy_runner
        self.settings = settings
        self.lease_seconds = int(lease_seconds)
        self.clock = clock
        self._resolved: tuple[V4ModelBinding | None, Any | None] | None = None
        self._resolved_key: tuple[str, str, str, str, str] | None = None
        self._identity_config_key: tuple[str, str, str, str] | None = None
        self._identity_state = ModelIdentityCheckState()
        self._model_context_tokens: int | None = None

    def policy(self) -> V4OverviewPolicy:
        if not self._policy_loaded:
            self._policy = load_v4_policy()
            self._policy_loaded = True
        if self._policy is None:
            raise V4AttemptError("policy_missing")
        return self._policy

    def _resolve(self) -> tuple[V4ModelBinding | None, Any | None]:
        policy = self.policy()
        client = self.client
        binding = None if self.binding is _UNSET else self.binding
        endpoint_fingerprint = model_endpoint_configuration_fingerprint(
            "overview", settings=self.settings
        )
        config_key = (
            "overview", endpoint_fingerprint, policy.model_name, policy.digest
        )
        if self._identity_config_key != config_key:
            self._invalidate_identity_cache()
            self._identity_config_key = config_key
        if self._resolved is not None:
            cached_binding = self._resolved[0]
            expected_key = model_identity_cache_key(
                "overview", settings=self.settings, model=policy.model_name,
                revision=cached_binding.model_digest,
                policy_digest=policy.digest,
            )
            if self._resolved_key == expected_key:
                return self._resolved
            self._invalidate_identity_cache()
        if self.binding is not _UNSET:
            if binding is not None and client is not None and binding.policy_digest == policy.digest:
                self._model_context_tokens = getattr(client, "model_context_tokens", None)
                self._resolved = (binding, client)
                self._resolved_key = model_identity_cache_key(
                    "overview", settings=self.settings, model=policy.model_name,
                    revision=binding.model_digest, policy_digest=policy.digest,
                )
                return self._resolved
            return (None, None)
        now = self.clock()
        if not self._identity_state.should_check(now):
            return (None, None)
        owns_client = client is None
        try:
            if client is None:
                client = ModelClient.for_purpose(
                    "overview", model=policy.model_name, output_contract=policy.output_contract,
                    settings=self.settings, verify_identity=False,
                )
            identity = client.verify_identity()
            self._model_context_tokens = getattr(identity, "max_model_len", None)
            binding = approved_v4_binding(policy=policy, identity=identity)
            if binding is None:
                raise ModelIdentityError("model_not_served", retryable=False)
            if binding is not None and binding.policy_digest != policy.digest:
                binding = None
        except (ModelEndpointError, ModelIdentityError, V4AttemptError, ValueError, OSError) as error:
            reason = self._identity_state.record_failure(error, now)
            next_check = self._identity_state.next_check_at
            logger.warning(
                "prespec v4 identity blocked reason=%s next_check_at=%s",
                reason,
                next_check.isoformat() if next_check is not None else None,
            )
            if client is not None and owns_client:
                closer = getattr(client, "close", None)
                if callable(closer):
                    closer()
            return (None, None)
        self._identity_state.record_success()
        self._resolved = (binding, client)
        self._resolved_key = model_identity_cache_key(
            "overview", settings=self.settings, model=policy.model_name,
            revision=binding.model_digest, policy_digest=policy.digest,
        )
        logger.info(
            "prespec v4 identity verified endpoint_fingerprint=%s",
            endpoint_fingerprint,
        )
        return self._resolved

    def _invalidate_identity_cache(self) -> None:
        resolved, self._resolved = self._resolved, None
        self._resolved_key = None
        self._model_context_tokens = None
        self._identity_state.invalidate_success()
        if resolved is not None and resolved[1] is not self.client:
            closer = getattr(resolved[1], "close", None)
            if callable(closer):
                closer()

    def _activation_settings(self) -> Any | None:
        policy = self.policy()
        try:
            legacy = load_v4_policy(V4_LEGACY_POLICY_PATH)
        except V4AttemptError:
            legacy = None
        if self.settings is None and legacy is not None and policy.digest == legacy.digest:
            return SimpleNamespace(prespec_overview_policy_path=V4_LEGACY_POLICY_PATH)
        return self.settings

    def _run_legacy(self, session: Session, worker_id: str) -> Any:
        if self.legacy_runner is None:
            return V4RunResult(False)
        try:
            excluded = _legacy_excluded_documents(session)
        except V4AttemptError as error:
            return V4RunResult(False, status="failed", reason_code=error.code)
        return self.legacy_runner.run_once(
            session, worker_id, excluded_document_version_ids=excluded
        )

    def run_once(self, session: Session, worker_id: str) -> V4RunResult:
        now = self.clock()
        try:
            lock_v4_gate(session)
            expired = _expire_v4_attempts(session, now=now)
            from .prespec_v4_ops import v4_dispatch_enabled
            activation = v4_dispatch_enabled(session, settings=self._activation_settings())
            queued = None if activation is None else session.scalar(
                select(PrespecV4Attempt.id)
                .where(
                    PrespecV4Attempt.status == "queued",
                    PrespecV4Attempt.activation_id == activation.activation_id,
                    PrespecV4Attempt.policy_digest == activation.policy_digest,
                    PrespecV4Attempt.binding_digest == activation.binding.binding_digest,
                )
                .limit(1)
            )
            session.commit()
        except (SQLAlchemyError, V4AttemptError, ValueError, OSError):
            session.rollback()
            return V4RunResult(False, status="failed", reason_code="database_unavailable")
        if queued is None:
            return self._run_legacy(session, worker_id)
        binding, client = self._resolve()
        if binding is None or client is None:
            legacy = self._run_legacy(session, worker_id)
            if getattr(legacy, "claimed", False):
                return legacy
            return V4RunResult(False, status="awaiting_model", reason_code="model_unavailable")
        if (
            binding.binding_digest != activation.binding.binding_digest
            or binding.policy_digest != activation.policy_digest
        ):
            legacy = self._run_legacy(session, worker_id)
            if getattr(legacy, "claimed", False):
                return legacy
            return V4RunResult(False, status="awaiting_model", reason_code="activation_binding_mismatch")
        try:
            # Activation may have changed while identity was checked.
            lock_v4_gate(session)
            live_activation = v4_dispatch_enabled(session, settings=self._activation_settings())
            if live_activation is None or live_activation.activation_id != activation.activation_id:
                session.rollback()
                return self._run_legacy(session, worker_id)
            attempt = _claim_v4_attempt(
                session,
                worker_id,
                now=self.clock(),
                lease_seconds=self.lease_seconds,
                activation_id=activation.activation_id,
                binding=binding,
            )
            if attempt is None:
                session.rollback()
                return self._run_legacy(session, worker_id)
            attempt_id = attempt.id
            session.commit()
        except (SQLAlchemyError, V4AttemptError, ValueError, OSError):
            session.rollback()
            return V4RunResult(False, status="failed", reason_code="database_unavailable")
        if self.policy().document.get("schema") == "bidops.prespec-overview-policy.v5":
            return self._run_claims_attempt(session, attempt_id, worker_id, binding, client)
        return self._run_legacy_v4_attempt(session, attempt_id, worker_id, binding, client)

    def _run_legacy_v4_attempt(
        self, session: Session, attempt_id: UUID, worker_id: str,
        binding: V4ModelBinding, client: Any,
    ) -> V4RunResult:
        attempt = session.get(PrespecV4Attempt, attempt_id)
        if attempt is None:
            return V4RunResult(True, attempt_id, "stale", "stale_attempt")
        raw_sha: str | None = None
        retry: dict[str, Any] | None = None
        try:
            target, snapshot, input_slice, page_text = self._load_input(session, attempt, binding)
            stage, policy_document = self.policy().stage, self.policy().document
            try:
                response = client.invoke(stage, input_slice, policy_document)
                output, raw = _response_parts(response)
                raw_sha = self._store_raw(session, raw)
                # The encrypted raw object is a durable failure/result audit even
                # when deterministic result validation below rejects the attempt.
                session.commit()
                # 결정적 검증을 `_complete` 앞에서 한 번 본다. `_complete`는
                # 그대로 최종 관문으로 다시 검사한다.
                codes = validate_page_overview(output, dict(page_text))
            except ModelInvocationError as error:
                code = str(getattr(error, "code", "model_failed"))
                if code not in VALIDATION_RETRY_INVOCATION_CODES:
                    raise
                raw_sha = self._store_error_raw(session, error)
                response, output, codes = None, None, [code]
            if codes:
                correction = build_correction(codes)
                retry = validation_retry_metadata(codes, correction, raw_sha)
                response = client.invoke(
                    stage, input_slice, policy_document, seed=VALIDATION_RETRY_SEED, correction=correction
                )
                output, raw = _response_parts(response)
                raw_sha = self._store_raw(session, raw)
                session.commit()
            self._complete(session, attempt, target, snapshot, output, raw_sha, response, worker_id, page_text, binding, retry)
            return V4RunResult(True, attempt_id, "completed")
        except ModelInvocationError as error:
            if error.code in RUNTIME_IDENTITY_ERROR_CODES:
                self._invalidate_identity_cache()
            raw = getattr(error, "raw_response", None)
            if isinstance(raw, (bytes, bytearray)):
                stored = self._store_error_raw(session, error)
                raw_sha = stored if stored is not None else raw_sha
            return self._fail(session, attempt_id, worker_id, getattr(error, "code", "model_failed"), raw_sha, retry)
        except (V4AttemptError, ValidationError, ObjectStoreError, OSError, ValueError) as error:
            return self._fail(session, attempt_id, worker_id, getattr(error, "code", "validation_failed"), raw_sha, retry)
        except Exception:
            return self._fail(session, attempt_id, worker_id, "runner_failed", raw_sha, retry)

    def _live_attempt(
        self,
        session: Session,
        attempt_id: UUID,
        worker_id: str,
        binding: V4ModelBinding,
        *,
        reserve_seconds: int = 0,
    ) -> tuple[PrespecV4Attempt, PrespecV4Target, PrespecV4PdfSnapshot]:
        """Lock and revalidate the complete dispatch/publication fence."""

        lock_v4_gate(session)
        live = session.scalar(
            select(PrespecV4Attempt)
            .where(PrespecV4Attempt.id == attempt_id)
            .with_for_update()
        )
        now = self.clock()
        if live is None or live.status != "running" or live.lease_owner != worker_id:
            raise V4AttemptError("stale_attempt")
        if live.lease_expires_at is None:
            raise V4AttemptError("stale_attempt")
        if live.lease_expires_at <= now:
            raise V4AttemptError("lease_expired")
        if live.lease_expires_at <= now + timedelta(seconds=reserve_seconds):
            raise V4AttemptError("lease_budget_exhausted")
        if live.activation_id is None:
            raise V4AttemptError("activation_mismatch")
        if (
            live.binding_digest != binding.binding_digest
            or live.policy_digest != binding.policy_digest
        ):
            raise V4AttemptError("binding_mismatch")
        target = session.get(PrespecV4Target, live.target_id)
        snapshot = session.get(PrespecV4PdfSnapshot, target.snapshot_id) if target is not None else None
        if target is None or snapshot is None:
            raise V4AttemptError("input_scope_mismatch")
        from .prespec_v4_ops import require_v4_enqueue_enabled

        activation = require_v4_enqueue_enabled(
            session, target=target, binding=binding,
            settings=_policy_settings_for_binding(binding, self.settings),
        )
        if activation.activation_id != live.activation_id:
            raise V4AttemptError("activation_mismatch")
        document = session.get(DocumentVersion, target.document_version_id)
        source = session.get(ContentObject, document.content_object_id) if document is not None else None
        if (
            target.selection_status != "ready"
            or document is None
            or not document.is_current
            or document.safety_status != "safe"
            or document.needs_human_review
            or source is None
            or snapshot.source_sha256 != source.sha256
            or live.input_sha256 != target.input_sha256
            or live.selection_manifest_sha256 != target.selection_manifest_sha256
        ):
            raise V4AttemptError("input_integrity_failed")
        return live, target, snapshot

    def _authorize_call(
        self,
        session: Session,
        attempt_id: UUID,
        worker_id: str,
        binding: V4ModelBinding,
        *,
        stage: str,
        prompt_sha256: str,
    ) -> tuple[UUID, int]:
        live, _target, _snapshot = self._live_attempt(
            session,
            attempt_id,
            worker_id,
            binding,
            reserve_seconds=V4_DISPATCH_RESERVE_SECONDS,
        )
        dispatched = session.scalars(
            select(PrespecOverviewCallEvent).where(
                PrespecOverviewCallEvent.attempt_id == attempt_id,
                PrespecOverviewCallEvent.event_kind == "dispatch",
            )
        ).all()
        ordinal = len(dispatched) + 1
        if ordinal > LIMITS["max_calls"]:
            raise V4AttemptError("call_budget_exhausted")
        if stage == CLAIMS_STAGE and sum(row.stage == "draft" for row in dispatched) >= LIMITS["max_draft_calls"]:
            raise V4AttemptError("call_budget_exhausted")
        if stage == SEMANTIC_STAGE and any(row.stage == "semantic" for row in dispatched):
            raise V4AttemptError("call_budget_exhausted")
        ledger_stage = "draft" if stage == CLAIMS_STAGE else "semantic"
        call_id = uuid4()
        session.add(
            PrespecOverviewCallEvent(
                id=uuid4(),
                call_id=call_id,
                attempt_id=live.id,
                ordinal=ordinal,
                stage=ledger_stage,
                event_kind="dispatch",
                input_sha256=live.input_sha256,
                prompt_sha256=prompt_sha256,
                binding_digest=binding.binding_digest,
                created_at=self.clock(),
            )
        )
        session.commit()
        return call_id, ordinal

    def _raw_reference(self, session: Session, raw: bytes) -> tuple[str, UUID, UUID]:
        digest = self._store_raw(session, raw)
        content = session.scalar(select(ContentObject).where(ContentObject.sha256 == digest))
        location = session.scalar(
            select(ContentObjectLocation)
            .where(
                ContentObjectLocation.content_object_id == content.id,
                ContentObjectLocation.namespace_key == "model-response",
            )
            .order_by(ContentObjectLocation.created_at.desc(), ContentObjectLocation.id.desc())
        ) if content is not None else None
        if content is None or location is None:
            raise V4AttemptError("response_store_unavailable")
        return digest, content.id, location.id

    def _record_call_response(
        self, session: Session, *, call_id: UUID, attempt_id: UUID,
        ordinal: int, stage: str, binding: V4ModelBinding, response: Any, raw: bytes,
    ) -> str:
        try:
            dispatch = session.scalar(select(PrespecOverviewCallEvent).where(
                PrespecOverviewCallEvent.call_id == call_id,
                PrespecOverviewCallEvent.event_kind == "dispatch",
            ))
            if dispatch is None:
                raise V4AttemptError("call_dispatch_missing")
            digest, content_id, location_id = self._raw_reference(session, raw)
            session.add(PrespecOverviewCallEvent(
                id=uuid4(), call_id=call_id, attempt_id=attempt_id, ordinal=ordinal,
                stage=stage, event_kind="response",
                input_sha256=dispatch.input_sha256,
                prompt_sha256=dispatch.prompt_sha256, binding_digest=binding.binding_digest,
                raw_response_sha256=digest, raw_response_content_object_id=content_id,
                raw_response_location_id=location_id,
                prompt_tokens=getattr(response, "prompt_tokens", None),
                output_tokens=getattr(response, "output_tokens", None),
                latency_ms=getattr(response, "latency_ms", None), created_at=self.clock(),
            ))
            session.commit()
            return digest
        except Exception:
            session.rollback()
            raise V4AttemptError("response_store_unavailable") from None

    def _record_call_error(
        self, session: Session, *, call_id: UUID, attempt_id: UUID,
        ordinal: int, stage: str, binding: V4ModelBinding, error: BaseException,
    ) -> None:
        session.rollback()
        raw = getattr(error, "raw_response", None)
        digest = None
        content_id = None
        location_id = None
        storage_failed = False
        if isinstance(raw, (bytes, bytearray)):
            try:
                digest, content_id, location_id = self._raw_reference(session, bytes(raw))
            except Exception:
                session.rollback()
                storage_failed = True
        code = "response_store_unavailable" if storage_failed else _safe_error_code(getattr(error, "code", None), "model_failed")
        dispatch = session.scalar(select(PrespecOverviewCallEvent).where(
            PrespecOverviewCallEvent.call_id == call_id,
            PrespecOverviewCallEvent.event_kind == "dispatch",
        ))
        if dispatch is None:
            raise V4AttemptError("call_dispatch_missing")
        session.add(PrespecOverviewCallEvent(
            id=uuid4(), call_id=call_id, attempt_id=attempt_id, ordinal=ordinal,
            stage=stage, event_kind="error",
            input_sha256=dispatch.input_sha256,
            prompt_sha256=dispatch.prompt_sha256, binding_digest=binding.binding_digest,
            raw_response_sha256=digest, raw_response_content_object_id=content_id,
            raw_response_location_id=location_id, error_code=code,
            created_at=self.clock(),
        ))
        session.commit()
        if storage_failed:
            raise V4AttemptError("response_store_unavailable")

    def _invoke_claim_stage(
        self,
        session: Session,
        *,
        attempt_id: UUID,
        worker_id: str,
        binding: V4ModelBinding,
        client: Any,
        stage: str,
        input_slice: Mapping[str, Any],
        correction: str | None = None,
        seed: int | None = None,
    ) -> tuple[Any, bytes, str]:
        policy = self.policy()
        claims_policy = ClaimsOverviewPolicy(dict(policy.document), policy.digest)
        prompt = build_claims_prompt(claims_policy, stage, dict(input_slice))
        output_contract = claims_policy.structured_output_contract(stage)
        effective_seed = int(APPROVED_GENERATION["seed"] if seed is None else seed)
        structured_request_capacity(
            model=binding.model_name,
            prompt=prompt,
            contract=output_contract,
            api_dialect=str(getattr(client, "api_dialect", "vllm")),
            max_model_len=self._model_context_tokens,
            policy_context_ceiling=LIMITS["max_model_context_tokens"],
            max_tokens=APPROVED_GENERATION["max_completion_tokens"],
            chat_template_reserve_tokens=LIMITS["chat_template_reserve_tokens"],
            timeout_seconds=LIMITS["timeout_seconds"],
            seed=effective_seed,
            correction=correction,
        )
        prompt_sha256 = canonical_sha256({
            "system_prompt": output_contract.system_prompt,
            "user_prompt": prompt,
            "correction": correction,
            "seed": effective_seed,
        })
        call_id, ordinal = self._authorize_call(
            session, attempt_id, worker_id, binding,
            stage=stage, prompt_sha256=prompt_sha256,
        )
        ledger_stage = "draft" if stage == CLAIMS_STAGE else "semantic"
        try:
            response = client.invoke(
                stage,
                input_slice,
                claims_policy.stage_policy(stage),
                seed=seed,
                correction=correction,
                output_contract=output_contract,
            )
            output, raw = _response_parts(response)
            digest = self._record_call_response(
                session, call_id=call_id, attempt_id=attempt_id, ordinal=ordinal,
                stage=ledger_stage, binding=binding, response=response, raw=raw,
            )
            return response, raw, digest
        except (ModelInvocationError, ModelIdentityError) as error:
            self._record_call_error(
                session, call_id=call_id, attempt_id=attempt_id, ordinal=ordinal,
                stage=ledger_stage, binding=binding, error=error,
            )
            if getattr(error, "code", None) in RUNTIME_IDENTITY_ERROR_CODES:
                self._invalidate_identity_cache()
            raise
        except V4AttemptError as error:
            self._record_call_error(
                session, call_id=call_id, attempt_id=attempt_id, ordinal=ordinal,
                stage=ledger_stage, binding=binding, error=error,
            )
            raise

    def _run_claims_attempt(
        self, session: Session, attempt_id: UUID, worker_id: str,
        binding: V4ModelBinding, client: Any,
    ) -> V4RunResult:
        raw_sha: str | None = None
        try:
            attempt = session.get(PrespecV4Attempt, attempt_id)
            if attempt is None:
                raise V4AttemptError("stale_attempt")
            target, snapshot, _legacy_input, pages = self._load_input(session, attempt, binding)
            session.commit()
            draft_input = build_claims_stage_input(pages)

            def _publish_failed_draft(raw_value: bytes, error: ClaimDraftError) -> V4RunResult:
                checks = draft_failure_checks(
                    raw_value, error, attempt_id=attempt_id,
                    input_sha256=attempt.input_sha256,
                    policy_digest=binding.policy_digest,
                    binding_digest=binding.binding_digest,
                )
                return self._publish_verification(
                    session, attempt_id, worker_id, binding, checks,
                    target=target, snapshot=snapshot, draft=None,
                    raw_sha=raw_sha,
                )

            retry_code: str | None = None
            try:
                _response, raw, raw_sha = self._invoke_claim_stage(
                    session, attempt_id=attempt_id, worker_id=worker_id,
                    binding=binding, client=client, stage=CLAIMS_STAGE,
                    input_slice=draft_input,
                )
                draft = parse_claims_draft(raw)
            except ClaimDraftError as first_error:
                if not first_error.retryable:
                    return _publish_failed_draft(raw, first_error)
                retry_code = first_error.code
            except ModelInvocationError as first_error:
                if (first_error.code not in CLAIMS_TRANSPORT_FORMAT_RETRY_CODES
                    or not isinstance(first_error.raw_response, (bytes, bytearray))
                    or not first_error.raw_response):
                    raise
                retry_code = first_error.code
            if retry_code is not None:
                correction = build_correction([retry_code])
                try:
                    _response, raw, raw_sha = self._invoke_claim_stage(
                        session, attempt_id=attempt_id, worker_id=worker_id,
                        binding=binding, client=client, stage=CLAIMS_STAGE,
                        input_slice=draft_input, correction=correction,
                        seed=VALIDATION_RETRY_SEED,
                    )
                except ModelInvocationError as second_error:
                    if second_error.code in CLAIMS_TRANSPORT_FORMAT_RETRY_CODES:
                        raise V4AttemptError("draft_format_retry_exhausted") from None
                    raise
                try:
                    draft = parse_claims_draft(raw)
                except ClaimDraftError as second_error:
                    if not second_error.retryable:
                        return _publish_failed_draft(raw, second_error)
                    raise V4AttemptError("draft_format_retry_exhausted") from None
            checks = validate_claims_deterministically(
                draft, pages, attempt_id=attempt_id,
                input_sha256=attempt.input_sha256,
                policy_digest=binding.policy_digest,
                binding_digest=binding.binding_digest,
                company_comparison_performed=False,
            )
            if checks.reason_codes or any(
                row.deterministic.status != "passed" for row in checks.checks
            ):
                return self._publish_verification(
                    session, attempt_id, worker_id, binding, checks,
                    target=target, snapshot=snapshot, draft=draft, raw_sha=raw_sha,
                )
            semantic_input = build_claims_stage_input(
                pages, draft=draft, checks=checks,
                company_comparison_performed=False,
            )
            _response, semantic_raw, raw_sha = self._invoke_claim_stage(
                session, attempt_id=attempt_id, worker_id=worker_id,
                binding=binding, client=client, stage=SEMANTIC_STAGE,
                input_slice=semantic_input,
            )
            checks = apply_semantic_review(draft, checks, semantic_raw)
            return self._publish_verification(
                session, attempt_id, worker_id, binding, checks,
                target=target, snapshot=snapshot, draft=draft, raw_sha=raw_sha,
            )
        except SemanticResponseError as error:
            return self._fail(session, attempt_id, worker_id, error.code, raw_sha)
        except (ModelInvocationError, ModelIdentityError) as error:
            return self._fail(session, attempt_id, worker_id, getattr(error, "code", "model_failed"), raw_sha)
        except (V4AttemptError, ClaimDraftError, ObjectStoreError, OSError, ValueError) as error:
            code = getattr(error, "code", str(error) or "validation_failed")
            if code in CLAIMS_INPUT_CAPACITY_CODES:
                code = "input_capacity_exceeded"
            return self._fail(session, attempt_id, worker_id, code, raw_sha)
        except Exception:
            return self._fail(session, attempt_id, worker_id, "runner_failed", raw_sha)

    def _publish_verification(
        self, session: Session, attempt_id: UUID, worker_id: str,
        binding: V4ModelBinding, checks: Any, *, target: PrespecV4Target,
        snapshot: PrespecV4PdfSnapshot, draft: Any | None, raw_sha: str | None,
    ) -> V4RunResult:
        session.rollback()
        live, locked_target, locked_snapshot = self._live_attempt(
            session, attempt_id, worker_id, binding
        )
        if locked_target.id != target.id or locked_snapshot.id != snapshot.id:
            raise V4AttemptError("input_scope_mismatch")
        verification_id = uuid4()
        checks_json = checks.model_dump(mode="json")
        verification_sha = canonical_sha256(checks_json)
        verification = PrespecOverviewVerification(
            id=verification_id, attempt_id=attempt_id,
            schema_version=checks.schema_version,
            draft_sha256=checks.draft_sha256,
            input_sha256=live.input_sha256,
            policy_digest=live.policy_digest,
            binding_digest=live.binding_digest,
            model_digest=live.model_digest,
            validator_version=checks.validator_version,
            payload_jsonb=checks_json, payload_sha256=verification_sha,
            overall=checks.overall, created_at=self.clock(),
        )
        session.add(verification)
        # The result's insert guard queries this immutable row through the
        # connection; make it visible inside the same transaction first.
        session.flush()
        completed_at = self.clock()
        result_id = None
        if checks.overall == "passed":
            if draft is None:
                raise V4AttemptError("verification_binding_mismatch")
            limitations = build_input_limitations(
                list(locked_target.page_numbers_jsonb or []),
                pdf_page_count=locked_snapshot.pdf_page_count,
            )
            payload = compose_page_overview(
                draft, checks, verification_id=verification_id,
                input_limitations=limitations,
            )
            if validate_composed_page_overview(payload, checks):
                raise V4AttemptError("verification_content_mismatch")
            payload_json = payload.model_dump(mode="json")
            payload_sha = canonical_sha256(payload_json)
            result = PreSpecPageOverview(
                id=uuid4(), run_id=live.id, notice_id=live.notice_id,
                document_version_id=locked_target.document_version_id,
                input_location_id=locked_target.manifest_location_id,
                pdf_location_id=locked_snapshot.pdf_location_id,
                schema_version=payload.schema_version,
                verification_id=verification_id,
                verification_sha256=verification_sha,
                source_sha256=locked_snapshot.source_sha256,
                pdf_sha256=locked_snapshot.pdf_sha256,
                payload_sha256=payload_sha,
                import_sha256=canonical_sha256({
                    "attempt_id": str(live.id), "target_id": str(locked_target.id),
                    "verification_id": str(verification_id), "payload_sha256": payload_sha,
                    "binding_digest": live.binding_digest,
                }),
                input_sha256=live.input_sha256,
                model_digest=live.model_digest, policy_digest=live.policy_digest,
                model_name=live.model_name, prompt_version=live.prompt_version,
                pdf_page_count=locked_snapshot.pdf_page_count,
                reviewed_pages=list(locked_target.page_numbers_jsonb or []),
                payload_jsonb=payload_json, validation_status="passed",
                validation_errors=[], evidence_check_status="passed",
                evidence_check_errors=[], validator_version=checks.validator_version,
                quality_status=live.quality_status,
            )
            session.add(result)
            session.flush()
            result_id = result.id
            live.result_id = result.id
            live.result_sha256 = payload_sha
            live.status = "completed"
            job_status = "completed"
            error_code = None
        else:
            live.status = "needs_human_review"
            job_status = "failed"
            error_code = "claim_verification_required"
            live.error_code = error_code
        live.raw_response_sha256 = raw_sha
        live.completed_at = completed_at
        live.lease_owner = None
        live.lease_expires_at = None
        if live.work_job_id is not None:
            job = session.scalar(
                select(WorkJob).where(WorkJob.id == live.work_job_id).with_for_update()
            )
            if job is not None:
                job.status = job_status
                job.last_error_code = error_code
                job.completed_at = completed_at
                job.lease_owner = None
                job.lease_expires_at = None
        session.add(AuditEvent(
            actor_kind="system", claimed_name=None,
            action="prespec_v4.attempt_run", aggregate_type="prespec_v4_attempt",
            aggregate_id=str(live.id), safe_metadata={
                "notice_id": live.notice_id, "status": live.status,
                "result_id": str(result_id) if result_id else None,
                "verification_id": str(verification_id),
                "reason_code": error_code,
            },
        ))
        session.commit()
        return V4RunResult(True, attempt_id, live.status, error_code)

    def _load_input(self, session: Session, attempt: PrespecV4Attempt, binding: V4ModelBinding) -> tuple[PrespecV4Target, PrespecV4PdfSnapshot, dict[str, Any], dict[int, str]]:
        target = session.get(PrespecV4Target, attempt.target_id)
        snapshot = session.get(PrespecV4PdfSnapshot, target.snapshot_id) if target is not None else None
        if target is None or snapshot is None or target.selection_status != "ready" or target.notice_id != attempt.notice_id:
            raise V4AttemptError("input_scope_mismatch")
        document = session.get(DocumentVersion, target.document_version_id)
        if document is None or not document.is_current or document.safety_status != "safe" or document.notice_id != target.notice_id:
            raise V4AttemptError("document_not_current_or_safe")
        if attempt.document_version_id != document.id or attempt.policy_digest != binding.policy_digest or attempt.model_name != binding.model_name or attempt.model_digest != binding.model_digest or attempt.prompt_version != binding.prompt_version or attempt.binding_digest != binding.binding_digest:
            raise V4AttemptError("binding_mismatch")
        source = session.get(ContentObject, document.content_object_id)
        if source is None or snapshot.source_sha256 != source.sha256:
            raise V4AttemptError("source_hash_mismatch")
        pdf = session.get(ContentObject, snapshot.pdf_content_object_id)
        if pdf is None or _latest_clean_scan(session, pdf.id) is None:
            raise V4AttemptError("pdf_scan_unavailable")
        store = self.object_store
        if store is None:
            try:
                from ...core.object_store import object_store
                store = object_store(namespaces=("structure",), read_namespaces=("structure",))
                self.object_store = store
            except (ObjectStoreError, OSError, ValueError) as error:
                raise V4AttemptError("object_store_unavailable") from error
        manifest, pages = _load_manifest(session, store, target)
        return target, snapshot, _model_input(manifest, pages), pages

    def _store_raw(self, session: Session, raw: bytes) -> str:
        if self.raw_response_store is None:
            self.raw_response_store = EncryptedModelResponseStore(self.settings or get_settings())
        return store_raw_model_response(session, raw, store=self.raw_response_store, clock=self.clock)

    def _store_error_raw(self, session: Session, error: ModelInvocationError) -> str | None:
        """실패 응답 원본도 감사로 남긴다. 저장 실패는 실패 사유를 덮지 않는다."""

        raw = getattr(error, "raw_response", None)
        if not isinstance(raw, (bytes, bytearray)):
            return None
        try:
            stored = self._store_raw(session, bytes(raw))
            session.commit()
            return stored
        except Exception:
            return None

    def _complete(self, session: Session, attempt: PrespecV4Attempt, target: PrespecV4Target, snapshot: PrespecV4PdfSnapshot, output: Mapping[str, Any], raw_sha: str, response: Any, worker_id: str, pages: Mapping[int, str], binding: V4ModelBinding, retry: Mapping[str, Any] | None = None) -> None:
        live, locked_target, locked_snapshot = self._live_attempt(
            session, attempt.id, worker_id, binding
        )
        if locked_target.id != target.id or locked_snapshot.id != snapshot.id:
            raise V4AttemptError("input_scope_mismatch")
        document = session.get(DocumentVersion, target.document_version_id)
        if document is None or not document.is_current or document.safety_status != "safe" or document.notice_id != live.notice_id:
            raise V4AttemptError("document_not_current_or_safe")
        source = session.get(ContentObject, document.content_object_id)
        if source is None or live.policy_digest != binding.policy_digest or live.model_name != binding.model_name or live.model_digest != binding.model_digest or live.prompt_version != binding.prompt_version or live.binding_digest != binding.binding_digest or snapshot.source_sha256 != source.sha256:
            raise V4AttemptError("binding_mismatch")
        payload = PageOverviewPayload.model_validate(output)
        # 경고는 실패가 아니다. 완료된 attempt에 목록으로 남기고 재시도 사유로 쓰지 않는다.
        errors, warnings = validate_page_overview_detailed(output, dict(pages))
        if errors:
            raise V4AttemptError(errors[0])
        payload_json = payload.model_dump(mode="json")
        payload_sha = _sha256_json(payload_json)
        import_sha = _sha256_json({"attempt_id": str(live.id), "target_id": str(target.id), "payload_sha256": payload_sha, "binding_digest": live.binding_digest})
        result = PreSpecPageOverview(
            id=uuid4(), run_id=live.id, notice_id=live.notice_id, document_version_id=target.document_version_id,
            input_location_id=target.manifest_location_id, pdf_location_id=snapshot.pdf_location_id,
            schema_version=payload.schema_version, source_sha256=snapshot.source_sha256, pdf_sha256=snapshot.pdf_sha256,
            payload_sha256=payload_sha, import_sha256=import_sha, input_sha256=target.input_sha256,
            model_digest=live.model_digest, policy_digest=live.policy_digest, model_name=live.model_name,
            prompt_version=live.prompt_version, pdf_page_count=snapshot.pdf_page_count,
            reviewed_pages=list(target.page_numbers_jsonb or []), payload_jsonb=payload_json,
            validation_status="passed", validation_errors=[], evidence_check_status="passed",
            evidence_check_errors=[], validator_version=VALIDATOR_VERSION, quality_status=live.quality_status,
        )
        session.add(result)
        session.flush()
        live.result_id = result.id
        live.result_sha256 = payload_sha
        live.raw_response_sha256 = raw_sha
        live.validation_warnings = list(warnings)
        live.status = "completed"
        live.completed_at = self.clock()
        live.lease_owner = None
        live.lease_expires_at = None
        live.prompt_tokens = getattr(response, "prompt_tokens", None)
        live.output_tokens = getattr(response, "output_tokens", None)
        live.latency_ms = getattr(response, "latency_ms", None)
        if live.work_job_id is not None:
            job = session.scalar(
                select(WorkJob).where(WorkJob.id == live.work_job_id).with_for_update()
            )
            if job is not None:
                job.status = "completed"
                job.completed_at = live.completed_at
                job.lease_owner = None
                job.lease_expires_at = None
        session.add(AuditEvent(actor_kind="system", claimed_name=None, action="prespec_v4.attempt_run", aggregate_type="prespec_v4_attempt", aggregate_id=str(live.id), safe_metadata={"notice_id": live.notice_id, "status": "completed", "result_id": str(result.id), "raw_response_sha256": raw_sha, "validation_retry": dict(retry) if retry else None, "validation_warnings": list(warnings)}))
        session.commit()

    def _fail(self, session: Session, attempt_id: UUID, worker_id: str, reason_code: str, raw_sha: str | None, retry: Mapping[str, Any] | None = None) -> V4RunResult:
        session.rollback()
        lock_v4_gate(session)
        _expire_v4_attempts(session, now=self.clock())
        attempt = session.scalar(select(PrespecV4Attempt).where(PrespecV4Attempt.id == attempt_id).with_for_update())
        code = _safe_error_code(reason_code, "runner_failed")
        if (
            attempt is not None
            and attempt.status == "failed"
            and attempt.error_code == "lease_expired"
        ):
            session.commit()
            return V4RunResult(True, attempt_id, "failed", "lease_expired")
        from .prespec_v4_ops import v4_dispatch_enabled
        activation = v4_dispatch_enabled(session, settings=self._activation_settings())
        if (
            attempt is None
            or attempt.status != "running"
            or attempt.lease_owner != worker_id
            or attempt.lease_expires_at is None
            or attempt.lease_expires_at <= self.clock()
            or activation is None
            or attempt.activation_id != activation.activation_id
        ):
            session.rollback()
            return V4RunResult(True, attempt_id, "stale", "stale_attempt")
        attempt.status = "failed"
        attempt.error_code = code
        attempt.raw_response_sha256 = raw_sha
        attempt.completed_at = self.clock()
        attempt.lease_owner = None
        attempt.lease_expires_at = None
        if attempt.work_job_id is not None:
            job = session.scalar(
                select(WorkJob).where(WorkJob.id == attempt.work_job_id).with_for_update()
            )
            if job is not None:
                job.status = "failed"
                job.last_error_code = code
                job.completed_at = attempt.completed_at
                job.lease_owner = None
                job.lease_expires_at = None
        session.add(AuditEvent(actor_kind="system", claimed_name=None, action="prespec_v4.attempt_run", aggregate_type="prespec_v4_attempt", aggregate_id=str(attempt.id), safe_metadata={"notice_id": attempt.notice_id, "status": "failed", "reason_code": code, "raw_response_sha256": raw_sha, "validation_retry": dict(retry) if retry else None}))
        session.commit()
        return V4RunResult(True, attempt_id, "failed", code)


def _payload_hash_matches(result: PreSpecPageOverview | None) -> bool:
    if result is None:
        return False
    try:
        return _sha256_json(result.payload_jsonb) == result.payload_sha256
    except (TypeError, ValueError, OverflowError, RecursionError, V4PreparationError):
        return False


def _project_v4_current(
    *,
    notice_id: int,
    attempt: PrespecV4Attempt | None,
    target: PrespecV4Target | None,
    latest_target: PrespecV4Target | None,
    snapshot: PrespecV4PdfSnapshot | None,
    document: DocumentVersion | None,
    source: ContentObject | None,
    pdf: ContentObject | None,
    latest_scan: ContentScan | None,
    result: PreSpecPageOverview | None,
    verification: PrespecOverviewVerification | None,
    policy: V4OverviewPolicy | None,
    model_revision: str | None,
) -> dict[str, Any] | None:
    if attempt is None:
        if latest_target is None or latest_target.selection_status == "ready":
            return None
        return {
            "attempt_id": None,
            "status": "needs_human_review",
            "result_id": None,
            "reason_code": latest_target.reason_code,
            "prompt_version": None,
            "created_at": latest_target.created_at,
        }

    status = attempt.status
    result_id = attempt.result_id
    reason = attempt.error_code
    if (latest_target is not None and latest_target.id != attempt.target_id
            and status in {"queued", "running", "completed"}):
        # A human may replace an already reviewed range. Keep its immutable
        # result in history, but never offer it as the new range's current input.
        status, result_id, reason = "stale", None, "target_superseded"
    input_current = (
        target is not None
        and target.selection_status == "ready"
        and snapshot is not None
        and document is not None
        and source is not None
        and pdf is not None
        and latest_scan is not None
        and latest_scan.status == "clean"
        and target.notice_id == notice_id
        and target.document_version_id == attempt.document_version_id
        and snapshot.notice_id == notice_id
        and snapshot.document_version_id == target.document_version_id
        and document.is_current
        and document.safety_status == "safe"
        and not document.needs_human_review
        and snapshot.source_sha256 == source.sha256
        and snapshot.source_size_bytes == source.size_bytes
        and snapshot.pdf_sha256 == pdf.sha256
        and snapshot.pdf_size_bytes == pdf.size_bytes
        and pdf.detected_mime == "application/pdf"
        and attempt.source_sha256 == snapshot.source_sha256
        and attempt.pdf_sha256 == snapshot.pdf_sha256
        and attempt.input_sha256 == target.input_sha256
        and attempt.selection_manifest_sha256 == target.selection_manifest_sha256
        and policy is not None
        and attempt.policy_digest == policy.digest
        and (
            (
                attempt.provider == V4_LUNA_REFERENCE_PROVIDER
                and attempt.model_name == V4_LUNA_REFERENCE_MODEL
            )
            or (
                attempt.provider != V4_LUNA_REFERENCE_PROVIDER
                and attempt.model_name == policy.model_name
            )
        )
        and attempt.prompt_version == policy.prompt_version
        and attempt.model_digest == model_revision
        and attempt.binding_digest == _sha256_json({
            "provider": attempt.provider,
            "model_name": attempt.model_name,
            "model_digest": attempt.model_digest,
            "prompt_version": attempt.prompt_version,
            "policy_digest": attempt.policy_digest,
            "reference_only": bool(attempt.reference_only),
            "deployable": bool(attempt.deployable),
        })
    )
    if status in {"queued", "running"} and not input_current:
        status, result_id, reason = "stale", None, "input_integrity_failed"
    if status == "completed":
        is_claims_result = result is not None and result.schema_version == "bidops.prespec-overview-page-review.v4"
        verification_current = True
        if is_claims_result:
            try:
                parsed_payload = PageOverviewPayloadV4.model_validate_json(
                    json.dumps(result.payload_jsonb, ensure_ascii=False)
                )
                verification_current = (
                    verification is not None
                    and verification.attempt_id == attempt.id
                    and verification.overall == "passed"
                    and verification.input_sha256 == attempt.input_sha256
                    and verification.policy_digest == attempt.policy_digest
                    and verification.binding_digest == attempt.binding_digest
                    and verification.model_digest == attempt.model_digest
                    and canonical_sha256(verification.payload_jsonb) == verification.payload_sha256
                    and parsed_payload.verification_id == verification.id
                    and parsed_payload.verification_sha256 == verification.payload_sha256
                    and not validate_composed_page_overview(
                        parsed_payload, verification.payload_jsonb
                    )
                )
            except (TypeError, ValueError):
                verification_current = False
        result_current = (
            input_current
            and result is not None
            and result.notice_id == notice_id
            and result.document_version_id == target.document_version_id
            and result.source_sha256 == snapshot.source_sha256
            and result.pdf_sha256 == snapshot.pdf_sha256
            and result.input_sha256 == target.input_sha256
            and result.policy_digest == attempt.policy_digest
            and result.model_name == attempt.model_name
            and result.model_digest == attempt.model_digest
            and result.prompt_version == attempt.prompt_version
            and result.validation_status == "passed"
            and result.evidence_check_status == "passed"
            and _payload_hash_matches(result)
            and verification_current
        )
        if not result_current:
            status, result_id, reason = "stale", None, "result_integrity_failed"
    return {
        "attempt_id": attempt.id,
        "status": status,
        "result_id": result_id,
        "reason_code": reason,
        "prompt_version": attempt.prompt_version,
        "created_at": attempt.created_at,
    }


def current_v4_projections(
    session: Session, notice_ids: Sequence[int]
) -> dict[int, dict[str, Any] | None]:
    """Project current v4 state for a bounded batch with one query per relation."""

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return {}
    attempts = session.scalars(
        select(PrespecV4Attempt)
        .where(PrespecV4Attempt.notice_id.in_(ids))
        .order_by(PrespecV4Attempt.created_at.desc(), PrespecV4Attempt.sequence.desc())
    ).all()
    attempt_by_notice: dict[int, PrespecV4Attempt] = {}
    for row in attempts:
        attempt_by_notice.setdefault(int(row.notice_id), row)

    targets = session.scalars(
        select(PrespecV4Target)
        .where(PrespecV4Target.notice_id.in_(ids))
        .order_by(PrespecV4Target.created_at.desc(), PrespecV4Target.id.desc())
    ).all()
    if not attempts and not targets:
        return {notice_id: None for notice_id in ids}
    target_by_id = {row.id: row for row in targets}
    latest_target_by_notice: dict[int, PrespecV4Target] = {}
    for row in targets:
        latest_target_by_notice.setdefault(int(row.notice_id), row)

    snapshot_ids = {row.snapshot_id for row in targets}
    snapshots = session.scalars(
        select(PrespecV4PdfSnapshot).where(PrespecV4PdfSnapshot.id.in_(snapshot_ids))
    ).all() if snapshot_ids else []
    snapshot_by_id = {row.id: row for row in snapshots}

    document_ids = {row.document_version_id for row in targets}
    documents = session.scalars(
        select(DocumentVersion).where(DocumentVersion.id.in_(document_ids))
    ).all() if document_ids else []
    document_by_id = {row.id: row for row in documents}

    content_ids = {row.content_object_id for row in documents}
    content_ids.update(row.source_content_object_id for row in snapshots)
    content_ids.update(row.pdf_content_object_id for row in snapshots)
    contents = session.scalars(
        select(ContentObject).where(ContentObject.id.in_(content_ids))
    ).all() if content_ids else []
    content_by_id = {row.id: row for row in contents}

    pdf_ids = {row.pdf_content_object_id for row in snapshots}
    scans = session.scalars(
        select(ContentScan)
        .where(ContentScan.content_object_id.in_(pdf_ids))
        .order_by(ContentScan.scanned_at.desc(), ContentScan.id.desc())
    ).all() if pdf_ids else []
    latest_scan_by_content: dict[UUID, ContentScan] = {}
    for row in scans:
        latest_scan_by_content.setdefault(row.content_object_id, row)

    result_ids = {row.result_id for row in attempts if row.result_id is not None}
    results = session.scalars(
        select(PreSpecPageOverview).where(PreSpecPageOverview.id.in_(result_ids))
    ).all() if result_ids else []
    result_by_id = {row.id: row for row in results}

    attempt_ids = {row.id for row in attempts}
    verifications = session.scalars(
        select(PrespecOverviewVerification).where(
            PrespecOverviewVerification.attempt_id.in_(attempt_ids)
        )
    ).all() if attempt_ids else []
    verification_by_attempt = {row.attempt_id: row for row in verifications}

    try:
        policy = load_v4_policy()
    except V4AttemptError:
        policy = None
    try:
        legacy_policy = load_v4_policy(V4_LEGACY_POLICY_PATH)
    except V4AttemptError:
        legacy_policy = None
    try:
        model_revision = resolve_model_endpoint("overview").model_revision
    except (ModelEndpointError, ModelIdentityError, ValueError, OSError):
        model_revision = None

    output: dict[int, dict[str, Any] | None] = {}
    for notice_id in ids:
        attempt = attempt_by_notice.get(notice_id)
        target = target_by_id.get(attempt.target_id) if attempt is not None and attempt.target_id is not None else None
        snapshot = snapshot_by_id.get(target.snapshot_id) if target is not None else None
        document = document_by_id.get(target.document_version_id) if target is not None else None
        source = content_by_id.get(document.content_object_id) if document is not None else None
        pdf = content_by_id.get(snapshot.pdf_content_object_id) if snapshot is not None else None
        result = result_by_id.get(attempt.result_id) if attempt is not None and attempt.result_id is not None else None
        projection_model_revision = (
            attempt.model_digest
            if attempt is not None and attempt.provider == V4_LUNA_REFERENCE_PROVIDER
            else model_revision
        )
        projection_policy = policy
        if (
            attempt is not None
            and legacy_policy is not None
            and attempt.policy_digest == legacy_policy.digest
        ):
            projection_policy = legacy_policy
        output[notice_id] = _project_v4_current(
            notice_id=notice_id,
            attempt=attempt,
            target=target,
            latest_target=latest_target_by_notice.get(notice_id),
            snapshot=snapshot,
            document=document,
            source=source,
            pdf=pdf,
            latest_scan=latest_scan_by_content.get(pdf.id) if pdf is not None else None,
            result=result,
            verification=verification_by_attempt.get(attempt.id) if attempt is not None else None,
            policy=projection_policy,
            model_revision=projection_model_revision,
        )
    return output


def current_v4_projection(session: Session, notice_id: int) -> dict[str, Any] | None:
    """Return one notice's current projection through the shared batch path."""

    return current_v4_projections(session, [notice_id]).get(int(notice_id))


__all__ = [
    "V4AttemptError", "V4ModelBinding", "V4OverviewPolicy", "V4RunResult",
    "PrespecV4OverviewRunner", "V4_LEASE_SECONDS", "V4_STAGE", "load_v4_policy",
    "V4_LUNA_REFERENCE_MODEL", "V4_LUNA_REFERENCE_PROVIDER",
    "approved_v4_binding", "enqueue_v4_attempt", "record_v4_preparation_failure",
    "current_v4_projection", "current_v4_projections",
]
