"""분석 파이프라인: Pass1 산출물·입력 해시 캐시(spec M2-02 "산출물")와 공고 단위 진입점
`run_notice`(spec M2-04 "공고 단위 진입점", 계약 시트 X19·X20·X47·X48·X53).

- `run_notice`는 rfp.json 경로와 산출 폴더를 따로 받아 extract → match → synth 중 요청 단계를
  실행하고 facts.json·fits.json·analysis.json·usage.json을 산출 폴더에만 쓴다(analyze CLI는
  모든 `--pass`를 이 경로로 보낸다 — M3-01, X45).
- extract 단계 순서(X29): 요청 전략 기준 input_hash로 캐시 확인(적중이면 count_tokens·클라이언트
  없음) → 미스일 때만 요청 전략 검증 → 실제 전략의 `extract`. match·synth의
  실제 전략은 facts.json `meta.strategy_effective`를 따른다(요청이 mapreduce면 mapreduce).
- `run_extract`는 `run_notice(passes=("extract",))`를 부르고 결과를 M2-02 `ExtractOutcome`으로
  바꾸는 얇은 래퍼다(X45, X60). `out_root/<slug>/rfp.json`을 읽고 같은 폴더에 쓴다.
- usage.json 병합: 이번 실행의 과금 호출(성공 `ParseResult.record`, 실패 `exc.record`)이 있는
  purpose의 이전 기록은 지우고 이번 기록을 보낸 순서로 붙인다. 다른 purpose 기록은 둔다.
  `strategy`·`strategy_effective`·`run_id`는 이번 실행 값, `warnings`는 이번에 돈 pass의 키만
  교체한다. `error`는 이번 실행의 slug 실패 사유(성공이면 null). 과금 호출이 0건이면 쓰지
  않는다(X48).
- 회사 지식(KB-03, X71·X72·X75): `knowledge`가 있으면 공고당 한 번 `prepare_knowledge`로 발췌를
  골라 match·synth(전략 무관)에 같은 `knowledge_text`를 넘기고, match 결과에
  `annotate_evidence_pages`를 적용한 뒤 fits.json에 쓴다. fits.json meta는 `profile_hash` 뒤
  `company_input_hash`·`knowledge_hash`·`knowledge`, analysis.json은 회사 입력 지문과
  `knowledge`(선택 전체). 지식이 없으면 knowledge 항목은
  null이고 instruction은 KB 이전과 바이트 동일하다. 게이트·점수·권고에는 넘기지 않는다(X70).
- 게이트 사람 확인(GT-01): synth는 `evaluate_gates` 직후 산출 폴더의 `gate_confirmations.yaml`을
  읽어 적용하고(경고는 synth 경고), 불량 파일이면 LLM 호출 전에 slug 실패
  (`invalid gate_confirmations.yaml: GateConfirmationError`)로 끝낸다. extract·match는 읽지 않는다.
- 실패 산출물(LLM-01 A): `LlmOutputError`·`LlmTruncated`(직접 또는 `PassError.cause`)는
  `<out_dir>/_failed/<run_id>-<purpose>-<n>.json`에 응답 원문·검증 오류·usage·비용을 남기고
  (프롬프트 제외, 제약 7) usage.json `error`·`NoticeOutcome.reason`에 요약을 붙인다. `<n>`은 이번
  실행에서 그 purpose의 과금 호출 순번(1부터, mapreduce chunk 번호). 쓰기 실패(OSError)는 경고만
  남기고 분석 결과를 바꾸지 않는다.
- 관측(OBS-02): `run_notice`는 공고 1건 전체(캐시 판정 포함)를 `tracer.notice_scope`로 감싸고
  끝에 `set_output`을 남긴다. `tracer` None이면 `NullTracer`(기록 없음, 산출물·결과 불변).
  전략·synth 호출은 `tracer`를 받아 `traced_parse`로 generation을 연다. 기록 쪽 예외는 tracer가
  삼키므로 여기에는 try/except가 없다.
"""

import hashlib
import json
import math
import os
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from bid_deep_engine.analysis.document import build_document
from bid_deep_engine.analysis.evidence import Citations
from bid_deep_engine.analysis.evidence_locations import load_location_sources, locate_model_evidence
from bid_deep_engine.analysis.extractor import prompt_bytes
from bid_deep_engine.analysis.gates import evaluate_gates, resolve_as_of
from bid_deep_engine.analysis.llm import (
    CallRecord,
    LlmCallError,
    LlmClient,
    LlmOutputError,
    LlmRefusal,
    LlmTruncated,
)
from bid_deep_engine.analysis.provenance import (
    artifact_stage_stamp,
    as_of_hash,
    code_parameters,
    confirmations_hash,
    gate_ref,
    knowledge_input_hash,
    llm_parameters,
    make_stage_stamp,
    model_settings_hash,
    portfolio_knowledge_hash,
    prompt_set_hash,
    requirements_hash,
    rfp_input_hash,
    stage_output_hash,
    write_run_state,
)
from bid_deep_engine.analysis.recommend import recommend
from bid_deep_engine.analysis.review import (
    GateResolver,
    finalize_readiness,
    make_gate_resolver,
    resolve_stage_states,
)
from bid_deep_engine.analysis.schemas import (
    Analysis,
    Evidence,
    GateResult,
    RequirementFit,
    RfpFacts,
    StageStamp,
    StrategyName,
    SynthOut,
    iter_evidence,
)
from bid_deep_engine.analysis.scoring import estimate_scores
from bid_deep_engine.analysis.spend import Phase
from bid_deep_engine.analysis.strategies import (
    AnalysisStrategy,
    PassError,
    make_strategy,
    resolve_effective,
)
from bid_deep_engine.analysis.synthesizer import synth_document, synthesize
from bid_deep_engine.analysis.tracing import NULL_TRACER, NoticeTrace, Tracer
from bid_deep_engine.company.knowledge import (
    WIKILINK_RE,
    Knowledge,
    KnowledgeSelection,
    prepare_knowledge,
)
from bid_deep_engine.company.provenance import CompanyEvidenceView
from bid_deep_engine.company.schema import CompanyProfile
from bid_deep_engine.config import Settings
from bid_deep_engine.feedback.gate_confirmations import (
    GATE_CONFIRMATIONS_FILE,
    GateConfirmationError,
    load_confirmations,
    resolve_confirmations,
)
from bid_deep_engine.ingest.models import NoticeBundle, RawDoc, RfpDocument

Status = Literal["ok", "cached", "failed"]
PassName = Literal["extract", "match", "synth"]
PASS_ORDER: tuple[PassName, ...] = ("extract", "match", "synth")  # 실행 순서 고정(X53)
FACTS_MISMATCH_WARNING = "fits.json was produced from different facts"
KNOWLEDGE_MISMATCH_WARNING = "fits.json was produced with different knowledge"
COMPANY_INPUT_MISMATCH_WARNING = "fits.json was produced with different company input"
FAILED_DIR = "_failed"  # tunable. 실패 산출물 폴더(out_dir 아래)
FAILED_SCHEMA_VERSION = 1
GATE_VERDICTS = ("PASS", "FAIL", "UNKNOWN", "RISK")  # trace output gates 키(순서 고정)
FAILED_JSON_HEAD_CHARS = 2_000  # 실패 산출물 json_text_head 길이(response_text는 전문)

_LENGTH_BYTES = 8


@dataclass(frozen=True)
class ExtractOutcome:
    slug: str
    status: Status
    reason: str | None
    citations: Citations | None
    cost_usd: float
    served_model: (
        str | None
    )  # ok: 응답 모델, failed: usage.json을 썼으면 record의 모델, cached: None
    totals: dict[str, Any] | None  # 쓴 usage.json의 totals(쓰지 않았거나 cached면 None)


def input_hash(
    *,
    rfp_json: bytes,
    system: bytes,
    extract: bytes,
    model: str,
    strategy: str,
    effort: str,
    schema_version: int,
) -> str:
    """입력 해시: 조각마다 8바이트 big-endian 길이 접두를 붙여 sha256에 넣는다(경계 모호성 제거)."""
    h = hashlib.sha256()
    pieces = (
        rfp_json,
        system,
        extract,
        model.encode("utf-8"),
        strategy.encode("utf-8"),
        effort.encode("utf-8"),
        str(schema_version).encode("utf-8"),
    )
    for piece in pieces:
        h.update(len(piece).to_bytes(_LENGTH_BYTES, "big"))
        h.update(piece)
    return h.hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """같은 폴더의 임시 파일에 쓴 뒤 바꿔 넣어 중간 상태 파일이 남지 않게 한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _usage_payload(
    slug: str,
    run_id: str,
    calls: list[CallRecord],
    *,
    strategy: str,
    strategy_effective: str,
    warnings: dict[str, list[str]],
    error: str | None,
) -> dict[str, Any]:
    return {
        "slug": slug,
        "run_id": run_id,
        "strategy": strategy,
        "strategy_effective": strategy_effective,
        "calls": [c.model_dump(mode="json") for c in calls],
        "totals": {
            "calls": len(calls),
            "input_tokens": sum(c.input_tokens for c in calls),
            "output_tokens": sum(c.output_tokens for c in calls),
            "cache_read_input_tokens": sum(c.cache_read_input_tokens for c in calls),
            "cache_creation_input_tokens": sum(
                c.cache_creation_5m + c.cache_creation_1h for c in calls
            ),
            "cost_usd": math.fsum(c.cost_usd for c in calls),
        },
        "warnings": warnings,
        "served_models": list(dict.fromkeys(c.served_model for c in calls)),
        "error": error,
    }


def _pass1_prompt(strategy: str) -> str:
    """요청 전략의 Pass1 프롬프트 파일(system.md 외). 캐시 키·prompt_hashes의 원천(X29)."""
    if strategy == "single":
        return "extract.md"
    if strategy == "mapreduce":
        return "extract_partial.md"
    raise ValueError(f"unknown strategy: {strategy}")


def _extract_digest(rfp_bytes: bytes, *, model: str, strategy: str, effort: str) -> str:
    """facts.json 캐시 키(spec M2-02 "input_hash"): rfp.json·프롬프트 2개·설정·스키마 버전.

    strategy는 **요청** 전략이고 프롬프트 조각은 그 전략의 Pass1 집합이다(X29).
    """
    return input_hash(
        rfp_json=rfp_bytes,
        system=prompt_bytes("system.md"),
        extract=prompt_bytes(_pass1_prompt(strategy)),
        model=model,
        strategy=strategy,
        effort=effort,
        schema_version=RfpFacts.model_fields["schema_version"].default,
    )


def _facts_payload(
    slug: str,
    digest: str,
    *,
    facts: RfpFacts,
    citations: Citations,
    warnings: list[str],
    served_model: str,
    model: str,
    strategy: str,
    effective: str,
    effort: str,
    created_at: str,
    stage: StageStamp | None,
) -> dict[str, Any]:
    """facts.json 내용(M2-02 형식 + `strategy_effective`). prompt_hashes는 실제 전략의 집합."""
    stem = _pass1_prompt(effective).removesuffix(".md")
    meta = {
        "slug": slug,
        "input_hash": digest,
        "model": model,
        "served_model": served_model,
        "strategy": strategy,
        "strategy_effective": effective,
        "effort": effort,
        "prompt_hashes": {
            "system": _sha256(prompt_bytes("system.md")),
            stem: _sha256(prompt_bytes(f"{stem}.md")),
        },
        "created_at": created_at,
        "citations": citations.model_dump(),
        "warnings": warnings,
    }
    if stage is not None:
        meta["stage"] = stage.model_dump(mode="json")
    return {
        "meta": meta,
        "facts": facts.model_dump(mode="json"),
    }


def _cached_meta(facts_path: Path, expected_hash: str) -> dict[str, Any] | None:
    """facts.json meta.input_hash가 같으면 그 meta. 읽을 수 없거나 다르면 None(재실행)."""
    try:
        meta = json.loads(facts_path.read_text(encoding="utf-8"))["meta"]
        return meta if meta["input_hash"] == expected_hash else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _effective_of(meta: dict[str, Any]) -> StrategyName:
    """facts.json meta의 실제 전략. 키가 없으면 M2 산출물이므로 single."""
    return "mapreduce" if meta.get("strategy_effective") == "mapreduce" else "single"


def run_extract(
    slug: str,
    *,
    out_root: Path,
    settings: Settings,
    client_factory: Callable[[], LlmClient],
    model: str,
    strategy: str,
    effort: str,
    force: bool,
    run_id: str,
) -> ExtractOutcome:
    """공고 하나의 Pass1 추출. `run_notice(passes=("extract",))`를 부르는 얇은 래퍼(X45).

    캐시 적중이면 API·클라이언트 없이 건너뛴다. slug 단위 실패는 failed 결과로 돌려주고 치명
    오류(`LlmConfigError`, `LedgerError`)는 그대로 전파한다. `ExtractOutcome.reason`은 M2-02와
    같이 예외 메시지(`str(exc)`)다. run_id·settings는 클라이언트가 가진다(X2) — 시그니처 호환용.
    """
    slug_dir = out_root / slug
    outcome = run_notice(
        slug_dir / "rfp.json",
        slug_dir,
        client_factory=client_factory,
        profile=None,
        model=model,
        strategy=cast(StrategyName, strategy),
        effort=effort,
        passes=("extract",),
        force=force,
    )
    return extract_outcome(outcome, slug_dir, slug=slug)


# --- run_notice(spec M2-04 "공고 단위 진입점", 계약 시트 X19) ---------------------------------


@dataclass(frozen=True)
class NoticeOutcome:
    slug: str
    status: Status
    # failed일 때만. 예외에서 온 실패는 "<예외 클래스명>: <str(exc)>"(X48) — 출력 오류·잘림이면
    # 뒤에 실패 요약(`; validation, …; saved _failed/…`, LLM-01)이 붙는다(usage.json error와 같음)
    reason: str | None
    calls: list[CallRecord]  # 이번 실행의 과금 호출 전부(성공 record·실패 exc.record, 보낸 순서)
    warnings: list[str] = field(default_factory=list)  # 256k 전환·match·synth 후처리·불일치 경고
    # 예외에서 온 실패의 원인(전제조건 실패는 None). `run_extract`가 M2-02 reason을 만드는 데 쓴다
    cause: BaseException | None = field(default=None, compare=False, repr=False)
    # OBS-02: 이 공고의 Langfuse trace ID(기록하지 않았으면 None). CLI·bench가 링크 줄을 만든다
    trace_id: str | None = None


class _SlugFailure(Exception):
    """예외가 아닌 slug 실패(전제조건). 메시지가 그대로 reason이 된다."""


def profile_file_hash(profile_path: Path, profile: CompanyProfile) -> str:
    """fits.json meta.profile_hash = sha256(프로필 파일 바이트 + portfolio 파일 바이트)."""
    portfolio = profile_path.parent / profile.portfolio_file
    return _sha256(profile_path.read_bytes() + portfolio.read_bytes())


def annotate_evidence_pages(
    fits: list[RequirementFit], selection: KnowledgeSelection
) -> tuple[list[RequirementFit], list[str]]:
    """각 fit `rationale`의 `[[slug]]`(KB-01 `WIKILINK_RE`)를 등장 순·중복 제거로 뽑아, 발췌에
    포함된 페이지(`selection.pages`)만 `evidence_pages`에 넣는다(KB-03, X75).

    나머지 slug마다 경고 `match: unknown knowledge page removed: <slug> (<req_id>)`. `rationale`은
    바꾸지 않고 입력 fit도 바꾸지 않는다(`model_copy`). 지식 비활성이면 호출하지 않는다.
    """
    included = set(selection.pages)
    out: list[RequirementFit] = []
    warnings: list[str] = []
    for fit in fits:
        slugs = dict.fromkeys(m.group(1).strip() for m in WIKILINK_RE.finditer(fit.rationale))
        kept: list[str] = []
        for slug in slugs:
            if slug in included:
                kept.append(slug)
            else:
                warnings.append(f"match: unknown knowledge page removed: {slug} ({fit.req_id})")
        out.append(fit.model_copy(update={"evidence_pages": kept}))
    return out, warnings


def _skipped_warning(selection: KnowledgeSelection | None) -> list[str]:
    """예산 때문에 빠진 페이지 경고(match·synth 각 pass). 없으면 빈 목록."""
    if selection is None or not selection.skipped:
        return []
    return [f"knowledge: pages skipped by budget: {', '.join(selection.skipped)}"]


def _knowledge_mismatch(
    fits_meta: dict[str, Any],
    knowledge: Knowledge | None,
    selection: KnowledgeSelection | None,
) -> bool:
    """fits.json을 만든 지식이 지금과 다른가: `knowledge_hash`가 다르거나(한쪽만 null 포함)
    meta `knowledge.categories`가 현재 선택과 다르다. 키가 없는 이전 산출물은 null로 본다."""
    current_hash = knowledge.hash if knowledge is not None else None
    if fits_meta.get("knowledge_hash") != current_hash:
        return True
    stored = fits_meta.get("knowledge")
    stored_categories = stored.get("categories") if isinstance(stored, dict) else None
    current_categories = selection.categories if selection is not None else None
    return stored_categories != current_categories


def _failure_reason(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _failure_kind(exc: LlmOutputError | LlmTruncated) -> str:
    return "truncated" if isinstance(exc, LlmTruncated) else exc.failure.kind


def _failure_summary(exc: LlmOutputError | LlmTruncated, saved: str | None) -> str:
    """usage.json `error`(LLM-01): 기본 사유 + 실패 종류(검증이면 오류 수·첫 오류) + 저장 위치.

    `saved`는 `_failed/<파일명>`(쓰기 실패면 None — `; saved …` 생략).
    """
    parts = [_failure_reason(exc)]
    if isinstance(exc, LlmOutputError) and exc.failure.kind == "validation":
        failure = exc.failure
        detail = f"validation, {failure.error_count} validation errors"
        if failure.validation_errors:
            first = failure.validation_errors[0]
            detail += f", first: {first['loc']} — {first['msg']}"
        parts.append(detail)
    else:
        parts.append(_failure_kind(exc))
    if saved is not None:
        parts.append(f"saved {saved}")
    return "; ".join(parts)


def _failed_payload(
    exc: LlmOutputError | LlmTruncated, *, slug: str, run_id: str, call_index: int
) -> dict[str, Any]:
    """실패 산출물 내용(키 순서 고정). 응답 텍스트만 담고 프롬프트는 담지 않는다(제약 7)."""
    record = exc.record
    if isinstance(exc, LlmTruncated):
        error_count, errors, json_text, response_text = 0, [], None, exc.response_text
    else:
        failure = exc.failure
        error_count, errors = failure.error_count, failure.validation_errors
        json_text, response_text = failure.json_text, failure.response_text
    return {
        "schema_version": FAILED_SCHEMA_VERSION,
        "slug": slug,
        "run_id": run_id,
        "purpose": record.purpose,
        "call_index": call_index,
        "model": record.model,
        "served_model": record.served_model,
        "stop_reason": record.stop_reason,
        "kind": _failure_kind(exc),
        "error_count": error_count,
        "validation_errors": [dict(e) for e in errors],
        "json_text_head": json_text[:FAILED_JSON_HEAD_CHARS] if json_text is not None else None,
        "response_text": response_text,
        "usage": {
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "cache_read_input_tokens": record.cache_read_input_tokens,
            "cache_creation_5m": record.cache_creation_5m,
            "cache_creation_1h": record.cache_creation_1h,
        },
        "cost_usd": record.cost_usd,
        "estimate_usd": record.estimate_usd,
        "duration_ms": record.duration_ms,
        "at": record.at,
    }


def _check_passes(passes: tuple[str, ...]) -> None:
    """비어 있지 않고 PASS_ORDER 순서의 중복 없는 부분열이어야 한다("all" 문자열 불가)."""
    order = [p for p in PASS_ORDER if p in passes]
    if not passes or list(passes) != order:
        raise ValueError(f"invalid passes: {passes!r} (ordered subset of {PASS_ORDER})")


def _read_usage(path: Path) -> tuple[list[CallRecord], dict[str, list[str]]]:
    """기존 usage.json의 (calls, pass별 warnings). 없거나 읽을 수 없으면 비어 있는 값.

    M2 산출물처럼 `warnings` 키가 없으면 pass마다 빈 목록이다.
    """
    warnings: dict[str, list[str]] = {p: [] for p in PASS_ORDER}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        calls = [CallRecord.model_validate(c) for c in data["calls"]]
    except (OSError, ValueError, KeyError, TypeError):
        return [], warnings
    raw = data.get("warnings")
    if isinstance(raw, dict):
        for name in PASS_ORDER:
            value = raw.get(name)
            if isinstance(value, list):
                warnings[name] = [str(w) for w in value]
    return calls, warnings


def extract_outcome(
    outcome: NoticeOutcome, out_dir: Path, *, slug: str | None = None
) -> ExtractOutcome:
    """`run_notice(passes=("extract",))` 결과를 M2-02 `ExtractOutcome`으로 바꾼다(X45).

    reason은 M2-02와 같이 예외 메시지(`str(exc)`)다(NoticeOutcome.reason은 클래스명 접두, X48).
    served_model은 마지막 Pass1 호출, totals는 쓴 usage.json의 totals(과금 0건이면 None)다.
    """
    extract_calls = [c for c in outcome.calls if c.purpose == "extract"]
    totals: dict[str, Any] | None = None
    if outcome.calls:  # usage.json을 썼다
        try:
            totals = json.loads((out_dir / "usage.json").read_text(encoding="utf-8"))["totals"]
        except (OSError, ValueError, KeyError):
            totals = None
    citations: Citations | None = None
    if outcome.status == "ok":
        meta = json.loads((out_dir / "facts.json").read_text(encoding="utf-8"))["meta"]
        citations = Citations(**meta["citations"])
    reason = str(outcome.cause) if outcome.cause is not None else outcome.reason
    return ExtractOutcome(
        slug=slug if slug is not None else outcome.slug,
        status=outcome.status,
        reason=reason,
        citations=citations,
        cost_usd=math.fsum(c.cost_usd for c in outcome.calls),
        served_model=extract_calls[-1].served_model if extract_calls else None,
        totals=totals,
    )


def _read_artifact(path: Path, missing: str) -> dict[str, Any]:
    """facts.json·fits.json 읽기. 없으면 `missing` 사유, 읽을 수 없으면 "invalid <파일>" 사유."""
    if not path.is_file():
        raise _SlugFailure(missing)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("meta"), dict):
            raise ValueError("meta missing")
        return data
    except (OSError, ValueError) as exc:
        raise _SlugFailure(f"invalid {path.name}: {type(exc).__name__}") from exc


def _facts_citations(facts: RfpFacts) -> Citations:
    """facts 인용 통계. conflicts 제외(X10) — verify_facts가 센 값과 같다."""
    counted = list(iter_evidence(facts))
    verified = sum(e.verified is True for e in counted)
    return Citations(
        total=len(counted),
        verified=verified,
        repaired=sum(e.repaired is True for e in counted),
        unverified=len(counted) - verified,
    )


def _citations(facts: RfpFacts, fits: list[RequirementFit], synth: SynthOut) -> dict[str, int]:
    """facts(conflicts 제외 — X10) + fits + risks + checklist.source(None 제외). gates는 제외."""
    counted: list[Evidence] = list(iter_evidence(facts))
    counted += [f.evidence for f in fits if f.evidence is not None]
    counted += [r.evidence for r in synth.risks]
    counted += [c.source for c in synth.checklist if c.source is not None]
    verified = sum(e.verified is True for e in counted)
    return {
        "total": len(counted),
        "verified": verified,
        "repaired": sum(e.repaired is True for e in counted),
        "unverified": len(counted) - verified,
    }


def _served_models(calls: list[dict[str, Any]]) -> str:
    """usage.json 호출들의 served_model 고유값을 등장 순으로 ","로 연결."""
    return ",".join(dict.fromkeys(c["served_model"] for c in calls))


class _NoticeRun:
    """run_notice 한 번의 상태: 지연 생성 클라이언트, 이번 과금 기록, 실행 전 usage.json."""

    def __init__(
        self,
        rfp_path: Path,
        out_dir: Path,
        *,
        client_factory: Callable[[], LlmClient],
        profile: CompanyProfile | CompanyEvidenceView | None,
        model: str,
        strategy: StrategyName,
        effort: str,
        force: bool,
        profile_hash: str | None,
        company_input_hash: str | None,
        knowledge: Knowledge | None,
        category_override: list[str] | None,
        tracer: Tracer = NULL_TRACER,
        trace: NoticeTrace | None = None,
        run_id: str | None = None,
        portfolio_texts: Mapping[str, str] | None = None,
        model_fingerprint: str | None = None,
    ) -> None:
        self.rfp_path = rfp_path
        self.out_dir = out_dir
        self.factory = client_factory
        self.profile = profile
        self.model = model
        self.model_fingerprint = model_fingerprint
        self.strategy = strategy
        self.effort = effort
        self.force = force
        self.profile_hash = profile_hash
        self.company_input_hash = company_input_hash
        self.knowledge = knowledge
        self.category_override = category_override
        self.portfolio_texts = portfolio_texts
        self.tracer = tracer
        self.trace = trace if trace is not None else NoticeTrace()
        self.run_id = run_id
        # 권고까지 간 실행의 요약(decision·fit_score·gates). 그 밖은 비어 있어 trace output이 null
        self._summary: dict[str, Any] = {}
        self.slug = out_dir.name  # rfp.json을 읽으면 doc.slug로 바뀐다
        self.calls: list[CallRecord] = []
        self.warnings: list[str] = []  # 호출자에게 보이는 경고(stderr)
        self.pass_warnings: dict[str, list[str]] = {p: [] for p in PASS_ORDER}  # usage.json용
        self.ran: set[str] = set()  # 이번 실행이 실제로 돌린 pass(캐시로 건너뛴 pass 제외)
        self.current: str | None = None
        self.effective: StrategyName | None = None  # 이번 slug의 실제 전략(알게 된 뒤)
        self._mismatch_checked = False
        self._client: LlmClient | None = None
        self._doc: RfpDocument | None = None
        self._fits: tuple[dict[str, Any], list[RequirementFit]] | None = None
        self._selection: tuple[KnowledgeSelection | None, str] | None = None
        self._location_cache: tuple[NoticeBundle | None, list[RawDoc]] | None = None
        # 병합 기준은 이번 실행이 쓰기 전의 usage.json이다.
        self._base_calls, self._base_warnings = _read_usage(out_dir / "usage.json")

    # --- 공용 ---

    def client(self) -> LlmClient:
        """LLM 호출이 처음 필요할 때 한 번 만든다(캐시 적중만이면 부르지 않음)."""
        if self._client is None:
            self._client = self.factory()
            if self.run_id is None:  # scope를 열 때 몰랐던 run_id를 클라이언트 것으로 보강
                self.trace.update_metadata(run_id=self._client.run_id)
        return self._client

    def required_profile(self) -> CompanyProfile | CompanyEvidenceView:
        """match·synth용 프로필. profile 없이는 extract 단독만 허용된다(`run_notice`가 검사)."""
        assert self.profile is not None
        return self.profile

    def strategy_for(self, effective: StrategyName) -> AnalysisStrategy:
        """실제 전략 객체. 슬러그는 rfp.json을 읽은 뒤의 `doc.slug`다."""
        return make_strategy(
            effective,
            client=self.client(),
            model=self.model,
            effort=self.effort,
            slug=self.slug,
            tracer=self.tracer,
        )

    def set_effective(self, effective: StrategyName) -> None:
        """이번 slug의 실제 전략을 기록하고 trace metadata `strategy_effective`를 갱신한다."""
        changed = self.effective != effective
        self.effective = effective
        if changed:
            self.trace.update_metadata(strategy_effective=effective)

    def record_input(self, rfp_bytes: bytes) -> None:
        """trace input에 문서 글자 수·프로필 해시를 더한다(기록 중일 때만 rfp.json을 한 번 더 해석).

        `self.doc()`와 달리 slug·검증 상태를 건드리지 않는다. 읽을 수 없으면 글자 수는 null.
        """
        if not self.trace.trace_id:
            return
        try:
            rfp_chars: int | None = len(RfpDocument.model_validate_json(rfp_bytes).full_text)
        except (ValidationError, ValueError):
            rfp_chars = None
        self.trace.set_input(
            {
                "slug": self.slug,
                "rfp_chars": rfp_chars,
                "company_profile_hash": self.profile_hash,
            }
        )

    def finish_trace(self, passes: tuple[str, ...], outcome: "NoticeOutcome") -> None:
        """trace output(spec OBS-02 "trace" 표). 성공·실패·캐시 적중 모두 남긴다."""
        failed = outcome.status == "failed"
        summary = {} if failed else self._summary
        self.trace.set_output(
            {
                "passes": list(passes),
                "decision": summary.get("decision"),
                "fit_score": summary.get("fit_score"),
                "gates": summary.get("gates"),
                "cost_usd": math.fsum(c.cost_usd for c in outcome.calls),
                "calls": len(outcome.calls),
                "status": "failed" if failed else "ok",
                "failure": outcome.reason if failed else None,
                "cache_hit": not outcome.calls,
            }
        )

    def doc(self, rfp_bytes: bytes) -> RfpDocument:
        if self._doc is None:
            try:
                doc = RfpDocument.model_validate_json(rfp_bytes)
                build_document(doc)  # 섹션 헤딩을 못 찾으면 ValueError — API 호출 전에 걸러낸다
            except (ValidationError, ValueError) as exc:
                raise _SlugFailure(f"invalid rfp.json: {type(exc).__name__}") from exc
            self._doc = doc
            self.slug = doc.slug
        return self._doc

    def knowledge_for(self, doc: RfpDocument) -> tuple[KnowledgeSelection | None, str]:
        """공고당 한 번 고른 발췌 (선택, 렌더링 텍스트). 지식이 없으면 `(None, "")`.

        match·synth가 같은 값을 쓴다. 미지 override slug의 `ValueError`는 잡지 않는다(CLI가 미리
        검증 — 여기서 나면 프로그래밍 오류).
        """
        if self._selection is None:
            if self.knowledge is None:
                self._selection = (None, "")
            else:
                self._selection = prepare_knowledge(
                    doc, self.knowledge, override=self.category_override
                )
        return self._selection

    def locate(self, model: Any, doc: RfpDocument) -> Any:
        """현재 bundle/raw 캐시로 code-owned 위치 metadata를 덮어쓴 복사본.

        legacy fixture처럼 bundle/raw가 없거나 손상됐으면 분석 자체는 계속하되 LLM inline 위치를
        신뢰하지 않고 unavailable로 낮춘다.
        """
        if self._location_cache is None:
            try:
                bundle, _, raws = load_location_sources(
                    self.rfp_path.parent, document=doc, require_bundle=False
                )
                self._location_cache = (bundle, list(raws))
            except (OSError, ValueError):
                self._location_cache = (None, [])
        bundle, raws = self._location_cache
        return locate_model_evidence(model, bundle, raws)

    def warn(self, name: PassName, lines: list[str]) -> None:
        """pass 경고를 호출자(stderr)와 usage.json 둘 다에 남긴다."""
        self.warnings.extend(lines)
        self.pass_warnings[name].extend(lines)

    def begin(self, name: PassName) -> None:
        """pass 시작(캐시로 건너뛰지 않는 pass만). 실패해도 그 pass의 경고는 이번 값으로 바뀐다."""
        self.current = name
        self.ran.add(name)

    def failure_error(self, exc: BaseException) -> str:
        """응답 뒤 실패의 slug 사유. 출력 오류·잘림이면 `_failed/` 파일을 쓰고 요약을 붙인다.

        `exc.record`는 이미 `self.calls`에 있어야 한다(순번 = 그 purpose의 이번 실행 과금 호출 수).
        쓰기 실패(OSError)는 이번 pass 경고(stderr·usage.json)로만 남기고 `; saved …`를 뺀다.
        """
        if not isinstance(exc, (LlmOutputError, LlmTruncated)):
            return _failure_reason(exc)
        assert self._client is not None  # 과금 호출은 클라이언트로만 생긴다
        purpose = exc.record.purpose
        index = sum(c.purpose == purpose for c in self.calls)
        name = f"{self._client.run_id}-{purpose}-{index}.json"
        payload = _failed_payload(exc, slug=self.slug, run_id=self._client.run_id, call_index=index)
        try:
            _write_json(self.out_dir / FAILED_DIR / name, payload)
        except OSError as write_exc:
            line = f"failed artifact not written: {type(write_exc).__name__}"
            self.warnings.append(line)
            if self.current is not None:
                self.pass_warnings[self.current].append(line)
            return _failure_summary(exc, None)
        return _failure_summary(exc, f"{FAILED_DIR}/{name}")

    def write_usage(self, error: str | None = None) -> dict[str, Any] | None:
        """이번 과금 기록이 있으면 병합한 usage.json을 쓰고 그 내용을 돌려준다(0건이면 None).

        `error`는 이번 실행의 slug 실패 사유(성공이면 None)다.
        """
        if not self.calls:
            return None
        assert self._client is not None  # 과금 호출은 클라이언트로만 생긴다
        purposes = {c.purpose for c in self.calls}
        merged = [c for c in self._base_calls if c.purpose not in purposes] + self.calls
        warnings = {
            name: list(self.pass_warnings[name] if name in self.ran else self._base_warnings[name])
            for name in PASS_ORDER
        }
        usage = _usage_payload(
            self.slug,
            self._client.run_id,
            merged,
            strategy=self.strategy,
            strategy_effective=self.effective or self.strategy,
            warnings=warnings,
            error=error,
        )
        _write_json(self.out_dir / "usage.json", usage)
        return usage

    def facts(self) -> tuple[dict[str, Any], RfpFacts]:
        data = _read_artifact(
            self.out_dir / "facts.json",
            f"facts.json not found: run --pass extract ({self.slug})",
        )
        try:
            facts = RfpFacts.model_validate(data["facts"])
        except (KeyError, ValidationError) as exc:
            raise _SlugFailure(f"invalid facts.json: {type(exc).__name__}") from exc
        return data["meta"], facts

    def stored_fits(self) -> tuple[dict[str, Any], list[RequirementFit]]:
        if self._fits is not None:  # 이번 실행의 match 결과
            return self._fits
        data = _read_artifact(
            self.out_dir / "fits.json", f"fits.json not found: run --pass match ({self.slug})"
        )
        try:
            fits = [RequirementFit.model_validate(f) for f in data["fits"]]
        except (KeyError, TypeError, ValidationError) as exc:
            raise _SlugFailure(f"invalid fits.json: {type(exc).__name__}") from exc
        return data["meta"], fits

    def stage_strategy(self, facts_meta: dict[str, Any]) -> StrategyName:
        """match·synth의 실제 전략(X29): 요청이 mapreduce면 mapreduce, 아니면 facts.json 값.

        256k 판정은 Pass1 입력으로 한 번만 하고 여기서는 다시 판정하지 않는다.
        facts.json의 요청 전략이 이번 요청과 다르면 경고만 낸다(실행은 계속).
        """
        stored = facts_meta.get("strategy")
        if stored is not None and stored != self.strategy and not self._mismatch_checked:
            line = f"facts.json strategy {stored} differs from requested {self.strategy}"
            self.warnings.append(line)
            if self.current is not None:
                self.pass_warnings[self.current].append(line)
        self._mismatch_checked = True
        effective: StrategyName = (
            "mapreduce" if self.strategy == "mapreduce" else _effective_of(facts_meta)
        )
        self.set_effective(effective)
        return effective

    # --- 단계 ---

    def extract(self, rfp_bytes: bytes) -> bool:
        """facts.json을 준비한다. 캐시 적중이면 True(호출·count_tokens·클라이언트 생성 없음)."""
        key = _extract_digest(
            rfp_bytes, model=self.model, strategy=self.strategy, effort=self.effort
        )
        if self.model_fingerprint is not None:
            key = _sha256((key + self.model_fingerprint).encode())
        facts_path = self.out_dir / "facts.json"
        if not self.force:
            cached_meta = _cached_meta(facts_path, key)
            if cached_meta is not None:
                self.set_effective(_effective_of(cached_meta))
                return True
        doc = self.doc(rfp_bytes)
        self.begin("extract")
        effective, _ = resolve_effective(self.strategy, doc, client=self.client(), model=self.model)
        self.set_effective(effective)
        warnings: list[str] = []
        facts, calls, strategy_warnings = self.strategy_for(effective).extract(doc)
        facts = self.locate(facts, doc)
        warnings += strategy_warnings
        self.pass_warnings["extract"].extend(strategy_warnings)
        self.calls.extend(calls)
        created_at = _now()
        stage: StageStamp | None = None
        try:
            inputs = {
                "rfp": rfp_input_hash(self.rfp_path, doc),
                "prompts": prompt_set_hash("facts", effective),
                "model_settings": model_settings_hash(
                    model=self.model,
                    strategy=effective,
                    effort=self.effort,
                    model_fingerprint=self.model_fingerprint,
                ),
            }
            stage = make_stage_stamp(
                "facts",
                inputs=inputs,
                output=facts.model_dump(mode="json"),
                parameters=llm_parameters(
                    model=self.model,
                    strategy=effective,
                    effort=self.effort,
                    model_fingerprint=self.model_fingerprint,
                ),
                computed_at=created_at,
            )
        except (OSError, ValueError, ValidationError):
            # bundle/source hashes가 없는 legacy fixture에는 현재 지문을 만들어 붙이지 않는다.
            stage = None
        facts_doc = _facts_payload(
            self.slug,
            key,
            facts=facts,
            citations=_facts_citations(facts),
            warnings=warnings,
            served_model=calls[-1].served_model,  # 마지막 Pass1 호출(chunk)
            model=self.model,
            strategy=self.strategy,
            effective=effective,
            effort=self.effort,
            created_at=created_at,
            stage=stage,
        )
        # usage를 먼저 쓴다: facts.json이 있으면(=캐시 적중 가능) usage.json도 있다(M2-02).
        self.write_usage()
        _write_json(facts_path, facts_doc)
        return False

    def match(self, rfp_bytes: bytes) -> None:
        doc = self.doc(rfp_bytes)
        self.begin("match")
        facts_meta, facts = self.facts()
        effective = self.stage_strategy(facts_meta)
        selection, knowledge_text = self.knowledge_for(doc)
        skipped = _skipped_warning(selection)
        self.warn("match", skipped)  # 입력 사실이므로 호출 실패여도 usage.json에 남는다
        fits, calls, warnings = self.strategy_for(effective).match(
            doc, facts, self.required_profile(), knowledge_text=knowledge_text
        )
        self.calls.extend(calls)
        if selection is not None:  # 전략(single·mapreduce) 공통 — 발췌 포함 페이지만 남긴다
            fits, page_warnings = annotate_evidence_pages(fits, selection)
            warnings = [*warnings, *page_warnings]
        fits = [self.locate(fit, doc) for fit in fits]
        self.warn("match", warnings)
        created_at = _now()
        stage: StageStamp | None = None
        if self.company_input_hash is not None:
            try:
                stage = make_stage_stamp(
                    "fits",
                    inputs={
                        "facts": stage_output_hash("facts", facts.model_dump(mode="json")),
                        "requirements": requirements_hash(doc),
                        "company": self.company_input_hash,
                        "knowledge": knowledge_input_hash(self.knowledge, selection),
                        "prompts": prompt_set_hash("fits", effective),
                        "model_settings": model_settings_hash(
                            model=self.model,
                            strategy=effective,
                            effort=self.effort,
                            model_fingerprint=self.model_fingerprint,
                        ),
                    },
                    output=[fit.model_dump(mode="json") for fit in fits],
                    parameters=llm_parameters(
                        model=self.model,
                        strategy=effective,
                        effort=self.effort,
                        knowledge=self.knowledge,
                        selection=selection,
                        model_fingerprint=self.model_fingerprint,
                    ),
                    computed_at=created_at,
                )
            except (OSError, ValueError, ValidationError):
                stage = None
        meta = {
            "facts_input_hash": facts_meta.get("input_hash"),
            "profile_hash": self.profile_hash,
            "company_input_hash": self.company_input_hash,
            "knowledge_hash": selection.knowledge_hash if selection is not None else None,
            "knowledge": (
                selection.model_dump(mode="json", exclude={"knowledge_hash"})
                if selection is not None
                else None
            ),
            "model": self.model,
            "served_model": calls[-1].served_model if calls else None,
            "strategy": self.strategy,
            "effort": self.effort,
            "prompt_hashes": {
                "system": _sha256(prompt_bytes("system.md")),
                "match": _sha256(prompt_bytes("match.md")),
            },
            "created_at": created_at,
            "warnings": [*skipped, *warnings],
        }
        if stage is not None:
            meta["stage"] = stage.model_dump(mode="json")
        self.write_usage()
        _write_json(
            self.out_dir / "fits.json",
            {"meta": meta, "fits": [f.model_dump(mode="json") for f in fits]},
        )
        self._fits = (meta, fits)

    def confirmed_gates(
        self, gates: list[GateResult], document: RfpDocument
    ) -> tuple[list[GateResult], str, list[str], GateResolver | None]:
        """게이트 사람 확인 기록(`<slug 폴더>/gate_confirmations.yaml`, GT-01)을 적용한다.

        파일이 없으면 그대로. 불량 파일은 `_SlugFailure` — synthesize(LLM 호출) 앞에서 불러
        과금 0으로 실패한다. 사유는 클래스명만 쓴다(메시지에 RFP 원문이 들어갈 수 있음).
        확인 경고(unmatched·ambiguous·ignored)는 비치명이라 synth 경고로 남긴다.
        마지막 값은 같은 확인 목록·rfp_hash로 만든 잠정 결론용 resolver다(파일이 없으면 None).
        """
        try:
            doc_conf = load_confirmations(self.out_dir / GATE_CONFIRMATIONS_FILE)
        except GateConfirmationError as exc:
            reason = f"invalid {GATE_CONFIRMATIONS_FILE}: {type(exc).__name__}"
            raise _SlugFailure(reason) from exc
        if doc_conf is None:
            return gates, confirmations_hash([]), [], None
        try:
            current_rfp_hash = rfp_input_hash(self.rfp_path, document)
        except (OSError, ValueError, ValidationError):
            current_rfp_hash = None
        resolution = resolve_confirmations(gates, doc_conf.confirmations, rfp_hash=current_rfp_hash)
        self.warn("synth", resolution.warnings)
        outdated = sorted(
            dict.fromkeys(gate_ref(code, value) for code, value in resolution.outdated)
        )
        resolver = make_gate_resolver(doc_conf.confirmations, current_rfp_hash)
        return resolution.gates, confirmations_hash(resolution.applicable), outdated, resolver

    def synth(self, rfp_bytes: bytes) -> None:
        doc = self.doc(rfp_bytes)
        self.begin("synth")
        facts_meta, facts = self.facts()
        facts = self.locate(facts, doc)
        effective = self.stage_strategy(facts_meta)
        fits_meta, fits = self.stored_fits()
        fits = [self.locate(fit, doc) for fit in fits]
        if fits_meta.get("facts_input_hash") != facts_meta.get("input_hash"):
            self.warn("synth", [FACTS_MISMATCH_WARNING])  # 경고만, synth 계속
        if fits_meta.get("company_input_hash") != self.company_input_hash:
            # 과거 fits에 현재 회사 지문을 추정해 채우지 않는다. REV-02가 이 경고와 저장된
            # fits meta를 읽어 stale/unknown을 판정할 수 있도록 원본은 그대로 둔다.
            self.warn("synth", [COMPANY_INPUT_MISMATCH_WARNING])
        selection, knowledge_text = self.knowledge_for(doc)
        if _knowledge_mismatch(fits_meta, self.knowledge, selection):
            self.warn("synth", [KNOWLEDGE_MISMATCH_WARNING])  # 경고만, synth 계속
        self.warn("synth", _skipped_warning(selection))
        as_of, _ = resolve_as_of(facts)
        profile = self.required_profile()
        gates, confirmation_input, confirmation_outdated, gate_resolver = self.confirmed_gates(
            evaluate_gates(facts, profile, as_of=as_of, portfolio_texts=self.portfolio_texts), doc
        )
        scores = estimate_scores(facts, profile, as_of=as_of)
        # Pass3 document는 그 slug의 실제 전략으로 고른다(X47 — 고정 "single" 금지).
        synth_out, calls, warnings = synthesize(
            doc,
            facts,
            gates,
            scores,
            fits,
            profile,
            client=self.client(),
            model=self.model,
            effort=self.effort,
            slug=self.slug,
            document=synth_document(effective, doc),
            knowledge_text=knowledge_text,
            tracer=self.tracer,
        )
        self.calls.extend(calls)
        self.warn("synth", warnings)
        synth_out = self.locate(synth_out, doc)
        # 제약 4: rfp 원문이 pdf면 숫자 사실 미확정 — 권고 가드·리포트 표지가 이 값만 본다.
        numeric_facts_unconfirmed = doc.primary_format == "pdf"
        recommendation, data_to_confirm = recommend(
            facts,
            gates,
            fits,
            synth_out,
            profile,
            scores,
            numeric_facts_unconfirmed=numeric_facts_unconfirmed,
        )
        usage = self.write_usage()
        assert usage is not None  # synth 호출 기록이 있다
        computed_at = _now()
        stages: dict[str, StageStamp] = {}
        facts_stage = artifact_stage_stamp("facts", facts_meta)
        fits_stage = artifact_stage_stamp("fits", fits_meta)
        if facts_stage is not None:
            stages["facts"] = facts_stage
        if fits_stage is not None:
            stages["fits"] = fits_stage

        facts_hash = stage_output_hash("facts", facts.model_dump(mode="json"))
        gates_hash = stage_output_hash("gates", [gate.model_dump(mode="json") for gate in gates])
        scores_hash = stage_output_hash(
            "scores", [score.model_dump(mode="json") for score in scores]
        )
        fits_hash = stage_output_hash("fits", [fit.model_dump(mode="json") for fit in fits])
        if self.company_input_hash is not None:
            stages["gates"] = make_stage_stamp(
                "gates",
                inputs={
                    "facts": facts_hash,
                    "company": self.company_input_hash,
                    "confirmations": confirmation_input,
                    "as_of": as_of_hash(as_of),
                    "portfolio_knowledge": portfolio_knowledge_hash(self.portfolio_texts),
                },
                output=[gate.model_dump(mode="json") for gate in gates],
                parameters=code_parameters(),
                computed_at=computed_at,
            )
            stages["scores"] = make_stage_stamp(
                "scores",
                inputs={
                    "facts": facts_hash,
                    "company": self.company_input_hash,
                    "as_of": as_of_hash(as_of),
                },
                output=[score.model_dump(mode="json") for score in scores],
                parameters=code_parameters(),
                computed_at=computed_at,
            )
            stages["synth"] = make_stage_stamp(
                "synth",
                inputs={
                    "facts": facts_hash,
                    "gates": gates_hash,
                    "scores": scores_hash,
                    "fits": fits_hash,
                    "company": self.company_input_hash,
                    "knowledge": knowledge_input_hash(self.knowledge, selection),
                    "prompts": prompt_set_hash("synth", effective),
                    "model_settings": model_settings_hash(
                        model=self.model,
                        strategy=effective,
                        effort=self.effort,
                        model_fingerprint=self.model_fingerprint,
                    ),
                },
                output=synth_out.model_dump(mode="json"),
                parameters=llm_parameters(
                    model=self.model,
                    strategy=effective,
                    effort=self.effort,
                    knowledge=self.knowledge,
                    selection=selection,
                    model_fingerprint=self.model_fingerprint,
                ),
                computed_at=computed_at,
            )
        analysis = Analysis(
            slug=self.slug,
            model=self.model,
            served_model=_served_models(usage["calls"]),
            strategy=self.strategy,
            strategy_effective=effective,
            numeric_facts_unconfirmed=numeric_facts_unconfirmed,
            knowledge=selection,
            company_input_hash=self.company_input_hash,
            effort=self.effort,
            facts=facts,
            gates=gates,
            scores=scores,
            fits=fits,
            risks=synth_out.risks,
            profitability=synth_out.profitability,
            checklist=synth_out.checklist,
            data_to_confirm=data_to_confirm,
            recommendation=recommendation,
            synth_output=synth_out,
            assessment=None,
            stages=stages,
            citations=_citations(facts, fits, synth_out),
            usage=usage["totals"],
            created_at=computed_at,
        )
        analysis = self.locate(analysis, doc)
        review_company = (
            profile if isinstance(profile, CompanyEvidenceView) else CompanyEvidenceView(profile)
        )
        analysis, _ = finalize_readiness(
            analysis,
            resolve_stage_states(
                self.out_dir,
                analysis,
                review_company,
                source_dir=self.rfp_path.parent,
                document=doc,
                portfolio_texts=self.portfolio_texts,
            ),
            [requirement.id for requirement in doc.requirements],
            company=review_company,
            computed_at=computed_at,
            confirmation_outdated_refs=confirmation_outdated,
            preparation_facts_artifact="facts.json",
            resolve_gates=gate_resolver,
            portfolio_texts=self.portfolio_texts,
        )
        self._summary = {
            "decision": None if analysis.assessment is None else analysis.assessment.decision,
            "fit_score": analysis.recommendation.fit_score,
            "gates": {k: sum(g.verdict == k for g in gates) for k in GATE_VERDICTS},
        }
        _write_json(self.out_dir / "analysis.json", analysis.model_dump(mode="json"))

    def outcome(
        self, status: Status, reason: str | None = None, cause: BaseException | None = None
    ) -> NoticeOutcome:
        return NoticeOutcome(
            slug=self.slug,
            status=status,
            reason=reason,
            calls=list(self.calls),
            warnings=list(self.warnings),
            cause=cause,
            trace_id=self.trace.trace_id or None,
        )


def run_notice(
    rfp_path: Path,
    out_dir: Path,
    *,
    client_factory: Callable[[], LlmClient],
    profile: CompanyProfile | CompanyEvidenceView | None,
    model: str,
    strategy: StrategyName,
    effort: str,
    passes: tuple[PassName, ...],
    force: bool,
    profile_hash: str | None = None,
    company_input_hash: str | None = None,
    knowledge: Knowledge | None = None,
    category_override: list[str] | None = None,
    tracer: Tracer | None = None,
    phase: Phase = "analyze",
    run_id: str | None = None,
    transport: str | None = None,
    portfolio_texts: Mapping[str, str] | None = None,
    model_fingerprint: str | None = None,
) -> NoticeOutcome:
    """공고 하나의 요청 단계를 extract → match → synth 순서로 실행한다(X19·X53).

    `rfp_path`(rfp.json)는 읽기만 하고 산출 파일은 모두 `out_dir`에 쓴다. slug 실패
    (전제조건·`LlmRefusal`·`LlmTruncated`·`LlmOutputError`·`LlmCallError`·rfp.json 불량)는
    failed 결과로 돌려준다. 치명 오류(`LedgerError`, `LlmConfigError`)는 그대로 전파한다.
    `profile_hash`는 fits.json meta에 그대로 기록한다(CLI는 `profile_file_hash`, 없으면 null).
    `company_input_hash`는 출처 sidecar까지 포함한 별도 지문이며 fits/analysis에 기록한다.
    `profile`은 extract 단독 실행에서만 None일 수 있다(match·synth는 필요).
    `knowledge`가 있으면 공고당 한 번 `prepare_knowledge(doc, knowledge,
    override=category_override)`로 발췌를 골라 match·synth에 같은 텍스트를 넘긴다(None이면
    지식 비활성, `category_override` 무시).
    `category_override`의 미지 slug는 호출자가 미리 검증한다(`ValueError`를 잡지 않음).
    `portfolio_texts`는 게이트가 대조할 회사 지식 실적 텍스트(`knowledge.load_portfolio_texts`,
    설계 2026-10-25-past-performance-capability 2.1)다. None이면 지식 없는 게이트 판정이다.
    `tracer`·`phase`·`run_id`·`transport`는 관측용(OBS-02): 공고 전체를 `tracer.notice_scope`로
    감싸고 `NoticeOutcome.trace_id`에 trace ID를 돌려준다. `tracer` None이면 기록 없음이다.
    """
    _check_passes(passes)
    if profile is None and any(p in passes for p in ("match", "synth")):
        raise ValueError("profile is required for match/synth passes")
    _pass1_prompt(strategy)  # 알 수 없는 전략이면 ValueError
    tracer = tracer if tracer is not None else NULL_TRACER
    with tracer.notice_scope(
        phase=phase,
        run_id=run_id,
        slug=out_dir.name,
        model=model,
        strategy=strategy,
        transport=transport,
    ) as trace:
        run = _NoticeRun(
            rfp_path,
            out_dir,
            client_factory=client_factory,
            profile=profile,
            model=model,
            strategy=strategy,
            effort=effort,
            force=force,
            profile_hash=profile_hash,
            company_input_hash=company_input_hash,
            knowledge=knowledge,
            category_override=category_override,
            tracer=tracer,
            trace=trace,
            run_id=run_id,
            portfolio_texts=portfolio_texts,
            model_fingerprint=model_fingerprint,
        )
        try:
            outcome = _run_passes(run, passes)
        except Exception as exc:  # 다시 올리는 치명 오류도 trace에는 실패로 남긴다
            phase_name = cast(PassName, run.current or passes[0])
            try:
                write_run_state(
                    out_dir,
                    phase=phase_name,
                    at=_now(),
                    outcome="failed",
                    error=_failure_reason(exc),
                )
            except OSError as state_exc:
                warnings.warn(
                    f"run_state.json not written: {type(state_exc).__name__}",
                    RuntimeWarning,
                    stacklevel=2,
                )
            trace.set_output(
                {
                    "passes": list(passes),
                    "decision": None,
                    "fit_score": None,
                    "gates": None,
                    "cost_usd": math.fsum(c.cost_usd for c in run.calls),
                    "calls": len(run.calls),
                    "status": "failed",
                    "failure": _failure_reason(exc),
                    "cache_hit": not run.calls,
                }
            )
            raise
        phase_name = cast(PassName, run.current or passes[-1])
        try:
            write_run_state(
                out_dir,
                phase=phase_name,
                at=_now(),
                outcome="failed" if outcome.status == "failed" else "success",
                error=outcome.reason if outcome.status == "failed" else None,
            )
        except OSError as state_exc:
            line = f"run_state.json not written: {type(state_exc).__name__}"
            outcome = replace(outcome, warnings=[*outcome.warnings, line])
        run.finish_trace(passes, outcome)
        return outcome


def _run_passes(run: _NoticeRun, passes: tuple[PassName, ...]) -> NoticeOutcome:
    """요청 pass를 순서대로 돌려 `NoticeOutcome`을 만든다(slug 실패는 결과로, 치명 오류는 전파)."""
    cached = False
    try:
        try:
            rfp_bytes = run.rfp_path.read_bytes()
        except OSError as exc:
            raise _SlugFailure(f"cannot read rfp.json: {type(exc).__name__}") from exc
        run.record_input(rfp_bytes)
        if "extract" in passes:
            cached = run.extract(rfp_bytes)
        if "match" in passes:
            run.match(rfp_bytes)
        if "synth" in passes:
            run.synth(rfp_bytes)
    except _SlugFailure as exc:
        run.write_usage(error=str(exc))
        return run.outcome("failed", str(exc))
    except PassError as exc:
        # 전략이 감싼 slug 실패: 과금된 호출(실패 호출 record 포함)을 남기고 cause로 사유를 만든다
        run.calls.extend(exc.calls)
        run.warnings.extend(exc.warnings)
        if run.current is not None:
            run.pass_warnings[run.current].extend(exc.warnings)
        reason = run.failure_error(exc.cause)  # 출력 오류·잘림이면 _failed/ 저장(calls 반영 뒤)
        run.write_usage(error=reason)
        return run.outcome("failed", reason, exc.cause)
    except (LlmRefusal, LlmTruncated, LlmOutputError) as exc:
        # 응답을 받은 뒤의 실패: 과금됐으므로 원장 줄과 같은 record를 usage.json에 남긴다(X3·X20).
        run.calls.append(exc.record)
        reason = run.failure_error(exc)
        run.write_usage(error=reason)
        return run.outcome("failed", reason, exc)
    except LlmCallError as exc:
        run.write_usage(error=_failure_reason(exc))  # 앞 단계 과금 기록만. 0건이면 쓰지 않는다
        return run.outcome("failed", _failure_reason(exc), exc)
    return run.outcome("cached" if cached and passes == ("extract",) else "ok")
