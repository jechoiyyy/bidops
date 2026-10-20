"""RL-03 card-v1: extract validation, append-only stage rows and the stage runner.

Ported from the HP-03 stage wire rules (spec "단계 wire 계약") with the RL
names.  The deterministic parts (quote/number/operator/alias validation,
compare, role/synthesis closure) never correct a model answer: a failure is a
safe ``card_*`` code and the attempt goes to people (``failed`` +
``needs_human_review`` availability).  Only a transport-level schema failure
gets the policy's single repair call; evidence or number errors do not.

Policy ``analysis-policy-luna-rl-v4`` (결정 B33, ``stage_schema`` =
``bidops.requirement-extract.v2``): the model answers only the semantic extract
fields (no ``concept_candidates``, no constraint ``operator``) under an output
schema that carries the kind x unit table.  ``assemble_requirement_extract_v2``
derives the two missing fields in code -- the unit's ``card_expected_concepts``
and ``expected_constraint_operator`` (the validator's own operator rule) -- and
the unchanged ``validate_requirement_extract`` then decides.  A structural
failure of the assembled object (pydantic kind x unit/value/duplicates or the
item-per-unit order) is schema-class and gets the same single repair, whose
envelope names only rule codes and item indexes.  Quote, number, concept and
evidence failures stay non-repairable.

Policy ``analysis-policy-luna-rl-v7`` (결정 B51, item isolation): an extract item
that breaks only evidence-class rules (quote not verbatim, number not in the
source, truncated or repeated constraint quote, constraint expression,
``fact_key`` anchor, concept mismatch) is ``rejected`` -- its model content is
not changed and not used; the stored extract row lists ``{unit_id,
rule_codes}`` under ``rejected_units``.  The compare stage gives such a unit
``unknown`` (``extract_rejected``), the synthesis gets the rejected unit ids
and cannot answer "진행 가능".  More than 25% rejected units of the attempt
(cumulative, checked after every batch) still fails the attempt
(``card_extract_invalid``); structural failures keep the single repair.

Policy ``analysis-policy-luna-rl-v9`` (결정 B55): synthesis output contract
``bidops.practitioner-verdict.v2`` (``report_schema``) -- no
``blocking_condition_ids`` (code computes them from mandatory ``gap`` rows),
code "사람 확인" next actions for missing sections and rejected units.  A
synthesis-only resume (``CardResume``) reuses the validated extract/compare/
role rows of a failed attempt with the same frozen content and policy lineage:
every reused row's stage input is recomputed from the new frozen input and must
hash to the stored ``input_sha256``, compare is recomputed, roles are
re-validated; the rows are copied into the new attempt and audited
(``card.stages.reused``), then only synthesis is called.

Policy ``analysis-policy-luna-rl-v10`` (결정 C15) is v9 with selector
``card-sections-v4``: an oversized segment unit arrives as ``#p<n>`` parts.
Every stage treats a part like any unit (opaque ``unit_id``).  v9 -> v10 is not
a resume lineage (the selector differs).  결정 C16 adds to v10: the role stage
answers ``card-role-v2`` (short evidence ids in ``evidence_catalog``, mapped back
and isolated per item by ``card_roles.validate_verdict_role_v2``), and a batch
unit still missing from the answer to the final extract repair is isolated
(``rejected_units`` with ``extract_unit_missing``) instead of failing the
attempt; extra, unknown or reordered ids stay fatal and the 25% limit applies.
결정 C19 (validation only, same v10 file): a role caution naming a unit outside the
role and a synthesis caution/next action outside the role units or their evidence
are dropped and recorded (role row / final row ``isolated_items``) instead of
failing the attempt; a v10 synthesis-only resume follows the same rule.

Policy ``analysis-policy-luna-rl-v11`` (결정 C20) is v10 with role contract v3
(``card-role-v3``: the role payload names units by ``U1``.. refs, the answer cites
refs and the v10 evidence ids; ``card_roles.validate_verdict_role_v3`` maps them
back -- same stored row, same C16/C19 isolation), synthesis contract v3
(``card-synthesis-v3``: the payload's ``unit_catalog`` numbers the role units and
their role evidence; cautions/next actions cite refs and ids only, unresolved ones
are dropped and recorded as in C19) and the text-constraint value rule
(``_text_value_ok``).  v10 -> v11 is not a resume lineage; v11 -> v11 is.

Model I/O happens only in ``run_card_analysis`` through the existing Luna
client with the D2 transfer projections of ``company_analysis_input`` (every
payload passes ``check_card_transfer_payload`` before the call).  With
``BIDOPS_ANALYSIS_PROVIDER=mock`` (reference mode, 결정 B16) the same runner uses
``MockCardAnalysisClient`` instead: no runner or network call, same validators.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from time import monotonic as _monotonic
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...core.company_ontology import OntologyConcept, ValidatedOntology
from ...core.model_binding import canonical_json_bytes
from ...core.model_client import ModelInvocationError
from ..contracts import (
    PRACTITIONER_VERDICT_V2_SCHEMA,
    PRACTITIONER_VERDICT_V3_SCHEMA,
    REQUIREMENT_EXTRACT_SCHEMA,
    REQUIREMENT_EXTRACT_V2_SCHEMA,
    SchemaValidationError,
    validate_payload,
)
from ..schemas.card_analysis import (
    CardAnalysisBatch,
    CardAnalysisInput,
    CardAnalysisUnit,
    CardRequirementConstraint,
    CardRequirementExtract,
    CardRequirementExtractItem,
)
from .company_analysis_input import CARD_COMPARE_FACT_PATHS, CompanyAnalysisError, card_expected_concepts
from .company_knowledge_retrieval import match_concepts


#: Stable failure codes of the card-v1 pipeline (spec "오류 code 접두").
CARD_SOURCE_SELECTION_INCOMPLETE: Final[str] = "card_source_selection_incomplete"
CARD_EXTRACT_INVALID: Final[str] = "card_extract_invalid"
CARD_COMPARE_INVALID: Final[str] = "card_compare_invalid"
CARD_ROLE_INVALID: Final[str] = "card_role_invalid"
CARD_SYNTHESIS_INVALID: Final[str] = "card_synthesis_invalid"
CARD_REVIEW_TIMEOUT: Final[str] = "card_review_timeout"
INPUT_BUDGET_EXCEEDED: Final[str] = "input_budget_exceeded"
#: Existing Luna client code for a prompt over the cap (never truncated).
PROMPT_REJECTED: Final[str] = "prompt_rejected"
#: Spec "인터페이스": the Luna client's 100,000-character prompt cap, checked
#: here too so an oversized stage payload is never sent (no partial send).
PROMPT_CHARACTER_LIMIT: int = 100_000
#: A failed attempt with one of these codes is projected as
#: ``availability=needs_human_review`` (HP-03 "설정·상태·저장"); the attempt
#: status itself stays ``failed``.
NEEDS_HUMAN_REVIEW_CODES: Final[frozenset[str]] = frozenset({
    CARD_SOURCE_SELECTION_INCOMPLETE, CARD_EXTRACT_INVALID, CARD_COMPARE_INVALID,
    CARD_ROLE_INVALID, CARD_SYNTHESIS_INVALID, CARD_REVIEW_TIMEOUT, PROMPT_REJECTED,
})

#: runner/client contracts per stage (spec "인터페이스").
STAGE_CONTRACTS: Final[dict[str, str]] = {
    "extract": "card-extract-v1",
    "role": "card-role-v1",
    "synthesis": "card-synthesis-v1",
}
#: 결정 B33: policy ``stage_schema`` values and the extract contract each selects.
REQUIREMENT_EXTRACT_V1: Final[str] = "bidops.requirement-extract.v1"
REQUIREMENT_EXTRACT_V2: Final[str] = "bidops.requirement-extract.v2"
EXTRACT_CONTRACT_BY_STAGE_SCHEMA: Final[dict[str, str]] = {
    REQUIREMENT_EXTRACT_V1: "card-extract-v1",
    REQUIREMENT_EXTRACT_V2: "card-extract-v2",
}
#: 결정 B55: policy ``report_schema`` values and the synthesis contract each selects.
PRACTITIONER_VERDICT_V1: Final[str] = "bidops.practitioner-verdict.v1"
PRACTITIONER_VERDICT_V2: Final[str] = "bidops.practitioner-verdict.v2"
#: 결정 C20 (policy v11): cautions/next actions cite ``unit_ref``/``evidence_ids`` only.
PRACTITIONER_VERDICT_V3: Final[str] = "bidops.practitioner-verdict.v3"
SYNTHESIS_CONTRACT_BY_REPORT_SCHEMA: Final[dict[str, str]] = {
    PRACTITIONER_VERDICT_V1: "card-synthesis-v1",
    PRACTITIONER_VERDICT_V2: "card-synthesis-v2",
    PRACTITIONER_VERDICT_V3: "card-synthesis-v3",
}
#: 결정 B55: synthesis fields code derives under contract v2 (recorded in audits).
CODE_DERIVED_SYNTHESIS_FIELDS: Final[tuple[str, ...]] = ("blocking_condition_ids", "next_actions.person_check")
#: 결정 B55: resume failure code (the source is not a valid reuse source for this attempt).
RESUME_SOURCE_INVALID: Final[str] = "resume_source_invalid"
#: 결정 B55: frozen-input keys that identify one preview/policy row; everything else must be equal.
RESUME_IDENTITY_KEYS: Final[frozenset[str]] = frozenset({
    "execution_nonce", "target_review_id", "policy_version_id", "policy_sha256",
})
#: 결정 B55: policy keys a resume may differ in (identity, synthesis contract, synthesis instruction).
RESUME_POLICY_FREE_KEYS: Final[frozenset[str]] = frozenset({"policy_identity", "policy_sha256", "report_schema", "stages"})
#: 결정 B51: policies that isolate evidence-class extract failures per item (v10: 결정 C15, v11: C20).
ITEM_ISOLATION_POLICY_IDENTITIES: Final[frozenset[str]] = frozenset({
    "analysis-policy-luna-rl-v7", "analysis-policy-luna-rl-v8", "analysis-policy-luna-rl-v9",
    "analysis-policy-luna-rl-v10", "analysis-policy-luna-rl-v11",
})
#: 결정 C16 (RL-05): policies whose role stage answers ``card-role-v2`` (short evidence
#: ids, role item isolation) and whose extract stage isolates units still missing after
#: the single repair (``extract_unit_missing``).  Every earlier policy is unchanged.
ROLE_CONTRACT_V2: Final[str] = "card-role-v2"
ROLE_CONTRACT_V2_SCHEMA_VERSION: Final[str] = "bidops.verdict-role.v2"
ROLE_CONTRACT_V2_POLICY_IDENTITIES: Final[frozenset[str]] = frozenset({"analysis-policy-luna-rl-v10"})
#: 결정 C20 (RL-05 STEP-009): policies whose role stage answers ``card-role-v3`` -- units by
#: short ref ``U1``.. (role extract order) and evidence by the v10 ids; code maps both back,
#: so the stored role row keeps the v10 shape.  C16/C19 isolation rules apply unchanged.
ROLE_CONTRACT_V3: Final[str] = "card-role-v3"
ROLE_CONTRACT_V3_SCHEMA_VERSION: Final[str] = "bidops.verdict-role.v3"
ROLE_CONTRACT_V3_POLICY_IDENTITIES: Final[frozenset[str]] = frozenset({"analysis-policy-luna-rl-v11"})
EXTRACT_MISSING_UNIT_POLICY_IDENTITIES: Final[frozenset[str]] = frozenset({
    "analysis-policy-luna-rl-v10", "analysis-policy-luna-rl-v11",
})
#: 결정 C19 (RL-05 STEP-008): policies whose synthesis cautions/next actions outside the
#: role units or their evidence are dropped and recorded (final row ``isolated_items``)
#: instead of failing the attempt.  Validation code only -- the v10 policy file is unchanged.
#: 결정 C20: v11 keeps the rule (its refs/ids that do not resolve are dropped the same way).
SYNTHESIS_ITEM_ISOLATION_POLICY_IDENTITIES: Final[frozenset[str]] = frozenset({
    "analysis-policy-luna-rl-v10", "analysis-policy-luna-rl-v11",
})
#: 결정 C20 (RL-05 STEP-009): policies whose text-kind constraint ``value`` need not be a
#: verbatim substring of its (still verbatim) quote -- see ``_text_value_ok``.  Every other
#: kind and every earlier policy keep the exact expression rule.
TEXT_VALUE_RELAXED_POLICY_IDENTITIES: Final[frozenset[str]] = frozenset({"analysis-policy-luna-rl-v11"})
#: 결정 C20: facts whose deterministic compare reads a text constraint's ``value`` (상주
#: 지역, 직접생산 품명, 본점·소재지 지역; ``card_compare._confirmed_comparison``).  A text
#: constraint resolving to one of them keeps the verbatim value rule under v11 too, so a
#: paraphrased value can never decide a compare result.
TEXT_VALUE_COMPARED_FACT_KEYS: Final[frozenset[str]] = frozenset({
    "staff:onsite", "qual:direct_production", "qual:branch",
})
#: 결정 C16: rule code of a batch unit the extract answer still lacks after the repair.
EXTRACT_UNIT_MISSING_RULE: Final[str] = "extract_unit_missing"
#: Extract fields a v2 answer never carries; code derives them (recorded in audits).
CODE_DERIVED_EXTRACT_FIELDS: Final[tuple[str, ...]] = ("concept_candidates", "constraints.operator")
#: 결정 B51: evidence-class rule codes of one extract item (isolated under v7).
EVIDENCE_QUOTE_RULE: Final[str] = "evidence_quote_not_verbatim"
CONSTRAINT_QUOTE_RULE: Final[str] = "constraint_quote_not_verbatim"
CONSTRAINT_NOT_UNIQUE_RULE: Final[str] = "constraint_quote_not_unique"
CONSTRAINT_TRUNCATED_RULE: Final[str] = "constraint_quote_truncated"
CONSTRAINT_FACT_KEY_RULE: Final[str] = "constraint_fact_key_invalid"
CONSTRAINT_EXPRESSION_RULE: Final[str] = "constraint_expression"
REQUIREMENT_NUMBER_RULE: Final[str] = "requirement_number_untraceable"
CONCEPT_RULE: Final[str] = "concept_candidates_mismatch"
#: 결정 B51: the attempt fails when rejected units exceed this share of all units.
REJECTED_UNIT_LIMIT_NUMERATOR: Final[int] = 1
REJECTED_UNIT_LIMIT_DENOMINATOR: Final[int] = 4
#: Repair rule code when the answer does not match the v2 output schema itself.
OUTPUT_SCHEMA_RULE: Final[str] = "output_schema"
#: Repair rule code when items are not exactly one per batch unit in input order.
UNIT_COVERAGE_RULE: Final[str] = "extract_unit_coverage"
_RULE_CODE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


class CardAnalysisValidationError(ValueError):
    """Safe stage validation failure without model text or company material."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CardExtractStructureError(CardAnalysisValidationError):
    """결정 B33: schema-class failure of an assembled v2 extract (repairable once).

    Carries only rule codes (pydantic/coverage codes, ``output_schema``) and
    item indexes -- never source or answer text.  Unrepaired it is
    ``card_extract_invalid`` like every other extract failure.
    """

    def __init__(self, rule_codes: Sequence[str], item_indexes: Sequence[int]) -> None:
        super().__init__(CARD_EXTRACT_INVALID)
        self.rule_codes = sorted({code for code in rule_codes if _RULE_CODE.fullmatch(code)}) or [OUTPUT_SCHEMA_RULE]
        self.item_indexes = sorted({int(index) for index in item_indexes if type(index) is int and index >= 0})


class CardConstraintQuoteTruncatedError(CardAnalysisValidationError):
    """결정 B35: a constraint quote that cuts off its number's unit or comparator.

    ``card_extract_invalid`` like every evidence failure (never repaired: the
    quote is evidence); ``rule_code`` names the rule for tests and diagnosis.
    """

    rule_code = "constraint_quote_truncated"

    def __init__(self) -> None:
        super().__init__(CARD_EXTRACT_INVALID)


class CardConstraintQuoteNotUniqueError(CardAnalysisValidationError):
    """결정 B37: a digit-bearing constraint quote that is not exactly once in its cited block.

    The locator names only the block, so a repeated quote does not identify
    which number it means.  ``card_extract_invalid`` (evidence, never repaired).
    """

    rule_code = "constraint_quote_not_unique"

    def __init__(self) -> None:
        super().__init__(CARD_EXTRACT_INVALID)


class CardAnalysisRuntimeError(RuntimeError):
    """Safe runner failure code; the worker turns it into a failed attempt."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CardAnalysisStageStoreError(ValueError):
    """Safe persistence-envelope failure raised before any row is inserted."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# --- RL fact anchors (spec "대조 fact_key allowlist") -------------------------------
#
# A constraint is linked to an allowlisted company fact only when the source
# quote itself carries the fact's lexical anchor (whitespace removed, NFKC,
# upper case).  No synonym expansion or semantic guess; outside the list a
# constraint is ``unmapped`` (unknown).  ``CARD_FACT_KINDS`` limits which
# constraint kinds a fact can be compared with.

CARD_FACT_ANCHORS: Final[dict[str, tuple[str, ...]]] = {
    "staff:onsite": ("상주",),
    "staff:total": ("인원총수", "총인원", "전체인원", "전체임직원", "총임직원", "상시근로자"),
    "staff:design_publishing": ("디자인", "디자이너", "퍼블리싱", "퍼블리셔"),
    "qual:direct_production": ("직접생산",),
    "qual:procurement_1468": ("1468", "컴퓨터관련서비스"),
    "qual:sme_certificate": ("중소기업확인서", "중소기업자확인서", "소상공인확인서"),
    "qual:sw_business": ("일반현황관리확인서", "SW사업자일반현황", "소프트웨어사업자일반현황"),
    "qual:credit_rating": ("신용평가등급", "신용등급", "기업신용평가"),
    "qual:infosec_cert": ("ISMS", "정보보호관리체계", "정보보호인증"),
    "qual:sanction_free": ("부정당", "입찰참가자격제한", "참가자격제한"),
    "qual:branch": ("본점", "주된영업소", "소재지", "지역제한", "지점"),
    "pref:solo_cap": ("추정가격", "사업예산", "사업비", "소요예산", "기초금액", "배정예산", "예정가격"),
    "pref:consortium": ("공동수급", "컨소시엄", "공동도급"),
    "pref:subcontract": ("하도급", "하청"),
}
CARD_FACT_KINDS: Final[dict[str, frozenset[str]]] = {
    "staff:onsite": frozenset({"count", "text"}),
    "staff:total": frozenset({"count"}),
    "staff:design_publishing": frozenset({"count"}),
    "qual:direct_production": frozenset({"boolean", "text"}),
    "qual:procurement_1468": frozenset({"boolean", "text"}),
    "qual:sme_certificate": frozenset({"boolean", "text"}),
    "qual:sw_business": frozenset({"boolean", "text"}),
    "qual:credit_rating": frozenset({"boolean", "text"}),
    "qual:infosec_cert": frozenset({"boolean", "text"}),
    "qual:sanction_free": frozenset({"boolean", "text"}),
    "qual:branch": frozenset({"text"}),
    "pref:solo_cap": frozenset({"amount"}),
    "pref:consortium": frozenset({"boolean", "text", "amount", "count"}),
    "pref:subcontract": frozenset({"boolean", "text", "percentage"}),
}
if not set(CARD_FACT_ANCHORS) == set(CARD_COMPARE_FACT_PATHS) == set(CARD_FACT_KINDS):
    raise RuntimeError("card fact anchor table does not match the compare allowlist")

_AMOUNT_MULTIPLIERS: Final[dict[str, Decimal]] = {
    "억원": Decimal(100_000_000),
    "백만원": Decimal(1_000_000),
    "천원": Decimal(1_000),
    "원": Decimal(1),
}
_DURATION_SUFFIXES: Final[dict[str, tuple[str, ...]]] = {
    "month": ("개월", "월"),
    "day": ("일",),
    "year": ("년",),
}
_NUMBER = r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?"


def normalized_anchor_text(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).upper()


def fact_anchor_matches(fact_key: str, quote: str) -> bool:
    """Whether ``quote`` carries the lexical anchor of an allowlisted fact."""

    anchors = CARD_FACT_ANCHORS.get(fact_key)
    if anchors is None:
        return False
    # "비상주" is the opposite of an onsite condition; it never anchors 상주.
    normalized = normalized_anchor_text(quote).replace("비상주", "")
    if fact_key == "staff:total" and "상주" in normalized:
        return False  # 총 인원을 상주 인원으로 쓰지 않는다
    if fact_key == "pref:solo_cap" and "실적" in normalized:
        return False  # 실적 금액은 사업 금액 상한과 다른 사실이다
    if fact_key == "qual:infosec_cert":
        if re.search(r"(?<![A-Z0-9])ISMS", normalized) is not None:
            return True
        anchors = tuple(anchor for anchor in anchors if anchor != "ISMS")
    return any(normalized_anchor_text(anchor) in normalized for anchor in anchors)


def resolve_fact_key(constraint: CardRequirementConstraint) -> str | None:
    """The allowlisted fact a constraint is compared with, or ``None`` (unmapped).

    A model-supplied ``fact_key`` is kept (extract validation already proved
    it is allowlisted and anchored).  Otherwise exactly one allowlisted
    anchor of a compatible kind must occur in the constraint quote; zero or
    several candidates stay unmapped.  ``operator=unknown`` never links.
    """

    if constraint.fact_key is not None:
        return constraint.fact_key
    if constraint.operator == "unknown":
        return None
    matches = [
        key for key in CARD_FACT_ANCHORS
        if constraint.kind in CARD_FACT_KINDS[key] and fact_anchor_matches(key, constraint.quote)
    ]
    return matches[0] if len(matches) == 1 else None


# --- numbers and operators (HP-03 rules) -------------------------------------------


def decimal_value(value: int | float, code: str = CARD_EXTRACT_INVALID) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise CardAnalysisValidationError(code) from None
    if not result.is_finite():
        raise CardAnalysisValidationError(code)
    return result


def source_numbers(text: str) -> list[Decimal]:
    result: list[Decimal] = []
    for raw in re.findall(rf"(?<![0-9.])(?:{_NUMBER})(?![0-9.])", text):
        try:
            result.append(Decimal(raw.replace(",", "")))
        except InvalidOperation:
            continue
    return result


def amount_atoms(text: str) -> list[Decimal]:
    return [
        Decimal(number.replace(",", "")) * _AMOUNT_MULTIPLIERS[suffix]
        for number, suffix in re.findall(rf"(?<![0-9.])({_NUMBER})\s*(억원|백만원|천원|원)", text)
    ]


#: Closed operator vocabulary (HP-03 rules + 결정 B35).  ``미만``/``초과`` stay
#: ``unknown``: the wire has no strict lt/gt operator.
GTE_MARKERS: Final[tuple[str, ...]] = ("이상", "최소")
LTE_MARKERS: Final[tuple[str, ...]] = ("이하", "이내", "최대", "까지")
AMBIGUOUS_MARKERS: Final[tuple[str, ...]] = ("초과", "미만", "전후", "내외", "종료일포함", "약", "정도")
#: 결정 B35: "N초 내(에)" / "N일 내로" -- ``내`` right after a number (and its
#: unit) is a within-deadline like ``이내``; "내용"/"내부"/"국내" never match.
_WITHIN_AFTER_NUMBER = re.compile(r"[0-9]\s*[가-힣%]{0,3}\s*내(?:에|로)?(?![가-힣])")
#: 결정 B35: "N부터 M까지" is a range (ambiguous), not a deadline.
_RANGE_FROM_TO = re.compile(r"부터.*까지", re.DOTALL)
#: 결정 B37: tilde ranges incl. the wave dash U+301C and a ``.``/``)`` before the
#: tilde ("4〜8시간", "2027. 1. 1. ～ 2027. 12. 31.", "2～3점").
_TILDE_RANGE = re.compile(r"[0-9][.)]?\s*[~～〜]\s*[0-9]")
#: 결정 B37: a hyphen/en dash/minus between exactly two numbers ("4-8시간",
#: "1–2단계").  A third group (phone numbers "032-650-6751", ISO dates
#: "2027-01-31") is not a range, and a letter before the dash ("SFR-001") never is.
_DASH_RANGE = re.compile(
    r"(?<![0-9][-–−])(?<![0-9.])[0-9]+(?:\.[0-9]+)?\s*[-–−]\s*[0-9]+(?:\.[0-9]+)?(?![0-9.])(?!\s*[-–−]\s*[0-9])"
)


def _operator_from_quote(quote: str) -> str:
    normalized = normalized_anchor_text(quote)
    nfkc = unicodedata.normalize("NFKC", quote)
    has_gte = any(marker in normalized for marker in GTE_MARKERS)
    has_lte = (
        any(marker in normalized for marker in LTE_MARKERS)
        or _WITHIN_AFTER_NUMBER.search(nfkc) is not None
    )
    ambiguous = (
        (has_gte and has_lte)
        or any(marker in normalized for marker in AMBIGUOUS_MARKERS)
        or _RANGE_FROM_TO.search(nfkc) is not None
        or re.search(r"[0-9]\s*/\s*[0-9]", quote) is not None
        or _TILDE_RANGE.search(quote) is not None
        or _DASH_RANGE.search(quote) is not None
    )
    if ambiguous:
        return "unknown"
    if has_gte:
        return "gte"
    if has_lte:
        return "lte"
    return "eq"


# --- 결정 B35: truncated constraint quotes ---------------------------------------------
#
# A quote that stops right before its own unit word or comparator ("3" of
# "월 3회 미만", "90%" of "90%를 초과", "5" of "5일 이상") lets the operator --
# derived from the quote -- read ``eq`` where the notice says otherwise.  The
# check uses the quote matcher's own form (raw substring of the named block).
# It applies to every constraint whose quote carries a digit except
# ``boolean``.

#: Comparators that follow a number (subset of the operator vocabulary + ``내``).
TRAILING_COMPARATORS: Final[tuple[str, ...]] = (
    "이상", "이하", "이내", "초과", "미만", "전후", "내외", "정도", "까지",
)
#: Unit/counter words that directly follow a number in RFP text.
TRAILING_UNIT_WORDS: Final[tuple[str, ...]] = (
    "백만원", "천원", "억원", "만원", "원", "개월", "시간", "글자", "%", "％",
    "명", "일", "월", "년", "회", "건", "분", "초", "자", "대", "개", "점", "주", "배", "차",
)
_TRAILING_PARTICLES = "를을의"
_TRAILING_COMPARATOR = re.compile(
    r"^\s*(?:[" + _TRAILING_PARTICLES + r"]\s*)?(?:"
    + "|".join(re.escape(word) for word in TRAILING_COMPARATORS)
    + r"|내(?:에|로)?(?![가-힣]))"
)
_TRAILING_UNIT = re.compile(r"^\s*(?:" + "|".join(re.escape(word) for word in TRAILING_UNIT_WORDS) + ")")
_TRAILING_DIGITS = re.compile(r"^(?:[0-9]|[.,][0-9])")
#: 결정 B36: text right before a digit-initial quote that continues a number.
_LEADING_NUMBER_CUT = re.compile(r"[0-9][.,]?$")


def constraint_quote_checked(kind: str, quote: str) -> bool:
    """Whether the B35-B37 quote rules apply: the quote carries a digit and the kind is not ``boolean``."""

    return bool(quote) and kind != "boolean" and re.search(r"[0-9]", quote) is not None


def constraint_quote_occurrences(quote: str, text: str) -> int:
    """Occurrences of ``quote`` in ``text`` with the quote matcher's raw substring rule (overlaps count)."""

    if not quote:
        return 0
    count, start = 0, text.find(quote)
    while start >= 0:
        count += 1
        start = text.find(quote, start + 1)
    return count


def constraint_quote_truncated(kind: str, quote: str, text: str) -> bool:
    """Whether the cited occurrence of ``quote`` in ``text`` continues with its comparator or unit.

    ``True`` when, right after an occurrence (whitespace and one particle
    를/을/의 allowed), the block continues with a trailing comparator
    (``이상``·``이하``·``이내``·``초과``·``미만``·``전후``·``내외``·``정도``·
    ``까지``·``내(에|로)``), or -- when the quote ends with a digit -- with more
    digits or a unit word (``회``·``일``·``%``·``글자``·``분``…).  결정 B36
    (front truncation): a quote that starts with a digit is also truncated when
    an occurrence is directly preceded by a digit, or by ``,``/``.`` that itself
    follows a digit (``0명`` of ``10명``, ``000,000원`` of ``150,000,000원``;
    ``1. 3명`` is not -- a space separates them).  Only quotes containing a
    digit are checked; ``boolean`` constraints never are.  결정 B37: the
    validator first requires the quote to occur exactly once in the block
    (``constraint_quote_occurrences``), so only that single occurrence -- the
    first one -- is checked here (the B35 "any occurrence" rule is replaced).
    """

    if not constraint_quote_checked(kind, quote):
        return False
    start = text.find(quote)
    if start < 0:
        return False
    rest = text[start + len(quote):]
    if _TRAILING_COMPARATOR.match(rest) is not None:
        return True
    if quote[-1].isdigit() and (_TRAILING_DIGITS.match(rest) or _TRAILING_UNIT.match(rest)):
        return True
    return quote[0].isdigit() and _LEADING_NUMBER_CUT.search(text[:start]) is not None


def expected_constraint_operator(kind: str, quote: str) -> str:
    """The only operator the extract validator accepts for a constraint of ``kind`` quoting ``quote``.

    ``_operator_from_quote`` plus the relative-date rule for ``text``/``date``.
    The validator itself uses this function; v2 assembly (결정 B33) reuses it
    so the operator is derived, never supplied by the model.
    """

    expected_operator = _operator_from_quote(quote)
    if kind in {"text", "date"} and any(
        marker in normalized_anchor_text(quote) for marker in ("착수후", "계약후", "상대일", "종료일포함")
    ):
        expected_operator = "unknown"
    return expected_operator


def _text_value_ok(constraint: CardRequirementConstraint) -> bool:
    """결정 C20 (policy v11): the text-kind ``value`` rule replacing "value is a substring of the quote".

    The value may be a short normalized phrase of the quote (the quote itself is
    still checked verbatim, unique and untruncated elsewhere), but every digit run
    of the value must be a digit run of the quote (no number the quote does not
    write), and a constraint whose compare reads the value
    (``TEXT_VALUE_COMPARED_FACT_KEYS``) keeps the verbatim rule.  Non-emptiness and
    ``unit=null`` are the unchanged DTO rules.
    """

    value = str(constraint.value)
    if not set(re.findall(r"[0-9]+", value)) <= set(re.findall(r"[0-9]+", constraint.quote)):
        return False
    if resolve_fact_key(constraint) in TEXT_VALUE_COMPARED_FACT_KEYS:
        return value in constraint.quote
    return True


def _validate_constraint_expression(constraint: CardRequirementConstraint, *, text_value_relaxed: bool = False) -> None:
    """Number, unit and operator must be the quote's own expression (no conversion beyond KRW/%).

    ``text_value_relaxed`` (결정 C20, policy v11) replaces only the text-kind check
    ``value in quote`` with ``_text_value_ok``; the operator check (derived from the
    quote) and every other kind are unchanged.
    """

    quote = constraint.quote
    expected_operator = expected_constraint_operator(constraint.kind, quote)
    if constraint.operator != expected_operator:
        raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)

    if constraint.kind == "amount":
        parsed = amount_atoms(quote)
        if decimal_value(constraint.value) not in parsed or (
            constraint.operator != "unknown" and len(set(parsed)) != 1
        ):
            raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    elif constraint.kind == "duration":
        suffixes = _DURATION_SUFFIXES[str(constraint.unit)]
        found = re.findall(rf"(?<![0-9.])({_NUMBER})\s*(개월|월|일|년)", quote)
        parsed = [Decimal(number.replace(",", "")) for number, suffix in found if suffix in suffixes]
        if decimal_value(constraint.value) not in parsed or (
            constraint.operator != "unknown"
            and (len(set(parsed)) != 1 or any(suffix not in suffixes for _number, suffix in found))
        ):
            raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    elif constraint.kind == "count":
        if constraint.unit == "person":
            parsed = [Decimal(number.replace(",", "")) for number in re.findall(rf"(?<![0-9.])({_NUMBER})\s*명", quote)]
            if constraint.operator == "unknown":
                # ``2/3명``: the trailing unit applies to both numbers of that
                # exact shared-unit expression only.
                for first, second in re.findall(
                    rf"(?<![0-9.])({_NUMBER})\s*(?:/|또는|혹은)\s*({_NUMBER})\s*명", quote,
                ):
                    parsed.extend((Decimal(first.replace(",", "")), Decimal(second.replace(",", ""))))
        else:
            parsed = source_numbers(quote)
        if decimal_value(constraint.value) not in parsed or (
            constraint.operator != "unknown" and len(set(parsed)) != 1
        ):
            raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    elif constraint.kind == "percentage":
        parsed = [Decimal(number.replace(",", "")) for number in re.findall(rf"(?<![0-9.])({_NUMBER})\s*%", quote)]
        if decimal_value(constraint.value) not in parsed or (
            constraint.operator != "unknown" and len(set(parsed)) != 1
        ):
            raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    elif constraint.kind == "date":
        year, month, day = str(constraint.value).split("-")
        forms = {
            str(constraint.value),
            f"{year}.{int(month)}.{int(day)}",
            f"{year}년 {int(month)}월 {int(day)}일",
            f"{year}년{int(month)}월{int(day)}일",
        }
        if not any(form in quote for form in forms):
            raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    elif constraint.kind == "boolean":
        negative = any(marker in quote for marker in ("미보유", "없음", "불가", "아님", "않음", "아닌"))
        positive = any(marker in quote for marker in ("보유", "필수", "가능", "준수", "하여야", "등록", "제출"))
        if (constraint.value is True and (negative or not positive)) or (
            constraint.value is False and not negative
        ):
            raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    elif constraint.kind == "text":
        if not (_text_value_ok(constraint) if text_value_relaxed else str(constraint.value) in quote):
            raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)


def _requirement_numbers_traceable(item: CardRequirementExtractItem, unit: CardAnalysisUnit) -> bool:
    """Every number of ``normalized_requirement`` occurs in the unit source (or a validated constraint)."""

    source_text = "\n".join(block.text for block in unit.blocks)
    allowed: set[Decimal] = set(source_numbers(source_text))
    allowed.update(Decimal(run) for run in re.findall(r"[0-9]+", source_text))
    allowed.update(amount_atoms(source_text))
    for constraint in item.constraints:
        if constraint.kind in {"amount", "duration", "count", "percentage"}:
            allowed.add(decimal_value(constraint.value))
    return all(number in allowed for number in source_numbers(item.normalized_requirement))


# --- extract validation -------------------------------------------------------------


def _ontology_rows(ontology: ValidatedOntology | Sequence[OntologyConcept]) -> tuple[OntologyConcept, ...]:
    rows = ontology.concepts if isinstance(ontology, ValidatedOntology) else tuple(ontology)
    if not rows or any(not isinstance(row, OntologyConcept) for row in rows):
        raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    return tuple(rows)


def card_input_of(value: CardAnalysisInput | Mapping[str, Any], code: str) -> CardAnalysisInput:
    try:
        return value if isinstance(value, CardAnalysisInput) else CardAnalysisInput.model_validate(value)
    except (TypeError, ValueError, ValidationError):
        raise CardAnalysisValidationError(code) from None


def _batch_context(
    card_input: CardAnalysisInput | Mapping[str, Any],
    batch_index: int,
) -> tuple[CardAnalysisInput, CardAnalysisBatch, list[CardAnalysisUnit]]:
    if isinstance(batch_index, bool) or not isinstance(batch_index, int) or batch_index < 0:
        raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    frozen = card_input_of(card_input, CARD_EXTRACT_INVALID)
    if batch_index >= len(frozen.batches):
        raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    batch = frozen.batches[batch_index]
    units_by_id = {unit.unit_id: unit for unit in frozen.units}
    try:
        units = [units_by_id[unit_id] for unit_id in batch.unit_ids]
    except KeyError:
        raise CardAnalysisValidationError(CARD_EXTRACT_INVALID) from None
    return frozen, batch, units


def _violation_error(code: str) -> CardAnalysisValidationError:
    if code == CONSTRAINT_NOT_UNIQUE_RULE:
        return CardConstraintQuoteNotUniqueError()
    if code == CONSTRAINT_TRUNCATED_RULE:
        return CardConstraintQuoteTruncatedError()
    return CardAnalysisValidationError(CARD_EXTRACT_INVALID)


def extract_item_violations(
    item: CardRequirementExtractItem,
    unit: CardAnalysisUnit,
    concepts: Sequence[OntologyConcept],
    *,
    first_only: bool = False,
    text_value_relaxed: bool = False,
) -> list[str]:
    """Evidence-class rule codes of one extract item against its frozen unit (결정 B51).

    The rules and their order are exactly the extract validator's: evidence
    quotes, then per constraint (verbatim quote, uniqueness, truncation,
    ``fact_key`` anchor, expression), the numbers of ``normalized_requirement``
    and the concept candidates.  A constraint whose quote is not in its block
    is not checked further.  ``first_only`` stops at the first code (the
    batch-level validator).  ``text_value_relaxed`` (결정 C20, policy v11) is the
    text-value rule of ``_validate_constraint_expression``.  Nothing is corrected.
    """

    codes: list[str] = []

    def add(code: str) -> bool:
        if code not in codes:
            codes.append(code)
        return first_only

    blocks = {(unit.source_sha256, block.block_key): block.text for block in unit.blocks}
    for evidence in item.evidence:
        text = blocks.get((evidence.source_sha256, evidence.block_key))
        if (text is None or evidence.quote not in text) and add(EVIDENCE_QUOTE_RULE):
            return codes
    for constraint in item.constraints:
        text = blocks.get((constraint.locator.source_sha256, constraint.locator.block_key))
        if text is None or constraint.quote not in text:
            if add(CONSTRAINT_QUOTE_RULE):
                return codes
            continue
        if (
            constraint_quote_checked(constraint.kind, constraint.quote)
            and constraint_quote_occurrences(constraint.quote, text) != 1
        ):
            if add(CONSTRAINT_NOT_UNIQUE_RULE):
                return codes
        elif constraint_quote_truncated(constraint.kind, constraint.quote, text) and add(CONSTRAINT_TRUNCATED_RULE):
            return codes
        if constraint.fact_key is not None and (
            constraint.fact_key not in CARD_COMPARE_FACT_PATHS
            or constraint.kind not in CARD_FACT_KINDS[constraint.fact_key]
            or not fact_anchor_matches(constraint.fact_key, constraint.quote)
        ) and add(CONSTRAINT_FACT_KEY_RULE):
            return codes
        try:
            _validate_constraint_expression(constraint, text_value_relaxed=text_value_relaxed)
        except CardAnalysisValidationError:
            if add(CONSTRAINT_EXPRESSION_RULE):
                return codes
    try:
        traceable = _requirement_numbers_traceable(item, unit)
    except CardAnalysisValidationError:
        traceable = False
    if not traceable and add(REQUIREMENT_NUMBER_RULE):
        return codes
    source_texts = [block.text for block in unit.blocks]
    matched_by_alias: dict[str, set[str]] = {}
    supplied_by_alias: dict[str, set[str]] = {}
    concept_ok = True
    for candidate in item.concept_candidates:
        if not any(candidate.alias_text in text for text in source_texts):
            concept_ok = False
            continue
        matched = set(match_concepts(candidate.alias_text, concepts))
        matched_by_alias[candidate.alias_text] = matched
        if candidate.concept_id is None:
            if matched:
                concept_ok = False
        elif candidate.concept_id not in matched:
            concept_ok = False
        else:
            supplied_by_alias.setdefault(candidate.alias_text, set()).add(candidate.concept_id)
    if any(
        matched and supplied_by_alias.get(alias_text, set()) != matched
        for alias_text, matched in matched_by_alias.items()
    ):
        concept_ok = False
    expected_concepts = {concept_id for text in source_texts for concept_id in match_concepts(text, concepts)}
    supplied_concepts = {
        candidate.concept_id for candidate in item.concept_candidates if candidate.concept_id is not None
    }
    if supplied_concepts != expected_concepts:
        concept_ok = False
    if not concept_ok:
        add(CONCEPT_RULE)
    return codes


def _parsed_extract_batch(
    payload: Mapping[str, Any],
    card_input: CardAnalysisInput | Mapping[str, Any],
    batch_index: int,
    ontology: ValidatedOntology | Sequence[OntologyConcept],
    missing_unit_ids: Sequence[str] = (),
) -> tuple[CardRequirementExtract, dict[str, CardAnalysisUnit], tuple[OntologyConcept, ...], list[str]]:
    """Whole-call (structural) checks shared by both validators: schema, DTO, ontology, exact coverage.

    ``missing_unit_ids`` (결정 C16, policy v10 after the repair): distinct batch
    units the answer lacks; the items must then be exactly the other batch units
    in batch order.  Returns the batch unit order as well.
    """

    validate_payload(payload, REQUIREMENT_EXTRACT_SCHEMA)
    result = CardRequirementExtract.model_validate(payload)
    frozen, batch, units = _batch_context(card_input, batch_index)
    concepts = _ontology_rows(ontology)
    if isinstance(ontology, ValidatedOntology) and ontology.sha256 != frozen.company_binding.ontology_sha256:
        raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    missing = list(missing_unit_ids)
    if isinstance(missing_unit_ids, (str, bytes)) or len(missing) != len(set(missing)) or not set(missing) <= set(
        batch.unit_ids
    ):
        raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    expected = [unit_id for unit_id in batch.unit_ids if unit_id not in set(missing)]
    if result.rejected_units or [item.unit_id for item in result.items] != expected:
        raise CardAnalysisValidationError(CARD_EXTRACT_INVALID)
    return result, {unit.unit_id: unit for unit in units}, concepts, list(batch.unit_ids)


def validate_requirement_extract_isolated(
    payload: Mapping[str, Any],
    *,
    card_input: CardAnalysisInput | Mapping[str, Any],
    batch_index: int,
    ontology: ValidatedOntology | Sequence[OntologyConcept],
    missing_unit_ids: Sequence[str] = (),
    text_value_relaxed: bool = False,
) -> CardRequirementExtract:
    """결정 B51 (policy v7): the batch with evidence-class failures isolated per item.

    ``text_value_relaxed`` (결정 C20, policy v11): the text-constraint value rule of
    ``_text_value_ok`` instead of "value is a substring of its quote".

    Structural failures (schema, strict DTO, ontology binding, exact
    item-per-unit coverage in order) still raise ``card_extract_invalid`` for
    the whole call.  Every item with evidence-class rule codes
    (``extract_item_violations``) is left out of ``items`` -- unchanged and
    unused -- and recorded as ``{unit_id, rule_codes}`` in ``rejected_units``
    (batch order).  Nothing is corrected.

    결정 C16 (policy v10): ``missing_unit_ids`` are batch units the answer still
    lacks after the single repair; each is recorded with ``extract_unit_missing``
    (batch order, together with the evidence-rejected units) and the items must
    be exactly the remaining batch units in order.
    """

    try:
        result, units_by_id, concepts, batch_order = _parsed_extract_batch(
            payload, card_input, batch_index, ontology, missing_unit_ids)
        accepted = []
        rejected_by_id: dict[str, dict[str, Any]] = {
            unit_id: {"unit_id": unit_id, "rule_codes": [EXTRACT_UNIT_MISSING_RULE]} for unit_id in missing_unit_ids
        }
        for item in result.items:
            codes = extract_item_violations(item, units_by_id[item.unit_id], concepts,
                                            text_value_relaxed=text_value_relaxed)
            if codes:
                rejected_by_id[item.unit_id] = {"unit_id": item.unit_id, "rule_codes": codes}
            else:
                accepted.append(item)
        rejected = [rejected_by_id[unit_id] for unit_id in batch_order if unit_id in rejected_by_id]
        return CardRequirementExtract.model_validate({
            "schema_version": result.schema_version,
            "items": [item.model_dump(mode="json") for item in accepted],
            "rejected_units": rejected,
        })
    except CardAnalysisValidationError:
        raise
    except (TypeError, ValueError, ValidationError, SchemaValidationError, KeyError):
        raise CardAnalysisValidationError(CARD_EXTRACT_INVALID) from None


class CardResume:
    """결정 B55: the validated non-synthesis stage rows of a failed source attempt (read only)."""

    def __init__(self, source_attempt_id: UUID, rows: Sequence[Any]) -> None:
        self.source_attempt_id = source_attempt_id
        self.rows = {(row.stage, row.stage_key): row for row in rows}


def resume_content_sha256(frozen: Mapping[str, Any]) -> str:
    """결정 B55: canonical SHA of a frozen input without its preview/policy identity keys."""

    return _sha256({key: value for key, value in frozen.items() if key not in RESUME_IDENTITY_KEYS})


def resume_lineage_valid(
    source_frozen: Mapping[str, Any],
    source_policy: Mapping[str, Any],
    new_frozen: Mapping[str, Any],
    new_policy: Mapping[str, Any],
) -> bool:
    """결정 B55: same frozen content and a policy lineage that differs only in synthesis.

    Frozen inputs are equal except ``RESUME_IDENTITY_KEYS`` (company binding,
    bundle, documents, card units/batches, facts and model identity included).
    Policies are card-v1 and equal except identity, ``report_schema`` and the
    synthesis stage instruction: the extract and three role instructions,
    stage schema, prompt contract, packing and selector must be byte-identical,
    and both must agree on item isolation.  Identity names are never trusted.
    """

    try:
        if resume_content_sha256(source_frozen) != resume_content_sha256(new_frozen):
            return False
        if any(
            policy.get("pipeline_version") != "card-v1" or not isinstance(policy.get("stages"), list)
            for policy in (source_policy, new_policy)
        ):
            return False
        if {key: value for key, value in source_policy.items() if key not in RESUME_POLICY_FREE_KEYS} != {
            key: value for key, value in new_policy.items() if key not in RESUME_POLICY_FREE_KEYS
        }:
            return False
        if any(
            [row.get("stage") for row in policy["stages"]].count("synthesis") != 1 or len(policy["stages"]) != 5
            for policy in (source_policy, new_policy)
        ):
            return False
        source_stages = [row for row in source_policy["stages"] if row.get("stage") != "synthesis"]
        new_stages = [row for row in new_policy["stages"] if row.get("stage") != "synthesis"]
        if source_stages != new_stages:
            return False
        return all(
            (source_policy.get("policy_identity") in identities) == (new_policy.get("policy_identity") in identities)
            # 결정 C16: the role contract (stored role row shape) must agree as well; 결정 C20:
            # so must the v3 role contract and the extract text-value rule (v10 -> v11 never resumes).
            for identities in (ITEM_ISOLATION_POLICY_IDENTITIES, ROLE_CONTRACT_V2_POLICY_IDENTITIES,
                               ROLE_CONTRACT_V3_POLICY_IDENTITIES, TEXT_VALUE_RELAXED_POLICY_IDENTITIES)
        )
    except (TypeError, ValueError, AttributeError):
        return False


def rejected_units_exceed_limit(rejected_count: int, unit_count: int) -> bool:
    """결정 B51: more than 25% of all attempt units rejected (exactly 25% continues)."""

    return rejected_count * REJECTED_UNIT_LIMIT_DENOMINATOR > unit_count * REJECTED_UNIT_LIMIT_NUMERATOR


def validate_requirement_extract(
    payload: Mapping[str, Any],
    *,
    card_input: CardAnalysisInput | Mapping[str, Any],
    batch_index: int,
    ontology: ValidatedOntology | Sequence[OntologyConcept],
    text_value_relaxed: bool = False,
) -> CardRequirementExtract:
    """Validate one model batch against its exact frozen units and ontology (``card_extract_invalid``).

    Exact batch unit coverage in order; every evidence/constraint quote is a
    substring of the named block of that unit; a digit-bearing constraint
    quote occurs exactly once there (결정 B37) and does not cut off its
    number's unit or comparator (결정 B35·B36); numbers, units and operators
    are the quote's own expression; a ``fact_key`` is allowlisted and
    anchored in its quote; concept candidates equal the deterministic
    ontology matches of the unit text; numbers in ``normalized_requirement``
    occur in the source.  Nothing is corrected.
    """

    try:
        result, units_by_id, concepts, _order = _parsed_extract_batch(payload, card_input, batch_index, ontology)
        for item in result.items:
            codes = extract_item_violations(item, units_by_id[item.unit_id], concepts, first_only=True,
                                            text_value_relaxed=text_value_relaxed)
            if codes:
                raise _violation_error(codes[0])
        return result
    except CardAnalysisValidationError:
        raise
    except (TypeError, ValueError, ValidationError, SchemaValidationError, KeyError):
        raise CardAnalysisValidationError(CARD_EXTRACT_INVALID) from None


# --- 결정 B33: v2 answer → v1 extract (code-derived concepts and operators) -----------

_ITEM_PATH = re.compile(r"^\$\.items\[(\d+)\]")
_PYDANTIC_CODE = re.compile(r"^(?:Value error, )?([a-z][a-z0-9_]{2,63})$")


def assemble_requirement_extract_v2(
    payload: Mapping[str, Any],
    *,
    card_input: CardAnalysisInput | Mapping[str, Any],
    batch_index: int,
    ontology: ValidatedOntology | Sequence[OntologyConcept],
    allow_missing_units: bool = False,
) -> dict[str, Any]:
    """Build the ``bidops.requirement-extract.v1`` object of one v2 answer (no correction).

    ``allow_missing_units`` (결정 C16, policy v10, used only for the answer to the
    final repair): a coverage failure that is only missing units (the items are
    the remaining batch units in order, nothing else wrong) is returned instead
    of raised; the caller isolates the missing units.

    The model supplies the semantic fields only.  Per item, ``concept_candidates``
    = ``card_expected_concepts`` of the item's frozen unit (all block texts) and
    every constraint gets ``operator`` = ``expected_constraint_operator(kind,
    quote)``; every model field is copied unchanged.  Schema-class problems --
    the v2 output schema, the strict v1 DTO rules (kind x unit, value format,
    duplicates, ``unknown`` + ``fact_key``) and exactly one item per batch unit
    in input order -- raise ``CardExtractStructureError`` with rule codes and
    item indexes (repairable once).  Everything else (quotes, numbers,
    concepts, evidence) is left to the unchanged ``validate_requirement_extract``.
    """

    _frozen, batch, units = _batch_context(card_input, batch_index)
    concepts = _ontology_rows(ontology)
    units_by_id = {unit.unit_id: unit for unit in units}
    codes: list[str] = []
    indexes: list[int] = []
    try:
        validate_payload(payload, REQUIREMENT_EXTRACT_V2_SCHEMA)
    except SchemaValidationError as error:
        codes.append(OUTPUT_SCHEMA_RULE)
        found = _ITEM_PATH.match(getattr(error, "path", "") or "")
        if found is not None:
            indexes.append(int(found.group(1)))
    items = payload.get("items") if isinstance(payload, Mapping) else None
    if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
        raise CardExtractStructureError([OUTPUT_SCHEMA_RULE], [])
    assembled_items: list[dict[str, Any]] = []
    for item in items:
        unit = units_by_id.get(item.get("unit_id"))
        try:
            expected = (
                card_expected_concepts([block.text for block in unit.blocks], concepts) if unit is not None else []
            )
        except CompanyAnalysisError:
            raise CardAnalysisValidationError(CARD_EXTRACT_INVALID) from None
        constraints = item.get("constraints")
        derived_constraints = constraints
        if isinstance(constraints, list):
            derived_constraints = []
            for constraint in constraints:
                if (
                    isinstance(constraint, Mapping) and isinstance(constraint.get("kind"), str)
                    and isinstance(constraint.get("quote"), str) and "operator" not in constraint
                ):
                    constraint = {**constraint, "operator": expected_constraint_operator(
                        constraint["kind"], constraint["quote"])}
                derived_constraints.append(constraint)
        assembled_items.append({
            **{key: value for key, value in item.items()},
            "constraints": derived_constraints,
            "concept_candidates": expected,
        })
    assembled = {"schema_version": REQUIREMENT_EXTRACT_V1, "items": assembled_items}
    try:
        CardRequirementExtract.model_validate(assembled)
    except ValidationError as error:
        for detail in error.errors():
            found = _PYDANTIC_CODE.match(str(detail.get("msg", "")))
            codes.append(found.group(1) if found is not None else OUTPUT_SCHEMA_RULE)
            location = detail.get("loc", ())
            if len(location) >= 2 and location[0] == "items" and type(location[1]) is int:
                indexes.append(location[1])
    unit_ids = [item.get("unit_id") for item in items]
    # 결정 C16 (policy v10, final attempt only): items that are an ordered strict
    # subsequence of the batch units, with no other structural problem, are kept;
    # the caller records the missing units (``extract_unit_missing``).  Extra,
    # unknown, duplicate or reordered ids stay structural failures.
    missing_only = (
        allow_missing_units and not codes and all(isinstance(unit_id, str) for unit_id in unit_ids)
        and len(unit_ids) == len(set(unit_ids)) and len(unit_ids) < len(batch.unit_ids)
        and unit_ids == [unit_id for unit_id in batch.unit_ids if unit_id in set(unit_ids)]
    )
    if unit_ids != batch.unit_ids and not missing_only:
        codes.append(UNIT_COVERAGE_RULE)
        indexes.extend(
            index for index in range(max(len(unit_ids), len(batch.unit_ids)))
            if index >= len(unit_ids) or index >= len(batch.unit_ids) or unit_ids[index] != batch.unit_ids[index]
        )
    if codes:
        raise CardExtractStructureError(codes, indexes)
    return assembled


# --- append-only stage rows (``card_analysis_stage``) -------------------------------

CardAnalysisStageName = Literal["extract", "compare", "role", "synthesis"]
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_BATCH_KEY = re.compile(r"^(?:0|[1-9][0-9]*)$")
_ROLE_KEYS = frozenset({"eligibility_economics", "technical_fit", "operations_risk"})


def _is_strict_json(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return value == value and value not in {float("inf"), float("-inf")}
    if isinstance(value, list):
        return all(_is_strict_json(item) for item in value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _is_strict_json(item) for key, item in value.items())
    return False


def canonical_card_stage_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """A detached strict JSON object and its canonical SHA-256."""

    if not isinstance(payload, Mapping) or not _is_strict_json(payload):
        raise CardAnalysisStageStoreError("card_stage_payload_invalid")
    try:
        encoded = json.dumps(
            dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        detached = json.loads(encoded)
    except (TypeError, ValueError, UnicodeError):
        raise CardAnalysisStageStoreError("card_stage_payload_invalid") from None
    if not isinstance(detached, dict):
        raise CardAnalysisStageStoreError("card_stage_payload_invalid")
    return detached, hashlib.sha256(encoded).hexdigest()


def store_card_analysis_stage(
    session: Session,
    *,
    attempt_id: UUID,
    stage: CardAnalysisStageName,
    stage_key: str,
    input_sha256: str,
    payload: Mapping[str, Any],
) -> Any:
    """Insert one validated stage result (flush, no commit); the caller owns the fenced transaction."""

    from ..models import CardAnalysisStage

    if not isinstance(attempt_id, UUID):
        raise CardAnalysisStageStoreError("card_stage_attempt_invalid")
    if stage not in {"extract", "compare", "role", "synthesis"}:
        raise CardAnalysisStageStoreError("card_stage_name_invalid")
    valid_key = isinstance(stage_key, str) and len(stage_key) <= 64 and (
        (stage in {"extract", "compare"} and _BATCH_KEY.fullmatch(stage_key) is not None)
        or (stage == "role" and stage_key in _ROLE_KEYS)
        or (stage == "synthesis" and stage_key == "final")
    )
    if not valid_key:
        raise CardAnalysisStageStoreError("card_stage_key_invalid")
    if not isinstance(input_sha256, str) or _HEX64.fullmatch(input_sha256) is None:
        raise CardAnalysisStageStoreError("card_stage_input_hash_invalid")
    detached, result_sha256 = canonical_card_stage_payload(payload)
    row = CardAnalysisStage(
        attempt_id=attempt_id, stage=stage, stage_key=stage_key,
        input_sha256=input_sha256, result_sha256=result_sha256, payload=detached,
    )
    session.add(row)
    session.flush()
    return row


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


# --- runner ---------------------------------------------------------------------------


def _transport_repair_detail(accept: Any, raw_response: bytes | None) -> dict[str, Any]:
    """Rule codes/item indexes of a client-rejected v2 extract answer (codes only, 결정 B33)."""

    fallback = {"rule_codes": [OUTPUT_SCHEMA_RULE], "item_indexes": []}
    try:
        output = json.loads(raw_response or b"")
    except (TypeError, ValueError, UnicodeError):
        return fallback
    if not isinstance(output, Mapping):
        return fallback
    try:
        accept(output)
    except CardExtractStructureError as error:
        return {"rule_codes": list(error.rule_codes), "item_indexes": list(error.item_indexes)}
    except (CardAnalysisValidationError, CardAnalysisRuntimeError):
        return fallback
    return fallback


def stage_prompt(stage: str, instruction: str, rules: Mapping[str, Any], value: Mapping[str, Any],
                 *, repair: bool, repair_detail: Mapping[str, Any] | None = None) -> str:
    """Canonical prompt envelope; ``input`` is the checked D2 transfer payload.

    ``repair_detail`` (결정 B33, v2 extract only) adds ``rule_codes`` and
    ``item_indexes`` to ``validation_repair`` -- codes and integers, never text.
    """

    repair_value: dict[str, Any] = {"scope": "syntax_or_schema_only"}
    if repair and repair_detail is not None:
        rule_codes = repair_detail.get("rule_codes")
        item_indexes = repair_detail.get("item_indexes")
        if (
            set(repair_detail) != {"rule_codes", "item_indexes"}
            or not isinstance(rule_codes, list) or not rule_codes
            or any(not isinstance(code, str) or _RULE_CODE.fullmatch(code) is None for code in rule_codes)
            or not isinstance(item_indexes, list)
            or any(type(index) is not int or index < 0 for index in item_indexes)
        ):
            raise CardAnalysisRuntimeError("processing_failed")
        repair_value = {**repair_value, "rule_codes": list(rule_codes), "item_indexes": list(item_indexes)}
    envelope = {
        "stage": stage,
        "instruction": instruction,
        "output_contract": dict(rules),
        "input": dict(value),
        **({"validation_repair": repair_value} if repair else {}),
    }
    return canonical_json_bytes(envelope).decode("utf-8")


def run_card_analysis(
    service: Any,
    session: Session,
    claim: Any,
    *,
    frozen: Mapping[str, Any],
    policy: Mapping[str, Any],
    approval: Any,
    client: Any | None = None,
    ontology: ValidatedOntology | None = None,
    resume: CardResume | None = None,
) -> None:
    """Run one approved card-v1 attempt: B extract → compare → 3 roles → synthesis.

    * Calls: planned ``B+4``; each call may get one schema-only repair
      (``card.repair_attempts``), so at most ``2*(B+4)``.  Evidence/number
      failures are never repaired.
    * ``stage_schema = bidops.requirement-extract.v2`` (policy v4, 결정 B33):
      the extract call uses ``card-extract-v2``, the payload carries no
      ``expected_concepts``, ``assemble_requirement_extract_v2`` derives
      concepts and operators, and a structural failure of the assembled
      object uses the same single repair (envelope with rule codes and item
      indexes).  The stored extract row is the assembled v1 object; the raw
      response audit and the completion audit record the code-derived fields.
    * Every payload is a D2 projection (role/synthesis: only the facts their
      compare rows reference, 결정 B11) checked by
      ``check_card_transfer_payload`` (``company_input_invalid`` before the call).
    * Every validated result is appended to ``card_analysis_stage`` under the
      claim fence; a stale fence or an expired deadline stores nothing more.
    * ``missing_sections`` of a ``card-sections-v1`` input keep the validated
      extract/compare/role rows but stop before synthesis with
      ``card_source_selection_incomplete`` (unchanged).  A ``card-sections-v2``
      or ``-v3`` input (결정 B23·B30) continues: the final row records ``missing_sections``
      and "진행 가능" is rejected while any section is missing.
    * ``review_timeout_seconds`` is measured with a monotonic clock from the
      start of this run; ``card_review_timeout`` after it.
    """

    from .card_compare import compare_requirements
    from .card_roles import (
        VERDICT_ROLES,
        assemble_practitioner_verdict,
        build_synthesis_input,
        build_verdict_role_inputs,
        synthesis_v1_from_v2,
        synthesis_v1_from_v3,
        validate_isolated_verdict_role,
        validate_practitioner_verdict,
        validate_verdict_role,
        validate_verdict_role_v2,
        validate_verdict_role_v3,
    )
    from .card_units import SELECTOR_VERSION, analysis_call_budget
    from .company_analysis_input import (
        CompanyAnalysisError,
        card_extract_transfer,
        card_referenced_fact_keys,
        card_role_transfer,
        card_synthesis_transfer,
        resolve_company_knowledge_context,
    )
    from .deep_reviews import StaleFenceError

    started = _monotonic()
    review_timeout = int(policy["execution"]["review_timeout_seconds"])
    target_seconds = int(policy["card"]["target_seconds"])
    repair_attempts = int(policy["card"]["repair_attempts"])
    deadline = started + review_timeout
    owned_client = False
    try:
        card_input = card_input_of(frozen["card_analysis"], CARD_EXTRACT_INVALID)
        budget = analysis_call_budget(len(card_input.batches), repair_attempts=repair_attempts)
        if ontology is None:
            knowledge = resolve_company_knowledge_context(session, UUID(str(frozen["company_id"])))
            if (
                knowledge.ontology_row.sha256 != frozen["ontology_sha256"]
                or knowledge.ontology_row.version != frozen["ontology_version"]
                or str(knowledge.graph.id) != frozen["graph_version_id"]
            ):
                raise CardAnalysisRuntimeError("approval_invalid")
            ontology = knowledge.ontology
        session.rollback()
        if client is None:
            if getattr(getattr(service, "settings", None), "analysis_provider", None) == "mock":
                # 결정 B16: reference-mode mock -- deterministic answers, no runner/network.
                from .mock_analysis_client import MockCardAnalysisClient

                client = MockCardAnalysisClient(ontology)
            elif getattr(service, "_injected_client", False):
                client = service._client
            else:
                from .luna_client import LunaClient

                client = LunaClient(
                    service.settings.luna_runner_url,
                    lambda: service._renew_lease(session, claim, require_live=True),
                    deadline,
                )
                owned_client = True
        instructions = {row["stage"]: row["instruction"] for row in policy["stages"]}
        rules = policy["prompt_output_contract"]
        operational = (approval.id, claim.attempt_id, claim.deep_review_id, claim.job_id)
        calls = [0]
        stage_schema = policy.get("stage_schema", REQUIREMENT_EXTRACT_V1)
        if stage_schema not in EXTRACT_CONTRACT_BY_STAGE_SCHEMA:
            raise CardAnalysisRuntimeError("approval_invalid")
        extract_v2 = stage_schema == REQUIREMENT_EXTRACT_V2
        extract_contract = EXTRACT_CONTRACT_BY_STAGE_SCHEMA[stage_schema]
        # 결정 B51: item isolation is a policy v7 rule (v1-v6 keep the batch-level failure).
        item_isolation = policy.get("policy_identity") in ITEM_ISOLATION_POLICY_IDENTITIES
        # 결정 C16: role contract v2 + role item isolation, and extract missing-unit isolation.
        role_v2 = policy.get("policy_identity") in ROLE_CONTRACT_V2_POLICY_IDENTITIES
        # 결정 C20: role contract v3 (unit refs + the v2 evidence ids, same stored row shape).
        role_v3 = policy.get("policy_identity") in ROLE_CONTRACT_V3_POLICY_IDENTITIES
        role_ids = role_v2 or role_v3
        missing_unit_isolation = (
            extract_v2 and item_isolation and policy.get("policy_identity") in EXTRACT_MISSING_UNIT_POLICY_IDENTITIES
        )
        # 결정 C20: the text-constraint value rule of policy v11.
        text_value_relaxed = policy.get("policy_identity") in TEXT_VALUE_RELAXED_POLICY_IDENTITIES
        rejected_units: list[Any] = []
        # 결정 B55: the synthesis contract follows the pinned policy's report_schema.
        report_schema = policy.get("report_schema", PRACTITIONER_VERDICT_V1)
        if report_schema not in SYNTHESIS_CONTRACT_BY_REPORT_SCHEMA:
            raise CardAnalysisRuntimeError("approval_invalid")
        synthesis_v2 = report_schema == PRACTITIONER_VERDICT_V2
        # 결정 C20: synthesis contract v3 (refs/ids) always runs with C19 item isolation.
        synthesis_v3 = report_schema == PRACTITIONER_VERDICT_V3
        synthesis_isolation = policy.get("policy_identity") in SYNTHESIS_ITEM_ISOLATION_POLICY_IDENTITIES
        if synthesis_v3 and not synthesis_isolation:
            raise CardAnalysisRuntimeError("approval_invalid")
        synthesis_contract = SYNTHESIS_CONTRACT_BY_REPORT_SCHEMA[report_schema]
        derivation = (
            {"extract_contract": REQUIREMENT_EXTRACT_V2, "code_derived_fields": list(CODE_DERIVED_EXTRACT_FIELDS)}
            if extract_v2 else None
        )

        def check_deadline() -> None:
            if _monotonic() >= deadline:
                raise CardAnalysisRuntimeError(CARD_REVIEW_TIMEOUT)

        def persist_raw(result: Any, *, stage: str, stage_key: str, repair_attempt: int,
                        repair_detail: Mapping[str, Any] | None = None) -> None:
            if not isinstance(getattr(result, "raw_response", None), bytes) or not result.raw_response:
                return
            check_deadline()
            extra: dict[str, Any] = {}
            if stage == "extract" and derivation is not None:
                extra.update(derivation)
            if repair_detail is not None:
                extra["repair_rule_codes"] = list(repair_detail["rule_codes"])
            service._persist_card_raw_response(
                session, claim, result, stage=stage, stage_key=stage_key,
                call_index=calls[0], repair_attempt=repair_attempt,
                **({"extra_safe_metadata": extra} if extra else {}),
            )

        def invoke(stage: str, stage_key: str, contract: str, instruction: str,
                   value: Mapping[str, Any], invalid_code: str,
                   accept: Any = None, final_accept: Any = None) -> Mapping[str, Any]:
            repair_detail: dict[str, Any] | None = None
            for repair_attempt in range(repair_attempts + 1):
                check_deadline()
                if calls[0] >= budget.maximum_calls:
                    raise CardAnalysisRuntimeError(INPUT_BUDGET_EXCEEDED)
                service._renew_lease(session, claim, require_live=True)
                check_deadline()
                prompt = stage_prompt(stage, instruction, rules, value, repair=repair_attempt > 0,
                                      repair_detail=repair_detail if repair_attempt > 0 else None)
                if len(prompt) > PROMPT_CHARACTER_LIMIT:
                    # fail closed before the call; the payload is never cut (결정 B11)
                    raise CardAnalysisRuntimeError(PROMPT_REJECTED)
                calls[0] += 1
                try:
                    result = client.invoke_prompt(prompt, contract=contract)
                except ModelInvocationError as error:
                    if error.code in {"review_timeout", "model_timeout"}:
                        raise CardAnalysisRuntimeError(CARD_REVIEW_TIMEOUT) from None
                    if error.raw_response:
                        persist_raw(error, stage=stage, stage_key=stage_key, repair_attempt=repair_attempt,
                                    repair_detail=repair_detail if repair_attempt > 0 else None)
                    if error.code != "schema_invalid":
                        raise CardAnalysisRuntimeError(error.code) from None
                    if repair_attempt >= repair_attempts:
                        raise CardAnalysisRuntimeError(invalid_code) from None
                    # v1 contracts keep the existing envelope; a v2 extract (결정 B33) also
                    # names the rule codes of the rejected answer (the client checks the
                    # same output schema before BidOps sees the answer).
                    repair_detail = None if accept is None else _transport_repair_detail(accept, error.raw_response)
                    continue
                check_deadline()
                persist_raw(result, stage=stage, stage_key=stage_key, repair_attempt=repair_attempt,
                            repair_detail=repair_detail if repair_attempt > 0 else None)
                output = getattr(result, "structured_output", result)
                if not isinstance(output, Mapping):
                    raise CardAnalysisRuntimeError(invalid_code)
                if accept is None:
                    return output
                try:
                    return accept(output)
                except CardExtractStructureError as error:
                    # 결정 B33: schema-class failure of the assembled answer -- same single repair.
                    if repair_attempt >= repair_attempts:
                        if final_accept is not None:
                            # 결정 C16: the answer to the last call may still be accepted with
                            # its missing units isolated; any other structure failure stays fatal.
                            try:
                                return final_accept(output)
                            except CardExtractStructureError:
                                pass
                        raise CardAnalysisRuntimeError(invalid_code) from None
                    repair_detail = {"rule_codes": list(error.rule_codes), "item_indexes": list(error.item_indexes)}
                    continue
            raise CardAnalysisRuntimeError(invalid_code)

        def persist(stage: str, key: str, value: Mapping[str, Any], input_value: Mapping[str, Any]) -> None:
            check_deadline()
            if not service._lock_claim(session, claim):
                session.rollback()
                raise StaleFenceError()
            if _monotonic() >= deadline:
                session.rollback()
                raise CardAnalysisRuntimeError(CARD_REVIEW_TIMEOUT)
            store_card_analysis_stage(
                session, attempt_id=claim.attempt_id, stage=stage, stage_key=key,
                input_sha256=_sha256(input_value), payload=value,
            )
            session.commit()

        extract_items: list[Any] = []
        compare_items: list[Any] = []
        reused: list[dict[str, Any]] = []

        def reuse(stage: str, key: str, input_value: Mapping[str, Any]) -> Mapping[str, Any]:
            """결정 B55: copy one validated source row whose recomputed input hashes the same."""

            row = resume.rows.get((stage, key)) if resume is not None else None
            if row is None or not isinstance(row.payload, Mapping) or row.input_sha256 != _sha256(input_value):
                raise CardAnalysisRuntimeError(RESUME_SOURCE_INVALID)
            payload_value, result_sha256 = canonical_card_stage_payload(row.payload)
            if result_sha256 != row.result_sha256:
                raise CardAnalysisRuntimeError(RESUME_SOURCE_INVALID)
            reused.append({"stage": stage, "stage_key": key, "input_sha256": row.input_sha256,
                           "result_sha256": result_sha256})
            return payload_value

        if resume is not None and (
            {key for key in resume.rows if key[0] in {"extract", "compare"}}
            != {(stage, str(batch.batch_index)) for batch in card_input.batches for stage in ("extract", "compare")}
            or {key for key in resume.rows if key[0] == "role"} != {("role", role) for role in VERDICT_ROLES}
            or any(key[0] not in {"extract", "compare", "role"} for key in resume.rows)
        ):
            raise CardAnalysisRuntimeError(RESUME_SOURCE_INVALID)
        for batch in card_input.batches:
            key = str(batch.batch_index)
            payload = card_extract_transfer(frozen, batch.batch_index, ontology, operational_values=operational,
                                            stage_schema=stage_schema)
            if resume is not None:
                stored_extract = CardRequirementExtract.model_validate(reuse("extract", key, payload))
                compared = compare_requirements(stored_extract, frozen=frozen)
                extract_payload = stored_extract.model_dump(mode="json")
                compare_input = {
                    "extract": extract_payload,
                    "profile_facts": frozen["profile_facts"], "profile_evidence": frozen["profile_evidence"],
                    "graph_nodes": frozen["graph_nodes"], "graph_edges": frozen["graph_edges"],
                    "graph_paths": frozen["graph_paths"],
                }
                if reuse("compare", key, compare_input) != compared.model_dump(mode="json"):
                    raise CardAnalysisRuntimeError(RESUME_SOURCE_INVALID)
                if not item_isolation and stored_extract.rejected_units:
                    raise CardAnalysisRuntimeError(RESUME_SOURCE_INVALID)
                persist("extract", key, extract_payload, payload)
                persist("compare", key, compared.model_dump(mode="json"), compare_input)
                extract_items.extend(stored_extract.items)
                compare_items.extend(compared.items)
                rejected_units.extend(stored_extract.rejected_units)
                if rejected_units_exceed_limit(len(rejected_units), len(card_input.units)):
                    raise CardAnalysisRuntimeError(RESUME_SOURCE_INVALID)
                continue
            accept = None
            if extract_v2:
                def accept(output: Mapping[str, Any], _index: int = batch.batch_index) -> Mapping[str, Any]:
                    return assemble_requirement_extract_v2(
                        output, card_input=card_input, batch_index=_index, ontology=ontology,
                    )
            final_accept = None
            missing_ids: list[str] = []
            if missing_unit_isolation:
                def final_accept(output: Mapping[str, Any], _batch: Any = batch) -> Mapping[str, Any]:
                    # 결정 C16: only the answer to the final repair; extra/unknown/reordered
                    # ids or any other structure failure still raise (attempt failure).
                    assembled = assemble_requirement_extract_v2(
                        output, card_input=card_input, batch_index=_batch.batch_index, ontology=ontology,
                        allow_missing_units=True,
                    )
                    present = {item["unit_id"] for item in assembled["items"]}
                    missing_ids[:] = [unit_id for unit_id in _batch.unit_ids if unit_id not in present]
                    return assembled
            raw = invoke("extract", key, extract_contract, instructions["extract"], payload,
                         CARD_EXTRACT_INVALID, accept, final_accept)
            if missing_ids:
                extracted = validate_requirement_extract_isolated(
                    raw, card_input=card_input, batch_index=batch.batch_index, ontology=ontology,
                    missing_unit_ids=missing_ids, text_value_relaxed=text_value_relaxed,
                )
            else:
                validator = validate_requirement_extract_isolated if item_isolation else validate_requirement_extract
                extracted = validator(raw, card_input=card_input, batch_index=batch.batch_index, ontology=ontology,
                                      text_value_relaxed=text_value_relaxed)
            extract_payload = extracted.model_dump(mode="json")
            persist("extract", key, extract_payload, payload)
            compared = compare_requirements(extracted, frozen=frozen)
            compare_input = {
                "extract": extract_payload,
                "profile_facts": frozen["profile_facts"], "profile_evidence": frozen["profile_evidence"],
                "graph_nodes": frozen["graph_nodes"], "graph_edges": frozen["graph_edges"],
                "graph_paths": frozen["graph_paths"],
            }
            persist("compare", key, compared.model_dump(mode="json"), compare_input)
            extract_items.extend(extracted.items)
            compare_items.extend(compared.items)
            rejected_units.extend(extracted.rejected_units)
            if rejected_units_exceed_limit(len(rejected_units), len(card_input.units)):
                # 결정 B51: fail fast -- the validated rows stay for people, no verdict.
                raise CardAnalysisRuntimeError(CARD_EXTRACT_INVALID)

        from ..schemas.card_analysis import CardRequirementCompare

        extract = CardRequirementExtract(items=extract_items, rejected_units=rejected_units)
        compare = CardRequirementCompare(items=compare_items)
        rejected_ids = [row.unit_id for row in rejected_units]
        role_inputs = build_verdict_role_inputs(extract, compare)
        roles = {}
        for role in VERDICT_ROLES:
            role_input = role_inputs[role]
            payload = card_role_transfer(
                frozen, role=role, extract=role_input.extract.model_dump(mode="json"),
                compare=role_input.compare.model_dump(mode="json"), operational_values=operational,
                evidence_ids=role_ids, unit_refs=role_v3,
            )
            if resume is not None:
                stored_role = reuse("role", role, payload)
                result = (validate_isolated_verdict_role(stored_role, role_input=role_input) if role_ids
                          else validate_verdict_role(stored_role, role_input=role_input))
            elif role_v3:
                # 결정 C20: unit refs and evidence ids only; code maps both back (C16/C19 isolation).
                raw = invoke(role, role, ROLE_CONTRACT_V3, instructions[role], payload, CARD_ROLE_INVALID)
                result = validate_verdict_role_v3(raw, role_input=role_input)
            elif role_v2:
                # 결정 C16: ids only; code maps them back and isolates per item.
                raw = invoke(role, role, ROLE_CONTRACT_V2, instructions[role], payload, CARD_ROLE_INVALID)
                result = validate_verdict_role_v2(raw, role_input=role_input)
            else:
                raw = invoke(role, role, STAGE_CONTRACTS["role"], instructions[role], payload, CARD_ROLE_INVALID)
                result = validate_verdict_role(raw, role_input=role_input)
            persist("role", role, result.model_dump(mode="json"), payload)
            roles[role] = result
        if resume is not None:
            service._record_card_stages_reused(session, claim, source_attempt_id=resume.source_attempt_id,
                                               stages=reused)

        if card_input.missing_sections and card_input.selector.version == SELECTOR_VERSION:
            # card-sections-v1: partial analysis is kept; a final verdict is never
            # published without the six source sections (HP-03 "동결 입력과 unit").
            raise CardAnalysisRuntimeError(CARD_SOURCE_SELECTION_INCOMPLETE)
        # card-sections-v2/-v3/-v4 (결정 B23·B30·C15): synthesis continues and the missing
        # sections are recorded in the final row and cap the verdict.
        missing_sections = list(card_input.missing_sections)
        synthesis_input = build_synthesis_input(roles)
        synthesis_facts: list[str] = []
        for role in VERDICT_ROLES:
            for key in card_referenced_fact_keys(role_inputs[role].compare.model_dump(mode="json")):
                if key not in synthesis_facts:
                    synthesis_facts.append(key)
        payload = card_synthesis_transfer(
            frozen, roles=[row.model_dump(mode="json") for row in synthesis_input.roles],
            fact_keys=synthesis_facts, operational_values=operational,
            rejected_units=rejected_ids if item_isolation else None, unit_refs=synthesis_v3,
        )
        synthesis_accept = None
        #: 결정 C20: the records of v3 items whose ref/ids did not resolve (set by the accepted answer).
        synthesis_dropped: list[Any] = []
        if synthesis_v3:
            def synthesis_accept(output: Mapping[str, Any]) -> Mapping[str, Any]:
                # 결정 C20: the v3 output schema is the only repairable rule; the refs/ids are
                # resolved against the payload's own catalog (unresolved items dropped and
                # recorded, an invented owner fatal) -- never guessed.
                try:
                    validate_payload(output, PRACTITIONER_VERDICT_V3_SCHEMA)
                except SchemaValidationError:
                    raise CardExtractStructureError([OUTPUT_SCHEMA_RULE], []) from None
                mapped, records = synthesis_v1_from_v3(
                    output, synthesis_input=synthesis_input, extract=extract, compare=compare, allowed_owners=(),
                )
                synthesis_dropped[:] = records
                return mapped
        elif synthesis_v2:
            def synthesis_accept(output: Mapping[str, Any]) -> Mapping[str, Any]:
                # 결정 B55: the v2 output schema is the only repairable rule here
                # (the client checks it too); everything else is validated below.
                try:
                    validate_payload(output, PRACTITIONER_VERDICT_V2_SCHEMA)
                except SchemaValidationError:
                    raise CardExtractStructureError([OUTPUT_SCHEMA_RULE], []) from None
                return synthesis_v1_from_v2(output, extract=extract, compare=compare)
        raw = invoke("synthesis", "final", synthesis_contract, instructions["synthesis"], payload,
                     CARD_SYNTHESIS_INVALID, synthesis_accept)
        # 결정 C19: v10 drops (and records) synthesis items outside the role units/evidence;
        # the answer goes to assembly as given so the dropped items are recorded there.
        # 결정 C20: v11 items dropped while resolving refs/ids are recorded first (``pre_isolated``).
        verdict = (
            raw if synthesis_isolation else validate_practitioner_verdict(
                raw, synthesis_input=synthesis_input, extract=extract, compare=compare, allowed_owners=(),
                missing_sections=missing_sections, rejected_units=rejected_ids,
            )
        )
        assembled = assemble_practitioner_verdict(
            verdict, synthesis_input=synthesis_input, extract=extract, compare=compare, allowed_owners=(),
            missing_sections=missing_sections, rejected_units=rejected_ids,
            record_rejected_units=item_isolation, code_actions=synthesis_v2 or synthesis_v3,
            isolate_items=synthesis_isolation, pre_isolated=synthesis_dropped,
        )
        persist("synthesis", "final", assembled.model_dump(mode="json"), payload)
        finished = _monotonic()
        if finished >= deadline:
            raise CardAnalysisRuntimeError(CARD_REVIEW_TIMEOUT)
        elapsed = max(0.0, finished - started)
        completion_derivation = dict(derivation or {})
        if synthesis_v2 or synthesis_v3:
            completion_derivation.update({
                "synthesis_contract": PRACTITIONER_VERDICT_V3 if synthesis_v3 else PRACTITIONER_VERDICT_V2,
                "synthesis_code_derived_fields": list(CODE_DERIVED_SYNTHESIS_FIELDS),
            })
        if role_v2:
            completion_derivation["role_contract"] = ROLE_CONTRACT_V2_SCHEMA_VERSION
        elif role_v3:
            completion_derivation["role_contract"] = ROLE_CONTRACT_V3_SCHEMA_VERSION
        service._finish_card_claim(
            session, claim, batch_count=len(card_input.batches), call_count=calls[0],
            elapsed_seconds=elapsed, target_seconds=target_seconds, target_missed=elapsed > target_seconds,
            **({"extract_derivation": completion_derivation} if completion_derivation else {}),
            **({"resumed_from_attempt_id": resume.source_attempt_id} if resume is not None else {}),
        )
    except (CardAnalysisRuntimeError, StaleFenceError):
        raise
    except CardAnalysisValidationError as error:
        raise CardAnalysisRuntimeError(error.code) from None
    except CompanyAnalysisError as error:
        raise CardAnalysisRuntimeError(error.code) from None
    except CardAnalysisStageStoreError:
        raise CardAnalysisRuntimeError("processing_failed") from None
    finally:
        if owned_client:
            client.close()


__all__ = [
    "CARD_COMPARE_INVALID",
    "CARD_EXTRACT_INVALID",
    "CARD_FACT_ANCHORS",
    "CARD_FACT_KINDS",
    "CARD_REVIEW_TIMEOUT",
    "CARD_ROLE_INVALID",
    "CARD_SOURCE_SELECTION_INCOMPLETE",
    "CARD_SYNTHESIS_INVALID",
    "CODE_DERIVED_EXTRACT_FIELDS",
    "EXTRACT_CONTRACT_BY_STAGE_SCHEMA",
    "INPUT_BUDGET_EXCEEDED",
    "OUTPUT_SCHEMA_RULE",
    "REQUIREMENT_EXTRACT_V1",
    "REQUIREMENT_EXTRACT_V2",
    "UNIT_COVERAGE_RULE",
    "NEEDS_HUMAN_REVIEW_CODES",
    "PROMPT_CHARACTER_LIMIT",
    "PROMPT_REJECTED",
    "STAGE_CONTRACTS",
    "CardAnalysisRuntimeError",
    "CardAnalysisStageStoreError",
    "CardAnalysisValidationError",
    "CONCEPT_RULE",
    "CONSTRAINT_EXPRESSION_RULE",
    "CONSTRAINT_FACT_KEY_RULE",
    "CONSTRAINT_NOT_UNIQUE_RULE",
    "CONSTRAINT_QUOTE_RULE",
    "CONSTRAINT_TRUNCATED_RULE",
    "EVIDENCE_QUOTE_RULE",
    "EXTRACT_MISSING_UNIT_POLICY_IDENTITIES",
    "EXTRACT_UNIT_MISSING_RULE",
    "ITEM_ISOLATION_POLICY_IDENTITIES",
    "ROLE_CONTRACT_V2",
    "ROLE_CONTRACT_V2_POLICY_IDENTITIES",
    "ROLE_CONTRACT_V2_SCHEMA_VERSION",
    "ROLE_CONTRACT_V3",
    "ROLE_CONTRACT_V3_POLICY_IDENTITIES",
    "ROLE_CONTRACT_V3_SCHEMA_VERSION",
    "SYNTHESIS_ITEM_ISOLATION_POLICY_IDENTITIES",
    "TEXT_VALUE_COMPARED_FACT_KEYS",
    "TEXT_VALUE_RELAXED_POLICY_IDENTITIES",
    "REQUIREMENT_NUMBER_RULE",
    "CODE_DERIVED_SYNTHESIS_FIELDS",
    "PRACTITIONER_VERDICT_V1",
    "PRACTITIONER_VERDICT_V2",
    "PRACTITIONER_VERDICT_V3",
    "RESUME_IDENTITY_KEYS",
    "RESUME_POLICY_FREE_KEYS",
    "RESUME_SOURCE_INVALID",
    "SYNTHESIS_CONTRACT_BY_REPORT_SCHEMA",
    "CardResume",
    "CardConstraintQuoteNotUniqueError",
    "CardConstraintQuoteTruncatedError",
    "CardExtractStructureError",
    "amount_atoms",
    "assemble_requirement_extract_v2",
    "canonical_card_stage_payload",
    "decimal_value",
    "constraint_quote_checked",
    "constraint_quote_occurrences",
    "constraint_quote_truncated",
    "expected_constraint_operator",
    "extract_item_violations",
    "rejected_units_exceed_limit",
    "resume_content_sha256",
    "resume_lineage_valid",
    "validate_requirement_extract_isolated",
    "fact_anchor_matches",
    "normalized_anchor_text",
    "resolve_fact_key",
    "run_card_analysis",
    "source_numbers",
    "stage_prompt",
    "store_card_analysis_stage",
    "validate_requirement_extract",
]
