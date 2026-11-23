"""Offline upload, review and recovery using synthetic documents and a disposable wiki."""
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import get_db, init_db
from app.core.models import AuditEvent
from app.deep_review.document_mcp.hwpx import extract_hwpx
from app.deep_review.document_mcp.safety import ProcessorOptions
from app.deep_review.routers.company_wiki_ingests import router
from app.deep_review.services import attachments, company_wiki_ingest_worker as worker
from app.deep_review.services.company_wiki import CompanyWiki
from app.deep_review.services.company_wiki_ingests import Run
from app.deep_review.services.document_converter import ScratchDocumentProcessor
from tests.deep_review.engine_fixtures import synthetic_engine_hwpx, REQUIREMENT
from tests.deep_review.test_document_worker_protocol import _generated_native_document
from tests.postgres import migrated_engine, requires_postgres

BASE = "/api/company-wiki/ingests"
PROJECT = "P2025-01"
ACTOR = {"X-BidOps-Actor-Name": "tester"}
EXPECTED = {"expected_status": "awaiting_review"}


def flag(monkeypatch, name, value):
    monkeypatch.setenv("BIDOPS_" + name, value)
    get_settings.cache_clear()


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def ctx(request, tmp_path, monkeypatch):
    base = tmp_path / "bundle"
    root = base / "example"
    for folder in ["portfolio", "categories", "capabilities"]:
        (root / folder).mkdir(parents=True, exist_ok=True)
    (base / "example.yaml").write_text("company: {name: 합성회사}")
    (base / "example.portfolio.yaml").write_text("- {id: P2025-01, title: 합성사업, amount_krw: 987654321}")
    (base / "example.provenance.yaml").write_text("{}")
    (root / "portfolio/P2025-01.md").write_text(
        "---\nslug: P2025-01\nkind: portfolio\ntitle: 합성\nportfolio_id: P2025-01\n"
        "confidence: confirmed\nsources: [합성]\n---\n## 수행한 요구 범위\n")
    (root / "categories/other.md").write_text("---\nslug: other\nkind: category\ntitle: 기타\n---\n[[P2025-01]]\n")
    (root / "INDEX.md").write_text("# 목차\n\n[[P2025-01]]\n[[other]]\n")
    (root / "work-units.json").write_text(json.dumps({
        "schema": "bidops.wiki-work-units.v1", "sources": {}, "evidence": [], "no_record": [],
        "topics": [{"id": "search", "title": "검색", "scope": "검색", "units": [
            {"id": "search.find", "title": "통합검색", "covers": "통합검색", "not": ""}]}]}))
    for key, value in {
        "ENGINE_COMPANY_BUNDLE_DIR": str(base), "ENGINE_COMPANY_BUNDLE_SLUG": "example",
        "COMPANY_WIKI_INGEST_ENABLED": "true", "COMPANY_WIKI_INGEST_APPLY_REFERENCE_ENABLED": "true",
        "COMPANY_WIKI_BACKUP_DIR": str(tmp_path / "backup"), "OBJECT_STORE_BACKEND": "filesystem",
        "TEST_MODE": "1", "ATTACHMENTS_DIR": str(tmp_path / "objects"),
    }.items():
        flag(monkeypatch, key, value)

    def setup(bind):
        with Session(bind) as session:
            app = FastAPI()
            app.include_router(router)
            app.dependency_overrides[get_db] = lambda: session
            with TestClient(app) as client:
                yield session, client, root

    try:
        if request.param == "postgres":
            with migrated_engine() as bind:
                yield from setup(bind)
        else:
            bind = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
            init_db(bind)
            yield from setup(bind)
            bind.dispose()
    finally:
        get_settings.cache_clear()


def upload(ctx, *, name="private.hwpx", key=None, project=PROJECT, actor=ACTOR):
    return ctx[1].post(BASE, data={"project_id": project}, files={"file": (name, synthetic_engine_hwpx())},
                       headers={**actor, "Idempotency-Key": str(key or uuid4())})


class SyntheticConverter:
    def process(self, content, media):
        structure = _generated_native_document(content, b"%PDF-1.7\n%%EOF")
        _, structure["blocks"], _ = extract_hwpx(content, ProcessorOptions())
        return structure


def review(ctx):
    session, client, _ = ctx
    response = upload(ctx)
    assert response.status_code == 202, response.text
    path = BASE + "/" + response.json()["id"]
    assert worker.run_once(session, "slot", processor=SyntheticConverter())
    detail = client.get(path).json()
    assert detail["status"] == "awaiting_review", detail
    assert detail["assignments"] == [{"req_id": "SFR-001", "name": "통합검색", "unit_titles": ["통합검색"]}]
    return path


def test_apply(ctx, tmp_path, caplog):
    session, client, root = ctx
    before = CompanyWiki().digest
    path = review(ctx)
    assert client.get(BASE).json()["total"] == 1
    assert client.post(path + "/approve", headers=ACTOR, json=EXPECTED).json()["status"] == "approved"
    assert worker.run_once(session, "slot")
    result = client.get(path).json()
    assert result["status"] == "applied", result
    assert before == result["wiki_sha256_before"] != result["wiki_sha256_after"] == CompanyWiki().digest
    assert (tmp_path / "backup" / result["backup_name"] / "example.yaml").is_file()
    assert "SFR-001" in (root / "capabilities/work-search.md").read_text()
    assert "요구사항 전체 목록" in (root / "portfolio/P2025-01.md").read_text()
    assert "P2025-01" in (root / "log.txt").read_text()
    assert not worker.run_once(session, "slot")
    for action in ("approve", "reject"):
        body = EXPECTED if action == "approve" else {**EXPECTED, "reason": "재요청"}
        assert client.post(path + "/" + action, headers=ACTOR, json=body).json()["error"]["code"] == "status_conflict"
    audit = list(session.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == result["id"])))
    assert {a.safe_metadata["status"] for a in audit} == {
        "queued", "extracting", "classifying", "awaiting_review", "approved", "applying", "applied"}
    for secret in ("987654321", str(tmp_path), REQUIREMENT):
        assert secret not in json.dumps(result, ensure_ascii=False)
    for secret in ("private.hwpx", REQUIREMENT):
        assert secret not in caplog.text + str([a.safe_metadata for a in audit])


def test_upload_guards(ctx, monkeypatch):
    session, client, _ = ctx
    assert upload(ctx, actor={}).json()["error"]["code"] == "actor_name_required"
    assert upload(ctx, project="P2000-99").json()["error"]["code"] == "project_not_registered"
    assert upload(ctx, name="private.exe").json()["error"]["code"] == "unsupported_extension"
    assert upload(ctx, name="disguised.pdf").json()["error"]["code"] == "mime_mismatch"
    key = uuid4()
    first = upload(ctx, key=key)
    assert first.status_code == 202
    assert upload(ctx, key=key).json()["id"] == first.json()["id"]
    assert upload(ctx, key=key, name="another.hwpx").json()["error"]["code"] == "idempotency_conflict"
    assert upload(ctx).json()["error"]["code"] == "ingest_in_progress"
    objects = get_settings().attachments_dir
    assert len(list(objects.rglob("source"))) == 1
    monkeypatch.setattr(attachments, "MAX_ATTACHMENT_SIZE", 4)
    assert upload(ctx).status_code == 413
    flag(monkeypatch, "COMPANY_WIKI_INGEST_ENABLED", "false")
    for response in [client.get(BASE), client.post(BASE), client.post(BASE + "/missing/approve")]:
        assert response.status_code == 404 and response.json()["error"]["code"] == "company_wiki_ingest_disabled"
    assert not worker.run_once(session, "slot")


def test_review_guards(ctx, monkeypatch):
    _, client, _ = ctx
    path = review(ctx)
    flag(monkeypatch, "COMPANY_WIKI_INGEST_APPLY_REFERENCE_ENABLED", "false")
    assert not client.get(path).json()["apply_allowed"]
    assert client.post(path + "/approve", headers=ACTOR, json=EXPECTED).json()["error"]["code"] == "reference_apply_disabled"
    reject = lambda: client.post(path + "/reject", headers=ACTOR, json={**EXPECTED, "reason": "재검토"})
    assert reject().json()["status"] == "rejected"
    assert reject().json()["error"]["code"] == "status_conflict"
    assert upload(ctx).status_code == 202


@pytest.mark.parametrize("code", ["malware_detected", "no_requirements", "portfolio_page_missing", "project_not_registered"])
def test_extraction_failures(ctx, tmp_path, code):
    session, client, root = ctx
    path = BASE + "/" + upload(ctx).json()["id"]
    processor = SyntheticConverter()
    if code == "malware_detected":
        processor = ScratchDocumentProcessor(tmp_path / "scratch", clamav_checker=lambda _: False)
    if code == "no_requirements":
        processor.process = lambda *_: {"blocks": []}
    if code == "portfolio_page_missing":
        (root / "portfolio/P2025-01.md").unlink()
    if code == "project_not_registered":
        (root.parent / "example.portfolio.yaml").write_text("[]")
    assert worker.run_once(session, "slot", processor=processor)
    detail = client.get(path).json()
    assert (detail["status"], detail["error_code"]) == ("failed", code)
    if code == "malware_detected":
        assert not list(get_settings().attachments_dir.rglob("source"))


@pytest.mark.parametrize("failure", ["lint", "crash", "unset"])
def test_backup_and_recovery(ctx, monkeypatch, failure):
    session, client, root = ctx
    path = review(ctx)
    client.post(path + "/approve", headers=ACTOR, json=EXPECTED).raise_for_status()
    before = CompanyWiki().digest
    files = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    if failure == "unset":
        flag(monkeypatch, "COMPANY_WIKI_BACKUP_DIR", "")
    reached = []

    class ProcessDied(BaseException):
        pass

    def interrupt(command, *args, **kwargs):
        if command == "lint":
            reached.append(command)
            assert CompanyWiki().digest != before
            if failure == "crash":
                raise ProcessDied
            raise RuntimeError("private diagnostic")
        return worker.invoke(command, *args, **kwargs)

    if failure == "crash":
        with pytest.raises(ProcessDied):
            worker.run_once(session, "slot", command=interrupt)
        session.rollback()
        row = session.get(Run, UUID(path.split("/")[-1]))
        assert row.status == "applying"
        row.heartbeat_at = datetime.now(UTC) - timedelta(minutes=4)
        session.commit()
        assert worker.run_once(session, "reaper")
    else:
        assert worker.run_once(session, "slot", command=interrupt)
    detail = client.get(path).json()
    assert detail["error_code"] == {"lint": "apply_failed", "crash": "lease_expired", "unset": "backup_dir_unset"}[failure], detail
    assert detail["status"] == ("aborted" if failure == "crash" else "failed")
    assert reached == ([] if failure == "unset" else ["lint"])
    assert CompanyWiki().digest == before
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == files


@requires_postgres
def test_empty_ingest_migration_downgrades_and_upgrades():
    from tests.postgres import run_alembic, temporary_database

    with temporary_database() as url:
        for action, revision in [("downgrade", "0042_engine_run"), ("upgrade", "0043_company_wiki_ingest")]:
            result = run_alembic(url, action, revision)
            assert result.returncode == 0, result.stderr
