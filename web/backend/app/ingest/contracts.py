"""Pydantic models for the BidOps artifact contract.

The producer-side contract is intentionally stricter than the importer needs
to be.  The importer must be able to display an already-produced, older
artifact, so fields whose absence is an ingest warning are represented as
optional here.  ``model_fields_set`` and the raw artifact are retained by the
loader to distinguish an absent value from an explicitly empty value.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    """Base class that preserves unknown keys for an ingest info warning."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class SourceWindow(ContractModel):
    from_: date | str | None = Field(default=None, alias="from")
    to: date | str | None = None
    timezone: str | None = None


class ProcurementClass(ContractModel):
    large: str | None = None
    middle: str | None = None
    detail: str | None = None
    code: str | None = None


class RegionLimit(ContractModel):
    basis: Any = None
    joint_contract_regions: list[Any] | None = None
    joint_contract_rate: Any = None
    regional_joint_contract_limit: Any = None


class Lifecycle(ContractModel):
    pre_spec_no: Any = None
    re_notice: Any = None
    changed_at: Any = None
    change_reason: Any = None
    unified_notice_no: Any = None
    previous_failed_notice_no: Any = None
    # Optional in collected.v2.  This is a projection of the bid API's own
    # orderPlanUntyNo value; keeping it optional preserves old v2 artifacts.
    order_plan_no: Any = None
    # Optional projection of the pre-spec response's bidNtceNoList.  Empty
    # source values remain null; a missing field is not fabricated.
    bid_ntice_no_list: Any = None


class QualificationFlags(ContractModel):
    participation_limited: Any = None
    industry_limited: Any = None
    information_business: Any = None
    general_service: Any = None
    service_division: Any = None
    joint_contract_method: Any = None
    performance_restricted_competition: Any = None
    pq_evaluation: Any = None
    technical_evaluation: Any = None
    technical_evaluation_rate: Any = None
    successful_bid_method: Any = None
    # Pre-spec-only API projections.  They are optional so older collected.v2
    # notices and bid-only qualification objects remain readable.
    sw_business_status: Any = None
    business_division: Any = None


class AttachmentContract(ContractModel):
    name: str | None = None
    url: str | None = None


class NoticeContract(ContractModel):
    """A normalized notice as present in validation, screening, or collection."""

    notice_id: str | None = None
    source_type: str | None = None
    title: str | None = None
    agency: str | None = None
    published_at: datetime | str | None = None
    deadline_at: datetime | str | None = None
    budget: Decimal | int | float | str | None = None
    estimated_price: Decimal | int | float | str | None = None
    method: str | None = None
    url: str | None = None
    procurement_class: ProcurementClass | dict[str, Any] | None = None
    region_limit: RegionLimit | dict[str, Any] | None = None
    lifecycle: Lifecycle | dict[str, Any] | None = None
    attachments: list[AttachmentContract | dict[str, Any]] | None = None
    qualification_flags: QualificationFlags | dict[str, Any] | None = None
    focus_matches: list[dict[str, Any]] | None = None
    performance_matches: list[dict[str, Any]] | None = None
    performance_top_score: float | int | str | None = None
    candidate_sources: list[Any] | None = None
    collection_bucket: str | None = None
    unknown_fields: list[Any] | None = None
    raw_source: Any = None
    sample_role: str | None = None
    sample_stratum: str | None = None


class EvidenceContract(ContractModel):
    source: str | None = None
    status: str | None = None
    fact: str | None = None


class PerspectiveContract(ContractModel):
    position: int | None = None
    name: str | None = None
    assessment: str | None = None
    reason: str | None = None
    evidence: list[EvidenceContract | dict[str, Any]] | None = None


class CounterargumentContract(ContractModel):
    position: int | None = None
    text: str | None = None


class VerificationItemContract(ContractModel):
    item: str | None = None
    why: str | None = None
    blocking: bool | None = None
    status: str | None = None


class MatchedPerformanceContract(ContractModel):
    name: str | None = None
    project_name: str | None = None
    match_reason: str | None = None
    mismatch_or_limit: str | None = None
    source: str | None = None
    source_page: str | None = None
    similarity: float | int | str | None = None
    common_fragment: str | None = None
    status: str | None = None
    legal_qualification_status: str | None = None


class JudgmentContract(ContractModel):
    """A judgment in either decisions.v1 or decisions.v2 form.

    ``notice_id`` is present in decisions.v1.  In screening-results.v2 it is
    carried by the sibling ``notice`` object, so it is optional here and the
    loader supplies the sibling value only as an identifier, never as a
    defaulted judgment field.
    """

    notice_id: str | None = None
    grade: str | None = None
    readiness: str | None = None
    primary_focus: str | None = None
    exclusion_category: str | None = None
    summary: str | None = None
    perspectives: list[PerspectiveContract | dict[str, Any]] | None = None
    matched_performances: list[MatchedPerformanceContract | dict[str, Any]] | None = None
    counterarguments: list[str | CounterargumentContract | dict[str, Any]] | None = None
    verification_items: list[VerificationItemContract | dict[str, Any]] | None = None
    next_action: str | None = None


class DecisionArtifact(ContractModel):
    schema_version: str
    screening_basis: str | None = None
    generated_at: datetime | str | None = None
    source_window: SourceWindow | dict[str, Any] | None = None
    judgments: list[JudgmentContract | dict[str, Any]] | None = None
    # v3 generation binding.  Optional keeps v1/v2 importer compatibility;
    # the loader applies the strict pair/legacy normalization policy.
    generation_config: dict[str, Any] | None = None
    generation_config_digest: str | None = None


class ScreeningResultContract(ContractModel):
    notice: NoticeContract | dict[str, Any] | None = None
    judgment: JudgmentContract | dict[str, Any] | None = None


class ScreeningArtifact(ContractModel):
    schema_version: str
    generated_at: datetime | str | None = None
    screening_basis: str | None = None
    source_window: SourceWindow | dict[str, Any] | None = None
    results: list[ScreeningResultContract | dict[str, Any]] | None = None
    # v3 generation binding; see DecisionArtifact above.
    generation_config: dict[str, Any] | None = None
    generation_config_digest: str | None = None


class ValidationArtifact(ContractModel):
    schema_version: str
    generated_at: datetime | str | None = None
    source_window: SourceWindow | dict[str, Any] | None = None
    selection: dict[str, Any] | None = None
    warnings: list[Any] | None = None
    notices: list[NoticeContract | dict[str, Any]] | None = None


class CollectionArtifact(ContractModel):
    schema_version: str
    generated_at: datetime | str | None = None
    source_window: SourceWindow | dict[str, Any] | None = None
    counts: dict[str, Any] | None = None
    warnings: list[Any] | None = None
    notices: list[NoticeContract | dict[str, Any]] | None = None


class OrderPlanContract(ContractModel):
    """One normalized order-plan record in the independent plan artifact.

    The measured API spellings (``orderPlanUntyNo``, ``bidNtceNoList``,
    ``nticeNticeYn``, ``rcritRgstNo`` and ``chgDt``) are accepted by the
    importer as compatibility aliases.  The canonical producer spelling is
    snake_case so this artifact is not a hidden extension of collected.v2.
    ``sw_business_status`` is deliberately nullable: the plan response did
    not expose a measured SW flag, so the loader must not infer one.
    """

    order_plan_unty_no: str | None = None
    title: str | None = None
    agency_code: str | None = None
    agency_name: str | None = None
    supervising_agency_name: str | None = None
    business_division: str | None = None
    business_division_code: str | None = None
    service_type: str | None = None
    service_type_code: str | None = None
    budget_amount: Decimal | int | float | str | None = None
    contract_amount: Decimal | int | float | str | None = None
    planned_order_year: str | None = None
    planned_order_month: str | None = None
    procurement_method: str | None = None
    contract_method: str | None = None
    sw_business_status: str | None = None
    published_at: datetime | date | str | None = None
    changed_at: datetime | date | str | None = None
    bid_ntice_no_list: str | None = None
    notice_posted: str | None = None
    rcrit_rgst_no: str | None = None
    source_url: str | None = None
    official_url: str | None = None
    first_discovered_at: datetime | date | str | None = None
    last_discovered_at: datetime | date | str | None = None
    source_sha256: str | None = None
    unknown_fields: list[Any] | None = None
    raw_source: Any = None
    source: dict[str, Any] | None = None


class OrderPlanArtifact(ContractModel):
    """Independent, cumulative order-plan collection artifact."""

    schema_version: str
    generated_at: datetime | str | None = None
    # Metadata names used by the earlier offline population artifact.  They
    # are accepted for read-only compatibility; the canonical file uses
    # generated_at/source_window/counts below.
    run_id: str | None = None
    created_at: datetime | str | None = None
    input_sha256: str | None = None
    population_sha256: str | None = None
    source_window: SourceWindow | dict[str, Any] | None = None
    # The current producer records the endpoint and explicit business-scope
    # allowlist here so later runs can be compared when the scope changes.
    metadata: dict[str, Any] | None = None
    counts: dict[str, Any] | None = None
    warnings: list[Any] | None = None
    # Rows are validated individually by the loader so one malformed/partial
    # row can be warned and skipped without rejecting the whole artifact.
    order_plans: list[Any] | None = None
    # ``items`` and ``plans`` are read-only compatibility spellings for the
    # earlier offline population artifact and first producer drafts.  The
    # canonical file uses ``order_plans``.
    items: list[Any] | None = None
    plans: list[Any] | None = None


# C-2 Phase 2 artifacts ----------------------------------------------------
#
# The older importer models above intentionally allow extra fields for
# compatibility warnings.  C-2 is a frozen, versioned hand-off, so these
# models reject unknown keys and validate the state combinations that a JSON
# Schema ``if/then`` rule expresses.


class C2StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _c2_sha256(value: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("SHA-256 must be 64 lowercase hexadecimal characters")
    return value


def _c2_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


class C2ArtifactReference(C2StrictModel):
    name: str = Field(min_length=1)
    schema_version: Literal["bidops.collected-order-plans.v1"]
    sha256: str

    _validate_sha256 = field_validator("sha256")(_c2_sha256)

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or "/" in value or "\\" in value:
            raise ValueError("artifact name must be a single safe relative name")
        if value in {".", ".."}:
            raise ValueError("artifact name is unsafe")
        return value


class C2BindingReference(C2StrictModel):
    version: str = Field(min_length=1)
    sha256: str

    _validate_sha256 = field_validator("sha256")(_c2_sha256)


class OrderPlanScreeningInputItem(C2StrictModel):
    plan_id: str = Field(min_length=1)
    title: str = Field(min_length=1)


class OrderPlanScreeningInputArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-input.v1"]
    producer: Literal["order-plan-screening-orchestrator"]
    consumer: Literal["order-plan-screening-worker"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    source_artifact: C2ArtifactReference
    population_count: int = Field(ge=1)
    population_sha256: str
    policy: C2BindingReference
    stage1_binding: C2BindingReference
    stage2_binding: C2BindingReference
    items: list[OrderPlanScreeningInputItem] = Field(min_length=1)
    status: Literal["frozen"]
    created_at: datetime

    _validate_population_sha256 = field_validator("population_sha256")(_c2_sha256)
    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @model_validator(mode="after")
    def unique_population(self) -> "OrderPlanScreeningInputArtifact":
        ids = [item.plan_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("input items must contain unique plan_id values")
        if self.population_count != len(self.items):
            raise ValueError("population_count must equal the number of items")
        return self


class OrderPlanScreeningRankingItem(C2StrictModel):
    plan_id: str = Field(min_length=1)
    rank: int | None = Field(default=None, ge=1)
    score: float | None = Field(default=None, ge=0)
    nearest_capability: str | None = None
    stage1_status: Literal["selected", "filtered_out", "failed", "rejected"]

    @field_validator("score")
    @classmethod
    def finite_score(cls, value: float | None) -> float | None:
        if value is not None:
            import math

            if not math.isfinite(value):
                raise ValueError("score must be finite")
        return value


class OrderPlanScreeningRankingArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-ranking.v1"]
    producer: Literal["order-plan-screening-bm25"]
    consumer: Literal["order-plan-screening-merge"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    input_artifact_sha256: str
    policy_version: str = Field(min_length=1)
    policy_sha256: str
    status: Literal["성공", "실패"]
    population_count: int = Field(ge=1)
    selected_count: int = Field(ge=0)
    filtered_out_count: int = Field(ge=0)
    items: list[OrderPlanScreeningRankingItem] = Field(min_length=1)
    created_at: datetime

    _validate_input_sha256 = field_validator("input_artifact_sha256")(_c2_sha256)
    _validate_policy_sha256 = field_validator("policy_sha256")(_c2_sha256)
    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @model_validator(mode="after")
    def population_and_status(self) -> "OrderPlanScreeningRankingArtifact":
        if len(self.items) != self.population_count:
            raise ValueError("ranking must contain the full population")
        ids = [item.plan_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("ranking items must contain unique plan_id values")
        selected = sum(item.stage1_status == "selected" for item in self.items)
        filtered = sum(item.stage1_status == "filtered_out" for item in self.items)
        if selected != self.selected_count or filtered != self.filtered_out_count:
            raise ValueError("ranking counts do not match item statuses")
        for item in self.items:
            if item.stage1_status in {"selected", "filtered_out"} and (
                item.rank is None or item.score is None
            ):
                raise ValueError("rank and score are required for ranked items")
            if item.stage1_status in {"failed", "rejected"} and any(
                value is not None
                for value in (item.rank, item.score, item.nearest_capability)
            ):
                raise ValueError("failed or rejected ranking items must be null")
        return self


class OrderPlanScreeningDecisionBinding(C2StrictModel):
    model_name: Literal["qwen3.8-27B"]
    model_digest: str
    prompt_version: str = Field(min_length=1)
    prompt_sha256: str
    company_profile_version: str = Field(min_length=1)
    company_profile_sha256: str
    generation_config_sha256: str

    _validate_hashes = field_validator(
        "model_digest",
        "prompt_sha256",
        "company_profile_sha256",
        "generation_config_sha256",
    )(_c2_sha256)


class OrderPlanScreeningDecisionBatch(C2StrictModel):
    batch_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    plan_ids: list[str]
    attempt_count: int = Field(ge=1, le=2)
    status: Literal["success", "failed", "rejected"]


class OrderPlanScreeningDecisionItem(C2StrictModel):
    plan_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    attempt_no: int = Field(ge=1, le=2)
    relevance: Literal["relevant", "not_relevant", "uncertain"]
    score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("score")
    @classmethod
    def finite_score(cls, value: float) -> float:
        import math

        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


class OrderPlanScreeningDecisionsArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-decisions.v1"]
    producer: Literal["order-plan-screening-qwen-worker"]
    consumer: Literal["order-plan-screening-merge"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    input_artifact_sha256: str
    ranking_artifact_sha256: str
    binding: OrderPlanScreeningDecisionBinding
    status: Literal["성공", "부분 성공", "실패"]
    candidate_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    batch_count: int = Field(ge=0)
    batches: list[OrderPlanScreeningDecisionBatch]
    items: list[OrderPlanScreeningDecisionItem]
    created_at: datetime

    _validate_input_sha256 = field_validator("input_artifact_sha256")(_c2_sha256)
    _validate_ranking_sha256 = field_validator("ranking_artifact_sha256")(_c2_sha256)
    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @model_validator(mode="after")
    def unique_batches_and_items(self) -> "OrderPlanScreeningDecisionsArtifact":
        batch_ids = [batch.batch_id for batch in self.batches]
        if len(batch_ids) != len(set(batch_ids)) or self.batch_count != len(self.batches):
            raise ValueError("decision batch count or identity is invalid")
        item_ids = [item.plan_id for item in self.items]
        if len(item_ids) != len(set(item_ids)) or self.success_count != len(self.items):
            raise ValueError("decision item count or identity is invalid")
        if any(item.batch_id not in set(batch_ids) for item in self.items):
            raise ValueError("decision item references an unknown batch")
        return self


class OrderPlanScreeningFailure(C2StrictModel):
    batch_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    plan_ids: list[str] = Field(min_length=1)
    attempt_count: int = Field(ge=1, le=2)
    max_attempts: Literal[2]
    failure_type: Literal[
        "timeout", "truncated_output", "schema_violation", "id_mismatch",
        "model_mismatch", "binding_mismatch", "payload_not_approved", "transport",
        "policy_rejected", "unknown",
    ]
    outcome: Literal["failed", "rejected", "unknown"]
    status: Literal["human_review_required"]
    error_code: str = Field(min_length=1, max_length=128)


class OrderPlanScreeningFailuresArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-failures.v1"]
    producer: Literal["order-plan-screening-worker"]
    consumer: Literal["order-plan-screening-review-and-merge"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    status: Literal["none", "partial", "failed", "rejected"]
    failure_count: int = Field(ge=0)
    failures: list[OrderPlanScreeningFailure]
    created_at: datetime

    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @model_validator(mode="after")
    def count_failures(self) -> "OrderPlanScreeningFailuresArtifact":
        if self.failure_count != len(self.failures):
            raise ValueError("failure_count does not match failures")
        if not self.failures and self.status != "none":
            raise ValueError("empty failures artifact must have status none")
        if self.failures and self.status == "none":
            raise ValueError("non-empty failures artifact cannot have status none")
        return self


class OrderPlanScreeningMeasurement(C2StrictModel):
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)

    @field_validator("started_at", "finished_at")
    @classmethod
    def aware_if_present(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _c2_aware_datetime(value)

    @model_validator(mode="after")
    def ordered(self) -> "OrderPlanScreeningMeasurement":
        if self.started_at is not None and self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("measurement finished_at precedes started_at")
        return self


class OrderPlanScreeningTelemetryAttempt(C2StrictModel):
    attempt_no: int = Field(ge=1, le=2)
    status: Literal["success", "failed", "rejected"]
    started_at: datetime | None
    finished_at: datetime | None
    measurement: OrderPlanScreeningMeasurement

    @field_validator("started_at", "finished_at")
    @classmethod
    def aware_if_present(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _c2_aware_datetime(value)

    @model_validator(mode="after")
    def ordered(self) -> "OrderPlanScreeningTelemetryAttempt":
        if self.started_at is not None and self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("attempt finished_at precedes started_at")
        return self


class OrderPlanScreeningTelemetryBatch(C2StrictModel):
    batch_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    status: Literal["success", "failed", "rejected", "unknown"]
    attempts: list[OrderPlanScreeningTelemetryAttempt]


class OrderPlanScreeningTelemetryArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-telemetry.v1"]
    producer: Literal["order-plan-screening-worker"]
    consumer: Literal["observability-and-merge"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    status: Literal["complete", "partial", "not_measured"]
    execution: OrderPlanScreeningMeasurement
    batches: list[OrderPlanScreeningTelemetryBatch]
    created_at: datetime

    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)


class OrderPlanScreeningResultCounts(C2StrictModel):
    population: int = Field(ge=0)
    stage1_selected: int = Field(ge=0)
    stage1_filtered_out: int = Field(ge=0)
    stage1_failed: int = Field(ge=0)
    stage2_relevant: int = Field(ge=0)
    stage2_not_relevant: int = Field(ge=0)
    stage2_uncertain: int = Field(ge=0)
    stage2_failed: int = Field(ge=0)
    stage2_rejected: int = Field(ge=0)
    human_review_count: int = Field(ge=0)


class OrderPlanScreeningResultItem(C2StrictModel):
    plan_id: str = Field(min_length=1)
    stage1_status: Literal["selected", "filtered_out", "failed", "rejected"]
    stage1_rank: int | None = Field(ge=1)
    stage1_score: float | None = Field(ge=0)
    nearest_capability: str | None
    stage2_status: Literal["not_attempted", "success", "failed", "rejected", "unknown"]
    qwen_relevance: Literal["relevant", "not_relevant", "uncertain"] | None
    qwen_score: float | None = Field(ge=0, le=1)
    qwen_reason: str | None
    batch_id: str | None
    attempt_no: int | None = Field(ge=1, le=2)
    failure_code: str | None

    @field_validator("stage1_score", "qwen_score")
    @classmethod
    def finite_if_present(cls, value: float | None) -> float | None:
        if value is not None:
            import math

            if not math.isfinite(value):
                raise ValueError("score must be finite")
        return value

    @model_validator(mode="after")
    def state_fields(self) -> "OrderPlanScreeningResultItem":
        stage2_null = (
            self.qwen_relevance, self.qwen_score, self.qwen_reason,
            self.batch_id, self.attempt_no, self.failure_code,
        )
        if self.stage1_status in {"failed", "rejected"}:
            if self.stage2_status != "not_attempted" or any(
                value is not None for value in stage2_null
            ):
                raise ValueError("stage1 failure/rejection must not carry stage2 data")
            return self
        if self.stage1_rank is None or self.stage1_score is None:
            raise ValueError("rank and score are required for a ranked item")
        if self.stage1_status == "filtered_out" and self.stage2_status != "not_attempted":
            raise ValueError("filtered_out item must not be attempted")
        if self.stage2_status == "not_attempted":
            if any(value is not None for value in (self.qwen_relevance, self.qwen_score, self.qwen_reason, self.batch_id, self.attempt_no, self.failure_code)):
                raise ValueError("not_attempted item has result fields")
        elif self.stage2_status == "success":
            if self.qwen_relevance is None or self.qwen_score is None or self.qwen_reason is None or not self.qwen_reason.strip() or len(self.qwen_reason) > 500 or self.batch_id is None or self.attempt_no is None or self.failure_code is not None:
                raise ValueError("successful stage2 item is incomplete")
        else:
            if self.qwen_relevance is not None or self.qwen_score is not None or self.qwen_reason is not None or self.failure_code is None or not self.failure_code.strip():
                raise ValueError("failed stage2 item has invalid nullable fields")
        if (self.batch_id is None) != (self.attempt_no is None):
            raise ValueError("batch_id and attempt_no must be paired")
        return self


class OrderPlanScreeningResultArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-result.v1"]
    producer: Literal["order-plan-screening-merge"]
    consumer: Literal["postgres-loader-and-review-api"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    input_artifact_sha256: str
    policy_version: str = Field(min_length=1)
    policy_sha256: str
    status: Literal["성공", "부분 성공", "실패", "거부됨"]
    partial_artifact: bool
    counts: OrderPlanScreeningResultCounts
    items: list[OrderPlanScreeningResultItem] = Field(min_length=1)
    created_at: datetime

    _validate_input_sha256 = field_validator("input_artifact_sha256")(_c2_sha256)
    _validate_policy_sha256 = field_validator("policy_sha256")(_c2_sha256)
    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @model_validator(mode="after")
    def full_population_and_counts(self) -> "OrderPlanScreeningResultArtifact":
        ids = [item.plan_id for item in self.items]
        if len(ids) != len(set(ids)) or len(ids) != self.counts.population:
            raise ValueError("result must contain the full population exactly once")
        stage1_selected = sum(item.stage1_status == "selected" for item in self.items)
        stage1_filtered = sum(item.stage1_status == "filtered_out" for item in self.items)
        stage1_failed = sum(item.stage1_status in {"failed", "rejected"} for item in self.items)
        stage2_relevant = sum(item.qwen_relevance == "relevant" for item in self.items)
        stage2_not_relevant = sum(item.qwen_relevance == "not_relevant" for item in self.items)
        stage2_uncertain = sum(item.qwen_relevance == "uncertain" for item in self.items)
        stage2_failed = sum(item.stage2_status == "failed" for item in self.items)
        stage2_rejected = sum(item.stage2_status == "rejected" for item in self.items)
        expected = {
            "stage1_selected": stage1_selected,
            "stage1_filtered_out": stage1_filtered,
            "stage1_failed": stage1_failed,
            "stage2_relevant": stage2_relevant,
            "stage2_not_relevant": stage2_not_relevant,
            "stage2_uncertain": stage2_uncertain,
            "stage2_failed": stage2_failed,
            "stage2_rejected": stage2_rejected,
            "human_review_count": stage1_failed + stage2_failed + stage2_rejected + sum(item.stage2_status == "unknown" for item in self.items) + stage2_relevant + stage2_uncertain,
        }
        for field_name, value in expected.items():
            if getattr(self.counts, field_name) != value:
                raise ValueError(f"result count {field_name} does not match items")
        incomplete = stage1_failed + stage2_failed + stage2_rejected + sum(item.stage2_status == "unknown" for item in self.items)
        successful = stage2_relevant + stage2_not_relevant + stage2_uncertain
        expected_status = (
            "성공" if incomplete == 0 and successful == stage1_selected
            else "거부됨" if stage1_failed == 0 and stage1_selected > 0 and stage2_rejected == stage1_selected
            else "부분 성공" if successful > 0
            else "실패"
        )
        if self.status != expected_status or self.partial_artifact != (self.status != "성공"):
            raise ValueError("result status or partial_artifact is inconsistent")
        return self


class OrderPlanScreeningFeedbackArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-feedback.v1"]
    producer: Literal["human-review-api"]
    consumer: Literal["postgres-review-history"]
    feedback_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    actor_kind: Literal["human"]
    claimed_name: str = Field(min_length=1)
    relevance: Literal["relevant", "not_relevant", "uncertain"]
    priority: Literal["high", "medium", "low"] | None
    memo: str | None
    supersedes_feedback_id: str | None = None
    created_at: datetime

    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @field_validator("memo")
    @classmethod
    def nonblank_memo(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("memo must be nonblank when supplied")
        return value


class OrderPlanScreeningPolicyArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-policy.v1"]
    producer: Literal["phase0-contracts"]
    consumer: Literal["phase1-screening-pipeline"]
    policy_version: str = Field(min_length=1, max_length=64)
    policy_status: Literal["draft", "activation_candidate", "active", "retired"]
    decision_scope: Literal["c2_order_plan_first_pass"]
    created_at: datetime
    stage1: dict[str, Any]
    stage2: dict[str, Any]
    audit_sample: dict[str, Any]
    execution: dict[str, Any]
    feedback: dict[str, Any]
    quality_gate: dict[str, Any]
    bindings: dict[str, Any]
    activation: dict[str, Any]

    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)


class FeedbackAnswerContract(ContractModel):
    item: str | None = None
    answer: str | None = None


class FeedbackReviewContract(ContractModel):
    notice_id: str | None = None
    disposition: str | None = None
    system_judgment_review: str | None = None
    corrected_grade: str | None = None
    corrected_readiness: str | None = None
    weakest_perspective: str | None = None
    reason: str | None = None
    verification_answers: list[FeedbackAnswerContract | dict[str, Any]] | None = None


class FeedbackArtifact(ContractModel):
    schema_version: str
    reviews: list[FeedbackReviewContract | dict[str, Any]] | None = None


ModelT = TypeVar("ModelT", bound=BaseModel)


def as_model(value: Any, model: type[ModelT]) -> ModelT:
    """Validate a nested value while keeping a small, testable public helper."""

    return model.model_validate(value)


def is_blank(value: Any) -> bool:
    """Return whether a contract value is absent, empty, or whitespace-only."""

    return value is None or (isinstance(value, str) and not value.strip())


def model_extra_fields(value: Any, prefix: str = "") -> list[str]:
    """Collect unknown fields retained by ``extra='allow'`` models.

    Field paths make nested contract drift actionable while keeping the
    warning context compact.  Values in intentionally free-form JSON fields
    are not traversed because their keys are data, not contract fields.
    """

    found: list[str] = []

    def walk(item: Any, path: str) -> None:
        if isinstance(item, BaseModel):
            extras = getattr(item, "model_extra", None) or {}
            for key, extra_value in extras.items():
                extra_path = f"{path}.{key}" if path else str(key)
                found.append(extra_path)
                # An unknown object is still reported by its parent field;
                # recursively reporting arbitrary payload keys is noise.
            for field_name in type(item).model_fields:
                if not hasattr(item, field_name):
                    continue
                child = getattr(item, field_name)
                child_path = f"{path}.{field_name}" if path else field_name
                walk(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")
        elif isinstance(item, dict):
            # Dicts are used for untyped/raw payloads and are intentionally
            # opaque.  Typed nested dicts have already become BaseModels.
            return

    walk(value, prefix)
    return found


def missing_judgment_fields(
    judgment: JudgmentContract,
    notice_id: Any = None,
) -> list[str]:
    """Return the three fields whose absence makes a judgment unusable."""

    missing: list[str] = []
    if is_blank(notice_id if notice_id is not None else judgment.notice_id):
        missing.append("notice_id")
    if is_blank(judgment.grade):
        missing.append("grade")
    if is_blank(judgment.readiness):
        missing.append("readiness")
    return missing


def artifact_version(value: Any) -> str | None:
    """Extract a supported decisions schema version from a model or mapping."""

    version = getattr(value, "schema_version", None)
    if version is None and isinstance(value, dict):
        version = value.get("schema_version")
    if version in {"bidops.decisions.v1", "bidops.decisions.v2", "bidops.decisions.v3"}:
        return version
    return None


def decision_contract_requirements(schema_version: str) -> dict[str, int]:
    """Return producer-side minimum list sizes for the selected decisions version.

    The importer reports these as warnings instead of raising.  v1 is kept
    intentionally permissive because its historical one-perspective output is
    valid legacy data; v2 is the five-perspective contract described in the
    workflow reference.
    """

    if schema_version == "bidops.decisions.v1":
        return {"perspectives": 1, "counterarguments": 0, "verification_items": 0}
    return {"perspectives": 5, "counterarguments": 1, "verification_items": 0}


# Names used by the plan and by callers that mirror the artifact filenames.
ValidationSetArtifact = ValidationArtifact
ScreeningResultsArtifact = ScreeningArtifact
CollectedNoticesArtifact = CollectionArtifact
CollectedOrderPlansArtifact = OrderPlanArtifact
ReviewFeedbackArtifact = FeedbackArtifact
DecisionJudgment = JudgmentContract

# Public names mirror the filenames and keep callers from depending on the
# internal ``C2`` prefix used by the shared strict base model.
OrderPlanScreeningInput = OrderPlanScreeningInputArtifact
OrderPlanScreeningRanking = OrderPlanScreeningRankingArtifact
OrderPlanScreeningDecisions = OrderPlanScreeningDecisionsArtifact
OrderPlanScreeningFailures = OrderPlanScreeningFailuresArtifact
OrderPlanScreeningTelemetry = OrderPlanScreeningTelemetryArtifact
OrderPlanScreeningResult = OrderPlanScreeningResultArtifact
OrderPlanScreeningFeedback = OrderPlanScreeningFeedbackArtifact
OrderPlanScreeningPolicy = OrderPlanScreeningPolicyArtifact
