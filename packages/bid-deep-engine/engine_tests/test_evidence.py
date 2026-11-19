"""인용 검증 테스트(spec M2-02 T17~T24, "인용 검증").

합성 원문·섹션과 픽스처 tests/fixtures/facts_full.json(M2-01)만 쓴다. 네트워크·LLM을 쓰지 않는다.
"""

import difflib
import random
import unicodedata
from pathlib import Path

import pytest

from bid_deep_engine.analysis import evidence as ev_mod
from bid_deep_engine.analysis.evidence import (
    QUOTE_REPAIR_RATIO,
    WINDOW_TOLERANCE,
    Citations,
    normalize,
    verify,
    verify_facts,
)
from bid_deep_engine.analysis.schemas import QUOTE_MAX_CHARS, Evidence, RfpFacts, iter_evidence
from bid_deep_engine.ingest.models import RfpDocument, Section, SourceQuality

FIXTURES = Path(__file__).parent / "fixtures"

FILLER = "본 사업은 발주기관의 홈페이지를 안정적으로 운영하기 위한 유지관리 사업이다.\n"


def _section(sid: str, page_start: int | None = None) -> Section:
    return Section(
        id=sid,
        heading=f"제목 {sid}",
        level=1,
        kind="other",
        block_start=0,
        block_end=0,
        text="",
        page_start=page_start,
    )


SECTIONS = [_section("S000"), _section("S001", 31), _section("S002")]


def _doc(full_text: str, sections: list[Section]) -> RfpDocument:
    return RfpDocument(
        slug="synthetic",
        title="합성 문서",
        source_files=["synthetic.hwpx"],
        primary_format="hwpx",
        sections=sections,
        requirements=[],
        tables=[],
        full_text=full_text,
        source_quality=SourceQuality(
            primary_format="hwpx",
            primary_chars=len(full_text),
            primary_digits=0,
            has_tables=False,
            requirements_found=0,
            sections_mapped_to_pages=0,
        ),
    )


def _ev(quote: str, section_id: str | None = "S001") -> Evidence:
    return Evidence(quote=quote, section_id=section_id)


# --- 상수 ---


def test_constants():
    assert QUOTE_REPAIR_RATIO == 0.9
    assert WINDOW_TOLERANCE == 0.2
    assert QUOTE_MAX_CHARS == 200


# --- normalize ---


def test_normalize_whitespace_and_mapping():
    text = "  가\t\t나 \n\n 다  "
    norm, idx = normalize(text)
    assert norm == "가 나 다"
    assert len(idx) == len(norm)
    assert [text[i] for i in idx] == ["가", "\t", "나", " ", "다"]  # 공백은 연속 구간의 첫 문자
    assert idx == sorted(idx)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A·BㆍC∙D•E‧F", "A·B·C·D·E·F"),
        ("“”„‟″「」『』", '"' * 9),
        ("‘’‚‛′", "'" * 5),
    ],
)
def test_normalize_punct_variants(raw: str, expected: str):
    norm, idx = normalize(raw)
    assert norm == expected
    assert idx == list(range(len(raw)))


def test_normalize_nfc_mapping():
    decomposed = unicodedata.normalize("NFD", "가나")  # 자모 4개
    norm, idx = normalize(decomposed)
    assert norm == "가나"
    assert idx == [0, 1]  # NFC 문자열 기준 인덱스


def test_normalize_empty():
    assert normalize("") == ("", [])
    assert normalize(" \n\t ") == ("", [])


# --- T17 정확 일치 ---


def test_t17_exact_whitespace():
    src_part = "직접생산확인 증명서  (세부품명: 정보시스템유지관리서비스)\n소지자"
    source = FILLER + src_part + "로 한다.\n" + FILLER
    quote = "직접생산확인 증명서 (세부품명: 정보시스템유지관리서비스) 소지자"
    ev = _ev(quote)
    out, warnings = verify(ev, source, SECTIONS)
    assert out.verified is True
    assert out.repaired is False
    assert out.quote == src_part  # 이중 공백·줄바꿈 포함 원문 그대로
    assert out.quote in source
    assert warnings == []
    assert ev.quote == quote and ev.verified is None  # 입력 불변


def test_t17_exact_middot_and_quotes():
    src_part = "“정보ㆍ통신” 분야 「소프트웨어 진흥법」에 따른 ‘중소기업’"
    source = FILLER + src_part + FILLER
    quote = '"정보·통신" 분야 "소프트웨어 진흥법"에 따른 \'중소기업\''
    out, warnings = verify(_ev(quote), source, SECTIONS)
    assert (out.verified, out.repaired) == (True, False)
    assert out.quote == src_part
    assert warnings == []


def test_t17_exact_first_occurrence():
    source = "앞 부분 상주 인원 3명 중간 상주 인원 3명 끝"
    out, _ = verify(_ev("상주  인원 3명"), source, SECTIONS)
    assert out.verified is True
    assert source.index(out.quote) == source.index("상주 인원 3명")


# --- T18 근사 교정 ---

REPAIR_SRC = "계약상대자는 하도급 계약금액이 원도급 계약금액의 50%를 초과하지 않도록 하여야 한다"
REPAIR_TYPO = "계약상대자는 하도급 계약금액이 원도굽 계약금액의 50%를 초과하지 않도록 하여야 한다"


def test_t18_repair_one_char_typo():
    source = FILLER * 3 + REPAIR_SRC + ".\n" + FILLER * 3
    out, warnings = verify(_ev(REPAIR_TYPO), source, SECTIONS)
    assert out.verified is True
    assert out.repaired is True
    assert out.quote == REPAIR_SRC
    assert warnings == []


def test_t18_repair_maps_back_to_source_whitespace():
    src_part = REPAIR_SRC.replace(" ", "  ").replace("원도급", "\n원도급")
    source = FILLER + src_part + "。" + FILLER
    out, _ = verify(_ev(REPAIR_TYPO), source, SECTIONS)
    assert (out.verified, out.repaired) == (True, True)
    assert out.quote == src_part
    assert out.quote in source


def test_t18_repair_tie_prefers_earliest():
    source = FILLER + REPAIR_SRC + "\n" + FILLER + REPAIR_SRC + "\n" + FILLER
    out, _ = verify(_ev(REPAIR_TYPO), source, SECTIONS)
    assert out.repaired is True
    assert out.quote == REPAIR_SRC
    # 같은 결과가 반복돼도 동일(결정적)
    again, _ = verify(_ev(REPAIR_TYPO), source, SECTIONS)
    assert again == out


def test_t18_repair_window_longer_than_quote():
    # quote가 원문보다 몇 자 짧다(누락) — 창 길이 L×(1+0.2) 안에서 찾는다.
    missing = REPAIR_SRC.replace("원도급 ", "")
    source = FILLER + REPAIR_SRC + "\n" + FILLER
    out, _ = verify(_ev(missing), source, SECTIONS)
    assert (out.verified, out.repaired) == (True, True)
    assert out.quote == REPAIR_SRC


def _brute_best(q: str, text: str, threshold: float) -> tuple[int, int] | None:
    length = len(q)
    lo = max(1, int(length * 0.8 + 0.5))
    hi = min(len(text), int(length * 1.2 + 0.5))
    best: tuple[float, int, int] | None = None
    for s in range(len(text)):
        for w in range(lo, min(hi, len(text) - s) + 1):
            r = difflib.SequenceMatcher(None, q, text[s : s + w], autojunk=False).ratio()
            if best is None or r > best[0]:
                best = (r, s, s + w)
    if best is None or best[0] < threshold:
        return None
    return best[1], best[2]


@pytest.mark.parametrize("seed", range(30))
def test_t18_fine_search_matches_brute_force(monkeypatch: pytest.MonkeyPatch, seed: int):
    # 거친 후보를 전부 정밀 탐색하게 하면 가지치기 결과가 전수 탐색(최대·동률 규칙)과 같아야 한다.
    monkeypatch.setattr(ev_mod, "_COARSE_TOP", 10**6)
    rng = random.Random(seed)
    alphabet = "가나다라 "
    text = "".join(rng.choice(alphabet) for _ in range(60)).strip()
    start = rng.randrange(0, 40)
    q = list(text[start : start + rng.randrange(8, 20)])
    q[rng.randrange(len(q))] = rng.choice(alphabet)
    quote = "".join(q).strip() or "가"
    for threshold in (0.0, 0.7, 0.9):
        assert ev_mod._best_window(quote, text, threshold) == _brute_best(quote, text, threshold)


# --- T19 실패 ---


def test_t19_unverified():
    source = FILLER * 5
    quote = "제안서는 전자조달시스템을 통해서만 제출하며 우편 접수는 받지 않는다"
    ev = _ev(quote)
    out, warnings = verify(ev, source, SECTIONS)
    assert out.verified is False
    assert out.repaired is False
    assert out.quote == quote
    assert warnings == []


def test_t19_source_empty():
    out, _ = verify(_ev("무언가"), "", SECTIONS)
    assert (out.verified, out.repaired, out.quote) == (False, False, "무언가")


# --- T20 임계값 ---


def test_t20_threshold_from_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ev_mod, "QUOTE_REPAIR_RATIO", 0.99)
    source = FILLER * 3 + REPAIR_SRC + ".\n" + FILLER * 3
    out, _ = verify(_ev(REPAIR_TYPO), source, SECTIONS)
    assert out.verified is False
    assert out.repaired is False
    assert out.quote == REPAIR_TYPO


# --- T21 200자 ---


def test_t21_quote_truncated():
    long_part = "".join(f"{i:03d}항목 " for i in range(60))  # 360자, 반복 없는 원문
    source = FILLER + long_part + FILLER
    quote = long_part[:250]
    out, warnings = verify(_ev(quote), source, SECTIONS)
    assert warnings == ["quote truncated to 200 chars"]
    assert len(out.quote) == QUOTE_MAX_CHARS
    assert out.quote == quote[:200]
    assert (out.verified, out.repaired) == (True, False)
    assert out.quote in source


def test_t21_repaired_quote_truncated():
    words = [f"단어{i:02d}" for i in range(40)]  # 단어당 4자 + 공백
    src_part = "     ".join(words)  # 원문 공백 5칸 → 원문 구간 > 200자
    source = FILLER + src_part + "\n" + FILLER
    norm_quote = " ".join(words)  # 199자
    assert len(norm_quote) <= QUOTE_MAX_CHARS < len(src_part)
    quote = norm_quote[:100] + "X" + norm_quote[101:]  # 1자 오탈자
    out, warnings = verify(_ev(quote), source, SECTIONS)
    assert (out.verified, out.repaired) == (True, True)
    assert warnings == ["repaired quote truncated to 200 chars"]
    assert len(out.quote) == QUOTE_MAX_CHARS
    assert out.quote == src_part[:200]
    assert out.quote in source


def test_t21_exact_long_source_span_truncated():
    # 정확 일치라도 원문 구간이 공백 때문에 200자를 넘으면 앞 200자로 자른다(spec 7).
    words = [f"단어{i:02d}" for i in range(40)]
    src_part = "     ".join(words)
    source = FILLER + src_part + "\n" + FILLER
    out, warnings = verify(_ev(" ".join(words)), source, SECTIONS)
    assert (out.verified, out.repaired) == (True, False)
    assert warnings == ["repaired quote truncated to 200 chars"]
    assert out.quote == src_part[:200]


# --- T22 section_id·page ---


def test_t22_unknown_section():
    out, warnings = verify(_ev("유지관리", "S999"), FILLER, SECTIONS)
    assert out.section_id is None
    assert out.page is None
    assert warnings == ["unknown section_id S999"]
    assert out.verified is True


def test_t22_known_section_page():
    ev = Evidence(quote="유지관리", section_id="S001", page=99)
    out, warnings = verify(ev, FILLER, SECTIONS)
    assert out.section_id == "S001"
    assert out.page == 31
    assert list(out.locations) == [] and out.location_status == "unavailable"
    assert warnings == []


def test_t22_section_without_page():
    out, _ = verify(_ev("유지관리", "S002"), FILLER, SECTIONS)
    assert out.section_id == "S002"
    assert out.page is None


def test_t22_no_section():
    ev = Evidence(quote="유지관리", section_id=None, page=5)
    out, warnings = verify(ev, FILLER, SECTIONS)
    assert out.section_id is None
    assert out.page is None
    assert warnings == []


# --- T23 빈 quote ---


@pytest.mark.parametrize("quote", ["", "   ", "\n\t"])
def test_t23_empty_quote(quote: str):
    out, warnings = verify(_ev(quote), FILLER, SECTIONS)
    assert out.verified is False
    assert out.repaired is False
    assert out.quote == quote
    assert warnings == ["empty quote"]


def test_t23_empty_quote_with_unknown_section():
    out, warnings = verify(_ev("  ", "S999"), FILLER, SECTIONS)
    assert warnings == ["unknown section_id S999", "empty quote"]
    assert out.verified is False


# --- T24 verify_facts ---

# facts_full.json 인용 → 합성 원문에 넣을 형태. 없는 키는 원문에 넣지 않는다(불일치).
T24_SOURCE_PARTS = {
    # 정확 일치(공백·줄바꿈 변형)
    "사업예산: 430,000,000원(부가가치세 포함)": "사업예산:  430,000,000원(부가가치세\n포함)",
    "제안서 제출 마감: 2026. 11. 20.(금) 10:00": "제안서 제출 마감: 2026. 11. 20.(금) 10:00",
    "직접생산확인증명서(소프트웨어유지및지원서비스, 8111159901)": (
        "직접생산확인증명서(소프트웨어유지및지원서비스, 8111159901)"
    ),
    "기술능력평가 90점, 입찰가격평가 10점": "기술능력평가 90점, 입찰가격평가 10점",
    "사업예산 430,000,000원": "사업예산 430,000,000원",
    # 근사 교정(원문 가운데가 1자 다름 — 끝 글자가 다르면 짧은 창이 이긴다)
    "대기업인 소프트웨어사업자는 참여할 수 없음": "대기업인 소프트웨어 사업자는 참여할 수 없음",
    "PM 1명은 발주기관 지정 장소에 상주": "PM 1명은 발주기관 지정장소에 상주",
    "공동수급은 공동이행방식만 허용함": "공동수급은 공동 이행방식만 허용함",
}
T24_EXACT = 4  # conflicts 제외 정확 일치 수(위 정확 일치 5개 중 conflicts 1개 제외)
T24_REPAIRED = 3


@pytest.fixture
def facts_full() -> RfpFacts:
    return RfpFacts.model_validate_json((FIXTURES / "facts_full.json").read_text("utf-8"))


@pytest.fixture
def t24_doc() -> RfpDocument:
    parts = []
    for i, part in enumerate(T24_SOURCE_PARTS.values()):
        parts.append(FILLER if i % 2 else "다음과 같이 정한다.\n")
        parts.append(part + "\n")
    full = "".join(parts) + FILLER
    sections = [_section(f"S{i:03d}", 10 + i) for i in range(9)]  # S000~S008, S009 없음
    return _doc(full, sections)


def test_t24_verify_facts(facts_full: RfpFacts, t24_doc: RfpDocument):
    before = facts_full.model_dump()
    new, citations, warnings = verify_facts(facts_full, t24_doc)

    assert facts_full.model_dump() == before  # 입력 불변
    assert new is not facts_full

    all_ev = list(iter_evidence(new, include_conflicts=True))
    assert len(all_ev) == len(list(iter_evidence(facts_full, include_conflicts=True)))
    assert all(e.verified is not None for e in all_ev)  # conflicts 포함 전부
    assert all(e.repaired is not None for e in all_ev)
    for e in all_ev:
        if e.verified:
            assert e.quote in t24_doc.full_text  # 교정 결과는 원문 그대로

    counted = list(iter_evidence(new))  # conflicts 제외
    assert isinstance(citations, Citations)
    assert citations.total == len(counted) == 11
    assert citations.verified == sum(e.verified is True for e in counted)
    assert citations.repaired == sum(e.repaired is True for e in counted)
    assert citations.unverified == sum(e.verified is not True for e in counted)
    assert citations.verified == T24_EXACT + T24_REPAIRED
    assert citations.repaired == T24_REPAIRED
    assert citations.unverified == 11 - T24_EXACT - T24_REPAIRED
    assert citations.total == citations.verified + citations.unverified
    assert citations.repaired <= citations.verified

    # 개별 경로 확인
    assert new.project.evidence[0].quote == "사업예산:  430,000,000원(부가가치세\n포함)"
    assert new.project.evidence[0].page == 11  # S001 page_start
    assert (new.eligibility[1].evidence.verified, new.eligibility[1].evidence.repaired) == (
        True,
        True,
    )
    assert new.eligibility[1].evidence.quote == "대기업인 소프트웨어 사업자는 참여할 수 없음"
    assert new.commercial_sw[0].evidence.verified is False  # 원문에 없음
    conflict_ev = new.conflicts[0].evidence
    assert (conflict_ev[0].verified, conflict_ev[0].repaired) == (True, False)
    assert (conflict_ev[1].verified, conflict_ev[1].repaired) == (False, False)
    assert conflict_ev[1].section_id is None  # S009 없음

    # 경고는 Evidence 경로 접두
    assert warnings == ["conflicts[0].evidence[1]: unknown section_id S009"]


def test_t24_warning_paths(t24_doc: RfpDocument):
    facts = RfpFacts.model_validate(
        {
            "project": {"evidence": [{"quote": "유지관리"}, {"quote": " ", "section_id": "S001"}]},
            "eligibility": [
                {"code": "OTHER", "text": "a", "evidence": {"quote": "x"}},
                {"code": "OTHER", "text": "b", "evidence": {"quote": "x"}},
                {"code": "OTHER", "text": "c", "evidence": {"quote": "x", "section_id": "S999"}},
            ],
            "evaluation": {
                "quantitative": [
                    {
                        "item": "i",
                        "max_points": 1,
                        "kind": "OTHER",
                        "evidence": {"quote": "y" * 201},
                    }
                ]
            },
        }
    )
    new, citations, warnings = verify_facts(facts, t24_doc)
    assert warnings == [
        "project.evidence[1]: empty quote",
        "eligibility[2].evidence: unknown section_id S999",
        "evaluation.quantitative[0].evidence: quote truncated to 200 chars",
    ]
    assert citations == Citations(total=6, verified=1, repaired=0, unverified=5)
    assert new.project.evidence[0].verified is True


def test_t24_conflicts_excluded_from_stats():
    # conflicts의 Evidence도 verify하지만 통계에는 세지 않는다(X10).
    facts = RfpFacts.model_validate(
        {"conflicts": [{"field": "f", "evidence": [{"quote": "유지관리"}, {"quote": "없음"}]}]}
    )
    new, citations, warnings = verify_facts(facts, _doc(FILLER, SECTIONS))
    assert citations == Citations(total=0, verified=0, repaired=0, unverified=0)
    assert [e.verified for e in new.conflicts[0].evidence] == [True, False]
    assert warnings == []
