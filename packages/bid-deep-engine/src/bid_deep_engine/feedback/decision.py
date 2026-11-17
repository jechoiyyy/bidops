"""담당자 판단 기록 `out/<slug>/decision.yaml`(spec M2-06).

`{current, history}` 구조. 새 결정은 history 끝에 추가하고 기존 항목은 바꾸지 않는다. 결정 값
타입은 `bid_deep_engine.analysis.schemas.DecisionValue`가 단일 출처다(계약 시트 13절 X24). 이 모듈은
`bid_deep_engine.config`·llm·pipeline을 import하지 않는다(decide는 .env·키를 읽지 않는다).
"""

import contextlib
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError, field_validator, model_validator

from bid_deep_engine.analysis.schemas import DecisionValue

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DECIDED_AT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
DECISION_FILE = "decision.yaml"


class DecisionFileError(Exception):
    """decision.yaml 파싱·검증 실패. 메시지는 `<경로>: <첫 오류>` 한 줄."""


class Decision(BaseModel):
    """사람의 판단 기록 1건. 필드 순서가 YAML 키 순서다."""

    slug: str
    decision: DecisionValue
    reason: str
    decided_by: str
    decided_at: str

    @field_validator("slug")
    @classmethod
    def _slug_format(cls, value: str) -> str:
        if not SLUG_PATTERN.fullmatch(value):
            raise ValueError(f"invalid slug: {value}")
        return value

    @field_validator("reason", "decided_by")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value

    @field_validator("decided_at")
    @classmethod
    def _decided_at_format(cls, value: str) -> str:
        if not DECIDED_AT_PATTERN.fullmatch(value):
            raise ValueError(f"decided_at must be ISO 8601 with offset, got {value!r}")
        return value


class DecisionFile(BaseModel):
    current: Decision
    history: list[Decision]

    @model_validator(mode="after")
    def _history_ends_with_current(self) -> "DecisionFile":
        if not self.history:
            raise ValueError("history must have at least 1 entry")
        if self.history[-1] != self.current:
            raise ValueError("history[-1] must equal current")
        return self


def decision_path(out_dir: Path, slug: str) -> Path:
    return out_dir / slug / DECISION_FILE


def now_local(now: datetime | None = None) -> str:
    """로컬 시간대 오프셋을 붙인 ISO 8601 초 단위 시각."""
    return (now or datetime.now()).astimezone().replace(microsecond=0).isoformat()


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err["loc"])
    msg = str(err["msg"]).splitlines()[0] if err["msg"] else ""
    return f"{loc}: {msg}" if loc else msg


def _plain_decided_at(entry: Any) -> None:
    """따옴표 없이 고쳐 datetime·date로 읽힌 `decided_at`을 문자열로 되돌린다(제자리 변경)."""
    if not isinstance(entry, dict):
        return
    value = entry.get("decided_at")
    if isinstance(value, datetime):
        entry["decided_at"] = value.isoformat(timespec="seconds")
    elif isinstance(value, date):
        entry["decided_at"] = value.isoformat()


def load_decision(path: Path) -> DecisionFile | None:
    """파일이 없으면 None, 읽기·파싱·검증 실패는 `DecisionFileError`."""
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, ValueError) as exc:  # ValueError ⊃ UnicodeDecodeError
        first = str(exc).strip().splitlines()
        detail = first[0].strip() if first else type(exc).__name__
        raise DecisionFileError(f"{path}: cannot read ({type(exc).__name__}: {detail})") from exc
    if not isinstance(data, dict):
        raise DecisionFileError(f"{path}: top level must be a mapping with 'current' and 'history'")
    _plain_decided_at(data.get("current"))
    history = data.get("history")
    if isinstance(history, list):
        for entry in history:
            _plain_decided_at(entry)
    try:
        return DecisionFile.model_validate(data)
    except ValidationError as exc:
        raise DecisionFileError(f"{path}: {_first_error(exc)}") from exc


def write_atomic(path: Path, text: str) -> None:
    """같은 디렉터리의 임시 파일에 쓴 뒤 `os.replace`로 교체한다."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def record_decision(
    out_dir: Path,
    slug: str,
    decision: DecisionValue,
    reason: str,
    decided_by: str,
    *,
    now: datetime | None = None,
) -> DecisionFile:
    """새 결정을 history 끝에 추가하고 current를 교체해 저장한다.

    기존 파일이 깨져 있으면 `DecisionFileError`를 올리고 파일을 그대로 둔다. 입력 검증 오류는
    pydantic `ValidationError`(ValueError)로 올라온다.
    """
    new = Decision(
        slug=slug,
        decision=decision,
        reason=reason,
        decided_by=decided_by,
        decided_at=now_local(now),
    )
    path = decision_path(out_dir, slug)
    existing = load_decision(path)
    history = [*existing.history, new] if existing is not None else [new]
    doc = DecisionFile(current=new, history=history)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        doc.model_dump(), allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    write_atomic(path, text)
    return doc
