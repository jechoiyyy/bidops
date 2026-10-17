"""RL-03 연결: 활동 피드·브리핑 판정 표시·Slack 스레드 답글 (spec "연결", STEP-008).

세 가지 모두 card-v1 판정(실회사 RL 경로)의 **저장된** 결과만 읽는다. 모델·네트워크를 부르는
것은 Slack 답글 하나뿐이고, 그것도 core 전송기(`core/slack.py`)의 호출 전 검사를 지난다.

- 활동 피드(lifecycle hook `opportunity_activity_items`): 사업기회에 권위 연결된 사전규격의
  `completed` attempt마다 `verdict_completed` 1건("판정 완료 · <판정>", 판정 탭 링크). 실패·진행
  중 attempt는 항목이 아니다(시스템 사건 아님, 화면 상태로만).
- 브리핑 판정 표시(lifecycle projection `briefing_verdict_display`, `bidops.briefing.v2`):
  사전규격은 최신 attempt가 대기·실행 중이면 `분석 중`, 아니면 최신 `completed` attempt의 판정
  이름, 둘 다 없으면 `분석 대기`; 입찰공고는 같은 사업기회의 권위 연결 사전규격(최신 연결)에
  completed 판정이 있으면 `사전규격 판정 참조`, 없으면 `판정 대상 아님`.
- Slack 스레드(`notify_verdict_completed`): attempt가 `completed`가 된 직후 worker가 한 번
  부른다. 그 사전규격의 최신 브리핑 추천 항목에 `slack_message_ts`가 있으면 그 메시지 스레드에
  "판정 완료 · <판정> · 확인할 것 n" 한 줄을 단다(n = 대조 결과 `unknown`(확인 필요) 요구사항
  수). ts가 없거나(토큰 없음·미게시) 전송기 검사가 막으면 건너뛰며 오류가 아니다(D5). 실패한
  attempt는 부르지 않는다. 답글 실패는 판정 결과에 영향을 주지 않는다(재시도 없음).

`BIDOPS_RL_ANALYSIS_ENABLED`가 꺼져 있거나 실회사가 없으면 피드·표시는 아무것도 주지 않는다
(브리핑은 RL-01 v1 규칙으로 돌아간다). 조회는 넘긴 공고 수와 무관한 상수 회다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any, get_args
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.slack import SlackSender, SlackTransportError
from ...lifecycle import active_opportunity_predicate, authoritative_link_predicate
from ...lifecycle.models import Company, Notice, OpportunityLink
from ...lifecycle.schemas.opportunity_activity import ActivityItem, ActivityLink
from ..models import AnalysisPolicyVersion, CardAnalysisStage, DeepReview, DeepReviewApproval, DeepReviewAttempt
from ..schemas.card_analysis import CardAssembledPractitionerVerdict, PractitionerVerdictValue
from .company_deep_review import rl_path
from .deep_reviews import _policy_payload
from .verdict_trigger import PRE_SPEC_SOURCE_TYPES, latest_recommendation, real_company


logger = logging.getLogger(__name__)

#: 판정 표시 글자(브리핑 v2가 v1에 더한 입찰공고용 2값과 v1 값).
DISPLAY_RUNNING = "분석 중"
DISPLAY_WAITING = "분석 대기"
DISPLAY_PRE_SPEC_REFERENCE = "사전규격 판정 참조"
DISPLAY_NOT_TARGET = "판정 대상 아님"
BID_NOTICE_SOURCE_TYPE = "bid_notice"

#: 활동 피드 항목의 판정 탭 링크 문구.
ACTIVITY_LINK_LABEL = "판정 보기"

#: Slack 답글 결과(테스트·로그용 안전한 code). `posted` 외에는 답글을 보내지 않았다.
NOTIFY_POSTED = "posted"
NOTIFY_NOT_COMPLETED = "not_completed"
NOTIFY_NOT_CARD = "not_card_attempt"
NOTIFY_VERDICT_MISSING = "verdict_missing"
NOTIFY_NO_BRIEFING_ITEM = "no_briefing_item"
NOTIFY_NOT_POSTED = "briefing_not_posted"


@dataclass(frozen=True)
class _CardAttempt:
    notice_id: int
    attempt: DeepReviewAttempt
    approved_at: datetime


@dataclass(frozen=True)
class _FinalVerdict:
    verdict: str
    unknown_count: int


def _rl_company(session: Session, settings: Any) -> Company | None:
    company = real_company(session)
    return company if rl_path(settings, company) else None


def _card_attempts(session: Session, company_id: UUID, notice_ids: Iterable[int]) -> list[_CardAttempt]:
    """card-v1 정책 review의 attempt(승인 시각 포함). 공고 수와 무관하게 3회 조회."""

    ids = sorted({int(value) for value in notice_ids})
    if not ids:
        return []
    reviews = session.execute(
        select(DeepReview.id, DeepReview.notice_id, DeepReview.policy_version_id).where(
            DeepReview.company_id == company_id, DeepReview.notice_id.in_(ids),
        )
    ).all()
    policy_ids = {row.policy_version_id for row in reviews}
    if not policy_ids:
        return []
    card_policies = {
        policy.id
        for policy in session.scalars(select(AnalysisPolicyVersion).where(AnalysisPolicyVersion.id.in_(policy_ids)))
        if _policy_payload(policy).get("pipeline_version") == "card-v1"
    }
    notice_of_review = {row.id: int(row.notice_id) for row in reviews if row.policy_version_id in card_policies}
    if not notice_of_review:
        return []
    rows = session.execute(
        select(DeepReviewAttempt, DeepReviewApproval.approved_at)
        .join(DeepReviewApproval, DeepReviewApproval.attempt_id == DeepReviewAttempt.id)
        .where(DeepReviewAttempt.deep_review_id.in_(list(notice_of_review)))
    ).all()
    return [
        _CardAttempt(notice_of_review[attempt.deep_review_id], attempt, approved_at)
        for attempt, approved_at in rows
    ]


def _final_verdicts(session: Session, attempt_ids: Iterable[UUID]) -> dict[UUID, _FinalVerdict]:
    """검증된 `synthesis`/`final` 행의 판정 이름과 `unknown` 요구사항 수. 깨진 행은 빠진다."""

    ids = list({value for value in attempt_ids})
    if not ids:
        return {}
    out: dict[UUID, _FinalVerdict] = {}
    for row in session.scalars(
        select(CardAnalysisStage).where(
            CardAnalysisStage.attempt_id.in_(ids),
            CardAnalysisStage.stage == "synthesis",
            CardAnalysisStage.stage_key == "final",
        )
    ):
        try:
            final = CardAssembledPractitionerVerdict.model_validate(
                row.payload if isinstance(row.payload, Mapping) else {}
            )
        except (ValidationError, TypeError, ValueError):
            # 저장 행이 계약과 다르면 표시하지 않는다(보정하지 않는다).
            continue
        out[row.attempt_id] = _FinalVerdict(
            verdict=final.verdict,
            unknown_count=sum(1 for item in final.matrix if item.fit_status == "unknown"),
        )
    return out


def _newest_first(rows: Sequence[_CardAttempt]) -> list[_CardAttempt]:
    return sorted(rows, key=lambda row: (row.approved_at, str(row.attempt.id)), reverse=True)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# --- 활동 피드 ----------------------------------------------------------------------------


def _opportunity_pre_spec_ids(session: Session, opportunity_id: int) -> list[int]:
    return [
        int(value)
        for value in session.scalars(
            select(OpportunityLink.notice_id)
            .join(Notice, Notice.id == OpportunityLink.notice_id)
            .where(
                OpportunityLink.opportunity_id == int(opportunity_id),
                OpportunityLink.stage == "notice",
                authoritative_link_predicate(),
                Notice.source_type.in_(PRE_SPEC_SOURCE_TYPES),
            )
        )
        if value is not None
    ]


def verdict_activity_items(
    session: Session, opportunity_id: int, *, settings: Any = None
) -> list[ActivityItem]:
    """사업기회 하나의 `verdict_completed` 항목(completed attempt마다 1건)."""

    settings = settings or get_settings()
    company = _rl_company(session, settings)
    if company is None:
        return []
    notice_ids = _opportunity_pre_spec_ids(session, opportunity_id)
    completed = [
        row for row in _card_attempts(session, company.id, notice_ids)
        if row.attempt.status == "completed" and row.attempt.completed_at is not None
    ]
    verdicts = _final_verdicts(session, (row.attempt.id for row in completed))
    items: list[ActivityItem] = []
    for row in completed:
        final = verdicts.get(row.attempt.id)
        if final is None:
            continue
        items.append(
            ActivityItem(
                item_id=f"verdict_completed:{row.attempt.id}",
                kind="verdict_completed",
                at=_aware(row.attempt.completed_at).astimezone(UTC),
                actor=None,
                title=f"판정 완료 · {final.verdict}",
                link=ActivityLink(label=ACTIVITY_LINK_LABEL, path=f"/opportunities/{int(opportunity_id)}/verdict"),
            )
        )
    return items


class RLVerdictActivityProvider:
    """lifecycle 확장점 `opportunity_activity_items`의 deep_review 제공자 (읽기 전용)."""

    def opportunity_activity_items(self, session: Any, opportunity_id: int) -> list[ActivityItem]:
        return verdict_activity_items(session, opportunity_id)


# --- 브리핑 판정 표시 -------------------------------------------------------------------


def _pre_spec_displays(session: Session, company_id: UUID, notice_ids: Sequence[int]) -> dict[int, str]:
    attempts = _card_attempts(session, company_id, notice_ids)
    by_notice: dict[int, list[_CardAttempt]] = {}
    for row in attempts:
        by_notice.setdefault(row.notice_id, []).append(row)
    verdicts = _final_verdicts(
        session, (row.attempt.id for row in attempts if row.attempt.status == "completed")
    )
    out: dict[int, str] = {}
    for notice_id in notice_ids:
        rows = _newest_first(by_notice.get(int(notice_id), []))
        if rows and rows[0].attempt.status in {"queued", "running"}:
            out[int(notice_id)] = DISPLAY_RUNNING
            continue
        verdict = next(
            (
                verdicts[row.attempt.id].verdict
                for row in rows
                if row.attempt.status == "completed" and row.attempt.id in verdicts
            ),
            None,
        )
        out[int(notice_id)] = verdict if verdict is not None else DISPLAY_WAITING
    return out


def _linked_pre_specs(session: Session, bid_notice_ids: Sequence[int]) -> dict[int, int]:
    """입찰공고 → 같은 (활성) 사업기회의 권위 연결 사전규격(최신 연결 `created_at`, 그다음 id)."""

    if not bid_notice_ids:
        return {}
    owners: dict[int, int] = {}
    for notice_id, opportunity_id in session.execute(
        select(OpportunityLink.notice_id, OpportunityLink.opportunity_id)
        .where(
            OpportunityLink.notice_id.in_(list(bid_notice_ids)),
            authoritative_link_predicate(),
            active_opportunity_predicate(),
        )
        .order_by(OpportunityLink.created_at.desc(), OpportunityLink.id.desc())
    ).all():
        owners.setdefault(int(notice_id), int(opportunity_id))
    if not owners:
        return {}
    newest_pre_spec: dict[int, int] = {}
    for opportunity_id, notice_id in session.execute(
        select(OpportunityLink.opportunity_id, OpportunityLink.notice_id)
        .join(Notice, Notice.id == OpportunityLink.notice_id)
        .where(
            OpportunityLink.opportunity_id.in_(sorted(set(owners.values()))),
            OpportunityLink.stage == "notice",
            authoritative_link_predicate(),
            Notice.source_type.in_(PRE_SPEC_SOURCE_TYPES),
        )
        .order_by(OpportunityLink.created_at.desc(), OpportunityLink.id.desc())
    ).all():
        newest_pre_spec.setdefault(int(opportunity_id), int(notice_id))
    return {
        bid_id: newest_pre_spec[opportunity_id]
        for bid_id, opportunity_id in owners.items()
        if opportunity_id in newest_pre_spec
    }


def briefing_verdict_displays(
    session: Session, notice_ids: Sequence[int], *, settings: Any = None
) -> dict[int, str]:
    """브리핑 추천 항목 공고 → 판정 표시 글자(`bidops.briefing.v2`)."""

    settings = settings or get_settings()
    ids = sorted({int(value) for value in notice_ids})
    if not ids:
        return {}
    company = _rl_company(session, settings)
    if company is None:
        return {}
    source_types = dict(session.execute(select(Notice.id, Notice.source_type).where(Notice.id.in_(ids))).all())
    pre_specs = [notice_id for notice_id in ids if source_types.get(notice_id) in PRE_SPEC_SOURCE_TYPES]
    bids = [notice_id for notice_id in ids if source_types.get(notice_id) == BID_NOTICE_SOURCE_TYPE]
    linked = _linked_pre_specs(session, bids)
    displays = _pre_spec_displays(session, company.id, sorted(set(pre_specs) | set(linked.values())))
    verdict_names = set(get_args(PractitionerVerdictValue))
    out = {notice_id: displays[notice_id] for notice_id in pre_specs}
    for bid_id in bids:
        pre_spec_id = linked.get(bid_id)
        has_verdict = pre_spec_id is not None and displays.get(pre_spec_id) in verdict_names
        out[bid_id] = DISPLAY_PRE_SPEC_REFERENCE if has_verdict else DISPLAY_NOT_TARGET
    return out


class RLBriefingVerdictDisplay:
    """lifecycle 확장점 `briefing_verdict_display`의 deep_review 제공자 (읽기 전용)."""

    def briefing_verdict_display(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, str]:
        return briefing_verdict_displays(session, notice_ids)


# --- Slack 스레드 답글 ------------------------------------------------------------------


def thread_reply_text(verdict: str, unknown_count: int) -> str:
    return f"판정 완료 · {verdict} · 확인할 것 {int(unknown_count)}"


def notify_verdict_completed(
    session: Session,
    attempt_id: UUID,
    *,
    sender: SlackSender | None = None,
    settings: Any = None,
) -> str:
    """completed card attempt 하나의 판정 완료 답글. 결과 code를 돌려주고 예외를 내지 않는다.

    `slack_message_ts`가 없으면(토큰 없음·미게시) 전송기를 만들지도 않고 건너뛴다. 전송기
    검사(`slack_disabled`·`token_missing`·`channel_missing`·`host_not_allowed`)가 막으면 그 사유를
    돌려주며 네트워크에 닿지 않는다. Slack 오류는 안전한 code로만 남긴다(토큰·응답 본문 없음).
    """

    try:
        attempt = session.get(DeepReviewAttempt, attempt_id)
        if attempt is None or attempt.status != "completed":
            return NOTIFY_NOT_COMPLETED
        review = session.get(DeepReview, attempt.deep_review_id)
        policy = session.get(AnalysisPolicyVersion, review.policy_version_id) if review is not None else None
        if review is None or policy is None or _policy_payload(policy).get("pipeline_version") != "card-v1":
            return NOTIFY_NOT_CARD
        final = _final_verdicts(session, [attempt.id]).get(attempt.id)
        if final is None:
            return NOTIFY_VERDICT_MISSING
        item = latest_recommendation(session, int(review.notice_id))
        if item is None:
            return NOTIFY_NO_BRIEFING_ITEM
        thread_ts = (item.slack_message_ts or "").strip()
        if not thread_ts:
            return NOTIFY_NOT_POSTED
        if sender is None:
            sender = SlackSender.from_settings(settings or get_settings())
        reason = sender.preflight()
        if reason is not None:
            return reason
        sender.post_thread_reply(
            channel=sender.channel_id, thread_ts=thread_ts,
            text=thread_reply_text(final.verdict, final.unknown_count),
        )
        return NOTIFY_POSTED
    except SlackTransportError as error:
        logger.warning("verdict thread reply failed: attempt=%s code=%s", attempt_id, error.code)
        return error.code
    except Exception as error:  # 답글 실패가 판정 완료를 되돌리면 안 된다
        logger.warning("verdict thread reply failed: attempt=%s error=%s", attempt_id, type(error).__name__)
        return "processing_failed"


__all__ = [
    "ACTIVITY_LINK_LABEL",
    "DISPLAY_NOT_TARGET",
    "DISPLAY_PRE_SPEC_REFERENCE",
    "DISPLAY_RUNNING",
    "DISPLAY_WAITING",
    "NOTIFY_POSTED",
    "RLBriefingVerdictDisplay",
    "RLVerdictActivityProvider",
    "briefing_verdict_displays",
    "notify_verdict_completed",
    "thread_reply_text",
    "verdict_activity_items",
]
