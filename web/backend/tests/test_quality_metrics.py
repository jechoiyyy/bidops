from __future__ import annotations

from app.screening.quality_metrics import (
    calculate_metrics,
    judgment_digest,
    ratio,
    required_metrics_pass,
)


NAMES = ("기술 적합성", "실적 정합성", "공공 SI 적합성", "사업성·자격 제약", "전략 부합")


def judgment(notice_id: str, *, grade: str = "검토 권장", assessments: tuple[str, ...] | None = None):
    assessments = assessments or ("적합",) * 5
    return {
        "notice_id": notice_id,
        "judgment_mode": "신규",
        "model_name": "qwen3.8:27b",
        "model_digest": "a" * 64,
        "prompt_version": "prompt-v1",
        "policy_version": "policy-v1",
        "company_profile_version": "company-profile.sha256:" + "b" * 64,
        "company_profile_digest": "b" * 64,
        "judged_in_run": "run-1",
        "recorded_in_run": "run-1",
        "carried_over": False,
        "rejudge_reason": None,
        "grade": grade,
        "readiness": "확인 완료",
        "primary_focus": "AI/데이터",
        "exclusion_category": None,
        "summary": "공고의 핵심 요구를 확인했습니다",
        "next_action": "제안 참여 조건을 추가 확인합니다",
        "matched_performances": [],
        "perspectives": [
            {
                "name": name,
                "assessment": assessments[index],
                "reason": "검증 가능한 관점 판단 근거입니다",
                "evidence": [{"source": "title", "status": "confirmed", "fact": "공고 사실"}],
            }
            for index, name in enumerate(NAMES)
        ],
        "verification_items": [],
        "counterarguments": ["공고별 반론"],
        "counterargument_resolutions": [
            {"counterargument": "공고별 반론", "status": "추가 확인", "reflection": "확인 항목에 반영"}
        ],
        "two_axis_mixing_flag": False,
        "two_axis_mixing_label": None,
    }


def artifact(count: int, *, priority: int = 0, offset: int = 0):
    return {
        "schema_version": "bidops.decisions.v3",
        "execution_id": "scr-" + "1" * 32,
        "run_id": "run-1",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "screening_basis": "회차에 고정된 정규화 공고와 회사 프로필·정책 버전",
        "model_name": "qwen3.8:27b",
        "model_digest": "a" * 64,
        "prompt_version": "prompt-v1",
        "policy_version": "policy-v1",
        "company_profile_version": "company-profile.sha256:" + "b" * 64,
        "company_profile_digest": "b" * 64,
        "judgments": [
            judgment(f"n-{index + offset}", grade="우선 검토" if index < priority else "검토 권장")
            for index in range(count)
        ]
    }


def test_decimal_boundary_is_compared_before_rounding():
    assert ratio(32, 40)["percent"] == 80.0
    assert ratio(31, 40)["percent"] == 77.5

    left = artifact(40)
    right = artifact(40)
    # 32/40 exactly meets the reproducibility threshold.
    right["judgments"][32]["grade"] = "우선 검토"
    right["judgments"][33]["grade"] = "우선 검토"
    right["judgments"][34]["grade"] = "우선 검토"
    right["judgments"][35]["grade"] = "우선 검토"
    right["judgments"][36]["grade"] = "우선 검토"
    right["judgments"][37]["grade"] = "우선 검토"
    right["judgments"][38]["grade"] = "우선 검토"
    right["judgments"][39]["grade"] = "우선 검토"
    metrics = calculate_metrics(left, right, sample_ids=[f"n-{index}" for index in range(40)])
    assert metrics["grade_reproducibility"]["numerator"] == 32
    assert metrics["grade_reproducibility"]["status"] == "통과"

    right["judgments"][31]["grade"] = "우선 검토"
    metrics = calculate_metrics(left, right, sample_ids=[f"n-{index}" for index in range(40)])
    assert metrics["grade_reproducibility"]["numerator"] == 31
    assert metrics["grade_reproducibility"]["status"] == "미달"


def test_small_discrimination_sample_is_not_zero_percent():
    values = artifact(9, priority=1)
    metrics = calculate_metrics(values, values, sample_ids=[f"n-{index}" for index in range(9)], expected_sample_count=9)
    assert metrics["discrimination"]["pass_a"]["numerator"] == 1
    assert metrics["discrimination"]["pass_a"]["denominator"] == 9
    assert metrics["discrimination"]["pass_a"]["percent"] == 11.11
    assert metrics["discrimination"]["pass_a"]["status"] == "계산 불가(소표본)"


def test_review_digest_mismatch_and_hold_are_excluded():
    left = artifact(40)
    reviews = [
        {"notice_id": f"n-{index}", "decision_digest": judgment_digest(left["judgments"][index]), "evidence_judgment": "동의"}
        for index in range(9)
    ]
    reviews.append({"notice_id": "n-9", "decision_digest": "f" * 64, "evidence_judgment": "동의"})
    reviews.append({"notice_id": "n-10", "decision_digest": judgment_digest(left["judgments"][10]), "evidence_judgment": "판단 보류"})
    metrics = calculate_metrics(left, left, reviews=reviews, sample_ids=[f"n-{index}" for index in range(40)])
    evidence = metrics["evidence_validity"]
    assert evidence["valid_review_count"] == 9
    assert evidence["distinct_notice_review_count"] == 9
    assert evidence["judgment_hold_count"] == 1
    assert evidence["status"] == "계산 불가(리뷰 부족)"
    assert any(item["reason"] == "decision_digest_mismatch" for item in metrics["excluded_notices"])


def test_metric_shape_and_precedence_include_all_required_keys():
    values = artifact(40)
    metrics = calculate_metrics(values, values, sample_ids=[f"n-{index}" for index in range(40)])
    assert set(metrics) == {
        "sample_count", "paired_valid_count", "excluded_notices", "grade_reproducibility",
        "perspective_reproducibility", "perspective_mismatch_concentration", "discrimination",
        "evidence_validity", "information_sufficiency", "perspective_split", "two_axis_mixing",
        "counterargument_reflection", "claude_alignment",
    }
    assert required_metrics_pass(metrics)[0] is False


def test_partial_v3_judgment_is_excluded_with_identity_and_fixed_sample_remains_40():
    left = artifact(1)
    right = artifact(1)
    left["judgments"][0].pop("counterargument_resolutions")
    metrics = calculate_metrics(left, right, sample_ids=["n-0"], expected_sample_count=1)
    assert metrics["sample_count"] == 1
    assert metrics["paired_valid_count"] == 0
    assert any(
        row["notice_id"] == "n-0" and row["pass"] == "A" and row["reason"].startswith("invalid_judgment:")
        for row in metrics["excluded_notices"]
    )


def test_input_performance_match_requires_matching_performance_evidence():
    left = artifact(1)
    right = artifact(1)
    notice = {"notice_id": "n-0", "performance_matches": [{"project_name": "기존 사업"}]}
    metrics = calculate_metrics(
        left,
        right,
        sample_ids=["n-0"],
        expected_sample_count=1,
        input_a={"notices": [notice]},
        input_b={"notices": [notice]},
    )
    assert metrics["paired_valid_count"] == 0
    assert any(row["notice_id"] == "n-0" and row["pass"] == "A" for row in metrics["excluded_notices"])


def test_invalid_decisions_top_level_excludes_every_fixed_notice():
    left = artifact(2)
    right = artifact(2)
    left.pop("screening_basis")
    ids = ["n-0", "n-1"]
    metrics = calculate_metrics(left, right, sample_ids=ids, expected_sample_count=2)
    assert metrics["paired_valid_count"] == 0
    assert {row["notice_id"] for row in metrics["excluded_notices"] if row["pass"] == "A"} >= set(ids)


def test_duplicate_in_sample_identity_is_not_counted_from_first_object():
    left = artifact(2)
    right = artifact(2)
    left["judgments"].append(dict(left["judgments"][0]))
    right["judgments"].append(dict(right["judgments"][0]))
    metrics = calculate_metrics(left, right, sample_ids=["n-0", "n-1"], expected_sample_count=2)
    assert metrics["paired_valid_count"] == 1
    assert any(row["notice_id"] == "n-0" and row["reason"] == "duplicate_notice_id" for row in metrics["excluded_notices"])


def test_pass_metrics_ignore_out_of_sample_and_zero_denominators_are_explicit():
    left = artifact(1)
    right = artifact(1)
    extra = judgment("outside")
    left["judgments"].append(extra)
    right["judgments"].append(extra)
    left["judgments"][0]["verification_items"] = []
    right["judgments"][0]["verification_items"] = []
    metrics = calculate_metrics(left, right, sample_ids=["n-0"], expected_sample_count=1)
    assert metrics["perspective_split"]["pass_a"]["denominator"] == 1
    assert metrics["information_sufficiency"]["pass_a"]["status"] == "해당 없음"
    assert metrics["two_axis_mixing"]["pass_a"]["status"] == "측정 완료"
    assert metrics["counterargument_reflection"]["pass_a"]["denominator"] == 1
    assert any(row["notice_id"] == "outside" and row["reason"] == "out_of_sample" for row in metrics["excluded_notices"])


def test_reflection_requires_same_index_counterargument_and_zero_is_unmeasurable():
    values = artifact(1)
    values["judgments"][0]["counterargument_resolutions"][0]["counterargument"] = "다른 반론"
    metrics = calculate_metrics(values, values, sample_ids=["n-0"], expected_sample_count=1)
    assert metrics["counterargument_reflection"]["pass_a"]["numerator"] == 0
    assert metrics["counterargument_reflection"]["pass_a"]["denominator"] == 0
    assert metrics["counterargument_reflection"]["pass_a"]["status"] == "계산 불가"

    values["judgments"][0]["counterarguments"] = []
    values["judgments"][0]["counterargument_resolutions"] = []
    metrics = calculate_metrics(values, values, sample_ids=["n-0"], expected_sample_count=1)
    assert metrics["counterargument_reflection"]["pass_a"]["status"] == "계산 불가"
