"""Strict wire models for the four lean deep-review report endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .document_bundles import DocumentStructurePageView


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class ReportRow(StrictModel):
    row_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    cells: list[str]
    claim_ids: list[UUID]


ReportBlockType = Literal["paragraph", "matrix", "decision_card", "scenario", "action_list"]
ReportSectionKey = Literal[
    "project_overview", "eligibility_matrix", "scope_deliverables", "requirements_matrix",
    "evaluation_strategy", "delivery_plan", "technical_integration_risks",
    "security_legal_contract_risks", "economics_scenarios", "competitive_proposal_strategy",
    "questions_internal_actions", "document_bundle_limitations", "decision_card",
]


class ReportBlock(StrictModel):
    block_id: str = Field(min_length=1)
    type: ReportBlockType
    title: str | None
    body: str | None
    claim_ids: list[UUID]
    rows: list[ReportRow]


class ReportSection(StrictModel):
    section_key: ReportSectionKey
    title: str = Field(min_length=1)
    blocks: list[ReportBlock]


class ReportClaim(StrictModel):
    claim_id: UUID
    category: str = Field(min_length=1)
    claim_type: Literal["fact", "calculation", "inference", "opinion", "unknown"]
    body: str = Field(min_length=1)
    status: Literal["supported", "unsupported", "conflicting", "unknown"]
    formula: str | None
    premise_claim_ids: list[UUID]
    reason: str | None
    evidence_ids: list[UUID]


class ValidationSummary(StrictModel):
    status: Literal["passed", "failed"]
    failed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    passed: int = Field(ge=0)


class DeepReviewReport(StrictModel):
    schema: Literal["bidops.deep-review-report.v1"]
    deep_review_id: UUID
    notice_id: int
    bundle_id: UUID
    profile_version_id: UUID
    policy_version_id: UUID
    sections: list[ReportSection]
    system_recommendation: Literal["추진 검토", "조건부 추진 검토", "보류", "검토 종료"]
    claims: list[ReportClaim]
    unknowns: list[str]
    validation_summary: ValidationSummary
    created_at: datetime


class ValidationCheck(StrictModel):
    check_type: str = Field(min_length=1)
    status: Literal["passed", "failed", "warning"]
    severity: Literal["차단", "중대", "보통", "낮음"]
    message: str = Field(min_length=1)
    related_claim_ids: list[UUID]
    related_evidence_ids: list[UUID]


class DeepReviewValidation(StrictModel):
    schema: Literal["bidops.deep-review-validation.v1"]
    validation_run_id: UUID
    report_revision_id: UUID
    status: Literal["passed", "failed"]
    checks: list[ValidationCheck]
    created_at: datetime


class RevisionHistoryItem(StrictModel):
    revision_id: UUID
    sequence: int = Field(ge=1)
    origin: Literal["machine", "human"]
    validation_status: Literal["passed", "failed"] | None
    created_by_name: str | None
    created_at: datetime


class FinalOpinionView(StrictModel):
    id: UUID
    sequence: int = Field(ge=1)
    value: Literal["추진", "조건부 추진", "보류", "검토 종료"]
    reason: str
    validation_status_at_opinion: Literal["passed", "failed"]
    acknowledged_validation_failure: bool
    claimed_name: str
    created_at: datetime


class ReportView(StrictModel):
    deep_review_id: UUID
    current_revision_id: UUID
    report: DeepReviewReport
    validation: DeepReviewValidation
    history: list[RevisionHistoryItem]
    final_opinion: FinalOpinionView | None


class ReportRevisionRequest(StrictModel):
    request_id: UUID
    base_revision_id: UUID
    report: DeepReviewReport
    reason: str
    factual_change_evidence_ids: list[UUID]

    @field_validator("reason")
    @classmethod
    def reason_is_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


class FinalOpinionRequest(StrictModel):
    request_id: UUID
    report_revision_id: UUID
    validation_run_id: UUID
    value: Literal["추진", "조건부 추진", "보류", "검토 종료"]
    reason: str
    acknowledged_validation_failure: bool


class EvidenceView(StrictModel):
    evidence_id: UUID
    source_kind: Literal["document", "profile"]
    document_version_id: UUID | None
    structure_id: UUID | None
    profile_version_id: UUID | None
    profile_evidence_id: UUID | None
    locator_type: Literal["page", "paragraph", "table_cell", "bbox", "profile_fact"]
    locator: dict[str, Any]
    quote: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: DocumentStructurePageView | None


__all__ = [
    "DeepReviewReport", "DeepReviewValidation", "EvidenceView", "FinalOpinionRequest",
    "FinalOpinionView", "ReportBlock", "ReportClaim", "ReportRevisionRequest", "ReportRow",
    "ReportSection", "ReportView", "RevisionHistoryItem", "ValidationCheck", "ValidationSummary",
]
