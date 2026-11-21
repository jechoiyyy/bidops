"""인용 검증(spec M2-02 "인용 검증", 사용자 결정 6, 계약 시트 5절·13절 X10).

LLM이 낸 인용(Evidence.quote)이 원문(`RfpDocument.full_text`, NFC 적용)에 실제로 있는지 확인한다.
1. 정규화(`normalize`) 후 부분 문자열이면 원문 구간 그대로로 바꾼다(verified).
2. 아니면 정규화 원문을 quote 길이 ±`WINDOW_TOLERANCE` 창으로 훑어 difflib ratio 최대 창이
   `QUOTE_REPAIR_RATIO` 이상이면 그 원문 구간으로 바꾼다(verified, repaired).
3. 아니면 verified=False. 교정 결과는 항상 원문의 연속 부분 문자열이다.

근사 탐색(성능): 거친 단계는 quote 길이 L 창의 2-gram 겹침 수를 모든 시작점에서 슬라이딩으로
매겨(O(n)) 서로 보폭 `max(1, L // _COARSE_DIV)`보다 떨어진 상위 `_COARSE_TOP`개 시작점을 고른다.
정밀 단계는 각 후보 ±보폭 안을 보폭 1·길이 전 범위로 difflib ratio를 계산하되, ratio 상한
(`real_quick_ratio`·`quick_ratio`와 같은 식)이 현재 최선을 넘을 수 없거나 임계값 미만인 창은
건너뛴다(결과에 영향 없음). 동률은 시작이 앞선 것, 그다음 짧은 것.
"""

import difflib
import json
import math
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from bid_deep_engine.analysis.schemas import (
    QUOTE_MAX_CHARS,
    Evidence,
    RequirementFit,
    RfpFacts,
    SourceBlockLocation,
    SourceLocation,
    iter_evidence,
)
from bid_deep_engine.ingest.models import RfpDocument, Section

QUOTE_REPAIR_RATIO = 0.9  # 근사 교정 임계값(tunable, 사용자 결정 6). 호출 시점에 모듈 값을 읽는다
WINDOW_TOLERANCE = 0.2  # 근사 탐색 창 길이 L×(1±이 값)(tunable)
EVIDENCE_LOCATION_FIELDS = frozenset(
    {"locations", "location_status", "block_locations", "block_location_status"}
)

_COARSE_DIV = 4  # 후보 간격·정밀 탐색 반경 = max(1, L // _COARSE_DIV)
_COARSE_TOP = 5  # 정밀 탐색할 거친 후보 수

_MIDDOTS = "·ㆍ∙•‧"  # · ㆍ ∙ • ‧ → ·
_DQUOTES = "“”„‟″「」『』"  # “ ” „ ‟ ″ 「 」 『 』 → "
_SQUOTES = "‘’‚‛′"  # ‘ ’ ‚ ‛ ′ → '
_CHAR_MAP = str.maketrans(
    {**dict.fromkeys(_MIDDOTS, "·"), **dict.fromkeys(_DQUOTES, '"'), **dict.fromkeys(_SQUOTES, "'")}
)


class Citations(BaseModel):
    """인용 통계(M2-04·M2-05 공통). conflicts 제외 Evidence를 센다(X10).

    불변식: total == verified + unverified, repaired <= verified.
    """

    total: int
    verified: int  # verified is True(교정 포함)
    repaired: int  # repaired is True
    unverified: int  # verified is not True(None 포함)


def _llm_exclude(value: object) -> set[str] | dict[object, object] | None:
    """Pydantic ``exclude`` 트리: 모든 Evidence의 code-owned 위치 metadata만 고른다."""
    if isinstance(value, Evidence):
        return set(EVIDENCE_LOCATION_FIELDS)
    if isinstance(value, BaseModel):
        fields: dict[object, object] = {}
        for name in type(value).model_fields:
            if isinstance(value, RequirementFit) and (
                name in {"name", "definition"}
                or (name == "instance_key" and value.instance_key is None)
            ):
                fields[name] = True
                continue
            child = _llm_exclude(getattr(value, name))
            if child:
                fields[name] = child
        return fields or None
    if isinstance(value, (list, tuple)):
        items: dict[object, object] = {}
        for index, item in enumerate(value):
            child = _llm_exclude(item)
            if child:
                items[index] = child
        return items or None
    if isinstance(value, dict):
        items = {}
        for key, item in value.items():
            child = _llm_exclude(item)
            if child:
                items[key] = child
        return items or None
    return None


def model_dump_for_llm(model: BaseModel) -> dict[str, object]:
    """저장 모델은 유지하고 기존 Evidence wire 필드만 직렬화한다.

    ``locations``와 ``location_status``는 현재 로컬 캐시에서 코드가 계산하는 저장 metadata이므로
    provider 요청에 보내지 않는다. quote/page/verified/repaired 등 기존 필드는 그대로 보존한다.
    """
    return model.model_dump(mode="json", exclude=_llm_exclude(model))


def model_json_schema_for_llm(output_model: type[BaseModel]) -> dict[str, Any]:
    """저장 모델의 raw JSON Schema에서 code-owned Evidence 위치 metadata만 제외한다."""
    schema = output_model.model_json_schema()
    definitions = schema.get("$defs", {})
    evidence = definitions.get(Evidence.__name__)
    if evidence is not None:
        properties = evidence.get("properties", {})
        for name in EVIDENCE_LOCATION_FIELDS:
            properties.pop(name, None)
        required = evidence.get("required")
        if isinstance(required, list):
            evidence["required"] = [
                name for name in required if name not in EVIDENCE_LOCATION_FIELDS
            ]
        for model in (SourceLocation, SourceBlockLocation):
            definitions.pop(model.__name__, None)
            if f"#/$defs/{model.__name__}" in json.dumps(schema):
                raise ValueError(
                    f"{model.__name__} is referenced outside Evidence location metadata"
                )
    return schema


def normalize(text: str) -> tuple[str, list[int]]:
    """NFC → 중점류·따옴표류 통일 → 공백 연속을 공백 1개로 → 앞뒤 공백 제거.

    두 번째 값은 정규화 문자열 각 문자의 NFC 문자열 인덱스(공백 1개는 그 연속 구간의 첫 문자).
    문자 치환은 1:1이므로 인덱스가 어긋나지 않는다.
    """
    nfc = unicodedata.normalize("NFC", text).translate(_CHAR_MAP)
    chars: list[str] = []
    index: list[int] = []
    pending: int | None = None  # 아직 내보내지 않은 공백 연속 구간의 시작
    for i, ch in enumerate(nfc):
        if ch.isspace():  # re `\s`와 같은 판정(유니코드 공백, 줄바꿈 포함)
            if pending is None:
                pending = i
            continue
        if pending is not None and chars:  # 앞 공백은 버린다
            chars.append(" ")
            index.append(pending)
        pending = None
        chars.append(ch)
        index.append(i)
    return "".join(chars), index  # 뒤 공백은 pending으로 남아 버려진다


@dataclass(frozen=True)
class _Source:
    text: str  # NFC 원문(인용 교체의 기준)
    norm: str
    index: list[int]  # norm 문자 → text 인덱스
    sections: dict[str, Section]

    @classmethod
    def build(cls, source_text: str, sections: list[Section]) -> "_Source":
        norm, index = normalize(source_text)
        by_id: dict[str, Section] = {}
        for s in sections:
            by_id.setdefault(s.id, s)
        return cls(unicodedata.normalize("NFC", source_text), norm, index, by_id)

    def span(self, start: int, end: int) -> str:
        """정규화 구간 `[start, end)`에 대응하는 원문 구간."""
        return self.text[self.index[start] : self.index[end - 1] + 1]


def table_quote_spans(
    quote: str, rows: list[list[str]], block: str | None = None
) -> list[tuple[int, int]]:
    """Match consecutive quoted rows in one table, keeping every literal cell character."""
    if not rows or not quote.lstrip().startswith("|") or len(quote) > QUOTE_MAX_CHARS:
        return []
    width = max(map(len, rows))
    lines = ["".join(line.split()) for line in quote.strip().splitlines()]
    separator = "|" + "---|" * width
    raw_rows = [" | ".join(cell.replace("\n", " ") for cell in row) for row in rows]
    if block is not None and block != " / ".join(raw_rows):
        return []
    matches = []
    offset = 0
    for first, row_text in enumerate(raw_rows):
        start = pos = offset
        offset += len(row_text) + 3
        index = first
        for n, line in enumerate(lines):
            if n == 1 and first == 0 and line == separator and n < len(lines) - 1:
                continue
            if index >= len(rows) or not line.startswith("|"):
                break
            raw = raw_rows[index]
            # Render cells separately so escaped pipes and empty columns retain their boundaries.
            padded = rows[index] + [""] * (width - len(rows[index]))
            rendered = "|" + "|".join("".join(c.split()).replace("|", "\\|") for c in padded) + "|"
            last = n == len(lines) - 1
            if line != rendered and not (
                last and not line.endswith("|") and rendered.startswith(line)
            ):
                break
            if last:
                if not any(c.isalnum() for c in quote):
                    break
                stop = len(raw)
                if line != rendered:
                    target = line[1:].replace("\\|", "|")
                    offsets = [i for i, c in enumerate(raw) if not c.isspace()]
                    if not target or len(target) > len(offsets):
                        break
                    stop = offsets[len(target) - 1] + 1
                matches.append((start, pos + stop))
            pos += len(raw) + 3
            index += 1
    return matches


def verify(
    evidence: Evidence, source_text: str, sections: list[Section], *, allow_repair: bool = True
) -> tuple[Evidence, list[str]]:
    """Evidence 하나를 검증한 새 Evidence와 경고 목록(입력은 바꾸지 않는다)."""
    return _verify(evidence, _Source.build(source_text, sections), allow_repair=allow_repair)


def _verify(evidence: Evidence, src: _Source, *, allow_repair: bool) -> tuple[Evidence, list[str]]:
    warnings: list[str] = []
    quote = evidence.quote
    if allow_repair and len(quote) > QUOTE_MAX_CHARS:
        quote = quote[:QUOTE_MAX_CHARS]
        warnings.append(f"quote truncated to {QUOTE_MAX_CHARS} chars")

    section_id = evidence.section_id
    if section_id is not None and section_id not in src.sections:
        warnings.append(f"unknown section_id {section_id}")
        section_id = None
    page = src.sections[section_id].page_start if allow_repair and section_id is not None else None

    def result(q: str, verified: bool, repaired: bool) -> tuple[Evidence, list[str]]:
        update = {
            "quote": q,
            "section_id": section_id,
            "page": page,
            "verified": verified,
            "repaired": repaired,
        }
        return evidence.model_copy(update=update), warnings

    if not allow_repair and len(quote) > QUOTE_MAX_CHARS:
        warnings.append(f"quote exceeds {QUOTE_MAX_CHARS} chars")
        return result(quote, False, False)

    norm_q, _ = normalize(quote)
    if not norm_q:
        warnings.append("empty quote")
        return result(quote, False, False)

    found = src.norm.find(norm_q)
    if found >= 0:
        return result(_cap(src.span(found, found + len(norm_q)), warnings), True, False)

    if allow_repair:
        window = _best_window(norm_q, src.norm, QUOTE_REPAIR_RATIO)
        if window is not None:
            return result(_cap(src.span(*window), warnings), True, True)
    return result(quote, False, False)


def _cap(span: str, warnings: list[str]) -> str:
    """교체한 원문 구간이 200자를 넘으면(원문 공백이 많아서) 앞 200자로 자른다(spec 7)."""
    if len(span) > QUOTE_MAX_CHARS:
        warnings.append(f"repaired quote truncated to {QUOTE_MAX_CHARS} chars")
        return span[:QUOTE_MAX_CHARS]
    return span


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _best_window(q: str, text: str, threshold: float) -> tuple[int, int] | None:
    """ratio가 최대인 창 `[start, end)`(정규화 원문 기준). 최대값이 threshold 미만이면 None.

    동률은 시작이 앞선 것, 그다음 짧은 것. 정밀 단계는 후보를 거친 점수 순으로 돌지만 비교는
    (ratio 큰 것, 시작 작은 것, 길이 작은 것) 전순서라 순회 순서와 무관하게 결정적이다.
    """
    n = len(text)
    length = len(q)
    lo = max(1, _round_half_up(length * (1 - WINDOW_TOLERANCE)))
    hi = min(n, _round_half_up(length * (1 + WINDOW_TOLERANCE)))
    if lo > hi:
        return None
    step = max(1, length // _COARSE_DIV)
    candidates = _coarse_candidates(q, text, min(max(length, lo), hi), step)

    q_counts: dict[str, int] = {}
    for ch in q:
        q_counts[ch] = q_counts.get(ch, 0) + 1
    best: tuple[float, int, int] | None = None  # (ratio, start, 길이), ratio >= threshold

    def can_win(x: float, s: int, w: int) -> bool:  # 상한·값 x인 창 (s, w)가 최선을 대체하는가
        if best is None:
            return x >= threshold
        return x > best[0] or (x == best[0] and (s, w) < (best[1], best[2]))

    seen: set[int] = set()
    for c in candidates:
        for s in range(max(0, c - step), min(n - lo, c + step) + 1):
            if s in seen:
                continue
            seen.add(s)
            avail = dict(q_counts)  # quick_ratio 상한: 문자 다중집합 교집합 크기(창을 늘리며 갱신)
            matches = 0
            for w in range(1, min(hi, n - s) + 1):
                ch = text[s + w - 1]
                if avail.get(ch, 0) > 0:
                    avail[ch] -= 1
                    matches += 1
                if w < lo:
                    continue
                total = length + w
                # difflib real_quick_ratio·quick_ratio와 같은 식(ratio <= 둘)
                if not can_win(2.0 * min(length, w) / total, s, w):
                    continue
                if not can_win(2.0 * matches / total, s, w):
                    continue
                r = difflib.SequenceMatcher(None, q, text[s : s + w], autojunk=False).ratio()
                if can_win(r, s, w):
                    best = (r, s, w)
    return None if best is None else (best[1], best[1] + best[2])


def _coarse_candidates(q: str, text: str, width: int, step: int) -> list[int]:
    """거친 단계: 길이 width 창을 모든 시작점에서 2-gram 다중집합 겹침 수로 매기고(슬라이딩, O(n)),
    점수 내림차순·시작 오름차순으로 서로 step보다 떨어진 시작점을 최대 `_COARSE_TOP`개 고른다."""
    q_grams: dict[str, int] = {}
    for i in range(len(q) - 1):
        g = q[i : i + 2]
        q_grams[g] = q_grams.get(g, 0) + 1
    w_grams: dict[str, int] = {}
    overlap = 0

    def add(g: str) -> None:
        nonlocal overlap
        c = w_grams.get(g, 0)
        if c < q_grams.get(g, 0):
            overlap += 1
        w_grams[g] = c + 1

    def remove(g: str) -> None:
        nonlocal overlap
        c = w_grams[g] - 1
        w_grams[g] = c
        if c < q_grams.get(g, 0):
            overlap -= 1

    for i in range(width - 1):
        add(text[i : i + 2])
    scores = [overlap]
    for s in range(1, len(text) - width + 1):
        if width > 1:
            remove(text[s - 1 : s + 1])
            add(text[s + width - 2 : s + width])
        scores.append(overlap)

    picked: list[int] = []
    for s in sorted(range(len(scores)), key=lambda i: (-scores[i], i)):
        if all(abs(s - p) > step for p in picked):
            picked.append(s)
            if len(picked) >= _COARSE_TOP:
                break
    return picked


def _evidence_paths(model: BaseModel, prefix: str = "") -> Iterator[tuple[str, Evidence]]:
    """(경로, Evidence)를 `iter_evidence(..., include_conflicts=True)`와 같은 순서로 낸다."""
    for name in type(model).model_fields:
        yield from _value_paths(getattr(model, name), f"{prefix}{name}")


def _value_paths(value: object, path: str) -> Iterator[tuple[str, Evidence]]:
    if isinstance(value, Evidence):
        yield path, value
    elif isinstance(value, BaseModel):
        yield from _evidence_paths(value, f"{path}.")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _value_paths(item, f"{path}[{i}]")


def _count(facts: RfpFacts) -> Citations:
    counted = list(iter_evidence(facts))  # 기본: conflicts 제외(X10)
    verified = sum(e.verified is True for e in counted)
    return Citations(
        total=len(counted),
        verified=verified,
        repaired=sum(e.repaired is True for e in counted),
        unverified=len(counted) - verified,
    )


def verify_facts(
    facts: RfpFacts, doc: RfpDocument, *, allow_repair: bool = True
) -> tuple[RfpFacts, Citations, list[str]]:
    """conflicts 포함 모든 Evidence를 문서 순으로 verify한 새 RfpFacts, 통계, 경로 접두 경고."""
    src = _Source.build(doc.full_text, doc.sections)
    new = facts.model_copy(deep=True)
    warnings: list[str] = []
    for ev, (path, same) in zip(
        iter_evidence(new, include_conflicts=True), _evidence_paths(new), strict=True
    ):
        assert ev is same  # 경로 순회가 iter_evidence 순서와 같다
        checked, ev_warnings = _verify(ev, src, allow_repair=allow_repair)
        for name in Evidence.model_fields:  # 제자리 교체(새 RfpFacts 안의 인스턴스)
            setattr(ev, name, getattr(checked, name))
        warnings.extend(f"{path}: {w}" for w in ev_warnings)
    return new, _count(new), warnings
