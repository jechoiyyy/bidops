"""Deep-review lifecycle, bounded stage execution, and lease-fenced writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import time
import hashlib
import json
import logging
import os
import re
from copy import deepcopy
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.models import AuditEvent, IdempotencyRecord
from ..models import (
    AnalysisPolicyVersion,
    Claim,
    ClaimEvidence,
    ContentObject,
    ContentObjectLocation,
    DeepReview,
    DeepReviewAttempt,
    DeepReviewStage,
    EvidenceRef,
    ProfileVersion,
    WorkJob,
)
from ...lifecycle import lock_notice
from ...core.config import get_settings
from .deep_review_validation import DeepReviewValidationError, merge_stage_chunks, validate_deep_review_stage
from ...core.model_binding import canonical_json_bytes
from .effective_grade import eligible_with_grade
from .input_versions import (
    STAGES,
    GradeBasis,
    InputVersionError,
    bundle_context,
    effective_grade_basis,
    profile_context,
    policy_quality_snapshot,
    resolve_active_versions,
    validate_pinned_policy,
)
from .luna_identity import (
    CLI_VERSION,
    COMPANY_POLICY_IDENTITIES,
    matches_runtime,
    policy_reasoning_effort,
)
from ...core.model_binding import MODEL_ENDPOINT_REF
from ...core.model_client import (
    APPROVED_RETRIES,
    APPROVED_TIMEOUT_SECONDS,
    EncryptedObjectStore,
    InvocationResult,
    ModelClient,
    ModelEndpointError,
    ModelIdentityError,
    ModelInvocationError,
)
from .deep_review_vllm import DEEP_REVIEW_STAGE_CONTRACT, NARRATIVE_STAGE_CONTRACT
from . import company_slices, narrative_inputs, document_segments, luna_inputs
from .mock_analysis_client import MOCK_MODEL_NAME, MockAnalysisClient
from ...core.constants import (
    DEEP_REVIEW_CREATION_ACTION_BY_ACTOR_KIND,
    DEEP_REVIEW_CREATION_ACTIONS,
)
from ...core.object_store import EncryptedModelResponseStore


STAGE_SEQUENCE = {name: index for index, name in enumerate(STAGES, start=1)}
MOCK_ANALYSIS_PROVIDER = "mock-analysis"
MODEL_PURPOSE = "deep_review"
logger = logging.getLogger(__name__)
#: 심층 검토를 만든 감사 action. 사람 클릭과 §6.4의 자동 시작 둘뿐이다.
#: 정본은 `core.constants`다 — 의존성 없는 agent projection도 같은 표를 읽는다.
CREATION_ACTION_BY_ACTOR_KIND = DEEP_REVIEW_CREATION_ACTION_BY_ACTOR_KIND
CREATION_ACTIONS = DEEP_REVIEW_CREATION_ACTIONS
MIN_LEASE_SECONDS = APPROVED_TIMEOUT_SECONDS * (APPROVED_RETRIES + 1) + 60
WORKER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
EMPTY_PRIOR_CLAIM_ID = uuid5(NAMESPACE_URL, "bidops.deep-review.empty-prior-claim")
_SAFE_INVOCATION_ATTEMPT_KEYS = frozenset({
    # 정수·bool·hex만 남긴다. 프롬프트·응답 본문과 떼어 낸 사고 문자열은 들어오지 않는다.
    "retry_index", "status", "error_code", "latency_ms",
    "seed", "correction_sha256", "thinking_stripped", "thinking_chars",
})
_SAFE_INVOCATION_KEYS = frozenset({
    "slice_index", "input_slice_sha256", "prompt_sha256", "response_sha256",
    "model", "policy_sha256", "prompt_tokens", "output_tokens", "latency_ms",
    "status", "error_code", "retry_index", "fixed_input_hash", "safe",
    "attempts", "provider", "cli_version", "reasoning_effort",
    "validation_repair_attempt", "validation_repair_issues",
})

_NARRATIVE_ERROR_PATHS = {
    "narrative_schema_required": "$.schema",
    "considered_claim_out_of_slice": "$.considered_claim_ids",
    "source_coverage_mismatch": "$.coverage",
    "requirement_coverage_mismatch": "$.claims[*].requirement_ids",
    "claim_source_out_of_slice": "$.claims[*].source_unit_ids",
    "coverage_claim_missing": "$.coverage[*].claim_ids",
    "coverage_without_analysis": "$.coverage[*].claim_ids",
    "synthesis_source_out_of_slice": "$.claims[*].source_unit_ids",
    "synthesis_coverage_mismatch": "$.considered_claim_ids",
    "synthesis_claim_omission": "$.claims[*].related_claim_ids",
    "recommendation_scope_mismatch": "$.claims[*].narrative_role",
    "claim_relation_out_of_slice": "$.claims[*].related_claim_ids|premise_claim_ids",
    "evidence_out_of_slice": "$.claims[*].evidence_ids",
    "document_evidence_out_of_slice": "$.evidence[*]",
    "profile_evidence_out_of_slice": "$.evidence[*].profile_evidence_id",
    "local_identifier_redefinition": "$.claims[*].claim_id|evidence[*].evidence_id",
    "local_identifier_invalid": "$.claims[*].claim_id|evidence[*].evidence_id",
    # Company (DEMO-03) slice check: a cited profile evidence must copy the
    # supplied row's profile_version_id, source_sha256, locator and quote.
    "profile_evidence_mismatch": "$.evidence[*]",
}


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


def _validate_actor_kind(actor_kind: str) -> str:
    """심층 검토를 만들 수 있는 actor 종류는 사람과 시스템 둘뿐이다 (§6.4)."""

    if actor_kind not in CREATION_ACTION_BY_ACTOR_KIND:
        raise DeepReviewServiceError("invalid_request", "actor 종류가 올바르지 않습니다", status_code=400)
    return actor_kind


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


def _policy_execution_limit(
    policy: Mapping[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    execution = policy.get("execution", {})
    if not isinstance(execution, Mapping):
        raise DeepReviewServiceError("service_unavailable", "analysis policy execution 설정이 올바르지 않습니다", status_code=503)
    value = execution.get(key, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise DeepReviewServiceError("service_unavailable", f"analysis policy {key} 설정이 올바르지 않습니다", status_code=503)
    return value


def _safe_issue_path(path: Any) -> str:
    """Return a bounded field-only JSON path for repair feedback."""

    if not isinstance(path, str) or not path.startswith("$"):
        return "$"
    clean = re.sub(r"\[\d+\]", "[*]", path)
    if len(clean) > 160 or not re.fullmatch(r"\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\*\])*", clean):
        return "$"
    return clean


def _validation_repair_issues(error: Exception) -> list[dict[str, str]]:
    """Project validator failures to code + field location only.

    Model text, quotes, validator messages, and identifiers never enter the
    correction prompt or persisted diagnostics.
    """

    if isinstance(error, narrative_inputs.NarrativeInputError):
        code = error.code if re.fullmatch(r"[a-z0-9_]{1,80}", error.code) else "narrative_invalid"
        return [{"code": f"narrative:{code}", "path": _NARRATIVE_ERROR_PATHS.get(code, "$")}]
    if isinstance(error, DeepReviewValidationError):
        result: list[dict[str, str]] = []
        for issue in error.issues[:20]:
            code = issue.code if re.fullmatch(r"[a-z0-9_]{1,80}", issue.code) else "contract_invalid"
            row = {"code": f"validation:{code}", "path": _safe_issue_path(issue.path)}
            if row not in result:
                result.append(row)
        return result or [{"code": "validation:contract_invalid", "path": "$"}]
    if isinstance(error, ModelInvocationError) and error.code == "schema_invalid":
        return [{"code": "schema_invalid", "path": "$"}]
    return []


def _resolve_exact_evidence_quotes(
    payload: Mapping[str, Any],
    structures: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve presentation differences within the pinned locator scope.

    V2 page locators may span contiguous blocks on that page. Paragraph/cell
    locators remain confined to their block. Ambiguous or changed content is
    left untouched for validation; raw model responses are preserved.
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
        if payload.get("schema") == "bidops.deep-review-stage.v2":
            from .quote_matching import page_texts, source_quote
            if evidence.get("locator_type") == "page":
                texts = page_texts(blocks)
            matched = source_quote(quote, texts)
            if matched is not None:
                evidence["quote"] = matched
            continue
        tokens = re.findall(r"\S+", quote)
        if not tokens:
            continue
        pattern = re.compile(r"\s+".join(re.escape(token) for token in tokens))
        matches = [match.group(0) for text in texts for match in pattern.finditer(text)]
        if len(matches) == 1:
            evidence["quote"] = matches[0]
    return resolved


_CARD_DERIVATION_KEYS = frozenset({
    "extract_contract", "code_derived_fields", "repair_rule_codes",
    # 결정 B55: synthesis contract v2 (code-computed blocking ids and person-check rows).
    "synthesis_contract", "synthesis_code_derived_fields",
})
_CARD_DERIVATION_CONTRACTS = {
    "extract_contract": "bidops.requirement-extract.v2",
    "synthesis_contract": "bidops.practitioner-verdict.v2",
}
#: 결정 B55: audit actions of a synthesis-only resume (request link, reused rows).
CARD_RESUME_REQUESTED_ACTION = "card.resume.requested"
CARD_STAGES_REUSED_ACTION = "card.stages.reused"


def _card_derivation_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """결정 B33: only the closed code-only keys (contract name, field names, rule codes)."""

    if value is None:
        return {}
    if not isinstance(value, Mapping) or not set(value) <= _CARD_DERIVATION_KEYS:
        raise DeepReviewServiceError("processing_failed", "카드 분석 감사 값이 올바르지 않습니다", status_code=500)
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in _CARD_DERIVATION_CONTRACTS:
            if item != _CARD_DERIVATION_CONTRACTS[key]:
                raise DeepReviewServiceError("processing_failed", "카드 분석 감사 값이 올바르지 않습니다", status_code=500)
            result[key] = item
        else:
            if not isinstance(item, (list, tuple)) or any(
                not isinstance(text, str) or re.fullmatch(r"[a-z][a-z0-9_.]{2,63}", text) is None for text in item
            ):
                raise DeepReviewServiceError("processing_failed", "카드 분석 감사 값이 올바르지 않습니다", status_code=500)
            result[key] = list(item)
    return result


def card_resume_source_id(session: Session, attempt_id: UUID) -> UUID | None:
    """결정 B55: the source attempt linked to ``attempt_id`` at request time (``card.resume.requested``)."""

    rows = session.scalars(select(AuditEvent).where(
        AuditEvent.action == CARD_RESUME_REQUESTED_ACTION,
        AuditEvent.aggregate_type == "deep_review_attempt",
        AuditEvent.aggregate_id == str(attempt_id),
    )).all()
    if not rows:
        return None
    sources = {str((row.safe_metadata or {}).get("source_attempt_id")) for row in rows}
    if len(sources) != 1:
        raise DeepReviewServiceError("resume_source_invalid", "재실행 원본이 하나가 아닙니다", status_code=409)
    try:
        return UUID(sources.pop())
    except ValueError:
        raise DeepReviewServiceError("resume_source_invalid", "재실행 원본이 올바르지 않습니다", status_code=409) from None


def card_resume_check(
    session: Session,
    *,
    source_attempt_id: UUID,
    company_id: UUID,
    notice_id: int,
    frozen: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[Any]:
    """결정 B55: the reusable non-synthesis stage rows of ``source_attempt_id`` or ``resume_source_invalid``.

    The source is a card-v1 attempt of the same company/notice that ended
    ``failed`` (or was ``superseded``) without a final verdict, with every
    extract/compare batch and all three role rows, whose approved frozen input
    and policy pass ``resume_lineage_valid`` against the new attempt's.  The
    worker additionally recomputes every reused stage input (``CardResume``).
    """

    from ..models import CardAnalysisStage
    from .card_analysis import resume_lineage_valid

    def invalid() -> DeepReviewServiceError:
        return DeepReviewServiceError("resume_source_invalid", "재실행 원본을 쓸 수 없습니다", status_code=409)

    source = session.get(DeepReviewAttempt, source_attempt_id)
    review = session.get(DeepReview, source.deep_review_id) if source is not None else None
    if (
        source is None or review is None or source.status not in {"failed", "superseded"}
        or review.company_id != company_id or int(review.notice_id) != int(notice_id)
    ):
        raise invalid()
    source_policy = session.get(AnalysisPolicyVersion, review.policy_version_id)
    if source_policy is None:
        raise invalid()
    try:
        # The same approved-input gate the worker applies (hash, lineage, nonce, target).
        source_frozen = luna_inputs.approved_company_input(session, source.id, review)
    except InputVersionError:
        raise invalid() from None
    if not resume_lineage_valid(source_frozen, _policy_payload(source_policy), frozen, policy):
        raise invalid()
    rows = session.scalars(select(CardAnalysisStage).where(CardAnalysisStage.attempt_id == source.id)).all()
    batches = {str(row["batch_index"]) for row in source_frozen["card_analysis"]["batches"]}
    keys = {(row.stage, row.stage_key) for row in rows}
    expected = ({("extract", key) for key in batches} | {("compare", key) for key in batches}
                | {("role", role) for role in ("eligibility_economics", "technical_fit", "operations_risk")})
    if keys != expected:
        raise invalid()
    return list(rows)


def card_resume_for_attempt(
    session: Session,
    attempt: DeepReviewAttempt,
    *,
    frozen: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> Any:
    """결정 B55: the ``CardResume`` of a resume attempt (re-checked in the worker), else ``None``."""

    from .card_analysis import CardResume

    source_id = card_resume_source_id(session, attempt.id)
    if source_id is None:
        return None
    review = session.get(DeepReview, attempt.deep_review_id)
    if review is None or review.company_id is None:
        raise DeepReviewServiceError("resume_source_invalid", "재실행 원본을 쓸 수 없습니다", status_code=409)
    rows = card_resume_check(
        session, source_attempt_id=source_id, company_id=review.company_id, notice_id=int(review.notice_id),
        frozen=frozen, policy=policy,
    )
    return CardResume(source_id, rows)


def _add_job_audit(
    session: Session,
    *,
    action: str,
    job_id: UUID | str,
    review_id: UUID | str | None,
    attempt_id: UUID | str | None,
    fence: int,
    status: str,
    extra_safe_metadata: Mapping[str, Any] | None = None,
) -> None:
    """Append only safe system metadata inside the fenced transition txn.

    ``extra_safe_metadata`` (RL-03 card-v1: stage keys, counts, hashes,
    elapsed seconds) may add keys but never replace the base ones.
    """

    metadata: dict[str, Any] = {
        "job_id": str(job_id),
        "review_id": str(review_id) if review_id is not None else None,
        "attempt_id": str(attempt_id) if attempt_id is not None else None,
        "lease_fence": int(fence),
        "status": status,
    }
    if extra_safe_metadata:
        if set(metadata) & set(extra_safe_metadata):
            raise ValueError("job_audit_metadata_conflict")
        metadata.update(dict(extra_safe_metadata))
    session.add(AuditEvent(
        actor_kind="system",
        claimed_name=None,
        action=action,
        aggregate_type="work_job",
        aggregate_id=str(job_id),
        request_id=None,
        safe_metadata=metadata,
    ))


def _idempotency_hash(operation: str, payload: Mapping[str, Any]) -> str:
    return _canonical_hash({"operation": operation, **dict(payload)})


def _policy_payload(policy: AnalysisPolicyVersion) -> dict[str, Any]:
    rules = dict(policy.validation_rules) if isinstance(policy.validation_rules, Mapping) else {}
    if isinstance(rules.get("policy_snapshot"), Mapping):
        return {**deepcopy(rules["policy_snapshot"]), "policy_sha256": policy.policy_sha256}
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
    actions: Sequence[str],
    aggregate_type: str,
    aggregate_id: str,
) -> UUID | None:
    """Read one immutable lineage value without backfilling legacy audits.

    ``actions``는 "이 aggregate를 만든 감사"의 후보다. 심층 검토는 사람 클릭과
    자동 시작 둘 중 하나로 만들어지므로 한쪽만 보면 계보가 비어 보인다.
    """

    rows = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action.in_(tuple(actions)),
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


def quality_status_for_review(session: Session, review_id: UUID) -> str | None:
    """생성 감사 이벤트에서 이 심층 검토의 모델 실행 품질 상태를 계산한다 (명세 §8).

    순서가 규칙이다. mock provider면 `mock_reference`, 그 밖에 참조 모드였으면
    `unmeasured_reference`, 측정값이 배치 가능(`deployable`)하면 `measured`다.
    **감사 이벤트가 없거나 어느 것도 아니면 `None`이다.** 없음을 미측정이나
    측정으로 바꾸지 않는다 — 필드가 없던 시절의 실행은 표식 없음으로 남는다.
    """

    return quality_status_for_reviews(session, [review_id]).get(review_id)


def quality_status_for_reviews(session: Session, review_ids: Sequence[UUID]) -> dict[UUID, str | None]:
    """같은 규칙을 여러 심층 검토에 **상수 회 조회**로 적용한다 (명세 §8).

    목록 화면이 건별로 부르면 N+1이 된다. 단건 함수는 이 배치판을 부른다.
    """

    ids = {str(review_id): review_id for review_id in review_ids}
    if not ids:
        return {}
    metadata_by_id: dict[str, Any] = {}
    for aggregate_id, metadata in session.execute(
        select(AuditEvent.aggregate_id, AuditEvent.safe_metadata)
        .where(
            AuditEvent.action.in_(CREATION_ACTIONS),
            AuditEvent.aggregate_type == "deep_review",
            AuditEvent.aggregate_id.in_(ids),
        )
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
    ).all():
        metadata_by_id.setdefault(aggregate_id, metadata)
    return {review_id: _quality_status(metadata_by_id.get(key)) for key, review_id in ids.items()}


def _quality_status(metadata: Any) -> str | None:
    if not isinstance(metadata, Mapping):
        return None
    if metadata.get("analysis_provider") == MOCK_ANALYSIS_PROVIDER:
        return "mock_reference"
    if metadata.get("reference_workflow_mode") is True:
        return "unmeasured_reference"
    quality = metadata.get("policy_quality")
    if isinstance(quality, Mapping) and quality.get("deployable") is True:
        return "measured"
    return None


class DeepReviewService:
    """Owns review/attempt/job state while keeping model I/O transaction-free."""

    def __init__(
        self,
        *,
        client: ModelClient | Any | None = None,
        raw_response_store: EncryptedObjectStore | Any | None = None,
        structure_loader: Callable[[Session, Any], Mapping[str, Any]] | None = None,
        report_service: Any | None = None,
        lease_seconds: int = 300,
        clock: Callable[[], datetime] = _now,
        verdict_completed_notifier: Callable[[Session, UUID], Any] | None = None,
    ) -> None:
        settings = get_settings()
        self.settings = settings
        # 심층 검토가 부르는 모델명은 policy의 `model_name`이다. 그 값은 review가
        # policy를 고정한 뒤에야 정해지므로 vLLM client는 여기서 만들지 않고
        # 실행 직전에 `_bind_client`가 용도별 설정으로 만든다. 미리 만들면
        # 모델명을 설정에서 다시 읽게 되고, 실행 row에 기록되는 policy 모델명과
        # 실제로 부른 모델이 갈린다.
        if client is not None:
            self._client = client
        elif settings.analysis_provider == "mock":
            self._client = MockAnalysisClient()
        else:
            self._client = None
        # 주입·mock client는 policy 모델명에 묶이지 않는다. 그 밖의 client는
        # `_bind_client`가 만든 것이고, 어느 모델명으로 만들었는지를 여기에
        # 남겨야 policy가 다른 job이 남의 client를 물려받지 않는다.
        self._injected_client = self._client is not None
        self._bound_model_name: str | None = None
        # 참조 실행 모드는 provider와 무관하다(명세 §6.5). mock provider는
        # 설정 검증이 이 모드를 필수로 요구하고, vLLM 경로도 이 모드에서는
        # 측정값 없는 policy로 실행할 수 있다.
        self.reference_workflow_mode = bool(settings.reference_workflow_mode)
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
        # RL-03 "Slack 스레드": card-v1 attempt가 completed로 commit된 직후 한 번 부른다.
        # 기본은 `verdict_links.notify_verdict_completed`(브리핑 메시지 ts가 없거나 Slack이 꺼져
        # 있으면 네트워크에 닿지 않는다). 테스트는 가짜 전송기를 묶은 함수를 넣는다.
        self.verdict_completed_notifier = verdict_completed_notifier

    @property
    def client(self) -> Any | None:
        """이 서비스가 쓰는 분석 client.

        vLLM 경로에서는 policy가 모델명을 정하므로 실행 전까지 `None`이다.
        `None`을 "client가 없다"가 아니라 "아직 묶이지 않았다"로 읽는다.
        """

        return self._client

    def _runtime_identity(self, policy: AnalysisPolicyVersion) -> tuple[str, str]:
        """감사에 남길 provider와 모델명. 모델을 부르지 않고 정한다.

        생성 시점에 `/models`를 부르면 공고 잠금을 쥔 transaction 안에서
        network I/O를 하게 된다. transport 식별자와 policy 모델명은 그때도
        확정돼 있으므로 여기서는 그 둘만 읽는다.
        """

        if luna_inputs.is_luna(policy):
            if (
                self.settings.analysis_provider == "mock"
                and self.reference_workflow_mode
                and _policy_payload(policy).get("pipeline_version") == "card-v1"
            ):
                # 결정 B16: the RL card path runs the deterministic mock (no transfer).
                return MOCK_ANALYSIS_PROVIDER, MOCK_MODEL_NAME
            return "codex-exec", str(policy.model_name)
        if self._client is not None and self._client_matches(str(policy.model_name)):
            return (
                str(getattr(self._client, "provider_name", "injected-analysis-client")),
                str(getattr(self._client, "model", policy.model_name)),
            )
        return MODEL_ENDPOINT_REF, str(policy.model_name)

    def _client_matches(self, model_name: str) -> bool:
        """들고 있는 client를 이 모델명에 그대로 쓸 수 있는가.

        주입·mock client는 언제나 쓴다 — 호출자가 그 계약을 소유한다. 스스로
        묶은 client는 **묶을 때 쓴 모델명이 같을 때만** 쓴다. worker 하나가
        서비스를 job 사이에 들고 있으므로, 이 대조가 없으면 policy A로 만든
        client가 policy B에 고정된 job에 그대로 돌아간다.
        """

        return self._injected_client or self._bound_model_name == model_name

    def _bind_client(self, model_name: str, *, narrative: bool = False) -> Any:
        """용도별 설정으로 심층 검토 client를 만들고 identity를 확인한다 (명세 §6.6).

        허용 host나 배포 선언 revision이 없으면 `/models`를 부르기도 전에 fail
        closed하고, served id에 policy 모델명이 없으면 `model_not_served`다.
        어느 실패도 다른 주소·다른 provider로 넘어가지 않는다.
        """

        if self._client is not None and self._client_matches(model_name) and (self._injected_client or getattr(self, "_bound_narrative", False) == narrative):
            return self._client
        # 모델명이 다르면 이전 client는 버린다. transport를 닫지 않으면 job이
        # 모델을 오갈 때마다 연결이 쌓인다.
        discarded, self._client, self._bound_model_name = self._client, None, None
        if discarded is not None:
            closer = getattr(discarded, "close", None)
            if callable(closer):
                closer()
        try:
            self._client = ModelClient.for_purpose(
                MODEL_PURPOSE,
                model=model_name,
                output_contract=NARRATIVE_STAGE_CONTRACT if narrative else DEEP_REVIEW_STAGE_CONTRACT,
                settings=self.settings,
            )
        except ModelIdentityError as error:
            raise DeepReviewServiceError(error.code, "승인된 분석 모델 identity를 확인할 수 없습니다", status_code=503) from error
        except (ModelEndpointError, ValueError) as error:
            raise DeepReviewServiceError("service_unavailable", "심층 검토 모델 endpoint 설정이 유효하지 않습니다", status_code=503) from error
        self._bound_model_name = model_name
        self._bound_narrative = narrative
        return self._client

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
        from .verification import enabled_for_attempt
        from ..models import DeepReviewApproval
        approval = session.scalar(select(DeepReviewApproval).where(DeepReviewApproval.attempt_id == attempt.id))
        review = session.get(DeepReview, attempt.deep_review_id) if approval else None
        policy = session.get(AnalysisPolicyVersion, review.policy_version_id) if review is not None else None
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
            "source_verification_enabled": enabled_for_attempt(session, attempt.id),
            "provider": policy.model_endpoint_ref if policy is not None else None,
            "model": policy.model_name if policy is not None else None,
            "reasoning_effort": policy_reasoning_effort(policy) if policy is not None else None,
            "preview_id": str(approval.preview_id) if approval else None,
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
            "quality_status": quality_status_for_review(session, review.id),
        }

    def opportunity_reviews(self, session: Session, opportunity_id: int) -> dict[str, Any]:
        from .opportunity_reviews import opportunity_reviews

        return opportunity_reviews(session, opportunity_id)

    def _seed_attempt(self, session: Session, review: DeepReview, *, sequence: int, actor: str, source_verification_enabled: bool = True, actor_kind: str = "human") -> DeepReviewAttempt:
        attempt = DeepReviewAttempt(id=uuid4(), deep_review_id=review.id, sequence=sequence, status="queued", lease_fence=0, requested_by_name=actor)
        session.add(attempt)
        session.flush()
        job = WorkJob(id=uuid4(), job_type="deep_review", aggregate_type="deep_review", aggregate_id=review.id, status="queued", priority=0, max_attempts=1)
        session.add(job)
        session.flush()
        attempt.work_job_id = job.id
        from .verification import record_selection
        record_selection(session, attempt.id, source_verification_enabled, actor, actor_kind)
        # RL-03 card-v1 attempts keep their validated results in the
        # append-only ``card_analysis_stage`` rows; the narrative StageName
        # rows are not created for them (HP-03 "설정·상태·저장").
        policy = session.get(AnalysisPolicyVersion, review.policy_version_id)
        if policy is None or _policy_payload(policy).get("pipeline_version") != "card-v1":
            for stage, sequence_number in STAGE_SEQUENCE.items():
                session.add(DeepReviewStage(id=uuid4(), attempt_id=attempt.id, stage=stage, sequence=sequence_number, status="queued", structured_output={}, invocation_metadata={}))
        review.current_attempt_id = attempt.id
        review.status = "queued"
        return attempt

    def create_review(
        self,
        session: Session,
        notice_id: int,
        bundle_id: UUID,
        actor: str | None,
        request_id: UUID,
        *,
        actor_kind: str = "human",
        source_verification_enabled: bool = True,
        preview_id: UUID | None = None,
    ) -> dict[str, Any]:
        """심층 검토와 첫 attempt를 만든다.

        `actor_kind`가 ``system``이면 §6.4의 자동 시작이다. 담당자 이름 검사와
        불변 입력 고정, 등급 검사, 감사 metadata의 **모양**은 사람 경로와 같고
        감사 action 이름과 actor 종류만 다르다 — `quality_status`가 두 action
        모두에서 계산되기 때문이다(§8). 자동 시작이 추가 권한을 얻지는 않는다.
        """

        claimed_name = _validate_actor(actor)
        actor_kind = _validate_actor_kind(actor_kind)
        if actor_kind == "system" and not self.settings.deep_review_auto_start_enabled:
            raise DeepReviewServiceError("manual_request_required", "사용자 요청이 필요합니다", status_code=409)
        creation_action = CREATION_ACTION_BY_ACTOR_KIND[actor_kind]
        request_hash = _idempotency_hash("deep_review_create", {"notice_id": notice_id, "bundle_id": str(bundle_id), **({"source_verification_enabled": False} if not source_verification_enabled else {}), **({"preview_id": str(preview_id)} if preview_id else {})})
        try:
            # Notice is the aggregate root for the immutable grade/bundle /
            # active profile/policy snapshot.  Lock it before replay lookup so
            # concurrent same-key requests cannot create two reviews.
            notice = lock_notice(session, notice_id)
            if notice is None:
                raise InputVersionError("not_found", "공고를 찾을 수 없습니다")
            approval_check = getattr(self.client, "require_notice_approval", None)
            if callable(approval_check):
                try:
                    approval_check(notice_id)
                except ModelInvocationError as error:
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
            if luna_inputs.is_luna(policy) and actor_kind != "human":
                raise DeepReviewServiceError("manual_request_required", "Luna는 사람 요청만 지원합니다", status_code=409)
            luna_inputs.require_runtime(policy)
            preview = luna_inputs.check(self, session, preview_id, notice, bundle_id, profile, policy, source_verification_enabled) if luna_inputs.is_luna(policy) else None
            if preview is not None and session.scalar(select(DeepReview.id).where(
                DeepReview.company_id.is_(None),
                DeepReview.notice_id == notice_id,
                DeepReview.status.in_(("queued", "running")),
            ).limit(1)):
                raise DeepReviewServiceError("active_attempt_exists", "이미 대기·실행 중인 검토가 있습니다", status_code=409)
            runtime_provider, runtime_model = self._runtime_identity(policy)
            quality_snapshot = (
                {"status": "reference_workflow_unmeasured", "deployable": False}
                if self.reference_workflow_mode
                else policy_quality_snapshot(policy)
            )
            # 등급 자체는 seam이 읽고 그대로 기록한다(`effective_grade_at_start`).
            # 자격 판정만 자동 준비·개요와 **같은 helper**가 한다 — 플래그가
            # 켜져 있으면 `SW사업대상=Y` 사전규격도 자격을 갖고, 꺼져 있으면
            # 기존 `우선 검토` 규칙 그대로다(2026-09-11 MVP 완화).
            basis = effective_grade_basis(session, notice_id)
            if not eligible_with_grade(session, notice_id, basis.grade):
                raise DeepReviewServiceError("effective_grade_ineligible", "우선 검토 또는 SW사업대상=Y 공고만 심층 분석할 수 있습니다", status_code=403, request_id=request_id)
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
                actions=("document_bundle.create",),
                aggregate_type="document_bundle",
                aggregate_id=str(bundle_id),
            )
            # The unique input tuple is authoritative; existing review rows are
            # returned only when they are the same immutable input set.
            existing = session.scalar(select(DeepReview).where(
                DeepReview.company_id.is_(None),
                DeepReview.notice_id == notice_id, DeepReview.bundle_id == bundle_id,
                DeepReview.profile_version_id == profile.id, DeepReview.policy_version_id == policy.id,
            ).limit(1))
            if existing is not None:
                if preview is not None:
                    raise DeepReviewServiceError("review_exists", "기존 검토에서 새 분석을 요청하십시오", status_code=409)
                creation = session.scalar(select(AuditEvent).where(
                    # 사람 경로와 자동 시작(§6.4)이 같은 계보를 남긴다. 한쪽만
                    # 보면 자동 생성된 review의 provider 문맥을 못 읽는다.
                    AuditEvent.action.in_(CREATION_ACTIONS),
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
                from .verification import enabled_for_attempt
                if existing.current_attempt_id and enabled_for_attempt(session, existing.current_attempt_id) != source_verification_enabled:
                    raise DeepReviewServiceError("verification_setting_conflict", "기존 실행의 대조 설정이 다릅니다. 해당 보고서에서 새 분석을 실행하십시오.", status_code=409, request_id=request_id)
                response = self.view(session, existing.id)
                session.add(IdempotencyRecord(operation="deep_review_create", aggregate_type="notice", aggregate_id=str(notice_id), claimed_name=claimed_name, request_id=request_id, request_sha256=request_hash, response_status=202, response_snapshot=response))
                session.commit()
                return response
            review = DeepReview(id=uuid4(), company_id=None, notice_id=notice_id, bundle_id=bundle_id, profile_version_id=profile.id, policy_version_id=policy.id, effective_grade_at_start=basis.grade or "unknown", status="queued", requested_by_name=claimed_name)
            session.add(review)
            session.flush()
            attempt = self._seed_attempt(session, review, sequence=1, actor=claimed_name, source_verification_enabled=source_verification_enabled, actor_kind=actor_kind)
            if preview is not None:
                luna_inputs.approve(session, preview, attempt.id, claimed_name, request_id)
            session.flush()
            response = self.view(session, review.id)
            session.add(IdempotencyRecord(operation="deep_review_create", aggregate_type="notice", aggregate_id=str(notice_id), claimed_name=claimed_name, request_id=request_id, request_sha256=request_hash, response_status=202, response_snapshot=response))
            session.add(AuditEvent(actor_kind=actor_kind, claimed_name=claimed_name, action=creation_action, aggregate_type="deep_review", aggregate_id=str(review.id), request_id=str(request_id), safe_metadata={
                "notice_id": notice_id, "bundle_id": str(bundle_id), "profile_version_id": str(profile.id), "profile_sha256": profile.profile_sha256,
                "policy_version_id": str(policy.id), "policy_sha256": policy.policy_sha256, "policy_model_name": policy.model_name,
                "analysis_provider": runtime_provider, "runtime_model": runtime_model,
                # No approved external analysis provider exists in this
                # deployment; the remaining providers are vLLM and the local
                # mock, so this audit flag is always false.
                "external_provider_approved": preview is not None,
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

    def create_attempt(self, session: Session, review_id: UUID, actor: str | None, request_id: UUID, *, source_verification_enabled: bool = True, preview_id: UUID | None = None) -> dict[str, Any]:
        claimed_name = _validate_actor(actor)
        request_hash = _idempotency_hash("deep_review_attempt", {"review_id": str(review_id), **({"source_verification_enabled": False} if not source_verification_enabled else {}), **({"preview_id": str(preview_id)} if preview_id else {})})
        try:
            notice_id = session.scalar(select(DeepReview.notice_id).where(DeepReview.id == review_id))
            if notice_id is not None:
                lock_notice(session, notice_id)
            # Lock the review aggregate before idempotency replay and active
            # attempt checks.  This makes same-review retries serializable.
            review = session.scalar(select(DeepReview).where(DeepReview.id == review_id).with_for_update())
            # Company reviews (DEMO-03) are retried only through the company
            # path with a company preview; the legacy path never touches them.
            if review is None or review.company_id is not None:
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
                # 사람이 만든 검토든 자동으로 시작된 검토든 계보는 그 생성
                # 감사에 있다. 한쪽만 보면 자동 생성분의 재시도가 계보 불일치로
                # 막힌다.
                actions=CREATION_ACTIONS,
                aggregate_type="deep_review",
                aggregate_id=str(review.id),
            )
            bundle_correlation_id = _audit_correlation_id(
                session,
                actions=("document_bundle.create",),
                aggregate_type="document_bundle",
                aggregate_id=str(review.bundle_id),
            )
            if correlation_id != bundle_correlation_id:
                raise DeepReviewServiceError("processing_failed", "deep review 계보를 확인할 수 없습니다", status_code=500, request_id=request_id)
            profile = session.get(ProfileVersion, review.profile_version_id)
            policy = session.get(AnalysisPolicyVersion, review.policy_version_id)
            validate_pinned_policy(policy, allow_unmeasured_reference=self.reference_workflow_mode)
            luna_inputs.require_runtime(policy)
            notice = lock_notice(session, review.notice_id)
            preview = luna_inputs.check(self, session, preview_id, notice, review.bundle_id, profile, policy, source_verification_enabled) if luna_inputs.is_luna(policy) else None
            if preview is not None and session.scalar(select(DeepReview.id).where(DeepReview.company_id.is_(None), DeepReview.notice_id == review.notice_id, DeepReview.status.in_(("queued", "running"))).limit(1)):
                raise DeepReviewServiceError("active_attempt_exists", "이미 대기·실행 중인 검토가 있습니다", status_code=409)
            max_sequence = session.scalar(select(DeepReviewAttempt.sequence).where(DeepReviewAttempt.deep_review_id == review.id).order_by(DeepReviewAttempt.sequence.desc()).limit(1)) or 0
            # Completed attempts are immutable snapshots.  A retry may move
            # the review pointer to a new attempt, but never rewrites a
            # completed attempt to ``superseded``; only failed attempts can be
            # superseded as part of retry bookkeeping.
            if current.status == "failed":
                current.status = "superseded"
            attempt = self._seed_attempt(session, review, sequence=int(max_sequence) + 1, actor=claimed_name, source_verification_enabled=source_verification_enabled)
            if preview is not None:
                luna_inputs.approve(session, preview, attempt.id, claimed_name, request_id)
            session.flush()
            response = self._attempt_view(session, attempt)
            session.add(IdempotencyRecord(operation="deep_review_attempt", aggregate_type="deep_review", aggregate_id=str(review_id), claimed_name=claimed_name, request_id=request_id, request_sha256=request_hash, response_status=202, response_snapshot=response))
            session.add(AuditEvent(actor_kind="human", claimed_name=claimed_name, action="deep_review.attempt", aggregate_type="deep_review", aggregate_id=str(review.id), request_id=str(request_id), safe_metadata={
                "attempt_id": str(attempt.id), "sequence": attempt.sequence,
                **({"correlation_id": str(correlation_id)} if correlation_id is not None else {}),
            }))
            session.commit()
        except (DeepReviewServiceError, InputVersionError):
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
        # Company-scoped jobs (DEMO-03) share this one slot and its lease,
        # fencing and failure rules, but only while BIDOPS_DEMO_ENABLED is on;
        # otherwise they are left untouched (queued).  Orphan jobs still pass
        # the predicate and keep the fail-closed review_scope_missing handling.
        # RL-03: with BIDOPS_RL_ANALYSIS_ENABLED (and demo off) the real
        # company's jobs are claimed too; fictional-company jobs stay queued.
        if getattr(self.settings, "demo_enabled", False):
            company_scope = []
        elif getattr(self.settings, "rl_analysis_enabled", False):
            from ...lifecycle.models import Company

            company_scope = [
                ~exists().where(
                    DeepReview.id == WorkJob.aggregate_id,
                    DeepReview.company_id.is_not(None),
                    ~exists().where(Company.id == DeepReview.company_id, Company.is_fictional.is_(False)),
                ),
            ]
        else:
            company_scope = [
                ~exists().where(
                    DeepReview.id == WorkJob.aggregate_id,
                    DeepReview.company_id.is_not(None),
                ),
            ]
        job = session.scalar(
            select(WorkJob)
            .where(
                WorkJob.job_type == "deep_review",
                *company_scope,
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
            policy = session.get(AnalysisPolicyVersion, review.policy_version_id)
            if policy is not None and luna_inputs.is_luna(policy):
                job.status = attempt.status = review.status = "failed"
                job.last_error_code = "lease_expired"
                job.lease_fence += 1
                job.lease_expires_at = None
                job.completed_at = attempt.completed_at = now
                for stage in self._stages(session, attempt.id):
                    if stage.status in {"queued", "running"}:
                        stage.status = "failed"
                        stage.completed_at = now
                        stage.invocation_metadata = [{"error_code": "lease_expired"}]
                _add_job_audit(session, action="deep_review.job.failed", job_id=job.id, review_id=review.id, attempt_id=attempt.id, fence=job.lease_fence, status="failed")
                session.commit()
                return None
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
            if int(job.attempt_count) >= int(job.max_attempts):
                # 만료된 lease를 상한 없이 다시 잡으면 같은 job이 무한히
                # 재점유된다. 시도를 다 쓴 job은 여기서 닫는다.
                # 심층 쪽 attempt·review 상태는 건드리지 않는다: 이 경로에는
                # 소유 lease와 fence가 없어 `_fail_claim`(모든 UPDATE가 자기
                # fence를 조건으로 한다)을 부를 수 없고, 같은 자리의 형제
                # 분기(`review_scope_missing`·`expired_attempt_not_active`)도
                # job만 닫고 감사 행을 남긴다.
                job.status = "failed"
                job.last_error_code = "attempts_exhausted"
                job.completed_at = job.completed_at or now
                job.lease_expires_at = None
                _add_job_audit(
                    session, action="deep_review.job.failed", job_id=job.id,
                    review_id=review.id, attempt_id=attempt.id,
                    fence=int(job.lease_fence), status="failed",
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

    def _renew_lease(self, session: Session, claim: JobClaim, *, require_live: bool = False) -> None:
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
                *([WorkJob.lease_expires_at > self.clock()] if require_live else []),
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
        source_verification_enabled: bool = True,
        result_checks_enabled: bool = True,
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
                        known_evidence=[row for output in outputs for row in output.get("evidence", [])] if stage.structured_output.get("schema") == "bidops.deep-review-stage.v2" else (),
                        structures=structures, source_verification_enabled=source_verification_enabled, result_checks_enabled=result_checks_enabled,
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
            key=lambda item: (
                item[1][1].get("slice_index", item[0]) if isinstance(item[1][1], Mapping) else item[0],
                item[1][1].get("validation_repair_attempt", 0) if isinstance(item[1][1], Mapping) else 0,
                item[0],
            ),
        )
        for fallback_index, (_source_index, (result, metadata)) in enumerate(ordered_records):
            try:
                raw_text = result.raw_response.decode("utf-8")
            except (AttributeError, UnicodeDecodeError) as exc:
                raise DeepReviewServiceError("processing_failed", "model raw response가 UTF-8 JSON이 아닙니다", status_code=500) from exc
            slice_index = metadata.get("slice_index", fallback_index) if isinstance(metadata, Mapping) else fallback_index
            responses.append({
                "slice_index": slice_index,
                "response_sha256": hashlib.sha256(result.raw_response).hexdigest(),
                "raw_response": raw_text,
            })
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

    def _fail_claim(self, session: Session, claim: JobClaim, stage: DeepReviewStage | None, code: str, invocation_metadata: Sequence[Mapping[str, Any]] = (), raw_records: Sequence[tuple[InvocationResult, Mapping[str, Any]]] = ()) -> None:
        session.rollback()
        raw_aggregate = None
        if raw_records:
            try:
                raw_aggregate = self._store_raw_aggregate(raw_records)
            except DeepReviewServiceError:
                # Preserve the original rejection even if diagnostic storage is unavailable.
                raw_aggregate = None
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
                raw_content = self._raw_content_row(session, *raw_aggregate) if raw_aggregate is not None else None
                stage_count = session.execute(update(DeepReviewStage).where(DeepReviewStage.id == stage.id, DeepReviewStage.attempt_id == claim.attempt_id, DeepReviewStage.status.in_(("queued", "running"))).values(status="failed", invocation_metadata=metadata, completed_at=self.clock(), raw_response_content_object_id=raw_content.id if raw_content else None)).rowcount
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

    def _approved_company_context(
        self,
        session: Session,
        review: DeepReview,
        attempt: DeepReviewAttempt,
        profile: ProfileVersion,
        policy: AnalysisPolicyVersion,
        creation: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Mapping[str, Any]]]:
        """Worker-side ``approval_invalid`` gate of a company attempt (DEMO-03 §9/§10).

        Returns (approved frozen CompanyAnalysisInput, pinned bundle, pinned
        structures).  The input is never rebuilt: ``approved_company_input``
        checks approval/preview/review company, lineage, hash and nonce; here
        the creation audit's company keys, this attempt's approval audit, the
        pinned profile/policy/graph hashes and the frozen source units are
        compared with immutable rows.  The pinned bundle structures are read
        only as the deterministic validation context (quotes/locators); they
        must re-split into exactly the frozen units or the attempt fails
        before any model call.  Nothing new is added to the model input.
        """

        from .company_deep_review import company_source_units
        from ..models import CompanyKnowledgeVersion, DeepReviewApproval, DeepReviewPreview

        def invalid() -> InputVersionError:
            return InputVersionError("approval_invalid", "승인된 동결 입력을 확인할 수 없습니다")

        frozen = luna_inputs.approved_company_input(session, attempt.id, review)
        approval = session.scalar(select(DeepReviewApproval).where(DeepReviewApproval.attempt_id == attempt.id))
        preview = session.get(DeepReviewPreview, approval.preview_id) if approval is not None else None
        graph = session.get(CompanyKnowledgeVersion, review.graph_version_id)
        approval_audits = session.scalars(select(AuditEvent).where(
            AuditEvent.action == "deep_review.external_transfer_approved",
            AuditEvent.aggregate_type == "deep_review_attempt",
            AuditEvent.aggregate_id == str(attempt.id),
        ).limit(2)).all()
        approved = approval_audits[0].safe_metadata if len(approval_audits) == 1 and isinstance(approval_audits[0].safe_metadata, Mapping) else {}
        if (
            approval is None or preview is None or graph is None
            or creation.get("company_id") != str(review.company_id)
            or creation.get("graph_version_id") != str(review.graph_version_id)
            or creation.get("graph_sha256") != graph.graph_sha256 or frozen.get("graph_sha256") != graph.graph_sha256
            or creation.get("grade_source") != "company_sw_business" or creation.get("effective_grade") is not None
            or (attempt.sequence == 1 and (
                creation.get("preview_id") != str(preview.id) or creation.get("input_sha256") != preview.input_sha256
            ))
            or approved.get("preview_id") != str(preview.id) or approved.get("input_sha256") != preview.input_sha256
            or approved.get("company_id") != str(review.company_id)
            or approved.get("graph_version_id") != str(review.graph_version_id)
            or frozen.get("profile_sha256") != profile.profile_sha256
            or frozen.get("policy_sha256") != policy.policy_sha256
            or frozen.get("model_name") != policy.model_name
        ):
            raise invalid()
        bundle, structures = bundle_context(session, review.bundle_id, structure_loader=self.structure_loader)
        chunking = _policy_payload(policy).get("chunking")
        source_characters = chunking.get("source_characters") if isinstance(chunking, Mapping) else None
        if type(source_characters) is not int or source_characters < 1:
            raise DeepReviewServiceError("company_policy_invalid", "회사 분석 정책이 올바르지 않습니다", status_code=503)
        units = company_source_units(session, bundle, structures, source_characters=source_characters)
        frozen_units = [unit for row in frozen.get("requirements", []) for unit in row.get("source_units", [])]
        if (
            frozen_units != units
            or [str(row["document_version_id"]) for row in bundle["documents"]] != list(frozen.get("document_version_ids", []))
        ):
            raise invalid()
        return frozen, bundle, structures

    def _approved_card_input(
        self,
        session: Session,
        review: DeepReview,
        attempt: DeepReviewAttempt,
        profile: ProfileVersion,
        policy: AnalysisPolicyVersion,
        creation: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Worker-side ``approval_invalid`` gate of an RL card-v1 attempt.

        Same frozen-input checks as ``_approved_company_context`` (approval /
        preview / review company, lineage, hash, nonce, creation and approval
        audits, pinned profile/policy/graph hashes) plus the v2 shape: exact
        v2 keys, ``overview_*`` both null (D1), and the frozen ``card_analysis``
        units/batches/selector rebuilt from the pinned bundle unchanged.  The
        input is never rebuilt into the call; nothing is added to it.
        """

        from .card_units import CardAnalysisSelectionError
        from .company_analysis_input import COMPANY_ANALYSIS_INPUT_V2_KEYS, CompanyAnalysisError
        from .company_deep_review import card_analysis_for_bundle, resolve_company_deep_policy
        from .company_analysis_input import resolve_company_knowledge_context
        from ..models import CompanyKnowledgeVersion, DeepReviewApproval, DeepReviewPreview

        def invalid() -> InputVersionError:
            return InputVersionError("approval_invalid", "승인된 동결 입력을 확인할 수 없습니다")

        frozen = luna_inputs.approved_company_input(session, attempt.id, review)
        approval = session.scalar(select(DeepReviewApproval).where(DeepReviewApproval.attempt_id == attempt.id))
        preview = session.get(DeepReviewPreview, approval.preview_id) if approval is not None else None
        graph = session.get(CompanyKnowledgeVersion, review.graph_version_id)
        approval_audits = session.scalars(select(AuditEvent).where(
            AuditEvent.action == "deep_review.external_transfer_approved",
            AuditEvent.aggregate_type == "deep_review_attempt",
            AuditEvent.aggregate_id == str(attempt.id),
        ).limit(2)).all()
        approved = approval_audits[0].safe_metadata if len(approval_audits) == 1 and isinstance(approval_audits[0].safe_metadata, Mapping) else {}
        if (
            approval is None or preview is None or graph is None
            or set(frozen) != COMPANY_ANALYSIS_INPUT_V2_KEYS
            or frozen.get("schema_version") != "bidops.company-analysis-input.v2"
            or frozen.get("overview_run_id") is not None or frozen.get("overview_sha256") is not None
            or creation.get("company_id") != str(review.company_id)
            or creation.get("graph_version_id") != str(review.graph_version_id)
            or creation.get("graph_sha256") != graph.graph_sha256 or frozen.get("graph_sha256") != graph.graph_sha256
            or creation.get("grade_source") != "company_sw_business" or creation.get("effective_grade") is not None
            or (attempt.sequence == 1 and (
                creation.get("preview_id") != str(preview.id) or creation.get("input_sha256") != preview.input_sha256
            ))
            or approved.get("preview_id") != str(preview.id) or approved.get("input_sha256") != preview.input_sha256
            or approved.get("company_id") != str(review.company_id)
            or approved.get("graph_version_id") != str(review.graph_version_id)
            or frozen.get("profile_sha256") != profile.profile_sha256
            or frozen.get("policy_sha256") != policy.policy_sha256
            or frozen.get("model_name") != policy.model_name
        ):
            raise invalid()
        bundle, structures = bundle_context(session, review.bundle_id, structure_loader=self.structure_loader)
        if [str(row["document_version_id"]) for row in bundle["documents"]] != list(frozen.get("document_version_ids", [])):
            raise invalid()
        try:
            card_policy = resolve_company_deep_policy(session, self.settings, rl=True)
            if card_policy.row.id != policy.id:
                raise invalid()
            knowledge = resolve_company_knowledge_context(session, review.company_id)
            if (
                str(knowledge.graph.id) != frozen.get("graph_version_id")
                or str(knowledge.profile.id) != frozen.get("profile_version_id")
            ):
                raise invalid()
            rebuilt = card_analysis_for_bundle(
                session, bundle, structures, knowledge=knowledge, policy=card_policy,
            ).model_dump(mode="json")
        except (CardAnalysisSelectionError, CompanyAnalysisError, DeepReviewServiceError):
            raise invalid() from None
        if rebuilt != frozen.get("card_analysis"):
            raise invalid()
        return frozen

    def _card_pipeline(self) -> Callable[..., None] | None:
        """The card-v1 stage runner (RL-03 STEP-005 ``card_analysis.run_card_analysis``).

        A ``None`` runner (kept as a seam) fails closed with
        ``company_policy_invalid`` **before** the transfer audit and before
        any call; no ``analysis.transfer.sent`` is written for a transfer that
        cannot happen.
        """

        from .card_analysis import run_card_analysis

        return run_card_analysis

    def _persist_card_raw_response(
        self,
        session: Session,
        claim: JobClaim,
        result: Any,
        *,
        stage: str,
        stage_key: str,
        call_index: int,
        repair_attempt: int,
        extra_safe_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Encrypt one card-v1 model response and append only its safe receipt (fenced).

        The encrypted object is written before the fence lock; its DB pointer
        and the ``deep_review.card.raw_response.stored`` audit (stage, key,
        call index, repair attempt, response sha) are written only under the
        live claim, so a stale worker cannot attach a late response.
        ``extra_safe_metadata`` (결정 B33) adds code-only keys: the v2 extract
        contract, the code-derived field names and repair rule codes.
        """

        raw = getattr(result, "raw_response", None)
        if not isinstance(raw, bytes) or not raw:
            raise DeepReviewServiceError("processing_failed", "model raw response가 없습니다", status_code=500)
        aggregate, metadata = self._store_raw_aggregate([(
            result, {"slice_index": call_index, "validation_repair_attempt": repair_attempt},
        )])
        if not self._lock_claim(session, claim):
            session.rollback()
            raise StaleFenceError()
        content = self._raw_content_row(session, aggregate, metadata)
        _add_job_audit(
            session, action="deep_review.card.raw_response.stored", job_id=claim.job_id,
            review_id=claim.deep_review_id, attempt_id=claim.attempt_id, fence=claim.fence, status="stored",
            extra_safe_metadata={
                "stage": stage, "stage_key": stage_key, "call_index": int(call_index),
                "repair_attempt": int(repair_attempt), "content_object_id": str(content.id),
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                **_card_derivation_metadata(extra_safe_metadata),
            },
        )
        session.commit()

    def _record_card_stages_reused(
        self,
        session: Session,
        claim: JobClaim,
        *,
        source_attempt_id: UUID,
        stages: Sequence[Mapping[str, Any]],
    ) -> None:
        """결정 B55: one fenced ``card.stages.reused`` audit (source attempt, stage keys, input/result sha)."""

        rows = [
            {key: str(row[key]) for key in ("stage", "stage_key", "input_sha256", "result_sha256")}
            for row in stages
        ]
        if not rows or any(
            row["stage"] not in {"extract", "compare", "role"}
            or re.fullmatch(r"[0-9a-f]{64}", row["input_sha256"]) is None
            or re.fullmatch(r"[0-9a-f]{64}", row["result_sha256"]) is None
            for row in rows
        ):
            raise DeepReviewServiceError("processing_failed", "재사용 단계 감사 값이 올바르지 않습니다", status_code=500)
        if not self._lock_claim(session, claim):
            session.rollback()
            raise StaleFenceError()
        _add_job_audit(
            session, action=CARD_STAGES_REUSED_ACTION, job_id=claim.job_id, review_id=claim.deep_review_id,
            attempt_id=claim.attempt_id, fence=claim.fence, status="reused",
            extra_safe_metadata={"source_attempt_id": str(source_attempt_id), "stages": rows},
        )
        session.commit()

    def _finish_card_claim(
        self,
        session: Session,
        claim: JobClaim,
        *,
        batch_count: int,
        call_count: int,
        elapsed_seconds: float,
        target_seconds: int,
        target_missed: bool,
        extract_derivation: Mapping[str, Any] | None = None,
        resumed_from_attempt_id: UUID | None = None,
    ) -> None:
        """Complete a card-v1 attempt once its full append-only stage set exists.

        Exactly extract/compare ``0..B-1``, the three roles and ``final``;
        anything else is a stale or broken attempt and nothing is completed.
        The completion audit carries the call count and the 2400-second target
        result (a missed target is still a completed attempt).
        """

        from ..models import CardAnalysisStage

        if (
            type(batch_count) is not int or batch_count < 1
            or type(call_count) is not int
            or call_count < (1 if resumed_from_attempt_id is not None else batch_count + 4)
            or isinstance(elapsed_seconds, bool) or not isinstance(elapsed_seconds, (int, float)) or elapsed_seconds < 0
            or type(target_seconds) is not int or target_seconds < 1
            or type(target_missed) is not bool or target_missed != (elapsed_seconds > target_seconds)
        ):
            raise DeepReviewServiceError("processing_failed", "카드 분석 완료 감사 값이 올바르지 않습니다", status_code=500)
        now = self.clock()
        if not self._lock_claim(session, claim):
            session.rollback()
            raise StaleFenceError()
        rows = session.scalars(select(CardAnalysisStage).where(CardAnalysisStage.attempt_id == claim.attempt_id)).all()
        keys = {(row.stage, row.stage_key) for row in rows}
        batches = {str(index) for index in range(batch_count)}
        expected = (
            {("extract", key) for key in batches} | {("compare", key) for key in batches}
            | {("role", role) for role in ("eligibility_economics", "technical_fit", "operations_risk")}
            | {("synthesis", "final")}
        )
        if keys != expected or len(rows) != len(expected):
            session.rollback()
            raise DeepReviewServiceError("processing_failed", "카드 분석 단계 결과가 완전하지 않습니다", status_code=500)
        attempt_count = session.execute(update(DeepReviewAttempt).where(
            DeepReviewAttempt.id == claim.attempt_id, DeepReviewAttempt.deep_review_id == claim.deep_review_id,
            DeepReviewAttempt.lease_fence == claim.fence, DeepReviewAttempt.status == "running",
        ).values(status="completed", completed_at=now)).rowcount
        review_count = session.execute(update(DeepReview).where(
            DeepReview.id == claim.deep_review_id, DeepReview.current_attempt_id == claim.attempt_id,
            DeepReview.status == "running",
        ).values(status="completed", completed_at=now)).rowcount
        job_count = session.execute(update(WorkJob).where(
            WorkJob.id == claim.job_id, WorkJob.lease_owner == claim.worker_id,
            WorkJob.lease_fence == claim.fence, WorkJob.status == "running",
        ).values(status="completed", completed_at=now, lease_expires_at=None)).rowcount
        if (attempt_count, review_count, job_count) != (1, 1, 1):
            session.rollback()
            raise StaleFenceError()
        _add_job_audit(
            session, action="deep_review.job.completed", job_id=claim.job_id, review_id=claim.deep_review_id,
            attempt_id=claim.attempt_id, fence=claim.fence, status="completed",
            extra_safe_metadata={
                "pipeline_version": "card-v1", "batch_count": batch_count, "call_count": call_count,
                "elapsed_seconds": float(elapsed_seconds), "target_seconds": target_seconds,
                "target_missed": target_missed,
                **_card_derivation_metadata(extract_derivation),
                **({"resumed_from_attempt_id": str(resumed_from_attempt_id)}
                   if resumed_from_attempt_id is not None else {}),
            },
        )
        session.commit()
        self._notify_verdict_completed(session, claim.attempt_id)

    def _notify_verdict_completed(self, session: Session, attempt_id: UUID) -> None:
        """판정 완료 Slack 스레드 답글(RL-03). 완료 commit 뒤라 어떤 실패도 attempt를 바꾸지 않는다."""

        notifier = self.verdict_completed_notifier
        if notifier is None:
            from .verdict_links import notify_verdict_completed as notifier
        try:
            notifier(session, attempt_id)
        except Exception as error:  # pragma: no cover - 기본 notifier는 예외를 내지 않는다
            logger.warning("verdict completion notifier failed: attempt=%s error=%s", attempt_id, type(error).__name__)
        finally:
            # 읽기만 한 transaction을 닫는다(worker session을 idle-in-transaction으로 두지 않는다).
            session.rollback()

    def _run_card_claim(
        self,
        session: Session,
        claim: JobClaim,
        *,
        review: DeepReview,
        attempt: DeepReviewAttempt,
        profile: ProfileVersion,
        policy: AnalysisPolicyVersion,
        creation: Mapping[str, Any],
    ) -> None:
        """Claimed RL card-v1 attempt: approval re-check → transfer audit → stage runner.

        Spec "정책 단위 사전 승인": the approval must still be active for the
        pinned policy sha with the ``pre_spec``/``deep_review`` scope.  A real
        attempt also re-checks the daily cap here (결정 B17: the cap counts only
        attempts that actually transmitted, so the last gate before the first
        call is the worker; this attempt itself is excluded so a reclaimed run
        is not refused by its own audit).  ``analysis.transfer.sent`` is
        committed once, right after the claim and before the first call.

        With ``BIDOPS_ANALYSIS_PROVIDER=mock`` in reference mode (결정 B16) the
        runner uses the deterministic mock card client: nothing is transmitted,
        so no ``analysis.transfer.sent`` is written and the cap is not checked;
        the attempt's provider lineage (``mock-analysis``) was pinned at creation.
        """

        from . import transfer_policy
        from .card_units import analysis_call_budget

        mock = self.settings.analysis_provider == "mock"
        if not self.settings.luna_deep_review_enabled or (mock and not self.reference_workflow_mode):
            raise DeepReviewServiceError("service_unavailable", "Luna 실행 비활성", status_code=503)
        runner = self._card_pipeline()
        if runner is None:
            raise DeepReviewServiceError("company_policy_invalid", "카드 분석 실행기가 연결되지 않았습니다", status_code=503)
        frozen = self._approved_card_input(session, review, attempt, profile, policy, creation)
        try:
            approval = transfer_policy.require_transfer_approval(
                session, policy, check_cap=not mock, reserve_in_flight=False, exclude_attempt_id=attempt.id,
            )
        except transfer_policy.TransferPolicyError as error:
            raise DeepReviewServiceError(error.code, "전송 정책 승인이 없습니다", status_code=409) from None
        policy_payload = _policy_payload(policy)
        card = frozen["card_analysis"]
        budget = analysis_call_budget(
            len(card["batches"]), repair_attempts=int(policy_payload["card"]["repair_attempts"]),
        )
        # 결정 B55: a synthesis-only resume plans one call (its reused stages call nothing).
        resume = card_resume_for_attempt(session, attempt, frozen=frozen, policy=policy_payload)
        planned_calls = 1 if resume is not None else budget.normal_calls
        preview_hash = luna_inputs.approved_company_input_sha256(session, attempt.id)
        if not self._lock_claim(session, claim):
            session.rollback()
            raise StaleFenceError()
        if not mock and not getattr(self, "_injected_client", False):
            # 결정 B25: check the fixed runner endpoint before the transfer audit is
            # written, so a misconfigured stack neither records a send nor uses the cap.
            from .luna_client import valid_runner_endpoint

            if not valid_runner_endpoint(self.settings.luna_runner_url):
                session.rollback()
                raise DeepReviewServiceError("runner_unavailable", "Luna runner 주소가 올바르지 않습니다", status_code=503)
        if not mock:
            transfer_policy.record_transfer_sent(
                session, approval=approval, attempt_id=attempt.id, notice_id=int(review.notice_id),
                input_sha256=preview_hash, unit_count=len(card["units"]),
                planned_call_count=planned_calls,
            )
        session.commit()
        from .card_analysis import CardAnalysisRuntimeError

        try:
            runner(self, session, claim, frozen=frozen, policy=policy_payload, approval=approval,
                   **({"resume": resume} if resume is not None else {}))
        except CardAnalysisRuntimeError as error:
            raise DeepReviewServiceError(error.code, "카드 분석 실행이 검증을 통과하지 못했습니다", status_code=500) from None

    def run_claim(self, session: Session, claim: JobClaim) -> None:
        """Execute the three ordered business stages without an open I/O transaction.

        ``review.company_id`` selects the input: legacy (NULL) rows use the
        Luna preview snapshot (``approved_input``) or the live narrative
        context; company rows use only the approved frozen
        CompanyAnalysisInput (``_approved_company_context``), company slices
        and the company slice validator.  Lease, fencing, validation repair,
        raw-response storage and report materialization are shared.
        """

        stage_row: DeepReviewStage | None = None
        previous_outputs: list[Mapping[str, Any]] = []
        try:
            review = session.get(DeepReview, claim.deep_review_id)
            attempt = session.get(DeepReviewAttempt, claim.attempt_id)
            if review is None or attempt is None or attempt.lease_fence != claim.fence:
                raise StaleFenceError()
            # Early fail-closed checks still belong to the first unfinished
            # stage so attempt views expose their stable error code.
            stage_row = session.scalar(
                select(DeepReviewStage)
                .where(
                    DeepReviewStage.attempt_id == claim.attempt_id,
                    DeepReviewStage.status.in_(("queued", "running")),
                )
                .order_by(DeepReviewStage.sequence.asc())
                .limit(1)
            )
            profile = session.get(ProfileVersion, review.profile_version_id)
            policy = session.get(AnalysisPolicyVersion, review.policy_version_id)
            if profile is None or policy is None:
                raise DeepReviewServiceError("service_unavailable", "고정된 profile 또는 policy가 없습니다", status_code=503)
            validate_pinned_policy(policy, allow_unmeasured_reference=self.reference_workflow_mode)
            luna = luna_inputs.is_luna(policy)
            if luna and not matches_runtime(policy.model_name, policy_reasoning_effort(policy)):
                raise DeepReviewServiceError(
                    "model_binding_invalid", "심층 분석 모델 설정이 유효하지 않습니다", status_code=503
                )
            company = review.company_id is not None
            # Company policy identities are company-only and company rows run
            # only on one of them. Checked before any audit/approval/model step.
            company_policy = luna_inputs.is_luna(policy) and _policy_payload(policy).get("policy_identity") in COMPANY_POLICY_IDENTITIES
            if company != company_policy:
                raise DeepReviewServiceError("company_policy_invalid", "회사 계보와 분석 정책이 일치하지 않습니다", status_code=503)
            pinned_provider, pinned_runtime_model = self._runtime_identity(policy)
            # 생성 감사는 사람 클릭과 자동 시작 둘 중 하나다. 사람 action만
            # 보면 자동 생성된 검토가 고정 입력 snapshot을 못 찾고 503으로
            # 끝난다 — 만들어지기만 하고 실행되지 않는 검토가 된다.
            creation_audit = session.scalar(select(AuditEvent).where(AuditEvent.action.in_(CREATION_ACTIONS), AuditEvent.aggregate_type == "deep_review", AuditEvent.aggregate_id == str(review.id)).order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc()).limit(1))
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
                or audit_snapshot.get("analysis_provider") not in {None, pinned_provider}
                or audit_snapshot.get("runtime_model") not in {None, pinned_runtime_model}
            ):
                raise DeepReviewServiceError("service_unavailable", "pinned deep review 입력이 변경되었습니다", status_code=503)
            approval_check = getattr(self.client, "require_notice_approval", None)
            if callable(approval_check):
                try:
                    approval_check(review.notice_id)
                except ModelInvocationError as error:
                    raise DeepReviewServiceError(error.code, "외부 분석 provider 사용 승인이 없습니다", status_code=403) from error
            if company and luna and _policy_payload(policy).get("pipeline_version") == "card-v1":
                # RL-03 card-v1 (real company, policy-level transfer approval).
                self._run_card_claim(
                    session, claim, review=review, attempt=attempt, profile=profile, policy=policy,
                    creation=audit_snapshot,
                )
                return
            if not luna:
                bundle, structures = bundle_context(session, review.bundle_id, structure_loader=self.structure_loader)
                profile_payload = profile_context(session, profile)
                policy_payload = _policy_payload(policy)
            company_input: dict[str, Any] | None = None
            if luna:
                if not self.settings.luna_deep_review_enabled or self.settings.analysis_provider == "mock":
                    raise DeepReviewServiceError("service_unavailable", "Luna 실행 비활성", status_code=503)
                if company:
                    company_input, bundle, structures = self._approved_company_context(
                        session, review, attempt, profile, policy, audit_snapshot,
                    )
                    policy_payload = _policy_payload(policy)
                    profile_payload = company_slices.company_validation_profile(company_input)
                else:
                    frozen = luna_inputs.approved_input(session, attempt.id, review)
                    bundle, structures, profile_payload, policy_payload = (frozen[k] for k in ("bundle", "structures", "profile", "policy"))
            from .verification import result_checks_enabled as checks_enabled
            result_checks_enabled = checks_enabled(policy_payload)
            narrative = policy_payload.get("pipeline_version") == "narrative-v2"
            if company and (not narrative or not result_checks_enabled):
                raise DeepReviewServiceError("company_policy_invalid", "회사 분석 정책이 올바르지 않습니다", status_code=503)
            source_units = []
            if narrative and not company:
                inventory = frozen["inventory"] if luna else document_segments.inventory_context(session, [UUID(str(row["structure_id_at_confirmation"])) for row in bundle["documents"]])
                source_units = [row for group in self._requirements(bundle, structures, max_characters=int(policy_payload["chunking"]["source_characters"]), max_requirements=1) for row in group]
                for unit in source_units:
                    unit["document_requirement_ids"] = sorted(document_segments.observed_requirement_ids([unit["text"]], inventory.get("prefixes", [])))
                if {rid for unit in source_units for rid in unit["document_requirement_ids"]} != set(inventory.get("expected_ids", [])):
                    raise narrative_inputs.NarrativeInputError("source_requirement_inventory_mismatch")
            # Commit plain deep-copied snapshots before any model I/O.  The
            # worker never rereads live projections while a review is running.
            bundle = deepcopy(bundle)
            structures = deepcopy(structures)
            from .verification import enabled_for_attempt
            source_verification_enabled = enabled_for_attempt(session, claim.attempt_id)
            profile_payload = deepcopy(profile_payload)
            policy_payload = deepcopy(policy_payload)
            prefix_outputs, prefix_claim_ids, prefix_evidence_ids = self._contiguous_completed_prefix(
                self._stages(session, claim.attempt_id), bundle=bundle, profile=profile_payload,
                profile_version_id=str(profile.id), review_id=str(review.id), structures=structures,
                session=session, attempt_id=str(claim.attempt_id), source_verification_enabled=source_verification_enabled, result_checks_enabled=result_checks_enabled,
            )
            review_id = review.id
            pinned_notice_id = review.notice_id
            attempt_id = attempt.id
            pinned_profile_id = str(profile.id)
            pinned_profile_sha256 = str(profile.profile_sha256)
            pinned_policy_sha256 = str(policy.policy_sha256)
            pinned_model_name = str(policy.model_name)
            pinned_reasoning_effort = policy_reasoning_effort(policy)
            session.commit()
            previous_outputs: list[Mapping[str, Any]] = prefix_outputs
            known_claim_ids: set[str] = prefix_claim_ids
            known_evidence_ids: set[str] = prefix_evidence_ids
            review_timeout_seconds = _policy_execution_limit(
                policy_payload, "review_timeout_seconds", default=7200, minimum=1, maximum=86400,
            )
            validation_repair_attempts = _policy_execution_limit(
                policy_payload, "validation_repair_attempts", default=0, minimum=0, maximum=1,
            )
            luna_deadline = time.monotonic() + review_timeout_seconds
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
                # 실제로 모델을 부르기 직전에만 client를 묶는다. 완료된 stage만
                # 남은 재개 실행은 여기까지 오지 않으므로 `/models`도 부르지 않는다.
                if luna:
                    from .luna_client import LunaClient
                    client = self._client if self._injected_client else LunaClient(self.settings.luna_runner_url, lambda: self._renew_lease(session, claim, require_live=True), luna_deadline)
                else:
                    client = self._bind_client(pinned_model_name, narrative=True) if narrative else self._bind_client(pinned_model_name)
                self._mark_running(session, claim, stage_row)
                if company:
                    # Only the approved frozen CompanyAnalysisInput is sliced;
                    # coverage is re-checked before any model call.
                    slices = company_slices.company_stage_slices(stage_name, company_input, previous_outputs, policy_payload)
                else:
                    slices = narrative_inputs.build_slices(stage_name, source_units, profile_payload, previous_outputs, policy_payload) if narrative else self._stage_slices(stage_name, bundle, structures, profile_payload, previous_outputs)
                partial_slice_count = len(slices)
                chunks: list[Mapping[str, Any]] = []
                invocation_metadata: list[dict[str, Any]] = []
                raw_records: list[tuple[InvocationResult, Mapping[str, Any]]] = []
                for slice_index, input_slice in enumerate(slices):
                    base_invocation_input = {
                        **input_slice,
                        "notice_id": pinned_notice_id,
                        "deep_review_id": str(review_id),
                        "attempt_id": str(attempt_id),
                        "stage": stage_name,
                    }
                    frozen_slice_sha256 = _canonical_hash(base_invocation_input)
                    repair_feedback: list[dict[str, str]] = []
                    for repair_attempt in range(validation_repair_attempts + 1):
                        invocation_input = deepcopy(base_invocation_input)
                        if repair_attempt:
                            invocation_input["validation_repair"] = {
                                "attempt": repair_attempt,
                                "instruction": "Return a complete replacement response. Correct only the listed validation failures; all frozen source inputs and identifiers remain authoritative.",
                                "issues": deepcopy(repair_feedback),
                            }
                        try:
                            self._renew_lease(session, claim, require_live=luna)
                            result = client.invoke(
                                stage_name,
                                invocation_input,
                                policy_payload,
                                profile={"profile_version_id": pinned_profile_id, "profile_sha256": pinned_profile_sha256} if stage_name == STAGES[1] else None,
                                prior_stages=(),
                            )
                        except ModelInvocationError as error:
                            if error.raw_response:
                                raw_records.append((
                                    InvocationResult({}, error.raw_response, _canonical_hash(invocation_input), hashlib.sha256(error.raw_response).hexdigest(), None, None, 0, (), pinned_provider, pinned_model_name),
                                    {"slice_index": slice_index, "validation_repair_attempt": repair_attempt},
                                ))
                            safe_attempts = [_safe_invocation_attempt(item) for item in error.attempts]
                            issues = _validation_repair_issues(error)
                            failure_observation = {
                                "slice_index": slice_index,
                                "input_slice_sha256": frozen_slice_sha256,
                                "status": "validation_failed" if issues else "failed",
                                "error_code": error.code,
                                **({"validation_repair_attempt": repair_attempt} if validation_repair_attempts else {}),
                                **({"response_sha256": hashlib.sha256(error.raw_response).hexdigest()} if error.raw_response else {}),
                                **({"validation_repair_issues": issues} if issues else {}),
                                "attempts": safe_attempts,
                            }
                            invocation_metadata.append(failure_observation)
                            stage_invocations.append(failure_observation)
                            if (
                                issues
                                and error.raw_response
                                and narrative
                                and stage_name in STAGES[:2]
                                and repair_attempt < validation_repair_attempts
                            ):
                                repair_feedback = issues
                                continue
                            raise DeepReviewServiceError(error.code, "승인된 model invocation이 실패했습니다", status_code=503)
                        if luna:
                            self._renew_lease(session, claim, require_live=True)
                            if time.monotonic() >= luna_deadline:
                                raise DeepReviewServiceError("review_timeout", "검토 제한시간 초과", status_code=503)
                        raw_records.append((result, {"slice_index": slice_index, "validation_repair_attempt": repair_attempt}))
                        stage_invocations.extend(_safe_invocation_attempt(item) for item in result.attempts)
                        try:
                            chunk_output = _resolve_exact_evidence_quotes(result.structured_output, structures) if source_verification_enabled else deepcopy(result.structured_output)
                            relation_diagnostics = []
                            if narrative:
                                if chunk_output.get("schema") != "bidops.deep-review-stage.v2":
                                    raise narrative_inputs.NarrativeInputError("narrative_schema_required")
                                chunk_output = narrative_inputs.bind_local_ids(chunk_output, input_slice)
                                chunk_output, relation_diagnostics = narrative_inputs.project_related_claims(chunk_output, input_slice, policy_payload)
                                if result_checks_enabled:
                                    slice_validator = company_slices.validate_company_slice_output if company else narrative_inputs.validate_slice_output
                                    slice_validator(chunk_output, input_slice, stage_name, source_verification_enabled=source_verification_enabled)
                            # Validate each untrusted chunk before paying for the
                            # next provider call. The final merge repeats this
                            # check and adds cross-chunk duplicate/conflict rules.
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
                                known_claim_ids=({row["claim_id"] for row in input_slice.get("verified_claims", [])} if narrative else known_claim_ids) | chunk_claim_ids,
                                known_evidence_ids=({row["evidence_id"] for row in input_slice.get("prior_evidence", [])} if narrative else known_evidence_ids) | chunk_evidence_ids,
                                known_evidence=input_slice.get("prior_evidence", []) if narrative else (),
                                structures=structures, source_verification_enabled=source_verification_enabled, result_checks_enabled=result_checks_enabled,
                            )
                        except (narrative_inputs.NarrativeInputError, DeepReviewValidationError) as error:
                            issues = _validation_repair_issues(error)
                            failure_observation = {
                                "slice_index": slice_index,
                                "input_slice_sha256": frozen_slice_sha256,
                                "prompt_sha256": result.input_sha256,
                                "response_sha256": hashlib.sha256(result.raw_response).hexdigest(),
                                "provider": result.provider or str(getattr(client, "provider_name", "unknown")),
                                "model": result.model or pinned_model_name,
                                **({"cli_version": CLI_VERSION, "reasoning_effort": pinned_reasoning_effort} if luna else {}),
                                "policy_sha256": pinned_policy_sha256,
                                "prompt_tokens": result.prompt_tokens,
                                "output_tokens": result.output_tokens,
                                "latency_ms": result.latency_ms,
                                "status": "validation_failed",
                                "error_code": issues[0]["code"],
                                **({"validation_repair_attempt": repair_attempt} if validation_repair_attempts else {}),
                                "validation_repair_issues": issues,
                                "attempts": [_safe_invocation_attempt(item) for item in result.attempts],
                            }
                            invocation_metadata.append(failure_observation)
                            stage_invocations.append(failure_observation)
                            if narrative and stage_name in STAGES[:2] and repair_attempt < validation_repair_attempts:
                                repair_feedback = issues
                                continue
                            raise
                        safe_attempts = [_safe_invocation_attempt(item) for item in result.attempts]
                        invocation_metadata.append({
                            "slice_index": slice_index, "input_slice_sha256": frozen_slice_sha256, "prompt_sha256": result.input_sha256,
                            "response_sha256": hashlib.sha256(result.raw_response).hexdigest(),
                            "provider": result.provider or str(getattr(client, "provider_name", "unknown")),
                            "model": result.model or pinned_model_name,
                            **({"cli_version": CLI_VERSION, "reasoning_effort": pinned_reasoning_effort} if luna else {}),
                            "policy_sha256": pinned_policy_sha256, "prompt_tokens": result.prompt_tokens,
                            "output_tokens": result.output_tokens, "latency_ms": result.latency_ms,
                            "status": "succeeded", "attempts": safe_attempts,
                            **({"validation_repair_attempt": repair_attempt} if validation_repair_attempts else {}),
                            **({"validation_repair_issues": repair_feedback} if repair_attempt else {}),
                            **({"related_claim_diagnostics": relation_diagnostics} if relation_diagnostics else {}),
                            **({"profile_selection": deepcopy(input_slice["profile_selection"])} if narrative and "profile_selection" in input_slice else {}),
                            **({"synthesis_phase": input_slice["synthesis_phase"]} if narrative and "synthesis_phase" in input_slice else {}),
                        })
                        chunks.append(chunk_output)
                        if narrative and stage_name == STAGES[2] and slice_index + 1 == partial_slice_count:
                            partial_claims = [row for chunk in chunks for row in chunk["claims"]]
                            all_evidence = {row["evidence_id"]: row for output in [*previous_outputs, *chunks] for row in output["evidence"]}
                            slices.extend(narrative_inputs.pack_verified(partial_claims, list(all_evidence.values()), budget=16000, phase="global"))
                        break
                if luna and not self._injected_client:
                    client.close()
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
                merged = merge_stage_chunks(chunks, bundle=bundle, profile=profile_payload, profile_version_id=pinned_profile_id, expected_deep_review_id=str(review_id), known_claim_ids=known_claim_ids, known_evidence_ids=known_evidence_ids, known_evidence=[row for output in previous_outputs for row in output.get("evidence", [])] if narrative else (), structures=structures, source_verification_enabled=source_verification_enabled, result_checks_enabled=result_checks_enabled, chunk_order_key=lambda chunk: chunk_orders.get(id(chunk), (STAGE_SEQUENCE[stage_name], 0, 0, 0, "", 0)))
                known_claim_ids.update(item["claim_id"] for item in merged.get("claims", []))
                known_evidence_ids.update(item["evidence_id"] for item in merged.get("evidence", []))
                invocation_doc = sorted(
                    invocation_metadata,
                    key=lambda item: (
                        item.get("slice_index", 0),
                        item.get("validation_repair_attempt", 0),
                        item.get("retry_index", 0),
                    ),
                )
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
        except InputVersionError as error:
            self._fail_claim(session, claim, stage_row, error.code)
            raise DeepReviewServiceError(error.code, "동결 입력 검증 실패", status_code=409) from error
        except narrative_inputs.NarrativeInputError as error:
            observations = tuple(invocation_metadata if "invocation_metadata" in locals() else ()) + (
                {"status": "failed", "error_code": "narrative:" + error.code},
            )
            self._fail_claim(session, claim, stage_row, "validation_failed", observations, raw_records if "raw_records" in locals() else ())
            raise DeepReviewServiceError("validation_failed", "설명형 분석의 입력·출력 범위 검증에 실패했습니다", status_code=500) from error
        except DeepReviewValidationError as error:
            # Persist stable validator codes only.  Messages, quotes, locators,
            # and model content remain outside DB/audit failure metadata.
            diagnostics = tuple(
                {"status": "failed", "error_code": f"validation:{issue.code}"}
                for issue in error.issues[:20]
            )
            observations = tuple(invocation_metadata if "invocation_metadata" in locals() else ()) + diagnostics
            self._fail_claim(session, claim, stage_row, "validation_failed", observations, raw_records if "raw_records" in locals() else ())
            raise DeepReviewServiceError("processing_failed", "model 결과가 권위 schema를 통과하지 못했습니다", status_code=500)
        except DeepReviewServiceError as error:
            observations = invocation_metadata if "invocation_metadata" in locals() else stage_invocations if "stage_invocations" in locals() else ()
            self._fail_claim(session, claim, stage_row, error.code, observations, raw_records if "raw_records" in locals() else ())
            raise
        except Exception as error:
            self._fail_claim(session, claim, stage_row, "processing_failed")
            raise DeepReviewServiceError("processing_failed", "deep review 실행에 실패했습니다", status_code=500) from error
        finally:
            if "luna" in locals() and luna and "client" in locals() and not self._injected_client:
                client.close()


__all__ = [
    "DeepReviewError", "DeepReviewService", "DeepReviewServiceError",
    "JobClaim", "StaleFenceError", "quality_status_for_review",
    "quality_status_for_reviews",
]
