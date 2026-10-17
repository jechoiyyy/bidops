"""RL-03 결정 B15: ``attach-local-original`` connects an operator-held original to a G2B attachment row.

The bytes take the provider fetcher's own path (quarantine → ClamAV/MIME inspection
→ source → document → structure) through ``attach_local_original``; no G2B
connector exists in these tests and none may be built.  Each core case runs on
SQLite and, with ``BIDOPS_TEST_POSTGRES_URL``, on a migrated PostgreSQL 17 database.
The notice is SW사업대상=N without any grade, so document preparation opens only
because of the ``operator_local_original`` trigger.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import init_db
from app.core.models import AuditEvent
from app.deep_review.cli import attach_local_original as cli
from app.deep_review.document_mcp.processor import DocumentProcessor
from app.deep_review.models import (
    AttachmentFetch,
    ContentObjectLocation,
    ContentScan,
    DocumentBundle,
    DocumentStructure,
    DocumentVersion,
)
from app.deep_review.services import assets, prespec_attachments
from app.deep_review.services.prespec_attachments import (
    LOCAL_ORIGINAL_ACTION,
    LocalOriginalError,
    attach_local_original,
    read_operator_file,
)
from app.lifecycle.models import Attachment, Notice
from app.lifecycle.services.opportunity_connections import parse_attachment_key
# 판정 테이블을 metadata에 등록한다(자동 준비가 등급 seam을 부른다).
from app.screening.models import Judgment  # noqa: F401
from tests.app.test_prespec_attachment_fetch import G2B_URL, SAFE_PDF, make_engine
from tests.postgres import migrated_engine, requires_postgres


EICAR_PDF = Path(__file__).parents[1] / "fixtures/document_bundles/eicar.pdf"


@pytest.fixture(autouse=True)
def no_g2b_connector(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("G2B connector built")

    monkeypatch.setattr(assets, "g2b_attachment_connectors", forbidden)
    monkeypatch.setattr(assets.ProviderConnector, "fetch", forbidden)
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def engine(request):
    if request.param == "sqlite":
        bind = make_engine()
        init_db(bind)
        try:
            yield bind
        finally:
            bind.dispose()
    else:
        with migrated_engine() as bind:
            yield bind


@pytest.fixture
def sqlite_engine():
    bind = make_engine()
    init_db(bind)
    try:
        yield bind
    finally:
        bind.dispose()


def seed(session: Session, *, fetch_status: str | None = "대기", source_url: str | None = G2B_URL,
         name: str = "제안요청서.pdf") -> tuple[int, int]:
    notice = Notice(notice_key=f"pre:local:{os.urandom(4).hex()}", source_type="pre_spec",
                    title="폴리텍 사전규격", qualification_flags_json={"sw_business_status": "N"}, raw_source={})
    session.add(notice)
    session.flush()
    attachment = Attachment(
        notice_id=notice.id, name=name, source_url=source_url,
        source_system="g2b" if source_url == G2B_URL else None,
        source_attachment_key=parse_attachment_key(source_url) if source_url else None, origin="g2b",
    )
    session.add(attachment)
    session.flush()
    if fetch_status is not None:
        from datetime import UTC, datetime

        session.add(AttachmentFetch(
            attachment_id=attachment.id, status=fetch_status, eligibility_reason="sw_business_object",
            attempt_count=3 if fetch_status == "실패" else 0, max_attempts=3, next_attempt_at=datetime.now(UTC),
            lease_fence=4, last_error_code="provider_dns_blocked" if fetch_status == "실패" else None,
            completed_at=datetime.now(UTC) if fetch_status == "실패" else None,
        ))
    session.commit()
    return int(notice.id), int(attachment.id)


class RecordingScanner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, content: bytes) -> bool:
        self.calls.append(hashlib.sha256(content).hexdigest())
        return True


def attach(session: Session, notice_id: int, attachment_id: int, tmp_path: Path, *, content: bytes | None = None,
           expected: str | None = None, scanner=None, dry_run: bool = False, **kwargs) -> dict:
    data = SAFE_PDF.read_bytes() if content is None else content
    scanner = scanner or RecordingScanner()
    return attach_local_original(
        session, notice_id=notice_id, attachment_id=attachment_id, content=data,
        expected_sha256=expected or hashlib.sha256(data).hexdigest(), actor="jechoi",
        processor=DocumentProcessor(clamav_checker=scanner), root=tmp_path, dry_run=dry_run, **kwargs,
    )


def code_of(session: Session, notice_id: int, attachment_id: int, tmp_path: Path, **kwargs) -> str:
    with pytest.raises(LocalOriginalError) as error:
        attach(session, notice_id, attachment_id, tmp_path, **kwargs)
    session.rollback()
    return error.value.code


def counts(session: Session) -> dict[str, int]:
    return {
        model.__name__: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in (DocumentVersion, ContentObjectLocation, ContentScan, DocumentStructure, DocumentBundle)
    } | {"audit": int(session.scalar(select(func.count()).select_from(AuditEvent)) or 0)}


def asset_files(root: Path) -> list[Path]:
    base = root / "document-assets"
    return sorted(path for path in base.rglob("*") if path.is_file()) if base.exists() else []


def fetch_row(session: Session, attachment_id: int) -> AttachmentFetch | None:
    return session.scalar(select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment_id))


# --- success --------------------------------------------------------------------------


def test_success_stores_scanned_bytes_marks_fetch_and_opens_preparation(engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        notice_id, attachment_id = seed(session, fetch_status="실패")
        scanner = RecordingScanner()
        result = attach(session, notice_id, attachment_id, tmp_path, scanner=scanner)
        digest = hashlib.sha256(SAFE_PDF.read_bytes()).hexdigest()
        assert result["errors"] == [] and result["dry_run"] is False
        assert result["provenance"] == "operator_local_original"
        assert result["content_sha256"] == digest and result["fetch_status_before"] == "실패"
        assert result["scan_status"] == "clean"
        assert digest in scanner.calls  # the same ClamAV seam as the fetcher was called

        document = session.get(DocumentVersion, UUID(result["document_version_id"]))
        assert document.attachment_id == attachment_id and document.notice_id == notice_id
        assert (document.source_kind, document.source_system, document.source_url) == ("provider", "g2b", G2B_URL)
        assert document.source_attachment_key == parse_attachment_key(G2B_URL)
        assert document.safety_status == "safe" and document.is_current is True
        assert document.created_by_name == "jechoi" and document.original_filename == "제안요청서.pdf"
        namespaces = set(session.scalars(select(ContentObjectLocation.namespace_key).where(
            ContentObjectLocation.content_object_id == document.content_object_id)))
        assert {"quarantine", "source"} <= namespaces
        scan = session.scalar(select(ContentScan).where(ContentScan.content_object_id == document.content_object_id))
        assert scan.status == "clean" and scan.scanner == "clamav"
        structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
        assert structure is not None and structure.validation_status == "ready"

        row = fetch_row(session, attachment_id)
        assert row.status == "완료" and row.document_version_id == document.id
        assert row.lease_fence == 5 and row.last_error_code is None and row.lease_owner is None

        audits = session.scalars(select(AuditEvent).where(AuditEvent.action == LOCAL_ORIGINAL_ACTION)).all()
        assert len(audits) == 1
        audit = audits[0]
        assert (audit.actor_kind, audit.claimed_name) == ("human", "jechoi")
        assert (audit.aggregate_type, audit.aggregate_id) == ("attachment", str(attachment_id))
        assert audit.safe_metadata["provenance"] == "operator_local_original"
        assert audit.safe_metadata["status"] == "완료" and audit.safe_metadata["content_sha256"] == digest
        assert audit.safe_metadata["document_version_id"] == str(document.id)
        text = json.dumps(audit.safe_metadata, ensure_ascii=False)
        assert "제안요청서" not in text and "g2b.go.kr" not in text and str(tmp_path) not in text

        preparation = result["preparation"]
        assert preparation["confirmed"] is True and preparation["reason"] is None, preparation
        bundle = session.get(DocumentBundle, UUID(preparation["bundle_id"]))
        assert bundle.notice_id == notice_id and bundle.status == "ready"
        confirm = session.scalar(select(AuditEvent).where(AuditEvent.action == "document_bundle.auto_confirm"))
        assert confirm.safe_metadata["trigger"] == "operator_local_original"
        # the preparation is durable (committed by the attach, not left in an open transaction)
        bundle_id = bundle.id
        session.rollback()
        session.expire_all()
        assert session.get(DocumentBundle, bundle_id).status == "ready"


def test_without_the_operator_trigger_the_same_notice_is_not_prepared(engine, tmp_path: Path) -> None:
    """Control: SW=N without grade is not eligible for the ordinary preparation trigger."""

    from app.deep_review.services.auto_preparation import maybe_auto_prepare

    with Session(engine) as session:
        notice_id, _attachment_id = seed(session)
        assert [o.reason for o in maybe_auto_prepare(session, [notice_id], root=tmp_path)] == ["grade_not_priority"]


def test_attachment_without_fetch_row_is_attached_and_no_fetch_row_is_invented(engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        notice_id, attachment_id = seed(session, fetch_status=None)
        result = attach(session, notice_id, attachment_id, tmp_path)
        assert result["fetch_status_before"] is None and result["document_version_id"] is not None
        assert fetch_row(session, attachment_id) is None
        assert result["preparation"]["confirmed"] is True


# --- refusals (nothing written) -------------------------------------------------------


def test_sha_mismatch_writes_nothing(engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        notice_id, attachment_id = seed(session)
        before = counts(session)
        assert code_of(session, notice_id, attachment_id, tmp_path, expected="0" * 64) == "sha256_mismatch"
        assert counts(session) == before and asset_files(tmp_path) == []
        assert fetch_row(session, attachment_id).status == "대기"


def test_wrong_notice_is_refused(engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        notice_id, attachment_id = seed(session)
        other_notice, _ = seed(session)
        before = counts(session)
        assert code_of(session, other_notice, attachment_id, tmp_path) == "attachment_notice_mismatch"
        assert code_of(session, notice_id, attachment_id + 999, tmp_path) == "attachment_not_found"
        assert counts(session) == before and asset_files(tmp_path) == []


def test_already_has_bytes_is_refused(engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        notice_id, attachment_id = seed(session)
        attach(session, notice_id, attachment_id, tmp_path)
        before = counts(session)
        files = asset_files(tmp_path)
        assert code_of(session, notice_id, attachment_id, tmp_path) == "attachment_has_bytes"
        # a different file is refused just the same (no double registration)
        other = SAFE_PDF.read_bytes() + b"\n"
        assert code_of(session, notice_id, attachment_id, tmp_path, content=other) == "attachment_has_bytes"
        assert counts(session) == before and asset_files(tmp_path) == files


def test_non_g2b_retired_and_leased_rows_are_refused(sqlite_engine, tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    with Session(sqlite_engine) as session:
        manual_notice, manual_attachment = seed(session, source_url=None, fetch_status=None)
        assert code_of(session, manual_notice, manual_attachment, tmp_path) == "attachment_source_not_g2b"
        notice_id, attachment_id = seed(session)
        row = fetch_row(session, attachment_id)
        row.status, row.lease_owner = "진행", "worker-a"
        row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=2)
        session.commit()
        assert code_of(session, notice_id, attachment_id, tmp_path) == "attachment_fetch_in_progress"
        retired_notice, retired_attachment = seed(session)
        session.get(Attachment, retired_attachment).retired_at = datetime.now(UTC)
        session.commit()
        assert code_of(session, retired_notice, retired_attachment, tmp_path) == "attachment_retired"
        txt_notice, txt_attachment = seed(session, name="안내.txt")
        assert code_of(session, txt_notice, txt_attachment, tmp_path) == "unsupported_extension"
        bid = Notice(notice_key="bid:local", source_type="bid_notice", raw_source={})
        session.add(bid)
        session.flush()
        session.get(Attachment, txt_attachment).notice_id = bid.id
        session.commit()
        assert code_of(session, bid.id, txt_attachment, tmp_path) == "notice_not_pre_spec"
        assert code_of(session, notice_id, attachment_id, tmp_path, expected="xyz") == "expected_sha256_invalid"
        with pytest.raises(LocalOriginalError) as error:
            attach_local_original(session, notice_id=notice_id, attachment_id=attachment_id,
                                  content=SAFE_PDF.read_bytes(),
                                  expected_sha256=hashlib.sha256(SAFE_PDF.read_bytes()).hexdigest(),
                                  actor="system:transfer-policy", root=tmp_path)
        assert error.value.code == "actor_name_invalid"
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 0


def test_dry_run_writes_nothing(engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        notice_id, attachment_id = seed(session)
        before = counts(session)
        scanner = RecordingScanner()
        result = attach(session, notice_id, attachment_id, tmp_path, scanner=scanner, dry_run=True)
        assert result["dry_run"] is True and result["document_version_id"] is None
        assert result["preparation"] is None and result["errors"] == []
        assert scanner.calls == []
        assert counts(session) == before
        assert not (tmp_path / "document-assets").exists()
        assert fetch_row(session, attachment_id).status == "대기"


def test_placeholder_g2b_name_uses_the_operator_file_name(engine, tmp_path: Path) -> None:
    """G2B rows store placeholders such as "첨부 1" (no extension); the operator's file name wins (B22)."""

    with Session(engine) as session:
        notice_id, attachment_id = seed(session, name="첨부 1")
        # Without the operator file name there is still no usable extension.
        assert code_of(session, notice_id, attachment_id, tmp_path) == "unsupported_extension"
        result = attach(session, notice_id, attachment_id, tmp_path, dry_run=True, fallback_filename="제안요청서.pdf")
        assert result["dry_run"] is True and result["errors"] == []
        stored = attach(session, notice_id, attachment_id, tmp_path, fallback_filename="제안요청서.pdf")
        assert stored["document_version_id"] is not None
        names = session.scalars(
            select(DocumentVersion.original_filename).where(DocumentVersion.attachment_id == attachment_id)
        ).all()
        assert names == ["제안요청서.pdf"]


# --- inspection failures (same seam as the fetcher) -----------------------------------


def test_malware_is_refused_with_one_audit_and_no_document(sqlite_engine, tmp_path: Path) -> None:
    with Session(sqlite_engine) as session:
        notice_id, attachment_id = seed(session)
        eicar = EICAR_PDF.read_bytes()
        assert code_of(session, notice_id, attachment_id, tmp_path, content=eicar) == "malware_detected"
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 0
        audit = session.scalar(select(AuditEvent).where(AuditEvent.action == LOCAL_ORIGINAL_ACTION))
        assert audit.safe_metadata["status"] == "차단" and audit.safe_metadata["error_code"] == "malware_detected"
        assert fetch_row(session, attachment_id).status == "대기"
        assert [path for path in asset_files(tmp_path) if "source" in path.parts] == []


def test_missing_scanner_fails_closed_as_retryable(sqlite_engine, tmp_path: Path) -> None:
    with Session(sqlite_engine) as session:
        notice_id, attachment_id = seed(session)
        data = SAFE_PDF.read_bytes()
        with pytest.raises(LocalOriginalError) as error:
            attach_local_original(session, notice_id=notice_id, attachment_id=attachment_id, content=data,
                                  expected_sha256=hashlib.sha256(data).hexdigest(), actor="jechoi", root=tmp_path)
        assert (error.value.code, error.value.retryable) == ("clamav_unavailable", True)
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 0


def test_mime_must_match_the_attachment_extension(sqlite_engine, tmp_path: Path) -> None:
    with Session(sqlite_engine) as session:
        notice_id, attachment_id = seed(session, name="제안요청서.hwp")
        assert code_of(session, notice_id, attachment_id, tmp_path) == "mime_mismatch"
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 0


# --- local file reading ---------------------------------------------------------------


def test_read_operator_file_requires_a_regular_capped_file(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "원본.pdf"
    source.write_bytes(SAFE_PDF.read_bytes())
    assert read_operator_file(source) == SAFE_PDF.read_bytes()
    link = tmp_path / "link.pdf"
    link.symlink_to(source)
    for path, code in ((link, "file_not_regular"), (tmp_path, "file_not_regular"),
                       (tmp_path / "missing.pdf", "file_not_found")):
        with pytest.raises(LocalOriginalError) as error:
            read_operator_file(path)
        assert error.value.code == code and str(tmp_path) not in str(error.value)
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(LocalOriginalError) as error:
        read_operator_file(empty)
    assert error.value.code == "file_empty"
    monkeypatch.setattr(assets, "MAX_ASSET_BYTES", 10)
    with pytest.raises(LocalOriginalError) as error:
        read_operator_file(source)
    assert error.value.code == "file_size_limit"


# --- CLI --------------------------------------------------------------------------------


def run_cli(monkeypatch, engine, tmp_path: Path, capsys, *argv: str, scanner=None) -> tuple[int, dict, str]:
    monkeypatch.setattr(cli, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(cli, "init_db", lambda: None)
    scanner = scanner or RecordingScanner()
    monkeypatch.setattr(cli, "_document_processing",
                        lambda _settings: (DocumentProcessor(clamav_checker=scanner), scanner))
    original = prespec_attachments.attach_local_original
    monkeypatch.setattr(cli, "attach_local_original", lambda *a, **k: original(*a, **{**k, "root": tmp_path}))
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err.strip()


def test_cli_dry_run_success_and_refusal_exit_codes(sqlite_engine, tmp_path: Path, monkeypatch, capsys) -> None:
    with Session(sqlite_engine) as session:
        notice_id, attachment_id = seed(session)
    source = tmp_path / "local" / "원본.pdf"
    source.parent.mkdir()
    source.write_bytes(SAFE_PDF.read_bytes())
    digest = hashlib.sha256(SAFE_PDF.read_bytes()).hexdigest()
    base = ("--notice-id", str(notice_id), "--attachment-id", str(attachment_id), "--file", str(source),
            "--actor", "jechoi")

    code, payload, err = run_cli(monkeypatch, sqlite_engine, tmp_path, capsys, *base,
                                 "--expected-sha256", "f" * 64)
    assert (code, payload["errors"], err) == (2, ["sha256_mismatch"], "sha256_mismatch")
    assert str(source) not in json.dumps(payload, ensure_ascii=False)

    code, payload, err = run_cli(monkeypatch, sqlite_engine, tmp_path, capsys, *base,
                                 "--expected-sha256", digest, "--dry-run")
    assert code == 0 and err == "" and payload["dry_run"] is True and payload["document_version_id"] is None
    with Session(sqlite_engine) as session:
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0

    scanner = RecordingScanner()
    code, payload, err = run_cli(monkeypatch, sqlite_engine, tmp_path, capsys, *base,
                                 "--expected-sha256", digest.upper(), scanner=scanner)
    assert code == 0 and err == "" and payload["errors"] == []
    assert payload["document_version_id"] is not None and payload["preparation"]["confirmed"] is True
    assert scanner.calls and set(payload) == set(cli._payload())

    code, payload, err = run_cli(monkeypatch, sqlite_engine, tmp_path, capsys, *base,
                                 "--expected-sha256", digest)
    assert (code, payload["errors"]) == (2, ["attachment_has_bytes"])
