"""회사 지식 베이스(md) 로더. 네트워크·LLM 없이 파일만 읽는다(표준 라이브러리 + pydantic + yaml).

트리 배치·페이지 형식·위키링크·심볼릭 링크 규칙은 KB-01 spec "입력·출력 계약"을 따른다.

- 파일 전체를 UTF-8로 읽어 `\\r\\n` → `\\n`으로 정규화한 뒤 frontmatter(YAML)와 본문을 가른다.
- 디렉터리는 상대 경로(POSIX, NFC) 정렬 순으로 순회한다(결정성).
- `.md` 심볼릭 링크는 페이지로 세지 않는다. 루트 밖을 가리키면 E12, 루트 안이면 W6.
- lint 규칙(E1~E12, W1~W6)과 보고 순서(rel 정렬 → 규칙 순)는 spec "lint 규칙" 절을 따른다.
- W4 예산 계산과 `select_pages`·`render_knowledge`는 같은 머리글·블록 함수(`_render_header`,
  `_render_block`, `_SEP`)와 같은 그리디(`_plan_selection`)를 쓴다.
- 실적(portfolio) 페이지는 카테고리 예산에 넣지 않고, 공고와 겹침 점수가 높은 상위
  `PORTFOLIO_TOP_K`개를 별도 예산 `PORTFOLIO_BUDGET_CHARS`로 고른다(관련 실적 선택,
  설계 docs/design/2026-10-25-past-rfp-capabilities.md 2.3).
- 분류(`classify_notice`)는 `RfpDocument`(rfp.json)만 입력으로 쓴다. facts.json은 쓰지 않는다.
- `bid_deep_engine.analysis.*`를 import하지 않는다(KB-03의 `analysis/schemas.py`가 이 모듈을 import한다).
"""

import hashlib
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, Field, StringConstraints, ValidationError, field_validator

from bid_deep_engine.company.past_labels import (
    PAST_LABELS_FILE,
    PastLabels,
    PastLabelsError,
    parse_past_labels,
    portfolio_id_of,
    read_past_labels_text,
)
from bid_deep_engine.company.schema import CompanyProfile, _Model
from bid_deep_engine.ingest.models import RfpDocument

# --- 설정 키(모듈 상수, spec "설정 키와 기본값") ---

KNOWLEDGE_DIR_NAME = "knowledge"
KNOWLEDGE_BUDGET_CHARS = 12_000
MAX_CATEGORIES = 2
CATEGORY_MIN_SCORE = 3
TITLE_WEIGHT = 3
BODY_WEIGHT = 1
BODY_SECTION_CHARS = 4_000
BODY_TOTAL_CHARS = 20_000
CATEGORY_PAGE_MAX_CHARS = 6_000
PAGE_MAX_CHARS = 4_000
FALLBACK_CATEGORY = "other"
PORTFOLIO_TOP_K = 5  # 관련 실적 선택: 겹침 점수 상위 개수
PORTFOLIO_BUDGET_CHARS = 16_000  # 관련 실적 선택의 별도 예산(카테고리 예산과 따로 센다)
# 실적 페이지 점수에 쓰는 절. 둘 다 없는 페이지(사람이 쓴 시드)는 본문 전체로 센다.
PORTFOLIO_MATCH_SECTIONS: tuple[str, ...] = ("수행한 요구 범위", "기술 환경")
KB_CLASSIFY_TARGET_PCT = 80  # 분류 적중 보고용 기준(코드로 강제하지 않는다)

# --- 패턴·트리 배치 ---

SLUG_RE = re.compile(r"^(P\d{4}-\d{2}|[a-z0-9]+(-[a-z0-9]+)*)$")
PAGE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # DateStr은 YYYY-MM도 허용하므로 따로 둔다
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

INDEX_FILE = "INDEX.md"
SCHEMA_FILE = "SCHEMA.md"
ROOT_PAGE_FILE = "glossary.md"
# 폴더 → 그 폴더에 둘 수 있는 kind. 루트의 glossary.md는 폴더가 없다(`ROOT_PAGE_FILE`).
KIND_DIRS: dict[str, str] = {
    "categories": "category",
    "capabilities": "capability",
    "portfolio": "portfolio",
    "rules": "rule",
}
ROOT_PAGE_KIND = "glossary"

# category 본문 `##` 절의 고정 이름·순서(W2).
CATEGORY_SECTIONS: tuple[str, ...] = (
    "이 유형 공고의 전형적 요구",
    "보유 역량·근거",
    "강점",
    "약점·갭",
    "대표 실적",
    "관련 페이지",
)
# kind 전용 필드(E9). 선언 순서가 보고 순서다.
KIND_ONLY_FIELDS: tuple[tuple[str, str], ...] = (
    ("keywords", "category"),
    ("exclude_keywords", "category"),
    ("portfolio_id", "portfolio"),
)
SECTION_RE = re.compile(r"^## (.*)$", re.MULTILINE)
HEADING_DEMOTE_RE = re.compile(r"^(?=#{1,4} )", re.MULTILINE)  # 본문 ATX 제목 두 단계 내림

PageKind = Literal["category", "capability", "portfolio", "rule", "glossary"]
Confidence = Literal["confirmed", "estimate", "unknown"]
CategorySource = Literal["keyword", "override", "fallback"]

Slug = Annotated[str, StringConstraints(pattern=SLUG_RE.pattern)]
PageDate = Annotated[str, StringConstraints(pattern=PAGE_DATE_RE.pattern)]


# --- 스키마 ---


class Keyword(_Model):
    term: str
    weight: Annotated[int, Field(ge=1)]

    @field_validator("term")
    @classmethod
    def _term_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("String should not be blank")
        return value


class PageMeta(_Model):
    """페이지 frontmatter. kind별 허용 필드(E9)·slug↔stem(E2)·유일성(E3)은 lint가 본다."""

    slug: Slug
    title: str
    kind: PageKind
    tags: list[str] = []
    categories: list[str] = []
    updated: PageDate | None = None
    confidence: Confidence = "unknown"
    sources: list[str] = []
    keywords: list[str | Keyword] = []  # category만. str은 weight 1
    exclude_keywords: list[str] = []  # category만
    portfolio_id: str | None = None  # portfolio만

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("String should not be blank")
        return value


# --- 결과 모델 ---


@dataclass(frozen=True)
class Page:
    meta: PageMeta
    path: Path  # 실제 파일(심볼릭 링크면 resolve 결과)
    rel: str  # 루트 기준 상대 경로(POSIX, NFC)
    body: str
    links: list[str]  # 본문 [[slug]] 순서, 중복 제거


@dataclass(frozen=True)
class Knowledge:
    root: Path
    pages: dict[str, Page]  # slug → Page, 삽입 순서 = rel 정렬
    index_slugs: list[str]  # INDEX.md의 [[slug]] 등장 순(중복 제거)
    hash: str  # knowledge_hash(root)

    def categories(self) -> list[Page]:
        """kind == category인 페이지, slug 정렬."""
        found = [p for p in self.pages.values() if p.meta.kind == "category"]
        return sorted(found, key=lambda p: p.meta.slug)


class KnowledgeError(Exception):
    """load_knowledge 실패. errors는 lint_knowledge의 errors와 같은 문구."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


class KnowledgeReport(BaseModel):
    errors: list[str] = []
    warnings: list[str] = []
    pages: int = 0  # frontmatter 파싱에 성공한 페이지 수(루트 없음 → 0)


class Classification(BaseModel):
    categories: list[str]  # 1개 이상, 선택 순서
    source: CategorySource
    scores: dict[str, int]  # 모든 keyword 보유 category의 점수(0 포함), slug 정렬


LabelResult = Literal["hit", "partial", "miss", "unlabeled"]


class LabelRow(BaseModel):
    slug: str
    label: list[str] | None  # 사람이 매긴 카테고리(주, 부 순). 라벨 없음 → None
    predicted: list[str]
    result: LabelResult
    scores: dict[str, int]


class LabelReport(BaseModel):
    rows: list[LabelRow]  # slug 정렬
    labeled: int  # unlabeled가 아닌 행 수
    hit: int
    partial: int
    miss: int
    pct: int | None  # hit 비율(소수 없이 반올림). labeled == 0 → None

    @property
    def below_target(self) -> bool:
        return self.pct is not None and self.pct < KB_CLASSIFY_TARGET_PCT

    def summary_line(self) -> str:
        """요약 줄. n == 0이면 `labeled: 0 · hit: 0 (n/a)`."""
        if self.pct is None:
            return "labeled: 0 · hit: 0 (n/a)"
        line = (
            f"labeled: {self.labeled} · hit: {self.hit} ({self.pct}%) "
            f"· partial: {self.partial} · miss: {self.miss}"
        )
        if self.below_target:
            line += f" · below target {KB_CLASSIFY_TARGET_PCT}%"
        return line


class KnowledgeSelection(BaseModel):
    categories: list[str]
    category_source: CategorySource
    pages: list[str]  # 포함된 slug, 렌더링 순서
    skipped: list[str]  # 예산 때문에 빠진 slug
    chars: int  # render_knowledge 결과 길이
    knowledge_hash: str


# --- 공개 함수 ---


def load_knowledge(root: Path | str, *, profile: CompanyProfile | None = None) -> Knowledge:
    """트리를 읽는다. lint error가 하나라도 있으면 KnowledgeError(경고는 무시)."""
    tree, report = _build(Path(root), profile)
    if report.errors or tree is None:
        raise KnowledgeError(report.errors)
    return Knowledge(
        root=Path(root),
        pages=tree.pages,
        index_slugs=tree.index_slugs,
        hash=knowledge_hash(Path(root)),
    )


def lint_knowledge(root: Path | str, *, profile: CompanyProfile | None = None) -> KnowledgeReport:
    """트리 검사. 루트가 없으면 errors=["knowledge root not found: <root>"]. 예외를 내지 않는다."""
    _, report = _build(Path(root), profile)
    return report


def knowledge_hash(root: Path) -> str:
    """root 아래 일반 `*.md`(심볼릭 링크 파일·디렉터리 제외, INDEX·SCHEMA 포함)의 sha256 hex.

    rel(POSIX, NFC) 문자열 정렬 순으로, `len(rel utf-8)`(4바이트 big-endian) + rel utf-8 +
    `len(bytes)`(4바이트 big-endian) + 파일 바이트(정규화 없이 원본)를 이어 붙인다.
    """
    digest = hashlib.sha256()
    for entry in _walk_md(Path(root)):
        if entry.is_link:
            continue
        rel_bytes = entry.rel.encode("utf-8")
        data = entry.path.read_bytes()
        digest.update(len(rel_bytes).to_bytes(4, "big"))
        digest.update(rel_bytes)
        digest.update(len(data).to_bytes(4, "big"))
        digest.update(data)
    return digest.hexdigest()


def classify_notice(
    doc: RfpDocument, knowledge: Knowledge, *, override: list[str] | None = None
) -> Classification:
    """공고를 category 페이지 slug로 분류한다(spec "분류" 절). 결정적 코드 규칙.

    입력은 rfp.json(`RfpDocument`)뿐이다. `override`가 주어지면 `validate_override`로 검사한
    순서 그대로 쓰고 source는 `override`이며, scores는 똑같이 계산해 기록한다.
    """
    title_text = _norm(doc.title)
    body_text = _norm(_body_source(doc))
    scores: dict[str, int] = {}
    for page in knowledge.categories():  # slug 정렬 → scores도 slug 정렬
        meta = page.meta
        if not meta.keywords:
            continue
        scores[meta.slug] = _score(meta, title_text, body_text)
    if override is not None:
        return Classification(
            categories=validate_override(knowledge, override), source="override", scores=scores
        )
    ranked = sorted(
        (slug for slug, score in scores.items() if score >= CATEGORY_MIN_SCORE),
        key=lambda slug: (-scores[slug], slug),
    )
    if not ranked:
        return Classification(categories=[FALLBACK_CATEGORY], source="fallback", scores=scores)
    return Classification(categories=ranked[:MAX_CATEGORIES], source="keyword", scores=scores)


def compare_labels(
    classifications: Mapping[str, Classification], labels: PastLabels
) -> LabelReport:
    """분류 결과를 사람이 매긴 라벨과 견준다(spec "분류 적중"). 결정적 코드 규칙.

    - hit: 라벨 주(`categories[0]`)가 `predicted`에 포함 / partial: 주는 없고 부 카테고리만
      포함 / miss: 교집합 없음 / unlabeled: 라벨 없음(적중률 분모에서 제외).
    - pct = hit / labeled를 소수 없이 반올림(round half up, 정수 연산으로 정확히 계산).
    """
    rows: list[LabelRow] = []
    counts = {"hit": 0, "partial": 0, "miss": 0, "unlabeled": 0}
    for slug in sorted(classifications):
        c = classifications[slug]
        label = labels.notices.get(slug)
        result: LabelResult
        if label is None:
            result = "unlabeled"
        elif label.categories[0] in c.categories:
            result = "hit"
        elif any(cat in c.categories for cat in label.categories[1:]):
            result = "partial"
        else:
            result = "miss"
        counts[result] += 1
        rows.append(
            LabelRow(
                slug=slug,
                label=None if label is None else list(label.categories),
                predicted=list(c.categories),
                result=result,
                scores=dict(c.scores),
            )
        )
    labeled = len(rows) - counts["unlabeled"]
    pct = (200 * counts["hit"] + labeled) // (2 * labeled) if labeled else None
    return LabelReport(
        rows=rows,
        labeled=labeled,
        hit=counts["hit"],
        partial=counts["partial"],
        miss=counts["miss"],
        pct=pct,
    )


def select_pages(
    knowledge: Knowledge,
    categories: list[str],
    *,
    budget_chars: int = KNOWLEDGE_BUDGET_CHARS,
    category_source: CategorySource = "keyword",
    doc: RfpDocument | None = None,
    portfolio_top_k: int = PORTFOLIO_TOP_K,
    portfolio_budget_chars: int = PORTFOLIO_BUDGET_CHARS,
) -> KnowledgeSelection:
    """발췌 페이지를 고른다(spec "선택" 절): category → depth-1 링크(실적 제외) → glossary,
    그리디 예산. `doc`이 있으면 뒤에 관련 실적(`relevant_portfolio`)을 별도 예산으로 붙인다.

    `category_source`는 렌더링 머리글(`(<source>)`)에 들어가 예산 계산의 시작 길이를 바꾸므로
    여기서 받는다(`prepare_knowledge`는 분류 결과의 source를 넘긴다). categories는
    `validate_override`와 같은 규칙으로 중복 제거·검사한다. 카테고리가 링크한 실적 페이지는
    카테고리 예산에 들어가지 않고 관련 실적 선택으로만 들어간다(중복 없음). `doc`이 없으면
    실적 페이지는 고르지 않는다.
    """
    cats = validate_override(knowledge, categories)
    related = (
        [] if doc is None else [s for s, _ in relevant_portfolio(knowledge, doc, portfolio_top_k)]
    )
    plan = _plan_selection(
        knowledge.pages,
        cats,
        category_source,
        budget_chars,
        related=related,
        portfolio_budget_chars=portfolio_budget_chars,
    )
    return KnowledgeSelection(
        categories=cats,
        category_source=category_source,
        pages=plan.pages,
        skipped=plan.skipped,
        chars=plan.chars,
        knowledge_hash=knowledge.hash,
    )


def render_knowledge(knowledge: Knowledge, selection: KnowledgeSelection) -> str:
    """선택 결과를 결정적 문자열로 렌더링한다(spec "렌더링" 절 — 바이트 고정).

    머리글 두 줄 + 포함된 페이지 블록들을 빈 줄 하나로 잇는다. 제목 줄·타임스탬프·경로·해시
    없음, 끝 개행 없음.
    """
    parts = [_render_header(selection.categories, selection.category_source)]
    parts.extend(_render_block(knowledge.pages[slug]) for slug in selection.pages)
    return _SEP.join(parts).rstrip("\n")


def prepare_knowledge(
    doc: RfpDocument,
    knowledge: Knowledge,
    *,
    override: list[str] | None = None,
    budget_chars: int = KNOWLEDGE_BUDGET_CHARS,
) -> tuple[KnowledgeSelection, str]:
    """classify → select(관련 실적 포함) → render. KB-03 pipeline·bench 사전 추정과 CLI show가
    같이 쓴다."""
    classification = classify_notice(doc, knowledge, override=override)
    selection = select_pages(
        knowledge,
        classification.categories,
        budget_chars=budget_chars,
        category_source=classification.source,
        doc=doc,
    )
    return selection, render_knowledge(knowledge, selection)


def relevant_portfolio(
    knowledge: Knowledge, doc: RfpDocument, top_k: int = PORTFOLIO_TOP_K
) -> list[tuple[str, int]]:
    """공고와 겹침 점수가 높은 실적 페이지 `(slug, 점수)` 상위 `top_k`개(설계 2.3).

    점수 = 공고 토큰(제목 + overview 본문 + 요구사항 이름·정의, `_notice_match_text`)과 실적 페이지
    토큰(`PORTFOLIO_MATCH_SECTIONS` 절, 둘 다 없으면 본문 전체)의 교집합 크기. 토큰은
    `_match_tokens`(정규화한 2글자 이상, 불용어 제외). 점수 0인 페이지는 고르지 않는다.
    정렬은 점수 내림차순 → slug 사전순(결정성).
    """
    if top_k <= 0:
        return []
    notice = _match_tokens(_notice_match_text(doc))
    if not notice:
        return []
    scored: list[tuple[str, int]] = []
    for slug, page in knowledge.pages.items():
        if page.meta.kind != "portfolio":
            continue
        score = len(notice & _match_tokens(_portfolio_match_text(page)))
        if score > 0:
            scored.append((slug, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:top_k]


# 수행 실적 게이트가 대조하는 실적 페이지 절(설계 2026-10-25-past-performance-capability 2.1).
PORTFOLIO_GATE_SECTIONS: tuple[str, ...] = (
    "수행한 요구 범위",
    "기술 환경",
    "이 실적이 뒷받침하는 역량",
)
_EMPTY_SECTION_LINE = "(없음)"


def gate_knowledge_root(company_path: Path | str) -> Path:
    """게이트가 읽는 지식 루트: 회사 프로필 파일 폴더의 `knowledge/`(analyze 기본 해석과 같다)."""
    return Path(company_path).parent / KNOWLEDGE_DIR_NAME


def portfolio_gate_texts(knowledge: Knowledge) -> dict[str, str]:
    """`{실적 ID: 대조 텍스트}`(실적 ID 정렬). `confidence: confirmed`인 portfolio 페이지만 쓴다.

    대조 텍스트 = `PORTFOLIO_GATE_SECTIONS` 절 본문을 이 순서로 이은 것(빈 줄과 `(없음)` 줄 —
    글머리 `- (없음)` 포함 — 은 뺀다). 세 절이 모두 비면 그 페이지는 넣지 않는다. 실적 ID는
    frontmatter `portfolio_id`, 없으면 slug다.
    """
    found: dict[str, str] = {}
    for page in knowledge.pages.values():
        meta = page.meta
        if meta.kind != "portfolio" or meta.confidence != "confirmed":
            continue
        sections = _sections(page.body)
        parts: list[str] = []
        for name in PORTFOLIO_GATE_SECTIONS:
            lines = [
                line
                for line in sections.get(name, "").strip().splitlines()
                if line.strip().lstrip("-* ").strip() not in ("", _EMPTY_SECTION_LINE)
            ]
            if lines:
                parts.append("\n".join(lines))
        if parts:
            found[meta.portfolio_id or meta.slug] = "\n".join(parts)
    return dict(sorted(found.items()))


def load_portfolio_texts(
    root: Path | str | None, *, profile: CompanyProfile | None = None
) -> dict[str, str]:
    """게이트용 실적 지식 텍스트 공통 로더(pipeline·regate·report·잠정 결론이 같이 쓴다).

    root가 None이거나 디렉터리가 아니면 `{}`(지식 없음 = 기존 판정). 트리 lint 오류는
    `KnowledgeError`(호출자가 치명·비활성을 정한다).
    """
    if root is None or not Path(root).is_dir():
        return {}
    return portfolio_gate_texts(load_knowledge(root, profile=profile))


def parse_category_option(value: str | None) -> list[str] | None:
    """`--category` 값: `","`로 나눠 strip, 빈 항목 제거, 중복 제거(순서 유지). CLI 공용.

    None → None. 남는 항목이 없으면 ValueError("--category is empty").
    """
    if value is None:
        return None
    items = [item.strip() for item in value.split(",")]
    result = list(dict.fromkeys(item for item in items if item))
    if not result:
        raise ValueError("--category is empty")
    return result


def validate_override(knowledge: Knowledge, categories: list[str]) -> list[str]:
    """중복 제거(순서 유지) 후 각 값이 category slug인지 검사한다(doc 없이 호출 가능).

    아니면 ValueError("unknown category '<v>' (known: <정렬 목록 ", ">)"). 결과가 비면(빈 목록)
    ValueError("category override is empty") — Classification.categories는 1개 이상이어야 한다.
    """
    unique = list(dict.fromkeys(categories))
    if not unique:
        raise ValueError("category override is empty")
    known = [page.meta.slug for page in knowledge.categories()]
    known_set = set(known)
    for value in unique:
        if value not in known_set:
            raise ValueError(f"unknown category '{value}' (known: {', '.join(known)})")
    return unique


# --- 분류 내부 ---


def _norm(text: str) -> str:
    """NFC → casefold → 모든 공백 문자 제거."""
    return "".join(unicodedata.normalize("NFC", text).casefold().split())


def _body_source(doc: RfpDocument) -> str:
    """overview 절 text(절마다 앞 BODY_SECTION_CHARS, 합쳐서 BODY_TOTAL_CHARS) + 요구사항 이름.

    합계 한도는 절에서 가져온 글자 수만 센다(구분 개행 제외). 정규화 전 원문 글자 기준.
    """
    parts: list[str] = []
    remaining = BODY_TOTAL_CHARS
    for section in doc.sections:
        if section.kind != "overview" or remaining <= 0:
            continue
        piece = section.text[: min(BODY_SECTION_CHARS, remaining)]
        parts.append(piece)
        remaining -= len(piece)
    names = "\n".join(req.name for req in doc.requirements)
    return "\n".join(parts) + "\n" + names


def _keyword_terms(meta: PageMeta) -> list[tuple[str, int]]:
    """(정규화된 term, weight). str 키워드는 weight 1. 정규화 후 빈 term은 버린다."""
    terms: list[tuple[str, int]] = []
    for keyword in meta.keywords:
        term, weight = (keyword, 1) if isinstance(keyword, str) else (keyword.term, keyword.weight)
        normalized = _norm(term)
        if normalized:
            terms.append((normalized, weight))
    return terms


def _score(meta: PageMeta, title_text: str, body_text: str) -> int:
    """Σ weight × (TITLE_WEIGHT·[제목 포함] + BODY_WEIGHT·[본문 포함]). exclude 제목 히트면 0."""
    excludes = [term for term in map(_norm, meta.exclude_keywords) if term]
    if any(term in title_text for term in excludes):
        return 0
    return sum(
        weight * (TITLE_WEIGHT * (term in title_text) + BODY_WEIGHT * (term in body_text))
        for term, weight in _keyword_terms(meta)
    )


# --- 관련 실적 선택 내부(설계 2.3) ---

MATCH_TOKEN_RE = re.compile(r"[0-9a-z가-힣]+")
MATCH_TOKEN_MIN_CHARS = 2
# 토큰 끝에서 한 번만 떼는 조사(남는 글자가 2자 이상일 때만). 긴 것부터 본다.
_MATCH_PARTICLES: tuple[str, ...] = (
    "으로", "에서", "에게", "까지", "부터",
    "을", "를", "은", "는", "의", "에", "와", "과", "로", "이", "가", "도",
)  # fmt: skip
# RFP에 흔해 관련성을 가르지 못하는 말과 요구사항 ID 접두(SFR 등).
MATCH_STOPWORDS: frozenset[str] = frozenset(
    """
    및 등 관련 대한 위한 통한 따른 경우 이상 이하 이내 필요 적용 기반 제공 지원 관리 기능 구축
    사업 용역 시스템 요구 요구사항 수행 운영 정의 내용 방안 계획 산출물 발주기관 제안사 제안
    해당 각종 전체 기타 포함 대상 위해 있음 있는 하는 한다 해야 하여 가능 사항 구현 개발 세부
    방법 서비스 업무 기준 준수 작성 제출 사용 확인 수립 기술 환경 조건 범위 항목 실시 진행
    sfr ecr per sir dar ter ser qur cor pmr psr inr csr pjr mhr
    """.split()
)


def _match_tokens(text: str) -> set[str]:
    """NFKC·casefold 후 `[0-9a-z가-힣]+` 토큰. 조사 하나를 떼고 2글자 미만·숫자로 시작하는 것
    (`2024년`·`10개월` 같은 수량)·불용어는 버린다."""
    tokens: set[str] = set()
    for raw in MATCH_TOKEN_RE.findall(unicodedata.normalize("NFKC", text).casefold()):
        token = raw
        for particle in _MATCH_PARTICLES:
            if token.endswith(particle) and len(token) - len(particle) >= MATCH_TOKEN_MIN_CHARS:
                token = token[: -len(particle)]
                break
        if len(token) < MATCH_TOKEN_MIN_CHARS or token[0].isdigit() or token in MATCH_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _notice_match_text(doc: RfpDocument) -> str:
    """공고 쪽 점수 입력: 제목 + overview 본문(`_body_source`와 같은 한도) + 요구사항 이름·정의.

    요구사항이 추출되지 않은 공고(요구사항 0건)도 제목·개요로 관련 실적을 고를 수 있게 제목을
    넣는다.
    """
    reqs = "\n".join(f"{req.name}\n{req.definition or ''}" for req in doc.requirements)
    return f"{doc.title}\n{_body_source(doc)}\n{reqs}"


def _sections(body: str) -> dict[str, str]:
    """`## 제목` → 그 절 본문(다음 `## ` 전까지). 같은 제목이 또 나오면 이어 붙인다."""
    found: dict[str, str] = {}
    matches = list(SECTION_RE.finditer(body))
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        name = match.group(1).strip()
        text = body[match.end() : end]
        found[name] = found.get(name, "") + text
    return found


def _portfolio_match_text(page: Page) -> str:
    sections = _sections(page.body)
    picked = [sections[name] for name in PORTFOLIO_MATCH_SECTIONS if name in sections]
    return "\n".join(picked) if picked else page.body


# --- 트리 순회 ---


@dataclass(frozen=True)
class _Entry:
    rel: str  # POSIX, NFC. 심볼릭 링크면 링크 경로
    path: Path  # 순회에서 만난 경로(링크 자체 포함)
    is_link: bool


def _walk_md(root: Path) -> list[_Entry]:
    """root 아래 모든 `*.md`를 rel 정렬 순으로. 심볼릭 링크 디렉터리는 들어가지 않는다."""
    entries: list[_Entry] = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            if not name.endswith(".md"):
                continue
            full = Path(dirpath, name)
            entries.append(_Entry(_rel_of(full, root), full, os.path.islink(full)))
    entries.sort(key=lambda e: (e.rel, str(e.path)))
    return entries


def _rel_of(path: Path, root: Path) -> str:
    rel = PurePosixPath(*path.relative_to(root).parts)
    return unicodedata.normalize("NFC", rel.as_posix())


def _expected_kind(rel: str) -> str | None:
    """rel 위치에서 허용되는 kind. 페이지가 아니거나 허용 위치 밖이면 None."""
    parts = rel.split("/")
    if len(parts) == 1:
        return ROOT_PAGE_KIND if parts[0] == ROOT_PAGE_FILE else None
    if len(parts) == 2:
        return KIND_DIRS.get(parts[0])
    return None


def _is_inside(target: Path, root_real: Path) -> bool:
    return target == root_real or root_real in target.parents


# --- 트리 빌드(lint의 공통 입력) ---

# 이슈 = (rel, 규칙 번호, 메시지). 보고 순서는 "rel 정렬 → 규칙 순"(spec).
_Issue = tuple[str, int, str]


@dataclass
class _Tree:
    pages: dict[str, Page] = field(default_factory=dict)  # 등록된 페이지(E3 뒤 파일 제외)
    parsed_pages: list[Page] = field(default_factory=list)  # E1·E2를 통과한 모든 페이지, rel 순
    index_slugs: list[str] = field(default_factory=list)
    index_present: bool = False
    index_unreadable: bool = False  # INDEX.md가 있으나 읽기 실패(E1) — E7을 내지 않는다
    unexpected: list[str] = field(default_factory=list)  # 허용 위치 밖 `.md`의 rel(E11 후보)
    suppressed: set[str] = field(default_factory=set)  # E1·E2 페이지의 stem·frontmatter slug
    parsed: int = 0  # frontmatter 파싱에 성공한 페이지 수
    errors: list[_Issue] = field(default_factory=list)
    warnings: list[_Issue] = field(default_factory=list)


def _build(root: Path, profile: CompanyProfile | None) -> tuple[_Tree | None, KnowledgeReport]:
    """트리를 읽고(E1·E2·E12·W6) 나머지 lint 규칙을 적용해 보고서를 만든다."""
    if not root.is_dir():
        return None, KnowledgeReport(errors=[f"knowledge root not found: {root}"], pages=0)
    tree = _read_tree(root)
    _lint_tree(tree, profile)
    _lint_past_labels(root, tree, profile)
    report = KnowledgeReport(
        errors=[msg for _, _, msg in sorted(tree.errors, key=_issue_key)],
        warnings=[msg for _, _, msg in sorted(tree.warnings, key=_issue_key)],
        pages=tree.parsed,
    )
    return tree, report


def _issue_key(issue: _Issue) -> tuple[str, int]:
    return issue[0], issue[1]


def _read_tree(root: Path) -> _Tree:
    tree = _Tree()
    root_real = root.resolve()
    for entry in _walk_md(root):
        if entry.is_link:
            try:
                target = entry.path.resolve()
            except (OSError, RuntimeError):  # 링크 순환 등: 루트 안으로 보고 경고만 낸다
                target = root_real
            if _is_inside(target, root_real):
                tree.warnings.append((entry.rel, 6, f"{entry.rel}: symlink; use [[link]] instead"))
            else:
                tree.errors.append(
                    (entry.rel, 12, f"{entry.rel}: symlink target outside knowledge root")
                )
            continue  # 링크는 페이지로 세지 않는다. 실제 파일은 순회에서 따로 읽힌다.
        if entry.rel == SCHEMA_FILE:
            continue
        if entry.rel == INDEX_FILE:
            text = _read_text(entry, tree)
            if text is not None:
                tree.index_present = True
                tree.index_slugs = _extract_links(_normalize_newlines(text))
            continue
        if _expected_kind(entry.rel) is None:
            tree.unexpected.append(entry.rel)
            continue
        text = _read_text(entry, tree)
        if text is not None:
            _read_page(entry, text, tree)
    return tree


def _read_text(entry: _Entry, tree: _Tree) -> str | None:
    try:
        return entry.path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = " ".join(str(exc).split())
        tree.errors.append((entry.rel, 1, f"{entry.rel}: cannot read file: {msg}"))
        if entry.rel == INDEX_FILE:
            tree.index_unreadable = True
        else:
            tree.suppressed.add(PurePosixPath(entry.rel).stem)
        return None


def _read_page(entry: _Entry, text: str, tree: _Tree) -> None:
    rel = entry.rel
    stem = PurePosixPath(rel).stem
    parsed = _parse_page(text)
    if isinstance(parsed, str):  # E1 사유
        tree.errors.append((rel, 1, f"{rel}: {parsed}"))
        tree.suppressed.add(stem)
        return
    meta_or_errors, body, raw_slug = parsed
    if not isinstance(meta_or_errors, PageMeta):
        tree.errors.extend((rel, 1, f"{rel}: {line}") for line in meta_or_errors)
        tree.suppressed.add(stem)
        if raw_slug is not None:
            tree.suppressed.add(raw_slug)
        return
    meta = meta_or_errors
    tree.parsed += 1
    if meta.slug != stem:
        tree.errors.append((rel, 2, f"{rel}: slug '{meta.slug}' != file stem '{stem}'"))
        tree.suppressed.update((stem, meta.slug))
        return
    page = Page(meta=meta, path=entry.path, rel=rel, body=body, links=_extract_links(body))
    tree.parsed_pages.append(page)
    # slug가 겹치면 rel 정렬에서 앞선 파일만 등록한다(뒤 파일의 E3는 `_lint_tree`가 보고).
    tree.pages.setdefault(meta.slug, page)


# --- lint 규칙(E3~E11, W1~W5) ---


def _lint_tree(tree: _Tree, profile: CompanyProfile | None) -> None:
    """`tree.errors`·`tree.warnings`에 이슈를 더한다. 정렬은 `_build`가 한다.

    페이지 단위 규칙은 E1·E2를 통과한 모든 페이지(E3 뒤 파일 포함)에, W1·W4는 등록된
    페이지에만 적용한다.
    """
    category_slugs = {s for s, p in tree.pages.items() if p.meta.kind == "category"}
    profile_ids = None if profile is None else {item.id for item in profile.portfolio}
    seen_slugs: dict[str, str] = {}
    seen_titles: dict[str, str] = {}
    for page in tree.parsed_pages:
        _check_duplicates(page, seen_slugs, seen_titles, tree)
        _check_page(page, tree, category_slugs, profile_ids)
    _check_fallback(tree)
    _check_index(tree)
    _check_registered(tree)
    tree.errors.extend((rel, 11, f"{rel}: unexpected markdown file") for rel in tree.unexpected)


def _check_duplicates(
    page: Page, seen_slugs: dict[str, str], seen_titles: dict[str, str], tree: _Tree
) -> None:
    """E3. rel 정렬에서 뒤에 오는 파일에 보고하고 (also …)는 처음 나온 파일을 가리킨다."""
    rel, meta = page.rel, page.meta
    first = seen_slugs.setdefault(meta.slug, rel)
    if first != rel:
        tree.errors.append((rel, 3, f"{rel}: duplicate slug '{meta.slug}' (also {first})"))
    first = seen_titles.setdefault(meta.title.strip(), rel)
    if first != rel:
        tree.errors.append((rel, 3, f"{rel}: duplicate title '{meta.title}' (also {first})"))


def _check_page(
    page: Page, tree: _Tree, category_slugs: set[str], profile_ids: set[str] | None
) -> None:
    """페이지 하나로 판정하는 규칙: E4, E6, E8, E9, E10, W2, W3, W5."""
    rel, meta = page.rel, page.meta
    errors, warnings = tree.errors, tree.warnings
    if meta.kind != _expected_kind(rel):
        folder = PurePosixPath(rel).parent.as_posix()  # 루트 glossary.md → "."
        errors.append((rel, 4, f"{rel}: kind '{meta.kind}' not allowed in '{folder}/'"))
    for link in page.links:
        if link not in tree.pages and link not in tree.suppressed:
            errors.append((rel, 6, f"{rel}: broken link [[{link}]]"))
    for value in dict.fromkeys(meta.categories):
        known = value == meta.slug if meta.kind == "category" else value in category_slugs
        if not known:
            errors.append((rel, 8, f"{rel}: unknown category '{value}'"))
    for name, kind in KIND_ONLY_FIELDS:
        if name in meta.model_fields_set and meta.kind != kind:
            errors.append((rel, 9, f"{rel}: field '{name}' only allowed for kind {kind}"))
    if meta.kind == "portfolio":
        errors.extend((rel, 10, msg) for msg in _portfolio_issues(page, profile_ids))
    if meta.kind == "category":
        got = [m.group(1).strip() for m in SECTION_RE.finditer(page.body)]
        if got != list(CATEGORY_SECTIONS):
            expected = ", ".join(CATEGORY_SECTIONS)
            msg = f"{rel}: category sections differ: expected [{expected}] got [{', '.join(got)}]"
            warnings.append((rel, 2, msg))
    limit = CATEGORY_PAGE_MAX_CHARS if meta.kind == "category" else PAGE_MAX_CHARS
    if len(page.body) > limit:
        warnings.append((rel, 3, f"{rel}: body {len(page.body)} chars > {limit}"))
    if meta.confidence == "confirmed" and not meta.sources:
        warnings.append((rel, 5, f"{rel}: confirmed without sources"))


def _portfolio_issues(page: Page, profile_ids: set[str] | None) -> list[str]:
    """E10 메시지들(kind portfolio 페이지). 프로필이 없으면 실적 존재 검사는 생략한다."""
    rel, slug, pid = page.rel, page.meta.slug, page.meta.portfolio_id
    if pid is None:
        return [f"{rel}: portfolio_id required for kind portfolio"]
    issues = []
    if pid != slug:
        issues.append(f"{rel}: portfolio_id '{pid}' != slug '{slug}'")
    if profile_ids is not None and pid not in profile_ids:
        issues.append(f"{rel}: portfolio_id '{pid}' not in profile portfolio")
    return issues


def _check_fallback(tree: _Tree) -> None:
    """E5. 등록된 `other` 페이지가 있고 kind가 category여야 한다."""
    page = tree.pages.get(FALLBACK_CATEGORY)
    if page is None or page.meta.kind != "category":
        rel = f"categories/{FALLBACK_CATEGORY}.md"
        tree.errors.append((rel, 5, f"{rel}: fallback category missing"))


def _check_index(tree: _Tree) -> None:
    """E7. 등재 누락은 등록 순(rel), 미지 항목은 INDEX 등장 순. 읽기 실패한 INDEX는 E1만."""
    if tree.index_unreadable:
        return
    if not tree.index_present:
        tree.errors.append((INDEX_FILE, 7, f"{INDEX_FILE}: missing"))
        return
    listed = set(tree.index_slugs)
    for slug in tree.pages:
        if slug not in listed:
            tree.errors.append((INDEX_FILE, 7, f"{INDEX_FILE}: page not listed: {slug}"))
    for slug in tree.index_slugs:
        if slug not in tree.pages and slug not in tree.suppressed:
            tree.errors.append((INDEX_FILE, 7, f"{INDEX_FILE}: unknown page [[{slug}]]"))


def _check_registered(tree: _Tree) -> None:
    """등록된 페이지만 보는 경고: W1(고아, 자기 링크 제외), W4(단일 카테고리 선택 예산)."""
    inbound = {
        link for page in tree.pages.values() for link in page.links if link != page.meta.slug
    }
    for slug, page in tree.pages.items():
        if page.meta.kind in ("category", "glossary") or slug in inbound:
            continue
        tree.warnings.append((page.rel, 1, f"{page.rel}: orphan page (no inbound [[link]])"))
    for slug, page in tree.pages.items():
        if page.meta.kind != "category":
            continue
        plan = _plan_selection(tree.pages, [slug], "keyword", KNOWLEDGE_BUDGET_CHARS)
        if plan.skipped:
            msg = f"{page.rel}: selection would skip: {', '.join(plan.skipped)}"
            tree.warnings.append((page.rel, 4, msg))


# --- lint 규칙(E13~E15, KB-02): `<root>/past.yaml`. 파일이 없으면 검사하지 않는다 ---


def _lint_past_labels(root: Path, tree: _Tree, profile: CompanyProfile | None) -> None:
    path = root / PAST_LABELS_FILE
    if not path.exists():
        return
    rel = PAST_LABELS_FILE
    try:
        labels = parse_past_labels(read_past_labels_text(path))
    except PastLabelsError as exc:
        tree.errors.extend((rel, 13, f"{rel}: {line}") for line in exc.errors)
        return
    category_slugs = {s for s, p in tree.pages.items() if p.meta.kind == "category"}
    profile_ids = None if profile is None else {item.id for item in profile.portfolio}
    for slug, label in labels.notices.items():
        expected = portfolio_id_of(slug)
        if label.portfolio_id != expected:
            msg = f"{rel}: {slug}: portfolio_id '{label.portfolio_id}' != slug id '{expected}'"
            tree.errors.append((rel, 14, msg))
        if profile_ids is not None and label.portfolio_id not in profile_ids:
            msg = f"{rel}: {slug}: portfolio_id '{label.portfolio_id}' not in profile portfolio"
            tree.errors.append((rel, 14, msg))
    for slug, label in labels.notices.items():
        for value in label.categories:
            if value not in category_slugs:
                tree.errors.append((rel, 15, f"{rel}: {slug}: unknown category '{value}'"))


# --- 선택·렌더링 공용 함수(W4·select_pages·render_knowledge가 같은 계산을 쓴다) ---

_SEP = "\n\n"  # 머리글·블록 사이 구분(빈 줄 하나)
_RULE_LINE = (
    '- 규칙: 아래는 회사가 작성한 설명 페이지다. "(확인 필요)" 표기와 confidence가 '
    'unknown·estimate인 페이지의 값은 프로필 "unknown"과 같이 다룬다(추정 금지). '
    "근거로 쓴 페이지는 [[slug]]로 가리킨다."
)


def _render_header(categories: list[str], source: str) -> str:
    """렌더링 머리글 두 줄(끝 개행 없음). 제목 줄은 넣지 않는다."""
    return f"- 공고 유형: {', '.join(categories)}({source})\n{_RULE_LINE}"


def _demote_headings(body: str) -> str:
    """`^(#{1,4}) `로 시작하는 줄 앞에 `##`를 붙인다(`## 강점` → `#### 강점`)."""
    return HEADING_DEMOTE_RE.sub("##", body)


def _render_block(page: Page) -> str:
    """페이지 블록(`### …`부터 본문 끝까지, 끝 개행 없음). 본문이 비면 메타 줄에서 끝난다."""
    meta = page.meta
    head = (
        f"### [[{meta.slug}]] {meta.title}\n"
        f"- kind: {meta.kind} · confidence: {meta.confidence} · updated: {meta.updated or '-'}"
    )
    body = _demote_headings(page.body)
    return f"{head}\n{body}" if body else head


@dataclass(frozen=True)
class _SelectionPlan:
    pages: list[str]  # 포함 slug, 렌더링 순서
    skipped: list[str]  # 예산 때문에 빠진 slug
    chars: int  # 머리글 + Σ(_SEP + 블록) = 렌더링 결과 길이


def _plan_selection(
    pages: dict[str, Page],
    categories: list[str],
    source: str,
    budget_chars: int,
    *,
    related: list[str] | None = None,
    portfolio_budget_chars: int = PORTFOLIO_BUDGET_CHARS,
) -> _SelectionPlan:
    """spec "선택" 절의 그리디. categories는 등록된 category slug여야 한다(호출자가 검증).

    1) category 페이지를 순서대로 예산과 무관하게 넣고 2) 각 category의 links 순으로 depth-1
    후보(category·portfolio kind·이미 들어간 slug·트리에 없는 대상 제외) 3) 마지막에 glossary
    kind 페이지(아직 없으면) 4) 후보마다 `running + len(_SEP + block) <= budget_chars`면 포함,
    아니면 skipped에 넣고 계속. `running`은 머리글 길이 + 포함된 category 블록(각 `_SEP` 포함).
    5) `related`(관련 실적 slug, 순위 순)를 별도 예산으로 같은 그리디에 넣는다. 실적 누계는
    `len(_SEP + block)`의 합이고 `portfolio_budget_chars` 이하일 때만 포함한다.
    """
    included: list[str] = []
    running = len(_render_header(categories, source))
    for slug in categories:
        if slug in included:
            continue
        included.append(slug)
        running += len(_SEP) + len(_render_block(pages[slug]))
    candidates: list[str] = []
    for slug in categories:
        for link in pages[slug].links:
            target = pages.get(link)
            if target is None or target.meta.kind in ("category", "portfolio"):
                continue
            if link not in included and link not in candidates:
                candidates.append(link)
    glossary = next((s for s, p in pages.items() if p.meta.kind == ROOT_PAGE_KIND), None)
    if glossary is not None and glossary not in included and glossary not in candidates:
        candidates.append(glossary)
    skipped: list[str] = []
    for slug in candidates:
        cost = len(_SEP) + len(_render_block(pages[slug]))
        if running + cost <= budget_chars:
            included.append(slug)
            running += cost
        else:
            skipped.append(slug)
    portfolio_running = 0
    for slug in related or []:
        page = pages.get(slug)
        if page is None or page.meta.kind != "portfolio" or slug in included:
            continue
        cost = len(_SEP) + len(_render_block(page))
        if portfolio_running + cost <= portfolio_budget_chars:
            included.append(slug)
            portfolio_running += cost
        else:
            skipped.append(slug)
    return _SelectionPlan(pages=included, skipped=skipped, chars=running + portfolio_running)


# --- 페이지 파싱 ---


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def _extract_links(text: str) -> list[str]:
    """위키링크 대상 slug를 등장 순서대로, 중복 없이."""
    return list(dict.fromkeys(m.group(1).strip() for m in WIKILINK_RE.finditer(text)))


def _split_frontmatter(text: str) -> tuple[str, str] | None:
    """(frontmatter 원문, 본문). `---` 시작 줄과 닫는 `---` 줄이 모두 있어야 한다."""
    normalized = _normalize_newlines(text)
    if not normalized.startswith("---\n"):
        return None
    lines = normalized[len("---\n") :].split("\n")
    for idx, line in enumerate(lines):
        if line == "---":
            return "\n".join(lines[:idx]), "\n".join(lines[idx + 1 :]).rstrip()
    return None


def _parse_page(
    text: str,
) -> str | tuple[PageMeta | list[str], str, str | None]:
    """E1 사유 문자열, 또는 (PageMeta | 검증 오류 줄들, 본문, frontmatter의 slug 원문)."""
    split = _split_frontmatter(text)
    if split is None:
        return "missing frontmatter"
    raw_front, body = split
    try:
        raw = yaml.safe_load(raw_front)
    except yaml.YAMLError as exc:
        return f"yaml parse error: {' '.join(str(exc).split())}"
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        return "frontmatter must be a mapping"
    data = _dates_to_str(raw)
    raw_slug = data.get("slug") if isinstance(data.get("slug"), str) else None
    try:
        return PageMeta.model_validate(data), body, raw_slug
    except ValidationError as exc:
        return _format_errors(exc.errors(include_url=False), data), body, raw_slug


def _dates_to_str(value: Any) -> Any:
    """PyYAML이 따옴표 없는 YYYY-MM-DD를 date로 읽으므로 검증 전에 문자열로 바꾼다."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {_dates_to_str(k): _dates_to_str(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dates_to_str(v) for v in value]
    return value


# --- pydantic 오류 → `<필드 경로>: <msg>` 줄 ---


def _format_errors(errs: list[dict[str, Any]], data: dict) -> list[str]:
    """경로당 한 줄(첫 메시지). union 분기 태그는 경로에서 빼고, 엉뚱한 분기의 오류는 버린다."""
    lines: dict[str, str] = {}
    for err in errs:
        located = _locate(err, data)
        if located is None:
            continue
        lines.setdefault(located, err["msg"])
    return [f"{path}: {msg}" if path else msg for path, msg in lines.items()]


def _locate(err: dict[str, Any], data: Any) -> str | None:
    """오류의 출력 경로. 데이터에 없는 loc 조각은 union 분기 태그로 보고 경로에서 뺀다.

    `keywords: list[str | Keyword]`에서 항목이 매핑이면 `str` 분기 오류를, 매핑이 아니면
    `Keyword` 분기 오류를 버려(None) 항목 모양에 맞는 분기의 오류만 남긴다.
    """
    loc = err["loc"]
    node = data
    path = ""
    for pos, el in enumerate(loc):
        if isinstance(node, list) and type(el) is int and 0 <= el < len(node):
            path += f"[#{el}]"
            node = node[el]
        elif isinstance(node, dict) and el in node:
            path += f".{el}" if path else str(el)
            node = node[el]
        elif err["type"] == "missing" and pos == len(loc) - 1:
            path += f".{el}" if path else str(el)
        elif el == "str" and isinstance(node, dict):
            return None
        elif el == "Keyword" and not isinstance(node, dict):
            return None
        # 그 밖의 문자열은 union 분기 태그(constrained-str, none 등): 경로에서 뺀다.
    return path
