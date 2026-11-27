"""Human commands and receipts for the wiki-scoped prespec engine review."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .engine_runs import EngineRunView


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class RequestCommand(Command):
    origin: Literal["tracking_start", "manual"]


class BatchCommand(Command):
    origin: Literal["tracking_start"]
    notice_ids: list[int] = Field(min_length=1, max_length=200)


class ApprovalCommand(Command):
    preview_id: UUID
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class DismissalCommand(Command):
    preview_id: UUID


class AcknowledgmentCommand(Command):
    result_id: UUID


class RequestReceipt(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    notice_id: int
    opportunity_id: int
    company_bundle_slug: str
    origin: Literal["tracking_start", "manual"]
    requested_by: str
    requested_at: datetime
    request_id: UUID
    closed_at: datetime | None
    closed_reason: str | None
    closed_by: str | None


class PreviewReceipt(BaseModel):
    preview_id: UUID
    manifest_sha256: str
    created_at: datetime
    expires_at: datetime
    manifest: dict[str, Any]
    #: live 미리보기의 오늘(KST) 사용량·남은 상한. manifest digest 밖이다(ADR-0081).
    budget: dict[str, Any] | None = None


class ApprovalReceipt(BaseModel):
    approval_id: UUID
    run_id: UUID
    state: Literal["queued", "running", "completed", "partial", "failed"]


class DismissalReceipt(BaseModel):
    dismissal_id: UUID
    request: RequestReceipt


class AcknowledgmentReceipt(BaseModel):
    acknowledgment_id: UUID
    result_id: UUID
    request_id: UUID
    acknowledged_by: str
    acknowledged_at: datetime


State = Literal["not_requested", "preparing", "blocked", "awaiting_approval", "queued",
                "running", "result_ready", "acknowledged", "stale"]
Reason = Literal["tracking_required", "documents_pending", "original_hwp_required",
                 "unsafe_document", "structure_unavailable", "company_bundle_unavailable",
                 "company_bundle_invalid", "engine_disabled", "engine_live_disabled",
                 "budget_exhausted", "input_changed", "live_run_failed"]


class ReviewState(BaseModel):
    state: State
    next_action: Literal["request", "resolve_exception", "approve", "review_result"] | None = None
    reason: Reason | None = None
    request: RequestReceipt | None = None
    preview: PreviewReceipt | None = None
    current_result: EngineRunView | None = None
    review_receipt: AcknowledgmentReceipt | None = None


class RequestResponse(BaseModel):
    request: RequestReceipt
    state: State


class BatchResult(BaseModel):
    notice_id: int
    outcome: Literal["requested", "already_requested", "ineligible"]
    request: RequestReceipt | None = None
    reason: str | None = None


class BatchResponse(BaseModel):
    items: list[BatchResult]
