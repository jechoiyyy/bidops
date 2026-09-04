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


__all__ = [
    "AttemptStatus",
    "AttemptView",
    "DeepReviewView",
    "QualityStatus",
    "ReviewStatus",
    "StageName",
    "StageStatus",
    "StageView",
]
