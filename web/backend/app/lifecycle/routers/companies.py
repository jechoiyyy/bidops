"""Company identity and company-scoped tracking API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.db import get_db
from ..models import Company
from ..schemas.companies import (
    CompanyDTO,
    CompanyListResponse,
    CompanyTrackingDTO,
    CompanyTrackingUpdateRequest,
)
from ..services.company_context import get_company, list_companies
from ..services import opportunity_tracking


router = APIRouter(prefix="/api/companies", tags=["companies"])

_TRACKING_ERRORS: dict[str, tuple[int, str]] = {
    "invalid_request": (422, "요청이 올바르지 않습니다"),
    "actor_name_required": (400, "담당자 이름이 필요합니다"),
    "actor_name_invalid": (400, "담당자 이름이 올바르지 않습니다"),
    "not_found": (404, "회사 또는 사업기회를 찾을 수 없습니다"),
    "tracking_status_invalid": (422, "지원하지 않는 추적 상태입니다"),
    "tracking_reason_required": (422, "추적 상태를 선택한 이유가 필요합니다"),
    "version_conflict": (409, "회사별 추적 상태가 변경되었습니다"),
    "idempotency_conflict": (409, "같은 request_id가 다른 요청에 사용되었습니다"),
    "processing_failed": (500, "회사별 추적 상태를 처리할 수 없습니다"),
}


def _dto(company: Company) -> CompanyDTO:
    return CompanyDTO(
        company_id=company.id,
        slug=company.slug,
        name=company.name,
        is_fictional=company.is_fictional,
        created_at=company.created_at,
    )


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "code": "not_found",
                "message": "회사를 찾을 수 없습니다",
                "details": None,
            },
            "request_id": None,
        },
    )


def _tracking_error_response(
    error: opportunity_tracking.OpportunityTrackingError | BundleServiceError,
    *,
    request_id: UUID | None = None,
) -> JSONResponse:
    registered = error.code in _TRACKING_ERRORS
    status_code, message = _TRACKING_ERRORS.get(
        error.code, _TRACKING_ERRORS["processing_failed"]
    )
    if isinstance(error, BundleServiceError):
        status_code = error.status_code
    details = getattr(error, "details", None) if registered else None
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": error.code if registered else "processing_failed",
                "message": message,
                "details": details if isinstance(details, dict) else None,
            },
            "request_id": str(request_id) if request_id is not None else None,
        },
    )


def _tracking_unexpected(*, request_id: UUID | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "processing_failed",
                "message": _TRACKING_ERRORS["processing_failed"][1],
                "details": None,
            },
            "request_id": str(request_id) if request_id is not None else None,
        },
    )


@router.get("", response_model=CompanyListResponse)
def companies(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> CompanyListResponse:
    rows, total = list_companies(session, limit=limit, offset=offset)
    return CompanyListResponse(
        items=[_dto(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{company_id}", response_model=CompanyDTO)
def company_detail(
    company_id: UUID,
    session: Session = Depends(get_db),
) -> CompanyDTO | JSONResponse:
    company = get_company(session, company_id)
    return _dto(company) if company is not None else _not_found()


@router.get(
    "/{company_id}/opportunities/{opportunity_id}/tracking",
    response_model=CompanyTrackingDTO,
)
def company_opportunity_tracking(
    company_id: UUID,
    opportunity_id: int,
    session: Session = Depends(get_db),
) -> CompanyTrackingDTO | JSONResponse:
    try:
        return opportunity_tracking.get_company_tracking(
            session,
            company_id=company_id,
            opportunity_id=opportunity_id,
        )
    except opportunity_tracking.OpportunityTrackingError as error:
        session.rollback()
        return _tracking_error_response(error)
    except Exception:  # pragma: no cover - defensive API boundary
        session.rollback()
        return _tracking_unexpected()


@router.patch(
    "/{company_id}/opportunities/{opportunity_id}/tracking",
    response_model=CompanyTrackingDTO,
)
def update_company_opportunity_tracking(
    company_id: UUID,
    opportunity_id: int,
    payload: CompanyTrackingUpdateRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[
        str | None, Header(alias="X-BidOps-Actor-Name-Format")
    ] = None,
    session: Session = Depends(get_db),
) -> JSONResponse:
    try:
        actor_name = validate_actor(actor, actor_format)
        result = opportunity_tracking.set_company_tracking(
            session,
            company_id=company_id,
            opportunity_id=opportunity_id,
            status=payload.tracking_status,
            reason=payload.reason,
            expected_revision=payload.expected_revision,
            request_id=payload.request_id,
            selected_by=actor_name,
        )
        session.commit()
        return JSONResponse(
            status_code=result.response_status,
            content=result.snapshot,
        )
    except (
        opportunity_tracking.OpportunityTrackingError,
        BundleServiceError,
    ) as error:
        session.rollback()
        return _tracking_error_response(error, request_id=payload.request_id)
    except Exception:  # pragma: no cover - defensive API boundary
        session.rollback()
        return _tracking_unexpected(request_id=payload.request_id)


__all__ = ["router"]
