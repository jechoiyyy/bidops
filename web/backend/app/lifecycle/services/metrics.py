"""검증 지표 응답 조립 (명세 §6.1).

다섯 지표는 전부 판정·리뷰 데이터에서 나온다. lifecycle은 지표의 의미를 알지
못하므로, 임계값 판단과 "측정 불가" 사유 라벨까지 판정 projection이 조립한 것을
응답 모델로 옮기기만 한다. 제공자가 없으면 다섯 지표 모두 측정 불가다.
"""

from __future__ import annotations

from .. import extension_registry
from ..schemas import MetricBasis, ValidationMetric

#: 제공자가 없을 때 내보내는 지표의 키와 이름. 순서는 응답 계약의 일부다.
ABSENT_METRICS: tuple[tuple[str, str], ...] = (
    ("reproducibility", "재현성"),
    ("discriminative_power", "변별력"),
    ("evidence_validity", "근거 타당성"),
    ("information_sufficiency", "정보 충분성"),
    ("perspective_split", "관점 분할"),
)

ABSENT_REASON = "판정 결과를 제공하는 모듈이 없어 지표를 계산할 수 없습니다."


def _absent(key: str, label: str) -> ValidationMetric:
    """값이 아니라 측정 불가다. 0이나 빈 값으로 바꾸지 않는다."""

    return ValidationMetric(
        key=key,
        label=label,
        value=None,
        percentage=None,
        threshold=None,
        meets_threshold=None,
        status="not_measurable",
        basis=MetricBasis(numerator=0, denominator=0, detail={}),
        reason=ABSENT_REASON,
    )


def calculate_validation_metrics(session, run_id: str) -> list[ValidationMetric]:
    """회차 하나의 검증 지표 다섯 개. DB 상태를 바꾸지 않는다."""

    metrics = extension_registry().judgment_projection.metrics_input(session, [run_id])
    values = metrics.get(run_id) if isinstance(metrics, dict) else None
    if not values:
        return [_absent(key, label) for key, label in ABSENT_METRICS]
    return list(values)


# Small aliases make the service convenient for callers and tests while the
# public name remains explicit about the endpoint's five validation metrics.
calculate_metrics = calculate_validation_metrics
get_validation_metrics = calculate_validation_metrics
