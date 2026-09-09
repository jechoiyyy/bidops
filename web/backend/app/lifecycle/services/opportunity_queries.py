"""사업기회 구역·페이지 집계와 안전한 감사 이력 projection."""
from __future__ import annotations

from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ...core.models import AuditEvent
from ..extensions import extension_registry
from ..models import Opportunity, OpportunityLink
from ..schemas.opportunities import (
    OpportunityDetailResponse,
    OpportunityFirstRegisteredStage,
    OpportunityLinkView,
    OpportunityListItem,
    OpportunityListResponse,
    OpportunitySection,
    OpportunitySort,
    OpportunityTrackingDecisionsResponse,
    OpportunityTrackingDecisionView,
    OpportunityTrackingStatus,
)
from .opportunity_integrity import active_opportunity_predicate
from .opportunity_tracking import HUMAN_TRACKING_ACTION, OpportunityTrackingError

_TRACKING_STATUS_ORDER = ("미선택", "계속 추적", "보류", "종료")
_FIRST_STAGE_ORDER = ("order_plan", "pre_spec", "bid_notice")
_SECTION_KEYS = ("조치 필요", "추적 중", "보류", "추적 종료", "미결정")


def _strategy_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    allowed = {"full", "breaking_split", "normalized", "longest_fragment", "prefix12"}
    return [item for item in value if isinstance(item, str) and item in allowed]


def link_view(link: OpportunityLink) -> OpportunityLinkView:
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
        link_view(link)
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
        "merged_into_opportunity_id": opportunity.merged_into_opportunity_id,
        "merged_at": opportunity.merged_at,
        "merge_reason": opportunity.merge_reason,
    }


def _link_options():
    # 기회 페이지(limit <= 500)를 먼저 자른 뒤 링크를 한 번에 읽는다.
    # scalar 대상은 같은 조회에 합쳐, 연결 공고 수가 500을 넘어도 조회가 늘지 않는다.
    return (
        selectinload(Opportunity.links).joinedload(OpportunityLink.notice),
        selectinload(Opportunity.links).joinedload(OpportunityLink.order_plan),
    )


def _pending_candidate_count():
    return (
        select(func.count(OpportunityLink.id))
        .where(
            OpportunityLink.opportunity_id == Opportunity.id,
            OpportunityLink.link_type == "candidate",
            OpportunityLink.status == "후보 확인 대기",
        )
        .correlate(Opportunity)
        .scalar_subquery()
    )


def _section_expression(session: Session):
    blocking_notice_ids = extension_registry().notice_ids_with_open_blocking_items(session)
    has_blocking = (
        select(OpportunityLink.id)
        .where(
            OpportunityLink.opportunity_id == Opportunity.id,
            OpportunityLink.notice_id.in_(blocking_notice_ids),
        )
        .correlate(Opportunity)
        .exists()
    )
    needs_action = or_(
        and_(
            Opportunity.tracking_status == "미선택",
            Opportunity.first_registered_stage == "bid_notice",
        ),
        Opportunity.recheck_signal_at.is_not(None),
        _pending_candidate_count() > 0,
        has_blocking,
    )
    # 첫 일치가 이긴다. 구역과 사람의 추적 선택은 서로 다른 축이다.
    return case(
        (needs_action, '조치 필요'),
        (Opportunity.tracking_status == '보류', '보류'),
        (Opportunity.tracking_status == '종료', '추적 종료'),
        (Opportunity.tracking_status == '계속 추적', '추적 중'),
        else_=None,
    )


def count_opportunity_section(session: Session, section: OpportunitySection) -> int:
    """목록과 같은 첫 일치 규칙으로 활성 사업기회 구역을 집계한다."""
    return int(session.scalar(
        select(func.count(Opportunity.id)).where(
            active_opportunity_predicate(Opportunity),
            _section_expression(session) == section,
        )
    ))


def _page_blocking_counts(session: Session, opportunities: list[Opportunity]) -> dict[int, int]:
    # 이 값은 소유권이 아니라 기존 상세의 전체 링크를 통한 확인 항목 범위다.
    # 같은 공고의 연결 이력이 여러 번 있어도 확인 항목은 한 번만 센다.
    linked_ids = {
        opportunity.id: {link.notice_id for link in opportunity.links if link.notice_id is not None}
        for opportunity in opportunities
    }
    notice_ids = sorted({pk for ids in linked_ids.values() for pk in ids})
    counts = extension_registry().open_blocking_item_counts(session, notice_ids)
    return {pk: sum(counts.get(notice_id, 0) for notice_id in ids) for pk, ids in linked_ids.items()}


def list_opportunities(
    session: Session,
    *,
    tracking_status: OpportunityTrackingStatus | None = None,
    first_registered_stage: OpportunityFirstRegisteredStage | None = None,
    section: OpportunitySection | None = None,
    sort: OpportunitySort = "created_at",
    limit: int = 50,
    offset: int = 0,
) -> OpportunityListResponse:
    conditions = [active_opportunity_predicate(Opportunity)]
    if tracking_status is not None:
        conditions.append(Opportunity.tracking_status == tracking_status)
    if first_registered_stage is not None:
        conditions.append(Opportunity.first_registered_stage == first_registered_stage)
    section_expression = _section_expression(session)
    grouped = session.execute(
        select(section_expression, func.count(Opportunity.id))
        .where(*conditions).group_by(section_expression)
    ).all()
    section_counts = dict.fromkeys(_SECTION_KEYS, 0)
    for label, count in grouped:
        section_counts[label if label is not None else '미결정'] = int(count)
    total = section_counts[section] if section is not None else sum(section_counts.values())
    if section is not None:
        conditions.append(section_expression == section)
    query = (
        select(Opportunity, section_expression, _pending_candidate_count())
        .where(*conditions)
        .options(*_link_options())
    )
    if sort == 'tracking_status':
        rank = case(
            *[(Opportunity.tracking_status == value, index) for index, value in enumerate(_TRACKING_STATUS_ORDER)],
            else_=len(_TRACKING_STATUS_ORDER),
        )
        query = query.order_by(rank.asc(), Opportunity.created_at.desc(), Opportunity.id.desc())
    elif sort == 'first_registered_stage':
        rank = case(
            *[(Opportunity.first_registered_stage == value, index) for index, value in enumerate(_FIRST_STAGE_ORDER)],
            else_=len(_FIRST_STAGE_ORDER),
        )
        query = query.order_by(rank.asc(), Opportunity.created_at.desc(), Opportunity.id.desc())
    else:
        query = query.order_by(Opportunity.created_at.desc(), Opportunity.id.desc())
    rows = session.execute(query.offset(offset).limit(limit)).all()
    blocking_counts = _page_blocking_counts(session, [row[0] for row in rows])
    return OpportunityListResponse(
        items=[
            OpportunityListItem(
                **_opportunity_state(opportunity),
                links=_links_for(opportunity),
                section=label,
                pending_candidate_link_count=pending,
                open_blocking_item_count=blocking_counts[opportunity.id],
            )
            for opportunity, label, pending in rows
        ],
        section_counts=section_counts,
        total=total,
        limit=limit,
        offset=offset,
    )


def get_opportunity(session: Session, opportunity_id: int) -> OpportunityDetailResponse:
    row = session.execute(
        select(Opportunity, _section_expression(session), _pending_candidate_count())
        .where(Opportunity.id == opportunity_id).options(*_link_options())
    ).first()
    if row is None:
        raise OpportunityTrackingError('opportunity_not_found', '사업기회를 찾을 수 없습니다')
    opportunity, label, pending = row
    counts = _page_blocking_counts(session, [opportunity])
    return OpportunityDetailResponse(
        **_opportunity_state(opportunity),
        links=_links_for(opportunity),
        section=label,
        pending_candidate_link_count=pending,
        open_blocking_item_count=counts[opportunity.id],
    )


def tracking_decisions(session: Session, opportunity_id: int) -> OpportunityTrackingDecisionsResponse:
    if session.get(Opportunity, opportunity_id) is None:
        raise OpportunityTrackingError('opportunity_not_found', '사업기회를 찾을 수 없습니다')
    audits = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action == HUMAN_TRACKING_ACTION,
            AuditEvent.aggregate_type == "opportunity",
            AuditEvent.aggregate_id == str(opportunity_id),
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    ).all()
    items = []
    for audit in audits:
        metadata = audit.safe_metadata
        items.append(
            OpportunityTrackingDecisionView(
                decided_at=audit.created_at,
                tracking_status=metadata["tracking_status"],
                previous_tracking_status=metadata.get("previous_tracking_status"),
                reason=metadata.get("reason"),
                claimed_name=audit.claimed_name,
                audit_event_id=audit.id,
                cleared_recheck_signal=metadata.get("cleared_recheck_signal_link_id") is not None,
            )
        )
    return OpportunityTrackingDecisionsResponse(opportunity_id=opportunity_id, items=items)
