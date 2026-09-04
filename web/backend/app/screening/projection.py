"""판정 결과를 lifecycle 화면에 실어 주는 projection과 deep_review seam (명세 §6.1·§6.3).

lifecycle은 자기 목록·상세·통계·지표에 등급과 리뷰를 함께 보여 주어야 하지만
판정 테이블을 알지 못한다. 그 자리를 여기 구현이 채운다. 반대 방향(deep_review가
판정을 읽는 자리)은 이름을 가려 받는 seam 함수 세 개뿐이다.

성능 계약: 회차 하나가 최대 약 2,000건이므로 **회차 단위로 한 번에** 읽고
메모리에서 결합한다. 공고당 조회(N+1)를 만들지 않는다.

응답 DTO는 lifecycle schemas가 소유한다. 이 파일은 그 모델을 만들어 돌려줄 뿐이고
OpenAPI 응답 모양은 바뀌지 않는다.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..core.constants import GRADE_ORDER, READINESS_ORDER
from ..lifecycle.models import Notice, NoticeObservation
from .models import Judgment, JudgmentRevision, Perspective, Review
from ..lifecycle.schemas import (
    CounterargumentResponse,
    DistributionItem,
    EvidenceResponse,
    FunnelItem,
    JudgmentResponse,
    MatchedPerformanceResponse,
    MetricBasis,
    PerspectiveResponse,
    ReviewAnswerResponse,
    ReviewResponse,
    ValidationMetric,
    VerificationItemResponse,
    VerificationRequest,
)

#: 회차 통계의 focus 분포 정렬 순서. 등급·준비 상태와 달리 core 상수가 아니라
#: 판정 축이므로 여기서 소유한다.
FOCUS_ORDER = ["AI/데이터", "블록체인·DID", "공공 SI·통합관리", "해당 없음"]

#: 필터가 없을 때 목록에 적용되는 기본 조건. projection의 일부이므로 제공자가
#: 없으면 적용되지 않는다(§6.1).
DEFAULT_EXCLUDED_GRADE = "제외"

GRADE_REPRODUCIBILITY_THRESHOLD = 0.80
DISCRIMINATIVE_POWER_RANGE = (0.10, 0.25)
EVIDENCE_VALIDITY_THRESHOLD = 0.70
PERSPECTIVE_SPLIT_THRESHOLD = 0.40

#: 확인 항목의 근거 문장에서 회사 프로필 절 번호만 잘라낸다. "회사 프로필 5.2의
#: 조달 자격 항목이" 처럼 절 번호 뒤에 조사가 붙어 나온다.
_PROFILE_SECTION_RE = re.compile(r"회사 프로필\s+(\d+(?:\.\d+)*)")


# --- deep_review seam (§6.3) --------------------------------------------------


@dataclass(frozen=True)
class JudgmentSummary:
    """공고 하나의 현재 판정 요약.

    deep_review는 판정 테이블을 직접 읽지 못한다(§4). 문서 준비와 입력 동결이
    필요로 하는 값만 이 불변 값으로 건넨다. `run_id`는 판정이 기록된 회차이며,
    revision이 없는 과거 판정에는 없을 수 있으므로 `None`이 정상이다.
    """

    notice_id: int
    run_id: str | None
    grade: str | None
    readiness: str | None
    focus: str | None


@dataclass(frozen=True)
class CorrectedGrade:
    """사람이 정정한 등급. 정정이 없으면 아예 만들지 않는다."""

    grade: str
    run_id: str | None
    review_id: int


def _summary(notice_id: int, grade: str | None, readiness: str | None, focus: str | None, run_id: str | None) -> JudgmentSummary:
    return JudgmentSummary(notice_id=notice_id, run_id=run_id, grade=grade, readiness=readiness, focus=focus)


def current_judgments(
    session: Session, notice_ids: Sequence[int]
) -> Mapping[int, JudgmentSummary]:
    """공고 여러 건의 현재 판정. 건수와 무관하게 상수 회 조회다.

    판정이 없는 공고는 결과에 없다 — `null`과 "판정 없음"을 같은 값으로 만들지
    않기 위해 빈 요약을 채우지 않는다.
    """

    ids = [int(value) for value in notice_ids]
    if not ids:
        return {}
    rows = session.execute(
        select(Judgment.notice_id, Judgment.grade, Judgment.readiness, Judgment.primary_focus).where(
            Judgment.notice_id.in_(ids)
        )
    ).all()
    if not rows:
        return {}
    revisions = session.execute(
        select(JudgmentRevision.notice_id, JudgmentRevision.run_id, JudgmentRevision.sequence).where(
            JudgmentRevision.notice_id.in_([row[0] for row in rows])
        )
    ).all()
    latest_run: dict[int, tuple[int, str | None]] = {}
    for notice_id, run_id, sequence in revisions:
        current = latest_run.get(notice_id)
        if current is None or sequence > current[0]:
            latest_run[notice_id] = (sequence, run_id)
    return {
        notice_id: _summary(
            notice_id, grade, readiness, focus, latest_run.get(notice_id, (0, None))[1]
        )
        for notice_id, grade, readiness, focus in rows
    }


def current_judgment(session: Session, notice_id: int) -> JudgmentSummary | None:
    """공고 하나의 현재 판정. 없으면 `None`."""

    return current_judgments(session, [notice_id]).get(int(notice_id))


def latest_corrected_grades(
    session: Session, notice_ids: Sequence[int]
) -> Mapping[int, CorrectedGrade]:
    """공고 여러 건의 정정 등급. 건수와 무관하게 **한 번의 조회**다.

    `latest_corrected_grade`의 batch 판이며 `current_judgment`/`current_judgments`
    와 같은 관계다. 목록 화면과 자격 재평가는 공고 수백~수천 건을 한 번에 다루고
    명세 §8이 그 자리에 N+1을 금지하므로, 단건 판만 seam에 두면 호출부가 공고당
    조회를 만들 수밖에 없다.

    정정이 없는 공고는 결과에 없다 — `null`과 "정정 없음"을 같은 값으로 만들지
    않기 위해 빈 항목을 채우지 않는다. 정정 등급이 비어 있는 리뷰도 정정으로
    세지 않는다.
    """

    ids = [int(value) for value in notice_ids]
    if not ids:
        return {}
    rows = session.execute(
        select(Review.notice_id, Review.corrected_grade, Review.run_id, Review.id)
        .where(Review.notice_id.in_(ids), Review.corrected_grade.is_not(None))
        .order_by(Review.updated_at.desc(), Review.id.desc())
    ).all()
    corrected: dict[int, CorrectedGrade] = {}
    for notice_id, grade, run_id, review_id in rows:
        if not grade:
            continue
        # 정렬이 최신 우선이므로 공고당 첫 행만 남긴다.
        corrected.setdefault(
            int(notice_id), CorrectedGrade(grade=grade, run_id=run_id, review_id=review_id)
        )
    return corrected


def latest_corrected_grade(session: Session, notice_id: int) -> CorrectedGrade | None:
    """가장 최근에 사람이 정정한 등급. 정정이 없으면 `None`."""

    return latest_corrected_grades(session, [notice_id]).get(int(notice_id))


# --- lifecycle projection (§6.1) ----------------------------------------------


def _judgment_response(judgment: Judgment | None) -> JudgmentResponse | None:
    if judgment is None:
        return None
    return JudgmentResponse(
        id=judgment.id,
        schema_version=judgment.schema_version,
        grade=judgment.grade,
        readiness=judgment.readiness,
        primary_focus=judgment.primary_focus,
        exclusion_category=judgment.exclusion_category,
        summary=judgment.summary,
        next_action=judgment.next_action,
        perspectives=[
            PerspectiveResponse(
                id=perspective.id,
                position=perspective.position,
                name=perspective.name,
                assessment=perspective.assessment,
                reason=perspective.reason,
                evidence=[
                    EvidenceResponse(
                        id=evidence.id,
                        source=evidence.source,
                        status=evidence.status,
                        fact=evidence.fact,
                    )
                    for evidence in perspective.evidence
                ],
            )
            for perspective in judgment.perspectives
        ],
        counterarguments=[
            CounterargumentResponse(id=item.id, position=item.position, text=item.text)
            for item in judgment.counterarguments
        ],
        verification_items=[
            VerificationItemResponse(
                id=item.id,
                item=item.item,
                why=item.why,
                blocking=item.blocking,
                status=item.status,
            )
            for item in judgment.verification_items
        ],
        matched_performances=[
            MatchedPerformanceResponse(
                id=item.id,
                name=item.name,
                match_reason=item.match_reason,
                mismatch_or_limit=item.mismatch_or_limit,
                source=item.source,
                status=item.status,
            )
            for item in judgment.matched_performances
        ],
    )


def _review_response(review: Review) -> ReviewResponse:
    return ReviewResponse(
        id=review.id,
        run_id=review.run_id,
        notice_pk=review.notice_pk,
        disposition=review.disposition,
        system_judgment_review=review.system_judgment_review,
        corrected_grade=review.corrected_grade,
        corrected_readiness=review.corrected_readiness,
        weakest_perspective=review.weakest_perspective,
        reason=review.reason,
        reviewer=review.reviewer,
        created_at=review.created_at,
        updated_at=review.updated_at,
        answers=[
            ReviewAnswerResponse(id=answer.id, item=answer.item, answer=answer.answer)
            for answer in review.answers
        ],
    )


def _distribution(values: list[str | None], order: list[str]) -> list[DistributionItem]:
    counter = Counter(value or "값 없음" for value in values)
    keys = order + sorted(key for key in counter if key not in order)
    return [DistributionItem(key=key, label=key, count=counter[key]) for key in keys if counter[key]]


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
    """다섯 지표 중 유일하게 회차 범위를 벗어나 전체를 훑는다."""

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
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .where(NoticeObservation.run_id == run_id, Notice.sample_role == "analysis")
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
        select(Review.system_judgment_review)
        .join(Notice, Review.notice_pk == Notice.id)
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .where(
            NoticeObservation.run_id == run_id,
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
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .where(NoticeObservation.run_id == run_id)
        .options(
            # notice.attachments 까지 함께 읽지 않으면 판정 수만큼 조회가 늘어난다.
            selectinload(Judgment.notice).selectinload(Notice.attachments),
            selectinload(Judgment.verification_items),
        )
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
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .where(NoticeObservation.run_id == run_id)
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


class ScreeningJudgmentProjection:
    """`JudgmentProjection` 구현. 조립 계층이 registry에 등록한다(§6)."""

    # --- 목록 ---------------------------------------------------------------
    def notice_fields(
        self, session: Session, notice_ids: Sequence[int]
    ) -> Mapping[int, Mapping[str, Any]]:
        ids = [int(value) for value in notice_ids]
        if not ids:
            return {}
        rows = session.execute(
            select(Judgment.notice_id, Judgment.grade, Judgment.readiness, Judgment.primary_focus).where(
                Judgment.notice_id.in_(ids)
            )
        ).all()
        return {
            notice_id: {"grade": grade, "readiness": readiness, "focus": focus}
            for notice_id, grade, readiness, focus in rows
        }

    def notice_ids_for_filters(
        self,
        session: Session,
        *,
        run_id: str | None = None,
        grade: str | None = None,
        readiness: str | None = None,
        focus: str | None = None,
    ) -> Sequence[int] | None:
        conditions = []
        if grade and grade != "all":
            conditions.append(Judgment.grade == grade)
        elif grade != "all":
            # 필터가 없을 때의 기본 조건. projection의 일부이므로 제공자가 없으면
            # 적용되지 않는다(§6.1).
            conditions.append(Judgment.grade != DEFAULT_EXCLUDED_GRADE)
        if readiness:
            conditions.append(Judgment.readiness == readiness)
        if focus:
            conditions.append(Judgment.primary_focus == focus)
        if not conditions:
            # grade=all 이고 다른 판정 필터가 없다 — 공고 집합을 제한하지 않는다.
            return None
        query = select(Judgment.notice_id).where(*conditions)
        if run_id is not None:
            query = query.join(Notice, Judgment.notice_pk == Notice.id).join(
                NoticeObservation, NoticeObservation.notice_id == Notice.id
            ).where(NoticeObservation.run_id == run_id)
        return list(session.scalars(query.distinct()))

    def grade_rank(self, session: Session, notice_ids: Sequence[int]) -> Mapping[int, int]:
        """`sort=grade` 가 쓰는 공고별 등급 순위.

        판정이 없는 공고와 순서를 모르는 등급은 같은 마지막 순위다 — 둘을 가르면
        "판정 없음"이 "알 수 없는 등급"보다 앞이나 뒤로 밀려 목록 순서가 바뀐다.
        호출부가 값을 만들어 내지 않도록 요청한 모든 공고에 순위를 준다.
        """

        ids = [int(value) for value in notice_ids]
        if not ids:
            return {}
        rows = session.execute(
            select(Judgment.notice_id, Judgment.grade).where(Judgment.notice_id.in_(ids))
        ).all()
        order = {value: index for index, value in enumerate(GRADE_ORDER)}
        graded = {notice_id: order.get(grade, len(GRADE_ORDER)) for notice_id, grade in rows}
        return {notice_id: graded.get(notice_id, len(GRADE_ORDER)) for notice_id in ids}

    # --- 상세 ---------------------------------------------------------------
    def notice_detail(self, session: Session, notice_id: int) -> Mapping[str, Any]:
        judgment = session.scalar(
            select(Judgment)
            .where(Judgment.notice_id == int(notice_id))
            .options(
                selectinload(Judgment.perspectives).selectinload(Perspective.evidence),
                selectinload(Judgment.counterarguments),
                selectinload(Judgment.verification_items),
                selectinload(Judgment.matched_performances),
            )
        )
        reviews = session.scalars(
            select(Review)
            .where(Review.notice_id == int(notice_id))
            .options(selectinload(Review.answers))
            .order_by(Review.id)
        ).all()
        return {
            "judgment": _judgment_response(judgment),
            "reviews": [_review_response(review) for review in reviews],
        }

    # --- 회차 통계 -----------------------------------------------------------
    def run_stats(self, session: Session, run_id: str) -> Mapping[str, Any]:
        rows = session.execute(
            select(Notice.id, Notice.sample_role, Judgment.grade, Judgment.readiness, Judgment.primary_focus)
            .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
            .join(Judgment, Judgment.notice_pk == Notice.id)
            .where(NoticeObservation.run_id == run_id)
            .distinct()
        ).all()
        analysis = [row for row in rows if row[1] == "analysis"]
        priority = sum(row[2] == "우선 검토" for row in analysis)
        audit_missed = sum(row[1] == "audit" and row[2] != DEFAULT_EXCLUDED_GRADE for row in rows)
        queue_count = sum(row[1] == "analysis" and row[2] != DEFAULT_EXCLUDED_GRADE for row in rows)

        judgments = session.scalars(
            select(Judgment)
            .join(Notice, Judgment.notice_pk == Notice.id)
            .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
            .where(NoticeObservation.run_id == run_id)
            .options(selectinload(Judgment.verification_items))
            .order_by(Notice.id)
            .distinct()
        ).all()
        role_by_notice = {row[0]: row[1] for row in rows}
        verification: dict[str, dict[str, Any]] = {}
        blocking_by_notice: dict[int, list[str]] = {}
        for judgment in judgments:
            notice_id = judgment.notice_id
            blocking = [item.item for item in judgment.verification_items if item.blocking and item.item]
            if blocking:
                blocking_by_notice[notice_id] = blocking
            if role_by_notice.get(notice_id) != "analysis":
                continue
            for item in judgment.verification_items:
                if not item.blocking or not item.item:
                    continue
                record = verification.setdefault(
                    item.item,
                    {"count": 0, "notice_pks": [], "profile_sections": []},
                )
                record["count"] += 1
                record["notice_pks"].append(notice_id)
                match = _PROFILE_SECTION_RE.search(item.why or "")
                if match and match.group(1) not in record["profile_sections"]:
                    record["profile_sections"].append(match.group(1))

        return {
            "priority_review_count": priority,
            "audit_missed_count": audit_missed,
            "funnel": [FunnelItem(key="review_queue", label="검토 대기", count=queue_count)],
            "grade_distribution": _distribution([row[2] for row in analysis], GRADE_ORDER),
            "readiness_distribution": _distribution([row[3] for row in analysis], READINESS_ORDER),
            "focus_distribution": _distribution([row[4] for row in analysis], FOCUS_ORDER),
            "verification_requests": [
                # 건수가 많은 항목부터. 화면이 그대로 그릴 수 있어야 한다.
                VerificationRequest(
                    item=item,
                    count=record["count"],
                    notice_pks=record["notice_pks"],
                    profile_sections=record["profile_sections"],
                )
                for item, record in sorted(verification.items(), key=lambda pair: (-pair[1]["count"], pair[0]))
            ],
            "blocking_verification_items": blocking_by_notice,
        }

    # --- 검증 지표 -----------------------------------------------------------
    def metrics_input(self, session: Session, run_ids: Sequence[str]) -> Mapping[str, Any]:
        return {
            run_id: [
                _reproducibility(session),
                _discriminative_power(session, run_id),
                _evidence_validity(session, run_id),
                _information_sufficiency(session, run_id),
                _perspective_split(session, run_id),
            ]
            for run_id in run_ids
        }


__all__ = [
    "CorrectedGrade",
    "FOCUS_ORDER",
    "JudgmentSummary",
    "ScreeningJudgmentProjection",
    "current_judgment",
    "current_judgments",
    "latest_corrected_grade",
    "latest_corrected_grades",
]
