"""Safe cumulative pre-specification list contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from . import AwareDateTime, RuntimeContractModel
from .opportunities import OpportunityTrackingStatus


PreSpecOrigin = Literal["추적", "신규"]
PreSpecSort = Literal["published", "deadline"]


class PreSpecDocumentSummary(RuntimeContractModel):
    """Counts only; object-store and local storage metadata stay server-side."""

    model_config = ConfigDict(extra="forbid", from_attributes=True, populate_by_name=True)

    attachments: int = Field(ge=0)
    completed: int = Field(default=0, ge=0, alias="완료")
    pending: int = Field(default=0, ge=0, alias="대기")
    running: int = Field(default=0, ge=0, alias="진행")
    blocked: int = Field(default=0, ge=0, alias="차단")
    failed: int = Field(default=0, ge=0, alias="실패")


class PreSpecListItem(RuntimeContractModel):
    notice_pk: int = Field(ge=1)
    pre_spec_no: str | None = None
    title: str | None = None
    agency: str | None = None
    published_at: AwareDateTime | None = None
    deadline_at: AwareDateTime | None = None
    budget: float | None = None
    sw_business_status: str | None = None
    business_division: str | None = None
    origin: PreSpecOrigin | None = None
    opportunity_id: int | None = Field(default=None, ge=1)
    tracking_status: OpportunityTrackingStatus | None = None
    kept_by_tracking: bool
    document: PreSpecDocumentSummary


class PreSpecListResponse(RuntimeContractModel):
    items: list[PreSpecListItem] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


__all__ = [
    "PreSpecDocumentSummary",
    "PreSpecListItem",
    "PreSpecListResponse",
    "PreSpecOrigin",
    "PreSpecSort",
]
