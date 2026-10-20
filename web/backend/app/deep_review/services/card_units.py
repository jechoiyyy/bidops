"""RL-03 card-v1 unit selection, batching and the frozen ``card_analysis`` input.

The HP-03 rules are adopted unchanged (RL-03 spec "루트랩 재명세 차이"): one
unit per HP-01 requirement card, one unit per manifest segment whose blocks
fall under the six heading-scoped sections (overview/schedule/budget/
eligibility/evaluation/contract), card-owned blocks, card tables and table of
contents excluded, deterministic greedy packing without truncation.  Only the
selector version (``card-sections-v1``), the failure code prefix (``card_``)
and the nested input identity (``company_binding`` of the active real-company
binding instead of HP basis hashes) differ.

Selector ``card-sections-v2`` (결정 B23, policy ``analysis-policy-luna-rl-v2``)
is v1 plus one heading rule: a paragraph that starts with a symbol bullet
(Unicode private use U+E000-U+F8FF such as the Wingdings U+F06D of real HWP
RFPs, or one of ``BULLET_HEADING_SYMBOLS``), whose title after the bullet is
at most ``BULLET_HEADING_MAX_CHARACTERS`` and contains a v1 section keyword
opens that section one level below every numbered heading.  The title cap
keeps bullet *sentences* out (the real Polytech RFP has 63- and 73-character
bullet sentences that mention "계약조건"/"계약일반조건"; its bullet headings are
8-34 characters).  A bullet paragraph that is not a heading neither opens nor
closes a scope.  v1 is unchanged.

Selector ``card-sections-v3`` (결정 B30, policy ``analysis-policy-luna-rl-v3``)
is v2 plus two exclusions found on the real Polytech RFP (T12 4차):

* table of contents **without page numbers**: after the single TOC marker
  paragraph (``목차``/``목 차``/``목    차``… -- the manifest marker set), the
  consecutive paragraphs that are blank or a short title-only entry (numbered
  heading, roman numeral, symbol/PUA bullet, ``붙임``-style prefix, bracketed
  title, or a trailing page number; at most ``TOC_ENTRY_MAX_CHARACTERS``, no
  ``:``) are excluded from units.  The region stops at the first non-paragraph
  block, the first body paragraph, or an entry that repeats an earlier entry
  (the body restarting with the same heading); an entry directly followed by
  that stopping content is the first body heading and is not excluded.
  Headings keep their scope
  effect exactly like the v1 page-numbered TOC exclusion;
* segment units without body text: a unit whose blocks are only blank or
  title-only numbered headings (no ``:`` and no digit after the leading
  number) is dropped and its sections are not counted as present.  Symbol
  bullet headings count as body text (they often carry an inline value such
  as "사업예산: 134,700천원").

v1 and v2 are unchanged.

Selector ``card-sections-v4`` (결정 C15, policy ``analysis-policy-luna-rl-v10``)
is v3 plus one rule found on real pre-specs (RL-05: 3 of 10 refused with
``input_budget_exceeded`` because one segment unit had 12,061 / 12,963 /
29,949 characters).  A segment unit above the policy ``batch_max_chars`` is
split at block boundaries into consecutive parts in its block order, packed
greedily up to the limit; nothing is cut, dropped or reordered.  A single
block above the limit is still ``input_budget_exceeded``.  Every part keeps
the segment's kind, ordinal, section kinds, page range and mapping status and
has the id ``<segment unit id>#p<n>`` (n from 1); an unsplit unit keeps the
v3 id.  v1-v3 are unchanged.

The selection functions are pure.  ``card_analysis_sources`` reads the pinned
confirmation-time structures and the persisted HP-01 manifest/card projection
of a ready bundle; it never calls a model or the network.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, Final
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.object_store import ObjectStoreError, object_store
from ..contracts import CARD_ANALYSIS_INPUT_SCHEMA, SchemaValidationError, validate_payload
from ..models import DocumentSegment
from ..schemas.card_analysis import (
    CARD_SELECTOR_VERSION,
    CARD_SELECTOR_VERSION_V2,
    CARD_SELECTOR_VERSION_V3,
    CARD_SELECTOR_VERSION_V4,
    CardAnalysisBatch,
    CardAnalysisInput,
    CardAnalysisSource,
    CardAnalysisUnit,
    CardBatchPolicy,
    CardCallBudget,
    CardCompanyBinding,
    CardSelector,
    CardSelectorCandidateBlock,
    CardSelectorSelectedBlock,
    CardSourceBinding,
    CardUnitBlock,
    CardUnitSelection,
    SectionKind,
)
from . import document_segments
from .overview_range import _normalise_heading_text  # noqa: PLC2701 - canonical heading rule


SECTION_KINDS: Final[tuple[SectionKind, ...]] = (
    "overview",
    "schedule",
    "budget",
    "eligibility",
    "evaluation",
    "contract",
)
SECTION_KEYWORDS: Final[dict[SectionKind, tuple[str, ...]]] = {
    "overview": ("사업개요", "과업개요", "사업목적", "추진배경"),
    "schedule": ("추진일정", "사업기간", "수행기간"),
    "budget": ("사업예산", "사업비", "소요예산", "추정가격"),
    "eligibility": ("입찰참가자격", "참가자격", "입찰자격"),
    "evaluation": ("평가기준", "평가방법", "제안서평가", "배점"),
    "contract": (
        "계약조건",
        "계약사항",
        "계약일반",
        "계약특수",
        "대금지급",
        "지체상금",
        "지식재산권",
    ),
}

SELECTOR_VERSION: Final[str] = CARD_SELECTOR_VERSION
_SELECTOR_POLICY: Final[dict[str, Any]] = {
    "version": SELECTOR_VERSION,
    "sections": {key: list(SECTION_KEYWORDS[key]) for key in SECTION_KINDS},
    "heading_normalization": "overview-range-v1+remove-whitespace",
    "heading_scope": "through-next-same-or-higher-heading",
    "segment_rule": "intersect-current-manifest-segment",
    "exclusions": ["requirement-card-owned-block", "requirement-card-table", "toc-block"],
    "deduplication": "source-sha256-then-block-key-first-in-source-order",
}

#: 결정 B23 selector: v1 + bullet headings (symbol/PUA first character).
SELECTOR_VERSION_V2: Final[str] = CARD_SELECTOR_VERSION_V2
#: Bullet symbols accepted in front of a v2 heading besides the private use
#: area (the existing overview heading bullets plus common RFP markers).
BULLET_HEADING_SYMBOLS: Final[str] = "·•∙◦○●◉▪▫■□◆◇▶▷▸►‣◎※❖➢➤"
#: Below every numbered level (chapter/roman 1, decimal 2..5).
BULLET_HEADING_LEVEL: Final[int] = 6
#: Title length after the bullet (NFKC, whitespace collapsed) of a v2 bullet heading.
BULLET_HEADING_MAX_CHARACTERS: Final[int] = 40
_PRIVATE_USE_FIRST: Final[int] = 0xE000
_PRIVATE_USE_LAST: Final[int] = 0xF8FF
_SELECTOR_POLICY_V2: Final[dict[str, Any]] = {
    **_SELECTOR_POLICY,
    "version": SELECTOR_VERSION_V2,
    "bullet_headings": {
        "leading_symbols": BULLET_HEADING_SYMBOLS,
        "private_use_range": ["U+E000", "U+F8FF"],
        "requires_section_keyword": True,
        "max_title_characters": BULLET_HEADING_MAX_CHARACTERS,
        "level": "below-numbered-headings",
    },
}

#: 결정 B30 selector: v2 + TOC entries without page numbers + title-only units dropped.
SELECTOR_VERSION_V3: Final[str] = CARD_SELECTOR_VERSION_V3
#: Maximum entry length (NFKC, whitespace collapsed, trailing page number removed).
TOC_ENTRY_MAX_CHARACTERS: Final[int] = 50
#: Prefixes of attachment/annex entries listed in a table of contents.
TOC_ATTACHMENT_PREFIXES: Final[tuple[str, ...]] = ("붙임", "별첨", "첨부", "부록", "별지", "서식")
_SELECTOR_POLICY_V3: Final[dict[str, Any]] = {
    **_SELECTOR_POLICY_V2,
    "version": SELECTOR_VERSION_V3,
    "exclusions": [*_SELECTOR_POLICY["exclusions"], "toc-entry-without-page-number", "unit-without-body-text"],
    "toc_entries": {
        "marker": "exactly-one-manifest-toc-marker-paragraph",
        "entry_lead": [
            "numbered-heading", "roman-numeral", "bullet-symbol-or-private-use",
            "attachment-prefix", "bracketed-title", "trailing-page-number",
        ],
        "attachment_prefixes": list(TOC_ATTACHMENT_PREFIXES),
        "max_entry_characters": TOC_ENTRY_MAX_CHARACTERS,
        "entry_forbidden_characters": [":", "："],
        "blank_paragraphs": "inside-region",
        "stop": ["non-paragraph-block", "body-paragraph", "repeated-entry"],
        "entry_directly_before_stopping_content": "body-heading-not-excluded",
        "scope_effect": "unchanged",
    },
    "body_text": "non-blank-block-other-than-title-only-numbered-heading",
}

#: 결정 C15 selector: v3 + an oversized segment unit split at block boundaries.
SELECTOR_VERSION_V4: Final[str] = CARD_SELECTOR_VERSION_V4
#: Part id suffix of a split v4 segment unit (``<segment unit id>#p<n>``, n from 1).
SEGMENT_PART_SUFFIX: Final[str] = "#p"
_SELECTOR_POLICY_V4: Final[dict[str, Any]] = {
    **_SELECTOR_POLICY_V3,
    "version": SELECTOR_VERSION_V4,
    "segment_split": {
        "trigger": "segment-unit-characters-above-policy-batch-max-chars",
        "boundary": "block",
        "order": "unit-block-order",
        "packing": "greedy-consecutive-blocks-up-to-batch-max-chars",
        "single_block_above_limit": "input_budget_exceeded",
        "truncation": "never",
        "part_unit_id": "segment-unit-id#p<n>-from-1",
        "part_attributes": "segment-kind-ordinal-section-kinds-page-range-mapping-status",
    },
}

#: Stable selection failure code (RL-03 ``card_*`` codes).
SELECTION_INCOMPLETE: Final[str] = "card_source_selection_incomplete"
INPUT_BUDGET_EXCEEDED: Final[str] = "input_budget_exceeded"


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


#: SHA of the canonical selector policy object frozen in every input.
SELECTOR_SHA256: Final[str] = hashlib.sha256(_canonical_json_bytes(_SELECTOR_POLICY)).hexdigest()
SELECTOR_SHA256_V2: Final[str] = hashlib.sha256(_canonical_json_bytes(_SELECTOR_POLICY_V2)).hexdigest()
SELECTOR_SHA256_V3: Final[str] = hashlib.sha256(_canonical_json_bytes(_SELECTOR_POLICY_V3)).hexdigest()
SELECTOR_SHA256_V4: Final[str] = hashlib.sha256(_canonical_json_bytes(_SELECTOR_POLICY_V4)).hexdigest()
#: Selector version → canonical selector policy SHA frozen in every input.
SELECTOR_SHA256_BY_VERSION: Final[dict[str, str]] = {
    SELECTOR_VERSION: SELECTOR_SHA256,
    SELECTOR_VERSION_V2: SELECTOR_SHA256_V2,
    SELECTOR_VERSION_V3: SELECTOR_SHA256_V3,
    SELECTOR_VERSION_V4: SELECTOR_SHA256_V4,
}
#: Selectors that accept symbol/PUA bullet headings (v2 rule, kept by v3 and v4).
_BULLET_HEADING_SELECTORS: Final[frozenset[str]] = frozenset({
    SELECTOR_VERSION_V2, SELECTOR_VERSION_V3, SELECTOR_VERSION_V4,
})
#: Selectors with the v3 TOC-entry and title-only-unit exclusions (결정 B30, kept by v4).
_V3_EXCLUSION_SELECTORS: Final[frozenset[str]] = frozenset({SELECTOR_VERSION_V3, SELECTOR_VERSION_V4})

_CHAPTER_HEADING = re.compile(r"^\s*제\s*\d{1,2}\s*[장절편]\s*\S")
_DECIMAL_HEADING = re.compile(r"^\s*(?P<number>\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+\S")
_ROMAN_HEADING = re.compile(r"^\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX]{1,4}\s*[.)、:：\-–—]?\s*\S", re.IGNORECASE)
#: v3 TOC entry leads (on NFKC text; NFKC turns Ⅰ..Ⅹ into ASCII I/V/X).
_TOC_ROMAN_ENTRY = re.compile(r"^[IVX]{1,4}(?:\s*[.)]|\s|(?=[^\x00-\x7f]))")
_TOC_KOREAN_LIST_ENTRY = re.compile(r"^[가-하]\s*[.)]\s*\S")
_TOC_BRACKETED_ENTRY = re.compile(r"^(?:【[^】]+】|\[[^\]]+\]|〔[^〕]+〕|<[^>]+>|〈[^〉]+〉|《[^》]+》)$")
_TOC_PAGE_SUFFIX = re.compile(r"(?:\s*[.·…]{2,}\s*|\s{2,}|\t+\s*)\d{1,5}\s*$")
_CIRCLED_FIRST, _CIRCLED_LAST = 0x2460, 0x2473
_LEADING_NUMBER = re.compile(r"^\s*(?:제\s*\d{1,2}\s*[장절편]|\d{1,2}(?:\.\d{1,2}){0,3}\.?)")


class CardAnalysisSelectionError(ValueError):
    """Safe selection failure (``card_source_selection_incomplete`` | ``input_budget_exceeded``).

    Carries no source text, path or company material.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _is_bullet_heading(text: str) -> bool:
    """v2: symbol/PUA bullet first, a short title, and a v1 section keyword in that title."""

    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()
    if len(normalized) < 2:
        return False
    first = normalized[0]
    if not (_PRIVATE_USE_FIRST <= ord(first) <= _PRIVATE_USE_LAST or first in BULLET_HEADING_SYMBOLS):
        return False
    title = normalized[1:].strip()
    if not title or len(title) > BULLET_HEADING_MAX_CHARACTERS:
        return False
    return bool(_section_kinds(title))


def _heading_level(text: str, selector_version: str = SELECTOR_VERSION) -> int | None:
    """Return the deterministic heading hierarchy used by the selector."""

    normalized = unicodedata.normalize("NFKC", text).strip()
    if not normalized or not document_segments._is_numbered_heading(text):  # noqa: PLC2701
        if selector_version in _BULLET_HEADING_SELECTORS and _is_bullet_heading(text):
            return BULLET_HEADING_LEVEL
        return None
    if _CHAPTER_HEADING.match(normalized) or _ROMAN_HEADING.match(normalized):
        return 1
    decimal = _DECIMAL_HEADING.match(normalized)
    if decimal is None:
        return None
    return len(decimal.group("number").split(".")) + 1


def _section_kinds(text: str) -> tuple[SectionKind, ...]:
    normalized = re.sub(r"\s+", "", _normalise_heading_text(text))
    return tuple(
        section
        for section in SECTION_KINDS
        if any(keyword in normalized for keyword in SECTION_KEYWORDS[section])
    )


def _toc_block_keys(source: CardAnalysisSource) -> set[str]:
    structure = {"blocks": [block.model_dump(mode="json") for block in source.blocks]}
    blocks = document_segments._read_blocks(structure)  # noqa: PLC2701 - same manifest input parser
    indices, _entries, _warnings = document_segments._toc_region(blocks)  # noqa: PLC2701
    return {blocks[index].block_key for index in indices if 0 <= index < len(blocks)}


def _toc_entry(text: str) -> str | None:
    """v3: the squashed comparison form of a title-only TOC entry, or ``None`` (body text)."""

    normalized = unicodedata.normalize("NFKC", text)
    has_page = _TOC_PAGE_SUFFIX.search(normalized) is not None
    title = re.sub(r"\s+", " ", _TOC_PAGE_SUFFIX.sub("", normalized)).strip()
    if not title or len(title) > TOC_ENTRY_MAX_CHARACTERS or ":" in title or "：" in title:
        return None
    raw = text.strip()
    first = raw[0] if raw else ""
    led = (
        has_page
        or document_segments._is_numbered_heading(title)  # noqa: PLC2701 - manifest heading rule
        or _TOC_ROMAN_ENTRY.match(title) is not None
        or _TOC_KOREAN_LIST_ENTRY.match(title) is not None
        or _TOC_BRACKETED_ENTRY.match(title) is not None
        or title.startswith(TOC_ATTACHMENT_PREFIXES)
        or (bool(first) and (
            _PRIVATE_USE_FIRST <= ord(first) <= _PRIVATE_USE_LAST
            or _CIRCLED_FIRST <= ord(first) <= _CIRCLED_LAST
            or first in BULLET_HEADING_SYMBOLS
        ))
    )
    return document_segments._squash(title) if led else None  # noqa: PLC2701


def _toc_entry_keys_v3(source: CardAnalysisSource) -> set[str]:
    """v3: the TOC marker and its consecutive title-only entries (page numbers optional).

    Exactly one marker paragraph (the manifest marker set) is required, as in
    the manifest TOC rule; blank paragraphs inside and right after the entries
    belong to the region.  The region stops at a non-paragraph block, a body
    paragraph, or an entry that repeats an earlier one.  An entry directly
    followed (no blank paragraph) by the content that stops the region is the
    first body heading and stays outside the region.
    """

    markers = {document_segments._squash(item) for item in document_segments._TOC_MARKERS}  # noqa: PLC2701
    indices = [
        index for index, block in enumerate(source.blocks)
        if block.type.casefold() in {"paragraph", "text"}
        and document_segments._squash(block.text) in markers  # noqa: PLC2701
    ]
    if len(indices) != 1:
        return set()
    keys = {source.blocks[indices[0]].block_key}
    entries: set[str] = set()
    adjacent_entry: str | None = None  # last entry key when no blank followed it
    for block in source.blocks[indices[0] + 1:]:
        if block.type.casefold() in {"paragraph", "text"} and not block.text.strip():
            keys.add(block.block_key)
            adjacent_entry = None
            continue
        entry = _toc_entry(block.text) if block.type.casefold() in {"paragraph", "text"} else None
        if entry is not None and entry not in entries:
            entries.add(entry)
            keys.add(block.block_key)
            adjacent_entry = block.block_key
            continue
        if entry is None and adjacent_entry is not None:
            # Content (body paragraph or a table) directly after an entry: that
            # entry is the first body heading, not a TOC line.
            keys.discard(adjacent_entry)
        break
    return keys


def _is_title_only_heading(block: Any) -> bool:
    """v3: a numbered (v1) heading paragraph with no ``:`` and no digit after its leading number."""

    if block.type.casefold() not in {"paragraph", "text"} or _heading_level(block.text) is None:
        return False
    normalized = unicodedata.normalize("NFKC", block.text).strip()
    rest = _LEADING_NUMBER.sub("", normalized, count=1)
    return ":" not in rest and "：" not in rest and re.search(r"[0-9]", rest) is None


def _has_body_text(blocks: Sequence[Any]) -> bool:
    """v3: a unit has body text when one block is non-blank and not a title-only numbered heading."""

    return any(block.text.strip() and not _is_title_only_heading(block) for block in blocks)


def _card_owned_keys(source: CardAnalysisSource) -> dict[int, tuple[str, ...]]:
    """Map card ordinal to its exact table-cell span using the HP-01 rules."""

    cells_by_table: dict[str, list[tuple[int, int, int, str, str]]] = {}
    for source_ordinal, block in enumerate(source.blocks):
        if block.type.casefold() != "table_cell":
            continue
        table_key = block.attributes.get("table_key")
        row = block.attributes.get("row")
        column = block.attributes.get("column")
        if (
            not isinstance(table_key, str)
            or isinstance(row, bool)
            or not isinstance(row, int)
            or isinstance(column, bool)
            or not isinstance(column, int)
        ):
            continue
        cells_by_table.setdefault(table_key, []).append(
            (row, column, source_ordinal, block.block_key, block.text)
        )

    cards_by_table: dict[str, list[tuple[int, int]]] = {}
    for card in source.cards:
        table_key = card.card.get("table_key")
        row = card.locator.get("row")
        if (
            not isinstance(table_key, str)
            or not table_key
            or isinstance(row, bool)
            or not isinstance(row, int)
            or table_key not in cells_by_table
        ):
            raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
        cards_by_table.setdefault(table_key, []).append((row, card.ordinal))

    result: dict[int, tuple[str, ...]] = {}
    already_owned: set[str] = set()
    for table_key, card_rows in cards_by_table.items():
        ordered_cards = sorted(card_rows)
        cells = sorted(cells_by_table[table_key], key=lambda row: (row[2], row[0], row[1]))
        category_rows = sorted({
            row
            for row, _column, _ordinal, _key, text in cells
            if document_segments._card_field(text) == "category"  # noqa: PLC2701
        })
        last_row = max(row for row, *_rest in cells)
        starts: list[tuple[int, int, int]] = []
        for id_row, card_ordinal in ordered_cards:
            preceding = [row for row in category_rows if row <= id_row]
            start_row = preceding[-1] if preceding else id_row
            starts.append((start_row, id_row, card_ordinal))
        for index, (start_row, _id_row, card_ordinal) in enumerate(starts):
            # Adjacent cards can place the next category row before its ID row.
            # Give that row to the following card so one source block never
            # appears in two units.
            end_row = starts[index + 1][0] - 1 if index + 1 < len(starts) else last_row
            keys = tuple(
                key
                for row, _column, _ordinal, key, _text in cells
                if start_row <= row <= end_row and key not in already_owned
            )
            if not keys:
                raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
            already_owned.update(keys)
            result[card_ordinal] = keys
    if set(result) != {card.ordinal for card in source.cards}:
        raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
    return result


def _card_table_keys(source: CardAnalysisSource) -> set[str]:
    keys: set[str] = set()
    for card in source.cards:
        table_key = card.card.get("table_key")
        if isinstance(table_key, str) and table_key:
            keys.add(table_key)
    return keys


def _table_key(block: Any) -> str | None:
    value = block.attributes.get("table_key")
    return value if isinstance(value, str) and value else None


def _heading_scopes(
    source: CardAnalysisSource, selector_version: str = SELECTOR_VERSION,
) -> dict[str, tuple[SectionKind, ...]]:
    """Assign each block to active matching heading scopes in source order."""

    scopes: dict[str, tuple[SectionKind, ...]] = {}
    active: list[tuple[int, tuple[SectionKind, ...]]] = []
    for block in source.blocks:
        if block.type.casefold() in {"paragraph", "text"}:
            level = _heading_level(block.text, selector_version)
            if level is not None:
                while active and active[-1][0] >= level:
                    active.pop()
                kinds = _section_kinds(block.text)
                if kinds:
                    active.append((level, kinds))
        selected = {section for _level, kinds in active for section in kinds}
        if selected:
            scopes[block.block_key] = tuple(section for section in SECTION_KINDS if section in selected)
    return scopes


def _source_bindings(
    sources: Sequence[CardAnalysisSource],
) -> tuple[list[CardAnalysisSource], list[CardSourceBinding]]:
    grouped: dict[str, dict[str, Any]] = {}
    document_hashes: dict[UUID, str] = {}
    for source in sources:
        previous_hash = document_hashes.setdefault(source.document_version_id, source.source_sha256)
        if previous_hash != source.source_sha256:
            raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
        current = grouped.get(source.source_sha256)
        if current is None:
            grouped[source.source_sha256] = {
                "source": source,
                "document_version_ids": [source.document_version_id],
            }
        elif source.document_version_id not in current["document_version_ids"]:
            current["document_version_ids"].append(source.document_version_id)
    # Sources are ordered by identity, blocks keep their original order.  Input
    # collection order is not an identity and must not perturb units/batches.
    selected = [grouped[source_hash]["source"] for source_hash in sorted(grouped)]
    bindings = [
        CardSourceBinding(
            source_sha256=source.source_sha256,
            selected_document_version_id=source.document_version_id,
            selected_structure_id=source.structure_id,
            selected_manifest_id=source.manifest_id,
            document_version_ids=grouped[source.source_sha256]["document_version_ids"],
        )
        for source in selected
    ]
    return selected, bindings


def unit_characters(unit: CardAnalysisUnit) -> int:
    """Unicode character count of a unit's frozen source text (packing measure)."""

    return sum(len(block.text) for block in unit.blocks)


def _split_segment_unit(unit: CardAnalysisUnit, batch_max_chars: int) -> list[CardAnalysisUnit]:
    """결정 C15 (v4): consecutive block parts of a segment unit above ``batch_max_chars``.

    Blocks keep their unit order and are packed greedily; a part is closed
    when the next block would exceed the limit.  A unit within the limit is
    returned unchanged (v3 id).  One block above the limit is
    ``input_budget_exceeded``; it is never cut.
    """

    if unit_characters(unit) <= batch_max_chars:
        return [unit]
    groups: list[list[CardUnitBlock]] = []
    current: list[CardUnitBlock] = []
    characters = 0
    for block in unit.blocks:
        size = len(block.text)
        if size > batch_max_chars:
            raise CardAnalysisSelectionError(INPUT_BUDGET_EXCEEDED)
        if current and characters + size > batch_max_chars:
            groups.append(current)
            current, characters = [], 0
        current.append(block)
        characters += size
    groups.append(current)
    base = unit.model_dump(mode="python")
    return [
        CardAnalysisUnit.model_validate({
            **base,
            "unit_id": f"{unit.unit_id}{SEGMENT_PART_SUFFIX}{number}",
            "blocks": [block.model_dump(mode="python") for block in blocks],
        })
        for number, blocks in enumerate(groups, start=1)
    ]


def pack_analysis_batches(
    units: Sequence[CardAnalysisUnit | Mapping[str, Any]],
    *,
    policy: CardBatchPolicy | Mapping[str, Any] | None = None,
) -> list[CardAnalysisBatch]:
    """Greedily pack source-ordered units without truncation or reordering.

    A single unit above ``batch_max_chars`` is ``input_budget_exceeded``; it is
    never cut.
    """

    parsed_policy = policy if isinstance(policy, CardBatchPolicy) else CardBatchPolicy.model_validate(policy or {})
    parsed_units = [
        unit if isinstance(unit, CardAnalysisUnit) else CardAnalysisUnit.model_validate(unit)
        for unit in units
    ]
    batches: list[CardAnalysisBatch] = []
    current_ids: list[str] = []
    current_characters = 0

    def flush() -> None:
        nonlocal current_ids, current_characters
        if not current_ids:
            return
        batches.append(
            CardAnalysisBatch(
                batch_index=len(batches),
                unit_ids=current_ids,
                source_characters=current_characters,
            )
        )
        current_ids = []
        current_characters = 0

    for unit in parsed_units:
        characters = unit_characters(unit)
        if characters > parsed_policy.batch_max_chars:
            raise CardAnalysisSelectionError(INPUT_BUDGET_EXCEEDED)
        if current_ids and (
            len(current_ids) >= parsed_policy.batch_size
            or current_characters + characters > parsed_policy.batch_max_chars
        ):
            flush()
        current_ids.append(unit.unit_id)
        current_characters += characters
    flush()
    return batches


def analysis_call_budget(batch_count: int, *, repair_attempts: int = 1) -> CardCallBudget:
    """Fixed call counts: B extract + 3 roles + 1 synthesis; repair doubles the maximum."""

    policy = CardBatchPolicy(repair_attempts=repair_attempts)
    if isinstance(batch_count, bool) or not isinstance(batch_count, int) or batch_count < 0:
        raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
    normal = batch_count + 4
    return CardCallBudget(
        batch_count=batch_count,
        normal_calls=normal,
        maximum_calls=normal * (policy.repair_attempts + 1),
    )


def select_analysis_units(
    sources: Sequence[CardAnalysisSource | Mapping[str, Any]],
    *,
    policy: CardBatchPolicy | Mapping[str, Any] | None = None,
    selector_version: str = SELECTOR_VERSION,
) -> CardUnitSelection:
    """Build the complete deterministic selection from HP-01 data.

    ``selector_version`` comes from the pinned policy (``card.selector``; v1
    rows have none and use ``card-sections-v1``).  An unknown version is
    ``card_source_selection_incomplete``.
    """

    if selector_version not in SELECTOR_SHA256_BY_VERSION:
        raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
    try:
        parsed_sources = [
            source if isinstance(source, CardAnalysisSource) else CardAnalysisSource.model_validate(source)
            for source in sources
        ]
    except (TypeError, ValueError):
        raise CardAnalysisSelectionError(SELECTION_INCOMPLETE) from None
    selected_sources, bindings = _source_bindings(parsed_sources)
    split_limit: int | None = None
    if selector_version == SELECTOR_VERSION_V4:
        # 결정 C15: the split limit is the pinned policy's packing limit.
        parsed_policy = policy if isinstance(policy, CardBatchPolicy) else CardBatchPolicy.model_validate(policy or {})
        split_limit = parsed_policy.batch_max_chars
    all_units: list[CardAnalysisUnit] = []
    candidate_blocks: list[CardSelectorCandidateBlock] = []
    selected_blocks: list[CardSelectorSelectedBlock] = []
    selector_order: dict[tuple[str, str], int] = {}
    present_sections: set[SectionKind] = set()

    for source in selected_sources:
        by_key = {block.block_key: block for block in source.blocks}
        source_order = {block.block_key: ordinal for ordinal, block in enumerate(source.blocks)}
        selector_order.update(
            ((source.source_sha256, block.block_key), ordinal)
            for ordinal, block in enumerate(source.blocks)
        )
        scopes = _heading_scopes(source, selector_version)
        candidate_blocks.extend(
            CardSelectorCandidateBlock(source_sha256=source.source_sha256, block_key=block.block_key)
            for block in source.blocks
            if block.block_key in scopes
        )
        card_owned = _card_owned_keys(source)
        card_tables = _card_table_keys(source)
        excluded = set(_toc_block_keys(source))
        if selector_version in _V3_EXCLUSION_SELECTORS:
            excluded.update(_toc_entry_keys_v3(source))
        for keys in card_owned.values():
            excluded.update(keys)
        excluded.update(block.block_key for block in source.blocks if _table_key(block) in card_tables)

        ordered: list[tuple[int, int, CardAnalysisUnit]] = []
        assigned: set[str] = set()
        for card in source.cards:
            keys = [key for key in card_owned[card.ordinal] if key in by_key and key not in assigned]
            if not keys:
                raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
            assigned.update(keys)
            unit = CardAnalysisUnit(
                unit_id=f"card:{source.source_sha256}:{card.ordinal}:{card.normalized_id}",
                source_sha256=source.source_sha256,
                document_version_id=source.document_version_id,
                structure_id=source.structure_id,
                manifest_id=source.manifest_id,
                kind="card",
                ordinal=card.ordinal,
                normalized_id=card.normalized_id,
                section_kinds=[],
                blocks=[CardUnitBlock(block_key=key, text=by_key[key].text) for key in keys],
                page_range=card.page_range,
                mapping_status=card.mapping_status,
            )
            ordered.append((min(source_order[key] for key in keys), 0, unit))

        for segment in sorted(source.segments, key=lambda row: row.ordinal):
            keys = [
                key
                for key in segment.source_block_keys
                if key in by_key and key in scopes and key not in excluded and key not in assigned
            ]
            if not keys:
                continue
            assigned.update(keys)
            kinds = tuple(
                section for section in SECTION_KINDS if any(section in scopes[key] for key in keys)
            )
            if not kinds:
                continue
            if selector_version in _V3_EXCLUSION_SELECTORS and not _has_body_text([by_key[key] for key in keys]):
                continue  # 결정 B30: a title-only unit is not source text
            present_sections.update(kinds)
            selected_blocks.extend(
                CardSelectorSelectedBlock(
                    source_sha256=source.source_sha256,
                    block_key=key,
                    section_kinds=list(scopes[key]),
                )
                for key in keys
            )
            unit = CardAnalysisUnit(
                unit_id=f"segment:{source.source_sha256}:{segment.segment_id}",
                source_sha256=source.source_sha256,
                document_version_id=source.document_version_id,
                structure_id=source.structure_id,
                manifest_id=source.manifest_id,
                kind="segment",
                ordinal=segment.ordinal,
                normalized_id=None,
                section_kinds=list(kinds),
                blocks=[CardUnitBlock(block_key=key, text=by_key[key].text) for key in keys],
                page_range=segment.page_range,
                mapping_status=segment.mapping_status,
            )
            parts = [unit] if split_limit is None else _split_segment_unit(unit, split_limit)
            ordered.extend(
                (min(source_order[block.block_key] for block in part.blocks), 1, part) for part in parts
            )
        ordered.sort(key=lambda row: (row[0], row[1], row[2].ordinal, row[2].unit_id))
        all_units.extend(unit for _ordinal, _kind, unit in ordered)

    unit_ids = [unit.unit_id for unit in all_units]
    if len(unit_ids) != len(set(unit_ids)):
        raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
    batches = pack_analysis_batches(all_units, policy=policy)
    missing = [section for section in SECTION_KINDS if section not in present_sections]
    candidate_blocks.sort(key=lambda row: (row.source_sha256, selector_order[(row.source_sha256, row.block_key)]))
    selected_blocks.sort(key=lambda row: (row.source_sha256, selector_order[(row.source_sha256, row.block_key)]))
    return CardUnitSelection(
        units=all_units,
        batches=batches,
        missing_sections=missing,
        selector=CardSelector(
            version=selector_version,
            sha256=SELECTOR_SHA256_BY_VERSION[selector_version],
            candidate_blocks=candidate_blocks,
            selected_blocks=selected_blocks,
        ),
        source_bindings=bindings,
    )


def card_company_binding(knowledge: Any) -> CardCompanyBinding:
    """The ``company_binding`` of a resolved ``CompanyKnowledgeContext``."""

    return CardCompanyBinding(
        graph_version_id=knowledge.graph.id,
        graph_sha256=knowledge.graph.graph_sha256,
        profile_version_id=knowledge.profile.id,
        profile_sha256=knowledge.profile.profile_sha256,
        ontology_version=knowledge.ontology_row.version,
        ontology_sha256=knowledge.ontology_row.sha256,
    )


def freeze_card_analysis_input(
    selection: CardUnitSelection | Mapping[str, Any],
    *,
    company_binding: CardCompanyBinding | Mapping[str, Any],
) -> CardAnalysisInput:
    """Bind a selection to the active company binding and the strict wire schema."""

    try:
        parsed = selection if isinstance(selection, CardUnitSelection) else CardUnitSelection.model_validate(selection)
        binding = (
            company_binding
            if isinstance(company_binding, CardCompanyBinding)
            else CardCompanyBinding.model_validate(company_binding)
        )
        if SELECTOR_SHA256_BY_VERSION.get(parsed.selector.version) != parsed.selector.sha256:
            raise ValueError("selector_sha256_mismatch")
        value = CardAnalysisInput(
            company_binding=binding,
            units=parsed.units,
            batches=parsed.batches,
            missing_sections=parsed.missing_sections,
            selector=parsed.selector,
        )
        validate_payload(value.model_dump(mode="json"), CARD_ANALYSIS_INPUT_SCHEMA)
    except (TypeError, ValueError, ValidationError, SchemaValidationError):
        raise CardAnalysisSelectionError(SELECTION_INCOMPLETE) from None
    return value


def card_analysis_sources(
    session: Session,
    bundle: Mapping[str, Any],
    structures: Mapping[Any, Mapping[str, Any]],
) -> list[CardAnalysisSource]:
    """Project a ready bundle into selection sources (pinned structures + HP-01 manifest).

    Documents are read in ``(content_sha256, document_version_id)`` order.  A
    missing manifest, hash mismatch, missing page or unreadable page map is
    ``card_source_selection_incomplete``; page 1 is never invented.
    """

    sources: list[CardAnalysisSource] = []
    for document in sorted(bundle["documents"], key=lambda row: (row["content_sha256"], row["document_version_id"])):
        try:
            structure_id = UUID(str(document["structure_id_at_confirmation"]))
        except (KeyError, TypeError, ValueError):
            raise CardAnalysisSelectionError(SELECTION_INCOMPLETE) from None
        manifest = document_segments._manifest_for_structure(session, structure_id)  # noqa: PLC2701
        structure = structures.get(str(structure_id)) or structures.get(structure_id) or {}
        if manifest is None or manifest.source_sha256 != document["content_sha256"]:
            raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
        try:
            blocks = []
            for block in structure.get("blocks", []):
                if not isinstance(block, Mapping):
                    continue
                blocks.append({
                    "block_key": block["block_key"], "parent_block_key": block.get("parent_block_key"),
                    "type": block.get("type", block.get("block_type", "text")),
                    "page": block["page"], "bbox": block.get("bbox"),
                    "text": block.get("text", block.get("content", "")) or "",
                    "confidence": block.get("confidence"), "attributes": block.get("attributes") or {},
                })
            # HP-01 keeps page mapping as a read-time projection: open the
            # structure store only when a pinned para-page-map exists.
            store = None
            if document_segments.latest_para_page_map_snapshot(session, structure_id) is not None:
                store = object_store(namespaces=("structure",), read_namespaces=("structure",))
            cards = document_segments.requirement_cards(session, structure_id, store)
            segment_view = document_segments.segments_view(session, structure_id, store)
            projected = {row["segment_id"]: row for row in segment_view["segments"]}
            segment_rows = session.scalars(
                select(DocumentSegment)
                .where(DocumentSegment.manifest_id == manifest.id)
                .order_by(DocumentSegment.ordinal.asc())
            ).all()
            if set(projected) != {row.segment_id for row in segment_rows}:
                raise ValueError("segment_projection_mismatch")
            segments = [
                {
                    # Unit identity is the persisted DocumentSegment row UUID;
                    # ``segment_id`` (``seg-<hex>``) only joins the projection.
                    "segment_id": row.id, "ordinal": row.ordinal,
                    "start_locator": dict(row.start_locator or {}),
                    "source_block_keys": list(row.source_block_keys or []),
                    "page_range": projected[row.segment_id]["page_range"],
                    "mapping_status": projected[row.segment_id]["mapping_status"],
                }
                for row in segment_rows
            ]
            sources.append(CardAnalysisSource.model_validate({
                "source_sha256": manifest.source_sha256,
                "document_version_id": document["document_version_id"],
                "structure_id": structure_id, "manifest_id": manifest.id,
                "blocks": blocks, "cards": cards, "segments": segments,
            }))
        except (KeyError, ObjectStoreError, document_segments.SegmentViewError, TypeError, ValueError):
            raise CardAnalysisSelectionError(SELECTION_INCOMPLETE) from None
    return sources


def card_requirement_units(
    card_input: CardAnalysisInput,
    bundle: Mapping[str, Any],
    structures: Mapping[Any, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Retrieval source units (``SOURCE_UNIT_KEYS``) for the frozen card units, in order.

    ``requirements[].id`` of the v2 input is the frozen ``unit_id``.  The page
    locator is the first selected block's stored page; the unit's own
    ``page_range`` stays a separate projection.
    """

    document_ordinals = {
        UUID(str(document["document_version_id"])): int(document["ordinal"])
        for document in bundle["documents"]
    }
    rows: list[dict[str, Any]] = []
    for unit in card_input.units:
        structure = structures.get(str(unit.structure_id)) or structures.get(unit.structure_id)
        if not isinstance(structure, Mapping):
            raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
        block_positions = {
            block["block_key"]: (order, block["page"])
            for order, block in enumerate(structure.get("blocks", []))
            if isinstance(block, Mapping) and "block_key" in block and "page" in block
        }
        selected = [block_positions.get(block.block_key) for block in unit.blocks]
        if any(position is None for position in selected):
            raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
        block_order, page = min(selected)  # type: ignore[type-var]
        if type(page) is not int or page < 1:
            raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
        document_ordinal = document_ordinals.get(unit.document_version_id)
        if document_ordinal is None:
            raise CardAnalysisSelectionError(SELECTION_INCOMPLETE)
        rows.append({
            "requirement_id": unit.unit_id,
            "document_version_id": str(unit.document_version_id), "structure_id": str(unit.structure_id),
            "source_sha256": unit.source_sha256, "document_ordinal": document_ordinal,
            "page": page, "block_order": block_order, "locator_type": "page", "locator": {"page": page},
            "text": "\n".join(block.text for block in unit.blocks),
            "document_requirement_ids": [unit.normalized_id] if unit.normalized_id else [],
        })
    return rows


__all__ = [
    "INPUT_BUDGET_EXCEEDED",
    "SECTION_KEYWORDS",
    "SECTION_KINDS",
    "SELECTION_INCOMPLETE",
    "BULLET_HEADING_LEVEL",
    "BULLET_HEADING_MAX_CHARACTERS",
    "BULLET_HEADING_SYMBOLS",
    "SELECTOR_SHA256",
    "SELECTOR_SHA256_BY_VERSION",
    "SELECTOR_SHA256_V2",
    "SEGMENT_PART_SUFFIX",
    "SELECTOR_SHA256_V3",
    "SELECTOR_SHA256_V4",
    "SELECTOR_VERSION",
    "SELECTOR_VERSION_V2",
    "SELECTOR_VERSION_V3",
    "SELECTOR_VERSION_V4",
    "TOC_ENTRY_MAX_CHARACTERS",
    "CardAnalysisSelectionError",
    "analysis_call_budget",
    "card_analysis_sources",
    "card_company_binding",
    "card_requirement_units",
    "freeze_card_analysis_input",
    "pack_analysis_batches",
    "select_analysis_units",
    "unit_characters",
]
