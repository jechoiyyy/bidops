"""Approved deep-review endpoints #8-10; registration is owned by the deep_review module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path as ApiPath
from fastapi.responses import JSONResponse
from pydantic import StrictBool, BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents import (
    AgentAction,
    AgentActorKind,
    AgentActorRef,
    AgentAggregateRef,
    AgentAggregateType,
    AgentArtifactRef,
    AgentArtifactType,
    DeepReviewAgent,
    RetryAttemptCommand,
    RetryAttemptPayload,
    StartReviewCommand,
    StartReviewPayload,
    attempt_artifact_ref,
    bundle_artifact_ref,
)
from ...core.db import get_db
from ..models import (
    DeepReview,
    DeepReviewAttempt,
    DeepReviewStage,
    DocumentBundle,
    DocumentBundleItem,
)
from ..schemas.company_fit import CompanyFitResponse
from ..schemas.deep_reviews import DeepReviewPreviewView, AttemptView, DeepReviewView, OpportunityDeepReviewsResponse
from ..services.company_fit import company_fit_view
from ..services.deep_reviews import DeepReviewService, DeepReviewServiceError
from ..services.document_bundles import BundleServiceError, PageOverviewError, validate_actor
from ..services.input_versions import InputVersionError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeepReviewCreateRequest(_Strict):
    preview_id: UUID | None = None
    source_verification_enabled: StrictBool = True
    request_id: UUID
    bundle_id: UUID


class DeepReviewAttemptRequest(_Strict):
    preview_id: UUID | None = None
    source_verification_enabled: StrictBool = True
    request_id: UUID


router = APIRouter(prefix="/api", tags=["deep-reviews"])
service = DeepReviewService()


def _actor_ref(actor: str | None, actor_format: str | None = None) -> AgentActorRef:
    """Build the strict human actor after preserving the legacy validation."""

    try:
        claimed_name = validate_actor(actor, actor_format)
        return AgentActorRef(actor_kind=AgentActorKind.human, claimed_name=claimed_name)
    except BundleServiceError as error:
        raise DeepReviewServiceError(error.code, error.message, status_code=error.status_code) from error
    except ValidationError as error:
        raise DeepReviewServiceError("actor_name_invalid", "담당자 이름이 올바르지 않습니다", status_code=400) from error


def _bundle_ref(session: Session, bundle_id: UUID, *, notice_id: int) -> AgentArtifactRef:
    bundle = session.get(DocumentBundle, bundle_id)
    if bundle is None:
        raise InputVersionError("not_found", "document bundle을 찾을 수 없습니다")
    if bundle.notice_id != notice_id:
        raise DeepReviewServiceError("not_found", "공고와 document bundle이 일치하지 않습니다", status_code=404)
    if bundle.status != "ready":
        raise InputVersionError("bundle_not_ready", "ready document bundle이 필요합니다")
    items = session.scalars(
        select(DocumentBundleItem)
        .where(DocumentBundleItem.bundle_id == bundle.id)
        .order_by(DocumentBundleItem.ordinal.asc(), DocumentBundleItem.document_version_id.asc())
    ).all()
    return bundle_artifact_ref(bundle, items)


def _attempt_ref(session: Session, review_id: UUID) -> AgentArtifactRef:
    review = session.get(DeepReview, review_id)
    if review is None:
        raise DeepReviewServiceError("not_found", "deep review를 찾을 수 없습니다", status_code=404)
    attempt_id = review.current_attempt_id
    if attempt_id is None:
        # The adapter performs the authoritative readiness check.  This
        # placeholder only lets the strict retry command reach that check.
        return AgentArtifactRef(
            artifact_type=AgentArtifactType.deep_review_attempt,
            artifact_id=str(review_id),
            version=1,
        )
    attempt = session.get(DeepReviewAttempt, attempt_id)
    if attempt is None:
        return AgentArtifactRef(
            artifact_type=AgentArtifactType.deep_review_attempt,
            artifact_id=str(attempt_id),
            version=1,
        )
    stages = session.scalars(
        select(DeepReviewStage)
        .where(DeepReviewStage.attempt_id == attempt.id)
        .order_by(DeepReviewStage.sequence.asc(), DeepReviewStage.id.asc())
    ).all()
    return attempt_artifact_ref(attempt, stages)


def _error_response(error: DeepReviewServiceError | InputVersionError, *, request_id: UUID | None = None) -> JSONResponse:
    allowed = {
        "invalid_request", "actor_name_required", "actor_name_invalid", "not_found", "effective_grade_ineligible",
        "bundle_not_ready", "idempotency_conflict", "active_attempt_exists", "service_unavailable", "review_not_ready",
        "processing_failed", "preview_required", "preview_changed", "preview_used", "review_exists",
    }
    code = error.code if getattr(error, "code", None) in allowed else "processing_failed"
    messages = {
        "invalid_request": "요청을 처리할 수 없습니다", "actor_name_required": "담당자 이름이 필요합니다",
        "actor_name_invalid": "담당자 이름이 올바르지 않습니다", "not_found": "대상을 찾을 수 없습니다",
        "effective_grade_ineligible": "심층 검토 대상 등급이 아닙니다", "bundle_not_ready": "ready document bundle이 필요합니다",
        "idempotency_conflict": "같은 request_id가 다른 요청에 사용되었습니다", "active_attempt_exists": "이미 실행 중인 attempt가 있습니다",
        "service_unavailable": "심층 검토 서비스를 사용할 수 없습니다", "review_not_ready": "심층 검토가 아직 준비되지 않았습니다",
        "processing_failed": "심층 검토를 완료할 수 없습니다",
    }
    default_status = {
        "not_found": 404, "effective_grade_ineligible": 403, "bundle_not_ready": 409,
        "idempotency_conflict": 409, "active_attempt_exists": 409, "service_unavailable": 503,
        "processing_failed": 500,
    }.get(code, 400)
    return JSONResponse(status_code=getattr(error, "status_code", None) if getattr(error, "status_code", None) is not None and isinstance(error, DeepReviewServiceError) else default_status, content={"error": {"code": code, "message": messages.get(code, "전송 미리보기를 다시 확인하십시오"), "details": None}, "request_id": str(request_id or getattr(error, "request_id", None)) if (request_id or getattr(error, "request_id", None)) else None})


@router.get("/opportunities/{opportunity_id}/deep-reviews", response_model=OpportunityDeepReviewsResponse)
def get_opportunity_deep_reviews(opportunity_id: int, session: Session = Depends(get_db)) -> dict[str, object] | JSONResponse:
    try:
        return service.opportunity_reviews(session, opportunity_id)
    except (DeepReviewServiceError, InputVersionError) as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        session.rollback()
        return _error_response(DeepReviewServiceError("processing_failed", "심층 검토를 조회할 수 없습니다", status_code=500))


@router.post("/notices/{notice_id}/deep-reviews", response_model=DeepReviewView, status_code=202)
def create_deep_review(
    notice_id: int,
    payload: DeepReviewCreateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        command = StartReviewCommand(
            schema="bidops.agent-command.v1",
            agent_name="deep_review",
            action=AgentAction.start_review,
            aggregate=AgentAggregateRef(
                aggregate_type=AgentAggregateType.notice,
                aggregate_id=str(notice_id),
            ),
            actor=_actor_ref(actor, actor_format),
            request_id=payload.request_id,
            correlation_id=None,
            expected_version=None,
            input_refs=[_bundle_ref(session, payload.bundle_id, notice_id=notice_id)],
            payload=StartReviewPayload(bundle_id=payload.bundle_id, source_verification_enabled=payload.source_verification_enabled, preview_id=payload.preview_id),
        )
        return DeepReviewAgent(service).start(session, command).result
    except (DeepReviewServiceError, InputVersionError) as error:
        return _error_response(error, request_id=payload.request_id)
    except Exception:
        session.rollback()
        return _error_response(DeepReviewServiceError("processing_failed", "processing failed", status_code=500), request_id=payload.request_id)


@router.get("/deep-reviews/{deep_review_id}", response_model=DeepReviewView)
def get_deep_review(deep_review_id: UUID, session: Session = Depends(get_db)) -> dict[str, object] | JSONResponse:
    try:
        return service.view(session, deep_review_id)
    except (DeepReviewServiceError, InputVersionError) as error:
        return _error_response(error)
    except Exception:
        session.rollback()
        return _error_response(DeepReviewServiceError("processing_failed", "processing failed", status_code=500))


@router.post("/deep-reviews/{deep_review_id}/attempts", response_model=AttemptView, status_code=202)
def create_deep_review_attempt(
    deep_review_id: UUID,
    payload: DeepReviewAttemptRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        command = RetryAttemptCommand(
            schema="bidops.agent-command.v1",
            agent_name="deep_review",
            action=AgentAction.retry_attempt,
            aggregate=AgentAggregateRef(
                aggregate_type=AgentAggregateType.deep_review,
                aggregate_id=str(deep_review_id),
            ),
            actor=_actor_ref(actor, actor_format),
            request_id=payload.request_id,
            correlation_id=None,
            expected_version=None,
            input_refs=[_attempt_ref(session, deep_review_id)],
            payload=RetryAttemptPayload(source_verification_enabled=payload.source_verification_enabled, preview_id=payload.preview_id),
        )
        return DeepReviewAgent(service).retry_attempt(session, command).result
    except (DeepReviewServiceError, InputVersionError) as error:
        return _error_response(error, request_id=payload.request_id)
    except Exception:
        session.rollback()
        return _error_response(DeepReviewServiceError("processing_failed", "processing failed", status_code=500), request_id=payload.request_id)


# --- 사전규격 화면이 부르는 조회 (명세 §5.3: 경로는 pre_specs, 제공 모듈은 deep_review) ---
# 개요 검토 REST는 routers/overviews.py에 있다. 이 router에는 회사 핏 조회만 남는다.
pre_spec_overview_router = APIRouter(prefix="/api/pre-specs", tags=["pre-specs"])


@pre_spec_overview_router.get("/{notice_id}/company-fit", response_model=CompanyFitResponse)
def get_company_fit(notice_id: int = ApiPath(..., ge=1), session: Session = Depends(get_db)):
    try:
        return company_fit_view(session, notice_id)
    except LookupError:
        return _page_error(PageOverviewError("not_found"))
    except Exception:
        return _page_error(PageOverviewError("processing_failed"))



def _page_error(error: PageOverviewError) -> JSONResponse:
    code = str(error)
    statuses = {"not_found": 404, "result_integrity_failed": 409, "pdf_integrity_failed": 409,
                "overview_contract_upgrade_required": 409, "pdf_unavailable": 503, "processing_failed": 503}
    if code not in statuses:
        code = "processing_failed"
    return JSONResponse(status_code=statuses[code],
                        content={"error": {"code": code, "message": "개요 또는 PDF 근거를 확인할 수 없습니다", "details": None}, "request_id": None})


__all__ = [
    "DeepReviewAttemptRequest",
    "DeepReviewCreateRequest",
    "pre_spec_overview_router",
    "router",
    "service",
]


class DeepReviewPreviewRequest(_Strict):
    bundle_id: UUID
    review_id: UUID | None = None
    source_verification_enabled: StrictBool = True


@router.post("/notices/{notice_id}/deep-review-previews", response_model=DeepReviewPreviewView)
def create_deep_review_preview(notice_id: int, payload: DeepReviewPreviewRequest, session: Session = Depends(get_db)):
    from ..services.luna_inputs import preview
    try:
        return preview(service, session, notice_id, payload.bundle_id, payload.source_verification_enabled, payload.review_id)
    except (DeepReviewServiceError, InputVersionError) as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        session.rollback()
        return _error_response(DeepReviewServiceError("processing_failed", "입력을 확인할 수 없습니다", status_code=500))
