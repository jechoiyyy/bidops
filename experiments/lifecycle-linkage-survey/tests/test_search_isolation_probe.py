"""Offline tests for the six-query search isolation probe."""

from __future__ import annotations

import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from helpers import FakeOpener, page_payload

from common import ExperimentError  # noqa: E402
import search_isolation_probe as probe  # noqa: E402
import survey  # noqa: E402
from endpoints import ENDPOINTS  # noqa: E402


class SearchIsolationTests(unittest.TestCase):
    def _factory(self, opener: FakeOpener):
        def factory(quote_via):
            return survey.SurveyFetcher(
                "test-service-key",
                timeout=1,
                max_attempts=1,
                opener=opener,
                sleeper=lambda _seconds: None,
                quote_via=quote_via,
            )

        return factory

    def test_six_variants_are_called_in_order_and_expected_is_found(self) -> None:
        opener = FakeOpener(
            [
                page_payload(
                    [{"bfSpecRgstNo": probe.DEFAULT_EXPECTED_SPEC_NO}]
                )
                for _ in range(6)
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            document = probe.run_probe(
                probe.DEFAULT_NAME,
                probe.DEFAULT_EXPECTED_SPEC_NO,
                probe.DEFAULT_FROM_DATE,
                probe.DEFAULT_TO_DATE,
                Path(directory) / "out",
                fetcher_factory=self._factory(opener),
            )

            self.assertEqual(len(opener.urls), 6)
            self.assertEqual(document["request_count"], 6)
            self.assertEqual(
                [row["strategy"] for row in document["variants"]],
                [
                    "full_quote_plus",
                    "token",
                    "token_with_space",
                    "middle_dot",
                    "parentheses",
                    "full_quote_percent20",
                ],
            )
            self.assertTrue(all(row["expected_found"] for row in document["variants"]))

            parsed_names = [
                urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)[
                    "prdctClsfcNoNm"
                ][0]
                for url in opener.urls
            ]
            self.assertEqual(
                parsed_names,
                [
                    probe.DEFAULT_NAME,
                    "디지털새싹",
                    "2026 디지털새싹",
                    "개발·제작",
                    "용역(하반기)",
                    probe.DEFAULT_NAME,
                ],
            )

    def test_percent20_variant_is_not_plus_encoded(self) -> None:
        opener = FakeOpener([page_payload([]) for _ in range(6)])
        with tempfile.TemporaryDirectory() as directory:
            probe.run_probe(
                probe.DEFAULT_NAME,
                probe.DEFAULT_EXPECTED_SPEC_NO,
                probe.DEFAULT_FROM_DATE,
                probe.DEFAULT_TO_DATE,
                Path(directory) / "out",
                fetcher_factory=self._factory(opener),
            )

        plus_query = urllib.parse.urlsplit(opener.urls[0]).query
        percent_query = urllib.parse.urlsplit(opener.urls[5]).query
        self.assertIn("+", plus_query)
        self.assertIn("%20", percent_query)
        self.assertNotIn("+", percent_query.split("prdctClsfcNoNm=", 1)[1].split("&", 1)[0])

    def test_raw_and_result_metadata_do_not_store_service_key(self) -> None:
        opener = FakeOpener([page_payload([]) for _ in range(6)])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            document = probe.run_probe(
                probe.DEFAULT_NAME,
                probe.DEFAULT_EXPECTED_SPEC_NO,
                probe.DEFAULT_FROM_DATE,
                probe.DEFAULT_TO_DATE,
                output,
                fetcher_factory=self._factory(opener),
            )
            # The runner itself returns the safe metadata; raw pages are the
            # only files written by run_probe and are all public-query pages.
            self.assertTrue(document["variants"])
            self.assertNotIn("serviceKey", str(document))
            self.assertNotIn("test-service-key", str(document))
            for path in (output / "raw").glob("*.json"):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("serviceKey", text)
                self.assertNotIn("test-service-key", text)

    def test_no_execute_stops_before_creating_or_fetching(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            with mock.patch.object(
                probe.survey, "get_service_key", side_effect=AssertionError("must not read key")
            ):
                exit_code = probe.main(
                    ["--output-dir", str(output)]
                )

            self.assertEqual(exit_code, 2)
            self.assertFalse(output.exists())

    def test_char_tolerance_makes_probe_and_control_pairs(self) -> None:
        # U+2219 is deliberately absent from this local fixture, exercising
        # the required "only present characters" selection rule.
        targets = [
            target
            for target in probe.CHAR_TOLERANCE_TARGETS
            if target.display != "∙"
        ]
        items = []
        for index, target in enumerate(targets, start=1):
            # 대조군은 대상 문자를 뗀 뒤에도 원문의 연속 부분문자열이어야 하고
            # TOLERANCE_MIN_CONTROL_CHARS(6자)를 채워야 한다. 양옆을 그만큼 준다.
            if len(target.chars) == 1:
                name = f"가나다라마바사{target.display}아자차카타파하"
            else:
                name = "가나다라마바사『내용가나다라마바사』아자차카타파하"
            items.append(
                {
                    "bfSpecRgstNo": f"R26TEST{index:05d}",
                    "prdctClsfcNoNm": name,
                }
            )
        payload = page_payload(items)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_dir = root / "raw"
            survey.write_raw_page(
                raw_dir / "prespec" / "prespec-page-00001.json",
                ENDPOINTS["prespec"],
                {},
                1,
                1,
                payload,
            )
            opener = FakeOpener(
                [
                    page_payload(
                        [{"bfSpecRgstNo": f"R26TEST{index:05d}"}]
                    )
                    for index in range(1, len(items) + 1)
                    for _role in ("probe", "control")
                ]
            )

            document = probe.run_char_tolerance(
                raw_dir,
                root / "out",
                probe.DEFAULT_FROM_DATE,
                probe.DEFAULT_TO_DATE,
                fetcher_factory=self._factory(opener),
            )

        self.assertEqual(document["target_count"], len(targets))
        self.assertEqual(document["planned_request_count"], len(items) * 2)
        self.assertEqual(document["request_count"], len(items) * 2)
        self.assertEqual(len(opener.urls), len(items) * 2)
        for comparison in document["comparisons"]:
            self.assertNotEqual(comparison["query"], comparison["control_query"])
            target = comparison["target"]
            self.assertIn(target[0], comparison["query"])
            for char in target:
                self.assertNotIn(char, comparison["control_query"])

    def test_char_tolerance_stops_without_execute(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            with mock.patch.object(
                probe.survey, "get_service_key", side_effect=AssertionError("must not read key")
            ):
                exit_code = probe.main(
                    ["--char-tolerance", "--output-dir", str(output)]
                )

            self.assertEqual(exit_code, 2)
            self.assertFalse(output.exists())

    def test_char_tolerance_rejects_a_too_small_call_budget_before_fetching(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            survey.write_raw_page(
                root / "raw" / "prespec" / "prespec-page-00001.json",
                ENDPOINTS["prespec"],
                {},
                1,
                1,
                page_payload(
                    [
                        {
                            "bfSpecRgstNo": "R26TEST00001",
                            "prdctClsfcNoNm": "가나다라마바사&아자차카타파하",
                        }
                    ]
                ),
            )
            opener = FakeOpener([])
            with self.assertRaises(ExperimentError) as error:
                probe.run_char_tolerance(
                    root / "raw",
                    root / "out",
                    max_requests=1,
                    fetcher_factory=self._factory(opener),
                )

            self.assertEqual(error.exception.code, "request_limit")
            self.assertEqual(opener.urls, [])


if __name__ == "__main__":
    unittest.main()
