"""lifecycle 이벤트 hook의 deep_review 구현: 첨부 fetch 자격 갱신 (명세 §6.2).

- 회차 적재됨: 그 회차에서 관측된 사전규격 공고의 첨부 자격을 재평가한다.
  실패는 savepoint 안에 가두고, 오늘 loader가 남기던 것과 같은 경고를 건수로
  돌려준다 — 회차 적재 자체를 되돌리지 않는다.
- 추적 결정 변경됨: 그 사업기회에 연결된 사전규격 공고의 첨부 자격을 재평가한다.
  별도 transaction 격리는 호출부(`PATCH /api/opportunities/{id}/tracking-status`)가
  그대로 갖고 있다.

둘 다 호출자가 넘긴 session에서 동기적으로 실행된다. lifecycle 모델은 읽기만
한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..lifecycle import RunDirectoryClaim, RunIngestCounts
from ..models import Notice, NoticeObservation, OpportunityLink
from .prespec_attachments import refresh_fetch_eligibility

#: loader가 `_record_warning`으로 남기던 경고와 같은 code·message.
REFRESH_FAILED_CODE = "attachment_eligibility_refresh_failed"
REFRESH_FAILED_MESSAGE = "사전규격 첨부 자격 재평가를 완료하지 못했습니다."


def _refresh_failed_warning(notice_count: int) -> Mapping[str, Any]:
    return {
        "level": "warning",
        "code": REFRESH_FAILED_CODE,
        "message": REFRESH_FAILED_MESSAGE,
        "context": {"notice_count": notice_count},
    }


class PreSpecAttachmentEligibilityHook:
    """`RunIngestHook`과 `TrackingDecisionHook`을 함께 제공한다."""

    # --- RunIngestHook ---
    def inspect_run_directory(self, directory: Path) -> RunDirectoryClaim | None:
        """심층 검토는 회차 디렉터리를 전용으로 주장하지 않는다."""

        return None

    def run_ingested(self, session: Any, run_id: str, directory: Path) -> RunIngestCounts:
        notice_ids = [
            int(value)
            for value in session.scalars(
                select(Notice.id)
                .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
                .where(
                    NoticeObservation.run_id == run_id,
                    Notice.source_type == "pre_spec",
                )
                .distinct()
            ).all()
        ]
        if not notice_ids:
            return RunIngestCounts()
        try:
            # IntegrityError나 dialect 문제가 회차 적재 transaction 전체를 되돌리지
            # 않도록 savepoint 안에서 돈다.
            with session.begin_nested():
                refresh_fetch_eligibility(session, notice_ids=notice_ids)
        except Exception:
            return RunIngestCounts(warnings=(_refresh_failed_warning(len(notice_ids)),))
        return RunIngestCounts()

    # --- TrackingDecisionHook ---
    def tracking_decision_changed(self, session: Any, opportunity_id: Any) -> None:
        notice_ids = session.scalars(
            select(Notice.id)
            .join(OpportunityLink, OpportunityLink.notice_id == Notice.id)
            .where(
                OpportunityLink.opportunity_id == opportunity_id,
                OpportunityLink.stage == "notice",
                Notice.source_type == "pre_spec",
            )
        ).all()
        refresh_fetch_eligibility(session, notice_ids=notice_ids)


__all__ = [
    "PreSpecAttachmentEligibilityHook",
    "REFRESH_FAILED_CODE",
    "REFRESH_FAILED_MESSAGE",
]
