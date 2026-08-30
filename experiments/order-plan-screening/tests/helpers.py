from __future__ import annotations

import sys
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (  # noqa: E402
    METHOD_RESULT_SCHEMA,
    POPULATION_SCHEMA,
    RUN_SCHEMA,
    digest_json,
)


KST = timezone(timedelta(hours=9))
FIXED_TIME = "2026-08-28T12:00:00+09:00"


def make_plan(index: int) -> dict[str, Any]:
    plan_id = f"P{index:04d}"
    return {
        "plan_id": plan_id,
        "title": f"사업 {index}",
        "agency_code": f"A{index:04d}",
        "agency_name": f"기관 {index % 3}",
        "supervising_agency_name": None,
        "business_division": "일반용역" if index % 2 == 0 else "기술용역",
        "business_division_code": "01" if index % 2 == 0 else "05",
        "service_type": "신규(단기)",
        "service_type_code": "신120001",
        "budget_amount": None if index == 0 else index * 1_000_000,
        "contract_amount": None,
        "planned_order_month": "2026-09",
        "procurement_method": "자체조달",
        "contract_method": "일반경쟁",
        "sw_business_status": None,
        "official_url": None,
        "published_at": "2026-08-24T01:00:00+09:00",
        "changed_at": None,
        "first_discovered_at": FIXED_TIME,
        "last_discovered_at": FIXED_TIME,
        "unknown_fields": ["official_url", "sw_business_status"],
        "source": {
            "raw_ref": f"raw/page-00001.json#items[{index}]",
            "source_sha256": digest_json({"index": index}),
        },
    }


def make_population(count: int, run_id: str = "test-run") -> dict[str, Any]:
    items = [make_plan(index) for index in range(count)]
    return {
        "schema_version": POPULATION_SCHEMA,
        "run_id": run_id,
        "created_at": FIXED_TIME,
        "input_sha256": digest_json({"raw": run_id}),
        "population_sha256": digest_json(items),
        "items": items,
    }


def make_run(population: dict[str, Any]) -> dict[str, Any]:
    bindings = {
        "keyword": {
            "method_version": "keyword-v1",
            "model_name": None,
            "model_revision": None,
            "prompt_id": None,
            "prompt_sha256": None,
        },
        "tfidf": {
            "method_version": "tfidf-v1",
            "model_name": None,
            "model_revision": None,
            "prompt_id": None,
            "prompt_sha256": None,
        },
        "bge_m3_dense": {
            "method_version": "bge_m3_dense-v1",
            "model_name": "bge-m3:latest",
            "model_revision": "d" * 64,
            "prompt_id": None,
            "prompt_sha256": None,
        },
        "bge_m3_colbert": {
            "method_version": "bge_m3_colbert-v1",
            "model_name": "BAAI/bge-m3",
            "model_revision": "a" * 40,
            "prompt_id": None,
            "prompt_sha256": None,
        },
        "qwen": {
            "method_version": "qwen-v1",
            "model_name": "qwen",
            "model_revision": "b" * 64,
            "prompt_id": "prompt-v1",
            "prompt_sha256": "c" * 64,
        },
        "luna": {
            "method_version": "luna-v1",
            "model_name": "gpt-5.6-luna",
            "model_revision": "gpt-5.6-luna-immutable-test",
            "prompt_id": "prompt-v1",
            "prompt_sha256": "c" * 64,
        },
    }
    for binding in bindings.values():
        binding["config_sha256"] = "a" * 64
    return {
        "schema_version": RUN_SCHEMA,
        "run_id": population["run_id"],
        "created_at": FIXED_TIME,
        "input_sha256": population["input_sha256"],
        "population_sha256": population["population_sha256"],
        "population_count": len(population["items"]),
        "selection": {"top_k": 3},
        "model_payload": {
            "allowed_plan_fields": ["title"],
            "company_capabilities_sha256": "f" * 64,
            "batch_sizes": {"bge_m3_dense": 128, "qwen": 25, "luna": 25},
        },
        "config": {
            "company_capabilities_sha256": "d" * 64,
            "methods_sha256": "e" * 64,
        },
        "methods": bindings,
        "collection": {
            "page_count": 1,
            "request_count": 1,
            "complete": True,
        },
    }


def make_result(
    population: dict[str, Any],
    method: str,
    selected_ids: set[str],
    failed_ids: set[str] | None = None,
) -> dict[str, Any]:
    failed_ids = failed_ids or set()
    successful_ids = [
        item["plan_id"] for item in population["items"] if item["plan_id"] not in failed_ids
    ]
    ranked = sorted(successful_ids)
    rank_by_id = {plan_id: index + 1 for index, plan_id in enumerate(ranked)}
    items = []
    for plan in population["items"]:
        plan_id = plan["plan_id"]
        if plan_id in failed_ids:
            items.append(
                {
                    "plan_id": plan_id,
                    "status": "failed",
                    "score": None,
                    "rank": None,
                    "selected": False,
                    "reason": None,
                    "relevance": None,
                    "evidence_fields": [],
                    "latency_ms": 1,
                    "error_code": "timeout",
                    "input_tokens": None,
                    "cached_input_tokens": None,
                    "output_tokens": None,
                    "device": None,
                }
            )
        else:
            rank = rank_by_id[plan_id]
            items.append(
                {
                    "plan_id": plan_id,
                    "status": "success",
                    "score": float(len(ranked) - rank),
                    "rank": rank,
                    "selected": plan_id in selected_ids,
                    "reason": "fixture",
                    "relevance": "relevant" if method in {"qwen", "luna"} else None,
                    "evidence_fields": ["title"] if method in {"qwen", "luna"} else [],
                    "latency_ms": 1,
                    "error_code": None,
                    "input_tokens": None,
                    "cached_input_tokens": None,
                    "output_tokens": None,
                    "device": "fixture",
                }
            )
    success_count = len(successful_ids)
    failure_count = len(failed_ids)
    model_bindings = {
        "bge_m3_dense": {"name": "bge-m3:latest", "revision": "d" * 64},
        "bge_m3_colbert": {"name": "BAAI/bge-m3", "revision": "a" * 40},
        "qwen": {"name": "qwen", "revision": "b" * 64},
        "luna": {"name": "gpt-5.6-luna", "revision": "gpt-5.6-luna-immutable-test"},
    }
    prompt_bindings = {
        "qwen": {"id": "prompt-v1", "sha256": "c" * 64},
        "luna": {"id": "prompt-v1", "sha256": "c" * 64},
    }
    batch_size = {"bge_m3_dense": 128, "qwen": 25, "luna": 25}.get(method)
    return {
        "schema_version": METHOD_RESULT_SCHEMA,
        "run_id": population["run_id"],
        "created_at": FIXED_TIME,
        "input_sha256": population["population_sha256"],
        "method": method,
        "method_version": f"{method}-v1",
        "top_k": len(selected_ids),
        "config_sha256": "a" * 64,
        "model": model_bindings.get(method, {"name": None, "revision": None}),
        "prompt": prompt_bindings.get(method, {"id": None, "sha256": None}),
        "batching": {
            "mode": "fixed",
            "batch_size": batch_size,
            "batch_count": (len(items) + batch_size - 1) // batch_size,
        }
        if batch_size is not None
        else None,
        "external_approval": None,
        "status": (
            "success"
            if failure_count == 0
            else "failed"
            if success_count == 0
            else "partial_failure"
        ),
        "metrics": {
            "population_count": len(population["items"]),
            "success_count": success_count,
            "failure_count": failure_count,
            "selected_count": len(selected_ids),
            "elapsed_ms": len(items) + 10,
            "total_latency_ms": len(items),
            "average_latency_ms": 1,
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
            "device": "fixture",
        },
        "items": items,
    }
