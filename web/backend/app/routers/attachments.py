"""Attachment acquisition workflow endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..core.constants import GRADE_ORDER, GRADE_RANK
from ..core.db import get_db
from ..lifecycle import delete_manual_attachment, extension_registry, register_manual_attachment
from ..models import AgencyPortal, Attachment, AuditEvent, Notice, NoticeObservation
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
    StoredUpload,
    store_upload,
)
from ..services import assets
from ..services.document_bundles import BundleServiceError, stable_api_error, validate_actor
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


def _queue_item(
    session: Session,
    notice: Notice,
    run_id: str | None = None,
    judgment_fields: Mapping[str, Any] | None = None,
) -> AttachmentQueueItem:
    base = notice_list_item(notice, run_id, judgment_fields)
    portal, search_url, portal_message = _portal_context(session, notice)
    return AttachmentQueueItem(
        **base.model_dump(),
        bid_no=notice.bid_no,
        matched_portal=_portal_response(portal),
        search_url=search_url,
        portal_message=portal_message,
    )


def _cleanup_uploads(uploads: list[StoredUpload]) -> None:
    for upload in uploads:
        upload.absolute_path.unlink(missing_ok=True)
        upload.source_path.unlink(missing_ok=True)
        assets.cleanup_asset(upload.asset)


def _actor_error_response(error: BundleServiceError) -> JSONResponse:
    code, message = stable_api_error(error.code)
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {"code": code, "message": message, "details": None},
            "request_id": None,
        },
    )


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
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> AttachmentProcedureResponse | JSONResponse:
    try:
        actor_name = validate_actor(actor, actor_format)
    except BundleServiceError as error:
        return _actor_error_response(error)

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

    stored_uploads: list[StoredUpload] = []
    created_attachments: list[Attachment] = []
    try:
        for upload in uploads:
            stored = await store_upload(upload, notice.id)
            stored_uploads.append(stored)
            # 첨부 메타는 lifecycle 테이블이다. 쓰기는 lifecycle 공개 함수로만 한다.
            attachment = register_manual_attachment(
                session,
                notice,
                name=stored.original_name,
                file_ext=stored.extension.upper(),
                size_bytes=stored.size_bytes,
                stored_path=stored.stored_path,
            )
            created_attachments.append(attachment)
        session.flush()
        for attachment in created_attachments:
            session.add(
                AuditEvent(
                    actor_kind="human",
                    claimed_name=actor_name,
                    action="attachment.upload",
                    aggregate_type="attachment",
                    aggregate_id=str(attachment.id),
                    safe_metadata={
                        "notice_id": int(notice.id),
                        "origin": "manual",
                        "file_ext": attachment.file_ext,
                        "size_bytes": int(attachment.size_bytes or 0),
                        "safety_status": "safe",
                    },
                )
            )
        session.commit()
    except AttachmentValidationError as exc:
        session.rollback()
        _cleanup_uploads(stored_uploads)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except assets.AssetError as exc:
        session.rollback()
        _cleanup_uploads(stored_uploads)
        code, message = stable_api_error(exc.code)
        status_code = 503 if code == "service_unavailable" else 500 if code == "processing_failed" else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    except Exception:
        session.rollback()
        _cleanup_uploads(stored_uploads)
        raise

    refreshed = session.scalar(
        select(Notice)
        .where(Notice.id == notice.id)
        .options(selectinload(Notice.attachments))
    )
    if refreshed is None:  # pragma: no cover - the notice was checked above.
        raise HTTPException(status_code=404, detail="업로드한 공고를 다시 찾을 수 없습니다.")
    return _procedure_response(session, refreshed)


@router.delete("/attachments/{attachment_id}", response_model=None, status_code=204)
def delete_attachment(
    attachment_id: int,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> None | JSONResponse:
    try:
        actor_name = validate_actor(actor, actor_format)
    except BundleServiceError as error:
        return _actor_error_response(error)

    attachment = session.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail=f"첨부를 찾을 수 없습니다: {attachment_id}")
    if attachment.origin != "manual":
        raise HTTPException(status_code=403, detail="나라장터 제공 첨부는 삭제할 수 없습니다.")
    try:
        remove_stored_file(attachment)
    except AttachmentPathError as exc:
        raise HTTPException(status_code=500, detail="첨부 저장 경로가 올바르지 않습니다.") from exc
    delete_manual_attachment(session, attachment)
    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=actor_name,
            action="attachment.delete",
            aggregate_type="attachment",
            aggregate_id=str(attachment.id),
            safe_metadata={
                "notice_id": int(attachment.notice_pk),
                "origin": attachment.origin,
                "status": "deleted",
            },
        )
    )
    session.commit()


@router.get("/attachments/queue", response_model=AttachmentQueueResponse)
def attachment_queue(
    run_id: str = Query(...),
    session: Session = Depends(get_db),
) -> AttachmentQueueResponse:
    run = get_run(session, run_id)
    notices = session.scalars(
        select(Notice)
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .where(NoticeObservation.run_id == run.id, ~Notice.attachments.any())
        .options(selectinload(Notice.attachments))
        .order_by(Notice.agency.asc().nulls_last(), Notice.deadline_at.asc().nulls_last(), Notice.id.asc())
    ).all()
    # 등급은 판정 projection의 몫이다(§6.1). 목록 전체를 한 번에 읽어 정렬과 응답이
    # 같은 값을 쓰게 하고, 공고당 조회를 만들지 않는다. 제공자가 없으면 빈 map이라
    # 모든 공고가 같은 순위를 받아 나머지 정렬 키로만 갈린다.
    projection = extension_registry().judgment_projection
    judgment_fields = projection.notice_fields(session, [notice.id for notice in notices])
    notices.sort(
        key=lambda notice: (
            notice.agency or "",
            GRADE_RANK.get(
                judgment_fields.get(notice.id, {}).get("grade") or "", len(GRADE_ORDER)
            ),
            notice.deadline_at is None,
            notice.deadline_at,
            notice.id,
        )
    )
    return AttachmentQueueResponse(
        run_id=run.id,
        total=len(notices),
        items=[
            _queue_item(session, notice, run.id, judgment_fields.get(notice.id, {}))
            for notice in notices
        ],
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
    return FileResponse(
        path,
        media_type=media_type,
        filename=name,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        },
    )
