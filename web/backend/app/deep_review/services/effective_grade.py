"""공고의 effective grade를 선별 seam으로 계산한다 (명세 §4·§6.2).

effective grade = 사람이 정정한 등급이 있으면 그것, 없으면 판정 등급이다.
판정과 리뷰는 선별(screening) 소유이므로 deep_review는 그 ORM을 직접 읽지 않고
§4가 허용한 읽기 전용 seam 함수만 쓴다. **seam import는 함수 안에서** 한다 —
모듈 최상위에서 들면 선별 폴더가 없는 배포에서 deep_review 테스트가 수집조차
되지 않는다(`document_bundles.effective_grade`와 같은 이유).

여기 있는 함수는 **batch**다. 회차 하나의 사전규격 공고 전부(약 2,000건)와
사전규격 목록 한 페이지가 이 값을 필요로 하고, 명세 §8이 그 자리에 N+1을
금지하기 때문이다. 판정도 정정도 없는 공고는 결과에 없다 — "등급 없음"을 빈
문자열이나 특정 등급으로 바꾸지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, not_, or_, select
from sqlalchemy.sql.elements import ColumnElement

from ...core.config import get_settings
from ...lifecycle.models import BriefingItem, Notice

#: 자동 문서 준비 자격을 여는 유일한 등급 (명세 §6.2).
PRIORITY_GRADE = "우선 검토"

#: `grade_source` 안전 코드 (명세 §8).
SOURCE_HUMAN_REVIEW = "human_review"
SOURCE_SCREENING_JUDGMENT = "screening_judgment"


@dataclass(frozen=True)
class EffectiveGrade:
    """한 공고의 현재 등급과 그 출처.

    `grade`가 ``None``이면 판정도 정정도 없다는 뜻이고 그때 `source`도 ``None``
    이다. 둘을 따로 두는 이유는 사람 정정과 모델 판정을 같은 값으로 접지 않기
    위해서다(§8).

    `run_id`·`review_id`는 **이 등급을 만든 것이 무엇인가**를 가리킨다. 명세
    §6.2가 자동 준비 감사 이벤트에 "촉발 회차·리뷰 식별자"를 요구하는데, 등급
    변경 hook은 확장점 서명상 그 식별자를 받지 않으므로 등급 자신이 실어 나른다.
    사람 정정에서 온 등급이면 그 리뷰의 회차와 리뷰 id, 판정에서 온 등급이면 그
    판정이 기록된 회차이고 `review_id`는 ``None``이다. 값이 없는 것은 그대로
    ``None``이며 다른 회차로 채우지 않는다.
    """

    notice_id: int
    grade: str | None
    source: str | None
    run_id: str | None = None
    review_id: int | None = None
    assessed_at: datetime | None = None

    @property
    def is_priority(self) -> bool:
        return self.grade == PRIORITY_GRADE


def effective_grades(
    session: Any, notice_ids: Sequence[int]
) -> Mapping[int, EffectiveGrade]:
    """공고별 effective grade. 공고 수와 무관하게 상수 회 조회다.

    판정도 정정도 없는 공고는 결과에 **없다**. 호출부는 그것을 "등급 없음"으로
    읽고 자동 준비 대상에서 제외한다.
    """

    # 선별 seam은 함수 안에서 늦게 들여온다(§4). 방향과 이름은 §4가 허용한
    # 읽기 전용 seam 그대로이며 import 시점만 옮긴다.
    from ...screening import current_judgments, latest_corrected_grades

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return {}
    corrected = latest_corrected_grades(session, ids)
    judgments = current_judgments(session, ids)
    resolved: dict[int, EffectiveGrade] = {}
    for notice_id in ids:
        correction = corrected.get(notice_id)
        if correction is not None:
            resolved[notice_id] = EffectiveGrade(
                notice_id=notice_id,
                grade=correction.grade,
                source=SOURCE_HUMAN_REVIEW,
                run_id=correction.run_id,
                review_id=correction.review_id,
                assessed_at=correction.assessed_at,
            )
            continue
        judgment = judgments.get(notice_id)
        if judgment is not None and judgment.grade is not None:
            resolved[notice_id] = EffectiveGrade(
                notice_id=notice_id,
                grade=judgment.grade,
                source=SOURCE_SCREENING_JUDGMENT,
                run_id=judgment.run_id,
                assessed_at=judgment.assessed_at,
            )
    return resolved


def priority_notice_ids(session: Any, notice_ids: Sequence[int]) -> frozenset[int]:
    """effective grade가 `우선 검토`인 공고 id."""

    return frozenset(
        notice_id
        for notice_id, value in effective_grades(session, notice_ids).items()
        if value.is_priority
    )


def sw_business_object(flags: Any) -> bool:
    """발주기관이 매긴 `SW사업대상` 값. `unknown`·값 없음을 `Y`로 접지 않는다."""

    return isinstance(flags, Mapping) and flags.get("sw_business_status") == "Y"


def sw_business_notice_ids(session: Any, notice_ids: Sequence[int]) -> frozenset[int]:
    """`SW사업대상=Y`인 **사전규격** 공고 id. 조회는 한 번이다."""

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return frozenset()
    return frozenset(
        int(notice_id)
        for notice_id, flags in session.execute(
            select(Notice.id, Notice.qualification_flags_json).where(
                Notice.id.in_(ids), Notice.source_type == "pre_spec"
            )
        ).all()
        if sw_business_object(flags)
    )


# --- 자동 처리 범위 (2026-11-19 사전규격 단계 수정안 §3 A) ---------------------
#
# 자동 경로 셋 — 첨부 취득 worker의 claim, 자동 문서 준비, 자동 개요 enqueue — 은
# 의견 마감이 지나지 않았거나(마감 미확인 포함) 사업기회가 `추적 중`(계속 추적·
# 보류)인 사전규격만 처리한다. 마감이 지났고 추적 중이 아닌 공고는 사람이 추적을
# 시작할 때까지 그대로 둔다(추적 결정 hook이 그때 같은 경로를 다시 부른다).
#
# 규칙은 **여기 한 벌**이다. "마감 경과"와 "추적 중"의 뜻은 lifecycle이 공개한 술어
# 그대로라 사전규격 목록의 `deadline_scope`(ADR-0064)·`추적 중` 보기와 같다.
# 첨부 claim은 SQL(`attachment_claim_scope_predicate`)로, 자동 준비·목록 투영·개요
# enqueue는 `overview_eligibility`로 읽는데 둘 다 `auto_processing_predicate`
# 하나에서 나온다.


def _utc_now() -> datetime:
    return datetime.now(UTC)


def auto_processing_predicate(notice_id: Any, now: datetime) -> ColumnElement[bool]:
    """자동 처리 범위 SQL 술어: 마감이 지나지 않았거나(미확인 포함) 추적 중이다.

    `Notice.deadline_at`을 직접 읽으므로 호출부 질의에 `Notice`가 있어야 한다.
    """

    from ...lifecycle import pre_spec_deadline_passed_expression, tracked_notice_predicate

    return or_(
        not_(pre_spec_deadline_passed_expression(now)),
        tracked_notice_predicate(notice_id),
    )


def auto_processing_notice_ids(
    session: Any, notice_ids: Sequence[int], *, now: datetime | None = None
) -> frozenset[int]:
    """자동 처리 범위 안에 있는 공고 id. 조회는 한 번이다."""

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return frozenset()
    current = now if now is not None else _utc_now()
    return frozenset(
        int(value)
        for value in session.scalars(
            select(Notice.id).where(
                Notice.id.in_(ids), auto_processing_predicate(Notice.id, current)
            )
        ).all()
    )


def attachment_claim_scope_predicate(fetch_table: Any, now: datetime) -> ColumnElement[bool]:
    """첨부 취득 worker가 claim해도 되는 취득 행의 SQL 술어.

    취득 행 자체는 지금처럼 SW사업대상·추적 발주계획·`우선 검토` 등급에 대해
    만들어진다(`refresh_fetch_eligibility`). claim만 자동 처리 범위로 좁힌다 —
    범위 밖의 `대기` 행은 지우지도 상태를 바꾸지도 않고 그냥 claim하지 않는다.

    예외 둘은 지금 규칙 그대로 남긴다.

    * 행이 `우선 검토` 등급 때문에 생겼다(`eligibility_reason='priority_grade'`).
      등급 규칙은 바꾸지 않는다.
    * 공고가 브리핑 추천을 받았다(RL-03 결정 B18). 추천 건의 준비가 취득에서
      멈추지 않게 한다.

    운영자 로컬 원본 연결(B15)은 claim을 거치지 않으므로 여기 해당이 없다.
    """

    from ...lifecycle.models import Attachment

    briefing_recommended = exists(
        select(1).where(
            BriefingItem.notice_id == Notice.id,
            BriefingItem.kind == "recommendation",
            BriefingItem.stage == "pre_spec",
        )
    )
    in_scope_attachments = (
        select(Attachment.id)
        .join(Notice, Notice.id == Attachment.notice_id)
        .where(or_(auto_processing_predicate(Notice.id, now), briefing_recommended))
    )
    return or_(
        fetch_table.eligibility_reason == "priority_grade",
        fetch_table.attachment_id.in_(in_scope_attachments),
    )


@dataclass(frozen=True)
class OverviewEligibility:
    """자격 판정 결과.

    `eligible`은 자격이 열린 공고, `out_of_auto_scope`는 수동 경로라면 자격이
    있지만 자동 처리 범위 밖이라 자동 경로에서 빠진 공고다(목록 투영의 사유
    `deadline_passed_untracked`). 둘은 서로소다.
    """

    eligible: frozenset[int]
    out_of_auto_scope: frozenset[int]


def overview_eligibility(
    session: Any,
    notice_ids: Sequence[int],
    *,
    settings: Any | None = None,
    grades: Mapping[int, EffectiveGrade] | None = None,
    automatic: bool = True,
    now: datetime | None = None,
) -> OverviewEligibility:
    """자동 준비·개요 enqueue·문서 묶음 생성의 자격 (MVP 완화 2026-09-11, 범위 2026-11-19).

    자격은 "effective grade `우선 검토`"이고, `BIDOPS_PRESPEC_OVERVIEW_ENABLED`가
    켜져 있으면 "`SW사업대상=Y` 사전규격"이 더해진다. 운영 DB에 C-1 판정이 없어
    `우선 검토`가 0건이면 개요를 한 번도 돌릴 수 없기 때문이다. 플래그가 꺼져 있으면
    완화는 **없고** 기존 등급 규칙 그대로다.

    `automatic=True`(기본)는 자동 경로다. 플래그로 열린 `SW사업대상=Y` 자격은
    자동 처리 범위(`auto_processing_predicate`) 안의 공고에만 열린다. `우선 검토`
    등급 자격은 범위와 무관하다 — 등급 규칙은 그대로 둔다. `automatic=False`는
    사람이 누르는 경로(묶음 생성·심층 검토 생성)이며 범위를 보지 않는다.

    `grades`를 주면 그 batch 결과를 그대로 쓴다(명세 §8의 N+1 금지).
    """

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return OverviewEligibility(frozenset(), frozenset())
    resolved = grades if grades is not None else effective_grades(session, ids)
    priority = {
        notice_id
        for notice_id in ids
        if (value := resolved.get(notice_id)) is not None and value.is_priority
    }
    settings = settings if settings is not None else get_settings()
    relaxed: frozenset[int] = frozenset()
    if getattr(settings, "prespec_overview_enabled", False):
        relaxed = sw_business_notice_ids(session, [value for value in ids if value not in priority])
    if not automatic or not relaxed:
        return OverviewEligibility(frozenset(priority | relaxed), frozenset())
    in_scope = auto_processing_notice_ids(session, sorted(relaxed), now=now)
    return OverviewEligibility(
        eligible=frozenset(priority | in_scope),
        out_of_auto_scope=frozenset(relaxed - in_scope),
    )


def overview_eligible(
    session: Any,
    notice_ids: Sequence[int],
    *,
    settings: Any | None = None,
    grades: Mapping[int, EffectiveGrade] | None = None,
    automatic: bool = True,
    now: datetime | None = None,
) -> frozenset[int]:
    """자격이 열린 공고 id. 규칙은 `overview_eligibility` 한 벌이다.

    자격을 여는 곳(자동 준비, 목록 투영, 개요 enqueue, 사람의 묶음 생성)이 모두 이
    함수를 부른다 — 목록이 말하는 상태와 실제 준비 결과가 갈리지 않게 하는 것이
    이 함수의 존재 이유다.
    """

    return overview_eligibility(
        session, notice_ids, settings=settings, grades=grades, automatic=automatic, now=now
    ).eligible


def eligible_with_grade(
    session: Any,
    notice_id: int,
    grade: str | None,
    *,
    settings: Any | None = None,
) -> bool:
    """이미 자기 seam으로 읽은 등급 하나로 자격을 판정한다.

    문서 bundle 생성(`DocumentBundleService.effective_grade`)과 심층 검토 생성
    (`effective_grade_basis`)은 각자의 읽기 전용 seam으로 등급을 이미 읽는다.
    그 seam은 그대로 두고 **자격 규칙만** `overview_eligible` 한 벌로 모은다 —
    등급을 여기서 다시 조회하면 두 벌이 되고, 검사와 기록이 다른 값을 보게 된다.

    사람이 누르는 경로이므로 자동 처리 범위(마감·추적)를 보지 않는다.
    """

    notice_id = int(notice_id)
    grades = (
        {notice_id: EffectiveGrade(notice_id=notice_id, grade=grade, source=None)}
        if grade is not None
        else {}
    )
    return notice_id in overview_eligible(
        session, [notice_id], settings=settings, grades=grades, automatic=False
    )


__all__ = [
    "EffectiveGrade",
    "OverviewEligibility",
    "attachment_claim_scope_predicate",
    "auto_processing_notice_ids",
    "auto_processing_predicate",
    "overview_eligibility",
    "eligible_with_grade",
    "PRIORITY_GRADE",
    "SOURCE_HUMAN_REVIEW",
    "SOURCE_SCREENING_JUDGMENT",
    "effective_grades",
    "overview_eligible",
    "priority_notice_ids",
    "sw_business_notice_ids",
    "sw_business_object",
]
