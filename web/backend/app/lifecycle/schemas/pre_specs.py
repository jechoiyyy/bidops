"""사전규격 목록과 추적 계약 (lifecycle, 명세 §5.2·§6.1).

개요 검토의 응답 view는 `app/deep_review/schemas/prespec_overview.py`가 갖고,
목록이 투영하는 개요 상태 리터럴은 `app/core/constants.py`에 있다(명세 §4:
상수는 core로 옮겨 lifecycle → deep_review 역방향을 만들지 않는다).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, StringConstraints, field_validator

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
#: 검토할 항목(actionable)의 기본 시야를 나누는 구간 (ADR-0064).
#: `current`는 `마감 전`과 `마감 미확인`(deadline_at is null)을 함께 담는다 —
#: 미확인을 마감 경과로 접지 않는다(CLAUDE.md unknown/null 보존 게이트).
PreSpecDeadlineScope = Literal["current", "passed", "all"]
PreSpecGradeFilter = Literal["우선 검토", "검토 권장", "관찰 대상", "제외", "판정 없음"]
PreSpecDisplayGradeFilter = Literal[
    "우선 검토", "검토 권장", "관찰 대상", "제외", "판단 보류", "판정 없음"
]
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


PreSpecReviewExclusionStatus = Literal["included", "excluded"]
PreSpecReviewExclusionFilter = Literal["all", "included", "excluded"]


class PreSpecReviewExclusionRequest(RuntimeContractModel):
    notice_ids: list[Annotated[int, Field(strict=True, ge=1, le=2147483647)]] = Field(min_length=1, max_length=200)
    status: PreSpecReviewExclusionStatus
    actor_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

    @field_validator("notice_ids")
    @classmethod
    def unique_ids(cls, values: list[int]) -> list[int]:
        if len(set(values)) != len(values):
            raise ValueError("duplicate notice_ids")
        return values


class PreSpecReviewExclusionResult(RuntimeContractModel):
    notice_id: int
    outcome: Literal["changed", "unchanged"]
    status: PreSpecReviewExclusionStatus


class PreSpecReviewExclusionResponse(RuntimeContractModel):
    items: list[PreSpecReviewExclusionResult]


class PreSpecDisplayAssessmentAxis(RuntimeContractModel):
    axis: Literal["ai_data", "blockchain_did", "public_si_integration"]
    relation: Literal["direct", "partial", "indirect", "unrelated", "unknown"]
    reason: str
    claim_refs: list[str] = Field(default_factory=list)
    company_refs: list[str] = Field(default_factory=list)


class PreSpecDisplayAssessment(RuntimeContractModel):
    grade: Literal["우선 검토", "검토 권장", "관찰 대상", "제외"] | None = None
    status: Literal["graded", "held", "none"] = "none"
    source: Literal[
        "human_review", "preliminary_assessment", "screening_judgment", "none"
    ] = "none"
    basis_run_id: str | None = None
    assessed_at: AwareDateTime | None = None
    quality_status: Literal["unmeasured_reference", "mock_reference"] | None = None
    reason_codes: list[str] = Field(default_factory=list)
    axes: list[PreSpecDisplayAssessmentAxis] = Field(default_factory=list)
    verification_items: list[str] = Field(default_factory=list)
    semantic_status: Literal["not_run", "passed", "failed"] | None = None
    semantic_scope: list[str] = Field(default_factory=list)
    latest_run_status: PreSpecOverviewReviewStatus | None = None


class PreSpecListItem(RuntimeContractModel):
    review_exclusion_status: PreSpecReviewExclusionStatus = "included"
    review_exclusion_actor_name: str | None = None
    review_exclusion_reason: str | None = None
    review_exclusion_changed_at: AwareDateTime | None = None
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
    display_assessment: PreSpecDisplayAssessment = Field(default_factory=PreSpecDisplayAssessment)
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


class PreSpecDeadlineScopeCounts(RuntimeContractModel):
    """구간 적용 **전** actionable 집합을 두 구간으로 나눈 건수 (ADR-0064 결정 5).

    `current` + `passed`는 언제나 구간 미적용 actionable 건수와 같다. 두 칸만 갖는
    명명된 모델인 이유는 `all` 키가 생기면 "분할"인지 "합계"인지가 모호해지기
    때문이다 — 합계가 필요하면 소비자가 두 칸을 더한다.
    """

    current: int = Field(ge=0)
    passed: int = Field(ge=0)


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
    # 활성 workspace·활성 `deadline_scope`와 무관하게 항상 같은 값이고 항상 존재한다.
    # 나머지 필터(`q`·`deadline_status`·`grade` 등)는 모두 반영한다.
    deadline_scope_counts: PreSpecDeadlineScopeCounts


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
    "PreSpecDeadlineScope",
    "PreSpecDeadlineScopeCounts",
    "PreSpecDisplayAssessment",
    "PreSpecDisplayAssessmentAxis",
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
    "PreSpecDisplayGradeFilter",
    "PreSpecNextAction",
    "PreSpecOverviewStatusCount",
    "PreSpecSort",
]
