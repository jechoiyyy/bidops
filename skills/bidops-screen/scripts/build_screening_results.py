#!/usr/bin/env python3
"""Validate agent-authored judgments and merge them with the validation set.

This step never supplies content. A judgment that omits perspectives, evidence,
counterarguments, or verification items is rejected, because a default filled in
here would reach the report as if an agent had reasoned about the notice.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
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
    unexpected = [name for name in names if name not in REQUIRED_PERSPECTIVES]
    if unexpected:
        errors.append(f"{prefix} 계약에 없는 관점 이름입니다: {', '.join(map(str, unexpected))}")
    for item in perspectives:
        if not isinstance(item, dict):
            errors.append(f"{prefix} 관점 항목이 객체가 아닙니다.")
            continue
        name = item.get("name")
        if item.get("assessment") not in ASSESSMENTS:
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
            if entry.get("status") not in EVIDENCE_STATUS:
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
        if item.get("status") not in VERIFICATION_STATUS:
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
    if grade not in GRADES:
        errors.append(f"{prefix} 잘못된 등급: {grade}")
    if readiness not in READINESS:
        errors.append(f"{prefix} 잘못된 참여 준비 상태: {readiness}")
    if judgment.get("primary_focus") not in FOCUS_AXES:
        errors.append(f"{prefix} primary_focus가 계약의 축 목록에 없습니다.")
    if not non_empty(judgment.get("summary")):
        errors.append(f"{prefix} summary가 비어 있습니다.")
    if not non_empty(judgment.get("next_action")):
        errors.append(f"{prefix} next_action이 비어 있습니다.")

    category = judgment.get("exclusion_category")
    if grade == "제외":
        if readiness not in {"해당 없음", "참여 불가 확인"}:
            errors.append(
                f"{prefix} 제외 등급의 참여 준비 상태는 '해당 없음' 또는 "
                "'참여 불가 확인'이어야 합니다."
            )
        if category not in EXCLUSION_CATEGORIES:
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
        for text in judgment.get("counterarguments", []) or []:
            if non_empty(text):
                counts[text.strip()] += 1
    return [
        f"동일한 반론이 {count}/{total}건에서 반복됩니다: {text}"
        for text, count in counts.items()
        if count > limit
    ]


def merge(
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
        if not notice_id or notice_id in by_id:
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("validation_set", type=Path)
    parser.add_argument("decisions", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--boilerplate-ratio", type=float, default=DEFAULT_BOILERPLATE_RATIO
    )
    args = parser.parse_args()

    output = merge(
        json.loads(args.validation_set.read_text(encoding="utf-8")),
        json.loads(args.decisions.read_text(encoding="utf-8")),
        args.boilerplate_ratio,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
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
