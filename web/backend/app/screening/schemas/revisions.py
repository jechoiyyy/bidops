"""Read-only notice judgment/review revision-history wire models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _RevisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JudgmentRevisionHistoryItem(_RevisionModel):
    id: int
    sequence: int = Field(ge=1)
    source_kind: str
    run_id: str | None
    recording_execution_id: str | None
    source_revision_id: int | None
    origin_execution_id: str | None
    payload_schema_version: str
    payload: dict[str, Any]
    payload_sha256: str
    captured_at: datetime


class ReviewRevisionHistoryItem(_RevisionModel):
    id: int
    sequence: int = Field(ge=1)
    source_kind: str
    run_id: str | None
    judgment_revision_id: int | None
    origin_execution_id: str | None
    payload_schema_version: str
    payload: dict[str, Any]
    payload_sha256: str
    captured_at: datetime


class NoticeRevisionHistoryResponse(_RevisionModel):
    notice_pk: int
    judgments: list[JudgmentRevisionHistoryItem]
    reviews: list[ReviewRevisionHistoryItem]


__all__ = [
    "JudgmentRevisionHistoryItem",
    "NoticeRevisionHistoryResponse",
    "ReviewRevisionHistoryItem",
]
