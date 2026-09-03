"""ADR-009 run identity: build it and read it back.

회차 식별자는 회차 적재(lifecycle)뿐 아니라 조립 계층의 worker와 CLI도 읽으므로
테이블을 쓰지 않는 순수 문자열 유틸로 core가 소유한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Seoul"

RUN_ID_RE = re.compile(r"^(?P<directory>.+)--(?P<generated>\d{8}T\d{6}(?:\.\d{1,6})?Z)$")


def ensure_aware(value: datetime, timezone_name: str = DEFAULT_TIMEZONE) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return value.replace(tzinfo=zone)


def deterministic_run_id(directory_name: str, generated_at: datetime) -> str:
    """Build the ADR-009 run identity from the directory and generated time."""

    aware = ensure_aware(generated_at, DEFAULT_TIMEZONE).astimezone(timezone.utc)
    stamp = aware.strftime("%Y%m%dT%H%M%S")
    if aware.microsecond:
        stamp += f".{aware.microsecond:06d}".rstrip("0")
    return f"{directory_name}--{stamp}Z"


def parse_run_id(run_id: str) -> tuple[str, datetime] | None:
    """Parse a generated run id; useful to callers inspecting old snapshots."""

    match = RUN_ID_RE.match(run_id)
    if not match:
        return None
    value = match.group("generated").removesuffix("Z")
    try:
        generated = datetime.strptime(value, "%Y%m%dT%H%M%S.%f" if "." in value else "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    return match.group("directory"), generated.replace(tzinfo=timezone.utc)


__all__ = ["DEFAULT_TIMEZONE", "RUN_ID_RE", "deterministic_run_id", "ensure_aware", "parse_run_id"]
