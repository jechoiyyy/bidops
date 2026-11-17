"""결정적 정량점수 추정(spec M2-03). `RfpFacts × CompanyProfile → ScoreEstimate[]`.

점수는 코드 규칙으로만 계산한다(LLM·네트워크 없음). 배점 조건 문자열(`Criterion.condition`)은
숫자·단위·등급 토큰만 정규식으로 읽고(`parse_condition`), 그 밖의 자유 텍스트는 해석하지 않는다.

구간 두 종류(계약 시트 X16):
- 판별 불가 구간 = [일반 criteria 점수 최소, 최대]. 입력은 known이지만 조건을 판별할 수 없을 때
  (해석 불가 조건 섞임, 사업금액 미상, 인증·교육 종류 판별 불가).
- unknown 구간 = 프로필 입력이 unknown일 때 `points_for`의 unknown 규칙. [일반 criteria 점수 최소,
  최대]이되 정의역 최솟값(수치 0, 등급 D)이 어떤 조건도 만족하지 않으면 하한 0.

"일반 criteria" = condition에 `STARTUP_KEYWORD`("창업")가 없는 조건. 창업 특례 조건은 CREDIT_RATING
특례에서만 쓴다. 최종 점수는 항상 0 ≤ est_min ≤ est_max ≤ max_points로 clamp한다.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from bid_deep_engine.analysis.gates import (
    STARTUP_YEARS,
    CompanyInput,
    _as_evidence_view,
    _CompanyReader,
    _is_startup,
    _item_path,
    _performance_window,
    performance_amount,
    profile_date,
)
from bid_deep_engine.analysis.schemas import Criterion, EvalItem, EvalKind, RfpFacts, ScoreEstimate
from bid_deep_engine.company.provenance import CompanyEvidenceView, parse_canonical_path
from bid_deep_engine.company.schema import UNKNOWN

Unit = Literal["pct", "count", "krw", "grade"]

# 신용등급 서열(tunable). 높을수록 우수, "이상" = 서열 ≥.
GRADE_ORDER: dict[str, int] = {
    "AAA": 22,
    "AA+": 21,
    "AA0": 20,
    "AA-": 19,
    "A+": 18,
    "A0": 17,
    "A-": 16,
    "BBB+": 15,
    "BBB0": 14,
    "BBB-": 13,
    "BB+": 12,
    "BB0": 11,
    "BB-": 10,
    "B+": 9,
    "B0": 8,
    "B-": 7,
    "CCC+": 6,
    "CCC0": 5,
    "CCC-": 4,
    "CC": 3,
    "C": 2,
    "D": 1,
}
# 부호(+·0·-) 없이 쓰면 `0`을 보충하는 등급(AAA·CC·C·D는 부호 없는 형태가 정규형).
_SIGNLESS_GRADES = frozenset({"AA", "A", "BBB", "BB", "B", "CCC"})
_LOWEST_GRADE = "D"  # 등급 정의역 최솟값(unknown 구간 하한 판정)

# 단위 → (단위 종류, 원 환산 배수)(tunable).
UNIT_MULTIPLIERS: dict[str, tuple[Unit, float]] = {
    "%": ("pct", 1),
    "퍼센트": ("pct", 1),
    "건": ("count", 1),
    "명": ("count", 1),
    "인": ("count", 1),
    "개": ("count", 1),
    "원": ("krw", 1),
    "천원": ("krw", 1e3),
    "만원": ("krw", 1e4),
    "백만원": ("krw", 1e6),
    "억원": ("krw", 1e8),
    "억": ("krw", 1e8),
}

# kind별로 받아들이는 조건 단위. None(단위 없음)은 CERT_COUNT·STAFF_TRAINING에서 count로 본다.
KIND_UNITS: dict[EvalKind, frozenset[Unit | None]] = {
    "CREDIT_RATING": frozenset({"grade"}),
    "PAST_PERFORMANCE": frozenset({"pct", "krw", "count"}),
    "CERT_COUNT": frozenset({"count", None}),
    "STAFF_TRAINING": frozenset({"count", None}),
    "OTHER": frozenset(),
}

STARTUP_KEYWORD = "창업"  # 이 말이 든 condition은 창업 특례 조건(일반 계산에서 제외)

# 항목명+조건 텍스트(공백 제거)의 키워드 → 입력 프로필 경로(tunable). 사전 순서대로 먼저 맞는 것.
CERT_KIND_KEYWORDS: dict[str, tuple[str, ...]] = {
    "registrations.egov_framework_inspection_reports": ("전자정부", "표준프레임워크"),
    "registrations.web_accessibility_certs.count": ("웹접근성",),
}
TRAINING_KEYWORDS: dict[str, tuple[str, ...]] = {
    "people.trainings.sw_security_diagnostician": ("보안약점",),
    "people.trainings.sw_test_expert": ("테스트",),
}

CREDIT_GRADE_PATH = "registrations.credit_rating.grade"
FOUNDED_PATH = "company.founded"
_RECENT_YEARS_RE = re.compile(r"최근\s*(\d+)\s*년")

_GRADE_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(AAA|AA[+0-]?|A[+0-]?|BBB[+0-]?|BB[+0-]?|B[+0-]?|CCC[+0-]?|CC|C|D)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_GRADE_CMP_RE = re.compile(r"\s*(이상|초과|이하|미만)")
_GRADE_RANGE_GAP_RE = re.compile(r"\s*(?:이상|초과)?\s*[~∼～]\s*")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
# 숫자 앞 경계: 영문에 붙은 숫자(등급 부호·코드 — "A30", "ISO9001")를 숫자 조건으로 읽지 않는다
# (X13 `(?<![A-Za-z])`). 숫자·소수점도 경계에 넣어, 영문 뒤 숫자의 중간("A30"의 "0")에서
# 숫자를 새로 시작하지 않게 한다.
_NUM = r"(?<![A-Za-z\d.])(\d+(?:\.\d+)?)"
_UNIT = "(" + "|".join(re.escape(u) for u in sorted(UNIT_MULTIPLIERS, key=len, reverse=True)) + ")"
_RANGE_RE = re.compile(
    rf"{_NUM}\s*{_UNIT}?\s*(이상|초과)?\s*[~∼～-]\s*{_NUM}\s*{_UNIT}?\s*(이하|미만)?"
)
_CMP_RE = re.compile(rf"{_NUM}\s*{_UNIT}?\s*(이상|초과|이하|미만)")


@dataclass(frozen=True)
class ParsedCondition:
    """배점 조건 하나의 해석 결과.

    수치 조건: `lo`/`hi`(원 환산 후 값, 없으면 None)와 포함 여부, `ranks` None.
    등급 조건: `unit="grade"`, `ranks` = 만족하는 `GRADE_ORDER` 서열 집합, `lo`/`hi` None.
    """

    unit: Unit | None
    lo: float | None = None
    lo_incl: bool = True
    hi: float | None = None
    hi_incl: bool = True
    ranks: frozenset[int] | None = None


@dataclass(frozen=True)
class PointRange:
    """`points_for` 결과. clamp된 구간과 코드 포맷 근거 문구."""

    est_min: float
    est_max: float
    basis: str


def normalize_grade(text: str) -> str | None:
    """신용등급 정규화(X13): 대문자·공백 제거 → 사전에 있으면 그대로, 부호 없으면 `0` 보충.

    그래도 `GRADE_ORDER`에 없으면 None(호출자가 unknown으로 다루고 basis에 경고).
    """
    if not isinstance(text, str):
        return None
    grade = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).upper()
    if grade in GRADE_ORDER:
        return grade
    if grade in _SIGNLESS_GRADES:
        return grade + "0"
    return None


def parse_condition(text: str) -> ParsedCondition | None:
    """배점 조건 문자열 해석. 등급 → 범위 → 비교 순(X13: 등급 토큰을 숫자보다 먼저). 불가면 None."""
    if not isinstance(text, str):
        return None
    norm = _THOUSANDS_RE.sub("", unicodedata.normalize("NFC", text))
    if _GRADE_TOKEN_RE.search(norm):
        return _parse_grade(norm)
    m = _RANGE_RE.search(norm)
    if m is not None:
        lo_num, lo_unit, lo_op, hi_num, hi_unit, hi_op = m.groups()
        resolved = _resolve_units([(lo_num, lo_unit), (hi_num, hi_unit)])
        if resolved is None:
            return None
        unit, (lo, hi) = resolved
        return ParsedCondition(
            unit=unit, lo=lo, lo_incl=lo_op != "초과", hi=hi, hi_incl=hi_op != "미만"
        )
    tokens = _CMP_RE.findall(norm)
    if not tokens:
        return None
    lowers = [t for t in tokens if t[2] in ("이상", "초과")]
    uppers = [t for t in tokens if t[2] in ("이하", "미만")]
    if len(lowers) > 1 or len(uppers) > 1:
        return None
    ordered = lowers + uppers
    resolved = _resolve_units([(num, unit) for num, unit, _ in ordered])
    if resolved is None:
        return None
    unit, values = resolved
    lo = hi = None
    lo_incl = hi_incl = True
    for (_, _, op), value in zip(ordered, values, strict=True):
        if op in ("이상", "초과"):
            lo, lo_incl = value, op == "이상"
        else:
            hi, hi_incl = value, op == "이하"
    return ParsedCondition(unit=unit, lo=lo, lo_incl=lo_incl, hi=hi, hi_incl=hi_incl)


def _resolve_units(
    pairs: list[tuple[str, str | None]],
) -> tuple[Unit | None, list[float]] | None:
    """숫자·단위 쌍들을 한 단위 종류로 맞춰 원 환산 값으로. 단위 없는 숫자는 다른 쪽 단위를 빌린다.

    단위 종류가 섞이면(예: % 와 건) None(해석 불가).
    """
    units = [u for _, u in pairs if u]
    kinds = {UNIT_MULTIPLIERS[u][0] for u in units}
    if len(kinds) > 1:
        return None
    fallback = units[0] if units else None
    values: list[float] = []
    for num, unit in pairs:
        unit = unit or fallback
        multiplier = UNIT_MULTIPLIERS[unit][1] if unit else 1
        values.append(float(num) * multiplier)
    return (UNIT_MULTIPLIERS[fallback][0] if fallback else None), values


def _parse_grade(norm: str) -> ParsedCondition | None:
    """등급 조건: `X 이상|초과|이하|미만` → 서열 비교, `X ~ Y` → 양끝 포함 구간, 그 외 나열 집합."""
    matches = list(_GRADE_TOKEN_RE.finditer(norm))
    ranks_in_order: list[int] = []
    for m in matches:
        grade = normalize_grade(m.group(1))
        if grade is None:
            return None
        ranks_in_order.append(GRADE_ORDER[grade])
    ops = [_grade_op(norm, m.end()) for m in matches]
    if len(matches) == 2 and _GRADE_RANGE_GAP_RE.fullmatch(
        norm, matches[0].end(), matches[1].start()
    ):
        a, b = ranks_in_order
        ranks = set(range(min(a, b), max(a, b) + 1))
        # 끝점에 붙은 초과·미만은 그 끝점 등급을 뺀다
        for rank, op in zip(ranks_in_order, ops, strict=True):
            if op in ("초과", "미만"):
                ranks.discard(rank)
        return ParsedCondition(unit="grade", ranks=frozenset(ranks))
    # 같은 방향 비교끼리는 합집합("CCC+ 이하 | C 이하" → CCC+ 이하), 하한 쪽과 상한 쪽은 교집합
    # ("BBB0 이상 A0 미만"), 비교 없는 나열 등급은 더한다.
    lower: set[int] | None = None
    upper: set[int] | None = None
    plain: set[int] = set()
    for rank, op in zip(ranks_in_order, ops, strict=True):
        if op is None:
            plain.add(rank)
            continue
        allowed = {r for r in GRADE_ORDER.values() if _rank_cmp(r, rank, op)}
        if op in ("이상", "초과"):
            lower = allowed if lower is None else lower | allowed
        else:
            upper = allowed if upper is None else upper | allowed
    if lower is not None and upper is not None:
        compared = lower & upper
    else:
        compared = lower or upper or set()
    return ParsedCondition(unit="grade", ranks=frozenset(plain | compared))


def _grade_op(norm: str, pos: int) -> str | None:
    m = _GRADE_CMP_RE.match(norm, pos)
    return m.group(1) if m else None


def _rank_cmp(rank: int, bound: int, op: str) -> bool:
    if op == "이상":
        return rank >= bound
    if op == "초과":
        return rank > bound
    if op == "이하":
        return rank <= bound
    return rank < bound  # 미만


def _satisfies(parsed: ParsedCondition, value: float | str) -> bool:
    if parsed.unit == "grade":
        return parsed.ranks is not None and GRADE_ORDER.get(str(value)) in parsed.ranks
    v = float(value)
    if parsed.lo is not None and (v < parsed.lo or (v == parsed.lo and not parsed.lo_incl)):
        return False
    if parsed.hi is not None and (v > parsed.hi or (v == parsed.hi and not parsed.hi_incl)):
        return False
    return True


def fmt_points(x: float) -> str:
    """점수·수치 표기: 소수 둘째 자리까지, 뒤 0 제거(10.0 → "10", 9.5 → "9.5")."""
    text = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _value_text(value: float | str, unit: Unit | None) -> str:
    if isinstance(value, str):
        return value
    if unit == "pct":
        return fmt_points(value) + "%"
    if unit == "krw":
        return f"{value:,.0f}원"
    return fmt_points(value)


def clamp_range(est_min: float, est_max: float, max_points: float) -> tuple[float, float]:
    """0 ≤ est_min ≤ est_max ≤ max_points로 맞춘다."""
    hi = min(max(est_max, 0.0), max_points)
    lo = min(max(est_min, 0.0), hi)
    return float(lo), float(hi)


def _ranged(reason: str, est_min: float, est_max: float, max_points: float) -> PointRange:
    lo, hi = clamp_range(est_min, est_max, max_points)
    return PointRange(lo, hi, f"{reason}: {fmt_points(lo)}~{fmt_points(hi)}점")


def general_criteria(criteria: Sequence[Criterion]) -> list[Criterion]:
    """창업 특례 조건(`STARTUP_KEYWORD` 포함)을 뺀 일반 criteria."""
    return [c for c in criteria if STARTUP_KEYWORD not in c.condition]


def criteria_range(criteria: Sequence[Criterion], reason: str, max_points: float) -> PointRange:
    """판별 불가 구간(X16): [일반 criteria 점수 최소, 최대]. 일반 criteria가 없으면 [0, 만점]."""
    general = general_criteria(criteria)
    if not general:
        return _ranged(reason, 0.0, max_points, max_points)
    points = [c.points for c in general]
    return _ranged(reason, min(points), max(points), max_points)


def parse_for_kind(condition: str, kind: EvalKind) -> ParsedCondition | None:
    """`parse_condition` + kind 단위 호환 검사. 해석 불가이거나 단위가 맞지 않으면 None."""
    parsed = parse_condition(condition)
    if parsed is None or parsed.unit not in KIND_UNITS[kind]:
        return None
    return parsed


def points_for(
    criteria: Sequence[Criterion],
    value: float | str | Mapping[Unit | None, float],
    *,
    kind: EvalKind,
    max_points: float,
    label: str,
) -> PointRange:
    """공통 점수 구간 계산(spec "공통 구간 계산"). 위에서 먼저 맞는 규칙.

    `value`: known 값(수치, 또는 `normalize_grade`된 등급), 미확인이면 `UNKNOWN`("unknown").
    조건 단위마다 값이 다르면(PAST_PERFORMANCE의 비율·금액·건수) `{단위: 값}` 매핑을 준다.
    `label`은 basis의 입력 표기(프로필 경로 등).

    known 값이 여러 조건을 만족하면(누적 "이상" 구간) 가장 높은 점수의 조건 하나를 고른다
    (spec T19: 35건 × "30건 이상 3·20건 이상 2" → [3, 3]).
    """
    if not criteria:
        return _ranged("배점 기준 없음", 0.0, max_points, max_points)
    general = general_criteria(criteria)
    if not general:
        return _ranged("배점 기준 없음", 0.0, max_points, max_points)
    parsed = [(c, parse_for_kind(c.condition, kind)) for c in general]
    bad = sum(1 for _, p in parsed if p is None)
    if bad:
        return criteria_range(general, f"해석 불가 조건 {bad}건", max_points)
    points = [c.points for c in general]
    if isinstance(value, str) and value == UNKNOWN:
        floor: float | str = _LOWEST_GRADE if kind == "CREDIT_RATING" else 0.0
        lo = min(points)
        if not any(_satisfies(p, floor) for _, p in parsed if p is not None):
            lo = 0.0
        return _ranged(f"{label} 미확인", lo, max(points), max_points)
    hits: list[tuple[Criterion, Unit | None]] = []
    for criterion, p in parsed:
        assert p is not None
        if _satisfies(p, _value_for(value, p.unit)):
            hits.append((criterion, p.unit))
    if not hits:
        first = parsed[0][1]
        unit = first.unit if first is not None else None
        shown = _value_text(_value_for(value, unit), unit)
        return _ranged(f"{label}={shown} → 해당 구간 없음", 0.0, 0.0, max_points)
    # 누적 구간("30건 이상"·"20건 이상")에 함께 들면 가장 높은 구간 점수(T19). 동점이면 앞 조건.
    best, unit = max(hits, key=lambda h: h[0].points)
    lo, hi = clamp_range(best.points, best.points, max_points)
    shown = _value_text(_value_for(value, unit), unit)
    return PointRange(lo, hi, f"{label}={shown} → {best.condition} {fmt_points(best.points)}점")


def _value_for(value: float | str | Mapping[Unit | None, float], unit: Unit | None) -> float | str:
    if isinstance(value, Mapping):
        return value[unit]
    return value


# --- EvalKind별 추정 ---


def estimate_scores(
    facts: RfpFacts,
    profile: CompanyInput,
    *,
    as_of: date,
    evidence_view: CompanyEvidenceView | None = None,
) -> list[ScoreEstimate]:
    """정량평가 항목마다 ScoreEstimate 하나(문서 순). 같은 입력 → 같은 출력."""
    view = _as_evidence_view(profile, evidence_view)
    return [
        _estimate(item, facts, _CompanyReader(view), as_of)
        for item in facts.evaluation.quantitative
    ]


def _estimate(
    item: EvalItem, facts: RfpFacts, reader: _CompanyReader, as_of: date
) -> ScoreEstimate:
    if item.kind == "CREDIT_RATING":
        return _credit_rating(item, reader, as_of)
    if item.kind == "PAST_PERFORMANCE":
        return _past_performance(item, facts, reader, as_of)
    if item.kind == "CERT_COUNT":
        return _routed_count(item, reader, CERT_KIND_KEYWORDS, "인증 종류 판별 불가")
    if item.kind == "STAFF_TRAINING":
        return _routed_count(item, reader, TRAINING_KEYWORDS, "교육 종류 판별 불가")
    r = _ranged("규칙 계산 불가", 0.0, item.max_points, item.max_points)  # OTHER
    return _score(item, r.est_min, r.est_max, r.basis, [], reader.input_fields)


def _score(
    item: EvalItem,
    est_min: float,
    est_max: float,
    basis: str,
    unknown_inputs: list[str],
    input_fields: Sequence[str],
) -> ScoreEstimate:
    lo, hi = clamp_range(est_min, est_max, item.max_points)
    return ScoreEstimate(
        item=item.item,
        kind=item.kind,
        max_points=item.max_points,
        est_min=lo,
        est_max=hi,
        basis=basis,
        unknown_inputs=list(dict.fromkeys(unknown_inputs)),
        input_fields=list(dict.fromkeys(input_fields)),
    )


def _mentions_startup(item: EvalItem) -> bool:
    return STARTUP_KEYWORD in item.item or any(
        STARTUP_KEYWORD in c.condition for c in item.criteria
    )


def _credit_rating(item: EvalItem, reader: _CompanyReader, as_of: date) -> ScoreEstimate:
    """신용등급: 일반 계산(등급 서열) + 창업 특례(항목·조건에 "창업"이 있을 때)."""
    raw = reader.value(CREDIT_GRADE_PATH)
    unknown_inputs: list[str] = []
    warning: str | None = None
    grade = normalize_grade(raw) if raw != UNKNOWN else None
    if grade is None:
        unknown_inputs.append(CREDIT_GRADE_PATH)
        if raw != UNKNOWN:
            warning = f"등급 해석 불가: {raw}"  # X13: 서열 사전 밖 → unknown 구간 + 경고
    general = points_for(
        item.criteria,
        grade if grade is not None else UNKNOWN,
        kind=item.kind,
        max_points=item.max_points,
        label=CREDIT_GRADE_PATH,
    )
    basis = general.basis if warning is None else f"{warning}; {general.basis}"
    if not _mentions_startup(item):
        return _score(
            item, general.est_min, general.est_max, basis, unknown_inputs, reader.input_fields
        )
    startup = _is_startup(reader, as_of)
    if startup:
        return _score(
            item,
            item.max_points,
            item.max_points,
            f"창업 {STARTUP_YEARS}년 이내 특례(만점)",
            [],
            reader.input_fields,
        )
    if startup is None:  # X18: founded unknown → 특례 가능성을 구간에 포함
        lo, hi = clamp_range(general.est_min, item.max_points, item.max_points)
        basis += (
            f"; {FOUNDED_PATH} 미확인(창업 {STARTUP_YEARS}년 이내 특례 가능성 포함): "
            f"{fmt_points(lo)}~{fmt_points(hi)}점"
        )
        return _score(item, lo, hi, basis, [*unknown_inputs, FOUNDED_PATH], reader.input_fields)
    return _score(
        item, general.est_min, general.est_max, basis, unknown_inputs, reader.input_fields
    )


def _past_performance(
    item: EvalItem, facts: RfpFacts, reader: _CompanyReader, as_of: date
) -> ScoreEstimate:
    """실적: 창 안 확정 실적의 비율(금액 합 / 사업금액)·금액 합·건수를 조건과 비교.

    창·후보 분류는 게이트 실적 규칙 1·2(keyword 없음), 금액은 규칙 3. 금액 미확인·불확실 후보가
    판정에 영향을 주면 est_min = known 값으로 계산한 점수, est_max = 만점.
    """
    text = " ".join([item.item, *(c.condition for c in item.criteria)])
    m = _RECENT_YEARS_RE.search(text)
    start, _ = _performance_window(reader, as_of, int(m[1]) if m else None)
    unknown_inputs: list[str] = []
    if _is_startup(reader, as_of) is None:
        unknown_inputs.append(FOUNDED_PATH)  # 창업 특례 창 판정 불가(비창업으로 계산)

    confirmed = uncertain = amount_unknown = 0
    known_sum = 0.0
    paths: list[tuple[str, bool]] = []  # (경로, 금액 경로 여부) — 실적 순서
    for idx, p in enumerate(reader.profile.portfolio):
        pid = _item_path("portfolio", p.id, idx)
        completed = reader.value(f"{pid}.completed")
        if completed == UNKNOWN:
            uncertain += 1
            paths.append((f"{pid}.completed", False))
            continue
        if completed is not True:
            continue
        period_end = reader.value(f"{pid}.period.end")
        end = profile_date(period_end, end_of_month=True)
        if end is None:
            uncertain += 1
            paths.append((f"{pid}.period.end", False))
            continue
        if (start is not None and end < start) or end > as_of:
            continue
        confirmed += 1
        amount, amount_paths = performance_amount(p, pid, reader)
        if amount is None:
            amount_unknown += 1
            paths.extend((path, True) for path in amount_paths)
        else:
            known_sum += amount

    general = general_criteria(item.criteria)
    parsed = [parse_for_kind(c.condition, item.kind) for c in general]
    parse_ok = bool(general) and all(p is not None for p in parsed)
    units = {p.unit for p in parsed if p is not None}
    amount_relevant = not parse_ok or bool(units & {"pct", "krw"})  # 건수 조건은 금액 무관
    unknown_inputs += [path for path, is_amount in paths if amount_relevant or not is_amount]

    budget = facts.project.budget_krw
    has_budget = budget is not None and budget > 0
    if parse_ok and "pct" in units and not has_budget:  # X16: 판별 불가 구간
        r = criteria_range(item.criteria, "사업금액 미상", item.max_points)
        return _score(item, r.est_min, r.est_max, r.basis, unknown_inputs, reader.input_fields)
    values: dict[Unit | None, float] = {"krw": known_sum, "count": float(confirmed)}
    if has_budget:
        assert budget is not None
        values["pct"] = known_sum / budget * 100
    label = f"portfolio[창 {start.isoformat() if start else '-'}~{as_of.isoformat()}]"
    r = points_for(item.criteria, values, kind=item.kind, max_points=item.max_points, label=label)
    if not parse_ok:
        return _score(item, r.est_min, r.est_max, r.basis, unknown_inputs, reader.input_fields)
    list_unknown = not reader.list_complete("portfolio")
    if list_unknown:
        unknown_inputs.append("portfolio")
    pending = uncertain + (amount_unknown if amount_relevant else 0) + int(list_unknown)
    if pending == 0:
        return _score(item, r.est_min, r.est_max, r.basis, unknown_inputs, reader.input_fields)
    lo, hi = clamp_range(r.est_min, item.max_points, item.max_points)
    reasons = []
    if amount_relevant and amount_unknown:
        reasons.append(f"금액 미확인 {amount_unknown}건")
    if uncertain:
        reasons.append(f"불확실 후보 {uncertain}건")
    if list_unknown:
        reasons.append("실적 목록 완전성 미확인")
    basis = f"{r.basis}; {'·'.join(reasons)}: {fmt_points(lo)}~{fmt_points(hi)}점"
    return _score(item, lo, hi, basis, unknown_inputs, reader.input_fields)


def _route(item: EvalItem, table: Mapping[str, tuple[str, ...]]) -> str | None:
    text = re.sub(r"\s+", "", unicodedata.normalize("NFC", item.item))
    text += "".join(
        re.sub(r"\s+", "", unicodedata.normalize("NFC", c.condition)) for c in item.criteria
    )
    for path, keywords in table.items():
        if any(k in text for k in keywords):
            return path
    return None


def _routed_count(
    item: EvalItem,
    reader: _CompanyReader,
    table: Mapping[str, tuple[str, ...]],
    undetermined: str,
) -> ScoreEstimate:
    """CERT_COUNT·STAFF_TRAINING: 키워드로 입력 경로를 고르고 건수·인원을 조건과 비교."""
    if not general_criteria(item.criteria):
        r = points_for(item.criteria, UNKNOWN, kind=item.kind, max_points=item.max_points, label="")
        return _score(item, r.est_min, r.est_max, r.basis, [], reader.input_fields)
    path = _route(item, table)
    if path is None:  # X16: 판별 불가 구간
        r = criteria_range(item.criteria, undetermined, item.max_points)
        return _score(item, r.est_min, r.est_max, r.basis, [], reader.input_fields)
    value = reader.value(path)
    known = isinstance(value, int) and not isinstance(value, bool)
    r = points_for(
        item.criteria,
        float(value) if known else UNKNOWN,  # type: ignore[arg-type]
        kind=item.kind,
        max_points=item.max_points,
        label=path,
    )
    return _score(
        item,
        r.est_min,
        r.est_max,
        r.basis,
        [] if known else [path],
        reader.input_fields,
    )


def score_request_exclusion_reason(
    facts: RfpFacts,
    item: EvalItem,
    estimate: ScoreEstimate,
    profile: CompanyInput,
    field: str,
    *,
    as_of: date,
    evidence_view: CompanyEvidenceView | None = None,
) -> Literal["out_of_scope", "score_invariant"] | None:
    """Prove that one unknown score input cannot affect this score.

    Equality of the stored interval is not proof by itself.  The admitted proof is deliberately
    narrow: PAST_PERFORMANCE is monotone once the founding date fixes its active window.  A
    portfolio candidate with a confirmed end outside that window is out of scope; any other
    portfolio uncertainty is invariant only when independently known performance already earns
    the maximum score.
    """
    if item.kind != "PAST_PERFORMANCE" or estimate.kind != "PAST_PERFORMANCE":
        return None
    try:
        parts = parse_canonical_path(field)
    except ValueError:
        return None
    if not parts or parts[0][0] != "portfolio":
        return None

    reader = _CompanyReader(_as_evidence_view(profile, evidence_view))
    if profile_date(reader.value(FOUNDED_PATH), end_of_month=False) is None:
        return None

    text = " ".join([item.item, *(criterion.condition for criterion in item.criteria)])
    match = _RECENT_YEARS_RE.search(text)
    start, end = _performance_window(reader, as_of, int(match[1]) if match else None)

    identifier = parts[0][1]
    if identifier is not None:
        portfolio_item = next(
            (value for value in reader.profile.portfolio if value.id == identifier), None
        )
        if portfolio_item is None:
            return None
        base = _item_path("portfolio", portfolio_item.id, 0)
        period_end = profile_date(reader.value(f"{base}.period.end"), end_of_month=True)
        if period_end is not None and (
            (start is not None and period_end < start) or period_end > end
        ):
            return "out_of_scope"

    if _known_performance_is_monotone_max(facts, item, estimate, reader, start, end):
        return "score_invariant"
    return None


def _known_performance_is_monotone_max(
    facts: RfpFacts,
    item: EvalItem,
    estimate: ScoreEstimate,
    reader: _CompanyReader,
    start: date | None,
    end: date,
) -> bool:
    """Prove maximum score from known contributions under lower-bound-only criteria."""
    general = general_criteria(item.criteria)
    parsed = [parse_for_kind(criterion.condition, item.kind) for criterion in general]
    if not general or any(condition is None for condition in parsed):
        return False
    # Adding an unknown candidate is monotone only for lower-bound conditions.  Upper bounds and
    # bounded ranges can lose points when a value/count increases.
    if any(condition.lo is None or condition.hi is not None for condition in parsed if condition):
        return False

    confirmed = 0
    known_sum = 0.0
    for index, portfolio_item in enumerate(reader.profile.portfolio):
        base = _item_path("portfolio", portfolio_item.id, index)
        if reader.value(f"{base}.completed") is not True:
            continue
        period_end = profile_date(reader.value(f"{base}.period.end"), end_of_month=True)
        if period_end is None or period_end > end or (start is not None and period_end < start):
            continue
        confirmed += 1
        amount, _ = performance_amount(portfolio_item, base, reader)
        if amount is not None:
            known_sum += amount

    units = {condition.unit for condition in parsed if condition is not None}
    budget = facts.project.budget_krw
    if "pct" in units and (budget is None or budget <= 0):
        return False
    values: dict[Unit | None, float] = {"krw": known_sum, "count": float(confirmed)}
    if budget is not None and budget > 0:
        values["pct"] = known_sum / budget * 100
    result = points_for(
        item.criteria,
        values,
        kind=item.kind,
        max_points=item.max_points,
        label="known portfolio proof",
    )
    return bool(
        estimate.max_points == item.max_points
        and result.est_min == result.est_max == item.max_points
    )
