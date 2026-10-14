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
from . import luna_inputs
from .company_analysis_input import (
    CompanyAnalysisError,
    build_company_analysis_input,
    document_provenance,
    frozen_provenance,
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
from .luna_identity import COMPANY_POLICY_IDENTITIES, PROVIDER, matches_runtime, policy_reasoning_effort


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
}
ERROR_MESSAGES: dict[str, str] = {
    "invalid_request": "요청을 처리할 수 없습니다",
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "effective_grade_ineligible": "SW사업대상 사전규격만 심층 분석할 수 있습니다",
    "not_found": "대상을 찾을 수 없습니다",
    "company_profile_not_ready": "회사 프로필이 아직 준비되지 않았습니다",
    "company_input_invalid": "회사 분석 입력을 만들 수 없습니다",
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
}


def _error(code: str, *, request_id: UUID | None = None) -> DeepReviewServiceError:
    if code not in ERROR_STATUS:
        code = "processing_failed"
    return DeepReviewServiceError(code, ERROR_MESSAGES[code], status_code=ERROR_STATUS[code], request_id=request_id)


# --- configuration and policy ------------------------------------------------------


def _gate_company(session: Session, company_id: UUID, settings: Any) -> Company:
    """§9 order: demo off / unknown company → 404, then reference mode, then Luna."""

    if not getattr(settings, "demo_enabled", False):
        raise _error("not_found")
    company = session.get(Company, company_id)
    if company is None:
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


def resolve_company_deep_policy(session: Session, settings: Any = None) -> CompanyDeepPolicy:
    """Explicit demo policy row only; there is no global active-policy fallback.

    ``analysis_policy_unavailable``: setting unset, row missing, row not the
    approved policy bytes, not an identity in ``COMPANY_POLICY_IDENTITIES``
    (contract §9; global Luna rows carry no company/graph input description),
    or an unusable payload -- including a missing or non-positive
    ``chunking.path_limit_per_requirement`` (no default).
    ``model_binding_invalid``: not a Luna ``codex-exec`` binding, or the mock
    provider is configured.
    """

    settings = settings or get_settings()
    policy_id = getattr(settings, "demo_deep_review_policy_version_id", None)
    row = session.get(AnalysisPolicyVersion, policy_id) if policy_id else None
    if row is None:
        raise _error("analysis_policy_unavailable")
    payload = _policy_payload(row)
    generation = payload.get("generation")
    if settings.analysis_provider == "mock" or not luna_inputs.is_luna(row):
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
    if (
        payload.get("pipeline_version") != "narrative-v2"
        or payload.get("policy_identity") not in COMPANY_POLICY_IDENTITIES
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
    return CompanyDeepPolicy(
        row=row, payload=payload, generation=dict(generation),
        generation_config_sha256=canonical_json_hash(dict(generation)), model_revision=revision,
        source_characters=int(chunking["source_characters"]),
        profile_characters=int(chunking["profile_characters"]),
        path_limit_per_requirement=int(path_limit),
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

    Read-only; the caller has already passed ``_gate_company``.
    """

    settings = settings or get_settings()
    try:
        knowledge = resolve_company_knowledge_context(session, company_id)
    except CompanyAnalysisError as error:
        raise _error("not_found" if error.code == "company_not_found" else error.code) from None
    policy = resolve_company_deep_policy(session, settings)
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
) -> dict[str, Any]:
    """POST base/pre-specs/{notice_id}/deep-review-previews → CompanyDeepReviewPreviewDTO.

    ``review_id`` is only for a retry of the same company/notice/bundle review
    whose frozen lineage (profile/graph/policy) is still current; a new
    graph/profile is a new review (``version_conflict``).  Only the preview row
    is written; a failure writes nothing.
    """

    settings = settings or get_settings()
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
        session.commit()
        return response
    except DeepReviewServiceError:
        session.rollback()
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
    return {
        "notice_id": review.notice_id, "bundle_id": str(review.bundle_id),
        "profile_version_id": str(review.profile_version_id),
        "profile_sha256": prepared.input["profile_sha256"],
        "policy_version_id": str(policy.id), "policy_sha256": policy.policy_sha256,
        "policy_model_name": policy.model_name,
        "analysis_provider": PROVIDER, "runtime_model": str(policy.model_name),
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
) -> dict[str, Any]:
    """POST base/pre-specs/{notice_id}/deep-reviews → 202 CompanyReviewView.

    The exact request_id replay returns the first response before any state
    check.  ``review_exists`` leaves the preview unconsumed.  Review, first
    attempt (+WorkJob), approval, idempotency record and audit are one
    transaction.
    """

    settings = settings or get_settings()
    claimed_name = _validate_actor(actor)
    request_hash = _idempotency_hash(CREATE_OPERATION, {
        "company_id": str(company_id), "notice_id": int(notice_id), "bundle_id": str(bundle_id),
        "preview_id": str(preview_id) if preview_id else None,
    })
    aggregate_id = f"{company_id}:{int(notice_id)}"
    replay = {
        "operation": CREATE_OPERATION, "aggregate_type": "company_notice", "aggregate_id": aggregate_id,
        "actor": claimed_name, "request_id": request_id, "request_hash": request_hash,
    }
    try:
        if source_verification_enabled is not True:
            raise _error("invalid_request", request_id=request_id)
        _gate_company(session, company_id, settings)
        if lock_notice(session, int(notice_id)) is None:
            raise _error("not_found", request_id=request_id)
        duplicate = service._idempotent_response(session, **replay)
        if duplicate is not None:
            session.commit()
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
        attempt = service._seed_attempt(session, review, sequence=1, actor=claimed_name, source_verification_enabled=True)
        luna_inputs.approve(session, row, attempt.id, claimed_name, request_id)
        session.add(AuditEvent(
            actor_kind="human", claimed_name=claimed_name, action=CREATION_ACTION_BY_ACTOR_KIND["human"],
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
        session.commit()
        return response
    except DeepReviewServiceError:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        duplicate = service._idempotent_response(session, **replay)
        if duplicate is not None:
            return dict(duplicate)
        raise _conflict_after_race(session, preview_id, request_id) from exc


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
) -> dict[str, Any]:
    """POST base/deep-reviews/{review_id}/attempts → 202 AttemptView.

    Only a preview frozen with ``target_review_id`` = this review is accepted;
    its lineage must still be the review's (otherwise a new review is needed).
    """

    settings = settings or get_settings()
    claimed_name = _validate_actor(actor)
    request_hash = _idempotency_hash(ATTEMPT_OPERATION, {
        "company_id": str(company_id), "review_id": str(review_id),
        "preview_id": str(preview_id) if preview_id else None,
    })
    replay = {
        "operation": ATTEMPT_OPERATION, "aggregate_type": "deep_review", "aggregate_id": str(review_id),
        "actor": claimed_name, "request_id": request_id, "request_hash": request_hash,
    }
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
            session.commit()
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
        )
        luna_inputs.approve(session, row, attempt.id, claimed_name, request_id)
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
            actor_kind="human", claimed_name=claimed_name, action="deep_review.attempt",
            aggregate_type="deep_review", aggregate_id=str(review.id), request_id=str(request_id),
            safe_metadata={
                "attempt_id": str(attempt.id), "sequence": attempt.sequence,
                "company_id": str(company_id), "preview_id": str(row.id), "input_sha256": row.input_sha256,
                **({"correlation_id": str(correlation_id)} if correlation_id is not None else {}),
            },
        ))
        session.commit()
        return response
    except DeepReviewServiceError:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        duplicate = service._idempotent_response(session, **replay)
        if duplicate is not None:
            return dict(duplicate)
        if preview_id is not None and _preview_used(session, preview_id):
            raise _error("preview_used", request_id=request_id) from exc
        raise _error("active_attempt_exists", request_id=request_id) from exc


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
    try:
        policy = resolve_company_deep_policy(session, settings)
    except DeepReviewServiceError:
        return {review.id: False for review in rows}
    previews = current_attempt_previews(session, rows)
    notice_ids = sorted({review.notice_id for review in rows})
    overviews = current_company_overviews(session, notice_ids)
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
        out[review.id] = bool(
            preview is not None
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
    try:
        document_ids = {UUID(str(row["document_version_id"])) for row in documents}
        overview_hash = overview_digest(overview[1]) if overview is not None else None
    except (KeyError, TypeError, ValueError):
        return False
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
        and overview is not None
        and str(overview[0].id) == frozen.get("overview_run_id")
        and overview_hash == frozen.get("overview_sha256")
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
]
