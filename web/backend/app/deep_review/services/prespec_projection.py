"""사전규격 개요·문서 projection의 deep_review 구현 (명세 §6.1 둘째 행).

lifecycle의 `GET /api/pre-specs`는 누적 목록이라 회차 상한이 없다. 그래서 세
메서드 모두 호출부가 넘긴 `notice_ids`를 batch projection으로 처리하고,
공고 수에 따라 조회를 늘리지 않는다. 개요 상태는 v4 current batch를 먼저 읽고
current가 없는 공고에만 legacy 상태를 적용한다. 없는 공고는 빠뜨린다 —
`None`/0으로 채우는 것은 lifecycle의 몫이다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select

from ...core.constants import prespec_overview_status_from_v4
from ...lifecycle import PreSpecDocumentCounts, WorkloadCount
from ..models import AttachmentFetch, PreSpecOverviewReview
from ...lifecycle.models import Attachment, Notice
from .auto_preparation import auto_preparation_fields
from .company_fit import current_v4_projections

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
        """Return one current status per notice using one batch v4 projection."""

        ids = _distinct_ids(notice_ids)
        if not ids:
            return {}
        current = current_v4_projections(session, ids)
        legacy = {
            int(notice_id): status
            for notice_id, status in session.execute(
                select(PreSpecOverviewReview.notice_id, PreSpecOverviewReview.status).where(
                    PreSpecOverviewReview.notice_id.in_(ids)
                )
            ).all()
        }
        statuses: dict[int, str] = {}
        for notice_id in ids:
            projection = current.get(notice_id)
            statuses[notice_id] = (
                prespec_overview_status_from_v4(projection.get("status"))
                if projection is not None
                else legacy.get(notice_id)
            )
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
        return auto_preparation_fields(session, ids)

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


class DeepReviewWorkloadProjection:
    """deep_review가 소유한 업무 건수. 대상이 없으면 실제 0이다."""

    def workload_counts(self, session: Any) -> Mapping[str, WorkloadCount]:
        from .decision_queue import decision_queue

        notice_ids = session.scalars(select(Notice.id).where(Notice.source_type == "pre_spec")).all()
        ready = PreSpecOverviewDocumentProjection().notice_ids_for_auto_preparation_status(
            session, notice_ids, "deep_review_ready_for_click"
        )
        return {
            "pre_spec_deep_review_ready": WorkloadCount(len(ready)),
            "bid_final_decision_pending": WorkloadCount(decision_queue(session, limit=1)["total"]),
        }


__all__ = ["DeepReviewWorkloadProjection", "PreSpecOverviewDocumentProjection"]
