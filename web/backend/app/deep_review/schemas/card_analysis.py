"""Strict DTOs of the RL-03 card-v1 frozen source selection (``card_analysis``).

RL-03 spec "루트랩 재명세 차이": the HP-03 unit/selector/batch wire is adopted
unchanged except that the nested input is ``bidops.card-analysis-input.v1``
with a ``company_binding`` (graph/profile/ontology identity of the active
binding) instead of the HP basis/scenario/registration hashes, and the
selector version is ``card-sections-v1``, (결정 B23, policy
``analysis-policy-luna-rl-v2``) ``card-sections-v2`` or (결정 B30, policy
``analysis-policy-luna-rl-v3``) ``card-sections-v3`` or (결정 C15, policy
``analysis-policy-luna-rl-v10``) ``card-sections-v4``, whose split segment parts
carry ``segment:<sha>:<segment UUID>#p<n>`` ids.  The company facts are the
top-level v2 retrieval rows, never a copy inside ``card_analysis``.

The stage wire DTOs (extract/compare/role/synthesis, STEP-005) follow the
HP-03 "단계 wire 계약" with RL names; compare adds the ``proposed_fact`` reason.
결정 C16 (policy v10): the stored role result keeps the v1 shape after code maps the
v2 evidence ids back to triples, plus ``isolated_items`` (``CardRoleIsolation``).
"""

from __future__ import annotations

from datetime import date
import math
import re
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    ConfigDict, Field, SerializerFunctionWrapHandler, StrictBool, StrictFloat, StrictInt, StrictStr,
    model_serializer, model_validator,
)

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
    # 결정 B51: the unit's extract item was rejected (evidence-class rule); no
    # model content of it is compared -- always ``unknown`` with no constraint facts.
    "extract_rejected",
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
#: 결정 C15: v3 + a segment unit above ``batch_max_chars`` split at block
#: boundaries into consecutive parts (``#p<n>`` unit ids).
CARD_SELECTOR_VERSION_V4 = "card-sections-v4"
CardSelectorVersion = Literal["card-sections-v1", "card-sections-v2", "card-sections-v3", "card-sections-v4"]
#: 결정 C15: ``<segment unit id>#p<n>`` of one v4 part (n from 1, no leading zero).
_SEGMENT_PART_SUFFIX = re.compile(r"#p([1-9][0-9]*)\Z")


def segment_unit_part(unit_id: str) -> tuple[str, int | None]:
    """``(segment unit id, part number)`` of a v4 part id; ``(unit_id, None)`` when unsplit (결정 C15)."""

    match = _SEGMENT_PART_SUFFIX.search(unit_id)
    if match is None:
        return unit_id, None
    return unit_id[:match.start()], int(match.group(1))


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
            segment_id, _part = segment_unit_part(self.unit_id)
            try:
                UUID(segment_id[len(prefix):])
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


def _check_segment_parts(units: list[CardAnalysisUnit], selector_version: str) -> None:
    """결정 C15: part ids only under ``card-sections-v4``, as complete ``p1..pk`` (k >= 2) runs.

    The parts of one segment appear in unit order, share every parent
    attribute and never sit beside the unsplit segment id.
    """

    parts: dict[str, list[tuple[int, tuple[Any, ...]]]] = {}
    unsplit: set[str] = set()
    for unit in units:
        if unit.kind != "segment":
            continue
        segment_id, part = segment_unit_part(unit.unit_id)
        if part is None:
            unsplit.add(segment_id)
            continue
        if selector_version != CARD_SELECTOR_VERSION_V4:
            raise ValueError("segment_part_selector_invalid")
        pages = None if unit.page_range is None else (unit.page_range.first, unit.page_range.last)
        parent = (unit.document_version_id, unit.structure_id, unit.manifest_id, unit.ordinal,
                  tuple(unit.section_kinds), pages, unit.mapping_status)
        parts.setdefault(segment_id, []).append((part, parent))
    for segment_id, rows in parts.items():
        if (
            segment_id in unsplit
            or [part for part, _parent in rows] != list(range(1, len(rows) + 1))
            or len(rows) < 2
            or len({parent for _part, parent in rows}) != 1
        ):
            raise ValueError("segment_part_invalid")


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
        _check_segment_parts(self.units, self.selector.version)
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
        _check_segment_parts(self.units, self.selector.version)
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


#: 결정 B51: a rule code of an isolated (rejected) extract item.
RuleCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")]


class CardRejectedUnit(CardStrictModel):
    """결정 B51: one unit whose extract item failed evidence-class rules (codes only, no model text)."""

    unit_id: NonEmpty
    rule_codes: list[RuleCode] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_codes(self) -> "CardRejectedUnit":
        if len(self.rule_codes) != len(set(self.rule_codes)):
            raise ValueError("rejected_rule_code_duplicate")
        return self


class CardRequirementExtract(CardStrictModel):
    schema_version: Literal["bidops.requirement-extract.v1"] = "bidops.requirement-extract.v1"
    items: list[CardRequirementExtractItem]
    #: 결정 B51 (stored extract rows only, policy v7): units isolated from the
    #: batch -- their model items are kept only in the raw response and are not
    #: in ``items``.  Rows stored before the key existed read as ``[]``.
    rejected_units: list[CardRejectedUnit] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_units(self) -> "CardRequirementExtract":
        unit_ids = [row.unit_id for row in self.items]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("extract_unit_duplicate")
        rejected = [row.unit_id for row in self.rejected_units]
        if len(rejected) != len(set(rejected)) or set(rejected) & set(unit_ids):
            raise ValueError("extract_rejected_unit_invalid")
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


#: 결정 C16: rule codes of an isolated role item (policy v10, role contract v2).
#: ``role_evidence_unknown`` = an evidence id that is not in the role payload;
#: ``role_evidence_foreign_unit`` = the id of another unit's evidence.
RoleIsolationRule = Literal["role_evidence_unknown", "role_evidence_foreign_unit"]
#: 결정 C16: the fixed BidOps notice stored as the reason of an isolated finding.  The
#: model's own reason is not used (it stays only in the raw response); the notice is
#: not a claim about the requirement.
ROLE_ISOLATED_REASON = "원문 근거 번호 검증에 실패한 판단입니다. 원문에서 사람이 확인하세요(자동으로 고치지 않음)."


class CardRoleIsolation(CardStrictModel):
    """결정 C16: one role finding (kept as ``unknown``) or caution (dropped) whose evidence ids failed.

    Codes only -- never model text.  ``unit_id`` is the finding's/caution's unit.
    """

    kind: Literal["finding", "caution"]
    unit_id: NonEmpty
    rule_codes: list[RoleIsolationRule] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_codes(self) -> "CardRoleIsolation":
        if len(self.rule_codes) != len(set(self.rule_codes)):
            raise ValueError("role_isolation_rule_duplicate")
        return self


class CardVerdictRoleResult(CardStrictModel):
    schema_version: Literal["bidops.verdict-role.v1"] = "bidops.verdict-role.v1"
    role: VerdictRole
    unit_findings: list[CardVerdictRoleFinding]
    cautions: list[CardVerdictCaution]
    evidence_refs: list[CardEvidence]
    #: 결정 C16 additive (role stage rows of policy v10, possibly empty): the isolated
    #: findings/cautions.  ``None`` (every earlier policy) is omitted from the stored
    #: row, so v1-v9 rows keep their exact shape and result SHA.
    isolated_items: list[CardRoleIsolation] | None = None

    @model_validator(mode="after")
    def _unique_references(self) -> "CardVerdictRoleResult":
        unit_ids = [row.unit_id for row in self.unit_findings]
        evidence = [(row.source_sha256, row.block_key, row.quote) for row in self.evidence_refs]
        if len(unit_ids) != len(set(unit_ids)) or len(evidence) != len(set(evidence)):
            raise ValueError("role_reference_duplicate")
        if self.isolated_items is not None:
            # 결정 C16: an isolated finding is ``unknown`` with the fixed notice and no
            # evidence; each finding is isolated at most once; every record names a role unit.
            findings = {row.unit_id: row for row in self.unit_findings}
            isolated = [row.unit_id for row in self.isolated_items if row.kind == "finding"]
            if len(isolated) != len(set(isolated)) or any(row.unit_id not in findings for row in self.isolated_items):
                raise ValueError("role_isolation_invalid")
            if any(
                findings[unit_id].assessment != "unknown" or findings[unit_id].evidence_refs
                for unit_id in isolated
            ) or self.evidence_refs:
                raise ValueError("role_isolation_invalid")
            # the fixed notice marks exactly the recorded findings
            if {row.unit_id for row in self.unit_findings if row.reason == ROLE_ISOLATED_REASON} != set(isolated):
                raise ValueError("role_isolation_invalid")
        return self

    @model_serializer(mode="wrap")
    def _omit_absent_isolation(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if data.get("isolated_items") is None:
            data.pop("isolated_items", None)
        return data


class CardSynthesisInput(CardStrictModel):
    """The synthesis boundary: exactly the three role results in canonical order."""

    roles: list[CardVerdictRoleResult] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def _exact_roles(self) -> "CardSynthesisInput":
        expected = ["eligibility_economics", "technical_fit", "operations_risk"]
        if [row.role for row in self.roles] != expected:
            raise ValueError("synthesis_roles_invalid")
        return self


#: 결정 B55: who wrote a stored next action.  ``model`` = the synthesis answer,
#: ``code`` = a deterministic BidOps "사람 확인" row (missing section / rejected
#: unit).  ``None`` on model wire answers and on rows stored before policy v9.
NextActionOrigin = Literal["model", "code"]
#: 결정 B55: ``unit_id`` prefix of a code "사람 확인" row for a missing source section.
MISSING_SECTION_ACTION_PREFIX = "missing_section:"


class CardNextAction(CardStrictModel):
    unit_id: NonEmpty
    owner: NonEmpty | None
    action: NonEmpty
    evidence_refs: list[CardEvidence]
    origin: NextActionOrigin | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_origin(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # 결정 B55: rows without an origin (model wire, policies before v9) keep
        # their exact pre-v9 stored shape (and result SHA): no ``origin`` key.
        data = handler(self)
        if data.get("origin") is None:
            data.pop("origin", None)
        return data


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
    #: ``null`` only for a rejected unit (결정 B51): its model type is not used.
    type: RequirementType | None
    fit_status: FitStatus
    role_findings: list[CardMatrixRoleFinding]
    #: 결정 B51 additive: the rule codes of a rejected unit (``unknown``, no role
    #: findings); ``null`` for every other row and on rows stored before the key.
    rejected_rule_codes: list[RuleCode] | None = None

    @model_validator(mode="after")
    def _rejected_row(self) -> "CardRequirementMatrixItem":
        if self.rejected_rule_codes is not None:
            if (not self.rejected_rule_codes or self.type is not None or self.fit_status != "unknown"
                    or self.role_findings):
                raise ValueError("matrix_rejected_row_invalid")
        elif self.type is None:
            raise ValueError("matrix_type_missing")
        return self


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
    #: 결정 B51 additive: units isolated at extract (copied by code from the
    #: extract rows); ``null`` only on rows stored before the key existed.  A
    #: non-empty list caps the verdict below "진행 가능" like ``missing_sections``.
    rejected_units: list[CardRejectedUnit] | None = None

    @model_validator(mode="after")
    def _missing_sections_cap(self) -> "CardAssembledPractitionerVerdict":
        if self.missing_sections is not None and len(self.missing_sections) != len(set(self.missing_sections)):
            raise ValueError("missing_section_duplicate")
        if self.missing_sections and self.verdict == "진행 가능":
            raise ValueError("missing_sections_verdict_cap")
        if self.rejected_units is not None:
            rejected = [row.unit_id for row in self.rejected_units]
            if len(rejected) != len(set(rejected)):
                raise ValueError("rejected_unit_duplicate")
            matrix_rejected = {row.unit_id for row in self.matrix if row.rejected_rule_codes is not None}
            if matrix_rejected != set(rejected):
                raise ValueError("rejected_units_matrix_mismatch")
            if rejected and self.verdict == "진행 가능":
                raise ValueError("rejected_units_verdict_cap")
        elif any(row.rejected_rule_codes is not None for row in self.matrix):
            raise ValueError("rejected_units_matrix_mismatch")
        # 결정 B55: either no row carries an origin (rows before policy v9) or every
        # row does, and the code rows are exactly one per missing section and per
        # rejected unit (in that order, after the model rows) with no owner/evidence.
        origins = [row.origin for row in self.next_actions]
        if any(origin is not None for origin in origins):
            if any(origin is None for origin in origins):
                raise ValueError("next_action_origin_mixed")
            model_rows = [row for row in self.next_actions if row.origin == "model"]
            code_rows = [row for row in self.next_actions if row.origin == "code"]
            if self.next_actions != [*model_rows, *code_rows]:
                raise ValueError("next_action_code_order")
            expected = [MISSING_SECTION_ACTION_PREFIX + kind for kind in self.missing_sections or []]
            expected += [row.unit_id for row in self.rejected_units or []]
            if [row.unit_id for row in code_rows] != expected or any(
                row.owner is not None or row.evidence_refs for row in code_rows
            ):
                raise ValueError("next_action_code_rows_invalid")
            if any(row.unit_id.startswith(MISSING_SECTION_ACTION_PREFIX) for row in model_rows):
                raise ValueError("next_action_model_target_invalid")
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
    "MISSING_SECTION_ACTION_PREFIX",
    "NextActionOrigin",
    "CardPractitionerVerdict",
    "CardRequirementCompare",
    "CardRequirementCompareItem",
    "CardRequirementConstraint",
    "CardRequirementExtract",
    "CardRequirementExtractItem",
    "CardRequirementMatrixItem",
    "CardRejectedUnit",
    "CardRoleIsolation",
    "ROLE_ISOLATED_REASON",
    "RoleIsolationRule",
    "RuleCode",
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
    "CARD_SELECTOR_VERSION_V4",
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
    "segment_unit_part",
]
