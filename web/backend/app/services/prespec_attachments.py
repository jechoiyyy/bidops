"""Eligibility, leasing, and backend fetching for pre-specification assets.

The service keeps provider and document I/O outside database transactions.  A
claim is a small lease fence; after I/O, every write rechecks that fence before
it records a source object or document version.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..document_mcp.errors import DocumentProcessingError
from ..models import (
    Attachment,
    AttachmentFetch,
    AuditEvent,
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentVersion,
    Notice,
    Opportunity,
    OpportunityLink,
    utc_now,
)
from . import assets


SOURCE_SYSTEM = "g2b"
G2B_HOST = "www.g2b.go.kr"
G2B_ATTACHMENT_PATH = "/pn/pnz/pnza/UntyAtchFile/downloadFile.do"
_ATTACHMENT_QUERY_KEYS = frozenset({"bfSpecRegNo", "fileType", "fileSeq"})
_TRACKING_LINK_STATUSES = frozenset({"확정", "사람 확인 완료", "후보 확인 대기"})
_TRACKING_STATUSES = frozenset({"계속 추적", "보류"})
_WORKER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,127}$")
_SAFE_WARNING_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")

_RETRYABLE_CODES = frozenset(
    {
        "provider_timeout",
        "provider_fetch_failed",
        "provider_dns_blocked",
        "provider_connector_blocked",
        "clamav_unavailable",
        "service_unavailable",
    }
)
_TERMINAL_CODES = frozenset(
    {
        "unsupported_extension",
        "mime_mismatch",
        "malware_detected",
        "provider_size_limit",
        "malformed_pdf",
        "malformed_archive",
        "unsafe_document",
        "invalid_request",
        "hash_mismatch",
        "provider_response_invalid",
        "provider_url_blocked",
        "provider_host_blocked",
        "provider_redirect_blocked",
        "provider_private_ip",
        "provider_proxy_blocked",
        "processing_failed",
        "conversion_required",
        "malformed_hwpx",
        "image_size_limit",
        "output_size_limit",
        "page_limit",
        "archive_size_limit",
    }
)


@dataclass(frozen=True)
class AttachmentFetchClaim:
    """The immutable identity of a claimed queue row."""

    id: UUID
    attachment_id: int
    worker_id: str
    lease_fence: int

    @property
    def fetch_id(self) -> UUID:
        return self.id

    @property
    def fence(self) -> int:
        return self.lease_fence


@dataclass(frozen=True)
class _AttachmentSnapshot:
    fetch_id: UUID
    attachment_id: int
    notice_id: int
    source_url: str | None
    source_attachment_key: str | None


def parse_attachment_key(url: str | None) -> str | None:
    """Parse only the measured G2B pre-specification attachment URL shape."""

    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    # ``netloc`` is intentionally exact: a port, userinfo, trailing dot, or
    # alternate host must not become provider provenance by inference.
    if (
        parsed.scheme != "https"
        or parsed.netloc != G2B_HOST
        or parsed.path != G2B_ATTACHMENT_PATH
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        return None
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=False)
    except ValueError:
        return None
    values: dict[str, str] = {}
    for key, value in pairs:
        if key not in _ATTACHMENT_QUERY_KEYS:
            continue
        if key in values or not value:
            return None
        values[key] = value
    if set(values) != _ATTACHMENT_QUERY_KEYS:
        return None
    return f"{values['bfSpecRegNo']}:{values['fileType']}:{values['fileSeq']}"


def _tracked_order_plan_connection(session: Session, notice_id: int) -> bool:
    """Return whether a notice has the exact tracked order-plan path."""

    opportunity_ids = set(
        session.scalars(
            select(OpportunityLink.opportunity_id)
            .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
            .where(
                OpportunityLink.notice_id == notice_id,
                OpportunityLink.stage == "notice",
                OpportunityLink.status.in_(_TRACKING_LINK_STATUSES),
                Opportunity.tracking_status.in_(_TRACKING_STATUSES),
            )
        ).all()
    )
    if not opportunity_ids:
        return False
    return (
        session.scalar(
            select(OpportunityLink.id)
            .where(
                OpportunityLink.opportunity_id.in_(opportunity_ids),
                OpportunityLink.stage == "order_plan",
                OpportunityLink.order_plan_id.is_not(None),
            )
            .limit(1)
        )
        is not None
    )


def _sw_business_object(notice: Notice) -> bool:
    flags = notice.qualification_flags_json
    return isinstance(flags, Mapping) and flags.get("sw_business_status") == "Y"


def refresh_fetch_eligibility(
    session: Session,
    *,
    notice_ids: Sequence[int] | None = None,
) -> int:
    """Create missing fetch rows for currently eligible attachments.

    Existing queue state is intentionally untouched except for the explanation
    of why it is eligible.  In particular, a later re-evaluation never revives
    a completed, blocked, or exhausted row.
    """

    if notice_ids is not None:
        narrowed_ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
        if not narrowed_ids:
            return 0
    else:
        narrowed_ids = ()

    # The loader may have just added notices/attachments while using a session
    # configured with autoflush disabled.  Make the candidate snapshot visible
    # without committing the caller's larger transaction.
    session.flush()
    conditions = [
        Notice.source_type == "pre_spec",
        Attachment.notice_id == Notice.id,
        Attachment.retired_at.is_(None),
        Attachment.source_system == SOURCE_SYSTEM,
        Attachment.source_attachment_key.is_not(None),
        Attachment.source_url.is_not(None),
    ]
    if notice_ids is not None:
        conditions.append(Notice.id.in_(narrowed_ids))
    candidates = session.scalars(
        select(Attachment).join(Notice, Notice.id == Attachment.notice_id).where(*conditions)
    ).all()
    if not candidates:
        return 0

    existing = {
        row.attachment_id: row
        for row in session.scalars(
            select(AttachmentFetch).where(
                AttachmentFetch.attachment_id.in_([row.id for row in candidates])
            )
        ).all()
    }
    created = 0
    next_attempt_at = utc_now()
    for attachment in candidates:
        notice = attachment.notice
        sw = _sw_business_object(notice)
        tracked = _tracked_order_plan_connection(session, notice.id)
        if not sw and not tracked:
            continue
        reason = "both" if sw and tracked else "sw_business_object" if sw else "tracked_order_plan"
        row = existing.get(attachment.id)
        if row is not None:
            if row.eligibility_reason != reason:
                row.eligibility_reason = reason
            continue
        row = AttachmentFetch(
            attachment_id=attachment.id,
            status="대기",
            eligibility_reason=reason,
            attempt_count=0,
            max_attempts=3,
            next_attempt_at=next_attempt_at,
            lease_fence=0,
        )
        session.add(row)
        existing[attachment.id] = row
        created += 1
    session.flush()
    return created


def _validate_worker_id(worker_id: str) -> str:
    clean = worker_id.strip() if isinstance(worker_id, str) else ""
    if not _WORKER_ID_RE.fullmatch(clean):
        raise ValueError("worker_id 형식이 올바르지 않습니다")
    return clean


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def claim_next(
    session: Session,
    *,
    worker_id: str,
    lease_seconds: float,
    now: datetime | None = None,
) -> AttachmentFetchClaim | None:
    """Claim one due or expired row with a PostgreSQL row lock."""

    worker_id = _validate_worker_id(worker_id)
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    current_time = _aware(now)
    if session.in_transaction():
        session.commit()
    row = session.scalar(
        select(AttachmentFetch)
        .where(
            or_(
                (AttachmentFetch.status == "대기")
                & (AttachmentFetch.next_attempt_at <= current_time),
                (AttachmentFetch.status == "진행")
                & AttachmentFetch.lease_expires_at.is_not(None)
                & (AttachmentFetch.lease_expires_at <= current_time),
            )
        )
        .order_by(AttachmentFetch.next_attempt_at.asc(), AttachmentFetch.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        session.commit()
        return None
    row.status = "진행"
    row.lease_owner = worker_id
    row.lease_expires_at = current_time + timedelta(seconds=lease_seconds)
    row.lease_fence = int(row.lease_fence) + 1
    session.flush()
    claim = AttachmentFetchClaim(
        id=row.id,
        attachment_id=row.attachment_id,
        worker_id=worker_id,
        lease_fence=int(row.lease_fence),
    )
    session.commit()
    return claim


def _claim_values(claim: AttachmentFetchClaim) -> tuple[UUID, str, int]:
    fetch_id = getattr(claim, "id", getattr(claim, "fetch_id", None))
    worker_id = getattr(claim, "worker_id", None)
    fence = getattr(claim, "lease_fence", getattr(claim, "fence", None))
    if fetch_id is None or worker_id is None or fence is None:
        raise ValueError("invalid attachment fetch claim")
    return fetch_id, _validate_worker_id(worker_id), int(fence)


def _snapshot(session: Session, claim: AttachmentFetchClaim) -> _AttachmentSnapshot | None:
    fetch_id, worker_id, fence = _claim_values(claim)
    # This is deliberately a read-only, short-lived ORM transaction.  No
    # relationship is carried across the boundary into provider I/O.
    session.rollback()
    row = session.execute(
        select(
            AttachmentFetch.id,
            AttachmentFetch.attachment_id,
            Attachment.notice_id,
            Attachment.source_url,
            Attachment.source_attachment_key,
        )
        .join(Attachment, Attachment.id == AttachmentFetch.attachment_id)
        .where(
            AttachmentFetch.id == fetch_id,
            AttachmentFetch.status == "진행",
            AttachmentFetch.lease_owner == worker_id,
            AttachmentFetch.lease_fence == fence,
        )
    ).one_or_none()
    session.commit()
    if row is None:
        return None
    return _AttachmentSnapshot(
        fetch_id=row[0],
        attachment_id=int(row[1]),
        notice_id=int(row[2]),
        source_url=row[3],
        source_attachment_key=row[4],
    )


def _lock_claim(session: Session, claim: AttachmentFetchClaim) -> AttachmentFetch | None:
    fetch_id, worker_id, fence = _claim_values(claim)
    session.rollback()
    row = session.scalar(
        select(AttachmentFetch)
        .where(
            AttachmentFetch.id == fetch_id,
            AttachmentFetch.status == "진행",
            AttachmentFetch.lease_owner == worker_id,
            AttachmentFetch.lease_fence == fence,
        )
        .with_for_update()
    )
    if row is None:
        session.rollback()
    return row


def _safe_error_code(value: object, *, fallback: str = "processing_failed") -> str:
    if isinstance(value, str) and _SAFE_CODE_RE.fullmatch(value):
        return value
    return fallback


def _safe_warnings(values: Sequence[object]) -> list[str]:
    return [value for value in (str(item) for item in values) if _SAFE_WARNING_RE.fullmatch(value)]


def _backoff_seconds(attempt_count: int) -> int:
    return min(3600, 2 ** max(0, attempt_count - 1))


def _audit(
    session: Session,
    row: AttachmentFetch,
    *,
    status: str,
    error_code: str | None,
) -> None:
    # Only stable internal identifiers and bounded status data are retained.
    # URL, object key, local path, credentials, and exception text are absent.
    session.add(
        AuditEvent(
            actor_kind="system",
            claimed_name=None,
            action="prespec_attachment.fetch",
            aggregate_type="attachment_fetch",
            aggregate_id=str(row.id),
            safe_metadata={
                "attachment_id": int(row.attachment_id),
                "status": status,
                "error_code": error_code,
                "attempt_count": int(row.attempt_count),
                "lease_fence": int(row.lease_fence),
            },
        )
    )


def _transition_failure(
    session: Session,
    claim: AttachmentFetchClaim,
    code: str,
) -> AttachmentFetch | None:
    row = _lock_claim(session, claim)
    if row is None:
        return None
    now = datetime.now(UTC)
    retryable = code in _RETRYABLE_CODES
    if retryable:
        row.attempt_count = int(row.attempt_count) + 1
        if row.attempt_count >= int(row.max_attempts):
            row.status = "실패"
            row.completed_at = now
            final_status = "실패"
        else:
            row.status = "대기"
            row.next_attempt_at = now + timedelta(seconds=_backoff_seconds(row.attempt_count))
            row.completed_at = None
            final_status = "대기"
    else:
        row.status = "차단"
        row.completed_at = now
        final_status = "차단"
    row.last_error_code = code
    row.lease_owner = None
    row.lease_expires_at = None
    _audit(session, row, status=final_status, error_code=code)
    session.commit()
    return row


def _object_key_for_path(path: Path, namespace: str, root: Path | None) -> str:
    base = assets.asset_root(root)
    try:
        relative = path.resolve().relative_to(base)
    except (OSError, ValueError) as exc:
        raise assets.AssetError("processing_failed", "asset location이 격리 루트 밖입니다") from exc
    if not relative.parts or relative.parts[0] != namespace:
        raise assets.AssetError("processing_failed", "asset namespace가 올바르지 않습니다")
    return relative.as_posix()


def _add_location(
    session: Session,
    *,
    content_object_id: UUID,
    namespace: str,
    object_key: str,
    root: Path | None,
) -> None:
    metadata = assets.head_object(namespace, object_key, root=root)
    session.add(
        ContentObjectLocation(
            content_object_id=content_object_id,
            namespace_key=namespace,
            object_key=object_key,
            object_version_id=metadata.object_version_id,
            etag=metadata.etag,
            status="verified",
            verified_at=datetime.now(UTC),
        )
    )


def _ensure_content_object(
    session: Session,
    inspected: assets.InspectedAsset,
) -> ContentObject:
    asset = inspected.asset
    content = session.scalar(select(ContentObject).where(ContentObject.sha256 == asset.sha256))
    if content is None:
        content = ContentObject(
            sha256=asset.sha256,
            size_bytes=asset.size_bytes,
            detected_mime=inspected.detected_mime or "application/octet-stream",
            retention_class="document-source",
        )
        session.add(content)
        session.flush()
    return content


def _persist_inspected(
    session: Session,
    claim: AttachmentFetchClaim,
    snapshot: _AttachmentSnapshot,
    inspected: assets.InspectedAsset,
    *,
    root: Path | None,
) -> AttachmentFetch | None:
    code = _safe_error_code(
        inspected.error_code
        or ("clamav_unavailable" if inspected.scan_status == "unavailable" else None),
        fallback="unsafe_document",
    )
    row = _lock_claim(session, claim)
    if row is None:
        return None
    content = _ensure_content_object(session, inspected)
    asset = inspected.asset
    quarantine_key = asset.object_key or _object_key_for_path(asset.path, "quarantine", root)
    _add_location(
        session,
        content_object_id=content.id,
        namespace="quarantine",
        object_key=quarantine_key,
        root=root,
    )
    scan_status = inspected.scan_status if inspected.scan_status in {"pending", "clean", "infected", "unavailable", "error"} else "error"
    session.add(
        ContentScan(
            content_object_id=content.id,
            scanner="clamav",
            scanner_version="clamav-instream-v1",
            status=scan_status,
            safe_result={
                "code": code,
                "warnings": _safe_warnings(inspected.warnings),
            },
        )
    )
    row.last_error_code = code
    row.lease_owner = None
    row.lease_expires_at = None
    if code in _RETRYABLE_CODES:
        row.attempt_count = int(row.attempt_count) + 1
        if row.attempt_count >= int(row.max_attempts):
            row.status = "실패"
            row.completed_at = datetime.now(UTC)
            final_status = "실패"
        else:
            row.status = "대기"
            row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=_backoff_seconds(row.attempt_count))
            row.completed_at = None
            final_status = "대기"
    else:
        row.status = "차단"
        row.completed_at = datetime.now(UTC)
        final_status = "차단"
    _audit(session, row, status=final_status, error_code=code)
    session.commit()
    return row


def _document_for_safe_asset(
    session: Session,
    *,
    row: AttachmentFetch,
    snapshot: _AttachmentSnapshot,
    inspected: assets.InspectedAsset,
    source_path: Path,
    root: Path | None,
) -> DocumentVersion:
    content = _ensure_content_object(session, inspected)
    asset = inspected.asset
    quarantine_key = asset.object_key or _object_key_for_path(asset.path, "quarantine", root)
    _add_location(
        session,
        content_object_id=content.id,
        namespace="quarantine",
        object_key=quarantine_key,
        root=root,
    )
    session.add(
        ContentScan(
            content_object_id=content.id,
            scanner="clamav",
            scanner_version="clamav-instream-v1",
            status="clean",
            safe_result={"code": None, "warnings": _safe_warnings(inspected.warnings)},
        )
    )
    source_key = _object_key_for_path(source_path, "source", root)
    _add_location(
        session,
        content_object_id=content.id,
        namespace="source",
        object_key=source_key,
        root=root,
    )

    versions = session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.attachment_id == snapshot.attachment_id)
        .order_by(DocumentVersion.version.desc(), DocumentVersion.id.desc())
        .with_for_update()
    ).all()
    current = next((version for version in versions if version.is_current), None)
    if current is not None:
        current_content = session.get(ContentObject, current.content_object_id)
        if current_content is not None and current_content.sha256 == asset.sha256:
            return current
        session.execute(
            update(DocumentVersion)
            .where(
                DocumentVersion.attachment_id == snapshot.attachment_id,
                DocumentVersion.is_current.is_(True),
            )
            .values(is_current=False)
        )
    previous = versions[0] if versions else None
    document = DocumentVersion(
        notice_id=snapshot.notice_id,
        attachment_id=snapshot.attachment_id,
        content_object_id=content.id,
        version=(int(previous.version) + 1) if previous is not None else 1,
        source_kind="provider",
        source_system=SOURCE_SYSTEM,
        source_attachment_key=snapshot.source_attachment_key,
        source_url=snapshot.source_url,
        original_filename=asset.filename,
        role="기타",
        replaces_document_version_id=current.id if current is not None else None,
        is_current=True,
        safety_status="safe",
        needs_human_review=False,
        created_by_name=None,
    )
    session.add(document)
    session.flush()
    return document


def _complete_safe(
    session: Session,
    claim: AttachmentFetchClaim,
    snapshot: _AttachmentSnapshot,
    inspected: assets.InspectedAsset,
    *,
    source_path: Path,
    root: Path | None,
) -> AttachmentFetch | None:
    row = _lock_claim(session, claim)
    if row is None:
        return None
    document = _document_for_safe_asset(
        session,
        row=row,
        snapshot=snapshot,
        inspected=inspected,
        source_path=source_path,
        root=root,
    )
    row.status = "완료"
    row.last_error_code = None
    row.document_version_id = document.id
    row.lease_owner = None
    row.lease_expires_at = None
    row.completed_at = datetime.now(UTC)
    _audit(session, row, status="완료", error_code=None)
    session.commit()
    return row


def fetch_claimed(
    session: Session,
    claim: AttachmentFetchClaim,
    *,
    connectors: Mapping[str, Any],
    processor: Any = None,
    clamav_checker: Any = None,
    root: Path | None = None,
) -> AttachmentFetch | None:
    """Fetch, inspect, promote, and record one claimed attachment."""

    snapshot = _snapshot(session, claim)
    if snapshot is None:
        return None
    asset: assets.QuarantinedAsset | None = None
    try:
        if not snapshot.source_url or not snapshot.source_attachment_key:
            return _transition_failure(session, claim, "processing_failed")
        asset = assets.acquire_provider_attachment(
            source_system=SOURCE_SYSTEM,
            source_url=snapshot.source_url,
            source_attachment_key=snapshot.source_attachment_key,
            filename=None,
            connectors=connectors,
            root=root,
        )
        inspected = assets.inspect_quarantine(
            asset,
            processor=processor,
            clamav_checker=clamav_checker,
        )
        if inspected.safety_status != "safe":
            return _persist_inspected(
                session,
                claim,
                snapshot,
                inspected,
                root=root,
            )
        source_path, digest, size = assets.commit_source(asset, root=root)
        if digest != asset.sha256 or size != asset.size_bytes:
            raise assets.AssetError("hash_mismatch", "원문 hash 검증에 실패했습니다")
        return _complete_safe(
            session,
            claim,
            snapshot,
            inspected,
            source_path=source_path,
            root=root,
        )
    except assets.AssetError as error:
        code = _safe_error_code(error.code)
        return _transition_failure(session, claim, code)
    except DocumentProcessingError as error:
        code = _safe_error_code(error.code)
        return _transition_failure(session, claim, code)
    except Exception:
        # Exception text is intentionally discarded at this boundary.  A
        # provider, scanner, or storage adapter failure receives one stable
        # retry code and no URL/path/credential can reach the database.
        return _transition_failure(session, claim, "service_unavailable")
    finally:
        try:
            assets.cleanup_asset(asset)
        except Exception:
            # Cleanup is best effort and must not expose a local path or mask a
            # durable queue transition.  Storage reconciliation handles a
            # failed delete.
            pass


__all__ = [
    "AttachmentFetchClaim",
    "G2B_ATTACHMENT_PATH",
    "G2B_HOST",
    "SOURCE_SYSTEM",
    "claim_next",
    "fetch_claimed",
    "parse_attachment_key",
    "refresh_fetch_eligibility",
]
