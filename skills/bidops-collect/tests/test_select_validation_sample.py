#!/usr/bin/env python3
"""Sampling tests: axis rotation for analysis, targeted strata for the audit."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/select_validation_sample.py"
SPEC = importlib.util.spec_from_file_location("bidops_select_validation_sample", SCRIPT)
assert SPEC and SPEC.loader
SAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLE)


def notice(
    identifier: str,
    *,
    axes: tuple[str, ...] = (),
    performances: int = 0,
    top_score: float = 0.0,
    middle: str | None = None,
    bucket: str = "candidate_pool",
) -> dict:
    return {
        "notice_id": identifier,
        "title": identifier,
        "collection_bucket": bucket,
        "focus_matches": [
            {
                "axis": axis,
                "label": "라벨",
                "matched_field": "bidNtceNm",
                "matched_text": "라벨",
                "field_kind": "title",
            }
            for axis in axes
        ],
        "performance_matches": [{"project_name": "p"} for _ in range(performances)],
        "performance_top_score": top_score,
        "procurement_class": {"large": None, "middle": middle, "detail": None, "code": None},
    }


class AnalysisSamplingTests(unittest.TestCase):
    def test_rotation_covers_every_axis_before_repeating_one(self) -> None:
        candidates = [
            notice(f"ai-{index}", axes=("AI/데이터",)) for index in range(5)
        ] + [
            notice(f"si-{index}", axes=("공공 SI·통합관리",)) for index in range(5)
        ] + [
            notice("bc-1", axes=("블록체인·DID",)),
            notice("perf-1", performances=1, top_score=0.9),
        ]
        selected = SAMPLE.select_analysis(candidates, 4)
        strata = [item["sample_stratum"] for item in selected]
        self.assertEqual(
            ["AI/데이터", "블록체인·DID", "공공 SI·통합관리", "수행실적 유사"],
            strata,
        )

    def test_selection_is_stable_across_runs(self) -> None:
        candidates = [notice(f"n-{index}", axes=("AI/데이터",)) for index in range(20)]
        first = [item["notice_id"] for item in SAMPLE.select_analysis(candidates, 5)]
        second = [item["notice_id"] for item in SAMPLE.select_analysis(candidates, 5)]
        self.assertEqual(first, second)

    def test_no_record_is_selected_twice(self) -> None:
        candidates = [
            notice("both", axes=("AI/데이터", "공공 SI·통합관리"), performances=1),
            notice("solo", axes=("AI/데이터",)),
        ]
        selected = SAMPLE.select_analysis(candidates, 2)
        self.assertEqual(2, len({item["notice_id"] for item in selected}))


class AuditSamplingTests(unittest.TestCase):
    """The audit sample looks for misses, so it is targeted rather than random."""

    def test_digital_classification_records_are_drawn_first(self) -> None:
        audit_pool = [
            notice(f"plain-{index}", bucket="audit_pool", middle="폐기물 처리")
            for index in range(20)
        ] + [
            notice("digital-1", bucket="audit_pool", middle="SW 및 시스템 개발"),
        ]
        selected = SAMPLE.select_audit(audit_pool, 2)
        self.assertIn("digital-1", {item["notice_id"] for item in selected})
        self.assertEqual(
            "분류 근접",
            next(
                item["sample_stratum"]
                for item in selected
                if item["notice_id"] == "digital-1"
            ),
        )

    def test_performance_near_miss_records_are_drawn(self) -> None:
        audit_pool = [
            notice(f"plain-{index}", bucket="audit_pool", middle="설계")
            for index in range(20)
        ] + [
            notice("near-1", bucket="audit_pool", middle="설계", top_score=0.52),
        ]
        selected = SAMPLE.select_audit(audit_pool, 3)
        by_id = {item["notice_id"]: item for item in selected}
        self.assertIn("near-1", by_id)
        self.assertEqual("실적 유사 근접", by_id["near-1"]["sample_stratum"])

    def test_remaining_slots_fall_back_to_random_records(self) -> None:
        audit_pool = [
            notice(f"plain-{index}", bucket="audit_pool", middle="설계")
            for index in range(20)
        ]
        selected = SAMPLE.select_audit(audit_pool, 3)
        self.assertEqual(3, len(selected))
        self.assertEqual({"무작위"}, {item["sample_stratum"] for item in selected})

    def test_targeted_strata_are_not_double_counted(self) -> None:
        audit_pool = [
            notice("both", bucket="audit_pool", middle="SW 및 시스템 개발", top_score=0.5),
            notice("plain", bucket="audit_pool", middle="설계"),
        ]
        selected = SAMPLE.select_audit(audit_pool, 2)
        self.assertEqual(2, len({item["notice_id"] for item in selected}))


class SchemaTests(unittest.TestCase):
    def test_v1_collection_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            SAMPLE.load_collection({"schema_version": "bidops.collected.v1"})

    def test_v2_collection_is_accepted(self) -> None:
        payload = {
            "schema_version": "bidops.collected.v2",
            "source_window": {"from": "2026-08-17", "to": "2026-08-23"},
            "notices": [],
        }
        self.assertEqual(payload, SAMPLE.load_collection(payload))


if __name__ == "__main__":
    unittest.main()
