"""Deterministic, non-production transport for screening workflow tests.

This transport implements the same small boundary as :class:`OllamaTransport`.
It never contacts a model service.  The output is deliberately marked as a
mock and keeps company performance evidence unknown, so it cannot be used as
an operating screening result or as a quality approval.

Stage selection is based only on the required-key set in Ollama's JSON schema.
The prompt is used for notice identity only when the synthesis response needs
to satisfy the notice-bound judgment contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
import re
from typing import Any, Final
from uuid import NAMESPACE_URL, uuid5

from .contracts import (
    EXCLUSION_CATEGORIES,
    MODEL_NAME,
    PERSPECTIVE_NAMES,
    canonical_json,
)


# This is a synthetic identity, not an Ollama blob digest.  It is deliberately
# exposed so persisted ScreeningAttempt telemetry can distinguish a reference
# mock execution from a real model execution by digest alone.
MOCK_MODEL_DIGEST: Final[str] = "0f1e2d3c4b5a69788796a5b4c3d2e1f0aabbccddeeff00112233445566778899"

_NOTICE_ASSIGNMENT: Final[str] = "notice_json="
_PERSPECTIVE_REQUIRED: Final[frozenset[str]] = frozenset(
    {"name", "assessment", "reason", "evidence"}
)
_COUNTERARGUMENT_REQUIRED: Final[frozenset[str]] = frozenset({"counterarguments"})
_JUDGMENT_REQUIRED: Final[frozenset[str]] = frozenset(
    {
        "notice_id",
        "grade",
        "readiness",
        "primary_focus",
        "exclusion_category",
        "summary",
        "perspectives",
        "matched_performances",
        "counterarguments",
        "counterargument_resolutions",
        "verification_items",
        "next_action",
    }
)

_GRADE_ORDER: Final[tuple[str, ...]] = (
    "우선 검토",
    "검토 권장",
    "관찰 대상",
    "제외",
)
_NON_EXCLUDED_READINESS_ORDER: Final[tuple[str, ...]] = (
    "확인 완료",
    "부분 확인 필요",
    "참여 불가 확인",
)
_FOCUS_ORDER: Final[tuple[str, ...]] = (
    "AI/데이터",
    "블록체인·DID",
    "공공 SI·통합관리",
)
_ASSESSMENT_ORDER: Final[tuple[str, ...]] = (
    "적합",
    "부분 적합",
    "부적합",
    "확인 불가",
)
_FAILURE_MODES: Final[frozenset[str]] = frozenset(
    {
        "schema_violation",
        "evidence_missing",
        "malformed_json",
        "truncated_output",
        "notice_id_mismatch",
    }
)
_TRAILING_NUMBER: Final[re.Pattern[str]] = re.compile(r"(\d+)$")


class MockScreeningTransportError(ValueError):
    """A malformed mock request or an unextractable notice identity."""


def _seed_number(notice_id: str, stage: str) -> int:
    """Return a stable integer derived only from the notice and stage."""

    return uuid5(
        NAMESPACE_URL,
        f"bidops.screening.mock.v1:{notice_id}:{stage}",
    ).int


def _stable_index(notice_id: str, stage: str, size: int) -> int:
    if size <= 0:
        raise ValueError("stable index size must be positive")
    return _seed_number(notice_id, stage) % size


def _extract_notice(prompt: str, *, required: bool) -> dict[str, Any] | None:
    """Extract the one canonical notice object assigned to ``notice_json``.

    The canonical serialization check prevents a malformed or ambiguous
    prompt from silently changing the notice identity used in a judgment.
    """

    if not isinstance(prompt, str):
        raise MockScreeningTransportError("mock prompt is not text")
    marker = prompt.find(_NOTICE_ASSIGNMENT)
    if marker < 0:
        if required:
            raise MockScreeningTransportError(
                "judgment notice_json canonical object is missing"
            )
        return None

    start = marker + len(_NOTICE_ASSIGNMENT)
    try:
        value, consumed = json.JSONDecoder().raw_decode(prompt[start:])
    except (TypeError, ValueError, json.JSONDecodeError):
        raise MockScreeningTransportError(
            "notice_json is not one canonical JSON object"
        ) from None
    if not isinstance(value, dict):
        raise MockScreeningTransportError(
            "notice_json canonical value is not an object"
        )
    try:
        serialized = prompt[start : start + consumed]
        if serialized != canonical_json(value):
            raise MockScreeningTransportError(
                "notice_json is not canonical JSON"
            )
    except MockScreeningTransportError:
        raise
    except Exception:
        raise MockScreeningTransportError(
            "notice_json cannot be represented as canonical JSON"
        ) from None

    # A marker embedded in the JSON value itself is part of the consumed
    # canonical object and is harmless.  A second assignment is ambiguous.
    if prompt.find(_NOTICE_ASSIGNMENT, start + consumed) >= 0:
        raise MockScreeningTransportError(
            "notice_json canonical assignment is ambiguous"
        )
    notice_id = value.get("notice_id")
    if required and (not isinstance(notice_id, str) or not notice_id.strip()):
        raise MockScreeningTransportError(
            "notice_json canonical object has no notice_id"
        )
    return value


def _notice_id(prompt: str, *, required: bool) -> str:
    notice = _extract_notice(prompt, required=required)
    if notice is None:
        return ""
    value = notice.get("notice_id")
    if not isinstance(value, str) or not value.strip():
        # Perspective prompts intentionally project only policy-allowed notice
        # fields and may not contain notice_id.  Their deterministic seed is
        # therefore stage-only; synthesis is the strict notice-bound stage.
        return ""
    return value


def _stage_for_schema(schema: Mapping[str, Any]) -> tuple[str, str | None]:
    """Classify a request from its JSON-schema required-key set."""

    required = schema.get("required")
    if (
        not isinstance(required, list)
        or any(not isinstance(key, str) for key in required)
        or len(required) != len(set(required))
    ):
        raise MockScreeningTransportError(
            "mock schema required keys are invalid"
        )
    required_keys = frozenset(required)
    if required_keys == _PERSPECTIVE_REQUIRED:
        properties = schema.get("properties")
        name_property = properties.get("name") if isinstance(properties, Mapping) else None
        names = name_property.get("enum") if isinstance(name_property, Mapping) else None
        if (
            not isinstance(names, list)
            or len(names) != 1
            or names[0] not in PERSPECTIVE_NAMES
        ):
            raise MockScreeningTransportError(
                "mock perspective schema does not identify one stage"
            )
        return "perspective", names[0]
    if required_keys == _COUNTERARGUMENT_REQUIRED:
        return "counterargument", None
    if required_keys == _JUDGMENT_REQUIRED:
        return "judgment", None
    raise MockScreeningTransportError(
        "mock schema required keys do not identify a screening stage"
    )


def _perspective(notice_id: str, name: str) -> dict[str, Any]:
    if name == "사업성·자격 제약":
        assessment = "확인 불가"
    else:
        assessment = _ASSESSMENT_ORDER[
            _stable_index(notice_id, name, len(_ASSESSMENT_ORDER))
        ]
    return {
        "name": name,
        "assessment": assessment,
        "reason": (
            f"모의 판정: {name}의 실제 공고·회사 사실을 확인하지 않은 "
            "결정적 자리표시자입니다."
        ),
        "evidence": [
            {
                "source": "모의 근거 자리표시자(실제 출처 아님)",
                "status": "unknown",
                "fact": "모의 검증용 문자열이며 원문·회사 실적 근거가 아닙니다.",
            }
        ],
    }


def _counterargument(notice_id: str) -> dict[str, Any]:
    return {
        "counterarguments": [
            (
                f"모의 반론: 공고 식별자 {notice_id}의 예산·자격 범위는 "
                "원문 확인 전에는 알 수 없으며 실제 판단으로 사용할 수 없습니다."
            )
        ]
    }


def _grade(notice_id: str) -> str:
    # Numbered fixture IDs intentionally cover all four grades in sequence;
    # arbitrary IDs use the same stable UUID5 seed as every other choice.
    match = _TRAILING_NUMBER.search(notice_id)
    index = (
        (int(match.group(1)) - 1) % len(_GRADE_ORDER)
        if match is not None
        else _stable_index(notice_id, "synthesis:grade", len(_GRADE_ORDER))
    )
    return _GRADE_ORDER[index]


def _verification_items(notice_id: str, readiness: str) -> list[dict[str, Any]]:
    if readiness == "확인 완료":
        return []
    if readiness == "부분 확인 필요":
        return [
            {
                "item": "모의 참여 자격 확인",
                "why": "모의 결과이며 실제 자격 원문이 제공되지 않았습니다.",
                "blocking": True,
                "status": "미확인",
                "requires_attachment": False,
            }
        ]
    if readiness == "참여 불가 확인":
        return [
            {
                "item": "모의 차단 조건 확인",
                "why": "모의 검증을 위해 확인된 차단 상태를 표시한 자리표시자입니다.",
                "blocking": True,
                "status": "확인 완료",
                "requires_attachment": False,
            }
        ]
    return []


def _judgment(notice_id: str) -> dict[str, Any]:
    grade = _grade(notice_id)
    readiness_index = _stable_index(notice_id, "synthesis:readiness", 3)
    if grade == "제외":
        readiness = (
            "해당 없음" if readiness_index % 2 == 0 else "참여 불가 확인"
        )
        exclusion_category = (
            tuple(sorted(EXCLUSION_CATEGORIES))[
                _stable_index(
                    notice_id,
                    "synthesis:exclusion_category",
                    len(EXCLUSION_CATEGORIES),
                )
            ]
        )
        primary_focus = "해당 없음"
    else:
        readiness = _NON_EXCLUDED_READINESS_ORDER[readiness_index]
        exclusion_category = None
        primary_focus = _FOCUS_ORDER[
            _stable_index(notice_id, "synthesis:primary_focus", len(_FOCUS_ORDER))
        ]

    counter = _counterargument(notice_id)
    counterarguments = counter["counterarguments"]
    return {
        "notice_id": notice_id,
        "grade": grade,
        "readiness": readiness,
        "primary_focus": primary_focus,
        "exclusion_category": exclusion_category,
        "summary": "모의 종합 결과이며 실제 사업·회사 판단이나 승인 근거가 아닙니다.",
        "perspectives": [_perspective(notice_id, name) for name in PERSPECTIVE_NAMES],
        "matched_performances": [
            {
                "name": "모의 실적 자리표시자(실제 회사 실적 아님)",
                "match_reason": "모의 검증용 문자열이며 실제 수행실적 일치 근거가 아닙니다.",
                "mismatch_or_limit": "실제 회사 실적·자격·일치 여부는 확인하지 않았습니다.",
                "source": "모의 근거 자리표시자(실제 출처 아님)",
                "status": "unknown",
            }
        ],
        "counterarguments": counterarguments,
        "counterargument_resolutions": [
            {
                "counterargument": counterargument,
                "status": "추가 확인",
                "reflection": "모의 반론에 대한 자리표시자 처리이며 담당자의 실제 확인이 필요합니다.",
            }
            for counterargument in counterarguments
        ],
        "verification_items": _verification_items(notice_id, readiness),
        "next_action": "모의 결과를 실제 판단으로 사용하지 말고 담당자가 원문과 자격을 확인합니다.",
    }


def _valid_output(kind: str, name: str | None, notice_id: str) -> dict[str, Any]:
    if kind == "perspective":
        assert name is not None
        return _perspective(notice_id, name)
    if kind == "counterargument":
        return _counterargument(notice_id)
    return _judgment(notice_id)


def _stage_matches(kind: str, name: str | None, requested: str | None) -> bool:
    if requested is None:
        return True
    normalized = {
        "counterargument.v1": "counterargument",
        "synthesis": "judgment",
        "judgment": "judgment",
        "judgment.v3": "judgment",
    }.get(requested, requested)
    if kind == "perspective":
        return normalized in {"perspective", name}
    return normalized == kind


class MockScreeningTransport:
    """Implement the Ollama transport contract with deterministic fixtures."""

    model_digest = MOCK_MODEL_DIGEST

    def __init__(
        self,
        *,
        failure_mode: str | None = None,
        failure_stage: str | None = None,
    ) -> None:
        if failure_mode is not None and failure_mode not in _FAILURE_MODES:
            raise ValueError("unknown mock screening failure mode")
        if failure_stage is not None and not failure_stage.strip():
            raise ValueError("mock screening failure stage must be nonblank")
        self.failure_mode = failure_mode
        self.failure_stage = failure_stage
        self.requests: list[dict[str, Any]] = []

    @property
    def generate_requests(self) -> list[dict[str, Any]]:
        return [
            request
            for request in self.requests
            if request["path"] == "/api/generate"
        ]

    def _envelope(
        self,
        value: dict[str, Any],
        *,
        done: bool = True,
        done_reason: str = "stop",
        raw: str | None = None,
    ) -> dict[str, Any]:
        return {
            "model": MODEL_NAME,
            "digest": MOCK_MODEL_DIGEST,
            "done": done,
            "done_reason": done_reason,
            "response": canonical_json(value) if raw is None else raw,
        }

    def _generate_response(
        self,
        prompt: str,
        schema: Mapping[str, Any],
    ) -> dict[str, Any]:
        kind, name = _stage_for_schema(schema)
        notice_id = _notice_id(prompt, required=kind == "judgment")
        output = _valid_output(kind, name, notice_id)
        if not _stage_matches(kind, name, self.failure_stage):
            return self._envelope(output)
        if self.failure_mode == "schema_violation":
            # Keep an evidence member so the authoritative validator reports a
            # schema violation rather than classifying the response as missing
            # evidence.  The extra key is intentionally never repaired here.
            output["모의 계약 위반"] = "추가 키가 있는 모의 응답입니다."
            return self._envelope(output)
        if self.failure_mode == "evidence_missing":
            if kind == "perspective":
                output.pop("evidence", None)
            else:
                output["evidence"] = []
            return self._envelope(output)
        if self.failure_mode == "malformed_json":
            return self._envelope(output, raw="{")
        if self.failure_mode == "truncated_output":
            return self._envelope(output, done=False, done_reason="length")
        if self.failure_mode == "notice_id_mismatch":
            if kind == "judgment":
                output["notice_id"] = "모의 notice_id 불일치 자리표시자"
            else:
                output = {"모의 계약 위반": "notice identity mismatch는 종합 단계 전용입니다."}
            return self._envelope(output)
        return self._envelope(output)

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
        *,
        timeout: float,
    ) -> Mapping[str, Any]:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "payload": None if payload is None else deepcopy(dict(payload)),
                "timeout": timeout,
            }
        )
        if path == "/api/tags":
            if method != "GET" or payload is not None:
                raise MockScreeningTransportError("mock tags request shape is invalid")
            return {
                "models": [
                    {
                        "name": MODEL_NAME,
                        "model": MODEL_NAME,
                        "digest": MOCK_MODEL_DIGEST,
                    }
                ]
            }
        if path != "/api/generate":
            raise MockScreeningTransportError("mock transport path is unsupported")
        if method != "POST" or not isinstance(payload, Mapping):
            raise MockScreeningTransportError("mock generate request shape is invalid")
        prompt = payload.get("prompt")
        schema = payload.get("format")
        if not isinstance(prompt, str) or not prompt:
            raise MockScreeningTransportError("mock prompt is missing")
        if not isinstance(schema, Mapping):
            raise MockScreeningTransportError("mock format schema is missing")
        return self._generate_response(prompt, schema)


__all__ = [
    "MOCK_MODEL_DIGEST",
    "MockScreeningTransport",
    "MockScreeningTransportError",
]
