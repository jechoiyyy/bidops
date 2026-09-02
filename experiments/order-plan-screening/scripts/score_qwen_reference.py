#!/usr/bin/env python3
"""Score a full-population Qwen first-pass classification against fixed reference labels."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any

from common import (
    ExperimentError,
    load_json,
    load_run_population,
    sha256_file,
    validate_method_result,
    validate_result_run_binding,
    write_json_new,
)


SCHEMA_VERSION = "bidops.order-plan-qwen-reference-scoring.v1"
KST = timezone(timedelta(hours=9))
GOLD_RELEVANT = "관련"
PREDICTIONS = ("relevant", "uncertain", "not_relevant")


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _execution_metrics(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result["metrics"]
    elapsed_ms = metrics.get("elapsed_ms")
    input_tokens = metrics.get("input_tokens")
    cached_input_tokens = metrics.get("cached_input_tokens")
    output_tokens = metrics.get("output_tokens")
    total_tokens = (
        (input_tokens or 0) + (output_tokens or 0)
        if input_tokens is not None or output_tokens is not None
        else None
    )
    elapsed_seconds = elapsed_ms / 1000 if isinstance(elapsed_ms, int) and elapsed_ms > 0 else None
    return {
        "batching": result.get("batching"),
        "elapsed_ms": elapsed_ms,
        "total_latency_ms": metrics.get("total_latency_ms"),
        "average_latency_ms": metrics.get("average_latency_ms"),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "records_per_second": round(metrics["success_count"] / elapsed_seconds, 4)
        if elapsed_seconds
        else None,
        "output_tokens_per_second": round(output_tokens / elapsed_seconds, 4)
        if elapsed_seconds and output_tokens is not None
        else None,
        "device": metrics.get("device"),
    }


def load_reference(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {
            "plan_id",
            "effective_relevance",
            "effective_priority",
            "label_source",
        }
        if not reader.fieldnames or not required <= set(reader.fieldnames):
            raise ExperimentError("reference_invalid", "effective reference 필드가 없습니다")
        for row in reader:
            plan_id = row["plan_id"].strip()
            if not plan_id or plan_id in rows:
                raise ExperimentError("reference_invalid", "reference plan_id가 비었거나 중복됐습니다")
            if row["effective_relevance"] not in {"관련", "비관련"}:
                raise ExperimentError("reference_invalid", "reference 관련성 값이 잘못됐습니다")
            rows[plan_id] = row
    return rows


def build_scoring(
    run: dict[str, Any],
    population: dict[str, Any],
    result: dict[str, Any],
    reference: dict[str, dict[str, str]],
    reference_path: Path,
    result_path: Path,
) -> dict[str, Any]:
    plans = {row["plan_id"]: row for row in population["items"]}
    if set(reference) != set(plans):
        raise ExperimentError("population_coverage_mismatch", "reference와 모집단 ID가 다릅니다")
    by_result = {row["plan_id"]: row for row in result["items"]}
    successful = [row for row in result["items"] if row["status"] == "success"]
    failed = [row for row in result["items"] if row["status"] != "success"]
    matrix: Counter[tuple[str, str]] = Counter()
    source_matrix: Counter[tuple[str, str, str]] = Counter()
    for row in successful:
        gold = reference[row["plan_id"]]["effective_relevance"]
        matrix[(gold, row["relevance"])] += 1
        source_matrix[(reference[row["plan_id"]]["label_source"], gold, row["relevance"])] += 1

    total_relevant = sum(row["effective_relevance"] == GOLD_RELEVANT for row in reference.values())
    evaluated_relevant = sum(matrix[(GOLD_RELEVANT, prediction)] for prediction in PREDICTIONS)
    strict_tp = matrix[(GOLD_RELEVANT, "relevant")]
    strict_fp = matrix[("비관련", "relevant")]
    retained_tp = strict_tp + matrix[(GOLD_RELEVANT, "uncertain")]
    retained_fp = strict_fp + matrix[("비관련", "uncertain")]

    def details(ids: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "plan_id": plan_id,
                "title": plans[plan_id]["title"],
                "priority": reference[plan_id]["effective_priority"],
                "label_source": reference[plan_id]["label_source"],
                "prediction": by_result[plan_id]["relevance"],
                "score": by_result[plan_id]["score"],
                "reason": by_result[plan_id]["reason"],
            }
            for plan_id in sorted(ids)
        ]

    false_negative_ids = [
        row["plan_id"]
        for row in successful
        if reference[row["plan_id"]]["effective_relevance"] == GOLD_RELEVANT
        and row["relevance"] == "not_relevant"
    ]
    uncertain_relevant_ids = [
        row["plan_id"]
        for row in successful
        if reference[row["plan_id"]]["effective_relevance"] == GOLD_RELEVANT
        and row["relevance"] == "uncertain"
    ]
    false_positive_ids = [
        row["plan_id"]
        for row in successful
        if reference[row["plan_id"]]["effective_relevance"] == "비관련"
        and row["relevance"] == "relevant"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(KST).isoformat(),
        "run_id": run["run_id"],
        "population_count": len(plans),
        "population_sha256": population["population_sha256"],
        "result": {
            "path": str(result_path),
            "sha256": sha256_file(result_path),
            "status": result["status"],
            "model": result["model"],
            "prompt": result["prompt"],
        },
        "reference": {
            "path": str(reference_path),
            "sha256": sha256_file(reference_path),
            "relevant": total_relevant,
            "not_relevant": len(reference) - total_relevant,
            "label_source_counts": dict(
                sorted(Counter(row["label_source"] for row in reference.values()).items())
            ),
        },
        "coverage": {
            "success": len(successful),
            "failed": len(failed),
            "rate": _ratio(len(successful), len(plans)),
            "failure_error_counts": dict(
                sorted(Counter(row["error_code"] for row in failed).items())
            ),
        },
        "execution": _execution_metrics(result),
        "prediction_counts": dict(
            sorted(Counter(row["relevance"] for row in successful).items())
        ),
        "confusion": {
            gold: {prediction: matrix[(gold, prediction)] for prediction in PREDICTIONS}
            for gold in ("관련", "비관련")
        },
        "metrics": {
            "strict_relevant": {
                "recall": _ratio(strict_tp, total_relevant),
                "recall_on_evaluated": _ratio(strict_tp, evaluated_relevant),
                "precision": _ratio(strict_tp, strict_tp + strict_fp),
            },
            "review_retained_relevant_or_uncertain": {
                "recall": _ratio(retained_tp, total_relevant),
                "recall_on_evaluated": _ratio(retained_tp, evaluated_relevant),
                "precision": _ratio(retained_tp, retained_tp + retained_fp),
                "review_load": sum(
                    row["relevance"] in {"relevant", "uncertain"} for row in successful
                ),
            },
        },
        "label_source_confusion": [
            {
                "label_source": source,
                "gold": gold,
                "prediction": prediction,
                "count": count,
            }
            for (source, gold, prediction), count in sorted(source_matrix.items())
        ],
        "false_negatives": details(false_negative_ids),
        "uncertain_relevant": details(uncertain_relevant_ids),
        "false_positives": details(false_positive_ids),
        "failures": [
            {
                "plan_id": row["plan_id"],
                "title": plans[row["plan_id"]]["title"],
                "gold": reference[row["plan_id"]]["effective_relevance"],
                "priority": reference[row["plan_id"]]["effective_priority"],
                "label_source": reference[row["plan_id"]]["label_source"],
                "error_code": row["error_code"],
            }
            for row in failed
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        run_dir = args.run_dir.resolve()
        run, population = load_run_population(run_dir)
        result_path = run_dir / "results" / "qwen.json"
        result = validate_method_result(
            load_json(result_path), population, "qwen", run["selection"]["top_k"]
        )
        validate_result_run_binding(result, run)
        reference_path = args.reference.resolve()
        reference = load_reference(reference_path)
        document = build_scoring(
            run, population, result, reference, reference_path, result_path
        )
        destination = args.out.resolve() if args.out else run_dir / "qwen-reference-scoring.json"
        write_json_new(destination, document)
        print(
            f"status={result['status']} success={document['coverage']['success']} "
            f"failed={document['coverage']['failed']} "
            f"retained_recall={document['metrics']['review_retained_relevant_or_uncertain']['recall']}"
        )
        return 0
    except ExperimentError as exc:
        print(f"status=failed error_code={exc.code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
