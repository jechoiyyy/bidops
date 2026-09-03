"""Attachment storage, validation, and agency portal matching helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ..document_mcp.processor import ClamAVChecker
from ...lifecycle.models import AgencyPortal, Attachment
from . import assets
from ...core.clamav import ClamAVScanner

ALLOWED_EXTENSIONS = frozenset({"hwp", "hwpx", "pdf"})
MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024


class AttachmentValidationError(ValueError):
    """Raised when an uploaded file does not meet the attachment policy."""


class AttachmentPathError(ValueError):
    """Raised when a stored attachment path escapes the attachment root."""


@dataclass(frozen=True)
class StoredUpload:
    """Metadata returned after a validated upload has been written."""

    original_name: str
    extension: str
    size_bytes: int
    stored_path: str
    absolute_path: Path
    source_path: Path
    asset: assets.QuarantinedAsset


def extension_for_name(filename: str | None) -> str:
    """Return a normalized suffix without using the filename as a path."""

    if not filename:
        return ""
    return Path(filename).suffix.lower().removeprefix(".")


def validate_extension(filename: str | None) -> str:
    extension = extension_for_name(filename)
    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(item.upper() for item in ALLOWED_EXTENSIONS))
        raise AttachmentValidationError(
            f"허용되지 않는 확장자입니다. {allowed} 파일만 등록할 수 있습니다."
        )
    return extension


def validate_size(size_bytes: int) -> None:
    if size_bytes > MAX_ATTACHMENT_SIZE:
        raise AttachmentValidationError(
            "파일 크기가 50MB를 초과합니다. 50MB 이하 파일만 등록할 수 있습니다."
        )


def attachment_root() -> Path:
    """Return the configured attachment root, creating it when needed."""

    root = get_settings().attachments_dir
    if root is None:  # pragma: no cover - Settings derives this by default.
        raise RuntimeError("첨부 보관 경로가 설정되지 않았습니다.")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def notice_attachment_directory(notice_pk: int) -> Path:
    """Build a notice directory from the server-side integer primary key."""

    if notice_pk <= 0:
        raise AttachmentPathError("공고 식별자가 올바르지 않습니다.")
    directory = attachment_root() / str(notice_pk)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def safe_stored_path(stored_path: str | None) -> Path:
    """Resolve a stored path and reject traversal or symlink escapes."""

    if not stored_path or not stored_path.strip():
        raise AttachmentPathError("첨부 저장 경로가 없습니다.")
    root = attachment_root()
    candidate = Path(stored_path)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AttachmentPathError("첨부 저장 경로가 보관 디렉토리 밖을 가리킵니다.") from exc
    return resolved


async def store_upload(
    upload: UploadFile,
    notice_pk: int,
    *,
    clamav_checker: ClamAVChecker | None = None,
) -> StoredUpload:
    """Inspect an upload before writing the legacy download copy.

    The original filename is only returned as metadata. It never participates
    in directory or stored filename construction.  The bytes first enter the
    shared quarantine/object-store boundary; the legacy local copy is written
    only after MIME, structure, and ClamAV inspection reports ``safe``.
    """

    original_name = upload.filename or ""
    extension = validate_extension(original_name)
    if upload.size is not None:
        validate_size(upload.size)

    size_bytes = 0
    content_parts: list[bytes] = []
    asset: assets.QuarantinedAsset | None = None
    source_path: Path | None = None
    temporary_path: Path | None = None
    final_path: Path | None = None

    try:
        while True:
            chunk = await upload.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            size_bytes += len(chunk)
            validate_size(size_bytes)
            content_parts.append(chunk)
        if size_bytes == 0:
            raise AttachmentValidationError("빈 파일은 등록할 수 없습니다.")

        root = attachment_root()
        content = b"".join(content_parts)
        asset = assets.quarantine_bytes(
            content,
            original_name,
            declared_media_type=upload.content_type,
            root=root,
            source_kind="manual",
        )

        checker = clamav_checker
        if checker is None:
            settings = get_settings()
            checker = ClamAVScanner(
                host=settings.clamav_host,
                port=settings.clamav_port,
                timeout=settings.clamav_timeout_seconds,
            ).scan
        inspected = assets.inspect_quarantine(asset, clamav_checker=checker)
        if inspected.safety_status != "safe":
            # ``quarantined`` includes scanner unavailable; neither an
            # unscanned nor a blocked file may become a legacy attachment.
            raise AttachmentValidationError("첨부파일이 안전성 검사를 통과하지 못했습니다.")

        source_path, _source_sha256, source_size = assets.commit_source(asset, root=root)
        if source_size != size_bytes:
            raise AttachmentValidationError("첨부파일 크기 검증에 실패했습니다.")

        directory = notice_attachment_directory(notice_pk)
        temporary_path = directory / f".{uuid4().hex}.upload"
        final_name = f"{uuid4().hex}.{extension}"
        final_path = directory / final_name
        with temporary_path.open("wb") as target:
            target.write(content)
        temporary_path.replace(final_path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        if final_path is not None:
            final_path.unlink(missing_ok=True)
        if source_path is not None:
            source_path.unlink(missing_ok=True)
        assets.cleanup_asset(asset)
        raise
    finally:
        await upload.close()

    assert asset is not None
    assert source_path is not None
    assert final_path is not None
    relative_path = Path(str(notice_pk)) / final_name
    return StoredUpload(
        original_name=original_name,
        extension=extension,
        size_bytes=source_size,
        stored_path=relative_path.as_posix(),
        absolute_path=final_path,
        source_path=source_path,
        asset=asset,
    )


def match_portal(session: Session, agency: str | None) -> AgencyPortal | None:
    """Return the most specific enabled partial match for an agency string."""

    if not agency or not agency.strip():
        return None
    agency_value = agency.casefold()
    portals = session.scalars(
        select(AgencyPortal)
        .where(AgencyPortal.enabled.is_(True))
        .order_by(AgencyPortal.id.asc())
    ).all()
    matches = [
        portal
        for portal in portals
        if portal.agency_pattern.strip()
        and portal.agency_pattern.strip().casefold() in agency_value
    ]
    return max(matches, key=lambda portal: (len(portal.agency_pattern), -portal.id), default=None)


def build_search_url(
    portal: AgencyPortal,
    *,
    bid_no: str | None,
    title: str | None,
) -> str:
    """Substitute URL-encoded notice values into a portal template."""

    values = {
        "{bid_no}": quote((bid_no or "").strip(), safe=""),
        "{title}": quote((title or "").strip(), safe=""),
    }
    result = portal.search_url_template
    for placeholder, encoded_value in values.items():
        result = result.replace(placeholder, encoded_value)
    return result


# MVP 대상 3개 기관의 시드 데이터. 검색 주소는 담당자가 실제 주소로 교체하는
# 것을 전제로 한 자리표시자이며, 확인 전에는 화면에서 미확인 상태로 안내한다.
PORTAL_SEED_NOTE = "검색 주소는 자리표시자입니다. 실제 조달시스템 주소를 확인하여 수정한 뒤 사용하십시오."


def seed_default_portals(session: Session) -> None:
    """Insert MVP portal data only when the table is completely empty."""

    if session.scalar(select(AgencyPortal.id).limit(1)) is not None:
        return
    session.add_all(
        [
            AgencyPortal(
                agency_pattern="한국수자원공사",
                system_name="한국수자원공사 전자조달시스템",
                search_url_template="https://ebid.kwater.or.kr/search?bidNo={bid_no}&title={title}",
                note=PORTAL_SEED_NOTE,
            ),
            AgencyPortal(
                agency_pattern="한국도로공사",
                system_name="한국도로공사 전자조달시스템",
                search_url_template="https://ebid.ex.co.kr/search?bidNo={bid_no}&title={title}",
                note=PORTAL_SEED_NOTE,
            ),
            AgencyPortal(
                agency_pattern="한국토지주택공사",
                system_name="한국토지주택공사 전자조달",
                search_url_template="https://ebid.lh.or.kr/search?bidNo={bid_no}&title={title}",
                note=PORTAL_SEED_NOTE,
            ),
        ]
    )
    session.commit()


def attachment_download_path(attachment: Attachment) -> Path:
    """Resolve an attachment's path, keeping the security check at the edge."""

    return safe_stored_path(attachment.stored_path)


def attachment_download_url(attachment: Attachment) -> str | None:
    """Return an internal download URL when a stored file exists."""

    if attachment.stored_path:
        return f"/api/attachments/{attachment.id}/download"
    return attachment.url


def remove_stored_file(attachment: Attachment) -> None:
    """Delete a stored file only after resolving it inside the root."""

    if not attachment.stored_path:
        return
    path = attachment_download_path(attachment)
    path.unlink(missing_ok=True)
