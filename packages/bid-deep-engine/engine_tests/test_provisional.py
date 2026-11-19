"""잠정 결론(PF-01) 단위 테스트. 네트워크·LLM 없이 합성 fixture만 쓴다.

T2: 가정 뷰(`ASSUMED_LEVELS`)의 수용 범위, 가정 목록 완전성(`list_complete`),
`evaluate_gates_traced`의 가정 목록 경로.
T16: `GATE_LABELS` 17개. 스키마(조건 id 유일성, 옛 Assessment JSON 로드).
T18(일부): provisional 유무가 stamp 해시 입력(readiness payload, recommendation 출력)에 영향 없음.
T3~T11, T15, T20, T12(일부): `compute_provisional`의 분기·조건 순서·문구·refs와
`assess_analysis` 연결.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import date
from typing import get_args

import pytest
from pydantic import ValidationError

from bid_deep_engine.analysis import gates as gates_module
from bid_deep_engine.analysis.gates import (
    _CompanyReader,
    _trusted_list_identifiers,
    evaluate_gates,
    evaluate_gates_traced,
)
from bid_deep_engine.analysis.labels import GATE_LABELS
from bid_deep_engine.analysis.provenance import (
    STAGE_VERSIONS,
    analysis_stage_output,
    field_ref,
    fit_ref,
    readiness_hash,
    readiness_payload,
    stage_output_hash,
    stage_ref,
)
from bid_deep_engine.analysis.review import _condition_hint, assess_analysis, compute_provisional
from bid_deep_engine.analysis.schemas import (
    CONDITION_KIND_ORDER,
    Assessment,
    ConditionKind,
    FitCoverage,
    GateCode,
    Provisional,
    ProvisionalCondition,
)
from bid_deep_engine.company.hints import DEFAULT_HINT, FIELD_HINTS
from bid_deep_engine.company.provenance import (
    ASSUMED_LEVELS,
    CompanyEvidenceView,
    ProvenanceDocument,
    resolve_profile_path,
    value_hash,
)
from bid_deep_engine.company.schema import UNKNOWN
from engine_tests.gate_factories import (
    confirmed_fixture_view,
    direct_production,
    make_facts,
    make_profile,
    portfolio_item,
    rule,
    staffing,
)
from engine_tests.report_factory import make_analysis, make_fit, make_gate
from engine_tests.report_factory import make_evidence as verified_evidence

AS_OF = date(2026, 11, 5)


def leveled_view(
    profile,
    levels: dict[str, str],
    *,
    stale: tuple[str, ...] = (),
    accepted_levels: frozenset[str] | None = None,
) -> CompanyEvidenceView:
    """경로별 출처 수준을 지정한 뷰. `stale` 경로는 값 해시가 현재 값과 다르다."""
    fields = {
        path: {
            "level": level,
            "sources": [{"kind": "user", "ref": "PF-01 T2 synthetic fixture"}],
            "value_hash": (
                "0" * 64 if path in stale else value_hash(resolve_profile_path(profile, path))
            ),
            "checked_at": None,
            "note": None,
        }
        for path, level in levels.items()
    }
    provenance = ProvenanceDocument.model_validate({"schema_version": 1, "fields": fields})
    view = CompanyEvidenceView(profile, provenance, ("경고",))
    return view if accepted_levels is None else view.with_accepted_levels(accepted_levels)


def assumed(profile, levels: dict[str, str], **kwargs) -> CompanyEvidenceView:
    return leveled_view(profile, levels, accepted_levels=ASSUMED_LEVELS, **kwargs)


def _portfolio_profile(**values):
    return make_profile(
        {"company.founded": "2010-01", **values},
        portfolio=[
            portfolio_item("P2020-01", title="홈페이지 유지관리", completed=True),
            portfolio_item("P2021-01", title="모바일앱 개발", completed=True),
        ],
    )


# --- 가정 뷰 수용 범위 ---


def test_t2_assumed_levels_constant_is_fixed():
    assert ASSUMED_LEVELS == frozenset({"confirmed", "demo", "public", "estimate"})


def test_t2_assumed_view_accepts_public_estimate_and_demo_but_not_unknown():
    profile = make_profile(
        {
            "company.size": "중소기업",
            "company.founded": "2010-01",
            "people.total_tech_staff": 10,
            "registrations.g2b.registered": True,
            "registrations.sw_business_report.reported": True,
        }
    )
    levels = {
        "company.size": "confirmed",
        "company.founded": "public",
        "people.total_tech_staff": "estimate",
        "registrations.g2b.registered": "demo",
        "registrations.sw_business_report.reported": "unknown",
    }
    view = assumed(profile, levels)

    assert view.accepted_levels == ASSUMED_LEVELS
    accepted = ("confirmed", "demo", "public", "estimate")
    assert [view.accepts(level) for level in accepted] == [True] * 4
    assert not view.accepts("unknown")
    assert view.decision_value("company.size") == "중소기업"
    assert view.decision_value("company.founded") == "2010-01"
    assert view.decision_value("people.total_tech_staff") == 10
    assert view.decision_value("registrations.g2b.registered") is True
    assert view.decision_value("registrations.sw_business_report.reported") == UNKNOWN
    # 출처 기록이 없는 원값은 가정 뷰에서도 쓰지 않는다.
    assert view.decision_value("company.name") == UNKNOWN

    stale = assumed(profile, {"company.founded": "public"}, stale=("company.founded",))
    assert stale.decision_value("company.founded") == UNKNOWN


def test_t2_with_accepted_levels_returns_new_view_sharing_inputs():
    profile = make_profile({"company.founded": "2010-01"})
    base = leveled_view(profile, {"company.founded": "public"})

    view = base.with_accepted_levels(ASSUMED_LEVELS)

    assert view is not base
    assert view.profile is base.profile
    assert view.provenance is base.provenance
    assert view.warnings == base.warnings == ("경고",)
    assert view.company_input_hash == base.company_input_hash
    assert base.accepted_levels == frozenset({"confirmed", "demo"})
    assert base.decision_value("company.founded") == UNKNOWN
    assert view.decision_value("company.founded") == "2010-01"


@pytest.mark.parametrize(
    "levels",
    [
        frozenset({"confirmed", "unknown"}),
        frozenset({"demo", "unknown"}),
        frozenset({"confirmed", "demo", "public", "estimate", "unknown"}),
        frozenset({"guess"}),
    ],
)
def test_t2_no_view_accepts_unknown(levels):
    profile = make_profile()
    with pytest.raises(ValueError):
        CompanyEvidenceView(profile, accepted_levels=levels)
    with pytest.raises(ValueError):
        CompanyEvidenceView(profile).with_accepted_levels(levels)


@pytest.mark.parametrize(
    "levels",
    [frozenset({"confirmed", "demo"}), frozenset({"demo"}), ASSUMED_LEVELS],
)
def test_t2_views_may_accept_demo(levels):
    """demo는 판정 수준이라 뷰가 수용할 수 있다(2026-10-25). unknown만 거부한다."""
    profile = make_profile()
    assert CompanyEvidenceView(profile, accepted_levels=levels).accepts("demo")
    assert CompanyEvidenceView(profile).with_accepted_levels(levels).accepts("demo")


def test_t2_assumed_reader_value_optional_present_and_trusted_ids():
    profile = make_profile(
        {
            "company.size": "중소기업",
            "registrations.venture": {"type": "기술평가보증", "since": "2020-01"},
            "registrations.innobiz": {"since": "2020-01"},
            "registrations.iso": [{"std": "9001"}, {"std": "27001"}],
        }
    )
    view = assumed(
        profile,
        {
            "company.size": "public",
            "registrations.venture.type": "estimate",
            "registrations.innobiz.since": "demo",
            "registrations.iso[9001]": "public",
            "registrations.iso[27001]": "demo",
        },
    )
    reader = _CompanyReader(view)

    assert reader.value("company.size") == "중소기업"
    assert reader.optional_present("registrations.venture", ("type", "since", "valid_until")) == (
        True,
        [],
    )
    # demo 잎도 확인값과 같이 존재 근거가 된다.
    assert reader.optional_present("registrations.innobiz", ("since", "valid_until")) == (
        True,
        [],
    )
    assert _trusted_list_identifiers(
        reader, "registrations.iso", profile.registrations.iso, "std"
    ) == (["9001", "27001"], ["registrations.iso"])

    id_view = assumed(
        profile,
        {"registrations.iso[9001].std": "estimate", "registrations.iso[27001].std": "demo"},
    )
    assert _trusted_list_identifiers(
        _CompanyReader(id_view), "registrations.iso", profile.registrations.iso, "std"
    ) == (["9001", "27001"], ["registrations.iso"])

    # unknown 수준은 가정 뷰에서도 존재·식별 근거가 아니다.
    unknown_view = assumed(
        profile,
        {"registrations.innobiz.since": "unknown", "registrations.iso[27001]": "unknown"},
    )
    unknown_reader = _CompanyReader(unknown_view)
    assert unknown_reader.optional_present("registrations.innobiz", ("since", "valid_until")) == (
        UNKNOWN,
        ["registrations.innobiz.since"],
    )
    assert _trusted_list_identifiers(
        unknown_reader, "registrations.iso", profile.registrations.iso, "std"
    ) == ([], ["registrations.iso"])


# --- 가정 목록 완전성 ---


@pytest.mark.parametrize("level", ["public", "estimate"])
def test_t2_list_complete_assumes_list_with_public_or_estimate_item(level):
    profile = _portfolio_profile()
    view = assumed(
        profile,
        {"portfolio[P2020-01].title": "confirmed", "portfolio[P2021-01].completed": level},
    )
    reader = _CompanyReader(view)

    assert reader.list_complete("portfolio") is True
    assert reader.list_complete("portfolio") is True
    assert reader.assumed_lists == ["portfolio"]
    # 항목 출처 확인은 판정 입력으로 기록하지 않는다.
    assert reader.input_fields == ["portfolio", "portfolio"]


def test_t2_list_complete_accepts_item_path_entry_itself():
    profile = make_profile(
        direct_production=[direct_production("8111189901", status="valid")],
    )
    view = assumed(profile, {"registrations.direct_production[8111189901]": "public"})
    reader = _CompanyReader(view)

    assert reader.list_complete("registrations.direct_production") is True
    assert reader.assumed_lists == ["registrations.direct_production"]


def test_t2_list_with_only_confirmed_or_demo_items_is_not_assumed():
    profile = _portfolio_profile()
    view = assumed(
        profile,
        {"portfolio[P2020-01].title": "confirmed", "portfolio[P2021-01].title": "demo"},
    )
    reader = _CompanyReader(view)

    assert reader.list_complete("portfolio") is False
    assert reader.assumed_lists == []


@pytest.mark.parametrize(
    ("levels", "stale", "accepted"),
    [
        # 목록 경로 자체에 (수용되지 않는) 출처 항목이 있다.
        ({"portfolio": "unknown", "portfolio[P2020-01].title": "public"}, (), ASSUMED_LEVELS),
        # 항목의 public 출처가 현재 값과 맞지 않는다.
        ({"portfolio[P2020-01].title": "public"}, ("portfolio[P2020-01].title",), ASSUMED_LEVELS),
        # 기본 뷰는 목록을 가정하지 않는다.
        ({"portfolio[P2020-01].title": "public"}, (), None),
        # 항목 하위 출처가 없다(다른 경로에만 public이 있다).
        ({"company.founded": "public"}, (), ASSUMED_LEVELS),
    ],
)
def test_t2_list_complete_false_cases(levels, stale, accepted):
    profile = _portfolio_profile()
    view = leveled_view(profile, levels, stale=stale, accepted_levels=accepted)
    reader = _CompanyReader(view)

    assert reader.list_complete("portfolio") is False
    assert reader.assumed_lists == []


def test_t2_empty_list_is_not_assumed():
    profile = make_profile({"company.founded": "2010-01"}, portfolio=[])
    view = assumed(profile, {"company.founded": "public"})
    reader = _CompanyReader(view)

    assert reader.list_complete("portfolio") is False
    assert reader.assumed_lists == []


def test_t2_list_path_with_public_provenance_is_complete_without_assumption():
    profile = _portfolio_profile()
    view = assumed(profile, {"portfolio": "public"})
    reader = _CompanyReader(view)

    assert reader.list_complete("portfolio") is True
    assert reader.assumed_lists == []


@pytest.mark.parametrize("accepted", [None, ASSUMED_LEVELS])
def test_t2_list_path_with_demo_provenance_is_complete_in_every_view(accepted):
    """demo 목록 경로는 confirmed처럼 value()로 완전하다(기본·가정 뷰 모두, 가정 아님)."""
    profile = _portfolio_profile()
    view = leveled_view(
        profile,
        {"portfolio": "demo", "portfolio[P2020-01].title": "public"},
        accepted_levels=accepted,
    )
    reader = _CompanyReader(view)

    assert reader.list_complete("portfolio") is True
    assert reader.assumed_lists == []


# --- evaluate_gates_traced ---


def _public_portfolio_view(profile):
    levels = {"company.founded": "confirmed"}
    for item in ("P2020-01", "P2021-01"):
        for leaf in ("title", "domain", "completed"):
            levels[f"portfolio[{item}].{leaf}"] = "public"
    return levels


def test_t2_evaluate_gates_traced_reports_assumed_list_and_matches_evaluate_gates():
    profile = _portfolio_profile()
    levels = _public_portfolio_view(profile)
    facts = make_facts(
        submission_deadline="2026-11-05 10:00",
        eligibility=[
            rule("PAST_PERFORMANCE", "챗봇 구축 실적", keyword="챗봇 구축"),
            rule("PAST_PERFORMANCE", "드론 관제 실적", keyword="드론 관제"),
        ],
    )
    view = assumed(profile, levels)

    gates, assumed_paths = evaluate_gates_traced(
        facts, view.profile, as_of=AS_OF, evidence_view=view
    )

    assert [g.verdict for g in gates] == ["FAIL", "FAIL"]
    assert all("portfolio" in g.input_fields for g in gates)
    assert assumed_paths == ("portfolio",)
    plain = evaluate_gates(facts, view.profile, as_of=AS_OF, evidence_view=view)
    assert [g.model_dump_json() for g in plain] == [g.model_dump_json() for g in gates]

    default_view = leveled_view(profile, levels)
    default_gates, default_assumed = evaluate_gates_traced(
        facts, default_view.profile, as_of=AS_OF, evidence_view=default_view
    )
    assert [g.verdict for g in default_gates] == ["UNKNOWN", "UNKNOWN"]
    assert all("portfolio" in g.unknown_fields for g in default_gates)
    assert default_assumed == ()


def test_t2_evaluate_gates_traced_without_assumable_list_is_empty():
    profile = _portfolio_profile()
    levels = {
        path: ("demo" if path.startswith("portfolio[") else level)
        for path, level in _public_portfolio_view(profile).items()
    }
    facts = make_facts(
        submission_deadline="2026-11-05 10:00",
        eligibility=[rule("PAST_PERFORMANCE", "챗봇 구축 실적", keyword="챗봇 구축")],
    )
    view = assumed(profile, levels)

    gates, assumed_paths = evaluate_gates_traced(
        facts, view.profile, as_of=AS_OF, evidence_view=view
    )

    assert gates[0].verdict == "UNKNOWN"
    assert assumed_paths == ()


# --- T16: 게이트 라벨 ---


def test_t16_gate_labels_cover_all_17_gate_codes():
    codes = set(get_args(GateCode))
    assert len(codes) == 17
    assert set(GATE_LABELS) == codes
    assert all(isinstance(label, str) and label for label in GATE_LABELS.values())
    assert len(set(GATE_LABELS.values())) == 17
    assert GATE_LABELS["G2B_REGISTERED"] == "나라장터 입찰참가자격 등록"
    assert GATE_LABELS["OTHER"] == "원문 확인이 필요한 참가자격"
    assert GATE_LABELS["INSOLVENCY"] == "부도·회생"


# --- 스키마 ---


def _condition(kind: ConditionKind = "unknown_gate", target: str = "SME_CERT"):
    return ProvisionalCondition(
        id=f"{kind}:{target}",
        kind=kind,
        title="중소기업·소상공인 확인서",
        check="중소기업 확인서 확인",
        if_not="충족하지 못하면 참가 불가",
    )


def _provisional(conditions):
    return Provisional(
        decision="CONDITIONAL_GO",
        basis="assumed",
        conditions=conditions,
        fit_coverage=FitCoverage(judged=2, total=3),
        fit_base=75,
        assumed_fields=["a.b", "c.d"],
    )


def test_condition_kind_order_is_fixed_and_matches_literal():
    assert CONDITION_KIND_ORDER == (
        "recheck_fail",
        "risk_gate",
        "unknown_gate",
        "requirements_missing",
        "fit_coverage",
        "pdf_numeric",
        "stale_analysis",
    )
    assert set(CONDITION_KIND_ORDER) == set(get_args(ConditionKind))


def test_provisional_condition_defaults_and_roundtrip():
    condition = _condition()
    assert condition.gate_codes == []
    assert condition.company_fields == []
    assert condition.refs == []
    provisional = _provisional([condition, _condition("risk_gate", "ONSITE_LOCATION")])
    assert Provisional.model_validate_json(provisional.model_dump_json()) == provisional


def test_provisional_rejects_duplicate_condition_ids():
    with pytest.raises(ValidationError, match="unique"):
        _provisional([_condition(), _condition()])


def test_provisional_allows_same_target_with_different_kind():
    provisional = _provisional([_condition("unknown_gate"), _condition("risk_gate")])
    assert [c.id for c in provisional.conditions] == [
        "unknown_gate:SME_CERT",
        "risk_gate:SME_CERT",
    ]


def test_provisional_rejects_unknown_kind_and_gate_code():
    with pytest.raises(ValidationError):
        ProvisionalCondition(id="x:y", kind="nope", title="t", check="c", if_not="i")
    with pytest.raises(ValidationError):
        ProvisionalCondition(
            id="unknown_gate:X",
            kind="unknown_gate",
            title="t",
            check="c",
            if_not="i",
            gate_codes=["NOT_A_GATE"],
        )


def test_legacy_assessment_json_without_provisional_loads_as_none():
    legacy = {
        "state": "ready",
        "decision": "GO",
        "reason_codes": ["stale_stage", "missing_fits"],
        "score_interval": {"min": 60, "max": 80},
    }
    assessment = Assessment.model_validate_json(json.dumps(legacy))
    assert assessment.provisional is None
    assert assessment.reason_codes == ["missing_fits", "stale_stage"] or set(
        assessment.reason_codes
    ) == {"stale_stage", "missing_fits"}


def test_assessment_keeps_state_decision_validator_with_provisional():
    with pytest.raises(ValidationError):
        Assessment(
            state="ready",
            decision=None,
            reason_codes=[],
            score_interval=None,
            provisional=_provisional([]),
        )


def test_legacy_analysis_json_without_provisional_loads():
    analysis = make_analysis(
        assessment=Assessment(
            state="abstain", decision=None, reason_codes=["stale_stage"], score_interval=None
        )
    )
    data = json.loads(analysis.model_dump_json())
    data["assessment"].pop("provisional")
    loaded = type(analysis).model_validate(data)
    assert loaded.assessment is not None
    assert loaded.assessment.provisional is None


# --- T18(일부): stamp 해시에서 provisional 제외 ---

_STATES = {
    "facts": "current",
    "gates": "current",
    "scores": "current",
    "fits": "current",
    "synth": "current",
    "requests": "current",
    "recommendation": "current",
}


def _assessment(provisional):
    return Assessment(
        state="abstain",
        decision=None,
        reason_codes=["stale_stage"],
        score_interval=None,
        provisional=provisional,
    )


def test_provisional_demo_fields_default_and_stamp_exclusion():
    """demo_fields는 기본 빈 목록이라 이전 산출물 JSON도 읽히고, provisional과 함께 stamp 해시에서
    빠진다."""
    legacy = _provisional([_condition()]).model_dump(mode="json")
    legacy.pop("demo_fields")
    assert Provisional.model_validate(legacy).demo_fields == []

    reasons = [
        {"code": "stale_stage", "stage": "facts", "refs": ["stage:facts"], "message": "이전 입력"}
    ]
    demo = _provisional([_condition()]).model_copy(
        update={"demo_fields": ["registrations.g2b.registered"]}
    )
    assert readiness_hash(_assessment(demo), reasons, _STATES) == readiness_hash(
        _assessment(None), reasons, _STATES
    )


def test_t18_readiness_payload_and_hash_ignore_provisional():
    reasons = [
        {"code": "stale_stage", "stage": "facts", "refs": ["stage:facts"], "message": "이전 입력"}
    ]
    without = _assessment(None)
    with_prov = _assessment(_provisional([_condition()]))

    payload = readiness_payload(with_prov, reasons, _STATES)
    assert "provisional" not in payload["assessment"]
    assert payload == readiness_payload(without, reasons, _STATES)
    assert readiness_hash(with_prov, reasons, _STATES) == readiness_hash(without, reasons, _STATES)
    # 저장 직렬화에는 provisional이 남는다.
    assert with_prov.model_dump(mode="json")["provisional"] is not None


def test_t18_recommendation_output_hash_ignores_provisional():
    base = make_analysis(assessment=_assessment(None))
    with_prov = base.model_copy(update={"assessment": _assessment(_provisional([_condition()]))})

    out_base = analysis_stage_output(base, "recommendation")
    out_prov = analysis_stage_output(with_prov, "recommendation")
    assert "provisional" not in out_prov["assessment"]
    assert out_prov == out_base
    assert stage_output_hash("recommendation", out_prov) == stage_output_hash(
        "recommendation", out_base
    )


def test_t18_recommendation_stage_version_is_v2():
    assert STAGE_VERSIONS["recommendation"] == "recommendation-v2"


# --- STEP-003: 잠정 결론 계산(compute_provisional) ---

CURRENT_STATES = {
    "facts": "current",
    "gates": "current",
    "scores": "current",
    "fits": "current",
    "synth": "current",
    "requests": "unknown",
    "recommendation": "unknown",
}
DEADLINE = "2026-11-05 10:00"
VERIFIED = verified_evidence()
_ALL_FITS = object()


def _facts(*rules, staff=(), budget_krw=None):
    return make_facts(
        submission_deadline=DEADLINE,
        eligibility=list(rules),
        staffing=list(staff),
        budget_krw=budget_krw,
    )


def _registered_rule():
    return rule("G2B_REGISTERED", "나라장터 등록", evidence=VERIFIED)


def _registered_view():
    return confirmed_fixture_view(make_profile({"registrations.g2b.registered": True}))


def _fits(*values):
    return [make_fit(f"SFR-{index:03d}", value) for index, value in enumerate(values, 1)]


def _states(**overrides):
    return {**CURRENT_STATES, **overrides}


def _analysis_for(facts, fits=("FULL",), *, numeric=False, gates=()):
    return make_analysis(
        facts=facts,
        gates=list(gates),
        fits=_fits(*fits),
        numeric_facts_unconfirmed=numeric,
    )


def _provisional_of(
    facts,
    company,
    fits=("FULL",),
    *,
    requirement_ids=_ALL_FITS,
    states=None,
    numeric=False,
    resolve_gates=None,
):
    analysis = _analysis_for(facts, fits, numeric=numeric)
    ids = (
        [item.req_id for item in analysis.fits] if requirement_ids is _ALL_FITS else requirement_ids
    )
    return compute_provisional(
        analysis,
        CURRENT_STATES if states is None else states,
        ids,
        company=company,
        now=AS_OF,
        resolve_gates=resolve_gates,
    )


def _ids(provisional):
    return [condition.id for condition in provisional.conditions]


# --- T3: 공개 실적만으로 미충족 → 잠정 포기 + 재확인 조건 ---


def _t3_inputs(*keywords):
    profile = _portfolio_profile()
    facts = _facts(
        *(
            rule("PAST_PERFORMANCE", f"{keyword} 실적", keyword=keyword, evidence=VERIFIED)
            for keyword in keywords
        )
    )
    levels = _public_portfolio_view(profile)
    return facts, levels, leveled_view(profile, levels)


def test_t3_public_portfolio_without_match_is_no_go_with_recheck_condition():
    facts, levels, company = _t3_inputs("챗봇 구축")
    analysis = _analysis_for(facts)
    before = analysis.model_dump_json()

    provisional = compute_provisional(
        analysis, CURRENT_STATES, ["SFR-001"], company=company, now=AS_OF
    )

    assert provisional.decision == "NO_GO"
    assert _ids(provisional) == ["recheck_fail:PAST_PERFORMANCE"]
    assert provisional.basis == "assumed"
    [condition] = provisional.conditions
    assert condition.kind == "recheck_fail"
    assert condition.title == "수행 실적 미충족(재확인 필요)"
    # 필드별 확인처(PF-02 실적 필드 힌트) + 확인처가 없는 맨 portfolio 경로의 기본 문구
    assert condition.check == (
        "실적증명서의 준공·완료일 / 실적증명서·계약서의 사업명"
        " / 사업 분야(실적증명서·과업지시서 기준) / 회사 기록 확인"
    )
    assert condition.if_not == "현재 기록·원문 기준 참가 불가 — 증빙이 있으면 재검토"
    assert condition.gate_codes == ["PAST_PERFORMANCE"]
    assert "portfolio" in condition.company_fields
    assert len(condition.company_fields) == len(set(condition.company_fields))
    assert condition.refs[0].startswith("gate:PAST_PERFORMANCE:")
    assert condition.refs[1:] == [field_ref(path) for path in condition.company_fields]
    # 가정 목록과 public 입력 경로만 가정 값으로 기록한다.
    assert "portfolio" in provisional.assumed_fields
    assert provisional.assumed_fields == sorted(set(provisional.assumed_fields))
    assert all(
        path == "portfolio" or levels.get(path) == "public" for path in provisional.assumed_fields
    )
    # 적합도가 높아도 참가자격 미충족이 우선한다.
    assert provisional.fit_coverage == FitCoverage(judged=1, total=1)
    assert provisional.fit_base == 100
    # 저장된 게이트·확정 기준 게이트는 그대로다.
    assert analysis.model_dump_json() == before
    assert [g.verdict for g in evaluate_gates(facts, company, as_of=AS_OF)] == ["UNKNOWN"]


def test_t3_recheck_fail_groups_same_code_with_count_in_title():
    facts, _, company = _t3_inputs("챗봇 구축", "드론 관제")

    provisional = _provisional_of(facts, company)

    assert _ids(provisional) == ["recheck_fail:PAST_PERFORMANCE"]
    [condition] = provisional.conditions
    assert condition.title == "수행 실적 미충족(재확인 필요) (2건)"
    assert [ref.split(":")[0] for ref in condition.refs[:2]] == ["gate", "gate"]
    assert condition.refs[0] != condition.refs[1]


# --- T4: 확인된 입력의 신뢰 FAIL → 잠정 포기, 조건 없음 ---


def _industry_inputs(evidence=VERIFIED):
    facts = _facts(
        _registered_rule(),
        rule("INDUSTRY_CODE", "업종 1468", industry_code=["1468"], evidence=evidence),
    )
    profile = make_profile(
        {
            "registrations.g2b.registered": True,
            "registrations.g2b.industry_codes": ["9999"],
            "registrations.g2b.other_codes": [],
        }
    )
    return facts, confirmed_fixture_view(profile)


def test_t4_confirmed_trusted_fail_is_no_go_without_conditions():
    facts, company = _industry_inputs()
    assert [(g.code, g.verdict) for g in evaluate_gates(facts, company, as_of=AS_OF)] == [
        ("G2B_REGISTERED", "PASS"),
        ("INDUSTRY_CODE", "FAIL"),
    ]

    provisional = _provisional_of(facts, company)

    assert provisional.decision == "NO_GO"
    assert provisional.conditions == []
    assert provisional.basis == "confirmed"
    assert provisional.assumed_fields == []


def test_t4_unverified_quote_fail_needs_recheck_but_basis_stays_confirmed():
    facts, company = _industry_inputs(verified_evidence(verified=False))

    provisional = _provisional_of(facts, company)

    assert provisional.decision == "NO_GO"
    assert _ids(provisional) == ["recheck_fail:INDUSTRY_CODE"]
    assert provisional.conditions[0].title == "업종코드 미충족(재확인 필요)"
    assert provisional.conditions[0].check == "증빙 서류와 원문 조항 확인"
    assert provisional.conditions[0].company_fields == []
    assert provisional.basis == "confirmed"


def test_t4_no_go_keeps_only_recheck_conditions():
    facts, company = _industry_inputs(verified_evidence(verified=False))
    facts.eligibility.append(rule("SME_CERT", "중소기업 확인서", evidence=VERIFIED))

    provisional = _provisional_of(
        facts,
        company,
        fits=("UNKNOWN",),
        requirement_ids=[],
        numeric=True,
        states=_states(facts="stale", fits="stale"),
    )

    assert provisional.decision == "NO_GO"
    assert _ids(provisional) == ["recheck_fail:INDUSTRY_CODE"]


def test_t4_human_confirmed_fail_is_rechecked_through_resolver():
    facts, company = _industry_inputs()

    def human_fail(gates):
        return [
            gate.model_copy(
                update={"company_value": "사람 확인 FAIL: 업종 미등록 (담당자, 2026-10-25)"}
            )
            if gate.code == "INDUSTRY_CODE"
            else gate
            for gate in gates
        ]

    provisional = _provisional_of(facts, company, resolve_gates=human_fail)

    assert provisional.decision == "NO_GO"
    assert _ids(provisional) == ["recheck_fail:INDUSTRY_CODE"]


def test_t4_trusted_min_contract_is_no_go_without_conditions():
    profile = make_profile(
        {"registrations.g2b.registered": True, "policy.min_contract_amount_krw": 200}
    )
    company = confirmed_fixture_view(profile)
    facts = _facts(_registered_rule(), budget_krw=100)
    facts.project.evidence = [verified_evidence("사업금액 100원")]

    provisional = _provisional_of(facts, company)

    assert (provisional.decision, provisional.conditions, provisional.basis) == (
        "NO_GO",
        [],
        "confirmed",
    )
    # 사업금액 사실이 현재가 아니면 최소계약 포기를 쓰지 않는다.
    stale = _provisional_of(facts, company, states=_states(facts="stale"))
    assert stale.decision == "CONDITIONAL_GO"
    assert _ids(stale) == ["stale_analysis:analysis"]


def test_resolver_is_applied_and_its_errors_propagate():
    facts = _facts(_registered_rule(), rule("SME_CERT", "중소기업 확인서", evidence=VERIFIED))
    company = _registered_view()
    assert _ids(_provisional_of(facts, company)) == ["unknown_gate:SME_CERT"]

    def human_pass(gates):
        return [
            gate.model_copy(
                update={
                    "verdict": "PASS",
                    "company_value": "사람 확인 PASS: 확인서 보유 (담당자, 2026-10-25)",
                    "unknown_fields": [],
                    "action": None,
                }
            )
            if gate.code == "SME_CERT"
            else gate
            for gate in gates
        ]

    resolved = _provisional_of(facts, company, resolve_gates=human_pass)
    assert (resolved.decision, resolved.conditions) == ("GO", [])

    def broken(gates):
        raise RuntimeError("confirmation failure")

    with pytest.raises(RuntimeError, match="confirmation failure"):
        _provisional_of(facts, company, resolve_gates=broken)


# --- T5: 위험·미확인 게이트 조건 순서와 묶음 ---


def _t5_facts():
    return _facts(
        rule("DIRECT_PRODUCTION", "직접생산확인", item_no=["8111189901"], evidence=VERIFIED),
        rule("SME_CERT", "중소기업 확인서", evidence=VERIFIED),
        rule("SME_CERT", "소상공인 확인서", evidence=VERIFIED),
        staff=[
            staffing("PM", count=1, resident=True, location="서울"),
            staffing("PL", count=1, resident=True, location="서울 중구"),
        ],
    )


def test_t5_risk_then_unknown_conditions_grouped_by_code():
    company = confirmed_fixture_view(make_profile({"company.founded": "2010-01"}))

    provisional = _provisional_of(_t5_facts(), company)

    assert _ids(provisional) == [
        "risk_gate:ONSITE_LOCATION",
        "unknown_gate:DIRECT_PRODUCTION",
        "unknown_gate:SME_CERT",
    ]
    assert provisional.decision == "CONDITIONAL_GO"
    assert provisional.basis == "confirmed"
    onsite, direct, sme = provisional.conditions
    assert onsite.title == "상주 근무 (2건)"
    assert onsite.check == "서울 상주 가능 인원 확인"
    assert onsite.if_not == "해결하지 못하면 포기 검토"
    assert onsite.gate_codes == ["ONSITE_LOCATION"]
    assert [ref.split(":")[0] for ref in onsite.refs[:2]] == ["gate", "gate"]
    assert onsite.refs[2:] == [field_ref(path) for path in onsite.company_fields]
    assert "policy.seoul_resident_ok" in onsite.company_fields
    assert direct.title == "직접생산확인"
    assert direct.check == "공공구매종합정보망(smpp) 직접생산확인증명서"
    assert direct.if_not == "충족하지 못하면 참가 불가"
    assert sme.title == "중소기업·소상공인 확인서 (2건)"
    assert sme.check == "중소기업현황정보시스템(sminfo) 중소기업확인서"
    assert sme.company_fields == ["registrations.sme_certificate.status"]


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("확인 필요: company/schema.md 참고", "원문 조건 확인"),
        ("people.onsite_capacity 확인", "원문 조건 확인"),
        (None, "원문 조건 확인"),
        ("부정당업자 제재 여부 조회 확인", "부정당업자 제재 여부 조회 확인"),
    ],
)
def test_risk_gate_check_uses_action_unless_it_exposes_paths(action, expected):
    risk = make_gate("DEBARMENT", "RISK", action=action)

    provisional = _provisional_of(
        _facts(_registered_rule()),
        _registered_view(),
        resolve_gates=lambda gates: [*gates, risk],
    )

    [condition] = provisional.conditions
    assert condition.id == "risk_gate:DEBARMENT"
    assert condition.title == "부정당업자 제재"
    assert condition.check == expected
    assert condition.if_not == "부담을 감수할 수 있는지 검토"
    assert condition.refs == ["stage:gates"]


@pytest.mark.parametrize("code", ["ONSITE_LOCATION", "STAFFING_CAPACITY"])
def test_risk_gate_onsite_and_staffing_suggest_giving_up(code):
    risk = make_gate(code, "RISK", action="자사 인력 투입 가능 여부 확인", evidence=[])

    provisional = _provisional_of(
        _facts(_registered_rule()),
        _registered_view(),
        resolve_gates=lambda gates: [*gates, risk],
    )

    assert provisional.conditions[0].if_not == "해결하지 못하면 포기 검토"


def test_unknown_gate_without_company_fields_asks_for_notice_clause():
    other = make_gate("OTHER", "UNKNOWN", action="원문 확인")

    provisional = _provisional_of(
        _facts(_registered_rule()),
        _registered_view(),
        resolve_gates=lambda gates: [*gates, other],
    )

    [condition] = provisional.conditions
    assert condition.id == "unknown_gate:OTHER"
    assert condition.title == "원문 확인이 필요한 참가자격"
    assert condition.check == "공고 원문 조항 확인"


# --- T6·T7: 요구사항 미분석과 판단 범위 ---


@pytest.mark.parametrize("requirement_ids", [[], None])
def test_t6_no_requirements_is_conditional_with_requirements_missing(requirement_ids):
    provisional = _provisional_of(
        _facts(_registered_rule()), _registered_view(), fits=(), requirement_ids=requirement_ids
    )

    assert provisional.decision == "CONDITIONAL_GO"
    assert _ids(provisional) == ["requirements_missing:requirements"]
    [condition] = provisional.conditions
    assert condition.title == "요구사항 미분석"
    assert condition.check == "과업 범위를 원문에서 직접 확인"
    assert condition.if_not == "역량 적합도를 판단할 수 없음"
    assert condition.refs == [stage_ref("fits")]
    assert (condition.gate_codes, condition.company_fields) == ([], [])
    assert provisional.fit_base is None
    assert provisional.fit_coverage == FitCoverage(judged=0, total=0)


def test_t7_fit_coverage_below_half_adds_condition_with_unjudged_refs():
    values = ["FULL"] * 8 + ["UNKNOWN"] * 33

    provisional = _provisional_of(_facts(_registered_rule()), _registered_view(), values)

    assert _ids(provisional) == ["fit_coverage:fits"]
    [condition] = provisional.conditions
    assert condition.title == "요구사항 역량 판단 부족(33/41건)"
    assert condition.check == "회사 역량·실적 기록 보강"
    assert condition.if_not == "보강 후 재분석하면 결론이 바뀔 수 있음"
    assert condition.refs == [fit_ref(f"SFR-{index:03d}") for index in range(9, 42)]
    assert provisional.fit_coverage == FitCoverage(judged=8, total=41)
    assert provisional.fit_base == 100
    assert provisional.decision == "CONDITIONAL_GO"


def test_t7_half_judged_has_no_coverage_condition():
    half = _provisional_of(
        _facts(_registered_rule()), _registered_view(), ["FULL"] * 10 + ["UNKNOWN"] * 10
    )
    assert half.conditions == []
    assert half.fit_coverage == FitCoverage(judged=10, total=20)
    assert half.decision == "GO"

    below = _provisional_of(
        _facts(_registered_rule()), _registered_view(), ["FULL"] * 9 + ["UNKNOWN"] * 11
    )
    assert [c.title for c in below.conditions] == ["요구사항 역량 판단 부족(11/20건)"]


def test_t7_requirement_without_fit_row_counts_as_unjudged():
    provisional = _provisional_of(
        _facts(_registered_rule()),
        _registered_view(),
        ("FULL",),
        requirement_ids=["SFR-003", "SFR-001", "SFR-002"],
    )

    assert provisional.fit_coverage == FitCoverage(judged=1, total=3)
    [condition] = provisional.conditions
    assert condition.title == "요구사항 역량 판단 부족(2/3건)"
    assert condition.refs == [fit_ref("SFR-002"), fit_ref("SFR-003")]


# --- T8·T9: 조건 없을 때만 적합도로 결론 ---


@pytest.mark.parametrize(
    ("values", "fit_base", "decision"),
    [
        (["FULL", "PARTIAL"], 75, "GO"),
        (["PARTIAL"], 50, "CONDITIONAL_GO"),
        (["FULL", "GAP", "GAP", "GAP", "PARTIAL"], 30, "NO_GO"),
        (["FULL"] * 7 + ["GAP"] * 3, 70, "GO"),
        (["FULL", "FULL", "GAP", "GAP", "GAP"], 40, "CONDITIONAL_GO"),
        (["FULL", "PARTIAL", "GAP", "GAP"], 38, "NO_GO"),  # 37.5 → 38(round_half_up)
    ],
)
def test_t8_without_conditions_fit_base_decides(values, fit_base, decision):
    provisional = _provisional_of(_facts(_registered_rule()), _registered_view(), values)

    assert provisional.conditions == []
    assert provisional.fit_base == fit_base
    assert provisional.decision == decision
    assert provisional.basis == "confirmed"
    assert provisional.assumed_fields == []


def test_t9_condition_keeps_conditional_go_even_with_low_fit():
    values = ["FULL"] * 4 + ["PARTIAL"] + ["GAP"] * 10 + ["UNKNOWN"] * 10
    facts = _facts(_registered_rule(), rule("SME_CERT", "중소기업 확인서", evidence=VERIFIED))

    provisional = _provisional_of(facts, _registered_view(), values)

    assert provisional.fit_coverage == FitCoverage(judged=15, total=25)
    assert provisional.fit_base == 30
    assert _ids(provisional) == ["unknown_gate:SME_CERT"]
    assert provisional.decision == "CONDITIONAL_GO"


# --- T10·T11: pdf 숫자, 이전 기준 분석 ---


def test_t10_pdf_notice_adds_pdf_numeric_condition():
    provisional = _provisional_of(_facts(_registered_rule()), _registered_view(), numeric=True)

    assert _ids(provisional) == ["pdf_numeric:pdf"]
    [condition] = provisional.conditions
    assert condition.title == "pdf 원문 숫자 미확정"
    assert condition.check == "금액·기간을 hwp/hwpx 원문으로 확인"
    assert condition.if_not == "금액·기간이 다르면 재검토"
    assert condition.refs == [stage_ref("facts")]
    assert provisional.decision == "CONDITIONAL_GO"


def test_t10_pdf_past_performance_fail_is_rechecked_even_when_confirmed():
    profile = _portfolio_profile()
    company = confirmed_fixture_view(profile)
    facts = _facts(
        rule("PAST_PERFORMANCE", "챗봇 구축 실적", keyword="챗봇 구축", evidence=VERIFIED)
    )
    assert [g.verdict for g in evaluate_gates(facts, company, as_of=AS_OF)] == ["FAIL"]

    hwp = _provisional_of(facts, company)
    pdf = _provisional_of(facts, company, numeric=True)

    assert (hwp.decision, hwp.conditions, hwp.basis) == ("NO_GO", [], "confirmed")
    assert pdf.decision == "NO_GO"
    assert _ids(pdf) == ["recheck_fail:PAST_PERFORMANCE"]


@pytest.mark.parametrize(
    ("overrides", "stale"),
    [
        ({"fits": "stale"}, ["fits"]),
        ({"facts": "stale"}, ["facts"]),
        ({"facts": "unknown", "fits": "missing"}, ["facts", "fits"]),
    ],
)
def test_t11_non_current_facts_or_fits_adds_stale_analysis(overrides, stale):
    provisional = _provisional_of(
        _facts(_registered_rule()), _registered_view(), states=_states(**overrides)
    )

    assert _ids(provisional) == ["stale_analysis:analysis"]
    [condition] = provisional.conditions
    assert condition.title == "이전 기준 분석"
    assert condition.check == "분석 다시 실행"
    assert condition.if_not == "회사 기록 변경이 반영되지 않았을 수 있음"
    assert condition.refs == [stage_ref(stage) for stage in stale]
    assert provisional.decision == "CONDITIONAL_GO"


def test_t11_other_stage_states_do_not_add_stale_analysis():
    states = _states(gates="stale", scores="missing", synth="unknown", recommendation="stale")

    provisional = _provisional_of(_facts(_registered_rule()), _registered_view(), states=states)

    assert (provisional.decision, provisional.conditions) == ("GO", [])


@pytest.mark.parametrize(
    ("fits", "requirement_ids", "middle"),
    [
        (("UNKNOWN", "UNKNOWN", "FULL"), _ALL_FITS, "fit_coverage:fits"),
        ((), [], "requirements_missing:requirements"),
    ],
)
def test_conditions_follow_kind_order(fits, requirement_ids, middle):
    provisional = _provisional_of(
        _t5_facts(),
        confirmed_fixture_view(make_profile({"company.founded": "2010-01"})),
        fits,
        requirement_ids=requirement_ids,
        numeric=True,
        states=_states(fits="stale"),
    )

    assert _ids(provisional) == [
        "risk_gate:ONSITE_LOCATION",
        "unknown_gate:DIRECT_PRODUCTION",
        "unknown_gate:SME_CERT",
        middle,
        "pdf_numeric:pdf",
        "stale_analysis:analysis",
    ]
    kinds = [condition.kind for condition in provisional.conditions]
    assert kinds == sorted(kinds, key=CONDITION_KIND_ORDER.index)


# --- basis·assumed_fields(조건부·적합 분기) ---


def test_estimate_input_is_assumed_and_demo_is_used_like_confirmed():
    facts = _facts(_registered_rule())
    profile = make_profile({"registrations.g2b.registered": True})

    estimate = _provisional_of(
        facts, leveled_view(profile, {"registrations.g2b.registered": "estimate"})
    )
    assert (estimate.decision, estimate.conditions) == ("GO", [])
    assert estimate.basis == "assumed"
    assert estimate.assumed_fields == ["registrations.g2b.registered"]
    assert estimate.demo_fields == []

    # demo는 확인값과 같이 판정에 쓰이고 basis를 assumed로 만들지 않는다(2026-10-25).
    demo = _provisional_of(facts, leveled_view(profile, {"registrations.g2b.registered": "demo"}))
    assert (demo.decision, demo.conditions) == ("GO", [])
    assert demo.basis == "confirmed"
    assert demo.assumed_fields == []
    assert demo.demo_fields == ["registrations.g2b.registered"]

    # unknown 수준은 여전히 확인 조건이다.
    unknown = _provisional_of(
        facts, leveled_view(profile, {"registrations.g2b.registered": "unknown"})
    )
    assert _ids(unknown) == ["unknown_gate:G2B_REGISTERED"]
    assert unknown.conditions[0].company_fields == ["registrations.g2b.registered"]
    assert unknown.conditions[0].check == "나라장터 > 입찰참가자격등록증"
    assert unknown.basis == "confirmed"
    assert unknown.demo_fields == []


def test_demo_fields_sorted_unique_and_follow_decision_scope():
    """demo_fields는 결론을 정한 게이트 범위(assumed_fields와 같은 규칙)의 demo 입력만, 정렬·
    중복 없이 담는다. demo와 public이 섞이면 basis는 public 때문에만 assumed다."""
    profile = make_profile(
        {
            "registrations.g2b.registered": True,
            "registrations.g2b.industry_codes": ["1468"],
            "registrations.g2b.other_codes": [],
            "company.founded": "2010-01",
        }
    )
    levels = {
        "registrations.g2b.registered": "demo",
        "registrations.g2b.industry_codes": "demo",
        "registrations.g2b.other_codes": "public",
    }
    facts = _facts(
        rule("INDUSTRY_CODE", "업종 1468", industry_code=["1468"], evidence=VERIFIED),
        _registered_rule(),
        rule("G2B_REGISTERED", "나라장터 등록(중복)", evidence=VERIFIED),
    )

    provisional = _provisional_of(facts, leveled_view(profile, levels))

    assert provisional.decision == "GO"
    assert provisional.demo_fields == [
        "registrations.g2b.industry_codes",
        "registrations.g2b.registered",
    ]
    assert provisional.assumed_fields == ["registrations.g2b.other_codes"]
    assert provisional.basis == "assumed"

    # NO_GO 범위는 실패 게이트뿐이다: 통과 게이트의 demo 입력은 담지 않는다.
    failing = make_profile(
        {
            "registrations.g2b.registered": True,
            "registrations.g2b.industry_codes": ["9999"],
            "registrations.g2b.other_codes": [],
        }
    )
    fail_levels = {
        "registrations.g2b.registered": "demo",
        "registrations.g2b.industry_codes": "demo",
        "registrations.g2b.other_codes": "confirmed",
    }
    no_go = _provisional_of(
        _facts(
            _registered_rule(),
            rule("INDUSTRY_CODE", "업종 1468", industry_code=["1468"], evidence=VERIFIED),
        ),
        leveled_view(failing, fail_levels),
    )
    assert (no_go.decision, no_go.conditions, no_go.basis) == ("NO_GO", [], "confirmed")
    assert no_go.demo_fields == ["registrations.g2b.industry_codes"]


def test_demo_trusted_fail_is_no_go_without_recheck():
    """신뢰 FAIL 입력이 demo여도 confirmed와 같이 재확인 조건 없이 포기다."""
    profile = make_profile(
        {
            "registrations.g2b.registered": True,
            "registrations.g2b.industry_codes": ["9999"],
            "registrations.g2b.other_codes": [],
        }
    )
    facts = _facts(rule("INDUSTRY_CODE", "업종 1468", industry_code=["1468"], evidence=VERIFIED))
    company = leveled_view(
        profile,
        {"registrations.g2b.industry_codes": "demo", "registrations.g2b.other_codes": "demo"},
    )

    provisional = _provisional_of(facts, company)

    assert (provisional.decision, provisional.conditions) == ("NO_GO", [])
    assert provisional.basis == "confirmed"
    assert provisional.demo_fields == [
        "registrations.g2b.industry_codes",
        "registrations.g2b.other_codes",
    ]

    unknown = leveled_view(
        profile,
        {"registrations.g2b.industry_codes": "unknown", "registrations.g2b.other_codes": "demo"},
    )
    assert [g.verdict for g in evaluate_gates(facts, unknown, as_of=AS_OF)] == ["UNKNOWN"]


def test_demo_min_contract_is_no_go_and_recorded_in_demo_fields():
    profile = make_profile(
        {"registrations.g2b.registered": True, "policy.min_contract_amount_krw": 200}
    )
    company = leveled_view(
        profile,
        {"registrations.g2b.registered": "confirmed", "policy.min_contract_amount_krw": "demo"},
    )
    facts = _facts(_registered_rule(), budget_krw=100)
    facts.project.evidence = [verified_evidence("사업금액 100원")]

    provisional = _provisional_of(facts, company)

    assert (provisional.decision, provisional.conditions, provisional.basis) == (
        "NO_GO",
        [],
        "confirmed",
    )
    assert provisional.demo_fields == ["policy.min_contract_amount_krw"]
    assert provisional.assumed_fields == []


def _registered_portfolio_view():
    profile = _portfolio_profile(**{"registrations.g2b.registered": True})
    levels = {**_public_portfolio_view(profile), "registrations.g2b.registered": "confirmed"}
    return profile, leveled_view(profile, levels)


def test_public_inputs_used_by_passing_gate_are_assumed():
    profile = make_profile(
        {"company.founded": "2010-01", "registrations.g2b.registered": True},
        portfolio=[
            portfolio_item(
                "P2020-01", title="홈페이지 유지관리", completed=True, period_end="2025-06"
            ),
            portfolio_item("P2021-01", title="모바일앱 개발", completed=True),
        ],
    )
    levels = {
        **_public_portfolio_view(profile),
        "portfolio[P2020-01].period.end": "public",
        "registrations.g2b.registered": "confirmed",
    }
    company = leveled_view(profile, levels)
    facts = _facts(
        _registered_rule(),
        rule("PAST_PERFORMANCE", "홈페이지 실적", keyword="홈페이지", evidence=VERIFIED),
    )

    provisional = _provisional_of(facts, company)

    assert provisional.conditions == []
    assert provisional.decision == "GO"
    assert provisional.basis == "assumed"
    # 충족(PASS)은 목록 완전성을 묻지 않으므로 가정 목록 없이 public 입력만 가정 값이다.
    assert "portfolio[P2020-01].period.end" in provisional.assumed_fields
    assert "portfolio" not in provisional.assumed_fields
    assert all(levels[path] == "public" for path in provisional.assumed_fields)


def test_assumed_list_basis_and_fields_follow_steps_8_and_9():
    _, company = _registered_portfolio_view()
    facts = _facts(
        _registered_rule(),
        rule("PAST_PERFORMANCE", "챗봇 구축 실적", keyword="챗봇 구축", evidence=VERIFIED),
    )

    def drop_failure(gates):
        return [g for g in gates if g.code != "PAST_PERFORMANCE"]

    # 가정 목록을 쓴 게이트가 빠져도 가정 목록이 있었으면 basis는 assumed다(8단계).
    provisional = _provisional_of(facts, company, resolve_gates=drop_failure)
    assert provisional.decision == "GO"
    assert provisional.basis == "assumed"
    # 9단계: 결정 범위(gates_a 전체)가 쓰지 않은 가정 목록은 assumed_fields에 넣지 않는다.
    assert provisional.assumed_fields == []


def test_company_none_returns_none():
    analysis = _analysis_for(_facts(_registered_rule()))
    assert compute_provisional(analysis, CURRENT_STATES, ["SFR-001"], company=None) is None


# --- T15·T20: 조건 문구에 내부 식별자가 없다 ---

_DISPLAY_CODES = (
    "GO",
    "NO_GO",
    "CONDITIONAL_GO",
    "PASS",
    "FAIL",
    "UNKNOWN",
    "RISK",
    "FULL",
    "PARTIAL",
    "GAP",
    *get_args(GateCode),
)
_FORBIDDEN_TEXT = (
    re.compile(r"(gate|field|fit|stage|risk):"),
    re.compile(r"#/"),
    re.compile(r"[0-9a-f]{64}"),
    re.compile(r"(?<![A-Za-z_])(" + "|".join(_DISPLAY_CODES) + r")(?![A-Za-z_])"),
    re.compile(r"schema\.md"),
    re.compile(r"[a-z_]+\.[a-z_]"),
)


def _assert_display_text(text: str) -> None:
    assert text.strip()
    for pattern in _FORBIDDEN_TEXT:
        assert pattern.search(text) is None, (pattern.pattern, text)


def _scenario_provisionals():
    company_t5 = confirmed_fixture_view(make_profile({"company.founded": "2010-01"}))
    registered = _registered_view()
    yield _provisional_of(*_t3_inputs("챗봇 구축", "드론 관제")[::2])
    yield _provisional_of(*_industry_inputs(verified_evidence(verified=False)))
    yield _provisional_of(
        _t5_facts(),
        company_t5,
        ("UNKNOWN", "UNKNOWN", "FULL"),
        numeric=True,
        states=_states(facts="stale", fits="stale"),
    )
    yield _provisional_of(_t5_facts(), company_t5, (), requirement_ids=None)
    for code in get_args(GateCode):
        for verdict in ("RISK", "UNKNOWN"):
            extra = make_gate(
                code,
                verdict,
                action="확인 필요: company/schema.md 참고",
                unknown_fields=["registrations.unmapped_field", "portfolio[P2020-01].amount_krw"],
            )
            yield _provisional_of(
                _facts(_registered_rule()), registered, resolve_gates=lambda g, x=extra: [*g, x]
            )
        failing = make_gate(code, "FAIL", evidence=[], unknown_fields=["company.region"])
        yield _provisional_of(
            _facts(_registered_rule()), registered, resolve_gates=lambda g, x=failing: [*g, x]
        )


def test_t15_condition_text_has_no_internal_identifiers():
    seen_kinds = set()
    for provisional in _scenario_provisionals():
        for condition in provisional.conditions:
            seen_kinds.add(condition.kind)
            for text in (condition.title, condition.check, condition.if_not):
                _assert_display_text(text)
    assert seen_kinds == set(CONDITION_KIND_ORDER)


def test_t20_hints_used_in_condition_text_have_no_internal_identifiers():
    # 최소계약금액 정책 hint("NO_GO 권고")는 게이트 입력이 아니어서 조건 문구에 쓰이지 않는다.
    assert "min_contract_amount_krw" not in inspect.getsource(gates_module)
    for path in FIELD_HINTS:
        if path == "policy.min_contract_amount_krw":
            continue
        _assert_display_text(_condition_hint(path))
    assert DEFAULT_HINT != _condition_hint("portfolio")
    assert _condition_hint("portfolio") == "회사 기록 확인"
    assert _condition_hint("registrations.unmapped_field") == "회사 기록 확인"
    # 영문 일반어는 금지 대상이 아니다.
    assert "Go/No-Go" in _condition_hint("policy.seoul_resident_ok")
    assert "solo" in _condition_hint("policy.default_bid_mode")


# --- T12(일부): assess_analysis 연결 ---


def test_t12_assess_analysis_fills_provisional_from_same_inputs():
    facts, company = _industry_inputs(verified_evidence(verified=False))
    analysis = make_analysis(
        facts=facts,
        gates=evaluate_gates(facts, company, as_of=AS_OF),
        fits=_fits("FULL"),
    )

    assessment, _ = assess_analysis(
        analysis, CURRENT_STATES, ["SFR-001"], company=company, now=AS_OF
    )

    assert (assessment.state, assessment.decision) == ("abstain", None)
    assert "untrusted_failure" in assessment.reason_codes
    assert assessment.provisional == compute_provisional(
        analysis, CURRENT_STATES, ["SFR-001"], company=company, now=AS_OF
    )
    assert assessment.provisional.decision == "NO_GO"


def test_t12_trusted_fail_assessment_and_provisional_agree():
    facts, company = _industry_inputs()
    analysis = make_analysis(
        facts=facts,
        gates=evaluate_gates(facts, company, as_of=AS_OF),
        fits=_fits("FULL"),
    )

    assessment, _ = assess_analysis(
        analysis, CURRENT_STATES, ["SFR-001"], company=company, now=AS_OF
    )

    assert (assessment.state, assessment.decision) == ("ready", "NO_GO")
    assert assessment.reason_codes == ["hard_gate_fail"]
    assert (assessment.provisional.decision, assessment.provisional.conditions) == ("NO_GO", [])


def test_t12_resolver_changes_only_provisional():
    facts = _facts(_registered_rule(), rule("SME_CERT", "중소기업 확인서", evidence=VERIFIED))
    company = _registered_view()
    analysis = make_analysis(
        facts=facts,
        gates=evaluate_gates(facts, company, as_of=AS_OF),
        fits=_fits("FULL"),
    )

    def human_pass(gates):
        return [g.model_copy(update={"verdict": "PASS", "unknown_fields": []}) for g in gates]

    plain, plain_reasons = assess_analysis(
        analysis, CURRENT_STATES, ["SFR-001"], company=company, now=AS_OF
    )
    resolved, resolved_reasons = assess_analysis(
        analysis,
        CURRENT_STATES,
        ["SFR-001"],
        company=company,
        now=AS_OF,
        resolve_gates=human_pass,
    )

    assert plain.model_dump(exclude={"provisional"}) == resolved.model_dump(exclude={"provisional"})
    assert plain_reasons == resolved_reasons
    assert plain.provisional.decision == "CONDITIONAL_GO"
    assert (resolved.provisional.decision, resolved.provisional.conditions) == ("GO", [])


def test_t12_assess_analysis_without_company_has_no_provisional():
    analysis = _analysis_for(_facts(_registered_rule()))

    assessment, _ = assess_analysis(analysis, CURRENT_STATES, ["SFR-001"])

    assert assessment.provisional is None
