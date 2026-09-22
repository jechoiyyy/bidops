"""심층 검토 실행·attempt의 응답 view (deep_review).

`routers/deep_reviews.py`와 `agents/deep_review/agent.py`가 같은 view를 쓴다.
agent(하위)가 router(상위)를 import하지 않도록 schemas에 둔다(명세 §5.2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from .document_bundles import StrictModel

StageName = Literal["requirements_and_evaluation", "delivery_risk_economics", "synthesis_and_validation"]
StageStatus = Literal["queued", "running", "completed", "failed"]
AttemptStatus = Literal["queued", "running", "completed", "failed", "superseded"]
ReviewStatus = Literal["queued", "running", "completed", "failed"]
#: 모델 실행 품질 상태 (명세 §5). 참조 실행 두 값은 `deployable=false`이며
#: 운영 완료로 집계하지 않는다. `None`은 표식 없음이고 미측정과 다르다.
QualityStatus = Literal["measured", "unmeasured_reference", "mock_reference"]


class StageView(StrictModel):
    stage: StageName
    sequence: int = Field(ge=1)
    status: StageStatus
    started_at: datetime | None
    completed_at: datetime | None
    last_error_code: str | None


class AttemptView(StrictModel):
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    preview_id: UUID | None = None
    source_verification_enabled: bool = True
    id: UUID
    sequence: int = Field(ge=1)
    status: AttemptStatus
    stages: list[StageView]
    started_at: datetime | None
    completed_at: datetime | None
    last_error_code: str | None


class DeepReviewView(StrictModel):
    id: UUID
    notice_id: int
    bundle_id: UUID
    status: ReviewStatus
    current_attempt: AttemptView | None
    attempts: list[AttemptView]
    created_at: datetime
    completed_at: datetime | None
    # 기본값은 이 필드가 없던 시절의 idempotency snapshot을 그대로 재생하기
    # 위한 것이다. 없음을 미측정으로 승격시키지 않는다 (명세 §8).
    quality_status: QualityStatus | None = None


class OpportunityReviewFinalOpinion(StrictModel):
    value: str
    decided_at: datetime


class OpportunityDeepReviewItem(StrictModel):
    deep_review_id: str
    notice_id: int
    notice_title: str | None
    status: str
    quality_status: str | None
    created_at: datetime
    current_attempt_status: str | None
    latest_final_opinion: OpportunityReviewFinalOpinion | None


class OpportunityDeepReviewsResponse(StrictModel):
    opportunity_id: int
    items: list[OpportunityDeepReviewItem]


__all__ = [
    "AttemptStatus",
    "AttemptView",
    "DeepReviewView",
    "OpportunityDeepReviewItem",
    "OpportunityDeepReviewsResponse",
    "OpportunityReviewFinalOpinion",
    "QualityStatus",
    "ReviewStatus",
    "StageName",
    "StageStatus",
    "StageView",
]


class DeepReviewPreviewView(StrictModel):
    preview_id: UUID
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: Literal["codex-exec"]
    model: Literal["gpt-5.6-luna"]
    reasoning_effort: Literal["xhigh"]
    quality_status: Literal["unmeasured_reference"]
    source_verification_enabled: bool
    input: dict
