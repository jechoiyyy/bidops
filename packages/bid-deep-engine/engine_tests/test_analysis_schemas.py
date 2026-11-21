"""M2-04 분석 결과 스키마 테스트(spec M2-04 T1).

네트워크·LLM을 쓰지 않는다.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from bid_deep_engine.analysis import schemas
from bid_deep_engine.analysis.schemas import (
    ActionCounts,
    ActionRef,
    Analysis,
    ChecklistItem,
    ConfirmRequest,
    DataToConfirm,
    Evidence,
    ExcludedRequest,
    MatchOut,
    Profitability,
    Recommendation,
    RequirementFit,
    RequirementFitOut,
    ReviewActions,
    RfpFacts,
    Risk,
    SynthOut,
)
from bid_deep_engine.company.knowledge import KnowledgeSelection

FORBIDDEN_SCHEMA_KEYS = {"pattern", "minLength", "maxLength", "minimum", "maximum"}


def _walk_keys(node: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            keys |= _walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _walk_keys(item)
    return keys


def _evidence() -> Evidence:
    return Evidence(quote="원문")


def _recommendation(**over: object) -> Recommendation:
    data: dict = {
        "decision": "GO",
        "fit_score": 70,
        "summary": "요약",
        "score_breakdown": {},
    }
    data.update(over)
    return Recommendation(**data)


def test_requirement_fit_req_id_pattern():
    ok = RequirementFit(req_id="SFR-001", fit="FULL", rationale="r")
    assert ok.evidence_portfolio_ids == []
    assert ok.evidence_pages == []
    assert ok.gap_action is None
    assert ok.evidence is None
    for bad in ("bad", "sfr-001", "SFR-1", "SFR-0001", "SF-001", " SFR-001", "SFR-001\n"):
        with pytest.raises(ValidationError):
            RequirementFit(req_id=bad, fit="FULL", rationale="r")


def test_requirement_fit_enum_and_required():
    with pytest.raises(ValidationError):
        RequirementFit(req_id="SFR-001", fit="MAYBE", rationale="r")
    with pytest.raises(ValidationError):
        RequirementFit(req_id="SFR-001", fit="FULL")
    with pytest.raises(ValidationError):
        RequirementFit(fit="FULL", rationale="r")
    for fit in ("FULL", "PARTIAL", "GAP", "UNKNOWN"):
        assert RequirementFit(req_id="SFR-001", fit=fit, rationale="r").fit == fit


def test_requirement_fit_out_has_no_constraints():
    out = RequirementFitOut(req_id="bad", fit="UNKNOWN", rationale="r")
    assert out.req_id == "bad"
    with pytest.raises(ValidationError):
        RequirementFitOut(req_id="SFR-001", fit="MAYBE", rationale="r")


def test_risk_category_seven_and_severity():
    assert set(get_args(schemas.RiskCategory)) == {
        "인력",
        "계약",
        "기술",
        "일정",
        "재무",
        "보안",
        "지역",
    }
    assert set(get_args(schemas.Severity)) == {"H", "M", "L"}
    for category in get_args(schemas.RiskCategory):
        risk = Risk(category=category, severity="H", description="d", evidence=_evidence())
        assert risk.mitigation is None
    with pytest.raises(ValidationError):
        Risk(category="법무", severity="H", description="d", evidence=_evidence())
    with pytest.raises(ValidationError):
        Risk(category="인력", severity="X", description="d", evidence=_evidence())
    with pytest.raises(ValidationError):  # evidence 필수
        Risk(category="인력", severity="H", description="d")


def test_small_models_defaults():
    item = ChecklistItem(item="제안서")
    assert item.due is None and item.source is None
    with pytest.raises(ValidationError):
        DataToConfirm(field="policy.x")
    data = DataToConfirm(field="policy.x", why="필요")
    assert data.field == "policy.x" and data.origin == "legacy"
    prof = Profitability(note="메모")
    assert prof.budget_krw is None and prof.est_mm is None
    with pytest.raises(ValidationError):
        Profitability()


def test_recommendation_decision_and_fit_score_bounds():
    assert set(get_args(schemas.DecisionValue)) == {"GO", "CONDITIONAL_GO", "NO_GO"}
    for decision in ("GO", "CONDITIONAL_GO", "NO_GO"):
        assert _recommendation(decision=decision).decision == decision
    with pytest.raises(ValidationError):
        _recommendation(decision="MAYBE")
    for score in (0, 100):
        assert _recommendation(fit_score=score).fit_score == score
    for score in (-1, 101):
        with pytest.raises(ValidationError):
            _recommendation(fit_score=score)
    rec = _recommendation()
    assert rec.preconditions == [] and rec.why_not == [] and rec.basis == []


def test_confirmation_action_models_are_additive_and_exact():
    ref = ActionRef(source="code", path="analysis.json#/raw_data_to_confirm/0")
    request = ConfirmRequest(
        id="confirm-" + "a" * 64,
        kind="company",
        fields=["company.founded"],
        title="설립일",
        why="창업 특례 판정",
        affects=["field:company.founded"],
        blocking=True,
        completion="법인등기 확인",
        refs=[ref],
    )
    actions = ReviewActions(
        requests=[request],
        excluded=[ExcludedRequest(field="company.name", refs=[ref], reason="confirmed")],
        counts=ActionCounts(
            raw_requests=2,
            active_requests=1,
            excluded_requests=1,
            raw_preparations=0,
            unique_preparations=0,
        ),
    )
    assert actions.schema_version == 1
    assert actions.preparations == []


def test_decision_and_strategy_single_source():
    assert hasattr(schemas, "DecisionValue")
    assert not hasattr(schemas, "Decision")
    assert set(get_args(schemas.StrategyName)) == {"single", "mapreduce"}


def test_synth_out_has_no_decision_fields():
    fields = set(SynthOut.model_fields)
    assert not fields & {"decision", "fit_score", "verdict"}
    assert fields == {
        "risks",
        "profitability",
        "checklist",
        "data_to_confirm",
        "summary",
        "preconditions",
        "why_not",
    }


@pytest.mark.parametrize("model", [MatchOut, SynthOut, RequirementFitOut])
def test_llm_output_models_have_no_constraints(model):
    keys = _walk_keys(model.model_json_schema())
    assert not keys & FORBIDDEN_SCHEMA_KEYS, keys & FORBIDDEN_SCHEMA_KEYS


def test_match_out_and_synth_out_round_trip():
    match = MatchOut(fits=[RequirementFitOut(req_id="bad", fit="GAP", rationale="r")])
    assert MatchOut.model_validate_json(match.model_dump_json()) == match
    synth = SynthOut(
        risks=[Risk(category="인력", severity="H", description="d", evidence=_evidence())],
        profitability=Profitability(budget_krw=999, est_mm=3.5, note="n"),
        checklist=[ChecklistItem(item="i", due="2026-01-01", source=_evidence())],
        data_to_confirm=[DataToConfirm(field="f", why="w")],
        summary="s",
        preconditions=["p"],
        why_not=["w"],
    )
    assert SynthOut.model_validate_json(synth.model_dump_json()) == synth


def test_analysis_fields_and_round_trip():
    assert list(Analysis.model_fields) == [
        "schema_version",
        "slug",
        "model",
        "served_model",
        "strategy",
        "strategy_effective",
        "numeric_facts_unconfirmed",
        "knowledge",
        "company_input_hash",
        "effort",
        "requirement_counts",
        "language_warnings",
        "facts",
        "gates",
        "scores",
        "fits",
        "risks",
        "profitability",
        "checklist",
        "data_to_confirm",
        "raw_data_to_confirm",
        "review_actions",
        "recommendation",
        "synth_output",
        "assessment",
        "stages",
        "citations",
        "usage",
        "created_at",
    ]
    analysis = Analysis(
        slug="s",
        model="m",
        served_model="m",
        strategy="single",
        effort="high",
        facts=RfpFacts(),
        fits=[RequirementFit(req_id="SFR-001", fit="FULL", rationale="r", evidence=_evidence())],
        profitability=Profitability(note="n"),
        recommendation=_recommendation(score_breakdown={"base": 50.0}),
        citations={"total": 1, "verified": 0, "repaired": 0, "unverified": 1},
        usage={
            "calls": 1,
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cost_usd": 0.0123,
        },
        created_at="2026-10-22T10:00:00+09:00",
    )
    assert analysis.schema_version == 1
    assert analysis.numeric_facts_unconfirmed is False  # 기본값(필드 도입 전 산출물도 False)
    assert analysis.company_input_hash is None  # REV-01 이전 산출물 호환
    dumped = analysis.model_dump(mode="json")
    assert list(dumped) == list(Analysis.model_fields)
    assert Analysis.model_validate(json.loads(json.dumps(dumped, ensure_ascii=False))) == analysis
    assert isinstance(dumped["usage"]["calls"], int)
    assert isinstance(dumped["usage"]["cost_usd"], float)


# --- KB-03 T9: evidence_pages·Analysis.knowledge(기존 산출물 호환) ---


def _analysis_kwargs() -> dict:
    return {
        "slug": "s",
        "model": "m",
        "served_model": "m",
        "strategy": "single",
        "effort": "high",
        "facts": RfpFacts(),
        "profitability": Profitability(note="n"),
        "recommendation": _recommendation(),
        "citations": {"total": 0, "verified": 0, "repaired": 0, "unverified": 0},
        "usage": {"calls": 0, "cost_usd": 0.0},
        "created_at": "2026-10-23T10:00:00+09:00",
    }


def test_t9_requirement_fit_evidence_pages_field_order():
    assert list(RequirementFit.model_fields) == [
        "req_id",
        "fit",
        "rationale",
        "evidence_portfolio_ids",
        "evidence_pages",
        "gap_action",
        "evidence",
        "name",
        "definition",
        "instance_key",
    ]
    fit = RequirementFit(req_id="SFR-001", fit="FULL", rationale="r", evidence_pages=["alpha"])
    assert list(fit.model_dump(mode="json")) == list(RequirementFit.model_fields)
    assert RequirementFit.model_validate_json(fit.model_dump_json()) == fit


def test_t9_model_output_schema_unchanged():
    # X7: 모델 출력 스키마에는 지식 인용 필드가 없다(코드가 rationale에서 추출)
    assert list(RequirementFitOut.model_fields) == [
        "req_id",
        "fit",
        "rationale",
        "evidence_portfolio_ids",
        "gap_action",
        "evidence",
    ]
    assert "evidence_pages" not in json.dumps(MatchOut.model_json_schema())


def test_t9_legacy_fit_without_evidence_pages_loads_empty():
    legacy = {"req_id": "SFR-001", "fit": "PARTIAL", "rationale": "r", "evidence_portfolio_ids": []}
    assert RequirementFit.model_validate(legacy).evidence_pages == []


def test_t9_legacy_analysis_without_knowledge_loads_none():
    dumped = Analysis(**_analysis_kwargs()).model_dump(mode="json")
    del dumped["knowledge"]
    loaded = Analysis.model_validate(json.loads(json.dumps(dumped, ensure_ascii=False)))
    assert loaded.knowledge is None


def test_t9_analysis_knowledge_round_trip_includes_hash():
    selection = KnowledgeSelection(
        categories=["homepage-build"],
        category_source="keyword",
        pages=["alpha", "beta"],
        skipped=["gamma"],
        chars=1234,
        knowledge_hash="abc",
    )
    analysis = Analysis(**_analysis_kwargs(), knowledge=selection)
    dumped = analysis.model_dump(mode="json")
    assert list(dumped) == list(Analysis.model_fields)
    assert dumped["knowledge"] == {
        "categories": ["homepage-build"],
        "category_source": "keyword",
        "pages": ["alpha", "beta"],
        "skipped": ["gamma"],
        "chars": 1234,
        "knowledge_hash": "abc",
    }
    assert Analysis.model_validate(json.loads(json.dumps(dumped, ensure_ascii=False))) == analysis
    assert Analysis(**_analysis_kwargs()).model_dump(mode="json")["knowledge"] is None


def test_t9_schemas_import_has_no_cycle():
    # schemas가 KnowledgeSelection을 import해도 새 인터프리터에서 단독 import가 된다(순환 없음)
    for module in ("bid_deep_engine.analysis.schemas", "bid_deep_engine.company.knowledge"):
        proc = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
    source = (Path(schemas.__file__).parents[1] / "company" / "knowledge.py").read_text("utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert "bid_deep_engine.company.past_labels" in imported  # 수집이 동작하는지(빈 집합 방지)
    assert not any(m == "bid_deep_engine.analysis" or m.startswith("bid_deep_engine.analysis.") for m in imported)
