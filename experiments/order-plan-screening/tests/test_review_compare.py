from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from helpers import make_population, make_result, make_run

from common import ExperimentError  # noqa: E402
from compare import build_comparison_rows, render_report  # noqa: E402
from make_review_set import (  # noqa: E402
    METHOD_NAMES,
    REVIEW_FIELDS,
    build_review_artifacts,
    read_labels,
    select_review_ids,
)


class ReviewAndComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.population = make_population(20)
        self.run = make_run(self.population)
        selections = {
            "keyword": {"P0000", "P0001", "P0002"},
            "bge_m3_colbert": {"P0001", "P0002", "P0003"},
            "qwen": {"P0002", "P0003", "P0004"},
            "luna": {"P0003", "P0004", "P0005"},
        }
        self.results = {
            method: make_result(self.population, method, selections[method])
            for method in METHOD_NAMES
        }

    def test_review_rows_are_blind_and_audit_sample_is_deterministic(self) -> None:
        first = select_review_ids(self.population, self.results, 5)
        second = select_review_ids(self.population, self.results, 5)
        self.assertEqual(first, second)
        manifest, rows = build_review_artifacts(
            self.run, self.population, self.results, 5
        )
        self.assertEqual(set(rows[0]), set(REVIEW_FIELDS))
        forbidden = {"method", "score", "rank", "selected", "selection_role", "split"}
        self.assertFalse(forbidden & set(rows[0]))
        self.assertEqual(manifest["candidate_union_count"], 6)
        self.assertEqual(manifest["audit_count"], 5)

    def _write_labels(self, path: Path, manifest: dict, invalid: bool = False) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index, item in enumerate(manifest["items"]):
                relevance, priority = ("관련", "높음") if index % 2 == 0 else ("비관련", "해당없음")
                if invalid and index == 0:
                    relevance, priority = "비관련", "높음"
                plan = next(row for row in self.population["items"] if row["plan_id"] == item["plan_id"])
                writer.writerow(
                    {
                        "plan_id": item["plan_id"],
                        "title": plan["title"],
                        "agency_name": plan["agency_name"],
                        "budget_amount": plan["budget_amount"] or "",
                        "planned_order_month": plan["planned_order_month"],
                        "published_at": plan["published_at"],
                        "relevance": relevance,
                        "priority": priority,
                        "reason": "검토 근거",
                        "reviewer": "검토자",
                        "reviewed_at": "2026-08-28T12:00:00+09:00",
                    }
                )

    def test_label_validator_rejects_disallowed_combination(self) -> None:
        manifest, _rows = build_review_artifacts(self.run, self.population, self.results, 5)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "labels.tsv"
            self._write_labels(path, manifest, invalid=True)
            with self.assertRaises(ExperimentError) as caught:
                read_labels(path, manifest, self.population)
            self.assertEqual(caught.exception.code, "label_combination_invalid")

    def test_comparison_is_bounded_and_does_not_claim_full_recall(self) -> None:
        manifest, _rows = build_review_artifacts(self.run, self.population, self.results, 5)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "labels.tsv"
            self._write_labels(path, manifest)
            labels = read_labels(path, manifest, self.population)
        rows = build_comparison_rows(self.results, labels, manifest)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["full_recall"] is None for row in rows))
        self.assertTrue(all(row["elapsed_ms"] == 30 for row in rows))
        report = render_report(self.run, self.population, manifest, rows)
        self.assertIn("전체 recall: 미측정", report)
        self.assertIn("실제 총 소요(ms)", report)
        self.assertIn("단일 평가자", report)
        self.assertNotIn("우승 방법", report)


if __name__ == "__main__":
    unittest.main()
