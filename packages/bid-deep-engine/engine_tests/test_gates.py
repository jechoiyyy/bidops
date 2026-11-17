"""결정적 게이트 테스트(spec M2-03). 이 파일은 단계별로 늘어난다.

STEP-001: T1(스키마), T2(`resolve_as_of` 세 경우), 날짜 헬퍼·`is_startup`·`performance_window`,
테스트 빌더(`tests/gate_factories.py`) 동작.
STEP-002: T3~T9, T11(자격·등록 게이트 규칙, `normalize_region`).
STEP-003: T10(실적 게이트, 창업기업 특례 창).
STEP-004: T2 기준일 접미, T12(STAFFING_CAPACITY), T13(ONSITE_LOCATION), T14(조합·결정성).
GT-01 STEP-002: T1 갱신(GateCode 17개), GT T2(`reclassify_other` — 리뷰 2회 뒤 허용 목록 템플릿·
`norm_clause`), GT T3(재분류 게이트), GT T4
(CONSORTIUM_CONDITION·INSOLVENCY 규칙), GT T6(`profile_cert_names` other_certs·별칭).
GT-02 STEP-001: T1(`parse_perf_keyword`·`perf_norm`), T2(`perf_variants`·상수), T3(`keyword_match`).
GT-02 STEP-002: T4(`_performance_rule` 유형 분기·`portfolio[ID].type` 경로·company_value 접미).
네트워크·LLM을 쓰지 않는다.
"""

import inspect
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

import bid_deep_engine.analysis.gates as gates_module
from bid_deep_engine.analysis.gates import (
    ACTION_CHECK_CONSORTIUM,
    FAIL_ACTION,
    OTHER_CERT_ALIASES,
    OTHER_RECLASS,
    PERF_STOPWORDS,
    PERF_SYNONYMS,
    PERF_TYPE_TOKENS,
    RECLASS_SUFFIX,
    STARTUP_YEARS,
    PerfKeyword,
    add_years,
    eligibility_rule_hash,
    eligibility_rule_payload,
    keyword_match,
    norm_clause,
    norm_compact,
    normalize_region,
    onsite_location_rule_payload,
    parse_leading_date,
    parse_perf_keyword,
    perf_norm,
    perf_variants,
    profile_cert_names,
    profile_date,
    reclassify_other,
    resolve_as_of,
    rule_payload_hash,
    staffing_capacity_rule_payload,
)
from bid_deep_engine.analysis.gates import (
    evaluate_gates as _evaluate_gates,
)
from bid_deep_engine.analysis.gates import (
    is_startup as _is_startup,
)
from bid_deep_engine.analysis.gates import (
    performance_window as _performance_window,
)
from bid_deep_engine.analysis.schemas import (
    EligibilityCode,
    EvalKind,
    GateCode,
    GateResult,
    RuleParams,
    ScoreEstimate,
    Verdict,
)
from bid_deep_engine.company.hints import hint_for
from bid_deep_engine.company.loader import todo
from bid_deep_engine.company.provenance import CompanyEvidenceView, encode_path_token
from bid_deep_engine.company.schema import ProjectType
from engine_tests.gate_factories import (
    EVIDENCE,
    confirmed_fixture_view,
    confirmed_view,
    direct_production,
    eval_item,
    make_evidence,
    make_facts,
    make_profile,
    other_cert,
    portfolio_item,
    rule,
    staffing,
)


def evaluate_gates(facts, profile, *, as_of):
    if isinstance(profile, CompanyEvidenceView):
        return _evaluate_gates(facts, profile, as_of=as_of)
    return _evaluate_gates(facts, confirmed_fixture_view(profile), as_of=as_of)


def is_startup(profile, as_of):
    return _is_startup(confirmed_view(profile, ["company.founded"]), as_of)


def performance_window(profile, as_of, years):
    return _performance_window(confirmed_view(profile, ["company.founded"]), as_of, years)


# --- T1: 스키마 ---


def test_t1_gate_code_is_eligibility_code_plus_two_derived_plus_two_reclass():
    gate_codes = set(get_args(GateCode))
    eligibility_codes = set(get_args(EligibilityCode))
    assert len(eligibility_codes) == 13
    assert len(get_args(GateCode)) == len(gate_codes) == 17
    derived = {"STAFFING_CAPACITY", "ONSITE_LOCATION"}
    reclass = {"CONSORTIUM_CONDITION", "INSOLVENCY"}
    assert gate_codes == eligibility_codes | derived | reclass
    # 재분류 코드는 GateCode에만 있다(EligibilityCode·extract 프롬프트 불변, X76)
    assert not (reclass & eligibility_codes)


def test_t1_verdict_values():
    assert set(get_args(Verdict)) == {"PASS", "FAIL", "UNKNOWN", "RISK"}


def test_t1_gate_result_fields_and_defaults():
    assert list(GateResult.model_fields) == [
        "code",
        "rule_text",
        "company_value",
        "verdict",
        "evidence",
        "action",
        "unknown_fields",
        "input_fields",
        "rule_hash",
    ]
    g = GateResult(
        code="SME_CERT", rule_text="규칙", company_value="a=b", verdict="PASS", evidence=[EVIDENCE]
    )
    assert g.action is None
    assert g.unknown_fields == []
    assert g.input_fields == []
    assert g.rule_hash is None
    # 기본 리스트는 인스턴스마다 따로다.
    g.unknown_fields.append("x")
    other = GateResult(
        code="OTHER", rule_text="r", company_value="-", verdict="UNKNOWN", evidence=[]
    )
    assert other.unknown_fields == []


def test_t1_gate_result_evidence_is_required_but_may_be_empty():
    base = {"code": "STAFFING_CAPACITY", "rule_text": "r", "company_value": "c", "verdict": "RISK"}
    assert GateResult(**base, evidence=[]).evidence == []
    with pytest.raises(ValidationError):
        GateResult(**base)


def test_rev02_t6_rule_hash_payloads_and_golden_hashes():
    text = "AI\u00a0챗봇 (생성형\nAI)"
    assert eligibility_rule_payload(text) == {
        "schema_version": 1,
        "origin": "eligibility",
        "text": "AI챗봇(생성형AI)",
    }
    assert eligibility_rule_hash(text) == (
        "e31658bec63b1c2d870f3e01efea6095b71cd9b299c297d4c35d4fb4dc1bedfb"
    )

    requirement = staffing(
        "PM",
        grade="고급",
        count=2,
        resident=True,
        location="서울특별시",
        min_years=5,
        notes=None,
    )
    facts = make_facts(staffing=[requirement], consortium_allowed=False, subcontract_allowed=None)
    staffing_payload = staffing_capacity_rule_payload(facts)
    assert staffing_payload == {
        "schema_version": 1,
        "origin": "staffing_capacity",
        "requirements": [
            {
                "role": "PM",
                "grade": "고급",
                "count": 2,
                "resident": True,
                "location": "서울특별시",
                "min_years": 5,
                "notes": None,
            }
        ],
        "consortium_allowed": False,
        "subcontract_allowed": None,
    }
    assert rule_payload_hash(staffing_payload) == (
        "34d8136cdace8883a1278bfbca8899e0e09c651c2a678648e36133dfa7b6716d"
    )
    onsite_payload = onsite_location_rule_payload(requirement)
    assert onsite_payload == {
        "schema_version": 1,
        "origin": "onsite_location",
        "requirement": staffing_payload["requirements"][0],
    }
    assert rule_payload_hash(onsite_payload) == (
        "0ada8a742b734105cec4f387c4578b9c7d2aeb423e471c32b178a8bb4ba86b47"
    )


def test_rev02_t6_rule_hash_uses_source_facts_not_evidence_or_display_suffix():
    requirement = staffing("개발자", count=1, resident=True, location="서울")
    changed_evidence = staffing(
        "개발자",
        count=1,
        resident=True,
        location="서울",
        evidence=make_evidence("다른 인용"),
    )
    assert rule_payload_hash(onsite_location_rule_payload(requirement)) == rule_payload_hash(
        onsite_location_rule_payload(changed_evidence)
    )
    assert eligibility_rule_hash("A B") == eligibility_rule_hash("A\nB")
    assert eligibility_rule_hash("A B") != eligibility_rule_hash("A B [기준일 2026-11-03]")


@pytest.mark.parametrize("missing", ["code", "rule_text", "company_value", "verdict"])
def test_t1_gate_result_required_fields(missing):
    data = {
        "code": "OTHER",
        "rule_text": "r",
        "company_value": "c",
        "verdict": "UNKNOWN",
        "evidence": [],
    }
    del data[missing]
    with pytest.raises(ValidationError):
        GateResult(**data)


@pytest.mark.parametrize("bad", ["pass", "OK", "MAYBE", "", None])
def test_t1_gate_result_rejects_other_verdicts(bad):
    with pytest.raises(ValidationError):
        GateResult(code="OTHER", rule_text="r", company_value="c", verdict=bad, evidence=[])


def test_t1_gate_result_rejects_unknown_code():
    with pytest.raises(ValidationError):
        GateResult(code="NOPE", rule_text="r", company_value="c", verdict="PASS", evidence=[])


def test_t1_score_estimate_fields_and_defaults():
    assert list(ScoreEstimate.model_fields) == [
        "item",
        "kind",
        "max_points",
        "est_min",
        "est_max",
        "basis",
        "unknown_inputs",
        "input_fields",
    ]
    s = ScoreEstimate(
        item="신용평가", kind="CREDIT_RATING", max_points=10, est_min=8, est_max=10, basis="b"
    )
    assert s.unknown_inputs == []
    assert s.input_fields == []
    assert set(get_args(EvalKind)) >= {s.kind}
    with pytest.raises(ValidationError):
        ScoreEstimate(item="i", kind="NOPE", max_points=1, est_min=0, est_max=1, basis="b")


def test_t1_models_roundtrip_json():
    g = GateResult(
        code="ONSITE_LOCATION",
        rule_text="r",
        company_value="c",
        verdict="RISK",
        evidence=[EVIDENCE],
        action="a",
        unknown_fields=["people.onsite_capacity.서울.ok"],
    )
    assert GateResult.model_validate_json(g.model_dump_json()) == g


def test_rev_input_fields_preserve_order_and_remove_duplicates():
    g = GateResult(
        code="SME_CERT",
        rule_text="규칙",
        company_value="-",
        verdict="UNKNOWN",
        evidence=[],
        input_fields=["b", "a", "b"],
    )
    s = ScoreEstimate(
        item="점수",
        kind="OTHER",
        max_points=1,
        est_min=0,
        est_max=1,
        basis="범위",
        input_fields=["x", "x", "y"],
    )
    assert g.input_fields == ["b", "a"]
    assert s.input_fields == ["x", "y"]


# --- T2: resolve_as_of ---


def test_t2_submission_deadline_wins():
    facts = make_facts(submission_deadline="2026-11-05 10:00", notice_date="2026-10-15")
    assert resolve_as_of(facts, date(2026, 10, 22)) == (date(2026, 11, 5), "submission_deadline")


def test_t2_falls_back_to_notice_date_when_deadline_missing():
    facts = make_facts(submission_deadline=None, notice_date="2026-10-15")
    assert resolve_as_of(facts, date(2026, 10, 22)) == (date(2026, 10, 15), "notice_date")


def test_t2_falls_back_to_notice_date_when_deadline_unparseable():
    facts = make_facts(submission_deadline="미정", notice_date="2026-10-15 09:00")
    assert resolve_as_of(facts, date(2026, 10, 22)) == (date(2026, 10, 15), "notice_date")


def test_t2_falls_back_to_run_date():
    facts = make_facts(submission_deadline="미정", notice_date=None)
    assert resolve_as_of(facts, date(2026, 10, 22)) == (date(2026, 10, 22), "run_date")


def test_t2_run_date_defaults_to_today():
    as_of, source = resolve_as_of(make_facts())
    assert source == "run_date"
    assert as_of == date.today()


@pytest.mark.parametrize("text", ["2026-11", "2026/11/05", "2026-13-40", "2026-02-30", "", "  "])
def test_t2_unparseable_dates_fall_through(text):
    facts = make_facts(submission_deadline=text, notice_date=text)
    assert resolve_as_of(facts, date(2026, 10, 22)) == (date(2026, 10, 22), "run_date")


def test_parse_leading_date():
    assert parse_leading_date("2026-11-05") == date(2026, 11, 5)
    assert parse_leading_date("2026-11-05T10:00:00") == date(2026, 11, 5)
    assert parse_leading_date("제출 2026-11-05") is None  # 앞부분이 날짜가 아니면 해석 불가
    assert parse_leading_date(None) is None


# --- 날짜 헬퍼 ---


def test_add_years_regular_and_leap_day():
    assert add_years(date(2026, 11, 5), -3) == date(2023, 11, 5)
    assert add_years(date(2022, 9, 1), STARTUP_YEARS) == date(2029, 9, 1)
    assert add_years(date(2024, 2, 29), 1) == date(2025, 2, 28)
    assert add_years(date(2024, 2, 29), -4) == date(2020, 2, 29)  # 윤년이면 그대로
    assert add_years(date(2024, 2, 29), -1) == date(2023, 2, 28)


def test_profile_date_month_end_vs_start():
    assert profile_date("2026-03", end_of_month=True) == date(2026, 3, 31)
    assert profile_date("2026-04", end_of_month=True) == date(2026, 4, 30)
    assert profile_date("2025-02", end_of_month=True) == date(2025, 2, 28)
    assert profile_date("2024-02", end_of_month=True) == date(2024, 2, 29)
    assert profile_date("2026-03", end_of_month=False) == date(2026, 3, 1)
    assert profile_date("2026-03-17", end_of_month=True) == date(2026, 3, 17)
    assert profile_date("2026-03-17", end_of_month=False) == date(2026, 3, 17)


@pytest.mark.parametrize("value", ["unknown", None, 2026, "2026", "2026-13", "2026-02-30", ""])
def test_profile_date_unreadable_is_none(value):
    assert profile_date(value, end_of_month=True) is None
    assert profile_date(value, end_of_month=False) is None


# --- is_startup / performance_window ---


def test_is_startup_within_seven_years():
    as_of = date(2026, 11, 1)
    assert is_startup(make_profile({"company.founded": "2022-09"}), as_of) is True


def test_is_startup_boundary_is_exclusive():
    founded_profile = make_profile({"company.founded": "2019-11-01"})
    assert is_startup(founded_profile, date(2026, 10, 31)) is True
    assert is_startup(founded_profile, date(2026, 11, 1)) is False  # as_of == founded + 7년
    assert is_startup(make_profile({"company.founded": "2015-01"}), date(2026, 11, 1)) is False


def test_is_startup_unknown_founded_is_none():
    assert is_startup(make_profile(), date(2026, 11, 1)) is None


def test_performance_window_non_startup():
    profile = make_profile({"company.founded": "2015-01"})
    as_of = date(2026, 11, 5)
    assert performance_window(profile, as_of, 3) == (date(2023, 11, 5), as_of)
    assert performance_window(profile, as_of, None) == (None, as_of)


def test_performance_window_startup_uses_founding_date():
    profile = make_profile({"company.founded": "2022-09"})
    as_of = date(2026, 11, 5)
    assert performance_window(profile, as_of, 3) == (date(2022, 9, 1), as_of)
    assert performance_window(profile, as_of, None) == (date(2022, 9, 1), as_of)


def test_performance_window_unknown_founded_is_treated_as_non_startup():
    as_of = date(2026, 11, 5)
    assert performance_window(make_profile(), as_of, 5) == (date(2021, 11, 5), as_of)
    assert performance_window(make_profile(), as_of, None) == (None, as_of)


# --- 테스트 빌더 ---


def test_factories_build_facts():
    facts = make_facts(
        submission_deadline="2026-11-05 10:00",
        budget_krw=500_000_000,
        eligibility=[rule("INDUSTRY_CODE", "업종", industry_code=["1468"])],
        staffing=[staffing("PM", grade="고급", count=1, resident=True, location="서울")],
        quantitative=[eval_item("신용평가", 10, "CREDIT_RATING", [("A0 이상", 10)])],
        consortium_allowed=False,
        subcontract_allowed=False,
    )
    assert facts.schedule.submission_deadline == "2026-11-05 10:00"
    assert facts.project.budget_krw == 500_000_000
    assert facts.eligibility[0].params.industry_code == ["1468"]
    assert facts.eligibility[0].params.region is None
    assert facts.eligibility[0].evidence == EVIDENCE
    assert facts.staffing[0].resident is True
    assert facts.evaluation.quantitative[0].criteria[0].condition == "A0 이상"
    assert facts.contract_terms.consortium.allowed is False
    assert facts.contract_terms.subcontract.allowed is False
    # 안 쓴 값은 RfpFacts 기본값
    empty = make_facts()
    assert empty.eligibility == [] and empty.contract_terms.consortium.allowed is None


def test_factories_build_profile_defaults_to_unknown():
    profile = make_profile()
    assert profile.company.size == "unknown"
    assert profile.registrations.sme_certificate.status == "unknown"
    assert profile.registrations.g2b.industry_codes == "unknown"
    assert profile.people.headcount_by_grade["고급"] == "unknown"
    assert profile.people.onsite_capacity["서울"].ok == "unknown"
    assert profile.portfolio == []


def test_factories_profile_overrides_by_dotted_path():
    profile = make_profile(
        {
            "company.size": "대기업",
            "registrations.sme_certificate.status": "valid",
            "registrations.sme_certificate.valid_until": "2027-03",
            "registrations.g2b.industry_codes": [],
            "people.headcount_by_grade.고급": 2,
            "people.onsite_capacity.서울.ok": True,
            "people.onsite_capacity.서울.max_people": 3,
        },
        direct_production=[direct_production("8111189901", status="valid", valid_until="2027-01")],
        portfolio=[
            portfolio_item(
                "P2024-03", amount_krw=300_000_000, completed=True, period_end="2025-06"
            ),
            portfolio_item("P2024-04", role="공동수급", share_pct=40),
        ],
    )
    assert profile.company.size == "대기업"
    assert profile.registrations.sme_certificate.valid_until == "2027-03"
    assert profile.registrations.g2b.industry_codes == []
    assert profile.people.headcount_by_grade["고급"] == 2
    assert profile.people.headcount_by_grade["중급"] == "unknown"
    assert profile.people.onsite_capacity["서울"].max_people == 3
    assert profile.registrations.direct_production[0].item_no == "8111189901"
    assert [p.id for p in profile.portfolio] == ["P2024-03", "P2024-04"]
    assert profile.portfolio[0].completed is True
    assert profile.portfolio[0].period.end == "2025-06"
    assert profile.portfolio[1].amount_krw == "unknown"
    assert profile.portfolio[1].share_pct == 40


def test_factories_profile_validates_values():
    with pytest.raises(ValidationError):
        make_profile({"company.size": "거대기업"})


def test_factories_profile_gt01_fields():
    profile = make_profile(
        {"registrations.insolvency": "none", "policy.default_bid_mode": "solo"},
        other_certs=[other_cert("ISMS"), other_cert("사회적기업", since="2020-03")],
    )
    assert profile.registrations.insolvency == "none"
    assert profile.policy.default_bid_mode == "solo"
    assert [c.name for c in profile.registrations.other_certs] == ["ISMS", "사회적기업"]
    assert profile.registrations.other_certs[0].valid_until == "unknown"
    assert profile.registrations.other_certs[1].since == "2020-03"
    # 안 쓰면 기본값(unknown / 빈 목록)
    default = make_profile()
    assert default.registrations.insolvency == "unknown"
    assert default.policy.default_bid_mode == "unknown"
    assert default.registrations.other_certs == []


# --- 게이트 공통 도우미 ---

AS_OF = date(2026, 11, 5)


def gate(r, profile=None, *, as_of=AS_OF):
    """eligibility 하나만 있는 공고(계약조건 파생 없음)를 평가해 결과 하나를 돌려준다."""
    results = evaluate_gates(
        make_facts(eligibility=[r]), profile if profile is not None else make_profile(), as_of=as_of
    )
    assert len(results) == 1
    return results[0]


def assert_unknown_hint(g, *fields):
    """UNKNOWN이고 unknown_fields가 주어진 경로이며 action이 첫 경로의 hint_for 문구."""
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == list(fields)
    assert g.action == "확인 필요: " + hint_for(fields[0])


def assert_fail(g):
    assert g.verdict == "FAIL"
    assert g.action == FAIL_ACTION


def assert_pass(g):
    assert g.verdict == "PASS"
    assert g.action is None


# --- T3: 규모(대기업·상호출자제한 제외) ---


@pytest.mark.parametrize("code", ["LARGE_CORP_EXCLUDED", "MUTUAL_INVEST_GROUP_EXCLUDED"])
@pytest.mark.parametrize(
    ("size", "verdict"),
    [
        ("중소기업", "PASS"),
        ("소상공인", "PASS"),
        ("대기업", "FAIL"),
        ("중견기업", "RISK"),
        ("unknown", "UNKNOWN"),
    ],
)
def test_t3_company_size(code, size, verdict):
    r = rule(code, "대기업 참여 제한")
    g = gate(r, make_profile({"company.size": size}))
    assert g.code == code
    assert g.verdict == verdict
    assert g.rule_text == "대기업 참여 제한"
    assert g.company_value == f"company.size={size}"
    assert g.evidence == [EVIDENCE]
    if verdict == "PASS":
        assert g.action is None and g.unknown_fields == []
    elif verdict == "FAIL":
        assert g.action == FAIL_ACTION and g.unknown_fields == []
    elif verdict == "UNKNOWN":
        assert_unknown_hint(g, "company.size")
    else:
        assert isinstance(g.action, str) and g.action
        assert g.action != FAIL_ACTION
        assert g.unknown_fields == []


# --- T4: 중소기업확인서 ---


def _sme(status, valid_until="unknown", classification="중기업"):
    return make_profile(
        {
            "registrations.sme_certificate.status": status,
            "registrations.sme_certificate.valid_until": valid_until,
            "registrations.sme_certificate.classification": classification,
        }
    )


@pytest.mark.parametrize("valid_until", ["2027-03", "2026-11", "2026-11-05", "2026-11-30"])
def test_t4_sme_valid_future_or_same_month_passes(valid_until):
    g = gate(rule("SME_CERT"), _sme("valid", valid_until))
    assert_pass(g)
    assert "registrations.sme_certificate.status=valid" in g.company_value
    assert f"registrations.sme_certificate.valid_until={valid_until}" in g.company_value


def test_t4_sme_month_end_boundary():
    # "2026-11"은 2026-11-30까지 유효
    assert_pass(gate(rule("SME_CERT"), _sme("valid", "2026-11"), as_of=date(2026, 11, 30)))
    g = gate(rule("SME_CERT"), _sme("valid", "2026-11"), as_of=date(2026, 12, 1))
    assert g.verdict == "FAIL" and g.action == "갱신 확인"


def test_t4_sme_valid_unknown_until_is_unknown():
    g = gate(rule("SME_CERT"), _sme("valid", "unknown"))
    assert_unknown_hint(g, "registrations.sme_certificate.valid_until")


@pytest.mark.parametrize("valid_until", ["2026-10", "2026-11-04", "2020-01-01"])
def test_t4_sme_valid_but_expired_date_fails_with_renewal_action(valid_until):
    g = gate(rule("SME_CERT"), _sme("valid", valid_until))
    assert g.verdict == "FAIL"
    assert g.action == "갱신 확인"
    assert g.unknown_fields == []


@pytest.mark.parametrize("status", ["expired", "none"])
def test_t4_sme_expired_or_none_fails(status):
    assert_fail(gate(rule("SME_CERT"), _sme(status, "2027-01")))


def test_t4_sme_status_unknown():
    g = gate(rule("SME_CERT"), _sme("unknown"))
    assert g.unknown_fields[0] == "registrations.sme_certificate.status"
    assert_unknown_hint(g, *g.unknown_fields)


def test_rev_t2_legacy_known_sme_values_are_not_promoted_to_confirmed():
    profile = _sme("valid", "2027-01", "소기업")
    g = gate(rule("SME_CERT", "소기업 확인서"), CompanyEvidenceView(profile))
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == ["registrations.sme_certificate.status"]
    assert g.input_fields == ["registrations.sme_certificate.status"]


def test_rev_t2_demo_expiry_and_unconfirmed_classification_stay_unknown():
    profile = _sme("valid", "2027-01", "소기업")
    view = confirmed_view(
        profile,
        [
            "registrations.sme_certificate.status",
            "registrations.sme_certificate.valid_until",
        ],
    )
    g = gate(rule("SME_CERT", "소기업 확인서"), view)
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == ["registrations.sme_certificate.classification"]
    assert g.input_fields == [
        "registrations.sme_certificate.status",
        "registrations.sme_certificate.valid_until",
        "registrations.sme_certificate.classification",
    ]


@pytest.mark.parametrize(
    ("text", "classification"),
    [
        ("소기업 확인서", "소기업"),
        ("소상공인 확인서", "소상공인"),
        ("소기업 또는 소상공인 확인서", "소기업"),
        ("소기업 또는 소상공인 확인서", "소상공인"),
        ("중소기업 확인서", "중기업"),
        ("중소기업 확인서", "소기업"),
        ("중소기업 확인서", "소상공인"),
        ("중·소기업자 중소기업확인서", "중기업"),
        ("중소기업 또는 소상공인 확인서", "중기업"),
        ("중소기업 또는 소기업 확인서", "중기업"),
        ("소상공인 또는 중소기업 확인서", "중기업"),
        ("중·소기업·소상공인 확인서", "중기업"),
    ],
)
def test_rev_t3_sme_allowed_classification_sets_pass(text, classification):
    assert_pass(gate(rule("SME_CERT", text), _sme("valid", "2027-01", classification)))


@pytest.mark.parametrize(
    ("text", "classification"),
    [
        ("소기업 확인서", "중기업"),
        ("소상공인 확인서", "소기업"),
        ("소기업 또는 소상공인 확인서", "중기업"),
    ],
)
def test_rev_t3_sme_clear_classification_mismatch_fails(text, classification):
    assert_fail(gate(rule("SME_CERT", text), _sme("valid", "2027-01", classification)))


def test_rev_t3_small_business_does_not_assume_microenterprise_inclusion():
    g = gate(rule("SME_CERT", "소기업 확인서"), _sme("valid", "2027-01", "소상공인"))
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == []


def test_rev_t3_generic_certificate_name_does_not_widen_explicit_small_requirement():
    g = gate(
        rule("SME_CERT", "중소기업 확인서를 소지한 소기업"),
        _sme("valid", "2027-01", "중기업"),
    )
    assert g.verdict == "FAIL"


def test_rev_t3_unparsed_sme_exception_is_unknown_without_company_inputs():
    g = gate(
        rule("SME_CERT", "소기업 확인서 소지 업체(단, 예외 대상 제외)"),
        CompanyEvidenceView(_sme("valid", "2027-01", "소기업")),
    )
    assert g.verdict == "UNKNOWN"
    assert g.input_fields == []


@pytest.mark.parametrize(
    "text",
    [
        "소기업에 해당하지 않는 업체",
        "소기업이 아니어도 참가 가능한 업체",
        "소기업을 제외한 업체",
        "소기업으로 인정하지 않는 업체",
        "소기업 비해당 업체",
        "중소기업 또는 소기업이 아닌 업체",
    ],
)
def test_rev_t3_unparsed_sme_negation_is_unknown_without_company_inputs(text):
    g = gate(rule("SME_CERT", text), _sme("valid", "2027-01", "소기업"))
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == []
    assert g.input_fields == []


# --- T5: 직접생산확인 ---

DP_REQ = ["8111159901", "8111229901"]
DP_PATH = "registrations.direct_production"


def test_t5_direct_production_one_valid_future_passes():
    profile = make_profile(
        direct_production=[
            direct_production("8111159901", status="unknown"),
            direct_production("8111229901", status="valid", valid_until="2027-01"),
        ]
    )
    g = gate(rule("DIRECT_PRODUCTION", item_no=DP_REQ), profile)
    assert_pass(g)
    assert f"{DP_PATH}[8111229901].status=valid" in g.company_value


def test_t5_direct_production_valid_unknown_until():
    profile = make_profile(
        direct_production=[
            direct_production("8111159901", status="valid", valid_until="unknown"),
            direct_production("8111229901", status="none"),
        ]
    )
    g = gate(rule("DIRECT_PRODUCTION", item_no=DP_REQ), profile)
    assert_unknown_hint(g, f"{DP_PATH}[8111159901].valid_until")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (("none", "unknown"), ("expired", "2027-01")),
        (("valid", "2026-10"), ("none", "unknown")),  # 유효기간 경과 확인 + 미보유
    ],
)
def test_t5_direct_production_all_confirmed_not_valid_fails(first, second):
    profile = make_profile(
        direct_production=[
            direct_production("8111159901", status=first[0], valid_until=first[1]),
            direct_production("8111229901", status=second[0], valid_until=second[1]),
        ]
    )
    assert_fail(gate(rule("DIRECT_PRODUCTION", item_no=DP_REQ), profile))


def test_t5_direct_production_missing_item_is_unknown_with_holding_action():
    profile = make_profile(direct_production=[direct_production("8111159901", status="none")])
    view = confirmed_view(profile, ["registrations.direct_production[8111159901].status"])
    g = gate(rule("DIRECT_PRODUCTION", item_no=DP_REQ), view)
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == ["registrations.direct_production"]
    assert g.input_fields == [
        "registrations.direct_production[8111159901].status",
        "registrations.direct_production",
    ]
    assert g.action == "확인 필요: " + hint_for("registrations.direct_production")


def test_t5_direct_production_no_profile_items_is_unknown():
    g = gate(rule("DIRECT_PRODUCTION", item_no=DP_REQ), CompanyEvidenceView(make_profile()))
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == ["registrations.direct_production"]
    assert g.input_fields == ["registrations.direct_production"]
    assert g.action == "확인 필요: " + hint_for("registrations.direct_production")


@pytest.mark.parametrize("item_no", [None, []])
def test_t5_direct_production_item_no_missing(item_no):
    profile = make_profile(
        direct_production=[direct_production("8111159901", status="valid", valid_until="2027-01")]
    )
    g = gate(rule("DIRECT_PRODUCTION", item_no=item_no), profile)
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == []
    assert g.action == "원문 확인: 세부품명번호 미추출"


def test_t5_direct_production_compares_digits_only():
    profile = make_profile(
        direct_production=[direct_production("8111189901", status="valid", valid_until="2027-01")]
    )
    assert_pass(gate(rule("DIRECT_PRODUCTION", item_no=["811-118-9901"]), profile))
    profile = make_profile(direct_production=[direct_production("811-118-9901", status="valid")])
    g = gate(rule("DIRECT_PRODUCTION", item_no=["8111189901"]), profile)
    # 경로의 식별 키는 프로필 항목 값 그대로
    assert_unknown_hint(g, f"{DP_PATH}[811-118-9901].valid_until")


def test_t5_direct_production_mofa_unknown_status():
    profile = make_profile(direct_production=[direct_production("8111189901")])
    g = gate(rule("DIRECT_PRODUCTION", item_no=["8111189901"]), profile)
    assert_unknown_hint(g, f"{DP_PATH}[8111189901].status")


def test_t5_direct_production_unknown_beats_fail_when_one_is_unknown():
    profile = make_profile(
        direct_production=[
            direct_production("8111159901", status="none"),
            direct_production("8111229901", status="unknown"),
        ]
    )
    g = gate(rule("DIRECT_PRODUCTION", item_no=DP_REQ), profile)
    assert_unknown_hint(g, f"{DP_PATH}[8111229901].status")


# --- T6: 조달등록·업종코드 ---


@pytest.mark.parametrize(
    ("registered", "verdict"), [(True, "PASS"), (False, "FAIL"), ("unknown", "UNKNOWN")]
)
def test_t6_g2b_registered(registered, verdict):
    g = gate(rule("G2B_REGISTERED"), make_profile({"registrations.g2b.registered": registered}))
    assert g.verdict == verdict
    if verdict == "PASS":
        assert_pass(g)
        assert g.company_value == "registrations.g2b.registered=true"
    elif verdict == "FAIL":
        assert_fail(g)
        assert g.company_value == "registrations.g2b.registered=false"
    else:
        assert_unknown_hint(g, "registrations.g2b.registered")


def _codes(industry, other):
    return make_profile(
        {"registrations.g2b.industry_codes": industry, "registrations.g2b.other_codes": other}
    )


def test_t6_industry_code_held_passes():
    assert_pass(gate(rule("INDUSTRY_CODE", industry_code=["1468"]), _codes(["1468"], "unknown")))
    # other_codes에만 있어도 PASS
    assert_pass(gate(rule("INDUSTRY_CODE", industry_code=["1468"]), _codes("unknown", ["1468"])))


def test_t6_industry_code_confirmed_absent_fails():
    g = gate(rule("INDUSTRY_CODE", industry_code=["1468"]), _codes(["1234"], []))
    assert_fail(g)
    assert "registrations.g2b.industry_codes=[1234]" in g.company_value
    assert "registrations.g2b.other_codes=[]" in g.company_value


def test_t6_industry_code_empty_lists_are_confirmed_absence():
    assert_fail(gate(rule("INDUSTRY_CODE", industry_code=["1468"]), _codes([], [])))


def test_t6_industry_code_other_unknown():
    g = gate(rule("INDUSTRY_CODE", industry_code=["1468"]), _codes(["1234"], "unknown"))
    assert_unknown_hint(g, "registrations.g2b.other_codes")


def test_t6_industry_code_all_unknown():
    g = gate(rule("INDUSTRY_CODE", industry_code=["1468"]), make_profile())
    assert_unknown_hint(g, "registrations.g2b.industry_codes", "registrations.g2b.other_codes")


@pytest.mark.parametrize("codes", [None, []])
def test_t6_industry_code_params_missing(codes):
    g = gate(rule("INDUSTRY_CODE", industry_code=codes), _codes(["1468"], []))
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == []
    assert g.action == "원문 확인"


# --- T7: SW사업자 신고 ---


def _sw(reported, latest_year="unknown"):
    return make_profile(
        {
            "registrations.sw_business_report.reported": reported,
            "registrations.sw_business_report.latest_year": latest_year,
        }
    )


@pytest.mark.parametrize("year", [AS_OF.year - 1, AS_OF.year])
def test_t7_sw_report_recent_passes(year):
    g = gate(rule("SW_BUSINESS_REPORT"), _sw(True, year))
    assert_pass(g)
    assert f"registrations.sw_business_report.latest_year={year}" in g.company_value


def test_t7_sw_report_old_year_is_unknown_with_year_action():
    g = gate(rule("SW_BUSINESS_REPORT"), _sw(True, AS_OF.year - 3))
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == []
    assert g.action == "신고 연도 확인"


def test_t7_sw_report_year_unknown():
    g = gate(rule("SW_BUSINESS_REPORT"), _sw(True, "unknown"))
    assert_unknown_hint(g, "registrations.sw_business_report.latest_year")


def test_t7_sw_report_false_fails():
    assert_fail(gate(rule("SW_BUSINESS_REPORT"), _sw(False, 2025)))


def test_t7_sw_report_unknown():
    g = gate(rule("SW_BUSINESS_REPORT"), _sw("unknown", 2025))
    assert_unknown_hint(g, "registrations.sw_business_report.reported")


# --- T8: 지역제한, normalize_region ---


@pytest.mark.parametrize(
    ("region", "verdict"),
    [
        (["대구광역시"], "PASS"),
        (["서울특별시", "경기도"], "FAIL"),
        (["대구·경북"], "PASS"),
        (["대구광역시 소재 업체"], "PASS"),
        (["경상북도", "대구광역시"], "PASS"),
    ],
)
def test_t8_region_limit(region, verdict):
    g = gate(rule("REGION_LIMIT", region=region), make_profile({"company.region": "대구"}))
    assert g.verdict == verdict
    assert g.company_value == "company.region=대구"
    if verdict == "FAIL":
        assert_fail(g)
    else:
        assert_pass(g)


def test_t8_region_limit_company_variant_name():
    profile = make_profile({"company.region": "대구광역시"})
    assert_pass(gate(rule("REGION_LIMIT", region=["대구"]), profile))


def test_t8_region_limit_company_region_unknown():
    g = gate(rule("REGION_LIMIT", region=["대구광역시"]), make_profile())
    assert_unknown_hint(g, "company.region")


@pytest.mark.parametrize("region", [None, []])
def test_t8_region_limit_params_missing(region):
    g = gate(rule("REGION_LIMIT", region=region), make_profile({"company.region": "대구"}))
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == []
    assert g.action == "원문 확인"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("경상북도 및 대구광역시", ["경북", "대구"]),
        ("외교부 청사(서울)", ["서울"]),
        ("경기도 광주시", ["경기"]),  # 최장 일치 동률 → 첫 등장
        ("광주광역시", ["광주"]),
        ("대구광역시 소재", ["대구"]),
        ("서울 외교부 청사", ["서울"]),
        ("대구·경북", ["대구", "경북"]),
        ("대구, 대구광역시", ["대구"]),  # 중복 제거
        ("부산/울산ㆍ경남 또는 제주특별자치도", ["부산", "울산", "경남", "제주"]),
        ("강원특별자치도", ["강원"]),
        ("전라북도", ["전북"]),
        ("발주기관 지정 장소", ["발주기관지정장소"]),  # 변형 없음 → 토큰 유지(공백 제거)
        ("", []),
    ],
)
def test_t8_normalize_region(text, expected):
    assert normalize_region(text) == expected


def test_t8_normalize_region_nfc():
    assert normalize_region(unicodedata.normalize("NFD", "서울특별시")) == ["서울"]


# --- T9: 부정당·체납 ---


@pytest.mark.parametrize(("value", "verdict"), [("none", "PASS"), ("active", "FAIL")])
def test_t9_debarment_pass_fail(value, verdict):
    g = gate(rule("DEBARMENT"), make_profile({"registrations.debarment": value}))
    assert g.verdict == verdict
    assert g.company_value == f"registrations.debarment={value}"
    if verdict == "PASS":
        assert_pass(g)
    else:
        assert_fail(g)


def test_t9_debarment_none_known_is_risk():
    g = gate(rule("DEBARMENT"), make_profile({"registrations.debarment": "none_known"}))
    assert g.verdict == "RISK"
    assert g.action == "부정당업자 제재 여부 조회 확인"
    assert g.unknown_fields == []


@pytest.mark.parametrize(
    ("value", "verdict"), [("none", "PASS"), ("exists", "FAIL"), ("unknown", "UNKNOWN")]
)
def test_t9_tax_delinquency(value, verdict):
    g = gate(rule("TAX_DELINQUENCY"), make_profile({"registrations.tax_delinquency": value}))
    assert g.verdict == verdict
    if verdict == "PASS":
        assert_pass(g)
    elif verdict == "FAIL":
        assert_fail(g)
    else:
        assert_unknown_hint(g, "registrations.tax_delinquency")


# --- T11: 필수 인증, 기타 ---

CERT_PROFILE = {
    "registrations.iso": [{"std": "9001"}, {"std": "27001"}],
    "registrations.venture": {"type": "혁신성장유형"},
    "registrations.rnd_institute": {"type": "기업부설연구소"},
    "registrations.cloud_certs": [{"name": "CSAP"}],
    "registrations.esg_cert": {"has": True},
}


@pytest.mark.parametrize(
    "cert_name",
    [
        "ISO 9001",
        "ISO9001 인증",
        "iso 27001",
        "벤처기업확인서",
        "기업부설연구소",
        "CSAP 인증",
        "ESG",
    ],
)
def test_t11_required_cert_held_passes(cert_name):
    g = gate(rule("REQUIRED_CERT", cert_name=cert_name), make_profile(CERT_PROFILE))
    assert_pass(g)
    assert "ISO 9001" in g.company_value


def test_t11_required_cert_gs_unknown_is_unknown_not_fail():
    g = gate(rule("REQUIRED_CERT", cert_name="GS인증"), make_profile(CERT_PROFILE))
    assert g.verdict == "UNKNOWN"
    assert "registrations.gs_cert" in g.unknown_fields
    assert g.action.startswith("확인 필요: ")


def test_t11_required_cert_gs_list():
    held = make_profile({"registrations.gs_cert": ["바로웹 v2"]})
    assert_pass(gate(rule("REQUIRED_CERT", cert_name="GS인증 1등급"), held))
    assert_pass(gate(rule("REQUIRED_CERT", cert_name="바로웹 V2"), held))
    # 빈 리스트(확인된 미보유)여도 보유 목록이 완전하지 않으므로 FAIL로 단정하지 않는다
    none_held = make_profile({"registrations.gs_cert": []})
    g = gate(rule("REQUIRED_CERT", cert_name="GS인증"), none_held)
    assert g.verdict == "UNKNOWN" and g.action.startswith("확인 필요: ")


def test_t11_required_cert_unknown_values_are_not_names():
    # rnd_institute.type이 unknown이면 이름 목록에 "unknown"을 넣지 않는다
    profile = make_profile({"registrations.rnd_institute": {"since": "2023-02"}})
    g = gate(rule("REQUIRED_CERT", cert_name="unknown"), profile)
    assert g.verdict == "UNKNOWN"


@pytest.mark.parametrize("cert_name", [None, "", "  "])
def test_t11_required_cert_name_missing(cert_name):
    g = gate(rule("REQUIRED_CERT", cert_name=cert_name), make_profile(CERT_PROFILE))
    assert g.verdict == "UNKNOWN"
    assert g.action == "원문 확인"


def test_t11_unreclassified_other_is_unknown():
    """재분류 패턴에 맞지 않는 OTHER는 UNKNOWN(원문 확인) — 재분류는 `test_gt_*`가 검증한다."""
    g = gate(rule("OTHER", "기타 자격"), make_profile(CERT_PROFILE))
    assert g.verdict == "UNKNOWN"
    assert g.action == "원문 확인"
    assert g.unknown_fields == []
    assert g.company_value == "-"
    assert g.rule_text == "기타 자격"


# --- T10: 실적 게이트(창업기업 특례 창) ---

NON_STARTUP = "2015-01"  # as_of 2026-11-05 기준 창업 7년 경과
STARTUP = "2022-09"


def done(pid, end, amount="unknown", *, role="주사업자", **kw):
    """완료(completed True) 실적 항목."""
    return portfolio_item(pid, period_end=end, amount_krw=amount, role=role, completed=True, **kw)


def perf(portfolio, *, founded=NON_STARTUP, as_of=AS_OF, **params):
    values = {} if founded is None else {"company.founded": founded}
    profile = make_profile(values, portfolio=portfolio)
    return gate(rule("PAST_PERFORMANCE", "유사 실적", **params), profile, as_of=as_of)


def test_t10a_non_startup_window_excludes_older_than_years():
    g = perf([done("P2022-01", "2022-10", 100)], years=3)  # 4년 전 종료 → 창 밖
    assert_fail(g)
    assert "확정후보=0" in g.company_value
    g = perf([done("P2024-01", "2024-06", 100)], years=3)
    assert_pass(g)
    assert g.company_value == (
        "창=2023-11-05~2026-11-05; 창업특례=아니오; 확정후보=1; 금액확인합계=100; "
        "금액미확인=0; 불확실=0"
    )


def test_t10a_window_boundaries():
    # 창 시작 2023-11-05: "2023-11"은 말일(11-30)로 창 안, "2023-10"은 창 밖
    assert "확정후보=1" in perf([done("P2023-01", "2023-11")], years=3).company_value
    assert "확정후보=0" in perf([done("P2023-01", "2023-10")], years=3).company_value
    # as_of 이후 종료는 창 밖
    assert "확정후보=0" in perf([done("P2026-01", "2026-12")], years=3).company_value
    assert "확정후보=1" in perf([done("P2026-01", "2026-11-05")], years=3).company_value


def test_t10b_startup_window_starts_at_founding():
    g = perf([done("P2023-01", "2023-01", 100)], founded=STARTUP, years=3)
    assert_pass(g)
    assert g.company_value.startswith("창=2022-09-01~2026-11-05; 창업특례=예; 확정후보=1")
    # 창업일 이전 종료는 창 밖
    g = perf([done("P2022-01", "2022-08", 100)], founded=STARTUP, years=3)
    assert "확정후보=0" in g.company_value


def test_t10_no_years_means_no_lower_bound():
    g = perf([done("P2010-01", "2010-03", 100)])
    assert_pass(g)
    assert g.company_value.startswith("창=-~2026-11-05; 창업특례=아니오; 확정후보=1")


def test_t10_founded_unknown_is_non_startup_and_recorded():
    g = perf([done("P2022-01", "2022-10", 100)], founded=None, years=3)
    assert "창=2023-11-05~2026-11-05; 창업특례=미상; 확정후보=0" in g.company_value
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == ["company.founded"]
    assert g.action == "확인 필요: " + hint_for("company.founded")


def test_t10c_keyword_filters_title_or_domain():
    items = [
        done("P2024-01", "2024-06", 100, title="OO기관 홈페이지 구축"),
        done("P2024-02", "2024-06", 200, title="ERP 고도화", domain=["홈 페이지", "웹"]),
        done("P2024-03", "2024-06", 400, title="ERP 구축", domain=["ERP"]),
    ]
    g = perf(items, keyword="홈페이지", amount_krw=300)
    assert_pass(g)
    assert "확정후보=2; 금액확인합계=300;" in g.company_value
    g = perf(items, keyword="홈 페이지", amount_krw=301)
    assert_fail(g)


def test_t10d_known_sum_reaches_amount_passes():
    items = [done("P2024-01", "2024-06", 300), done("P2025-01", "2025-06", 250)]
    g = perf(items, years=3, amount_krw=500)
    assert_pass(g)
    assert "확정후보=2; 금액확인합계=550; 금액미확인=0; 불확실=0" in g.company_value


def test_t10e_unknown_amount_with_short_known_sum_is_unknown():
    items = [done("P2024-01", "2024-06", 300), done("P2024-02", "2024-07", "unknown")]
    g = perf(items, years=3, amount_krw=500)
    assert_unknown_hint(g, "portfolio[P2024-02].amount_krw")
    assert "확정후보=2; 금액확인합계=300; 금액미확인=1; 불확실=0" in g.company_value


def test_t10f_all_known_short_sum_fails():
    items = [done("P2024-01", "2024-06", 300), done("P2024-02", "2024-07", 100)]
    assert_fail(perf(items, years=3, amount_krw=500))


def test_t10g_no_amount_one_confirmed_passes():
    g = perf([done("P2024-01", "2024-06", "unknown")], years=3)
    assert_pass(g)
    # 금액 요건이 없으면 금액은 판정에 쓰지 않으므로 금액 경로를 남기지 않는다
    assert g.unknown_fields == []


def test_t10h_no_amount_confirmed_empty_portfolio_fails():
    g = perf([], years=3)
    assert_fail(g)
    assert g.input_fields == ["company.founded", "portfolio"]


def test_t10i_amount_and_confirmed_zero_candidates_fails():
    g = perf([done("P2010-01", "2010-03", 900)], years=3, amount_krw=100)
    assert_fail(g)


def test_rev_amount_zero_candidates_with_unconfirmed_portfolio_stays_unknown():
    item = done("P2010-01", "2010-03", 900)
    profile = make_profile({"company.founded": NON_STARTUP}, portfolio=[item])
    view = confirmed_view(
        profile,
        [
            "company.founded",
            "portfolio[P2010-01].completed",
            "portfolio[P2010-01].period.end",
        ],
    )
    g = gate(
        rule("PAST_PERFORMANCE", "유사 실적", years=3, amount_krw=100),
        view,
    )
    assert_unknown_hint(g, "portfolio")


def test_t10j_completed_unknown_is_uncertain():
    item = portfolio_item("P2024-01", period_end="2024-06", amount_krw=100, role="주사업자")
    g = perf([item], years=3)
    assert_unknown_hint(g, "portfolio[P2024-01].completed")
    assert "확정후보=0; 금액확인합계=0; 금액미확인=0; 불확실=1" in g.company_value
    g = perf([done("P2024-02", "2024-06", 100), item], years=3, amount_krw=500)
    assert_unknown_hint(g, "portfolio[P2024-01].completed")


def test_t10j_completed_true_end_unknown_is_uncertain():
    g = perf([done("P2024-01", "unknown", 100)], years=3)
    assert_unknown_hint(g, "portfolio[P2024-01].period.end")
    assert "불확실=1" in g.company_value


def test_t10j_completed_false_is_excluded():
    item = portfolio_item("P2024-01", period_end="2024-06", amount_krw=100, completed=False)
    g = perf([item], years=3)
    assert_fail(g)
    assert "확정후보=0" in g.company_value and "불확실=0" in g.company_value


def test_t10k_role_unknown_amount_is_unconfirmed():
    items = [
        done("P2024-01", "2024-06", 300),
        done("P2024-02", "2024-07", 400, role="unknown"),
    ]
    g = perf(items, years=3, amount_krw=500)
    assert_unknown_hint(g, "portfolio[P2024-02].role")
    assert "금액확인합계=300; 금액미확인=1" in g.company_value


@pytest.mark.parametrize(("amount", "verdict"), [(400, "PASS"), (401, "FAIL")])
def test_t10l_consortium_share(amount, verdict):
    item = done("P2024-01", "2024-06", 1000, role="공동수급", share_pct=40)
    g = perf([item], years=3, amount_krw=amount)
    assert g.verdict == verdict
    assert "금액확인합계=400;" in g.company_value


def test_t10l_consortium_share_unknown():
    item = done("P2024-01", "2024-06", 1000, role="공동수급")
    g = perf([item], years=3, amount_krw=100)
    assert_unknown_hint(g, "portfolio[P2024-01].share_pct")


def test_t10_subcontract_role_counts_full_amount():
    g = perf([done("P2024-01", "2024-06", 500, role="하도급")], years=3, amount_krw=500)
    assert_pass(g)


# --- T2(접미): 기준일 표기 ---

DATE_CODES = ["SME_CERT", "DIRECT_PRODUCTION", "SW_BUSINESS_REPORT", "PAST_PERFORMANCE"]


def _texts(facts, as_of):
    return [g.rule_text for g in evaluate_gates(facts, make_profile(), as_of=as_of)]


def test_t2_sme_rule_text_has_deadline_suffix():
    facts = make_facts(
        submission_deadline="2026-11-05 10:00",
        notice_date="2026-10-15",
        eligibility=[rule("SME_CERT", "중소기업확인서 제출")],
    )
    as_of, _ = resolve_as_of(facts)
    [gate_result] = evaluate_gates(facts, make_profile(), as_of=as_of)
    assert gate_result.rule_text == "중소기업확인서 제출 [기준일 2026-11-05 제출마감]"
    assert gate_result.rule_hash == eligibility_rule_hash("중소기업확인서 제출")


def test_t2_suffix_source_notice_and_run_date():
    eligibility = [rule("SME_CERT", "확인서")]
    facts = make_facts(notice_date="2026-10-15", eligibility=eligibility)
    as_of, _ = resolve_as_of(facts)
    assert _texts(facts, as_of) == ["확인서 [기준일 2026-10-15 공고일]"]
    facts = make_facts(submission_deadline="미정", eligibility=eligibility)
    as_of, _ = resolve_as_of(facts, date(2026, 10, 22))
    assert _texts(facts, as_of) == ["확인서 [기준일 2026-10-22 실행일]"]
    # as_of가 마감일·공고일 어느 것과도 다르면 실행일
    facts = make_facts(
        submission_deadline="2026-11-05", notice_date="2026-10-15", eligibility=eligibility
    )
    assert _texts(facts, date(2026, 10, 22)) == ["확인서 [기준일 2026-10-22 실행일]"]


def test_t2_suffix_only_on_date_gates():
    codes = [*DATE_CODES, "G2B_REGISTERED", "LARGE_CORP_EXCLUDED", "OTHER", "REQUIRED_CERT"]
    facts = make_facts(
        submission_deadline="2026-11-05", eligibility=[rule(c, f"규칙 {c}") for c in codes]
    )
    texts = _texts(facts, date(2026, 11, 5))
    suffix = " [기준일 2026-11-05 제출마감]"
    assert texts == [f"규칙 {c}" + (suffix if c in DATE_CODES else "") for c in codes]


# --- T12: STAFFING_CAPACITY ---


def derived(facts, profile=None, code="STAFFING_CAPACITY"):
    results = evaluate_gates(facts, profile if profile is not None else make_profile(), as_of=AS_OF)
    return [g for g in results if g.code == code]


def closed(staff=(), **kw):
    """공동수급·하도급 모두 불허 공고."""
    return make_facts(
        staffing=list(staff), consortium_allowed=False, subcontract_allowed=False, **kw
    )


RESIDENT_3 = [
    staffing("PM", grade="고급", count=1, resident=True, location="외교부 청사(서울)"),
    staffing("PG", grade="중급", count=1, resident=True, location="외교부 청사(서울)"),
    staffing("디자이너", count=1, resident=True, location="외교부 청사(서울)"),
]


def test_t12a_closed_with_unknown_headcount_is_risk():
    [g] = derived(closed(RESIDENT_3))
    assert g.verdict == "RISK"
    assert g.rule_text == "공동수급·하도급 불허 + 요구 인력 3명(자사 인력만으로 충족 필요)"
    assert g.unknown_fields == [
        "people.total_tech_staff",
        f"people.headcount_by_grade.{encode_path_token('고급')}",
        f"people.headcount_by_grade.{encode_path_token('중급')}",
    ]
    assert g.action == "자사 인력 투입 가능 여부 확인"
    assert g.company_value == (
        "total_tech_staff=unknown; headcount_by_grade.고급=unknown; headcount_by_grade.중급=unknown"
    )


@pytest.mark.parametrize(
    ("consortium", "subcontract"), [(True, False), (False, True), (False, None), (None, False)]
)
def test_t12bc_not_generated_unless_both_disallowed(consortium, subcontract):
    facts = make_facts(
        staffing=RESIDENT_3, consortium_allowed=consortium, subcontract_allowed=subcontract
    )
    assert derived(facts) == []


def test_t12d_no_staffing_is_risk():
    [g] = derived(closed(), make_profile({"people.total_tech_staff": 10}))
    assert g.verdict == "RISK"
    assert g.rule_text == "공동수급·하도급 불허(인력 요건 미추출, 자사 단독 수행 필요)"
    assert g.action == "자사 인력 투입 가능 여부 확인"


def test_t12e_non_resident_staffing_counts():
    staff = [staffing("개발자", count=2, resident=False)]
    results = evaluate_gates(
        closed(staff), make_profile({"people.total_tech_staff": 10}), as_of=AS_OF
    )
    assert [g.code for g in results] == ["STAFFING_CAPACITY"]  # 상주 없음 → ONSITE 없음
    g = results[0]
    assert_pass(g)
    assert "요구 인력 2명" in g.rule_text
    assert g.unknown_fields == []


def test_t12f_enough_staff_and_grade_passes():
    staff = [staffing("PM", grade="고급", count=2), staffing("PG", count=3)]
    profile = make_profile({"people.total_tech_staff": 10, "people.headcount_by_grade.고급": 2})
    [g] = derived(closed(staff), profile)
    assert_pass(g)
    assert g.company_value == "total_tech_staff=10; headcount_by_grade.고급=2"
    assert g.rule_hash == rule_payload_hash(staffing_capacity_rule_payload(closed(staff)))


def test_t12g_short_total_is_risk():
    staff = [staffing("PG", count=3)]
    [g] = derived(closed(staff), make_profile({"people.total_tech_staff": 2}))
    assert g.verdict == "RISK"
    assert g.unknown_fields == []


def test_t12_short_grade_is_risk():
    staff = [staffing("PM", grade="고급", count=2)]
    profile = make_profile({"people.total_tech_staff": 10, "people.headcount_by_grade.고급": 1})
    [g] = derived(closed(staff), profile)
    assert g.verdict == "RISK"


def test_t12h_count_none_assumes_per_role_count():
    # 설계 2026-10-25-gate-staffing-consortium 2.1: 인원 미상 직무는
    # STAFFING_UNKNOWN_COUNT_ASSUMED(3)명으로 가정한다. 2 + 3 = 5명
    staff = [staffing("PM", count=2), staffing("PG")]
    [g] = derived(closed(staff), make_profile({"people.total_tech_staff": 10}))
    assert g.verdict == "PASS"
    assert "요구 인력 3명 이상(인원 미상 포함)" in g.rule_text
    assert g.company_value.endswith("; 인원 미상 직무 가정=3명씩(합계 5명)")
    [short] = derived(closed(staff), make_profile({"people.total_tech_staff": 4}))
    assert short.verdict == "RISK"
    assert short.unknown_fields == []


def test_t12h_count_none_unknown_staff_is_risk():
    staff = [staffing("PG")]
    [g] = derived(closed(staff), make_profile({}))
    assert g.verdict == "RISK"
    assert g.unknown_fields == ["people.total_tech_staff"]


def test_t12i_no_evidence_source_gives_empty_list():
    [g] = derived(closed())
    assert g.evidence == []


def test_t12_evidence_dedup_keeps_order():
    other = make_evidence("공동수급 불허", "S010")
    third = make_evidence("하도급 불허", "S011")
    staff = [staffing("PM", count=1), staffing("PG", count=1, evidence=other)]
    [g] = derived(closed(staff, contract_evidence=[other, EVIDENCE, third]))
    assert g.evidence == [EVIDENCE, other, third]


# --- T13: ONSITE_LOCATION ---


def onsite(staff, values=None):
    return derived(make_facts(staffing=staff), make_profile(values), code="ONSITE_LOCATION")


@pytest.mark.parametrize("location", ["서울 외교부 청사", "외교부 청사(서울)"])
def test_t13_seoul_unknown_capacity_is_risk(location):
    requirement = staffing("PM", count=1, resident=True, location=location)
    [g] = onsite([requirement])
    assert g.verdict == "RISK"
    assert g.rule_text == f"PM 1명 상주: {location}"
    assert g.unknown_fields == [
        f"people.onsite_capacity.{encode_path_token('서울')}.ok",
        f"people.onsite_capacity.{encode_path_token('서울')}.max_people",
    ]
    assert g.company_value == (
        "onsite_capacity.서울.ok=unknown; max_people=unknown; policy.seoul_resident_ok=unknown"
    )
    assert g.action == "서울 상주 가능 인원 확인"
    assert g.evidence == [EVIDENCE]
    assert g.rule_hash == rule_payload_hash(onsite_location_rule_payload(requirement))


def test_t13_daegu_capacity_enough_passes():
    values = {"people.onsite_capacity.대구.ok": True, "people.onsite_capacity.대구.max_people": 5}
    [g] = onsite([staffing("PM", count=2, resident=True, location="대구광역시 청사")], values)
    assert_pass(g)
    assert g.unknown_fields == []


def test_t13_capacity_short_is_risk():
    values = {"people.onsite_capacity.대구.ok": True, "people.onsite_capacity.대구.max_people": 1}
    [g] = onsite([staffing("PM", count=2, resident=True, location="대구")], values)
    assert g.verdict == "RISK"
    assert g.unknown_fields == []


def test_t13_ok_true_max_unknown_is_risk():
    [g] = onsite(
        [staffing("PM", count=1, resident=True, location="대구")],
        {"people.onsite_capacity.대구.ok": True},
    )
    assert g.verdict == "RISK"
    assert g.unknown_fields == [f"people.onsite_capacity.{encode_path_token('대구')}.max_people"]


def test_t13_ok_false_is_risk():
    [g] = onsite(
        [staffing("PM", count=1, resident=True, location="서울")],
        {"people.onsite_capacity.서울.ok": False, "policy.seoul_resident_ok": False},
    )
    assert g.verdict == "RISK"
    assert g.unknown_fields == []
    assert "policy.seoul_resident_ok=false" in g.company_value


def test_t13_count_none_is_risk():
    values = {"people.onsite_capacity.서울.ok": True, "people.onsite_capacity.서울.max_people": 9}
    [g] = onsite([staffing("PM", resident=True, location="서울")], values)
    assert g.verdict == "RISK"
    assert g.rule_text == "PM 인원 미상 상주: 서울"


@pytest.mark.parametrize("location", [None, "발주기관 지정 장소", "강원도 춘천시"])
def test_t13_other_location_maps_to_etc_and_never_passes(location):
    values = {"people.onsite_capacity.기타.ok": True}
    [g] = onsite([staffing("PM", count=1, resident=True, location=location)], values)
    assert g.verdict == "RISK"
    assert g.action == "기타 상주 가능 인원 확인"
    assert g.company_value.startswith("onsite_capacity.기타.ok=true; max_people=-;")
    if location is None:
        assert g.rule_text == "PM 1명 상주: 장소 미상"


def test_t13_first_onsite_key_wins():
    [g] = onsite([staffing("PM", count=1, resident=True, location="경상북도 구미시")])
    assert g.action == "경북 상주 가능 인원 확인"
    [g] = onsite([staffing("PM", count=1, resident=True, location="대구·경북")])
    assert g.action == "대구 상주 가능 인원 확인"


@pytest.mark.parametrize("resident", [False, None])
def test_t13_non_resident_not_generated(resident):
    assert onsite([staffing("PM", count=1, resident=resident, location="서울")]) == []


def test_t13_one_gate_per_resident_staffing():
    gates = onsite(RESIDENT_3)
    assert len(gates) == 3
    assert [g.rule_text.split(" ")[0] for g in gates] == ["PM", "PG", "디자이너"]


# --- T14: evaluate_gates 조합 ---


def _combo_facts():
    sec = make_evidence("상주 요건", "S020")
    return make_facts(
        submission_deadline="2026-11-05",
        eligibility=[
            rule("OTHER", "기타"),
            rule("G2B_REGISTERED", "조달등록"),
            rule("SME_CERT", "중소기업확인서"),
        ],
        staffing=[
            staffing("PM", count=1, resident=True, location="서울", evidence=sec),
            staffing("PG", count=2, resident=False),
            staffing("디자이너", count=1, resident=True, location="대구"),
        ],
        consortium_allowed=False,
        subcontract_allowed=False,
        contract_evidence=[EVIDENCE],
    )


def test_t14_order_eligibility_then_staffing_then_onsite():
    results = evaluate_gates(_combo_facts(), make_profile(), as_of=AS_OF)
    assert [g.code for g in results] == [
        "OTHER",
        "G2B_REGISTERED",
        "SME_CERT",
        "STAFFING_CAPACITY",
        "ONSITE_LOCATION",
        "ONSITE_LOCATION",
    ]
    assert results[4].action == "서울 상주 가능 인원 확인"
    assert results[5].action == "대구 상주 가능 인원 확인"


def test_t14_evidence_is_copied():
    facts = _combo_facts()
    results = evaluate_gates(facts, make_profile(), as_of=AS_OF)
    assert results[0].evidence == [facts.eligibility[0].evidence]
    assert results[0].evidence[0] is not facts.eligibility[0].evidence
    assert results[3].evidence == [facts.staffing[0].evidence, EVIDENCE]  # 중복 제거
    assert results[3].evidence[0] is not facts.staffing[0].evidence
    assert results[4].evidence == [facts.staffing[0].evidence]
    results[4].evidence[0].quote = "변경"
    assert facts.staffing[0].evidence.quote == "상주 요건"


def test_t14_pass_has_no_action_and_others_have_action():
    profile = make_profile(
        {
            "registrations.g2b.registered": True,
            "registrations.sme_certificate.status": "valid",
            "registrations.sme_certificate.valid_until": "2027-01",
            "registrations.sme_certificate.classification": "중기업",
        }
    )
    results = evaluate_gates(_combo_facts(), profile, as_of=AS_OF)
    for g in results:
        if g.verdict == "PASS":
            assert g.action is None
        else:
            assert isinstance(g.action, str) and g.action
    assert [g.verdict for g in results[:3]] == ["UNKNOWN", "PASS", "PASS"]


def test_t14_deterministic_and_input_unchanged():
    facts = _combo_facts()
    profile = make_profile()
    before = (facts.model_dump(), profile.model_dump())
    first = evaluate_gates(facts, profile, as_of=AS_OF)
    second = evaluate_gates(facts, profile, as_of=AS_OF)
    assert [g.model_dump() for g in first] == [g.model_dump() for g in second]
    assert (facts.model_dump(), profile.model_dump()) == before


_FORBIDDEN_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+(?:anthropic|httpx)\b", re.MULTILINE)


@pytest.mark.parametrize("module_file", ["gates.py", "scoring.py"])
def test_t14_no_llm_or_network_imports(module_file):
    path = Path(gates_module.__file__).with_name(module_file)
    if not path.exists():
        pytest.skip(f"{module_file} 없음(다른 단계에서 생성)")
    source = path.read_text(encoding="utf-8")
    assert _FORBIDDEN_IMPORT_RE.search(source) is None
    assert "anthropic" not in source and "httpx" not in source


# --- GT-01: OTHER 재분류(spec GT-01 T2·T3) ---

# 실제 공고(out/<slug>/analysis.json facts)의 OTHER 조항 문구 그대로.
KNU_TEXT = (
    "｢소프트웨어 진흥법｣ 제48조(중소 소프트웨어사업자의 사업참여 지원)에 따른 "
    "｢중소 소프트웨어사업자의 사업 참여 지원에 관한 지침｣ 준수"
)
MOFA_TEXT = (
    "국가를 당사자로 하는 계약에 관한 법률 시행령」 제12조(경쟁입찰의 참가자격) 및 동법 "
    "시행규칙 제14조(입찰참가자격요건의 증명) 규정에 의한 경쟁입찰 참가자격을 갖추어야 하며"
)
NAMYANGJU_TEXT = (
    "공동수급은 공동이행방식을 원칙으로 하며, 공동수급체 구성원 모두가 본 입찰에서 요구하는 "
    "입찰참가자격을 갖추어야 함."
)
DONGMIN_CHATBOT_TEXT = "AI 챗봇(생성형 AI 기반 포함) 구축 실적 또는 구축 역량을 보유한 업체"
DONGMIN_INSOLVENCY_TEXT = "부도·파산·회생절차 중에 있지 아니한 업체"


def test_gt_norm_compact_is_public_and_replaces_private_name():
    assert norm_compact("  홈페이지 \t 구축\n") == "홈페이지구축"
    nfd = unicodedata.normalize("NFD", "챗 봇")
    assert norm_compact(nfd) == unicodedata.normalize("NFC", "챗봇")
    assert not hasattr(gates_module, "_norm_keyword")


def test_gt_norm_clause_rules():
    # NFC, 공백 접기(앞뒤 제거), 낫표·가운뎃점·전각 괄호/쉼표 통일, 끝 마침표 하나 제거
    nfd = unicodedata.normalize("NFD", "  부도 ㆍ 파산∙회생절차   중에\t있지 아니한 업체. ")
    assert norm_clause(nfd) == "부도·파산·회생절차 중에 있지 아니한 업체"
    assert norm_clause("｢소프트웨어 진흥법｣ 제48조") == "「소프트웨어 진흥법」 제48조"
    assert norm_clause("『지침』 준수") == "「지침」 준수"
    assert norm_clause("AI 챗봇（ 생성형 AI 포함 ） 구축") == "AI 챗봇(생성형 AI 포함) 구축"
    assert norm_clause("원칙으로 하며 , 구성원") == "원칙으로 하며, 구성원"
    assert norm_clause("갖추어야 함。") == "갖추어야 함"
    # 단어 사이 공백은 지우지 않는다("전부 도급" → "전부도급" 속 "부도" 오탐 방지)
    assert norm_clause("계약 목적물의 전부 도급") == "계약 목적물의 전부 도급"
    # norm_compact(사람 확인 키·실적 키워드)는 그대로
    assert norm_compact("부도 · 파산") == "부도·파산"


def test_gt_other_reclass_table_templates():
    assert [e.code for e in OTHER_RECLASS] == [
        "INSOLVENCY",
        "CONSORTIUM_CONDITION",
        "LARGE_CORP_EXCLUDED",
        "G2B_REGISTERED",
        "PAST_PERFORMANCE",
    ]
    assert [len(e.templates) for e in OTHER_RECLASS] == [1, 3, 2, 2, 1]
    assert {e.code: e.keyword for e in OTHER_RECLASS} == {
        "INSOLVENCY": None,
        "CONSORTIUM_CONDITION": None,
        "LARGE_CORP_EXCLUDED": None,
        "G2B_REGISTERED": None,
        "PAST_PERFORMANCE": "챗봇 구축",
    }
    assert RECLASS_SUFFIX == " [재분류 OTHER→{code}]"
    for entry in OTHER_RECLASS:
        assert entry.code in gates_module._RULES
        assert entry.code in get_args(GateCode)
        # 블랙리스트(패턴 포함 + 제외 단서) 필드는 없다(허용 목록 전환)
        assert not hasattr(entry, "patterns") and not hasattr(entry, "excludes")
        for t in entry.templates:
            assert isinstance(t, re.Pattern)
            assert t.flags & re.IGNORECASE
            # 임의 삽입(`.`·`.*`·`.+`)이 없다 — 가변 부분은 열거한 선택지뿐
            assert re.search(r"(?<!\\)\.", t.pattern) is None, t.pattern
            # 템플릿은 norm_clause 형태(연속 공백 없음)
            assert "  " not in t.pattern
    with pytest.raises(AttributeError):  # frozen
        OTHER_RECLASS[0].code = "OTHER"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (KNU_TEXT, "LARGE_CORP_EXCLUDED"),
        (MOFA_TEXT, "G2B_REGISTERED"),
        (NAMYANGJU_TEXT, "CONSORTIUM_CONDITION"),
        (DONGMIN_INSOLVENCY_TEXT, "INSOLVENCY"),
    ],
)
def test_gt_t2_reclassify_real_texts_keep_params(text, code):
    r = rule("OTHER", text)
    result = reclassify_other(r)
    assert result is not None
    got_code, params = result
    assert got_code == code
    assert params == r.params  # OTHER의 params(모두 null) 그대로
    assert params == RuleParams()


def test_gt_t2_reclassify_chatbot_to_performance_with_keyword():
    result = reclassify_other(rule("OTHER", DONGMIN_CHATBOT_TEXT))
    assert result == ("PAST_PERFORMANCE", RuleParams(keyword="챗봇 구축"))
    _, params = result
    assert params.years is None and params.amount_krw is None


# 허용 목록 템플릿에 통째로 맞는 변형(순서·구분자·조사·어미·선택 수식어·정규화)
ALLOWED_VARIANTS = [
    # INSOLVENCY
    ("부도, 파산 또는 회생절차 중에 있지 않은 자", "INSOLVENCY"),
    ("파산 및 회생절차 중에 있지 아니한 기업", "INSOLVENCY"),
    ("회생절차·파산·부도 중에 있지 아니한 업체", "INSOLVENCY"),
    ("부도ㆍ파산ㆍ회생절차 중에 있지 아니한 업체.", "INSOLVENCY"),
    ("부도 · 파산 · 회생 중이 아닌 자", "INSOLVENCY"),
    ("회생절차 진행 중이 아닌 업체", "INSOLVENCY"),
    # CONSORTIUM_CONDITION(구성원 자격 요건만)
    (
        "공동수급은 공동이행방식을 원칙으로 하며, 공동수급체 구성원 모두가 입찰참가자격을 "
        "갖추어야 함.",
        "CONSORTIUM_CONDITION",
    ),
    ("공동수급체 구성원 모두가 입찰참가자격을 갖추어야 함", "CONSORTIUM_CONDITION"),
    # CONSORTIUM_CONDITION(단독입찰 전용, 설계 2026-10-25-gate-staffing-consortium 2.2)
    (
        "본 사업은 단독입찰만 허용하며, 공동수급(공동이행)을 허용하지 않음",
        "CONSORTIUM_CONDITION",
    ),
    ("단독 입찰만 가능함", "CONSORTIUM_CONDITION"),
    ("공동수급 불허", "CONSORTIUM_CONDITION"),
    ("본 입찰은 공동수급(공동 또는 분담이행방식)은 불가", "CONSORTIUM_CONDITION"),
    (
        "공동수급체 구성원 전원이 본 입찰에서 요구하는 입찰 참가자격을 갖춰야 한다.",
        "CONSORTIUM_CONDITION",
    ),
    # LARGE_CORP_EXCLUDED
    ("「중소 소프트웨어사업자의 사업 참여 지원에 관한 지침」 준수", "LARGE_CORP_EXCLUDED"),
    (
        "『소프트웨어 진흥법』 제48조 및 「중소 소프트웨어사업자의 사업 참여 지원에 관한 지침」을 "
        "준수하여야 함",
        "LARGE_CORP_EXCLUDED",
    ),
    ("대기업인 소프트웨어사업자 참여 제한", "LARGE_CORP_EXCLUDED"),
    ("대기업인 소프트웨어사업자의 사업참여 제한", "LARGE_CORP_EXCLUDED"),
    # G2B_REGISTERED(국가계약법 시행령 12조 [및 시행규칙 14조] 경쟁입찰 참가자격만)
    ("국가계약법 시행령 제12조에 따른 경쟁입찰 참가자격", "G2B_REGISTERED"),
    ("국가계약법 시행령 제12조에 따른 경쟁입찰 참가자격을 갖춘 자", "G2B_REGISTERED"),
    (
        "「국가를 당사자로 하는 계약에 관한 법률 시행령」 제12조에 의한 경쟁입찰 참가자격을 "
        "갖추어야 함",
        "G2B_REGISTERED",
    ),
    (
        "국가를 당사자로 하는 계약에 관한 법률 시행령 제12조(경쟁입찰의 참가자격) 및 같은 법 "
        "시행규칙 제14조 규정에 따른 경쟁입찰 참가자격을 갖춘 업체",
        "G2B_REGISTERED",
    ),
    ("조달청 입찰참가자격 등록을 마친 업체", "G2B_REGISTERED"),
    # PAST_PERFORMANCE(챗봇)
    ("챗봇 구축 실적", "PAST_PERFORMANCE"),
    ("AI 챗봇 구축 실적을 보유한 업체", "PAST_PERFORMANCE"),
    ("ai 챗봇(LLM 기반 포함) 구축 실적 또는 역량을 보유한 자", "PAST_PERFORMANCE"),
    ("챗봇 구축 실적이 있는 업체", "PAST_PERFORMANCE"),
    (
        "AI 챗봇（생성형 AI 기반 포함） 구축 실적 또는 구축 역량을 보유한 업체.",
        "PAST_PERFORMANCE",
    ),
]


@pytest.mark.parametrize(("text", "code"), ALLOWED_VARIANTS)
def test_gt_t2_reclassify_allowed_variants(text, code):
    result = reclassify_other(rule("OTHER", text))
    assert result is not None and result[0] == code
    expected = RuleParams(keyword="챗봇 구축") if code == "PAST_PERFORMANCE" else RuleParams()
    assert result[1] == expected


@pytest.mark.parametrize(
    "text",
    [KNU_TEXT, MOFA_TEXT, NAMYANGJU_TEXT, DONGMIN_INSOLVENCY_TEXT, DONGMIN_CHATBOT_TEXT]
    + [t for t, _ in ALLOWED_VARIANTS],
)
def test_gt_t2_each_allowed_text_matches_exactly_one_entry(text):
    # fullmatch 템플릿끼리 겹치지 않는다(표 순서에 기대는 재분류 없음)
    normalized = norm_clause(text)
    hits = [e.code for e in OTHER_RECLASS if any(t.fullmatch(normalized) for t in e.templates)]
    assert len(hits) == 1, hits


def test_gt_t2_reclassify_normalization_variants_of_real_texts():
    # 공백·NFD·낫표/가운뎃점 변형·끝 마침표 유무에도 실공고 문구는 같은 코드
    spaced = "  " + NAMYANGJU_TEXT.replace(" ", "   ").rstrip(".") + "  "
    assert reclassify_other(rule("OTHER", spaced))[0] == "CONSORTIUM_CONDITION"
    nfd = unicodedata.normalize("NFD", DONGMIN_INSOLVENCY_TEXT.replace("·", "ㆍ"))
    assert reclassify_other(rule("OTHER", nfd))[0] == "INSOLVENCY"
    corner = KNU_TEXT.replace("｢", "「").replace("｣", "」")
    assert reclassify_other(rule("OTHER", corner))[0] == "LARGE_CORP_EXCLUDED"
    assert reclassify_other(rule("OTHER", MOFA_TEXT + "."))[0] == "G2B_REGISTERED"
    assert reclassify_other(rule("OTHER", DONGMIN_CHATBOT_TEXT.upper()))[0] == "PAST_PERFORMANCE"


def test_gt_t2_reclassify_none_cases():
    # OTHER가 아닌 코드는 문구가 템플릿에 맞아도 재분류하지 않는다
    assert reclassify_other(rule("G2B_REGISTERED", DONGMIN_INSOLVENCY_TEXT)) is None
    assert reclassify_other(rule("PAST_PERFORMANCE", DONGMIN_CHATBOT_TEXT)) is None
    # 일치 없는 OTHER
    assert reclassify_other(rule("OTHER", "제안서 제출 전 설명회 참석")) is None
    assert reclassify_other(rule("OTHER", "기타 자격")) is None
    assert reclassify_other(rule("OTHER", "")) is None


# 근거 없는 PASS 재현 사례(독립 리뷰 2026-10-23 두 차례 + 허용 목록 전환 뒤 보수 쪽 미탐).
# 조항 전체가 템플릿과 통째로 맞지 않으면 OTHER UNKNOWN → 사람 확인.
REVIEW_KEEP_OTHER = [
    # 1차 리뷰: G2B_REGISTERED 등록 외 요건(중소기업자간·직접생산·지역·소재·업종코드)
    "중소기업자간 경쟁입찰 참가자격을 갖춘 자로서 직접생산확인증명서를 소지한 업체",
    "지역제한 경쟁입찰 참가자격: 주된 영업소 소재지가 강원특별자치도인 업체",
    "국가계약법 시행령 제12조에 따른 경쟁입찰 참가자격을 갖추고 소프트웨어사업자(업종코드 1468)로 "
    "신고한 업체",
    "입찰참가자격 등록 및 업종코드(1468) 등록 업체",
    # 1차 리뷰: 공동수급 의무화, 실적·금액 요건 혼합
    "본 사업은 지역의무 공동수급 대상으로, 반드시 도내 업체와 공동수급체를 구성하여 참가하여야 함",
    "공동수급체를 구성하여야 함",
    "단독 입찰 불가, 공동수급만 허용",
    "공동수급체 구성 시 대표사는 최근 3년간 유사 실적 10억 이상 보유",
    # 1차 리뷰: 체납·제재 요건 혼합, 다른 단어 속 "부도"
    "국세·지방세 체납이 없고 부도·파산·회생절차 중에 있지 아니한 업체",
    "부정당업자 제재를 받지 않은 자로서 파산선고를 받지 않은 자",
    "부도심 지역 소재 업체",
    "남부 도시 지역 업체",
    # 1차 리뷰: 챗봇 금액·기간·인력 단서
    "최근 3년 이내 단일 계약 3억원 이상 AI 챗봇 구축 실적 보유 업체",
    "챗봇 운영 인력(PM) 1명 이상 상주",
    "챗봇 구축 실적 2건 이상",
    "챗봇 전담 pm 투입",
    "대기업인 소프트웨어사업자의 참여 제한 예외 인정 사업으로 대기업 참여 가능",
    # 2차 리뷰: 공동수급 의무·지분·지역·조건
    "공동수급 허용(공동이행방식, 구성원 수 3개사 이하)",
    "도내 업체와 공동수급하여야 함",
    "지역업체 참여비율 30% 이상 공동수급",
    "지역업체와 공동수급체를 구성할 것",
    "공동수급을 원칙으로 함",
    "공동수급체 구성 시 지역업체를 포함할 것",
    "본 사업은 공동수급이 불가하며 하도급도 제한됨",
    "공동수급 시 구성원은 5개사 이하, 최소 지분율 10% 이상",
    "공동수급체 구성원 중 1개사 이상은 도내 업체여야 함",
    "공동수급(분담이행) 시 지역업체 지분 40% 이상 포함",
    # 2차 리뷰: 부도·파산 외 요건·다른 사유, 공백 제거 비교의 단어 경계 오탐
    "부도·파산·회생 및 입찰참가자격 제한을 받고 있지 않은 자",
    "파산선고를 받고 복권되지 아니한 자, 금고 이상의 형을 선고받은 자는 참가 불가",
    "부도, 당좌거래정지, 해산, 청산 중인 업체 제외",
    "설계 세부도면 제출이 가능한 업체",
    "기업회생 절차 개시 업체 제외",
    "계약 목적물의 전부 도급(일괄 하도급)은 금지함",
    "사업의 일부 도급 시 발주기관 사전 승인 필요",
    # 2차 리뷰: 경쟁입찰 참가자격 + 다른 요건(면허·등록·지정·인증·다른 법)
    "국가종합전자조달시스템 경쟁입찰 참가자격 등록 및 정보통신공사업법에 따른 정보통신공사업 "
    "등록 업체",
    "경쟁입찰 참가자격을 갖추고 엔지니어링사업자로 신고된 자",
    "경쟁입찰참가자격 및 정보보호전문서비스기업 지정 업체",
    "경쟁입찰 참가자격을 갖춘 자로서 ISMS 인증 보유 업체",
    "지방자치단체를 당사자로 하는 계약에 관한 법률 시행령 제13조에 따른 경쟁입찰 참가자격",
    "경쟁입찰 참가자격을 갖추고 전기공사업 면허를 보유한 자",
    "경쟁입찰 참가자격을 갖추고 정보통신공사업을 등록한 자",
    # 2차 리뷰: 챗봇 + 인증·제품·대상·대체 요건
    "AI 챗봇 구축 실적 보유 업체로서 GS인증 제품 보유",
    "챗봇 솔루션 보유 업체",
    "공공기관 대상 챗봇 구축 실적",
    "챗봇 구축 실적 또는 ISMS-P 인증",
    "챗봇 구축 실적이 있는 업체로서 소프트웨어사업자 신고 업체",
    "챗봇 구축 실적 보유 및 정보보호 관리체계(ISMS) 획득 업체",
    "챗봇 서비스 운영 실적(단, 하도급 실적 불인정)",
    # 실공고 문구 + 덧붙은 요건(허용 목록은 조항 전체가 맞아야 한다)
    "공동수급은 공동이행방식을 원칙으로 하며, 공동수급체 구성원 모두가 본 입찰에서 요구하는 "
    "입찰참가자격을 갖추어야 하며, 지역업체 지분 30% 이상 포함",
    "공동수급체 구성원 모두가 입찰참가자격을 갖추어야 하며, 대표사는 지분 51% 이상",
    "부도·파산·회생절차 중에 있지 아니한 업체로서 국세 체납이 없는 업체",
    "국가계약법 시행령 제12조에 따른 경쟁입찰 참가자격을 갖춘 자로서 직접생산확인증명서를 소지한 "
    "업체",
    "국가를 당사자로 하는 계약에 관한 법률 시행령 제12조에 따른 경쟁입찰 참가자격을 갖춘 자로서 "
    "서울특별시에 소재한 업체",
    "AI 챗봇(단일 계약 3억원 이상) 구축 실적을 보유한 업체",
    "AI 챗봇(생성형 AI 기반 포함) 구축 실적 또는 구축 역량을 보유한 업체로서 ISMS 인증 보유",
    # 최종 리뷰: 범위를 좁히는 한정 괄호("(… 포함)"이 아닌 것)는 실적 규칙이 판정하지 못함
    "ai 챗봇(LLM 기반) 구축 실적 또는 역량을 보유한 자",
    "챗봇(LLM 기반) 구축 실적 보유",
    "챗봇(생성형 AI 기반) 구축 실적을 보유한 업체",
    "AI 챗봇(대화형 AI 기반) 구축 실적 또는 구축 역량을 보유한 업체",
    "｢소프트웨어 진흥법｣ 제48조에 따른 대기업인 소프트웨어사업자의 참여 제한 예외 인정 사업",
    # 허용 목록 밖 → 보수 쪽 미탐(사람 확인). 이전 패턴 방식에서는 재분류되던 문구
    # ("공동수급 불허"는 2026-10-25 단독입찰 전용 템플릿으로 허용 목록에 들어갔다)
    "공동수급 불허(단독 입찰만 가능)",
    "공동 수급 허용",
    "공동수급체 구성원 중 부도 업체가 있어서는 안 됨",
    "공동수급체 구성원 모두 입찰참가자격 등록을 해야 함",
    "부도 시 계약 해지",
    "부도 또는 파산 상태가 아닌 자",
    "회생절차 개시 신청 사실이 없는 업체",
    "대기업인 소프트웨어사업자의 참여 제한 예외 인정 사업",
    "국세 체납이 없고 부도가 없으며 입찰참가자격 등록을 마친 업체",
    "경쟁입찰 참가자격을 갖춘 자(2026년 9월 1일 기준)",
]


@pytest.mark.parametrize("text", REVIEW_KEEP_OTHER)
def test_gt_review_reclass_not_in_allowlist_keeps_other(text):
    assert reclassify_other(rule("OTHER", text)) is None
    # 게이트는 기존 OTHER UNKNOWN "원문 확인" — 가정값(단독 입찰·등록·부도 없음)으로 PASS하지 않음
    profile = make_profile(
        {
            **GT_PROFILE,
            "registrations.tax_delinquency": "none",
        },
        portfolio=[
            portfolio_item(
                "P1",
                title="OO기관 AI 챗봇 구축",
                type="구축",
                completed=True,
                period_end="2026-01",
                amount_krw=50_000_000,
            )
        ],
    )
    [g] = evaluate_gates(make_facts(eligibility=[rule("OTHER", text)]), profile, as_of=AS_OF)
    assert g.code == "OTHER"
    assert g.verdict == "UNKNOWN"
    assert g.action == "원문 확인"
    assert g.rule_text == text


def test_gt_t2_reclassify_does_not_change_rule():
    r = rule("OTHER", DONGMIN_CHATBOT_TEXT)
    before = r.model_dump()
    reclassify_other(r)
    assert r.model_dump() == before


def _reclass_suffix(code):
    return RECLASS_SUFFIX.format(code=code)


DATE_SUFFIX = " [기준일 2026-11-05 제출마감]"

GT_PROFILE = {
    "company.size": "중소기업",
    "registrations.g2b.registered": True,
    "registrations.insolvency": "none",
    "policy.default_bid_mode": "solo",
    "company.founded": "2015-01",
}


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (KNU_TEXT, "LARGE_CORP_EXCLUDED"),
        (MOFA_TEXT, "G2B_REGISTERED"),
        (NAMYANGJU_TEXT, "CONSORTIUM_CONDITION"),
        (DONGMIN_INSOLVENCY_TEXT, "INSOLVENCY"),
    ],
)
def test_gt_t3_reclassified_gate_code_rule_text_evidence(text, code):
    ev = make_evidence(quote=text, section_id="S010")
    facts = make_facts(
        submission_deadline="2026-11-05", eligibility=[rule("OTHER", text, evidence=ev)]
    )
    [g] = evaluate_gates(facts, make_profile(GT_PROFILE), as_of=AS_OF)
    assert g.code == code
    assert g.rule_text == text + f" [재분류 OTHER→{code}]"  # 기준일 접미 없음
    assert g.rule_hash == eligibility_rule_hash(text)
    assert g.evidence == [ev]
    assert_pass(g)
    # facts는 바꾸지 않는다
    assert facts.eligibility[0].code == "OTHER"
    assert facts.eligibility[0].params == RuleParams()


def test_gt_t3_reclassified_performance_gets_reclass_then_date_suffix():
    facts = make_facts(
        submission_deadline="2026-11-05", eligibility=[rule("OTHER", DONGMIN_CHATBOT_TEXT)]
    )
    [g] = evaluate_gates(facts, make_profile(GT_PROFILE), as_of=AS_OF)
    assert g.code == "PAST_PERFORMANCE"
    assert g.rule_text == (DONGMIN_CHATBOT_TEXT + " [재분류 OTHER→PAST_PERFORMANCE]" + DATE_SUFFIX)
    assert g.rule_hash == eligibility_rule_hash(DONGMIN_CHATBOT_TEXT)
    # 실적 없음 → 실적 규칙(keyword 챗봇 구축, 금액·연수 없음)대로 UNKNOWN
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == ["portfolio"]
    assert g.action == "확인 필요: " + hint_for("portfolio")
    assert "확정후보=0" in g.company_value
    assert g.evidence == [EVIDENCE]
    assert facts.eligibility[0].params.keyword is None


def test_gt_t3_reclassified_performance_uses_pattern_keyword():
    chatbot = portfolio_item(
        "P2025-01", title="민원 AI 챗봇 구축", type="구축", completed=True, period_end="2025-06"
    )
    homepage = portfolio_item(
        "P2025-02", title="홈페이지 구축", type="구축", completed=True, period_end="2025-06"
    )
    r = rule("OTHER", DONGMIN_CHATBOT_TEXT)
    passed = gate(r, make_profile(GT_PROFILE, portfolio=[homepage, chatbot]))
    assert_pass(passed)
    assert "확정후보=1" in passed.company_value
    # keyword 챗봇 구축에 맞지 않는 실적만 있으면 후보 0
    missing = gate(r, make_profile(GT_PROFILE, portfolio=[homepage]))
    assert_fail(missing)
    assert "확정후보=0" in missing.company_value


@pytest.mark.parametrize("perf_type", ["유지관리", "운영", "컨설팅"])
@pytest.mark.parametrize(
    "text", ["챗봇 구축 실적", "AI 챗봇 구축 실적을 보유한 업체", DONGMIN_CHATBOT_TEXT]
)
def test_gt_final_review_chatbot_non_build_type_is_not_pass(text, perf_type):
    # 최종 리뷰: keyword가 "챗봇"뿐이면 유형 필터가 꺼져 챗봇 유지관리·운영·컨설팅 1건으로 PASS했다
    item = portfolio_item(
        "P2025-01", title="민원 AI 챗봇 운영", type=perf_type, completed=True, period_end="2025-06"
    )
    g = gate(rule("OTHER", text), make_profile(GT_PROFILE, portfolio=[item]))
    assert g.code == "PAST_PERFORMANCE"
    assert_fail(g)
    assert "확정후보=0" in g.company_value
    assert g.company_value.endswith("키워드=[챗봇]; 유형=[구축, 개발]")


@pytest.mark.parametrize("perf_type", ["구축", "개발"])
@pytest.mark.parametrize(
    "text", ["챗봇 구축 실적", "AI 챗봇 구축 실적을 보유한 업체", DONGMIN_CHATBOT_TEXT]
)
def test_gt_final_review_chatbot_build_type_passes(text, perf_type):
    item = portfolio_item(
        "P2025-01", title="민원 AI 챗봇 구축", type=perf_type, completed=True, period_end="2025-06"
    )
    g = gate(rule("OTHER", text), make_profile(GT_PROFILE, portfolio=[item]))
    assert g.code == "PAST_PERFORMANCE"
    assert_pass(g)
    assert "확정후보=1" in g.company_value


@pytest.mark.parametrize(
    "text",
    [
        "챗봇(LLM 기반) 구축 실적 보유",
        "챗봇(생성형 AI 기반) 구축 실적을 보유한 업체",
    ],
)
def test_gt_final_review_chatbot_narrowing_parenthesis_is_not_reclassified(text):
    # 한정 괄호는 범위를 좁힌다 → 재분류하지 않고 OTHER UNKNOWN(시나리오형 챗봇 실적으로 PASS 금지)
    assert reclassify_other(rule("OTHER", text)) is None
    item = portfolio_item(
        "P2025-01", title="시나리오형 챗봇 구축", type="구축", completed=True, period_end="2025-06"
    )
    g = gate(rule("OTHER", text), make_profile(GT_PROFILE, portfolio=[item]))
    assert g.code == "OTHER"
    assert g.verdict == "UNKNOWN"
    assert g.action == "원문 확인"


def test_gt_t3_unmatched_other_keeps_existing_behavior():
    facts = make_facts(
        submission_deadline="2026-11-05",
        eligibility=[rule("OTHER", "제안서 제출 전 설명회 참석")],
    )
    [g] = evaluate_gates(facts, make_profile(GT_PROFILE), as_of=AS_OF)
    assert g.code == "OTHER"
    assert g.rule_text == "제안서 제출 전 설명회 참석"
    assert g.verdict == "UNKNOWN"
    assert g.action == "원문 확인"
    assert g.company_value == "-"
    assert g.unknown_fields == []


def test_gt_t3_reclassified_rule_unknown_profile_keeps_unknown_fields():
    # 재분류된 규칙이 프로필 unknown을 만나면 UNKNOWN + unknown_fields(제약 2)
    g = gate(rule("OTHER", MOFA_TEXT), make_profile())
    assert g.code == "G2B_REGISTERED"
    assert_unknown_hint(g, "registrations.g2b.registered")
    g = gate(rule("OTHER", KNU_TEXT), make_profile({"company.size": "대기업"}))
    assert g.code == "LARGE_CORP_EXCLUDED"
    assert_fail(g)


def test_gt_t3_rule_functions_do_not_read_rule_code():
    # 재분류는 rule.code를 OTHER로 둔 채 다른 코드의 규칙 함수를 부르므로, 규칙 함수가
    # rule.code를 읽으면 안 된다(spec 유지 조건)
    for fn in set(gates_module._RULES.values()):
        assert "rule.code" not in inspect.getsource(fn), fn.__name__


def test_gt_t3_deterministic_and_input_unchanged():
    facts = make_facts(
        submission_deadline="2026-11-05",
        eligibility=[
            rule("OTHER", NAMYANGJU_TEXT),
            rule("OTHER", DONGMIN_CHATBOT_TEXT),
            rule("OTHER", "기타 자격"),
        ],
    )
    profile = make_profile(GT_PROFILE)
    before = (facts.model_dump(), profile.model_dump())
    first = evaluate_gates(facts, profile, as_of=AS_OF)
    second = evaluate_gates(facts, profile, as_of=AS_OF)
    assert [g.model_dump() for g in first] == [g.model_dump() for g in second]
    assert (facts.model_dump(), profile.model_dump()) == before
    assert [g.code for g in first] == ["CONSORTIUM_CONDITION", "PAST_PERFORMANCE", "OTHER"]


# --- GT-01: 새 규칙(spec GT-01 T4) ---


def _consortium(mode):
    values = {} if mode is None else {"policy.default_bid_mode": mode}
    return gate(rule("OTHER", NAMYANGJU_TEXT), make_profile(values))


def test_gt_t4_consortium_solo_passes():
    g = _consortium("solo")
    assert g.code == "CONSORTIUM_CONDITION"
    assert_pass(g)
    assert g.company_value == "policy.default_bid_mode=solo"
    assert g.unknown_fields == []
    assert g.rule_text == NAMYANGJU_TEXT + _reclass_suffix("CONSORTIUM_CONDITION")


def test_gt_t4_consortium_mode_is_unknown_with_member_check_action():
    g = _consortium("consortium")
    assert g.verdict == "UNKNOWN"
    assert g.company_value == "policy.default_bid_mode=consortium"
    assert g.unknown_fields == []
    assert ACTION_CHECK_CONSORTIUM == "공동수급체 구성원 자격 확인"
    assert g.action == ACTION_CHECK_CONSORTIUM


def test_gt_t4_consortium_policy_unknown():
    g = _consortium(None)
    assert g.company_value == "policy.default_bid_mode=unknown"
    assert_unknown_hint(g, "policy.default_bid_mode")


@pytest.mark.parametrize(("value", "verdict"), [("none", "PASS"), ("active", "FAIL")])
def test_gt_t4_insolvency_pass_fail(value, verdict):
    g = gate(
        rule("OTHER", DONGMIN_INSOLVENCY_TEXT),
        make_profile({"registrations.insolvency": value}),
    )
    assert g.code == "INSOLVENCY"
    assert g.company_value == f"registrations.insolvency={value}"
    assert g.rule_text == DONGMIN_INSOLVENCY_TEXT + _reclass_suffix("INSOLVENCY")
    if verdict == "PASS":
        assert_pass(g)
    else:
        assert_fail(g)
    assert g.unknown_fields == []


def test_gt_t4_insolvency_unknown():
    g = gate(rule("OTHER", DONGMIN_INSOLVENCY_TEXT), make_profile())
    assert g.company_value == "registrations.insolvency=unknown"
    assert_unknown_hint(g, "registrations.insolvency")


def test_gt_t4_new_rules_registered_and_not_date_gates():
    assert "CONSORTIUM_CONDITION" in gates_module._RULES
    assert "INSOLVENCY" in gates_module._RULES
    assert gates_module.DATE_GATE_CODES == frozenset(
        {"SME_CERT", "DIRECT_PRODUCTION", "SW_BUSINESS_REPORT", "PAST_PERFORMANCE"}
    )
    # 기준일 접미 없음(재분류 접미만)
    facts = make_facts(
        submission_deadline="2026-11-05",
        eligibility=[rule("OTHER", NAMYANGJU_TEXT), rule("OTHER", DONGMIN_INSOLVENCY_TEXT)],
    )
    texts = [g.rule_text for g in evaluate_gates(facts, make_profile(), as_of=AS_OF)]
    assert texts == [
        NAMYANGJU_TEXT + _reclass_suffix("CONSORTIUM_CONDITION"),
        DONGMIN_INSOLVENCY_TEXT + _reclass_suffix("INSOLVENCY"),
    ]


# --- GT-01: 인증 이름(spec GT-01 T6) ---


def test_gt_t6_other_cert_aliases_table():
    assert OTHER_CERT_ALIASES == {
        "isms": ("정보보호관리체계",),
        "isms-p": ("정보보호및개인정보보호관리체계",),
    }


def _confirmed_cert_names(profile):
    reg = profile.registrations
    optional_leaf = {
        "venture": "type",
        "innobiz": "since",
        "mainbiz": "since",
        "rnd_institute": "type",
        "specialized_research_business": "since",
        "engineering_business_report": "since",
        "industrial_design_company": "since",
        "performance_sharing_company": "since",
        "military_designated_company": "since",
        "esg_cert": "has",
    }
    paths = [
        f"registrations.{name}.{leaf}"
        for name, leaf in optional_leaf.items()
        if getattr(reg, name) is not None
    ]
    paths.extend(
        [
            "registrations.iso",
            "registrations.cloud_certs",
            "registrations.gs_cert",
            "registrations.other_certs",
        ]
    )
    return profile_cert_names(confirmed_view(profile, paths))


def test_gt_t6_other_certs_appended_after_gs_cert_with_aliases():
    profile = make_profile(
        {**CERT_PROFILE, "registrations.gs_cert": ["바로웹 v2"]},
        other_certs=[other_cert("ISMS"), other_cert("사회적기업")],
    )
    names = _confirmed_cert_names(profile)
    assert names[-5:] == ["바로웹 v2", "GS인증", "ISMS", "정보보호관리체계", "사회적기업"]
    # 기존 이름 순서는 그대로 앞에
    assert names[0] == "벤처기업"


def test_gt_t6_other_certs_without_gs_cert_and_alias_key_normalized():
    profile = make_profile(other_certs=[other_cert(" is ms-P "), other_cert("isms")])
    assert _confirmed_cert_names(profile) == [
        " is ms-P ",
        "정보보호및개인정보보호관리체계",
        "isms",
        "정보보호관리체계",
    ]


def test_gt_t6_other_certs_dedup_and_unknown_names_skipped():
    profile = make_profile(
        {"registrations.venture": {"type": "혁신성장유형"}},
        other_certs=[
            other_cert("ISMS"),
            other_cert("벤처기업"),
            other_cert("unknown"),
            other_cert("  "),
        ],
    )
    assert _confirmed_cert_names(profile) == ["벤처기업", "ISMS", "정보보호관리체계"]


def test_gt_t6_confirmed_null_cert_objects_do_not_become_holdings():
    profile = make_profile()
    view = confirmed_view(
        profile,
        ["registrations.venture", "registrations.specialized_research_business"],
    )
    assert profile_cert_names(view) == []


@pytest.mark.parametrize(
    ("kind", "cert_name"),
    [
        ("venture", "벤처기업"),
        ("iso", "ISO 9001"),
        ("cloud", "CSAP"),
        ("other", "ISMS"),
    ],
)
def test_rev_required_cert_passes_from_todo_guided_paths_only(kind, cert_name):
    if kind == "venture":
        profile = make_profile(
            {
                "registrations.venture": {
                    "type": "혁신성장유형",
                    "since": "2023-05",
                    "valid_until": "2027-05",
                }
            }
        )
        prefix = "registrations.venture"
    elif kind == "iso":
        profile = make_profile({"registrations.iso": [{"std": "9001", "since": "2024-01"}]})
        prefix = "registrations.iso"
    elif kind == "cloud":
        profile = make_profile(
            {"registrations.cloud_certs": [{"name": "CSAP", "since": "2024-01"}]}
        )
        prefix = "registrations.cloud_certs"
    else:
        profile = make_profile(
            other_certs=[other_cert("ISMS", since="2024-01", valid_until="2027-01")]
        )
        prefix = "registrations.other_certs"

    todo_paths = [
        item.path for item in todo(CompanyEvidenceView(profile)) if item.path.startswith(prefix)
    ]
    assert todo_paths
    assert not any(path.endswith((".std", ".name")) for path in todo_paths)

    g = gate(rule("REQUIRED_CERT", cert_name=cert_name), confirmed_view(profile, todo_paths))

    assert_pass(g)
    assert not any(path.endswith((".std", ".name")) for path in g.input_fields)


@pytest.mark.parametrize(
    ("kind", "cert_name", "collection_path", "structural_suffix"),
    [
        ("iso", "ISO 9001", "registrations.iso", ".std"),
        ("cloud", "CSAP", "registrations.cloud_certs", ".name"),
        ("other", "ISMS", "registrations.other_certs", ".name"),
    ],
)
def test_rev_required_cert_raw_list_unknowns_are_todo_actionable(
    kind, cert_name, collection_path, structural_suffix
):
    if kind == "iso":
        profile = make_profile({"registrations.iso": [{"std": "9001", "since": "2024-01"}]})
    elif kind == "cloud":
        profile = make_profile(
            {"registrations.cloud_certs": [{"name": "CSAP", "since": "2024-01"}]}
        )
    else:
        profile = make_profile(
            other_certs=[other_cert("ISMS", since="2024-01", valid_until="2027-01")]
        )
    view = CompanyEvidenceView(profile)

    g = gate(rule("REQUIRED_CERT", cert_name=cert_name), view)
    todo_paths = {item.path for item in todo(view)}

    assert g.verdict == "UNKNOWN"
    assert collection_path in g.unknown_fields
    assert set(g.unknown_fields) <= todo_paths
    assert not any(path.endswith(structural_suffix) for path in g.unknown_fields)
    assert not any(path.endswith(structural_suffix) for path in g.input_fields)


@pytest.mark.parametrize(
    ("path", "values", "cert_name"),
    [
        (
            "registrations.iso[9001]",
            {"registrations.iso": [{"std": "9001", "since": "2024-01"}]},
            "ISO 9001",
        ),
        (
            "registrations.cloud_certs[CSAP]",
            {"registrations.cloud_certs": [{"name": "CSAP", "since": "2024-01"}]},
            "CSAP",
        ),
    ],
)
def test_rev_required_cert_accepts_exact_item_provenance(path, values, cert_name):
    profile = make_profile(values)
    g = gate(rule("REQUIRED_CERT", cert_name=cert_name), confirmed_view(profile, [path]))
    assert_pass(g)
    assert path in g.input_fields
    assert not any(field.endswith((".std", ".name")) for field in g.input_fields)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("venture_unconfirmed", "UNKNOWN"),
        ("venture_hash_mismatch", "UNKNOWN"),
        ("venture_since_confirmed", "PASS"),
        ("iso_unconfirmed", "UNKNOWN"),
        ("iso_item_confirmed", "PASS"),
        ("cloud_item_confirmed", "PASS"),
        ("other_name_confirmed", "PASS"),
    ],
)
def test_rev_required_cert_records_every_provenance_lookup(monkeypatch, case, expected):
    if case.startswith("venture"):
        profile = make_profile(
            {
                "registrations.venture": {
                    "type": "혁신성장유형",
                    "since": "2023-05",
                    "valid_until": "2027-05",
                }
            }
        )
        if case == "venture_unconfirmed":
            view = CompanyEvidenceView(profile)
        else:
            view = confirmed_view(profile, ["registrations.venture.since"])
            if case == "venture_hash_mismatch":
                profile.registrations.venture.since = "2023-06"  # type: ignore[union-attr]
        cert_name = "벤처기업"
    elif case.startswith("iso"):
        profile = make_profile({"registrations.iso": [{"std": "9001", "since": "2024-01"}]})
        view = (
            confirmed_view(profile, ["registrations.iso[9001]"])
            if case == "iso_item_confirmed"
            else CompanyEvidenceView(profile)
        )
        cert_name = "ISO 9001"
    elif case == "cloud_item_confirmed":
        profile = make_profile(
            {"registrations.cloud_certs": [{"name": "CSAP", "since": "2024-01"}]}
        )
        view = confirmed_view(profile, ["registrations.cloud_certs[CSAP]"])
        cert_name = "CSAP"
    else:
        profile = make_profile(other_certs=[other_cert("ISMS")])
        view = confirmed_view(profile, ["registrations.other_certs[ISMS].name"])
        cert_name = "ISMS"

    calls: list[str] = []
    original_get = view.get

    def spy(path):
        calls.append(path)
        return original_get(path)

    monkeypatch.setattr(view, "get", spy)
    g = gate(rule("REQUIRED_CERT", cert_name=cert_name), view)

    assert g.verdict == expected
    assert g.input_fields == list(dict.fromkeys(calls))
    if case in ("venture_unconfirmed", "venture_hash_mismatch"):
        assert calls[:3] == [
            "registrations.venture.type",
            "registrations.venture.since",
            "registrations.venture.valid_until",
        ]
    elif case == "venture_since_confirmed":
        assert calls[:2] == [
            "registrations.venture.type",
            "registrations.venture.since",
        ]


def test_rev_required_cert_missing_optional_object_provenance_is_tracked():
    profile = make_profile()
    g = gate(
        rule("REQUIRED_CERT", cert_name="기업부설연구소"),
        CompanyEvidenceView(profile),
    )
    for path in ("registrations.rnd_institute", "registrations.esg_cert"):
        assert path in g.input_fields
        assert path in g.unknown_fields


def test_rev_required_cert_confirmed_null_optional_objects_are_known_absent():
    profile = make_profile()
    paths = ["registrations.rnd_institute", "registrations.esg_cert"]
    g = gate(
        rule("REQUIRED_CERT", cert_name="기업부설연구소"),
        confirmed_view(profile, paths),
    )
    for path in paths:
        assert path in g.input_fields
        assert path not in g.unknown_fields


_OPTIONAL_CERT_ROOTS = [
    "venture",
    "innobiz",
    "mainbiz",
    "rnd_institute",
    "specialized_research_business",
    "engineering_business_report",
    "industrial_design_company",
    "performance_sharing_company",
    "military_designated_company",
    "esg_cert",
]


def _profile_with_no_confirmed_cert_holdings(*, omit: str | None = None):
    values = {
        **{f"registrations.{name}": None for name in _OPTIONAL_CERT_ROOTS if name != omit},
        "registrations.iso": [],
        "registrations.cloud_certs": [],
        "registrations.gs_cert": [],
    }
    return make_profile(values, other_certs=[])


def test_rev_required_cert_all_confirmed_holdings_absent_fails():
    g = gate(
        rule("REQUIRED_CERT", cert_name="기업부설연구소"),
        _profile_with_no_confirmed_cert_holdings(),
    )
    assert_fail(g)
    assert g.unknown_fields == []


def test_rev_required_cert_any_unconfirmed_holding_path_remains_unknown():
    g = gate(
        rule("REQUIRED_CERT", cert_name="기업부설연구소"),
        _profile_with_no_confirmed_cert_holdings(omit="esg_cert"),
    )
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == ["registrations.esg_cert"]


@pytest.mark.parametrize(
    "cert_name",
    ["정보보호 관리체계(ISMS) 인증", "ISMS", "정보보호 관리체계 인증", "ISMS-P"],
)
def test_gt_t6_required_cert_isms_passes(cert_name):
    # "ISMS-P"는 목록의 "isms"가 포함돼 PASS(알려진 과대 판정 — spec 결정과 이유 표)
    profile = make_profile(other_certs=[other_cert("ISMS"), other_cert("사회적기업")])
    g = gate(rule("REQUIRED_CERT", cert_name=cert_name), profile)
    assert_pass(g)
    assert g.code == "REQUIRED_CERT"
    assert "ISMS" in g.company_value and "사회적기업" in g.company_value


def test_gt_t6_required_cert_gs_behavior_unchanged_with_other_certs():
    profile = make_profile(CERT_PROFILE, other_certs=[other_cert("ISMS")])
    g = gate(rule("REQUIRED_CERT", cert_name="GS인증"), profile)
    assert g.verdict == "UNKNOWN"
    assert "registrations.gs_cert" in g.unknown_fields
    assert g.action.startswith("확인 필요: ")


def test_gt_t6_required_cert_isms_without_other_certs_is_unknown():
    g = gate(rule("REQUIRED_CERT", cert_name="정보보호 관리체계(ISMS) 인증"), make_profile())
    assert g.verdict == "UNKNOWN" and g.action.startswith("확인 필요: ")
    assert "registrations.other_certs" in g.unknown_fields


# --- GT-02: 실적 키워드 해석·동의어·유형 매칭(spec GT-02 T1~T3) ---

_PROJECT_TYPES = frozenset(get_args(ProjectType))


@pytest.mark.parametrize(
    ("text", "core", "types"),
    [
        ("기업·기관 홈페이지(반응형 웹) 구축", ("홈페이지",), {"구축", "개발"}),
        ("최근 3년 이내 홈페이지 유지관리 실적", ("홈페이지",), {"유지관리", "운영"}),
        ("누리집 개편", ("누리집",), {"구축", "고도화"}),
        ("챗봇", ("챗봇",), None),
        ("수행 실적", (), None),
        ("AI 챗봇 구축", ("ai", "챗봇"), {"구축", "개발"}),
    ],
)
def test_gt02_t1_parse_spec_examples(text, core, types):
    kw = parse_perf_keyword(text)
    assert isinstance(kw, PerfKeyword)
    assert kw.raw == text
    assert kw.core == core
    if types is None:
        assert kw.types is None
    else:
        assert kw.types == frozenset(types)


def test_gt02_t1_perf_keyword_is_frozen():
    kw = parse_perf_keyword("홈페이지 구축")
    with pytest.raises(AttributeError):
        kw.core = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    "text",
    [
        "기업·기관 홈페이지（반응형 웹） 구축",  # 전각 소괄호
        "기업·기관 홈페이지 [반응형 웹] 구축",  # 대괄호
        "기업·기관 홈페이지 ［반응형 웹］ 구축",  # 전각 대괄호
        "기업 홈페이지(반응형) (모바일 포함) 구축",  # 괄호 구간 여러 개
    ],
)
def test_gt02_t1_paren_sections_removed(text):
    kw = parse_perf_keyword(text)
    assert kw.core == ("홈페이지",)
    assert kw.types == frozenset({"구축", "개발"})


def test_gt02_t1_split_on_separators_keeps_order():
    kw = parse_perf_keyword("홈페이지·누리집/챗봇,포털ㆍ웹사이트\t대화형봇")
    assert kw.core == ("홈페이지", "누리집", "챗봇", "포털", "웹사이트", "대화형봇")
    assert kw.types is None


def test_gt02_t1_duplicate_tokens_once_and_types_union():
    kw = parse_perf_keyword("홈페이지 홈페이지 구축 개발 유지관리 홈페이지")
    assert kw.core == ("홈페이지",)
    assert kw.types == frozenset({"구축", "개발", "유지관리", "운영"})


def test_gt02_t1_number_leading_tokens_dropped():
    kw = parse_perf_keyword("최근 5년 이내 2건 이상 10억원 홈페이지 3D 구축")
    assert kw.core == ("홈페이지",)
    assert kw.types == frozenset({"구축", "개발"})


def test_gt02_t1_short_tokens_and_stopwords_dropped():
    # "홈"(길이 1) 버림, "페이지"는 핵심; keyword 토큰 "앱"도 길이 1이라 버림(의도된 비대칭)
    assert parse_perf_keyword("홈 페이지").core == ("페이지",)
    kw = parse_perf_keyword("앱 개발")
    assert kw.core == ()
    assert kw.types == frozenset({"구축", "개발"})
    every_stopword = " ".join(sorted(PERF_STOPWORDS))
    assert parse_perf_keyword(every_stopword).core == ()
    assert parse_perf_keyword(every_stopword).types is None


def test_gt02_t1_type_tokens_each_map_to_table():
    for token, allowed in PERF_TYPE_TOKENS.items():
        kw = parse_perf_keyword(f"홈페이지 {token}")
        assert kw.core == ("홈페이지",), token
        assert kw.types == allowed, token


def test_gt02_t1_casefold_nfc_and_empty():
    nfd = unicodedata.normalize("NFD", "Chatbot 홈페이지 구축")
    kw = parse_perf_keyword(nfd)
    assert kw.raw == nfd
    assert kw.core == ("chatbot", "홈페이지")
    for empty in ("", "   ", "()", "（반응형 웹）"):
        kw = parse_perf_keyword(empty)
        assert kw.core == () and kw.types is None, empty


def test_gt02_t1_core_tokens_are_perf_norm_fixed_points():
    for text in ("기업·기관 홈페이지(반응형 웹) 구축", "AI 챗봇 구축", "Web 포털 리뉴얼"):
        for token in parse_perf_keyword(text).core:
            assert perf_norm(token) == token


def test_gt02_perf_norm():
    assert perf_norm(" A I  챗봇\n구축 ") == "ai챗봇구축"
    assert perf_norm(unicodedata.normalize("NFD", "홈 페이지")) == "홈페이지"
    # norm_compact(GT-01)는 casefold하지 않는다 — 재분류·확인 키 불변
    assert norm_compact("AI 챗봇") == "AI챗봇"


# T2: perf_variants·상수

# 챗봇 동의어 그룹(GT-02 기존 3개 + 설계 2.3 추가 7개, perf_norm 형태)
CHATBOT_GROUP = (
    "챗봇", "chatbot", "대화형봇",
    "대화형", "에이전트", "ai에이전트", "rag", "민원응대", "상담봇",
)  # fmt: skip


def test_gt02_t2_perf_variants_group_or_self():
    for group in PERF_SYNONYMS:
        for token in group:
            assert perf_variants(token) == group
    # 설계 2026-10-25-past-performance-capability 2.3: 챗봇에 에이전트 계열 추가.
    # "웹"·"질의응답"은 지식 텍스트에서 과잉 일치(웹 표준·발표평가 질의응답)해 제외했다.
    assert perf_variants("누리집") == frozenset(
        {"홈페이지", "누리집", "웹사이트", "웹페이지", "홈피", "포털"}
    )
    assert perf_variants("chatbot") == frozenset(CHATBOT_GROUP)
    assert perf_variants("앱") == frozenset({"모바일앱", "앱", "어플리케이션", "애플리케이션"})
    assert perf_variants("학교") == frozenset({"학교"})
    assert perf_variants("ai") == frozenset({"ai"})


def test_gt02_t2_synonym_groups_disjoint_and_normalized():
    groups = list(PERF_SYNONYMS)
    assert len(groups) == 3
    for i, a in enumerate(groups):
        for b in groups[i + 1 :]:
            assert not (a & b)
    for group in groups:
        assert isinstance(group, frozenset)
        for token in group:
            assert perf_norm(token) == token


def test_gt02_t2_type_token_values_are_project_types():
    for token, allowed in PERF_TYPE_TOKENS.items():
        assert isinstance(allowed, frozenset), token
        assert allowed and allowed <= _PROJECT_TYPES, token
        assert perf_norm(token) == token


def test_gt02_t2_constant_defaults():
    assert PERF_STOPWORDS == frozenset(
        {
            "기업", "기관", "공공기관", "공공", "민간", "사업", "용역", "실적", "수행",
            "수행실적", "구축실적", "등", "관련", "분야", "최근", "이내", "이상", "년",
            "보유", "업체", "경험", "유사", "동종", "동일", "및", "또는",
        }
    )  # fmt: skip
    for word in PERF_STOPWORDS:
        assert perf_norm(word) == word
    build, rebuild, maintain = (
        frozenset({"구축", "개발"}),
        frozenset({"구축", "고도화"}),
        frozenset({"유지관리", "운영"}),
    )
    assert PERF_TYPE_TOKENS == {
        "구축": build, "개발": build, "신규": build,
        "고도화": frozenset({"고도화"}),
        "개편": rebuild, "리뉴얼": rebuild,
        "유지관리": maintain, "유지보수": maintain,
        "운영": maintain, "위탁운영": maintain,
        "컨설팅": frozenset({"컨설팅"}),
        "물품": frozenset({"물품"}), "구입": frozenset({"물품"}), "납품": frozenset({"물품"}),
    }  # fmt: skip
    # 고도화는 구축 실적에 포함하지 않는다(보수적 기본값)
    assert "고도화" not in PERF_TYPE_TOKENS["구축"]
    assert PERF_SYNONYMS == (
        frozenset({"홈페이지", "누리집", "웹사이트", "웹페이지", "홈피", "포털"}),
        frozenset(CHATBOT_GROUP),
        frozenset({"모바일앱", "앱", "어플리케이션", "애플리케이션"}),
    )


# T3: keyword_match


def _pitem(**kwargs):
    return make_profile(portfolio=[portfolio_item("P2025-01", **kwargs)]).portfolio[0]


def test_gt02_t3_synonym_title_with_matching_type():
    item = _pitem(title="OO 누리집 개편", type="구축")
    assert keyword_match(item, parse_perf_keyword("홈페이지 구축")) == "match"


def test_gt02_t3_domain_only_with_wrong_type_is_no():
    item = _pitem(title="2025년 민원 홈서비스 용역", domain=["홈페이지 유지관리"], type="유지관리")
    assert keyword_match(item, parse_perf_keyword("홈페이지 구축")) == "no"


def test_gt02_t3_type_unknown():
    item = _pitem(title="OO 홈페이지 구축")  # type 기본 unknown
    assert item.type == "unknown"
    assert keyword_match(item, parse_perf_keyword("홈페이지 구축")) == "type_unknown"


def test_gt02_t3_all_core_tokens_required():
    item = _pitem(title="OO기관 홈페이지 구축", type="구축")
    assert keyword_match(item, parse_perf_keyword("학교 홈페이지")) == "no"
    # 핵심 토큰 불일치면 유형이 unknown이어도 no(핵심 대조가 먼저)
    unknown = _pitem(title="OO기관 홈페이지 구축")
    assert keyword_match(unknown, parse_perf_keyword("학교 홈페이지 구축")) == "no"


def test_gt02_t3_tokens_may_match_different_fields():
    item = _pitem(title="민원 챗봇 구축", domain=["AI", "상담"], type="구축")
    assert keyword_match(item, parse_perf_keyword("AI 챗봇 구축")) == "match"


def test_gt02_t3_no_type_tokens_means_no_type_filter():
    kw = parse_perf_keyword("홈페이지")
    for project_type in [*sorted(_PROJECT_TYPES), "unknown"]:
        item = _pitem(title="OO 홈페이지 운영", type=project_type)
        assert keyword_match(item, kw) == "match", project_type


def test_gt02_t3_empty_core_and_no_types_matches_everything():
    kw = parse_perf_keyword("수행 실적")
    assert keyword_match(_pitem(title="관계없는 사업", type="유지관리"), kw) == "match"
    assert keyword_match(_pitem(title="관계없는 사업"), kw) == "match"


def test_gt02_t3_empty_core_with_types_filters_by_type_only():
    kw = parse_perf_keyword("구축 실적")
    assert kw.core == ()
    assert keyword_match(_pitem(title="아무 사업", type="개발"), kw) == "match"
    assert keyword_match(_pitem(title="아무 사업", type="고도화"), kw) == "no"
    assert keyword_match(_pitem(title="아무 사업"), kw) == "type_unknown"


def test_gt02_t3_upgrade_not_counted_as_build():
    item = _pitem(title="OO 홈페이지 고도화", type="고도화")
    assert keyword_match(item, parse_perf_keyword("홈페이지 구축")) == "no"
    assert keyword_match(item, parse_perf_keyword("홈페이지 개편")) == "match"


def test_gt02_t3_short_variant_matches_field():
    # keyword 토큰 "모바일앱"의 변형 "앱"(길이 제한 없음)이 title에 맞는다
    item = _pitem(title="OO 앱 개발", type="개발")
    assert keyword_match(item, parse_perf_keyword("모바일앱 개발")) == "match"


def test_gt02_t3_fields_normalized_space_case_nfc():
    item = _pitem(title="합성 실적", domain=["홈 페이지", "ChatBot"], type="구축")
    assert keyword_match(item, parse_perf_keyword("홈페이지")) == "match"
    assert keyword_match(item, parse_perf_keyword("챗봇 구축")) == "match"
    nfd = _pitem(title=unicodedata.normalize("NFD", "OO 누리집 구축"), type="구축")
    assert keyword_match(nfd, parse_perf_keyword("홈페이지 구축")) == "match"


def test_gt02_t3_keyword_match_is_pure():
    item = _pitem(title="OO 누리집 개편", type="구축")
    kw = parse_perf_keyword("홈페이지 구축")
    before = (item.model_dump(), kw)
    assert keyword_match(item, kw) == keyword_match(item, kw) == "match"
    assert (item.model_dump(), kw) == before


# --- GT-02 T4: _performance_rule 분기와 company_value 접미 ---
# AS_OF 2026-11-05, 비창업(NON_STARTUP), years 3 → 창 2023-11-05~2026-11-05.

PERF_CV_PREFIX = "창=2023-11-05~2026-11-05; 창업특례=아니오; "
BUILD_SUFFIX = "; 키워드=[홈페이지]; 유형=[구축, 개발]"


def test_gt02_t4_type_mismatch_is_excluded():
    item = done(
        "P2025-15",
        "2025-12",
        100,
        title="민원 홈서비스 유지관리 용역",
        domain=["홈페이지 유지관리"],
        type="유지관리",
    )
    g = perf([item], years=3, keyword="홈페이지 구축")
    assert_fail(g)
    assert g.company_value == (
        PERF_CV_PREFIX + "확정후보=0; 금액확인합계=0; 금액미확인=0; 불확실=0" + BUILD_SUFFIX
    )


def test_gt02_t4_matching_type_is_confirmed_with_suffix():
    item = done("P2025-01", "2026-04", 100, title="OO재단 홈페이지 통합 구축", type="구축")
    g = perf([item], years=3, keyword="홈페이지 구축")
    assert_pass(g)
    assert g.unknown_fields == []
    assert g.company_value == (
        PERF_CV_PREFIX + "확정후보=1; 금액확인합계=100; 금액미확인=0; 불확실=0" + BUILD_SUFFIX
    )


def test_gt02_t4_type_unknown_in_confirmed_slot_is_uncertain():
    item = done("P2025-11", "2025-10", 100, title="OO 누리집 개편")  # type unknown
    g = perf([item], years=3, keyword="홈페이지 구축")
    assert_unknown_hint(g, "portfolio[P2025-11].type")
    assert g.action == "확인 필요: " + hint_for("portfolio[*].type")
    # 불확실 후보의 금액은 합계에 넣지 않는다(확정 후보가 아니므로)
    assert g.company_value == (
        PERF_CV_PREFIX + "확정후보=0; 금액확인합계=0; 금액미확인=0; 불확실=1" + BUILD_SUFFIX
    )


def test_gt02_t4_confirmed_plus_type_unknown_passes_with_type_path():
    items = [
        done("P2025-01", "2026-04", 139500000, title="OO 홈페이지 구축", type="구축"),
        done("P2025-11", "2025-10", 100, title="OO 누리집 개편"),
    ]
    g = perf(items, years=3, keyword="홈페이지 구축")
    assert_pass(g)
    assert g.unknown_fields == ["portfolio[P2025-11].type"]
    assert g.company_value == (
        PERF_CV_PREFIX + "확정후보=1; 금액확인합계=139500000; 금액미확인=0; 불확실=1" + BUILD_SUFFIX
    )


def test_gt02_t4_amount_required_type_unknown_orders_type_then_amount():
    item = done("P2025-11", "2025-10", "unknown", title="OO 누리집 개편")
    g = perf([item], years=3, keyword="홈페이지 구축", amount_krw=300)
    assert_unknown_hint(g, "portfolio[P2025-11].type", "portfolio[P2025-11].amount_krw")
    assert "확정후보=0; 금액확인합계=0; 금액미확인=0; 불확실=1" in g.company_value
    # 금액이 확인돼도 type unknown 후보는 합계에 들지 않아 UNKNOWN(FAIL로 단정하지 않음)
    item = done("P2025-11", "2025-10", 900, title="OO 누리집 개편")
    g = perf([item], years=3, keyword="홈페이지 구축", amount_krw=300)
    assert_unknown_hint(g, "portfolio[P2025-11].type")
    assert "금액확인합계=0;" in g.company_value


def test_gt02_t4_amount_paths_omitted_without_required_amount():
    item = done("P2025-11", "2025-10", "unknown", role="unknown", title="OO 누리집 개편")
    g = perf([item], years=3, keyword="홈페이지 구축")
    assert_unknown_hint(g, "portfolio[P2025-11].type")


def test_gt02_t4_already_uncertain_appends_type_after_existing_paths():
    item = portfolio_item("P2025-11", title="OO 누리집 개편", period_end="2025-10", amount_krw=100)
    g = perf([item], years=3, keyword="홈페이지 구축")
    assert_unknown_hint(g, "portfolio[P2025-11].completed", "portfolio[P2025-11].type")
    assert "확정후보=0; 금액확인합계=0; 금액미확인=0; 불확실=1" in g.company_value  # 1번만 센다
    # 순서 고정: completed → period.end → type → 금액 경로
    item = portfolio_item("P2025-12", title="OO 누리집 개편", role="주사업자")
    g = perf([item], years=3, keyword="홈페이지 구축", amount_krw=300)
    assert_unknown_hint(
        g,
        "portfolio[P2025-12].completed",
        "portfolio[P2025-12].period.end",
        "portfolio[P2025-12].type",
        "portfolio[P2025-12].amount_krw",
    )
    assert "불확실=1" in g.company_value
    g = perf([done("P2025-13", "unknown", 100, title="OO 누리집")], years=3, keyword="누리집 구축")
    assert_unknown_hint(g, "portfolio[P2025-13].period.end", "portfolio[P2025-13].type")


def test_gt02_t4_type_unknown_outside_window_or_not_completed_is_excluded():
    items = [
        done("P2020-01", "2020-06", 100, title="OO 홈페이지 구축"),  # 창 밖
        portfolio_item("P2025-02", title="OO 홈페이지 구축", period_end="2025-06", completed=False),
    ]
    g = perf(items, years=3, keyword="홈페이지 구축")
    assert_fail(g)
    assert "확정후보=0; 금액확인합계=0; 금액미확인=0; 불확실=0" in g.company_value


@pytest.mark.parametrize("keyword", ["수행 실적", "유사 용역 수행 실적", "1억원 이상", "3년간"])
def test_gt02_t4_unparseable_keyword_makes_no_candidates(keyword):
    """keyword 문자열이 있는데 핵심 토큰·유형이 모두 지워지면 후보를 만들지 않는다(리뷰
    2026-10-23: 모든 실적을 후보로 보던 근거 없는 PASS 수정)."""
    items = [
        done("P2024-01", "2024-06", 100, title="관계없는 사업", type="유지관리"),
        done("P2024-02", "2024-07", 200, title="다른 사업"),
    ]
    g = perf(items, years=3, keyword=keyword)
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == []
    assert g.action == "실적 목록 확인"
    assert g.company_value == (
        PERF_CV_PREFIX + "확정후보=0; 금액확인합계=0; 금액미확인=0; 불확실=0; 키워드=[-]; 유형=[-]"
    )
    # 금액 요구가 있어도 같은 UNKNOWN(FAIL·PASS로 단정하지 않음)
    g = perf(items, years=3, keyword=keyword, amount_krw=100)
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == []
    assert g.action == "실적 목록 확인"


def test_gt02_t4_unparseable_keyword_keeps_startup_path():
    # 후보가 없어도 창업특례 미상 경로는 기존 "확정후보=0" 경로처럼 남긴다
    items = [done("P2024-01", "2024-06", 100, title="관계없는 사업", type="구축")]
    g = perf(items, founded=None, years=3, keyword="수행 실적")
    assert g.verdict == "UNKNOWN"
    assert g.unknown_fields == ["company.founded"]
    assert "확정후보=0;" in g.company_value


def test_gt02_t4_types_without_core_shows_dash_keyword():
    g = perf([done("P2024-01", "2024-06", 100, type="개발")], years=3, keyword="구축 실적")
    assert_pass(g)
    assert g.company_value.endswith("; 불확실=0; 키워드=[-]; 유형=[구축, 개발]")


def test_gt02_t4_core_without_types_shows_dash_types():
    g = perf([done("P2024-01", "2024-06", 100, title="민원 챗봇")], years=3, keyword="AI 챗봇")
    assert_fail(g)  # 핵심 토큰 "ai"가 title/domain에 없음(AND), 목록은 confirmed
    assert g.company_value.endswith("; 불확실=0; 키워드=[ai, 챗봇]; 유형=[-]")


@pytest.mark.parametrize(
    ("keyword", "suffix"),
    [
        ("홈페이지 유지관리", "; 키워드=[홈페이지]; 유형=[유지관리, 운영]"),
        ("누리집 개편", "; 키워드=[누리집]; 유형=[구축, 고도화]"),
        ("운영 개발 홈페이지 홈페이지", "; 키워드=[홈페이지]; 유형=[구축, 유지관리, 운영, 개발]"),
        (
            "물품 컨설팅 개발 운영 고도화 구축",
            "; 키워드=[-]; 유형=[구축, 고도화, 유지관리, 운영, 개발, 컨설팅, 물품]",
        ),
    ],
)
def test_gt02_t4_suffix_types_follow_project_type_declaration_order(keyword, suffix):
    g = perf([], years=3, keyword=keyword)
    assert g.company_value.endswith(suffix)
    assert g.company_value.count("; 키워드=") == 1


@pytest.mark.parametrize("keyword", [None, "", "   "])
def test_gt02_t4_no_suffix_without_keyword_text(keyword):
    g = perf([done("P2024-01", "2024-06", 100)], years=3, keyword=keyword)
    assert_pass(g)
    assert g.company_value == (
        PERF_CV_PREFIX + "확정후보=1; 금액확인합계=100; 금액미확인=0; 불확실=0"
    )
