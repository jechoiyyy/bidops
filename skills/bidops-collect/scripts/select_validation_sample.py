#!/usr/bin/env python3
"""Select a deterministic BidOps validation set: 30 analysis, 10 audit records."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


AXES = ("AI/데이터", "블록체인·DID", "공공 SI·통합관리")
PERFORMANCE_STRATUM = "수행실적 유사"
ANALYSIS_STRATA = (*AXES, PERFORMANCE_STRATUM)

CLASSIFICATION_STRATUM = "분류 근접"
NEAR_MISS_STRATUM = "실적 유사 근접"
RANDOM_STRATUM = "무작위"
AUDIT_STRATA = (CLASSIFICATION_STRATUM, NEAR_MISS_STRATUM, RANDOM_STRATUM)

# Procurement classes that describe a digital deliverable. A record that carries
# one of them and still failed retrieval is the most informative audit case,
# because a random draw from 2,000 unrelated notices cannot measure recall.
DIGITAL_MIDDLE_CLASSES = {
    "SW 및 시스템 개발",
    "운영 및 유지관리",
    "ICT사업 컨설팅",
    "DB구축 및 자료입력",
    "시스템 운영환경 구축",
    "정보보호서비스",
    "통신서비스",
}

# Portfolio similarity that came close to the retrieval threshold.
NEAR_MISS_MIN_SCORE = 0.40


def stable_key(item: dict[str, Any]) -> str:
    return hashlib.sha256(str(item.get("notice_id", "")).encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--analysis-count", type=int, default=30)
    parser.add_argument("--audit-count", type=int, default=10)
    return parser.parse_args()


def load_collection(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("schema_version") != "bidops.collected.v2":
        raise SystemExit(
            "지원하지 않는 수집 스키마입니다: "
            f"{source.get('schema_version')} (bidops.collected.v2가 필요합니다)"
        )
    return source


def notice_axes(item: dict[str, Any]) -> set[str]:
    return {signal["axis"] for signal in item.get("focus_matches", [])}


def in_analysis_stratum(item: dict[str, Any], stratum: str) -> bool:
    if stratum == PERFORMANCE_STRATUM:
        return bool(item.get("performance_matches"))
    return stratum in notice_axes(item)


def in_audit_stratum(item: dict[str, Any], stratum: str) -> bool:
    if stratum == CLASSIFICATION_STRATUM:
        middle = (item.get("procurement_class") or {}).get("middle")
        return middle in DIGITAL_MIDDLE_CLASSES
    if stratum == NEAR_MISS_STRATUM:
        return float(item.get("performance_top_score") or 0.0) >= NEAR_MISS_MIN_SCORE
    return True


def rotate_strata(
    pool: list[dict[str, Any]],
    strata: tuple[str, ...],
    membership,
    target: int,
) -> list[dict[str, Any]]:
    """Draw one record per stratum in turn until the target count is reached."""
    by_stratum = {
        stratum: sorted(
            [item for item in pool if membership(item, stratum)], key=stable_key
        )
        for stratum in strata
    }
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    while len(selected) < target:
        drawn_this_round = False
        for stratum in strata:
            while (
                by_stratum[stratum]
                and by_stratum[stratum][0]["notice_id"] in selected_ids
            ):
                by_stratum[stratum].pop(0)
            if by_stratum[stratum] and len(selected) < target:
                item = by_stratum[stratum].pop(0)
                selected.append(dict(item, sample_stratum=stratum))
                selected_ids.add(item["notice_id"])
                drawn_this_round = True
        if not drawn_this_round:
            break
    return selected


def select_analysis(
    candidates: list[dict[str, Any]], target: int
) -> list[dict[str, Any]]:
    selected = rotate_strata(candidates, ANALYSIS_STRATA, in_analysis_stratum, target)
    selected_ids = {item["notice_id"] for item in selected}
    remainder = sorted(
        [item for item in candidates if item["notice_id"] not in selected_ids],
        key=stable_key,
    )
    selected.extend(
        dict(item, sample_stratum=RANDOM_STRATUM)
        for item in remainder[: max(0, target - len(selected))]
    )
    return selected[:target]


def select_audit(audit_pool: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    return rotate_strata(audit_pool, AUDIT_STRATA, in_audit_stratum, target)


def main() -> int:
    args = parse_args()
    source = load_collection(json.loads(args.input.read_text(encoding="utf-8")))
    notices = source.get("notices", [])
    candidates = [item for item in notices if item.get("collection_bucket") == "candidate_pool"]
    audit_pool = [item for item in notices if item.get("collection_bucket") == "audit_pool"]

    analysis = select_analysis(candidates, args.analysis_count)
    audits = select_audit(audit_pool, args.audit_count)
    sampled = [dict(item, sample_role="analysis") for item in analysis]
    sampled.extend(dict(item, sample_role="audit") for item in audits)

    warnings: list[str] = []
    if len(analysis) < args.analysis_count:
        warnings.append(
            f"분석 표본이 {len(analysis)}건으로 목표 {args.analysis_count}건에 미달합니다."
        )
    if len(audits) < args.audit_count:
        warnings.append(
            f"감사 표본이 {len(audits)}건으로 목표 {args.audit_count}건에 미달합니다."
        )
    for stratum in AUDIT_STRATA[:-1]:
        drawn = sum(1 for item in audits if item["sample_stratum"] == stratum)
        available = sum(1 for item in audit_pool if in_audit_stratum(item, stratum))
        if available and not drawn:
            warnings.append(
                f"감사 층 '{stratum}'에 {available}건이 있으나 표본에 배정되지 않았습니다."
            )

    axis_counts = {
        axis: sum(axis in notice_axes(item) for item in analysis) for axis in AXES
    }
    title_only = sum(
        1
        for item in analysis
        if "focus_title" in item.get("candidate_sources", [])
    )
    classification_only = sum(
        1
        for item in analysis
        if item.get("candidate_sources") == ["focus_classification"]
    )
    result = {
        "schema_version": "bidops.validation-set.v2",
        "source_window": source["source_window"],
        "selection": {
            "analysis_target": args.analysis_count,
            "audit_target": args.audit_count,
            "analysis_selected": len(analysis),
            "audit_selected": len(audits),
            "analysis_axis_counts": axis_counts,
            "analysis_title_signal_count": title_only,
            "analysis_classification_only_count": classification_only,
            "analysis_performance_match_count": sum(
                bool(item.get("performance_matches")) for item in analysis
            ),
            "analysis_performance_only_count": sum(
                1
                for item in analysis
                if item.get("candidate_sources") == ["performance_similarity"]
            ),
            "audit_stratum_counts": {
                stratum: sum(1 for item in audits if item["sample_stratum"] == stratum)
                for stratum in AUDIT_STRATA
            },
        },
        "warnings": warnings,
        "notices": sampled,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), **result["selection"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
