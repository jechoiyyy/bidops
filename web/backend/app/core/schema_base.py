"""여러 모듈이 함께 쓰는 요청·응답 기반 모델과 검증기 (명세 §4).

`schemas`는 `models`·`services`를 import하지 않고, 상수·검증기가 필요하면
core에서 가져온다(명세 §4). T7 3단계가 `app/schemas/__init__.py`를 해체하면서
lifecycle·screening이 함께 쓰던 기반 모델·타입 별칭·검증기를 여기로 옮겼다.
정의와 동작은 그대로다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    StringConstraints,
)

from .company_profile import PROFILE_PARSE_ERROR_CODES


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PageFilters(APIModel):
    run_id: str
    grade: str | None = None
    readiness: str | None = None
    focus: str | None = None
    sample_role: str | None = None
    attachment: Literal["any", "none", "manual"] = "any"
    q: str | None = None
    sort: Literal["deadline", "grade", "published"] = "deadline"
    limit: int
    offset: int


def _validate_profile_projection_binding_values(version: str, digest: str) -> None:
    prefix = "company-profile.sha256:"
    if (
        not version.startswith(prefix)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or version.removeprefix(prefix) != digest
    ):
        raise ValueError("profile projection version and digest must match")


def _validate_profile_error_codes(value: list[str]) -> list[str]:
    if any(code not in PROFILE_PARSE_ERROR_CODES for code in value):
        raise ValueError("profile error code is not registered")
    return value


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value


def _validate_clock_time(value: str) -> str:
    if len(value) != 5 or value[2] != ":" or not value[:2].isdigit() or not value[3:].isdigit():
        raise ValueError("time must use HH:MM")
    hour = int(value[:2])
    minute = int(value[3:])
    if hour > 23 or minute > 59:
        raise ValueError("time must use HH:MM")
    return value


def _validate_relative_source_ref(value: str) -> str:
    if (
        value.startswith(("/", "\\"))
        or value == ".."
        or value.startswith("../")
        or "/../" in value
        or value.endswith("/..")
    ):
        raise ValueError("working-tree source_ref must be a relative path")
    if "\\" in value:
        raise ValueError("working-tree source_ref must use a relative POSIX path")
    return value


def _validate_run_key_for_kind(value: str, kind: str) -> str:
    try:
        if kind == "daily":
            start_text, end_text = value.split("-", 1)
            start = date.fromisoformat(f"{start_text[:4]}-{start_text[4:6]}-{start_text[6:8]}")
            end = date.fromisoformat(f"{end_text[:4]}-{end_text[4:6]}-{end_text[6:8]}")
            if len(start_text) != 8 or len(end_text) != 8 or start != end or value != f"{start_text}-{end_text}":
                raise ValueError
        else:
            prefix, dates = value.split(":", 1)
            start_text, end_text = dates.split("-", 1)
            start = date.fromisoformat(f"{start_text[:4]}-{start_text[4:6]}-{start_text[6:8]}")
            end = date.fromisoformat(f"{end_text[:4]}-{end_text[4:6]}-{end_text[6:8]}")
            if (
                prefix != "weekly"
                or len(start_text) != 8
                or len(end_text) != 8
                or start.weekday() != 0
                or (end - start).days != 6
            ):
                raise ValueError
    except (ValueError, IndexError):
        raise ValueError("run_key does not match its job_kind") from None
    return value


def _validate_profile_binding(version: str, digest: str) -> None:
    if version.split(":", 1)[-1] != digest:
        raise ValueError("company profile version and digest must match")


def _validate_generation_binding(
    value: dict[str, Any] | None,
    digest: str | None,
    *,
    required: bool = False,
) -> dict[str, Any] | None:
    """Require response config/digest pairs to be canonical and identical."""

    if value is None or digest is None:
        if required:
            raise ValueError("generation config and digest are required")
        if value is not None or digest is not None:
            raise ValueError("generation config metadata must be provided as a pair")
        return None
    try:
        from .generation_config import config_from_value, validate_digest

        config = config_from_value(value)
        validate_digest(config, digest)
    except (TypeError, ValueError) as exc:
        raise ValueError("generation config and digest do not match") from exc
    canonical = config.canonical_value()
    if value != canonical:
        raise ValueError("generation config must be canonical")
    return canonical


AwareDateTime = Annotated[datetime, AfterValidator(_require_aware)]
Actor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class RuntimeContractModel(BaseModel):
    """Strict, metadata-only base for the new named REST contracts."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


__all__ = [
    "APIModel",
    "Actor",
    "AwareDateTime",
    "Digest",
    "NonEmpty",
    "PageFilters",
    "RuntimeContractModel",
]
