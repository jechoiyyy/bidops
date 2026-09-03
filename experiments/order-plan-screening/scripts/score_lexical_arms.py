#!/usr/bin/env python3
"""Compare fixed BM25 and TF-IDF title rankings against an effective reference."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import time
from typing import Any

from common import (
    ExperimentError,
    capabilities_projection,
    load_json,
    load_run_population,
    sha256_file,
    write_json_new,
)
from methods import BM25Adapter, TfidfAdapter
from score_arms import CUTOFFS, RELEVANT, _evaluate, _load_gold, _ranked


SCHEMA_VERSION = "bidops.order-plan-lexical-arm-scoring.v1"
KST = timezone(timedelta(hours=9))
EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]


def _detail(
    plan_id: str,
    plans: dict[str, dict[str, Any]],
    gold: Any,
    ranks: dict[str, dict[str, int]],
) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "title": plans[plan_id]["title"],
        "priority": gold.priority.get(plan_id),
        "bm25_rank": ranks["bm25"][plan_id],
        "tfidf_rank": ranks["tfidf"][plan_id],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--company-capabilities",
        type=Path,
        default=(
            EXPERIMENT_ROOT
            / "review-inputs/company/company-capabilities-v1-approved.json"
        ),
    )
    parser.add_argument(
        "--methods-config", type=Path, default=EXPERIMENT_ROOT / "config/methods.json"
    )
    parser.add_argument("--bm25-config", type=Path, default=EXPERIMENT_ROOT / "config/bm25.json")
    parser.add_argument("--comparison-cutoff", type=int, default=300)
    args = parser.parse_args()
    try:
        run, population = load_run_population(args.run_dir.resolve())
        plans_list = population["items"]
        plans = {row["plan_id"]: row for row in plans_list}
        reference_path = args.reference.resolve()
        gold = _load_gold(
            reference_path,
            "effective_relevance",
            "effective_priority",
            "label_source",
        )
        if set(gold.relevance) != set(plans):
            raise ExperimentError("population_coverage_mismatch", "reference와 모집단 ID가 다릅니다")

        capabilities_path = args.company_capabilities.resolve()
        capabilities = capabilities_projection(load_json(capabilities_path), require_approved=True)
        methods_path = args.methods_config.resolve()
        methods_config = load_json(methods_path)
        tfidf_config = methods_config["methods"]["tfidf"]
        bm25_path = args.bm25_config.resolve()
        bm25_config = load_json(bm25_path)

        elapsed: dict[str, int] = {}
        started = time.monotonic()
        bm25_rows = BM25Adapter(bm25_config).score_all(plans_list, capabilities)
        elapsed["bm25"] = max(0, round((time.monotonic() - started) * 1000))
        started = time.monotonic()
        tfidf_rows = TfidfAdapter(tfidf_config).score_all(plans_list, capabilities)
        elapsed["tfidf"] = max(0, round((time.monotonic() - started) * 1000))

        scores = {
            "bm25": {
                plan["plan_id"]: row.score
                for plan, row in zip(plans_list, bm25_rows, strict=True)
            },
            "tfidf": {
                plan["plan_id"]: row.score
                for plan, row in zip(plans_list, tfidf_rows, strict=True)
            },
        }
        orders = {name: _ranked(values) for name, values in scores.items()}
        ranks = {
            name: {plan_id: rank for rank, plan_id in enumerate(order, start=1)}
            for name, order in orders.items()
        }
        evaluations = {name: _evaluate(order, gold) for name, order in orders.items()}
        relevant_ids = {
            plan_id for plan_id, relevance in gold.relevance.items() if relevance == RELEVANT
        }
        cutoff = args.comparison_cutoff
        heads = {name: set(order[:cutoff]) for name, order in orders.items()}
        groups = {
            "both": sorted(relevant_ids & heads["bm25"] & heads["tfidf"]),
            "bm25_only": sorted(relevant_ids & heads["bm25"] - heads["tfidf"]),
            "tfidf_only": sorted(relevant_ids & heads["tfidf"] - heads["bm25"]),
            "neither": sorted(relevant_ids - heads["bm25"] - heads["tfidf"]),
        }
        misses = {
            name: [
                _detail(plan_id, plans, gold, ranks)
                for plan_id in sorted(relevant_ids - heads[name], key=lambda value: ranks[name][value])
            ]
            for name in orders
        }
        selected_union = heads["bm25"] | heads["tfidf"]
        selected_intersection = heads["bm25"] & heads["tfidf"]
        document = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(KST).isoformat(),
            "run_id": run["run_id"],
            "population_count": len(plans_list),
            "population_sha256": population["population_sha256"],
            "reference": {
                "path": str(reference_path),
                "sha256": sha256_file(reference_path),
                "relevant": len(relevant_ids),
                "label_source_counts": gold.label_source_counts,
            },
            "configs": {
                "company_capabilities_sha256": sha256_file(capabilities_path),
                "bm25_sha256": sha256_file(bm25_path),
                "methods_sha256": sha256_file(methods_path),
                "bm25": bm25_config,
                "tfidf": tfidf_config,
            },
            "elapsed_ms": elapsed,
            "evaluations": evaluations,
            "comparison_at_cutoff": {
                "cutoff": cutoff,
                "selected_overlap_count": len(selected_intersection),
                "selected_union_count": len(selected_union),
                "selected_jaccard": round(
                    len(selected_intersection) / len(selected_union), 4
                ) if selected_union else None,
                "relevant_groups": {
                    name: [_detail(plan_id, plans, gold, ranks) for plan_id in ids]
                    for name, ids in groups.items()
                },
            },
            "relevant_misses_at_cutoff": misses,
        }
        write_json_new(args.out.resolve(), document)
        for name in ("bm25", "tfidf"):
            row = next(
                item for item in evaluations[name]["at_cutoff"] if item["cutoff"] == cutoff
            )
            print(
                f"{name} top{cutoff}: found={row['found']} recall={row['recall']} "
                f"full_recall_rank={evaluations[name]['rank_for_full_recall']}"
            )
        print(f"record={args.out}")
        return 0
    except (ExperimentError, KeyError, ValueError) as exc:
        code = exc.code if isinstance(exc, ExperimentError) else "scoring_failed"
        print(f"status=failed error_code={code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
