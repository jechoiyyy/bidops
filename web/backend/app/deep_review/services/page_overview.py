"""Import/read frozen page summaries without invoking a model or lifecycle hook."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.models import AuditEvent
from ...core.object_store import ObjectStore
from ...lifecycle.models import Notice
from ..models import ContentObject, ContentObjectLocation, ContentScan, DocumentVersion, PreSpecPageOverview
from ..schemas.page_overview import PageOverviewPayload, PageOverviewResponse, PageOverviewView
from .page_overview_validation import VALIDATOR_VERSION, fold_space, validate_page_overview


class PageOverviewError(ValueError):
    """Only stable codes may leave this boundary."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise PageOverviewError(code)


def require_notice(session: Session, notice_id: int) -> None:
    notice = session.get(Notice, notice_id)
    require(notice is not None and notice.source_type == "pre_spec", "not_found")


def verified_input_pages(record: dict, pdf: bytes, pdf_pages: list[str]) -> dict[int, str]:
    require(digest(pdf) == record["pdf_sha256"] and pdf.startswith(b"%PDF-"), "pdf_hash_mismatch")
    require(type(record["pdf_pages"]) is int and len(pdf_pages) == record["pdf_pages"] > 0, "pdf_page_count_mismatch")
    selected = record["selected_pages"]
    require(isinstance(selected, list) and bool(selected) and all(type(n) is int and 1 <= n <= len(pdf_pages) for n in selected) and len(set(selected)) == len(selected), "input_pages_invalid")
    blocks = record["model_input"]["blocks"]
    require(len(blocks) == len(selected) and {b["pdf_page"] for b in blocks} == set(selected), "input_pages_invalid")
    pages: dict[int, str] = {}
    for block in blocks:
        n = block["pdf_page"]
        require(type(n) is int and isinstance(block["text"], str) and bool(fold_space(block["text"])), "input_pages_invalid")
        # A page input may be a bounded slice; its actual bytes must come from this PDF page.
        require(fold_space(block["text"]) in fold_space(pdf_pages[n - 1]), "pdf_text_mismatch")
        pages[n] = block["text"]
    return pages


def import_page_overview(
    session: Session, *, record: dict, output: dict, manifest: dict, outcome: dict,
    pdf: bytes, pdf_pages: list[str], store: ObjectStore, scanner: Any, actor: str,
) -> tuple[PreSpecPageOverview, bool]:
    """Caller verifies frozen prompt binding and extracts pages in a bounded worker.

    Failed historical validation remains failed even if the revised evidence checks
    pass. No recommendation or existing review/attempt is written here.
    """
    payload = PageOverviewPayload.model_validate(output)
    notice_id = record["notice_id"]
    require(type(notice_id) is int and notice_id > 0, "invalid_notice")
    require_notice(session, notice_id)
    require(bool(actor.strip()) and actor.strip().casefold() != "system" and len(actor) <= 200 and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in actor), "invalid_actor")
    document = session.scalar(select(DocumentVersion).where(DocumentVersion.id == UUID(record["document_version_id"])).with_for_update())
    require(document is not None and document.notice_id == notice_id and document.safety_status == "safe", "document_scope_mismatch")
    source = session.get(ContentObject, document.content_object_id)
    require(source is not None and source.sha256 == record["source_sha256"], "source_hash_mismatch")
    require(manifest["schema_version"] == "bidops.prespec-overview-page-run.v1", "run_schema_invalid")
    require(manifest["quality_status"] in {"unmeasured_reference", "mock_reference"}, "quality_invalid")
    bindings = [x for x in manifest["inputs"] if x["notice_id"] == notice_id]
    require(len(bindings) == 1, "input_binding_mismatch")
    binding = bindings[0]
    for name in ("source_sha256", "pdf_sha256"):
        require(binding[name] == record[name], "input_binding_mismatch")
    require(outcome["notice_id"] == notice_id and outcome["prompt_sha256"] == binding["prompt_sha256"], "output_binding_mismatch")
    require(outcome["status"] in {"validation_failed", "evidence_checks_passed"}, "output_status_invalid")
    original_errors = outcome["validation_errors"]
    require(isinstance(original_errors, list) and all(isinstance(c, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,100}", c) for c in original_errors), "error_codes_invalid")
    require(bool(original_errors) == (outcome["status"] == "validation_failed"), "output_status_invalid")
    for value in (record["source_sha256"], record["pdf_sha256"], binding["prompt_sha256"], manifest["model_digest"], manifest["policy_digest"]):
        require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "digest_invalid")
    pages = verified_input_pages(record, pdf, pdf_pages)
    errors = validate_page_overview(output, pages)
    identity = digest(canonical({"record": record, "output": output, "manifest": manifest, "outcome": outcome}))
    run_id = UUID(manifest["run_id"])
    existing = session.scalar(select(PreSpecPageOverview).where(PreSpecPageOverview.run_id == run_id, PreSpecPageOverview.notice_id == notice_id))
    if existing:
        require(existing.import_sha256 == identity, "idempotency_conflict")
        return existing, False
    # Scan exact PDF bytes; a unavailable/infected scanner never creates a visible row.
    require(scanner.scan(pdf) is True, "unsafe_pdf")
    metadata = store.put("source", f"source/page-overview/{uuid4().hex}.pdf", pdf, content_type="application/pdf")
    require(bool(metadata.object_version_id), "pdf_version_missing")
    pdf_content = session.scalar(select(ContentObject).where(ContentObject.sha256 == digest(pdf)))
    if pdf_content is None:
        pdf_content = ContentObject(sha256=digest(pdf), size_bytes=len(pdf), detected_mime="application/pdf", retention_class="overview-reference-pdf")
        session.add(pdf_content)
        session.flush()
    require(pdf_content.size_bytes == len(pdf) and pdf_content.detected_mime == "application/pdf", "pdf_content_mismatch")
    location = ContentObjectLocation(content_object_id=pdf_content.id, namespace_key="source", object_key=metadata.object_key,
                                    object_version_id=metadata.object_version_id, etag=metadata.etag, status="verified", verified_at=datetime.now(UTC))
    session.add(location)
    session.add(ContentScan(content_object_id=pdf_content.id, scanner="clamav", scanner_version=scanner.version, status="clean", safe_result={}))
    session.flush()
    frozen = canonical({"record": record, "manifest": manifest, "outcome": outcome})
    input_meta = store.put("structure", f"structure/page-overview/{uuid4().hex}.json", frozen, content_type="application/json")
    require(bool(input_meta.object_version_id), "input_version_missing")
    input_content = session.scalar(select(ContentObject).where(ContentObject.sha256 == digest(frozen)))
    if input_content is None:
        input_content = ContentObject(sha256=digest(frozen), size_bytes=len(frozen), detected_mime="application/json", retention_class="overview-page-input")
        session.add(input_content)
        session.flush()
    input_location = ContentObjectLocation(content_object_id=input_content.id, namespace_key="structure", object_key=input_meta.object_key,
                                           object_version_id=input_meta.object_version_id, etag=input_meta.etag, status="verified", verified_at=datetime.now(UTC))
    session.add(input_location)
    session.flush()
    row = PreSpecPageOverview(
        run_id=run_id, notice_id=notice_id, document_version_id=document.id, pdf_location_id=location.id, input_location_id=input_location.id,
        schema_version=payload.schema_version, source_sha256=record["source_sha256"], pdf_sha256=digest(pdf),
        payload_sha256=digest(canonical(output)), import_sha256=identity, input_sha256=binding["prompt_sha256"],
        model_digest=manifest["model_digest"], policy_digest=manifest["policy_digest"], model_name=manifest["model"],
        prompt_version=manifest["prompt_version"], pdf_page_count=len(pdf_pages), reviewed_pages=record["selected_pages"],
        payload_jsonb=output, validation_status="failed" if original_errors or errors else "passed",
        validation_errors=sorted(set(original_errors) | set(errors)), evidence_check_status="failed" if errors else "passed",
        evidence_check_errors=errors, validator_version=VALIDATOR_VERSION, quality_status=manifest["quality_status"],
    )
    session.add(row)
    session.flush()
    session.add(AuditEvent(actor_kind="human", claimed_name=actor, action="prespec_overview.page_import",
                           aggregate_type="prespec_page_overview", aggregate_id=str(row.id),
                           safe_metadata={"notice_id": notice_id, "payload_sha256": row.payload_sha256,
                                          "validation_status": row.validation_status, "quality_status": row.quality_status}))
    return row, True


def list_page_overviews(session: Session, notice_id: int) -> PageOverviewResponse:
    require_notice(session, notice_id)
    rows = session.scalars(select(PreSpecPageOverview).where(PreSpecPageOverview.notice_id == notice_id)
                           .order_by(PreSpecPageOverview.created_at.desc(), PreSpecPageOverview.id.desc()).limit(20)).all()
    views = []
    for row in rows:
        require(digest(canonical(row.payload_jsonb)) == row.payload_sha256, "result_integrity_failed")
        fields = {name: getattr(row, name) for name in PageOverviewView.model_fields if name != "payload"}
        views.append(PageOverviewView(**fields, payload=PageOverviewPayload.model_validate(row.payload_jsonb)))
    return PageOverviewResponse(notice_id=notice_id, reviews=views)


def get_page_pdf(session: Session, notice_id: int, review_id: UUID, store: ObjectStore) -> bytes:
    require_notice(session, notice_id)
    row = session.get(PreSpecPageOverview, review_id)
    require(row is not None and row.notice_id == notice_id, "not_found")
    location = session.get(ContentObjectLocation, row.pdf_location_id)
    require(location is not None and location.status == "verified" and location.namespace_key == "source" and bool(location.object_version_id), "pdf_unavailable")
    content = session.get(ContentObject, location.content_object_id)
    require(content is not None and content.sha256 == row.pdf_sha256 and content.detected_mime == "application/pdf", "pdf_integrity_failed")
    latest_scan = session.scalar(select(ContentScan).where(ContentScan.content_object_id == content.id)
                                 .order_by(ContentScan.scanned_at.desc(), ContentScan.id.desc()).limit(1))
    require(latest_scan is not None and latest_scan.status == "clean", "pdf_unavailable")
    data, meta = store.get("source", location.object_key, version_id=location.object_version_id)
    require(meta.object_version_id == location.object_version_id and meta.etag == location.etag and len(data) == content.size_bytes and digest(data) == row.pdf_sha256, "pdf_integrity_failed")
    return data
