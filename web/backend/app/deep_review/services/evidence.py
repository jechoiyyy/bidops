"""Safe, deep-review-scoped evidence projections for API #14."""

from __future__ import annotations

from collections.abc import Mapping
import math
import re
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ContentObject,
    ContentScan,
    DeepReview,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    EvidenceRef,
    ProfileEvidence,
)
from .document_bundles import BundleServiceError, DocumentBundleService


class EvidenceServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _safe_locator(locator_type: str, locator: Any) -> dict[str, Any]:
    """Return only the closed locator keys needed by the public view."""

    if not isinstance(locator, Mapping):
        raise EvidenceServiceError("evidence_out_of_scope", "근거 위치를 확인할 수 없습니다", status_code=403)
    allowed = {
        "page": {"page"},
        "paragraph": {"page", "block_key", "paragraph_key", "text_start", "text_end"},
        "table_cell": {"page", "block_key", "table_key", "row", "column"},
        "bbox": {"page", "block_key", "bbox"},
        "profile_fact": {"fact_key"},
    }.get(locator_type)
    if allowed is None or set(locator) != allowed:
        raise EvidenceServiceError("evidence_out_of_scope", "근거 위치를 확인할 수 없습니다", status_code=403)
    def integer(value: Any, *, minimum: int = 0) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= minimum

    page = locator.get("page")
    if locator_type in {"page", "paragraph", "table_cell", "bbox"} and not integer(page, minimum=1):
        raise EvidenceServiceError("evidence_out_of_scope", "근거 page가 올바르지 않습니다", status_code=403)
    if locator_type == "paragraph":
        if not isinstance(locator["block_key"], str) or not locator["block_key"].strip() or not isinstance(locator["paragraph_key"], (str, type(None))):
            raise EvidenceServiceError("evidence_out_of_scope", "paragraph locator가 올바르지 않습니다", status_code=403)
        if not all(value is None or integer(value) for value in (locator["text_start"], locator["text_end"])):
            raise EvidenceServiceError("evidence_out_of_scope", "paragraph offset이 올바르지 않습니다", status_code=403)
        if locator["text_start"] is not None and locator["text_end"] is not None and locator["text_start"] > locator["text_end"]:
            raise EvidenceServiceError("evidence_out_of_scope", "paragraph offset 순서가 올바르지 않습니다", status_code=403)
    elif locator_type == "table_cell":
        if not isinstance(locator["block_key"], str) or not locator["block_key"].strip() or not isinstance(locator["table_key"], str) or not locator["table_key"].strip() or not integer(locator["row"]) or not integer(locator["column"]):
            raise EvidenceServiceError("evidence_out_of_scope", "table-cell locator가 올바르지 않습니다", status_code=403)
    elif locator_type == "bbox":
        bbox = locator["bbox"]
        if not isinstance(bbox, list) or len(bbox) != 4 or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0 for value in bbox) or bbox[2] < bbox[0] or bbox[3] < bbox[1]:
            raise EvidenceServiceError("evidence_out_of_scope", "bbox locator가 올바르지 않습니다", status_code=403)
        if not isinstance(locator["block_key"], str) or not locator["block_key"].strip():
            raise EvidenceServiceError("evidence_out_of_scope", "bbox block locator가 올바르지 않습니다", status_code=403)
    elif locator_type == "profile_fact" and (not isinstance(locator["fact_key"], str) or not locator["fact_key"].strip()):
        raise EvidenceServiceError("evidence_out_of_scope", "profile fact locator가 올바르지 않습니다", status_code=403)
    return {key: locator[key] for key in sorted(allowed)}


def _safe_confidence(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
        raise EvidenceServiceError("evidence_out_of_scope", "근거 confidence가 올바르지 않습니다", status_code=403)
    return float(value)


def _safe_hash(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise EvidenceServiceError("evidence_out_of_scope", "근거 source hash가 올바르지 않습니다", status_code=403)
    return value


_UNSAFE_PAGE_KEY = re.compile(r"(?:path|url|uri|object|locator|credential|secret|token|password|shell)", re.I)


def _safe_page_attributes(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _safe_page_attributes(child)
            for key, child in value.items()
            if isinstance(key, str) and not _UNSAFE_PAGE_KEY.search(key)
        }
    if isinstance(value, list):
        return [_safe_page_attributes(child) for child in value]
    return value


def _safe_page_data(page: Any) -> dict[str, Any]:
    """Project a page without object locators, paths, or unsafe attributes."""

    if hasattr(page, "model_dump"):
        data = page.model_dump(mode="json")
    elif isinstance(page, Mapping):
        data = dict(page)
    else:
        raise EvidenceServiceError("unsafe_document", "문서 page projection을 확인할 수 없습니다", status_code=403)
    metadata = data.get("metadata")
    if not isinstance(metadata, Mapping):
        raise EvidenceServiceError("unsafe_document", "문서 page metadata를 확인할 수 없습니다", status_code=403)
    safe_metadata = _safe_page_attributes(metadata)
    if not isinstance(safe_metadata, Mapping):
        raise EvidenceServiceError("unsafe_document", "문서 page metadata를 확인할 수 없습니다", status_code=403)
    safe_metadata = dict(safe_metadata)
    safe_metadata["image_content_object_id"] = None
    blocks = data.get("blocks")
    if not isinstance(blocks, list):
        raise EvidenceServiceError("unsafe_document", "문서 page block을 확인할 수 없습니다", status_code=403)
    safe_blocks: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            raise EvidenceServiceError("unsafe_document", "문서 page block을 확인할 수 없습니다", status_code=403)
        safe_blocks.append({
            "block_key": block.get("block_key"),
            "parent_block_key": block.get("parent_block_key"),
            "type": block.get("type"), "page": block.get("page"),
            "bbox": block.get("bbox"), "text": block.get("text", ""),
            "confidence": block.get("confidence"),
            "attributes": _safe_page_attributes(block.get("attributes", {})),
        })
    return {
        "structure_id": data.get("structure_id"), "page": data.get("page"),
        "metadata": safe_metadata, "blocks": safe_blocks,
    }


def _resolve_locator_against_page(locator_type: str, locator: Mapping[str, Any], quote: str, page: Mapping[str, Any]) -> None:
    page_number = locator.get("page")
    if page.get("page") != page_number:
        raise EvidenceServiceError("evidence_out_of_scope", "근거 page가 구조 projection과 일치하지 않습니다", status_code=403)
    blocks = [item for item in page.get("blocks", []) if isinstance(item, Mapping)]
    if locator_type == "page":
        if not any(isinstance(item.get("text"), str) and quote in item["text"] for item in blocks):
            raise EvidenceServiceError("evidence_out_of_scope", "page 근거 quote를 확인할 수 없습니다", status_code=403)
        return
    block = next((item for item in blocks if item.get("block_key") == locator.get("block_key")), None)
    if block is None or block.get("page") != page_number:
        raise EvidenceServiceError("evidence_out_of_scope", "근거 block을 확인할 수 없습니다", status_code=403)
    text = block.get("text")
    if not isinstance(text, str) or quote not in text:
        raise EvidenceServiceError("evidence_out_of_scope", "근거 quote를 확인할 수 없습니다", status_code=403)
    attributes = block.get("attributes") if isinstance(block.get("attributes"), Mapping) else {}
    if locator_type == "paragraph":
        if locator.get("paragraph_key") is not None and attributes.get("paragraph_key") != locator.get("paragraph_key"):
            raise EvidenceServiceError("evidence_out_of_scope", "paragraph locator를 확인할 수 없습니다", status_code=403)
        start, end = locator.get("text_start"), locator.get("text_end")
        if start is not None and end is not None and (end > len(text) or text[start:end] != quote):
            raise EvidenceServiceError("evidence_out_of_scope", "paragraph offset을 확인할 수 없습니다", status_code=403)
    elif locator_type == "table_cell":
        if any(attributes.get(key) != locator.get(key) for key in ("table_key", "row", "column")):
            raise EvidenceServiceError("evidence_out_of_scope", "table-cell locator를 확인할 수 없습니다", status_code=403)
    elif locator_type == "bbox":
        block_bbox = block.get("bbox")
        cited_bbox = locator.get("bbox")
        if not isinstance(block_bbox, list) or not isinstance(cited_bbox, list) or len(block_bbox) != 4 or len(cited_bbox) != 4 or any(cited_bbox[index] < block_bbox[index] for index in (0, 1)) or any(cited_bbox[index] > block_bbox[index] for index in (2, 3)):
            raise EvidenceServiceError("evidence_out_of_scope", "bbox locator를 확인할 수 없습니다", status_code=403)


class EvidenceService:
    """Resolve evidence only through the review's immutable scope joins."""

    def __init__(self, *, document_service: DocumentBundleService | None = None) -> None:
        self.document_service = document_service or DocumentBundleService()

    def get(self, session: Session, evidence_id: UUID) -> dict[str, Any]:
        evidence = session.get(EvidenceRef, evidence_id)
        if evidence is None:
            raise EvidenceServiceError("not_found", "근거를 찾을 수 없습니다", status_code=404)
        review = session.get(DeepReview, evidence.deep_review_id)
        if review is None:
            raise EvidenceServiceError("evidence_out_of_scope", "근거 범위를 확인할 수 없습니다", status_code=403)
        if evidence.notice_id != review.notice_id:
            raise EvidenceServiceError("evidence_out_of_scope", "다른 공고의 근거입니다", status_code=403)
        if not evidence.quote or not evidence.source_sha256:
            raise EvidenceServiceError("evidence_out_of_scope", "근거를 확인할 수 없습니다", status_code=403)
        _safe_hash(evidence.source_sha256)
        _safe_confidence(evidence.confidence)

        if evidence.source_kind == "document":
            return self._document_view(session, review, evidence)
        if evidence.source_kind == "profile":
            return self._profile_view(session, review, evidence)
        raise EvidenceServiceError("evidence_out_of_scope", "근거 범위를 확인할 수 없습니다", status_code=403)

    def _document_view(self, session: Session, review: DeepReview, evidence: EvidenceRef) -> dict[str, Any]:
        if any(value is None for value in (evidence.bundle_id, evidence.document_version_id, evidence.structure_id)):
            raise EvidenceServiceError("evidence_out_of_scope", "문서 근거 범위를 확인할 수 없습니다", status_code=403)
        if evidence.profile_version_id is not None or evidence.profile_evidence_id is not None:
            raise EvidenceServiceError("evidence_out_of_scope", "문서 근거 범위를 확인할 수 없습니다", status_code=403)
        if evidence.bundle_id != review.bundle_id:
            raise EvidenceServiceError("evidence_out_of_scope", "다른 document bundle의 근거입니다", status_code=403)
        bundle = session.get(DocumentBundle, review.bundle_id)
        item = session.scalar(select(DocumentBundleItem).where(
            DocumentBundleItem.bundle_id == review.bundle_id,
            DocumentBundleItem.document_version_id == evidence.document_version_id,
            DocumentBundleItem.structure_id_at_confirmation == evidence.structure_id,
        ))
        document = session.get(DocumentVersion, evidence.document_version_id)
        structure = session.get(DocumentStructure, evidence.structure_id)
        if bundle is None or bundle.notice_id != review.notice_id or item is None:
            raise EvidenceServiceError("evidence_out_of_scope", "ready bundle 범위 밖의 근거입니다", status_code=403)
        if bundle.status != "ready":
            raise EvidenceServiceError("unsafe_document", "안전 검사를 통과하지 못한 문서입니다", status_code=403)
        content = session.get(ContentObject, document.content_object_id) if document is not None else None
        payload_content = session.get(ContentObject, structure.payload_content_object_id) if structure is not None else None
        latest_scan = session.scalar(select(ContentScan).where(
            ContentScan.content_object_id == document.content_object_id,
        ).order_by(ContentScan.scanned_at.desc(), ContentScan.id.desc()).limit(1)) if document is not None else None
        if document is None or structure is None or content is None or payload_content is None or document.notice_id != review.notice_id or document.safety_status != "safe" or structure.validation_status != "ready" or latest_scan is None or latest_scan.status != "clean":
            raise EvidenceServiceError("unsafe_document", "안전 검사를 통과하지 못한 문서입니다", status_code=403)
        if (
            item.document_version_version != document.version
            or item.content_object_id != document.content_object_id
            or item.content_sha256 != content.sha256
            or item.size_bytes != content.size_bytes
            or item.detected_mime != content.detected_mime
            or structure.document_version_id != document.id
            or structure.source_sha256 != content.sha256
            or structure.source_sha256 != evidence.source_sha256
            or item.structure_id_at_confirmation != structure.id
            or item.structure_payload_sha256 != structure.payload_sha256
            or payload_content.sha256 != structure.payload_sha256
        ):
            raise EvidenceServiceError("evidence_out_of_scope", "문서 근거 해시가 bundle과 일치하지 않습니다", status_code=403)
        if item.content_sha256 != evidence.source_sha256:
            raise EvidenceServiceError("evidence_out_of_scope", "문서 근거가 확인된 bundle과 일치하지 않습니다", status_code=403)
        if item.safety_status_at_confirmation != "safe":
            raise EvidenceServiceError("unsafe_document", "안전 검사를 통과하지 못한 문서입니다", status_code=403)

        locator = _safe_locator(evidence.locator_type, evidence.locator)
        try:
            page_number = int(locator.get("page", 0))
            page = self.document_service.get_structure_page(session, structure.id, page_number)
        except BundleServiceError as error:
            code = "unsafe_document" if error.code in {"unsafe_document", "structure_unavailable"} else "not_found"
            status = 403 if code == "unsafe_document" else 404
            raise EvidenceServiceError(code, "문서 근거를 확인할 수 없습니다", status_code=status) from error
        page_data = _safe_page_data(page)
        _resolve_locator_against_page(evidence.locator_type, locator, evidence.quote, page_data)
        return {
            "evidence_id": evidence.id,
            "source_kind": "document",
            "document_version_id": document.id,
            "structure_id": structure.id,
            "profile_version_id": None,
            "profile_evidence_id": None,
            "locator_type": evidence.locator_type,
            "locator": locator,
            "quote": evidence.quote,
            "confidence": _safe_confidence(evidence.confidence),
            "source_sha256": evidence.source_sha256,
            "page": page_data,
        }

    def _profile_view(self, session: Session, review: DeepReview, evidence: EvidenceRef) -> dict[str, Any]:
        if any(value is not None for value in (evidence.bundle_id, evidence.document_version_id, evidence.structure_id)):
            raise EvidenceServiceError("evidence_out_of_scope", "프로필 근거 범위를 확인할 수 없습니다", status_code=403)
        if evidence.profile_version_id != review.profile_version_id or evidence.profile_evidence_id is None:
            raise EvidenceServiceError("evidence_out_of_scope", "고정된 profile 범위 밖의 근거입니다", status_code=403)
        profile_evidence = session.scalar(select(ProfileEvidence).where(
            ProfileEvidence.profile_version_id == review.profile_version_id,
            ProfileEvidence.id == evidence.profile_evidence_id,
        ))
        if profile_evidence is None or profile_evidence.locator_type != "profile_fact":
            raise EvidenceServiceError("evidence_out_of_scope", "profile fact 근거를 확인할 수 없습니다", status_code=403)
        locator = _safe_locator(evidence.locator_type, evidence.locator)
        profile_locator = _safe_locator(profile_evidence.locator_type, profile_evidence.locator)
        if locator != profile_locator or locator.get("fact_key") != profile_evidence.fact_key or profile_evidence.source_sha256 != evidence.source_sha256 or profile_evidence.quote != evidence.quote:
            raise EvidenceServiceError("evidence_out_of_scope", "profile fact 근거가 고정된 사실과 일치하지 않습니다", status_code=403)
        return {
            "evidence_id": evidence.id,
            "source_kind": "profile",
            "document_version_id": None,
            "structure_id": None,
            "profile_version_id": profile_evidence.profile_version_id,
            "profile_evidence_id": profile_evidence.id,
            "locator_type": "profile_fact",
            "locator": locator,
            "quote": profile_evidence.quote,
            "confidence": _safe_confidence(evidence.confidence),
            "source_sha256": profile_evidence.source_sha256,
            "page": None,
        }


__all__ = ["EvidenceService", "EvidenceServiceError"]
