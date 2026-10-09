"""Strict public response contracts for company identity lookup."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, StrictStr

from ...core.schema_base import AwareDateTime, RuntimeContractModel


class CompanyDTO(RuntimeContractModel):
    company_id: UUID
    slug: StrictStr
    name: StrictStr
    is_fictional: StrictBool
    created_at: AwareDateTime


class CompanyListResponse(RuntimeContractModel):
    items: list[CompanyDTO]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


CompanyTrackingStatus = Literal["미선택", "계속 추적", "보류", "종료"]


class CompanyTrackingDTO(RuntimeContractModel):
    company_id: UUID
    opportunity_id: StrictInt = Field(ge=1)
    tracking_status: CompanyTrackingStatus
    reason: StrictStr | None
    selected_by: StrictStr | None
    selected_at: AwareDateTime | None
    revision: StrictInt = Field(ge=0)


class CompanyTrackingUpdateRequest(RuntimeContractModel):
    tracking_status: CompanyTrackingStatus
    reason: StrictStr
    expected_revision: StrictInt = Field(ge=0)
    request_id: UUID


__all__ = [
    "CompanyDTO",
    "CompanyListResponse",
    "CompanyTrackingDTO",
    "CompanyTrackingStatus",
    "CompanyTrackingUpdateRequest",
]
