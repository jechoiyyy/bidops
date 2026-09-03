"""Document-version and immutable-ready-bundle service.

The service owns the state transition from an asset's quarantine record to a
document version and finally to a locked bundle snapshot.  It intentionally
does not enqueue deep-review work; T5/T7 own that boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_from_bytes, unquote_to_bytes
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..document_mcp.contracts import validate_structure
from ..document_mcp.processor import ClamAVChecker, DocumentProcessor
from ..models import (
    Attachment,
    AuditEvent,
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    IdempotencyRecord,
    Judgment,
    Notice,
    Review,
)
from ..schemas.document_bundles import (
    BundleIssue,
    BundleListResponse,
    BundleView,
    ConfirmRequest,
    DocumentStructure as DocumentStructureSchema,
    DocumentStructurePageView,
    DocumentVersionView,
    PatchDocumentVersionRequest,
)
from . import assets
from .document_converter import ScratchDocumentProcessor
from .document_structures import materialize_structure
from .prespec_overview import prepare_overview_review
from ..core.api_errors import (
    API_ERROR_CODES,
    MAX_ACTOR_NAME,
    UTF8_ACTOR_FORMAT,
    UTF8_ACTOR_PREFIX,
    BundleServiceError,
    stable_api_error,
    validate_actor,
)

CREATE_BUNDLE_RETRIES = 3
DOCUMENT_ROLES = {"공고", "정정", "제안요청서", "과업지시서", "내역서", "제출서식", "부록", "기타"}


def _prepare_pre_spec_overview(
    session: Session,
    notice_id: int,
    *,
    root: Path | None,
) -> None:
    """Materialize T-23 state only for a pre-spec notice.

    ``DocumentBundleService`` also handles generic/manual notices.  Those
    callers must not accidentally create an unrelated overview review row.
    """

    notice = session.get(Notice, notice_id)
    if notice is not None and notice.source_type == "pre_spec":
        prepare_overview_review(session, notice_id, root=root)




def map_asset_error(error: assets.AssetError) -> BundleServiceError:
    code, message = stable_api_error(error.code)
    status_code = 503 if code == "service_unavailable" else (500 if code == "processing_failed" else 400)
    return BundleServiceError(code, message, status_code=status_code)



@dataclass(frozen=True)
class _ProviderAttachmentSnapshot:
    """Safe, immutable source metadata carried across provider I/O."""

    bundle_notice_id: int
    bundle_status: str
    attachment_id: int
    notice_id: int
    name: str | None
    source_system: str | None
    source_attachment_key: str | None
    source_url: str | None
    retired: bool


@dataclass(frozen=True)
class _LegacyAttachmentSnapshot:
    """Plain-data snapshot carried across legacy filesystem/processor I/O."""

    bundle_id: UUID
    bundle_notice_id: int
    bundle_revision: int
    bundle_version: int
    bundle_status: str
    bundle_supersedes_bundle_id: UUID | None
    bundle_created_by_name: str | None
    bundle_confirmed_by_name: str | None
    bundle_confirmed_at: datetime | None
    bundle_created_at: datetime
    bundle_issues_hash: str
    attachment_id: int
    attachment_notice_id: int
    attachment_name: str | None
    attachment_source_url: str | None
    attachment_origin: str | None
    attachment_file_ext: str | None
    attachment_size_bytes: int | None
    attachment_legacy_stored_path: str | None
    attachment_extract_status: str | None
    attachment_created_at: datetime
    attachment_source_system: str | None
    attachment_source_attachment_key: str | None
    attachment_last_seen_at: datetime | None
    attachment_retired_at: datetime | None
    attachment_retired_reason: str | None
    attachment_retired_by_name: str | None


def _provider_scope_matches(
    snapshot: _ProviderAttachmentSnapshot,
    bundle: DocumentBundle,
    attachment: Attachment,
) -> bool:
    """Compare every provider scope field captured before external I/O."""

    return (
        bundle.notice_id == snapshot.bundle_notice_id
        and bundle.status == snapshot.bundle_status
        and attachment.id == snapshot.attachment_id
        and attachment.notice_id == snapshot.notice_id
        and attachment.name == snapshot.name
        and attachment.source_system == snapshot.source_system
        and attachment.source_attachment_key == snapshot.source_attachment_key
        and attachment.source_url == snapshot.source_url
        and (attachment.retired_at is not None) == snapshot.retired
    )


def _legacy_scope_matches(
    snapshot: _LegacyAttachmentSnapshot,
    bundle: DocumentBundle,
    attachment: Attachment,
) -> bool:
    """Compare the complete source/bundle snapshot before any DB write."""

    return (
        bundle.id == snapshot.bundle_id
        and bundle.notice_id == snapshot.bundle_notice_id
        and bundle.revision == snapshot.bundle_revision
        and bundle.version == snapshot.bundle_version
        and bundle.status == snapshot.bundle_status
        and bundle.supersedes_bundle_id == snapshot.bundle_supersedes_bundle_id
        and bundle.created_by_name == snapshot.bundle_created_by_name
        and bundle.confirmed_by_name == snapshot.bundle_confirmed_by_name
        and bundle.confirmed_at == snapshot.bundle_confirmed_at
        and bundle.created_at == snapshot.bundle_created_at
        and _canonical_hash(bundle.issues_snapshot) == snapshot.bundle_issues_hash
        and attachment.id == snapshot.attachment_id
        and attachment.notice_id == snapshot.attachment_notice_id
        and attachment.name == snapshot.attachment_name
        and attachment.source_url == snapshot.attachment_source_url
        and attachment.origin == snapshot.attachment_origin
        and attachment.file_ext == snapshot.attachment_file_ext
        and attachment.size_bytes == snapshot.attachment_size_bytes
        and attachment.legacy_stored_path == snapshot.attachment_legacy_stored_path
        and attachment.extract_status == snapshot.attachment_extract_status
        and attachment.created_at == snapshot.attachment_created_at
        and attachment.source_system == snapshot.attachment_source_system
        and attachment.source_attachment_key == snapshot.attachment_source_attachment_key
        and attachment.last_seen_at == snapshot.attachment_last_seen_at
        and attachment.retired_at == snapshot.attachment_retired_at
        and attachment.retired_reason == snapshot.attachment_retired_reason
        and attachment.retired_by_name == snapshot.attachment_retired_by_name
    )




def _now() -> datetime:
    return datetime.now(UTC)


def _error_issue(
    code: str,
    message: str,
    *,
    document_version_id: UUID | None = None,
    blocking: bool = True,
    severity: str = "차단",
) -> dict[str, Any]:
    return {
        "issue_id": f"{code}:{document_version_id or 'bundle'}",
        "code": code,
        "severity": severity,
        "blocking": blocking,
        "document_version_id": str(document_version_id) if document_version_id else None,
        "message": message,
        "locator_type": "none",
        "locator": None,
    }


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def document_bundle_snapshot_hash(
    bundle: DocumentBundle,
    items: Iterable[DocumentBundleItem],
) -> str | None:
    """Hash the immutable ready snapshot used by agent artifact refs."""

    if bundle.status not in {"ready", "superseded"}:
        return None
    canonical_documents = [
        {
            "document_version_id": str(item.document_version_id),
            "document_version_version": item.document_version_version,
            "ordinal": item.ordinal,
            "content_sha256": item.content_sha256,
            "detected_mime": item.detected_mime,
            "size_bytes": item.size_bytes,
            "role_at_confirmation": item.role_at_confirmation,
            "effective_date_at_confirmation": item.effective_date_at_confirmation.isoformat() if item.effective_date_at_confirmation else None,
            "replaces_id_at_confirmation": str(item.replaces_id_at_confirmation) if item.replaces_id_at_confirmation else None,
            "is_current_at_confirmation": item.is_current_at_confirmation,
            "safety_status_at_confirmation": item.safety_status_at_confirmation,
            "structure_id_at_confirmation": str(item.structure_id_at_confirmation),
            "structure_payload_sha256": item.structure_payload_sha256,
        }
        for item in sorted(items, key=lambda row: (row.ordinal, str(row.document_version_id)))
    ]
    return _canonical_hash(
        {
            "schema": "bidops.document-bundle.v1",
            "bundle_id": str(bundle.id),
            "notice_id": bundle.notice_id,
            "revision": bundle.revision,
            # Superseding a ready bundle changes only which revision is current;
            # the immutable handoff snapshot retains its original ready hash.
            "status": "ready",
            "version": bundle.version,
            "documents": canonical_documents,
            "issues": bundle.issues_snapshot if isinstance(bundle.issues_snapshot, list) else [],
            "confirmed_by": bundle.confirmed_by_name,
            "confirmed_at": bundle.confirmed_at.isoformat() if bundle.confirmed_at else None,
            "created_at": bundle.created_at.isoformat(),
        }
    )


def _uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _as_uuid(value: UUID | str | None) -> UUID | None:
    return None if value is None else _uuid(value)


class DocumentBundleService:
    """T3 application service; one instance may be configured in tests."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        processor: DocumentProcessor | None = None,
        clamav_checker: ClamAVChecker | None = None,
        converter: ScratchDocumentProcessor | None = None,
    ) -> None:
        self.root = root
        self.processor = processor
        self.clamav_checker = clamav_checker
        self.converter = converter or ScratchDocumentProcessor(clamav_checker=clamav_checker)

    # ------------------------------------------------------------------
    # ORM projection helpers
    # ------------------------------------------------------------------

    def _structure_for(self, session: Session, document_version_id: UUID) -> DocumentStructure | None:
        return session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document_version_id))

    def _document_status(self, session: Session, document: DocumentVersion) -> str:
        structure = self._structure_for(session, document.id)
        if structure is None:
            return "pending" if document.safety_status in {"quarantined", "scanning"} else "failed"
        return structure.validation_status

    def _bundle_documents(self, session: Session, bundle: DocumentBundle) -> list[DocumentVersionView]:
        # A ready (or superseded) bundle is an immutable input snapshot.  Do
        # not even require the live document row to exist when projecting it:
        # the snapshot is the source of truth for historical views.
        items = session.scalars(
            select(DocumentBundleItem)
            .where(DocumentBundleItem.bundle_id == bundle.id)
            .order_by(DocumentBundleItem.ordinal.asc(), DocumentBundleItem.document_version_id.asc())
        ).all()
        if bundle.status in {"ready", "superseded"}:
            return [self._snapshot_document_view(item, bundle.id) for item in items]

        # Drafts intentionally remain a live projection.  Bundle items are a
        # convenient staging aid, but cannot hide a current document whose
        # structure is still pending or unavailable.
        live_documents = session.scalars(
            select(DocumentVersion)
            .join(Attachment, Attachment.id == DocumentVersion.attachment_id)
            .where(
                DocumentVersion.notice_id == bundle.notice_id,
                DocumentVersion.is_current.is_(True),
                Attachment.retired_at.is_(None),
            )
            .order_by(DocumentVersion.created_at.asc(), DocumentVersion.id.asc())
        ).all()
        return [self._document_view(document, bundle.id, session) for document in live_documents]

    def _snapshot_document_view(self, item: DocumentBundleItem, bundle_id: UUID) -> DocumentVersionView:
        """Project only confirmation-time fields for immutable bundle views."""

        structure_status = "ready" if item.structure_id_at_confirmation and item.structure_payload_sha256 else "failed"
        return DocumentVersionView(
            id=item.document_version_id,
            bundle_id=bundle_id,
            version=item.document_version_version,
            role=item.role_at_confirmation,
            effective_date=item.effective_date_at_confirmation,
            replaces_document_version_id=item.replaces_id_at_confirmation,
            is_current=item.is_current_at_confirmation,
            safety_status=item.safety_status_at_confirmation,
            structure_status=structure_status,
            original_filename=item.original_filename,
        )

    def _document_view(self, document: DocumentVersion, bundle_id: UUID, session: Session) -> DocumentVersionView:
        return DocumentVersionView(
            id=document.id,
            bundle_id=bundle_id,
            version=document.version,
            role=document.role,
            effective_date=document.effective_date,
            replaces_document_version_id=document.replaces_document_version_id,
            is_current=document.is_current,
            safety_status=document.safety_status,
            structure_status=self._document_status(session, document),
            original_filename=document.original_filename,
        )

    def _issues(self, session: Session, bundle: DocumentBundle) -> list[dict[str, Any]]:
        notice = session.get(Notice, bundle.notice_id)
        if notice is None:
            return [_error_issue("not_found", "공고를 찾을 수 없습니다")]
        attachments = session.scalars(
            select(Attachment).where(Attachment.notice_id == notice.id, Attachment.retired_at.is_(None)).order_by(Attachment.id.asc())
        ).all()
        documents = session.scalars(
            select(DocumentVersion).where(DocumentVersion.notice_id == notice.id).order_by(DocumentVersion.created_at.asc(), DocumentVersion.id.asc())
        ).all()
        by_attachment: dict[int, list[DocumentVersion]] = {}
        for document in documents:
            if document.attachment_id is not None:
                by_attachment.setdefault(document.attachment_id, []).append(document)

        issues: list[dict[str, Any]] = []
        current_documents: list[DocumentVersion] = []
        for attachment in attachments:
            candidates = [item for item in by_attachment.get(attachment.id, []) if item.is_current]
            if attachment.extract_status and attachment.extract_status.startswith("provider_"):
                # Keep a provider connector failure blocking even when the
                # acquisition stopped before a DocumentVersion could be
                # created.  This must be recorded before the no-document
                # branch below, otherwise a failed URL-only attachment can
                # look like an ordinary missing document.
                current = candidates[-1] if candidates else None
                issues.append(
                    _error_issue(
                        "provider_acquisition_failed",
                        "provider 원문 취득이 완료되지 않았습니다",
                        document_version_id=current.id if current else None,
                    )
                )
            if attachment.extract_status == "legacy_acquisition_failed":
                current = candidates[-1] if candidates else None
                issues.append(
                    _error_issue(
                        "legacy_acquisition_failed",
                        "기존 첨부 원문 취득이 완료되지 않았습니다",
                        document_version_id=current.id if current else None,
                    )
                )
            if not candidates:
                issues.append(_error_issue("attachment_bytes_missing", "모든 non-retired 첨부의 원문과 문서 version이 필요합니다"))
                continue
            if len(candidates) > 1:
                issues.append(_error_issue("multiple_current_versions", "첨부에 current 문서 version이 여러 개입니다"))
            document = candidates[-1]
            current_documents.append(document)
            if document.source_kind == "provider":
                if (
                    document.source_system != attachment.source_system
                    or document.source_attachment_key != attachment.source_attachment_key
                    or document.source_url != attachment.source_url
                ):
                    issues.append(_error_issue("source_changed", "provider 첨부 source snapshot이 변경되었습니다", document_version_id=document.id))
            if attachment.name != document.original_filename:
                issues.append(_error_issue("source_changed", "첨부 파일명이 document snapshot과 다릅니다", document_version_id=document.id))
            if attachment.size_bytes is not None:
                content = session.get(ContentObject, document.content_object_id)
                if content is None or int(attachment.size_bytes) != int(content.size_bytes):
                    issues.append(_error_issue("source_changed", "첨부 원문 크기가 document snapshot과 다릅니다", document_version_id=document.id))
            content = session.get(ContentObject, document.content_object_id)
            if content is None or not self._source_location_matches(session, content):
                issues.append(_error_issue("source_hash_mismatch", "source location hash가 document snapshot과 다릅니다", document_version_id=document.id))
            if content is None or not self._latest_scan_clean(session, content.id):
                issues.append(_error_issue("unsafe_document", "최신 content scan이 clean이 아닙니다", document_version_id=document.id))
            if document.safety_status != "safe":
                code = "quarantine_document" if document.safety_status == "quarantined" else "unsafe_document"
                issues.append(_error_issue(code, "안전 검사를 통과하지 못한 문서는 ready가 될 수 없습니다", document_version_id=document.id))
            structure = self._structure_for(session, document.id)
            if structure is None or structure.validation_status != "ready":
                issues.append(_error_issue("structure_unavailable", "문서 구조가 준비되지 않았습니다", document_version_id=document.id))
            else:
                if content is None or structure.source_sha256 != content.sha256 or structure.media_type != content.detected_mime:
                    issues.append(_error_issue("structure_unavailable", "문서 구조의 원문 계보가 일치하지 않습니다", document_version_id=document.id))
                payload = self._load_structure_payload(session, structure, allow_unsafe=True)
                if payload is None:
                    # A missing, malformed, or hash/lineage-mismatched
                    # payload is a blocking issue; silently skipping it would
                    # let confirm manufacture an apparently complete bundle.
                    issues.append(_error_issue("structure_unavailable", "문서 구조 payload를 검증할 수 없습니다", document_version_id=document.id))
                else:
                    warnings = set(payload.get("warnings", []))
                    if warnings & {"ocr_unavailable", "ocr_failed", "needs_review", "page_render_unavailable"}:
                        issues.append(_error_issue("ocr_issue", "OCR 또는 page 구조화 확인이 필요합니다", document_version_id=document.id))
                    for block in payload.get("blocks", []):
                        confidence = block.get("confidence")
                        if isinstance(confidence, (float, int)) and confidence < 0.5:
                            issues.append(_error_issue("ocr_low_confidence", "낮은 OCR confidence는 확정 사실로 사용할 수 없습니다", document_version_id=document.id, blocking=False, severity="보통"))
                            break
            if document.replaces_document_version_id is not None:
                replaced = session.get(DocumentVersion, document.replaces_document_version_id)
                if replaced is None or replaced.notice_id != notice.id:
                    issues.append(_error_issue("invalid_replaces_reference", "대체 문서 version이 같은 공고에 속하지 않습니다", document_version_id=document.id))

        # A draft can be created before any attachment exists.  It remains a
        # valid draft, but confirm still requires at least one covered document.
        if not attachments:
            issues.append(_error_issue("attachment_bytes_missing", "확인 시점에 다뤄야 할 첨부가 없습니다"))
        return _dedupe_issues(issues)

    def _load_structure_payload(self, session: Session, structure: DocumentStructure, *, allow_unsafe: bool = False) -> dict[str, Any] | None:
        document = session.get(DocumentVersion, structure.document_version_id)
        if document is None or (not allow_unsafe and document.safety_status != "safe"):
            return None
        content = session.get(ContentObject, document.content_object_id)
        if content is None:
            return None
        if not allow_unsafe:
            # A viewer must re-check the live safety projection instead of
            # trusting a stale document version or structure row.
            if not self._latest_scan_clean(session, content.id):
                return None
            if (
                structure.source_sha256 != content.sha256
                or structure.media_type != content.detected_mime
                or not self._source_location_matches(session, content)
            ):
                return None
        location = session.scalar(
            select(ContentObjectLocation)
            .where(
                ContentObjectLocation.content_object_id == structure.payload_content_object_id,
                ContentObjectLocation.namespace_key == "structure",
                ContentObjectLocation.status == "verified",
            )
            .order_by(ContentObjectLocation.created_at.desc(), ContentObjectLocation.id.desc())
        )
        if location is None:
            return None
        try:
            raw, object_metadata = assets.read_object("structure", location.object_key, root=self.root)
            payload_object = session.get(ContentObject, structure.payload_content_object_id)
            if (
                payload_object is None
                or payload_object.sha256 != structure.payload_sha256
                or len(raw) != payload_object.size_bytes
                or hashlib.sha256(raw).hexdigest() != structure.payload_sha256
                or location.etag != object_metadata.etag
                or location.object_version_id != object_metadata.object_version_id
            ):
                return None
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                return None
            if (
                payload.get("document_version_id") != str(document.id)
                or payload.get("structure_id") != str(structure.id)
                or payload.get("source_sha256") != structure.source_sha256
            ):
                return None
            # The JSON payload is authoritative, so lineage checks above are
            # not enough: a syntactically valid but contract-invalid payload
            # must also fail closed before it can influence ready validation.
            validate_structure(payload)
            return payload
        except (assets.AssetError, OSError, UnicodeError, ValueError, json.JSONDecodeError, RuntimeError):
            return None

    def _latest_scan_clean(self, session: Session, content_id: UUID) -> bool:
        scan = session.scalar(
            select(ContentScan)
            .where(ContentScan.content_object_id == content_id)
            .order_by(ContentScan.scanned_at.desc(), ContentScan.id.desc())
            .limit(1)
        )
        return scan is not None and scan.status == "clean"

    def _source_location_matches(self, session: Session, content: ContentObject) -> bool:
        location = session.scalar(
            select(ContentObjectLocation)
            .where(
                ContentObjectLocation.content_object_id == content.id,
                ContentObjectLocation.namespace_key == "source",
                ContentObjectLocation.status == "verified",
            )
            .order_by(ContentObjectLocation.created_at.desc(), ContentObjectLocation.id.desc())
        )
        if location is None:
            return False
        try:
            raw, object_metadata = assets.read_object("source", location.object_key, root=self.root)
        except (assets.AssetError, OSError, ValueError):
            return False
        return (
            location.etag == object_metadata.etag
            and location.object_version_id == object_metadata.object_version_id
            and len(raw) == content.size_bytes
            and hashlib.sha256(raw).hexdigest() == content.sha256
        )

    def _bundle_view(self, session: Session, bundle: DocumentBundle) -> BundleView:
        # Only confirmed bundles expose their frozen issue list.  Draft views
        # must reflect the current attachment/document safety projection.
        issues = (
            _dedupe_issues(bundle.issues_snapshot if isinstance(bundle.issues_snapshot, list) else [])
            if bundle.status in {"ready", "superseded"}
            else self._issues(session, bundle)
        )
        return BundleView(
            id=bundle.id,
            notice_id=bundle.notice_id,
            revision=bundle.revision,
            version=bundle.version,
            status=bundle.status,
            documents=self._bundle_documents(session, bundle),
            issues=[BundleIssue.model_validate(item) for item in issues],
            confirmed_by=bundle.confirmed_by_name,
            confirmed_at=bundle.confirmed_at,
            created_at=bundle.created_at,
        )

    # ------------------------------------------------------------------
    # Business operations
    # ------------------------------------------------------------------

    def _notice_or_error(self, session: Session, notice_id: int) -> Notice:
        notice = session.get(Notice, notice_id)
        if notice is None:
            raise BundleServiceError("not_found", "공고를 찾을 수 없습니다", status_code=404)
        return notice

    def effective_grade(self, session: Session, notice_id: int) -> str | None:
        notice = self._notice_or_error(session, notice_id)
        judgment = session.scalar(select(Judgment).where(Judgment.notice_id == notice.id))
        system_grade = judgment.grade if judgment else None
        human_grade = session.scalar(
            select(Review.corrected_grade)
            .where(Review.notice_id == notice.id, Review.corrected_grade.is_not(None))
            .order_by(Review.updated_at.desc(), Review.id.desc())
            .limit(1)
        )
        return human_grade or system_grade

    def list_bundles(self, session: Session, notice_id: int) -> BundleListResponse:
        self._notice_or_error(session, notice_id)
        bundles = session.scalars(select(DocumentBundle).where(DocumentBundle.notice_id == notice_id).order_by(DocumentBundle.revision.desc())).all()
        return BundleListResponse(items=[self._bundle_view(session, bundle) for bundle in bundles])

    def _bundle_creation_audit(self, session: Session, bundle: DocumentBundle) -> AuditEvent | None:
        rows = session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.action == "document_bundle.create",
                AuditEvent.aggregate_type == "document_bundle",
                AuditEvent.aggregate_id == str(bundle.id),
            )
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            .limit(2)
        ).all()
        if len(rows) > 1:
            raise BundleServiceError(
                "processing_failed",
                "문서 bundle creation audit이 올바르지 않습니다",
                status_code=500,
            )
        return rows[0] if rows else None

    def _bundle_correlation_id(self, session: Session, bundle: DocumentBundle) -> UUID | None:
        """Read the immutable creation lineage without backfilling legacy rows."""

        creation = self._bundle_creation_audit(session, bundle)
        metadata = creation.safe_metadata if creation is not None and isinstance(creation.safe_metadata, Mapping) else {}
        if "correlation_id" not in metadata:
            return None
        value = metadata.get("correlation_id")
        try:
            if value is None:
                raise ValueError("null correlation")
            return value if isinstance(value, UUID) else UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise BundleServiceError(
                "processing_failed",
                "문서 bundle 계보를 확인할 수 없습니다",
                status_code=500,
            ) from exc

    @staticmethod
    def _lineage_metadata(correlation_id: UUID | None) -> dict[str, str | None]:
        return {"correlation_id": str(correlation_id) if correlation_id is not None else None}

    def create_bundle(
        self,
        session: Session,
        notice_id: int,
        actor: str,
        *,
        correlation_id: UUID | None = None,
    ) -> BundleView:
        claimed_name = validate_actor(actor)
        for attempt in range(CREATE_BUNDLE_RETRIES):
            # The notice is the allocation aggregate for bundle revisions.
            # Lock it before every latest-revision read; an unexpected unique
            # collision is retried after the failed transaction is rolled back
            # instead of leaking an endpoint-2 version_conflict response.
            session.rollback()
            notice = session.scalar(
                select(Notice)
                .where(Notice.id == notice_id)
                .with_for_update()
            )
            if notice is None:
                raise BundleServiceError("not_found", "공고를 찾을 수 없습니다", status_code=404)
            effective_grade_at_start = self.effective_grade(session, notice.id)
            if effective_grade_at_start != "우선 검토":
                raise BundleServiceError("effective_grade_ineligible", "우선 검토 공고만 문서 bundle을 만들 수 있습니다", status_code=403)
            previous = session.scalar(select(DocumentBundle).where(DocumentBundle.notice_id == notice.id).order_by(DocumentBundle.revision.desc()).limit(1))
            revision = (previous.revision + 1) if previous else 1
            bundle = DocumentBundle(
                id=uuid4(),
                notice_id=notice.id,
                revision=revision,
                version=1,
                status="draft",
                supersedes_bundle_id=previous.id if previous else None,
                issues_snapshot=[],
                created_by_name=claimed_name,
            )
            try:
                session.add(bundle)
                session.flush()
                self._seed_bundle_items(session, bundle)
                bundle.issues_snapshot = self._issues(session, bundle)
                session.add(
                    AuditEvent(
                        actor_kind="human",
                        claimed_name=claimed_name,
                        action="document_bundle.create",
                        aggregate_type="document_bundle",
                        aggregate_id=str(bundle.id),
                        safe_metadata={
                            "notice_id": notice.id,
                            "revision": revision,
                            "effective_grade_at_start": effective_grade_at_start,
                            **(
                                {"correlation_id": str(correlation_id)}
                                if correlation_id is not None
                                else {}
                            ),
                        },
                    )
                )
                session.commit()
                session.refresh(bundle)
                return self._bundle_view(session, bundle)
            except IntegrityError as exc:
                session.rollback()
                if attempt + 1 < CREATE_BUNDLE_RETRIES:
                    continue
                raise BundleServiceError("processing_failed", "문서 bundle을 만들 수 없습니다", status_code=500) from exc
        # The loop either returns or raises after the final collision.
        raise BundleServiceError("processing_failed", "문서 bundle을 만들 수 없습니다", status_code=500)

    def _seed_bundle_items(self, session: Session, bundle: DocumentBundle) -> None:
        documents = session.scalars(
            select(DocumentVersion)
            .join(Attachment, Attachment.id == DocumentVersion.attachment_id)
            .where(
                DocumentVersion.notice_id == bundle.notice_id,
                DocumentVersion.is_current.is_(True),
                Attachment.retired_at.is_(None),
            )
            .order_by(DocumentVersion.created_at.asc(), DocumentVersion.id.asc())
        ).all()
        existing_items = session.scalars(select(DocumentBundleItem).where(DocumentBundleItem.bundle_id == bundle.id)).all()
        for item in existing_items:
            # Draft items are a live projection.  Recreate the projection in
            # canonical order rather than updating ordinals in place: an
            # immediate (bundle_id, ordinal) unique constraint cannot permit
            # transient swaps.  Ready item rows are never passed here.
            session.delete(item)
        if existing_items:
            session.flush()

        ordinal = 0
        for document in documents:
            structure = self._structure_for(session, document.id)
            if structure is None:
                continue
            content = session.get(ContentObject, document.content_object_id)
            if content is None:
                continue
            payload = self._load_structure_payload(session, structure, allow_unsafe=True)
            payload_hash = structure.payload_sha256 if payload is not None else "0" * 64
            session.add(
                DocumentBundleItem(
                    bundle_id=bundle.id,
                    document_version_id=document.id,
                    ordinal=ordinal,
                    document_version_version=document.version,
                    content_object_id=document.content_object_id,
                    content_sha256=content.sha256,
                    detected_mime=content.detected_mime,
                    size_bytes=content.size_bytes,
                    original_filename=document.original_filename,
                    source_kind=document.source_kind,
                    source_system=document.source_system,
                    source_attachment_key=document.source_attachment_key,
                    source_url=document.source_url,
                    role_at_confirmation=document.role,
                    effective_date_at_confirmation=document.effective_date,
                    replaces_id_at_confirmation=document.replaces_document_version_id,
                    is_current_at_confirmation=document.is_current,
                    safety_status_at_confirmation=document.safety_status,
                    structure_id_at_confirmation=structure.id,
                    structure_payload_sha256=payload_hash,
                )
            )
            ordinal += 1

    async def upload_document(self, session: Session, bundle_id: UUID, upload: Any, actor: str, request_id: UUID) -> DocumentVersionView:
        claimed_name = validate_actor(actor)
        # A caller may have performed a read immediately before invoking the
        # service.  End that transaction before multipart streaming and keep
        # the session entirely out of the quarantine/processor phase.
        session.rollback()
        asset: assets.QuarantinedAsset | None = None
        request_paths: list[Path] = []
        try:
            asset = await assets.quarantine_upload(upload, root=self.root)
            request_paths.append(asset.path)
            request_hash = _canonical_hash({"filename": asset.filename, "sha256": asset.sha256, "size": asset.size_bytes, "media_type": asset.declared_media_type})
            inspected = assets.inspect_quarantine(asset, processor=self.processor or self.converter, clamav_checker=self.clamav_checker)

            # Quarantine and inspection intentionally happen before the first
            # database read.  Acquire the aggregate lock only for the short
            # idempotency/readiness recheck and subsequent writes.
            session.rollback()
            bundle = session.scalar(
                select(DocumentBundle)
                .where(DocumentBundle.id == bundle_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if bundle is None:
                raise BundleServiceError("not_found", "문서 bundle을 찾을 수 없습니다", status_code=404, request_id=request_id)
            if bundle.status in {"ready", "superseded"}:
                raise BundleServiceError("invalid_request", "ready bundle은 수정할 수 없습니다. 새 bundle을 만드십시오", status_code=400, request_id=request_id)
            existing = self._idempotency(session, "document_upload", "document_bundle", str(bundle.id), claimed_name, request_id, request_hash)
            if existing is not None:
                assets.cleanup_asset(asset)
                session.rollback()
                return DocumentVersionView.model_validate(existing.response_snapshot)
            try:
                correlation_id = self._bundle_correlation_id(session, bundle)
            except BundleServiceError as error:
                error.request_id = request_id
                raise
            content = self._ensure_content_object(session, asset, inspected.detected_mime)
            self._add_location(session, content.id, "quarantine", asset.path, asset.sha256)
            session.add(
                ContentScan(
                    content_object_id=content.id,
                    scanner="clamav",
                    scanner_version="configured" if inspected.scan_status == "clean" else "unavailable",
                    status=inspected.scan_status,
                    safe_result={"code": inspected.error_code, "warnings": list(inspected.warnings)},
                )
            )
            retry_document = session.scalar(
                select(DocumentVersion)
                .join(Attachment, Attachment.id == DocumentVersion.attachment_id)
                .where(
                    DocumentVersion.notice_id == bundle.notice_id,
                    DocumentVersion.content_object_id == content.id,
                    DocumentVersion.source_kind == asset.source_kind,
                    DocumentVersion.original_filename == asset.filename,
                    DocumentVersion.is_current.is_(True),
                )
                .order_by(DocumentVersion.created_at.desc(), DocumentVersion.id.desc())
                .limit(1)
            )
            if retry_document is not None:
                attachment = session.get(Attachment, retry_document.attachment_id)
                if attachment is None:
                    raise BundleServiceError("processing_failed", "이전 document version 계보가 올바르지 않습니다", status_code=500, request_id=request_id)
                retry_document.is_current = False
                # The current-row partial unique index is immediate.  Persist
                # the demotion before adding its replacement.
                session.flush()
            else:
                attachment = Attachment(
                    notice_id=bundle.notice_id,
                    name=asset.filename,
                    source_url=asset.source_url,
                    origin="manual" if asset.source_kind == "manual" else "g2b",
                    file_ext=Path(asset.filename).suffix.upper().lstrip("."),
                    size_bytes=asset.size_bytes,
                    source_system=asset.source_system,
                    source_attachment_key=asset.source_attachment_key,
                )
                session.add(attachment)
                session.flush()
            version = (session.scalar(select(func.max(DocumentVersion.version)).where(DocumentVersion.attachment_id == attachment.id)) or 0) + 1
            document = DocumentVersion(
                id=uuid4(),
                notice_id=bundle.notice_id,
                attachment_id=attachment.id,
                content_object_id=content.id,
                version=version,
                source_kind=asset.source_kind,
                source_system=asset.source_system,
                source_attachment_key=asset.source_attachment_key,
                source_url=asset.source_url,
                original_filename=asset.filename,
                role=retry_document.role if retry_document is not None else "기타",
                effective_date=retry_document.effective_date if retry_document is not None else None,
                replaces_document_version_id=retry_document.id if retry_document is not None else None,
                is_current=True,
                safety_status=inspected.safety_status,
                needs_human_review=inspected.safety_status != "safe",
                created_by_name=claimed_name,
            )
            session.add(document)
            session.flush()

            structure = self._materialize_structure(session, document, asset, inspected, request_paths)
            if inspected.safety_status == "safe":
                source_path, _digest, _size = assets.commit_source(asset, root=self.root)
                request_paths.append(source_path)
                attachment.legacy_stored_path = str(source_path.relative_to(assets.asset_root(self.root).parent.parent)) if source_path.is_relative_to(assets.asset_root(self.root).parent.parent) else None
                self._add_location(session, content.id, "source", source_path, asset.sha256)
            else:
                attachment.extract_status = inspected.error_code or inspected.safety_status
            if inspected.safety_status == "safe":
                # T-23 preparation runs only after the source location is
                # persisted, while remaining inside this transaction so a
                # failed cut cannot leave a partial bundle lineage.  A clean
                # document with no materialized structure still gets the
                # durable ``awaiting_structure`` state.
                _prepare_pre_spec_overview(session, bundle.notice_id, root=self.root)
            if structure is not None:
                self._seed_bundle_items(session, bundle)
            session.flush()
            bundle.issues_snapshot = self._issues(session, bundle)
            response = self._document_view(document, bundle.id, session)
            session.add(
                IdempotencyRecord(
                    operation="document_upload",
                    aggregate_type="document_bundle",
                    aggregate_id=str(bundle.id),
                    claimed_name=claimed_name,
                    request_id=request_id,
                    request_sha256=request_hash,
                    response_status=202,
                    response_snapshot=response.model_dump(mode="json"),
                )
            )
            session.add(
                AuditEvent(
                    actor_kind="human",
                    claimed_name=claimed_name,
                    action="document.upload",
                    aggregate_type="document_version",
                    aggregate_id=str(document.id),
                    safe_metadata={
                        "bundle_id": str(bundle.id),
                        "status": inspected.safety_status,
                        "scan_status": inspected.scan_status,
                        "error_code": inspected.error_code,
                        **self._lineage_metadata(correlation_id),
                    },
                    request_id=str(request_id),
                )
            )
            session.commit()
            return response
        except assets.AssetError as error:
            session.rollback()
            assets.cleanup_paths(request_paths)
            mapped = map_asset_error(error)
            mapped.request_id = request_id
            raise mapped from error
        except BundleServiceError:
            session.rollback()
            assets.cleanup_paths(request_paths)
            raise
        except IntegrityError as exc:
            session.rollback()
            assets.cleanup_paths(request_paths)
            raise BundleServiceError("idempotency_conflict", "동일 요청이 충돌했습니다", status_code=409, request_id=request_id) from exc
        except Exception:
            session.rollback()
            assets.cleanup_paths(request_paths)
            raise

    def _record_provider_failure(
        self,
        session: Session,
        bundle_id: UUID,
        attachment_id: int,
        *,
        snapshot: _ProviderAttachmentSnapshot | None = None,
        request_paths: Iterable[Path] = (),
    ) -> None:
        """Persist only a safe blocking marker after connector failure."""

        assets.cleanup_paths(request_paths)
        session.rollback()
        try:
            notice_id = snapshot.bundle_notice_id if snapshot is not None else None
            if notice_id is None:
                identity = session.scalar(select(DocumentBundle).where(DocumentBundle.id == bundle_id))
                if identity is None:
                    raise BundleServiceError("not_found", "provider 첨부를 찾을 수 없습니다", status_code=404)
                notice_id = identity.notice_id
                session.rollback()
            notice = session.scalar(
                select(Notice)
                .where(Notice.id == notice_id)
                .with_for_update()
            )
            if notice is None:
                raise BundleServiceError("not_found", "provider 첨부를 찾을 수 없습니다", status_code=404)
            bundle = session.scalar(
                select(DocumentBundle)
                .where(DocumentBundle.id == bundle_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            attachment = session.scalar(
                select(Attachment)
                .where(Attachment.id == attachment_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if bundle is None or attachment is None:
                raise BundleServiceError("not_found", "provider 첨부를 찾을 수 없습니다", status_code=404)
            if attachment.notice_id != bundle.notice_id:
                raise BundleServiceError("not_found", "provider 첨부를 찾을 수 없습니다", status_code=404)
            if snapshot is not None:
                if bundle.notice_id != snapshot.bundle_notice_id or attachment.notice_id != snapshot.notice_id:
                    raise BundleServiceError("not_found", "provider 첨부를 찾을 수 없습니다", status_code=404)
                if bundle.status != snapshot.bundle_status:
                    raise BundleServiceError("bundle_not_ready", "bundle은 더 이상 수정할 수 없습니다", status_code=409)
                if not _provider_scope_matches(snapshot, bundle, attachment):
                    raise BundleServiceError("bundle_not_ready", "provider 첨부 source가 변경되었습니다", status_code=409)
            correlation_id = self._bundle_correlation_id(session, bundle)
            # Provider I/O is deliberately unlocked.  Confirmation may have
            # won while it was in flight; only a still-draft bundle may receive
            # the blocking marker.  In particular, never mutate a ready or
            # superseded snapshot after the race has been observed.
            if bundle.status != "draft":
                raise BundleServiceError("bundle_not_ready", "bundle은 더 이상 수정할 수 없습니다", status_code=409)
            attachment.extract_status = "provider_acquisition_failed"
            bundle.issues_snapshot = self._issues(session, bundle)
            # System attribution is explicit, while URL/path/connector details
            # stay out of audit metadata and therefore cannot leak to callers.
            session.add(
                AuditEvent(
                    actor_kind="system",
                    claimed_name=None,
                    action="provider_attachment.ingest_failed",
                    aggregate_type="attachment",
                    aggregate_id=str(attachment.id),
                    safe_metadata={
                        "status": "blocked",
                        "reason": "provider_acquisition_failed",
                        **self._lineage_metadata(correlation_id),
                    },
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        raise BundleServiceError(
            "bundle_has_blocking_issues",
            "bundle에 해결되지 않은 차단 항목이 있습니다",
            status_code=409,
        )

    def _record_legacy_failure(
        self,
        session: Session,
        bundle_id: UUID,
        attachment_id: int,
        *,
        snapshot: _LegacyAttachmentSnapshot,
        request_paths: Iterable[Path] = (),
    ) -> None:
        """Record only a safe blocking marker for a classified source error."""

        assets.cleanup_paths(request_paths)
        session.rollback()
        try:
            notice = session.scalar(
                select(Notice)
                .where(Notice.id == snapshot.bundle_notice_id)
                .with_for_update()
            )
            if notice is None:
                raise BundleServiceError("not_found", "기존 첨부를 찾을 수 없습니다", status_code=404)
            bundle = session.scalar(
                select(DocumentBundle)
                .where(DocumentBundle.id == bundle_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            attachment = session.scalar(
                select(Attachment)
                .where(Attachment.id == attachment_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if bundle is None or attachment is None or attachment.notice_id != snapshot.attachment_notice_id:
                raise BundleServiceError("not_found", "기존 첨부를 찾을 수 없습니다", status_code=404)
            if bundle.status != "draft" or not _legacy_scope_matches(snapshot, bundle, attachment):
                raise BundleServiceError("bundle_not_ready", "기존 첨부 source가 변경되었습니다", status_code=409)
            correlation_id = self._bundle_correlation_id(session, bundle)

            # Do not copy source details or replace legacy metadata.  This
            # marker is deliberately generic and safe for API/audit output.
            attachment.extract_status = "legacy_acquisition_failed"
            bundle.issues_snapshot = self._issues(session, bundle)
            session.add(
                AuditEvent(
                    actor_kind="system",
                    claimed_name=None,
                    action="legacy_attachment.ingest_failed",
                    aggregate_type="attachment",
                    aggregate_id=str(attachment.id),
                    safe_metadata={
                        "status": "blocked",
                        "reason": "legacy_source_unavailable",
                        **self._lineage_metadata(correlation_id),
                    },
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        raise BundleServiceError(
            "bundle_has_blocking_issues",
            "bundle에 해결되지 않은 차단 항목이 있습니다",
            status_code=409,
        )

    def ingest_legacy_attachment(
        self,
        session: Session,
        bundle_id: UUID,
        attachment_id: int,
    ) -> DocumentVersionView:
        """Reacquire an existing legacy/manual attachment without an HTTP route.

        Only a plain-data snapshot crosses the filesystem and T2 processor
        boundary.  The read transaction is closed before path resolution,
        quarantine streaming, or inspection; the bundle and attachment are
        locked and compared in full immediately before the first write.
        """

        session.rollback()
        bundle = session.scalar(select(DocumentBundle).where(DocumentBundle.id == bundle_id))
        attachment = session.scalar(select(Attachment).where(Attachment.id == attachment_id))
        if bundle is None or attachment is None or attachment.notice_id != bundle.notice_id:
            session.rollback()
            raise BundleServiceError("not_found", "기존 첨부를 찾을 수 없습니다", status_code=404)
        if bundle.status != "draft":
            session.rollback()
            raise BundleServiceError("bundle_not_ready", "bundle은 더 이상 수정할 수 없습니다", status_code=409)
        if attachment.retired_at is not None:
            # Retirement is a caller-visible scope conflict, not an
            # acquisition failure.  Reject before touching the legacy path so
            # no marker, audit, or request-created object can be produced.
            session.rollback()
            raise BundleServiceError("bundle_not_ready", "기존 첨부가 retired 상태입니다", status_code=409)
        snapshot = _LegacyAttachmentSnapshot(
            bundle_id=bundle.id,
            bundle_notice_id=bundle.notice_id,
            bundle_revision=bundle.revision,
            bundle_version=bundle.version,
            bundle_status=bundle.status,
            bundle_supersedes_bundle_id=bundle.supersedes_bundle_id,
            bundle_created_by_name=bundle.created_by_name,
            bundle_confirmed_by_name=bundle.confirmed_by_name,
            bundle_confirmed_at=bundle.confirmed_at,
            bundle_created_at=bundle.created_at,
            bundle_issues_hash=_canonical_hash(bundle.issues_snapshot),
            attachment_id=attachment.id,
            attachment_notice_id=attachment.notice_id,
            attachment_name=attachment.name,
            attachment_source_url=attachment.source_url,
            attachment_origin=attachment.origin,
            attachment_file_ext=attachment.file_ext,
            attachment_size_bytes=attachment.size_bytes,
            attachment_legacy_stored_path=attachment.legacy_stored_path,
            attachment_extract_status=attachment.extract_status,
            attachment_created_at=attachment.created_at,
            attachment_source_system=attachment.source_system,
            attachment_source_attachment_key=attachment.source_attachment_key,
            attachment_last_seen_at=attachment.last_seen_at,
            attachment_retired_at=attachment.retired_at,
            attachment_retired_reason=attachment.retired_reason,
            attachment_retired_by_name=attachment.retired_by_name,
        )
        # End the metadata read transaction before touching the legacy path.
        session.rollback()

        source_name = snapshot.attachment_name
        if not source_name:
            suffix = (snapshot.attachment_file_ext or "").strip().lstrip(".").lower()
            source_name = f"legacy.{suffix}" if suffix else Path(snapshot.attachment_legacy_stored_path or "").name
        source_kind = "provider" if snapshot.attachment_source_system and snapshot.attachment_source_attachment_key else "manual"

        asset: assets.QuarantinedAsset | None = None
        inspected: assets.InspectedAsset | None = None
        request_paths: list[Path] = []
        try:
            provider_fields = (
                snapshot.attachment_source_system,
                snapshot.attachment_source_attachment_key,
                snapshot.attachment_source_url,
            )
            if any(provider_fields) and not all(provider_fields):
                raise assets.AssetError("legacy_provenance_invalid", "기존 첨부 source metadata가 올바르지 않습니다")
            asset = assets.acquire_legacy_attachment(
                stored_path=snapshot.attachment_legacy_stored_path,
                filename=source_name or "legacy.pdf",
                expected_size=snapshot.attachment_size_bytes,
                root=self.root,
            )
            request_paths.append(asset.path)
            inspected = assets.inspect_quarantine(asset, processor=self.processor or self.converter, clamav_checker=self.clamav_checker)

            # This is the race fence: no ORM write happens before this lock
            # and complete source/bundle comparison.
            session.rollback()
            notice = session.scalar(
                select(Notice)
                .where(Notice.id == snapshot.bundle_notice_id)
                .with_for_update()
            )
            if notice is None:
                raise BundleServiceError("not_found", "기존 첨부를 찾을 수 없습니다", status_code=404)
            bundle = session.scalar(
                select(DocumentBundle)
                .where(DocumentBundle.id == bundle_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            attachment = session.scalar(
                select(Attachment)
                .where(Attachment.id == attachment_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if bundle is None or attachment is None or attachment.notice_id != snapshot.attachment_notice_id:
                raise BundleServiceError("not_found", "기존 첨부를 찾을 수 없습니다", status_code=404)
            if bundle.status != "draft" or not _legacy_scope_matches(snapshot, bundle, attachment):
                raise BundleServiceError("bundle_not_ready", "기존 첨부 source가 변경되었습니다", status_code=409)
            correlation_id = self._bundle_correlation_id(session, bundle)

            content = self._ensure_content_object(session, asset, inspected.detected_mime)
            self._add_location(session, content.id, "quarantine", asset.path, asset.sha256)
            session.add(
                ContentScan(
                    content_object_id=content.id,
                    scanner="clamav",
                    scanner_version="configured" if inspected.scan_status == "clean" else "unavailable",
                    status=inspected.scan_status,
                    safe_result={"code": inspected.error_code, "warnings": list(inspected.warnings)},
                )
            )
            session.flush()

            versions = session.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.attachment_id == attachment.id)
                .order_by(DocumentVersion.version.desc(), DocumentVersion.created_at.desc(), DocumentVersion.id.desc())
                .with_for_update()
            ).all()
            current = next((row for row in versions if row.is_current), None)
            current_content = session.get(ContentObject, current.content_object_id) if current else None
            current_structure = self._structure_for(session, current.id) if current else None
            current_structure_valid = bool(
                current
                and current.safety_status == "safe"
                and current_structure is not None
                and current_structure.validation_status == "ready"
                and current_content is not None
                and current_structure.source_sha256 == current_content.sha256 == asset.sha256
                and current_structure.media_type == current_content.detected_mime
                and self._load_structure_payload(session, current_structure, allow_unsafe=True) is not None
            )
            same_byte_restore = bool(
                current
                and current_content
                and current_content.sha256 == asset.sha256
                and current_structure_valid
                and inspected.safety_status == "safe"
            )
            inspected_persisted = False

            # Existing legacy metadata, especially legacy_stored_path, is
            # intentionally untouched.  New provenance belongs on the
            # immutable document version and content location rows.
            if inspected.safety_status == "safe":
                source_path, _digest, _size = assets.commit_source(asset, root=self.root)
                request_paths.append(source_path)
                self._add_location(session, content.id, "source", source_path, asset.sha256)

            if same_byte_restore:
                document = current
                assert document is not None
                inspected_persisted = True
            else:
                if current is not None:
                    session.execute(
                        update(DocumentVersion)
                        .where(DocumentVersion.id == current.id, DocumentVersion.is_current.is_(True))
                        .values(is_current=False)
                    )
                    session.flush()
                previous = versions[0] if versions else None
                document = DocumentVersion(
                    id=uuid4(),
                    notice_id=bundle.notice_id,
                    attachment_id=attachment.id,
                    content_object_id=content.id,
                    version=(previous.version + 1) if previous else 1,
                    source_kind=source_kind,
                    source_system=snapshot.attachment_source_system if source_kind == "provider" else None,
                    source_attachment_key=snapshot.attachment_source_attachment_key if source_kind == "provider" else None,
                    source_url=snapshot.attachment_source_url if source_kind == "provider" else None,
                    original_filename=source_name or "legacy.pdf",
                    role=current.role if current is not None else "기타",
                    effective_date=current.effective_date if current is not None else None,
                    replaces_document_version_id=current.id if current is not None else None,
                    is_current=True,
                    safety_status=inspected.safety_status,
                    needs_human_review=inspected.safety_status != "safe",
                    created_by_name=None,
                )
                session.add(document)
                session.flush()
                inspected_persisted = self._materialize_structure(session, document, asset, inspected, request_paths) is not None

            # Preserve ordinary legacy extract_status values (for example
            # ``pending``) on a first successful import.  Only remove the
            # service-generated marker after the inspected result and source
            # persistence have succeeded, so a failed retry remains visible.
            if inspected_persisted and inspected.safety_status == "safe" and attachment.extract_status == "legacy_acquisition_failed":
                attachment.extract_status = None
            if inspected.safety_status == "safe":
                _prepare_pre_spec_overview(session, bundle.notice_id, root=self.root)

            bundle.issues_snapshot = self._issues(session, bundle)
            session.add(
                AuditEvent(
                    actor_kind="system",
                    claimed_name=None,
                    action="legacy_attachment.ingest",
                    aggregate_type="document_version",
                    aggregate_id=str(document.id),
                    safe_metadata={
                        "attachment_id": attachment.id,
                        "version": document.version,
                        "same_byte_restore": same_byte_restore,
                        "status": inspected.safety_status,
                        **self._lineage_metadata(correlation_id),
                    },
                )
            )
            response = self._document_view(document, bundle.id, session)
            session.commit()
            return response
        except assets.AssetError:
            # Classified source failures may leave only a generic blocking
            # marker/audit on the unchanged draft scope.  Unsafe bytes that
            # reached inspection are represented above and retain quarantine;
            # path/read failures have no trusted bytes to retain.
            return self._record_legacy_failure(
                session,
                bundle_id,
                attachment_id,
                snapshot=snapshot,
                request_paths=request_paths,
            )
        except BundleServiceError:
            session.rollback()
            assets.cleanup_paths(request_paths)
            raise
        except Exception:
            # DB/programming failures do not receive a source-failure marker;
            # all request-created objects are removed after rollback.
            session.rollback()
            assets.cleanup_paths(request_paths)
            raise

    # Explicit worker-facing alias; no router imports or registers it.
    ingest_legacy_document = ingest_legacy_attachment

    def ingest_provider_attachment(
        self,
        session: Session,
        bundle_id: UUID,
        attachment_id: int,
        connectors: Mapping[str, assets.ProviderConnector],
        *,
        filename: str | None = None,
    ) -> DocumentVersionView:
        """Acquire an existing URL-only provider attachment internally.

        There is intentionally no HTTP route for this operation.  The
        caller supplies a source-system connector selected by trusted worker
        configuration; the existing attachment is the only source of URL and
        stable key provenance.  Source metadata is snapshotted in a short
        read transaction, then the connector and processor run with no open
        transaction.  The bundle and attachment are locked and compared only
        immediately before the first write.
        """

        # Do not carry a caller's read transaction into network or document
        # processing.  The snapshot below is plain data, not ORM instances.
        session.rollback()
        bundle = session.scalar(
            select(DocumentBundle)
            .where(DocumentBundle.id == bundle_id)
        )
        attachment = session.scalar(
            select(Attachment)
            .where(Attachment.id == attachment_id)
        )
        if bundle is None or attachment is None or attachment.notice_id != bundle.notice_id:
            session.rollback()
            raise BundleServiceError("not_found", "provider 첨부를 찾을 수 없습니다", status_code=404)

        if bundle.status != "draft":
            session.rollback()
            raise BundleServiceError("bundle_not_ready", "bundle은 더 이상 수정할 수 없습니다", status_code=409)
        if attachment.retired_at is not None:
            # A retired provider attachment must be rejected before any
            # connector, quarantine, or processor work.  It is not a
            # provider failure and therefore must not receive a marker or
            # failure audit.
            session.rollback()
            raise BundleServiceError("bundle_not_ready", "provider 첨부가 retired 상태입니다", status_code=409)
        snapshot = _ProviderAttachmentSnapshot(
            bundle_notice_id=bundle.notice_id,
            bundle_status=bundle.status,
            attachment_id=attachment.id,
            notice_id=attachment.notice_id,
            name=attachment.name,
            source_system=attachment.source_system,
            source_attachment_key=attachment.source_attachment_key,
            source_url=attachment.source_url,
            retired=attachment.retired_at is not None,
        )
        # End the short metadata read transaction before connector I/O.
        session.rollback()

        if snapshot.retired or not snapshot.source_system or not snapshot.source_attachment_key or not snapshot.source_url:
            return self._record_provider_failure(session, bundle_id, attachment_id, snapshot=snapshot)

        requested_filename = filename if filename is not None else snapshot.name

        asset: assets.QuarantinedAsset | None = None
        request_paths: list[Path] = []
        try:
            asset = assets.acquire_provider_attachment(
                source_system=snapshot.source_system,
                source_url=snapshot.source_url,
                source_attachment_key=snapshot.source_attachment_key,
                filename=requested_filename,
                connectors=connectors,
                root=self.root,
            )
            request_paths.append(asset.path)
            source_name = asset.filename
            inspected = assets.inspect_quarantine(asset, processor=self.processor or self.converter, clamav_checker=self.clamav_checker)

            # Recheck only after connector/document I/O.  This is the first
            # transaction/lock after the snapshot and is the race fence with
            # confirmation and provider metadata updates.
            session.rollback()
            notice = session.scalar(
                select(Notice)
                .where(Notice.id == snapshot.notice_id)
                .with_for_update()
            )
            if notice is None:
                raise BundleServiceError("not_found", "provider 첨부를 찾을 수 없습니다", status_code=404)
            bundle = session.scalar(
                select(DocumentBundle)
                .where(DocumentBundle.id == bundle_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            attachment = session.scalar(
                select(Attachment)
                .where(Attachment.id == attachment_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if bundle is None or attachment is None or attachment.notice_id != snapshot.notice_id or bundle.notice_id != snapshot.bundle_notice_id:
                raise BundleServiceError("not_found", "provider 첨부를 찾을 수 없습니다", status_code=404)
            if bundle.status != "draft":
                raise BundleServiceError("bundle_not_ready", "bundle은 더 이상 수정할 수 없습니다", status_code=409)
            if not _provider_scope_matches(snapshot, bundle, attachment):
                raise BundleServiceError("bundle_not_ready", "provider 첨부 source가 변경되었습니다", status_code=409)
            correlation_id = self._bundle_correlation_id(session, bundle)

            content = self._ensure_content_object(session, asset, inspected.detected_mime)
            self._add_location(session, content.id, "quarantine", asset.path, asset.sha256)
            session.add(
                ContentScan(
                    content_object_id=content.id,
                    scanner="clamav",
                    scanner_version="configured" if inspected.scan_status == "clean" else "unavailable",
                    status=inspected.scan_status,
                    safe_result={"code": inspected.error_code, "warnings": list(inspected.warnings)},
                )
            )
            session.flush()

            versions = session.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.attachment_id == attachment.id)
                .order_by(DocumentVersion.version.desc(), DocumentVersion.created_at.desc(), DocumentVersion.id.desc())
                .with_for_update()
            ).all()
            current = next((row for row in versions if row.is_current), None)
            current_content = session.get(ContentObject, current.content_object_id) if current else None
            current_structure = self._structure_for(session, current.id) if current else None
            current_structure_valid = bool(
                current
                and current.safety_status == "safe"
                and current_structure is not None
                and current_structure.validation_status == "ready"
                and current_content is not None
                and current_structure.source_sha256 == current_content.sha256 == asset.sha256
                and current_structure.media_type == current_content.detected_mime
                and self._load_structure_payload(session, current_structure, allow_unsafe=True) is not None
            )
            same_byte_restore = bool(current and current_content and current_content.sha256 == asset.sha256 and current_structure_valid and inspected.safety_status == "safe")

            attachment.size_bytes = asset.size_bytes
            attachment.name = source_name
            attachment.origin = attachment.origin or "g2b"
            attachment.extract_status = None if inspected.safety_status == "safe" else (inspected.error_code or inspected.safety_status)
            if inspected.safety_status == "safe":
                source_path, _digest, _size = assets.commit_source(asset, root=self.root)
                request_paths.append(source_path)
                asset_root = assets.asset_root(self.root)
                attachment.legacy_stored_path = str(source_path.relative_to(asset_root.parent.parent))
                self._add_location(session, content.id, "source", source_path, asset.sha256)

            if same_byte_restore:
                # Re-acquisition of the same bytes only restores a verified
                # source location; it must not create a duplicate business
                # version or structure lineage.
                document = current
                assert document is not None
            else:
                if current is not None:
                    session.execute(
                        update(DocumentVersion)
                        .where(DocumentVersion.id == current.id, DocumentVersion.is_current.is_(True))
                        .values(is_current=False)
                    )
                    session.flush()
                previous = versions[0] if versions else None
                document = DocumentVersion(
                    id=uuid4(),
                    notice_id=bundle.notice_id,
                    attachment_id=attachment.id,
                    content_object_id=content.id,
                    version=(previous.version + 1) if previous else 1,
                    source_kind="provider",
                    source_system=attachment.source_system,
                    source_attachment_key=attachment.source_attachment_key,
                    # Keep the attachment's original URL even if connector
                    # transport followed an allowlisted redirect.
                    source_url=attachment.source_url,
                    original_filename=source_name,
                    role=current.role if current is not None else "기타",
                    effective_date=current.effective_date if current is not None else None,
                    replaces_document_version_id=current.id if current is not None else None,
                    is_current=True,
                    safety_status=inspected.safety_status,
                    needs_human_review=inspected.safety_status != "safe",
                    created_by_name=None,
                )
                session.add(document)
                session.flush()
                structure = self._materialize_structure(session, document, asset, inspected, request_paths)
            if inspected.safety_status == "safe":
                # Also refresh the logical review when this acquisition is a
                # same-byte restore and no new structure row was needed.
                _prepare_pre_spec_overview(session, bundle.notice_id, root=self.root)

            bundle.issues_snapshot = self._issues(session, bundle)
            session.add(
                AuditEvent(
                    actor_kind="system",
                    claimed_name=None,
                    action="provider_attachment.ingest",
                    aggregate_type="document_version",
                    aggregate_id=str(document.id),
                    safe_metadata={
                        "attachment_id": attachment.id,
                        "version": document.version,
                        "same_byte_restore": same_byte_restore,
                        "status": inspected.safety_status,
                        **self._lineage_metadata(correlation_id),
                    },
                )
            )
            response = self._document_view(document, bundle.id, session)
            session.commit()
            return response
        except assets.AssetError:
            # Only classified asset/provider acquisition failures receive the
            # safe blocking marker.  DB, service, and programming failures
            # must leave no acquisition-failure audit or attachment status.
            return self._record_provider_failure(
                session,
                bundle_id,
                attachment_id,
                snapshot=snapshot,
                request_paths=request_paths,
            )
        except BundleServiceError:
            session.rollback()
            assets.cleanup_paths(request_paths)
            raise
        except Exception:
            # Unexpected DB/ORM/programming failures are not provider
            # acquisition failures.  Roll back all rows and remove every
            # object created by this request, then let the API boundary map
            # the original failure to processing_failed.
            session.rollback()
            assets.cleanup_paths(request_paths)
            raise

    # Explicit worker-facing alias; no router imports or registers it.
    ingest_provider_document = ingest_provider_attachment

    def _ensure_content_object(self, session: Session, asset: assets.QuarantinedAsset, detected_mime: str) -> ContentObject:
        content = session.scalar(select(ContentObject).where(ContentObject.sha256 == asset.sha256))
        if content is None:
            content = ContentObject(sha256=asset.sha256, size_bytes=asset.size_bytes, detected_mime=detected_mime or "application/octet-stream", retention_class="document-source")
            session.add(content)
            session.flush()
        return content

    def _materialize_structure(
        self,
        session: Session,
        document: DocumentVersion,
        asset: assets.QuarantinedAsset,
        inspected: assets.InspectedAsset,
        request_paths: list[Path],
    ) -> DocumentStructure | None:
        """Delegate every structure write to the canonical materializer."""

        return materialize_structure(
            session,
            document,
            asset,
            inspected,
            request_paths,
            root=self.root,
            add_location=self._add_location,
        )

    def _add_location(self, session: Session, content_id: UUID, namespace: str, path: Path, digest: str) -> None:
        root = assets.asset_root(self.root)
        try:
            key = path.resolve().relative_to(root).as_posix()
        except ValueError as exc:
            raise BundleServiceError("processing_failed", "asset location이 격리 루트 밖입니다", status_code=500) from exc
        try:
            metadata = assets.head_object(namespace, key, root=self.root)
        except assets.AssetError as exc:
            raise BundleServiceError("processing_failed", "asset object metadata를 확인할 수 없습니다", status_code=500) from exc
        session.add(ContentObjectLocation(
            content_object_id=content_id,
            namespace_key=namespace,
            object_key=key,
            object_version_id=metadata.object_version_id,
            status="verified",
            etag=metadata.etag,
            verified_at=_now(),
        ))

    def patch_document(
        self,
        session: Session,
        document_id: UUID,
        request: PatchDocumentVersionRequest,
        actor: str,
        *,
        expected_bundle_id: UUID | None = None,
        expected_bundle_version: int | None = None,
        expected_bundle_sha256: str | None = None,
    ) -> DocumentVersionView:
        claimed_name = validate_actor(actor)
        # Discover the aggregate scope without retaining a read transaction,
        # then take the same notice allocation fence used by create_bundle.
        # This keeps an agent's latest-bundle ref valid through the mutation.
        session.rollback()
        identity = session.scalar(select(DocumentVersion).where(DocumentVersion.id == document_id))
        if identity is None:
            session.rollback()
            raise BundleServiceError("not_found", "document version을 찾을 수 없습니다", status_code=404)
        notice_id = identity.notice_id
        session.rollback()
        notice = session.scalar(select(Notice).where(Notice.id == notice_id).with_for_update())
        if notice is None:
            session.rollback()
            raise BundleServiceError("not_found", "공고를 찾을 수 없습니다", status_code=404)
        latest_bundle = session.scalar(
            select(DocumentBundle)
            .where(DocumentBundle.notice_id == notice.id)
            .order_by(DocumentBundle.revision.desc(), DocumentBundle.id.desc())
            .limit(1)
            .with_for_update()
        )
        if latest_bundle is None:
            raise BundleServiceError("not_found", "document bundle을 찾을 수 없습니다", status_code=404)
        if expected_bundle_id is not None:
            latest_items = session.scalars(
                select(DocumentBundleItem)
                .where(DocumentBundleItem.bundle_id == latest_bundle.id)
                .order_by(DocumentBundleItem.ordinal.asc(), DocumentBundleItem.document_version_id.asc())
            ).all()
            if (
                latest_bundle.id != expected_bundle_id
                or latest_bundle.version != expected_bundle_version
                or document_bundle_snapshot_hash(latest_bundle, latest_items) != expected_bundle_sha256
            ):
                session.rollback()
                raise BundleServiceError(
                    "version_conflict",
                    "document bundle이 변경되었습니다",
                    status_code=409,
                )
        document = session.scalar(
            select(DocumentVersion)
            .where(DocumentVersion.id == document_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if document is None:
            raise BundleServiceError("not_found", "document version을 찾을 수 없습니다", status_code=404)
        ready = session.scalar(
            select(DocumentBundleItem).join(DocumentBundle, DocumentBundle.id == DocumentBundleItem.bundle_id).where(
                DocumentBundleItem.document_version_id == document.id,
                DocumentBundle.status.in_(("ready", "superseded")),
            )
        )
        if ready is not None:
            raise BundleServiceError("version_conflict", "확정된 bundle의 document version은 변경할 수 없습니다", status_code=409)
        if document.version != request.version:
            raise BundleServiceError("version_conflict", "document version이 변경되었습니다", status_code=409)
        if request.replaces_document_version_id == document.id:
            raise BundleServiceError("invalid_request", "문서는 자기 자신을 대체할 수 없습니다", status_code=400)
        if request.replaces_document_version_id is not None:
            replaced = session.get(DocumentVersion, request.replaces_document_version_id)
            if replaced is None or replaced.notice_id != document.notice_id:
                raise BundleServiceError("invalid_request", "대체 document version이 같은 공고에 속하지 않습니다", status_code=400)
        correlation_id = self._bundle_correlation_id(session, latest_bundle)

        # A non-null attachment owns a version lineage.  Lock the complete
        # lineage and allocate after its maximum so patching an older row can
        # never reuse a version already assigned to a newer row.  NULL
        # attachment IDs intentionally have no shared lineage.
        next_version = int(document.version) + 1
        if document.attachment_id is not None:
            lineage = session.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.attachment_id == document.attachment_id)
                .order_by(DocumentVersion.version.asc(), DocumentVersion.id.asc())
                .with_for_update()
            ).all()
            next_version = max(int(row.version) for row in lineage) + 1

        if request.is_current and document.attachment_id is not None:
            session.execute(
                update(DocumentVersion)
                .where(
                    DocumentVersion.attachment_id == document.attachment_id,
                    DocumentVersion.id != document.id,
                    DocumentVersion.is_current.is_(True),
                )
                .values(is_current=False)
            )
            # The current-row uniqueness check is immediate, so the old
            # current state must be gone before this row is marked current.
            session.flush()
        changed = session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == document.id, DocumentVersion.version == request.version)
            .values(
                role=request.role,
                effective_date=request.effective_date,
                replaces_document_version_id=request.replaces_document_version_id,
                is_current=request.is_current,
                version=next_version,
            )
        )
        if changed.rowcount != 1:
            session.rollback()
            raise BundleServiceError("version_conflict", "document version이 변경되었습니다", status_code=409)
        session.refresh(document)
        session.add(
            AuditEvent(
                actor_kind="human",
                claimed_name=claimed_name,
                action="document_version.patch",
                aggregate_type="document_version",
                aggregate_id=str(document.id),
                safe_metadata={
                    "version": document.version,
                    "role": document.role,
                    "is_current": document.is_current,
                    **self._lineage_metadata(correlation_id),
                },
            )
        )
        session.commit()
        bundle = session.scalar(
            select(DocumentBundle)
            .where(DocumentBundle.notice_id == document.notice_id)
            .order_by(DocumentBundle.revision.desc(), DocumentBundle.id.desc())
            .limit(1)
        )
        if bundle is None:
            raise BundleServiceError("not_found", "document bundle을 찾을 수 없습니다", status_code=404)
        return self._document_view(document, bundle.id, session)

    def confirm(self, session: Session, bundle_id: UUID, request: ConfirmRequest, actor: str) -> BundleView:
        claimed_name = validate_actor(actor)
        request_hash = _canonical_hash(request.model_dump(mode="json"))
        existing = self._idempotency(session, "document_bundle_confirm", "document_bundle", str(bundle_id), claimed_name, request.request_id, request_hash)
        if existing is not None:
            response = BundleView.model_validate(existing.response_snapshot)
            # Replay is a read-only immutable snapshot.  End the transaction
            # opened by the idempotency probe before returning so a caller does
            # not retain a read/row lock for the lifetime of its session.
            session.rollback()
            return response

        # The initial idempotency probe intentionally does not hold the
        # aggregate lock.  Read only the target identity to discover the
        # notice scope, then start the lock cycle in its canonical order:
        # notice -> target bundle -> all bundles -> attachments -> documents
        # -> structures.  Attachment writers use this same notice fence so a
        # retirement or source update cannot race the ready scope enumeration.
        bundle_identity = session.scalar(select(DocumentBundle).where(DocumentBundle.id == bundle_id))
        if bundle_identity is None:
            session.rollback()
            raise BundleServiceError("not_found", "문서 bundle을 찾을 수 없습니다", status_code=404, request_id=request.request_id)
        notice_id = bundle_identity.notice_id
        session.rollback()

        notice = session.scalar(
            select(Notice)
            .where(Notice.id == notice_id)
            .with_for_update()
        )
        if notice is None:
            session.rollback()
            raise BundleServiceError("not_found", "공고를 찾을 수 없습니다", status_code=404, request_id=request.request_id)
        bundle = session.scalar(
            select(DocumentBundle)
            .where(DocumentBundle.id == bundle_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if bundle is None or bundle.notice_id != notice.id:
            session.rollback()
            raise BundleServiceError("not_found", "문서 bundle을 찾을 수 없습니다", status_code=404, request_id=request.request_id)
        # A concurrent confirmer may have committed the idempotency record
        # while this request waited for the notice/bundle locks.  Recheck in
        # the locked transaction so an identical request replays the stored
        # response and a different hash gets idempotency_conflict before any
        # scope enumeration or status/version validation can mask it.
        existing = self._idempotency(session, "document_bundle_confirm", "document_bundle", str(bundle_id), claimed_name, request.request_id, request_hash)
        if existing is not None:
            response = BundleView.model_validate(existing.response_snapshot)
            session.rollback()
            return response
        correlation_id = self._bundle_correlation_id(session, bundle)
        if bundle.version != request.version:
            raise BundleServiceError("version_conflict", "bundle version이 변경되었습니다", status_code=409, request_id=request.request_id)
        if bundle.status in {"ready", "superseded"}:
            raise BundleServiceError("version_conflict", "bundle이 이미 확정되어 있습니다", status_code=409, request_id=request.request_id)

        # Lock every bundle in revision order while the notice scope is held.
        # A higher ready/superseded revision means this draft is a backward
        # confirmation and must not be allowed to replace the approved
        # lineage.  Lower ready bundles are superseded only after the target
        # snapshot is complete below.
        bundles = session.scalars(
            select(DocumentBundle)
            .where(DocumentBundle.notice_id == notice.id)
            .order_by(DocumentBundle.revision.asc(), DocumentBundle.id.asc())
            .with_for_update()
        ).all()
        if any(row.revision > bundle.revision and row.status in {"ready", "superseded"} for row in bundles):
            session.rollback()
            raise BundleServiceError("version_conflict", "더 높은 revision의 bundle이 이미 확정되어 있습니다", status_code=409, request_id=request.request_id)

        # Lock all non-retired attachments first, then current documents and
        # their structures.  The explicit rows (rather than a joined lock)
        # make the notice-wide retirement fence visible and deterministic to
        # PostgreSQL and to the future T7 attachment writers.
        attachments = session.scalars(
            select(Attachment)
            .where(Attachment.notice_id == notice.id, Attachment.retired_at.is_(None))
            .order_by(Attachment.id.asc())
            .with_for_update()
        ).all()
        attachment_ids = {attachment.id for attachment in attachments}
        all_current = session.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.notice_id == notice.id,
                DocumentVersion.is_current.is_(True),
                DocumentVersion.attachment_id.in_(attachment_ids),
            )
            .order_by(DocumentVersion.attachment_id.asc(), DocumentVersion.id.asc())
            .with_for_update()
        ).all() if attachment_ids else []
        current_ids = {document.id for document in all_current}
        structures = session.scalars(
            select(DocumentStructure)
            .where(DocumentStructure.document_version_id.in_(current_ids))
            .order_by(DocumentStructure.document_version_id.asc())
            .with_for_update()
        ).all() if current_ids else []
        structures_by_document = {structure.document_version_id: structure for structure in structures}

        # Do not collapse the request into a dict until duplicates have been
        # recorded.  A duplicate must never silently choose the last version.
        requested: dict[UUID, int] = {}
        duplicate_ids: set[UUID] = set()
        for confirmed in request.confirmed_documents:
            if confirmed.document_version_id in requested:
                duplicate_ids.add(confirmed.document_version_id)
            else:
                requested[confirmed.document_version_id] = confirmed.version

        scope_issues: list[dict[str, Any]] = []
        for duplicate_id in sorted(duplicate_ids, key=str):
            scope_issues.append(_error_issue("duplicate_confirmed_document", "확인 문서 ID가 중복되었습니다", document_version_id=duplicate_id))
        for document in all_current:
            requested_version = requested.get(document.id)
            if requested_version is None:
                scope_issues.append(_error_issue("confirmation_scope_incomplete", "확인 시점의 모든 current document를 포함해야 합니다", document_version_id=document.id))
            elif requested_version != document.version:
                scope_issues.append(_error_issue("confirmation_version_mismatch", "확인한 document version이 현재 version과 다릅니다", document_version_id=document.id))
        for requested_id in sorted(set(requested) - current_ids, key=str):
            scope_issues.append(_error_issue("confirmation_scope_incomplete", "확인 문서가 현재 bundle 범위에 없습니다", document_version_id=requested_id))

        # Seed only after the locked scope is known.  _issues then validates
        # the same rows/structures that will become the immutable snapshot.
        self._seed_bundle_items(session, bundle)
        session.flush()
        issues = self._issues(session, bundle)
        issues.extend(scope_issues)
        issues = _dedupe_issues(issues)
        bundle.issues_snapshot = issues
        if not all_current:
            session.commit()
            raise BundleServiceError("bundle_has_blocking_issues", "bundle 문서가 없습니다", status_code=409, request_id=request.request_id)
        blocking = [issue for issue in issues if issue.get("blocking")]
        if blocking:
            session.commit()
            raise BundleServiceError("bundle_has_blocking_issues", "bundle에 해결되지 않은 blocking issue가 있습니다", status_code=409, request_id=request.request_id)
        claimed = session.execute(
            update(DocumentBundle)
            .where(DocumentBundle.id == bundle.id, DocumentBundle.version == request.version, DocumentBundle.status != "ready")
            .values(version=DocumentBundle.version + 1)
        )
        if claimed.rowcount != 1:
            session.rollback()
            raise BundleServiceError("version_conflict", "bundle version이 변경되었습니다", status_code=409, request_id=request.request_id)
        session.refresh(bundle)
        items_by_document = {
            item.document_version_id: item
            for item in session.scalars(
                select(DocumentBundleItem)
                .where(DocumentBundleItem.bundle_id == bundle.id)
                .order_by(DocumentBundleItem.ordinal.asc(), DocumentBundleItem.document_version_id.asc())
            ).all()
        }
        for ordinal, document in enumerate(all_current):
            item = items_by_document.get(document.id)
            structure = structures_by_document.get(document.id)
            content = session.get(ContentObject, document.content_object_id) if document else None
            if structure is None or content is None:
                session.rollback()
                raise BundleServiceError("structure_unavailable", "bundle snapshot을 만들 수 없습니다", status_code=409, request_id=request.request_id)
            if item is None:
                item = DocumentBundleItem(bundle_id=bundle.id, document_version_id=document.id, ordinal=ordinal)
                session.add(item)
            item.document_version_version = document.version
            item.content_object_id = content.id
            item.content_sha256 = content.sha256
            item.detected_mime = content.detected_mime
            item.size_bytes = content.size_bytes
            item.original_filename = document.original_filename
            item.source_kind = document.source_kind
            item.source_system = document.source_system
            item.source_attachment_key = document.source_attachment_key
            item.source_url = document.source_url
            item.role_at_confirmation = document.role
            item.effective_date_at_confirmation = document.effective_date
            item.replaces_id_at_confirmation = document.replaces_document_version_id
            item.is_current_at_confirmation = document.is_current
            item.safety_status_at_confirmation = document.safety_status
            item.structure_id_at_confirmation = structure.id
            item.structure_payload_sha256 = structure.payload_sha256
        bundle.status = "ready"
        bundle.confirmed_by_name = claimed_name
        bundle.confirmed_at = _now()
        # A draft can sit between two confirmations, so supersede every
        # lower-revision ready bundle in this notice, not merely the bundle
        # referenced by supersedes_bundle_id.  Only the status changes;
        # historical DocumentBundleItem snapshots remain untouched.
        for historical in bundles:
            if historical.revision < bundle.revision and historical.status == "ready":
                historical.status = "superseded"
        response = self._bundle_view(session, bundle)
        session.add(
            IdempotencyRecord(
                operation="document_bundle_confirm",
                aggregate_type="document_bundle",
                aggregate_id=str(bundle.id),
                claimed_name=claimed_name,
                request_id=request.request_id,
                request_sha256=request_hash,
                response_status=200,
                response_snapshot=response.model_dump(mode="json"),
            )
        )
        session.add(
            AuditEvent(
                actor_kind="human",
                claimed_name=claimed_name,
                action="document_bundle.confirm",
                aggregate_type="document_bundle",
                aggregate_id=str(bundle.id),
                safe_metadata={
                    "version": bundle.version,
                    "document_count": len(response.documents),
                    **self._lineage_metadata(correlation_id),
                },
                request_id=str(request.request_id),
            )
        )
        session.commit()
        return response

    def get_structure(self, session: Session, structure_id: UUID) -> DocumentStructureSchema:
        structure = session.get(DocumentStructure, structure_id)
        if structure is None:
            raise BundleServiceError("not_found", "document structure를 찾을 수 없습니다", status_code=404)
        document = session.get(DocumentVersion, structure.document_version_id)
        if document is None or document.safety_status != "safe":
            raise BundleServiceError("unsafe_document", "quarantine 문서는 열람할 수 없습니다", status_code=403)
        payload = self._load_structure_payload(session, structure)
        if payload is None:
            raise BundleServiceError("unsafe_document", "document structure를 검증할 수 없습니다", status_code=403)
        try:
            return DocumentStructureSchema.model_validate(payload)
        except ValueError as exc:
            raise BundleServiceError("unsafe_document", "document structure를 검증할 수 없습니다", status_code=403) from exc

    def get_structure_page(self, session: Session, structure_id: UUID, page: int) -> DocumentStructurePageView:
        structure = self.get_structure(session, structure_id)
        if page < 1:
            raise BundleServiceError("not_found", "document page를 찾을 수 없습니다", status_code=404)
        metadata = next((item for item in structure.pages if item.number == page), None)
        if metadata is None:
            raise BundleServiceError("not_found", "document page를 찾을 수 없습니다", status_code=404)
        return DocumentStructurePageView(
            structure_id=structure.structure_id,
            page=page,
            metadata=metadata,
            blocks=[block for block in structure.blocks if block.page == page],
        )

    def _idempotency(self, session: Session, operation: str, aggregate_type: str, aggregate_id: str, actor: str, request_id: UUID, request_hash: str) -> IdempotencyRecord | None:
        record = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.aggregate_type == aggregate_type,
                IdempotencyRecord.aggregate_id == aggregate_id,
                IdempotencyRecord.claimed_name == actor,
                IdempotencyRecord.request_id == request_id,
            )
        )
        if record is not None and record.request_sha256 != request_hash:
            raise BundleServiceError("idempotency_conflict", "동일 request_id의 요청 내용이 다릅니다", status_code=409, request_id=request_id)
        return record


def _dedupe_issues(issues: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for raw in issues:
        issue = dict(raw)
        key = (str(issue.get("code", "")), str(issue.get("document_version_id")) if issue.get("document_version_id") else None)
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result
