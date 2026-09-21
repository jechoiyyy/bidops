"""사업기회 구역·조치 사유·보류 기한·페이지 집계와 안전한 감사 이력 projection.

구역과 사유는 한 SQL 식(:func:`_classified`)으로 계산하고 목록·구역 집계·workload가
같은 식을 쓴다(spec §7). 기준 시각 ``now``는 Python에서 timezone-aware UTC로 정하고,
보류 기한 비교는 ``tracking_selected_at``과 ``now - 14일``을 bound parameter로 대조해
dialect별 날짜 산술 없이 마이크로초까지 같은 결과를 낸다.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from ...core.models import AuditEvent
from ...core.search import search_key, search_sql_match, validation_value
from ..extensions import extension_registry
from ..models import Notice, Opportunity, OpportunityLink, OrderPlan
from ..schemas.opportunities import (
    OpportunityActionReason,
    OpportunityDetailResponse,
    OpportunityFirstRegisteredStage,
    OpportunityHoldReview,
    OpportunityLinkView,
    OpportunityListItem,
    OpportunityListResponse,
    OpportunityRecheckEventView,
    OpportunitySection,
    OpportunitySort,
    OpportunityTrackingDecisionsResponse,
    OpportunityTrackingDecisionView,
    OpportunityTrackingStatus,
)
from .opportunity_integrity import (
    MERGE_CONFIRMATION_STRATEGY,
    active_opportunity_predicate,
    authoritative_link_predicate,
)
from .opportunity_tracking import (
    ACKNOWLEDGED_RECHECK_ACTION,
    HUMAN_TRACKING_ACTION,
    SYSTEM_RECHECK_ACTION,
    OpportunityTrackingError,
)

#: 보류 재검토 기한(일). 보류를 다시 저장하면 ``tracking_selected_at``이 바뀌어 새로 시작한다.
HOLD_REVIEW_PERIOD_DAYS = 14
#: ``hold_review=due_soon``의 창(일): ``now < 기한 ≤ now + 3일``.
HOLD_REVIEW_DUE_SOON_DAYS = 3
#: §7.1 표 순서. ``action_reasons``와 ``action_reason_counts``가 이 순서를 따른다.
ACTION_REASON_CODES: tuple[OpportunityActionReason, ...] = (
    "new_link",
    "candidate_pending",
    "merge_confirmation",
    "blocking_item",
    "hold_overdue",
)
SEARCH_QUERY_MIN_LENGTH = 2
SEARCH_QUERY_MAX_LENGTH = 100

_TRACKING_STATUS_ORDER = ("미선택", "계속 추적", "보류", "종료")
_FIRST_STAGE_ORDER = ("order_plan", "pre_spec", "bid_notice")
_SECTION_KEYS = ("조치 필요", "추적 중", "보류", "추적 종료", "신규 입찰공고", "미결정")
_OPEN_TRACKING_STATUSES = ("계속 추적", "보류")
_LINK_REASONS = ("new_link", "candidate_pending", "merge_confirmation")
#: ``q`` 비교에서 지우는 공백 문자. DB 쪽은 이 문자만 지우고 질의는 Python 공백 전체를 지운다.


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
        search_target_kind=link.search_target_kind,
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


def reference_time(now: datetime | None = None) -> datetime:
    """The request's timezone-aware UTC clock value."""

    value = datetime.now(UTC) if now is None else now
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("reference time must be timezone-aware")
    return value.astimezone(UTC)


def hold_review_due_at(opportunity: Opportunity) -> datetime | None:
    """``tracking_selected_at + 14일`` for a held opportunity, otherwise ``None``."""

    if opportunity.tracking_status != "보류" or opportunity.tracking_selected_at is None:
        return None
    return opportunity.tracking_selected_at.astimezone(UTC) + timedelta(
        days=HOLD_REVIEW_PERIOD_DAYS
    )


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
        "hold_review_due_at": hold_review_due_at(opportunity),
    }


def _link_options():
    # 기회 페이지(limit <= 500)를 먼저 자른 뒤 링크를 한 번에 읽는다.
    # scalar 대상은 같은 조회에 합쳐, 연결 공고 수가 500을 넘어도 조회가 늘지 않는다.
    return (
        selectinload(Opportunity.links).joinedload(OpportunityLink.notice),
        selectinload(Opportunity.links).joinedload(OpportunityLink.order_plan),
    )


def actionable_pending_candidate_predicate(candidate: Any) -> ColumnElement[bool]:
    """A ``후보 확인 대기`` candidate whose target its owner does not already own.

    A later official link or automatic merge can give the owner the very
    record a pending candidate proposes; that stale row asks nothing and is
    not counted (spec §7.1, P2b open risk).  ``candidate`` is the link alias
    the caller's statement selects from.
    """

    owned = aliased(OpportunityLink, name="owned_candidate_target")
    already_owned = (
        select(owned.id)
        .where(
            owned.opportunity_id == candidate.opportunity_id,
            owned.id != candidate.id,
            authoritative_link_predicate(owned),
            or_(
                and_(candidate.notice_id.is_not(None), owned.notice_id == candidate.notice_id),
                and_(
                    candidate.order_plan_id.is_not(None),
                    owned.order_plan_id == candidate.order_plan_id,
                ),
            ),
        )
        .correlate(candidate)
        .exists()
    )
    return and_(
        candidate.link_type == "candidate",
        candidate.status == "후보 확인 대기",
        ~already_owned,
    )


def _pending_candidates(merge_confirmation: bool | None = None):
    candidate = aliased(OpportunityLink, name="pending_candidate")
    conditions = [
        candidate.opportunity_id == Opportunity.id,
        actionable_pending_candidate_predicate(candidate),
    ]
    strategy = func.coalesce(candidate.search_strategy, "")
    if merge_confirmation is True:
        conditions.append(strategy == MERGE_CONFIRMATION_STRATEGY)
    elif merge_confirmation is False:
        conditions.append(strategy != MERGE_CONFIRMATION_STRATEGY)
    return candidate, conditions


def _pending_candidate_count():
    candidate, conditions = _pending_candidates()
    return (
        select(func.count(candidate.id))
        .where(*conditions)
        .correlate(Opportunity)
        .scalar_subquery()
    )


def _pending_candidate_exists(*, merge_confirmation: bool) -> ColumnElement[bool]:
    candidate, conditions = _pending_candidates(merge_confirmation)
    return select(candidate.id).where(*conditions).correlate(Opportunity).exists()


def hold_review_predicate(
    kind: OpportunityHoldReview,
    now: datetime,
) -> ColumnElement[bool]:
    """보류 기한 조건. ``기한 ≤ now``는 ``tracking_selected_at ≤ now - 14일``이다."""

    reference = reference_time(now)
    overdue_cutoff = reference - timedelta(days=HOLD_REVIEW_PERIOD_DAYS)
    due_soon_cutoff = overdue_cutoff + timedelta(days=HOLD_REVIEW_DUE_SOON_DAYS)
    held = and_(
        Opportunity.tracking_status == "보류",
        Opportunity.tracking_selected_at.is_not(None),
    )
    if kind == "overdue":
        return and_(held, Opportunity.tracking_selected_at <= overdue_cutoff)
    if kind == "due_soon":
        return and_(
            held,
            Opportunity.tracking_selected_at > overdue_cutoff,
            Opportunity.tracking_selected_at <= due_soon_cutoff,
        )
    if kind == "attention":
        return and_(held, Opportunity.tracking_selected_at <= due_soon_cutoff)
    raise ValueError(f"unknown hold review filter: {kind}")


def normalize_search_query(q: str) -> str:
    """Validate the raw query without changing what is sent or displayed."""

    collapsed = validation_value(q) if isinstance(q, str) else ""
    if not search_key(q):
        return q
    if not SEARCH_QUERY_MIN_LENGTH <= len(collapsed) <= SEARCH_QUERY_MAX_LENGTH:
        raise OpportunityTrackingError(
            "invalid_request", "검색어는 공백을 정리한 뒤 2~100자여야 합니다"
        )
    return q


def _search_predicate(q: str) -> ColumnElement[bool]:
    """Whitespace- and case-insensitive substring match on owned records (§7.5).

    Only authoritative links count; pending or rejected candidate targets are
    not searched.  Whitespace is removed on both sides, which keeps SQLite and
    PostgreSQL identical without dialect regular expressions.
    """

    normalize_search_query(q)
    link = aliased(OpportunityLink, name="searched_link")
    plan = aliased(OrderPlan, name="searched_order_plan")
    notice = aliased(Notice, name="searched_notice")
    columns = (plan.title, plan.agency_name, notice.title, notice.agency, notice.demand_agency)
    return (
        select(link.id)
        .outerjoin(plan, plan.id == link.order_plan_id)
        .outerjoin(notice, notice.id == link.notice_id)
        .where(
            link.opportunity_id == Opportunity.id,
            authoritative_link_predicate(link),
            or_(*(search_sql_match(column, q) for column in columns)),
        )
        .correlate(Opportunity)
        .exists()
    )


def _reason_column(code: str) -> str:
    return f"reason_{code}"


def _classified(
    session: Session,
    *,
    now: datetime,
    conditions: list[ColumnElement[bool]],
) -> Subquery:
    """The one section/reason classification shared by list, counts and workload.

    Each reason is evaluated once per row in an inner subquery as an integer
    flag; the section is a first-match CASE over those flags (spec §7.2).
    """

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
    reasons: dict[str, ColumnElement[bool]] = {
        "new_link": Opportunity.recheck_signal_at.is_not(None),
        "candidate_pending": _pending_candidate_exists(merge_confirmation=False),
        "merge_confirmation": _pending_candidate_exists(merge_confirmation=True),
        "blocking_item": has_blocking,
        "hold_overdue": hold_review_predicate("overdue", now),
    }
    flagged = (
        select(
            Opportunity.id.label("id"),
            Opportunity.tracking_status.label("tracking_status"),
            Opportunity.first_registered_stage.label("first_registered_stage"),
            _pending_candidate_count().label("pending_candidate_link_count"),
            *(
                case((reasons[code], 1), else_=0).label(_reason_column(code))
                for code in ACTION_REASON_CODES
            ),
        )
        .where(*conditions)
        .subquery("opportunity_flags")
    )
    has = {code: flagged.c[_reason_column(code)] == 1 for code in ACTION_REASON_CODES}
    status = flagged.c.tracking_status
    # 첫 일치가 이긴다. 구역과 사람의 추적 선택은 서로 다른 축이며, 미선택은
    # 사유가 있어도 조치 필요로 올라오지 않는다(결정 6).
    section = case(
        (
            or_(
                and_(status.in_(_OPEN_TRACKING_STATUSES), or_(*has.values())),
                and_(status == "종료", or_(*(has[code] for code in _LINK_REASONS))),
            ),
            "조치 필요",
        ),
        (status == "보류", "보류"),
        (status == "종료", "추적 종료"),
        (status == "계속 추적", "추적 중"),
        (
            and_(status == "미선택", flagged.c.first_registered_stage == "bid_notice"),
            "신규 입찰공고",
        ),
        else_=None,
    )
    return select(
        flagged.c.id,
        section.label("section"),
        flagged.c.pending_candidate_link_count,
        *(flagged.c[_reason_column(code)] for code in ACTION_REASON_CODES),
    ).subquery("opportunity_classified")


def _reason_values(classified: Subquery) -> list[Any]:
    return [classified.c[_reason_column(code)] for code in ACTION_REASON_CODES]


def _present_reasons(flags: Any) -> list[OpportunityActionReason]:
    return [code for code, flag in zip(ACTION_REASON_CODES, flags) if flag]


def count_opportunity_section(
    session: Session,
    section: OpportunitySection,
    *,
    now: datetime | None = None,
) -> int:
    """목록과 같은 첫 일치 규칙으로 활성 사업기회 구역을 집계한다."""

    classified = _classified(
        session,
        now=reference_time(now),
        conditions=[active_opportunity_predicate(Opportunity)],
    )
    return int(
        session.scalar(
            select(func.count()).select_from(classified).where(classified.c.section == section)
        )
    )


def count_hold_review(
    session: Session,
    kind: OpportunityHoldReview,
    *,
    now: datetime | None = None,
) -> int:
    """목록 ``hold_review`` 필터와 같은 조건으로 활성 사업기회를 센다."""

    return int(
        session.scalar(
            select(func.count(Opportunity.id)).where(
                active_opportunity_predicate(Opportunity),
                hold_review_predicate(kind, reference_time(now)),
            )
        )
    )


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
    reason: OpportunityActionReason | None = None,
    hold_review: OpportunityHoldReview | None = None,
    q: str | None = None,
    sort: OpportunitySort = "created_at",
    limit: int = 50,
    offset: int = 0,
    now: datetime | None = None,
) -> OpportunityListResponse:
    """One page plus facet counts over the same classification.

    ``section_counts`` apply every active filter except ``section``;
    ``action_reason_counts`` apply every active filter except ``reason``;
    ``total`` applies all of them.  One grouped query yields all three.
    """

    reference = reference_time(now)
    conditions = [active_opportunity_predicate(Opportunity)]
    if tracking_status is not None:
        conditions.append(Opportunity.tracking_status == tracking_status)
    if first_registered_stage is not None:
        conditions.append(Opportunity.first_registered_stage == first_registered_stage)
    if hold_review is not None:
        conditions.append(hold_review_predicate(hold_review, reference))
    if q is not None and search_key(q):
        conditions.append(_search_predicate(q))
    classified = _classified(session, now=reference, conditions=conditions)
    reason_values = _reason_values(classified)
    grouped = session.execute(
        select(classified.c.section, *reason_values, func.count())
        .group_by(classified.c.section, *reason_values)
    ).all()
    section_counts = dict.fromkeys(_SECTION_KEYS, 0)
    action_reason_counts = dict.fromkeys(ACTION_REASON_CODES, 0)
    total = 0
    for label, *flags, raw_count in grouped:
        count = int(raw_count)
        key = label if label is not None else "미결정"
        present = _present_reasons(flags)
        matches_reason = reason is None or reason in present
        matches_section = section is None or key == section
        if matches_reason:
            section_counts[key] += count
        if matches_section:
            for code in present:
                action_reason_counts[code] += count
        if matches_reason and matches_section:
            total += count

    query = (
        select(
            Opportunity,
            classified.c.section,
            classified.c.pending_candidate_link_count,
            *reason_values,
        )
        .join(classified, classified.c.id == Opportunity.id)
        .options(*_link_options())
    )
    if section is not None:
        query = query.where(classified.c.section == section)
    if reason is not None:
        query = query.where(classified.c[_reason_column(reason)] == 1)
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
    elif sort == 'hold_review_due_at':
        # 기한은 선택 시각 + 상수라 선택 시각 순서가 곧 기한 순서다. null은 방언과
        # 무관하게 마지막에 둔다.
        due = case((Opportunity.tracking_status == '보류', Opportunity.tracking_selected_at), else_=None)
        query = query.order_by(
            case((due.is_(None), 1), else_=0).asc(),
            due.asc(),
            Opportunity.created_at.desc(),
            Opportunity.id.desc(),
        )
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
                action_reasons=_present_reasons(flags),
            )
            for opportunity, label, pending, *flags in rows
        ],
        section_counts=section_counts,
        action_reason_counts=action_reason_counts,
        total=total,
        limit=limit,
        offset=offset,
    )


def get_opportunity(
    session: Session,
    opportunity_id: int,
    *,
    now: datetime | None = None,
) -> OpportunityDetailResponse:
    classified = _classified(
        session,
        now=reference_time(now),
        conditions=[Opportunity.id == opportunity_id],
    )
    row = session.execute(
        select(
            Opportunity,
            classified.c.section,
            classified.c.pending_candidate_link_count,
            *_reason_values(classified),
        )
        .join(classified, classified.c.id == Opportunity.id)
        .options(*_link_options())
    ).first()
    if row is None:
        raise OpportunityTrackingError('opportunity_not_found', '사업기회를 찾을 수 없습니다')
    opportunity, label, pending, *flags = row
    counts = _page_blocking_counts(session, [opportunity])
    return OpportunityDetailResponse(
        **_opportunity_state(opportunity),
        links=_links_for(opportunity),
        section=label,
        pending_candidate_link_count=pending,
        open_blocking_item_count=counts[opportunity.id],
        action_reasons=_present_reasons(flags),
    )


def _metadata_link_id(metadata: dict[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return None


def tracking_decisions(session: Session, opportunity_id: int) -> OpportunityTrackingDecisionsResponse:
    """Human decision history and recheck-signal events from one audit query."""

    if session.get(Opportunity, opportunity_id) is None:
        raise OpportunityTrackingError('opportunity_not_found', '사업기회를 찾을 수 없습니다')
    audits = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action.in_(
                (HUMAN_TRACKING_ACTION, SYSTEM_RECHECK_ACTION, ACKNOWLEDGED_RECHECK_ACTION)
            ),
            AuditEvent.aggregate_type == "opportunity",
            AuditEvent.aggregate_id == str(opportunity_id),
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    ).all()
    items = []
    recheck_events = []
    for audit in audits:
        metadata = audit.safe_metadata if isinstance(audit.safe_metadata, dict) else {}
        if audit.action == HUMAN_TRACKING_ACTION:
            cleared_link_id = metadata.get("cleared_recheck_signal_link_id")
            items.append(
                OpportunityTrackingDecisionView(
                    decided_at=audit.created_at,
                    tracking_status=metadata["tracking_status"],
                    previous_tracking_status=metadata.get("previous_tracking_status"),
                    reason=metadata.get("reason"),
                    claimed_name=audit.claimed_name,
                    audit_event_id=audit.id,
                    cleared_recheck_signal=cleared_link_id is not None,
                )
            )
            if cleared_link_id is None:
                continue
            kind, link_id, note_present = (
                "cleared_by_decision",
                _metadata_link_id(metadata, "cleared_recheck_signal_link_id"),
                False,
            )
        elif audit.action == SYSTEM_RECHECK_ACTION:
            kind, link_id, note_present = "created", _metadata_link_id(metadata, "link_id"), False
        else:
            kind, link_id, note_present = (
                "acknowledged",
                _metadata_link_id(metadata, "link_id"),
                metadata.get("note_present") is True,
            )
        recheck_events.append(
            OpportunityRecheckEventView(
                kind=kind,
                link_id=link_id,
                actor_kind=audit.actor_kind,
                claimed_name=audit.claimed_name,
                created_at=audit.created_at,
                note_present=note_present,
            )
        )
    return OpportunityTrackingDecisionsResponse(
        opportunity_id=opportunity_id, items=items, recheck_events=recheck_events
    )
