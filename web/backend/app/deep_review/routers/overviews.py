"""사전규격 개요 검토 REST (`bidops.prespec-overview.v1`).

경로 접두사는 lifecycle의 `/api/pre-specs`이지만 제공 모듈은 deep_review다
(명세 §5.3). 세 endpoint뿐이며 모델 원문·원응답 참조·object key·filesystem
경로는 어느 응답에도 담지 않는다.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path as ApiPath
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.db import get_db
from ...core.models import AuditEvent
from ...core.object_store import ObjectStoreError, object_store
from ..models import ContentObject, ContentObjectLocation, PrespecOverviewRun, PrespecV4PdfSnapshot
from ..services.overview_range import V4OpsError, V4PreparationError
from ..services.overview_runs import (
    OverviewEnqueueError,
    active_run,
    enqueue_overview_run,
    overview_envelope,
    ready_bundle_document,
)
from ..services.pdf_snapshot import safe_snapshot

router = APIRouter(prefix="/api/pre-specs", tags=["pre-specs"])

RANGE_CONFIRMATION_ACTION = "prespec_overview.range_confirmation"

_STATUSES = {
    "invalid_request": 400,
    "actor_name_required": 400,
    "actor_name_invalid": 400,
    "not_found": 404,
    "run_active": 409,
    "document_not_current_safe": 409,
    "range_invalid": 422,
    "pdf_unavailable": 503,
    "processing_failed": 503,
}
_MESSAGES = {
    "invalid_request": "요청을 처리할 수 없습니다",
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "not_found": "대상을 찾을 수 없습니다",
    "run_active": "이미 실행 중인 개요 run이 있습니다",
    "document_not_current_safe": "현재 안전한 제안요청서 문서를 확인할 수 없습니다",
    "range_invalid": "쪽 범위가 올바르지 않습니다",
    "pdf_unavailable": "고정 스냅샷 PDF를 읽을 수 없습니다",
    "processing_failed": "개요 검토를 처리할 수 없습니다",
}


def _error(code: str) -> JSONResponse:
    safe = code if code in _STATUSES else "processing_failed"
    return JSONResponse(
        status_code=_STATUSES[safe],
        content={"error": {"code": safe, "message": _MESSAGES[safe], "details": None}, "request_id": None},
    )


class RangeConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


@router.get("/{notice_id}/overview")
def get_overview(notice_id: int = ApiPath(..., ge=1), session: Session = Depends(get_db)) -> Any:
    try:
        return overview_envelope(session, notice_id)
    except Exception:
        session.rollback()
        return _error("processing_failed")


@router.post("/{notice_id}/overview/range-confirmations", status_code=201)
def create_range_confirmation(
    payload: RangeConfirmationRequest,
    notice_id: int = ApiPath(..., ge=1),
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> Any:
    """사람이 확정한 쪽 범위로 개요 run 하나를 넣는다.

    범위 확정은 **자동 enqueue 플래그와 무관**하다. 사람이 명시적으로 고른
    범위는 언제나 한 건을 실행할 수 있어야 하기 때문이다.
    """

    try:
        actor_name = validate_actor(actor, actor_format)
    except BundleServiceError as error:
        return _error(error.code)
    if payload.page_end < payload.page_start:
        return _error("range_invalid")
    try:
        if active_run(session, notice_id) is not None:
            return _error("run_active")
        document = ready_bundle_document(session, notice_id)
        if document is None:
            return _error("not_found")
        # 준비된 스냅샷이 있으면 그 현재성을 본다. 아직 없어도 문서 자체가
        # current·safe면 허용한다 — 준비는 run이 한다.
        snapshot = (
            session.query(PrespecV4PdfSnapshot)
            .filter(PrespecV4PdfSnapshot.document_version_id == document.id)
            .order_by(PrespecV4PdfSnapshot.created_at.desc())
            .first()
        )
        if snapshot is not None:
            safe_snapshot(session, snapshot)
        elif not document.is_current or document.safety_status != "safe" or document.needs_human_review:
            return _error("document_not_current_safe")
        run = enqueue_overview_run(
            session, notice_id,
            range_source="human",
            page_start=payload.page_start,
            page_end=payload.page_end,
            actor_name=actor_name,
        )
    except OverviewEnqueueError as error:
        session.rollback()
        return _error(error.code)
    except (V4OpsError, V4PreparationError) as error:
        session.rollback()
        code = str(getattr(error, "code", "") or "")
        return _error("document_not_current_safe" if code == "document_not_current_safe" else "processing_failed")
    except Exception:
        session.rollback()
        return _error("processing_failed")
    if run is None:
        return _error("not_found")
    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=actor_name,
            action=RANGE_CONFIRMATION_ACTION,
            aggregate_type="prespec_overview_run",
            aggregate_id=str(run.id),
            safe_metadata={
                "notice_id": int(notice_id),
                "page_start": int(payload.page_start),
                "page_end": int(payload.page_end),
                "has_note": payload.note is not None,
            },
        )
    )
    session.commit()
    return {"run_id": str(run.id), "attempt_enqueued": True}


@router.get("/{notice_id}/overview/runs/{run_id}/pdf")
def get_overview_pdf(
    notice_id: int = ApiPath(..., ge=1),
    run_id: UUID = ApiPath(...),
    session: Session = Depends(get_db),
) -> Any:
    """이 run이 실제로 읽은 고정 스냅샷 PDF를 그대로 흘려 보낸다."""

    from ..services.pdf_snapshot import _read_verified_artifact

    run = session.get(PrespecOverviewRun, run_id)
    if run is None or int(run.notice_id) != int(notice_id) or run.snapshot_id is None:
        return _error("not_found")
    snapshot = session.get(PrespecV4PdfSnapshot, run.snapshot_id)
    if snapshot is None:
        return _error("not_found")
    try:
        safe_snapshot(session, snapshot)
    except V4OpsError:
        return _error("document_not_current_safe")
    content = session.get(ContentObject, snapshot.pdf_content_object_id)
    location = session.get(ContentObjectLocation, snapshot.pdf_location_id)
    if content is None or location is None:
        return _error("pdf_unavailable")
    try:
        store = object_store(namespaces=("source",), read_namespaces=("source",))
        data = _read_verified_artifact(
            store, location, content, max_bytes=content.size_bytes, expected_mime="application/pdf",
        )
    except (V4PreparationError, ObjectStoreError, OSError, ValueError):
        return _error("pdf_unavailable")
    return Response(content=data, media_type="application/pdf")


__all__ = ["RANGE_CONFIRMATION_ACTION", "RangeConfirmationRequest", "router"]
