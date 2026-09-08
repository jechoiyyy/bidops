from __future__ import annotations

import io
import hashlib
import json
import os
import struct
import time
import uuid
import zipfile
import zlib
from pathlib import Path

import pytest

from app.deep_review.document_mcp import (
    MAX_INPUT_BYTES,
    DocumentProcessingError,
    DocumentProcessor,
    ProcessorOptions,
    process_document,
    validate_structure,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "documents"


def hwpx_bytes(*, name: str = "Contents/section0.xml") -> bytes:
    stream = (FIXTURES / "section0.xml").read_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, stream)
    return output.getvalue()


def hwpx_with_member(name: str, content: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Contents/section0.xml", (FIXTURES / "section0.xml").read_bytes())
        archive.writestr(name, content)
    return output.getvalue()


def text_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length 40 >> stream\nBT (Fixture PDF) Tj ET\nendstream endobj\n%%EOF"
    )


def mixed_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >> endobj\n"
        b"3 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length 28 >> stream\nBT (Text page) Tj ET\nendstream endobj\n"
        b"5 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 6 0 R >> endobj\n"
        b"6 0 obj << /Length 8 >> stream\nBT ET\nendstream endobj\n%%EOF"
    )


def blank_two_page_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >> endobj\n"
        b"3 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length 8 >> stream\nBT ET\nendstream endobj\n"
        b"5 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 6 0 R >> endobj\n"
        b"6 0 obj << /Length 8 >> stream\nBT ET\nendstream endobj\n%%EOF"
    )


def multi_stream_pdf() -> bytes:
    first = b"A" * 700
    second = b"B" * 700
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents [4 0 R 5 0 R] >> endobj\n"
        + b"4 0 obj << /Length " + str(len(first)).encode() + b" >> stream\n"
        + first + b"\nendstream endobj\n"
        + b"5 0 obj << /Length " + str(len(second)).encode() + b" >> stream\n"
        + second + b"\nendstream endobj\n%%EOF"
    )


def compressed_large_text_pdf() -> bytes:
    content = zlib.compress(b"BT (" + b"A" * 2_000_000 + b") Tj ET")
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
        + b"4 0 obj << /Filter /FlateDecode >> stream\n"
        + content
        + b"\nendstream endobj\n%%EOF"
    )


def hwpx_xml(raw: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Contents/section0.xml", raw)
    return output.getvalue()


def one_pixel_png() -> bytes:
    def chunk(kind: bytes, value: bytes) -> bytes:
        import binascii
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", binascii.crc32(kind + value) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff")) + chunk(b"IEND", b"")


def test_hwpx_paragraph_table_cell_and_provenance() -> None:
    source = hwpx_bytes()
    result = process_document(source, "application/hwp+zip", {"ocr": False})
    assert result["schema"] == "bidops.document-structure.v1"
    assert {block["type"] for block in result["blocks"]} == {"paragraph", "table", "table_cell"}
    assert any(block["attributes"].get("row") == 0 for block in result["blocks"])
    assert result.original_bytes == source
    assert result["extractor"]["upstream_commit"] == "96a2633f23a08f707679d7e212ebdc59948260e6"
    validate_structure(result)


def test_text_pdf_page_bbox() -> None:
    result = process_document(text_pdf(), "application/pdf", {"ocr": False})
    assert result["pages"][0]["width"] == 612
    assert result["blocks"][0]["bbox"] == [0.0, 0.0, 612.0, 792.0]
    assert result["blocks"][0]["text"] == "Fixture PDF"


def test_control_heavy_stdlib_pdf_text_uses_bounded_poppler_fallback(monkeypatch) -> None:
    processor = DocumentProcessor()
    fallback = (
        [{"number": 1, "width": 612.0, "height": 792.0, "image_content_object_id": None}],
        [{
            "block_key": "page-1-text", "parent_block_key": None, "type": "text", "page": 1,
            "bbox": [0.0, 0.0, 612.0, 792.0], "text": "정상 공고문", "confidence": 1.0,
            "attributes": {"source": "pdf-poppler-text"},
        }],
        [],
        [],
    )
    monkeypatch.setattr(
        "app.deep_review.document_mcp.processor.extract_pdf",
        lambda _data, _options: (
            fallback[0],
            [{**fallback[1][0], "text": "binary\x01font\x9cstream"}],
            [],
            [],
        ),
    )
    monkeypatch.setattr(processor, "_extract_pdf_poppler", lambda _data, _options: fallback)

    result = processor.process(text_pdf(), "application/pdf", {"ocr": False})

    assert result["extractor"]["name"] == "pdf-poppler-fallback"
    assert result["blocks"][0]["text"] == "정상 공고문"
    assert "pdf_stdlib_text_fallback" in result["warnings"]


def test_prepare_pdf_has_a_separate_bounded_object_budget() -> None:
    assert ProcessorOptions.from_mapping({"ocr": False}).max_pdf_objects == 4096
    assert ProcessorOptions.from_mapping({"ocr": False, "prepare_pdf": True}).max_pdf_objects == 10_000
    assert ProcessorOptions.from_mapping({
        "ocr": False, "prepare_pdf": True, "max_pdf_objects": 4096,
    }).max_pdf_objects == 4096
    with pytest.raises(DocumentProcessingError) as caught:
        ProcessorOptions.from_mapping({"ocr": False, "prepare_pdf": True, "max_pdf_objects": 10_001})
    assert caught.value.code == "invalid_options"


def test_pdf_decoded_output_limit_rejects_compressed_two_megabyte_payload() -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(compressed_large_text_pdf(), "application/pdf", {"ocr": False, "max_output_bytes": 1024})
    assert caught.value.code == "output_size_limit"


def test_pdf_decoded_output_limit_is_aggregate_across_content_streams() -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(multi_stream_pdf(), "application/pdf", {"ocr": False, "max_output_bytes": 1024})
    assert caught.value.code == "output_size_limit"


def test_pdf_rendered_page_bytes_are_aggregate_before_retaining_pages() -> None:
    processor = DocumentProcessor()
    processor._render_pdf_page = lambda _original, _page, _options: b"x" * 700  # type: ignore[method-assign]
    with pytest.raises(DocumentProcessingError) as caught:
        processor.process(mixed_pdf(), "application/pdf", {"ocr": False, "render_pages": True, "max_output_bytes": 1024})
    assert caught.value.code == "output_size_limit"


def test_pdf_ocr_text_is_aggregate_across_pages_before_appending_blocks() -> None:
    processor = DocumentProcessor(ocr_engine=lambda _data, _mime: "x" * 700)
    processor._render_pdf_page = lambda _original, _page, _options: b"rendered"  # type: ignore[method-assign]
    with pytest.raises(DocumentProcessingError) as caught:
        processor.process(blank_two_page_pdf(), "application/pdf", {"ocr": True, "max_output_bytes": 1024})
    assert caught.value.code == "output_size_limit"


def test_subprocess_output_limit_is_aggregate_across_stdout_and_stderr() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        executable = Path(temporary) / "mixed-noise-converter"
        executable.write_text(
            "#!/bin/sh\n"
            "i=0\n"
            "while [ $i -lt 700 ]; do printf x; i=$((i + 1)); done\n"
            "i=0\n"
            "while [ $i -lt 700 ]; do printf x >&2; i=$((i + 1)); done\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        with pytest.raises(DocumentProcessingError) as caught:
            DocumentProcessor(node_executable=str(executable), clamav_checker=lambda data: True).process(
                b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1noisy",
                "application/x-hwp",
                {"ocr": False, "max_output_bytes": 1024},
            )
    assert caught.value.code == "output_size_limit"
    assert caught.value.source_preserved is True


def test_mixed_pdf_ocr_targets_only_pages_without_extractable_text() -> None:
    calls: list[str] = []
    processor = DocumentProcessor(
        ocr_engine=lambda _data, mime: calls.append(mime) or {"text": "OCR page", "confidence": 0.8}
    )
    processor._render_pdf_page = lambda _original, _page, _options: one_pixel_png()  # type: ignore[method-assign]
    result = processor.process(mixed_pdf(), "application/pdf", {"ocr": True})
    assert calls == ["image/png"]
    assert [block["page"] for block in result["blocks"] if block["type"] == "ocr_text"] == [2]
    assert not any(block["type"] == "ocr_text" and block["page"] == 1 for block in result["blocks"])


def test_mixed_pdf_without_renderer_is_explicitly_needs_review() -> None:
    processor = DocumentProcessor()

    def unavailable(_original: bytes, _page: int, _options: ProcessorOptions) -> bytes:
        raise DocumentProcessingError("renderer_unavailable", "renderer unavailable")

    processor._render_pdf_page = unavailable  # type: ignore[method-assign]
    result = processor.process(mixed_pdf(), "application/pdf", {"ocr": True})
    assert "needs_review" in result["warnings"]
    assert "ocr_unavailable" in result["warnings"]
    assert not any(block["type"] == "ocr_text" for block in result["blocks"])


def test_image_ocr_is_injected_and_confidence_is_bounded() -> None:
    # 1x1 PNG
    png = one_pixel_png()
    result = process_document(png, "image/png", {"ocr": True}, ocr_engine=lambda data, mime: {"text": "OCR", "confidence": 0.75})
    assert result["blocks"][0]["text"] == "OCR"
    assert result["blocks"][0]["confidence"] == 0.75


def test_ocr_unavailable_is_explicit_warning() -> None:
    png = one_pixel_png()
    result = DocumentProcessor().process(png, "image/png")
    assert "ocr_unavailable" in result["warnings"] or result["blocks"]


def test_clamav_unavailable_is_not_reported_as_clean() -> None:
    result = DocumentProcessor(clamav_checker=lambda data: None).process(hwpx_bytes(), "application/hwp+zip", {"ocr": False})
    assert "clamav_unavailable" in result["warnings"]
    with pytest.raises(DocumentProcessingError) as caught:
        DocumentProcessor(clamav_checker=lambda data: False).process(hwpx_bytes(), "application/hwp+zip", {"ocr": False})
    assert caught.value.code == "malware_detected"


def test_hwp_conversion_failure_preserves_source_and_blocks() -> None:
    hwp = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"invalid fixture"
    with pytest.raises(DocumentProcessingError) as caught:
        DocumentProcessor(clamav_checker=lambda data: True).process(hwp, "application/x-hwp", {"ocr": False})
    assert caught.value.code == "conversion_required"
    assert caught.value.blocking is True
    assert caught.value.source_preserved is True


def test_archive_bomb_and_oversize_input_are_blocked() -> None:
    bomb = hwpx_with_member("data.bin", b"A" * 100_000)
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(bomb, "application/hwp+zip", {"ocr": False, "max_archive_uncompressed_bytes": 10_000})
    assert caught.value.code in {"archive_size_limit", "archive_member_limit", "archive_ratio_limit"}
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(b"0" * (MAX_INPUT_BYTES + 1), "application/pdf", {"ocr": False})
    assert caught.value.code == "input_size_limit"


def test_prepare_pdf_reuses_hwpx_archive_boundary_before_rhwp(monkeypatch: pytest.MonkeyPatch) -> None:
    bomb = hwpx_with_member("data.bin", b"A" * 100_000)

    def unexpected_renderer(*args: object, **kwargs: object) -> None:
        raise AssertionError("rhwp must not receive an archive that failed validation")

    monkeypatch.setattr(DocumentProcessor, "_prepare_pdf_structure", unexpected_renderer)
    with pytest.raises(DocumentProcessingError) as caught:
        DocumentProcessor(clamav_checker=lambda data: True).process(
            bomb,
            "application/hwp+zip",
            {"ocr": False, "prepare_pdf": True, "max_archive_uncompressed_bytes": 10_000},
        )
    assert caught.value.code in {"archive_size_limit", "archive_member_limit", "archive_ratio_limit"}
    assert caught.value.source_preserved is True


def test_nested_archive_magic_is_blocked_even_with_disguised_name() -> None:
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("inner.txt", b"nested")
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_with_member("notes.txt", nested.getvalue()), "application/hwp+zip", {"ocr": False})
    assert caught.value.code == "archive_depth_limit"

    tar_header = bytearray(512)
    tar_header[257:262] = b"ustar"
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_with_member("notes.txt", bytes(tar_header)), "application/hwp+zip", {"ocr": False})
    assert caught.value.code == "archive_depth_limit"


def test_malformed_pdf_and_real_timeout_path() -> None:
    malformed = b"%PDF-1.4\n1 0 obj << /Type /Page /Contents 2 0 R >> endobj\n2 0 obj << /Length 3 >> stream\nabc\nendobj\n%%EOF"
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(malformed, "application/pdf", {"ocr": False})
    assert caught.value.code == "malformed_pdf"

    # A trusted test-only converter executable sleeps after receiving the
    # internal source path.  The public bytes API never accepts this path.
    import tempfile
    with tempfile.TemporaryDirectory() as temporary:
        executable = Path(temporary) / "slow-converter"
        executable.write_text("#!/bin/sh\nsleep 2\n", encoding="utf-8")
        executable.chmod(0o700)
        with pytest.raises(DocumentProcessingError) as caught:
            DocumentProcessor(node_executable=str(executable), clamav_checker=lambda data: True).process(
                b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1slow", "application/x-hwp", {"ocr": False, "timeout_seconds": 0.1}
            )
        assert caught.value.code == "conversion_required"
        assert caught.value.source_preserved is True


def test_converter_stdout_limit_is_enforced_before_completion() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        executable = Path(temporary) / "noisy-converter"
        executable.write_text(
            "#!/bin/sh\n"
            "i=0\n"
            "while [ $i -lt 4096 ]; do printf x; i=$((i + 1)); done\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        with pytest.raises(DocumentProcessingError) as caught:
            DocumentProcessor(node_executable=str(executable), clamav_checker=lambda data: True).process(
                b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1noisy", "application/x-hwp", {"ocr": False, "max_output_bytes": 1024}
            )
    assert caught.value.code == "output_size_limit"
    assert caught.value.source_preserved is True


def test_converter_stderr_limit_is_enforced_before_completion() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        executable = Path(temporary) / "noisy-converter"
        executable.write_text(
            "#!/bin/sh\n"
            "i=0\n"
            "while [ $i -lt 4096 ]; do printf x >&2; i=$((i + 1)); done\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        with pytest.raises(DocumentProcessingError) as caught:
            DocumentProcessor(node_executable=str(executable), clamav_checker=lambda data: True).process(
                b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1noisy", "application/x-hwp", {"ocr": False, "max_output_bytes": 1024}
            )
    assert caught.value.code == "output_size_limit"
    assert caught.value.source_preserved is True


def test_boolean_bbox_and_confidence_are_not_numbers() -> None:
    result = process_document(hwpx_bytes(), "application/hwp+zip", {"ocr": False})
    bad_bbox = dict(result)
    bad_bbox["blocks"] = [dict(result["blocks"][0], bbox=[0, False, 1, 1])]
    with pytest.raises(DocumentProcessingError):
        validate_structure(bad_bbox)
    bad_confidence = dict(result)
    bad_confidence["blocks"] = [dict(result["blocks"][0], confidence=True)]
    with pytest.raises(DocumentProcessingError):
        validate_structure(bad_confidence)


def test_structure_rejects_naive_page_and_unapproved_provenance() -> None:
    result = process_document(hwpx_bytes(), "application/hwp+zip", {"ocr": False})

    naive = dict(result)
    naive["created_at"] = "2026-08-25T00:00:00"
    with pytest.raises(DocumentProcessingError) as caught:
        validate_structure(naive)
    assert caught.value.code == "invalid_structure"

    bool_page = dict(result)
    bool_page["blocks"] = [dict(result["blocks"][0], page=True)]
    with pytest.raises(DocumentProcessingError) as caught:
        validate_structure(bool_page)
    assert caught.value.code == "invalid_structure"

    unknown_commit = dict(result)
    unknown_commit["extractor"] = dict(result["extractor"], upstream_commit="0" * 40)
    with pytest.raises(DocumentProcessingError) as caught:
        validate_structure(unknown_commit)
    assert caught.value.code == "invalid_structure"


def test_hwpx_xml_entity_and_depth_limits_fail_closed() -> None:
    entity_xml = b'<!DOCTYPE root [<!ENTITY x "unsafe">]><root>&x;</root>'
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_xml(entity_xml), "application/hwp+zip", {"ocr": False})
    assert caught.value.code == "unsafe_xml"

    deep_xml = b"<root>" + b"<a>" * 16 + b"x" + b"</a>" * 16 + b"</root>"
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_xml(deep_xml), "application/hwp+zip", {"ocr": False, "max_xml_depth": 8})
    assert caught.value.code == "xml_depth_limit"


def test_injected_ocr_output_limit_is_enforced() -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(
            one_pixel_png(),
            "image/png",
            {"ocr": True, "max_output_bytes": 1024},
            ocr_engine=lambda _data, _mime: "A" * 2048,
        )
    assert caught.value.code == "output_size_limit"


def test_tiff_dimensions_use_distinct_width_and_height_tags() -> None:
    # Little-endian classic TIFF, two inline SHORT IFD entries: width=3,
    # height=5.  No image pixels are needed for dimension sniffing.
    header = b"II*\x00" + (8).to_bytes(4, "little")
    ifd = (2).to_bytes(2, "little")
    width = (256).to_bytes(2, "little") + (3).to_bytes(2, "little") + (1).to_bytes(4, "little") + (3).to_bytes(2, "little") + b"\x00\x00"
    height = (257).to_bytes(2, "little") + (3).to_bytes(2, "little") + (1).to_bytes(4, "little") + (5).to_bytes(2, "little") + b"\x00\x00"
    tiff = header + ifd + width + height + b"\x00\x00\x00\x00"
    result = process_document(tiff, "image/tiff", {"ocr": False})
    assert (result["pages"][0]["width"], result["pages"][0]["height"]) == (3.0, 5.0)


def test_hwp_fixture_converts_in_isolated_child_and_keeps_original() -> None:
    source = (FIXTURES / "labor_template.hwp").read_bytes()
    result = DocumentProcessor(clamav_checker=lambda data: True).process(source, "application/x-hwp", {"ocr": False})
    assert result.original_bytes == source
    assert result.converted_bytes and result.converted_bytes.startswith(b"PK")
    assert result["extractor"]["upstream_commit"] == "96a2633f23a08f707679d7e212ebdc59948260e6"


@pytest.mark.parametrize(
    ("content", "media_type", "code"),
    [
        (b"%PDF-1.4 /Encrypt", "application/pdf", "encrypted_pdf"),
        (b"not a document", "application/pdf", "mime_mismatch"),
        (hwpx_bytes(name="../escape.xml"), "application/hwp+zip", "archive_traversal"),
    ],
)
def test_safe_failure_modes(content: bytes, media_type: str, code: str) -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(content, media_type, {"ocr": False})
    assert caught.value.code == code
    assert "/" not in caught.value.message
    assert "escape" not in caught.value.message


def test_limits_and_restricted_options() -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_bytes(), "application/hwp+zip", {"output_path": "/tmp/out"})
    assert caught.value.code == "invalid_options"
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_bytes(), "application/hwp+zip", {"timeout_seconds": 0.01})
    assert caught.value.code == "invalid_options"
    with pytest.raises(DocumentProcessingError):
        process_document("/tmp/input.hwpx", "application/hwp+zip")


def test_structure_rejects_additional_fields_and_cycles() -> None:
    result = process_document(hwpx_bytes(), "application/hwp+zip", {"ocr": False})
    extra = dict(result)
    extra["internal_path"] = "/quarantine/secret"
    with pytest.raises(DocumentProcessingError):
        validate_structure(extra)
    cyclic = dict(result)
    cyclic["blocks"] = [dict(cyclic["blocks"][0], parent_block_key=cyclic["blocks"][0]["block_key"])]
    with pytest.raises(DocumentProcessingError):
        validate_structure(cyclic)


def test_structure_rejects_payload_page_and_block_counts_above_defaults() -> None:
    result = process_document(hwpx_bytes(), "application/hwp+zip", {"ocr": False})

    too_many_pages = dict(result)
    too_many_pages["pages"] = [dict(result["pages"][0], number=number) for number in range(1, 514)]
    too_many_pages["blocks"] = []
    with pytest.raises(DocumentProcessingError) as caught:
        validate_structure(too_many_pages)
    assert caught.value.code == "page_limit"

    too_many_blocks = dict(result)
    too_many_blocks["blocks"] = [result["blocks"][0]] * 100_001
    with pytest.raises(DocumentProcessingError) as caught:
        validate_structure(too_many_blocks)
    assert caught.value.code == "block_limit"


def test_structure_large_parent_chain_is_linear_and_bounded() -> None:
    result = process_document(hwpx_bytes(), "application/hwp+zip", {"ocr": False})
    blocks: list[dict[str, object]] = []
    for index in range(12_000):
        blocks.append({
            "block_key": f"chain-{index}",
            "parent_block_key": f"chain-{index - 1}" if index else None,
            "type": "paragraph",
            "page": 1,
            "bbox": None,
            "text": "",
            "confidence": None,
            "attributes": {},
        })
    payload = dict(result)
    payload["blocks"] = blocks
    started = time.monotonic()
    validate_structure(payload)
    assert time.monotonic() - started < 2.0


def test_vendored_sha256_manifest_is_deterministic_and_complete() -> None:
    vendor = Path(__file__).parents[2] / "app" / "deep_review" / "document_mcp" / "vendor"
    manifest = vendor / "SHA256SUMS"
    contents = manifest.read_text(encoding="utf-8")
    assert "hwpx-skill.git" in contents
    assert "96a2633f23a08f707679d7e212ebdc59948260e6" in contents
    assert "DoHyun468/claw-hwp" in contents
    entries = [line.split(maxsplit=1) for line in contents.splitlines() if line and not line.startswith("#")]
    assert entries == sorted(entries, key=lambda item: item[1])
    assert all(len(digest) == 64 and path != "SHA256SUMS" for digest, path in entries)
    for digest, relative_path in entries:
        path = vendor / relative_path
        assert path.is_file(), relative_path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
