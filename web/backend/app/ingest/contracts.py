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
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field


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
