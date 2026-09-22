"""사전규격 개요·문서 projection의 deep_review 구현 (명세 §6.1 둘째 행).

lifecycle의 `GET /api/pre-specs`는 누적 목록이라 회차 상한이 없다. 그래서 세
메서드 모두 호출부가 넘긴 `notice_ids`를 batch projection으로 처리하고,
공고 수에 따라 조회를 늘리지 않는다. 개요 상태는 공고별 최신 run 하나이며,
run이 없는 공고는 빠뜨린다 — `None`/0으로 채우는 것은 lifecycle의 몫이다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select

from ...lifecycle import (
    PreSpecDocumentCounts,
    WorkloadCount,
    active_opportunity_predicate,
    authoritative_link_predicate,
)
from ..models import AttachmentFetch
from ...lifecycle.models import Attachment, Notice, Opportunity, OpportunityLink
from .auto_preparation import auto_preparation_fields
from .display_assessment import display_assessments
from .overview_runs import current_runs, overview_status_for

# attachment_fetch.status 값 → PreSpecDocumentCounts 필드. 응답 별칭(완료·대기·
# 진행·차단·실패)은 lifecycle의 응답 모델이 붙인다.
_FETCH_STATUS_FIELDS: Mapping[str, str] = {
    "완료": "completed",
    "대기": "pending",
    "진행": "running",
    "차단": "blocked",
    "실패": "failed",
}


def _distinct_ids(notice_ids: Sequence[int]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(int(value) for value in notice_ids))


class PreSpecOverviewDocumentProjection:
    """`OverviewDocumentProjection` 제공자."""

    def _overview_statuses(
        self, session: Any, notice_ids: Sequence[int]
    ) -> dict[int, str]:
        """공고별 최신 개요 run의 상태 하나. batch 조회 한 번이다."""

        ids = _distinct_ids(notice_ids)
        if not ids:
            return {}
        runs = current_runs(session, ids)
        statuses = {notice_id: overview_status_for(runs.get(notice_id)) for notice_id in ids}
        return {notice_id: status for notice_id, status in statuses.items() if status is not None}

    def overview_status(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, str]:
        return self._overview_statuses(session, notice_ids)

    def overview_status_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[str, int]:
        return dict(Counter(self._overview_statuses(session, notice_ids).values()))

    def document_counts(
        self, session: Any, notice_ids: Sequence[int]
    ) -> Mapping[int, PreSpecDocumentCounts]:
        ids = _distinct_ids(notice_ids)
        if not ids:
            return {}
        # 은퇴한 첨부의 취득 행은 세지 않는다. lifecycle이 `attachments`를 셀 때와
        # 같은 조건이라 두 숫자의 모집단이 같다.
        rows = session.execute(
            select(
                Attachment.notice_id,
                AttachmentFetch.status,
                func.count(AttachmentFetch.id),
            )
            .join(Attachment, Attachment.id == AttachmentFetch.attachment_id)
            .where(Attachment.notice_id.in_(ids), Attachment.retired_at.is_(None))
            .group_by(Attachment.notice_id, AttachmentFetch.status)
        ).all()
        grouped: dict[int, dict[str, int]] = {}
        for notice_id, status, count in rows:
            field = _FETCH_STATUS_FIELDS.get(status)
            if field is None:
                continue
            grouped.setdefault(int(notice_id), {})[field] = int(count or 0)
        return {
            notice_id: PreSpecDocumentCounts(**fields) for notice_id, fields in grouped.items()
        }

    def prespec_status_fields(
        self, session: Any, notice_ids: Sequence[int]
    ) -> Mapping[int, Mapping[str, Any]]:
        """등급·자동 준비 상태·최신 심층 검토 (명세 §8).

        계산은 자동 준비 서비스가 갖는다. projection은 확장점 서명을 맞추고
        결과를 그대로 넘긴다 — 상태의 뜻을 두 곳에서 정의하지 않는다.
        """

        ids = _distinct_ids(notice_ids)
        if not ids:
            return {}
        fields = {notice_id: dict(value) for notice_id, value in auto_preparation_fields(session, ids).items()}
        runs = current_runs(session, ids)
        assessments = display_assessments(session, ids, latest_runs=runs)
        for notice_id in ids:
            fields.setdefault(notice_id, {})["display_assessment"] = assessments[notice_id]
        return fields

    def notice_ids_for_auto_preparation_status(
        self, session: Any, notice_ids: Sequence[int], status: str
    ) -> Sequence[int]:
        ids = _distinct_ids(notice_ids)
        if not ids:
            return []
        fields = auto_preparation_fields(session, ids)
        return [
            notice_id
            for notice_id in ids
            if fields.get(notice_id, {}).get("auto_preparation_status") == status
        ]


#: `사람 확인 필요` 패널의 개요 하위 건수가 세는 상태. 두 상태는 서로 배타적이라
#: 사전규격 목록 `overview_view=failed`·`overview_view=attention`의 `total` 합과 같다
#: (ADR-0067 §7.1). `pending` 계열과 run 부재(`null`)는 사람을 기다리지 않는다.
_HUMAN_REVIEW_OVERVIEW_STATUSES = ("failed", "needs_human_review")

#: 사람이 추적 결정을 내리지 않은 상태. lifecycle 목록의 `검토할 항목`
#: 술어(`routers/pre_specs._tracking_decision_absent`)와 같은 값이다.
_TRACKING_DECISION_ABSENT = ("미선택",)


def _tracking_decided_notice_ids(session: Any, notice_ids: Sequence[int]) -> set[int]:
    """사람이 추적 결정(`계속 추적`·`보류`·`종료`)을 내린 공고 id. batch 한 번이다.

    소유 사업기회를 고르는 규칙은 lifecycle이 공개한 두 술어 그대로이며
    (`GET /api/pre-specs`가 쓰는 것과 같다) 여기서 새로 정의하지 않는다.
    """

    ids = _distinct_ids(notice_ids)
    if not ids:
        return set()
    rows = session.execute(
        select(OpportunityLink.notice_id, Opportunity.tracking_status)
        .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
        .where(
            OpportunityLink.notice_id.in_(ids),
            OpportunityLink.stage == "notice",
            authoritative_link_predicate(),
            active_opportunity_predicate(),
        )
    ).all()
    return {
        int(notice_id)
        for notice_id, status in rows
        if status is not None and status not in _TRACKING_DECISION_ABSENT
    }


class DeepReviewWorkloadProjection:
    """deep_review가 소유한 업무 건수. 대상이 없으면 실제 0이다."""

    def workload_counts(self, session: Any) -> Mapping[str, WorkloadCount]:
        from .decision_queue import decision_queue

        notice_ids = session.scalars(select(Notice.id).where(Notice.source_type == "pre_spec")).all()
        projection = PreSpecOverviewDocumentProjection()
        ready = projection.notice_ids_for_auto_preparation_status(
            session, notice_ids, "deep_review_ready_for_click"
        )
        # 2026-09-22 개정(시안 M7 ③): 사람이 추적 결정을 내린 공고는 이유 불문
        # `검토할 항목`에서 빠지므로 이 건수에서도 빠진다 — 타일 건수와 목록의
        # 모집단을 같게 유지한다(ADR-0067). 검토 제외(`review_exclusion`)는
        # 예전처럼 업무 집계를 바꾸지 않는다.
        decided = _tracking_decided_notice_ids(session, ready)
        statuses = projection.overview_status_counts(session, notice_ids)
        return {
            "pre_spec_deep_review_ready": WorkloadCount(
                sum(1 for notice_id in ready if int(notice_id) not in decided)
            ),
            "bid_final_decision_pending": WorkloadCount(decision_queue(session, limit=1)["total"]),
            "overview_human_review": WorkloadCount(
                sum(int(statuses.get(status, 0)) for status in _HUMAN_REVIEW_OVERVIEW_STATUSES)
            ),
        }


__all__ = ["DeepReviewWorkloadProjection", "PreSpecOverviewDocumentProjection"]
