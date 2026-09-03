import importlib.util
import json
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("prepare_collected_run", SCRIPTS / "prepare_collected_run.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PrepareCollectedRunTests(unittest.TestCase):
    def test_population_preserves_identity_and_source_locator(self):
        collected = {
            "order_plans": [
                {
                    "order_plan_unty_no": "R2",
                    "title": "둘",
                    "source_sha256": "b" * 64,
                    "source_url": "https://example.test/2",
                    "unknown_fields": ["sw_business_status"],
                },
                {
                    "order_plan_unty_no": "R1",
                    "title": "하나",
                    "source_sha256": "a" * 64,
                    "source_url": "https://example.test/1",
                    "unknown_fields": [],
                },
            ]
        }
        population = MODULE.build_population(
            collected, "test-run", "c" * 64, "2026-09-01T10:00:00+09:00"
        )
        self.assertEqual(["R1", "R2"], [row["plan_id"] for row in population["items"]])
        by_id = {row["plan_id"]: row for row in population["items"]}
        self.assertEqual("input/collected-order-plans.json#/order_plans/0", by_id["R2"]["source"]["raw_ref"])
        self.assertEqual("https://example.test/1", by_id["R1"]["official_url"])

    def test_rejects_incomplete_collection(self):
        document = {
            "schema_version": MODULE.COLLECTED_SCHEMA,
            "generated_at": "2026-09-01T10:00:00+09:00",
            "metadata": {"collection": {"complete": False}},
            "counts": {"order_plans": 1},
            "warnings": [],
            "order_plans": [{"order_plan_unty_no": "R1"}],
        }
        with self.assertRaisesRegex(MODULE.ExperimentError, "완료된"):
            MODULE._validate_collected(document)


if __name__ == "__main__":
    unittest.main()
