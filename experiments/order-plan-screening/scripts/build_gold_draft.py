#!/usr/bin/env python3
"""Build a reviewable order-plan gold draft without claiming human authorship."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ARTIFACT_SCHEMA = "bidops.collected-order-plans.v1"
DECISION_SCHEMA = "bidops.order-plan-gold-draft-decisions.v1"
MANIFEST_SCHEMA = "bidops.order-plan-gold-draft-manifest.v1"
ALLOWED = {
    ("관련", "높음"),
    ("관련", "보통"),
    ("관련", "낮음"),
    ("판단보류", "낮음"),
    ("비관련", "해당없음"),
}
FIELDS = (
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
)
NEAR_MISS_TERMS = (
    "ai", "ax", "정보", "시스템", "플랫폼", "데이터", "디지털", "sw",
    "소프트웨어", "gis", "db", "온라인", "스마트", "클라우드", "모니터링",
)


class DraftError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--near-miss-audit", type=int, default=20)
    parser.add_argument("--random-audit", type=int, default=10)
    return parser.parse_args()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DraftError(f"JSON을 읽을 수 없습니다: {path.name}") from exc
    if not isinstance(value, dict):
        raise DraftError(f"JSON 최상위가 object가 아닙니다: {path.name}")
    return value


def nonrelevant_reason(title: str) -> str:
    text = title.casefold()
    if any(term in text for term in ("감리", "안전점검", "안전진단", "성능평가", "기술진단")):
        return "감리·안전점검·진단 등 검증 용역이며 정보시스템 직접 구축·운영 범위가 확인되지 않는다."
    if any(term in text for term in ("폐기물", "건설사업관리", "실시설계", "건축설계", "전기공사", "측량")):
        return "건축·토목·시설 또는 폐기물 분야 용역으로 회사 핵심 디지털 사업 범위와 직접 연결되지 않는다."
    if any(term in text for term in ("행사", "축제", "수학여행", "현장체험", "연수", "홍보", "광고", "전시", "콘텐츠 제작")):
        return "행사·여행·교육운영·홍보·콘텐츠 과업이며 디지털 시스템 납품 범위가 확인되지 않는다."
    if any(term in text for term in ("조사", "연구", "컨설팅", "분석 용역", "전략 수립")):
        return "조사·연구·컨설팅 중심 과업이며 AI·데이터·정보시스템 구현 범위가 확인되지 않는다."
    if any(term in text for term in ("임차", "보험", "급식", "운반", "수거", "청소", "처리용역")):
        return "임차·보험·급식·운반·청소 등 공급·운영 용역으로 회사 핵심 디지털 역량과 직접 연결되지 않는다."
    return "제목과 공개 메타데이터에서 회사 핵심 AI·데이터·블록체인·공공 SI 과업이 확인되지 않는다."


def validate_decisions(
    decisions: dict[str, Any], input_sha256: str, plans: list[dict[str, Any]]
) -> dict[str, dict[str, str]]:
    if decisions.get("schema_version") != DECISION_SCHEMA:
        raise DraftError("draft decision schema가 다릅니다.")
    if decisions.get("input_sha256") != input_sha256:
        raise DraftError("draft decision이 수집 artifact hash와 맞지 않습니다.")
    if decisions.get("input_record_count") != len(plans):
        raise DraftError("draft decision의 모집단 건수가 다릅니다.")
    overrides = decisions.get("overrides")
    if not isinstance(overrides, dict):
        raise DraftError("overrides는 object여야 합니다.")
    population_ids = {plan["order_plan_unty_no"] for plan in plans}
    if not set(overrides) <= population_ids:
        raise DraftError("overrides에 모집단 밖 plan_id가 있습니다.")
    validated: dict[str, dict[str, str]] = {}
    for plan_id, decision in overrides.items():
        if not isinstance(decision, dict) or set(decision) != {"relevance", "priority", "reason"}:
            raise DraftError(f"override 형식이 잘못됐습니다: {plan_id}")
        relevance = str(decision["relevance"]).strip()
        priority = str(decision["priority"]).strip()
        reason = " ".join(str(decision["reason"]).split())
        if (relevance, priority) not in ALLOWED or not reason:
            raise DraftError(f"override 판정이 잘못됐습니다: {plan_id}")
        validated[plan_id] = {
            "relevance": relevance,
            "priority": priority,
            "reason": reason,
        }
    return validated


def audit_ids(rows: list[dict[str, str]], near_count: int, random_count: int) -> tuple[set[str], set[str]]:
    negatives = [row for row in rows if row["draft_relevance"] == "비관련"]
    near = [
        row for row in negatives
        if any(re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", row["title"].casefold()) if term.isascii() else term in row["title"].casefold() for term in NEAR_MISS_TERMS)
    ]
    near.sort(
        key=lambda row: (
            -sum(term in row["title"].casefold() for term in NEAR_MISS_TERMS),
            hashlib.sha256(("near-miss-v1:" + row["plan_id"]).encode()).hexdigest(),
        )
    )
    near_ids = {row["plan_id"] for row in near[:near_count]}
    remaining = [row for row in negatives if row["plan_id"] not in near_ids]
    remaining.sort(key=lambda row: hashlib.sha256(("random-audit-v1:" + row["plan_id"]).encode()).hexdigest())
    return near_ids, {row["plan_id"] for row in remaining[:random_count]}


def write_tsv_new(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, str]]) -> str:
    lines = [
        "| 구분 | 우선순위 | 계획번호 | 사업명 | 기관 | 예산 | 초안 근거 | 사람 판정 |",
        "|---|---|---|---|---|---:|---|---|",
    ]
    for row in rows:
        cells = [
            row["confirmation_role"], row["draft_priority"], row["plan_id"],
            row["title"], row["agency_name"], row["budget_amount"] or "미표기",
            row["draft_reason"], "",
        ]
        escaped = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    if args.near_miss_audit < 0 or args.random_audit < 0:
        raise DraftError("audit 크기는 0 이상이어야 합니다.")
    if args.output_dir.exists():
        raise DraftError("기존 output-dir을 덮어쓸 수 없습니다.")
    artifact = load_json(args.input)
    if artifact.get("schema_version") != ARTIFACT_SCHEMA:
        raise DraftError("수집 artifact schema가 다릅니다.")
    plans = artifact.get("order_plans")
    if not isinstance(plans, list) or len(plans) != artifact.get("counts", {}).get("total"):
        raise DraftError("수집 artifact 모집단 건수가 잘못됐습니다.")
    input_sha = file_sha256(args.input)
    decisions_doc = load_json(args.decisions)
    overrides = validate_decisions(decisions_doc, input_sha, plans)

    rows: list[dict[str, str]] = []
    for index, plan in enumerate(plans, start=1):
        plan_id = plan["order_plan_unty_no"]
        decision = overrides.get(plan_id)
        if decision is None:
            relevance, priority = "비관련", "해당없음"
            reason = nonrelevant_reason(plan.get("title") or "")
            basis = "전수 제목·공개 메타데이터 검토 후 비관련 기본군"
        else:
            relevance = decision["relevance"]
            priority = decision["priority"]
            reason = decision["reason"]
            basis = "개별 의미 검토 override"
        rows.append({
            "draft_order": str(index),
            "plan_id": plan_id,
            "title": plan.get("title") or "",
            "agency_name": plan.get("agency_name") or "",
            "budget_amount": "" if plan.get("budget_amount") is None else str(plan["budget_amount"]),
            "planned_order_month": plan.get("planned_order_month") or "",
            "published_at": plan.get("published_at") or "",
            "source_sha256": plan.get("source_sha256") or "",
            "draft_relevance": relevance,
            "draft_priority": priority,
            "draft_reason": reason,
            "draft_basis": basis,
            "confirmation_role": "",
            "human_relevance": "",
            "human_priority": "",
            "human_reason": "",
            "reviewer": "",
            "reviewed_at": "",
        })

    near_ids, random_ids = audit_ids(rows, args.near_miss_audit, args.random_audit)
    for row in rows:
        if row["draft_relevance"] == "판단보류":
            row["confirmation_role"] = "판단보류 결정"
        elif row["draft_relevance"] == "관련":
            row["confirmation_role"] = "관련 초안 승인"
        elif row["plan_id"] in near_ids:
            row["confirmation_role"] = "비관련 근접 감사"
        elif row["plan_id"] in random_ids:
            row["confirmation_role"] = "비관련 무작위 감사"
        else:
            row["confirmation_role"] = "확인 큐 제외"

    queue_order = {"판단보류 결정": 0, "관련 초안 승인": 1, "비관련 근접 감사": 2, "비관련 무작위 감사": 3}
    priority_order = {"높음": 0, "보통": 1, "낮음": 2, "해당없음": 3}
    queue = [row.copy() for row in rows if row["confirmation_role"] != "확인 큐 제외"]
    queue.sort(key=lambda row: (queue_order[row["confirmation_role"]], priority_order[row["draft_priority"]], row["plan_id"]))

    args.output_dir.mkdir(parents=True, exist_ok=False)
    full_path = args.output_dir / "gold-draft-full-population.tsv"
    queue_path = args.output_dir / "human-confirmation-queue.tsv"
    markdown_path = args.output_dir / "human-confirmation-queue.md"
    manifest_path = args.output_dir / "manifest.json"
    write_tsv_new(full_path, rows)
    write_tsv_new(queue_path, queue)
    markdown = (
        "# 발주계획 gold 초안 확인 큐\n\n"
        "> 이 파일은 사람이 확정한 gold가 아니다. `draft_*`는 보조 판정이며, "
        "`human_*`·`reviewer`·`reviewed_at`을 담당자가 채운 뒤에만 사람 gold로 승격할 수 있다.\n\n"
        f"- 입력: `{args.input}`\n"
        f"- 입력 SHA-256: `{input_sha}`\n"
        f"- 모집단: {len(rows)}건\n"
        f"- 초안 분포: {dict(Counter(row['draft_relevance'] for row in rows))}\n"
        f"- 확인 큐 분포: {dict(Counter(row['confirmation_role'] for row in queue))}\n\n"
        + markdown_table(queue)
        + "\n"
    )
    markdown_path.write_text(markdown, encoding="utf-8", newline="\n")
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "status": "draft_not_human_gold",
        "input_path": str(args.input),
        "input_sha256": input_sha,
        "input_schema_version": artifact["schema_version"],
        "source_window": artifact.get("source_window"),
        "population_count": len(rows),
        "draft_counts": dict(sorted(Counter(row["draft_relevance"] for row in rows).items())),
        "confirmation_counts": dict(sorted(Counter(row["confirmation_role"] for row in queue).items())),
        "decision_source_sha256": file_sha256(args.decisions),
        "files": {
            full_path.name: file_sha256(full_path),
            queue_path.name: file_sha256(queue_path),
            markdown_path.name: file_sha256(markdown_path),
        },
        "human_fields_complete": False,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"output_dir": str(args.output_dir), **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
