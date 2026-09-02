from __future__ import annotations

import unittest

import helpers  # noqa: F401  # Adds the sibling scripts directory to sys.path.

from build_gold_draft import (  # noqa: E402
    DECISION_SCHEMA,
    DraftError,
    audit_ids,
    nonrelevant_reason,
    validate_decisions,
)


class GoldDraftTests(unittest.TestCase):
    def test_decisions_are_bound_to_input_and_population(self) -> None:
        plans = [{"order_plan_unty_no": "P1"}, {"order_plan_unty_no": "P2"}]
        document = {
            "schema_version": DECISION_SCHEMA,
            "input_sha256": "abc",
            "input_record_count": 2,
            "overrides": {
                "P1": {
                    "relevance": "관련",
                    "priority": "높음",
                    "reason": "AI 시스템 구축",
                }
            },
        }
        validated = validate_decisions(document, "abc", plans)
        self.assertEqual(validated["P1"]["priority"], "높음")
        document["input_sha256"] = "different"
        with self.assertRaises(DraftError):
            validate_decisions(document, "abc", plans)

    def test_invalid_relevance_priority_combination_is_rejected(self) -> None:
        document = {
            "schema_version": DECISION_SCHEMA,
            "input_sha256": "abc",
            "input_record_count": 1,
            "overrides": {
                "P1": {
                    "relevance": "비관련",
                    "priority": "높음",
                    "reason": "잘못된 조합",
                }
            },
        }
        with self.assertRaises(DraftError):
            validate_decisions(document, "abc", [{"order_plan_unty_no": "P1"}])

    def test_negative_audits_are_deterministic_and_disjoint(self) -> None:
        rows = [
            {
                "plan_id": f"P{index}",
                "title": "AI 시스템 감리" if index < 4 else "일반 행사",
                "draft_relevance": "비관련",
            }
            for index in range(10)
        ]
        first = audit_ids(rows, 3, 2)
        second = audit_ids(rows, 3, 2)
        self.assertEqual(first, second)
        self.assertEqual((len(first[0]), len(first[1])), (3, 2))
        self.assertFalse(first[0] & first[1])

    def test_nonrelevant_reason_preserves_role_boundary(self) -> None:
        self.assertIn("감리", nonrelevant_reason("AI 시스템 구축 감리용역"))
        self.assertIn("행사", nonrelevant_reason("AI 박람회 행사 운영"))


if __name__ == "__main__":
    unittest.main()
