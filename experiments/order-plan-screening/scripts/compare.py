#!/usr/bin/env python3
"""Build the bounded CSV and Markdown comparison from completed human labels."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from common import (
    ExperimentError,
    load_json,
    load_run_population,
    safe_ratio,
    validate_method_result,
    validate_result_run_binding,
)
from make_review_set import (
    METHOD_NAMES,
    read_labels,
    validate_manifest_selection,
    validate_review_manifest,
)


COMPARISON_FIELDS = (
    "method",
    "selected_count",
    "precision_at_50",
    "relevant_high_at_50",
    "unique_relevant_in_candidate_union",
    "candidate_union_relative_recall",
    "overlap_jaccard_keyword",
    "overlap_jaccard_bge_m3_colbert",
    "overlap_jaccard_qwen",
    "overlap_jaccard_luna",
    "success_count",
    "failure_count",
    "elapsed_ms",
    "total_latency_ms",
    "average_latency_ms",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "cost_usd",
    "device",
    "audit_relevant_count",
    "audit_sample_count",
    "full_recall",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def selected_ids(result: dict[str, Any]) -> set[str]:
    return {row["plan_id"] for row in result["items"] if row["selected"]}


def jaccard(left: set[str], right: set[str]) -> float | None:
    union = left | right
    return safe_ratio(len(left & right), len(union))


def build_comparison_rows(
    results: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, str]],
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    roles = {item["plan_id"]: item["selection_role"] for item in manifest["items"]}
    candidate_ids = {plan_id for plan_id, role in roles.items() if role == "candidate_union"}
    audit_ids = {plan_id for plan_id, role in roles.items() if role == "audit"}
    relevant_candidate = {plan_id for plan_id in candidate_ids if labels[plan_id]["relevance"] == "관련"}
    relevant_audit = {plan_id for plan_id in audit_ids if labels[plan_id]["relevance"] == "관련"}
    selections = {method: selected_ids(result) for method, result in results.items()}
    rows: list[dict[str, Any]] = []
    for method in METHOD_NAMES:
        method_selected = selections[method]
        relevant_selected = {plan_id for plan_id in method_selected if labels[plan_id]["relevance"] == "관련"}
        important_selected = {
            plan_id
            for plan_id in method_selected
            if labels[plan_id]["relevance"] == "관련" and labels[plan_id]["priority"] == "높음"
        }
        other_selected = set().union(
            *(selection for other, selection in selections.items() if other != method)
        )
        unique_relevant = relevant_selected - other_selected
        metrics = results[method]["metrics"]
        row: dict[str, Any] = {
            "method": method,
            "selected_count": len(method_selected),
            "precision_at_50": safe_ratio(len(relevant_selected), len(method_selected)),
            "relevant_high_at_50": len(important_selected),
            "unique_relevant_in_candidate_union": len(unique_relevant),
            "candidate_union_relative_recall": safe_ratio(
                len(relevant_selected), len(relevant_candidate)
            ),
            "success_count": metrics.get("success_count"),
            "failure_count": metrics.get("failure_count"),
            "elapsed_ms": metrics.get("elapsed_ms"),
            "total_latency_ms": metrics.get("total_latency_ms"),
            "average_latency_ms": metrics.get("average_latency_ms"),
            "input_tokens": metrics.get("input_tokens"),
            "cached_input_tokens": metrics.get("cached_input_tokens"),
            "output_tokens": metrics.get("output_tokens"),
            "cost_usd": metrics.get("cost_usd"),
            "device": metrics.get("device"),
            "audit_relevant_count": len(relevant_audit),
            "audit_sample_count": len(audit_ids),
            "full_recall": None,
        }
        for other in METHOD_NAMES:
            row[f"overlap_jaccard_{other}"] = jaccard(method_selected, selections[other])
        rows.append(row)
    return rows


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return value


def write_comparison_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COMPARISON_FIELDS, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: csv_value(row.get(field)) for field in COMPARISON_FIELDS})
    except FileExistsError as exc:
        raise ExperimentError("artifact_exists", "기존 comparison.csv를 덮어쓸 수 없습니다") from exc
    except (OSError, csv.Error) as exc:
        raise ExperimentError("artifact_write_failed", "comparison.csv를 쓸 수 없습니다") from exc


def render_percent(value: Any) -> str:
    return "계산 불가" if value is None else f"{float(value) * 100:.1f}%"


def render_value(value: Any) -> str:
    return "미측정" if value is None else str(value)


def render_report(
    run: dict[str, Any],
    population: dict[str, Any],
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
) -> str:
    audit_relevant = rows[0]["audit_relevant_count"] if rows else 0
    lines = [
        "# 발주계획 선별 방법 간이 비교",
        "",
        f"- 실행 ID: `{run['run_id']}`",
        f"- 고정 모집단: {len(population['items'])}건",
        f"- 사람 검토: 후보 합집합 {manifest['candidate_union_count']}건 + 감사 표본 {manifest['audit_count']}건",
        "- 전체 recall: 미측정",
        "",
        "## 품질 비교",
        "",
        "| 방법 | Precision@50 | 관련+높음 | 고유 관련 | 후보 합집합 기준 상대 회수율 | 성공/실패 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {method} | {precision} | {important} | {unique} | {relative} | {success}/{failure} |".format(
                method=row["method"],
                precision=render_percent(row["precision_at_50"]),
                important=row["relevant_high_at_50"],
                unique=row["unique_relevant_in_candidate_union"],
                relative=render_percent(row["candidate_union_relative_recall"]),
                success=render_value(row["success_count"]),
                failure=render_value(row["failure_count"]),
            )
        )
    lines.extend(
        [
            "",
            "`고유 관련`과 `후보 합집합 기준 상대 회수율`은 네 방법의 Top 50 합집합 안에서만 계산했다. 전체 모집단 recall로 해석하지 않는다.",
            "",
            "## 실행 부담",
            "",
            "| 방법 | 실제 총 소요(ms) | 측정 지연 합(ms) | 건당 지연(ms) | 입력/캐시/출력 token | 비용(USD) | 장치 |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        tokens = (
            "미측정"
            if (
                row["input_tokens"] is None
                and row["cached_input_tokens"] is None
                and row["output_tokens"] is None
            )
            else (
                f"{render_value(row['input_tokens'])}/"
                f"{render_value(row['cached_input_tokens'])}/"
                f"{render_value(row['output_tokens'])}"
            )
        )
        lines.append(
            f"| {row['method']} | {render_value(row['elapsed_ms'])} | "
            f"{render_value(row['total_latency_ms'])} | "
            f"{render_value(row['average_latency_ms'])} | {tokens} | "
            f"{render_value(row['cost_usd'])} | {render_value(row['device'])} |"
        )
    lines.extend(
        [
            "",
            "## 중복과 감사 표본",
            "",
            "방법 간 Top 50 중복은 `comparison.csv`의 pairwise Jaccard 열에 기록했다. "
            f"네 방법 모두 Top 50 밖인 감사 표본 {manifest['audit_count']}건 중 관련은 {audit_relevant}건이었다. "
            "이 값은 중요 누락 위험을 보는 신호이며 전체 recall의 추정치가 아니다.",
            "",
            "## 한계와 후속 판단",
            "",
            "이 비교는 2026-08-24~26의 고정 3일 구간, 단일 평가자, Top 50과 50건 감사 표본에 한정된다. "
            "점수는 방법 내부 순위에만 사용했고 방법 간 확률처럼 비교하지 않았다. 실패와 미측정 값은 0으로 보정하지 않았다. "
            "자동 우승 점수나 운영 정책 활성화는 수행하지 않으며, 담당자가 품질·비용·누락 사례를 함께 검토해 후속 후보를 정한다.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise ExperimentError("artifact_exists", "기존 report.md를 덮어쓸 수 없습니다") from exc
    except OSError as exc:
        raise ExperimentError("artifact_write_failed", "report.md를 쓸 수 없습니다") from exc


def main() -> int:
    args = parse_args()
    try:
        run_dir = args.run_dir.resolve()
        run, population = load_run_population(run_dir)
        manifest = validate_review_manifest(
            load_json(run_dir / "review" / "manifest.json"), run, population
        )
        results = {
            method: validate_method_result(
                load_json(run_dir / "results" / f"{method}.json"),
                population,
                method,
                run["selection"]["top_k"],
            )
            for method in METHOD_NAMES
        }
        for result in results.values():
            validate_result_run_binding(result, run)
        validate_manifest_selection(manifest, population, results)
        labels_path = args.labels.resolve() if args.labels else run_dir / "review" / "labels.tsv"
        labels = read_labels(labels_path, manifest, population)
        rows = build_comparison_rows(results, labels, manifest)
        output_dir = args.output_dir.resolve()
        csv_path = output_dir / "comparison.csv"
        report_path = output_dir / "report.md"
        if csv_path.exists() or report_path.exists():
            raise ExperimentError("artifact_exists", "기존 비교 산출물을 덮어쓸 수 없습니다")
        write_comparison_csv(csv_path, rows)
        write_report(report_path, render_report(run, population, manifest, rows))
        print(
            json.dumps(
                {
                    "status": "complete",
                    "population_count": len(population["items"]),
                    "review_count": manifest["review_count"],
                    "method_count": len(rows),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except ExperimentError as exc:
        print(json.dumps({"status": "failed", "error_code": exc.code}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
