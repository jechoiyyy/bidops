"""평일 브리핑 REST 계약 `bidops.briefing.v1` (RL-01 spec "REST").

응답에는 운영 정보(`score`·`policy_sha256`·`graph_version_id`)를 넣지 않는다. 키는
spec 목록 그대로이며 더하거나 빼지 않는다.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, StrictStr

from ...core.schema_base import AwareDateTime, RuntimeContractModel

BRIEFING_SCHEMA_VERSION = "bidops.briefing.v1"
BRIEFING_SLACK_PREVIEW_SCHEMA_VERSION = "bidops.briefing-slack-preview.v1"

BriefingStatus = Literal["generated", "empty", "collection_incomplete"]
BriefingItemKind = Literal["recommendation", "tracked_change"]
BriefingStage = Literal["pre_spec", "bid_notice", "order_plan"]
BriefingDeadlineKind = Literal["bid_close", "opinion_close", "planned_month"]
BriefingReaction = Literal["대기", "채택", "무시", "나중에"]
BriefingReactionVia = Literal["screen", "slack"]
#: v1에서 닫힌 다섯 값. RL-03이 판정 enum을 더해 v2로 올린다.
BriefingVerdictDisplay = Literal["분석 대기", "연차 추적", "재검토 중", "마감 임박", "분석 중"]


class BriefingReason(RuntimeContractModel):
    """추천 이유 칩. `keyword`·`repeat_agency`는 `text`, `similar_project`는 `count`."""

    kind: Literal["keyword", "similar_project", "repeat_agency"]
    text: StrictStr | None = None
    count: StrictInt | None = Field(default=None, ge=1)


class BriefingBlocking(RuntimeContractModel):
    kind: Literal["consortium_review", "deadline_short"]
    text: StrictStr


class BriefingItemView(RuntimeContractModel):
    item_id: UUID
    kind: BriefingItemKind
    rank: StrictInt | None = Field(ge=1)
    stage: BriefingStage
    notice_id: StrictInt | None
    order_plan_id: StrictInt | None
    opportunity_id: StrictInt = Field(ge=1)
    title: StrictStr
    agency: StrictStr
    amount_krw: StrictInt | None
    deadline_at: AwareDateTime | None
    deadline_kind: BriefingDeadlineKind | None
    planned_month: StrictStr | None
    verdict_display: BriefingVerdictDisplay
    reasons: list[BriefingReason]
    blocking: list[BriefingBlocking]
    change_fields: list[StrictStr]
    reaction: BriefingReaction | None
    reacted_by: StrictStr | None
    reacted_at: AwareDateTime | None
    reacted_via: BriefingReactionVia | None
    revision: StrictInt = Field(ge=0)
    record_path: StrictStr


class BriefingView(RuntimeContractModel):
    schema_version: Literal["bidops.briefing.v1"]
    briefing_date: date
    status: BriefingStatus
    generated_at: AwareDateTime
    #: 추천 수만(추적 변화 제외).
    item_count: StrictInt = Field(ge=0)
    slack_sent_at: AwareDateTime | None
    items: list[BriefingItemView]
    tracked_changes: list[BriefingItemView]
    collection_note: StrictStr | None


class BriefingReactionRequest(RuntimeContractModel):
    reaction: BriefingReaction
    expected_revision: StrictInt = Field(ge=0)
    request_id: UUID


class BriefingSlackPreview(RuntimeContractModel):
    """실제 전송 payload와 같은 함수가 만든 Block Kit 미리보기."""

    schema_version: Literal["bidops.briefing-slack-preview.v1"]
    channel_id_present: StrictBool
    blocks: list[dict[str, Any]]
    text: StrictStr


__all__ = [
    "BRIEFING_SCHEMA_VERSION",
    "BRIEFING_SLACK_PREVIEW_SCHEMA_VERSION",
    "BriefingBlocking",
    "BriefingDeadlineKind",
    "BriefingItemKind",
    "BriefingItemView",
    "BriefingReaction",
    "BriefingReactionRequest",
    "BriefingReactionVia",
    "BriefingReason",
    "BriefingSlackPreview",
    "BriefingStage",
    "BriefingStatus",
    "BriefingVerdictDisplay",
    "BriefingView",
]
