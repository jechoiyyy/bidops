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


def v3_notice(notice_id: str, *, mode: str = "신규") -> dict:
    return {
        "notice_id": notice_id,
        "source_type": "bid_notice",
        "title": "AI 데이터 플랫폼 구축",
        "agency": "테스트기관",
        "method": "일반경쟁",
        "url": "https://example.test/notice",
        "collection_bucket": "candidate_pool",
        "published_at": "2026-08-25T09:00:00+09:00",
        "deadline_at": None,
        "budget": "100000000",
        "estimated_price": None,
        "procurement_class": {"large": "ICT", "middle": None, "detail": None, "code": None},
        "region_limit": {
            "basis": None,
            "joint_contract_regions": [],
            "joint_contract_rate": None,
            "regional_joint_contract_limit": None,
        },
        "lifecycle": {
            "pre_spec_no": None,
            "re_notice": None,
            "changed_at": None,
            "change_reason": None,
            "unified_notice_no": None,
            "previous_failed_notice_no": None,
        },
        "qualification_flags": {},
        "attachments": [],
        "focus_matches": [],
        "performance_matches": [],
        "performance_top_score": 0.0,
        "candidate_sources": ["focus_title"],
        "unknown_fields": [],
        "sample_stratum": "AI/데이터",
        "sample_role": "analysis",
        "raw_source": "raw/bid-page-001.json",
        "judgment_mode": mode,
        "carry_over_from": None,
        "rejudge_reason": None,
    }


def v3_judgment(notice_id: str, *, mode: str = "신규", run_id: str = "run-20260825", carried: bool = False) -> dict:
    value = {
        "notice_id": notice_id,
        "judgment_mode": mode,
        "model_name": "qwen-test",
        "model_digest": "b" * 64,
        "prompt_version": "prompt.v3",
        "policy_version": "policy.v3",
        "company_profile_version": "company-profile.sha256:" + "c" * 64,
        "company_profile_digest": "c" * 64,
        "judged_in_run": run_id,
        "recorded_in_run": run_id,
        "carried_over": carried,
        "rejudge_reason": "정정" if mode == "재판정" else None,
        "grade": "우선 검토",
        "readiness": "부분 확인 필요",
        "primary_focus": "AI/데이터",
        "exclusion_category": None,
        "summary": "핵심 기술과 공고 범위가 연결된다.",
        "next_action": "첨부 제안요청서에서 자격을 확인한다.",
        "perspectives": perspectives(),
        "matched_performances": [],
        "counterarguments": ["데이터 규모가 기존 실적보다 클 가능성이 있다."],
        "counterargument_resolutions": [{
            "counterargument": "데이터 규모가 기존 실적보다 클 가능성이 있다.",
            "status": "추가 확인",
            "reflection": "첨부 원문에서 규모와 투입 인력을 확인한다.",
        }],
        "verification_items": [{
            "item": "입찰참가자격",
            "why": "회사 프로필의 자격 상태가 아직 unknown이다.",
            "blocking": True,
            "status": "미확인",
            "requires_attachment": True,
        }],
        "two_axis_mixing_flag": False,
        "two_axis_mixing_label": None,
    }
    return value


def v3_input(*, modes: tuple[str, ...] = ("신규",)) -> dict:
    notices = [v3_notice(f"bid:v3:{index}", mode=mode) for index, mode in enumerate(modes)]
    return {
        "schema_version": "bidops.screening-input.v1",
        "execution_id": "scr-" + "a" * 32,
        "run_id": "run-20260825",
        "generated_at": "2026-08-25T10:00:00+09:00",
        "source_window": {"from": "2026-08-24", "to": "2026-08-24", "timezone": "Asia/Seoul"},
        "policy_version": "policy.v3",
        "prompt_version": "prompt.v3",
        "company_profile_version": "company-profile.sha256:" + "c" * 64,
        "company_profile_digest": "c" * 64,
        "candidate_count": len(notices),
        "notices": notices,
    }


def v3_decisions(input_value: dict, judgments: list[dict]) -> dict:
    return {
        "schema_version": "bidops.decisions.v3",
        "execution_id": input_value["execution_id"],
        "run_id": input_value["run_id"],
        "generated_at": "2026-08-25T10:01:00+09:00",
        "screening_basis": "정규화 공고와 회사 프로필",
        "model_name": "qwen-test",
        "model_digest": "b" * 64,
        "prompt_version": input_value["prompt_version"],
        "policy_version": input_value["policy_version"],
        "company_profile_version": input_value["company_profile_version"],
        "company_profile_digest": input_value["company_profile_digest"],
        "judgments": judgments,
    }


def v3_failure(input_value: dict, notice_id: str) -> dict:
    return {
        "schema_version": "bidops.screening-failures.v1",
        "execution_id": input_value["execution_id"],
        "run_id": input_value["run_id"],
        "generated_at": "2026-08-25T10:02:00+09:00",
        "failure_count": 1,
        "failures": [{
            "notice_id": notice_id,
            "failed_stage": "종합 판정",
            "failure_type": "timeout",
            "last_attempt_at": "2026-08-25T10:01:59+09:00",
            "retry_count": 1,
            "status": "사람 검토 대기",
            "failure_context": None,
            "trace_id": "trace-default",
            "span_id": "span-default",
            "error_summary": "모델 호출 시간이 초과되었다.",
        }],
    }


class V3ContractTests(unittest.TestCase):
    def test_complete_v3_merge_has_exact_top_shape(self) -> None:
        input_value = v3_input()
        output = BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))
        self.assertEqual("bidops.screening.v3", output["schema_version"])
        self.assertEqual(1, output["candidate_count"])
        self.assertEqual(1, output["result_count"])
        self.assertEqual(0, output["failure_count"])
        self.assertFalse(output["partial_artifact"])
        self.assertIsNone(output["failure_artifact"])
        self.assertEqual(
            set(output),
            {"schema_version", "execution_id", "generated_at", "screening_basis", "source_window", "model_name", "model_digest", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest", "candidate_count", "result_count", "failure_count", "partial_artifact", "failure_artifact", "results"},
        )

    def test_partial_v3_requires_failure_artifact_and_excludes_failed_notice(self) -> None:
        input_value = v3_input(modes=("신규", "신규"))
        decisions = v3_decisions(input_value, [v3_judgment("bid:v3:0")])
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, decisions)
        output = BUILD.merge(input_value, decisions, v3_failure(input_value, "bid:v3:1"))
        self.assertEqual(1, output["result_count"])
        self.assertEqual(1, output["failure_count"])
        self.assertTrue(output["partial_artifact"])
        self.assertEqual("screening-failures.json", output["failure_artifact"])
        self.assertEqual(["bid:v3:0"], [item["notice"]["notice_id"] for item in output["results"]])

    def test_v3_rejects_digest_mismatch_and_extra_keys(self) -> None:
        input_value = v3_input()
        decisions = v3_decisions(input_value, [v3_judgment("bid:v3:0")])
        decisions["company_profile_digest"] = "d" * 64
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, decisions)
        decisions = v3_decisions(input_value, [v3_judgment("bid:v3:0")])
        decisions["judgments"][0]["unexpected"] = True
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, decisions)

    def test_rejudge_metadata_must_match_input(self) -> None:
        input_value = v3_input(modes=("재판정",))
        decision = v3_judgment("bid:v3:0", mode="신규")
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, [decision]))

    def test_carried_judged_run_must_match_carry_over_from(self) -> None:
        input_value = v3_input(modes=("승계",))
        input_value["notices"][0]["carry_over_from"] = "run-source"
        decision = v3_judgment("bid:v3:0", mode="승계", carried=True, run_id="run-source")
        decision["judged_in_run"] = "different-source"
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, [decision]))

    def test_failure_notice_id_is_unique_even_across_stages(self) -> None:
        input_value = v3_input(modes=("신규", "신규"))
        decisions = v3_decisions(input_value, [v3_judgment("bid:v3:0")])
        failures = v3_failure(input_value, "bid:v3:1")
        duplicate = copy.deepcopy(failures["failures"][0])
        duplicate["failed_stage"] = "반론 검토"
        duplicate["trace_id"] = "trace-1"
        duplicate["span_id"] = "span-1"
        failures["failures"].append(duplicate)
        failures["failure_count"] = 2
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, decisions, failures)

    def test_carried_over_failure_context_is_cross_checked_with_input(self) -> None:
        input_value = v3_input(modes=("신규",))
        failures = v3_failure(input_value, "bid:v3:0")
        failure = failures["failures"][0]
        failure["failed_stage"] = "병합·검증"
        failure["failure_type"] = "schema_violation"
        failure["failure_context"] = "carried_over_validation"
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, []), failures)

    def test_valid_carried_over_failure_is_allowed_without_model_trace(self) -> None:
        input_value = v3_input(modes=("승계",))
        input_value["notices"][0]["carry_over_from"] = "run-source"
        failures = v3_failure(input_value, "bid:v3:0")
        failure = failures["failures"][0]
        failure["failed_stage"] = "병합·검증"
        failure["failure_type"] = "schema_violation"
        failure["failure_context"] = "carried_over_validation"
        failure["trace_id"] = None
        failure["span_id"] = None
        output = BUILD.merge(input_value, v3_decisions(input_value, []), failures)
        self.assertEqual((1, 0, 1), (output["candidate_count"], output["result_count"], output["failure_count"]))

    def test_carried_notice_failure_must_be_carried_over_validation(self) -> None:
        input_value = v3_input(modes=("승계",))
        input_value["notices"][0]["carry_over_from"] = "run-source"
        for stage, failure_type, context, trace_id, span_id in (
            ("병합·검증", "schema_violation", None, None, None),
            ("종합 판정", "timeout", None, "trace-model", "span-model"),
        ):
            failures = v3_failure(input_value, "bid:v3:0")
            failure = failures["failures"][0]
            failure.update({
                "failed_stage": stage,
                "failure_type": failure_type,
                "failure_context": context,
                "trace_id": trace_id,
                "span_id": span_id,
            })
            with self.subTest(stage=stage, context=context), self.assertRaises(SystemExit):
                BUILD.merge(input_value, v3_decisions(input_value, []), failures)

    def test_model_failure_requires_trace_and_span(self) -> None:
        input_value = v3_input(modes=("신규",))
        failures = v3_failure(input_value, "bid:v3:0")
        failures["failures"][0]["trace_id"] = None
        failures["failures"][0]["span_id"] = None
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, []), failures)

    def test_windows_control_and_colon_prefixed_paths_are_rejected(self) -> None:
        for path in ("C:/raw.json", "C:raw.json", "\x1fraw.json"):
            input_value = v3_input()
            input_value["notices"][0]["raw_source"] = path
            with self.subTest(path=path), self.assertRaises(SystemExit):
                BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))

    def test_collected_nested_object_keys_are_required(self) -> None:
        for object_name, key in (
            ("procurement_class", "large"),
            ("region_limit", "basis"),
            ("lifecycle", "pre_spec_no"),
            ("qualification_flags", "participation_limited"),
        ):
            input_value = v3_input()
            if object_name == "qualification_flags":
                input_value["notices"][0][object_name] = {
                    name: None for name in (
                        "participation_limited", "industry_limited", "information_business",
                        "general_service", "service_division", "joint_contract_method",
                        "performance_restricted_competition", "pq_evaluation",
                        "technical_evaluation", "technical_evaluation_rate",
                        "successful_bid_method",
                    )
                }
            input_value["notices"][0][object_name].pop(key)
            with self.subTest(object_name=object_name, key=key), self.assertRaises(SystemExit):
                BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))

    def test_malformed_attachments_is_rejected_as_contract_error(self) -> None:
        input_value = v3_input()
        input_value["notices"][0]["attachments"] = None
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))

    def test_malformed_focus_matches_is_rejected_as_contract_error(self) -> None:
        input_value = v3_input()
        input_value["notices"][0]["focus_matches"] = None
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))

    def test_malformed_performance_matches_is_rejected_as_contract_error(self) -> None:
        input_value = v3_input()
        input_value["notices"][0]["performance_matches"] = None
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))

    def test_failure_array_non_object_is_rejected_without_internal_error(self) -> None:
        input_value = v3_input()
        failures = v3_failure(input_value, "bid:v3:0")
        failures["failures"] = [None]
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, []), failures)

    def test_failure_notice_id_unhashable_is_rejected_without_internal_error(self) -> None:
        for notice_id in ([], {}):
            input_value = v3_input()
            failures = v3_failure(input_value, "bid:v3:0")
            failures["failures"][0]["notice_id"] = notice_id
            with self.subTest(notice_id=notice_id), self.assertRaises(SystemExit):
                BUILD.merge(input_value, v3_decisions(input_value, []), failures)

    def test_unhashable_ids_and_enums_are_rejected_without_internal_error(self) -> None:
        cases = ("notice_id", "judgment_mode", "perspective_name", "failure_stage", "failure_type")
        for case in cases:
            input_value = v3_input()
            decisions = v3_decisions(input_value, [v3_judgment("bid:v3:0")])
            failures = None
            if case == "notice_id":
                input_value["notices"][0]["notice_id"] = []
            elif case == "judgment_mode":
                input_value["notices"][0]["judgment_mode"] = []
            elif case == "perspective_name":
                decisions["judgments"][0]["perspectives"][0]["name"] = []
            else:
                input_value = v3_input(modes=("신규", "신규"))
                decisions = v3_decisions(input_value, [v3_judgment("bid:v3:0")])
                failures = v3_failure(input_value, "bid:v3:1")
                failures["failures"][0]["failed_stage" if case == "failure_stage" else "failure_type"] = []
            with self.subTest(case=case), self.assertRaises(SystemExit):
                BUILD.merge(input_value, decisions, failures)

    def test_invalid_counterarguments_do_not_reach_boilerplate_iteration(self) -> None:
        input_value = v3_input(modes=("신규", "신규", "신규"))
        judgments = [v3_judgment(f"bid:v3:{index}") for index in range(3)]
        judgments[0]["counterarguments"] = 1
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, judgments))

    def test_two_axis_perspective_scan_requires_a_list(self) -> None:
        for value in (1, True):
            input_value = v3_input()
            decision = v3_judgment("bid:v3:0")
            decision["perspectives"] = value
            with self.subTest(value=value), self.assertRaises(SystemExit):
                BUILD.merge(input_value, v3_decisions(input_value, [decision]))

    def test_collected_nested_types_are_rejected_without_internal_error(self) -> None:
        cases = (
            ("procurement_class", None, []),
            ("region_limit", None, []),
            ("lifecycle", None, []),
            ("qualification_flags", None, []),
            ("procurement_class", "large", []),
            ("procurement_class", "large", {}),
            ("region_limit", "basis", []),
            ("region_limit", "basis", {}),
            ("region_limit", "joint_contract_regions", [[]]),
            ("lifecycle", "pre_spec_no", []),
            ("lifecycle", "pre_spec_no", {}),
            ("lifecycle", "changed_at", []),
            ("lifecycle", "changed_at", {}),
            ("qualification_flags", "participation_limited", []),
        )
        for object_name, key, bad_value in cases:
            input_value = v3_input()
            if key is None:
                input_value["notices"][0][object_name] = bad_value
            else:
                if object_name == "qualification_flags":
                    input_value["notices"][0][object_name] = {
                        name: None
                        for name in (
                            "participation_limited", "industry_limited", "information_business",
                            "general_service", "service_division", "joint_contract_method",
                            "performance_restricted_competition", "pq_evaluation",
                            "technical_evaluation", "technical_evaluation_rate", "successful_bid_method",
                        )
                    }
                input_value["notices"][0][object_name][key] = bad_value
            with self.subTest(object_name=object_name, key=key), self.assertRaises(SystemExit):
                BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))

    def test_non_object_input_and_decisions_are_contract_errors(self) -> None:
        input_value = v3_input()
        decisions = v3_decisions(input_value, [v3_judgment("bid:v3:0")])
        for invalid_input, invalid_decisions in (
            (None, decisions),
            ([], decisions),
            (input_value, None),
            (input_value, []),
        ):
            with self.subTest(input=type(invalid_input).__name__, decisions=type(invalid_decisions).__name__), self.assertRaises(SystemExit):
                BUILD.merge(invalid_input, invalid_decisions)

    def test_budget_must_be_a_decimal_string_or_null(self) -> None:
        for budget in (100, 1.5, "", "not-a-number", "NaN", "Infinity"):
            input_value = v3_input()
            input_value["notices"][0]["budget"] = budget
            with self.subTest(budget=budget), self.assertRaises(SystemExit):
                BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))

    def test_window_requires_dates_in_order(self) -> None:
        for source_window in (
            {"from": "2026-08-24T00:00:00+09:00", "to": "2026-08-24", "timezone": "Asia/Seoul"},
            {"from": "2026-08-25", "to": "2026-08-24", "timezone": "Asia/Seoul"},
        ):
            input_value = v3_input()
            input_value["source_window"] = source_window
            with self.subTest(source_window=source_window), self.assertRaises(SystemExit):
                BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))

    def test_company_profile_version_is_digest_bound(self) -> None:
        input_value = v3_input()
        input_value["company_profile_version"] = "profile.v3"
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))
        input_value = v3_input()
        decision = v3_judgment("bid:v3:0")
        decision["company_profile_version"] = "profile.v3"
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, [decision]))

    def test_v3_merge_is_byte_deterministic_for_fixed_inputs(self) -> None:
        input_value = v3_input()
        decisions = v3_decisions(input_value, [v3_judgment("bid:v3:0")])
        first = BUILD.merge(input_value, decisions)
        second = BUILD.merge(input_value, decisions)
        self.assertEqual(BUILD.canonical_json_bytes(first), BUILD.canonical_json_bytes(second))

    def test_v3_rejects_top_notice_judgment_and_failure_extra_keys(self) -> None:
        input_value = v3_input()
        input_value["unexpected"] = True
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))
        input_value = v3_input()
        decisions = v3_decisions(input_value, [v3_judgment("bid:v3:0")])
        decisions["unexpected"] = True
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, decisions)
        input_value = v3_input()
        input_value["notices"][0]["unexpected"] = True
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]))
        input_value = v3_input(modes=("신규", "신규"))
        failures = v3_failure(input_value, "bid:v3:1")
        failures["unexpected"] = True
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, [v3_judgment("bid:v3:0")]), failures)
        input_value = v3_input()
        decision = v3_judgment("bid:v3:0")
        decision["unexpected"] = True
        with self.assertRaises(SystemExit):
            BUILD.merge(input_value, v3_decisions(input_value, [decision]))


if __name__ == "__main__":
    unittest.main()
