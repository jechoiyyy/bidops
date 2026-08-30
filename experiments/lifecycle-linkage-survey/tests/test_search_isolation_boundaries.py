"""Offline unit tests for the character-tolerance boundary contract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import FakeOpener, page_payload

import search_isolation_probe as probe  # noqa: E402
from common import ExperimentError  # noqa: E402
from endpoints import ENDPOINTS  # noqa: E402
import survey  # noqa: E402


class ToleranceBoundaryTests(unittest.TestCase):
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

    def _write_prespec(
        self, root: Path, items: list[dict[str, object]]
    ) -> Path:
        raw_dir = root / "raw"
        survey.write_raw_page(
            raw_dir / "prespec" / "prespec-page-00001.json",
            ENDPOINTS["prespec"],
            {},
            1,
            1,
            page_payload(items),
        )
        return raw_dir

    def test_selected_queries_and_controls_are_source_substrings_at_boundary(self) -> None:
        items = [
            {
                "bfSpecRgstNo": "R26TEST00001",
                "prdctClsfcNoNm": "가나다라마바사&아자차",
            },
            {
                "bfSpecRgstNo": "R26TEST00002",
                "prdctClsfcNoNm": "가나다~아자차카타파하",
            },
            {
                "bfSpecRgstNo": "R26TEST00003",
                "prdctClsfcNoNm": "가나다라/아자차카타파하",
            },
            {
                "bfSpecRgstNo": "R26TEST00004",
                "prdctClsfcNoNm": "가나다라마바사’아자차카타파하",
            },
            {
                "bfSpecRgstNo": "R26TEST00005",
                "prdctClsfcNoNm": "가나다라마바사_아자차카타파하",
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            selection = probe.select_tolerance_selection(
                self._write_prespec(Path(directory), items)
            )

        self.assertEqual(len(selection.cases), 5)
        for case in selection.cases:
            validation = probe.validate_tolerance_case(case)
            self.assertTrue(validation["query_is_contiguous_substring"])
            self.assertTrue(validation["control_query_is_contiguous_substring"])
            self.assertIn(case.query, case.source_name)
            self.assertIn(case.control_query, case.source_name)
            self.assertEqual(
                probe._remove_target(case.query, case.target), case.control_query
            )
            self.assertTrue(
                case.query.startswith(case.target.display)
                or case.query.endswith(case.target.display)
            )

        ampersand = next(
            case for case in selection.cases if case.target.display == "&"
        )
        self.assertTrue(ampersand.query.endswith("&"))

    def test_invalid_case_fails_before_any_fetch(self) -> None:
        case = probe.ToleranceCase(
            target=probe.ToleranceTarget("ampersand", ("&",)),
            query="가&나다라",
            control_query="가나다라",
            expected_spec_no="R26TEST00001",
            source_name="가&나다라가나다라",
        )
        opener = FakeOpener([])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            with mock.patch.object(
                probe,
                "select_tolerance_selection",
                return_value=probe.ToleranceSelection((case,), ()),
            ):
                with self.assertRaises(ExperimentError) as error:
                    probe.run_char_tolerance(
                        Path(directory) / "raw",
                        output,
                        fetcher_factory=self._factory(opener),
                    )

        self.assertEqual(error.exception.code, "invalid_tolerance_case")
        self.assertEqual(opener.urls, [])
        self.assertFalse(output.exists())

    def test_zero_cases_fail_and_short_target_is_skipped_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = self._write_prespec(
                Path(directory),
                [
                    {
                        "bfSpecRgstNo": "R26TEST00001",
                        "prdctClsfcNoNm": "가&나다",
                    }
                ],
            )
            selection = probe.select_tolerance_selection(raw_dir)
            with self.assertRaises(ExperimentError) as error:
                probe.run_char_tolerance(
                    raw_dir,
                    Path(directory) / "out",
                    fetcher_factory=self._factory(FakeOpener([])),
                )

        self.assertEqual(selection.cases, ())
        ampersand = next(
            item for item in selection.skipped if item.target.display == "&"
        )
        self.assertEqual(
            ampersand.reason_code, "boundary_control_too_short_or_unsafe"
        )
        self.assertIn("unknown", ampersand.reason)
        self.assertEqual(error.exception.code, "no_tolerance_cases")

    def test_artifact_records_source_fields_and_both_zero_unknown(self) -> None:
        item = {
            "bfSpecRgstNo": "R26TEST00001",
            "prdctClsfcNoNm": "가나다라마바사&아자차카타파하",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_dir = self._write_prespec(root, [item])
            opener = FakeOpener([page_payload([]), page_payload([])])
            document = probe.run_char_tolerance(
                raw_dir,
                root / "out",
                fetcher_factory=self._factory(opener),
            )

        comparison = document["comparisons"][0]
        self.assertEqual(document["request_count"], 2)
        self.assertEqual(document["planned_request_count"], 2)
        self.assertEqual(comparison["sample_source_spec_no"], item["bfSpecRgstNo"])
        self.assertIn(comparison["query"], item["prdctClsfcNoNm"])
        self.assertIn(comparison["control_query"], item["prdctClsfcNoNm"])
        self.assertTrue(comparison["query_is_contiguous_substring"])
        self.assertTrue(comparison["control_query_is_contiguous_substring"])
        self.assertEqual(comparison["conclusion"], "unknown")
        self.assertEqual(
            comparison["interpretation_code"], "both_zero_sample_selection_unknown"
        )
        self.assertEqual(len(document["variants"]), 2)
        self.assertTrue(
            all(row["case_query_is_contiguous_substring"] for row in document["variants"])
        )

    def test_control_hit_and_probe_zero_is_breaking_candidate(self) -> None:
        item = {
            "bfSpecRgstNo": "R26TEST00001",
            "prdctClsfcNoNm": "가나다라마바사&아자차카타파하",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_dir = self._write_prespec(root, [item])
            opener = FakeOpener(
                [
                    page_payload([]),
                    page_payload([{"bfSpecRgstNo": item["bfSpecRgstNo"]}]),
                ]
            )
            document = probe.run_char_tolerance(
                raw_dir,
                root / "out",
                fetcher_factory=self._factory(opener),
            )

        comparison = document["comparisons"][0]
        self.assertEqual(comparison["conclusion"], "breaking_candidate")
        self.assertEqual(
            comparison["interpretation_code"],
            "control_hit_probe_zero_breaking_candidate",
        )

    def test_call_budget_rejected_before_fetch_for_valid_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_dir = self._write_prespec(
                root,
                [
                    {
                        "bfSpecRgstNo": "R26TEST00001",
                        "prdctClsfcNoNm": "가나다라마바사&아자차카타파하",
                    }
                ],
            )
            opener = FakeOpener([])
            with self.assertRaises(ExperimentError) as error:
                probe.run_char_tolerance(
                    raw_dir,
                    root / "out",
                    max_requests=1,
                    fetcher_factory=self._factory(opener),
                )

        self.assertEqual(error.exception.code, "request_limit")
        self.assertEqual(opener.urls, [])


if __name__ == "__main__":
    unittest.main()
