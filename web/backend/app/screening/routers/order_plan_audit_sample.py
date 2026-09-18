"""C-2 감사 표본 미리보기와 기록 endpoint (contracts "감사 표본 REST")."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...core.db import get_db
from ..schemas.order_plan_audit_sample import (
    AuditSampleDrawRequest,
    AuditSampleDrawResponse,
    AuditSamplePreviewResponse,
)
from ..services.order_plan_audit_sample import OrderPlanAuditSampleService
from ..services.order_plan_screening import OrderPlanScreeningError


router = APIRouter(prefix="/api", tags=["order-plan-screening"])
service = OrderPlanAuditSampleService()

_MESSAGES = {
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "invalid_request": "요청 형식이 올바르지 않습니다",
    "not_found": "C-2 대상을 찾을 수 없습니다",
    "execution_not_completed": "완료된 C-2 execution이 아닙니다",
    "idempotency_conflict": "같은 request_id가 다른 요청에 사용되었습니다",
    "immutable_conflict": "기록된 감사 표본과 다시 계산한 표본이 다릅니다",
    "processing_failed": "C-2 요청을 완료할 수 없습니다",
}


def _error_response(error: OrderPlanScreeningError) -> JSONResponse:
    code = error.code if error.code in _MESSAGES else "processing_failed"
    status = error.status_code if code == error.code else 500
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": _MESSAGES[code], "details": None},
            "request_id": str(error.request_id) if error.request_id is not None else None,
        },
    )


def _unexpected(session: Session, request_id: UUID | None = None) -> JSONResponse:
    session.rollback()
    return JSONResponse(
        status_code=500,
        content={
            "error": {"code": "processing_failed", "message": _MESSAGES["processing_failed"], "details": None},
            "request_id": str(request_id) if request_id is not None else None,
        },
    )


@router.get(
    "/order-plan-screening/executions/{execution_id}/audit-sample",
    response_model=AuditSamplePreviewResponse,
)
def preview_audit_sample(execution_id: UUID, session: Session = Depends(get_db)) -> dict[str, object] | JSONResponse:
    try:
        return service.preview(session, execution_id)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session)


@router.post(
    "/order-plan-screening/executions/{execution_id}/audit-sample",
    response_model=AuditSampleDrawResponse,
    status_code=201,
    responses={200: {"model": AuditSampleDrawResponse}},
)
def draw_audit_sample(
    execution_id: UUID,
    payload: AuditSampleDrawRequest,
    response: Response,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    trigger: Annotated[str | None, Header(alias="X-BidOps-Trigger")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        status, body = service.draw(session, execution_id, payload, actor, actor_format, trigger)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session, payload.request_id)
    response.status_code = status
    return body
