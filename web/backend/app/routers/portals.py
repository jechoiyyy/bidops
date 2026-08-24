"""CRUD endpoints for agency procurement portals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AgencyPortal
from ..schemas import (
    AgencyPortalCreateRequest,
    AgencyPortalResponse,
    AgencyPortalUpdateRequest,
)


router = APIRouter(prefix="/api/portals", tags=["portals"])


def _text(value: str | None, field: str, *, required: bool = True) -> str | None:
    normalized = value.strip() if isinstance(value, str) else value
    if required and not normalized:
        raise HTTPException(status_code=422, detail=f"{field}을(를) 입력하십시오.")
    return normalized or None


def _response(portal: AgencyPortal) -> AgencyPortalResponse:
    return AgencyPortalResponse(
        id=portal.id,
        agency_pattern=portal.agency_pattern,
        system_name=portal.system_name,
        search_url_template=portal.search_url_template,
        enabled=portal.enabled,
        note=portal.note,
    )


@router.get("", response_model=list[AgencyPortalResponse])
def list_portals(session: Session = Depends(get_db)) -> list[AgencyPortalResponse]:
    rows = session.scalars(
        select(AgencyPortal).order_by(AgencyPortal.enabled.desc(), AgencyPortal.id.asc())
    ).all()
    return [_response(row) for row in rows]


@router.post("", response_model=AgencyPortalResponse, status_code=201)
def create_portal(
    payload: AgencyPortalCreateRequest,
    session: Session = Depends(get_db),
) -> AgencyPortalResponse:
    portal = AgencyPortal(
        agency_pattern=_text(payload.agency_pattern, "기관 매칭 문자열") or "",
        system_name=_text(payload.system_name, "조달시스템 이름") or "",
        search_url_template=_text(payload.search_url_template, "검색 주소 템플릿") or "",
        enabled=payload.enabled,
        note=_text(payload.note, "비고", required=False),
    )
    session.add(portal)
    session.commit()
    session.refresh(portal)
    return _response(portal)


@router.patch("/{portal_id}", response_model=AgencyPortalResponse)
def update_portal(
    portal_id: int,
    payload: AgencyPortalUpdateRequest,
    session: Session = Depends(get_db),
) -> AgencyPortalResponse:
    portal = session.get(AgencyPortal, portal_id)
    if portal is None:
        raise HTTPException(status_code=404, detail=f"기관 조달시스템을 찾을 수 없습니다: {portal_id}")

    if "agency_pattern" in payload.model_fields_set:
        portal.agency_pattern = _text(payload.agency_pattern, "기관 매칭 문자열") or ""
    if "system_name" in payload.model_fields_set:
        portal.system_name = _text(payload.system_name, "조달시스템 이름") or ""
    if "search_url_template" in payload.model_fields_set:
        portal.search_url_template = _text(payload.search_url_template, "검색 주소 템플릿") or ""
    if "enabled" in payload.model_fields_set and payload.enabled is not None:
        portal.enabled = payload.enabled
    if "note" in payload.model_fields_set:
        portal.note = _text(payload.note, "비고", required=False)

    session.commit()
    session.refresh(portal)
    return _response(portal)

