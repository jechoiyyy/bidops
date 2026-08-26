"""T3 quarantine, bundle, provider, and concurrency contract tests."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import socket
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import init_db
from app.document_mcp.processor import DocumentProcessor
from app.models import AuditEvent, Attachment, ContentObject, ContentObjectLocation, ContentScan, DocumentBundle, DocumentBundleItem, DocumentStructure, DocumentVersion, IdempotencyRecord, Judgment, Notice, Run
from app.schemas.document_bundles import ConfirmRequest, PatchDocumentVersionRequest
from app.services import assets
from app.services import document_converter
from app.services.document_converter import ScratchDocumentProcessor
from app.services.document_bundles import BundleServiceError, DocumentBundleService, stable_api_error
from app.workers.document_protocol import convert_one

FIXTURES = Path(__file__).parent / "fixtures" / "document_bundles"


def fixture_pdf() -> bytes:
    return (FIXTURES / "safe.pdf").read_bytes()


class MemoryUpload:
    def __init__(self, content: bytes, filename: str, content_type: str) -> None:
        self._content = content
        self._offset = 0
        self.filename = filename
        self.content_type = content_type

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._content)
        chunk = self._content[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    async def close(self) -> None:
        return None


@dataclass
class Context:
    engine: object
    service: DocumentBundleService
    notice_id: int
    asset_root: Path


@pytest.fixture
def context(tmp_path: Path) -> Context:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    root = tmp_path / "assets"
    service = DocumentBundleService(
        root=root,
        processor=DocumentProcessor(clamav_checker=lambda _data: True),
    )
    with Session(engine) as session:
        run = Run(id=f"t3-{uuid4()}")
        notice = Notice(run=run, notice_key=f"t3-notice-{uuid4()}", title="T3", sample_role="analysis")
        notice.judgment = Judgment(grade="우선 검토", readiness="확인")
        session.add(run)
        session.commit()
        notice_id = notice.id
    return Context(engine, service, notice_id, root)


def upload(context: Context, bundle_id: UUID, content: bytes = fixture_pdf(), filename: str = "요청서.pdf", content_type: str = "application/pdf"):
    with Session(context.engine) as session:  # type: ignore[arg-type]
        return asyncio.run(context.service.upload_document(session, bundle_id, MemoryUpload(content, filename, content_type), "담당자", uuid4()))


def make_bundle(context: Context):
    with Session(context.engine) as session:  # type: ignore[arg-type]
        return context.service.create_bundle(session, context.notice_id, "담당자")


def test_safe_upload_streams_quarantine_then_commits_source_and_structure(context: Context) -> None:
    bundle = make_bundle(context)
    document = upload(context, bundle.id)
    assert document.safety_status == "safe"
    assert document.structure_status == "ready"
    root = assets.asset_root(context.asset_root)
    assert list((root / "quarantine").iterdir())
    assert list((root / "source").iterdir())
    assert list((root / "structure").iterdir())

    with Session(context.engine) as session:  # type: ignore[arg-type]
        structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
        assert structure is not None
        payload = context.service.get_structure(session, structure.id)
        assert payload.source_sha256
        page = context.service.get_structure_page(session, structure.id, 1)
        assert page.blocks


def test_production_upload_writes_and_consumes_converter_result(monkeypatch: pytest.MonkeyPatch, context: Context, tmp_path: Path) -> None:
    scratch = tmp_path / "converter-scratch"
    converter = ScratchDocumentProcessor(scratch, wait_seconds=2, clamav_checker=lambda _content: True)
    requests: list[Path] = []
    real_write_request = document_converter.write_request

    def write_and_run_converter(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = real_write_request(*args, **kwargs)
        requests.append(request)
        assert convert_one(scratch) is True
        return request

    monkeypatch.setattr(document_converter, "write_request", write_and_run_converter)
    service = DocumentBundleService(root=context.asset_root, converter=converter)
    bundle = make_bundle(context)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        document = asyncio.run(service.upload_document(session, bundle.id, MemoryUpload(fixture_pdf(), "sidecar.pdf", "application/pdf"), "담당자", uuid4()))
        structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
        assert structure is not None
    assert len(requests) == 1
    assert requests[0].name.endswith(".json")
    assert not list((scratch / "results").glob("*.json"))


@pytest.mark.skipif(os.environ.get("BIDOPS_MINIO_E2E") != "1", reason="requires the isolated T7 MinIO service")
def test_t7_minio_e2e_upload_provider_and_structure_round_trip(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    """Exercise the production bundle paths against live purpose buckets."""

    bundle = make_bundle(context)
    uploaded = upload(context, bundle.id, fixture_pdf(), "minio-upload.pdf", "application/pdf")
    with Session(context.engine) as session:  # type: ignore[arg-type]
        structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == uploaded.id))
        assert structure is not None
        payload = context.service.get_structure(session, structure.id)
        expected_source_sha256 = hashlib.sha256(fixture_pdf()).hexdigest()
        assert payload.source_sha256 == expected_source_sha256
        locations = session.scalars(
            select(ContentObjectLocation)
            .join(ContentObject, ContentObject.id == ContentObjectLocation.content_object_id)
        ).all()
        assert {row.namespace_key for row in locations} >= {"source", "structure", "quarantine"}
        assert all(row.object_key and row.object_version_id and row.etag for row in locations)

        monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
        attachment = Attachment(
            notice_id=context.notice_id,
            name="minio-provider.pdf",
            source_url="https://files.example.test/minio-provider.pdf",
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="minio-provider-1",
        )
        session.add(attachment)
        session.commit()
        connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=lambda _url: fixture_pdf())
        provider_view = context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        provider_structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == provider_view.id))
        assert provider_structure is not None
        assert context.service.get_structure(session, provider_structure.id).source_sha256 == expected_source_sha256


def test_upload_processor_runs_without_an_open_db_transaction(context: Context) -> None:
    bundle = make_bundle(context)
    transaction_states: list[bool] = []
    delegate = DocumentProcessor(clamav_checker=lambda _data: True)

    class Processor:
        def process(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            transaction_states.append(session.in_transaction())
            return delegate.process(*args, **kwargs)

    service = DocumentBundleService(root=context.asset_root, processor=Processor())  # type: ignore[arg-type]
    with Session(context.engine) as session:  # type: ignore[arg-type]
        document = asyncio.run(service.upload_document(session, bundle.id, MemoryUpload(fixture_pdf(), "transaction.pdf", "application/pdf"), "담당자", uuid4()))
        assert document.safety_status == "safe"
    assert transaction_states == [False]


def test_quarantine_clamav_unavailable_and_viewer_denial(context: Context) -> None:
    bundle = make_bundle(context)
    service = DocumentBundleService(root=context.asset_root, processor=DocumentProcessor())
    with Session(context.engine) as session:  # type: ignore[arg-type]
        document = asyncio.run(service.upload_document(session, bundle.id, MemoryUpload(fixture_pdf(), "scan.pdf", "application/pdf"), "담당자", uuid4()))
        assert document.safety_status == "quarantined"
        assert document.structure_status == "ready"
        with pytest.raises(BundleServiceError, match="quarantine"):
            structure_row = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
            assert structure_row is not None
            service.get_structure(session, structure_row.id)
        request = ConfirmRequest(request_id=uuid4(), version=bundle.version, confirmed_documents=[{"document_version_id": document.id, "version": document.version}])
        with pytest.raises(BundleServiceError) as error:
            service.confirm(session, bundle.id, request, "담당자")
        assert error.value.code == "bundle_has_blocking_issues"


@pytest.mark.parametrize(
    ("content", "filename", "content_type", "code"),
    [
        ((FIXTURES / "eicar.pdf").read_bytes(), "eicar.pdf", "application/pdf", "malware_detected"),
        (fixture_pdf(), "bad.pdf", "image/png", "mime_mismatch"),
        ((FIXTURES / "corrupt.pdf").read_bytes(), "corrupt.pdf", "application/pdf", "malformed_pdf"),
    ],
)
def test_malware_mime_and_corrupt_pdf_are_blocked(context: Context, content: bytes, filename: str, content_type: str, code: str) -> None:
    bundle = make_bundle(context)
    document = upload(context, bundle.id, content, filename, content_type)
    assert document.safety_status == "blocked"
    with Session(context.engine) as session:  # type: ignore[arg-type]
        row = session.get(DocumentVersion, document.id)
        assert row is not None
        assert row.needs_human_review is True
        assert row.attachment_id is not None


def test_archive_bomb_is_quarantined_as_blocked_before_structure(context: Context) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Contents/section0.xml", b"<root><p>safe</p></root>")
        archive.writestr("data.bin", b"A" * 50_000)
    asset = assets.quarantine_bytes(output.getvalue(), "bomb.hwpx", declared_media_type="application/hwp+zip", root=context.asset_root, source_kind="manual")
    inspected = assets.inspect_quarantine(
        asset,
        processor=DocumentProcessor(clamav_checker=lambda _data: True),
        options={"ocr": False, "max_archive_uncompressed_bytes": 1_000},
    )
    assert inspected.safety_status == "blocked"
    assert inspected.error_code in {"archive_size_limit", "archive_ratio_limit", "archive_member_limit"}


def test_source_copy_hash_mismatch_aborts_location_reference_and_cleans_request(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    bundle = make_bundle(context)

    def mismatch(*_args, **_kwargs):
        raise assets.AssetError("hash_mismatch", "hash mismatch")

    monkeypatch.setattr(assets, "commit_source", mismatch)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        with pytest.raises(BundleServiceError) as error:
            asyncio.run(context.service.upload_document(session, bundle.id, MemoryUpload(fixture_pdf(), "mismatch.pdf", "application/pdf"), "담당자", uuid4()))
        assert error.value.code == "processing_failed"
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.notice_id == context.notice_id)) is None
    assert not list((assets.asset_root(context.asset_root) / "source").iterdir())


def test_source_hash_change_blocks_confirm_and_stale_confirm_conflicts(context: Context) -> None:
    bundle = make_bundle(context)
    document = upload(context, bundle.id)
    with Session(context.engine) as first, Session(context.engine) as stale:  # type: ignore[arg-type]
        stale_bundle = stale.get(DocumentBundle, bundle.id)
        assert stale_bundle is not None
        location = first.scalar(select(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "source"))
        assert location is not None
        path = assets.asset_root(context.asset_root) / location.object_key
        path.write_bytes(b"changed source bytes")
        request = ConfirmRequest(request_id=uuid4(), version=bundle.version, confirmed_documents=[{"document_version_id": document.id, "version": document.version}])
        with pytest.raises(BundleServiceError) as changed:
            context.service.confirm(first, bundle.id, request, "담당자")
        assert changed.value.code == "bundle_has_blocking_issues"

        path.write_bytes(fixture_pdf())
        first_bundle = context.service.confirm(first, bundle.id, request, "담당자")
        assert first_bundle.status == "ready"
        stale_request = ConfirmRequest(request_id=uuid4(), version=stale_bundle.version, confirmed_documents=[{"document_version_id": document.id, "version": document.version}])
        with pytest.raises(BundleServiceError) as conflict:
            context.service.confirm(stale, bundle.id, stale_request, "다른 담당자")
        assert conflict.value.code == "version_conflict"


def test_attachment_filename_drift_blocks_ready_confirmation(context: Context) -> None:
    bundle = make_bundle(context)
    document = upload(context, bundle.id, filename="original-name.pdf")
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = session.get(Attachment, session.get(DocumentVersion, document.id).attachment_id)  # type: ignore[union-attr]
        assert attachment is not None
        attachment.name = "renamed-after-upload.pdf"
        session.commit()
        request = ConfirmRequest(
            request_id=uuid4(),
            version=bundle.version,
            confirmed_documents=[{"document_version_id": document.id, "version": document.version}],
        )
        with pytest.raises(BundleServiceError) as error:
            context.service.confirm(session, bundle.id, request, "담당자")
        assert error.value.code == "bundle_has_blocking_issues"
        row = session.get(DocumentBundle, bundle.id)
        assert row is not None
        assert any(issue["code"] == "source_changed" for issue in row.issues_snapshot)


def test_new_file_requires_new_bundle_and_old_ready_snapshot_is_preserved(context: Context) -> None:
    bundle = make_bundle(context)
    document = upload(context, bundle.id)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        ready = context.service.confirm(
            session,
            bundle.id,
            ConfirmRequest(request_id=uuid4(), version=bundle.version, confirmed_documents=[{"document_version_id": document.id, "version": document.version}]),
            "담당자",
        )
        newer = context.service.create_bundle(session, context.notice_id, "담당자")
        assert ready.status == "ready"
        assert newer.revision == ready.revision + 1
        assert newer.status == "draft"
        with pytest.raises(BundleServiceError) as blocked:
            asyncio.run(context.service.upload_document(session, ready.id, MemoryUpload(fixture_pdf(), "new.pdf", "application/pdf"), "담당자", uuid4()))
        assert blocked.value.code == "invalid_request"


def test_ready_and_superseded_bundle_snapshots_are_immutable(context: Context) -> None:
    original = make_bundle(context)
    original_document = upload(context, original.id, filename="original.pdf")
    with Session(context.engine) as session:  # type: ignore[arg-type]
        ready = context.service.confirm(
            session,
            original.id,
            ConfirmRequest(
                request_id=uuid4(),
                version=original.version,
                confirmed_documents=[{"document_version_id": original_document.id, "version": original_document.version}],
            ),
            "담당자",
        )
        original_item = session.get(DocumentBundleItem, {"bundle_id": original.id, "document_version_id": original_document.id})
        assert original_item is not None
        original_snapshot = (
            original_item.ordinal,
            original_item.document_version_version,
            original_item.content_sha256,
            original_item.original_filename,
            original_item.role_at_confirmation,
            original_item.structure_id_at_confirmation,
            original_item.structure_payload_sha256,
        )

        with pytest.raises(BundleServiceError) as ready_upload:
            asyncio.run(context.service.upload_document(session, original.id, MemoryUpload(fixture_pdf(), "ready-new.pdf", "application/pdf"), "담당자", uuid4()))
        assert ready_upload.value.code == "invalid_request"

        with pytest.raises(BundleServiceError) as ready_patch:
            context.service.patch_document(
                session,
                original_document.id,
                PatchDocumentVersionRequest(role="제안요청서", effective_date=None, replaces_document_version_id=None, is_current=True, version=original_document.version),
                "담당자",
            )
        assert ready_patch.value.code == "version_conflict"

        successor = context.service.create_bundle(session, context.notice_id, "담당자")
        successor_document = asyncio.run(context.service.upload_document(session, successor.id, MemoryUpload(fixture_pdf(), "successor.pdf", "application/pdf"), "담당자", uuid4()))
        successor_ready = context.service.confirm(
            session,
            successor.id,
            ConfirmRequest(
                request_id=uuid4(),
                version=successor.version,
                confirmed_documents=[
                    {"document_version_id": original_document.id, "version": original_document.version},
                    {"document_version_id": successor_document.id, "version": successor_document.version},
                ],
            ),
            "담당자",
        )
        assert successor_ready.status == "ready"
        old_row = session.get(DocumentBundle, original.id)
        assert old_row is not None and old_row.status == "superseded"

        with pytest.raises(BundleServiceError) as superseded_upload:
            asyncio.run(context.service.upload_document(session, original.id, MemoryUpload(fixture_pdf(), "superseded-new.pdf", "application/pdf"), "담당자", uuid4()))
        assert superseded_upload.value.code == "invalid_request"
        with pytest.raises(BundleServiceError) as superseded_confirm:
            context.service.confirm(
                session,
                original.id,
                ConfirmRequest(
                    request_id=uuid4(),
                    version=ready.version,
                    confirmed_documents=[{"document_version_id": original_document.id, "version": original_document.version}],
                ),
                "담당자",
            )
        assert superseded_confirm.value.code == "version_conflict"

        # Confirming a third revision makes the successor superseded too;
        # patching its snapshotted document must remain a conflict.
        third = context.service.create_bundle(session, context.notice_id, "담당자")
        context.service.confirm(
            session,
            third.id,
            ConfirmRequest(
                request_id=uuid4(),
                version=third.version,
                confirmed_documents=[
                    {"document_version_id": original_document.id, "version": original_document.version},
                    {"document_version_id": successor_document.id, "version": successor_document.version},
                ],
            ),
            "담당자",
        )
        with pytest.raises(BundleServiceError) as successor_patch:
            context.service.patch_document(
                session,
                successor_document.id,
                PatchDocumentVersionRequest(role="제안요청서", effective_date=None, replaces_document_version_id=None, is_current=True, version=successor_document.version),
                "담당자",
            )
        assert successor_patch.value.code == "version_conflict"

        unchanged = session.get(DocumentBundleItem, {"bundle_id": original.id, "document_version_id": original_document.id})
        assert unchanged is not None
        assert (
            unchanged.ordinal,
            unchanged.document_version_version,
            unchanged.content_sha256,
            unchanged.original_filename,
            unchanged.role_at_confirmation,
            unchanged.structure_id_at_confirmation,
            unchanged.structure_payload_sha256,
        ) == original_snapshot


def _bundle_item_state(item: DocumentBundleItem) -> dict[str, object]:
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


def test_confirm_supersedes_all_lower_ready_bundles_through_intermediate_draft(context: Context) -> None:
    first = make_bundle(context)
    document = upload(context, first.id, filename="lineage.pdf")
    with Session(context.engine) as session:  # type: ignore[arg-type]
        first_ready = context.service.confirm(
            session,
            first.id,
            ConfirmRequest(
                request_id=uuid4(),
                version=first.version,
                confirmed_documents=[{"document_version_id": document.id, "version": document.version}],
            ),
            "담당자",
        )
        first_item = session.get(DocumentBundleItem, {"bundle_id": first.id, "document_version_id": document.id})
        assert first_item is not None
        first_item_snapshot = _bundle_item_state(first_item)

        intermediate = context.service.create_bundle(session, context.notice_id, "담당자")
        latest = context.service.create_bundle(session, context.notice_id, "담당자")
        latest_ready = context.service.confirm(
            session,
            latest.id,
            ConfirmRequest(
                request_id=uuid4(),
                version=latest.version,
                confirmed_documents=[{"document_version_id": document.id, "version": document.version}],
            ),
            "담당자",
        )
        assert first_ready.status == "ready"
        assert latest_ready.status == "ready"
        statuses = {
            row.revision: row.status
            for row in session.scalars(
                select(DocumentBundle).where(DocumentBundle.notice_id == context.notice_id).order_by(DocumentBundle.revision.asc())
            ).all()
        }
        assert statuses[first_ready.revision] == "superseded"
        assert statuses[intermediate.revision] == "draft"
        assert statuses[latest_ready.revision] == "ready"

        unchanged = session.get(DocumentBundleItem, {"bundle_id": first.id, "document_version_id": document.id})
        assert unchanged is not None
        assert _bundle_item_state(unchanged) == first_item_snapshot


def test_confirm_rejects_backward_confirmation_after_higher_ready_revision(context: Context) -> None:
    first = make_bundle(context)
    document = upload(context, first.id, filename="backward.pdf")
    with Session(context.engine) as session:  # type: ignore[arg-type]
        context.service.confirm(
            session,
            first.id,
            ConfirmRequest(
                request_id=uuid4(),
                version=first.version,
                confirmed_documents=[{"document_version_id": document.id, "version": document.version}],
            ),
            "담당자",
        )
        intermediate = context.service.create_bundle(session, context.notice_id, "담당자")
        latest = context.service.create_bundle(session, context.notice_id, "담당자")
        context.service.confirm(
            session,
            latest.id,
            ConfirmRequest(
                request_id=uuid4(),
                version=latest.version,
                confirmed_documents=[{"document_version_id": document.id, "version": document.version}],
            ),
            "담당자",
        )
        draft = session.get(DocumentBundle, intermediate.id)
        draft_item = session.get(DocumentBundleItem, {"bundle_id": intermediate.id, "document_version_id": document.id})
        assert draft is not None and draft_item is not None
        draft_version = draft.version
        draft_item_snapshot = _bundle_item_state(draft_item)

        with pytest.raises(BundleServiceError) as error:
            context.service.confirm(
                session,
                intermediate.id,
                ConfirmRequest(
                    request_id=uuid4(),
                    version=draft.version,
                    confirmed_documents=[{"document_version_id": document.id, "version": document.version}],
                ),
                "담당자",
            )
        assert error.value.code == "version_conflict"
        draft = session.get(DocumentBundle, intermediate.id)
        draft_item = session.get(DocumentBundleItem, {"bundle_id": intermediate.id, "document_version_id": document.id})
        assert draft is not None and draft.status == "draft" and draft.version == draft_version
        assert draft_item is not None
        assert _bundle_item_state(draft_item) == draft_item_snapshot


def test_upload_and_confirm_idempotency_replay_and_conflict(context: Context) -> None:
    bundle = make_bundle(context)
    request_id = uuid4()
    with Session(context.engine) as session:  # type: ignore[arg-type]
        first = asyncio.run(context.service.upload_document(session, bundle.id, MemoryUpload(fixture_pdf(), "same.pdf", "application/pdf"), "담당자", request_id))
        replay = asyncio.run(context.service.upload_document(session, bundle.id, MemoryUpload(fixture_pdf(), "same.pdf", "application/pdf"), "담당자", request_id))
        assert replay.id == first.id
        request = ConfirmRequest(request_id=uuid4(), version=bundle.version, confirmed_documents=[{"document_version_id": first.id, "version": first.version}])
        ready = context.service.confirm(session, bundle.id, request, "담당자")
        assert context.service.confirm(session, bundle.id, request, "담당자").id == ready.id
        assert not session.in_transaction()
        conflict = ConfirmRequest(request_id=request.request_id, version=bundle.version, confirmed_documents=[])
        with pytest.raises(BundleServiceError) as error:
            context.service.confirm(session, bundle.id, conflict, "담당자")
        assert error.value.code == "idempotency_conflict"


def test_same_named_same_byte_reupload_creates_one_replacement_lineage(context: Context) -> None:
    first_bundle = make_bundle(context)
    first = upload(context, first_bundle.id, filename="재처리.pdf")
    with Session(context.engine) as session:  # type: ignore[arg-type]
        context.service.confirm(
            session,
            first_bundle.id,
            ConfirmRequest(
                request_id=uuid4(), version=first_bundle.version,
                confirmed_documents=[{"document_version_id": first.id, "version": first.version}],
            ),
            "담당자",
        )

    second_bundle = make_bundle(context)
    replacement = upload(context, second_bundle.id, filename="재처리.pdf")
    with Session(context.engine) as session:  # type: ignore[arg-type]
        old = session.get(DocumentVersion, first.id)
        new = session.get(DocumentVersion, replacement.id)
        assert old is not None and new is not None
        assert old.attachment_id == new.attachment_id
        assert old.is_current is False and new.is_current is True
        assert new.replaces_document_version_id == old.id
        assert session.query(Attachment).count() == 1


def test_confirm_rechecks_idempotency_after_bundle_lock(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    bundle = make_bundle(context)
    document = upload(context, bundle.id)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        first_request = ConfirmRequest(
            request_id=uuid4(),
            version=bundle.version,
            confirmed_documents=[{"document_version_id": document.id, "version": document.version}],
        )
        ready = context.service.confirm(session, bundle.id, first_request, "담당자")
        replay_request = ConfirmRequest(
            request_id=uuid4(),
            version=ready.version,
            confirmed_documents=[{"document_version_id": document.id, "version": document.version}],
        )
        stored_hash: str | None = None
        calls = 0
        original_idempotency = context.service._idempotency

        def insert_after_lock(current_session, operation, aggregate_type, aggregate_id, actor, request_id, request_hash):  # type: ignore[no-untyped-def]
            nonlocal calls, stored_hash
            calls += 1
            if calls == 2:
                stored_hash = stored_hash or request_hash
                current_session.add(
                    IdempotencyRecord(
                        id=uuid4(),
                        operation=operation,
                        aggregate_type=aggregate_type,
                        aggregate_id=aggregate_id,
                        claimed_name=actor,
                        request_id=request_id,
                        request_sha256=stored_hash,
                        response_status=200,
                        response_snapshot=ready.model_dump(mode="json"),
                    )
                )
                current_session.flush()
                current_session.commit()
            return original_idempotency(current_session, operation, aggregate_type, aggregate_id, actor, request_id, request_hash)

        monkeypatch.setattr(context.service, "_idempotency", insert_after_lock)
        replay = context.service.confirm(session, bundle.id, replay_request, "담당자")
        assert replay.id == ready.id
        assert replay.status == "ready"
        assert not session.in_transaction()
        calls = 0
        conflict_request = ConfirmRequest(
            request_id=replay_request.request_id,
            version=ready.version,
            confirmed_documents=[],
        )
        with pytest.raises(BundleServiceError) as error:
            context.service.confirm(session, bundle.id, conflict_request, "담당자")
        assert error.value.code == "idempotency_conflict"


def test_provider_connector_allowlist_dns_private_ip_and_size_limits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=lambda _url: fixture_pdf())
    asset = assets.acquire_provider_attachment(
        source_system="g2b",
        source_url="https://files.example.test/request.pdf",
        source_attachment_key="source-1",
        filename="request.pdf",
        connectors={"g2b": connector},
        root=tmp_path,
    )
    assert asset.source_attachment_key == "source-1"
    assert asset.path.parent.name == "quarantine"
    with pytest.raises(assets.ProviderSecurityError) as arbitrary:
        assets.acquire_provider_attachment(source_system="unknown", source_url="https://files.example.test/x.pdf", filename="x.pdf", connectors={}, root=tmp_path)
    assert arbitrary.value.code == "provider_connector_blocked"

    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("127.0.0.1",))
    with pytest.raises(assets.ProviderSecurityError) as private:
        connector.fetch("https://files.example.test/request.pdf")
    assert private.value.code == "provider_private_ip"

    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    oversized = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=lambda _url: b"x" * (assets.MAX_ASSET_BYTES + 1))
    with pytest.raises(assets.ProviderSecurityError) as size:
        oversized.fetch("https://files.example.test/request.pdf")
    assert size.value.code == "provider_size_limit"


def test_provider_https_transport_uses_pinned_ip_with_original_sni_and_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DNS answer is pinned; the transport must not resolve the hostname again."""

    destinations: list[tuple[str, int, float | None]] = []
    server_names: list[str | None] = []

    class FakeSocket:
        pass

    class FakeContext:
        def wrap_socket(self, sock: FakeSocket, *, server_hostname: str):
            server_names.append(server_hostname)
            return sock

    def create_connection(address, timeout=None, *args, **kwargs):  # type: ignore[no-untyped-def]
        destinations.append((address[0], address[1], timeout))
        return FakeSocket()

    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("hostname was resolved during transport")))
    connection = assets._PinnedHTTPSConnection(
        "files.example.test",
        pinned_ip="8.8.8.8",
        server_hostname="files.example.test",
        context=FakeContext(),
        timeout=2.0,
    )
    connection.connect()
    assert destinations == [("8.8.8.8", 443, 2.0)]
    assert server_names == ["files.example.test"]


def test_provider_overall_deadline_covers_slow_drip_read(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self) -> str:
            return "https://files.example.test/request.pdf"

        def read(self, _size: int) -> bytes:
            time.sleep(0.15)
            return b"x"

    class FakeOpener:
        def open(self, _request, timeout: float):
            assert timeout <= 0.11
            return SlowResponse()

    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    monkeypatch.setattr(assets, "build_opener", lambda *_handlers: FakeOpener())
    connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), timeout_seconds=0.1)
    with pytest.raises(assets.ProviderSecurityError) as error:
        connector.fetch("https://files.example.test/request.pdf")
    assert error.value.code == "provider_timeout"


def test_provider_redirects_are_manually_revalidated_and_limited_to_five(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    resolved: list[str] = []

    class RedirectingOpener:
        def open(self, request, timeout: float):
            opened.append(request.full_url)
            raise HTTPError(request.full_url, 302, "redirect", {"Location": "https://files.example.test/next.pdf"}, None)

    monkeypatch.setattr(assets, "resolve_public_ips", lambda host, _port: resolved.append(host) or ("8.8.8.8",))
    monkeypatch.setattr(assets, "build_opener", lambda *_handlers: RedirectingOpener())
    connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}))
    with pytest.raises(assets.ProviderSecurityError) as error:
        connector.fetch("https://files.example.test/request.pdf")
    assert error.value.code == "provider_redirect_blocked"
    assert len(opened) == assets.MAX_REDIRECTS + 1
    assert resolved == ["files.example.test"] * (assets.MAX_REDIRECTS + 1)


def test_upload_db_failure_cleans_every_request_created_object(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    bundle = make_bundle(context)
    processed = DocumentProcessor(clamav_checker=lambda _data: True).process(fixture_pdf(), "application/pdf")
    processed["pages"][0]["image_content_object_id"] = str(uuid4())
    processed.rendered_pages = {1: b"generated page bytes"}

    class Processor:
        def process(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return processed

    service = DocumentBundleService(root=context.asset_root, processor=Processor())  # type: ignore[arg-type]
    with Session(context.engine) as session:  # type: ignore[arg-type]
        def fail_commit():
            raise RuntimeError("simulated DB failure after object writes")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated DB failure"):
            asyncio.run(service.upload_document(session, bundle.id, MemoryUpload(fixture_pdf(), "rollback.pdf", "application/pdf"), "담당자", uuid4()))
    root = assets.asset_root(context.asset_root)
    assert not list((root / "quarantine").iterdir())
    assert not list((root / "source").iterdir())
    assert not list((root / "structure").iterdir())


@pytest.mark.parametrize("tamper", ["scan", "status", "source", "structure"])
def test_viewer_fails_closed_for_live_safety_and_hash_tampering(context: Context, tamper: str) -> None:
    bundle = make_bundle(context)
    document = upload(context, bundle.id)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
        assert structure is not None
        if tamper == "scan":
            content = session.get(DocumentVersion, document.id)
            assert content is not None
            scan = session.scalar(select(ContentScan).where(ContentScan.content_object_id == content.content_object_id))
            assert scan is not None
            scan.status = "error"
            session.commit()
        elif tamper == "status":
            row = session.get(DocumentVersion, document.id)
            assert row is not None
            row.safety_status = "quarantined"
            session.commit()
        elif tamper == "source":
            location = session.scalar(select(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "source"))
            assert location is not None
            (assets.asset_root(context.asset_root) / location.object_key).write_bytes(b"tampered")
        else:
            structure.payload_sha256 = "0" * 64
            session.commit()
        with pytest.raises(BundleServiceError) as error:
            service = context.service
            service.get_structure(session, structure.id)
        assert error.value.code == "unsafe_document"


def test_create_bundle_revision_unique_conflict_is_safe(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    with Session(context.engine) as session:  # type: ignore[arg-type]
        original_flush = session.flush

        def duplicate_revision():
            if any(isinstance(item, DocumentBundle) for item in session.new):
                raise IntegrityError("duplicate revision", {}, RuntimeError("uq_document_bundle_notice_revision"))
            original_flush()

        monkeypatch.setattr(session, "flush", duplicate_revision)
        with pytest.raises(BundleServiceError) as error:
            context.service.create_bundle(session, context.notice_id, "담당자")
        assert error.value.code == "processing_failed"
        assert error.value.status_code == 500
        assert error.value.message == "문서 bundle을 만들 수 없습니다"
        assert "uq_document_bundle_notice_revision" not in error.value.message


def test_internal_processor_detail_maps_to_stable_safe_api_error() -> None:
    code, message = stable_api_error("malformed_pdf", "/private/quarantine/path")
    assert code == "unsafe_document"
    assert "/private" not in message
    code, message = stable_api_error("provider_fetch_failed", "credential=secret")
    assert code == "processing_failed"
    assert "secret" not in message


def test_confirm_scope_ignores_retired_attachment_but_requires_all_active_current_versions(context: Context) -> None:
    bundle = make_bundle(context)
    retired = upload(context, bundle.id, filename="retired.pdf")
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = session.get(Attachment, session.get(DocumentVersion, retired.id).attachment_id)  # type: ignore[union-attr]
        assert attachment is not None
        attachment.retired_at = datetime.now(UTC)
        session.commit()
    active = upload(context, bundle.id, filename="active.pdf")
    with Session(context.engine) as session:  # type: ignore[arg-type]
        ready = context.service.confirm(
            session,
            bundle.id,
            ConfirmRequest(
                request_id=uuid4(),
                version=bundle.version,
                confirmed_documents=[{"document_version_id": active.id, "version": active.version}],
            ),
            "담당자",
        )
        assert ready.status == "ready"
        items = session.scalars(select(DocumentBundleItem).where(DocumentBundleItem.bundle_id == bundle.id)).all()
        assert [item.document_version_id for item in items] == [active.id]


def test_confirm_preserves_version_mismatch_and_rejects_duplicate_ids(context: Context) -> None:
    bundle = make_bundle(context)
    document = upload(context, bundle.id)
    mismatch = ConfirmRequest(
        request_id=uuid4(),
        version=bundle.version,
        confirmed_documents=[{"document_version_id": document.id, "version": document.version + 1}],
    )
    with Session(context.engine) as session:  # type: ignore[arg-type]
        with pytest.raises(BundleServiceError) as error:
            context.service.confirm(session, bundle.id, mismatch, "담당자")
        assert error.value.code == "bundle_has_blocking_issues"
        row = session.get(DocumentBundle, bundle.id)
        assert row is not None
        assert any(issue["code"] == "confirmation_version_mismatch" for issue in row.issues_snapshot)
        assert row.status != "ready"

        duplicate = ConfirmRequest(
            request_id=uuid4(),
            version=row.version,
            confirmed_documents=[
                {"document_version_id": document.id, "version": document.version},
                {"document_version_id": document.id, "version": document.version},
            ],
        )
        with pytest.raises(BundleServiceError) as duplicate_error:
            context.service.confirm(session, bundle.id, duplicate, "담당자")
        assert duplicate_error.value.code == "bundle_has_blocking_issues"
        row = session.get(DocumentBundle, bundle.id)
        assert row is not None
        assert any(issue["code"] == "duplicate_confirmed_document" for issue in row.issues_snapshot)
        assert row.status != "ready"


def test_ready_bundle_view_uses_confirmation_snapshot_not_live_document(context: Context) -> None:
    bundle = make_bundle(context)
    document = upload(context, bundle.id)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        patched = context.service.patch_document(
            session,
            document.id,
            PatchDocumentVersionRequest(role="제안요청서", effective_date=None, replaces_document_version_id=None, is_current=True, version=document.version),
            "담당자",
        )
        ready = context.service.confirm(
            session,
            bundle.id,
            ConfirmRequest(request_id=uuid4(), version=bundle.version, confirmed_documents=[{"document_version_id": patched.id, "version": patched.version}]),
            "담당자",
        )
        assert ready.documents[0].role == "제안요청서"
        live = session.get(DocumentVersion, document.id)
        assert live is not None
        live.role = "기타"
        live.original_filename = "changed-live-name.pdf"
        session.commit()
        projected = context.service.list_bundles(session, context.notice_id).items[0]
        assert projected.status == "ready"
        assert projected.documents[0].role == "제안요청서"
        assert projected.documents[0].original_filename == document.original_filename


def test_confirm_fails_closed_on_nonclean_latest_scan_and_structure_lineage(context: Context) -> None:
    bundle = make_bundle(context)
    document = upload(context, bundle.id)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        content = session.get(DocumentVersion, document.id)
        assert content is not None
        scan = session.scalar(select(ContentScan).where(ContentScan.content_object_id == content.content_object_id))
        structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
        assert scan is not None and structure is not None
        scan.status = "error"
        session.commit()
        with pytest.raises(BundleServiceError) as scan_error:
            context.service.confirm(
                session,
                bundle.id,
                ConfirmRequest(request_id=uuid4(), version=bundle.version, confirmed_documents=[{"document_version_id": document.id, "version": document.version}]),
                "담당자",
            )
        assert scan_error.value.code == "bundle_has_blocking_issues"
        scan.status = "clean"
        structure.media_type = "application/octet-stream"
        session.commit()
        with pytest.raises(BundleServiceError) as lineage_error:
            context.service.confirm(
                session,
                bundle.id,
                ConfirmRequest(request_id=uuid4(), version=bundle.version, confirmed_documents=[{"document_version_id": document.id, "version": document.version}]),
                "담당자",
            )
        assert lineage_error.value.code == "bundle_has_blocking_issues"


def test_provider_retired_attachment_rejected_before_external_processing(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    bundle = make_bundle(context)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="retired-provider.pdf",
            source_url="https://files.example.test/retired-provider.pdf",
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="retired-provider",
            retired_at=datetime.now(UTC),
        )
        session.add(attachment)
        session.commit()

        def should_not_fetch(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("retired provider attachment must not reach acquisition")

        monkeypatch.setattr(assets, "acquire_provider_attachment", should_not_fetch)
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {})
        assert error.value.code == "bundle_not_ready"
        session.rollback()
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.extract_status is None
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))) is None
        assert session.scalar(select(ContentObject)) is None
    root = assets.asset_root(context.asset_root)
    assert not list((root / "quarantine").iterdir())
    assert not list((root / "source").iterdir())


def test_provider_ingestion_existing_attachment_redirect_and_original_url(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    bundle = make_bundle(context)
    source_url = "https://files.example.test/original.pdf"
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="provider.pdf",
            source_url=source_url,
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="provider-1",
        )
        session.add(attachment)
        session.commit()
        connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=lambda _url: fixture_pdf())
        view = context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        assert view.safety_status == "safe"
        document = session.get(DocumentVersion, view.id)
        assert document is not None
        assert document.source_url == source_url
        assert document.created_by_name is None
        structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
        assert structure is not None
        audit = session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(document.id)).order_by(AuditEvent.created_at.desc()))
        assert audit is not None
        assert audit.actor_kind == "system"


def test_legacy_provider_ingestion_preserves_all_provenance_fields(context: Context) -> None:
    bundle = make_bundle(context)
    source_url = "https://files.example.test/legacy-provider.pdf"
    attachment = _legacy_attachment(
        context,
        bundle,
        source_system="g2b",
        source_attachment_key="legacy-provider-1",
        source_url=source_url,
        origin="g2b",
    )
    with Session(context.engine) as session:  # type: ignore[arg-type]
        view = context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        document = session.get(DocumentVersion, view.id)
        assert document is not None
        assert document.source_kind == "provider"
        assert document.source_system == "g2b"
        assert document.source_attachment_key == "legacy-provider-1"
        assert document.source_url == source_url


@pytest.mark.parametrize("missing", ["source_system", "source_attachment_key", "source_url"])
def test_legacy_partial_provider_provenance_fails_closed(context: Context, missing: str) -> None:
    bundle = make_bundle(context)
    provider = {
        "source_system": "g2b",
        "source_attachment_key": "legacy-partial",
        "source_url": "https://files.example.test/legacy-partial.pdf",
    }
    provider[missing] = None
    attachment = _legacy_attachment(context, bundle, origin="g2b", **provider)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        assert error.value.code == "bundle_has_blocking_issues"
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.extract_status == "legacy_acquisition_failed"
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        bundle_row = session.get(DocumentBundle, bundle.id)
        assert bundle_row is not None
        assert any(issue["code"] == "legacy_acquisition_failed" for issue in bundle_row.issues_snapshot)


def test_provider_ingestion_name_race_conflicts_before_writes(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    bundle = make_bundle(context)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="provider-name-race.pdf",
            source_url="https://files.example.test/provider-name-race.pdf",
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="provider-name-race",
        )
        session.add(attachment)
        session.commit()

        def fetcher(_url: str) -> bytes:
            with Session(context.engine) as winner:  # type: ignore[arg-type]
                row = winner.get(Attachment, attachment.id)
                assert row is not None
                row.name = "provider-renamed-during-fetch.pdf"
                winner.commit()
            return fixture_pdf()

        connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=fetcher)
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        assert error.value.code == "bundle_not_ready"
        session.rollback()
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.name == "provider-renamed-during-fetch.pdf"
        assert row.extract_status is None
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))) is None
    root = assets.asset_root(context.asset_root)
    assert not list((root / "quarantine").iterdir())
    assert not list((root / "source").iterdir())
    assert not list((root / "structure").iterdir())


def test_provider_retirement_race_conflicts_and_cleans_request(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    bundle = make_bundle(context)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="provider-retirement-race.pdf",
            source_url="https://files.example.test/provider-retirement-race.pdf",
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="provider-retirement-race",
        )
        session.add(attachment)
        session.commit()

        def fetcher(_url: str) -> bytes:
            with Session(context.engine) as winner:  # type: ignore[arg-type]
                row = winner.get(Attachment, attachment.id)
                assert row is not None
                row.retired_at = datetime.now(UTC)
                winner.commit()
            return fixture_pdf()

        connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=fetcher)
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        assert error.value.code == "bundle_not_ready"
        session.rollback()
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.retired_at is not None and row.extract_status is None
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))) is None
        assert session.scalar(select(ContentObject)) is None
    root = assets.asset_root(context.asset_root)
    assert not list((root / "quarantine").iterdir())
    assert not list((root / "source").iterdir())
    assert not list((root / "structure").iterdir())


def test_provider_fetcher_and_processor_run_without_an_open_db_transaction(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    bundle = make_bundle(context)
    transaction_states: list[bool] = []
    delegate = DocumentProcessor(clamav_checker=lambda _data: True)

    class Processor:
        def process(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            transaction_states.append(session.in_transaction())
            return delegate.process(*args, **kwargs)

    service = DocumentBundleService(root=context.asset_root, processor=Processor())  # type: ignore[arg-type]
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="provider-transaction.pdf",
            source_url="https://files.example.test/provider-transaction.pdf",
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="provider-transaction",
        )
        session.add(attachment)
        session.commit()

        def fetcher(_url: str) -> bytes:
            transaction_states.append(session.in_transaction())
            return fixture_pdf()

        connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=fetcher)
        view = service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        assert view.safety_status == "safe"
    assert transaction_states == [False, False]


def test_provider_ingestion_failure_is_blocking_without_source_details(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    bundle = make_bundle(context)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="provider.pdf",
            source_url="https://files.example.test/private.pdf?token=secret",
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="provider-failure",
        )
        session.add(attachment)
        session.commit()
        connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=lambda _url: (_ for _ in ()).throw(RuntimeError("credential=secret")))
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        assert error.value.code == "bundle_has_blocking_issues"
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.extract_status == "provider_acquisition_failed"
        bundle_row = session.get(DocumentBundle, bundle.id)
        assert bundle_row is not None
        assert any(issue["code"] == "provider_acquisition_failed" and issue["blocking"] for issue in bundle_row.issues_snapshot)
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        audits = session.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))).all()
        assert audits
        assert all("secret" not in str(audit.safe_metadata) and "files.example" not in str(audit.safe_metadata) for audit in audits)


def test_provider_classified_failure_source_race_conflicts_without_marker(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    bundle = make_bundle(context)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="provider-failure-race.pdf",
            source_url="https://files.example.test/provider-failure-race.pdf",
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="provider-failure-race",
        )
        session.add(attachment)
        session.commit()

        def fetcher(_url: str) -> bytes:
            with Session(context.engine) as winner:  # type: ignore[arg-type]
                row = winner.get(Attachment, attachment.id)
                assert row is not None
                row.source_url = "https://files.example.test/provider-failure-race-new.pdf"
                winner.commit()
            raise assets.AssetError("provider_response_invalid", "provider response was invalid")

        connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=fetcher)
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        assert error.value.code == "bundle_not_ready"
        session.rollback()
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.source_url.endswith("provider-failure-race-new.pdf")
        assert row.extract_status is None
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))) is None


def test_provider_fetcher_unexpected_exception_is_safe_fetch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    connector = assets.ProviderConnector(
        "g2b",
        frozenset({"files.example.test"}),
        fetcher=lambda _url: (_ for _ in ()).throw(RuntimeError("credential=secret")),
    )
    with pytest.raises(assets.ProviderSecurityError) as error:
        connector.fetch("https://files.example.test/provider.pdf")
    assert error.value.code == "provider_fetch_failed"
    assert "secret" not in str(error.value)


def test_provider_db_failure_rolls_back_without_failure_marker_or_objects(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    bundle = make_bundle(context)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="provider-db-failure.pdf",
            source_url="https://files.example.test/provider-db-failure.pdf",
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="provider-db-failure",
        )
        session.add(attachment)
        session.commit()
        connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=lambda _url: fixture_pdf())

        def fail_commit():
            raise RuntimeError("simulated provider DB failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated provider DB failure"):
            context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})

        session.rollback()
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.extract_status is None
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))) is None
    root = assets.asset_root(context.asset_root)
    assert not list((root / "quarantine").iterdir())
    assert not list((root / "source").iterdir())
    assert not list((root / "structure").iterdir())


def test_provider_ready_race_cleans_request_without_mutating_ready_bundle(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    bundle = make_bundle(context)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="provider-race.pdf",
            source_url="https://files.example.test/provider-race.pdf",
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="provider-race",
        )
        session.add(attachment)
        session.commit()

        def fetcher(_url: str) -> bytes:
            with Session(context.engine) as winner:  # type: ignore[arg-type]
                row = winner.get(DocumentBundle, bundle.id)
                assert row is not None
                row.status = "ready"
                winner.commit()
            return fixture_pdf()

        connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=fetcher)
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        assert error.value.code == "bundle_not_ready"
        session.rollback()
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.extract_status is None
        current_bundle = session.get(DocumentBundle, bundle.id)
        assert current_bundle is not None and current_bundle.status == "ready"
        assert session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))) is None
    root = assets.asset_root(context.asset_root)
    assert not list((root / "quarantine").iterdir())
    assert not list((root / "source").iterdir())
    assert not list((root / "structure").iterdir())


def test_provider_same_hash_source_loss_restores_without_new_version(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    bundle = make_bundle(context)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="provider.pdf",
            source_url="https://files.example.test/provider.pdf",
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="provider-restore",
        )
        session.add(attachment)
        session.commit()
        connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=lambda _url: fixture_pdf())
        first = context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        location = session.scalar(select(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "source").order_by(ContentObjectLocation.created_at.asc()))
        assert location is not None
        (assets.asset_root(context.asset_root) / location.object_key).unlink()
        second = context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        assert second.id == first.id
        versions = session.scalars(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)).all()
        assert len(versions) == 1
        assert context.service._source_location_matches(session, session.get(ContentObject, versions[0].content_object_id))  # type: ignore[arg-type]


def test_provider_changed_hash_creates_next_current_version(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    monkeypatch.setattr(assets, "resolve_public_ips", lambda _host, _port: ("8.8.8.8",))
    bundle = make_bundle(context)
    bodies = [fixture_pdf(), fixture_pdf() + b"\n"]
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="provider.pdf",
            source_url="https://files.example.test/provider.pdf",
            origin="g2b",
            file_ext="PDF",
            source_system="g2b",
            source_attachment_key="provider-change",
        )
        session.add(attachment)
        session.commit()
        connector = assets.ProviderConnector("g2b", frozenset({"files.example.test"}), fetcher=lambda _url: bodies.pop(0))
        first = context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        second = context.service.ingest_provider_attachment(session, bundle.id, attachment.id, {"g2b": connector})
        assert second.id != first.id
        versions = session.scalars(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id).order_by(DocumentVersion.version.asc())).all()
        assert [row.version for row in versions] == [1, 2]
        assert [row.is_current for row in versions] == [False, True]
        assert versions[1].replaces_document_version_id == versions[0].id


def _legacy_attachment(
    context: Context,
    bundle: object,
    *,
    stored_path: str = "legacy/old.pdf",
    content: bytes = fixture_pdf(),
    origin: str = "manual",
    source_system: str | None = None,
    source_attachment_key: str | None = None,
    source_url: str | None = None,
) -> Attachment:
    """Create one pre-T3 attachment row and its server-owned legacy file."""

    relative = Path(stored_path)
    if not relative.is_absolute() and ".." not in relative.parts:
        path = context.asset_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        attachment = Attachment(
            notice_id=context.notice_id,
            name="old.pdf",
            source_url=source_url,
            origin=origin,
            file_ext="PDF",
            size_bytes=len(content),
            legacy_stored_path=stored_path,
            extract_status="pending",
            source_system=source_system,
            source_attachment_key=source_attachment_key,
        )
        session.add(attachment)
        session.commit()
        session.refresh(attachment)
        return attachment


def test_legacy_stored_attachment_success_preserves_legacy_metadata(context: Context) -> None:
    bundle = make_bundle(context)
    attachment = _legacy_attachment(context, bundle)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        view = context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        assert view.safety_status == "safe"
        assert view.structure_status == "ready"
        row = session.get(Attachment, attachment.id)
        assert row is not None
        assert row.legacy_stored_path == "legacy/old.pdf"
        assert row.name == "old.pdf"
        assert row.origin == "manual"
        assert row.file_ext == "PDF"
        assert row.size_bytes == len(fixture_pdf())
        assert row.extract_status == "pending"
        document = session.get(DocumentVersion, view.id)
        assert document is not None and document.attachment_id == attachment.id
        assert document.source_kind == "manual"
        assert document.source_url is None
        assert session.scalar(select(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "source")) is not None


def test_legacy_retired_attachment_rejected_before_file_processing(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    bundle = make_bundle(context)
    attachment = _legacy_attachment(context, bundle)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        row = session.get(Attachment, attachment.id)
        assert row is not None
        row.retired_at = datetime.now(UTC)
        session.commit()

        def should_not_read(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("retired legacy attachment must not reach file acquisition")

        monkeypatch.setattr(assets, "acquire_legacy_attachment", should_not_read)
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        assert error.value.code == "bundle_not_ready"
        session.rollback()
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.extract_status == "pending"
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))) is None
        assert session.scalar(select(ContentObject)) is None
        assert session.scalar(select(ContentObjectLocation)) is None
    assert (context.asset_root / "legacy/old.pdf").read_bytes() == fixture_pdf()
    root = assets.asset_root(context.asset_root)
    assert not list((root / "quarantine").iterdir())
    assert not list((root / "source").iterdir())


@pytest.mark.parametrize("case", ["traversal", "symlink", "missing", "oversize"])
def test_legacy_source_path_failures_are_blocking_and_do_not_escape(context: Context, case: str) -> None:
    bundle = make_bundle(context)
    if case == "traversal":
        attachment = _legacy_attachment(context, bundle, stored_path="../escape.pdf")
    elif case == "symlink":
        outside = context.asset_root.parent / "outside.pdf"
        outside.write_bytes(fixture_pdf())
        link = context.asset_root / "legacy" / "link.pdf"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(outside)
        attachment = _legacy_attachment(context, bundle, stored_path="legacy/link.pdf")
    elif case == "missing":
        attachment = _legacy_attachment(context, bundle, stored_path="legacy/missing.pdf")
        (context.asset_root / "legacy" / "missing.pdf").unlink()
    else:
        attachment = _legacy_attachment(context, bundle, stored_path="legacy/large.pdf")
        with (context.asset_root / "legacy" / "large.pdf").open("r+b") as large_file:
            large_file.truncate(assets.MAX_ASSET_BYTES + 1)
        with Session(context.engine) as session:  # type: ignore[arg-type]
            row = session.get(Attachment, attachment.id)
            assert row is not None
            row.size_bytes = assets.MAX_ASSET_BYTES + 1
            session.commit()

    with Session(context.engine) as session:  # type: ignore[arg-type]
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        assert error.value.code == "bundle_has_blocking_issues"
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.extract_status == "legacy_acquisition_failed"
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        audits = session.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))).all()
        assert audits
        assert all("/" not in str(audit.safe_metadata) and "escape" not in str(audit.safe_metadata) for audit in audits)
    root = assets.asset_root(context.asset_root)
    assert not list((root / "quarantine").iterdir())
    assert not list((root / "source").iterdir())


def test_legacy_same_size_path_replacement_during_open_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "legacy" / "replacement.pdf"
    source.parent.mkdir(parents=True)
    original = fixture_pdf()
    replacement = original[:-1] + (b" " if original[-1:] != b" " else b"\n")
    source.write_bytes(original)
    original_open = assets.os.open
    replaced = False

    def replace_before_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal replaced
        if Path(path) == source and not replaced:
            replaced = True
            replacement_path = source.with_name("replacement-new.pdf")
            replacement_path.write_bytes(replacement)
            replacement_path.replace(source)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(assets.os, "open", replace_before_open)
    with pytest.raises(assets.AssetError) as error:
        assets.acquire_legacy_attachment(
            stored_path="legacy/replacement.pdf",
            filename="replacement.pdf",
            expected_size=len(original),
            root=tmp_path,
        )
    assert error.value.code == "legacy_source_changed"
    assert not list((assets.asset_root(tmp_path) / "quarantine").iterdir())


def test_legacy_same_size_in_place_mutation_during_copy_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "legacy" / "mutated.pdf"
    source.parent.mkdir(parents=True)
    original = fixture_pdf()
    mutated = original[:-1] + (b" " if original[-1:] != b" " else b"\n")
    source.write_bytes(original)
    initial_mtime = source.stat().st_mtime_ns
    original_read = assets.os.read
    changed = False

    def mutate_before_read(fd, size):  # type: ignore[no-untyped-def]
        nonlocal changed
        if not changed:
            changed = True
            source.write_bytes(mutated)
            current = source.stat()
            assets.os.utime(source, ns=(current.st_atime_ns, initial_mtime + 1))
        return original_read(fd, size)

    monkeypatch.setattr(assets.os, "read", mutate_before_read)
    with pytest.raises(assets.AssetError) as error:
        assets.acquire_legacy_attachment(
            stored_path="legacy/mutated.pdf",
            filename="mutated.pdf",
            expected_size=len(original),
            root=tmp_path,
        )
    assert error.value.code == "legacy_source_changed"
    assert not list((assets.asset_root(tmp_path) / "quarantine").iterdir())


def test_legacy_unsafe_bytes_retain_quarantine_and_blocking_state(context: Context) -> None:
    bundle = make_bundle(context)
    attachment = _legacy_attachment(context, bundle, content=(FIXTURES / "eicar.pdf").read_bytes())
    with Session(context.engine) as session:  # type: ignore[arg-type]
        view = context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        assert view.safety_status == "blocked"
        assert view.structure_status == "failed"
        document = session.get(DocumentVersion, view.id)
        assert document is not None and document.attachment_id == attachment.id
        assert session.scalar(select(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "quarantine")) is not None
        assert session.scalar(select(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "source")) is None
        bundle_row = session.get(DocumentBundle, bundle.id)
        assert bundle_row is not None and any(issue["blocking"] for issue in bundle_row.issues_snapshot)
    assert list((assets.asset_root(context.asset_root) / "quarantine").iterdir())


def test_legacy_copy_and_processor_run_without_open_db_transaction(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    bundle = make_bundle(context)
    attachment = _legacy_attachment(context, bundle)
    states: list[bool] = []
    original_acquire = assets.acquire_legacy_attachment
    delegate = DocumentProcessor(clamav_checker=lambda _data: True)

    def acquire(*args, **kwargs):  # type: ignore[no-untyped-def]
        states.append(session.in_transaction())
        return original_acquire(*args, **kwargs)

    class Processor:
        def process(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            states.append(session.in_transaction())
            return delegate.process(*args, **kwargs)

    monkeypatch.setattr(assets, "acquire_legacy_attachment", acquire)
    service = DocumentBundleService(root=context.asset_root, processor=Processor())  # type: ignore[arg-type]
    with Session(context.engine) as session:  # type: ignore[arg-type]
        view = service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        assert view.safety_status == "safe"
    assert states == [False, False]


def test_legacy_source_metadata_race_conflicts_before_writes(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    bundle = make_bundle(context)
    attachment = _legacy_attachment(context, bundle)
    original_acquire = assets.acquire_legacy_attachment

    def acquire(*args, **kwargs):  # type: ignore[no-untyped-def]
        with Session(context.engine) as winner:  # type: ignore[arg-type]
            row = winner.get(Attachment, attachment.id)
            assert row is not None
            row.name = "renamed-during-copy.pdf"
            winner.commit()
        return original_acquire(*args, **kwargs)

    monkeypatch.setattr(assets, "acquire_legacy_attachment", acquire)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        assert error.value.code == "bundle_not_ready"
        session.rollback()
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.name == "renamed-during-copy.pdf"
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))) is None
    root = assets.asset_root(context.asset_root)
    assert not list((root / "quarantine").iterdir())
    assert not list((root / "source").iterdir())


def test_legacy_retirement_race_conflicts_and_cleans_request(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    bundle = make_bundle(context)
    attachment = _legacy_attachment(context, bundle)
    original_acquire = assets.acquire_legacy_attachment

    def acquire(*args, **kwargs):  # type: ignore[no-untyped-def]
        with Session(context.engine) as winner:  # type: ignore[arg-type]
            row = winner.get(Attachment, attachment.id)
            assert row is not None
            row.retired_at = datetime.now(UTC)
            winner.commit()
        return original_acquire(*args, **kwargs)

    monkeypatch.setattr(assets, "acquire_legacy_attachment", acquire)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        assert error.value.code == "bundle_not_ready"
        session.rollback()
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.retired_at is not None and row.extract_status == "pending"
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))) is None
        assert session.scalar(select(ContentObject)) is None
        assert session.scalar(select(ContentObjectLocation)) is None
    root = assets.asset_root(context.asset_root)
    assert not list((root / "quarantine").iterdir())
    assert not list((root / "source").iterdir())
    assert (context.asset_root / "legacy/old.pdf").read_bytes() == fixture_pdf()


def test_legacy_db_failure_rolls_back_without_marker_and_cleans_objects(monkeypatch: pytest.MonkeyPatch, context: Context) -> None:
    bundle = make_bundle(context)
    attachment = _legacy_attachment(context, bundle)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        def fail_commit():
            raise RuntimeError("simulated legacy DB failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated legacy DB failure"):
            context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        session.rollback()
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.extract_status == "pending"
        assert session.scalar(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)) is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(attachment.id))) is None
    root = assets.asset_root(context.asset_root)
    assert not list((root / "quarantine").iterdir())
    assert not list((root / "source").iterdir())
    assert (context.asset_root / "legacy/old.pdf").read_bytes() == fixture_pdf()


def test_legacy_failure_then_fix_clears_marker_and_allows_ready(context: Context) -> None:
    bundle = make_bundle(context)
    attachment = _legacy_attachment(context, bundle, stored_path="legacy/fixable.pdf")
    legacy_path = context.asset_root / "legacy/fixable.pdf"
    legacy_path.unlink()
    with Session(context.engine) as session:  # type: ignore[arg-type]
        with pytest.raises(BundleServiceError) as error:
            context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        assert error.value.code == "bundle_has_blocking_issues"
        failed = session.get(Attachment, attachment.id)
        assert failed is not None and failed.extract_status == "legacy_acquisition_failed"

        legacy_path.write_bytes(fixture_pdf())
        view = context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        fixed = session.get(Attachment, attachment.id)
        assert fixed is not None and fixed.extract_status is None
        draft = session.get(DocumentBundle, bundle.id)
        assert draft is not None
        assert not any(issue["code"] == "legacy_acquisition_failed" for issue in draft.issues_snapshot)
        ready = context.service.confirm(
            session,
            bundle.id,
            ConfirmRequest(
                request_id=uuid4(),
                version=bundle.version,
                confirmed_documents=[{"document_version_id": view.id, "version": view.version}],
            ),
            "담당자",
        )
        assert ready.status == "ready"


def test_legacy_same_hash_reacquisition_restores_source_without_new_version(context: Context) -> None:
    bundle = make_bundle(context)
    attachment = _legacy_attachment(context, bundle)
    with Session(context.engine) as session:  # type: ignore[arg-type]
        first = context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        location = session.scalar(select(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "source").order_by(ContentObjectLocation.created_at.asc()))
        assert location is not None
        (assets.asset_root(context.asset_root) / location.object_key).unlink()
        second = context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        assert second.id == first.id
        versions = session.scalars(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id)).all()
        assert len(versions) == 1
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.legacy_stored_path == "legacy/old.pdf"
        assert context.service._source_location_matches(session, session.get(ContentObject, versions[0].content_object_id))  # type: ignore[arg-type]


def test_legacy_changed_hash_creates_next_immutable_version(context: Context) -> None:
    bundle = make_bundle(context)
    attachment = _legacy_attachment(context, bundle)
    legacy_path = context.asset_root / "legacy/old.pdf"
    with Session(context.engine) as session:  # type: ignore[arg-type]
        first = context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        original = fixture_pdf()
        legacy_path.write_bytes(original[:-1] + (b" " if original[-1:] != b" " else b"\n"))
        second = context.service.ingest_legacy_attachment(session, bundle.id, attachment.id)
        assert second.id != first.id
        versions = session.scalars(select(DocumentVersion).where(DocumentVersion.attachment_id == attachment.id).order_by(DocumentVersion.version.asc())).all()
        assert [row.version for row in versions] == [1, 2]
        assert [row.is_current for row in versions] == [False, True]
        assert versions[1].replaces_document_version_id == versions[0].id
        row = session.get(Attachment, attachment.id)
        assert row is not None and row.legacy_stored_path == "legacy/old.pdf"
