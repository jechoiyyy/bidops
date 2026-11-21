"""RawDoc을 RfpDocument로 정규화한다(M0-04). 이 모듈은 단계별로 채워진다."""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from bid_deep_engine.ingest.models import (
    Block,
    NoticeBundle,
    RawDoc,
    RawTable,
    Requirement,
    RfpDocument,
    Section,
    SectionKind,
    SourceQuality,
    Table,
    TableKind,
)

# --- 헤딩 인식(spec "헤딩 인식") ---
HEADING_MAX_LEN = 60  # tunable
TOC_REPEAT = 5  # tunable: `·`/`…`이 이만큼 연속이면 목차 줄로 보아 제외

_TOC_LEADER = re.compile(rf"[·…]{{{TOC_REPEAT},}}")
# 목차 줄: 번호 표지 뒤 텍스트가 공백(탭 포함) + 1~3자리 쪽번호로 끝난다("Ⅰ. 사업개요\t4").
_TOC_PAGE_SUFFIX = re.compile(r"\S\s+\d{1,3}$")
_SENTENCE_END = re.compile(r"(다|함|음)\.$")
_YEAR_PREFIX = re.compile(r"^\d{4}\.")
_BLANK_DATE = re.compile(r"^\d{1,2}\s*[\.．]\s*[\.．]")  # 서명란 빈 날짜 서식("20  .  .  .")

_NO_SPACE = re.compile(r"\s+")


def _squash(text: str) -> str:
    """공백을 모두 지우고 NFC로 맞춘다(pdf 텍스트의 공백·분해형 차이를 흡수)."""
    return unicodedata.normalize("NFC", _NO_SPACE.sub("", text))


_ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
_ATT_KW = r"(?:붙임|별지|별표|서식|첨부)"
_ATT_NO = r"(?:제\s*)?\d+(?:\s*-\s*\d+)?\s*호?"  # 1 · 4-1 · 제2호
# 붙임·서식 표지: 괄호 표기([붙임 1]·【별지 제2호 서식】·(별지 1)·【붙임자료】)
# 또는 키워드 바로 뒤 번호(붙임 1·별지 제2호·서식2)
_ATT_CORE = (
    rf"(?:[\[【(]\s*{_ATT_KW}\s*(?:{_ATT_NO})?\s*(?:서식|자료)?\s*[\]】)]"
    rf"|{_ATT_KW}\s*{_ATT_NO}(?!\d))"
)
# 번호 표지(헤딩 패턴의 접두). 표지 뒤 텍스트가 페이지 대응 접두·목차 판정의 대상이다.
_MARKS: dict[str, str] = {
    "roman": rf"[{_ROMAN}]\s*[\.．]?\s*",
    "chapter": r"제\s*\d+\s*장\s*",
    "attachment": rf"{_ATT_CORE}\s*[\.．:]?\s*",
    "number": r"\d{1,2}\s*[\.．]\s*",
    "hangul": r"[가나다라마바사아자차카타파하]\s*[\.．]\s*",
    "paren": r"\d{1,2}\s*[\)）]\s*",
}
_MARK_RES = {k: re.compile(f"^{v}") for k, v in _MARKS.items()}
# 붙임 표지 바로 뒤에 조사가 붙으면 본문 속 참조다("[별표8]에 따라 평가", "[별표 3]의 …").
_ATT_CORE_RE = re.compile(f"^{_ATT_CORE}")
_ATT_JOSA = re.compile(r"^(?:에서|에|의|을|를|과|와|으로|로)(?:\s|$)")

_ROMAN_HEADING = re.compile(rf"^{_MARKS['roman']}\S")
_CHAPTER_HEADING = re.compile(rf"^{_MARKS['chapter']}\S")
_ATTACHMENT_HEADING = _ATT_CORE_RE
_NUMBER_HEADING = re.compile(rf"^{_MARKS['number']}\S")
_HANGUL_HEADING = re.compile(rf"^{_MARKS['hangul']}\S")
_PAREN_NUMBER_HEADING = re.compile(rf"^{_MARKS['paren']}\S")
_ROMAN_ALONE = re.compile(rf"^[{_ROMAN}]\s*[\.．]?$")  # 쪼개진 level 1 헤딩의 앞 줄("Ⅰ")

# 위에서부터 첫 매치. (정규식, level, 붙임·서식 헤딩 여부)
_HEADING_PATTERNS: list[tuple[re.Pattern[str], int, bool]] = [
    (_ROMAN_HEADING, 1, False),
    (_CHAPTER_HEADING, 1, False),
    (_ATTACHMENT_HEADING, 1, True),
    (_NUMBER_HEADING, 2, False),
    (_HANGUL_HEADING, 3, False),
    (_PAREN_NUMBER_HEADING, 4, False),
]


def _is_attachment_heading(text: str) -> bool:
    """붙임·서식 헤딩: 괄호 표기 또는 키워드 바로 뒤 번호. 괄호 뒤에 조사가 붙으면 아니다."""
    m = _ATT_CORE_RE.match(text)
    return m is not None and not _ATT_JOSA.match(text[m.end() :])


def strip_heading_mark(text: str) -> str:
    """헤딩 앞의 번호 표지(로마숫자·제N장·붙임 표기·1.·가.·1))를 뗀 나머지(strip).

    표지가 없으면 원문 strip. 표지만 있는 헤딩("붙임 2", "[붙임 1]")은 빈 문자열.
    """
    t = text.strip()
    for key in ("roman", "chapter", "attachment", "number", "hangul", "paren"):
        m = _MARK_RES[key].match(t)
        if m:
            return t[m.end() :].strip()
    return t


def is_toc_line(text: str) -> bool:
    """목차 줄: `·`/`…` 반복, 또는 번호 표지 뒤 텍스트가 공백 + 1~3자리 쪽번호로 끝남."""
    t = text.strip()
    return bool(_TOC_LEADER.search(t) or _TOC_PAGE_SUFFIX.search(strip_heading_mark(t)))


def classify_heading(text: str) -> tuple[int, bool] | None:
    """paragraph 텍스트가 헤딩이면 (level, 붙임·서식 헤딩 여부), 아니면 None.

    앞뒤 공백을 제거한 뒤 판정한다. 길이 초과·문장 종결(`다.`/`함.`/`음.`)·목차 줄(`·`/`…`
    연속 또는 끝 쪽번호)·연도(`2026.`)·빈 날짜 서식(`20  .  .  .`)은 제외하고, 패턴 표를
    위에서부터 첫 매치한다.
    """
    t = text.strip()
    if not t or len(t) > HEADING_MAX_LEN:
        return None
    if _SENTENCE_END.search(t) or _YEAR_PREFIX.match(t) or _BLANK_DATE.match(t):
        return None
    if is_toc_line(t):
        return None
    for pattern, level, is_attachment in _HEADING_PATTERNS:
        if is_attachment:
            if _is_attachment_heading(t):
                return level, True
        elif pattern.match(t):
            return level, False
    return None


def detect_heading(text: str) -> int | None:
    """헤딩 level(1~4) 또는 None."""
    hit = classify_heading(text)
    return None if hit is None else hit[0]


# --- 섹션 종류 태그(spec "섹션 종류 태그"): 순서대로 첫 매치. tunable ---
# 키워드는 공백 없는 형태로 두고, 헤딩 원문(strip)과 공백 제거형 둘 다에 search한다("개 요"→개요).
# attachments는 헤딩 인식의 붙임·서식 판정(_is_attachment_heading)과 같은 기준이다.
SECTION_KEYWORDS: list[tuple[SectionKind, list[re.Pattern[str]]]] = [
    ("requirements", [re.compile(p) for p in ("요구사항", "제안요청내용", "상세요구", "과업내용")]),
    ("evaluation", [re.compile(p) for p in ("평가", "배점", "기술성", "기술능력")]),
    (
        "eligibility",
        [re.compile(p) for p in ("참가자격", "입찰참가", "사업자선정", "입찰방식", "제안안내")],
    ),
    (
        "proposal_guide",
        [re.compile(p) for p in ("제안서작성", "제안서목차", "작성요령", "제안서제출")],
    ),
    (
        "contract",
        [re.compile(p) for p in ("계약", "지식재산권", "하도급", "기타사항", "특수조건")],
    ),
    (
        "overview",
        [re.compile(p) for p in ("개요", "추진배경", "사업범위", "추진방안", "기대효과")],
    ),
]

PREAMBLE_ID = "S000"
PREAMBLE_HEADING = "전문"


def _keyword_kind(heading: str) -> SectionKind | None:
    t = heading.strip()
    if _is_attachment_heading(t):
        return "attachments"
    squashed = _squash(t)
    for kind, patterns in SECTION_KEYWORDS:
        if any(p.search(t) or p.search(squashed) for p in patterns):
            return kind
    return None


@dataclass(frozen=True)
class _Head:
    pos: int  # 헤딩 첫 Block의 blocks 내 위치
    last: int  # 헤딩에 포함된 마지막 Block 위치(쪼개진 헤딩이면 두 번째 줄, 아니면 pos)
    level: int
    is_attachment: bool
    text: str  # 헤딩 텍스트(strip; 쪼개진 헤딩은 "Ⅰ 사업 개요"처럼 공백 하나로 결합)


def _split_roman_head(blocks: list[Block], pos: int) -> _Head | None:
    """`Ⅰ` 단독 줄 + 다음 비어 있지 않은 paragraph → 하나의 level 1 헤딩.

    사이에는 빈 paragraph만 허용한다(table Block이 끼면 합치지 않는다). 다음 줄이 그 자체로
    헤딩이면 합치지 않고, 합친 텍스트가 로마숫자 헤딩으로 인식될 때만 합친다.
    """
    for nxt in range(pos + 1, len(blocks)):
        b = blocks[nxt]
        if b.kind != "paragraph":
            return None
        if not b.text.strip():
            continue
        if classify_heading(b.text) is not None:
            return None  # 다음 줄이 그 자체로 헤딩이면 합치지 않는다
        merged = f"{blocks[pos].text.strip()} {b.text.strip()}"
        hit = classify_heading(merged)
        if hit is None or hit != (1, False) or not _ROMAN_HEADING.match(merged):
            return None
        return _Head(pos=pos, last=nxt, level=1, is_attachment=False, text=merged)
    return None


def _detect_heads(blocks: list[Block]) -> list[_Head]:
    """paragraph Block 중 헤딩(쪼개진 level 1 헤딩 포함)을 문서 순으로."""
    heads: list[_Head] = []
    pos = 0
    while pos < len(blocks):
        b = blocks[pos]
        if b.kind == "paragraph":
            if _ROMAN_ALONE.match(b.text.strip()):
                head = _split_roman_head(blocks, pos)
                if head is not None:
                    heads.append(head)
                    pos = head.last + 1
                    continue
            hit = classify_heading(b.text)
            if hit is not None:
                heads.append(_Head(pos, pos, hit[0], hit[1], b.text.strip()))
        pos += 1
    return heads


def build_sections(
    blocks: list[Block], tables_by_id: dict[str, RawTable] | None = None
) -> list[Section]:
    """Block 나열을 평면 범위의 섹션 목록으로 만든다(트리는 parent_id로만).

    paragraph Block만 헤딩 후보다. 첫 헤딩 이전에 Block이 있으면 전문(S000)을 둔다.
    쪼개진 level 1 헤딩("Ⅰ" + "사업 개요")은 첫 Block부터 범위를 잡고, 두 번째 줄까지를
    헤딩 Block으로 보아 text에서 뺀다.
    page_start/page_end는 여기서 채우지 않는다(페이지 대응 단계가 채운다).
    `tables_by_id`가 있으면 table_id가 비어 있는 table Block을 RawTable.block_idx로 보완한다.
    """
    if not blocks:
        return []

    table_at: dict[int, str] = {}
    if tables_by_id:
        for tid in sorted(tables_by_id):
            table_at.setdefault(tables_by_id[tid].block_idx, tid)

    heads = _detect_heads(blocks)

    # (시작 위치, 본문 시작 위치, 끝 위치(포함), 헤딩 또는 None(전문))
    spans: list[tuple[int, int, int, _Head | None]] = []
    first_head = heads[0].pos if heads else len(blocks)
    if first_head > 0:
        spans.append((0, 0, first_head - 1, None))
    for i, head in enumerate(heads):
        end = heads[i + 1].pos - 1 if i + 1 < len(heads) else len(blocks) - 1
        spans.append((head.pos, head.last + 1, end, head))

    sections: list[Section] = []
    stack: list[Section] = []  # level이 증가하는 조상 후보(전문 제외)
    number = 0
    for start, body_start, end, head in spans:
        rng = blocks[start : end + 1]
        body = blocks[body_start : end + 1]
        text = "\n".join(b.text for b in body if b.kind == "paragraph")
        table_ids = []
        for b in rng:
            if b.kind != "table":
                continue
            tid = b.table_id or table_at.get(b.idx)
            if tid is not None:
                table_ids.append(tid)

        if head is None:
            sections.append(
                Section(
                    id=PREAMBLE_ID,
                    heading=PREAMBLE_HEADING,
                    level=0,
                    kind="other",
                    parent_id=None,
                    block_start=blocks[start].idx,
                    block_end=blocks[end].idx,
                    text=text,
                    table_ids=table_ids,
                )
            )
            continue

        level = head.level
        while stack and stack[-1].level >= level:
            stack.pop()
        parent = stack[-1] if stack else None
        if head.is_attachment:
            kind: SectionKind = "attachments"
        else:
            kind = _keyword_kind(head.text) or (parent.kind if parent else "other")
        number += 1
        sec = Section(
            id=f"S{number:03d}",
            heading=head.text,
            level=level,
            kind=kind,
            parent_id=parent.id if parent else None,
            block_start=blocks[start].idx,
            block_end=blocks[end].idx,
            text=text,
            table_ids=table_ids,
        )
        sections.append(sec)
        stack.append(sec)
    return sections


def _check_ranges(sections: list[Section], n_blocks: int) -> None:
    """섹션 범위 불변식: 0부터 n_blocks-1까지 겹침·빈틈 없이 문서 순으로 덮는다.

    위반 시 ValueError.
    """
    if n_blocks == 0:
        if sections:
            raise ValueError("sections exist for empty block list")
        return
    if not sections:
        raise ValueError("no sections for non-empty block list")
    expected = 0
    for s in sections:
        if s.block_start != expected:
            raise ValueError(f"{s.id}: block_start {s.block_start} != expected {expected}")
        if s.block_end < s.block_start:
            raise ValueError(f"{s.id}: block_end {s.block_end} < block_start {s.block_start}")
        expected = s.block_end + 1
    if expected != n_blocks:
        raise ValueError(f"sections end at {expected - 1}, last block is {n_blocks - 1}")


def _md_cell(text: str) -> str:
    """마크다운 표 셀 이스케이프: 줄바꿈은 공백 하나, `|`는 `\\|`."""
    return text.replace("\r\n", " ").replace("\n", " ").replace("|", "\\|")


def render_table_markdown(rows: list[list[str]]) -> str:
    """표 행을 마크다운 표로 렌더한다. 결정적이다.

    첫 행이 헤더이고 그 뒤에 구분 행이 온다. 셀 내 `|`는 `\\|`로, 줄바꿈은 공백 하나로 바꾼다.
    행 길이가 다르면 최대 열 수로 빈 셀을 채운다. 빈 표는 빈 문자열이다.
    """
    width = max((len(r) for r in rows), default=0)
    if width == 0:
        return ""

    def line(row: list[str]) -> str:
        padded = [*row, *([""] * (width - len(row)))]
        return "| " + " | ".join(_md_cell(c) for c in padded) + " |"

    lines = [line(rows[0]), "|" + "|".join(["---"] * width) + "|"]
    lines.extend(line(r) for r in rows[1:])
    return "\n".join(lines)


# --- 표 종류 태그(spec "표 종류 태그") ---
REQ_ID = r"[A-Z]{3}-\d{3}(?:-\d+)*"
_REQ_ID_RE = re.compile(REQ_ID)
_REQ_ID_FULL = re.compile(rf"^{REQ_ID}$")
_WS = re.compile(r"\s+")

_DETAIL_ID_LABEL = re.compile(r"요구사항\s*(고유)?\s*번호|고유번호")

# 종류별 패턴 묶음: 묶음 안 모든 패턴이 (표의 어떤 셀에서든) 매치해야 한다. tunable.
# requirement_detail은 이 패턴 + ID 셀, requirement_summary는 헤더 행(첫 행)에서만 본다.
# requirement_list는 키워드가 아니라 ID 행 수(LIST_MIN_ID_ROWS)로 판정한다.
TABLE_KEYWORDS: dict[TableKind, list[re.Pattern[str]]] = {
    "requirement_detail": [_DETAIL_ID_LABEL],
    # spec `요구사항\s*수`를 실데이터에 맞춰 보강: "요구 사항수"(학교 웹호스팅)도 잡고,
    # "요구사항 수행방안"·"요구사항 수준"처럼 `수` 뒤에 한글이 이어지는 말은 제외한다.
    "requirement_summary": [re.compile(r"요구\s*사항\s*수(?![가-힣])")],
    "evaluation_scores": [re.compile(r"배점"), re.compile(r"평가항목|평가부문|평가기준")],
    "staffing": [
        re.compile(r"인원|상주|투입"),
        re.compile(r"PM|프로그래머|디자이너|기술자|등급"),
    ],
    "commercial_sw": [re.compile(r"상용|솔루션"), re.compile(r"제조사|품명|제품명|도입")],
    "schedule": [re.compile(r"추진일정|M\+\d|개월차")],
}
LIST_MIN_ID_ROWS = 3  # tunable: ID가 든 행이 이만큼이면 목록표
DETAIL_MAX_ID_CELLS = 1  # 고유번호 값 셀·단독 ID 셀이 이보다 많으면 목록표로 재분류

# --- 요구사항 파서 A 라벨(공백 정규화한 셀 텍스트에 search). tunable ---
REQUIREMENT_LABELS: dict[str, re.Pattern[str]] = {
    "id": _DETAIL_ID_LABEL,
    "name": re.compile(r"요구사항\s*명칭|^명칭$"),
    "definition": re.compile(r"^정의$"),
    "details": re.compile(r"세부\s*내용|상세\s*내용|상세설명|세부내용"),
    "mandatory": re.compile(r"^(?:응락\s*수준|필수\s*여부)\s*:?$"),
}
LABEL_MAX_LEN = 20  # tunable: 이보다 긴 셀(본문 문장)은 라벨 단어가 있어도 라벨로 보지 않는다


@dataclass(frozen=True)
class _Cell:
    raw: str  # 원문 strip
    norm: str  # 공백 정규화(연속 공백·줄바꿈 → 공백 하나, strip)
    label: str | None  # REQUIREMENT_LABELS 키 또는 None


_Pos = tuple[int, int]


def _norm_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _label_of(norm: str) -> str | None:
    if not norm or len(norm) > LABEL_MAX_LEN:
        return None
    for key, pattern in REQUIREMENT_LABELS.items():
        if pattern.search(norm):
            return key
    return None


def _grid(rows: list[list[str]]) -> list[list[_Cell]]:
    out: list[list[_Cell]] = []
    for row in rows:
        cells = []
        for text in row:
            norm = _norm_ws(text)
            cells.append(_Cell(raw=text.strip(), norm=norm, label=_label_of(norm)))
        out.append(cells)
    return out


def _positions(grid: list[list[_Cell]]) -> list[_Pos]:
    """행 우선 순회 순서의 셀 좌표."""
    return [(r, c) for r, row in enumerate(grid) for c in range(len(row))]


def _value_pos(grid: list[list[_Cell]], r: int, c: int) -> _Pos | None:
    """라벨 (r, c)의 값 셀 좌표.

    같은 행 오른쪽 첫 비어 있지 않은 셀, 없으면 다음 행의 첫 비어 있지 않은 셀.
    그 셀이 다른 라벨이면 값이 없는 것으로 본다(라벨을 값으로 잘못 읽지 않도록).
    """
    for c2 in range(c + 1, len(grid[r])):
        cell = grid[r][c2]
        if cell.raw:
            if cell.label is None:
                return (r, c2)
            break  # 같은 행 오른쪽 첫 셀이 라벨 → 이 행에는 값이 없다
    if r + 1 < len(grid):
        for c2, cell in enumerate(grid[r + 1]):
            if cell.raw:
                return None if cell.label is not None else (r + 1, c2)
    return None


def _labels(grid: list[list[_Cell]], key: str) -> list[_Pos]:
    return [(r, c) for r, c in _positions(grid) if grid[r][c].label == key]


def _id_label_values(grid: list[list[_Cell]]) -> list[_Pos]:
    """라벨 `고유번호`의 값 셀 중 ID 정규식이 든 것(행 우선 순)."""
    out = []
    for r, c in _labels(grid, "id"):
        vp = _value_pos(grid, r, c)
        if vp is not None and _REQ_ID_RE.search(grid[vp[0]][vp[1]].raw):
            out.append(vp)
    return out


def _id_cell_count(grid: list[list[_Cell]]) -> int:
    """라벨 `고유번호` 값 셀 ∪ 단독 ID 셀(셀 전체가 ID) 수. 문장 속 참조 ID는 세지 않는다."""
    cells = set(_id_label_values(grid))
    cells.update((r, c) for r, c in _positions(grid) if _REQ_ID_FULL.match(grid[r][c].norm))
    return len(cells)


def _matches_all(patterns: list[re.Pattern[str]], texts: list[str]) -> bool:
    return all(any(p.search(t) for t in texts) for p in patterns)


def classify_table(rows: list[list[str]]) -> TableKind:
    """표 종류 태그. spec 순서대로 첫 매치(셀 텍스트는 공백 정규화 후 판정)."""
    grid = _grid(rows)
    norms = [cell.norm for row in grid for cell in row]
    has_id = any(_REQ_ID_RE.search(n) for n in norms)
    if has_id and _matches_all(TABLE_KEYWORDS["requirement_detail"], norms):
        if _id_cell_count(grid) > DETAIL_MAX_ID_CELLS:
            return "requirement_list"  # 파서 A의 목록형 재분류와 같은 규칙
        return "requirement_detail"
    if grid and _matches_all(TABLE_KEYWORDS["requirement_summary"], [c.norm for c in grid[0]]):
        return "requirement_summary"
    id_rows = sum(1 for row in grid if any(_REQ_ID_RE.search(c.norm) for c in row))
    if id_rows >= LIST_MIN_ID_ROWS:
        return "requirement_list"
    for kind in ("evaluation_scores", "staffing", "commercial_sw", "schedule"):
        if _matches_all(TABLE_KEYWORDS[kind], norms):
            return kind
    return "other"


def _mandatory(value: str | None) -> bool | None:
    if value is None:
        return None
    level = _squash(value)
    if level in {"필수", "필수사항"}:
        return True
    if level in {"선택", "선택사항"}:
        return False
    return None


def _parse_detail_table(
    table: RawTable, section_id: str | None
) -> tuple[Requirement, list[str]] | None:
    """상세표 하나 → Requirement(+경고). ID가 없으면 None."""
    grid = _grid(table.rows)
    order = _positions(grid)

    def first_value(key: str) -> tuple[_Pos | None, str | None]:
        for r, c in _labels(grid, key):
            vp = _value_pos(grid, r, c)
            if vp is not None:
                return vp, grid[vp[0]][vp[1]].raw
        return None, None

    # ID: 라벨 고유번호 값 우선, 아니면 표 전체 첫 매치
    req_id: str | None = None
    id_pos: _Pos | None = None
    label_ids = _id_label_values(grid)
    if label_ids:
        id_pos = label_ids[0]
        m = _REQ_ID_RE.search(grid[id_pos[0]][id_pos[1]].raw)
        req_id = m.group(0) if m else None
    else:
        for r, c in order:
            m = _REQ_ID_RE.search(grid[r][c].raw)
            if m:
                req_id = m.group(0)
                if _REQ_ID_FULL.match(grid[r][c].norm):
                    id_pos = (r, c)  # 단독 ID 셀만 details 폴백에서 제외한다
                break
    if req_id is None:
        return None

    warnings: list[str] = []
    name_pos, name = first_value("name")
    if not name:
        warnings.append(f"missing requirement name: {req_id}")
        name = req_id
    def_pos, definition = first_value("definition")
    mand_pos, mand_text = first_value("mandatory")

    detail_labels = _labels(grid, "details")
    if detail_labels:
        # 그룹 라벨("요구사항 상세설명") 아래 하위 라벨("세부 내용")이 있으면 하위 라벨이 기준
        start = order.index(detail_labels[-1]) + 1
        picked = [(r, c) for r, c in order[start:] if grid[r][c].label is None]
    else:
        excluded = {p for p in (id_pos, name_pos, def_pos, mand_pos) if p is not None}
        picked = [(r, c) for r, c in order if grid[r][c].label is None and (r, c) not in excluded]
    details = "\n".join(grid[r][c].raw for r, c in picked if grid[r][c].raw)

    req = Requirement(
        id=req_id[:7],
        instance_key=req_id if len(req_id) > 7 else None,
        category=req_id[:3],
        name=name,
        definition=definition or None,
        details=details,
        mandatory=_mandatory(mand_text),
        section_id=section_id,
        table_id=table.id,
        source="table",
    )
    return req, warnings


def parse_requirements_from_tables(
    tables: list[RawTable],
    kinds: dict[str, TableKind],
    block_section: Callable[[int], str | None],
) -> tuple[list[Requirement], list[str]]:
    """상세표마다 하나의 요구사항을 원문 순서로 보존한다."""
    requirements = []
    warnings: list[str] = []
    for table in tables:
        if kinds.get(table.id) != "requirement_detail":
            continue
        parsed = _parse_detail_table(table, block_section(table.block_idx))
        if parsed is None:
            continue
        req, req_warnings = parsed
        requirements.append(req)
        warnings.extend(req_warnings)
    return _identify_occurrences(requirements, warnings)


def _identify_occurrences(
    requirements: list[Requirement], warnings: list[str]
) -> tuple[list[Requirement], list[str]]:
    totals = Counter(req.source_id for req in requirements)
    seen = Counter()
    for req in requirements:
        source_id = req.source_id
        if totals[source_id] > 1:
            seen[source_id] += 1
            req.instance_key = f"{source_id}@{seen[source_id]}"
            if seen[source_id] > 1:
                warnings.append(f"duplicate requirement id: {source_id}")
    return requirements, warnings


# --- 요구사항 파서 B(spec "요구사항 파서 B"): paragraph Block을 줄 단위로 펼쳐 읽는다 ---
# 라벨 정규식은 현재 줄과 "현재 줄 + 공백 + 다음 줄"(pdf에서 라벨이 두 줄로 갈린 경우)에 적용한다.
_TEXT_ID_LABEL = re.compile(rf"요구사항\s*(고유)?\s*번호\s*({REQ_ID})")
_TEXT_ID_LINE = re.compile(rf"^({REQ_ID})$")
_TEXT_NAME = re.compile(r"^요구사항\s*명칭\s*(.+)")
_TEXT_DEFINITION = re.compile(r"^정의\s*(.+)")
_TEXT_DETAILS = re.compile(r"^세부\s*내용|^세부내용|^상세\s*내용|^상세설명")
_TEXT_DETAILS_END = re.compile(r"^요구사항\s*분류|^요구사항\s*고유")
# 세부내용 종료 줄(spec 파서 B "details 종료"):
# 소제목 줄(pdf에서 번호가 뒤로 밀린 "성능 요구사항2)", "제약사항8)")
_TEXT_SUBTITLE = re.compile(r"사항\s*\d{1,2}\s*[\)）]$")
# 목록표 행("기능 요구사항 SFR-002 반응형 …", "사항 PMR-001 …"): 분류명 끝말 바로 뒤 ID
_TEXT_LIST_ROW = re.compile(rf"(?:^|\s)(?:요구\s*사항|제약\s*사항|사항)\s+{REQ_ID}(?:\s|$)")
# 마지막 항목 전용: 상세표 영역 뒤 다음 부분의 시작(공백 제거 후 앞부분 비교)
_TEXT_TAIL_START = re.compile(r"^(?:요구사항총괄표|평가|붙임|서식|별지|별표|첨부)")
_TEXT_MANDATORY = re.compile(r"^(?:응락\s*수준|필수\s*여부)\s*:?\s*(.*)$")


@dataclass(frozen=True)
class _Line:
    block_idx: int
    text: str  # strip, 비어 있지 않음


def _text_lines(blocks: list[Block]) -> list[_Line]:
    """paragraph Block을 줄 단위로 펼친다(빈 줄 제외, 각 줄에 원 Block idx 유지)."""
    out: list[_Line] = []
    for b in blocks:
        if b.kind != "paragraph":
            continue
        for raw in b.text.splitlines():
            t = raw.strip()
            if t:
                out.append(_Line(b.idx, t))
    return out


def _match_lines(
    pattern: re.Pattern[str], lines: list[_Line], i: int, *, search: bool = False
) -> tuple[re.Match[str], int] | None:
    """i번째 줄에서, 안 되면 i번째+다음 줄 결합 문자열에서 매치. (매치, 소비한 줄 수).

    결합 매치는 현재 줄에서 시작해야 한다(다음 줄만으로 성립하는 매치는 다음 줄 차례에 본다).
    """
    cur = lines[i].text
    fn = pattern.search if search else pattern.match
    m = fn(cur)
    if m:
        return m, 1
    if i + 1 < len(lines):
        m = fn(f"{cur} {lines[i + 1].text}")
        if m and m.start() < len(cur):
            return m, 2
    return None


@dataclass
class _TextItem:
    req_id: str
    block_idx: int
    name: str | None = None
    definition: str | None = None
    mandatory: bool | None = None
    details: list[str] | None = None  # None: 세부내용 라벨 전, list: 라벨 이후
    closed: bool = False  # 세부내용이 끝난 뒤(다음 항목 시작 전까지 줄을 버린다)
    is_last: bool = False  # 문서의 마지막 항목(뒤따르는 본문에서 끝을 찾는 규칙을 더 쓴다)


def _start_id(lines: list[_Line], i: int) -> tuple[str, int] | None:
    """새 항목 시작 줄이면 (ID, 소비한 줄 수)."""
    hit = _match_lines(_TEXT_ID_LABEL, lines, i, search=True)
    if hit is not None:
        return hit[0].group(2), hit[1]
    m = _TEXT_ID_LINE.match(lines[i].text)
    if m:
        return m.group(1), 1
    return None


def _details_end(text: str, is_last: bool) -> bool:
    """세부내용을 끝내는 줄인가(그 줄은 details에 넣지 않는다).

    모든 항목: `요구사항 분류`·`요구사항 고유` 줄, 소제목 줄(`…사항N)`로 끝나거나 헤딩 패턴
    level 1~4), 목록표 행(`… 요구사항 <ID> …`). 마지막 항목은 추가로 `요구사항 총괄표`·`평가`·
    `붙임`·`서식`·`별지`·`별표`·`첨부`로 시작하는 줄(공백 제거 후)에서도 끝난다.
    """
    if _TEXT_DETAILS_END.match(text) or _TEXT_SUBTITLE.search(text):
        return True
    if _TEXT_LIST_ROW.search(text) or classify_heading(text) is not None:
        return True
    return is_last and bool(_TEXT_TAIL_START.match(_squash(text)))


def _feed_line(item: _TextItem, lines: list[_Line], i: int) -> int:
    """항목 하나에 i번째 줄을 반영하고 소비한 줄 수를 돌려준다."""
    text = lines[i].text
    mandatory = _TEXT_MANDATORY.match(text)
    if item.details is not None:
        if _details_end(text, item.is_last):
            item.closed = True
            return 1
        if item.mandatory is None and mandatory:
            item.mandatory = _mandatory(mandatory[1])
        item.details.append(text)
        return 1
    if item.mandatory is None and mandatory:
        item.mandatory = _mandatory(mandatory[1])
        return 1
    hit = _match_lines(_TEXT_DETAILS, lines, i)
    if hit is not None:
        m, used = hit
        joined = text if used == 1 else f"{text} {lines[i + 1].text}"
        rest = joined[m.end() :].strip()
        item.details = [rest] if rest else []
        return used
    if item.name is None:
        hit = _match_lines(_TEXT_NAME, lines, i)
        if hit is not None:
            item.name = hit[0].group(1).strip()
            return hit[1]
    if item.definition is None:
        hit = _match_lines(_TEXT_DEFINITION, lines, i)
        if hit is not None:
            item.definition = hit[0].group(1).strip()
            return hit[1]
    return 1  # 세부내용 라벨 전의 그 밖의 줄은 버린다


def _scan_items(lines: list[_Line], last: int | None) -> list[_TextItem]:
    """줄을 순서대로 읽어 항목을 만든다. `last`번째(0부터) 항목은 마지막 항목 규칙을 쓴다."""
    items: list[_TextItem] = []
    current: _TextItem | None = None
    i = 0
    while i < len(lines):
        start = _start_id(lines, i)
        if start is not None:
            current = _TextItem(
                req_id=start[0], block_idx=lines[i].block_idx, is_last=len(items) == last
            )
            items.append(current)
            i += start[1]
            continue
        if current is None or current.closed:
            i += 1
            continue
        i += _feed_line(current, lines, i)
    return items


def parse_requirements_from_text(
    blocks: list[Block], block_section: Callable[[int], str | None]
) -> tuple[list[Requirement], list[str]]:
    """요구사항 파서 B(줄 기반). 원문 순서와 중복 항목을 보존한다.

    paragraph Block의 텍스트를 줄 단위로 펼쳐(원 Block idx 유지) 읽는다. `요구사항 (고유) 번호
    <ID>` 또는 단독 ID 줄이 새 항목을 시작한다. 세부내용 라벨 이후 줄이 details이고
    다음 항목 시작 또는 `_details_end` 줄에서 끝난다. 라벨은 연속 두 줄을 합친 문자열에도
    매치한다(합쳐서 매치하면 두 줄 모두 소비).
    """
    lines = _text_lines(blocks)
    items = _scan_items(lines, last=None)
    if items:
        # 마지막 항목을 알아야 그 항목에만 꼬리 종료 규칙을 쓸 수 있으므로 한 번 더 읽는다.
        items = _scan_items(lines, last=len(items) - 1)

    requirements = []
    warnings: list[str] = []
    for item in items:
        details = "\n".join(item.details or [])
        name = item.name
        if not name:
            warnings.append(f"missing requirement name: {item.req_id}")
            name = item.req_id
        requirements.append(
            Requirement(
                id=item.req_id[:7],
                instance_key=item.req_id if len(item.req_id) > 7 else None,
                category=item.req_id[:3],
                name=name,
                definition=item.definition or None,
                details=details,
                mandatory=item.mandatory,
                section_id=block_section(item.block_idx),
                table_id=None,
                source="text",
            )
        )
    return _identify_occurrences(requirements, warnings)


# --- 기대 수와 교차검증(spec "기대 수와 교차검증") ---
_TOTAL_LABEL = re.compile(r"합\s*계|^계$")
_NUMBER_CELL = re.compile(r"^\d{1,4}$")
_TEXT_SUMMARY_TRIGGER = re.compile(r"요구사항\s*총괄표|요구사항\s*수")
_TEXT_TOTAL_LINE = re.compile(r"^합\s*계\s+(\d{1,3})\s*$")
_TEXT_TOTAL_INLINE = re.compile(r"합\s*계\s+(\d{1,3})\b")
EXPECTED_TEXT_WINDOW = 40  # tunable: 트리거 줄과 그 뒤 이만큼의 줄에서 합계를 찾는다


def _number_cell(text: str) -> int | None:
    t = _WS.sub("", text).replace(",", "")
    return int(t) if _NUMBER_CELL.match(t) else None


def _last_number(row: list[str]) -> int | None:
    for cell in reversed(row):
        n = _number_cell(cell)
        if n is not None:
            return n
    return None


def _summary_count(rows: list[list[str]]) -> int | None:
    """총괄표 하나의 기대 수: 합계 행의 마지막 숫자 셀, 없으면 각 행 마지막 숫자 셀 합."""
    body = rows[1:]  # 헤더 행 제외
    for row in body:
        if row and _TOTAL_LABEL.search(_norm_ws(row[0])):
            n = _last_number(row)
            if n is not None:
                return n
    nums = [n for n in (_last_number(r) for r in body) if n is not None]
    return sum(nums) if nums else None


def _text_expected(blocks: list[Block]) -> int | None:
    lines = _text_lines(blocks)
    for i, line in enumerate(lines):
        if not _TEXT_SUMMARY_TRIGGER.search(line.text):
            continue
        for cand in lines[i : i + EXPECTED_TEXT_WINDOW + 1]:
            m = _TEXT_TOTAL_LINE.match(cand.text) or _TEXT_TOTAL_INLINE.search(cand.text)
            if m:
                return int(m.group(1))
    return None


def expected_requirement_count(
    tables: list[RawTable], kinds: dict[str, TableKind], blocks: list[Block]
) -> int | None:
    """요구사항 기대 수. (1) 총괄표(표 순서상 첫 값), (2) 표가 없으면 텍스트 규칙, (3) None.

    텍스트 규칙은 paragraph Block을 줄 단위로 펼친 뒤, `요구사항 총괄표|요구사항 수`를 포함한
    줄부터 그 뒤 EXPECTED_TEXT_WINDOW 줄 안에서 `합계 <n>` 첫 매치를 쓴다(pdf Block은 페이지
    덩어리라 Block 단위 창은 사실상 문서 전체가 되므로 줄 단위로 센다).
    """
    summaries = [t for t in tables if kinds.get(t.id) == "requirement_summary"]
    enumerated: list[list[str]] = []
    for table in summaries:
        if not table.rows or "ID" not in table.rows[0]:
            break
        col = table.rows[0].index("ID")
        ids = [row[col].strip() for row in table.rows[1:] if len(row) > col and row[col].strip()]
        reported = _summary_count(table.rows)
        if (
            not ids
            or not all(_REQ_ID_FULL.fullmatch(i) for i in ids)
            or reported not in (None, len(ids))
        ):
            break
        enumerated.append(ids)
    if summaries and len(enumerated) == len(summaries):
        if len(summaries) > 1:
            # Summaries can repeat the same list. Count across them only if each
            # occurrence is independently corroborated by a detail table.
            detail_ids = []
            for table in tables:
                if kinds.get(table.id) == "requirement_detail":
                    parsed = _parse_detail_table(table, None)
                    if parsed is not None:
                        detail_ids.append(parsed[0].source_id)
            if Counter(i for group in enumerated for i in group) != Counter(detail_ids):
                return None
        return sum(map(len, enumerated))
    for table in tables:
        if kinds.get(table.id) == "requirement_summary":
            n = _summary_count(table.rows)
            if n is not None:
                return n
    if tables:
        return None
    return _text_expected(blocks)


@dataclass(frozen=True)
class RequirementSelection:
    requirements: list[Requirement]
    expected: int | None
    warnings: list[str]  # 파서 경고 → 수 불일치 → listed but no detail → 0건 순

    @property
    def found(self) -> int:
        return len({r.source_id for r in self.requirements})


def _listed_ids(tables: list[RawTable], kinds: dict[str, TableKind]) -> list[str]:
    """`requirement_list` 표 셀의 ID(표 순·행 우선, 중복 제거)."""
    out: list[str] = []
    for table in tables:
        if kinds.get(table.id) != "requirement_list":
            continue
        for row in table.rows:
            for cell in row:
                for m in _REQ_ID_RE.finditer(cell):
                    if m.group(0) not in out:
                        out.append(m.group(0))
    return out


def select_requirements(
    raw: RawDoc, kinds: dict[str, TableKind], block_section: Callable[[int], str | None]
) -> RequirementSelection:
    """primary RawDoc의 요구사항을 고르고 기대 수와 교차검증한다.

    표가 있으면 파서 A, 표가 없거나 A가 0건이면 파서 B. 상세 항목 수가 expected와 다르면
    `"requirements found X != expected Y"`, 목록표 ID 중 found에 없는 것은
    `"listed but no detail: <ID>"`, 0건이면 `"no requirements parsed"`.
    """
    reqs: list[Requirement] = []
    warnings: list[str] = []
    if raw.tables:
        reqs, warnings = parse_requirements_from_tables(raw.tables, kinds, block_section)
    if not reqs:
        reqs, warnings = parse_requirements_from_text(raw.blocks, block_section)

    expected = expected_requirement_count(raw.tables, kinds, raw.blocks)
    found_ids = {r.source_id for r in reqs}
    if expected is not None and len(reqs) != expected:
        warnings.append(f"requirements found {len(reqs)} != expected {expected}")
    warnings.extend(
        f"listed but no detail: {rid}"
        for rid in _listed_ids(raw.tables, kinds)
        if rid not in found_ids
    )
    if not reqs:
        warnings.append("no requirements parsed")
    return RequirementSelection(requirements=reqs, expected=expected, warnings=warnings)


# --- 페이지 대응(spec "페이지 대응") ---
PAGE_PREFIX_LEN = (
    20  # tunable: 헤딩(번호 표지 제거) 공백 제거 앞 N자를 pdf 페이지 텍스트에서 찾는다
)
_TRAILING_PAGE_NO = re.compile(r"\s+\d{1,3}$")


def page_prefix(heading: str) -> str:
    """페이지 대응 접두: 번호 표지·끝 쪽번호를 떼고 공백을 지운 앞 PAGE_PREFIX_LEN자.

    pdf 텍스트에서는 번호("2.", "Ⅳ.")가 본문과 떨어져 다른 위치에 찍히므로 번호를 빼고
    찾는다. 표지만 있는 헤딩("붙임 2")은 빈 문자열이며 매핑하지 않는다.
    """
    rest = _TRAILING_PAGE_NO.sub("", strip_heading_mark(heading))
    return _squash(rest)[:PAGE_PREFIX_LEN]


def _searchable_page(page_text: str) -> str:
    """pdf 페이지 텍스트에서 목차 리더 줄(공백 제거 후 `·`/`…` TOC_REPEAT개 이상)을 빼고 공백 제거.

    목차 쪽에도 같은 헤딩 문구가 있으므로, 리더 줄을 빼야 본문 헤딩이 본문 쪽에 매핑된다.
    """
    kept = [line for line in page_text.splitlines() if not _TOC_LEADER.search(_squash(line))]
    return _squash("\n".join(kept))


def _pages_from_blocks(sections: list[Section], blocks: list[Block]) -> list[Section]:
    """pdf가 primary일 때: 섹션 범위 안 Block.page의 최소/최대."""
    page_of = {b.idx: b.page for b in blocks if b.page is not None}
    out: list[Section] = []
    for sec in sections:
        pages = [page_of[i] for i in range(sec.block_start, sec.block_end + 1) if i in page_of]
        if pages:
            sec = sec.model_copy(update={"page_start": min(pages), "page_end": max(pages)})
        out.append(sec)
    return out


def map_pages(
    sections: list[Section], primary: RawDoc, reference_pdf: RawDoc | None
) -> list[Section]:
    """섹션에 page_start/page_end를 채운 새 목록을 돌려준다(입력은 바꾸지 않는다).

    - primary가 pdf면 Block.page에서 직접 가져온다.
    - 그 밖에는 reference_pdf.page_texts(목차 리더 줄 제외)에서 헤딩 접두(`page_prefix`: 번호
      표지·끝 쪽번호 제거, 공백 제거, `PAGE_PREFIX_LEN`자)를 찾는다. 접두가 비면 매핑하지 않는다.
      검색은 직전에 매핑된 섹션의 page_start부터(없으면 1쪽부터)이므로 쪽 번호가 문서 순으로
      줄어들지 않는다. 못 찾으면 둘 다 None이고 검색 시작 쪽도 그대로 둔다.
    - page_end = 뒤따르는 섹션 중 처음 매핑된 섹션의 page_start - 1(같은 쪽이면 page_start),
      뒤에 매핑된 섹션이 없으면 총 페이지.
    - 헤딩이 없는 전문(S000)은 매칭할 헤딩이 없어 None으로 둔다(pdf primary는 Block.page 사용).
    """
    if primary.format == "pdf":
        return _pages_from_blocks(sections, primary.blocks)
    if reference_pdf is None or not reference_pdf.page_texts:
        return list(sections)

    pages = [_searchable_page(t) for t in reference_pdf.page_texts]
    total = len(pages)
    starts: list[int | None] = []
    cursor = 1
    for sec in sections:
        found: int | None = None
        if sec.level > 0:
            prefix = page_prefix(sec.heading)
            if prefix:
                for page_no in range(cursor, total + 1):
                    if prefix in pages[page_no - 1]:
                        found = page_no
                        break
        starts.append(found)
        if found is not None:
            cursor = found

    ends: list[int | None] = [None] * len(sections)
    next_mapped: int | None = None
    for i in range(len(sections) - 1, -1, -1):
        start = starts[i]
        if start is None:
            continue
        ends[i] = total if next_mapped is None else max(start, next_mapped - 1)
        next_mapped = start

    out: list[Section] = []
    for sec, start, end in zip(sections, starts, ends, strict=True):
        if start is None:
            out.append(sec)
        else:
            out.append(sec.model_copy(update={"page_start": start, "page_end": end}))
    return out


# --- 경고 결합 ---
def merge_warnings(*groups: Iterable[str]) -> list[str]:
    """경고 목록을 주어진 순서대로 이어 붙이고 처음 나온 것만 남긴다(순서 유지)."""
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for w in group:
            if w not in seen:
                seen.add(w)
                out.append(w)
    return out


# --- 전체 조립 ---
def _section_lookup(sections: list[Section]) -> Callable[[int], str | None]:
    """Block idx → 섹션 id. 범위가 평면·빈틈 없음이므로 이진 탐색으로 찾는다.

    마지막 섹션 뒤의 idx(위치 미상으로 문서 끝에 둔 표 등)는 마지막 섹션으로 귀속한다.
    """
    starts = [s.block_start for s in sections]

    def lookup(block_idx: int) -> str | None:
        if not sections:
            return None
        pos = bisect_right(starts, block_idx) - 1
        return sections[max(pos, 0)].id

    return lookup


def render_full_text(blocks: list[Block], sections: list[Section], tables: list[Table]) -> str:
    """Block 순서대로 paragraph는 텍스트, table은 Table.markdown을 "\\n"으로 결합한다.

    헤딩 블록(전문이 아닌 섹션의 block_start)은 `#`×level + 공백 + 헤딩이다. 쪼개진 헤딩의
    나머지 Block("Ⅰ" 다음 "사업 개요")은 헤딩 줄에 이미 들어 있으므로 다시 쓰지 않는다.
    """
    heading_at = {s.block_start: s for s in sections if s.level > 0}
    merged = {blocks[k].idx for h in _detect_heads(blocks) for k in range(h.pos + 1, h.last + 1)}
    markdown_of = {t.id: t.markdown for t in tables}
    lines: list[str] = []
    for b in blocks:
        if b.kind == "table":
            lines.append(markdown_of.get(b.table_id or "", b.text))
            continue
        if b.idx in merged:
            continue
        sec = heading_at.get(b.idx)
        lines.append(f"{'#' * sec.level} {sec.heading}" if sec else b.text)
    return "\n".join(lines)


def build(bundle: NoticeBundle, primary: RawDoc, reference_pdf: RawDoc | None) -> RfpDocument:
    """primary RawDoc(과 있으면 참고 pdf)을 RfpDocument로 정규화한다.

    섹션 범위 불변식이 깨지면 ValueError. primary가 pdf면 reference_pdf는 쓰지 않는다.
    """
    if primary.format == "pdf":
        reference_pdf = None
    tables_by_id = {t.id: t for t in primary.tables}
    sections = build_sections(primary.blocks, tables_by_id)
    _check_ranges(sections, len(primary.blocks))
    sections = map_pages(sections, primary, reference_pdf)
    lookup = _section_lookup(sections)

    kinds: dict[str, TableKind] = {t.id: classify_table(t.rows) for t in primary.tables}
    tables = [
        Table(
            id=t.id,
            section_id=lookup(t.block_idx) or PREAMBLE_ID,
            kind=kinds[t.id],
            rows=t.rows,
            markdown=render_table_markdown(t.rows),
        )
        for t in primary.tables
    ]
    selection = select_requirements(primary, kinds, lookup)

    ref_meta = reference_pdf.meta if reference_pdf is not None else None
    quality = SourceQuality(
        primary_format=primary.format,
        primary_chars=primary.meta.chars,
        primary_digits=primary.meta.digits,
        reference_pdf_chars=ref_meta.chars if ref_meta else None,
        reference_pdf_digits=ref_meta.digits if ref_meta else None,
        has_tables=len(primary.tables) > 0,
        requirements_found=selection.found,
        requirements_expected=selection.expected,
        sections_mapped_to_pages=sum(1 for s in sections if s.page_start is not None),
        warnings=merge_warnings(
            bundle.warnings,
            primary.meta.warnings,
            ref_meta.warnings if ref_meta else [],
            selection.warnings,
        ),
    )
    blocks = _with_table_ids(primary.blocks, tables_by_id)
    return RfpDocument(
        slug=bundle.slug,
        title=bundle.title,
        source_files=[f.path for f in bundle.files],
        primary_format=bundle.primary_format,
        sections=sections,
        requirements=selection.requirements,
        tables=tables,
        full_text=render_full_text(blocks, sections, tables),
        source_quality=quality,
    )


def _with_table_ids(blocks: list[Block], tables_by_id: dict[str, RawTable]) -> list[Block]:
    """table_id가 비어 있는 table Block을 RawTable.block_idx로 보완한 목록."""
    table_at: dict[int, str] = {}
    for tid in sorted(tables_by_id):
        table_at.setdefault(tables_by_id[tid].block_idx, tid)
    return [
        b.model_copy(update={"table_id": table_at[b.idx]})
        if b.kind == "table" and b.table_id is None and b.idx in table_at
        else b
        for b in blocks
    ]


# --- rfp.md ---
def _pages_label(sec: Section) -> str:
    if sec.page_start is None:
        return "p.-"
    if sec.page_end is None or sec.page_end == sec.page_start:
        return f"p.{sec.page_start}"
    return f"p.{sec.page_start}-{sec.page_end}"


def render_rfp_md(doc: RfpDocument) -> str:
    """사람이 읽는 rfp.md. 결정적이다.

    섹션 헤딩은 문서 제목(`#`) 아래 `#`×(level+1)이고 전문(level 0)은 level 1과 같은 `##`이다.
    섹션 본문은 단락 뒤에 그 섹션의 표를 둔다(RfpDocument에는 Block 순서가 없다).
    """
    q = doc.source_quality
    expected = "-" if q.requirements_expected is None else str(q.requirements_expected)
    warnings = "; ".join(q.warnings) if q.warnings else "-"
    lines = [
        f"# {doc.title}",
        f"- slug: {doc.slug}",
        f"- primary_format: {doc.primary_format} / source_files: {', '.join(doc.source_files)}",
        f"- chars: {q.primary_chars} / digits: {q.primary_digits}",
        f"- requirements: {q.requirements_found} / expected: {expected}",
        f"- warnings: {warnings}",
        "",
        f"## 요구사항 ({len(doc.requirements)}건)",
        "| ID | 분류 | 명칭 | 필수 | 섹션 |",
        "|---|---|---|---|---|",
    ]
    mandatory_label = {True: "필수", False: "선택", None: "-"}
    for r in doc.requirements:
        cells = [r.source_id, r.category, r.name, mandatory_label[r.mandatory], r.section_id or "-"]
        lines.append("| " + " | ".join(_md_cell(c) for c in cells) + " |")
    lines += ["", "---"]

    table_by_id = {t.id: t for t in doc.tables}
    for sec in doc.sections:
        lines += [
            "",
            f"{'#' * (max(sec.level, 1) + 1)} {sec.heading}  "
            f"<!-- {sec.id} kind={sec.kind} {_pages_label(sec)} -->",
        ]
        if sec.text:
            lines += ["", sec.text]
        for tid in sec.table_ids:
            table = table_by_id.get(tid)
            if table is None:
                continue
            lines += ["", f"<!-- {tid} -->", table.markdown]
    return "\n".join(lines) + "\n"
