"""REV-02 단계 지문과 현재 권고 가능 여부의 오프라인 계약."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bid_deep_engine.analysis.provenance import (
    STAGE_INPUT_KEYS,
    STAGE_VERSIONS,
    canonical_reasons,
    code_parameters,
    execution_ref,
    gate_ref,
    make_stage_stamp,
    readiness_hash,
    readiness_payload,
    readiness_rules_hash,
    rfp_input_hash,
    stage_input_hash,
    stage_input_payload,
    stage_output_hash,
    stage_output_payload,
    write_run_state,
)
from bid_deep_engine.analysis.review import assess_analysis, build_review, policy_conflicts
from bid_deep_engine.analysis.schemas import Assessment, Conflict, Evidence, GateResult, StageParameters
from bid_deep_engine.company.provenance import CompanyEvidenceView
from engine_tests.gate_factories import confirmed_view, make_profile, rule, staffing
from engine_tests.gate_factories import make_facts as gate_facts
from engine_tests.report_factory import (
    SCORE_BREAKDOWN,
    make_analysis,
    make_fit,
    make_gate,
    make_recommendation,
    make_rfp,
    write_slug,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _hashes(*keys: str) -> dict[str, str]:
    return {key: f"{index:x}" * 64 for index, key in enumerate(keys, start=1)}


def test_t1_exact_stage_keys_versions_and_golden_payload_hashes():
    expected = {
        "facts": ("rfp", "prompts", "model_settings"),
        # 설계 2026-10-25-past-performance-capability 2.1: 실적 지식 텍스트 해시
        "gates": ("facts", "company", "confirmations", "as_of", "portfolio_knowledge"),
        "scores": ("facts", "company", "as_of"),
        "fits": ("facts", "requirements", "company", "knowledge", "prompts", "model_settings"),
        "synth": (
            "facts",
            "gates",
            "scores",
            "fits",
            "company",
            "knowledge",
            "prompts",
            "model_settings",
        ),
        "requests": ("facts", "gates", "scores", "fits", "synth", "company", "readiness"),
        "recommendation": (
            "facts",
            "gates",
            "scores",
            "fits",
            "synth",
            "company",
            "readiness_rules",
            "readiness",
        ),
    }
    assert STAGE_INPUT_KEYS == expected
    assert STAGE_VERSIONS == {
        "facts": "extract-v1",
        "gates": "gates-v3",
        "scores": "scores-v1",
        "fits": "match-v1",
        "synth": "synth-v1",
        "requests": "requests-v2",
        "recommendation": "recommendation-v2",
    }

    inputs = _hashes(*expected["requests"])
    assert stage_input_payload("requests", inputs) == {
        "schema_version": 1,
        "stage": "requests",
        "version": "requests-v2",
        "inputs": inputs,
    }
    assert stage_input_hash("requests", inputs) == (
        "1839e4031f7fa6f15a72efcf20c430adc506b1d72805d2f254981d9261a9e1ab"
    )
    with pytest.raises(ValueError, match="exactly"):
        stage_input_hash("requests", {**inputs, "recommendation": "f" * 64})

    first = make_stage_stamp(
        "requests",
        inputs=inputs,
        output={"data_to_confirm": [], "raw_data_to_confirm": None, "review_actions": None},
        parameters=code_parameters(),
        computed_at="2026-10-24T10:00:00+09:00",
    )
    later = make_stage_stamp(
        "requests",
        inputs=inputs,
        output={"data_to_confirm": [], "raw_data_to_confirm": None, "review_actions": None},
        parameters=code_parameters(),
        computed_at="2026-10-24T11:00:00+09:00",
    )
    assert first.input_hash == later.input_hash
    assert first.output_hash == later.output_hash
    assert first.computed_at != later.computed_at


def test_t1_output_hash_excludes_only_recursive_location_projection():
    base = {
        "items": [
            {
                "evidence": {
                    "quote": "원문",
                    "section_id": "S001",
                    "page": 7,
                    "verified": True,
                    "repaired": False,
                    "locations": [],
                    "location_status": "unavailable",
                }
            }
        ],
        "nullable": None,
    }
    moved = json.loads(json.dumps(base, ensure_ascii=False))
    moved["items"][0]["evidence"]["locations"] = [
        {"file": "a.pdf", "file_sha256": "a" * 64, "page": 2, "start": 1, "end": 3}
    ]
    moved["items"][0]["evidence"]["location_status"] = "exact"
    assert stage_output_payload("fits", base) == stage_output_payload("fits", moved)
    assert stage_output_hash("fits", base) == stage_output_hash("fits", moved)
    assert stage_output_hash("fits", base) == (
        "5369f6db11b6630d88348861d8f549100df9fd9230f7b2d516dd6a785f815e48"
    )

    for key, value in (("page", 8), ("verified", False), ("quote", "다른 원문")):
        changed = json.loads(json.dumps(base, ensure_ascii=False))
        changed["items"][0]["evidence"][key] = value
        assert stage_output_hash("fits", changed) != stage_output_hash("fits", base)
    reversed_items = {"items": list(reversed([*base["items"], {"x": 1}]))}
    forward_items = {"items": [*base["items"], {"x": 1}]}
    assert stage_output_hash("fits", reversed_items) != stage_output_hash("fits", forward_items)
    assert stage_output_hash("fits", {"locations": ["business-site"]}) != stage_output_hash(
        "fits", {"locations": []}
    )


def test_t1_rfp_source_order_and_bytes_matter_but_collection_time_does_not(tmp_path):
    document = json.loads((FIXTURES / "rfp_req3.json").read_text(encoding="utf-8"))
    document["source_files"] = ["a.hwpx", "b.pdf"]
    rfp_path = tmp_path / "rfp.json"
    rfp_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    bundle = {
        "slug": document["slug"],
        "title": document["title"],
        "manifest_matched": True,
        "files": [
            {
                "path": "a.hwpx",
                "format": "hwpx",
                "role": "primary",
                "size_bytes": 1,
                "sha256": "a" * 64,
            },
            {
                "path": "b.pdf",
                "format": "pdf",
                "role": "reference",
                "size_bytes": 1,
                "sha256": "b" * 64,
            },
        ],
        "primary_format": "hwpx",
        "status": "ok",
        "warnings": [],
        "created_at": "2026-10-24T10:00:00+09:00",
    }
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    original = rfp_input_hash(rfp_path)

    bundle["created_at"] = "2030-01-01T00:00:00+09:00"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    assert rfp_input_hash(rfp_path) == original

    bundle["files"].reverse()
    document["source_files"].reverse()
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    rfp_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    assert rfp_input_hash(rfp_path) != original


def test_t1_readiness_payload_is_deterministic_and_has_no_consumer_cycle():
    assessment = Assessment(
        state="abstain",
        decision=None,
        reason_codes=["stale_stage", "missing_fits"],
        score_interval=None,
    )
    reasons = [
        {
            "code": "missing_fits",
            "stage": "fits",
            "refs": ["fit:SFR-002", "fit:SFR-001", "fit:SFR-002"],
            "message": "요구사항 적합도 누락",
        },
        {
            "code": "stale_stage",
            "stage": "facts",
            "refs": ["stage:facts"],
            "message": "이전 입력 기준",
        },
    ]
    states = {
        "facts": "stale",
        "gates": "current",
        "scores": "current",
        "fits": "current",
        "synth": "unknown",
        "requests": "stale",
        "recommendation": "stale",
    }
    payload = readiness_payload(assessment, reasons, states)
    assert list(payload["stage_states"]) == ["facts", "gates", "scores", "fits", "synth"]
    assert "requests" not in payload["stage_states"]
    assert "recommendation" not in payload["stage_states"]
    assert payload["reasons"] == canonical_reasons(reversed(reasons))
    assert readiness_hash(assessment, reasons, states) == (
        "1ccb6c0c4e63d9dbc333b6756a0948f569f1086fdcf04a8cc67f8ccf84da2e6f"
    )
    assert readiness_rules_hash() == (
        "7c4a5dcc7eab958858c70101b9c61460e4588c9054e43e74cd9a0d244fbc76c1"
    )


def test_t1_reference_ids_are_stable_and_legacy_gate_does_not_guess():
    assert gate_ref("OTHER", None) == "stage:gates"
    assert gate_ref("SME_CERT", "a" * 64) == f"gate:SME_CERT:{'a' * 64}"
    assert execution_ref("  검토\t제목  ") == execution_ref("검토 제목")
    assert execution_ref("  검토 제목 ") == execution_ref("검토 제목")
    assert execution_ref("검토 제목") == (
        "execution:99d0c16892c8c716ae87d5911548db2eba56e041eae03f1e7e2c70a8df446bb2"
    )


def test_t1_stage_parameters_do_not_use_environment_preferences():
    code = StageParameters(
        model=None,
        strategy=None,
        effort=None,
        knowledge_root=None,
        knowledge_categories=[],
        knowledge_category_source="none",
    )
    assert code.model_dump(mode="json", exclude={"model_fingerprint"}) == {
        "model": None,
        "strategy": None,
        "effort": None,
        "knowledge_root": None,
        "knowledge_categories": [],
        "knowledge_category_source": "none",
    }
    with pytest.raises(ValidationError, match="inactive knowledge"):
        StageParameters(
            model="m",
            strategy="single",
            effort="high",
            knowledge_root="/tmp/knowledge",
            knowledge_categories=[],
            knowledge_category_source="none",
        )


def test_t5_run_state_exact_schema_and_replaces_last_attempt(tmp_path):
    write_run_state(
        tmp_path,
        phase="synth",
        at="2026-10-24T15:01:02+09:00",
        outcome="failed",
        error="LlmCallError: api error: InternalServerError status=500",
    )
    first = json.loads((tmp_path / "run_state.json").read_text(encoding="utf-8"))
    assert first == {
        "schema_version": 1,
        "last_attempt": {
            "phase": "synth",
            "at": "2026-10-24T15:01:02+09:00",
            "outcome": "failed",
            "error": "LlmCallError: api error: InternalServerError status=500",
        },
    }
    write_run_state(
        tmp_path,
        phase="regate",
        at="2026-10-24T15:02:03+09:00",
        outcome="success",
        error=None,
    )
    second = json.loads((tmp_path / "run_state.json").read_text(encoding="utf-8"))
    assert second["last_attempt"] == {
        "phase": "regate",
        "at": "2026-10-24T15:02:03+09:00",
        "outcome": "success",
        "error": None,
    }
    assert list(tmp_path.iterdir()) == [tmp_path / "run_state.json"]


def _states(**overrides):
    states = {
        "facts": "current",
        "gates": "current",
        "scores": "current",
        "fits": "current",
        "synth": "current",
        "requests": "unknown",
        "recommendation": "unknown",
    }
    states.update(overrides)
    return states


def _decision_view():
    paths = {
        "policy.min_contract_amount_krw": 0,
        "policy.target_gross_margin_pct": 20,
        "policy.seoul_resident_ok": True,
        "policy.max_concurrent_new_projects": 10,
        "policy.no_bid_if": [],
        "policy.preferred_domains": [],
    }
    profile = make_profile(paths)
    return confirmed_view(profile, paths)


def _score_recommendation(decision: str, score: int, rule_name: str = "score"):
    breakdown = {
        **SCORE_BREAKDOWN,
        "fit_score": score,
        "decision_rule": rule_name,
        "gate_counts": {"PASS": 1, "FAIL": 0, "UNKNOWN": 0, "RISK": 0},
        "policy_unknown": [],
    }
    return make_recommendation(decision=decision, fit_score=score, score_breakdown=breakdown)


def test_t2_legacy_empty_requirements_abstains_without_rewriting_history(tmp_path):
    original = make_analysis(
        fits=[], recommendation=_score_recommendation("NO_GO", 20), synth_output=None
    )
    slug_dir = write_slug(tmp_path, "legacy", analysis=original, rfp=make_rfp(requirements=[]))
    before = (slug_dir / "analysis.json").read_bytes()

    review = build_review(slug_dir)

    assert review["assessment"].state == "abstain"
    assert review["assessment"].decision is None
    assert review["legacy_recommendation"].decision == "NO_GO"
    assert review["legacy_recommendation"].fit_score == 20
    assert review["last_success_at"] is None
    assert review["stage_states"]["facts"] == "unknown"
    assert review["stage_states"]["synth"] == "missing"
    assert "empty_requirements" in review["assessment"].reason_codes
    # PF-01: 회사가 지정되지 않으면 잠정 결론은 없다.
    assert review["assessment"].provisional is None
    assert (slug_dir / "analysis.json").read_bytes() == before


def test_t2_invalid_stage_metadata_does_not_turn_existing_outputs_into_missing(tmp_path):
    analysis = make_analysis()
    payload = analysis.model_dump(mode="json")
    payload["stages"] = {"gates": {"invalid": True}}
    slug_dir = write_slug(
        tmp_path,
        "legacy",
        analysis_text=json.dumps(payload, ensure_ascii=False),
        rfp=make_rfp(),
    )

    review = build_review(slug_dir)

    assert review["stage_states"]["gates"] == "unknown"
    assert review["stage_states"]["gates"] != "missing"
    assert review["legacy_recommendation"] == analysis.recommendation
    assert any(
        reason["code"] == "legacy_metadata" and reason["stage"] == "gates"
        for reason in review["reasons"]
    )


def test_t3_only_source_trusted_deterministic_fail_shortcuts_missing_stages():
    evidence = Evidence(quote="나라장터 미등록", section_id="S001", verified=True)
    facts = gate_facts(eligibility=[rule("G2B_REGISTERED", evidence=evidence)])
    profile = make_profile({"registrations.g2b.registered": False})
    view = confirmed_view(profile, ["registrations.g2b.registered"])
    from bid_deep_engine.analysis.gates import evaluate_gates, resolve_as_of

    gates = evaluate_gates(facts, view, as_of=resolve_as_of(facts)[0])
    analysis = make_analysis(
        facts=facts,
        gates=gates,
        fits=[make_fit("SFR-001", "FULL")],
        recommendation=_score_recommendation("NO_GO", 100, "gate_fail"),
    )
    assessment, reasons = assess_analysis(
        analysis,
        _states(scores="missing", synth="missing"),
        ["SFR-001"],
        company=view,
    )

    assert (assessment.state, assessment.decision, assessment.score_interval) == (
        "ready",
        "NO_GO",
        None,
    )
    assert "hard_gate_fail" in assessment.reason_codes
    assert "missing_stage" in assessment.reason_codes
    assert any(reason["code"] == "hard_gate_fail" for reason in reasons)
    # PF-01: 같은 입력의 잠정 결론도 신뢰 FAIL로 포기이고 재확인 조건이 없다.
    assert assessment.provisional is not None
    assert (assessment.provisional.decision, assessment.provisional.conditions) == ("NO_GO", [])


def test_t3_demo_or_human_other_fail_is_untrusted_and_abstains():
    evidence = Evidence(quote="나라장터 미등록", section_id="S001", verified=True)
    facts = gate_facts(eligibility=[rule("G2B_REGISTERED", evidence=evidence)])
    profile = make_profile({"registrations.g2b.registered": False})
    confirmed = confirmed_view(profile, ["registrations.g2b.registered"])
    from bid_deep_engine.analysis.gates import evaluate_gates, resolve_as_of

    [stored] = evaluate_gates(facts, confirmed, as_of=resolve_as_of(facts)[0])
    for gate, company in (
        (stored, CompanyEvidenceView(profile)),
        (
            GateResult(
                code="OTHER",
                rule_text="해석 불가 조항",
                company_value="사람 확인 FAIL: 확인",
                verdict="FAIL",
                evidence=[evidence],
            ),
            confirmed,
        ),
    ):
        analysis = make_analysis(
            facts=facts,
            gates=[gate],
            fits=[make_fit("SFR-001", "FULL")],
            recommendation=_score_recommendation("NO_GO", 100, "gate_fail"),
        )
        assessment, _ = assess_analysis(analysis, _states(), ["SFR-001"], company=company)
        assert assessment.state == "abstain"
        assert assessment.decision is None
        assert "untrusted_failure" in assessment.reason_codes


def _leveled(profile, levels):
    from bid_deep_engine.company.provenance import ProvenanceDocument, resolve_profile_path, value_hash

    fields = {
        path: {
            "level": level,
            "sources": [{"kind": "user", "ref": "demo-as-real synthetic fixture"}],
            "value_hash": value_hash(resolve_profile_path(profile, path)),
            "checked_at": None,
            "note": None,
        }
        for path, level in levels.items()
    }
    return CompanyEvidenceView(
        profile, ProvenanceDocument.model_validate({"schema_version": 1, "fields": fields})
    )


def test_t3_demo_fail_input_is_trusted_like_confirmed_but_unknown_is_not():
    """신뢰 FAIL 입력 판정은 confirmed 또는 demo다(2026-10-25). unknown 입력은 여전히 불신."""
    evidence = Evidence(quote="나라장터 미등록", section_id="S001", verified=True)
    facts = gate_facts(eligibility=[rule("G2B_REGISTERED", evidence=evidence)])
    profile = make_profile({"registrations.g2b.registered": False})
    demo = _leveled(profile, {"registrations.g2b.registered": "demo"})
    from bid_deep_engine.analysis.gates import evaluate_gates, resolve_as_of

    gates = evaluate_gates(facts, demo, as_of=resolve_as_of(facts)[0])
    assert [g.verdict for g in gates] == ["FAIL"]
    analysis = make_analysis(
        facts=facts,
        gates=gates,
        fits=[make_fit("SFR-001", "FULL")],
        recommendation=_score_recommendation("NO_GO", 100, "gate_fail"),
    )
    assessment, _ = assess_analysis(analysis, _states(), ["SFR-001"], company=demo)
    assert (assessment.state, assessment.decision) == ("ready", "NO_GO")
    assert "hard_gate_fail" in assessment.reason_codes
    assert "untrusted_failure" not in assessment.reason_codes
    assert assessment.provisional is not None
    assert (assessment.provisional.decision, assessment.provisional.conditions) == ("NO_GO", [])
    assert assessment.provisional.basis == "confirmed"
    assert assessment.provisional.demo_fields == ["registrations.g2b.registered"]

    unknown = _leveled(profile, {"registrations.g2b.registered": "unknown"})
    assessment, _ = assess_analysis(analysis, _states(), ["SFR-001"], company=unknown)
    assert assessment.state == "abstain"
    assert "untrusted_failure" in assessment.reason_codes


def test_t3_demo_min_contract_shortcut_is_trusted():
    profile = make_profile({"policy.min_contract_amount_krw": 200})
    view = _leveled(profile, {"policy.min_contract_amount_krw": "demo"})
    evidence = Evidence(quote="사업금액 100원", section_id="S001", verified=True)
    facts = gate_facts(budget_krw=100)
    facts.project.evidence = [evidence]
    analysis = make_analysis(
        facts=facts,
        gates=[],
        fits=[make_fit("SFR-001", "FULL")],
        recommendation=_score_recommendation("NO_GO", 100, "min_contract_amount"),
    )
    assessment, _ = assess_analysis(
        analysis, _states(scores="missing", synth="missing"), ["SFR-001"], company=view
    )
    assert (assessment.state, assessment.decision) == ("ready", "NO_GO")
    assert "min_contract_fail" in assessment.reason_codes

    unknown = _leveled(profile, {"policy.min_contract_amount_krw": "unknown"})
    unknown_assessment, _ = assess_analysis(
        analysis, _states(scores="missing", synth="missing"), ["SFR-001"], company=unknown
    )
    assert "min_contract_fail" not in unknown_assessment.reason_codes


def test_t3_unknown_gate_lists_only_non_demo_inputs_as_untrusted():
    """UNKNOWN 게이트의 불신 회사 입력 사유는 confirmed·demo가 아닌 경로만 가리킨다."""
    evidence = Evidence(quote="확인서 소지", section_id="S001", verified=True)
    facts = gate_facts(eligibility=[rule("SME_CERT", evidence=evidence)])
    profile = make_profile(
        {
            "registrations.sme_certificate.status": "valid",
            "registrations.sme_certificate.valid_until": "2030-01-01",
        }
    )
    view = _leveled(
        profile,
        {
            "registrations.sme_certificate.status": "demo",
            "registrations.sme_certificate.valid_until": "public",
        },
    )
    from bid_deep_engine.analysis.gates import evaluate_gates, resolve_as_of

    gates = evaluate_gates(facts, view, as_of=resolve_as_of(facts)[0])
    assert [g.verdict for g in gates] == ["UNKNOWN"]
    analysis = make_analysis(facts=facts, gates=gates, fits=[make_fit("SFR-001", "FULL")])
    _, reasons = assess_analysis(analysis, _states(), ["SFR-001"], company=view)
    [untrusted] = [r for r in reasons if r["code"] == "untrusted_company_input"]
    assert "field:registrations.sme_certificate.valid_until" in untrusted["refs"]
    assert "field:registrations.sme_certificate.status" not in untrusted["refs"]


def test_t3_only_conflict_for_the_failed_gate_blocks_hard_no_go():
    from bid_deep_engine.analysis.gates import evaluate_gates, resolve_as_of

    failed_evidence = Evidence(quote="나라장터 미등록", section_id="S001", verified=True)
    other_evidence = Evidence(quote="중소기업 확인서", section_id="S002", verified=True)
    facts = gate_facts(
        eligibility=[
            rule("G2B_REGISTERED", evidence=failed_evidence),
            rule("SME_CERT", evidence=other_evidence),
        ]
    )
    profile = make_profile({"registrations.g2b.registered": False})
    view = confirmed_view(profile, ["registrations.g2b.registered"])
    gates = evaluate_gates(facts, view, as_of=resolve_as_of(facts)[0])

    unrelated = facts.model_copy(deep=True)
    unrelated.conflicts = [
        Conflict(
            field="eligibility[1].params.cert_name",
            values=["A", "B"],
            evidence=[other_evidence],
        )
    ]
    analysis = make_analysis(
        facts=unrelated,
        gates=gates,
        fits=[make_fit("SFR-001", "FULL")],
        recommendation=_score_recommendation("NO_GO", 100, "gate_fail"),
    )
    trusted, _ = assess_analysis(analysis, _states(), ["SFR-001"], company=view)
    assert (trusted.state, trusted.decision) == ("ready", "NO_GO")
    assert "hard_gate_fail" in trusted.reason_codes

    related = unrelated.model_copy(deep=True)
    related.conflicts[0] = related.conflicts[0].model_copy(
        update={"field": "eligibility[0].params.keyword"}
    )
    untrusted, _ = assess_analysis(
        analysis.model_copy(update={"facts": related}),
        _states(),
        ["SFR-001"],
        company=view,
    )
    assert untrusted.state == "abstain"
    assert "untrusted_failure" in untrusted.reason_codes


def test_t3_reclassified_other_uses_original_rule_identity_for_indexed_conflict():
    from bid_deep_engine.analysis.gates import evaluate_gates, resolve_as_of

    source = Evidence(
        quote="부도·파산·회생절차 중에 있지 아니한 업체",
        section_id="S001",
        verified=True,
    )
    facts = gate_facts(
        eligibility=[
            rule(
                "OTHER",
                "부도·파산·회생절차 중에 있지 아니한 업체",
                evidence=source,
            )
        ]
    )
    facts.conflicts = [
        Conflict(
            field="eligibility[0].params.keyword",
            values=["부도", "파산"],
            evidence=[Evidence(quote="서로 다른 충돌 인용", section_id="S002", verified=True)],
        )
    ]
    profile = make_profile({"registrations.insolvency": "active"})
    view = confirmed_view(profile, ["registrations.insolvency"])
    gates = evaluate_gates(facts, view, as_of=resolve_as_of(facts)[0])
    assert [(gate.code, gate.verdict) for gate in gates] == [("INSOLVENCY", "FAIL")]
    analysis = make_analysis(
        facts=facts,
        gates=gates,
        fits=[make_fit("SFR-001", "FULL")],
        recommendation=_score_recommendation("NO_GO", 100, "gate_fail"),
    )

    assessment, _ = assess_analysis(
        analysis,
        _states(),
        ["SFR-001"],
        company=view,
    )

    assert (assessment.state, assessment.decision) == ("abstain", None)
    assert "untrusted_failure" in assessment.reason_codes
    assert "hard_gate_fail" not in assessment.reason_codes


def test_t3_confirmed_min_contract_shortcut_rejects_pdf_and_budget_conflict():
    profile = make_profile({"policy.min_contract_amount_krw": 200})
    view = confirmed_view(profile, ["policy.min_contract_amount_krw"])
    evidence = Evidence(quote="사업금액 100원", section_id="S001", verified=True)
    facts = gate_facts(budget_krw=100)
    facts.project.evidence = [evidence]
    base = make_analysis(
        facts=facts,
        gates=[],
        fits=[make_fit("SFR-001", "FULL")],
        recommendation=_score_recommendation("NO_GO", 100, "min_contract_amount"),
    )
    assessment, reasons = assess_analysis(
        base, _states(scores="missing", synth="missing"), ["SFR-001"], company=view
    )
    assert (assessment.state, assessment.decision) == ("ready", "NO_GO")
    min_reason = next(reason for reason in reasons if reason["code"] == "min_contract_fail")
    assert min_reason["refs"] == [
        "field:policy.min_contract_amount_krw",
        "notice:/project/budget_krw",
    ]

    pdf = base.model_copy(update={"numeric_facts_unconfirmed": True}, deep=True)
    pdf_assessment, _ = assess_analysis(
        pdf, _states(scores="missing", synth="missing"), ["SFR-001"], company=view
    )
    assert pdf_assessment.state == "abstain"

    conflict = facts.model_copy(deep=True)
    conflict.conflicts = [
        Conflict(
            field="project.budget_krw",
            values=["100", "300"],
            evidence=[evidence],
        )
    ]
    conflicted = base.model_copy(update={"facts": conflict})
    conflict_assessment, _ = assess_analysis(
        conflicted,
        _states(scores="missing", synth="missing"),
        ["SFR-001"],
        company=view,
    )
    assert conflict_assessment.state == "abstain"


@pytest.mark.parametrize(
    ("rule_name", "known", "expected_interval", "expected_state"),
    [
        ("guarded", ["GAP", "UNKNOWN"], (0, 50), "abstain"),
        ("score", ["PARTIAL", "UNKNOWN"], (25, 75), "abstain"),
        ("score", ["FULL", "FULL", "FULL", "UNKNOWN"], (75, 100), "ready"),
    ],
)
def test_t4_partial_unknown_uses_existing_decision_branches(
    rule_name, known, expected_interval, expected_state
):
    fits = [make_fit(f"SFR-{index:03d}", value) for index, value in enumerate(known, 1)]
    legacy_decision = "GO" if rule_name == "score" and known[0] == "FULL" else "CONDITIONAL_GO"
    analysis = make_analysis(
        gates=[make_gate("G2B_REGISTERED", "PASS")],
        fits=fits,
        recommendation=_score_recommendation(legacy_decision, expected_interval[1], rule_name),
    )
    assessment, _ = assess_analysis(
        analysis,
        _states(),
        [fit.req_id for fit in fits],
        company=_decision_view(),
    )
    assert (assessment.score_interval.min, assessment.score_interval.max) == expected_interval
    assert assessment.state == expected_state
    assert ("uncertain_fit_decision" in assessment.reason_codes) == (expected_state == "abstain")


def test_t4_all_unknown_and_id_mismatch_abstain_but_risk_only_does_not():
    all_unknown = make_analysis(
        gates=[make_gate("G2B_REGISTERED", "PASS")],
        fits=[make_fit("SFR-001", "UNKNOWN")],
        recommendation=_score_recommendation("CONDITIONAL_GO", 50),
    )
    decision_view = _decision_view()
    assessment, _ = assess_analysis(all_unknown, _states(), ["SFR-001"], company=decision_view)
    assert assessment.score_interval is None
    assert "missing_fits" in assessment.reason_codes

    mismatch, reasons = assess_analysis(all_unknown, _states(), ["SFR-002"], company=decision_view)
    refs = next(reason["refs"] for reason in reasons if reason["code"] == "missing_fits")
    assert refs == ["fit:SFR-001", "fit:SFR-002"]
    assert mismatch.state == "abstain"

    risk = make_analysis(
        gates=[make_gate("ONSITE_LOCATION", "RISK", evidence=[])],
        fits=[make_fit("SFR-001", "FULL")],
        recommendation=_score_recommendation("CONDITIONAL_GO", 90, "guarded"),
    )
    risk_assessment, _ = assess_analysis(risk, _states(), ["SFR-001"], company=decision_view)
    assert (risk_assessment.state, risk_assessment.decision) == (
        "ready",
        "CONDITIONAL_GO",
    )


@pytest.mark.parametrize(
    ("fits_values", "gates", "rule_name", "expected_interval", "expected"),
    [
        (
            ["FULL", "FULL", "PARTIAL", "UNKNOWN", "UNKNOWN"],
            [make_gate("ONSITE_LOCATION", "RISK", evidence=[])],
            "guarded",
            (40, 80),
            ("ready", "CONDITIONAL_GO"),
        ),
        (
            ["FULL", "FULL", "UNKNOWN", "UNKNOWN", "UNKNOWN"],
            [make_gate("G2B_REGISTERED", "PASS")],
            "score",
            (40, 100),
            ("abstain", None),
        ),
        (
            [*["FULL"] * 7, *["UNKNOWN"] * 3],
            [make_gate("G2B_REGISTERED", "PASS")],
            "score",
            (70, 100),
            ("ready", "GO"),
        ),
    ],
)
def test_t4_partial_unknown_shares_exact_40_and_70_boundaries(
    fits_values, gates, rule_name, expected_interval, expected
):
    fits = [make_fit(f"SFR-{index:03d}", value) for index, value in enumerate(fits_values, 1)]
    legacy_decision = expected[1] or "GO"
    analysis = make_analysis(
        gates=gates,
        fits=fits,
        recommendation=_score_recommendation(
            legacy_decision,
            expected_interval[1],
            rule_name,
        ),
    )

    assessment, _ = assess_analysis(
        analysis,
        _states(),
        [fit.req_id for fit in fits],
        company=_decision_view(),
    )

    assert (assessment.score_interval.min, assessment.score_interval.max) == expected_interval
    assert (assessment.state, assessment.decision) == expected


def test_t4_current_known_inputs_do_not_reuse_stale_audit_recommendation():
    analysis = make_analysis(
        gates=[make_gate("G2B_REGISTERED", "PASS")],
        fits=[make_fit("SFR-001", "FULL")],
        recommendation=_score_recommendation("NO_GO", 0, "score"),
    )
    before = analysis.recommendation.model_dump_json()

    assessment, _ = assess_analysis(
        analysis,
        _states(recommendation="stale"),
        ["SFR-001"],
        company=_decision_view(),
    )

    assert (assessment.state, assessment.decision) == ("ready", "GO")
    assert (assessment.score_interval.min, assessment.score_interval.max) == (100, 100)
    assert analysis.recommendation.model_dump_json() == before


def test_t4_partial_unknown_same_endpoint_uses_current_decision_not_legacy_label():
    fits = [
        make_fit(f"SFR-{index:03d}", value)
        for index, value in enumerate([*["FULL"] * 7, *["UNKNOWN"] * 3], 1)
    ]
    analysis = make_analysis(
        gates=[make_gate("G2B_REGISTERED", "PASS")],
        fits=fits,
        recommendation=_score_recommendation("NO_GO", 0, "score"),
    )

    assessment, _ = assess_analysis(
        analysis,
        _states(recommendation="stale"),
        [fit.req_id for fit in fits],
        company=_decision_view(),
    )

    assert (assessment.state, assessment.decision) == ("ready", "GO")
    assert (assessment.score_interval.min, assessment.score_interval.max) == (70, 100)


def test_rev02_t6_policy_conflict_only_for_confirmed_seoul_employee_residency():
    profile = make_profile({"policy.seoul_resident_ok": False})
    company = confirmed_view(profile, ["policy.seoul_resident_ok"])
    onsite_evidence = Evidence(
        quote="PM 1명은 서울 발주기관에 상주", section_id="S010", page=7, verified=True
    )
    onsite = staffing(
        "PM",
        count=1,
        resident=True,
        location="외교부 청사(서울)",
        evidence=onsite_evidence,
    )
    conflicts = policy_conflicts(gate_facts(staffing=[onsite]), company)
    assert [item.model_dump(mode="json") for item in conflicts] == [
        {
            "code": "seoul_onsite",
            "company_fields": ["policy.seoul_resident_ok"],
            "evidence": [onsite_evidence.model_dump(mode="json")],
            "message": "서울 직원 상주 요구가 확인된 회사 방침과 충돌합니다.",
        }
    ]

    on_premise = staffing(
        "서버 설치",
        count=1,
        resident=False,
        location="서울 데이터센터",
        notes="on-premise 장비 설치",
    )
    agency_only = staffing("기술지원", count=1, resident=None, location="서울 발주기관")
    assert policy_conflicts(gate_facts(staffing=[on_premise, agency_only]), company) == []
    assert policy_conflicts(gate_facts(staffing=[onsite]), CompanyEvidenceView(profile)) == []
    # 데모값 방침도 확인값과 같이 충돌로 보인다(2026-10-25). unknown 수준은 보이지 않는다.
    demo = _leveled(profile, {"policy.seoul_resident_ok": "demo"})
    assert [item.code for item in policy_conflicts(gate_facts(staffing=[onsite]), demo)] == [
        "seoul_onsite"
    ]
    unknown = _leveled(profile, {"policy.seoul_resident_ok": "unknown"})
    assert policy_conflicts(gate_facts(staffing=[onsite]), unknown) == []
