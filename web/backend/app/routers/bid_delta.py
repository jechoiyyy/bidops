"""Bid-delta comparison and final-decision REST endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas.bid_delta import (
    BidDeltaAttemptCreateRequest,
    BidDeltaComparisonCreateRequest,
    BidDeltaComparisonView,
    BidDeltaWorkspaceView,
    BidFinalDecisionCreateRequest,
    BidFinalDecisionView,
)
from ..services.bid_delta import BidDeltaService, BidDeltaServiceError


router = APIRouter(prefix="/api/opportunities", tags=["bid-delta"])
service = BidDeltaService()

_MESSAGES = {
    "opportunity_not_found": "사업기회를 찾을 수 없습니다",
    "opportunity_merged": "병합된 사업기회는 사용할 수 없습니다",
    "bid_delta_input_not_found": "비교 입력을 찾을 수 없습니다",
    "bid_delta_input_not_authoritative": "비교 입력 연결이 authoritative 상태가 아닙니다",
    "bid_delta_input_not_ready": "비교 입력이 아직 준비되지 않았습니다",
    "bid_delta_input_scope_conflict": "비교 입력의 사업기회 범위가 다릅니다",
    "bid_delta_input_version_conflict": "비교 문서 버전이 변경되었습니다",
    "bid_delta_comparison_not_found": "비교를 찾을 수 없습니다",
    "bid_delta_comparison_scope_conflict": "비교의 사업기회 범위가 다릅니다",
    "bid_delta_comparison_not_retryable": "실패한 비교만 재시도할 수 있습니다",
    "bid_delta_comparison_not_completed": "완료된 비교만 최종 결정할 수 있습니다",
    "bid_delta_version_conflict": "비교 버전이 변경되었습니다",
    "bid_delta_result_digest_conflict": "비교 결과 digest가 변경되었습니다",
    "bid_delta_comparison_stale": "새로운 비교 입력이 있어 재검토가 필요합니다",
    "final_decision_supersession_conflict": "최종 결정의 supersession 대상이 변경되었습니다",
    "final_decision_not_found": "앞선 최종 결정을 찾을 수 없습니다",
    "active_attempt_exists": "이미 실행 중인 attempt가 있습니다",
    "idempotency_conflict": "같은 request_id가 다른 요청에 사용되었습니다",
    "bid_delta_same_input": "baseline과 comparison 입력이 같습니다",
    "bid_delta_baseline_type_invalid": "baseline 입력 형식이 올바르지 않습니다",
    "bid_delta_comparison_type_invalid": "comparison 입력 형식이 올바르지 않습니다",
    "bid_delta_category_policy_invalid": "지원하지 않는 category policy입니다",
    "final_decision_value_invalid": "최종 결정 값이 올바르지 않습니다",
    "final_decision_input_fence_invalid": "최종 결정 입력 fence가 비교와 다릅니다",
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "final_decision_reason_required": "최종 결정 사유가 필요합니다",
    "bid_delta_service_unavailable": "입찰 delta 서비스를 사용할 수 없습니다",
    "bid_delta_projection_unavailable": "입찰 delta 조회를 사용할 수 없습니다",
    "bid_delta_currentness_unavailable": "비교 현재성을 확인할 수 없습니다",
    "processing_failed": "입찰 delta 작업을 완료할 수 없습니다",
}


def _error_response(error: BidDeltaServiceError) -> JSONResponse:
    code = error.code if error.code in _MESSAGES else "processing_failed"
    status_code = error.status_code if code == error.code else 500
    return JSONResponse(
        status_code=status_code,
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


@router.get("/{opportunity_id}/bid-delta", response_model=BidDeltaWorkspaceView)
def get_bid_delta_workspace(
    opportunity_id: int,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.workspace(session, opportunity_id)
    except BidDeltaServiceError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session)


@router.post(
    "/{opportunity_id}/bid-delta/comparisons",
    response_model=BidDeltaComparisonView,
    status_code=202,
)
def create_bid_delta_comparison(
    opportunity_id: int,
    payload: BidDeltaComparisonCreateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.create_comparison(session, opportunity_id, payload, actor, actor_format)
    except BidDeltaServiceError as error:
        return _error_response(error)
    except Exception:
        return _unexpected(session, payload.request_id)


@router.get(
    "/{opportunity_id}/bid-delta/comparisons/{comparison_id}",
    response_model=BidDeltaComparisonView,
)
def get_bid_delta_comparison(
    opportunity_id: int,
    comparison_id: UUID,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.comparison_view(session, comparison_id, opportunity_id)
    except BidDeltaServiceError as error:
        session.rollback()
        return _error_response(error)
    except Exception:
        return _unexpected(session)


@router.post(
    "/{opportunity_id}/bid-delta/comparisons/{comparison_id}/attempts",
    response_model=BidDeltaComparisonView,
    status_code=202,
)
def retry_bid_delta_attempt(
    opportunity_id: int,
    comparison_id: UUID,
    payload: BidDeltaAttemptCreateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.retry_attempt(session, opportunity_id, comparison_id, payload, actor, actor_format)
    except BidDeltaServiceError as error:
        return _error_response(error)
    except Exception:
        return _unexpected(session, payload.request_id)


@router.post(
    "/{opportunity_id}/bid-delta/comparisons/{comparison_id}/final-decisions",
    response_model=BidFinalDecisionView,
    status_code=201,
)
def create_bid_final_decision(
    opportunity_id: int,
    comparison_id: UUID,
    payload: BidFinalDecisionCreateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        return service.record_final_decision(session, opportunity_id, comparison_id, payload, actor, actor_format)
    except BidDeltaServiceError as error:
        return _error_response(error)
    except Exception:
        return _unexpected(session, payload.request_id)


__all__ = ["router", "service"]
