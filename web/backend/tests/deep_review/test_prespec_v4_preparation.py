"""Focused immutable PDF preparation and range binding contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.core.object_store import FilesystemObjectStore
from app.deep_review.document_mcp.processor import ProcessedDocument
from app.deep_review.models import (
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentVersion,
    PrespecV4PdfSnapshot,
    PrespecV4Target,
)
from app.deep_review.services.prespec_v4 import (
    V4PreparationError,
    freeze_v4_target,
    prepare_v4_pdf_snapshot,
    select_v4_input_range,
)
from app.lifecycle.models import Notice


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_SOURCE_PROCESSOR_PROVENANCE = {
    "schema": "bidops.pdf-text-provenance.v1",
    "processor_sha256": "d" * 64,
    "text_extractor": {"name": "pdf-poppler-prepared", "version": "1"},
    "poppler_binary_sha256": {"pdfinfo": "e" * 64, "pdftotext": "f" * 64},
}
_SOURCE_RENDERER = {"source_pdf": True, "processor_provenance": _SOURCE_PROCESSOR_PROVENANCE}
_SOURCE_FONT = {"source_pdf": True, "font_provenance": None}


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    return engine


def _source(session: Session, store: FilesystemObjectStore, data: bytes) -> tuple[DocumentVersion, ContentObjectLocation]:
    notice = Notice(id=142, notice_key="pre:R26BD00271191", title="fixture")
    session.add(notice)
    session.flush()
    detected_mime = "application/pdf" if data.startswith(b"%PDF-") else "application/x-hwp"
    filename = "fixture_제안요청서.pdf" if detected_mime == "application/pdf" else "fixture_제안요청서.hwp"
    metadata = store.put("source", f"source/v4/source-{_sha(data)}", data, content_type=detected_mime)
    content = ContentObject(
        sha256=_sha(data), size_bytes=len(data), detected_mime=detected_mime, retention_class="document-source"
    )
    session.add(content)
    session.flush()
    location = ContentObjectLocation(
        content_object_id=content.id,
        namespace_key="source",
        object_key=metadata.object_key,
        object_version_id=metadata.object_version_id,
        etag=metadata.etag,
        status="verified",
    )
    session.add(location)
    session.add(ContentScan(content_object_id=content.id, scanner="test", scanner_version="1", status="clean", safe_result={"sha256": _sha(data)}))
    document = DocumentVersion(
        id=uuid4(), notice_id=notice.id, content_object_id=content.id, version=1,
        source_kind="manual", original_filename=filename, role="제안요청서",
        is_current=True, safety_status="safe", needs_human_review=False,
    )
    session.add(document)
    session.flush()
    return document, location


def _processed(source: bytes) -> ProcessedDocument:
    page_one = "목차\nⅠ. 감리 개요\nⅡ. 제안요청 사항"
    page_two = "Ⅰ. 감리 개요\n1. 목적\n본문\n2. 범위\n감리 범위\nⅡ. 제안요청 사항\n다음 장"
    payload = {
        "schema": "bidops.document-structure.v1",
        "structure_id": str(uuid4()),
        "document_version_id": str(uuid4()),
        "source_sha256": _sha(source),
        "media_type": "application/pdf",
        "extractor": {"name": "pdf-poppler-prepared", "version": "1"},
        "pages": [
            {"number": 1, "width": 612.0, "height": 792.0, "image_content_object_id": None},
            {"number": 2, "width": 612.0, "height": 792.0, "image_content_object_id": None},
        ],
        "blocks": [
            {"block_key": "page-1-text", "page": 1, "type": "text", "text": page_one, "bbox": [0, 0, 612, 792], "confidence": 1.0, "attributes": {}},
            {"block_key": "page-2-text", "page": 2, "type": "text", "text": page_two, "bbox": [0, 0, 612, 792], "confidence": 1.0, "attributes": {}},
        ],
        "warnings": ["pdf_poppler_text_fallback"],
        "created_at": datetime.now(UTC).isoformat(),
    }
    return ProcessedDocument(
        payload,
        original_bytes=source,
        converted_pdf_bytes=None,
        pdf_metadata={
            "schema": "bidops.pdf-snapshot.v1",
            "renderer": "source-pdf",
            "renderer_version": "1",
            "rerendered": False,
            "processor_provenance": _SOURCE_PROCESSOR_PROVENANCE,
            "font_provenance": None,
            "page_count": 2,
            "pages": [
                {"number": 1, "width": 612.0, "height": 792.0, "text_sha256": _sha(page_one.encode())},
                {"number": 2, "width": 612.0, "height": 792.0, "text_sha256": _sha(page_two.encode())},
            ],
        },
    )


class _Converter:
    def __init__(self, processed: ProcessedDocument, scanner):
        self.processed = processed
        self.clamav_checker = scanner
        self.calls = 0

    def process(self, content: bytes, media_type: str | None, options: Any) -> ProcessedDocument:
        self.calls += 1
        assert content == self.processed.original_bytes
        assert media_type == "application/pdf"
        return self.processed


class _GeneratedConverter(_Converter):
    def process(self, content: bytes, media_type: str | None, options: Any) -> ProcessedDocument:
        self.calls += 1
        assert content == self.processed.original_bytes
        assert media_type == "application/octet-stream"
        payload = dict(self.processed)
        payload["media_type"] = "application/x-hwp"
        return ProcessedDocument(
            payload,
            original_bytes=content,
            converted_pdf_bytes=b"%PDF-1.7\ngenerated-pdf",
            pdf_metadata={
                "schema": "bidops.hwp-pdf-snapshot.v1",
                "renderer": "rhwp-canvas-chromium",
                "renderer_version": "1",
                "page_count": 2,
                "renderer_provenance": {"worker_image_digest": "c" * 64, "runtime_sha256": "a" * 64},
                "font_provenance": {"worker_image_digest": "c" * 64, "font_manifest_sha256": "b" * 64},
                "pages": self.processed.pdf_metadata["pages"],
            },
        )


def _selection(document: DocumentVersion, source: bytes):
    return select_v4_input_range({
        "document_version_id": str(document.id),
        "source_sha256": _sha(source),
        "pages": [
            {"number": 1, "text": "목차\nⅠ. 감리 개요\nⅡ. 제안요청 사항"},
            {"number": 2, "text": "Ⅰ. 감리 개요\n1. 목적\n본문\n2. 범위\n감리 범위\nⅡ. 제안요청 사항\n다음 장"},
        ],
        "blocks": [],
    })


def test_snapshot_roundtrip_stores_full_page_text_and_reuses_exact_binding(tmp_path: Path):
    source = b"%PDF-1.7\nfixture-original"
    engine = _engine()
    store = FilesystemObjectStore(tmp_path)
    scanner_calls: list[bytes] = []

    def scanner(value: bytes) -> bool:
        scanner_calls.append(value)
        return True

    with Session(engine) as session:
        document, source_location = _source(session, store, source)
        session.commit()
        converter = _Converter(_processed(source), scanner)
        snapshot = prepare_v4_pdf_snapshot(
            session,
            document_version_id=document.id,
            source_location_id=source_location.id,
            source_bytes=source,
            media_type="application/pdf",
            converter=converter,
            store=store,
            options={"prepare_pdf": True},
            renderer=_SOURCE_RENDERER,
            font=_SOURCE_FONT,
            config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True})), "text_extractor": "pdf-poppler-prepared"},
            scanner=scanner,
        )
        session.commit()
        assert snapshot.source_kind == "original"
        assert converter.calls == 1
        assert snapshot.source_content_object_id == snapshot.pdf_content_object_id
        assert snapshot.source_location_id == snapshot.pdf_location_id
        page_text, _ = store.get("structure", f"structure/prespec-v4/{document.id}/page-text-{snapshot.page_text_sha256}.json")
        assert "Ⅰ. 감리 개요" in json.loads(page_text)["pages"][0]["text"]
        assert scanner_calls.count(source) >= 2

        selection = _selection(document, source)
        assert selection.status == "ready"
        manifest_meta = store.put("structure", "structure/v4/manifest.json", selection.manifest_bytes, content_type="application/json")
        manifest_content = ContentObject(
            sha256=_sha(selection.manifest_bytes), size_bytes=len(selection.manifest_bytes), detected_mime="application/json", retention_class="prespec-v4-input"
        )
        session.add(manifest_content)
        session.flush()
        manifest_location = ContentObjectLocation(
            content_object_id=manifest_content.id, namespace_key="structure", object_key=manifest_meta.object_key,
            object_version_id=manifest_meta.object_version_id, etag=manifest_meta.etag, status="verified",
        )
        session.add(manifest_location)
        session.flush()
        target = freeze_v4_target(
            session,
            snapshot_id=snapshot.id,
            observation_kind="explicit_sample",
            observation_id=None,
            observation_reference={"sample": "notice-142"},
            selection=selection,
            manifest_content_object_id=manifest_content.id,
            manifest_location_id=manifest_location.id,
            manifest_bytes=selection.manifest_bytes,
        )
        session.commit()
        assert target.selection_status == "ready"
        assert target.identity_sha256 == _sha(json.dumps({
            "snapshot_id": str(snapshot.id),
            "observation_kind": "explicit_sample",
            "observation_id": None,
            "selection_manifest_sha256": target.selection_manifest_sha256,
            "selection_status": "ready",
            "reason_code": None,
        }, sort_keys=True, separators=(",", ":")).encode())

        # The canonical identity digest makes explicit samples idempotent even
        # though SQL NULL unique columns would otherwise permit duplicates.
        reused_target = freeze_v4_target(
            session,
            snapshot_id=snapshot.id,
            observation_kind="explicit_sample",
            observation_id=None,
            observation_reference={"sample": "notice-142"},
            selection=selection,
            manifest_content_object_id=manifest_content.id,
            manifest_location_id=manifest_location.id,
            manifest_bytes=selection.manifest_bytes,
        )
        assert reused_target.id == target.id

        reused_snapshot = prepare_v4_pdf_snapshot(
            session,
            document_version_id=document.id,
            source_location_id=source_location.id,
            source_bytes=source,
            media_type="application/pdf",
            converter=converter,
            store=store,
            options={"prepare_pdf": True},
            renderer=_SOURCE_RENDERER,
            font=_SOURCE_FONT,
            config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True})), "text_extractor": "pdf-poppler-prepared"},
            scanner=scanner,
        )
        assert reused_snapshot.id == snapshot.id
        assert converter.calls == 1

        # Cache reuse must honor the newest scan row.  An older clean result
        # cannot mask a later infected/unavailable verdict.
        session.add(ContentScan(
            content_object_id=snapshot.pdf_content_object_id,
            scanner="clamav",
            scanner_version="2",
            status="infected",
            safe_result={"verdict": "infected"},
            scanned_at=datetime.now(UTC) + timedelta(seconds=1),
        ))
        session.flush()
        with pytest.raises(V4PreparationError) as scan_error:
            prepare_v4_pdf_snapshot(
                session,
                document_version_id=document.id,
                source_location_id=source_location.id,
                source_bytes=source,
                media_type="application/pdf",
                converter=converter,
                store=store,
                options={"prepare_pdf": True},
                renderer=_SOURCE_RENDERER,
                font=_SOURCE_FONT,
                config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True})), "text_extractor": "pdf-poppler-prepared"},
                scanner=scanner,
            )
        assert scan_error.value.code == "scanner_unavailable"
        assert converter.calls == 1

        with pytest.raises(ValueError, match="append-only"):
            snapshot.pdf_metadata_jsonb = {"changed": True}
            session.flush()
        session.rollback()


def test_range_keeps_exact_substrings_and_marks_missing_boundary_for_human_review():
    selection = select_v4_input_range({
        "pages": [
            {"number": 1, "text": "목차\nⅠ. 감리 개요\nⅡ. 제안요청 사항"},
            {"number": 2, "text": "Ⅰ. 감리 개요\n1. 목적\n본문\nⅡ. 제안요청 사항\n다음"},
        ],
        "blocks": [],
    })
    assert selection.status == "ready"
    assert selection.page_numbers == (2,)
    assert "Ⅱ. 제안요청 사항" not in selection.manifest["pages"][0]["text"]
    assert selection.manifest["pages"][0]["source_page_text_sha256"] != selection.manifest["pages"][0]["text_sha256"]

    ambiguous = select_v4_input_range({
        "pages": [{"number": 1, "text": "Ⅰ. 감리 개요\n1. 목적\n본문"}],
        "blocks": [],
    })
    assert ambiguous.status == "needs_human_review"
    assert ambiguous.reason_code == "scope_end_missing"


def test_snapshot_rejects_page_text_or_scanner_failure(tmp_path: Path):
    source = b"%PDF-1.7\nfixture"
    engine = _engine()
    store = FilesystemObjectStore(tmp_path)
    with Session(engine) as session:
        document, source_location = _source(session, store, source)
        with pytest.raises(V4PreparationError) as error:
            prepare_v4_pdf_snapshot(
                session,
                document_version_id=document.id,
                source_location_id=source_location.id,
                source_bytes=source,
                media_type="application/pdf",
                converter=_Converter(_processed(source), lambda _value: False),
                store=store,
                options={"prepare_pdf": True},
                renderer=_SOURCE_RENDERER,
                font=_SOURCE_FONT,
                config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True}))},
                scanner=lambda _value: False,
            )
        assert error.value.code == "scanner_failed"
        assert session.scalar(select(PrespecV4PdfSnapshot)) is None


def test_generated_pdf_is_versioned_in_source_namespace(tmp_path: Path):
    source = b"HWP source bytes"
    engine = _engine()
    store = FilesystemObjectStore(tmp_path)
    with Session(engine) as session:
        document, source_location = _source(session, store, source)
        converter = _GeneratedConverter(_processed(source), lambda _value: True)
        snapshot = prepare_v4_pdf_snapshot(
            session,
            document_version_id=document.id,
            source_location_id=source_location.id,
            source_bytes=source,
            media_type="application/octet-stream",
            converter=converter,
            store=store,
            options={"prepare_pdf": True},
            renderer={"worker_image_digest": "c" * 64, "runtime_sha256": "a" * 64},
            font={"worker_image_digest": "c" * 64, "font_manifest_sha256": "b" * 64},
            config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True}))},
        )
        pdf_location = session.get(ContentObjectLocation, snapshot.pdf_location_id)
        assert snapshot.source_kind == "generated"
        assert snapshot.source_content_object_id != snapshot.pdf_content_object_id
        assert pdf_location is not None and pdf_location.namespace_key == "source"


def test_generated_pdf_requires_worker_emitted_provenance(tmp_path: Path):
    source = b"HWP source bytes"
    engine = _engine()
    store = FilesystemObjectStore(tmp_path)
    with Session(engine) as session:
        document, source_location = _source(session, store, source)
        converter = _GeneratedConverter(_processed(source), lambda _value: True)
        with pytest.raises(V4PreparationError) as error:
            prepare_v4_pdf_snapshot(
                session,
                document_version_id=document.id,
                source_location_id=source_location.id,
                source_bytes=source,
                media_type="application/octet-stream",
                converter=converter,
                store=store,
                options={"prepare_pdf": True},
                renderer={"worker_image_digest": "c" * 64, "runtime_sha256": "9" * 64},
                font={"worker_image_digest": "c" * 64, "font_manifest_sha256": "b" * 64},
                config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True}))},
            )
        assert error.value.code == "renderer_binding_invalid"
        assert converter.calls == 1
        assert session.scalar(select(PrespecV4PdfSnapshot)) is None
