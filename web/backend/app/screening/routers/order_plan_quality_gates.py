"""C-2 quality gate record endpoints (docs/contracts.md "품질 게이트 REST").

C-1 공고 판정 게이트(`routers/quality_gates.py`, `/api/quality-gates`)와 경로·저장소가
다르다. 오류 envelope는 C-2 수동 REST와 같은 것을 쓴다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...core.db import get_db
from ..schemas.order_plan_quality_gates import (
    QualityEvaluationCreateRequest,
    QualityEvaluationCreateResponse,
    QualityGateCreateRequest,
    QualityGateCreateResponse,
    QualityGateListResponse,
)
from ..services.order_plan_quality_gate import OrderPlanQualityGateService
from ..services.order_plan_screening import OrderPlanScreeningError
from .order_plans import _error_response, _unexpected


router = APIRouter(prefix="/api/order-plan-screening/quality-gates", tags=["order-plan-screening"])
service = OrderPlanQualityGateService()


@router.post("", response_model=QualityGateCreateResponse, status_code=201)
def create_gate(
    payload: QualityGateCreateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.create_gate(session, payload, actor, actor_format)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session, payload.request_id)


@router.get("", response_model=QualityGateListResponse)
def list_gates(
    policy_version: str | None = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    # query가 없을 때도 FastAPI 기본 422가 아니라 C-2 envelope의 invalid_request로 답한다.
    try:
        return service.list_gates(session, policy_version)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session)


@router.post("/{gate_id}/evaluations", response_model=QualityEvaluationCreateResponse, status_code=201)
def create_evaluation(
    gate_id: str,
    payload: QualityEvaluationCreateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.create_evaluation(session, gate_id, payload, actor, actor_format)
    except OrderPlanScreeningError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session, payload.request_id)
