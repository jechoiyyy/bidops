#!/usr/bin/env python3
"""Run exactly one configured method without cross-model fallback."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from common import (
    METHOD_RESULT_SCHEMA,
    ExperimentError,
    digest_json,
    external_preview,
    is_sha256,
    load_capabilities,
    load_json,
    load_methods_config,
    load_run_population,
    sha256_file,
    validate_external_approval,
    validate_method_result,
    validate_result_run_binding,
    write_json_new,
)
from methods import (
    AdapterFailure,
    AdapterResult,
    BGEM3ColBERTAdapter,
    KeywordAdapter,
    LunaAdapter,
    QwenAdapter,
)


KST = timezone(timedelta(hours=9))
EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--method",
        required=True,
        choices=("keyword", "bge_m3_colbert", "qwen", "luna"),
    )
    parser.add_argument(
        "--company-capabilities",
        type=Path,
        default=EXPERIMENT_ROOT / "config/company-capabilities.json",
    )
    parser.add_argument(
        "--methods-config",
        type=Path,
        default=EXPERIMENT_ROOT / "config/methods.json",
    )
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--external-approval", type=Path)
    parser.add_argument("--check-ready", action="store_true")
    return parser.parse_args()


def read_prompt(path: Path | None, expected_hash: Any) -> tuple[str | None, str | None]:
    if path is None:
        if expected_hash is not None:
            raise ExperimentError("prompt_missing", "고정 prompt 파일이 필요합니다")
        return None, None
    try:
        prompt = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ExperimentError("prompt_read_failed", "prompt 파일을 읽을 수 없습니다") from exc
    if not prompt.strip():
        raise ExperimentError("prompt_invalid", "prompt 파일이 비어 있습니다")
    actual_hash = sha256_file(path)
    if expected_hash != actual_hash:
        raise ExperimentError("prompt_hash_mismatch", "prompt hash가 methods config와 다릅니다")
    return prompt, actual_hash


def check_bindings(
    run: dict[str, Any],
    method_name: str,
    methods_path: Path,
    capabilities_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    methods_config = load_methods_config(methods_path)
    capabilities_document, capabilities = load_capabilities(capabilities_path, require_approved=True)
    if run["config"]["methods_sha256"] != sha256_file(methods_path):
        raise ExperimentError("config_hash_mismatch", "run에 고정된 methods config와 다릅니다")
    if run["config"]["company_capabilities_sha256"] != sha256_file(capabilities_path):
        raise ExperimentError("config_hash_mismatch", "run에 고정된 company capabilities와 다릅니다")
    if run["selection"]["top_k"] != methods_config["top_k"]:
        raise ExperimentError("invalid_top_k", "run과 methods config의 top_k가 다릅니다")
    expected_payload_binding = {
        "allowed_plan_fields": list(methods_config["model_plan_allowed_fields"]),
        "company_capabilities_sha256": digest_json(capabilities),
        "batch_sizes": {
            method: methods_config["methods"][method]["batch_size"]
            for method in ("qwen", "luna")
        },
    }
    if run["model_payload"] != expected_payload_binding:
        raise ExperimentError("method_binding_mismatch", "run model payload binding이 현재 입력과 다릅니다")
    method_config = methods_config["methods"][method_name]
    binding = run["methods"][method_name]
    expected_binding = {
        "method_version": method_config.get("method_version"),
        "model_name": method_config.get("model_name"),
        "model_revision": method_config.get("model_revision"),
        "prompt_id": method_config.get("prompt_id"),
        "prompt_sha256": method_config.get("prompt_sha256"),
        "config_sha256": digest_json(method_config),
    }
    for key, expected_value in expected_binding.items():
        if binding.get(key) != expected_value:
            raise ExperimentError("method_binding_mismatch", f"run method binding {key}가 다릅니다")
    if method_name == "keyword" and not method_config.get("positive_rules"):
        raise ExperimentError("keyword_rules_missing", "승인된 고정 keyword positive_rules가 필요합니다")
    if method_name != "keyword":
        revision = method_config.get("model_revision")
        if not isinstance(revision, str) or not revision or revision == method_config.get("model_name"):
            raise ExperimentError("model_revision_unfixed", "고정 model revision 또는 digest가 필요합니다")
        if not isinstance(method_config.get("model_name"), str) or not method_config["model_name"]:
            raise ExperimentError("model_name_missing", "model_name이 필요합니다")
    if method_name == "bge_m3_colbert":
        revision = method_config["model_revision"]
        if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
            raise ExperimentError("model_revision_unfixed", "BGE-M3에 40자 commit SHA가 필요합니다")
    if method_name == "qwen" and not is_sha256(method_config["model_revision"]):
        raise ExperimentError("model_revision_unfixed", "Qwen에 64자 model digest가 필요합니다")
    if method_name == "luna" and method_config.get("reasoning_effort") != "xhigh":
        raise ExperimentError("reasoning_effort_mismatch", "Luna reasoning effort는 xhigh여야 합니다")
    if method_name in {"qwen", "luna"} and not method_config.get("prompt_sha256"):
        raise ExperimentError("prompt_hash_unfixed", "고정 prompt_sha256이 필요합니다")
    return methods_config, method_config, capabilities


def rank_rows(rows: list[dict[str, Any]], top_k: int) -> None:
    successful = [row for row in rows if row["status"] == "success"]
    successful.sort(key=lambda row: (-float(row["score"]), row["plan_id"]))
    for rank, row in enumerate(successful, start=1):
        row["rank"] = rank
        row["selected"] = rank <= top_k


def failure_row(plan_id: str, failure: AdapterFailure) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "status": "failed",
        "score": None,
        "rank": None,
        "selected": False,
        "reason": None,
        "relevance": None,
        "evidence_fields": [],
        "latency_ms": failure.latency_ms,
        "error_code": failure.error_code,
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "device": None,
    }


def success_row(plan_id: str, result: AdapterResult) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "status": "success",
        "score": result.score,
        "rank": None,
        "selected": False,
        "reason": result.reason,
        "relevance": result.relevance,
        "evidence_fields": result.evidence_fields,
        "latency_ms": result.latency_ms,
        "error_code": None,
        "input_tokens": result.input_tokens,
        "cached_input_tokens": result.cached_input_tokens,
        "output_tokens": result.output_tokens,
        "device": result.device,
    }


def execute_adapter(
    adapter: Any,
    plans: Sequence[dict[str, Any]],
    capabilities: dict[str, Any],
    top_k: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if hasattr(adapter, "prepare"):
        try:
            adapter.prepare()
        except AdapterFailure as exc:
            rows = [failure_row(plan["plan_id"], exc) for plan in plans]
            rank_rows(rows, top_k)
            return rows
    if hasattr(adapter, "score_all"):
        try:
            results = adapter.score_all(plans, capabilities)
            if len(results) != len(plans):
                raise AdapterFailure("population_coverage_mismatch")
            rows = [success_row(plan["plan_id"], result) for plan, result in zip(plans, results, strict=True)]
        except AdapterFailure as exc:
            rows = [failure_row(plan["plan_id"], exc) for plan in plans]
    elif hasattr(adapter, "score_many"):
        try:
            outcomes = adapter.score_many(plans, capabilities)
            if len(outcomes) != len(plans):
                raise AdapterFailure("population_coverage_mismatch")
            for plan, outcome in zip(plans, outcomes, strict=True):
                if isinstance(outcome, AdapterResult):
                    rows.append(success_row(plan["plan_id"], outcome))
                elif isinstance(outcome, AdapterFailure):
                    rows.append(failure_row(plan["plan_id"], outcome))
                else:
                    raise AdapterFailure("malformed_response")
        except AdapterFailure as exc:
            rows = [failure_row(plan["plan_id"], exc) for plan in plans]
    else:
        for plan in plans:
            try:
                result = adapter.score(plan, capabilities)
                if not isinstance(result, AdapterResult):
                    raise AdapterFailure("malformed_response")
                rows.append(success_row(plan["plan_id"], result))
            except AdapterFailure as exc:
                rows.append(failure_row(plan["plan_id"], exc))
    rank_rows(rows, top_k)
    return rows


def sum_or_none(rows: Sequence[dict[str, Any]], field: str) -> int | None:
    values = [row[field] for row in rows if row[field] is not None]
    return sum(values) if values else None


def calculate_luna_cost(rows: Sequence[dict[str, Any]], pricing: dict[str, Any]) -> float | None:
    input_tokens = sum_or_none(rows, "input_tokens")
    cached_tokens = sum_or_none(rows, "cached_input_tokens")
    output_tokens = sum_or_none(rows, "output_tokens")
    if input_tokens is None and output_tokens is None:
        return None
    uncached = max(0, (input_tokens or 0) - (cached_tokens or 0))
    cost = (
        uncached * float(pricing["input"])
        + (cached_tokens or 0) * float(pricing["cached_input"])
        + (output_tokens or 0) * float(pricing["output"])
    ) / 1_000_000
    return round(cost, 8)


def build_result(
    run: dict[str, Any],
    population: dict[str, Any],
    method_name: str,
    method_config: dict[str, Any],
    rows: list[dict[str, Any]],
    prompt_hash: str | None,
    approval: dict[str, Any] | None,
    top_k: int,
    elapsed_ms: int,
) -> dict[str, Any]:
    success_count = sum(row["status"] == "success" for row in rows)
    failure_count = len(rows) - success_count
    status = "success" if failure_count == 0 else "failed" if success_count == 0 else "partial_failure"
    latency_total = sum_or_none(rows, "latency_ms")
    metrics = {
        "population_count": len(rows),
        "success_count": success_count,
        "failure_count": failure_count,
        "selected_count": sum(bool(row["selected"]) for row in rows),
        "elapsed_ms": elapsed_ms,
        "total_latency_ms": latency_total,
        "average_latency_ms": round(latency_total / len(rows), 3) if latency_total is not None and rows else None,
        "input_tokens": sum_or_none(rows, "input_tokens"),
        "cached_input_tokens": sum_or_none(rows, "cached_input_tokens"),
        "output_tokens": sum_or_none(rows, "output_tokens"),
        "cost_usd": calculate_luna_cost(
            rows, method_config["pricing_usd_per_million_tokens"]
        )
        if method_name == "luna"
        else None,
        "device": next((row["device"] for row in rows if row["device"]), None),
    }
    approval_record = None
    if approval is not None:
        approval_record = {
            "model": approval["model"],
            "purpose": approval["purpose"],
            "prompt_sha256": approval["prompt_sha256"],
            "company_capabilities_sha256": approval["company_capabilities_sha256"],
            "payload_fields": approval["payload_fields"],
            "record_count": approval["record_count"],
            "batch_size": approval["batch_size"],
            "batch_count": approval["batch_count"],
            "preview_sha256": approval["preview_sha256"],
            "approved_by": approval["approved_by"],
            "approved_at": approval["approved_at"],
        }
    batching = None
    if method_name in {"qwen", "luna"}:
        batch_size = int(method_config["batch_size"])
        batching = {
            "mode": "fixed",
            "batch_size": batch_size,
            "batch_count": (len(rows) + batch_size - 1) // batch_size,
        }
    return {
        "schema_version": METHOD_RESULT_SCHEMA,
        "run_id": run["run_id"],
        "created_at": datetime.now(KST).isoformat(),
        "input_sha256": population["population_sha256"],
        "method": method_name,
        "method_version": method_config["method_version"],
        "top_k": top_k,
        "config_sha256": digest_json(method_config),
        "model": {
            "name": method_config.get("model_name"),
            "revision": method_config.get("model_revision"),
        },
        "prompt": {"id": method_config.get("prompt_id"), "sha256": prompt_hash},
        "batching": batching,
        "status": status,
        "metrics": metrics,
        "external_approval": approval_record,
        "items": rows,
    }


def main() -> int:
    args = parse_args()
    try:
        run_dir = args.run_dir.resolve()
        run, population = load_run_population(run_dir)
        methods_config, method_config, capabilities = check_bindings(
            run,
            args.method,
            args.methods_config.resolve(),
            args.company_capabilities.resolve(),
        )
        prompt, prompt_hash = read_prompt(args.prompt_file, method_config.get("prompt_sha256"))
        approval = None
        if args.method == "luna":
            preview = external_preview(
                population,
                capabilities,
                methods_config["model_plan_allowed_fields"],
                method_config["model_revision"],
                method_config["prompt_sha256"],
                method_config["batch_size"],
            )
            expected_run_approval = {
                "status": "approved",
                **preview,
            }
            actual_run_approval = run.get("external_transmission")
            if not isinstance(actual_run_approval, dict):
                raise ExperimentError("preview_mismatch", "run의 외부 payload preview가 없습니다")
            if {
                key: value
                for key, value in actual_run_approval.items()
                if key not in {"approved_by", "approved_at"}
            } != expected_run_approval:
                raise ExperimentError("preview_mismatch", "run의 외부 payload preview가 현재 입력과 다릅니다")
            if args.external_approval is None:
                raise ExperimentError("external_approval_missing", "Luna 실행 승인 파일이 필요합니다")
            approval = validate_external_approval(load_json(args.external_approval), run, preview)
            if (
                actual_run_approval.get("approved_by") != approval["approved_by"]
                or actual_run_approval.get("approved_at") != approval["approved_at"]
            ):
                raise ExperimentError("approval_mismatch", "run에 기록된 외부 승인과 승인 파일이 다릅니다")
        elif args.external_approval is not None:
            raise ExperimentError("approval_not_applicable", "외부 승인 파일은 Luna에만 사용합니다")
        if args.check_ready:
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "run_id": run["run_id"],
                        "method": args.method,
                        "population_count": len(population["items"]),
                        "model_name": method_config.get("model_name"),
                        "model_revision": method_config.get("model_revision"),
                        "prompt_sha256": prompt_hash,
                        "batch_size": method_config.get("batch_size")
                        if args.method in {"qwen", "luna"}
                        else None,
                        "batch_count": (
                            len(population["items"]) + method_config["batch_size"] - 1
                        )
                        // method_config["batch_size"]
                        if args.method in {"qwen", "luna"}
                        else None,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        execution_started = time.monotonic()
        if args.method == "keyword":
            adapter = KeywordAdapter(method_config)
        elif args.method == "bge_m3_colbert":
            adapter = BGEM3ColBERTAdapter(method_config)
        elif args.method == "qwen":
            if prompt is None:
                raise ExperimentError("prompt_missing", "Qwen prompt가 필요합니다")
            adapter = QwenAdapter(method_config, prompt)
        else:
            if prompt is None:
                raise ExperimentError("prompt_missing", "Luna prompt가 필요합니다")
            adapter = LunaAdapter(method_config, prompt)
        rows = execute_adapter(
            adapter,
            population["items"],
            capabilities,
            methods_config["top_k"],
        )
        elapsed_ms = max(0, round((time.monotonic() - execution_started) * 1000))
        result = build_result(
            run,
            population,
            args.method,
            method_config,
            rows,
            prompt_hash,
            approval,
            methods_config["top_k"],
            elapsed_ms,
        )
        validate_method_result(result, population, args.method, run["selection"]["top_k"])
        validate_result_run_binding(result, run)
        output = run_dir / "results" / f"{args.method}.json"
        write_json_new(output, result)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "method": args.method,
                    "success_count": result["metrics"]["success_count"],
                    "failure_count": result["metrics"]["failure_count"],
                    "selected_count": result["metrics"]["selected_count"],
                    "elapsed_ms": result["metrics"]["elapsed_ms"],
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
