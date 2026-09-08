"""Company-fit inference with references to frozen overview and profile facts."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...core.schema_base import RuntimeContractModel

Text = Annotated[str, Field(min_length=1, max_length=2000)]
Decision = Literal["matched", "mismatch", "unknown"]


class FitReason(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["scope_match", "scope_mismatch", "information_gap"]
    explanation: Text
    notice_refs: list[str] = Field(min_length=1, max_length=8)
    company_refs: list[str] = Field(max_length=8)


class CompanyFitPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["bidops.prespec-company-fit-result.v1"]
    decision: Decision
    summary: Text
    reasons: list[FitReason] = Field(min_length=1, max_length=8)
    verification_items: list[Text] = Field(max_length=8)

    @model_validator(mode="after")
    def consistent_decision(self):
        kinds = {reason.kind for reason in self.reasons}
        if self.decision == "matched" and kinds != {"scope_match"}:
            raise ValueError("matched_requires_supported_matches")
        if self.decision == "mismatch" and "scope_mismatch" not in kinds:
            raise ValueError("mismatch_requires_supported_gap")
        if self.decision == "unknown" and ("information_gap" not in kinds or not self.verification_items):
            raise ValueError("unknown_requires_verification")
        return self


class FitNoticeFact(RuntimeContractModel):
    ref: str
    text: str
    pages: list[int]
    block_key: str | None = None


class FitCompanyFact(RuntimeContractModel):
    ref: str
    fact_key: str
    status: Literal["confirmed", "inferred", "unknown"]
    value: str | int | float | bool | list | dict | None


class CompanyFitView(RuntimeContractModel):
    id: UUID
    notice_id: int
    status: Literal["queued", "running", "completed", "failed", "needs_human_review"]
    result: CompanyFitPayload | None
    error_code: str | None
    is_current: bool
    overview_kind: Literal["page", "extractive"]
    overview_id: UUID
    document_version_id: UUID
    overview_sha256: str
    profile_version_id: UUID
    profile_sha256: str
    policy_digest: str
    model_name: str
    model_revision: str
    prompt_version: str
    quality_status: Literal["unmeasured_reference", "mock_reference"]
    notice_facts: list[FitNoticeFact]
    company_facts: list[FitCompanyFact]
    created_at: datetime
    completed_at: datetime | None
    prompt_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None


class CompanyFitResponse(RuntimeContractModel):
    schema_version: Literal["bidops.prespec-company-fit.v1"] = "bidops.prespec-company-fit.v1"
    notice_id: int
    attempts: list[CompanyFitView]
    automation_enabled: bool
    auto_deep_review_reason: str | None
    deep_review_id: UUID | None
