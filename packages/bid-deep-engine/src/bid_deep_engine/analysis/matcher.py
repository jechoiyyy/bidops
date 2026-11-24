"""Pass2 match: 요구사항 적합도(spec M2-04 "Pass2 match", "프로필 요약", 계약 시트 7절·X21).

single 경로는 요구사항 전체를 한 번의 `LlmClient.parse`(`tracing.traced_parse` 경유, OBS-02)로
분류한다. document는 `build_document`
(X1 — Pass1과 바이트 동일, 캐시 프리픽스 공유), system은 M2-01 공통 프롬프트(X8, 수정 금지),
phase는 클라이언트에 고정되어 있다(X2). 응답(`MatchOut`)은 `postprocess_fits`가 코드 규칙으로
정리해 저장 모델 `RequirementFit`으로 바꾼다. M3-01 mapreduce는 `build_match_instruction`·
`postprocess_fits`를 묶음 단위로 재사용한다(X21·X30).

실패 예외(`LlmRefusal`·`LlmTruncated`·`LlmOutputError` — `record` 보유, `LlmCallError`)는
잡지 않고 그대로 올린다. 호출자가 `exc.record`를 usage에 남긴다(X3).
"""

import yaml

from bid_deep_engine.analysis.document import build_document
from bid_deep_engine.analysis.evidence import table_quote_spans, verify
from bid_deep_engine.analysis.extractor import prompt_bytes
from bid_deep_engine.analysis.llm import CallRecord, LlmClient, ParseResult
from bid_deep_engine.analysis.schemas import (
    QUOTE_MAX_CHARS,
    Evidence,
    MatchOut,
    RequirementFit,
    RequirementFitOut,
    RfpFacts,
)
from bid_deep_engine.analysis.tracing import Tracer, traced_parse
from bid_deep_engine.company.provenance import CompanyEvidenceView
from bid_deep_engine.company.schema import CompanyProfile
from bid_deep_engine.ingest.models import Requirement, RfpDocument

PROFILE_HEADER = '# 회사 기록·출처·확인 수준 — 값 "unknown"은 미확인(추정 금지), null은 해당 없음'
PROVENANCE_HEADER = "## 필드별 출처·확인 수준"
NO_RESPONSE_RATIONALE = "LLM 미응답"
NO_REQUIREMENTS_WARNING = "no requirements: match skipped"


def _scalar(value: object) -> str:
    """실적 표 칸 값. YAML 절과 같게 bool은 true/false, None은 null."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _raw_profile(profile: CompanyProfile | CompanyEvidenceView) -> CompanyProfile:
    return profile.profile if isinstance(profile, CompanyEvidenceView) else profile


def render_profile(profile: CompanyProfile | CompanyEvidenceView) -> str:
    """Pass2·Pass3 공통 회사 기록과 필드별 확인 수준(결정적)."""
    view = profile if isinstance(profile, CompanyEvidenceView) else None
    raw = _raw_profile(profile)
    data = raw.model_dump(mode="json", exclude={"portfolio", "provenance_file"})
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).rstrip("\n")
    lines = [PROFILE_HEADER, body, f"## 실적 ({len(raw.portfolio)}건)"]
    for p in raw.portfolio:
        cells = [
            p.id,
            p.client,
            p.client_type,
            p.title,
            p.type,
            ",".join(p.domain),
            f"{_scalar(p.period.start)}~{_scalar(p.period.end)}",
            p.amount_krw,
            p.role,
            f"completed={_scalar(p.completed)}",
        ]
        lines.append("- " + " | ".join(_scalar(c) for c in cells))
    lines.append(PROVENANCE_HEADER)
    if view is None or view.provenance is None:
        lines.append("- sidecar 없음: 모든 필드 확인 수준 unknown")
    else:
        # note/checked_at/source kind처럼 아래 요약에 직접 노출하지 않는 provenance 변경도
        # 실제 LLM 입력(및 provider prompt-cache key)을 바꾸도록 canonical 지문을 포함한다.
        lines.append(f"- company_input_hash={view.company_input_hash}")
        lines.append("- 아래에 없는 필드의 확인 수준은 unknown")
        for path, entry in view.provenance.fields.items():
            evidence = view.get(path)
            refs = ", ".join(source.ref for source in entry.sources) or "-"
            lines.append(
                f"- {path} | level={entry.level} | "
                f"effective_level={evidence['effective_level']} | sources={refs}"
            )
    return "\n".join(lines)



def profile_gap_paths(profile: CompanyProfile | CompanyEvidenceView) -> list[str]:
    """Paths with a current, explicitly negative profile value usable by match."""
    if not isinstance(profile, CompanyEvidenceView) or profile.provenance is None:
        return []
    paths = []
    for path in profile.provenance.fields:
        item = profile.get(path)
        if item["effective_level"] not in ("confirmed", "demo", "public"):
            continue
        value = item["value"]
        if value is False or value == [] or value == "none":
            paths.append(path)
    return paths

def build_match_instruction(
    requirements: list[Requirement], profile_summary: str, knowledge_text: str = ""
) -> str:
    """match.md + 프로필 요약 + (회사 지식 발췌) + 평가 대상 요구사항 ID(주어진 순서).

    mapreduce는 묶음만 넘긴다. `knowledge_text`(KB-01 `render_knowledge` 결과 그대로)가 비어 있으면
    지식 절을 만들지 않아 KB 이전과 바이트 동일하다(X71).
    """
    ids = ", ".join(r.key for r in requirements)
    knowledge = f"\n\n## 회사 지식(발췌)\n{knowledge_text}" if knowledge_text != "" else ""
    return (
        prompt_bytes("match.md").decode("utf-8")
        + "\n\n## 회사 기록·출처·확인 수준\n"
        + profile_summary
        + knowledge
        + f"\n\n## 평가 대상 요구사항 ID ({len(requirements)}건)\n"
        + ids
    )


def postprocess_fits(
    out: MatchOut,
    doc: RfpDocument,
    profile: CompanyProfile | CompanyEvidenceView,
    *,
    scope_ids: list[str],
) -> tuple[list[RequirementFit], list[str]]:
    """LLM 응답을 코드 규칙(spec 1~8단계, 이 순서)으로 정리한다. 입력 `out`은 바꾸지 않는다."""
    requirements = {r.key: r for r in doc.requirements}
    missing = [i for i in scope_ids if i not in requirements]
    if missing:
        raise ValueError(f"scope_ids not in document requirements: {', '.join(missing)}")
    scope = set(scope_ids)
    warnings: list[str] = []

    # 1. scope 밖 req_id 제거
    items: list[RequirementFitOut] = []
    for item in out.fits:
        if item.req_id not in scope:
            warnings.append(f"match: unknown req_id dropped: {item.req_id}")
            continue
        items.append(item.model_copy(deep=True))

    # 2. 중복 req_id는 첫 항목만
    seen: dict[str, RequirementFitOut] = {}
    for item in items:
        if item.req_id in seen:
            warnings.append(f"match: duplicate req_id: {item.req_id}")
            continue
        seen[item.req_id] = item
    items = list(seen.values())

    # 3. 프로필 portfolio에 없는 실적 id 제거
    known_ids = {p.id for p in _raw_profile(profile).portfolio}
    for item in items:
        kept: list[str] = []
        for pid in item.evidence_portfolio_ids:
            if pid in known_ids:
                kept.append(pid)
            else:
                warnings.append(f"match: unknown portfolio id removed: {pid} ({item.req_id})")
        item.evidence_portfolio_ids = kept

    # 4. 응답 없는 scope_ids는 UNKNOWN
    for req_id in scope_ids:
        if req_id not in seen:
            item = RequirementFitOut(req_id=req_id, fit="UNKNOWN", rationale=NO_RESPONSE_RATIONALE)
            seen[req_id] = item
            items.append(item)
            warnings.append(f"match: no response for {req_id}")

    # 5. 빈 인용은 요구사항 명칭으로 채움(제약 1)
    for item in items:
        if item.evidence is None:
            req = requirements[item.req_id]
            item.evidence = Evidence(quote=req.name[:QUOTE_MAX_CHARS], section_id=req.section_id)

    # 6. 모든 인용 verify(실패해도 항목 유지, verified=false)
    tables = {table.id: table for table in doc.tables}
    for item in items:
        assert item.evidence is not None  # 5단계에서 채움
        if item.evidence.quote.lstrip().startswith("|"):
            req = requirements[item.req_id]
            table = tables.get(req.table_id)
            matched = bool(
                table
                and item.evidence.section_id in (None, req.section_id)
                and table_quote_spans(item.evidence.quote, table.rows)
            )
            item.evidence = item.evidence.model_copy(
                update={
                    "verified": matched,
                    "repaired": False,
                    "section_id": req.section_id if matched else item.evidence.section_id,
                    "page": None,
                }
            )
            if not matched:
                warnings.append(f"match: {item.req_id}: unmatched table quote")
            continue
        checked, ev_warnings = verify(
            item.evidence, doc.full_text, doc.sections, allow_repair=False
        )
        item.evidence = checked
        warnings.extend(f"match: {item.req_id}: {w}" for w in ev_warnings)

    # 7. scope_ids 순서로 정렬, 8. 저장 모델로 변환(req_id pattern 검증)
    order = {req_id: k for k, req_id in enumerate(scope_ids)}
    items.sort(key=lambda it: order[it.req_id])
    fits = []
    for item in items:
        req = requirements[item.req_id]
        values = item.model_dump()
        values.update(
            req_id=req.id,
            instance_key=req.instance_key,
            definition=req.definition,
            name=req.source_name,
        )
        fits.append(RequirementFit.model_validate(values))
    return fits, warnings


def match_inputs(
    doc: RfpDocument,
    profile: CompanyProfile | CompanyEvidenceView,
    *,
    knowledge_text: str = "",
) -> tuple[str, str, str]:
    """Pass2 single 입력 (system, document, instruction). `plan_calls`와 실행이 공유한다(X46).

    지식 발췌는 instruction(비캐시 블록)에만 들어간다 — system·document는 그대로(X1·X8).
    """
    return (
        prompt_bytes("system.md").decode("utf-8"),
        build_document(doc),
        build_match_instruction(doc.requirements, render_profile(profile), knowledge_text),
    )


def finish_match(
    result: ParseResult, doc: RfpDocument, profile: CompanyProfile | CompanyEvidenceView
) -> tuple[list[RequirementFit], list[CallRecord], list[str]]:
    """Pass2 single 응답을 후처리한다. 반환 (fits, [record], warnings)."""
    parsed = result.parsed
    assert isinstance(parsed, MatchOut)  # output_model=MatchOut의 결과
    fits, warnings = postprocess_fits(
        parsed, doc, profile, scope_ids=[r.key for r in doc.requirements]
    )
    return fits, [result.record], warnings


def match(
    doc: RfpDocument,
    facts: RfpFacts,
    profile: CompanyProfile | CompanyEvidenceView,
    *,
    client: LlmClient,
    model: str,
    effort: str,
    slug: str,
    knowledge_text: str = "",
    tracer: Tracer | None = None,
) -> tuple[list[RequirementFit], list[CallRecord], list[str]]:
    """Pass2 single: 요구사항 전체를 한 번에 분류. 반환 (fits, [record], warnings)(X21).

    `tracer` None이면 기록 없음(`NullTracer`).
    """
    if not doc.requirements:
        return [], [], [NO_REQUIREMENTS_WARNING]
    system, document, instruction = match_inputs(doc, profile, knowledge_text=knowledge_text)
    result = traced_parse(
        tracer,
        client,
        purpose="match",
        output_model=MatchOut,
        system=system,
        document=document,
        instruction=instruction,
        model=model,
        effort=effort,
        slug=slug,
    )
    return finish_match(result, doc, profile)
