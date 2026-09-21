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
FinalDecisionBasisKind = Literal["comparison", "notice_conditions"]
ChangeStatus = Literal["changed", "unchanged", "unknown"]


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


class BidNoticeFinalDecisionCreateRequest(BidDeltaModel):
    """Final decision on the latest bid notice's conditions (ADR-0058).

    The two expected values fence the exact bid notice and observation the
    person reviewed; the server does not pick a notice on the client's behalf.
    """

    request_id: UUID
    expected_notice_id: int = Field(ge=1)
    expected_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
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
    # v2 (ADR-0058): basis_kind·basis_* added and the comparison fields became
    # nullable. Stored v1 replay receipts are upgraded on read, see
    # ``services.bid_delta.final_decision_receipt``.
    schema_version: Literal["bidops.bid-final-decision.v2"]
    id: UUID
    opportunity_id: int = Field(ge=1)
    sequence: int = Field(ge=1)
    basis_kind: FinalDecisionBasisKind
    # comparison basis: the five comparison fields are set and basis_* are null.
    # notice_conditions basis: the reverse (DB CHECK ck_bid_final_decision_basis_fields).
    comparison_id: UUID | None
    comparison_version: int | None = Field(ge=1)
    result_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_document_version_id: UUID | None
    comparison_document_version_id: UUID | None
    basis_notice_id: int | None = Field(ge=1)
    basis_observation_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
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


class BidDecisionQueueLatestDecision(BidDeltaModel):
    decision: Literal["go", "no_go"]
    decided_at: datetime
    claimed_name: str


class BidDecisionQueueItem(BidDeltaModel):
    opportunity_id: int
    title: str | None
    agency: str | None
    tracking_status: str
    first_registered_stage: str
    recheck_signal: bool
    bid_notice_external_id: str | None
    comparison_count: int
    latest_final_decision: BidDecisionQueueLatestDecision | None
    decision_currentness: Currentness
    # Additive projection (0921_practitioner-screens spec §5): the selected bid
    # notice's own deadline/amount columns, for the queue's default sort and
    # display. When no bid notice is selected for the opportunity, all three
    # stay ``None`` — they are never inferred from the order plan or pre-spec.
    # Amounts stay Decimal strings (same convention as ``BidConditionValues``)
    # so exact values are never lost to float rounding.
    deadline_at: datetime | None
    budget: str | None
    estimated_price: str | None


class BidDecisionQueueResponse(BidDeltaModel):
    items: list[BidDecisionQueueItem]
    total: int
    limit: int
    offset: int


class BidConditionValues(BidDeltaModel):
    """Deterministic conditions read from the collected notice (no model call).

    Amounts are Decimal strings; timestamps keep the stored instant. ``null``
    means the value was not observed and is never read as "none" or ``N``.
    """

    budget: str | None
    estimated_price: str | None
    deadline_at: datetime | None
    opening_at: str | None
    method: str | None
    participation_limited: str | None
    industry_limited: str | None
    sw_industry_1468: str | None
    joint_contract_method: str | None
    successful_bid_method: str | None
    technical_evaluation_rate: str | None
    region_limit_basis: str | None
    joint_contract_regions: list[str] | None
    change_reason: str | None
    re_notice: str | None


BidConditionField = Literal[
    "budget",
    "estimated_price",
    "deadline_at",
    "opening_at",
    "method",
    "participation_limited",
    "industry_limited",
    "sw_industry_1468",
    "joint_contract_method",
    "successful_bid_method",
    "technical_evaluation_rate",
    "region_limit_basis",
    "joint_contract_regions",
    "change_reason",
    "re_notice",
]


class BidConditionChange(BidDeltaModel):
    field: BidConditionField
    status: ChangeStatus
    before: Any
    after: Any


class BidConditionNotice(BidDeltaModel):
    notice_id: int = Field(ge=1)
    bid_no: str | None
    bid_ord: str | None
    published_at: datetime | None
    observation_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    conditions: BidConditionValues
    changes_from_previous: list[BidConditionChange]


class BidConditionPreSpec(BidDeltaModel):
    notice_id: int = Field(ge=1)
    title: str | None
    agency: str | None
    budget: str | None


class BidConditionPreSpecChange(BidDeltaModel):
    field: Literal["budget", "title"]
    status: ChangeStatus
    before: str | None
    after: str | None


class BidConditionsView(BidDeltaModel):
    opportunity_id: int = Field(ge=1)
    generated_at: datetime
    # The exact fence a notice-conditions final decision must submit. Both are
    # null when there is no authoritative bid notice or the latest one cannot be
    # determined; the observation hash is also null when that notice has none.
    latest_notice_id: int | None = Field(ge=1)
    latest_observation_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    pre_spec: BidConditionPreSpec | None
    bid_notices: list[BidConditionNotice]
    pre_spec_comparison: list[BidConditionPreSpecChange]
    not_comparable: list[Literal["deadline_at"]]


__all__ = [
    "BidConditionChange",
    "BidConditionNotice",
    "BidConditionPreSpec",
    "BidConditionPreSpecChange",
    "BidConditionValues",
    "BidConditionsView",
    "BidDecisionQueueItem",
    "BidDecisionQueueLatestDecision",
    "BidDecisionQueueResponse",
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
    "BidNoticeFinalDecisionCreateRequest",
]
