"""RL-03 deterministic compare of validated extract rows against the frozen Rootlab input.

HP-03 compare rules (spec "단계 wire 계약" 코드 대조) with the RL allowlist:

* company values are read **only** through ``card_fact_value`` and the
  ``CARD_COMPARE_FACT_PATHS`` (fact_key, value path) pairs -- never a scalar
  guess, a sum of other nodes, or a fact outside the list (``unmapped``);
* ``proposed`` facts are not evidence: reason ``proposed_fact`` (unknown);
  ``unknown``/``inferred``/missing facts and null values are ``unknown_fact``;
* only a ``confirmed`` contradiction is ``gap``; ``unknown`` never becomes
  gap ("부족"); a whole unit is ``met`` only when every atom is a confirmed
  match and nothing is left unknown, unmapped, partial or out of scope;
* ``계약`` units stay ``unknown`` (``contract_unaccepted``).

Two rule sets exist (``rules``).  ``card-compare-v1`` is every policy up to v11 and
is unchanged.  ``card-compare-v2`` (RL-10, policy v12, 결정 E1~E4) adds the blocker
rules on top of v1:

* 상주 장소: in a constraint whose quote carries the 상주 anchor, the places named
  in the on-site clauses of its cited block are resolved to 시·도 through the
  versioned place table (``card-compare-places-kr-v1.json``, administrative names
  only).  An unresolvable or ambiguous place is ``place_unresolved``.  ``gap`` only
  when the confirmed ``pref:onsite_cap.params.onsite_regions`` (the complete list
  of on-site regions) shares no region with the required ones; role/scope words do
  not pre-empt this comparison.  A contradiction found this way is decisive for any
  constraint whose quote carries 상주, even one with several anchors;
* 제외 분야: a constraint whose quote carries a ``requirement_terms`` entry of a
  confirmed ``excl:<hardware|election>`` fact is ``gap`` only when every clause of
  its cited source context carries such a term, otherwise ``exclusion_partial``;
  terms come from the company source, never from code.  A unit whose source holds
  such a term that no constraint quotes is incomplete;
* a confirmed contradiction decides ``gap`` before the ``계약`` rule (a 계약 unit is
  still never ``met``).

The compare runs locally on the frozen input; no model call and no value is
sent anywhere from here.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from pydantic import ValidationError

from ...core.company_ontology import ORIGINS, REQUIREMENT_LEVEL_EXCLUSION_KINDS
from ..schemas.card_analysis import (
    CardAnalysisUnit,
    CardConstraintResult,
    CardRequirementCompare,
    CardRequirementCompareItem,
    CardRequirementConstraint,
    CardRequirementExtract,
    CardRequirementExtractItem,
)
from .card_analysis import (
    CARD_COMPARE_INVALID,
    CARD_FACT_ANCHORS,
    CARD_FACT_KINDS,
    CardAnalysisValidationError,
    amount_atoms,
    card_input_of,
    decimal_value,
    fact_anchor_matches,
    normalized_anchor_text,
    resolve_fact_key,
)
from .company_analysis_input import (
    CARD_COMPARE_FACT_PATHS,
    CARD_EXCLUSION_FACT_PREFIX,
    CompanyAnalysisError,
    card_blocker_fact_value,
    card_fact_value,
)


#: Compare rule sets (RL-10 결정 E1).  v1 = policies v1..v11 (unchanged); v2 = policy v12.
COMPARE_RULES_V1: Final[str] = "card-compare-v1"
COMPARE_RULES_V2: Final[str] = "card-compare-v2"
COMPARE_RULES: Final[frozenset[str]] = frozenset({COMPARE_RULES_V1, COMPARE_RULES_V2})
#: Reason codes only ``card-compare-v2`` emits (both are ``unknown``).
COMPARE_V2_ONLY_REASONS: Final[frozenset[str]] = frozenset({"place_unresolved", "exclusion_partial"})
#: The versioned place table of ``card-compare-v2`` (immutable; a change is a new file + version).
PLACE_TABLE_FILE: Final[Path] = Path(__file__).resolve().parents[1] / "policies" / "card-compare-places-kr-v1.json"
PLACE_TABLE_VERSION: Final[str] = "card-compare-places-kr-v1"
PLACE_TABLE_SHA256: Final[str] = "03cb66d02e61168be8bf1378b013562c89a2b4ffcdeebc74e57e7d3d7e32b227"


_REASON_ORDER: Final[tuple[str, ...]] = (
    "confirmed_contradiction",
    "unknown_fact",
    "proposed_fact",
    "partial_path",
    "unmapped",
    "unsupported_comparison",
    "scope_unverified",
    "place_unresolved",
    "exclusion_partial",
    "contract_unaccepted",
    "incomplete_unit",
    "confirmed_match",
)
#: 결정 B51: the only reason of a rejected unit's compare row (``unknown``, no facts).
EXTRACT_REJECTED_REASON: Final[str] = "extract_rejected"


def rejected_compare_row(unit_id: str) -> CardRequirementCompareItem:
    """The fixed compare row of a unit whose extract item was rejected (결정 B51)."""

    return CardRequirementCompareItem(
        unit_id=unit_id, fit_status="unknown", constraint_results=[], evidence_ids=[],
        reason_codes=[EXTRACT_REJECTED_REASON],
    )


def _compare_unit_order(result_ids: Sequence[str], parsed_extract: CardRequirementExtract) -> bool:
    """Compare rows = the extract items plus the rejected units, each once, items in their order."""

    rejected = {row.unit_id for row in parsed_extract.rejected_units}
    accepted = [unit_id for unit_id in result_ids if unit_id not in rejected]
    return (
        accepted == [row.unit_id for row in parsed_extract.items]
        and len(result_ids) == len(set(result_ids))
        and set(result_ids) - set(accepted) == rejected
    )
_STATUS_BY_REASON: Final[dict[str, str]] = {
    "confirmed_match": "met",
    "confirmed_contradiction": "gap",
}
_SCOPE_TERMS: Final[tuple[str, ...]] = (
    "최근", "회계연도", "유효기간", "기준일", "현재가용", "착수일", "종료일포함",
)
_ROLE_TERMS: Final[tuple[str, ...]] = (
    "PM", "사업관리자", "프로젝트관리자", "개발자", "기술자", "디자이너", "특정역할",
)
_STAFF_COUNT_FACTS: Final[dict[str, tuple[str, ...]]] = {
    "staff:onsite": ("available",),
    "staff:total": ("total",),
    "staff:design_publishing": ("available",),
}
_HELD_FACTS: Final[frozenset[str]] = frozenset({
    "qual:procurement_1468", "qual:sme_certificate", "qual:sw_business",
})
#: 시·도 이름과 표기 (지역 비교는 이 표에 있는 이름끼리만 한다).
_REGIONS: Final[dict[str, tuple[str, ...]]] = {
    "서울": ("서울",), "부산": ("부산",), "대구": ("대구",), "인천": ("인천",), "광주": ("광주",),
    "대전": ("대전",), "울산": ("울산",), "세종": ("세종",), "경기": ("경기",), "강원": ("강원",),
    "충북": ("충북", "충청북도"), "충남": ("충남", "충청남도"), "전북": ("전북", "전라북도"),
    "전남": ("전남", "전라남도"), "경북": ("경북", "경상북도"), "경남": ("경남", "경상남도"),
    "제주": ("제주",),
}
_MAIN_OFFICE_TERMS: Final[tuple[str, ...]] = ("본점", "주된영업소", "법인등기")


def _invalid() -> CardAnalysisValidationError:
    return CardAnalysisValidationError(CARD_COMPARE_INVALID)


def _regions(text: Any) -> set[str]:
    if not isinstance(text, str):
        return set()
    normalized = normalized_anchor_text(text)
    return {name for name, forms in _REGIONS.items() if any(form in normalized for form in forms)}


def _main_office_regions(detail: str) -> set[str]:
    """Regions of the ``(본점)`` token of a branch detail such as ``대구(본점), 세종``."""

    return {
        region
        for token in re.split(r"[,，/·]", detail)
        if "본점" in token
        for region in _regions(token)
    }


def _scope_unverified(fact_key: str, constraint: CardRequirementConstraint) -> bool:
    normalized = normalized_anchor_text(constraint.quote)
    if any(normalized_anchor_text(term) in normalized for term in _SCOPE_TERMS):
        return True
    return fact_key in {"staff:onsite", "staff:total"} and any(
        normalized_anchor_text(term) in normalized for term in _ROLE_TERMS
    )


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return decimal_value(value, CARD_COMPARE_INVALID)


def _read(frozen: Mapping[str, Any], fact_key: str, path: tuple[str, ...]) -> Any:
    try:
        return card_fact_value(frozen, fact_key, path)
    except CompanyAnalysisError:
        raise _invalid() from None


def _confirmed_comparison(
    fact_key: str,
    constraint: CardRequirementConstraint,
    frozen: Mapping[str, Any],
) -> tuple[str, str]:
    """(status, reason) for a constraint whose fact is ``confirmed`` (not null at the primary path)."""

    met, gap = ("met", "confirmed_match"), ("gap", "confirmed_contradiction")
    unknown = lambda reason: ("unknown", reason)  # noqa: E731
    kind = constraint.kind
    if fact_key in _STAFF_COUNT_FACTS and kind == "count":
        if constraint.unit != "person":
            return unknown("unsupported_comparison")
        reading = _read(frozen, fact_key, _STAFF_COUNT_FACTS[fact_key])
        if reading.state != "confirmed":
            return unknown("unknown_fact")
        available = _number(reading.value)
        if available is None:
            return unknown("unsupported_comparison")
        if constraint.operator not in {"eq", "gte"}:
            # "n명 이하" limits the bid, not the company's capacity.
            return unknown("unsupported_comparison")
        return met if available >= decimal_value(constraint.value, CARD_COMPARE_INVALID) else gap
    if fact_key == "staff:onsite" and kind == "text":
        reading = _read(frozen, fact_key, ("region",))
        if reading.state != "confirmed":
            return unknown("unknown_fact")
        required = _regions(constraint.value) or _regions(constraint.quote)
        if not required:
            return unknown("unsupported_comparison")
        return met if required <= _regions(reading.value) else unknown("scope_unverified")
    if fact_key in _HELD_FACTS:
        if kind == "boolean" and constraint.value is not True:
            return unknown("unsupported_comparison")
        held = _read(frozen, fact_key, ("held",))
        if held.state != "confirmed" or not isinstance(held.value, bool):
            return unknown("unknown_fact")
        return met if held.value else gap
    if fact_key == "qual:sanction_free":
        # held=true means "no sanction"; the requirement is always "not sanctioned".
        held = _read(frozen, fact_key, ("held",))
        if held.state != "confirmed" or not isinstance(held.value, bool):
            return unknown("unknown_fact")
        return met if held.value else gap
    if fact_key == "qual:direct_production":
        held = _read(frozen, fact_key, ("held",))
        if held.state == "confirmed" and held.value is False:
            return gap
        detail = _read(frozen, fact_key, ("detail",))
        if detail.state != "confirmed" or not isinstance(detail.value, str):
            return unknown("unknown_fact")  # item names unknown → cannot compare
        if kind == "text" and normalized_anchor_text(str(constraint.value)) in normalized_anchor_text(detail.value):
            return met
        return unknown("scope_unverified")
    if fact_key == "qual:credit_rating":
        return unknown("unsupported_comparison")  # grade ordering is not a deterministic comparison
    if fact_key == "qual:infosec_cert":
        detail = _read(frozen, fact_key, ("detail",))
        if detail.state != "confirmed" or not isinstance(detail.value, str):
            return unknown("unknown_fact")  # ISMS / ISMS-P cannot be told apart
        quote = normalized_anchor_text(constraint.quote)
        held = normalized_anchor_text(detail.value)
        if re.search(r"ISMS-?P(?![A-Z0-9])", quote):
            return met if re.search(r"ISMS-?P(?![A-Z0-9])", held) else unknown("scope_unverified")
        if re.search(r"(?<![A-Z0-9])ISMS(?!-?P(?:[^A-Z0-9]|$))", quote):
            return met if re.search(r"(?<![A-Z0-9])ISMS(?!-?P(?:[^A-Z0-9]|$))", held) else unknown("scope_unverified")
        return unknown("scope_unverified")
    if fact_key == "qual:branch":
        detail = _read(frozen, fact_key, ("detail",))
        if detail.state != "confirmed" or not isinstance(detail.value, str):
            return unknown("unknown_fact")
        required = _regions(constraint.value) or _regions(constraint.quote)
        if not required:
            return unknown("unsupported_comparison")
        quote = normalized_anchor_text(constraint.quote)
        if any(term in quote for term in _MAIN_OFFICE_TERMS):
            main = _main_office_regions(detail.value)
            if not main:
                return unknown("unknown_fact")
            return met if required & main else gap
        return met if required & _regions(detail.value) else unknown("scope_unverified")
    if fact_key == "pref:solo_cap" and kind == "amount":
        reading = _read(frozen, fact_key, ("params", "krw"))
        if reading.state != "confirmed":
            return unknown("unknown_fact")
        cap = _number(reading.value)
        if cap is None or constraint.operator not in {"eq", "lte"}:
            return unknown("unsupported_comparison")
        return met if decimal_value(constraint.value, CARD_COMPARE_INVALID) <= cap else gap
    if fact_key == "pref:subcontract":
        if kind == "boolean" and constraint.value is True:
            reading = _read(frozen, fact_key, ("params", "allowed"))
            if reading.state != "confirmed" or not isinstance(reading.value, bool):
                return unknown("unknown_fact")
            return met if reading.value else gap
        return unknown("scope_unverified")  # a ban or a ratio is the company's choice, not a capability
    return unknown("unsupported_comparison")  # pref:consortium and unsupported kinds


def _primary_path(fact_key: str, constraint: CardRequirementConstraint) -> tuple[str, ...]:
    if fact_key == "staff:onsite" and constraint.kind == "text":
        return ("region",)
    return CARD_COMPARE_FACT_PATHS[fact_key][0]


def constraint_comparison(
    constraint: CardRequirementConstraint,
    frozen: Mapping[str, Any],
    known_facts: set[str],
    *,
    rules: str = COMPARE_RULES_V1,
    block_text: str | None = None,
) -> tuple[str, str, list[str]]:
    """(status, reason_code, fact_ids) of one validated constraint.

    ``rules`` selects the rule set (``card-compare-v1`` unless the pinned policy is
    v12); ``block_text`` is the cited block of the constraint (v2 reads the source
    clause around the quote; without it the quote alone is the context).
    """

    if rules == COMPARE_RULES_V1:
        return _constraint_comparison_v1(constraint, frozen, known_facts)
    if rules == COMPARE_RULES_V2:
        return _constraint_comparison_v2(constraint, frozen, known_facts, block_text)
    raise _invalid()


def _constraint_comparison_v1(
    constraint: CardRequirementConstraint,
    frozen: Mapping[str, Any],
    known_facts: set[str],
) -> tuple[str, str, list[str]]:
    if constraint.operator == "unknown":
        return "unknown", "unsupported_comparison", []
    fact_key = resolve_fact_key(constraint)
    if fact_key is None:
        return "unknown", "unmapped", []
    if fact_key not in CARD_FACT_ANCHORS or not fact_anchor_matches(fact_key, constraint.quote):
        raise _invalid()
    fact_ids = [fact_key] if fact_key in known_facts else []
    if constraint.kind not in CARD_FACT_KINDS[fact_key]:
        return "unknown", "unsupported_comparison", fact_ids
    reading = _read(frozen, fact_key, _primary_path(fact_key, constraint))
    if reading.state == "proposed":
        return "unknown", "proposed_fact", fact_ids
    if reading.state in {"absent", "unknown", "inferred"}:
        return "unknown", "unknown_fact", fact_ids
    if reading.state not in {"confirmed", "null"}:
        raise _invalid()
    if _scope_unverified(fact_key, constraint):
        return "unknown", "scope_unverified", fact_ids
    status, reason = _confirmed_comparison(fact_key, constraint, frozen)
    return status, reason, fact_ids


# --- card-compare-v2 (RL-10, policy v12): place table and source clauses ---------------


@dataclass(frozen=True)
class _PlaceTable:
    pattern: re.Pattern[str]
    region_by_form: Mapping[str, str | None]  # None: the name belongs to more than one 시·도
    bare_forms: frozenset[str]
    bare_followers: frozenset[str]
    not_followed_by: Mapping[str, frozenset[str]]


_HANGUL_SYLLABLE = re.compile(r"[가-힣]")


@lru_cache(maxsize=1)
def _place_table() -> _PlaceTable:
    """Load the pinned place table; a changed file is never read (``card_compare_invalid``)."""

    try:
        raw = PLACE_TABLE_FILE.read_bytes()
    except OSError:
        raise _invalid() from None
    if hashlib.sha256(raw).hexdigest() != PLACE_TABLE_SHA256:
        raise _invalid()
    value = json.loads(raw)
    if value.get("version") != PLACE_TABLE_VERSION or value.get("schema_version") != "bidops.card-compare-places.v1":
        raise _invalid()
    regions_by_form: dict[str, set[str]] = {}
    bare: set[str] = set()
    for region, row in value["provinces"].items():
        for form in (*row["forms"], *row["divisions"]):
            regions_by_form.setdefault(form, set()).add(region)
        for form in row["bare"]:
            regions_by_form.setdefault(form, set()).add(region)
            bare.add(form)
    forms = sorted(regions_by_form, key=lambda form: (-len(form), form))
    return _PlaceTable(
        pattern=re.compile(r"(?<![가-힣])(" + "|".join(re.escape(form) for form in forms) + ")"),
        region_by_form={
            form: next(iter(regions)) if len(regions) == 1 else None for form, regions in regions_by_form.items()
        },
        bare_forms=frozenset(bare),
        bare_followers=frozenset(value["bare_followers"]),
        not_followed_by={suffix: frozenset(chars) for suffix, chars in value["not_followed_by"].items()},
    )


def resolve_places(text: Any) -> tuple[set[str], bool]:
    """(시·도 names, ambiguous name seen) of the administrative place names in ``text``.

    A name matches only at a left word boundary (no Hangul syllable before it).  A
    bare 시·도 name (``서울``) needs the end, a non-Hangul character or a listed
    particle after it; a 시/구 name followed by a guard character (``상주시켜``,
    ``…구간``) is not a place.  A name listed under two 시·도 (``중구``, ``고성군``,
    ``광주시``) is ambiguous and resolves nothing.  Nothing is guessed.
    """

    if not isinstance(text, str) or not text:
        return set(), False
    table = _place_table()
    normalized = unicodedata.normalize("NFKC", text)
    regions: set[str] = set()
    ambiguous = False
    for match in table.pattern.finditer(normalized):
        form = match.group(1)
        follower = normalized[match.end():match.end() + 1]
        if form in table.bare_forms:
            if follower and _HANGUL_SYLLABLE.fullmatch(follower) and follower not in table.bare_followers:
                continue
        elif follower in table.not_followed_by.get(form[-1], frozenset()):
            continue
        region = table.region_by_form[form]
        if region is None:
            ambiguous = True
        else:
            regions.add(region)
    return regions, ambiguous


def _region_list(value: Any) -> set[str] | None:
    """The 시·도 set of a company region list such as ``"대구, 세종"`` (None: not resolvable)."""

    if not isinstance(value, str):
        return None
    tokens = [token.strip() for token in re.split(r"[,，/·]", value)]
    if not tokens or any(not token for token in tokens):
        return None
    table = _place_table()
    result: set[str] = set()
    for token in tokens:
        # each entry is exactly one listed name ("대구", "경상북도"), never a phrase around one
        region = table.region_by_form.get(unicodedata.normalize("NFKC", token))
        if region is None:
            return None
        result.add(region)
    return result


#: Clause boundaries of a source block: line breaks, list marks, sentence ends, `` - ``
#: bullets and numbered items (``1)``, ``가)``).
_CLAUSE_BREAK = re.compile(
    r"[\n\r○●◎◦•▪□■※;]"
    r"|(?<=[다함음임])\.(?=\s|$)"
    r"|(?<=\s)-(?=\s)"
    r"|(?<![0-9])(?=[0-9]{1,2}\))"
    r"|(?<=\s)(?=[가나다라마바사아자차카타파하]\)\s)"
)
#: Coordinated parts of one clause (coverage of an excluded field is checked per part).
_SUBCLAUSE_BREAK = re.compile(r"\s*(?:및|그리고|,|，|、)\s*")
_CONTENT = re.compile(r"[가-힣A-Za-z]")


def _clause_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _CLAUSE_BREAK.finditer(text):
        if match.start() > start:
            spans.append((start, match.start()))
        start = max(start, match.end())
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _source_context(quote: str, block_text: str | None) -> list[str]:
    """The clauses of the cited block that overlap any occurrence of the quote (else the quote's own clauses)."""

    text = block_text if isinstance(block_text, str) and quote in block_text else quote
    spans = _clause_spans(text)
    occurrences = [match.start() for match in re.finditer(re.escape(quote), text)] or [0]
    selected: list[tuple[int, int]] = []
    for start in occurrences:
        end = start + len(quote)
        selected.extend(span for span in spans if span[0] < end and start < span[1] and span not in selected)
    return [text[a:b] for a, b in sorted(selected)]


def _onsite_anchored(text: str) -> bool:
    return "상주" in normalized_anchor_text(text).replace("비상주", "")


def _known(keys: Sequence[str], known_facts: set[str]) -> list[str]:
    return [key for key in keys if key in known_facts]


def _onsite_location(
    constraint: CardRequirementConstraint,
    frozen: Mapping[str, Any],
    known_facts: set[str],
    block_text: str | None,
) -> tuple[str, str, list[str]] | None:
    """The on-site place comparison of one constraint (None: its quote carries no 상주).

    Required regions are the places of the on-site clauses of the source context;
    ``met`` when they lie in the confirmed ``staff:onsite.region``; ``gap`` when the
    confirmed complete list ``pref:onsite_cap.params.onsite_regions`` shares none of
    them.  Role and scope words are not consulted: the place is the place.
    """

    if not _onsite_anchored(constraint.quote):
        return None
    ids = _known(("staff:onsite",), known_facts)
    unknown = lambda reason, facts=ids: ("unknown", reason, facts)  # noqa: E731
    region = _read(frozen, "staff:onsite", ("region",))
    if region.state == "proposed":
        return unknown("proposed_fact")
    if region.state != "confirmed":
        return unknown("unknown_fact")
    required: set[str] = set()
    for clause in _source_context(constraint.quote, block_text):
        if not _onsite_anchored(clause):
            continue
        regions, ambiguous = resolve_places(clause)
        if ambiguous and not regions:
            return unknown("place_unresolved")
        required |= regions
    if not required:
        return unknown("place_unresolved")
    if required <= resolve_places(region.value)[0]:
        return "met", "confirmed_match", ids
    cap_ids = _known(("staff:onsite", "pref:onsite_cap"), known_facts)
    try:
        cap = card_blocker_fact_value(frozen, "pref:onsite_cap", ("params", "onsite_regions"))
    except CompanyAnalysisError:
        raise _invalid() from None
    if cap.state == "proposed":
        return unknown("proposed_fact", cap_ids)
    if cap.state != "confirmed":
        return unknown("unknown_fact", cap_ids)
    allowed = _region_list(cap.value)
    if allowed is None:
        return unknown("unsupported_comparison", cap_ids)
    if not required & allowed:
        return "gap", "confirmed_contradiction", cap_ids
    return unknown("scope_unverified", cap_ids)


def _confirmed_exclusions(frozen: Mapping[str, Any]) -> list[tuple[str, tuple[str, ...]]]:
    """``(fact_key, normalized requirement terms)`` of every usable confirmed exclusion.

    Usable: ``excl:<kind>`` with confirmed ``excluded=true``, a requirement-level
    ``kind`` (``hardware``·``election``) equal to the key, and a confirmed non-empty
    ``requirement_terms`` list.  Anything else (proposed, unknown, no terms) is not
    read and links nothing.
    """

    result: list[tuple[str, tuple[str, ...]]] = []
    try:
        for row in frozen.get("profile_facts", []):
            key = row.get("fact_key") if isinstance(row, Mapping) else None
            if not isinstance(key, str) or not key.startswith(CARD_EXCLUSION_FACT_PREFIX):
                continue
            excluded = card_blocker_fact_value(frozen, key, ("excluded",))
            kind = card_blocker_fact_value(frozen, key, ("kind",))
            terms = card_blocker_fact_value(frozen, key, ("requirement_terms",))
            if (
                excluded.state != "confirmed" or excluded.value is not True
                or kind.state != "confirmed" or kind.value not in REQUIREMENT_LEVEL_EXCLUSION_KINDS
                or key != f"{CARD_EXCLUSION_FACT_PREFIX}{kind.value}"
                or terms.state != "confirmed" or not isinstance(terms.value, list) or not terms.value
                or any(not isinstance(term, str) for term in terms.value)
            ):
                continue
            normalized = tuple(normalized_anchor_text(term) for term in terms.value)
            if any(len(term) < 2 for term in normalized):
                continue
            result.append((key, normalized))
    except CompanyAnalysisError:
        raise _invalid() from None
    return result


def _exclusion_comparison(
    constraint: CardRequirementConstraint,
    exclusions: Sequence[tuple[str, tuple[str, ...]]],
    known_facts: set[str],
    block_text: str | None,
) -> tuple[str, str, list[str]] | None:
    """Excluded-field comparison of one constraint (None: its quote carries no term).

    ``gap`` only when every coordinated part of every clause of the source context
    carries a term of a confirmed excluded field; otherwise ``exclusion_partial``.
    """

    quote = normalized_anchor_text(constraint.quote)
    hit = [(key, terms) for key, terms in exclusions if any(term in quote for term in terms)]
    if not hit:
        return None
    ids = _known([key for key, _terms in hit], known_facts)
    terms = [term for _key, row in hit for term in row]
    parts = [
        normalized_anchor_text(part)
        for clause in _source_context(constraint.quote, block_text)
        for part in _SUBCLAUSE_BREAK.split(clause)
    ]
    parts = [part for part in parts if _CONTENT.search(part)]
    if parts and all(any(term in part for term in terms) for part in parts):
        return "gap", "confirmed_contradiction", ids
    return "unknown", "exclusion_partial", ids


def _constraint_comparison_v2(
    constraint: CardRequirementConstraint,
    frozen: Mapping[str, Any],
    known_facts: set[str],
    block_text: str | None,
) -> tuple[str, str, list[str]]:
    if constraint.operator == "unknown":
        return "unknown", "unsupported_comparison", []
    fact_key = resolve_fact_key(constraint)
    if fact_key is not None and (fact_key not in CARD_FACT_ANCHORS or not fact_anchor_matches(fact_key, constraint.quote)):
        raise _invalid()
    if fact_key == "staff:onsite" and constraint.kind == "text":
        # 결정 E3: the place comparison is not pre-empted by role/scope words.
        result = _onsite_location(constraint, frozen, known_facts, block_text) or (
            "unknown", "place_unresolved", _known(("staff:onsite",), known_facts))
    else:
        result = (
            _constraint_comparison_v1(constraint, frozen, known_facts) if fact_key is not None
            else ("unknown", "unmapped", [])
        )
        if result[0] != "gap":
            # 결정 E3: a contradiction in an on-site clause decides even a count or a
            # several-anchor constraint; anything short of a contradiction keeps the v1 result.
            location = _onsite_location(constraint, frozen, known_facts, block_text)
            if location is not None and location[0] == "gap":
                result = location
    if result[0] != "gap":
        exclusion = _exclusion_comparison(constraint, _confirmed_exclusions(frozen), known_facts, block_text)
        if exclusion is not None:
            result = exclusion  # a touched excluded field never lets the atom be met
    return result


def _profile_evidence_index(profile_evidence: Sequence[Mapping[str, Any]]) -> tuple[dict[str, list[UUID]], set[UUID]]:
    by_fact: dict[str, list[UUID]] = {}
    all_ids: set[UUID] = set()
    for row in profile_evidence:
        if not isinstance(row, Mapping) or row.get("origin") not in ORIGINS:
            raise _invalid()
        try:
            evidence_id = UUID(str(row["profile_evidence_id"]))
        except (KeyError, TypeError, ValueError):
            raise _invalid() from None
        fact_key = row.get("fact_key")
        if not isinstance(fact_key, str) or not fact_key or evidence_id in all_ids:
            raise _invalid()
        all_ids.add(evidence_id)
        by_fact.setdefault(fact_key, []).append(evidence_id)
    return by_fact, all_ids


_STATUSES: Final[frozenset[str]] = frozenset({"confirmed", "proposed", "inferred", "unknown"})


def _validated_graph_context(
    graph_paths: Sequence[Mapping[str, Any]],
    graph_nodes: Sequence[Mapping[str, Any]],
    graph_edges: Sequence[Mapping[str, Any]],
    evidence_ids: set[UUID],
) -> tuple[list[dict[str, Any]], dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    nodes: dict[str, Mapping[str, Any]] = {}
    edges: dict[str, Mapping[str, Any]] = {}
    for raw in graph_nodes:
        if not isinstance(raw, Mapping) or raw.get("origin") not in ORIGINS:
            raise _invalid()
        node_id = raw.get("id")
        if not isinstance(node_id, str) or not node_id or node_id in nodes or raw.get("status") not in _STATUSES:
            raise _invalid()
        nodes[node_id] = raw
    for raw in graph_edges:
        if not isinstance(raw, Mapping) or raw.get("origin") not in ORIGINS:
            raise _invalid()
        edge_id = raw.get("id")
        if not isinstance(edge_id, str) or not edge_id or edge_id in edges or raw.get("status") not in _STATUSES:
            raise _invalid()
        if raw.get("from_id") not in nodes or raw.get("to_id") not in nodes:
            raise _invalid()
        edges[edge_id] = raw
    paths: list[dict[str, Any]] = []
    for raw in graph_paths:
        if not isinstance(raw, Mapping) or set(raw) != {
            "requirement_id", "node_ids", "edge_ids", "profile_evidence_ids", "relation",
        }:
            raise _invalid()
        if raw["relation"] not in {"direct", "partial", "unmapped"}:
            raise _invalid()
        if not isinstance(raw["requirement_id"], str) or not raw["requirement_id"]:
            raise _invalid()
        if not isinstance(raw["node_ids"], list) or not isinstance(raw["edge_ids"], list):
            raise _invalid()
        if any(node_id not in nodes for node_id in raw["node_ids"]) or any(
            edge_id not in edges for edge_id in raw["edge_ids"]
        ):
            raise _invalid()
        try:
            path_evidence = [UUID(str(value)) for value in raw["profile_evidence_ids"]]
        except (TypeError, ValueError):
            raise _invalid() from None
        if len(path_evidence) != len(set(path_evidence)) or not set(path_evidence) <= evidence_ids:
            raise _invalid()
        if raw["relation"] == "unmapped" and (raw["node_ids"] or raw["edge_ids"] or path_evidence):
            raise _invalid()
        if raw["relation"] != "unmapped" and (
            len(raw["node_ids"]) != len(raw["edge_ids"]) + 1
            or len(raw["node_ids"]) != len(set(raw["node_ids"]))
            or any(
                edges[edge_id].get("from_id") != raw["node_ids"][index]
                or edges[edge_id].get("to_id") != raw["node_ids"][index + 1]
                for index, edge_id in enumerate(raw["edge_ids"])
            )
        ):
            raise _invalid()
        paths.append(dict(raw) | {"profile_evidence_ids": path_evidence})
    return paths, nodes, edges


def _concept_reasons(
    item: CardRequirementExtractItem,
    paths: Sequence[Mapping[str, Any]],
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Mapping[str, Mapping[str, Any]],
    constrained_facts: set[str],
) -> list[str]:
    """Concept candidates never prove a requirement on their own in RL.

    A direct path to an allowlisted fact defers to that fact's constraint
    comparison (no extra reason when such a constraint exists, otherwise the
    fact status: ``proposed_fact`` / ``unknown_fact`` / ``scope_unverified``).
    A direct path to a node outside the allowlist is refused (``unmapped``);
    a partial path is ``partial_path``.
    """

    reasons: list[str] = []
    owned = [path for path in paths if path["requirement_id"] == item.unit_id]
    for candidate in item.concept_candidates:
        if candidate.concept_id is None:
            reasons.append("unmapped")
            continue
        matched = [
            path for path in owned
            if any(nodes[node_id].get("concept_id") == candidate.concept_id for node_id in path["node_ids"])
        ]
        direct_targets = [path["node_ids"][-1] for path in matched if path["relation"] == "direct"]
        allowlisted = [target for target in direct_targets if target in CARD_COMPARE_FACT_PATHS]
        if allowlisted:
            for target in allowlisted:
                if target in constrained_facts:
                    continue
                status = nodes[target].get("status")
                reasons.append(
                    "proposed_fact" if status == "proposed"
                    else "scope_unverified" if status == "confirmed"
                    else "unknown_fact"
                )
        elif any(path["relation"] == "partial" for path in matched):
            reasons.append("partial_path")
        else:
            reasons.append("unmapped")
    return reasons


def _scalar_atom_signatures(text: str) -> list[tuple[str, str, str | None]]:
    """Explicit scalar atoms only (lexical); ambiguity keeps the unit incomplete."""

    number = r"(?P<value>[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"
    signatures: list[tuple[str, str, str | None]] = []
    occupied: list[tuple[int, int]] = []
    for match in re.finditer(rf"(?<![0-9.]){number}\s*(?P<unit>억원|백만원|천원|원)", text):
        signatures.append(("amount", str(amount_atoms(match.group(0))[0].normalize()), "KRW"))
        occupied.append(match.span())
    for pattern, kind, unit in (
        (rf"(?<![0-9.]){number}\s*%", "percentage", "percent"),
        (rf"(?<![0-9.]){number}\s*명", "count", "person"),
        (rf"(?<![0-9.]){number}\s*건", "count", None),
    ):
        for match in re.finditer(pattern, text):
            value = Decimal(match.group("value").replace(",", ""))
            signatures.append((kind, str(value.normalize()), unit))
            occupied.append(match.span())
    duration_units = {"개월": "month", "월": "month", "일": "day", "년": "year"}
    for match in re.finditer(rf"(?<![0-9.]){number}\s*(?P<unit>개월|월|일|년)", text):
        if any(start <= match.start() and match.end() <= end for start, end in occupied):
            continue
        value = Decimal(match.group("value").replace(",", ""))
        signatures.append(("duration", str(value.normalize()), duration_units[match.group("unit")]))
    return signatures


def _atomic_coverage_incomplete(
    item: CardRequirementExtractItem,
    unit: CardAnalysisUnit,
    exclusion_terms: Sequence[str] = (),
) -> bool:
    """Conservatively flag explicit source atoms omitted by the extraction.

    ``exclusion_terms`` (``card-compare-v2`` only): normalized requirement terms of the
    confirmed excluded fields; a term in the unit source that no constraint quotes
    leaves the unit incomplete (it can never be ``met``).
    """

    source_text = "\n".join(block.text for block in unit.blocks)
    expected_facts = {key for key in CARD_FACT_ANCHORS if fact_anchor_matches(key, source_text)}
    supplied_facts = {key for key in (resolve_fact_key(row) for row in item.constraints) if key is not None}
    if not expected_facts <= supplied_facts:
        return True
    if exclusion_terms:
        source = normalized_anchor_text(source_text)
        quotes = [normalized_anchor_text(row.quote) for row in item.constraints]
        if any(term in source and not any(term in quote for quote in quotes) for term in exclusion_terms):
            return True
    remaining = [
        (row.kind, str(decimal_value(row.value, CARD_COMPARE_INVALID).normalize()), row.unit)
        for row in item.constraints
        if row.kind in {"amount", "duration", "count", "percentage"}
    ]
    for signature in _scalar_atom_signatures(source_text):
        try:
            remaining.remove(signature)
        except ValueError:
            return True
    clauses = [clause.strip() for clause in re.split(r"\s*(?:및|그리고|;)\s*", source_text) if clause.strip()]
    if len(clauses) > 1:
        for clause in clauses:
            if (
                _scalar_atom_signatures(clause)
                or any(fact_anchor_matches(key, clause) for key in CARD_FACT_ANCHORS)
                or any(candidate.alias_text in clause for candidate in item.concept_candidates)
                # 결정 C21(리뷰 권고): a v11 text value may summarize its quote, so only a
                # value that is also verbatim in the quote can mark a source clause covered
                # (v1~v10 values are always inside the quote -- unchanged there).
                or any(
                    row.kind in {"text", "date"} and str(row.value) in clause and str(row.value) in row.quote
                    for row in item.constraints
                )
            ):
                continue
            return True
    return False


def _expected_fit(item: CardRequirementExtractItem, reasons: Sequence[str], rules: str = COMPARE_RULES_V1) -> str:
    has_atom = bool(item.constraints or item.concept_candidates)
    if rules == COMPARE_RULES_V2 and "confirmed_contradiction" in reasons:
        # 결정 E4: a confirmed contradiction is a 부족 whatever the requirement type; the
        # 계약 rule below still keeps a contract unit from ever being ``met``.
        return "gap"
    if item.type == "계약":
        return "unknown"
    if "confirmed_contradiction" in reasons:
        return "gap"
    if has_atom and not item.unknowns and reasons and all(reason == "confirmed_match" for reason in reasons):
        return "met"
    return "unknown"


def validate_requirement_compare(
    payload: Mapping[str, Any],
    *,
    extract: CardRequirementExtract | Mapping[str, Any],
    graph_paths: Sequence[Mapping[str, Any]],
    known_fact_ids: Sequence[str],
    known_evidence_ids: Sequence[UUID],
    rules: str = COMPARE_RULES_V1,
) -> CardRequirementCompare:
    """Validate compare references, reason→status and exact extract coverage (``card_compare_invalid``)."""

    if rules not in COMPARE_RULES:
        raise _invalid()
    try:
        result = CardRequirementCompare.model_validate(payload)
        parsed_extract = (
            extract if isinstance(extract, CardRequirementExtract) else CardRequirementExtract.model_validate(extract)
        )
        if not _compare_unit_order([row.unit_id for row in result.items], parsed_extract):
            raise _invalid()
        extracts = {row.unit_id: row for row in parsed_extract.items}
        rejected = {row.unit_id for row in parsed_extract.rejected_units}
        fact_ids = set(known_fact_ids)
        evidence_ids = set(known_evidence_ids)
        for item in result.items:
            if item.unit_id in rejected:
                if item != rejected_compare_row(item.unit_id):
                    raise _invalid()
                continue
            if EXTRACT_REJECTED_REASON in item.reason_codes:
                raise _invalid()
            source = extracts[item.unit_id]
            if len(item.constraint_results) != len(source.constraints):
                raise _invalid()
            for row in item.constraint_results:
                if not set(row.fact_ids) <= fact_ids:
                    raise _invalid()
                if any(
                    path_id >= len(graph_paths) or graph_paths[path_id].get("requirement_id") != item.unit_id
                    for path_id in row.path_ids
                ):
                    raise _invalid()
                if row.status != _STATUS_BY_REASON.get(row.reason_code, "unknown"):
                    raise _invalid()
            if not set(item.evidence_ids) <= evidence_ids:
                raise _invalid()
            if item.reason_codes != [reason for reason in _REASON_ORDER if reason in item.reason_codes]:
                raise _invalid()
            if rules == COMPARE_RULES_V1 and COMPARE_V2_ONLY_REASONS & (
                set(item.reason_codes) | {row.reason_code for row in item.constraint_results}
            ):
                raise _invalid()
            if item.fit_status != _expected_fit(source, item.reason_codes, rules):
                raise _invalid()
        return result
    except CardAnalysisValidationError:
        raise
    except (TypeError, ValueError, ValidationError, KeyError):
        raise _invalid() from None


def compare_requirements(
    extract: CardRequirementExtract | Mapping[str, Any],
    *,
    frozen: Mapping[str, Any],
    rules: str = COMPARE_RULES_V1,
) -> CardRequirementCompare:
    """The deterministic RL compare of one validated extract batch (``card_compare_invalid`` on any doubt).

    ``rules`` is the rule set the pinned policy selects (``card-compare-v2`` for v12).
    """

    if rules not in COMPARE_RULES:
        raise _invalid()
    try:
        card_input = card_input_of(frozen["card_analysis"], CARD_COMPARE_INVALID)
        parsed_extract = (
            extract if isinstance(extract, CardRequirementExtract) else CardRequirementExtract.model_validate(extract)
        )
        evidence_by_fact, all_evidence_ids = _profile_evidence_index(frozen["profile_evidence"])
        paths, nodes, edges = _validated_graph_context(
            frozen["graph_paths"], frozen["graph_nodes"], frozen["graph_edges"], all_evidence_ids,
        )
        known_facts = {
            row["fact_key"] for row in frozen["profile_facts"]
            if isinstance(row, Mapping) and isinstance(row.get("fact_key"), str)
        }
        unit_by_id = {unit.unit_id: unit for unit in card_input.units}
        rejected_ids = {row.unit_id for row in parsed_extract.rejected_units}
        batch = next(
            (row for row in card_input.batches
             if set(row.unit_ids) == {item.unit_id for item in parsed_extract.items} | rejected_ids),
            None,
        )
        if batch is None or not _compare_unit_order(batch.unit_ids, parsed_extract):
            raise _invalid()
        items_by_id = {item.unit_id: item for item in parsed_extract.items}
        if any(path["requirement_id"] not in unit_by_id for path in paths):
            raise _invalid()
        exclusion_terms = (
            [term for _key, terms in _confirmed_exclusions(frozen) for term in terms]
            if rules == COMPARE_RULES_V2 else []
        )

        output: list[CardRequirementCompareItem] = []
        for unit_id in batch.unit_ids:
            if unit_id in rejected_ids:
                # 결정 B51: no model content of a rejected item is compared.
                output.append(rejected_compare_row(unit_id))
                continue
            item = items_by_id[unit_id]
            unit = unit_by_id[item.unit_id]
            blocks = {(unit.source_sha256, block.block_key): block.text for block in unit.blocks}
            if any(
                (text := blocks.get((row.source_sha256, row.block_key))) is None or row.quote not in text
                for row in item.evidence
            ) or any(
                (text := blocks.get((row.locator.source_sha256, row.locator.block_key))) is None
                or row.quote not in text
                for row in item.constraints
            ) or any(
                not any(candidate.alias_text in block.text for block in unit.blocks)
                for candidate in item.concept_candidates
            ):
                raise _invalid()
            results: list[CardConstraintResult] = []
            reasons: list[str] = []
            item_evidence: list[UUID] = []
            constrained: set[str] = set()
            for index, constraint in enumerate(item.constraints):
                status, reason, fact_ids = constraint_comparison(
                    constraint, frozen, known_facts, rules=rules,
                    block_text=blocks.get((constraint.locator.source_sha256, constraint.locator.block_key)),
                )
                reasons.append(reason)
                constrained.update(fact_ids)
                if reason in _STATUS_BY_REASON:
                    # Only a confirmed decision cites company evidence (never proposed/unknown rows).
                    for fact_id in fact_ids:
                        for evidence_id in evidence_by_fact.get(fact_id, []):
                            if evidence_id not in item_evidence:
                                item_evidence.append(evidence_id)
                results.append(CardConstraintResult(
                    constraint_index=index, status=status, fact_ids=fact_ids, path_ids=[], reason_code=reason,
                ))
            reasons.extend(_concept_reasons(item, paths, nodes, edges, constrained))
            if item.unknowns or _atomic_coverage_incomplete(item, unit, exclusion_terms):
                reasons.append("incomplete_unit")
            if item.type == "계약":
                reasons.append("contract_unaccepted")
            if not (item.constraints or item.concept_candidates):
                reasons.append("incomplete_unit")
            output.append(CardRequirementCompareItem(
                unit_id=item.unit_id,
                fit_status=_expected_fit(item, reasons, rules),
                constraint_results=results,
                evidence_ids=item_evidence,
                reason_codes=[reason for reason in _REASON_ORDER if reason in reasons],
            ))
        result = CardRequirementCompare(items=output)
        return validate_requirement_compare(
            result.model_dump(mode="json"),
            extract=parsed_extract,
            graph_paths=paths,
            known_fact_ids=sorted(known_facts | set(nodes)),
            known_evidence_ids=sorted(all_evidence_ids),
            rules=rules,
        )
    except CardAnalysisValidationError as error:
        if error.code == CARD_COMPARE_INVALID:
            raise
        raise _invalid() from None
    except (TypeError, ValueError, ValidationError, KeyError):
        raise _invalid() from None


__all__ = [
    "COMPARE_RULES",
    "COMPARE_RULES_V1",
    "COMPARE_RULES_V2",
    "COMPARE_V2_ONLY_REASONS",
    "EXTRACT_REJECTED_REASON",
    "PLACE_TABLE_FILE",
    "PLACE_TABLE_SHA256",
    "PLACE_TABLE_VERSION",
    "compare_requirements",
    "rejected_compare_row",
    "constraint_comparison",
    "resolve_places",
    "validate_requirement_compare",
]
