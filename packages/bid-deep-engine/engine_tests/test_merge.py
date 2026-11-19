"""M3-01 partial 병합 규칙 테스트(spec M3-01 "병합 규칙", T1~T9, T13).

네트워크·LLM을 쓰지 않는다. 합성 `RfpFactsPartial`만 쓴다.
"""

import types
import unicodedata
from pathlib import Path
from typing import Union, get_args, get_origin

import pytest
from pydantic import BaseModel, Field

from bid_deep_engine.analysis import merge
from bid_deep_engine.analysis.evidence import verify_facts
from bid_deep_engine.analysis.merge import MERGE_RULES, MergeError, merge_partials, normalize_text
from bid_deep_engine.analysis.schemas import (
    CommercialSw,
    Conflict,
    ContractTerms,
    Criterion,
    EligibilityRule,
    EvalItem,
    Evaluation,
    Evidence,
    Period,
    Project,
    QualItem,
    RfpFacts,
    RfpFactsPartial,
    RuleParams,
    Schedule,
    SourceLocation,
    StaffingReq,
    Subcontract,
    SubmissionDoc,
    SystemEnv,
    iter_evidence,
)
from bid_deep_engine.ingest.models import RfpDocument


def _ev(quote: str, section_id: str | None = "S001") -> Evidence:
    return Evidence(quote=quote, section_id=section_id)


# ---------------------------------------------------------------- normalize_text


def test_normalize_text_nfc_strip_collapse():
    nfd = unicodedata.normalize("NFD", " 제한\t\n 경쟁 ")
    assert normalize_text(nfd) == "제한 경쟁"
    assert normalize_text("a  b") == "a b"
    assert normalize_text("") == ""


# ---------------------------------------------------------------- T1 스칼라 첫 non-null


def test_t1_scalar_first_non_null():
    p1 = RfpFactsPartial(project=Project(budget_krw=None))
    p2 = RfpFactsPartial(project=Project(budget_krw=430000000))
    facts = merge_partials([p1, p2])
    assert isinstance(facts, RfpFacts)
    assert facts.project.budget_krw == 430000000
    assert facts.conflicts == []


def test_t1_top_level_none_does_not_contribute():
    p1 = RfpFactsPartial(project=None)
    p2 = RfpFactsPartial(project=Project(agency="외교부", evidence=[_ev("외교부")]))
    p3 = RfpFactsPartial(project=Project(agency="외교부"))
    facts = merge_partials([p1, p2, p3])
    assert facts.project.agency == "외교부"
    assert facts.project.evidence == [_ev("외교부")]
    assert facts.conflicts == []


def test_t1_nested_object_scalar_first_non_null():
    p1 = RfpFactsPartial(project=Project(period=Period(months=None, days=10)))
    p2 = RfpFactsPartial(project=Project(period=Period(months=12)))
    facts = merge_partials([p1, p2])
    assert facts.project.period.months == 12
    assert facts.project.period.days == 10
    assert facts.conflicts == []


# ---------------------------------------------------------------- T2 스칼라 충돌


def test_t2_scalar_conflict_with_evidence():
    e1 = _ev("사업예산 430,000,000원", "S002")
    e2 = _ev("사업예산 390,000,000원", "S010")
    p1 = RfpFactsPartial(project=Project(budget_krw=430000000, evidence=[e1]))
    p2 = RfpFactsPartial(project=Project(budget_krw=390000000, evidence=[e2]))
    facts = merge_partials([p1, p2])
    assert facts.project.budget_krw == 430000000
    assert facts.conflicts == [
        Conflict(field="project.budget_krw", values=["430000000", "390000000"], evidence=[e1, e2])
    ]


def test_t2_conflict_evidence_is_first_item_of_owner_list():
    e1a, e1b = _ev("a1"), _ev("a2")
    e2a = _ev("b1", "S009")
    p1 = RfpFactsPartial(evaluation=Evaluation(tech_weight=80, evidence=[e1a, e1b]))
    p2 = RfpFactsPartial(evaluation=Evaluation(tech_weight=90, evidence=[e2a]))
    facts = merge_partials([p1, p2])
    assert facts.evaluation.tech_weight == 80
    assert facts.conflicts == [
        Conflict(field="evaluation.tech_weight", values=["80", "90"], evidence=[e1a, e2a])
    ]


def test_t2_conflict_order_follows_schema_declaration():
    # partial 순서상 evaluation 충돌이 먼저 보여도 conflicts는 표 순(project → evaluation).
    p1 = RfpFactsPartial(
        evaluation=Evaluation(tech_weight=80),
        project=Project(period=Period(months=12), budget_krw=1),
    )
    p2 = RfpFactsPartial(
        evaluation=Evaluation(tech_weight=90, price_weight=10),
        project=Project(period=Period(months=6), budget_krw=2),
    )
    p3 = RfpFactsPartial(
        evaluation=Evaluation(price_weight=20),
        contract_terms=ContractTerms(warranty_months=12),
    )
    p4 = RfpFactsPartial(contract_terms=ContractTerms(warranty_months=24))
    facts = merge_partials([p1, p2, p3, p4])
    assert [c.field for c in facts.conflicts] == [
        "project.budget_krw",
        "project.period.months",
        "evaluation.tech_weight",
        "evaluation.price_weight",
        "contract_terms.warranty_months",
    ]


# ---------------------------------------------------------------- T3 같은 값·형식 변형


def test_t3_string_normalized_equal_no_conflict():
    nfd = unicodedata.normalize("NFD", " 제한  경쟁")
    p1 = RfpFactsPartial(project=Project(contract_method="제한 경쟁"))
    p2 = RfpFactsPartial(project=Project(contract_method=" 제한  경쟁"))
    p3 = RfpFactsPartial(project=Project(contract_method=nfd))
    facts = merge_partials([p1, p2, p3])
    assert facts.project.contract_method == "제한 경쟁"  # 채택값은 첫 원문 그대로
    assert facts.conflicts == []


def test_t3_adopted_string_is_first_raw_value():
    p1 = RfpFactsPartial(project=Project(contract_method=" 제한  경쟁 "))
    p2 = RfpFactsPartial(project=Project(contract_method="제한 경쟁"))
    facts = merge_partials([p1, p2])
    assert facts.project.contract_method == " 제한  경쟁 "
    assert facts.conflicts == []


def test_t3_bool_conflict_stringified():
    e1, e2 = _ev("하도급 불가"), _ev("하도급 가능", "S020")
    p1 = RfpFactsPartial(
        contract_terms=ContractTerms(subcontract=Subcontract(allowed=False), evidence=[e1])
    )
    p2 = RfpFactsPartial(
        contract_terms=ContractTerms(subcontract=Subcontract(allowed=True), evidence=[e2])
    )
    facts = merge_partials([p1, p2])
    assert facts.contract_terms.subcontract.allowed is False
    assert facts.conflicts == [
        Conflict(
            field="contract_terms.subcontract.allowed",
            values=["false", "true"],
            evidence=[e1, e2],
        )
    ]


def test_t3_three_values_in_order_evidence_skips_empty_owner():
    e1, e3 = _ev("12개월"), _ev("24개월", "S030")
    p1 = RfpFactsPartial(project=Project(period=Period(months=12), evidence=[e1]))
    p2 = RfpFactsPartial(project=Project(period=Period(months=6)))  # 소유 evidence 빈 partial
    p3 = RfpFactsPartial(project=Project(period=Period(months=24), evidence=[e3]))
    p4 = RfpFactsPartial(project=Project(period=Period(months=6), evidence=[_ev("6개월")]))
    facts = merge_partials([p1, p2, p3, p4])
    assert facts.project.period.months == 12
    assert facts.conflicts == [
        Conflict(field="project.period.months", values=["12", "6", "24"], evidence=[e1, e3])
    ]


def test_t3_float_and_enum_stringified():
    p1 = RfpFactsPartial(
        evaluation=Evaluation(qualifying_threshold=85.0, qualifying_basis="points")
    )
    p2 = RfpFactsPartial(
        evaluation=Evaluation(qualifying_threshold=85.5, qualifying_basis="percent")
    )
    facts = merge_partials([p1, p2])
    by_field = {c.field: c.values for c in facts.conflicts}
    assert by_field == {
        "evaluation.qualifying_threshold": ["85.0", "85.5"],
        "evaluation.qualifying_basis": ["points", "percent"],
    }


def test_t3_system_env_conflict_has_no_evidence():
    p1 = RfpFactsPartial(system_env=SystemEnv(framework="전자정부프레임워크 3.x"))
    p2 = RfpFactsPartial(system_env=SystemEnv(framework="Spring Boot"))
    facts = merge_partials([p1, p2])
    assert facts.system_env.framework == "전자정부프레임워크 3.x"
    assert facts.conflicts == [
        Conflict(
            field="system_env.framework",
            values=["전자정부프레임워크 3.x", "Spring Boot"],
            evidence=[],
        )
    ]


# ---------------------------------------------------------------- T4 eligibility 키


def test_t4_eligibility_key_same_params_different_text():
    params_a = RuleParams.model_validate({"region": ["서울"], "item_no": ["8111159901"]})
    params_b = RuleParams.model_validate({"item_no": ["8111159901"], "region": ["서울"]})
    r1 = EligibilityRule(code="REGION_LIMIT", text="첫 문장", params=params_a, evidence=_ev("a"))
    r2 = EligibilityRule(code="REGION_LIMIT", text="다른 문장", params=params_b, evidence=_ev("b"))
    facts = merge_partials([RfpFactsPartial(eligibility=[r1]), RfpFactsPartial(eligibility=[r2])])
    assert facts.eligibility == [r1]
    assert facts.eligibility[0].text == "첫 문장"


def test_t4_eligibility_key_different_item_no_kept_in_order():
    r1 = EligibilityRule(
        code="DIRECT_PRODUCTION",
        text="직접생산 1",
        params=RuleParams(item_no=["A"]),
        evidence=_ev("a"),
    )
    r2 = EligibilityRule(
        code="DIRECT_PRODUCTION",
        text="직접생산 2",
        params=RuleParams(item_no=["B"]),
        evidence=_ev("b"),
    )
    r3 = EligibilityRule(code="G2B_REGISTERED", text="등록", evidence=_ev("c"))
    facts = merge_partials(
        [RfpFactsPartial(eligibility=[r1, r3]), RfpFactsPartial(eligibility=[r2, r3])]
    )
    assert facts.eligibility == [r1, r3, r2]


def test_t4_eligibility_item_no_order_matters_and_is_not_merged():
    # 키 JSON은 키만 정렬하고 리스트 값 순서는 유지 → 순서 다른 item_no는 다른 키.
    r1 = EligibilityRule(
        code="INDUSTRY_CODE", text="t", params=RuleParams(item_no=["A", "B"]), evidence=_ev("a")
    )
    r2 = EligibilityRule(
        code="INDUSTRY_CODE", text="t", params=RuleParams(item_no=["B", "A"]), evidence=_ev("a")
    )
    facts = merge_partials([RfpFactsPartial(eligibility=[r1]), RfpFactsPartial(eligibility=[r2])])
    assert facts.eligibility == [r1, r2]
    assert facts.eligibility[0].params.item_no == ["A", "B"]


# ---------------------------------------------------------------- T5 staffing 키


def test_t5_staffing_key():
    s1 = StaffingReq(role="PM", grade="고급", location="서울", count=1, evidence=_ev("a"))
    s2 = StaffingReq(role="PM", grade="고급", location="서울", count=None, evidence=_ev("b"))
    s3 = StaffingReq(role="PM", grade="고급", location="세종", count=1, evidence=_ev("c"))
    facts = merge_partials([RfpFactsPartial(staffing=[s1]), RfpFactsPartial(staffing=[s2, s3])])
    assert facts.staffing == [s1, s3]
    assert facts.staffing[0].count == 1


def test_t5_staffing_key_includes_none():
    s1 = StaffingReq(role="개발자", grade=None, location=None, evidence=_ev("a"))
    s2 = StaffingReq(role="개발자", grade=None, location=None, notes="x", evidence=_ev("b"))
    s3 = StaffingReq(role="개발자", grade="중급", location=None, evidence=_ev("c"))
    facts = merge_partials([RfpFactsPartial(staffing=[s1, s2, s3])])
    assert facts.staffing == [s1, s3]


# ---------------------------------------------------------------- T6 기타 키 병합 리스트


def test_t6_quantitative_normalized_item_key():
    q1 = EvalItem(item="신용평가  등급", max_points=10, kind="CREDIT_RATING", evidence=_ev("a"))
    q2 = EvalItem(item="신용평가 등급", max_points=5, kind="CREDIT_RATING", evidence=_ev("b"))
    q3 = EvalItem(item="수행실적", max_points=10, kind="PAST_PERFORMANCE", evidence=_ev("c"))
    facts = merge_partials(
        [
            RfpFactsPartial(evaluation=Evaluation(quantitative=[q1])),
            RfpFactsPartial(evaluation=Evaluation(quantitative=[q2, q3])),
        ]
    )
    assert facts.evaluation.quantitative == [q1, q3]
    assert facts.conflicts == []  # 항목 내부 필드는 비교하지 않는다


def test_t6_qualitative_raw_item_key():
    a = QualItem(item="사업 이해도", max_points=10)
    b = QualItem(item="사업  이해도", max_points=10)
    c = QualItem(item="사업 이해도", max_points=5)
    facts = merge_partials(
        [
            RfpFactsPartial(evaluation=Evaluation(qualitative=[a])),
            RfpFactsPartial(evaluation=Evaluation(qualitative=[b, c])),
        ]
    )
    assert facts.evaluation.qualitative == [a, b]


def test_t6_commercial_sw_and_submission_docs_condition_and_evidence_key():
    sw1 = CommercialSw(name="Oracle", vendor="Oracle", evidence=_ev("a"))
    sw2 = CommercialSw(name="Oracle", vendor=None, evidence=_ev("b"))
    sw3 = CommercialSw(name="JEUS", evidence=_ev("c"))
    d1 = SubmissionDoc(name="제안서", due="2026-11-01", evidence=_ev("d"))
    d2 = SubmissionDoc(name="제안서", due=None, evidence=_ev("e"))
    d3 = SubmissionDoc(name="가격제안서", evidence=_ev("f"))
    facts = merge_partials(
        [
            RfpFactsPartial(commercial_sw=[sw1], submission_docs=[d1]),
            RfpFactsPartial(commercial_sw=[sw2, sw3], submission_docs=[d2, d3]),
        ]
    )
    assert facts.commercial_sw == [sw1, sw3]
    assert facts.submission_docs == [d1, d2, d3]


def test_rev04_t3_submission_docs_preserve_all_conditions_and_non_location_evidence():
    location = SourceLocation(file="notice.pdf", file_sha256="0" * 64, page=1, start=0, end=2)
    base_evidence = Evidence(
        quote="제안서 10부",
        section_id="S010",
        page=4,
        verified=True,
        repaired=False,
        locations=[location],
        location_status="exact",
    )
    base = SubmissionDoc(
        name="제안서",
        due="11월 5일 10시",
        copies="10부",
        stage="입찰등록 시",
        condition="직접 제출",
        evidence=base_evidence,
    )
    same_except_code_owned_location = base.model_copy(deep=True)
    same_except_code_owned_location.evidence.locations = []
    same_except_code_owned_location.evidence.location_status = "unavailable"
    variants = [
        base.model_copy(update={"due": "11월 6일 10시"}, deep=True),
        base.model_copy(update={"copies": "1부"}, deep=True),
        base.model_copy(update={"stage": "제안서 제출 시"}, deep=True),
        base.model_copy(update={"condition": None}, deep=True),
        base.model_copy(
            update={"evidence": base_evidence.model_copy(update={"page": 5}, deep=True)},
            deep=True,
        ),
        base.model_copy(
            update={"evidence": base_evidence.model_copy(update={"verified": False}, deep=True)},
            deep=True,
        ),
        base.model_copy(
            update={"evidence": base_evidence.model_copy(update={"repaired": True}, deep=True)},
            deep=True,
        ),
    ]
    facts = merge_partials(
        [
            RfpFactsPartial(submission_docs=[base]),
            RfpFactsPartial(submission_docs=[same_except_code_owned_location, *variants]),
        ]
    )

    assert len(facts.submission_docs) == 1 + len(variants)
    # 위치 메타데이터만 다른 항목은 병합되고, merge가 위치를 비운 첫 항목이 남는다.
    expected_first = base.model_copy(deep=True)
    expected_first.evidence.locations = []
    expected_first.evidence.location_status = "unavailable"
    assert facts.submission_docs[0] == expected_first
    assert {item.evidence.page for item in facts.submission_docs} == {4, 5}
    assert {item.evidence.verified for item in facts.submission_docs} == {True, False}
    assert {item.evidence.repaired for item in facts.submission_docs} == {False, True}
    assert all(item.evidence.locations == [] for item in facts.submission_docs)


def test_t6_deliverables_normalized_key_keeps_first_raw():
    nfd = unicodedata.normalize("NFD", "착수 보고서")
    facts = merge_partials(
        [
            RfpFactsPartial(deliverables=[" 착수  보고서", "완료보고서"]),
            RfpFactsPartial(deliverables=[nfd, "착수 보고서", "산출물 목록"]),
        ]
    )
    assert facts.deliverables == [" 착수  보고서", "완료보고서", "산출물 목록"]


def test_t6_empty_list_contributes_nothing():
    facts = merge_partials(
        [
            RfpFactsPartial(deliverables=[]),
            RfpFactsPartial(deliverables=None),
            RfpFactsPartial(deliverables=["x"]),
        ]
    )
    assert facts.deliverables == ["x"]


# ---------------------------------------------------------------- T7 evidence 리스트 4종


@pytest.mark.parametrize(
    ("field", "factory"),
    [
        ("project", Project),
        ("schedule", Schedule),
        ("evaluation", Evaluation),
        ("contract_terms", ContractTerms),
    ],
)
def test_t7_evidence_lists_concat_dedup(field, factory):
    shared = _ev("공통 인용", "S001")
    a = _ev("앞 인용", "S001")
    b = _ev("뒤 인용", "S005")
    same_quote_other_section = _ev("공통 인용", "S009")
    p1 = RfpFactsPartial(**{field: factory(evidence=[a, shared])})
    p2 = RfpFactsPartial(
        **{field: factory(evidence=[_ev("공통 인용", "S001"), b, same_quote_other_section])}
    )
    facts = merge_partials([p1, p2])
    assert getattr(facts, field).evidence == [a, shared, b, same_quote_other_section]


def test_t7_evidence_dedup_uses_raw_quote_and_ignores_verify_fields():
    e1 = Evidence(quote="인용", section_id="S001", page=3)
    e2 = Evidence(quote="인용", section_id="S001", page=None, verified=True)
    e3 = Evidence(quote="인용 ", section_id="S001")  # 원문 문자열이 다르면 다른 항목
    facts = merge_partials(
        [
            RfpFactsPartial(schedule=Schedule(evidence=[e1])),
            RfpFactsPartial(schedule=Schedule(evidence=[e2, e3])),
        ]
    )
    assert facts.schedule.evidence == [e1, e3]


# ---------------------------------------------------------------- T8 누락


def test_t8_all_none_schedule_is_empty_instance():
    facts = merge_partials(
        [RfpFactsPartial(schedule=None), RfpFactsPartial(project=Project(agency="x"))]
    )
    assert facts.schedule == Schedule()
    assert facts.schedule.evidence == []
    assert facts.schedule.submission_deadline is None


def test_t8_all_none_project_name_stays_none():
    facts = merge_partials([RfpFactsPartial(), RfpFactsPartial(project=None)])
    assert facts.project == Project()
    assert facts.project.name is None
    assert facts.project.evidence == []
    assert facts == RfpFacts()


def test_t8_no_partials_raises_merge_error():
    with pytest.raises(MergeError, match="^no partials$"):
        merge_partials([])
    assert issubclass(MergeError, ValueError)


def test_t8_conflicts_only_from_merge():
    assert "conflicts" not in RfpFactsPartial.model_fields
    p = RfpFactsPartial(project=Project(name="사업", budget_krw=1))
    facts = merge_partials([p])
    assert facts.conflicts == []
    assert facts.project.name == "사업"
    assert facts.schema_version == RfpFacts().schema_version


# ---------------------------------------------------------------- T9 키 표 완전성


EXPECTED_LIST_PATHS = {
    "project.evidence",
    "project.evidence[].locations",
    "schedule.evidence",
    "schedule.evidence[].locations",
    "eligibility",
    "eligibility[].params.item_no",
    "eligibility[].params.industry_code",
    "eligibility[].params.region",
    "eligibility[].evidence.locations",
    "evaluation.quantitative",
    "evaluation.quantitative[].criteria",
    "evaluation.quantitative[].evidence.locations",
    "evaluation.qualitative",
    "evaluation.evidence",
    "evaluation.evidence[].locations",
    "staffing",
    "staffing[].evidence.locations",
    "contract_terms.evidence",
    "contract_terms.evidence[].locations",
    "commercial_sw",
    "commercial_sw[].evidence.locations",
    "deliverables",
    "submission_docs",
    "submission_docs[].evidence.locations",
    "conflicts",
    "conflicts[].values",
    "conflicts[].evidence",
    "conflicts[].evidence[].locations",
}


def _unwrap_optional(ann: object) -> object:
    if get_origin(ann) in (Union, types.UnionType):
        args = [a for a in get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _walk_list_paths(model: type[BaseModel], prefix: str = "") -> set[str]:
    """테스트 쪽 독립 구현: 타입 주석을 재귀로 훑어 리스트 경로를 모은다."""
    paths: set[str] = set()
    for name, field in model.model_fields.items():
        ann = _unwrap_optional(field.annotation)
        path = f"{prefix}{name}"
        if get_origin(ann) is list:
            paths.add(path)
            item = _unwrap_optional(get_args(ann)[0])
            if isinstance(item, type) and issubclass(item, BaseModel):
                paths |= _walk_list_paths(item, f"{path}[].")
        elif isinstance(ann, type) and issubclass(ann, BaseModel):
            paths |= _walk_list_paths(ann, f"{path}.")
    return paths


def test_t9_merge_rules_cover_all_list_paths():
    assert _walk_list_paths(RfpFacts) == set(MERGE_RULES) == EXPECTED_LIST_PATHS
    assert all(isinstance(v, str) and v for v in MERGE_RULES.values())


def test_t9_evidence_locations_are_code_owned_and_cleared_by_merge():
    location = SourceLocation(file="notice.pdf", file_sha256="0" * 64, page=1, start=0, end=2)
    evidence = Evidence(quote="근거", locations=[location], location_status="exact", verified=True)
    facts = merge_partials([RfpFactsPartial(project=Project(name="사업", evidence=[evidence]))])

    assert facts.project.evidence[0].quote == "근거"
    assert facts.project.evidence[0].verified is True
    assert facts.project.evidence[0].locations == []
    assert facts.project.evidence[0].location_status == "unavailable"


def test_t9_unknown_top_level_list_raises(monkeypatch):
    class FakeFacts(RfpFacts):
        extra_tags: list[str] = Field(default_factory=list)

    monkeypatch.setattr(merge, "RfpFacts", FakeFacts)
    with pytest.raises(TypeError, match=r"^no merge key for extra_tags$"):
        merge_partials([RfpFactsPartial()])


def test_t9_unknown_nested_list_raises(monkeypatch):
    class FakeQualItem(QualItem):
        notes: list[str] = Field(default_factory=list)

    class FakeEvaluation(Evaluation):
        qualitative: list[FakeQualItem] = Field(default_factory=list)

    class FakeFacts(RfpFacts):
        evaluation: FakeEvaluation = Field(default_factory=FakeEvaluation)

    monkeypatch.setattr(merge, "RfpFacts", FakeFacts)
    with pytest.raises(TypeError, match=r"^no merge key for evaluation\.qualitative\[\]\.notes$"):
        merge_partials([RfpFactsPartial()])


def test_t9_item_internal_criteria_not_merged():
    q1 = EvalItem(
        item="신용평가 등급",
        max_points=10,
        kind="CREDIT_RATING",
        criteria=[Criterion(condition="AA 이상", points=10)],
        evidence=_ev("a"),
    )
    q2 = EvalItem(
        item="신용평가  등급",
        max_points=10,
        kind="CREDIT_RATING",
        criteria=[Criterion(condition="A 이상", points=8), Criterion(condition="B", points=6)],
        evidence=_ev("b"),
    )
    facts = merge_partials(
        [
            RfpFactsPartial(evaluation=Evaluation(quantitative=[q1])),
            RfpFactsPartial(evaluation=Evaluation(quantitative=[q2])),
        ]
    )
    assert len(facts.evaluation.quantitative) == 1
    assert facts.evaluation.quantitative[0].criteria == [Criterion(condition="AA 이상", points=10)]
    assert facts.conflicts == []


# ---------------------------------------------------------------- 결정성·입력 불변


def _sample_partials() -> list[RfpFactsPartial]:
    return [
        RfpFactsPartial(
            project=Project(budget_krw=430000000, evidence=[_ev("a", "S001")]),
            eligibility=[EligibilityRule(code="G2B_REGISTERED", text="t", evidence=_ev("g"))],
            deliverables=["착수보고서"],
        ),
        RfpFactsPartial(
            project=Project(budget_krw=390000000, evidence=[_ev("b", "S002")]),
            system_env=SystemEnv(cms="X"),
            deliverables=["착수보고서", "완료보고서"],
        ),
    ]


def test_merge_is_deterministic_and_does_not_mutate_inputs():
    partials = _sample_partials()
    before = [p.model_dump_json() for p in partials]
    first = merge_partials(partials)
    second = merge_partials(_sample_partials())
    assert first.model_dump_json() == second.model_dump_json()
    assert [p.model_dump_json() for p in partials] == before


def test_merge_result_shares_no_evidence_instances_with_inputs():
    partials = _sample_partials()
    facts = merge_partials(partials)
    input_ids = {id(e) for p in partials for e in _all_evidence(p)}
    output = list(_all_evidence(facts))
    assert output
    assert not input_ids & {id(e) for e in output}
    # 결과 안에서도 공유 없음(verify가 제자리에서 고친다)
    assert len({id(e) for e in output}) == len(output)


def _all_evidence(model: BaseModel):
    return iter_evidence(model, include_conflicts=True)


# ---------------------------------------------------------------- T13 병합 후 검증


def test_t13_verify_applies_to_conflict_evidence_but_stats_exclude_them():
    doc = RfpDocument.model_validate_json(
        (Path(__file__).parent / "fixtures" / "rfp_req3.json").read_text(encoding="utf-8")
    )
    e1 = _ev("사업금액: 150,000,000원(부가세 포함)", "S001")
    e2 = _ev("사업기간: 계약일로부터 10개월", "S001")
    merged = merge_partials(
        [
            RfpFactsPartial(project=Project(budget_krw=150000000, evidence=[e1])),
            RfpFactsPartial(project=Project(budget_krw=130000000, evidence=[e2])),
        ]
    )
    assert [c.field for c in merged.conflicts] == ["project.budget_krw"]

    facts, citations, warnings = verify_facts(merged, doc)

    assert warnings == []
    (conflict,) = facts.conflicts
    assert [e.verified for e in conflict.evidence] == [True, True]  # 원문에 있으면 True
    every = list(iter_evidence(facts, include_conflicts=True))
    assert all(e.verified is not None for e in every)
    assert citations.total == len(list(iter_evidence(facts))) == len(every) - 2  # 통계는 제외
