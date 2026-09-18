"""Batch currentness of final decisions: the one rule every consumer shares.

ADR-0053 §6 keeps currentness in a single place. ADR-0058 adds a second decision
basis, so this module owns both halves: immutable comparisons against newer
ready inputs, and notice-condition decisions against newer authoritative bid
notices and changed observations. The workspace, decision queue, workload
projection, and final-decision endpoint all read these functions.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...lifecycle import authoritative_link_predicate
from ...lifecycle.models import Notice, NoticeObservation, OpportunityLink
from ..models import (
    BidDeltaComparison,
    BidFinalDecision,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
)

Currentness = tuple[str, list[str]]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _ordinal(bid_ord: str | None) -> int | None:
    return int(bid_ord) if bid_ord is not None and bid_ord.isdecimal() else None


def is_newer_bid_notice(candidate: Notice, basis: Notice) -> bool | None:
    """Whether ``candidate`` is a later bid notice than ``basis``.

    ``published_at`` decides first and ``bid_ord`` breaks an exact tie. ``None``
    means the order cannot be determined (missing date, non-decimal ordinal on a
    tie, or an identical date and ordinal) and must never be read as "older".
    """

    if candidate.published_at is None or basis.published_at is None:
        return None
    left, right = _aware(candidate.published_at), _aware(basis.published_at)
    if left != right:
        return left > right
    left_ord, right_ord = _ordinal(candidate.bid_ord), _ordinal(basis.bid_ord)
    if left_ord is None or right_ord is None or left_ord == right_ord:
        return None
    return left_ord > right_ord


def latest_bid_notice(notices: Sequence[Notice]) -> tuple[Notice | None, str | None]:
    """Return ``(latest, None)`` or ``(None, reason)``.

    ``reason`` is ``bid_notice_missing`` when there is no authoritative bid
    notice and ``ordering_unknown`` when the latest one cannot be determined.
    """

    if not notices:
        return None, "bid_notice_missing"
    if any(notice.published_at is None for notice in notices):
        return None, "ordering_unknown"
    newest = max(_aware(notice.published_at) for notice in notices)  # type: ignore[arg-type]
    top = [notice for notice in notices if _aware(notice.published_at) == newest]  # type: ignore[arg-type]
    if len(top) == 1:
        return top[0], None
    ordinals = [_ordinal(notice.bid_ord) for notice in top]
    if any(value is None for value in ordinals):
        return None, "ordering_unknown"
    highest = max(ordinals)  # type: ignore[type-var]
    if ordinals.count(highest) > 1:
        return None, "ordering_unknown"
    return top[ordinals.index(highest)], None


def authoritative_bid_notices(session: Session, opportunity_ids: Iterable[int]) -> dict[int, list[Notice]]:
    """Authoritative bid notices per opportunity in one read."""

    ids = tuple(dict.fromkeys(opportunity_ids))
    result: dict[int, list[Notice]] = defaultdict(list)
    if not ids:
        return result
    seen: set[tuple[int, int]] = set()
    for opportunity_id, notice in session.execute(
        select(OpportunityLink.opportunity_id, Notice)
        .join(Notice, Notice.id == OpportunityLink.notice_id)
        .where(
            OpportunityLink.opportunity_id.in_(ids),
            authoritative_link_predicate(),
            Notice.source_type == "bid_notice",
        )
        .order_by(OpportunityLink.opportunity_id.asc(), Notice.id.asc())
    ).all():
        if (opportunity_id, notice.id) not in seen:
            seen.add((opportunity_id, notice.id))
            result[opportunity_id].append(notice)
    return result


def latest_observation_hashes(session: Session, notice_ids: Iterable[int]) -> dict[int, str | None]:
    """Latest observation ``source_sha256`` per notice (``observed_at``, then id).

    A notice without any observation is absent; a legacy observation without a
    snapshot maps to ``None``. Neither is treated as a match.
    """

    ids = tuple(dict.fromkeys(notice_ids))
    if not ids:
        return {}
    latest: dict[int, tuple[datetime, int, str | None]] = {}
    for notice_id, observed_at, observation_id, source_sha256 in session.execute(
        select(
            NoticeObservation.notice_id,
            NoticeObservation.observed_at,
            NoticeObservation.id,
            NoticeObservation.source_sha256,
        ).where(NoticeObservation.notice_id.in_(ids))
    ).all():
        key = (_aware(observed_at), observation_id)
        current = latest.get(notice_id)
        if current is None or key > current[:2]:
            latest[notice_id] = (*key, source_sha256)
    return {notice_id: value[2] for notice_id, value in latest.items()}


def comparison_currentness(
    session: Session,
    opportunity_ids: Sequence[int],
    *,
    comparisons: Sequence[BidDeltaComparison] | None = None,
) -> dict[UUID, Currentness]:
    """Resolve the same strict currentness rules for a whole opportunity set.

    Explicit bulk selects avoid both per-notice lookups and relationship loader
    chunks. A caller with exact comparisons can reuse them without another read.
    """
    from .bid_delta import BASELINE_DOCUMENT_ROLES, COMPARISON_DOCUMENT_ROLES, _is_authoritative

    ids = tuple(dict.fromkeys(opportunity_ids))
    if not ids:
        return {}
    if comparisons is None:
        comparisons = session.scalars(select(BidDeltaComparison).where(BidDeltaComparison.opportunity_id.in_(ids))).all()
    if not comparisons:
        return {}
    links = session.scalars(select(OpportunityLink).where(
        OpportunityLink.opportunity_id.in_(ids), OpportunityLink.notice_id.is_not(None)
    )).all()
    notice_ids = {c.baseline_notice_id for c in comparisons} | {c.comparison_notice_id for c in comparisons}
    notice_ids.update(link.notice_id for link in links)
    notices = {n.id: n for n in session.scalars(select(Notice).where(Notice.id.in_(notice_ids))).all()}
    by_opportunity = defaultdict(list)
    for link in links:
        if _is_authoritative(link):
            notice = notices.get(link.notice_id)
            if notice is not None and notice.source_type == "bid_notice":
                by_opportunity[link.opportunity_id].append(notice)
    ready = defaultdict(list)
    for bundle, item, document, structure in session.execute(
        select(DocumentBundle, DocumentBundleItem, DocumentVersion, DocumentStructure)
        .join(DocumentBundleItem, DocumentBundleItem.bundle_id == DocumentBundle.id)
        .join(DocumentVersion, DocumentVersion.id == DocumentBundleItem.document_version_id)
        .join(DocumentStructure, DocumentStructure.id == DocumentBundleItem.structure_id_at_confirmation)
        .where(DocumentBundle.notice_id.in_(notice_ids), DocumentBundle.status == "ready",
            DocumentBundleItem.role_at_confirmation.in_(COMPARISON_DOCUMENT_ROLES),
            DocumentBundleItem.safety_status_at_confirmation == "safe",
            DocumentVersion.safety_status == "safe", DocumentStructure.validation_status == "ready")
    ).all():
        if structure.source_sha256 == item.content_sha256 and structure.payload_sha256 == item.structure_payload_sha256:
            ready[bundle.notice_id].append((bundle, item, document))

    def resolve(comparison):
        captured = notices.get(comparison.comparison_notice_id)
        if captured is None or captured.published_at is None:
            return "unknown", ["ordering_unknown"]
        # Keep the existing early-return rules. SQL order is not a semantic
        # chronology; published_at alone determines whether a notice is newer.
        for notice in by_opportunity[comparison.opportunity_id]:
            if notice.published_at is None:
                return "unknown", ["ordering_unknown"]
            if notice.id != captured.id and _aware(notice.published_at) > _aware(captured.published_at):
                return "stale", ["newer_bid_notice"]
        for side, roles in (("baseline", BASELINE_DOCUMENT_ROLES), ("comparison", COMPARISON_DOCUMENT_ROLES)):
            for bundle, item, document in ready[getattr(comparison, f"{side}_notice_id")]:
                if item.role_at_confirmation not in roles:
                    continue
                captured_bundle = (getattr(comparison, f"{side}_bundle_revision"), getattr(comparison, f"{side}_bundle_version"))
                if (bundle.revision, bundle.version) > captured_bundle or (
                    document.id != getattr(comparison, f"{side}_document_version_id")
                    and document.version > getattr(comparison, f"{side}_document_version_version")
                ):
                    return "stale", ["newer_ready_document_version"]
        return "current", []

    return {comparison.id: resolve(comparison) for comparison in comparisons}


def notice_conditions_currentness(
    session: Session,
    opportunity_ids: Sequence[int],
    decisions: Sequence[Any],
) -> dict[UUID, Currentness]:
    """Currentness of ``notice_conditions`` decisions (ADR-0058).

    ``stale`` is certain evidence: a newer authoritative bid notice than the
    basis notice, or a latest observation hash that differs from the recorded
    one. ``unknown`` means that order or hash cannot be established. A certain
    stale reason wins over an unknown one; ``current`` needs neither.
    """

    if not decisions:
        return {}
    bids = authoritative_bid_notices(session, opportunity_ids)
    basis_ids = {decision.basis_notice_id for decision in decisions}
    basis_notices = {
        notice.id: notice
        for notice in session.scalars(select(Notice).where(Notice.id.in_(basis_ids))).all()
    }
    hashes = latest_observation_hashes(session, basis_ids)

    def resolve(decision: Any) -> Currentness:
        stale: list[str] = []
        unknown: list[str] = []
        basis = basis_notices.get(decision.basis_notice_id)
        if basis is None or basis.published_at is None:
            unknown.append("ordering_unknown")
        else:
            for notice in bids.get(decision.opportunity_id, []):
                if notice.id == basis.id:
                    continue
                newer = is_newer_bid_notice(notice, basis)
                if newer is True and "newer_bid_notice" not in stale:
                    stale.append("newer_bid_notice")
                elif newer is None and "ordering_unknown" not in unknown:
                    unknown.append("ordering_unknown")
        observed = hashes.get(decision.basis_notice_id)
        if observed is None:
            unknown.append("observation_unknown")
        elif observed != decision.basis_observation_sha256:
            stale.append("notice_observation_changed")
        if stale:
            return "stale", stale
        if unknown:
            return "unknown", unknown
        return "current", []

    return {decision.id: resolve(decision) for decision in decisions}


def decision_currentness(
    session: Session,
    opportunity_ids: Sequence[int],
    decisions: Sequence[BidFinalDecision],
    *,
    comparisons: Sequence[BidDeltaComparison] | None = None,
) -> dict[UUID, Currentness]:
    """Basis-aware currentness for final decisions, keyed by decision ID.

    A comparison decision keeps the comparison rule unchanged; a comparison row
    that cannot be read is ``unknown`` rather than current.
    """

    by_comparison = [decision for decision in decisions if decision.basis_kind == "comparison"]
    by_notice = [decision for decision in decisions if decision.basis_kind == "notice_conditions"]
    result: dict[UUID, Currentness] = {}
    if by_comparison:
        if comparisons is None:
            comparisons = session.scalars(select(BidDeltaComparison).where(
                BidDeltaComparison.id.in_({decision.comparison_id for decision in by_comparison})
            )).all()
        states: Mapping[UUID, Currentness] = comparison_currentness(session, opportunity_ids, comparisons=comparisons)
        for decision in by_comparison:
            state = states.get(decision.comparison_id)  # type: ignore[arg-type]
            result[decision.id] = state if state is not None else ("unknown", ["comparison_unavailable"])
    result.update(notice_conditions_currentness(session, opportunity_ids, by_notice))
    for decision in decisions:
        result.setdefault(decision.id, ("unknown", ["basis_unknown"]))
    return result


__all__ = [
    "authoritative_bid_notices",
    "comparison_currentness",
    "decision_currentness",
    "is_newer_bid_notice",
    "latest_bid_notice",
    "latest_observation_hashes",
    "notice_conditions_currentness",
]
