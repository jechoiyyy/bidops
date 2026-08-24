"""Attachment acquisition workflow endpoints."""

from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..constants import GRADE_ORDER, GRADE_RANK
from ..db import get_db
from ..models import AgencyPortal, Attachment, Notice
from ..schemas import (
    AttachmentProcedureResponse,
    AttachmentQueueItem,
    AttachmentQueueResponse,
    AttachmentResponse,
    AgencyPortalResponse,
)
from ..services.attachments import (
    AttachmentPathError,
    AttachmentValidationError,
    attachment_download_path,
    attachment_download_url,
    build_search_url,
    match_portal,
    remove_stored_file,
    store_upload,
)
from .common import get_run, notice_list_item


router = APIRouter(prefix="/api", tags=["attachments"])

PROCEDURE_STEPS = [
    "발주기관의 자체 조달시스템을 확인합니다.",
    "해당 시스템에서 공고번호 또는 공고명으로 입찰공고를 검색합니다.",
    "상세 공고의 첨부파일을 내려받아 애플리케이션에 등록합니다.",
]


def _portal_response(portal: AgencyPortal | None) -> AgencyPortalResponse | None:
    if portal is None:
        return None
    return AgencyPortalResponse(
        id=portal.id,
        agency_pattern=portal.agency_pattern,
        system_name=portal.system_name,
        search_url_template=portal.search_url_template,
        enabled=portal.enabled,
        note=portal.note,
    )


def _attachment_response(attachment: Attachment) -> AttachmentResponse:
    return AttachmentResponse(
        id=attachment.id,
        name=attachment.name,
        url=attachment_download_url(attachment),
        origin=attachment.origin,
        file_ext=attachment.file_ext,
        size_bytes=attachment.size_bytes,
        stored_path=attachment.stored_path,
        extract_status=attachment.extract_status,
        created_at=attachment.created_at,
    )


def _procedure_status(attachments: list[Attachment]) -> str:
    if any(item.origin == "manual" for item in attachments):
        return "completed"
    if attachments:
        return "provided"
    return "missing"


def _portal_context(
    session: Session,
    notice: Notice,
) -> tuple[AgencyPortal | None, str | None, str]:
    portal = match_portal(session, notice.agency)
    if portal is None:
        if notice.agency and notice.agency.strip():
            return None, None, "등록된 조달시스템 없음. 기관을 등록하면 검색 주소를 생성할 수 있습니다."
        return None, None, "발주기관 미확인. 기관을 등록해도 검색 주소를 생성할 수 없습니다."
    return portal, build_search_url(portal, bid_no=notice.bid_no, title=notice.title), f"{portal.system_name} 검색 주소가 생성되었습니다."


def _procedure_response(session: Session, notice: Notice) -> AttachmentProcedureResponse:
    portal, search_url, portal_message = _portal_context(session, notice)
    return AttachmentProcedureResponse(
        notice_pk=notice.id,
        agency=notice.agency,
        bid_no=notice.bid_no,
        title=notice.title,
        status=_procedure_status(notice.attachments),
        matched_portal=_portal_response(portal),
        search_url=search_url,
        portal_message=portal_message,
        steps=PROCEDURE_STEPS,
        attachments=[_attachment_response(item) for item in notice.attachments],
    )


def _queue_item(session: Session, notice: Notice) -> AttachmentQueueItem:
    base = notice_list_item(notice)
    portal, search_url, portal_message = _portal_context(session, notice)
    return AttachmentQueueItem(
        **base.model_dump(),
        bid_no=notice.bid_no,
        matched_portal=_portal_response(portal),
        search_url=search_url,
        portal_message=portal_message,
    )


def _cleanup_uploads(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


@router.get("/notices/{notice_pk}/attachments", response_model=AttachmentProcedureResponse)
def list_notice_attachments(
    notice_pk: int,
    session: Session = Depends(get_db),
) -> AttachmentProcedureResponse:
    notice = session.scalar(
        select(Notice)
        .where(Notice.id == notice_pk)
        .options(selectinload(Notice.attachments))
    )
    if notice is None:
        raise HTTPException(status_code=404, detail=f"공고를 찾을 수 없습니다: {notice_pk}")
    return _procedure_response(session, notice)


@router.post("/notices/{notice_pk}/attachments", response_model=AttachmentProcedureResponse)
async def upload_notice_attachments(
    notice_pk: int,
    files: list[UploadFile] | None = File(default=None),
    file: UploadFile | None = File(default=None),
    session: Session = Depends(get_db),
) -> AttachmentProcedureResponse:
    notice = session.scalar(
        select(Notice)
        .where(Notice.id == notice_pk)
        .options(selectinload(Notice.attachments))
    )
    if notice is None:
        raise HTTPException(status_code=404, detail=f"공고를 찾을 수 없습니다: {notice_pk}")

    uploads = list(files or [])
    if file is not None:
        uploads.append(file)
    if not uploads:
        raise HTTPException(status_code=400, detail="등록할 파일을 선택하십시오.")

    stored_paths: list[Path] = []
    try:
        for upload in uploads:
            stored = await store_upload(upload, notice.id)
            stored_paths.append(stored.absolute_path)
            notice.attachments.append(
                Attachment(
                    name=stored.original_name,
                    url=None,
                    origin="manual",
                    file_ext=stored.extension.upper(),
                    size_bytes=stored.size_bytes,
                    stored_path=stored.stored_path,
                    extract_status="pending",
                )
            )
        session.commit()
    except AttachmentValidationError as exc:
        session.rollback()
        _cleanup_uploads(stored_paths)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        _cleanup_uploads(stored_paths)
        raise

    refreshed = session.scalar(
        select(Notice)
        .where(Notice.id == notice.id)
        .options(selectinload(Notice.attachments))
    )
    if refreshed is None:  # pragma: no cover - the notice was checked above.
        raise HTTPException(status_code=404, detail="업로드한 공고를 다시 찾을 수 없습니다.")
    return _procedure_response(session, refreshed)


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(
    attachment_id: int,
    session: Session = Depends(get_db),
) -> None:
    attachment = session.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail=f"첨부를 찾을 수 없습니다: {attachment_id}")
    if attachment.origin != "manual":
        raise HTTPException(status_code=403, detail="나라장터 제공 첨부는 삭제할 수 없습니다.")
    try:
        remove_stored_file(attachment)
    except AttachmentPathError as exc:
        raise HTTPException(status_code=500, detail="첨부 저장 경로가 올바르지 않습니다.") from exc
    session.delete(attachment)
    session.commit()


@router.get("/attachments/queue", response_model=AttachmentQueueResponse)
def attachment_queue(
    run_id: str = Query(...),
    session: Session = Depends(get_db),
) -> AttachmentQueueResponse:
    run = get_run(session, run_id)
    notices = session.scalars(
        select(Notice)
        .where(Notice.run_id == run.id, ~Notice.attachments.any())
        .options(selectinload(Notice.judgment), selectinload(Notice.attachments))
        .order_by(Notice.agency.asc().nulls_last(), Notice.deadline_at.asc().nulls_last(), Notice.id.asc())
    ).all()
    notices.sort(
        key=lambda notice: (
            notice.agency or "",
            GRADE_RANK.get(notice.judgment.grade if notice.judgment else "", len(GRADE_ORDER)),
            notice.deadline_at is None,
            notice.deadline_at,
            notice.id,
        )
    )
    return AttachmentQueueResponse(
        run_id=run.id,
        total=len(notices),
        items=[_queue_item(session, notice) for notice in notices],
    )


@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    session: Session = Depends(get_db),
) -> FileResponse:
    attachment = session.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail=f"첨부를 찾을 수 없습니다: {attachment_id}")
    try:
        path = attachment_download_path(attachment)
    except AttachmentPathError as exc:
        raise HTTPException(status_code=404, detail="첨부 파일을 찾을 수 없습니다.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="첨부 파일을 찾을 수 없습니다.")

    name = Path(attachment.name or f"attachment-{attachment.id}").name
    name = name.replace("\r", "").replace("\n", "") or f"attachment-{attachment.id}"
    media_type = "application/pdf" if attachment.file_ext == "PDF" else "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=name)
