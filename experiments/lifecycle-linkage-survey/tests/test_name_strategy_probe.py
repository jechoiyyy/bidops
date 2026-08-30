"""Offline contract tests for the name-strategy probe and response cache."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from helpers import make_fetcher, page_payload

import name_strategy_probe as probe  # noqa: E402


FROM_DATE = date(2026, 1, 1)
TO_DATE = date(2026, 8, 29)
PAIR = {
    "plan_id": "R1",
    "plan_title": "가나다라마바사 사업(세부)",
    "plan_agency": "가기관",
    "bid_no": "R26BK00000000",
    "expected_spec_no": "R26BD9",
}


class CacheTests(unittest.TestCase):
    def test_a_cache_hit_does_not_call_the_fetcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = probe.ResponseCache(Path(directory) / "cache")
            first_delegate = make_fetcher(
                [page_payload([{"bfSpecRgstNo": "R26BD9"}])]
            )
            first = probe.CachedFetcher(cache, first_delegate)
            probe.search_by_name(
                first, "캐시 확인 사업", FROM_DATE, TO_DATE, 50
            )

            second_delegate = make_fetcher([])
            second = probe.CachedFetcher(cache, second_delegate)
            total, items = probe.search_by_name(
                second, "캐시 확인 사업", FROM_DATE, TO_DATE, 50
            )

            self.assertEqual(total, 1)
            self.assertEqual(items[0]["bfSpecRgstNo"], "R26BD9")
            self.assertEqual(second.cache_hits, 1)
            self.assertEqual(second_delegate.opener.urls, [])
            cache_files = list((Path(directory) / "cache").glob("*.json"))
            self.assertEqual(len(cache_files), 1)
            self.assertNotIn("serviceKey", cache_files[0].read_text(encoding="utf-8"))

    def test_offline_cache_miss_is_retained_as_a_failed_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fetcher = probe.CachedFetcher(
                probe.ResponseCache(Path(directory) / "cache"), offline=True
            )

            row = probe.probe_pair(PAIR, fetcher, FROM_DATE, TO_DATE, 50)

            self.assertEqual(row["status"], "cache_miss")
            self.assertFalse(row["hit"])
            self.assertTrue(row["attempts"])
            self.assertTrue(all(item["status"] == "cache_miss" for item in row["attempts"]))
            self.assertEqual(fetcher.request_count, 0)


class StrategyTests(unittest.TestCase):
    def test_ladder_stops_at_the_first_hit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fetcher = probe.CachedFetcher(
                probe.ResponseCache(Path(directory) / "cache"),
                make_fetcher(
                    [
                        page_payload([], total=0),
                        page_payload([{"bfSpecRgstNo": "R26BD9", "orderInsttNm": "가기관"}]),
                    ]
                ),
            )

            row = probe.probe_pair(PAIR, fetcher, FROM_DATE, TO_DATE, 50)

        self.assertEqual(row["first_hit_strategy"], "normalized")
        self.assertTrue(row["hit"])
        self.assertEqual([item["strategy"] for item in row["attempts"]], ["full", "normalized"])

    def test_execution_gate_stops_without_execute(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"

            exit_code = probe.main(
                [
                    "--run-id",
                    "t1",
                    "--raw-dir",
                    directory,
                    "--output-dir",
                    str(output),
                ]
            )

            self.assertEqual(exit_code, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
