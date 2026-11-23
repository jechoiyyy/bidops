"""One WorkJob on the shared analysis slot. Only this worker writes the wiki."""
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from sqlalchemy import and_, or_, select, text

from ...core.config import get_settings
from ...core.object_store import object_store
from ..document_mcp.errors import DocumentProcessingError
from ..models import CompanyWikiIngestRun as Run, WorkJob
from .company_wiki import CompanyWiki, WikiError
from .company_wiki_ingests import IngestError, NAMESPACE, project, transition
from .document_converter import ScratchDocumentProcessor, SAFE_CONVERTER_CODES
from .engine_runs import package_root, MAX_INPUT, ENGINE_TIMEOUT_SECONDS

LEASE = timedelta(seconds=120)


def invoke(command, *args, payload=None):
    with tempfile.TemporaryFile() as stdout:
        result = subprocess.run(
            [sys.executable, "-m", "bid_deep_engine.wiki_tools", command, *args],
            input=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else b"",
            env={"PATH": os.defpath, "PYTHONPATH": str(package_root()), "PYTHONIOENCODING": "utf-8",
                 "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=stdout, stderr=subprocess.DEVNULL, timeout=ENGINE_TIMEOUT_SECONDS,
        )
        stdout.seek(0)
        data = stdout.read(MAX_INPUT + 1)
    if result.returncode or len(data) > MAX_INPUT:
        raise IngestError("engine_process_failed")
    output = json.loads(data)
    if not isinstance(output, dict):
        raise IngestError("engine_process_failed")
    return output


def reference_classifier(root, source):
    return invoke("reference-mapping", "--root", root, payload=source)


def bundle_parts(base, slug):
    return [base / (slug + suffix) for suffix in (".yaml", ".portfolio.yaml", ".provenance.yaml", "")]


def check_tree(path):
    mode = path.lstat().st_mode
    if stat.S_ISDIR(mode):
        for child in path.iterdir():
            check_tree(child)
    elif not stat.S_ISREG(mode) or path.stat().st_nlink != 1:
        raise IngestError("unsafe_wiki_bundle")


def backup_root():
    value = get_settings().company_wiki_backup_dir
    if not value:
        raise IngestError("backup_dir_unset")
    path = Path(value)
    base = Path(get_settings().engine_company_bundle_dir).resolve()
    if path.is_symlink() or path.resolve().is_relative_to(base) or base.is_relative_to(path.resolve()):
        raise IngestError("unsafe_backup_dir")
    return path


def backup(wiki, run_id):
    destination = backup_root()
    destination.mkdir(parents=True, exist_ok=True)
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + str(run_id)[:8]
    with tempfile.TemporaryDirectory(dir=destination) as temp:
        snapshot = Path(temp) / "snapshot"
        snapshot.mkdir(mode=0o700)
        for part in bundle_parts(wiki.root.parent, wiki.slug):
            check_tree(part)
            if part.is_dir():
                shutil.copytree(part, snapshot / part.name)
            else:
                shutil.copy2(part, snapshot / part.name)
        snapshot.rename(destination / name)
    return name


def restore(row):
    # A crash before the backup checkpoint cannot have changed any wiki file.
    if not row.backup_name:
        return
    settings = get_settings()
    slug = settings.engine_company_bundle_slug
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug) or not re.fullmatch(
        r"\d{8}T\d{12}Z-" + str(row.id)[:8], row.backup_name
    ):
        raise IngestError("restore_failed")
    base = Path(settings.engine_company_bundle_dir)
    snapshot = backup_root() / row.backup_name
    if base.is_symlink() or snapshot.is_symlink():
        raise IngestError("restore_failed")
    parts = bundle_parts(snapshot, slug)
    for part in parts:
        check_tree(part)
    # Keep the snapshot intact so a crash during restoration can be recovered.
    for part in parts:
        target = base / part.name
        if target.is_symlink():
            raise IngestError("restore_failed")
        if part.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(part, target)
        else:
            with tempfile.TemporaryDirectory(dir=base) as temp:
                staged = Path(temp) / part.name
                shutil.copy2(part, staged)
                staged.replace(target)
    if CompanyWiki().digest != row.wiki_sha256_before:
        raise IngestError("restore_failed")


def apply(row, root, command):
    command("expand-requirements", "--root", root, "--project", row.project_id,
            payload=row.review_input["source"])
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as mapping:
        json.dump(row.mapping, mapping, ensure_ascii=False)
        mapping.flush()
        command("ingest-apply", "--root", root, "--mapping", mapping.name)
    command("lint", "--root", root)
    command("check", "--root", root)


def run_once(session, worker_id, *, store=None, processor=None, classifier=reference_classifier, command=invoke):
    try:
        return _run_once(session, worker_id, store, processor, classifier, command)
    except Exception:
        # DB errors can contain bound data; I/O errors can contain filenames.
        # Leave the committed lease and backup for the reaper if recovery failed.
        session.rollback()
        raise IngestError("ingest_worker_unavailable") from None


def _run_once(session, worker_id, store, processor, classifier, command):
    settings = get_settings()
    if not settings.company_wiki_ingest_enabled:
        return False
    now = datetime.now(UTC)
    # Serialize the short claim transaction, including the no-other-applying check.
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(11230043)"))
    applying = session.scalar(select(Run.id).where(Run.status == "applying"))
    ready = and_(WorkJob.status == "queued", Run.status.in_(["queued"] if applying else ["queued", "approved"]))
    stale = and_(WorkJob.status == "running", Run.heartbeat_at < now - LEASE)
    job = session.scalar(select(WorkJob).join(Run, Run.id == WorkJob.aggregate_id)
                         .where(WorkJob.job_type == NAMESPACE, or_(ready, stale))
                         .order_by(WorkJob.scheduled_at, WorkJob.id).limit(1)
                         .with_for_update(of=WorkJob, skip_locked=True))
    if job is None:
        session.commit()
        return False
    row = session.get(Run, job.aggregate_id, populate_existing=True)

    def finish(status, code=None):
        row.error_code = code
        transition(session, row, status, worker_id)
        job.status = "failed" if code else "completed"
        job.completed_at = datetime.now(UTC)
        job.last_error_code = code
        job.lease_expires_at = job.lease_owner = None
        session.commit()

    if job.status == "running":
        if row.status == "applying":
            restore(row)
        job.lease_fence += 1
        finish("aborted", "lease_expired")
        return True

    is_apply = row.status == "approved"
    job_id = job.id
    job.lease_fence += 1
    fence = job.lease_fence
    job.status = "running"
    job.lease_owner = worker_id
    job.attempt_count += 1
    row.worker_id = worker_id

    def checkpoint():
        row.heartbeat_at = datetime.now(UTC)
        job.lease_expires_at = row.heartbeat_at + LEASE
        session.commit()
        # Hold the job lock during each bounded operation. A reaper cannot restore
        # underneath a live writer. Recheck ownership after each committed checkpoint.
        current = session.get(WorkJob, job_id, with_for_update=True, populate_existing=True)
        return current.status == "running" and current.lease_fence == fence

    transition(session, row, "applying" if is_apply else "extracting", worker_id)
    if not checkpoint():
        return True
    try:
        wiki = CompanyWiki()
        project(wiki, row.project_id)
        if f"portfolio/{row.project_id}.md" not in wiki.knowledge:
            raise IngestError("portfolio_page_missing")
        if is_apply:
            if not settings.company_wiki_ingest_apply_reference_enabled:
                raise IngestError("reference_apply_disabled")
            row.wiki_sha256_before = wiki.digest
            row.backup_name = backup(wiki, row.id)
            if not checkpoint():
                return True
            apply(row, wiki.root, command)
            row.wiki_sha256_after = CompanyWiki().digest
            row.applied_at = datetime.now(UTC)
        else:
            store = store or object_store(namespaces=(NAMESPACE,))
            raw, _ = store.get(NAMESPACE, row.source_object_key, version_id=row.source_object_version)
            if hashlib.sha256(raw).hexdigest() != row.source_sha256:
                raise IngestError("hash_mismatch")
            try:
                structure = (processor or ScratchDocumentProcessor()).process(raw, row.source_media_type)
            except DocumentProcessingError as exc:
                if exc.code == "malware_detected":
                    store.delete_ingest_version(row.source_object_key, row.source_object_version)
                raise IngestError(exc.code if exc.code in SAFE_CONVERTER_CODES else "processing_failed") from None
            source = command("source-from-blocks", "--project", row.project_id, "--title", row.project_title,
                             payload={"blocks": [dict(block, document_version_id=str(row.id))
                                                 for block in structure["blocks"]]})
            row.requirement_count = len(source["requirements"])
            row.document_requirement_ids_unlisted = len(source["unlisted_ids"])
            if not row.requirement_count:
                raise IngestError("no_requirements")
            transition(session, row, "classifying", worker_id)
            row.classification_attempts += 1
            if not checkpoint():
                return True
            sidecar = wiki.side_file("work-units.json")
            if sidecar is None:
                raise IngestError("company_wiki_unreadable")
            titles = {u["id"]: wiki.public_prose(u["title"]) for t in json.loads(sidecar)["topics"] for u in t["units"]}
            row.mapping = classifier(wiki.root, source)
            row.review_input = {"source": source, "titles": titles,
                                "names": {r["id"]: wiki.public_prose(r["name"]) for r in source["requirements"]}}
    except Exception as exc:
        code = exc.code if isinstance(exc, WikiError) else "processing_failed"
        if is_apply and row.backup_name:
            restore(row)
            code = "apply_failed"
        finish("failed", code)
    else:
        finish("applied" if is_apply else "awaiting_review")
    return True
