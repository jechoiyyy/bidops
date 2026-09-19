#!/usr/bin/env python3
"""Produce the deterministic Phase 1 BM25 ranking artifact.

The module deliberately owns only the file-contract boundary. It does not
know about the collection runtime, a model client, a database, or the web
application.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


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


PHASE0 = _load_phase0_helpers()
ContractError = PHASE0.ContractError

INPUT_SCHEMA = "bidops.order-plan-screening-input.v1"
RANKING_SCHEMA = "bidops.order-plan-screening-ranking.v1"
COLLECTED_SCHEMA = "bidops.collected-order-plans.v1"
BM25_SCHEMA = "bidops.order-plan-bm25.v1"
BM25_METHOD_VERSION = "bm25-char-title-capability-v1"
TOP_K = 300
K1 = 1.2
B = 0.75
NGRAM_MIN = 2
NGRAM_MAX = 5

INPUT_KEYS = {
    "schema_version",
    "producer",
    "consumer",
    "execution_id",
    "source_run_id",
    "source_artifact",
    "population_count",
    "population_sha256",
    "policy",
    "stage1_binding",
    "stage2_binding",
    "items",
    "status",
    "created_at",
}
SOURCE_ARTIFACT_KEYS = {"name", "schema_version", "sha256"}
BINDING_KEYS = {"version", "sha256"}
INPUT_ITEM_KEYS = {"plan_id", "title"}

POLICY_KEYS = {
    "schema_version",
    "producer",
    "consumer",
    "policy_version",
    "policy_status",
    "decision_scope",
    "created_at",
    "stage1",
    "stage2",
    "audit_sample",
    "execution",
    "feedback",
    "quality_gate",
    "bindings",
    "activation",
}
STAGE1_KEYS = {"method", "config", "top_k", "population"}
STAGE1_CONFIG_KEYS = {
    "path",
    "schema_version",
    "sha256",
    "method_version",
    "normalization",
    "tokenization",
    "scoring",
    "tie_break",
}
NORMALIZATION_KEYS = {"unicode", "case", "whitespace", "fields"}
TOKENIZATION_KEYS = {"type", "min_n", "max_n", "boundary"}
SCORING_KEYS = {
    "k1",
    "b",
    "query_term_frequency",
    "capability_aggregation",
    "idf_corpus",
}
STAGE2_KEYS = {
    "provider",
    "model_name",
    "model_digest",
    "generation_config",
    "prompt",
    "company_profile",
    "payload",
    "batching",
    "response",
    "retry",
}
BINDING_DOCUMENT_KEYS = {
    "schema_version",
    "producer",
    "consumer",
    "binding_version",
    "status",
    "created_at",
    "policy",
    "selection_decision",
    "source_input",
    "selection_evidence_population",
    "stage1_binding",
    "stage2_binding",
    "selection_evidence",
    "review_inputs",
    "gold",
    "external_transport",
    "compatibility",
    "activation",
}

CAPABILITIES_KEYS = {
    "schema_version",
    "approval_status",
    "profile_version",
    "summary_sha256",
    "approved_by",
    "approved_at",
    "capabilities",
}
CAPABILITY_KEYS = {"id", "summary"}


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


def _hash(value: Any, label: str) -> str:
    if not PHASE0.is_sha256(value):
        _error("invalid_hash", f"{label} SHA-256이 잘못됐습니다")
    return value


def _finite_number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _error("invalid_field", f"{label} 숫자 형식이 잘못됐습니다")
    if minimum is not None and value < minimum:
        _error("invalid_field", f"{label} 값이 범위를 벗어났습니다")
    return float(value)


def _validate_binding_ref(value: Any, label: str) -> dict[str, Any]:
    binding = PHASE0.require_exact_keys(value, BINDING_KEYS, label)
    _string(binding["version"], f"{label}.version")
    _hash(binding["sha256"], f"{label}.sha256")
    return binding


def validate_frozen_input(input_value: Path | Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return the frozen input plus its file digest.

    ``input_value`` may be an already decoded mapping for callers that have
    already verified the file. File-producing entry points pass a ``Path`` so
    duplicate JSON keys and the byte-level input digest are checked here.
    """

    input_path: Path | None
    if isinstance(input_value, Path):
        input_path = input_value
        document = PHASE0.load_json(input_path)
        input_sha256 = PHASE0.sha256_file(input_path)
    else:
        input_path = None
        document = input_value
        input_sha256 = None

    document = PHASE0.require_exact_keys(document, INPUT_KEYS, "screening input")
    if document["schema_version"] != INPUT_SCHEMA:
        _error("schema_mismatch", "screening input schema가 다릅니다")
    if document["producer"] != "order-plan-screening-orchestrator" or document["consumer"] != "order-plan-screening-worker":
        _error("provenance_mismatch", "screening input provenance가 다릅니다")
    _string(document["execution_id"], "input.execution_id")
    _string(document["source_run_id"], "input.source_run_id")
    source = PHASE0.require_exact_keys(document["source_artifact"], SOURCE_ARTIFACT_KEYS, "input.source_artifact")
    _string(source["name"], "input.source_artifact.name")
    if source["name"].startswith(("/", "\\")) or "\x00" in source["name"]:
        _error("unsafe_path", "input.source_artifact.name이 안전하지 않습니다")
    if source["schema_version"] != COLLECTED_SCHEMA:
        _error("schema_mismatch", "input source artifact schema가 다릅니다")
    _hash(source["sha256"], "input.source_artifact.sha256")
    population_count = _integer(document["population_count"], "input.population_count", minimum=1)
    population_sha256 = _hash(document["population_sha256"], "input.population_sha256")
    policy = _validate_binding_ref(document["policy"], "input.policy")
    stage1_binding = _validate_binding_ref(document["stage1_binding"], "input.stage1_binding")
    stage2_binding = _validate_binding_ref(document["stage2_binding"], "input.stage2_binding")
    if document["status"] != "frozen":
        _error("invalid_status", "screening input은 frozen 상태여야 합니다")
    PHASE0.parse_timestamp(document["created_at"], "input.created_at")

    items = document["items"]
    if not isinstance(items, list) or not items:
        _error("invalid_population", "screening input items가 비어 있습니다")
    ids: set[str] = set()
    for index, item in enumerate(items):
        row = PHASE0.require_exact_keys(item, INPUT_ITEM_KEYS, f"screening input item {index}")
        plan_id = _string(row["plan_id"], f"input item {index}.plan_id")
        _string(row["title"], f"input item {index}.title")
        if plan_id in ids:
            _error("duplicate_plan_id", "screening input plan id가 중복됐습니다")
        ids.add(plan_id)
    if population_count != len(items):
        _error("count_mismatch", "screening input population_count가 items와 다릅니다")
    if population_sha256 != PHASE0.digest_json(items):
        _error("hash_mismatch", "screening input population hash가 items와 다릅니다")

    return {
        "path": input_path,
        "document": document,
        "sha256": input_sha256,
        "items": items,
        "items_by_id": {item["plan_id"]: item for item in items},
        "policy": policy,
        "stage1_binding": stage1_binding,
        "stage2_binding": stage2_binding,
    }


def _validate_policy_document(document: Any) -> dict[str, Any]:
    """Check the fixed portions of the Phase 0 policy file."""

    policy = PHASE0.require_exact_keys(document, POLICY_KEYS, "screening policy")
    if policy["schema_version"] != "bidops.order-plan-screening-policy.v1" or policy["producer"] != "phase0-contracts" or policy["consumer"] != "phase1-screening-pipeline":
        _error("provenance_mismatch", "screening policy provenance가 다릅니다")
    _string(policy["policy_version"], "policy.policy_version")
    if policy["policy_status"] not in {"draft", "activation_candidate", "active", "retired"}:
        _error("invalid_policy_status", "screening policy status가 잘못됐습니다")
    if policy["decision_scope"] != "c2_order_plan_first_pass":
        _error("policy_binding_mismatch", "screening policy scope가 다릅니다")
    PHASE0.parse_timestamp(policy["created_at"], "policy.created_at")

    stage1 = PHASE0.require_exact_keys(policy["stage1"], STAGE1_KEYS, "policy.stage1")
    if stage1["method"] != "bm25" or stage1["top_k"] != TOP_K:
        _error("policy_binding_mismatch", "BM25 top_k 또는 method가 다릅니다")
    config = PHASE0.require_exact_keys(stage1["config"], STAGE1_CONFIG_KEYS, "policy.stage1.config")
    _hash(config["sha256"], "policy.stage1.config.sha256")
    if config["schema_version"] != BM25_SCHEMA:
        _error("policy_binding_mismatch", "BM25 config schema가 다릅니다")
    normalization = PHASE0.require_exact_keys(config["normalization"], NORMALIZATION_KEYS, "policy BM25 normalization")
    if normalization != {"unicode": "NFKC", "case": "casefold", "whitespace": "collapse_runs_and_trim", "fields": ["title"]}:
        _error("policy_binding_mismatch", "BM25 normalization이 다릅니다")
    tokenization = PHASE0.require_exact_keys(config["tokenization"], TOKENIZATION_KEYS, "policy BM25 tokenization")
    if tokenization != {"type": "character_ngram", "min_n": NGRAM_MIN, "max_n": NGRAM_MAX, "boundary": "within_field"}:
        _error("policy_binding_mismatch", "BM25 tokenization이 다릅니다")
    scoring = PHASE0.require_exact_keys(config["scoring"], SCORING_KEYS, "policy BM25 scoring")
    if scoring != {"k1": K1, "b": B, "query_term_frequency": "binary", "capability_aggregation": "max_bm25", "idf_corpus": "full_population_titles"}:
        _error("policy_binding_mismatch", "BM25 scoring이 다릅니다")
    if config["tie_break"] != ["score_desc", "order_plan_unty_no_asc"]:
        _error("policy_binding_mismatch", "BM25 tie-break가 다릅니다")
    stage2 = PHASE0.require_exact_keys(policy["stage2"], STAGE2_KEYS, "policy.stage2")
    if (stage2["provider"], stage2["model_name"]) not in {("approved_private_vllm", "qwen3.8-27B"), ("approved_private_ollama", "qwen3.8:27b")}:
        _error("policy_binding_mismatch", "Qwen stage2 binding이 다릅니다")
    if stage2["provider"] == "approved_private_ollama" and (
        policy["policy_status"] != "activation_candidate"
        or policy.get("quality_gate", {}).get("status") != "not_measured"
        or policy.get("quality_gate", {}).get("activation_eligible") is not False
        or policy.get("activation", {}).get("enabled") is not False
        or policy.get("activation", {}).get("status") != "blocked"
        or policy.get("activation", {}).get("approved_by") is not None
        or policy.get("activation", {}).get("approved_at") is not None
    ):
        _error("policy_binding_mismatch", "Ollama 결과는 미측정 참조 정책에만 저장합니다")
    _hash(stage2["model_digest"], "policy.stage2.model_digest")
    generation_config = PHASE0.require_exact_keys(stage2["generation_config"], {"version", "sha256"}, "policy.stage2.generation_config")
    _string(generation_config["version"], "policy.stage2.generation_config.version")
    _hash(generation_config["sha256"], "policy.stage2.generation_config.sha256")
    prompt = PHASE0.require_exact_keys(stage2["prompt"], {"version", "sha256"}, "policy.stage2.prompt")
    _string(prompt["version"], "policy.stage2.prompt.version")
    _hash(prompt["sha256"], "policy.stage2.prompt.sha256")
    profile = PHASE0.require_exact_keys(stage2["company_profile"], {"version", "sha256", "allowed_fields"}, "policy.stage2.company_profile")
    _string(profile["version"], "policy.stage2.company_profile.version")
    _hash(profile["sha256"], "policy.stage2.company_profile.sha256")
    if profile["allowed_fields"] != ["profile_version", "capabilities"]:
        _error("policy_binding_mismatch", "policy company profile allowlist가 다릅니다")
    payload = PHASE0.require_exact_keys(stage2["payload"], {"allowed_plan_fields", "allowed_company_fields", "forbidden_fields"}, "policy.stage2.payload")
    if payload["allowed_plan_fields"] != ["title"] or payload["allowed_company_fields"] != ["profile_version", "capabilities"]:
        _error("policy_binding_mismatch", "policy payload allowlist가 다릅니다")
    batching = PHASE0.require_exact_keys(stage2["batching"], {"mode", "size", "last_batch", "concurrency", "order"}, "policy.stage2.batching")
    if batching != {"mode": "fixed_rank_contiguous", "size": 25, "last_batch": "shorter_allowed", "concurrency": 1, "order": "stage1_rank_ascending"}:
        _error("policy_binding_mismatch", "policy batching이 다릅니다")
    return policy


BINDING_STATUSES = frozenset({"blocked", "activation_candidate", "approved"})


def _validate_binding_document(document: Any) -> dict[str, Any]:
    """Check the fixed portions of an optional immutable Phase 0 binding."""

    binding = PHASE0.require_exact_keys(document, BINDING_DOCUMENT_KEYS, "phase0 binding")
    if binding["schema_version"] != "bidops.order-plan-screening-phase0-binding.v1" or binding["producer"] != "phase0-contracts" or binding["consumer"] != "phase1-screening-pipeline" or binding["status"] not in BINDING_STATUSES:
        _error("binding_invalid", "phase0 binding provenance/status가 다릅니다")
    transport = binding["external_transport"]
    # A blocked binding that allows execution is contradictory (ADR-0060); the
    # service and worker reject the same combination.
    if binding["status"] == "blocked" and isinstance(transport, dict) and transport.get("execution_allowed") is True:
        _error("binding_invalid", "blocked binding이 실행을 허용합니다")
    _string(binding["binding_version"], "binding.binding_version")
    PHASE0.parse_timestamp(binding["created_at"], "binding.created_at")
    stage1 = PHASE0.require_exact_keys(binding["stage1_binding"], {"method", "path", "schema_version", "sha256", "top_k", "tie_break"}, "binding.stage1_binding")
    _hash(stage1["sha256"], "binding.stage1_binding.sha256")
    if stage1["method"] != "bm25" or stage1["schema_version"] != BM25_SCHEMA or stage1["top_k"] != TOP_K or stage1["tie_break"] != ["score_desc", "order_plan_unty_no_asc"]:
        _error("binding_invalid", "phase0 stage1 binding이 고정값과 다릅니다")
    stage2 = PHASE0.require_exact_keys(binding["stage2_binding"], {"provider", "model_name", "model_digest", "generation_config_version", "generation_config_sha256", "prompt_version", "prompt_sha256", "company_profile_version", "company_profile_sha256", "payload_fields", "company_payload_fields", "batch_size", "max_attempts", "concurrency"}, "binding.stage2_binding")
    if (stage2["provider"], stage2["model_name"]) not in {("approved_private_vllm", "qwen3.8-27B"), ("approved_private_ollama", "qwen3.8:27b")}:
        _error("binding_invalid", "phase0 stage2 model binding이 다릅니다")
    for field in ("model_digest", "generation_config_sha256", "prompt_sha256", "company_profile_sha256"):
        _hash(stage2[field], f"binding.stage2_binding.{field}")
    for field in ("generation_config_version", "prompt_version", "company_profile_version"):
        _string(stage2[field], f"binding.stage2_binding.{field}")
    if stage2["payload_fields"] != ["title"] or stage2["company_payload_fields"] != ["profile_version", "capabilities"] or stage2["batch_size"] != 25 or stage2["max_attempts"] != 2 or stage2["concurrency"] != 1:
        _error("binding_invalid", "phase0 stage2 execution binding이 다릅니다")
    return binding


def validate_fixed_references(
    frozen_input: dict[str, Any],
    *,
    policy_path: Path | None = None,
    binding_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the required approved policy and Phase 0 binding references."""

    result: dict[str, Any] = {"policy": None, "binding": None}
    if policy_path is None or binding_path is None:
        _error("missing_reference", "승인된 policy와 Phase 0 binding 경로가 필요합니다")

    policy_path = Path(policy_path)
    binding_path = Path(binding_path)
    policy_actual = PHASE0.sha256_file(policy_path)
    if policy_actual != frozen_input["policy"]["sha256"]:
        _error("hash_mismatch", "policy file digest가 input binding과 다릅니다")
    policy = _validate_policy_document(PHASE0.load_json(policy_path))
    if policy["policy_version"] != frozen_input["policy"]["version"]:
        _error("policy_binding_mismatch", "policy version이 input binding과 다릅니다")

    binding_actual = PHASE0.sha256_file(binding_path)
    accepted_hashes = {
        frozen_input["stage1_binding"]["sha256"],
        frozen_input["stage2_binding"]["sha256"],
    }
    if binding_actual not in accepted_hashes:
        _error("hash_mismatch", "binding file digest가 input binding과 다릅니다")
    binding = _validate_binding_document(PHASE0.load_json(binding_path))
    policy_ref = PHASE0.require_exact_keys(binding["policy"], {"path", "schema_version", "policy_version", "sha256", "policy_status"}, "binding.policy")
    if policy_ref["schema_version"] != "bidops.order-plan-screening-policy.v1" or policy_ref["policy_version"] != policy["policy_version"] or policy_ref["sha256"] != policy_actual or policy_ref["policy_status"] != policy["policy_status"]:
        _error("binding_mismatch", "binding policy ref가 policy와 다릅니다")
    if binding["stage1_binding"]["sha256"] != frozen_input["stage1_binding"]["sha256"]:
        _error("binding_mismatch", "binding stage1 ref가 input과 다릅니다")
    policy_stage1 = policy["stage1"]
    binding_stage1 = binding["stage1_binding"]
    if (
        policy_stage1["method"] != binding_stage1["method"]
        or policy_stage1["config"]["sha256"] != binding_stage1["sha256"]
        or policy_stage1["config"]["method_version"] != BM25_METHOD_VERSION
    ):
        _error("binding_mismatch", "policy와 binding stage1 ref가 다릅니다")

    stage2 = binding["stage2_binding"]
    policy_stage2 = policy["stage2"]
    expected_stage2 = {
        "provider": stage2["provider"],
        "model_name": stage2["model_name"],
        "model_digest": stage2["model_digest"],
        "generation_config": {"version": stage2["generation_config_version"], "sha256": stage2["generation_config_sha256"]},
        "prompt": {"version": stage2["prompt_version"], "sha256": stage2["prompt_sha256"]},
        "company_profile": {"version": stage2["company_profile_version"], "sha256": stage2["company_profile_sha256"], "allowed_fields": ["profile_version", "capabilities"]},
    }
    for field in ("provider", "model_name", "model_digest", "generation_config", "prompt", "company_profile"):
        if policy_stage2[field] != expected_stage2[field]:
            _error("binding_mismatch", "policy와 binding stage2 ref가 다릅니다")
    policy_bindings = PHASE0.require_exact_keys(policy["bindings"], {"bm25_config_sha256", "prompt_sha256", "company_profile_sha256", "model_digest", "generation_config_sha256"}, "policy.bindings")
    expected_policy_bindings = {
        "bm25_config_sha256": binding["stage1_binding"]["sha256"],
        "prompt_sha256": stage2["prompt_sha256"],
        "company_profile_sha256": stage2["company_profile_sha256"],
        "model_digest": stage2["model_digest"],
        "generation_config_sha256": stage2["generation_config_sha256"],
    }
    if policy_bindings != expected_policy_bindings:
        _error("binding_mismatch", "policy digest binding이 Phase 0 binding과 다릅니다")
    review_inputs = PHASE0.require_exact_keys(binding["review_inputs"], {"manifest_path", "manifest_schema_version", "manifest_sha256", "active_company_capabilities_path", "active_company_capabilities_sha256", "active_prompt_path", "active_prompt_sha256"}, "binding.review_inputs")
    if review_inputs["active_company_capabilities_sha256"] != stage2["company_profile_sha256"] or review_inputs["active_prompt_sha256"] != stage2["prompt_sha256"]:
        _error("binding_mismatch", "binding approved review-input ref가 stage2와 다릅니다")
    result["policy"] = policy
    result["binding"] = binding
    return result


def normalize_title(value: str) -> str:
    """Apply the fixed NFKC, casefold, and whitespace policy."""

    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def character_ngrams(value: str, *, minimum: int = NGRAM_MIN, maximum: int = NGRAM_MAX) -> Counter[str]:
    """Return within-field character n-gram frequencies."""

    normalized = normalize_title(value)
    return Counter(
        normalized[index : index + size]
        for size in range(minimum, maximum + 1)
        for index in range(0, max(0, len(normalized) - size + 1))
    )


def _capability_rows(value: Any) -> list[dict[str, str]]:
    document: dict[str, Any] | None = None
    if isinstance(value, list):
        raw_capabilities = value
    else:
        document = PHASE0.require_exact_keys(value, CAPABILITIES_KEYS, "company capabilities")
        if document["schema_version"] != "bidops.order-plan-capabilities.v1" or document["approval_status"] != "approved":
            _error("capabilities_not_approved", "회사 역량은 승인 상태여야 합니다")
        _string(document["profile_version"], "capabilities.profile_version")
        _hash(document["summary_sha256"], "capabilities.summary_sha256")
        _string(document["approved_by"], "capabilities.approved_by")
        PHASE0.parse_timestamp(document["approved_at"], "capabilities.approved_at")
        raw_capabilities = document["capabilities"]
        if not isinstance(raw_capabilities, list):
            _error("invalid_capabilities", "회사 역량 목록이 배열이 아닙니다")

    if not raw_capabilities:
        _error("invalid_capabilities", "회사 역량 목록이 비어 있습니다")
    capabilities: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, value in enumerate(raw_capabilities):
        row = PHASE0.require_exact_keys(value, CAPABILITY_KEYS, f"company capability {index}")
        capability_id = _string(row["id"], f"company capability {index}.id")
        summary = _string(row["summary"], f"company capability {index}.summary")
        if capability_id in seen:
            _error("duplicate_capability_id", "회사 역량 id가 중복됐습니다")
        seen.add(capability_id)
        capabilities.append({"id": capability_id, "summary": summary})

    if document is not None:
        projection = {"profile_version": document["profile_version"], "capabilities": capabilities}
        if PHASE0.digest_json(projection) != document["summary_sha256"]:
            _error("hash_mismatch", "회사 역량 summary hash가 본문과 다릅니다")
    return capabilities


def load_capabilities(capabilities_value: Path | Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    if isinstance(capabilities_value, Path):
        return _capability_rows(PHASE0.load_json(capabilities_value))
    return _capability_rows(list(capabilities_value))


def bm25_scores(items: Iterable[Mapping[str, str]], capabilities: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    """Score every title against every capability and take the maximum."""

    rows = list(items)
    documents = [character_ngrams(row["title"]) for row in rows]
    document_lengths = [sum(terms.values()) for terms in documents]
    population_count = len(rows)
    average_length = sum(document_lengths) / population_count if population_count else 0.0
    document_frequency: Counter[str] = Counter()
    for terms in documents:
        document_frequency.update(terms.keys())
    idf = {
        term: math.log(1.0 + (population_count - frequency + 0.5) / (frequency + 0.5))
        for term, frequency in document_frequency.items()
    }
    capability_queries = [
        (capability["id"], set(character_ngrams(capability["summary"])))
        for capability in capabilities
    ]

    scored: list[dict[str, Any]] = []
    for row, terms, document_length in zip(rows, documents, document_lengths):
        best_score = 0.0
        best_capability: str | None = None
        normalization = 1.0 - B
        if average_length:
            normalization += B * document_length / average_length
        for capability_id, query_terms in capability_queries:
            score = 0.0
            for term in sorted(query_terms):
                frequency = terms.get(term, 0)
                if frequency == 0:
                    continue
                denominator = frequency + K1 * normalization
                score += idf[term] * (frequency * (K1 + 1.0)) / denominator
            if best_capability is None or score > best_score or (score == best_score and capability_id < best_capability):
                best_score = score
                best_capability = capability_id
        scored.append(
            {
                "plan_id": row["plan_id"],
                "score": best_score,
                "nearest_capability": best_capability,
            }
        )
    return scored


def _write_no_overwrite(path: Path, value: Any) -> None:
    data = PHASE0.canonical_json_bytes(value)
    try:
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        _error("output_exists", "출력 파일을 덮어쓸 수 없습니다")
    except OSError as exc:
        raise ContractError("output_unavailable", "출력 파일을 만들 수 없습니다") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        try:
            path.unlink()
        except OSError:
            pass
        raise ContractError("output_write_failed", "출력 파일을 쓸 수 없습니다") from exc


def rank_order_plans(
    input_path: Path,
    capabilities_path: Path,
    output_path: Path,
    *,
    policy_path: Path | None = None,
    binding_path: Path | None = None,
) -> dict[str, Any]:
    """Build and exclusively create a ranking artifact."""

    input_path = Path(input_path)
    output_path = Path(output_path)
    frozen = validate_frozen_input(input_path)
    fixed = validate_fixed_references(frozen, policy_path=policy_path, binding_path=binding_path)
    if not isinstance(capabilities_path, Path):
        _error("missing_reference", "승인된 company capabilities 파일 경로가 필요합니다")
    capabilities_path = Path(capabilities_path)
    approved_stage2 = fixed["binding"]["stage2_binding"]
    if PHASE0.sha256_file(capabilities_path) != approved_stage2["company_profile_sha256"]:
        _error("hash_mismatch", "company capabilities file digest가 승인된 profile binding과 다릅니다")
    capabilities_document = PHASE0.load_json(capabilities_path)
    capabilities = _capability_rows(capabilities_document)
    if capabilities_document["profile_version"] != approved_stage2["company_profile_version"]:
        _error("binding_mismatch", "company capabilities profile version이 승인된 binding과 다릅니다")
    scored = bm25_scores(frozen["items"], capabilities)
    ranked = sorted(scored, key=lambda row: (-row["score"], row["plan_id"]))
    selected_limit = min(TOP_K, len(ranked))
    output_items: list[dict[str, Any]] = []
    for rank, row in enumerate(ranked, start=1):
        output_items.append(
            {
                "plan_id": row["plan_id"],
                "rank": rank,
                "score": row["score"],
                "nearest_capability": row["nearest_capability"],
                "stage1_status": "selected" if rank <= selected_limit else "filtered_out",
            }
        )
    artifact = {
        "schema_version": RANKING_SCHEMA,
        "producer": "order-plan-screening-bm25",
        "consumer": "order-plan-screening-merge",
        "execution_id": frozen["document"]["execution_id"],
        "source_run_id": frozen["document"]["source_run_id"],
        "input_artifact_sha256": frozen["sha256"],
        "policy_version": frozen["policy"]["version"],
        "policy_sha256": frozen["policy"]["sha256"],
        "status": "성공",
        "population_count": len(output_items),
        "selected_count": selected_limit,
        "filtered_out_count": len(output_items) - selected_limit,
        "items": output_items,
        "created_at": frozen["document"]["created_at"],
    }
    _write_no_overwrite(output_path, artifact)
    return artifact


build_ranking_artifact = rank_order_plans
rank_order_plans_bm25 = rank_order_plans


def _cli_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    positional = list(args.paths)
    input_path = args.input_option
    capabilities_path = args.capabilities_option
    output_path = args.output_option
    if len(positional) == 3:
        if any(value is not None for value in (input_path, capabilities_path, output_path)):
            _error("invalid_arguments", "입력 경로를 중복 지정할 수 없습니다")
        input_path, capabilities_path, output_path = map(Path, positional)
    elif len(positional) == 2 and input_path is None and capabilities_path is not None and output_path is None:
        input_path, output_path = map(Path, positional)
    elif len(positional) == 2 and input_path is None and capabilities_path is None and output_path is not None:
        input_path, capabilities_path = map(Path, positional)
    elif len(positional) == 1 and input_path is None and capabilities_path is not None and output_path is not None:
        input_path = Path(positional[0])
    elif positional:
        _error("invalid_arguments", "ranker 입력 경로가 부족하거나 중복됐습니다")
    if input_path is None or capabilities_path is None or output_path is None:
        _error("invalid_arguments", "input, capabilities, output 경로가 필요합니다")
    return Path(input_path), Path(capabilities_path), Path(output_path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--input", dest="input_option", type=Path)
    parser.add_argument("--capabilities", dest="capabilities_option", type=Path)
    parser.add_argument("--output", dest="output_option", type=Path)
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument("--binding", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        input_path, capabilities_path, output_path = _cli_paths(args)
        rank_order_plans(
            input_path,
            capabilities_path,
            output_path,
            policy_path=args.policy,
            binding_path=args.binding,
        )
    except ContractError as exc:
        print(f"error={exc.code}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
