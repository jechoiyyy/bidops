import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bid_deep_engine.ingest.models import (
    Block,
    RawDoc,
    RawMeta,
    RawTable,
    Requirement,
    RfpDocument,
    Section,
    SourceQuality,
    Table,
)
from bid_deep_engine.ingest.normalize import (
    _check_ranges,
    build,
    build_sections,
    classify_heading,
    classify_table,
    detect_heading,
    expected_requirement_count,
    is_toc_line,
    map_pages,
    merge_warnings,
    page_prefix,
    parse_requirements_from_tables,
    parse_requirements_from_text,
    render_rfp_md,
    render_table_markdown,
    select_requirements,
    strip_heading_mark,
)
from engine_tests.ingest_writer import dump_json
from engine_tests.test_models import make_bundle


def make_section(**kw) -> Section:
    base = dict(
        id="S001",
        heading="Ⅰ. 사업 개요",
        level=1,
        kind="overview",
        block_start=0,
        block_end=3,
        text="본문",
        table_ids=["T001"],
    )
    return Section(**{**base, **kw})


def make_requirement(**kw) -> Requirement:
    base = dict(
        id="SFR-001",
        category="SFR",
        name="사용자 관리",
        definition=None,
        details="세부 내용",
        mandatory=True,
        section_id="S001",
        table_id="T001",
        source="table",
    )
    return Requirement(**{**base, **kw})


def make_doc() -> RfpDocument:
    rows = [["ID", "명칭"], ["SFR-001", "사용자 관리"]]
    return RfpDocument(
        slug="demo",
        title="데모 사업",
        source_files=["a/제안요청서.hwpx", "a/제안요청서.pdf"],
        primary_format="hwpx",
        sections=[make_section()],
        requirements=[make_requirement()],
        tables=[
            Table(
                id="T001",
                section_id="S001",
                kind="requirement_list",
                rows=rows,
                markdown=render_table_markdown(rows),
            )
        ],
        full_text="## x",
        source_quality=SourceQuality(
            primary_format="hwpx",
            primary_chars=10,
            primary_digits=2,
            has_tables=True,
            requirements_found=1,
            sections_mapped_to_pages=0,
        ),
    )


def test_rfp_document_round_trip():
    doc = make_doc()
    assert doc.schema_version == 1
    restored = RfpDocument.model_validate_json(doc.model_dump_json())
    assert restored == doc
    assert json.loads(dump_json(doc))["slug"] == "demo"


def test_rfp_document_field_order():
    assert list(RfpDocument.model_fields) == [
        "slug",
        "title",
        "source_files",
        "primary_format",
        "sections",
        "requirements",
        "tables",
        "full_text",
        "source_quality",
        "schema_version",
    ]
    assert list(Requirement.model_fields) == [
        "id",
        "category",
        "name",
        "definition",
        "details",
        "mandatory",
        "section_id",
        "table_id",
        "source",
        "instance_key",
    ]


@pytest.mark.parametrize(
    "bad_id", ["sfr-001", "SFR-1", "SFR-0001", "SF-001", "SFR001", " SFR-001"]
)
def test_requirement_id_pattern_rejected(bad_id):
    with pytest.raises(ValidationError):
        make_requirement(id=bad_id)


@pytest.mark.parametrize("req_id", ["MAR-001", "COR-02", "SFR-A-04"])
def test_requirement_id_pattern_kept_verbatim(req_id):
    assert make_requirement(id=req_id).id == req_id


@pytest.mark.parametrize("level", [-1, 5, 9])
def test_section_level_out_of_range_rejected(level):
    with pytest.raises(ValidationError):
        make_section(level=level)


@pytest.mark.parametrize("level", [0, 1, 2, 3, 4])
def test_section_level_in_range_accepted(level):
    assert make_section(level=level).level == level


def test_invalid_enum_values_rejected():
    with pytest.raises(ValidationError):
        make_section(kind="unknown")
    with pytest.raises(ValidationError):
        make_requirement(source="pdf")
    with pytest.raises(ValidationError):
        Table(id="T001", section_id="S001", kind="nope", rows=[], markdown="")


def test_markdown_basic():
    md = render_table_markdown([["a", "b"], ["1", "2"], ["3", "4"]])
    assert md == "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"


def test_markdown_header_only():
    assert render_table_markdown([["a", "b", "c"]]) == "| a | b | c |\n|---|---|---|"


def test_markdown_pipe_escaped():
    md = render_table_markdown([["x|y", "b"], ["1", "a|b|c"]])
    assert md == "| x\\|y | b |\n|---|---|\n| 1 | a\\|b\\|c |"


def test_markdown_newlines_become_single_space():
    md = render_table_markdown([["h1", "h2"], ["a\nb", "c\r\nd"]])
    assert md == "| h1 | h2 |\n|---|---|\n| a b | c d |"


def test_markdown_empty_table():
    assert render_table_markdown([]) == ""
    assert render_table_markdown([[]]) == ""


def test_markdown_pads_ragged_rows():
    md = render_table_markdown([["a"], ["1", "2", "3"], ["x", "y"]])
    assert md == "| a |  |  |\n|---|---|---|\n| 1 | 2 | 3 |\n| x | y |  |"


def test_markdown_deterministic():
    rows = [["a|b", "c\nd"], ["1"]]
    assert render_table_markdown(rows) == render_table_markdown([list(r) for r in rows])
    assert render_table_markdown(rows) == render_table_markdown(rows)


# --- STEP-002: 헤딩 인식·섹션 트리·종류 태그 ---


def make_blocks(*items: str | tuple[str, str]) -> list[Block]:
    """문자열은 paragraph, ("table", "T001")은 table Block."""
    blocks = []
    for i, item in enumerate(items):
        if isinstance(item, tuple):
            blocks.append(Block(idx=i, kind="table", text="", table_id=item[1]))
        else:
            blocks.append(Block(idx=i, kind="paragraph", text=item))
    return blocks


def test_t1_heading_levels_and_exclusions():
    lines = [
        "Ⅰ. 사업개요",
        "1. 추진배경",
        "가. 사업 목적",
        "1) 세부 내용",
        "Ⅰ. 사업개요 ·········· 3",
        "2026. 10.",
        "1. 본 사업은 … 수행한다.",
    ]
    levels = [detect_heading(t) for t in lines]
    assert levels == [1, 2, 3, 4, None, None, None]
    assert [t for t, lv in zip(lines, levels, strict=True) if lv is not None] == lines[:4]


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("  Ⅱ 사업추진 방안  ", 1),
        ("Ⅲ．사업 내용", 1),
        ("제 3 장 제안요청 내용", 1),
        ("제2장 일반사항", 1),
        ("[붙임 1] 기술제안서 평가항목", 1),
        ("붙임 2", 1),
        ("【별표 1】 사업자 보안위규 처리기준", 1),
        ("(서식 3) 제안서 표지", 1),
        ("[첨부]", 1),
        ("12. 기타 사항", 2),
        ("3．사업범위", 2),
        ("나 . 보안 요구사항", 3),
        ("10) 유의사항", 4),
        ("2） 제출서류", 4),
    ],
)
def test_detect_heading_patterns(text, level):
    assert detect_heading(text) == level


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "2026. 10.",
        "2026.10.30.",
        "본문 문장입니다",
        "1. 본 사업은 홈페이지를 유지관리한다.",
        "가. 요구사항을 충족함.",
        "1) 결과를 제출하여야 있음.",
        "Ⅰ. 사업개요 …………… 3",
        "1. 추진배경·····4",
        "1. " + "가" * 58,  # 61자
        "100. 항목",  # 세 자리 번호
        "카) 프로젝트 관리",  # 가나다+괄호는 표에 없는 패턴
        "1.",
    ],
)
def test_detect_heading_rejects(text):
    assert detect_heading(text) is None


def test_heading_max_len_boundary():
    assert detect_heading("1. " + "가" * 57) == 2  # 정확히 60자
    assert detect_heading("1. " + "가" * 58) is None


def test_toc_needs_five_repeats():
    assert detect_heading("1. 추진배경 ····") == 2  # 4개는 목차 아님
    assert detect_heading("1. 추진배경 ·····") is None


def test_classify_heading_attachment_flag():
    assert classify_heading("[붙임 1] 기술제안서 평가항목") == (1, True)
    assert classify_heading("붙임 2") == (1, True)
    assert classify_heading("Ⅰ. 사업개요") == (1, False)
    assert classify_heading("4. 제안요청 내용") == (2, False)
    assert classify_heading("2026. 10.") is None


def t2_blocks() -> list[Block]:
    return make_blocks(
        "제 안 요 청 서",  # 0 전문
        "목  차",  # 1 전문
        "Ⅰ. 사업개요",  # 2 S001
        "본 사업의 개요를 설명한다.",  # 3
        "1. 일반 현황",  # 4 S002
        ("table", "T001"),  # 5
        "가. 대상 기관",  # 6 S003
        "기관 설명",  # 7
        "1) 세부 항목",  # 8 S004
        "세부 설명 1",  # 9
        "세부 설명 2",  # 10
        "Ⅱ. 제안요청 내용",  # 11 S005
        ("table", "T002"),  # 12
        "가. 기능 목록",  # 13 S006
        ("table", "T003"),  # 14
        "마지막 문단",  # 15
    )


def test_t2_section_tree():
    blocks = t2_blocks()
    secs = build_sections(blocks)
    assert [s.id for s in secs] == ["S000", "S001", "S002", "S003", "S004", "S005", "S006"]
    s000 = secs[0]
    assert (s000.heading, s000.level, s000.kind, s000.parent_id) == ("전문", 0, "other", None)
    assert (s000.block_start, s000.block_end) == (0, 1)
    assert s000.text == "제 안 요 청 서\n목  차"

    by_id = {s.id: s for s in secs}
    assert [s.level for s in secs] == [0, 1, 2, 3, 4, 1, 3]
    assert by_id["S001"].parent_id is None
    assert by_id["S002"].parent_id == "S001"
    assert by_id["S003"].parent_id == "S002"
    assert by_id["S004"].parent_id == "S003"
    assert by_id["S005"].parent_id is None
    assert by_id["S006"].parent_id == "S005"  # level 2를 건너뛴 3

    _check_ranges(secs, len(blocks))
    assert [(s.block_start, s.block_end) for s in secs] == [
        (0, 1),
        (2, 3),
        (4, 5),
        (6, 7),
        (8, 10),
        (11, 12),
        (13, 15),
    ]
    assert by_id["S001"].heading == "Ⅰ. 사업개요"
    assert by_id["S001"].text == "본 사업의 개요를 설명한다."
    assert by_id["S002"].text == ""
    assert by_id["S002"].table_ids == ["T001"]
    assert by_id["S004"].text == "세부 설명 1\n세부 설명 2"
    assert by_id["S005"].table_ids == ["T002"]
    assert by_id["S006"].table_ids == ["T003"]
    assert by_id["S006"].text == "마지막 문단"

    # kind: Ⅰ은 개요 키워드, 하위는 키워드가 없어 상속. Ⅱ는 requirements, 가.는 상속.
    assert [s.kind for s in secs] == [
        "other",
        "overview",
        "overview",
        "overview",
        "overview",
        "requirements",
        "requirements",
    ]
    assert all(s.page_start is None and s.page_end is None for s in secs)


def test_t2b_first_block_is_heading():
    blocks = make_blocks("Ⅰ. 사업개요", "본문", "1. 추진배경", "본문2")
    secs = build_sections(blocks)
    assert [s.id for s in secs] == ["S001", "S002"]
    assert secs[0].block_start == 0
    assert all(s.level != 0 for s in secs)
    _check_ranges(secs, len(blocks))


def test_no_heading_gives_single_preamble():
    blocks = make_blocks("본문 1", ("table", "T001"), "본문 2")
    secs = build_sections(blocks)
    assert len(secs) == 1
    s = secs[0]
    assert (s.id, s.heading, s.level, s.kind, s.parent_id) == ("S000", "전문", 0, "other", None)
    assert (s.block_start, s.block_end) == (0, 2)
    assert s.text == "본문 1\n본문 2"
    assert s.table_ids == ["T001"]
    _check_ranges(secs, len(blocks))


def test_no_blocks_gives_empty():
    assert build_sections([]) == []


def test_table_block_text_is_not_heading():
    blocks = [
        Block(idx=0, kind="table", text="Ⅰ. 사업개요", table_id="T001"),
        Block(idx=1, kind="paragraph", text="본문"),
    ]
    secs = build_sections(blocks)
    assert [s.id for s in secs] == ["S000"]
    assert secs[0].table_ids == ["T001"]


def test_table_id_fallback_from_tables_by_id():
    blocks = [
        Block(idx=0, kind="paragraph", text="Ⅰ. 사업개요"),
        Block(idx=1, kind="table", text=""),
    ]
    tables = {"T007": RawTable(id="T007", block_idx=1, rows=[["a"]])}
    assert build_sections(blocks)[0].table_ids == []
    assert build_sections(blocks, tables)[0].table_ids == ["T007"]


def test_t3_section_kinds():
    blocks = make_blocks(
        "4. 제안요청 내용",
        "6. 제안 안내사항",
        "나. 제안서 평가 방법",
        "[붙임 1] 기술제안서 평가항목",
        "붙임 2",
    )
    secs = build_sections(blocks)
    assert [s.kind for s in secs] == [
        "requirements",
        "eligibility",
        "evaluation",
        "attachments",
        "attachments",
    ]
    assert [s.level for s in secs][3:] == [1, 1]
    _check_ranges(secs, len(blocks))


@pytest.mark.parametrize(
    ("heading", "kind"),
    [
        ("Ⅰ. 사업개요", "overview"),
        ("2. 입찰 참가자격", "eligibility"),
        ("5. 제안서 작성요령", "proposal_guide"),
        ("3. 계약 조건", "contract"),
        ("Ⅵ. 기타사항", "contract"),
        ("2. 상세 요구사항", "requirements"),
        ("3. 기술성 평가기준", "evaluation"),
        ("Ⅱ. 시스템 현황", "other"),
    ],
)
def test_section_kind_keywords(heading, kind):
    assert build_sections(make_blocks(heading))[0].kind == kind


def test_attachment_heading_overrides_keywords():
    # 붙임 패턴 헤딩은 다른 키워드("평가")가 있어도 attachments, 하위는 상속.
    secs = build_sections(make_blocks("[별지 2] 평가 기준표", "1. 일반 항목"))
    assert [s.kind for s in secs] == ["attachments", "attachments"]
    assert secs[1].parent_id == secs[0].id


def test_toc_lines_with_trailing_page_numbers_are_not_sections():
    # 목차 줄(`\t<쪽>` 또는 공백 + 쪽번호로 끝남)은 헤딩이 아니다 → 전문에 남고 본문만 섹션.
    blocks = make_blocks(
        "제 안 요 청 서",
        "목  차",
        "Ⅰ. 사업개요\t4",
        "1. 추진배경\t 4",
        "2. 입찰 참가자격 29",
        "Ⅱ. 제안 안내사항\t 9",
        "Ⅰ. 사업개요",
        "본문",
        "1. 추진배경",
        ("table", "T001"),
        "Ⅱ. 제안 안내사항",
        "본문 끝",
    )
    secs = build_sections(blocks)
    _check_ranges(secs, len(blocks))
    assert [s.heading for s in secs] == ["전문", "Ⅰ. 사업개요", "1. 추진배경", "Ⅱ. 제안 안내사항"]
    assert secs[0].text.split("\n")[2:] == [
        "Ⅰ. 사업개요\t4",
        "1. 추진배경\t 4",
        "2. 입찰 참가자격 29",
        "Ⅱ. 제안 안내사항\t 9",
    ]
    assert [s.parent_id for s in secs] == [None, None, "S001", None]
    assert [s.kind for s in secs] == ["other", "overview", "overview", "eligibility"]
    assert secs[2].table_ids == ["T001"]


def test_check_ranges_detects_violations():
    blocks = make_blocks("Ⅰ. 사업개요", "본문", "1. 추진배경", "본문2")
    secs = build_sections(blocks)
    _check_ranges(secs, 4)
    with pytest.raises(ValueError):
        _check_ranges(secs, 5)  # 끝에 빈틈
    gap = [secs[0].model_copy(update={"block_end": 0}), secs[1]]
    with pytest.raises(ValueError):
        _check_ranges(gap, 4)
    overlap = [secs[0].model_copy(update={"block_end": 2}), secs[1]]
    with pytest.raises(ValueError):
        _check_ranges(overlap, 4)
    with pytest.raises(ValueError):
        _check_ranges([], 1)
    _check_ranges([], 0)


def test_build_sections_deterministic():
    blocks = t2_blocks()
    assert build_sections(blocks) == build_sections([b.model_copy() for b in blocks])


# --- STEP-003: 표 종류 태그와 요구사항 파서 A ---

FIXTURES = Path(__file__).parent / "fixtures"


def load_mini_hwpx() -> RawDoc:
    return RawDoc.model_validate_json((FIXTURES / "raw_mini_hwpx.json").read_text("utf-8"))


def section_lookup(doc: RawDoc):
    secs = build_sections(doc.blocks, {t.id: t for t in doc.tables})

    def block_section(block_idx: int) -> str | None:
        for s in secs:
            if s.block_start <= block_idx <= s.block_end:
                return s.id
        return None

    return block_section


def parse_tables(tables: list[RawTable], block_section=lambda _idx: None):
    kinds = {t.id: classify_table(t.rows) for t in tables}
    return parse_requirements_from_tables(tables, kinds, block_section)


def raw_table(rows: list[list[str]], tid: str = "T001", block_idx: int = 0) -> RawTable:
    return RawTable(id=tid, block_idx=block_idx, rows=rows)


def test_t8_fixture_table_kinds():
    doc = load_mini_hwpx()
    kinds = {t.id: classify_table(t.rows) for t in doc.tables}
    assert kinds == {
        "T001": "requirement_summary",
        "T002": "requirement_list",  # "요구사항 번호" 라벨 + 단독 ID 셀 4개 → list 재분류
        "T003": "requirement_detail",
        "T004": "requirement_detail",
        "T005": "requirement_detail",
        "T006": "requirement_detail",
        "T007": "evaluation_scores",
        "T008": "staffing",
        "T009": "commercial_sw",
        "T010": "schedule",
        "T011": "other",
    }


def test_classify_list_by_three_id_rows_without_label():
    rows = [["ID", "명칭"], ["SFR-001", "가"], ["SFR-002", "나"], ["SFR-003", "다"]]
    assert classify_table(rows) == "requirement_list"
    assert classify_table(rows[:3]) == "other"  # ID 행 2개는 list 기준 미달


def test_classify_two_standalone_id_cells_reclassified_to_list():
    rows = [["고유번호", "요구사항 명칭"], ["SFR-001", "가"], ["SFR-002", "나"]]
    assert classify_table(rows) == "requirement_list"


def test_classify_reference_ids_do_not_reclassify():
    rows = [
        ["요구사항 고유번호", "SFR-003"],
        ["요구사항 명칭", "검색"],
        ["세부내용", "SFR-001 참조"],
        ["관련 요구사항", "SFR-002"],
        ["화면", "관련 요구사항"],
        ["상세 검색", "SFR-004"],
    ]
    assert classify_table(rows) == "requirement_detail"


def test_classify_detail_needs_label_and_id():
    assert classify_table([["요구사항 고유번호", ""], ["요구사항 명칭", "가"]]) == "other"
    assert classify_table([["관련 요구사항", "SFR-001"]]) == "other"
    assert classify_table([]) == "other"


def test_classify_summary_needs_header_row():
    assert classify_table([["구분", "요구사항 수"], ["기능", "3"]]) == "requirement_summary"
    assert classify_table([["구분", "비고"], ["기능", "요구사항 수 3"]]) == "other"


@pytest.mark.parametrize(
    ("header", "kind"),
    [
        ("요구사항 수", "requirement_summary"),
        ("요구사항수", "requirement_summary"),
        ("요구 사항수", "requirement_summary"),
        ("요구사항 수(건)", "requirement_summary"),
        ("2. 기능요구사항 수행방안", "other"),
        ("보안 요구사항 수준", "other"),
    ],
)
def test_classify_summary_header_variants(header, kind):
    assert classify_table([["구분", header], ["기능", "3"]]) == kind


def test_t4_parser_a_two_layouts():
    doc = load_mini_hwpx()
    by_id = {t.id: t for t in doc.tables}
    reqs, warnings = parse_requirements_from_tables(
        [by_id["T003"], by_id["T004"]],
        {"T003": "requirement_detail", "T004": "requirement_detail"},
        section_lookup(doc),
    )
    assert warnings == []
    assert [r.id for r in reqs] == ["SFR-001", "MAR-001"]
    sfr, mar = reqs
    assert sfr == Requirement(
        id="SFR-001",
        category="SFR",
        name="게시판 통합 관리 기능",
        definition="여러 게시판을 한 화면에서 만들고 관리하는 기능",
        details="- 게시판 생성·삭제·권한 설정 기능 제공\n- 첨부파일 용량 제한 설정(SFR-002 참조)",
        mandatory=None,
        section_id="S004",
        table_id="T003",
        source="table",
    )
    assert mar == Requirement(
        id="MAR-001",
        category="MAR",
        name="서버 정기 점검",
        definition="서버 장애를 줄이기 위한 정기 점검 수행",
        details="o 월 1회 서버 자원 사용률 점검\no 점검 결과 보고서 제출",
        mandatory=True,
        section_id="S004",
        table_id="T004",
        source="table",
    )


def test_t5_duplicate_id_preserved():
    doc = load_mini_hwpx()
    by_id = {t.id: t for t in doc.tables}
    reqs, warnings = parse_tables([by_id["T005"], by_id["T006"]], section_lookup(doc))
    assert [r.key for r in reqs] == ["QUR-003@1", "QUR-003@2"]
    qur = reqs[0]
    assert qur.id == "QUR-003"
    assert qur.table_id == "T005"
    assert qur.name == "웹 접근성 품질 확보"
    assert qur.definition == "웹 접근성 인증 기준 충족"
    assert [r.details for r in reqs] == ["o 접근성 자체 점검 수행", "o 점검 결과에 따른 개선 조치"]
    assert qur.mandatory is False
    assert warnings == ["duplicate requirement id: QUR-003"]


def test_parser_a_full_fixture_order_and_kinds():
    doc = load_mini_hwpx()
    reqs, warnings = parse_tables(doc.tables, section_lookup(doc))
    assert [r.id for r in reqs] == ["SFR-001", "MAR-001", "QUR-003", "QUR-003"]
    assert [r.table_id for r in reqs] == ["T003", "T004", "T005", "T006"]
    assert all(r.source == "table" and r.section_id == "S004" for r in reqs)
    assert warnings == ["duplicate requirement id: QUR-003"]
    # 결정적
    assert parse_tables(doc.tables, section_lookup(doc)) == (reqs, warnings)


def test_parser_a_skips_non_detail_kinds():
    t = raw_table([["요구사항 고유번호", "SFR-001"], ["요구사항 명칭", "가"]])
    assert parse_requirements_from_tables([t], {"T001": "other"}, lambda _i: None) == ([], [])
    assert parse_requirements_from_tables([t], {}, lambda _i: None) == ([], [])


def test_parser_a_details_fallback_without_label():
    t = raw_table(
        [
            ["요구사항 고유번호", "SFR-010"],
            ["요구사항 명칭", "통합 검색"],
            ["정의", "전체 게시물 통합 검색"],
            ["- 검색어 자동완성", "- 결과 정렬  "],
        ]
    )
    (req,), warnings = parse_tables([t])
    assert warnings == []
    assert req.definition == "전체 게시물 통합 검색"
    assert req.details == "- 검색어 자동완성\n- 결과 정렬"


def test_parser_a_missing_name_uses_id_with_warning():
    t = raw_table([["요구사항 고유번호", "SER-002"], ["세부내용", "보안 서약서 제출"]])
    (req,), warnings = parse_tables([t])
    assert req.name == "SER-002"
    assert req.definition is None
    assert req.details == "보안 서약서 제출"
    assert warnings == ["missing requirement name: SER-002"]


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("필수", True),
        ("선택", False),
        ("필수 아님", None),
        ("필수 또는 선택", None),
        ("협의", None),
        ("", None),
    ],
)
def test_parser_a_mandatory_values(level, expected):
    t = raw_table(
        [
            ["요구사항 고유번호", "PMR-001", "응락 수준", level],
            ["요구사항 명칭", "인력 관리", "", ""],
            ["세부 내용", "상주 인력 관리", "", ""],
        ]
    )
    (req,), _ = parse_tables([t])
    assert req.mandatory is expected
    assert req.details == "상주 인력 관리"


def test_parser_a_value_from_next_row_and_label_id_priority():
    t = raw_table(
        [
            ["관련 요구사항", "SFR-001 참조"],
            ["요구사항 고유번호", ""],
            ["", "SFR-005"],
            ["요구사항 명칭", ""],
            ["  첨부파일 관리\n기능 ", ""],
            ["상세 내용", "업로드 용량 제한"],
        ]
    )
    assert classify_table(t.rows) == "requirement_detail"
    (req,), warnings = parse_tables([t])
    assert warnings == []
    assert req.id == "SFR-005"  # 라벨 고유번호 값이 표 전체 첫 매치(SFR-001)보다 우선
    assert req.category == "SFR"
    assert req.name == "첨부파일 관리\n기능"  # 값은 원문 그대로(strip만)
    assert req.details == "업로드 용량 제한"


def test_parser_a_does_not_take_id_from_details_when_id_field_missing():
    t = raw_table(
        [
            ["요구사항 고유번호", "미정"],
            ["요구사항 명칭", "데이터 이관"],
            ["세부내용", "DAR-002 데이터 이관 수행, DAR-003 연계"],
        ]
    )
    assert classify_table(t.rows) == "other"
    assert parse_tables([t]) == ([], [])


def test_parser_a_preserves_lettered_ids_and_merges_explicit_continuation():
    def detail(table_id, req_id, name, details):
        return raw_table(
            [
                ["요구사항 번호", req_id],
                ["요구사항 명", name],
                ["요구사항 정의", "접근 통제"],
                ["세부내용", details],
            ],
            tid=table_id,
        )

    tables = [
        detail("T001", "SFR-A-04", "검색", "기본 검색"),
        detail("T002", "SFR-A-04(계속)", "검색", "상세 필터"),
        detail("T003", "SFR-A-04", "보안 검색", "감사 이력"),
        detail("T004", "COR-02-1", "제약사항", "접근 제한"),
    ]
    reqs, warnings = parse_tables(tables)
    assert [req.id for req in reqs] == ["SFR-A-04", "SFR-A-04", "COR-02"]
    assert [req.key for req in reqs] == ["SFR-A-04@1", "SFR-A-04@2", "COR-02-1"]
    assert reqs[0].details == "기본 검색\n상세 필터"
    assert reqs[0].definition == "접근 통제"
    assert reqs[0].table_id == "T001"
    assert warnings == ["duplicate requirement id: SFR-A-04"]


def test_parser_a_reads_independent_requirements_in_a_shared_detail_table():
    table = raw_table(
        [
            ["요구사항명", "고유번호", "요구사항 정의", "관련 요구사항"],
            ["세부내용"],
            ["예방점검", "SOR-01", "정기 점검", "SOR-02"],
            ["일주일에 한 번 점검"],
            ["점검 결과 보고"],
            ["장애조치", "SOR-02", "서비스 복구", "SOR-01"],
            ["장애 원인 분석"],
        ]
    )
    reqs, warnings = parse_tables([table])
    assert [req.id for req in reqs] == ["SOR-01", "SOR-02"]
    assert [req.name for req in reqs] == ["예방점검", "장애조치"]
    assert reqs[0].definition == "정기 점검"
    assert reqs[0].details == "일주일에 한 번 점검\n점검 결과 보고"
    assert reqs[1].details == "장애 원인 분석"
    assert not warnings


def test_parser_a_collapses_an_identical_table_copied_into_another_attached_document():
    first = raw_table(
        [["요구사항 번호", "SOR-01"], ["요구사항 명", "예방점검"], ["세부내용", "정기 점검"]]
    )
    first.document_version_id = "one"
    copy = first.model_copy(update={"id": "T002", "document_version_id": "two"})
    changed = copy.model_copy(deep=True, update={"id": "T003"})
    changed.rows = [["요구사항 번호", "SOR-01"], ["요구사항 명", "예방점검"], ["세부내용", "월간 보고"]]
    reqs, warnings = parse_tables([first, copy, changed])
    assert [r.table_id for r in reqs] == ["T001", "T003"]
    assert warnings == ["duplicate requirement id: SOR-01"]


def test_parser_a_group_label_before_sub_labels():
    # "요구사항 상세설명"(그룹 라벨)과 "세부 내용"(하위 라벨)이 함께 있으면
    # 마지막 세부 라벨 이후가 details. 하위 라벨이 없으면 그룹 라벨 이후가 details
    # (정의 셀이 없을 때 정의 문구도 details에 남는다).
    with_sub = raw_table(
        [
            ["요구사항 고유번호", "QUR-001"],
            ["요구사항 명칭", "품질 관리"],
            ["요구사항 상세설명", "정의", "품질 기준 준수"],
            ["", "세부 내용", "o 품질 점검"],
            ["산출정보", "", "점검 결과서"],
        ]
    )
    (req,), _ = parse_tables([with_sub])
    assert req.definition == "품질 기준 준수"
    assert req.details == "o 품질 점검\n산출정보\n점검 결과서"

    group_only = raw_table(
        [
            ["요구사항 고유번호", "PMR-001"],
            ["요구사항 명칭", "수행조직 관리"],
            ["요구사항\n상세설명", "수행조직 구성 사항"],
            ["", "o 상주 인력은 임의 변경 불가"],
        ]
    )
    (req,), _ = parse_tables([group_only])
    assert req.definition is None
    assert req.details == "수행조직 구성 사항\no 상주 인력은 임의 변경 불가"


def test_parser_a_long_value_cell_is_not_a_label():
    # 세부 내용 문장 안의 "상세 내용"·"응락수준" 같은 단어는 라벨로 보지 않는다.
    long_text = "o 작업 결과의 상세 내용은 월간 보고서에 포함하여 제출하고 응락수준을 준수"
    t = raw_table(
        [
            ["요구사항 고유번호", "COR-004"],
            ["요구사항 명칭", "보고"],
            ["세부내용", long_text],
            ["", "o 추가 보고"],
        ]
    )
    (req,), _ = parse_tables([t])
    assert req.details == f"{long_text}\no 추가 보고"
    assert req.mandatory is None


# --- STEP-004: 요구사항 파서 B와 기대 수 교차검증 ---


def load_mini_pdf() -> RawDoc:
    return RawDoc.model_validate_json((FIXTURES / "raw_mini_pdf.json").read_text("utf-8"))


def page_blocks(*texts: str) -> list[Block]:
    """pdf형 Block(여러 줄 덩어리, 페이지 1부터)."""
    return [Block(idx=i, kind="paragraph", text=t, page=i + 1) for i, t in enumerate(texts)]


def by_block(mapping: dict[int, str]):
    return lambda idx: mapping.get(idx)


def test_t6_parser_b_fixture():
    doc = load_mini_pdf()
    reqs, warnings = parse_requirements_from_text(doc.blocks, by_block({3: "S003", 4: "S004"}))
    assert warnings == []
    assert [r.id for r in reqs] == ["SFR-001", "SFR-002", "PER-001", "SER-001"]
    assert all(r.source == "text" and r.table_id is None for r in reqs)
    sfr1, sfr2, per, ser = reqs
    # "요구사항 고유" / "번호 SFR-001" 분리 줄
    assert sfr1 == Requirement(
        id="SFR-001",
        category="SFR",
        name="게시물 일괄 관리",
        definition="여러 게시물을 한 번에 다루는 관리 기능",
        details="게시물 선택 후 일괄 이동 삭제 기능○\n이동 이력 보관 기능○",
        mandatory=None,
        section_id="S003",
        table_id=None,
        source="text",
    )
    assert sfr2.name == "방문자 문의 접수"
    assert sfr2.mandatory is True
    # 다음 쪽 첫 줄의 소제목("성능 요구사항2)")에서 details가 끝난다(spec 파서 B 종료 규칙).
    assert sfr2.details.split("\n") == [
        "문의 등록 시 담당자 알림 발송○",
        "답변 완료 시 방문자 알림○",
    ]
    # 단독 ID 줄, "요구사항 명칭" / 값 분리 줄, "세부" / "내용" 분리 라벨
    assert per.category == "PER"
    assert per.name == "화면 응답 속도"
    assert per.definition == "주요 화면 응답 시간 목표"
    assert per.details == "주요 화면은 평균 초 이내 응답 3○"
    assert per.section_id == "S004"
    # 같은 줄 라벨, 세부내용 라벨 뒤 같은 줄 본문
    assert ser.name == "접속 기록 보관"
    assert ser.mandatory is False
    assert ser.details == "접속 기록 개월 이상 보관 6○"


def test_parser_b_list_lines_do_not_start_items():
    blocks = page_blocks(
        "구분 번호 요구사항 명\n기능 요구사항 SFR-001 게시물 관리\n기능 요구사항 SFR-002 문의",
    )
    assert parse_requirements_from_text(blocks, lambda _i: None) == ([], [])


def test_parser_b_details_stop_at_classification_and_next_item():
    blocks = page_blocks(
        "요구사항 고유번호 SFR-001\n요구사항 명칭 가\n세부내용\n가 내용 1\n",
        "가 내용 2\n요구사항 분류 기능 요구사항\n분류 뒤 버려지는 줄\n"
        "SFR-002\n요구사항 명칭 나\n세부내용\n나 내용\n"
        "요구사항 고유\n번호 SFR-003\n세부내용\n다 내용",
    )
    reqs, warnings = parse_requirements_from_text(blocks, by_block({0: "S001", 1: "S002"}))
    assert [r.id for r in reqs] == ["SFR-001", "SFR-002", "SFR-003"]
    assert reqs[0].details == "가 내용 1\n가 내용 2"  # Block(페이지) 경계를 넘어 이어진다
    assert reqs[0].section_id == "S001"
    assert reqs[1].details == "나 내용"
    assert reqs[1].section_id == "S002"
    assert reqs[2].details == "다 내용"
    assert reqs[2].name == "SFR-003"
    assert warnings == ["missing requirement name: SFR-003"]


def test_parser_b_split_label_line_is_consumed_once():
    # "요구사항 고유번호" / "SFR-001": 결합 매치 후 다음 줄(단독 ID)이 다시 시작하지 않는다.
    blocks = page_blocks("요구사항 고유번호\nSFR-001\n요구사항 명칭 가\n세부내용\n본문")
    reqs, warnings = parse_requirements_from_text(blocks, lambda _i: None)
    assert warnings == []
    assert [(r.id, r.name, r.details) for r in reqs] == [("SFR-001", "가", "본문")]


def test_parser_b_duplicate_id_preserved():
    blocks = page_blocks(
        "요구사항 고유번호 QUR-003\n요구사항 명칭 품질\n세부내용\n앞 내용",
        "요구사항 고유번호 QUR-003\n요구사항 명칭 품질\n세부내용\n뒤 내용",
    )
    reqs, warnings = parse_requirements_from_text(blocks, lambda _i: None)
    assert [r.details for r in reqs] == ["앞 내용", "뒤 내용"]
    assert warnings == ["duplicate requirement id: QUR-003"]


def test_parser_b_ignores_table_blocks_and_is_deterministic():
    blocks = [
        Block(idx=0, kind="table", text="요구사항 고유번호 | SFR-009", table_id="T001"),
        Block(idx=1, kind="paragraph", text="요구사항 고유번호 SFR-001\n요구사항 명칭 가"),
    ]
    first = parse_requirements_from_text(blocks, lambda _i: None)
    assert [r.id for r in first[0]] == ["SFR-001"]
    assert first[0][0].details == ""
    assert parse_requirements_from_text(blocks, lambda _i: None) == first


def summary_table(rows: list[list[str]], tid: str = "T001") -> RawTable:
    return raw_table([["구분", "구분코드", "요구사항 수"], *rows], tid=tid)


def test_expected_from_summary_total_row():
    t = summary_table([["기능", "SFR", "20"], ["보안", "SER", "15"], ["합 계", "", "35"]])
    kinds = {"T001": "requirement_summary"}
    assert expected_requirement_count([t], kinds, []) == 35


@pytest.mark.parametrize("label", ["합계", "합  계", "합\n계", "계"])
def test_expected_total_row_label_variants(label):
    t = summary_table([["기능", "SFR", "3"], [label, "", "4"]])
    assert expected_requirement_count([t], {"T001": "requirement_summary"}, []) == 4


def test_expected_sums_rows_without_total_row():
    t = raw_table([["No", "구분", "요구사항 수"], ["1", "기능", "12"], ["2", "성능", " 2 "]])
    # 헤더 행 제외, 각 행 마지막 숫자 셀(No 열이 아니라 요구사항 수 열)의 합
    assert expected_requirement_count([t], {"T001": "requirement_summary"}, []) == 14


def test_expected_none_without_summary_table_or_text():
    t = raw_table([["구분", "비고"], ["합계", "35"]])
    assert expected_requirement_count([t], {"T001": "other"}, []) is None
    assert expected_requirement_count([], {}, page_blocks("본문만 있음")) is None


def test_t7b_expected_from_text_rule():
    blocks = page_blocks(
        "사업 개요. Ⅰ\n요구사항 총괄표1. \nNo 요구사항 구분 구분코드 요구사항 수",
        "1 기능 요구사항 SFR 20\n2 보안 요구사항 SER 15",
        "합계 35  ",
        "평가 기준표\n합    계 100",
    )
    assert expected_requirement_count([], {}, blocks) == 35


def test_expected_text_rule_fixture():
    doc = load_mini_pdf()
    assert expected_requirement_count(doc.tables, {}, doc.blocks) == 4


def test_expected_text_rule_window_is_forty_lines():
    filler = "\n".join(f"줄 {i}" for i in range(39))
    near = page_blocks(f"요구사항 총괄표\n{filler}\n합계 7")  # 트리거 뒤 40번째 줄
    far = page_blocks(f"요구사항 총괄표\n{filler}\n추가 줄\n합계 7")  # 41번째 줄
    assert expected_requirement_count([], {}, near) == 7
    assert expected_requirement_count([], {}, far) is None


def test_expected_text_rule_inline_total_and_no_trigger():
    assert expected_requirement_count([], {}, page_blocks("요구사항 수 합계 12 건")) == 12
    assert expected_requirement_count([], {}, page_blocks("평가표\n합계 100")) is None


def test_expected_text_rule_skipped_when_tables_exist():
    # spec (2)는 표가 없을 때만. 표가 있는데 총괄표가 없으면 None.
    t = raw_table([["구분", "비고"], ["가", "나"]])
    blocks = page_blocks("요구사항 총괄표\n합계 35")
    assert expected_requirement_count([t], {"T001": "other"}, blocks) is None


def detail_table(req_id: str, tid: str, block_idx: int) -> RawTable:
    return RawTable(
        id=tid,
        block_idx=block_idx,
        rows=[
            ["요구사항 고유번호", req_id],
            ["요구사항 명칭", f"{req_id} 명칭"],
            ["세부내용", f"{req_id} 세부"],
        ],
    )


def rawdoc(blocks: list[Block], tables: list[RawTable]) -> RawDoc:
    meta = RawMeta(
        chars=0,
        digits=0,
        paragraphs=0,
        tables=len(tables),
        extractor="hwpx-lxml",
        extractor_version="x",
    )
    return RawDoc(
        slug="t", format="hwpx", source_paths=["t"], blocks=blocks, tables=tables, meta=meta
    )


def t7_doc() -> RawDoc:
    ids = [f"SFR-{n:03d}" for n in range(1, 36)]
    summary = summary_table([["기능", "SFR", "35"], ["합계", "", "35"]], tid="T001")
    summary.block_idx = 0
    listing = RawTable(
        id="T002",
        block_idx=1,
        rows=[["번호", "요구사항 명"], *[[i, f"{i} 명칭"] for i in ids]],
    )
    details = [detail_table(i, f"T{n + 3:03d}", n + 2) for n, i in enumerate(ids[:34])]
    tables = [summary, listing, *details]
    blocks = [Block(idx=t.block_idx, kind="table", text="", table_id=t.id) for t in tables]
    return rawdoc(blocks, tables)


def test_t7_found_vs_expected_and_listed_but_no_detail():
    doc = t7_doc()
    kinds = {t.id: classify_table(t.rows) for t in doc.tables}
    assert kinds["T001"] == "requirement_summary"
    assert kinds["T002"] == "requirement_list"
    sel = select_requirements(doc, kinds, lambda _i: "S001")
    assert sel.expected == 35
    assert sel.found == 34
    assert len(sel.requirements) == 34
    assert all(r.source == "table" for r in sel.requirements)
    assert sel.warnings == [
        "requirements found 34 != expected 35",
        "listed but no detail: SFR-035",
    ]


def test_select_no_warning_when_counts_match():
    tables = [
        summary_table([["기능", "SFR", "1"], ["합계", "", "1"]]),
        detail_table("SFR-001", "T002", 1),
    ]
    doc = rawdoc([Block(idx=0, kind="table", text="", table_id="T001")], tables)
    kinds = {t.id: classify_table(t.rows) for t in doc.tables}
    sel = select_requirements(doc, kinds, lambda _i: None)
    assert (sel.found, sel.expected, sel.warnings) == (1, 1, [])


def test_select_falls_back_to_parser_b_when_parser_a_finds_nothing():
    text = "요구사항 고유번호 SFR-001\n요구사항 명칭 가\n세부내용\n본문"
    blocks = [
        Block(idx=0, kind="paragraph", text=text),
        Block(idx=1, kind="table", text="", table_id="T001"),
    ]
    other = raw_table([["구분", "비고"], ["가", "나"]], block_idx=1)
    sel = select_requirements(rawdoc(blocks, [other]), {"T001": "other"}, lambda _i: "S001")
    assert [(r.id, r.source, r.section_id) for r in sel.requirements] == [
        ("SFR-001", "text", "S001")
    ]
    assert sel.expected is None
    assert sel.warnings == []


def test_select_pdf_without_tables_uses_parser_b_and_text_expected():
    doc = load_mini_pdf()
    sel = select_requirements(doc, {}, lambda _i: None)
    assert [r.id for r in sel.requirements] == ["SFR-001", "SFR-002", "PER-001", "SER-001"]
    assert (sel.found, sel.expected, sel.warnings) == (4, 4, [])


def test_select_table_path_does_not_run_parser_b():
    # 표가 있고 A가 1건 이상이면 B를 쓰지 않는다(본문 줄의 ID 라벨은 무시).
    blocks = [
        Block(idx=0, kind="paragraph", text="요구사항 고유번호 SFR-009\n요구사항 명칭 본문"),
        Block(idx=1, kind="table", text="", table_id="T001"),
    ]
    doc = rawdoc(blocks, [detail_table("SFR-001", "T001", 1)])
    sel = select_requirements(doc, {"T001": "requirement_detail"}, lambda _i: None)
    assert [r.id for r in sel.requirements] == ["SFR-001"]


def test_select_no_requirements_warning():
    doc = rawdoc([Block(idx=0, kind="paragraph", text="본문")], [])
    sel = select_requirements(doc, {}, lambda _i: None)
    assert sel.requirements == []
    assert sel.found == 0
    assert sel.warnings == ["no requirements parsed"]


# --- STEP-005: 페이지 대응·SourceQuality·full_text·rfp.md ---


def pdf_doc(page_texts: list[str], warnings: list[str] | None = None) -> RawDoc:
    meta = RawMeta(
        chars=sum(len(t) for t in page_texts),
        digits=0,
        paragraphs=len(page_texts),
        tables=0,
        pages=len(page_texts),
        extractor="pypdf",
        extractor_version="x",
        warnings=warnings or [],
    )
    blocks = [Block(idx=i, kind="paragraph", text=t, page=i + 1) for i, t in enumerate(page_texts)]
    return RawDoc(
        slug="t",
        format="pdf",
        source_paths=["t.pdf"],
        blocks=blocks,
        tables=[],
        page_texts=page_texts,
        meta=meta,
    )


def head_section(n: int, heading: str, level: int = 1) -> Section:
    return make_section(
        id=f"S{n:03d}",
        heading=heading,
        level=level,
        block_start=n,
        block_end=n,
        text="",
        table_ids=[],
    )


def hwpx_stub() -> RawDoc:
    return rawdoc([], [])


def test_merge_warnings_order_and_dedup():
    assert merge_warnings(["a"], ["b", "a"], ["c"]) == ["a", "b", "c"]
    assert merge_warnings([], ["x", "x"]) == ["x"]
    assert merge_warnings() == []


def test_t7c_source_quality_warning_order():
    primary = load_mini_hwpx()
    primary.meta.warnings = ["b", "a"]
    ref = pdf_doc(["가나다"], warnings=["r", "b"])
    bundle = make_bundle(warnings=["a"])
    doc = build(bundle, primary, ref)
    # bundle → primary meta → reference pdf meta → normalize(파서·교차검증) 순, 중복 제거
    assert doc.source_quality.warnings[:3] == ["a", "b", "r"]
    assert doc.source_quality.warnings[3:] == [
        "duplicate requirement id: QUR-003",
        "listed but no detail: SFR-002",
    ]


def test_t9_page_mapping_three_sections_five_pages():
    sections = [
        head_section(1, "Ⅰ. 사업 개요"),
        head_section(2, "2. 제안 안내사항", level=2),
        head_section(3, "3. 어디에도 없는 헤딩", level=2),
    ]
    pages = ["표지", "Ⅰ.사업개요 본문", "계속", "2.제안 안내사항 본문", "끝"]
    mapped = map_pages(sections, hwpx_stub(), pdf_doc(pages))
    assert [(s.page_start, s.page_end) for s in mapped] == [(2, 3), (4, 5), (None, None)]
    assert sum(1 for s in mapped if s.page_start is not None) == 2
    # 입력은 바뀌지 않는다
    assert all(s.page_start is None for s in sections)


def test_page_mapping_search_never_goes_backwards():
    # 두 번째 섹션 헤딩이 1쪽(목차)에도 있지만 앞 섹션이 3쪽이므로 3쪽부터 찾는다
    sections = [head_section(1, "Ⅰ. 개요"), head_section(2, "1. 추진 배경", 2)]
    pages = ["1.추진배경 목차", "x", "Ⅰ.개요", "1.추진배경 본문"]
    mapped = map_pages(sections, hwpx_stub(), pdf_doc(pages))
    assert [(s.page_start, s.page_end) for s in mapped] == [(3, 3), (4, 4)]


def test_page_end_skips_unmapped_next_section():
    sections = [head_section(1, "Ⅰ. 가"), head_section(2, "Ⅱ. 없음"), head_section(3, "Ⅲ. 다")]
    pages = ["Ⅰ.가", "x", "x", "Ⅲ.다", "x"]
    mapped = map_pages(sections, hwpx_stub(), pdf_doc(pages))
    assert [(s.page_start, s.page_end) for s in mapped] == [(1, 3), (None, None), (4, 5)]


def test_page_mapping_preamble_is_none_and_no_pdf_leaves_none():
    pre = make_section(id="S000", heading="전문", level=0, kind="other", block_start=0, block_end=0)
    sections = [pre, head_section(1, "Ⅰ. 가")]
    mapped = map_pages(sections, hwpx_stub(), pdf_doc(["Ⅰ.가"]))
    assert [(s.page_start, s.page_end) for s in mapped] == [(None, None), (1, 1)]
    assert map_pages(sections, hwpx_stub(), None) == sections
    no_texts = pdf_doc(["x"])
    no_texts.page_texts = None
    assert map_pages(sections, hwpx_stub(), no_texts) == sections


def test_page_mapping_long_heading_uses_first_twenty_chars():
    long_heading = "Ⅰ. " + "가" * 30
    sections = [head_section(1, long_heading)]
    page = "가" * 20 + "다른 꼬리"  # 번호 표지를 뗀 앞 20자(공백 제거)만 같으면 매치
    mapped = map_pages(sections, hwpx_stub(), pdf_doc(["가" * 19, page]))
    assert mapped[0].page_start == 2


def test_page_mapping_pdf_primary_uses_block_pages():
    blocks = [
        Block(idx=0, kind="paragraph", text="표지", page=1),
        Block(idx=1, kind="paragraph", text="Ⅰ. 개요", page=2),
        Block(idx=2, kind="paragraph", text="본문", page=3),
        Block(idx=3, kind="paragraph", text="Ⅱ. 평가", page=4),
    ]
    meta = RawMeta(
        chars=1, digits=0, paragraphs=4, tables=0, extractor="pypdf", extractor_version="x"
    )
    primary = RawDoc(
        slug="t", format="pdf", source_paths=["t"], blocks=blocks, tables=[], meta=meta
    )
    sections = build_sections(blocks)
    mapped = map_pages(sections, primary, None)
    assert [(s.id, s.page_start, s.page_end) for s in mapped] == [
        ("S000", 1, 1),
        ("S001", 2, 3),
        ("S002", 4, 4),
    ]


def hwpx_with_pdf_pages() -> tuple[RawDoc, RawDoc]:
    pages = [
        "표지",
        "Ⅲ.제안요청 내용 1.요구사항 총괄표",
        "2.요구사항 목록 3.상세 요구사항",
        "x",
        "Ⅳ.제안서 평가",
    ]
    return load_mini_hwpx(), pdf_doc(pages)


def test_build_integration_synthetic_hwpx_with_pdf():
    primary, ref = hwpx_with_pdf_pages()
    doc = build(make_bundle(warnings=[]), primary, ref)

    assert doc.slug == "mofa-homepage-maint-2027"
    assert doc.source_files == ["a/제안요청서.hwpx", "a/제안요청서.pdf"]
    assert doc.primary_format == "hwpx"
    assert [s.id for s in doc.sections] == ["S001", "S002", "S003", "S004", "S005"]
    # 범위 불변식: 겹침·빈틈 없이 0..마지막 Block
    _check_ranges(doc.sections, len(primary.blocks))
    # 표: 모두 승계, 표 Block idx가 속한 섹션
    assert [t.id for t in doc.tables] == [f"T{n:03d}" for n in range(1, 12)]
    by_id = {t.id: t for t in doc.tables}
    for raw in primary.tables:
        sec = next(s for s in doc.sections if s.id == by_id[raw.id].section_id)
        assert sec.block_start <= raw.block_idx <= sec.block_end
        assert raw.id in sec.table_ids
    assert by_id["T003"].kind == "requirement_detail"
    assert by_id["T003"].markdown.startswith("| 요구사항 분류 | 기능 요구사항 |\n|---|---|")
    # 요구사항 section_id는 표가 속한 섹션
    assert {r.id: r.section_id for r in doc.requirements} == {
        "SFR-001": "S004",
        "MAR-001": "S004",
        "QUR-003": "S004",
    }
    assert [(s.page_start, s.page_end) for s in doc.sections] == [
        (2, 2),
        (2, 2),
        (3, 3),
        (3, 4),
        (5, 5),
    ]
    q = doc.source_quality
    assert (q.primary_format, q.primary_chars, q.primary_digits) == ("hwpx", 857, 52)
    assert (q.reference_pdf_chars, q.reference_pdf_digits) == (ref.meta.chars, 0)
    assert q.has_tables is True
    assert (q.requirements_found, q.requirements_expected) == (3, 4)
    assert q.sections_mapped_to_pages == 5
    assert "no requirements parsed" not in q.warnings


def test_build_without_reference_pdf_has_no_pages():
    doc = build(make_bundle(warnings=[]), load_mini_hwpx(), None)
    q = doc.source_quality
    assert (q.reference_pdf_chars, q.reference_pdf_digits) == (None, None)
    assert q.sections_mapped_to_pages == 0
    assert all(s.page_start is None and s.page_end is None for s in doc.sections)


def test_build_no_requirements_warns_once_and_no_headings_gives_only_preamble():
    blocks = [
        Block(idx=0, kind="paragraph", text="그냥 본문"),
        Block(idx=1, kind="paragraph", text="둘"),
    ]
    doc = build(make_bundle(warnings=[]), rawdoc(blocks, []), None)
    assert [(s.id, s.heading, s.level) for s in doc.sections] == [("S000", "전문", 0)]
    assert doc.source_quality.warnings.count("no requirements parsed") == 1
    assert doc.source_quality.has_tables is False


def test_build_pdf_primary_uses_text_parser_and_block_pages():
    primary = load_mini_pdf()
    bundle = make_bundle(primary_format="pdf", warnings=["primary format is pdf: x"])
    doc = build(bundle, primary, None)
    assert [r.id for r in doc.requirements] == ["SFR-001", "SFR-002", "PER-001", "SER-001"]
    assert doc.source_quality.requirements_expected == 4
    assert doc.source_quality.reference_pdf_chars is None
    assert doc.source_quality.warnings == ["primary format is pdf: x"]
    assert all(s.page_start is not None for s in doc.sections)


def test_build_unpositioned_tables_attach_to_last_section():
    blocks = [
        Block(idx=0, kind="paragraph", text="Ⅰ. 개요"),
        Block(idx=1, kind="paragraph", text="Ⅱ. 끝"),
        Block(idx=2, kind="table", text="", table_id="T001"),
    ]
    table = raw_table([["a", "b"], ["1", "2"]], block_idx=2)
    doc = build(make_bundle(warnings=[]), rawdoc(blocks, [table]), None)
    assert doc.tables[0].section_id == "S002"
    assert doc.sections[1].table_ids == ["T001"]


def test_build_is_deterministic():
    primary, ref = hwpx_with_pdf_pages()
    a = build(make_bundle(), primary, ref)
    b = build(make_bundle(), load_mini_hwpx(), pdf_doc(ref.page_texts or []))
    assert dump_json(a) == dump_json(b)
    assert render_rfp_md(a) == render_rfp_md(b)


def t10_doc() -> RfpDocument:
    blocks = [
        Block(idx=0, kind="paragraph", text="표지 문구"),
        Block(idx=1, kind="paragraph", text="Ⅰ. 사업 개요"),
        Block(idx=2, kind="paragraph", text="본문 한 줄"),
        Block(idx=3, kind="table", text="", table_id="T001"),
        Block(idx=4, kind="paragraph", text="1. 세부"),
        Block(idx=5, kind="paragraph", text="가. 더 세부"),
        Block(idx=6, kind="paragraph", text="1) 가장 세부"),
        Block(idx=7, kind="paragraph", text="끝줄"),
    ]
    table = raw_table([["구분", "비고|참고"], ["가", "나\n다"]], block_idx=3)
    return build(make_bundle(warnings=["w1"]), rawdoc(blocks, [table]), None)


def test_t10_full_text_rendering():
    doc = t10_doc()
    assert doc.full_text.split("\n") == [
        "표지 문구",  # 전문은 헤딩 줄 없음
        "# Ⅰ. 사업 개요",
        "본문 한 줄",
        "| 구분 | 비고\\|참고 |",
        "|---|---|",
        "| 가 | 나 다 |",
        "## 1. 세부",
        "### 가. 더 세부",
        "#### 1) 가장 세부",
        "끝줄",
    ]


def test_t10_rfp_md_rendering():
    doc = t10_doc()
    md = render_rfp_md(doc)
    lines = md.split("\n")
    assert lines[0] == f"# {doc.title}"
    assert "- slug: mofa-homepage-maint-2027" in lines
    assert "- primary_format: hwpx / source_files: a/제안요청서.hwpx, a/제안요청서.pdf" in lines
    assert "- requirements: 0 / expected: -" in lines
    assert "- warnings: w1; no requirements parsed" in lines
    assert "## 요구사항 (0건)" in lines
    # 섹션 헤딩은 level+1 개의 #, 전문(level 0)도 ##
    assert "## 전문  <!-- S000 kind=other p.- -->" in lines
    assert "## Ⅰ. 사업 개요  <!-- S001 kind=overview p.- -->" in lines
    assert "### 1. 세부  <!-- S002 kind=overview p.- -->" in lines
    assert "#### 가. 더 세부  <!-- S003 kind=overview p.- -->" in lines
    assert "##### 1) 가장 세부  <!-- S004 kind=overview p.- -->" in lines
    # 표 마커와 마크다운은 해당 섹션 본문 뒤에
    i = lines.index("<!-- T001 -->")
    assert lines[i - 2 : i] == ["본문 한 줄", ""]
    assert lines[i + 1 : i + 4] == ["| 구분 | 비고\\|참고 |", "|---|---|", "| 가 | 나 다 |"]
    assert md.endswith("끝줄\n")


def test_rfp_md_requirement_table_and_page_labels():
    primary, ref = hwpx_with_pdf_pages()
    doc = build(make_bundle(warnings=[]), primary, ref)
    doc.requirements[0].name = "이름|파이프"
    md = render_rfp_md(doc)
    lines = md.split("\n")
    assert "## 요구사항 (4건)" in lines
    assert "| ID | 분류 | 명칭 | 필수 | 섹션 |" in lines
    assert "| SFR-001 | SFR | 이름\\|파이프 | - | S004 |" in lines
    assert "| MAR-001 | MAR | 서버 정기 점검 | 필수 | S004 |" in lines
    assert "| QUR-003 | QUR | 웹 접근성 품질 확보 | 선택 | S004 |" in lines
    assert "## Ⅲ. 제안요청 내용  <!-- S001 kind=requirements p.2 -->" in lines
    assert "### 3. 상세 요구사항  <!-- S004 kind=requirements p.3-4 -->" in lines


def test_rfp_md_page_range_label():
    doc = t10_doc()
    doc.sections[1].page_start, doc.sections[1].page_end = 31, 33
    doc.sections[2].page_start, doc.sections[2].page_end = 33, 33
    lines = render_rfp_md(doc).split("\n")
    assert "## Ⅰ. 사업 개요  <!-- S001 kind=overview p.31-33 -->" in lines
    assert "### 1. 세부  <!-- S002 kind=overview p.33 -->" in lines


# --- STEP-006: 실데이터 검증으로 보강한 규칙 ---


@pytest.mark.parametrize(
    ("heading", "rest"),
    [
        ("Ⅳ. 사업자 선정 및 제안 안내", "사업자 선정 및 제안 안내"),
        ("Ⅲ．사업 내용", "사업 내용"),
        ("제 3 장 제안요청 내용", "제안요청 내용"),
        ("2. 입찰 참가자격", "입찰 참가자격"),
        ("가. 사업 목적", "사업 목적"),
        ("1) 세부 내용", "세부 내용"),
        ("[붙임 1] 기술제안서 평가항목", "기술제안서 평가항목"),
        ("【별표 4-1】사업자 보안관리 준수사항", "사업자 보안관리 준수사항"),
        ("붙임 1. 제안서 관련 서식", "제안서 관련 서식"),
        ("[별지 제1호 서식]", ""),
        ("붙임 2", ""),
        ("본문 문장", "본문 문장"),
    ],
)
def test_strip_heading_mark(heading, rest):
    assert strip_heading_mark(heading) == rest


@pytest.mark.parametrize(
    ("heading", "prefix"),
    [
        ("2. 입찰 참가자격", "입찰참가자격"),
        ("Ⅰ. 사업개요\t4", "사업개요"),  # 끝 쪽번호도 뗀다
        ("Ⅰ 사업 개요", "사업개요"),
        (
            "가. 유지관리 수행 요구사항(MAR, Maintenance Requirement)",
            "유지관리수행요구사항(MAR,Maint",
        ),
        ("[붙임 1]", ""),
        ("붙임 2", ""),
    ],
)
def test_page_prefix_strips_marks_and_page_number(heading, prefix):
    assert page_prefix(heading) == prefix


def test_page_mapping_ignores_heading_number_scattered_in_pdf():
    # pdf 텍스트에서는 번호가 뒤로 밀려 "입찰 참가자격2."처럼 찍힌다.
    sections = [head_section(1, "2. 입찰 참가자격", level=2), head_section(2, "붙임 2")]
    pages = ["표지", "입찰 참가자격2. 본문", "붙임 2"]
    mapped = map_pages(sections, hwpx_stub(), pdf_doc(pages))
    assert mapped[0].page_start == 2
    assert (mapped[1].page_start, mapped[1].page_end) == (None, None)  # 표지만 있는 헤딩


def test_page_mapping_skips_pdf_toc_leader_lines():
    # pdf 목차 쪽의 리더 줄("입찰 참가자격······ 29")은 검색 대상에서 빠진다.
    sections = [head_section(1, "1. 사업 개요", level=2), head_section(2, "2. 입찰 참가자격", 2)]
    pages = [
        "목 차\n사업 개요· · · · · · · · 1\n입찰 참가자격·········· 29",
        "사업 개요1.\n본문",
        "x",
        "입찰 참가자격2.",
    ]
    mapped = map_pages(sections, hwpx_stub(), pdf_doc(pages))
    assert [(s.page_start, s.page_end) for s in mapped] == [(2, 3), (4, 4)]


@pytest.mark.parametrize(
    "text",
    [
        "Ⅰ. 사업개요\t4",
        "1. 추진배경\t 4",
        "Ⅰ. 사업개요  1",
        "2. 입찰 참가자격 29",
        "제1장 총칙 1",
        "[붙임1] 종합서비스수준 관리지표 10",
        "붙임 1. 제안서 관련 서식\t33",
        "가. 추진배경 및 필요성\t4",
    ],
)
def test_toc_page_number_lines_are_not_headings(text):
    assert is_toc_line(text)
    assert detect_heading(text) is None


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("붙임 2", 1),  # 번호가 표지의 일부 → 쪽번호가 아니다
        ("[붙임 2]", 1),
        ("별지 제2호", 1),
        ("제2장 일반사항", 1),
        ("2. 장애등급별 가중치 : 1등급 장애 2.5", 2),  # 소수는 쪽번호가 아니다
        ("나. 사업기간 2027", 3),  # 4자리 숫자는 쪽번호가 아니다
        ("4.1 장애 조치 내역 (00건)", 2),
    ],
)
def test_toc_rule_keeps_body_headings(text, level):
    assert not is_toc_line(text)
    assert detect_heading(text) == level


@pytest.mark.parametrize(
    "text",
    [
        "[붙임 1]",
        "[붙임 1] 기술제안서 평가항목",
        "【서식 2】",
        "(별지 1)",
        "붙임 1",
        "별지 제2호",
        "서식2",
        "【별표 4-1】사업자 보안관리 준수사항",
        "[별지 제1호 서식]",
        "【별지 제10호 서식】",
        "(별지 제2호 서식)",
        "【붙임자료】",
        "[첨부]",
        "[첨부1]",
        "붙임 1. 제안서 관련 서식",
    ],
)
def test_attachment_heading_bracket_or_number(text):
    assert classify_heading(text) == (1, True)


@pytest.mark.parametrize(
    "text",
    [
        "첨부파일 미리보기",
        "첨부자료 암호화 후 수·발신 할 수 있으나, 대외비 이상의 비밀 자",
        "첨부 : 법인 인감증명서 1통(개인인 경우 대표자 인감증명서)",
        "첨부",
        "별지",
        "서식 조정 가능",
        "[별표8]에 따라 평가",  # 괄호 표기 뒤 조사 → 본문 속 참조
        "[별표 3]의 ‘누출금지 정보의 범위’에 대한 정보 누출 시 발주기관은",
        "별표 1의 기준",
    ],
)
def test_attachment_like_body_lines_are_not_headings(text):
    assert classify_heading(text) is None


def test_body_attachment_line_does_not_capture_following_sections():
    secs = build_sections(
        make_blocks("Ⅱ. 시스템 현황", "첨부파일 미리보기", "1. H/W 구성도 및 현황", "본문")
    )
    assert [s.heading for s in secs] == ["Ⅱ. 시스템 현황", "1. H/W 구성도 및 현황"]
    assert secs[0].text == "첨부파일 미리보기"
    assert secs[1].parent_id == secs[0].id
    assert [s.kind for s in secs] == ["other", "other"]


def test_split_roman_heading_is_merged():
    blocks = make_blocks(
        "표지",  # 0 전문
        "Ⅰ",  # 1 S001(헤딩 첫 줄)
        "사업 개요",  # 2 헤딩 둘째 줄
        "1. 사업개요",  # 3 S002
        "본문",  # 4
        "Ⅱ.",  # 5 S003
        "",  # 6 빈 줄(건너뜀)
        "시스템 현황",  # 7
        "x",  # 8
    )
    secs = build_sections(blocks)
    _check_ranges(secs, len(blocks))
    assert [(s.id, s.heading, s.level) for s in secs] == [
        ("S000", "전문", 0),
        ("S001", "Ⅰ 사업 개요", 1),
        ("S002", "1. 사업개요", 2),
        ("S003", "Ⅱ. 시스템 현황", 1),
    ]
    assert [(s.block_start, s.block_end) for s in secs] == [(0, 0), (1, 2), (3, 4), (5, 8)]
    assert secs[1].text == ""  # 합쳐진 둘째 줄은 헤딩 Block
    assert secs[3].text == "x"
    assert secs[1].kind == "overview"
    assert secs[2].parent_id == "S001"


def test_split_roman_heading_not_merged_with_table_or_heading():
    # 다음이 table이거나 그 자체로 헤딩이면 합치지 않는다(단독 "Ⅰ"은 헤딩이 아니다).
    secs = build_sections(make_blocks("Ⅰ", ("table", "T001"), "본문"))
    assert [s.id for s in secs] == ["S000"]
    secs = build_sections(make_blocks("Ⅰ", "1. 사업개요", "본문"))
    assert [(s.heading, s.level) for s in secs] == [("전문", 0), ("1. 사업개요", 2)]
    assert secs[0].text == "Ⅰ"


def test_split_roman_heading_full_text_not_duplicated():
    blocks = make_blocks("Ⅰ", "사업 개요", "본문")
    doc = build(make_bundle(), rawdoc(blocks, []), None)
    assert doc.full_text.split("\n") == ["# Ⅰ 사업 개요", "본문"]


@pytest.mark.parametrize("text", ["20  .  .  .", "20 . . .", "2026.  .  ."])
def test_blank_date_line_is_not_heading(text):
    assert detect_heading(text) is None


def test_blank_date_rule_keeps_number_headings():
    assert detect_heading("20. 기타") == 2
    assert detect_heading("2.1 정보자원 현황") == 2


@pytest.mark.parametrize(
    ("heading", "kind"),
    [
        ("1. 개 요", "overview"),
        ("2. 입 찰 참 가 자 격", "eligibility"),
        ("Ⅶ. 기 타 사 항", "contract"),
        ("나. 제안서 평가 방법", "evaluation"),
        ("3. 사업 범위", "overview"),
        ("가. 추진 방안", "overview"),
    ],
)
def test_section_keywords_ignore_spaces(heading, kind):
    assert build_sections(make_blocks(heading))[0].kind == kind


def test_parser_b_details_end_at_subtitle_and_list_rows():
    blocks = page_blocks(
        "요구사항 고유번호 SFR-001\n요구사항 명칭 가\n세부내용\n가 내용○\n"
        "테스트 요구사항 TER-001 단위 테스트\n프로젝트 관리 요구\n사항 PMR-001 사업관리\n"
        "요구사항 고유번호 SFR-002\n요구사항 명칭 나\n세부내용\n나 내용○\n제약사항8)\n"
        "요구사항 고유번호 SFR-003\n요구사항 명칭 다\n세부내용\n다 내용○\n"
        "1. 다음 절\n다음 절 본문\n"
        "요구사항 고유번호 SFR-004\n요구사항 명칭 라\n세부내용\n라 내용○\n"
        "SFR-001 참조하여 구현○",
    )
    reqs, warnings = parse_requirements_from_text(blocks, lambda _i: None)
    assert warnings == []
    assert [(r.id, r.details) for r in reqs] == [
        ("SFR-001", "가 내용○"),  # 목록표 행("… 요구사항 <ID> …")에서 끝
        ("SFR-002", "나 내용○"),  # 소제목 "제약사항8)"에서 끝
        ("SFR-003", "다 내용○"),  # 헤딩 패턴 줄에서 끝
        ("SFR-004", "라 내용○\nSFR-001 참조하여 구현○"),  # 참조 ID는 목록표 행이 아니다
    ]


def test_parser_b_last_item_ends_at_tail_keywords_only():
    blocks = page_blocks(
        "요구사항 고유번호 SFR-001\n요구사항 명칭 가\n세부내용\n평가 결과를 반영○\n"
        "요구사항 고유번호 SFR-002\n요구사항 명칭 나\n세부내용\n나 내용○",
        "평 가 항 목 기 준 표\n평가항목 및 배점\n합계 100",
    )
    reqs, _ = parse_requirements_from_text(blocks, lambda _i: None)
    # 마지막이 아닌 항목은 "평가…" 줄에서 끝나지 않고, 마지막 항목은 끝난다.
    assert [(r.id, r.details) for r in reqs] == [
        ("SFR-001", "평가 결과를 반영○"),
        ("SFR-002", "나 내용○"),
    ]


@pytest.mark.parametrize(
    "tail", ["요구사항 총괄표", "붙임 1 서식", "[서식 1] 제안서", "별지 제1호", "첨부 서류"]
)
def test_parser_b_last_item_tail_variants(tail):
    blocks = page_blocks(
        f"요구사항 고유번호 SFR-001\n요구사항 명칭 가\n세부내용\n가 내용○\n{tail}\n뒤"
    )
    reqs, _ = parse_requirements_from_text(blocks, lambda _i: None)
    assert reqs[0].details == "가 내용○"


# 실제 상세표(R26BD00305325, 2026-11-27): ID를 `SFR - 002`처럼 하이픈 앞뒤에 공백을 두고 적는다.
# 기대 수(요약표 60)는 세면서 상세표 ID를 읽지 못해 4개만 뽑던 문제의 회귀 시험이다.
def test_detail_table_reads_ids_written_with_spaced_hyphen():
    t = raw_table(
        [
            ["고유번호", "SFR - 002"],
            ["요구사항 분류", "기능 요구사항"],
            ["요구사항 명칭", "사용량 분석자료 등록 기능"],
            ["요구사항상세설명", "정의", "정해진 입력자료 양식에 맞춘 엑셀자료를 업로드하는 기능"],
            ["세부내용", "❍ 수도미터 사용량 자료 업로드"],
        ]
    )
    assert classify_table(t.rows) == "requirement_detail"
    (req,), _warnings = parse_tables([t])
    assert (req.id, req.category, req.name) == ("SFR-002", "SFR", "사용량 분석자료 등록 기능")


@pytest.mark.parametrize("written", ["SFR - 002", "SFR -002", "SFR- 002", "SFR-002", "SFR - A - 04"])
def test_detail_table_id_hyphen_spacing_variants(written):
    t = raw_table([["요구사항 고유번호", written], ["요구사항 명칭", "가"], ["세부내용", "나"]])
    (req,), _warnings = parse_tables([t])
    assert req.id == written.replace(" ", "")


def test_detail_rows_read_ids_written_with_spaced_hyphen():
    t = raw_table(
        [
            ["요구사항 고유번호", "요구사항 명칭", "정의"],
            ["세부내용", "", ""],
            ["COR - 001", "제약사항 일반", "준수 사항"],
            ["- 관련 법령 준수", "", ""],
            ["COR - 002", "보안 제약", "보안 지침"],
        ]
    )
    reqs, _warnings = parse_tables([t])
    assert [r.id for r in reqs] == ["COR-001", "COR-002"]


def test_spaced_hyphen_folding_does_not_touch_prose():
    t = raw_table(
        [
            ["요구사항 고유번호", "SFR - 003"],
            ["요구사항 명칭", "기간 분석 (2026 - 2027)"],
            ["세부내용", "SFR - 001 참조"],
        ]
    )
    (req,), _warnings = parse_tables([t])
    assert req.id == "SFR-003"
    assert req.name == "기간 분석 (2026 - 2027)"
    assert req.details == "SFR - 001 참조"
