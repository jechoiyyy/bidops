"""RfpDocument를 LLM 입력 문자열로 렌더하고 나눈다(spec M2-01 "LLM 입력 렌더").

섹션 표지: `<<{section_id} | kind={kind} | {pages}>>`(pages는 `normalize._pages_label` 규칙).
- `render_for_llm`: `full_text`를 섹션 구간으로 나눠 구간마다 표지 줄을 앞에 넣는다. 표지 줄을
  모두 지우면 `full_text`와 정확히 같다(손실 없음 — 인용 검증의 원문이 그대로 보인다).
- `render_requirements`: 요구사항 블록(0건이면 `""`).
- `build_document`: 단일 문서 문자열 빌더(계약 시트 13절 X1). 문서 문자열은 이것만 쓴다.
- `split_n`: 예약 규칙 균등 분할(항상 `min(n, m)`개, X11).
- `split_for_mapreduce`: 넘기 전에 닫는 통일 규칙(level-1 묶음 → 섹션 구간 → 줄, X11).

두 분할 모두 `"\\n".join(c.text for c in chunks) == render_for_llm(doc)`를 지킨다.
"""

from dataclasses import dataclass
from itertools import accumulate

from pydantic import BaseModel

from bid_deep_engine.ingest.models import RfpDocument, Section
from bid_deep_engine.ingest.normalize import _pages_label


class Chunk(BaseModel):
    section_ids: list[str]
    text: str


@dataclass(frozen=True)
class _Segment:
    """렌더 줄 목록의 `[start, end)` 구간. 표지 없는 앞부분 줄(S000 부재 시)은 section_id None."""

    section_id: str | None
    level: int
    start: int
    end: int


@dataclass(frozen=True)
class _Rendered:
    lines: list[str]  # 렌더 결과를 "\n"으로 나눈 줄
    owner: list[str | None]  # 줄마다 그 줄이 속한 섹션 ID
    is_marker: list[bool]
    segments: list[_Segment]  # 문서 순


def _marker(sec: Section) -> str:
    return f"<<{sec.id} | kind={sec.kind} | {_pages_label(sec)}>>"


def _render(doc: RfpDocument) -> _Rendered:
    """full_text를 섹션 구간으로 나눠 표지 줄을 넣는다. 헤딩 줄 미발견은 ValueError."""
    src = doc.full_text.split("\n")
    headed = [s for s in doc.sections if s.level > 0]
    starts: list[int] = []
    pos = 0
    for sec in headed:
        target = f"{'#' * sec.level} {sec.heading}"
        try:
            found = src.index(target, pos)
        except ValueError:
            raise ValueError(f"heading line not found: {sec.id}") from None
        starts.append(found)
        pos = found + 1
    first = starts[0] if starts else len(src)

    lines: list[str] = []
    owner: list[str | None] = []
    is_marker: list[bool] = []
    segments: list[_Segment] = []

    def emit(sec: Section | None, body: list[str]) -> None:
        begin = len(lines)
        if sec is not None:
            lines.append(_marker(sec))
            owner.append(sec.id)
            is_marker.append(True)
        lines.extend(body)
        owner.extend([sec.id if sec is not None else None] * len(body))
        is_marker.extend([False] * len(body))
        segments.append(
            _Segment(
                section_id=sec.id if sec is not None else None,
                level=sec.level if sec is not None else 0,
                start=begin,
                end=len(lines),
            )
        )

    preamble = next((s for s in doc.sections if s.level == 0), None)
    if preamble is not None:
        emit(preamble, src[:first])
    elif first > 0:
        # M0-04상 생기지 않아야 하지만 손실 없음을 위해 표지 없이 둔다.
        emit(None, src[:first])
    for k, sec in enumerate(headed):
        end = starts[k + 1] if k + 1 < len(headed) else len(src)
        emit(sec, src[starts[k] : end])
    return _Rendered(lines=lines, owner=owner, is_marker=is_marker, segments=segments)


def render_for_llm(doc: RfpDocument) -> str:
    """섹션 표지가 붙은 LLM 입력. 표지 줄을 지우면 `doc.full_text`와 같다."""
    return "\n".join(_render(doc).lines)


_MANDATORY_LABEL = {True: "필수", False: "선택", None: "-"}


def render_requirements(doc: RfpDocument) -> str:
    """요구사항 블록. 요구사항이 없으면 `""`. ID·세부내용은 원문 그대로."""
    if not doc.requirements:
        return ""
    blocks: list[str] = []
    for r in doc.requirements:
        lines = [
            f"[{r.id}] {r.name} | 필수={_MANDATORY_LABEL[r.mandatory]} | 섹션={r.section_id or '-'}"
        ]
        if r.definition is not None:
            lines.append(f"정의: {r.definition}")
        if r.details:
            lines.append(r.details)
        blocks.append("\n".join(lines))
    return f"<<REQUIREMENTS | count={len(doc.requirements)}>>\n" + "\n\n".join(blocks)


def build_document(doc: RfpDocument) -> str:
    """단일 문서 문자열(X1). 요구사항이 0건이면 구분자도 붙이지 않는다."""
    text = render_for_llm(doc)
    if doc.requirements:
        text += "\n\n" + render_requirements(doc)
    return text


def _units(r: _Rendered) -> list[_Segment]:
    """분할 단위 섹션 구간. 표지 없는 앞부분 줄은 다음 구간에 붙인다(다음이 없으면 단독)."""
    segs = r.segments
    if len(segs) >= 2 and segs[0].section_id is None:
        nxt = segs[1]
        segs = [_Segment(nxt.section_id, nxt.level, segs[0].start, nxt.end), *segs[2:]]
    return segs


def _chunk(r: _Rendered, start: int, end: int) -> Chunk:
    """렌더 줄 `[start, end)`의 Chunk. 구간 중간에서 시작하면 진행 중 섹션을 맨 앞에 둔다."""
    ids = [r.owner[k] for k in range(start, end) if r.is_marker[k]]
    head = r.owner[start] if start < end else None
    if start < end and not r.is_marker[start] and head is not None:
        ids.insert(0, head)
    return Chunk(section_ids=[i for i in ids if i is not None], text="\n".join(r.lines[start:end]))


def split_n(doc: RfpDocument, n: int) -> list[Chunk]:
    """섹션 구간을 자르지 않고 정확히 `min(n, m)`개로 나눈다(예약 규칙, X11)."""
    if n < 1:
        raise ValueError(f"n must be >= 1: {n}")
    r = _render(doc)
    units = _units(r)
    m = len(units)
    if m <= n:
        return [_chunk(r, u.start, u.end) for u in units]

    sizes = [len("\n".join(r.lines[u.start : u.end])) for u in units]
    total = sum(sizes)
    chunks: list[Chunk] = []
    begin = 0  # 현재 Chunk의 첫 단위
    cum = 0
    for j, size in enumerate(sizes):
        cum += size
        i = len(chunks) + 1  # 현재 Chunk 번호(1부터)
        if i >= n:
            continue
        remaining = m - j - 1
        if cum * n >= total * i or remaining == n - i:
            chunks.append(_chunk(r, units[begin].start, units[j].end))
            begin = j + 1
    chunks.append(_chunk(r, units[begin].start, units[-1].end))
    return chunks


@dataclass(frozen=True)
class _Unit:
    """렌더 줄 `[start, end)`. children이 None이면 줄 하나(더 풀 수 없음)."""

    start: int
    end: int
    children: list["_Unit"] | None


def _line_units(start: int, end: int) -> list[_Unit]:
    return [_Unit(k, k + 1, None) for k in range(start, end)]


def _segment_unit(seg: _Segment) -> _Unit:
    return _Unit(seg.start, seg.end, _line_units(seg.start, seg.end))


def _top_units(r: _Rendered) -> list[_Unit]:
    """level 1 섹션이 2개 이상이면 level-1 묶음, 아니면 섹션 구간이 1단계 단위다."""
    segs = _units(r)
    if sum(1 for s in segs if s.level == 1) < 2:
        return [_segment_unit(s) for s in segs]
    groups: list[list[_Segment]] = []
    in_bundle = False
    for s in segs:
        if s.level == 1:
            groups.append([s])
            in_bundle = True
        elif in_bundle:
            groups[-1].append(s)
        else:
            groups.append([s])  # 첫 level 1 이전 구간은 각각 독립 묶음
    return [_Unit(g[0].start, g[-1].end, [_segment_unit(s) for s in g]) for g in groups]


def split_for_mapreduce(doc: RfpDocument, max_chars: int) -> list[Chunk]:
    """넘기 전에 닫는 통일 규칙(X11)으로 나눈다. 줄 하나가 max_chars보다 길 때만 초과한다."""
    if max_chars < 1:
        raise ValueError(f"max_chars must be >= 1: {max_chars}")
    r = _render(doc)
    prefix = [0, *accumulate(len(line) for line in r.lines)]

    def length(start: int, end: int) -> int:
        # 줄 [start, end)를 "\n"으로 결합한 길이
        return prefix[end] - prefix[start] + (end - start - 1)

    bounds: list[tuple[int, int]] = []
    cur_start: int | None = None  # 현재 Chunk의 시작 줄(비어 있으면 None)
    cur_end = 0

    def close() -> None:
        nonlocal cur_start
        if cur_start is not None:
            bounds.append((cur_start, cur_end))
            cur_start = None

    def add(u: _Unit) -> None:
        nonlocal cur_start, cur_end
        if cur_start is not None:
            if length(cur_start, u.end) <= max_chars:
                cur_end = u.end
                return
            close()  # 다음 단위를 더하면 넘으므로 먼저 닫는다
        if length(u.start, u.end) <= max_chars or u.children is None:
            # max_chars보다 긴 줄은 다음 단위가 오면 위 규칙으로 닫혀 단독 Chunk가 된다.
            cur_start, cur_end = u.start, u.end
            return
        for c in u.children:  # 단독으로 넘는 단위는 다음 단계 단위로 푼다
            add(c)

    for u in _top_units(r):
        add(u)
    close()
    return [_chunk(r, s, e) for s, e in bounds]
