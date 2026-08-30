"""Small immutable-file contracts for the order-plan screening experiment."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence


POPULATION_SCHEMA = "bidops.order-plan-population.v1"
RUN_SCHEMA = "bidops.order-plan-screening-run.v3"
RAW_PAGE_SCHEMA = "bidops.order-plan-raw-page.v1"
METHOD_RESULT_SCHEMA = "bidops.order-plan-method-result.v3"
CAPABILITIES_SCHEMA = "bidops.order-plan-capabilities.v1"
METHODS_CONFIG_SCHEMA = "bidops.order-plan-methods.v3"
EXTERNAL_APPROVAL_SCHEMA = "bidops.order-plan-external-approval.v2"
REVIEW_MANIFEST_SCHEMA = "bidops.order-plan-review-manifest.v1"

METHOD_NAMES = (
    "keyword",
    "tfidf",
    "bge_m3_dense",
    "bge_m3_colbert",
    "qwen",
    "luna",
)
BATCHED_METHOD_NAMES = ("bge_m3_dense", "qwen", "luna")
JUDGMENT_METHOD_NAMES = {"qwen", "luna"}
ROW_STATUSES = {"success", "failed"}
HEX_64 = set("0123456789abcdef")


class ExperimentError(RuntimeError):
    """A stable, safe-to-display experiment validation failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExperimentError("duplicate_json_key", f"중복 JSON 키: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys
        )
    except ExperimentError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExperimentError("invalid_json", f"JSON을 읽을 수 없습니다: {path.name}") from exc


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ExperimentError("file_read_failed", f"파일을 읽을 수 없습니다: {path.name}") from exc
    return digest.hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX_64


def write_json_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except FileExistsError as exc:
        raise ExperimentError("artifact_exists", f"기존 산출물을 덮어쓸 수 없습니다: {path.name}") from exc
    except (OSError, ValueError) as exc:
        raise ExperimentError("artifact_write_failed", f"산출물을 쓸 수 없습니다: {path.name}") from exc


def write_tsv_new(path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
                delimiter="\t",
                lineterminator="\n",
                extrasaction="raise",
            )
            writer.writeheader()
            writer.writerows(rows)
    except FileExistsError as exc:
        raise ExperimentError("artifact_exists", f"기존 산출물을 덮어쓸 수 없습니다: {path.name}") from exc
    except (OSError, ValueError) as exc:
        raise ExperimentError("artifact_write_failed", f"산출물을 쓸 수 없습니다: {path.name}") from exc


def parse_timezone_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ExperimentError("invalid_timestamp", f"{field}에 timezone 포함 timestamp가 필요합니다")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ExperimentError("invalid_timestamp", f"{field} timestamp 형식이 잘못됐습니다") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExperimentError("invalid_timestamp", f"{field}에 timezone 정보가 없습니다")
    return parsed


def require_keys(value: Any, keys: Iterable[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExperimentError("invalid_contract", f"{label}은 JSON object여야 합니다")
    missing = [key for key in keys if key not in value]
    if missing:
        raise ExperimentError("missing_field", f"{label} 필드 누락: {', '.join(missing)}")
    return value


def require_exact_keys(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    obj = require_keys(value, keys, label)
    extras = sorted(set(obj) - keys)
    if extras:
        raise ExperimentError("unexpected_field", f"{label} 허용 밖 필드: {', '.join(extras)}")
    return obj


def validate_population(document: Any) -> dict[str, Any]:
    population = require_keys(
        document,
        (
            "schema_version",
            "run_id",
            "created_at",
            "input_sha256",
            "population_sha256",
            "items",
        ),
        "population",
    )
    if population["schema_version"] != POPULATION_SCHEMA:
        raise ExperimentError("schema_mismatch", "population schema_version이 다릅니다")
    if not isinstance(population["run_id"], str) or not population["run_id"]:
        raise ExperimentError("invalid_run_id", "population run_id가 비어 있습니다")
    parse_timezone_timestamp(population["created_at"], "population.created_at")
    if not is_sha256(population["input_sha256"]):
        raise ExperimentError("invalid_hash", "population input_sha256이 잘못됐습니다")
    items = population["items"]
    if not isinstance(items, list):
        raise ExperimentError("invalid_contract", "population.items는 배열이어야 합니다")
    ids: list[str] = []
    for index, item in enumerate(items):
        row = require_keys(item, ("plan_id",), f"population.items[{index}]")
        plan_id = row["plan_id"]
        if not isinstance(plan_id, str) or not plan_id.strip():
            raise ExperimentError("missing_plan_id", f"population.items[{index}] plan_id가 없습니다")
        ids.append(plan_id)
    if len(ids) != len(set(ids)):
        raise ExperimentError("duplicate_plan_id", "population에 중복 plan_id가 있습니다")
    actual_hash = digest_json(items)
    if population["population_sha256"] != actual_hash:
        raise ExperimentError("hash_mismatch", "population_sha256이 items와 다릅니다")
    return population


def validate_run(document: Any, population: dict[str, Any]) -> dict[str, Any]:
    run = require_keys(
        document,
        (
            "schema_version",
            "run_id",
            "created_at",
            "input_sha256",
            "population_sha256",
            "population_count",
            "selection",
            "model_payload",
            "config",
            "methods",
        ),
        "run",
    )
    if run["schema_version"] != RUN_SCHEMA:
        raise ExperimentError("schema_mismatch", "run schema_version이 다릅니다")
    parse_timezone_timestamp(run["created_at"], "run.created_at")
    if run["run_id"] != population["run_id"]:
        raise ExperimentError("run_id_mismatch", "run과 population의 run_id가 다릅니다")
    if run["input_sha256"] != population["input_sha256"]:
        raise ExperimentError("hash_mismatch", "run과 population의 입력 hash가 다릅니다")
    if run["population_sha256"] != population["population_sha256"]:
        raise ExperimentError("hash_mismatch", "run과 population hash가 다릅니다")
    if run["population_count"] != len(population["items"]):
        raise ExperimentError("count_mismatch", "run population_count가 다릅니다")
    selection = require_exact_keys(run["selection"], {"top_k"}, "run.selection")
    if not isinstance(selection["top_k"], int) or isinstance(selection["top_k"], bool) or selection["top_k"] < 1:
        raise ExperimentError("invalid_top_k", "run selection.top_k가 잘못됐습니다")
    model_payload = require_exact_keys(
        run["model_payload"],
        {"allowed_plan_fields", "company_capabilities_sha256", "batch_sizes"},
        "run.model_payload",
    )
    allowed_fields = model_payload["allowed_plan_fields"]
    if (
        allowed_fields != ["title"]
        or not is_sha256(model_payload["company_capabilities_sha256"])
    ):
        raise ExperimentError("invalid_allowlist", "run model plan payload는 title 하나여야 합니다")
    batch_sizes = require_exact_keys(
        model_payload["batch_sizes"],
        set(BATCHED_METHOD_NAMES),
        "run.model_payload.batch_sizes",
    )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 1
        for value in batch_sizes.values()
    ):
        raise ExperimentError("invalid_batch_size", "run model batch size binding이 잘못됐습니다")
    if not isinstance(run["methods"], dict) or set(run["methods"]) != set(METHOD_NAMES):
        raise ExperimentError("method_set_mismatch", "run의 방법 binding이 완전하지 않습니다")
    return run


def load_run_population(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    population = validate_population(load_json(run_dir / "population.json"))
    run = validate_run(load_json(run_dir / "run.json"), population)
    return run, population


def load_methods_config(path: Path) -> dict[str, Any]:
    config = require_keys(
        load_json(path),
        ("schema_version", "top_k", "model_plan_allowed_fields", "methods"),
        "methods config",
    )
    if config["schema_version"] != METHODS_CONFIG_SCHEMA:
        raise ExperimentError("schema_mismatch", "methods config schema_version이 다릅니다")
    if not isinstance(config["top_k"], int) or isinstance(config["top_k"], bool) or config["top_k"] != 50:
        raise ExperimentError("invalid_top_k", "이 실험의 top_k는 50으로 고정됩니다")
    if not isinstance(config["methods"], dict) or set(config["methods"]) != set(METHOD_NAMES):
        raise ExperimentError("method_set_mismatch", "methods config에 고정 방법 전체가 필요합니다")
    for method_name, method_config in config["methods"].items():
        if not isinstance(method_config, dict):
            raise ExperimentError("invalid_contract", f"{method_name} config는 object여야 합니다")
        if not isinstance(method_config.get("method_version"), str) or not method_config["method_version"]:
            raise ExperimentError("invalid_contract", f"{method_name} method_version이 필요합니다")
    allowed = config["model_plan_allowed_fields"]
    if allowed != ["title"]:
        raise ExperimentError("invalid_allowlist", "발주계획 모델 입력은 title 하나로 고정됩니다")
    for method_name in BATCHED_METHOD_NAMES:
        batch_size = config["methods"][method_name].get("batch_size")
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ExperimentError("invalid_batch_size", f"{method_name} batch_size가 잘못됐습니다")
    return config


def capabilities_projection(document: Any, require_approved: bool = True) -> dict[str, Any]:
    keys = {
        "schema_version",
        "approval_status",
        "profile_version",
        "summary_sha256",
        "approved_by",
        "approved_at",
        "capabilities",
    }
    config = require_exact_keys(document, keys, "company capabilities")
    if config["schema_version"] != CAPABILITIES_SCHEMA:
        raise ExperimentError("schema_mismatch", "company capabilities schema_version이 다릅니다")
    if require_approved and config["approval_status"] != "approved":
        raise ExperimentError("capabilities_not_approved", "승인된 최소 회사 역량 요약이 필요합니다")
    capabilities = config["capabilities"]
    if not isinstance(capabilities, list):
        raise ExperimentError("invalid_capabilities", "capabilities는 배열이어야 합니다")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(capabilities):
        row = require_exact_keys(item, {"id", "summary"}, f"capabilities[{index}]")
        capability_id = row["id"]
        summary = row["summary"]
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ExperimentError("invalid_capabilities", f"capabilities[{index}].id가 비었습니다")
        if not isinstance(summary, str) or not summary.strip():
            raise ExperimentError("invalid_capabilities", f"capabilities[{index}].summary가 비었습니다")
        if capability_id in seen:
            raise ExperimentError("invalid_capabilities", "capability id가 중복됐습니다")
        seen.add(capability_id)
        normalized.append({"id": capability_id, "summary": summary})
    projection = {"profile_version": config["profile_version"], "capabilities": normalized}
    if config["approval_status"] == "approved":
        if not isinstance(config["profile_version"], str) or not config["profile_version"]:
            raise ExperimentError("invalid_capabilities", "승인 profile_version이 필요합니다")
        if not normalized:
            raise ExperimentError("invalid_capabilities", "승인 capabilities가 비어 있습니다")
        parse_timezone_timestamp(config["approved_at"], "company-capabilities.approved_at")
        if not isinstance(config["approved_by"], str) or not config["approved_by"].strip():
            raise ExperimentError("invalid_capabilities", "approved_by 감사 표식이 필요합니다")
        expected = digest_json(projection)
        if config["summary_sha256"] != expected:
            raise ExperimentError("hash_mismatch", "승인 회사 역량 summary_sha256이 다릅니다")
    elif config["approval_status"] != "pending":
        raise ExperimentError("invalid_capabilities", "approval_status는 pending 또는 approved여야 합니다")
    return projection


def load_capabilities(path: Path, require_approved: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    document = load_json(path)
    projection = capabilities_projection(document, require_approved=require_approved)
    return document, projection


def title_plan_projection(plan: dict[str, Any]) -> dict[str, str]:
    title = plan.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ExperimentError("payload_field_unavailable", "모델 입력에 비어 있지 않은 title이 필요합니다")
    return {"title": title}


def fixed_batches(values: Sequence[Any], batch_size: int) -> list[Sequence[Any]]:
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
        raise ExperimentError("invalid_batch_size", "batch_size는 1 이상의 정수여야 합니다")
    return [values[index : index + batch_size] for index in range(0, len(values), batch_size)]


def model_batch_payload(
    plans: Sequence[dict[str, Any]],
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    return {
        "company_capabilities": capabilities,
        "items": [
            {"item_id": item_id, **title_plan_projection(plan)}
            for item_id, plan in enumerate(plans)
        ],
    }


def external_preview(
    population: dict[str, Any],
    capabilities: dict[str, Any],
    allowed_fields: Sequence[str],
    model_name: str,
    prompt_sha256: str | None,
    batch_size: int,
) -> dict[str, Any]:
    if list(allowed_fields) != ["title"]:
        raise ExperimentError("invalid_allowlist", "외부 모델 plan payload는 title 하나여야 합니다")
    batches = [
        model_batch_payload(batch, capabilities)
        for batch in fixed_batches(population["items"], batch_size)
    ]
    return {
        "model": model_name,
        "purpose": "order_plan_screening_comparison",
        "prompt_sha256": prompt_sha256,
        "company_capabilities_sha256": digest_json(capabilities),
        "payload_fields": ["title"],
        "record_count": len(population["items"]),
        "batch_size": batch_size,
        "batch_count": len(batches),
        "preview_sha256": digest_json(
            {
                "model": model_name,
                "prompt_sha256": prompt_sha256,
                "company_capabilities_sha256": digest_json(capabilities),
                "batch_size": batch_size,
                "batches": batches,
            }
        ),
    }


def validate_external_approval(
    document: Any,
    run: dict[str, Any],
    preview: dict[str, Any],
) -> dict[str, Any]:
    keys = {
        "schema_version",
        "run_id",
        "model",
        "purpose",
        "prompt_sha256",
        "company_capabilities_sha256",
        "payload_fields",
        "record_count",
        "batch_size",
        "batch_count",
        "preview_sha256",
        "approved_by",
        "approved_at",
    }
    approval = require_exact_keys(document, keys, "external approval")
    if approval["schema_version"] != EXTERNAL_APPROVAL_SCHEMA:
        raise ExperimentError("schema_mismatch", "external approval schema_version이 다릅니다")
    for key in (
        "model",
        "purpose",
        "prompt_sha256",
        "company_capabilities_sha256",
        "payload_fields",
        "record_count",
        "batch_size",
        "batch_count",
        "preview_sha256",
    ):
        if approval[key] != preview[key]:
            raise ExperimentError("approval_mismatch", f"external approval {key}가 preview와 다릅니다")
    if approval["run_id"] != run["run_id"]:
        raise ExperimentError("approval_mismatch", "external approval run_id가 다릅니다")
    if not isinstance(approval["approved_by"], str) or not approval["approved_by"].strip():
        raise ExperimentError("approval_invalid", "external approval approved_by가 필요합니다")
    parse_timezone_timestamp(approval["approved_at"], "external-approval.approved_at")
    return approval


def validate_method_result(
    document: Any,
    population: dict[str, Any],
    expected_method: str | None = None,
    expected_top_k: int | None = None,
) -> dict[str, Any]:
    result = require_keys(
        document,
        (
            "schema_version",
            "run_id",
            "created_at",
            "input_sha256",
            "method",
            "method_version",
            "top_k",
            "config_sha256",
            "model",
            "prompt",
            "batching",
            "external_approval",
            "status",
            "metrics",
            "items",
        ),
        "method result",
    )
    if result["schema_version"] != METHOD_RESULT_SCHEMA:
        raise ExperimentError("schema_mismatch", "method result schema_version이 다릅니다")
    if result["run_id"] != population["run_id"]:
        raise ExperimentError("run_id_mismatch", "method result run_id가 다릅니다")
    if result["input_sha256"] != population["population_sha256"]:
        raise ExperimentError("hash_mismatch", "method result input_sha256이 다릅니다")
    if not isinstance(result["method"], str) or result["method"] not in METHOD_NAMES or (
        expected_method is not None and result["method"] != expected_method
    ):
        raise ExperimentError("method_mismatch", "method result의 방법명이 다릅니다")
    if not isinstance(result["top_k"], int) or isinstance(result["top_k"], bool) or result["top_k"] < 1:
        raise ExperimentError("invalid_top_k", "method result top_k가 잘못됐습니다")
    if expected_top_k is not None and result["top_k"] != expected_top_k:
        raise ExperimentError("invalid_top_k", "method result top_k가 run binding과 다릅니다")
    if result["method"] in BATCHED_METHOD_NAMES:
        batching = require_exact_keys(
            result["batching"], {"mode", "batch_size", "batch_count"}, "method result batching"
        )
        if batching["mode"] != "fixed":
            raise ExperimentError("invalid_batch_size", "모델 batch mode는 fixed여야 합니다")
        if (
            not isinstance(batching["batch_size"], int)
            or isinstance(batching["batch_size"], bool)
            or batching["batch_size"] < 1
        ):
            raise ExperimentError("invalid_batch_size", "method result batch_size가 잘못됐습니다")
        expected_batch_count = (
            len(population["items"]) + batching["batch_size"] - 1
        ) // batching["batch_size"]
        if (
            not isinstance(batching["batch_count"], int)
            or isinstance(batching["batch_count"], bool)
            or batching["batch_count"] != expected_batch_count
        ):
            raise ExperimentError("count_mismatch", "method result batch_count가 다릅니다")
    elif result["batching"] is not None:
        raise ExperimentError("invalid_contract", "비-batch 방법 result에는 batching이 없어야 합니다")
    parse_timezone_timestamp(result["created_at"], "method-result.created_at")
    items = result["items"]
    if not isinstance(items, list):
        raise ExperimentError("invalid_contract", "method result items는 배열이어야 합니다")
    population_by_id = {item["plan_id"]: item for item in population["items"]}
    population_ids = set(population_by_id)
    result_ids: list[str] = []
    success_rows: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        row = require_keys(
            item,
            (
                "plan_id",
                "status",
                "score",
                "rank",
                "selected",
                "reason",
                "relevance",
                "evidence_fields",
                "latency_ms",
                "error_code",
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "device",
            ),
            f"method-result.items[{index}]",
        )
        if not isinstance(row["plan_id"], str) or not row["plan_id"].strip():
            raise ExperimentError("missing_plan_id", "method item plan_id가 비었거나 잘못됐습니다")
        result_ids.append(row["plan_id"])
        if not isinstance(row["status"], str) or row["status"] not in ROW_STATUSES:
            raise ExperimentError("invalid_status", "method item status가 잘못됐습니다")
        if not isinstance(row["selected"], bool):
            raise ExperimentError("invalid_contract", "method item selected는 boolean이어야 합니다")
        if row["latency_ms"] is not None and (
            not isinstance(row["latency_ms"], int)
            or isinstance(row["latency_ms"], bool)
            or row["latency_ms"] < 0
        ):
            raise ExperimentError("invalid_contract", "latency_ms가 잘못됐습니다")
        for token_field in ("input_tokens", "cached_input_tokens", "output_tokens"):
            token_value = row[token_field]
            if token_value is not None and (
                not isinstance(token_value, int) or isinstance(token_value, bool) or token_value < 0
            ):
                raise ExperimentError("invalid_contract", f"{token_field}가 잘못됐습니다")
        evidence_fields = row["evidence_fields"]
        if (
            not isinstance(evidence_fields, list)
            or not all(isinstance(field_name, str) and field_name for field_name in evidence_fields)
            or len(evidence_fields) != len(set(evidence_fields))
        ):
            raise ExperimentError("invalid_contract", "evidence_fields가 잘못됐습니다")
        if row["status"] == "success":
            if not isinstance(row["score"], (int, float)) or isinstance(row["score"], bool):
                raise ExperimentError("invalid_score", "성공 item에 숫자 score가 필요합니다")
            if not math.isfinite(float(row["score"])):
                raise ExperimentError("invalid_score", "score는 유한한 값이어야 합니다")
            if not isinstance(row["rank"], int) or isinstance(row["rank"], bool) or row["rank"] < 1:
                raise ExperimentError("invalid_rank", "성공 item에 rank가 필요합니다")
            if row["error_code"] is not None:
                raise ExperimentError("invalid_contract", "성공 item에는 error_code가 없어야 합니다")
            if not isinstance(row["reason"], str) or not row["reason"].strip() or len(row["reason"]) > 500:
                raise ExperimentError("invalid_contract", "성공 item에 짧은 reason이 필요합니다")
            if result["method"] in JUDGMENT_METHOD_NAMES:
                if (
                    row["relevance"] not in {"relevant", "not_relevant", "uncertain"}
                    or evidence_fields != ["title"]
                ):
                    raise ExperimentError("invalid_contract", "모델 item에 관련성과 근거 필드가 필요합니다")
                source_plan = population_by_id.get(row["plan_id"])
                if source_plan is None or not set(evidence_fields) <= set(source_plan):
                    raise ExperimentError("invalid_contract", "모델 근거가 모집단에 없는 필드를 참조합니다")
            elif row["relevance"] is not None or evidence_fields:
                raise ExperimentError("invalid_contract", "비판정 방법은 모델 관련성 필드를 가질 수 없습니다")
            success_rows.append(row)
        else:
            if (
                row["score"] is not None
                or row["rank"] is not None
                or row["selected"]
                or row["reason"] is not None
                or row["relevance"] is not None
                or evidence_fields
            ):
                raise ExperimentError("invalid_failure", "실패 item은 score/rank/selected를 가질 수 없습니다")
            if not isinstance(row["error_code"], str) or not row["error_code"]:
                raise ExperimentError("invalid_failure", "실패 item에는 error_code가 필요합니다")
    if len(result_ids) != len(set(result_ids)):
        raise ExperimentError("duplicate_plan_id", "method result에 중복 plan_id가 있습니다")
    if set(result_ids) != population_ids:
        raise ExperimentError("population_coverage_mismatch", "method result가 모집단 전체를 덮지 않습니다")
    expected_order = sorted(success_rows, key=lambda row: (-float(row["score"]), row["plan_id"]))
    expected_ranks = {row["plan_id"]: index + 1 for index, row in enumerate(expected_order)}
    for row in success_rows:
        if row["rank"] != expected_ranks[row["plan_id"]]:
            raise ExperimentError("invalid_rank", "동점 plan_id 규칙과 rank가 다릅니다")
    selected_ranks = sorted(row["rank"] for row in success_rows if row["selected"])
    expected_selected = min(result["top_k"], len(success_rows))
    if selected_ranks != list(range(1, expected_selected + 1)):
        raise ExperimentError("invalid_selection", "selected는 성공 상위 top_k 전체여야 합니다")

    metrics = require_keys(
        result["metrics"],
        (
            "population_count",
            "success_count",
            "failure_count",
            "selected_count",
            "elapsed_ms",
        ),
        "method result metrics",
    )
    if (
        not isinstance(metrics["elapsed_ms"], int)
        or isinstance(metrics["elapsed_ms"], bool)
        or metrics["elapsed_ms"] < 0
    ):
        raise ExperimentError("invalid_contract", "method result metrics.elapsed_ms가 잘못됐습니다")
    expected_status = (
        "success"
        if len(success_rows) == len(items)
        else "failed"
        if not success_rows
        else "partial_failure"
    )
    if result["status"] != expected_status:
        raise ExperimentError("invalid_status", "method result status와 item 상태가 다릅니다")
    expected_metrics = {
        "population_count": len(items),
        "success_count": len(success_rows),
        "failure_count": len(items) - len(success_rows),
        "selected_count": expected_selected,
    }
    for key, expected_value in expected_metrics.items():
        if (
            not isinstance(metrics[key], int)
            or isinstance(metrics[key], bool)
            or metrics[key] != expected_value
        ):
            raise ExperimentError("count_mismatch", f"method result metrics.{key}가 다릅니다")
    return result


def validate_result_run_binding(
    result: dict[str, Any],
    run: dict[str, Any],
) -> None:
    method_name = result["method"]
    binding = run["methods"].get(method_name)
    if not isinstance(binding, dict):
        raise ExperimentError("method_binding_mismatch", "run method binding이 없습니다")
    expected_values = {
        "method_version": binding.get("method_version"),
        "config_sha256": binding.get("config_sha256"),
        "model": {
            "name": binding.get("model_name"),
            "revision": binding.get("model_revision"),
        },
        "prompt": {
            "id": binding.get("prompt_id"),
            "sha256": binding.get("prompt_sha256"),
        },
    }
    for key, expected_value in expected_values.items():
        if result.get(key) != expected_value:
            raise ExperimentError("method_binding_mismatch", f"method result {key}가 run binding과 다릅니다")
    if method_name == "luna":
        transmission = run.get("external_transmission")
        if not isinstance(transmission, dict) or transmission.get("status") != "approved":
            raise ExperimentError("external_approval_missing", "run에 승인된 Luna 전송 기록이 없습니다")
        expected_approval = {
            key: value for key, value in transmission.items() if key != "status"
        }
        if result.get("external_approval") != expected_approval:
            raise ExperimentError("approval_mismatch", "Luna result와 run의 외부 승인 기록이 다릅니다")
    elif result.get("external_approval") is not None:
        raise ExperimentError("approval_not_applicable", "Luna 외 result에 외부 승인 기록이 있습니다")
    if method_name in BATCHED_METHOD_NAMES:
        batch_size = run["model_payload"]["batch_sizes"][method_name]
        if result["batching"]["batch_size"] != batch_size:
            raise ExperimentError("method_binding_mismatch", "method result batch_size가 run binding과 다릅니다")
    if method_name in JUDGMENT_METHOD_NAMES:
        for row in result["items"]:
            if row["status"] == "success" and row["evidence_fields"] != ["title"]:
                raise ExperimentError("external_payload_rejected", "모델 근거는 title로 고정됩니다")


def safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator
