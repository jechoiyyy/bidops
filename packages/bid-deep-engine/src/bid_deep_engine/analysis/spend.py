"""지출 원장(`.cache/bidops/spend.jsonl`)과 원장 실측 기반 예상 비용(spec M2-02 "지출 원장").

원장은 응답을 받은 API 호출 1건당 JSON 한 줄이다. 비용은 항상 유한한 float이고(계약 시트
13절 X4 — 미지 모델은 `pricing.MAX_PRICE`로 계산), `count_tokens`(무료)는 기록하지 않는다(X2).
읽을 수 없는 줄이 하나라도 있으면 `LedgerError`로 실행을 막는다 — 기록 무결성(과소 집계)을
지키기 위해서다(사용자 결정 1).

지출 금액 한도(누적 상한·이번 실행 한도·가드)는 없다. 비용 통제는 모델 호출 전 CLI 확인이다
(docs/design/2026-10-25-spend-approval.md). 확인 화면의 예상 비용은 `estimate_from_ledger`가
원장 실측으로 정한다.
"""

import json
import math
import statistics
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

Phase = Literal["analyze", "bench", "agent"]
Purpose = Literal["extract", "match", "synth", "chat"]
CostBasis = Literal["exact", "max_price", "subscription"]

OUTPUT_SAMPLE_WINDOW = 50  # tunable(>= 1). 호출별 출력 추정 표본: purpose·단가 모델별 최근 건수


class LedgerError(Exception):
    """원장 줄을 읽을 수 없음. 모델 호출을 막는다(CLI 종료 1)."""


class SpendRecord(BaseModel):
    """원장 한 줄. 필드 선언 순서가 JSON 키 순서다."""

    at: str  # ISO 8601, 초 단위, 로컬 시간대
    run_id: str  # "<phase>-<YYYYmmddTHHMMSS>"(로컬 시각), CLI 호출 1회당 1개
    phase: Phase
    slug: str
    purpose: Purpose
    model: str  # 요청 모델 ID
    served_model: str  # 응답 model(없으면 요청 모델)
    price_model: str | None  # pricing.price_for(served_model).price_model, max_price면 None
    cost_basis: CostBasis
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_input_tokens: int = Field(ge=0)
    cache_creation_5m: int = Field(ge=0)
    cache_creation_1h: int = Field(ge=0)
    # 항상 유한한 0 이상 float. NaN·음수는 합계를 무력화하므로 손상으로 본다.
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    stop_reason: str | None = None
    finish_reason: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    output_limit: int | None = Field(default=None, gt=0)
    model_fingerprint: str | None = None


class Ledger:
    """JSONL 지출 원장. 파일이 없으면 빈 원장이다."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, record: SpendRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()

    def records(self) -> list[SpendRecord]:
        if not self.path.exists():
            return []
        out: list[SpendRecord] = []
        for n, raw in enumerate(self.path.read_bytes().split(b"\n"), start=1):
            if not raw.strip():
                continue
            try:
                out.append(SpendRecord.model_validate_json(raw))
            except ValidationError as exc:
                raise LedgerError(f"ledger line {n} unreadable") from exc
        return out

    def recent_outputs(
        self, purpose: Purpose, price_model: str, n: int = OUTPUT_SAMPLE_WINDOW
    ) -> list[int]:
        """purpose·price_model이 같은 마지막 n건의 output_tokens(파일 순서 = 시간 순).

        호출별 출력 추정(LLM-01 D2)의 표본이다. `output_tokens <= 0`인 줄(테스트 시드·빈 응답)은
        표본이 아니므로 창에 세기 전에 뺀다. 원장이 없거나 일치가 없으면 `[]`.
        """
        samples = [
            r.output_tokens
            for r in self.records()
            if r.purpose == purpose
            and r.price_model == price_model
            and r.output_tokens > 0
            and r.stop_reason not in ("max_tokens", "refusal")
            and r.finish_reason not in ("length", "content_filter")
        ]
        return samples[-n:] if n > 0 else []

    def total(self, phase: str | None = None, *, subscription: bool = False) -> float:
        """phase 누적 비용(USD). phase None이면 전체 합.

        기본(`subscription=False`)은 API 과금 기록(`cost_basis != "subscription"`)만 더한다.
        `subscription=True`면 구독(claude -p) 기록만 더한다(API 환산 금액).
        """
        return math.fsum(
            r.cost_usd
            for r in self.records()
            if (phase is None or r.phase == phase)
            and (r.cost_basis == "subscription") == subscription
        )

    def total_for_run(self, run_id: str) -> float:
        """run_id가 같은 줄의 비용 합(USD). 없으면 0.0. 읽을 수 없는 줄이 있으면 `LedgerError`."""
        return math.fsum(r.cost_usd for r in self.records() if r.run_id == run_id)


def _pass_costs(records: list[SpendRecord]) -> list[tuple[str, float]]:
    """(run_id, slug)별 비용 합을 처음 나온 순서로. 한 pass가 호출 여러 번(mapreduce 등)이어도
    공고×pass 1회의 실측이 되게 묶는다. 값은 `(slug, 합)`."""
    groups: dict[tuple[str, str], list[float]] = {}
    for r in records:
        groups.setdefault((r.run_id, r.slug), []).append(r.cost_usd)
    return [(slug, math.fsum(costs)) for (_, slug), costs in groups.items()]


def estimate_from_ledger(
    ledger: Ledger, slug: str, purpose: Purpose, price_model: str
) -> float | None:
    """공고×pass 1회의 예상 비용(USD, 확인 화면용 — 판정에 쓰지 않는다).

    원장에서 purpose·price_model이 같은 줄을 (run_id, slug)별로 합쳐 pass 1회 실측으로 보고:
    1. 같은 slug의 가장 최근(파일 순서 = 시간 순) 실측
    2. 없으면 그 purpose·price_model 전체 실측의 중앙값
    3. 그것도 없으면 None(`추정 불가`)
    phase는 가리지 않는다(analyze·bench 모두 같은 요청의 실측이다). 네트워크를 쓰지 않는다.
    읽을 수 없는 줄이 있으면 `LedgerError`.
    """
    passes = _pass_costs(
        [r for r in ledger.records() if r.purpose == purpose and r.price_model == price_model]
    )
    same = [cost for s, cost in passes if s == slug]
    if same:
        return same[-1]
    if passes:
        return statistics.median(cost for _, cost in passes)
    return None
