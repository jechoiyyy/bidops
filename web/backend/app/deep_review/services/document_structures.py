"""Canonical persistence for clean, inspected document structures.

The document preparation and pre-specification attachment paths both receive
the same :class:`~app.deep_review.services.assets.InspectedAsset`.  This module owns the
single transition from its processed structure mapping to the immutable
``DocumentStructure``/``DocumentBlock`` rows and the versioned structure
payload object.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..document_mcp.contracts import validate_structure
from ..document_mcp.errors import DocumentProcessingError
from ..models import (
    ContentObject,
    ContentObjectLocation,
    DocumentBlock,
    DocumentStructure,
    DocumentVersion,
)
from . import assets, document_segments


LocationWriter = Callable[[Session, UUID, str, Path, str], None]


def _add_location(
    session: Session,
    content_id: UUID,
    namespace: str,
    path: Path,
    digest: str,
    *,
    root: Path | None,
) -> None:
    """Record a verified object location below its purpose namespace."""

    base = assets.asset_root(root)
    try:
        relative = path.resolve().relative_to(base)
    except (OSError, ValueError) as exc:
        raise assets.AssetError("processing_failed", "asset location이 격리 루트 밖입니다") from exc
    if not relative.parts or relative.parts[0] != namespace:
        raise assets.AssetError("processing_failed", "asset namespace가 올바르지 않습니다")
    object_key = relative.as_posix()
    metadata = assets.head_object(namespace, object_key, root=root)
    session.add(
        ContentObjectLocation(
            content_object_id=content_id,
            namespace_key=namespace,
            object_key=object_key,
            object_version_id=metadata.object_version_id,
            status="verified",
            etag=metadata.etag,
            verified_at=datetime.now(UTC),
        )
    )


def _ensure_structure_content(
    session: Session,
    payload_hash: str,
    payload: Mapping[str, object],
) -> ContentObject:
    content = session.scalar(select(ContentObject).where(ContentObject.sha256 == payload_hash))
    if content is None:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        content = ContentObject(
            sha256=payload_hash,
            size_bytes=len(encoded),
            detected_mime="application/json",
            retention_class="document-structure",
        )
        session.add(content)
        session.flush()
    return content


def _store_generated_content(
    session: Session,
    content: bytes,
    media_type: str,
    *,
    root: Path | None,
    request_paths: list[Path],
    add_location: LocationWriter,
) -> ContentObject:
    digest = hashlib.sha256(content).hexdigest()
    object_row = session.scalar(select(ContentObject).where(ContentObject.sha256 == digest))
    if object_row is None:
        object_row = ContentObject(
            sha256=digest,
            size_bytes=len(content),
            detected_mime=media_type,
            retention_class="document-structure",
        )
        session.add(object_row)
        session.flush()
    destination, metadata = assets.store_bytes("structure", content, root=root, suffix=".bin")
    if metadata.size_bytes != len(content):
        raise assets.AssetError("hash_mismatch", "구조 이미지 hash 검증에 실패했습니다")
    request_paths.append(destination)
    add_location(session, object_row.id, "structure", destination, digest)
    return object_row


def materialize_structure(
    session: Session,
    document: DocumentVersion,
    asset: assets.QuarantinedAsset,
    inspected: assets.InspectedAsset,
    request_paths: list[Path],
    *,
    root: Path | None = None,
    add_location: LocationWriter | None = None,
) -> DocumentStructure | None:
    """Persist one clean inspected structure and its block projection.

    A structure is a derived, immutable snapshot of clean bytes.  Quarantined,
    blocked, scanner-unavailable, or otherwise non-clean inspection results are
    deliberately a no-op: their source/quarantine records remain the only
    durable result and no structure or block is created.

    ``add_location`` lets a caller retain its existing API error mapping while
    keeping all payload, rendered-page, hash, and ORM materialization rules in
    this one helper.
    """

    if (
        inspected.safety_status != "safe"
        or inspected.scan_status != "clean"
        or inspected.processed is None
    ):
        return None

    source_content = session.get(ContentObject, document.content_object_id)
    if source_content is None or source_content.sha256 != asset.sha256:
        raise DocumentProcessingError("hash_mismatch", "문서 원문 hash가 일치하지 않습니다")

    existing = session.scalar(
        select(DocumentStructure).where(DocumentStructure.document_version_id == document.id)
    )
    if existing is not None:
        if existing.source_sha256 != asset.sha256 or existing.media_type != inspected.detected_mime:
            raise DocumentProcessingError("hash_mismatch", "기존 문서 구조의 원문 계보가 일치하지 않습니다")
        return existing

    processed = inspected.processed
    payload: dict[str, Any] = copy.deepcopy(dict(processed))
    payload["document_version_id"] = str(document.id)
    payload["structure_id"] = str(payload.get("structure_id") or uuid4())
    if payload.get("source_sha256") != asset.sha256:
        raise DocumentProcessingError("hash_mismatch", "문서 구조 원문 hash가 일치하지 않습니다")
    if payload.get("media_type") != inspected.detected_mime:
        raise DocumentProcessingError("hash_mismatch", "문서 구조 media type이 일치하지 않습니다")

    location_writer = add_location or (
        lambda current_session, content_id, namespace, path, digest: _add_location(
            current_session,
            content_id,
            namespace,
            path,
            digest,
            root=root,
        )
    )
    rendered_pages = getattr(processed, "rendered_pages", {}) or {}
    for page in payload.get("pages", []):
        image_id = page.get("image_content_object_id")
        rendered = rendered_pages.get(int(page["number"]))
        if image_id is not None and rendered:
            image_object = _store_generated_content(
                session,
                rendered,
                "image/png",
                root=root,
                request_paths=request_paths,
                add_location=location_writer,
            )
            page["image_content_object_id"] = str(image_object.id)

    validate_structure(payload)
    structure_path, payload_hash, _size = assets.store_structure_payload(payload, root=root)
    request_paths.append(structure_path)
    structure_object = _ensure_structure_content(session, payload_hash, payload)
    location_writer(session, structure_object.id, "structure", structure_path, payload_hash)
    structure = DocumentStructure(
        id=UUID(str(payload["structure_id"])),
        document_version_id=document.id,
        source_sha256=asset.sha256,
        media_type=inspected.detected_mime,
        extractor_name=str(payload["extractor"]["name"]),
        extractor_version=str(payload["extractor"]["version"]),
        upstream_commit=payload["extractor"].get("upstream_commit"),
        payload_content_object_id=structure_object.id,
        payload_sha256=payload_hash,
        page_count=len(payload.get("pages", [])),
        block_count=len(payload.get("blocks", [])),
        validation_status="ready",
    )
    session.add(structure)
    session.flush()
    for block in payload.get("blocks", []):
        session.add(
            DocumentBlock(
                structure_id=structure.id,
                block_key=block["block_key"],
                parent_block_key=block["parent_block_key"],
                block_type=block["type"],
                page=block["page"],
                bbox=block["bbox"],
                content=block["text"],
                confidence=block["confidence"],
                attributes=block["attributes"],
            )
        )
    # 구조 저장 직후에 결정적 segment·요구사항 inventory manifest를 만든다. 취득
    # worker와 수동 업로드가 이 helper 하나를 공유한다. 실패는 구조 저장을
    # 되돌리지 않고 savepoint 안에서 경고로 끝난다.
    session.flush()
    document_segments.ensure_manifest(session, payload)
    return structure


__all__ = ["LocationWriter", "materialize_structure"]
