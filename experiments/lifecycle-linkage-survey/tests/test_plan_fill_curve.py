"""Offline contract tests for the cross-sectional plan fill curve."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from helpers import FakeOpener, page_payload

from common import ExperimentError  # noqa: E402
import plan_fill_curve as curve  # noqa: E402
import survey  # noqa: E402
from endpoints import KST  # noqa: E402


OBSERVED_AT = datetime(2026, 8, 29, 12, 0, tzinfo=KST)


class PlanFillCurveTests(unittest.TestCase):
    def _fetcher(self, opener: FakeOpener, request_limit: int = 40) -> survey.SurveyFetcher:
        return survey.SurveyFetcher(
            "test-service-key",
            timeout=1,
            max_attempts=1,
            opener=opener,
            sleeper=lambda _seconds: None,
            request_limit=request_limit,
        )

    def test_default_windows_use_inclusive_end_date_for_age(self) -> None:
        ages = [
            curve.calculate_window_metrics(window, [], OBSERVED_AT)["age_days"]
            for window in curve.DEFAULT_WINDOWS
        ]

        self.assertEqual(ages, [3, 17, 31, 57, 87, 148])

    def test_no_execute_stops_before_constructing_a_fetcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            with mock.patch.object(
                curve.survey,
                "get_service_key",
                side_effect=AssertionError("must not read API key"),
            ), mock.patch.object(
                curve.survey,
                "SurveyFetcher",
                side_effect=AssertionError("must not construct fetcher"),
            ):
                exit_code = curve.main(["--output-dir", str(output)])

        self.assertEqual(exit_code, 2)
        self.assertFalse(output.exists())

    def test_each_window_and_each_extra_page_is_fetched_once(self) -> None:
        windows = (
            curve.Window(date(2026, 8, 24), date(2026, 8, 27)),
            curve.Window(date(2026, 8, 10), date(2026, 8, 13)),
        )
        opener = FakeOpener(
            [
                page_payload(
                    [{"orderPlanUntyNo": "R1", "bidNtceNoList": ""}],
                    total=2,
                    page_no=1,
                    rows=1,
                ),
                page_payload(
                    [{"orderPlanUntyNo": "R2", "bidNtceNoList": "B2"}],
                    total=2,
                    page_no=2,
                    rows=1,
                ),
                page_payload(
                    [{"orderPlanUntyNo": "R3", "bidNtceNoList": "B3"}],
                    total=1,
                    page_no=1,
                    rows=1,
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            document = curve.collect_curve(
                windows,
                Path(directory) / "out",
                rows=1,
                max_requests=3,
                observed_at=OBSERVED_AT,
                fetcher=self._fetcher(opener, 3),
            )

        self.assertEqual(len(opener.urls), 3)
        self.assertEqual(document["request_count"], 3)
        self.assertEqual(document["page_count"], 3)
        self.assertEqual(document["window_count"], 2)
        self.assertEqual(
            [row["total_count"] for row in document["windows"]], [2, 1]
        )

    def test_fill_rates_treat_null_empty_and_whitespace_as_unfilled(self) -> None:
        window = curve.Window(date(2026, 8, 24), date(2026, 8, 27))
        items = [
            {"bidNtceNoList": "", "ntceNticeYn": "Y", "chgDt": "", "nticeDt": "2026-08-24 00:00:00"},
            {"bidNtceNoList": "   ", "ntceNticeYn": "N", "chgDt": "  ", "nticeDt": "2026-08-24 00:00:00"},
            {"bidNtceNoList": None, "ntceNticeYn": "Y", "chgDt": None, "nticeDt": "2026-08-24 00:00:00"},
            {
                "bidNtceNoList": "B1, B2",
                "ntceNticeYn": "Y",
                "chgDt": "2026-08-24 12:00:00",
                "nticeDt": "2026-08-24 00:00:00",
            },
        ]

        metrics = curve.calculate_window_metrics(window, items, OBSERVED_AT)

        self.assertEqual(metrics["total_count"], 4)
        self.assertEqual(metrics["bidNtceNoList"]["filled_count"], 1)
        self.assertEqual(metrics["bidNtceNoList"]["fill_rate"], 0.25)
        self.assertEqual(metrics["bidNtceNoList"]["notice_number_total"], 2)
        self.assertEqual(metrics["bidNtceNoList"]["multi_notice_record_count"], 1)
        self.assertEqual(metrics["bidNtceNoList"]["count_distribution"], {"0": 3, "2": 1})
        self.assertEqual(metrics["ntceNticeYn"]["y_rate"], 0.75)
        self.assertEqual(metrics["chgDt"]["fill_rate"], 0.25)
        self.assertEqual(metrics["chgDt_minus_nticeDt"]["available_count"], 1)
        self.assertEqual(metrics["chgDt_minus_nticeDt"]["p50_days"], 0.5)

    def test_age_is_based_on_observation_date_and_inclusive_end_date(self) -> None:
        window = curve.Window(date(2026, 8, 24), date(2026, 8, 27))

        metrics = curve.calculate_window_metrics(window, [], OBSERVED_AT)

        self.assertEqual(metrics["age_days"], 3)
        self.assertEqual(metrics["window"]["to_inclusive"], "2026-08-26")

    def test_request_budget_fails_before_the_first_fetch(self) -> None:
        windows = (
            curve.Window(date(2026, 8, 24), date(2026, 8, 27)),
            curve.Window(date(2026, 8, 10), date(2026, 8, 13)),
        )
        opener = FakeOpener([])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ExperimentError) as error:
                curve.collect_curve(
                    windows,
                    Path(directory) / "out",
                    max_requests=1,
                    observed_at=OBSERVED_AT,
                    fetcher=self._fetcher(opener, 1),
                )

        self.assertEqual(error.exception.code, "request_budget_too_small")
        self.assertEqual(opener.urls, [])

    def test_from_raw_recalculation_matches_the_collected_metrics(self) -> None:
        window = (curve.Window(date(2026, 8, 24), date(2026, 8, 27)),)
        payload = page_payload(
            [
                {
                    "orderPlanUntyNo": "R1",
                    "bidNtceNoList": "B1, B2",
                    "ntceNticeYn": "Y",
                    "chgDt": "2026-08-24 12:00:00",
                    "nticeDt": "2026-08-24 00:00:00",
                    "ofclNm": "홍길동",
                    "telNo": "02-0000-0000",
                }
            ]
        )
        opener = FakeOpener([payload])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = curve.collect_curve(
                window,
                root / "live",
                observed_at=OBSERVED_AT,
                fetcher=self._fetcher(opener),
            )
            with mock.patch.object(
                curve.survey,
                "SurveyFetcher",
                side_effect=AssertionError("from-raw must not construct fetcher"),
            ):
                replay = curve.recompute_from_raw(
                    root / "live" / "raw", root / "replay"
                )
            output_json = (root / "live" / curve.OUTPUT_JSON).read_text(encoding="utf-8")
            output_md = (root / "live" / curve.OUTPUT_MARKDOWN).read_text(encoding="utf-8")
            replay_json = json.loads(
                (root / "replay" / curve.OUTPUT_JSON).read_text(encoding="utf-8")
            )

        self.assertEqual(replay["windows"], live["windows"])
        self.assertEqual(replay["request_count"], live["request_count"])
        self.assertEqual(replay["observed_at"], live["observed_at"])
        self.assertNotIn("홍길동", output_json)
        self.assertNotIn("02-0000-0000", output_json)
        self.assertNotIn("홍길동", output_md)
        self.assertNotIn("02-0000-0000", output_md)

        self.assertEqual(replay_json["mode"], "from_raw")


if __name__ == "__main__":
    unittest.main()
