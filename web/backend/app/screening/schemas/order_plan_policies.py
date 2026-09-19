"""C-2 policy REST wire schema (contracts "C-2 일일 운영 계약 — policy REST")."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PolicyStatus = Literal["draft", "activation_candidate", "active", "retired"]
QualityGateStatus = Literal["not_measured", "measured", "passed", "failed"]


class _Response(_Strict):
    producer: Literal["policy-api"]
    consumer: Literal["human-review-client"]


class PolicyCandidateRequest(_Strict):
    schema_version: Literal["policy-candidate-request.v1"]
    producer: Literal["human-review-client"]
    consumer: Literal["policy-api"]
    request_id: UUID
    policy_version: str = Field(min_length=1, max_length=64)
    base_policy_sha256: Sha256 | None = None
    candidate_sha256: Sha256
    reason: str = Field(min_length=1, max_length=500)


class PolicyActivateRequest(_Strict):
    schema_version: Literal["policy-activate-request.v1"]
    producer: Literal["human-review-client"]
    consumer: Literal["policy-api"]
    request_id: UUID
    policy_sha256: Sha256
    quality_gate_artifact_sha256: Sha256
    # `true`로 고정하지 않는다. `false`는 검증 순서 8번에서 invalid_request가 된다.
    explicit_confirmation: bool


class PolicySummary(_Strict):
    policy_version: str
    policy_status: PolicyStatus
    quality_gate_status: QualityGateStatus | None
    policy_sha256: str
    binding_sha256: str
    created_by: str
    created_at: datetime
    activated_by: str | None
    activated_at: datetime | None


class PolicyListResponse(_Response):
    schema_version: Literal["policy-list-response.v1"]
    items: list[PolicySummary]
    total: int = Field(ge=0)


class PolicyBlocker(_Strict):
    code: str
    detail: str | None = None


class ExternalTransportView(_Strict):
    execution_allowed: bool | None = None
    approval_scope: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    approval_required_per_execution: bool | None = None


class AuditSampleSettingView(_Strict):
    enabled: bool | None = None
    max_per_execution: int | None = None
    review_cadence: str | None = None


class LatestEvaluationView(_Strict):
    evaluation_id: str
    revision: int = Field(ge=1)
    result_status: Literal["통과", "미달", "미측정", "보류"]
    artifact_sha256: str
    evaluated_at: datetime


class SelectedGateView(_Strict):
    gate_id: str
    evaluation_basis: Literal["product_rerun", "reference_artifact_rescore"]
    thresholds_decided: bool
    latest_evaluation: LatestEvaluationView | None


class PolicyInspectResponse(PolicySummary):
    schema_version: Literal["policy-inspect-response.v1"]
    producer: Literal["policy-api"]
    consumer: Literal["human-review-client"]
    binding_status: str | None
    policy_file_present: bool
    binding_file_present: bool
    external_transport: ExternalTransportView | None
    audit_sample: AuditSampleSettingView | None
    quality_gate: SelectedGateView | None
    activation_allowed: bool
    blockers: list[PolicyBlocker]


class PolicyCandidateResponse(_Response):
    schema_version: Literal["policy-candidate-response.v1"]
    request_id: UUID
    policy_version: str
    policy_status: Literal["activation_candidate"]
    policy_sha256: str
    binding_sha256: str
    audit_event_id: UUID


class PolicyActivateResponse(_Response):
    schema_version: Literal["policy-activate-response.v1"]
    request_id: UUID
    policy_version: str
    policy_status: Literal["active"]
    quality_gate_status: Literal["passed"]
    policy_sha256: str
    binding_sha256: str
    gate_id: str
    evaluation_id: str
    previous_active_policy_version: str | None
    activated_by: str
    activated_at: datetime
    audit_event_id: UUID
