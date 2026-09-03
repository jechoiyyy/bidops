#!/usr/bin/env python3
"""Create an immutable Top-K prefilter population for a Qwen cascade run."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sys
from typing import Any

from common import (
    POPULATION_SCHEMA,
    ExperimentError,
    capabilities_projection,
    digest_json,
    load_json,
    load_methods_config,
    load_run_population,
    sha256_file,
    validate_method_result,
    validate_population,
    validate_result_run_binding,
    validate_run,
    write_json_new,
)
from methods import BM25Adapter


SCHEMA_VERSION = "bidops.order-plan-qwen-cascade.v1"
KST = timezone(timedelta(hours=9))
EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
RRF_K = 60


def _ranked(scores: dict[str, float]) -> list[str]:
    return [key for key, _value in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


def _rrf(rankings: list[list[str]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, plan_id in enumerate(ranking, start=1):
            scores[plan_id] = scores.get(plan_id, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def select(
    population: dict[str, Any],
    method: str,
    top_k: int,
    capabilities: dict[str, Any],
    bm25_config: dict[str, Any],
    dense_result: dict[str, Any] | None,
) -> tuple[list[str], dict[str, float]]:
    plans = population["items"]
    bm25_rows = BM25Adapter(bm25_config).score_all(plans, capabilities)
    bm25_scores = {plan["plan_id"]: row.score for plan, row in zip(plans, bm25_rows, strict=True)}
    if method == "bm25":
        scores = bm25_scores
    else:
        if dense_result is None or dense_result.get("status") != "success":
            raise ExperimentError("dense_result_unavailable", "성공한 dense 전수 결과가 필요합니다")
        dense_scores = {
            row["plan_id"]: float(row["score"])
            for row in dense_result["items"]
            if row["status"] == "success"
        }
        if set(dense_scores) != set(bm25_scores):
            raise ExperimentError("population_coverage_mismatch", "dense 모집단이 다릅니다")
        if method == "dense":
            scores = dense_scores
        elif method == "hybrid_rrf":
            scores = _rrf([_ranked(bm25_scores), _ranked(dense_scores)])
        else:
            raise ExperimentError("prefilter_invalid", "지원하지 않는 prefilter입니다")
    order = _ranked(scores)
    return order[:top_k], scores


def _copy_new(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst)
    except (FileExistsError, OSError) as exc:
        raise ExperimentError("artifact_write_failed", "고정 입력을 복사할 수 없습니다") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--method", required=True, choices=("bm25", "dense", "hybrid_rrf"))
    parser.add_argument("--top-k", type=int, default=300)
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
    parser.add_argument("--dense-result", type=Path)
    args = parser.parse_args()
    try:
        if args.top_k < 1:
            raise ExperimentError("invalid_top_k", "top-k는 1 이상이어야 합니다")
        source_dir = args.source_run_dir.resolve()
        source_run, source_population = load_run_population(source_dir)
        if args.top_k >= len(source_population["items"]):
            raise ExperimentError("invalid_top_k", "cascade top-k는 전체 모집단보다 작아야 합니다")
        capabilities_document = load_json(args.company_capabilities.resolve())
        capabilities = capabilities_projection(capabilities_document, require_approved=True)
        methods = load_methods_config(args.methods_config.resolve())
        bm25_config = load_json(args.bm25_config.resolve())
        dense_result = None
        if args.method != "bm25":
            if args.dense_result is None:
                raise ExperimentError("dense_result_unavailable", "dense-result가 필요합니다")
            dense_path = args.dense_result.resolve()
            dense_result = validate_method_result(
                load_json(dense_path), source_population, "bge_m3_dense", source_run["selection"]["top_k"]
            )
            validate_result_run_binding(dense_result, source_run)
        selected_ids, scores = select(
            source_population, args.method, args.top_k, capabilities, bm25_config, dense_result
        )
        selected = set(selected_ids)
        items = [copy.deepcopy(row) for row in source_population["items"] if row["plan_id"] in selected]
        created_at = datetime.now(KST).isoformat()
        population = validate_population(
            {
                "schema_version": POPULATION_SCHEMA,
                "run_id": args.run_id,
                "created_at": created_at,
                "input_sha256": source_population["input_sha256"],
                "population_sha256": digest_json(items),
                "items": items,
            }
        )
        run = copy.deepcopy(source_run)
        run.update(
            {
                "run_id": args.run_id,
                "created_at": created_at,
                "population_sha256": population["population_sha256"],
                "population_count": len(items),
                "selection": {"top_k": methods["top_k"]},
                "model_payload": {
                    "allowed_plan_fields": list(methods["model_plan_allowed_fields"]),
                    "company_capabilities_sha256": digest_json(capabilities),
                    "batch_sizes": {
                        name: methods["methods"][name]["batch_size"]
                        for name in ("bge_m3_dense", "qwen", "luna")
                    },
                },
                "config": {
                    "company_capabilities_sha256": sha256_file(args.company_capabilities.resolve()),
                    "methods_sha256": sha256_file(args.methods_config.resolve()),
                    "company_capabilities_approval_status": capabilities_document["approval_status"],
                    "company_capabilities_summary_sha256": capabilities_document["summary_sha256"],
                },
                "methods": {
                    name: {
                        "method_version": config.get("method_version"),
                        "model_name": config.get("model_name"),
                        "model_revision": config.get("model_revision"),
                        "prompt_id": config.get("prompt_id"),
                        "prompt_sha256": config.get("prompt_sha256"),
                        "config_sha256": digest_json(config),
                    }
                    for name, config in methods["methods"].items()
                },
                "external_transmission": {
                    "status": "configured_not_executed",
                    "purpose": "order_plan_first_pass_classification_cascade",
                    "provider": "approved_private_vllm",
                    "endpoint_env": methods["methods"]["qwen"].get("base_url_env"),
                    "model": methods["methods"]["qwen"].get("model_name"),
                    "model_revision": methods["methods"]["qwen"].get("model_revision"),
                    "payload_fields": ["title"],
                    "record_count": len(items),
                    "authorization_context": "interactive_user_instruction",
                },
                "cascade": {
                    "source_run_id": source_run["run_id"],
                    "source_population_sha256": source_population["population_sha256"],
                    "prefilter": args.method,
                    "prefilter_top_k": args.top_k,
                },
            }
        )
        validate_run(run, population)
        output_dir = args.output_dir.resolve()
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ExperimentError("artifact_exists", "기존 cascade 회차를 덮어쓸 수 없습니다")
        source_input = source_dir / "input" / "collected-order-plans.json"
        _copy_new(source_input, output_dir / "input" / "collected-order-plans.json")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": created_at,
            "run_id": args.run_id,
            "source_run_id": source_run["run_id"],
            "source_population_sha256": source_population["population_sha256"],
            "prefilter": args.method,
            "prefilter_top_k": args.top_k,
            "rrf_k": RRF_K if args.method == "hybrid_rrf" else None,
            "bm25_config_sha256": sha256_file(args.bm25_config.resolve()),
            "dense_result_sha256": sha256_file(args.dense_result.resolve()) if args.dense_result else None,
            "selected_ids": selected_ids,
            "ranking": [
                {
                    "plan_id": plan_id,
                    "rank": rank,
                    "score": scores[plan_id],
                    "selected": plan_id in selected,
                }
                for rank, plan_id in enumerate(_ranked(scores), start=1)
            ],
        }
        write_json_new(output_dir / "population.json", population)
        write_json_new(output_dir / "run.json", run)
        write_json_new(output_dir / "cascade.json", manifest)
        print(f"run_id={args.run_id} prefilter={args.method} selected={len(items)}")
        return 0
    except ExperimentError as exc:
        print(f"status=failed error_code={exc.code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
