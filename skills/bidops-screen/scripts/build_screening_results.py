#!/usr/bin/env python3
"""Validate agent-authored judgments and merge them with the validation set.

This step never supplies content. A judgment that omits perspectives, evidence,
counterarguments, or verification items is rejected, because a default filled in
here would reach the report as if an agent had reasoned about the notice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable
from typing import Any


GRADES = {"우선 검토", "검토 권장", "관찰 대상", "제외"}
READINESS = {"확인 완료", "부분 확인 필요", "참여 불가 확인", "해당 없음"}
ASSESSMENTS = {"적합", "부분 적합", "부적합", "확인 불가"}
EVIDENCE_STATUS = {"confirmed", "inferred", "unknown"}
VERIFICATION_STATUS = {"미확인", "확인 완료"}
FOCUS_AXES = {"AI/데이터", "블록체인·DID", "공공 SI·통합관리", "해당 없음"}
EXCLUSION_CATEGORIES = {
    "도메인 불일치", "시설·현장 용역", "공사·인프라", "행사·교육·홍보",
    "연구·조사", "감리·평가", "물품·임차", "자격 미달", "취소·종료", "기타 비관련",
}
REQUIRED_PERSPECTIVES = (
    "기술 적합성", "실적 정합성", "공공 SI 적합성", "사업성·자격 제약", "전략 부합",
)

# v3 is deliberately kept separate from the historical v2 contract.  In
# particular, v2 notices and judgments are not retrofitted with provenance
# fields and the v2 output remains byte-for-byte compatible at the object
# level with the old merge path.
COMMON_NOTICE_KEYS = (
    "notice_id", "source_type", "title", "agency", "method", "url",
    "collection_bucket", "published_at", "deadline_at", "budget",
    "estimated_price", "procurement_class", "region_limit", "lifecycle",
    "qualification_flags", "attachments", "focus_matches",
    "performance_matches", "performance_top_score", "candidate_sources",
    "unknown_fields", "sample_stratum", "sample_role", "raw_source",
)
SCREENING_INPUT_KEYS = (
    "schema_version", "execution_id", "run_id", "generated_at",
    "source_window", "policy_version", "prompt_version",
    "company_profile_version", "company_profile_digest", "candidate_count",
    "notices", "generation_config", "generation_config_digest",
)
DECISIONS_V3_KEYS = (
    "schema_version", "execution_id", "run_id", "generated_at",
    "screening_basis", "model_name", "model_digest", "prompt_version",
    "policy_version", "company_profile_version", "company_profile_digest",
    "judgments", "generation_config", "generation_config_digest",
)
JUDGMENT_V3_KEYS = (
    "notice_id", "judgment_mode", "model_name", "model_digest",
    "prompt_version", "policy_version", "company_profile_version",
    "company_profile_digest", "judged_in_run", "recorded_in_run",
    "carried_over", "rejudge_reason", "grade", "readiness",
    "primary_focus", "exclusion_category", "summary", "next_action",
    "perspectives", "matched_performances", "counterarguments",
    "counterargument_resolutions", "verification_items",
    "two_axis_mixing_flag", "two_axis_mixing_label",
)
FAILURES_TOP_KEYS = (
    "schema_version", "execution_id", "run_id", "generated_at",
    "failure_count", "failures",
)
FAILURE_KEYS = (
    "notice_id", "failed_stage", "failure_type", "last_attempt_at",
    "retry_count", "status", "failure_context", "trace_id", "span_id",
    "error_summary",
)
PERSPECTIVE_KEYS = ("name", "assessment", "reason", "evidence")
EVIDENCE_KEYS = ("source", "status", "fact")
MATCHED_PERFORMANCE_KEYS = (
    "name", "match_reason", "mismatch_or_limit", "source", "status",
)
RESOLUTION_KEYS = ("counterargument", "status", "reflection")
VERIFICATION_KEYS = ("item", "why", "blocking", "status", "requires_attachment")

JUDGMENT_MODES = {"신규", "재판정", "승계"}
REJUDGE_REASONS = {"정정", "재공고", "본공고 전환", "담당자 요청"}
FAILURE_STAGES = set(REQUIRED_PERSPECTIVES) | {"반론 검토", "종합 판정", "병합·검증"}
MODEL_FAILURE_STAGES = set(REQUIRED_PERSPECTIVES) | {"반론 검토", "종합 판정"}
FAILURE_TYPES = {
    "timeout", "truncated_output", "schema_violation", "evidence_missing",
    "counterargument_repetition",
}
FAILURE_STATUS = "사람 검토 대기"
SAMPLE_ROLES = {"analysis", "audit"}
SAMPLE_STRATA = {
    "AI/데이터", "블록체인·DID", "공공 SI·통합관리", "수행실적 유사",
    "분류 근접", "실적 유사 근접", "무작위",
}
SOURCE_TYPES = {"bid_notice", "pre_spec"}
COLLECTION_BUCKETS = {"candidate_pool", "audit_pool"}
EXECUTION_ID_RE = re.compile(r"^scr-[0-9a-f]{32}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
DECIMAL_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

DEFAULT_BOILERPLATE_RATIO = 0.4
MIN_REASON_LENGTH = 10


def non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_perspectives(judgment: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    perspectives = judgment.get("perspectives")
    if not isinstance(perspectives, list):
        return [f"{prefix} perspectives가 배열이 아닙니다."]
    names = [item.get("name") for item in perspectives if isinstance(item, dict)]
    missing = [name for name in REQUIRED_PERSPECTIVES if name not in names]
    if missing:
        errors.append(f"{prefix} 관점이 누락되었습니다: {', '.join(missing)}")
    unexpected = [name for name in names if not _enum(name, set(REQUIRED_PERSPECTIVES))]
    if unexpected:
        errors.append(f"{prefix} 계약에 없는 관점 이름입니다: {', '.join(map(str, unexpected))}")
    for item in perspectives:
        if not isinstance(item, dict):
            errors.append(f"{prefix} 관점 항목이 객체가 아닙니다.")
            continue
        name = item.get("name")
        if not _enum(item.get("assessment"), ASSESSMENTS):
            errors.append(f"{prefix} 관점 '{name}'의 assessment가 잘못되었습니다.")
        if not non_empty(item.get("reason")) or len(item["reason"].strip()) < MIN_REASON_LENGTH:
            errors.append(f"{prefix} 관점 '{name}'의 판단 근거 서술이 없습니다.")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{prefix} 관점 '{name}'에 근거가 없습니다.")
            continue
        for entry in evidence:
            if not isinstance(entry, dict):
                errors.append(f"{prefix} 관점 '{name}'의 근거 항목이 객체가 아닙니다.")
                continue
            if not _enum(entry.get("status"), EVIDENCE_STATUS):
                errors.append(
                    f"{prefix} 관점 '{name}'의 근거 status가 잘못되었습니다: "
                    f"{entry.get('status')}"
                )
            if not non_empty(entry.get("source")) or not non_empty(entry.get("fact")):
                errors.append(f"{prefix} 관점 '{name}'의 근거에 출처나 사실이 비어 있습니다.")
    return errors


def validate_verification(judgment: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    items = judgment.get("verification_items")
    if not isinstance(items, list):
        return [f"{prefix} verification_items가 배열이 아닙니다."]
    for item in items:
        if not isinstance(item, dict):
            errors.append(f"{prefix} 확인 항목이 객체가 아닙니다.")
            continue
        if not non_empty(item.get("item")) or not non_empty(item.get("why")):
            errors.append(f"{prefix} 확인 항목의 내용이나 사유가 비어 있습니다.")
        if not isinstance(item.get("blocking"), bool):
            errors.append(f"{prefix} 확인 항목의 blocking이 불리언이 아닙니다.")
        if not _enum(item.get("status"), VERIFICATION_STATUS):
            errors.append(f"{prefix} 확인 항목의 status가 잘못되었습니다.")

    readiness = judgment.get("readiness")
    blocking_unknown = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("blocking")
        and item.get("status") != "확인 완료"
    ]
    if readiness == "부분 확인 필요" and not items:
        errors.append(f"{prefix} 부분 확인 필요인데 확인 항목이 없습니다.")
    if readiness == "확인 완료" and blocking_unknown:
        errors.append(f"{prefix} 확인 완료인데 미확인 필수 항목이 남아 있습니다.")
    if readiness == "참여 불가 확인" and not any(
        isinstance(item, dict) and item.get("blocking") for item in items
    ):
        errors.append(f"{prefix} 참여 불가 확인인데 참여를 막는 항목이 없습니다.")
    return errors


def validate_judgment(judgment: dict[str, Any], notice: dict[str, Any]) -> list[str]:
    notice_id = judgment.get("notice_id") or notice.get("notice_id")
    prefix = f"[{notice_id}]"
    errors: list[str] = []

    grade = judgment.get("grade")
    readiness = judgment.get("readiness")
    if not _enum(grade, GRADES):
        errors.append(f"{prefix} 잘못된 등급: {grade}")
    if not _enum(readiness, READINESS):
        errors.append(f"{prefix} 잘못된 참여 준비 상태: {readiness}")
    if not _enum(judgment.get("primary_focus"), FOCUS_AXES):
        errors.append(f"{prefix} primary_focus가 계약의 축 목록에 없습니다.")
    if not non_empty(judgment.get("summary")):
        errors.append(f"{prefix} summary가 비어 있습니다.")
    if not non_empty(judgment.get("next_action")):
        errors.append(f"{prefix} next_action이 비어 있습니다.")

    category = judgment.get("exclusion_category")
    if grade == "제외":
        if not _enum(readiness, {"해당 없음", "참여 불가 확인"}):
            errors.append(
                f"{prefix} 제외 등급의 참여 준비 상태는 '해당 없음' 또는 "
                "'참여 불가 확인'이어야 합니다."
            )
        if not _enum(category, EXCLUSION_CATEGORIES):
            errors.append(f"{prefix} 제외 등급에는 exclusion_category가 필요합니다.")
    elif category not in (None, ""):
        errors.append(f"{prefix} 제외가 아닌 등급에 exclusion_category가 있습니다.")

    counterarguments = judgment.get("counterarguments")
    if not isinstance(counterarguments, list) or not any(
        non_empty(item) for item in counterarguments
    ):
        errors.append(f"{prefix} 반론이 최소 한 건 필요합니다.")

    errors.extend(validate_perspectives(judgment, prefix))
    errors.extend(validate_verification(judgment, prefix))

    if notice.get("performance_matches"):
        matched = judgment.get("matched_performances")
        if not isinstance(matched, list) or not matched:
            errors.append(
                f"{prefix} 수행실적 탐색 신호가 있으나 검토 결과가 기록되지 않았습니다."
            )
        else:
            for item in matched:
                if not isinstance(item, dict) or not non_empty(
                    item.get("mismatch_or_limit")
                ):
                    errors.append(
                        f"{prefix} 연결 실적에 유사도가 설명하지 못하는 차이가 없습니다."
                    )
    return errors


def boilerplate_errors(
    judgments: list[dict[str, Any]], ratio: float = DEFAULT_BOILERPLATE_RATIO
) -> list[str]:
    """Reject one sentence pasted across most judgments."""
    total = len(judgments)
    if total < 3:
        return []
    limit = max(2, int(total * ratio))
    counts: Counter[str] = Counter()
    for judgment in judgments:
        counterarguments = judgment.get("counterarguments")
        if not isinstance(counterarguments, list):
            continue
        for text in counterarguments:
            if non_empty(text):
                counts[text.strip()] += 1
    return [
        f"동일한 반론이 {count}/{total}건에서 반복됩니다: {text}"
        for text, count in counts.items()
        if count > limit
    ]


def _merge_v2(
    validation: dict[str, Any],
    decisions: dict[str, Any],
    boilerplate_ratio: float = DEFAULT_BOILERPLATE_RATIO,
) -> dict[str, Any]:
    if validation.get("schema_version") != "bidops.validation-set.v2":
        raise SystemExit(
            "지원하지 않는 검증 표본 스키마입니다: " f"{validation.get('schema_version')}"
        )
    if decisions.get("schema_version") != "bidops.decisions.v2":
        raise SystemExit(
            "지원하지 않는 판정 스키마입니다: " f"{decisions.get('schema_version')}"
        )
    if not non_empty(decisions.get("screening_basis")):
        raise SystemExit("screening_basis가 비어 있습니다.")

    by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for judgment in decisions.get("judgments", []):
        notice_id = judgment.get("notice_id")
        if not isinstance(notice_id, str) or not notice_id or notice_id in by_id:
            raise SystemExit(f"판정 notice_id가 없거나 중복되었습니다: {notice_id}")
        by_id[notice_id] = judgment

    notices = validation.get("notices", [])
    missing = [
        notice["notice_id"] for notice in notices if notice["notice_id"] not in by_id
    ]
    if missing:
        errors.append(f"판정이 없는 공고가 {len(missing)}건입니다: {', '.join(missing)}")
    extra = sorted(set(by_id) - {notice["notice_id"] for notice in notices})
    if extra:
        errors.append(f"표본에 없는 판정이 있습니다: {', '.join(extra)}")

    results = []
    for notice in notices:
        judgment = by_id.get(notice["notice_id"])
        if not judgment:
            continue
        errors.extend(validate_judgment(judgment, notice))
        judgment = {
            key: value for key, value in judgment.items() if key != "notice_id"
        }
        results.append({"notice": notice, "judgment": judgment})

    errors.extend(boilerplate_errors(list(by_id.values()), boilerplate_ratio))
    if errors:
        raise SystemExit(
            "판정이 계약을 만족하지 않습니다.\n- " + "\n- ".join(errors)
        )

    return {
        "schema_version": "bidops.screening.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "screening_basis": decisions["screening_basis"],
        "source_window": validation["source_window"],
        "results": results,
    }


def canonical_json_bytes(value: Any) -> bytes:
    """Return the contract's canonical UTF-8 JSON representation."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_digest(value: bytes | str) -> str:
    """Hash raw bytes (a string is encoded as UTF-8 for convenience)."""

    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _keys_error(value: Any, allowed: Iterable[str], prefix: str, *, require_all: bool = True) -> list[str]:
    if not isinstance(value, dict):
        return [f"{prefix} 객체가 아닙니다."]
    allowed_set = set(allowed)
    actual = set(value)
    errors: list[str] = []
    missing = sorted(allowed_set - actual) if require_all else []
    extra = sorted(actual - allowed_set)
    if missing:
        errors.append(f"{prefix} 필드가 누락되었습니다: {', '.join(missing)}")
    if extra:
        errors.append(f"{prefix} 허용되지 않은 필드입니다: {', '.join(extra)}")
    return errors


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _enum(value: Any, allowed: set[str]) -> bool:
    return isinstance(value, str) and value in allowed


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _digest(value: Any, prefix: str) -> list[str]:
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        return [f"{prefix}는 lowercase SHA-256 digest가 아닙니다."]
    return []


def _generation_config_errors(value: Any, digest: Any, prefix: str) -> list[str]:
    """Validate the frozen generation contract without importing the app."""

    errors: list[str] = []
    expected_keys = {"schema_version", "num_ctx", "num_predict", "think", "stream"}
    if not isinstance(value, dict):
        return [f"{prefix} 객체가 아닙니다."]
    errors.extend(_keys_error(value, expected_keys, prefix))
    if value.get("schema_version") != "bidops.generation-config.v1":
        errors.append(f"{prefix}.schema_version이 잘못되었습니다.")
    context = value.get("num_ctx")
    if type(context) is not int or not 1 <= context <= 131072:
        errors.append(f"{prefix}.num_ctx가 허용 범위를 벗어났습니다.")
    budgets = value.get("num_predict")
    if not isinstance(budgets, dict) or set(budgets) != {"perspective", "counterargument", "synthesis"}:
        errors.append(f"{prefix}.num_predict stage map이 잘못되었습니다.")
    else:
        for stage, budget in budgets.items():
            if type(budget) is not int or not 1 <= budget <= 32768 or (type(context) is int and budget > context):
                errors.append(f"{prefix}.num_predict.{stage}가 허용 범위를 벗어났습니다.")
    if value.get("think") is not False or value.get("stream") is not False:
        errors.append(f"{prefix}.think/stream은 false여야 합니다.")
    errors.extend(_digest(digest, f"{prefix}_digest"))
    if not errors:
        expected_digest = sha256_digest(canonical_json_bytes(value))
        if digest != expected_digest:
            errors.append(f"{prefix}와 digest가 일치하지 않습니다.")
    return errors


def _company_profile_version(value: Any, digest: Any, prefix: str) -> list[str]:
    expected = f"company-profile.sha256:{digest}" if isinstance(digest, str) else None
    if not isinstance(value, str) or expected is None or value != expected:
        return [f"{prefix}가 company_profile_digest와 일치하지 않습니다."]
    return []


def _decimal_string(value: Any, prefix: str, *, nullable: bool = True) -> list[str]:
    if value is None and nullable:
        return []
    if not isinstance(value, str) or not DECIMAL_RE.fullmatch(value):
        return [f"{prefix}는 base-10 decimal 문자열 또는 null이어야 합니다."]
    return []


def _execution_id(value: Any, prefix: str) -> list[str]:
    if not isinstance(value, str) or not EXECUTION_ID_RE.fullmatch(value):
        return [f"{prefix}는 scr- 뒤 32자리 lowercase hex여야 합니다."]
    return []


def _timestamp(value: Any, prefix: str, *, nullable: bool = False) -> list[str]:
    if value is None and nullable:
        return []
    if not isinstance(value, str):
        return [f"{prefix}가 timezone ISO-8601 문자열이 아닙니다."]
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return [f"{prefix}가 timezone ISO-8601 문자열이 아닙니다."]
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return [f"{prefix}에 timezone이 없습니다."]
    return []


def _window(value: Any, prefix: str) -> list[str]:
    errors = _keys_error(value, ("from", "to", "timezone"), prefix)
    if errors or not isinstance(value, dict):
        return errors
    if value.get("timezone") != "Asia/Seoul":
        errors.append(f"{prefix}.timezone은 Asia/Seoul이어야 합니다.")
    parsed_dates: dict[str, date] = {}
    for key in ("from", "to"):
        item = value.get(key)
        if not isinstance(item, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", item):
            errors.append(f"{prefix}.{key}가 YYYY-MM-DD date 문자열이 아닙니다.")
            continue
        try:
            parsed_dates[key] = date.fromisoformat(item)
        except ValueError:
            errors.append(f"{prefix}.{key}가 유효한 YYYY-MM-DD date가 아닙니다.")
    if len(parsed_dates) == 2 and parsed_dates["from"] > parsed_dates["to"]:
        errors.append(f"{prefix}.from이 to보다 늦습니다.")
    return errors


def _relative_posix_path(value: Any, prefix: str) -> list[str]:
    if not isinstance(value, str) or not value or "\\" in value:
        return [f"{prefix}가 프로젝트 상대 POSIX 경로가 아닙니다."]
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return [f"{prefix}가 프로젝트 상대 POSIX 경로가 아닙니다."]
    path = Path(value)
    if path.is_absolute() or value.startswith("/"):
        return [f"{prefix}가 프로젝트 상대 POSIX 경로가 아닙니다."]
    parts = value.split("/")
    if not parts or ":" in parts[0] or re.fullmatch(r"[A-Za-z]:.*", value):
        return [f"{prefix}가 프로젝트 상대 POSIX 경로가 아닙니다."]
    if any(part in {"", ".", ".."} for part in parts):
        return [f"{prefix}가 프로젝트 상대 POSIX 경로가 아닙니다."]
    return []


def _nullable_string_type(value: Any, prefix: str) -> list[str]:
    if value is not None and not isinstance(value, str):
        return [f"{prefix}는 문자열 또는 null이어야 합니다."]
    return []


def _nonblank_string_array(value: Any, prefix: str) -> list[str]:
    if not isinstance(value, list) or any(not _nonempty(item) for item in value):
        return [f"{prefix}는 nonblank 문자열 배열이어야 합니다."]
    return []


def _validate_nested_notice(notice: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    object_keys = {
        "procurement_class": ("large", "middle", "detail", "code"),
        "region_limit": (
            "basis", "joint_contract_regions", "joint_contract_rate",
            "regional_joint_contract_limit",
        ),
        "lifecycle": (
            "pre_spec_no", "re_notice", "changed_at", "change_reason",
            "unified_notice_no", "previous_failed_notice_no",
        ),
        "qualification_flags": (
            "participation_limited", "industry_limited", "information_business",
            "general_service", "service_division", "joint_contract_method",
            "performance_restricted_competition", "pq_evaluation",
            "technical_evaluation", "technical_evaluation_rate",
            "successful_bid_method",
        ),
    }
    for name, keys in object_keys.items():
        value = notice.get(name)
        # An empty qualification_flags object is emitted for pre-spec notices;
        # every other collected object, and any populated qualification object,
        # must retain the complete collected.v2 shape.
        require_all = name != "qualification_flags" or bool(value)
        errors.extend(_keys_error(value, keys, f"{prefix}.{name}", require_all=require_all))
    lifecycle = notice.get("lifecycle")
    if isinstance(lifecycle, dict):
        errors.extend(_timestamp(
            lifecycle.get("changed_at"), f"{prefix}.lifecycle.changed_at", nullable=True
        ))
        for key in (
            "pre_spec_no", "re_notice", "change_reason", "unified_notice_no",
            "previous_failed_notice_no",
        ):
            errors.extend(_nullable_string_type(
                lifecycle.get(key), f"{prefix}.lifecycle.{key}"
            ))
    procurement_class = notice.get("procurement_class")
    if isinstance(procurement_class, dict):
        for key in ("large", "middle", "detail", "code"):
            errors.extend(_nullable_string_type(
                procurement_class.get(key), f"{prefix}.procurement_class.{key}"
            ))
    region_limit = notice.get("region_limit")
    if isinstance(region_limit, dict):
        for key in ("basis", "joint_contract_rate", "regional_joint_contract_limit"):
            errors.extend(_nullable_string_type(
                region_limit.get(key), f"{prefix}.region_limit.{key}"
            ))
        errors.extend(_nonblank_string_array(
            region_limit.get("joint_contract_regions"),
            f"{prefix}.region_limit.joint_contract_regions",
        ))
    qualification_flags = notice.get("qualification_flags")
    if isinstance(qualification_flags, dict) and qualification_flags:
        for key in (
            "participation_limited", "industry_limited", "information_business",
            "general_service", "service_division", "joint_contract_method",
            "performance_restricted_competition", "pq_evaluation",
            "technical_evaluation", "technical_evaluation_rate", "successful_bid_method",
        ):
            errors.extend(_nullable_string_type(
                qualification_flags.get(key), f"{prefix}.qualification_flags.{key}"
            ))
    for index, item in enumerate(
        notice.get("attachments") if isinstance(notice.get("attachments"), list) else []
    ):
        errors.extend(_keys_error(item, ("name", "url"), f"{prefix}.attachments[{index}]"))
        if isinstance(item, dict):
            if not _nonempty(item.get("name")) or not _nonempty(item.get("url")):
                errors.append(f"{prefix}.attachments[{index}]의 name/url이 비어 있습니다.")
    for index, item in enumerate(
        notice.get("focus_matches") if isinstance(notice.get("focus_matches"), list) else []
    ):
        item_prefix = f"{prefix}.focus_matches[{index}]"
        errors.extend(_keys_error(
            item, ("axis", "label", "matched_field", "matched_text", "field_kind"), item_prefix
        ))
        if isinstance(item, dict):
            if not _enum(item.get("field_kind"), {"title", "classification", "other"}):
                errors.append(f"{item_prefix}.field_kind가 잘못되었습니다.")
            for key in ("axis", "label", "matched_field", "matched_text"):
                if not _nonempty(item.get(key)):
                    errors.append(f"{item_prefix}.{key}가 비어 있습니다.")
    for index, item in enumerate(
        notice.get("performance_matches") if isinstance(notice.get("performance_matches"), list) else []
    ):
        item_prefix = f"{prefix}.performance_matches[{index}]"
        errors.extend(_keys_error(
            item,
            ("project_name", "source_page", "similarity", "common_fragment", "legal_qualification_status"),
            item_prefix,
        ))
        if isinstance(item, dict):
            source_page = item.get("source_page")
            source_page_valid = (
                isinstance(source_page, int) and not isinstance(source_page, bool) and source_page >= 0
            ) or (isinstance(source_page, str) and bool(source_page.strip()))
            if not _nonempty(item.get("project_name")) or not source_page_valid:
                errors.append(f"{item_prefix}의 프로젝트명/출처가 비어 있습니다.")
            if not _finite_number(item.get("similarity")):
                errors.append(f"{item_prefix}.similarity가 숫자가 아닙니다.")
            if item.get("common_fragment") is not None and not _nonempty(item.get("common_fragment")):
                errors.append(f"{item_prefix}.common_fragment가 비어 있습니다.")
            if not _nonempty(item.get("legal_qualification_status")):
                errors.append(f"{item_prefix}.legal_qualification_status가 비어 있습니다.")
    return errors


def validate_common_notice(notice: Any, prefix: str = "notice") -> list[str]:
    """Validate the exact common collected.v2 notice projection used by v1."""

    errors = _keys_error(notice, COMMON_NOTICE_KEYS, prefix)
    if errors or not isinstance(notice, dict):
        return errors
    if not _nonempty(notice.get("notice_id")):
        errors.append(f"{prefix}.notice_id가 비어 있습니다.")
    if not _enum(notice.get("source_type"), SOURCE_TYPES):
        errors.append(f"{prefix}.source_type가 잘못되었습니다.")
    for key in ("title", "agency", "method", "url"):
        if notice.get(key) is not None and not _nonempty(notice.get(key)):
            errors.append(f"{prefix}.{key}가 비어 있습니다.")
    for key in ("published_at", "deadline_at"):
        errors.extend(_timestamp(notice.get(key), f"{prefix}.{key}", nullable=True))
    for key in ("budget", "estimated_price"):
        errors.extend(_decimal_string(notice.get(key), f"{prefix}.{key}"))
    if not _enum(notice.get("collection_bucket"), COLLECTION_BUCKETS):
        errors.append(f"{prefix}.collection_bucket가 잘못되었습니다.")
    for key in ("sample_stratum", "sample_role"):
        value = notice.get(key)
        if value is not None and not _nonempty(value):
            errors.append(f"{prefix}.{key}가 비어 있습니다.")
    if notice.get("sample_role") is not None and not _enum(notice.get("sample_role"), SAMPLE_ROLES):
        errors.append(f"{prefix}.sample_role가 잘못되었습니다.")
    if notice.get("sample_stratum") is not None and not _enum(notice.get("sample_stratum"), SAMPLE_STRATA):
        errors.append(f"{prefix}.sample_stratum가 잘못되었습니다.")
    for key in ("candidate_sources", "unknown_fields"):
        value = notice.get(key)
        if not isinstance(value, list) or any(not _nonempty(item) for item in value):
            errors.append(f"{prefix}.{key}가 문자열 배열이 아닙니다.")
    if notice.get("performance_top_score") is not None:
        score = notice.get("performance_top_score")
        if not _finite_number(score):
            errors.append(f"{prefix}.performance_top_score가 숫자가 아닙니다.")
    for key in ("procurement_class", "region_limit", "lifecycle", "qualification_flags",
                "attachments", "focus_matches", "performance_matches"):
        expected = "list" if key in {"attachments", "focus_matches", "performance_matches"} else "dict"
        if not isinstance(notice.get(key), list if expected == "list" else dict):
            errors.append(f"{prefix}.{key}가 {expected}가 아닙니다.")
    errors.extend(_relative_posix_path(notice.get("raw_source"), f"{prefix}.raw_source"))
    errors.extend(_validate_nested_notice(notice, prefix))
    return errors


def validate_screening_input(value: Any) -> list[str]:
    errors = _keys_error(value, SCREENING_INPUT_KEYS, "screening-input")
    if errors or not isinstance(value, dict):
        return errors
    if value.get("schema_version") != "bidops.screening-input.v1":
        errors.append("screening-input.schema_version이 잘못되었습니다.")
    errors.extend(_execution_id(value.get("execution_id"), "screening-input.execution_id"))
    for key in ("run_id", "policy_version", "prompt_version", "company_profile_version"):
        if not _nonempty(value.get(key)):
            errors.append(f"screening-input.{key}가 비어 있습니다.")
    errors.extend(_timestamp(value.get("generated_at"), "screening-input.generated_at"))
    errors.extend(_window(value.get("source_window"), "screening-input.source_window"))
    errors.extend(_digest(value.get("company_profile_digest"), "screening-input.company_profile_digest"))
    errors.extend(_company_profile_version(
        value.get("company_profile_version"), value.get("company_profile_digest"),
        "screening-input.company_profile_version",
    ))
    errors.extend(_generation_config_errors(
        value.get("generation_config"), value.get("generation_config_digest"),
        "screening-input.generation_config",
    ))
    notices = value.get("notices")
    if not isinstance(notices, list):
        return errors + ["screening-input.notices가 배열이 아닙니다."]
    if (
        isinstance(value.get("candidate_count"), bool)
        or not isinstance(value.get("candidate_count"), int)
        or value.get("candidate_count") != len(notices)
    ):
        errors.append("screening-input.candidate_count가 notices 길이와 다릅니다.")
    seen: set[str] = set()
    for index, notice in enumerate(notices):
        prefix = f"screening-input.notices[{index}]"
        errors.extend(_keys_error(notice, (*COMMON_NOTICE_KEYS, "judgment_mode", "carry_over_from", "rejudge_reason"), prefix))
        if not isinstance(notice, dict):
            continue
        common = {key: notice.get(key) for key in COMMON_NOTICE_KEYS}
        errors.extend(validate_common_notice(common, prefix))
        notice_id = notice.get("notice_id")
        if not isinstance(notice_id, str):
            errors.append(f"{prefix}.notice_id는 문자열이어야 합니다.")
        elif notice_id in seen:
            errors.append(f"{prefix}.notice_id가 중복되었습니다: {notice_id}")
        else:
            seen.add(notice_id)
        mode = notice.get("judgment_mode")
        if not _enum(mode, JUDGMENT_MODES):
            errors.append(f"{prefix}.judgment_mode가 잘못되었습니다.")
        if mode == "승계":
            if not _nonempty(notice.get("carry_over_from")):
                errors.append(f"{prefix}.승계에는 carry_over_from이 필요합니다.")
            elif notice.get("carry_over_from") == value.get("run_id"):
                errors.append(f"{prefix}.carry_over_from가 현재 run_id와 같습니다.")
            if notice.get("rejudge_reason") is not None:
                errors.append(f"{prefix}.승계의 rejudge_reason은 null이어야 합니다.")
        elif mode == "재판정":
            if notice.get("carry_over_from") is not None:
                errors.append(f"{prefix}.재판정의 carry_over_from은 null이어야 합니다.")
            if not _enum(notice.get("rejudge_reason"), REJUDGE_REASONS):
                errors.append(f"{prefix}.재판정의 rejudge_reason이 잘못되었습니다.")
        elif mode == "신규":
            if notice.get("carry_over_from") is not None or notice.get("rejudge_reason") is not None:
                errors.append(f"{prefix}.신규의 승계/재판정 필드는 null이어야 합니다.")
    return errors


def _validate_perspectives_v3(value: Any, prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, list):
        return [f"{prefix}가 배열이 아닙니다."]
    if len(value) != len(REQUIRED_PERSPECTIVES):
        errors.append(f"{prefix}는 정확히 5개여야 합니다.")
    names: list[str] = []
    for index, item in enumerate(value):
        item_prefix = f"{prefix}[{index}]"
        errors.extend(_keys_error(item, PERSPECTIVE_KEYS, item_prefix))
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not _enum(name, set(REQUIRED_PERSPECTIVES)):
            errors.append(f"{item_prefix}.name이 잘못되었습니다.")
        else:
            names.append(name)
        if not _enum(item.get("assessment"), ASSESSMENTS):
            errors.append(f"{item_prefix}.assessment가 잘못되었습니다.")
        if not _nonempty(item.get("reason")) or len(item["reason"].strip()) < MIN_REASON_LENGTH:
            errors.append(f"{item_prefix}.reason은 trim 기준 10자 이상이어야 합니다.")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{item_prefix}.evidence가 비어 있습니다.")
            continue
        for evidence_index, entry in enumerate(evidence):
            entry_prefix = f"{item_prefix}.evidence[{evidence_index}]"
            errors.extend(_keys_error(entry, EVIDENCE_KEYS, entry_prefix))
            if isinstance(entry, dict):
                if not _nonempty(entry.get("source")) or not _nonempty(entry.get("fact")):
                    errors.append(f"{entry_prefix}의 source/fact가 비어 있습니다.")
                if not _enum(entry.get("status"), EVIDENCE_STATUS):
                    errors.append(f"{entry_prefix}.status가 잘못되었습니다.")
    if len(names) != len(set(names)):
        errors.append(f"{prefix}의 관점 이름이 중복되었습니다.")
    if set(names) != set(REQUIRED_PERSPECTIVES):
        errors.append(f"{prefix}는 다섯 관점을 정확히 한 번씩 가져야 합니다.")
    return errors


def _validate_judgment_v3(judgment: Any, notice: dict[str, Any], decisions: dict[str, Any], prefix: str) -> list[str]:
    errors = _keys_error(judgment, JUDGMENT_V3_KEYS, prefix)
    if errors or not isinstance(judgment, dict):
        return errors
    notice_id = judgment.get("notice_id")
    if notice_id != notice.get("notice_id"):
        errors.append(f"{prefix}.notice_id가 input notice와 다릅니다.")
    mode = notice.get("judgment_mode")
    if judgment.get("judgment_mode") != mode:
        errors.append(f"{prefix}.judgment_mode가 input과 다릅니다.")
    for key in ("model_name", "prompt_version", "policy_version", "company_profile_version"):
        if not _nonempty(judgment.get(key)):
            errors.append(f"{prefix}.{key}가 비어 있습니다.")
    errors.extend(_digest(judgment.get("model_digest"), f"{prefix}.model_digest"))
    errors.extend(_digest(judgment.get("company_profile_digest"), f"{prefix}.company_profile_digest"))
    errors.extend(_company_profile_version(
        judgment.get("company_profile_version"), judgment.get("company_profile_digest"),
        f"{prefix}.company_profile_version",
    ))
    if _enum(mode, {"신규", "재판정"}):
        for key in ("model_name", "model_digest", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest"):
            if judgment.get(key) != decisions.get(key):
                errors.append(f"{prefix}.{key}가 decisions top과 다릅니다.")
        if judgment.get("judged_in_run") != decisions.get("run_id") or judgment.get("recorded_in_run") != decisions.get("run_id"):
            errors.append(f"{prefix}.신규·재판정의 run 메타데이터가 현재 run과 다릅니다.")
        if judgment.get("carried_over") is not False:
            errors.append(f"{prefix}.신규·재판정의 carried_over는 false여야 합니다.")
        if judgment.get("rejudge_reason") != notice.get("rejudge_reason"):
            errors.append(f"{prefix}.rejudge_reason이 input과 다릅니다.")
        if mode == "신규" and judgment.get("rejudge_reason") is not None:
            errors.append(f"{prefix}.신규의 rejudge_reason은 null이어야 합니다.")
    elif mode == "승계":
        if judgment.get("carried_over") is not True:
            errors.append(f"{prefix}.승계의 carried_over는 true여야 합니다.")
        if judgment.get("recorded_in_run") != decisions.get("run_id"):
            errors.append(f"{prefix}.승계의 recorded_in_run이 현재 run과 다릅니다.")
        if judgment.get("judged_in_run") != notice.get("carry_over_from"):
            errors.append(f"{prefix}.승계의 judged_in_run은 input carry_over_from과 같아야 합니다.")
        if judgment.get("rejudge_reason") is not None or notice.get("rejudge_reason") is not None:
            errors.append(f"{prefix}.승계의 rejudge_reason은 null이어야 합니다.")
    else:
        errors.append(f"{prefix}.judgment_mode가 잘못되었습니다.")

    grade = judgment.get("grade")
    readiness = judgment.get("readiness")
    if not _enum(grade, GRADES):
        errors.append(f"{prefix}.grade가 잘못되었습니다.")
    if not _enum(readiness, READINESS):
        errors.append(f"{prefix}.readiness가 잘못되었습니다.")
    if not _enum(judgment.get("primary_focus"), FOCUS_AXES):
        errors.append(f"{prefix}.primary_focus가 잘못되었습니다.")
    if not _nonempty(judgment.get("summary")) or not _nonempty(judgment.get("next_action")):
        errors.append(f"{prefix}.summary/next_action은 비어 있을 수 없습니다.")
    category = judgment.get("exclusion_category")
    if grade == "제외":
        if not _enum(readiness, {"해당 없음", "참여 불가 확인"}):
            errors.append(f"{prefix}.제외 등급의 readiness가 잘못되었습니다.")
        if not _enum(category, EXCLUSION_CATEGORIES):
            errors.append(f"{prefix}.제외 등급에는 exclusion_category가 필요합니다.")
    elif category is not None:
        errors.append(f"{prefix}.제외가 아닌 등급의 exclusion_category는 null이어야 합니다.")

    errors.extend(_validate_perspectives_v3(judgment.get("perspectives"), f"{prefix}.perspectives"))
    matched = judgment.get("matched_performances")
    if not isinstance(matched, list):
        errors.append(f"{prefix}.matched_performances가 배열이 아닙니다.")
    else:
        for index, item in enumerate(matched):
            item_prefix = f"{prefix}.matched_performances[{index}]"
            errors.extend(_keys_error(item, MATCHED_PERFORMANCE_KEYS, item_prefix))
            if isinstance(item, dict):
                for key in ("name", "match_reason", "mismatch_or_limit", "source"):
                    if not _nonempty(item.get(key)):
                        errors.append(f"{item_prefix}.{key}가 비어 있습니다.")
                if not _enum(item.get("status"), EVIDENCE_STATUS):
                    errors.append(f"{item_prefix}.status가 잘못되었습니다.")
        if notice.get("performance_matches") and not matched:
            errors.append(f"{prefix} 수행실적 신호가 있으나 matched_performances가 비어 있습니다.")

    counterarguments = judgment.get("counterarguments")
    if not isinstance(counterarguments, list) or not counterarguments or any(not _nonempty(item) for item in counterarguments):
        errors.append(f"{prefix}.counterarguments는 nonblank 문자열 1개 이상이어야 합니다.")
    resolutions = judgment.get("counterargument_resolutions")
    if not isinstance(resolutions, list):
        errors.append(f"{prefix}.counterargument_resolutions가 배열이 아닙니다.")
    elif isinstance(counterarguments, list):
        if len(resolutions) != len(counterarguments):
            errors.append(f"{prefix}.반론과 반론 해결의 길이가 다릅니다.")
        for index, item in enumerate(resolutions):
            item_prefix = f"{prefix}.counterargument_resolutions[{index}]"
            errors.extend(_keys_error(item, RESOLUTION_KEYS, item_prefix))
            if isinstance(item, dict):
                if index < len(counterarguments) and item.get("counterargument") != counterarguments[index]:
                    errors.append(f"{item_prefix}.counterargument가 원 반론과 일치하지 않습니다.")
                if not _enum(item.get("status"), {"수용", "기각", "추가 확인"}):
                    errors.append(f"{item_prefix}.status가 잘못되었습니다.")
                if not _nonempty(item.get("reflection")):
                    errors.append(f"{item_prefix}.reflection이 비어 있습니다.")

    verification = judgment.get("verification_items")
    if not isinstance(verification, list):
        errors.append(f"{prefix}.verification_items가 배열이 아닙니다.")
    else:
        for index, item in enumerate(verification):
            item_prefix = f"{prefix}.verification_items[{index}]"
            errors.extend(_keys_error(item, VERIFICATION_KEYS, item_prefix))
            if isinstance(item, dict):
                for key in ("item", "why"):
                    if not _nonempty(item.get(key)):
                        errors.append(f"{item_prefix}.{key}가 비어 있습니다.")
                if not isinstance(item.get("blocking"), bool):
                    errors.append(f"{item_prefix}.blocking이 불리언이 아닙니다.")
                if not _enum(item.get("status"), VERIFICATION_STATUS):
                    errors.append(f"{item_prefix}.status가 잘못되었습니다.")
                if not isinstance(item.get("requires_attachment"), bool):
                    errors.append(f"{item_prefix}.requires_attachment가 불리언이 아닙니다.")
        blocking_unknown = [
            item for item in verification
            if isinstance(item, dict) and item.get("blocking") and item.get("status") == "미확인"
        ]
        if readiness == "부분 확인 필요" and not verification:
            errors.append(f"{prefix}.부분 확인 필요에는 확인 항목이 필요합니다.")
        if readiness == "확인 완료" and blocking_unknown:
            errors.append(f"{prefix}.확인 완료인데 blocking 미확인 항목이 있습니다.")
        if readiness == "참여 불가 확인" and not any(
            isinstance(item, dict) and item.get("blocking") for item in verification
        ):
            errors.append(f"{prefix}.참여 불가 확인에는 blocking 항목이 필요합니다.")

    perspective_values = judgment.get("perspectives")
    if not isinstance(perspective_values, list):
        perspective_values = []
    business = next((item for item in perspective_values if isinstance(item, dict) and item.get("name") == "사업성·자격 제약"), None)
    expected_flag = isinstance(business, dict) and business.get("assessment") == "확인 불가" and _enum(grade, {"관찰 대상", "제외"})
    if judgment.get("two_axis_mixing_flag") is not expected_flag:
        errors.append(f"{prefix}.two_axis_mixing_flag가 결정 규칙과 다릅니다.")
    expected_label = "확인 요망" if expected_flag else None
    if judgment.get("two_axis_mixing_label") != expected_label:
        errors.append(f"{prefix}.two_axis_mixing_label이 결정 규칙과 다릅니다.")
    return errors


def validate_failures(value: Any, *, execution_id: str | None = None, run_id: str | None = None) -> list[str]:
    errors = _keys_error(value, FAILURES_TOP_KEYS, "screening-failures")
    if errors or not isinstance(value, dict):
        return errors
    if value.get("schema_version") != "bidops.screening-failures.v1":
        errors.append("screening-failures.schema_version이 잘못되었습니다.")
    errors.extend(_execution_id(value.get("execution_id"), "screening-failures.execution_id"))
    if execution_id is not None and value.get("execution_id") != execution_id:
        errors.append("screening-failures.execution_id가 input과 다릅니다.")
    if not _nonempty(value.get("run_id")):
        errors.append("screening-failures.run_id가 비어 있습니다.")
    if run_id is not None and value.get("run_id") != run_id:
        errors.append("screening-failures.run_id가 input과 다릅니다.")
    errors.extend(_timestamp(value.get("generated_at"), "screening-failures.generated_at"))
    failures = value.get("failures")
    if not isinstance(failures, list):
        return errors + ["screening-failures.failures가 배열이 아닙니다."]
    if isinstance(value.get("failure_count"), bool) or not isinstance(value.get("failure_count"), int) or value.get("failure_count") != len(failures):
        errors.append("screening-failures.failure_count가 failures 길이와 다릅니다.")
    seen: set[tuple[Any, Any]] = set()
    seen_notice_ids: set[Any] = set()
    for index, failure in enumerate(failures):
        prefix = f"screening-failures.failures[{index}]"
        errors.extend(_keys_error(failure, FAILURE_KEYS, prefix))
        if not isinstance(failure, dict):
            continue
        failure_notice_id = failure.get("notice_id")
        failure_stage = failure.get("failed_stage")
        if isinstance(failure_notice_id, str) and isinstance(failure_stage, str):
            key = (failure_notice_id, failure_stage)
            if key in seen:
                errors.append(f"{prefix}의 (notice_id, failed_stage)가 중복되었습니다.")
            seen.add(key)
        if isinstance(failure_notice_id, str):
            if failure_notice_id in seen_notice_ids:
                errors.append(f"{prefix}.notice_id가 중복되었습니다.")
            seen_notice_ids.add(failure_notice_id)
        if not _nonempty(failure.get("notice_id")):
            errors.append(f"{prefix}.notice_id가 비어 있습니다.")
        if not _enum(failure.get("failed_stage"), FAILURE_STAGES):
            errors.append(f"{prefix}.failed_stage가 잘못되었습니다.")
        if not _enum(failure.get("failure_type"), FAILURE_TYPES):
            errors.append(f"{prefix}.failure_type가 잘못되었습니다.")
        errors.extend(_timestamp(failure.get("last_attempt_at"), f"{prefix}.last_attempt_at"))
        if not isinstance(failure.get("retry_count"), int) or isinstance(failure.get("retry_count"), bool) or failure.get("retry_count") < 0:
            errors.append(f"{prefix}.retry_count가 0 이상 정수가 아닙니다.")
        if failure.get("status") != FAILURE_STATUS:
            errors.append(f"{prefix}.status가 사람 검토 대기가 아닙니다.")
        context = failure.get("failure_context")
        if context not in (None, "carried_over_validation"):
            errors.append(f"{prefix}.failure_context가 잘못되었습니다.")
        if context == "carried_over_validation" and failure.get("failed_stage") != "병합·검증":
            errors.append(f"{prefix}.승계 검증 실패는 병합·검증 단계여야 합니다.")
        for key in ("trace_id", "span_id"):
            if failure.get(key) is not None and not _nonempty(failure.get(key)):
                errors.append(f"{prefix}.{key}가 비어 있습니다.")
        if _enum(failure.get("failed_stage"), MODEL_FAILURE_STAGES):
            if not _nonempty(failure.get("trace_id")) or not _nonempty(failure.get("span_id")):
                errors.append(f"{prefix} 모델 단계 실패에는 trace_id/span_id가 필요합니다.")
        elif failure.get("failed_stage") == "병합·검증":
            if failure.get("trace_id") is not None or failure.get("span_id") is not None:
                errors.append(f"{prefix} 병합·검증 실패의 trace_id/span_id는 null이어야 합니다.")
        if not _nonempty(failure.get("error_summary")):
            errors.append(f"{prefix}.error_summary가 비어 있습니다.")
    return errors


def _validate_failure_context(failure: dict[str, Any], notice: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    if notice.get("judgment_mode") == "승계" and failure.get("failure_context") != "carried_over_validation":
        errors.append(f"{prefix} 승계 공고 실패는 carried_over_validation이어야 합니다.")
    if notice.get("judgment_mode") != "승계" and failure.get("failure_context") == "carried_over_validation":
        errors.append(f"{prefix}.carried_over_validation은 승계 공고에만 허용됩니다.")
    if failure.get("failure_context") != "carried_over_validation":
        return errors
    if notice.get("judgment_mode") != "승계":
        errors.append(f"{prefix}.carried_over_validation은 승계 공고에만 허용됩니다.")
    if failure.get("failed_stage") != "병합·검증":
        errors.append(f"{prefix}.carried_over_validation은 병합·검증 단계여야 합니다.")
    if failure.get("failure_type") != "schema_violation":
        errors.append(f"{prefix}.carried_over_validation은 schema_violation이어야 합니다.")
    if failure.get("trace_id") is not None or failure.get("span_id") is not None:
        errors.append(f"{prefix}.carried_over_validation의 trace_id/span_id는 null이어야 합니다.")
    return errors


def _read_failure_artifact(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    path = Path(value)
    if not path.is_file():
        raise SystemExit(f"실패 artifact를 찾을 수 없습니다: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"실패 artifact를 읽을 수 없습니다: {path}: {error}") from error


def merge(
    validation: dict[str, Any],
    decisions: dict[str, Any],
    failures: dict[str, Any] | str | Path | float | int | None = None,
    boilerplate_ratio: float = DEFAULT_BOILERPLATE_RATIO,
    *,
    failure_artifact: dict[str, Any] | str | Path | None = None,
) -> dict[str, Any]:
    """Merge either the historical v2 pair or the complete v3 contract.

    ``failures`` is optional only for complete v3 runs.  A positional numeric
    third argument retains the old ``merge(..., boilerplate_ratio)`` API.
    """

    if failure_artifact is not None:
        if failures is not None:
            raise SystemExit("failures와 failure_artifact 중 하나만 지정해야 합니다.")
        failures = failure_artifact
    if isinstance(failures, (int, float)) and not isinstance(failures, bool):
        boilerplate_ratio = float(failures)
        failures = None
    if not isinstance(validation, dict):
        raise SystemExit("판정 입력 최상위 객체가 아닙니다.")
    if not isinstance(decisions, dict):
        raise SystemExit("판정 decisions 최상위 객체가 아닙니다.")
    if validation.get("schema_version") == "bidops.validation-set.v2" and decisions.get("schema_version") == "bidops.decisions.v2":
        return _merge_v2(validation, decisions, boilerplate_ratio)
    if validation.get("schema_version") != "bidops.screening-input.v1":
        raise SystemExit(f"지원하지 않는 판정 입력 스키마입니다: {validation.get('schema_version')}")
    if decisions.get("schema_version") != "bidops.decisions.v3":
        raise SystemExit(f"지원하지 않는 판정 스키마입니다: {decisions.get('schema_version')}")

    errors = validate_screening_input(validation)
    errors.extend(_keys_error(decisions, DECISIONS_V3_KEYS, "decisions"))
    try:
        canonical_json_bytes(validation)
        canonical_json_bytes(decisions)
    except (TypeError, ValueError) as error:
        errors.append(f"canonical JSON으로 직렬화할 수 없습니다: {error}")
    if errors:
        raise SystemExit("입력 계약을 만족하지 않습니다.\n- " + "\n- ".join(errors))
    errors = []
    errors.extend(_execution_id(decisions.get("execution_id"), "decisions.execution_id"))
    for key in ("execution_id", "run_id", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest"):
        if decisions.get(key) != validation.get(key):
            errors.append(f"decisions.{key}가 screening-input과 다릅니다.")
    errors.extend(_timestamp(decisions.get("generated_at"), "decisions.generated_at"))
    for key in ("screening_basis", "model_name"):
        if not _nonempty(decisions.get(key)):
            errors.append(f"decisions.{key}가 비어 있습니다.")
    errors.extend(_digest(decisions.get("model_digest"), "decisions.model_digest"))
    errors.extend(_company_profile_version(
        decisions.get("company_profile_version"), decisions.get("company_profile_digest"),
        "decisions.company_profile_version",
    ))
    errors.extend(_generation_config_errors(
        decisions.get("generation_config"), decisions.get("generation_config_digest"),
        "decisions.generation_config",
    ))
    if decisions.get("generation_config") != validation.get("generation_config") or decisions.get("generation_config_digest") != validation.get("generation_config_digest"):
        errors.append("decisions generation config가 screening-input과 다릅니다.")
    judgments = decisions.get("judgments")
    if not isinstance(judgments, list):
        errors.append("decisions.judgments가 배열이 아닙니다.")
        raise SystemExit("입력 계약을 만족하지 않습니다.\n- " + "\n- ".join(errors))

    notices_by_id = {notice["notice_id"]: notice for notice in validation["notices"]}
    failure_artifact = _read_failure_artifact(failures)
    if failure_artifact is not None:
        errors.extend(validate_failures(
            failure_artifact,
            execution_id=validation.get("execution_id"),
            run_id=validation.get("run_id"),
        ))
        if isinstance(failure_artifact, dict):
            failure_values = failure_artifact.get("failures")
            for index, failure in enumerate(failure_values if isinstance(failure_values, list) else []):
                if not isinstance(failure, dict):
                    continue
                failure_notice_id = failure.get("notice_id")
                if not isinstance(failure_notice_id, str):
                    continue
                notice = notices_by_id.get(failure_notice_id)
                if notice is not None:
                    errors.extend(_validate_failure_context(
                        failure, notice, f"screening-failures.failures[{index}]"
                    ))
    elif len(judgments) != len(validation.get("notices", [])):
        errors.append("판정이 일부 누락되었지만 screening-failures artifact가 없습니다.")
    if errors:
        raise SystemExit("입력 계약을 만족하지 않습니다.\n- " + "\n- ".join(errors))

    failures_by_id: dict[str, dict[str, Any]] = {}
    failure_ids: set[str] = set()
    if failure_artifact is not None:
        failures_by_id = {failure["notice_id"]: failure for failure in failure_artifact["failures"]}
        failure_ids = set(failures_by_id)
    judgment_by_id: dict[str, dict[str, Any]] = {}
    for judgment in judgments:
        notice_id = judgment.get("notice_id") if isinstance(judgment, dict) else None
        if not isinstance(notice_id, str) or not notice_id:
            errors.append(f"판정 notice_id가 문자열이 아니거나 비어 있습니다: {notice_id}")
        elif notice_id in judgment_by_id:
            errors.append(f"판정 notice_id가 없거나 중복되었습니다: {notice_id}")
        else:
            judgment_by_id[notice_id] = judgment
    if set(judgment_by_id) & set(failures_by_id):
        errors.append("성공 판정과 실패 artifact의 notice_id가 겹칩니다.")
    if (set(judgment_by_id) | failure_ids) != set(notices_by_id):
        missing = sorted(set(notices_by_id) - set(judgment_by_id) - failure_ids)
        extra = sorted((set(judgment_by_id) | failure_ids) - set(notices_by_id))
        if missing:
            errors.append(f"판정·실패 어디에도 없는 공고가 있습니다: {', '.join(missing)}")
        if extra:
            errors.append(f"input에 없는 판정·실패 공고가 있습니다: {', '.join(extra)}")
    for notice_id, judgment in judgment_by_id.items():
        if notice_id not in notices_by_id:
            continue
        errors.extend(_validate_judgment_v3(
            judgment, notices_by_id[notice_id], decisions, f"judgments[{notice_id}]"
        ))
    if errors:
        raise SystemExit("판정이 계약을 만족하지 않습니다.\n- " + "\n- ".join(errors))
    errors.extend(boilerplate_errors(list(judgment_by_id.values()), boilerplate_ratio))
    if errors:
        raise SystemExit("판정이 계약을 만족하지 않습니다.\n- " + "\n- ".join(errors))

    results: list[dict[str, Any]] = []
    for notice in validation["notices"]:
        notice_id = notice["notice_id"]
        judgment = judgment_by_id.get(notice_id)
        if judgment is None:
            continue
        output_judgment = {key: value for key, value in judgment.items() if key != "notice_id"}
        results.append({"notice": {key: notice[key] for key in COMMON_NOTICE_KEYS}, "judgment": output_judgment})
    failure_count = len(failure_artifact["failures"]) if failure_artifact is not None else 0
    if len(validation["notices"]) != len(results) + failure_count:
        raise SystemExit("candidate_count가 result_count와 failure_count의 합과 다릅니다.")
    return {
        "schema_version": "bidops.screening.v3",
        "execution_id": validation["execution_id"],
        "generated_at": decisions["generated_at"],
        "screening_basis": decisions["screening_basis"],
        "source_window": validation["source_window"],
        "model_name": decisions["model_name"],
        "model_digest": decisions["model_digest"],
        "prompt_version": decisions["prompt_version"],
        "policy_version": decisions["policy_version"],
        "company_profile_version": decisions["company_profile_version"],
        "company_profile_digest": decisions["company_profile_digest"],
        "generation_config": decisions["generation_config"],
        "generation_config_digest": decisions["generation_config_digest"],
        "candidate_count": len(validation["notices"]),
        "result_count": len(results),
        "failure_count": failure_count,
        "partial_artifact": failure_count > 0,
        "failure_artifact": "screening-failures.json" if failure_count else None,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("validation_set", type=Path)
    parser.add_argument("decisions", type=Path)
    parser.add_argument(
        "--failures", type=Path,
        help="partial v3 run의 screening-failures.json 경로",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--boilerplate-ratio", type=float, default=DEFAULT_BOILERPLATE_RATIO
    )
    args = parser.parse_args()

    output = merge(
        json.loads(args.validation_set.read_text(encoding="utf-8")),
        json.loads(args.decisions.read_text(encoding="utf-8")),
        args.failures,
        args.boilerplate_ratio,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if output.get("schema_version") == "bidops.screening.v3":
        args.output.write_bytes(canonical_json_bytes(output))
    else:
        args.output.write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {"output": str(args.output), "results": len(output["results"])},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
