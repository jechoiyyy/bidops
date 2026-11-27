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


# v1 reason + ``graph_path_indexes`` into the frozen ``input.graph_paths``.
# No docstrings on the v2 models: their JSON schema is frozen byte-for-byte in
# the approved policy's ``prompt_output_contract``.
class FitReasonV2(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["scope_match", "scope_mismatch", "information_gap"]
    explanation: Text
    notice_refs: list[str] = Field(min_length=1, max_length=8)
    company_refs: list[str] = Field(max_length=8)
    graph_path_indexes: list[int] = Field(max_length=32)


# DEMO company-fit result (``bidops.prespec-company-fit-result.v2``). Same
# decision/summary/reason rules as v1; ``notice_refs`` cite frozen
# ``requirements[].id``, ``company_refs`` cite ``profile_facts[].fact_key`` and
# ``graph_path_indexes`` cite 0-based positions of ``graph_paths``.
class CompanyFitPayloadV2(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["bidops.prespec-company-fit-result.v2"]
    decision: Decision
    summary: Text
    reasons: list[FitReasonV2] = Field(min_length=1, max_length=8)
    verification_items: list[Text] = Field(max_length=8)

    @model_validator(mode="after")
    def consistent_decision(self):
        return CompanyFitPayload.consistent_decision(self)


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
    overview_kind: Literal["overview_run"]
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


class CompanyFitViewV2(CompanyFitView):
    """사전규격 회사 핏 응답 v2의 attempt (PS-01 C5).

    ``CompanyFitView``(v1)는 회사 lineage 응답(``CompanyScopedFitView``)이 그대로 쓰므로
    바꾸지 않는다. v2는 lineage·카드 신원·판정 주체·카드 근거 표시 이름을 더하고,
    카드 lineage에는 없는 프로필 신원을 nullable로 둔다.
    """

    lineage: Literal["profile", "card"]
    profile_version_id: UUID | None
    profile_sha256: str | None
    card_version: str | None
    card_sha256: str | None
    judged_by: Literal["model", "claude_reference"] | None
    company_fact_labels: dict[str, str] | None


class CompanyFitCardMode(RuntimeContractModel):
    """카드 모드 실효 상태 (C4). ``mode``·``set_by``·``set_at``은 최신 모드 행이며 행이 없으면 off·null이다."""

    mode: Literal["off", "suggest"]
    effective: bool
    reason_code: str | None
    card_version: str | None
    card_sha256: str | None
    prompt_version: str
    set_by: str | None = None
    set_at: datetime | None = None


class CompanyFitModeCommand(RuntimeContractModel):
    mode: str
    reason: str | None = None
    request_id: UUID


class CompanyFitResponse(RuntimeContractModel):
    schema_version: Literal["bidops.prespec-company-fit.v2"] = "bidops.prespec-company-fit.v2"
    notice_id: int
    attempts: list[CompanyFitViewV2]
    automation_enabled: bool
    mode: CompanyFitCardMode
    engine_suggested: bool
    auto_deep_review_reason: str | None
    deep_review_id: UUID | None
