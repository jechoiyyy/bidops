#!/usr/bin/env python3
"""Measure name-normalization risk using only frozen lifecycle raw files.

This script never calls G2B.  It reads the immutable order-plan,
pre-specification, and bid pages, plus the earlier name-match probe, and
creates the three measurements needed before any live strategy probe:

* collision groups for the unnormalized full query and its fallback queries;
* the query ladder and query-length distributions for the earlier misses; and
* exact versus normalized title equality for ground-truth pairs whose
  pre-specification is present in the local raw sample.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[2]
sys.path.insert(0, str(_SCRIPT_DIR.parents[1] / "order-plan-screening" / "scripts"))
sys.path.insert(0, str(_SCRIPT_DIR))

from common import ExperimentError, digest_json, load_json, write_json_new  # noqa: E402
from endpoints import KST  # noqa: E402
import name_match_probe  # noqa: E402
import name_normalize  # noqa: E402
import survey  # noqa: E402


ANALYSIS_SCHEMA = "bidops.lifecycle-name-offline-analysis.v4"
COLLISION_STRATEGIES = (
    "full",
    "breaking_split",
    "normalized",
    "longest_fragment",
    "prefix12",
)
MAX_COLLISION_EXAMPLES = 10
V4_CHANGE_NOTE = (
    "v3 대비 변경: 문자 관용도 실측으로 확정된 파손 문자 5종만 사용하는 `breaking_split`으로 교체하고, 무해·미측정 문자는 자르지 않도록 분류했으며, 설명되지 않은 실패 20건을 별도로 남김."
)

DEFAULT_RUN_DIR = _REPO_ROOT / "data/experiments/lifecycle-linkage-survey/20260828-lifecycle-v2"
DEFAULT_RAW_DIR = DEFAULT_RUN_DIR / "raw"
DEFAULT_PROBE = DEFAULT_RUN_DIR / "name-match/name-match-probe.json"
DEFAULT_OUTPUT_DIR = DEFAULT_RUN_DIR / "name-strategy"


def _read_items(raw_dir: Path, target: str) -> list[dict[str, Any]]:
    wrappers = survey.read_raw_pages(raw_dir / target)
    return survey.items_from_pages(wrappers)


def _title_value(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    return value if isinstance(value, str) else ""


def _strategy_query(name: str, strategy: str) -> str | None:
    """Return the query used by a strategy, including duplicate ladder rungs.

    Collision measurement must include a normalized value even when the
    runtime ladder omits it because it duplicates ``full``.  The minimum
    length still follows the ladder's safety threshold for every measured
    strategy.
    """

    if strategy == "full":
        query = name_normalize.collapse(name)
    elif strategy == "breaking_split":
        query = name_normalize.breaking_split(name)
    elif strategy == "normalized":
        query = name_normalize.normalize(name)
    elif strategy == "longest_fragment":
        query = name_normalize.longest_fragment(name)
    elif strategy == "prefix12":
        query = name_normalize.collapse(name)[: name_normalize.PREFIX_CHARS].strip()
    else:
        raise ExperimentError("unknown_strategy", f"알 수 없는 이름 전략입니다: {strategy}")
    if not query or len(query) < name_normalize.MIN_FRAGMENT_CHARS:
        return None
    return query


def _collision_report(
    items: Sequence[dict[str, Any]],
    record_key: str,
    title_field: str,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "record_count": len(items),
        "record_key": record_key,
        "title_field": title_field,
        "strategies": {},
    }
    strategy_reports: dict[str, dict[str, Any]] = {}
    for strategy in COLLISION_STRATEGIES:
        groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        eligible = 0
        for item in items:
            record_id = item.get(record_key)
            title = _title_value(item, title_field)
            if not isinstance(record_id, str) or not record_id.strip() or not title:
                continue
            query = _strategy_query(title, strategy)
            if query is None:
                continue
            eligible += 1
            groups[query].append({"record_id": record_id.strip(), "title": title})

        collisions = [
            (query, records)
            for query, records in groups.items()
            if len({record["record_id"] for record in records}) > 1
        ]
        collisions.sort(key=lambda pair: (-len(pair[1]), pair[0]))
        collision_record_count = sum(len(records) for _query, records in collisions)
        collision_pair_count = sum(
            len(records) * (len(records) - 1) // 2 for _query, records in collisions
        )
        examples = [
            {"query": query, "records": records}
            for query, records in collisions[:MAX_COLLISION_EXAMPLES]
        ]
        strategy_reports[strategy] = {
            "eligible_record_count": eligible,
            "unique_query_count": len(groups),
            "collision_group_count": len(collisions),
            "collision_record_count": collision_record_count,
            "collision_pair_count": collision_pair_count,
            "example_count": len(examples),
            "examples_truncated": max(0, len(collisions) - len(examples)),
            "examples": examples,
        }
    full_stats = strategy_reports["full"]
    for strategy, stats in strategy_reports.items():
        stats["increase_vs_full"] = {
            "collision_group_count": stats["collision_group_count"]
            - full_stats["collision_group_count"],
            "collision_record_count": stats["collision_record_count"]
            - full_stats["collision_record_count"],
            "collision_pair_count": stats["collision_pair_count"]
            - full_stats["collision_pair_count"],
        }
    report["strategies"] = strategy_reports
    return report


def _length_summary(values: Sequence[int]) -> dict[str, Any]:
    counts = Counter(values)
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": round(sum(values) / len(values), 2) if values else None,
        "distribution": {str(length): counts[length] for length in sorted(counts)},
    }


def _failed_pairs(
    raw_dir: Path,
    baseline_probe_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pairs = name_match_probe.ground_truth_pairs(raw_dir)
    by_key = {(pair["plan_id"], pair["expected_spec_no"]): pair for pair in pairs}
    baseline = load_json(baseline_probe_path.resolve())
    if not isinstance(baseline, dict) or not isinstance(baseline.get("results"), list):
        raise ExperimentError("invalid_probe", "기존 name-match probe의 results가 없습니다")

    failures: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for result in baseline["results"]:
        if not isinstance(result, dict) or result.get("hit") is not False:
            continue
        plan_id = result.get("plan_id")
        expected = result.get("expected_spec_no")
        if not isinstance(plan_id, str) or not isinstance(expected, str):
            raise ExperimentError("invalid_probe", "실패 결과의 정답쌍 식별자가 없습니다")
        key = (plan_id, expected)
        if key in seen:
            continue
        seen.add(key)
        pair = by_key.get(key)
        if pair is None:
            raise ExperimentError("probe_pair_missing", "실패 probe와 로컬 정답쌍을 맞출 수 없습니다")
        variants: list[dict[str, Any]] = []
        for strategy, query in name_normalize.search_variants(pair["plan_title"]):
            literal = (
                query in pair["plan_title"]
                if strategy in {"breaking_split", "longest_fragment"}
                else None
            )
            if strategy in {"breaking_split", "longest_fragment"} and not literal:
                raise ExperimentError(
                    "fragment_contract",
                    f"{strategy}가 원문 부분문자열이 아닙니다",
                )
            variants.append(
                {
                    "strategy": strategy,
                    "query": query,
                    "query_length": len(query),
                    "is_literal_substring": literal,
                }
            )
        failures.append(
            {
                "plan_id": pair["plan_id"],
                "expected_spec_no": pair["expected_spec_no"],
                "plan_title": pair["plan_title"],
                "variants": variants,
            }
        )

    by_strategy: dict[str, list[int]] = {strategy: [] for strategy in name_normalize.SEARCH_STRATEGIES}
    total_variants = 0
    for failure in failures:
        total_variants += len(failure["variants"])
        for variant in failure["variants"]:
            by_strategy.setdefault(variant["strategy"], []).append(variant["query_length"])
    breaking_split_rows = [
        {
            "plan_id": failure["plan_id"],
            "expected_spec_no": failure["expected_spec_no"],
            "plan_title": failure["plan_title"],
            "breaking_chars": [
                char
                for char in name_normalize.CONFIRMED_BREAKING_CHARS
                if char in failure["plan_title"]
            ],
            "query": next(
                (
                    variant["query"]
                    for variant in failure["variants"]
                    if variant["strategy"] == "breaking_split"
                ),
                None,
            ),
        }
        for failure in failures
        if any(
            char in failure["plan_title"]
            for char in name_normalize.CONFIRMED_BREAKING_CHARS
        )
    ]
    unexplained_pairs = [
        {
            "plan_id": failure["plan_id"],
            "expected_spec_no": failure["expected_spec_no"],
            "plan_title": failure["plan_title"],
        }
        for failure in failures
        if not any(
            char in failure["plan_title"]
            for char in name_normalize.CONFIRMED_BREAKING_CHARS
        )
    ]
    return failures, {
        "source": baseline_probe_path.resolve().name,
        "schema_version": baseline.get("schema_version"),
        "failed_pair_count": len(failures),
        "total_variant_count": total_variants,
        "query_length_by_strategy": {
            strategy: _length_summary(by_strategy.get(strategy, []))
            for strategy in name_normalize.SEARCH_STRATEGIES
        },
        "breaking_split": {
            "pair_count": len(breaking_split_rows),
            "queries": breaking_split_rows,
        },
        "confirmed_breaking_failure_count": len(breaking_split_rows),
        "unexplained_failure_count": len(unexplained_pairs),
        "unexplained_commonality": {
            "status": "unknown",
            "inference": False,
            "note": "확정 파손 문자 5종으로 설명되지 않는 20건에서 API 호출 없이 공통 원인을 판정하지 않음.",
        },
        "unexplained_pairs": unexplained_pairs,
        "confirmed_breaking_chars": list(name_normalize.CONFIRMED_BREAKING_CHARS),
        "unknown_chars": list(name_normalize.UNKNOWN_CHARS),
        "breaking_split_rationale": (
            "확정 파손 문자만 제거한 가장 긴 연속 부분문자열을 사용해, "
            "longest_fragment보다 무해 문맥을 더 많이 보존한다."
        ),
        "breaking_split_contract": {
            "all_queries_are_source_substrings": True,
            "unknown_u2219_is_not_split": True,
        },
        "pairs": failures,
    }


def _title_comparison(
    raw_dir: Path,
) -> dict[str, Any]:
    plans = _read_items(raw_dir, "order_plan")
    specs = _read_items(raw_dir, "prespec")
    plan_by_id = {item.get("orderPlanUntyNo"): item for item in plans}
    spec_by_id = {item.get("bfSpecRgstNo"): item for item in specs}
    pairs = name_match_probe.ground_truth_pairs(raw_dir)

    rows: list[dict[str, Any]] = []
    categories = Counter()
    for pair in pairs:
        plan = plan_by_id.get(pair["plan_id"])
        spec = spec_by_id.get(pair["expected_spec_no"])
        if not isinstance(plan, dict) or not isinstance(spec, dict):
            continue
        plan_title = _title_value(plan, "bizNm")
        spec_title = _title_value(spec, "prdctClsfcNoNm")
        exact = plan_title == spec_title
        normalized = name_normalize.normalize(plan_title) == name_normalize.normalize(spec_title)
        category = "exact" if exact else "normalized" if normalized else "neither"
        categories[category] += 1
        rows.append(
            {
                "plan_id": pair["plan_id"],
                "expected_spec_no": pair["expected_spec_no"],
                "category": category,
                "plan_title": plan_title,
                "prespec_title": spec_title,
            }
        )
    return {
        "ground_truth_pair_count": len(pairs),
        "local_prespec_pair_count": len(rows),
        "sample_size_note": "로컬 raw에 정답 사전규격이 있는 17쌍 표본만 비교함" if len(rows) == 17 else "로컬 raw에 있는 정답쌍만 비교함",
        "counts": {
            "exact": categories.get("exact", 0),
            "normalized": categories.get("normalized", 0),
            "neither": categories.get("neither", 0),
        },
        "pairs": rows,
    }


def analyse(raw_dir: Path, baseline_probe_path: Path) -> dict[str, Any]:
    """Build the complete offline analysis document without writing files."""

    raw_dir = raw_dir.resolve()
    baseline_probe_path = baseline_probe_path.resolve()
    order_plans = _read_items(raw_dir, "order_plan")
    prespecs = _read_items(raw_dir, "prespec")
    bids = _read_items(raw_dir, "bid")
    _, failure_report = _failed_pairs(raw_dir, baseline_probe_path)
    return {
        "schema_version": ANALYSIS_SCHEMA,
        "created_at": datetime.now(KST).isoformat(),
        "offline_only": True,
        "inputs": {
            "raw_dir": raw_dir.name,
            "baseline_probe": baseline_probe_path.name,
            "order_plan_count": len(order_plans),
            "prespec_count": len(prespecs),
            "bid_count": len(bids),
            "order_plan_items_sha256": digest_json(order_plans),
            "prespec_items_sha256": digest_json(prespecs),
            "bid_items_sha256": digest_json(bids),
        },
        "collision_risk": {
            "order_plan": _collision_report(
                order_plans, "orderPlanUntyNo", "bizNm"
            ),
            "prespec": _collision_report(
                prespecs, "bfSpecRgstNo", "prdctClsfcNoNm"
            ),
        },
        "missed_pair_ladder": failure_report,
        "local_title_comparison": _title_comparison(raw_dir),
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def render_markdown(document: dict[str, Any]) -> str:
    lines = [
        "# 발주계획 사업명 → 사전규격 검색어 오프라인 분석",
        "",
        V4_CHANGE_NOTE,
        "",
        f"수행 시각: {document['created_at']}",
        "",
        "외부 API 호출 없이 동결 raw와 기존 name-match probe만 읽어 계산했다.",
        "",
        "## 입력",
        "",
        f"- 발주계획: {document['inputs']['order_plan_count']}건",
        f"- 사전규격: {document['inputs']['prespec_count']}건",
        f"- 입찰공고: {document['inputs']['bid_count']}건",
        f"- 기존 실패 probe: `{document['missed_pair_ladder']['source']}`",
        "",
        "## (a) 정규화 충돌 위험",
        "",
        "`full`은 원문(공백만 정리한 baseline) 대조군이다. 충돌은 같은 질의에 서로 다른 원천 레코드 ID가 둘 이상 모인 그룹이다. `collision_pair_count`는 그룹 안의 레코드 쌍 수이고, 예시는 최대 10개만 남겼다. 증가분은 각 전략 수치에서 `full` 수치를 뺀 값이다.",
        "따라서 `normalized`의 증가분이 0이면 정규화 자체가 충돌을 늘리지 않았다는 뜻이다. `breaking_split`은 실측으로 확정된 파손 문자만 제거하고 괄호·공백·확정 무해 문자와 미측정 U+2219 문맥을 보존하므로 `longest_fragment`보다 충돌이 적은지 별도로 확인한다. 양수 증가는 fallback 질의에서 생긴 추가 위험으로 읽는다.",
        "",
        "| 대상 | 전략 | 유효 레코드 | 고유 질의 | 충돌 그룹 | full 대비 그룹 증가 | 충돌 레코드 | full 대비 레코드 증가 | 충돌 쌍 | full 대비 쌍 증가 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for target, report in document["collision_risk"].items():
        for strategy, stats in report["strategies"].items():
            lines.append(
                f"| {target} | `{strategy}` | {stats['eligible_record_count']} | {stats['unique_query_count']} | {stats['collision_group_count']} | {stats['increase_vs_full']['collision_group_count']:+d} | {stats['collision_record_count']} | {stats['increase_vs_full']['collision_record_count']:+d} | {stats['collision_pair_count']} | {stats['increase_vs_full']['collision_pair_count']:+d} |"
            )
    lines.extend(["", "### 충돌 사례 예시", ""])
    for target, report in document["collision_risk"].items():
        for strategy, stats in report["strategies"].items():
            lines.append(f"#### {target} · `{strategy}`")
            lines.append("")
            if not stats["examples"]:
                lines.append("충돌 사례 없음.")
                lines.append("")
                continue
            lines.extend(["| 질의 | 레코드 |", "|---|---|"])
            for example in stats["examples"]:
                records = "<br>".join(
                    f"`{_cell(record['record_id'])}` {_cell(record['title'])}"
                    for record in example["records"]
                )
                lines.append(f"| `{_cell(example['query'])}` | {records} |")
            lines.append("")

    ladder = document["missed_pair_ladder"]
    lines.extend(
        [
            f"## (b) 기존 실패쌍 {ladder['failed_pair_count']}건의 사다리",
            "",
            f"기존 probe에서 결과가 없었던 정답쌍은 {ladder['failed_pair_count']}건이다. 아래 질의는 만들기만 했고 실제 호출하지 않았다. 전체 사다리를 실행하면 필요한 호출 수는 중복 제거 후 총 {ladder['total_variant_count']}회다.",
            "",
            "| 전략 | 질의 수 | 최소 길이 | 최대 길이 | 평균 길이 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for strategy, stats in ladder["query_length_by_strategy"].items():
        lines.append(
            f"| `{strategy}` | {stats['count']} | {_cell(stats['min'])} | {_cell(stats['max'])} | {_cell(stats['mean'])} |"
        )
    lines.extend(["", "### 건별 질의", ""])
    for failure in ladder["pairs"]:
        lines.append(
            f"#### `{failure['plan_id']}` → `{failure['expected_spec_no']}`"
        )
        lines.append("")
        lines.append(f"사업명: {_cell(failure['plan_title'])}")
        lines.append("")
        lines.extend(["| 전략 | 길이 | 질의 |", "|---|---:|---|"])
        for variant in failure["variants"]:
            lines.append(
                f"| `{variant['strategy']}` | {variant['query_length']} | `{_cell(variant['query'])}` |"
            )
        lines.append("")

    lines.extend(
        [
            "### 확정 파손 문자 실패쌍의 `breaking_split` 질의",
            "",
            f"확정 파손 문자({', '.join(ladder['confirmed_breaking_chars'])})가 실제로 포함된 실패쌍 {ladder['breaking_split']['pair_count']}건에 대해서만 `breaking_split` 질의를 만들었다.",
            "",
            "| 발주계획 ID | 사전규격 ID | 파손 문자 | 질의 |",
            "|---|---|---|---|",
        ]
    )
    for row in ladder["breaking_split"]["queries"]:
        lines.append(
            f"| `{row['plan_id']}` | `{row['expected_spec_no']}` | `{_cell(' '.join(row['breaking_chars']))}` | `{_cell(row['query'])}` |"
        )
    lines.append("")

    lines.extend(
        [
            f"### 확정 파손 문자로 설명되지 않은 실패 {ladder['unexplained_failure_count']}건",
            "",
            "아래 실패쌍은 현재 실측으로 확정된 파손 문자 5종을 사업명에 포함하지 않는다. 공통 원인은 API 호출 없이 판정하지 않았으며 `unknown`으로 남긴다.",
            "",
            "| 발주계획 ID | 사전규격 ID | 사업명 |",
            "|---|---|---|",
        ]
    )
    for row in ladder["unexplained_pairs"]:
        lines.append(
            f"| `{row['plan_id']}` | `{row['expected_spec_no']}` | {_cell(row['plan_title'])} |"
        )
    lines.extend(
        [
            "",
            f"공통성 판정: `{ladder['unexplained_commonality']['status']}`. "
            f"{ladder['unexplained_commonality']['note']}",
            "",
        ]
    )

    comparison = document["local_title_comparison"]
    lines.extend(
        [
            "## (c) 로컬 raw에서 이름 비교 가능한 정답쌍",
            "",
            f"전체 정답쌍 {comparison['ground_truth_pair_count']}건 중 사전규격 raw에 등록번호가 존재하는 {comparison['local_prespec_pair_count']}건만 비교했다. 이 표본은 17건뿐이며 전체 성능으로 일반화할 수 없다.",
            "",
            "| 분류 | 건수 |",
            "|---|---:|",
            f"| 원문 일치 | {comparison['counts']['exact']} |",
            f"| 원문 불일치지만 정규화 후 일치 | {comparison['counts']['normalized']} |",
            f"| 어느 쪽도 아님 | {comparison['counts']['neither']} |",
            "",
            "### 비교 표본",
            "",
            "| 발주계획 ID | 사전규격 ID | 분류 | 발주계획 사업명 | 사전규격 사업명 |",
            "|---|---|---|---|---|",
        ]
    )
    for row in comparison["pairs"]:
        lines.append(
            f"| `{row['plan_id']}` | `{row['expected_spec_no']}` | {row['category']} | {_cell(row['plan_title'])} | {_cell(row['prespec_title'])} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def _write_markdown_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError as exc:
        raise ExperimentError("artifact_exists", f"기존 리포트를 덮어쓸 수 없습니다: {path.name}") from exc
    except OSError as exc:
        raise ExperimentError("artifact_write_failed", f"리포트를 쓸 수 없습니다: {path.name}") from exc


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument(
        "--baseline-probe",
        "--probe",
        dest="baseline_probe",
        type=Path,
        default=DEFAULT_PROBE,
        help="기존 name-match-probe.json 경로",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        document = analyse(args.raw_dir, args.baseline_probe)
        output_dir = args.output_dir.resolve()
        write_json_new(output_dir / "offline-analysis-v4.json", document)
        _write_markdown_new(output_dir / "offline-analysis-v4.md", render_markdown(document))
        print(
            f"오프라인 분석 완료 · 실패쌍 {document['missed_pair_ladder']['failed_pair_count']}건 ·"
            f" 로컬 이름 비교 {document['local_title_comparison']['local_prespec_pair_count']}건"
        )
        return 0
    except ExperimentError as exc:
        print(f"error[{exc.code}]: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
