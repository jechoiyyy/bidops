"""C-2 일일 자동 실행 스위치 wire schema (contracts "일일 자동 실행 스위치 REST")."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


DailyTriggerReason = Literal[
    "env_cap_off",
    "no_active_policy",
    "switch_off",
    "switch_bound_to_other_version",
    "quality_gate_not_passed",
    "execution_transport_not_allowed",
    "policy_file_missing",
]


class DailyTriggerSetRequest(_Strict):
    schema_version: Literal["daily-trigger-set-request.v1"]
    producer: Literal["human-review-client"]
    consumer: Literal["daily-trigger-api"]
    request_id: UUID
    policy_version: str = Field(min_length=1, max_length=64)
    enabled: bool
    reason: str | None = Field(default=None, min_length=1, max_length=200)
    # `true`로 고정하지 않는다. `false`는 서비스가 invalid_request로 거부한다.
    explicit_confirmation: bool


class DailyTriggerSwitchView(_Strict):
    enabled: bool
    reason: str | None = None
    set_by: str
    set_at: datetime


class DailyTriggerStateResponse(_Strict):
    schema_version: Literal["daily-trigger-state-response.v1"]
    producer: Literal["daily-trigger-api"]
    consumer: Literal["human-review-client"]
    effective_enabled: bool
    policy_version: str | None
    policy_sha256: str | None
    switch: DailyTriggerSwitchView | None
    reasons: list[DailyTriggerReason]


class DailyTriggerSetResponse(_Strict):
    schema_version: Literal["daily-trigger-set-response.v1"]
    producer: Literal["daily-trigger-api"]
    consumer: Literal["human-review-client"]
    request_id: UUID
    policy_version: str
    policy_sha256: str
    enabled: bool
    reason: str | None = None
    set_by: str
    set_at: datetime
    audit_event_id: UUID
    effective_enabled: bool
    reasons: list[DailyTriggerReason]
