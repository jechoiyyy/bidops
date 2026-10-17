"""회사별 분석 조회 REST (데모 계약 §6·§9·§10).

`/api/companies/{company_id}/...`의 GET 여섯 개와
`/api/pre-specs/{notice_id}/company-comparison` 하나다. 접두사는 lifecycle의
것이지만 제공 모듈은 deep_review다(명세 §5.3, `company_knowledge`·
`pre_spec_overview_router`와 같은 방식). `BIDOPS_DEMO_ENABLED=false`이면 조립
계층의 demo guard가 먼저 404를 내고 service도 같은 판정을 한 번 더 한다.

조회는 참조 실행 모드·Luna 플래그와 무관하며 쓰기·enqueue·모델 호출이 없다.
ORM은 다루지 않는다 — 판정·직렬화는 `services/company_projection`이 하고, 이
파일은 query를 옮기고 안정 오류 코드를 HTTP 상태로 바꾸는 일만 한다. 모르는
코드와 예기치 못한 예외는 내용 없이 processing_failed다. 응답에는 모델 입력
snapshot·원문·secret이 없다(그것은 전송 미리보기 POST에만 있다).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path as ApiPath, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...lifecycle.schemas.companies import CompanyTrackingStatus
from ..schemas.company_analysis import (
    CompanyComparisonView,
    CompanyFitAttemptsView,
    CompanyNoticeDetailView,
    CompanyPreSpecListView,
    CompanyReportView,
    CompanyReviewView,
)
from ..schemas.reports import EvidenceView
from ..services.company_projection import (
    READ_ERROR_MESSAGES,
    READ_ERROR_STATUS,
    CompanyReadError,
    company_comparison,
    company_evidence,
    company_fit_attempts,
    company_pre_spec_detail,
    company_pre_spec_list,
    company_report,
    company_review_detail,
)
from ..services.deep_reviews import DeepReviewService
from ..services.evidence import EvidenceService
from ..services.reports import ReportService
from ..schemas.verdict_view import PractitionerVerdictView
from ..services.verdict_view import VERDICT_ERROR_MESSAGES, VERDICT_ERROR_STATUS, VerdictViewError, verdict_view


router = APIRouter(prefix="/api/companies", tags=["company-analysis"])
comparison_router = APIRouter(prefix="/api/pre-specs", tags=["company-analysis"])
service = DeepReviewService()
report_service = ReportService()
evidence_service = EvidenceService()

#: 이 router가 내보낼 수 있는 안정 오류 코드 (계약 §9). 422는 FastAPI query 검증이다.
ALLOWED_ERROR_CODES = frozenset(READ_ERROR_STATUS)

FitDecisionFilter = Literal["matched", "mismatch", "unknown"]
CompanyPreSpecSort = Literal["posted_at_desc", "deadline_asc"]


def _error_response(code: str) -> JSONResponse:
    safe = code if code in ALLOWED_ERROR_CODES else "processing_failed"
    return JSONResponse(
        status_code=READ_ERROR_STATUS[safe],
        content={
            "error": {"code": safe, "message": READ_ERROR_MESSAGES[safe], "details": None},
            "request_id": None,
        },
    )


def _read(session: Session, call) -> JSONResponse:  # type: ignore[no-untyped-def]
    try:
        content = call()
    except CompanyReadError as error:
        session.rollback()
        return _error_response(error.code)
    except Exception:  # noqa: BLE001 - safe API boundary; nothing about the data is logged
        session.rollback()
        return _error_response("processing_failed")
    # Reads never write; end the read transaction without committing.
    session.rollback()
    return JSONResponse(status_code=200, content=content)


@router.get("/{company_id}/pre-specs", response_model=CompanyPreSpecListView)
def list_company_pre_specs(
    company_id: UUID,
    q: str | None = Query(default=None),
    fit: FitDecisionFilter | None = Query(default=None),
    tracking_status: CompanyTrackingStatus | None = Query(default=None),
    sort: CompanyPreSpecSort = Query(default="posted_at_desc"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _read(session, lambda: company_pre_spec_list(
        session, company_id=company_id, q=q, fit=fit, tracking_status=tracking_status,
        sort=sort, limit=limit, offset=offset,
    ))


@router.get("/{company_id}/pre-specs/{notice_id}", response_model=CompanyNoticeDetailView)
def get_company_pre_spec(
    company_id: UUID,
    notice_id: int = ApiPath(..., ge=1),
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _read(session, lambda: company_pre_spec_detail(session, company_id=company_id, notice_id=notice_id))


@router.get("/{company_id}/pre-specs/{notice_id}/company-fit", response_model=CompanyFitAttemptsView)
def get_company_fit_attempts(
    company_id: UUID,
    notice_id: int = ApiPath(..., ge=1),
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _read(session, lambda: company_fit_attempts(session, company_id=company_id, notice_id=notice_id))


@router.get("/{company_id}/pre-specs/{notice_id}/verdict", response_model=PractitionerVerdictView)
def get_company_pre_spec_verdict(
    company_id: UUID,
    notice_id: int = ApiPath(..., ge=1),
    attempt_id: UUID | None = Query(default=None),
    session: Session = Depends(get_db),
) -> JSONResponse:
    """RL-03 / HP-04 판정 view. 생성·모델 호출이 없는 읽기다."""

    try:
        content = verdict_view(session, company_id=company_id, notice_id=notice_id, attempt_id=attempt_id)
    except VerdictViewError as error:
        session.rollback()
        return _verdict_error(error.code)
    except Exception:  # noqa: BLE001 - safe API boundary
        session.rollback()
        return _verdict_error("processing_failed")
    session.rollback()
    return JSONResponse(status_code=200, content=content)


def _verdict_error(code: str) -> JSONResponse:
    safe = code if code in VERDICT_ERROR_STATUS else "processing_failed"
    return JSONResponse(
        status_code=VERDICT_ERROR_STATUS[safe],
        content={"error": {"code": safe, "message": VERDICT_ERROR_MESSAGES[safe], "details": None},
                 "request_id": None},
    )


@router.get("/{company_id}/deep-reviews/{review_id}", response_model=CompanyReviewView)
def get_company_deep_review(
    company_id: UUID,
    review_id: UUID,
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _read(session, lambda: company_review_detail(
        service, session, company_id=company_id, review_id=review_id,
    ))


@router.get("/{company_id}/deep-reviews/{review_id}/report", response_model=CompanyReportView)
def get_company_deep_review_report(
    company_id: UUID,
    review_id: UUID,
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _read(session, lambda: company_report(
        report_service, session, company_id=company_id, review_id=review_id,
    ))


@router.get("/{company_id}/deep-reviews/{review_id}/evidence/{evidence_id}", response_model=EvidenceView)
def get_company_deep_review_evidence(
    company_id: UUID,
    review_id: UUID,
    evidence_id: UUID,
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _read(session, lambda: company_evidence(
        evidence_service, session, company_id=company_id, review_id=review_id, evidence_id=evidence_id,
    ))


@comparison_router.get("/{notice_id}/company-comparison", response_model=CompanyComparisonView)
def get_company_comparison(
    notice_id: int = ApiPath(..., ge=1),
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _read(session, lambda: company_comparison(session, notice_id=notice_id))


__all__ = [
    "ALLOWED_ERROR_CODES",
    "comparison_router",
    "evidence_service",
    "report_service",
    "router",
    "service",
]
