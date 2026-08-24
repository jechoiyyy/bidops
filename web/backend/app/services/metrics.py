"""Validation metric calculations for the BidOps workflow."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Judgment, Notice, Review
from ..schemas import MetricBasis, ValidationMetric


GRADE_REPRODUCIBILITY_THRESHOLD = 0.80
DISCRIMINATIVE_POWER_RANGE = (0.10, 0.25)
EVIDENCE_VALIDITY_THRESHOLD = 0.70
PERSPECTIVE_SPLIT_THRESHOLD = 0.40


def _basis(numerator: int | float, denominator: int | float, **detail: Any) -> MetricBasis:
    return MetricBasis(numerator=numerator, denominator=denominator, detail=detail)


def _not_measurable(
    key: str,
    label: str,
    reason: str,
    *,
    detail: dict[str, Any] | None = None,
    denominator: int = 0,
    threshold: Any = None,
) -> ValidationMetric:
    return ValidationMetric(
        key=key,
        label=label,
        value=None,
        percentage=None,
        threshold=threshold,
        meets_threshold=None,
        status="not_measurable",
        basis=_basis(0, denominator, **(detail or {})),
        reason=reason,
    )


def _measured(
    key: str,
    label: str,
    numerator: int,
    denominator: int,
    *,
    threshold: Any,
    meets_threshold: bool | None,
    status: str,
    detail: dict[str, Any] | None = None,
    reason: str | None = None,
) -> ValidationMetric:
    value = numerator / denominator if denominator else None
    return ValidationMetric(
        key=key,
        label=label,
        value=value,
        percentage=value * 100 if value is not None else None,
        threshold=threshold,
        meets_threshold=meets_threshold,
        status=status,  # type: ignore[arg-type]
        basis=_basis(numerator, denominator, **(detail or {})),
        reason=reason,
    )


def _reproducibility(session: Session) -> ValidationMetric:
    rows = session.execute(
        select(Notice.notice_key, Judgment.grade)
        .join(Judgment, Judgment.notice_pk == Notice.id)
        .where(Judgment.grade.is_not(None))
    ).all()
    grades_by_key: dict[str, list[str]] = defaultdict(list)
    for notice_key, grade in rows:
        if notice_key and grade:
            grades_by_key[notice_key].append(grade)

    repeated = {key: grades for key, grades in grades_by_key.items() if len(grades) >= 2}
    comparison_count = sum(len(grades) * (len(grades) - 1) // 2 for grades in repeated.values())
    if comparison_count == 0:
        return _not_measurable(
            "reproducibility",
            "재현성",
            "둘 이상의 회차에서 같은 공고를 판정한 기록이 없습니다.",
            detail={"repeated_notice_keys": 0},
            threshold=GRADE_REPRODUCIBILITY_THRESHOLD,
        )

    matching = sum(
        sum(left == right for left, right in combinations(grades, 2))
        for grades in repeated.values()
    )
    return _measured(
        "reproducibility",
        "재현성",
        matching,
        comparison_count,
        threshold=GRADE_REPRODUCIBILITY_THRESHOLD,
        meets_threshold=matching / comparison_count >= GRADE_REPRODUCIBILITY_THRESHOLD,
        status="pass" if matching / comparison_count >= GRADE_REPRODUCIBILITY_THRESHOLD else "fail",
        detail={
            "matching_comparisons": matching,
            "comparison_groups": len(repeated),
        },
    )


def _discriminative_power(session: Session, run_id: str) -> ValidationMetric:
    rows = session.execute(
        select(Judgment.grade)
        .join(Notice, Judgment.notice_pk == Notice.id)
        .where(Notice.run_id == run_id, Notice.sample_role == "analysis")
    ).all()
    grades = [grade for (grade,) in rows if grade]
    denominator = len(grades)
    numerator = sum(grade == "우선 검토" for grade in grades)
    if denominator == 0:
        return _not_measurable(
            "discriminative_power",
            "변별력",
            "선택한 회차에 분석 표본 판정이 없습니다.",
            threshold={"min": DISCRIMINATIVE_POWER_RANGE[0], "max": DISCRIMINATIVE_POWER_RANGE[1]},
        )
    lower, upper = DISCRIMINATIVE_POWER_RANGE
    value = numerator / denominator
    return _measured(
        "discriminative_power",
        "변별력",
        numerator,
        denominator,
        threshold={"min": lower, "max": upper},
        meets_threshold=lower <= value <= upper,
        status="pass" if lower <= value <= upper else "fail",
        detail={"grade": "우선 검토", "sample_role": "analysis"},
    )


def _evidence_validity(session: Session, run_id: str) -> ValidationMetric:
    values = session.scalars(
        select(Review.system_judgment_review).where(
            Review.run_id == run_id,
            Review.system_judgment_review.is_not(None),
        )
    ).all()
    values = [value for value in values if value and value.strip()]
    denominator = len(values)
    numerator = sum(value == "동의" for value in values)
    if denominator == 0:
        return _not_measurable(
            "evidence_validity",
            "근거 타당성",
            "선택한 회차에 시스템 판정 평가가 기록된 리뷰가 없습니다.",
            threshold=EVIDENCE_VALIDITY_THRESHOLD,
        )
    value = numerator / denominator
    return _measured(
        "evidence_validity",
        "근거 타당성",
        numerator,
        denominator,
        threshold=EVIDENCE_VALIDITY_THRESHOLD,
        meets_threshold=value >= EVIDENCE_VALIDITY_THRESHOLD,
        status="pass" if value >= EVIDENCE_VALIDITY_THRESHOLD else "fail",
        detail={"agreement": numerator, "distribution": dict(defaultdict(int, ((v, values.count(v)) for v in set(values))))},
    )


def _information_sufficiency(session: Session, run_id: str) -> ValidationMetric:
    judgments = session.scalars(
        select(Judgment)
        .join(Notice, Judgment.notice_pk == Notice.id)
        .where(Notice.run_id == run_id)
        .options(selectinload(Judgment.notice), selectinload(Judgment.verification_items))
    ).all()
    items = [item for judgment in judgments for item in judgment.verification_items]
    if not items:
        return _not_measurable(
            "information_sufficiency",
            "정보 충분성",
            "선택한 회차에 확인 항목이 없습니다.",
        )

    # Step 1/2 intentionally keep the artifact contract unchanged.  The
    # model has no separate attachment-required flag, so the observable,
    # reproducible interpretation is an unresolved item on a notice with no
    # attached document.  This avoids inferring attachment dependence from
    # prose or turning a missing field into a zero.
    unresolved_without_attachment = sum(
        item.status != "확인 완료"
        and not judgment.notice.attachments
        for judgment in judgments
        for item in judgment.verification_items
    )
    return _measured(
        "information_sufficiency",
        "정보 충분성",
        unresolved_without_attachment,
        len(items),
        threshold=None,
        meets_threshold=None,
        status="measured",
        detail={
            "verification_items": len(items),
            "unresolved_without_attachment": unresolved_without_attachment,
        },
        reason="이 항목은 사전 확정된 합격 임계값 없이 비율을 정량화합니다.",
    )


def _perspective_split(session: Session, run_id: str) -> ValidationMetric:
    judgments = session.scalars(
        select(Judgment)
        .join(Notice, Judgment.notice_pk == Notice.id)
        .where(Notice.run_id == run_id)
        .options(selectinload(Judgment.perspectives))
    ).all()
    eligible = [judgment for judgment in judgments if len(judgment.perspectives) >= 2]
    if not eligible:
        return _not_measurable(
            "perspective_split",
            "관점 분할",
            "관점이 둘 이상인 판정이 없어 관점 간 차이를 계산할 수 없습니다.",
            threshold=PERSPECTIVE_SPLIT_THRESHOLD,
        )
    split = sum(
        len({p.assessment for p in judgment.perspectives if p.assessment is not None}) >= 2
        for judgment in eligible
    )
    value = split / len(eligible)
    return _measured(
        "perspective_split",
        "관점 분할",
        split,
        len(eligible),
        threshold=PERSPECTIVE_SPLIT_THRESHOLD,
        meets_threshold=value >= PERSPECTIVE_SPLIT_THRESHOLD,
        status="pass" if value >= PERSPECTIVE_SPLIT_THRESHOLD else "fail",
        detail={"multi_perspective_judgments": len(eligible)},
    )


def calculate_validation_metrics(session: Session, run_id: str) -> list[ValidationMetric]:
    """Calculate all five validation metrics without mutating database state."""

    return [
        _reproducibility(session),
        _discriminative_power(session, run_id),
        _evidence_validity(session, run_id),
        _information_sufficiency(session, run_id),
        _perspective_split(session, run_id),
    ]


# Small aliases make the service convenient for callers and tests while the
# public name remains explicit about the endpoint's five validation metrics.
calculate_metrics = calculate_validation_metrics
get_validation_metrics = calculate_validation_metrics
