"""LLM 입력 렌더·분할 테스트(spec M2-01 T7~T11, T27).

픽스처 tests/fixtures/rfp_mini.json(S000 전문, S001 level1 p.31-33, S002 level2 page None,
S003 level1 p.40, 요구사항 2, 표 1)과 코드로 만든 합성 RfpDocument만 쓴다.
"""

import re
from pathlib import Path

import pytest

from bid_deep_engine.analysis.document import (
    Chunk,
    build_document,
    render_for_llm,
    render_requirements,
    split_for_mapreduce,
    split_n,
)
from bid_deep_engine.ingest.models import RfpDocument, Section, SourceQuality

FIXTURES = Path(__file__).parent / "fixtures"
MARKER = re.compile(r"^<<S\d{3} \| kind=[a-z_]+ \| p\.[0-9-]+>>$")


@pytest.fixture
def mini() -> RfpDocument:
    return RfpDocument.model_validate_json((FIXTURES / "rfp_mini.json").read_text("utf-8"))


def _strip_markers(text: str) -> str:
    return "\n".join(line for line in text.split("\n") if not MARKER.match(line))


def _make_doc(parts: list[tuple[int, list[str]]], *, requirements: bool = False) -> RfpDocument:
    """(level, 본문 줄) 목록으로 합성 문서. level 0은 맨 앞 전문(S000)만."""
    sections: list[Section] = []
    lines: list[str] = []
    for i, (level, body) in enumerate(parts):
        heading = "전문" if level == 0 else f"제목 {i:02d}"  # 같은 길이
        if level > 0:
            lines.append(f"{'#' * level} {heading}")
        lines.extend(body)
        sections.append(
            Section(
                id=f"S{i:03d}",
                heading=heading,
                level=level,
                kind="other",
                block_start=i,
                block_end=i,
                text="\n".join(body),
            )
        )
    full = "\n".join(lines)
    return RfpDocument(
        slug="synthetic",
        title="합성 문서",
        source_files=["synthetic.hwpx"],
        primary_format="hwpx",
        sections=sections,
        requirements=[],
        tables=[],
        full_text=full,
        source_quality=SourceQuality(
            primary_format="hwpx",
            primary_chars=len(full),
            primary_digits=0,
            has_tables=False,
            requirements_found=0,
            sections_mapped_to_pages=0,
        ),
    )


def _all_ids(doc: RfpDocument) -> list[str]:
    return [s.id for s in doc.sections]


def _dedup_consecutive(ids: list[str]) -> list[str]:
    out: list[str] = []
    for i in ids:
        if not out or out[-1] != i:
            out.append(i)
    return out


def _check_split_n(doc: RfpDocument, chunks: list[Chunk]) -> None:
    assert "\n".join(c.text for c in chunks) == render_for_llm(doc)
    assert [i for c in chunks for i in c.section_ids] == _all_ids(doc)  # 중복 제거 없이
    assert all(len(c.section_ids) >= 1 for c in chunks)
    for c in chunks:  # 구간을 자르지 않으므로 Chunk는 항상 표지 줄로 시작
        assert MARKER.match(c.text.split("\n")[0])


def _check_mapreduce(doc: RfpDocument, chunks: list[Chunk], max_chars: int) -> None:
    rendered = render_for_llm(doc)
    assert "\n".join(c.text for c in chunks) == rendered
    assert _dedup_consecutive([i for c in chunks for i in c.section_ids]) == _all_ids(doc)
    lines = rendered.split("\n")
    assert sum(len(c.text.split("\n")) for c in chunks) == len(lines)  # 줄 중간 자름 없음
    for c in chunks:
        if len(c.text) > max_chars:  # 초과는 max_chars보다 긴 줄 하나짜리 Chunk뿐
            assert "\n" not in c.text
            assert c.text in lines


# --- T7 섹션 표지 ---


def test_t7_markers_head_each_section(mini):
    out = render_for_llm(mini)
    lines = out.split("\n")
    expected = {
        "<<S000 | kind=other | p.->>": "2027년 미니 홈페이지 유지관리 용역 제안요청서",
        "<<S001 | kind=eligibility | p.31-33>>": "# Ⅰ. 입찰참가자격",
        "<<S002 | kind=eligibility | p.->>": "## 1. 공동수급 및 하도급",
        "<<S003 | kind=overview | p.40>>": "# Ⅱ. 사업 개요",
    }
    markers = [line for line in lines if MARKER.match(line)]
    assert markers == list(expected)
    assert lines[0] == "<<S000 | kind=other | p.->>"
    for marker, first_line in expected.items():
        assert lines[lines.index(marker) + 1] == first_line


def test_t7_same_page_label_is_single_page():
    doc = _make_doc([(0, ["앞"]), (1, ["본문"])])
    sec = doc.sections[1].model_copy(update={"page_start": 5, "page_end": 5})
    doc = doc.model_copy(update={"sections": [doc.sections[0], sec]})
    assert "<<S001 | kind=other | p.5>>" in render_for_llm(doc).split("\n")


# --- T8 표지 제거 = full_text ---


def test_t8_strip_markers_equals_full_text(mini):
    out = render_for_llm(mini)
    assert "| 공동수급 | 불허 |" in out  # 표 마크다운 포함
    assert _strip_markers(out) == mini.full_text


def test_t8_missing_heading_line_raises(mini):
    broken = mini.full_text.replace("# Ⅱ. 사업 개요\n", "")
    assert broken != mini.full_text
    doc = mini.model_copy(update={"full_text": broken})
    with pytest.raises(ValueError, match=r"^heading line not found: S003$"):
        render_for_llm(doc)


def test_t8_heading_search_continues_after_previous_match():
    # 두 섹션이 같은 헤딩 줄을 가지면 앞 섹션 다음 위치부터 찾는다.
    doc = _make_doc([(0, ["앞"]), (1, ["가"]), (1, ["나"])])
    secs = [s.model_copy(update={"heading": "같은 제목"}) for s in doc.sections[1:]]
    full = "앞\n# 같은 제목\n가\n# 같은 제목\n나"
    doc = doc.model_copy(update={"sections": [doc.sections[0], *secs], "full_text": full})
    out = render_for_llm(doc)
    assert out.split("\n") == [
        "<<S000 | kind=other | p.->>",
        "앞",
        "<<S001 | kind=other | p.->>",
        "# 같은 제목",
        "가",
        "<<S002 | kind=other | p.->>",
        "# 같은 제목",
        "나",
    ]
    assert _strip_markers(out) == full


def test_t8_lines_before_first_heading_without_preamble_section_kept():
    doc = _make_doc([(0, ["머리말"]), (1, ["본문"])])
    doc = doc.model_copy(update={"sections": doc.sections[1:]})  # S000 없음
    out = render_for_llm(doc)
    assert out.split("\n")[0] == "머리말"
    assert _strip_markers(out) == doc.full_text
    chunks = split_n(doc, 2)
    assert [c.section_ids for c in chunks] == [["S001"]]
    assert "\n".join(c.text for c in chunks) == out


def test_t8_empty_preamble_section_renders_marker_only():
    doc = _make_doc([(0, []), (1, ["본문"])])
    out = render_for_llm(doc)
    assert out.split("\n")[:2] == ["<<S000 | kind=other | p.->>", "<<S001 | kind=other | p.->>"]
    assert _strip_markers(out) == doc.full_text


# --- T9 요구사항 블록 ---


def test_t9_render_requirements_format(mini):
    assert render_requirements(mini) == (
        "<<REQUIREMENTS | count=2>>\n"
        "[SFR-001] 통합검색 기능 개선 | 필수=필수 | 섹션=S001\n"
        "정의: 통합검색 결과의 정확도를 높인다\n"
        "o 검색어 자동완성 제공\n"
        "- 오타 교정 기능 포함\n"
        "\n"
        "[SER-001] 정기 점검 | 필수=- | 섹션=-\n"
        "월 1회 정기 점검 보고서 제출"
    )


def test_t9_render_requirements_optional_and_empty_details(mini):
    r = mini.requirements[1].model_copy(update={"mandatory": False, "details": ""})
    doc = mini.model_copy(update={"requirements": [r]})
    assert render_requirements(doc) == (
        "<<REQUIREMENTS | count=1>>\n[SER-001] 정기 점검 | 필수=선택 | 섹션=-"
    )


def test_t9_render_requirements_empty(mini):
    assert render_requirements(mini.model_copy(update={"requirements": []})) == ""


# --- T27 build_document ---


def test_t27_build_document_with_requirements(mini):
    doc = build_document(mini)
    assert doc == render_for_llm(mini) + "\n\n" + render_requirements(mini)
    assert "<<S001" in doc and "<<REQUIREMENTS" in doc


def test_t27_build_document_without_requirements(mini):
    doc = mini.model_copy(update={"requirements": []})
    out = build_document(doc)
    assert out == render_for_llm(doc)
    assert not out.endswith("\n\n")


# --- T10 split_n ---


def _ten_sections() -> RfpDocument:
    # 표지·헤딩 길이가 같도록 S001~S010 level 1, 본문 길이 동일
    parts = [(1, ["가" * 50]) for _ in range(10)]
    doc = _make_doc([(0, []), *parts])
    # S000을 빼서 구간 10개(S001~S010)
    return doc.model_copy(update={"sections": doc.sections[1:]})


def test_t10_split_n_four_reservation_rule():
    doc = _ten_sections()
    chunks = split_n(doc, 4)
    assert len(chunks) == 4
    _check_split_n(doc, chunks)
    # 균등 구간: 누적 ≥ T×i/4에서 닫음 → 3, 2, 3, 2
    assert [len(c.section_ids) for c in chunks] == [3, 2, 3, 2]


def test_t10_split_n_one_and_more_than_sections():
    doc = _ten_sections()
    one = split_n(doc, 1)
    assert len(one) == 1
    assert one[0].text == render_for_llm(doc)
    _check_split_n(doc, one)
    many = split_n(doc, 20)
    assert len(many) == 10
    assert [c.section_ids for c in many] == [[s.id] for s in doc.sections]
    _check_split_n(doc, many)


@pytest.mark.parametrize("n", [0, -1])
def test_t10_split_n_invalid(n):
    with pytest.raises(ValueError):
        split_n(_ten_sections(), n)


def test_t10_split_n_skewed_first_section():
    body = ["가" * 10_000]  # 첫 구간이 전체의 95% 이상
    doc = _make_doc([(0, body), *[(1, ["나" * 40]) for _ in range(5)]])
    sizes = [len(seg) for seg in render_for_llm(doc).split("\n<<")]
    assert sizes[0] / sum(sizes) > 0.95
    chunks = split_n(doc, 4)
    assert len(chunks) == 4
    assert chunks[0].section_ids == ["S000"]
    _check_split_n(doc, chunks)


def test_t10_split_n_reserves_sections_for_remaining_chunks():
    # 마지막 구간이 거의 전부 → (a)는 늦게 성립, (b) 남은 구간 == 남은 Chunk에서 닫음
    doc = _make_doc([(0, ["가"]), *[(1, ["나"]) for _ in range(4)], (1, ["다" * 5000])])
    chunks = split_n(doc, 4)
    assert [c.section_ids for c in chunks] == [
        ["S000", "S001", "S002"],
        ["S003"],
        ["S004"],
        ["S005"],
    ]
    _check_split_n(doc, chunks)


def test_t10_split_n_fixture(mini):
    chunks = split_n(mini, 4)
    assert [c.section_ids for c in chunks] == [["S000"], ["S001"], ["S002"], ["S003"]]
    _check_split_n(mini, chunks)
    two = split_n(mini, 2)
    assert len(two) == 2
    _check_split_n(mini, two)


# --- T11 split_for_mapreduce ---


def test_t11a_closes_at_bundle_boundary_before_exceeding():
    doc = _make_doc(
        [
            (0, ["앞" * 50]),
            (1, ["가" * 200]),
            (2, ["가" * 200]),
            (1, ["나" * 200]),
            (2, ["나" * 200]),
            (1, ["다" * 200]),
            (2, ["다" * 200]),
        ]
    )
    max_chars = 600
    chunks = split_for_mapreduce(doc, max_chars)
    assert [c.section_ids for c in chunks] == [
        ["S000", "S001", "S002"],
        ["S003", "S004"],
        ["S005", "S006"],
    ]
    assert all(len(c.text) <= max_chars for c in chunks)
    # 다음 묶음을 더하면 넘으므로 닫았다
    assert len(chunks[0].text) + 1 + len(chunks[1].text) > max_chars
    _check_mapreduce(doc, chunks, max_chars)


def test_t11b_oversized_bundle_cut_at_section_boundaries():
    doc = _make_doc(
        [
            (0, ["앞" * 50]),
            (1, ["가" * 200]),
            (2, ["나" * 200]),
            (2, ["다" * 200]),
            (1, ["라" * 100]),
        ]
    )
    max_chars = 500
    chunks = split_for_mapreduce(doc, max_chars)
    # S000은 다음 묶음(단독 초과)을 더하면 넘으므로 먼저 닫고, 묶음은 섹션 구간 경계로 자른다.
    # 묶음의 마지막 구간 뒤에는 다음 묶음이 이어서 들어갈 수 있다.
    assert [c.section_ids for c in chunks] == [["S000"], ["S001", "S002"], ["S003", "S004"]]
    assert all(len(c.text) <= max_chars for c in chunks)
    for c in chunks:
        assert MARKER.match(c.text.split("\n")[0])
    _check_mapreduce(doc, chunks, max_chars)


def test_t11c_preamble_only_cut_at_lines_with_long_line():
    body = [f"줄{i:02d}" + "가" * 25 for i in range(6)]
    body.insert(3, "긴" * 150)
    doc = _make_doc([(0, body)])
    max_chars = 100
    chunks = split_for_mapreduce(doc, max_chars)
    over = [c for c in chunks if len(c.text) > max_chars]
    assert [c.text for c in over] == ["긴" * 150]
    assert len(chunks) >= 3
    assert all(c.section_ids == ["S000"] for c in chunks)  # 중간 시작은 진행 중 섹션
    _check_mapreduce(doc, chunks, max_chars)


def test_t11d_oversized_section_cut_at_lines():
    body = [f"{i:02d}" + "가" * 40 for i in range(10)]  # 구간 하나가 단독으로 초과
    doc = _make_doc([(0, ["앞"]), (1, body), (2, ["나" * 10]), (1, ["다" * 10])])
    max_chars = 150
    chunks = split_for_mapreduce(doc, max_chars)
    assert all(len(c.text) <= max_chars for c in chunks)
    ids = [c.section_ids for c in chunks]
    assert ids[0] == ["S000"]  # S000은 단독 초과 묶음 앞에서 먼저 닫힘
    assert ids[1][0] == "S001"
    mid = [c for c in chunks[1:] if not MARKER.match(c.text.split("\n")[0])]
    assert mid, "구간 중간에서 시작한 Chunk가 있어야 한다"
    for c in mid:
        assert c.section_ids[0] == "S001"
    _check_mapreduce(doc, chunks, max_chars)


def test_t11_single_level1_uses_sections_then_lines():
    # level 1이 1개뿐이면 1단계 = 섹션 구간
    doc = _make_doc([(0, ["앞" * 50]), (1, ["가" * 100]), (2, ["나" * 100]), (2, ["다" * 100])])
    max_chars = 280
    chunks = split_for_mapreduce(doc, max_chars)
    assert [c.section_ids for c in chunks] == [["S000", "S001"], ["S002", "S003"]]
    _check_mapreduce(doc, chunks, max_chars)


def test_t11_fixture_whole_doc_fits(mini):
    chunks = split_for_mapreduce(mini, 10**6)
    assert len(chunks) == 1
    assert chunks[0].section_ids == ["S000", "S001", "S002", "S003"]
    _check_mapreduce(mini, chunks, 10**6)
    for max_chars in (1, 20, 60, 120, 250):
        _check_mapreduce(mini, split_for_mapreduce(mini, max_chars), max_chars)


@pytest.mark.parametrize("max_chars", [0, -5])
def test_t11_invalid_max_chars(mini, max_chars):
    with pytest.raises(ValueError):
        split_for_mapreduce(mini, max_chars)
