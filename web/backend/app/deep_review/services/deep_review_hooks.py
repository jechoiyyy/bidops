"""lifecycle 이벤트 hook의 deep_review 구현: 첨부 fetch 자격 갱신 (명세 §6.2).

- 회차 적재됨: 그 회차에서 관측된 사전규격 공고의 첨부 자격을 재평가한다.
  실패는 savepoint 안에 가두고, 오늘 loader가 남기던 것과 같은 경고를 건수로
  돌려준다 — 회차 적재 자체를 되돌리지 않는다.
- 추적 결정 변경됨: 그 사업기회에 연결된 사전규격 공고의 첨부 자격을 재평가한다.
  별도 transaction 격리는 호출부(`PATCH /api/opportunities/{id}/tracking-status`)가
  그대로 갖고 있다.
- effective grade 변경됨: 사람 리뷰가 정정 등급을 바꾼 공고의 첨부 자격을
  재평가한다(명세 §6.2 둘째 촉발). 리뷰 저장과 같은 transaction에서 불리므로
  자기 실패를 savepoint 안에 가둔다 — 형제 hook의 쓰기도 리뷰 저장도 되돌리지
  않는다.

둘 다 호출자가 넘긴 session에서 동기적으로 실행된다. lifecycle 모델은 읽기만
한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ...lifecycle import RunDirectoryClaim, RunIngestCounts
from ...lifecycle.models import Notice, NoticeObservation, OpportunityLink
from .auto_preparation import maybe_auto_prepare
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
    """`RunIngestHook`·`TrackingDecisionHook`·`EffectiveGradeChangedHook`을 함께 제공한다."""

    # --- RunIngestHook ---
    def inspect_run_directory(self, directory: Path) -> RunDirectoryClaim | None:
        """심층 검토는 회차 디렉터리를 전용으로 주장하지 않는다."""

        return None

    def run_ingested(
        self,
        session: Any,
        run_id: str,
        directory: Path,
        *,
        reports_root: Path | None = None,
    ) -> RunIngestCounts:
        """회차의 사전규격 공고에 대해 첨부 취득 자격을 다시 계산한다.

        `reports_root`는 판정 계약 산출물을 보고서 트리에서 찾는 hook을 위한
        것이라 여기서는 쓰지 않는다. 확장점 서명의 일부이므로 받기만 한다.
        """

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
        # 자격을 다시 센 뒤 자동 문서 준비 조건을 본다(명세 §6.2). 같은 문서
        # 집합이면 아무 일도 하지 않고, 새 bytes가 들어왔으면 새 revision을
        # 만들어 확정한다. 자기 실패는 이 함수 안에서 삼킨다.
        maybe_auto_prepare(session, notice_ids, run_id=run_id)
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

    # --- EffectiveGradeChangedHook (§6.2 둘째 촉발) ---
    def effective_grade_changed(self, session: Any, notice_ids: Sequence[int]) -> None:
        """정정 등급이 바뀐 공고의 첨부 취득 자격을 다시 계산한다.

        리뷰 저장 transaction 안에서 불리므로 **자기 실패를 savepoint에 가둔다**.
        등급이 올라가면 새 취득 행이 생기고, 내려가면 아무것도 취소하지 않는다 —
        `refresh_fetch_eligibility`가 기존 행을 되돌리지 않기 때문이다(§6.2).
        """

        targets = [
            int(value)
            for value in session.scalars(
                select(Notice.id).where(
                    Notice.id.in_([int(value) for value in notice_ids]),
                    Notice.source_type == "pre_spec",
                )
            ).all()
        ]
        if not targets:
            return
        try:
            with session.begin_nested():
                refresh_fetch_eligibility(session, notice_ids=targets)
        except Exception:
            # 예외 본문은 여기서 버린다. 원인은 안전한 code로만 남고 리뷰 저장은
            # 그대로 유지된다(§6.2).
            return
        maybe_auto_prepare(session, targets)


__all__ = [
    "PreSpecAttachmentEligibilityHook",
    "REFRESH_FAILED_CODE",
    "REFRESH_FAILED_MESSAGE",
]
