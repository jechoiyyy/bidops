"""RL-04 proposal section validation (spec "문장 계약 `bidops.proposal-section.v1`").

Deterministic check of one model ``Section`` against the frozen per-section
input (``bidops.proposal-input.v1``: ``section_key``, ``units`` with blocks,
confirmed ``company_facts`` with label/value, ``notice_meta``).  Nothing is
corrected: the payload is only read, and a failure sends the section to people
(``failed``) with a safe code, rule codes and indexes -- never model or source
text.

Rules (spec, in the order they are checked):

* ``output_schema`` -- the closed JSON Schema of ``bidops.proposal-section.v1``.
  A schema failure stops here (the shape is not trustworthy for deeper rules).
* Structure and sentence kind: ``section_key`` equals the input; paragraph ids
  and sentence ids (UUID) are unique in the section; ``statement`` and
  ``proposed_figure`` have ``sources`` >= 1 and ``placeholder_hint=null``;
  ``proposed_figure`` text carries a number; ``placeholder`` has ``sources=[]``
  and a non-blank ``placeholder_hint``; text is not blank; every
  ``requirement_links[].paragraph_id`` names a paragraph of this section.
* Sources: ``requirement_unit`` ref is a ``unit_id`` of this section's input
  and its quote is a raw substring of one block text of that unit (HP-03
  Evidence rule, the same raw ``in`` matching as RL-03 card extract);
  ``company_fact`` ref is a ``fact_key`` of ``company_facts`` and its quote is a
  raw substring of the fact ``label`` or of ``company_fact_quote_texts``' value
  string; ``notice_meta`` ref is one of the five meta keys and its quote is a
  raw substring of that (non-null) value (결정 B42).  A digit-bearing quote must
  not cut a number (RL-03 lessons B35/B36, digit level only): at least one
  occurrence must not continue a number on either side.
* Requirement links: every ``unit_id`` is a unit of this input; the
  ``requirements`` section links every ``kind=card`` unit at least once.
* Forbidden content on ``statement``/``proposed_figure`` text: (a) currency
  amount, (b) staffing, (c) schedule promise (spec regexes verbatim).  A match
  is allowed only when its whole number token occurs, written the same way,
  in a quote of that sentence's sources that passed verification.

Classes (결정 B33 mirror): schema-class rules (structure/kind/shape) may get
the policy's single repair; evidence-class rules (sources, quotes, coverage,
forbidden content) never do.  A result is ``repairable`` only when every
violation is schema-class.  Error code precedence: ``proposal_forbidden_content``
> ``proposal_section_invalid`` > ``proposal_coverage_incomplete``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from ..contracts import PROPOSAL_SECTION_SCHEMA, SchemaValidationError, validate_payload

#: Spec "상태 값과 실패 처리" error codes produced by this validator.
PROPOSAL_FORBIDDEN_CONTENT: Final[str] = "proposal_forbidden_content"
PROPOSAL_SECTION_INVALID: Final[str] = "proposal_section_invalid"
PROPOSAL_COVERAGE_INCOMPLETE: Final[str] = "proposal_coverage_incomplete"

SECTION_KEYS: Final[tuple[str, ...]] = (
    "overview", "track_record", "strategy", "requirements", "operations_sla", "organization",
)
REQUIREMENTS_SECTION: Final[str] = "requirements"
NOTICE_META_KEYS: Final[tuple[str, ...]] = ("title", "agency", "deadline_at", "method", "estimated_price")
UNIT_KINDS: Final[frozenset[str]] = frozenset({"card", "segment"})
#: Joiner of a company fact's scalar values (spec "quote" rule).
FACT_VALUE_JOINER: Final[str] = " · "

# --- rule codes -----------------------------------------------------------------------

OUTPUT_SCHEMA_RULE: Final[str] = "output_schema"
SECTION_KEY_MISMATCH: Final[str] = "section_key_mismatch"
PARAGRAPH_ID_DUPLICATE: Final[str] = "paragraph_id_duplicate"
SENTENCE_ID_DUPLICATE: Final[str] = "sentence_id_duplicate"
SENTENCE_TEXT_BLANK: Final[str] = "sentence_text_blank"
STATEMENT_SOURCES_REQUIRED: Final[str] = "statement_sources_required"
PROPOSED_FIGURE_SOURCES_REQUIRED: Final[str] = "proposed_figure_sources_required"
PROPOSED_FIGURE_NUMBER_REQUIRED: Final[str] = "proposed_figure_number_required"
PLACEHOLDER_SOURCES_FORBIDDEN: Final[str] = "placeholder_sources_forbidden"
PLACEHOLDER_HINT_REQUIRED: Final[str] = "placeholder_hint_required"
PLACEHOLDER_HINT_FORBIDDEN: Final[str] = "placeholder_hint_forbidden"
REQUIREMENT_LINK_PARAGRAPH_UNKNOWN: Final[str] = "requirement_link_paragraph_unknown"

SOURCE_UNIT_UNKNOWN: Final[str] = "source_unit_unknown"
SOURCE_FACT_UNKNOWN: Final[str] = "source_fact_unknown"
SOURCE_META_UNKNOWN: Final[str] = "source_meta_unknown"
SOURCE_QUOTE_MISMATCH: Final[str] = "source_quote_mismatch"
SOURCE_QUOTE_TRUNCATED: Final[str] = "source_quote_truncated"
REQUIREMENT_LINK_UNIT_UNKNOWN: Final[str] = "requirement_link_unit_unknown"
REQUIREMENT_COVERAGE_MISSING: Final[str] = "requirement_coverage_missing"
FORBIDDEN_AMOUNT: Final[str] = "forbidden_amount"
FORBIDDEN_STAFFING: Final[str] = "forbidden_staffing"
FORBIDDEN_SCHEDULE: Final[str] = "forbidden_schedule"

#: Schema-class: structure, kind and shape (one repair, like RL-03 B33).
SCHEMA_RULES: Final[frozenset[str]] = frozenset({
    OUTPUT_SCHEMA_RULE, SECTION_KEY_MISMATCH, PARAGRAPH_ID_DUPLICATE, SENTENCE_ID_DUPLICATE,
    SENTENCE_TEXT_BLANK, STATEMENT_SOURCES_REQUIRED, PROPOSED_FIGURE_SOURCES_REQUIRED,
    PROPOSED_FIGURE_NUMBER_REQUIRED, PLACEHOLDER_SOURCES_FORBIDDEN, PLACEHOLDER_HINT_REQUIRED,
    PLACEHOLDER_HINT_FORBIDDEN, REQUIREMENT_LINK_PARAGRAPH_UNKNOWN,
})
FORBIDDEN_RULES: Final[frozenset[str]] = frozenset({FORBIDDEN_AMOUNT, FORBIDDEN_STAFFING, FORBIDDEN_SCHEDULE})
COVERAGE_RULES: Final[frozenset[str]] = frozenset({REQUIREMENT_COVERAGE_MISSING})
#: Evidence-class: sources, quotes, coverage, forbidden content (never repaired).
EVIDENCE_RULES: Final[frozenset[str]] = frozenset({
    SOURCE_UNIT_UNKNOWN, SOURCE_FACT_UNKNOWN, SOURCE_META_UNKNOWN, SOURCE_QUOTE_MISMATCH,
    SOURCE_QUOTE_TRUNCATED, REQUIREMENT_LINK_UNIT_UNKNOWN,
}) | COVERAGE_RULES | FORBIDDEN_RULES

#: Spec "금지 내용 검증" regexes, verbatim.  Group 1 is the number.
FORBIDDEN_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (FORBIDDEN_AMOUNT, re.compile(r"(\d[\d,]*)\s*(원|천원|백만원|억)")),
    (FORBIDDEN_STAFFING, re.compile(r"(\d+)\s*(명|인)\s*(투입|상주|배치)")),
    (FORBIDDEN_SCHEDULE, re.compile(r"(\d+)\s*(개월|일)\s*(내|이내)\s*(완료|구축)")),
)
#: Source kinds whose verified quotes can carry the "원문 숫자 인용" exception.
#: Spec wording is "sources의 quote" (all kinds); its parenthetical names 공고 원문.
#: Narrowing to ``requirement_unit``/``notice_meta`` is one edit here.
# Only notice-side sources exempt a forbidden number ("공고 원문 숫자 인용은 허용", decision B43):
# a company fact such as an available-staff count must not become a staffing or price promise.
FORBIDDEN_EXEMPT_SOURCE_KINDS: Final[frozenset[str]] = frozenset({"requirement_unit", "notice_meta"})
FORBIDDEN_CHECKED_KINDS: Final[frozenset[str]] = frozenset({"statement", "proposed_figure"})

_DIGIT = re.compile(r"\d")
#: Text ending in a digit (optionally followed by a decimal/thousands mark).
_NUMBER_TAIL = re.compile(r"\d[.,]?$")
#: Text starting with a digit (optionally preceded by a decimal/thousands mark).
_NUMBER_HEAD = re.compile(r"[.,]?\d")
_PATH_INDEX = {
    "paragraph_index": re.compile(r"^\$\.paragraphs\[(\d+)\]"),
    "sentence_index": re.compile(r"^\$\.paragraphs\[\d+\]\.sentences\[(\d+)\]"),
    "source_index": re.compile(r"^\$\.paragraphs\[\d+\]\.sentences\[\d+\]\.sources\[(\d+)\]"),
    "link_index": re.compile(r"^\$\.requirement_links\[(\d+)\]"),
}


class ProposalSectionInputError(ValueError):
    """The frozen section input itself is malformed (a code defect, not a model failure)."""


@dataclass(frozen=True)
class ProposalViolation:
    """One rule violation located by indexes only (no model or source text)."""

    rule_code: str
    paragraph_index: int | None = None
    sentence_index: int | None = None
    source_index: int | None = None
    link_index: int | None = None
    unit_index: int | None = None

    def safe_detail(self) -> dict[str, Any]:
        return {
            "rule_code": self.rule_code,
            "paragraph_index": self.paragraph_index,
            "sentence_index": self.sentence_index,
            "source_index": self.source_index,
            "link_index": self.link_index,
            "unit_index": self.unit_index,
        }


@dataclass(frozen=True)
class ProposalValidationResult:
    """``ok`` or a failure with one spec error code and all violations found."""

    violations: tuple[ProposalViolation, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def rule_codes(self) -> tuple[str, ...]:
        return tuple(sorted({violation.rule_code for violation in self.violations}))

    @property
    def error_code(self) -> str | None:
        codes = set(self.rule_codes)
        if not codes:
            return None
        if codes & FORBIDDEN_RULES:
            return PROPOSAL_FORBIDDEN_CONTENT
        if codes - COVERAGE_RULES:
            return PROPOSAL_SECTION_INVALID
        return PROPOSAL_COVERAGE_INCOMPLETE

    @property
    def repairable(self) -> bool:
        """결정 B33 mirror: only an all-schema-class failure may get the single repair."""

        return bool(self.violations) and all(violation.rule_code in SCHEMA_RULES for violation in self.violations)

    def safe_detail(self) -> dict[str, Any]:
        """Codes and integer indexes only -- safe for raw-response records and audits."""

        return {
            "error_code": self.error_code,
            "repairable": self.repairable,
            "rule_codes": list(self.rule_codes),
            "violations": [violation.safe_detail() for violation in self.violations],
        }


# --- frozen input -----------------------------------------------------------------------


def _scalar_text(value: Any) -> str | None:
    if value is None or isinstance(value, (Mapping, list, tuple)):
        return None
    if isinstance(value, str):
        return value
    # Numbers and booleans as the model saw them in canonical JSON (``true``, ``58``).
    return json.dumps(value, ensure_ascii=False)


def company_fact_quote_texts(fact: Mapping[str, Any]) -> tuple[str, str]:
    """``(label, value string)`` a ``company_fact`` quote may be a substring of.

    Value string = the value's scalar values joined by ``" · "``: an object value
    contributes its top-level scalars in sorted key order (nested objects/arrays
    and nulls excluded); a scalar value is itself; an array contributes its
    scalar items in order (nulls excluded); null is ``""``.
    """

    value = fact.get("value")
    if isinstance(value, Mapping):
        parts = [_scalar_text(value[key]) for key in sorted(value)]
    elif isinstance(value, list):
        parts = [_scalar_text(item) for item in value]
    else:
        parts = [_scalar_text(value)]
    return str(fact.get("label")), FACT_VALUE_JOINER.join(part for part in parts if part is not None)


@dataclass(frozen=True)
class _Frozen:
    section_key: str
    unit_ids: tuple[str, ...]
    unit_kinds: tuple[str, ...]
    unit_blocks: dict[str, tuple[str, ...]]
    fact_texts: dict[str, tuple[str, ...]]
    notice_meta: dict[str, str | None]


def _frozen_input(section_input: Mapping[str, Any]) -> _Frozen:
    def fail(reason: str) -> ProposalSectionInputError:
        return ProposalSectionInputError(f"proposal section input: {reason}")

    if not isinstance(section_input, Mapping):
        raise fail("not an object")
    section_key = section_input.get("section_key")
    if section_key not in SECTION_KEYS:
        raise fail("section_key")
    units = section_input.get("units")
    if not isinstance(units, list):
        raise fail("units")
    unit_ids: list[str] = []
    unit_kinds: list[str] = []
    unit_blocks: dict[str, tuple[str, ...]] = {}
    for unit in units:
        if not isinstance(unit, Mapping):
            raise fail("unit")
        unit_id, kind, blocks = unit.get("unit_id"), unit.get("kind"), unit.get("blocks")
        if not isinstance(unit_id, str) or not unit_id or unit_id in unit_blocks:
            raise fail("unit_id")
        if kind not in UNIT_KINDS:
            raise fail("unit kind")
        if not isinstance(blocks, list) or not blocks or any(
            not isinstance(block, Mapping) or not isinstance(block.get("text"), str) for block in blocks
        ):
            raise fail("unit blocks")
        unit_ids.append(unit_id)
        unit_kinds.append(kind)
        unit_blocks[unit_id] = tuple(block["text"] for block in blocks)
    facts = section_input.get("company_facts")
    if not isinstance(facts, list):
        raise fail("company_facts")
    fact_texts: dict[str, tuple[str, ...]] = {}
    for fact in facts:
        if not isinstance(fact, Mapping):
            raise fail("company fact")
        fact_key, label = fact.get("fact_key"), fact.get("label")
        if not isinstance(fact_key, str) or not fact_key or fact_key in fact_texts:
            raise fail("fact_key")
        if not isinstance(label, str) or not label:
            raise fail("fact label")
        if "value" not in fact:
            raise fail("fact value")
        fact_texts[fact_key] = tuple(text for text in company_fact_quote_texts(fact) if text)
    meta = section_input.get("notice_meta")
    if not isinstance(meta, Mapping) or set(meta) != set(NOTICE_META_KEYS) or any(
        value is not None and not isinstance(value, str) for value in meta.values()
    ):
        raise fail("notice_meta")
    return _Frozen(
        section_key=section_key,
        unit_ids=tuple(unit_ids),
        unit_kinds=tuple(unit_kinds),
        unit_blocks=unit_blocks,
        fact_texts=fact_texts,
        notice_meta={key: meta[key] for key in NOTICE_META_KEYS},
    )


# --- quotes and numbers -----------------------------------------------------------------


def _clean_occurrence(quote: str, text: str) -> bool:
    """Whether ``quote`` occurs in ``text`` (raw) at a place that cuts no number.

    An occurrence is cut when the quote starts with a digit (or ``,``/``.`` +
    digit) right after a digit (or digit + ``,``/``.``) of the text, or ends with
    a digit (or digit + ``,``/``.``) right before a digit (or ``,``/``.`` +
    digit) of the text -- ``3명`` of ``13명``, ``50,000,000원`` of
    ``150,000,000원``, ``150,000`` of ``150,000,000``.  Only digit-level cuts:
    a whole number before its unit or comparator (``3`` of ``3초 이내``) is that
    number.  Quotes without a digit only need to occur.
    """

    if not quote:
        return False
    head = _NUMBER_HEAD.match(quote) is not None
    tail = _NUMBER_TAIL.search(quote) is not None
    start = text.find(quote)
    while start >= 0:
        cut_front = head and _NUMBER_TAIL.search(text[:start]) is not None
        cut_back = tail and _NUMBER_HEAD.match(text[start + len(quote):]) is not None
        if not cut_front and not cut_back:
            return True
        start = text.find(quote, start + 1)
    return False


def _quote_status(quote: str, texts: Sequence[str]) -> str | None:
    """``None`` (verified), ``source_quote_mismatch`` or ``source_quote_truncated``."""

    present = [text for text in texts if quote in text]
    if not present:
        return SOURCE_QUOTE_MISMATCH
    if _DIGIT.search(quote) is not None and not any(_clean_occurrence(quote, text) for text in present):
        return SOURCE_QUOTE_TRUNCATED
    return None


def _number_token(text: str, start: int, end: int) -> str:
    """The whole number around a regex number group (``1.5`` of ``1.5억``), trailing marks stripped."""

    while start > 0 and (
        _DIGIT.match(text[start - 1]) is not None
        or (text[start - 1] in ".," and start > 1 and _DIGIT.match(text[start - 2]) is not None)
    ):
        start -= 1
    while end < len(text) and (
        _DIGIT.match(text[end]) is not None
        or (text[end] in ".," and end + 1 < len(text) and _DIGIT.match(text[end + 1]) is not None)
    ):
        end += 1
    return text[start:end].rstrip(".,")


def _forbidden_rules(text: str, quotes: Sequence[str]) -> list[str]:
    found: list[str] = []
    for rule, pattern in FORBIDDEN_PATTERNS:
        for match in pattern.finditer(text):
            token = _number_token(text, match.start(1), match.end(1))
            if not any(_clean_occurrence(token, quote) for quote in quotes):
                found.append(rule)
                break
    return found


# --- validation -------------------------------------------------------------------------


def _schema_violation(error: SchemaValidationError) -> ProposalViolation:
    path = getattr(error, "path", "") or ""
    indexes = {
        name: int(found.group(1))
        for name, pattern in _PATH_INDEX.items()
        if (found := pattern.match(path)) is not None
    }
    return ProposalViolation(OUTPUT_SCHEMA_RULE, **indexes)


def validate_proposal_section(payload: Any, *, section_input: Mapping[str, Any]) -> ProposalValidationResult:
    """Validate one model ``Section`` against its frozen section input; never modifies either.

    Raises ``ProposalSectionInputError`` only when the frozen input itself is
    malformed.  Every model problem is a violation in the returned result.
    """

    frozen = _frozen_input(section_input)
    try:
        validate_payload(payload, PROPOSAL_SECTION_SCHEMA)
    except SchemaValidationError as error:
        return ProposalValidationResult((_schema_violation(error),))

    violations: list[ProposalViolation] = []
    if payload["section_key"] != frozen.section_key:
        violations.append(ProposalViolation(SECTION_KEY_MISMATCH))

    paragraph_ids: set[str] = set()
    sentence_ids: set[str] = set()
    for p_index, paragraph in enumerate(payload["paragraphs"]):
        if paragraph["paragraph_id"] in paragraph_ids:
            violations.append(ProposalViolation(PARAGRAPH_ID_DUPLICATE, paragraph_index=p_index))
        paragraph_ids.add(paragraph["paragraph_id"])
        for s_index, sentence in enumerate(paragraph["sentences"]):
            at = {"paragraph_index": p_index, "sentence_index": s_index}
            violations.extend(ProposalViolation(rule, **at) for rule in _sentence_shape_rules(sentence, sentence_ids))
            sentence_ids.add(sentence["sentence_id"].lower())

            verified_quotes: list[str] = []
            for src_index, source in enumerate(sentence["sources"]):
                rule = _source_rule(source, frozen)
                if rule is None:
                    if source["kind"] in FORBIDDEN_EXEMPT_SOURCE_KINDS:
                        verified_quotes.append(source["quote"])
                else:
                    violations.append(ProposalViolation(rule, source_index=src_index, **at))
            if sentence["kind"] in FORBIDDEN_CHECKED_KINDS:
                violations.extend(
                    ProposalViolation(rule, **at) for rule in _forbidden_rules(sentence["text"], verified_quotes)
                )

    input_unit_ids = set(frozen.unit_ids)
    linked_units: set[str] = set()
    for l_index, link in enumerate(payload["requirement_links"]):
        if link["unit_id"] not in input_unit_ids:
            violations.append(ProposalViolation(REQUIREMENT_LINK_UNIT_UNKNOWN, link_index=l_index))
        if link["paragraph_id"] not in paragraph_ids:
            violations.append(ProposalViolation(REQUIREMENT_LINK_PARAGRAPH_UNKNOWN, link_index=l_index))
        linked_units.add(link["unit_id"])
    if frozen.section_key == REQUIREMENTS_SECTION:
        violations.extend(
            ProposalViolation(REQUIREMENT_COVERAGE_MISSING, unit_index=u_index)
            for u_index, (unit_id, kind) in enumerate(zip(frozen.unit_ids, frozen.unit_kinds))
            if kind == "card" and unit_id not in linked_units
        )
    return ProposalValidationResult(tuple(violations))


def _sentence_shape_rules(sentence: Mapping[str, Any], seen_ids: set[str]) -> list[str]:
    rules: list[str] = []
    if sentence["sentence_id"].lower() in seen_ids:
        rules.append(SENTENCE_ID_DUPLICATE)
    text, kind, sources, hint = sentence["text"], sentence["kind"], sentence["sources"], sentence["placeholder_hint"]
    if not text.strip():
        rules.append(SENTENCE_TEXT_BLANK)
    if kind == "placeholder":
        if sources:
            rules.append(PLACEHOLDER_SOURCES_FORBIDDEN)
        if hint is None or not hint.strip():
            rules.append(PLACEHOLDER_HINT_REQUIRED)
        return rules
    if not sources:
        rules.append(STATEMENT_SOURCES_REQUIRED if kind == "statement" else PROPOSED_FIGURE_SOURCES_REQUIRED)
    if hint is not None:
        rules.append(PLACEHOLDER_HINT_FORBIDDEN)
    if kind == "proposed_figure" and _DIGIT.search(text) is None:
        rules.append(PROPOSED_FIGURE_NUMBER_REQUIRED)
    return rules


def _source_rule(source: Mapping[str, str], frozen: _Frozen) -> str | None:
    kind, ref, quote = source["kind"], source["ref"], source["quote"]
    if kind == "requirement_unit":
        texts = frozen.unit_blocks.get(ref)
        if texts is None:
            return SOURCE_UNIT_UNKNOWN
    elif kind == "company_fact":
        texts = frozen.fact_texts.get(ref)
        if texts is None:
            return SOURCE_FACT_UNKNOWN
    else:  # notice_meta (schema enum)
        if ref not in frozen.notice_meta:
            return SOURCE_META_UNKNOWN
        value = frozen.notice_meta[ref]
        texts = () if value is None else (value,)
    return _quote_status(quote, texts)


__all__ = [
    "COVERAGE_RULES",
    "EVIDENCE_RULES",
    "FORBIDDEN_PATTERNS",
    "FORBIDDEN_RULES",
    "NOTICE_META_KEYS",
    "PROPOSAL_COVERAGE_INCOMPLETE",
    "PROPOSAL_FORBIDDEN_CONTENT",
    "PROPOSAL_SECTION_INVALID",
    "SCHEMA_RULES",
    "ProposalSectionInputError",
    "ProposalValidationResult",
    "ProposalViolation",
    "company_fact_quote_texts",
    "validate_proposal_section",
]
