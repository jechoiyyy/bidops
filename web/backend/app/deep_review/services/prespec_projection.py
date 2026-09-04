"""사전규격 개요·문서 projection의 deep_review 구현 (명세 §6.1 둘째 행).

lifecycle의 `GET /api/pre-specs`는 누적 목록이라 회차 상한이 없다. 그래서 세
메서드 모두 호출부가 넘긴 `notice_ids` 만큼을 **한 번의 조회**로 처리하고,
공고당 조회를 만들지 않는다. 없는 공고는 빠뜨린다 — `None`/0으로 채우는 것은
lifecycle의 몫이다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select

from ...lifecycle import PreSpecDocumentCounts
from ..models import AttachmentFetch, PreSpecOverviewReview
from ...lifecycle.models import Attachment

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

    def overview_status(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, str]:
        ids = _distinct_ids(notice_ids)
        if not ids:
            return {}
        # prespec_overview_review는 notice_id가 unique라 공고당 최대 한 행이다.
        rows = session.execute(
            select(PreSpecOverviewReview.notice_id, PreSpecOverviewReview.status).where(
                PreSpecOverviewReview.notice_id.in_(ids)
            )
        ).all()
        return {int(notice_id): status for notice_id, status in rows}

    def overview_status_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[str, int]:
        ids = _distinct_ids(notice_ids)
        if not ids:
            return {}
        rows = session.execute(
            select(
                PreSpecOverviewReview.status,
                func.count(func.distinct(PreSpecOverviewReview.notice_id)),
            )
            .where(PreSpecOverviewReview.notice_id.in_(ids))
            .group_by(PreSpecOverviewReview.status)
        ).all()
        return {status: int(count or 0) for status, count in rows}

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


__all__ = ["PreSpecOverviewDocumentProjection"]
