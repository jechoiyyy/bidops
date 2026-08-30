"""Offline checks for the order-plan to pre-specification name probe."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from helpers import make_fetcher, page_payload

from common import ExperimentError  # noqa: E402
from endpoints import ENDPOINTS  # noqa: E402
import name_match_probe as probe  # noqa: E402
import survey  # noqa: E402


def build_raw(root: Path, plans, bids) -> Path:
    raw = root / "raw"
    survey.collect_pages(
        ENDPOINTS["order_plan"], raw / "order_plan", date(2026, 8, 24), date(2026, 8, 27), 500,
        make_fetcher([page_payload(plans)]),
    )
    survey.collect_pages(
        ENDPOINTS["bid"], raw / "bid", date(2026, 8, 25), date(2026, 8, 28), 500,
        make_fetcher([page_payload(bids)]),
    )
    return raw


class GroundTruthTests(unittest.TestCase):
    def test_pairs_join_plan_to_spec_through_the_notice(self) -> None:
        plans = [
            {
                "orderPlanUntyNo": "R26DD1",
                "bizNm": " 상수도 정비 용역 ",
                "orderInsttNm": "가기관",
                # 16 characters: the 13-character notice number plus its ordinal.
                "bidNtceNoList": "R26BK00000000001",
            }
        ]
        bids = [{"bidNtceNo": "R26BK00000000", "bfSpecRgstNo": "R26BD9"}]
        with tempfile.TemporaryDirectory() as directory:
            raw = build_raw(Path(directory), plans, bids)

            pairs = probe.ground_truth_pairs(raw)

            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0]["plan_id"], "R26DD1")
            self.assertEqual(pairs[0]["expected_spec_no"], "R26BD9")
            self.assertEqual(pairs[0]["plan_title"], "상수도 정비 용역")

    def test_a_notice_without_a_spec_number_makes_no_pair(self) -> None:
        plans = [{"orderPlanUntyNo": "R1", "bizNm": "가", "bidNtceNoList": "R26BK00000000001"}]
        bids = [{"bidNtceNo": "R26BK00000000", "bfSpecRgstNo": ""}]
        with tempfile.TemporaryDirectory() as directory:
            raw = build_raw(Path(directory), plans, bids)

            self.assertEqual(probe.ground_truth_pairs(raw), [])

    def test_a_plan_without_a_notice_makes_no_pair(self) -> None:
        plans = [{"orderPlanUntyNo": "R1", "bizNm": "가", "bidNtceNoList": ""}]
        bids = [{"bidNtceNo": "R26BK00000000", "bfSpecRgstNo": "R26BD9"}]
        with tempfile.TemporaryDirectory() as directory:
            raw = build_raw(Path(directory), plans, bids)

            self.assertEqual(probe.ground_truth_pairs(raw), [])


class GradingTests(unittest.TestCase):
    PAIR = {
        "plan_id": "R1",
        "plan_title": "상수도 정비 용역",
        "plan_agency": "가기관",
        "bid_no": "R26BK00000000",
        "expected_spec_no": "R26BD9",
    }

    def test_a_single_correct_result_is_a_unique_hit(self) -> None:
        row = probe.grade(
            self.PAIR, 1, [{"bfSpecRgstNo": "R26BD9", "orderInsttNm": "가기관"}]
        )

        self.assertTrue(row["hit"])
        self.assertTrue(row["unique_hit"])
        self.assertTrue(row["agency_matches"])

    def test_a_correct_result_among_several_is_not_unique(self) -> None:
        row = probe.grade(
            self.PAIR,
            2,
            [
                {"bfSpecRgstNo": "R26BD9", "orderInsttNm": "가기관"},
                {"bfSpecRgstNo": "R26BD8", "orderInsttNm": "나기관"},
            ],
        )

        self.assertTrue(row["hit"])
        self.assertFalse(row["unique_hit"])

    def test_a_wrong_result_is_graded_against_truth_not_its_own_guess(self) -> None:
        row = probe.grade(
            self.PAIR, 1, [{"bfSpecRgstNo": "R26BD7", "orderInsttNm": "가기관"}]
        )

        self.assertFalse(row["hit"])
        self.assertFalse(row["unique_hit"])

    def test_an_empty_result_is_a_miss(self) -> None:
        row = probe.grade(self.PAIR, 0, [])

        self.assertFalse(row["hit"])
        self.assertEqual(row["result_count"], 0)
        self.assertFalse(row["agency_matches"])


class SummaryTests(unittest.TestCase):
    def test_rates_are_computed_over_every_pair(self) -> None:
        rows = [
            {"hit": True, "unique_hit": True, "result_count": 1, "agency_matches": True},
            {"hit": True, "unique_hit": False, "result_count": 2, "agency_matches": True},
            {"hit": False, "unique_hit": False, "result_count": 0, "agency_matches": False},
            {"hit": False, "unique_hit": False, "result_count": 3, "agency_matches": False},
        ]

        summary = probe.summarise(rows)

        self.assertEqual(summary["pair_count"], 4)
        self.assertEqual(summary["hit_count"], 2)
        self.assertEqual(summary["hit_rate"], 0.5)
        self.assertEqual(summary["unique_hit_count"], 1)
        self.assertEqual(summary["empty_result_count"], 1)
        self.assertEqual(summary["agency_match_count"], 2)

    def test_an_empty_probe_reports_no_rate_instead_of_zero(self) -> None:
        summary = probe.summarise([])

        self.assertEqual(summary["pair_count"], 0)
        self.assertIsNone(summary["hit_rate"])


class SearchTests(unittest.TestCase):
    def test_the_business_name_is_sent_as_the_search_field(self) -> None:
        fetcher = make_fetcher([page_payload([{"bfSpecRgstNo": "R26BD9"}])])

        total, items = probe.search_by_name(
            fetcher, "상수도 정비 용역", date(2025, 8, 29), date(2026, 8, 29), 50
        )

        self.assertEqual(total, 1)
        self.assertEqual(items[0]["bfSpecRgstNo"], "R26BD9")
        self.assertIn("prdctClsfcNoNm=", fetcher.opener.urls[0])

    def test_the_probe_does_nothing_without_explicit_execute(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"

            exit_code = probe.main(
                [
                    "--run-id", "t1",
                    "--raw-dir", directory,
                    "--output-dir", str(output),
                ]
            )

            self.assertEqual(exit_code, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
