"""Human requests and safe projections for company wiki ingest."""
from collections import Counter
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import re
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from ...core.config import get_settings
from ...core.models import AuditEvent
from ...core.object_store import object_store
from ..document_mcp.safety import detect_media_type
from ..document_mcp.errors import DocumentProcessingError
from ..models import CompanyWikiIngestRun as Run, WorkJob
from ..schemas.company_wiki_ingests import IngestDetail, IngestSummary
from . import attachments
from .company_wiki import CompanyWiki, WikiError

NAMESPACE = "company-wiki-ingest"
TERMINAL = ("applied", "rejected", "failed", "aborted")
MEDIA = {".pdf": "application/pdf", ".hwpx": "application/hwp+zip", ".hwp": "application/x-hwp"}


class IngestError(WikiError):
    pass


def project(wiki, project_id):
    for record in wiki.records:
        if record["id"] == project_id:
            return wiki.public_prose(record["title"])
    raise IngestError("project_not_registered", 422)


def transition(session, row, status, actor, *, human=False):
    row.status = status
    row.updated_at = datetime.now(UTC)
    session.add(AuditEvent(actor_kind="human" if human else "system", claimed_name=actor,
                           action=f"company_wiki_ingest.{status}", aggregate_type="company_wiki_ingest",
                           aggregate_id=str(row.id), request_id=str(row.request_id),
                           safe_metadata={"status": status, "error_code": row.error_code}))


def enqueue(session, row):
    session.add(WorkJob(id=uuid4(), job_type=NAMESPACE, aggregate_type="company_wiki_ingest",
                        aggregate_id=row.id, status="queued", max_attempts=1))


def detail(row):
    review = row.review_input or {}
    names = review.get("names", {})
    titles = review.get("titles", {})
    result = row.mapping or {}
    assignments = result.get("assignments", [])
    counts = Counter(uid for a in assignments for uid in a["units"])
    return IngestDetail(
        **IngestSummary.model_validate(row).model_dump(),
        classification_attempts=row.classification_attempts,
        units=[{"id": uid, "title": titles[uid], "count": count} for uid, count in sorted(counts.items())],
        assignments=[{"req_id": a["req_id"], "name": names[a["req_id"]],
                      "unit_titles": [titles[uid] for uid in a["units"]]} for a in assignments],
        new_units=result.get("new_units", []),
        unassigned_count=sum(not a["units"] for a in assignments) if row.mapping else None,
        unlisted_id_count=row.document_requirement_ids_unlisted,
        apply_allowed=(row.status == "awaiting_review" and get_settings().company_wiki_ingest_apply_reference_enabled),
        **{key: getattr(row, key) for key in ("wiki_sha256_before", "wiki_sha256_after", "backup_name",
           "created_by_name", "decided_by_name", "decision_reason", "decided_at", "applied_at")},
    )


def get_run(session, run_id, *, lock=False):
    row = session.get(Run, run_id, with_for_update=lock, populate_existing=True)
    if row is None:
        raise IngestError("not_found", 404)
    return row


def list_runs(session, limit, offset):
    rows = session.scalars(select(Run).options(defer(Run.mapping), defer(Run.review_input))
                           .order_by(Run.created_at.desc(), Run.id.desc()).limit(limit).offset(offset))
    return {"items": [IngestSummary.model_validate(r) for r in rows],
            "total": session.scalar(select(func.count()).select_from(Run))}


def create(session, project_id, upload, request_id, actor):
    filename = upload.filename or ""
    media = MEDIA.get(Path(filename).suffix.lower())
    if not media or re.search(r"[/\\\x00-\x1f\x7f]", filename) or len(filename) > 255:
        raise IngestError("unsupported_extension", 422)
    raw = upload.file.read(attachments.MAX_ATTACHMENT_SIZE + 1)
    if len(raw) > attachments.MAX_ATTACHMENT_SIZE:
        raise IngestError("input_size_limit", 413)
    if not raw or not re.fullmatch(r"P[0-9]{4}-[0-9]{2}", project_id):
        raise IngestError("invalid_request", 422)
    try:
        if detect_media_type(raw, None) != media:
            raise IngestError("mime_mismatch", 422)
    except DocumentProcessingError:
        raise IngestError("mime_mismatch", 422) from None
    digest = hashlib.sha256(raw).hexdigest()

    def replay():
        previous = session.scalar(select(Run).where(Run.request_id == request_id))
        if previous and (previous.project_id, previous.created_by_name, previous.source_filename,
                         previous.source_sha256) != (project_id, actor, filename, digest):
            raise IngestError("idempotency_conflict", 409)
        return previous

    previous = replay()
    if previous:
        return detail(previous)
    title = project(CompanyWiki(), project_id)
    run_id = uuid4()
    key = f"{NAMESPACE}/{run_id}/source"
    row = Run(id=run_id, request_id=request_id, project_id=project_id, project_title=title,
              source_filename=filename, source_sha256=digest, source_size_bytes=len(raw),
              source_media_type=media, source_object_key=key, quality_status="mock_reference",
              created_by_name=actor, classification_attempts=0)
    store = object_store(namespaces=(NAMESPACE,))
    meta = store.put(NAMESPACE, key, raw, content_type=media)
    try:
        if not meta.object_version_id or meta.object_version_id == "null":
            raise IngestError("storage_unavailable", 503)
        row.source_object_version = meta.object_version_id
        session.add(row)
        transition(session, row, "queued", actor, human=True)
        enqueue(session, row)
        session.commit()
    except Exception as exc:
        session.rollback()
        store.delete_ingest_version(key, meta.object_version_id or "null")
        if isinstance(exc, IntegrityError):
            previous = replay()
            if previous:
                return detail(previous)
            if session.scalar(select(Run.id).where(Run.project_id == project_id, Run.status.not_in(TERMINAL))):
                raise IngestError("ingest_in_progress", 409) from None
        raise
    return detail(row)


def decide(session, run_id, payload, actor, *, approve):
    row = get_run(session, run_id, lock=True)
    if row.status != payload.expected_status:
        raise IngestError("status_conflict", 409)
    if approve and not get_settings().company_wiki_ingest_apply_reference_enabled:
        raise IngestError("reference_apply_disabled", 409)
    row.decided_at = datetime.now(UTC)
    row.decided_by_name = actor
    if approve:
        enqueue(session, row)
    else:
        row.decision_reason = payload.reason
    transition(session, row, "approved" if approve else "rejected", actor, human=True)
    session.commit()
    return detail(row)
