#!/usr/bin/env python3
"""Evaluate a prefilter→Qwen cascade on the full source population."""

from __future__ import annotations

import argparse
from collections import Counter
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
from score_qwen_reference import GOLD_RELEVANT, _execution_metrics, load_reference


SCHEMA_VERSION = "bidops.order-plan-qwen-cascade-scoring.v1"
KST = timezone(timedelta(hours=9))


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-dir", required=True, type=Path)
    parser.add_argument("--cascade-run-dir", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        source_run, source_population = load_run_population(args.source_run_dir.resolve())
        cascade_dir = args.cascade_run_dir.resolve()
        cascade_run, cascade_population = load_run_population(cascade_dir)
        manifest_path = cascade_dir / "cascade.json"
        manifest = load_json(manifest_path)
        if (
            manifest.get("schema_version") != "bidops.order-plan-qwen-cascade.v1"
            or manifest.get("source_run_id") != source_run["run_id"]
            or manifest.get("source_population_sha256") != source_population["population_sha256"]
        ):
            raise ExperimentError("cascade_binding_mismatch", "cascade가 source 모집단과 다릅니다")
        selected_ids = set(manifest["selected_ids"])
        if selected_ids != {row["plan_id"] for row in cascade_population["items"]}:
            raise ExperimentError("cascade_binding_mismatch", "cascade 선택과 모집단이 다릅니다")
        result_path = cascade_dir / "results" / "qwen.json"
        result = validate_method_result(
            load_json(result_path), cascade_population, "qwen", cascade_run["selection"]["top_k"]
        )
        validate_result_run_binding(result, cascade_run)
        reference_path = args.reference.resolve()
        reference = load_reference(reference_path)
        source_plans = {row["plan_id"]: row for row in source_population["items"]}
        if set(reference) != set(source_plans):
            raise ExperimentError("population_coverage_mismatch", "reference와 source 모집단이 다릅니다")
        result_by_id = {row["plan_id"]: row for row in result["items"]}
        filtered = set(source_plans) - selected_ids
        stage1_misses = sorted(
            plan_id for plan_id in filtered
            if reference[plan_id]["effective_relevance"] == GOLD_RELEVANT
        )
        qwen_false_negatives = sorted(
            plan_id for plan_id, row in result_by_id.items()
            if row["status"] == "success"
            and row["relevance"] == "not_relevant"
            and reference[plan_id]["effective_relevance"] == GOLD_RELEVANT
        )
        qwen_uncertain_relevant = sorted(
            plan_id for plan_id, row in result_by_id.items()
            if row["status"] == "success"
            and row["relevance"] == "uncertain"
            and reference[plan_id]["effective_relevance"] == GOLD_RELEVANT
        )
        failures = [row for row in result["items"] if row["status"] != "success"]
        retained = [
            row for row in result["items"]
            if row["status"] == "success" and row["relevance"] in {"relevant", "uncertain"}
        ]
        retained_relevant = sum(
            reference[row["plan_id"]]["effective_relevance"] == GOLD_RELEVANT
            for row in retained
        )
        total_relevant = sum(
            row["effective_relevance"] == GOLD_RELEVANT for row in reference.values()
        )

        def details(ids: list[str]) -> list[dict[str, Any]]:
            return [
                {
                    "plan_id": plan_id,
                    "title": source_plans[plan_id]["title"],
                    "priority": reference[plan_id]["effective_priority"],
                    "label_source": reference[plan_id]["label_source"],
                    "qwen_prediction": result_by_id.get(plan_id, {}).get("relevance"),
                    "qwen_reason": result_by_id.get(plan_id, {}).get("reason"),
                }
                for plan_id in ids
            ]

        document = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(KST).isoformat(),
            "source_run_id": source_run["run_id"],
            "cascade_run_id": cascade_run["run_id"],
            "source_population_count": len(source_plans),
            "selected_count": len(selected_ids),
            "filtered_out_count": len(filtered),
            "prefilter": manifest["prefilter"],
            "prefilter_top_k": manifest["prefilter_top_k"],
            "bindings": {
                "cascade_sha256": sha256_file(manifest_path),
                "qwen_result_sha256": sha256_file(result_path),
                "reference_sha256": sha256_file(reference_path),
            },
            "qwen": {
                "status": result["status"],
                "success": result["metrics"]["success_count"],
                "failed": result["metrics"]["failure_count"],
                "batching": result["batching"],
                "input_tokens": result["metrics"].get("input_tokens"),
                "output_tokens": result["metrics"].get("output_tokens"),
                "execution": _execution_metrics(result),
                "failure_error_counts": dict(
                    sorted(Counter(row["error_code"] for row in failures).items())
                ),
            },
            "metrics": {
                "review_retained_recall_full_population": _ratio(retained_relevant, total_relevant),
                "review_retained_precision": _ratio(retained_relevant, len(retained)),
                "review_load": len(retained),
                "qwen_input_reduction": _ratio(len(source_plans) - len(selected_ids), len(source_plans)),
                "stage1_relevant_missed": len(stage1_misses),
                "qwen_relevant_missed": len(qwen_false_negatives),
                "qwen_relevant_uncertain": len(qwen_uncertain_relevant),
            },
            "stage1_false_negatives": details(stage1_misses),
            "qwen_false_negatives": details(qwen_false_negatives),
            "qwen_uncertain_relevant": details(qwen_uncertain_relevant),
        }
        destination = args.out.resolve() if args.out else cascade_dir / "qwen-cascade-scoring.json"
        write_json_new(destination, document)
        print(
            f"prefilter={manifest['prefilter']} retained_recall="
            f"{document['metrics']['review_retained_recall_full_population']} "
            f"stage1_missed={len(stage1_misses)} qwen_missed={len(qwen_false_negatives)}"
        )
        return 0
    except ExperimentError as exc:
        print(f"status=failed error_code={exc.code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
