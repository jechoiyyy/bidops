"""Inspect current inputs and build metadata-only approval manifests."""

from collections import defaultdict
import hashlib
from pathlib import Path

from sqlalchemy import and_, func, select

from ...core.config import get_settings
from ...core.model_binding import canonical_json_bytes
from ...lifecycle import lock_active_attachments
from ...lifecycle.models import Attachment
from ..document_mcp.errors import DocumentProcessingError
from ..models import (
    AttachmentFetch, ContentObjectLocation, ContentScan, DocumentBundle, DocumentBundleItem,
    DocumentStructure, DocumentVersion,
)
from . import engine_runs
from .assets import AssetError, read_object
from .engine_runs import EngineRunError

HWP_FORMATS = {"hwp", "hwpx"}


def _is_hwp_original(filename):
    return Path(filename).suffix.lower().lstrip(".") in HWP_FORMATS


def has_unverified_page_count(manifest):
    """Older manifests copied logical HWP/HWPX section counts into this field."""
    return any(
        _is_hwp_original(document["filename"]) and document["page_count"] is not None
        for document in manifest["documents"]
    )


def digest(manifest):
    return hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()


def load_company():
    bundle = engine_runs.company_bundle()
    if bundle is None:
        raise EngineRunError("company_bundle_unavailable")
    slug = get_settings().engine_company_bundle_slug
    return {**bundle, "slug": slug}


def company_metadata(company):
    return engine_runs.preview_input({
        "schema_version": "bidops.engine-input.v3",
        "mode": "mock_reference",
        "company_bundle": company,
    })


def latest_ready_many(session, notice_ids):
    if not notice_ids:
        return {}
    latest = (
        select(DocumentBundle.notice_id, func.max(DocumentBundle.revision).label("revision"))
        .where(DocumentBundle.notice_id.in_(notice_ids), DocumentBundle.status == "ready")
        .group_by(DocumentBundle.notice_id)
        .subquery()
    )
    return {
        row.notice_id: row
        for row in session.scalars(
            select(DocumentBundle).join(
                latest,
                and_(latest.c.notice_id == DocumentBundle.notice_id, latest.c.revision == DocumentBundle.revision),
            )
        )
    }


def _bundle_documents(session, bundles):
    grouped = defaultdict(list)
    for item, document, structure in session.execute(
        select(DocumentBundleItem, DocumentVersion, DocumentStructure)
        .join(DocumentVersion, DocumentVersion.id == DocumentBundleItem.document_version_id)
        .outerjoin(DocumentStructure, DocumentStructure.id == DocumentBundleItem.structure_id_at_confirmation)
        .where(DocumentBundleItem.bundle_id.in_([bundle.id for bundle in bundles]))
        .order_by(DocumentBundleItem.ordinal)
        .execution_options(populate_existing=True)
    ):
        grouped[item.bundle_id].append((item, document, structure))
    return grouped


def _locations(session, rows):
    content_ids = {
        content_id
        for item, _, structure in rows
        for content_id in (item.content_object_id, structure.payload_content_object_id if structure else None)
        if content_id is not None
    }
    locations = {}
    for location in session.scalars(
        select(ContentObjectLocation).where(
            ContentObjectLocation.content_object_id.in_(content_ids),
            ContentObjectLocation.namespace_key.in_(("source", "structure")),
            ContentObjectLocation.status == "verified",
        ).order_by(ContentObjectLocation.verified_at.desc(), ContentObjectLocation.id.desc())
    ):
        locations.setdefault((location.content_object_id, location.namespace_key), location)
    return locations


def _latest_scan_statuses(session, rows):
    content_ids = {item.content_object_id for item, _, _ in rows}
    statuses = {}
    for content_id, status in session.execute(select(ContentScan.content_object_id, ContentScan.status)
        .where(ContentScan.content_object_id.in_(content_ids))
        .order_by(ContentScan.scanned_at.desc(), ContentScan.id.desc())
    ):
        statuses.setdefault(content_id, status)
    return statuses


def _pinned_location(locations, content_id, namespace):
    location = locations.get((content_id, namespace))
    return location if location and location.object_version_id else None


def _check_bundle(bundle, rows, locations, scans):
    if not rows:
        raise EngineRunError("structure_unavailable")
    formats = set()
    for item, document, structure in rows:
        if not document.is_current or document.version != item.document_version_version:
            raise EngineRunError("documents_pending")
        if not item.structure_id_at_confirmation or not structure:
            raise EngineRunError("structure_unavailable")
        formats.add(engine_runs.check_document(item, document, structure, bundle.notice_id))
        if scans.get(item.content_object_id) != "clean":
            raise EngineRunError("unsafe_document")
        if not _pinned_location(locations, structure.payload_content_object_id, "structure") or not structure.block_count:
            raise EngineRunError("structure_unavailable")
    if not formats & HWP_FORMATS:
        raise EngineRunError("original_hwp_required")
    for item, document, _ in rows:
        if (item.content_object_id != document.content_object_id
                or not _pinned_location(locations, item.content_object_id, "source")):
            raise EngineRunError("original_hwp_required")


def _unready_reasons(session, notice_ids):
    if not notice_ids:
        return {}
    attachments = defaultdict(list)
    for notice_id, status in session.execute(
        select(Attachment.notice_id, AttachmentFetch.status)
        .outerjoin(AttachmentFetch, AttachmentFetch.attachment_id == Attachment.id)
        .where(Attachment.notice_id.in_(notice_ids), Attachment.retired_at.is_(None))
    ):
        attachments[notice_id].append(status)
    documents = defaultdict(list)
    for doc, status in session.execute(
        select(DocumentVersion, DocumentStructure.validation_status)
        .outerjoin(DocumentStructure, DocumentStructure.document_version_id == DocumentVersion.id)
        .where(DocumentVersion.notice_id.in_(notice_ids), DocumentVersion.is_current.is_(True))
    ):
        documents[doc.notice_id].append((doc, status))
    result = {}
    for notice_id in notice_ids:
        docs, fetches = documents[notice_id], attachments[notice_id]
        has_original = any(_is_hwp_original(doc.original_filename) for doc, _ in docs)
        if any(doc.safety_status == "blocked" for doc, _ in docs) or "차단" in fetches:
            reason = "unsafe_document"
        elif any(status in {"failed", "needs_review"} for _, status in docs):
            reason = "structure_unavailable"
        elif not has_original and all(status in {"완료", "실패"} for status in fetches):
            reason = "original_hwp_required"
        else:
            reason = "documents_pending"
        result[notice_id] = reason
    return result


def _check_attachment_scope(attachments, rows):
    pinned_attachments = {doc.attachment_id for _, doc, _ in rows if doc.attachment_id is not None}
    if pinned_attachments != attachments.keys():
        raise EngineRunError("documents_pending")
    for _, doc, _ in rows:
        attachment = attachments.get(doc.attachment_id)
        if attachment and doc.source_kind == "provider" and (
            doc.source_system, doc.source_attachment_key, doc.source_url,
        ) != (attachment.source_system, attachment.source_attachment_key, attachment.source_url):
            raise EngineRunError("documents_pending")


def readiness_many(session, notice_ids):
    """Check readiness metadata for a batch without loading document bodies."""
    bundles = latest_ready_many(session, notice_ids)
    rows = _bundle_documents(session, bundles.values()) if bundles else {}
    all_rows = [row for values in rows.values() for row in values]
    locations = _locations(session, all_rows) if all_rows else {}
    scans = _latest_scan_statuses(session, all_rows) if all_rows else {}
    attachments = defaultdict(dict)
    if bundles:
        for row in session.scalars(select(Attachment).where(
            Attachment.notice_id.in_(bundles.keys()), Attachment.retired_at.is_(None),
        )):
            attachments[row.notice_id][row.id] = row
    reasons = _unready_reasons(session, set(notice_ids) - bundles.keys())
    for notice_id, bundle in bundles.items():
        try:
            documents = rows.get(bundle.id, ())
            _check_bundle(bundle, documents, locations, scans)
            _check_attachment_scope(attachments[notice_id], documents)
            reasons[notice_id] = None
        except EngineRunError as error:
            reasons[notice_id] = error.code
    return bundles, reasons


def freeze(session, notice, company):
    """Re-read exact object versions and use the engine's real local selector."""
    bundle = latest_ready_many(session, [notice.id]).get(notice.id)
    if bundle is None:
        raise EngineRunError(_unready_reasons(session, [notice.id])[notice.id])
    # The attachment worker locks attachment → document while publishing
    # replacements. Use that same order under the caller's notice fence.
    attachments = {row.id: row for row in lock_active_attachments(session, notice.id)}
    pinned_ids = select(DocumentBundleItem.document_version_id).where(DocumentBundleItem.bundle_id == bundle.id)
    session.scalars(select(DocumentVersion.id).where(DocumentVersion.id.in_(pinned_ids))
                    .order_by(DocumentVersion.id).with_for_update()).all()
    rows = _bundle_documents(session, [bundle]).get(bundle.id, ())
    locations = _locations(session, rows)
    _check_bundle(bundle, rows, locations, _latest_scan_statuses(session, rows))
    _check_attachment_scope(attachments, rows)
    for item, _, _ in rows:
        location = locations[item.content_object_id, "source"]
        try:
            raw, _ = read_object("source", location.object_key, version_id=location.object_version_id)
        except AssetError:
            raise EngineRunError("original_hwp_required") from None
        if hashlib.sha256(raw).hexdigest() != item.content_sha256:
            raise EngineRunError("unsafe_document")
    try:
        frozen = engine_runs.wiki_input(
            session, notice, bundle, company=company, rows=rows, locations=locations,
        )
    except (AssetError, DocumentProcessingError, ValueError) as error:
        if isinstance(error, EngineRunError) and error.code != "structure_hash_mismatch":
            raise
        raise EngineRunError("structure_unavailable") from None
    try:
        selected = engine_runs.preview_input(frozen)
    except EngineRunError as error:
        if error.code in {"invalid_table_coordinates", "table_too_large", "engine_pipeline_failed"}:
            raise EngineRunError("structure_unavailable") from None
        raise
    frozen["company_name"] = selected["company_name"]
    manifest = {
        "schema_version": "bidops.engine-review-manifest.v1",
        "input_schema_version": frozen["schema_version"],
        "notice_id": notice.id,
        "title": frozen["title"],
        "bundle_id": str(bundle.id),
        "bundle_revision": bundle.revision,
        "primary_format": frozen["primary_format"],
        "engine_version": frozen["engine_version"],
        "engine_sha256": frozen["engine_sha256"],
        "mode": frozen["mode"],
        "policy": "mock_reference",
        "strategy": "single",
        "model": "mock_reference",
        "planned_calls": 0,
        "remaining_calls": 0,
        "company_bundle_slug": company["slug"],
        "company_bundle_sha256": company["bundle_sha256"],
        "documents": [
            {**lineage, "version": item.document_version_version,
             "filename": item.original_filename,
             # Both HWP paths use HWPX XML sections as logical structure pages.
             "page_count": None if _is_hwp_original(item.original_filename) else structure.page_count}
            for (item, _, structure), lineage in zip(rows, frozen["documents"], strict=True)
        ],
        **{key: selected[key] for key in ("sections", "wiki_pages", "wiki_pages_skipped", "wiki_chars")},
    }
    return frozen, manifest
