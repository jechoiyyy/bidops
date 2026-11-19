"""공고 분류 단위 테스트(spec T9~T11, `validate_override`).

입력은 `RfpDocument`(rfp.json)뿐이다. fixture 지식 트리(`tests/fixtures/knowledge/`)는 읽기 전용,
카테고리 변형은 메모리에서 만든 `Knowledge`로 한다. 네트워크·LLM을 쓰지 않는다.

fixture 키워드: alpha = [홈페이지, 고도화], exclude [유지관리]; beta = [AI, {웹 접근성, weight 2}];
other = 없음(fallback).
"""

import unicodedata
from pathlib import Path

import pytest

from bid_deep_engine.company.knowledge import (
    BODY_SECTION_CHARS,
    BODY_TOTAL_CHARS,
    Classification,
    Knowledge,
    Page,
    PageMeta,
    classify_notice,
    load_knowledge,
    validate_override,
)
from bid_deep_engine.ingest.models import Requirement, RfpDocument, Section

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "knowledge"


@pytest.fixture(scope="module")
def knowledge() -> Knowledge:
    return load_knowledge(FIXTURE)


def rfp_req3() -> RfpDocument:
    return RfpDocument.model_validate_json((FIXTURES / "rfp_req3.json").read_text(encoding="utf-8"))


def section(idx: int, kind: str, text: str) -> Section:
    return Section(
        id=f"S{idx:03d}",
        heading=f"절 {idx}",
        level=1,
        kind=kind,
        block_start=idx,
        block_end=idx,
        text=text,
    )


def requirement(idx: int, name: str) -> Requirement:
    return Requirement(
        id=f"SFR-{idx:03d}", category="SFR", name=name, details="세부", source="table"
    )


def make_doc(
    title: str,
    *,
    overview: list[str] = (),
    names: list[str] = (),
    other_sections: list[tuple[str, str]] = (),
) -> RfpDocument:
    """rfp_req3을 바탕으로 제목·절·요구사항만 바꾼 문서."""
    sections = [section(i + 1, "overview", text) for i, text in enumerate(overview)]
    sections += [
        section(len(sections) + i + 1, kind, text) for i, (kind, text) in enumerate(other_sections)
    ]
    reqs = [requirement(i + 1, name) for i, name in enumerate(names)]
    return rfp_req3().model_copy(
        update={"title": title, "sections": sections, "requirements": reqs}
    )


def category(slug: str, keywords: list, exclude: list[str] = ()) -> Page:
    meta = PageMeta(
        slug=slug,
        title=f"{slug} 시트",
        kind="category",
        keywords=keywords,
        exclude_keywords=list(exclude),
    )
    return Page(
        meta=meta,
        path=Path(f"categories/{slug}.md"),
        rel=f"categories/{slug}.md",
        body="",
        links=[],
    )


def make_knowledge(*pages: Page) -> Knowledge:
    """메모리 Knowledge. fallback `other`(키워드 없음)를 항상 포함한다."""
    all_pages = [*pages, category("other", [])]
    by_slug = {p.meta.slug: p for p in sorted(all_pages, key=lambda p: p.rel)}
    return Knowledge(root=Path("mem"), pages=by_slug, index_slugs=list(by_slug), hash="0" * 64)


# --- 기준: spec 저장 절의 rfp_req3 기대값 ---


def test_rfp_req3_is_alpha_keyword(knowledge):
    result = classify_notice(rfp_req3(), knowledge)
    assert result == Classification(
        categories=["alpha"], source="keyword", scores={"alpha": 6, "beta": 2}
    )


def test_scores_only_for_categories_with_keywords_in_slug_order(knowledge):
    result = classify_notice(rfp_req3(), knowledge)
    assert list(result.scores) == ["alpha", "beta"]  # other는 keyword가 없어 제외


# --- T9: 가중치·정규화 ---


def test_t9_one_title_keyword_scores_three_and_is_selected(knowledge):
    result = classify_notice(make_doc("합성 홈페이지 용역"), knowledge)
    assert result.categories == ["alpha"]
    assert result.source == "keyword"
    assert result.scores == {"alpha": 3, "beta": 0}


def test_t9_body_only_hit_scores_one_and_is_below_minimum(knowledge):
    result = classify_notice(make_doc("합성 용역", names=["홈페이지 개편"]), knowledge)
    assert result.scores == {"alpha": 1, "beta": 0}
    assert result.categories == ["other"]
    assert result.source == "fallback"


def test_t9_title_and_body_hits_add_up(knowledge):
    doc = make_doc("합성 홈페이지 용역", overview=["홈페이지 고도화 사업"])
    # 홈페이지: 제목 3 + 본문 1, 고도화: 본문 1
    assert classify_notice(doc, knowledge).scores["alpha"] == 5


def test_t9_count_is_presence_not_occurrences(knowledge):
    doc = make_doc("홈페이지 홈페이지 홈페이지", names=["홈페이지", "홈페이지 홈페이지"])
    assert classify_notice(doc, knowledge).scores["alpha"] == 4


def test_t9_whitespace_difference_matches(knowledge):
    # keyword "웹 접근성"(weight 2) ↔ 제목 "웹접근성", 본문 "웹  접근\t성"
    doc = make_doc("웹접근성 개선 용역", names=["웹  접근\t성 인증"])
    result = classify_notice(doc, knowledge)
    assert result.scores["beta"] == 2 * (3 + 1)
    assert result.categories == ["beta"]


def test_t9_keyword_weight_two_in_title_scores_six(knowledge):
    result = classify_notice(make_doc("웹 접근성 개선 용역"), knowledge)
    assert result.scores == {"alpha": 0, "beta": 6}
    assert result.categories == ["beta"]


@pytest.mark.parametrize("title", ["ai 기반 상담 용역", "Ai 상담", "생성형AI 도입"])
def test_t9_case_insensitive(knowledge, title):
    result = classify_notice(make_doc(title), knowledge)
    assert result.scores["beta"] == 3
    assert result.categories == ["beta"]


def test_t9_casefold_applies_to_keyword_side():
    knowledge = make_knowledge(category("gamma", ["CMS"]))
    assert classify_notice(make_doc("cms 구축"), knowledge).scores == {"gamma": 3}


def test_t9_nfd_title_matches_nfc_keyword(knowledge):
    title = unicodedata.normalize("NFD", "합성 홈페이지 용역")
    assert title != unicodedata.normalize("NFC", title)
    assert classify_notice(make_doc(title), knowledge).scores["alpha"] == 3


def test_t9_nfd_keyword_matches_nfc_title():
    nfd = unicodedata.normalize("NFD", "포털")
    knowledge = make_knowledge(category("gamma", [nfd]))
    assert classify_notice(make_doc("통합 포털 구축"), knowledge).scores == {"gamma": 3}


def test_t9_keyword_matches_across_removed_whitespace(knowledge):
    # 모든 공백을 지운 뒤 비교하므로 "A I 기반" → "ai기반"에 "ai"가 포함된다.
    assert classify_notice(make_doc("A I 기반 상담"), knowledge).scores["beta"] == 3


# --- T10: exclude·정렬·동점·상위 N·fallback·본문 범위 ---


def test_t10_exclude_in_title_zeroes_score(knowledge):
    doc = make_doc("합성 홈페이지 유지관리 용역", names=["홈페이지 고도화"])
    result = classify_notice(doc, knowledge)
    assert result.scores == {"alpha": 0, "beta": 0}
    assert result.categories == ["other"]
    assert result.source == "fallback"


def test_t10_exclude_only_in_body_does_not_zero(knowledge):
    doc = make_doc("합성 홈페이지 고도화 용역", names=["유지관리 계획 수립"])
    assert classify_notice(doc, knowledge).scores["alpha"] == 6


def test_t10_exclude_is_normalized(knowledge):
    doc = make_doc("합성 홈페이지 유지 관리 용역")  # 공백이 달라도 exclude 히트
    assert classify_notice(doc, knowledge).scores["alpha"] == 0


def test_t10_tie_broken_by_slug():
    knowledge = make_knowledge(category("zeta", ["포털"]), category("eta", ["포털"]))
    result = classify_notice(make_doc("통합 포털 구축"), knowledge)
    assert result.categories == ["eta", "zeta"]
    assert result.scores == {"eta": 3, "zeta": 3}
    assert list(result.scores) == ["eta", "zeta"]


def test_t10_higher_score_first_regardless_of_slug():
    knowledge = make_knowledge(
        category("aaa", ["포털"]), category("zzz", [{"term": "포털", "weight": 2}])
    )
    result = classify_notice(make_doc("통합 포털 구축"), knowledge)
    assert result.categories == ["zzz", "aaa"]
    assert result.scores == {"aaa": 3, "zzz": 6}


def test_t10_more_than_two_candidates_keeps_top_two():
    knowledge = make_knowledge(
        category("alpha", ["홈페이지", "고도화"]),
        category("beta", [{"term": "웹 접근성", "weight": 2}]),
        category("gamma", ["용역"]),
        category("delta", ["합성"]),
    )
    doc = make_doc("합성 홈페이지 고도화 웹 접근성 용역")
    result = classify_notice(doc, knowledge)
    assert result.scores == {"alpha": 6, "beta": 6, "delta": 3, "gamma": 3}
    assert result.categories == ["alpha", "beta"]
    assert result.source == "keyword"


def test_t10_minimum_score_boundary():
    knowledge = make_knowledge(category("gamma", ["가", "나", "다"]))
    below = classify_notice(make_doc("사업", names=["가 나"]), knowledge)
    assert below.scores == {"gamma": 2} and below.categories == ["other"]
    at = classify_notice(make_doc("사업", names=["가 나 다"]), knowledge)
    assert at.scores == {"gamma": 3} and at.categories == ["gamma"]


def test_t10_no_candidate_falls_back_to_other(knowledge):
    result = classify_notice(make_doc("무관한 공사 용역"), knowledge)
    assert result == Classification(
        categories=["other"], source="fallback", scores={"alpha": 0, "beta": 0}
    )


def test_t10_document_without_overview_uses_requirement_names(knowledge):
    doc = make_doc(
        "웹 접근성 개선",
        names=["홈페이지 개편", "AI 상담"],
        other_sections=[("requirements", "고도화 고도화"), ("other", "홈페이지")],
    )
    result = classify_notice(doc, knowledge)
    # alpha: 본문 홈페이지 1(요구사항 이름). requirements·other 절의 "고도화"는 보지 않는다.
    # beta: 제목 웹 접근성 2×3 + 본문 AI 1
    assert result.scores == {"alpha": 1, "beta": 7}
    assert result.categories == ["beta"]


def test_t10_document_without_overview_and_requirements(knowledge):
    result = classify_notice(make_doc("합성 홈페이지 용역"), knowledge)
    assert result.scores == {"alpha": 3, "beta": 0}


def test_t10_only_overview_sections_count(knowledge):
    doc = make_doc("합성 용역", overview=["고도화"], other_sections=[("evaluation", "홈페이지")])
    assert classify_notice(doc, knowledge).scores["alpha"] == 1


def test_t10_body_section_char_limit(knowledge):
    filler = "가" * (BODY_SECTION_CHARS - len("홈페"))
    cut = make_doc("합성 용역", overview=[filler + "홈페이지"])  # 4000자 경계에서 잘림
    assert classify_notice(cut, knowledge).scores["alpha"] == 0
    kept = make_doc("합성 용역", overview=[filler[:-2] + "홈페이지"])  # 정확히 4000자
    assert len(filler[:-2] + "홈페이지") == BODY_SECTION_CHARS
    assert classify_notice(kept, knowledge).scores["alpha"] == 1


def test_t10_body_total_char_limit(knowledge):
    per = BODY_SECTION_CHARS
    full = BODY_TOTAL_CHARS // per  # 이 개수의 절이 합계 한도를 정확히 채운다
    assert full * per == BODY_TOTAL_CHARS
    sections = ["가" * per] * full + ["고도화"]
    doc = make_doc("합성 용역", overview=sections)
    assert classify_notice(doc, knowledge).scores["alpha"] == 0
    sections = ["가" * per] * (full - 1) + ["가" * (per - 3) + "고도화"]
    doc = make_doc("합성 용역", overview=sections)
    assert classify_notice(doc, knowledge).scores["alpha"] == 1


def test_t10_title_only_counts_title(knowledge):
    # 제목은 overview·요구사항과 섞이지 않는다: 본문의 "홈페이지"는 1점만.
    doc = make_doc("합성 용역", overview=["홈페이지"])
    assert classify_notice(doc, knowledge).scores["alpha"] == 1


def test_classification_is_deterministic(knowledge):
    doc = rfp_req3()
    first = classify_notice(doc, knowledge)
    second = classify_notice(doc, load_knowledge(FIXTURE))
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_category_without_keywords_is_not_scored():
    knowledge = make_knowledge(category("gamma", []), category("delta", ["포털"]))
    result = classify_notice(make_doc("포털 구축"), knowledge)
    assert result.scores == {"delta": 3}


# --- T11: override ---


def test_t11_override_keeps_order_and_records_scores(knowledge):
    result = classify_notice(rfp_req3(), knowledge, override=["beta", "alpha"])
    assert result == Classification(
        categories=["beta", "alpha"], source="override", scores={"alpha": 6, "beta": 2}
    )


def test_t11_override_removes_duplicates_in_order(knowledge):
    result = classify_notice(rfp_req3(), knowledge, override=["beta", "other", "beta", "other"])
    assert result.categories == ["beta", "other"]
    assert result.source == "override"


def test_t11_override_may_exceed_max_categories_and_use_fallback_slug(knowledge):
    result = classify_notice(rfp_req3(), knowledge, override=["other", "alpha", "beta"])
    assert result.categories == ["other", "alpha", "beta"]


def test_t11_override_unknown_slug_raises_with_known_list(knowledge):
    with pytest.raises(ValueError) as info:
        classify_notice(rfp_req3(), knowledge, override=["alpha", "bogus"])
    assert str(info.value) == "unknown category 'bogus' (known: alpha, beta, other)"


def test_t11_override_non_category_slug_is_unknown(knowledge):
    with pytest.raises(
        ValueError, match=r"^unknown category 'cap-one' \(known: alpha, beta, other\)$"
    ):
        classify_notice(rfp_req3(), knowledge, override=["cap-one"])


def test_t11_override_none_is_keyword_classification(knowledge):
    assert classify_notice(rfp_req3(), knowledge, override=None).source == "keyword"


def test_t11_override_empty_list_raises(knowledge):
    with pytest.raises(ValueError):
        classify_notice(rfp_req3(), knowledge, override=[])


# --- validate_override(doc 없이 CLI·KB-03 공용) ---


def test_validate_override_dedups_in_order(knowledge):
    assert validate_override(knowledge, ["beta", "alpha", "beta"]) == ["beta", "alpha"]


def test_validate_override_unknown_message(knowledge):
    with pytest.raises(ValueError) as info:
        validate_override(knowledge, ["bogus"])
    assert str(info.value) == "unknown category 'bogus' (known: alpha, beta, other)"


def test_validate_override_reports_first_unknown_in_order(knowledge):
    with pytest.raises(ValueError, match="'zzz'"):
        validate_override(knowledge, ["alpha", "zzz", "aaa"])


def test_validate_override_known_list_is_sorted():
    knowledge = make_knowledge(category("zeta", ["포털"]), category("eta", ["포털"]))
    with pytest.raises(ValueError) as info:
        validate_override(knowledge, ["x"])
    assert str(info.value) == "unknown category 'x' (known: eta, other, zeta)"


def test_validate_override_does_not_mutate_input(knowledge):
    given = ["beta", "beta"]
    validate_override(knowledge, given)
    assert given == ["beta", "beta"]
