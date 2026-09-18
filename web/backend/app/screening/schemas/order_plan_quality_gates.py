"""Wire schemas for the C-2 quality gate record (docs/contracts.md "품질 게이트 REST").

코드는 채점하지 않는다. 요청은 사람이 만든 gate artifact의 값을 그대로 싣고,
연결 검사와 판정 규칙은 service가 한다.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SHA256 = r"^[0-9a-f]{64}$"
# DB 열이 Numeric(7,4)이다. 소수 넷째 자리를 넘는 값은 저장 때 반올림되어 응답과
# 기록이 어긋나므로 받지 않는다.
_MAX_PCT_DECIMALS = 4

Sha256 = Annotated[str, Field(pattern=_SHA256)]
# strict: 문자열 "90"이나 bool을 숫자로 바꾸지 않는다. int는 float로 받는다.
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Pct = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=100)]
Count = Annotated[int, Field(strict=True, ge=0)]


def _check_decimals(value: float | None) -> float | None:
    if value is not None and Decimal(str(value)).as_tuple().exponent < -_MAX_PCT_DECIMALS:
        raise ValueError(f"at most {_MAX_PCT_DECIMALS} decimal places")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PassMetrics(_Strict):
    recall_pct: Pct | None = None
    precision_pct: Pct | None = None
    important_missed: Count | None = None
    review_load: Count | None = None

    _pct_decimals = field_validator("recall_pct", "precision_pct")(_check_decimals)


class QualityGateCreateRequest(_Strict):
    schema_version: Literal["order-plan-quality-gate-create-request.v1"]
    producer: Literal["human-review-client"]
    consumer: Literal["quality-gate-api"]
    request_id: UUID
    policy_version: str = Field(min_length=1, max_length=64)
    policy_sha256: Sha256
    binding_sha256: Sha256
    gold_manifest_sha256: Sha256
    gold_artifact_sha256: Sha256
    # 계약은 1~64자이지만 저장 열(0029)이 String(32)이다. 보고서 참조.
    gold_status: str = Field(min_length=1, max_length=32)
    scoring_input_sha256: Sha256
    evaluation_basis: Literal["product_rerun", "reference_artifact_rescore"]
    measurement_run_ids: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(min_length=1)
    # 네 key 모두 필수이고 값은 null을 허용한다(null = 사람 결정 전). 범위는 service가
    # 검사해 invalid_request로 답한다.
    threshold_recall_pct: Number | None
    threshold_precision_pct: Number | None
    threshold_important_missed_max: Annotated[int, Field(strict=True)] | None
    threshold_review_load_max: Annotated[int, Field(strict=True)] | None

    _threshold_decimals = field_validator("threshold_recall_pct", "threshold_precision_pct")(_check_decimals)

    @field_validator("gold_status")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class PassExecutionIds(_Strict):
    pass_1: list[UUID]
    pass_2: list[UUID] | None = None


class PassMetricsSet(_Strict):
    pass_1: PassMetrics
    pass_2: PassMetrics | None = None


class QualityEvaluationCreateRequest(_Strict):
    schema_version: Literal["order-plan-quality-evaluation-create-request.v1"]
    producer: Literal["human-review-client"]
    consumer: Literal["quality-gate-api"]
    request_id: UUID
    artifact_sha256: Sha256
    pass_execution_ids: PassExecutionIds
    pass_metrics: PassMetricsSet
    agreement_pct: Pct | None = None
    reference_full_window: PassMetrics | None = None
    reasons: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(default_factory=list, max_length=20)

    _agreement_decimals = field_validator("agreement_pct")(_check_decimals)

    @field_validator("reasons")
    @classmethod
    def _reasons_not_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("reasons must not be blank")
        return value


class GateThresholds(_Strict):
    recall_pct: float | None
    precision_pct: float | None
    important_missed_max: int | None
    review_load_max: int | None


class EvaluationMetrics(_Strict):
    pass_1: PassMetrics
    pass_2: PassMetrics | None = None
    agreement_pct: float | None = None
    reference_full_window: PassMetrics | None = None


class EvaluationView(_Strict):
    evaluation_id: str
    gate_id: str
    revision: int = Field(ge=1)
    result_status: Literal["통과", "미달", "미측정", "보류"]
    pass_execution_ids: PassExecutionIds
    measured_recall_pct: float | None
    measured_precision_pct: float | None
    measured_important_missed: int | None
    measured_review_load: int | None
    metrics: EvaluationMetrics
    reasons: list[str]
    artifact_sha256: str
    evaluated_by: str
    evaluated_at: datetime


class GateView(_Strict):
    gate_id: str
    policy_version: str
    policy_sha256: str
    binding_sha256: str
    gold_manifest_sha256: str
    gold_artifact_sha256: str
    gold_status: str
    scoring_input_sha256: str
    evaluation_basis: Literal["product_rerun", "reference_artifact_rescore"]
    scoring_unit: Literal["per_published_day"]
    measurement_run_ids: list[str]
    required_pass_count: Literal[2]
    thresholds: GateThresholds
    created_by: str
    created_at: datetime
    latest_evaluation: EvaluationView | None


class MeasurementExecution(_Strict):
    execution_id: UUID
    source_run_id: str
    status: Literal["대기", "실행 중", "중지 요청", "성공", "부분 성공", "실패", "중단됨"]
    queued_at: datetime
    finished_at: datetime | None


class GateListItem(GateView):
    measurement_executions: list[MeasurementExecution]


class QualityGateCreateResponse(GateView):
    schema_version: Literal["order-plan-quality-gate-response.v1"]
    producer: Literal["quality-gate-api"]
    consumer: Literal["human-review-client"]
    request_id: UUID


class QualityGateListResponse(_Strict):
    schema_version: Literal["order-plan-quality-gate-list-response.v1"]
    producer: Literal["quality-gate-api"]
    consumer: Literal["human-review-client"]
    policy_version: str
    items: list[GateListItem]


class QualityEvaluationCreateResponse(EvaluationView):
    schema_version: Literal["order-plan-quality-evaluation-response.v1"]
    producer: Literal["quality-gate-api"]
    consumer: Literal["human-review-client"]
    request_id: UUID
