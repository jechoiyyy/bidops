"""Manual C-2 order-plan screening and review endpoints."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..schemas.order_plans import (
    ArtifactSummaryResponse,
    ExecutionCreateRequest,
    ExecutionCreateResponse,
    ExecutionDetailResponse,
    ExecutionListResponse,
    ExecutionStopRequest,
    ExecutionStopResponse,
    FeedbackCreateRequest,
    FeedbackCreateResponse,
    FeedbackListResponse,
    OrderPlanDetailResponse,
    OrderPlanListResponse,
    ScreeningHistoryResponse,
)
from ..services.order_plan_screening import OrderPlanScreeningError, OrderPlanScreeningService


router = APIRouter(prefix="/api", tags=["order-plan-screening"])
service = OrderPlanScreeningService()

_MESSAGES = {
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "invalid_request": "요청 형식이 올바르지 않습니다",
    "not_found": "C-2 대상을 찾을 수 없습니다",
    "source_run_incomplete": "source run이 C-2 실행 조건을 충족하지 않습니다",
    "policy_not_active": "C-2 policy가 활성 상태가 아닙니다",
    "binding_mismatch": "C-2 binding이 일치하지 않습니다",
    "service_unavailable": "승인된 private vLLM transport를 사용할 수 없습니다",
    "active_execution_exists": "다른 C-2 execution이 실행 중입니다",
    "idempotency_conflict": "같은 request_id가 다른 요청에 사용되었습니다",
    "immutable_conflict": "불변 C-2 artifact가 이미 존재합니다",
    "execution_not_stoppable": "현재 C-2 execution은 중지할 수 없습니다",
    "artifact_kind_invalid": "C-2 artifact kind이 올바르지 않습니다",
    "artifact_not_ready": "C-2 artifact가 아직 준비되지 않았습니다",
    "feedback_conflict": "feedback revision이 충돌했습니다",
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


@router.get("/order-plans", response_model=OrderPlanListResponse)
def list_order_plans(
    source_run_id: str | None = None,
    stage1_status: Literal["selected", "filtered_out", "failed", "rejected"] | None = None,
    stage2_status: Literal["not_attempted", "success", "failed", "rejected", "unknown"] | None = None,
    qwen_relevance: Literal["relevant", "not_relevant", "uncertain"] | None = None,
    human_relevance: Literal["relevant", "not_relevant", "uncertain"] | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.list_order_plans(
            session,
            source_run_id=source_run_id,
            stage1_status=stage1_status,
            stage2_status=stage2_status,
            qwen_relevance=qwen_relevance,
            human_relevance=human_relevance,
            q=q,
            limit=limit,
            offset=offset,
        )
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session)


@router.get("/order-plans/{order_plan_pk}", response_model=OrderPlanDetailResponse)
def get_order_plan(order_plan_pk: int, session: Session = Depends(get_db)) -> dict[str, object] | JSONResponse:
    try:
        return service.order_plan_detail(session, order_plan_pk)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session)


@router.get("/order-plans/{order_plan_pk}/screening-history", response_model=ScreeningHistoryResponse)
def get_order_plan_history(order_plan_pk: int, session: Session = Depends(get_db)) -> dict[str, object] | JSONResponse:
    try:
        return service.screening_history(session, order_plan_pk)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session)


@router.get("/order-plan-screening/executions", response_model=ExecutionListResponse)
def list_executions(
    source_run_id: str | None = None,
    status: Literal["대기", "실행 중", "중지 요청", "성공", "부분 성공", "실패", "중단됨"] | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.list_executions(session, source_run_id=source_run_id, status=status, limit=limit, offset=offset)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session)


@router.post("/order-plan-screening/executions", response_model=ExecutionCreateResponse, status_code=202)
def create_execution(
    payload: ExecutionCreateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.create_execution(session, payload, actor, actor_format)
    except OrderPlanScreeningError as error:
        return _error_response(error)
    except Exception:
        return _unexpected(session, payload.request_id)


@router.get("/order-plan-screening/executions/{execution_id}", response_model=ExecutionDetailResponse)
def get_execution(execution_id: UUID, session: Session = Depends(get_db)) -> dict[str, object] | JSONResponse:
    try:
        return service.execution_detail(session, execution_id)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session)


@router.post("/order-plan-screening/executions/{execution_id}/stop", response_model=ExecutionStopResponse, status_code=202)
def stop_execution(
    execution_id: UUID,
    payload: ExecutionStopRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.stop_execution(session, execution_id, payload, actor, actor_format)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session, payload.request_id)


@router.get("/order-plan-screening/executions/{execution_id}/artifacts/{kind}", response_model=ArtifactSummaryResponse)
def get_artifact(execution_id: UUID, kind: str, session: Session = Depends(get_db)) -> dict[str, object] | JSONResponse:
    try:
        return service.artifact_detail(session, execution_id, kind)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session)


@router.get("/order-plans/{order_plan_pk}/screening-feedback", response_model=FeedbackListResponse)
def list_feedback(
    order_plan_pk: int,
    execution_id: UUID | None = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.list_feedback(session, order_plan_pk, execution_id)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session)


@router.post("/order-plans/{order_plan_pk}/screening-feedback", response_model=FeedbackCreateResponse, status_code=201)
def create_feedback(
    order_plan_pk: int,
    payload: FeedbackCreateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.create_feedback(session, order_plan_pk, payload, actor, actor_format)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session, payload.request_id)
