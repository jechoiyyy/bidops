"""REV-02 단계 지문과 실행 기록의 단일 canonical 계약.

이 모듈은 해시를 계산할 수 있다는 이유만으로 legacy 산출물을 current로 승격하지 않는다.
호출자는 자신이 실제로 생성한 단계에만 :func:`make_stage_stamp`를 사용해야 한다.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError, field_validator

from bid_deep_engine.analysis.evidence_locations import canonical_json
from bid_deep_engine.analysis.prompt_files import prompt_bytes
from bid_deep_engine.analysis.schemas import (
    REASON_CODE_ORDER,
    Analysis,
    Assessment,
    Stage,
    StageParameters,
    StageStamp,
    StageState,
    StrategyName,
)
from bid_deep_engine.company.knowledge import Knowledge, KnowledgeSelection, render_knowledge
from bid_deep_engine.ingest.models import NoticeBundle, RfpDocument

STAGE_ORDER: tuple[Stage, ...] = (
    "facts",
    "gates",
    "scores",
    "fits",
    "synth",
    "requests",
    "recommendation",
)
READINESS_STAGES: tuple[Stage, ...] = ("facts", "gates", "scores", "fits", "synth")
STAGE_INPUT_KEYS: dict[Stage, tuple[str, ...]] = {
    "facts": ("rfp", "prompts", "model_settings"),
    "gates": ("facts", "company", "confirmations", "as_of", "portfolio_knowledge"),
    "scores": ("facts", "company", "as_of"),
    "fits": ("facts", "requirements", "company", "knowledge", "prompts", "model_settings", "work_units"),
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
STAGE_VERSIONS: dict[Stage, str] = {
    "facts": "extract-v1",
    # gates-v2: 실적 지식·역량 대안·동의어(설계 2026-10-25-past-performance-capability)
    "gates": "gates-v3",
    "scores": "scores-v1",
    "fits": "match-v1",
    "synth": "synth-v1",
    "requests": "requests-v2",
    "recommendation": "recommendation-v2",
}
READINESS_RULES = "readiness-v1"
_REASON_INDEX = {code: index for index, code in enumerate(REASON_CODE_ORDER)}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_hash(value: Any) -> str:
    """null, 배열 순서, 숫자 타입을 보존한 canonical JSON SHA256."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _without_location_metadata(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        ignored = set()
        if "quote" in value:
            ignored.update(
                {"locations", "location_status", "block_locations", "block_location_status"}
            )
        if "req_id" in value and "fit" in value:
            ignored.update({"name", "definition"})
            if value.get("instance_key") is None:
                ignored.add("instance_key")
        if "blocking" in value and "affects" in value:
            ignored.update({"purpose", "availability"})
        return {
            key: _without_location_metadata(item)
            for key, item in value.items()
            if key not in ignored
        }
    if isinstance(value, list):
        return [_without_location_metadata(item) for item in value]
    return value


def stage_input_payload(stage: Stage, inputs: Mapping[str, str | None]) -> dict[str, Any]:
    expected = STAGE_INPUT_KEYS[stage]
    # Older match-v1 artifacts have no classification input.
    if stage == "fits" and "work_units" not in inputs:
        expected = expected[:-1]
    if set(inputs) != set(expected):
        raise ValueError(f"{stage} inputs must be exactly {expected!r}")
    if any(
        key != "work_units" if value is None else not _HASH_RE.fullmatch(value)
        for key, value in inputs.items()
    ):
        raise ValueError("stage input values must be 64 lowercase hex hashes")
    return {
        "schema_version": 1,
        "stage": stage,
        "version": STAGE_VERSIONS[stage],
        "inputs": {key: inputs[key] for key in expected},
    }


def stage_input_hash(stage: Stage, inputs: Mapping[str, str | None]) -> str:
    return canonical_hash(stage_input_payload(stage, inputs))


def stage_output_payload(stage: Stage, output: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "stage": stage,
        "output": _without_location_metadata(output),
    }


def stage_output_hash(stage: Stage, output: Any) -> str:
    return canonical_hash(stage_output_payload(stage, output))


def make_stage_stamp(
    stage: Stage,
    *,
    inputs: Mapping[str, str | None],
    output: Any,
    parameters: StageParameters,
    computed_at: str,
) -> StageStamp:
    """실제 producer가 가진 완전한 입력/출력으로 stamp를 만든다."""
    ordered = stage_input_payload(stage, inputs)["inputs"]
    return StageStamp(
        input_hash=stage_input_hash(stage, ordered),
        output_hash=stage_output_hash(stage, output),
        version=STAGE_VERSIONS[stage],
        computed_at=computed_at,
        inputs=ordered,
        parameters=parameters,
    )


def stage_stamp_matches(
    stage: Stage,
    stamp: StageStamp,
    *,
    inputs: Mapping[str, str | None],
    output: Any,
) -> bool:
    """시각/환경 선호는 비교하지 않고 저장 당시 parameters와 현재 내용 계약만 검사한다."""
    try:
        expected_input = stage_input_hash(stage, inputs)
        expected_output = stage_output_hash(stage, output)
    except ValueError:
        return False
    return (
        stamp.version == STAGE_VERSIONS[stage]
        and stamp.inputs == stage_input_payload(stage, inputs)["inputs"]
        and stamp.input_hash == expected_input
        and stamp.output_hash == expected_output
    )


def analysis_stage_output(analysis: Analysis, stage: Stage) -> Any | None:
    """analysis.json에서 spec이 정한 한 단계의 의미 출력만 투영한다."""
    if stage == "facts":
        return analysis.facts.model_dump(mode="json")
    if stage == "gates":
        return [item.model_dump(mode="json") for item in analysis.gates]
    if stage == "scores":
        return [item.model_dump(mode="json") for item in analysis.scores]
    if stage == "fits":
        return [item.model_dump(mode="json") for item in analysis.fits]
    if stage == "synth":
        return (
            None if analysis.synth_output is None else analysis.synth_output.model_dump(mode="json")
        )
    if stage == "requests":
        return {
            "data_to_confirm": [item.model_dump(mode="json") for item in analysis.data_to_confirm],
            "raw_data_to_confirm": (
                None
                if analysis.raw_data_to_confirm is None
                else [item.model_dump(mode="json") for item in analysis.raw_data_to_confirm]
            ),
            "review_actions": (
                None
                if analysis.review_actions is None
                else analysis.review_actions.model_dump(mode="json")
            ),
        }
    return {
        "recommendation": analysis.recommendation.model_dump(mode="json"),
        "assessment": (
            None
            if analysis.assessment is None
            else analysis.assessment.model_dump(mode="json", exclude={"provisional"})
        ),
    }


def _requirement_inputs(document: RfpDocument) -> list[dict[str, Any]]:
    return [
        req.model_dump(mode="json", exclude={"instance_key"} if req.instance_key is None else set())
        for req in document.requirements
    ]


def rfp_input_payload(rfp_path: Path, document: RfpDocument | None = None) -> dict[str, Any]:
    """실제 rfp.json 옆 bundle의 파일 순서/해시로 facts 입력 payload를 만든다."""
    doc = document or RfpDocument.model_validate_json(rfp_path.read_text(encoding="utf-8"))
    bundle = NoticeBundle.model_validate_json(
        (rfp_path.parent / "bundle.json").read_text(encoding="utf-8")
    )
    if bundle.slug != doc.slug or [item.path for item in bundle.files] != doc.source_files:
        raise ValueError("bundle/rfp source files mismatch")
    return {
        "schema_version": 1,
        "source_files": [{"path": source.path, "sha256": source.sha256} for source in bundle.files],
        "full_text": doc.full_text,
        "sections": [item.model_dump(mode="json") for item in doc.sections],
        "requirements": _requirement_inputs(doc),
        "primary_format": doc.primary_format,
    }


def rfp_input_hash(rfp_path: Path, document: RfpDocument | None = None) -> str:
    return canonical_hash(rfp_input_payload(rfp_path, document))


def requirements_hash(document: RfpDocument) -> str:
    return canonical_hash(_requirement_inputs(document))


def prompt_set_hash(stage: Literal["facts", "fits", "synth"], strategy: StrategyName) -> str:
    names = {
        "facts": ("system.md", "extract.md" if strategy == "single" else "extract_partial.md"),
        "fits": ("system.md", "match.md", "units.md"),
        "synth": ("system.md", "synth.md"),
    }[stage]
    files = sorted(
        ({"name": Path(name).stem, "text": prompt_bytes(name).decode("utf-8")} for name in names),
        key=lambda item: item["name"],
    )
    return canonical_hash({"strategy": strategy, "files": files})


def model_settings_hash(
    *,
    model: str,
    strategy: StrategyName,
    effort: str,
    model_fingerprint: str | None = None,
) -> str:
    value = {"model": model, "strategy": strategy, "effort": effort}
    if model_fingerprint is not None:
        value["model_fingerprint"] = model_fingerprint
    return canonical_hash(value)


def as_of_hash(value: Any) -> str:
    return canonical_hash(value.isoformat() if hasattr(value, "isoformat") else str(value))


def confirmations_hash(confirmations: Iterable[Any]) -> str:
    """호출자가 현재 rfp/rule hash에 맞는 항목만 넘긴 목록을 rule_hash 순으로 해시한다."""
    values = [
        item.model_dump(mode="json") if isinstance(item, BaseModel) else dict(item)
        for item in confirmations
    ]
    values.sort(key=lambda item: item.get("rule_hash") or "")
    return canonical_hash(values)


def portfolio_knowledge_hash(texts: Mapping[str, str] | None) -> str:
    """gates 입력 `portfolio_knowledge`: 게이트가 대조한 실적 페이지 텍스트(실적 ID 정렬)의 해시.

    None과 빈 값은 같다(지식 없음). 텍스트는 `knowledge.load_portfolio_texts` 결과 그대로다.
    """
    pages = [{"portfolio_id": key, "text": (texts or {})[key]} for key in sorted(texts or {})]
    return canonical_hash({"schema_version": 1, "pages": pages})


def _selection_source(selection: KnowledgeSelection) -> Literal["auto", "manual"]:
    return "manual" if selection.category_source == "override" else "auto"


def _render_page(knowledge: Knowledge, selection: KnowledgeSelection, slug: str) -> str:
    one = selection.model_copy(update={"pages": [slug], "skipped": []})
    rendered = render_knowledge(knowledge, one)
    return rendered.split("\n\n", 1)[1]


def knowledge_input_hash(
    knowledge: Knowledge | None, selection: KnowledgeSelection | None, *, work_unit_evidence: str = ""
) -> str:
    if knowledge is None or selection is None:
        if knowledge is not None or selection is not None:
            raise ValueError("knowledge and selection must both be active or inactive")
        return canonical_hash(None)
    payload = {
        "selection": {
            "categories": list(selection.categories),
            "category_source": _selection_source(selection),
        },
        "pages": [
            {"slug": slug, "text": _render_page(knowledge, selection, slug)}
            for slug in selection.pages
        ],
    }
    if work_unit_evidence:
        payload["work_unit_evidence"] = work_unit_evidence
    return canonical_hash(payload)


def code_parameters() -> StageParameters:
    return StageParameters(
        model=None,
        strategy=None,
        effort=None,
        knowledge_root=None,
        knowledge_categories=[],
        knowledge_category_source="none",
    )


def llm_parameters(
    *,
    model: str,
    strategy: StrategyName,
    effort: str,
    knowledge: Knowledge | None = None,
    selection: KnowledgeSelection | None = None,
    model_fingerprint: str | None = None,
) -> StageParameters:
    if knowledge is None or selection is None:
        if knowledge is not None or selection is not None:
            raise ValueError("knowledge and selection must both be active or inactive")
        return StageParameters(
            model=model,
            strategy=strategy,
            effort=effort,
            model_fingerprint=model_fingerprint,
            knowledge_root=None,
            knowledge_categories=[],
            knowledge_category_source="none",
        )
    return StageParameters(
        model=model,
        strategy=strategy,
        effort=effort,
        model_fingerprint=model_fingerprint,
        knowledge_root=str(knowledge.root.resolve()),
        knowledge_categories=list(selection.categories),
        knowledge_category_source=_selection_source(selection),
    )


def canonical_reasons(reasons: Iterable[Mapping[str, Any] | BaseModel]) -> list[dict[str, Any]]:
    """상세 reason을 stable refs/순서로 정규화하고 동일 identity를 합친다."""
    normalized: list[dict[str, Any]] = []
    for reason in reasons:
        raw = reason.model_dump(mode="json") if isinstance(reason, BaseModel) else dict(reason)
        code = str(raw["code"])
        if code not in _REASON_INDEX:
            raise ValueError(f"unknown reason code: {code}")
        stage = raw.get("stage")
        refs = sorted(dict.fromkeys(str(ref) for ref in raw.get("refs", [])))
        normalized.append(
            {"code": code, "stage": stage, "refs": refs, "message": str(raw["message"])}
        )
    normalized.sort(
        key=lambda item: (
            _REASON_INDEX[item["code"]],
            item["stage"] or "",
            item["refs"],
            item["message"],
        )
    )
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, Any, tuple[str, ...]]] = set()
    for item in normalized:
        identity = (item["code"], item["stage"], tuple(item["refs"]))
        if identity not in seen:
            seen.add(identity)
            result.append(item)
    return result


def readiness_payload(
    assessment: Assessment,
    reasons: Iterable[Mapping[str, Any] | BaseModel],
    stage_states: Mapping[Stage, StageState],
) -> dict[str, Any]:
    missing = [stage for stage in READINESS_STAGES if stage not in stage_states]
    if missing:
        raise ValueError(f"readiness stage states missing: {', '.join(missing)}")
    return {
        "schema_version": 1,
        "assessment": assessment.model_dump(mode="json", exclude={"provisional"}),
        "reasons": canonical_reasons(reasons),
        "stage_states": {stage: stage_states[stage] for stage in READINESS_STAGES},
        "readiness_rules": READINESS_RULES,
    }


def readiness_hash(
    assessment: Assessment,
    reasons: Iterable[Mapping[str, Any] | BaseModel],
    stage_states: Mapping[Stage, StageState],
) -> str:
    return canonical_hash(readiness_payload(assessment, reasons, stage_states))


def readiness_rules_hash() -> str:
    return canonical_hash(READINESS_RULES)


def stage_ref(stage: Stage) -> str:
    return f"stage:{stage}"


def gate_ref(code: str, rule_hash: str | None) -> str:
    return "stage:gates" if rule_hash is None else f"gate:{code}:{rule_hash}"


def score_ref(index: int) -> str:
    if index < 0:
        raise ValueError("score index must be >= 0")
    return f"score:{index}"


def fit_ref(req_id: str) -> str:
    return f"fit:{req_id}"


def field_ref(path: str) -> str:
    return f"field:{path}"


def notice_ref(pointer: str) -> str:
    if pointer != "" and not pointer.startswith("/"):
        raise ValueError("notice reference must be an RFC 6901 JSON Pointer")
    return f"notice:{pointer}"


def execution_ref(title: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFC", title).strip().split())
    return f"execution:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


RunPhase = Literal["extract", "match", "synth", "regate"]
RunOutcome = Literal["success", "failed"]


class LastAttempt(BaseModel):
    phase: RunPhase
    at: str
    outcome: RunOutcome
    error: str | None

    @field_validator("at")
    @classmethod
    def _validate_offset(cls, value: str) -> str:
        # StageStamp와 같은 ISO offset 계약. 별도 enum/sidecar 버전은 만들지 않는다.
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("at must include an ISO 8601 UTC offset")
        return value


class RunState(BaseModel):
    schema_version: Literal[1] = 1
    last_attempt: LastAttempt


def write_run_state(
    slug_dir: Path,
    *,
    phase: RunPhase,
    at: str,
    outcome: RunOutcome,
    error: str | None,
) -> None:
    """정확한 schema 1 sidecar를 원자적으로 교체한다. 실패는 호출자가 warning으로 강등한다."""
    state = RunState(last_attempt=LastAttempt(phase=phase, at=at, outcome=outcome, error=error))
    path = slug_dir / "run_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_stage_stamp(value: Any) -> StageStamp | None:
    """legacy meta의 선택 stamp만 엄격 검증해 읽고, 불완전 메타는 승격하지 않는다."""
    try:
        return StageStamp.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        return None


def artifact_stage_stamp(
    stage: Literal["facts", "fits"], meta: Mapping[str, Any]
) -> StageStamp | None:
    """facts/fits producer meta에서 같은 stages 계약의 stamp만 보존·복원한다."""
    stamp = read_stage_stamp(meta.get("stage"))
    if stamp is None:
        return None
    if stamp.version != STAGE_VERSIONS[stage]:
        return None
    if set(stamp.inputs) != set(STAGE_INPUT_KEYS[stage]):
        return None
    if stamp.input_hash != stage_input_hash(stage, stamp.inputs):
        return None
    if meta.get("created_at") != stamp.computed_at:
        return None
    return stamp
