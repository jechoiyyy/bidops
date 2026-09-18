"""발주계획·사전규격·입찰공고 이름 후보 대조와 찾아보기 (spec §4).

공식 통합번호가 없는 이름 일치는 확정 관계가 아니라 사람 확인 후보다
(engineering-notes "제목 유사도로 생애주기 관계를 확정하면 다른 사업이 합쳐진다").
이 모듈의 경로는 셋이다.

- SW사업대상 사전규격 자동 후보(§4.2): 수집 적재가 사전규격을 적재한 직후 같은
  트랜잭션에서 부른다. 같은 기관 발주계획만 SQL로 좁힌 뒤 이름 사다리로 대조한다.
- 찾아보기(§4.3): 사람이 요청한 사업기회 하나에 대해 보관 회차 색인을 검색한다.
  미적재 레코드는 회차 파일에서 ``search_result``로 적재한 뒤 후보를 만든다.
  찾지 못하면 ``검색 미확인``으로 남기며 "없음"으로 바꾸지 않는다(ADR-0025).
- 사전규격 상세의 후보 조회(§4.4).

이름 정규화와 전략 순서는 :mod:`name_matching` 하나만 쓴다. 모델 호출·원격 조회는 없다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from ...core.models import AuditEvent
from ..models import CollectedRecordIndex, Notice, Opportunity, OpportunityLink, OrderPlan
from ..schemas.opportunities import OpportunitySearchResponse, OpportunitySearchTarget
from ..schemas.pre_specs import (
    PreSpecCandidateOrderPlan,
    PreSpecOrderPlanCandidate,
    PreSpecOrderPlanCandidatesResponse,
)
from .collection_index import chunks, latest_row_per_identity, title_normalized
from .name_matching import SEARCH_STRATEGIES, collapse, search_variants
from .opportunity_integrity import (
    active_opportunity_predicate,
    authoritative_link_predicate,
    is_authoritative_link,
)
from .opportunity_queries import actionable_pending_candidate_predicate, link_view
from .opportunity_tracking import OpportunityTrackingError, _validate_human_name


#: 사전규격 한 건에 자동으로 만드는 후보 상한 (spec §4.2).
AUTO_CANDIDATE_LIMIT = 5
#: 찾아보기 한 번이 돌려주는 후보 상한 (spec §4.3).
SEARCH_CANDIDATE_LIMIT = 5
SEARCH_TARGETS: tuple[OpportunitySearchTarget, ...] = ("pre_spec", "bid_notice")
SEARCH_PERFORMED_ACTION = "opportunity.search.performed"
PENDING_CANDIDATE_STATUS = "후보 확인 대기"
SEARCH_UNCONFIRMED_STATUS = "검색 미확인"
PRE_SPEC_SOURCE_TYPES = ("pre_spec", "prespec", "pre-spec")
_LIKE_ESCAPE = "/"


# ---------------------------------------------------------------------------
# 이름·기관 대조
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NameMatch:
    """The first ladder rung that matched and the rungs tried up to it."""

    strategy: str
    attempted: tuple[str, ...]

    @property
    def rank(self) -> int:
        return SEARCH_STRATEGIES.index(self.strategy)


def name_ladders(titles: Iterable[str | None]) -> list[list[tuple[str, str]]]:
    """One :func:`search_variants` ladder per non-empty source title."""

    ladders: list[list[tuple[str, str]]] = []
    for title in titles:
        if not isinstance(title, str) or not title.strip():
            continue
        ladder = search_variants(title)
        if ladder:
            ladders.append(ladder)
    return ladders


def match_name(
    ladders: Sequence[Sequence[tuple[str, str]]],
    target_normalized: str | None,
) -> NameMatch | None:
    """Spec §4.1: a source variant contained in the target ``title_normalized``.

    Within one ladder the first contained rung wins; across several source
    titles the most precise winning rung is kept.
    """

    if not target_normalized:
        return None
    best: NameMatch | None = None
    for ladder in ladders:
        attempted: list[str] = []
        for strategy, query in ladder:
            attempted.append(strategy)
            if query in target_normalized:
                found = NameMatch(strategy=strategy, attempted=tuple(attempted))
                if best is None or found.rank < best.rank:
                    best = found
                break
    return best


def attempted_strategies(ladders: Sequence[Sequence[tuple[str, str]]]) -> list[str]:
    """Every strategy present in the ladders, in precision order."""

    used = {strategy for ladder in ladders for strategy, _query in ladder}
    return [strategy for strategy in SEARCH_STRATEGIES if strategy in used]


def agency_key(value: Any) -> str | None:
    """Whitespace-normalized agency name; blank stays ``None``."""

    if not isinstance(value, str):
        return None
    return collapse(value) or None


def _agency_like_pattern(key: str) -> str:
    """A LIKE pattern that is a superset of values whose collapsed form is ``key``."""

    escaped = (
        key.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )
    return "%" + "%".join(escaped.split(" ")) + "%"


def _newest_first(value: datetime | None) -> tuple[int, float]:
    if value is None:
        return (1, 0.0)
    return (0, -value.timestamp())


def _is_pre_spec(notice: Notice) -> bool:
    return (notice.source_type or "").strip().lower() in PRE_SPEC_SOURCE_TYPES


def _aware_utc(value: datetime | None) -> datetime:
    result = value if value is not None else datetime.now(UTC)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("candidate timestamps must be timezone-aware")
    return result.astimezone(UTC)


# ---------------------------------------------------------------------------
# SW=Y 사전규격 자동 후보 (§4.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AutoCandidateResult:
    matched: int = 0
    created: int = 0


def create_pre_spec_auto_candidates(
    session: Session,
    pre_spec: Notice,
    *,
    searched_at: datetime | None = None,
) -> AutoCandidateResult:
    """Propose order-plan owners for one loaded SW사업대상 pre-spec.

    Order plans are narrowed in SQL to the pre-spec's agency (발주기관 or
    수요기관) and to active owners with no authoritative pre-spec link yet;
    only those rows are compared in Python.  Owners are ranked by strategy
    precision, then by the matching plan's ``published_at`` (newest first),
    and at most :data:`AUTO_CANDIDATE_LIMIT` are proposed.  An owner that
    already has a candidate row for this pre-spec in any state is skipped, so
    a rejected pair is never proposed again.  Zero matches write nothing.
    The caller owns the transaction.
    """

    if pre_spec.id is None:
        session.flush()
    if not _is_pre_spec(pre_spec):
        return AutoCandidateResult()
    target_title = title_normalized(pre_spec.title)
    agencies = {
        key
        for key in (agency_key(pre_spec.agency), agency_key(pre_spec.demand_agency))
        if key is not None
    }
    if target_title is None or not agencies:
        return AutoCandidateResult()

    owner_link = aliased(OpportunityLink, name="plan_owner_link")
    owner = aliased(Opportunity, name="plan_owner")
    pre_spec_link = aliased(OpportunityLink, name="owner_pre_spec_link")
    owned_notice = aliased(Notice, name="owner_pre_spec")
    owner_has_pre_spec = (
        select(pre_spec_link.id)
        .join(owned_notice, owned_notice.id == pre_spec_link.notice_id)
        .where(
            pre_spec_link.opportunity_id == owner.id,
            authoritative_link_predicate(pre_spec_link),
            owned_notice.source_type.in_(PRE_SPEC_SOURCE_TYPES),
        )
        .correlate(owner)
        .exists()
    )
    plans = session.execute(
        select(OrderPlan, owner)
        .join(owner_link, owner_link.order_plan_id == OrderPlan.id)
        .join(owner, owner.id == owner_link.opportunity_id)
        .where(
            authoritative_link_predicate(owner_link),
            active_opportunity_predicate(owner),
            or_(
                *(
                    OrderPlan.agency_name.like(_agency_like_pattern(key), escape=_LIKE_ESCAPE)
                    for key in sorted(agencies)
                )
            ),
            ~owner_has_pre_spec,
        )
    ).all()

    best: dict[int, tuple[tuple[Any, ...], NameMatch, Opportunity]] = {}
    for plan, plan_owner in plans:
        if agency_key(plan.agency_name) not in agencies:
            continue
        match = match_name(name_ladders([plan.title]), target_title)
        if match is None:
            continue
        order = (match.rank, *_newest_first(plan.published_at), plan.id)
        current = best.get(plan_owner.id)
        if current is None or order < current[0]:
            best[plan_owner.id] = (order, match, plan_owner)
    if not best:
        return AutoCandidateResult()

    ranked = sorted(best.values(), key=lambda item: item[0])[:AUTO_CANDIDATE_LIMIT]
    existing = set(
        session.scalars(
            select(OpportunityLink.opportunity_id).where(
                OpportunityLink.opportunity_id.in_([item[2].id for item in ranked]),
                OpportunityLink.notice_id == pre_spec.id,
                OpportunityLink.link_type == "candidate",
            )
        )
    )
    event_at = _aware_utc(searched_at)
    created = 0
    for _order, match, plan_owner in ranked:
        if plan_owner.id in existing:
            continue
        # Assign the relationship, not only the FK: a merge later in the same
        # ingest moves the links of an already loaded ``Opportunity.links``.
        session.add(
            OpportunityLink(
                opportunity=plan_owner,
                notice=pre_spec,
                stage="notice",
                link_type="candidate",
                status=PENDING_CANDIDATE_STATUS,
                search_strategy=match.strategy,
                agency_match=True,
                attempted_strategies_json=list(match.attempted),
                last_searched_at=event_at,
            )
        )
        created += 1
    if created:
        session.flush()
    return AutoCandidateResult(matched=len(best), created=created)


# ---------------------------------------------------------------------------
# 찾아보기 (§4.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchOutcome:
    """The response plus what the router needs after commit."""

    response: OpportunitySearchResponse
    owner_opportunity_id: int
    loaded_count: int


@dataclass(frozen=True)
class _Found:
    row: CollectedRecordIndex
    match: NameMatch
    agency_match: bool

    def order(self) -> tuple[Any, ...]:
        return (
            not self.agency_match,
            self.match.rank,
            *_newest_first(self.row.published_at),
            self.row.record_key,
        )


def _lock_active_opportunity(session: Session, opportunity_id: int) -> Opportunity:
    if not isinstance(opportunity_id, int) or isinstance(opportunity_id, bool):
        raise OpportunityTrackingError("opportunity_invalid", "사업기회 식별자가 올바르지 않습니다")
    opportunity = session.get(Opportunity, opportunity_id, with_for_update=True)
    if opportunity is None:
        raise OpportunityTrackingError("opportunity_not_found", "사업기회를 찾을 수 없습니다")
    if opportunity.merged_into_opportunity_id is not None:
        raise OpportunityTrackingError(
            "opportunity_merged", "병합된 사업기회의 상태는 변경할 수 없습니다"
        )
    return opportunity


def _active_root(session: Session, opportunity: Opportunity) -> Opportunity:
    """Follow merge lineage; a record loaded by the search may merge the owner."""

    session.refresh(opportunity)
    current = opportunity
    seen: set[int] = set()
    while current.merged_into_opportunity_id is not None and current.id not in seen:
        seen.add(current.id)
        parent = session.get(Opportunity, current.merged_into_opportunity_id)
        if parent is None:  # pragma: no cover - the FK forbids a dangling lineage.
            break
        current = parent
    return current


def _search_sources(
    session: Session,
    opportunity_id: int,
    target: OpportunitySearchTarget,
) -> tuple[list[list[tuple[str, str]]], set[str]]:
    """Name ladders and agency keys of the owned records the search starts from."""

    owned = session.execute(
        select(OrderPlan, Notice)
        .select_from(OpportunityLink)
        .outerjoin(OrderPlan, OrderPlan.id == OpportunityLink.order_plan_id)
        .outerjoin(Notice, Notice.id == OpportunityLink.notice_id)
        .where(
            OpportunityLink.opportunity_id == opportunity_id,
            authoritative_link_predicate(OpportunityLink),
        )
        .order_by(OpportunityLink.id)
    ).all()
    plans = [
        plan for plan, _notice in owned
        if plan is not None and isinstance(plan.title, str) and plan.title.strip()
    ]
    pre_specs = [
        notice for _plan, notice in owned
        if notice is not None
        and _is_pre_spec(notice)
        and isinstance(notice.title, str)
        and notice.title.strip()
    ]
    sources: list[tuple[str, tuple[Any, ...]]] = []
    if target == "bid_notice":
        sources = [(notice.title, (notice.agency, notice.demand_agency)) for notice in pre_specs]
    if not sources:
        sources = [(plan.title, (plan.agency_name,)) for plan in plans]
    if not sources:
        raise OpportunityTrackingError(
            "search_source_missing",
            "찾아보기의 기준이 될 소유 레코드가 없습니다",
            details={"target": target},
        )
    ladders = name_ladders(title for title, _agencies in sources)
    agencies = {
        key
        for _title, values in sources
        for key in (agency_key(value) for value in values)
        if key is not None
    }
    return ladders, agencies


def _index_candidates(
    session: Session,
    target: OpportunitySearchTarget,
    ladders: Sequence[Sequence[tuple[str, str]]],
) -> list[CollectedRecordIndex]:
    """Newest index row per record whose title a ladder rung may be in.

    SQL narrows by substring (SQLite LIKE is case-insensitive, so this is a
    superset); :func:`match_name` then decides exactly on the newest row.
    """

    queries = sorted({query for ladder in ladders for _strategy, query in ladder})
    if not queries:
        return []
    keys = set(
        session.scalars(
            select(CollectedRecordIndex.record_key)
            .where(
                CollectedRecordIndex.record_kind == target,
                or_(
                    *(
                        CollectedRecordIndex.title_normalized.contains(query, autoescape=True)
                        for query in queries
                    )
                ),
            )
            .distinct()
        )
    )
    rows: list[CollectedRecordIndex] = []
    for batch in chunks(sorted(keys)):
        rows.extend(
            session.scalars(
                select(CollectedRecordIndex).where(
                    CollectedRecordIndex.record_kind == target,
                    CollectedRecordIndex.record_key.in_(batch),
                )
            )
        )
    return latest_row_per_identity(session, rows)


def _stored_notices(
    session: Session,
    rows: Sequence[CollectedRecordIndex],
) -> dict[int, Notice]:
    """Already loaded Notice per index row id, by the loader's key spellings."""

    from ..ingest.loader import _pre_spec_notice_keys

    wanted: dict[str, list[CollectedRecordIndex]] = {}
    for row in rows:
        keys = {row.record_key}
        if row.record_kind == "pre_spec" and row.bf_spec_rgst_no:
            keys.update(_pre_spec_notice_keys(row.bf_spec_rgst_no))
        for key in keys:
            wanted.setdefault(key, []).append(row)
    found: dict[int, Notice] = {}
    for batch in chunks(sorted(wanted)):
        for notice in session.scalars(select(Notice).where(Notice.notice_key.in_(batch))):
            for row in wanted[notice.notice_key]:
                exact = notice.notice_key == row.record_key
                if not exact and not _is_pre_spec(notice):
                    continue
                if exact or row.id not in found:
                    found[row.id] = notice
    return found


def _links_by_notice(
    session: Session,
    opportunity_id: int,
    notice_ids: Iterable[int],
) -> dict[int, list[OpportunityLink]]:
    result: dict[int, list[OpportunityLink]] = {}
    for batch in chunks(sorted(set(notice_ids))):
        for link in session.scalars(
            select(OpportunityLink)
            .where(
                OpportunityLink.opportunity_id == opportunity_id,
                OpportunityLink.notice_id.in_(batch),
            )
            .order_by(OpportunityLink.id)
        ):
            result.setdefault(link.notice_id, []).append(link)
    return result


def _is_rejected(link: OpportunityLink) -> bool:
    return link.link_type == "candidate" and link.human_decision == "rejected"


def _record_search_unconfirmed(
    session: Session,
    opportunity: Opportunity,
    target: OpportunitySearchTarget,
    attempted: list[str],
    searched_at: datetime,
) -> None:
    """Create or refresh this target's ``검색 미확인`` row (not an absence claim)."""

    row = session.scalar(
        select(OpportunityLink)
        .where(
            OpportunityLink.opportunity_id == opportunity.id,
            OpportunityLink.status == SEARCH_UNCONFIRMED_STATUS,
            OpportunityLink.search_target_kind == target,
        )
        .order_by(OpportunityLink.id)
        .limit(1)
    )
    if row is None:
        session.add(
            OpportunityLink(
                opportunity=opportunity,
                stage="notice",
                link_type="candidate",
                status=SEARCH_UNCONFIRMED_STATUS,
                search_target_kind=target,
                attempted_strategies_json=list(attempted),
                last_searched_at=searched_at,
            )
        )
    else:
        row.attempted_strategies_json = list(attempted)
        row.last_searched_at = searched_at


def search_opportunity_records(
    session: Session,
    opportunity_id: int,
    *,
    target: OpportunitySearchTarget,
    searched_by: str,
    runs_root: str | Path,
    searched_at: datetime | None = None,
) -> SearchOutcome:
    """Search the archived collection index for one opportunity (spec §4.3).

    - Sources: ``pre_spec`` starts from owned order plans; ``bid_notice``
      starts from owned pre-specs, otherwise owned order plans.  No source is
      ``search_source_missing``.
    - Records already owned by this opportunity and rejected owner+target
      pairs are excluded; the rest are ordered agency match first, then
      strategy precision, then newest, and at most five are kept.
    - A kept record that is only in the index is loaded from its run file as
      ``search_result`` (which applies the official-key linking and merge
      rule), then gets a pending candidate; an existing pending candidate is
      reused.  A record the load linked to this opportunity needs no
      candidate.
    - With no candidate and nothing newly owned, the target's ``검색 미확인``
      row is created or refreshed.

    The audit event carries counts only.  The caller owns commit.
    """

    if target not in SEARCH_TARGETS:
        raise OpportunityTrackingError("invalid_request", "지원하지 않는 찾아보기 대상입니다")
    actor = _validate_human_name(searched_by)
    event_at = _aware_utc(searched_at)
    requested = _lock_active_opportunity(session, opportunity_id)
    ladders, agencies = _search_sources(session, requested.id, target)
    attempted = attempted_strategies(ladders)

    found: list[_Found] = []
    for row in _index_candidates(session, target, ladders):
        match = match_name(ladders, row.title_normalized)
        if match is None:
            continue
        row_agencies = {
            key for key in (agency_key(row.agency), agency_key(row.demand_agency)) if key
        }
        found.append(_Found(row=row, match=match, agency_match=bool(agencies & row_agencies)))

    stored = _stored_notices(session, [item.row for item in found])
    existing_links = _links_by_notice(
        session, requested.id, (notice.id for notice in stored.values())
    )
    eligible: list[_Found] = []
    for item in found:
        notice = stored.get(item.row.id)
        links = existing_links.get(notice.id, []) if notice is not None else []
        if any(is_authoritative_link(link) or _is_rejected(link) for link in links):
            continue
        eligible.append(item)
    selected = sorted(eligible, key=_Found.order)[:SEARCH_CANDIDATE_LIMIT]

    loaded_count = 0
    unavailable_count = 0
    index_only = [item.row for item in selected if item.row.id not in stored]
    if index_only:
        from ..ingest.loader import ingest_indexed_records

        loaded = ingest_indexed_records(
            session, index_only, reason="search_result", runs_root=runs_root
        )
        loaded_count = sum(loaded.loaded.values())
        unavailable_count = loaded.unavailable
        for row in index_only:
            notice = loaded.notices.get(row.id)
            if notice is not None:
                stored[row.id] = notice

    # Loading may have merged the requested opportunity into another one.
    owner = _active_root(session, requested) if index_only else requested
    notices = [stored[item.row.id] for item in selected if item.row.id in stored]
    owners_by_notice: dict[int, int] = {}
    for batch in chunks(sorted({notice.id for notice in notices})):
        for notice_id, owner_id in session.execute(
            select(OpportunityLink.notice_id, OpportunityLink.opportunity_id)
            .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
            .where(
                OpportunityLink.notice_id.in_(batch),
                authoritative_link_predicate(OpportunityLink),
                active_opportunity_predicate(Opportunity),
            )
        ):
            owners_by_notice[notice_id] = owner_id
    owner_links = _links_by_notice(session, owner.id, (notice.id for notice in notices))

    candidates: list[OpportunityLink] = []
    created_count = 0
    newly_owned = 0
    for item in selected:
        notice = stored.get(item.row.id)
        if notice is None:
            continue
        if owners_by_notice.get(notice.id) == owner.id:
            newly_owned += 1
            continue
        links = owner_links.get(notice.id, [])
        if any(_is_rejected(link) for link in links):
            continue
        pending = next(
            (
                link for link in links
                if link.link_type == "candidate" and link.status == PENDING_CANDIDATE_STATUS
            ),
            None,
        )
        if pending is not None:
            pending.last_searched_at = event_at
            candidates.append(pending)
            continue
        link = OpportunityLink(
            opportunity=owner,
            notice=notice,
            stage="notice",
            link_type="candidate",
            status=PENDING_CANDIDATE_STATUS,
            search_strategy=item.match.strategy,
            agency_match=item.agency_match,
            attempted_strategies_json=list(item.match.attempted),
            last_searched_at=event_at,
        )
        session.add(link)
        candidates.append(link)
        created_count += 1

    search_unconfirmed = not candidates and newly_owned == 0
    if search_unconfirmed:
        _record_search_unconfirmed(session, owner, target, attempted, event_at)
    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=actor,
            action=SEARCH_PERFORMED_ACTION,
            aggregate_type="opportunity",
            aggregate_id=str(requested.id),
            safe_metadata={
                "opportunity_id": owner.id,
                "target": target,
                "matched_count": len(found),
                "candidate_count": len(candidates),
                "created_candidate_count": created_count,
                "owned_count": newly_owned,
                "loaded_count": loaded_count,
                "unavailable_count": unavailable_count,
                "search_unconfirmed": search_unconfirmed,
            },
            request_id=None,
            created_at=event_at,
        )
    )
    session.flush()
    response = OpportunitySearchResponse(
        searched_at=event_at,
        target=target,
        attempted_strategies=attempted,
        candidates=[link_view(link) for link in candidates],
        search_unconfirmed=search_unconfirmed,
    )
    return SearchOutcome(
        response=response,
        owner_opportunity_id=owner.id,
        loaded_count=loaded_count,
    )


# ---------------------------------------------------------------------------
# 사전규격 상세의 발주계획 후보 (§4.4)
# ---------------------------------------------------------------------------


def _strategy_rank(strategy: str | None) -> int:
    return SEARCH_STRATEGIES.index(strategy) if strategy in SEARCH_STRATEGIES else len(SEARCH_STRATEGIES)


def pre_spec_order_plan_candidates(
    session: Session,
    notice_pk: int,
) -> PreSpecOrderPlanCandidatesResponse | None:
    """Pending candidates targeting one pre-spec, with owner and plan summaries.

    Returns ``None`` for an unknown notice or a notice that is not a pre-spec.
    A stale candidate whose owner already owns the pre-spec is not listed.
    Three queries regardless of the number of candidates or plans.
    """

    notice = session.get(Notice, notice_pk)
    if notice is None or not _is_pre_spec(notice):
        return None
    candidate = aliased(OpportunityLink, name="pre_spec_candidate")
    rows = session.execute(
        select(candidate, Opportunity)
        .join(Opportunity, Opportunity.id == candidate.opportunity_id)
        .where(
            candidate.notice_id == notice.id,
            actionable_pending_candidate_predicate(candidate),
            active_opportunity_predicate(Opportunity),
        )
        .options(joinedload(candidate.notice))
        .order_by(candidate.id)
    ).all()
    owner_ids = sorted({opportunity.id for _link, opportunity in rows})
    plans: dict[int, list[PreSpecCandidateOrderPlan]] = {}
    for batch in chunks(owner_ids):
        for owner_id, plan in session.execute(
            select(OpportunityLink.opportunity_id, OrderPlan)
            .join(OrderPlan, OrderPlan.id == OpportunityLink.order_plan_id)
            .where(
                OpportunityLink.opportunity_id.in_(batch),
                authoritative_link_predicate(OpportunityLink),
            )
            .order_by(OpportunityLink.id)
        ):
            plans.setdefault(owner_id, []).append(
                PreSpecCandidateOrderPlan(
                    order_plan_id=plan.id,
                    order_plan_unty_no=plan.order_plan_unty_no,
                    title=plan.title,
                    agency_name=plan.agency_name,
                    planned_order_year=plan.planned_order_year,
                    planned_order_month=plan.planned_order_month,
                    budget_amount=(
                        float(plan.budget_amount) if plan.budget_amount is not None else None
                    ),
                )
            )
    ordered = sorted(
        rows,
        key=lambda row: (
            _strategy_rank(row[0].search_strategy),
            row[0].agency_match is not True,
            row[0].id,
        ),
    )
    return PreSpecOrderPlanCandidatesResponse(
        notice_pk=notice.id,
        items=[
            PreSpecOrderPlanCandidate(
                link=link_view(link),
                opportunity_id=opportunity.id,
                tracking_status=opportunity.tracking_status,
                order_plans=plans.get(opportunity.id, []),
            )
            for link, opportunity in ordered
        ],
    )


__all__ = [
    "AUTO_CANDIDATE_LIMIT",
    "AutoCandidateResult",
    "NameMatch",
    "PENDING_CANDIDATE_STATUS",
    "SEARCH_CANDIDATE_LIMIT",
    "SEARCH_PERFORMED_ACTION",
    "SEARCH_TARGETS",
    "SEARCH_UNCONFIRMED_STATUS",
    "SearchOutcome",
    "agency_key",
    "attempted_strategies",
    "create_pre_spec_auto_candidates",
    "match_name",
    "name_ladders",
    "pre_spec_order_plan_candidates",
    "search_opportunity_records",
]
