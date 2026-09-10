"""Validation helpers for ``bidops.document-structure.v1``.

The service stores the complete structure JSON as the authoritative payload.
This module intentionally uses the standard library rather than a second
schema dependency so the processor remains usable in the quarantine worker.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any, Mapping

from .errors import DocumentProcessingError

SCHEMA = "bidops.document-structure.v1"
UPSTREAM_COMMIT = "96a2633f23a08f707679d7e212ebdc59948260e6"
DEFAULT_MAX_PAGES = 512
DEFAULT_MAX_BLOCKS = 100_000
PARA_PAGE_MAP_SCHEMA = "bidops.para-page-map.v1"
PARA_PAGE_MAP_RULE = "para-page-align.v1"
PARA_PAGE_KINDS = frozenset({
    "fullParagraph", "partialParagraph", "table", "partialTable", "shape",
    "hiddenEmptyPara", "wrapAroundPara",
})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_FORBIDDEN_KEY = re.compile(r"(?:path|url|uri|credential|secret|token|password|shell)", re.I)


def _safe_attributes(value: Any, *, depth: int = 0) -> None:
    if depth > 64:
        raise DocumentProcessingError("invalid_attribute", "구조 속성의 중첩 깊이가 제한을 초과했습니다")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _FORBIDDEN_KEY.search(key):
                raise DocumentProcessingError("unsafe_attribute", "구조 속성에 허용되지 않는 필드가 있습니다")
            _safe_attributes(child, depth=depth + 1)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _safe_attributes(child, depth=depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise DocumentProcessingError("invalid_attribute", "구조 속성의 값 형식이 올바르지 않습니다")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise DocumentProcessingError("invalid_attribute", "구조 속성의 값 형식이 올바르지 않습니다")


def validate_structure(
    payload: Mapping[str, Any],
    *,
    max_output_bytes: int | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> dict[str, Any]:
    """Validate and return a JSON-compatible copy of a structure payload.

    Additional fields are rejected at every contract-owned level.  Extractor
    attributes are the only intentionally open object and still cannot carry
    paths, URLs, credentials, or other execution data.
    """

    allowed = {
        "schema", "structure_id", "document_version_id", "source_sha256",
        "media_type", "extractor", "pages", "blocks", "warnings", "created_at",
    }
    if set(payload) != allowed:
        raise DocumentProcessingError("invalid_structure", "문서 구조 계약 필드가 올바르지 않습니다")
    if payload.get("schema") != SCHEMA:
        raise DocumentProcessingError("invalid_structure", "문서 구조 schema가 올바르지 않습니다")
    for name in ("structure_id", "document_version_id"):
        value = payload.get(name)
        if not isinstance(value, str) or not _UUID.fullmatch(value):
            raise DocumentProcessingError("invalid_structure", "문서 구조 식별자가 올바르지 않습니다")
    source_hash = payload.get("source_sha256")
    if not isinstance(source_hash, str) or not _SHA256.fullmatch(source_hash):
        raise DocumentProcessingError("invalid_structure", "문서 원본 hash가 올바르지 않습니다")
    if not isinstance(payload.get("media_type"), str) or not payload["media_type"]:
        raise DocumentProcessingError("invalid_structure", "문서 media type이 올바르지 않습니다")

    extractor = payload.get("extractor")
    if not isinstance(extractor, Mapping) or set(extractor) != {"name", "version", "upstream_commit"}:
        raise DocumentProcessingError("invalid_structure", "추출기 정보가 올바르지 않습니다")
    if not all(isinstance(extractor.get(k), str) and extractor.get(k) for k in ("name", "version")):
        raise DocumentProcessingError("invalid_structure", "추출기 정보가 올바르지 않습니다")
    upstream_commit = extractor.get("upstream_commit")
    if upstream_commit is not None and upstream_commit != UPSTREAM_COMMIT:
        raise DocumentProcessingError("invalid_structure", "추출기 provenance가 올바르지 않습니다")

    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise DocumentProcessingError("invalid_structure", "페이지 목록이 올바르지 않습니다")
    if len(pages) > max_pages:
        raise DocumentProcessingError("page_limit", "문서 page 수 제한을 초과했습니다")
    page_numbers: set[int] = set()
    for page in pages:
        if not isinstance(page, Mapping) or set(page) != {"number", "width", "height", "image_content_object_id"}:
            raise DocumentProcessingError("invalid_structure", "페이지 metadata가 올바르지 않습니다")
        number, width, height = page.get("number"), page.get("width"), page.get("height")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1 or number in page_numbers:
            raise DocumentProcessingError("invalid_structure", "페이지 번호가 올바르지 않습니다")
        if not isinstance(width, (int, float)) or isinstance(width, bool) or not math.isfinite(width) or width <= 0:
            raise DocumentProcessingError("invalid_structure", "페이지 폭이 올바르지 않습니다")
        if not isinstance(height, (int, float)) or isinstance(height, bool) or not math.isfinite(height) or height <= 0:
            raise DocumentProcessingError("invalid_structure", "페이지 높이가 올바르지 않습니다")
        image_id = page.get("image_content_object_id")
        if image_id is not None and (not isinstance(image_id, str) or not _UUID.fullmatch(image_id)):
            raise DocumentProcessingError("invalid_structure", "페이지 이미지 식별자가 올바르지 않습니다")
        page_numbers.add(number)

    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        raise DocumentProcessingError("invalid_structure", "블록 목록이 올바르지 않습니다")
    if len(blocks) > max_blocks:
        raise DocumentProcessingError("block_limit", "문서 구조 block 수 제한을 초과했습니다")
    keys: set[str] = set()
    parents: dict[str, str | None] = {}
    for block in blocks:
        required = {"block_key", "parent_block_key", "type", "page", "bbox", "text", "confidence", "attributes"}
        if not isinstance(block, Mapping) or set(block) != required:
            raise DocumentProcessingError("invalid_structure", "블록 계약 필드가 올바르지 않습니다")
        key = block.get("block_key")
        if not isinstance(key, str) or not key or key in keys:
            raise DocumentProcessingError("invalid_structure", "블록 식별자가 올바르지 않습니다")
        parent = block.get("parent_block_key")
        if parent is not None and (not isinstance(parent, str) or not parent):
            raise DocumentProcessingError("invalid_structure", "블록 부모 식별자가 올바르지 않습니다")
        if not isinstance(block.get("type"), str) or not block["type"]:
            raise DocumentProcessingError("invalid_structure", "블록 유형이 올바르지 않습니다")
        if (
            not isinstance(block.get("page"), int)
            or isinstance(block.get("page"), bool)
            or block.get("page") not in page_numbers
        ):
            raise DocumentProcessingError("invalid_structure", "블록 페이지가 해소되지 않습니다")
        bbox = block.get("bbox")
        if bbox is not None:
            if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in bbox):
                raise DocumentProcessingError("invalid_structure", "블록 bbox가 올바르지 않습니다")
            if bbox[0] > bbox[2] or bbox[1] > bbox[3]:
                raise DocumentProcessingError("invalid_structure", "블록 bbox 순서가 올바르지 않습니다")
        if not isinstance(block.get("text"), str):
            raise DocumentProcessingError("invalid_structure", "블록 text가 올바르지 않습니다")
        confidence = block.get("confidence")
        if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise DocumentProcessingError("invalid_structure", "블록 confidence가 올바르지 않습니다")
        if not isinstance(block.get("attributes"), Mapping):
            raise DocumentProcessingError("invalid_structure", "블록 attributes가 올바르지 않습니다")
        _safe_attributes(block["attributes"])
        keys.add(key)
        parents[key] = parent
    for parent in parents.values():
        if parent is not None and parent not in keys:
            raise DocumentProcessingError("invalid_structure", "블록 부모가 해소되지 않습니다")

    # Each node is marked once as active and once as complete.  Completing the
    # path before starting the next root makes parent-chain validation O(n),
    # rather than walking every ancestor from every block (O(n^2) for a chain).
    state: dict[str, int] = {}
    for key in parents:
        if state.get(key) == 2:
            continue
        path: list[str] = []
        cursor: str | None = key
        while cursor is not None and state.get(cursor, 0) == 0:
            state[cursor] = 1
            path.append(cursor)
            cursor = parents[cursor]
        if cursor is not None and state.get(cursor) == 1:
            raise DocumentProcessingError("invalid_structure", "블록 부모 관계에 cycle이 있습니다")
        for visited in path:
            state[visited] = 2

    if not isinstance(payload.get("warnings"), list) or not all(isinstance(v, str) for v in payload["warnings"]):
        raise DocumentProcessingError("invalid_structure", "문서 warning 형식이 올바르지 않습니다")
    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        raise DocumentProcessingError("invalid_structure", "생성 시각이 올바르지 않습니다")
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if parsed_created_at.tzinfo is None or parsed_created_at.utcoffset() is None:
            raise DocumentProcessingError("invalid_structure", "생성 시각이 올바르지 않습니다")
    except ValueError as exc:
        raise DocumentProcessingError("invalid_structure", "생성 시각이 올바르지 않습니다") from exc
    if max_output_bytes is not None:
        try:
            serialized_size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError, RecursionError) as exc:
            raise DocumentProcessingError("invalid_structure", "문서 구조가 JSON으로 직렬화되지 않습니다") from exc
        if serialized_size > max_output_bytes:
            raise DocumentProcessingError("output_size_limit", "문서 처리 결과 크기 제한을 초과했습니다")
    return dict(payload)


def para_page_map_error() -> DocumentProcessingError:
    return DocumentProcessingError(
        "para_page_map_invalid", "문단·페이지 대응표 계약이 올바르지 않습니다", source_preserved=True,
    )


def validate_para_page_map(
    payload: Mapping[str, Any],
    *,
    block_keys: set[str] | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> dict[str, Any]:
    """Validate the closed schema, ranges, identities and full block partition.

    Mapping coverage is informational: zero mapped blocks is valid.
    """
    def integer(value: Any, minimum: int = 0) -> bool:
        return type(value) is int and value >= minimum

    def fields(value: Any, expected: set[str]) -> None:
        if not isinstance(value, Mapping) or set(value) != expected:
            raise para_page_map_error()

    fields(payload, {"schema", "page_count", "paragraph_count", "paragraphs", "blocks", "unmapped_block_keys", "mapping"})
    count = payload["page_count"]
    if payload["schema"] != PARA_PAGE_MAP_SCHEMA or not integer(count, 1) or count > max_pages:
        raise para_page_map_error()
    paragraphs, blocks, unmapped = payload["paragraphs"], payload["blocks"], payload["unmapped_block_keys"]
    if not all(isinstance(items, list) for items in (paragraphs, blocks, unmapped)):
        raise para_page_map_error()
    if not integer(payload["paragraph_count"]) or payload["paragraph_count"] != len(paragraphs):
        raise para_page_map_error()
    if len(paragraphs) > max_blocks or len(blocks) + len(unmapped) > max_blocks:
        raise para_page_map_error()

    def page_range(item: Mapping[str, Any]) -> tuple[int, int]:
        first, last = item["page_first"], item["page_last"]
        if not integer(first, 1) or not integer(last, 1) or not first <= last <= count:
            raise para_page_map_error()
        return first, last

    identities: dict[tuple[int, int], tuple[int, int]] = {}
    for item in paragraphs:
        fields(item, {"section", "para_index", "page_first", "page_last", "kind"})
        if not integer(item["section"]) or not integer(item["para_index"]) or not isinstance(item["kind"], str) or item["kind"] not in PARA_PAGE_KINDS:
            raise para_page_map_error()
        key = (item["section"], item["para_index"])
        if key in identities:
            raise para_page_map_error()
        identities[key] = page_range(item)

    keys: set[str] = set()
    for item in blocks:
        fields(item, {"block_key", "section", "para_index", "page_first", "page_last", "match"})
        key = item["block_key"]
        if not isinstance(key, str) or not key or key in keys:
            raise para_page_map_error()
        keys.add(key)
        bounds = page_range(item)
        section, para_index = item["section"], item["para_index"]
        if section is not None and not integer(section):
            raise para_page_map_error()
        if item["match"] == "exact":
            if not integer(section) or not integer(para_index) or identities.get((section, para_index)) != bounds:
                raise para_page_map_error()
        elif item["match"] == "page_text":
            if para_index is not None or bounds[0] != bounds[1]:
                raise para_page_map_error()
        else:
            raise para_page_map_error()
    for key in unmapped:
        if not isinstance(key, str) or not key or key in keys:
            raise para_page_map_error()
        keys.add(key)
    if block_keys is not None and keys != block_keys:
        raise para_page_map_error()
    mapping = payload["mapping"]
    fields(mapping, {"blocks_total", "blocks_mapped", "blocks_unmapped", "rule"})
    if mapping["rule"] != PARA_PAGE_MAP_RULE or any(
        not integer(mapping[key]) or mapping[key] != value
        for key, value in (("blocks_total", len(keys)), ("blocks_mapped", len(blocks)), ("blocks_unmapped", len(unmapped)))
    ):
        raise para_page_map_error()
    return dict(payload)


def para_page_map_bytes(
    payload: Mapping[str, Any], *, max_output_bytes: int,
    max_pages: int = DEFAULT_MAX_PAGES, max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> bytes:
    """Serialize an independently validated mapping as canonical UTF-8 JSON."""
    validate_para_page_map(payload, max_pages=max_pages, max_blocks=max_blocks)
    try:
        result = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise para_page_map_error() from exc
    if len(result) > max_output_bytes:
        raise DocumentProcessingError("output_size_limit", "문단·페이지 대응표 크기 제한을 초과했습니다", source_preserved=True)
    return result
