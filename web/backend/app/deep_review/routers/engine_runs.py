"""Versioned extracted-engine API. No source payload or transport settings accepted."""

from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ...core.db import get_db
from ...core.api_errors import validate_actor, BundleServiceError
from ..schemas.engine_runs import EngineRunCreate, EngineRunView, EngineRunList
from ..services import engine_runs as service

router = APIRouter(tags=["engine-runs"])


def _call(session, fn):
    try:
        return fn()
    except (service.EngineRunError, BundleServiceError) as e:
        session.rollback()
        return JSONResponse(
            status_code=getattr(e, "status", getattr(e, "status_code", 409)),
            content={
                "error": {
                    "code": e.code,
                    "message": "분석 실행 조건을 확인해 주세요",
                    "details": None,
                }
            },
        )
    except Exception:
        session.rollback()
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "engine_unavailable",
                    "message": "분석 실행을 처리할 수 없습니다",
                    "details": None,
                }
            },
        )


@router.post(
    "/api/companies/{company_id}/notices/{notice_id}/engine-runs",
    response_model=EngineRunView,
    status_code=202,
)
def create(
    company_id: UUID,
    notice_id: int,
    payload: EngineRunCreate,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[
        str | None, Header(alias="X-BidOps-Actor-Name-Format")
    ] = None,
    session: Session = Depends(get_db),
):
    return _call(
        session,
        lambda: service.create(
            session,
            company_id=company_id,
            notice_id=notice_id,
            payload=payload,
            actor=validate_actor(actor, actor_format),
        ),
    )


@router.get(
    "/api/companies/{company_id}/notices/{notice_id}/engine-runs",
    response_model=EngineRunList,
)
def list_runs(
    company_id: UUID,
    notice_id: int,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
):
    return _call(
        session,
        lambda: service.list_runs(
            session, company_id, notice_id, limit=limit, offset=offset
        ),
    )


@router.get("/api/engine-runs/{run_id}", response_model=EngineRunView)
def get_run(run_id: UUID, session: Session = Depends(get_db)):
    return _call(session, lambda: service.get_run(session, run_id))
