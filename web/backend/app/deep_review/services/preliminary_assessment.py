"""Pure parsing, risk detection and server-owned preliminary grade calculation.

The model describes relationships and references.  It never emits the Korean
grade label.  This module has no database, transport or live profile access so
the same frozen inputs can be checked again by later consumers.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from ..schemas.prespec_overview_claims import (
    ASSESSMENT_VALIDATOR_VERSION,
    CombinedOverviewAssessmentDraft,
    OverviewAssessmentSemanticResponse,
    OverviewClaimChecks,
    OverviewClaimsDraft,
    PreliminaryAssessmentDraft,
)


GRADES = ("우선 검토", "검토 권장", "관찰 대상", "제외")
_RELATION_GRADE = {
    "direct": "우선 검토",
    "partial": "검토 권장",
    "indirect": "관찰 대상",
}
_RELATION_STRENGTH = {"direct": 3, "partial": 2, "indirect": 1, "unrelated": 0}
_SEMANTIC_TRIGGER_WARNINGS = frozenset({"quantity_relation_ambiguous"})
_NEGATION_MARKERS = ("아니", "않", "없", "제외", "금지", "불가", "제한")
_CONDITION_MARKERS = ("경우", "한하여", "한해", "조건", "다만", "단,", "단 ")


class CombinedDraftError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ParsedCombinedDraft:
    overview: OverviewClaimsDraft | None
    assessment: PreliminaryAssessmentDraft | None
    overview_error: str | None = None
    assessment_error: str | None = None


@dataclass(frozen=True)
class AssessmentDecision:
    status: str
    grade: str | None
    semantic_required: bool
    reason_codes: tuple[str, ...]
    validator_version: str = ASSESSMENT_VALIDATOR_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "grade": self.grade,
            "semantic_required": self.semantic_required,
            "reason_codes": list(self.reason_codes),
            "validator_version": self.validator_version,
        }


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CombinedDraftError("duplicate_json_key")
        result[key] = value
    return result


def _load_top_level(raw: object) -> Mapping[str, Any]:
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
        except CombinedDraftError:
            raise
        except (ValueError, UnicodeError):
            raise CombinedDraftError("json_invalid") from None
    if not isinstance(raw, Mapping):
        raise CombinedDraftError("top_level_invalid")
    if set(raw) != {"schema_version", "overview", "assessment"}:
        raise CombinedDraftError("top_level_contract_invalid")
    if raw.get("schema_version") != "bidops.prespec-overview-assessment-draft.v1":
        raise CombinedDraftError("schema_version_invalid")
    return raw


def parse_combined_draft(raw: object) -> ParsedCombinedDraft:
    """Parse the two child objects independently after the JSON boundary is safe."""

    value = _load_top_level(raw)
    overview = assessment = None
    overview_error = assessment_error = None
    try:
        overview = OverviewClaimsDraft.model_validate(value.get("overview"))
    except ValidationError:
        overview_error = "overview_schema_invalid"
    try:
        assessment = PreliminaryAssessmentDraft.model_validate(value.get("assessment"))
    except ValidationError:
        assessment_error = "assessment_schema_invalid"
    return ParsedCombinedDraft(overview, assessment, overview_error, assessment_error)


def combined_contract_schema() -> dict[str, Any]:
    return CombinedOverviewAssessmentDraft.model_json_schema()


def parse_assessment_semantic(raw: object) -> OverviewAssessmentSemanticResponse:
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
        except CombinedDraftError:
            raise
        except (ValueError, UnicodeError):
            raise CombinedDraftError("semantic_schema_invalid") from None
    try:
        return OverviewAssessmentSemanticResponse.model_validate(raw)
    except ValidationError:
        raise CombinedDraftError("semantic_schema_invalid") from None


def assessment_semantic_triggers(
    assessment: PreliminaryAssessmentDraft,
    checks: OverviewClaimChecks,
) -> tuple[str, ...]:
    """Return stable rule codes that require the optional semantic pass.

    The marker rule does not decide whether a claim is true.  It only notices
    that the verified source and the generated sentence disagree on the
    presence of negation or a condition, which is exactly the ambiguity that
    deterministic substring checks cannot resolve safely.
    """

    triggers: set[str] = set()
    relations = {row.relation for row in assessment.axes}
    if relations == {"unrelated"}:
        triggers.add("exclusion_candidate")
    if assessment.delivery_role == "unclear":
        triggers.add("delivery_role_unclear")
    if assessment.uncertainty_codes:
        triggers.update(f"model_uncertainty:{code}" for code in assessment.uncertainty_codes)
    warning_codes = {
        warning
        for row in checks.checks
        for warning in row.warnings
    } | set(checks.warnings)
    triggers.update(warning_codes.intersection(_SEMANTIC_TRIGGER_WARNINGS))

    for row in checks.checks:
        source = " ".join(item.quote for item in row.deterministic.verified_evidence)
        for code, markers in (
            ("negation_context_mismatch", _NEGATION_MARKERS),
            ("condition_context_mismatch", _CONDITION_MARKERS),
        ):
            source_has = any(marker in source for marker in markers)
            claim_has = any(marker in row.text for marker in markers)
            if source_has != claim_has:
                triggers.add(code)
    return tuple(sorted(triggers))


def assessment_requires_semantic(
    assessment: PreliminaryAssessmentDraft,
    checks: OverviewClaimChecks,
) -> bool:
    return bool(assessment_semantic_triggers(assessment, checks))


def _semantic_passed(
    semantic: OverviewAssessmentSemanticResponse | None,
    *, claim_ids: set[str],
) -> bool:
    if semantic is None:
        return False
    rows = [row for row in semantic.claim_checks if row.claim_id in claim_ids]
    return (
        len(rows) == len(claim_ids)
        and {row.claim_id for row in rows} == claim_ids
        and all(row.status == "supported" for row in rows)
        and all(row.status == "supported" for row in semantic.assessment_checks)
    )


def calculate_assessment(
    assessment: PreliminaryAssessmentDraft,
    checks: OverviewClaimChecks,
    *,
    profile_status: str = "not_configured",
    allowed_company_refs: Sequence[str] = (),
    semantic: OverviewAssessmentSemanticResponse | None = None,
) -> AssessmentDecision:
    """Return a grade only when its frozen references support the calculation."""

    reasons: set[str] = set()
    passed = {
        row.claim_id
        for row in checks.checks
        if row.deterministic.status == "passed"
    }
    main_tasks = {
        row.claim_id
        for row in checks.checks
        if row.section == "main_tasks" and row.deterministic.status == "passed"
    }
    primary = set(assessment.primary_task_claim_ids)
    if not primary or not primary.issubset(main_tasks):
        reasons.add("primary_task_evidence_invalid")

    allowed_company = set(allowed_company_refs)
    referenced_claims: set[str] = set(primary)
    for axis in assessment.axes:
        refs = set(axis.claim_refs)
        referenced_claims.update(refs)
        if axis.relation != "unknown" and (not refs or not refs.issubset(passed)):
            reasons.add("assessment_claim_reference_invalid")
        if axis.relation in {"direct", "partial", "indirect"} and not refs.intersection(primary):
            reasons.add("assessment_primary_task_reference_missing")
        company_refs = set(axis.company_refs)
        if company_refs and (
            profile_status != "ready" or not company_refs.issubset(allowed_company)
        ):
            reasons.add("company_reference_invalid")

    if profile_status == "invalid":
        reasons.add("profile_binding_invalid")
    if assessment.delivery_role == "unclear":
        reasons.add("delivery_role_unclear")
    if any(row.relation == "unknown" for row in assessment.axes):
        reasons.add("assessment_relation_unknown")

    semantic_required = assessment_requires_semantic(assessment, checks)
    relations = [row.relation for row in assessment.axes]
    if all(relation == "unrelated" for relation in relations):
        candidate = "제외"
    else:
        known = [relation for relation in relations if relation in _RELATION_STRENGTH]
        candidate = _RELATION_GRADE.get(
            max(known, key=_RELATION_STRENGTH.get) if known else ""
        )
        if candidate is None:
            reasons.add("assessment_relation_unusable")

    if reasons:
        return AssessmentDecision("held", None, semantic_required, tuple(sorted(reasons)))
    if semantic_required and not _semantic_passed(semantic, claim_ids=referenced_claims):
        return AssessmentDecision(
            "held", None, True,
            ("semantic_required" if semantic is None else "semantic_validation_failed",),
        )
    return AssessmentDecision("graded", candidate, semantic_required, ())


__all__ = [
    "AssessmentDecision", "CombinedDraftError", "ParsedCombinedDraft",
    "assessment_requires_semantic", "assessment_semantic_triggers", "calculate_assessment",
    "combined_contract_schema", "parse_combined_draft",
    "parse_assessment_semantic",
]
