"""평일 브리핑 REST `bidops.briefing.v1` (RL-01 spec "REST").

router는 parsing·HTTP 대응만 한다. 조회 projection·반응 상태 전이·멱등 fence는
`services/briefing.py`, Slack 미리보기 payload는 `services/briefing_slack.py`가 한다.
오류 code는 lifecycle 관례대로 이 파일의 로컬 map에만 등록한다(core `api_errors`는
바꾸지 않는다).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.db import get_db
from ..schemas.briefings import (
    BriefingItemView,
    BriefingReactionRequest,
    BriefingSlackPreview,
    BriefingView,
)
from ..services import briefing as briefing_service
from ..services.briefing_slack import briefing_slack_preview

router = APIRouter(prefix="/api/briefings", tags=["briefings"])

_ERRORS: dict[str, tuple[int, str]] = {
    "invalid_request": (422, "요청이 올바르지 않습니다"),
    "actor_name_required": (400, "담당자 이름이 필요합니다"),
    "actor_name_invalid": (400, "담당자 이름이 올바르지 않습니다"),
    "briefing_not_found": (404, "브리핑을 찾을 수 없습니다"),
    "briefing_item_not_found": (404, "브리핑 항목을 찾을 수 없습니다"),
    "reaction_not_allowed": (409, "추적 중 사업 변화 항목에는 반응을 남길 수 없습니다"),
    "version_conflict": (409, "브리핑 항목이 변경되었습니다"),
    "idempotency_conflict": (409, "같은 request_id가 다른 요청에 사용되었습니다"),
    "processing_failed": (500, "브리핑을 처리할 수 없습니다"),
}


def _error(
    error: briefing_service.BriefingError | BundleServiceError,
    *,
    request_id: UUID | None = None,
) -> JSONResponse:
    registered = error.code in _ERRORS
    code = error.code if registered else "processing_failed"
    status_code, message = _ERRORS[code]
    details = getattr(error, "details", None) if registered else None
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details if isinstance(details, dict) else None,
            },
            "request_id": str(request_id) if request_id is not None else None,
        },
    )


def _unexpected(*, request_id: UUID | None = None) -> JSONResponse:
    return _error(briefing_service.BriefingError("processing_failed"), request_id=request_id)


@router.get("/latest", response_model=BriefingView)
def latest_briefing(session: Session = Depends(get_db)) -> BriefingView | JSONResponse:
    try:
        return briefing_service.get_latest_briefing_view(session)
    except briefing_service.BriefingError as error:
        return _error(error)


@router.get("/{briefing_date}", response_model=BriefingView)
def briefing_by_date(
    briefing_date: date, session: Session = Depends(get_db)
) -> BriefingView | JSONResponse:
    try:
        return briefing_service.get_briefing_view(session, briefing_date)
    except briefing_service.BriefingError as error:
        return _error(error)


@router.get("/{briefing_date}/slack-preview", response_model=BriefingSlackPreview)
def briefing_slack_preview_route(
    briefing_date: date, session: Session = Depends(get_db)
) -> BriefingSlackPreview | JSONResponse:
    try:
        return briefing_slack_preview(session, briefing_date)
    except briefing_service.BriefingError as error:
        return _error(error)


@router.patch("/items/{item_id}/reaction", response_model=BriefingItemView)
def react_to_briefing_item(
    item_id: UUID,
    payload: BriefingReactionRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> JSONResponse:
    try:
        actor_name = validate_actor(actor, actor_format)
        result = briefing_service.react_to_item(
            session,
            item_id=item_id,
            reaction=payload.reaction,
            expected_revision=payload.expected_revision,
            request_id=payload.request_id,
            actor=actor_name,
            via="screen",
        )
        session.commit()
        return JSONResponse(status_code=200, content=result.snapshot)
    except (briefing_service.BriefingError, BundleServiceError) as error:
        session.rollback()
        return _error(error, request_id=payload.request_id)
    except Exception:  # pragma: no cover - defensive API boundary
        session.rollback()
        return _unexpected(request_id=payload.request_id)


__all__ = ["router"]
