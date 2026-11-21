"""분석 전략 추상화(spec M3-01 "전략 프로토콜", "호출 입력 조립", 계약 시트 10절·X21·X46·X47·X54).

`AnalysisStrategy`는 Pass1(extract)·Pass2(match)만 맡고 반환은 3-튜플
`(결과, 그 메서드가 보낸 parse 호출의 CallRecord 목록, 경고 목록)`이다(X21). Pass3·게이트·점수는
전략 밖 pipeline 공통 경로다. phase·run_id는 `client`가 생성 시 가진 값이라 전략은 넘기지
않는다(X2).

`plan_calls`는 전략이 보낼 parse 호출의 입력을 같은 순서·같은 문자열·같은 출력 모델 클래스로
돌려주고, 전략 구현은 그 결과로 `tracing.traced_parse`(그 안에서 `client.parse`)를 부른다 —
사전 추정(M3-02)과 실행이 어긋나지 않는다(T19). `StrategyName`(`analysis.schemas`)·
`synth_document`(`analysis.synthesizer`)는 M2-04 소유라 여기서 다시 정의하지 않는다(X47·X54).

slug 실패 예외(`LlmRefusal`·`LlmTruncated`·`LlmOutputError`·`LlmCallError`)와 `MergeError`는
`PassError`로 감싸 올린다. 치명 예외(`LlmConfigError`, `LedgerError`)는 감싸지 않는다.

관측(OBS-02): 전략 객체는 `tracer`(기본 None → `NullTracer`)를 받아 호출마다 `traced_parse`로
generation을 연다. 맵리듀스 Pass1은 `_extract_calls` 순서대로 `chunk=(i, n)`(i는 0부터)를 넘긴다.
tracer가 None/NullTracer면 요청·원장·반환값은 tracer 이전과 같다.

맵리듀스: Pass1은 chunk(`MAPREDUCE_CHUNK_CHARS`)마다 `RfpFactsPartial`을 순차 호출해 코드가
병합하고(LLM reduce 없음), Pass2는 분류별 `MATCH_CHUNK_SIZE`건 이하 묶음마다 호출해 묶음별
M2-04 후처리(`scope_ids`)를 적용해 합친다. 입력 크기로 전략을 자동 전환하지 않고
사용자가 요청한 single 또는 mapreduce 전략을 그대로 사용한다.

회사 지식 발췌(KB-03, X71)는 전략 경계에서 **문자열** `knowledge_text`로만 받는다(`Knowledge`를
모른다). match 호출의 instruction(비캐시 블록)에만 들어가고 system·document는 그대로다(X1·X8).
mapreduce는 모든 묶음에 같은 텍스트를 넣는다. `""`(기본값)이면 KB 이전과 바이트 동일하다.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from bid_deep_engine.analysis import tracing
from bid_deep_engine.analysis.document import render_requirements, split_for_mapreduce
from bid_deep_engine.analysis.extractor import (
    ExtractResult,
    extract_inputs,
    finish_extract,
    finish_partials,
    partial_inputs,
    prompt_bytes,
)
from bid_deep_engine.analysis.llm import (
    CallRecord,
    LlmCallError,
    LlmClient,
    LlmOutputError,
    LlmRefusal,
    LlmTruncated,
    ParseResult,
)
from bid_deep_engine.analysis.matcher import (
    NO_REQUIREMENTS_WARNING,
    build_match_instruction,
    finish_match,
    match_inputs,
    postprocess_fits,
    render_profile,
)
from bid_deep_engine.analysis.merge import MergeError
from bid_deep_engine.analysis.schemas import (
    MatchOut,
    RequirementFit,
    RequirementFitOut,
    RfpFacts,
    RfpFactsPartial,
    StrategyName,
)
from bid_deep_engine.analysis.tracing import Tracer
from bid_deep_engine.company.provenance import CompanyEvidenceView
from bid_deep_engine.company.schema import CompanyProfile
from bid_deep_engine.ingest.models import Requirement, RfpDocument

MAPREDUCE_CHUNK_CHARS = 60_000  # tunable. split_for_mapreduce의 max_chars
MATCH_CHUNK_SIZE = 15  # tunable. Pass2 묶음 하나의 최대 요구사항 수

# 슬러그 실패로 다루는 예외. 앞 셋은 응답을 받은 뒤의 실패라 `record`(과금됨)를 가진다(X3).
_RECORDED_ERRORS = (LlmRefusal, LlmTruncated, LlmOutputError)
_SLUG_ERRORS = (*_RECORDED_ERRORS, LlmCallError)


class PassError(Exception):
    """한 pass의 slug 실패. `calls`는 그 pass에서 과금된 호출 전부(보낸 순서, 실패 호출 포함)."""

    def __init__(
        self, cause: Exception, calls: list[CallRecord], warnings: list[str] | None = None
    ) -> None:
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.cause = cause
        self.calls = calls
        self.warnings = warnings if warnings is not None else []


class PlannedCall(BaseModel):
    """parse 호출 하나의 입력. `output_model`은 클래스 자체(RfpFacts·RfpFactsPartial·MatchOut)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    purpose: Literal["extract", "match"]
    system: str
    document: str
    instruction: str
    output_model: type[BaseModel]


class AnalysisStrategy(Protocol):
    name: StrategyName  # 실제 전략(effective)

    def extract(self, doc: RfpDocument) -> tuple[RfpFacts, list[CallRecord], list[str]]: ...

    def match(
        self,
        doc: RfpDocument,
        facts: RfpFacts,
        profile: CompanyProfile | CompanyEvidenceView,
        *,
        knowledge_text: str = "",
    ) -> tuple[list[RequirementFit], list[CallRecord], list[str]]: ...


def chunk_requirements(reqs: list[Requirement], size: int | None = None) -> list[list[Requirement]]:
    """Pass2 묶음: 분류(ID 접두 3자)는 처음 등장한 순서, 분류 안은 문서 순서로 `size`개씩 자른다.

    묶음 하나는 분류 하나만 담는다. `size` 생략 시 `MATCH_CHUNK_SIZE`.
    """
    size = MATCH_CHUNK_SIZE if size is None else size
    if size < 1:
        raise ValueError(f"size must be >= 1: {size}")
    by_category: dict[str, list[Requirement]] = {}
    for req in reqs:
        by_category.setdefault(req.category, []).append(req)
    return [
        members[i : i + size]
        for members in by_category.values()
        for i in range(0, len(members), size)
    ]


def _planned(
    purpose: Literal["extract", "match"],
    inputs: tuple[str, str, str],
    output_model: type[BaseModel],
) -> PlannedCall:
    system, document, instruction = inputs
    return PlannedCall(
        purpose=purpose,
        system=system,
        document=document,
        instruction=instruction,
        output_model=output_model,
    )


def _extract_calls(effective: StrategyName, doc: RfpDocument) -> list[PlannedCall]:
    """Pass1 호출. single은 1회, mapreduce는 chunk마다 1회(문서 순서)."""
    if effective == "single":
        return [_planned("extract", extract_inputs(doc), RfpFacts)]
    chunks = split_for_mapreduce(doc, MAPREDUCE_CHUNK_CHARS)
    return [_planned("extract", partial_inputs(c), RfpFactsPartial) for c in chunks]


def _match_bundles(
    effective: StrategyName,
    doc: RfpDocument,
    profile: CompanyProfile | CompanyEvidenceView,
    knowledge_text: str,
) -> list[tuple[list[Requirement], PlannedCall]]:
    """Pass2 호출과 그 호출이 맡는 요구사항. single은 전체 1호출, 요구사항 0건이면 없다.

    `knowledge_text`는 모든 묶음의 instruction에 같은 문자열로 들어간다(document는 그대로).
    """
    if not doc.requirements:
        return []
    if effective == "single":
        inputs = match_inputs(doc, profile, knowledge_text=knowledge_text)
        return [(doc.requirements, _planned("match", inputs, MatchOut))]
    system = prompt_bytes("system.md").decode("utf-8")
    summary = render_profile(profile)
    bundles: list[tuple[list[Requirement], PlannedCall]] = []
    for bundle in chunk_requirements(doc.requirements):
        # document에는 그 묶음 요구사항 블록만(섹션 본문 없음), 지시문 ID 목록도 그 묶음만(X30)
        document = render_requirements(doc.model_copy(update={"requirements": bundle}))
        inputs = (system, document, build_match_instruction(bundle, summary, knowledge_text))
        bundles.append((bundle, _planned("match", inputs, MatchOut)))
    return bundles


def plan_calls(
    effective: StrategyName,
    doc: RfpDocument,
    profile: CompanyProfile | CompanyEvidenceView | None = None,
    *,
    knowledge_text: str = "",
) -> list[PlannedCall]:
    """해당 전략이 보낼 parse 호출 입력(보낼 순서). profile이 None이면 Pass1만(X46).

    `knowledge_text`는 match 호출 instruction에만 쓰인다(Pass1·profile None이면 영향 없음).
    Pass3(synth)는 전략 밖이라 여기 없다 — 추정은 `build_synth_inputs`에 같은 텍스트를 넘긴다.
    """
    if effective not in ("single", "mapreduce"):
        raise ValueError(f"unknown strategy: {effective}")
    calls = _extract_calls(effective, doc)
    if profile is not None:
        calls += [call for _, call in _match_bundles(effective, doc, profile, knowledge_text)]
    return calls


def resolve_effective(
    requested: StrategyName, doc: RfpDocument, *, client: LlmClient, model: str
) -> tuple[StrategyName, str | None]:
    """입력 토큰 한도 없이 요청 전략을 유지한다. 토큰 측정은 각 실제 호출에서 수행한다."""
    if requested not in ("single", "mapreduce"):
        raise ValueError(f"unknown strategy: {requested}")
    return requested, None


def _parse(
    client: LlmClient,
    call: PlannedCall,
    *,
    model: str,
    effort: str,
    slug: str,
    tracer: Tracer | None = None,
    chunk: tuple[int, int] | None = None,
) -> ParseResult:
    """`PlannedCall` 하나를 `traced_parse`로 보낸다(`chunk`는 맵리듀스 Pass1 청크 번호).

    slug 실패 예외는 generation에 ERROR로 남은 뒤 과금 record와 함께 `PassError`로 감싼다.
    """
    try:
        return tracing.traced_parse(
            tracer,
            client,
            purpose=call.purpose,
            chunk=chunk,
            output_model=call.output_model,
            system=call.system,
            document=call.document,
            instruction=call.instruction,
            model=model,
            effort=effort,
            slug=slug,
        )
    except _SLUG_ERRORS as exc:
        record = getattr(exc, "record", None) if isinstance(exc, _RECORDED_ERRORS) else None
        raise PassError(exc, [record] if record is not None else []) from exc


class _BaseStrategy:
    def __init__(
        self,
        *,
        client: LlmClient,
        model: str,
        effort: str,
        slug: str,
        tracer: Tracer | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.effort = effort
        self.slug = slug
        self.tracer = tracer

    def _send(self, call: PlannedCall, *, chunk: tuple[int, int] | None = None) -> ParseResult:
        return _parse(
            self.client,
            call,
            model=self.model,
            effort=self.effort,
            slug=self.slug,
            tracer=self.tracer,
            chunk=chunk,
        )


class SinglePassStrategy(_BaseStrategy):
    """Pass1 = extract 1회(`RfpFacts`), Pass2 = match 1회(요구사항 전체). M2 동작 그대로."""

    name: StrategyName = "single"

    def extract(self, doc: RfpDocument) -> tuple[RfpFacts, list[CallRecord], list[str]]:
        (call,) = plan_calls("single", doc)
        done: ExtractResult = finish_extract(self._send(call), doc)
        return done.facts, [done.call], done.warnings

    def match(
        self,
        doc: RfpDocument,
        facts: RfpFacts,
        profile: CompanyProfile | CompanyEvidenceView,
        *,
        knowledge_text: str = "",
    ) -> tuple[list[RequirementFit], list[CallRecord], list[str]]:
        if not doc.requirements:
            return [], [], [NO_REQUIREMENTS_WARNING]
        call = plan_calls("single", doc, profile, knowledge_text=knowledge_text)[-1]
        return finish_match(self._send(call), doc, profile)


class MapReduceStrategy(_BaseStrategy):
    """Pass1 = chunk마다 `RfpFactsPartial` 호출 후 코드 병합, Pass2 = 분류별 묶음 호출 후 합치기."""

    name: StrategyName = "mapreduce"

    def extract(self, doc: RfpDocument) -> tuple[RfpFacts, list[CallRecord], list[str]]:
        results: list[ParseResult] = []
        records: list[CallRecord] = []
        calls = _extract_calls("mapreduce", doc)
        for index, call in enumerate(calls):  # 문서 순서, 순차(지출 가드와 맞음)
            try:
                result = self._send(call, chunk=(index, len(calls)))
            except PassError as exc:  # 앞 chunk 과금 호출 + 실패 호출 record, 남은 chunk 중단
                raise PassError(exc.cause, [*records, *exc.calls]) from exc.cause
            results.append(result)
            records.append(result.record)
        try:
            done = finish_partials(results, doc)
        except MergeError as exc:
            raise PassError(exc, records) from exc
        return done.facts, records, done.warnings

    def match(
        self,
        doc: RfpDocument,
        facts: RfpFacts,
        profile: CompanyProfile | CompanyEvidenceView,
        *,
        knowledge_text: str = "",
    ) -> tuple[list[RequirementFit], list[CallRecord], list[str]]:
        if not doc.requirements:
            return [], [], [NO_REQUIREMENTS_WARNING]
        doc_ids = {r.key for r in doc.requirements}
        fits: list[RequirementFit] = []
        records: list[CallRecord] = []
        warnings: list[str] = []
        for bundle, call in _match_bundles("mapreduce", doc, profile, knowledge_text):
            try:
                result = self._send(call)
            except PassError as exc:
                raise PassError(exc.cause, [*records, *exc.calls], warnings) from exc.cause
            records.append(result.record)
            parsed = result.parsed
            assert isinstance(parsed, MatchOut)  # output_model=MatchOut의 결과
            scope_ids = [r.key for r in bundle]
            scope = set(scope_ids)
            kept: list[RequirementFitOut] = []
            for item in parsed.fits:
                if item.req_id in doc_ids and item.req_id not in scope:  # 다른 묶음의 ID
                    warnings.append(f"match chunk response outside chunk: {item.req_id}")
                else:
                    kept.append(item)  # 문서에 없는 ID는 postprocess_fits가 버린다
            bundle_fits, bundle_warnings = postprocess_fits(
                MatchOut(fits=kept), doc, profile, scope_ids=scope_ids
            )
            fits.extend(bundle_fits)
            warnings.extend(bundle_warnings)
        order = {r.key: k for k, r in enumerate(doc.requirements)}
        fits.sort(key=lambda f: order[f.key])
        return fits, records, warnings


def make_strategy(
    effective: StrategyName,
    *,
    client: LlmClient,
    model: str,
    effort: str,
    slug: str,
    tracer: Tracer | None = None,
) -> AnalysisStrategy:
    """실제 전략 이름으로 전략 객체를 만든다. `tracer` None이면 기록 없음(`NullTracer`)."""
    if effective == "single":
        return SinglePassStrategy(
            client=client, model=model, effort=effort, slug=slug, tracer=tracer
        )
    if effective == "mapreduce":
        return MapReduceStrategy(
            client=client, model=model, effort=effort, slug=slug, tracer=tracer
        )
    raise ValueError(f"unknown strategy: {effective}")
