#!/usr/bin/env python3
"""Merge the Phase 1 screening artifacts without inventing model results."""

from __future__ import annotations

import argparse
import importlib.util
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


def _load_phase0_helpers() -> Any:
    module_name = "_bidops_order_plan_phase0_helpers"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    helper_path = Path(__file__).resolve().with_name("validate_order_plan_phase0.py")
    spec = importlib.util.spec_from_file_location(module_name, helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Phase 0 helper module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_ranker() -> Any:
    module_name = "_bidops_order_plan_bm25_ranker"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    script_path = Path(__file__).resolve().with_name("rank_order_plans_bm25.py")
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Phase 1 ranker module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


PHASE0 = _load_phase0_helpers()
RANKER = _load_ranker()
ContractError = PHASE0.ContractError

RANKING_SCHEMA = "bidops.order-plan-screening-ranking.v1"
DECISIONS_SCHEMA = "bidops.order-plan-screening-decisions.v1"
FAILURES_SCHEMA = "bidops.order-plan-screening-failures.v1"
TELEMETRY_SCHEMA = "bidops.order-plan-screening-telemetry.v1"
RESULT_SCHEMA = "bidops.order-plan-screening-result.v1"
TOP_K = 300
BATCH_SIZE = 25
MAX_ATTEMPTS = 2
RETRYABLE_FAILURE_TYPES = {"timeout", "truncated_output", "schema_violation", "id_mismatch", "transport"}
REJECTION_FAILURE_TYPES = {"model_mismatch", "binding_mismatch", "payload_not_approved", "policy_rejected"}
FAILURE_TYPES = RETRYABLE_FAILURE_TYPES | REJECTION_FAILURE_TYPES | {"unknown"}

RANKING_KEYS = {
    "schema_version",
    "producer",
    "consumer",
    "execution_id",
    "source_run_id",
    "input_artifact_sha256",
    "policy_version",
    "policy_sha256",
    "status",
    "population_count",
    "selected_count",
    "filtered_out_count",
    "items",
    "created_at",
}
RANKING_ITEM_KEYS = {"plan_id", "rank", "score", "nearest_capability", "stage1_status"}
DECISIONS_KEYS = {
    "schema_version",
    "producer",
    "consumer",
    "execution_id",
    "source_run_id",
    "input_artifact_sha256",
    "ranking_artifact_sha256",
    "binding",
    "status",
    "candidate_count",
    "success_count",
    "failure_count",
    "batch_count",
    "batches",
    "items",
    "created_at",
}
DECISION_BINDING_KEYS = {
    "model_name",
    "model_digest",
    "prompt_version",
    "prompt_sha256",
    "company_profile_version",
    "company_profile_sha256",
    "generation_config_sha256",
}
DECISION_BATCH_KEYS = {"batch_id", "sequence", "plan_ids", "attempt_count", "status"}
DECISION_ITEM_KEYS = {"plan_id", "batch_id", "attempt_no", "relevance", "score", "reason"}
FAILURES_KEYS = {
    "schema_version",
    "producer",
    "consumer",
    "execution_id",
    "source_run_id",
    "status",
    "failure_count",
    "failures",
    "created_at",
}
FAILURE_KEYS = {
    "batch_id",
    "sequence",
    "plan_ids",
    "attempt_count",
    "max_attempts",
    "failure_type",
    "outcome",
    "status",
    "error_code",
}
TELEMETRY_KEYS = {
    "schema_version",
    "producer",
    "consumer",
    "execution_id",
    "source_run_id",
    "status",
    "execution",
    "batches",
    "created_at",
}
MEASUREMENT_KEYS = {
    "started_at",
    "finished_at",
    "duration_ms",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "total_tokens",
}
TELEMETRY_BATCH_KEYS = {"batch_id", "sequence", "status", "attempts"}
ATTEMPT_KEYS = {"attempt_no", "status", "started_at", "finished_at", "measurement"}
RESULT_KEYS = {
    "schema_version",
    "producer",
    "consumer",
    "execution_id",
    "source_run_id",
    "input_artifact_sha256",
    "policy_version",
    "policy_sha256",
    "status",
    "partial_artifact",
    "counts",
    "items",
    "created_at",
}
RESULT_COUNTS_KEYS = {
    "population",
    "stage1_selected",
    "stage1_filtered_out",
    "stage1_failed",
    "stage2_relevant",
    "stage2_not_relevant",
    "stage2_uncertain",
    "stage2_failed",
    "stage2_rejected",
    "human_review_count",
}
RESULT_ITEM_KEYS = {
    "plan_id",
    "stage1_status",
    "stage1_rank",
    "stage1_score",
    "nearest_capability",
    "stage2_status",
    "qwen_relevance",
    "qwen_score",
    "qwen_reason",
    "batch_id",
    "attempt_no",
    "failure_code",
}


def _error(code: str, message: str) -> None:
    raise ContractError(code, message)


def _string(value: Any, label: str, *, nonblank: bool = True) -> str:
    if not isinstance(value, str) or (nonblank and not value.strip()):
        _error("invalid_field", f"{label}이(가) 잘못됐습니다")
    return value


def _integer(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _error("invalid_field", f"{label} 정수 형식이 잘못됐습니다")
    if minimum is not None and value < minimum:
        _error("invalid_field", f"{label} 값이 범위를 벗어났습니다")
    return value


def _number(value: Any, label: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _error("invalid_field", f"{label} 숫자 형식이 잘못됐습니다")
    if minimum is not None and value < minimum:
        _error("invalid_field", f"{label} 값이 범위를 벗어났습니다")
    if maximum is not None and value > maximum:
        _error("invalid_field", f"{label} 값이 범위를 벗어났습니다")
    return float(value)


def _hash(value: Any, label: str) -> str:
    if not PHASE0.is_sha256(value):
        _error("invalid_hash", f"{label} SHA-256이 잘못됐습니다")
    return value


def _validate_execution(document: Mapping[str, Any], expected: Mapping[str, Any], label: str) -> None:
    _string(document["execution_id"], f"{label}.execution_id")
    _string(document["source_run_id"], f"{label}.source_run_id")
    if document["execution_id"] != expected["execution_id"] or document["source_run_id"] != expected["source_run_id"]:
        _error("execution_mismatch", f"{label} execution binding이 다릅니다")


def _validate_created_at(document: Mapping[str, Any], label: str) -> None:
    PHASE0.parse_timestamp(document["created_at"], f"{label}.created_at")


def _validate_ranking(path: Path, frozen: Mapping[str, Any]) -> dict[str, Any]:
    document = PHASE0.require_exact_keys(PHASE0.load_json(path), RANKING_KEYS, "ranking artifact")
    if document["schema_version"] != RANKING_SCHEMA or document["producer"] != "order-plan-screening-bm25" or document["consumer"] != "order-plan-screening-merge":
        _error("provenance_mismatch", "ranking artifact provenance가 다릅니다")
    _validate_execution(document, frozen["document"], "ranking")
    _hash(document["input_artifact_sha256"], "ranking.input_artifact_sha256")
    if document["input_artifact_sha256"] != frozen["sha256"]:
        _error("digest_mismatch", "ranking input digest가 다릅니다")
    _string(document["policy_version"], "ranking.policy_version")
    _hash(document["policy_sha256"], "ranking.policy_sha256")
    if document["policy_version"] != frozen["policy"]["version"] or document["policy_sha256"] != frozen["policy"]["sha256"]:
        _error("binding_mismatch", "ranking policy binding이 다릅니다")
    if document["status"] not in {"성공", "실패"}:
        _error("invalid_status", "ranking status가 잘못됐습니다")
    _validate_created_at(document, "ranking")
    population_count = _integer(document["population_count"], "ranking.population_count", minimum=1)
    selected_count = _integer(document["selected_count"], "ranking.selected_count", minimum=0)
    filtered_count = _integer(document["filtered_out_count"], "ranking.filtered_out_count", minimum=0)
    if population_count != frozen["document"]["population_count"]:
        _error("population_mismatch", "ranking population_count가 input과 다릅니다")
    items = document["items"]
    if not isinstance(items, list) or len(items) != population_count:
        _error("population_mismatch", "ranking이 전체 모집단을 포함하지 않습니다")
    by_id: dict[str, dict[str, Any]] = {}
    ranks: list[int] = []
    ranked_items: list[dict[str, Any]] = []
    failed_items: list[dict[str, Any]] = []
    for index, value in enumerate(items):
        row = PHASE0.require_exact_keys(value, RANKING_ITEM_KEYS, f"ranking item {index}")
        plan_id = _string(row["plan_id"], f"ranking item {index}.plan_id")
        if plan_id in by_id:
            _error("duplicate_plan_id", "ranking plan id가 중복됐습니다")
        if plan_id not in frozen["items_by_id"]:
            _error("population_mismatch", "ranking에 input에 없는 plan이 있습니다")
        if row["stage1_status"] not in {"selected", "filtered_out", "failed", "rejected"}:
            _error("invalid_status", "ranking stage1_status가 잘못됐습니다")
        if row["stage1_status"] in {"failed", "rejected"}:
            if row["rank"] is not None or row["score"] is not None or row["nearest_capability"] is not None:
                _error("ranking_invalid", "실패한 ranking item은 rank/score/capability가 없어야 합니다")
            failed_items.append(row)
        else:
            rank = _integer(row["rank"], f"ranking item {index}.rank", minimum=1)
            _number(row["score"], f"ranking item {index}.score", minimum=0.0)
            if row["nearest_capability"] is not None:
                _string(row["nearest_capability"], f"ranking item {index}.nearest_capability")
            ranked_items.append(row)
            ranks.append(rank)
        by_id[plan_id] = row
    if sorted(ranks) != list(range(1, len(ranked_items) + 1)) or ranks != list(range(1, len(ranked_items) + 1)):
        _error("ranking_invalid", "ranking rank가 연속·순서대로 정렬되지 않았습니다")
    if ranked_items != sorted(ranked_items, key=lambda row: (-row["score"], row["plan_id"])):
        _error("ranking_invalid", "ranking score-desc/plan_id-asc 순서가 다릅니다")
    expected_selected = min(TOP_K, len(ranked_items))
    for index, row in enumerate(ranked_items):
        expected_status = "selected" if index < expected_selected else "filtered_out"
        if row["stage1_status"] != expected_status:
            _error("ranking_invalid", "ranking top-k/filter 경계가 다릅니다")
    if selected_count != sum(row["stage1_status"] == "selected" for row in ranked_items) or filtered_count != sum(row["stage1_status"] == "filtered_out" for row in ranked_items):
        _error("count_mismatch", "ranking selected/filter count가 다릅니다")
    if selected_count + filtered_count + len(failed_items) != population_count:
        _error("count_mismatch", "ranking status count가 모집단과 다릅니다")
    if document["status"] == "성공" and failed_items:
        _error("status_mismatch", "실패 item이 있는 ranking을 성공으로 표시할 수 없습니다")
    if document["status"] == "실패" and not failed_items:
        _error("status_mismatch", "실패 item이 없는 ranking을 실패로 표시할 수 없습니다")
    if set(by_id) != set(frozen["items_by_id"]):
        _error("population_mismatch", "ranking plan id 집합이 input과 다릅니다")
    return {
        "document": document,
        "sha256": PHASE0.sha256_file(path),
        "items": items,
        "items_by_id": by_id,
        "selected_ids": [row["plan_id"] for row in items if row["stage1_status"] == "selected"],
    }


def _validate_decision_binding(binding: Any, approved_stage2: Mapping[str, Any]) -> dict[str, Any]:
    row = PHASE0.require_exact_keys(binding, DECISION_BINDING_KEYS, "decisions.binding")
    for field in ("model_digest", "prompt_sha256", "company_profile_sha256", "generation_config_sha256"):
        _hash(row[field], f"decisions.binding.{field}")
    for field in ("prompt_version", "company_profile_version"):
        _string(row[field], f"decisions.binding.{field}")
    expected = {
        "model_name": approved_stage2["model_name"],
        "model_digest": approved_stage2["model_digest"],
        "prompt_version": approved_stage2["prompt_version"],
        "prompt_sha256": approved_stage2["prompt_sha256"],
        "company_profile_version": approved_stage2["company_profile_version"],
        "company_profile_sha256": approved_stage2["company_profile_sha256"],
        "generation_config_sha256": approved_stage2["generation_config_sha256"],
    }
    if row != expected:
        _error("binding_mismatch", "decisions stage2 binding이 승인된 Phase 0 binding과 다릅니다")
    return row


def _expected_batches(candidate_ids: Sequence[str]) -> list[list[str]]:
    return [list(candidate_ids[index : index + BATCH_SIZE]) for index in range(0, len(candidate_ids), BATCH_SIZE)]


def _validate_decisions(path: Path, frozen: Mapping[str, Any], ranking: Mapping[str, Any], approved_stage2: Mapping[str, Any]) -> dict[str, Any]:
    document = PHASE0.require_exact_keys(PHASE0.load_json(path), DECISIONS_KEYS, "decisions artifact")
    if document["schema_version"] != DECISIONS_SCHEMA or document["producer"] != "order-plan-screening-qwen-worker" or document["consumer"] != "order-plan-screening-merge":
        _error("provenance_mismatch", "decisions artifact provenance가 다릅니다")
    _validate_execution(document, frozen["document"], "decisions")
    _hash(document["input_artifact_sha256"], "decisions.input_artifact_sha256")
    _hash(document["ranking_artifact_sha256"], "decisions.ranking_artifact_sha256")
    if document["input_artifact_sha256"] != frozen["sha256"] or document["ranking_artifact_sha256"] != ranking["sha256"]:
        _error("digest_mismatch", "decisions input/ranking digest가 다릅니다")
    _validate_decision_binding(document["binding"], approved_stage2)
    if document["status"] not in {"성공", "부분 성공", "실패"}:
        _error("invalid_status", "decisions status가 잘못됐습니다")
    _validate_created_at(document, "decisions")
    candidate_ids = list(ranking["selected_ids"])
    candidate_set = set(candidate_ids)
    candidate_count = _integer(document["candidate_count"], "decisions.candidate_count", minimum=0)
    success_count = _integer(document["success_count"], "decisions.success_count", minimum=0)
    failure_count = _integer(document["failure_count"], "decisions.failure_count", minimum=0)
    batch_count = _integer(document["batch_count"], "decisions.batch_count", minimum=0)
    if candidate_count != len(candidate_ids):
        _error("count_mismatch", "decisions candidate_count가 ranking과 다릅니다")
    batches = document["batches"]
    if not isinstance(batches, list) or len(batches) != batch_count:
        _error("batch_mismatch", "decisions batch_count가 batches와 다릅니다")
    expected_batch_plans = _expected_batches(candidate_ids)
    if len(batches) > len(expected_batch_plans):
        _error("batch_mismatch", "decisions batch 수가 고정 batching policy와 다릅니다")
    batches_by_id: dict[str, dict[str, Any]] = {}
    failed_batches: list[dict[str, Any]] = []
    for index, value in enumerate(batches):
        batch = PHASE0.require_exact_keys(value, DECISION_BATCH_KEYS, f"decisions batch {index}")
        batch_id = _string(batch["batch_id"], f"decisions batch {index}.batch_id")
        if batch_id in batches_by_id:
            _error("duplicate_batch_id", "decisions batch id가 중복됐습니다")
        sequence = _integer(batch["sequence"], f"decisions batch {index}.sequence", minimum=1)
        attempt_count = _integer(batch["attempt_count"], f"decisions batch {index}.attempt_count", minimum=1)
        if attempt_count > MAX_ATTEMPTS:
            _error("batch_mismatch", "decisions attempt_count가 policy를 초과했습니다")
        plan_ids = batch["plan_ids"]
        if not isinstance(plan_ids, list) or not plan_ids or any(not isinstance(plan_id, str) or not plan_id.strip() for plan_id in plan_ids):
            _error("batch_mismatch", "decisions batch plan_ids가 잘못됐습니다")
        if len(plan_ids) != len(set(plan_ids)):
            _error("duplicate_plan_id", "decisions batch plan id가 중복됐습니다")
        if batch["status"] not in {"success", "failed", "rejected"}:
            _error("invalid_status", "decisions batch status가 잘못됐습니다")
        if sequence != index + 1 or plan_ids != expected_batch_plans[index]:
            _error("batch_mismatch", "decisions batch sequence/plan 순서가 policy와 다릅니다")
        batches_by_id[batch_id] = batch
        if batch["status"] != "success":
            failed_batches.append(batch)
    if failure_count != len(failed_batches):
        _error("count_mismatch", "decisions failure_count가 failed batch 수와 다릅니다")
    decision_items = document["items"]
    if not isinstance(decision_items, list):
        _error("invalid_contract", "decisions items가 배열이 아닙니다")
    if success_count != len(decision_items):
        _error("count_mismatch", "decisions success_count가 items 수와 다릅니다")
    items_by_id: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(decision_items):
        item = PHASE0.require_exact_keys(value, DECISION_ITEM_KEYS, f"decisions item {index}")
        plan_id = _string(item["plan_id"], f"decisions item {index}.plan_id")
        if plan_id in items_by_id:
            _error("duplicate_plan_id", "decisions plan id가 중복됐습니다")
        if plan_id not in candidate_set:
            _error("noncandidate_result", "Qwen decisions에 비대상 plan이 있습니다")
        batch_id = _string(item["batch_id"], f"decisions item {index}.batch_id")
        batch = batches_by_id.get(batch_id)
        if batch is None or batch["status"] != "success" or plan_id not in batch["plan_ids"]:
            _error("batch_mismatch", "decisions item의 batch binding이 다릅니다")
        attempt_no = _integer(item["attempt_no"], f"decisions item {index}.attempt_no", minimum=1)
        if attempt_no > batch["attempt_count"]:
            _error("batch_mismatch", "decisions item attempt_no가 batch와 다릅니다")
        if item["relevance"] not in {"relevant", "not_relevant", "uncertain"}:
            _error("invalid_field", "decisions relevance가 잘못됐습니다")
        _number(item["score"], f"decisions item {index}.score", minimum=0.0, maximum=1.0)
        reason = _string(item["reason"], f"decisions item {index}.reason")
        if len(reason) > 500:
            _error("invalid_field", "decisions reason이 너무 깁니다")
        items_by_id[plan_id] = item
    failed_plan_ids = {plan_id for batch in failed_batches for plan_id in batch["plan_ids"]}
    if not (set(items_by_id) | failed_plan_ids) <= candidate_set:
        _error("population_mismatch", "candidate 결과에 비대상 plan이 있습니다")
    if set(items_by_id) & failed_plan_ids:
        _error("duplicate_plan_id", "성공·실패 결과에 같은 plan이 있습니다")
    if document["status"] == "성공" and (failed_batches or success_count != candidate_count):
        _error("status_mismatch", "실패 batch가 있는 decisions를 성공으로 표시할 수 없습니다")
    if document["status"] == "부분 성공" and (success_count == 0 or success_count == candidate_count):
        _error("status_mismatch", "부분 성공 decisions의 성공·미처리 구성이 다릅니다")
    stage1_failed_without_stage2_candidate = (
        document["status"] == "실패"
        and candidate_count == 0
        and ranking["document"]["status"] == "실패"
        and any(item["stage1_status"] in {"failed", "rejected"} for item in ranking["items"])
    )
    if document["status"] == "실패" and (success_count != 0 or (not failed_batches and candidate_count == 0 and not stage1_failed_without_stage2_candidate)):
        _error("status_mismatch", "실패 decisions의 성공·실패 구성이 다릅니다")
    return {
        "document": document,
        "sha256": PHASE0.sha256_file(path),
        "binding": document["binding"],
        "batches": batches,
        "batches_by_id": batches_by_id,
        "items_by_id": items_by_id,
        "failed_batches": failed_batches,
    }


def _validate_failures(path: Path, frozen: Mapping[str, Any], decisions: Mapping[str, Any], ranking: Mapping[str, Any]) -> dict[str, Any]:
    document = PHASE0.require_exact_keys(PHASE0.load_json(path), FAILURES_KEYS, "failures artifact")
    if document["schema_version"] != FAILURES_SCHEMA or document["producer"] != "order-plan-screening-worker" or document["consumer"] != "order-plan-screening-review-and-merge":
        _error("provenance_mismatch", "failures artifact provenance가 다릅니다")
    _validate_execution(document, frozen["document"], "failures")
    if document["status"] not in {"none", "partial", "failed", "rejected"}:
        _error("invalid_status", "failures status가 잘못됐습니다")
    _validate_created_at(document, "failures")
    failure_count = _integer(document["failure_count"], "failures.failure_count", minimum=0)
    failures = document["failures"]
    if not isinstance(failures, list) or failure_count != len(failures):
        _error("count_mismatch", "failures failure_count가 failures와 다릅니다")
    failed_batches = decisions["failed_batches"]
    failed_by_id = {batch["batch_id"]: batch for batch in failed_batches}
    failure_by_batch: dict[str, dict[str, Any]] = {}
    failed_plan_ids: set[str] = set()
    outcomes: list[str] = []
    candidate_set = set(ranking["selected_ids"])
    for index, value in enumerate(failures):
        failure = PHASE0.require_exact_keys(value, FAILURE_KEYS, f"failure {index}")
        batch_id = _string(failure["batch_id"], f"failure {index}.batch_id")
        if batch_id in failure_by_batch:
            _error("duplicate_batch_id", "failures batch id가 중복됐습니다")
        batch = failed_by_id.get(batch_id)
        if batch is None:
            _error("batch_mismatch", "failures에 decisions에 없는 failed batch가 있습니다")
        sequence = _integer(failure["sequence"], f"failure {index}.sequence", minimum=1)
        attempt_count = _integer(failure["attempt_count"], f"failure {index}.attempt_count", minimum=1)
        if attempt_count != batch["attempt_count"] or sequence != batch["sequence"]:
            _error("batch_mismatch", "failures attempt/sequence이 decisions와 다릅니다")
        if failure["plan_ids"] != batch["plan_ids"]:
            _error("batch_mismatch", "failures plan_ids가 decisions와 다릅니다")
        plan_ids = failure["plan_ids"]
        if not isinstance(plan_ids, list) or not plan_ids or any(not isinstance(plan_id, str) or not plan_id.strip() for plan_id in plan_ids):
            _error("invalid_field", "failures plan_ids가 잘못됐습니다")
        if len(plan_ids) != len(set(plan_ids)):
            _error("duplicate_plan_id", "failures plan id가 잘못됐습니다")
        if any(plan_id not in candidate_set for plan_id in plan_ids):
            _error("noncandidate_result", "failures에 비대상 plan이 있습니다")
        if failed_plan_ids & set(plan_ids):
            _error("duplicate_plan_id", "failures plan id가 중복됐습니다")
        failed_plan_ids.update(plan_ids)
        if failure["max_attempts"] != MAX_ATTEMPTS:
            _error("binding_mismatch", "failures max_attempts가 policy와 다릅니다")
        failure_type = failure["failure_type"]
        if failure_type not in FAILURE_TYPES:
            _error("invalid_field", "failure_type이 잘못됐습니다")
        outcome = failure["outcome"]
        if outcome not in {"failed", "rejected", "unknown"}:
            _error("invalid_field", "failure outcome이 잘못됐습니다")
        allowed_outcomes = {"failed"} if failure_type in RETRYABLE_FAILURE_TYPES else {"rejected"} if failure_type in REJECTION_FAILURE_TYPES else {"unknown"}
        if outcome not in allowed_outcomes:
            _error("invalid_field", "failure type과 outcome 조합이 허용되지 않습니다")
        if outcome == "unknown" and batch["status"] != "failed":
            _error("batch_mismatch", "unknown failure outcome은 failed batch여야 합니다")
        if outcome == "failed" and batch["status"] != "failed":
            _error("batch_mismatch", "failure outcome과 decision batch status가 다릅니다")
        if outcome == "rejected" and batch["status"] != "rejected":
            _error("batch_mismatch", "failure outcome과 decision batch status가 다릅니다")
        if failure["status"] != "human_review_required":
            _error("invalid_status", "failure는 human_review_required여야 합니다")
        error_code = _string(failure["error_code"], f"failure {index}.error_code")
        if len(error_code) > 128:
            _error("invalid_field", "failure error_code가 너무 깁니다")
        failure_by_batch[batch_id] = failure
        outcomes.append(failure["outcome"])
    if set(failure_by_batch) != set(failed_by_id):
        _error("batch_mismatch", "실패 batch가 failures artifact와 일치하지 않습니다")
    if not failures and document["status"] != "none":
        _error("status_mismatch", "failure가 없으면 failures status는 none이어야 합니다")
    if failures:
        expected_status = "failed" if set(outcomes) == {"failed"} else "rejected" if set(outcomes) == {"rejected"} else "partial"
        if document["status"] != expected_status:
            _error("status_mismatch", "failures status가 outcome과 다릅니다")
    return {
        "document": document,
        "sha256": PHASE0.sha256_file(path),
        "failures_by_batch": failure_by_batch,
        "failed_plan_ids": failed_plan_ids,
        "failure_by_plan": {plan_id: failure for failure in failures for plan_id in failure["plan_ids"]},
    }


def _validate_nullable_timestamp(value: Any, label: str) -> None:
    if value is not None:
        PHASE0.parse_timestamp(value, label)


def _validate_measurement(value: Any, label: str) -> dict[str, Any]:
    measurement = PHASE0.require_exact_keys(value, MEASUREMENT_KEYS, label)
    for field in ("started_at", "finished_at"):
        _validate_nullable_timestamp(measurement[field], f"{label}.{field}")
    for field in ("duration_ms", "input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"):
        if measurement[field] is not None:
            _integer(measurement[field], f"{label}.{field}", minimum=0)
    if measurement["started_at"] is not None and measurement["finished_at"] is not None:
        if PHASE0.parse_timestamp(measurement["finished_at"], f"{label}.finished_at") < PHASE0.parse_timestamp(measurement["started_at"], f"{label}.started_at"):
            _error("telemetry_invalid", f"{label} finished_at이 started_at보다 빠릅니다")
    return measurement


def _validate_telemetry(path: Path, frozen: Mapping[str, Any], decisions: Mapping[str, Any], failures: Mapping[str, Any]) -> dict[str, Any]:
    document = PHASE0.require_exact_keys(PHASE0.load_json(path), TELEMETRY_KEYS, "telemetry artifact")
    if document["schema_version"] != TELEMETRY_SCHEMA or document["producer"] != "order-plan-screening-worker" or document["consumer"] != "observability-and-merge":
        _error("provenance_mismatch", "telemetry artifact provenance가 다릅니다")
    _validate_execution(document, frozen["document"], "telemetry")
    if document["status"] not in {"complete", "partial", "not_measured"}:
        _error("invalid_status", "telemetry status가 잘못됐습니다")
    _validate_created_at(document, "telemetry")
    execution = _validate_measurement(document["execution"], "telemetry.execution")
    expected_batch_ids = set(decisions["batches_by_id"])
    telemetry_batches = document["batches"]
    if not isinstance(telemetry_batches, list) or len(telemetry_batches) != len(expected_batch_ids):
        _error("batch_mismatch", "telemetry batch 집합이 decisions와 다릅니다")
    telemetry_by_id: dict[str, dict[str, Any]] = {}
    any_measurement = any(value is not None for value in execution.values())
    for index, value in enumerate(telemetry_batches):
        batch = PHASE0.require_exact_keys(value, TELEMETRY_BATCH_KEYS, f"telemetry batch {index}")
        batch_id = _string(batch["batch_id"], f"telemetry batch {index}.batch_id")
        if batch_id in telemetry_by_id:
            _error("duplicate_batch_id", "telemetry batch id가 중복됐습니다")
        source_batch = decisions["batches_by_id"].get(batch_id)
        if source_batch is None:
            _error("batch_mismatch", "telemetry에 decisions에 없는 batch가 있습니다")
        if batch["sequence"] != source_batch["sequence"]:
            _error("batch_mismatch", "telemetry sequence가 decisions와 다릅니다")
        failure = failures["failures_by_batch"].get(batch_id)
        expected_status = "success" if source_batch["status"] == "success" else "unknown" if failure and failure["outcome"] == "unknown" else source_batch["status"]
        if batch["status"] != expected_status:
            _error("batch_mismatch", "telemetry batch status가 decisions/failures와 다릅니다")
        attempts = batch["attempts"]
        if not isinstance(attempts, list) or len(attempts) != source_batch["attempt_count"]:
            _error("batch_mismatch", "telemetry attempt 수가 decisions와 다릅니다")
        seen_attempts: set[int] = set()
        attempt_statuses: list[str] = []
        for attempt_index, value in enumerate(attempts):
            attempt = PHASE0.require_exact_keys(value, ATTEMPT_KEYS, f"telemetry batch {index} attempt {attempt_index}")
            attempt_no = _integer(attempt["attempt_no"], f"telemetry batch {index}.attempt_no", minimum=1)
            if attempt_no != attempt_index + 1 or attempt_no in seen_attempts:
                _error("batch_mismatch", "telemetry attempt 번호가 연속·유일하지 않습니다")
            seen_attempts.add(attempt_no)
            if attempt["status"] not in {"success", "failed", "rejected"}:
                _error("invalid_status", "telemetry attempt status가 잘못됐습니다")
            _validate_nullable_timestamp(attempt["started_at"], f"telemetry attempt {attempt_no}.started_at")
            _validate_nullable_timestamp(attempt["finished_at"], f"telemetry attempt {attempt_no}.finished_at")
            if attempt["started_at"] is not None and attempt["finished_at"] is not None and PHASE0.parse_timestamp(attempt["finished_at"], "telemetry.finished_at") < PHASE0.parse_timestamp(attempt["started_at"], "telemetry.started_at"):
                _error("telemetry_invalid", "telemetry attempt finished_at이 started_at보다 빠릅니다")
            measurement = _validate_measurement(attempt["measurement"], f"telemetry batch {index} attempt {attempt_no}.measurement")
            any_measurement = any_measurement or any(value is not None for value in measurement.values())
            attempt_statuses.append(attempt["status"])
        if "rejected" in attempt_statuses[:-1]:
            _error("batch_mismatch", "rejected attempt 뒤에 telemetry attempt가 있습니다")
        if source_batch["status"] == "success":
            if attempt_statuses[-1] != "success" or any(status == "success" for status in attempt_statuses[:-1]):
                _error("batch_mismatch", "성공 batch telemetry attempt 순서가 잘못됐습니다")
        else:
            expected_final_status = "failed" if failure and failure["outcome"] == "unknown" else source_batch["status"]
            if attempt_statuses[-1] != expected_final_status:
                _error("batch_mismatch", "실패 batch telemetry 최종 attempt status가 terminal class와 다릅니다")
            if any(status == "success" for status in attempt_statuses):
                _error("batch_mismatch", "실패 batch telemetry에 성공 attempt가 있습니다")
        telemetry_by_id[batch_id] = batch
    if set(telemetry_by_id) != expected_batch_ids:
        _error("batch_mismatch", "telemetry가 모든 decisions batch를 포함하지 않습니다")
    if document["status"] == "not_measured" and any_measurement:
        _error("telemetry_invalid", "측정값이 있는데 telemetry가 not_measured입니다")
    if document["status"] != "not_measured" and not any_measurement:
        _error("telemetry_invalid", "측정값이 없는데 telemetry가 측정 상태입니다")
    return {"document": document, "batches_by_id": telemetry_by_id}


def _result_item(
    plan_id: str,
    ranking_item: Mapping[str, Any],
    decision_item: Mapping[str, Any] | None,
    failure: Mapping[str, Any] | None,
) -> dict[str, Any]:
    stage1_status = ranking_item["stage1_status"]
    if stage1_status in {"filtered_out", "failed", "rejected"}:
        stage2_status = "not_attempted"
        relevance = score = reason = batch_id = attempt_no = failure_code = None
    elif decision_item is not None:
        stage2_status = "success"
        relevance = decision_item["relevance"]
        score = decision_item["score"]
        reason = decision_item["reason"]
        batch_id = decision_item["batch_id"]
        attempt_no = decision_item["attempt_no"]
        failure_code = None
    elif failure is not None:
        stage2_status = failure["outcome"]
        relevance = score = reason = batch_id = attempt_no = None
        failure_code = failure["error_code"]
    elif stage1_status == "selected":
        stage2_status = "not_attempted"
        relevance = score = reason = batch_id = attempt_no = failure_code = None
    else:
        _error("missing_result", "candidate 결과가 누락됐습니다")
    return {
        "plan_id": plan_id,
        "stage1_status": stage1_status,
        "stage1_rank": ranking_item["rank"],
        "stage1_score": ranking_item["score"],
        "nearest_capability": ranking_item["nearest_capability"],
        "stage2_status": stage2_status,
        "qwen_relevance": relevance,
        "qwen_score": score,
        "qwen_reason": reason,
        "batch_id": batch_id,
        "attempt_no": attempt_no,
        "failure_code": failure_code,
    }


def _write_no_overwrite(path: Path, value: Any) -> None:
    RANKER._write_no_overwrite(path, value)


def build_order_plan_screening_results(
    input_path: Path,
    ranking_path: Path,
    decisions_path: Path,
    failures_path: Path,
    telemetry_path: Path,
    output_path: Path,
    *,
    policy_path: Path | None = None,
    binding_path: Path | None = None,
) -> dict[str, Any]:
    """Validate all Phase 1 artifacts and build the full-population result."""

    frozen = RANKER.validate_frozen_input(Path(input_path))
    fixed = RANKER.validate_fixed_references(frozen, policy_path=policy_path, binding_path=binding_path)
    ranking = _validate_ranking(Path(ranking_path), frozen)
    decisions = _validate_decisions(Path(decisions_path), frozen, ranking, fixed["binding"]["stage2_binding"])
    failures = _validate_failures(Path(failures_path), frozen, decisions, ranking)
    telemetry = _validate_telemetry(Path(telemetry_path), frozen, decisions, failures)
    for item in decisions["items_by_id"].values():
        batch = decisions["batches_by_id"][item["batch_id"]]
        final_attempt = telemetry["batches_by_id"][item["batch_id"]]["attempts"][-1]
        if item["attempt_no"] != batch["attempt_count"] or final_attempt["status"] != "success" or item["attempt_no"] != final_attempt["attempt_no"]:
            _error("batch_mismatch", "decisions item attempt_no가 최종 성공 attempt와 다릅니다")

    result_items: list[dict[str, Any]] = []
    for input_item in frozen["items"]:
        plan_id = input_item["plan_id"]
        ranking_item = ranking["items_by_id"][plan_id]
        result_items.append(
            _result_item(
                plan_id,
                ranking_item,
                decisions["items_by_id"].get(plan_id),
                failures["failure_by_plan"].get(plan_id),
            )
        )

    relevant = sum(item["qwen_relevance"] == "relevant" for item in result_items)
    not_relevant = sum(item["qwen_relevance"] == "not_relevant" for item in result_items)
    uncertain = sum(item["qwen_relevance"] == "uncertain" for item in result_items)
    stage2_failed = sum(item["stage2_status"] == "failed" for item in result_items)
    stage2_rejected = sum(item["stage2_status"] == "rejected" for item in result_items)
    stage2_unknown = sum(item["stage2_status"] == "unknown" for item in result_items)
    stage1_selected = sum(item["stage1_status"] == "selected" for item in result_items)
    stage1_filtered = sum(item["stage1_status"] == "filtered_out" for item in result_items)
    stage1_failed = sum(item["stage1_status"] in {"failed", "rejected"} for item in result_items)
    successful_candidates = relevant + not_relevant + uncertain
    incomplete = stage1_failed + stage2_failed + stage2_rejected + stage2_unknown
    if incomplete == 0 and successful_candidates == stage1_selected:
        status = "성공"
    elif stage1_failed == 0 and stage1_selected > 0 and stage2_rejected == stage1_selected:
        status = "거부됨"
    elif successful_candidates > 0:
        status = "부분 성공"
    else:
        status = "실패"
    counts = {
        "population": len(result_items),
        "stage1_selected": stage1_selected,
        "stage1_filtered_out": stage1_filtered,
        "stage1_failed": stage1_failed,
        "stage2_relevant": relevant,
        "stage2_not_relevant": not_relevant,
        "stage2_uncertain": uncertain,
        "stage2_failed": stage2_failed,
        "stage2_rejected": stage2_rejected,
        "human_review_count": relevant + uncertain + stage2_failed + stage2_rejected + stage2_unknown + stage1_failed,
    }
    artifact = {
        "schema_version": RESULT_SCHEMA,
        "producer": "order-plan-screening-merge",
        "consumer": "postgres-loader-and-review-api",
        "execution_id": frozen["document"]["execution_id"],
        "source_run_id": frozen["document"]["source_run_id"],
        "input_artifact_sha256": frozen["sha256"],
        "policy_version": frozen["policy"]["version"],
        "policy_sha256": frozen["policy"]["sha256"],
        "status": status,
        "partial_artifact": status != "성공",
        "counts": counts,
        "items": result_items,
        "created_at": frozen["document"]["created_at"],
    }
    PHASE0.require_exact_keys(artifact, RESULT_KEYS, "screening result")
    PHASE0.require_exact_keys(counts, RESULT_COUNTS_KEYS, "screening result counts")
    for index, item in enumerate(result_items):
        PHASE0.require_exact_keys(item, RESULT_ITEM_KEYS, f"screening result item {index}")
    _write_no_overwrite(Path(output_path), artifact)
    return artifact


merge_order_plan_screening_results = build_order_plan_screening_results
build_results = build_order_plan_screening_results


def _cli_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path, Path, Path]:
    positional = list(args.paths)
    named = [args.input_option, args.ranking_option, args.decisions_option, args.failures_option, args.telemetry_option, args.output_option]
    if positional:
        if len(positional) == 5 and args.output_option is not None and all(value is None for value in named[:5]):
            return tuple(Path(value) for value in (*positional, args.output_option))  # type: ignore[return-value]
        if len(positional) != 6 or any(value is not None for value in named):
            _error("invalid_arguments", "merge 입력 경로가 부족하거나 중복됐습니다")
        return tuple(Path(value) for value in positional)  # type: ignore[return-value]
    if any(value is None for value in named):
        _error("invalid_arguments", "input, ranking, decisions, failures, telemetry, output 경로가 필요합니다")
    return tuple(Path(value) for value in named)  # type: ignore[return-value]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--input", dest="input_option", type=Path)
    parser.add_argument("--ranking", dest="ranking_option", type=Path)
    parser.add_argument("--decisions", dest="decisions_option", type=Path)
    parser.add_argument("--failures", dest="failures_option", type=Path)
    parser.add_argument("--telemetry", dest="telemetry_option", type=Path)
    parser.add_argument("--output", dest="output_option", type=Path)
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument("--binding", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        paths = _cli_paths(args)
        build_order_plan_screening_results(
            *paths,
            policy_path=args.policy,
            binding_path=args.binding,
        )
    except ContractError as exc:
        print(f"error={exc.code}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
