"""BidOps authority → frozen input → WorkJob → isolated engine → immutable result.

No policy activation, live model transport, company write, or human review write.
The offline baseline is always mock_reference and its conservative projection
remains partial, including when every engine stage completed successfully.
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from sqlalchemy import select, or_, and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ...core.config import get_settings
from ...core.models import AuditEvent
from ...core.model_binding import canonical_json_bytes
from ...core.object_store import object_store
from ...lifecycle.models import Notice
from ..models import (
    EngineRun,
    WorkJob,
    DocumentBundle,
    DocumentBundleItem,
    DocumentVersion,
    DocumentStructure,
    DocumentBlock,
    ContentObject,
    ContentObjectLocation,
    CompanyKnowledgeBinding,
)
from ..schemas.engine_runs import EngineRunView
from .assets import read_object
from ..document_mcp.contracts import validate_structure
from .company_analysis_input import (
    resolve_company_knowledge_context,
    CompanyAnalysisError,
)

ENGINE_VERSION = "bid-deep-engine.v1"
JOB_TYPE = "bid_deep_engine_v1"
MAX_INPUT = 8 * 1024 * 1024
ENGINE_TIMEOUT_SECONDS = 90
# Codes the packaged runner may emit (bid_deep_engine.runner.ERROR_CODES). The web
# process never imports the package, so the list is repeated here and any other value
# from the subprocess is treated as invalid output.
RUNNER_ERROR_CODES = frozenset(
    {
        "engine_live_not_approved",
        "structure_unavailable",
        "invalid_table_coordinates",
        "table_too_large",
        "input_too_large",
        "engine_input_invalid",
        "engine_pipeline_failed",
        "company_bundle_invalid",
    }
)
_BUNDLE_SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_ERROR_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")

logger = logging.getLogger(__name__)


class EngineRunError(ValueError):
    def __init__(self, code, status=409):
        self.code = code
        self.status = status
        super().__init__(code)


def _sha(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def package_root():
    return Path(__file__).resolve().parents[5] / "packages/bid-deep-engine/src"


def engine_digest():
    root = package_root()
    files = sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix in {".py", ".md"}
    )
    if not files:
        raise EngineRunError("engine_unavailable", 503)
    return hashlib.sha256(
        "".join(
            str(p.relative_to(root))
            + ":"
            + hashlib.sha256(p.read_bytes()).hexdigest()
            + "\n"
            for p in files
        ).encode()
    ).hexdigest()


def currentness_many(session, rows, *, wiki_identity=None):
    if not rows:
        return {}
    company_ids = {r.company_id for r in rows if r.company_id is not None}
    notice_ids = {r.notice_id for r in rows}
    bindings = {
        b.company_id: b
        for b in session.scalars(
            select(CompanyKnowledgeBinding).where(
                CompanyKnowledgeBinding.company_id.in_(company_ids)
            )
        )
    }
    latest = {}
    for notice_id, bundle_id in session.execute(
        select(DocumentBundle.notice_id, DocumentBundle.id)
        .where(
            DocumentBundle.notice_id.in_(notice_ids), DocumentBundle.status == "ready"
        )
        .order_by(DocumentBundle.revision.desc())
    ):
        latest.setdefault(notice_id, bundle_id)
    doc_ids = {
        UUID(d["document_version_id"])
        for r in rows
        for d in r.input_payload["documents"]
    }
    current_docs = set(
        session.scalars(
            select(DocumentVersion.id).where(
                DocumentVersion.id.in_(doc_ids),
                DocumentVersion.is_current.is_(True),
                DocumentVersion.safety_status == "safe",
            )
        )
    )
    try:
        code_digest = engine_digest()
    except EngineRunError:
        code_digest = None
    wiki_rows = [row for row in rows if row.company_id is None]
    wiki_changed = set()
    if wiki_rows:
        wiki_changed = set(session.scalars(
            select(DocumentBundleItem.bundle_id)
            .join(DocumentVersion, DocumentVersion.id == DocumentBundleItem.document_version_id)
            .where(DocumentBundleItem.bundle_id.in_([row.bundle_id for row in wiki_rows]),
                   DocumentBundleItem.document_version_version != DocumentVersion.version)
        ))
    if wiki_identity is None and wiki_rows:
        try:
            wiki = company_bundle()
            if wiki:
                wiki_identity = (get_settings().engine_company_bundle_slug, wiki["bundle_sha256"])
        except EngineRunError:
            pass
    result = {}
    for row in rows:
        payload = row.input_payload
        ids = {UUID(d["document_version_id"]) for d in payload["documents"]}
        stale = (
            latest.get(row.notice_id) != row.bundle_id
            or not ids.issubset(current_docs)
            or (code_digest is not None and code_digest != payload["engine_sha256"])
        )
        unknown = code_digest is None
        if row.company_id is None:
            if wiki_identity is None:
                result[row.id] = "unknown"
                continue
            stale |= (
                wiki_identity != (row.company_bundle_slug, row.company_bundle_sha256)
                or row.bundle_id in wiki_changed
            )
        else:
            binding = bindings.get(row.company_id)
            stale |= (
                binding is None
                or str(binding.profile_version_id) != str(row.profile_version_id)
                or str(binding.graph_version_id) != payload["graph_version_id"]
            )
        result[row.id] = "stale" if stale else "unknown" if unknown else "current"
    return result


def view(session, row, freshness=None):
    result = row.result_payload or {}
    frozen = row.input_payload
    return EngineRunView(
        id=row.id,
        request_id=row.request_id,
        company_id=row.company_id,
        notice_id=row.notice_id,
        bundle_id=row.bundle_id,
        engine_version=row.engine_version,
        engine_sha256=frozen["engine_sha256"],
        input_currentness=freshness or currentness_many(session, [row])[row.id],
        profile_version_id=row.profile_version_id,
        profile_sha256=frozen.get("profile_sha256"),
        graph_version_id=frozen.get("graph_version_id"),
        graph_sha256=frozen.get("graph_sha256"),
        company_bundle_slug=row.company_bundle_slug,
        company_bundle_sha256=row.company_bundle_sha256,
        documents=frozen["documents"],
        quality_status=row.quality_status,
        status=row.status,
        input_sha256=row.input_sha256,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        error_code=row.error_code,
        warnings=result.get("warnings", []),
        analysis=result.get("analysis"),
    )


def engine_analysis_enabled() -> bool:
    return bool(getattr(get_settings(), "engine_analysis_enabled", False))


def company_bundle():
    """The engine's own company files and wiki, when a bundle folder is configured.

    Returns None when the folder or slug is not set (input v1). The layout and the digest
    are the ones `bid_deep_engine.adapter` reads; the web process never imports the
    package, so the reader is repeated here and the engine re-checks the digest.
    """
    settings = get_settings()
    folder, slug = settings.engine_company_bundle_dir, settings.engine_company_bundle_slug
    if not folder or not slug:
        return None
    if not _BUNDLE_SLUG.fullmatch(slug):
        raise EngineRunError("company_bundle_unavailable")
    base = Path(folder)
    profile = base / f"{slug}.yaml"
    tree = base / slug
    try:
        if base.is_symlink():
            raise EngineRunError("company_bundle_unavailable")
        files = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted([profile, *base.glob(f"{slug}.*.yaml")])
            if path.is_file() and not path.is_symlink()
        }
        pages = {}
        if tree.is_dir() and not tree.is_symlink():
            # The engine accepts only root pages and one directory of pages.
            paths = []
            for entry in tree.iterdir():
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    paths.extend(child for child in entry.iterdir() if child.suffix == ".md")
                elif entry.suffix == ".md":
                    paths.append(entry)
            for path in sorted(paths):
                if path.is_file() and not path.is_symlink():
                    pages[path.relative_to(tree).as_posix()] = path.read_text(
                        encoding="utf-8"
                    )
    except (OSError, UnicodeDecodeError):
        raise EngineRunError("company_bundle_unavailable") from None
    if profile.name not in files:
        raise EngineRunError("company_bundle_unavailable")
    bundle = {"profile_file": profile.name, "files": files, "knowledge": pages}
    bundle["bundle_sha256"] = hashlib.sha256(
        json.dumps(
            bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return bundle


def check_document(item, doc, struct, notice_id):
    if (
        not doc
        or doc.notice_id != notice_id
        or doc.safety_status != "safe"
        or item.safety_status_at_confirmation != "safe"
    ):
        raise EngineRunError("unsafe_document")
    if (
        not struct
        or struct.document_version_id != doc.id
        or struct.validation_status != "ready"
        or struct.payload_sha256 != item.structure_payload_sha256
        or struct.source_sha256 != item.content_sha256
    ):
        raise EngineRunError("structure_unavailable")
    return Path(item.original_filename).suffix.lower().lstrip(".")


def freeze_documents(session, bundle, *, rows=None, structure_locations=None):
    """Read ordered, pinned structure versions for either engine entry point."""
    notice_id = bundle.notice_id
    if rows is None:
        items = session.scalars(
            select(DocumentBundleItem)
            .where(DocumentBundleItem.bundle_id == bundle.id)
            .order_by(DocumentBundleItem.ordinal)
        ).all()
        if not items:
            raise EngineRunError("structure_unavailable")
        rows = (
            (item, session.get(DocumentVersion, item.document_version_id),
             session.get(DocumentStructure, item.structure_id_at_confirmation))
            for item in items
        )
    documents = []
    blocks = []
    primary = None
    for item, doc, struct in rows:
        ext = check_document(item, doc, struct, notice_id)
        if ext in {"hwp", "hwpx"} and primary is None:
            primary = ext
        documents.append(
            {
                "document_version_id": str(doc.id),
                "source_sha256": item.content_sha256,
                "structure_id": str(struct.id),
                "structure_sha256": struct.payload_sha256,
            }
        )
        if structure_locations is not None:
            location = structure_locations.get((struct.payload_content_object_id, "structure"))
        else:
            location = session.scalar(
                select(ContentObjectLocation)
                .where(
                    ContentObjectLocation.content_object_id
                    == struct.payload_content_object_id,
                    ContentObjectLocation.namespace_key == "structure",
                    ContentObjectLocation.status == "verified",
                )
                .order_by(ContentObjectLocation.verified_at.desc())
                .limit(1)
            )
        if location is None:
            raise EngineRunError("structure_unavailable")
        raw, _ = read_object(
            "structure", location.object_key, version_id=location.object_version_id
        )
        if hashlib.sha256(raw).hexdigest() != struct.payload_sha256:
            raise EngineRunError("structure_hash_mismatch")
        structure = validate_structure(json.loads(raw))
        if (
            structure["document_version_id"] != str(doc.id)
            or structure["source_sha256"] != item.content_sha256
        ):
            raise EngineRunError("structure_unavailable")
        for block in structure["blocks"]:
            blocks.append(
                {
                    "document_version_id": str(doc.id),
                    "block_key": block["block_key"],
                    "text": block["text"],
                    "page": block["page"],
                    "type": block["type"],
                    "attributes": block["attributes"],
                }
            )
    if primary is None:
        raise EngineRunError("original_hwp_required")
    if not blocks:
        raise EngineRunError("structure_unavailable")
    return primary, documents, blocks


def create(session: Session, *, company_id: UUID, notice_id: int, payload, actor: str):
    # The switch is checked before idempotent replay and before any read.
    if not engine_analysis_enabled():
        raise EngineRunError("engine_analysis_disabled", 503)
    if payload.mode != "mock_reference":
        raise EngineRunError("engine_live_not_approved")
    previous = session.scalar(
        select(EngineRun).where(EngineRun.request_id == payload.request_id)
    )
    if previous:
        if (
            previous.company_id,
            previous.notice_id,
            previous.bundle_id,
            previous.created_by_name,
        ) != (company_id, notice_id, payload.bundle_id, actor):
            raise EngineRunError("idempotency_conflict")
        return view(session, previous)
    notice = session.get(Notice, notice_id)
    if notice is None:
        raise EngineRunError("not_found", 404)
    try:
        company = resolve_company_knowledge_context(session, company_id)
    except CompanyAnalysisError as e:
        raise EngineRunError(
            e.code, 404 if e.code == "company_not_found" else 409
        ) from None
    bundle = session.get(DocumentBundle, payload.bundle_id)
    if not bundle or bundle.notice_id != notice_id:
        raise EngineRunError("not_found", 404)
    if bundle.status != "ready":
        raise EngineRunError("bundle_not_ready")
    primary, documents, blocks = freeze_documents(session, bundle)
    run_id = uuid4()
    bundled = company_bundle()
    frozen = {
        "schema_version": "bidops.engine-input.v2"
        if bundled
        else "bidops.engine-input.v1",
        "engine_version": ENGINE_VERSION,
        "engine_sha256": engine_digest(),
        "mode": "mock_reference",
        "slug": str(run_id),
        "title": notice.title or "공고명 미확인",
        "company_id": str(company_id),
        "company_name": company.company.name,
        "profile_version_id": str(company.profile.id),
        "profile_sha256": company.profile.profile_sha256,
        "profile_payload": company.profile.profile_payload,
        "graph_nodes": list(company.graph_nodes),
        "graph_version_id": str(company.graph.id),
        "graph_sha256": company.graph.graph_sha256,
        "notice_id": notice_id,
        "bundle_id": str(bundle.id),
        "documents": documents,
        "primary_format": primary,
        "blocks": blocks,
    }
    if bundled:
        # The engine reads its own company files and wiki; the BidOps profile and graph
        # stay bound by id and hash above but their bodies are not part of this input.
        del frozen["profile_payload"], frozen["graph_nodes"]
        frozen["company_bundle"] = bundled
    row = _queue_run(session, frozen, request_id=payload.request_id, actor=actor)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        previous = session.scalar(
            select(EngineRun).where(EngineRun.request_id == payload.request_id)
        )
        if previous and (
            previous.company_id,
            previous.notice_id,
            previous.bundle_id,
            previous.created_by_name,
        ) == (company_id, notice_id, payload.bundle_id, actor):
            return view(session, previous)
        raise EngineRunError("idempotency_conflict") from None
    return view(session, row)


def _queue_run(session, frozen, *, request_id, actor):
    if len(canonical_json_bytes(frozen)) > MAX_INPUT:
        raise EngineRunError("input_too_large", 422)
    run_id = UUID(frozen["slug"])
    bundled = frozen.get("company_bundle")
    company_id = frozen.get("company_id")
    company_profile = frozen.get("profile_version_id")
    wiki_only = frozen["schema_version"] == "bidops.engine-input.v3"
    row = EngineRun(
        id=run_id,
        request_id=request_id,
        company_id=UUID(company_id) if company_id else None,
        notice_id=frozen["notice_id"],
        bundle_id=UUID(frozen["bundle_id"]),
        profile_version_id=UUID(company_profile) if company_profile else None,
        company_bundle_slug=bundled["slug"] if wiki_only else None,
        company_bundle_sha256=bundled["bundle_sha256"] if wiki_only else None,
        engine_version=ENGINE_VERSION,
        quality_status="mock_reference",
        status="queued",
        input_sha256=_sha(frozen),
        input_payload=frozen,
        created_by_name=actor,
    )
    session.add(row)
    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=actor,
            action="engine_run.queued",
            aggregate_type="engine_run",
            aggregate_id=str(run_id),
            safe_metadata={
                "engine_version": ENGINE_VERSION,
                "quality_status": "mock_reference",
                "input_sha256": row.input_sha256,
                "company_bundle_sha256": bundled["bundle_sha256"] if bundled else None,
            },
            request_id=str(request_id),
        )
    )
    session.add(
        WorkJob(
            id=uuid4(),
            job_type=JOB_TYPE,
            aggregate_type="engine_run",
            aggregate_id=run_id,
            status="queued",
            max_attempts=1,
        )
    )
    return row


def wiki_input(session, notice, bundle, *, company, rows, locations):
    """Freeze the same documents for v3 without resolving a registered company."""
    primary, documents, blocks = freeze_documents(
        session, bundle, rows=rows, structure_locations=locations,
    )
    return {
        "schema_version": "bidops.engine-input.v3",
        "engine_version": ENGINE_VERSION,
        "engine_sha256": engine_digest(),
        "mode": "mock_reference",
        "slug": str(uuid4()),
        "title": notice.title or "공고명 미확인",
        "notice_id": notice.id,
        "bundle_id": str(bundle.id),
        "documents": documents,
        "primary_format": primary,
        "blocks": blocks,
        "company_bundle": company,
    }


def create_wiki_run(session, frozen, *, request_id, actor):
    """Queue exactly the revalidated v3 snapshot in the caller's transaction."""
    if not engine_analysis_enabled():
        raise EngineRunError("engine_analysis_disabled", 503)
    if frozen["schema_version"] != "bidops.engine-input.v3" or frozen["mode"] != "mock_reference":
        raise EngineRunError("engine_live_not_approved")
    return _queue_run(session, frozen, request_id=request_id, actor=actor)


def list_runs(session, company_id, notice_id, *, limit=20, offset=0):
    q = select(EngineRun).where(
        EngineRun.company_id == company_id, EngineRun.notice_id == notice_id
    )
    total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = session.scalars(
        q.order_by(EngineRun.created_at.desc(), EngineRun.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    freshness = currentness_many(session, rows)
    return {
        "items": [view(session, row, freshness[row.id]) for row in rows],
        "total": total,
    }


def get_run(session, run_id):
    row = session.get(EngineRun, run_id)
    if not row:
        raise EngineRunError("not_found", 404)
    return view(session, row)


def _invoke(payload, *args, verify_digest=True):
    """No inherited API credentials, shell, fallback, or network client."""
    package = package_root()
    if verify_digest and payload.get("engine_sha256") != engine_digest():
        raise EngineRunError("engine_version_changed")
    # Worker receives fixed bounded files, not source-supplied paths/commands.
    # stderr is captured and discarded: it may quote source or company text.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            done = subprocess.run(
                [sys.executable, "-m", "bid_deep_engine.runner", *args],
                input=canonical_json_bytes(payload),
                stdout=stdout,
                stderr=stderr,
                timeout=ENGINE_TIMEOUT_SECONDS,
                env={
                    "PATH": os.defpath,
                    "PYTHONPATH": str(package),
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise EngineRunError("engine_timeout") from None
        stdout.seek(0)
        data = stdout.read(MAX_INPUT + 1)
    if done.returncode:
        raise EngineRunError("engine_process_failed")
    if len(data) > MAX_INPUT:
        raise EngineRunError("engine_output_invalid")
    try:
        result = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EngineRunError("engine_output_invalid") from None
    if not isinstance(result, dict):
        raise EngineRunError("engine_output_invalid")
    return result


def preview_input(payload):
    """Run only local company/document validation and wiki selection."""
    if len(canonical_json_bytes(payload)) > MAX_INPUT:
        raise EngineRunError("input_too_large", 422)
    try:
        result = _invoke(payload, "--preview", verify_digest="engine_sha256" in payload)
    except EngineRunError as error:
        if error.code == "engine_version_changed":
            raise
        raise EngineRunError("engine_unavailable", 503) from None
    if result.get("schema_version") != "bidops.engine-preview.v1":
        code = result.get("error_code")
        if code in {"company_bundle_invalid", "structure_unavailable", "invalid_table_coordinates",
                    "table_too_large", "engine_pipeline_failed"}:
            raise EngineRunError(code)
        if code == "input_too_large":
            raise EngineRunError(code, 422)
        raise EngineRunError("engine_unavailable", 503)
    return result


def invoke_engine(payload):
    result = _invoke(payload)
    if (
        result.get("schema_version") != "bidops.engine-output.v1"
        or result.get("engine_version") != ENGINE_VERSION
        or result.get("quality_status") != "mock_reference"
        or result.get("status") not in {"partial", "failed"}
    ):
        raise EngineRunError("engine_output_invalid")
    if result["status"] == "partial" and (
        not isinstance(result.get("analysis"), dict)
        or result.get("error_code") is not None
    ):
        raise EngineRunError("engine_output_invalid")
    if result["status"] == "failed" and result.get("error_code") not in RUNNER_ERROR_CODES:
        raise EngineRunError("engine_output_invalid")
    error_class = result.get("error_class")
    if error_class is not None and not (
        isinstance(error_class, str) and _ERROR_CLASS.fullmatch(error_class)
    ):
        result["error_class"] = None
    return result


def _log_failure(run_id, worker_id, code, error_class):
    """Only identifiers, a defined code and an exception class name are logged."""
    logger.warning(
        "engine run failed",
        extra={
            "bidops": {
                "event": "engine_run.failed",
                "run_id": str(run_id),
                "worker_id": worker_id,
                "error_code": code,
                "failure_type": error_class,
            }
        },
    )


def _store_result(session, result, run_id, store):
    raw = canonical_json_bytes(result)
    digest = hashlib.sha256(raw).hexdigest()
    key = f"structure/engine-runs/{run_id}/{digest}.json"
    meta = store.put("structure", key, raw, content_type="application/json")
    content = session.scalar(
        select(ContentObject).where(ContentObject.sha256 == digest)
    )
    if content is None:
        content = ContentObject(
            id=uuid4(),
            sha256=digest,
            size_bytes=len(raw),
            detected_mime="application/json",
            retention_class="derived",
        )
        session.add(content)
        session.flush()
    session.add(
        ContentObjectLocation(
            id=uuid4(),
            content_object_id=content.id,
            namespace_key="structure",
            object_key=key,
            object_version_id=meta.object_version_id,
            status="verified",
            etag=meta.etag,
            verified_at=datetime.now(UTC),
        )
    )
    return digest


def run_once(session: Session, worker_id: str, *, store=None, invoke=invoke_engine):
    # Switch off: the slot claims nothing and queued runs stay as they are.
    if not engine_analysis_enabled():
        return False
    now = datetime.now(UTC)
    if session.in_transaction():
        session.commit()
    job = session.scalar(
        select(WorkJob)
        .where(
            WorkJob.job_type == JOB_TYPE,
            or_(
                WorkJob.status == "queued",
                and_(WorkJob.status == "running", WorkJob.lease_expires_at < now),
            ),
        )
        .order_by(WorkJob.scheduled_at, WorkJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        session.commit()
        return False
    row = session.get(EngineRun, job.aggregate_id)
    if row is None or job.status == "running":
        job.status = "failed"
        job.last_error_code = "lease_expired"
        job.completed_at = now
        job.lease_fence += 1
        if row and row.status in {"queued", "running"}:
            row.status = "failed"
            row.error_code = "lease_expired"
            row.completed_at = now
        session.commit()
        return True
    if row.status != "queued":
        job.status = "failed"
        job.last_error_code = "state_conflict"
        job.completed_at = now
        session.commit()
        return True
    job.status = "running"
    job.lease_owner = worker_id
    job.lease_expires_at = now + timedelta(seconds=120)
    job.lease_fence += 1
    job.attempt_count += 1
    row.status = "running"
    row.started_at = now
    job_id = job.id
    run_id = row.id
    fence = job.lease_fence
    frozen = row.input_payload
    digest = row.input_sha256
    session.commit()
    failure = None
    try:
        if _sha(frozen) != digest:
            raise EngineRunError("input_hash_mismatch")
        result = invoke(frozen)
    except EngineRunError as error:
        failure = (error.code, type(error).__name__)
    except Exception as error:
        # Unexpected worker-side failure; the message may carry source text.
        failure = ("engine_execution_failed", type(error).__name__)
    if failure is not None:
        result = {
            "schema_version": "bidops.engine-output.v1",
            "engine_version": ENGINE_VERSION,
            "quality_status": "mock_reference",
            "status": "failed",
            "error_code": failure[0],
            "warnings": [],
            "analysis": None,
            "artifacts": {},
        }
        _log_failure(run_id, worker_id, *failure)
    elif result["status"] == "failed":
        _log_failure(run_id, worker_id, result["error_code"], result.get("error_class"))
    session.expire_all()
    job = session.scalar(select(WorkJob).where(WorkJob.id == job_id).with_for_update())
    now = datetime.now(UTC)
    if (
        job.status != "running"
        or job.lease_owner != worker_id
        or job.lease_fence != fence
        or job.lease_expires_at <= now
    ):
        session.rollback()
        return True
    row = session.get(EngineRun, run_id)
    try:
        result_digest = _store_result(
            session, result, run_id, store or object_store(namespaces=("structure",))
        )
    except Exception as storage_error:
        storage_class = type(storage_error).__name__
        session.rollback()
        job = session.scalar(
            select(WorkJob).where(WorkJob.id == job_id).with_for_update()
        )
        if (
            job.status != "running"
            or job.lease_owner != worker_id
            or job.lease_fence != fence
        ):
            session.rollback()
            return True
        row = session.get(EngineRun, run_id)
        row.status = "failed"
        row.error_code = "result_storage_failed"
        row.completed_at = datetime.now(UTC)
        _log_failure(run_id, worker_id, row.error_code, storage_class)
        job.status = "failed"
        job.last_error_code = row.error_code
        job.completed_at = row.completed_at
        job.lease_owner = None
        job.lease_expires_at = None
        session.commit()
        return True
    session.add(
        AuditEvent(
            actor_kind="system",
            claimed_name=worker_id,
            action="engine_run.finished",
            aggregate_type="engine_run",
            aggregate_id=str(run_id),
            safe_metadata={"status": result["status"], "result_sha256": result_digest},
            request_id=None,
        )
    )
    row.result_payload = result
    row.result_sha256 = result_digest
    row.status = result["status"]
    row.error_code = result["error_code"]
    row.completed_at = now
    job.status = "failed" if row.status == "failed" else "completed"
    job.last_error_code = row.error_code
    job.completed_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    session.commit()
    return True
