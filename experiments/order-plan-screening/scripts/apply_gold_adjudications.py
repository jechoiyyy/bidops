#!/usr/bin/env python3
"""Apply explicit human adjudications to a gold draft without rewriting it."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


DRAFT_FIELDS = (
    "draft_order", "plan_id", "title", "agency_name", "budget_amount",
    "planned_order_month", "published_at", "source_sha256", "draft_relevance",
    "draft_priority", "draft_reason", "draft_basis", "confirmation_role",
    "human_relevance", "human_priority", "human_reason", "reviewer", "reviewed_at",
)
ADJUDICATION_FIELDS = (
    "plan_id", "draft_relevance", "draft_priority", "human_relevance",
    "human_priority", "adjudication", "human_reason", "reviewer", "reviewed_at",
)
OUTPUT_FIELDS = DRAFT_FIELDS + (
    "effective_relevance", "effective_priority", "effective_reason", "label_source",
)
ALLOWED = {
    ("관련", "높음"), ("관련", "보통"), ("관련", "낮음"),
    ("판단보류", "낮음"), ("비관련", "해당없음"),
}


class AdjudicationError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", required=True, type=Path)
    parser.add_argument("--adjudications", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path, fields: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if tuple(reader.fieldnames or ()) != fields:
                raise AdjudicationError(f"TSV 열 계약이 다릅니다: {path.name}")
            return [{key: value or "" for key, value in row.items()} for row in reader]
    except AdjudicationError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise AdjudicationError(f"TSV를 읽을 수 없습니다: {path.name}") from exc


def validate_adjudications(
    draft_rows: list[dict[str, str]], adjudication_rows: list[dict[str, str]]
) -> dict[str, dict[str, str]]:
    draft_by_id = {row["plan_id"]: row for row in draft_rows}
    if len(draft_by_id) != len(draft_rows):
        raise AdjudicationError("draft plan_id가 중복됐습니다.")
    result: dict[str, dict[str, str]] = {}
    for index, row in enumerate(adjudication_rows, start=2):
        plan_id = row["plan_id"].strip()
        if not plan_id or plan_id in result or plan_id not in draft_by_id:
            raise AdjudicationError(f"adjudication plan_id가 비었거나 중복·범위 밖입니다: {index}행")
        draft = draft_by_id[plan_id]
        if row["draft_relevance"] != draft["draft_relevance"] or row["draft_priority"] != draft["draft_priority"]:
            raise AdjudicationError(f"adjudication이 draft와 맞지 않습니다: {plan_id}")
        combination = (row["human_relevance"].strip(), row["human_priority"].strip())
        if combination not in ALLOWED:
            raise AdjudicationError(f"사람 판정 조합이 잘못됐습니다: {plan_id}")
        if not row["adjudication"].strip() or not row["human_reason"].strip() or not row["reviewer"].strip():
            raise AdjudicationError(f"사람 판정 근거·작성자 표식이 필요합니다: {plan_id}")
        try:
            parsed = datetime.fromisoformat(row["reviewed_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise AdjudicationError(f"reviewed_at 형식이 잘못됐습니다: {plan_id}") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise AdjudicationError(f"reviewed_at timezone이 없습니다: {plan_id}")
        result[plan_id] = row
    return result


def write_tsv_new(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    draft_rows = read_tsv(args.draft, DRAFT_FIELDS)
    adjudication_rows = read_tsv(args.adjudications, ADJUDICATION_FIELDS)
    adjudications = validate_adjudications(draft_rows, adjudication_rows)
    output_rows: list[dict[str, str]] = []
    for draft in draft_rows:
        row = draft.copy()
        human = adjudications.get(row["plan_id"])
        if human is not None:
            row.update({
                "human_relevance": human["human_relevance"],
                "human_priority": human["human_priority"],
                "human_reason": human["human_reason"],
                "reviewer": human["reviewer"],
                "reviewed_at": human["reviewed_at"],
                "effective_relevance": human["human_relevance"],
                "effective_priority": human["human_priority"],
                "effective_reason": human["human_reason"],
                "label_source": "human",
            })
        else:
            row.update({
                "effective_relevance": row["draft_relevance"],
                "effective_priority": row["draft_priority"],
                "effective_reason": row["draft_reason"],
                "label_source": "draft",
            })
        output_rows.append(row)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "gold-adjudicated-full-population.tsv"
    remaining_path = args.output_dir / "remaining-confirmation-queue.tsv"
    manifest_path = args.output_dir / "manifest.json"
    remaining = [
        row for row in output_rows
        if row["confirmation_role"] != "확인 큐 제외" and row["label_source"] != "human"
    ]
    write_tsv_new(output_path, OUTPUT_FIELDS, output_rows)
    write_tsv_new(remaining_path, OUTPUT_FIELDS, remaining)
    manifest = {
        "schema_version": "bidops.order-plan-gold-adjudication-manifest.v1",
        "status": "partially_human_adjudicated",
        "draft_path": str(args.draft),
        "draft_sha256": sha256(args.draft),
        "adjudication_path": str(args.adjudications),
        "adjudication_sha256": sha256(args.adjudications),
        "population_count": len(output_rows),
        "human_adjudication_count": len(adjudications),
        "draft_label_count": len(output_rows) - len(adjudications),
        "effective_counts": dict(sorted(Counter(row["effective_relevance"] for row in output_rows).items())),
        "remaining_confirmation_count": len(remaining),
        "files": {
            output_path.name: sha256(output_path),
            remaining_path.name: sha256(remaining_path),
        },
    }
    with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
