"""Cumulative business-opportunity discovery and tracking endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...core.db import get_db
from .. import extension_registry
from ..schemas.opportunities import (
    CandidateDecisionRequest,
    OpportunityDetailResponse,
    OpportunityFirstRegisteredStage,
    OpportunityLinkView,
    OpportunityListResponse,
    OpportunitySection,
    OpportunityTrackingDecisionsResponse,
    OpportunitySort,
    OpportunityTrackingStatus,
    TrackingStatusUpdateRequest,
    OrderPlanBulkPreviewRequest,
    OrderPlanBulkPreviewResponse,
    OrderPlanBulkStartRequest,
    OrderPlanBulkStartResponse,
)
from ..services import opportunity_integrity, opportunity_tracking, opportunity_queries
from ..services import order_plan_bulk_tracking
from ...core.api_errors import BundleServiceError, validate_actor


router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])
logger = logging.getLogger(__name__)

_ERRORS: dict[str, tuple[int, str]] = {
    "invalid_request": (422, "요청이 올바르지 않습니다"),
    "actor_name_required": (400, "담당자 이름이 필요합니다"),
    "actor_name_invalid": (400, "담당자 이름이 올바르지 않습니다"),
    "opportunity_not_found": (404, "사업기회를 찾을 수 없습니다"),
    "opportunity_invalid": (422, "사업기회 식별자가 올바르지 않습니다"),
    "tracking_status_invalid": (422, "지원하지 않는 추적 상태입니다"),
    "tracking_reason_required": (422, "추적 상태를 선택한 이유가 필요합니다"),
    "opportunity_merged": (409, "병합된 사업기회의 상태는 변경할 수 없습니다"),
    "opportunity_link_invalid": (422, "사업기회 연결 식별자가 올바르지 않습니다"),
    "opportunity_link_not_found": (404, "사업기회 연결을 찾을 수 없습니다"),
    "candidate_link_required": (409, "후보 연결만 사람 판정할 수 있습니다"),
    "candidate_decision_reason_required": (422, "후보 연결 판정 이유가 필요합니다"),
    "candidate_decision_conflict": (409, "후보 연결에 이미 다른 판정이 있습니다"),
    "candidate_state_conflict": (409, "현재 상태에서는 후보 연결을 판정할 수 없습니다"),
    "candidate_target_required": (409, "수락할 후보 연결 대상이 필요합니다"),
    "candidate_target_already_authoritative": (
        409,
        "대상 레코드는 이미 확정된 사업기회에 연결되어 있습니다",
    ),
    "idempotency_conflict": (409, "같은 request_id가 다른 요청에 사용되었습니다"),
    "temporarily_unavailable": (503, "사업기회 작업을 일시적으로 사용할 수 없습니다"),
    "service_unavailable": (503, "사업기회 작업을 일시적으로 사용할 수 없습니다"),
    "processing_failed": (500, "사업기회 작업을 완료할 수 없습니다"),
}


def _error_response(
    error: opportunity_tracking.OpportunityTrackingError
    | opportunity_integrity.OpportunityIntegrityError
    | order_plan_bulk_tracking.OrderPlanBulkTrackingError
    | BundleServiceError,
) -> JSONResponse:
    """Return only stable, safe API error data."""

    status_code, message = _ERRORS.get(
        error.code,
        (500, "사업기회 작업을 완료할 수 없습니다"),
    )
    if isinstance(error, BundleServiceError):
        status_code = error.status_code
    elif isinstance(error, order_plan_bulk_tracking.OrderPlanBulkTrackingError):
        status_code = error.status_code
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": error.code if error.code in _ERRORS else "processing_failed",
                "message": message,
                "details": None,
            },
            "request_id": (
                str(error.request_id)
                if isinstance(
                    error, order_plan_bulk_tracking.OrderPlanBulkTrackingError
                )
                and error.request_id is not None
                else None
            ),
        },
    )


def _unexpected() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "processing_failed",
                "message": "사업기회 작업을 완료할 수 없습니다",
                "details": None,
            },
            "request_id": None,
        },
    )


@router.get("", response_model=OpportunityListResponse)
def list_opportunities(
    tracking_status: OpportunityTrackingStatus | None = Query(default=None),
    first_registered_stage: OpportunityFirstRegisteredStage | None = Query(default=None),
    section: OpportunitySection | None = Query(default=None),
    sort: OpportunitySort = Query(default="created_at"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> OpportunityListResponse:
    return opportunity_queries.list_opportunities(
        session, tracking_status=tracking_status, first_registered_stage=first_registered_stage,
        section=section, sort=sort, limit=limit, offset=offset,
    )


@router.post(
    "/order-plan-tracking/preview",
    response_model=OrderPlanBulkPreviewResponse,
)
def preview_order_plan_tracking(
    payload: OrderPlanBulkPreviewRequest,
    session: Session = Depends(get_db),
) -> OrderPlanBulkPreviewResponse | JSONResponse:
    """Preview selected plans without creating tracking or audit state."""

    try:
        return order_plan_bulk_tracking.preview_order_plan_tracking(
            session, payload.order_plan_ids
        )
    except order_plan_bulk_tracking.OrderPlanBulkTrackingError as error:
        session.rollback()
        return _error_response(error)
    except Exception:  # pragma: no cover - defensive API boundary
        session.rollback()
        return _unexpected()


@router.post(
    "/order-plan-tracking/bulk-start",
    response_model=OrderPlanBulkStartResponse,
)
def start_order_plan_tracking(
    payload: OrderPlanBulkStartRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> JSONResponse:
    """Start tracking for selected plans and return their durable receipt."""

    try:
        actor_name = validate_actor(actor, actor_format)
        result = order_plan_bulk_tracking.start_order_plan_tracking(
            session,
            payload.order_plan_ids,
            request_id=payload.request_id,
            reason=payload.reason,
            selected_by=actor_name,
        )
        # ``result.snapshot`` is either the exact JSON committed in the
        # IdempotencyRecord or the identical JSON that was just committed.
        # Returning it directly avoids a replay-time DTO dump/recalculation.
        return JSONResponse(
            status_code=result.response_status,
            content=result.snapshot,
        )
    except (
        order_plan_bulk_tracking.OrderPlanBulkTrackingError,
        BundleServiceError,
    ) as error:
        session.rollback()
        return _error_response(error)
    except Exception:  # pragma: no cover - defensive API boundary
        session.rollback()
        return _unexpected()


@router.get("/{opportunity_id}", response_model=OpportunityDetailResponse)
def get_opportunity(
    opportunity_id: int,
    session: Session = Depends(get_db),
) -> OpportunityDetailResponse | JSONResponse:
    try:
        return opportunity_queries.get_opportunity(session, opportunity_id)
    except opportunity_tracking.OpportunityTrackingError as error:
        return _error_response(error)


@router.get("/{opportunity_id}/tracking-decisions", response_model=OpportunityTrackingDecisionsResponse)
def get_tracking_decisions(
    opportunity_id: int,
    session: Session = Depends(get_db),
) -> OpportunityTrackingDecisionsResponse | JSONResponse:
    try:
        return opportunity_queries.tracking_decisions(session, opportunity_id)
    except opportunity_tracking.OpportunityTrackingError as error:
        return _error_response(error)


@router.patch(
    "/links/{link_id}/decision",
    response_model=OpportunityLinkView,
)
def decide_candidate_link(
    link_id: int,
    payload: CandidateDecisionRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> OpportunityLinkView | JSONResponse:
    """Record a human accept/reject decision for one pending candidate."""

    try:
        actor_name = validate_actor(actor, actor_format)
        link = opportunity_integrity.decide_candidate_link(
            session,
            link_id,
            decision=payload.decision,
            reason=payload.reason,
            reviewer_name=actor_name,
            reviewed_at=datetime.now(UTC),
        )
        session.commit()
        session.refresh(link)
        return opportunity_queries.link_view(link)
    except (
        opportunity_integrity.OpportunityIntegrityError,
        opportunity_tracking.OpportunityTrackingError,
        BundleServiceError,
    ) as error:
        session.rollback()
        return _error_response(error)
    except Exception:  # pragma: no cover - defensive API boundary
        session.rollback()
        return _unexpected()


@router.patch("/{opportunity_id}/tracking-status", response_model=OpportunityDetailResponse)
def update_tracking_status(
    opportunity_id: int,
    payload: TrackingStatusUpdateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> OpportunityDetailResponse | JSONResponse:
    """Record a human tracking choice through the domain service."""

    try:
        actor_name = validate_actor(actor, actor_format)
        opportunity_tracking.set_tracking_status(
            session,
            opportunity_id,
            status=payload.tracking_status,
            reason=payload.reason,
            selected_by=actor_name,
            selected_at=datetime.now(UTC),
        )
        session.commit()
        registry = None
        try:
            # 추적 결정 변경됨 hook(명세 §6.2). 어느 모듈이 무엇을 하는지는 모르고,
            # 사람 결정이 commit된 뒤 별도 transaction에서 부른다.
            registry = extension_registry()
            registry.tracking_decision_changed(session, opportunity_id)
            session.commit()
        except Exception as error:
            # The human tracking decision is already durable.  The hook is a
            # retryable side effect and must never rewrite the four human
            # choice fields or turn a successful PATCH into a 500 response.
            session.rollback()
            # 어느 제공자가 무엇을 하는지 모르므로 확장점 어휘로만 남긴다.
            # 등록자 수와 예외 타입은 lifecycle이 정당하게 아는 값이다.
            logger.warning(
                "tracking decision extension hook failed",
                extra={
                    "bidops": {
                        "event": "extension.tracking_decision_hook_failed",
                        "hook_count": (
                            registry.tracking_decision_hook_count
                            if registry is not None
                            else None
                        ),
                        "error_type": type(error).__name__,
                    }
                },
            )
        return opportunity_queries.get_opportunity(session, opportunity_id)
    except (opportunity_tracking.OpportunityTrackingError, BundleServiceError) as error:
        session.rollback()
        return _error_response(error)
    except Exception:  # pragma: no cover - defensive API boundary
        session.rollback()
        return _unexpected()


__all__ = ["router"]
