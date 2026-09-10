"""Shared validation of native artifacts at scratch and persistence boundaries."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from .contracts import validate_para_page_map, validate_structure
from .errors import DocumentProcessingError
from .safety import ProcessorOptions, validate_zip

NATIVE_RENDERER = "rhwp-svg-pdf"
NATIVE_SNAPSHOT_SCHEMA = "bidops.rhwp-pdf-snapshot.v1"
NATIVE_TEXT_SCHEMA = "bidops.rhwp-page-text.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _fail(code: str) -> None:
    raise DocumentProcessingError(code, "rhwp 산출물 결속을 확인할 수 없습니다", source_preserved=True)


def validate_native_renderer(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "renderer", "rhwp_version", "rhwp_binary_sha256", "backend", "compat", "fallback_fonts", "worker_image_digest",
    }:
        _fail("renderer_binding_invalid")
    if (
        value["renderer"] != NATIVE_RENDERER or value["rhwp_version"] != "0.8.6"
        or value["backend"] != "svg" or value["compat"] != "2022"
        or value["fallback_fonts"] != {"serif": "NanumMyeongjo", "sans": "NanumGothic", "mono": "NanumGothicCoding"}
        or not isinstance(value["rhwp_binary_sha256"], str) or not _SHA256.fullmatch(value["rhwp_binary_sha256"])
        or (value["worker_image_digest"] is not None and (not isinstance(value["worker_image_digest"], str) or not _SHA256.fullmatch(value["worker_image_digest"])))
    ):
        _fail("renderer_binding_invalid")
    return dict(value)


def validate_native_page_text(value: Any, metadata: Mapping[str, Any], *, max_pages: int = 512) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"schema", "page_count", "pages"} or value["schema"] != NATIVE_TEXT_SCHEMA:
        _fail("rhwp_manifest_invalid")
    count = value["page_count"]
    if type(count) is not int or not 1 <= count <= max_pages:
        _fail("pdf_page_mismatch")
    if not isinstance(metadata, Mapping) or set(metadata) != {"schema", "renderer", "renderer_version", "page_count", "renderer_provenance", "font_provenance", "pages"}:
        _fail("rhwp_manifest_invalid")
    if metadata.get("schema") != NATIVE_SNAPSHOT_SCHEMA or metadata.get("renderer") != NATIVE_RENDERER or metadata.get("renderer_version") != "1":
        _fail("rhwp_manifest_invalid")
    if metadata.get("page_count") != count or type(metadata.get("page_count")) is not int:
        _fail("pdf_page_mismatch")
    font = metadata.get("font_provenance")
    if not isinstance(font, Mapping) or set(font) != {"font_manifest_sha256"} or not isinstance(font["font_manifest_sha256"], str) or not _SHA256.fullmatch(font["font_manifest_sha256"]):
        _fail("font_binding_invalid")
    pages, expected = value["pages"], metadata.get("pages")
    if not isinstance(pages, list) or not isinstance(expected, list) or len(pages) != count or len(expected) != count:
        _fail("pdf_page_mismatch")
    for number, (page, ref) in enumerate(zip(pages, expected), 1):
        if not isinstance(page, Mapping) or set(page) != {"number", "display_page", "section", "text", "text_sha256"}:
            _fail("rhwp_manifest_invalid")
        if type(page["number"]) is not int or page["number"] != number or not isinstance(page["text"], str):
            _fail("rhwp_manifest_invalid")
        if type(page["section"]) is not int or page["section"] < 0 or (page["display_page"] is not None and (type(page["display_page"]) is not int or page["display_page"] < 0)):
            _fail("rhwp_manifest_invalid")
        try:
            digest = hashlib.sha256(page["text"].encode("utf-8")).hexdigest()
        except UnicodeError:
            _fail("rhwp_manifest_invalid")
        if not isinstance(ref, Mapping) or type(ref.get("number")) is not int or type(ref.get("section")) is not int:
            _fail("rhwp_manifest_invalid")
        if page["text_sha256"] != digest or ref != {key: page[key] for key in ("number", "display_page", "section", "text_sha256")}:
            _fail("rhwp_manifest_invalid")
    if not any(page["text"].strip() for page in pages):
        _fail("pdf_empty_text")
    return dict(value)


def validate_native_bundle(
    structure: Mapping[str, Any], *, source_bytes: bytes, hwpx_bytes: bytes,
    hwpx_verify: Any, page_text: Mapping[str, Any], para_page_map: Mapping[str, Any],
    pdf_metadata: Mapping[str, Any], options: ProcessorOptions,
) -> None:
    validate_structure(structure, max_output_bytes=options.max_output_bytes, max_pages=options.max_pages, max_blocks=options.max_blocks)
    if structure["source_sha256"] != hashlib.sha256(source_bytes).hexdigest():
        _fail("hash_mismatch")
    if structure["media_type"] not in {"application/hwp+zip", "application/x-hwp"}:
        _fail("mime_mismatch")
    if not isinstance(hwpx_bytes, bytes) or not hwpx_bytes or len(hwpx_bytes) > options.max_output_bytes:
        _fail("output_size_limit")
    archive = validate_zip(hwpx_bytes, options)
    archive.close()
    if structure["media_type"] == "application/hwp+zip":
        if hwpx_bytes != source_bytes or hwpx_verify is not None:
            _fail("hash_mismatch")
    else:
        if not isinstance(hwpx_verify, Mapping) or set(hwpx_verify) != {"identical", "diff_count", "pages"}:
            _fail("hwpx_verify_failed")
        pages = hwpx_verify["pages"]
        if hwpx_verify["identical"] is not True or type(hwpx_verify["diff_count"]) is not int or hwpx_verify["diff_count"] != 0 or not isinstance(pages, Mapping) or set(pages) != {"before", "after", "identical"}:
            _fail("hwpx_verify_failed")
        if pages["identical"] is not True or type(pages["before"]) is not int or type(pages["after"]) is not int or not 1 <= pages["before"] == pages["after"] == pdf_metadata.get("page_count"):
            _fail("hwpx_verify_failed")
    validate_native_renderer(pdf_metadata.get("renderer_provenance"))
    validate_native_page_text(page_text, pdf_metadata, max_pages=min(options.max_pages, options.max_pdf_pages))
    validate_para_page_map(para_page_map, block_keys={block["block_key"] for block in structure["blocks"]}, max_pages=options.max_pages, max_blocks=options.max_blocks)
    if para_page_map["page_count"] != page_text["page_count"]:
        _fail("pdf_page_mismatch")
