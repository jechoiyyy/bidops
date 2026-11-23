"""Order, count and locate rows for the paged C-2 review workspace."""

from datetime import date, datetime
import re
from typing import Any, Sequence
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
RELEVANCE_ORDER = {"relevant": 0, "uncertain": 1, "not_relevant": 2}


def _planned_month(year: str | None, month: str | None) -> str | None:
    month = (month or "").strip()
    if re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
        return month
    year = (year or "").strip()
    if re.fullmatch(r"[0-9]{4}", year) and re.fullmatch(r"[0-9]{1,2}", month) and 1 <= int(month) <= 12:
        return f"{year}-{int(month):02}"
    return None


def _review_key(row: Any, order: str, current_month: str) -> tuple:
    relevance = RELEVANCE_ORDER.get(row.relevance, 3)
    if order == "relevance":
        return relevance, row.pk
    observed = row.first_observed_at
    # Keep the prior browser's millisecond tie-break, including nulls last.
    observed_ms = int(observed.timestamp() * 1000) if observed is not None else float("-inf")
    day = observed.astimezone(SEOUL).date() if observed is not None else date.min
    if order == "relevant":
        month = _planned_month(row.planned_order_year, row.planned_order_month)
        stale = row.notice_posted == "Y" or (month is not None and month < current_month)
        return stale, "" if stale else month or "9999-99", -observed_ms, relevance, row.pk
    rank = row.stage1_rank if observed is not None and row.stage1_rank is not None else float("inf")
    rank_key = (-day.toordinal(), rank, -observed_ms, relevance, row.pk)
    if order == "uncertain":
        month = _planned_month(row.planned_order_year, row.planned_order_month)
        stale = row.notice_posted == "Y" or (month is not None and month < current_month)
        return stale, *rank_key
    return rank_key


def review_page(
    candidates: Sequence[Any],
    *,
    order: str,
    judgments_available: bool,
    limit: int,
    offset: int,
    locate: int | None,
    retain: int | None,
) -> tuple[list[int], int, int, dict[str, Any]]:
    counts = {"relevant": 0, "uncertain": 0, "unjudged": 0, "all": len(candidates)}
    matched = []
    default_filter = order == "default" and judgments_available
    for row in candidates:
        if row.tracking == "미선택" and row.relevance in ("relevant", "uncertain"):
            counts[row.relevance] += 1
        counts["unjudged"] += bool(row.unjudged)
        if row.pk == retain or (row.matches and (
            not default_filter or (row.relevance == "relevant" and row.tracking == "미선택")
        )):
            matched.append(row)

    if order == "default":
        order = "relevant" if default_filter else "relevance"
    target_in_scope = locate is not None and any(row.pk == locate for row in candidates)
    target_hidden = target_in_scope and all(row.pk != locate for row in matched)
    if target_hidden:
        matched = list(candidates)
        order = "relevance"
    current_month = datetime.now(SEOUL).strftime("%Y-%m")
    matched.sort(key=lambda row: _review_key(row, order, current_month))
    ids = [row.pk for row in matched]
    if target_in_scope:
        offset = ids.index(locate) // limit * limit
    offset = min(offset, max(0, (len(ids) - 1) // limit * limit))
    return ids[offset:offset + limit], len(ids), offset, {
        "view_counts": counts,
        "previous_pk": ids[offset - 1] if offset else None,
        "next_pk": ids[offset + limit] if offset + limit < len(ids) else None,
        "target_found": target_in_scope if locate is not None else None,
        "target_filters_cleared": target_hidden,
    }
