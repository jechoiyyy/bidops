"""Independent REST envelope; model text is always rendered as text."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PreviewRequest(Strict):
    bundle_id: UUID


class CreateRequest(Strict):
    preview_id: UUID
    request_id: UUID


class PreviewView(Strict):
    preview_id: UUID
    input_sha256: str
    input: dict[str, Any]
    previous_preview_id: UUID | None
    previous_preview_kind: str | None
    changed_fields: list[str]


class CreatedView(Strict):
    id: UUID
    notice_id: int


class ListItem(Strict):
    id: UUID
    status: Literal['queued', 'running', 'completed', 'failed', 'cancelled']
    approved_at: datetime
    error_code: str | None


class ListView(Strict):
    items: list[ListItem]


class StageView(Strict):
    stage: Literal['business', 'company', 'decision']
    part: int
    status: Literal['completed', 'failed']
    started_at: datetime
    completed_at: datetime
    latency_ms: int
    error_code: str | None
    result: dict[str, Any] | None


class RunView(CreatedView):
    schema_version: Literal['bidops.assumption-analysis.v1']
    status: Literal['queued', 'running', 'completed', 'failed', 'cancelled']
    error_code: str | None
    approved_at: datetime
    input_version_id: UUID
    input_sha256: str
    scenario: dict[str, Any]
    stages: list[StageView]
    active_call: dict[str, Any] | None
    call_count: int
    latency_ms: int
    sources: list[dict[str, Any]]
    report: dict[str, Any] | None
