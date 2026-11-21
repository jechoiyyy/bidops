"""REV-02 현재 권고 가능 여부의 공통 읽기 모델.

이 모듈은 LLM·환경 설정을 열지 않고 파일을 쓰지 않는다. producer는 :func:`finalize_readiness`
를 메모리에서 호출하고, report 계층은 :func:`build_review`로 같은 계산을 현재 입력에 재검증한다.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from bid_deep_engine.analysis.gates import (
    eligibility_rule_hash,
    evaluate_gates,
    evaluate_gates_traced,
    onsite_region_key,
    resolve_as_of,
)
from bid_deep_engine.analysis.labels import GATE_LABELS
from bid_deep_engine.analysis.provenance import (
    READINESS_STAGES,
    STAGE_ORDER,
    RunState,
    analysis_stage_output,
    artifact_stage_stamp,
    as_of_hash,
    canonical_reasons,
    code_parameters,
    confirmations_hash,
    field_ref,
    fit_ref,
    gate_ref,
    knowledge_input_hash,
    make_stage_stamp,
    model_settings_hash,
    notice_ref,
    portfolio_knowledge_hash,
    prompt_set_hash,
    readiness_hash,
    readiness_rules_hash,
    requirements_hash,
    rfp_input_hash,
    stage_output_hash,
    stage_ref,
    stage_stamp_matches,
)
from bid_deep_engine.analysis.recommend import (
    CONDITIONAL_THRESHOLD,
    GO_THRESHOLD,
    _is_int,
    decision_factors,
    decision_for_score,
    fit_score_for,
    round_half_up,
)
from bid_deep_engine.analysis.schemas import (
    CONDITION_KIND_ORDER,
    REASON_CODE_ORDER,
    Analysis,
    Assessment,
    ConditionKind,
    DataToConfirm,
    DecisionValue,
    FitCoverage,
    GateCode,
    GateResult,
    PolicyConflict,
    Provisional,
    ProvisionalBasis,
    ProvisionalCondition,
    ReasonCode,
    RequirementFit,
    ReviewActions,
    RfpFacts,
    ScoreInterval,
    Stage,
    StageStamp,
    StageState,
)
from bid_deep_engine.company.hints import DEFAULT_HINT, hint_for
from bid_deep_engine.company.knowledge import (
    KnowledgeError,
    gate_knowledge_root,
    load_knowledge,
    load_portfolio_texts,
    prepare_knowledge,
)
from bid_deep_engine.company.loader import ProfileError, load_evidence_view
from bid_deep_engine.company.provenance import ASSUMED_LEVELS, DECISION_LEVELS, CompanyEvidenceView
from bid_deep_engine.feedback.gate_confirmations import (
    ConfirmationResolution,
    GateConfirmation,
    GateConfirmationError,
    load_confirmations,
    resolve_confirmations,
)
from bid_deep_engine.ingest.models import RfpDocument

_MESSAGES: dict[ReasonCode, str] = {
    "legacy_metadata": "생성 입력 메타데이터를 현재 자료로 검증할 수 없습니다.",
    "stale_stage": "단계 입력·출력 또는 규칙 버전이 현재 자료와 다릅니다.",
    "missing_stage": "단계 산출물이 없습니다.",
    "empty_requirements": "공고 요구사항이 추출되지 않았습니다.",
    "missing_fits": "요구사항별 적합도 매핑이 완전하지 않습니다.",
    "unknown_gate": "필수 참가자격 판정이 UNKNOWN입니다.",
    "untrusted_company_input": "확인되지 않은 회사 입력 때문에 참가자격을 확정할 수 없습니다.",
    "uncertain_fit_decision": "UNKNOWN 적합도의 양끝 결정이 서로 다릅니다.",
    "untrusted_failure": "FAIL 판정의 원문·회사 입력 신뢰 조건이 충분하지 않습니다.",
    "confirmation_outdated": "사람 확인 기록이 현재 원문·판정 규칙과 일치하지 않습니다.",
    "hard_gate_fail": "현재 확인된 참가자격 FAIL이 있습니다.",
    "min_contract_fail": "현재 확인된 사업금액이 회사 최소계약금액보다 작습니다.",
}


_REQUEST_ROWS = TypeAdapter(list[DataToConfirm])
_REVIEW_ACTIONS = TypeAdapter(ReviewActions)


def _reason(code: ReasonCode, stage: Stage | None, refs: Sequence[str]) -> dict[str, Any]:
    ordered = sorted(dict.fromkeys(refs))
    suffix = f" ({', '.join(ordered)})" if ordered else ""
    return {"code": code, "stage": stage, "refs": ordered, "message": _MESSAGES[code] + suffix}


def _today(now: date | datetime | None) -> date | None:
    if isinstance(now, datetime):
        return now.date()
    return now


def _rule_hash(gate: GateResult) -> str | None:
    value = getattr(gate, "rule_hash", None)
    return value if isinstance(value, str) else None


def _gate_ref(gate: GateResult) -> str:
    return gate_ref(gate.code, _rule_hash(gate))


def _verified_evidence(gate: GateResult) -> bool:
    return bool(gate.evidence) and all(item.verified is True for item in gate.evidence)


def _gate_conflicted(facts: RfpFacts, gate: GateResult) -> bool:
    quotes = {item.quote for item in gate.evidence}
    origin_hash = _rule_hash(gate)
    rule_indexes = {
        index
        for index, rule in enumerate(facts.eligibility)
        if origin_hash is not None and eligibility_rule_hash(rule.text) == origin_hash
    }
    for conflict in facts.conflicts:
        if quotes & {item.quote for item in conflict.evidence}:
            return True
        field = conflict.field
        if field in ("eligibility", "eligibility[]"):
            return True
        conflict_indexes = {
            index
            for index in range(len(facts.eligibility))
            if field.startswith(f"eligibility[{index}]") or field.startswith(f"eligibility.{index}")
        }
        if conflict_indexes and (not rule_indexes or bool(conflict_indexes & rule_indexes)):
            return True
    return False


def _trusted_failure_basis(analysis: Analysis, gate: GateResult) -> bool:
    """FAIL 신뢰의 비입력 기준: OTHER·사람 확인·인용 미검증·원문 충돌·pdf 실적이 아니다.

    REV-02 `_deterministic_failures`와 PF-01 `compute_provisional`이 같은 기준을 쓴다.
    """
    return not (
        gate.code == "OTHER"
        or gate.company_value.startswith("사람 확인 ")
        or not _verified_evidence(gate)
        or _gate_conflicted(analysis.facts, gate)
        or (analysis.numeric_facts_unconfirmed and gate.code == "PAST_PERFORMANCE")
    )


def _deterministic_failures(
    analysis: Analysis,
    company: CompanyEvidenceView | None,
    now: date | datetime | None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> list[GateResult]:
    if company is None:
        return []
    as_of, _ = resolve_as_of(analysis.facts, _today(now))
    fresh = evaluate_gates(analysis.facts, company, as_of=as_of, portfolio_texts=portfolio_texts)
    trusted: list[GateResult] = []
    for stored, regenerated in zip(analysis.gates, fresh, strict=False):
        if (
            stored.verdict != "FAIL"
            or regenerated.verdict != "FAIL"
            or stored.code != regenerated.code
            or stored.rule_text != regenerated.rule_text
            or _rule_hash(stored) is None
            or _rule_hash(stored) != _rule_hash(regenerated)
            or not _trusted_failure_basis(analysis, stored)
        ):
            continue
        if any(
            company.get(path)["effective_level"] not in DECISION_LEVELS
            for path in regenerated.input_fields
        ):
            continue
        trusted.append(stored)
    return trusted


def _trusted_min_contract(
    analysis: Analysis,
    company: CompanyEvidenceView | None,
    stage_states: Mapping[Stage, StageState],
) -> bool:
    if company is None or stage_states.get("facts") != "current":
        return False
    budget = analysis.facts.project.budget_krw
    evidence = analysis.facts.project.evidence
    budget_digits = str(budget)
    verified_budget = any(
        item.verified is True
        and "".join(character for character in item.quote if character.isdigit()).find(
            budget_digits
        )
        >= 0
        for item in evidence
    )
    minimum_info = company.get("policy.min_contract_amount_krw")
    return bool(
        not analysis.numeric_facts_unconfirmed
        and _is_int(budget)
        and minimum_info["effective_level"] in DECISION_LEVELS
        and _is_int(minimum_info["value"])
        and budget < minimum_info["value"]
        and verified_budget
        and not any(c.field == "project.budget_krw" for c in analysis.facts.conflicts)
    )


def _fit_mapping_reasons(
    requirement_ids: Sequence[str] | None, fits: Sequence[RequirementFit]
) -> tuple[list[dict[str, Any]], bool]:
    if requirement_ids is None:
        return [], False
    reasons: list[dict[str, Any]] = []
    if not requirement_ids:
        reasons.append(_reason("empty_requirements", "fits", [stage_ref("fits")]))
    expected = Counter(requirement_ids)
    actual = Counter(item.key for item in fits)
    bad = sorted(
        key for key in expected.keys() | actual.keys() if expected[key] != 1 or actual[key] != 1
    )
    if bad:
        reasons.append(_reason("missing_fits", "fits", [fit_ref(key) for key in bad]))
    elif requirement_ids and fits and all(item.fit == "UNKNOWN" for item in fits):
        reasons.append(_reason("missing_fits", "fits", [fit_ref(item.key) for item in fits]))
    return reasons, not reasons


def _score_interval(
    analysis: Analysis,
    stage_states: Mapping[Stage, StageState],
    mapping_complete: bool,
    company: CompanyEvidenceView | None,
) -> tuple[ScoreInterval | None, tuple[DecisionValue, DecisionValue] | None]:
    if (
        company is None
        or not mapping_complete
        or any(stage_states.get(stage) != "current" for stage in ("facts", "gates", "fits"))
        or not analysis.fits
        or all(item.fit == "UNKNOWN" for item in analysis.fits)
    ):
        return None, None
    gate_counts, _, _, below_min, guarded = decision_factors(
        analysis.facts,
        analysis.gates,
        company,
        numeric_facts_unconfirmed=analysis.numeric_facts_unconfirmed,
    )
    if all(item.fit != "UNKNOWN" for item in analysis.fits):
        score, *_ = fit_score_for(analysis.gates, analysis.fits)
        decision = decision_for_score(
            score, gate_counts=gate_counts, below_min=below_min, guarded=guarded
        )[1]
        return ScoreInterval(min=score, max=score), (decision, decision)  # type: ignore[return-value]

    low, *_ = fit_score_for(analysis.gates, analysis.fits, unknown_fit=0)
    high, *_ = fit_score_for(analysis.gates, analysis.fits, unknown_fit=100)
    low_decision = decision_for_score(
        low, gate_counts=gate_counts, below_min=below_min, guarded=guarded
    )[1]
    high_decision = decision_for_score(
        high, gate_counts=gate_counts, below_min=below_min, guarded=guarded
    )[1]
    return ScoreInterval(min=low, max=high), (low_decision, high_decision)  # type: ignore[arg-type]


# --- PF-01 잠정 결론 ---

FIT_COVERAGE_MIN_RATIO = 0.5  # 고정(사용자 결정): judged < total * 0.5 이면 판단 부족 조건
_PROVISIONAL_FIT_POINTS: dict[str, int] = {"FULL": 100, "PARTIAL": 50, "GAP": 0}
_ASSUMABLE_LEVELS = frozenset({"public", "estimate"})
_ACTION_PATH_RE = re.compile(r"[a-z_]+\.[a-z_]")
_RISK_HARD_CODES = frozenset({"ONSITE_LOCATION", "STAFFING_CAPACITY"})
_HINT_FALLBACK = "회사 기록 확인"
_MIN_CONTRACT_PATH = "policy.min_contract_amount_krw"

GateResolver = Callable[[list[GateResult]], list[GateResult]]


def make_gate_resolver(
    confirmations: Sequence[GateConfirmation], rfp_hash: str | None
) -> GateResolver:
    """저장 게이트와 같은 확인 목록·rfp_hash로 사람 확인을 적용하는 함수(잠정 결론 전용)."""
    items = list(confirmations)

    def resolve(gates: list[GateResult]) -> list[GateResult]:
        return list(resolve_confirmations(gates, items, rfp_hash=rfp_hash).gates)

    return resolve


def _condition_hint(path: str) -> str:
    hint = hint_for(path)
    return _HINT_FALLBACK if hint == DEFAULT_HINT else hint


def _risk_check(action: str | None) -> str:
    if action is None or not action.strip():
        return "원문 조건 확인"
    if _ACTION_PATH_RE.search(action) or "schema.md" in action:
        return "원문 조건 확인"
    return action


def _group_by_code(gates: Sequence[GateResult]) -> list[tuple[GateCode, list[GateResult]]]:
    groups: dict[GateCode, list[GateResult]] = {}
    for gate in gates:
        groups.setdefault(gate.code, []).append(gate)
    return list(groups.items())


def _gate_condition(
    kind: ConditionKind,
    code: GateCode,
    group: Sequence[GateResult],
    view: CompanyEvidenceView,
) -> ProvisionalCondition:
    label = GATE_LABELS[code]
    fields = list(
        dict.fromkeys(
            [
                *(path for gate in group for path in gate.unknown_fields),
                *(
                    path
                    for gate in group
                    for path in gate.input_fields
                    if view.get(path)["effective_level"] not in DECISION_LEVELS
                ),
            ]
        )
    )
    hints = " / ".join(dict.fromkeys(_condition_hint(path) for path in fields))
    if kind == "recheck_fail":
        title = f"{label} 미충족(재확인 필요)"
        check = hints or "증빙 서류와 원문 조항 확인"
        if_not = "현재 기록·원문 기준 참가 불가 — 증빙이 있으면 재검토"
    elif kind == "risk_gate":
        title = label
        check = _risk_check(group[0].action)
        if_not = (
            "해결하지 못하면 포기 검토"
            if code in _RISK_HARD_CODES
            else "부담을 감수할 수 있는지 검토"
        )
    else:
        title = label
        check = hints or "공고 원문 조항 확인"
        if_not = "충족하지 못하면 참가 불가"
    if len(group) > 1:
        title = f"{title} ({len(group)}건)"
    refs = [*(_gate_ref(gate) for gate in group), *(field_ref(path) for path in fields)]
    return ProvisionalCondition(
        id=f"{kind}:{code}",
        kind=kind,
        title=title,
        check=check,
        if_not=if_not,
        gate_codes=[code],
        company_fields=fields,
        refs=list(dict.fromkeys(refs)),
    )


def _provisional_fits(
    fits: Sequence[RequirementFit], requirement_ids: Sequence[str] | None
) -> tuple[FitCoverage, int | None, list[str]]:
    """(판정 범위, 판정 적합도 평균, 판정되지 않은 요구사항 ID 정렬)."""
    ids = list(dict.fromkeys(requirement_ids or ()))
    by_id: dict[str, RequirementFit] = {}
    for item in fits:
        by_id.setdefault(item.key, item)
    points = [
        _PROVISIONAL_FIT_POINTS[by_id[req_id].fit]
        for req_id in ids
        if req_id in by_id and by_id[req_id].fit != "UNKNOWN"
    ]
    unjudged = sorted(
        req_id for req_id in ids if req_id not in by_id or by_id[req_id].fit == "UNKNOWN"
    )
    base = round_half_up(sum(points) / len(points)) if points else None
    return FitCoverage(judged=len(points), total=len(ids)), base, unjudged


def compute_provisional(
    analysis: Analysis,
    stage_states: Mapping[Stage, StageState],
    requirement_ids: Sequence[str] | None,
    *,
    company: CompanyEvidenceView | None,
    now: date | datetime | None = None,
    resolve_gates: GateResolver | None = None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> Provisional | None:
    """PF-01 잠정 결론: public·estimate를 가정한 게이트로 결론과 그 결론을 바꾸는 조건을 만든다.

    demo(MVP 데모 임의값)는 confirmed와 같이 판정에 쓰고, 쓴 경로를 ``demo_fields``에 남긴다.
    ``portfolio_texts``는 저장 게이트와 같은 회사 지식 실적 텍스트다(설계 2.1).

    저장된 ``analysis.gates``는 바꾸지 않는다. ``resolve_gates``(사람 확인 적용)의 예외는
    그대로 올린다(resolver 없이 계산하지 않는다).
    """
    if company is None:
        return None
    view = company.with_accepted_levels(ASSUMED_LEVELS)
    as_of, _ = resolve_as_of(analysis.facts, _today(now))
    gates, assumed_lists = evaluate_gates_traced(
        analysis.facts,
        view.profile,
        as_of=as_of,
        evidence_view=view,
        portfolio_texts=portfolio_texts,
    )
    if resolve_gates is not None:
        gates = list(resolve_gates(gates))
    coverage, fit_base, unjudged = _provisional_fits(analysis.fits, requirement_ids)

    def level(path: str) -> str:
        return view.get(path)["effective_level"]

    def assumed_inputs(scope: Sequence[GateResult]) -> list[str]:
        return [
            path for gate in scope for path in gate.input_fields if level(path) in _ASSUMABLE_LEVELS
        ]

    def used_lists(scope: Sequence[GateResult]) -> list[str]:
        return [path for path in assumed_lists if any(path in gate.input_fields for gate in scope)]

    def demo_inputs(scope: Sequence[GateResult]) -> list[str]:
        # demo는 확인값과 같이 판정에 쓰므로 basis를 assumed로 만들지 않는다. 교체 대상 추적용.
        return [path for gate in scope for path in gate.input_fields if level(path) == "demo"]

    failures = [gate for gate in gates if gate.verdict == "FAIL"]
    min_contract = _trusted_min_contract(analysis, company, stage_states)
    decision: DecisionValue
    basis: ProvisionalBasis
    conditions: list[ProvisionalCondition]
    # 게이트 밖에서 결론을 정한 demo 입력(최소계약금액 미달 NO_GO일 때만).
    extra_demo: list[str] = []
    if failures or min_contract:
        recheck = [
            gate
            for gate in failures
            if not (
                _trusted_failure_basis(analysis, gate)
                and all(level(path) in DECISION_LEVELS for path in gate.input_fields)
            )
        ]
        conditions = [
            _gate_condition("recheck_fail", code, group, view)
            for code, group in _group_by_code(recheck)
        ]
        decision = "NO_GO"
        scope = failures
        basis = "assumed" if assumed_inputs(scope) or used_lists(scope) else "confirmed"
        if min_contract and level(_MIN_CONTRACT_PATH) == "demo":
            extra_demo.append(_MIN_CONTRACT_PATH)
    else:
        conditions = [
            *(
                _gate_condition("risk_gate", code, group, view)
                for code, group in _group_by_code([g for g in gates if g.verdict == "RISK"])
            ),
            *(
                _gate_condition("unknown_gate", code, group, view)
                for code, group in _group_by_code([g for g in gates if g.verdict == "UNKNOWN"])
            ),
        ]
        if not requirement_ids:
            conditions.append(
                ProvisionalCondition(
                    id="requirements_missing:requirements",
                    kind="requirements_missing",
                    title="요구사항 미분석",
                    check="과업 범위를 원문에서 직접 확인",
                    if_not="역량 적합도를 판단할 수 없음",
                    refs=[stage_ref("fits")],
                )
            )
        if coverage.total > 0 and coverage.judged < coverage.total * FIT_COVERAGE_MIN_RATIO:
            conditions.append(
                ProvisionalCondition(
                    id="fit_coverage:fits",
                    kind="fit_coverage",
                    title=(
                        f"요구사항 역량 판단 부족({coverage.total - coverage.judged}"
                        f"/{coverage.total}건)"
                    ),
                    check="회사 역량·실적 기록 보강",
                    if_not="보강 후 재분석하면 결론이 바뀔 수 있음",
                    refs=[fit_ref(req_id) for req_id in unjudged],
                )
            )
        if analysis.numeric_facts_unconfirmed:
            conditions.append(
                ProvisionalCondition(
                    id="pdf_numeric:pdf",
                    kind="pdf_numeric",
                    title="pdf 원문 숫자 미확정",
                    check="금액·기간을 hwp/hwpx 원문으로 확인",
                    if_not="금액·기간이 다르면 재검토",
                    refs=[stage_ref("facts")],
                )
            )
        stale = [stage for stage in ("facts", "fits") if stage_states.get(stage) != "current"]
        if stale:
            conditions.append(
                ProvisionalCondition(
                    id="stale_analysis:analysis",
                    kind="stale_analysis",
                    title="이전 기준 분석",
                    check="분석 다시 실행",
                    if_not="회사 기록 변경이 반영되지 않았을 수 있음",
                    refs=[stage_ref(stage) for stage in stale],  # type: ignore[arg-type]
                )
            )
        conditions.sort(key=lambda item: CONDITION_KIND_ORDER.index(item.kind))
        if conditions:
            decision = "CONDITIONAL_GO"
        elif fit_base is not None and fit_base >= GO_THRESHOLD:
            decision = "GO"
        elif fit_base is not None and fit_base >= CONDITIONAL_THRESHOLD:
            decision = "CONDITIONAL_GO"
        else:
            decision = "NO_GO"
        scope = gates
        basis = "assumed" if assumed_inputs(scope) or assumed_lists else "confirmed"
    return Provisional(
        decision=decision,
        basis=basis,
        conditions=conditions,
        fit_coverage=coverage,
        fit_base=fit_base,
        assumed_fields=sorted({*assumed_inputs(scope), *used_lists(scope)}),
        demo_fields=sorted({*demo_inputs(scope), *extra_demo}),
    )


def assess_analysis(
    analysis: Analysis,
    stage_states: Mapping[Stage, StageState],
    requirement_ids: Sequence[str] | None,
    *,
    company: CompanyEvidenceView | None = None,
    now: date | datetime | None = None,
    confirmation_outdated_refs: Sequence[str] = (),
    resolve_gates: GateResolver | None = None,
    skip_provisional: bool = False,
    portfolio_texts: Mapping[str, str] | None = None,
) -> tuple[Assessment, list[dict[str, Any]]]:
    """현재 입력으로 검증된 선행 상태에서 assessment와 안정 reasons를 계산한다.

    ``assessment.provisional``은 같은 입력으로 :func:`compute_provisional`이 채운다
    (state·decision·reason_codes 규칙과 무관). ``skip_provisional``이면 계산하지 않고 None이다
    (확인 파일을 읽지 못해 사람 확인 없이 만든 결론을 내지 않는다).
    """
    provisional = (
        None
        if skip_provisional
        else compute_provisional(
            analysis,
            stage_states,
            requirement_ids,
            company=company,
            now=now,
            resolve_gates=resolve_gates,
            portfolio_texts=portfolio_texts,
        )
    )
    reasons: list[dict[str, Any]] = []
    for stage in READINESS_STAGES:
        state = stage_states.get(stage, "missing")
        if state == "unknown":
            reasons.append(_reason("legacy_metadata", stage, [stage_ref(stage)]))
        elif state == "stale":
            reasons.append(_reason("stale_stage", stage, [stage_ref(stage)]))
        elif state == "missing":
            reasons.append(_reason("missing_stage", stage, [stage_ref(stage)]))

    mapping_reasons, mapping_complete = _fit_mapping_reasons(requirement_ids, analysis.fits)
    reasons.extend(mapping_reasons)
    if confirmation_outdated_refs:
        reasons.append(_reason("confirmation_outdated", "gates", confirmation_outdated_refs))

    for gate in analysis.gates:
        if gate.verdict != "UNKNOWN":
            continue
        ref = _gate_ref(gate)
        reasons.append(_reason("unknown_gate", "gates", [ref]))
        if company is not None:
            untrusted = [
                path
                for path in gate.input_fields
                if company.get(path)["effective_level"] not in DECISION_LEVELS
            ]
            if untrusted:
                reasons.append(
                    _reason(
                        "untrusted_company_input",
                        "gates",
                        [ref, *(field_ref(path) for path in untrusted)],
                    )
                )

    failures = [gate for gate in analysis.gates if gate.verdict == "FAIL"]
    trusted_failures = (
        _deterministic_failures(analysis, company, now, portfolio_texts)
        if stage_states.get("facts") == stage_states.get("gates") == "current"
        else []
    )
    trusted_ids = {id(item) for item in trusted_failures}
    for gate in failures:
        if id(gate) not in trusted_ids and not any(
            gate is item or gate == item for item in trusted_failures
        ):
            reasons.append(_reason("untrusted_failure", "gates", [_gate_ref(gate)]))
    for gate in trusted_failures:
        reasons.append(_reason("hard_gate_fail", "gates", [_gate_ref(gate)]))

    min_contract = _trusted_min_contract(analysis, company, stage_states)
    if min_contract:
        reasons.append(
            _reason(
                "min_contract_fail",
                "recommendation",
                [field_ref("policy.min_contract_amount_krw"), notice_ref("/project/budget_krw")],
            )
        )

    interval, decisions = _score_interval(analysis, stage_states, mapping_complete, company)
    if decisions is not None and decisions[0] != decisions[1]:
        reasons.append(
            _reason(
                "uncertain_fit_decision",
                "fits",
                [fit_ref(item.key) for item in analysis.fits if item.fit == "UNKNOWN"],
            )
        )

    ordered = canonical_reasons(reasons)
    reason_codes = [code for code in REASON_CODE_ORDER if any(r["code"] == code for r in ordered)]
    if trusted_failures or min_contract:
        return (
            Assessment(
                state="ready",
                decision="NO_GO",
                reason_codes=reason_codes,
                score_interval=None,
                provisional=provisional,
            ),
            ordered,
        )

    blockers = {
        "legacy_metadata",
        "stale_stage",
        "missing_stage",
        "empty_requirements",
        "missing_fits",
        "unknown_gate",
        "untrusted_failure",
        "uncertain_fit_decision",
    }
    stable_decision = (
        decisions[0] if decisions is not None and decisions[0] == decisions[1] else None
    )
    abstain = stable_decision is None or any(reason["code"] in blockers for reason in ordered)
    return (
        Assessment(
            state="abstain" if abstain else "ready",
            decision=None if abstain else stable_decision,
            reason_codes=reason_codes,
            score_interval=interval,
            provisional=provisional,
        ),
        ordered,
    )


def finalize_readiness(
    analysis: Analysis,
    stage_states: Mapping[Stage, StageState],
    requirement_ids: Sequence[str] | None,
    *,
    company: CompanyEvidenceView,
    computed_at: str,
    now: date | datetime | None = None,
    confirmation_outdated_refs: Sequence[str] = (),
    preparation_facts_artifact: Literal["facts.json", "analysis.json"] | None = None,
    preserved_requests: Sequence[DataToConfirm] | None = None,
    checklist_source: Literal["llm", "legacy"] = "llm",
    resolve_gates: GateResolver | None = None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> tuple[Analysis, list[dict[str, Any]]]:
    """Attach assessment, optional REV-04 actions, then the two consumer-stage stamps.

    With ``preparation_facts_artifact`` the REV-04 raw list, active list and review_actions are
    rebuilt.  analyze passes nothing else: raw rows come from the validated ``synth_output``.
    regate passes ``preserved_requests`` (the stored llm/legacy rows it carries over) and the
    stored ``checklist_source``; then code rows are regenerated and a missing synth is allowed.
    """
    assessment, reasons = assess_analysis(
        analysis,
        stage_states,
        requirement_ids,
        company=company,
        now=now,
        confirmation_outdated_refs=confirmation_outdated_refs,
        resolve_gates=resolve_gates,
        portfolio_texts=portfolio_texts,
    )
    updated = analysis.model_copy(update={"assessment": assessment}, deep=True)
    if preparation_facts_artifact is not None and (
        preserved_requests is not None or updated.synth_output is not None
    ):
        # Local import avoids making the pure actions module part of review's import cycle.
        from bid_deep_engine.analysis.actions import (
            build_confirmation_projection,
            build_preparation_projection,
            build_raw_confirmation_data,
            rebuild_raw_confirmation_data,
        )

        if preserved_requests is not None:
            raw = rebuild_raw_confirmation_data(
                updated.gates,
                updated.scores,
                preserved_requests,
                reasons,
                numeric_facts_unconfirmed=updated.numeric_facts_unconfirmed,
            )
        else:
            assert updated.synth_output is not None
            raw = build_raw_confirmation_data(
                updated.gates,
                updated.scores,
                updated.synth_output,
                reasons,
                numeric_facts_unconfirmed=updated.numeric_facts_unconfirmed,
            )
        preparations = build_preparation_projection(
            updated.facts,
            updated.checklist,
            facts_artifact=preparation_facts_artifact,
            checklist_source=checklist_source,
        )
        as_of, _ = resolve_as_of(updated.facts, _today(now))
        projection = build_confirmation_projection(
            facts=updated.facts,
            gates=updated.gates,
            scores=updated.scores,
            raw_data_to_confirm=raw,
            company=company,
            assessment=assessment,
            reasons=reasons,
            as_of=as_of,
            stage_states=stage_states,
            preparations=preparations.preparations,
            raw_preparations=preparations.raw_preparations,
            numeric_facts_unconfirmed=updated.numeric_facts_unconfirmed,
        )
        updated = updated.model_copy(
            update={
                "data_to_confirm": projection.data_to_confirm,
                "raw_data_to_confirm": raw,
                "review_actions": projection.review_actions,
            },
            deep=True,
        )
    stages = dict(updated.stages)
    stages.pop("requests", None)
    stages.pop("recommendation", None)
    outputs = {
        stage: analysis_stage_output(updated, stage)
        for stage in ("facts", "gates", "scores", "fits", "synth")
    }
    if any(output is None for output in outputs.values()):
        return updated.model_copy(update={"stages": stages}), reasons
    ready_hash = readiness_hash(assessment, reasons, stage_states)
    hashes = {stage: stage_output_hash(stage, output) for stage, output in outputs.items()}
    common = {**hashes, "company": company.company_input_hash}
    stages["requests"] = make_stage_stamp(
        "requests",
        inputs={**common, "readiness": ready_hash},
        output=analysis_stage_output(updated, "requests"),
        parameters=code_parameters(),
        computed_at=computed_at,
    )
    stages["recommendation"] = make_stage_stamp(
        "recommendation",
        inputs={
            **common,
            "readiness_rules": readiness_rules_hash(),
            "readiness": ready_hash,
        },
        output=analysis_stage_output(updated, "recommendation"),
        parameters=code_parameters(),
        computed_at=computed_at,
    )
    return updated.model_copy(update={"stages": stages}), reasons


def resolve_stage_states(
    artifact_dir: Path,
    analysis: Analysis,
    company: CompanyEvidenceView | None,
    *,
    source_dir: Path | None = None,
    document: RfpDocument | None = None,
    now: date | datetime | None = None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> dict[Stage, StageState]:
    """producer/regate가 쓸 현재 source 검증. 현재 파일로 누락 stamp를 만들지는 않는다.

    ``portfolio_texts``는 producer가 게이트에 쓴 회사 지식 실적 텍스트다(gates 입력 대조용).
    """
    source_dir = artifact_dir if source_dir is None else source_dir
    facts_doc, fits_doc = _load_artifacts(artifact_dir)
    if document is None:
        raw_rfp = _load_json(source_dir / "rfp.json")
        if raw_rfp is not None:
            try:
                document = RfpDocument.model_validate(raw_rfp)
            except ValidationError:
                pass
    states, _ = _read_stage_states(
        artifact_dir,
        source_dir,
        analysis,
        company,
        document,
        facts_doc,
        fits_doc,
        now=now,
        portfolio_texts=portfolio_texts,
    )
    return states


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _load_analysis(raw: dict[str, Any] | None) -> Analysis | None:
    if raw is None:
        return None
    try:
        return Analysis.model_validate(raw)
    except ValidationError:
        # 한 legacy/손상 stamp가 의미 출력 전체를 missing으로 바꾸지 않게 유효 stamp만 복원한다.
        without_stages = dict(raw)
        raw_stages = without_stages.get("stages")
        without_stages["stages"] = {}
        # REV-04 선택 확장 필드가 손상되면 그 필드만 없는 것으로 읽는다(원파일은 그대로).
        # requests 출력이 stamp와 달라져 current로 읽히지 않고, 원목록 표시는
        # actions.project_legacy_actions가 경고와 함께 맡는다.
        for key, model in (
            ("raw_data_to_confirm", _REQUEST_ROWS),
            ("review_actions", _REVIEW_ACTIONS),
        ):
            if without_stages.get(key) is None:
                continue
            try:
                model.validate_python(without_stages[key])
            except ValidationError:
                without_stages[key] = None
        try:
            analysis = Analysis.model_validate(without_stages)
        except ValidationError:
            return None
        if not isinstance(raw_stages, dict):
            return analysis
        stages: dict[Stage, StageStamp] = {}
        for stage in STAGE_ORDER:
            candidate = raw_stages.get(stage)
            if candidate is None:
                continue
            try:
                stages[stage] = StageStamp.model_validate(candidate)
            except ValidationError:
                continue
        return analysis.model_copy(update={"stages": stages})


def _load_artifacts(slug_dir: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    return _load_json(slug_dir / "facts.json"), _load_json(slug_dir / "fits.json")


def _knowledge_hash_for(
    stamp: StageStamp, document: RfpDocument, company: CompanyEvidenceView | None
) -> str | None:
    params = stamp.parameters
    if params.knowledge_root is None:
        return knowledge_input_hash(None, None)
    try:
        knowledge = load_knowledge(
            params.knowledge_root, profile=None if company is None else company.profile
        )
        override = (
            params.knowledge_categories if params.knowledge_category_source == "manual" else None
        )
        selection, _ = prepare_knowledge(document, knowledge, override=override)
    except (OSError, ValueError, KnowledgeError):
        return None
    return knowledge_input_hash(knowledge, selection)


def _current_rfp_hash(source_dir: Path, document: RfpDocument | None) -> str | None:
    if document is None:
        return None
    try:
        return rfp_input_hash(source_dir / "rfp.json", document)
    except (OSError, ValueError, ValidationError):
        return None


def _confirmation_inputs(
    artifact_dir: Path, source_dir: Path, document: RfpDocument | None
) -> tuple[list[GateConfirmation], str | None]:
    """현재 확인 목록과 rfp_hash. 파일 손상은 `GateConfirmationError`."""
    doc = load_confirmations(artifact_dir / "gate_confirmations.yaml")
    return ([] if doc is None else list(doc.confirmations)), _current_rfp_hash(source_dir, document)


def _resolve_current(
    facts: RfpFacts,
    company: CompanyEvidenceView,
    confirmations: Sequence[GateConfirmation],
    rfp_hash: str | None,
    now: date | datetime | None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> ConfirmationResolution:
    as_of, _ = resolve_as_of(facts, _today(now))
    fresh = evaluate_gates(facts, company, as_of=as_of, portfolio_texts=portfolio_texts)
    return resolve_confirmations(fresh, confirmations, rfp_hash=rfp_hash)


def _confirmation_resolution(
    artifact_dir: Path,
    source_dir: Path,
    facts: RfpFacts,
    company: CompanyEvidenceView,
    document: RfpDocument | None,
    now: date | datetime | None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> ConfirmationResolution:
    """disk/producer가 공유하는 current confirmation 판정. 파일 손상은 호출자가 unknown 처리."""
    confirmations, rfp_hash = _confirmation_inputs(artifact_dir, source_dir, document)
    return _resolve_current(facts, company, confirmations, rfp_hash, now, portfolio_texts)


def _outdated_refs(resolution: ConfirmationResolution) -> list[str]:
    return sorted(
        dict.fromkeys(gate_ref(code, rule_hash) for code, rule_hash in resolution.outdated)
    )


def _staffing_location_conflicted(facts: RfpFacts, index: int) -> bool:
    """해당 staffing 행의 resident/location 추출 충돌 여부."""
    row_paths = (f"staffing[{index}]", f"staffing.{index}")
    for conflict in facts.conflicts:
        field = conflict.field
        if field in ("staffing", "staffing[]", *row_paths):
            return True
        if any(field in (f"{row}.resident", f"{row}.location") for row in row_paths):
            return True
    return False


def policy_conflicts(facts: RfpFacts, company: CompanyEvidenceView | None) -> list[PolicyConflict]:
    """확인된 서울 직원상주 불가 방침만 별도 표시한다. 서버 on-premise는 보지 않는다."""
    if company is None:
        return []
    policy = company.get("policy.seoul_resident_ok")
    if policy["effective_level"] not in DECISION_LEVELS or policy["value"] is not False:
        return []
    requirements = []
    for index, item in enumerate(facts.staffing):
        evidence = item.evidence
        if (
            item.resident is True
            and onsite_region_key(item.location) == "서울"
            and evidence.verified is True
            and bool(evidence.quote.strip())
            and not _staffing_location_conflicted(facts, index)
        ):
            requirements.append(item)
    if not requirements:
        return []
    evidence = []
    seen: set[tuple[object, ...]] = set()
    for item in requirements:
        value = item.evidence.model_dump(mode="json")
        key = (
            value["quote"],
            value["section_id"],
            value["page"],
            value["verified"],
            value["repaired"],
        )
        if key not in seen:
            seen.add(key)
            evidence.append(item.evidence.model_copy(deep=True))
    return [
        PolicyConflict(
            code="seoul_onsite",
            company_fields=["policy.seoul_resident_ok"],
            evidence=evidence,
            message="서울 직원 상주 요구가 확인된 회사 방침과 충돌합니다.",
        )
    ]


def _expected_inputs(
    stage: Stage,
    stamp: StageStamp,
    *,
    artifact_dir: Path,
    source_dir: Path,
    document: RfpDocument | None,
    analysis: Analysis | None,
    outputs: Mapping[Stage, Any | None],
    company: CompanyEvidenceView | None,
    readiness: str | None,
    now: date | datetime | None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> dict[str, str] | None:
    params = stamp.parameters
    upstream = {
        name: stage_output_hash(name, outputs[name])
        for name in READINESS_STAGES
        if outputs.get(name) is not None
    }
    try:
        if stage == "facts":
            if (
                document is None
                or params.model is None
                or params.strategy is None
                or params.effort is None
            ):
                return None
            return {
                "rfp": rfp_input_hash(source_dir / "rfp.json", document),
                "prompts": prompt_set_hash("facts", params.strategy),
                "model_settings": model_settings_hash(
                    model=params.model,
                    strategy=params.strategy,
                    effort=params.effort,
                    model_fingerprint=params.model_fingerprint,
                ),
            }
        if company is None or analysis is None or "facts" not in upstream:
            return None
        as_of, _ = resolve_as_of(analysis.facts, _today(now))
        if stage == "gates":
            try:
                confirmation = _confirmation_resolution(
                    artifact_dir,
                    source_dir,
                    analysis.facts,
                    company,
                    document,
                    now,
                    portfolio_texts,
                )
            except GateConfirmationError:
                return None
            return {
                "facts": upstream["facts"],
                "company": company.company_input_hash,
                "confirmations": confirmations_hash(confirmation.applicable),
                "as_of": as_of_hash(as_of),
                "portfolio_knowledge": portfolio_knowledge_hash(portfolio_texts),
            }
        if stage == "scores":
            return {
                "facts": upstream["facts"],
                "company": company.company_input_hash,
                "as_of": as_of_hash(as_of),
            }
        if document is None:
            return None
        if stage in ("fits", "synth"):
            if params.model is None or params.strategy is None or params.effort is None:
                return None
            knowledge = _knowledge_hash_for(stamp, document, company)
            if knowledge is None:
                return None
            prompt_stage = "fits" if stage == "fits" else "synth"
            result = {
                "facts": upstream["facts"],
                "company": company.company_input_hash,
                "knowledge": knowledge,
                "prompts": prompt_set_hash(prompt_stage, params.strategy),
                "model_settings": model_settings_hash(
                    model=params.model,
                    strategy=params.strategy,
                    effort=params.effort,
                    model_fingerprint=params.model_fingerprint,
                ),
            }
            if stage == "fits":
                result["requirements"] = requirements_hash(document)
            else:
                if any(name not in upstream for name in ("gates", "scores", "fits")):
                    return None
                result.update({name: upstream[name] for name in ("gates", "scores", "fits")})
            return result
        if readiness is None or any(name not in upstream for name in READINESS_STAGES):
            return None
        common = {name: upstream[name] for name in READINESS_STAGES}
        common["company"] = company.company_input_hash
        if stage == "requests":
            return {**common, "readiness": readiness}
        return {
            **common,
            "readiness_rules": readiness_rules_hash(),
            "readiness": readiness,
        }
    except (OSError, ValueError, ValidationError):
        return None


def _parameters_match_stage(stage: Stage, stamp: StageStamp) -> bool:
    if stage in ("gates", "scores", "requests", "recommendation"):
        return stamp.parameters == code_parameters()
    params = stamp.parameters
    if params.model is None or params.strategy is None or params.effort is None:
        return False
    if stage == "facts":
        return params == params.model_copy(
            update={
                "knowledge_root": None,
                "knowledge_categories": [],
                "knowledge_category_source": "none",
            }
        )
    return True


def _read_stage_states(
    artifact_dir: Path,
    source_dir: Path,
    analysis: Analysis | None,
    company: CompanyEvidenceView | None,
    document: RfpDocument | None,
    facts_doc: dict[str, Any] | None,
    fits_doc: dict[str, Any] | None,
    *,
    now: date | datetime | None,
    portfolio_texts: Mapping[str, str] | None = None,
) -> tuple[dict[Stage, StageState], dict[Stage, Any | None]]:
    outputs: dict[Stage, Any | None] = {stage: None for stage in STAGE_ORDER}
    if analysis is not None:
        outputs.update({stage: analysis_stage_output(analysis, stage) for stage in STAGE_ORDER})
    duplicate_mismatch: set[Stage] = set()
    artifact_stamps: dict[Stage, StageStamp] = {}
    for stage, doc, key in (("facts", facts_doc, "facts"), ("fits", fits_doc, "fits")):
        if doc is None or key not in doc:
            continue
        try:
            artifact_output = (
                RfpFacts.model_validate(doc[key]).model_dump(mode="json")
                if stage == "facts"
                else [
                    RequirementFit.model_validate(item).model_dump(mode="json") for item in doc[key]
                ]
            )
        except (TypeError, ValidationError):
            duplicate_mismatch.add(stage)
            continue
        if outputs[stage] is None:
            outputs[stage] = artifact_output
        elif stage_output_hash(stage, outputs[stage]) != stage_output_hash(stage, artifact_output):
            duplicate_mismatch.add(stage)
        meta = doc.get("meta")
        if isinstance(meta, dict):
            found = artifact_stage_stamp(stage, meta)  # type: ignore[arg-type]
            if found is not None:
                artifact_stamps[stage] = found

    states: dict[Stage, StageState] = {}
    for stage in READINESS_STAGES:
        output = outputs[stage]
        if output is None:
            states[stage] = "missing"
            continue
        if stage in duplicate_mismatch:
            states[stage] = "stale"
            continue
        stamp = analysis.stages.get(stage) if analysis is not None else None
        if stage in ("facts", "fits"):
            artifact = artifact_stamps.get(stage)
            if stamp is None:
                stamp = artifact
            elif artifact is None or artifact != stamp:
                states[stage] = "unknown" if artifact is None else "stale"
                continue
        if stamp is None:
            states[stage] = "unknown"
            continue
        if not _parameters_match_stage(stage, stamp):
            states[stage] = "stale"
            continue
        expected = _expected_inputs(
            stage,
            stamp,
            artifact_dir=artifact_dir,
            source_dir=source_dir,
            document=document,
            analysis=analysis,
            outputs=outputs,
            company=company,
            readiness=None,
            now=now,
            portfolio_texts=portfolio_texts,
        )
        if expected is None:
            states[stage] = "unknown"
        else:
            states[stage] = (
                "current"
                if stage_stamp_matches(stage, stamp, inputs=expected, output=output)
                else "stale"
            )
    states["requests"] = "missing" if outputs["requests"] is None else "unknown"
    states["recommendation"] = "missing" if outputs["recommendation"] is None else "unknown"
    return states, outputs


def _last_attempt(slug_dir: Path) -> dict[str, Any] | None:
    state = _load_json(slug_dir / "run_state.json")
    if state is not None:
        try:
            return RunState.model_validate(state).last_attempt.model_dump(mode="json")
        except ValidationError:
            pass
    usage = _load_json(slug_dir / "usage.json")
    error = None if usage is None else usage.get("error")
    if isinstance(error, str) and error:
        return {"phase": None, "at": None, "outcome": "failed", "error": error}
    return None


def build_review(
    slug_dir: Path, company_path: Path | str | None = None, now: date | datetime | None = None
) -> dict[str, Any]:
    """현재 파일을 검증해 공통 읽기 모델을 만든다. 어떠한 파일도 갱신하지 않는다."""
    raw_analysis = _load_json(slug_dir / "analysis.json")
    analysis = _load_analysis(raw_analysis)
    facts_doc, fits_doc = _load_artifacts(slug_dir)
    document: RfpDocument | None = None
    raw_rfp = _load_json(slug_dir / "rfp.json")
    if raw_rfp is not None:
        try:
            document = RfpDocument.model_validate(raw_rfp)
        except ValidationError:
            document = None
    company: CompanyEvidenceView | None = None
    portfolio_texts: dict[str, str] = {}
    if company_path is not None:
        try:
            company = load_evidence_view(company_path)
        except ProfileError:
            company = None
    if company is not None and company_path is not None:
        # 게이트와 같은 지식 루트(회사 프로필 폴더의 knowledge/). 트리가 깨졌으면 지식 없이
        # 계산한다 — 지식으로 만든 gates stamp와 입력이 달라 stale로 드러난다.
        try:
            portfolio_texts = load_portfolio_texts(
                gate_knowledge_root(company_path), profile=company.profile
            )
        except (OSError, KnowledgeError):
            portfolio_texts = {}

    states, outputs = _read_stage_states(
        slug_dir,
        slug_dir,
        analysis,
        company,
        document,
        facts_doc,
        fits_doc,
        now=now,
        portfolio_texts=portfolio_texts,
    )
    if analysis is None:
        reasons = []
        for stage in READINESS_STAGES:
            state = states[stage]
            if state == "unknown":
                reasons.append(_reason("legacy_metadata", stage, [stage_ref(stage)]))
            elif state == "stale":
                reasons.append(_reason("stale_stage", stage, [stage_ref(stage)]))
            elif state == "missing":
                reasons.append(_reason("missing_stage", stage, [stage_ref(stage)]))
        reasons = canonical_reasons(reasons)
        assessment = Assessment(
            state="abstain",
            decision=None,
            reason_codes=[
                code for code in REASON_CODE_ORDER if any(item["code"] == code for item in reasons)
            ],
            score_interval=None,
        )
    else:
        requirement_ids = None if document is None else [item.key for item in document.requirements]
        outdated: list[str] = []
        resolver: GateResolver | None = None
        skip_provisional = False
        if company is not None:
            try:
                confirmations, rfp_hash = _confirmation_inputs(slug_dir, slug_dir, document)
                outdated = _outdated_refs(
                    _resolve_current(
                        analysis.facts, company, confirmations, rfp_hash, now, portfolio_texts
                    )
                )
                resolver = make_gate_resolver(confirmations, rfp_hash)
            except GateConfirmationError:
                # 확인 기록 없이 만든 잠정 결론은 사람 확인이 빠진 결론이라 내지 않는다.
                skip_provisional = True
        assessment, reasons = assess_analysis(
            analysis,
            states,
            requirement_ids,
            company=company,
            now=now,
            confirmation_outdated_refs=outdated,
            resolve_gates=resolver,
            skip_provisional=skip_provisional,
            portfolio_texts=portfolio_texts,
        )
        ready = readiness_hash(assessment, reasons, states)
        for stage in ("requests", "recommendation"):
            output = outputs[stage]
            stamp = analysis.stages.get(stage)
            if output is None:
                states[stage] = "missing"
                continue
            if stamp is None:
                states[stage] = "unknown"
                continue
            if not _parameters_match_stage(stage, stamp):
                states[stage] = "stale"
                continue
            expected = _expected_inputs(
                stage,
                stamp,
                artifact_dir=slug_dir,
                source_dir=slug_dir,
                document=document,
                analysis=analysis,
                outputs=outputs,
                company=company,
                readiness=ready,
                now=now,
                portfolio_texts=portfolio_texts,
            )
            states[stage] = (
                "unknown"
                if expected is None
                else "current"
                if stage_stamp_matches(stage, stamp, inputs=expected, output=output)
                else "stale"
            )

    recommendation_stamp = None if analysis is None else analysis.stages.get("recommendation")
    return {
        "slug": slug_dir.name if analysis is None else analysis.slug,
        "assessment": assessment,
        "stage_states": states,
        "reasons": canonical_reasons(reasons),
        "last_success_at": (
            None if recommendation_stamp is None else recommendation_stamp.computed_at
        ),
        "last_attempt": _last_attempt(slug_dir),
        "policy_conflicts": policy_conflicts(
            RfpFacts() if analysis is None else analysis.facts,
            company if states["facts"] == "current" else None,
        ),
        "legacy_recommendation": None if analysis is None else analysis.recommendation,
    }
