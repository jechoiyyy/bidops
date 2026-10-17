"""Eligibility, leasing, and backend fetching for pre-specification assets.

The service keeps provider and document I/O outside database transactions.  A
claim is a small lease fence; after I/O, every write rechecks that fence before
it records a source object or document version.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, selectinload

from ..document_mcp.errors import DocumentProcessingError
from ...core.constants import UNSUPPORTED_ATTACHMENT_EXTRACT_STATUS
from ...core.models import AuditEvent, utc_now
from ..models import (
    AttachmentFetch,
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentVersion,
)
from ...lifecycle.models import Attachment, Notice
from . import assets
from .document_structures import materialize_structure
# 추적 관계 판정은 lifecycle 몫이다(명세 §5.2). 취득 자격은 그 공개 SQL 조각을
# 그대로 쓰므로 목록의 표시 예외와 어긋나지 않는다.
from ...lifecycle import lock_attachment, tracked_order_plan_connections
from .auto_preparation import (
    OPERATOR_LOCAL_ORIGINAL_TRIGGER,
    TERMINAL_FETCH_STATUSES,
    maybe_auto_prepare,
)
from .effective_grade import priority_notice_ids


SOURCE_SYSTEM = "g2b"
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
        "ocr_unavailable",
        "renderer_unavailable",
        "converter_unavailable",
        "timeout",
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
        "archive_file_limit",
        "archive_member_limit",
        "archive_ratio_limit",
        "archive_depth_limit",
        "block_limit",
        "invalid_attribute",
        "invalid_input",
        "invalid_options",
        "invalid_structure",
        "unsafe_attribute",
        "unsafe_xml",
        "xml_depth_limit",
        "encrypted_pdf",
        "pdf_object_limit",
        "pdf_page_limit",
        "pdf_page_mismatch",
        "pdf_empty_text",
        "malformed_image",
        "ocr_failed",
        "render_failed",
        "unsupported_media",
        "encrypted_archive",
        "archive_duplicate",
        "archive_link",
        "archive_traversal",
        "legacy_non_regular",
        "legacy_path_blocked",
        "legacy_size_limit",
        "legacy_size_mismatch",
        "legacy_source_changed",
        "legacy_source_missing",
        "legacy_symlink_blocked",
    }
)
_SAFE_ERROR_CODES = _RETRYABLE_CODES | _TERMINAL_CODES


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
    # ``None`` only for the operator local-original path when the attachment
    # has no fetch row (B15); the provider path always carries its claim row.
    fetch_id: UUID | None
    attachment_id: int
    notice_id: int
    source_url: str | None
    source_attachment_key: str | None
    name: str | None
    file_ext: str | None


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

    자격은 세 가지다 — SW사업대상, 추적 중인 발주계획 연결, 그리고 effective
    grade가 `우선 검토`인 사전규격(명세 §6.2). 등급이 내려가도 이미 만들어진
    행은 지우거나 되돌리지 않는다: 등급을 잃은 공고는 그저 새 행을 얻지 못한다.
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
        select(Attachment)
        .join(Notice, Notice.id == Attachment.notice_id)
        .where(*conditions)
        .options(selectinload(Attachment.notice))
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
    candidate_notice_ids = {attachment.notice_id for attachment in candidates}
    tracked_connections = tracked_order_plan_connections(
        session,
        notice_ids=candidate_notice_ids,
    )
    # 판정 등급 자격 (명세 §6.2 "자격"). 선별 seam을 batch로 **한 번만** 부른다 —
    # 회차 하나가 사전규격 약 2,000건이므로 공고당 조회를 만들지 않는다.
    #
    # §5의 결합 규칙에서 기존 사유는 등급 사유를 언제나 이기므로, SW나 추적으로
    # 이미 자격이 있는 후보의 등급은 결과를 바꾸지 못한다. 그래서 등급을 물어야
    # 하는 공고가 하나도 없으면 seam을 아예 부르지 않는다.
    sw_notice_ids = {
        attachment.notice_id
        for attachment in candidates
        if _sw_business_object(attachment.notice)
    }
    grade_candidates = sorted(
        notice_id
        for notice_id in candidate_notice_ids
        if notice_id not in sw_notice_ids and not tracked_connections.get(notice_id)
    )
    priority_ids = priority_notice_ids(session, grade_candidates) if grade_candidates else frozenset()
    created = 0
    next_attempt_at = utc_now()
    for attachment in candidates:
        notice = attachment.notice
        sw = _sw_business_object(notice)
        tracked = bool(tracked_connections.get(notice.id))
        priority = notice.id in priority_ids
        if not sw and not tracked and not priority:
            continue
        # §5 결합 규칙: 기존 사유가 등급 사유보다 우선한다. 등급은 아무 사유도
        # 없을 때만 `priority_grade`로 나타나고, SW·추적과 겹치면 그쪽 사유가
        # 그대로 남는다(등급이 `both`를 만들지 않는다).
        reason = (
            "both"
            if sw and tracked
            else "sw_business_object"
            if sw
            else "tracked_order_plan"
            if tracked
            else "priority_grade"
        )
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


def validate_notice_id(notice_id: int | None) -> int | None:
    """Validate the optional worker-only queue scope before database access."""

    if notice_id is None:
        return None
    if isinstance(notice_id, bool) or not isinstance(notice_id, int) or notice_id <= 0:
        raise ValueError("notice_id must be a positive integer")
    return notice_id


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
    notice_id: int | None = None,
) -> AttachmentFetchClaim | None:
    """Claim one due or expired row with a PostgreSQL row lock."""

    notice_id = validate_notice_id(notice_id)
    worker_id = _validate_worker_id(worker_id)
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    current_time = _aware(now)
    if session.in_transaction():
        session.commit()
    candidate = select(AttachmentFetch).where(
        or_(
            (AttachmentFetch.status == "대기")
            & (AttachmentFetch.next_attempt_at <= current_time),
            (AttachmentFetch.status == "진행")
            & AttachmentFetch.lease_expires_at.is_not(None)
            & (AttachmentFetch.lease_expires_at <= current_time),
        )
    )
    if notice_id is not None:
        candidate = candidate.where(
            AttachmentFetch.attachment_id.in_(
                select(Attachment.id).where(Attachment.notice_id == notice_id)
            )
        )
    row = session.scalar(
        candidate
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
            Attachment.name,
            Attachment.file_ext,
        )
        .join(Attachment, Attachment.id == AttachmentFetch.attachment_id)
        .where(
            AttachmentFetch.id == fetch_id,
            AttachmentFetch.attachment_id == int(claim.attachment_id),
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
        name=row[5],
        file_ext=row[6],
    )


def _lock_claim(session: Session, claim: AttachmentFetchClaim) -> AttachmentFetch | None:
    fetch_id, worker_id, fence = _claim_values(claim)
    session.rollback()
    row = session.scalar(
        select(AttachmentFetch)
        .where(
            AttachmentFetch.id == fetch_id,
            AttachmentFetch.attachment_id == int(claim.attachment_id),
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
    if isinstance(value, str) and _SAFE_CODE_RE.fullmatch(value) and value in _SAFE_ERROR_CODES:
        return value
    return fallback


def _safe_warnings(values: Sequence[object]) -> list[str]:
    return [value for value in (str(item) for item in values) if _SAFE_WARNING_RE.fullmatch(value)]


_BACKOFF_SCHEDULE = (60, 300, 900)


def _backoff_seconds(attempt_count: int) -> int:
    if attempt_count <= 0:
        return _BACKOFF_SCHEDULE[0]
    return _BACKOFF_SCHEDULE[min(attempt_count, 3) - 1]


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


def _apply_failure_outcome(row: AttachmentFetch, code: str, now: datetime) -> str:
    """Apply the retry/terminal judgment shared by the two failure paths.

    재시도 코드면 attempt_count를 늘려 max 도달 시 `실패`, 아니면 `대기`로
    돌려 backoff를 다시 잡는다. 재시도 코드가 아니면 `차단`으로 끝낸다.
    `_transition_failure`(제공자·처리 오류)와 `_persist_inspected`(격리 검사
    이후 오류)가 이 판정을 그대로 공유한다.
    """

    if code in _RETRYABLE_CODES:
        row.attempt_count = int(row.attempt_count) + 1
        if row.attempt_count >= int(row.max_attempts):
            row.status = "실패"
            row.completed_at = now
            return "실패"
        row.status = "대기"
        row.next_attempt_at = now + timedelta(seconds=_backoff_seconds(row.attempt_count))
        row.completed_at = None
        return "대기"
    row.status = "차단"
    row.completed_at = now
    return "차단"


def _transition_failure(
    session: Session,
    claim: AttachmentFetchClaim,
    code: str,
) -> AttachmentFetch | None:
    row = _lock_claim(session, claim)
    if row is None:
        return None
    now = datetime.now(UTC)
    final_status = _apply_failure_outcome(row, code, now)
    row.last_error_code = code
    row.lease_owner = None
    row.lease_expires_at = None
    if final_status == "차단" and code == "unsupported_extension":
        # 형식 밖 첨부는 취득으로는 `차단`이지만 **문서 묶음 확정을 막지 않는다**
        # (명세 §6.2). 묶음 issue 계산이 이 값을 보고 비차단
        # `unsupported_attachment_excluded`를 남긴다. 첨부 잠금은 lifecycle
        # 공개 함수로만 한다(§4).
        #
        # lease 열을 비운 **뒤에** 잠근다. `lock_attachment`의 autoflush가
        # `(status='진행') = (lease_owner IS NOT NULL ...)` CHECK를 반쯤 바뀐
        # 상태에서 보게 두면 안 되기 때문이다.
        attachment = lock_attachment(session, row.attachment_id)
        if attachment is not None:
            attachment.extract_status = UNSUPPORTED_ATTACHMENT_EXTRACT_STATUS
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


def _add_structure_location(
    session: Session,
    content_id: UUID,
    namespace: str,
    path: Path,
    digest: str,
    *,
    root: Path | None,
) -> None:
    """Adapt the canonical path-based structure writer to object-key storage."""

    object_key = _object_key_for_path(path, namespace, root)
    _add_location(
        session,
        content_object_id=content_id,
        namespace=namespace,
        object_key=object_key,
        root=root,
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
    final_status = _apply_failure_outcome(row, code, datetime.now(UTC))
    _audit(session, row, status=final_status, error_code=code)
    session.commit()
    return row


def _document_for_safe_asset(
    session: Session,
    *,
    row: AttachmentFetch | None,
    snapshot: _AttachmentSnapshot,
    inspected: assets.InspectedAsset,
    source_path: Path,
    root: Path | None,
    created_by_name: str | None = None,
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
        # The current-row partial unique index is immediate.  Make the
        # demotion visible before the replacement row is inserted.
        session.flush()
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
        created_by_name=created_by_name,
    )
    session.add(document)
    session.flush()
    return document


def _materialize_safe_document(
    session: Session,
    *,
    row: AttachmentFetch | None,
    snapshot: _AttachmentSnapshot,
    inspected: assets.InspectedAsset,
    source_path: Path,
    root: Path | None,
    request_paths: list[Path],
    created_by_name: str | None = None,
) -> DocumentVersion:
    """Record the clean source document and its canonical structure (no commit).

    The provider fetch and the operator local-original path (B15) share this
    so both keep one quarantine → scan → source → document → structure rule.
    """

    document = _document_for_safe_asset(
        session,
        row=row,
        snapshot=snapshot,
        inspected=inspected,
        source_path=source_path,
        root=root,
        created_by_name=created_by_name,
    )
    materialize_structure(
        session,
        document,
        inspected.asset,
        inspected,
        request_paths,
        root=root,
        add_location=lambda current_session, content_id, namespace, path, digest: _add_structure_location(
            current_session,
            content_id,
            namespace,
            path,
            digest,
            root=root,
        ),
    )
    return document


def _complete_safe(
    session: Session,
    claim: AttachmentFetchClaim,
    snapshot: _AttachmentSnapshot,
    inspected: assets.InspectedAsset,
    *,
    source_path: Path,
    root: Path | None,
    request_paths: list[Path],
) -> AttachmentFetch | None:
    row = _lock_claim(session, claim)
    if row is None:
        return None
    attachment = lock_attachment(session, row.attachment_id)
    if (
        attachment is None
        or row.attachment_id != snapshot.attachment_id
        or attachment.notice_id != snapshot.notice_id
        or attachment.source_system != SOURCE_SYSTEM
        or attachment.source_attachment_key != snapshot.source_attachment_key
        or attachment.source_url != snapshot.source_url
        or attachment.retired_at is not None
    ):
        # Provider I/O ran against an obsolete provenance snapshot.  Leave
        # the durable queue state untouched; the caller rolls this lock
        # transaction back and removes request-created source bytes.
        session.rollback()
        return None
    document = _materialize_safe_document(
        session,
        row=row,
        snapshot=snapshot,
        inspected=inspected,
        source_path=source_path,
        root=root,
        request_paths=request_paths,
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
    """Fetch, inspect, promote, and record one claimed attachment.

    취득 행이 종결(`완료|차단|실패`)되면 그 공고의 자동 문서 준비 조건을 다시
    본다(명세 §6.2). 자동 준비는 파생 작업이라 자기 실패를 삼키며, 취득 결과를
    되돌리지 않는다 — 이 함수의 반환값은 자동 준비 성패와 무관하다.
    """

    row = _fetch_claimed(
        session,
        claim,
        connectors=connectors,
        processor=processor,
        clamav_checker=clamav_checker,
        root=root,
    )
    if row is not None and row.status in TERMINAL_FETCH_STATUSES:
        notice_id = session.scalar(
            select(Attachment.notice_id).where(Attachment.id == row.attachment_id)
        )
        # 위 조회가 연 읽기 transaction을 닫는다.
        session.commit()
        if notice_id is not None:
            maybe_auto_prepare(session, [int(notice_id)], root=root)
            # 자동 준비는 자격 조회가 다시 연 transaction의 savepoint session에서
            # 돈다(`_work_session`). 그 commit은 savepoint만 놓으므로 여기서 바깥
            # transaction을 커밋해야 묶음·감사가 durable하다 — worker는 poll마다
            # session을 닫으므로(`--once` 포함) 그대로 두면 close의 rollback이
            # 방금 만든 묶음을 지운다(B18 확인).
            try:
                session.commit()
            except Exception:
                session.rollback()
    return row


def _fetch_claimed(
    session: Session,
    claim: AttachmentFetchClaim,
    *,
    connectors: Mapping[str, Any],
    processor: Any = None,
    clamav_checker: Any = None,
    root: Path | None = None,
) -> AttachmentFetch | None:
    """One claimed attachment: acquire, inspect, promote, record."""

    snapshot = _snapshot(session, claim)
    if snapshot is None:
        return None
    asset: assets.QuarantinedAsset | None = None
    request_paths: list[Path] = []
    try:
        if not snapshot.source_url or not snapshot.source_attachment_key:
            return _transition_failure(session, claim, "processing_failed")
        asset = assets.acquire_provider_attachment(
            source_system=SOURCE_SYSTEM,
            source_url=snapshot.source_url,
            source_attachment_key=snapshot.source_attachment_key,
            filename=None,
            fallback_filename=snapshot.name,
            connectors=connectors,
            root=root,
        )
        processor_checker = getattr(processor, "clamav_checker", None)
        if clamav_checker is None and processor_checker is None:
            # Keep the inspection seam and fail before any document
            # conversion/parsing when no scanner has been supplied.  The
            # worker normally provides a real ClamAV checker; this fallback
            # makes direct adapters fail closed without processing bytes.
            def unavailable_checker(_content: bytes) -> bool:
                raise DocumentProcessingError(
                    "clamav_unavailable", "malware 검사를 완료할 수 없습니다"
                )

            processor = None
            clamav_checker = unavailable_checker
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
        request_paths.append(source_path)
        if digest != asset.sha256 or size != asset.size_bytes:
            raise assets.AssetError("hash_mismatch", "원문 hash 검증에 실패했습니다")
        result = _complete_safe(
            session,
            claim,
            snapshot,
            inspected,
            source_path=source_path,
            root=root,
            request_paths=request_paths,
        )
        if result is None:
            # The lease may have been lost while provider I/O was in flight;
            # no durable writer owns these newly-created source bytes then.
            session.rollback()
            assets.cleanup_paths(request_paths)
        return result
    except assets.AssetError as error:
        session.rollback()
        assets.cleanup_paths(request_paths)
        code = _safe_error_code(error.code)
        return _transition_failure(session, claim, code)
    except DocumentProcessingError as error:
        session.rollback()
        assets.cleanup_paths(request_paths)
        code = _safe_error_code(error.code)
        return _transition_failure(session, claim, code)
    except Exception:
        # Exception text is intentionally discarded at this boundary.  A
        # provider, scanner, or storage adapter failure receives one stable
        # retry code and no URL/path/credential can reach the database.
        session.rollback()
        assets.cleanup_paths(request_paths)
        return _transition_failure(session, claim, "service_unavailable")
    finally:
        try:
            assets.cleanup_asset(asset)
        except Exception:
            # Cleanup is best effort and must not expose a local path or mask a
            # durable queue transition.  Storage reconciliation handles a
            # failed delete.
            pass


# --- operator local original (RL-03 결정 B15) ----------------------------------------
#
# A G2B attachment row may carry only a link (no bytes) while the operator holds
# the original file whose sha256 was matched against an earlier collection.
# ``attach_local_original`` connects those bytes to the *existing* attachment row
# through the same quarantine → ClamAV/MIME inspection → source → document →
# structure path the provider fetch uses, and then opens document preparation for
# the notice with trigger ``operator_local_original``.  No G2B call is made.  The
# only gate it bypasses is the grade/briefing eligibility of the preparation; the
# attachment must belong to the notice, be a current G2B row and have no bytes.

LOCAL_ORIGINAL_PROVENANCE = OPERATOR_LOCAL_ORIGINAL_TRIGGER
LOCAL_ORIGINAL_ACTION = "prespec_attachment.local_original"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTOR_MAX = 128
_LOCAL_READ_CHUNK = 1024 * 1024


class LocalOriginalError(ValueError):
    """Stable, path-free code of a refused or failed local-original attach."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True)
class LocalOriginalTarget:
    notice_id: int
    attachment_id: int
    filename: str
    source_attachment_key: str
    source_url: str
    fetch_id: UUID | None
    fetch_status: str | None


def _operator_actor(value: str | None) -> str:
    if value is None or not value.strip():
        raise LocalOriginalError("actor_name_required")
    clean = value.strip()
    if (
        len(clean) > _ACTOR_MAX
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in clean)
        or clean.lower() == "system"
        or clean.lower().startswith("system:")
    ):
        raise LocalOriginalError("actor_name_invalid")
    return clean


def read_operator_file(path: Path) -> bytes:
    """Read one operator-supplied regular file with the attachment size cap.

    The path itself (not only its target) must be a regular file: a symlink,
    directory, device or FIFO is refused before it is opened.  The descriptor
    is opened with ``O_NOFOLLOW`` and its identity is compared with the
    pre-open ``lstat`` so a swap between the check and the read fails closed.
    Error codes never carry the path.
    """

    try:
        before = os.lstat(path)
    except OSError:
        raise LocalOriginalError("file_not_found") from None
    if not stat.S_ISREG(before.st_mode):
        raise LocalOriginalError("file_not_regular")
    if before.st_size > assets.MAX_ASSET_BYTES:
        raise LocalOriginalError("file_size_limit")
    if before.st_size == 0:
        raise LocalOriginalError("file_empty")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise LocalOriginalError("file_not_regular") from None
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino, opened.st_size) != (before.st_dev, before.st_ino, before.st_size)
        ):
            raise LocalOriginalError("file_changed")
        chunks: list[bytes] = []
        total = 0
        while True:
            blob = os.read(fd, _LOCAL_READ_CHUNK)
            if not blob:
                break
            total += len(blob)
            if total > assets.MAX_ASSET_BYTES:
                raise LocalOriginalError("file_size_limit")
            chunks.append(blob)
        if total != before.st_size:
            raise LocalOriginalError("file_changed")
        return b"".join(chunks)
    except OSError:
        raise LocalOriginalError("file_changed") from None
    finally:
        os.close(fd)


def _local_original_target(
    session: Session,
    *,
    notice_id: int,
    attachment: Attachment | None,
    fallback_filename: str | None,
    lock_fetch: bool = False,
) -> tuple[LocalOriginalTarget, AttachmentFetch | None]:
    """Every refusal of the attach, read (or re-read under locks) from the rows."""

    if attachment is None:
        raise LocalOriginalError("attachment_not_found")
    if int(attachment.notice_id) != int(notice_id):
        raise LocalOriginalError("attachment_notice_mismatch")
    notice = session.get(Notice, int(notice_id))
    if notice is None:
        raise LocalOriginalError("notice_not_found")
    if notice.source_type != "pre_spec":
        # Document preparation and RL card analysis are pre-spec only (RL-03 범위).
        raise LocalOriginalError("notice_not_pre_spec")
    if attachment.retired_at is not None:
        raise LocalOriginalError("attachment_retired")
    if (
        attachment.source_system != SOURCE_SYSTEM
        or not attachment.source_attachment_key
        or not attachment.source_url
    ):
        raise LocalOriginalError("attachment_source_not_g2b")
    has_document = session.scalar(
        select(DocumentVersion.id).where(DocumentVersion.attachment_id == attachment.id).limit(1)
    )
    if has_document is not None:
        raise LocalOriginalError("attachment_has_bytes")
    fetch_query = select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id)
    if lock_fetch:
        fetch_query = fetch_query.with_for_update()
    fetch = session.scalar(fetch_query)
    if fetch is not None:
        if fetch.status == "완료" or fetch.document_version_id is not None:
            raise LocalOriginalError("attachment_has_bytes")
        if fetch.status == "진행":
            # A provider worker holds (or held) the lease; never race it.
            raise LocalOriginalError("attachment_fetch_in_progress")
    # The G2B fetcher prefers the provider's file name over the stored row name; the
    # operator's local file name plays that role here. G2B rows often store a
    # placeholder such as "첨부 1" with no extension, so the stored name is only a
    # fallback (결정 B22).
    filename = None
    for name in (fallback_filename, attachment.name):
        if not name:
            continue
        try:
            filename = assets._safe_filename(name)
            break
        except assets.AssetError:
            continue
    if filename is None:
        raise LocalOriginalError("unsupported_extension")
    return (
        LocalOriginalTarget(
            notice_id=int(notice_id),
            attachment_id=int(attachment.id),
            filename=filename,
            source_attachment_key=str(attachment.source_attachment_key),
            source_url=str(attachment.source_url),
            fetch_id=fetch.id if fetch is not None else None,
            fetch_status=fetch.status if fetch is not None else None,
        ),
        fetch,
    )


def _local_original_audit(
    session: Session,
    *,
    actor: str,
    target: LocalOriginalTarget,
    content_sha256: str,
    size_bytes: int,
    status: str,
    error_code: str | None,
    scan_status: str | None,
    document_version_id: UUID | None,
) -> None:
    # Safe identifiers only: no local path, file name, URL, object key or text.
    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=actor,
            action=LOCAL_ORIGINAL_ACTION,
            aggregate_type="attachment",
            aggregate_id=str(target.attachment_id),
            safe_metadata={
                "provenance": LOCAL_ORIGINAL_PROVENANCE,
                "notice_id": target.notice_id,
                "attachment_id": target.attachment_id,
                "attachment_fetch_id": str(target.fetch_id) if target.fetch_id is not None else None,
                "fetch_status_before": target.fetch_status,
                "content_sha256": content_sha256,
                "size_bytes": size_bytes,
                "scan_status": scan_status,
                "status": status,
                "error_code": error_code,
                "document_version_id": str(document_version_id) if document_version_id is not None else None,
            },
        )
    )


def _preparation_view(outcome: Any) -> dict[str, Any]:
    if outcome is None:
        return {"bundle_id": None, "created": False, "confirmed": False, "reason": "processing_failed"}
    return {
        "bundle_id": str(outcome.bundle_id) if outcome.bundle_id is not None else None,
        "created": bool(outcome.created),
        "confirmed": bool(outcome.confirmed),
        "reason": outcome.reason,
    }


def attach_local_original(
    session: Session,
    *,
    notice_id: int,
    attachment_id: int,
    content: bytes,
    expected_sha256: str,
    actor: str | None,
    fallback_filename: str | None = None,
    processor: Any = None,
    clamav_checker: Any = None,
    root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Connect operator-held original bytes to an existing G2B attachment row (B15).

    Refusals (``LocalOriginalError``, nothing written): actor, sha format,
    ``sha256_mismatch``, attachment/notice ownership, retired, non-G2B source,
    ``attachment_has_bytes`` (any document version or a completed fetch row),
    ``attachment_fetch_in_progress``, ``unsupported_extension``.  ``dry_run``
    stops after these checks.  Inspection failures (malware, MIME, scanner
    unavailable) write one refusal audit and no document.  On success the
    document, its structure, the fetch row (``완료``, fence +1) and the audit
    commit together; then ``maybe_auto_prepare`` runs with trigger
    ``operator_local_original`` (bypassing only grade/briefing eligibility).
    """

    claimed = _operator_actor(actor)
    expected = expected_sha256.strip().lower() if isinstance(expected_sha256, str) else ""
    if _SHA256_RE.fullmatch(expected) is None:
        raise LocalOriginalError("expected_sha256_invalid")
    if not isinstance(content, (bytes, bytearray)) or not content:
        raise LocalOriginalError("file_empty")
    if len(content) > assets.MAX_ASSET_BYTES:
        raise LocalOriginalError("file_size_limit")
    data = bytes(content)
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise LocalOriginalError("sha256_mismatch")
    try:
        notice_id = int(validate_notice_id(notice_id))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise LocalOriginalError("notice_not_found") from None
    if isinstance(attachment_id, bool) or not isinstance(attachment_id, int) or attachment_id <= 0:
        raise LocalOriginalError("attachment_not_found")

    if session.in_transaction():
        session.rollback()
    target, _fetch = _local_original_target(
        session, notice_id=notice_id, attachment=session.get(Attachment, attachment_id),
        fallback_filename=fallback_filename,
    )
    # Close the read transaction before any storage or scanner I/O.
    session.rollback()
    result: dict[str, Any] = {
        "notice_id": target.notice_id,
        "attachment_id": target.attachment_id,
        "content_sha256": digest,
        "size_bytes": len(data),
        "provenance": LOCAL_ORIGINAL_PROVENANCE,
        "fetch_status_before": target.fetch_status,
        "document_version_id": None,
        "scan_status": None,
        "preparation": None,
        "dry_run": bool(dry_run),
        "errors": [],
    }
    if dry_run:
        return result

    asset: assets.QuarantinedAsset | None = None
    request_paths: list[Path] = []
    try:
        asset = assets.quarantine_bytes(
            data,
            target.filename,
            declared_media_type=None,
            root=root,
            source_kind="provider",
            source_system=SOURCE_SYSTEM,
            source_attachment_key=target.source_attachment_key,
            source_url=target.source_url,
        )
        if asset.sha256 != digest or asset.size_bytes != len(data):
            raise LocalOriginalError("hash_mismatch")
        if clamav_checker is None and getattr(processor, "clamav_checker", None) is None:
            # Same fail-closed seam as the provider fetch: no scanner, no parsing.
            def unavailable_checker(_content: bytes) -> bool:
                raise DocumentProcessingError("clamav_unavailable", "malware 검사를 완료할 수 없습니다")

            processor = None
            clamav_checker = unavailable_checker
        inspected = assets.inspect_quarantine(asset, processor=processor, clamav_checker=clamav_checker)
        result["scan_status"] = inspected.scan_status
        if inspected.safety_status != "safe":
            code = _safe_error_code(
                inspected.error_code
                or ("clamav_unavailable" if inspected.scan_status == "unavailable" else None),
                fallback="unsafe_document",
            )
            _local_original_audit(
                session, actor=claimed, target=target, content_sha256=digest, size_bytes=len(data),
                status="차단", error_code=code, scan_status=inspected.scan_status, document_version_id=None,
            )
            session.commit()
            raise LocalOriginalError(code, retryable=code in _RETRYABLE_CODES)
        source_path, source_digest, source_size = assets.commit_source(asset, root=root)
        request_paths.append(source_path)
        if source_digest != digest or source_size != len(data):
            raise LocalOriginalError("hash_mismatch")

        # One fenced transaction: lock the attachment (lifecycle public lock),
        # re-check every refusal on the locked rows, then record.
        attachment = lock_attachment(session, target.attachment_id, populate_existing=True)
        locked, fetch = _local_original_target(
            session, notice_id=notice_id, attachment=attachment, fallback_filename=fallback_filename,
            lock_fetch=True,
        )
        if (locked.source_attachment_key, locked.source_url, locked.filename) != (
            target.source_attachment_key, target.source_url, target.filename,
        ):
            raise LocalOriginalError("attachment_changed")
        snapshot = _AttachmentSnapshot(
            fetch_id=locked.fetch_id,
            attachment_id=locked.attachment_id,
            notice_id=locked.notice_id,
            source_url=locked.source_url,
            source_attachment_key=locked.source_attachment_key,
            name=locked.filename,
            file_ext=None,
        )
        document = _materialize_safe_document(
            session,
            row=fetch,
            snapshot=snapshot,
            inspected=inspected,
            source_path=source_path,
            root=root,
            request_paths=request_paths,
            created_by_name=claimed,
        )
        if fetch is not None:
            fetch.status = "완료"
            fetch.last_error_code = None
            fetch.document_version_id = document.id
            fetch.lease_owner = None
            fetch.lease_expires_at = None
            # A stale provider claim of this row can no longer write.
            fetch.lease_fence = int(fetch.lease_fence) + 1
            fetch.completed_at = datetime.now(UTC)
        _local_original_audit(
            session, actor=claimed, target=locked, content_sha256=digest, size_bytes=len(data),
            status="완료", error_code=None, scan_status=inspected.scan_status, document_version_id=document.id,
        )
        session.commit()
        result["document_version_id"] = str(document.id)
    except LocalOriginalError as error:
        if session.in_transaction():
            session.rollback()
        assets.cleanup_paths(request_paths)
        raise error
    except assets.AssetError as error:
        session.rollback()
        assets.cleanup_paths(request_paths)
        code = _safe_error_code(error.code)
        raise LocalOriginalError(code, retryable=code in _RETRYABLE_CODES) from None
    except DocumentProcessingError as error:
        session.rollback()
        assets.cleanup_paths(request_paths)
        code = _safe_error_code(error.code)
        raise LocalOriginalError(code, retryable=code in _RETRYABLE_CODES) from None
    except Exception:
        session.rollback()
        assets.cleanup_paths(request_paths)
        raise LocalOriginalError("service_unavailable", retryable=True) from None
    finally:
        try:
            assets.cleanup_asset(asset)
        except Exception:
            pass

    # Preparation is derived work: it swallows its own failures and never
    # undoes the attach above (same rule as the provider fetch).
    outcomes = maybe_auto_prepare(session, [notice_id], root=root, trigger=OPERATOR_LOCAL_ORIGINAL_TRIGGER)
    # The eligibility reads open a transaction, so the preparation ran on a
    # savepoint session of it; make its bundle/audit rows durable here (the
    # provider worker gets the same effect from its next claim's commit).
    session.commit()
    result["preparation"] = _preparation_view(outcomes[0] if outcomes else None)
    return result


__all__ = [
    "AttachmentFetchClaim",
    "LOCAL_ORIGINAL_ACTION",
    "LOCAL_ORIGINAL_PROVENANCE",
    "LocalOriginalError",
    "SOURCE_SYSTEM",
    "attach_local_original",
    "claim_next",
    "fetch_claimed",
    "read_operator_file",
    "refresh_fetch_eligibility",
    "validate_notice_id",
]
