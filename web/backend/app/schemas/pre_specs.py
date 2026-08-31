"""Safe cumulative pre-specification list and overview contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from . import AwareDateTime, Digest, NonEmpty, RuntimeContractModel
from .opportunities import OpportunityTrackingStatus


PreSpecOrigin = Literal["추적", "신규"]
PreSpecSort = Literal["published", "deadline"]
PreSpecOverviewCutStatus = Literal["pending", "ready", "unknown", "failed"]
PreSpecOverviewReviewStatus = Literal[
    "awaiting_document",
    "awaiting_structure",
    "preparing",
    "awaiting_model",
    "queued",
    "running",
    "needs_human_review",
    "completed",
    "failed",
    "cancelled",
]
PreSpecOverviewAttemptStatus = Literal[
    "queued", "running", "completed", "failed", "cancelled"
]
PreSpecOverviewStrategy = Literal["toc_body_match", "topic_heading"]
PreSpecOverviewRecommendation = Literal["추진 검토", "조건부 추진 검토", "보류", "검토 종료"]
PreSpecOverviewValidationStatus = Literal["passed", "failed", "pending"]


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


class PreSpecOverviewSnapshotView(RuntimeContractModel):
    """Safe immutable input lineage; raw structure blocks are never exposed."""

    id: UUID
    document_version_id: UUID
    structure_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cut_status: PreSpecOverviewCutStatus
    strategy: PreSpecOverviewStrategy | None = None
    start_locator: dict[str, Any] | None = None
    end_locator: dict[str, Any] | None = None
    created_at: AwareDateTime


class PreSpecOverviewResultLocator(RuntimeContractModel):
    """The only document location a phase 2 result may expose."""

    block_key: NonEmpty
    page: int = Field(ge=1)
    ordinal: int = Field(ge=0)

    @field_validator("block_key")
    @classmethod
    def locator_key_is_not_a_path(cls, value: str) -> str:
        if "/" in value or "\\" in value:
            raise ValueError("locator block_key must not contain a path")
        return value


class PreSpecOverviewUnknown(RuntimeContractModel):
    topic: NonEmpty
    reason: NonEmpty
    verification_action: NonEmpty | None


class PreSpecOverviewEvidence(RuntimeContractModel):
    claim: NonEmpty
    locator: PreSpecOverviewResultLocator


class PreSpecOverviewResultPayload(RuntimeContractModel):
    """Strict provider result accepted by the phase 2 result validator."""

    schema_version: Literal["bidops.prespec-overview-result.v1"]
    recommendation: PreSpecOverviewRecommendation
    summary: NonEmpty
    conditions: list[NonEmpty]
    verification_due_at: AwareDateTime | None
    unknowns: list[PreSpecOverviewUnknown]
    evidence: list[PreSpecOverviewEvidence]
    input_limitations: list[NonEmpty]

    @field_validator("verification_due_at")
    @classmethod
    def normalize_due_at(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def conditional_recommendation_requires_due(self) -> "PreSpecOverviewResultPayload":
        if self.recommendation == "조건부 추진 검토":
            if not self.conditions:
                raise ValueError("conditional recommendation requires conditions")
            if self.verification_due_at is None:
                raise ValueError("conditional recommendation requires verification_due_at")
        return self


class PreSpecOverviewResultView(PreSpecOverviewResultPayload):
    """Safe result payload; it contains no provider or storage metadata."""


class PreSpecOverviewAttemptV2View(RuntimeContractModel):
    id: UUID
    snapshot_id: UUID
    sequence: int = Field(ge=1)
    status: PreSpecOverviewAttemptStatus
    reference_only: bool
    deployable: bool
    validation_status: PreSpecOverviewValidationStatus
    result_digest: Digest | None = None
    binding_digest: Digest | None = None
    created_at: AwareDateTime
    started_at: AwareDateTime | None = None
    completed_at: AwareDateTime | None = None


class PreSpecOverviewReviewV2View(RuntimeContractModel):
    id: UUID
    notice_id: int = Field(ge=1)
    status: PreSpecOverviewReviewStatus
    result: PreSpecOverviewResultView | None = None
    result_digest: Digest | None = None
    binding_digest: Digest | None = None
    validation_status: PreSpecOverviewValidationStatus
    completed_at: AwareDateTime | None = None
    current_snapshot: PreSpecOverviewSnapshotView | None = None
    attempts: list[PreSpecOverviewAttemptV2View] = Field(default_factory=list)


class PreSpecOverviewReviewsV2Response(RuntimeContractModel):
    schema_version: Literal["bidops.prespec-overview-reviews.v2"]
    notice_id: int = Field(ge=1)
    reviews: list[PreSpecOverviewReviewV2View] = Field(default_factory=list)


class PreSpecOverviewAttemptView(RuntimeContractModel):
    """Safe append-only attempt summary without provider/prompt/response data."""

    id: UUID
    snapshot_id: UUID
    sequence: int = Field(ge=1)
    status: PreSpecOverviewAttemptStatus
    reference_only: bool
    deployable: bool
    created_at: AwareDateTime
    started_at: AwareDateTime | None = None
    completed_at: AwareDateTime | None = None


class PreSpecOverviewReviewView(RuntimeContractModel):
    id: UUID
    notice_id: int = Field(ge=1)
    status: PreSpecOverviewReviewStatus
    result: Literal["추진 검토", "조건부 추진 검토", "보류", "검토 종료"] | None = None
    completed_at: AwareDateTime | None = None
    current_snapshot: PreSpecOverviewSnapshotView | None = None
    attempts: list[PreSpecOverviewAttemptView] = Field(default_factory=list)


class PreSpecOverviewReviewsResponse(RuntimeContractModel):
    schema_version: Literal["bidops.prespec-overview-reviews.v1"]
    notice_id: int = Field(ge=1)
    reviews: list[PreSpecOverviewReviewView] = Field(default_factory=list)


__all__ = [
    "PreSpecDocumentSummary",
    "PreSpecListItem",
    "PreSpecListResponse",
    "PreSpecOrigin",
    "PreSpecSort",
    "PreSpecOverviewAttemptStatus",
    "PreSpecOverviewAttemptView",
    "PreSpecOverviewAttemptV2View",
    "PreSpecOverviewCutStatus",
    "PreSpecOverviewEvidence",
    "PreSpecOverviewRecommendation",
    "PreSpecOverviewResultLocator",
    "PreSpecOverviewResultPayload",
    "PreSpecOverviewResultView",
    "PreSpecOverviewReviewStatus",
    "PreSpecOverviewReviewView",
    "PreSpecOverviewReviewV2View",
    "PreSpecOverviewReviewsResponse",
    "PreSpecOverviewReviewsV2Response",
    "PreSpecOverviewSnapshotView",
    "PreSpecOverviewStrategy",
    "PreSpecOverviewUnknown",
    "PreSpecOverviewValidationStatus",
]
