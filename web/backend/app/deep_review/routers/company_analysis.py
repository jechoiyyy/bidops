"""회사별 Luna 심층 검토 쓰기 REST (데모 계약 §6·§9).

경로 접두사는 lifecycle의 `/api/companies`이지만 제공 모듈은 deep_review다
(명세 §5.3, DEMO-02 `company_knowledge` router와 같은 방식). 세 POST뿐이다:
미리보기 생성, 승인으로 review 생성, 같은 review의 재시도. 조회 GET은 같은
접두사의 형제 router `routers/company_reads.py`에 있다. `BIDOPS_DEMO_ENABLED=false`이면 조립 계층의 demo
guard가 먼저 404를 내고, service도 같은 판정을 한 번 더 한다.

ORM은 다루지 않는다. 판정·저장은 `services/company_deep_review`가 하고, 이 파일은
본문 검증과 안정 오류 코드 → HTTP 상태 변환만 한다. 오류 message로 분기하지
않으며, 모르는 코드와 예기치 못한 예외는 내용 없이 processing_failed다.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path as ApiPath
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.db import get_db
from ..schemas.company_analysis import AttemptView, CompanyDeepReviewPreviewView, CompanyReviewView
from ..services.company_deep_review import (
    ERROR_MESSAGES,
    ERROR_STATUS,
    create_company_attempt,
    create_company_review,
    preview_company_deep_review,
)
from ..services.deep_reviews import DeepReviewService, DeepReviewServiceError
from ..services.input_versions import InputVersionError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanyDeepReviewPreviewRequest(_Strict):
    bundle_id: UUID
    source_verification_enabled: Literal[True] = True
    review_id: UUID | None = None


class CompanyDeepReviewCreateRequest(_Strict):
    preview_id: UUID
    source_verification_enabled: Literal[True] = True
    request_id: UUID
    bundle_id: UUID


class CompanyDeepReviewAttemptRequest(_Strict):
    preview_id: UUID
    source_verification_enabled: Literal[True] = True
    request_id: UUID


router = APIRouter(prefix="/api/companies", tags=["company-analysis"])
service = DeepReviewService()

#: 이 router가 내보낼 수 있는 안정 오류 코드 (계약 §9). 상태는 service 표가 정본이다.
ALLOWED_ERROR_CODES = frozenset(ERROR_STATUS)


def _error_response(code: str, *, request_id: UUID | None = None) -> JSONResponse:
    safe = code if code in ALLOWED_ERROR_CODES else "processing_failed"
    return JSONResponse(
        status_code=ERROR_STATUS[safe],
        content={
            "error": {"code": safe, "message": ERROR_MESSAGES[safe], "details": None},
            "request_id": str(request_id) if request_id else None,
        },
    )


def _actor(actor: str | None, actor_format: str | None) -> str:
    try:
        return validate_actor(actor, actor_format)
    except BundleServiceError as error:
        raise DeepReviewServiceError(error.code, error.message, status_code=error.status_code) from error


def _handle(session: Session, call, *, request_id: UUID | None = None, status_code: int = 200) -> JSONResponse:  # type: ignore[no-untyped-def]
    try:
        content = call()
    except (DeepReviewServiceError, InputVersionError) as error:
        session.rollback()
        return _error_response(error.code, request_id=request_id or getattr(error, "request_id", None))
    except Exception:  # noqa: BLE001 - safe API boundary; nothing about the input is logged
        session.rollback()
        return _error_response("processing_failed", request_id=request_id)
    return JSONResponse(status_code=status_code, content=content)


@router.post(
    "/{company_id}/pre-specs/{notice_id}/deep-review-previews",
    response_model=CompanyDeepReviewPreviewView,
)
def create_company_deep_review_preview(
    company_id: UUID,
    payload: CompanyDeepReviewPreviewRequest,
    notice_id: int = ApiPath(..., ge=1),
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _handle(session, lambda: preview_company_deep_review(
        service, session, company_id=company_id, notice_id=notice_id, bundle_id=payload.bundle_id,
        source_verification_enabled=payload.source_verification_enabled, review_id=payload.review_id,
    ))


@router.post(
    "/{company_id}/pre-specs/{notice_id}/deep-reviews",
    response_model=CompanyReviewView,
    status_code=202,
)
def create_company_deep_review(
    company_id: UUID,
    payload: CompanyDeepReviewCreateRequest,
    notice_id: int = ApiPath(..., ge=1),
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _handle(session, lambda: create_company_review(
        service, session, company_id=company_id, notice_id=notice_id, bundle_id=payload.bundle_id,
        preview_id=payload.preview_id, actor=_actor(actor, actor_format), request_id=payload.request_id,
        source_verification_enabled=payload.source_verification_enabled,
    ), request_id=payload.request_id, status_code=202)


@router.post(
    "/{company_id}/deep-reviews/{review_id}/attempts",
    response_model=AttemptView,
    status_code=202,
)
def create_company_deep_review_attempt(
    company_id: UUID,
    review_id: UUID,
    payload: CompanyDeepReviewAttemptRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _handle(session, lambda: create_company_attempt(
        service, session, company_id=company_id, review_id=review_id, preview_id=payload.preview_id,
        actor=_actor(actor, actor_format), request_id=payload.request_id,
        source_verification_enabled=payload.source_verification_enabled,
    ), request_id=payload.request_id, status_code=202)


__all__ = [
    "ALLOWED_ERROR_CODES",
    "CompanyDeepReviewAttemptRequest",
    "CompanyDeepReviewCreateRequest",
    "CompanyDeepReviewPreviewRequest",
    "router",
    "service",
]
