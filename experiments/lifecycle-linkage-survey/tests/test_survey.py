"""Offline contract checks for the lifecycle linkage survey."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from helpers import make_fetcher, page_payload

from common import ExperimentError, digest_json  # noqa: E402
from endpoints import ENDPOINTS  # noqa: E402
import survey  # noqa: E402


WINDOW_FROM = date(2026, 8, 24)
WINDOW_TO = date(2026, 8, 27)


class RawCollectionTests(unittest.TestCase):
    def test_stored_page_never_carries_the_service_key(self) -> None:
        fetcher = make_fetcher([page_payload([{"orderPlanUntyNo": "R1", "bizNm": "가"}])])
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory) / "order_plan"

            received = survey.collect_pages(
                ENDPOINTS["order_plan"], raw_dir, WINDOW_FROM, WINDOW_TO, 500, fetcher
            )

            self.assertEqual(received, 1)
            stored = json.loads(
                (raw_dir / "order_plan-page-00001.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("serviceKey", stored["query"])
            self.assertEqual(stored["payload_sha256"], digest_json(stored["payload"]))
        # The key still has to reach the wire, just never the artifact.
        self.assertIn("serviceKey=test-service-key", fetcher.opener.urls[0])

    def test_existing_raw_directory_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory) / "order_plan"
            raw_dir.mkdir(parents=True)
            (raw_dir / "order_plan-page-00001.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(ExperimentError) as error:
                survey.collect_pages(
                    ENDPOINTS["order_plan"], raw_dir, WINDOW_FROM, WINDOW_TO, 500, make_fetcher([])
                )
            self.assertEqual(error.exception.code, "artifact_exists")

    def test_collection_walks_every_page_until_total_is_reached(self) -> None:
        fetcher = make_fetcher(
            [
                page_payload([{"orderPlanUntyNo": "R1"}], total=2, page_no=1, rows=1),
                page_payload([{"orderPlanUntyNo": "R2"}], total=2, page_no=2, rows=1),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory) / "order_plan"

            received = survey.collect_pages(
                ENDPOINTS["order_plan"], raw_dir, WINDOW_FROM, WINDOW_TO, 1, fetcher
            )

            self.assertEqual(received, 2)
            self.assertEqual(
                sorted(path.name for path in raw_dir.glob("*.json")),
                ["order_plan-page-00001.json", "order_plan-page-00002.json"],
            )

    def test_a_reflected_service_key_stops_the_collection(self) -> None:
        leaking = page_payload([{"orderPlanUntyNo": "R1", "echo": "test-service-key"}])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ExperimentError) as error:
                survey.collect_pages(
                    ENDPOINTS["order_plan"],
                    Path(directory) / "order_plan",
                    WINDOW_FROM,
                    WINDOW_TO,
                    500,
                    make_fetcher([leaking]),
                )
            self.assertEqual(error.exception.code, "secret_reflected")

    def test_a_modified_payload_fails_the_hash_check(self) -> None:
        payload = page_payload([{"orderPlanUntyNo": "R1"}])
        with tempfile.TemporaryDirectory() as directory:
            raw_dir = Path(directory) / "order_plan"
            raw_dir.mkdir(parents=True)
            (raw_dir / "page.json").write_text(
                json.dumps(
                    {
                        "schema_version": survey.RAW_PAGE_SCHEMA,
                        "endpoint_id": "x",
                        "query": {"pageNo": "1"},
                        "page_no": 1,
                        "request_attempts": 1,
                        "collected_at": "2026-08-28T00:00:00+09:00",
                        "payload_sha256": digest_json(payload),
                        "payload": page_payload([{"orderPlanUntyNo": "TAMPERED"}]),
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ExperimentError) as error:
                survey.read_raw_pages(raw_dir)
            self.assertEqual(error.exception.code, "hash_mismatch")


class BaselineCompatibilityTests(unittest.TestCase):
    """The recheck is only comparable if it repeats the frozen query exactly."""

    FROZEN_RAW = (
        Path(__file__).resolve().parents[3]
        / "data/experiments/order-plan-screening/20260824-20260826-interim-v4/raw"
    )

    def test_order_plan_query_matches_the_frozen_experiment(self) -> None:
        if not self.FROZEN_RAW.is_dir():
            self.skipTest("고정 실험 raw가 없는 환경입니다")
        frozen = json.loads(
            (self.FROZEN_RAW / "page-00001.json").read_text(encoding="utf-8")
        )["query"]

        built = ENDPOINTS["order_plan"].query_builder(WINDOW_FROM, WINDOW_TO, 1, 500)

        self.assertEqual(built, frozen)

    def test_frozen_experiment_raw_is_readable_as_a_baseline(self) -> None:
        if not self.FROZEN_RAW.is_dir():
            self.skipTest("고정 실험 raw가 없는 환경입니다")

        pages = survey.read_raw_pages(self.FROZEN_RAW, survey.ACCEPTED_BASELINE_SCHEMAS)
        items = survey.items_from_pages(pages)

        self.assertTrue(items)
        self.assertEqual(len(items), len({item["orderPlanUntyNo"] for item in items}))

    def test_a_survey_schema_page_is_rejected_as_a_plain_survey_read(self) -> None:
        if not self.FROZEN_RAW.is_dir():
            self.skipTest("고정 실험 raw가 없는 환경입니다")

        with self.assertRaises(ExperimentError) as error:
            survey.read_raw_pages(self.FROZEN_RAW)
        self.assertEqual(error.exception.code, "schema_mismatch")


class FieldSurveyTests(unittest.TestCase):
    def test_always_empty_fields_stay_in_the_report(self) -> None:
        items = [
            {"orderPlanUntyNo": "R1", "rcritRgstNo": "", "bizNm": "가"},
            {"orderPlanUntyNo": "R2", "rcritRgstNo": None, "bizNm": ""},
        ]

        stats = {row["field"]: row for row in survey.field_stats(items)}

        self.assertEqual(stats["orderPlanUntyNo"]["filled"], 2)
        self.assertEqual(stats["bizNm"]["filled"], 1)
        # An always-empty field may be a linkage slot the source fills later,
        # so dropping it would erase evidence.
        self.assertEqual(stats["rcritRgstNo"]["filled"], 0)
        self.assertIsNone(stats["rcritRgstNo"]["example"])

    def test_contact_fields_are_counted_but_never_quoted(self) -> None:
        items = [{"ofclNm": "홍길동", "telNo": "042-000-0000", "bizNm": "사업"}]

        stats = {row["field"]: row for row in survey.field_stats(items)}

        self.assertEqual(stats["ofclNm"]["filled"], 1)
        self.assertTrue(stats["ofclNm"]["personal"])
        self.assertNotIn("홍길동", stats["ofclNm"]["example"])
        self.assertNotIn("042", stats["telNo"]["example"])
        self.assertEqual(stats["bizNm"]["example"], "사업")

    def test_linkage_probe_separates_absent_from_empty(self) -> None:
        probe = survey.linkage_probe(
            "order_plan", [{"orderPlanUntyNo": "R1", "bidNtceNoList": ""}]
        )

        self.assertEqual(
            probe["orderPlanUntyNo"],
            {"status": "present", "filled": 1, "total": 1, "fill_rate": 1.0},
        )
        self.assertEqual(probe["bidNtceNoList"]["status"], "present")
        self.assertEqual(probe["bidNtceNoList"]["filled"], 0)
        # A key the response never carried is a different finding from a key
        # that came back empty.
        self.assertEqual(probe["rcritRgstNo"], {"status": "absent_from_response"})


class ReobservationTests(unittest.TestCase):
    def test_newly_filled_linkage_fields_are_reported(self) -> None:
        baseline = [
            {"orderPlanUntyNo": "R1", "bidNtceNoList": "", "chgDt": ""},
            {"orderPlanUntyNo": "R2", "bidNtceNoList": "B2", "chgDt": ""},
        ]
        current = [
            {"orderPlanUntyNo": "R1", "bidNtceNoList": "B1", "chgDt": "2026-08-27 10:00:00"},
            {"orderPlanUntyNo": "R2", "bidNtceNoList": "B2", "chgDt": ""},
            {"orderPlanUntyNo": "R3", "bidNtceNoList": "", "chgDt": ""},
        ]

        result = survey.compare_observations(baseline, current, "orderPlanUntyNo")

        self.assertEqual(result["baseline_count"], 2)
        self.assertEqual(result["current_count"], 3)
        self.assertEqual(result["common_count"], 2)
        self.assertEqual(result["changed_record_count"], 1)
        self.assertEqual(result["changed_field_counts"], {"bidNtceNoList": 1, "chgDt": 1})
        self.assertEqual(result["only_in_current"], ["R3"])
        self.assertEqual(result["examples"][0]["record_key"], "R1")

    def test_duplicate_record_keys_are_rejected(self) -> None:
        with self.assertRaises(ExperimentError) as error:
            survey.compare_observations(
                [{"orderPlanUntyNo": "R1"}, {"orderPlanUntyNo": "R1"}],
                [{"orderPlanUntyNo": "R1"}],
                "orderPlanUntyNo",
            )
        self.assertEqual(error.exception.code, "duplicate_record_key")

    def test_comparison_runs_end_to_end_on_stored_raw(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            survey.collect_pages(
                ENDPOINTS["order_plan"],
                root / "baseline" / "order_plan",
                WINDOW_FROM,
                WINDOW_TO,
                500,
                make_fetcher([page_payload([{"orderPlanUntyNo": "R1", "bidNtceNoList": ""}])]),
            )
            survey.collect_pages(
                ENDPOINTS["order_plan"],
                root / "current" / "order_plan",
                WINDOW_FROM,
                WINDOW_TO,
                500,
                make_fetcher([page_payload([{"orderPlanUntyNo": "R1", "bidNtceNoList": "B1"}])]),
            )

            exit_code = survey.main(
                [
                    "report",
                    "--run-id",
                    "t1",
                    "--raw-dir",
                    str(root / "current"),
                    "--output-dir",
                    str(root / "out"),
                    "--baseline-raw",
                    str(root / "baseline" / "order_plan"),
                ]
            )

            self.assertEqual(exit_code, 0)
            document = json.loads((root / "out" / "survey.json").read_text(encoding="utf-8"))
            self.assertEqual(document["order_plan_recheck"]["changed_record_count"], 1)


class CommandTests(unittest.TestCase):
    def test_report_replays_stored_raw_and_renders_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fetcher = make_fetcher(
                [
                    page_payload([{"orderPlanUntyNo": "R1", "bidNtceNoList": "", "bizNm": "가"}]),
                    page_payload([{"bfSpecRgstNo": "P1", "bfSpecNm": "나"}]),
                ]
            )
            survey.collect_pages(
                ENDPOINTS["order_plan"], root / "raw" / "order_plan", WINDOW_FROM, WINDOW_TO, 500, fetcher
            )
            survey.collect_pages(
                ENDPOINTS["prespec"], root / "raw" / "prespec", WINDOW_FROM, WINDOW_TO, 500, fetcher
            )

            exit_code = survey.main(
                [
                    "report",
                    "--run-id",
                    "t1",
                    "--raw-dir",
                    str(root / "raw"),
                    "--output-dir",
                    str(root / "out"),
                    "--markdown",
                    str(root / "out" / "report.md"),
                ]
            )

            self.assertEqual(exit_code, 0)
            document = json.loads((root / "out" / "survey.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [report["target"] for report in document["targets"]], ["order_plan", "prespec"]
            )
            self.assertIsNone(document["order_plan_recheck"])
            markdown = (root / "out" / "report.md").read_text(encoding="utf-8")
            self.assertIn("orderPlanUntyNo", markdown)

    def test_collect_does_nothing_without_explicit_execute(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"

            exit_code = survey.main(
                [
                    "collect",
                    "--run-id",
                    "t1",
                    "--output-dir",
                    str(output),
                    "--target",
                    "order_plan",
                    "--from-date",
                    "2026-08-24",
                    "--to-date",
                    "2026-08-27",
                ]
            )

            self.assertEqual(exit_code, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
