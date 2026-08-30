#!/usr/bin/env python3
"""Isolate why one pre-specification name search returns no result.

The probe makes exactly six single-page requests for one case.  It changes one
query dimension at a time: a full-name baseline, a punctuation-free token, a
token with a leading year, a middle-dot fragment, a parenthesized fragment,
and the same full-name query with ``%20`` instead of ``+`` for spaces.

The response for each request is written through ``survey.write_raw_page`` so
the established raw-page schema and service-key hygiene are shared with the
collector.  The main result document contains only safe query/result metadata;
it does not copy contact fields from the raw response.

With ``--char-tolerance``, the same runner reads local pre-specification raw,
selects one short literal sample for each present configured character target,
and sends one character-bearing query plus its character-removed control.  The
target character is always at the beginning or end of the sample, so both
queries remain contiguous substrings of the source name.  Samples whose
control cannot reach the minimum length are skipped as ``unknown``.  The mode
uses a separate artifact/raw subdirectory and keeps the explicit
``--execute`` gate; the fixed target catalog is retained so the historical
24-call measurement can be reproduced.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[2]
sys.path.insert(0, str(_SCRIPT_DIR.parents[1] / "order-plan-screening" / "scripts"))
sys.path.insert(0, str(_SCRIPT_DIR))

from common import ExperimentError, write_json_new  # noqa: E402
from endpoints import ENDPOINTS, KST  # noqa: E402
import name_normalize  # noqa: E402
import survey  # noqa: E402


PROBE_SCHEMA = "bidops.lifecycle-search-isolation-probe.v1"
CHAR_TOLERANCE_SCHEMA = "bidops.lifecycle-search-char-tolerance-probe.v2"
SEARCH_FIELD = "prdctClsfcNoNm"
MAX_REQUESTS = 6
DEFAULT_CHAR_TOLERANCE_MAX_REQUESTS = 24
TOLERANCE_MIN_CONTROL_CHARS = name_normalize.MIN_FRAGMENT_CHARS
CHAR_TOLERANCE_ARTIFACT = "char-tolerance-probe.json"
CHAR_TOLERANCE_RAW_DIR = "char-tolerance"
DEFAULT_NAME = "2026 디지털새싹 교재 개발·제작 7종 용역(하반기)"
DEFAULT_EXPECTED_SPEC_NO = "R26BD00267196"
DEFAULT_FROM_DATE = date(2026, 1, 1)
DEFAULT_TO_DATE = date(2026, 8, 29)
DEFAULT_OUTPUT_DIR = (
    _REPO_ROOT
    / "data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/search-isolation"
)

_WORD_RE = re.compile(r"[0-9A-Za-z가-힣]+")
_HANGUL_RE = re.compile(r"[가-힣]+")
_MIDDLE_DOT_RE = re.compile(
    r"[0-9A-Za-z가-힣]+["
    + re.escape(name_normalize.MIDDLE_DOT_CHARS)
    + r"][0-9A-Za-z가-힣]+"
)
_PAREN_WORD_RE = re.compile(r"[0-9A-Za-z가-힣]+\([^()]*\)")
_PAREN_RE = re.compile(r"\([^()]*\)")


@dataclass(frozen=True)
class QueryVariant:
    number: int
    strategy: str
    query: str
    quote_via: Callable[..., str]
    encoding: str
    isolation_target: str


@dataclass(frozen=True)
class ToleranceTarget:
    label: str
    chars: tuple[str, ...]

    @property
    def display(self) -> str:
        return "".join(self.chars)


@dataclass(frozen=True)
class ToleranceCase:
    target: ToleranceTarget
    query: str
    control_query: str
    expected_spec_no: str
    source_name: str = ""
    boundary: str = ""

    @property
    def sample_source_spec_no(self) -> str:
        """The immutable local raw record used to construct this case."""

        return self.expected_spec_no


@dataclass(frozen=True)
class ToleranceSkip:
    target: ToleranceTarget
    reason_code: str
    reason: str
    occurrence_count: int


@dataclass(frozen=True)
class ToleranceSelection:
    cases: tuple[ToleranceCase, ...]
    skipped: tuple[ToleranceSkip, ...]


@dataclass(frozen=True)
class _ToleranceWindow:
    query: str
    control_query: str
    boundary: str
    available_side_length: int


CHAR_TOLERANCE_TARGETS = (
    # Keep the catalog stable for reruns of the 24-call measurement.  Whether
    # a target is confirmed breaking, confirmed harmless, or still unknown is
    # recorded in name_normalize; absence from local raw still causes a skip.
    ToleranceTarget("ampersand", ("&",)),
    ToleranceTarget("tilde", ("~",)),
    ToleranceTarget("slash", ("/",)),
    ToleranceTarget("right_single_quote", ("’",)),
    ToleranceTarget("left_single_quote", ("‘",)),
    ToleranceTarget("underscore", ("_",)),
    ToleranceTarget("corner_quote_open", ("『",)),
    ToleranceTarget("corner_quote_close", ("』",)),
    ToleranceTarget("middle_dot_u30fb", ("・",)),
    ToleranceTarget("middle_dot_u2027", ("‧",)),
    ToleranceTarget("middle_dot_u2024", ("․",)),
    ToleranceTarget("bullet_u2022", ("•",)),
    ToleranceTarget("bullet_operator_u2219", ("∙",)),
)


def _longest(values: Sequence[str], fallback: str) -> str:
    return max(values, key=len) if values else fallback


def build_variants(name: str) -> list[QueryVariant]:
    """Build the six fixed experiment dimensions for a supplied case.

    The default case yields the exact six strings in the task.  For another
    case, #2--#5 are derived from its longest Hangul token, leading numeric
    prefix, middle-dot component, and parenthesized component respectively;
    this keeps ``--name`` useful without inventing a second set of CLI query
    arguments.
    """

    words = _WORD_RE.findall(name)
    hangul_token = _longest(_HANGUL_RE.findall(name), _longest(words, name))
    leading_year = re.match(r"\s*(\d{4})", name)
    if leading_year:
        token_with_space = f"{leading_year.group(1)} {hangul_token}"
    else:
        token_with_space = " ".join(words[:2]) if len(words) >= 2 else hangul_token
    middle_dot = _longest(_MIDDLE_DOT_RE.findall(name), hangul_token)
    parenthesized = _longest(
        _PAREN_WORD_RE.findall(name) or _PAREN_RE.findall(name), hangul_token
    )

    return [
        QueryVariant(
            1,
            "full_quote_plus",
            name,
            urllib.parse.quote_plus,
            "quote_plus",
            "대조군: 전체 이름 검색 실패가 재현되는지 확인",
        ),
        QueryVariant(
            2,
            "token",
            hangul_token,
            urllib.parse.quote_plus,
            "quote_plus",
            "특수문자·공백 없는 순수 한글 토큰; 적중하면 레코드 구간과 부분일치를 함께 지지",
        ),
        QueryVariant(
            3,
            "token_with_space",
            token_with_space,
            urllib.parse.quote_plus,
            "quote_plus",
            "#2에 공백과 선행 연도 토큰을 추가해 공백 처리를 확인",
        ),
        QueryVariant(
            4,
            "middle_dot",
            middle_dot,
            urllib.parse.quote_plus,
            "quote_plus",
            "가운뎃점이 포함된 부분만 보내 특수문자 처리를 확인",
        ),
        QueryVariant(
            5,
            "parentheses",
            parenthesized,
            urllib.parse.quote_plus,
            "quote_plus",
            "괄호가 포함된 부분만 보내 괄호 처리를 확인",
        ),
        QueryVariant(
            6,
            "full_quote_percent20",
            name,
            urllib.parse.quote,
            "quote",
            "#1과 문자열은 같고 공백 인코딩만 +에서 %20으로 변경",
        ),
    ]


def _public_query(
    variant: QueryVariant,
    from_date: date,
    to_date: date,
    rows: int,
) -> dict[str, str]:
    query = ENDPOINTS["prespec_search"].query_builder(from_date, to_date, 1, rows)
    query[SEARCH_FIELD] = variant.query
    return query


def public_query_string(query: dict[str, str], variant: QueryVariant) -> str:
    """Encode only the public query, matching SurveyFetcher's wire encoding."""

    if "serviceKey" in query:
        raise ExperimentError("secret_stored", "공개 query에 인증키가 있습니다")
    return urllib.parse.urlencode(query, quote_via=variant.quote_via)


def _remove_target(text: str, target: ToleranceTarget) -> str:
    for char in target.chars:
        text = text.replace(char, "")
    return text


def _tolerance_forbidden_chars(target: ToleranceTarget) -> set[str]:
    unknown_chars = {
        char for candidate in CHAR_TOLERANCE_TARGETS for char in candidate.chars
    }
    unsafe_dot_chars = set(name_normalize.MIDDLE_DOT_CHARS)
    return (unknown_chars | unsafe_dot_chars) - set(target.chars)


def _edge_tolerance_window(
    name: str,
    target: ToleranceTarget,
    start: int,
    min_control_chars: int,
) -> _ToleranceWindow | None:
    """Build the shortest safe window for one target occurrence.

    ``start`` points at the target text.  The target is kept at the end of a
    left-hand window or the beginning of a right-hand window.  Only whitespace
    at the edge away from the target is trimmed; therefore the returned query
    and its control remain exact contiguous slices of ``name`` and the control
    is exactly the query with the target removed.
    """

    target_text = target.display
    target_end = start + len(target_text)
    forbidden = _tolerance_forbidden_chars(target)
    left = name[:start]
    right = name[target_end:]
    side_lengths = {"left": len(left), "right": len(right)}
    if max(side_lengths.values(), default=0) < min_control_chars:
        return None

    # Use only the longer side as requested.  A tie is resolved toward the
    # right side so selection remains deterministic without relying on raw
    # ordering.  If that side cannot provide a safe minimum window, skip the
    # target rather than silently changing the experiment design.
    side = "left" if len(left) > len(right) else "right"
    source = left if side == "left" else right
    if len(source) < min_control_chars:
        return None
    for width in range(min_control_chars, len(source) + 1):
        raw_context = source[-width:] if side == "left" else source[:width]
        # Whitespace at this edge is outside the target-facing boundary, so
        # removing it still leaves a source substring.  Whitespace next to the
        # target is intentionally retained.
        context = raw_context.lstrip() if side == "left" else raw_context.rstrip()
        if len(context) < min_control_chars:
            continue
        if target_text in context or any(char in context for char in forbidden):
            continue
        if side == "left":
            query = context + target_text
            boundary = "end"
        else:
            query = target_text + context
            boundary = "start"
        control = _remove_target(query, target)
        if control != context:
            continue
        if query not in name or control not in name:
            continue
        if not (query.endswith(target_text) if side == "left" else query.startswith(target_text)):
            continue
        return _ToleranceWindow(
            query=query,
            control_query=control,
            boundary=boundary,
            available_side_length=side_lengths[side],
        )
    return None


def _boundary_tolerance_windows(
    name: str,
    target: ToleranceTarget,
    min_control_chars: int = TOLERANCE_MIN_CONTROL_CHARS,
) -> list[_ToleranceWindow]:
    """Return one longer-side window for every usable target occurrence."""

    if min_control_chars < 1:
        raise ExperimentError(
            "invalid_tolerance_minimum", "대조군 최소 길이는 1 이상이어야 합니다"
        )
    target_text = target.display
    if not target_text:
        return []
    # Keep this explicit check close to the occurrence scan.  It prevents a
    # future multi-codepoint target from silently being treated as absent.
    if not all(name.count(char) for char in target.chars):
        return []
    windows: list[_ToleranceWindow] = []
    offset = 0
    while True:
        start = name.find(target_text, offset)
        if start < 0:
            break
        window = _edge_tolerance_window(name, target, start, min_control_chars)
        if window is not None:
            windows.append(window)
        offset = start + len(target_text)
    return windows


def _short_tolerance_fragment(
    name: str,
    target: ToleranceTarget,
    min_control_chars: int = TOLERANCE_MIN_CONTROL_CHARS,
) -> str | None:
    """Return the shortest valid boundary sample for compatibility callers."""

    windows = _boundary_tolerance_windows(name, target, min_control_chars)
    if not windows:
        return None
    return min(windows, key=lambda window: (len(window.query), window.query)).query


def _skip_reason(
    target: ToleranceTarget,
    *,
    occurrence_count: int,
    names_with_target_and_source: int,
    min_control_chars: int,
) -> ToleranceSkip:
    if occurrence_count == 0:
        return ToleranceSkip(
            target=target,
            reason_code="not_present_in_local_prespec",
            reason="로컬 prespec 이름에 대상 문자가 없어 표본을 구성하지 못했습니다; unknown",
            occurrence_count=0,
        )
    if names_with_target_and_source == 0:
        return ToleranceSkip(
            target=target,
            reason_code="missing_source_spec_no",
            reason="대상 문자는 있으나 출처 사전규격번호가 있는 표본을 찾지 못했습니다; unknown",
            occurrence_count=occurrence_count,
        )
    return ToleranceSkip(
        target=target,
        reason_code="boundary_control_too_short_or_unsafe",
        reason=(
            f"대상 문자를 질의 경계에 두고 대조군 {min_control_chars}자를 채우는 "
            "안전한 연속 부분문자열 창을 만들지 못했습니다; unknown"
        ),
        occurrence_count=occurrence_count,
    )


def select_tolerance_selection(
    raw_dir: Path,
    min_control_chars: int = TOLERANCE_MIN_CONTROL_CHARS,
) -> ToleranceSelection:
    """Select cases and explicit unknown skips from local prespec raw."""

    if min_control_chars < 1:
        raise ExperimentError(
            "invalid_tolerance_minimum", "대조군 최소 길이는 1 이상이어야 합니다"
        )
    items = survey.items_from_pages(survey.read_raw_pages(raw_dir / "prespec"))
    cases: list[ToleranceCase] = []
    skipped: list[ToleranceSkip] = []
    for target in CHAR_TOLERANCE_TARGETS:
        choices: list[tuple[_ToleranceWindow, str, str]] = []
        occurrence_count = 0
        names_with_target_and_source = 0
        for item in items:
            name = item.get(SEARCH_FIELD)
            expected = item.get("bfSpecRgstNo")
            if not isinstance(name, str) or target.display not in name:
                continue
            occurrence_count += name.count(target.display)
            if not isinstance(expected, str) or not expected.strip():
                continue
            names_with_target_and_source += 1
            for window in _boundary_tolerance_windows(name, target, min_control_chars):
                choices.append((window, expected.strip(), name))
        if not choices:
            skipped.append(
                _skip_reason(
                    target,
                    occurrence_count=occurrence_count,
                    names_with_target_and_source=names_with_target_and_source,
                    min_control_chars=min_control_chars,
                )
            )
            continue
        window, expected, source_name = min(
            choices,
            key=lambda choice: (
                len(choice[0].query),
                choice[0].query,
                choice[1],
                choice[2],
            ),
        )
        cases.append(
            ToleranceCase(
                target=target,
                query=window.query,
                control_query=window.control_query,
                expected_spec_no=expected,
                source_name=source_name,
                boundary=window.boundary,
            )
        )
    return ToleranceSelection(tuple(cases), tuple(skipped))


def select_tolerance_cases(
    raw_dir: Path,
    min_control_chars: int = TOLERANCE_MIN_CONTROL_CHARS,
) -> list[ToleranceCase]:
    """Select one deterministic local prespec sample for each usable target."""

    return list(select_tolerance_selection(raw_dir, min_control_chars).cases)


def validate_tolerance_case(
    case: ToleranceCase,
    min_control_chars: int = TOLERANCE_MIN_CONTROL_CHARS,
) -> dict[str, bool]:
    """Validate the source-substring invariant for one tolerance case."""

    if min_control_chars < 1:
        raise ExperimentError(
            "invalid_tolerance_minimum", "대조군 최소 길이는 1 이상이어야 합니다"
        )
    target_text = case.target.display
    if not case.source_name or not case.query or not case.control_query:
        raise ExperimentError(
            "invalid_tolerance_case", "문자 관용도 case에 원문과 두 질의가 필요합니다"
        )
    if len(case.control_query) < min_control_chars:
        raise ExperimentError(
            "invalid_tolerance_case", "문자 관용도 대조군이 최소 길이보다 짧습니다"
        )
    if not target_text or case.query.count(target_text) != 1:
        raise ExperimentError(
            "invalid_tolerance_case", "문자 관용도 본 질의에 대상 문자가 정확히 한 번 있어야 합니다"
        )
    if target_text in case.control_query:
        raise ExperimentError(
            "invalid_tolerance_case", "문자 관용도 대조군에 대상 문자가 남아 있습니다"
        )
    if _remove_target(case.query, case.target) != case.control_query:
        raise ExperimentError(
            "invalid_tolerance_case", "문자 관용도가 본 질의에서 대상 문자만 제거한 대조군이 아닙니다"
        )
    query_is_substring = case.query in case.source_name
    control_is_substring = case.control_query in case.source_name
    if not query_is_substring or not control_is_substring:
        raise ExperimentError(
            "invalid_tolerance_case",
            "문자 관용도 본 질의와 대조군은 출처 이름의 연속 부분문자열이어야 합니다",
        )
    if case.query.startswith(target_text):
        boundary = "start"
    elif case.query.endswith(target_text):
        boundary = "end"
    else:
        raise ExperimentError(
            "invalid_tolerance_case", "문자 관용도 대상 문자가 질의 경계에 있어야 합니다"
        )
    if case.boundary and case.boundary != boundary:
        raise ExperimentError(
            "invalid_tolerance_case", "문자 관용도 기록의 경계 방향이 질의와 다릅니다"
        )
    return {
        "query_is_contiguous_substring": query_is_substring,
        "control_query_is_contiguous_substring": control_is_substring,
    }


def validate_tolerance_cases(
    cases: Sequence[ToleranceCase],
    min_control_chars: int = TOLERANCE_MIN_CONTROL_CHARS,
) -> list[dict[str, bool]]:
    """Validate every case before any live request can be made."""

    return [
        validate_tolerance_case(case, min_control_chars) for case in cases
    ]


def _case_metadata(
    case: ToleranceCase,
    validation: dict[str, bool],
) -> dict[str, Any]:
    return {
        "target": case.target.display,
        "target_label": case.target.label,
        "target_codepoints": [f"U+{ord(char):04X}" for char in case.target.chars],
        "sample_source_spec_no": case.sample_source_spec_no,
        "expected_spec_no": case.sample_source_spec_no,
        "sample_source_name": case.source_name,
        "query": case.query,
        "control_query": case.control_query,
        "query_is_contiguous_substring": validation["query_is_contiguous_substring"],
        "control_query_is_contiguous_substring": validation[
            "control_query_is_contiguous_substring"
        ],
        "substring_validation": {
            "query": validation["query_is_contiguous_substring"],
            "control_query": validation["control_query_is_contiguous_substring"],
        },
        "target_boundary": case.boundary,
    }


def _skip_metadata(skip: ToleranceSkip, min_control_chars: int) -> dict[str, Any]:
    return {
        "target": skip.target.display,
        "target_label": skip.target.label,
        "target_codepoints": [f"U+{ord(char):04X}" for char in skip.target.chars],
        "status": "unknown",
        "reason_code": skip.reason_code,
        "reason": skip.reason,
        "occurrence_count": skip.occurrence_count,
        "minimum_control_chars": min_control_chars,
    }


def _request_delta(fetcher: Any, before: Any) -> int:
    after = getattr(fetcher, "request_count", None)
    if isinstance(before, int) and isinstance(after, int):
        delta = after - before
        if delta < 0:
            raise ExperimentError("request_count_mismatch", "fetcher 요청 수가 감소했습니다")
        return delta
    # A minimal test double may not expose request_count; one fetch call is
    # still the only call represented by this helper.
    return 1


def _execute_variant(
    variant: QueryVariant,
    expected_spec_no: str,
    from_date: date,
    to_date: date,
    raw_path: Path,
    raw_file: str,
    fetcher_factory: Callable[[Callable[..., str]], Any],
) -> tuple[dict[str, Any], int]:
    query = _public_query(variant, from_date, to_date, 50)
    fetcher = fetcher_factory(variant.quote_via)
    before_count = getattr(fetcher, "request_count", None)
    payload, attempts = fetcher.fetch(ENDPOINTS["prespec_search"].url, query)
    calls = _request_delta(fetcher, before_count)
    survey.write_raw_page(
        raw_path,
        ENDPOINTS["prespec_search"],
        query,
        1,
        attempts,
        payload,
    )
    items, total, _response_page, _response_rows = survey.extract_page(payload)
    returned_spec_nos = [
        (item.get("bfSpecRgstNo") or "").strip()
        for item in items
        if isinstance(item, dict)
    ]
    return (
        {
            "variant_no": variant.number,
            "strategy": variant.strategy,
            "isolation_target": variant.isolation_target,
            "encoding": variant.encoding,
            "query": variant.query,
            "public_query_string": public_query_string(query, variant),
            "result_count": total,
            "returned_count": len(items),
            "expected_found": expected_spec_no in returned_spec_nos,
            "returned_spec_nos": returned_spec_nos[:10],
            "raw_file": raw_file,
        },
        calls,
    )


def run_probe(
    name: str,
    expected_spec_no: str,
    from_date: date,
    to_date: date,
    output_dir: Path,
    *,
    timeout: int = 120,
    fetcher_factory: Callable[[Callable[..., str]], Any],
) -> dict[str, Any]:
    """Execute six requests using a factory that selects ``quote_via``.

    The CLI factory creates a fresh SurveyFetcher per variant with
    ``max_attempts=1``.  Tests provide a FakeOpener-backed factory.  Keeping
    the factory boundary makes the six-call limit explicit and testable.
    """

    if not name.strip() or not expected_spec_no.strip():
        raise ExperimentError("invalid_case", "name과 expected-spec-no가 필요합니다")
    if to_date <= from_date:
        raise ExperimentError("invalid_window", "to-date는 from-date보다 뒤여야 합니다")
    if timeout < 1:
        raise ExperimentError("invalid_http_config", "timeout은 1 이상이어야 합니다")

    variants = build_variants(name)
    if len(variants) > MAX_REQUESTS:
        raise ExperimentError("request_limit", "검색 변형 수가 6회를 초과합니다")
    endpoint = ENDPOINTS["prespec_search"]
    output_dir = output_dir.resolve()
    result_path = output_dir / "search-isolation-probe.json"
    if result_path.exists():
        raise ExperimentError("artifact_exists", "기존 probe 산출물을 덮어쓸 수 없습니다")
    raw_dir = output_dir / "raw"
    if raw_dir.exists() and any(raw_dir.iterdir()):
        raise ExperimentError("artifact_exists", "기존 search-isolation raw를 덮어쓸 수 없습니다")

    rows: list[dict[str, Any]] = []
    request_count = 0
    for variant in variants:
        if request_count >= MAX_REQUESTS:
            raise ExperimentError("request_limit", "검색 호출 수가 6회를 초과합니다")
        raw_path = raw_dir / f"variant-{variant.number:02d}-{variant.strategy}.json"
        row, calls = _execute_variant(
            variant,
            expected_spec_no,
            from_date,
            to_date,
            raw_path,
            raw_path.name,
            fetcher_factory,
        )
        request_count += calls
        if request_count > MAX_REQUESTS:
            raise ExperimentError("request_limit", "검색 호출 수가 6회를 초과합니다")
        rows.append(row)

    if len(rows) != MAX_REQUESTS or request_count != MAX_REQUESTS:
        raise ExperimentError("request_count_mismatch", "검색 변형과 실제 호출 수가 다릅니다")
    return {
        "schema_version": PROBE_SCHEMA,
        "run_id": output_dir.parent.name,
        "created_at": datetime.now(KST).isoformat(),
        "endpoint_id": endpoint.endpoint_id,
        "search_field": SEARCH_FIELD,
        "case": {
            "name": name,
            "expected_spec_no": expected_spec_no,
            "from": from_date.isoformat(),
            "to_exclusive": to_date.isoformat(),
        },
        "request_count": request_count,
        "max_requests": MAX_REQUESTS,
        "variants": rows,
    }


def run_char_tolerance(
    raw_dir: Path,
    output_dir: Path,
    from_date: date = DEFAULT_FROM_DATE,
    to_date: date = DEFAULT_TO_DATE,
    *,
    max_requests: int = DEFAULT_CHAR_TOLERANCE_MAX_REQUESTS,
    min_control_chars: int = TOLERANCE_MIN_CONTROL_CHARS,
    timeout: int = 120,
    fetcher_factory: Callable[[Callable[..., str]], Any],
) -> dict[str, Any]:
    """Run one probe/control pair for every usable local marker sample."""

    if max_requests < 1:
        raise ExperimentError("invalid_request_limit", "max-requests는 1 이상이어야 합니다")
    if min_control_chars < 1:
        raise ExperimentError(
            "invalid_tolerance_minimum", "대조군 최소 길이는 1 이상이어야 합니다"
        )
    if timeout < 1:
        raise ExperimentError("invalid_http_config", "timeout은 1 이상이어야 합니다")
    if to_date <= from_date:
        raise ExperimentError("invalid_window", "to-date는 from-date보다 뒤여야 합니다")
    output_dir = output_dir.resolve()
    artifact_path = output_dir / CHAR_TOLERANCE_ARTIFACT
    if artifact_path.exists():
        raise ExperimentError("artifact_exists", "기존 char-tolerance 산출물을 덮어쓸 수 없습니다")
    raw_dir = raw_dir.resolve()
    tolerance_raw_dir = output_dir / "raw" / CHAR_TOLERANCE_RAW_DIR
    if tolerance_raw_dir.exists() and any(tolerance_raw_dir.iterdir()):
        raise ExperimentError("artifact_exists", "기존 char-tolerance raw를 덮어쓸 수 없습니다")

    selection = select_tolerance_selection(raw_dir, min_control_chars)
    cases = list(selection.cases)
    # This is deliberately before the first fetch.  Selection is local-only,
    # and a future selector change must fail closed instead of spending part of
    # the live request budget with an invalid case.
    validations = validate_tolerance_cases(cases, min_control_chars)
    planned_requests = len(cases) * 2
    if planned_requests > max_requests:
        raise ExperimentError(
            "request_limit",
            f"문자 관용도에 필요한 {planned_requests}회가 상한 {max_requests}회를 초과합니다",
        )
    if not cases:
        raise ExperimentError(
            "no_tolerance_cases",
            "로컬 prespec에서 관용도 case를 하나도 만들지 못했습니다; 모든 대상이 unknown입니다",
        )

    endpoint = ENDPOINTS["prespec_search"]
    rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    request_count = 0
    variant_no = 1
    for case, validation in zip(cases, validations):
        probe_variant = QueryVariant(
            variant_no,
            "char_tolerance_probe",
            case.query,
            urllib.parse.quote_plus,
            "quote_plus",
            f"{case.target.display} 포함 본 질의",
        )
        probe_raw_path = tolerance_raw_dir / f"variant-{variant_no:02d}-{case.target.label}-probe.json"
        probe_row, calls = _execute_variant(
            probe_variant,
            case.expected_spec_no,
            from_date,
            to_date,
            probe_raw_path,
            str(Path("raw") / CHAR_TOLERANCE_RAW_DIR / probe_raw_path.name),
            fetcher_factory,
        )
        request_count += calls
        if request_count > max_requests:
            raise ExperimentError("request_limit", "문자 관용도 호출 수가 상한을 초과합니다")
        probe_row.update(
            {
                "target": case.target.display,
                "target_label": case.target.label,
                "target_codepoints": [f"U+{ord(char):04X}" for char in case.target.chars],
                "sample_source_spec_no": case.sample_source_spec_no,
                "sample_source_name": case.source_name,
                "case_query": case.query,
                "case_control_query": case.control_query,
                "case_query_is_contiguous_substring": validation[
                    "query_is_contiguous_substring"
                ],
                "case_control_query_is_contiguous_substring": validation[
                    "control_query_is_contiguous_substring"
                ],
                "target_boundary": case.boundary,
                "query_role": "probe",
            }
        )
        rows.append(probe_row)
        variant_no += 1

        control_variant = QueryVariant(
            variant_no,
            "char_tolerance_control",
            case.control_query,
            urllib.parse.quote_plus,
            "quote_plus",
            f"{case.target.display} 제거 대조군",
        )
        control_raw_path = tolerance_raw_dir / f"variant-{variant_no:02d}-{case.target.label}-control.json"
        control_row, calls = _execute_variant(
            control_variant,
            case.expected_spec_no,
            from_date,
            to_date,
            control_raw_path,
            str(Path("raw") / CHAR_TOLERANCE_RAW_DIR / control_raw_path.name),
            fetcher_factory,
        )
        request_count += calls
        if request_count > max_requests:
            raise ExperimentError("request_limit", "문자 관용도 호출 수가 상한을 초과합니다")
        control_row.update(
            {
                "target": case.target.display,
                "target_label": case.target.label,
                "target_codepoints": [f"U+{ord(char):04X}" for char in case.target.chars],
                "sample_source_spec_no": case.sample_source_spec_no,
                "sample_source_name": case.source_name,
                "case_query": case.query,
                "case_control_query": case.control_query,
                "case_query_is_contiguous_substring": validation[
                    "query_is_contiguous_substring"
                ],
                "case_control_query_is_contiguous_substring": validation[
                    "control_query_is_contiguous_substring"
                ],
                "target_boundary": case.boundary,
                "query_role": "control",
            }
        )
        rows.append(control_row)
        variant_no += 1

        if control_row["expected_found"] and probe_row["result_count"] == 0:
            conclusion = "breaking_candidate"
            interpretation = (
                "대조군 적중 + 본 질의 0건: 해당 문자가 검색을 깨뜨리는 후보"
            )
            interpretation_code = "control_hit_probe_zero_breaking_candidate"
        elif probe_row["result_count"] == 0 and control_row["result_count"] == 0:
            conclusion = "unknown"
            interpretation = (
                "본 질의와 대조군 모두 0건: 표본 선정 문제이므로 해당 문자는 unknown"
            )
            interpretation_code = "both_zero_sample_selection_unknown"
        elif control_row["expected_found"] and probe_row["expected_found"]:
            conclusion = "not_breaking_observed"
            interpretation = "본 질의와 대조군 모두 기대 사전규격을 적중해 파손을 관측하지 않음"
            interpretation_code = "both_hit_not_breaking_observed"
        else:
            conclusion = "unknown"
            interpretation = "대조군 적중과 본 질의 0건의 조건을 충족하지 않아 unknown"
            interpretation_code = "inconclusive_unknown"
        case_metadata = _case_metadata(case, validation)
        case_metadata.update(
            {
                "probe_variant_no": probe_variant.number,
                "control_variant_no": control_variant.number,
                "conclusion": conclusion,
                "interpretation_code": interpretation_code,
                "interpretation": interpretation,
            }
        )
        comparisons.append(case_metadata)

    if request_count != planned_requests or len(rows) != planned_requests:
        raise ExperimentError("request_count_mismatch", "문자 관용도 계획과 실제 호출 수가 다릅니다")
    return {
        "schema_version": CHAR_TOLERANCE_SCHEMA,
        "mode": "char_tolerance",
        "run_id": output_dir.parent.name,
        "created_at": datetime.now(KST).isoformat(),
        "endpoint_id": endpoint.endpoint_id,
        "search_field": SEARCH_FIELD,
        "search_window": {
            "from": from_date.isoformat(),
            "to_exclusive": to_date.isoformat(),
        },
        "raw_source": raw_dir.name,
        "minimum_control_chars": min_control_chars,
        "candidate_target_count": len(CHAR_TOLERANCE_TARGETS),
        "request_count": request_count,
        "planned_request_count": planned_requests,
        "max_requests": max_requests,
        "target_count": len(cases),
        "skipped_count": len(selection.skipped),
        "skipped": [
            _skip_metadata(skip, min_control_chars) for skip in selection.skipped
        ],
        "comparisons": comparisons,
        "variants": rows,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--expected-spec-no", default=DEFAULT_EXPECTED_SPEC_NO)
    parser.add_argument("--from-date", type=date.fromisoformat, default=DEFAULT_FROM_DATE)
    parser.add_argument("--to-date", type=date.fromisoformat, default=DEFAULT_TO_DATE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=_REPO_ROOT / "data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2/raw",
        help="--char-tolerance가 읽을 prespec raw 경로",
    )
    parser.add_argument(
        "--char-tolerance",
        action="store_true",
        help="로컬 prespec에 실제 있는 미판정 문자별 probe/control을 실행합니다",
    )
    parser.add_argument(
        "--max-requests",
        "--request-limit",
        type=int,
        default=DEFAULT_CHAR_TOLERANCE_MAX_REQUESTS,
        help="--char-tolerance 호출 상한(기본 24)",
    )
    parser.add_argument(
        "--min-control-chars",
        type=int,
        default=TOLERANCE_MIN_CONTROL_CHARS,
        help="문자 관용도 대조군 최소 길이(기본 6)",
    )
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--execute", action="store_true", help="외부 G2B 호출을 명시적으로 허용합니다")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not args.execute:
            print(
                "외부 호출이 승인되지 않았습니다. --execute를 명시하면 G2B를 호출합니다.",
                file=sys.stderr,
            )
            return 2
        # The key is resolved only in an explicitly approved live execution;
        # it is passed to SurveyFetcher and never logged or persisted.
        service_key = survey.get_service_key()

        def factory(quote_via: Callable[..., str]) -> survey.SurveyFetcher:
            return survey.SurveyFetcher(
                service_key,
                timeout=args.timeout,
                max_attempts=1,
                quote_via=quote_via,
            )

        if args.char_tolerance:
            document = run_char_tolerance(
                args.raw_dir,
                args.output_dir,
                args.from_date,
                args.to_date,
                max_requests=args.max_requests,
                min_control_chars=args.min_control_chars,
                timeout=args.timeout,
                fetcher_factory=factory,
            )
            artifact_name = CHAR_TOLERANCE_ARTIFACT
        else:
            document = run_probe(
                args.name,
                args.expected_spec_no,
                args.from_date,
                args.to_date,
                args.output_dir,
                timeout=args.timeout,
                fetcher_factory=factory,
            )
            artifact_name = "search-isolation-probe.json"
        output_dir = args.output_dir.resolve()
        write_json_new(output_dir / artifact_name, document)
        print(f"검색 변형 {document['request_count']}회 기록: {output_dir}")
        return 0
    except ExperimentError as exc:
        print(f"error[{exc.code}]: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
