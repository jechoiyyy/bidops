from uuid import uuid4

import pytest

from app.deep_review.schemas.prespec_overview_claims import (
    OverviewAssessmentSemanticResponse,
    PreliminaryAssessmentDraft,
)
from app.deep_review.services.preliminary_assessment import (
    CombinedDraftError,
    assessment_semantic_triggers,
    calculate_assessment,
    parse_combined_draft,
)
from app.deep_review.services.prespec_overview_claim_validation import (
    parse_claims_draft,
    validate_claims_deterministically,
)


PAGES = {1: "공공 데이터 플랫폼을 구축하고 통합 운영 체계를 구현한다."}


def overview_value():
    return {
        "schema_version": "bidops.prespec-overview-claims.v1",
        "claims": [
            {
                "id": "c1", "section": "business_overview",
                "text": "공공 데이터 플랫폼 사업이다.",
                "evidence": [{"page": 1, "quote": "공공 데이터 플랫폼"}],
                "quantities": [],
            },
            {
                "id": "c2", "section": "main_tasks",
                "text": "통합 운영 체계를 구현한다.",
                "evidence": [{"page": 1, "quote": "통합 운영 체계를 구현한다."}],
                "quantities": [],
            },
        ],
    }


def checks():
    draft = parse_claims_draft(overview_value())
    return validate_claims_deterministically(
        draft, PAGES, attempt_id=uuid4(), input_sha256="a" * 64,
        policy_digest="b" * 64, binding_digest="c" * 64,
    )


def assessment(*relations: str, role: str = "supplier", company_refs=None):
    relation_values = relations or ("direct", "unrelated", "partial")
    return PreliminaryAssessmentDraft.model_validate({
        "schema_version": "bidops.prespec-preliminary-assessment.v1",
        "primary_task_claim_ids": ["c2"],
        "delivery_role": role,
        "axes": [
            {
                "axis": axis,
                "relation": relation,
                "reason": "주요 과업과의 관계",
                "claim_refs": ["c2"],
                "company_refs": company_refs or [],
            }
            for axis, relation in zip(
                ("ai_data", "blockchain_did", "public_si_integration"),
                relation_values,
                strict=True,
            )
        ],
        "verification_items": [],
        "uncertainty_codes": [],
    })


def semantic_supported():
    return OverviewAssessmentSemanticResponse.model_validate({
        "schema_version": "bidops.prespec-overview-assessment-semantic.v1",
        "claim_checks": [
            {"claim_id": claim_id, "status": "supported", "reason_codes": []}
            for claim_id in ("c1", "c2")
        ],
        "assessment_checks": [
            {"axis": axis, "status": "supported", "reason_codes": []}
            for axis in ("ai_data", "blockchain_did", "public_si_integration")
        ],
    })


@pytest.mark.parametrize(
    ("relations", "grade"),
    [
        (("direct", "unrelated", "partial"), "우선 검토"),
        (("partial", "unrelated", "indirect"), "검토 권장"),
        (("indirect", "unrelated", "unrelated"), "관찰 대상"),
    ],
)
def test_server_calculates_strongest_supported_relation(relations, grade):
    decision = calculate_assessment(assessment(*relations), checks())
    assert decision.status == "graded"
    assert decision.grade == grade
    assert decision.semantic_required is False


def test_exclusion_requires_one_semantic_review():
    draft = assessment("unrelated", "unrelated", "unrelated")
    held = calculate_assessment(draft, checks())
    assert (held.status, held.grade, held.semantic_required) == ("held", None, True)
    assert held.reason_codes == ("semantic_required",)

    graded = calculate_assessment(draft, checks(), semantic=semantic_supported())
    assert (graded.status, graded.grade) == ("graded", "제외")


def test_missing_primary_evidence_and_invalid_profile_hold_instead_of_downgrading():
    value = assessment("indirect", "unrelated", "unrelated").model_dump(mode="json")
    value["primary_task_claim_ids"] = ["c1"]
    decision = calculate_assessment(PreliminaryAssessmentDraft.model_validate(value), checks())
    assert decision.status == "held"
    assert "primary_task_evidence_invalid" in decision.reason_codes

    profile = calculate_assessment(
        assessment("direct", "unrelated", "unrelated", company_refs=["p1"]),
        checks(), profile_status="invalid", allowed_company_refs=(),
    )
    assert profile.status == "held"
    assert "profile_binding_invalid" in profile.reason_codes


def test_child_parse_failure_preserves_valid_overview():
    parsed = parse_combined_draft({
        "schema_version": "bidops.prespec-overview-assessment-draft.v1",
        "overview": overview_value(),
        "assessment": {"schema_version": "wrong"},
    })
    assert parsed.overview is not None
    assert parsed.overview_error is None
    assert parsed.assessment is None
    assert parsed.assessment_error == "assessment_schema_invalid"


def test_duplicate_json_key_is_an_indivisible_format_failure():
    with pytest.raises(CombinedDraftError, match="duplicate_json_key"):
        parse_combined_draft(
            '{"schema_version":"bidops.prespec-overview-assessment-draft.v1",'
            '"overview":{},"overview":{},"assessment":{}}'
        )


@pytest.mark.parametrize(
    ("source", "claim", "expected"),
    [
        ("장애가 없는 경우에만 전환한다.", "장애가 없어 전환한다.", "condition_context_mismatch"),
        ("운영 업무는 포함하지 않는다.", "운영 업무를 수행한다.", "negation_context_mismatch"),
    ],
)
def test_negation_and_condition_differences_trigger_semantic_review(source, claim, expected):
    value = overview_value()
    value["claims"][1]["text"] = claim
    value["claims"][1]["evidence"] = [{"page": 1, "quote": source}]
    pages = {1: source}
    draft = parse_claims_draft(value)
    result = validate_claims_deterministically(
        draft, pages, attempt_id=uuid4(), input_sha256="a" * 64,
        policy_digest="b" * 64, binding_digest="c" * 64,
    )

    assert expected in assessment_semantic_triggers(assessment(), result)
