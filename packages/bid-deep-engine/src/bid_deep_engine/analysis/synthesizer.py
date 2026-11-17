"""Pass3 synth: 리스크·수익성·체크리스트·전제조건 서술(spec M2-04 "Pass3 synth", 시트 7절·X22·X47).

LLM은 요약·전제조건·리스크 서술만 낸다(사용자 결정 7) — `SynthOut`에는 결정·점수·판정 필드가 없고,
결정은 `recommend.recommend`가 코드로 계산한다. `synthesize`는 어떤 전략인지 모르고 받은
`document`를 그대로 `LlmClient.parse`(`tracing.traced_parse` 경유, OBS-02)에 넘긴다.
어떤 document를 줄지는 `synth_document`가 고른다
(single = `build_document(doc)`로 Pass1·Pass2와 바이트 동일 → 캐시 프리픽스 공유,
mapreduce = 빈 문서 → 입력은 instruction의 JSON뿐이라 256k 안전).
M3-01·M3-02는 `synth_document`를 import한다.

실패 예외는 잡지 않고 그대로 올린다. 호출자가 `exc.record`를 usage에 남긴다(X3).
"""

import json

from bid_deep_engine.analysis.document import build_document
from bid_deep_engine.analysis.evidence import model_dump_for_llm, verify
from bid_deep_engine.analysis.extractor import prompt_bytes
from bid_deep_engine.analysis.llm import CallRecord, LlmClient
from bid_deep_engine.analysis.matcher import render_profile
from bid_deep_engine.analysis.schemas import (
    GateResult,
    RequirementFit,
    RfpFacts,
    ScoreEstimate,
    StrategyName,
    SynthOut,
)
from bid_deep_engine.analysis.tracing import Tracer, traced_parse
from bid_deep_engine.company.provenance import CompanyEvidenceView
from bid_deep_engine.company.schema import CompanyProfile
from bid_deep_engine.ingest.models import RfpDocument


def build_synth_inputs(
    facts: RfpFacts,
    gates: list[GateResult],
    scores: list[ScoreEstimate],
    fits: list[RequirementFit],
    profile_summary: str,
    knowledge_text: str = "",
) -> str:
    """Pass3 instruction: synth.md + 프로필 요약 + (회사 지식 발췌) + 분석 입력 JSON.

    `knowledge_text`가 비어 있으면 지식 절이 없고, fits JSON에서 `evidence_pages`를 제외하므로
    KB 이전과 바이트 동일하다(X71). synth는 페이지 근거를 발췌 본문으로 직접 본다.
    """
    fit_payload = [model_dump_for_llm(fit) for fit in fits]
    for fit in fit_payload:
        fit.pop("evidence_pages", None)
    payload = {
        "facts": model_dump_for_llm(facts),
        "gates": [model_dump_for_llm(g) for g in gates],
        "scores": [model_dump_for_llm(s) for s in scores],
        "fits": fit_payload,
    }
    knowledge = f"\n\n## 회사 지식(발췌)\n{knowledge_text}" if knowledge_text != "" else ""
    return (
        prompt_bytes("synth.md").decode("utf-8")
        + "\n\n## 회사 기록·출처·확인 수준\n"
        + profile_summary
        + knowledge
        + "\n\n## 분석 입력(JSON)\n```json\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        + "\n```"
    )


def synth_document(strategy_effective: StrategyName, doc: RfpDocument) -> str:
    """Pass3 parse의 document. single은 Pass1·Pass2와 같은 문자열, mapreduce는 빈 문서(X22·X47)."""
    if strategy_effective == "single":
        return build_document(doc)
    return ""


def postprocess_synth(
    out: SynthOut, doc: RfpDocument, facts: RfpFacts
) -> tuple[SynthOut, list[str]]:
    """리스크·체크리스트 인용을 verify하고 예산을 facts 값으로 덮어쓴다. 입력 `out`은 바꾸지 않는다.

    verify가 실패해도 항목은 유지한다(verified=false). 경고는 `"synth: risks[<i>]: <경고>"`,
    `"synth: checklist[<i>]: <경고>"` 형식이다.
    """
    result = out.model_copy(deep=True)
    warnings: list[str] = []
    for i, risk in enumerate(result.risks):
        risk.evidence, ev_warnings = verify(risk.evidence, doc.full_text, doc.sections)
        warnings.extend(f"synth: risks[{i}]: {w}" for w in ev_warnings)
    for i, item in enumerate(result.checklist):
        if item.source is None:
            continue
        item.source, ev_warnings = verify(item.source, doc.full_text, doc.sections)
        warnings.extend(f"synth: checklist[{i}]: {w}" for w in ev_warnings)
    # ``origin`` is code-owned provenance.  A structured model response may contain any enum
    # value, so overwrite every validated SynthOut request rather than trusting model choice.
    for item in result.data_to_confirm:
        item.origin = "llm"
    result.profitability.budget_krw = facts.project.budget_krw
    return result, warnings


def synthesize(
    doc: RfpDocument,
    facts: RfpFacts,
    gates: list[GateResult],
    scores: list[ScoreEstimate],
    fits: list[RequirementFit],
    profile: CompanyProfile | CompanyEvidenceView,
    *,
    client: LlmClient,
    model: str,
    effort: str,
    slug: str,
    document: str,
    knowledge_text: str = "",
    tracer: Tracer | None = None,
) -> tuple[SynthOut, list[CallRecord], list[str]]:
    """Pass3: 호출 1회. 반환 (후처리된 SynthOut, [record], warnings)(X21).

    `tracer` None이면 기록 없음(`NullTracer`).
    """
    result = traced_parse(
        tracer,
        client,
        purpose="synth",
        output_model=SynthOut,
        system=prompt_bytes("system.md").decode("utf-8"),
        document=document,
        instruction=build_synth_inputs(
            facts, gates, scores, fits, render_profile(profile), knowledge_text
        ),
        model=model,
        effort=effort,
        slug=slug,
    )
    parsed = result.parsed
    assert isinstance(parsed, SynthOut)  # output_model=SynthOut의 결과
    out, warnings = postprocess_synth(parsed, doc, facts)
    return out, [result.record], warnings
