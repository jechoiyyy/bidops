#!/usr/bin/env python3
"""Create and validate the blinded candidate-union plus audit review set."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from common import (
    REVIEW_MANIFEST_SCHEMA,
    ExperimentError,
    digest_json,
    load_json,
    load_run_population,
    parse_timezone_timestamp,
    validate_method_result,
    validate_result_run_binding,
    write_json_new,
    write_tsv_new,
)


METHOD_NAMES = ("keyword", "bge_m3_colbert", "qwen", "luna")
REVIEW_FIELDS = (
    "plan_id",
    "title",
    "agency_name",
    "budget_amount",
    "planned_order_month",
    "published_at",
    "relevance",
    "priority",
    "reason",
    "reviewer",
    "reviewed_at",
)
ALLOWED_LABEL_COMBINATIONS = {
    ("관련", "높음"),
    ("관련", "보통"),
    ("관련", "낮음"),
    ("판단보류", "낮음"),
    ("비관련", "해당없음"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--audit-size", type=int, default=50)
    parser.add_argument("--labels", type=Path, help="생성 대신 작성 완료 labels.tsv를 검증합니다.")
    return parser.parse_args()


def load_results(
    run_dir: Path,
    run: dict[str, Any],
    population: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for method in METHOD_NAMES:
        path = run_dir / "results" / f"{method}.json"
        results[method] = validate_method_result(
            load_json(path), population, method, run["selection"]["top_k"]
        )
        validate_result_run_binding(results[method], run)
    return results


def select_review_ids(
    population: dict[str, Any],
    results: dict[str, dict[str, Any]],
    audit_size: int,
) -> tuple[set[str], set[str]]:
    if audit_size < 0:
        raise ExperimentError("invalid_audit_size", "audit-size는 0 이상이어야 합니다")
    selected_union = {
        row["plan_id"]
        for result in results.values()
        for row in result["items"]
        if row["selected"]
    }
    all_ids = {item["plan_id"] for item in population["items"]}
    audit_pool = all_ids - selected_union
    if len(audit_pool) < audit_size:
        raise ExperimentError("audit_pool_too_small", "합집합 밖 감사 모집단이 요청 크기보다 작습니다")
    ordered_audit = sorted(
        audit_pool,
        key=lambda plan_id: (hashlib.sha256(plan_id.encode("utf-8")).hexdigest(), plan_id),
    )
    return selected_union, set(ordered_audit[:audit_size])


def build_review_artifacts(
    run: dict[str, Any],
    population: dict[str, Any],
    results: dict[str, dict[str, Any]],
    audit_size: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    selected_union, audit_ids = select_review_ids(population, results, audit_size)
    review_ids = selected_union | audit_ids
    population_by_id = {item["plan_id"]: item for item in population["items"]}
    ordered_ids = sorted(
        review_ids,
        key=lambda plan_id: (
            hashlib.sha256(("review-order-v1:" + plan_id).encode("utf-8")).hexdigest(),
            plan_id,
        ),
    )
    manifest_items = [
        {
            "plan_id": plan_id,
            "selection_role": "candidate_union" if plan_id in selected_union else "audit",
        }
        for plan_id in sorted(review_ids)
    ]
    manifest = {
        "schema_version": REVIEW_MANIFEST_SCHEMA,
        "run_id": run["run_id"],
        "created_at": run["created_at"],
        "input_sha256": population["population_sha256"],
        "candidate_union_count": len(selected_union),
        "audit_count": len(audit_ids),
        "review_count": len(review_ids),
        "items_sha256": digest_json(manifest_items),
        "items": manifest_items,
    }
    rows = []
    for plan_id in ordered_ids:
        plan = population_by_id[plan_id]
        rows.append(
            {
                "plan_id": plan_id,
                "title": plan["title"],
                "agency_name": plan["agency_name"],
                "budget_amount": plan["budget_amount"],
                "planned_order_month": plan["planned_order_month"],
                "published_at": plan["published_at"],
                "relevance": "",
                "priority": "",
                "reason": "",
                "reviewer": "",
                "reviewed_at": "",
            }
        )
    return manifest, rows


def validate_review_manifest(document: Any, run: dict[str, Any], population: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("schema_version") != REVIEW_MANIFEST_SCHEMA:
        raise ExperimentError("schema_mismatch", "review manifest schema_version이 다릅니다")
    if document.get("run_id") != run["run_id"] or document.get("input_sha256") != population["population_sha256"]:
        raise ExperimentError("review_binding_mismatch", "review manifest 입력 binding이 다릅니다")
    parse_timezone_timestamp(document.get("created_at"), "review-manifest.created_at")
    items = document.get("items")
    if not isinstance(items, list) or document.get("items_sha256") != digest_json(items):
        raise ExperimentError("hash_mismatch", "review manifest items hash가 다릅니다")
    ids: list[str] = []
    roles: list[str] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"plan_id", "selection_role"}:
            raise ExperimentError("invalid_contract", "review manifest item 형식이 잘못됐습니다")
        ids.append(item["plan_id"])
        roles.append(item["selection_role"])
    if len(ids) != len(set(ids)):
        raise ExperimentError("duplicate_plan_id", "review manifest plan_id가 중복됐습니다")
    if not set(ids) <= {row["plan_id"] for row in population["items"]}:
        raise ExperimentError("population_coverage_mismatch", "review manifest에 모집단 밖 ID가 있습니다")
    if not set(roles) <= {"candidate_union", "audit"}:
        raise ExperimentError("invalid_contract", "review selection_role이 잘못됐습니다")
    if document.get("review_count") != len(ids):
        raise ExperimentError("count_mismatch", "review_count가 다릅니다")
    if document.get("candidate_union_count") != roles.count("candidate_union"):
        raise ExperimentError("count_mismatch", "candidate_union_count가 다릅니다")
    if document.get("audit_count") != roles.count("audit"):
        raise ExperimentError("count_mismatch", "audit_count가 다릅니다")
    return document


def validate_manifest_selection(
    manifest: dict[str, Any],
    population: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> None:
    selected_union, audit_ids = select_review_ids(
        population, results, int(manifest["audit_count"])
    )
    expected_roles = {
        **{plan_id: "candidate_union" for plan_id in selected_union},
        **{plan_id: "audit" for plan_id in audit_ids},
    }
    actual_roles = {
        item["plan_id"]: item["selection_role"] for item in manifest["items"]
    }
    if actual_roles != expected_roles:
        raise ExperimentError(
            "review_selection_mismatch",
            "review manifest가 고정 결과의 Top K 합집합·감사 표본과 다릅니다",
        )


def read_labels(
    path: Path,
    manifest: dict[str, Any],
    population: dict[str, Any] | None = None,
) -> dict[str, dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if tuple(reader.fieldnames or ()) != REVIEW_FIELDS:
                raise ExperimentError("label_columns_invalid", "labels.tsv 열이 review 계약과 다릅니다")
            rows = list(reader)
    except ExperimentError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ExperimentError("labels_read_failed", "labels.tsv를 읽을 수 없습니다") from exc
    expected_ids = {item["plan_id"] for item in manifest["items"]}
    population_by_id = (
        {item["plan_id"]: item for item in population["items"]}
        if population is not None
        else None
    )
    labels: dict[str, dict[str, str]] = {}
    for index, row in enumerate(rows, start=2):
        plan_id = row["plan_id"].strip()
        if not plan_id or plan_id in labels:
            raise ExperimentError("duplicate_plan_id", f"labels.tsv {index}행 plan_id가 비었거나 중복됐습니다")
        if population_by_id is not None and plan_id in population_by_id:
            plan = population_by_id[plan_id]
            expected_context = {
                "plan_id": plan_id,
                "title": plan["title"],
                "agency_name": plan["agency_name"],
                "budget_amount": plan["budget_amount"],
                "planned_order_month": plan["planned_order_month"],
                "published_at": plan["published_at"],
            }
            for field_name, expected_value in expected_context.items():
                expected_text = "" if expected_value is None else str(expected_value)
                if row[field_name] != expected_text:
                    raise ExperimentError(
                        "label_source_mismatch",
                        f"labels.tsv {index}행 {field_name}이 고정 모집단과 다릅니다",
                    )
        combination = (row["relevance"].strip(), row["priority"].strip())
        if combination not in ALLOWED_LABEL_COMBINATIONS:
            raise ExperimentError("label_combination_invalid", f"labels.tsv {index}행 판정 조합이 잘못됐습니다")
        if not row["reason"].strip() or not row["reviewer"].strip():
            raise ExperimentError("label_incomplete", f"labels.tsv {index}행 reason/reviewer가 필요합니다")
        parse_timezone_timestamp(row["reviewed_at"].strip(), f"labels.tsv[{index}].reviewed_at")
        labels[plan_id] = {key: (value or "").strip() for key, value in row.items()}
    if set(labels) != expected_ids:
        missing = len(expected_ids - set(labels))
        extra = len(set(labels) - expected_ids)
        raise ExperimentError("label_coverage_mismatch", f"labels.tsv 검토 범위가 다릅니다: missing={missing}, extra={extra}")
    return labels


def main() -> int:
    args = parse_args()
    try:
        run_dir = args.run_dir.resolve()
        run, population = load_run_population(run_dir)
        review_dir = run_dir / "review"
        if args.labels is not None:
            manifest = validate_review_manifest(load_json(review_dir / "manifest.json"), run, population)
            results = load_results(run_dir, run, population)
            validate_manifest_selection(manifest, population, results)
            labels = read_labels(args.labels.resolve(), manifest, population)
            print(json.dumps({"status": "valid", "label_count": len(labels)}, ensure_ascii=False))
            return 0
        results = load_results(run_dir, run, population)
        manifest, rows = build_review_artifacts(run, population, results, args.audit_size)
        manifest_path = review_dir / "manifest.json"
        review_path = review_dir / "review.tsv"
        if manifest_path.exists() or review_path.exists():
            raise ExperimentError("artifact_exists", "기존 review 산출물을 덮어쓸 수 없습니다")
        write_json_new(manifest_path, manifest)
        write_tsv_new(review_path, REVIEW_FIELDS, rows)
        print(
            json.dumps(
                {
                    "status": "complete",
                    "candidate_union_count": manifest["candidate_union_count"],
                    "audit_count": manifest["audit_count"],
                    "review_count": manifest["review_count"],
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
