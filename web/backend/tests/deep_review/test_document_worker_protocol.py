"""Scratch converter protocol tests: bounded, atomic, credential-free."""

import json
import hashlib
from pathlib import Path

import pytest

from app.deep_review.document_mcp.errors import DocumentProcessingError
from app.deep_review.document_mcp.processor import ProcessedDocument
from app.deep_review.document_mcp.safety import ProcessorOptions
from app.deep_review.services import document_converter
from app.deep_review.services.document_converter import ScratchDocumentProcessor
from app.deep_review import document_protocol
from app.deep_review.document_protocol import (
    ALLOWED_METADATA,
    PDF_PROTOCOL_SCHEMA,
    PDF_RESULT_SCHEMA,
    ScratchProtocolError,
    convert_one,
    write_request,
)
from tests.deep_review.test_rhwp_snapshot import native_processed


FIXTURE = Path(__file__).parents[1] / "fixtures" / "document_bundles" / "safe.pdf"


def clean_scan(content: bytes) -> dict[str, str]:
    return {
        "scanner": "clamav",
        "version": "clamd-instream-v1",
        "sha256": hashlib.sha256(content).hexdigest(),
        "verdict": "clean",
    }


def test_scratch_protocol_processes_structure_without_request_or_credentials(tmp_path: Path):
    request = write_request(
        tmp_path,
        request_id="11111111-1111-4111-8111-111111111111",
        content=FIXTURE.read_bytes(),
        media_type="application/pdf",
        original_filename="safe.pdf",
        options={"ocr": False, "render_pages": False},
        scan=clean_scan(FIXTURE.read_bytes()),
    )
    envelope = json.loads(request.read_text(encoding="utf-8"))
    assert set(envelope) == ALLOWED_METADATA
    assert not any(token in json.dumps(envelope).lower() for token in ("password", "secret", "token", "authorization", "credential"))
    assert convert_one(tmp_path) is True
    result = json.loads((tmp_path / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
    assert result["status"] == "succeeded"
    assert "original_bytes" not in result and "request_headers" not in result
    assert FIXTURE.read_bytes() not in (tmp_path / "results" / f"{request.stem}.json").read_bytes()
    assert "structure" in result and result["structure"]["source_sha256"]


def test_scratch_protocol_rejects_credential_bearing_or_traversal_envelopes(tmp_path: Path):
    request = write_request(
        tmp_path,
        request_id="22222222-2222-4222-8222-222222222222",
        content=FIXTURE.read_bytes(),
        media_type="application/pdf",
        original_filename="safe.pdf",
        scan=clean_scan(FIXTURE.read_bytes()),
    )
    envelope = json.loads(request.read_text(encoding="utf-8"))
    envelope["credential"] = "must-not-cross"
    request.write_text(json.dumps(envelope), encoding="utf-8")
    assert convert_one(tmp_path) is True
    result = json.loads((tmp_path / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert "must-not-cross" not in json.dumps(result)

    with pytest.raises(ScratchProtocolError):
        write_request(
            tmp_path,
            request_id="33333333-3333-4333-8333-333333333333",
            content=FIXTURE.read_bytes(),
            media_type="application/pdf",
            original_filename="../escape.pdf",
        )


def test_trusted_scan_verdicts_gate_production_spooling(tmp_path: Path):
    content = FIXTURE.read_bytes()
    clean = ScratchDocumentProcessor(tmp_path / "clean", clamav_checker=lambda _content: True)
    assert clean.clamav_checker(content) is True

    with pytest.raises(DocumentProcessingError, match="malware"):
        ScratchDocumentProcessor(tmp_path / "infected", clamav_checker=lambda _content: False).process(content, "application/pdf")

    def unavailable(_content: bytes) -> bool:
        raise OSError("scanner unavailable")

    with pytest.raises(DocumentProcessingError, match="malware"):
        ScratchDocumentProcessor(tmp_path / "unavailable", clamav_checker=unavailable).process(content, "application/pdf")

    request = write_request(
        tmp_path / "tamper",
        request_id="44444444-4444-4444-8444-444444444444",
        content=content,
        media_type="application/pdf",
        original_filename="safe.pdf",
        scan=clean_scan(content),
    )
    (request.parent / f"{request.stem}.bin").write_bytes(b"tampered")
    assert convert_one(tmp_path / "tamper") is True
    result = json.loads((tmp_path / "tamper" / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"


def test_result_consumer_rejects_source_hash_tamper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "result-tamper"
    real_write_request = document_converter.write_request

    def write_bad_result(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = real_write_request(*args, **kwargs)
        assert convert_one(root) is True
        result_path = root / "results" / f"{request.stem}.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["structure"]["source_sha256"] = "0" * 64
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return request

    monkeypatch.setattr(document_converter, "write_request", write_bad_result)
    processor = ScratchDocumentProcessor(root, wait_seconds=2, clamav_checker=lambda _content: True)
    with pytest.raises(DocumentProcessingError) as error:
        processor.process(FIXTURE.read_bytes(), "application/pdf", {"ocr": False, "render_pages": False})
    assert error.value.code == "hash_mismatch"


def _generated_native_document(content: bytes, pdf: bytes) -> ProcessedDocument:
    """Return the native HWP artifact bundle a worker publishes for ``content``.

    The shared native fixture is reused so this protocol test binds the same
    sidecars the persistence tests do; only the source identity and the
    generated PDF bytes are specific to this request.
    """

    native = native_processed(hwp=True)
    structure = dict(native)
    structure["source_sha256"] = hashlib.sha256(content).hexdigest()
    return ProcessedDocument(
        structure,
        original_bytes=content,
        converted_pdf_bytes=pdf,
        hwpx_bytes=native.hwpx_bytes,
        hwpx_verify=native.hwpx_verify,
        page_text=native.page_text,
        page_dump=native.page_dump,
        para_page_map=native.para_page_map,
        para_page_map_bytes=native.para_page_map_bytes,
        section_candidates=native.section_candidates,
        section_candidates_bytes=native.section_candidates_bytes,
        pdf_metadata=native.pdf_metadata,
    )


def _patch_generated_pdf_processor(monkeypatch: pytest.MonkeyPatch, pdf: bytes) -> None:
    class FakeProcessor:
        def __init__(self, **_kwargs):
            pass

        def process(self, content: bytes, media_type: str, _options: dict[str, object]) -> ProcessedDocument:
            return _generated_native_document(content, pdf)

    monkeypatch.setattr(document_protocol, "DocumentProcessor", FakeProcessor)


def test_pdf_v2_round_trip_publishes_and_consumes_one_bound_sidecar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "pdf-v2"
    source = FIXTURE.read_bytes()
    generated = b"%PDF-1.7\nmock generated PDF\n%%EOF"
    _patch_generated_pdf_processor(monkeypatch, generated)
    calls: list[bytes] = []
    real_write_request = document_converter.write_request

    def write_and_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = real_write_request(*args, **kwargs)
        envelope = json.loads(request.read_text(encoding="utf-8"))
        assert envelope["schema"] == PDF_PROTOCOL_SCHEMA
        assert convert_one(root) is True
        result = json.loads((root / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
        assert result["schema"] == PDF_RESULT_SCHEMA
        assert result["pdf_sidecar"]["file"] == f"pdf/{request.stem}.pdf"
        return request

    monkeypatch.setattr(document_converter, "write_request", write_and_run)

    def clean(content: bytes) -> bool:
        calls.append(content)
        return True

    processed = ScratchDocumentProcessor(root, wait_seconds=2, clamav_checker=clean).process(
        source,
        "application/pdf",
        {"ocr": False, "prepare_pdf": True, "max_output_bytes": 1024 * 1024},
    )

    expected = _generated_native_document(source, generated)
    assert processed.original_bytes == source
    assert processed.converted_pdf_bytes == generated
    assert processed.pdf_metadata == expected.pdf_metadata
    assert processed.pdf_metadata["schema"] == "bidops.rhwp-pdf-snapshot.v1"
    assert processed.para_page_map_bytes == expected.para_page_map_bytes
    assert calls == [source, generated, expected.hwpx_bytes]
    assert not list((root / "inbox").glob("*"))
    assert not list((root / "claimed").glob("*"))
    assert not list((root / "results").glob("*"))
    assert not list((root / "pdf").glob("*"))


def test_pdf_v2_original_pdf_uses_detected_media_and_preserves_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "original-pdf"
    source = FIXTURE.read_bytes()
    real_write_request = document_converter.write_request

    def write_and_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = real_write_request(*args, **kwargs)
        assert convert_one(root) is True
        result = json.loads((root / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
        assert result["pdf_sidecar"]["source_kind"] == "original"
        assert result["pdf_sidecar"]["metadata"]["schema"] == "bidops.pdf-snapshot.v1"
        assert result["pdf_sidecar"]["metadata"]["rerendered"] is False
        assert result["pdf_sidecar"]["metadata"]["font_provenance"] is None
        assert result["pdf_sidecar"]["metadata"]["processor_provenance"]["text_extractor"]["name"] in {
            "pdf-poppler-prepared", "pdf-stdlib-prepared",
        }
        return request

    monkeypatch.setattr(document_converter, "write_request", write_and_run)
    processed = ScratchDocumentProcessor(root, wait_seconds=2, clamav_checker=lambda _content: True).process(
        source,
        "application/octet-stream",
        ProcessorOptions(ocr=False, prepare_pdf=True, render_pages=False, max_pdf_objects=4096),
    )
    assert processed.original_bytes == source
    assert processed.converted_pdf_bytes == source
    assert processed.pdf_metadata["page_count"] == len(processed["pages"]) == 1
    assert processed.pdf_metadata["pages"][0]["text_sha256"]


def test_pdf_v2_original_source_kind_rejects_generated_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "original-mismatch"
    source = FIXTURE.read_bytes()
    generated = b"%PDF-1.7\nnot the source\n%%EOF"
    _patch_generated_pdf_processor(monkeypatch, generated)
    real_write_request = document_converter.write_request

    def write_and_tamper(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = real_write_request(*args, **kwargs)
        assert convert_one(root) is True
        result_path = root / "results" / f"{request.stem}.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["pdf_sidecar"]["source_kind"] = "original"
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return request

    monkeypatch.setattr(document_converter, "write_request", write_and_tamper)
    with pytest.raises(DocumentProcessingError) as error:
        ScratchDocumentProcessor(root, wait_seconds=2, clamav_checker=lambda _content: True).process(
            source,
            "application/pdf",
            {"ocr": False, "prepare_pdf": True, "max_output_bytes": 1024 * 1024},
        )
    assert error.value.code == "hash_mismatch"


def test_pdf_v2_original_pdf_requires_physical_page_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "original-metadata"
    source = FIXTURE.read_bytes()
    real_write_request = document_converter.write_request

    def write_and_tamper(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = real_write_request(*args, **kwargs)
        assert convert_one(root) is True
        result_path = root / "results" / f"{request.stem}.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["pdf_sidecar"]["metadata"] = {}
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return request

    monkeypatch.setattr(document_converter, "write_request", write_and_tamper)
    with pytest.raises(DocumentProcessingError) as error:
        ScratchDocumentProcessor(root, wait_seconds=2, clamav_checker=lambda _content: True).process(
            source,
            "application/octet-stream",
            {"ocr": False, "prepare_pdf": True},
        )
    assert error.value.code == "pdf_metadata_invalid"


def test_pdf_v2_rejects_symlink_input_and_preserves_other_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "symlink"
    source = FIXTURE.read_bytes()
    other = tmp_path / "other-request.bin"
    other.write_bytes(source)
    request = write_request(
        root,
        request_id="55555555-5555-4555-8555-555555555555",
        content=source,
        media_type="application/pdf",
        original_filename="safe.pdf",
        options={"ocr": False, "prepare_pdf": True},
        scan=clean_scan(source),
    )
    content_path = request.parent / f"{request.stem}.bin"
    content_path.unlink()
    content_path.symlink_to(other)
    assert convert_one(root) is True
    result = json.loads((root / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
    assert result["schema"] == PDF_RESULT_SCHEMA
    assert result["status"] == "failed"
    assert result["error"]["code"] == "processing_failed"
    assert other.read_bytes() == source


def test_pdf_v2_rejects_sidecar_hash_tamper_and_cleans_owned_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "sidecar-tamper"
    source = FIXTURE.read_bytes()
    generated = b"%PDF-1.7\nmock generated PDF\n%%EOF"
    _patch_generated_pdf_processor(monkeypatch, generated)
    real_write_request = document_converter.write_request

    def write_and_tamper(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = real_write_request(*args, **kwargs)
        assert convert_one(root) is True
        sidecar = root / "pdf" / f"{request.stem}.pdf"
        sidecar.write_bytes(generated + b"tamper")
        return request

    monkeypatch.setattr(document_converter, "write_request", write_and_tamper)
    with pytest.raises(DocumentProcessingError) as error:
        ScratchDocumentProcessor(root, wait_seconds=2, clamav_checker=lambda _content: True).process(
            source,
            "application/pdf",
            {"ocr": False, "prepare_pdf": True, "max_output_bytes": 1024 * 1024},
        )
    assert error.value.code == "hash_mismatch"
    assert not list((root / "results").glob("*"))
    assert not list((root / "pdf").glob("*"))


def test_pdf_v2_generated_sidecar_scanner_failure_is_not_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "sidecar-scan"
    source = FIXTURE.read_bytes()
    generated = b"%PDF-1.7\nmock generated PDF\n%%EOF"
    _patch_generated_pdf_processor(monkeypatch, generated)
    real_write_request = document_converter.write_request

    def write_and_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = real_write_request(*args, **kwargs)
        assert convert_one(root) is True
        return request

    monkeypatch.setattr(document_converter, "write_request", write_and_run)
    calls = 0

    def scan(_content: bytes) -> bool:
        nonlocal calls
        calls += 1
        return calls == 1

    with pytest.raises(DocumentProcessingError) as error:
        ScratchDocumentProcessor(root, wait_seconds=2, clamav_checker=scan).process(
            source,
            "application/pdf",
            {"ocr": False, "prepare_pdf": True, "max_output_bytes": 1024 * 1024},
        )
    assert error.value.code == "malware_detected"
    assert calls == 2
    assert not list((root / "results").glob("*"))
    assert not list((root / "pdf").glob("*"))


def test_pdf_v2_timeout_cleans_claimed_input_without_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "timeout"

    class TimeoutProcessor:
        def __init__(self, **_kwargs):
            pass

        def process(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise document_protocol._ConversionTimeout

    monkeypatch.setattr(document_protocol, "DocumentProcessor", TimeoutProcessor)
    source = FIXTURE.read_bytes()
    request = write_request(
        root,
        request_id="66666666-6666-4666-8666-666666666666",
        content=source,
        media_type="application/pdf",
        original_filename="safe.pdf",
        options={"ocr": False, "prepare_pdf": True},
        scan=clean_scan(source),
    )
    assert convert_one(root) is True
    result = json.loads((root / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "timeout"
    assert not list((root / "inbox").glob("*"))
    assert not list((root / "claimed").glob("*"))
    assert not list((root / "pdf").glob("*"))


def test_pdf_v2_sidecar_size_limit_fails_before_metadata_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "sidecar-size"
    source = FIXTURE.read_bytes()
    _patch_generated_pdf_processor(monkeypatch, b"%PDF-1.7\nsidecar too large\n%%EOF")
    request = write_request(
        root,
        request_id="77777777-7777-4777-8777-777777777777",
        content=source,
        media_type="application/pdf",
        original_filename="safe.pdf",
        options={"ocr": False, "prepare_pdf": True, "max_output_bytes": 1},
        scan=clean_scan(source),
    )
    assert convert_one(root) is True
    result = json.loads((root / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "output_size_limit"
    assert not list((root / "pdf").glob("*"))
    assert not list((root / "claimed").glob("*"))
    assert not list((root / "inbox").glob("*"))


def test_worker_cleanup_does_not_touch_another_request(tmp_path: Path):
    root = tmp_path / "two-requests"
    source = FIXTURE.read_bytes()
    first = write_request(
        root,
        request_id="11111111-1111-4111-8111-111111111111",
        content=source,
        media_type="application/pdf",
        original_filename="first.pdf",
        scan=clean_scan(source),
    )
    second = write_request(
        root,
        request_id="99999999-9999-4999-8999-999999999999",
        content=source,
        media_type="application/pdf",
        original_filename="second.pdf",
        scan=clean_scan(source),
    )
    assert convert_one(root) is True
    assert not first.exists()
    assert second.exists()
    assert (root / "inbox" / f"{second.stem}.bin").exists()


def test_pdf_v2_publishes_and_rebinds_the_section_candidate_sidecar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "candidates"
    source = FIXTURE.read_bytes()
    generated = b"%PDF-1.7\nmock generated PDF\n%%EOF"
    _patch_generated_pdf_processor(monkeypatch, generated)
    expected = _generated_native_document(source, generated)
    real_write_request = document_converter.write_request
    published: list[dict[str, object]] = []

    def write_and_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = real_write_request(*args, **kwargs)
        assert convert_one(root) is True
        result = json.loads((root / "results" / f"{request.stem}.json").read_text(encoding="utf-8"))
        descriptor = result["native_sidecars"]["section_candidates"]
        sidecar = root / "native" / f"{request.stem}.section-candidates.json"
        data = sidecar.read_bytes()
        assert descriptor["file"] == f"native/{sidecar.name}"
        assert descriptor["byte_count"] == len(data) == len(expected.section_candidates_bytes)
        assert descriptor["sha256"] == hashlib.sha256(data).hexdigest()
        assert data == expected.section_candidates_bytes
        published.append(descriptor)
        return request

    monkeypatch.setattr(document_converter, "write_request", write_and_run)
    processed = ScratchDocumentProcessor(root, wait_seconds=2, clamav_checker=lambda _content: True).process(
        source,
        "application/pdf",
        {"ocr": False, "prepare_pdf": True, "max_output_bytes": 1024 * 1024},
    )
    assert len(published) == 1
    assert processed.section_candidates == expected.section_candidates
    assert processed.section_candidates_bytes == expected.section_candidates_bytes
    assert not list((root / "native").glob("*"))


@pytest.mark.parametrize(
    ("tamper", "expected_code"),
    [("bytes", "hash_mismatch"), ("descriptor", "section_candidates_invalid"), ("missing", "rhwp_manifest_invalid")],
)
def test_pdf_v2_rejects_a_tampered_or_absent_section_candidate_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tamper: str, expected_code: str,
):
    root = tmp_path / f"candidate-{tamper}"
    source = FIXTURE.read_bytes()
    generated = b"%PDF-1.7\nmock generated PDF\n%%EOF"
    _patch_generated_pdf_processor(monkeypatch, generated)
    real_write_request = document_converter.write_request

    def write_and_tamper(*args, **kwargs):  # type: ignore[no-untyped-def]
        request = real_write_request(*args, **kwargs)
        assert convert_one(root) is True
        result_path = root / "results" / f"{request.stem}.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        sidecar = root / "native" / f"{request.stem}.section-candidates.json"
        if tamper == "missing":
            # A new native build that publishes no candidate sidecar fails closed.
            sidecar.unlink()
            del result["native_sidecars"]["section_candidates"]
        else:
            payload = json.loads(sidecar.read_bytes())
            payload["sections"][0]["page"] = 99
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            sidecar.write_bytes(data)
            if tamper == "descriptor":
                result["native_sidecars"]["section_candidates"].update(
                    sha256=hashlib.sha256(data).hexdigest(), byte_count=len(data),
                )
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return request

    monkeypatch.setattr(document_converter, "write_request", write_and_tamper)
    with pytest.raises(DocumentProcessingError) as error:
        ScratchDocumentProcessor(root, wait_seconds=2, clamav_checker=lambda _content: True).process(
            source,
            "application/pdf",
            {"ocr": False, "prepare_pdf": True, "max_output_bytes": 1024 * 1024},
        )
    assert error.value.code == expected_code
    assert not list((root / "native").glob("*"))
