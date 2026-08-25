"""Validation helpers for ``bidops.document-structure.v1``.

The service stores the complete structure JSON as the authoritative payload.
This module intentionally uses the standard library rather than a second
schema dependency so the processor remains usable in the quarantine worker.
"""

from __future__ import annotations

import re
import math
from datetime import datetime
from typing import Any, Mapping

from .errors import DocumentProcessingError

SCHEMA = "bidops.document-structure.v1"
UPSTREAM_COMMIT = "96a2633f23a08f707679d7e212ebdc59948260e6"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_FORBIDDEN_KEY = re.compile(r"(?:path|url|uri|credential|secret|token|password|shell)", re.I)


def _safe_attributes(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _FORBIDDEN_KEY.search(key):
                raise DocumentProcessingError("unsafe_attribute", "구조 속성에 허용되지 않는 필드가 있습니다")
            _safe_attributes(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _safe_attributes(child)
    elif isinstance(value, float) and not math.isfinite(value):
        raise DocumentProcessingError("invalid_attribute", "구조 속성의 값 형식이 올바르지 않습니다")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise DocumentProcessingError("invalid_attribute", "구조 속성의 값 형식이 올바르지 않습니다")


def validate_structure(payload: Mapping[str, Any]) -> dict[str, Any]:
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
    if extractor.get("upstream_commit") is not None and not isinstance(extractor["upstream_commit"], str):
        raise DocumentProcessingError("invalid_structure", "추출기 provenance가 올바르지 않습니다")

    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise DocumentProcessingError("invalid_structure", "페이지 목록이 올바르지 않습니다")
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
        if block.get("page") not in page_numbers:
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
    for key, parent in parents.items():
        if parent is not None and parent not in keys:
            raise DocumentProcessingError("invalid_structure", "블록 부모가 해소되지 않습니다")
        seen: set[str] = set()
        cursor = key
        while cursor is not None:
            if cursor in seen:
                raise DocumentProcessingError("invalid_structure", "블록 부모 관계에 cycle이 있습니다")
            seen.add(cursor)
            cursor = parents.get(cursor)

    if not isinstance(payload.get("warnings"), list) or not all(isinstance(v, str) for v in payload["warnings"]):
        raise DocumentProcessingError("invalid_structure", "문서 warning 형식이 올바르지 않습니다")
    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        raise DocumentProcessingError("invalid_structure", "생성 시각이 올바르지 않습니다")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DocumentProcessingError("invalid_structure", "생성 시각이 올바르지 않습니다") from exc
    return dict(payload)
