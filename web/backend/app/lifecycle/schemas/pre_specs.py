"""사전규격 목록과 추적 계약 (lifecycle, 명세 §5.2·§6.1).

개요 검토의 응답 view는 `app/deep_review/schemas/prespec_overview.py`가 갖고,
목록이 투영하는 개요 상태 리터럴은 `app/core/constants.py`에 있다(명세 §4:
상수는 core로 옮겨 lifecycle → deep_review 역방향을 만들지 않는다).
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from ...core.constants import PreSpecOverviewReviewStatus
from ...core.schema_base import AwareDateTime, RuntimeContractModel
from .opportunities import OpportunityTrackingStatus


PreSpecOrigin = Literal["추적", "신규"]
PreSpecSort = Literal["published", "deadline"]


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


__all__ = [
    "PreSpecDocumentSummary",
    "PreSpecListItem",
    "PreSpecListResponse",
    "PreSpecOrigin",
    "PreSpecOverviewStatusCount",
    "PreSpecSort",
]
