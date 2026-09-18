"""사전규격 목록과 추적 계약 (lifecycle, 명세 §5.2·§6.1).

개요 검토의 응답 view는 `app/deep_review/schemas/prespec_overview.py`가 갖고,
목록이 투영하는 개요 상태 리터럴은 `app/core/constants.py`에 있다(명세 §4:
상수는 core로 옮겨 lifecycle → deep_review 역방향을 만들지 않는다).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from ...core.constants import (
    PreSpecAutoPreparationStatus,
    PreSpecGradeSource,
    PreSpecOverviewReviewStatus,
)
from ...core.schema_base import AwareDateTime, RuntimeContractModel
from .opportunities import OpportunityLinkView, OpportunityTrackingStatus


PreSpecOrigin = Literal["추적", "신규"]
PreSpecSort = Literal["published", "deadline", "observed"]
PreSpecWorkspace = Literal["actionable", "recent", "tracking", "all"]
PreSpecOverviewView = Literal[
    "all",
    "attention",
    "pending",
    "completed",
    "failed",
    "cancelled",
    "not_started",
]
PreSpecTrackingDecision = Literal["pending"]
PreSpecDeadlineStatus = Literal["open", "passed", "unknown"]
PreSpecGradeFilter = Literal["우선 검토", "검토 권장", "관찰 대상", "제외", "판정 없음"]
PreSpecNextAction = Literal["confirm_overview", "open_deep_review", "decide_tracking"]


class PreSpecDocumentSummary(RuntimeContractModel):
    """Counts only; object-store and local storage metadata stay server-side."""

    model_config = ConfigDict(extra="forbid", from_attributes=True, populate_by_name=True)

    attachments: int = Field(ge=0)
    completed: int = Field(default=0, ge=0, alias="완료")
    pending: int = Field(default=0, ge=0, alias="대기")
    running: int = Field(default=0, ge=0, alias="진행")
    blocked: int = Field(default=0, ge=0, alias="차단")
    failed: int = Field(default=0, ge=0, alias="실패")


class PreSpecListItem(RuntimeContractModel):
    notice_pk: int = Field(ge=1)
    pre_spec_no: str | None = None
    title: str | None = None
    agency: str | None = None
    published_at: AwareDateTime | None = None
    deadline_at: AwareDateTime | None = None
    budget: float | None = None
    sw_business_status: str | None = None
    business_division: str | None = None
    origin: PreSpecOrigin | None = None
    opportunity_id: int | None = Field(default=None, ge=1)
    tracking_status: OpportunityTrackingStatus | None = None
    kept_by_tracking: bool
    document: PreSpecDocumentSummary
    # Additive projection (docs/design/PLAN.md 3단계): current overview review
    # status for this notice, from ``prespec_overview_review.status``.  A
    # notice with no overview review row yet (개요 검토 미시작) projects
    # ``None`` here; it is a distinct, eleventh bucket and must never be
    # folded into ``awaiting_document`` (CLAUDE.md unknown/null 보존 게이트).
    overview_review_status: PreSpecOverviewReviewStatus | None = None
    # 등급과 자동 문서 준비 (명세 §8). 값은 deep_review의 개요·문서 projection
    # 확장점에서 온다 — lifecycle은 판정도 자동 준비도 소유하지 않는다.
    #
    # `grade`가 `None`이면 판정도 사람 정정도 없다는 뜻이고 그때 `grade_source`도
    # `None`이다. 둘 중 하나만 채우거나 "없음"을 특정 등급으로 접지 않는다
    # (CLAUDE.md unknown/null 보존 게이트).
    grade: str | None = None
    grade_source: PreSpecGradeSource | None = None
    # 제공자가 없는 배포에서는 자동 준비가 실제로 일어나지 않으므로
    # `not_applicable`이다. "알 수 없음"이 아니라 "대상이 아님"이다.
    auto_preparation_status: PreSpecAutoPreparationStatus = "not_applicable"
    #: 왜 다음 단계로 가지 않는가. 안전한 코드이며 없으면 `None`이다.
    auto_preparation_reason: str | None = None
    latest_deep_review_id: UUID | None = None
    first_observed_at: AwareDateTime | None = None
    last_observed_at: AwareDateTime | None = None
    next_action: PreSpecNextAction | None = None


class PreSpecOverviewStatusCount(RuntimeContractModel):
    """One grouping bucket's total, independent of the page ``limit``/``offset``.

    ``status`` is ``None`` for notices with no ``prespec_overview_review`` row
    (개요 검토 미시작) — this is the eleventh bucket alongside the ten
    ``PreSpecOverviewReviewStatus`` values, never merged into one of them.
    """

    status: PreSpecOverviewReviewStatus | None = None
    count: int = Field(ge=0)


class PreSpecListResponse(RuntimeContractModel):
    items: list[PreSpecListItem] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    # Counts for every overview-review status bucket (the ten contract values
    # plus the ``None``/미시작 bucket) matching the current filter, computed
    # over the full filtered set rather than the returned page. This lets the
    # list screen render all-groups-always-visible collapsible sections with
    # correct counts while ``items``/``total``/``limit``/``offset`` keep their
    # existing pagination meaning (docs/design/PLAN.md 3단계 결정 (a)/(b)).
    overview_status_counts: list[PreSpecOverviewStatusCount] = Field(default_factory=list)
    workspace_counts: dict[PreSpecWorkspace, int] = Field(default_factory=dict)


class PreSpecCandidateOrderPlan(RuntimeContractModel):
    """Order-plan summary of an opportunity that proposes a pre-spec candidate."""

    order_plan_id: int = Field(ge=1)
    order_plan_unty_no: str
    title: str | None = None
    agency_name: str | None = None
    planned_order_year: str | None = None
    planned_order_month: str | None = None
    budget_amount: float | None = None


class PreSpecOrderPlanCandidate(RuntimeContractModel):
    """One pending candidate link that targets this pre-spec (spec §4.4).

    ``order_plans`` lists every order plan the owner opportunity owns; it is
    empty when the owner (for example a merge-confirmation owner) owns none.
    """

    link: OpportunityLinkView
    opportunity_id: int = Field(ge=1)
    tracking_status: OpportunityTrackingStatus
    order_plans: list[PreSpecCandidateOrderPlan] = Field(default_factory=list)


class PreSpecOrderPlanCandidatesResponse(RuntimeContractModel):
    notice_pk: int = Field(ge=1)
    items: list[PreSpecOrderPlanCandidate] = Field(default_factory=list)


__all__ = [
    "PreSpecCandidateOrderPlan",
    "PreSpecDocumentSummary",
    "PreSpecOrderPlanCandidate",
    "PreSpecOrderPlanCandidatesResponse",
    "PreSpecListItem",
    "PreSpecListResponse",
    "PreSpecOrigin",
    "PreSpecWorkspace",
    "PreSpecOverviewView",
    "PreSpecTrackingDecision",
    "PreSpecDeadlineStatus",
    "PreSpecGradeFilter",
    "PreSpecNextAction",
    "PreSpecOverviewStatusCount",
    "PreSpecSort",
]
