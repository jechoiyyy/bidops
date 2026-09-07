"""REST contracts for cumulative business-opportunity tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, Field

from ...core.schema_base import AwareDateTime, RuntimeContractModel


OpportunitySection = Literal["조치 필요", "추적 중", "보류", "추적 종료"]
OpportunitySectionCountKey = Literal["조치 필요", "추적 중", "보류", "추적 종료", "미결정"]

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
    section: OpportunitySection | None = None
    pending_candidate_link_count: int = Field(default=0, ge=0)
    open_blocking_item_count: int = Field(default=0, ge=0)
    recheck_signal: bool
    recheck_signal_at: AwareDateTime | None = None
    recheck_signal_link_id: int | None = Field(default=None, ge=1)
    first_registered_stage: OpportunityFirstRegisteredStage
    merged_into_opportunity_id: int | None = Field(default=None, ge=1)
    merged_at: AwareDateTime | None = None
    merge_reason: str | None = None


class OpportunityListItem(OpportunityStateView):
    """Opportunity row with link/record summaries for the list screen."""

    links: list[OpportunityLinkView] = Field(default_factory=list)


class OpportunityDetailResponse(OpportunityStateView):
    """Single opportunity with every stored link, including search failures."""

    links: list[OpportunityLinkView] = Field(default_factory=list)


class OpportunityTrackingDecisionView(RuntimeContractModel):
    decided_at: AwareDateTime
    tracking_status: str
    previous_tracking_status: str | None = None
    reason: str | None = None
    claimed_name: str | None = None
    audit_event_id: UUID
    cleared_recheck_signal: bool


class OpportunityTrackingDecisionsResponse(RuntimeContractModel):
    opportunity_id: int = Field(ge=1)
    items: list[OpportunityTrackingDecisionView] = Field(default_factory=list)


class OpportunityListResponse(RuntimeContractModel):
    section_counts: dict[OpportunitySectionCountKey, int]
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


class CandidateDecisionRequest(RuntimeContractModel):
    """Human decision for one pending candidate lifecycle link."""

    decision: Literal["accepted", "rejected"]
    reason: str = Field(min_length=1)


OpportunitySort = Literal["created_at", "tracking_status", "first_registered_stage"]


__all__ = [
    "CandidateDecisionRequest",
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
    "OpportunitySection",
    "OpportunityTrackingDecisionView",
    "OpportunityTrackingDecisionsResponse",
    "OpportunityStateView",
    "OpportunityTrackingStatus",
    "TrackingStatusUpdateRequest",
]
