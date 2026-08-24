#!/usr/bin/env python3
"""The merge step validates agent judgments and never fills in missing content."""

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_screening_results.py"
SPEC = importlib.util.spec_from_file_location("bidops_build_screening_results", SCRIPT)
assert SPEC and SPEC.loader
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


def perspectives() -> list[dict]:
    return [
        {
            "name": name,
            "assessment": "적합",
            "reason": f"{name} 관점에서 확인한 판단 근거를 서술한다.",
            "evidence": [
                {
                    "source": "나라장터 API bidNtceNm",
                    "status": "confirmed",
                    "fact": "AI 기반 데이터 플랫폼 구축",
                }
            ],
        }
        for name in BUILD.REQUIRED_PERSPECTIVES
    ]


def judgment(**overrides) -> dict:
    base = {
        "notice_id": "bid:1:00",
        "grade": "우선 검토",
        "readiness": "부분 확인 필요",
        "primary_focus": "AI/데이터",
        "exclusion_category": None,
        "summary": "AI 데이터 플랫폼 구축으로 핵심 역량과 직접 연결된다.",
        "perspectives": perspectives(),
        "matched_performances": [],
        "counterarguments": ["요구 데이터 규모가 회사 실적보다 클 수 있다."],
        "verification_items": [
            {
                "item": "입찰참가자격",
                "why": "회사 프로필의 조달 자격이 unknown이다.",
                "blocking": True,
                "status": "미확인",
            }
        ],
        "next_action": "첨부 제안요청서에서 과업 범위를 확인한다.",
    }
    base.update(overrides)
    return base


NOTICE = {
    "notice_id": "bid:1:00",
    "title": "AI 기반 데이터 플랫폼 구축",
    "performance_matches": [],
}


def errors_for(judgment_value: dict, notice: dict | None = None) -> list[str]:
    return BUILD.validate_judgment(judgment_value, notice or NOTICE)


class RequiredContentTests(unittest.TestCase):
    def test_a_complete_judgment_passes(self) -> None:
        self.assertEqual([], errors_for(judgment()))

    def test_missing_perspective_is_rejected(self) -> None:
        partial = judgment(perspectives=perspectives()[:3])
        self.assertTrue(any("관점" in message for message in errors_for(partial)))

    def test_unknown_perspective_name_is_rejected(self) -> None:
        renamed = perspectives()
        renamed[0]["name"] = "제목·API 메타데이터 적합성"
        self.assertTrue(any("관점" in message for message in errors_for(judgment(perspectives=renamed))))

    def test_perspective_without_evidence_is_rejected(self) -> None:
        stripped = perspectives()
        stripped[1]["evidence"] = []
        self.assertTrue(any("근거" in message for message in errors_for(judgment(perspectives=stripped))))

    def test_evidence_status_must_be_a_profile_status(self) -> None:
        bad = perspectives()
        bad[0]["evidence"][0]["status"] = "확실"
        self.assertTrue(any("status" in message for message in errors_for(judgment(perspectives=bad))))

    def test_empty_counterargument_list_is_rejected(self) -> None:
        self.assertTrue(any("반론" in message for message in errors_for(judgment(counterarguments=[]))))

    def test_next_action_and_summary_are_required(self) -> None:
        self.assertTrue(errors_for(judgment(next_action="")))
        self.assertTrue(errors_for(judgment(summary="  ")))


class GradeAndReadinessTests(unittest.TestCase):
    def test_excluded_notice_may_not_claim_verification_is_complete(self) -> None:
        excluded = judgment(
            grade="제외",
            readiness="확인 완료",
            exclusion_category="행사·교육·홍보",
            verification_items=[],
        )
        self.assertTrue(any("제외" in message for message in errors_for(excluded)))

    def test_excluded_notice_requires_an_exclusion_category(self) -> None:
        excluded = judgment(
            grade="제외", readiness="해당 없음", verification_items=[]
        )
        self.assertTrue(
            any("exclusion_category" in message for message in errors_for(excluded))
        )

    def test_non_excluded_notice_may_not_carry_an_exclusion_category(self) -> None:
        self.assertTrue(
            any(
                "exclusion_category" in message
                for message in errors_for(judgment(exclusion_category="감리·평가"))
            )
        )

    def test_partial_readiness_requires_a_verification_item(self) -> None:
        self.assertTrue(
            any("확인 항목" in message for message in errors_for(judgment(verification_items=[])))
        )

    def test_confirmed_readiness_may_not_hold_a_blocking_unknown(self) -> None:
        confirmed = judgment(readiness="확인 완료")
        self.assertTrue(any("확인 완료" in message for message in errors_for(confirmed)))

    def test_unable_to_participate_requires_a_blocking_item(self) -> None:
        blocked = judgment(
            readiness="참여 불가 확인",
            verification_items=[
                {
                    "item": "업종 제한",
                    "why": "요구 업종을 보유하지 않았다.",
                    "blocking": False,
                    "status": "확인 완료",
                }
            ],
        )
        self.assertTrue(any("참여 불가" in message for message in errors_for(blocked)))


class RetrievalSignalTests(unittest.TestCase):
    def test_portfolio_signal_must_be_addressed_in_the_judgment(self) -> None:
        notice = dict(NOTICE, performance_matches=[{"project_name": "평생교육 플랫폼"}])
        self.assertTrue(
            any("수행실적" in message for message in errors_for(judgment(), notice))
        )

    def test_addressed_portfolio_signal_passes(self) -> None:
        notice = dict(NOTICE, performance_matches=[{"project_name": "평생교육 플랫폼"}])
        addressed = judgment(
            matched_performances=[
                {
                    "name": "평생교육 플랫폼",
                    "match_reason": "동일한 평생교육 도메인이다.",
                    "mismatch_or_limit": "디지털배지 범위는 이 공고에 없다.",
                    "source": "[루트랩]회사소개서_260804.pdf p.44",
                    "status": "unknown",
                }
            ]
        )
        self.assertEqual([], errors_for(addressed, notice))


class BoilerplateTests(unittest.TestCase):
    """One sentence repeated across most notices is not a counterargument."""

    def test_repeated_counterargument_is_rejected(self) -> None:
        judgments = [
            judgment(
                notice_id=f"bid:{index}:00",
                counterarguments=["첨부 문서 전문을 분석하지 않은 기준선 판정이다."],
            )
            for index in range(10)
        ]
        self.assertTrue(BUILD.boilerplate_errors(judgments, 0.4))

    def test_varied_counterarguments_pass(self) -> None:
        judgments = [
            judgment(notice_id=f"bid:{index}:00", counterarguments=[f"근거 {index}"])
            for index in range(10)
        ]
        self.assertEqual([], BUILD.boilerplate_errors(judgments, 0.4))


class MergeTests(unittest.TestCase):
    VALIDATION = {
        "schema_version": "bidops.validation-set.v2",
        "source_window": {"from": "2026-08-17", "to": "2026-08-23"},
        "notices": [copy.deepcopy(NOTICE)],
    }
    DECISIONS = {
        "schema_version": "bidops.decisions.v2",
        "screening_basis": "제목과 API 메타데이터",
        "judgments": [judgment()],
    }

    def test_merge_keeps_the_judgment_untouched(self) -> None:
        output = BUILD.merge(
            copy.deepcopy(self.VALIDATION), copy.deepcopy(self.DECISIONS)
        )
        merged = output["results"][0]["judgment"]
        self.assertEqual(5, len(merged["perspectives"]))
        self.assertNotIn("notice_id", merged)
        self.assertEqual(["요구 데이터 규모가 회사 실적보다 클 수 있다."], merged["counterarguments"])
        self.assertEqual("bidops.screening.v2", output["schema_version"])

    def test_missing_judgment_stops_the_merge(self) -> None:
        validation = copy.deepcopy(self.VALIDATION)
        validation["notices"].append(dict(NOTICE, notice_id="bid:2:00"))
        with self.assertRaises(SystemExit):
            BUILD.merge(validation, copy.deepcopy(self.DECISIONS))

    def test_invalid_judgment_stops_the_merge(self) -> None:
        decisions = copy.deepcopy(self.DECISIONS)
        decisions["judgments"][0]["perspectives"] = []
        with self.assertRaises(SystemExit):
            BUILD.merge(copy.deepcopy(self.VALIDATION), decisions)

    def test_old_decision_schema_is_rejected(self) -> None:
        decisions = copy.deepcopy(self.DECISIONS)
        decisions["schema_version"] = "bidops.decisions.v1"
        with self.assertRaises(SystemExit):
            BUILD.merge(copy.deepcopy(self.VALIDATION), decisions)


if __name__ == "__main__":
    unittest.main()
