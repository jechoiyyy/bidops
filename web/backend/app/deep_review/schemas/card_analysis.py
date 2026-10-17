"""Strict DTOs of the RL-03 card-v1 frozen source selection (``card_analysis``).

RL-03 spec "루트랩 재명세 차이": the HP-03 unit/selector/batch wire is adopted
unchanged except that the nested input is ``bidops.card-analysis-input.v1``
with a ``company_binding`` (graph/profile/ontology identity of the active
binding) instead of the HP basis/scenario/registration hashes, and the
selector version is ``card-sections-v1``, (결정 B23, policy
``analysis-policy-luna-rl-v2``) ``card-sections-v2`` or (결정 B30, policy
``analysis-policy-luna-rl-v3``) ``card-sections-v3``.  The company facts are the
top-level v2 retrieval rows, never a copy inside ``card_analysis``.

The stage wire DTOs (extract/compare/role/synthesis, STEP-005) follow the
HP-03 "단계 wire 계약" with RL names; compare adds the ``proposed_fact`` reason.
"""

from __future__ import annotations

from datetime import date
import math
import re
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from .document_bundles import StrictModel


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmpty = Annotated[str, Field(min_length=1)]
SectionKind = Literal["overview", "schedule", "budget", "eligibility", "evaluation", "contract"]
MappingStatus = Literal["mapped", "partial", "inherited", "unavailable"]
UnitKind = Literal["card", "segment"]
RequirementType = Literal["자격", "실적", "인력", "기술", "기능", "성능SLA", "보안", "운영", "계약", "평가"]
ConstraintKind = Literal["amount", "duration", "count", "date", "percentage", "boolean", "text"]
ConstraintOperator = Literal["eq", "gte", "lte", "unknown"]
ConstraintUnit = Literal["KRW", "person", "month", "day", "year", "percent"]
FitStatus = Literal["met", "gap", "unknown"]
#: HP-03 compare reason enum + RL-03 ``proposed_fact`` (an agent-proposed
#: company value is never evidence; it compares like ``unknown_fact``).
CompareReason = Literal[
    "confirmed_match",
    "confirmed_contradiction",
    "unknown_fact",
    "proposed_fact",
    "partial_path",
    "unmapped",
    "unsupported_comparison",
    "scope_unverified",
    "contract_unaccepted",
    "incomplete_unit",
]
VerdictRole = Literal["eligibility_economics", "technical_fit", "operations_risk"]
PractitionerVerdictValue = Literal["진행 가능", "조건부 진행", "진행 어려움", "판단 불가"]
ChecklistKey = Literal[
    "qualification_track_record",
    "staffing_onsite",
    "amount_period",
    "technology",
    "operations_sla_security",
]

CARD_ANALYSIS_INPUT_SCHEMA_VERSION = "bidops.card-analysis-input.v1"
CARD_SELECTOR_VERSION = "card-sections-v1"
#: 결정 B23: v1 + symbol/PUA bullet headings that carry a section keyword.
CARD_SELECTOR_VERSION_V2 = "card-sections-v2"
#: 결정 B30: v2 + table-of-contents entries without page numbers and
#: title-only segment units are excluded.
CARD_SELECTOR_VERSION_V3 = "card-sections-v3"
CardSelectorVersion = Literal["card-sections-v1", "card-sections-v2", "card-sections-v3"]


class CardStrictModel(StrictModel):
    """Closed model which also validates defaults (no bool-to-int coercion via Strict types)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, validate_default=True)


class CardPageRange(CardStrictModel):
    first: StrictInt = Field(ge=1)
    last: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> "CardPageRange":
        if self.last < self.first:
            raise ValueError("page_range_invalid")
        return self


class CardUnitBlock(CardStrictModel):
    block_key: NonEmpty
    text: str


class CardAnalysisUnit(CardStrictModel):
    unit_id: NonEmpty
    source_sha256: Sha256
    document_version_id: UUID
    structure_id: UUID
    manifest_id: UUID
    kind: UnitKind
    ordinal: StrictInt = Field(ge=0)
    normalized_id: NonEmpty | None
    section_kinds: list[SectionKind]
    blocks: list[CardUnitBlock] = Field(min_length=1)
    page_range: CardPageRange | None
    mapping_status: MappingStatus

    @model_validator(mode="after")
    def _identity_and_blocks(self) -> "CardAnalysisUnit":
        keys = [block.block_key for block in self.blocks]
        if len(keys) != len(set(keys)):
            raise ValueError("unit_block_duplicate")
        if len(self.section_kinds) != len(set(self.section_kinds)):
            raise ValueError("unit_section_duplicate")
        if self.kind == "card":
            if self.normalized_id is None or self.section_kinds:
                raise ValueError("card_unit_invalid")
            expected = f"card:{self.source_sha256}:{self.ordinal}:{self.normalized_id}"
        else:
            if self.normalized_id is not None or not self.section_kinds:
                raise ValueError("segment_unit_invalid")
            prefix = f"segment:{self.source_sha256}:"
            if not self.unit_id.startswith(prefix):
                raise ValueError("segment_unit_id_invalid")
            try:
                UUID(self.unit_id[len(prefix):])
            except ValueError:
                raise ValueError("segment_unit_id_invalid") from None
            expected = self.unit_id
        if self.unit_id != expected:
            raise ValueError("unit_id_invalid")
        if (self.mapping_status == "unavailable") != (self.page_range is None):
            raise ValueError("unit_page_mapping_invalid")
        return self


class CardAnalysisBatch(CardStrictModel):
    batch_index: StrictInt = Field(ge=0)
    unit_ids: list[NonEmpty] = Field(min_length=1, max_length=8)
    source_characters: StrictInt = Field(ge=0, le=12000)

    @model_validator(mode="after")
    def _unique_units(self) -> "CardAnalysisBatch":
        if len(self.unit_ids) != len(set(self.unit_ids)):
            raise ValueError("batch_unit_duplicate")
        return self


class CardSelectorCandidateBlock(CardStrictModel):
    source_sha256: Sha256
    block_key: NonEmpty


class CardSelectorSelectedBlock(CardSelectorCandidateBlock):
    section_kinds: list[SectionKind] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_sections(self) -> "CardSelectorSelectedBlock":
        if len(self.section_kinds) != len(set(self.section_kinds)):
            raise ValueError("selector_section_duplicate")
        return self


class CardSelector(CardStrictModel):
    version: CardSelectorVersion = CARD_SELECTOR_VERSION
    sha256: Sha256
    candidate_blocks: list[CardSelectorCandidateBlock]
    selected_blocks: list[CardSelectorSelectedBlock]

    @model_validator(mode="after")
    def _unique_blocks(self) -> "CardSelector":
        candidates = [(row.source_sha256, row.block_key) for row in self.candidate_blocks]
        selected = [(row.source_sha256, row.block_key) for row in self.selected_blocks]
        if len(candidates) != len(set(candidates)) or len(selected) != len(set(selected)):
            raise ValueError("selector_block_duplicate")
        if not set(selected).issubset(set(candidates)):
            raise ValueError("selector_selected_not_candidate")
        return self


class CardSourceBinding(CardStrictModel):
    """Internal binding of deduplicated source content (outside the wire input).

    The enclosing CompanyAnalysisInput v2 already freezes every document
    version; this records which version supplied the one selected source.
    """

    source_sha256: Sha256
    selected_document_version_id: UUID
    selected_structure_id: UUID
    selected_manifest_id: UUID
    document_version_ids: list[UUID] = Field(min_length=1)

    @model_validator(mode="after")
    def _binding_is_unique(self) -> "CardSourceBinding":
        if len(self.document_version_ids) != len(set(self.document_version_ids)):
            raise ValueError("source_binding_duplicate")
        if self.selected_document_version_id not in self.document_version_ids:
            raise ValueError("source_binding_selected_missing")
        return self


def _check_batch_coverage(units: list[CardAnalysisUnit], batches: list[CardAnalysisBatch],
                          missing_sections: list[str]) -> None:
    unit_ids = [unit.unit_id for unit in units]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("unit_id_duplicate")
    if len(missing_sections) != len(set(missing_sections)):
        raise ValueError("missing_section_duplicate")
    batch_ids: list[str] = []
    for index, batch in enumerate(batches):
        if batch.batch_index != index:
            raise ValueError("batch_index_invalid")
        batch_ids.extend(batch.unit_ids)
    if batch_ids != unit_ids:
        raise ValueError("batch_unit_coverage_invalid")


class CardUnitSelection(CardStrictModel):
    """Pure selection result consumed by input freezing and later stages."""

    units: list[CardAnalysisUnit]
    batches: list[CardAnalysisBatch]
    missing_sections: list[SectionKind]
    selector: CardSelector
    source_bindings: list[CardSourceBinding]

    @model_validator(mode="after")
    def _coverage(self) -> "CardUnitSelection":
        _check_batch_coverage(self.units, self.batches, list(self.missing_sections))
        source_hashes = [binding.source_sha256 for binding in self.source_bindings]
        if len(source_hashes) != len(set(source_hashes)):
            raise ValueError("source_binding_hash_duplicate")
        known = set(source_hashes)
        if any(unit.source_sha256 not in known for unit in self.units):
            raise ValueError("unit_source_binding_missing")
        return self


class CardCompanyBinding(CardStrictModel):
    """Identity of the active company binding the input was frozen from (RL-03)."""

    graph_version_id: UUID
    graph_sha256: Sha256
    profile_version_id: UUID
    profile_sha256: Sha256
    ontology_version: NonEmpty
    ontology_sha256: Sha256


class CardAnalysisInput(CardStrictModel):
    """``bidops.card-analysis-input.v1`` -- the exact nested key set of RL-03."""

    schema_version: Literal["bidops.card-analysis-input.v1"] = CARD_ANALYSIS_INPUT_SCHEMA_VERSION
    company_binding: CardCompanyBinding
    units: list[CardAnalysisUnit]
    batches: list[CardAnalysisBatch]
    missing_sections: list[SectionKind]
    selector: CardSelector

    @model_validator(mode="after")
    def _batch_coverage(self) -> "CardAnalysisInput":
        _check_batch_coverage(self.units, self.batches, list(self.missing_sections))
        return self


class CardBatchPolicy(CardStrictModel):
    """The policy ``card`` packing values that change units/batches (HP-03 ranges)."""

    batch_size: StrictInt = Field(default=8, ge=1, le=8)
    batch_max_chars: StrictInt = Field(default=12000, ge=1, le=12000)
    repair_attempts: StrictInt = Field(default=1, ge=0, le=1)


class CardCallBudget(CardStrictModel):
    batch_count: StrictInt = Field(ge=0)
    normal_calls: StrictInt = Field(ge=4)
    maximum_calls: StrictInt = Field(ge=4)


# Source DTOs mirror the existing structure/card/manifest projections.  They are
# application inputs, not an additional wire schema.
class CardSourceBlock(CardStrictModel):
    block_key: NonEmpty
    parent_block_key: str | None
    type: NonEmpty
    page: StrictInt = Field(ge=1)
    bbox: list[float] | None
    text: str
    confidence: float | None
    attributes: dict[str, Any]


class CardSourceCard(CardStrictModel):
    raw_id: NonEmpty
    normalized_id: NonEmpty
    locator: dict[str, Any]
    title: str | None
    ordinal: StrictInt = Field(ge=1)
    source: Literal["label_value_table"]
    card: dict[str, Any]
    page_range: CardPageRange | None
    mapping_status: MappingStatus


class CardSourceSegment(CardStrictModel):
    segment_id: UUID
    ordinal: StrictInt = Field(ge=1)
    start_locator: dict[str, Any]
    source_block_keys: list[NonEmpty]
    page_range: CardPageRange | None
    mapping_status: MappingStatus


class CardAnalysisSource(CardStrictModel):
    source_sha256: Sha256
    document_version_id: UUID
    structure_id: UUID
    manifest_id: UUID
    blocks: list[CardSourceBlock]
    cards: list[CardSourceCard]
    segments: list[CardSourceSegment]

    @model_validator(mode="after")
    def _source_identity(self) -> "CardAnalysisSource":
        block_keys = [block.block_key for block in self.blocks]
        if len(block_keys) != len(set(block_keys)):
            raise ValueError("source_block_key_duplicate")
        card_ordinals = [card.ordinal for card in self.cards]
        if len(card_ordinals) != len(set(card_ordinals)):
            raise ValueError("source_card_ordinal_duplicate")
        segment_ids = [segment.segment_id for segment in self.segments]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("source_segment_id_duplicate")
        return self


# --- stage wire (HP-03 "단계 wire 계약", RL-03 names) --------------------------------
#
# Every object: listed keys required, extra keys forbidden, no bool for numbers,
# non-empty strings.  The JSON schema files (contracts/) are the transport
# check; these models add the cross-field rules.


class CardEvidence(CardStrictModel):
    source_sha256: Sha256
    block_key: NonEmpty
    quote: NonEmpty


class CardConstraintLocator(CardStrictModel):
    source_sha256: Sha256
    block_key: NonEmpty


ConstraintValue = StrictInt | StrictFloat | StrictBool | StrictStr


class CardRequirementConstraint(CardStrictModel):
    kind: ConstraintKind
    value: ConstraintValue
    unit: ConstraintUnit | None
    operator: ConstraintOperator
    fact_key: NonEmpty | None
    quote: NonEmpty
    locator: CardConstraintLocator

    @model_validator(mode="after")
    def _typed_value_and_unit(self) -> "CardRequirementConstraint":
        value = self.value
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("constraint_value_invalid")
        if self.kind in {"amount", "duration", "count", "percentage"}:
            if not numeric:
                raise ValueError("constraint_value_invalid")
        elif self.kind == "boolean":
            if not isinstance(value, bool):
                raise ValueError("constraint_value_invalid")
        elif self.kind in {"date", "text"}:
            if not isinstance(value, str) or not value:
                raise ValueError("constraint_value_invalid")
            if self.kind == "date":
                if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
                    raise ValueError("constraint_value_invalid")
                try:
                    date.fromisoformat(value)
                except ValueError:
                    raise ValueError("constraint_value_invalid") from None
        valid_units: dict[str, set[str | None]] = {
            "amount": {"KRW"},
            "duration": {"month", "day", "year"},
            "count": {"person", None},
            "percentage": {"percent"},
            "date": {None},
            "boolean": {None},
            "text": {None},
        }
        if self.unit not in valid_units[self.kind]:
            raise ValueError("constraint_unit_invalid")
        if self.operator == "unknown" and self.fact_key is not None:
            raise ValueError("unknown_constraint_fact_key")
        return self


class CardConceptCandidate(CardStrictModel):
    concept_id: NonEmpty | None
    alias_text: NonEmpty


class CardRequirementExtractItem(CardStrictModel):
    unit_id: NonEmpty
    type: RequirementType
    normalized_requirement: NonEmpty
    mandatory: StrictBool | None
    constraints: list[CardRequirementConstraint]
    concept_candidates: list[CardConceptCandidate]
    unknowns: list[NonEmpty]
    evidence: list[CardEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def _no_duplicate_references(self) -> "CardRequirementExtractItem":
        constraints = [
            (row.kind, type(row.value).__name__, str(row.value), row.unit, row.operator, row.fact_key,
             row.quote, row.locator.source_sha256, row.locator.block_key)
            for row in self.constraints
        ]
        concepts = [(row.concept_id, row.alias_text) for row in self.concept_candidates]
        evidence = [(row.source_sha256, row.block_key, row.quote) for row in self.evidence]
        if (
            len(constraints) != len(set(constraints))
            or len(concepts) != len(set(concepts))
            or len(evidence) != len(set(evidence))
        ):
            raise ValueError("extract_reference_duplicate")
        if len(self.unknowns) != len(set(self.unknowns)):
            raise ValueError("extract_unknown_duplicate")
        return self


class CardRequirementExtract(CardStrictModel):
    schema_version: Literal["bidops.requirement-extract.v1"] = "bidops.requirement-extract.v1"
    items: list[CardRequirementExtractItem]

    @model_validator(mode="after")
    def _unique_units(self) -> "CardRequirementExtract":
        unit_ids = [row.unit_id for row in self.items]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("extract_unit_duplicate")
        return self


class CardConstraintResult(CardStrictModel):
    constraint_index: StrictInt = Field(ge=0)
    status: FitStatus
    fact_ids: list[NonEmpty]
    path_ids: list[StrictInt]
    reason_code: CompareReason

    @model_validator(mode="after")
    def _unique_references(self) -> "CardConstraintResult":
        if len(self.fact_ids) != len(set(self.fact_ids)) or len(self.path_ids) != len(set(self.path_ids)):
            raise ValueError("compare_reference_duplicate")
        if any(path_id < 0 for path_id in self.path_ids):
            raise ValueError("compare_path_invalid")
        return self


class CardRequirementCompareItem(CardStrictModel):
    unit_id: NonEmpty
    fit_status: FitStatus
    constraint_results: list[CardConstraintResult]
    evidence_ids: list[UUID]
    reason_codes: list[CompareReason]

    @model_validator(mode="after")
    def _unique_references(self) -> "CardRequirementCompareItem":
        indexes = [row.constraint_index for row in self.constraint_results]
        if indexes != list(range(len(indexes))):
            raise ValueError("compare_constraint_coverage_invalid")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("compare_evidence_duplicate")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("compare_reason_duplicate")
        return self


class CardRequirementCompare(CardStrictModel):
    schema_version: Literal["bidops.requirement-compare.v1"] = "bidops.requirement-compare.v1"
    items: list[CardRequirementCompareItem]

    @model_validator(mode="after")
    def _unique_units(self) -> "CardRequirementCompare":
        unit_ids = [row.unit_id for row in self.items]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("compare_unit_duplicate")
        return self


class CardVerdictRoleInput(CardStrictModel):
    """Deterministic role input assembled from frozen stage results (never edited by a role)."""

    role: VerdictRole
    extract: CardRequirementExtract
    compare: CardRequirementCompare

    @model_validator(mode="after")
    def _matching_units(self) -> "CardVerdictRoleInput":
        if [row.unit_id for row in self.extract.items] != [row.unit_id for row in self.compare.items]:
            raise ValueError("role_input_unit_coverage_invalid")
        return self


class CardVerdictCaution(CardStrictModel):
    unit_id: NonEmpty
    text: NonEmpty
    evidence_refs: list[CardEvidence]


class CardVerdictRoleFinding(CardStrictModel):
    unit_id: NonEmpty
    assessment: FitStatus
    reason: NonEmpty
    evidence_refs: list[CardEvidence]


class CardVerdictRoleResult(CardStrictModel):
    schema_version: Literal["bidops.verdict-role.v1"] = "bidops.verdict-role.v1"
    role: VerdictRole
    unit_findings: list[CardVerdictRoleFinding]
    cautions: list[CardVerdictCaution]
    evidence_refs: list[CardEvidence]

    @model_validator(mode="after")
    def _unique_references(self) -> "CardVerdictRoleResult":
        unit_ids = [row.unit_id for row in self.unit_findings]
        evidence = [(row.source_sha256, row.block_key, row.quote) for row in self.evidence_refs]
        if len(unit_ids) != len(set(unit_ids)) or len(evidence) != len(set(evidence)):
            raise ValueError("role_reference_duplicate")
        return self


class CardSynthesisInput(CardStrictModel):
    """The synthesis boundary: exactly the three role results in canonical order."""

    roles: list[CardVerdictRoleResult] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def _exact_roles(self) -> "CardSynthesisInput":
        expected = ["eligibility_economics", "technical_fit", "operations_risk"]
        if [row.role for row in self.roles] != expected:
            raise ValueError("synthesis_roles_invalid")
        return self


class CardNextAction(CardStrictModel):
    unit_id: NonEmpty
    owner: NonEmpty | None
    action: NonEmpty
    evidence_refs: list[CardEvidence]


class CardPractitionerVerdict(CardStrictModel):
    schema_version: Literal["bidops.practitioner-verdict.v1"] = "bidops.practitioner-verdict.v1"
    verdict: PractitionerVerdictValue
    reason: NonEmpty
    blocking_condition_ids: list[NonEmpty]
    cautions: list[CardVerdictCaution]
    next_actions: list[CardNextAction]

    @model_validator(mode="after")
    def _unique_blocking_conditions(self) -> "CardPractitionerVerdict":
        if len(self.blocking_condition_ids) != len(set(self.blocking_condition_ids)):
            raise ValueError("blocking_condition_duplicate")
        return self


class CardVerdictConflict(CardStrictModel):
    unit_id: NonEmpty
    roles: list[VerdictRole] = Field(min_length=2)
    assessments: list[FitStatus] = Field(min_length=2)

    @model_validator(mode="after")
    def _parallel_values(self) -> "CardVerdictConflict":
        if len(self.roles) != len(self.assessments) or len(self.roles) != len(set(self.roles)):
            raise ValueError("conflict_values_invalid")
        if len(set(self.assessments)) < 2:
            raise ValueError("conflict_assessments_equal")
        return self


class CardChecklistItem(CardStrictModel):
    key: ChecklistKey
    status: FitStatus
    evidence_refs: list[CardEvidence]


class CardMatrixRoleFinding(CardStrictModel):
    role: VerdictRole
    assessment: FitStatus
    reason: NonEmpty
    evidence_refs: list[CardEvidence]


class CardRequirementMatrixItem(CardStrictModel):
    unit_id: NonEmpty
    type: RequirementType
    fit_status: FitStatus
    role_findings: list[CardMatrixRoleFinding]


class CardAssembledPractitionerVerdict(CardStrictModel):
    """Code-owned final projection (``synthesis``/``final`` stage row); the model supplies no derived field.

    ``missing_sections`` (결정 B23, additive): the frozen input's sections the
    selector did not find, copied by code.  ``null`` only on rows stored before
    the key existed.  A non-empty list caps the verdict below "진행 가능".
    """

    verdict: PractitionerVerdictValue
    reason: NonEmpty
    blocking_condition_ids: list[NonEmpty]
    checklist: list[CardChecklistItem]
    matrix: list[CardRequirementMatrixItem]
    cautions: list[CardVerdictCaution]
    conflicts: list[CardVerdictConflict]
    next_actions: list[CardNextAction]
    missing_sections: list[SectionKind] | None = None

    @model_validator(mode="after")
    def _missing_sections_cap(self) -> "CardAssembledPractitionerVerdict":
        if self.missing_sections is not None and len(self.missing_sections) != len(set(self.missing_sections)):
            raise ValueError("missing_section_duplicate")
        if self.missing_sections and self.verdict == "진행 가능":
            raise ValueError("missing_sections_verdict_cap")
        return self


__all__ = [
    "CARD_ANALYSIS_INPUT_SCHEMA_VERSION",
    "ChecklistKey",
    "CompareReason",
    "ConstraintKind",
    "ConstraintOperator",
    "ConstraintUnit",
    "CardAssembledPractitionerVerdict",
    "CardChecklistItem",
    "CardConceptCandidate",
    "CardConstraintLocator",
    "CardConstraintResult",
    "CardEvidence",
    "CardMatrixRoleFinding",
    "CardNextAction",
    "CardPractitionerVerdict",
    "CardRequirementCompare",
    "CardRequirementCompareItem",
    "CardRequirementConstraint",
    "CardRequirementExtract",
    "CardRequirementExtractItem",
    "CardRequirementMatrixItem",
    "CardSynthesisInput",
    "CardVerdictCaution",
    "CardVerdictConflict",
    "CardVerdictRoleFinding",
    "CardVerdictRoleInput",
    "CardVerdictRoleResult",
    "FitStatus",
    "PractitionerVerdictValue",
    "RequirementType",
    "VerdictRole",
    "CARD_SELECTOR_VERSION",
    "CARD_SELECTOR_VERSION_V2",
    "CARD_SELECTOR_VERSION_V3",
    "CardSelectorVersion",
    "CardAnalysisBatch",
    "CardAnalysisInput",
    "CardAnalysisSource",
    "CardAnalysisUnit",
    "CardBatchPolicy",
    "CardCallBudget",
    "CardCompanyBinding",
    "CardPageRange",
    "CardSelector",
    "CardSelectorCandidateBlock",
    "CardSelectorSelectedBlock",
    "CardSourceBinding",
    "CardSourceBlock",
    "CardSourceCard",
    "CardSourceSegment",
    "CardStrictModel",
    "CardUnitBlock",
    "CardUnitSelection",
    "MappingStatus",
    "SectionKind",
    "UnitKind",
]
