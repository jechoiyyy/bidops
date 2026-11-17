"""과거 공고 라벨 파일 `company/knowledge/past.yaml`(KB-02 `PastLabels`).

- 사람이 매긴 카테고리 라벨: 과거 나라장터 공고 slug(`past-p<연도>-<순번>`)
  → 실적 ID·카테고리·공고번호.
- ingest manifest(`notices.past.yaml`)와 분리한다
  (`ManifestEntry`가 extra 금지라 라벨을 넣을 수 없다).
- 이 모듈은 파일만 읽는다(네트워크·서브프로세스 없음). 카테고리 slug가 실제 category 페이지인지,
  실적 ID가 프로필에 있는지는 `knowledge.lint_knowledge`의 E14·E15가 검사한다.
"""

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

PAST_LABELS_FILE = "past.yaml"
PAST_SLUG_PATTERN = r"^past-p\d{4}-\d{2}$"
PAST_PORTFOLIO_ID_PATTERN = r"^P\d{4}-\d{2}$"
MAX_LABEL_CATEGORIES = 2

PAST_SLUG_RE = re.compile(PAST_SLUG_PATTERN)

PastSlug = Annotated[str, StringConstraints(pattern=PAST_SLUG_PATTERN)]
PastPortfolioId = Annotated[str, StringConstraints(pattern=PAST_PORTFOLIO_ID_PATTERN)]

_CONFIG = ConfigDict(extra="forbid", strict=True)


class PastLabel(BaseModel):
    model_config = _CONFIG

    portfolio_id: PastPortfolioId
    categories: list[str] = Field(min_length=1, max_length=MAX_LABEL_CATEGORIES)  # 순서 = 주·부
    g2b_no: str  # 나라장터 공고번호(출처 표기용 문자열)
    note: str | None = None

    @field_validator("categories")
    @classmethod
    def _no_duplicate_categories(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("categories must not contain duplicates")
        return value

    @field_validator("g2b_no")
    @classmethod
    def _g2b_no_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("g2b_no must not be blank")
        return value


class PastLabels(BaseModel):
    model_config = _CONFIG

    schema_version: Literal[1]
    notices: dict[PastSlug, PastLabel]


class PastLabelsError(Exception):
    """load_past_labels 실패. errors는 `lint_knowledge` E13이 `past.yaml: ` 뒤에 붙이는 문구."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def portfolio_id_of(slug: str) -> str:
    """`past-p2025-04` → `P2025-04`. slug 형식이 아니면 ValueError."""
    if not PAST_SLUG_RE.match(slug):
        raise ValueError(f"not a past slug: {slug!r}")
    return slug.removeprefix("past-").upper()


def parse_past_labels(text: str) -> PastLabels:
    """YAML 텍스트 → PastLabels. 실패하면 PastLabelsError(줄 목록)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PastLabelsError([f"yaml parse error: {' '.join(str(exc).split())}"]) from exc
    if not isinstance(data, dict):
        raise PastLabelsError(["yaml parse error: top level must be a mapping"])
    try:
        return PastLabels.model_validate(data)
    except ValidationError as exc:
        raise PastLabelsError(_format_errors(exc.errors(include_url=False))) from exc


def read_past_labels_text(path: Path) -> str:
    """파일 읽기. 실패하면 PastLabelsError(`cannot read file: ...`)."""
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PastLabelsError([f"cannot read file: {' '.join(str(exc).split())}"]) from exc


def load_past_labels(path: Path) -> PastLabels:
    """라벨 파일을 읽는다. 파일이 없으면 빈 라벨, 오류면 PastLabelsError."""
    path = Path(path)
    if not path.exists():
        return PastLabels(schema_version=1, notices={})
    return parse_past_labels(read_past_labels_text(path))


def _format_errors(errs: list[dict[str, Any]]) -> list[str]:
    """경로당 한 줄(첫 메시지): `notices.<slug>.categories: <msg>`, 목록 항목은 `[#i]`."""
    lines: dict[str, str] = {}
    for err in errs:
        path = ""
        for el in err["loc"]:
            if el == "[key]":  # dict 키 검증 오류: 경로는 키 자체까지
                continue
            if isinstance(el, int):
                path += f"[#{el}]"
            else:
                path += f".{el}" if path else str(el)
        lines.setdefault(path, err["msg"])
    return [f"{path}: {msg}" if path else msg for path, msg in lines.items()]
