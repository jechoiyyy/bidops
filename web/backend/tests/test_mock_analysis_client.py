"""Deterministic mock-provider contract tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.services.deep_review_validation import validate_deep_review_stage
from app.services.deep_reviews import DeepReviewService
from app.services.mock_analysis_client import MOCK_MODEL_NAME, MockAnalysisClient


def _policy() -> dict:
    return {
        "stages": [
            {"stage": "requirements_and_evaluation", "instruction": "요구사항 추출"},
            {"stage": "delivery_risk_economics", "instruction": "수행 위험 분석"},
            {"stage": "synthesis_and_validation", "instruction": "종합 권고"},
        ],
    }


def _document_context() -> tuple[dict, dict, dict]:
    document_id = str(uuid4())
    structure_id = str(uuid4())
    source_hash = "a" * 64
    requirement = {
        "requirement_id": "req-1", "document_version_id": document_id,
        "structure_id": structure_id, "source_sha256": source_hash,
        "document_ordinal": 0, "page": 1, "block_order": 0,
        "locator_type": "page", "locator": {"page": 1},
        "text": "제안사는 통합 학습 시스템을 구축해야 한다.",
    }
    bundle = {
        "status": "ready",
        "documents": [{
            "document_version_id": document_id,
            "structure_id_at_confirmation": structure_id,
            "content_sha256": source_hash,
        }],
    }
    structures = {structure_id: {
        "structure_id": structure_id, "document_version_id": document_id,
        "source_sha256": source_hash, "pages": [{"number": 1}],
        "blocks": [{"block_key": "p1", "page": 1, "text": requirement["text"]}],
    }}
    return requirement, bundle, structures


def test_mock_requires_explicit_reference_workflow_mode():
    with pytest.raises(ValidationError, match="reference workflow"):
        Settings(analysis_provider="mock", reference_workflow_mode=False)
    settings = Settings(analysis_provider="mock", reference_workflow_mode=True)
    assert settings.analysis_provider == "mock"


def test_deep_review_service_selects_mock_and_marks_reference_mode(monkeypatch):
    monkeypatch.setenv("BIDOPS_ANALYSIS_PROVIDER", "mock")
    monkeypatch.setenv("BIDOPS_REFERENCE_WORKFLOW_MODE", "true")
    monkeypatch.setenv("BIDOPS_OPENAI_ENABLED", "false")
    get_settings.cache_clear()
    try:
        service = DeepReviewService(raw_response_store=object())
        assert isinstance(service.client, MockAnalysisClient)
        assert service.reference_workflow_mode is True
    finally:
        get_settings.cache_clear()


def test_mock_generates_valid_document_profile_and_recommendation_stages():
    client = MockAnalysisClient()
    requirement, bundle, structures = _document_context()
    review_id, attempt_id, profile_id, profile_evidence_id = (str(uuid4()) for _ in range(4))

    stage1_input = {
        "deep_review_id": review_id, "attempt_id": attempt_id,
        "stage": "requirements_and_evaluation", "slice_index": 0,
        "requirements": [requirement],
    }
    stage1 = client.invoke("requirements_and_evaluation", stage1_input, _policy())
    validated1 = validate_deep_review_stage(
        stage1.structured_output, bundle=bundle, structures=structures,
        expected_deep_review_id=review_id,
    )
    assert validated1["claims"][0]["status"] == "supported"
    assert validated1["evidence"][0]["quote"] in requirement["text"]

    profile_quote = "AI 플랫폼 구축 경험을 보유하고 있습니다."
    profile = {
        "profile_version_id": profile_id,
        "source_text": profile_quote,
        "facts": [{
            "fact_key": "company.ai_delivery", "status": "confirmed",
            "value": profile_quote, "quote": profile_quote,
        }],
        "evidence": [{
            "profile_evidence_id": profile_evidence_id,
            "profile_version_id": profile_id, "fact_key": "company.ai_delivery",
            "source_sha256": "b" * 64, "locator_type": "profile_fact",
            "locator": {"fact_key": "company.ai_delivery"}, "quote": profile_quote,
        }],
    }
    stage2_input = {
        "deep_review_id": review_id, "attempt_id": attempt_id,
        "stage": "delivery_risk_economics", "slice_index": 0,
        "requirements": [requirement], "profile_facts": profile["facts"],
        "profile_evidence": profile["evidence"],
    }
    stage2 = client.invoke(
        "delivery_risk_economics", stage2_input, _policy(),
        profile={"profile_version_id": profile_id, "profile_sha256": "c" * 64},
    )
    validated2 = validate_deep_review_stage(
        stage2.structured_output, bundle=bundle, structures=structures,
        profile=profile, profile_version_id=profile_id,
        expected_deep_review_id=review_id,
    )
    assert {row["source_kind"] for row in validated2["evidence"]} == {"document", "profile"}

    known_claim_ids = {row["claim_id"] for row in validated1["claims"] + validated2["claims"]}
    known_evidence_ids = {row["evidence_id"] for row in validated1["evidence"] + validated2["evidence"]}
    stage3_input = {
        "deep_review_id": review_id, "attempt_id": attempt_id,
        "stage": "synthesis_and_validation", "slice_index": 0,
        "verified_claims": validated1["claims"] + validated2["claims"],
        "prior_evidence": validated1["evidence"] + validated2["evidence"],
    }
    stage3 = client.invoke("synthesis_and_validation", stage3_input, _policy())
    validated3 = validate_deep_review_stage(
        stage3.structured_output, bundle=bundle, structures=structures,
        profile=profile, profile_version_id=profile_id,
        expected_deep_review_id=review_id, known_claim_ids=known_claim_ids,
        known_evidence_ids=known_evidence_ids,
    )
    assert validated3["claims"][0]["body"] == "조건부 추진 검토"
    assert stage3.provider == "mock-analysis" and stage3.model == MOCK_MODEL_NAME
    assert stage3.attempts == ({"retry_index": 0, "status": "succeeded", "latency_ms": 0},)


def test_stage2_input_budget_accepts_evidence_backed_profile_rows_over_two_kib():
    requirement, bundle, structures = _document_context()
    fact_key = "company.large_but_bounded_fact"
    quote = "확인된 수행 실적 " + "가" * 800
    profile_id, evidence_id = str(uuid4()), str(uuid4())
    profile = {
        "facts": [{"fact_key": fact_key, "status": "confirmed", "value": "가" * 300, "quote": quote}],
        "evidence": [{
            "profile_evidence_id": evidence_id, "profile_version_id": profile_id,
            "fact_key": fact_key, "source_sha256": "b" * 64,
            "locator_type": "profile_fact", "locator": {"fact_key": fact_key}, "quote": quote,
        }],
    }
    service = DeepReviewService(client=MockAnalysisClient(), raw_response_store=object())
    slices = service._stage_slices("delivery_risk_economics", bundle, structures, profile, ())
    assert slices and slices[0]["profile_facts"][0]["fact_key"] == fact_key
    invocation_input = {
        **slices[0], "notice_id": 1, "deep_review_id": str(uuid4()),
        "attempt_id": str(uuid4()), "stage": "delivery_risk_economics",
    }
    assert service.client.invoke(
        "delivery_risk_economics", invocation_input, _policy(),
        profile={"profile_version_id": profile_id, "profile_sha256": "c" * 64},
    ).structured_output["stage"] == "delivery_risk_economics"
