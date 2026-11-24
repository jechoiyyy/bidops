"""관련 실적 선택(설계 docs/design/2026-10-25-past-rfp-capabilities.md 2.3) 단위 테스트.

- 점수: 공고(제목·overview 본문·요구사항 이름·정의) 토큰과 실적 페이지 '수행한 요구 범위'·
  '기술 환경' 토큰의 교집합 크기. 두 절이 없는 페이지는 본문 전체.
- 상위 `PORTFOLIO_TOP_K`개, 별도 예산 `PORTFOLIO_BUDGET_CHARS`, 카테고리 예산과 따로 센다.
- 카테고리가 링크한 실적은 카테고리 예산에서 빠지고 관련 실적으로만 한 번 들어간다.

fixture 트리(`tests/fixtures/knowledge/`)는 tmp_path 복사본에서만 바꾼다. 네트워크·LLM 없음.
"""

import shutil
from pathlib import Path

import pytest

from bid_deep_engine.company.knowledge import (
    PORTFOLIO_BUDGET_CHARS,
    PORTFOLIO_TOP_K,
    _match_tokens,
    _render_block,
    load_knowledge,
    prepare_knowledge,
    relevant_portfolio,
    render_knowledge,
    select_pages,
)
from bid_deep_engine.ingest.models import RfpDocument

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "knowledge"


def rfp(title: str = "합성 공고", reqs: list[tuple[str, str | None]] | None = None) -> RfpDocument:
    base = RfpDocument.model_validate_json((FIXTURES / "rfp_req3.json").read_text("utf-8"))
    requirements = []
    for idx, (name, definition) in enumerate(reqs or [], start=1):
        requirements.append(
            base.requirements[0].model_copy(
                update={"id": f"SFR-{idx:03d}", "name": name, "definition": definition}
            )
        )
    return base.model_copy(update={"title": title, "sections": [], "requirements": requirements})


def portfolio_page(slug: str, scope: list[str], tech: list[str], extra: str = "") -> str:
    lines = [
        "---",
        f"slug: {slug}",
        f"title: 합성 실적 {slug}",
        "kind: portfolio",
        "confidence: confirmed",
        "sources: [합성]",
        f"portfolio_id: {slug}",
        "---",
        "## 개요",
        "",
        "- 합성 개요",
        "",
        "## 수행한 요구 범위",
        "",
        *(f"- {item}" for item in scope),
        "",
        "## 기술 환경",
        "",
        *(f"- {item}" for item in tech),
    ]
    if extra:
        lines += ["", "## 이 실적이 뒷받침하는 역량", "", f"- {extra}"]
    return "\n".join(lines) + "\n"


def tree(tmp_path: Path, pages: dict[str, str], *, link_from_alpha: list[str] = ()) -> Path:
    root = tmp_path / "knowledge"
    shutil.copytree(FIXTURE, root, symlinks=True)
    for slug, text in pages.items():
        (root / "portfolio" / f"{slug}.md").write_text(text, encoding="utf-8")
    index = root / "INDEX.md"
    links = " ".join(f"[[{slug}]]" for slug in pages)
    index.write_text(index.read_text("utf-8") + f"\n- 실적: {links}\n", encoding="utf-8")
    if link_from_alpha:
        alpha = root / "categories" / "alpha.md"
        text = alpha.read_text("utf-8")
        added = "".join(f"\n- [[{slug}]]" for slug in link_from_alpha)
        alpha.write_text(
            text.replace("- [[P2024-01|합성 실적]]", "- [[P2024-01|합성 실적]]" + added)
        )
    return root


# --- 토큰 정규화 ---


def test_match_tokens_normalize_drop_particles_numbers_stopwords_and_req_prefixes():
    tokens = _match_tokens(
        "SFR-001 홈페이지를 통합검색으로 2024년 구축 및 운영, CMS의 Java 10개월 웹"
    )
    assert tokens == {"홈페이지", "통합검색", "cms", "java"}
    # 조사를 떼면 2글자 미만이 되는 말은 그대로 둔다(평가 → 평가)
    assert _match_tokens("평가 참가") == {"평가", "참가"}
    assert _match_tokens("ＣＭＳ") == _match_tokens("cms") == {"cms"}  # NFKC·casefold
    assert _match_tokens("") == set()


# --- 점수·순위 ---


def test_score_is_token_intersection_of_scope_and_tech_sections(tmp_path):
    page = portfolio_page(
        "P2030-01",
        ["SFR-001 통합검색 고도화", "관리자 통계 대시보드"],
        ["PostgreSQL", "전자정부표준프레임워크"],
        extra="결제 연동 역량",  # 다른 절은 점수에 쓰지 않는다
    )
    knowledge = load_knowledge(tree(tmp_path, {"P2030-01": page}))
    doc = rfp(reqs=[("통합검색 개선", "PostgreSQL 기반"), ("결제 연동", None)])
    scores = dict(relevant_portfolio(knowledge, doc))
    # 공고 {합성, 공고, 통합검색, 개선, postgresql, 결제, 연동} ∩ 페이지 {통합검색, 고도화, 관리자,
    # 통계, 대시보드, postgresql, 전자정부표준프레임워크} = {통합검색, postgresql}
    assert scores["P2030-01"] == 2


def test_pages_without_scope_sections_are_scored_on_whole_body(knowledge_fixture):
    # fixture P2024-01은 '수행한 요구 범위'·'기술 환경' 절이 없는 시드형 페이지다.
    doc = rfp(title="합성 홈페이지 고도화")
    assert relevant_portfolio(knowledge_fixture, doc) == [("P2024-01", 3)]


@pytest.fixture(scope="module")
def knowledge_fixture():
    return load_knowledge(FIXTURE)


def test_zero_score_pages_are_not_selected(knowledge_fixture):
    doc = rfp(title="무관 공사")
    assert relevant_portfolio(knowledge_fixture, doc) == []
    sel = select_pages(knowledge_fixture, ["alpha"], doc=doc)
    assert "P2024-01" not in sel.pages + sel.skipped


def test_top_k_by_score_then_slug(tmp_path):
    words = ["가나", "다라", "마바", "사아", "자차", "카타", "파하"]
    pages = {
        # P2030-0n은 앞 n개 단어를 가진다 → 점수 n. P2030-08은 P2030-03과 같은 점수(slug로 뒤)
        **{f"P2030-0{n}": portfolio_page(f"P2030-0{n}", words[:n], []) for n in range(1, 8)},
        "P2030-08": portfolio_page("P2030-08", words[:3], []),
    }
    knowledge = load_knowledge(tree(tmp_path, pages))
    doc = rfp(title=" ".join(words))
    ranked = relevant_portfolio(knowledge, doc)
    assert ranked == [("P2030-07", 7), ("P2030-06", 6), ("P2030-05", 5), ("P2030-04", 4),
                      ("P2030-03", 3)]  # fmt: skip
    assert len(ranked) == PORTFOLIO_TOP_K == 5
    assert relevant_portfolio(knowledge, doc, top_k=7)[-3:] == [
        ("P2030-03", 3), ("P2030-08", 3), ("P2030-02", 2)
    ]  # fmt: skip
    assert relevant_portfolio(knowledge, doc, top_k=0) == []
    sel = select_pages(knowledge, ["beta"], doc=doc)
    assert sel.pages[-5:] == [slug for slug, _ in ranked]


# --- 예산·중복 ---


def test_portfolio_budget_is_separate_and_greedy(tmp_path):
    pages = {
        "P2030-01": portfolio_page("P2030-01", ["통합검색 개선"], ["가" * 50]),
        "P2030-02": portfolio_page("P2030-02", ["통합검색"], ["나" * 3000]),
        "P2030-03": portfolio_page("P2030-03", ["통합검색"], []),
    }
    knowledge = load_knowledge(tree(tmp_path, pages))
    doc = rfp(title="통합검색 개선")
    ranked = [slug for slug, _ in relevant_portfolio(knowledge, doc)]
    assert ranked == ["P2030-01", "P2030-02", "P2030-03"]
    costs = {s: 2 + len(_render_block(knowledge.pages[s])) for s in ranked}
    budget = costs["P2030-01"] + costs["P2030-03"]  # 가운데(큰) 페이지만 넘친다
    sel = select_pages(knowledge, ["beta"], doc=doc, portfolio_budget_chars=budget)
    assert sel.pages == ["beta", "cap-two", "glossary", "P2030-01", "P2030-03"]
    assert sel.skipped == ["P2030-02"]
    assert sel.chars == len(render_knowledge(knowledge, sel))
    # 카테고리 예산 0이어도 관련 실적은 자기 예산으로 들어간다
    zero = select_pages(knowledge, ["beta"], doc=doc, budget_chars=0)
    assert zero.pages == ["beta", *ranked]
    assert zero.skipped == ["cap-two", "glossary"]
    assert PORTFOLIO_BUDGET_CHARS == 30_000


def test_category_linked_portfolio_is_not_in_category_budget_and_appears_once(tmp_path):
    page = portfolio_page("P2030-01", ["통합검색 개선"], [])
    root = tree(tmp_path, {"P2030-01": page}, link_from_alpha=["P2030-01"])
    knowledge = load_knowledge(root)
    assert "P2030-01" in knowledge.pages["alpha"].links
    # doc 없음: 카테고리가 링크한 실적도 고르지 않는다
    no_doc = select_pages(knowledge, ["alpha"])
    assert no_doc.pages == ["alpha", "cap-one", "rule-one", "glossary"]
    # doc 있음: 관련 실적으로만, 한 번(점수 P2024-01 = 3 > P2030-01 = 2)
    doc = rfp(title="합성 홈페이지 고도화 통합검색 개선")
    assert relevant_portfolio(knowledge, doc) == [("P2024-01", 3), ("P2030-01", 2)]
    sel = select_pages(knowledge, ["alpha"], doc=doc)
    assert sel.pages == ["alpha", "cap-one", "rule-one", "glossary", "P2024-01", "P2030-01"]
    assert sel.pages.count("P2030-01") == 1
    assert sel.chars == no_doc.chars + sum(
        2 + len(_render_block(knowledge.pages[s])) for s in ("P2030-01", "P2024-01")
    )


def test_prepare_records_portfolio_pages_in_selection(tmp_path):
    page = portfolio_page("P2030-01", ["관리자 통계 대시보드 구축"], ["통합검색엔진"])
    knowledge = load_knowledge(tree(tmp_path, {"P2030-01": page}))
    doc = RfpDocument.model_validate_json((FIXTURES / "rfp_req3.json").read_text("utf-8"))
    selection, text = prepare_knowledge(doc, knowledge)
    assert selection.pages[:4] == ["alpha", "cap-one", "rule-one", "glossary"]
    assert set(selection.pages[4:]) == {"P2030-01", "P2024-01"}
    assert "### [[P2030-01]] 합성 실적 P2030-01" in text
    assert selection.chars == len(text)


# --- 원문 요구사항 목록 발췌(2026-11-24) ---

from bid_deep_engine.company.knowledge import (  # noqa: E402
    PORTFOLIO_EXCERPT_CHARS,
    PORTFOLIO_EXCERPT_HEADING,
    PORTFOLIO_LIST_HEADING,
)


def _with_full_list(text: str, lines: list[str]) -> str:
    return text.replace(
        "## 기술 환경",
        f"{PORTFOLIO_LIST_HEADING}\n\n원문 목록 안내\n\n" + "\n".join(lines) + "\n\n## 기술 환경",
    )


def test_excerpt_keeps_only_matching_list_lines_within_cap_and_rest_of_page(tmp_path):
    filler = [f"- MAR-{i:03d} 장비 반입 절차 {'나' * 280}" for i in range(1, 80)]
    hits = ["- SFR-101 통합검색 색인 개선", "- SFR-102 통합검색 형태소 사전 관리"]
    text = _with_full_list(portfolio_page("P2030-01", ["통합검색 개선"], ["Java"], extra="검색 역량"), filler[:40] + hits + filler[40:])
    knowledge = load_knowledge(tree(tmp_path, {"P2030-01": text}))
    doc = rfp("통합검색 사업", [("통합검색 색인", "형태소 사전")])
    sel = select_pages(knowledge, ["beta"], doc=doc)
    assert "P2030-01" in sel.pages
    assert sel.portfolio_excerpts["P2030-01"] == [40, 41]
    rendered = render_knowledge(knowledge, sel)
    assert PORTFOLIO_EXCERPT_HEADING in rendered and PORTFOLIO_LIST_HEADING not in rendered
    assert "SFR-101" in rendered and "SFR-102" in rendered and "MAR-001" not in rendered
    assert "원문 목록 81줄 가운데" in rendered and "옮기지 않은 줄도 수행한 범위다." in rendered
    assert "검색 역량" in rendered and "Java" in rendered
    assert sel.chars == len(rendered)


def test_excerpt_respects_character_cap(tmp_path):
    lines = [f"- SFR-{i:03d} 통합검색 기능 {'다' * 290}" for i in range(1, 30)]
    text = _with_full_list(portfolio_page("P2030-01", ["통합검색 개선"], []), lines)
    knowledge = load_knowledge(tree(tmp_path, {"P2030-01": text}))
    sel = select_pages(knowledge, ["beta"], doc=rfp("통합검색 사업", [("통합검색 기능", None)]))
    picked = sel.portfolio_excerpts["P2030-01"]
    assert 0 < len(picked) < len(lines)
    assert sum(len(lines[i]) + 1 for i in picked) <= PORTFOLIO_EXCERPT_CHARS


def test_page_without_full_list_and_lint_path_render_unchanged(tmp_path):
    plain = portfolio_page("P2030-02", ["통합검색 개선"], [])
    knowledge = load_knowledge(tree(tmp_path, {"P2030-02": plain}))
    sel = select_pages(knowledge, ["beta"], doc=rfp("통합검색 사업", [("통합검색 개선", None)]))
    assert "P2030-02" not in sel.portfolio_excerpts
    assert _render_block(knowledge.pages["P2030-02"]) == _render_block(knowledge.pages["P2030-02"], None)
