#!/usr/bin/env python3
"""Probe an ordered ladder of offline-safe business-name search variants.

The pre-specification service has no observed order-plan key.  This experiment
therefore tries the conservative variants from :mod:`name_normalize` in order
and grades every response against the ground-truth pair obtained through a bid
notice.  The ground-truth join and the HTTP search/grading functions are
intentionally reused from ``name_match_probe.py``; this script only adds the
strategy ladder and a response cache.

No request is made unless ``--execute`` is supplied.  ``--offline`` still
requires that explicit safety acknowledgement, but it never has a network
fetcher and records a cache miss as an incomplete attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parents[1] / "order-plan-screening" / "scripts"))
sys.path.insert(0, str(_SCRIPT_DIR))

from common import ExperimentError, load_json, write_json_new  # noqa: E402
from endpoints import KST  # noqa: E402
import name_match_probe as baseline_probe  # noqa: E402
import name_normalize  # noqa: E402
import survey  # noqa: E402


PROBE_SCHEMA = "bidops.lifecycle-name-strategy-probe.v1"
CACHE_SCHEMA = "bidops.lifecycle-name-search-cache.v1"
SEARCH_STRATEGIES = name_normalize.SEARCH_STRATEGIES

# Public aliases make the reuse explicit to callers and tests.  The functions
# themselves remain owned by name_match_probe.py, so the two probes cannot
# silently acquire different ground-truth or grading rules.
ground_truth_pairs = baseline_probe.ground_truth_pairs
search_by_name = baseline_probe.search_by_name
grade = baseline_probe.grade


class CacheMiss(ExperimentError):
    """A cache-only lookup had no stored response."""

    def __init__(self) -> None:
        super().__init__("cache_miss", "응답 캐시에 없는 질의입니다")


def _query_string(public_query: dict[str, str]) -> str:
    """Serialize exactly the public part of the request, never the API key."""

    if "serviceKey" in public_query:
        raise ExperimentError("secret_stored", "공개 query에 인증키 필드가 있습니다")
    return urllib.parse.urlencode(public_query)


def _cache_identity(url: str, query_string: str) -> str:
    value = f"{url}?{query_string}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False


class ResponseCache:
    """Immutable JSON response cache keyed by URL plus public query string."""

    def __init__(self, directory: Path):
        self.directory = directory.resolve()

    def _path(self, url: str, public_query: dict[str, str]) -> tuple[Path, str]:
        query_string = _query_string(public_query)
        identity = _cache_identity(url, query_string)
        return self.directory / f"{identity}.json", query_string

    def read(
        self,
        url: str,
        public_query: dict[str, str],
        service_key: str = "",
    ) -> dict[str, Any] | None:
        path, query_string = self._path(url, public_query)
        if not path.exists():
            return None
        document = load_json(path)
        if not isinstance(document, dict):
            raise ExperimentError("cache_invalid", "응답 캐시가 object가 아닙니다")
        if document.get("schema_version") != CACHE_SCHEMA:
            raise ExperimentError("cache_invalid", "응답 캐시 schema가 다릅니다")
        if document.get("url") != url or document.get("query_string") != query_string:
            raise ExperimentError("cache_key_mismatch", "응답 캐시 키가 질의와 다릅니다")
        if document.get("cache_key") != _cache_identity(url, query_string):
            raise ExperimentError("cache_key_mismatch", "응답 캐시 digest가 질의와 다릅니다")
        if _contains_key(document, "serviceKey"):
            raise ExperimentError("secret_stored", "응답 캐시에 인증키 필드가 있습니다")
        if service_key and service_key in query_string:
            raise ExperimentError("secret_stored", "응답 캐시에 인증정보가 있습니다")
        response = document.get("response")
        if not isinstance(response, dict):
            raise ExperimentError("cache_invalid", "응답 캐시의 response가 object가 아닙니다")
        if service_key and service_key in json.dumps(response, ensure_ascii=False):
            raise ExperimentError("secret_stored", "응답 캐시에 인증정보가 있습니다")
        return response

    def write(
        self,
        url: str,
        public_query: dict[str, str],
        response: dict[str, Any],
        service_key: str = "",
    ) -> None:
        if _contains_key(response, "serviceKey"):
            raise ExperimentError("secret_stored", "응답 캐시에 인증키 필드를 저장할 수 없습니다")
        encoded = json.dumps(response, ensure_ascii=False)
        if service_key and service_key in encoded:
            raise ExperimentError("secret_stored", "응답 캐시에 인증정보를 저장할 수 없습니다")
        path, query_string = self._path(url, public_query)
        if service_key and service_key in query_string:
            raise ExperimentError("secret_stored", "응답 캐시에 인증 query를 저장할 수 없습니다")
        write_json_new(
            path,
            {
                "schema_version": CACHE_SCHEMA,
                "cache_key": _cache_identity(url, query_string),
                "url": url,
                "query_string": query_string,
                "response": response,
            },
        )


class CachedFetcher:
    """Adapter with the SurveyFetcher interface and an immutable response cache."""

    def __init__(
        self,
        cache: ResponseCache,
        delegate: survey.SurveyFetcher | None = None,
        *,
        offline: bool = False,
    ):
        if not offline and delegate is None:
            raise ExperimentError("invalid_fetcher", "온라인 cache fetcher에는 delegate가 필요합니다")
        self.cache = cache
        self.delegate = delegate
        self.offline = offline
        self.cache_hits = 0
        self.cache_misses = 0
        self.last_cache_hit = False

    @property
    def request_count(self) -> int:
        return self.delegate.request_count if self.delegate is not None else 0

    def fetch(
        self,
        url: str,
        public_query: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        service_key = self.delegate.service_key if self.delegate is not None else ""
        cached = self.cache.read(url, public_query, service_key)
        if cached is not None:
            self.cache_hits += 1
            self.last_cache_hit = True
            return cached, 0
        self.cache_misses += 1
        self.last_cache_hit = False
        if self.offline or self.delegate is None:
            raise CacheMiss()
        response, attempts = self.delegate.fetch(url, public_query)
        self.cache.write(url, public_query, response, self.delegate.service_key)
        return response, attempts


def _missed_keys(path: Path) -> set[tuple[str, str | None]]:
    document = load_json(path.resolve())
    if not isinstance(document, dict) or not isinstance(document.get("results"), list):
        raise ExperimentError("invalid_probe", "기존 name-match probe의 results가 없습니다")
    keys: set[tuple[str, str | None]] = set()
    for row in document["results"]:
        if not isinstance(row, dict) or row.get("hit") is not False:
            continue
        plan_id = row.get("plan_id")
        expected = row.get("expected_spec_no")
        if not isinstance(plan_id, str) or not plan_id.strip():
            raise ExperimentError("invalid_probe", "실패 결과에 plan_id가 없습니다")
        if expected is not None and (not isinstance(expected, str) or not expected.strip()):
            raise ExperimentError("invalid_probe", "실패 결과의 expected_spec_no가 잘못됐습니다")
        keys.add((plan_id.strip(), expected.strip() if isinstance(expected, str) else None))
    return keys


def select_pairs(
    pairs: Sequence[dict[str, str]],
    only_missed: Path | None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if only_missed is None:
        return list(pairs), {"enabled": False, "source": None, "failure_count": None}
    missed = _missed_keys(only_missed)
    selected: list[dict[str, str]] = []
    for pair in pairs:
        if any(
            pair["plan_id"] == plan_id
            and (expected is None or pair["expected_spec_no"] == expected)
            for plan_id, expected in missed
        ):
            selected.append(pair)
    selected_keys = {(pair["plan_id"], pair["expected_spec_no"]) for pair in selected}
    unresolved = {
        (plan_id, expected)
        for plan_id, expected in missed
        if not any(
            pair["plan_id"] == plan_id
            and (expected is None or pair["expected_spec_no"] == expected)
            for pair in pairs
        )
    }
    if unresolved:
        raise ExperimentError("probe_pair_missing", "기존 실패 probe와 정답쌍을 맞출 수 없습니다")
    return selected, {
        "enabled": True,
        "source": only_missed.resolve().name,
        "failure_count": len(missed),
        "selected_pair_count": len(selected_keys),
    }


def probe_pair(
    pair: dict[str, str],
    fetcher: Any,
    from_date: date,
    to_date: date,
    rows: int,
) -> dict[str, Any]:
    """Try one pair until the first graded hit, retaining cache failures."""

    attempts: list[dict[str, Any]] = []
    first_hit: dict[str, Any] | None = None
    cache_miss_count = 0
    for strategy, query in name_normalize.search_variants(pair["plan_title"]):
        try:
            total, items = search_by_name(fetcher, query, from_date, to_date, rows)
        except CacheMiss:
            cache_miss_count += 1
            attempts.append(
                {
                    "strategy": strategy,
                    "query": query,
                    "query_length": len(query),
                    "status": "cache_miss",
                    "result_count": None,
                    "returned_count": None,
                    "hit": None,
                    "unique_hit": None,
                    "agency_matches": None,
                    "returned_spec_nos": [],
                    "cache_hit": False,
                }
            )
            continue
        graded = grade(pair, total, items)
        attempt = {
            "strategy": strategy,
            "query": query,
            "query_length": len(query),
            "status": "ok",
            "result_count": graded["result_count"],
            "returned_count": graded["returned_count"],
            "hit": graded["hit"],
            "unique_hit": graded["unique_hit"],
            "agency_matches": graded["agency_matches"],
            "returned_spec_nos": graded["returned_spec_nos"],
            "cache_hit": bool(getattr(fetcher, "last_cache_hit", False)),
        }
        attempts.append(attempt)
        if graded["hit"]:
            first_hit = attempt
            break

    if first_hit is not None:
        status = "hit" if cache_miss_count == 0 else "hit_with_cache_miss"
    elif cache_miss_count:
        status = "cache_miss"
    else:
        status = "miss"
    return {
        "plan_id": pair["plan_id"],
        "plan_title": pair["plan_title"],
        "expected_spec_no": pair["expected_spec_no"],
        "first_hit_strategy": first_hit["strategy"] if first_hit else None,
        "hit": first_hit is not None,
        "unique_hit": bool(first_hit and first_hit["unique_hit"]),
        "agency_matches": bool(first_hit and first_hit["agency_matches"]),
        "status": status,
        "attempt_count": len(attempts),
        "cache_miss_count": cache_miss_count,
        "attempts": attempts,
    }


def _empty_strategy_summary() -> dict[str, Any]:
    return {
        "attempt_count": 0,
        "hit_count": 0,
        "cumulative_hit_count": 0,
        "cumulative_recall": None,
        "empty_result_count": 0,
        "result_count_distribution": {},
        "unknown_result_count": 0,
        "cache_hit_count": 0,
        "cache_miss_count": 0,
    }


def summarise_strategies(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Summarize first hits and result distributions for each ladder rung."""

    summary = {strategy: _empty_strategy_summary() for strategy in SEARCH_STRATEGIES}
    pair_count = len(rows)
    for row in rows:
        for attempt in row["attempts"]:
            strategy = attempt["strategy"]
            if strategy not in summary:
                summary[strategy] = _empty_strategy_summary()
            stats = summary[strategy]
            stats["attempt_count"] += 1
            if attempt["status"] == "cache_miss":
                stats["cache_miss_count"] += 1
                stats["unknown_result_count"] += 1
                continue
            if attempt.get("cache_hit"):
                stats["cache_hit_count"] += 1
            result_count = attempt["result_count"]
            if result_count is None:
                stats["unknown_result_count"] += 1
            else:
                key = str(result_count)
                distribution = stats["result_count_distribution"]
                distribution[key] = distribution.get(key, 0) + 1
                if result_count == 0:
                    stats["empty_result_count"] += 1
            if attempt["hit"]:
                stats["hit_count"] += 1
    cumulative = 0
    for strategy in SEARCH_STRATEGIES:
        stats = summary[strategy]
        cumulative += stats["hit_count"]
        stats["cumulative_hit_count"] = cumulative
        stats["cumulative_recall"] = round(cumulative / pair_count, 4) if pair_count else None
        stats["result_count_distribution"] = dict(
            sorted(stats["result_count_distribution"].items(), key=lambda pair: int(pair[0]))
        )
    return {
        "pair_count": pair_count,
        "hit_count": sum(1 for row in rows if row["hit"]),
        "hit_rate": round(sum(1 for row in rows if row["hit"]) / pair_count, 4)
        if pair_count
        else None,
        "unique_hit_count": sum(1 for row in rows if row["unique_hit"]),
        "cache_incomplete_pair_count": sum(1 for row in rows if row["cache_miss_count"]),
        "strategies": summary,
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
    parser.add_argument(
        "--only-missed",
        type=Path,
        help="기존 name-match-probe.json에서 hit=false인 정답쌍만 검사합니다",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="응답 캐시 디렉터리(기본: output-dir/cache)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="캐시만 사용하고 캐시 미스는 실패 attempt로 남깁니다",
    )
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
        if not args.run_id.strip() or any(part in args.run_id for part in ("/", "\\", "..")):
            raise ExperimentError("invalid_run_id", "run_id가 안전하지 않습니다")
        if args.limit < 1:
            raise ExperimentError("invalid_limit", "limit는 1 이상이어야 합니다")
        pairs = ground_truth_pairs(args.raw_dir.resolve())
        if not pairs:
            raise ExperimentError("no_ground_truth", "정답쌍을 만들 수 없습니다")
        pairs, selection = select_pairs(pairs, args.only_missed)
        pairs = pairs[: args.limit]
        if not pairs:
            raise ExperimentError("no_selected_pairs", "검사할 정답쌍이 없습니다")

        output_dir = args.output_dir.resolve()
        cache = ResponseCache((args.cache_dir or output_dir / "cache").resolve())
        if args.offline:
            fetcher: Any = CachedFetcher(cache, offline=True)
        else:
            delegate = survey.SurveyFetcher(
                survey.get_service_key(), timeout=args.timeout, max_attempts=args.max_attempts
            )
            fetcher = CachedFetcher(cache, delegate)

        rows: list[dict[str, Any]] = []
        for index, pair in enumerate(pairs, start=1):
            rows.append(
                probe_pair(pair, fetcher, args.from_date, args.to_date, args.rows)
            )
            if index % 20 == 0:
                print(f"  {index}/{len(pairs)} 진행", file=sys.stderr)

        document = {
            "schema_version": PROBE_SCHEMA,
            "run_id": args.run_id,
            "created_at": datetime.now(KST).isoformat(),
            "search_field": baseline_probe.SEARCH_FIELD,
            "search_window": {
                "from": args.from_date.isoformat(),
                "to_exclusive": args.to_date.isoformat(),
            },
            "selection": selection,
            "cache": {
                "directory": cache.directory.name,
                "offline": args.offline,
                "cache_hit_count": fetcher.cache_hits,
                "cache_miss_count": fetcher.cache_misses,
            },
            "request_count": fetcher.request_count,
            "summary": summarise_strategies(rows),
            "results": rows,
        }
        write_json_new(output_dir / "name-strategy-probe.json", document)
        summary = document["summary"]
        print(
            f"정답쌍 {summary['pair_count']}건 · 누적 적중 {summary['hit_count']}"
            f" ({(summary['hit_rate'] or 0) * 100:.1f}%) ·"
            f" 캐시미스 {summary['cache_incomplete_pair_count']}쌍"
        )
        return 0
    except ExperimentError as exc:
        print(f"error[{exc.code}]: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
