"""평일 브리핑의 결정적 규칙 엔진과 규칙 파일 (RL-01 spec T1·T2·T3, RL-02 spec T5).

규칙은 순수 함수다. 후보는 `Notice`·`OrderPlan`과 같은 속성을 가진 가짜 객체로,
회사 사실은 lifecycle 확장점 자료형(`CompanyFactsProjection`)으로 직접 만든다 —
lifecycle 테스트는 deep_review·screening을 import하지 않는다(경계 검사 1). 실제
제공자 검사는 `tests/deep_review/test_company_facts_projection.py`와
`tests/screening/test_briefing_order_plan_candidates.py`에 있다.

값은 회사 자료가 아니라 계약 모양만 갖춘 합성 값이다.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import random
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from app.core.config import DEFAULT_BRIEFING_POLICY_PATH, Settings
from app.lifecycle.extensions import CompanyFact, CompanyFactsProjection
from app.lifecycle.services import name_matching
from app.lifecycle.services.briefing_policy import (
    BriefingPolicyError,
    load_briefing_policy,
    parse_briefing_policy,
)
from app.lifecycle.services.briefing_rules import (
    CANDIDATE_FIELD_MAP,
    DEADLINE_REMINDER_FIELD,
    EXCLUSION_KINDS,
    BriefingRulesError,
    DeadlineReminderCandidate,
    TrackedChange,
    TrackedChangeObservation,
    build_recommendations,
    combine_tracked_changes,
    company_rules,
    korean_amount_text,
    merge_tracked_changes,
    normalize_text,
    notice_candidate,
    order_plan_candidate,
    tracked_change_verdict,
    tracked_changes,
    deadline_reminders,
)

V1_POLICY_PATH = DEFAULT_BRIEFING_POLICY_PATH.parent / "briefing-policy-v1.json"
V2_POLICY_PATH = DEFAULT_BRIEFING_POLICY_PATH.parent / "briefing-policy-v2.json"
V1_KEYS = {
    "schema", "policy_identity", "top_n", "weights", "deadline_warning_days",
    "tracked_change_fields", "slack_items_per_message", "large_enterprise_threshold_krw",
}

GRAPH = UUID("11111111-2222-3333-4444-555555555555")
NOW = datetime(2026, 10, 16, 22, 30, tzinfo=UTC)  # 2026-10-17 07:30 KST
FIRST_SEEN = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)


# --- 공통 fixture ------------------------------------------------------------


def _fact(fact_key: str, type_: str, value, *, status: str = "confirmed", label: str | None = None):
    return CompanyFact(fact_key=fact_key, type=type_, status=status, label=label or fact_key, value=value)


def _domain(tier, keywords, *, excluded=False, kind=None):
    return {"tier": tier, "keywords": list(keywords), "excluded": excluded, "kind": kind}


def _capability(params):
    return {"scope": "core", "description": "합성 조건", "params": params}


def _project(label: str, agency: str, year: int):
    return {
        "role": None, "scope": None, "amount_krw": None, "started_on": None,
        "ended_on": None, "agency": agency, "year": year,
    }


def _facts(*, status: str = "confirmed") -> list[CompanyFact]:
    return [
        _fact("pref:domain:01", "domain", _domain(1, ["유지관리", "홈페이지"]), status=status),
        _fact("pref:domain:02", "domain", _domain(2, ["빅데이터", "데이터 플랫폼"]), status=status),
        _fact("pref:domain:03", "domain", _domain(3, ["자원봉사"]), status=status),
        _fact("excl:hardware", "domain", _domain(None, ["하드웨어", "장비 구매"], excluded=True, kind="hardware"), status=status),
        _fact("excl:election", "domain", _domain(None, ["선거"], excluded=True, kind="election"), status=status),
        _fact("excl:design_only", "domain", _domain(None, ["디자인 단독"], excluded=True, kind="design_only"), status=status),
        _fact("excl:staffing_only", "domain", _domain(None, ["인력 파견"], excluded=True, kind="staffing_only"), status=status),
        _fact("excl:region", "domain", _domain(None, ["대구", "경북", "경상북도", "전국"], excluded=True, kind="region"), status=status),
        _fact("excl:amount_floor", "domain", _domain(None, [], excluded=True, kind="amount_floor"), status=status),
        _fact("pref:amount_floor", "capability", _capability({"krw": 30_000_000}), status=status),
        _fact("pref:amount_range", "capability", _capability({"min_krw": 100_000_000, "max_krw": 1_000_000_000}), status=status),
        _fact("pref:solo_cap", "capability", _capability({"krw": 1_500_000_000}), status=status),
        _fact("pref:agency:01", "domain", _domain(None, ["대구테크노파크"]), status=status, label="대구테크노파크"),
        _fact("pref:agency:02", "domain", _domain(None, ["합성진흥원"]), status=status, label="합성진흥원"),
        _fact("project:2024-01", "project", _project("스마트 관광 플랫폼 고도화 용역", "대구테크노파크", 2024),
              status=status, label="스마트 관광 플랫폼 고도화 용역"),
        _fact("project:2023-01", "project", _project("지역 데이터 허브 구축(1차)", "합성진흥원", 2023),
              status=status, label="지역 데이터 허브 구축(1차)"),
    ]


def _projection(facts=None) -> CompanyFactsProjection:
    return CompanyFactsProjection(graph_version_id=GRAPH, facts=tuple(_facts() if facts is None else facts))


@pytest.fixture(scope="module")
def policy():
    return load_briefing_policy(DEFAULT_BRIEFING_POLICY_PATH)


def _policy_with(**changes):
    value = json.loads(DEFAULT_BRIEFING_POLICY_PATH.read_bytes())
    value.update(changes)
    return parse_briefing_policy(json.dumps(value).encode())


_NEXT_ID = iter(range(1, 10_000))


def _notice(
    title: str,
    *,
    stage: str = "pre_spec",
    agency: str | None = "합성구청",
    demand_agency: str | None = None,
    estimated_price=None,
    budget=None,
    region=None,
    deadline_days: float | None = 10,
    sw: str | None = "Y",
    first_seen: datetime = FIRST_SEEN,
    notice_id: int | None = None,
):
    notice = SimpleNamespace(
        id=notice_id if notice_id is not None else next(_NEXT_ID),
        title=title,
        agency=agency,
        demand_agency=demand_agency,
        estimated_price=None if estimated_price is None else Decimal(estimated_price),
        budget=None if budget is None else Decimal(budget),
        region_limit_json=region,
        deadline_at=None if deadline_days is None else NOW + timedelta(days=deadline_days),
        qualification_flags_json={"sw_business_status": sw},
    )
    return notice_candidate(notice, stage=stage, first_observed_at=first_seen)


def _plan(
    title: str,
    *,
    agency_name: str | None = "합성구청",
    supervising: str | None = None,
    budget=None,
    month: str | None = "2026-12",
    first_seen: datetime = FIRST_SEEN,
):
    plan = SimpleNamespace(
        id=next(_NEXT_ID),
        title=title,
        agency_name=agency_name,
        supervising_agency_name=supervising,
        budget_amount=None if budget is None else Decimal(budget),
        planned_order_month=month,
        first_discovered_at=first_seen,
    )
    return order_plan_candidate(plan)


def _snapshot(result):
    """비교용 평면 표현. 같은 입력이면 바이트까지 같아야 한다."""

    return json.dumps(
        {
            "items": [
                {
                    "rank": item.rank,
                    "stage": item.candidate.stage,
                    "notice_id": item.candidate.notice_id,
                    "order_plan_id": item.candidate.order_plan_id,
                    "score": item.score,
                    "reasons": list(item.reasons),
                    "blocking": list(item.blocking),
                    "change_fields": list(item.change_fields),
                }
                for item in result.items
            ],
            "excluded": result.excluded_counts,
            "unscored": result.unscored_count,
            "order_plan_not_repeat": result.order_plan_not_repeat_count,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


# --- 규칙 파일 ---------------------------------------------------------------


def test_v1_policy_file_has_exactly_the_spec_values_and_its_byte_digest() -> None:
    # v1 파일은 v2 발행 뒤에도 그대로 남고 계속 읽힌다(immutable 파일 규칙).
    policy = load_briefing_policy(V1_POLICY_PATH)
    raw = V1_POLICY_PATH.read_bytes()
    assert set(json.loads(raw)) == V1_KEYS
    assert policy.deadline_reminder_days == ()
    assert policy.sha256 == hashlib.sha256(raw).hexdigest()
    assert (policy.schema, policy.policy_identity, policy.top_n) == (
        "bidops.briefing-policy.v1", "briefing-policy-v1", 10,
    )
    weights = policy.weights
    assert (
        weights.tier1, weights.tier2, weights.tier3, weights.repeat_agency,
        weights.similar_project, weights.sw_target, weights.amount_in_range,
    ) == (30, 20, 10, 25, 25, 10, 10)
    assert policy.deadline_warning_days == 7
    assert policy.tracked_change_fields == ("deadline_at", "title", "budget", "estimated_price")
    assert policy.slack_items_per_message == 10
    assert policy.large_enterprise_threshold_krw == 2_000_000_000


def test_v2_policy_file_is_v1_plus_deadline_reminder_days_and_method() -> None:
    """RL-02 spec "마감 알림": v1 전체 + `deadline_reminder_days:[3,1]` + 추적 필드 `method`."""

    raw = V2_POLICY_PATH.read_bytes()
    value = json.loads(raw)
    assert set(value) == V1_KEYS | {"deadline_reminder_days"}
    assert (value["schema"], value["policy_identity"]) == ("bidops.briefing-policy.v2", "briefing-policy-v2")
    v1 = json.loads(V1_POLICY_PATH.read_bytes())
    for key in V1_KEYS - {"schema", "policy_identity", "tracked_change_fields"}:
        assert value[key] == v1[key], key
    assert value["tracked_change_fields"] == [*v1["tracked_change_fields"], "method"]
    assert value["deadline_reminder_days"] == [3, 1]
    policy = load_briefing_policy(V2_POLICY_PATH)
    assert (policy.schema, policy.policy_identity) == ("bidops.briefing-policy.v2", "briefing-policy-v2")
    assert policy.tracked_change_fields == ("deadline_at", "title", "budget", "estimated_price", "method")
    assert policy.deadline_reminder_days == (3, 1)
    assert policy.sha256 == hashlib.sha256(raw).hexdigest()
    old = load_briefing_policy(V1_POLICY_PATH)
    same = {f.name for f in dataclass_fields(policy)} - {
        "schema", "policy_identity", "tracked_change_fields", "sha256", "deadline_reminder_days",
    }
    assert {name: getattr(policy, name) for name in same} == {name: getattr(old, name) for name in same}


def test_config_default_points_at_the_v2_policy_file_and_v1_stays(monkeypatch) -> None:
    monkeypatch.delenv("BIDOPS_BRIEFING_POLICY_PATH", raising=False)
    assert Settings().briefing_policy_path == DEFAULT_BRIEFING_POLICY_PATH
    assert DEFAULT_BRIEFING_POLICY_PATH == V2_POLICY_PATH
    assert DEFAULT_BRIEFING_POLICY_PATH.parent.name == "policies"
    assert V1_POLICY_PATH.is_file()
    assert load_briefing_policy().policy_identity == "briefing-policy-v2"
    monkeypatch.setenv("BIDOPS_BRIEFING_POLICY_PATH", "/elsewhere/briefing-policy-v3.json")
    assert str(Settings().briefing_policy_path) == "/elsewhere/briefing-policy-v3.json"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.update(extra=1),
        lambda v: v.pop("top_n"),
        lambda v: v.update(schema="bidops.briefing-policy.v2"),
        lambda v: v.update(policy_identity=""),
        lambda v: v.update(top_n=0),
        lambda v: v.update(top_n=31),
        lambda v: v.update(top_n=True),
        lambda v: v["weights"].update(tier1=101),
        lambda v: v["weights"].update(tier1=-1),
        lambda v: v["weights"].update(sw_target=1.5),
        lambda v: v["weights"].pop("tier3"),
        lambda v: v["weights"].update(bonus=1),
        lambda v: v.update(deadline_warning_days=31),
        lambda v: v.update(slack_items_per_message=13),
        lambda v: v.update(tracked_change_fields=[]),
        lambda v: v.update(tracked_change_fields=["deadline_at", "deadline_at"]),
        lambda v: v.update(tracked_change_fields=["not_a_notice_column"]),
        lambda v: v.update(large_enterprise_threshold_krw=0),
    ],
)
def test_policy_rejects_keys_and_ranges_outside_the_contract(mutate) -> None:
    value = json.loads(V1_POLICY_PATH.read_bytes())
    mutate(value)
    with pytest.raises(BriefingPolicyError) as error:
        parse_briefing_policy(json.dumps(value).encode())
    assert str(error.value) == "briefing_policy_invalid"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda v: v.pop("deadline_reminder_days"), id="v2-without-days"),
        pytest.param(lambda v: v.update(schema="bidops.briefing-policy.v1"), id="v1-schema-with-days"),
        pytest.param(lambda v: v.update(schema="bidops.briefing-policy.v3"), id="unknown-schema"),
        pytest.param(lambda v: v.update(deadline_reminder_days=[]), id="days-empty"),
        pytest.param(lambda v: v.update(deadline_reminder_days=[0]), id="days-zero"),
        pytest.param(lambda v: v.update(deadline_reminder_days=[31]), id="days-over-30"),
        pytest.param(lambda v: v.update(deadline_reminder_days=[3, 3]), id="days-duplicate"),
        pytest.param(lambda v: v.update(deadline_reminder_days=[1.5]), id="days-float"),
        pytest.param(lambda v: v.update(deadline_reminder_days=[True]), id="days-bool"),
        pytest.param(lambda v: v.update(deadline_reminder_days="3"), id="days-string"),
        pytest.param(lambda v: v.update(deadline_reminder_days=3), id="days-scalar"),
        pytest.param(lambda v: v.update(tracked_change_fields=["method", "deadline_reminder"]), id="reminder-is-not-a-column"),
        pytest.param(lambda v: v.update(extra=1), id="extra-key"),
    ],
)
def test_v2_policy_rejects_keys_and_ranges_outside_the_contract(mutate) -> None:
    value = json.loads(V2_POLICY_PATH.read_bytes())
    mutate(value)
    with pytest.raises(BriefingPolicyError) as error:
        parse_briefing_policy(json.dumps(value).encode())
    assert str(error.value) == "briefing_policy_invalid"


def test_v2_policy_accepts_other_in_range_reminder_days() -> None:
    value = json.loads(V2_POLICY_PATH.read_bytes())
    value["deadline_reminder_days"] = [30, 7, 1]
    assert parse_briefing_policy(json.dumps(value).encode()).deadline_reminder_days == (30, 7, 1)


def test_policy_rejects_unreadable_and_non_json_files(tmp_path) -> None:
    with pytest.raises(BriefingPolicyError):
        load_briefing_policy(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_bytes(b"{not json")
    with pytest.raises(BriefingPolicyError):
        load_briefing_policy(broken)


# --- 정규화와 필드 매핑 ------------------------------------------------------


def test_normalize_text_is_nfkc_then_name_matching_then_no_space_then_casefold() -> None:
    assert normalize_text("  Ｈｏｍｅ　Page·유지 관리 ") == "homepage유지관리"
    # 선두 상태 태그는 name_matching.normalize가 떼어 낸다.
    assert normalize_text("[재공고] 홈페이지 구축") == "홈페이지구축"
    # casefold는 lower보다 넓다.
    assert normalize_text("STRASSE Straße") == "strassestrasse"
    assert normalize_text(None) == ""
    assert normalize_text("  ·  ") == ""
    # name_matching.normalize 단독은 NFKC·casefold가 없어 쓰지 않는다.
    assert name_matching.normalize("Ｈｏｍｅ") != normalize_text("Ｈｏｍｅ")


def test_candidate_field_map_matches_the_spec_table() -> None:
    assert CANDIDATE_FIELD_MAP == {
        "notice": {
            "text": ("title", "agency", "demand_agency"),
            "agency": ("agency", "demand_agency"),
            "amount": ("estimated_price", "budget"),
            "region": "region_limit_json",
            "deadline": "deadline_at",
            "planned_month": None,
        },
        "order_plan": {
            "text": ("title", "agency_name", "supervising_agency_name"),
            "agency": ("agency_name", "supervising_agency_name"),
            "amount": ("budget_amount",),
            "region": None,
            "deadline": None,
            "planned_month": "planned_order_month",
        },
    }


def test_notice_and_order_plan_candidates_follow_the_mapping() -> None:
    pre_spec = _notice("사업", estimated_price=None, budget=70_000_000, deadline_days=3)
    assert pre_spec.stage == "pre_spec" and pre_spec.deadline_kind == "opinion_close"
    assert pre_spec.amount == Decimal(70_000_000) and pre_spec.amount_krw == 70_000_000
    assert pre_spec.sw_target is True and pre_spec.planned_month is None
    priced = _notice("사업", stage="bid_notice", estimated_price=50_000_000, budget=90_000_000)
    assert priced.deadline_kind == "bid_close" and priced.amount_krw == 50_000_000
    assert priced.sw_target is False  # sw_target은 사전규격 전용
    assert _notice("사업", sw="N").sw_target is False
    assert _notice("사업", sw=None).sw_target is False

    plan = _plan("연차 사업", agency_name="기관A", supervising="상위기관", budget=300_000_000, month="2027-02")
    assert (plan.stage, plan.deadline_at, plan.deadline_kind, plan.planned_month) == (
        "order_plan", None, "planned_month", "2027-02",
    )
    assert plan.agencies == ("기관A", "상위기관")
    assert plan.region_limit is None and plan.amount_krw == 300_000_000
    assert plan.first_observed_at == FIRST_SEEN and plan.order_plan_id is not None


def test_korean_amount_text() -> None:
    assert korean_amount_text(1_500_000_000) == "15억 원"
    assert korean_amount_text(2_000_000_000) == "20억 원"
    assert korean_amount_text(1_050_000_000) == "10억 5,000만 원"
    assert korean_amount_text(30_000_000) == "3,000만 원"
    assert korean_amount_text(12_345) == "1만 2,345 원"


# --- 회사 사실 입력 ----------------------------------------------------------


def test_company_rules_read_the_rl00_fact_keys(policy) -> None:
    rules = company_rules(_projection())
    assert rules.graph_version_id == GRAPH
    assert [(domain.fact_key, domain.tier) for domain in rules.domains] == [
        ("pref:domain:01", 1), ("pref:domain:02", 2), ("pref:domain:03", 3),
    ]
    assert set(rules.exclusion_keywords) == {"hardware", "election", "design_only", "staffing_only"}
    assert [keyword.text for keyword in rules.allowed_regions] == ["대구", "경북", "경상북도", "전국"]
    assert rules.amount_floor_krw == 30_000_000
    assert rules.amount_range == (100_000_000, 1_000_000_000)
    assert rules.solo_cap_krw == 1_500_000_000
    assert [agency.text for agency in rules.agencies] == ["대구테크노파크", "합성진흥원"]
    assert [project.fact_key for project in rules.projects] == ["project:2023-01", "project:2024-01"]


def test_company_rules_reject_a_confirmed_fact_with_a_broken_shape() -> None:
    broken = _facts()
    broken[0] = _fact("pref:domain:01", "domain", {"tier": 9, "keywords": ["x"], "excluded": False, "kind": None})
    with pytest.raises(BriefingRulesError) as error:
        company_rules(_projection(broken))
    assert str(error.value) == "company_facts_invalid"


# --- T1 ----------------------------------------------------------------------


def _t1_candidates():
    return {
        "pre_spec_y": _notice(
            "대구테크노파크 홈페이지 유지관리 용역", agency="대구테크노파크",
            estimated_price=200_000_000, deadline_days=5, notice_id=101,
        ),
        "pre_spec_n": _notice(
            "청사 홈페이지 개편", sw="N", estimated_price=200_000_000, deadline_days=20, notice_id=102,
        ),
        "bid": _notice(
            "빅데이터 분석 플랫폼 구축", stage="bid_notice", estimated_price=2_500_000_000,
            deadline_days=12, notice_id=103,
        ),
        "plan_repeat": _plan(
            "스마트 관광 플랫폼 고도화 용역(2차)", agency_name="대구 테크노파크", budget=500_000_000,
        ),
        "plan_agency_only": _plan("청사 시설 관리", agency_name="대구테크노파크", budget=500_000_000),
        "plan_similar_only": _plan("지역 데이터 허브 구축 2단계", agency_name="다른기관"),
        "hardware": _notice("네트워크 장비 구매 및 유지관리", estimated_price=200_000_000, notice_id=104),
        "election": _notice("선거 홈페이지 구축", estimated_price=200_000_000, notice_id=105),
        "region_other": _notice(
            "홈페이지 유지관리", estimated_price=200_000_000, notice_id=106,
            region={"basis": "본사소재지", "joint_contract_regions": ["부산광역시"]},
        ),
        "region_allowed": _notice(
            "자원봉사 관리 홈페이지", estimated_price=200_000_000, notice_id=107, deadline_days=30,
            region={"basis": "본사소재지", "joint_contract_regions": ["대구광역시"]},
        ),
        "region_empty": _notice(
            "홈페이지 포털 운영", estimated_price=None, budget=None, notice_id=108, deadline_days=None,
            region={"basis": "", "joint_contract_regions": []},
        ),
        "small": _notice("홈페이지 유지관리 소규모", estimated_price=20_000_000, notice_id=109),
        "zero": _notice("청사 청소 용역", sw="N", notice_id=110),
    }


def test_t1_exclusions_order_plan_rule_scores_and_order(policy) -> None:
    candidates = _t1_candidates()
    result = build_recommendations(list(candidates.values()), company_rules(_projection()), policy, now=NOW)

    assert result.excluded_counts == {
        "hardware": 1, "election": 1, "design_only": 0, "staffing_only": 0,
        # 지역 제외 보류(2026-10-17): 수집 basis는 판단 기준("본사소재지")이라 지역제한 공고도 제외하지 않는다.
        "region": 0, "amount_floor": 1,
    }
    assert tuple(result.excluded_counts) == EXCLUSION_KINDS
    assert result.unscored_count == 1  # "청사 청소 용역"
    assert result.order_plan_not_repeat_count == 2  # 반복만·유사만 발주계획

    ordered = [(item.rank, item.candidate.stage, item.score) for item in result.items]
    by_rank = {item.rank: item for item in result.items}
    # 75 = tier1 30 + repeat 25 + sw 10 + range 10
    assert by_rank[1].candidate is candidates["pre_spec_y"]
    # 60 = repeat 25 + similar 25 + range 10 (발주계획은 반복 ∧ 유사일 때만)
    assert by_rank[2].candidate is candidates["plan_repeat"]
    assert ordered == [
        (1, "pre_spec", 75),
        (2, "order_plan", 60),
        (3, "pre_spec", 50),   # region_other: tier1 30 + sw 10 + range 10, deadline +10 (지역 제외 보류로 남음)
        (4, "pre_spec", 50),   # region_allowed: 같은 점수, deadline +30 → 뒤
        (5, "pre_spec", 40),   # pre_spec_n: tier1 30 + range 10, deadline +20
        (6, "pre_spec", 40),   # region_empty: tier1 30 + sw 10, deadline 없음 → 뒤
        (7, "bid_notice", 20),  # tier2
    ]
    assert by_rank[3].candidate is candidates["region_other"]
    assert by_rank[4].candidate is candidates["region_allowed"]
    assert by_rank[5].candidate is candidates["pre_spec_n"]
    assert by_rank[6].candidate is candidates["region_empty"]

    assert by_rank[1].reasons == (
        {"kind": "keyword", "text": "유지관리"},
        {"kind": "repeat_agency", "text": "대구테크노파크"},
    )
    assert by_rank[1].blocking == ({"kind": "deadline_short", "text": "마감 5일"},)
    assert by_rank[2].reasons == (
        {"kind": "similar_project", "count": 1},
        {"kind": "repeat_agency", "text": "대구테크노파크"},
    )
    assert by_rank[2].blocking == ()
    bid = by_rank[7]
    assert bid.reasons == ({"kind": "keyword", "text": "빅데이터"},)
    # min(solo_cap 15억, 대기업 상수 20억) = 15억
    assert bid.blocking == ({"kind": "consortium_review", "text": "15억 원 이상 · 컨소시엄 검토"},)
    assert all(len(item.reasons) <= 3 and len(item.blocking) <= 2 for item in result.items)
    assert all(item.change_fields == () for item in result.items)


def test_t1_is_deterministic_for_the_same_input_and_any_input_order(policy) -> None:
    rules = company_rules(_projection())
    candidates = list(_t1_candidates().values())
    first = build_recommendations(candidates, rules, policy, now=NOW)
    second = build_recommendations(candidates, rules, policy, now=NOW)
    shuffled = candidates[:]
    random.Random(7).shuffle(shuffled)
    third = build_recommendations(shuffled, company_rules(_projection(list(reversed(_facts())))), policy, now=NOW)
    assert _snapshot(first) == _snapshot(second) == _snapshot(third)


def test_t1_top_n_truncates_after_ordering(policy) -> None:
    narrow = _policy_with(top_n=2)
    result = build_recommendations(list(_t1_candidates().values()), company_rules(_projection()), narrow, now=NOW)
    assert [(item.rank, item.score) for item in result.items] == [(1, 75), (2, 60)]


def test_tie_break_deadline_ascending_none_last_then_first_observed(policy) -> None:
    rules = company_rules(_projection())
    later = _notice("홈페이지 운영 A", deadline_days=9, notice_id=201)
    sooner = _notice("홈페이지 운영 B", deadline_days=8, notice_id=202)
    undated = _notice("홈페이지 운영 C", deadline_days=None, notice_id=203)
    same_deadline_old = _notice("홈페이지 운영 D", deadline_days=9, notice_id=204,
                                first_seen=FIRST_SEEN - timedelta(hours=1))
    result = build_recommendations([undated, later, sooner, same_deadline_old], rules, policy, now=NOW)
    assert {item.score for item in result.items} == {40}
    assert [item.candidate.notice_id for item in result.items] == [202, 204, 201, 203]
    assert [item.rank for item in result.items] == [1, 2, 3, 4]


def test_exclusion_details(policy) -> None:
    rules = company_rules(_projection())
    # 금액이 둘 다 없으면 소액 제외를 적용하지 않는다. 예정가격이 없으면 예산을 본다.
    no_amount = _notice("홈페이지 유지관리 A", notice_id=301)
    budget_small = _notice("홈페이지 유지관리 B", budget=29_999_999, notice_id=302)
    price_wins = _notice("홈페이지 유지관리 C", estimated_price=40_000_000, budget=10_000_000, notice_id=303)
    joint_only = _notice(
        "홈페이지 유지관리 D", notice_id=304,
        region={"basis": None, "joint_contract_regions": ["부산광역시"]},
    )
    joint_allowed = _notice(
        "홈페이지 유지관리 E", notice_id=305,
        region={"basis": None, "joint_contract_regions": ["경상북도"]},
    )
    region_missing = _notice("홈페이지 유지관리 F", notice_id=306, region=None)
    staffing = _notice("홈페이지 운영 인력파견 용역", notice_id=307)
    # 발주계획은 지역제한 조건을 적용하지 않고, 소액 제외는 예산으로 본다.
    plan_small = _plan("스마트 관광 플랫폼 고도화 용역", agency_name="대구테크노파크", budget=1_000_000)
    result = build_recommendations(
        [no_amount, budget_small, price_wins, joint_only, joint_allowed, region_missing, staffing, plan_small],
        rules, policy, now=NOW,
    )
    kept = {item.candidate.notice_id for item in result.items}
    # 지역 제외 보류: 공동도급 의무 지역(joint_contract_regions)은 참가 제한 지역이 아니므로 제외 근거가 아니다.
    assert kept == {301, 303, 304, 305, 306}
    assert result.excluded_counts["amount_floor"] == 2
    assert result.excluded_counts["region"] == 0
    assert result.excluded_counts["staffing_only"] == 1


def test_similar_project_uses_fragments_of_min_length(policy) -> None:
    facts = _facts() + [
        _fact("project:2022-01", "project", _project("앱·웹", "대구테크노파크", 2022), label="앱·웹"),
    ]
    rules = company_rules(_projection(facts))
    assert name_matching.MIN_FRAGMENT_CHARS == 6
    # "앱", "웹" 조각은 6자 미만이라 유사 실적 근거가 아니다.
    short = _plan("모바일 앱 웹 통합", agency_name="대구테크노파크")
    # 두 실적 모두 hit: count 2
    both = _plan(
        "스마트 관광 플랫폼 고도화 용역 및 지역 데이터 허브 구축", agency_name="대구테크노파크",
    )
    result = build_recommendations([short, both], rules, policy, now=NOW)
    assert [item.candidate for item in result.items] == [both]
    assert result.items[0].reasons[0] == {"kind": "similar_project", "count": 2}
    assert result.order_plan_not_repeat_count == 1


def test_reasons_are_capped_at_three_in_fixed_order(policy) -> None:
    rules = company_rules(_projection())
    rich = _notice(
        "스마트 관광 플랫폼 고도화 용역 유지관리", agency="합성구청", demand_agency="대구테크노파크",
        estimated_price=3_000_000_000, deadline_days=2, notice_id=401,
    )
    result = build_recommendations([rich], rules, policy, now=NOW)
    (item,) = result.items
    assert item.reasons == (
        {"kind": "keyword", "text": "유지관리"},
        {"kind": "similar_project", "count": 1},
        {"kind": "repeat_agency", "text": "대구테크노파크"},
    )
    assert item.blocking == (
        {"kind": "consortium_review", "text": "15억 원 이상 · 컨소시엄 검토"},
        {"kind": "deadline_short", "text": "마감 2일"},
    )
    # 30 + 25 + 25 + 10 (sw) = 90; 30억은 선호 구간 밖이다.
    assert item.score == 90


def test_consortium_threshold_falls_back_to_the_policy_constant_without_solo_cap(policy) -> None:
    facts = [fact for fact in _facts() if fact.fact_key != "pref:solo_cap"]
    rules = company_rules(_projection(facts))
    below = _notice("홈페이지 유지관리 대형", estimated_price=1_900_000_000, notice_id=501)
    above = _notice("홈페이지 유지관리 초대형", estimated_price=2_000_000_000, notice_id=502)
    result = build_recommendations([below, above], rules, policy, now=NOW)
    blocking = {item.candidate.notice_id: item.blocking for item in result.items}
    assert blocking[501] == ()
    assert blocking[502] == ({"kind": "consortium_review", "text": "20억 원 이상 · 컨소시엄 검토"},)


def test_deadline_short_uses_kst_days_and_the_policy_window(policy) -> None:
    rules = company_rules(_projection())
    seven = _notice("홈페이지 유지관리 7", deadline_days=7, notice_id=601)
    eight = _notice("홈페이지 유지관리 8", deadline_days=8, notice_id=602)
    result = build_recommendations([seven, eight], rules, policy, now=NOW)
    blocking = {item.candidate.notice_id: item.blocking for item in result.items}
    assert blocking[601] == ({"kind": "deadline_short", "text": "마감 7일"},)
    assert blocking[602] == ()


# --- T2 ----------------------------------------------------------------------


def test_t2_proposed_facts_never_reach_the_rules(policy) -> None:
    """제공자가 거르지 못한 `proposed`·`unknown` 사실도 규칙이 다시 걸러 낸다."""

    proposed = _projection(_facts(status="proposed"))
    rules = company_rules(proposed)
    assert rules.domains == () and rules.agencies == () and rules.projects == ()
    assert rules.exclusion_keywords == {} and rules.allowed_regions is None
    assert rules.amount_floor_krw is None and rules.amount_range is None
    candidate = _notice("대구테크노파크 홈페이지 유지관리", agency="대구테크노파크",
                        estimated_price=20_000_000, notice_id=701, sw="N")
    result = build_recommendations([candidate], rules, policy, now=NOW)
    assert result.items == ()
    assert result.unscored_count == 1
    assert set(result.excluded_counts.values()) == {0}

    unknown = [
        _fact("pref:domain:01", "domain", None, status="unknown"),
        *[fact for fact in _facts() if fact.fact_key != "pref:domain:01"],
    ]
    mixed = company_rules(_projection(unknown))
    assert [domain.fact_key for domain in mixed.domains] == ["pref:domain:02", "pref:domain:03"]


def test_t2_only_the_proposed_domain_is_ignored(policy) -> None:
    facts = _facts()
    facts[0] = _fact("pref:domain:01", "domain", _domain(1, ["유지관리", "홈페이지"]), status="proposed")
    rules = company_rules(_projection(facts))
    candidate = _notice("홈페이지 유지관리", sw="N", notice_id=702)
    result = build_recommendations([candidate], rules, policy, now=NOW)
    assert result.items == () and result.unscored_count == 1


# --- T3 ----------------------------------------------------------------------


def test_t3_tracked_change_one_row_for_tracked_and_none_for_untracked(policy) -> None:
    observations = [
        TrackedChangeObservation(notice_id=11, opportunity_id=1, tracking_status="계속 추적",
                                 changed_fields=("deadline_at",)),
        TrackedChangeObservation(notice_id=11, opportunity_id=1, tracking_status="계속 추적",
                                 changed_fields=("url", "title")),
        TrackedChangeObservation(notice_id=12, opportunity_id=2, tracking_status="미선택",
                                 changed_fields=("deadline_at",)),
        TrackedChangeObservation(notice_id=13, opportunity_id=3, tracking_status="보류",
                                 changed_fields=("agency",)),
        TrackedChangeObservation(notice_id=14, opportunity_id=4, tracking_status="종료",
                                 changed_fields=("deadline_at",)),
        TrackedChangeObservation(notice_id=15, opportunity_id=5, tracking_status="보류",
                                 changed_fields={"budget": {"old": 1, "new": 2}}),
    ]
    changes = tracked_changes(observations, policy)
    assert [(change.notice_id, change.opportunity_id, change.change_fields) for change in changes] == [
        (11, 1, ("deadline_at", "title")),
        (15, 5, ("budget",)),
    ]
    assert tracked_changes(list(reversed(observations)), policy) == changes


def test_t3_recommendation_row_absorbs_the_change_of_the_same_notice(policy) -> None:
    rules = company_rules(_projection())
    recommended = _notice("홈페이지 유지관리", notice_id=21)
    result = build_recommendations([recommended], rules, policy, now=NOW)
    changes = tracked_changes(
        [
            TrackedChangeObservation(notice_id=21, opportunity_id=9, tracking_status="계속 추적",
                                     changed_fields=("title",)),
            TrackedChangeObservation(notice_id=22, opportunity_id=8, tracking_status="보류",
                                     changed_fields=("estimated_price", "deadline_at")),
        ],
        policy,
    )
    items, remaining = merge_tracked_changes(result.items, changes)
    assert [(item.candidate.notice_id, item.change_fields) for item in items] == [(21, ("title",))]
    assert [(change.notice_id, change.change_fields) for change in remaining] == [
        (22, ("deadline_at", "estimated_price")),
    ]
    # 원래 결과는 바뀌지 않는다(순수 함수).
    assert result.items[0].change_fields == ()



# --- RL-02 T5: 마감 알림 -------------------------------------------------------

KST = ZoneInfo("Asia/Seoul")
#: 브리핑 날짜(금). D-3 = 10-19(월), D-1 = 10-17(토).
BRIEF_DATE = date(2026, 10, 16)


def _due(notice_id: int, days: int, *, status: str = "계속 추적", source_type: str = "bid_notice",
         at: datetime | None = None, opportunity_id: int | None = None) -> DeadlineReminderCandidate:
    deadline = at if at is not None else datetime(2026, 10, 16, 10, 0, tzinfo=KST) + timedelta(days=days)
    return DeadlineReminderCandidate(
        notice_id=notice_id,
        opportunity_id=opportunity_id if opportunity_id is not None else notice_id + 100,
        tracking_status=status,
        source_type=source_type,
        deadline_at=deadline,
    )


def test_t5_reminders_only_for_tracked_or_held_bid_notices_on_d3_and_d1(policy) -> None:
    candidates = [
        _due(1, 3),                                   # 계속 추적 D-3
        _due(2, 1, status="보류"),                     # 보류 D-1
        _due(3, 3, status="미선택"),                   # 미추적
        _due(4, 1, status="종료"),                     # 종료
        _due(5, 3, source_type="pre_spec"),           # 사전규격 의견 마감은 대상 아님
        _due(6, 3, source_type="pre_spec_public"),
        _due(7, 2),                                   # D-2
        _due(8, 0),                                   # 당일
        _due(9, -1),                                  # 지난 마감
        _due(10, 4),
        DeadlineReminderCandidate(notice_id=11, opportunity_id=111, tracking_status="계속 추적",
                                  source_type="bid_notice", deadline_at=None),
        _due(1, 3),                                   # 같은 공고가 두 번 와도 1행
    ]
    reminders = deadline_reminders(candidates, policy, BRIEF_DATE)
    assert [(item.notice_id, item.opportunity_id, item.change_fields) for item in reminders] == [
        (1, 101, (DEADLINE_REMINDER_FIELD,)),
        (2, 102, (DEADLINE_REMINDER_FIELD,)),
    ]
    assert deadline_reminders(list(reversed(candidates)), policy, BRIEF_DATE) == reminders
    assert DEADLINE_REMINDER_FIELD == "deadline_reminder"


def test_t5_reminder_day_is_the_kst_date_of_the_deadline(policy) -> None:
    # 2026-10-18 15:30Z = 10-19 00:30 KST → D-3 (UTC 날짜로는 D-2).
    early = _due(1, 0, at=datetime(2026, 10, 18, 15, 30, tzinfo=UTC))
    # 2026-10-19 14:59Z = 10-19 23:59 KST → D-3.
    late = _due(2, 0, at=datetime(2026, 10, 19, 14, 59, tzinfo=UTC))
    # 2026-10-19 15:00Z = 10-20 00:00 KST → D-4.
    after = _due(3, 0, at=datetime(2026, 10, 19, 15, 0, tzinfo=UTC))
    reminders = deadline_reminders([early, late, after], policy, BRIEF_DATE)
    assert [item.notice_id for item in reminders] == [1, 2]


def test_t5_v1_policy_has_no_deadline_reminders() -> None:
    v1 = load_briefing_policy(V1_POLICY_PATH)
    assert deadline_reminders([_due(1, 3), _due(2, 1)], v1, BRIEF_DATE) == ()


def test_t5_same_notice_correction_and_reminder_merge_into_one_row(policy) -> None:
    corrections = tracked_changes(
        [
            TrackedChangeObservation(notice_id=1, opportunity_id=101, tracking_status="계속 추적",
                                     changed_fields=("title", "method")),
            TrackedChangeObservation(notice_id=4, opportunity_id=104, tracking_status="보류",
                                     changed_fields=("deadline_at",)),
        ],
        policy,
    )
    # v2는 `method`도 추적 필드다.
    assert [change.change_fields for change in corrections] == [("title", "method"), ("deadline_at",)]
    reminders = deadline_reminders([_due(1, 3), _due(2, 1, status="보류")], policy, BRIEF_DATE)
    combined = combine_tracked_changes(corrections, reminders)
    assert [(item.notice_id, item.opportunity_id, item.change_fields) for item in combined] == [
        (1, 101, ("title", "method", "deadline_reminder")),
        (2, 102, ("deadline_reminder",)),
        (4, 104, ("deadline_at",)),
    ]
    assert [tracked_change_verdict(item.change_fields) for item in combined] == ["재검토 중", "마감 임박", "재검토 중"]
    # 입력은 그대로다(순수 함수), 이미 사유가 있으면 두 번 넣지 않는다.
    assert corrections[0].change_fields == ("title", "method")
    assert combine_tracked_changes(combined, reminders) == combined


def test_t5_reminder_on_a_recommended_notice_goes_into_the_recommendation_row(policy) -> None:
    rules = company_rules(_projection())
    recommended = _notice("홈페이지 유지관리", stage="bid_notice", notice_id=31)
    result = build_recommendations([recommended], rules, policy, now=NOW)
    combined = combine_tracked_changes((), (TrackedChange(notice_id=31, opportunity_id=9,
                                                          change_fields=(DEADLINE_REMINDER_FIELD,)),))
    items, remaining = merge_tracked_changes(result.items, combined)
    assert [(item.candidate.notice_id, item.change_fields) for item in items] == [(31, ("deadline_reminder",))]
    assert remaining == ()
