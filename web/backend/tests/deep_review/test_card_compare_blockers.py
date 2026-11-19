"""RL-10 compare rules ``card-compare-v2`` (policy v12): 상주 장소·제외 분야 blockers.

Every case states the ``card-compare-v1`` (policies v1..v11, unchanged) outcome next to
the v2 one, so the old behaviour is pinned as well.  Company facts here are synthetic
test fixtures, not Rootlab values: the structured values the v2 rules read
(``pref:onsite_cap.params.onsite_regions``, ``excl:*.requirement_terms``) do not
exist in company source v4 and must be confirmed by a person.  No model or network.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from uuid import UUID

import pytest

from app.core.company_ontology import CompanyKnowledgeValidationError, _domain_value
from app.deep_review.schemas.card_analysis import CardRequirementExtract
from app.deep_review.services.card_analysis import CardAnalysisValidationError
from app.deep_review.services.card_compare import (
    COMPARE_RULES_V1,
    COMPARE_RULES_V2,
    PLACE_TABLE_FILE,
    PLACE_TABLE_SHA256,
    compare_requirements,
    resolve_places,
    validate_requirement_compare,
)
from tests.deep_review.test_card_analysis import card_input, constraint, extract_item
from tests.deep_review.test_card_compare import _fact, synthetic_company


ONSITE = {"available": 6, "region": "대구"}
CAP_V4 = {"scope": "core", "description": "최대 상주 인력 6명", "params": {"count": 6}}  # no onsite_regions
CAP_DAEGU = {"scope": "core", "description": "최대 상주 인력 6명", "params": {"count": 6, "onsite_regions": "대구"}}
HW_V4 = {"tier": None, "keywords": ["하드웨어"], "excluded": True, "kind": "hardware"}  # no requirement_terms
HW_TERMS = {**HW_V4, "requirement_terms": ["하드웨어", "전산장비", "예비장비"]}


def _frozen(texts: list[str], facts: list[dict]) -> tuple[dict, list]:
    card = card_input(texts)
    return {"card_analysis": card.model_dump(mode="json"), **deepcopy(synthetic_company(facts))}, card.units


def _both(frozen: dict, item: dict):
    """(v1 row, v2 row) of one single-unit extract."""

    extract = CardRequirementExtract.model_validate({"schema_version": "bidops.requirement-extract.v1",
                                                     "items": [item]})
    return (compare_requirements(extract, frozen=frozen, rules=COMPARE_RULES_V1).items[0],
            compare_requirements(extract, frozen=frozen, rules=COMPARE_RULES_V2).items[0])


def _text_item(unit, quote: str, *, type_: str = "인력", value: str | None = None) -> dict:
    return extract_item(unit, type_=type_, constraints=[
        constraint(unit, kind="text", value=value or quote, unit_name=None, operator="eq", quote=quote)])


def _outcome(row) -> tuple[str, str, list[str]]:
    result = row.constraint_results[0]
    return row.fit_status, result.reason_code, result.fact_ids


# --- place table ----------------------------------------------------------------------------


def test_place_table_is_pinned_and_resolves_administrative_names_only() -> None:
    assert hashlib.sha256(PLACE_TABLE_FILE.read_bytes()).hexdigest() == PLACE_TABLE_SHA256
    assert resolve_places("원주시청 내 상주") == ({"강원"}, False)
    assert resolve_places("수원시 지정장소에서 근무") == ({"경기"}, False)
    assert resolve_places("수원시에서 지정한 장소") == ({"경기"}, False)
    assert resolve_places("강원특별자치도에서 지정한 장소에 파견") == ({"강원"}, False)
    assert resolve_places("대구광역시청") == ({"대구"}, False)
    assert resolve_places("상주시청 내 상주") == ({"경북"}, False)
    # not places: the verb "상주시키다", a common noun, a word split by a space, a street name
    for text in ("센터에 상주시켜야 한다", "경기 침체", "이동해 시스템", "세종로 청사", "발주기관이 지정한 장소"):
        assert resolve_places(text) == (set(), False), text
    # names under two 시·도 resolve nothing (ambiguous); a 시·도 next to them still resolves
    for text in ("중구청 내 상주", "고성군 지정 장소", "광주시청 상주"):
        assert resolve_places(text) == (set(), True), text
    assert resolve_places("부산 강서구") == ({"부산"}, True)


def test_changed_place_table_is_never_read(monkeypatch, tmp_path) -> None:
    from app.deep_review.services import card_compare

    changed = tmp_path / "places.json"
    changed.write_bytes(PLACE_TABLE_FILE.read_bytes().replace("원주시".encode(), "원주군".encode()))
    monkeypatch.setattr(card_compare, "PLACE_TABLE_FILE", changed)
    card_compare._place_table.cache_clear()
    try:
        with pytest.raises(CardAnalysisValidationError, match="card_compare_invalid"):
            resolve_places("원주시청")
    finally:
        card_compare._place_table.cache_clear()


# --- 상주 장소 -----------------------------------------------------------------------------


def test_onsite_place_outside_the_confirmed_region_list_is_a_gap_only_under_v2() -> None:
    text = "상주 기술인력은 1명 이상 지정하여 원주시청 내 상주, 중급기술자 이상"
    frozen, units = _frozen([text], [_fact("staff:onsite", "confirmed", ONSITE),
                                     _fact("pref:onsite_cap", "confirmed", CAP_DAEGU)])
    v1, v2 = _both(frozen, _text_item(units[0], text))
    # v1 (= RL-05 run): the role word 기술자 pre-empts the place comparison
    assert _outcome(v1) == ("unknown", "scope_unverified", ["staff:onsite"])
    assert _outcome(v2) == ("gap", "confirmed_contradiction", ["staff:onsite", "pref:onsite_cap"])
    evidence = {UUID(row["profile_evidence_id"]) for row in frozen["profile_evidence"]}
    assert set(v2.evidence_ids) == evidence and len(v2.evidence_ids) == 2


def test_v4_shaped_company_without_onsite_regions_stays_unknown() -> None:
    text = "- 상주: 강원특별자치도에서 지정한 장소에 파견"
    frozen, units = _frozen([text], [_fact("staff:onsite", "confirmed", ONSITE),
                                     _fact("pref:onsite_cap", "confirmed", CAP_V4)])
    v1, v2 = _both(frozen, _text_item(units[0], text))
    assert _outcome(v1) == ("unknown", "scope_unverified", ["staff:onsite"])
    assert _outcome(v2) == ("unknown", "unknown_fact", ["staff:onsite", "pref:onsite_cap"])
    assert v2.evidence_ids == []
    # no pref:onsite_cap at all: unknown as well, no fact id invented
    frozen, units = _frozen([text], [_fact("staff:onsite", "confirmed", ONSITE)])
    assert _outcome(_both(frozen, _text_item(units[0], text))[1]) == ("unknown", "unknown_fact", ["staff:onsite"])


@pytest.mark.parametrize("cap_status, onsite_status, reason", [
    ("proposed", "confirmed", "proposed_fact"),
    ("unknown", "confirmed", "unknown_fact"),
    ("confirmed", "proposed", "proposed_fact"),
    ("confirmed", "unknown", "unknown_fact"),
])
def test_unconfirmed_onsite_facts_are_unknown_never_gap(cap_status, onsite_status, reason) -> None:
    text = "상주인력은 수원시 지정장소에서 근무"
    frozen, units = _frozen([text], [
        _fact("staff:onsite", onsite_status, ONSITE if onsite_status != "unknown" else None),
        _fact("pref:onsite_cap", cap_status, CAP_DAEGU if cap_status != "unknown" else None),
    ])
    _v1, v2 = _both(frozen, _text_item(units[0], text))
    assert (v2.fit_status, v2.constraint_results[0].reason_code) == ("unknown", reason)
    assert v2.evidence_ids == []


@pytest.mark.parametrize("text", [
    "발주기관이 지정한 장소에 상주",           # no place name
    "통일부 요청 시 일정기간 동안 상주 원칙",    # an agency, not an administrative name
    "중구청 내 상주",                       # 중구 is in six 시·도
    "인력을 관제센터에 상주시켜야 한다",        # 상주시 + 켜 is the verb, not 경북 상주시
])
def test_unresolvable_or_ambiguous_place_is_place_unresolved(text) -> None:
    frozen, units = _frozen([text], [_fact("staff:onsite", "confirmed", ONSITE),
                                     _fact("pref:onsite_cap", "confirmed", CAP_DAEGU)])
    v1, v2 = _both(frozen, _text_item(units[0], text))
    assert v1.fit_status == "unknown" and v1.constraint_results[0].reason_code != "place_unresolved"
    assert _outcome(v2) == ("unknown", "place_unresolved", ["staff:onsite"])


def test_place_inside_the_region_is_met_and_a_mixed_place_is_not_a_gap() -> None:
    texts = ["대구광역시청 내 상주", "상주 장소: 대구광역시 또는 경상북도 지정 장소"]
    company = [_fact("staff:onsite", "confirmed", ONSITE), _fact("pref:onsite_cap", "confirmed", CAP_DAEGU)]
    frozen, units = _frozen(texts[:1], company)
    v1, v2 = _both(frozen, _text_item(units[0], texts[0]))
    assert _outcome(v1)[:2] == _outcome(v2)[:2] == ("met", "confirmed_match")
    frozen, units = _frozen(texts[1:], company)
    _v1, v2 = _both(frozen, _text_item(units[0], texts[1]))
    assert _outcome(v2) == ("unknown", "scope_unverified", ["staff:onsite", "pref:onsite_cap"])


def test_unparseable_company_region_list_is_unsupported_not_guessed() -> None:
    text = "원주시청 내 상주"
    cap = deepcopy(CAP_DAEGU)
    for value in ("대구 일대", "대구, ", "중구", "광주시", "대구광역시 수성구"):
        cap["params"]["onsite_regions"] = value
        frozen, units = _frozen([text], [_fact("staff:onsite", "confirmed", ONSITE),
                                         _fact("pref:onsite_cap", "confirmed", cap)])
        assert _outcome(_both(frozen, _text_item(units[0], text))[1]) == (
            "unknown", "unsupported_comparison", ["staff:onsite", "pref:onsite_cap"]), value
    cap["params"]["onsite_regions"] = "대구, 경상북도"   # a well-formed list still decides
    frozen, units = _frozen([text], [_fact("staff:onsite", "confirmed", ONSITE),
                                     _fact("pref:onsite_cap", "confirmed", cap)])
    assert _outcome(_both(frozen, _text_item(units[0], text))[1])[:2] == ("gap", "confirmed_contradiction")


def test_place_is_read_from_the_cited_clause_not_from_other_clauses() -> None:
    company = [_fact("staff:onsite", "confirmed", ONSITE), _fact("pref:onsite_cap", "confirmed", CAP_DAEGU)]
    # the place sits in the same clause as the quote, outside the quote: decisive
    block = "○ 원주시청 내에 기술인력 1명 이상 상주 ○ 상주인력 집기는 사업자 부담"
    frozen, units = _frozen([block], company)
    _v1, v2 = _both(frozen, _text_item(units[0], "기술인력 1명 이상 상주"))
    assert _outcome(v2)[:2] == ("gap", "confirmed_contradiction")
    # a place in another clause of the block is not the on-site place
    block = "○ 발주기관 지정 장소에 상주 ○ 국가정보자원관리원(광주)과 협조"
    frozen, units = _frozen([block], company)
    _v1, v2 = _both(frozen, _text_item(units[0], "발주기관 지정 장소에 상주"))
    assert _outcome(v2)[:2] == ("unknown", "place_unresolved")


def test_onsite_contradiction_decides_count_and_several_anchor_constraints() -> None:
    company = [_fact("staff:onsite", "confirmed", ONSITE), _fact("pref:onsite_cap", "confirmed", CAP_DAEGU),
               _fact("pref:consortium", "confirmed", {"scope": "core", "description": "공동수급 가능",
                                                      "params": {"allowed": True}})]
    count_text = "상주: 강원특별자치도에서 지정한 장소에 2명 이상 파견"
    frozen, units = _frozen([count_text], company)
    item = extract_item(units[0], constraints=[
        constraint(units[0], kind="count", value=2, unit_name="person", operator="gte", quote=count_text)])
    v1, v2 = _both(frozen, item)
    assert _outcome(v1)[:2] == ("met", "confirmed_match")      # 6 >= 2, the place never compared
    assert _outcome(v2) == ("gap", "confirmed_contradiction", ["staff:onsite", "pref:onsite_cap"])
    several = "공동수급 시에도 원주시청 내 상주"
    frozen, units = _frozen([several], company)
    v1, v2 = _both(frozen, _text_item(units[0], several))
    assert _outcome(v1) == ("unknown", "unmapped", [])          # two text anchors: not linked
    assert _outcome(v2)[:2] == ("gap", "confirmed_contradiction")
    # short of a contradiction a several-anchor quote stays unmapped (never met)
    several_daegu = "공동수급 시에도 대구광역시청 내 상주"
    frozen, units = _frozen([several_daegu], company)
    assert _outcome(_both(frozen, _text_item(units[0], several_daegu))[1]) == ("unknown", "unmapped", [])


def test_contradiction_decides_gap_before_the_contract_rule_only_under_v2() -> None:
    text = "- 상주: 강원특별자치도에서 지정한 장소에 파견"
    frozen, units = _frozen([text], [_fact("staff:onsite", "confirmed", ONSITE),
                                     _fact("pref:onsite_cap", "confirmed", CAP_DAEGU)])
    item = _text_item(units[0], text, type_="계약")
    v1, v2 = _both(frozen, item)
    assert v1.fit_status == "unknown" and "contract_unaccepted" in v1.reason_codes
    assert v2.fit_status == "gap" and "contract_unaccepted" in v2.reason_codes
    assert "confirmed_contradiction" in v2.reason_codes
    # a 계약 unit is still never met
    met_text = "대구광역시청 내 상주"
    frozen, units = _frozen([met_text], [_fact("staff:onsite", "confirmed", ONSITE)])
    _v1, v2 = _both(frozen, _text_item(units[0], met_text, type_="계약"))
    assert v2.fit_status == "unknown" and v2.constraint_results[0].reason_code == "confirmed_match"


# --- 제외 분야 -----------------------------------------------------------------------------


def test_requirement_squarely_in_a_confirmed_excluded_field_is_a_gap_only_under_v2() -> None:
    for text in ("전산장비 유지관리", "예비장비(예비부품) 확보"):
        frozen, units = _frozen([text], [_fact("excl:hardware", "confirmed", HW_TERMS)])
        v1, v2 = _both(frozen, _text_item(units[0], text, type_="기능"))
        assert _outcome(v1) == ("unknown", "unmapped", [])
        assert _outcome(v2) == ("gap", "confirmed_contradiction", ["excl:hardware"])
        assert v2.evidence_ids == [UUID(frozen["profile_evidence"][0]["profile_evidence_id"])]


@pytest.mark.parametrize("block, quote", [
    ("하드웨어 및 상용 소프트웨어 유지관리", "하드웨어 및 상용 소프트웨어 유지관리"),
    ("시스템(하드웨어, 상용 소프트웨어) 유지관리와 운영을 지원한다.", "시스템(하드웨어, 상용 소프트웨어) 유지관리와 운영을 지원한다."),
    # the model quotes only the excluded part: the cited clause still holds a part outside the field
    ("하드웨어 유지관리 및 웹 콘텐츠 운영", "하드웨어 유지관리"),
])
def test_partly_excluded_requirement_is_exclusion_partial(block, quote) -> None:
    frozen, units = _frozen([block], [_fact("excl:hardware", "confirmed", HW_TERMS)])
    v1, v2 = _both(frozen, _text_item(units[0], quote, type_="기능"))
    assert _outcome(v1) == ("unknown", "unmapped", [])
    assert _outcome(v2) == ("unknown", "exclusion_partial", ["excl:hardware"])
    assert v2.evidence_ids == []


@pytest.mark.parametrize("fact", [
    _fact("excl:hardware", "confirmed", HW_V4),                                   # source v4: no terms
    _fact("excl:hardware", "proposed", HW_TERMS),                                 # not confirmed
    _fact("excl:design_only", "confirmed", {"tier": None, "keywords": ["디자인"], "excluded": True,
                                            "kind": "design_only", "requirement_terms": ["전산장비"]}),
    _fact("excl:hardware", "confirmed", {**HW_TERMS, "excluded": False}),
    _fact("excl:election", "confirmed", {**HW_TERMS, "kind": "hardware"}),         # key and kind differ
])
def test_exclusion_without_confirmed_requirement_terms_links_nothing(fact) -> None:
    text = "전산장비 유지관리"
    frozen, units = _frozen([text], [fact])
    v1, v2 = _both(frozen, _text_item(units[0], text, type_="기능"))
    assert _outcome(v1) == _outcome(v2) == ("unknown", "unmapped", [])


def test_touched_excluded_field_never_lets_an_atom_be_met() -> None:
    text = "웹 운영, 하드웨어 유지관리 상주 인원 3명 이상"
    frozen, units = _frozen([text], [_fact("staff:onsite", "confirmed", ONSITE),
                                     _fact("excl:hardware", "confirmed", HW_TERMS)])
    item = extract_item(units[0], constraints=[
        constraint(units[0], kind="count", value=3, unit_name="person", operator="gte", quote=text)])
    v1, v2 = _both(frozen, item)
    assert _outcome(v1)[:2] == ("met", "confirmed_match")
    assert _outcome(v2) == ("unknown", "exclusion_partial", ["excl:hardware"])


def test_unquoted_excluded_term_in_the_source_keeps_the_unit_incomplete() -> None:
    text = "전산장비 상주 인원 3명 이상"
    frozen, units = _frozen([text], [_fact("staff:onsite", "confirmed", ONSITE),
                                     _fact("excl:hardware", "confirmed", HW_TERMS)])
    item = extract_item(units[0], constraints=[
        constraint(units[0], kind="count", value=3, unit_name="person", operator="gte", quote="상주 인원 3명 이상")])
    v1, v2 = _both(frozen, item)
    assert v1.fit_status == "met"
    assert v2.fit_status == "unknown" and "incomplete_unit" in v2.reason_codes
    assert v2.constraint_results[0].reason_code == "confirmed_match"


# --- validator ------------------------------------------------------------------------------


def test_validator_binds_the_new_codes_and_the_contract_order_to_the_rule_set() -> None:
    text = "- 상주: 강원특별자치도에서 지정한 장소에 파견"
    frozen, units = _frozen([text], [_fact("staff:onsite", "confirmed", ONSITE),
                                     _fact("pref:onsite_cap", "confirmed", CAP_DAEGU)])
    extract = CardRequirementExtract.model_validate({"schema_version": "bidops.requirement-extract.v1",
                                                     "items": [_text_item(units[0], text, type_="계약")]})
    result = compare_requirements(extract, frozen=frozen, rules=COMPARE_RULES_V2).model_dump(mode="json")
    facts = ["staff:onsite", "pref:onsite_cap"]
    evidence = [UUID(row["profile_evidence_id"]) for row in frozen["profile_evidence"]]
    validate_requirement_compare(result, extract=extract, graph_paths=[], known_fact_ids=facts,
                                 known_evidence_ids=evidence, rules=COMPARE_RULES_V2)
    with pytest.raises(CardAnalysisValidationError, match="card_compare_invalid"):  # 계약 gap is v2 only
        validate_requirement_compare(result, extract=extract, graph_paths=[], known_fact_ids=facts,
                                     known_evidence_ids=evidence, rules=COMPARE_RULES_V1)
    unresolved = deepcopy(result)
    row = unresolved["items"][0]
    row.update(fit_status="unknown", evidence_ids=[], reason_codes=["place_unresolved", "contract_unaccepted"])
    row["constraint_results"][0].update(status="unknown", reason_code="place_unresolved")
    validate_requirement_compare(unresolved, extract=extract, graph_paths=[], known_fact_ids=facts,
                                 known_evidence_ids=evidence, rules=COMPARE_RULES_V2)
    with pytest.raises(CardAnalysisValidationError, match="card_compare_invalid"):  # v1 never emits it
        validate_requirement_compare(unresolved, extract=extract, graph_paths=[], known_fact_ids=facts,
                                     known_evidence_ids=evidence, rules=COMPARE_RULES_V1)
    with pytest.raises(CardAnalysisValidationError, match="card_compare_invalid"):
        compare_requirements(extract, frozen=frozen, rules="card-compare-v9")


# --- company source shape (RL-10 결정 E2) ----------------------------------------------------


def test_requirement_terms_shape_is_strict() -> None:
    assert _domain_value(HW_V4) == HW_V4                       # the source v4 shape is unchanged
    assert _domain_value(HW_TERMS) == HW_TERMS
    election = {"tier": None, "keywords": ["선거"], "excluded": True, "kind": "election",
                "requirement_terms": ["선거관리"]}
    assert _domain_value(election) == election
    for broken in (
        {**HW_TERMS, "requirement_terms": []},
        {**HW_TERMS, "requirement_terms": ["H"]},                       # one character
        {**HW_TERMS, "requirement_terms": ["전산 장비", "전산장비"]},       # duplicate after normalization
        {**HW_TERMS, "requirement_terms": "하드웨어"},
        {**HW_TERMS, "excluded": False},
        {"tier": None, "keywords": ["디자인"], "excluded": True, "kind": "design_only", "requirement_terms": ["디자인"]},
        {"tier": None, "keywords": ["인력 파견"], "excluded": True, "kind": "staffing_only",
         "requirement_terms": ["인력 파견"]},
        {"tier": None, "keywords": ["대구"], "excluded": True, "kind": "region", "requirement_terms": ["대구"]},
    ):
        with pytest.raises(CompanyKnowledgeValidationError):
            _domain_value(broken)
