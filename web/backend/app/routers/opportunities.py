"""Cumulative business-opportunity discovery and tracking endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import Notice, Opportunity, OpportunityLink
from ..schemas.opportunities import (
    OpportunityDetailResponse,
    OpportunityFirstRegisteredStage,
    OpportunityLinkView,
    OpportunityListItem,
    OpportunityListResponse,
    OpportunitySort,
    OpportunityTrackingStatus,
    TrackingStatusUpdateRequest,
)
from ..services import opportunity_tracking
from ..services.document_bundles import BundleServiceError, validate_actor
from ..services.prespec_attachments import refresh_fetch_eligibility


router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])
logger = logging.getLogger(__name__)

_TRACKING_STATUS_ORDER = ("미선택", "계속 추적", "보류", "종료")
_FIRST_STAGE_ORDER = ("order_plan", "pre_spec", "bid_notice")

_ERRORS: dict[str, tuple[int, str]] = {
    "actor_name_required": (400, "담당자 이름이 필요합니다"),
    "actor_name_invalid": (400, "담당자 이름이 올바르지 않습니다"),
    "opportunity_not_found": (404, "사업기회를 찾을 수 없습니다"),
    "opportunity_invalid": (422, "사업기회 식별자가 올바르지 않습니다"),
    "tracking_status_invalid": (422, "지원하지 않는 추적 상태입니다"),
    "tracking_reason_required": (422, "추적 상태를 선택한 이유가 필요합니다"),
}


def _error_response(error: OpportunityTrackingError | BundleServiceError) -> JSONResponse:
    """Return only stable, safe API error data."""

    status_code, message = _ERRORS.get(
        error.code,
        (500, "사업기회 작업을 완료할 수 없습니다"),
    )
    if isinstance(error, BundleServiceError):
        status_code = error.status_code
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": error.code if error.code in _ERRORS else "processing_failed",
                "message": message,
                "details": None,
            },
            "request_id": None,
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


def _strategy_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    allowed = {"full", "breaking_split", "normalized", "longest_fragment", "prefix12"}
    return [item for item in value if isinstance(item, str) and item in allowed]


def _link_view(link: OpportunityLink) -> OpportunityLinkView:
    """Project a link without exposing raw records or storage metadata."""

    record_type: str | None = None
    record_id: int | None = None
    notice_id: int | None = link.notice_id
    order_plan_id: int | None = link.order_plan_id
    source_type: str | None = None
    title: str | None = None
    agency: str | None = None
    record_external_id: str | None = None

    if link.notice is not None:
        record_type = link.notice.source_type or "notice"
        record_id = link.notice.id
        notice_id = link.notice.id
        source_type = link.notice.source_type
        title = link.notice.title
        agency = link.notice.agency
        record_external_id = link.notice.notice_key
    elif link.order_plan is not None:
        record_type = "order_plan"
        record_id = link.order_plan.id
        order_plan_id = link.order_plan.id
        title = link.order_plan.title
        agency = link.order_plan.agency_name or link.order_plan.supervising_agency_name
        record_external_id = link.order_plan.order_plan_unty_no
    elif link.stage == "order_plan":
        # A targetless official link retains the upstream number while the
        # corresponding record is outside the current collection window.
        record_type = "order_plan"
    elif link.stage == "notice":
        record_type = "notice"

    external_id = record_external_id or link.evidence_external_no
    return OpportunityLinkView(
        id=link.id,
        stage=link.stage,
        link_type=link.link_type,
        status=link.status,
        search_strategy=link.search_strategy,
        attempted_strategies=_strategy_values(link.attempted_strategies_json),
        agency_match=link.agency_match,
        last_searched_at=link.last_searched_at,
        evidence_external_no=link.evidence_external_no,
        evidence_bid_no=link.evidence_bid_no,
        human_decision=link.human_decision,
        reviewer_name=link.reviewer_name,
        reviewed_at=link.reviewed_at,
        review_reason=link.review_reason,
        record_type=record_type,
        record_id=record_id,
        notice_id=notice_id,
        order_plan_id=order_plan_id,
        source_type=source_type,
        title=title,
        agency=agency,
        external_id=external_id,
        record_external_id=record_external_id,
    )


def _links_for(opportunity: Opportunity) -> list[OpportunityLinkView]:
    return [
        _link_view(link)
        for link in sorted(opportunity.links, key=lambda item: (item.stage, item.id))
    ]


def _opportunity_state(opportunity: Opportunity) -> dict[str, Any]:
    return {
        "id": opportunity.id,
        "tracking_status": opportunity.tracking_status,
        "tracking_reason": opportunity.tracking_reason,
        "tracking_selected_by": opportunity.tracking_selected_by,
        "tracking_selected_at": opportunity.tracking_selected_at,
        "recheck_signal": opportunity.recheck_signal_at is not None,
        "recheck_signal_at": opportunity.recheck_signal_at,
        "recheck_signal_link_id": opportunity.recheck_signal_link_id,
        "first_registered_stage": opportunity.first_registered_stage,
    }


def _list_item(opportunity: Opportunity) -> OpportunityListItem:
    return OpportunityListItem(**_opportunity_state(opportunity), links=_links_for(opportunity))


def _detail(opportunity: Opportunity) -> OpportunityDetailResponse:
    return OpportunityDetailResponse(**_opportunity_state(opportunity), links=_links_for(opportunity))


def _link_options():
    return (
        selectinload(Opportunity.links).selectinload(OpportunityLink.notice),
        selectinload(Opportunity.links).selectinload(OpportunityLink.order_plan),
    )


@router.get("", response_model=OpportunityListResponse)
def list_opportunities(
    tracking_status: OpportunityTrackingStatus | None = Query(default=None),
    first_registered_stage: OpportunityFirstRegisteredStage | None = Query(default=None),
    sort: OpportunitySort = Query(default="created_at"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> OpportunityListResponse:
    """List all opportunities unless an explicit filter is supplied.

    In particular, ``종료`` is not excluded by the default query.  The
    independent recheck signal lets a closed opportunity be visible again
    without changing the human tracking choice.
    """

    conditions: list[Any] = []
    if tracking_status is not None:
        conditions.append(Opportunity.tracking_status == tracking_status)
    if first_registered_stage is not None:
        conditions.append(Opportunity.first_registered_stage == first_registered_stage)

    total = int(
        session.scalar(
            select(func.count(Opportunity.id)).where(*conditions)
        )
        or 0
    )
    query = select(Opportunity).where(*conditions).options(*_link_options())
    if sort == "tracking_status":
        status_rank = case(
            *[(Opportunity.tracking_status == value, index) for index, value in enumerate(_TRACKING_STATUS_ORDER)],
            else_=len(_TRACKING_STATUS_ORDER),
        )
        query = query.order_by(status_rank.asc(), Opportunity.created_at.desc(), Opportunity.id.desc())
    elif sort == "first_registered_stage":
        stage_rank = case(
            *[(Opportunity.first_registered_stage == value, index) for index, value in enumerate(_FIRST_STAGE_ORDER)],
            else_=len(_FIRST_STAGE_ORDER),
        )
        query = query.order_by(stage_rank.asc(), Opportunity.created_at.desc(), Opportunity.id.desc())
    else:
        query = query.order_by(Opportunity.created_at.desc(), Opportunity.id.desc())

    rows = session.scalars(query.offset(offset).limit(limit)).all()
    return OpportunityListResponse(
        items=[_list_item(opportunity) for opportunity in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _get_opportunity(session: Session, opportunity_id: int) -> Opportunity | None:
    return session.scalar(
        select(Opportunity)
        .where(Opportunity.id == opportunity_id)
        .options(*_link_options())
    )


@router.get("/{opportunity_id}", response_model=OpportunityDetailResponse)
def get_opportunity(
    opportunity_id: int,
    session: Session = Depends(get_db),
) -> OpportunityDetailResponse | JSONResponse:
    opportunity = _get_opportunity(session, opportunity_id)
    if opportunity is None:
        return _error_response(
            opportunity_tracking.OpportunityTrackingError(
                "opportunity_not_found", "사업기회를 찾을 수 없습니다"
            )
        )
    return _detail(opportunity)


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
        try:
            prespec_notice_ids = session.scalars(
                select(Notice.id)
                .join(OpportunityLink, OpportunityLink.notice_id == Notice.id)
                .where(
                    OpportunityLink.opportunity_id == opportunity_id,
                    OpportunityLink.stage == "notice",
                    Notice.source_type == "pre_spec",
                )
            ).all()
            refresh_fetch_eligibility(session, notice_ids=prespec_notice_ids)
            session.commit()
        except Exception:
            # The human tracking decision is already durable.  Eligibility is
            # a retryable side effect and must never rewrite the four human
            # choice fields or turn a successful PATCH into a 500 response.
            session.rollback()
            logger.warning(
                "pre-spec attachment eligibility refresh failed",
                extra={"bidops": {"event": "prespec_attachment.refresh_failed"}},
            )
        updated = _get_opportunity(session, opportunity_id)
        if updated is None:  # pragma: no cover - the service locked this row.
            return _error_response(
                opportunity_tracking.OpportunityTrackingError(
                    "opportunity_not_found", "사업기회를 찾을 수 없습니다"
                )
            )
        return _detail(updated)
    except (opportunity_tracking.OpportunityTrackingError, BundleServiceError) as error:
        session.rollback()
        return _error_response(error)
    except Exception:  # pragma: no cover - defensive API boundary
        session.rollback()
        return _unexpected()


__all__ = ["router"]
