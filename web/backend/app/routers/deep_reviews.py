"""Approved deep-review endpoints #8-10; registration is T7-owned."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.deep_reviews import DeepReviewService, DeepReviewServiceError
from ..services.input_versions import InputVersionError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeepReviewCreateRequest(_Strict):
    request_id: UUID
    bundle_id: UUID


class DeepReviewAttemptRequest(_Strict):
    request_id: UUID


StageName = Literal["requirements_and_evaluation", "delivery_risk_economics", "synthesis_and_validation"]
StageStatus = Literal["queued", "running", "completed", "failed"]
AttemptStatus = Literal["queued", "running", "completed", "failed", "superseded"]
ReviewStatus = Literal["queued", "running", "completed", "failed"]


class StageView(_Strict):
    stage: StageName
    sequence: int = Field(ge=1)
    status: StageStatus
    started_at: datetime | None
    completed_at: datetime | None
    last_error_code: str | None


class AttemptView(_Strict):
    id: UUID
    sequence: int = Field(ge=1)
    status: AttemptStatus
    stages: list[StageView]
    started_at: datetime | None
    completed_at: datetime | None
    last_error_code: str | None


class DeepReviewView(_Strict):
    id: UUID
    notice_id: int
    bundle_id: UUID
    status: ReviewStatus
    current_attempt: AttemptView | None
    attempts: list[AttemptView]
    created_at: datetime
    completed_at: datetime | None


router = APIRouter(prefix="/api", tags=["deep-reviews"])
service = DeepReviewService()


def _error_response(error: DeepReviewServiceError | InputVersionError, *, request_id: UUID | None = None) -> JSONResponse:
    allowed = {
        "invalid_request", "actor_name_required", "actor_name_invalid", "not_found", "effective_grade_ineligible",
        "bundle_not_ready", "idempotency_conflict", "active_attempt_exists", "service_unavailable", "review_not_ready",
        "processing_failed",
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
    return JSONResponse(status_code=getattr(error, "status_code", None) if getattr(error, "status_code", None) is not None and isinstance(error, DeepReviewServiceError) else default_status, content={"error": {"code": code, "message": messages[code], "details": None}, "request_id": str(request_id or getattr(error, "request_id", None)) if (request_id or getattr(error, "request_id", None)) else None})


@router.post("/notices/{notice_id}/deep-reviews", response_model=DeepReviewView, status_code=202)
def create_deep_review(
    notice_id: int,
    payload: DeepReviewCreateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.create_review(session, notice_id, payload.bundle_id, actor, payload.request_id)
    except (DeepReviewServiceError, InputVersionError) as error:
        return _error_response(error, request_id=payload.request_id)
    except Exception:
        session.rollback()
        return _error_response(DeepReviewServiceError("processing_failed", "processing failed", status_code=500), request_id=payload.request_id)


@router.get("/deep-reviews/{deep_review_id}", response_model=DeepReviewView)
def get_deep_review(deep_review_id: UUID, session: Session = Depends(get_db)) -> dict[str, object] | JSONResponse:
    try:
        return service.view(session, deep_review_id)
    except DeepReviewServiceError as error:
        return _error_response(error)
    except Exception:
        session.rollback()
        return _error_response(DeepReviewServiceError("processing_failed", "processing failed", status_code=500))


@router.post("/deep-reviews/{deep_review_id}/attempts", response_model=AttemptView, status_code=202)
def create_deep_review_attempt(
    deep_review_id: UUID,
    payload: DeepReviewAttemptRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.create_attempt(session, deep_review_id, actor, payload.request_id)
    except DeepReviewServiceError as error:
        return _error_response(error, request_id=payload.request_id)
    except Exception:
        session.rollback()
        return _error_response(DeepReviewServiceError("processing_failed", "processing failed", status_code=500), request_id=payload.request_id)


__all__ = ["DeepReviewAttemptRequest", "DeepReviewCreateRequest", "DeepReviewView", "router", "service"]
