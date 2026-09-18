"""사업명 이름 대조 사다리 (spec §4.1).

`experiments/lifecycle-linkage-survey/scripts/name_normalize.py`를 동작 그대로 옮긴
순수 함수다. 수집 색인의 `title_normalized`와 후보 대조가 이 모듈 하나를 쓴다.
공식 통합번호가 없는 이름 일치는 사람 확인 후보를 만들 근거일 뿐 확정 관계가
아니다. I/O와 네트워크 호출이 없다.

전략 순서는 정밀도 순서다: ``full → breaking_split → normalized →
longest_fragment → prefix12``. 판정은 원천 제목의 변형이 대상
``title_normalized``에 포함되면 그 전략으로 일치한다.
"""

from __future__ import annotations

import re
from typing import Iterator

# The measured search-breaking set is intentionally narrower than the set of
# punctuation that normalization can rewrite.  U+00B7 ``·`` was isolated by
# the six-query T-1b probe: ``개발·제작`` returned zero while controls without
# that character returned rows.  U+0026 ``&``, U+2018 ``‘``, U+2019 ``’``, and
# U+2022 ``•`` were each confirmed by the 24-call character-tolerance probe:
# their character-bearing query returned zero while its character-removed
# control returned rows.  No other character is in this confirmed set.
CONFIRMED_BREAKING_CHARS = "·&‘’•"

# This is the visual middle-dot/bullet family used by normalization and the
# isolation fixture builder.  It is *not* a claim that the whole family is
# broken: U+30FB ``・``, U+2027 ``‧``, and U+2024 ``․`` were measured harmless by
# character tolerance.  U+2219 ``∙`` remains unknown because it did not occur
# in the local 650-record pre-specification raw sample, so it was not tested.
MIDDLE_DOT_CHARS = "·・‧․•∙"
# Keep the public spelling used by the existing normalization tests for the
# visual family; strategy decisions use the explicit classifications above.
DOT_CHARS = MIDDLE_DOT_CHARS

# These characters were measured harmless in the available probes: brackets,
# punctuation, whitespace, ~, /, _, corner quotes, and three visual dot
# codepoints.  This list is separate from the broader separator set used by
# normalization and must not be used as a breaking-split delimiter.
CONFIRMED_HARMLESS_CHARS = "(),-「」[],. ~/_『』・‧․"

# U+2219 was the only requested visual-dot target absent from local raw, so it
# remains unknown rather than being treated as either safe or breaking.
UNKNOWN_CHARS = "∙"

BRACKET_CHARS = "「」『』【】〔〕《》〈〉[]()（）<>{}"
QUOTE_CHARS = "'‘’\"“”"
MISC_CHARS = ",./~_&\\-+*:;|!?%#@"

SEPARATOR_CHARS = DOT_CHARS + BRACKET_CHARS + QUOTE_CHARS + MISC_CHARS
_SEPARATOR_RE = re.compile("[" + re.escape(SEPARATOR_CHARS) + "]")
_BREAKING_RE = re.compile("[" + re.escape(CONFIRMED_BREAKING_CHARS) + "]")
_WHITESPACE_RE = re.compile(r"\s+")

# Leading status tags that the announcing agency adds to one side only.
LEADING_TAGS = ("재공고", "긴급", "정정", "변경", "취소", "연기", "공고")

MIN_FRAGMENT_CHARS = 6
PREFIX_CHARS = 12
SEARCH_STRATEGIES = (
    "full",
    "breaking_split",
    "normalized",
    "longest_fragment",
    "prefix12",
)


def collapse(name: str) -> str:
    """Collapse whitespace runs and trim, leaving every other character."""

    return _WHITESPACE_RE.sub(" ", name).strip()


def normalize(name: str) -> str:
    """Replace every separator with a space and drop leading status tags."""

    text = collapse(_SEPARATOR_RE.sub(" ", name))
    while True:
        head, _, rest = text.partition(" ")
        if head in LEADING_TAGS:
            text = rest
            continue
        return text


def fragments(name: str) -> list[str]:
    """Split on separators, preserving each returned piece from ``name``.

    In particular, do not call :func:`collapse` here.  The fragment strategy
    is deliberately a literal-substring fallback: a server that performs a
    plain substring lookup should still be able to receive exactly the text
    that appeared in the order-plan title.
    """

    return [part.strip() for part in _SEPARATOR_RE.split(name) if part.strip()]


def breaking_split(name: str) -> str | None:
    """Return the longest fragment after splitting confirmed breakers only.

    Parentheses, spaces, confirmed-harmless punctuation, and unknown U+2219
    remain in the returned literal substring.  This is deliberately narrower
    than ``longest_fragment``: it removes only measured failure dimensions
    without throwing away context that improves precision.
    """

    if not _BREAKING_RE.search(name):
        return None
    candidates = [part.strip() for part in _BREAKING_RE.split(name) if part.strip()]
    candidates = [part for part in candidates if len(part) >= MIN_FRAGMENT_CHARS]
    if not candidates:
        return None
    return max(candidates, key=len)


def longest_fragment(name: str) -> str | None:
    """The longest separator-free run, which stays a literal substring.

    A fragment is still an exact substring of the original name, so it survives
    a server-side partial match even when the endpoint chokes on punctuation.
    """

    candidates = [f for f in fragments(name) if len(f) >= MIN_FRAGMENT_CHARS]
    if not candidates:
        return None
    # ``fragments`` only trims the edges of an actual split piece, so the
    # chosen value remains a contiguous substring of the original title.
    return max(candidates, key=len)


def search_variants(name: str) -> list[tuple[str, str]]:
    """Ordered (strategy, query) ladder, most precise first, deduplicated."""

    def candidates() -> Iterator[tuple[str, str]]:
        full = collapse(name)
        # `full` is the measured baseline: it preserves punctuation and tests
        # whether the endpoint accepts the source spelling unchanged.
        yield "full", full
        breaking_fragment = breaking_split(name)
        if breaking_fragment:
            # Split only on the five confirmed breaking characters.  The
            # result is still a contiguous source substring, while harmless
            # punctuation and unknown U+2219 remain available as context.
            yield "breaking_split", breaking_fragment
        # `normalized` targets spelling-only differences such as middle-dot
        # variants, brackets, and leading status tags.
        yield "normalized", normalize(name)
        fragment = longest_fragment(name)
        if fragment:
            # `longest_fragment` targets a query parser/server that fails on a
            # punctuation-bearing full value while retaining literal-match
            # safety by sending a contiguous source substring.
            yield "longest_fragment", fragment
        # `prefix12` is the broadest observed fallback: the earlier survey
        # recovered misses with a short prefix when the remaining wording
        # differed, so it is retained as a candidate rather than an automatic
        # relationship confirmation.
        # The earlier 80.5% measurement used the collapsed source spelling,
        # not a punctuation-normalized spelling.  Keep that measurement
        # comparable and do not claim normalization caused these hits.
        yield "prefix12", collapse(name)[:PREFIX_CHARS].strip()

    seen: set[str] = set()
    ladder: list[tuple[str, str]] = []
    for strategy, query in candidates():
        if len(query) < MIN_FRAGMENT_CHARS or query in seen:
            continue
        seen.add(query)
        ladder.append((strategy, query))
    return ladder


__all__ = [
    "BRACKET_CHARS",
    "CONFIRMED_BREAKING_CHARS",
    "CONFIRMED_HARMLESS_CHARS",
    "DOT_CHARS",
    "LEADING_TAGS",
    "MIDDLE_DOT_CHARS",
    "MIN_FRAGMENT_CHARS",
    "PREFIX_CHARS",
    "SEARCH_STRATEGIES",
    "SEPARATOR_CHARS",
    "UNKNOWN_CHARS",
    "breaking_split",
    "collapse",
    "fragments",
    "longest_fragment",
    "normalize",
    "search_variants",
]
