"""Approved deep-review report/evidence endpoints #11-14 (T7 registers router)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas.reports import EvidenceView, FinalOpinionRequest, FinalOpinionView, ReportRevisionRequest, ReportView
from ..services.evidence import EvidenceService, EvidenceServiceError
from ..services.reports import ReportService, ReportServiceError


router = APIRouter(prefix="/api", tags=["deep-review-reports"])
service = ReportService()
evidence_service = EvidenceService()

_MESSAGES = {
    "invalid_request": "요청을 처리할 수 없습니다",
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "not_found": "대상을 찾을 수 없습니다",
    "review_not_ready": "심층 검토가 아직 준비되지 않았습니다",
    "version_conflict": "대상이 변경되어 다시 시도해야 합니다",
    "idempotency_conflict": "같은 request_id가 다른 요청에 사용되었습니다",
    "evidence_out_of_scope": "심층 검토 범위 밖의 근거입니다",
    "factual_change_evidence_required": "사실 변경에는 범위 내 근거가 필요합니다",
    "validation_failed": "검증에 실패했습니다",
    "final_opinion_reason_required": "최종 의견 사유가 필요합니다",
    "unsafe_document": "안전 검사를 통과하지 못한 문서입니다",
    "processing_failed": "보고서 작업을 완료할 수 없습니다",
}
_ALLOWED = frozenset(_MESSAGES)
_STATUS = {
    "not_found": 404, "review_not_ready": 409, "version_conflict": 409,
    "idempotency_conflict": 409, "evidence_out_of_scope": 403,
    "factual_change_evidence_required": 400, "validation_failed": 409,
    "unsafe_document": 403, "final_opinion_reason_required": 400,
}


def _error_response(error: ReportServiceError | EvidenceServiceError, *, request_id: UUID | None = None) -> JSONResponse:
    code = error.code if error.code in _ALLOWED else "processing_failed"
    return JSONResponse(
        status_code=getattr(error, "status_code", None) or _STATUS.get(code, 400),
        content={
            "error": {"code": code, "message": _MESSAGES[code], "details": None},
            "request_id": str(request_id or getattr(error, "request_id", None)) if (request_id or getattr(error, "request_id", None)) else None,
        },
    )


@router.get("/deep-reviews/{deep_review_id}/report", response_model=ReportView)
def get_report(deep_review_id: UUID, session: Session = Depends(get_db)) -> ReportView | JSONResponse:
    try:
        return service.get_report(session, deep_review_id)
    except ReportServiceError as error:
        return _error_response(error)
    except Exception:
        session.rollback()
        return _error_response(ReportServiceError("processing_failed", "report failed", status_code=500))


@router.post("/deep-reviews/{deep_review_id}/report-revisions", response_model=ReportView, status_code=201)
def create_report_revision(
    deep_review_id: UUID,
    payload: ReportRevisionRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    session: Session = Depends(get_db),
) -> ReportView | JSONResponse:
    try:
        return service.create_revision(session, deep_review_id, actor, payload)
    except ReportServiceError as error:
        return _error_response(error, request_id=payload.request_id)
    except Exception:
        session.rollback()
        return _error_response(ReportServiceError("processing_failed", "revision failed", status_code=500), request_id=payload.request_id)


@router.post("/deep-reviews/{deep_review_id}/final-opinions", response_model=FinalOpinionView, status_code=201)
def create_final_opinion(
    deep_review_id: UUID,
    payload: FinalOpinionRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    session: Session = Depends(get_db),
) -> FinalOpinionView | JSONResponse:
    try:
        return service.create_final_opinion(session, deep_review_id, actor, payload)
    except ReportServiceError as error:
        return _error_response(error, request_id=payload.request_id)
    except Exception:
        session.rollback()
        return _error_response(ReportServiceError("processing_failed", "opinion failed", status_code=500), request_id=payload.request_id)


@router.get("/evidence/{evidence_id}", response_model=EvidenceView)
def get_evidence(evidence_id: UUID, session: Session = Depends(get_db)) -> EvidenceView | JSONResponse:
    try:
        return evidence_service.get(session, evidence_id)
    except EvidenceServiceError as error:
        return _error_response(error)
    except Exception:
        session.rollback()
        return _error_response(EvidenceServiceError("processing_failed", "evidence failed", status_code=500))


__all__ = ["evidence_service", "router", "service"]
