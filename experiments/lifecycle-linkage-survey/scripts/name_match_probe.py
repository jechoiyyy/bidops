#!/usr/bin/env python3
"""Measure how well an order-plan business name finds its pre-specification.

There is no official key from a pre-specification back to an order plan, so the
product has to fall back to the candidate linkage that docs/business-rules.md
prescribes.  This probe measures whether a name search can carry that link, and
it grades itself against ground truth rather than against its own guess.

Ground truth comes from the bid notice, which carries both `orderPlanUntyNo`
and `bfSpecRgstNo`.  For every plan whose notice is present in the collected
bid window, the true pre-specification number is known.  The probe then asks
the search endpoint for the plan's business name and checks whether that known
number comes back.
"""

from __future__ import annotations

import argparse
import sys
import urllib.parse
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parents[1] / "order-plan-screening" / "scripts"))
sys.path.insert(0, str(_SCRIPT_DIR))

from common import ExperimentError, write_json_new  # noqa: E402
from endpoints import ENDPOINTS, KST  # noqa: E402
import survey  # noqa: E402


PROBE_SCHEMA = "bidops.lifecycle-name-match-probe.v1"
# `bfSpecRgstNo` and `refNo` have their own lookup modes (`inqryDiv` 2 and 3),
# but neither is known from an order plan.  Under the receipt-datetime mode the
# endpoint honours `prdctClsfcNoNm` as a partial match, so the business name is
# the only bridge available from the plan side.
SEARCH_FIELD = "prdctClsfcNoNm"


def ground_truth_pairs(raw_root: Path) -> list[dict[str, str]]:
    """Pair each order plan with the pre-specification its notice points to."""

    plans = survey.items_from_pages(survey.read_raw_pages(raw_root / "order_plan"))
    bids = survey.items_from_pages(survey.read_raw_pages(raw_root / "bid"))

    bid_by_no: dict[str, dict[str, Any]] = {}
    for bid in bids:
        bid_by_no.setdefault(bid["bidNtceNo"], bid)

    pairs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for plan in plans:
        title = (plan.get("bizNm") or "").strip()
        if not title:
            continue
        for entry in (plan.get("bidNtceNoList") or "").split(","):
            entry = entry.strip()
            # The plan concatenates the 13-character notice number with its
            # 3-character ordinal; only the number joins to the notice list.
            if len(entry) != 16:
                continue
            bid = bid_by_no.get(entry[:13])
            if bid is None:
                continue
            spec = (bid.get("bfSpecRgstNo") or "").strip()
            if not spec:
                continue
            key = (plan["orderPlanUntyNo"], spec)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(
                {
                    "plan_id": plan["orderPlanUntyNo"],
                    "plan_title": title,
                    "plan_agency": (plan.get("orderInsttNm") or "").strip(),
                    "bid_no": entry[:13],
                    "expected_spec_no": spec,
                }
            )
    return pairs


def search_by_name(
    fetcher: survey.SurveyFetcher,
    name: str,
    from_date: date,
    to_date: date,
    rows: int,
) -> tuple[int, list[dict[str, Any]]]:
    endpoint = ENDPOINTS["prespec_search"]
    query = endpoint.query_builder(from_date, to_date, 1, rows)
    query[SEARCH_FIELD] = name
    payload, _attempts = fetcher.fetch(endpoint.url, query)
    items, total, _page_no, _rows = survey.extract_page(payload)
    return total, items


def grade(pair: dict[str, str], total: int, items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    returned = [(item.get("bfSpecRgstNo") or "").strip() for item in items]
    hit = pair["expected_spec_no"] in returned
    agencies = {(item.get("orderInsttNm") or "").strip() for item in items}
    return {
        "plan_id": pair["plan_id"],
        "expected_spec_no": pair["expected_spec_no"],
        "result_count": total,
        "returned_count": len(items),
        "hit": hit,
        # A single result that is the right one can be confirmed cheaply; more
        # than one still needs a person, which is what the business rules ask.
        "unique_hit": hit and total == 1,
        "agency_matches": pair["plan_agency"] in agencies if agencies else False,
        "returned_spec_nos": returned[:10],
    }


def summarise(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    hits = sum(1 for row in rows if row["hit"])
    unique = sum(1 for row in rows if row["unique_hit"])
    empty = sum(1 for row in rows if row["result_count"] == 0)
    return {
        "pair_count": total,
        "hit_count": hits,
        "hit_rate": round(hits / total, 4) if total else None,
        "unique_hit_count": unique,
        "unique_hit_rate": round(unique / total, 4) if total else None,
        "empty_result_count": empty,
        "agency_match_count": sum(1 for row in rows if row["agency_matches"]),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--from-date", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--to-date", type=date.fromisoformat, default=date(2026, 8, 29))
    parser.add_argument("--rows", type=int, default=50)
    parser.add_argument("--limit", type=int, default=100, help="검사할 정답쌍 수 상한")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--execute", action="store_true", help="외부 G2B 호출을 명시적으로 허용합니다")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not args.execute:
            print(
                "외부 호출이 승인되지 않았습니다. --execute를 명시하면 G2B를 호출합니다.",
                file=sys.stderr,
            )
            return 2
        pairs = ground_truth_pairs(args.raw_dir.resolve())
        if not pairs:
            raise ExperimentError("no_ground_truth", "정답쌍을 만들 수 없습니다")
        pairs = pairs[: args.limit]
        fetcher = survey.SurveyFetcher(
            survey.get_service_key(), timeout=args.timeout, max_attempts=args.max_attempts
        )
        rows: list[dict[str, Any]] = []
        for index, pair in enumerate(pairs, start=1):
            total, items = search_by_name(
                fetcher, pair["plan_title"], args.from_date, args.to_date, args.rows
            )
            rows.append(grade(pair, total, items))
            if index % 20 == 0:
                print(f"  {index}/{len(pairs)} 진행", file=sys.stderr)
        document = {
            "schema_version": PROBE_SCHEMA,
            "run_id": args.run_id,
            "created_at": datetime.now(KST).isoformat(),
            "search_field": SEARCH_FIELD,
            "search_window": {
                "from": args.from_date.isoformat(),
                "to_exclusive": args.to_date.isoformat(),
            },
            "request_count": fetcher.request_count,
            "summary": summarise(rows),
            "results": rows,
        }
        write_json_new(args.output_dir.resolve() / "name-match-probe.json", document)
        summary = document["summary"]
        print(
            f"정답쌍 {summary['pair_count']}건 · 적중 {summary['hit_count']}"
            f" ({(summary['hit_rate'] or 0) * 100:.1f}%) · 단일적중 {summary['unique_hit_count']}"
            f" · 결과없음 {summary['empty_result_count']}"
        )
        return 0
    except ExperimentError as exc:
        print(f"error[{exc.code}]: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
