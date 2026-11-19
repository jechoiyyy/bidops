"""정량점수 추정 테스트(spec M2-03 T15~T22). 이 파일은 단계별로 늘어난다.

STEP-005: T15(`parse_condition`·`normalize_grade`), T16(`GRADE_ORDER`), T22(`points_for` 공통 규칙 —
판별 불가 구간·unknown 구간·해당 구간 없음·clamp·단위 불일치).
STEP-006: T17~T21(EvalKind별 `estimate_scores`). 합성 RfpFacts·프로필은 `tests/gate_factories.py`.
네트워크·LLM을 쓰지 않는다.
"""

from datetime import date
from pathlib import Path

import pytest

from bid_deep_engine.analysis import gates, scoring
from bid_deep_engine.analysis.schemas import Criterion, EvalItem, ScoreEstimate
from bid_deep_engine.analysis.scoring import (
    GRADE_ORDER,
    ParsedCondition,
    normalize_grade,
    parse_condition,
    points_for,
)
from bid_deep_engine.analysis.scoring import (
    estimate_scores as _estimate_scores,
)
from bid_deep_engine.company.provenance import CompanyEvidenceView
from bid_deep_engine.company.schema import UNKNOWN
from engine_tests.gate_factories import (
    confirmed_fixture_view,
    confirmed_view,
    eval_item,
    make_facts,
    make_profile,
    portfolio_item,
)


def estimate_scores(facts, profile, *, as_of):
    if isinstance(profile, CompanyEvidenceView):
        return _estimate_scores(facts, profile, as_of=as_of)
    return _estimate_scores(facts, confirmed_fixture_view(profile), as_of=as_of)


def _ranks(*grades: str) -> frozenset[int]:
    return frozenset(GRADE_ORDER[g] for g in grades)


def _ranks_between(lo: int, hi: int) -> frozenset[int]:
    return frozenset(range(lo, hi + 1))


def _criteria(*pairs: tuple[str, float]) -> list[Criterion]:
    return [Criterion(condition=c, points=p) for c, p in pairs]


# --- T15: parse_condition ---


@pytest.mark.parametrize(
    ("text", "unit", "lo", "lo_incl", "hi", "hi_incl"),
    [
        ("100% 이상", "pct", 100, True, None, True),
        ("50% 이상 ~ 100% 미만", "pct", 50, True, 100, False),
        ("70~100%", "pct", 70, True, 100, True),
        ("30건 이상", "count", 30, True, None, True),
        ("1명 이상", "count", 1, True, None, True),
        ("5억원 이상", "krw", 500_000_000, True, None, True),
        ("1,000만원 미만", "krw", None, True, 10_000_000, False),
        # 실제 골든 RFP 표기(남양주 T071·T072, 전각 물결표)
        ("70% 이상～100% 미만", "pct", 70, True, 100, False),
        ("25건 이상 ~ 30건 미만", "count", 25, True, 30, False),
        ("40% 미만", "pct", None, True, 40, False),
        ("SW보안약점진단원 참여 (1건 이상)", "count", 1, True, None, True),
        # 하한 초과·상한 이하
        ("10% 초과 ~ 20% 이하", "pct", 10, False, 20, True),
        ("3건 초과", "count", 3, False, None, True),
    ],
)
def test_t15_parse_numeric_conditions(text, unit, lo, lo_incl, hi, hi_incl):
    parsed = parse_condition(text)
    assert parsed is not None, text
    assert parsed.unit == unit
    assert parsed.lo == lo
    assert parsed.hi == hi
    if lo is not None:
        assert parsed.lo_incl is lo_incl
    if hi is not None:
        assert parsed.hi_incl is hi_incl
    assert parsed.ranks is None


def test_t15_parse_condition_unit_multipliers():
    assert parse_condition("3천원 이상").lo == 3_000
    assert parse_condition("2만원 이상").lo == 20_000
    assert parse_condition("4백만원 이상").lo == 4_000_000
    assert parse_condition("1.5억 이상").lo == 150_000_000
    assert parse_condition("70 퍼센트 이상").unit == "pct"
    assert parse_condition("2인 이상").unit == "count"
    assert parse_condition("3개 이상").unit == "count"
    assert parse_condition("100,000,000원 이상").lo == 100_000_000


def test_t15_parse_condition_range_borrows_unit_from_other_end():
    parsed = parse_condition("1~5억원")
    assert parsed is not None
    assert (parsed.unit, parsed.lo, parsed.hi) == ("krw", 100_000_000, 500_000_000)


def test_t15_parse_condition_unitless_number_has_unit_none():
    parsed = parse_condition("30 이상")
    assert parsed is not None
    assert (parsed.unit, parsed.lo, parsed.hi) == (None, 30, None)


def test_t15_parse_condition_descending_bounds_read_as_two_comparisons():
    # 외교부 SLA 표 "100% 미만~ 99.92% 이상"(상한이 앞)은 범위가 아니라 비교 토큰 둘로 읽는다
    parsed = parse_condition("100% 미만~ 99.92% 이상")
    assert parsed is not None
    assert (parsed.unit, parsed.lo, parsed.lo_incl, parsed.hi, parsed.hi_incl) == (
        "pct",
        99.92,
        True,
        100,
        False,
    )


@pytest.mark.parametrize(
    ("text", "ranks"),
    [
        ("BBB0 이상", _ranks_between(14, 22)),
        ("A0 이상", _ranks_between(17, 22)),
        ("AAA, AA+, AA0", _ranks("AAA", "AA+", "AA0")),
        ("B+ ~ BBB-", _ranks_between(9, 13)),
        ("A 이상", _ranks_between(17, 22)),  # 부호 없음 → A0
        ("bbb 이상", _ranks_between(14, 22)),  # 소문자·부호 없음 → BBB0
        ("CCC+ 이하", _ranks_between(1, 6)),
        ("A0 초과", _ranks_between(18, 22)),
        ("BBB- ~ B+", _ranks_between(9, 13)),  # 양끝 순서 무관
        # 실제 골든 RFP(강원대 T088·남양주 T067 기업신용평가등급 열)
        (
            "AAA, AA+, AA0, AA-, A+, A0, A-, BBB+, BBB0",
            _ranks("AAA", "AA+", "AA0", "AA-", "A+", "A0", "A-", "BBB+", "BBB0"),
        ),
        ("BBB-, BB+, BB0, BB-", _ranks("BBB-", "BB+", "BB0", "BB-")),
        ("B+, B0, B-", _ranks("B+", "B0", "B-")),
    ],
)
def test_t15_parse_grade_conditions(text, ranks):
    parsed = parse_condition(text)
    assert parsed is not None, text
    assert parsed.unit == "grade"
    assert parsed.ranks == ranks
    assert parsed.lo is None and parsed.hi is None


def test_t15_grade_comparisons_same_direction_union_opposite_intersect():
    # 표의 열을 합친 행 표기(강원대 T088 "CCC+ 이하 | C 이하 | CCC+ 이하")
    assert parse_condition("CCC+ 이하 | C 이하 | CCC+ 이하").ranks == _ranks_between(1, 6)
    assert parse_condition("BBB0 이상 A0 미만").ranks == _ranks_between(14, 16)


def test_t15_grade_token_is_checked_before_numbers():
    # X13: "A0 이상"·"BBB0 이상"의 `0`을 숫자 조건 "0 이상"으로 읽지 않는다
    for text in ("A0 이상", "BBB0 이상"):
        parsed = parse_condition(text)
        assert parsed is not None
        assert parsed.unit == "grade"
        assert parsed.lo is None


def test_t15_number_glued_to_latin_letters_is_not_a_numeric_condition():
    # 기업어음 등급(A30)·코드처럼 영문에 붙은 숫자는 숫자 조건이 아니다(X13 경계)
    assert parse_condition("A30 이하") is None
    assert parse_condition("ISO9001 이상") is None


@pytest.mark.parametrize("text", ["우수", "", "보통", "SW보안약점진단원 미참여", "30 point 이상"])
def test_t15_uninterpretable_conditions_return_none(text):
    assert parse_condition(text) is None


def test_t15_mixed_unit_kinds_are_uninterpretable():
    assert parse_condition("10% 이상 ~ 20건 미만") is None


def test_t15_parsed_condition_is_frozen_dataclass_with_spec_fields():
    parsed = parse_condition("30건 이상")
    assert isinstance(parsed, ParsedCondition)
    assert list(ParsedCondition.__dataclass_fields__) == [
        "unit",
        "lo",
        "lo_incl",
        "hi",
        "hi_incl",
        "ranks",
    ]
    with pytest.raises(AttributeError):
        parsed.lo = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("bbb", "BBB0"),
        ("A +", "A+"),
        ("AAA", "AAA"),
        ("XYZ", None),
        ("BBB0", "BBB0"),
        ("aa-", "AA-"),
        ("A", "A0"),
        ("BB", "BB0"),
        ("B", "B0"),
        ("CCC", "CCC0"),
        ("cc", "CC"),
        ("C", "C"),
        ("D", "D"),
        ("", None),
        ("unknown", None),
        ("BBB0 (2025)", None),
    ],
)
def test_t15_normalize_grade(text, expected):
    assert normalize_grade(text) == expected


# --- T16: GRADE_ORDER ---


def test_t16_grade_order_has_22_grades_in_descending_rank():
    expected = [
        "AAA",
        "AA+",
        "AA0",
        "AA-",
        "A+",
        "A0",
        "A-",
        "BBB+",
        "BBB0",
        "BBB-",
        "BB+",
        "BB0",
        "BB-",
        "B+",
        "B0",
        "B-",
        "CCC+",
        "CCC0",
        "CCC-",
        "CC",
        "C",
        "D",
    ]
    assert len(GRADE_ORDER) == 22
    assert sorted(GRADE_ORDER, key=GRADE_ORDER.__getitem__, reverse=True) == expected
    assert GRADE_ORDER["AAA"] == 22
    assert GRADE_ORDER["D"] == 1


def test_t16_below_excludes_the_grade_itself():
    parsed = parse_condition("BB+ 미만")
    assert parsed is not None
    assert GRADE_ORDER["BB+"] not in parsed.ranks
    assert parsed.ranks == _ranks_between(1, 11)


# --- T22: points_for 공통 규칙 ---


def _pf(criteria, value, *, kind="CERT_COUNT", max_points=3.0, label="registrations.x"):
    return points_for(_criteria(*criteria), value, kind=kind, max_points=max_points, label=label)


def test_t22_one_uninterpretable_condition_gives_criteria_range_for_known_value():
    r = _pf([("30건 이상", 3), ("우수", 2)], 35)
    assert (r.est_min, r.est_max) == (2, 3)
    assert "해석 불가 조건 1건" in r.basis


def test_t22_uninterpretable_condition_gives_criteria_range_even_for_unknown_value():
    r = _pf([("30건 이상", 3), ("우수", 2)], UNKNOWN)
    assert (r.est_min, r.est_max) == (2, 3)
    assert "해석 불가 조건 1건" in r.basis


def test_t22_no_matching_condition_gives_zero():
    r = _pf([("30건 이상", 3), ("20건 이상", 2)], 5)
    assert (r.est_min, r.est_max) == (0, 0)
    assert "해당 구간 없음" in r.basis


def test_t22_points_above_max_points_are_clamped():
    r = _pf([("30건 이상", 5)], 35, max_points=3)
    assert (r.est_min, r.est_max) == (3, 3)


def test_t22_unit_mismatch_counts_as_uninterpretable():
    # CERT_COUNT에 % 조건 → 해석 불가로 센다
    r = _pf([("100% 이상", 3), ("30건 이상", 2)], 35)
    assert (r.est_min, r.est_max) == (2, 3)
    assert "해석 불가 조건 1건" in r.basis


def test_t22_known_value_selects_matching_condition_and_formats_basis():
    r = _pf([("30건 이상", 3), ("20건 이상 ~ 30건 미만", 2)], 25, label="registrations.y")
    assert (r.est_min, r.est_max) == (2, 2)
    assert r.basis == "registrations.y=25 → 20건 이상 ~ 30건 미만 2점"


def test_t22_overlapping_cumulative_tiers_pick_highest_points():
    # 35건은 "30건 이상"과 "20건 이상"을 모두 만족 → 가장 높은 구간(T19와 같은 규칙)
    r = _pf([("20건 이상", 2), ("30건 이상", 3)], 35, label="registrations.y")
    assert (r.est_min, r.est_max) == (3, 3)
    assert r.basis == "registrations.y=35 → 30건 이상 3점"


def test_t22_unitless_condition_is_count_for_cert_count():
    r = _pf([("30 이상", 3)], 35)
    assert (r.est_min, r.est_max) == (3, 3)


def test_t22_unknown_range_lower_bound_is_zero_when_domain_minimum_matches_nothing():
    r = _pf([("30건 이상", 3), ("20건 이상", 2)], UNKNOWN, label="registrations.z")
    assert (r.est_min, r.est_max) == (0, 3)
    assert r.basis == "registrations.z 미확인: 0~3점"


def test_t22_unknown_range_lower_bound_is_criteria_minimum_when_domain_minimum_matches():
    r = _pf([("20건 이상", 3), ("20건 미만", 1)], UNKNOWN)
    assert (r.est_min, r.est_max) == (1, 3)


def test_t22_unknown_grade_uses_d_as_domain_minimum():
    criteria = [("A0 이상", 10), ("BBB0 ~ BBB-", 9), ("BB+ 이하", 8)]
    r = _pf(criteria, UNKNOWN, kind="CREDIT_RATING", max_points=10)
    assert (r.est_min, r.est_max) == (8, 10)
    no_floor = [("A0 이상", 10), ("BBB0 ~ BBB-", 9)]
    r = _pf(no_floor, UNKNOWN, kind="CREDIT_RATING", max_points=10)
    assert (r.est_min, r.est_max) == (0, 10)


def test_t22_known_grade_matches_by_rank():
    criteria = [("A0 이상", 10), ("BBB0 ~ BBB-", 9), ("BB+ 이하", 8)]
    assert _pf(criteria, "BBB0", kind="CREDIT_RATING", max_points=10).est_min == 9
    assert _pf(criteria, "AA-", kind="CREDIT_RATING", max_points=10).est_min == 10
    assert _pf(criteria, "B0", kind="CREDIT_RATING", max_points=10).est_max == 8


def test_t22_grade_condition_is_unit_mismatch_for_count_kinds():
    r = _pf([("A0 이상", 3), ("30건 이상", 2)], 35)
    assert "해석 불가 조건 1건" in r.basis


def test_t22_empty_criteria_gives_full_range():
    r = _pf([], 35, max_points=4)
    assert (r.est_min, r.est_max) == (0, 4)
    assert "배점 기준 없음" in r.basis


def test_t22_startup_criterion_is_excluded_from_general_calculation():
    criteria = [("A0 이상", 10), ("창업 7년 이내 기업", 10), ("BBB0 ~ BBB-", 9)]
    # "창업" 조건은 해석 불가로 세지 않고(제외), 일반 조건만으로 계산
    r = _pf(criteria, "BBB0", kind="CREDIT_RATING", max_points=10)
    assert (r.est_min, r.est_max) == (9, 9)
    assert "해석 불가" not in r.basis


def test_t22_estimate_never_exceeds_bounds():
    r = _pf([("우수", 7), ("보통", 5)], 1, max_points=3)
    assert 0 <= r.est_min <= r.est_max <= 3


# --- STEP-006: estimate_scores(T17~T21) ---

AS_OF = date(2026, 11, 5)  # 창 = 2023-11-05 ~ 2026-11-05(최근 3년, 비창업)
CREDIT_CRITERIA = [("A0 이상", 10), ("BBB0~BBB-", 9), ("BB+ 이하", 8)]
STARTUP_CRITERION = ("창업 7년 이내 기업", 10)
GRADE_PATH = "registrations.credit_rating.grade"
OLD = {"company.founded": "2015-01"}  # 비창업(창업 7년 경과)


def _one(item: EvalItem, profile, *, budget_krw: int | None = None) -> ScoreEstimate:
    facts = make_facts(quantitative=[item], budget_krw=budget_krw)
    [estimate] = estimate_scores(facts, profile, as_of=AS_OF)
    return estimate


def _span(est: ScoreEstimate) -> tuple[float, float]:
    return est.est_min, est.est_max


# T17: CREDIT_RATING


def test_t17_startup_within_7_years_gets_full_points():
    item = eval_item("신용평가등급", 10, "CREDIT_RATING", [*CREDIT_CRITERIA, STARTUP_CRITERION])
    est = _one(item, make_profile({"company.founded": "2022-09"}))
    assert _span(est) == (10, 10)
    assert "창업 7년 이내 특례(만점)" in est.basis
    assert est.unknown_inputs == []


def test_t17_non_startup_grade_bbb0():
    item = eval_item("신용평가등급", 10, "CREDIT_RATING", [*CREDIT_CRITERIA, STARTUP_CRITERION])
    est = _one(item, make_profile({**OLD, GRADE_PATH: "BBB0"}))
    assert _span(est) == (9, 9)
    assert est.basis == f"{GRADE_PATH}=BBB0 → BBB0~BBB- 9점"
    assert est.unknown_inputs == []
    assert (est.item, est.kind, est.max_points) == ("신용평가등급", "CREDIT_RATING", 10)


def test_rev_t4_legacy_known_grade_does_not_narrow_score_range():
    item = eval_item("신용평가등급", 10, "CREDIT_RATING", CREDIT_CRITERIA)
    profile = make_profile({GRADE_PATH: "BBB0"})
    [est] = _estimate_scores(
        make_facts(quantitative=[item]), CompanyEvidenceView(profile), as_of=AS_OF
    )
    assert _span(est) == (8, 10)
    assert est.unknown_inputs == [GRADE_PATH]
    assert est.input_fields == [GRADE_PATH]


def test_t17_signless_grade_is_normalized():
    item = eval_item("신용평가등급", 10, "CREDIT_RATING", CREDIT_CRITERIA)
    est = _one(item, make_profile({**OLD, GRADE_PATH: "BBB"}))
    assert _span(est) == (9, 9)


def test_t17_unknown_grade_gives_unknown_range():
    # D가 "BB+ 이하"를 만족하므로 하한은 criteria 최솟값 8
    item = eval_item("신용평가등급", 10, "CREDIT_RATING", CREDIT_CRITERIA)
    est = _one(item, make_profile(OLD))
    assert _span(est) == (8, 10)
    assert est.unknown_inputs == [GRADE_PATH]


def test_t17_grade_outside_dictionary_is_unknown_with_warning():
    item = eval_item("신용평가등급", 10, "CREDIT_RATING", CREDIT_CRITERIA)
    est = _one(item, make_profile({**OLD, GRADE_PATH: "XYZ"}))
    assert _span(est) == (8, 10)
    assert est.unknown_inputs == [GRADE_PATH]
    assert "등급 해석 불가: XYZ" in est.basis


def test_t17_founded_unknown_includes_startup_possibility():
    item = eval_item("신용평가등급", 10, "CREDIT_RATING", [*CREDIT_CRITERIA, STARTUP_CRITERION])
    est = _one(item, make_profile({GRADE_PATH: "BBB0"}))
    assert _span(est) == (9, 10)
    assert est.unknown_inputs == ["company.founded"]


def test_t17_startup_keyword_in_item_name_triggers_exception():
    item = eval_item("경영상태(창업기업 특례)", 10, "CREDIT_RATING", CREDIT_CRITERIA)
    assert _span(_one(item, make_profile({"company.founded": "2022-09"}))) == (10, 10)


def test_t17_without_startup_condition_founded_is_irrelevant():
    item = eval_item("신용평가등급", 10, "CREDIT_RATING", CREDIT_CRITERIA)
    est = _one(item, make_profile({GRADE_PATH: "A+"}))  # founded unknown이어도 특례 조건 없음
    assert _span(est) == (10, 10)
    assert est.unknown_inputs == []


def test_t17_startup_criterion_excluded_from_general_calculation():
    item = eval_item("신용평가등급", 10, "CREDIT_RATING", [*CREDIT_CRITERIA, STARTUP_CRITERION])
    est = _one(item, make_profile({**OLD, GRADE_PATH: "B0"}))
    assert _span(est) == (8, 8)
    assert "해석 불가" not in est.basis


def test_t17_real_knu_credit_table_rows():
    # 강원대 T088 기업신용평가등급 열(행 = criterion)
    criteria = [
        ("AAA, AA+, AA0, AA-, A+, A0, A-, BBB+, BBB0", 10),
        ("BBB-, BB+, BB0, BB-", 9.5),
        ("B+, B0, B-", 9),
        ("CCC+ 이하", 7),
    ]
    item = eval_item("경영상태", 10, "CREDIT_RATING", criteria)
    assert _span(_one(item, make_profile({**OLD, GRADE_PATH: "BB+"}))) == (9.5, 9.5)
    assert _span(_one(item, make_profile(OLD))) == (7, 10)  # D가 "CCC+ 이하" 만족


# T18: PAST_PERFORMANCE

PERF_CRITERIA = [("100% 이상", 5), ("50% 이상 ~ 100% 미만", 3)]
BUDGET = 100_000_000


def _perf(id: str, amount: int | str, *, role: str = "주사업자", end: str = "2025-06", **kw):
    completed = kw.pop("completed", True)
    return portfolio_item(
        id, amount_krw=amount, role=role, completed=completed, period_end=end, **kw
    )


def _perf_item(criteria=PERF_CRITERIA) -> EvalItem:
    return eval_item("사업수행실적(최근 3년)", 5, "PAST_PERFORMANCE", criteria)


def test_t18_all_amounts_known_ratio_120pct():
    portfolio = [_perf("P2025-01", 70_000_000), _perf("P2025-02", 50_000_000)]
    est = _one(_perf_item(), make_profile(OLD, portfolio=portfolio), budget_krw=BUDGET)
    assert _span(est) == (5, 5)
    assert "120%" in est.basis
    assert est.unknown_inputs == []


def test_rev_t4_unconfirmed_portfolio_completeness_keeps_upper_bound_open():
    item = _perf_item()
    profile = make_profile(OLD, portfolio=[_perf("P2025-01", 60_000_000)])
    view = confirmed_view(
        profile,
        [
            "company.founded",
            "portfolio[P2025-01].completed",
            "portfolio[P2025-01].period.end",
            "portfolio[P2025-01].amount_krw",
            "portfolio[P2025-01].role",
        ],
    )
    [est] = _estimate_scores(make_facts(quantitative=[item], budget_krw=BUDGET), view, as_of=AS_OF)
    assert _span(est) == (3, 5)
    assert est.unknown_inputs == ["portfolio"]
    assert est.input_fields[-1] == "portfolio"


def test_t18_unknown_amount_gives_known_lower_bound_and_full_upper():
    portfolio = [_perf("P2025-01", 60_000_000), _perf("P2025-02", "unknown")]
    est = _one(_perf_item(), make_profile(OLD, portfolio=portfolio), budget_krw=BUDGET)
    assert _span(est) == (3, 5)
    assert est.unknown_inputs == ["portfolio[P2025-02].amount_krw"]


def test_t18_role_unknown_amount_counts_as_unconfirmed():
    portfolio = [_perf("P2025-01", 60_000_000), _perf("P2025-02", 50_000_000, role="unknown")]
    est = _one(_perf_item(), make_profile(OLD, portfolio=portfolio), budget_krw=BUDGET)
    assert _span(est) == (3, 5)
    assert est.unknown_inputs == ["portfolio[P2025-02].role"]


def test_t18_budget_unknown_gives_criteria_range_not_unknown_range():
    portfolio = [_perf("P2025-01", 120_000_000)]
    est = _one(_perf_item(), make_profile(OLD, portfolio=portfolio), budget_krw=None)
    assert _span(est) == (3, 5)
    assert "사업금액 미상" in est.basis


def test_t18_krw_condition_compares_known_sum():
    criteria = [("3억원 이상", 5), ("1억원 이상", 3)]
    portfolio = [_perf("P2025-01", 70_000_000), _perf("P2025-02", 50_000_000)]
    # krw 조건은 사업금액이 필요 없다
    est = _one(_perf_item(criteria), make_profile(OLD, portfolio=portfolio), budget_krw=None)
    assert _span(est) == (3, 3)
    assert "120,000,000원" in est.basis


def test_t18_count_condition_counts_confirmed_candidates():
    criteria = [("2건 이상", 5), ("1건 이상", 3)]
    portfolio = [_perf("P2025-01", 1), _perf("P2025-02", 1)]
    assert _span(_one(_perf_item(criteria), make_profile(OLD, portfolio=portfolio))) == (5, 5)


def test_t18_count_condition_ignores_unknown_amounts():
    # 건수 조건은 금액과 무관 — 금액 미확인 실적이 있어도 구간을 넓히지 않는다
    criteria = [("2건 이상", 5), ("1건 이상", 3)]
    portfolio = [_perf("P2025-01", "unknown"), _perf("P2025-02", 1)]
    est = _one(_perf_item(criteria), make_profile(OLD, portfolio=portfolio))
    assert _span(est) == (5, 5)
    assert est.unknown_inputs == []


def test_t18_window_excludes_projects_ended_before_recent_years():
    portfolio = [_perf("P2025-01", 60_000_000), _perf("P2022-01", 60_000_000, end="2022-06")]
    est = _one(_perf_item(), make_profile(OLD, portfolio=portfolio), budget_krw=BUDGET)
    assert _span(est) == (3, 3)


def test_t18_startup_window_starts_at_founding():
    # 창업 2021-01 → as_of 2026-11-05는 7년 이내 → 창 = 창업일 이후 전체
    portfolio = [_perf("P2025-01", 60_000_000), _perf("P2022-01", 60_000_000, end="2022-06")]
    profile = make_profile({"company.founded": "2021-01"}, portfolio=portfolio)
    assert _span(_one(_perf_item(), profile, budget_krw=BUDGET)) == (5, 5)


def test_t18_consortium_share_pct_scales_amount():
    portfolio = [_perf("P2025-01", 100_000_000, role="공동수급", share_pct=40)]
    est = _one(_perf_item(), make_profile(OLD, portfolio=portfolio), budget_krw=BUDGET)
    assert _span(est) == (0, 0)  # 40% → 해당 구간 없음
    assert "40%" in est.basis


def test_t18_consortium_share_unknown_is_unconfirmed_amount():
    portfolio = [_perf("P2025-01", 100_000_000, role="공동수급", share_pct="unknown")]
    est = _one(_perf_item(), make_profile(OLD, portfolio=portfolio), budget_krw=BUDGET)
    assert _span(est) == (0, 5)
    assert est.unknown_inputs == ["portfolio[P2025-01].share_pct"]


def test_t18_uncertain_candidates_widen_upper_bound():
    portfolio = [
        _perf("P2025-01", 60_000_000),
        _perf("P2025-02", 50_000_000, completed="unknown"),
        _perf("P2025-03", 50_000_000, end="unknown"),
    ]
    est = _one(_perf_item(), make_profile(OLD, portfolio=portfolio), budget_krw=BUDGET)
    assert _span(est) == (3, 5)
    assert est.unknown_inputs == [
        "portfolio[P2025-02].completed",
        "portfolio[P2025-03].period.end",
    ]


def test_t18_incomplete_projects_are_excluded():
    portfolio = [_perf("P2025-01", 60_000_000), _perf("P2026-01", 90_000_000, completed=False)]
    est = _one(_perf_item(), make_profile(OLD, portfolio=portfolio), budget_krw=BUDGET)
    assert _span(est) == (3, 3)


def test_t18_founded_unknown_is_reported_as_window_input():
    portfolio = [_perf("P2025-01", 120_000_000)]
    est = _one(_perf_item(), make_profile(portfolio=portfolio), budget_krw=BUDGET)
    assert _span(est) == (5, 5)
    assert est.unknown_inputs == ["company.founded"]


# T19: CERT_COUNT

WEB_PATH = "registrations.web_accessibility_certs.count"
EGOV_PATH = "registrations.egov_framework_inspection_reports"
CERT_CRITERIA = [("30건 이상", 3), ("20건 이상", 2)]


def test_t19_web_accessibility_count_known():
    item = eval_item("웹 접근성 품질인증 획득 실적", 3, "CERT_COUNT", CERT_CRITERIA)
    est = _one(item, make_profile({WEB_PATH: 35}))
    assert _span(est) == (3, 3)
    assert est.basis == f"{WEB_PATH}=35 → 30건 이상 3점"


def test_t19_web_accessibility_count_unknown():
    item = eval_item("웹접근성 품질인증", 3, "CERT_COUNT", CERT_CRITERIA)
    est = _one(item, make_profile())
    assert _span(est) == (0, 3)  # 0건은 어느 조건도 불만족
    assert est.unknown_inputs == [WEB_PATH]


def test_t19_egov_framework_routes_to_inspection_reports():
    criteria = [("5건 이상", 2), ("1건 이상", 1)]
    item = eval_item("전자정부표준프레임워크 적용점검결과서", 2, "CERT_COUNT", criteria)
    est = _one(item, make_profile({EGOV_PATH: 3, WEB_PATH: 40}))
    assert _span(est) == (1, 1)
    assert est.basis.startswith(f"{EGOV_PATH}=3")


def test_t19_keyword_in_criteria_text_also_routes():
    item = eval_item("기술현황", 3, "CERT_COUNT", [("웹 접근성 인증 30건 이상", 3)])
    assert _span(_one(item, make_profile({WEB_PATH: 31}))) == (3, 3)


def test_t19_unknown_cert_kind_gives_criteria_range():
    item = eval_item("기술현황", 3, "CERT_COUNT", CERT_CRITERIA)
    est = _one(item, make_profile({WEB_PATH: 35}))
    assert _span(est) == (2, 3)
    assert "인증 종류 판별 불가" in est.basis
    assert est.unknown_inputs == []


# T20: STAFF_TRAINING

SEC_PATH = "people.trainings.sw_security_diagnostician"
TEST_PATH = "people.trainings.sw_test_expert"


def test_t20_security_diagnostician_known():
    criteria = [("1명 이상", 1.5)]
    item = eval_item("기술자 교육이수현황(SW보안약점진단원)", 1.5, "STAFF_TRAINING", criteria)
    est = _one(item, make_profile({SEC_PATH: 2}))
    assert _span(est) == (1.5, 1.5)


def test_t20_security_diagnostician_unknown():
    item = eval_item("SW보안약점진단원 참여", 1.5, "STAFF_TRAINING", [("1명 이상", 1.5)])
    est = _one(item, make_profile())
    assert _span(est) == (0, 1.5)
    assert est.unknown_inputs == [SEC_PATH]


def test_t20_test_expert_routes_by_keyword():
    item = eval_item("SW테스트전문가 참여", 1.5, "STAFF_TRAINING", [("1건 이상", 1.5)])
    est = _one(item, make_profile({TEST_PATH: 0, SEC_PATH: 3}))
    assert _span(est) == (0, 0)
    assert est.basis.startswith(f"{TEST_PATH}=0")


def test_t20_unknown_training_kind_gives_criteria_range():
    criteria = [("2명 이상", 1.5), ("1명 이상", 1.1)]
    item = eval_item("기술자 교육이수현황", 1.5, "STAFF_TRAINING", criteria)
    est = _one(item, make_profile({SEC_PATH: 3}))
    assert _span(est) == (1.1, 1.5)
    assert "교육 종류 판별 불가" in est.basis


# T21: OTHER·빈 criteria


def test_t21_other_kind_is_full_range():
    item = eval_item("기술자 투입현황", 3, "OTHER", [("30 point 이상", 3)])
    est = _one(item, make_profile())
    assert _span(est) == (0, 3)
    assert "규칙 계산 불가" in est.basis
    assert est.unknown_inputs == []


def test_t21_empty_criteria_is_full_range():
    item = eval_item("웹 접근성 품질인증", 4, "CERT_COUNT", [])
    est = _one(item, make_profile({WEB_PATH: 35}))
    assert _span(est) == (0, 4)
    assert "배점 기준 없음" in est.basis


# 조합


def test_estimate_scores_one_per_item_in_order_and_deterministic():
    items = [
        eval_item("신용평가등급", 10, "CREDIT_RATING", CREDIT_CRITERIA),
        eval_item("웹 접근성", 4, "CERT_COUNT", CERT_CRITERIA),
        eval_item("기타", 2, "OTHER"),
    ]
    facts = make_facts(quantitative=items)
    profile = make_profile({**OLD, GRADE_PATH: "A0", WEB_PATH: 21})
    first = estimate_scores(facts, profile, as_of=AS_OF)
    assert [e.item for e in first] == ["신용평가등급", "웹 접근성", "기타"]
    assert [_span(e) for e in first] == [(10, 10), (2, 2), (0, 2)]
    assert estimate_scores(facts, profile, as_of=AS_OF) == first
    for e in first:
        assert 0 <= e.est_min <= e.est_max <= e.max_points


def test_estimate_scores_empty_quantitative():
    assert estimate_scores(make_facts(), make_profile(), as_of=AS_OF) == []


# --- GT-02 T8: 점수 규칙은 실적 키워드 대조를 쓰지 않는다(scoring.py 불변) ---


def test_scoring_does_not_use_perf_keyword_matching():
    source = Path(scoring.__file__).read_text(encoding="utf-8")
    for name in ("keyword_match", "parse_perf_keyword", "perf_variants", "PERF_", "PerfKeyword"):
        assert name not in source


def test_legacy_keyword_match_removed_from_gates():
    assert not hasattr(gates, "_keyword_match")
    source = Path(gates.__file__).read_text(encoding="utf-8")
    assert "def _keyword_match" not in source
    assert callable(gates.keyword_match)
    assert callable(gates.parse_perf_keyword)


# --- REV-04 T5: score request exclusion proof is pure and deterministic ---


def test_rev04_t5_score_request_exclusion_is_pure_and_deterministic():
    profile = make_profile(
        {"company.founded": "2010-01"},
        portfolio=[portfolio_item("P2020-01", period_end="2020-12", completed="unknown")],
    )
    view = confirmed_view(profile, ["company.founded", "portfolio[P2020-01].period.end"])
    item = eval_item("사업수행실적(최근 3년)", 5, "PAST_PERFORMANCE", [("1건 이상", 5)])
    facts = make_facts(quantitative=[item])
    estimate = ScoreEstimate(
        item=item.item,
        kind="PAST_PERFORMANCE",
        max_points=5,
        est_min=0,
        est_max=5,
        basis="합성",
        unknown_inputs=["portfolio[P2020-01].completed"],
    )
    snapshot = (
        profile.model_dump_json(),
        facts.model_dump_json(),
        estimate.model_dump_json(),
        view.provenance.model_dump_json(),
    )

    results = [
        scoring.score_request_exclusion_reason(
            facts,
            item,
            estimate,
            view,
            "portfolio[P2020-01].completed",
            as_of=date(2026, 11, 5),
        )
        for _ in range(2)
    ]

    assert results == ["out_of_scope", "out_of_scope"]
    assert (
        profile.model_dump_json(),
        facts.model_dump_json(),
        estimate.model_dump_json(),
        view.provenance.model_dump_json(),
    ) == snapshot
    # Not a past-performance score, or not a portfolio path: no proof, the request stays.
    credit = estimate.model_copy(update={"kind": "CREDIT_RATING"})
    assert (
        scoring.score_request_exclusion_reason(
            facts, item, credit, view, "portfolio[P2020-01].completed", as_of=date(2026, 11, 5)
        )
        is None
    )
    assert (
        scoring.score_request_exclusion_reason(
            facts, item, estimate, view, "company.founded", as_of=date(2026, 11, 5)
        )
        is None
    )
