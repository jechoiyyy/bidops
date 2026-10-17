"""평일 브리핑 규칙 파일 `bidops.briefing-policy.v1`의 적재와 검증 (RL-01 spec).

규칙 파일은 버전+sha256으로 고정된 immutable 파일이다. 값 하나라도 바꾸려면 새 버전
파일을 발행하고 `BIDOPS_BRIEFING_POLICY_PATH` 기본 경로를 함께 올린다. 여기서는
키 집합·형·허용 범위를 엄격히 검사하고, **파일 바이트**의 sha256을 돌려준다 — 그 값이
브리핑 행 `policy_sha256`에 고정된다(C-2 policy 적재와 같은 규칙). 검사 실패는 안전한
code 하나(`briefing_policy_invalid`)로만 알린다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from ..models import Notice

POLICY_SCHEMA = "bidops.briefing-policy.v1"

#: 파일의 최상위 키 전체(spec "결정적 점수와 제외"). 더하거나 빼면 거부한다.
POLICY_KEYS = frozenset(
    {
        "schema",
        "policy_identity",
        "top_n",
        "weights",
        "deadline_warning_days",
        "tracked_change_fields",
        "slack_items_per_message",
        "large_enterprise_threshold_krw",
    }
)
WEIGHT_KEYS = (
    "tier1",
    "tier2",
    "tier3",
    "repeat_agency",
    "similar_project",
    "sw_target",
    "amount_in_range",
)

#: 허용 범위(spec "설정 키와 기본값").
TOP_N_RANGE = (1, 30)
WEIGHT_RANGE = (0, 100)
DEADLINE_WARNING_DAYS_RANGE = (1, 30)
SLACK_ITEMS_PER_MESSAGE_RANGE = (1, 12)

_POLICY_IDENTITY_RE = re.compile(r"^briefing-policy-v[1-9][0-9]*$")


class BriefingPolicyError(ValueError):
    """규칙 파일이 계약과 다르다. 메시지는 안전한 code 하나다."""

    def __init__(self, code: str = "briefing_policy_invalid") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BriefingWeights:
    tier1: int
    tier2: int
    tier3: int
    repeat_agency: int
    similar_project: int
    sw_target: int
    amount_in_range: int

    def tier(self, tier: int) -> int:
        return {1: self.tier1, 2: self.tier2, 3: self.tier3}[tier]


@dataclass(frozen=True)
class BriefingPolicy:
    """검증된 규칙 파일. `sha256`은 파일 바이트의 digest다."""

    schema: str
    policy_identity: str
    top_n: int
    weights: BriefingWeights
    deadline_warning_days: int
    tracked_change_fields: tuple[str, ...]
    slack_items_per_message: int
    large_enterprise_threshold_krw: int
    sha256: str


def _int_in(value: Any, bounds: tuple[int, int]) -> int:
    # bool은 int의 하위형이라 명시적으로 막는다.
    if isinstance(value, bool) or not isinstance(value, int):
        raise BriefingPolicyError()
    low, high = bounds
    if not low <= value <= high:
        raise BriefingPolicyError()
    return value


def parse_briefing_policy(raw: bytes) -> BriefingPolicy:
    """규칙 파일 바이트를 검증한다. I/O가 없는 순수 함수다."""

    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise BriefingPolicyError() from None
    if not isinstance(value, Mapping) or set(value) != POLICY_KEYS:
        raise BriefingPolicyError()
    if value["schema"] != POLICY_SCHEMA:
        raise BriefingPolicyError()
    identity = value["policy_identity"]
    if not isinstance(identity, str) or not _POLICY_IDENTITY_RE.fullmatch(identity):
        raise BriefingPolicyError()
    weights = value["weights"]
    if not isinstance(weights, Mapping) or set(weights) != set(WEIGHT_KEYS):
        raise BriefingPolicyError()
    fields = value["tracked_change_fields"]
    notice_columns = set(Notice.__table__.columns.keys())
    if (
        not isinstance(fields, list)
        or not fields
        or any(not isinstance(item, str) or item not in notice_columns for item in fields)
        or len(set(fields)) != len(fields)
    ):
        raise BriefingPolicyError()
    threshold = value["large_enterprise_threshold_krw"]
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold <= 0:
        raise BriefingPolicyError()
    return BriefingPolicy(
        schema=POLICY_SCHEMA,
        policy_identity=identity,
        top_n=_int_in(value["top_n"], TOP_N_RANGE),
        weights=BriefingWeights(
            **{key: _int_in(weights[key], WEIGHT_RANGE) for key in WEIGHT_KEYS}
        ),
        deadline_warning_days=_int_in(value["deadline_warning_days"], DEADLINE_WARNING_DAYS_RANGE),
        tracked_change_fields=tuple(fields),
        slack_items_per_message=_int_in(
            value["slack_items_per_message"], SLACK_ITEMS_PER_MESSAGE_RANGE
        ),
        large_enterprise_threshold_krw=threshold,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def load_briefing_policy(path: Path | None = None) -> BriefingPolicy:
    """`path`(기본 `BIDOPS_BRIEFING_POLICY_PATH`)의 규칙 파일을 읽어 검증한다."""

    if path is None:
        from ...core.config import get_settings

        path = get_settings().briefing_policy_path
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise BriefingPolicyError() from None
    return parse_briefing_policy(raw)


__all__ = [
    "BriefingPolicy",
    "BriefingPolicyError",
    "BriefingWeights",
    "POLICY_SCHEMA",
    "load_briefing_policy",
    "parse_briefing_policy",
]
