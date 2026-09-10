"""Small, append-only preparation boundary for the v4 overview input.

This module only freezes verified document/object references and a bounded page
selection.  It does not run a model, enqueue a scheduler job, mutate the
legacy overview tables, or read credentials.  The later runner can consume the
prepared input manifest without being granted source-object access.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.object_store import ObjectStore, ObjectStoreError
from ...lifecycle.models import NoticeObservation
from ..document_mcp.safety import ProcessorOptions
from ..document_mcp.errors import DocumentProcessingError
from ..document_mcp.native_artifacts import (
    NATIVE_RENDERER, NATIVE_SNAPSHOT_SCHEMA, validate_native_renderer,
    validate_native_page_text, validate_native_bundle, validate_section_candidates,
)
from .document_structures import persist_structure_rows
from .document_converter import SAFE_CONVERTER_CODES, ScratchDocumentProcessor
from ..models import (
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentVersion,
    DocumentStructure,
    PrespecV4PdfSnapshot,
    PrespecV4Target,
)
from .prespec_overview import _filename_document_candidate


V4_MANIFEST_SCHEMA = "bidops.prespec-v4-input-manifest.v1"
V4_SNAPSHOT_METADATA_SCHEMAS = frozenset({"bidops.hwp-pdf-snapshot.v1", "bidops.pdf-snapshot.v1", NATIVE_SNAPSHOT_SCHEMA})
MAX_V4_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_V4_PROVENANCE_BYTES = 128 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHAPTER = re.compile(r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+)\s*[.)、:：\-–—]?\s*(.+)$")
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\s*[.)、:：\-–—]?\s+(.+)$")
_BULLET = re.compile(r"^[□■◆◇○●〇◦•·]\s*")
_TARGET_WORDS = frozenset(
    {
        "개요", "목적", "배경", "범위", "주요내용", "주요과업", "사업일반",
        "사업개요", "감리개요", "감리목적", "감리대상사업", "감리방법",
        "감리과업내용", "과업개요", "과업안내", "과업내용", "추진근거", "추진계획",
    }
)


class V4PreparationError(ValueError):
    """Stable failure at the v4 preparation/storage boundary."""

    def __init__(self, code: str, message: str = "v4 입력을 준비할 수 없습니다") -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class DocumentCandidateSelection:
    document: DocumentVersion | None
    reason_code: str | None


@dataclass(frozen=True)
class V4RangeSelection:
    status: str
    reason_code: str | None
    strategy: str | None
    start_locator: dict[str, Any] | None
    end_locator: dict[str, Any] | None
    page_numbers: tuple[int, ...]
    page_text_hashes: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]
    manifest_bytes: bytes
    input_sha256: str


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise V4PreparationError("invalid_json") from error


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical(value))


def _bounded_object(value: Any, *, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise V4PreparationError(code)
    try:
        encoded = _canonical(dict(value))
    except V4PreparationError:
        raise V4PreparationError(code) from None
    if len(encoded) > MAX_V4_PROVENANCE_BYTES:
        raise V4PreparationError("provenance_size_limit")
    return json.loads(encoded.decode("utf-8"))


def _worker_binding(value: Mapping[str, Any], *, code: str, asset_key: str) -> dict[str, Any]:
    """Validate worker asset identity and an optional declared image digest.

    An image digest is only meaningful when the worker image declaration is
    supplied by deployment.  A digest derived from renderer assets is not an
    image digest, so an undeclared value is represented as ``None`` and the
    actual renderer/font fingerprints remain the binding evidence.
    """

    safe = _bounded_object(value, code=code)
    image_digest = safe.get("worker_image_digest")
    asset_digest = safe.get(asset_key)
    if image_digest is not None and (not isinstance(image_digest, str) or not _SHA256.fullmatch(image_digest)):
        raise V4PreparationError(code)
    if not isinstance(asset_digest, str) or not _SHA256.fullmatch(asset_digest):
        raise V4PreparationError(code)
    return safe


def _worker_identity(value: Mapping[str, Any], *, asset_key: str) -> dict[str, Any]:
    """Return only the stable worker binding fields used for cache identity."""

    return {
        "worker_image_digest": value.get("worker_image_digest"),
        asset_key: str(value[asset_key]),
    }


def _native_renderer(value: Any) -> dict[str, Any]:
    try:
        return validate_native_renderer(value)
    except DocumentProcessingError as error:
        raise V4PreparationError(error.code) from error


def _assert_native_provenance(metadata, renderer, font):
    actual = _native_renderer(metadata.get("renderer_provenance"))
    actual_font = _worker_binding(metadata.get("font_provenance"), code="font_binding_invalid", asset_key="font_manifest_sha256")
    if actual != renderer:
        raise V4PreparationError("renderer_binding_invalid")
    if _worker_identity(actual_font, asset_key="font_manifest_sha256") != _worker_identity(font, asset_key="font_manifest_sha256"):
        raise V4PreparationError("font_binding_invalid")
    return actual, actual_font


def _source_pdf_binding(value: Mapping[str, Any], *, code: str, font: bool = False) -> dict[str, Any]:
    """Validate the non-rendering binding used by an original PDF."""

    safe = _bounded_object(value, code=code)
    if safe.get("source_pdf") is not True:
        raise V4PreparationError(code)
    if font:
        if safe.get("font_provenance") is not None:
            raise V4PreparationError(code)
        return safe
    provenance = safe.get("processor_provenance")
    if not isinstance(provenance, Mapping):
        raise V4PreparationError(code)
    if provenance.get("schema") != "bidops.pdf-text-provenance.v1":
        raise V4PreparationError(code)
    processor_sha256 = provenance.get("processor_sha256")
    if not isinstance(processor_sha256, str) or not _SHA256.fullmatch(processor_sha256):
        raise V4PreparationError(code)
    extractor = provenance.get("text_extractor")
    if not isinstance(extractor, Mapping) or not isinstance(extractor.get("name"), str) or not isinstance(extractor.get("version"), str):
        raise V4PreparationError(code)
    poppler = provenance.get("poppler_binary_sha256")
    if extractor.get("name") == "pdf-poppler-prepared":
        if not isinstance(poppler, Mapping) or set(poppler) != {"pdfinfo", "pdftotext"}:
            raise V4PreparationError(code)
        if any(not isinstance(item, str) or not _SHA256.fullmatch(item) for item in poppler.values()):
            raise V4PreparationError(code)
    elif poppler is not None:
        raise V4PreparationError(code)
    return safe


def _assert_source_pdf_provenance(
    metadata: Mapping[str, Any],
    expected_renderer: Mapping[str, Any],
    expected_font: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind source-PDF parser evidence without inventing renderer/font data."""

    if (
        metadata.get("schema") != "bidops.pdf-snapshot.v1"
        or metadata.get("renderer") != "source-pdf"
        or metadata.get("rerendered") is not False
        or metadata.get("font_provenance") is not None
    ):
        raise V4PreparationError("renderer_binding_invalid")
    actual = metadata.get("processor_provenance")
    expected = expected_renderer.get("processor_provenance")
    if not isinstance(actual, Mapping) or actual != expected:
        raise V4PreparationError("renderer_binding_invalid")
    if expected_font.get("font_provenance") is not None:
        raise V4PreparationError("font_binding_invalid")
    return dict(expected_renderer), dict(expected_font)


def choose_rfp_document(documents: Iterable[DocumentVersion]) -> DocumentCandidateSelection:
    """Reuse the established filename-only RFP selection rule.

    Currentness/safety belong to the DB preparation caller.  This pure helper
    intentionally never chooses by role, upload time, extension, or UUID.
    """

    candidates = [item for item in documents if _filename_document_candidate(item.original_filename)]
    if len(candidates) == 1:
        return DocumentCandidateSelection(candidates[0], None)
    if len(candidates) > 1:
        return DocumentCandidateSelection(None, "ambiguous_rfp_filename")
    return DocumentCandidateSelection(None, "rfp_filename_missing")


@dataclass(frozen=True)
class _Line:
    page: int
    block_key: str
    line_index: int
    char_start: int
    char_end: int
    text: str
    level: int | None
    heading_title: str | None
    chapter: bool


def _normalise_heading(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    text = re.sub(r"\s+", "", text).casefold()
    text = _BULLET.sub("", text)
    text = re.sub(r"^[\(\[\{<「『【〔〈《]+", "", text)
    text = re.sub(r"[\)\]\}>」』】〕〉》]+$", "", text)
    return text.strip(" .·…\t")


def _heading_from_line(text: str) -> tuple[int | None, str | None, bool]:
    # NFKC turns the Unicode Roman numerals used by the source (Ⅰ/Ⅱ/…) into
    # ASCII I/II.  Match the chapter marker before normalising; otherwise the
    # parent chapter disappears from every locator and range boundary.
    stripped = text.strip()
    chapter = _CHAPTER.match(stripped)
    if chapter:
        title = chapter.group(2).strip()
        return 1, title, bool(_normalise_heading(title))
    numbered = _NUMBERED.match(stripped)
    if numbered:
        title = numbered.group(2).strip()
        return 2, title, False
    return None, None, False


def _structure_pages(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise V4PreparationError("invalid_structure")
    raw_pages = payload.get("pages")
    raw_blocks = payload.get("blocks")
    if not isinstance(raw_pages, list) or not raw_pages or not isinstance(raw_blocks, list):
        raise V4PreparationError("invalid_structure")
    blocks_by_page: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for raw in raw_blocks:
        if not isinstance(raw, Mapping):
            raise V4PreparationError("invalid_structure")
        page = raw.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise V4PreparationError("invalid_structure")
        blocks_by_page[page].append(raw)
    pages: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw_page in raw_pages:
        if not isinstance(raw_page, Mapping):
            raise V4PreparationError("invalid_structure")
        number = raw_page.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1 or number in seen:
            raise V4PreparationError("invalid_structure")
        seen.add(number)
        text = raw_page.get("text")
        if not isinstance(text, str):
            chunks: list[str] = []
            for block in blocks_by_page.get(number, []):
                value = block.get("text")
                if isinstance(value, str):
                    chunks.append(value)
            text = "\n".join(chunks)
        if not isinstance(text, str):
            raise V4PreparationError("invalid_structure")
        blocks = blocks_by_page.get(number, [])
        block_keys = [str(block.get("block_key")) for block in blocks if isinstance(block.get("block_key"), str) and str(block.get("block_key")).strip()]
        pages.append({"number": number, "text": text, "block_keys": block_keys})
    pages.sort(key=lambda item: item["number"])
    if [item["number"] for item in pages] != list(range(1, len(pages) + 1)):
        raise V4PreparationError("invalid_structure")
    return pages


def _lines(pages: Sequence[Mapping[str, Any]]) -> list[_Line]:
    output: list[_Line] = []
    for page in pages:
        page_number = int(page["number"])
        page_text = str(page["text"])
        block_key = (page.get("block_keys") or [f"page-{page_number}-text"])[0]
        offset = 0
        for line_index, text in enumerate(page_text.splitlines() or [page_text]):
            char_start = offset
            char_end = char_start + len(text)
            level, title, chapter = _heading_from_line(text)
            output.append(_Line(page_number, block_key, line_index, char_start, char_end, text, level, title, chapter))
            offset = char_end + 1
    return output


def _is_target_heading(line: _Line) -> bool:
    if line.heading_title is None:
        return False
    normalized = _normalise_heading(line.heading_title)
    return any(word in normalized for word in _TARGET_WORDS)


def _locator(line: _Line, ordinal: int) -> dict[str, Any]:
    return {
        "block_key": line.block_key,
        "page": line.page,
        "line": line.line_index,
        "char_start": line.char_start,
        "char_end": line.char_end,
        "ordinal": ordinal,
    }


def select_v4_input_range(payload: Mapping[str, Any]) -> V4RangeSelection:
    """Select a contiguous, source-bound overview/purpose/scope range.

    The selector recognizes only explicit chapter/numbered heading forms.  It
    drops pages marked as a table of contents, keeps the nearest chapter parent
    and stops at the next heading of the selected section's level.  If a start
    or end cannot be established it emits a human-review manifest rather than
    selecting the whole document or cutting by a fixed page count.
    """

    pages = _structure_pages(payload)
    lines = _lines(pages)
    if len(_canonical(payload)) > MAX_V4_MANIFEST_BYTES:
        raise V4PreparationError("input_size_limit")
    toc_pages = {
        line.page
        for line in lines
        if _normalise_heading(line.text) in {"목차", "차례", "contents", "tableofcontents"}
    }
    body = [line for line in lines if line.page not in toc_pages]
    chapters = [line for line in body if line.chapter]

    reason: str | None = None
    start: _Line | None = None
    last: _Line | None = None
    end: _Line | None = None
    line_positions = {id(line): ordinal for ordinal, line in enumerate(lines)}
    selected_chapter: _Line | None = None
    selected_chapter_index: int | None = None
    chapter_anchors: list[_Line] = []
    for chapter_index, chapter in enumerate(chapters):
        chapter_start = line_positions[id(chapter)]
        chapter_end = line_positions[id(chapters[chapter_index + 1])] if chapter_index + 1 < len(chapters) else len(lines)
        candidates = [
            line for line in body[0:]
            if chapter_start < line_positions[id(line)] < chapter_end and _is_target_heading(line)
        ]
        if candidates:
            selected_chapter = chapter
            selected_chapter_index = chapter_index
            chapter_anchors = candidates
            break
    if not chapters:
        reason = "scope_heading_missing"
    elif selected_chapter is None:
        reason = "scope_heading_missing"
    else:
        start = selected_chapter
        last = chapter_anchors[-1]
        assert selected_chapter_index is not None
        next_chapter_index = selected_chapter_index + 1
        if next_chapter_index >= len(chapters):
            reason = "scope_end_missing"
        else:
            next_chapter = chapters[next_chapter_index]
            end = next_chapter
            # A document whose first chapter is an overview/guide sometimes
            # puts the first concrete work section under the following
            # ``과업 내용`` chapter.  Carry only that first numbered section
            # across the chapter boundary; a generic next chapter (for
            # example ``제안요청 사항`` or ``과업수행 지침``) remains the
            # exclusive boundary.
            next_title = _normalise_heading(next_chapter.heading_title or "")
            if "과업내용" in next_title:
                following_chapter_ordinal = (
                    line_positions[id(chapters[next_chapter_index + 1])]
                    if next_chapter_index + 1 < len(chapters)
                    else len(lines)
                )
                next_start = line_positions[id(next_chapter)]
                next_anchors = [
                    line for line in body
                    if next_start < line_positions[id(line)] < following_chapter_ordinal
                    and _is_target_heading(line)
                    and line.level == 2
                ]
                if next_anchors:
                    next_section = next_anchors[0]
                    next_section_ordinal = line_positions[id(next_section)]
                    end = next_chapter
                    for candidate in body:
                        ordinal = line_positions[id(candidate)]
                        if ordinal <= next_section_ordinal or ordinal >= following_chapter_ordinal:
                            continue
                        if candidate.level == 2:
                            end = candidate
                            break
        if end is None:
            reason = "scope_end_missing"
        elif end.page < last.page or (end.page == last.page and end.line_index <= last.line_index):
            reason = "ambiguous_scope_boundary"

    if reason is not None or start is None or last is None or end is None:
        manifest = {
            "schema_version": V4_MANIFEST_SCHEMA,
            "document_version_id": str(payload.get("document_version_id")) if payload.get("document_version_id") is not None else None,
            "source_sha256": payload.get("source_sha256"),
            "selection_status": "needs_human_review",
            "reason_code": reason or "ambiguous_scope",
            "strategy": "heading_scope",
            "input_limitations": ["page_text_only", "table_layout_not_inferred"],
        }
        raw = _canonical(manifest)
        return V4RangeSelection(
            "needs_human_review", manifest["reason_code"], "heading_scope", None, None,
            (), (), manifest, raw, _sha256_bytes(raw),
        )

    start_ordinal = line_positions[id(start)]
    end_ordinal = line_positions[id(end)]
    selected = lines[start_ordinal:end_ordinal]
    if not selected:
        raise V4PreparationError("ambiguous_scope")
    selected_pages = sorted({line.page for line in selected})
    page_by_number = {int(page["number"]): page for page in pages}
    selected_by_page: dict[int, list[_Line]] = defaultdict(list)
    for line in selected:
        selected_by_page[line.page].append(line)
    page_hashes_list: list[dict[str, Any]] = []
    selected_pages_payload: list[dict[str, Any]] = []
    for number in selected_pages:
        full_text = str(page_by_number[number]["text"])
        page_lines = selected_by_page[number]
        first_start = page_lines[0].char_start
        last_end = page_lines[-1].char_end
        selected_text = full_text[first_start:last_end]
        full_hash = _sha256_bytes(full_text.encode("utf-8"))
        selected_hash = _sha256_bytes(selected_text.encode("utf-8"))
        page_hashes_list.append({
            "number": number,
            "text_sha256": selected_hash,
            "source_page_text_sha256": full_hash,
        })
        selected_pages_payload.append({
            "number": number,
            "text": selected_text,
            "text_sha256": selected_hash,
            "source_page_text_sha256": full_hash,
        })
    page_hashes = tuple(page_hashes_list)
    block_keys = sorted({line.block_key for line in selected})
    limitations = ["page_text_only", "table_layout_not_inferred"]
    selected_text = [item["text"] for item in selected_pages_payload]
    input_payload = {
        "schema_version": V4_MANIFEST_SCHEMA,
        "document_version_id": str(payload.get("document_version_id")) if payload.get("document_version_id") is not None else None,
        "source_sha256": payload.get("source_sha256"),
        "pages": selected_pages_payload,
        "block_keys": block_keys,
        "start_locator": _locator(start, start_ordinal),
        "end_locator": _locator(end, end_ordinal),
        "input_limitations": limitations,
    }
    input_raw = _canonical(input_payload)
    manifest = {
        **input_payload,
        "selection_status": "ready",
        "strategy": "heading_scope",
        "selected_text_sha256": _sha256_bytes("\n".join(selected_text).encode("utf-8")),
    }
    raw = _canonical(manifest)
    if len(raw) > MAX_V4_MANIFEST_BYTES:
        raise V4PreparationError("input_size_limit")
    return V4RangeSelection(
        "ready", None, "heading_scope", _locator(start, start_ordinal), _locator(end, end_ordinal),
        tuple(selected_pages), page_hashes, manifest, raw, _sha256_bytes(input_raw),
    )


def _latest_clean_scan(session: Session, content_object_id: UUID) -> ContentScan | None:
    latest = session.scalar(
        select(ContentScan)
        .where(ContentScan.content_object_id == content_object_id)
        .order_by(ContentScan.scanned_at.desc(), ContentScan.id.desc())
        .limit(1)
    )
    # Do not search backwards for an older clean result.  A newer infected or
    # unavailable scan must invalidate reuse until a new exact clean scan is
    # recorded.
    return latest if latest is not None and latest.status == "clean" else None


def _verified_location(session: Session, location_id: UUID, content_object_id: UUID, *, allow_structure: bool = True) -> ContentObjectLocation:
    location = session.get(ContentObjectLocation, location_id)
    if location is None or location.content_object_id != content_object_id or location.status != "verified" or location.purged_at is not None:
        raise V4PreparationError("object_location_unverified")
    if not location.object_version_id:
        raise V4PreparationError("object_version_missing")
    if not location.etag:
        raise V4PreparationError("object_etag_missing")
    if location.namespace_key != "source" and not (allow_structure and location.namespace_key == "structure"):
        raise V4PreparationError("object_namespace_invalid")
    return location


def _validate_pdf_metadata(metadata: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    safe = _bounded_object(metadata, code="pdf_metadata_invalid")
    if safe.get("schema") not in V4_SNAPSHOT_METADATA_SCHEMAS:
        raise V4PreparationError("pdf_metadata_invalid")
    page_count = safe.get("page_count")
    pages = safe.get("pages")
    if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 1 or not isinstance(pages, list) or len(pages) != page_count:
        raise V4PreparationError("pdf_metadata_invalid")
    for expected, page in enumerate(pages, 1):
        if not isinstance(page, Mapping) or page.get("number") != expected:
            raise V4PreparationError("pdf_metadata_invalid")
        for key in (() if safe["schema"] == NATIVE_SNAPSHOT_SCHEMA else ("width", "height")):
            value = page.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
                raise V4PreparationError("pdf_metadata_invalid")
        if not isinstance(page.get("text_sha256"), str) or not _SHA256.fullmatch(page["text_sha256"]):
            raise V4PreparationError("pdf_metadata_invalid")
    return safe, page_count


def _check_artifact_bytes(data: bytes | None, obj: ContentObject, expected_mime: str | None = None) -> None:
    if data is None:
        return
    if not isinstance(data, bytes) or len(data) != obj.size_bytes or _sha256_bytes(data) != obj.sha256:
        raise V4PreparationError("artifact_hash_mismatch")
    if expected_mime == "application/pdf" and not data.startswith(b"%PDF-"):
        raise V4PreparationError("pdf_magic_mismatch")


def _read_verified_artifact(
    store: ObjectStore,
    location: ContentObjectLocation,
    content: ContentObject,
    *,
    max_bytes: int,
    expected_mime: str | None = None,
) -> bytes:
    """Read a cached object at its exact version and verify its stored identity."""

    if not location.object_version_id:
        raise V4PreparationError("object_version_missing")
    try:
        data, metadata = store.get(
            location.namespace_key,
            location.object_key,
            max_bytes=min(max_bytes, content.size_bytes),
            version_id=location.object_version_id,
        )
    except (ObjectStoreError, OSError, ValueError) as error:
        raise V4PreparationError("snapshot_artifact_unavailable") from error
    if (
        metadata.namespace != location.namespace_key
        or metadata.object_key != location.object_key
        or metadata.object_version_id != location.object_version_id
        or (location.etag is not None and metadata.etag != location.etag)
        or metadata.size_bytes != content.size_bytes
    ):
        raise V4PreparationError("snapshot_artifact_identity_mismatch")
    _check_artifact_bytes(data, content, expected_mime)
    return data


def _validate_cached_snapshot_artifacts(
    session: Session,
    store: ObjectStore,
    snapshot: PrespecV4PdfSnapshot,
    source: ContentObject,
    source_location: ContentObjectLocation,
    *,
    source_bytes: bytes,
    max_pdf_bytes: int,
) -> None:
    """Fail closed when a reusable row points at changed storage or scans."""

    cached_source = _read_verified_artifact(
        store,
        source_location,
        source,
        max_bytes=max(source.size_bytes, len(source_bytes)),
    )
    if cached_source != source_bytes:
        raise V4PreparationError("source_hash_mismatch")
    pdf = session.get(ContentObject, snapshot.pdf_content_object_id)
    pdf_location = session.get(ContentObjectLocation, snapshot.pdf_location_id)
    page_text = session.get(ContentObject, snapshot.page_text_content_object_id)
    page_text_location = session.get(ContentObjectLocation, snapshot.page_text_location_id)
    if pdf is None or pdf_location is None or page_text is None or page_text_location is None:
        raise V4PreparationError("snapshot_artifact_unavailable")
    _verified_location(session, pdf_location.id, pdf.id)
    _verified_location(session, page_text_location.id, page_text.id)
    cached_pdf = _read_verified_artifact(
        store,
        pdf_location,
        pdf,
        max_bytes=max_pdf_bytes,
        expected_mime="application/pdf",
    )
    if _sha256_bytes(cached_pdf) != snapshot.pdf_sha256 or len(cached_pdf) != snapshot.pdf_size_bytes:
        raise V4PreparationError("snapshot_artifact_hash_mismatch")
    cached_page_text = _read_verified_artifact(
        store,
        page_text_location,
        page_text,
        max_bytes=MAX_V4_MANIFEST_BYTES,
        expected_mime="application/json",
    )
    if _sha256_bytes(cached_page_text) != snapshot.page_text_sha256 or len(cached_page_text) != snapshot.page_text_size_bytes:
        raise V4PreparationError("snapshot_artifact_hash_mismatch")
    _validate_page_text_artifact(cached_page_text, page_text, snapshot.pdf_metadata_jsonb)
    if snapshot.pdf_metadata_jsonb.get("schema") == NATIVE_SNAPSHOT_SCHEMA:
        document = session.get(DocumentVersion, snapshot.document_version_id)
        refs = {field: getattr(snapshot, field) for field in _NATIVE_REFERENCE_FIELDS}
        native_binding = _validate_native_references(
            session, store, refs, document, source_bytes, cached_page_text,
            snapshot.pdf_metadata_jsonb, ProcessorOptions.from_mapping(snapshot.config_jsonb.get("options")),
        )
        binding = {"source_sha256": source.sha256, "pdf_sha256": pdf.sha256,
            "page_text_sha256": page_text.sha256, "source_kind": snapshot.source_kind,
            "pdf_metadata": snapshot.pdf_metadata_jsonb, "renderer": snapshot.renderer_jsonb,
            "font": snapshot.font_jsonb, "config": snapshot.config_jsonb, "scan": snapshot.scan_jsonb,
            "native": native_binding}
        if _sha256_json(binding) != snapshot.binding_sha256:
            raise V4PreparationError("snapshot_identity_conflict")
    if _latest_clean_scan(session, source.id) is None or _latest_clean_scan(session, pdf.id) is None:
        raise V4PreparationError("scanner_unavailable")


def _validate_page_text_artifact(
    data: bytes | None,
    obj: ContentObject,
    metadata: Mapping[str, Any],
) -> tuple[str, int]:
    """Validate the versioned full-page text object against PDF metadata."""

    if data is None or obj.detected_mime != "application/json":
        raise V4PreparationError("page_text_reference_invalid")
    _check_artifact_bytes(data, obj)
    if len(data) > MAX_V4_MANIFEST_BYTES:
        raise V4PreparationError("page_text_size_limit")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise V4PreparationError("page_text_invalid") from error
    if metadata.get("schema") == NATIVE_SNAPSHOT_SCHEMA:
        try:
            validate_native_page_text(payload, metadata)
        except DocumentProcessingError as error:
            raise V4PreparationError(error.code) from error
        return _sha256_bytes(data), len(data)
    if not isinstance(payload, Mapping) or payload.get("schema") != "bidops.prespec-v4-page-text.v1":
        raise V4PreparationError("page_text_invalid")
    pages = payload.get("pages")
    expected_pages = metadata.get("pages")
    if not isinstance(pages, list) or not isinstance(expected_pages, list) or len(pages) != len(expected_pages):
        raise V4PreparationError("page_text_invalid")
    for expected, page in zip(expected_pages, pages, strict=True):
        if not isinstance(expected, Mapping) or not isinstance(page, Mapping):
            raise V4PreparationError("page_text_invalid")
        text = page.get("text")
        if page.get("number") != expected.get("number") or not isinstance(text, str):
            raise V4PreparationError("page_text_invalid")
        if page.get("text_sha256") != _sha256_bytes(text.encode("utf-8")):
            raise V4PreparationError("page_text_invalid")
        if page.get("text_sha256") != expected.get("text_sha256"):
            raise V4PreparationError("page_text_binding_mismatch")
    return _sha256_bytes(data), len(data)


def _page_text_payload(processed: Mapping[str, Any]) -> bytes:
    """Build the canonical full-page text artifact from trusted worker output."""

    pages = processed.get("pages")
    blocks = processed.get("blocks")
    if not isinstance(pages, list) or not isinstance(blocks, list) or not pages:
        raise V4PreparationError("page_text_invalid")
    text_by_page: dict[int, list[str]] = defaultdict(list)
    for block in blocks:
        if not isinstance(block, Mapping):
            raise V4PreparationError("page_text_invalid")
        page = block.get("page")
        text = block.get("text")
        if isinstance(page, bool) or not isinstance(page, int) or not isinstance(text, str):
            raise V4PreparationError("page_text_invalid")
        text_by_page[page].append(text)
    output_pages: list[dict[str, Any]] = []
    for expected, page in enumerate(pages, 1):
        if not isinstance(page, Mapping) or page.get("number") != expected:
            raise V4PreparationError("page_text_invalid")
        text = "\n".join(text_by_page.get(expected, []))
        output_pages.append({
            "number": expected,
            "text": text,
            "text_sha256": _sha256_bytes(text.encode("utf-8")),
        })
    raw = _canonical({"schema": "bidops.prespec-v4-page-text.v1", "pages": output_pages})
    if len(raw) > MAX_V4_MANIFEST_BYTES:
        raise V4PreparationError("page_text_size_limit")
    return raw


def _persist_artifact(
    session: Session,
    store: ObjectStore,
    *,
    namespace: str,
    object_key: str,
    data: bytes,
    detected_mime: str,
    retention_class: str,
) -> tuple[ContentObject, ContentObjectLocation]:
    metadata = store.put(namespace, object_key, data, content_type=detected_mime)
    if metadata.object_version_id is None or metadata.size_bytes != len(data):
        raise V4PreparationError("object_version_missing")
    digest = _sha256_bytes(data)
    content = session.scalar(select(ContentObject).where(ContentObject.sha256 == digest))
    if content is None:
        content = ContentObject(
            sha256=digest,
            size_bytes=len(data),
            detected_mime=detected_mime,
            retention_class=retention_class,
        )
        session.add(content)
        session.flush()
    elif content.size_bytes != len(data) or content.detected_mime != detected_mime:
        raise V4PreparationError("object_identity_conflict")
    location = ContentObjectLocation(
        content_object_id=content.id,
        namespace_key=namespace,
        object_key=metadata.object_key,
        object_version_id=metadata.object_version_id,
        etag=metadata.etag,
        status="verified",
        verified_at=datetime.now(UTC),
    )
    session.add(location)
    session.flush()
    return content, location


_NATIVE_REFERENCE_FIELDS = (
    "hwpx_content_object_id", "hwpx_location_id", "hwpx_verify_jsonb",
    "structure_id", "structure_location_id", "para_page_map_content_object_id",
    "para_page_map_location_id", "para_page_map_sha256",
    "section_candidates_content_object_id", "section_candidates_location_id",
    "section_candidates_sha256", "rhwp_binary_sha256", "rhwp_version",
)
_SECTION_CANDIDATE_FIELDS = (
    "section_candidates_content_object_id", "section_candidates_location_id", "section_candidates_sha256",
)


def _native_object(session, store, content_id, location_id, *, max_bytes, mime, namespace="structure"):
    content = session.get(ContentObject, content_id) if content_id is not None else None
    if content is None or content.detected_mime != mime:
        raise V4PreparationError("native_artifact_reference_invalid")
    location = _verified_location(session, location_id, content.id)
    if location.namespace_key != namespace:
        raise V4PreparationError("object_namespace_invalid")
    data = _read_verified_artifact(store, location, content, max_bytes=max_bytes, expected_mime=mime)
    binding = {"sha256": content.sha256, "size_bytes": content.size_bytes, "location_id": str(location.id), "object_version_id": location.object_version_id}
    return data, binding


def _validate_native_references(session, store, refs, document, source_bytes, page_text_bytes, metadata, options):
    """Re-read every native artifact at its pinned object version before use."""
    if set(refs) != set(_NATIVE_REFERENCE_FIELDS):
        raise V4PreparationError("native_artifact_reference_invalid")
    renderer = _native_renderer(metadata.get("renderer_provenance"))
    if refs["rhwp_binary_sha256"] != renderer["rhwp_binary_sha256"] or refs["rhwp_version"] != renderer["rhwp_version"]:
        raise V4PreparationError("renderer_binding_invalid")
    structure = session.get(DocumentStructure, refs["structure_id"]) if refs["structure_id"] else None
    if structure is None or structure.document_version_id != document.id or structure.source_sha256 != _sha256_bytes(source_bytes) or structure.validation_status != "ready":
        raise V4PreparationError("structure_binding_mismatch")
    structure_bytes, structure_binding = _native_object(session, store, structure.payload_content_object_id, refs["structure_location_id"], max_bytes=options.max_output_bytes, mime="application/json")
    if structure_binding["sha256"] != structure.payload_sha256:
        raise V4PreparationError("structure_binding_mismatch")
    map_bytes, map_binding = _native_object(session, store, refs["para_page_map_content_object_id"], refs["para_page_map_location_id"], max_bytes=options.max_output_bytes, mime="application/json")
    if map_binding["sha256"] != refs["para_page_map_sha256"]:
        raise V4PreparationError("snapshot_artifact_hash_mismatch")
    # Snapshots frozen before 0024 carry no candidates.  All three references
    # are null together and the snapshot stays reusable; a mixed set is a
    # broken reference, not a legacy row.
    present = [refs[field] is not None for field in _SECTION_CANDIDATE_FIELDS]
    if any(present) and not all(present):
        raise V4PreparationError("native_artifact_reference_invalid")
    candidates_bytes: bytes | None = None
    candidates_binding = None
    if all(present):
        candidates_bytes, candidates_binding = _native_object(session, store, refs["section_candidates_content_object_id"], refs["section_candidates_location_id"], max_bytes=options.max_output_bytes, mime="application/json")
        if candidates_binding["sha256"] != refs["section_candidates_sha256"]:
            raise V4PreparationError("snapshot_artifact_hash_mismatch")
    try:
        payload = json.loads(structure_bytes)
        page_text = json.loads(page_text_bytes)
        mapping = json.loads(map_bytes)
        candidates = json.loads(candidates_bytes) if candidates_bytes is not None else None
    except (ValueError, UnicodeError):
        raise V4PreparationError("native_artifact_invalid") from None
    if not isinstance(payload, Mapping) or payload.get("structure_id") != str(structure.id) or payload.get("document_version_id") != str(document.id) or payload.get("media_type") != structure.media_type:
        raise V4PreparationError("structure_binding_mismatch")
    hwpx_binding = None
    if structure.media_type == "application/x-hwp":
        hwpx_bytes, hwpx_binding = _native_object(session, store, refs["hwpx_content_object_id"], refs["hwpx_location_id"], max_bytes=options.max_output_bytes, mime="application/hwp+zip", namespace="source")
        if _latest_clean_scan(session, refs["hwpx_content_object_id"]) is None:
            raise V4PreparationError("scanner_unavailable")
    else:
        if refs["hwpx_content_object_id"] is not None or refs["hwpx_location_id"] is not None:
            raise V4PreparationError("native_artifact_reference_invalid")
        hwpx_bytes = source_bytes
    try:
        validate_native_bundle(payload, source_bytes=source_bytes, hwpx_bytes=hwpx_bytes, hwpx_verify=refs["hwpx_verify_jsonb"], page_text=page_text, para_page_map=mapping, section_candidates=candidates, pdf_metadata=metadata, options=options)
    except DocumentProcessingError as error:
        raise V4PreparationError(error.code) from error
    if _canonical(mapping) != map_bytes:
        raise V4PreparationError("para_page_map_invalid")
    if candidates_bytes is not None and _canonical(candidates) != candidates_bytes:
        raise V4PreparationError("section_candidates_invalid")
    binding = {"structure": structure_binding, "para_page_map": map_binding, "hwpx": hwpx_binding, "hwpx_verify": refs["hwpx_verify_jsonb"]}
    # The key is added only when candidates exist so a pre-0024 snapshot keeps
    # its recorded ``binding_sha256`` and stays cache-reusable.
    if candidates_binding is not None:
        binding["section_candidates"] = candidates_binding
    return binding


def read_snapshot_section_candidates(
    session: Session,
    store: ObjectStore,
    snapshot: PrespecV4PdfSnapshot,
) -> dict[str, Any] | None:
    """Return the snapshot's validated section candidates, or ``None``.

    Side-effect free: the object is read at its pinned version, checked against
    the stored hash and the snapshot's own page count, and nothing is written.
    A snapshot frozen before 0024 has no candidates and is not an error.
    """

    present = [getattr(snapshot, field) is not None for field in _SECTION_CANDIDATE_FIELDS]
    if not any(present):
        return None
    if not all(present):
        raise V4PreparationError("native_artifact_reference_invalid")
    options = ProcessorOptions.from_mapping((snapshot.config_jsonb or {}).get("options"))
    data, binding = _native_object(
        session, store, snapshot.section_candidates_content_object_id,
        snapshot.section_candidates_location_id,
        max_bytes=min(options.max_output_bytes, MAX_V4_MANIFEST_BYTES), mime="application/json",
    )
    if binding["sha256"] != snapshot.section_candidates_sha256:
        raise V4PreparationError("snapshot_artifact_hash_mismatch")
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeError):
        raise V4PreparationError("section_candidates_invalid") from None
    try:
        candidates = validate_section_candidates(payload, page_count=snapshot.pdf_page_count)
    except DocumentProcessingError as error:
        raise V4PreparationError(error.code) from error
    if _canonical(candidates) != data:
        raise V4PreparationError("section_candidates_invalid")
    return candidates


def _persist_native_artifacts(session, store, document, processed, source_bytes, metadata, options, scanner):
    """Store native sidecars without replacing any existing document structure."""
    try:
        validate_native_bundle(processed, source_bytes=source_bytes, hwpx_bytes=processed.hwpx_bytes, hwpx_verify=processed.hwpx_verify, page_text=processed.page_text, para_page_map=processed.para_page_map, section_candidates=processed.section_candidates or None, pdf_metadata=metadata, options=options)
    except DocumentProcessingError as error:
        raise V4PreparationError(error.code) from error
    if _canonical(processed.para_page_map) != processed.para_page_map_bytes:
        raise V4PreparationError("para_page_map_invalid")
    if processed.section_candidates and _canonical(processed.section_candidates) != processed.section_candidates_bytes:
        raise V4PreparationError("section_candidates_invalid")
    source = session.get(ContentObject, document.content_object_id)
    if processed["media_type"] != source.detected_mime:
        raise V4PreparationError("source_media_type_mismatch")
    refs = dict.fromkeys(_NATIVE_REFERENCE_FIELDS)
    renderer = _native_renderer(metadata.get("renderer_provenance"))
    refs.update(rhwp_binary_sha256=renderer["rhwp_binary_sha256"], rhwp_version=renderer["rhwp_version"], hwpx_verify_jsonb=processed.hwpx_verify)
    structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
    if structure is not None:
        locations = session.scalars(select(ContentObjectLocation).where(
            ContentObjectLocation.content_object_id == structure.payload_content_object_id,
            ContentObjectLocation.namespace_key == "structure", ContentObjectLocation.status == "verified",
            ContentObjectLocation.purged_at.is_(None),
        ).order_by(ContentObjectLocation.created_at.desc())).all()
        if not locations:
            raise V4PreparationError("structure_binding_mismatch")
        structure_location = locations[0]
        raw, _binding = _native_object(session, store, structure.payload_content_object_id, structure_location.id, max_bytes=options.max_output_bytes, mime="application/json")
        try:
            previous = json.loads(raw)
        except (ValueError, UnicodeError):
            raise V4PreparationError("structure_binding_mismatch") from None
        # Parser-generated IDs/timestamps and extractor labels can differ. All
        # source identity and consumer-visible page/block contents must agree.
        if not isinstance(previous, Mapping) or any(previous.get(key) != processed.get(key) for key in ("source_sha256", "media_type", "pages", "blocks")):
            raise V4PreparationError("structure_binding_mismatch")
    else:
        payload = dict(processed)
        payload.update(structure_id=str(uuid4()), document_version_id=str(document.id))
        raw = _canonical(payload)
        content, structure_location = _persist_artifact(session, store, namespace="structure", object_key=f"structure/prespec-v4/{document.id}/structure-{_sha256_bytes(raw)}.json", data=raw, detected_mime="application/json", retention_class="document-structure")
        structure = persist_structure_rows(session, document, payload, content)
    refs.update(structure_id=structure.id, structure_location_id=structure_location.id)
    if processed["media_type"] == "application/x-hwp":
        try:
            if scanner(processed.hwpx_bytes) is not True:
                raise V4PreparationError("scanner_failed")
        except V4PreparationError:
            raise
        except Exception as error:
            raise V4PreparationError("scanner_unavailable") from error
        content, location = _persist_artifact(session, store, namespace="source", object_key=f"source/prespec-v4/{document.id}/hwpx-{_sha256_bytes(processed.hwpx_bytes)}.hwpx", data=processed.hwpx_bytes, detected_mime="application/hwp+zip", retention_class="document-structure")
        session.add(ContentScan(content_object_id=content.id, scanner="clamav", scanner_version="clamd-instream-v1", status="clean", safe_result={"sha256": content.sha256, "verdict": "clean"}))
        refs.update(hwpx_content_object_id=content.id, hwpx_location_id=location.id)
    raw = processed.para_page_map_bytes
    content, location = _persist_artifact(session, store, namespace="structure", object_key=f"structure/prespec-v4/{document.id}/para-page-map-{_sha256_bytes(raw)}.json", data=raw, detected_mime="application/json", retention_class="document-structure")
    refs.update(para_page_map_content_object_id=content.id, para_page_map_location_id=location.id, para_page_map_sha256=content.sha256)
    # A bundle without candidates leaves the three references null together:
    # the scratch protocol already fails closed when a native build omits the
    # sidecar, so this only covers artifacts frozen before 0024.
    if processed.section_candidates:
        raw = processed.section_candidates_bytes
        content, location = _persist_artifact(session, store, namespace="structure", object_key=f"structure/prespec-v4/{document.id}/section-candidates-{_sha256_bytes(raw)}.json", data=raw, detected_mime="application/json", retention_class="document-structure")
        refs.update(section_candidates_content_object_id=content.id, section_candidates_location_id=location.id, section_candidates_sha256=content.sha256)
    session.flush()
    return refs


def prepare_v4_pdf_snapshot(
    session: Session,
    *,
    document_version_id: UUID,
    source_location_id: UUID,
    source_bytes: bytes,
    media_type: str | None,
    converter: ScratchDocumentProcessor,
    store: ObjectStore,
    options: ProcessorOptions | Mapping[str, Any] | None,
    renderer: Mapping[str, Any],
    font: Mapping[str, Any],
    config: Mapping[str, Any],
    scanner: Callable[[bytes], bool] | None = None,
) -> PrespecV4PdfSnapshot:
    """Run the existing scratch converter and freeze its exact PDF artifacts.

    The worker remains credential-free.  This trusted-side seam only receives
    source bytes already bound to a current safe ``DocumentVersion`` and puts
    the worker PDF plus full-page text into the existing versioned object store
    before appending the immutable snapshot row.
    """

    document = session.get(DocumentVersion, document_version_id)
    if document is None or not document.is_current or document.safety_status != "safe":
        raise V4PreparationError("document_not_current_or_safe")
    source = session.get(ContentObject, document.content_object_id)
    if source is None or len(source_bytes) != source.size_bytes or _sha256_bytes(source_bytes) != source.sha256:
        raise V4PreparationError("source_hash_mismatch")
    try:
        safe_options = vars(ProcessorOptions.from_mapping(options))
    except Exception as error:
        raise V4PreparationError("config_binding_invalid") from error
    config_safe = _bounded_object(config, code="config_binding_invalid")
    if config_safe.get("options") != safe_options:
        raise V4PreparationError("config_binding_invalid")
    source_pdf_expected = source.detected_mime == "application/pdf"
    native = not source_pdf_expected and safe_options["renderer"] == NATIVE_RENDERER
    if source_pdf_expected:
        renderer_safe = _source_pdf_binding(renderer, code="renderer_binding_invalid")
        font_safe = _source_pdf_binding(font, code="font_binding_invalid", font=True)
    elif native:
        renderer_safe = _native_renderer(renderer)
        font_safe = _worker_binding(font, code="font_binding_invalid", asset_key="font_manifest_sha256")
    else:
        raise V4PreparationError("renderer_binding_invalid")
    source_location = _verified_location(session, source_location_id, source.id, allow_structure=False)
    config_sha = _sha256_json(config_safe)
    renderer_digest = _sha256_json(renderer_safe)
    font_digest = _sha256_json(
        font_safe if source_pdf_expected else _worker_identity(font_safe, asset_key="font_manifest_sha256")
    )
    reusable = session.scalar(
        select(PrespecV4PdfSnapshot).where(
            PrespecV4PdfSnapshot.document_version_id == document.id,
            PrespecV4PdfSnapshot.source_sha256 == source.sha256,
            PrespecV4PdfSnapshot.config_sha256 == config_sha,
            PrespecV4PdfSnapshot.renderer_digest == renderer_digest,
            PrespecV4PdfSnapshot.font_digest == font_digest,
        )
    )
    if reusable is not None:
        if reusable.source_location_id != source_location.id:
            raise V4PreparationError("snapshot_identity_conflict")
        _validate_cached_snapshot_artifacts(
            session,
            store,
            reusable,
            source,
            source_location,
            source_bytes=source_bytes,
            max_pdf_bytes=int(safe_options["max_output_bytes"]),
        )
        return reusable
    try:
        processed = converter.process(source_bytes, media_type, options)
    except Exception as error:
        if isinstance(error, V4PreparationError):
            raise
        code = getattr(error, "code", None)
        suffix = f":{code}" if isinstance(error, DocumentProcessingError) and code in SAFE_CONVERTER_CODES else ""
        raise V4PreparationError(f"pdf_preparation_failed{suffix}") from error
    exact_scanner = scanner or converter.clamav_checker
    detected_media_type = processed.get("media_type")
    if detected_media_type == "application/pdf":
        pdf_bytes = source_bytes
        source_kind = "original"
        pdf_location_id = source_location_id
    else:
        pdf_bytes = processed.converted_pdf_bytes
        if not isinstance(pdf_bytes, bytes):
            raise V4PreparationError("pdf_preparation_failed")
        source_kind = "generated"
    metadata = processed.pdf_metadata
    if not isinstance(metadata, Mapping):
        raise V4PreparationError("pdf_metadata_invalid")
    if native:
        renderer_safe, font_safe = _assert_native_provenance(metadata, renderer_safe, font_safe)
    else:
        renderer_safe, font_safe = _assert_source_pdf_provenance(metadata, renderer_safe, font_safe)
    if source_kind == "generated":
        try:
            if exact_scanner(pdf_bytes) is not True:
                raise V4PreparationError("scanner_failed")
        except V4PreparationError:
            raise
        except Exception as error:
            raise V4PreparationError("scanner_unavailable") from error
        _pdf_content, pdf_location = _persist_artifact(
            session,
            store,
            namespace="source",
            object_key=f"source/prespec-v4/{document.id}/pdf-{_sha256_bytes(pdf_bytes)}.pdf",
            data=pdf_bytes,
            detected_mime="application/pdf",
            retention_class="prespec-v4-pdf",
        )
        pdf_location_id = pdf_location.id
    native_refs = None
    if native:
        native_refs = _persist_native_artifacts(
            session, store, document, processed, source_bytes, metadata,
            ProcessorOptions.from_mapping(options), exact_scanner,
        )
    page_text_bytes = _canonical(processed.page_text) if native else _page_text_payload(processed)
    page_text_content, page_text_location = _persist_artifact(
        session,
        store,
        namespace="structure",
        object_key=f"structure/prespec-v4/{document.id}/page-text-{_sha256_bytes(page_text_bytes)}.json",
        data=page_text_bytes,
        detected_mime="application/json",
        retention_class="prespec-v4-page-text",
    )
    return freeze_pdf_snapshot(
        session,
        document_version_id=document.id,
        source_location_id=source_location_id,
        pdf_location_id=pdf_location_id,
        page_text_content_object_id=page_text_content.id,
        page_text_location_id=page_text_location.id,
        pdf_metadata=metadata,
        renderer=renderer_safe,
        font=font_safe,
        config=config_safe,
        source_kind=source_kind,
        source_bytes=source_bytes,
        pdf_bytes=pdf_bytes,
        page_text_bytes=page_text_bytes,
        scanner=exact_scanner,
        native_artifacts=native_refs,
        store=store,
    )


def freeze_pdf_snapshot(
    session: Session,
    *,
    document_version_id: UUID,
    source_location_id: UUID,
    pdf_location_id: UUID,
    page_text_content_object_id: UUID,
    page_text_location_id: UUID,
    pdf_metadata: Mapping[str, Any],
    renderer: Mapping[str, Any],
    font: Mapping[str, Any],
    config: Mapping[str, Any],
    source_kind: str,
    source_bytes: bytes | None = None,
    pdf_bytes: bytes | None = None,
    page_text_bytes: bytes | None = None,
    scanner: Callable[[bytes], bool] | None = None,
    scanner_version: str = "clamd-instream-v1",
    native_artifacts: Mapping[str, Any] | None = None,
    store: ObjectStore | None = None,
) -> PrespecV4PdfSnapshot:
    """Validate exact object references and append/reuse one PDF snapshot."""

    document = session.get(DocumentVersion, document_version_id)
    if document is None or not document.is_current or document.safety_status != "safe":
        raise V4PreparationError("document_not_current_or_safe")
    source = session.get(ContentObject, document.content_object_id)
    if source is None:
        raise V4PreparationError("source_content_missing")
    source_location = _verified_location(session, source_location_id, source.id, allow_structure=False)
    pdf_location = session.get(ContentObjectLocation, pdf_location_id)
    if pdf_location is None or pdf_location.status != "verified" or pdf_location.purged_at is not None or not pdf_location.object_version_id:
        raise V4PreparationError("object_location_unverified")
    pdf = session.get(ContentObject, pdf_location.content_object_id)
    if pdf is None or pdf.detected_mime != "application/pdf":
        raise V4PreparationError("pdf_content_missing")
    _verified_location(session, pdf_location_id, pdf.id)
    page_text = session.get(ContentObject, page_text_content_object_id)
    if page_text is None:
        raise V4PreparationError("page_text_reference_invalid")
    page_text_location = _verified_location(session, page_text_location_id, page_text.id)
    if source_kind not in {"original", "generated"}:
        raise V4PreparationError("source_kind_invalid")
    _check_artifact_bytes(source_bytes, source)
    _check_artifact_bytes(pdf_bytes, pdf, "application/pdf")
    if source_kind == "original" and (source.id != pdf.id or source.sha256 != pdf.sha256 or source.size_bytes != pdf.size_bytes or source_location.id != pdf_location.id):
        raise V4PreparationError("original_source_binding_mismatch")
    if source_kind == "original" and pdf_bytes is not None and source_bytes is not None and pdf_bytes != source_bytes:
        raise V4PreparationError("original_source_binding_mismatch")
    metadata, page_count = _validate_pdf_metadata(pdf_metadata)
    native = metadata["schema"] == NATIVE_SNAPSHOT_SCHEMA
    page_text_sha256, page_text_size = _validate_page_text_artifact(page_text_bytes, page_text, metadata)
    if source_kind == "original":
        renderer_safe = _source_pdf_binding(renderer, code="renderer_binding_invalid")
        font_safe = _source_pdf_binding(font, code="font_binding_invalid", font=True)
    elif native:
        renderer_safe = _native_renderer(renderer)
        font_safe = _worker_binding(font, code="font_binding_invalid", asset_key="font_manifest_sha256")
    else:
        raise V4PreparationError("renderer_binding_invalid")
    config_safe = _bounded_object(config, code="config_binding_invalid")
    config_sha = _sha256_json(config_safe)
    if native:
        renderer_safe, font_safe = _assert_native_provenance(metadata, renderer_safe, font_safe)
    else:
        renderer_safe, font_safe = _assert_source_pdf_provenance(metadata, renderer_safe, font_safe)
    renderer_digest = _sha256_json(renderer_safe)
    font_digest = _sha256_json(
        font_safe if source_kind == "original" else _worker_identity(font_safe, asset_key="font_manifest_sha256")
    )
    scan: dict[str, Any] = {"scanner": "clamav", "scanner_version": scanner_version, "source_sha256": source.sha256, "pdf_sha256": pdf.sha256}
    if scanner is not None:
        if source_bytes is None or pdf_bytes is None:
            raise V4PreparationError("artifact_bytes_required_for_scan")
        try:
            if scanner(source_bytes) is not True or scanner(pdf_bytes) is not True:
                raise V4PreparationError("scanner_failed")
        except V4PreparationError:
            raise
        except Exception as error:
            raise V4PreparationError("scanner_unavailable") from error
        scan["verdict"] = "clean"
        for content in (source, pdf):
            latest = _latest_clean_scan(session, content.id)
            if latest is None:
                session.add(ContentScan(
                    content_object_id=content.id,
                    scanner="clamav",
                    scanner_version=scanner_version,
                    status="clean",
                    safe_result={"sha256": content.sha256, "verdict": "clean"},
                ))
    else:
        source_scan = _latest_clean_scan(session, source.id)
        pdf_scan = _latest_clean_scan(session, pdf.id)
        if source_scan is None or pdf_scan is None:
            raise V4PreparationError("scanner_unavailable")
        scan["verdict"] = "clean"
    native_binding = {}
    if native:
        if source_kind != "generated" or store is None or source_bytes is None or page_text_bytes is None or native_artifacts is None:
            raise V4PreparationError("native_artifacts_required")
        native_options = ProcessorOptions.from_mapping(config_safe.get("options"))
        for content, location, data, limit in (
            (source, source_location, source_bytes, source.size_bytes),
            (pdf, pdf_location, pdf_bytes, native_options.max_output_bytes),
            (page_text, page_text_location, page_text_bytes, MAX_V4_MANIFEST_BYTES),
        ):
            stored = _read_verified_artifact(store, location, content, max_bytes=limit)
            if stored != data:
                raise V4PreparationError("artifact_hash_mismatch")
        native_binding = _validate_native_references(
            session, store, native_artifacts, document, source_bytes,
            page_text_bytes, metadata, native_options,
        )
    elif native_artifacts is not None:
        raise V4PreparationError("native_artifacts_unexpected")
    binding_sha = _sha256_json({
        "source_sha256": source.sha256,
        "pdf_sha256": pdf.sha256,
        "page_text_sha256": page_text_sha256,
        "source_kind": source_kind,
        "pdf_metadata": metadata,
        "renderer": renderer_safe,
        "font": font_safe,
        "config": config_safe,
        "scan": scan,
        **({"native": native_binding} if native else {}),
    })
    existing = session.scalar(
        select(PrespecV4PdfSnapshot).where(
            PrespecV4PdfSnapshot.document_version_id == document.id,
            PrespecV4PdfSnapshot.source_sha256 == source.sha256,
            PrespecV4PdfSnapshot.config_sha256 == config_sha,
            PrespecV4PdfSnapshot.renderer_digest == renderer_digest,
            PrespecV4PdfSnapshot.font_digest == font_digest,
        )
    )
    if existing is not None:
        if (
            existing.pdf_sha256 != pdf.sha256
            or existing.page_text_sha256 != page_text_sha256
            or existing.binding_sha256 != binding_sha
        ):
            raise V4PreparationError("snapshot_identity_conflict")
        return existing
    row = PrespecV4PdfSnapshot(
        id=uuid4(), notice_id=document.notice_id, document_version_id=document.id,
        source_content_object_id=source.id, source_location_id=source_location.id,
        pdf_content_object_id=pdf.id, pdf_location_id=pdf_location.id,
        page_text_content_object_id=page_text.id, page_text_location_id=page_text_location.id,
        source_kind=source_kind, source_sha256=source.sha256, source_size_bytes=source.size_bytes,
        pdf_sha256=pdf.sha256, pdf_size_bytes=pdf.size_bytes, pdf_page_count=page_count,
        page_text_sha256=page_text_sha256, page_text_size_bytes=page_text_size,
        pdf_metadata_jsonb=metadata, renderer_jsonb=renderer_safe, renderer_digest=renderer_digest,
        font_jsonb=font_safe, font_digest=font_digest, config_jsonb=config_safe, config_sha256=config_sha,
        scan_jsonb=scan, binding_sha256=binding_sha,
        **(dict(native_artifacts) if native else {}),
    )
    session.add(row)
    session.flush()
    return row


def _observation_ref(
    session: Session,
    notice_id: int,
    kind: str,
    observation_id: int | None,
    reference: Mapping[str, Any],
    *,
    document_version_id: UUID | None = None,
) -> dict[str, Any]:
    safe = _bounded_object(reference, code="observation_binding_invalid")
    if kind == "explicit_sample":
        if observation_id is not None:
            raise V4PreparationError("observation_binding_invalid")
        safe.setdefault("kind", "explicit_sample")
        return safe
    if observation_id is None:
        raise V4PreparationError("observation_binding_invalid")
    observation = session.get(NoticeObservation, observation_id)
    if observation is None or observation.notice_id != notice_id or not observation.source_sha256 or not observation.snapshot_schema_version:
        raise V4PreparationError("observation_binding_invalid")
    if document_version_id is not None and safe.get("document_version_id") != str(document_version_id):
        raise V4PreparationError("observation_binding_invalid")
    if kind != "explicit_sample":
        source = session.get(ContentObject, session.get(DocumentVersion, document_version_id).content_object_id) if document_version_id is not None and session.get(DocumentVersion, document_version_id) is not None else None
        if source is None or safe.get("document_source_sha256") != source.sha256 or safe.get("document_source_size_bytes") != source.size_bytes:
            raise V4PreparationError("observation_binding_invalid")
    if kind == "attachment_change":
        # `changed_fields_json` describes notice columns and is not sufficient
        # evidence that an attachment changed.  The preparation seam records
        # canonical current/previous attachment fingerprints instead.
        if safe.get("attachment_changed") is not True or safe.get("current_attachment_fingerprint_sha256") == safe.get("previous_attachment_fingerprint_sha256"):
            raise V4PreparationError("attachment_change_unobserved")
    safe.update({"kind": kind, "observation_id": observation.id, "observation_source_sha256": observation.source_sha256})
    return safe


def freeze_v4_target(
    session: Session,
    *,
    snapshot_id: UUID,
    observation_kind: str,
    observation_id: int | None,
    observation_reference: Mapping[str, Any],
    selection: V4RangeSelection,
    manifest_content_object_id: UUID | None = None,
    manifest_location_id: UUID | None = None,
    manifest_bytes: bytes | None = None,
) -> PrespecV4Target:
    """Append one target; an ambiguous range is stored without an input."""

    snapshot = session.get(PrespecV4PdfSnapshot, snapshot_id)
    if snapshot is None:
        raise V4PreparationError("snapshot_not_found")
    observation = _observation_ref(
        session,
        snapshot.notice_id,
        observation_kind,
        observation_id,
        observation_reference,
        document_version_id=snapshot.document_version_id,
    )
    if selection.status == "ready":
        if manifest_content_object_id is None or manifest_location_id is None or manifest_bytes is None:
            raise V4PreparationError("manifest_reference_missing")
        manifest_content = session.get(ContentObject, manifest_content_object_id)
        if manifest_content is None or manifest_content.detected_mime != "application/json":
            raise V4PreparationError("manifest_reference_invalid")
        _check_artifact_bytes(manifest_bytes, manifest_content)
        if _sha256_bytes(manifest_bytes) != _sha256_bytes(selection.manifest_bytes) or len(manifest_bytes) != len(selection.manifest_bytes):
            raise V4PreparationError("manifest_hash_mismatch")
        _verified_location(session, manifest_location_id, manifest_content.id)
        if selection.manifest.get("schema_version") != V4_MANIFEST_SCHEMA:
            raise V4PreparationError("manifest_schema_invalid")
        metadata_pages = {
            int(item["number"]): item
            for item in (snapshot.pdf_metadata_jsonb.get("pages") or [])
            if isinstance(item, Mapping) and isinstance(item.get("number"), int)
        }
        manifest_pages = selection.manifest.get("pages")
        if not isinstance(manifest_pages, list) or not manifest_pages:
            raise V4PreparationError("manifest_schema_invalid")
        for item in manifest_pages:
            if not isinstance(item, Mapping):
                raise V4PreparationError("manifest_schema_invalid")
            number = item.get("number")
            text = item.get("text")
            if number not in metadata_pages or not isinstance(text, str):
                raise V4PreparationError("manifest_page_binding_mismatch")
            if item.get("text_sha256") != _sha256_bytes(text.encode("utf-8")):
                raise V4PreparationError("manifest_page_binding_mismatch")
            if item.get("source_page_text_sha256") != metadata_pages[number].get("text_sha256"):
                raise V4PreparationError("manifest_page_binding_mismatch")
        status = "ready"
        reason_code = None
        manifest_sha = _sha256_bytes(manifest_bytes)
        input_sha = selection.input_sha256
        byte_count = len(manifest_bytes)
    else:
        if manifest_content_object_id is not None or manifest_location_id is not None or manifest_bytes is not None:
            raise V4PreparationError("manifest_reference_invalid")
        location = None
        status = selection.status if selection.status in {"needs_human_review", "excluded"} else "needs_human_review"
        reason_code = selection.reason_code or "ambiguous_scope"
        manifest_sha = None
        input_sha = None
        byte_count = None
    identity_sha = _sha256_json({
        "snapshot_id": str(snapshot.id),
        "observation_kind": observation_kind,
        "observation_id": observation_id,
        "selection_manifest_sha256": manifest_sha,
        "selection_status": status,
        "reason_code": reason_code,
    })
    existing = session.scalar(
        select(PrespecV4Target).where(
            PrespecV4Target.snapshot_id == snapshot.id,
            PrespecV4Target.identity_sha256 == identity_sha,
        )
    )
    if existing is not None:
        return existing
    row = PrespecV4Target(
        id=uuid4(), notice_id=snapshot.notice_id, document_version_id=snapshot.document_version_id,
        snapshot_id=snapshot.id, observation_kind=observation_kind, observation_id=observation_id,
        observation_jsonb=observation, selection_status=status, reason_code=reason_code,
        selection_strategy=selection.strategy, start_locator=selection.start_locator,
        end_locator=selection.end_locator, page_numbers_jsonb=list(selection.page_numbers) or None,
        input_text_sha256_jsonb=list(selection.page_text_hashes) or None, input_sha256=input_sha,
        input_byte_count=byte_count, selection_manifest_sha256=manifest_sha,
        identity_sha256=identity_sha,
        manifest_content_object_id=manifest_content_object_id, manifest_location_id=manifest_location_id,
    )
    session.add(row)
    session.flush()
    return row


__all__ = [
    "DocumentCandidateSelection", "V4PreparationError", "V4RangeSelection",
    "choose_rfp_document", "select_v4_input_range", "prepare_v4_pdf_snapshot",
    "freeze_pdf_snapshot",
    "freeze_v4_target",
]
