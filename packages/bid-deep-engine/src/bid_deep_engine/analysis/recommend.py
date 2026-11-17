"""권고 공식(spec M2-04 "권고"). 점수·결정은 코드로만 계산한다(사용자 결정 7, 제약 3).

`recommend(facts, gates, fits, synth, profile, scores)` → `(Recommendation, data_to_confirm)`.
LLM(SynthOut)은 요약·전제조건·이유 서술만 낸다. 프로필 정책값 "unknown"은 가정값으로 채우지
않고 결정 가드(최대 CONDITIONAL_GO)와 전제조건 "정책값 확인: policy.<키>"로 노출한다(사용자 결정 2,
제약 2).

1. 점수: fit ≠ UNKNOWN인 적합도의 `WEIGHTS[fit]` 평균(없으면 `EMPTY_BASE`)에 게이트 감점
   (`WEIGHTS["RISK"]`×RISK 수 + `WEIGHTS["UNKNOWN"]`×UNKNOWN 수; UNKNOWN은 0이라 감점 없음)을
   더해 half-up 반올림 후 0~100 clamp.
2. 결정(위에서 먼저 맞는 것): gate_fail → min_contract_amount → guarded → score.
   `numeric_facts_unconfirmed`(rfp primary pdf, 제약 4)면 min_contract_amount를 적용하지 않고
   guarded로 간다(최대 CONDITIONAL_GO). gate_fail은 그대로.
3. preconditions·why_not은 NFC·공백 축소 후 같은 문자열을 첫 항목만 남긴다. data_to_confirm은
   field/why/origin 전체가 같은 원항목만 중복 제거한다. 코드가 만드는 항목은 `code_preconditions`·
   `code_why_not`·`code_data_to_confirm`이 만든다(재계산이 이전 산출물에서 LLM 서술만 골라낼
   때 같은 함수를 쓴다, GT-01 X81).

`WEIGHTS`·임계값은 tunable이며 호출 시점의 모듈 값을 읽는다.
"""

import math
import unicodedata
from collections.abc import Iterable, Sequence

from bid_deep_engine.analysis.schemas import (
    DataToConfirm,
    GateResult,
    Recommendation,
    RequirementFit,
    RfpFacts,
    ScoreEstimate,
    SynthOut,
)
from bid_deep_engine.company.provenance import CompanyEvidenceView
from bid_deep_engine.company.schema import UNKNOWN, CompanyProfile

CompanyInput = CompanyProfile | CompanyEvidenceView

WEIGHTS: dict[str, int] = {
    "FULL": 100,
    "PARTIAL": 50,
    "GAP": 0,
    "RISK": -10,
    "UNKNOWN": 0,  # 게이트 UNKNOWN은 감점하지 않는다(PF-01: 미확인은 점수가 아니라 조건으로 노출)
    "EMPTY_BASE": 50,
}  # tunable(사용자 결정 7)
GO_THRESHOLD = 70  # tunable, 0~100
CONDITIONAL_THRESHOLD = 40  # tunable, 0~GO_THRESHOLD
POLICY_KEYS: tuple[str, ...] = (
    "min_contract_amount_krw",
    "target_gross_margin_pct",
    "seoul_resident_ok",
    "max_concurrent_new_projects",
    "no_bid_if",
    "preferred_domains",
)  # M1-01 policy 키(계약 시트 2절 순서)

# 제약 4(pdf 단독 숫자 사실 확정 금지): rfp primary_format이 pdf일 때 코드가 더하는 항목
PDF_PRECONDITION = "확인: pdf 원문 — 금액·기간 등 숫자 사실을 hwp/hwpx 원문으로 확인"
PDF_DATA_TO_CONFIRM_FIELD = "rfp.primary_format"
PDF_DATA_TO_CONFIRM_WHY = "pdf 원문 — 숫자 사실 미확정"

FIT_VALUES = ("FULL", "PARTIAL", "GAP", "UNKNOWN")
VERDICT_VALUES = ("PASS", "FAIL", "UNKNOWN", "RISK")


def round_half_up(x: float) -> int:
    """`floor(x + 0.5)`. Python `round`의 은행가 반올림(62.5 → 62)을 쓰지 않는다."""
    return math.floor(x + 0.5)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def fit_score_for(
    gates: Sequence[GateResult],
    fits: Sequence[RequirementFit],
    *,
    unknown_fit: int | None = None,
) -> tuple[int, dict[str, int], dict[str, int], float, str, float, float]:
    """기존 권고 점수 공식을 한 곳에서 계산한다.

    ``unknown_fit``은 readiness 진단에서만 쓰는 UNKNOWN 적합도 치환값(0 또는 100)이다.
    생략하면 기존 계약처럼 UNKNOWN을 평균 분모에서 제외하고, 알려진 fit이 하나도 없으면
    ``EMPTY_BASE``를 쓴다. 반환값은 score와 score_breakdown에 필요한 중간값이다.
    """
    if unknown_fit not in (None, 0, 100):
        raise ValueError("unknown_fit must be null, 0, or 100")
    weights = dict(WEIGHTS)
    fit_counts = {v: 0 for v in FIT_VALUES}
    for fit in fits:
        fit_counts[fit.fit] += 1
    gate_counts = {v: 0 for v in VERDICT_VALUES}
    for gate in gates:
        gate_counts[gate.verdict] += 1

    if unknown_fit is None:
        values = [weights[fit.fit] for fit in fits if fit.fit != "UNKNOWN"]
    else:
        values = [unknown_fit if fit.fit == "UNKNOWN" else weights[fit.fit] for fit in fits]
    if values:
        base = float(sum(values) / len(values))
        base_source = "fits"
    else:
        base = float(weights["EMPTY_BASE"])
        base_source = "empty"
    penalty = float(
        weights["RISK"] * gate_counts["RISK"] + weights["UNKNOWN"] * gate_counts["UNKNOWN"]
    )
    raw = base + penalty
    score = min(100, max(0, round_half_up(raw)))
    return score, fit_counts, gate_counts, base, base_source, penalty, raw


def decision_for_score(
    fit_score: int,
    *,
    gate_counts: dict[str, int],
    below_min: bool,
    guarded: bool,
) -> tuple[str, str]:
    """기존 결정 우선순위와 임계값을 적용한다.

    readiness 양끝 비교도 이 함수를 사용해 guarded 40 및 score 40/70 경계를 권고와
    공유한다. 튜닝 상수는 호출 시점 값을 읽는다.
    """
    if gate_counts["FAIL"] > 0:
        return "gate_fail", "NO_GO"
    if below_min:
        return "min_contract_amount", "NO_GO"
    if guarded:
        return (
            "guarded",
            "CONDITIONAL_GO" if fit_score >= CONDITIONAL_THRESHOLD else "NO_GO",
        )
    if fit_score >= GO_THRESHOLD:
        return "score", "GO"
    if fit_score >= CONDITIONAL_THRESHOLD:
        return "score", "CONDITIONAL_GO"
    return "score", "NO_GO"


def _norm_text(text: str) -> str:
    """중복 비교 키: NFC 정규화 후 연속 공백을 한 칸으로 줄이고 앞뒤 공백 제거."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _dedup_texts(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = _norm_text(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _as_evidence_view(
    company: CompanyInput, evidence_view: CompanyEvidenceView | None = None
) -> CompanyEvidenceView:
    if isinstance(company, CompanyEvidenceView):
        if evidence_view is not None and evidence_view is not company:
            raise ValueError("company and evidence_view refer to different evidence views")
        return company
    if evidence_view is not None:
        if evidence_view.profile is not company:
            raise ValueError("evidence_view.profile must be the supplied CompanyProfile")
        return evidence_view
    return CompanyEvidenceView(company)


def policy_unknown_keys(
    profile: CompanyInput, *, evidence_view: CompanyEvidenceView | None = None
) -> list[str]:
    """`POLICY_KEYS` 중 프로필 값이 "unknown"인 키(순서 유지)."""
    view = _as_evidence_view(profile, evidence_view)
    return [key for key in POLICY_KEYS if view.decision_value(f"policy.{key}") == UNKNOWN]


def decision_factors(
    facts: RfpFacts,
    gates: Sequence[GateResult],
    profile: CompanyInput,
    *,
    numeric_facts_unconfirmed: bool,
    evidence_view: CompanyEvidenceView | None = None,
) -> tuple[dict[str, int], list[str], object, bool, bool]:
    """기존 결정 분기의 gate/정책/PDF guard를 현재 입력에서 계산한다."""
    view = _as_evidence_view(profile, evidence_view)
    gate_counts = {value: 0 for value in VERDICT_VALUES}
    for gate in gates:
        gate_counts[gate.verdict] += 1
    policy_unknown = policy_unknown_keys(view)
    budget = facts.project.budget_krw
    min_amount = view.decision_value("policy.min_contract_amount_krw")
    below_min = bool(
        not numeric_facts_unconfirmed
        and _is_int(budget)
        and _is_int(min_amount)
        and budget < min_amount  # type: ignore[operator]
    )
    guarded = bool(
        gate_counts["UNKNOWN"] or gate_counts["RISK"] or policy_unknown or numeric_facts_unconfirmed
    )
    return gate_counts, policy_unknown, min_amount, below_min, guarded


def code_preconditions(
    gates: Sequence[GateResult],
    policy_unknown: Sequence[str],
    *,
    numeric_facts_unconfirmed: bool,
) -> list[str]:
    """코드가 만드는 전제조건(순서 고정): UNKNOWN·RISK 게이트 → 정책 unknown 키 → pdf 문구.

    `recommend`와 재계산(regate)의 LLM 서술 분리가 같은 함수를 쓴다(X81).
    """
    items = [
        f"확인: {g.rule_text} ({g.code} {g.verdict})"
        for g in gates
        if g.verdict in ("UNKNOWN", "RISK")
    ]
    items += [f"정책값 확인: policy.{key}" for key in policy_unknown]
    if numeric_facts_unconfirmed:
        items.append(PDF_PRECONDITION)
    return items


def code_why_not(
    gates: Sequence[GateResult],
    *,
    min_applied: bool,
    budget: int | None,
    min_amount: object,
) -> list[str]:
    """코드가 만드는 불가 이유(순서 고정): FAIL 게이트 → (min_applied면) 최소 계약금액 미달.

    `min_applied`가 참이면 `budget`·`min_amount`는 정수다(결정 규칙 min_contract_amount의 조건).
    """
    items = [f"참가자격 미충족: {g.rule_text} ({g.code})" for g in gates if g.verdict == "FAIL"]
    if min_applied:
        items.append(
            f"최소 계약금액 미달: 사업금액 {budget:,}원 < "
            f"policy.min_contract_amount_krw {min_amount:,}원"
        )
    return items


def code_data_to_confirm(
    gates: Sequence[GateResult],
    scores: Sequence[ScoreEstimate],
    *,
    numeric_facts_unconfirmed: bool,
) -> list[DataToConfirm]:
    """코드가 만드는 확인 필요 항목(중복 제거 전, 순서 고정): 게이트 unknown_fields → 점수
    unknown_inputs → pdf."""
    items: list[DataToConfirm] = []
    for g in gates:
        items.extend(
            DataToConfirm(field=f, why=f"게이트 {g.code} 판정에 필요", origin="code")
            for f in g.unknown_fields
        )
    for s in scores:
        items.extend(
            DataToConfirm(field=f, why=f"정량점수 '{s.item}' 추정에 필요", origin="code")
            for f in s.unknown_inputs
        )
    if numeric_facts_unconfirmed:
        items.append(
            DataToConfirm(
                field=PDF_DATA_TO_CONFIRM_FIELD, why=PDF_DATA_TO_CONFIRM_WHY, origin="code"
            )
        )
    return items


def raw_data_to_confirm(
    gates: Sequence[GateResult],
    scores: Sequence[ScoreEstimate],
    synth: SynthOut,
    *,
    numeric_facts_unconfirmed: bool,
) -> list[DataToConfirm]:
    """Preserve distinct code and LLM causes; remove only byte-equivalent semantic rows."""
    candidates = code_data_to_confirm(
        gates, scores, numeric_facts_unconfirmed=numeric_facts_unconfirmed
    )
    candidates.extend(
        d.model_copy(update={"origin": "llm"}, deep=True) for d in synth.data_to_confirm
    )
    seen: set[tuple[str, str, str]] = set()
    out: list[DataToConfirm] = []
    for d in candidates:
        key = (d.field, d.why, d.origin)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _basis(
    gates: Sequence[GateResult], fits: Sequence[RequirementFit], synth: SynthOut
) -> list[str]:
    """권고 근거 참조(제약 1). 인용(Evidence)이 하나도 없는 대상은 넣지 않는다."""
    refs = [f"gate:{g.code}#{i}" for i, g in enumerate(gates) if g.verdict != "PASS" and g.evidence]
    refs += [
        f"fit:{f.req_id}" for f in fits if f.fit in ("GAP", "PARTIAL") and f.evidence is not None
    ]
    refs += [
        f"risk:{i}"
        for i, r in enumerate(synth.risks)
        if r.severity == "H" and r.evidence is not None
    ]
    return refs


def recommend(
    facts: RfpFacts,
    gates: Sequence[GateResult],
    fits: Sequence[RequirementFit],
    synth: SynthOut,
    profile: CompanyInput,
    scores: Sequence[ScoreEstimate],
    *,
    numeric_facts_unconfirmed: bool = False,
    evidence_view: CompanyEvidenceView | None = None,
) -> tuple[Recommendation, list[DataToConfirm]]:
    """권고와 병합된 data_to_confirm. 입력은 고치지 않는다.

    `numeric_facts_unconfirmed`(rfp primary pdf)면 pdf 단독 숫자(사업금액)로 결정하지 않는다:
    min_contract_amount 미적용, gate_fail이 아니면 guarded(최대 CONDITIONAL_GO), 전제조건·
    data_to_confirm 1건씩 추가. 점수 계산식은 같다.
    """
    # 1. 점수
    (
        fit_score,
        fit_counts,
        gate_counts,
        base,
        base_source,
        penalty,
        raw,
    ) = fit_score_for(gates, fits)
    weights = dict(WEIGHTS)
    go_threshold = GO_THRESHOLD
    conditional_threshold = CONDITIONAL_THRESHOLD

    # 2~3. 정책 및 결정 guard(위에서 먼저 맞는 것)
    budget = facts.project.budget_krw
    gate_counts, policy_unknown, min_amount, below_min, guarded = decision_factors(
        facts,
        gates,
        profile,
        numeric_facts_unconfirmed=numeric_facts_unconfirmed,
        evidence_view=evidence_view,
    )
    decision_rule, decision = decision_for_score(
        fit_score,
        gate_counts=gate_counts,
        below_min=below_min,
        guarded=guarded,
    )
    min_applied = decision_rule == "min_contract_amount"

    # 4. preconditions = LLM + 코드(UNKNOWN·RISK 게이트, 정책 unknown)
    code_pre = code_preconditions(
        gates, policy_unknown, numeric_facts_unconfirmed=numeric_facts_unconfirmed
    )
    preconditions = _dedup_texts([*synth.preconditions, *code_pre])

    # 5. why_not = 코드(FAIL 게이트, 최소 계약금액) + LLM
    code_why = code_why_not(gates, min_applied=min_applied, budget=budget, min_amount=min_amount)
    why_not = _dedup_texts([*code_why, *synth.why_not])

    # 6. data_to_confirm
    data_to_confirm = raw_data_to_confirm(
        gates, scores, synth, numeric_facts_unconfirmed=numeric_facts_unconfirmed
    )

    # 7. score_breakdown(키 전부 항상 존재)
    score_breakdown = {
        "base": base,
        "base_source": base_source,
        "fit_counts": fit_counts,
        "gate_counts": gate_counts,
        "penalty": penalty,  # = raw − base
        "raw": raw,
        "fit_score": fit_score,
        "weights": weights,
        "thresholds": {"GO": go_threshold, "CONDITIONAL": conditional_threshold},
        "policy_unknown": policy_unknown,
        "min_contract": {
            "budget_krw": budget,
            "min_contract_amount_krw": min_amount,
            "applied": min_applied,
        },
        "numeric_facts_unconfirmed": numeric_facts_unconfirmed,
        "decision_rule": decision_rule,
    }

    recommendation = Recommendation(
        decision=decision,  # type: ignore[arg-type]
        fit_score=fit_score,
        summary=synth.summary,
        preconditions=preconditions,
        why_not=why_not,
        score_breakdown=score_breakdown,
        basis=_basis(gates, fits, synth),
    )
    return recommendation, data_to_confirm
