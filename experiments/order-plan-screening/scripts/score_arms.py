"""BM25 · dense · RRF 하이브리드를 사람 gold로 채점한다 (ADR-0021 개정).

세 arm을 고정 3일 모집단 997건에 돌리고 전수 사람 gold로 recall을 잰다.
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
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from methods import BM25Adapter  # noqa: E402

SCHEMA_VERSION = "bidops.order-plan-arm-scoring.v1"
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_gold(path: Path) -> Gold:
    relevance: dict[str, str] = {}
    priority: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            plan_id = row["plan_id"].strip()
            relevance[plan_id] = row["human_relevance"].strip()
            priority[plan_id] = row["human_priority"].strip()
    return Gold(relevance=relevance, priority=priority)


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--dense-result", default="bge_m3_dense.json")
    parser.add_argument(
        "--company-capabilities",
        type=Path,
        default=EXPERIMENT_ROOT / "config/company-capabilities.json",
    )
    parser.add_argument("--bm25-config", type=Path, default=EXPERIMENT_ROOT / "config/bm25.json")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--report-cutoff", type=int, default=50)
    args = parser.parse_args()

    population = json.loads((args.run_dir / "population.json").read_text(encoding="utf-8"))
    plans = population["items"]
    capabilities = json.loads(args.company_capabilities.read_text(encoding="utf-8"))
    gold = _load_gold(args.gold)

    missing = [plan["plan_id"] for plan in plans if plan["plan_id"] not in gold.relevance]
    if missing:
        print(f"gold에 없는 모집단 {len(missing)}건이 있어 중단한다: {missing[:5]}", file=sys.stderr)
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
        print("dense 결과가 success가 아니다", file=sys.stderr)
        return 1
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
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"\n사람 gold: 관련 {len(relevant_ids)}건 / 모집단 {len(plans)}건\n")
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
