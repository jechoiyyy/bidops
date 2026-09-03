from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.deep_review.contracts import SchemaValidationError, load_schema, validate_payload
from app.deep_review.services.deep_review_validation import (
    DeepReviewValidationError,
    compare_requirement_ids,
    merge_stage_chunks,
    replay_calculation,
    validate_deep_review_report,
    validate_deep_review_stage,
    validate_deep_review_validation,
    validate_document_bundle,
    validate_document_structure,
    validate_final_opinion_snapshot,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "deep_review"
U = "11111111-1111-1111-1111-111111111111"
U2 = "22222222-2222-2222-2222-222222222222"
U3 = "33333333-3333-3333-3333-333333333333"
U4 = "44444444-4444-4444-4444-444444444444"
U5 = "55555555-5555-5555-5555-555555555555"
HASH = "a" * 64


def structure() -> dict:
    return {
        "schema": "bidops.document-structure.v1",
        "structure_id": U,
        "document_version_id": U2,
        "source_sha256": HASH,
        "media_type": "application/pdf",
        "extractor": {"name": "fixture", "version": "1", "upstream_commit": None},
        "pages": [{"number": 1, "width": 612, "height": 792, "image_content_object_id": None}],
        "blocks": [{"block_key": "p1", "parent_block_key": None, "type": "paragraph", "page": 1, "bbox": None, "text": "100 × 2.5%", "confidence": 1, "attributes": {}}],
        "warnings": [],
        "created_at": "2026-08-25T00:00:00+09:00",
    }


def bundle() -> dict:
    return {
        "schema": "bidops.document-bundle.v1", "bundle_id": U3, "notice_id": 1,
        "revision": 1, "version": 1, "status": "ready",
        "documents": [{
            "document_version_id": U2, "document_version_version": 1, "ordinal": 0,
            "content_object_id": U4, "content_sha256": HASH, "detected_mime": "application/pdf",
            "size_bytes": 7, "original_filename": "fixture.pdf", "source_kind": "manual",
            "source_system": None, "source_attachment_key": None, "source_url": None,
            "role_at_confirmation": "공고", "effective_date_at_confirmation": None,
            "replaces_id_at_confirmation": None, "is_current_at_confirmation": True,
            "safety_status_at_confirmation": "safe", "structure_id_at_confirmation": U,
            "structure_payload_sha256": "b" * 64,
        }], "issues": [], "confirmed_by": "reviewer",
        "confirmed_at": "2026-08-25T00:00:00+09:00", "created_at": "2026-08-25T00:00:00+09:00",
    }


def structures() -> dict[str, dict]:
    return {U: structure()}


def locator_structures() -> dict[str, dict]:
    value = structure()
    value["blocks"] += [
        {"block_key": "cell1", "parent_block_key": None, "type": "table_cell", "page": 1, "bbox": [0, 0, 10, 10], "text": "Cell 10", "confidence": 1, "attributes": {"table_key": "t1", "row": 0, "column": 1}},
        {"block_key": "box1", "parent_block_key": None, "type": "paragraph", "page": 1, "bbox": [10, 10, 20, 20], "text": "Box 20", "confidence": 1, "attributes": {}},
    ]
    return {U: value}


def stage(*, claim: dict | None = None, evidence: dict | None = None) -> dict:
    return {
        "schema": "bidops.deep-review-stage.v1", "deep_review_id": U,
        "attempt_id": U2, "stage": "requirements_and_evaluation",
        "claims": [claim] if claim else [], "evidence": [evidence] if evidence else [],
        "unknowns": [], "warnings": [],
    }


def evidence() -> dict:
    return {
        "evidence_id": U5, "source_kind": "document", "document_version_id": U2,
        "structure_id": U, "profile_version_id": None, "profile_evidence_id": None,
        "locator_type": "paragraph", "locator": {"page": 1, "block_key": "p1", "paragraph_key": None, "text_start": 0, "text_end": len("100 × 2.5%")},
        "quote": "100 × 2.5%", "confidence": 1, "source_sha256": HASH,
    }


def claim(*, kind: str = "fact", body: str = "fixture", evidence_ids: list[str] | None = None, premises: list[str] | None = None, formula: str | None = None, reason: str | None = None) -> dict:
    return {
        "claim_id": U4, "category": "requirements", "claim_type": kind, "body": body,
        "status": "supported", "formula": formula, "premise_claim_ids": premises or [],
        "reason": reason, "evidence_ids": evidence_ids or [],
    }


def profile() -> dict:
    return {
        "profile_version_id": U,
        "evidence": [{"profile_evidence_id": U5, "fact_key": "company.region", "source_sha256": HASH, "quote": "서울"}],
    }


def complete_profile() -> dict:
    return {
        "profile_version_id": U,
        "facts": [{"fact_key": "company.region", "status": "confirmed", "quote": "서울"}],
        "evidence": [{"profile_evidence_id": U5, "profile_version_id": U, "fact_key": "company.region", "source_sha256": HASH, "quote": "서울"}],
        "source_text": "회사는 서울에 있다.",
    }


def profile_evidence() -> dict:
    return {
        "evidence_id": U5, "source_kind": "profile", "document_version_id": None, "structure_id": None,
        "profile_version_id": U, "profile_evidence_id": U5, "locator_type": "profile_fact",
        "locator": {"fact_key": "company.region"}, "quote": "서울", "confidence": 1, "source_sha256": HASH,
    }


def test_all_five_schema_files_are_closed_and_loadable() -> None:
    names = ("document-structure", "document-bundle", "deep-review-stage", "deep-review-report", "deep-review-validation")
    for name in names:
        schema = load_schema(name)
        assert schema["additionalProperties"] is False
        assert schema["$id"].startswith("bidops.")


def test_document_structure_validates_refs_and_rejects_cycles() -> None:
    assert validate_document_structure(structure())["schema"] == "bidops.document-structure.v1"
    invalid = structure()
    invalid["blocks"][0]["parent_block_key"] = "p1"
    with pytest.raises(DeepReviewValidationError, match="cyclic_parent"):
        validate_document_structure(invalid)


def test_bundle_ready_rejects_blocking_issue_and_locator_mismatch() -> None:
    invalid = bundle()
    invalid["issues"] = [{"issue_id": "missing", "code": "ocr", "severity": "중대", "blocking": True, "document_version_id": U2, "message": "check", "locator_type": "page", "locator": {"page": 1, "bad": True}}]
    with pytest.raises(DeepReviewValidationError):
        validate_document_bundle(invalid)


def test_fact_requires_evidence_and_calculation_replays_exact_decimal() -> None:
    with pytest.raises(DeepReviewValidationError, match="fact_evidence_required"):
        validate_deep_review_stage(stage(claim=claim()), bundle=bundle(), structures=structures())
    calculation = claim(kind="calculation", body="2.50", evidence_ids=[U5], formula="100 * 2.5%")
    assert validate_deep_review_stage(stage(claim=calculation, evidence=evidence()), bundle=bundle(), structures=structures())["claims"][0]["claim_type"] == "calculation"
    assert replay_calculation("1.20 + 0.30", expected="1.50") == replay_calculation("1.5")


def test_dangling_and_cyclic_premises_are_rejected() -> None:
    invalid = claim(kind="inference", evidence_ids=[U5], premises=[U], reason="because")
    with pytest.raises(DeepReviewValidationError, match="dangling_premise"):
        validate_deep_review_stage(stage(claim=invalid, evidence=evidence()), bundle=bundle(), structures=structures())
    invalid["premise_claim_ids"] = [U4]
    invalid["claim_type"] = "inference"
    invalid["claim_id"] = U4
    with pytest.raises(DeepReviewValidationError, match="cyclic_premise"):
        validate_deep_review_stage(stage(claim=invalid, evidence=evidence()), bundle=bundle(), structures=structures())


def test_bundle_scope_and_source_hash_are_enforced() -> None:
    invalid = evidence()
    invalid["source_sha256"] = "c" * 64
    with pytest.raises(DeepReviewValidationError, match="evidence_source_hash_mismatch"):
        validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=invalid), bundle=bundle(), structures=structures())


def test_document_evidence_fails_closed_without_pinned_context_and_never_uses_structure_payload_hash() -> None:
    with pytest.raises(DeepReviewValidationError, match="bundle_context_missing"):
        validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=evidence()), structures=structures())
    with pytest.raises(DeepReviewValidationError, match="structure_context_missing"):
        validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=evidence()), bundle=bundle())
    invalid = evidence()
    invalid["source_sha256"] = "b" * 64
    with pytest.raises(DeepReviewValidationError, match="evidence_source_hash_mismatch"):
        validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=invalid), bundle=bundle(), structures=structures())


def test_document_locators_resolve_quote_against_pinned_structure() -> None:
    for locator_type, locator in (
        ("page", {"page": 1}),
        ("paragraph", {"page": 1, "block_key": "p1", "paragraph_key": None, "text_start": 0, "text_end": len("100 × 2.5%")}),
    ):
        item = evidence()
        item["locator_type"], item["locator"] = locator_type, locator
        assert validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=item), bundle=bundle(), structures=structures())
    invalid = evidence()
    invalid["quote"] = "not pinned"
    with pytest.raises(DeepReviewValidationError, match="evidence_quote_mismatch"):
        validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=invalid), bundle=bundle(), structures=structures())
    invalid = evidence()
    invalid["locator"]["text_end"] = 3
    with pytest.raises(DeepReviewValidationError, match="locator_unresolved"):
        validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=invalid), bundle=bundle(), structures=structures())
    for locator_type, locator, quote in (
        ("table_cell", {"page": 1, "block_key": "cell1", "table_key": "t1", "row": 0, "column": 1}, "Cell 10"),
        ("bbox", {"page": 1, "block_key": "box1", "bbox": [10, 10, 20, 20]}, "Box 20"),
    ):
        item = evidence()
        item["locator_type"], item["locator"], item["quote"] = locator_type, locator, quote
        assert validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=item), bundle=bundle(), structures=locator_structures())


def test_profile_evidence_fails_closed_and_matches_pinned_fact_hash_and_quote() -> None:
    item = profile_evidence()
    assert validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=item), profile=profile())
    with pytest.raises(DeepReviewValidationError, match="profile_context_missing"):
        validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=item))
    invalid = profile_evidence()
    invalid["locator"]["fact_key"] = "company.other"
    with pytest.raises(DeepReviewValidationError, match="profile_fact_key_mismatch"):
        validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=invalid), profile=profile())
    invalid = profile_evidence()
    invalid["quote"] = "다른 인용"
    with pytest.raises(DeepReviewValidationError, match="evidence_quote_mismatch"):
        validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=invalid), profile=profile())
    invalid = profile_evidence()
    invalid["profile_version_id"] = U2
    with pytest.raises(DeepReviewValidationError, match="evidence_out_of_profile"):
        validate_deep_review_stage(stage(claim=claim(evidence_ids=[U5]), evidence=invalid), profile=profile())


def test_profile_fact_keys_and_evidence_are_exact_and_unique() -> None:
    invalid = complete_profile()
    invalid["facts"].append({"fact_key": "company.region", "status": "unknown", "quote": "서울"})
    with pytest.raises(DeepReviewValidationError, match="profile_fact_key_duplicate"):
        validate_deep_review_stage(stage(), profile=invalid)
    invalid = complete_profile()
    invalid["evidence"].append({**invalid["evidence"][0], "profile_evidence_id": U4})
    with pytest.raises(DeepReviewValidationError, match="profile_evidence_duplicate"):
        validate_deep_review_stage(stage(), profile=invalid)
    invalid = complete_profile()
    invalid["evidence"][0]["quote"] = "tampered"
    with pytest.raises(DeepReviewValidationError, match="profile_fact_quote_mismatch"):
        validate_deep_review_stage(stage(), profile=invalid)


def test_calculation_requires_each_left_input_in_a_cited_quote_and_bounds_ast() -> None:
    invalid = claim(kind="calculation", body="102", evidence_ids=[U5], formula="100 + 2")
    with pytest.raises(DeepReviewValidationError, match="calculation_input_evidence_missing"):
        validate_deep_review_stage(stage(claim=invalid, evidence=evidence()), bundle=bundle(), structures=structures())
    invalid = claim(kind="calculation", body="2", evidence_ids=[U5], formula="1" * 600)
    with pytest.raises(DeepReviewValidationError, match="calculation_replay_failed"):
        validate_deep_review_stage(stage(claim=invalid, evidence=evidence()), bundle=bundle(), structures=structures())


def _report() -> dict:
    sections = []
    for key in ("project_overview", "eligibility_matrix", "scope_deliverables", "requirements_matrix", "evaluation_strategy", "delivery_plan", "technical_integration_risks", "security_legal_contract_risks", "economics_scenarios", "competitive_proposal_strategy", "questions_internal_actions", "document_bundle_limitations"):
        sections.append({"section_key": key, "title": key, "blocks": []})
    sections.append({"section_key": "decision_card", "title": "decision", "blocks": [{"block_id": "decision", "type": "decision_card", "title": "decision", "body": "fixture", "claim_ids": [U4], "rows": []}]})
    return {"schema": "bidops.deep-review-report.v1", "deep_review_id": U, "notice_id": 1, "bundle_id": U3, "profile_version_id": U, "policy_version_id": U2, "sections": sections, "system_recommendation": "조건부 추진 검토", "claims": [claim(evidence_ids=[U5])], "unknowns": [], "validation_summary": {"status": "passed", "failed": 0, "warnings": 0, "passed": 1}, "created_at": "2026-08-25T00:00:00+09:00"}


def test_report_requires_exact_sections_and_decision_card() -> None:
    report = _report()
    assert validate_deep_review_report(report, bundle=bundle(), evidence=[evidence()], structures=structures())["schema"] == "bidops.deep-review-report.v1"
    report["sections"] = report["sections"][:-1]
    with pytest.raises(DeepReviewValidationError, match="report_sections_incomplete"):
        validate_deep_review_report(report, bundle=bundle(), evidence=[evidence()], structures=structures())


def test_report_factual_content_requires_claim_ids_and_rejects_duplicate_block_and_row_ids() -> None:
    report = _report()
    report["sections"][0]["blocks"] = [{"block_id": "b1", "type": "paragraph", "title": None, "body": "fact", "claim_ids": [], "rows": []}]
    with pytest.raises(DeepReviewValidationError, match="report_body_claims_required"):
        validate_deep_review_report(report, bundle=bundle(), evidence=[evidence()], structures=structures())
    report = _report()
    report["sections"][0]["blocks"] = [{"block_id": "b1", "type": "matrix", "title": None, "body": None, "claim_ids": [], "rows": [{"row_key": "r1", "label": "fact", "cells": ["value"], "claim_ids": []}]}]
    with pytest.raises(DeepReviewValidationError, match="report_cells_claims_required"):
        validate_deep_review_report(report, bundle=bundle(), evidence=[evidence()], structures=structures())
    report = _report()
    duplicate = {"block_id": "dup", "type": "paragraph", "title": None, "body": None, "claim_ids": [], "rows": []}
    report["sections"][0]["blocks"] = [duplicate]
    report["sections"][1]["blocks"] = [dict(duplicate)]
    with pytest.raises(DeepReviewValidationError, match="duplicate_report_block_id"):
        validate_deep_review_report(report, bundle=bundle(), evidence=[evidence()], structures=structures())
    report = _report()
    row_block = {"block_id": "matrix", "type": "matrix", "title": None, "body": None, "claim_ids": [], "rows": [{"row_key": "dup-row", "label": "x", "cells": [], "claim_ids": []}]}
    report["sections"][0]["blocks"] = [row_block]
    report["sections"][1]["blocks"] = [{**row_block, "block_id": "matrix-2"}]
    with pytest.raises(DeepReviewValidationError, match="duplicate_report_row_id"):
        validate_deep_review_report(report, bundle=bundle(), evidence=[evidence()], structures=structures())


def test_validation_check_related_ids_must_be_same_review() -> None:
    payload = {"schema": "bidops.deep-review-validation.v1", "validation_run_id": U, "report_revision_id": U2, "status": "failed", "checks": [{"check_type": "scope", "status": "failed", "severity": "차단", "message": "bad", "related_claim_ids": [U4], "related_evidence_ids": [U5]}], "created_at": "2026-08-25T00:00:00+09:00"}
    with pytest.raises(DeepReviewValidationError, match="validation_claim_scope"):
        validate_deep_review_validation(payload, expected_deep_review_id=U, claim_ids=[], evidence_ids=[U5])


def test_validation_related_ids_fail_closed_without_membership_context() -> None:
    payload = {"schema": "bidops.deep-review-validation.v1", "validation_run_id": U, "report_revision_id": U2, "status": "failed", "checks": [{"check_type": "scope", "status": "failed", "severity": "차단", "message": "bad", "related_claim_ids": [U4], "related_evidence_ids": []}], "created_at": "2026-08-25T00:00:00+09:00"}
    with pytest.raises(DeepReviewValidationError, match="validation_claim_context_missing"):
        validate_deep_review_validation(payload)
    with pytest.raises(DeepReviewValidationError, match="validation_claim_scope"):
        validate_deep_review_validation(payload, related_id_scopes={})


def test_schema_dates_are_semantically_valid_not_only_regex_shaped() -> None:
    invalid_structure = structure()
    invalid_structure["created_at"] = "2026-02-30T00:00:00+09:00"
    with pytest.raises(SchemaValidationError):
        validate_payload(invalid_structure, "document-structure")
    invalid_bundle = bundle()
    invalid_bundle["documents"][0]["effective_date_at_confirmation"] = "2026-02-30"
    with pytest.raises(SchemaValidationError):
        validate_payload(invalid_bundle, "document-bundle")
    invalid_report = _report()
    invalid_report["created_at"] = "2026-02-30T00:00:00+09:00"
    with pytest.raises(SchemaValidationError):
        validate_payload(invalid_report, "deep-review-report")
    invalid_validation = {"schema": "bidops.deep-review-validation.v1", "validation_run_id": U, "report_revision_id": U2, "status": "failed", "checks": [], "created_at": "2026-02-30T00:00:00+09:00"}
    with pytest.raises(SchemaValidationError):
        validate_payload(invalid_validation, "deep-review-validation")


def test_failed_final_opinion_requires_acknowledgement_and_reason() -> None:
    payload = {"report_revision_id": U, "validation_run_id": U2, "value": "보류", "reason": "확인 필요", "acknowledged_validation_failure": True, "validation_status_at_opinion": "failed", "claimed_name": "reviewer", "created_at": "2026-08-25T00:00:00+09:00"}
    assert validate_final_opinion_snapshot(payload)["value"] == "보류"
    payload["acknowledged_validation_failure"] = False
    with pytest.raises(DeepReviewValidationError, match="final_opinion_ack_required"):
        validate_final_opinion_snapshot(payload)


def test_chunk_merge_is_sorted_idempotent_and_detects_conflict_and_missing() -> None:
    e = evidence()
    c = claim(evidence_ids=[U5])
    first = stage(claim=c, evidence=e)
    merged = merge_stage_chunks([first], expected_claim_ids=[U4], expected_evidence_ids=[U5], bundle=bundle(), structures=structures())
    assert [item["claim_id"] for item in merged["claims"]] == [U4]
    with pytest.raises(DeepReviewValidationError, match="chunk_duplicate"):
        merge_stage_chunks([first, first], bundle=bundle(), structures=structures())
    conflict = stage(claim={**c, "body": "different"}, evidence=e)
    with pytest.raises(DeepReviewValidationError, match="chunk_conflict"):
        merge_stage_chunks([first, conflict], bundle=bundle(), structures=structures())
    with pytest.raises(DeepReviewValidationError, match="chunk_missing_claim"):
        merge_stage_chunks([stage(evidence=e)], expected_claim_ids=[U4], bundle=bundle(), structures=structures())


def test_chunk_merge_uses_approved_order_and_allows_prior_reference_but_not_redefinition() -> None:
    first_claim = claim(kind="opinion", body="first", reason="reason")
    first_claim["claim_id"] = U4
    second_claim = claim(kind="opinion", body="second", reason="reason")
    second_claim["claim_id"] = U5
    chunk_a = stage(claim=first_claim)
    chunk_b = stage(claim=second_claim)
    merged = merge_stage_chunks([chunk_a, chunk_b], chunk_order_key=lambda chunk: [2, 0] if chunk["claims"][0]["body"] == "first" else [1, 0], bundle=bundle(), structures=structures())
    assert [item["claim_id"] for item in merged["claims"]] == [U5, U4]

    prior = claim(kind="opinion", body="prior", reason="reason")
    prior["claim_id"] = U4
    inferred = claim(kind="inference", body="derived", evidence_ids=[U5], premises=[U4], reason="because")
    inferred["claim_id"] = U3
    current = stage(claim=inferred)
    assert merge_stage_chunks([current], known_claim_ids=[U4], known_evidence_ids=[U5], bundle=bundle(), structures=structures())
    redefined = stage(claim=prior)
    with pytest.raises(DeepReviewValidationError, match="prior_claim_redefinition"):
        merge_stage_chunks([redefined], known_claim_ids=[U4], bundle=bundle(), structures=structures())


def test_pilot_55_52_and_yangsan_evaluation_duty_regressions() -> None:
    expected = json.loads((FIXTURES / "fire_prevention_55.json").read_text())["expected_requirement_ids"]
    observed = json.loads((FIXTURES / "fire_prevention_52.json").read_text())["observed_requirement_ids"]
    inventory = compare_requirement_ids(expected, observed)
    assert inventory.expected_count == 55
    assert inventory.observed_count == 52
    assert len(inventory.missing_ids) == 3
    yangsan = json.loads((FIXTURES / "yangsan_evaluation_duty.json").read_text())
    duties = compare_requirement_ids(yangsan["required_duties"], yangsan["observed_duties"])
    assert duties.missing_ids == ("평가위원 사전교육",)
