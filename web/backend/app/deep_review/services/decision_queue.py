"""Cumulative final-decision queue and its workload count share one population."""
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.search import search_match
from ...lifecycle import active_opportunity_predicate, authoritative_link_predicate
from ...lifecycle.models import Notice, Opportunity, OpportunityLink, OrderPlan
from ..models import BidDeltaComparison, BidFinalDecision
from .bid_delta_currentness import decision_currentness, latest_bid_notice, latest_observation_hashes


def _review_state(*, has_decision: bool, state: str, bid_reason: str | None, has_observation: bool) -> tuple[str, str | None]:
    if bid_reason == "bid_notice_missing" and not has_decision:
        return "waiting_notice", None
    if bid_reason is not None:
        return "notice_check", bid_reason
    if has_decision and state == "current":
        return "decided", None
    if not has_observation:
        return "notice_check", "observation_unknown"
    if not has_decision:
        return "undecided", None
    if state == "stale":
        return "recheck", None
    return "notice_check", "decision_currentness_unknown"


def _amount(value: Decimal | None) -> str | None:
    """Keep the exact stored magnitude; never a float-rounded amount."""

    if value is None:
        return None
    return format(value.normalize(), "f")


def _deadline_sort_key(value: datetime | None) -> tuple[int, datetime]:
    """Ascending deadline, unknown deadlines last (spec §5)."""

    if value is None:
        return (1, datetime.max.replace(tzinfo=UTC))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return (0, value)


def decision_queue(
    session: Session, *, status: str = "pending", limit: int = 50, offset: int = 0, q: str | None = None,
) -> dict:
    view_counts = dict.fromkeys(("pending", "recheck", "notice_check", "decided", "all"), 0)
    opportunities = session.scalars(select(Opportunity).where(
        active_opportunity_predicate(), Opportunity.tracking_status == "계속 추적"
    ).order_by(Opportunity.created_at.desc(), Opportunity.id.desc())).all()
    ids = [row.id for row in opportunities]
    if not ids:
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "view_counts": view_counts}

    latest_sequence = select(BidFinalDecision.opportunity_id, func.max(BidFinalDecision.sequence).label("sequence")).where(
        BidFinalDecision.opportunity_id.in_(ids)
    ).group_by(BidFinalDecision.opportunity_id).subquery()
    decisions = {}
    comparisons = []
    # A notice-conditions decision has no comparison (ADR-0058); an inner join
    # would drop it and leave a decided opportunity in the pending queue.
    for decision, comparison in session.execute(select(BidFinalDecision, BidDeltaComparison)
        .join(latest_sequence, (latest_sequence.c.opportunity_id == BidFinalDecision.opportunity_id)
            & (latest_sequence.c.sequence == BidFinalDecision.sequence))
        .outerjoin(BidDeltaComparison, BidDeltaComparison.id == BidFinalDecision.comparison_id)).all():
        decisions[decision.opportunity_id] = decision
        if comparison is not None:
            comparisons.append(comparison)
    currentness = decision_currentness(session, ids, list(decisions.values()), comparisons=comparisons)
    comparison_counts = dict(session.execute(select(BidDeltaComparison.opportunity_id, func.count())
        .where(BidDeltaComparison.opportunity_id.in_(ids)).group_by(BidDeltaComparison.opportunity_id)).all())

    records = defaultdict(list)
    for link, notice, plan in session.execute(select(OpportunityLink, Notice, OrderPlan)
        .outerjoin(Notice, Notice.id == OpportunityLink.notice_id)
        .outerjoin(OrderPlan, OrderPlan.id == OpportunityLink.order_plan_id)
        .where(OpportunityLink.opportunity_id.in_(ids), authoritative_link_predicate())
        .order_by(OpportunityLink.id.desc())).all():
        records[link.opportunity_id].append((notice, plan))

    latest_bids = {
        owner_id: latest_bid_notice(list({notice.id: notice for notice, _ in linked
            if notice is not None and notice.source_type == "bid_notice"}.values()))
        for owner_id, linked in records.items()
    }
    hashes = latest_observation_hashes(session, [bid.id for bid, _ in latest_bids.values() if bid is not None])
    items = []
    for opportunity in opportunities:
        linked = records[opportunity.id]
        bid, bid_reason = latest_bids.get(opportunity.id, (None, "bid_notice_missing"))
        record = bid or next((notice if notice is not None else plan for notice, plan in linked if notice is not None or plan is not None), None)
        title = record.title if record is not None else None
        agency = (record.agency if isinstance(record, Notice) else record.agency_name) if record is not None else None
        if q and not search_match(q, title, agency):
            continue
        decision = decisions.get(opportunity.id)
        state = currentness[decision.id][0] if decision is not None else "unknown"
        review_state, notice_check_reason = _review_state(
            has_decision=decision is not None, state=state, bid_reason=bid_reason,
            has_observation=bid is not None and bool(hashes.get(bid.id)),
        )
        views = ["all"]
        if review_state in {"undecided", "recheck", "notice_check"}:
            views.append("pending")
        if review_state in {"recheck", "notice_check"}:
            views.append(review_state)
        if decision is not None:
            views.append("decided")
        for view in views:
            view_counts[view] += 1
        if status not in views:
            continue
        items.append({"opportunity_id": opportunity.id,
            "title": title, "agency": agency,
            "tracking_status": opportunity.tracking_status,
            "first_registered_stage": opportunity.first_registered_stage,
            "recheck_signal": opportunity.recheck_signal_at is not None,
            "bid_notice_external_id": bid.notice_key if bid is not None else None,
            "comparison_count": int(comparison_counts.get(opportunity.id, 0)),
            "latest_final_decision": {"decision": decision.decision, "decided_at": decision.created_at,
                "claimed_name": decision.claimed_name} if decision is not None else None,
            "decision_currentness": state,
            "review_state": review_state, "notice_check_reason": notice_check_reason,
            # Selected bid notice's own columns only (spec §5); no order plan
            # or pre-spec fallback, and no value when no bid notice is chosen.
            "deadline_at": bid.deadline_at if bid is not None else None,
            "budget": _amount(bid.budget) if bid is not None else None,
            "estimated_price": _amount(bid.estimated_price) if bid is not None else None})
    # Primary key: nearest bid-notice deadline first, unknown deadlines last.
    # Secondary key: the prior rule (undecided opportunities first), which also
    # preserves recent registration order within each deadline+decision group
    # because Python's sort is stable and opportunities were queried in that
    # order.
    items.sort(key=lambda row: (
        _deadline_sort_key(row["deadline_at"]),
        row["latest_final_decision"] is not None,
    ))
    return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset,
        "view_counts": view_counts}
