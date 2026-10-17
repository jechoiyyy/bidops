"""사업기회 레코드 활동 피드 계약 (RL-02 spec "활동 피드"·"단계 바").

`GET /api/opportunities/{id}/activity`의 응답과 그 항목 `ActivityItem`이다. 피드는 저장하지
않고 원본(연결·관측·감사·반응·노트)에서 파생하며, 다른 모듈(RL-03 판정·RL-04 초안)은
lifecycle 확장점 `opportunity_activity_items`로 같은 `ActivityItem`을 돌려준다 — 그래서 이
파일은 lifecycle 공개 표면(`tests/app/boundary_map.py`)에 올라 있다.

`models`·`services`를 import하지 않는다(경계 검사 3).
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import Field, StrictInt, StrictStr, model_validator

from ...core.schema_base import AwareDateTime, RuntimeContractModel

OPPORTUNITY_ACTIVITY_SCHEMA_VERSION = "bidops.opportunity-activity.v1"

#: 활동 kind 13값(spec 표). 시스템 처리(수집 회차·변환·호출·정책)는 어떤 kind에도 없다.
OpportunityActivityKind = Literal[
    "order_plan_found",
    "pre_spec_opened",
    "bid_posted",
    "notice_corrected",
    "tracking_decided",
    "recheck_signal",
    "link_reviewed",
    "briefing_reacted",
    "note_added",
    "action_added",
    "action_done",
    "verdict_completed",
    "draft_prepared",
]
OPPORTUNITY_ACTIVITY_KINDS: tuple[str, ...] = get_args(OpportunityActivityKind)

#: 단계 바 6단계의 고정 순서. 응답 `stages`는 언제나 이 순서로 6개다.
OpportunityStageKey = Literal["order_plan", "pre_spec", "bid_notice", "deadline", "opening", "contract"]
OPPORTUNITY_STAGE_KEYS: tuple[str, ...] = get_args(OpportunityStageKey)
OpportunityStageState = Literal["done", "current", "upcoming_deadline", "pending", "unknown"]

#: `limit` 질의 인자(spec "설정 키와 기본값").
ACTIVITY_LIMIT_DEFAULT = 50
ACTIVITY_LIMIT_MAX = 200


class ActivityLink(RuntimeContractModel):
    label: StrictStr = Field(min_length=1)
    # 내부 화면 경로(`/pre-specs/…`) 또는 공고 외부 URL(`https://…`, 새 창).
    path: StrictStr = Field(min_length=1)


class ActivityItem(RuntimeContractModel):
    #: `"<kind>:<원본 PK>"`. 결정적이고 저장하지 않는다.
    item_id: StrictStr
    kind: OpportunityActivityKind
    at: AwareDateTime
    actor: StrictStr | None = None
    title: StrictStr = Field(min_length=1)
    detail: StrictStr | None = None
    link: ActivityLink | None = None
    status_pill: StrictStr | None = None

    @model_validator(mode="after")
    def _item_id_names_its_kind(self) -> ActivityItem:
        prefix = f"{self.kind}:"
        if not self.item_id.startswith(prefix) or len(self.item_id) == len(prefix) or "|" in self.item_id:
            raise ValueError("item_id must be '<kind>:<pk>' without '|'")
        return self


class OpportunityStageView(RuntimeContractModel):
    key: OpportunityStageKey
    state: OpportunityStageState
    at: AwareDateTime | None
    #: 이 단계를 대표하는 권위 연결 id(`opportunity_stages.representatives`). 발주계획·사전규격·
    #: 입찰공고는 그 단계 대표, 마감·개찰은 입찰공고 대표의 id이고 입찰공고가 없거나 계약이면 `null`.
    #: 화면은 대표 연결을 스스로 고르지 않고 이 id로 상세 `links`에서 찾는다.
    link_id: StrictInt | None = Field(ge=1)


class OpportunityActivityResponse(RuntimeContractModel):
    schema_version: Literal["bidops.opportunity-activity.v1"]
    opportunity_id: StrictInt = Field(ge=1)
    merged_into_opportunity_id: StrictInt | None = Field(ge=1)
    #: 권위 연결 중 가장 뒤 단계의 제목. 없으면 `#<id>`.
    title: StrictStr = Field(min_length=1)
    stages: list[OpportunityStageView] = Field(min_length=6, max_length=6)
    items: list[ActivityItem]
    #: 다음 페이지 opaque 커서 `"<at ISO>|<item_id>"`. 마지막 페이지면 `null`.
    next_before: StrictStr | None


__all__ = [
    "ACTIVITY_LIMIT_DEFAULT",
    "ACTIVITY_LIMIT_MAX",
    "ActivityItem",
    "ActivityLink",
    "OPPORTUNITY_ACTIVITY_KINDS",
    "OPPORTUNITY_ACTIVITY_SCHEMA_VERSION",
    "OPPORTUNITY_STAGE_KEYS",
    "OpportunityActivityKind",
    "OpportunityActivityResponse",
    "OpportunityStageKey",
    "OpportunityStageState",
    "OpportunityStageView",
]
