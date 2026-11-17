"""회사 프로필 출처 메타데이터와 판정용 읽기 뷰.

프로필의 원값과 기존 profile_hash 입력은 건드리지 않는다. 별도 sidecar에서 출처 수준을
읽고, value_hash가 현재 값을 가리킬 때만 그 메타데이터를 유효하게 취급한다.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from bid_deep_engine.company.schema import LIST_ID_KEYS, UNKNOWN, CompanyProfile

ProvenanceLevel = Literal["confirmed", "public", "estimate", "demo", "unknown"]
SourceKind = Literal["user", "document", "website", "comment"]

# 확정 권고 기본 뷰가 수용하는 출처 수준. demo(MVP 데모 임의값)는 판정에서 확인값과 같이 쓴다
# (2026-10-25 결정). demo 표지·level은 실제 운영 전 교체 대상을 추적하려고 그대로 둔다.
CONFIRMED_LEVELS: frozenset[ProvenanceLevel] = frozenset({"confirmed", "demo"})
# 판정 계층이 확인값과 같이 다루는 수준(신뢰 FAIL·최소계약금액·확인 요청 제외·조건 경로 판단).
DECISION_LEVELS: frozenset[str] = frozenset(CONFIRMED_LEVELS)
# 잠정 결론(PF-01)의 가정 뷰가 수용하는 출처 수준(고정). unknown은 어떤 뷰도 수용하지 않는다.
ASSUMED_LEVELS: frozenset[ProvenanceLevel] = frozenset({"confirmed", "demo", "public", "estimate"})
_NEVER_ACCEPTED_LEVELS: frozenset[str] = frozenset({"unknown"})
_ACCEPTABLE_LEVELS: frozenset[str] = frozenset({"confirmed", "demo", "public", "estimate"})

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CHECKED_AT_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_ENCODED_TOKEN_RE = re.compile(r"(?:[A-Za-z0-9_-]|%[0-9A-F]{2})+")
_SAFE_BYTES = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProvenanceSource(_StrictModel):
    kind: SourceKind
    ref: str


class ProvenanceEntry(_StrictModel):
    level: ProvenanceLevel
    sources: list[ProvenanceSource]
    value_hash: str
    checked_at: str | None
    note: str | None

    @field_validator("value_hash")
    @classmethod
    def _check_hash(cls, value: str) -> str:
        if not _HASH_RE.fullmatch(value):
            raise ValueError("value_hash must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("checked_at")
    @classmethod
    def _check_checked_at(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _CHECKED_AT_RE.fullmatch(value):
            raise ValueError("checked_at must be YYYY-MM-DD or null")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("checked_at must be a valid YYYY-MM-DD date or null") from exc
        return value

    @model_validator(mode="after")
    def _require_source_for_asserted_levels(self) -> ProvenanceEntry:
        if self.level in ("confirmed", "public") and not self.sources:
            raise ValueError(f"{self.level} provenance requires at least one source")
        return self


class ProvenanceDocument(_StrictModel):
    schema_version: Literal[1]
    fields: dict[str, ProvenanceEntry]

    @field_validator("schema_version", mode="before")
    @classmethod
    def _require_integer_schema_version(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("schema_version must be integer 1")
        return value

    def to_payload(self) -> dict[str, Any]:
        """Validated sidecar mapping, including every explicit field."""
        return self.model_dump(mode="json")


def encode_path_token(value: str) -> str:
    """UTF-8 percent encoding for one canonical path token."""
    pieces: list[str] = []
    for byte in value.encode("utf-8"):
        if byte in _SAFE_BYTES:
            pieces.append(chr(byte))
        else:
            pieces.append(f"%{byte:02X}")
    return "".join(pieces)


def decode_path_token(token: str) -> str:
    """Decode and enforce the canonical token spelling."""
    if not _ENCODED_TOKEN_RE.fullmatch(token):
        raise ValueError("path token is not canonical percent encoding")
    data = bytearray()
    pos = 0
    while pos < len(token):
        if token[pos] == "%":
            data.append(int(token[pos + 1 : pos + 3], 16))
            pos += 3
        else:
            data.append(ord(token[pos]))
            pos += 1
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("path token is not valid UTF-8") from exc
    if encode_path_token(decoded) != token:
        raise ValueError("path token is not canonical percent encoding")
    return decoded


def parse_canonical_path(path: str) -> list[tuple[str, str | None]]:
    """Parse a path into decoded field tokens and optional stable list identifiers."""
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty canonical path")
    result: list[tuple[str, str | None]] = []
    for raw_segment in path.split("."):
        if not raw_segment:
            raise ValueError("path contains an empty field token")
        if "[" in raw_segment or "]" in raw_segment:
            if raw_segment.count("[") != 1 or raw_segment.count("]") != 1:
                raise ValueError("path contains malformed list identifier syntax")
            start = raw_segment.index("[")
            if not raw_segment.endswith("]") or start == 0:
                raise ValueError("path contains malformed list identifier syntax")
            field_token = raw_segment[:start]
            id_token = raw_segment[start + 1 : -1]
            if not id_token:
                raise ValueError("path contains an empty list identifier")
            identifier = decode_path_token(id_token)
        else:
            field_token = raw_segment
            identifier = None
        result.append((decode_path_token(field_token), identifier))
    return result


def canonical_json(value: Any) -> str:
    """Serialize a JSON-compatible value using the provenance canonical form."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def value_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def resolve_profile_path(profile: CompanyProfile, path: str) -> Any:
    """Resolve one canonical path against the fully defaulted profile model."""
    parts = parse_canonical_path(path)
    current: Any = profile.model_dump(mode="json")
    field_path: list[str] = []

    for field, identifier in parts:
        if not isinstance(current, dict):
            raise ValueError(f"path does not exist: {path}")
        candidates = [
            key
            for key in current
            if (isinstance(key, str) and key == field) or (type(key) is int and str(key) == field)
        ]
        if len(candidates) != 1:
            raise ValueError(f"path does not exist: {path}")
        current = current[candidates[0]]
        field_path.append(field)

        if identifier is not None:
            list_path = ".".join(field_path)
            id_key = LIST_ID_KEYS.get(list_path)
            if id_key is None or not isinstance(current, list):
                raise ValueError(f"path has no stable list identifier: {path}")
            matches = [
                item
                for item in current
                if isinstance(item, dict) and item.get(id_key) == identifier
            ]
            if len(matches) != 1:
                raise ValueError(f"path does not identify exactly one list item: {path}")
            current = matches[0]

    return current


class CompanyEvidenceView:
    """Read-only view joining raw profile values with validated provenance metadata.

    `load_profile()` deliberately returns only CompanyProfile for legacy callers. Call
    `load_evidence_view()` when a caller needs source levels or decision-safe values.
    """

    def __init__(
        self,
        profile: CompanyProfile,
        provenance: ProvenanceDocument | None = None,
        warnings: tuple[str, ...] = (),
        *,
        accepted_levels: frozenset[ProvenanceLevel] = CONFIRMED_LEVELS,
    ) -> None:
        levels = frozenset(accepted_levels)
        rejected = sorted(level for level in levels if level not in _ACCEPTABLE_LEVELS)
        if rejected:
            # unknown(및 알 수 없는 수준)은 어떤 뷰도 판정 값으로 수용하지 않는다.
            raise ValueError(f"accepted_levels cannot include {rejected}")
        self.profile = profile
        self.provenance = provenance
        self.warnings = warnings
        self.accepted_levels: frozenset[ProvenanceLevel] = levels

    def accepts(self, level: object) -> bool:
        """Whether an effective provenance level may be used as a decision value in this view."""
        return level in self.accepted_levels

    def with_accepted_levels(self, levels: frozenset[ProvenanceLevel]) -> CompanyEvidenceView:
        """Same profile, provenance and warnings read under a different accepted-level set."""
        return CompanyEvidenceView(
            self.profile,
            self.provenance,
            self.warnings,
            accepted_levels=frozenset(levels),
        )

    @property
    def company_input_hash(self) -> str:
        return company_input_hash(self.profile, self.provenance)

    def get(self, path: str) -> dict[str, Any]:
        """Return raw value and provenance state for one canonical path."""
        value = resolve_profile_path(self.profile, path)
        entry = self.provenance.fields.get(path) if self.provenance is not None else None
        if entry is None:
            level = "unknown"
            sources: list[dict[str, str]] = []
            matches: bool | None = None
            effective_level = "unknown"
        else:
            matches = value_hash(value) == entry.value_hash
            level = entry.level
            sources = [source.model_dump(mode="json") for source in entry.sources]
            effective_level = level if matches else "unknown"
        if value == UNKNOWN:
            effective_level = "unknown"
        return {
            "value": value,
            "level": level,
            "effective_level": effective_level,
            "sources": sources,
            "value_hash_matches": matches,
        }

    def decision_value(self, path: str) -> Any:
        """Return only a current value at an accepted level; otherwise preserve UNKNOWN.

        The default view accepts confirmed and demo, so it returns current values at those levels.
        """
        result = self.get(path)
        if self.accepts(result["effective_level"]) and result["value"] != UNKNOWN:
            return result["value"]
        return UNKNOWN


def company_input_hash(
    profile: CompanyProfile,
    provenance: ProvenanceDocument | None = None,
) -> str:
    """Hash the canonical normalized profile and full sidecar, separately from profile_hash."""
    profile_payload = profile.model_dump(mode="json")
    profile_payload.pop("provenance_file", None)
    payload = {
        "schema_version": 1,
        "profile": profile_payload,
        "provenance": (
            provenance.to_payload()
            if provenance is not None
            else {"schema_version": 1, "fields": {}}
        ),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def format_validation_errors(exc: ValidationError) -> list[str]:
    """Render sidecar model errors in a stable one-line format."""
    lines: list[str] = []
    for error in exc.errors(include_url=False):
        loc = list(error["loc"])
        if len(loc) >= 2 and loc[0] == "fields" and isinstance(loc[1], str):
            path = f"provenance.fields[{loc[1]}]"
            rest = loc[2:]
        else:
            path = "provenance"
            rest = loc
        for part in rest:
            path += f"[{part}]" if isinstance(part, int) else f".{part}"
        message = " ".join(error["msg"].split())
        lines.append(f"{path}: {message}")
    return lines
