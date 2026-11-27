"""Independent human commands for prespec engine review."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.db import get_db
from ..schemas import engine_review as wire
from ..services import engine_review as service
from ..services.engine_runs import EngineRunError

router = APIRouter(prefix="/api/pre-specs", tags=["engine-review"])
review_path = "/{notice_id}/engine-review"
Database = Annotated[Session, Depends(get_db)]


def _actor(
    name: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    name_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
):
    return name, name_format


Actor = Annotated[tuple[str | None, str | None], Depends(_actor)]


def _call(session, operation, *, detail_notice_id=None):
    try:
        return operation()
    except (EngineRunError, BundleServiceError) as error:
        session.rollback()
        details = {"reason": error.code}
        if error.code == "input_changed" and detail_notice_id is not None:
            try:
                details["current"] = service.review_state(session, detail_notice_id).model_dump(mode="json")
            except EngineRunError:
                pass
        return JSONResponse(
            status_code=getattr(error, "status", getattr(error, "status_code", 409)),
            content={"error": {
                "code": error.code,
                "message": "분석 검토 조건을 확인해 주세요",
                "details": details,
            }},
        )
    except Exception as error:
        session.rollback()
        # Only safe exception class metadata reaches the log.
        logging.getLogger(__name__).warning("engine review command failed: %s", type(error).__name__)
        return JSONResponse(status_code=503, content={"error": {
            "code": "engine_unavailable", "message": "분석 검토를 처리할 수 없습니다", "details": None,
        }})


@router.get(review_path, response_model=wire.ReviewState)
def get_review(notice_id: int, session: Database):
    return _call(session, lambda: service.review_state(session, notice_id))


@router.post(review_path + "/requests", response_model=wire.RequestResponse, responses={201: {"model": wire.RequestResponse}})
def request_review(notice_id: int, payload: wire.RequestCommand, response: Response, session: Database, actor: Actor):
    def run():
        receipt, created, state = service.request_review(session, notice_id, payload, validate_actor(*actor))
        response.status_code = 201 if created else 200
        return wire.RequestResponse(request=receipt, state=state)
    return _call(session, run)


@router.post("/engine-review/requests:batch", response_model=wire.BatchResponse)
def batch(payload: wire.BatchCommand, session: Database, actor: Actor):
    return _call(session, lambda: service.request_review_batch(session, payload, validate_actor(*actor)))


@router.post(review_path + "/previews", response_model=wire.PreviewReceipt)
def preview(notice_id: int, payload: wire.Command, session: Database, actor: Actor):
    return _call(session, lambda: service.create_preview(session, notice_id, payload, validate_actor(*actor)))


@router.post(review_path + "/approvals", response_model=wire.ApprovalReceipt, status_code=202)
def approve(notice_id: int, payload: wire.ApprovalCommand, session: Database, actor: Actor):
    return _call(session, lambda: service.approve(session, notice_id, payload, validate_actor(*actor)))


@router.post(review_path + "/dismissals", response_model=wire.DismissalReceipt)
def dismiss(notice_id: int, payload: wire.DismissalCommand, session: Database, actor: Actor):
    return _call(
        session, lambda: service.dismiss(session, notice_id, payload, validate_actor(*actor)),
        detail_notice_id=notice_id,
    )


@router.post(review_path + "/acknowledgments", response_model=wire.AcknowledgmentReceipt)
def acknowledge(notice_id: int, payload: wire.AcknowledgmentCommand, session: Database, actor: Actor):
    return _call(
        session, lambda: service.acknowledge(session, notice_id, payload, validate_actor(*actor)),
        detail_notice_id=notice_id,
    )
