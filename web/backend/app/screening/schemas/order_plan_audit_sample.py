"""Wire schemas for the C-2 audit sample (감사 표본) REST surface.

정본은 ``docs/contracts.md`` "C-2 일일 운영 계약 > 감사 표본 REST"다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


AuditSampleStratum = Literal["classification_proximity", "performance_similarity_proximity", "uniform_hash"]
AuditSampleStatus = Literal["preview", "drawn", "pending_human_approval", "not_applicable"]


class AuditSampleDrawRequest(_Strict):
    schema_version: Literal["audit-sample-draw-request.v1"]
    producer: Literal["human-review-client"]
    consumer: Literal["audit-sample-api"]
    request_id: UUID


class AuditSampleItem(_Strict):
    order_plan_pk: int
    order_plan_unty_no: str
    title: str | None
    stratum: AuditSampleStratum
    selection_rank: int = Field(ge=1)
    plan_id_sha256: str = Field(min_length=64, max_length=64)
    stage1_rank: int
    stage1_score: float
    nearest_capability: str | None


class _AuditSampleView(_Strict):
    producer: Literal["screening-api"]
    consumer: Literal["human-review-client"]
    execution_id: UUID
    status: AuditSampleStatus
    reason: str | None
    pending_decision: str | None
    policy_version: str
    policy_sha256: str
    population_count: int = Field(ge=0)
    filtered_out_count: int = Field(ge=0)
    max_per_execution: int | None
    review_cadence: str | None
    sample: list[AuditSampleItem] | None
    drawn_by: str | None
    drawn_at: datetime | None


class AuditSamplePreviewResponse(_AuditSampleView):
    schema_version: Literal["audit-sample-preview-response.v1"]


class AuditSampleDrawResponse(_AuditSampleView):
    schema_version: Literal["audit-sample-draw-response.v1"]
    request_id: UUID
    audit_event_id: UUID | None
