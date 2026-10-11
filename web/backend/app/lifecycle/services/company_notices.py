"""Shared pre-spec notice rows for company-scoped read projections (DEMO §6).

The company list, detail and comparison views are served by deep_review under
the lifecycle path prefixes (``/api/companies/...``, ``/api/pre-specs/...``).
The notice part of those views -- population, search, order, and the notice's
sole authoritative active opportunity -- is lifecycle data, so lifecycle owns
it here and exposes it through ``app.lifecycle`` (``company_pre_spec_notices``).
deep_review never re-implements the link/ownership rule and lifecycle never
imports deep_review.

Notices and opportunities are shared across companies: nothing here carries a
company id.  Company decisions are read separately with
``opportunity_tracking.company_tracking_views``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from ...core.search import search_key, search_sql_match
from ..models import Notice, Opportunity, OpportunityLink
from .opportunity_integrity import active_opportunity_predicate, authoritative_link_predicate

CompanyNoticeSort = Literal["posted_at_desc", "deadline_asc"]
COMPANY_NOTICE_SORTS: tuple[str, ...] = ("posted_at_desc", "deadline_asc")


@dataclass(frozen=True)
class CompanyPreSpecNotice:
    """One shared pre-spec notice row (no company data)."""

    notice_id: int
    opportunity_id: int | None
    title: str | None
    posted_at: datetime | None
    deadline_at: datetime | None


def _connected_link_subquery():
    """The sole authoritative active owner per notice (same rule as the pre-spec list)."""

    link = aliased(OpportunityLink)
    opportunity = aliased(Opportunity)
    return (
        select(link.notice_id.label("notice_id"), link.opportunity_id.label("opportunity_id"))
        .join(opportunity, opportunity.id == link.opportunity_id)
        .where(
            link.stage == "notice",
            link.notice_id.is_not(None),
            authoritative_link_predicate(link),
            active_opportunity_predicate(opportunity),
        )
        .subquery("company_notice_connected_link")
    )


def company_pre_spec_notices(
    session: Session,
    *,
    q: str | None = None,
    sort: CompanyNoticeSort = "posted_at_desc",
    notice_ids: Sequence[int] | None = None,
    sw_only: bool = True,
) -> list[CompanyPreSpecNotice]:
    """Pre-spec notices in the requested order, with their connected opportunity.

    * population: ``source_type = 'pre_spec'``; with ``sw_only`` (the company
      list) only notices whose agency-assigned ``SW사업대상`` is exactly ``Y``.
      ``unknown``/missing are never folded into ``Y``.
    * ``q``: the existing pre-spec list search rule (title, agency, demand
      agency through ``core.search``); a blank key does not filter.
    * ``notice_ids``: restrict to these ids (detail/comparison lookups).
    * order: ``posted_at_desc`` (default) or ``deadline_asc``; nulls last and
      ``notice_id DESC`` as the tie-break, evaluated by SQL.

    One query.  ``opportunity_id`` is ``None`` when the notice has no
    authoritative active owner.
    """

    if sort not in COMPANY_NOTICE_SORTS:
        raise ValueError("company_notice_sort_invalid")
    connected = _connected_link_subquery()
    conditions = [Notice.source_type == "pre_spec"]
    if sw_only:
        conditions.append(Notice.qualification_flags_json["sw_business_status"].as_string() == "Y")
    if notice_ids is not None:
        ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
        if not ids:
            return []
        conditions.append(Notice.id.in_(ids))
    if q and search_key(q):
        conditions.append(or_(
            search_sql_match(Notice.title, q),
            search_sql_match(Notice.agency, q),
            search_sql_match(Notice.demand_agency, q),
        ))
    if sort == "deadline_asc":
        order = (Notice.deadline_at.asc().nulls_last(), Notice.id.desc(), connected.c.opportunity_id.asc())
    else:
        order = (Notice.published_at.desc().nulls_last(), Notice.id.desc(), connected.c.opportunity_id.asc())
    rows = session.execute(
        select(Notice.id, connected.c.opportunity_id, Notice.title, Notice.published_at, Notice.deadline_at)
        .select_from(Notice)
        .outerjoin(connected, connected.c.notice_id == Notice.id)
        .where(*conditions)
        .order_by(*order)
    ).all()
    out: list[CompanyPreSpecNotice] = []
    seen: set[int] = set()
    for notice_id, opportunity_id, title, posted_at, deadline_at in rows:
        if int(notice_id) in seen:
            # The authoritative-owner rule admits one active owner; keep the
            # first deterministic row rather than duplicating the notice.
            continue
        seen.add(int(notice_id))
        out.append(CompanyPreSpecNotice(
            notice_id=int(notice_id),
            opportunity_id=None if opportunity_id is None else int(opportunity_id),
            title=title,
            posted_at=posted_at,
            deadline_at=deadline_at,
        ))
    return out


__all__ = [
    "COMPANY_NOTICE_SORTS",
    "CompanyNoticeSort",
    "CompanyPreSpecNotice",
    "company_pre_spec_notices",
]
