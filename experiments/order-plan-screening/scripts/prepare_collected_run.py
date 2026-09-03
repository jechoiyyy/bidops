#!/usr/bin/env python3
"""Project an immutable bidops-collect artifact into a screening experiment run."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common import (
    POPULATION_SCHEMA,
    RUN_SCHEMA,
    ExperimentError,
    capabilities_projection,
    digest_json,
    load_json,
    load_methods_config,
    parse_timezone_timestamp,
    sha256_file,
    validate_population,
    validate_run,
    write_json_new,
)


KST = timezone(timedelta(hours=9))
EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
COLLECTED_SCHEMA = "bidops.collected-order-plans.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--collected", required=True, type=Path)
    parser.add_argument(
        "--company-capabilities",
        type=Path,
        default=(
            EXPERIMENT_ROOT
            / "review-inputs/company/company-capabilities-v1-approved.json"
        ),
    )
    parser.add_argument(
        "--methods-config",
        type=Path,
        default=EXPERIMENT_ROOT / "config/methods.json",
    )
    return parser.parse_args()


def _copy_new(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst)
    except FileExistsError as exc:
        raise ExperimentError("artifact_exists", "고정 입력을 덮어쓸 수 없습니다") from exc
    except OSError as exc:
        raise ExperimentError("input_copy_failed", "고정 입력 복사에 실패했습니다") from exc


def _validate_collected(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("schema_version") != COLLECTED_SCHEMA:
        raise ExperimentError("schema_mismatch", "수집 산출물 schema_version이 다릅니다")
    plans = document.get("order_plans")
    if not isinstance(plans, list) or not plans:
        raise ExperimentError("invalid_contract", "수집 산출물 order_plans가 비었습니다")
    metadata = document.get("metadata")
    collection = metadata.get("collection") if isinstance(metadata, dict) else None
    if not isinstance(collection, dict) or collection.get("complete") is not True:
        raise ExperimentError("collection_incomplete", "완료된 수집 산출물만 사용할 수 있습니다")
    if document.get("warnings") not in ([], None):
        raise ExperimentError("collection_warning", "경고가 있는 수집 산출물은 검토 후 사용해야 합니다")
    if document.get("counts", {}).get("order_plans") != len(plans):
        raise ExperimentError("count_mismatch", "수집 산출물 건수가 맞지 않습니다")
    parse_timezone_timestamp(document.get("generated_at"), "collected.generated_at")
    return document


def build_population(
    collected: dict[str, Any], run_id: str, input_sha256: str, created_at: str
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for index, source in enumerate(collected["order_plans"]):
        if not isinstance(source, dict):
            raise ExperimentError("invalid_contract", f"order_plans[{index}]가 object가 아닙니다")
        plan_id = source.get("order_plan_unty_no")
        title = source.get("title")
        source_sha256 = source.get("source_sha256")
        if not isinstance(plan_id, str) or not plan_id.strip():
            raise ExperimentError("missing_plan_id", f"order_plans[{index}] 식별자가 없습니다")
        if not isinstance(title, str) or not title.strip():
            raise ExperimentError("title_missing", f"order_plans[{index}] 제목이 없습니다")
        if not isinstance(source_sha256, str) or len(source_sha256) != 64:
            raise ExperimentError("invalid_hash", f"order_plans[{index}] source hash가 잘못됐습니다")
        items.append(
            {
                "plan_id": plan_id,
                "title": title,
                "agency_code": source.get("agency_code"),
                "agency_name": source.get("agency_name"),
                "supervising_agency_name": source.get("supervising_agency_name"),
                "business_division": source.get("business_division"),
                "business_division_code": source.get("business_division_code"),
                "service_type": source.get("service_type"),
                "service_type_code": source.get("service_type_code"),
                "budget_amount": source.get("budget_amount"),
                "contract_amount": source.get("contract_amount"),
                "planned_order_month": source.get("planned_order_month"),
                "procurement_method": source.get("procurement_method"),
                "contract_method": source.get("contract_method"),
                "sw_business_status": source.get("sw_business_status"),
                "official_url": source.get("source_url"),
                "published_at": source.get("published_at"),
                "changed_at": source.get("changed_at"),
                "first_discovered_at": source.get("first_discovered_at"),
                "last_discovered_at": source.get("last_discovered_at"),
                "unknown_fields": source.get("unknown_fields", []),
                "source": {
                    "raw_ref": f"input/collected-order-plans.json#/order_plans/{index}",
                    "source_sha256": source_sha256,
                },
            }
        )
    items.sort(key=lambda item: item["plan_id"])
    return validate_population(
        {
            "schema_version": POPULATION_SCHEMA,
            "run_id": run_id,
            "created_at": created_at,
            "input_sha256": input_sha256,
            "population_sha256": digest_json(items),
            "items": items,
        }
    )


def build_run(
    collected: dict[str, Any],
    population: dict[str, Any],
    capabilities_path: Path,
    methods_path: Path,
) -> dict[str, Any]:
    capabilities_document = load_json(capabilities_path)
    capabilities = capabilities_projection(capabilities_document, require_approved=True)
    methods = load_methods_config(methods_path)
    bindings = {
        name: {
            "method_version": config.get("method_version"),
            "model_name": config.get("model_name"),
            "model_revision": config.get("model_revision"),
            "prompt_id": config.get("prompt_id"),
            "prompt_sha256": config.get("prompt_sha256"),
            "config_sha256": digest_json(config),
        }
        for name, config in methods["methods"].items()
    }
    window = collected["source_window"]
    metadata = collected["metadata"]
    collection = metadata["collection"]
    first_seen = min(item["first_discovered_at"] for item in collected["order_plans"])
    last_seen = max(item["last_discovered_at"] for item in collected["order_plans"])
    qwen_config = methods["methods"]["qwen"]
    if qwen_config.get("api_style") == "openai_compatible":
        transmission = {
            "status": "configured_not_executed",
            "purpose": "order_plan_first_pass_classification",
            "provider": "approved_private_vllm",
            "endpoint_env": qwen_config.get("base_url_env"),
            "model": qwen_config.get("model_name"),
            "model_revision": qwen_config.get("model_revision"),
            "payload_fields": ["title"],
            "record_count": len(population["items"]),
            "authorization_context": "interactive_user_instruction",
        }
    else:
        transmission = {
            "status": "not_requested",
            "reason": "c2_local_bm25_dense_rrf_rerun",
        }
    run = {
        "schema_version": RUN_SCHEMA,
        "run_id": population["run_id"],
        "created_at": population["created_at"],
        "input_sha256": population["input_sha256"],
        "population_sha256": population["population_sha256"],
        "population_count": len(population["items"]),
        "selection": {"top_k": methods["top_k"]},
        "model_payload": {
            "allowed_plan_fields": list(methods["model_plan_allowed_fields"]),
            "company_capabilities_sha256": digest_json(capabilities),
            "batch_sizes": {
                name: methods["methods"][name]["batch_size"]
                for name in ("bge_m3_dense", "qwen", "luna")
            },
        },
        "query_window": {
            "from": f"{window['from']}T00:00:00+09:00",
            "to_exclusive": f"{window['to']}T00:00:00+09:00",
            "business_divisions": list(metadata["business_divisions"]),
            "prefilters": [],
            "api_order_month_scope": {
                "from": metadata["order_month_scope"]["from"],
                "to_inclusive": metadata["order_month_scope"]["to"],
                "purpose": "required_api_dimension_without_population_prefilter",
            },
        },
        "collection": {
            "endpoint_id": metadata["endpoint_id"],
            "page_count": collection["page_count"],
            "request_count": collection["request_count"],
            "first_collected_at": first_seen,
            "last_collected_at": last_seen,
            "raw_input_sha256": population["input_sha256"],
            "complete": True,
        },
        "config": {
            "company_capabilities_sha256": sha256_file(capabilities_path),
            "methods_sha256": sha256_file(methods_path),
            "company_capabilities_approval_status": capabilities_document["approval_status"],
            "company_capabilities_summary_sha256": capabilities_document["summary_sha256"],
        },
        "methods": bindings,
        "external_transmission": transmission,
    }
    return validate_run(run, population)


def main() -> int:
    args = parse_args()
    try:
        if not args.run_id.strip() or any(part in args.run_id for part in ("/", "\\", "..")):
            raise ExperimentError("invalid_run_id", "run_id가 안전하지 않습니다")
        output_dir = args.output_dir.resolve()
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ExperimentError("artifact_exists", "기존 실험 디렉터리를 덮어쓸 수 없습니다")
        collected_path = args.collected.resolve()
        collected = _validate_collected(load_json(collected_path))
        fixed_input = output_dir / "input" / "collected-order-plans.json"
        _copy_new(collected_path, fixed_input)
        input_sha256 = sha256_file(fixed_input)
        created_at = datetime.now(KST).isoformat()
        population = build_population(collected, args.run_id, input_sha256, created_at)
        run = build_run(
            collected,
            population,
            args.company_capabilities.resolve(),
            args.methods_config.resolve(),
        )
        write_json_new(output_dir / "population.json", population)
        write_json_new(output_dir / "run.json", run)
        print(
            f"run_id={args.run_id} population_count={len(population['items'])} "
            f"input_sha256={input_sha256}"
        )
        return 0
    except ExperimentError as exc:
        print(f"status=failed error_code={exc.code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
