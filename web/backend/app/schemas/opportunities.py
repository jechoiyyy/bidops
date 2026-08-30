"""REST contracts for cumulative business-opportunity tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, Field

from . import AwareDateTime, RuntimeContractModel


OpportunityTrackingStatus = Literal["미선택", "계속 추적", "보류", "종료"]
OpportunityFirstRegisteredStage = Literal["order_plan", "pre_spec", "bid_notice"]
OpportunityLinkStage = Literal["order_plan", "notice"]
OpportunityLinkType = Literal["official", "candidate"]
OpportunityLinkStatus = Literal["확정", "후보 확인 대기", "사람 확인 완료", "검색 미확인"]
OpportunitySearchStrategy = Literal[
    "full",
    "breaking_split",
    "normalized",
    "longest_fragment",
    "prefix12",
]


class OpportunityLinkView(RuntimeContractModel):
    """Safe projection of one lifecycle link and, when present, its target."""

    id: int = Field(ge=1)
    stage: OpportunityLinkStage
    link_type: OpportunityLinkType
    status: OpportunityLinkStatus
    search_strategy: OpportunitySearchStrategy | None = None
    attempted_strategies: list[OpportunitySearchStrategy] = Field(default_factory=list)
    agency_match: bool | None = None
    last_searched_at: AwareDateTime | None = None
    evidence_external_no: str | None = None
    evidence_bid_no: str | None = None
    human_decision: Literal["accepted", "rejected"] | None = None
    reviewer_name: str | None = None
    reviewed_at: AwareDateTime | None = None
    review_reason: str | None = None

    # The following fields are a deliberately small, safe record projection.
    # They contain identifiers/titles only; raw_source, URLs, filesystem
    # references, and object-store metadata are not part of this contract.
    record_type: str | None = None
    record_id: int | None = Field(default=None, ge=1)
    notice_id: int | None = Field(default=None, ge=1)
    order_plan_id: int | None = Field(default=None, ge=1)
    source_type: str | None = None
    title: str | None = None
    agency: str | None = None
    external_id: str | None = None
    record_external_id: str | None = None


class OpportunityStateView(RuntimeContractModel):
    id: int = Field(ge=1)
    tracking_status: OpportunityTrackingStatus
    tracking_reason: str | None = None
    tracking_selected_by: str | None = None
    tracking_selected_at: AwareDateTime | None = None
    recheck_signal: bool
    recheck_signal_at: AwareDateTime | None = None
    recheck_signal_link_id: int | None = Field(default=None, ge=1)
    first_registered_stage: OpportunityFirstRegisteredStage


class OpportunityListItem(OpportunityStateView):
    """Opportunity row with link/record summaries for the list screen."""

    links: list[OpportunityLinkView] = Field(default_factory=list)


class OpportunityDetailResponse(OpportunityStateView):
    """Single opportunity with every stored link, including search failures."""

    links: list[OpportunityLinkView] = Field(default_factory=list)


class OpportunityListResponse(RuntimeContractModel):
    items: list[OpportunityListItem] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class TrackingStatusUpdateRequest(RuntimeContractModel):
    """Human tracking choice; actor identity comes only from request headers."""

    tracking_status: str = Field(
        validation_alias=AliasChoices("tracking_status", "status"),
        min_length=1,
    )
    reason: str = Field(
        validation_alias=AliasChoices("reason", "tracking_reason"),
        min_length=1,
    )


OpportunitySort = Literal["created_at", "tracking_status", "first_registered_stage"]


__all__ = [
    "OpportunityDetailResponse",
    "OpportunityFirstRegisteredStage",
    "OpportunityLinkView",
    "OpportunityListItem",
    "OpportunityListResponse",
    "OpportunityLinkStage",
    "OpportunityLinkStatus",
    "OpportunityLinkType",
    "OpportunitySearchStrategy",
    "OpportunitySort",
    "OpportunityStateView",
    "OpportunityTrackingStatus",
    "TrackingStatusUpdateRequest",
]
