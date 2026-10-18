"""RL-03 role and synthesis stages: closed inputs, output validation, code-owned assembly.

HP-03 rules (spec "단계 wire 계약" 역할·종합) with RL names:

* each role gets only its requirement types and must return every unit of
  its input exactly once; evidence references must be the unit's own frozen
  extract evidence or (결정 B53) the unit's own constraint
  ``(locator.source_sha256, locator.block_key, quote)`` -- both were verified
  verbatim against the same unit block at extract (``unit_evidence_keys``);
* a role may not move a unit away from the deterministic compare: its
  assessment equals the compare ``fit_status`` or is ``unknown`` (an unknown
  never becomes met or gap; disagreements between roles stay as conflicts);
* synthesis gets only the three validated role results; owners are never
  invented (``owner`` must be null unless an allowlisted name is supplied);
  a mandatory gap is a blocking condition or a caution, and "진행 가능" with a
  mandatory gap or any unresolved item is rejected; so is "진행 가능" when the
  frozen input has ``missing_sections`` (결정 B23: the highest allowed verdict
  is then "조건부 진행"; the answer is rejected, never rewritten); 결정 B51: the
  same cap holds while extract items were isolated (``rejected_units``) --
  rejected units are in the compare (``unknown``/``extract_rejected``) but in
  no role input (their model type is not used), and the matrix lists them as
  ``unknown`` rows with their rule codes;
* checklist, matrix and conflicts are assembled by code from the frozen
  compare and role rows; the verdict is never a Go/No-Go decision;
* synthesis contract v2 (결정 B55, policy v9): the model supplies only verdict,
  reason, cautions and role-unit next actions.  ``synthesis_v1_from_v2`` adds
  ``blocking_condition_ids`` = the mandatory ``gap`` units (the rule the
  validator already enforces) and the unchanged validator decides; assembly
  appends one code "사람 확인" action per missing section and per rejected
  unit (``origin="code"``; model rows ``origin="model"``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from pydantic import ValidationError

from ..contracts import (
    PRACTITIONER_VERDICT_SCHEMA,
    PRACTITIONER_VERDICT_V2_SCHEMA,
    SchemaValidationError,
    VERDICT_ROLE_SCHEMA,
    validate_payload,
)
from ..schemas.card_analysis import (
    MISSING_SECTION_ACTION_PREFIX,
    CardNextAction,
    CardAssembledPractitionerVerdict,
    CardChecklistItem,
    CardMatrixRoleFinding,
    CardPractitionerVerdict,
    CardRequirementCompare,
    CardRequirementCompareItem,
    CardRequirementExtract,
    CardRequirementMatrixItem,
    CardSynthesisInput,
    CardVerdictCaution,
    CardVerdictConflict,
    CardVerdictRoleInput,
    CardVerdictRoleResult,
    VerdictRole,
)
from .card_analysis import CARD_ROLE_INVALID, CARD_SYNTHESIS_INVALID, CardAnalysisValidationError


VERDICT_ROLES: Final[tuple[VerdictRole, ...]] = ("eligibility_economics", "technical_fit", "operations_risk")
ROLE_REQUIREMENT_TYPES: Final[dict[str, frozenset[str]]] = {
    "eligibility_economics": frozenset({"자격", "실적", "인력", "계약", "평가"}),
    "technical_fit": frozenset({"기술", "기능", "성능SLA", "보안"}),
    "operations_risk": frozenset({"인력", "성능SLA", "보안", "운영", "계약"}),
}


def _role_invalid() -> CardAnalysisValidationError:
    return CardAnalysisValidationError(CARD_ROLE_INVALID)


def _synthesis_invalid() -> CardAnalysisValidationError:
    return CardAnalysisValidationError(CARD_SYNTHESIS_INVALID)


def _evidence_key(evidence: Any) -> tuple[str, str, str]:
    return (evidence.source_sha256, evidence.block_key, evidence.quote)


def _constraint_key(constraint: Any) -> tuple[str, str, str]:
    return (constraint.locator.source_sha256, constraint.locator.block_key, constraint.quote)


def unit_evidence_keys(item: Any) -> set[tuple[str, str, str]]:
    """결정 B53: the evidence a role/synthesis may cite for one extract item.

    The item's ``evidence`` triples plus its own constraint triples
    ``(locator.source_sha256, locator.block_key, quote)``.  Both kinds were
    checked verbatim against the same unit block by the extract validator, so
    the set stays per unit and exact (another unit's triple never qualifies).
    """

    return {_evidence_key(row) for row in item.evidence} | {_constraint_key(row) for row in item.constraints}


def cited_constraint_refs(item: Any, refs: Sequence[Any]) -> list[Any]:
    """결정 B53: role-cited refs of ``item`` that are its constraint triples (not already its evidence)."""

    evidence = {_evidence_key(row) for row in item.evidence}
    constraints = {_constraint_key(row) for row in item.constraints}
    result: list[Any] = []
    seen: set[tuple[str, str, str]] = set()
    for row in refs:
        key = _evidence_key(row)
        if key in constraints and key not in evidence and key not in seen:
            seen.add(key)
            result.append(row.model_copy(deep=True))
    return result


def _parsed_extract_compare(
    extract: CardRequirementExtract | Mapping[str, Any],
    compare: CardRequirementCompare | Mapping[str, Any],
) -> tuple[CardRequirementExtract, CardRequirementCompare]:
    parsed_extract = (
        extract if isinstance(extract, CardRequirementExtract) else CardRequirementExtract.model_validate(extract)
    )
    parsed_compare = (
        compare if isinstance(compare, CardRequirementCompare) else CardRequirementCompare.model_validate(compare)
    )
    rejected = {row.unit_id for row in parsed_extract.rejected_units}
    compare_ids = [row.unit_id for row in parsed_compare.items]
    if (
        [unit_id for unit_id in compare_ids if unit_id not in rejected] != [row.unit_id for row in parsed_extract.items]
        or set(compare_ids) - {row.unit_id for row in parsed_extract.items} != rejected
        or any(row.unit_id in rejected and row.reason_codes != ["extract_rejected"] for row in parsed_compare.items)
    ):
        raise _role_invalid()
    return parsed_extract, parsed_compare


def build_verdict_role_inputs(
    extract: CardRequirementExtract | Mapping[str, Any],
    compare: CardRequirementCompare | Mapping[str, Any],
) -> dict[str, CardVerdictRoleInput]:
    """The three closed role inputs (type allowlists); frozen compare rows are copied, never changed."""

    try:
        parsed_extract, parsed_compare = _parsed_extract_compare(extract, compare)
        compare_by_id = {row.unit_id: row for row in parsed_compare.items}
        result: dict[str, CardVerdictRoleInput] = {}
        for role in VERDICT_ROLES:
            role_extract = [
                row.model_copy(deep=True) for row in parsed_extract.items if row.type in ROLE_REQUIREMENT_TYPES[role]
            ]
            result[role] = CardVerdictRoleInput(
                role=role,
                extract=CardRequirementExtract(items=role_extract),
                compare=CardRequirementCompare(
                    items=[compare_by_id[row.unit_id].model_copy(deep=True) for row in role_extract],
                ),
            )
        return result
    except CardAnalysisValidationError:
        raise
    except (TypeError, ValueError, ValidationError, KeyError):
        raise _role_invalid() from None


def validate_verdict_role(
    payload: Mapping[str, Any],
    *,
    role_input: CardVerdictRoleInput | Mapping[str, Any],
) -> CardVerdictRoleResult:
    """Exact role coverage, allowed units, compare-bounded assessments and evidence closure."""

    try:
        validate_payload(payload, VERDICT_ROLE_SCHEMA)
        result = CardVerdictRoleResult.model_validate(payload)
        frozen = role_input if isinstance(role_input, CardVerdictRoleInput) else CardVerdictRoleInput.model_validate(role_input)
        if result.role != frozen.role:
            raise _role_invalid()
        expected_ids = [row.unit_id for row in frozen.extract.items]
        if [row.unit_id for row in result.unit_findings] != expected_ids:
            raise _role_invalid()
        if [row.unit_id for row in frozen.compare.items] != expected_ids:
            raise _role_invalid()
        if any(row.type not in ROLE_REQUIREMENT_TYPES[result.role] for row in frozen.extract.items):
            raise _role_invalid()
        compare_fit = {row.unit_id: row.fit_status for row in frozen.compare.items}
        evidence_by_unit = {row.unit_id: unit_evidence_keys(row) for row in frozen.extract.items}
        all_evidence = set().union(*evidence_by_unit.values()) if evidence_by_unit else set()
        if any(_evidence_key(evidence) not in all_evidence for evidence in result.evidence_refs):
            raise _role_invalid()
        for row in result.unit_findings:
            if row.assessment not in {compare_fit[row.unit_id], "unknown"}:
                raise _role_invalid()
            if any(_evidence_key(evidence) not in evidence_by_unit[row.unit_id] for evidence in row.evidence_refs):
                raise _role_invalid()
        for caution in result.cautions:
            if caution.unit_id not in evidence_by_unit or any(
                _evidence_key(evidence) not in evidence_by_unit[caution.unit_id] for evidence in caution.evidence_refs
            ):
                raise _role_invalid()
        return result
    except CardAnalysisValidationError:
        raise
    except (TypeError, ValueError, ValidationError, SchemaValidationError, KeyError):
        raise _role_invalid() from None


def build_synthesis_input(
    roles: Mapping[str, CardVerdictRoleResult | Mapping[str, Any]]
    | Sequence[CardVerdictRoleResult | Mapping[str, Any]],
) -> CardSynthesisInput:
    """Exactly the three validated role results in canonical order."""

    try:
        if isinstance(roles, Mapping):
            if set(roles) != set(VERDICT_ROLES):
                raise _synthesis_invalid()
            values = [roles[role] for role in VERDICT_ROLES]
        else:
            values = list(roles)
        parsed = [
            value if isinstance(value, CardVerdictRoleResult) else CardVerdictRoleResult.model_validate(value)
            for value in values
        ]
        return CardSynthesisInput(roles=[row.model_copy(deep=True) for row in parsed])
    except CardAnalysisValidationError:
        raise
    except (TypeError, ValueError, ValidationError, KeyError):
        raise _synthesis_invalid() from None


def _role_evidence_by_unit(synthesis_input: CardSynthesisInput) -> dict[str, set[tuple[str, str, str]]]:
    evidence_by_unit: dict[str, set[tuple[str, str, str]]] = {}
    for role in synthesis_input.roles:
        global_evidence = {_evidence_key(row) for row in role.evidence_refs}
        for finding in role.unit_findings:
            evidence_by_unit.setdefault(finding.unit_id, set()).update(global_evidence)
            evidence_by_unit[finding.unit_id].update(_evidence_key(row) for row in finding.evidence_refs)
        for caution in role.cautions:
            evidence_by_unit.setdefault(caution.unit_id, set()).update(
                _evidence_key(row) for row in caution.evidence_refs
            )
    return evidence_by_unit


def _mandatory_gap_ids(extract: CardRequirementExtract, compare: CardRequirementCompare) -> list[str]:
    comparisons = {row.unit_id: row for row in compare.items}
    return [
        row.unit_id for row in extract.items
        if row.mandatory is True and comparisons[row.unit_id].fit_status == "gap"
    ]


def validate_practitioner_verdict(
    payload: Mapping[str, Any],
    *,
    synthesis_input: CardSynthesisInput | Mapping[str, Any],
    extract: CardRequirementExtract | Mapping[str, Any],
    compare: CardRequirementCompare | Mapping[str, Any],
    allowed_owners: Sequence[str] = (),
    missing_sections: Sequence[str] = (),
    rejected_units: Sequence[str] = (),
) -> CardPractitionerVerdict:
    """Synthesis references, invented-owner refusal and the unconditional-proceed safety gate.

    ``missing_sections`` are the frozen input's unfound source sections
    (only ``card-sections-v2``/``-v3`` reach synthesis with them, 결정 B23·B30); any
    entry makes "진행 가능" ``card_synthesis_invalid``.  ``rejected_units`` (결정 B51)
    must be exactly the extract's isolated unit ids; any entry makes "진행 가능"
    ``card_synthesis_invalid`` too.

    ``allowed_owners`` must come from names explicitly present in the frozen
    model input; actor/audit names are not owner evidence, so the empty
    default rejects every non-null owner.
    """

    try:
        validate_payload(payload, PRACTITIONER_VERDICT_SCHEMA)
        result = CardPractitionerVerdict.model_validate(payload)
        frozen_roles = (
            synthesis_input if isinstance(synthesis_input, CardSynthesisInput)
            else CardSynthesisInput.model_validate(synthesis_input)
        )
        parsed_extract, parsed_compare = _parsed_extract_compare(extract, compare)
        if sorted(rejected_units) != sorted(row.unit_id for row in parsed_extract.rejected_units) or (
            len(set(rejected_units)) != len(list(rejected_units))
        ):
            raise _synthesis_invalid()
        expected_role_inputs = build_verdict_role_inputs(parsed_extract, parsed_compare)
        for role_result in frozen_roles.roles:
            validate_verdict_role(role_result.model_dump(mode="json"), role_input=expected_role_inputs[role_result.role])
        unit_ids = {row.unit_id for row in parsed_extract.items}
        role_unit_ids = {finding.unit_id for role in frozen_roles.roles for finding in role.unit_findings}
        if role_unit_ids != unit_ids:
            raise _synthesis_invalid()
        evidence_by_unit = _role_evidence_by_unit(frozen_roles)
        for caution in result.cautions:
            if caution.unit_id not in role_unit_ids or any(
                _evidence_key(evidence) not in evidence_by_unit.get(caution.unit_id, set())
                for evidence in caution.evidence_refs
            ):
                raise _synthesis_invalid()
        owner_allowlist = set(allowed_owners)
        for action in result.next_actions:
            if action.unit_id not in role_unit_ids:
                raise _synthesis_invalid()
            if action.owner is not None and action.owner not in owner_allowlist:
                raise _synthesis_invalid()
            if any(
                _evidence_key(evidence) not in evidence_by_unit.get(action.unit_id, set())
                for evidence in action.evidence_refs
            ):
                raise _synthesis_invalid()
        mandatory_gaps = _mandatory_gap_ids(parsed_extract, parsed_compare)
        if not set(result.blocking_condition_ids) <= set(mandatory_gaps):
            raise _synthesis_invalid()
        caution_ids = {row.unit_id for row in result.cautions}
        if any(unit_id not in result.blocking_condition_ids and unit_id not in caution_ids for unit_id in mandatory_gaps):
            raise _synthesis_invalid()
        unresolved = (
            any(row.fit_status != "met" for row in parsed_compare.items)
            or any(finding.assessment != "met" for role in frozen_roles.roles for finding in role.unit_findings)
            or any(role.cautions for role in frozen_roles.roles)
            or bool(result.cautions)
            or bool(result.next_actions)
        )
        if result.verdict == "진행 가능" and (mandatory_gaps or unresolved or missing_sections or rejected_units):
            raise _synthesis_invalid()
        return result
    except CardAnalysisValidationError as error:
        if error.code != CARD_SYNTHESIS_INVALID:
            raise _synthesis_invalid() from None
        raise
    except (TypeError, ValueError, ValidationError, SchemaValidationError, KeyError):
        raise _synthesis_invalid() from None


def _aggregate_fit(rows: Sequence[CardRequirementCompareItem]) -> str:
    if any(row.fit_status == "gap" for row in rows):
        return "gap"
    if not rows or any(row.fit_status == "unknown" for row in rows):
        return "unknown"
    return "met"


def _unique_evidence(rows: Sequence[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = _evidence_key(row)
        if key not in seen:
            seen.add(key)
            result.append(row.model_copy(deep=True))
    return result


#: HP-04 checklist mapping (5 keys); RL qualifications are ``자격`` units.
CHECKLIST_MEMBERS: Final[tuple[tuple[str, Any], ...]] = (
    ("qualification_track_record", lambda row: row.type in {"자격", "실적", "평가"}),
    ("staffing_onsite", lambda row: row.type == "인력"),
    ("amount_period", lambda row: any(
        constraint.kind in {"amount", "duration", "date", "percentage"} for constraint in row.constraints
    )),
    ("technology", lambda row: row.type in {"기술", "기능"}),
    ("operations_sla_security", lambda row: row.type in {"성능SLA", "보안", "운영", "계약"}),
)


#: 결정 B55: Korean section names of the code "사람 확인" actions (business-rules wording).
SECTION_NAMES: Final[dict[str, str]] = {
    "overview": "사업개요", "schedule": "추진일정", "budget": "사업예산",
    "eligibility": "입찰참가자격", "evaluation": "평가기준", "contract": "계약조건",
}
MISSING_SECTION_ACTION = "원문에서 '{name}' 영역을 찾지 못했습니다. 이 영역의 조건을 원문에서 사람이 확인하세요."
REJECTED_UNIT_ACTION = "원문 근거 검증에 실패한 요구사항입니다. 원문에서 사람이 확인하세요(자동으로 고치지 않음)."


def synthesis_v1_from_v2(
    payload: Mapping[str, Any],
    *,
    extract: CardRequirementExtract | Mapping[str, Any],
    compare: CardRequirementCompare | Mapping[str, Any],
) -> dict[str, Any]:
    """결정 B55: the v1 synthesis object of a ``bidops.practitioner-verdict.v2`` answer.

    The answer must match the v2 output schema (``card_synthesis_invalid``
    otherwise -- the client already rejects it as ``schema_invalid``, which gets
    the single schema repair).  Every model field is copied unchanged;
    ``blocking_condition_ids`` is the mandatory ``gap`` units of the compare, in
    extract order -- exactly what ``validate_practitioner_verdict`` requires of
    a v1 answer.  Nothing is corrected: a next action or caution naming a
    non-role unit still fails validation (not schema-expressible: the allowed
    unit ids differ per attempt).
    """

    try:
        validate_payload(payload, PRACTITIONER_VERDICT_V2_SCHEMA)
        parsed_extract, parsed_compare = _parsed_extract_compare(extract, compare)
        return {
            "schema_version": "bidops.practitioner-verdict.v1",
            **{key: payload[key] for key in ("verdict", "reason", "cautions", "next_actions")},
            "blocking_condition_ids": _mandatory_gap_ids(parsed_extract, parsed_compare),
        }
    except CardAnalysisValidationError as error:
        if error.code != CARD_SYNTHESIS_INVALID:
            raise _synthesis_invalid() from None
        raise
    except (TypeError, ValueError, ValidationError, SchemaValidationError, KeyError):
        raise _synthesis_invalid() from None


def code_next_actions(missing_sections: Sequence[str], rejected_units: Sequence[str]) -> list[CardNextAction]:
    """결정 B55: the deterministic "사람 확인" rows (missing sections, then rejected units)."""

    rows = [
        CardNextAction(unit_id=MISSING_SECTION_ACTION_PREFIX + kind, owner=None,
                       action=MISSING_SECTION_ACTION.format(name=SECTION_NAMES.get(kind, kind)),
                       evidence_refs=[], origin="code")
        for kind in missing_sections
    ]
    rows += [
        CardNextAction(unit_id=unit_id, owner=None, action=REJECTED_UNIT_ACTION, evidence_refs=[], origin="code")
        for unit_id in rejected_units
    ]
    return rows


def assemble_practitioner_verdict(
    synthesis: CardPractitionerVerdict | Mapping[str, Any],
    *,
    synthesis_input: CardSynthesisInput | Mapping[str, Any],
    extract: CardRequirementExtract | Mapping[str, Any],
    compare: CardRequirementCompare | Mapping[str, Any],
    allowed_owners: Sequence[str] = (),
    missing_sections: Sequence[str] = (),
    rejected_units: Sequence[str] = (),
    record_rejected_units: bool = False,
    code_actions: bool = False,
) -> CardAssembledPractitionerVerdict:
    """Code-owned checklist, matrix and role conflicts around the validated synthesis.

    ``missing_sections`` is copied from the frozen input into the final row
    (결정 B23).  No unit of those sections was selected, so their requirements
    are unknown ("확인 필요") -- the record keeps that visible; the checklist and
    matrix stay computed from the selected units only.

    결정 B51: a rejected unit is a matrix row with ``type`` null, ``unknown``, no
    role findings and its rule codes; the checklist uses accepted items only
    (a rejected item's type is not used).  ``record_rejected_units`` (policy v7)
    copies ``{unit_id, rule_codes}`` into the final row.

    결정 B55: ``code_actions`` (synthesis contract v2) marks the model actions
    ``origin="model"`` and appends ``code_next_actions`` (``origin="code"``).
    """

    try:
        frozen_roles = (
            synthesis_input if isinstance(synthesis_input, CardSynthesisInput)
            else CardSynthesisInput.model_validate(synthesis_input)
        )
        parsed_extract, parsed_compare = _parsed_extract_compare(extract, compare)
        payload = synthesis.model_dump(mode="json") if isinstance(synthesis, CardPractitionerVerdict) else synthesis
        verdict = validate_practitioner_verdict(
            payload, synthesis_input=frozen_roles, extract=parsed_extract, compare=parsed_compare,
            allowed_owners=allowed_owners, missing_sections=missing_sections, rejected_units=rejected_units,
        )
        compare_by_id = {row.unit_id: row for row in parsed_compare.items}
        rejected_by_id = {row.unit_id: row for row in parsed_extract.rejected_units}
        extract_by_id = {row.unit_id: row for row in parsed_extract.items}
        findings_by_unit: dict[str, list[tuple[str, Any]]] = {row.unit_id: [] for row in parsed_extract.items}
        for role in frozen_roles.roles:
            for finding in role.unit_findings:
                findings_by_unit[finding.unit_id].append((role.role, finding))
        matrix = []
        conflicts = []
        for compared in parsed_compare.items:
            if compared.unit_id in rejected_by_id:
                matrix.append(CardRequirementMatrixItem(
                    unit_id=compared.unit_id, type=None, fit_status="unknown", role_findings=[],
                    rejected_rule_codes=list(rejected_by_id[compared.unit_id].rule_codes),
                ))
                continue
            item = extract_by_id[compared.unit_id]
            role_findings = findings_by_unit[item.unit_id]
            matrix.append(CardRequirementMatrixItem(
                unit_id=item.unit_id, type=item.type, fit_status=compare_by_id[item.unit_id].fit_status,
                role_findings=[
                    CardMatrixRoleFinding(
                        role=role, assessment=finding.assessment, reason=finding.reason,
                        evidence_refs=[row.model_copy(deep=True) for row in finding.evidence_refs],
                    )
                    for role, finding in role_findings
                ],
            ))
            if len({finding.assessment for _role, finding in role_findings}) > 1:
                conflicts.append(CardVerdictConflict(
                    unit_id=item.unit_id,
                    roles=[role for role, _finding in role_findings],
                    assessments=[finding.assessment for _role, finding in role_findings],
                ))
        role_refs_by_unit: dict[str, list[Any]] = {}
        for role in frozen_roles.roles:
            for finding in role.unit_findings:
                role_refs_by_unit.setdefault(finding.unit_id, []).extend(finding.evidence_refs)
            for caution in role.cautions:
                role_refs_by_unit.setdefault(caution.unit_id, []).extend(caution.evidence_refs)
        checklist = []
        for key, predicate in CHECKLIST_MEMBERS:
            members = [row for row in parsed_extract.items if predicate(row)]
            checklist.append(CardChecklistItem(
                key=key,
                status=_aggregate_fit([compare_by_id[row.unit_id] for row in members]),
                # 결정 B53: plus the constraint quotes the roles cited for these units
                # (identical to the item evidence when no constraint quote is cited).
                evidence_refs=_unique_evidence([
                    value for row in members
                    for value in [*row.evidence, *cited_constraint_refs(row, role_refs_by_unit.get(row.unit_id, []))]
                ]),
            ))
        cautions: list[CardVerdictCaution] = []
        caution_keys: set[tuple[str, str, tuple[tuple[str, str, str], ...]]] = set()
        for caution in [*(row for role in frozen_roles.roles for row in role.cautions), *verdict.cautions]:
            key = (caution.unit_id, caution.text, tuple(_evidence_key(row) for row in caution.evidence_refs))
            if key not in caution_keys:
                caution_keys.add(key)
                cautions.append(caution.model_copy(deep=True))
        return CardAssembledPractitionerVerdict(
            verdict=verdict.verdict, reason=verdict.reason,
            blocking_condition_ids=list(verdict.blocking_condition_ids),
            checklist=checklist, matrix=matrix, cautions=cautions, conflicts=conflicts,
            next_actions=(
                [*(row.model_copy(update={"origin": "model"}, deep=True) for row in verdict.next_actions),
                 *code_next_actions(missing_sections, [row.unit_id for row in parsed_extract.rejected_units])]
                if code_actions else [row.model_copy(deep=True) for row in verdict.next_actions]
            ),
            missing_sections=list(missing_sections),
            rejected_units=(
                [row.model_copy(deep=True) for row in parsed_extract.rejected_units] if record_rejected_units else None
            ),
        )
    except CardAnalysisValidationError as error:
        if error.code != CARD_SYNTHESIS_INVALID:
            raise _synthesis_invalid() from None
        raise
    except (TypeError, ValueError, ValidationError, SchemaValidationError, KeyError):
        raise _synthesis_invalid() from None


__all__ = [
    "CHECKLIST_MEMBERS",
    "ROLE_REQUIREMENT_TYPES",
    "VERDICT_ROLES",
    "assemble_practitioner_verdict",
    "build_synthesis_input",
    "build_verdict_role_inputs",
    "code_next_actions",
    "synthesis_v1_from_v2",
    "cited_constraint_refs",
    "unit_evidence_keys",
    "validate_practitioner_verdict",
    "validate_verdict_role",
]
