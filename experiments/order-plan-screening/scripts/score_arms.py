"""BM25 · dense · RRF 하이브리드를 고정 reference로 채점한다 (ADR-0021 개정).

세 arm을 고정 모집단에 돌리고 전수 reference label로 recall을 잰다.
채택 근거는 평균 순위 품질이 아니라 **단독 arm이 놓친 건을 하이브리드가 복구하는가**다.
그래서 BM25 단독과 dense 단독을 함께 내고 서로 다른 실패를 대조한다.

기존 6-method run 계약(`common.METHOD_NAMES`)은 건드리지 않는다. 과거 회차의 run.json이
그대로 검증되어야 하기 때문이다. 이 스크립트는 분석 산출물만 새로 쓴다. 방식이
선택되면 그때 제품 경로에 통합한다.

    python3 experiments/order-plan-screening/scripts/score_arms.py \
        --run-dir data/experiments/order-plan-screening/20260824-20260826-interim-v8 \
        --gold data/experiments/order-plan-screening/20260824-20260826-sol200-luna797-xhigh-b100-reference-v1/review/human-gold-full-population.tsv
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from methods import BM25Adapter  # noqa: E402

SCHEMA_VERSION = "bidops.order-plan-arm-scoring.v1"
PARTIAL_SCHEMA_VERSION = "bidops.order-plan-arm-scoring-partial.v1"
EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
# 사람 gold의 `관련`만 정답으로 센다. `판단보류`는 놓쳐도 실패로 세지 않고
# 잡아도 성공으로 세지 않는다. 검토량에는 포함된다.
RELEVANT = "관련"
UNCERTAIN = "판단보류"
# RRF 상수. 원 논문 기본값이며 튜닝하지 않는다. 튜닝 노브를 만들지 않는 것이
# ADR-0021 개정의 제약이다.
RRF_K = 60
CUTOFFS = (20, 30, 50, 75, 100, 150, 200, 300)


@dataclass(frozen=True)
class Gold:
    relevance: dict[str, str]
    priority: dict[str, str]
    label_source_counts: dict[str, int]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_gold(
    path: Path,
    relevance_column: str = "human_relevance",
    priority_column: str = "human_priority",
    label_source_column: str | None = None,
) -> Gold:
    relevance: dict[str, str] = {}
    priority: dict[str, str] = {}
    source_counts: Counter[str] = Counter()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"plan_id", relevance_column, priority_column}
        if label_source_column:
            required.add(label_source_column)
        if not reader.fieldnames or not required <= set(reader.fieldnames):
            raise ValueError(f"reference 필드가 없습니다: {', '.join(sorted(required))}")
        for row in reader:
            plan_id = row["plan_id"].strip()
            if not plan_id or plan_id in relevance:
                raise ValueError("reference plan_id가 비었거나 중복됐습니다")
            relevance[plan_id] = row[relevance_column].strip()
            priority[plan_id] = row[priority_column].strip()
            if label_source_column:
                source_counts[row[label_source_column].strip() or "unknown"] += 1
    return Gold(
        relevance=relevance,
        priority=priority,
        label_source_counts=dict(sorted(source_counts.items())),
    )


def _ranked(scores: dict[str, float]) -> list[str]:
    """점수 내림차순, 동점은 plan_id 오름차순. 결정적이어야 한다."""

    return [plan_id for plan_id, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


def _rrf(rankings: dict[str, list[str]]) -> dict[str, float]:
    combined: dict[str, float] = {}
    for order in rankings.values():
        for position, plan_id in enumerate(order, start=1):
            combined[plan_id] = combined.get(plan_id, 0.0) + 1.0 / (RRF_K + position)
    return combined


def _evaluate(order: list[str], gold: Gold) -> dict[str, Any]:
    relevant_ids = {plan_id for plan_id, value in gold.relevance.items() if value == RELEVANT}
    total_relevant = len(relevant_ids)
    rank_of = {plan_id: index + 1 for index, plan_id in enumerate(order)}

    at_cutoff = []
    for cutoff in CUTOFFS:
        head = order[:cutoff]
        found = [plan_id for plan_id in head if plan_id in relevant_ids]
        at_cutoff.append(
            {
                "cutoff": cutoff,
                "review_load": len(head),
                "found": len(found),
                "missed": total_relevant - len(found),
                "recall": round(len(found) / total_relevant, 4) if total_relevant else None,
                "precision": round(len(found) / len(head), 4) if head else None,
            }
        )

    ranks = sorted(rank_of[plan_id] for plan_id in relevant_ids if plan_id in rank_of)
    return {
        "total_relevant": total_relevant,
        "at_cutoff": at_cutoff,
        # 전량 회수에 필요한 검토량. 운영에서 "중요 누락 0"을 원할 때 드는 비용이다.
        "rank_for_full_recall": ranks[-1] if ranks else None,
        "rank_p50": ranks[len(ranks) // 2] if ranks else None,
        "rank_p90": ranks[int(len(ranks) * 0.9)] if ranks else None,
        "relevant_ranks": ranks,
    }


def _high_priority_misses(order: list[str], gold: Gold, cutoff: int) -> list[dict[str, str]]:
    head = set(order[:cutoff])
    misses = [
        {"plan_id": plan_id, "priority": gold.priority.get(plan_id, "")}
        for plan_id, value in gold.relevance.items()
        if value == RELEVANT and plan_id not in head
    ]
    weight = {"높음": 0, "보통": 1, "낮음": 2}
    return sorted(misses, key=lambda row: (weight.get(row["priority"], 3), row["plan_id"]))


def _write_new(destination: Path, document: dict[str, Any]) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
    except FileExistsError:
        print(f"기존 산출물을 덮어쓸 수 없다: {destination}", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--dense-result", default="bge_m3_dense.json")
    parser.add_argument("--relevance-column", default="human_relevance")
    parser.add_argument("--priority-column", default="human_priority")
    parser.add_argument("--label-source-column")
    parser.add_argument(
        "--allow-dense-failure",
        action="store_true",
        help="dense가 실패한 경우 BM25만 채점하고 partial 산출물을 기록합니다.",
    )
    parser.add_argument(
        "--company-capabilities",
        type=Path,
        default=(
            EXPERIMENT_ROOT
            / "review-inputs/company/company-capabilities-v1-approved.json"
        ),
    )
    parser.add_argument("--bm25-config", type=Path, default=EXPERIMENT_ROOT / "config/bm25.json")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--report-cutoff", type=int, default=50)
    args = parser.parse_args()

    population = json.loads((args.run_dir / "population.json").read_text(encoding="utf-8"))
    plans = population["items"]
    capabilities = json.loads(args.company_capabilities.read_text(encoding="utf-8"))
    try:
        gold = _load_gold(
            args.gold,
            args.relevance_column,
            args.priority_column,
            args.label_source_column,
        )
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        print(f"reference를 읽을 수 없다: {exc}", file=sys.stderr)
        return 1

    missing = [plan["plan_id"] for plan in plans if plan["plan_id"] not in gold.relevance]
    if missing:
        print(f"gold에 없는 모집단 {len(missing)}건이 있어 중단한다: {missing[:5]}", file=sys.stderr)
        return 1
    population_ids = {plan["plan_id"] for plan in plans}
    extra = sorted(set(gold.relevance) - population_ids)
    if extra:
        print(f"모집단에 없는 reference {len(extra)}건이 있어 중단한다: {extra[:5]}", file=sys.stderr)
        return 1

    # methods.json은 기존 6-method 닫힌 집합 계약이라 건드리지 않는다.
    bm25_config = json.loads(args.bm25_config.read_text(encoding="utf-8"))
    print(f"BM25 실행 ({len(plans)}건) …")
    bm25_rows = BM25Adapter(bm25_config).score_all(plans, capabilities)
    bm25_scores = {plan["plan_id"]: row.score for plan, row in zip(plans, bm25_rows)}

    dense_document = json.loads(
        (args.run_dir / "results" / args.dense_result).read_text(encoding="utf-8")
    )
    if dense_document["status"] != "success":
        if not args.allow_dense_failure:
            print("dense 결과가 success가 아니다", file=sys.stderr)
            return 1
        bm25_order = _ranked(bm25_scores)
        evaluation = _evaluate(bm25_order, gold)
        relevant_ids = {
            plan_id for plan_id, value in gold.relevance.items() if value == RELEVANT
        }
        error_counts = dict(
            sorted(
                Counter(
                    item.get("error_code") or "unknown"
                    for item in dense_document.get("items", [])
                    if item.get("status") != "success"
                ).items()
            )
        )
        destination = args.out or (args.run_dir / "arm-scoring-partial.json")
        document = {
            "schema_version": PARTIAL_SCHEMA_VERSION,
            "status": "partial",
            "run_dir": str(args.run_dir),
            "population_count": len(plans),
            "population_sha256": population.get("population_sha256"),
            "gold": {
                "path": str(args.gold),
                "sha256": _sha256(args.gold),
                "relevance_column": args.relevance_column,
                "priority_column": args.priority_column,
                "label_source_column": args.label_source_column,
                "label_source_counts": gold.label_source_counts,
                "relevant": len(relevant_ids),
                "uncertain": sum(
                    1 for value in gold.relevance.values() if value == UNCERTAIN
                ),
            },
            "arms": {"bm25": {"config": bm25_config}},
            "blocked_arms": {
                "dense": {
                    "status": dense_document["status"],
                    "model": dense_document.get("model"),
                    "method_version": dense_document.get("method_version"),
                    "error_counts": error_counts,
                },
                "hybrid_rrf": {
                    "status": "blocked",
                    "reason": "dense_arm_failed",
                    "k": RRF_K,
                    "inputs": ["bm25", "dense"],
                },
            },
            "evaluations": {"bm25": evaluation},
            "high_priority_misses_at_cutoff": {
                "bm25": _high_priority_misses(bm25_order, gold, args.report_cutoff)
            },
        }
        if not _write_new(destination, document):
            return 1
        print(
            f"dense 실패로 partial 채점: BM25 Top {args.report_cutoff} "
            f"recall={next(row['recall'] for row in evaluation['at_cutoff'] if row['cutoff'] == args.report_cutoff)}"
        )
        print(f"기록: {destination}")
        return 0
    dense_scores = {
        item["plan_id"]: item["score"]
        for item in dense_document["items"]
        if item["status"] == "success" and item["score"] is not None
    }
    if set(dense_scores) != set(bm25_scores):
        print("dense와 BM25의 모집단이 다르다", file=sys.stderr)
        return 1

    orders = {"bm25": _ranked(bm25_scores), "dense": _ranked(dense_scores)}
    orders["hybrid_rrf"] = _ranked(_rrf(orders))

    evaluations = {name: _evaluate(order, gold) for name, order in orders.items()}

    cutoff = args.report_cutoff
    relevant_ids = {plan_id for plan_id, value in gold.relevance.items() if value == RELEVANT}
    heads = {name: set(order[:cutoff]) for name, order in orders.items()}
    recovery = {
        "cutoff": cutoff,
        "bm25_only": sorted(relevant_ids & heads["bm25"] - heads["dense"]),
        "dense_only": sorted(relevant_ids & heads["dense"] - heads["bm25"]),
        "both": sorted(relevant_ids & heads["bm25"] & heads["dense"]),
        "neither": sorted(relevant_ids - heads["bm25"] - heads["dense"]),
        "hybrid_recovered_over_bm25": sorted(
            relevant_ids & heads["hybrid_rrf"] - heads["bm25"]
        ),
        "hybrid_lost_from_bm25": sorted(relevant_ids & heads["bm25"] - heads["hybrid_rrf"]),
    }

    document = {
        "schema_version": SCHEMA_VERSION,
        "run_dir": str(args.run_dir),
        "population_count": len(plans),
        "population_sha256": population.get("population_sha256"),
        "gold": {
            "path": str(args.gold),
            "sha256": _sha256(args.gold),
            "relevance_column": args.relevance_column,
            "priority_column": args.priority_column,
            "label_source_column": args.label_source_column,
            "label_source_counts": gold.label_source_counts,
            "relevant": len(relevant_ids),
            "uncertain": sum(1 for value in gold.relevance.values() if value == UNCERTAIN),
        },
        "arms": {
            "bm25": {"config": bm25_config},
            "dense": {
                "model": dense_document["model"],
                "method_version": dense_document["method_version"],
            },
            "hybrid_rrf": {"k": RRF_K, "inputs": ["bm25", "dense"]},
        },
        "evaluations": evaluations,
        "recovery": recovery,
        "high_priority_misses_at_cutoff": {
            name: _high_priority_misses(order, gold, cutoff) for name, order in orders.items()
        },
    }

    destination = args.out or (args.run_dir / "arm-scoring.json")
    if not _write_new(destination, document):
        return 1

    print(f"\n평가 reference: 관련 {len(relevant_ids)}건 / 모집단 {len(plans)}건")
    if gold.label_source_counts:
        print("라벨 출처: " + ", ".join(f"{key} {value}건" for key, value in gold.label_source_counts.items()))
    print()
    header = f"{'검토량':>6} " + " ".join(f"{name:>14}" for name in orders)
    print(header)
    print("-" * len(header))
    for index, size in enumerate(CUTOFFS):
        cells = []
        for name in orders:
            row = evaluations[name]["at_cutoff"][index]
            cells.append(f"{row['found']:>3}/{len(relevant_ids)} {row['recall'] * 100:5.1f}%")
        print(f"{size:>6} " + " ".join(f"{cell:>14}" for cell in cells))

    print("\n전량 회수에 필요한 검토량")
    for name in orders:
        print(f"  {name:>12}: {evaluations[name]['rank_for_full_recall']:>4}건  "
              f"(p50 {evaluations[name]['rank_p50']}, p90 {evaluations[name]['rank_p90']})")

    print(f"\nTop {cutoff} 기준 서로 다른 실패")
    print(f"  BM25만 잡음      {len(recovery['bm25_only']):>3}건")
    print(f"  dense만 잡음     {len(recovery['dense_only']):>3}건")
    print(f"  둘 다 잡음       {len(recovery['both']):>3}건")
    print(f"  둘 다 놓침       {len(recovery['neither']):>3}건")
    print(f"  하이브리드가 BM25 대비 복구 {len(recovery['hybrid_recovered_over_bm25']):>3}건, "
          f"잃음 {len(recovery['hybrid_lost_from_bm25'])}건")
    print(f"\n기록: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
