"""RL-03 사업기회 경로 판정 REST와 전송 정책 조회 (spec "REST", ADR-0045).

- `GET /api/opportunities/{id}/verdict?attempt_id=`: 권위 연결 사전규격의 판정 view(읽기 전용
  별칭). 사전규격이 없으면 200 `availability=none`.
- `POST /api/opportunities/{id}/verdict-requests`: 수동 "다시 판정"(202, 항상 새 attempt,
  cap 초과는 409 `daily_cap_reached`, 큐에 넣지 않음).
- `GET /api/analysis/transfer-policy`: 설정 화면용 활성 전송 승인과 오늘 사용량(운영 정보).

경로 접두사는 lifecycle 것(`/api/opportunities`)이지만 제공 모듈은 deep_review다.
`BIDOPS_RL_ANALYSIS_ENABLED=false`이면 조립 계층 미들웨어가 먼저 404를 내고 service도 같은
판정을 한 번 더 한다. ORM은 다루지 않는다 — 판정·저장은 `services/verdict_view`·
`services/verdict_trigger`가 하고, 이 파일은 본문 검증과 안정 오류 코드 → HTTP 상태 변환만 한다.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path as ApiPath, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.db import get_db
from ..schemas.verdict_view import (
    PractitionerVerdictView,
    TransferPolicyView,
    VerdictRequestCreate,
    VerdictRequestReceipt,
)
from ..services.company_deep_review import ERROR_MESSAGES, ERROR_STATUS
from ..services.deep_reviews import DeepReviewService, DeepReviewServiceError
from ..services.input_versions import InputVersionError
from ..services.verdict_trigger import VerdictRequestError, request_manual_verdict
from ..services.verdict_view import (
    VERDICT_ERROR_MESSAGES,
    VERDICT_ERROR_STATUS,
    VerdictViewError,
    opportunity_verdict_view,
    transfer_policy_view,
)


router = APIRouter(prefix="/api/opportunities", tags=["verdicts"])
transfer_policy_router = APIRouter(prefix="/api/analysis", tags=["verdicts"])
service = DeepReviewService()

#: Stable codes this router may answer with (service tables are the source of truth).
ERROR_STATUS_ALL: dict[str, int] = {**ERROR_STATUS, **VerdictRequestError.STATUS, **VERDICT_ERROR_STATUS}
ERROR_MESSAGES_ALL: dict[str, str] = {**ERROR_MESSAGES, **VerdictRequestError.MESSAGES, **VERDICT_ERROR_MESSAGES}
# A manual request body problem is a 422 like FastAPI validation (spec "REST" 422).
ERROR_STATUS_ALL["invalid_request"] = 422


def _error_response(code: str, *, request_id: UUID | None = None) -> JSONResponse:
    safe = code if code in ERROR_STATUS_ALL else "processing_failed"
    return JSONResponse(
        status_code=ERROR_STATUS_ALL[safe],
        content={
            "error": {"code": safe, "message": ERROR_MESSAGES_ALL[safe], "details": None},
            "request_id": str(request_id) if request_id else None,
        },
    )


def _read(session: Session, call) -> JSONResponse:  # type: ignore[no-untyped-def]
    try:
        content = call()
    except VerdictViewError as error:
        session.rollback()
        return _error_response(error.code)
    except Exception:  # noqa: BLE001 - safe API boundary; nothing about the data is logged
        session.rollback()
        return _error_response("processing_failed")
    session.rollback()
    return JSONResponse(status_code=200, content=content)


@router.get("/{opportunity_id}/verdict", response_model=PractitionerVerdictView)
def get_opportunity_verdict(
    opportunity_id: int = ApiPath(..., ge=1),
    attempt_id: UUID | None = Query(default=None),
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _read(session, lambda: opportunity_verdict_view(
        session, opportunity_id=opportunity_id, attempt_id=attempt_id,
    ))


@router.post("/{opportunity_id}/verdict-requests", response_model=VerdictRequestReceipt, status_code=202)
def create_opportunity_verdict_request(
    payload: VerdictRequestCreate,
    opportunity_id: int = ApiPath(..., ge=1),
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> JSONResponse:
    try:
        claimed = validate_actor(actor, actor_format)
        if claimed.casefold().startswith("system:"):
            raise BundleServiceError("actor_name_invalid", "담당자 이름이 올바르지 않습니다", status_code=400)
        content = request_manual_verdict(
            service, session, opportunity_id=opportunity_id, actor=claimed, request_id=payload.request_id,
        )
    except BundleServiceError as error:
        session.rollback()
        return _error_response(error.code, request_id=payload.request_id)
    except (VerdictRequestError, DeepReviewServiceError, InputVersionError) as error:
        session.rollback()
        return _error_response(error.code, request_id=payload.request_id)
    except Exception:  # noqa: BLE001 - safe API boundary
        session.rollback()
        return _error_response("processing_failed", request_id=payload.request_id)
    return JSONResponse(status_code=202, content=content)


@transfer_policy_router.get("/transfer-policy", response_model=TransferPolicyView)
def get_transfer_policy(session: Session = Depends(get_db)) -> JSONResponse:
    return _read(session, lambda: transfer_policy_view(session))


__all__ = ["ERROR_MESSAGES_ALL", "ERROR_STATUS_ALL", "router", "service", "transfer_policy_router"]
