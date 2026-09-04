"""Cumulative pre-specification discovery list."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, get_args

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from ...core.db import get_db
from .. import PreSpecDocumentCounts, extension_registry
from ..models import Attachment, Notice, Opportunity, OpportunityLink
from ..schemas.pre_specs import (
    PreSpecDocumentSummary,
    PreSpecListItem,
    PreSpecListResponse,
    PreSpecOverviewStatusCount,
    PreSpecOverviewReviewStatus,
    PreSpecOrigin,
    PreSpecSort,
)
from ..services.opportunity_connections import tracked_order_plan_connection_predicate
from ..services.opportunity_integrity import (
    active_opportunity_predicate,
    authoritative_link_predicate,
)
from .common import decimal_float


router = APIRouter(prefix="/api/pre-specs", tags=["pre-specs"])


def _attachment_counts_subquery():
    """공고별 현재 첨부 수. lifecycle이 자기 `attachment` 테이블에서 직접 센다.

    취득 상태 건수(완료·대기·진행·차단·실패)는 개요·문서 projection(명세 §6.1)이
    공고 id 집합을 받아 채운다.
    """

    return (
        select(
            Attachment.notice_id.label("notice_id"),
            func.count(Attachment.id).label("attachments"),
        )
        .where(Attachment.retired_at.is_(None))
        .group_by(Attachment.notice_id)
        .subquery("pre_spec_attachment_counts")
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

    projection = extension_registry().overview_document_projection
    connected_link = _connected_link_subquery()
    selected_link = aliased(OpportunityLink, name="pre_spec_selected_link")
    selected_opportunity = aliased(Opportunity, name="pre_spec_selected_opportunity")
    attachment_counts = _attachment_counts_subquery()
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

    query = (
        select(
            Notice,
            selected_opportunity.id.label("opportunity_id"),
            selected_opportunity.tracking_status.label("tracking_status"),
            selected_opportunity.first_registered_stage.label("first_registered_stage"),
            kept_by_tracking.label("kept_by_tracking"),
            attachment_counts.c.attachments,
        )
        .select_from(Notice)
        .outerjoin(connected_link, connected_link.c.notice_id == Notice.id)
        .outerjoin(selected_link, selected_link.id == connected_link.c.link_id)
        .outerjoin(selected_opportunity, selected_opportunity.id == selected_link.opportunity_id)
        .outerjoin(attachment_counts, attachment_counts.c.notice_id == Notice.id)
        .where(*conditions)
    )

    # 필터 전체의 공고 id 집합 하나로 `total`과 그룹 건수를 모두 낸다. 그룹
    # 건수는 반환 페이지가 아니라 필터 전체를 설명해야 하므로(docs/design/PLAN.md
    # 3단계 결정 (a)/(b)) projection에 전체 집합을 넘긴다. 공고당 조회는 없다.
    filtered_ids = [
        int(value)
        for value in session.scalars(
            query.with_only_columns(Notice.id, maintain_column_froms=True)
            .distinct()
            .order_by(None)
        ).all()
    ]
    total = len(filtered_ids)

    status_counts = projection.overview_status_counts(session, filtered_ids)
    overview_status_counts: list[PreSpecOverviewStatusCount] = []
    counted = 0
    for status in get_args(PreSpecOverviewReviewStatus):
        count = int(status_counts.get(status, 0))
        counted += count
        overview_status_counts.append(PreSpecOverviewStatusCount(status=status, count=count))
    # 개요 검토 행이 없는 공고(미시작)는 열한 번째 bucket이다. 제공자가 없으면
    # 전체가 여기 들어간다. 제공자가 전체보다 많이 세면 응답 계약(ge=0)을 지키려
    # 0으로 막는다 — 그런 제공자는 자기 테스트에서 잡혀야 한다.
    overview_status_counts.append(
        PreSpecOverviewStatusCount(status=None, count=max(total - counted, 0))
    )

    if sort == "deadline":
        query = query.order_by(Notice.deadline_at.asc().nulls_last(), Notice.id.asc())
    else:
        query = query.order_by(Notice.published_at.desc().nulls_last(), Notice.id.desc())
    rows = session.execute(query.offset(offset).limit(limit)).all()

    page_ids = [int(row._mapping[Notice].id) for row in rows]
    overview_status = projection.overview_status(session, page_ids)
    document_counts = projection.document_counts(session, page_ids)
    absent_counts = PreSpecDocumentCounts()

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
        counts = document_counts.get(notice.id, absent_counts)
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
                overview_review_status=overview_status.get(notice.id),
                document=PreSpecDocumentSummary(
                    attachments=_count(mapping["attachments"]),
                    completed=counts.completed,
                    pending=counts.pending,
                    running=counts.running,
                    blocked=counts.blocked,
                    failed=counts.failed,
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
