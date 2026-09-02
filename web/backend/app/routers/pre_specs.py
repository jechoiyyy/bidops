"""Cumulative pre-specification discovery list."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, get_args

from fastapi import APIRouter, Depends, Path as ApiPath, Query
from fastapi.responses import JSONResponse
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from ..db import get_db
from ..models import (
    Attachment,
    AttachmentFetch,
    Notice,
    Opportunity,
    OpportunityLink,
    PreSpecOverviewReview,
)
from ..schemas.pre_specs import (
    PreSpecDocumentSummary,
    PreSpecListItem,
    PreSpecListResponse,
    PreSpecOverviewReviewsResponse,
    PreSpecOverviewReviewsV2Response,
    PreSpecOverviewStatusCount,
    PreSpecOverviewReviewStatus,
    PreSpecOrigin,
    PreSpecSort,
)
from ..services.opportunity_integrity import (
    active_opportunity_predicate,
    authoritative_link_predicate,
)
from ..services.prespec_attachments import tracked_order_plan_connection_predicate
from ..services.prespec_overview import (
    OverviewPreparationError,
    OverviewReviewNotFound,
    OverviewScopeError,
    get_overview_reviews,
    get_overview_reviews_v2,
)
from .common import decimal_float


router = APIRouter(prefix="/api/pre-specs", tags=["pre-specs"])

_FETCH_STATUSES = {
    "완료": "completed",
    "대기": "pending",
    "진행": "running",
    "차단": "blocked",
    "실패": "failed",
}


def _document_counts_subquery():
    count_columns = [
        Attachment.notice_id.label("notice_id"),
        func.count(Attachment.id).label("attachments"),
    ]
    for status, label in _FETCH_STATUSES.items():
        count_columns.append(
            func.coalesce(
                func.sum(case((AttachmentFetch.status == status, 1), else_=0)),
                0,
            ).label(label)
        )
    return (
        select(*count_columns)
        .select_from(Attachment)
        .outerjoin(AttachmentFetch, AttachmentFetch.attachment_id == Attachment.id)
        .where(Attachment.retired_at.is_(None))
        .group_by(Attachment.notice_id)
        .subquery("pre_spec_document_counts")
    )


def _connected_link_subquery():
    """Select the sole authoritative active owner for each notice."""

    link = aliased(OpportunityLink)
    opportunity = aliased(Opportunity)
    return (
        select(
            link.notice_id.label("notice_id"),
            link.id.label("link_id"),
        )
        .join(opportunity, opportunity.id == link.opportunity_id)
        .where(
            link.stage == "notice",
            link.notice_id.is_not(None),
            authoritative_link_predicate(link),
            active_opportunity_predicate(opportunity),
        )
        .subquery("pre_spec_connected_link")
    )


def _qualification_value(notice: Notice, key: str) -> Any:
    flags = notice.qualification_flags_json
    if not isinstance(flags, Mapping):
        return None
    return flags.get(key)


def _pre_spec_number(notice: Notice) -> Any:
    lifecycle = notice.lifecycle_json
    if not isinstance(lifecycle, Mapping):
        return None
    # The response contract deliberately names this exact source location;
    # an arbitrary notice key must not be promoted to a pre-spec number.
    return lifecycle.get("pre_spec_no")


def _count(value: Any) -> int:
    return int(value or 0)


@router.get("/{notice_id}/overview-reviews", response_model=PreSpecOverviewReviewsResponse)
def get_pre_spec_overview_reviews(
    notice_id: int = ApiPath(..., ge=1),
    session: Session = Depends(get_db),
) -> PreSpecOverviewReviewsResponse | JSONResponse:
    """Return safe lineage metadata for the independent overview stage."""

    try:
        return get_overview_reviews(session, notice_id)
    except OverviewReviewNotFound:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "not_found",
                    "message": "요청한 사전규격 공고를 찾을 수 없습니다",
                    "details": None,
                },
                "request_id": None,
            },
        )
    except OverviewPreparationError:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "processing_failed",
                    "message": "사전규격 개요 검토를 준비할 수 없습니다",
                    "details": None,
                },
                "request_id": None,
            },
        )


@router.get(
    "/{notice_id}/overview-reviews/v2",
    response_model=PreSpecOverviewReviewsV2Response,
)
def get_pre_spec_overview_reviews_v2(
    notice_id: int = ApiPath(..., ge=1),
    session: Session = Depends(get_db),
) -> PreSpecOverviewReviewsV2Response | JSONResponse:
    """Return the phase-2 validated result projection without internals."""

    try:
        return get_overview_reviews_v2(session, notice_id)
    except OverviewReviewNotFound:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "not_found",
                    "message": "요청한 사전규격 공고를 찾을 수 없습니다",
                    "details": None,
                },
                "request_id": None,
            },
        )
    except OverviewScopeError:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "validation_failed",
                    "message": "사전규격 개요 결과의 입력 범위를 검증할 수 없습니다",
                    "details": None,
                },
                "request_id": None,
            },
        )
    except OverviewPreparationError:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "processing_failed",
                    "message": "사전규격 개요 검토를 준비할 수 없습니다",
                    "details": None,
                },
                "request_id": None,
            },
        )


@router.get("", response_model=PreSpecListResponse)
def list_pre_specs(
    notice_pk: int | None = Query(default=None, ge=1),
    sw_only: bool = Query(default=True),
    business_division: str | None = Query(default=None),
    origin: PreSpecOrigin | None = Query(default=None),
    q: str | None = Query(default=None),
    sort: PreSpecSort = Query(default="published"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> PreSpecListResponse:
    """List all cumulative pre-spec notices with safe attachment summaries."""

    connected_link = _connected_link_subquery()
    selected_link = aliased(OpportunityLink, name="pre_spec_selected_link")
    selected_opportunity = aliased(Opportunity, name="pre_spec_selected_opportunity")
    document_counts = _document_counts_subquery()
    tracked_exception = tracked_order_plan_connection_predicate(Notice.id)
    sw_status = Notice.qualification_flags_json["sw_business_status"].as_string()
    division_value = Notice.qualification_flags_json["business_division"].as_string()
    kept_by_tracking = and_(or_(sw_status.is_(None), sw_status != "Y"), tracked_exception)

    conditions: list[Any] = [Notice.source_type == "pre_spec"]
    if notice_pk is not None:
        conditions.append(Notice.id == notice_pk)
    if sw_only and notice_pk is None:
        # The tracked exception is the same domain predicate used by
        # attachment eligibility; it is not a second router-owned rule.
        conditions.append(or_(sw_status == "Y", tracked_exception))
    if business_division and business_division.strip():
        conditions.append(division_value == business_division.strip())
    if origin == "추적":
        conditions.append(selected_opportunity.first_registered_stage == "order_plan")
    elif origin == "신규":
        conditions.append(selected_opportunity.first_registered_stage.in_(("pre_spec", "bid_notice")))
    if q and q.strip():
        needle = f"%{q.strip()}%"
        conditions.append(or_(Notice.title.ilike(needle), Notice.agency.ilike(needle)))

    overview_review = aliased(PreSpecOverviewReview, name="pre_spec_overview_review")

    query = (
        select(
            Notice,
            selected_opportunity.id.label("opportunity_id"),
            selected_opportunity.tracking_status.label("tracking_status"),
            selected_opportunity.first_registered_stage.label("first_registered_stage"),
            kept_by_tracking.label("kept_by_tracking"),
            document_counts.c.attachments,
            document_counts.c.completed,
            document_counts.c.pending,
            document_counts.c.running,
            document_counts.c.blocked,
            document_counts.c.failed,
            overview_review.status.label("overview_review_status"),
        )
        .select_from(Notice)
        .outerjoin(connected_link, connected_link.c.notice_id == Notice.id)
        .outerjoin(selected_link, selected_link.id == connected_link.c.link_id)
        .outerjoin(selected_opportunity, selected_opportunity.id == selected_link.opportunity_id)
        .outerjoin(document_counts, document_counts.c.notice_id == Notice.id)
        # prespec_overview_review has a UNIQUE(notice_id) row per notice, so
        # this outer join can only add or drop columns — it never multiplies
        # or drops a Notice row, and the existing distinct-notice count/total
        # below stays correct.
        .outerjoin(overview_review, overview_review.notice_id == Notice.id)
        .where(*conditions)
    )
    count_query = query.with_only_columns(
        func.count(func.distinct(Notice.id)),
        maintain_column_froms=True,
    ).order_by(None)
    total = int(session.scalar(count_query) or 0)

    # Group counts over the *entire* filtered set (not the returned page) so
    # the list screen can show all-groups-always-visible collapsible sections
    # with correct counts without an N+1 per-row lookup (docs/design/PLAN.md
    # 3단계 결정 (a)/(b); see docs/tracking/decisions and the PreSpecsPage
    # test suite for the rendered contract).
    status_count_query = query.with_only_columns(
        overview_review.status,
        func.count(func.distinct(Notice.id)),
        maintain_column_froms=True,
    ).group_by(overview_review.status).order_by(None)
    status_counts_by_value: dict[str | None, int] = {
        row[0]: int(row[1] or 0) for row in session.execute(status_count_query).all()
    }
    overview_status_counts = [
        PreSpecOverviewStatusCount(status=status, count=status_counts_by_value.get(status, 0))
        for status in get_args(PreSpecOverviewReviewStatus)
    ]
    overview_status_counts.append(
        PreSpecOverviewStatusCount(status=None, count=status_counts_by_value.get(None, 0))
    )

    if sort == "deadline":
        query = query.order_by(Notice.deadline_at.asc().nulls_last(), Notice.id.asc())
    else:
        query = query.order_by(Notice.published_at.desc().nulls_last(), Notice.id.desc())
    rows = session.execute(query.offset(offset).limit(limit)).all()

    items: list[PreSpecListItem] = []
    for row in rows:
        mapping = row._mapping
        notice: Notice = mapping[Notice]
        first_stage = mapping["first_registered_stage"]
        if first_stage == "order_plan":
            origin_value = "추적"
        elif first_stage in {"pre_spec", "bid_notice"}:
            origin_value = "신규"
        else:
            origin_value = None
        items.append(
            PreSpecListItem(
                notice_pk=notice.id,
                pre_spec_no=_pre_spec_number(notice),
                title=notice.title,
                agency=notice.agency,
                published_at=notice.published_at,
                deadline_at=notice.deadline_at,
                budget=decimal_float(notice.budget),
                sw_business_status=_qualification_value(notice, "sw_business_status"),
                business_division=_qualification_value(notice, "business_division"),
                origin=origin_value,
                opportunity_id=mapping["opportunity_id"],
                tracking_status=mapping["tracking_status"],
                kept_by_tracking=bool(mapping["kept_by_tracking"]),
                overview_review_status=mapping["overview_review_status"],
                document=PreSpecDocumentSummary(
                    attachments=_count(mapping["attachments"]),
                    completed=_count(mapping["completed"]),
                    pending=_count(mapping["pending"]),
                    running=_count(mapping["running"]),
                    blocked=_count(mapping["blocked"]),
                    failed=_count(mapping["failed"]),
                ),
            )
        )
    return PreSpecListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        overview_status_counts=overview_status_counts,
    )


__all__ = ["router"]
