"""C-2 일일 자동 실행 스위치 endpoint (contracts "일일 자동 실행 스위치 REST")."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...core.db import get_db
from ..schemas.order_plan_daily_trigger import (
    DailyTriggerSetRequest,
    DailyTriggerSetResponse,
    DailyTriggerStateResponse,
)
from ..services.order_plan_daily_trigger import OrderPlanDailyTriggerService
from ..services.order_plan_screening import OrderPlanScreeningError
from .order_plan_policies import error_response, unexpected


router = APIRouter(prefix="/api/order-plan-screening", tags=["order-plan-screening"])
service = OrderPlanDailyTriggerService()


@router.get("/daily-trigger", response_model=DailyTriggerStateResponse)
def get_daily_trigger(session: Session = Depends(get_db)) -> dict[str, object] | JSONResponse:
    try:
        return service.state(session)
    except OrderPlanScreeningError as error:
        session.rollback()
        return error_response(error)
    except Exception:
        return unexpected(session)


@router.post("/daily-trigger", response_model=DailyTriggerSetResponse, status_code=201)
def set_daily_trigger(
    payload: DailyTriggerSetRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.set_switch(session, payload, actor, actor_format)
    except OrderPlanScreeningError as error:
        session.rollback()
        return error_response(error)
    except Exception:
        return unexpected(session, payload.request_id)
