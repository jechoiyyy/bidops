"""Pass1 single 추출기(spec M2-02 "추출기 Pass1 single").

문서 문자열은 `build_document`만 쓴다(계약 시트 13절 X1). 호출은 `LlmClient.parse` 한 번
(`tracing.traced_parse` 경유, OBS-02 — `tracer` None이면 기록 없음)이고,
응답의 인용은 `verify_facts`로 원문과 대조한다. 실패 예외(`LlmRefusal`·`LlmTruncated`·
`LlmOutputError`·`LlmCallError`)는 그대로 전파한다.
"""

from dataclasses import dataclass

from bid_deep_engine.analysis.document import Chunk, build_document
from bid_deep_engine.analysis.evidence import Citations, verify_facts
from bid_deep_engine.analysis.llm import CallRecord, LlmClient, ParseResult
from bid_deep_engine.analysis.merge import merge_partials
from bid_deep_engine.analysis.prompt_files import PROMPTS_DIR as PROMPTS_DIR  # 기존 import 경로 유지
from bid_deep_engine.analysis.prompt_files import prompt_bytes as prompt_bytes
from bid_deep_engine.analysis.schemas import RfpFacts, RfpFactsPartial
from bid_deep_engine.analysis.tracing import Tracer, traced_parse
from bid_deep_engine.ingest.models import RfpDocument

PDF_PRIMARY_WARNING = "primary format is pdf: numeric facts unconfirmed"


@dataclass(frozen=True)
class ExtractResult:
    facts: RfpFacts
    citations: Citations
    warnings: list[str]
    call: CallRecord  # ParseResult.record
    served_model: str


def extract_inputs(doc: RfpDocument) -> tuple[str, str, str]:
    """Pass1 single 입력 (system, document, instruction). `plan_calls`와 실행이 공유한다(X46)."""
    return (
        prompt_bytes("system.md").decode("utf-8"),
        build_document(doc),
        prompt_bytes("extract.md").decode("utf-8"),
    )


def partial_inputs(chunk: Chunk) -> tuple[str, str, str]:
    """Pass1 mapreduce chunk 입력 (system, document, instruction). 요구사항 블록은 없다."""
    return (
        prompt_bytes("system.md").decode("utf-8"),
        chunk.text,
        prompt_bytes("extract_partial.md").decode("utf-8"),
    )


def _pass1_warnings(
    verify_warnings: list[str], doc: RfpDocument, results: list[ParseResult]
) -> list[str]:
    """Pass1 경고(X49, single·mapreduce 공통): verify → pdf primary → max_price served_model마다."""
    warnings = list(verify_warnings)
    if doc.primary_format == "pdf":
        warnings.append(PDF_PRIMARY_WARNING)  # 값은 그대로 두고 표시만(제약 4)
    unpriced = dict.fromkeys(r.served_model for r in results if r.record.cost_basis == "max_price")
    warnings.extend(f"unpriced served model {m}: cost at max known price" for m in unpriced)
    return warnings


def finish_partials(results: list[ParseResult], doc: RfpDocument) -> ExtractResult:
    """Pass1 mapreduce: chunk 응답(문서 순서)을 코드로 병합하고 인용을 검증한다(conflicts 포함).

    병합할 응답이 없으면 `MergeError`. 인용 통계는 conflicts를 제외한다(X10).
    """
    partials: list[RfpFactsPartial] = []
    for r in results:
        assert isinstance(r.parsed, RfpFactsPartial)  # output_model=RfpFactsPartial의 결과
        partials.append(r.parsed)
    facts, citations, verify_warnings = verify_facts(merge_partials(partials), doc)
    return ExtractResult(
        facts=facts,
        citations=citations,
        warnings=_pass1_warnings(verify_warnings, doc, results),
        call=results[-1].record,
        served_model=results[-1].served_model,
    )


def finish_extract(result: ParseResult, doc: RfpDocument) -> ExtractResult:
    """Pass1 single 응답을 인용 검증하고 경고(verify → pdf primary → max_price)를 붙인다."""
    parsed = result.parsed
    assert isinstance(parsed, RfpFacts)  # output_model=RfpFacts의 결과
    facts, citations, verify_warnings = verify_facts(parsed, doc)
    warnings = _pass1_warnings(verify_warnings, doc, [result])
    return ExtractResult(
        facts=facts,
        citations=citations,
        warnings=warnings,
        call=result.record,
        served_model=result.served_model,
    )


def extract_single(
    doc: RfpDocument,
    client: LlmClient,
    *,
    model: str,
    effort: str,
    tracer: Tracer | None = None,
) -> ExtractResult:
    """문서 하나를 한 번의 호출로 추출하고 인용을 검증한다. phase는 클라이언트에 고정되어 있다."""
    system, document, instruction = extract_inputs(doc)
    result = traced_parse(
        tracer,
        client,
        purpose="extract",
        output_model=RfpFacts,
        system=system,
        document=document,
        instruction=instruction,
        model=model,
        effort=effort,
        slug=doc.slug,
    )
    return finish_extract(result, doc)
