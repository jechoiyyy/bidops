"""Native scratch handoff and immutable artifact/cache binding contracts."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.models import AuditEvent
from app.core.object_store import FilesystemObjectStore
from app.deep_review import document_protocol
from app.deep_review.document_mcp import process_document
from app.deep_review.document_mcp.contracts import para_page_map_bytes
from app.deep_review.document_mcp.errors import DocumentProcessingError
from app.deep_review.document_mcp.para_page_map import build_para_page_map
from app.deep_review.document_mcp.processor import ProcessedDocument
from app.deep_review.document_mcp.safety import ProcessorOptions
from app.deep_review.models import ContentObject, ContentObjectLocation, ContentScan, DocumentStructure, PrespecV4PdfSnapshot
from app.deep_review.services import document_converter
from app.deep_review.services.document_converter import ScratchDocumentProcessor
from app.deep_review.services.prespec_v4 import V4PreparationError, prepare_v4_pdf_snapshot
from app.deep_review.services.prespec_v4_runner import record_v4_preparation_failure
from tests.deep_review.test_document_mcp import hwpx_bytes, text_pdf
from tests.deep_review.test_prespec_v4_preparation import _engine, _source

RENDERER = {"renderer": "rhwp-svg-pdf", "rhwp_version": "0.8.6", "rhwp_binary_sha256": "a" * 64, "backend": "svg", "compat": "2022", "fallback_fonts": {"serif": "NanumMyeongjo", "sans": "NanumGothic", "mono": "NanumGothicCoding"}, "worker_image_digest": None}
FONT = {"font_manifest_sha256": "b" * 64}
OPTIONS = ProcessorOptions.from_mapping({"prepare_pdf": True, "renderer": "rhwp-svg-pdf", "ocr": False})


def native_processed(*, hwp=False):
    hwpx = hwpx_bytes()
    source = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1fake-hwp" if hwp else hwpx
    structure = dict(process_document(hwpx, "application/hwp+zip", {"ocr": False}))
    structure["source_sha256"] = hashlib.sha256(source).hexdigest()
    structure["media_type"] = "application/x-hwp" if hwp else "application/hwp+zip"
    # Physical PDF text intentionally differs from XML section/block text.
    text = "Ⅰ. 사업 개요\n사업 예산 123,456,789원\nⅡ. 제안요청 사항"
    page = {"number": 1, "display_page": 7, "section": 0, "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
    page_text = {"schema": "bidops.rhwp-page-text.v1", "page_count": 1, "pages": [page]}
    dump = {"schemaVersion": "1.0", "pageCount": 1, "pages": [{"pageIndex": 0, "section": 0, "columns": [], "extras": []}]}
    mapping = build_para_page_map(structure["blocks"], dump, page_text, original_hwpx=not hwp)
    return ProcessedDocument(structure, original_bytes=source, converted_pdf_bytes=text_pdf(), hwpx_bytes=hwpx,
        hwpx_verify={"identical": True, "diff_count": 0, "pages": {"before": 1, "after": 1, "identical": True}} if hwp else None,
        page_text=page_text, para_page_map=mapping, para_page_map_bytes=para_page_map_bytes(mapping, max_output_bytes=OPTIONS.max_output_bytes),
        pdf_metadata={"schema": "bidops.rhwp-pdf-snapshot.v1", "renderer": "rhwp-svg-pdf", "renderer_version": "1", "page_count": 1, "renderer_provenance": copy.deepcopy(RENDERER), "font_provenance": FONT, "pages": [{k: v for k, v in page.items() if k != "text"}]})


class NativeConverter:
    clamav_checker = staticmethod(lambda _: True)

    def __init__(self, processed):
        self.processed, self.calls = processed, 0

    def process(self, *_args):
        self.calls += 1
        return self.processed


def seed_native(session, store, processed):
    document, location = _source(session, store, processed.original_bytes)
    content = session.get(ContentObject, document.content_object_id)
    content.detected_mime = processed["media_type"]
    return document, location


def prepare(session, store, document, location, converter, **overrides):
    args = dict(document_version_id=document.id, source_location_id=location.id, source_bytes=converter.processed.original_bytes,
        media_type=converter.processed["media_type"], converter=converter, store=store, options=OPTIONS,
        renderer=RENDERER, font=FONT, config={"options": vars(OPTIONS)})
    args.update(overrides)
    return prepare_v4_pdf_snapshot(session, **args)


def wire_worker(monkeypatch, root, processed, after=None):
    class Worker:
        def __init__(self, **_kwargs):
            pass

        def process(self, *_args):
            return processed

    monkeypatch.setattr(document_protocol, "DocumentProcessor", Worker)
    real_write = document_converter.write_request

    def write(*args, **kwargs):
        request = real_write(*args, **kwargs)
        assert document_protocol.convert_one(root)
        if after:
            after(request)
        return request

    monkeypatch.setattr(document_converter, "write_request", write)


@pytest.mark.parametrize("hwp", [False, True])
def test_native_scratch_roundtrip_preserves_sidecars_and_cleans_files(monkeypatch, tmp_path, hwp):
    processed = native_processed(hwp=hwp)
    wire_worker(monkeypatch, tmp_path, processed)
    scanned = []
    processor = ScratchDocumentProcessor(tmp_path, wait_seconds=1, clamav_checker=lambda data: scanned.append(data) or True)
    result = processor.process(processed.original_bytes, processed["media_type"], OPTIONS)
    assert result.page_text == processed.page_text
    assert result.hwpx_bytes == processed.hwpx_bytes
    assert result.para_page_map_bytes == processed.para_page_map_bytes
    assert result.hwpx_verify == processed.hwpx_verify
    assert processed.converted_pdf_bytes in scanned
    assert (processed.hwpx_bytes in scanned)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


@pytest.mark.parametrize("tamper", ["hash", "missing", "path", "symlink", "verify", "page_text"])
def test_native_scratch_rejects_tamper(monkeypatch, tmp_path, tamper):
    processed = native_processed(hwp=True)
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.write_bytes(b"outside")

    def alter(request):
        result_path = tmp_path / "results" / request.name
        result = json.loads(result_path.read_bytes())
        paths = document_protocol.native_sidecar_paths(tmp_path, request.stem)
        if tamper == "hash":
            paths["para_page_map"].write_bytes(b"{}")
        elif tamper == "missing":
            paths["hwpx"].unlink()
        elif tamper == "path":
            result["native_sidecars"]["hwpx"]["file"] = "../outside"
        elif tamper == "symlink":
            paths["hwpx"].unlink()
            paths["hwpx"].symlink_to(outside)
        elif tamper == "verify":
            result["native_sidecars"]["hwpx_verify"]["identical"] = False
        else:
            payload = json.loads(paths["page_text"].read_bytes())
            payload["pages"][0]["text"] = "wrong text"
            data = json.dumps(payload).encode()
            paths["page_text"].write_bytes(data)
            result["native_sidecars"]["page_text"].update(sha256=hashlib.sha256(data).hexdigest(), byte_count=len(data))
        result_path.write_text(json.dumps(result))

    wire_worker(monkeypatch, tmp_path, processed, alter)
    with pytest.raises(DocumentProcessingError):
        ScratchDocumentProcessor(tmp_path, wait_seconds=1, clamav_checker=lambda _: True).process(processed.original_bytes, processed["media_type"], OPTIONS)
    assert outside.read_bytes() == b"outside"
    assert not list((tmp_path / "native").iterdir())


def test_native_publish_failure_removes_partial_bundle(monkeypatch, tmp_path):
    processed = native_processed(hwp=True)
    wire_worker(monkeypatch, tmp_path, processed)
    real_write = document_protocol._atomic_write

    def write(path, content, **kwargs):
        if path.name.endswith("para-page-map.json"):
            raise OSError("disk full")
        return real_write(path, content, **kwargs)

    monkeypatch.setattr(document_protocol, "_atomic_write", write)
    with pytest.raises(DocumentProcessingError):
        ScratchDocumentProcessor(tmp_path, wait_seconds=1, clamav_checker=lambda _: True).process(processed.original_bytes, processed["media_type"], OPTIONS)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


@pytest.mark.parametrize("hwp", [False, True])
def test_native_snapshot_stores_exact_objects_and_reuses_verified_cache(tmp_path, hwp):
    store = FilesystemObjectStore(tmp_path)
    with Session(_engine()) as session:
        processed = native_processed(hwp=hwp)
        document, location = seed_native(session, store, processed)
        converter = NativeConverter(processed)
        snapshot = prepare(session, store, document, location, converter)
        session.commit()
        assert snapshot.rhwp_version == "0.8.6"
        assert snapshot.para_page_map_sha256 == hashlib.sha256(processed.para_page_map_bytes).hexdigest()
        assert (snapshot.hwpx_content_object_id is not None) == hwp
        assert (snapshot.hwpx_verify_jsonb is not None) == hwp
        text_location = session.get(ContentObjectLocation, snapshot.page_text_location_id)
        data, _ = store.get(text_location.namespace_key, text_location.object_key, version_id=text_location.object_version_id)
        assert json.loads(data) == processed.page_text
        assert prepare(session, store, document, location, converter).id == snapshot.id
        assert converter.calls == 1
        assert session.scalar(select(func.count()).select_from(DocumentStructure)) == 1
        # Native renderer digest includes every declared renderer field.
        changed = copy.deepcopy(RENDERER)
        changed["worker_image_digest"] = "d" * 64
        processed.pdf_metadata["renderer_provenance"] = changed
        second = prepare(session, store, document, location, converter, renderer=changed)
        assert second.id != snapshot.id and second.renderer_digest != snapshot.renderer_digest
        assert second.structure_id == snapshot.structure_id


@pytest.mark.parametrize("artifact", ["structure", "hwpx", "para_page_map"])
@pytest.mark.parametrize("damage", ["missing", "changed_version", "changed_bytes"])
def test_native_cache_revalidates_every_pinned_sidecar(tmp_path, artifact, damage):
    store = FilesystemObjectStore(tmp_path)
    with Session(_engine()) as session:
        processed = native_processed(hwp=True)
        document, location = seed_native(session, store, processed)
        converter = NativeConverter(processed)
        snapshot = prepare(session, store, document, location, converter)
        session.commit()
        pinned = session.get(ContentObjectLocation, getattr(snapshot, f"{artifact}_location_id"))
        original_get = store.get

        def get(namespace, key, **kwargs):
            if key == pinned.object_key:
                assert kwargs["version_id"] == pinned.object_version_id
                if damage == "missing":
                    raise OSError("missing")
                data, metadata = original_get(namespace, key, **kwargs)
                if damage == "changed_bytes":
                    return b"x" * len(data), metadata
                from dataclasses import replace
                return data, replace(metadata, object_version_id="changed")
            return original_get(namespace, key, **kwargs)

        store.get = get
        with pytest.raises(V4PreparationError):
            prepare(session, store, document, location, converter)
        assert converter.calls == 1
        assert session.scalar(select(func.count()).select_from(PrespecV4PdfSnapshot)) == 1


def test_native_structure_conflict_preserves_existing_rows(tmp_path):
    store = FilesystemObjectStore(tmp_path)
    with Session(_engine()) as session:
        processed = native_processed()
        document, location = seed_native(session, store, processed)
        converter = NativeConverter(processed)
        first = prepare(session, store, document, location, converter)
        session.commit()
        structure_id = first.structure_id
        changed = copy.deepcopy(RENDERER)
        changed["worker_image_digest"] = "d" * 64
        processed.pdf_metadata["renderer_provenance"] = changed
        processed["blocks"][0]["text"] = "different structure"
        with pytest.raises(V4PreparationError) as error:
            prepare(session, store, document, location, converter, renderer=changed)
        assert error.value.code == "structure_binding_mismatch"
        session.rollback()
        assert session.get(PrespecV4PdfSnapshot, first.id).structure_id == structure_id
        assert session.scalar(select(func.count()).select_from(DocumentStructure)) == 1


@pytest.mark.parametrize("code", ["hwpx_verify_failed", "timeout", "rhwp_manifest_invalid", "para_page_map_invalid", "secret-bearing arbitrary error"])
def test_converter_failure_keeps_safe_code_in_attempt_and_audit(tmp_path, code):
    store = FilesystemObjectStore(tmp_path)
    with Session(_engine()) as session:
        processed = native_processed()
        document, location = seed_native(session, store, processed)
        converter = NativeConverter(processed)

        def fail(*_args):
            raise DocumentProcessingError(code, "secret-bearing stderr", source_preserved=True)

        converter.process = fail
        with pytest.raises(V4PreparationError) as error:
            prepare(session, store, document, location, converter)
        safe = code in document_converter.SAFE_CONVERTER_CODES
        expected = "pdf_preparation_failed" + (f":{code}" if safe else "")
        assert error.value.code == expected
        attempt = record_v4_preparation_failure(session, notice_id=document.notice_id, error_code=error.value.code)
        session.flush()
        audit = session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(attempt.id)))
        assert attempt.error_code == expected
        assert audit.safe_metadata.get("converter_code") == (code if safe else None)
        assert "secret-bearing" not in json.dumps(audit.safe_metadata)


@pytest.mark.parametrize("field", ["renderer", "font", "text", "metadata", "map"])
def test_native_freeze_rejects_unbound_or_extra_metadata(tmp_path, field):
    store = FilesystemObjectStore(tmp_path)
    with Session(_engine()) as session:
        processed = native_processed()
        document, location = seed_native(session, store, processed)
        if field == "renderer":
            processed.pdf_metadata["renderer_provenance"]["rhwp_binary_sha256"] = "c" * 64
        elif field == "font":
            processed.pdf_metadata["font_provenance"] = {"font_manifest_sha256": "c" * 64}
        elif field == "text":
            processed.page_text["pages"][0]["text"] = "wrong text"
        elif field == "metadata":
            processed.pdf_metadata["unexpected_path"] = "/must/not/persist"
        else:
            processed.para_page_map_bytes = b"{}"
        with pytest.raises(V4PreparationError):
            prepare(session, store, document, location, NativeConverter(processed))
        assert session.scalar(select(func.count()).select_from(PrespecV4PdfSnapshot)) == 0


@pytest.mark.parametrize("artifact", ["source", "pdf", "page_text"])
def test_first_native_freeze_reads_all_stored_base_artifacts(tmp_path, artifact):
    store = FilesystemObjectStore(tmp_path)
    with Session(_engine()) as session:
        processed = native_processed()
        document, location = seed_native(session, store, processed)
        real_get = store.get

        def get(namespace, key, **kwargs):
            data, metadata = real_get(namespace, key, **kwargs)
            match = key == location.object_key if artifact == "source" else ("/pdf-" in key if artifact == "pdf" else "/page-text-" in key)
            return (b"x" * len(data) if match else data), metadata

        store.get = get
        with pytest.raises(V4PreparationError) as error:
            prepare(session, store, document, location, NativeConverter(processed))
        assert error.value.code == "artifact_hash_mismatch"
        assert session.scalar(select(func.count()).select_from(PrespecV4PdfSnapshot)) == 0
