"""게이트 사람 확인 기록 `out/<slug>/gate_confirmations.yaml`(spec GT-01).

`{confirmations: [...]}` 목록이고 이력은 없다(같은 키는 교체). 신규 키는
`(rfp_hash, rule_hash)`, legacy 키는 `norm_compact(rule_text)`이며 파일 안에서 유일하다. `code`와
`rule_text`는 표시·감사용이고 신규 적용 키로 쓰지 않는다.

적용은 현재 RFP hash와 GateResult.rule_hash가 모두 맞는 게이트 하나에만 하고, 그 게이트가
UNKNOWN이고 `unknown_fields`가 비어 있을 때만 판정을 바꾼다. 범위가 없거나 달라진 기록은
보존하면서 outdated로 알리고, 프로필 경로가 있는 UNKNOWN은 프로필을 채우는 것이 정답이라
무시하고 경고한다(제약 2).

이 모듈은 `bid_deep_engine.analysis.schemas`·`bid_deep_engine.analysis.gates`·`bid_deep_engine.feedback.decision`만
import한다(`bid_deep_engine.config`·llm·pipeline·subprocess 없음).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ValidationError, field_validator, model_validator

from bid_deep_engine.analysis.gates import FAIL_ACTION, norm_compact
from bid_deep_engine.analysis.schemas import GateCode, GateResult
from bid_deep_engine.feedback.decision import DECIDED_AT_PATTERN, now_local, write_atomic

__all__ = [
    "GATE_CONFIRMATIONS_FILE",
    "ConfirmedVerdict",
    "GateConfirmation",
    "GateConfirmationError",
    "GateConfirmationFile",
    "ConfirmationResolution",
    "apply_confirmations",
    "clear_confirmation",
    "confirmations_path",
    "load_confirmations",
    "now_local",
    "record_confirmation",
    "resolve_confirmations",
]

GATE_CONFIRMATIONS_FILE = "gate_confirmations.yaml"
ConfirmedVerdict = Literal["PASS", "FAIL"]
WARN_TEXT_CHARS = 40  # 경고 문구에 넣는 rule_text 앞 글자 수
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class GateConfirmationError(Exception):
    """gate_confirmations.yaml 읽기·파싱·검증 실패. 메시지는 `<경로>: <첫 오류>` 한 줄."""


class GateConfirmation(BaseModel):
    """게이트 하나에 대한 사람 확인 1건. 필드 순서가 YAML 키 순서다."""

    code: GateCode
    rule_text: str
    rfp_hash: str | None = None
    rule_hash: str | None = None
    verdict: ConfirmedVerdict
    reason: str
    confirmed_by: str
    confirmed_at: str

    @field_validator("rule_text", "reason", "confirmed_by")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value

    @field_validator("rfp_hash", "rule_hash")
    @classmethod
    def _hash_is_lower_hex(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_RE.fullmatch(value):
            raise ValueError("must be 64 lowercase hex characters")
        return value

    @field_validator("confirmed_at")
    @classmethod
    def _confirmed_at_format(cls, value: str) -> str:
        if not DECIDED_AT_PATTERN.fullmatch(value):
            raise ValueError(f"confirmed_at must be ISO 8601 with offset, got {value!r}")
        return value


def _key(
    rule_text: str, rfp_hash: str | None = None, rule_hash: str | None = None
) -> tuple[str, ...]:
    """새 기록은 원문+판정 scope, legacy는 기존 rule_text key를 보존한다."""
    if rfp_hash is not None and rule_hash is not None:
        return ("scoped", rfp_hash, rule_hash)
    return ("legacy", norm_compact(rule_text))


def _confirmation_key(item: GateConfirmation) -> tuple[str, ...]:
    return _key(item.rule_text, item.rfp_hash, item.rule_hash)


class GateConfirmationFile(BaseModel):
    confirmations: list[GateConfirmation]

    @model_validator(mode="after")
    def _unique_keys(self) -> "GateConfirmationFile":
        seen: dict[tuple[str, ...], int] = {}
        for i, item in enumerate(self.confirmations):
            key = _confirmation_key(item)
            if key in seen:
                dup = f"confirmations[{i}] repeats confirmations[{seen[key]}]"
                raise ValueError(f"duplicate rule_text key: {dup}")
            seen[key] = i
        return self


def confirmations_path(out_dir: Path, slug: str) -> Path:
    return out_dir / slug / GATE_CONFIRMATIONS_FILE


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err["loc"])
    msg = str(err["msg"]).splitlines()[0] if err["msg"] else ""
    return f"{loc}: {msg}" if loc else msg


def _plain_confirmed_at(entry: Any) -> None:
    """따옴표 없이 고쳐 datetime·date로 읽힌 `confirmed_at`을 문자열로 되돌린다(제자리 변경)."""
    if not isinstance(entry, dict):
        return
    value = entry.get("confirmed_at")
    if isinstance(value, datetime):
        entry["confirmed_at"] = value.isoformat(timespec="seconds")
    elif isinstance(value, date):
        entry["confirmed_at"] = value.isoformat()


def load_confirmations(path: Path) -> GateConfirmationFile | None:
    """파일이 없으면 None, 읽기·파싱·검증 실패는 `GateConfirmationError`."""
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, ValueError) as exc:  # ValueError ⊃ UnicodeDecodeError
        first = str(exc).strip().splitlines()
        detail = first[0].strip() if first else type(exc).__name__
        raise GateConfirmationError(
            f"{path}: cannot read ({type(exc).__name__}: {detail})"
        ) from exc
    if not isinstance(data, dict):
        raise GateConfirmationError(f"{path}: top level must be a mapping with 'confirmations'")
    items = data.get("confirmations")
    if isinstance(items, list):
        for entry in items:
            _plain_confirmed_at(entry)
    try:
        return GateConfirmationFile.model_validate(data)
    except ValidationError as exc:
        raise GateConfirmationError(f"{path}: {_first_error(exc)}") from exc


def _save(path: Path, doc: GateConfirmationFile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        doc.model_dump(exclude_none=True),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    write_atomic(path, text)


def record_confirmation(
    out_dir: Path, slug: str, confirmation: GateConfirmation
) -> GateConfirmationFile:
    """같은 키의 기록을 제자리에서 교체하고, 없으면 끝에 추가해 저장한다.

    기존 파일이 깨져 있으면 `GateConfirmationError`를 올리고 파일을 그대로 둔다.
    """
    path = confirmations_path(out_dir, slug)
    existing = load_confirmations(path)
    items = list(existing.confirmations) if existing is not None else []
    key = _confirmation_key(confirmation)
    for i, item in enumerate(items):
        if _confirmation_key(item) == key:
            items[i] = confirmation
            break
    else:
        items.append(confirmation)
    doc = GateConfirmationFile(confirmations=items)
    _save(path, doc)
    return doc


def clear_confirmation(
    out_dir: Path,
    slug: str,
    rule_text: str,
    *,
    rfp_hash: str | None = None,
    rule_hash: str | None = None,
) -> GateConfirmationFile | None:
    """키가 일치하는 기록을 지우고 저장한다. 파일이 없거나 키가 없으면 None(저장하지 않음).

    기존 파일이 깨져 있으면 `GateConfirmationError`를 올리고 파일을 그대로 둔다.
    """
    path = confirmations_path(out_dir, slug)
    existing = load_confirmations(path)
    if existing is None:
        return None
    key = _key(rule_text, rfp_hash, rule_hash)
    kept = [item for item in existing.confirmations if _confirmation_key(item) != key]
    # Explicit clear remains able to remove one legacy entry after scoped IDs were introduced.
    if len(kept) == len(existing.confirmations) and rfp_hash is not None and rule_hash is not None:
        legacy_key = _key(rule_text)
        kept = [item for item in existing.confirmations if _confirmation_key(item) != legacy_key]
    if len(kept) == len(existing.confirmations):
        return None
    doc = GateConfirmationFile(confirmations=kept)
    _save(path, doc)
    return doc


@dataclass(frozen=True)
class ConfirmationResolution:
    gates: list[GateResult]
    warnings: list[str]
    applicable: list[GateConfirmation]
    outdated: list[tuple[GateCode, str | None]]


def resolve_confirmations(
    gates: Sequence[GateResult],
    confirmations: Sequence[GateConfirmation],
    *,
    rfp_hash: str | None,
) -> ConfirmationResolution:
    """현재 RFP와 rule hash가 모두 맞는 확인만 적용하고 범위 밖 기록은 보존한다."""
    result = list(gates)
    warnings: list[str] = []
    applicable: list[GateConfirmation] = []
    outdated: list[tuple[GateCode, str | None]] = []
    for conf in confirmations:
        text = conf.rule_text[:WARN_TEXT_CHARS]
        scoped = rfp_hash is not None and conf.rfp_hash == rfp_hash and conf.rule_hash is not None
        matches = (
            [i for i, gate in enumerate(result) if gate.rule_hash == conf.rule_hash]
            if scoped
            else []
        )
        if not scoped or not matches:
            stable = next(
                (
                    (gate.code, gate.rule_hash)
                    for gate in result
                    if conf.rule_hash is not None and gate.rule_hash == conf.rule_hash
                ),
                None,
            )
            outdated.append(stable or (conf.code, None))
            warnings.append(f"gate confirmation outdated: {conf.code} {text}")
            continue
        first = result[matches[0]]
        if len(matches) > 1:
            warnings.append(f"gate confirmation ambiguous: {first.code} {text}")
            continue
        if first.verdict != "UNKNOWN" or first.unknown_fields:
            fields = ", profile fields" if first.unknown_fields else ""
            warnings.append(
                f"gate confirmation ignored ({first.verdict}{fields}): {first.code} {text}"
            )
            continue
        applicable.append(conf)
        result[matches[0]] = first.model_copy(
            update={
                "verdict": conf.verdict,
                "company_value": (
                    f"사람 확인 {conf.verdict}: {conf.reason} "
                    f"({conf.confirmed_by}, {conf.confirmed_at[:10]})"
                ),
                "action": None if conf.verdict == "PASS" else FAIL_ACTION,
                "unknown_fields": [],
            }
        )
    return ConfirmationResolution(result, warnings, applicable, outdated)


def apply_confirmations(
    gates: Sequence[GateResult],
    confirmations: Sequence[GateConfirmation],
    *,
    rfp_hash: str | None,
) -> tuple[list[GateResult], list[str]]:
    """호환 wrapper. 적용 입력 hash가 필요한 호출자는 resolve_confirmations를 쓴다."""
    resolution = resolve_confirmations(gates, confirmations, rfp_hash=rfp_hash)
    return resolution.gates, resolution.warnings
