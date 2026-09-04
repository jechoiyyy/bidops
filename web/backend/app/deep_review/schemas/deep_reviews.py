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


class StageView(StrictModel):
    stage: StageName
    sequence: int = Field(ge=1)
    status: StageStatus
    started_at: datetime | None
    completed_at: datetime | None
    last_error_code: str | None


class AttemptView(StrictModel):
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


__all__ = [
    "AttemptStatus",
    "AttemptView",
    "DeepReviewView",
    "ReviewStatus",
    "StageName",
    "StageStatus",
    "StageView",
]
