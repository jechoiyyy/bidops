"""Company-scoped Luna deep review: preview → approval → review/attempt.

Demo contract §5/§6/§9/§10.  The existing Luna tables are reused with
``company_id`` (no new preview/approval/receipt table):

* **preview** freezes one ``CompanyAnalysisInput(purpose=deep_review)`` with
  ``execution_nonce`` = the new preview id, plus its ``FrozenProvenance``, into
  ``DeepReviewPreview``.  Nothing is queued.
* **create** re-builds the input with the *stored* preview id as nonce,
  requires the same hash, then creates the review, its first attempt (with the
  usual ``deep_review`` WorkJob) and the approval atomically.
* **retry** does the same for a preview whose ``target_review_id`` is the review.

Eligibility is SW사업대상=Y, a ready bundle, a completed current v7 overview,
the company's active knowledge binding and the explicitly configured demo deep
policy row.  The C-1 ``우선 검토`` grade (``effective_grade``) is never read.
A company-fit result (matched/mismatch/unknown or none) never gates a manual
request.  No model or network is called here; the frozen input is consumed by
the shared analysis slot (STEP-006), never rebuilt there.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.models import AuditEvent, IdempotencyRecord
from ...lifecycle import lock_notice
from ...lifecycle.models import Company
from ..models import (
    AnalysisPolicyVersion,
    CompanyKnowledgeBinding,
    CompanyKnowledgeVersion,
    DeepReview,
    DeepReviewApproval,
    DeepReviewAttempt,
    DeepReviewPreview,
    DocumentBundle,
    DocumentVersion,
    KnowledgeOntologyVersion,
)
from ..schemas.company_analysis import (
    AttemptView,
    CompanyDeepReviewPreviewView,
    CompanyReviewView,
    FrozenProvenance,
)
from . import luna_inputs, transfer_policy
from .card_units import (
    SELECTOR_VERSION,
    CardAnalysisSelectionError,
    card_analysis_sources,
    card_company_binding,
    card_requirement_units,
    freeze_card_analysis_input,
    select_analysis_units,
)
from .company_analysis_input import (
    CompanyAnalysisError,
    build_company_analysis_input,
    build_company_analysis_input_v2,
    card_company_transfer,
    card_extract_transfer,
    card_synthesis_missing_sections,
    check_card_transfer_payload,
    document_provenance,
    frozen_provenance,
    ready_bundle_document_sets,
    resolve_company_knowledge_context,
)
from .company_fit import company_part_is_prompt_safe, current_company_overviews, digest as overview_digest
from .company_source_units import bundle_source_units
from .company_knowledge_retrieval import CompanyRetrievalError, requirements_from_source_units
from .deep_review_validation import DeepReviewValidationError
from .deep_reviews import (
    CREATION_ACTION_BY_ACTOR_KIND,
    DeepReviewService,
    DeepReviewServiceError,
    _audit_correlation_id,
    _idempotency_hash,
    _policy_payload,
    _validate_actor,
)
from .effective_grade import sw_business_notice_ids
from .input_versions import (
    InputVersionError,
    bundle_context,
    canonical_json_hash,
    validate_pinned_policy,
)
from .luna_identity import (
    COMPANY_POLICY_IDENTITIES,
    PROVIDER,
    RL_POLICY_IDENTITIES,
    matches_runtime,
    policy_reasoning_effort,
)
from ..schemas.card_analysis import CardBatchPolicy


QUALITY_STATUS = "unmeasured_reference"
CREATE_OPERATION = "company_deep_review_create"
ATTEMPT_OPERATION = "company_deep_review_attempt"

#: Every stable code this path may answer with, and its HTTP status (§9).
ERROR_STATUS: dict[str, int] = {
    "invalid_request": 400,
    "actor_name_required": 400,
    "actor_name_invalid": 400,
    "effective_grade_ineligible": 403,
    "not_found": 404,
    "company_profile_not_ready": 409,
    "company_input_invalid": 409,
    "input_budget_exceeded": 409,
    "card_source_selection_incomplete": 409,
    "policy_not_approved": 409,
    "daily_cap_reached": 409,
    "overview_not_completed": 409,
    "bundle_not_ready": 409,
    "review_exists": 409,
    "active_attempt_exists": 409,
    "review_not_ready": 409,
    "preview_required": 409,
    "preview_changed": 409,
    "preview_used": 409,
    "idempotency_conflict": 409,
    "version_conflict": 409,
    "processing_failed": 500,
    "reference_mode_required": 503,
    "luna_disabled": 503,
    "analysis_policy_unavailable": 503,
    "model_binding_invalid": 503,
    # 결정 B55: the named source attempt cannot be resumed at synthesis.
    "resume_source_invalid": 409,
}
ERROR_MESSAGES: dict[str, str] = {
    "invalid_request": "요청을 처리할 수 없습니다",
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "effective_grade_ineligible": "SW사업대상 사전규격만 심층 분석할 수 있습니다",
    "not_found": "대상을 찾을 수 없습니다",
    "company_profile_not_ready": "회사 프로필이 아직 준비되지 않았습니다",
    "company_input_invalid": "회사 분석 입력을 만들 수 없습니다",
    "input_budget_exceeded": "분석 입력 한도를 초과했습니다",
    "card_source_selection_incomplete": "카드 분석 원문 선택을 완료할 수 없습니다",
    "policy_not_approved": "전송 정책 승인이 없습니다",
    "daily_cap_reached": "오늘의 판정 상한에 도달했습니다",
    "overview_not_completed": "개요 검토 완료가 필요합니다",
    "bundle_not_ready": "ready document bundle이 필요합니다",
    "review_exists": "같은 입력의 검토가 있습니다. 기존 검토에서 새 분석을 요청하십시오",
    "active_attempt_exists": "이미 대기·실행 중인 검토가 있습니다",
    "review_not_ready": "재시도할 수 있는 검토가 아닙니다",
    "preview_required": "전송 미리보기를 확인하십시오",
    "preview_changed": "입력이 변경되었습니다. 전송 미리보기를 다시 확인하십시오",
    "preview_used": "이미 승인한 미리보기입니다",
    "idempotency_conflict": "같은 request_id가 다른 요청에 사용되었습니다",
    "version_conflict": "회사 지식 또는 정책 버전이 바뀌었습니다. 새 검토로 요청하십시오",
    "processing_failed": "심층 검토를 처리할 수 없습니다",
    "reference_mode_required": "참조 실행 모드가 필요합니다",
    "luna_disabled": "Luna 심층 검토가 비활성입니다",
    "analysis_policy_unavailable": "심층 분석 정책을 사용할 수 없습니다",
    "model_binding_invalid": "심층 분석 모델 설정이 유효하지 않습니다",
    "resume_source_invalid": "이어서 실행할 수 없는 원본 시도입니다",
}


def _error(code: str, *, request_id: UUID | None = None) -> DeepReviewServiceError:
    if code not in ERROR_STATUS:
        code = "processing_failed"
    return DeepReviewServiceError(code, ERROR_MESSAGES[code], status_code=ERROR_STATUS[code], request_id=request_id)


# --- configuration and policy ------------------------------------------------------


def rl_path(settings: Any, company: Company | None) -> bool:
    """RL-03 real-company path: ``BIDOPS_RL_ANALYSIS_ENABLED`` and a real company."""

    return bool(
        company is not None
        and getattr(settings, "rl_analysis_enabled", False)
        and company.is_fictional is False
    )


def _gate_company(session: Session, company_id: UUID, settings: Any) -> Company:
    """§9 order: path closed / unknown company → 404, then reference mode, then Luna.

    The path is open for any company while ``BIDOPS_DEMO_ENABLED`` (DEMO rule)
    and, otherwise, for the real company while ``BIDOPS_RL_ANALYSIS_ENABLED``
    (RL-03 "가드 두 겹" (b)).  Reference mode and the Luna flag stay required.
    """

    company = session.get(Company, company_id)
    if company is None:
        raise _error("not_found")
    if not getattr(settings, "demo_enabled", False) and not rl_path(settings, company):
        raise _error("not_found")
    if not settings.reference_workflow_mode:
        raise _error("reference_mode_required")
    if not settings.luna_deep_review_enabled:
        raise _error("luna_disabled")
    return company


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


@dataclass(frozen=True)
class CompanyDeepPolicy:
    """The demo deep policy row selected by ``BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID``."""

    row: AnalysisPolicyVersion
    payload: Mapping[str, Any]
    generation: Mapping[str, Any]
    generation_config_sha256: str
    model_revision: str | None
    source_characters: int
    profile_characters: int
    path_limit_per_requirement: int
    pipeline_version: str = "narrative-v2"
    #: ``card-v1`` packing values (``batch_size``/``batch_max_chars``/``repair_attempts``/``target_seconds``)
    #: and, for ``analysis-policy-luna-rl-v2``/``-v3``, ``selector`` (결정 B23·B30).
    card: Mapping[str, Any] | None = None

    @property
    def selector_version(self) -> str:
        """``card.selector`` of the pinned policy; v1 rows carry none (``card-sections-v1``)."""

        value = (self.card or {}).get("selector")
        return value if isinstance(value, str) else SELECTOR_VERSION


def resolve_company_deep_policy(session: Session, settings: Any = None, *, rl: bool = False) -> CompanyDeepPolicy:
    """Explicit policy row only; there is no global active-policy fallback.

    ``rl=False`` reads ``BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID`` and accepts
    only a ``narrative-v2`` row (unchanged).  ``rl=True`` (real company with
    ``BIDOPS_RL_ANALYSIS_ENABLED``) reads ``BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID``
    and accepts only the ``card-v1`` row of ``analysis-policy-luna-rl-v1`` .. ``-v9``
    (RL-03 spec "정책 행·선택", 결정 B23·B30·B33·B35·B37·B51·B53·B55); an unset/other row is
    ``analysis_policy_unavailable``.

    ``analysis_policy_unavailable``: setting unset, row missing, row not the
    approved policy bytes, not an identity in ``COMPANY_POLICY_IDENTITIES``
    (contract §9; global Luna rows carry no company/graph input description),
    or an unusable payload -- including a missing or non-positive
    ``chunking.path_limit_per_requirement`` (no default).
    ``model_binding_invalid``: not a Luna ``codex-exec`` binding, or the mock
    provider is configured on the DEMO (``rl=False``) path.  The RL ``card-v1``
    path accepts the mock provider in reference mode (결정 B16): the pinned row
    is unchanged and the worker swaps in the deterministic mock card client.
    """

    settings = settings or get_settings()
    policy_id = getattr(
        settings, "rl_deep_review_policy_version_id" if rl else "demo_deep_review_policy_version_id", None,
    )
    row = session.get(AnalysisPolicyVersion, policy_id) if policy_id else None
    if row is None:
        raise _error("analysis_policy_unavailable")
    payload = _policy_payload(row)
    generation = payload.get("generation")
    mock_allowed = bool(rl) and bool(getattr(settings, "reference_workflow_mode", False))
    if (settings.analysis_provider == "mock" and not mock_allowed) or not luna_inputs.is_luna(row):
        raise _error("model_binding_invalid")
    if isinstance(generation, Mapping) and not matches_runtime(row.model_name, generation.get("reasoning_effort")):
        # A legacy company row is a runner binding mismatch even though its
        # identity is company-scoped; check this before the identity set.
        raise _error("model_binding_invalid")
    try:
        validate_pinned_policy(row, allow_unmeasured_reference=True)
    except InputVersionError:
        raise _error("analysis_policy_unavailable") from None
    chunking = payload.get("chunking")
    pipeline = payload.get("pipeline_version")
    identity = payload.get("policy_identity")
    if (
        pipeline not in {"narrative-v2", "card-v1"}
        # card-v1 is exactly the RL identity on the RL path; narrative-v2 never is.
        or (pipeline == "card-v1") != (identity in RL_POLICY_IDENTITIES)
        or (pipeline == "card-v1") != bool(rl)
        or identity not in COMPANY_POLICY_IDENTITIES
        or not isinstance(chunking, Mapping)
        or not isinstance(generation, Mapping)
        or not _positive_int(chunking.get("source_characters"))
        or not _positive_int(chunking.get("profile_characters"))
    ):
        raise _error("analysis_policy_unavailable")
    path_limit = chunking.get("path_limit_per_requirement")
    if not _positive_int(path_limit):
        raise _error("analysis_policy_unavailable")
    if not matches_runtime(row.model_name, generation.get("reasoning_effort")):
        raise _error("model_binding_invalid")
    revision = payload.get("model_revision")
    if revision is not None and not isinstance(revision, str):
        raise _error("analysis_policy_unavailable")
    card = payload.get("card")
    if pipeline == "card-v1":
        try:
            CardBatchPolicy.model_validate({
                key: card[key] for key in ("batch_size", "batch_max_chars", "repair_attempts")
            })
        except (KeyError, TypeError, ValueError):
            raise _error("analysis_policy_unavailable") from None
    return CompanyDeepPolicy(
        row=row, payload=payload, generation=dict(generation),
        generation_config_sha256=canonical_json_hash(dict(generation)), model_revision=revision,
        source_characters=int(chunking["source_characters"]),
        profile_characters=int(chunking["profile_characters"]),
        path_limit_per_requirement=int(path_limit),
        pipeline_version=str(pipeline),
        card=dict(card) if pipeline == "card-v1" and isinstance(card, Mapping) else None,
    )


# --- frozen input ------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedCompanyDeepReview:
    """Everything a company preview freezes (and an approval re-checks)."""

    company_id: UUID
    notice_id: int
    bundle_id: UUID
    profile_version_id: UUID
    graph_version_id: UUID
    policy: CompanyDeepPolicy
    input: dict[str, Any]
    input_sha256: str
    provenance: dict[str, Any]


def _bundle_owned_by_notice(session: Session, bundle_id: UUID, notice_id: int) -> None:
    bundle = session.get(DocumentBundle, bundle_id)
    if bundle is None or bundle.notice_id != int(notice_id):
        raise _error("not_found")


def _ready_bundle(service: DeepReviewService, session: Session, notice_id: int, bundle_id: UUID):
    try:
        bundle, structures = bundle_context(session, bundle_id, structure_loader=service.structure_loader)
    except InputVersionError as error:
        raise _error("not_found" if error.code == "not_found" else "bundle_not_ready") from None
    except DeepReviewValidationError:
        raise _error("bundle_not_ready") from None
    if bundle["notice_id"] != int(notice_id):
        raise _error("not_found")
    return bundle, structures


def company_source_units(
    session: Session,
    bundle: Mapping[str, Any],
    structures: Mapping[str, Mapping[str, Any]],
    *,
    source_characters: int,
) -> list[dict[str, Any]]:
    """The existing splitter's units, exactly as the narrative worker builds them.

    ``DeepReviewService._requirements`` with ``max_requirements=1`` and the
    policy ``source_characters``; ``document_requirement_ids`` from the bundle
    inventory.  An inventory mismatch is ``company_input_invalid`` (the legacy
    worker would fail the same input after approval).  The splitting itself is
    ``company_source_units.bundle_source_units``, shared with the company fit
    enqueue (STEP-008); this wrapper keeps the deep path's 409 error.
    """

    try:
        return bundle_source_units(session, bundle, structures, source_characters=source_characters)
    except CompanyAnalysisError:
        raise _error("company_input_invalid") from None


def prepare_company_deep_review(
    service: DeepReviewService,
    session: Session,
    *,
    company_id: UUID,
    notice_id: int,
    bundle_id: UUID,
    execution_nonce: UUID,
    target_review_id: UUID | None,
    settings: Any = None,
) -> PreparedCompanyDeepReview:
    """Gate (binding → policy → model → overview → SW → bundle) and build the input.

    Read-only; the caller has already passed ``_gate_company``.  A ``card-v1``
    policy (RL path) skips the overview step entirely -- ``current_company_overviews``
    is not read and ``overview_not_completed`` is never answered (RL-03 "개요
    의존 제거" 1·5); its v2 input freezes ``overview_*`` as null.
    """

    settings = settings or get_settings()
    try:
        knowledge = resolve_company_knowledge_context(session, company_id)
    except CompanyAnalysisError as error:
        raise _error("not_found" if error.code == "company_not_found" else error.code) from None
    policy = resolve_company_deep_policy(session, settings, rl=rl_path(settings, knowledge.company))
    if policy.pipeline_version == "card-v1":
        return _prepare_card_review(
            service, session, knowledge=knowledge, policy=policy, company_id=company_id,
            notice_id=notice_id, bundle_id=bundle_id, execution_nonce=execution_nonce,
            target_review_id=target_review_id,
        )
    overview = current_company_overviews(session, [notice_id]).get(int(notice_id))
    if overview is None:
        raise _error("overview_not_completed")
    if int(notice_id) not in sw_business_notice_ids(session, [notice_id]):
        raise _error("effective_grade_ineligible")
    bundle, structures = _ready_bundle(service, session, notice_id, bundle_id)
    run, result, _document = overview
    units = company_source_units(session, bundle, structures, source_characters=policy.source_characters)
    try:
        requirements = requirements_from_source_units(units, knowledge.ontology)
        document_ids = [UUID(str(row["document_version_id"])) for row in bundle["documents"]]
        value = build_company_analysis_input(
            purpose="deep_review",
            execution_nonce=execution_nonce,
            knowledge=knowledge,
            notice_id=int(notice_id),
            document_version_ids=document_ids,
            overview_run_id=run.id,
            overview_sha256=overview_digest(result),
            policy_version_id=policy.row.id,
            policy_sha256=policy.row.policy_sha256,
            model_name=policy.row.model_name,
            model_revision=policy.model_revision,
            generation=policy.generation,
            requirements=requirements,
            path_limit_per_requirement=policy.path_limit_per_requirement,
            profile_characters=policy.profile_characters,
            bundle_id=bundle_id,
            target_review_id=target_review_id,
        )
        if not company_part_is_prompt_safe(value):
            raise CompanyAnalysisError("company_input_invalid")
        input_hash = canonical_json_hash(value)
        provenance = frozen_provenance(
            value, input_sha256=input_hash, documents=document_provenance(session, document_ids)
        )
        FrozenProvenance.model_validate(provenance)
    except (CompanyAnalysisError, CompanyRetrievalError, ValidationError, TypeError, ValueError):
        raise _error("company_input_invalid") from None
    return PreparedCompanyDeepReview(
        company_id=company_id, notice_id=int(notice_id), bundle_id=bundle_id,
        profile_version_id=knowledge.profile.id, graph_version_id=knowledge.graph.id, policy=policy,
        input=value, input_sha256=input_hash, provenance=provenance,
    )


def card_analysis_for_bundle(
    session: Session,
    bundle: Mapping[str, Any],
    structures: Mapping[Any, Mapping[str, Any]],
    *,
    knowledge: Any,
    policy: CompanyDeepPolicy,
):
    """The frozen ``card_analysis`` of a ready bundle (HP-03 unit/selector/batch rules)."""

    card = policy.card or {}
    selection = select_analysis_units(
        card_analysis_sources(session, bundle, structures),
        policy=CardBatchPolicy.model_validate({
            key: card[key] for key in ("batch_size", "batch_max_chars", "repair_attempts")
        }),
        selector_version=policy.selector_version,
    )
    return freeze_card_analysis_input(selection, company_binding=card_company_binding(knowledge))


def _prepare_card_review(
    service: DeepReviewService,
    session: Session,
    *,
    knowledge: Any,
    policy: CompanyDeepPolicy,
    company_id: UUID,
    notice_id: int,
    bundle_id: UUID,
    execution_nonce: UUID,
    target_review_id: UUID | None,
) -> PreparedCompanyDeepReview:
    """RL ``card-v1``: SW=Y → ready bundle → card units → v2 input (no overview, D1).

    The transfer projection of every stage that can be built before a call
    (the extract batches and the company part of role/synthesis) is checked
    here, at the same place as the prompt-safety check; a violation is
    ``company_input_invalid`` and nothing is frozen (spec "전송 payload 규칙").
    """

    if int(notice_id) not in sw_business_notice_ids(session, [notice_id]):
        raise _error("effective_grade_ineligible")
    bundle, structures = _ready_bundle(service, session, notice_id, bundle_id)
    try:
        card_input = card_analysis_for_bundle(
            session, bundle, structures, knowledge=knowledge, policy=policy,
        )
        units = card_requirement_units(card_input, bundle, structures)
        requirements = requirements_from_source_units(units, knowledge.ontology)
        document_ids = [UUID(str(row["document_version_id"])) for row in bundle["documents"]]
        value = build_company_analysis_input_v2(
            card_analysis=card_input.model_dump(mode="json"),
            purpose="deep_review",
            execution_nonce=execution_nonce,
            knowledge=knowledge,
            notice_id=int(notice_id),
            document_version_ids=document_ids,
            overview_run_id=None,
            overview_sha256=None,
            policy_version_id=policy.row.id,
            policy_sha256=policy.row.policy_sha256,
            model_name=policy.row.model_name,
            model_revision=policy.model_revision,
            generation=policy.generation,
            requirements=requirements,
            path_limit_per_requirement=policy.path_limit_per_requirement,
            profile_characters=policy.profile_characters,
            bundle_id=bundle_id,
            target_review_id=target_review_id,
        )
        # The frozen v2 input itself is never sent.  Prompt safety is checked on
        # the company part that is sent (``check_card_transfer_payload``), the
        # same rule ``company_part_is_prompt_safe`` applies to narrative inputs.
        # A stage sends only the facts its compare references (결정 B11), so the
        # preview checks the projection of every fact any stage could reference.
        every_fact = [row["fact_key"] for row in value["profile_facts"]]
        company_part = card_company_transfer(value, every_fact)
        synthesis_part = {"roles": [], **company_part}
        missing_sections = card_synthesis_missing_sections(value)
        if missing_sections is not None:
            synthesis_part["missing_sections"] = missing_sections  # 결정 B24 (v2 only)
        check_card_transfer_payload("synthesis", synthesis_part, value, fact_keys=every_fact)
        for index in range(len(card_input.batches)):
            card_extract_transfer(value, index, knowledge.ontology)
        input_hash = canonical_json_hash(value)
        provenance = frozen_provenance(
            value, input_sha256=input_hash, documents=document_provenance(session, document_ids)
        )
        FrozenProvenance.model_validate(provenance)
    except CardAnalysisSelectionError as error:
        raise _error(error.code) from None
    except (CompanyAnalysisError, CompanyRetrievalError, ValidationError, TypeError, ValueError):
        raise _error("company_input_invalid") from None
    return PreparedCompanyDeepReview(
        company_id=company_id, notice_id=int(notice_id), bundle_id=bundle_id,
        profile_version_id=knowledge.profile.id, graph_version_id=knowledge.graph.id, policy=policy,
        input=value, input_sha256=input_hash, provenance=provenance,
    )


def _same_lineage(review: DeepReview, prepared: PreparedCompanyDeepReview) -> bool:
    return (
        review.company_id == prepared.company_id
        and review.notice_id == prepared.notice_id
        and review.bundle_id == prepared.bundle_id
        and review.profile_version_id == prepared.profile_version_id
        and review.graph_version_id == prepared.graph_version_id
        and review.policy_version_id == prepared.policy.row.id
    )


def _safe_hash(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return canonical_json_hash(value)
    except (TypeError, ValueError):
        return None


# --- transaction ownership ---------------------------------------------------------


class _UnitOfWork:
    """``commit=True``: the function owns the transaction (commit / rollback).

    ``commit=False`` (RL automatic path, spec "전송 승인"): the caller owns the
    transaction; the function works inside a SAVEPOINT, releases it on success
    and rolls only it back on failure, so a failed gate leaves no preview,
    approval or attempt behind and the caller's other work intact.
    """

    def __init__(self, session: Session, commit: bool) -> None:
        self.session = session
        self.commit_owned = commit
        self.nested = None if commit else session.begin_nested()

    def finish(self) -> None:
        if self.commit_owned:
            self.session.commit()
        elif self.nested is not None and self.nested.is_active:
            self.nested.commit()

    def abort(self) -> None:
        if self.commit_owned:
            self.session.rollback()
        elif self.nested is not None and self.nested.is_active:
            self.nested.rollback()


# --- preview -----------------------------------------------------------------------


def preview_company_deep_review(
    service: DeepReviewService,
    session: Session,
    *,
    company_id: UUID,
    notice_id: int,
    bundle_id: UUID,
    source_verification_enabled: bool = True,
    review_id: UUID | None = None,
    settings: Any = None,
    commit: bool = True,
) -> dict[str, Any]:
    """POST base/pre-specs/{notice_id}/deep-review-previews → CompanyDeepReviewPreviewDTO.

    ``review_id`` is only for a retry of the same company/notice/bundle review
    whose frozen lineage (profile/graph/policy) is still current; a new
    graph/profile is a new review (``version_conflict``).  Only the preview row
    is written; a failure writes nothing.  ``commit=False``: the caller owns
    the transaction (``_UnitOfWork``).
    """

    settings = settings or get_settings()
    work = _UnitOfWork(session, commit)
    try:
        if source_verification_enabled is not True:
            raise _error("invalid_request")
        _gate_company(session, company_id, settings)
        if lock_notice(session, int(notice_id)) is None:
            raise _error("not_found")
        _bundle_owned_by_notice(session, bundle_id, notice_id)
        review = None
        if review_id is not None:
            review = session.get(DeepReview, review_id)
            if (
                review is None
                or review.company_id != company_id
                or review.notice_id != int(notice_id)
                or review.bundle_id != bundle_id
            ):
                raise _error("not_found")
        preview_id = uuid4()
        prepared = prepare_company_deep_review(
            service, session, company_id=company_id, notice_id=notice_id, bundle_id=bundle_id,
            execution_nonce=preview_id, target_review_id=review_id, settings=settings,
        )
        if review is not None and not _same_lineage(review, prepared):
            raise _error("version_conflict")
        row = DeepReviewPreview(
            id=preview_id, notice_id=int(notice_id), bundle_id=bundle_id,
            profile_version_id=prepared.profile_version_id, policy_version_id=prepared.policy.row.id,
            input_sha256=prepared.input_sha256, input_snapshot=prepared.input,
            company_id=company_id, graph_version_id=prepared.graph_version_id,
            provenance_jsonb=prepared.provenance,
        )
        session.add(row)
        session.flush()
        try:
            response = CompanyDeepReviewPreviewView.model_validate({
                "preview_id": str(row.id), "input_sha256": row.input_sha256,
                "provider": PROVIDER, "model": prepared.policy.row.model_name,
                "reasoning_effort": policy_reasoning_effort(prepared.policy.row),
                "quality_status": QUALITY_STATUS, "source_verification_enabled": True,
                "input": deepcopy(prepared.input),
                "company_id": str(company_id), "profile_version_id": str(prepared.profile_version_id),
                "graph_version_id": str(prepared.graph_version_id),
                "graph_sha256": prepared.input["graph_sha256"],
                "ontology_version": prepared.input["ontology_version"],
            }).model_dump(mode="json")
        except ValidationError:
            raise _error("processing_failed") from None
        work.finish()
        return response
    except DeepReviewServiceError:
        work.abort()
        raise
    except BaseException:
        if not commit:
            work.abort()
        raise


# --- approval ----------------------------------------------------------------------


def _load_preview(session: Session, preview_id: UUID | None, company_id: UUID) -> DeepReviewPreview:
    row = session.get(DeepReviewPreview, preview_id) if preview_id else None
    if row is None:
        raise _error("preview_required")
    if row.company_id != company_id:
        # A legacy (NULL) preview or another company's preview is not this
        # company's resource (§9: foreign ids are 404).
        raise _error("not_found")
    return row


def _preview_used(session: Session, preview_id: UUID) -> bool:
    return session.scalar(
        select(DeepReviewApproval.id).where(DeepReviewApproval.preview_id == preview_id).limit(1)
    ) is not None


def recheck_company_preview(
    service: DeepReviewService,
    session: Session,
    row: DeepReviewPreview,
    *,
    company_id: UUID,
    notice_id: int,
    bundle_id: UUID,
    target_review_id: UUID | None,
    settings: Any = None,
) -> PreparedCompanyDeepReview:
    """Rebuild the input with the stored preview id as nonce; any change is ``preview_changed``.

    Gate failures of the rebuild (binding gone, overview not completed, …)
    keep their own §9 code.
    """

    frozen = row.input_snapshot
    expected_target = None if target_review_id is None else str(target_review_id)
    if (
        row.company_id != company_id
        or row.notice_id != int(notice_id)
        or row.bundle_id != bundle_id
        or not isinstance(frozen, Mapping)
        or frozen.get("target_review_id") != expected_target
        or frozen.get("execution_nonce") != str(row.id)
    ):
        raise _error("preview_changed")
    prepared = prepare_company_deep_review(
        service, session, company_id=company_id, notice_id=notice_id, bundle_id=bundle_id,
        execution_nonce=row.id, target_review_id=target_review_id, settings=settings,
    )
    if (
        prepared.input_sha256 != row.input_sha256
        or _safe_hash(frozen) != row.input_sha256
        or prepared.provenance != row.provenance_jsonb
        or row.profile_version_id != prepared.profile_version_id
        or row.graph_version_id != prepared.graph_version_id
        or row.policy_version_id != prepared.policy.row.id
    ):
        raise _error("preview_changed")
    return prepared


def _active_company_review(session: Session, company_id: UUID, notice_id: int) -> bool:
    return session.scalar(
        select(DeepReview.id).where(
            DeepReview.company_id == company_id,
            DeepReview.notice_id == int(notice_id),
            DeepReview.status.in_(("queued", "running")),
        ).limit(1)
    ) is not None


def _creation_metadata(
    service: DeepReviewService,
    review: DeepReview,
    prepared: PreparedCompanyDeepReview,
    row: DeepReviewPreview,
    correlation_id: UUID | None,
) -> dict[str, Any]:
    """Same shape as the legacy creation audit (the worker re-checks it) + company ids."""

    policy = prepared.policy.row
    provider, runtime_model = service._runtime_identity(policy)
    return {
        "notice_id": review.notice_id, "bundle_id": str(review.bundle_id),
        "profile_version_id": str(review.profile_version_id),
        "profile_sha256": prepared.input["profile_sha256"],
        "policy_version_id": str(policy.id), "policy_sha256": policy.policy_sha256,
        "policy_model_name": policy.model_name,
        # Provider lineage: ``codex-exec`` or, for the RL mock card path (B16),
        # ``mock-analysis`` -- the latter reads as ``quality_status=mock_reference``.
        "analysis_provider": provider, "runtime_model": runtime_model,
        "external_provider_approved": True,
        "policy_quality": {"status": "reference_workflow_unmeasured", "deployable": False},
        "reference_workflow_mode": True,
        # The company path never reads the C-1 grade (§9); SW=Y is the gate.
        "effective_grade": None, "grade_source": "company_sw_business",
        "source_run_id": None, "source_review_id": None,
        "company_id": str(review.company_id), "graph_version_id": str(review.graph_version_id),
        "graph_sha256": prepared.input["graph_sha256"], "preview_id": str(row.id),
        "input_sha256": row.input_sha256,
        **({"correlation_id": str(correlation_id)} if correlation_id is not None else {}),
    }


def create_company_review(
    service: DeepReviewService,
    session: Session,
    *,
    company_id: UUID,
    notice_id: int,
    bundle_id: UUID,
    preview_id: UUID | None,
    actor: str | None,
    request_id: UUID,
    source_verification_enabled: bool = True,
    settings: Any = None,
    actor_kind: str = "human",
    commit: bool = True,
) -> dict[str, Any]:
    """POST base/pre-specs/{notice_id}/deep-reviews → 202 CompanyReviewView.

    The exact request_id replay returns the first response before any state
    check.  ``review_exists`` leaves the preview unconsumed.  Review, first
    attempt (+WorkJob), approval, idempotency record and audit are one
    transaction.  ``actor_kind="system"`` is the RL policy-level path: the
    creation audit, the attempt selection and the approval audit carry the
    system actor; ``commit=False`` leaves the transaction to the caller.
    """

    settings = settings or get_settings()
    claimed_name = _validate_actor(actor)
    if actor_kind not in CREATION_ACTION_BY_ACTOR_KIND:
        raise _error("invalid_request", request_id=request_id)
    request_hash = _idempotency_hash(CREATE_OPERATION, {
        "company_id": str(company_id), "notice_id": int(notice_id), "bundle_id": str(bundle_id),
        "preview_id": str(preview_id) if preview_id else None,
    })
    aggregate_id = f"{company_id}:{int(notice_id)}"
    replay = {
        "operation": CREATE_OPERATION, "aggregate_type": "company_notice", "aggregate_id": aggregate_id,
        "actor": claimed_name, "request_id": request_id, "request_hash": request_hash,
    }
    work = _UnitOfWork(session, commit)
    try:
        if source_verification_enabled is not True:
            raise _error("invalid_request", request_id=request_id)
        _gate_company(session, company_id, settings)
        if lock_notice(session, int(notice_id)) is None:
            raise _error("not_found", request_id=request_id)
        duplicate = service._idempotent_response(session, **replay)
        if duplicate is not None:
            work.finish()
            return dict(duplicate)
        _bundle_owned_by_notice(session, bundle_id, notice_id)
        row = _load_preview(session, preview_id, company_id)
        prepared = recheck_company_preview(
            service, session, row, company_id=company_id, notice_id=notice_id, bundle_id=bundle_id,
            target_review_id=None, settings=settings,
        )
        if _preview_used(session, row.id):
            raise _error("preview_used", request_id=request_id)
        if _active_company_review(session, company_id, notice_id):
            raise _error("active_attempt_exists", request_id=request_id)
        existing = session.scalar(select(DeepReview.id).where(
            DeepReview.company_id == company_id,
            DeepReview.notice_id == int(notice_id),
            DeepReview.bundle_id == bundle_id,
            DeepReview.profile_version_id == prepared.profile_version_id,
            DeepReview.graph_version_id == prepared.graph_version_id,
            DeepReview.policy_version_id == prepared.policy.row.id,
        ).limit(1))
        if existing is not None:
            raise _error("review_exists", request_id=request_id)
        correlation_id = _audit_correlation_id(
            session, actions=("document_bundle.create",), aggregate_type="document_bundle",
            aggregate_id=str(bundle_id),
        )
        review = DeepReview(
            id=uuid4(), company_id=company_id, graph_version_id=prepared.graph_version_id,
            notice_id=int(notice_id), bundle_id=bundle_id, profile_version_id=prepared.profile_version_id,
            policy_version_id=prepared.policy.row.id, effective_grade_at_start="unknown",
            status="queued", requested_by_name=claimed_name,
        )
        session.add(review)
        session.flush()
        attempt = service._seed_attempt(
            session, review, sequence=1, actor=claimed_name, source_verification_enabled=True,
            actor_kind=actor_kind,
        )
        luna_inputs.approve(
            session, row, attempt.id, claimed_name, request_id, actor_kind=actor_kind,
            provider=service._runtime_identity(prepared.policy.row)[0],
        )
        session.add(AuditEvent(
            actor_kind=actor_kind, claimed_name=claimed_name, action=CREATION_ACTION_BY_ACTOR_KIND[actor_kind],
            aggregate_type="deep_review", aggregate_id=str(review.id), request_id=str(request_id),
            safe_metadata=_creation_metadata(service, review, prepared, row, correlation_id),
        ))
        session.flush()
        response = company_review_view(service, session, review, settings=settings)
        session.add(IdempotencyRecord(
            operation=CREATE_OPERATION, aggregate_type="company_notice", aggregate_id=aggregate_id,
            claimed_name=claimed_name, request_id=request_id, request_sha256=request_hash,
            response_status=202, response_snapshot=response,
        ))
        work.finish()
        return response
    except DeepReviewServiceError:
        work.abort()
        raise
    except IntegrityError as exc:
        work.abort()
        duplicate = service._idempotent_response(session, **replay)
        if duplicate is not None:
            return dict(duplicate)
        raise _conflict_after_race(session, preview_id, request_id) from exc
    except BaseException:
        if not commit:
            work.abort()
        raise


def _conflict_after_race(session: Session, preview_id: UUID | None, request_id: UUID) -> DeepReviewServiceError:
    if preview_id is not None and _preview_used(session, preview_id):
        return _error("preview_used", request_id=request_id)
    return _error("review_exists", request_id=request_id)


def create_company_attempt(
    service: DeepReviewService,
    session: Session,
    *,
    company_id: UUID,
    review_id: UUID,
    preview_id: UUID | None,
    actor: str | None,
    request_id: UUID,
    source_verification_enabled: bool = True,
    settings: Any = None,
    actor_kind: str = "human",
    commit: bool = True,
) -> dict[str, Any]:
    """POST base/deep-reviews/{review_id}/attempts → 202 AttemptView.

    Only a preview frozen with ``target_review_id`` = this review is accepted;
    its lineage must still be the review's (otherwise a new review is needed).
    ``actor_kind``/``commit`` as in ``create_company_review`` (RL re-verdict path).
    """

    settings = settings or get_settings()
    claimed_name = _validate_actor(actor)
    if actor_kind not in CREATION_ACTION_BY_ACTOR_KIND:
        raise _error("invalid_request", request_id=request_id)
    request_hash = _idempotency_hash(ATTEMPT_OPERATION, {
        "company_id": str(company_id), "review_id": str(review_id),
        "preview_id": str(preview_id) if preview_id else None,
    })
    replay = {
        "operation": ATTEMPT_OPERATION, "aggregate_type": "deep_review", "aggregate_id": str(review_id),
        "actor": claimed_name, "request_id": request_id, "request_hash": request_hash,
    }
    work = _UnitOfWork(session, commit)
    try:
        if source_verification_enabled is not True:
            raise _error("invalid_request", request_id=request_id)
        _gate_company(session, company_id, settings)
        notice_id = session.scalar(select(DeepReview.notice_id).where(
            DeepReview.id == review_id, DeepReview.company_id == company_id,
        ))
        if notice_id is None:
            raise _error("not_found", request_id=request_id)
        lock_notice(session, int(notice_id))
        review = session.scalar(select(DeepReview).where(DeepReview.id == review_id).with_for_update())
        if review is None or review.company_id != company_id:
            raise _error("not_found", request_id=request_id)
        duplicate = service._idempotent_response(session, **replay)
        if duplicate is not None:
            work.finish()
            return dict(duplicate)
        current = session.get(DeepReviewAttempt, review.current_attempt_id) if review.current_attempt_id else None
        if current is None or current.deep_review_id != review.id or current.status == "superseded":
            raise _error("review_not_ready", request_id=request_id)
        active = session.scalar(select(DeepReviewAttempt.id).where(
            DeepReviewAttempt.deep_review_id == review.id,
            DeepReviewAttempt.status.in_(("queued", "running")),
        ).limit(1))
        if active is not None or _active_company_review(session, company_id, review.notice_id):
            raise _error("active_attempt_exists", request_id=request_id)
        if current.status not in {"failed", "completed"}:
            raise _error("review_not_ready", request_id=request_id)
        correlation_id = _audit_correlation_id(
            session, actions=tuple(CREATION_ACTION_BY_ACTOR_KIND.values()), aggregate_type="deep_review",
            aggregate_id=str(review.id),
        )
        bundle_correlation_id = _audit_correlation_id(
            session, actions=("document_bundle.create",), aggregate_type="document_bundle",
            aggregate_id=str(review.bundle_id),
        )
        if correlation_id != bundle_correlation_id:
            raise _error("processing_failed", request_id=request_id)
        row = _load_preview(session, preview_id, company_id)
        prepared = recheck_company_preview(
            service, session, row, company_id=company_id, notice_id=review.notice_id,
            bundle_id=review.bundle_id, target_review_id=review.id, settings=settings,
        )
        if not _same_lineage(review, prepared):
            raise _error("version_conflict", request_id=request_id)
        if _preview_used(session, row.id):
            raise _error("preview_used", request_id=request_id)
        max_sequence = session.scalar(
            select(DeepReviewAttempt.sequence).where(DeepReviewAttempt.deep_review_id == review.id)
            .order_by(DeepReviewAttempt.sequence.desc()).limit(1)
        ) or 0
        # Completed attempts stay immutable; only a failed current attempt is
        # superseded (legacy retry bookkeeping).
        if current.status == "failed":
            current.status = "superseded"
        attempt = service._seed_attempt(
            session, review, sequence=int(max_sequence) + 1, actor=claimed_name, source_verification_enabled=True,
            actor_kind=actor_kind,
        )
        luna_inputs.approve(
            session, row, attempt.id, claimed_name, request_id, actor_kind=actor_kind,
            provider=service._runtime_identity(prepared.policy.row)[0],
        )
        session.flush()
        try:
            response = AttemptView.model_validate(service._attempt_view(session, attempt)).model_dump(mode="json")
        except ValidationError:
            raise _error("processing_failed", request_id=request_id) from None
        session.add(IdempotencyRecord(
            operation=ATTEMPT_OPERATION, aggregate_type="deep_review", aggregate_id=str(review.id),
            claimed_name=claimed_name, request_id=request_id, request_sha256=request_hash,
            response_status=202, response_snapshot=response,
        ))
        session.add(AuditEvent(
            actor_kind=actor_kind, claimed_name=claimed_name, action="deep_review.attempt",
            aggregate_type="deep_review", aggregate_id=str(review.id), request_id=str(request_id),
            safe_metadata={
                "attempt_id": str(attempt.id), "sequence": attempt.sequence,
                "company_id": str(company_id), "preview_id": str(row.id), "input_sha256": row.input_sha256,
                **({"correlation_id": str(correlation_id)} if correlation_id is not None else {}),
            },
        ))
        work.finish()
        return response
    except DeepReviewServiceError:
        work.abort()
        raise
    except IntegrityError as exc:
        work.abort()
        duplicate = service._idempotent_response(session, **replay)
        if duplicate is not None:
            return dict(duplicate)
        if preview_id is not None and _preview_used(session, preview_id):
            raise _error("preview_used", request_id=request_id) from exc
        raise _error("active_attempt_exists", request_id=request_id) from exc
    except BaseException:
        if not commit:
            work.abort()
        raise


# --- RL automatic path (policy-level approval) -------------------------------------


@dataclass(frozen=True)
class RLVerdictStart:
    """The rows one RL start created (caller commits)."""

    review_id: UUID
    attempt_id: UUID
    preview_id: UUID
    approval_id: UUID
    input_sha256: str
    new_review: bool


def _latest_ready_bundle_id(session: Session, notice_id: int) -> UUID:
    found = ready_bundle_document_sets(session, [int(notice_id)]).get(int(notice_id))
    if found is None:
        raise _error("bundle_not_ready")
    return found[0]


def start_rl_verdict(
    service: DeepReviewService,
    session: Session,
    *,
    company_id: UUID,
    notice_id: int,
    bundle_id: UUID | None = None,
    settings: Any = None,
    now: datetime | None = None,
    commit: bool = False,
    on_started: Any = None,
) -> RLVerdictStart:
    """Create preview → review/attempt → approval automatically under the active policy approval.

    RL-03 spec "전송 승인"·"정책 단위 사전 승인" order: RL path (real company,
    ``BIDOPS_RL_ANALYSIS_ENABLED``; otherwise 404) → approval active → policy
    sha equal → scope → daily cap (``policy_not_approved`` |
    ``daily_cap_reached``) → the existing §9 gates (reference mode, Luna,
    binding, policy/model, SW=Y, ready bundle -- no overview for ``card-v1``).
    Same lineage (company·notice·bundle·profile·graph·policy) → a
    ``target_review_id`` preview and ``create_company_attempt`` (existing
    codes ``active_attempt_exists``/``bundle_not_ready``; a failed current
    attempt is superseded); otherwise a new review.  Rows carry
    ``actor_kind="system"``, ``claimed_name="system:transfer-policy"`` and
    ``request_id = uuid5(approval.id, input_sha256)``.  No model or network is
    called.  ``commit=False`` (default): the caller owns the transaction; any
    failure leaves nothing behind.  ``on_started(result)`` (결정 B55: the resume
    link) runs inside the same unit of work before it is released, so its
    failure removes the new preview/attempt too.
    """

    settings = settings or get_settings()
    company = session.get(Company, company_id)
    if company is None or not rl_path(settings, company):
        raise _error("not_found")
    policy_row = transfer_policy.selected_rl_policy_row(session, settings)
    try:
        approval = transfer_policy.require_transfer_approval(session, policy_row, now=now)
    except transfer_policy.TransferPolicyError as error:
        raise _error(error.code) from None
    work = _UnitOfWork(session, commit)
    try:
        if bundle_id is None:
            bundle_id = _latest_ready_bundle_id(session, notice_id)
        binding = session.get(CompanyKnowledgeBinding, company_id)
        existing = None
        if binding is not None and policy_row is not None:
            existing = session.scalar(select(DeepReview).where(
                DeepReview.company_id == company_id,
                DeepReview.notice_id == int(notice_id),
                DeepReview.bundle_id == bundle_id,
                DeepReview.profile_version_id == binding.profile_version_id,
                DeepReview.graph_version_id == binding.graph_version_id,
                DeepReview.policy_version_id == policy_row.id,
            ).order_by(DeepReview.created_at.desc(), DeepReview.id.desc()).limit(1))
        preview = preview_company_deep_review(
            service, session, company_id=company_id, notice_id=int(notice_id), bundle_id=bundle_id,
            review_id=existing.id if existing is not None else None, settings=settings, commit=False,
        )
        preview_id = UUID(preview["preview_id"])
        request_id = transfer_policy.auto_request_id(approval.id, preview["input_sha256"])
        common = {
            "preview_id": preview_id, "actor": transfer_policy.SYSTEM_ACTOR, "request_id": request_id,
            "settings": settings, "actor_kind": "system", "commit": False,
        }
        if existing is not None:
            response = create_company_attempt(
                service, session, company_id=company_id, review_id=existing.id, **common,
            )
            review_id, attempt_id = existing.id, UUID(str(response["id"]))
        else:
            response = create_company_review(
                service, session, company_id=company_id, notice_id=int(notice_id), bundle_id=bundle_id,
                **common,
            )
            review_id = UUID(str(response["id"]))
            attempt_id = UUID(str(response["current_attempt"]["id"]))
        result = RLVerdictStart(
            review_id=review_id, attempt_id=attempt_id, preview_id=preview_id, approval_id=approval.id,
            input_sha256=preview["input_sha256"], new_review=existing is None,
        )
        if on_started is not None:
            on_started(result)
        work.finish()
        return result
    except BaseException:
        work.abort()
        raise


# --- views and currentness ---------------------------------------------------------


def current_attempt_previews(
    session: Session, reviews: Sequence[DeepReview]
) -> dict[UUID, DeepReviewPreview]:
    """review id → the approved preview of its ``current_attempt`` (one query)."""

    attempt_to_review = {
        review.current_attempt_id: review.id
        for review in reviews
        if review.company_id is not None and review.current_attempt_id is not None
    }
    if not attempt_to_review:
        return {}
    rows = session.execute(
        select(DeepReviewApproval.attempt_id, DeepReviewPreview)
        .join(DeepReviewPreview, DeepReviewPreview.id == DeepReviewApproval.preview_id)
        .where(DeepReviewApproval.attempt_id.in_(tuple(attempt_to_review)))
    ).all()
    return {attempt_to_review[attempt_id]: preview for attempt_id, preview in rows}


def company_review_current_flags(
    session: Session,
    reviews: Sequence[DeepReview],
    *,
    settings: Any = None,
) -> dict[UUID, bool]:
    """Contract §5 currentness of company reviews; batched (constant query count).

    Current means: the frozen input of the current attempt's approved preview
    is intact and bound to the review; the company's active binding still
    points at the review's graph/profile; the configured demo deep policy is
    the review's row with the same hash/model/generation; the bundle is still
    ``ready`` and every frozen document is still current; the notice's current
    completed v7 overview is the frozen run with the same result hash; and the
    notice is still SW사업대상=Y.  Old rows are never changed: a stale review
    simply reads ``False``.
    """

    settings = settings or get_settings()
    rows = [review for review in reviews if review.company_id is not None]
    if not rows:
        return {}
    companies = {
        company.id: company
        for company in session.scalars(select(Company).where(Company.id.in_({review.company_id for review in rows})))
    }
    policies: dict[bool, CompanyDeepPolicy | None] = {}
    for rl in {rl_path(settings, companies.get(review.company_id)) for review in rows}:
        try:
            policies[rl] = resolve_company_deep_policy(session, settings, rl=rl)
        except DeepReviewServiceError:
            policies[rl] = None
    previews = current_attempt_previews(session, rows)
    notice_ids = sorted({review.notice_id for review in rows})
    # card-v1 reviews never read the overview (RL-03 "개요 의존 제거" 3).
    overviews = (
        current_company_overviews(session, notice_ids)
        if any(policy is not None and policy.pipeline_version != "card-v1" for policy in policies.values())
        else {}
    )
    sw = sw_business_notice_ids(session, notice_ids)
    bindings = {
        binding.company_id: binding
        for binding in session.scalars(select(CompanyKnowledgeBinding).where(
            CompanyKnowledgeBinding.company_id.in_({review.company_id for review in rows})
        ))
    }
    bundles = dict(session.execute(
        select(DocumentBundle.id, DocumentBundle.status).where(
            DocumentBundle.id.in_({review.bundle_id for review in rows})
        )
    ).all())
    frozen_documents: set[UUID] = set()
    for preview in previews.values():
        provenance = preview.provenance_jsonb if isinstance(preview.provenance_jsonb, Mapping) else {}
        for document in provenance.get("documents", []) or []:
            try:
                frozen_documents.add(UUID(str(document["document_version_id"])))
            except (KeyError, TypeError, ValueError):
                continue
    current_documents = set(session.scalars(select(DocumentVersion.id).where(
        DocumentVersion.id.in_(frozen_documents), DocumentVersion.is_current.is_(True),
    ))) if frozen_documents else set()
    out: dict[UUID, bool] = {}
    for review in rows:
        preview = previews.get(review.id)
        policy = policies.get(rl_path(settings, companies.get(review.company_id)))
        out[review.id] = bool(
            preview is not None
            and policy is not None
            and _review_current(review, preview, policy, bindings.get(review.company_id),
                                overviews.get(review.notice_id), review.notice_id in sw,
                                bundles.get(review.bundle_id), current_documents)
        )
    return out


def _review_current(
    review: DeepReview,
    preview: DeepReviewPreview,
    policy: CompanyDeepPolicy,
    binding: CompanyKnowledgeBinding | None,
    overview: Any,
    sw: bool,
    bundle_status: str | None,
    current_documents: set[UUID],
) -> bool:
    frozen = preview.input_snapshot if isinstance(preview.input_snapshot, Mapping) else {}
    provenance = preview.provenance_jsonb if isinstance(preview.provenance_jsonb, Mapping) else {}
    documents = provenance.get("documents") if isinstance(provenance.get("documents"), list) else []
    card = policy.pipeline_version == "card-v1"
    try:
        document_ids = {UUID(str(row["document_version_id"])) for row in documents}
        overview_hash = overview_digest(overview[1]) if overview is not None and not card else None
    except (KeyError, TypeError, ValueError):
        return False
    if card:
        # RL-03 "개요 의존 제거" 3: instead of comparing an overview, the frozen
        # card-v1 input must carry no overview at all (both null).
        overview_ok = (
            frozen.get("schema_version") == "bidops.company-analysis-input.v2"
            and "overview_run_id" in frozen and frozen.get("overview_run_id") is None
            and "overview_sha256" in frozen and frozen.get("overview_sha256") is None
            and provenance.get("overview_run_id") is None and provenance.get("overview_sha256") is None
        )
    else:
        overview_ok = bool(
            overview is not None
            and str(overview[0].id) == frozen.get("overview_run_id")
            and overview_hash == frozen.get("overview_sha256")
        )
    return bool(
        _safe_hash(frozen) == preview.input_sha256 == provenance.get("input_sha256")
        and preview.company_id == review.company_id
        and preview.graph_version_id == review.graph_version_id
        and preview.profile_version_id == review.profile_version_id
        and preview.policy_version_id == review.policy_version_id
        and preview.bundle_id == review.bundle_id
        and binding is not None
        and binding.graph_version_id == review.graph_version_id
        and binding.profile_version_id == review.profile_version_id
        and policy.row.id == review.policy_version_id
        and policy.row.policy_sha256 == frozen.get("policy_sha256")
        and policy.row.model_name == frozen.get("model_name")
        and policy.model_revision == frozen.get("model_revision")
        and policy.generation_config_sha256 == frozen.get("generation_config_sha256")
        and bundle_status == "ready"
        and document_ids
        and document_ids <= current_documents
        and sw
        and overview_ok
    )


def is_company_review_current(session: Session, review: DeepReview, *, settings: Any = None) -> bool:
    return company_review_current_flags(session, [review], settings=settings).get(review.id, False)


def company_review_view(
    service: DeepReviewService,
    session: Session,
    review: DeepReview,
    *,
    settings: Any = None,
    is_current: bool | None = None,
) -> dict[str, Any]:
    """CompanyReviewView of one company review (contract §6, §10).

    Identity fields come from the immutable review/graph/ontology rows and the
    approved preview columns; ``provenance`` is the preview's stored snapshot.
    Any disagreement between them is ``processing_failed`` — never repaired.
    """

    if review.company_id is None or review.graph_version_id is None:
        raise _error("not_found")
    preview = current_attempt_previews(session, [review]).get(review.id)
    graph = session.get(CompanyKnowledgeVersion, review.graph_version_id)
    ontology = session.get(KnowledgeOntologyVersion, graph.ontology_id) if graph is not None else None
    if preview is None or graph is None or ontology is None:
        raise _error("processing_failed")
    provenance = preview.provenance_jsonb if isinstance(preview.provenance_jsonb, Mapping) else None
    if (
        provenance is None
        or preview.company_id != review.company_id
        or preview.graph_version_id != review.graph_version_id
        or preview.profile_version_id != review.profile_version_id
        or preview.policy_version_id != review.policy_version_id
        or provenance.get("policy_version_id") != str(review.policy_version_id)
        or provenance.get("ontology_sha256") != ontology.sha256
    ):
        raise _error("processing_failed")
    if is_current is None:
        is_current = is_company_review_current(session, review, settings=settings)
    try:
        view = CompanyReviewView.model_validate({
            **service.view(session, review.id),
            "company_id": str(review.company_id),
            "profile_version_id": str(review.profile_version_id),
            "graph_version_id": str(review.graph_version_id),
            "graph_sha256": graph.graph_sha256,
            "ontology_version": ontology.version,
            "input_sha256": preview.input_sha256,
            "is_current": bool(is_current),
            "provenance": deepcopy(dict(provenance)),
        })
    except ValidationError:
        raise _error("processing_failed") from None
    return view.model_dump(mode="json")


__all__ = [
    "ERROR_MESSAGES",
    "ERROR_STATUS",
    "CompanyDeepPolicy",
    "PreparedCompanyDeepReview",
    "RLVerdictStart",
    "card_analysis_for_bundle",
    "company_review_current_flags",
    "company_review_view",
    "company_source_units",
    "create_company_attempt",
    "create_company_review",
    "current_attempt_previews",
    "is_company_review_current",
    "prepare_company_deep_review",
    "preview_company_deep_review",
    "recheck_company_preview",
    "resolve_company_deep_policy",
    "rl_path",
    "start_rl_verdict",
]
