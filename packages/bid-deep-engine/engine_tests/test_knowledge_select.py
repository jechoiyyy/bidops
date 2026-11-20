"""발췌 선택·렌더링·조합 단위 테스트(spec T12~T14, `parse_category_option`).

fixture(`tests/fixtures/knowledge/`)는 읽기 전용으로만 쓰고, 변형은 tmp_path 복사본에서 한다.
렌더링 기대 문자열은 spec "렌더링" 절을 테스트 쪽에서 따로 조립해 비교하고, rfp_req3의 alpha
선택 결과(관련 실적 포함)는 골든 파일 `tests/fixtures/knowledge_render_alpha.md`(끝 개행 없음)와
바이트 단위로 비교한다. 실적 페이지는 카테고리 예산에 들어가지 않고 공고(`doc`)가 있을 때 관련
실적 선택으로만 끝에 붙는다(설계 docs/design/2026-10-25-past-rfp-capabilities.md 2.3, 세부 검사는
`test_knowledge_portfolio_select.py`). 네트워크·LLM을 쓰지 않는다.
"""

import shutil
from pathlib import Path

import pytest

from bid_deep_engine.company.knowledge import (
    KNOWLEDGE_BUDGET_CHARS,
    Knowledge,
    KnowledgeSelection,
    classify_notice,
    lint_knowledge,
    load_knowledge,
    parse_category_option,
    prepare_knowledge,
    render_knowledge,
    select_pages,
)
from bid_deep_engine.ingest.models import RfpDocument

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "knowledge"
GOLDEN = FIXTURES / "knowledge_render_alpha.md"

RULE_LINE = (
    '- 규칙: 아래는 회사가 작성한 설명 페이지다. "(확인 필요)" 표기와 confidence가 '
    'unknown·estimate인 페이지의 값은 프로필 "unknown"과 같이 다룬다(추정 금지). '
    "근거로 쓴 페이지는 [[slug]]로 가리킨다."
)
# doc 없는 선택: 카테고리 → depth-1(실적 제외) → glossary.
ALPHA_PAGES = ["alpha", "cap-one", "rule-one", "glossary"]
# rfp_req3(doc)로 고르면 관련 실적 P2024-01이 별도 예산으로 끝에 붙는다.
ALPHA_DOC_PAGES = [*ALPHA_PAGES, "P2024-01"]


@pytest.fixture(scope="module")
def knowledge() -> Knowledge:
    return load_knowledge(FIXTURE)


def rfp_req3() -> RfpDocument:
    return RfpDocument.model_validate_json((FIXTURES / "rfp_req3.json").read_text(encoding="utf-8"))


def copy_tree(tmp_path: Path) -> Path:
    dest = tmp_path / "knowledge"
    shutil.copytree(FIXTURE, dest, symlinks=True)
    return dest


def append(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def edit(root: Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {rel}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# --- spec 렌더링 형식을 테스트 쪽에서 독립적으로 조립 ---


def header(categories: list[str], source: str) -> str:
    return f"- 공고 유형: {', '.join(categories)}({source})\n{RULE_LINE}"


def block(knowledge: Knowledge, slug: str) -> str:
    """`### [[slug]] title` + 메타 줄 + 본문(ATX 제목 `#`~`####` 줄만 두 단계 내림)."""
    page = knowledge.pages[slug]
    meta = page.meta
    lines = []
    for line in page.body.split("\n"):
        stripped = line.lstrip("#")
        hashes = len(line) - len(stripped)
        lines.append("##" + line if 1 <= hashes <= 4 and stripped.startswith(" ") else line)
    head = (
        f"### [[{meta.slug}]] {meta.title}\n"
        f"- kind: {meta.kind} · confidence: {meta.confidence} · updated: {meta.updated or '-'}"
    )
    body = "\n".join(lines)
    return f"{head}\n{body}" if body else head


def rendered(knowledge: Knowledge, categories: list[str], source: str, pages: list[str]) -> str:
    return "\n\n".join([header(categories, source), *(block(knowledge, s) for s in pages)])


def cost(knowledge: Knowledge, slug: str) -> int:
    return 2 + len(block(knowledge, slug))


# --- T12: 선택 순서·예산 ---


def test_t12_alpha_order_category_links_glossary(knowledge):
    sel = select_pages(knowledge, ["alpha"])
    assert sel == KnowledgeSelection(
        categories=["alpha"],
        category_source="keyword",
        pages=ALPHA_PAGES,
        skipped=[],
        chars=len(rendered(knowledge, ["alpha"], "keyword", ALPHA_PAGES)),
        knowledge_hash=knowledge.hash,
    )


def test_t12_beta_order(knowledge):
    sel = select_pages(knowledge, ["beta"])
    assert sel.pages == ["beta", "cap-two", "glossary"]
    assert sel.skipped == []


def test_t12_two_categories_first_then_links_in_category_order(knowledge):
    sel = select_pages(knowledge, ["beta", "alpha"])
    assert sel.pages == ["beta", "alpha", "cap-two", "cap-one", "rule-one", "glossary"]
    assert sel.categories == ["beta", "alpha"]


def test_t12_shared_link_included_once(tmp_path):
    root = copy_tree(tmp_path)
    append(root, "categories/beta.md", "\n- [[cap-one]]\n")
    knowledge = load_knowledge(root)
    assert knowledge.pages["beta"].links == ["cap-two", "cap-one"]
    sel = select_pages(knowledge, ["alpha", "beta"])
    assert sel.pages == ["alpha", "beta", "cap-one", "rule-one", "cap-two", "glossary"]
    sel = select_pages(knowledge, ["beta", "alpha"])
    assert sel.pages == ["beta", "alpha", "cap-two", "cap-one", "rule-one", "glossary"]


def test_t12_large_page_skipped_and_later_smaller_pages_included(tmp_path):
    root = copy_tree(tmp_path)
    append(root, "capabilities/cap-one.md", "가" * 3000)
    knowledge = load_knowledge(root)
    rest = ["alpha", "rule-one", "glossary"]
    budget = len(header(["alpha"], "keyword")) + sum(cost(knowledge, s) for s in rest)
    assert cost(knowledge, "cap-one") > cost(knowledge, "glossary")
    sel = select_pages(knowledge, ["alpha"], budget_chars=budget)
    assert sel.pages == rest
    assert sel.skipped == ["cap-one"]
    assert sel.chars == budget  # 경계(≤)에서 포함


def test_t12_one_char_over_budget_skips_last_candidate_too(tmp_path):
    root = copy_tree(tmp_path)
    append(root, "capabilities/cap-one.md", "가" * 3000)
    knowledge = load_knowledge(root)
    rest = ["alpha", "rule-one", "glossary"]
    budget = len(header(["alpha"], "keyword")) + sum(cost(knowledge, s) for s in rest) - 1
    sel = select_pages(knowledge, ["alpha"], budget_chars=budget)
    assert sel.pages == ["alpha", "rule-one"]
    assert sel.skipped == ["cap-one", "glossary"]
    assert sel.chars == budget + 1 - cost(knowledge, "glossary")


def test_t12_category_pages_included_even_with_zero_budget(knowledge):
    sel = select_pages(knowledge, ["alpha", "beta"], budget_chars=0)
    assert sel.pages == ["alpha", "beta"]
    assert sel.skipped == ["cap-one", "rule-one", "cap-two", "glossary"]
    assert sel.chars == len(rendered(knowledge, ["alpha", "beta"], "keyword", ["alpha", "beta"]))
    assert sel.chars > 0


def test_t12_depth_two_pages_not_included(tmp_path):
    root = copy_tree(tmp_path)
    append(root, "capabilities/cap-two.md", "\n[[rule-one]]\n")  # beta → cap-two → rule-one
    knowledge = load_knowledge(root)
    sel = select_pages(knowledge, ["beta"])
    assert sel.pages == ["beta", "cap-two", "glossary"]
    assert "rule-one" not in sel.skipped


def test_t12_linked_category_is_not_a_candidate(tmp_path):
    root = copy_tree(tmp_path)
    append(root, "categories/alpha.md", "\n- [[beta]]\n")
    knowledge = load_knowledge(root)
    sel = select_pages(knowledge, ["alpha"])
    assert sel.pages == ALPHA_PAGES
    assert sel.skipped == []


def test_t12_glossary_linked_by_category_keeps_link_position(tmp_path):
    root = copy_tree(tmp_path)
    edit(root, "categories/beta.md", "세부는 [[cap-two]]", "[[glossary]] 세부는 [[cap-two]]")
    knowledge = load_knowledge(root)
    assert select_pages(knowledge, ["beta"]).pages == ["beta", "glossary", "cap-two"]


def test_t12_tree_without_glossary(tmp_path):
    root = copy_tree(tmp_path)
    (root / "glossary.md").unlink()
    edit(root, "INDEX.md", "[[glossary]]", "없음")
    knowledge = load_knowledge(root)
    assert select_pages(knowledge, ["beta"]).pages == ["beta", "cap-two"]


def test_t12_duplicate_categories_removed(knowledge):
    sel = select_pages(knowledge, ["alpha", "alpha"])
    assert sel.categories == ["alpha"]
    assert sel.pages == ALPHA_PAGES
    assert render_knowledge(knowledge, sel).startswith("- 공고 유형: alpha(keyword)\n")


def test_t12_unknown_category_raises(knowledge):
    with pytest.raises(ValueError) as info:
        select_pages(knowledge, ["cap-one"])
    assert str(info.value) == "unknown category 'cap-one' (known: alpha, beta, other)"


@pytest.mark.parametrize("source", ["keyword", "override", "fallback"])
def test_t12_category_source_in_header_and_chars(knowledge, source):
    sel = select_pages(knowledge, ["alpha"], category_source=source)
    assert sel.category_source == source
    assert sel.chars == len(rendered(knowledge, ["alpha"], source, ALPHA_PAGES))
    assert render_knowledge(knowledge, sel).startswith(f"- 공고 유형: alpha({source})\n")


def test_t12_category_source_affects_budget(knowledge):
    # "override"는 "keyword"보다 1자 길다 → 같은 예산에서 마지막 후보가 빠진다.
    budget = select_pages(knowledge, ["alpha"]).chars
    assert select_pages(knowledge, ["alpha"], budget_chars=budget).skipped == []
    sel = select_pages(knowledge, ["alpha"], budget_chars=budget, category_source="override")
    assert sel.skipped == ["glossary"]


@pytest.mark.parametrize(
    "categories", [["alpha"], ["beta"], ["other"], ["alpha", "beta"], ["other", "beta"]]
)
@pytest.mark.parametrize("budget", [0, 300, 900, KNOWLEDGE_BUDGET_CHARS])
def test_t12_chars_equals_rendered_length(knowledge, categories, budget):
    sel = select_pages(knowledge, categories, budget_chars=budget)
    text = render_knowledge(knowledge, sel)
    assert sel.chars == len(text)
    assert text == rendered(knowledge, categories, "keyword", sel.pages)
    assert sorted(sel.pages + sel.skipped) == sorted(set(sel.pages + sel.skipped))


def test_t12_matches_lint_w4_skip(tmp_path):
    # W4와 select_pages는 같은 계산: 단일 카테고리 선택의 skipped가 경고 목록과 같다.
    root = copy_tree(tmp_path)
    append(root, "capabilities/cap-one.md", "가" * KNOWLEDGE_BUDGET_CHARS)
    knowledge = load_knowledge(root)
    sel = select_pages(knowledge, ["alpha"])
    assert sel.skipped == ["cap-one"]
    assert "categories/alpha.md: selection would skip: cap-one" in lint_knowledge(root).warnings


def test_selection_field_order():
    assert list(KnowledgeSelection.model_fields) == [
        "categories",
        "category_source",
        "pages",
        "skipped",
        "chars",
        "knowledge_hash",
    ]


# --- T13: 렌더링 골든 ---


def golden_text() -> str:
    return GOLDEN.read_bytes().decode("utf-8")


def test_t13_golden_file_shape():
    data = GOLDEN.read_bytes()
    assert not data.endswith(b"\n")
    assert b"\r" not in data
    assert data.startswith("- 공고 유형: alpha(keyword)\n".encode())


def test_t13_golden_matches_spec_format_assembly(knowledge):
    assert golden_text() == rendered(knowledge, ["alpha"], "keyword", ALPHA_DOC_PAGES)


def test_t13_render_alpha_selection_is_byte_identical_to_golden(knowledge):
    text = render_knowledge(knowledge, select_pages(knowledge, ["alpha"], doc=rfp_req3()))
    assert text.encode("utf-8") == GOLDEN.read_bytes()


def test_t13_render_alpha_without_doc_has_no_portfolio(knowledge):
    text = render_knowledge(knowledge, select_pages(knowledge, ["alpha"]))
    assert text == rendered(knowledge, ["alpha"], "keyword", ALPHA_PAGES)
    assert "### [[P2024-01]]" not in text


def test_t13_prepare_rfp_req3_is_byte_identical_to_golden(knowledge):
    selection, text = prepare_knowledge(rfp_req3(), knowledge)
    assert selection.categories == ["alpha"]
    assert selection.category_source == "keyword"
    assert text.encode("utf-8") == GOLDEN.read_bytes()
    assert selection.chars == len(text)


def test_t13_render_properties(knowledge):
    text = render_knowledge(knowledge, select_pages(knowledge, ["alpha"], doc=rfp_req3()))
    lines = text.split("\n")
    assert lines[0] == "- 공고 유형: alpha(keyword)"
    assert lines[1] == RULE_LINE
    assert not text.endswith("\n")
    # frontmatter 누출 없음
    for leaked in ("---", "slug:", "keywords", "exclude_keywords", "sources:", "portfolio_id"):
        assert leaked not in text
    # 제목 두 단계 내림: category 절은 ####, 소절은 #####. 페이지 블록 제목만 ###.
    assert "\n#### 강점\n" in text
    assert "\n## 강점" not in text
    assert "\n##### 세부\n" in text
    block_titles = [line for line in lines if line.startswith("### ")]
    assert block_titles == [
        "### [[alpha]] 알파 유형 비교 시트",
        "### [[cap-one]] 합성 역량 하나",
        "### [[rule-one]] 합성 규칙 하나",
        "### [[glossary]] 합성 용어집",
        "### [[P2024-01]] 2024년 합성 홈페이지 고도화 실적",
    ]
    assert not any(line.startswith(("# ", "## ")) for line in lines)
    # 링크는 원문 그대로, 해시·경로 없음
    assert "[[P2024-01|합성 실적]]" in text and "[[rule-one#주의]]" in text
    assert knowledge.hash not in text
    assert str(FIXTURE) not in text and "categories/alpha.md" not in text


def test_t13_skipped_pages_not_rendered(knowledge):
    sel = select_pages(knowledge, ["alpha"], budget_chars=0)
    text = render_knowledge(knowledge, sel)
    assert text == rendered(knowledge, ["alpha"], "keyword", ["alpha"])
    assert "[[cap-one]] 합성 역량 하나" not in text


def test_t13_heading_demotion_only_atx_one_to_four(tmp_path):
    root = copy_tree(tmp_path)
    append(
        root,
        "capabilities/cap-two.md",
        "\n# 하나\n#### 넷\n##### 다섯\n#해시태그\n ## 들여쓰기\n본문 ## 중간\n",
    )
    knowledge = load_knowledge(root)
    text = render_knowledge(knowledge, select_pages(knowledge, ["beta"]))
    for line in (
        "### 하나",
        "###### 넷",
        "##### 다섯",
        "#해시태그",
        " ## 들여쓰기",
        "본문 ## 중간",
    ):
        assert f"\n{line}\n" in text


def test_t13_empty_body_block_ends_at_meta_line(tmp_path):
    root = copy_tree(tmp_path)
    path = root / "rules/rule-one.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: text.index("## 주의")], encoding="utf-8")
    knowledge = load_knowledge(root)
    assert knowledge.pages["rule-one"].body == ""
    rendered_text = render_knowledge(knowledge, select_pages(knowledge, ["alpha"]))
    assert (
        "### [[rule-one]] 합성 규칙 하나\n- kind: rule · confidence: estimate · updated: -\n\n"
        "### [[glossary]]" in rendered_text
    )


# --- T14: prepare_knowledge·parse_category_option ---


def test_t14_prepare_is_classify_select_render(knowledge):
    doc = rfp_req3()
    selection, text = prepare_knowledge(doc, knowledge, budget_chars=900)
    cls = classify_notice(doc, knowledge)
    expected = select_pages(
        knowledge, cls.categories, budget_chars=900, category_source=cls.source, doc=doc
    )
    assert selection == expected
    assert selection.pages[-1] == "P2024-01"  # 관련 실적은 카테고리 예산(900)과 따로 센다
    assert text == render_knowledge(knowledge, expected)


def test_t14_prepare_is_deterministic(knowledge):
    doc = rfp_req3()
    first = prepare_knowledge(doc, knowledge)
    second = prepare_knowledge(doc, load_knowledge(FIXTURE))
    assert first == second
    assert first[0].model_dump_json() == second[0].model_dump_json()


def test_t14_prepare_with_override(knowledge):
    selection, text = prepare_knowledge(rfp_req3(), knowledge, override=["beta", "alpha", "beta"])
    assert selection.categories == ["beta", "alpha"]
    assert selection.category_source == "override"
    assert selection.pages[:2] == ["beta", "alpha"]
    assert text.startswith("- 공고 유형: beta, alpha(override)\n")
    assert selection.chars == len(text)


def test_t14_prepare_fallback(knowledge):
    doc = rfp_req3().model_copy(update={"title": "무관 공사", "sections": [], "requirements": []})
    selection, text = prepare_knowledge(doc, knowledge)
    assert selection.categories == ["other"]
    assert selection.category_source == "fallback"
    assert selection.pages == ["other", "glossary"]
    assert text.startswith("- 공고 유형: other(fallback)\n")


def test_t14_prepare_unknown_override_raises(knowledge):
    with pytest.raises(
        ValueError, match=r"^unknown category 'bogus' \(known: alpha, beta, other\)$"
    ):
        prepare_knowledge(rfp_req3(), knowledge, override=["bogus"])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("a, b,,a", ["a", "b"]),
        ("alpha", ["alpha"]),
        (" beta ,alpha ", ["beta", "alpha"]),
        ("a,a,a", ["a"]),
    ],
)
def test_t14_parse_category_option(value, expected):
    assert parse_category_option(value) == expected


@pytest.mark.parametrize("value", ["", " , ", ",,", "  "])
def test_t14_parse_category_option_empty_raises(value):
    with pytest.raises(ValueError) as info:
        parse_category_option(value)
    assert str(info.value) == "--category is empty"
