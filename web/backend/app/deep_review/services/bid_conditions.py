"""Deterministic bid-notice condition summary for the final Go/No-Go (spec §9.1).

Every value comes from the collected notice columns and JSON that lifecycle
already stores. Nothing is inferred, no model is called, and lifecycle rows are
only read. ``null`` stays "not observed": a comparison with a missing side is
``unknown``, never ``unchanged``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...lifecycle import authoritative_link_predicate
from ...lifecycle.models import Notice, OpportunityLink
from ..schemas.bid_delta import BidConditionsView
from .bid_delta import BidDeltaService
from .bid_delta_currentness import authoritative_bid_notices, latest_observation_hashes

#: Response order of ``conditions`` and of each ``changes_from_previous`` list.
CONDITION_FIELDS = (
    "budget",
    "estimated_price",
    "deadline_at",
    "opening_at",
    "method",
    "participation_limited",
    "industry_limited",
    "sw_industry_1468",
    "joint_contract_method",
    "successful_bid_method",
    "technical_evaluation_rate",
    "region_limit_basis",
    "joint_contract_regions",
    "change_reason",
    "re_notice",
)
_AMOUNT_FIELDS = frozenset({"budget", "estimated_price"})
_INSTANT_FIELDS = frozenset({"deadline_at", "opening_at"})
_QUALIFICATION_KEYS = (
    "participation_limited",
    "industry_limited",
    "sw_industry_1468",
    "joint_contract_method",
    "successful_bid_method",
    "technical_evaluation_rate",
)
#: The pre-spec ``deadline_at`` is the opinion-registration deadline, not the
#: bid deadline, so the two are never compared.
NOT_COMPARABLE = ("deadline_at",)


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    """Collected flags are strings. A number keeps its literal; other shapes are unobserved."""

    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _amount(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _regions(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    regions = [_text(item) for item in value]
    return None if any(item is None for item in regions) else regions  # type: ignore[return-value]


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None
    return None


def _conditions(notice: Notice) -> dict[str, Any]:
    flags = _object(notice.qualification_flags_json)
    region = _object(notice.region_limit_json)
    lifecycle = _object(notice.lifecycle_json)
    values: dict[str, Any] = {
        "budget": _amount(notice.budget),
        "estimated_price": _amount(notice.estimated_price),
        "deadline_at": notice.deadline_at,
        "opening_at": _text(lifecycle.get("opening_at")),
        "method": notice.method,
        "region_limit_basis": _text(region.get("basis")),
        "joint_contract_regions": _regions(region.get("joint_contract_regions")),
        "change_reason": _text(lifecycle.get("change_reason")),
        "re_notice": _text(lifecycle.get("re_notice")),
    }
    values.update({key: _text(flags.get(key)) for key in _QUALIFICATION_KEYS})
    return {field: values[field] for field in CONDITION_FIELDS}


def _comparable(field: str, value: Any) -> Any:
    """The value two notices are compared on; ``None`` when it cannot be compared."""

    if value is None:
        return None
    if field in _AMOUNT_FIELDS:
        try:
            return _amount(Decimal(value))
        except InvalidOperation:
            return None
    if field in _INSTANT_FIELDS:
        instant = _instant(value)
        return instant.astimezone(UTC) if instant is not None else None
    if isinstance(value, list):
        return tuple(" ".join(item.split()) for item in value)
    return " ".join(str(value).split())


def _change(field: str, before: Any, after: Any) -> dict[str, Any]:
    left, right = _comparable(field, before), _comparable(field, after)
    if left is None or right is None:
        status = "unknown"
    else:
        status = "unchanged" if left == right else "changed"
    return {"field": field, "status": status, "before": before, "after": after}


def _ordinal_key(bid_ord: str | None) -> tuple[int, int, str]:
    if bid_ord is not None and bid_ord.isdecimal():
        return (0, int(bid_ord), bid_ord)
    return (1, 0, bid_ord or "")


def _pre_spec(session: Session, opportunity_id: int) -> Notice | None:
    notices = {
        notice.id: notice
        for notice in session.scalars(
            select(Notice)
            .join(OpportunityLink, OpportunityLink.notice_id == Notice.id)
            .where(
                OpportunityLink.opportunity_id == opportunity_id,
                authoritative_link_predicate(),
                Notice.source_type == "pre_spec",
            )
        ).all()
    }
    if not notices:
        return None
    # Display choice only: the most recently published pre-spec; undated rows
    # lose. The comparison below never treats this choice as an order fact.
    return max(
        notices.values(),
        key=lambda notice: (
            notice.published_at is not None,
            _instant(notice.published_at) or datetime.min.replace(tzinfo=UTC),
            notice.id,
        ),
    )


def bid_conditions(session: Session, opportunity_id: int) -> dict[str, Any]:
    opportunity = BidDeltaService._opportunity(session, opportunity_id, lock=False)
    bids: Sequence[Notice] = sorted(
        authoritative_bid_notices(session, [opportunity.id]).get(opportunity.id, []),
        key=lambda notice: (notice.bid_no or "", _ordinal_key(notice.bid_ord), notice.id),
    )
    hashes = latest_observation_hashes(session, [notice.id for notice in bids])
    rows: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for notice in bids:
        conditions = _conditions(notice)
        changes = (
            []
            if previous is None
            else [_change(field, previous[field], conditions[field]) for field in CONDITION_FIELDS]
        )
        rows.append(
            {
                "notice_id": notice.id,
                "bid_no": notice.bid_no,
                "bid_ord": notice.bid_ord,
                "published_at": notice.published_at,
                "observation_sha256": hashes.get(notice.id),
                "conditions": conditions,
                "changes_from_previous": changes,
            }
        )
        previous = conditions

    pre_spec_notice = _pre_spec(session, opportunity.id)
    pre_spec = None
    comparison: list[dict[str, Any]] = []
    if pre_spec_notice is not None:
        pre_spec = {
            "notice_id": pre_spec_notice.id,
            "title": pre_spec_notice.title,
            "agency": pre_spec_notice.agency,
            "budget": _amount(pre_spec_notice.budget),
        }
        # Compared with the last listed 차수, the one the decision screen shows.
        last = bids[-1] if bids else None
        comparison = [
            _change("budget", pre_spec["budget"], _amount(last.budget) if last is not None else None),
            _change("title", pre_spec_notice.title, last.title if last is not None else None),
        ]
    view = BidConditionsView(
        opportunity_id=opportunity.id,
        generated_at=datetime.now(UTC),
        pre_spec=pre_spec,
        bid_notices=rows,
        pre_spec_comparison=comparison,
        not_comparable=list(NOT_COMPARABLE),
    )
    return view.model_dump(mode="json")


__all__ = ["CONDITION_FIELDS", "NOT_COMPARABLE", "bid_conditions"]
