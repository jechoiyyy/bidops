"""REST contracts for bid-delta comparisons and final decisions."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


BidDeltaCategory = Literal[
    "budget_and_economics",
    "contract_period_and_schedule",
    "eligibility",
    "joint_supply_and_subcontracting",
    "scope_and_requirements",
    "evaluation",
    "submission",
]
CalculationStatus = Literal["pending", "running", "completed", "failed"]
ResultStatus = Literal["changed", "unchanged", "unknown", "failed"]
Materiality = Literal["material", "non_material", "unknown"]
Currentness = Literal["current", "stale", "unknown"]


class BidDeltaModel(BaseModel):
    """Strict wire model; unknown request/response fields are not accepted."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=False,
        from_attributes=True,
    )


class BidDeltaInputFence(BidDeltaModel):
    opportunity_link_id: int = Field(ge=1)
    notice_id: int = Field(ge=1)
    bundle_id: UUID
    bundle_revision: int = Field(ge=1)
    bundle_version: int = Field(ge=1)
    document_version_id: UUID
    document_version_version: int = Field(ge=1)
    structure_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    structure_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BidDeltaInputRef(BidDeltaInputFence):
    notice_source_type: str
    notice_external_id: str
    bid_ordinal: str | None
    published_at: datetime | None
    document_role: str
    effective_date: date | None


class BidDeltaComparisonCreateRequest(BidDeltaModel):
    schema_version: Literal["bidops.bid-delta-comparison-create.v1"]
    request_id: UUID
    category_policy_version: str = Field(min_length=1, max_length=64)
    baseline: BidDeltaInputFence
    comparison: BidDeltaInputFence


class BidDeltaAttemptCreateRequest(BidDeltaModel):
    schema_version: Literal["bidops.bid-delta-attempt-create.v1"]
    request_id: UUID
    expected_comparison_version: int = Field(ge=1)


class BidFinalDecisionCreateRequest(BidDeltaModel):
    schema_version: Literal["bidops.bid-final-decision-create.v1"]
    request_id: UUID
    expected_comparison_version: int = Field(ge=1)
    expected_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_document_version_id: UUID
    comparison_document_version_id: UUID
    supersedes_final_decision_id: UUID | None
    decision: str
    reason: str


class BidDeltaEvidenceView(BidDeltaModel):
    id: UUID
    side: Literal["baseline", "comparison"]
    document_version_id: UUID
    structure_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator_type: Literal["page", "paragraph", "table_cell", "bbox"]
    locator: dict[str, Any]
    quote: str | None
    verification_status: Literal["verified", "missing", "mismatch"]


class BidDeltaItemView(BidDeltaModel):
    id: UUID
    ordinal: int = Field(ge=1)
    category: BidDeltaCategory
    result_status: ResultStatus
    materiality: Materiality
    before_value: str | None
    after_value: str | None
    summary: str | None
    baseline_evidence: list[BidDeltaEvidenceView]
    comparison_evidence: list[BidDeltaEvidenceView]
    error_code: str | None


class BidDeltaAttemptView(BidDeltaModel):
    id: UUID
    sequence: int = Field(ge=1)
    status: Literal["queued", "running", "completed", "failed"]
    started_at: datetime | None
    completed_at: datetime | None
    last_error_code: str | None


class BidFinalDecisionView(BidDeltaModel):
    schema_version: Literal["bidops.bid-final-decision.v1"]
    id: UUID
    opportunity_id: int = Field(ge=1)
    sequence: int = Field(ge=1)
    comparison_id: UUID
    comparison_version: int = Field(ge=1)
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_document_version_id: UUID
    comparison_document_version_id: UUID
    supersedes_final_decision_id: UUID | None
    decision: Literal["go", "no_go"]
    reason: str
    claimed_name: str
    request_id: UUID
    created_at: datetime
    currentness: Currentness
    currentness_reasons: list[str]


class BidDeltaComparisonView(BidDeltaModel):
    schema_version: Literal["bidops.bid-delta-comparison.v1"]
    id: UUID
    opportunity_id: int = Field(ge=1)
    sequence: int = Field(ge=1)
    version: int = Field(ge=1)
    category_policy_version: str
    calculation_status: CalculationStatus
    result_status: ResultStatus | None
    materiality: Materiality
    baseline: BidDeltaInputRef
    comparison: BidDeltaInputRef
    items: list[BidDeltaItemView]
    attempts: list[BidDeltaAttemptView]
    result_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    last_error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    final_decisions: list[BidFinalDecisionView]
    latest_final_decision: BidFinalDecisionView | None
    decision_currentness: Currentness
    currentness_reasons: list[str]


class BidDeltaComparisonSummary(BidDeltaModel):
    id: UUID
    sequence: int = Field(ge=1)
    version: int = Field(ge=1)
    category_policy_version: str
    calculation_status: CalculationStatus
    result_status: ResultStatus | None
    materiality: Materiality
    baseline: BidDeltaInputRef
    comparison: BidDeltaInputRef
    result_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class BidDeltaWorkspaceView(BidDeltaModel):
    schema_version: Literal["bidops.bid-delta-workspace.v1"]
    opportunity_id: int = Field(ge=1)
    baseline_candidates: list[BidDeltaInputRef]
    comparison_candidates: list[BidDeltaInputRef]
    comparisons: list[BidDeltaComparisonSummary]
    latest_final_decision: BidFinalDecisionView | None
    decision_currentness: Currentness
    currentness_reasons: list[str]
    generated_at: datetime


__all__ = [
    "BidDeltaAttemptCreateRequest",
    "BidDeltaAttemptView",
    "BidDeltaCategory",
    "BidDeltaComparisonCreateRequest",
    "BidDeltaComparisonSummary",
    "BidDeltaComparisonView",
    "BidDeltaEvidenceView",
    "BidDeltaInputFence",
    "BidDeltaInputRef",
    "BidDeltaItemView",
    "BidDeltaWorkspaceView",
    "BidFinalDecisionCreateRequest",
    "BidFinalDecisionView",
]
