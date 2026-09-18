"""C-2 policy 조회·후보 지정·활성화 endpoint (contracts "policy REST")."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...core.db import get_db
from ..schemas.order_plan_policies import (
    PolicyActivateRequest,
    PolicyActivateResponse,
    PolicyCandidateRequest,
    PolicyCandidateResponse,
    PolicyInspectResponse,
    PolicyListResponse,
)
from ..services.order_plan_policy import OrderPlanPolicyService
from ..services.order_plan_screening import OrderPlanScreeningError


router = APIRouter(prefix="/api/order-plan-screening", tags=["order-plan-screening"])
service = OrderPlanPolicyService()

MESSAGES = {
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "invalid_request": "요청 형식이 올바르지 않습니다",
    "not_found": "C-2 대상을 찾을 수 없습니다",
    "idempotency_conflict": "같은 request_id가 다른 요청에 사용되었습니다",
    "immutable_conflict": "C-2 policy digest 또는 상태가 요청과 다릅니다",
    "activation_blocked": "C-2 policy 활성화 조건을 충족하지 않습니다",
    "processing_failed": "C-2 요청을 완료할 수 없습니다",
}


def error_response(error: OrderPlanScreeningError, messages: dict[str, str] = MESSAGES) -> JSONResponse:
    """C-2 envelope. ``details``는 오류가 실어 온 경우(`activation_blocked`·`daily_trigger_off`)만 채운다."""

    code = error.code if error.code in messages else "processing_failed"
    status = error.status_code if code == error.code else 500
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": messages[code], "details": getattr(error, "details", None)},
            "request_id": str(error.request_id) if error.request_id is not None else None,
        },
    )


def unexpected(session: Session, request_id: UUID | None = None) -> JSONResponse:
    session.rollback()
    return JSONResponse(
        status_code=500,
        content={
            "error": {"code": "processing_failed", "message": MESSAGES["processing_failed"], "details": None},
            "request_id": str(request_id) if request_id is not None else None,
        },
    )


@router.get("/policies", response_model=PolicyListResponse)
def list_policies(session: Session = Depends(get_db)) -> dict[str, object] | JSONResponse:
    try:
        return service.list_policies(session)
    except OrderPlanScreeningError as error:
        session.rollback()
        return error_response(error)
    except Exception:
        return unexpected(session)


@router.post("/policies/candidate", response_model=PolicyCandidateResponse, status_code=201)
def set_candidate(
    payload: PolicyCandidateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.set_candidate(session, payload, actor, actor_format)
    except OrderPlanScreeningError as error:
        session.rollback()
        return error_response(error)
    except Exception:
        return unexpected(session, payload.request_id)


@router.get("/policies/{policy_version}", response_model=PolicyInspectResponse)
def inspect_policy(policy_version: str, session: Session = Depends(get_db)) -> dict[str, object] | JSONResponse:
    try:
        return service.inspect_policy(session, policy_version)
    except OrderPlanScreeningError as error:
        session.rollback()
        return error_response(error)
    except Exception:
        return unexpected(session)


@router.post("/policies/{policy_version}/activate", response_model=PolicyActivateResponse, status_code=200)
def activate_policy(
    policy_version: str,
    payload: PolicyActivateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.activate(session, policy_version, payload, actor, actor_format)
    except OrderPlanScreeningError as error:
        session.rollback()
        return error_response(error)
    except Exception:
        return unexpected(session, payload.request_id)
