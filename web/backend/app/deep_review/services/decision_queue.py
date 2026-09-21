"""Cumulative final-decision queue and its workload count share one population."""
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...lifecycle import active_opportunity_predicate, authoritative_link_predicate
from ...lifecycle.models import Notice, Opportunity, OpportunityLink, OrderPlan
from ..models import BidDeltaComparison, BidFinalDecision
from .bid_delta_currentness import decision_currentness


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


def decision_queue(session: Session, *, status: str = "pending", limit: int = 50, offset: int = 0) -> dict:
    opportunities = session.scalars(select(Opportunity).where(
        active_opportunity_predicate(), Opportunity.tracking_status == "계속 추적"
    ).order_by(Opportunity.created_at.desc(), Opportunity.id.desc())).all()
    ids = [row.id for row in opportunities]
    if not ids:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

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

    items = []
    for opportunity in opportunities:
        linked = records[opportunity.id]
        bids = [notice for notice, _plan in linked if notice is not None and notice.source_type == "bid_notice"]
        # This selects display metadata only; unknown dates remain unknown and do
        # not authorize a comparison or determine currentness.
        bid = max(bids, key=lambda n: (
            n.published_at is not None,
            n.published_at.replace(tzinfo=UTC) if n.published_at is not None and n.published_at.tzinfo is None else n.published_at,
            n.id,
        )) if bids else None
        record = bid or next((notice if notice is not None else plan for notice, plan in linked if notice is not None or plan is not None), None)
        decision = decisions.get(opportunity.id)
        state = currentness[decision.id][0] if decision is not None else "unknown"
        if status == "pending" and (bid is None or (decision is not None and state != "stale")):
            continue
        items.append({"opportunity_id": opportunity.id,
            "title": record.title if record is not None else None,
            "agency": (record.agency if isinstance(record, Notice) else record.agency_name) if record is not None else None,
            "tracking_status": opportunity.tracking_status,
            "first_registered_stage": opportunity.first_registered_stage,
            "recheck_signal": opportunity.recheck_signal_at is not None,
            "bid_notice_external_id": bid.notice_key if bid is not None else None,
            "comparison_count": int(comparison_counts.get(opportunity.id, 0)),
            "latest_final_decision": {"decision": decision.decision, "decided_at": decision.created_at,
                "claimed_name": decision.claimed_name} if decision is not None else None,
            "decision_currentness": state,
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
    return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}
