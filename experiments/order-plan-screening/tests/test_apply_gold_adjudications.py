from __future__ import annotations

import unittest

import helpers  # noqa: F401  # Adds the sibling scripts directory to sys.path.

from apply_gold_adjudications import AdjudicationError, validate_adjudications  # noqa: E402


class GoldAdjudicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.draft = [{
            "plan_id": "P1",
            "draft_relevance": "판단보류",
            "draft_priority": "낮음",
        }]
        self.human = [{
            "plan_id": "P1",
            "draft_relevance": "판단보류",
            "draft_priority": "낮음",
            "human_relevance": "비관련",
            "human_priority": "해당없음",
            "adjudication": "판단보류→비관련",
            "human_reason": "회사 기준 비관련",
            "reviewer": "interactive-user",
            "reviewed_at": "2026-09-01T09:48:33+09:00",
        }]

    def test_human_adjudication_is_validated_and_bound_to_draft(self) -> None:
        validated = validate_adjudications(self.draft, self.human)
        self.assertEqual(validated["P1"]["human_relevance"], "비관련")
        self.human[0]["draft_relevance"] = "관련"
        with self.assertRaises(AdjudicationError):
            validate_adjudications(self.draft, self.human)

    def test_human_reviewer_timestamp_and_combination_are_required(self) -> None:
        self.human[0]["reviewed_at"] = "2026-09-01T09:48:33"
        with self.assertRaises(AdjudicationError):
            validate_adjudications(self.draft, self.human)
        self.human[0]["reviewed_at"] = "2026-09-01T09:48:33+09:00"
        self.human[0]["human_priority"] = "높음"
        with self.assertRaises(AdjudicationError):
            validate_adjudications(self.draft, self.human)


if __name__ == "__main__":
    unittest.main()
