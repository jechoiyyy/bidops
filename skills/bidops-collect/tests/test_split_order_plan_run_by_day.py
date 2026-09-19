#!/usr/bin/env python3
"""Contract tests for the gold run published-day split tool."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SCRIPT = SCRIPT_DIR / "split_order_plan_run_by_day.py"
SPEC = importlib.util.spec_from_file_location("bidops_split_order_plan_run_by_day", SCRIPT)
assert SPEC and SPEC.loader
SPLIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SPLIT)


WINDOW_FROM = "2026-08-27"
WINDOW_TO = "2026-08-31"


def sample_item(plan_id: str, published_at: str, *, title: str | None = None) -> dict:
    """One normalized order-plan item shaped like collect_order_plans.py's output."""

    return {
        "order_plan_unty_no": plan_id,
        "title": title or f"실측 사업 {plan_id}",
        "agency_code": "1234567",
        "agency_name": "발주기관",
        "supervising_agency_name": "총괄기관",
        "business_division": "일반용역",
        "business_division_code": "03",
        "service_type": "신규(단기)",
        "service_type_code": "신120001",
        "budget_amount": 123456789,
        "contract_amount": 0,
        "planned_order_year": "2027",
        "planned_order_month": "2027-09",
        "procurement_method": "자체조달",
        "contract_method": "제한경쟁",
        "sw_business_status": None,
        "published_at": published_at,
        "changed_at": "2026-08-26T10:10:10+09:00",
        "bid_ntice_no_list": "R26BK01696186000",
        "notice_posted": "Y",
        "rcrit_rgst_no": "",
        "source_url": "https://www.g2b.go.kr/order-plan",
        "first_discovered_at": "2026-08-31T12:00:00+09:00",
        "last_discovered_at": "2026-08-31T12:00:00+09:00",
        "source_sha256": hashlib.sha256(plan_id.encode("utf-8")).hexdigest(),
        "unknown_fields": ["sw_business_status"],
        "raw_source": "raw/page-00001.json",
    }


def build_input_artifact(order_plans: list[dict]) -> dict:
    return {
        "schema_version": "bidops.collected-order-plans.v1",
        "generated_at": "2026-08-31T12:00:00+09:00",
        "source_window": {
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
            "timezone": "Asia/Seoul",
        },
        "metadata": {
            "endpoint_id": "g2b_order_plan_service_pps_search_v1",
            "endpoint": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListServcPPSSrch",
            "scope": "bsnsDivNm allowlist; SW사업대상 여부로 선필터하지 않음",
            "business_division_field": "bsnsDivNm",
            "business_divisions": ["기술용역", "일반용역"],
            "order_month_scope": {"from": "200412", "to": "999912"},
            "collection": {
                "page_count": 5,
                "request_count": 5,
                "complete": True,
            },
        },
        "counts": {
            "total": len(order_plans),
            "order_plans": len(order_plans),
            "in_scope": len(order_plans),
            "source_total": len(order_plans),
            "source_records": len(order_plans),
            "excluded_out_of_scope": 0,
            "excluded_business_divisions": 0,
            "page_count": 5,
            "request_count": 5,
        },
        "warnings": [],
        "order_plans": order_plans,
    }


def write_input_run(root: Path, run_id: str, artifact: dict) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / SPLIT.INPUT_FILE).write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return run_dir


# Four published days (2026-08-27..30), 1-3 items each, inside the input's
# half-open source_window [2026-08-27, 2026-08-31).
FOUR_DAY_ITEMS = [
    sample_item("2026PLN0000000001", "2026-08-27T09:00:00+09:00"),
    sample_item("2026PLN0000000002", "2026-08-28T10:15:00+09:00"),
    sample_item("2026PLN0000000003", "2026-08-28T18:45:00+09:00"),
    sample_item("2026PLN0000000004", "2026-08-29T08:30:00+09:00"),
    sample_item("2026PLN0000000005", "2026-08-29T13:00:00+09:00"),
    sample_item("2026PLN0000000006", "2026-08-29T23:59:00+09:00"),
    sample_item("2026PLN0000000007", "2026-08-30T00:00:00+09:00"),
]


class SplitIntoPerDayRunsTests(unittest.TestCase):
    def test_splits_into_four_runs_with_matching_totals_and_no_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = write_input_run(
                root, "order-plans-20260827-20260830-retry1", build_input_artifact(FOUR_DAY_ITEMS)
            )
            output_root = root / "runs"

            results = SPLIT.split_run(input_dir, output_root)

            self.assertEqual(4, len(results))
            expected_run_ids = {
                "gate-gold-20260827-plans",
                "gate-gold-20260828-plans",
                "gate-gold-20260829-plans",
                "gate-gold-20260830-plans",
            }
            self.assertEqual(expected_run_ids, {run_id for run_id, _count in results})

            total_written = 0
            seen_plan_ids: set[str] = set()
            for run_id, count in results:
                artifact_path = output_root / run_id / SPLIT.INPUT_FILE
                self.assertTrue(artifact_path.is_file())
                artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
                plan_ids = {item["order_plan_unty_no"] for item in artifact["order_plans"]}
                self.assertEqual(count, len(artifact["order_plans"]))
                self.assertEqual(set(), seen_plan_ids & plan_ids)
                seen_plan_ids |= plan_ids
                total_written += count
            self.assertEqual(len(FOUR_DAY_ITEMS), total_written)
            self.assertEqual({item["order_plan_unty_no"] for item in FOUR_DAY_ITEMS}, seen_plan_ids)

    def test_output_item_matches_input_item_and_preserves_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [
                sample_item("2026PLN0000000010", "2026-08-28T09:00:00+09:00"),
                sample_item("2026PLN0000000011", "2026-08-28T21:00:00+09:00"),
            ]
            input_dir = write_input_run(root, "order-plans-20260827-20260830-retry1", build_input_artifact(items))
            output_root = root / "runs"

            SPLIT.split_run(input_dir, output_root)

            artifact = json.loads(
                (output_root / "gate-gold-20260828-plans" / SPLIT.INPUT_FILE).read_text(encoding="utf-8")
            )
            self.assertEqual(items, artifact["order_plans"])

    def test_input_file_bytes_are_unchanged_after_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = write_input_run(
                root, "order-plans-20260827-20260830-retry1", build_input_artifact(FOUR_DAY_ITEMS)
            )
            input_path = input_dir / SPLIT.INPUT_FILE
            before = input_path.read_bytes()

            SPLIT.split_run(input_dir, root / "runs")

            self.assertEqual(before, input_path.read_bytes())

    def test_existing_output_directory_aborts_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = write_input_run(
                root, "order-plans-20260827-20260830-retry1", build_input_artifact(FOUR_DAY_ITEMS)
            )
            output_root = root / "runs"
            conflicting = output_root / "gate-gold-20260829-plans"
            conflicting.mkdir(parents=True)

            exit_code = SPLIT.main(
                ["--input-run", str(input_dir), "--output-root", str(output_root)]
            )

            self.assertNotEqual(0, exit_code)
            # No other output directory was created; only the pre-existing one exists.
            self.assertEqual(["gate-gold-20260829-plans"], sorted(p.name for p in output_root.iterdir()))
            self.assertEqual([], list(conflicting.iterdir()))

    def test_published_at_outside_source_window_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [
                sample_item("2026PLN0000000020", "2026-08-27T09:00:00+09:00"),
                # 2026-09-01 is outside the input's half-open [08-27, 08-31) window.
                sample_item("2026PLN0000000021", "2026-09-01T09:00:00+09:00"),
            ]
            input_dir = write_input_run(root, "order-plans-20260827-20260830-retry1", build_input_artifact(items))
            output_root = root / "runs"

            with self.assertRaises(SPLIT.SplitError) as ctx:
                SPLIT.split_run(input_dir, output_root)
            self.assertEqual("window_boundary_mismatch", ctx.exception.code)
            self.assertFalse(output_root.exists())

    def test_missing_published_at_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = sample_item("2026PLN0000000030", "2026-08-27T09:00:00+09:00")
            item["published_at"] = None
            input_dir = write_input_run(root, "order-plans-20260827-20260830-retry1", build_input_artifact([item]))
            output_root = root / "runs"

            with self.assertRaises(SPLIT.SplitError) as ctx:
                SPLIT.split_run(input_dir, output_root)
            self.assertEqual("missing_published_at", ctx.exception.code)
            self.assertFalse(output_root.exists())

    def test_duplicate_json_object_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "order-plans-20260827-20260830-retry1"
            input_dir.mkdir(parents=True)
            # Hand-write JSON text with a literal duplicate top-level key: this
            # is a corruption signal json.loads would otherwise silently hide
            # by keeping only the last value.
            raw_text = (
                '{"schema_version": "bidops.collected-order-plans.v1", '
                '"schema_version": "bidops.collected-order-plans.v1", '
                '"generated_at": "2026-08-31T12:00:00+09:00", '
                '"source_window": {"from": "2026-08-27", "to": "2026-08-31", "timezone": "Asia/Seoul"}, '
                '"metadata": {}, "counts": {}, "warnings": [], "order_plans": []}'
            )
            (input_dir / SPLIT.INPUT_FILE).write_text(raw_text, encoding="utf-8")
            output_root = root / "runs"

            with self.assertRaises(SPLIT.SplitError) as ctx:
                SPLIT.split_run(input_dir, output_root)
            self.assertEqual("duplicate_key", ctx.exception.code)
            self.assertFalse(output_root.exists())


class SourcePopulationCompatibilityTests(unittest.TestCase):
    """Assert the exact conditions order_plan_screening._source_population checks.

    _source_population (web/backend/app/screening/services/order_plan_screening.py:180-225)
    cannot be imported from this skill module (no web/backend cross-import per
    skills/bidops-collect/AGENTS.md). Its conditions are asserted directly here instead.
    """

    def test_each_day_output_passes_source_population_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = write_input_run(
                root, "order-plans-20260827-20260830-retry1", build_input_artifact(FOUR_DAY_ITEMS)
            )
            output_root = root / "runs"

            results = SPLIT.split_run(input_dir, output_root)

            self.assertTrue(results)
            for run_id, _count in results:
                artifact = json.loads(
                    (output_root / run_id / SPLIT.INPUT_FILE).read_text(encoding="utf-8")
                )
                # complete
                self.assertIs(True, artifact["metadata"]["collection"]["complete"])
                # warnings empty
                self.assertEqual([], artifact["warnings"])
                # order_plans non-empty
                rows = artifact["order_plans"]
                self.assertTrue(rows)
                # no duplicate order_plan_unty_no
                plan_ids = [row["order_plan_unty_no"] for row in rows]
                self.assertEqual(len(plan_ids), len(set(plan_ids)))
                # source_sha256 is 64 hex chars for every row
                for row in rows:
                    self.assertRegex(row["source_sha256"], r"^[0-9a-f]{64}$")
                # counts.total == len(order_plans)
                self.assertEqual(len(rows), artifact["counts"]["total"])


if __name__ == "__main__":
    unittest.main()
