"""Deterministic contracts at the model-call boundary.

The model is deliberately treated as an untrusted JSON producer.  These
helpers validate without filling, correcting, or otherwise changing a value.
They are independent of SQLAlchemy and therefore safe to use in a worker or
in unit tests with no application state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any, Final, Literal, Mapping, Sequence
from uuid import uuid4


SYSTEM_MESSAGE: Final[str] = "JSON 외 텍스트를 출력하지 마라. 제공되지 않은 사실을 만들지 마라."
PERSPECTIVE_NAMES: Final[tuple[str, ...]] = (
    "기술 적합성",
    "실적 정합성",
    "공공 SI 적합성",
    "사업성·자격 제약",
    "전략 부합",
)
ASSESSMENTS: Final[frozenset[str]] = frozenset(
    {"적합", "부분 적합", "부적합", "확인 불가"}
)
EVIDENCE_STATUSES: Final[frozenset[str]] = frozenset(
    {"confirmed", "inferred", "unknown"}
)
GRADES: Final[frozenset[str]] = frozenset({"우선 검토", "검토 권장", "관찰 대상", "제외"})
READINESS: Final[frozenset[str]] = frozenset(
    {"확인 완료", "부분 확인 필요", "참여 불가 확인", "해당 없음"}
)
FOCUS_AXES: Final[frozenset[str]] = frozenset(
    {"AI/데이터", "블록체인·DID", "공공 SI·통합관리", "해당 없음"}
)
EXCLUSION_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "도메인 불일치",
        "시설·현장 용역",
        "공사·인프라",
        "행사·교육·홍보",
        "연구·조사",
        "감리·평가",
        "물품·임차",
        "자격 미달",
        "취소·종료",
        "기타 비관련",
    }
)
RESOLUTION_STATUSES: Final[frozenset[str]] = frozenset({"수용", "기각", "추가 확인"})
VERIFICATION_STATUSES: Final[frozenset[str]] = frozenset({"미확인", "확인 완료"})

FailureType = Literal[
    "timeout",
    "truncated_output",
    "schema_violation",
    "evidence_missing",
    "counterargument_repetition",
]


class ContractViolation(ValueError):
    """A safe, deterministic model contract failure.

    Only a short path/reason is retained.  The rejected response body is never
    included, which makes this exception safe for normal logs and API errors.
    """

    def __init__(self, message: str, *, failure_type: FailureType = "schema_violation") -> None:
        self.failure_type = failure_type
        self.reason = str(message)[:240]
        super().__init__(self.reason)


class DuplicateJSONKey(ContractViolation):
    """A JSON object contains a duplicate member name."""

    def __init__(self) -> None:
        super().__init__("JSON object contains duplicate keys")


@dataclass(frozen=True)
class CallMetadata:
    """Pure per-attempt telemetry returned by a model call."""

    execution_id: str
    notice_id: str
    stage: str
    attempt_no: int
    trace_id: str
    span_id: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    failure_type: FailureType | None
    done_reason: str | None
    model_name: str
    model_digest: str | None
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    prompt_eval_duration_ns: int | None = None
    eval_duration_ns: int | None = None
    load_duration_ns: int | None = None
    total_duration_ns: int | None = None
    error_summary: str | None = None
    generation_config_digest: str | None = None
    num_ctx: int | None = None
    num_predict: int | None = None


@dataclass(frozen=True)
class ModelIdentity:
    """한 실행이 묶인 모델명과 배포가 선언한 revision.

    `model_name`은 `BIDOPS_VLLM_SCREENING_MODEL`이 정하고 server의 served id에
    있어야 한다. `digest`는 Ollama blob digest가 아니라 **배포가 선언한 64자
    revision**이다(ADR-0042). 응답이 revision을 실어 보내면 대조하고 없으면
    통과하며, 선언이 비면 그 용도는 fail closed한다.
    """

    model_name: str
    digest: str


@dataclass(frozen=True)
class TwoAxisMixing:
    flag: bool
    label: str | None


def new_trace_id() -> str:
    return "trace-" + uuid4().hex


def new_span_id() -> str:
    return "span-" + uuid4().hex


def canonical_json(value: Any) -> str:
    """Serialize a value using the one frozen prompt representation."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError):
        raise ContractViolation("value cannot be represented as canonical JSON") from None


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKey()
        result[key] = value
    return result


def parse_json_object(raw: str | bytes) -> dict[str, Any]:
    """Parse one JSON object while rejecting duplicate keys and arrays."""

    if not isinstance(raw, (str, bytes)):
        raise ContractViolation("model response is not JSON text")
    duplicate = False
    malformed = False
    try:
        value = json.loads(raw, object_pairs_hook=_object_pairs)
    except DuplicateJSONKey:
        duplicate = True
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        malformed = True
    if duplicate:
        raise DuplicateJSONKey()
    if malformed:
        # JSONDecodeError retains the entire rejected document in ``doc``;
        # raise after leaving the handler so no exception context can leak it.
        raise ContractViolation("model response is malformed JSON")
    if not isinstance(value, dict):
        raise ContractViolation("model response must be a JSON object")
    return value


def _exact_object(value: Any, keys: Sequence[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractViolation(f"{path} must be an object")
    expected = set(keys)
    actual = set(value)
    if actual != expected:
        raise ContractViolation(f"{path}: exact object keys contract failed")
    return value


def _nonblank(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{path} must be a nonblank string")
    return value


def _enum(value: Any, allowed: frozenset[str], path: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ContractViolation(f"{path} has an invalid enum")
    return value


def validate_evidence(value: Any, *, path: str = "evidence") -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ContractViolation("evidence is missing", failure_type="evidence_missing")
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"source", "status", "fact"}:
            raise ContractViolation("evidence item is missing", failure_type="evidence_missing")
        # Once all evidence members are present, ordinary type/enum failures
        # remain schema violations and are distinguishable from absent proof.
        _nonblank(item["source"], f"{path}[{index}].source")
        _enum(item["status"], EVIDENCE_STATUSES, f"{path}[{index}].status")
        _nonblank(item["fact"], f"{path}[{index}].fact")
    return value


def validate_perspective(value: Any, *, expected_name: str | None = None) -> dict[str, Any]:
    if isinstance(value, dict) and "evidence" not in value:
        raise ContractViolation("evidence is missing", failure_type="evidence_missing")
    item = _exact_object(value, ("name", "assessment", "reason", "evidence"), "perspective")
    name = _nonblank(item["name"], "perspective.name")
    if expected_name is not None and name != expected_name:
        raise ContractViolation("perspective name does not match its stage")
    if name not in PERSPECTIVE_NAMES:
        raise ContractViolation("perspective name is not one of the five names")
    _enum(item["assessment"], ASSESSMENTS, "perspective.assessment")
    reason = _nonblank(item["reason"], "perspective.reason")
    if len(reason.strip()) < 10:
        raise ContractViolation("perspective.reason is shorter than 10 characters")
    validate_evidence(item["evidence"])
    return item


def _normalized_text(value: str) -> str:
    # Keep Korean letters and numbers but ignore punctuation/spacing, which
    # catches deterministic copies with harmless formatting changes.
    return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())


def _token_set(value: str) -> set[str]:
    return set(re.findall(r"[0-9a-z가-힣]{2,}", value.casefold()))


def _reject_repetition(items: list[str]) -> None:
    normalized = [_normalized_text(item) for item in items]
    if any(not item for item in normalized):
        raise ContractViolation("counterarguments contain empty normalized text", failure_type="counterargument_repetition")
    if len(set(normalized)) != len(normalized):
        raise ContractViolation("counterarguments repeat normalized text", failure_type="counterargument_repetition")
    token_sets = [_token_set(item) for item in items]
    for index, left in enumerate(token_sets):
        for right in token_sets[index + 1 :]:
            if left and right:
                similarity = len(left & right) / len(left | right)
                if similarity >= 0.8:
                    raise ContractViolation("counterarguments are highly repetitive", failure_type="counterargument_repetition")
    # A response consisting only of generic boilerplate is not a notice-bound
    # counterargument.  The phrases are intentionally small and deterministic.
    generic = {
        "추가확인이필요하다",
        "검토가필요하다",
        "위험이있을수있다",
        "주의가필요하다",
        "확인할필요가있다",
    }
    generic_stems = (
        "검토가필요",
        "확인이필요",
        "추가확인이필요",
        "주의가필요",
        "일반적인검토",
        "위험이있을수",
    )
    def is_generic(item: str) -> bool:
        normalized = _normalized_text(item)
        return normalized in generic or (
            any(stem in normalized for stem in generic_stems)
            and not any(anchor in normalized for anchor in ("공고", "사업", "예산", "자격", "요구", "기관"))
        )

    if any(is_generic(item) for item in items):
        raise ContractViolation("counterarguments are generic boilerplate", failure_type="counterargument_repetition")


def validate_counterargument(value: Any) -> dict[str, Any]:
    item = _exact_object(value, ("counterarguments",), "counterargument")
    values = item["counterarguments"]
    if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
        raise ContractViolation("counterarguments must contain one or more nonblank strings")
    _reject_repetition(values)
    return item


def _validate_nested_perspectives(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(PERSPECTIVE_NAMES):
        raise ContractViolation("judgment.perspectives must contain exactly five items")
    names: list[str] = []
    for item in value:
        checked = validate_perspective(item)
        names.append(checked["name"])
    if set(names) != set(PERSPECTIVE_NAMES) or len(set(names)) != len(PERSPECTIVE_NAMES):
        raise ContractViolation("judgment perspectives must contain five unique names")
    return value


def validate_judgment(value: Any, *, notice: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if (
        not isinstance(notice, Mapping)
        or not isinstance(notice.get("notice_id"), str)
        or not notice["notice_id"].strip()
    ):
        raise ContractViolation("notice identity is required")
    keys = (
        "notice_id", "grade", "readiness", "primary_focus", "exclusion_category", "summary",
        "perspectives", "matched_performances", "counterarguments", "counterargument_resolutions",
        "verification_items", "next_action",
    )
    item = _exact_object(value, keys, "judgment")
    _nonblank(item["notice_id"], "judgment.notice_id")
    if item["notice_id"] != notice["notice_id"]:
        raise ContractViolation("judgment.notice_id does not match notice")
    _enum(item["grade"], GRADES, "judgment.grade")
    readiness = _enum(item["readiness"], READINESS, "judgment.readiness")
    _enum(item["primary_focus"], FOCUS_AXES, "judgment.primary_focus")
    _nonblank(item["summary"], "judgment.summary")
    _nonblank(item["next_action"], "judgment.next_action")

    category = item["exclusion_category"]
    if item["grade"] == "제외":
        if readiness not in {"해당 없음", "참여 불가 확인"}:
            raise ContractViolation("excluded judgment has invalid readiness")
        _enum(category, EXCLUSION_CATEGORIES, "judgment.exclusion_category")
    elif category is not None:
        raise ContractViolation("non-excluded judgment must have null exclusion_category")

    _validate_nested_perspectives(item["perspectives"])

    matches = item["matched_performances"]
    if not isinstance(matches, list):
        raise ContractViolation("judgment.matched_performances must be an array")
    if notice is not None and notice.get("performance_matches"):
        if not matches:
            raise ContractViolation("performance evidence is missing", failure_type="evidence_missing")
    for index, match in enumerate(matches):
        match = _exact_object(
            match,
            ("name", "match_reason", "mismatch_or_limit", "source", "status"),
            f"matched_performances[{index}]",
        )
        for key in ("name", "match_reason", "mismatch_or_limit", "source"):
            _nonblank(match[key], f"matched_performances[{index}].{key}")
        _enum(match["status"], EVIDENCE_STATUSES, f"matched_performances[{index}].status")

    counterarguments = item["counterarguments"]
    if not isinstance(counterarguments, list) or not counterarguments or any(not isinstance(v, str) or not v.strip() for v in counterarguments):
        raise ContractViolation("judgment.counterarguments must contain one or more nonblank strings")
    _reject_repetition(counterarguments)
    resolutions = item["counterargument_resolutions"]
    if not isinstance(resolutions, list) or len(resolutions) != len(counterarguments):
        raise ContractViolation("counterargument resolutions must preserve order and length")
    for index, resolution in enumerate(resolutions):
        resolution = _exact_object(
            resolution, ("counterargument", "status", "reflection"), f"counterargument_resolutions[{index}]"
        )
        if resolution["counterargument"] != counterarguments[index]:
            raise ContractViolation("counterargument resolution order does not match")
        _enum(resolution["status"], RESOLUTION_STATUSES, f"counterargument_resolutions[{index}].status")
        _nonblank(resolution["reflection"], f"counterargument_resolutions[{index}].reflection")

    verification = item["verification_items"]
    if not isinstance(verification, list):
        raise ContractViolation("judgment.verification_items must be an array")
    for index, check in enumerate(verification):
        check = _exact_object(
            check,
            ("item", "why", "blocking", "status", "requires_attachment"),
            f"verification_items[{index}]",
        )
        _nonblank(check["item"], f"verification_items[{index}].item")
        _nonblank(check["why"], f"verification_items[{index}].why")
        if type(check["blocking"]) is not bool or type(check["requires_attachment"]) is not bool:
            raise ContractViolation("verification boolean fields must be strict booleans")
        _enum(check["status"], VERIFICATION_STATUSES, f"verification_items[{index}].status")
    blocking_unknown = [
        check for check in verification
        if isinstance(check, dict) and check.get("blocking") is True and check.get("status") == "미확인"
    ]
    if readiness == "부분 확인 필요" and not verification:
        raise ContractViolation("partial readiness requires verification items")
    if readiness == "확인 완료" and blocking_unknown:
        raise ContractViolation("complete readiness cannot retain blocking unknown items")
    if readiness == "참여 불가 확인" and not any(
        isinstance(check, dict) and check.get("blocking") is True for check in verification
    ):
        raise ContractViolation("unavailable readiness requires a blocking item")
    return item


def two_axis_mixing(perspectives: Sequence[Mapping[str, Any]], grade: str) -> TwoAxisMixing:
    """Compute the review flag without rewriting either judgment axis."""

    qualification = next(
        (item for item in perspectives if item.get("name") == "사업성·자격 제약"), None
    )
    flag = bool(
        isinstance(qualification, Mapping)
        and qualification.get("assessment") == "확인 불가"
        and grade in {"관찰 대상", "제외"}
    )
    return TwoAxisMixing(flag=flag, label="확인 요망" if flag else None)


def add_two_axis_metadata(judgment: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with deterministic two-axis metadata for v3 assembly."""

    result = dict(judgment)
    mix = two_axis_mixing(result.get("perspectives", ()), str(result.get("grade", "")))
    result["two_axis_mixing_flag"] = mix.flag
    result["two_axis_mixing_label"] = mix.label
    return result


__all__ = [
    "ASSESSMENTS", "CallMetadata", "ContractViolation", "EXCLUSION_CATEGORIES",
    "EVIDENCE_STATUSES", "FOCUS_AXES", "GRADES", "ModelIdentity",
    "PERSPECTIVE_NAMES", "READINESS", "RESOLUTION_STATUSES", "SYSTEM_MESSAGE",
    "TwoAxisMixing", "VERIFICATION_STATUSES", "add_two_axis_metadata", "canonical_json",
    "new_span_id", "new_trace_id", "parse_json_object", "two_axis_mixing",
    "validate_counterargument", "validate_evidence", "validate_judgment", "validate_perspective",
]
