"""Metadata-only request; documents and company facts come from existing authority."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class EngineRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    bundle_id: UUID
    mode: Literal["mock_reference", "live"] = "mock_reference"


class EngineRunView(BaseModel):
    id: UUID
    request_id: UUID
    company_id: UUID
    notice_id: int
    bundle_id: UUID
    engine_version: str
    quality_status: Literal["mock_reference"]
    status: Literal["queued", "running", "completed", "partial", "failed"]
    engine_sha256: str
    input_currentness: Literal["current", "stale", "unknown"]
    profile_version_id: UUID
    profile_sha256: str
    graph_version_id: UUID
    graph_sha256: str
    documents: list[dict[str, str]]
    input_sha256: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    warnings: list[str]
    analysis: dict[str, Any] | None


class EngineRunList(BaseModel):
    items: list[EngineRunView]
    total: int
