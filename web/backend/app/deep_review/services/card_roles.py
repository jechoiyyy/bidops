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
  unit (``origin="code"``; model rows ``origin="model"``);
* role contract v2 (결정 C16, policy v10): the role payload numbers each unit's
  allowed evidence ``E1``..``En`` (``card_role_evidence_index``) and the model
  cites ids only.  ``validate_verdict_role_v2`` maps the ids back to the frozen
  triples, so the stored role result keeps the v1 shape every consumer reads.
  A finding citing an unknown id or another unit's id is isolated -- kept as
  ``unknown`` with the fixed notice ``ROLE_ISOLATED_REASON`` and no evidence
  (the model's reason is not used; nothing is rewritten into another claim);
  such a caution is dropped; both are recorded in ``isolated_items``.  More
  than 25% isolated findings of the role's units is ``card_role_invalid``;
  coverage, order, role name and assessments beyond the compare stay fatal.
  Any role isolation caps the verdict below "진행 가능" like ``rejected_units``;
* 결정 C19 (policy v10): a role caution naming a unit outside the role is
  dropped too (``role_caution_foreign_unit``; cautions never count toward the
  25% limit, which is about findings).  A synthesis caution or next action whose
  unit is in no role result or whose evidence is outside that unit's role
  evidence is left out of the final row and recorded in its ``isolated_items``
  (``validate_practitioner_verdict_isolated``); verdict, reason, blocking ids,
  code actions and caps are unchanged, an invented owner stays fatal, and a
  dropped item is never rewritten or remapped;
* 결정 C20 (policy v11): role contract v3 names units by the payload's short refs
  ``U1``.. (``card_role_unit_refs``, role extract order) and keeps the v2 evidence
  ids; ``validate_verdict_role_v3`` maps every ref back (an explicit pointer, never
  a guess) and then applies the unchanged v2 rules, so the stored row is the v10
  one.  A finding ref list that is not exactly ``U1``..``Un`` is fatal; a caution
  with a ref outside the role is dropped as ``role_caution_foreign_unit`` with the
  ref it named.  Synthesis contract v3 cites ``unit_ref``/``evidence_ids`` of the
  payload's ``unit_catalog`` (``card_synthesis_unit_index``);
  ``synthesis_v1_from_v3`` resolves them to unit ids and triples, drops an item
  with an unknown ref (``synthesis_unit_outside_roles``) or an id outside that
  unit (``synthesis_evidence_outside_unit``) and records it; assembly receives
  those records as ``pre_isolated``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from pydantic import ValidationError

from ..contracts import (
    PRACTITIONER_VERDICT_SCHEMA,
    PRACTITIONER_VERDICT_V2_SCHEMA,
    PRACTITIONER_VERDICT_V3_SCHEMA,
    SchemaValidationError,
    VERDICT_ROLE_SCHEMA,
    VERDICT_ROLE_V2_SCHEMA,
    VERDICT_ROLE_V3_SCHEMA,
    validate_payload,
)
from ..schemas.card_analysis import (
    MISSING_SECTION_ACTION_PREFIX,
    ROLE_CAUTION_FOREIGN_UNIT_RULE,
    ROLE_ISOLATED_REASON,
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
    CardSynthesisIsolation,
    CardVerdictCaution,
    CardVerdictConflict,
    CardVerdictRoleInput,
    CardVerdictRoleResult,
    VerdictRole,
)
from .card_analysis import (
    CARD_ROLE_INVALID,
    CARD_SYNTHESIS_INVALID,
    CardAnalysisValidationError,
    rejected_units_exceed_limit,
)
from .company_analysis_input import card_role_evidence_index, card_role_unit_refs, card_synthesis_unit_index


#: 결정 C16: rule codes of an isolated role finding/caution (``CardRoleIsolation``).
ROLE_EVIDENCE_UNKNOWN_RULE: Final[str] = "role_evidence_unknown"
ROLE_EVIDENCE_FOREIGN_RULE: Final[str] = "role_evidence_foreign_unit"
#: 결정 C19: rule codes of a dropped synthesis caution/next action (``CardSynthesisIsolation``).
SYNTHESIS_UNIT_OUTSIDE_ROLES_RULE: Final[str] = "synthesis_unit_outside_roles"
SYNTHESIS_EVIDENCE_OUTSIDE_UNIT_RULE: Final[str] = "synthesis_evidence_outside_unit"

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


def _isolated_finding_count(result: CardVerdictRoleResult) -> int:
    return sum(1 for row in result.isolated_items or [] if row.kind == "finding")


def validate_isolated_verdict_role(
    payload: CardVerdictRoleResult | Mapping[str, Any],
    *,
    role_input: CardVerdictRoleInput | Mapping[str, Any],
) -> CardVerdictRoleResult:
    """결정 C16: a stored policy v10 role result (mapped v1 shape + ``isolated_items``).

    The result without ``isolated_items`` must pass the unchanged v1
    ``validate_verdict_role`` (coverage, order, compare bounds, exact per-unit
    evidence); the DTO ties every isolated finding to an ``unknown`` finding with
    the fixed notice and no evidence; isolated findings stay within 25% of the
    role's units.  Used for the synthesis re-check and a synthesis-only resume.
    """

    try:
        result = payload if isinstance(payload, CardVerdictRoleResult) else CardVerdictRoleResult.model_validate(payload)
        frozen = role_input if isinstance(role_input, CardVerdictRoleInput) else CardVerdictRoleInput.model_validate(role_input)
        if result.isolated_items is None:
            raise _role_invalid()
        validate_verdict_role(result.model_copy(update={"isolated_items": None}).model_dump(mode="json"),
                              role_input=frozen)
        if rejected_units_exceed_limit(_isolated_finding_count(result), len(frozen.extract.items)):
            raise _role_invalid()
        return result
    except CardAnalysisValidationError:
        raise
    except (TypeError, ValueError, ValidationError, SchemaValidationError, KeyError):
        raise _role_invalid() from None


def validate_verdict_role_v2(
    payload: Mapping[str, Any],
    *,
    role_input: CardVerdictRoleInput | Mapping[str, Any],
) -> CardVerdictRoleResult:
    """결정 C16: a ``bidops.verdict-role.v2`` answer (evidence ids) as the stored role result.

    Fatal (``card_role_invalid``) as in v1: the v2 output schema, the role name,
    findings not exactly one per role unit in input order, an assessment other
    than the compare ``fit_status`` or ``unknown``, more than 25% isolated
    findings (cautions never count).  Per item: an id that is not in the
    payload's ``card_role_evidence_index`` (``role_evidence_unknown``) or
    belongs to another unit (``role_evidence_foreign_unit``) isolates that
    finding (``unknown``, ``ROLE_ISOLATED_REASON``, no evidence) or drops that
    caution; 결정 C19: a caution naming a unit outside the role is dropped with
    the single code ``role_caution_foreign_unit`` (its ids are not resolved);
    each is recorded as ``{kind, unit_id, rule_codes}``.  Valid ids are mapped
    to their frozen triples in the cited order; nothing else is changed.
    """

    try:
        validate_payload(payload, VERDICT_ROLE_V2_SCHEMA)
        frozen = role_input if isinstance(role_input, CardVerdictRoleInput) else CardVerdictRoleInput.model_validate(role_input)
        if payload["role"] != frozen.role:
            raise _role_invalid()
        expected_ids = [row.unit_id for row in frozen.extract.items]
        if [row["unit_id"] for row in payload["unit_findings"]] != expected_ids:
            raise _role_invalid()
        if [row.unit_id for row in frozen.compare.items] != expected_ids:
            raise _role_invalid()
        if any(row.type not in ROLE_REQUIREMENT_TYPES[frozen.role] for row in frozen.extract.items):
            raise _role_invalid()
        compare_fit = {row.unit_id: row.fit_status for row in frozen.compare.items}
        index = {row["evidence_id"]: row for row in card_role_evidence_index(frozen.extract.model_dump(mode="json"))}

        def resolve(unit_id: str, evidence_ids: Sequence[str]) -> tuple[list[dict[str, str]], list[str]]:
            refs: list[dict[str, str]] = []
            codes: list[str] = []
            for evidence_id in evidence_ids:
                row = index.get(evidence_id)
                if row is not None and row["unit_id"] == unit_id:
                    refs.append({key: row[key] for key in ("source_sha256", "block_key", "quote")})
                    continue
                code = ROLE_EVIDENCE_UNKNOWN_RULE if row is None else ROLE_EVIDENCE_FOREIGN_RULE
                if code not in codes:
                    codes.append(code)
            return refs, codes

        findings: list[dict[str, Any]] = []
        cautions: list[dict[str, Any]] = []
        isolated: list[dict[str, Any]] = []
        for row in payload["unit_findings"]:
            if row["assessment"] not in {compare_fit[row["unit_id"]], "unknown"}:
                raise _role_invalid()
            refs, codes = resolve(row["unit_id"], row["evidence_ids"])
            if codes:
                findings.append({"unit_id": row["unit_id"], "assessment": "unknown", "reason": ROLE_ISOLATED_REASON,
                                 "evidence_refs": []})
                isolated.append({"kind": "finding", "unit_id": row["unit_id"], "rule_codes": codes})
            else:
                findings.append({"unit_id": row["unit_id"], "assessment": row["assessment"], "reason": row["reason"],
                                 "evidence_refs": refs})
        for row in payload["cautions"]:
            if row["unit_id"] not in compare_fit:
                # 결정 C19: a caution naming a unit outside the role is dropped and recorded
                # (not a finding, so it never counts toward the 25% limit).
                isolated.append({"kind": "caution", "unit_id": row["unit_id"],
                                 "rule_codes": [ROLE_CAUTION_FOREIGN_UNIT_RULE]})
                continue
            refs, codes = resolve(row["unit_id"], row["evidence_ids"])
            if codes:
                isolated.append({"kind": "caution", "unit_id": row["unit_id"], "rule_codes": codes})
            else:
                cautions.append({"unit_id": row["unit_id"], "text": row["text"], "evidence_refs": refs})
        result = CardVerdictRoleResult.model_validate({
            "schema_version": "bidops.verdict-role.v1", "role": frozen.role, "unit_findings": findings,
            "cautions": cautions, "evidence_refs": [], "isolated_items": isolated,
        })
        return validate_isolated_verdict_role(result, role_input=frozen)
    except CardAnalysisValidationError:
        raise
    except (TypeError, ValueError, ValidationError, SchemaValidationError, KeyError):
        raise _role_invalid() from None


def validate_verdict_role_v3(
    payload: Mapping[str, Any],
    *,
    role_input: CardVerdictRoleInput | Mapping[str, Any],
) -> CardVerdictRoleResult:
    """결정 C20: a ``bidops.verdict-role.v3`` answer (unit refs + evidence ids) as the stored role result.

    The refs are the role payload's ``card_role_unit_refs`` (``U1``..``Un`` in role
    extract order).  Fatal (``card_role_invalid``): the v3 output schema (a unit id
    or a cut unit id is not a ref), and finding refs that are not exactly
    ``U1``..``Un`` in order -- an unknown, missing, duplicate or reordered ref.  Each
    ref is then replaced by its unit id and the unchanged ``validate_verdict_role_v2``
    decides (role name, compare bounds, evidence ids, C16 finding/caution isolation,
    the 25% finding limit, C19).  A caution whose ref is not a unit of the role keeps
    the ref it named as its ``unit_id``, so v2 drops it as ``role_caution_foreign_unit``
    -- recorded with that ref, never guessed to a unit.  The stored row is exactly
    the v10 shape.
    """

    try:
        validate_payload(payload, VERDICT_ROLE_V3_SCHEMA)
        frozen = role_input if isinstance(role_input, CardVerdictRoleInput) else CardVerdictRoleInput.model_validate(role_input)
        unit_by_ref = {row["unit_ref"]: row["unit_id"] for row in card_role_unit_refs(frozen.extract.model_dump(mode="json"))}
        if [row["unit_ref"] for row in payload["unit_findings"]] != list(unit_by_ref):
            raise _role_invalid()
        resolved = {
            "schema_version": "bidops.verdict-role.v2",
            "role": payload["role"],
            "unit_findings": [
                {"unit_id": unit_by_ref[row["unit_ref"]], "assessment": row["assessment"], "reason": row["reason"],
                 "evidence_ids": list(row["evidence_ids"])}
                for row in payload["unit_findings"]
            ],
            "cautions": [
                {"unit_id": unit_by_ref.get(row["unit_ref"], row["unit_ref"]), "text": row["text"],
                 "evidence_ids": list(row["evidence_ids"])}
                for row in payload["cautions"]
            ],
        }
        return validate_verdict_role_v2(resolved, role_input=frozen)
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
    (only ``card-sections-v2``/``-v3``/``-v4`` reach synthesis with them, 결정 B23·B30·C15); any
    entry makes "진행 가능" ``card_synthesis_invalid``.  ``rejected_units`` (결정 B51)
    must be exactly the extract's isolated unit ids; any entry makes "진행 가능"
    ``card_synthesis_invalid`` too.

    ``allowed_owners`` must come from names explicitly present in the frozen
    model input; actor/audit names are not owner evidence, so the empty
    default rejects every non-null owner.
    """

    result, _isolated = _checked_practitioner_verdict(
        payload, synthesis_input=synthesis_input, extract=extract, compare=compare, allowed_owners=allowed_owners,
        missing_sections=missing_sections, rejected_units=rejected_units, isolate=False,
    )
    return result


def validate_practitioner_verdict_isolated(
    payload: Mapping[str, Any],
    *,
    synthesis_input: CardSynthesisInput | Mapping[str, Any],
    extract: CardRequirementExtract | Mapping[str, Any],
    compare: CardRequirementCompare | Mapping[str, Any],
    allowed_owners: Sequence[str] = (),
    missing_sections: Sequence[str] = (),
    rejected_units: Sequence[str] = (),
) -> tuple[CardPractitionerVerdict, list[CardSynthesisIsolation]]:
    """결정 C19 (policy v10): ``validate_practitioner_verdict`` with per-item isolation of cautions/next actions.

    A caution or next action whose unit is in no role result
    (``synthesis_unit_outside_roles``) or that cites an evidence triple outside
    that unit's role evidence (``synthesis_evidence_outside_unit``, e.g. a
    shortened quote) is left out of the returned verdict and recorded as
    ``{kind, unit_id, rule_codes}`` -- never rewritten or remapped.  Everything
    else is unchanged and fatal (``card_synthesis_invalid``): an owner outside
    ``allowed_owners`` (even on an item that is dropped), blocking ids, the
    mandatory-gap rule on the kept cautions, the rejected-units contract, and
    "진행 가능" while anything is unresolved -- the dropped items count as
    unresolved, so dropping never makes "진행 가능" pass.  Verdict, reason and
    blocking ids are returned as answered.
    """

    return _checked_practitioner_verdict(
        payload, synthesis_input=synthesis_input, extract=extract, compare=compare, allowed_owners=allowed_owners,
        missing_sections=missing_sections, rejected_units=rejected_units, isolate=True,
    )


def _checked_practitioner_verdict(
    payload: Mapping[str, Any],
    *,
    synthesis_input: CardSynthesisInput | Mapping[str, Any],
    extract: CardRequirementExtract | Mapping[str, Any],
    compare: CardRequirementCompare | Mapping[str, Any],
    allowed_owners: Sequence[str],
    missing_sections: Sequence[str],
    rejected_units: Sequence[str],
    isolate: bool,
    pre_isolated: Sequence[CardSynthesisIsolation] = (),
) -> tuple[CardPractitionerVerdict, list[CardSynthesisIsolation]]:
    """Shared synthesis check; ``pre_isolated`` (결정 C20) = items already dropped while resolving v3 refs.

    Those records lead the isolation list and count as unresolved answer items
    (so "진행 가능" stays rejected); they require ``isolate``.
    """

    try:
        if pre_isolated and not isolate:
            raise _synthesis_invalid()
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
            if role_result.isolated_items is None:
                validate_verdict_role(role_result.model_dump(mode="json"),
                                      role_input=expected_role_inputs[role_result.role])
            else:
                # 결정 C16: a policy v10 role row (mapped ids + isolation list).
                validate_isolated_verdict_role(role_result, role_input=expected_role_inputs[role_result.role])
        unit_ids = {row.unit_id for row in parsed_extract.items}
        role_unit_ids = {finding.unit_id for role in frozen_roles.roles for finding in role.unit_findings}
        if role_unit_ids != unit_ids:
            raise _synthesis_invalid()
        evidence_by_unit = _role_evidence_by_unit(frozen_roles)

        def item_codes(unit_id: str, refs: Sequence[Any]) -> list[str]:
            if unit_id not in role_unit_ids:
                return [SYNTHESIS_UNIT_OUTSIDE_ROLES_RULE]
            if any(_evidence_key(evidence) not in evidence_by_unit.get(unit_id, set()) for evidence in refs):
                return [SYNTHESIS_EVIDENCE_OUTSIDE_UNIT_RULE]
            return []

        isolated: list[CardSynthesisIsolation] = [
            row if isinstance(row, CardSynthesisIsolation) else CardSynthesisIsolation.model_validate(row)
            for row in pre_isolated
        ]
        kept_cautions = []
        for caution in result.cautions:
            codes = item_codes(caution.unit_id, caution.evidence_refs)
            if not codes:
                kept_cautions.append(caution)
            elif isolate:
                # 결정 C19: dropped as answered (never rewritten), recorded with codes only.
                isolated.append(CardSynthesisIsolation(kind="caution", unit_id=caution.unit_id, rule_codes=codes))
            else:
                raise _synthesis_invalid()
        owner_allowlist = set(allowed_owners)
        kept_actions = []
        for action in result.next_actions:
            # an invented owner stays fatal, also on an action that would be dropped (결정 C19)
            if action.owner is not None and action.owner not in owner_allowlist:
                raise _synthesis_invalid()
            codes = item_codes(action.unit_id, action.evidence_refs)
            if not codes:
                kept_actions.append(action)
            elif isolate:
                isolated.append(CardSynthesisIsolation(kind="next_action", unit_id=action.unit_id, rule_codes=codes))
            else:
                raise _synthesis_invalid()
        mandatory_gaps = _mandatory_gap_ids(parsed_extract, parsed_compare)
        if not set(result.blocking_condition_ids) <= set(mandatory_gaps):
            raise _synthesis_invalid()
        caution_ids = {row.unit_id for row in kept_cautions}
        if any(unit_id not in result.blocking_condition_ids and unit_id not in caution_ids for unit_id in mandatory_gaps):
            raise _synthesis_invalid()
        unresolved = (
            any(row.fit_status != "met" for row in parsed_compare.items)
            or any(finding.assessment != "met" for role in frozen_roles.roles for finding in role.unit_findings)
            or any(role.cautions for role in frozen_roles.roles)
            # the answer as given: a dropped item (결정 C19) is still unresolved
            or bool(result.cautions)
            or bool(result.next_actions)
            # 결정 C20: so is an item dropped before this check (unresolved v3 ref/id)
            or bool(isolated)
        )
        # 결정 C16: any isolated role item caps the verdict exactly like a rejected unit.
        role_isolated = any(role.isolated_items for role in frozen_roles.roles)
        if result.verdict == "진행 가능" and (
            mandatory_gaps or unresolved or missing_sections or rejected_units or role_isolated
        ):
            raise _synthesis_invalid()
        if not isolated:
            return result, isolated
        return result.model_copy(update={"cautions": kept_cautions, "next_actions": kept_actions}), isolated
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


def synthesis_v1_from_v3(
    payload: Mapping[str, Any],
    *,
    synthesis_input: CardSynthesisInput | Mapping[str, Any],
    extract: CardRequirementExtract | Mapping[str, Any],
    compare: CardRequirementCompare | Mapping[str, Any],
    allowed_owners: Sequence[str] = (),
) -> tuple[dict[str, Any], list[CardSynthesisIsolation]]:
    """결정 C20: the v1 synthesis object of a ``bidops.practitioner-verdict.v3`` answer and its dropped items.

    Refs and ids are resolved against ``card_synthesis_unit_index`` of the same
    role rows the payload's ``unit_catalog`` was built from.  A caution or next
    action whose ``unit_ref`` is not in the catalog is dropped as
    ``synthesis_unit_outside_roles`` (recorded with the ref it named); one citing
    an id that is unknown or listed under another unit is dropped as
    ``synthesis_evidence_outside_unit`` (recorded with its unit id).  Nothing is
    remapped or rewritten.  An owner outside ``allowed_owners`` is fatal even on a
    dropped item.  ``blocking_condition_ids`` are the mandatory ``gap`` units as in
    ``synthesis_v1_from_v2``; verdict and reason are copied unchanged.  The
    v3 output schema failing is ``card_synthesis_invalid`` (the runner turns it
    into the single schema repair first).
    """

    try:
        validate_payload(payload, PRACTITIONER_VERDICT_V3_SCHEMA)
        parsed_extract, parsed_compare = _parsed_extract_compare(extract, compare)
        frozen_roles = (
            synthesis_input if isinstance(synthesis_input, CardSynthesisInput)
            else CardSynthesisInput.model_validate(synthesis_input)
        )
        units, index = card_synthesis_unit_index([role.model_dump(mode="json") for role in frozen_roles.roles])
        unit_by_ref = {row["unit_ref"]: row["unit_id"] for row in units}
        evidence_by_id = {row["evidence_id"]: row for row in index}
        isolated: list[CardSynthesisIsolation] = []

        def resolve(kind: str, row: Mapping[str, Any]) -> tuple[str, list[dict[str, str]]] | None:
            unit_id = unit_by_ref.get(row["unit_ref"])
            if unit_id is None:
                isolated.append(CardSynthesisIsolation(kind=kind, unit_id=row["unit_ref"],
                                                       rule_codes=[SYNTHESIS_UNIT_OUTSIDE_ROLES_RULE]))
                return None
            refs: list[dict[str, str]] = []
            for evidence_id in row["evidence_ids"]:
                entry = evidence_by_id.get(evidence_id)
                if entry is None or entry["unit_id"] != unit_id:
                    isolated.append(CardSynthesisIsolation(kind=kind, unit_id=unit_id,
                                                           rule_codes=[SYNTHESIS_EVIDENCE_OUTSIDE_UNIT_RULE]))
                    return None
                refs.append({key: entry[key] for key in ("source_sha256", "block_key", "quote")})
            return unit_id, refs

        cautions: list[dict[str, Any]] = []
        for row in payload["cautions"]:
            resolved = resolve("caution", row)
            if resolved is not None:
                cautions.append({"unit_id": resolved[0], "text": row["text"], "evidence_refs": resolved[1]})
        owner_allowlist = set(allowed_owners)
        actions: list[dict[str, Any]] = []
        for row in payload["next_actions"]:
            if row["owner"] is not None and row["owner"] not in owner_allowlist:
                raise _synthesis_invalid()
            resolved = resolve("next_action", row)
            if resolved is not None:
                actions.append({"unit_id": resolved[0], "owner": row["owner"], "action": row["action"],
                                "evidence_refs": resolved[1]})
        return {
            "schema_version": "bidops.practitioner-verdict.v1",
            "verdict": payload["verdict"], "reason": payload["reason"],
            "cautions": cautions, "next_actions": actions,
            "blocking_condition_ids": _mandatory_gap_ids(parsed_extract, parsed_compare),
        }, isolated
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
    isolate_items: bool = False,
    pre_isolated: Sequence[CardSynthesisIsolation] = (),
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

    결정 C19: ``isolate_items`` (policy v10) validates with
    ``validate_practitioner_verdict_isolated``: the dropped cautions/next actions
    never reach the row and are recorded in ``isolated_items`` (``[]`` when
    none); without it the key is absent (v1-v9 stored shape unchanged).  Pass
    the synthesis answer as given -- an already filtered verdict has nothing
    left to record.

    결정 C20: ``pre_isolated`` are the records of v3 items ``synthesis_v1_from_v3``
    dropped (unknown ref / id outside the unit); they lead ``isolated_items`` and
    need ``isolate_items``.
    """

    try:
        frozen_roles = (
            synthesis_input if isinstance(synthesis_input, CardSynthesisInput)
            else CardSynthesisInput.model_validate(synthesis_input)
        )
        parsed_extract, parsed_compare = _parsed_extract_compare(extract, compare)
        payload = synthesis.model_dump(mode="json") if isinstance(synthesis, CardPractitionerVerdict) else synthesis
        verdict, isolated = _checked_practitioner_verdict(
            payload, synthesis_input=frozen_roles, extract=parsed_extract, compare=parsed_compare,
            allowed_owners=allowed_owners, missing_sections=missing_sections, rejected_units=rejected_units,
            isolate=isolate_items, pre_isolated=pre_isolated,
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
            isolated_items=[row.model_copy(deep=True) for row in isolated] if isolate_items else None,
        )
    except CardAnalysisValidationError as error:
        if error.code != CARD_SYNTHESIS_INVALID:
            raise _synthesis_invalid() from None
        raise
    except (TypeError, ValueError, ValidationError, SchemaValidationError, KeyError):
        raise _synthesis_invalid() from None


__all__ = [
    "CHECKLIST_MEMBERS",
    "ROLE_CAUTION_FOREIGN_UNIT_RULE",
    "ROLE_EVIDENCE_FOREIGN_RULE",
    "ROLE_EVIDENCE_UNKNOWN_RULE",
    "ROLE_ISOLATED_REASON",
    "ROLE_REQUIREMENT_TYPES",
    "SYNTHESIS_EVIDENCE_OUTSIDE_UNIT_RULE",
    "SYNTHESIS_UNIT_OUTSIDE_ROLES_RULE",
    "VERDICT_ROLES",
    "assemble_practitioner_verdict",
    "build_synthesis_input",
    "build_verdict_role_inputs",
    "code_next_actions",
    "synthesis_v1_from_v2",
    "synthesis_v1_from_v3",
    "cited_constraint_refs",
    "unit_evidence_keys",
    "validate_isolated_verdict_role",
    "validate_practitioner_verdict",
    "validate_practitioner_verdict_isolated",
    "validate_verdict_role",
    "validate_verdict_role_v2",
    "validate_verdict_role_v3",
]
