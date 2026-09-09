"""Batch projection of immutable bid comparisons against currently ready inputs."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...lifecycle.models import Notice, OpportunityLink
from ..models import BidDeltaComparison, DocumentBundle, DocumentBundleItem, DocumentStructure, DocumentVersion


def comparison_currentness(
    session: Session,
    opportunity_ids: Sequence[int],
    *,
    comparisons: Sequence[BidDeltaComparison] | None = None,
) -> dict[UUID, tuple[str, list[str]]]:
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

    def aware(value):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def resolve(comparison):
        captured = notices.get(comparison.comparison_notice_id)
        if captured is None or captured.published_at is None:
            return "unknown", ["ordering_unknown"]
        # Keep the existing early-return rules. SQL order is not a semantic
        # chronology; published_at alone determines whether a notice is newer.
        for notice in by_opportunity[comparison.opportunity_id]:
            if notice.published_at is None:
                return "unknown", ["ordering_unknown"]
            if notice.id != captured.id and aware(notice.published_at) > aware(captured.published_at):
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
