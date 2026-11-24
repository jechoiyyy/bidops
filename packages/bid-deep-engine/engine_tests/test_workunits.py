"""Work-unit evidence from frozen company pages through the offline pipeline."""

import json
from dataclasses import replace

import pytest

from bid_deep_engine import runner
from bid_deep_engine.analysis.llm import LlmCallError, LlmOutputError, LlmRefusal, LlmTruncated, OutputFailure
from bid_deep_engine.analysis.pipeline import run_notice
from bid_deep_engine.analysis.provenance import canonical_hash
from bid_deep_engine.analysis.schemas import Analysis
from bid_deep_engine.analysis.workunits import (
    WorkUnitAssignmentsOut,
    link_portfolio,
    parse_work_unit_map,
    render_work_unit_evidence,
    summarize_assignments,
)
from bid_deep_engine.company.knowledge import (
    PORTFOLIO_EXCERPT_CHARS,
    lint_knowledge,
    render_knowledge,
    select_pages,
)
from engine_tests.gate_factories import confirmed_view, make_profile
from engine_tests.report_factory import make_rfp, write_bundle
from engine_tests.test_runner import make_bundle_payload

TOPIC_PAGE = """---
slug: work-search
title: 업무 근거 — 검색
kind: capability
tags: [업무 근거]
sources: [합성 출처]
confidence: confirmed
---

## 범위

- 검색과 검색 운영
- 전체 지도: [[work-units]]

## 업무 단위별 근거

### 통합 검색

- 단위 id: `search.integrated`
- 범위: 여러 자료를 검색한다. 다른 단위: 검색 로그 점검
- [[P2025-01]] SFR-101, PER-102
- [[P2025-02]] SFR-101
- [[P2025-03]] SFR-101

### 검색 운영

- 단위 id: `search.operations`
- 범위: 검색 로그를 점검한다.
- [[P2025-01]] PER-102
- [[P2025-03]] SFR-101
- [[P2030-01]] PER-103

### 검색 이관

- 단위 id: `search.migrate`
- 범위: 검색 자료를 이관한다.
- [[P2030-01]] SFR-103
"""
HUB_PAGE = """---
slug: work-units
title: 업무 근거 지도
kind: capability
---
## 주제
- [[work-search]]
"""
ROWS = [
    {"req_id": "SFR-001", "units": ["search.integrated", "search.operations"], "uncovered": []},
    {"req_id": "SFR-002", "units": ["search.migrate", "search.operations"], "uncovered": ["연구 자료 정제"]},
    {"req_id": "SFR-003", "units": [], "uncovered": ["시설 점검"]},
]


@pytest.fixture
def payload():
    payload = make_bundle_payload()
    bundle = payload["company_bundle"]
    pages = bundle["knowledge"]
    pages["capabilities/work-search.md"] = TOPIC_PAGE
    pages["capabilities/work-units.md"] = HUB_PAGE
    pages["INDEX.md"] += "- [[work-search]]\n- [[work-units]]\n"
    original = pages["portfolio/P2025-01.md"]
    pages["portfolio/P2025-01.md"] += (
        "\n### 요구사항 전체 목록(원문)\n\n"
        + "- SFR-101 검색 기능 " + "가" * 800 + "\n"
        + "- SFR-1010 접두어만 일치하는 다른 기능\n"
        + "- PER-102 검색 운영 " + "나" * 800 + "\n"
        + "- DAR-100 공고의 통합검색 기능과 단어만 비슷한 줄\n"
    )
    for n in ("02", "03"):
        slug = f"P2025-{n}"
        bundle["files"]["synthetic.portfolio.yaml"] += f"- id: {slug}\n  title: 다른 합성 실적 {n}\n  client: 합성기관\n"
        pages[f"portfolio/{slug}.md"] = (
            original.replace("P2025-01", slug).replace("합성 홈페이지 구축 실적", f"다른 실적 {n}")
            + "\n### 요구사항 전체 목록(원문)\n\n- SFR-101 여러 자료를 검색한다.\n"
        )
        pages["INDEX.md"] += f"- [[{slug}]]\n"
    return payload


@pytest.fixture
def company(tmp_path, payload):
    return runner.company_inputs(payload, tmp_path)


@pytest.fixture
def rfp():
    return make_rfp(requirements=[(row["req_id"], f"합성 요구사항 {i}") for i, row in enumerate(ROWS)])


def test_map_parses_real_page_format_and_filters_missing_projects(company):
    knowledge = company.knowledge
    assert any("broken link [[P2030-01]]" in error for error in lint_knowledge(knowledge.root).errors)
    unfiltered = replace(
        knowledge, pages={
            **knowledge.pages,
            "work-search": replace(knowledge.pages["work-search"], body=TOPIC_PAGE.split("---", 2)[2]),
        },
    )
    work_map = parse_work_unit_map(unfiltered)
    assert work_map == parse_work_unit_map(knowledge)
    assert work_map.basis_projects == 3
    assert [(t.slug, t.title, t.scope) for t in work_map.topics] == [
        ("work-search", "검색", "검색과 검색 운영"),
    ]
    assert work_map.units["search.integrated"].evidence == (
        ("P2025-01", "SFR-101"), ("P2025-01", "PER-102"), ("P2025-02", "SFR-101"),
        ("P2025-03", "SFR-101"),
    )
    assert work_map.units["search.operations"].evidence == (("P2025-01", "PER-102"), ("P2025-03", "SFR-101"))
    assert work_map.units["search.migrate"].evidence == ()
    assert "## search — 검색: 검색과 검색 운영" in work_map.taxonomy()
    assert "- search.integrated | 통합 검색 | 여러 자료를 검색한다. | 아님: 검색 로그 점검" in work_map.taxonomy()


def test_link_rank_excerpt_budget_and_rendering(company):
    knowledge = company.knowledge
    work_map = parse_work_unit_map(knowledge)
    output = WorkUnitAssignmentsOut.model_validate({"assignments": ROWS})
    summary = summarize_assignments(work_map, output, None)
    related, excerpts = link_portfolio(knowledge, work_map, summary)
    assert related == ["P2025-01", "P2025-03", "P2025-02"]
    assert excerpts == {"P2025-01": [2], "P2025-02": [0], "P2025-03": [0]}
    selection = select_pages(
        knowledge, ["other"], related_override=related, excerpt_override=excerpts,
    )
    text = render_knowledge(knowledge, selection)
    assert selection.chars == len(text)
    assert "- PER-102 검색 운영" in text
    assert "- SFR-101 검색 기능" not in text
    assert "- SFR-1010 " not in text
    assert "- DAR-100 " not in text
    chosen = next(line for line in text.splitlines() if line.startswith("- PER-102 "))
    assert len(chosen) + 1 <= PORTFOLIO_EXCERPT_CHARS
    assert "업무 근거 지도가 이번 공고와 연결한 1줄만 옮겼다. 옮기지 않은 줄도 수행한 범위다." in text
    section = render_work_unit_evidence(work_map, summary)
    assert section.splitlines() == [
        "## 요구사항별 업무 근거(업무 근거 지도, 실적 3건 기준)",
        "- SFR-001: 통합 검색(search.integrated) ← [[P2025-01]] SFR-101, "
        "[[P2025-01]] PER-102, [[P2025-02]] SFR-101, [[P2025-03]] SFR-101 / "
        "검색 운영(search.operations) ← [[P2025-01]] PER-102, [[P2025-03]] SFR-101",
        "- SFR-002: 검색 이관(search.migrate) ← 지도 범위(실적 3건) 안 근거 없음 → 판단 보류 / "
        "검색 운영(search.operations) ← [[P2025-01]] PER-102, [[P2025-03]] SFR-101 / "
        "단위에 들지 않는 부분: 연구 자료 정제",
        "- SFR-003: 어느 업무 단위에도 해당하지 않음 — 시설 점검",
    ]


class ScriptedClient(runner.MockTransport):
    def __init__(self, rfp, outputs, gap_rationales=None):
        super().__init__(rfp)
        self.outputs = iter(outputs)
        self.requests = []
        self.gap_rationales = gap_rationales or {}

    def parse(self, output_model, *, purpose, **kwargs):
        self.requests.append((purpose, kwargs))
        record = super().parse(output_model, purpose=purpose, **kwargs)
        if purpose == "units":
            output = next(self.outputs)
            if output == "call_failed":
                raise LlmCallError("private request details")
            if output == "output_error":
                raise LlmOutputError(
                    self.rfp.slug, purpose, record=record.record,
                    failure=OutputFailure(response_text="private", json_text=None, validation_errors=[],
                                          error_count=0, kind="no_json"),
                )
            if output == "truncated":
                raise LlmTruncated(self.rfp.slug, purpose, 10, record=record.record, response_text="private")
            if output == "refused":
                raise LlmRefusal(self.rfp.slug, purpose, record=record.record)
            record.parsed.assignments = output_model.model_validate({"assignments": output}).assignments
        elif purpose == "match":
            for fit in record.parsed.fits:
                if fit.req_id in self.gap_rationales:
                    fit.fit = "GAP"
                    fit.rationale = self.gap_rationales[fit.req_id]
        return record


def run_pipeline(tmp_path, rfp, client, company, *, passes=("extract", "match", "synth")):
    out = tmp_path / "work"
    write_bundle(out, rfp.slug)
    source = out / "rfp.json"
    source.write_text(rfp.model_dump_json(), encoding="utf-8")
    result = run_notice(
        source, out, client_factory=lambda: client, profile=company.profile,
        knowledge=company.knowledge, model="mock_reference", effort="high", strategy="single",
        passes=passes, force=True, company_input_hash=company.profile.company_input_hash,
    )
    assert result.status == "ok", result.reason
    return result, json.loads((out / "analysis.json").read_text()), out


def test_pipeline_repair_success_records_one_classification_for_match_and_synth(tmp_path, company, rfp):
    rfp.requirements[0].details = "가" * 1500 + "제외되는 뒷부분"
    client = ScriptedClient(rfp, [ROWS[:1], ROWS], {
        "SFR-001": "근거 없는 모의 판정",
        "SFR-003": "업무 근거 지도(실적 3건 기준)의 어느 업무 단위에도 해당하는 수행 기록이 없다. 시설 점검",
    })
    result, analysis, out = run_pipeline(tmp_path, rfp, client, company)
    assert [call.purpose for call in result.calls] == ["extract", "units", "units", "match", "synth"]
    _, first = client.requests[1]
    _, repair = client.requests[2]
    assert first["document"] == repair["document"]
    assert "가" * 1500 in first["document"] and "제외되는 뒷부분" not in first["document"]
    assert "앞선 답과 검사 결과" in repair["instruction"]
    assert "SFR-001, SFR-002, SFR-003" in repair["instruction"]
    evidence = render_work_unit_evidence(
        parse_work_unit_map(company.knowledge), Analysis.model_validate(analysis).work_units,
    )
    assert all(evidence in call["instruction"] for _, call in client.requests[-2:])
    assert "match: gap without work-unit or profile basis (SFR-001)" in result.warnings
    assert "match: gap without work-unit or profile basis (SFR-003)" not in result.warnings
    assert analysis["fits"][0]["fit"] == "GAP"  # diagnostics do not rewrite a model verdict
    assert analysis["work_units"] == {
        "basis_projects": 3, "status": "classified", "reason": None,
        "assignments": [
            {**ROWS[0], "evidence_projects": ["P2025-01", "P2025-02", "P2025-03"]},
            {**ROWS[1], "evidence_projects": ["P2025-01", "P2025-03"]},
            {**ROWS[2], "evidence_projects": []},
        ],
    }
    assert analysis["stages"]["fits"]["inputs"]["work_units"] == canonical_hash({"assignments": ROWS})
    assert "stale_stage" not in analysis["assessment"]["reason_codes"]
    fits_meta = json.loads((out / "fits.json").read_text())["meta"]
    assert "units" in fits_meta["prompt_hashes"]
    usage = json.loads((out / "usage.json").read_text())
    assert [call["purpose"] for call in usage["calls"]] == ["extract", "units", "units", "match", "synth"]
    synth_only = ScriptedClient(rfp, [])
    _, replayed, _ = run_pipeline(tmp_path, rfp, synth_only, company, passes=("synth",))
    assert [purpose for purpose, _ in synth_only.requests] == ["synth"]
    assert evidence in synth_only.requests[0][1]["instruction"]
    assert replayed["work_units"] == analysis["work_units"]


@pytest.mark.parametrize("bad", [
    ROWS[:1],
    list(reversed(ROWS)),
    [{**ROWS[0], "units": ["search.invented"]}, *ROWS[1:]],
    [ROWS[0], ROWS[0], ROWS[2]],
])
def test_invalid_assignments_retry_once_and_fall_back(tmp_path, company, rfp, bad):
    client = ScriptedClient(rfp, [bad, bad])
    result, analysis, out = run_pipeline(tmp_path, rfp, client, company)
    assert [purpose for purpose, _ in client.requests] == ["extract", "units", "units", "match", "synth"]
    assert analysis["work_units"] == {
        "basis_projects": 3, "status": "unavailable", "reason": "invalid_assignments", "assignments": [],
    }
    warning = "units: classification unavailable: invalid_assignments"
    assert warning in result.warnings
    assert warning in json.loads((out / "usage.json").read_text())["warnings"]["match"]
    assert analysis["stages"]["fits"]["inputs"]["work_units"] is None
    assert all(fit["fit"] == "UNKNOWN" for fit in analysis["fits"])
    assert all("\n## 요구사항별 업무 근거" not in call["instruction"] for _, call in client.requests[-2:])


@pytest.mark.parametrize("reason", ["call_failed", "output_error", "truncated", "refused"])
def test_call_failures_keep_billed_records_and_safe_warning(tmp_path, company, rfp, reason):
    client = ScriptedClient(rfp, [reason])
    result, analysis, _ = run_pipeline(tmp_path, rfp, client, company)
    assert [purpose for purpose, _ in client.requests] == ["extract", "units", "match", "synth"]
    assert [call.purpose for call in result.calls].count("units") == (0 if reason == "call_failed" else 1)
    assert analysis["work_units"]["reason"] == reason
    assert f"units: classification unavailable: {reason}" in result.warnings
    assert "private" not in " ".join(result.warnings)
    assert all(fit["fit"] != "GAP" for fit in analysis["fits"])


def test_profile_gap_with_confirmed_negative_value_has_a_basis(tmp_path, company, rfp):
    path = "registrations.g2b.registered"
    profile = confirmed_view(make_profile({path: False}, portfolio=[
        item.model_dump(mode="json") for item in company.profile.profile.portfolio
    ]), [path])
    client = ScriptedClient(rfp, [ROWS], {"SFR-001": f"{path}가 false로 확인되어 등록 요건 미충족"})
    result, _, _ = run_pipeline(tmp_path, rfp, client, replace(company, profile=profile))
    assert "match: gap without work-unit or profile basis (SFR-001)" not in result.warnings


def test_mock_runner_with_projected_map_creates_no_gap(payload):
    output = runner.execute(payload)
    assert output["status"] == "partial", output.get("error_code")
    analysis = output["analysis"]
    assert analysis["work_units"]["status"] == "unavailable"
    assert analysis["work_units"]["basis_projects"] == 3
    assert all(fit["fit"] != "GAP" for fit in analysis["fits"])
    assert analysis["usage"]["calls"] == 5
    assert "stale_stage" not in analysis["assessment"]["reason_codes"]


def test_map_absent_keeps_legacy_analysis_json(tmp_path):
    payload = make_bundle_payload()
    company = runner.company_inputs(payload, tmp_path)
    assert parse_work_unit_map(company.knowledge) is None
    analysis = runner.execute(payload)["analysis"]
    assert "work_units" not in analysis
    assert analysis["stages"]["fits"]["inputs"]["work_units"] is None


def test_no_requirements_skips_classification_even_with_map(tmp_path, company):
    rfp = make_rfp(requirements=[])
    client = ScriptedClient(rfp, [])
    _, analysis, _ = run_pipeline(tmp_path, rfp, client, company)
    assert [purpose for purpose, _ in client.requests] == ["extract", "synth"]
    assert "work_units" not in analysis
    assert analysis["stages"]["fits"]["inputs"]["work_units"] is None


def test_requirement_without_units_or_uncovered_is_not_rendered_as_no_record():
    """내용 없는 요구사항(분류 기준 3)은 수행 기록 없음이 아니라 판단 보류다."""
    from types import SimpleNamespace

    work_map = SimpleNamespace(basis_projects=3, units={})
    summary = SimpleNamespace(assignments=[
        SimpleNamespace(req_id="SFR-009", units=[], uncovered=[]),
        SimpleNamespace(req_id="SFR-010", units=[], uncovered=["시설 점검"]),
    ])
    assert render_work_unit_evidence(work_map, summary).splitlines()[1:] == [
        "- SFR-009: 분류할 업무 내용 없음(판단 보류)",
        "- SFR-010: 어느 업무 단위에도 해당하지 않음 — 시설 점검",
    ]
