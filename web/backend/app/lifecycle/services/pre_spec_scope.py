"""사전규격의 "의견 마감 경과"와 "추적 중" 술어 (lifecycle).

두 술어는 lifecycle 개념이다. 마감 경과는 사전규격 목록의 `deadline_scope`
(ADR-0064)가, 추적 중은 목록의 `추적 중` 보기(계속 추적·보류)가 이미 쓰는 뜻이다.
deep_review의 자동 처리 범위(첨부 취득 claim·자동 문서 준비·자동 개요 enqueue,
2026-11-19 사전규격 단계 수정안 §3 A)가 **같은 뜻**을 써야 목록이 말하는 범위와
실제 자동 처리 범위가 갈리지 않는다. 그래서 router 안에 있던 마감 술어를 여기로
옮기고 형제 모듈에 공개한다.

비교는 SQL이 한다 — 파이썬에서 naive/aware datetime을 섞어 비교하지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, exists, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from ..models import Notice, Opportunity, OpportunityLink
from .opportunity_integrity import active_opportunity_predicate, authoritative_link_predicate

#: `추적 중`으로 읽는 사업기회 추적 상태. 사전규격 목록의 `tracking` 보기와
#: 추적 발주계획 연결(`opportunity_connections._TRACKING_STATUSES`)과 같은 값이다.
TRACKING_ACTIVE_STATUSES: tuple[str, ...] = ("계속 추적", "보류")


def deadline_passed_expression(now: datetime, deadline_column: Any = None) -> ColumnElement[bool]:
    """SQL로 평가하는 "의견등록 마감이 지났다" 술어 (ADR-0064).

    `deadline_at`이 null이면 false다 — 마감 미확인은 마감 경과로 접지 않는다.
    """

    column = Notice.deadline_at if deadline_column is None else deadline_column
    return and_(column.is_not(None), column < now)


def tracked_notice_predicate(notice_id: Any) -> ColumnElement[bool]:
    """공고의 소유 사업기회가 `추적 중`(계속 추적·보류)인가.

    소유 사업기회를 고르는 규칙은 목록과 같은 공개 술어 두 개(권위 연결·활성
    사업기회)다. 새로 정의하지 않는다.
    """

    link = aliased(OpportunityLink)
    opportunity = aliased(Opportunity)
    return exists(
        select(1)
        .select_from(link)
        .join(opportunity, opportunity.id == link.opportunity_id)
        .where(
            link.notice_id == notice_id,
            link.stage == "notice",
            authoritative_link_predicate(link),
            active_opportunity_predicate(opportunity),
            opportunity.tracking_status.in_(TRACKING_ACTIVE_STATUSES),
        )
    )


__all__ = [
    "TRACKING_ACTIVE_STATUSES",
    "deadline_passed_expression",
    "tracked_notice_predicate",
]
