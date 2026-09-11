"""사전규격 개요 검토 REST (`bidops.prespec-overview.v1`).

경로 접두사는 lifecycle의 `/api/pre-specs`이지만 제공 모듈은 deep_review다
(명세 §5.3). 세 endpoint뿐이며 모델 원문·원응답 참조·object key·filesystem
경로는 어느 응답에도 담지 않는다.

**여기서 ORM을 직접 다루지 않는다** (§4의 router 경계). 조회·확정·PDF 읽기는
모두 `services/overview_runs`의 함수가 하고, 이 파일은 요청을 옮기고 안정
오류 코드를 HTTP 상태로 바꾸는 일만 한다.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path as ApiPath
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.db import get_db
from ..services.overview_runs import (
    OverviewRequestError,
    confirm_range,
    overview_envelope,
    run_snapshot_pdf,
)

router = APIRouter(prefix="/api/pre-specs", tags=["pre-specs"])

_STATUSES = {
    "invalid_request": 400,
    "actor_name_required": 400,
    "actor_name_invalid": 400,
    "not_found": 404,
    "run_active": 409,
    "document_not_current_safe": 409,
    "range_invalid": 422,
    "pdf_unavailable": 503,
    "processing_failed": 503,
}
_MESSAGES = {
    "invalid_request": "요청을 처리할 수 없습니다",
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "not_found": "대상을 찾을 수 없습니다",
    "run_active": "이미 실행 중인 개요 run이 있습니다",
    "document_not_current_safe": "현재 안전한 제안요청서 문서를 확인할 수 없습니다",
    "range_invalid": "쪽 범위가 올바르지 않습니다",
    "pdf_unavailable": "고정 스냅샷 PDF를 읽을 수 없습니다",
    "processing_failed": "개요 검토를 처리할 수 없습니다",
}


def _error(code: str) -> JSONResponse:
    safe = code if code in _STATUSES else "processing_failed"
    return JSONResponse(
        status_code=_STATUSES[safe],
        content={"error": {"code": safe, "message": _MESSAGES[safe], "details": None}, "request_id": None},
    )


class RangeConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


@router.get("/{notice_id}/overview")
def get_overview(notice_id: int = ApiPath(..., ge=1), session: Session = Depends(get_db)) -> Any:
    try:
        return overview_envelope(session, notice_id)
    except Exception:
        session.rollback()
        return _error("processing_failed")


@router.post("/{notice_id}/overview/range-confirmations", status_code=201)
def create_range_confirmation(
    payload: RangeConfirmationRequest,
    notice_id: int = ApiPath(..., ge=1),
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> Any:
    """사람이 확정한 쪽 범위로 개요 run 하나를 넣는다."""

    try:
        actor_name = validate_actor(actor, actor_format)
    except BundleServiceError as error:
        return _error(error.code)
    try:
        run = confirm_range(
            session, notice_id,
            page_start=payload.page_start, page_end=payload.page_end,
            actor_name=actor_name, note=payload.note,
        )
        session.commit()
    except OverviewRequestError as error:
        session.rollback()
        return _error(error.code)
    except Exception:
        session.rollback()
        return _error("processing_failed")
    return {"run_id": str(run.id), "attempt_enqueued": True}


@router.get("/{notice_id}/overview/runs/{run_id}/pdf")
def get_overview_pdf(
    notice_id: int = ApiPath(..., ge=1),
    run_id: UUID = ApiPath(...),
    session: Session = Depends(get_db),
) -> Any:
    """이 run이 실제로 읽은 고정 스냅샷 PDF를 그대로 흘려 보낸다."""

    try:
        data = run_snapshot_pdf(session, notice_id, run_id)
    except OverviewRequestError as error:
        return _error(error.code)
    except Exception:
        session.rollback()
        return _error("processing_failed")
    return Response(content=data, media_type="application/pdf")


__all__ = ["RangeConfirmationRequest", "router"]
