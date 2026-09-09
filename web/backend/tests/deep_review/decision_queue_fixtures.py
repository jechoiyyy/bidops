"""Synthetic exact input fixtures for decision queue/currentness tests."""
from datetime import UTC, datetime
import hashlib
from uuid import uuid4
from sqlalchemy.orm import Session
from app.lifecycle.models import Notice, Opportunity, OpportunityLink
from app.deep_review.models import (BidDeltaComparison, BidFinalDecision, ContentObject,
    DocumentBundle, DocumentBundleItem, DocumentStructure, DocumentVersion)

NOW = datetime(2026, 9, 7, tzinfo=UTC)

def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _input(session: Session, opportunity: Opportunity, label: str, source_type: str, role: str, published_at: datetime | None):
    source_sha = _sha(f"{label}:source")
    payload_sha = _sha(f"{label}:structure")
    notice = Notice(
        notice_key=f"bid-delta-api:{label}:{uuid4()}",
        source_type=source_type,
        bid_ord=None if source_type == "pre_spec" else "not-an-ordinal",
        published_at=published_at,
    )
    session.add(notice)
    session.flush()
    link = OpportunityLink(
        opportunity_id=opportunity.id,
        notice_id=notice.id,
        stage="notice",
        link_type="official",
        status="확정",
        evidence_external_no=f"external:{label}",
    )
    content = ContentObject(
        sha256=source_sha,
        size_bytes=10,
        detected_mime="application/pdf",
        retention_class="document-source",
    )
    session.add_all([link, content])
    session.flush()
    document = DocumentVersion(
        notice_id=notice.id,
        content_object_id=content.id,
        version=1,
        source_kind="manual",
        original_filename=f"{label}.pdf",
        role=role,
        is_current=True,
        safety_status="safe",
        needs_human_review=False,
    )
    session.add(document)
    session.flush()
    structure = DocumentStructure(
        document_version_id=document.id,
        source_sha256=source_sha,
        media_type="application/pdf",
        extractor_name="fixture",
        extractor_version="1",
        payload_content_object_id=content.id,
        payload_sha256=payload_sha,
        page_count=1,
        block_count=1,
        validation_status="ready",
    )
    bundle = DocumentBundle(
        notice_id=notice.id,
        revision=1,
        version=1,
        status="ready",
        issues_snapshot=[],
    )
    session.add_all([structure, bundle])
    session.flush()
    item = DocumentBundleItem(
        bundle_id=bundle.id,
        document_version_id=document.id,
        ordinal=1,
        document_version_version=1,
        content_object_id=content.id,
        content_sha256=source_sha,
        detected_mime="application/pdf",
        size_bytes=10,
        original_filename=f"{label}.pdf",
        source_kind="manual",
        role_at_confirmation=role,
        is_current_at_confirmation=True,
        safety_status_at_confirmation="safe",
        structure_id_at_confirmation=structure.id,
        structure_payload_sha256=payload_sha,
    )
    session.add(item)
    session.flush()
    return {"notice": notice, "link": link, "content": content, "document": document, "structure": structure, "bundle": bundle, "item": item}


def opportunity(session, *, created_at=NOW, tracking="계속 추적"):
    row = Opportunity(first_registered_stage="pre_spec", tracking_status=tracking, created_at=created_at,
        tracking_selected_by="fixture" if tracking != "미선택" else None,
        tracking_selected_at=NOW if tracking != "미선택" else None)
    session.add(row)
    session.flush()
    return row


def comparison(session, row):
    base = _input(session, row, str(uuid4()), "pre_spec", "제안요청서", NOW)
    bid = _input(session, row, str(uuid4()), "bid_notice", "공고", NOW)
    fields = {}
    for side, source in (("baseline", base), ("comparison", bid)):
        fields.update({f"{side}_link_id": source["link"].id, f"{side}_notice_id": source["notice"].id,
            f"{side}_bundle_id": source["bundle"].id, f"{side}_bundle_revision": 1,
            f"{side}_bundle_version": 1, f"{side}_document_version_id": source["document"].id,
            f"{side}_document_version_version": 1, f"{side}_structure_id": source["structure"].id,
            f"{side}_source_sha256": source["content"].sha256,
            f"{side}_structure_payload_sha256": source["structure"].payload_sha256})
    result = BidDeltaComparison(opportunity_id=row.id, sequence=1, version=1,
        category_policy_version="bid-delta-policy.v1", calculation_status="pending",
        materiality="unknown", created_by_name="fixture", **fields)
    session.add(result)
    session.flush()
    return result, base, bid


def decide(session, row, compared, *, sequence=1, supersedes=None, decision="go"):
    result = BidFinalDecision(opportunity_id=row.id, sequence=sequence, comparison_id=compared.id,
        comparison_version=compared.version, result_sha256="a" * 64,
        baseline_document_version_id=compared.baseline_document_version_id,
        comparison_document_version_id=compared.comparison_document_version_id,
        supersedes_final_decision_id=supersedes, decision=decision, reason="fixture",
        claimed_name="reviewer", request_id=uuid4(), created_at=NOW)
    session.add(result)
    session.flush()
    return result


def ready_candidate(session, side, **overrides):
    content = ContentObject(sha256=hashlib.sha256(str(uuid4()).encode()).hexdigest(), size_bytes=1,
        detected_mime="application/pdf", retention_class="document-source")
    session.add(content)
    session.flush()
    document = DocumentVersion(notice_id=side["notice"].id, content_object_id=content.id,
        version=overrides.get("document_version", 2), source_kind="manual", original_filename="fixture.pdf",
        role=side["document"].role, is_current=True,
        safety_status=overrides.get("document_safety", "safe"), needs_human_review=False)
    session.add(document)
    session.flush()
    structure = DocumentStructure(document_version_id=document.id, source_sha256=content.sha256,
        media_type="application/pdf", extractor_name="fixture", extractor_version="1",
        payload_content_object_id=content.id, payload_sha256="d"*64, page_count=1, block_count=1,
        validation_status=overrides.get("structure_status", "ready"))
    bundle = side["bundle"] if overrides.get("reuse_bundle") else DocumentBundle(
        notice_id=side["notice"].id, revision=2, version=1,
        status=overrides.get("bundle_status", "ready"), issues_snapshot=[])
    session.add_all([structure, bundle])
    session.flush()
    item = DocumentBundleItem(bundle_id=bundle.id, document_version_id=document.id,
        ordinal=2 if overrides.get("reuse_bundle") else 1,
        document_version_version=document.version, content_object_id=content.id,
        content_sha256=overrides.get("source_hash", content.sha256), detected_mime="application/pdf",
        size_bytes=1, original_filename="fixture.pdf", source_kind="manual",
        role_at_confirmation=overrides.get("role", side["document"].role), is_current_at_confirmation=True,
        safety_status_at_confirmation=overrides.get("snapshot_safety", "safe"),
        structure_id_at_confirmation=structure.id,
        structure_payload_sha256=overrides.get("payload_hash", structure.payload_sha256))
    session.add(item)
    session.flush()
    return bundle, item, document, structure
