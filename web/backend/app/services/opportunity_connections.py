"""사전규격 공고의 추적 관계 판정과 나라장터 첨부 키 (lifecycle, 명세 §5.2).

`services/prespec_attachments.py`에서 갈라져 나온 lifecycle 몫이다. 회차 적재가
첨부 메타를 기록할 때 `parse_attachment_key`를 쓰고, 사전규격 목록과 첨부 취득
자격이 같은 `tracked_order_plan_connection_predicate`를 쓴다. 표시 예외와 취득
규칙이 한 builder에서 나오므로 서로 어긋나지 않는다. 로직은 옮기기 전과 같다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from ..lifecycle.models import Notice, Opportunity, OpportunityLink
from .opportunity_integrity import (
    active_opportunity_predicate,
    authoritative_link_predicate,
)

G2B_HOST = "www.g2b.go.kr"
G2B_ATTACHMENT_PATH = "/pn/pnz/pnza/UntyAtchFile/downloadFile.do"
_ATTACHMENT_QUERY_KEYS = frozenset({"bfSpecRegNo", "fileType", "fileSeq"})
_TRACKING_STATUSES = frozenset({"계속 추적", "보류"})


def parse_attachment_key(url: str | None) -> str | None:
    """Parse only the measured G2B pre-specification attachment URL shape."""

    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    # ``netloc`` is intentionally exact: a port, userinfo, trailing dot, or
    # alternate host must not become provider provenance by inference.
    if (
        parsed.scheme != "https"
        or parsed.netloc != G2B_HOST
        or parsed.path != G2B_ATTACHMENT_PATH
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        return None
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=False)
    except ValueError:
        return None
    values: dict[str, str] = {}
    for key, value in pairs:
        if key not in _ATTACHMENT_QUERY_KEYS:
            continue
        if key in values or not value:
            return None
        values[key] = value
    if set(values) != _ATTACHMENT_QUERY_KEYS:
        return None
    return f"{values['bfSpecRegNo']}:{values['fileType']}:{values['fileSeq']}"


def _tracked_order_plan_conditions(
    *,
    notice_link: Any,
    opportunity: Any,
    order_plan_link: Any,
    notice_id: Any | None = None,
) -> list[ColumnElement[bool]]:
    """Build the single source of truth for the tracked order-plan path."""

    conditions: list[ColumnElement[bool]] = [
        notice_link.stage == "notice",
        notice_link.notice_id.is_not(None),
        authoritative_link_predicate(notice_link),
        opportunity.tracking_status.in_(_TRACKING_STATUSES),
        active_opportunity_predicate(opportunity),
        exists(
            select(1)
            .select_from(order_plan_link)
            .where(
                order_plan_link.opportunity_id == opportunity.id,
                order_plan_link.stage == "order_plan",
                order_plan_link.order_plan_id.is_not(None),
                authoritative_link_predicate(order_plan_link),
            )
        ),
    ]
    if notice_id is not None:
        conditions.insert(0, notice_link.notice_id == notice_id)
    return conditions


def tracked_order_plan_connection_predicate(notice_id: Any) -> ColumnElement[bool]:
    """Return the exact tracked order-plan exception as a SQL predicate.

    This expression is shared by the cumulative pre-spec list and the
    attachment eligibility refresh.  Keeping the status and link conditions in
    one builder prevents the display exception from drifting from the fetch
    eligibility rule.
    """

    notice_link = aliased(OpportunityLink)
    opportunity = aliased(Opportunity)
    order_plan_link = aliased(OpportunityLink)
    return exists(
        select(1)
        .select_from(notice_link)
        .join(opportunity, opportunity.id == notice_link.opportunity_id)
        .where(
            *_tracked_order_plan_conditions(
                notice_link=notice_link,
                opportunity=opportunity,
                order_plan_link=order_plan_link,
                notice_id=notice_id,
            )
        )
    )


def tracked_order_plan_connections(
    session: Session,
    *,
    notice_ids: Sequence[int] | None = None,
) -> dict[int, set[int]]:
    """Return qualifying opportunity IDs grouped by notice in one query."""

    if notice_ids is not None:
        narrowed_ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
        if not narrowed_ids:
            return {}
    else:
        narrowed_ids = ()

    notice_link = aliased(OpportunityLink)
    opportunity = aliased(Opportunity)
    order_plan_link = aliased(OpportunityLink)
    conditions = _tracked_order_plan_conditions(
        notice_link=notice_link,
        opportunity=opportunity,
        order_plan_link=order_plan_link,
    )
    conditions.append(notice_link.notice_id.is_not(None))
    if notice_ids is not None:
        conditions.append(notice_link.notice_id.in_(narrowed_ids))
    rows = session.execute(
        select(notice_link.notice_id, notice_link.opportunity_id)
        .select_from(notice_link)
        .join(opportunity, opportunity.id == notice_link.opportunity_id)
        .where(*conditions)
    ).all()
    grouped: dict[int, set[int]] = {}
    for notice_id_value, opportunity_id in rows:
        grouped.setdefault(int(notice_id_value), set()).add(int(opportunity_id))
    return grouped


def tracked_order_plan_connection(session: Session, notice_id: int) -> bool:
    """Return whether one notice has the exact tracked order-plan path."""

    return bool(
        session.scalar(
            select(tracked_order_plan_connection_predicate(Notice.id))
            .select_from(Notice)
            .where(Notice.id == int(notice_id))
        )
    )


__all__ = [
    "G2B_ATTACHMENT_PATH",
    "G2B_HOST",
    "parse_attachment_key",
    "tracked_order_plan_connection",
    "tracked_order_plan_connection_predicate",
    "tracked_order_plan_connections",
]
