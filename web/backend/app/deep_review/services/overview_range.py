"""개요 입력 범위 선택과 그 순수 helper (결정적 규칙만).

DB·객체 저장소·모델을 건드리지 않는다. 쪽 텍스트 payload 하나를 받아 개요·목적
·범위에 해당하는 연속 구간을 고르고, 고르지 못하면 사람 확인 manifest를 만든다.
사람이 확정한 쪽 범위를 같은 manifest 모양으로 동결하는 것도 여기다.

heading 문자열 정규화(`_normalise_heading_text`·`_meaningful_heading`)도 여기 있다.
문서 segment 계산이 같은 규칙을 두 벌 만들지 않도록 한 곳에 둔다.

함수 이름의 `v4`는 옛 세대 이름이며 P2에서 정리한다.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


V4_MANIFEST_SCHEMA = "bidops.prespec-v4-input-manifest.v1"
V4_RANGE_REVIEW_SCHEMA = "bidops.prespec-v4-range-review.v1"
MAX_V4_MANIFEST_BYTES = 8 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHAPTER = re.compile(r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+)\s*[.)、:：\-–—]?\s*(.+)$")
#: 같은 장 표식의 다른 표기. 조판기가 로마숫자를 ASCII로 떨어뜨리기도 하고
#: (0916 공고 780) `제3장` 표기를 쓰는 문서도 있다. ASCII 표기는 `IT 장비`
#: 같은 본문 줄을 장으로 오인할 수 있으므로 구분 기호나 공백을 요구한다.
_CHAPTER_ASCII = re.compile(r"^([IVX]{1,4})(?:\s*[.)、:：\-–—]\s*|\s+)(.+)$")
_CHAPTER_KO = re.compile(r"^(제\s*\d{1,2}\s*장)\s*[.)、:：\-–—]?\s*(.+)$")
#: 장 표식만 있고 제목이 다음 줄로 갈라진 줄 (0916 공고 781·805의 `Ⅰ` 줄).
_CHAPTER_MARKER_ONLY = re.compile(
    r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]{1,4}|제\s*\d{1,2}\s*장)\s*[.)、:：\-–—]?$"
)
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\s*[.)、:：\-–—]?\s+(.+)$")
_BULLET = re.compile(r"^[□■◆◇○●〇◦•·]\s*")
#: The only manifest fields a human confirmation may add (ADR-RDP-004).
_V4_SPAN_EXTRA_FIELDS = frozenset({"confirmed_from_target_id", "confirmed_by", "note", "candidate_indices"})
#: 목차 표제. 장식 기호(`- 목  차 -`, `<목차>`, `[ 차례 ]`)를 걷어낸 뒤 본다.
_TOC_TRIM = re.compile(r"[-<>\[\]():\s]+")
_TOC_WORDS = frozenset({"목차", "차례", "contents", "tableofcontents"})
#: 목차 항목 줄: 탭이나 점선 뒤에 쪽 번호로 끝난다.
_TOC_ENTRY = re.compile(r"(?:\t\d{1,4}|[.·…]{2,}\s*\d{1,4})\s*$")
_TOC_ENTRY_LINES = 5
#: 같은 항목을 제목과 인쇄 쪽번호로 갈라 읽는다. 탭·점선 외에 공백 연속으로
#: 자리를 맞춘 목차도 있다 (ADR-0057 결정 2).
_TOC_ENTRY_LINE = re.compile(
    r"^\s*(?P<title>\S.*?)(?:\t+\s*|\s*[.·…]{2,}\s*|\s{2,})(?P<page>\d{1,3})\s*$"
)
#: 목차를 찾는 앞쪽 범위와 한 쪽을 목차로 보는 항목 수 하한.
_TOC_SCAN_PAGES = 5
_TOC_MIN_ENTRIES = 4
_TARGET_WORDS = frozenset(
    {
        "개요", "목적", "배경", "범위", "주요내용", "주요과업", "사업일반",
        "사업개요", "감리개요", "감리목적", "감리대상사업", "감리방법",
        "감리과업내용", "과업개요", "과업안내", "과업내용", "추진근거", "추진계획",
    }
)
#: 제안사가 쓰는 양식 안내 장. 이 헤딩 뒤의 장은 발주처의 사업 범위가 아니라
#: 제안서 작성 양식이므로 본문 전략의 후보에서 뺀다 (0916 공고 805의 70쪽
#: `제안서 목차` 양식이 첫 장으로 잡혔다).
_FORM_CHAPTER_WORDS = (
    "제안서작성안내", "제안서작성요령", "제안서작성방법", "제안서목차", "세부작성지침",
)

MAX_V4_PROVENANCE_BYTES = 128 * 1024


class V4PreparationError(ValueError):
    """Stable failure at the v4 preparation/storage boundary."""

    def __init__(self, code: str, message: str = "v4 입력을 준비할 수 없습니다") -> None:
        self.code = code
        super().__init__(message)


class V4OpsError(RuntimeError):
    """범위 확정 경계의 안정 실패 코드. 예외 본문은 밖으로 내보내지 않는다."""

    def __init__(self, code: str) -> None:
        self.code = str(code or "v4_ops_failed")[:64]
        super().__init__(self.code)


@dataclass(frozen=True)
class V4RangeSelection:
    status: str
    reason_code: str | None
    strategy: str | None
    start_locator: dict[str, Any] | None
    end_locator: dict[str, Any] | None
    page_numbers: tuple[int, ...]
    page_text_hashes: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]
    manifest_bytes: bytes
    input_sha256: str
    #: 이 선택을 만들기 **전에** 목차 전략이 실패한 사유. 성공한 선택의 사유가
    #: 아니므로 manifest에도 넣지 않고, 최종 결과가 fallback·사람 검토일 때만
    #: 호출부가 `range_reason_codes` 끝에 덧붙인다 (ADR-0057 결정 2).
    toc_reason_code: str | None = None


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise V4PreparationError("invalid_json") from error


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical(value))


def _bounded_object(value: Any, *, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise V4PreparationError(code)
    try:
        encoded = _canonical(dict(value))
    except V4PreparationError:
        raise V4PreparationError(code) from None
    if len(encoded) > MAX_V4_PROVENANCE_BYTES:
        raise V4PreparationError("provenance_size_limit")
    return json.loads(encoded.decode("utf-8"))


@dataclass(frozen=True)
class _Line:
    page: int
    block_key: str
    line_index: int
    char_start: int
    char_end: int
    text: str
    level: int | None
    heading_title: str | None
    chapter: bool


def _normalise_heading(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    text = re.sub(r"\s+", "", text).casefold()
    text = _BULLET.sub("", text)
    text = re.sub(r"^[\(\[\{<「『【〔〈《]+", "", text)
    text = re.sub(r"[\)\]\}>」』】〕〉》]+$", "", text)
    return text.strip(" .·…\t")


def _toc_label(text: str) -> bool:
    value = _TOC_TRIM.sub("", unicodedata.normalize("NFKC", text)).casefold()
    return value in _TOC_WORDS or _normalise_heading(text) in _TOC_WORDS


def _heading_from_line(text: str) -> tuple[int | None, str | None, bool]:
    # NFKC turns the Unicode Roman numerals used by the source (Ⅰ/Ⅱ/…) into
    # ASCII I/II.  Match the chapter marker before normalising; otherwise the
    # parent chapter disappears from every locator and range boundary.
    stripped = text.strip()
    chapter = _CHAPTER.match(stripped) or _CHAPTER_KO.match(stripped)
    if chapter:
        title = chapter.group(2).strip()
        return 1, title, bool(_normalise_heading(title))
    ascii_chapter = _CHAPTER_ASCII.match(stripped)
    if ascii_chapter:
        title = ascii_chapter.group(2).strip()
        # ASCII 표기는 오인 여지가 크므로 제목이 실제 제목일 때만 장으로 본다.
        if _meaningful_heading(title):
            return 1, title, True
    numbered = _NUMBERED.match(stripped)
    if numbered:
        title = numbered.group(2).strip()
        return 2, title, False
    return None, None, False


def _structure_pages(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise V4PreparationError("invalid_structure")
    raw_pages = payload.get("pages")
    raw_blocks = payload.get("blocks")
    if not isinstance(raw_pages, list) or not raw_pages or not isinstance(raw_blocks, list):
        raise V4PreparationError("invalid_structure")
    blocks_by_page: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for raw in raw_blocks:
        if not isinstance(raw, Mapping):
            raise V4PreparationError("invalid_structure")
        page = raw.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise V4PreparationError("invalid_structure")
        blocks_by_page[page].append(raw)
    pages: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw_page in raw_pages:
        if not isinstance(raw_page, Mapping):
            raise V4PreparationError("invalid_structure")
        number = raw_page.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1 or number in seen:
            raise V4PreparationError("invalid_structure")
        seen.add(number)
        text = raw_page.get("text")
        if not isinstance(text, str):
            chunks: list[str] = []
            for block in blocks_by_page.get(number, []):
                value = block.get("text")
                if isinstance(value, str):
                    chunks.append(value)
            text = "\n".join(chunks)
        if not isinstance(text, str):
            raise V4PreparationError("invalid_structure")
        blocks = blocks_by_page.get(number, [])
        block_keys = [str(block.get("block_key")) for block in blocks if isinstance(block.get("block_key"), str) and str(block.get("block_key")).strip()]
        pages.append({"number": number, "text": text, "block_keys": block_keys})
    pages.sort(key=lambda item: item["number"])
    if [item["number"] for item in pages] != list(range(1, len(pages) + 1)):
        raise V4PreparationError("invalid_structure")
    return pages


def _lines(pages: Sequence[Mapping[str, Any]]) -> list[_Line]:
    output: list[_Line] = []
    for page in pages:
        page_number = int(page["number"])
        page_text = str(page["text"])
        block_key = (page.get("block_keys") or [f"page-{page_number}-text"])[0]
        offset = 0
        texts = page_text.splitlines() or [page_text]
        for line_index, text in enumerate(texts):
            char_start = offset
            char_end = char_start + len(text)
            level, title, chapter = _heading_from_line(text)
            if level is None and _CHAPTER_MARKER_ONLY.match(text.strip()):
                # 장 표식과 제목이 두 줄로 갈라진 조판. 같은 쪽의 다음 비공백
                # 줄까지가 하나의 장 heading이며, 장은 표식 줄에서 시작한다.
                follower = next((item for item in texts[line_index + 1:] if item.strip()), "")
                if follower:
                    level, title, chapter = _heading_from_line(f"{text.strip()} {follower.strip()}")
            output.append(_Line(page_number, block_key, line_index, char_start, char_end, text, level, title, chapter))
            offset = char_end + 1
    return output


def _has_target_word(title: str | None) -> bool:
    if not title:
        return False
    normalized = _normalise_heading(title)
    return any(word in normalized for word in _TARGET_WORDS)


def _is_target_heading(line: _Line) -> bool:
    return _has_target_word(line.heading_title)


@dataclass(frozen=True)
class _TocEntry:
    """목차 한 항목. `printed_page`는 목차가 적어 둔 **인쇄** 쪽번호다."""

    level: int | None
    title: str
    printed_page: int | None


def _toc_entry_pages(pages: Sequence[Mapping[str, Any]]) -> set[int]:
    """앞 `_TOC_SCAN_PAGES`쪽 중 "제목 … 쪽번호" 항목이 하한 이상인 쪽."""

    found: set[int] = set()
    for page in pages[:_TOC_SCAN_PAGES]:
        count = sum(1 for text in str(page["text"]).splitlines() if _TOC_ENTRY_LINE.match(text))
        if count >= _TOC_MIN_ENTRIES:
            found.add(int(page["number"]))
    return found


def _toc_entries(pages: Sequence[Mapping[str, Any]], entry_pages: set[int]) -> list[_TocEntry]:
    """목차 쪽을 (level, 제목, 인쇄 쪽번호) 항목 목록으로 읽는다.

    쪽번호가 없는 줄은 장 표식(로마숫자·`제N장`)이 있을 때만 항목으로 본다.
    안내 문구를 목차 항목으로 승격시키지 않기 위해서다 (0916 공고 805는 장
    줄에 쪽번호가 없고 하위 절에만 있다).
    """

    entries: list[_TocEntry] = []
    for page in pages:
        if int(page["number"]) not in entry_pages:
            continue
        for text in str(page["text"]).splitlines():
            match = _TOC_ENTRY_LINE.match(text)
            title_raw = (match.group("title") if match else text).strip()
            if not title_raw:
                continue
            printed = int(match.group("page")) if match else None
            level, title, _chapter = _heading_from_line(title_raw)
            if printed is None and level != 1:
                continue
            entries.append(_TocEntry(level, (title or title_raw).strip(), printed))
    return entries


def _toc_chapters(entries: Sequence[_TocEntry]) -> list[tuple[int, _TocEntry, int | None]]:
    """장 항목과 그 인쇄 쪽. 쪽이 없는 장은 자기 첫 하위 항목의 쪽을 쓴다."""

    chapters: list[tuple[int, _TocEntry, int | None]] = []
    for index, entry in enumerate(entries):
        if entry.level != 1:
            continue
        printed = entry.printed_page
        if printed is None:
            for follower in entries[index + 1:]:
                if follower.level == 1:
                    break
                if follower.printed_page is not None:
                    printed = follower.printed_page
                    break
        chapters.append((index, entry, printed))
    return chapters


def _toc_offset(
    chapters: Sequence[tuple[int, _TocEntry, int | None]],
    body_headings: Mapping[str, Sequence[_Line]],
) -> int | None:
    """인쇄 쪽 → 물리 쪽 offset. 두 장 이상이 같은 값을 낼 때만 확정한다."""

    offsets = [
        {line.page - printed for line in body_headings.get(_normalise_heading(entry.title), [])}
        if printed is not None else set()
        for _index, entry, printed in chapters
    ]
    if not offsets or not offsets[0]:
        return None
    support = {offset: sum(1 for item in offsets if offset in item) for offset in offsets[0]}
    best = max(support.values())
    winners = [offset for offset, count in support.items() if count == best]
    if best < 2 or len(winners) != 1:
        return None
    return winners[0]


def _carry_first_work_section(
    entries: Sequence[_TocEntry], end_index: int, end_entry: _TocEntry, end_printed: int | None,
) -> tuple[str, int | None]:
    """끝 장이 `과업 내용`이면 그 장의 첫 절까지 범위에 넣는다.

    본문 전략의 같은 예외를 목차 항목으로 옮긴 것이다. 끝은 여전히 배타이므로
    **둘째** 절이 새 끝이 되고, 절이 하나뿐이면 끝 장을 그대로 쓴다.
    """

    if "과업내용" not in _normalise_heading(end_entry.title):
        return end_entry.title, end_printed
    sections: list[_TocEntry] = []
    for follower in entries[end_index + 1:]:
        if follower.level == 1:
            break
        if follower.level == 2 and follower.printed_page is not None:
            sections.append(follower)
    first = next((index for index, item in enumerate(sections) if _has_target_word(item.title)), None)
    if first is None or first + 1 >= len(sections):
        return end_entry.title, end_printed
    following = sections[first + 1]
    return following.title, following.printed_page


def _locator(line: _Line, ordinal: int) -> dict[str, Any]:
    return {
        "block_key": line.block_key,
        "page": line.page,
        "line": line.line_index,
        "char_start": line.char_start,
        "char_end": line.char_end,
        "ordinal": ordinal,
    }


def select_v4_input_range(payload: Mapping[str, Any], *, candidates_complete: bool = True) -> V4RangeSelection:
    """Select a contiguous, source-bound overview/purpose/scope range.

    두 전략을 순서대로 쓴다 (ADR-0032 결정 1, ADR-0057 결정 2).
    ① 목차(`toc_scope`): 앞 5쪽의 목차 항목을 읽고 인쇄 쪽번호를 본문 제목 대조로
    물리 쪽에 맞춘 뒤 개요 장의 시작과 다음 장을 경계로 삼는다.
    ② 본문 heading(`heading_scope`): 목차를 쓸 수 없을 때만, 명시적인 장·번호
    heading만 인식해 가장 가까운 장을 유지하고 다음 장에서 멈춘다.

    어느 쪽도 시작·끝을 확정하지 못하면 전체 문서를 고르거나 고정 쪽 수로 자르지
    않고 사람 확인 manifest를 낸다. 목차 전략이 실패한 사유는 성공한 선택의 사유가
    아니므로 `reason_code`가 아니라 `toc_reason_code`로만 따라간다.
    """

    pages = _structure_pages(payload)
    lines = _lines(pages)
    if len(_canonical(payload)) > MAX_V4_MANIFEST_BYTES:
        raise V4PreparationError("input_size_limit")
    toc_pages = {line.page for line in lines if _toc_label(line.text)}
    # 표제 없이 항목만 있는 목차 쪽도 있다 (0911 공고 805). 쪽 번호로 끝나는
    # 줄이 여러 개면 그 쪽은 본문이 아니라 안내다. 한두 줄은 본문에도 있으므로
    # 고정 하한(5줄)을 넘을 때만 제외한다.
    entry_counts: dict[int, int] = defaultdict(int)
    for line in lines:
        if _TOC_ENTRY.search(line.text):
            entry_counts[line.page] += 1
    toc_pages |= {page for page, count in entry_counts.items() if count >= _TOC_ENTRY_LINES}
    entry_pages = _toc_entry_pages(pages)
    toc_pages |= entry_pages
    line_positions = {id(line): ordinal for ordinal, line in enumerate(lines)}
    # 목차가 본문과 대응하면 목차가 1순위다 (ADR-0032 결정 1, ADR-0057 결정 2).
    # 목차 전략은 rhwp 절 후보를 쓰지 않으므로 후보 완결성과 무관하게 먼저 시도한다.
    # `candidates_complete=False`의 자동 확정 금지는 아래 본문 전략에만 걸린다
    # (2026-09-16 운영 재실행: 공고 781이 후보 잘림으로 목차를 건너뛰고 fallback).
    toc_selection, toc_reason = _select_by_toc(payload, pages, lines, line_positions, toc_pages, entry_pages)
    if toc_selection is not None:
        return toc_selection
    body = [line for line in lines if line.page not in toc_pages]
    chapters = [line for line in body if line.chapter]
    # 제안서 작성 양식 안내 뒤의 장은 발주처 사업 범위가 아니다 (ADR-0057 결정 2).
    form_ordinal = next(
        (
            line_positions[id(line)] for line in body
            if line.heading_title
            and any(word in _normalise_heading(line.heading_title) for word in _FORM_CHAPTER_WORDS)
        ),
        None,
    )
    # 양식 안내 뒤의 장은 시작 후보가 아니지만 **끝 경계**로는 그대로 쓴다.
    selectable_chapters = (
        len(chapters) if form_ordinal is None
        else next(
            (index for index, line in enumerate(chapters) if line_positions[id(line)] >= form_ordinal),
            len(chapters),
        )
    )
    # Multiple explicit chapter markers on one extracted line have no proven
    # reading order (for example a two-column overview followed by chapter II).
    # Do not infer a column layout or silently keep the rest of the document.
    ambiguous_chapter_line = any(
        len(re.findall(r"(?:^|\s)[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s*[.)、:：\-–—]?\s*[^\sⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]", line.text)) > 1
        for line in chapters
    )

    reason: str | None = None
    start: _Line | None = None
    last: _Line | None = None
    end: _Line | None = None
    selected_chapter: _Line | None = None
    selected_chapter_index: int | None = None
    chapter_anchors: list[_Line] = []
    for chapter_index, chapter in enumerate(chapters[:selectable_chapters]):
        chapter_start = line_positions[id(chapter)]
        chapter_end = line_positions[id(chapters[chapter_index + 1])] if chapter_index + 1 < len(chapters) else len(lines)
        if form_ordinal is not None:
            chapter_end = min(chapter_end, form_ordinal)
        candidates = [
            line for line in body[0:]
            if chapter_start < line_positions[id(line)] < chapter_end and _is_target_heading(line)
        ]
        if candidates:
            selected_chapter = chapter
            selected_chapter_index = chapter_index
            chapter_anchors = candidates
            break
    if not chapters:
        reason = "scope_heading_missing"
    elif selected_chapter is None:
        reason = "scope_heading_missing"
    else:
        start = selected_chapter
        last = chapter_anchors[-1]
        assert selected_chapter_index is not None
        next_chapter_index = selected_chapter_index + 1
        if next_chapter_index >= len(chapters):
            reason = "scope_end_missing"
        else:
            next_chapter = chapters[next_chapter_index]
            end = next_chapter
            # A document whose first chapter is an overview/guide sometimes
            # puts the first concrete work section under the following
            # ``과업 내용`` chapter.  Carry only that first numbered section
            # across the chapter boundary; a generic next chapter (for
            # example ``제안요청 사항`` or ``과업수행 지침``) remains the
            # exclusive boundary.
            next_title = _normalise_heading(next_chapter.heading_title or "")
            if "과업내용" in next_title:
                following_chapter_ordinal = (
                    line_positions[id(chapters[next_chapter_index + 1])]
                    if next_chapter_index + 1 < len(chapters)
                    else len(lines)
                )
                next_start = line_positions[id(next_chapter)]
                next_anchors = [
                    line for line in body
                    if next_start < line_positions[id(line)] < following_chapter_ordinal
                    and _is_target_heading(line)
                    and line.level == 2
                ]
                if next_anchors:
                    next_section = next_anchors[0]
                    next_section_ordinal = line_positions[id(next_section)]
                    end = next_chapter
                    for candidate in body:
                        ordinal = line_positions[id(candidate)]
                        if ordinal <= next_section_ordinal or ordinal >= following_chapter_ordinal:
                            continue
                        if candidate.level == 2:
                            end = candidate
                            break
        if end is None:
            reason = "scope_end_missing"
        elif end.page < last.page or (end.page == last.page and end.line_index <= last.line_index):
            reason = "ambiguous_scope_boundary"

    # The proposal-writing template can contain 목적/범위 headings too.  Its
    # explicit 제안개요 label does not establish the procurer's business scope
    # (0910 notices 754/755). Do not accept that template as an overview.
    if selected_chapter is not None and _normalise_heading(selected_chapter.heading_title or "") == "제안개요":
        reason = "ambiguous_scope_boundary"
    if ambiguous_chapter_line:
        reason = "ambiguous_scope_boundary"
    if not candidates_complete:
        reason = "section_candidates_incomplete"
    if reason is not None or start is None or last is None or end is None:
        manifest = {
            "schema_version": V4_MANIFEST_SCHEMA,
            "document_version_id": str(payload.get("document_version_id")) if payload.get("document_version_id") is not None else None,
            "source_sha256": payload.get("source_sha256"),
            "selection_status": "needs_human_review",
            "reason_code": reason or "ambiguous_scope",
            "strategy": "heading_scope",
            "input_limitations": ["page_text_only", "table_layout_not_inferred"],
        }
        raw = _canonical(manifest)
        return V4RangeSelection(
            "needs_human_review", manifest["reason_code"], "heading_scope", None, None,
            (), (), manifest, raw, _sha256_bytes(raw), toc_reason,
        )

    return _range_from_lines(
        payload, pages, lines, line_positions, start, end,
        strategy="heading_scope", toc_reason_code=toc_reason,
    )


def _range_from_lines(
    payload: Mapping[str, Any],
    pages: Sequence[Mapping[str, Any]],
    lines: Sequence[_Line],
    line_positions: Mapping[int, int],
    start: _Line,
    end: _Line,
    *,
    strategy: str,
    toc_reason_code: str | None = None,
) -> V4RangeSelection:
    """`start`(포함)부터 `end`(배타)까지를 동결 입력 manifest로 만든다.

    두 전략이 같은 manifest 모양과 같은 쪽 부분 문자열 규칙을 쓰도록 한 곳에
    둔다. 끝 경계 앞의 공백만 있는 줄은 쪽을 늘리기만 하므로 버린다.
    """

    start_ordinal = line_positions[id(start)]
    end_ordinal = line_positions[id(end)]
    selected = list(lines[start_ordinal:end_ordinal])
    while selected and not selected[-1].text.strip():
        selected.pop()
    if not selected:
        raise V4PreparationError("ambiguous_scope")
    selected_pages = sorted({line.page for line in selected})
    page_by_number = {int(page["number"]): page for page in pages}
    selected_by_page: dict[int, list[_Line]] = defaultdict(list)
    for line in selected:
        selected_by_page[line.page].append(line)
    page_hashes_list: list[dict[str, Any]] = []
    selected_pages_payload: list[dict[str, Any]] = []
    for number in selected_pages:
        full_text = str(page_by_number[number]["text"])
        page_lines = selected_by_page[number]
        first_start = page_lines[0].char_start
        last_end = page_lines[-1].char_end
        selected_text = full_text[first_start:last_end]
        full_hash = _sha256_bytes(full_text.encode("utf-8"))
        selected_hash = _sha256_bytes(selected_text.encode("utf-8"))
        page_hashes_list.append({
            "number": number,
            "text_sha256": selected_hash,
            "source_page_text_sha256": full_hash,
        })
        selected_pages_payload.append({
            "number": number,
            "text": selected_text,
            "text_sha256": selected_hash,
            "source_page_text_sha256": full_hash,
        })
    return _ready_range_selection(
        document_version_id=payload.get("document_version_id"),
        source_sha256=payload.get("source_sha256"),
        page_payloads=selected_pages_payload,
        page_hashes=page_hashes_list,
        block_keys=sorted({line.block_key for line in selected}),
        start_locator=_locator(start, start_ordinal),
        end_locator=_locator(end, end_ordinal),
        strategy=strategy,
        toc_reason_code=toc_reason_code,
    )


def _select_by_toc(
    payload: Mapping[str, Any],
    pages: Sequence[Mapping[str, Any]],
    lines: Sequence[_Line],
    line_positions: Mapping[int, int],
    toc_pages: set[int],
    entry_pages: set[int],
) -> tuple[V4RangeSelection | None, str | None]:
    """목차로 앞부분 장을 고른다. 못 고르면 (None, 사유)를 돌려준다.

    인쇄 쪽번호는 본문 제목 대조로 물리 쪽에 맞춘다. 두 장 이상이 같은 offset을
    내지 못하면 추측하지 않고 본문 전략에 넘긴다 (ADR-0057 결정 2).
    """

    entries = _toc_entries(pages, entry_pages)
    if not entries:
        return None, "toc_missing"
    chapters = [item for item in _toc_chapters(entries) if item[2] is not None]
    if len(chapters) < 2:
        return None, "toc_target_missing"
    body_headings: dict[str, list[_Line]] = defaultdict(list)
    lines_by_page: dict[int, list[_Line]] = defaultdict(list)
    for line in lines:
        lines_by_page[line.page].append(line)
        if line.page in toc_pages or line.level != 1 or not line.heading_title:
            continue
        body_headings[_normalise_heading(line.heading_title)].append(line)
    offset = _toc_offset(chapters, body_headings)
    if offset is None:
        return None, "toc_alignment_failed"
    start_at = next(
        (index for index, (_i, entry, _p) in enumerate(chapters) if _has_target_word(entry.title)), 0
    )
    if start_at + 1 >= len(chapters):
        return None, "toc_target_missing"
    _start_index, start_entry, start_printed = chapters[start_at]
    end_index, end_entry, end_printed = chapters[start_at + 1]
    end_title, end_printed = _carry_first_work_section(entries, end_index, end_entry, end_printed)
    if start_printed is None or end_printed is None:
        return None, "toc_target_missing"

    def aligned(title: str, printed: int) -> _Line | None:
        page = printed + offset
        if page < 1 or page > len(pages) or page in toc_pages:
            return None
        page_lines = lines_by_page.get(page) or []
        normalized = _normalise_heading(title)
        for line in page_lines:
            if line.heading_title and _normalise_heading(line.heading_title) == normalized:
                return line
        # 정렬은 확정됐고 그 쪽에서 장이 시작한다. 제목 줄을 못 찾으면 쪽 첫
        # 줄을 경계로 쓴다(끝 경계에서는 그 쪽을 통째로 뺀다).
        return page_lines[0] if page_lines else None

    start_line = aligned(start_entry.title, start_printed)
    end_line = aligned(end_title, end_printed)
    if start_line is None or end_line is None:
        return None, "toc_target_missing"
    if line_positions[id(end_line)] <= line_positions[id(start_line)]:
        return None, "toc_alignment_failed"
    return _range_from_lines(
        payload, pages, lines, line_positions, start_line, end_line, strategy="toc_scope",
    ), None


def _ready_range_selection(
    *,
    document_version_id: Any,
    source_sha256: Any,
    page_payloads: Sequence[Mapping[str, Any]],
    page_hashes: Sequence[Mapping[str, Any]],
    block_keys: Sequence[str],
    start_locator: Mapping[str, Any],
    end_locator: Mapping[str, Any],
    strategy: str,
    extra: Mapping[str, Any] | None = None,
    toc_reason_code: str | None = None,
) -> V4RangeSelection:
    """Assemble one ready input manifest from an already bounded page selection.

    Both selectors (deterministic heading scope and human-confirmed page span)
    must emit the exact same manifest shape, so the assembly lives here once.
    ``extra`` only carries the human-confirmation fields; the input digest is
    taken before it is merged so the same pages keep the same input identity.
    ``toc_reason_code``는 범위를 정한 사유가 아니라 **앞선 목차 전략이 실패한
    사유**다. 성공한 선택의 `reason_code`는 언제나 ``None``이며, 이 값은 manifest
    에도 들어가지 않는다.
    """

    input_payload = {
        "schema_version": V4_MANIFEST_SCHEMA,
        "document_version_id": str(document_version_id) if document_version_id is not None else None,
        "source_sha256": source_sha256,
        "pages": [dict(item) for item in page_payloads],
        "block_keys": list(block_keys),
        "start_locator": dict(start_locator),
        "end_locator": dict(end_locator),
        "input_limitations": ["page_text_only", "table_layout_not_inferred"],
    }
    input_raw = _canonical(input_payload)
    manifest = {
        **input_payload,
        "selection_status": "ready",
        "strategy": strategy,
        "selected_text_sha256": _sha256_bytes(
            "\n".join(str(item["text"]) for item in page_payloads).encode("utf-8")
        ),
        **(dict(extra) if extra else {}),
    }
    raw = _canonical(manifest)
    if len(raw) > MAX_V4_MANIFEST_BYTES:
        raise V4PreparationError("input_size_limit")
    return V4RangeSelection(
        "ready", None, strategy, dict(start_locator), dict(end_locator),
        tuple(int(item["number"]) for item in page_payloads),
        tuple(dict(item) for item in page_hashes),
        manifest, raw, _sha256_bytes(input_raw), toc_reason_code,
    )


def select_v4_page_span(
    payload: Mapping[str, Any],
    first_page: int,
    last_page: int,
    *,
    start_locator: Mapping[str, Any],
    end_locator: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> V4RangeSelection:
    """Freeze a human-confirmed, contiguous **full-page** span.

    The deterministic selector cuts at heading boundaries inside a page; a human
    confirmation names whole pages, so every selected page carries its complete
    source text (``text_sha256 == source_page_text_sha256``).  Nothing here
    re-reads storage or decides eligibility: the caller has already bound the
    page-text payload and the page numbers, and this function only produces the
    immutable manifest.  A span that does not fit the manifest budget fails closed.
    """

    pages = _structure_pages(payload)
    if len(_canonical(payload)) > MAX_V4_MANIFEST_BYTES:
        raise V4PreparationError("input_size_limit")
    if (
        isinstance(first_page, bool) or isinstance(last_page, bool)
        or not isinstance(first_page, int) or not isinstance(last_page, int)
        or first_page < 1 or last_page < first_page or last_page > len(pages)
    ):
        raise V4PreparationError("page_range_invalid")
    safe_extra: dict[str, Any] = {}
    if extra is not None:
        safe_extra = _bounded_object(extra, code="range_confirmation_invalid")
        if set(safe_extra) - _V4_SPAN_EXTRA_FIELDS:
            raise V4PreparationError("range_confirmation_invalid")
    page_by_number = {int(page["number"]): page for page in pages}
    page_payloads: list[dict[str, Any]] = []
    page_hashes: list[dict[str, Any]] = []
    for number in range(first_page, last_page + 1):
        text = str(page_by_number[number]["text"])
        digest = _sha256_bytes(text.encode("utf-8"))
        page_payloads.append({
            "number": number, "text": text,
            "text_sha256": digest, "source_page_text_sha256": digest,
        })
        page_hashes.append({
            "number": number, "text_sha256": digest, "source_page_text_sha256": digest,
        })
    block_keys = sorted({
        line.block_key for line in _lines(pages) if first_page <= line.page <= last_page
    })
    return _ready_range_selection(
        document_version_id=payload.get("document_version_id"),
        source_sha256=payload.get("source_sha256"),
        page_payloads=page_payloads,
        page_hashes=page_hashes,
        block_keys=block_keys,
        start_locator=start_locator,
        end_locator=end_locator,
        strategy="human_confirmed",
        extra=safe_extra,
    )


def build_v4_range_review_manifest(
    selection: V4RangeSelection,
    *,
    candidates_sha256: str | None = None,
    candidate_count: int = 0,
) -> tuple[dict[str, Any], bytes]:
    """Build the human-review manifest for a selection that is not ``ready``.

    It records *why* a person has to choose and *which* candidate list they will
    see, never any document text.  Candidate titles stay in artifact ⑦; only its
    digest and count are bound here.
    """

    if selection.status == "ready":
        raise V4PreparationError("range_review_status_invalid")
    if candidates_sha256 is not None and not _SHA256.fullmatch(str(candidates_sha256)):
        raise V4PreparationError("section_candidates_invalid")
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, int) or candidate_count < 0:
        raise V4PreparationError("section_candidates_invalid")
    manifest = {
        "schema_version": V4_RANGE_REVIEW_SCHEMA,
        "document_version_id": selection.manifest.get("document_version_id"),
        "source_sha256": selection.manifest.get("source_sha256"),
        "selection_status": selection.status,
        "reason_code": selection.reason_code,
        "strategy": selection.strategy,
        "candidates_sha256": str(candidates_sha256) if candidates_sha256 is not None else None,
        "candidate_count": int(candidate_count),
        "input_limitations": list(selection.manifest.get("input_limitations") or []),
    }
    raw = _canonical(manifest)
    if len(raw) > MAX_V4_MANIFEST_BYTES:
        raise V4PreparationError("input_size_limit")
    return manifest, raw


def _pages_from_indices(
    candidates: Mapping[str, Any] | None,
    start_index: int,
    end_index: int,
    pdf_page_count: int,
) -> tuple[int, int]:
    """후보 index 쌍을 연속 쪽 범위로 바꾼다 (R7 고정 규칙).

    시작은 고른 절의 쪽, 끝은 **다음 절의 쪽**(마지막 절이면 문서 끝 쪽)이다.
    다음 절이 같은 쪽에서 시작하면 한 쪽짜리 범위가 된다.
    """

    sections = list(candidates.get("sections") or []) if candidates else []
    if candidates and candidates.get("candidates_truncated") is True:
        raise V4OpsError("candidate_range_incomplete")
    if not sections:
        raise V4OpsError("range_invalid")
    if start_index < 0 or end_index < start_index or end_index >= len(sections):
        raise V4OpsError("range_invalid")
    first_page = int(sections[start_index]["page"])
    last_page = (
        int(sections[end_index + 1]["page"]) if end_index + 1 < len(sections) else int(pdf_page_count)
    )
    if last_page < first_page:
        last_page = first_page
    return first_page, last_page


# --- heading 문자열 정규화 (문서 segment 계산과 공유) -------------------------
_NUMBERING_ONLY = re.compile(
    r"^[\s\d\W_]+$|^[\s]*(?:[ivxlcdm]+|[가-힣])(?:[.)、·\-:]?\s*)*$",
    re.IGNORECASE,
)
_PAGE_SUFFIX = re.compile(r"(?:\s*[.·…]{2,}\s*|\s+)(\d{1,5})\s*$")
_WHITESPACE = re.compile(r"\s+")
_GENERIC_HEADINGS = frozenset(
    {
        "목차",
        "contents",
        "table of contents",
        "tableofcontents",
        "페이지",
        "page",
        "쪽",
    }
)
_LEADING_HEADING_BULLET = re.compile(
    r"^\s*[·•∙◦○●◉▪▫■□◆◇▶▷]\s*"
)
_LEADING_HEADING_BRACKET = re.compile(
    r"^\s*(?:[\(\[\{]\s*(?:\d+(?:\.\d+)*|[ivxlcdm]+|[가-힣])\s*[\)\]\}]|"
    r"[①-⑳⓵-⓿])\s*[.)、:：\-–—]?\s*",
    re.IGNORECASE,
)
_LEADING_HEADING_NUMBER = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*|[ivxlcdm]+|[ⅰⅱⅲⅳⅴⅵⅠⅡⅢⅣⅤⅥ]+|[가-힣])"
    r"\s*[.)、:：\-–—]\s*",
    re.IGNORECASE,
)
_LEADING_HEADING_PUNCTUATION = re.compile(
    r"^\s*[.,:;!?。．、:：\-–—/|]+\s*"
)
_WRAPPED_HEADING_OPEN = re.compile(r"^\s*[\(\[\{<「『【〔〈《]\s*")
_WRAPPED_HEADING_CLOSE = re.compile(r"\s*[\)\]\}>」』】〕〉》]\s*$")


def _normalise_heading_text(value: object, *, toc: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    if toc:
        # TOC page numbers and leader dots are layout metadata, not heading
        # identity.  This only removes a suffix when an explicit TOC marker
        # already established that the block is a TOC entry.
        text = _PAGE_SUFFIX.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip().casefold()
    # Numbering is useful for humans but does not by itself establish a
    # heading match.  Remove it only after checking that the remaining title
    # contains meaningful text.
    # These are formatting prefixes observed in T-21 (arabic, roman, hangul,
    # bracketed, and circle/bullet numbering).  The title itself must still
    # equal a closed vocabulary item; this is not a substring or prose match.
    text = _LEADING_HEADING_BULLET.sub("", text)
    text = _LEADING_HEADING_BRACKET.sub("", text)
    text = _LEADING_HEADING_NUMBER.sub("", text)
    text = re.sub(r"^\s*\d+(?:\.\d+)*\s+", "", text)
    text = _LEADING_HEADING_PUNCTUATION.sub("", text)
    text = _WRAPPED_HEADING_OPEN.sub("", text)
    text = _WRAPPED_HEADING_CLOSE.sub("", text)
    return text.strip(" .·…\t")


def _meaningful_heading(text: object, *, toc: bool = False) -> bool:
    if not isinstance(text, str):
        return False
    raw = unicodedata.normalize("NFKC", text).strip()
    if not raw or _NUMBERING_ONLY.fullmatch(raw):
        return False
    normalized = _normalise_heading_text(raw, toc=toc)
    if not normalized or normalized in _GENERIC_HEADINGS:
        return False
    # A heading needs at least two alphanumeric/Hangul characters.  This
    # rejects punctuation and numbering-only blocks without guessing from
    # arbitrary paragraph prose.
    meaningful_chars = [char for char in normalized if char.isalnum() or "가" <= char <= "힣"]
    return len(meaningful_chars) >= 2



def _normalise_filename_label(original_filename: object) -> str | None:
    """NFKC + casefold + 공백 제거한 파일명. 문자열이 아니면 ``None``.

    `_filename_document_candidate`·`_filename_task_order_candidate`가 같은
    정규화를 공유하도록 한 곳에 둔다.
    """

    if not isinstance(original_filename, str):
        return None
    value = unicodedata.normalize("NFKC", original_filename).casefold()
    return _WHITESPACE.sub("", value)


def _filename_document_candidate(original_filename: object) -> bool:
    """Match the Korean RFP filename label, allowing formatting whitespace."""

    compact = _normalise_filename_label(original_filename)
    return compact is not None and "제안요청서" in compact


def _filename_task_order_candidate(original_filename: object) -> bool:
    """Match the Korean task-order (과업지시서) filename label.

    Same normalisation as `_filename_document_candidate`; used only as a
    fallback input document when no 제안요청서 candidate exists
    (2026-09-17 user decision).
    """

    compact = _normalise_filename_label(original_filename)
    return compact is not None and "과업지시서" in compact


__all__ = [
    "MAX_V4_MANIFEST_BYTES",
    "MAX_V4_PROVENANCE_BYTES",
    "V4OpsError",
    "V4PreparationError",
    "V4RangeSelection",
    "V4_MANIFEST_SCHEMA",
    "V4_RANGE_REVIEW_SCHEMA",
    "build_v4_range_review_manifest",
    "select_v4_input_range",
    "select_v4_page_span",
]
