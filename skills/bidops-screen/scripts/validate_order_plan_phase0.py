#!/usr/bin/env python3
"""Validate the frozen C-2 Phase 0 contract without exposing protected bodies.

This validator is deliberately read-only.  It verifies the current repository
binding, the immutable collection input (including raw-record hashes), the
approved review-input manifest, historical selection evidence, and the
partially adjudicated C-1 gold artifact.  A valid but not yet activatable
contract exits successfully with ``valid_but_blocked``; it never promotes a
draft label, activates a policy, or calls a model endpoint.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_RELATIVE = "skills/bidops-screen/contracts"

POLICY_SCHEMA = "bidops.order-plan-screening-policy.v1"
BINDING_SCHEMA = "bidops.order-plan-screening-phase0-binding.v1"
COLLECTED_SCHEMA = "bidops.collected-order-plans.v1"
POPULATION_SCHEMA = "bidops.order-plan-population.v1"
SELECTION_SCHEMA = "bidops.order-plan-screening-selection-decision.v1"
REVIEW_INPUT_SCHEMA = "bidops.order-plan-review-inputs-manifest.v1"
GOLD_SCHEMA = "bidops.order-plan-gold-adjudication-manifest.v1"
RAW_PAGE_SCHEMA = "bidops.collected-order-plans-raw-page.v1"

POLICY_RELATIVE = "experiments/order-plan-screening/config/order-plan-screening-policy.v1.json"
BINDING_RELATIVE = "experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v1.json"
BM25_RELATIVE = "experiments/order-plan-screening/config/bm25.json"
REVIEW_INPUTS_RELATIVE = "experiments/order-plan-screening/review-inputs"
SOURCE_RELATIVE = "data/runs/order-plans-20260827-20260830-retry1/collected-order-plans.json"
POPULATION_RELATIVE = "data/experiments/order-plan-screening/20260827-20260830-qwen-direct-v3/population.json"
SELECTION_RELATIVE = "data/experiments/order-plan-screening/20260827-20260830-bm25-qwen300-v3/selection-decision.json"
GOLD_MANIFEST_RELATIVE = "data/experiments/order-plan-screening/20260827-20260830-gold-adjudicated-v2/review/manifest.json"

# These are public provenance digests, not secrets.  Updating any one of them
# requires a new binding version or an explicit contract update; silently
# accepting a changed historical artifact would defeat the Phase 0 gate.
EXPECTED = {
    "contract_index_sha256": "7cc1ace43dad42e0cfb59cfef101f99caee05d4358ced54df30fee4db7c1e5a1",
    "policy_sha256": "3010c7bfb569e062fc8e94b052df0325caccad7e23a34cf1e15dad6a6358e196",
    "binding_sha256": "e0367de6155e362539a867d3b6820e204ba1238a2a613c6b973780c8348c86ef",
    "bm25_sha256": "e026b2bdd2f99ddc09ae17bc83b1cd9cc40ef413f3b72372a35db32918d696da",
    "generation_config_sha256": "1fd2f511a0b1c99f5a57125ebd9e1d67314d98202d42327394daa540abd27754",
    "review_manifest_sha256": "a478a18a873f332d0de45b13b4445315db83a855c9fa698ceb9150a9b98203b8",
    "company_profile_sha256": "8f60dfece1934bdf857cd7e57d0fdd1860d01871131d98c3f2e8f9d71f271eae",
    "prompt_sha256": "639f7332e1120a41b2e8d8306126f121ae1ed37068a81b1687aff9ce66ab9d12",
    "source_sha256": "d608e1ad71dd03467278ad06a8c3290b5a5db47a118b3f1fcda5c7e90d122faf",
    "raw_manifest_sha256": "f0afcbb549844d5628bed6726bb141a9d0acc7ad987e9b5ab996f84c62903402",
    "population_file_sha256": "503a7794d37bbb406c2d2069b23ef3cc42bb8f1d163c88764e50fee0bba549bd",
    "population_sha256": "7846e7ff51002dac613f85cc1a3e8a358430c9519ed96c6501e8e41c9f3d1c5a",
    "selection_sha256": "e242077be204fddb6213bb4ba96f24ec51a8acac3cc5fb95654a191be9c1aa44",
    "cascade_sha256": "06fd0cdf122f0ffec6cf6480e50b6dd50d98d019acdc40fe1a14c01f3dfb9a7a",
    "qwen_result_sha256": "a150cf845271b591d4144d76b9d7f9931fe87389eca894fc6e6e2fa0611f44e4",
    "scoring_sha256": "36040cbf68796129fd8d67ebc817c9f41b3ac2b667ba4d78eaffe8d422ae11a3",
    "accepted_misses_sha256": "ba8aea251e39e0b83cf2ecb85c220fa62213d72635471a6579a21ba7a741d13c",
    "gold_manifest_sha256": "6089b8421540a39352af9fa06b082d72d67ee5868d6c843051bae802ebc1b6e5",
    "gold_artifact_sha256": "07d1986ab9d8abc7ef8ce12466e65998044928127682b9b7f743b08f4aacc4cd",
    "gold_remaining_sha256": "2f1dc92be41029f8a5a4e5c078fa3dc44c626ce706fc863e59c36544b81d65a8",
}

CONTRACT_CATALOG = {
    "bidops.order-plan-screening-policy.v1.json": (
        "bidops.order-plan-screening-policy.v1",
        "phase0-contracts",
        "phase1-screening-pipeline",
        "d6b66094d4273c8159594de5ba1dd188e0058d38391b21dd268839623a73e3ab",
        "new_v1_only",
        "immutable_after_activation",
    ),
    "bidops.order-plan-screening-phase0-binding.v1.json": (
        "bidops.order-plan-screening-phase0-binding.v1",
        "phase0-contracts",
        "phase1-screening-pipeline",
        "3fb670bba9cbf24bcd15e857bc2e4192f8b969b61db609483a6ab6305b12253a",
        "new_v1_only",
        "immutable_after_creation",
    ),
    "bidops.order-plan-screening-input.v1.json": (
        "bidops.order-plan-screening-input.v1",
        "order-plan-screening-orchestrator",
        "order-plan-screening-worker",
        "aad7e23829d68cad0d93225619427d914a3c6144ebe30f90086f8bddd13ced71",
        "new_v1_only",
        "immutable_after_creation",
    ),
    "bidops.order-plan-screening-ranking.v1.json": (
        "bidops.order-plan-screening-ranking.v1",
        "order-plan-screening-bm25",
        "order-plan-screening-merge",
        "514e9b6ac744c9b1b783b3fdee66c7f9a7e1a938f0e426b6324ffa69d560a3f5",
        "new_v1_only",
        "immutable_after_creation",
    ),
    "bidops.order-plan-screening-decisions.v1.json": (
        "bidops.order-plan-screening-decisions.v1",
        "order-plan-screening-qwen-worker",
        "order-plan-screening-merge",
        "bd8eb46ed2b4139a0d83a19481938a91ed1e215c803804daf36b3b40235db036",
        "new_v1_only",
        "immutable_after_creation",
    ),
    "bidops.order-plan-screening-failures.v1.json": (
        "bidops.order-plan-screening-failures.v1",
        "order-plan-screening-worker",
        "order-plan-screening-review-and-merge",
        "a11d7719f9100d0428bcf9f97e330ce806b4bf74c40804c00bbc7cada82fc5b5",
        "new_v1_only",
        "immutable_after_creation",
    ),
    "bidops.order-plan-screening-telemetry.v1.json": (
        "bidops.order-plan-screening-telemetry.v1",
        "order-plan-screening-worker",
        "observability-and-merge",
        "69d994853ebdec3e81b07abd61c3182ccc7c2ce523d1f39c0e84b8ce97fe98ae",
        "new_v1_only",
        "immutable_after_creation",
    ),
    "bidops.order-plan-screening-result.v1.json": (
        "bidops.order-plan-screening-result.v1",
        "order-plan-screening-merge",
        "postgres-loader-and-review-api",
        "6be7121f6b9a321ee3ff5b7ea9acaf34d6222c379dd9d6f46350e880e273e1ff",
        "new_v1_only",
        "immutable_after_creation",
    ),
    "bidops.order-plan-screening-feedback.v1.json": (
        "bidops.order-plan-screening-feedback.v1",
        "human-review-api",
        "postgres-review-history",
        "e3d839ca4a46a3c6023c0c78f7596dbf328ae9964d08e20cab19e90806376c09",
        "append_only_revision",
        "immutable_after_creation",
    ),
}

ALLOWED_DIVISIONS = ("기술용역", "일반용역")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

COLLECTED_KEYS = {
    "schema_version",
    "generated_at",
    "source_window",
    "metadata",
    "counts",
    "warnings",
    "order_plans",
}
COLLECTED_ITEM_KEYS = {
    "order_plan_unty_no",
    "title",
    "agency_code",
    "agency_name",
    "supervising_agency_name",
    "business_division",
    "business_division_code",
    "service_type",
    "service_type_code",
    "budget_amount",
    "contract_amount",
    "planned_order_year",
    "planned_order_month",
    "procurement_method",
    "contract_method",
    "sw_business_status",
    "published_at",
    "changed_at",
    "bid_ntice_no_list",
    "notice_posted",
    "rcrit_rgst_no",
    "source_url",
    "first_discovered_at",
    "last_discovered_at",
    "source_sha256",
    "unknown_fields",
    "raw_source",
}
RAW_PAGE_KEYS = {
    "schema_version",
    "endpoint_id",
    "query",
    "page_no",
    "request_attempts",
    "collected_at",
    "payload_sha256",
    "payload",
}
POPULATION_ITEM_KEYS = {
    "plan_id",
    "title",
    "agency_code",
    "agency_name",
    "supervising_agency_name",
    "business_division",
    "business_division_code",
    "service_type",
    "service_type_code",
    "budget_amount",
    "contract_amount",
    "planned_order_month",
    "procurement_method",
    "contract_method",
    "sw_business_status",
    "official_url",
    "published_at",
    "changed_at",
    "first_discovered_at",
    "last_discovered_at",
    "unknown_fields",
    "source",
}
GOLD_HEADER = [
    "draft_order",
    "plan_id",
    "title",
    "agency_name",
    "budget_amount",
    "planned_order_month",
    "published_at",
    "source_sha256",
    "draft_relevance",
    "draft_priority",
    "draft_reason",
    "draft_basis",
    "confirmation_role",
    "human_relevance",
    "human_priority",
    "human_reason",
    "reviewer",
    "reviewed_at",
    "effective_relevance",
    "effective_priority",
    "effective_reason",
    "label_source",
]
DRAFT_HEADER = GOLD_HEADER[:18]
ADJUDICATION_HEADER = [
    "plan_id",
    "draft_relevance",
    "draft_priority",
    "human_relevance",
    "human_priority",
    "adjudication",
    "human_reason",
    "reviewer",
    "reviewed_at",
]
MISS_HEADER = [
    "plan_id",
    "title",
    "effective_relevance",
    "effective_priority",
    "label_source",
    "miss_stage",
    "bm25_rank",
    "accepted_for_c2",
    "accepted_at",
    "decision_note",
]


class ContractError(RuntimeError):
    """A stable, safe-to-display contract validation failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _reject_constant(value: str) -> None:
    raise ContractError("non_finite_number", "JSON에 유한하지 않은 숫자가 있습니다")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate_json_key", "JSON 키가 중복됐습니다")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(
            raw,
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("invalid_json", "JSON 산출물을 읽을 수 없습니다") from exc


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid_json_value", "JSON canonical digest를 계산할 수 없습니다") from exc


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except (OSError, ValueError) as exc:
        raise ContractError("file_read_failed", "참조 파일을 읽을 수 없습니다") from exc
    return digest.hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("invalid_contract", f"{label}은 JSON object여야 합니다")
    return value


def require_exact_keys(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    obj = require_object(value, label)
    missing = sorted(keys - set(obj))
    extras = sorted(set(obj) - keys)
    if missing:
        raise ContractError("missing_field", f"{label} 필드가 누락됐습니다")
    if extras:
        raise ContractError("unexpected_field", f"{label} 허용 밖 필드가 있습니다")
    return obj


def require_nonblank(value: Any, code: str, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(code, message)
    return value


def parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("invalid_timestamp", f"{label} timestamp가 필요합니다")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractError("invalid_timestamp", f"{label} timestamp 형식이 잘못됐습니다") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError("invalid_timestamp", f"{label}에 timezone이 없습니다")
    return parsed


def _relative_parts(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ContractError("unsafe_path", f"{label}은 안전한 상대 경로여야 합니다")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ContractError("unsafe_path", f"{label}은 안전한 상대 경로여야 합니다")
    return relative.parts


def _resolve_directory(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ContractError("file_unavailable", f"{label} 디렉터리를 읽을 수 없습니다") from exc
    if not resolved.is_dir():
        raise ContractError("file_unavailable", f"{label} 디렉터리를 읽을 수 없습니다")
    return resolved


def resolve_repo_file(repo_root: Path, value: Any, label: str) -> Path:
    parts = _relative_parts(value, label)
    root = _resolve_directory(repo_root, "repository root")
    candidate = root.joinpath(*parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ContractError("unsafe_path", f"{label}이 저장소 경계를 벗어납니다") from exc
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ContractError("unsafe_path", f"{label}에 symlink를 사용할 수 없습니다")
    if not candidate.is_file():
        raise ContractError("file_unavailable", f"{label} 파일을 읽을 수 없습니다")
    return candidate


def resolve_child_file(parent: Path, value: Any, label: str) -> Path:
    parts = _relative_parts(value, label)
    root = _resolve_directory(parent, "file parent")
    candidate = root.joinpath(*parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ContractError("unsafe_path", f"{label}이 경계를 벗어납니다") from exc
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ContractError("unsafe_path", f"{label}에 symlink를 사용할 수 없습니다")
    if not candidate.is_file():
        raise ContractError("file_unavailable", f"{label} 파일을 읽을 수 없습니다")
    return candidate


def _assert_hash(actual: str, expected: Any, label: str) -> None:
    if not is_sha256(expected) or actual != expected:
        raise ContractError("hash_mismatch", f"{label} SHA-256이 다릅니다")


def _assert_string_or_null(value: Any, label: str, *, nonblank: bool = False) -> None:
    if value is not None and not isinstance(value, str):
        raise ContractError("invalid_field", f"{label} 타입이 잘못됐습니다")
    if nonblank and (not isinstance(value, str) or not value.strip()):
        raise ContractError("invalid_field", f"{label}은 비어 있을 수 없습니다")


def _assert_nonnegative_amount(value: Any, label: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ContractError("invalid_field", f"{label} 금액이 잘못됐습니다")


def validate_schema_catalog(repo_root: Path = REPO_ROOT) -> int:
    index_path = resolve_repo_file(repo_root, f"{CONTRACT_RELATIVE}/contract-index.v1.json", "contract-index")
    _assert_hash(sha256_file(index_path), EXPECTED["contract_index_sha256"], "contract-index")
    contract_dir = index_path.parent
    index = require_exact_keys(
        load_json(index_path),
        {
            "schema_version",
            "producer",
            "consumer",
            "contract_status",
            "contracts",
            "rest_contract",
            "db_contract",
        },
        "contract-index",
    )
    if index["schema_version"] != "bidops.order-plan-screening-contract-index.v1":
        raise ContractError("schema_mismatch", "contract index schema가 다릅니다")
    if (
        index["producer"] != "phase0-contracts"
        or index["consumer"] != "phase1-to-phase5-implementations"
        or index["rest_contract"] != "docs/contracts.md#c-2-phase-0-fixed-contract"
        or index["db_contract"] != "docs/tracking/decisions/0038-order-plan-c2-phase0-contracts.md"
    ):
        raise ContractError("contract_index_mismatch", "계약 index provenance 또는 참조가 다릅니다")
    if index["contract_status"] != "fixed_for_implementation":
        raise ContractError("contract_not_fixed", "계약 index가 구현 고정 상태가 아닙니다")
    entries = index["contracts"]
    if not isinstance(entries, list) or len(entries) != len(CONTRACT_CATALOG):
        raise ContractError("invalid_contract", "계약 index contracts 수가 고정값과 다릅니다")
    actual_schema_files = {
        path.name for path in contract_dir.glob("*.json") if path.name != "contract-index.v1.json"
    }
    if actual_schema_files != set(CONTRACT_CATALOG):
        raise ContractError("invalid_contract", "계약 schema 파일 집합이 고정값과 다릅니다")
    seen: set[str] = set()
    for entry in entries:
        entry_obj = require_object(entry, "contract-index entry")
        filename = entry_obj.get("file")
        expected = CONTRACT_CATALOG.get(filename) if isinstance(filename, str) else None
        if expected is None:
            raise ContractError("invalid_contract", "계약 schema 파일이 고정 catalog 밖에 있습니다")
        schema_version, producer, consumer, schema_sha256, compatibility, immutability_key = expected
        row = require_exact_keys(
            entry_obj,
            {
                "file",
                "schema_version",
                "producer",
                "consumer",
                "sha256",
                "compatibility",
                immutability_key,
            },
            "contract-index entry",
        )
        if not isinstance(filename, str) or filename in seen:
            raise ContractError("invalid_contract", "계약 schema 파일이 중복됐습니다")
        if row != {
            "file": filename,
            "schema_version": schema_version,
            "producer": producer,
            "consumer": consumer,
            "sha256": schema_sha256,
            "compatibility": compatibility,
            immutability_key: True,
        }:
            raise ContractError("contract_index_mismatch", "계약 index entry가 고정값과 다릅니다")
        if row[immutability_key] is not True:
            raise ContractError("invalid_contract", "계약 불변성 표식이 필요합니다")
        seen.add(filename)
        schema_path = resolve_child_file(contract_dir, filename, "contract schema")
        _assert_hash(sha256_file(schema_path), schema_sha256, "contract schema")
        schema = require_object(load_json(schema_path), "contract schema")
        for field in ("$schema", "$id", "title", "x-bidops-producer", "x-bidops-consumer", "type", "required", "properties"):
            if field not in schema:
                raise ContractError("invalid_contract_schema", "계약 schema metadata가 누락됐습니다")
        if schema["type"] != "object" or not isinstance(schema["required"], list):
            raise ContractError("invalid_contract_schema", "계약 schema 구조가 잘못됐습니다")
        if not {"schema_version", "producer", "consumer"}.issubset(set(schema["required"])):
            raise ContractError("invalid_contract_schema", "계약 schema provenance 필드가 필요합니다")
        props = require_object(schema["properties"], "contract schema properties")
        for field in ("schema_version", "producer", "consumer"):
            if field not in props:
                raise ContractError("invalid_contract_schema", "계약 schema provenance property가 필요합니다")
            require_object(props[field], f"contract schema {field} property")
        if props["schema_version"].get("const") != row["schema_version"]:
            raise ContractError("schema_mismatch", "계약 index와 schema version이 다릅니다")
        if props["producer"].get("const") != row["producer"] or props["consumer"].get("const") != row["consumer"]:
            raise ContractError("schema_mismatch", "계약 index와 schema provenance가 다릅니다")
    if len(seen) != len(entries):
        raise ContractError("invalid_contract", "계약 index가 중복됐습니다")
    return len(entries)


def _validate_capabilities(document: Any, *, require_approved: bool = True) -> tuple[dict[str, Any], str]:
    config = require_exact_keys(
        document,
        {
            "schema_version",
            "approval_status",
            "profile_version",
            "summary_sha256",
            "approved_by",
            "approved_at",
            "capabilities",
        },
        "company capabilities",
    )
    if config["schema_version"] != "bidops.order-plan-capabilities.v1":
        raise ContractError("schema_mismatch", "회사 역량 schema가 다릅니다")
    if config["approval_status"] not in {"approved", "pending"}:
        raise ContractError("invalid_capabilities", "회사 역량 approval status가 잘못됐습니다")
    if require_approved and config["approval_status"] != "approved":
        raise ContractError("capabilities_not_approved", "active 회사 역량은 approved여야 합니다")
    require_nonblank(config["profile_version"], "invalid_capabilities", "회사 profile version이 필요합니다")
    if config["approval_status"] == "approved":
        require_nonblank(config["approved_by"], "invalid_capabilities", "회사 역량 승인 표식이 필요합니다")
        parse_timestamp(config["approved_at"], "company-capabilities.approved_at")
    elif config["approved_by"] is not None or config["approved_at"] is not None:
        raise ContractError("invalid_capabilities", "pending 회사 역량에는 승인 표식이 있을 수 없습니다")
    if not is_sha256(config["summary_sha256"]):
        raise ContractError("invalid_hash", "회사 역량 summary hash가 잘못됐습니다")
    capabilities = config["capabilities"]
    if not isinstance(capabilities, list) or not capabilities:
        raise ContractError("invalid_capabilities", "승인 회사 역량이 비어 있습니다")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in capabilities:
        row = require_exact_keys(item, {"id", "summary"}, "company capability")
        capability_id = require_nonblank(row["id"], "invalid_capabilities", "회사 역량 id가 비어 있습니다")
        summary = require_nonblank(row["summary"], "invalid_capabilities", "회사 역량 summary가 비어 있습니다")
        if capability_id in seen:
            raise ContractError("invalid_capabilities", "회사 역량 id가 중복됐습니다")
        seen.add(capability_id)
        normalized.append({"id": capability_id, "summary": summary})
    projection = {"profile_version": config["profile_version"], "capabilities": normalized}
    if digest_json(projection) != config["summary_sha256"]:
        raise ContractError("hash_mismatch", "회사 역량 summary hash가 본문과 다릅니다")
    return config, digest_json(projection)


def validate_review_inputs(repo_root: Path) -> dict[str, Any]:
    root = resolve_repo_file(repo_root, f"{REVIEW_INPUTS_RELATIVE}/manifest.json", "review-inputs manifest")
    manifest = require_exact_keys(
        load_json(root),
        {
            "schema_version",
            "updated_at",
            "active_company_capabilities",
            "active_prompt",
            "documents",
        },
        "review-inputs manifest",
    )
    if manifest["schema_version"] != REVIEW_INPUT_SCHEMA:
        raise ContractError("schema_mismatch", "review-inputs manifest schema가 다릅니다")
    parse_timestamp(manifest["updated_at"], "review-inputs.updated_at")
    documents = manifest["documents"]
    if not isinstance(documents, list) or not documents:
        raise ContractError("invalid_review_inputs", "review-inputs documents가 비어 있습니다")
    indexed: dict[str, dict[str, Any]] = {}
    for item in documents:
        document = require_exact_keys(
            item,
            {
                "kind",
                "path",
                "version",
                "status",
                "execution_allowed",
                "sha256",
                "source_path",
            },
            "review-input document",
        )
        path_value = require_nonblank(document["path"], "invalid_review_inputs", "review-input path가 필요합니다")
        if path_value in indexed:
            raise ContractError("invalid_review_inputs", "review-input path가 중복됐습니다")
        if document["kind"] not in {"company_capabilities", "prompt"}:
            raise ContractError("invalid_review_inputs", "review-input kind이 잘못됐습니다")
        if document["status"] not in {"approved", "draft", "retired"}:
            raise ContractError("invalid_review_inputs", "review-input status가 잘못됐습니다")
        if not isinstance(document["execution_allowed"], bool):
            raise ContractError("invalid_review_inputs", "review-input execution_allowed가 boolean이어야 합니다")
        if document["execution_allowed"] and document["status"] != "approved":
            raise ContractError("invalid_review_inputs", "승인되지 않은 review-input은 실행 허용될 수 없습니다")
        if not is_sha256(document["sha256"]):
            raise ContractError("invalid_hash", "review-input hash가 잘못됐습니다")
        source_path = document["source_path"]
        _relative_parts(source_path, "review-input source_path")
        actual_path = resolve_child_file(root.parent, path_value, "review-input document")
        _assert_hash(sha256_file(actual_path), document["sha256"], "review-input")
        if document["kind"] == "company_capabilities":
            capability_doc = load_json(actual_path)
            _validate_capabilities(capability_doc, require_approved=document["status"] == "approved")
        else:
            try:
                prompt = actual_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise ContractError("review_input_unavailable", "prompt를 읽을 수 없습니다") from exc
            if not prompt.strip() or "\x00" in prompt:
                raise ContractError("invalid_review_inputs", "prompt가 비었거나 잘못됐습니다")
        indexed[path_value] = document

    active_capabilities = require_nonblank(
        manifest["active_company_capabilities"],
        "invalid_review_inputs",
        "active company capabilities path가 필요합니다",
    )
    active_prompt = require_nonblank(
        manifest["active_prompt"],
        "invalid_review_inputs",
        "active prompt path가 필요합니다",
    )
    for path_value, kind in ((active_capabilities, "company_capabilities"), (active_prompt, "prompt")):
        active = indexed.get(path_value)
        if (
            active is None
            or active["kind"] != kind
            or active["status"] != "approved"
            or active["execution_allowed"] is not True
        ):
            raise ContractError("active_review_input_invalid", "active review-input이 승인·실행 허용 상태가 아닙니다")
    manifest_hash = sha256_file(root)
    _assert_hash(manifest_hash, EXPECTED["review_manifest_sha256"], "review-inputs manifest")
    _assert_hash(indexed[active_capabilities]["sha256"], EXPECTED["company_profile_sha256"], "active company profile")
    _assert_hash(indexed[active_prompt]["sha256"], EXPECTED["prompt_sha256"], "active prompt")
    return {
        "manifest_path": root,
        "manifest_sha256": manifest_hash,
        "active_company_capabilities": active_capabilities,
        "active_company_capabilities_sha256": indexed[active_capabilities]["sha256"],
        "active_prompt": active_prompt,
        "active_prompt_sha256": indexed[active_prompt]["sha256"],
        "active_company_profile_version": indexed[active_capabilities]["version"],
        "active_prompt_version": indexed[active_prompt]["version"],
    }


def _validate_raw_pages(
    source_run_dir: Path,
    raw_paths: set[str],
    *,
    expected_page_count: int,
    expected_request_count: int,
    source_window: dict[str, str],
    order_month_scope: dict[str, str],
) -> tuple[dict[str, tuple[str, str]], str]:
    raw_dir = source_run_dir / "raw"
    if not raw_dir.is_dir():
        raise ContractError("raw_input_unavailable", "불변 raw 입력 디렉터리가 없습니다")
    if expected_page_count < 1 or expected_request_count != expected_page_count:
        raise ContractError("invalid_collection", "raw page/request count가 잘못됐습니다")
    expected_raw_paths = {f"raw/page-{page_no:05d}.json" for page_no in range(1, expected_page_count + 1)}
    actual_raw_paths = {f"raw/{path.name}" for path in raw_dir.iterdir()}
    if actual_raw_paths != expected_raw_paths or raw_paths != expected_raw_paths:
        raise ContractError("raw_population_mismatch", "raw page 집합이 수집 manifest와 다릅니다")
    try:
        from_date = date.fromisoformat(source_window["from"])
        to_date = date.fromisoformat(source_window["to"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("invalid_source_window", "raw query 기준 source window가 잘못됐습니다") from exc
    if to_date <= from_date:
        raise ContractError("invalid_source_window", "raw query 기준 source window가 잘못됐습니다")
    query_end = datetime.combine(to_date, datetime.min.time()) - timedelta(minutes=1)
    index: dict[str, tuple[str, str]] = {}
    manifest: list[dict[str, str]] = []
    for raw_value in sorted(expected_raw_paths):
        raw_path = resolve_child_file(source_run_dir, raw_value, "raw_source")
        page = require_exact_keys(load_json(raw_path), RAW_PAGE_KEYS, "raw page")
        if page["schema_version"] != RAW_PAGE_SCHEMA:
            raise ContractError("schema_mismatch", "raw page schema가 다릅니다")
        if page["endpoint_id"] != "g2b_order_plan_service_pps_search_v1":
            raise ContractError("source_binding_mismatch", "raw page endpoint binding이 다릅니다")
        if isinstance(page["page_no"], bool) or not isinstance(page["page_no"], int) or page["page_no"] < 1:
            raise ContractError("invalid_raw_page", "raw page 번호가 잘못됐습니다")
        expected_query = {
            "pageNo": str(page["page_no"]),
            "numOfRows": "500",
            "type": "json",
            "orderBgnYm": order_month_scope["from"],
            "orderEndYm": order_month_scope["to"],
            "inqryBgnDt": f"{from_date:%Y%m%d}0000",
            "inqryEndDt": query_end.strftime("%Y%m%d%H%M"),
        }
        query = require_exact_keys(
            page["query"],
            set(expected_query),
            "raw page query",
        )
        if query != expected_query or page["page_no"] != int(query["pageNo"]):
            raise ContractError("source_binding_mismatch", "raw page query가 source window와 다릅니다")
        if isinstance(page["request_attempts"], bool) or not isinstance(page["request_attempts"], int) or page["request_attempts"] < 1:
            raise ContractError("invalid_raw_page", "raw page retry 횟수가 잘못됐습니다")
        parse_timestamp(page["collected_at"], "raw page collected_at")
        if not is_sha256(page["payload_sha256"]):
            raise ContractError("invalid_hash", "raw page payload hash가 잘못됐습니다")
        payload = require_object(page["payload"], "raw page payload")
        _assert_hash(digest_json(payload), page["payload_sha256"], "raw page payload")
        try:
            rows = payload["response"]["body"]["items"]
        except (KeyError, TypeError) as exc:
            raise ContractError("invalid_raw_page", "raw page record 배열이 없습니다") from exc
        if not isinstance(rows, list):
            raise ContractError("invalid_raw_page", "raw page record 배열이 아닙니다")
        manifest.append({"path": raw_value, "sha256": sha256_file(raw_path)})
        for raw_record in rows:
            record = require_object(raw_record, "raw record")
            plan_id = record.get("orderPlanUntyNo")
            if not isinstance(plan_id, str) or not plan_id.strip():
                raise ContractError("missing_plan_id", "raw record plan id가 없습니다")
            if plan_id in index:
                raise ContractError("duplicate_plan_id", "raw 입력 plan id가 중복됐습니다")
            index[plan_id] = (digest_json(record), raw_value)
    return index, digest_json(manifest)


def validate_collected_artifact(repo_root: Path, path: Path | None = None) -> dict[str, Any]:
    artifact_path = path or resolve_repo_file(repo_root, SOURCE_RELATIVE, "collected input")
    document = require_exact_keys(load_json(artifact_path), COLLECTED_KEYS, "collected input")
    if document["schema_version"] != COLLECTED_SCHEMA:
        raise ContractError("schema_mismatch", "collected input schema가 다릅니다")
    parse_timestamp(document["generated_at"], "collected.generated_at")
    window = require_exact_keys(document["source_window"], {"from", "to", "timezone"}, "source_window")
    if not all(isinstance(window[key], str) and DATE_RE.fullmatch(window[key]) for key in ("from", "to")):
        raise ContractError("invalid_source_window", "source window 날짜가 잘못됐습니다")
    if window["from"] > window["to"] or window["timezone"] != "Asia/Seoul":
        raise ContractError("invalid_source_window", "source window이 잘못됐습니다")
    metadata = require_exact_keys(
        document["metadata"],
        {"endpoint_id", "endpoint", "scope", "business_division_field", "business_divisions", "order_month_scope", "collection"},
        "collected.metadata",
    )
    if metadata["endpoint_id"] != "g2b_order_plan_service_pps_search_v1":
        raise ContractError("source_binding_mismatch", "수집 endpoint binding이 다릅니다")
    require_nonblank(metadata["endpoint"], "invalid_source", "수집 endpoint가 필요합니다")
    require_nonblank(metadata["scope"], "invalid_source", "수집 scope가 필요합니다")
    if metadata["business_division_field"] != "bsnsDivNm" or metadata["business_divisions"] != list(ALLOWED_DIVISIONS):
        raise ContractError("source_binding_mismatch", "업무구분 allowlist가 다릅니다")
    order_month_scope = require_exact_keys(metadata["order_month_scope"], {"from", "to"}, "order_month_scope")
    if order_month_scope != {"from": "200412", "to": "999912"}:
        raise ContractError("source_binding_mismatch", "order month scope가 다릅니다")
    collection = require_exact_keys(metadata["collection"], {"page_count", "request_count", "complete"}, "collection")
    for field in ("page_count", "request_count"):
        if isinstance(collection[field], bool) or not isinstance(collection[field], int) or collection[field] < 1:
            raise ContractError("invalid_collection", "collection count가 잘못됐습니다")
    if collection["complete"] is not True:
        raise ContractError("source_incomplete", "완료된 수집 회차만 사용할 수 있습니다")
    if document["warnings"] != []:
        raise ContractError("source_warning", "수집 warning이 있는 회차는 사용할 수 없습니다")
    counts = require_exact_keys(
        document["counts"],
        {"total", "order_plans", "in_scope", "source_total", "source_records", "excluded_out_of_scope", "excluded_business_divisions", "page_count", "request_count"},
        "collected.counts",
    )
    for value in counts.values():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContractError("invalid_collection", "collected count가 잘못됐습니다")
    plans = document["order_plans"]
    if not isinstance(plans, list) or not plans:
        raise ContractError("invalid_collection", "order_plans가 비어 있습니다")
    if counts["order_plans"] != len(plans) or counts["total"] != len(plans) or counts["in_scope"] != len(plans) or counts["source_records"] != len(plans):
        raise ContractError("count_mismatch", "collected count와 order_plans 수가 다릅니다")
    if counts["page_count"] != collection["page_count"] or counts["request_count"] != collection["request_count"]:
        raise ContractError("count_mismatch", "collection page/request count가 다릅니다")
    if counts["source_total"] < counts["source_records"]:
        raise ContractError("count_mismatch", "source total보다 record가 많습니다")

    raw_values: set[str] = set()
    items_by_id: dict[str, dict[str, Any]] = {}
    for item in plans:
        row = require_exact_keys(item, COLLECTED_ITEM_KEYS, "collected order_plan")
        plan_id = require_nonblank(row["order_plan_unty_no"], "missing_plan_id", "order plan id가 없습니다")
        if plan_id in items_by_id:
            raise ContractError("duplicate_plan_id", "collected plan id가 중복됐습니다")
        require_nonblank(row["title"], "invalid_field", "order plan title이 비어 있습니다")
        for field in ("agency_code", "agency_name", "business_division_code", "planned_order_year", "planned_order_month", "procurement_method", "contract_method", "notice_posted"):
            _assert_string_or_null(row[field], f"collected.{field}", nonblank=True)
        for field in ("supervising_agency_name", "service_type", "service_type_code"):
            _assert_string_or_null(row[field], f"collected.{field}", nonblank=False)
        if row["business_division"] not in ALLOWED_DIVISIONS:
            raise ContractError("source_binding_mismatch", "collected business division이 allowlist 밖입니다")
        if not isinstance(row["planned_order_year"], str) or not re.fullmatch(r"\d{4}", row["planned_order_year"]):
            raise ContractError("invalid_field", "planned_order_year가 잘못됐습니다")
        if not isinstance(row["planned_order_month"], str) or not MONTH_RE.fullmatch(row["planned_order_month"]):
            raise ContractError("invalid_field", "planned_order_month가 잘못됐습니다")
        _assert_nonnegative_amount(row["budget_amount"], "budget_amount")
        _assert_nonnegative_amount(row["contract_amount"], "contract_amount")
        if row["sw_business_status"] is not None:
            _assert_string_or_null(row["sw_business_status"], "sw_business_status", nonblank=True)
        for field in ("changed_at", "bid_ntice_no_list", "rcrit_rgst_no", "source_url"):
            _assert_string_or_null(row[field], f"collected.{field}")
        for field in ("published_at", "first_discovered_at", "last_discovered_at"):
            parse_timestamp(row[field], f"collected.{field}")
        if row["changed_at"] is not None:
            parse_timestamp(row["changed_at"], "collected.changed_at")
        if not is_sha256(row["source_sha256"]):
            raise ContractError("invalid_hash", "collected source hash가 잘못됐습니다")
        unknown = row["unknown_fields"]
        if not isinstance(unknown, list) or not all(isinstance(value, str) and value for value in unknown) or len(unknown) != len(set(unknown)):
            raise ContractError("invalid_unknown_fields", "unknown_fields가 잘못됐습니다")
        for field in unknown:
            if field not in COLLECTED_ITEM_KEYS or row[field] is not None:
                raise ContractError("invalid_unknown_fields", "unknown field와 null 보존이 일치하지 않습니다")
        raw_value = row["raw_source"]
        parts = _relative_parts(raw_value, "raw_source")
        if not parts or parts[0] != "raw":
            raise ContractError("unsafe_path", "raw_source는 raw 디렉터리 아래여야 합니다")
        raw_values.add(raw_value)
        items_by_id[plan_id] = row
    source_run_dir = artifact_path.parent
    raw_index, raw_manifest_sha256 = _validate_raw_pages(
        source_run_dir,
        raw_values,
        expected_page_count=collection["page_count"],
        expected_request_count=collection["request_count"],
        source_window=window,
        order_month_scope=order_month_scope,
    )
    if set(raw_index) != set(items_by_id):
        raise ContractError("source_population_mismatch", "collected와 raw 입력 모집단이 다릅니다")
    for plan_id, row in items_by_id.items():
        source_digest, raw_value = raw_index[plan_id]
        if row["raw_source"] != raw_value or row["source_sha256"] != source_digest:
            raise ContractError("hash_mismatch", "정규화 record와 raw record hash가 다릅니다")
    actual_hash = sha256_file(artifact_path)
    source_run_id = source_run_dir.name
    if source_run_id.startswith("order-plans-"):
        source_run_id = source_run_id[len("order-plans-"):]
    return {
        "path": artifact_path,
        "sha256": actual_hash,
        "source_run_id": source_run_id,
        "population_count": len(plans),
        "business_divisions": list(metadata["business_divisions"]),
        "complete": collection["complete"],
        "raw_manifest_sha256": raw_manifest_sha256,
        "items_by_id": items_by_id,
    }


def validate_population_artifact(repo_root: Path, collected: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    artifact_path = path or resolve_repo_file(repo_root, POPULATION_RELATIVE, "selection population")
    document = require_exact_keys(
        load_json(artifact_path),
        {"schema_version", "run_id", "created_at", "input_sha256", "population_sha256", "items"},
        "selection population",
    )
    if document["schema_version"] != POPULATION_SCHEMA:
        raise ContractError("schema_mismatch", "selection population schema가 다릅니다")
    require_nonblank(document["run_id"], "invalid_run_id", "selection population run id가 필요합니다")
    parse_timestamp(document["created_at"], "population.created_at")
    _assert_hash(collected["sha256"], document["input_sha256"], "population input")
    if not is_sha256(document["population_sha256"]):
        raise ContractError("invalid_hash", "population hash가 잘못됐습니다")
    items = document["items"]
    if not isinstance(items, list) or not items:
        raise ContractError("invalid_population", "population items가 비어 있습니다")
    ids: set[str] = set()
    source_items = collected["items_by_id"]
    for index, item in enumerate(items):
        row = require_exact_keys(item, POPULATION_ITEM_KEYS, f"population item {index}")
        plan_id = require_nonblank(row["plan_id"], "missing_plan_id", "population plan id가 없습니다")
        if plan_id in ids:
            raise ContractError("duplicate_plan_id", "population plan id가 중복됐습니다")
        ids.add(plan_id)
        source = source_items.get(plan_id)
        if source is None:
            raise ContractError("source_population_mismatch", "population에 source 없는 plan이 있습니다")
        mapping = {
            "title": "title",
            "agency_code": "agency_code",
            "agency_name": "agency_name",
            "supervising_agency_name": "supervising_agency_name",
            "business_division": "business_division",
            "business_division_code": "business_division_code",
            "service_type": "service_type",
            "service_type_code": "service_type_code",
            "budget_amount": "budget_amount",
            "contract_amount": "contract_amount",
            "planned_order_month": "planned_order_month",
            "procurement_method": "procurement_method",
            "contract_method": "contract_method",
            "sw_business_status": "sw_business_status",
            "official_url": "source_url",
            "published_at": "published_at",
            "changed_at": "changed_at",
            "first_discovered_at": "first_discovered_at",
            "last_discovered_at": "last_discovered_at",
            "unknown_fields": "unknown_fields",
        }
        for population_key, source_key in mapping.items():
            if row[population_key] != source[source_key]:
                raise ContractError("source_population_mismatch", "population projection이 source와 다릅니다")
        source_ref = require_exact_keys(row["source"], {"raw_ref", "source_sha256"}, "population source")
        if source_ref["source_sha256"] != source["source_sha256"]:
            raise ContractError("hash_mismatch", "population source hash가 다릅니다")
        raw_ref = require_nonblank(source_ref["raw_ref"], "unsafe_path", "population raw_ref가 필요합니다")
        _relative_parts(raw_ref.split("#/", 1)[0], "population raw_ref")
        if not re.fullmatch(r"input/collected-order-plans\.json#/order_plans/\d+", raw_ref):
            raise ContractError("unsafe_path", "population raw_ref 형식이 잘못됐습니다")
    if len(items) != collected["population_count"] or ids != set(source_items):
        raise ContractError("count_mismatch", "population count 또는 id 집합이 다릅니다")
    _assert_hash(digest_json(items), document["population_sha256"], "population")
    actual_hash = sha256_file(artifact_path)
    return {
        "path": artifact_path,
        "sha256": actual_hash,
        "population_sha256": document["population_sha256"],
        "population_count": len(items),
        "run_id": document["run_id"],
        "items_by_id": {item["plan_id"]: item for item in items},
    }


def validate_bm25_config(repo_root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    path = resolve_repo_file(repo_root, BM25_RELATIVE, "BM25 config")
    actual_hash = sha256_file(path)
    _assert_hash(actual_hash, EXPECTED["bm25_sha256"], "BM25 config")
    config = require_exact_keys(
        load_json(path),
        {
            "schema_version",
            "note",
            "method_version",
            "model_name",
            "model_revision",
            "prompt_id",
            "prompt_sha256",
            "analyzer",
            "ngram_min",
            "ngram_max",
            "k1",
            "b",
            "query_term_frequency",
            "capability_aggregation",
        },
        "BM25 config",
    )
    if config["schema_version"] != "bidops.order-plan-bm25.v1" or config["method_version"] != "bm25-char-title-capability-v1":
        raise ContractError("schema_mismatch", "BM25 config version이 다릅니다")
    if config["analyzer"] != "char" or config["ngram_min"] != 2 or config["ngram_max"] != 5 or config["k1"] != 1.2 or config["b"] != 0.75 or config["query_term_frequency"] != "binary" or config["capability_aggregation"] != "max_bm25":
        raise ContractError("policy_binding_mismatch", "BM25 config 값이 정책과 다릅니다")
    stage1_config = policy["stage1"]["config"]
    if stage1_config["sha256"] != actual_hash or stage1_config["method_version"] != config["method_version"]:
        raise ContractError("policy_binding_mismatch", "정책의 BM25 binding이 다릅니다")
    return {"path": path, "sha256": actual_hash, "config": config}


def validate_policy_artifact(repo_root: Path, review: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    policy_path = path or resolve_repo_file(repo_root, POLICY_RELATIVE, "screening policy")
    policy_hash = sha256_file(policy_path)
    if path is None:
        _assert_hash(policy_hash, EXPECTED["policy_sha256"], "screening policy")
    policy = require_exact_keys(
        load_json(policy_path),
        {
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
        },
        "screening policy",
    )
    if policy["schema_version"] != POLICY_SCHEMA or policy["producer"] != "phase0-contracts" or policy["consumer"] != "phase1-screening-pipeline":
        raise ContractError("schema_mismatch", "screening policy provenance가 다릅니다")
    if policy["policy_status"] not in ("draft", "activation_candidate", "active", "retired"):
        raise ContractError("invalid_policy_status", "screening policy status가 잘못됐습니다")
    parse_timestamp(policy["created_at"], "policy.created_at")
    if policy["decision_scope"] != "c2_order_plan_first_pass":
        raise ContractError("policy_binding_mismatch", "screening policy scope가 다릅니다")
    stage1 = require_exact_keys(policy["stage1"], {"method", "config", "top_k", "population"}, "policy.stage1")
    if stage1["method"] != "bm25" or stage1["top_k"] != 300:
        raise ContractError("policy_binding_mismatch", "BM25 top_k가 300이 아닙니다")
    config = require_exact_keys(
        stage1["config"],
        {"path", "schema_version", "sha256", "method_version", "normalization", "tokenization", "scoring", "tie_break"},
        "policy.stage1.config",
    )
    if config["path"] != BM25_RELATIVE or config["schema_version"] != "bidops.order-plan-bm25.v1" or config["sha256"] != EXPECTED["bm25_sha256"]:
        raise ContractError("policy_binding_mismatch", "정책 BM25 config 참조가 다릅니다")
    if config["tie_break"] != ["score_desc", "order_plan_unty_no_asc"]:
        raise ContractError("policy_binding_mismatch", "BM25 tie-break가 다릅니다")
    normalization = require_exact_keys(config["normalization"], {"unicode", "case", "whitespace", "fields"}, "policy BM25 normalization")
    if normalization != {"unicode": "NFKC", "case": "casefold", "whitespace": "collapse_runs_and_trim", "fields": ["title"]}:
        raise ContractError("policy_binding_mismatch", "BM25 normalization이 다릅니다")
    tokenization = require_exact_keys(config["tokenization"], {"type", "min_n", "max_n", "boundary"}, "policy BM25 tokenization")
    if tokenization != {"type": "character_ngram", "min_n": 2, "max_n": 5, "boundary": "within_field"}:
        raise ContractError("policy_binding_mismatch", "BM25 tokenization이 다릅니다")
    scoring = require_exact_keys(config["scoring"], {"k1", "b", "query_term_frequency", "capability_aggregation", "idf_corpus"}, "policy BM25 scoring")
    if scoring != {"k1": 1.2, "b": 0.75, "query_term_frequency": "binary", "capability_aggregation": "max_bm25", "idf_corpus": "full_population_titles"}:
        raise ContractError("policy_binding_mismatch", "BM25 scoring이 다릅니다")
    population_rules = require_exact_keys(stage1["population"], {"source_schema_version", "business_divisions", "complete_required", "empty_population", "at_or_below_top_k", "above_top_k"}, "policy population")
    if population_rules["source_schema_version"] != COLLECTED_SCHEMA or population_rules["business_divisions"] != list(ALLOWED_DIVISIONS) or population_rules["complete_required"] is not True or population_rules["empty_population"] != "reject":
        raise ContractError("policy_binding_mismatch", "population policy가 다릅니다")
    if population_rules["at_or_below_top_k"] != {"action": "select_all", "audit_sample": "not_applicable"} or population_rules["above_top_k"] != {"action": "select_exact_top_k"}:
        raise ContractError("policy_binding_mismatch", "population 경계 policy가 다릅니다")
    validate_bm25_config(repo_root, policy)

    stage2 = require_exact_keys(policy["stage2"], {"provider", "model_name", "model_digest", "generation_config", "prompt", "company_profile", "payload", "batching", "response", "retry"}, "policy.stage2")
    if stage2["provider"] != "approved_private_vllm" or stage2["model_name"] != "qwen3.8-27B" or stage2["model_digest"] != "6ae70ca30563209f09ec0114ce5813f7a232b38e5bb409f2adbd0e9bbe318b11":
        raise ContractError("policy_binding_mismatch", "Qwen model binding이 다릅니다")
    generation_config = require_exact_keys(stage2["generation_config"], {"version", "sha256"}, "policy generation config")
    if generation_config != {"version": "vllm-qwen-order-plan-batch-nonthinking-v4", "sha256": EXPECTED["generation_config_sha256"]}:
        raise ContractError("policy_binding_mismatch", "generation config binding이 다릅니다")
    prompt = require_exact_keys(stage2["prompt"], {"version", "sha256"}, "policy prompt")
    if prompt["version"] != review["active_prompt_version"] or prompt["sha256"] != review["active_prompt_sha256"]:
        raise ContractError("policy_binding_mismatch", "prompt binding이 active manifest와 다릅니다")
    profile = require_exact_keys(stage2["company_profile"], {"version", "sha256", "allowed_fields"}, "policy company profile")
    if profile["version"] != review["active_company_profile_version"] or profile["sha256"] != review["active_company_capabilities_sha256"] or profile["allowed_fields"] != ["capabilities"]:
        raise ContractError("policy_binding_mismatch", "company profile binding이 active manifest와 다릅니다")
    payload = require_exact_keys(stage2["payload"], {"allowed_plan_fields", "allowed_company_fields", "forbidden_fields"}, "policy payload")
    if payload["allowed_plan_fields"] != ["plan_id", "title"] or payload["allowed_company_fields"] != ["capabilities"]:
        raise ContractError("payload_policy_mismatch", "model payload allowlist가 다릅니다")
    if not isinstance(payload["forbidden_fields"], list) or not all(isinstance(field, str) and field for field in payload["forbidden_fields"]) or not {"agency_code", "agency_name", "budget_amount", "business_division", "contract_amount", "source_url", "raw_source", "review", "attachment", "credential"}.issubset(set(payload["forbidden_fields"])):
        raise ContractError("payload_policy_mismatch", "model payload 금지 필드가 부족합니다")
    batching = require_exact_keys(stage2["batching"], {"mode", "size", "last_batch", "concurrency", "order"}, "policy batching")
    if batching != {"mode": "fixed_rank_contiguous", "size": 25, "last_batch": "shorter_allowed", "concurrency": 1, "order": "stage1_rank_ascending"}:
        raise ContractError("policy_binding_mismatch", "Qwen batching policy가 다릅니다")
    response = require_exact_keys(stage2["response"], {"format", "required_item_cardinality", "labels", "review_retained_labels", "score", "reason"}, "policy response")
    if response["format"] != "strict_json" or response["required_item_cardinality"] != "exactly_once" or response["labels"] != ["relevant", "not_relevant", "uncertain"] or response["review_retained_labels"] != ["relevant", "uncertain"]:
        raise ContractError("policy_binding_mismatch", "Qwen response label policy가 다릅니다")
    score = require_exact_keys(response["score"], {"finite", "minimum", "maximum"}, "policy score")
    if score != {"finite": True, "minimum": 0.0, "maximum": 1.0}:
        raise ContractError("policy_binding_mismatch", "Qwen score policy가 다릅니다")
    reason = require_exact_keys(response["reason"], {"min_length", "max_length"}, "policy reason")
    if reason != {"min_length": 1, "max_length": 500}:
        raise ContractError("policy_binding_mismatch", "Qwen reason policy가 다릅니다")
    retry = require_exact_keys(stage2["retry"], {"max_attempts", "retryable_failure_types", "non_retryable_failure_types", "after_exhaustion"}, "policy retry")
    if retry["max_attempts"] != 2 or retry["after_exhaustion"] != "human_review_required":
        raise ContractError("policy_binding_mismatch", "Qwen retry policy가 다릅니다")
    if retry["retryable_failure_types"] != ["timeout", "truncated_output", "schema_violation", "id_mismatch", "transport"] or retry["non_retryable_failure_types"] != ["model_mismatch", "binding_mismatch", "payload_not_approved", "policy_rejected"]:
        raise ContractError("policy_binding_mismatch", "Qwen failure retry 분류가 다릅니다")

    audit = require_exact_keys(policy["audit_sample"], {"status", "enabled", "population", "strata", "selection_order", "replacement", "sample_size", "review_cadence", "allowed_review_labels", "pending_decision"}, "policy audit sample")
    if audit["status"] != "pending_human_approval" or audit["enabled"] is not False or audit["population"] != "stage1_filtered_out" or audit["strata"] != ["classification_proximity", "performance_similarity_proximity", "uniform_hash"] or audit["selection_order"] != "stratum_priority_then_sha256_plan_id" or audit["replacement"] != "none" or audit["sample_size"] is not None or audit["review_cadence"] is not None or audit["pending_decision"] != "sample_size_and_review_cadence":
        raise ContractError("audit_policy_not_approved", "탈락 감사 표본 policy가 아직 승인 대기 상태가 아닙니다")
    if audit["allowed_review_labels"] != ["relevant", "not_relevant", "uncertain"]:
        raise ContractError("policy_binding_mismatch", "감사 표본 label policy가 다릅니다")
    execution = require_exact_keys(policy["execution"], {"active_slot", "queue_order", "stale_recovery", "automatic_resume", "statuses", "terminal_statuses", "status_rules"}, "policy execution")
    expected_statuses = ["대기", "실행 중", "중지 요청", "성공", "부분 성공", "실패", "중단됨"]
    if execution["active_slot"] != 1 or execution["queue_order"] != "fifo" or execution["stale_recovery"] != "manual_new_execution" or execution["automatic_resume"] is not False or execution["statuses"] != expected_statuses or execution["terminal_statuses"] != ["성공", "부분 성공", "실패", "중단됨"]:
        raise ContractError("policy_binding_mismatch", "execution state policy가 다릅니다")
    expected_status_rules = {
        "성공": "모든 eligible batch가 검증을 통과하고 full-population merge와 publish가 성공함",
        "부분 성공": "하나 이상의 batch 결과가 유효하고 하나 이상의 batch가 failed 또는 rejected임",
        "실패": "유효한 결과를 publish하지 못했거나 preflight·BM25·merge가 실패함",
        "중단됨": "stop 요청 또는 stale/process interruption으로 종료되며 보존된 성공 subset을 폐기하지 않음",
    }
    if execution["status_rules"] != expected_status_rules:
        raise ContractError("policy_binding_mismatch", "terminal status rule이 다릅니다")
    feedback = require_exact_keys(policy["feedback"], {"schema_version", "relevance", "priority", "priority_unspecified", "memo_unspecified", "revision", "update_policy", "does_not_update"}, "policy feedback")
    if feedback["schema_version"] != "bidops.order-plan-screening-feedback.v1" or feedback["relevance"] != ["relevant", "not_relevant", "uncertain"] or feedback["priority"] != ["high", "medium", "low"] or feedback["priority_unspecified"] is not None or feedback["memo_unspecified"] is not None or feedback["revision"] != "append_only_sequence_per_execution_plan" or feedback["update_policy"] != "new_revision_only":
        raise ContractError("policy_binding_mismatch", "feedback policy가 다릅니다")
    if feedback["does_not_update"] != ["grade", "readiness", "tracking_status", "final_go_no_go"]:
        raise ContractError("policy_scope_mismatch", "feedback가 변경하지 않는 축이 다릅니다")
    quality = require_exact_keys(policy["quality_gate"], {"status", "gold_status", "gold_manifest_sha256", "gold_artifact_sha256", "human_adjudication_count", "draft_label_count", "remaining_confirmation_count", "targets", "activation_eligible"}, "policy quality gate")
    if quality["status"] != "not_measured" or quality["gold_status"] != "partially_human_adjudicated" or quality["human_adjudication_count"] != 22 or quality["draft_label_count"] != 603 or quality["remaining_confirmation_count"] != 87 or quality["activation_eligible"] is not False:
        raise ContractError("quality_gate_invalid", "현재 quality gate 상태가 실제 gold 상태와 다릅니다")
    _assert_hash(EXPECTED["gold_manifest_sha256"], quality["gold_manifest_sha256"], "quality gold manifest")
    _assert_hash(EXPECTED["gold_artifact_sha256"], quality["gold_artifact_sha256"], "quality gold artifact")
    targets = require_exact_keys(quality["targets"], {"recall", "precision", "important_missed_max", "review_load_max"}, "quality targets")
    if any(value is not None for value in targets.values()):
        raise ContractError("quality_gate_invalid", "미측정 quality gate에 threshold가 설정돼 있습니다")
    bindings = require_exact_keys(policy["bindings"], {"bm25_config_sha256", "prompt_sha256", "company_profile_sha256", "model_digest", "generation_config_sha256"}, "policy bindings")
    if bindings != {"bm25_config_sha256": EXPECTED["bm25_sha256"], "prompt_sha256": review["active_prompt_sha256"], "company_profile_sha256": review["active_company_capabilities_sha256"], "model_digest": stage2["model_digest"], "generation_config_sha256": EXPECTED["generation_config_sha256"]}:
        raise ContractError("policy_binding_mismatch", "policy digest binding이 다릅니다")
    activation = require_exact_keys(policy["activation"], {"status", "enabled", "approved_by", "approved_at", "required_conditions", "blockers"}, "policy activation")
    expected_blockers = ["c1_gold_incomplete", "audit_sample_policy_unapproved", "quality_gate_not_measured", "private_vllm_transport_requires_per_execution_approval"]
    if activation["status"] != "blocked" or activation["enabled"] is not False or activation["approved_by"] is not None or activation["approved_at"] is not None or activation["blockers"] != expected_blockers:
        raise ContractError("activation_boundary_violation", "policy activation이 blocked 경계를 벗어났습니다")
    return {"path": policy_path, "sha256": policy_hash, "policy": policy}


def _load_tsv(path: Path, header: list[str], label: str) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if reader.fieldnames != header:
                raise ContractError("invalid_tsv", f"{label} header가 계약과 다릅니다")
            rows = list(reader)
    except ContractError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ContractError("invalid_tsv", f"{label}을 읽을 수 없습니다") from exc
    if any(None in row for row in rows):
        raise ContractError("invalid_tsv", f"{label} 열 수가 계약과 다릅니다")
    return rows


def validate_gold_artifact(repo_root: Path, path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or resolve_repo_file(repo_root, GOLD_MANIFEST_RELATIVE, "gold manifest")
    manifest = require_exact_keys(
        load_json(manifest_path),
        {"schema_version", "status", "draft_path", "draft_sha256", "adjudication_path", "adjudication_sha256", "population_count", "human_adjudication_count", "draft_label_count", "effective_counts", "remaining_confirmation_count", "files"},
        "gold manifest",
    )
    if manifest["schema_version"] != GOLD_SCHEMA or manifest["status"] not in ("draft", "partially_human_adjudicated", "human_adjudicated", "rejected"):
        raise ContractError("gold_status_invalid", "gold manifest 상태가 잘못됐습니다")
    for field in ("draft_sha256", "adjudication_sha256"):
        if not is_sha256(manifest[field]):
            raise ContractError("invalid_hash", "gold source hash가 잘못됐습니다")
    if any(isinstance(manifest[field], bool) or not isinstance(manifest[field], int) or manifest[field] < 0 for field in ("population_count", "human_adjudication_count", "draft_label_count", "remaining_confirmation_count")):
        raise ContractError("invalid_gold", "gold count가 잘못됐습니다")
    effective_counts = require_exact_keys(manifest["effective_counts"], {"관련", "비관련"}, "gold effective counts")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in effective_counts.values()) or sum(effective_counts.values()) != manifest["population_count"]:
        raise ContractError("count_mismatch", "gold effective count가 다릅니다")
    draft_path = resolve_repo_file(repo_root, manifest["draft_path"], "gold draft")
    adjudication_path = resolve_repo_file(repo_root, manifest["adjudication_path"], "gold adjudication")
    _assert_hash(sha256_file(draft_path), manifest["draft_sha256"], "gold draft")
    _assert_hash(sha256_file(adjudication_path), manifest["adjudication_sha256"], "gold adjudication")
    files = require_exact_keys(manifest["files"], {"gold-adjudicated-full-population.tsv", "remaining-confirmation-queue.tsv"}, "gold files")
    full_path = resolve_child_file(manifest_path.parent, "gold-adjudicated-full-population.tsv", "gold full artifact")
    remaining_path = resolve_child_file(manifest_path.parent, "remaining-confirmation-queue.tsv", "gold remaining queue")
    _assert_hash(sha256_file(full_path), files["gold-adjudicated-full-population.tsv"], "gold full artifact")
    _assert_hash(sha256_file(remaining_path), files["remaining-confirmation-queue.tsv"], "gold remaining queue")
    if path is None:
        _assert_hash(sha256_file(manifest_path), EXPECTED["gold_manifest_sha256"], "gold manifest")
        _assert_hash(files["gold-adjudicated-full-population.tsv"], EXPECTED["gold_artifact_sha256"], "gold full artifact")
        _assert_hash(files["remaining-confirmation-queue.tsv"], EXPECTED["gold_remaining_sha256"], "gold remaining queue")
    full_rows = _load_tsv(full_path, GOLD_HEADER, "gold full artifact")
    remaining_rows = _load_tsv(remaining_path, GOLD_HEADER, "gold remaining queue")
    adjudications = _load_tsv(adjudication_path, ADJUDICATION_HEADER, "gold adjudication")
    draft_rows = _load_tsv(draft_path, DRAFT_HEADER, "gold draft")
    if len(full_rows) != manifest["population_count"] or len(draft_rows) != manifest["population_count"] or len(adjudications) != manifest["human_adjudication_count"] or len(remaining_rows) != manifest["remaining_confirmation_count"]:
        raise ContractError("count_mismatch", "gold artifact row count가 manifest와 다릅니다")
    full_ids = [row["plan_id"] for row in full_rows]
    if any(not isinstance(value, str) or not value.strip() for value in full_ids) or len(set(full_ids)) != len(full_ids):
        raise ContractError("duplicate_plan_id", "gold full artifact plan id가 중복됐습니다")
    source_counter = Counter(row["label_source"] for row in full_rows)
    if source_counter != Counter({"human": manifest["human_adjudication_count"], "draft": manifest["draft_label_count"]}):
        raise ContractError("count_mismatch", "gold human/draft row count가 다릅니다")
    if manifest["status"] == "human_adjudicated" and (manifest["draft_label_count"] or manifest["remaining_confirmation_count"]):
        raise ContractError("gold_status_invalid", "draft 또는 remaining이 있는 gold를 human_adjudicated로 선언할 수 없습니다")
    if manifest["status"] == "partially_human_adjudicated" and (manifest["draft_label_count"] == 0 or manifest["remaining_confirmation_count"] == 0):
        raise ContractError("gold_status_invalid", "부분 adjudication 상태와 잔여 count가 다릅니다")
    effective_counter = Counter(row["effective_relevance"] for row in full_rows)
    if effective_counter != Counter({"관련": effective_counts["관련"], "비관련": effective_counts["비관련"]}):
        raise ContractError("count_mismatch", "gold effective relevance count가 다릅니다")
    for row in full_rows:
        if row["label_source"] == "human":
            if not row["human_relevance"] or not row["reviewer"] or not row["reviewed_at"]:
                raise ContractError("gold_status_invalid", "human gold row에 adjudication provenance가 없습니다")
        elif row["label_source"] == "draft":
            if row["human_relevance"] or row["reviewer"] or row["reviewed_at"]:
                raise ContractError("gold_status_invalid", "draft gold row에 human provenance가 있습니다")
        else:
            raise ContractError("gold_status_invalid", "gold label_source가 잘못됐습니다")
    human_ids = {row["plan_id"] for row in full_rows if row["label_source"] == "human"}
    adjudication_ids = {row["plan_id"] for row in adjudications}
    if len(adjudications) != len(adjudication_ids) or any(not row["plan_id"].strip() for row in adjudications) or human_ids != adjudication_ids:
        raise ContractError("gold_status_invalid", "human gold와 adjudication id가 다릅니다")
    remaining_ids = [row["plan_id"] for row in remaining_rows]
    if any(not value.strip() for value in remaining_ids) or len(set(remaining_ids)) != len(remaining_ids) or not set(remaining_ids).issubset(set(full_ids)):
        raise ContractError("gold_status_invalid", "remaining queue id가 gold full과 다릅니다")
    for row in remaining_rows:
        if row["label_source"] != "draft" or row["human_relevance"] or row["reviewer"] or row["reviewed_at"]:
            raise ContractError("gold_status_invalid", "remaining queue에 human adjudication이 섞였습니다")
    return {
        "manifest_path": manifest_path,
        "manifest_sha256": sha256_file(manifest_path),
        "full_path": full_path,
        "full_sha256": files["gold-adjudicated-full-population.tsv"],
        "remaining_path": remaining_path,
        "remaining_sha256": files["remaining-confirmation-queue.tsv"],
        "status": manifest["status"],
        "population_count": manifest["population_count"],
        "human_adjudication_count": manifest["human_adjudication_count"],
        "draft_label_count": manifest["draft_label_count"],
        "remaining_confirmation_count": manifest["remaining_confirmation_count"],
        "effective_counts": dict(effective_counts),
    }


def validate_selection_decision(repo_root: Path, population: dict[str, Any], gold: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    selection_path = path or resolve_repo_file(repo_root, SELECTION_RELATIVE, "selection decision")
    selection_hash = sha256_file(selection_path)
    if path is None:
        _assert_hash(selection_hash, EXPECTED["selection_sha256"], "selection decision")
    decision = require_exact_keys(
        load_json(selection_path),
        {"schema_version", "decision_id", "decision_status", "decision_scope", "decided_at", "decision_authority", "selected_method", "evidence", "measured_metrics", "accepted_tradeoff", "runtime_rules", "operational_activation"},
        "selection decision",
    )
    if decision["schema_version"] != SELECTION_SCHEMA or decision["decision_status"] != "selected" or decision["decision_scope"] != "c2_order_plan_first_pass_method":
        raise ContractError("selection_invalid", "selection decision 상태·scope가 다릅니다")
    parse_timestamp(decision["decided_at"], "selection.decided_at")
    selected = require_exact_keys(decision["selected_method"], {"name", "stage1", "stage2"}, "selection method")
    if selected["name"] != "BM25 Top 300 + Qwen":
        raise ContractError("selection_invalid", "선정 method가 다릅니다")
    stage1 = require_exact_keys(selected["stage1"], {"method", "top_k", "config_sha256"}, "selection stage1")
    if stage1 != {"method": "bm25", "top_k": 300, "config_sha256": EXPECTED["bm25_sha256"]}:
        raise ContractError("selection_invalid", "선정 stage1 binding이 다릅니다")
    stage2 = require_exact_keys(selected["stage2"], {"method", "model_name", "model_revision", "prompt_id", "prompt_sha256", "company_capabilities_sha256", "batch_size", "candidate_labels"}, "selection stage2")
    if stage2 != {"method": "qwen", "model_name": "qwen3.8-27B", "model_revision": "6ae70ca30563209f09ec0114ce5813f7a232b38e5bb409f2adbd0e9bbe318b11", "prompt_id": "order-plan-batch-relevance-v3", "prompt_sha256": EXPECTED["prompt_sha256"], "company_capabilities_sha256": EXPECTED["company_profile_sha256"], "batch_size": 25, "candidate_labels": ["relevant", "uncertain"]}:
        raise ContractError("selection_invalid", "선정 stage2 binding이 다릅니다")
    evidence = require_exact_keys(decision["evidence"], {"run_id", "source_population_count", "source_population_sha256", "cascade_path", "cascade_sha256", "qwen_result_path", "qwen_result_sha256", "scoring_path", "scoring_sha256", "reference_sha256", "accepted_misses_path", "accepted_misses_sha256"}, "selection evidence")
    if evidence["run_id"] != "20260827-20260830-bm25-qwen300-v3" or evidence["source_population_count"] != population["population_count"] or evidence["source_population_sha256"] != EXPECTED["population_sha256"] or evidence["reference_sha256"] != gold["full_sha256"]:
        raise ContractError("selection_invalid", "selection evidence population/gold binding이 다릅니다")
    experiment_dir = selection_path.parent
    evidence_paths = {
        "cascade_path": (evidence["cascade_path"], EXPECTED["cascade_sha256"]),
        "qwen_result_path": (evidence["qwen_result_path"], EXPECTED["qwen_result_sha256"]),
        "scoring_path": (evidence["scoring_path"], EXPECTED["scoring_sha256"]),
        "accepted_misses_path": (evidence["accepted_misses_path"], EXPECTED["accepted_misses_sha256"]),
    }
    for field, (value, expected) in evidence_paths.items():
        evidence_path = resolve_child_file(experiment_dir, value, f"selection {field}")
        _assert_hash(sha256_file(evidence_path), expected, f"selection {field}")
    qwen_result_path = resolve_child_file(experiment_dir, evidence["qwen_result_path"], "selection qwen result")
    qwen_result = require_object(load_json(qwen_result_path), "selection qwen result")
    if qwen_result.get("schema_version") != "bidops.order-plan-method-result.v3" or qwen_result.get("run_id") != evidence["run_id"] or qwen_result.get("method") != "qwen" or qwen_result.get("method_version") != "vllm-qwen-order-plan-batch-nonthinking-v4" or qwen_result.get("config_sha256") != EXPECTED["generation_config_sha256"]:
        raise ContractError("selection_invalid", "Qwen historical evidence generation binding이 다릅니다")
    miss_path = resolve_child_file(experiment_dir, evidence["accepted_misses_path"], "accepted misses")
    miss_rows = _load_tsv(miss_path, MISS_HEADER, "accepted misses")
    if len(miss_rows) != 2 or any(row["accepted_for_c2"] != "true" or row["miss_stage"] != "bm25_top300_filtered_out" for row in miss_rows):
        raise ContractError("selection_invalid", "accepted miss 기록이 다릅니다")
    if len({row["plan_id"] for row in miss_rows}) != len(miss_rows):
        raise ContractError("duplicate_plan_id", "accepted miss plan id가 중복됐습니다")
    rules = require_exact_keys(decision["runtime_rules"], {"stage1_filtered_out_is_not_qwen_not_relevant", "qwen_failure_has_no_model_fallback", "final_go_no_go_remains_human"}, "selection runtime rules")
    if rules != {"stage1_filtered_out_is_not_qwen_not_relevant": True, "qwen_failure_has_no_model_fallback": True, "final_go_no_go_remains_human": True}:
        raise ContractError("selection_scope_mismatch", "selection runtime rule이 다릅니다")
    activation = require_exact_keys(decision["operational_activation"], {"active", "reason"}, "selection activation")
    if activation["active"] is not False or not isinstance(activation["reason"], str) or not activation["reason"].strip():
        raise ContractError("activation_boundary_violation", "선정 decision이 operational activation으로 선언됐습니다")
    return {"path": selection_path, "sha256": selection_hash, "decision": decision}


def _validate_ref_hash(repo_root: Path, ref: dict[str, Any], label: str) -> Path:
    row = require_object(ref, label)
    value = row.get("path")
    actual_path = resolve_repo_file(repo_root, value, label)
    expected = row.get("sha256")
    _assert_hash(sha256_file(actual_path), expected, label)
    return actual_path


def validate_binding(repo_root: Path, review: dict[str, Any], collected: dict[str, Any], population: dict[str, Any], policy: dict[str, Any], selection: dict[str, Any], gold: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    binding_path = path or resolve_repo_file(repo_root, BINDING_RELATIVE, "phase0 binding")
    binding_hash = sha256_file(binding_path)
    if path is None:
        _assert_hash(binding_hash, EXPECTED["binding_sha256"], "phase0 binding")
    binding = require_exact_keys(
        load_json(binding_path),
        {"schema_version", "producer", "consumer", "binding_version", "status", "created_at", "policy", "selection_decision", "source_input", "selection_evidence_population", "stage1_binding", "stage2_binding", "selection_evidence", "review_inputs", "gold", "external_transport", "compatibility", "activation"},
        "phase0 binding",
    )
    if binding["schema_version"] != BINDING_SCHEMA or binding["producer"] != "phase0-contracts" or binding["consumer"] != "phase1-screening-pipeline" or binding["status"] != "blocked":
        raise ContractError("binding_invalid", "phase0 binding provenance/status가 다릅니다")
    parse_timestamp(binding["created_at"], "binding.created_at")
    policy_ref = require_exact_keys(binding["policy"], {"path", "schema_version", "policy_version", "sha256", "policy_status"}, "binding policy ref")
    policy_path = _validate_ref_hash(repo_root, {"path": policy_ref["path"], "sha256": policy_ref["sha256"]}, "binding policy")
    if policy_path != policy["path"] or policy_ref["schema_version"] != POLICY_SCHEMA or policy_ref["policy_version"] != policy["policy"]["policy_version"] or policy_ref["policy_status"] != policy["policy"]["policy_status"]:
        raise ContractError("binding_invalid", "binding policy ref가 실제 policy와 다릅니다")
    selection_ref = require_exact_keys(binding["selection_decision"], {"path", "schema_version", "sha256", "decision_status", "operational_activation"}, "binding selection ref")
    selection_path = _validate_ref_hash(repo_root, {"path": selection_ref["path"], "sha256": selection_ref["sha256"]}, "binding selection")
    if selection_path != selection["path"] or selection_ref["schema_version"] != SELECTION_SCHEMA or selection_ref["decision_status"] != "selected" or selection_ref["operational_activation"] is not False:
        raise ContractError("binding_invalid", "binding selection ref가 실제 selection과 다릅니다")
    source_ref = require_exact_keys(binding["source_input"], {"path", "schema_version", "sha256", "raw_manifest_sha256", "source_run_id", "population_count", "complete", "business_divisions"}, "binding source ref")
    source_path = _validate_ref_hash(repo_root, {"path": source_ref["path"], "sha256": source_ref["sha256"]}, "binding source")
    if source_path != collected["path"] or source_ref["schema_version"] != COLLECTED_SCHEMA or source_ref["raw_manifest_sha256"] != collected["raw_manifest_sha256"] or source_ref["raw_manifest_sha256"] != EXPECTED["raw_manifest_sha256"] or source_ref["source_run_id"] != collected["source_run_id"] or source_ref["population_count"] != collected["population_count"] or source_ref["complete"] is not True or source_ref["business_divisions"] != list(ALLOWED_DIVISIONS):
        raise ContractError("binding_invalid", "binding source ref가 실제 source와 다릅니다")
    population_ref = require_exact_keys(binding["selection_evidence_population"], {"path", "schema_version", "file_sha256", "population_sha256", "population_count"}, "binding population ref")
    population_path = _validate_ref_hash(repo_root, {"path": population_ref["path"], "sha256": population_ref["file_sha256"]}, "binding population")
    if population_path != population["path"] or population_ref["schema_version"] != POPULATION_SCHEMA or population_ref["file_sha256"] != EXPECTED["population_file_sha256"] or population_ref["population_sha256"] != population["population_sha256"] or population_ref["population_count"] != population["population_count"]:
        raise ContractError("binding_invalid", "binding population ref가 실제 population과 다릅니다")
    stage1 = require_exact_keys(binding["stage1_binding"], {"method", "path", "schema_version", "sha256", "top_k", "tie_break"}, "binding stage1")
    if stage1 != {"method": "bm25", "path": BM25_RELATIVE, "schema_version": "bidops.order-plan-bm25.v1", "sha256": EXPECTED["bm25_sha256"], "top_k": 300, "tie_break": ["score_desc", "order_plan_unty_no_asc"]}:
        raise ContractError("binding_invalid", "binding stage1이 고정값과 다릅니다")
    stage2 = require_exact_keys(binding["stage2_binding"], {"provider", "model_name", "model_digest", "generation_config_version", "generation_config_sha256", "prompt_version", "prompt_sha256", "company_profile_version", "company_profile_sha256", "payload_fields", "company_payload_fields", "batch_size", "max_attempts", "concurrency"}, "binding stage2")
    expected_stage2 = {"provider": "approved_private_vllm", "model_name": "qwen3.8-27B", "model_digest": "6ae70ca30563209f09ec0114ce5813f7a232b38e5bb409f2adbd0e9bbe318b11", "generation_config_version": "vllm-qwen-order-plan-batch-nonthinking-v4", "generation_config_sha256": EXPECTED["generation_config_sha256"], "prompt_version": review["active_prompt_version"], "prompt_sha256": review["active_prompt_sha256"], "company_profile_version": review["active_company_profile_version"], "company_profile_sha256": review["active_company_capabilities_sha256"], "payload_fields": ["plan_id", "title"], "company_payload_fields": ["capabilities"], "batch_size": 25, "max_attempts": 2, "concurrency": 1}
    if stage2 != expected_stage2:
        raise ContractError("binding_invalid", "binding stage2가 고정값과 다릅니다")
    evidence = require_exact_keys(binding["selection_evidence"], {"cascade_path", "cascade_sha256", "qwen_result_path", "qwen_result_sha256", "scoring_path", "scoring_sha256", "accepted_misses_path", "accepted_misses_sha256", "accepted_misses_count"}, "binding selection evidence")
    selection_dir = selection["path"].parent
    for field, expected in (("cascade_sha256", EXPECTED["cascade_sha256"]), ("qwen_result_sha256", EXPECTED["qwen_result_sha256"]), ("scoring_sha256", EXPECTED["scoring_sha256"]), ("accepted_misses_sha256", EXPECTED["accepted_misses_sha256"])):
        path_field = field.replace("_sha256", "_path")
        evidence_path = resolve_repo_file(repo_root, evidence[path_field], f"binding {path_field}")
        if evidence_path != resolve_child_file(selection_dir, selection["decision"]["evidence"][path_field], f"selection {path_field}") or evidence[field] != expected:
            raise ContractError("binding_invalid", "binding selection evidence path/hash가 다릅니다")
        _assert_hash(sha256_file(evidence_path), evidence[field], f"binding {field}")
    if evidence["accepted_misses_count"] != 2:
        raise ContractError("binding_invalid", "accepted miss count가 다릅니다")
    review_ref = require_exact_keys(binding["review_inputs"], {"manifest_path", "manifest_schema_version", "manifest_sha256", "active_company_capabilities_path", "active_company_capabilities_sha256", "active_prompt_path", "active_prompt_sha256"}, "binding review inputs")
    review_manifest_path = _validate_ref_hash(repo_root, {"path": review_ref["manifest_path"], "sha256": review_ref["manifest_sha256"]}, "binding review manifest")
    if review_manifest_path != review["manifest_path"] or review_ref["manifest_schema_version"] != REVIEW_INPUT_SCHEMA or review_ref["manifest_sha256"] != review["manifest_sha256"] or review_ref["active_company_capabilities_path"] != f"{REVIEW_INPUTS_RELATIVE}/{review['active_company_capabilities']}" or review_ref["active_company_capabilities_sha256"] != review["active_company_capabilities_sha256"] or review_ref["active_prompt_path"] != f"{REVIEW_INPUTS_RELATIVE}/{review['active_prompt']}" or review_ref["active_prompt_sha256"] != review["active_prompt_sha256"]:
        raise ContractError("binding_invalid", "binding review input ref가 다릅니다")
    gold_ref = require_exact_keys(binding["gold"], {"manifest_path", "manifest_schema_version", "manifest_sha256", "status", "full_artifact_path", "full_artifact_sha256", "remaining_queue_path", "remaining_queue_sha256", "population_count", "human_adjudication_count", "draft_label_count", "remaining_confirmation_count", "activation_eligible"}, "binding gold")
    gold_manifest_path = _validate_ref_hash(repo_root, {"path": gold_ref["manifest_path"], "sha256": gold_ref["manifest_sha256"]}, "binding gold manifest")
    for field, path_value, expected in (("full_artifact_sha256", gold_ref["full_artifact_path"], gold["full_sha256"]), ("remaining_queue_sha256", gold_ref["remaining_queue_path"], gold["remaining_sha256"])):
        referenced = _validate_ref_hash(repo_root, {"path": path_value, "sha256": gold_ref[field]}, f"binding gold {field}")
        if referenced != (gold["full_path"] if field == "full_artifact_sha256" else gold["remaining_path"]) or gold_ref[field] != expected:
            raise ContractError("binding_invalid", "binding gold artifact ref가 다릅니다")
    if gold_manifest_path != gold["manifest_path"] or gold_ref["manifest_schema_version"] != GOLD_SCHEMA or gold_ref["status"] != gold["status"] or gold_ref["manifest_sha256"] != gold["manifest_sha256"] or gold_ref["population_count"] != gold["population_count"] or gold_ref["human_adjudication_count"] != gold["human_adjudication_count"] or gold_ref["draft_label_count"] != gold["draft_label_count"] or gold_ref["remaining_confirmation_count"] != gold["remaining_confirmation_count"] or gold_ref["activation_eligible"] is not False:
        raise ContractError("binding_invalid", "binding gold 상태/count가 다릅니다")
    transport = require_exact_keys(binding["external_transport"], {"status", "execution_allowed", "approval_required_per_execution", "endpoint_source", "redirects", "environment_proxy", "fallback_provider"}, "binding external transport")
    if transport != {"status": "not_allowed_for_product_runtime", "execution_allowed": False, "approval_required_per_execution": True, "endpoint_source": "runtime_secret_and_literal_allowlist", "redirects": False, "environment_proxy": False, "fallback_provider": None}:
        raise ContractError("transport_boundary_violation", "external transport fail-closed 경계가 다릅니다")
    compatibility = require_exact_keys(binding["compatibility"], {"legacy_experiment_artifacts", "legacy_schema_mutation", "new_semantics_require_new_version"}, "binding compatibility")
    if compatibility != {"legacy_experiment_artifacts": "read_only", "legacy_schema_mutation": False, "new_semantics_require_new_version": True}:
        raise ContractError("compatibility_violation", "legacy compatibility 경계가 다릅니다")
    activation = require_exact_keys(binding["activation"], {"status", "enabled", "approved_by", "approved_at", "blockers"}, "binding activation")
    if activation["status"] != "blocked" or activation["enabled"] is not False or activation["approved_by"] is not None or activation["approved_at"] is not None or activation["blockers"] != policy["policy"]["activation"]["blockers"]:
        raise ContractError("activation_boundary_violation", "binding activation이 blocked 경계를 벗어났습니다")
    return {"path": binding_path, "sha256": binding_hash, "status": binding["status"], "binding": binding}


def validate_phase0(repo_root: Path = REPO_ROOT, *, policy_path: Path | None = None, binding_path: Path | None = None) -> dict[str, Any]:
    repo_root = _resolve_directory(repo_root, "repository root")
    contract_count = validate_schema_catalog(repo_root)
    review = validate_review_inputs(repo_root)
    collected = validate_collected_artifact(repo_root)
    if collected["sha256"] != EXPECTED["source_sha256"]:
        raise ContractError("hash_mismatch", "collected input의 고정 digest가 다릅니다")
    _assert_hash(collected["raw_manifest_sha256"], EXPECTED["raw_manifest_sha256"], "raw page manifest")
    population = validate_population_artifact(repo_root, collected)
    if population["sha256"] != EXPECTED["population_file_sha256"] or population["population_sha256"] != EXPECTED["population_sha256"]:
        raise ContractError("hash_mismatch", "selection population의 고정 digest가 다릅니다")
    gold = validate_gold_artifact(repo_root)
    policy = validate_policy_artifact(repo_root, review, path=policy_path)
    selection = validate_selection_decision(repo_root, population, gold)
    binding = validate_binding(repo_root, review, collected, population, policy, selection, gold, path=binding_path)
    blockers = list(policy["policy"]["activation"]["blockers"])
    return {
        "status": "valid_but_blocked",
        "contract_count": contract_count,
        "policy_version": policy["policy"]["policy_version"],
        "policy_sha256": policy["sha256"],
        "binding_sha256": binding["sha256"],
        "source_run_id": collected["source_run_id"],
        "population_count": collected["population_count"],
        "gold_status": gold["status"],
        "human_adjudication_count": gold["human_adjudication_count"],
        "draft_label_count": gold["draft_label_count"],
        "remaining_confirmation_count": gold["remaining_confirmation_count"],
        "execution_allowed": False,
        "activation_allowed": False,
        "blockers": blockers,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument("--binding", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate_phase0(args.repo_root, policy_path=args.policy, binding_path=args.binding)
    except ContractError as exc:
        print(f"phase0=invalid error_code={exc.code}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(
            "phase0=valid_but_blocked "
            f"contracts={result['contract_count']} "
            f"population={result['population_count']} "
            f"c1_human={result['human_adjudication_count']} "
            f"c1_draft={result['draft_label_count']} "
            f"c1_remaining={result['remaining_confirmation_count']} "
            "execution_allowed=false activation_allowed=false "
            f"blockers={','.join(result['blockers'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
