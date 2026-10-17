"""RL-03 practitioner verdict REST DTOs (HP-04 "API 계약" + RL-03 spec "REST").

``bidops.practitioner-verdict-view.v1`` keeps the HP-04 key set; RL-03 adds
``briefing_item_id``/``opportunity_id`` at the top level and (decision B4) the
matrix row keys ``normalized_requirement``/``mandatory``/``fact_labels`` and
``source_binding.document_versions[].structure_id``.  ``company_sha256`` is
the frozen company graph sha (no basis file).  Every model is closed (extra
keys forbidden) so the view cannot silently grow.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, model_validator

from .document_bundles import StrictModel


VIEW_SCHEMA_VERSION = "bidops.practitioner-verdict-view.v1"
TRANSFER_POLICY_SCHEMA_VERSION = "bidops.transfer-policy.v1"

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmpty = Annotated[str, Field(min_length=1)]
Availability = Literal["none", "pending", "running", "completed", "failed", "needs_human_review", "legacy"]
StaleReason = Literal["company_changed", "ontology_changed", "documents_changed", "policy_changed", "superseded"]
QualityStatus = Literal["measured", "unmeasured_reference", "mock_reference"]
Fit = Literal["met", "gap", "unknown"]
Role = Literal["eligibility_economics", "technical_fit", "operations_risk"]
MappingStatus = Literal["mapped", "partial", "inherited", "unavailable"]
SectionKind = Literal["overview", "schedule", "budget", "eligibility", "evaluation", "contract"]
ChecklistKey = Literal[
    "qualification_track_record", "staffing_onsite", "amount_period", "technology", "operations_sla_security",
]
VerdictName = Literal["진행 가능", "조건부 진행", "진행 어려움", "판단 불가"]
FeedbackKind = Literal["wrong_verdict", "wrong_unit", "not_requirement", "source_mismatch"]

STALE_REASON_ORDER: tuple[str, ...] = (
    "company_changed", "ontology_changed", "documents_changed", "policy_changed", "superseded",
)
CHECKLIST_ORDER: tuple[str, ...] = (
    "qualification_track_record", "staffing_onsite", "amount_period", "technology", "operations_sla_security",
)


class VerdictEvidenceRef(StrictModel):
    source_sha256: Sha256
    block_key: NonEmpty
    quote: NonEmpty


class VerdictRoleFinding(StrictModel):
    role: Role
    assessment: Fit
    reason: NonEmpty
    evidence_refs: list[VerdictEvidenceRef]


class VerdictPageRange(StrictModel):
    first: StrictInt = Field(ge=1)
    last: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> "VerdictPageRange":
        if self.last < self.first:
            raise ValueError("page_range_invalid")
        return self


class VerdictMatrixRow(StrictModel):
    unit_id: NonEmpty
    type: NonEmpty
    fit_status: Fit
    role_findings: list[VerdictRoleFinding]
    evidence_refs: list[VerdictEvidenceRef]
    page_range: VerdictPageRange | None
    mapping_status: MappingStatus
    #: B4 additive keys (extract ``normalized_requirement``/``mandatory``, compare fact labels).
    normalized_requirement: NonEmpty | None
    mandatory: StrictBool | None
    fact_labels: list[NonEmpty]

    @model_validator(mode="after")
    def _mapping(self) -> "VerdictMatrixRow":
        if (self.mapping_status == "unavailable") != (self.page_range is None):
            raise ValueError("page_mapping_invalid")
        return self


class VerdictChecklistRow(StrictModel):
    key: ChecklistKey
    status: Fit
    evidence_refs: list[VerdictEvidenceRef]


class VerdictCaution(StrictModel):
    unit_id: NonEmpty
    text: NonEmpty
    evidence_refs: list[VerdictEvidenceRef]


class VerdictConflict(StrictModel):
    unit_id: NonEmpty
    roles: list[Role]
    assessments: list[Fit]


class VerdictNextAction(StrictModel):
    unit_id: NonEmpty
    owner: NonEmpty | None
    action: NonEmpty
    evidence_refs: list[VerdictEvidenceRef]


class VerdictResult(StrictModel):
    verdict: VerdictName
    reason: NonEmpty
    blocking_condition_ids: list[NonEmpty]
    checklist: list[VerdictChecklistRow] = Field(min_length=5, max_length=5)
    matrix: list[VerdictMatrixRow]
    cautions: list[VerdictCaution]
    conflicts: list[VerdictConflict]
    next_actions: list[VerdictNextAction]

    @model_validator(mode="after")
    def _checklist_order(self) -> "VerdictResult":
        if tuple(row.key for row in self.checklist) != CHECKLIST_ORDER:
            raise ValueError("checklist_order_invalid")
        return self


class VerdictIdentity(StrictModel):
    policy_id: UUID
    policy_sha256: Sha256
    model: NonEmpty
    reasoning_effort: NonEmpty
    cli_version: NonEmpty


class VerdictDocumentVersion(StrictModel):
    document_version_id: UUID
    source_sha256: Sha256
    #: B4: the frozen bundle item's structure (the "쪽 전체 보기" target), null when unknown.
    structure_id: UUID | None


class VerdictSourceBinding(StrictModel):
    document_versions: list[VerdictDocumentVersion] = Field(min_length=1)
    company_version_id: UUID
    company_sha256: Sha256
    ontology_sha256: Sha256


class PractitionerVerdictView(StrictModel):
    schema_version: Literal["bidops.practitioner-verdict-view.v1"] = VIEW_SCHEMA_VERSION
    company_id: UUID
    #: ``null`` only on the opportunity alias when no pre-spec is authoritatively linked.
    notice_id: StrictInt | None
    attempt_id: UUID | None
    availability: Availability
    is_current: StrictBool
    stale_reasons: list[StaleReason]
    quality_status: QualityStatus | None
    identity: VerdictIdentity | None
    source_binding: VerdictSourceBinding | None
    result: VerdictResult | None
    partial_stage_ids: list[UUID]
    error_code: NonEmpty | None
    missing_sections: list[SectionKind]
    started_at: str | None
    finished_at: str | None
    partial_matrix: list[VerdictMatrixRow]
    briefing_item_id: UUID | None
    opportunity_id: StrictInt | None

    @model_validator(mode="after")
    def _consistency(self) -> "PractitionerVerdictView":
        if self.availability == "none" and (
            self.attempt_id is not None or self.is_current or self.stale_reasons or self.result is not None
            or self.partial_matrix or self.partial_stage_ids
        ):
            raise ValueError("none_view_invalid")
        if self.result is not None and self.availability != "completed":
            raise ValueError("result_requires_completed")
        if self.availability == "completed" and (self.result is None or self.partial_matrix):
            raise ValueError("completed_view_invalid")
        if list(self.stale_reasons) != [reason for reason in STALE_REASON_ORDER if reason in self.stale_reasons]:
            raise ValueError("stale_reasons_order_invalid")
        if self.is_current and self.stale_reasons:
            raise ValueError("current_with_stale_reason")
        return self


class VerdictRequestCreate(StrictModel):
    request_id: UUID


class VerdictRequestReceipt(StrictModel):
    request_id: UUID
    attempt_id: UUID
    status: Literal["queued"]


class VerdictFeedbackCreate(StrictModel):
    attempt_id: UUID
    kind: FeedbackKind
    unit_id: NonEmpty | None = None
    note: Annotated[str, Field(max_length=500)] | None = None
    request_id: UUID


class VerdictFeedbackReceipt(StrictModel):
    feedback_id: UUID


class TransferPolicyActive(StrictModel):
    approval_id: UUID
    policy_identity: NonEmpty
    policy_sha256: Sha256
    daily_cap: StrictInt = Field(ge=1, le=50)
    approved_at: datetime
    approved_by: NonEmpty
    today_used: StrictInt = Field(ge=0)


class TransferPolicyView(StrictModel):
    schema_version: Literal["bidops.transfer-policy.v1"] = TRANSFER_POLICY_SCHEMA_VERSION
    active: TransferPolicyActive | None


__all__ = [
    "CHECKLIST_ORDER",
    "STALE_REASON_ORDER",
    "TRANSFER_POLICY_SCHEMA_VERSION",
    "VIEW_SCHEMA_VERSION",
    "PractitionerVerdictView",
    "TransferPolicyActive",
    "TransferPolicyView",
    "VerdictChecklistRow",
    "VerdictDocumentVersion",
    "VerdictEvidenceRef",
    "VerdictFeedbackCreate",
    "VerdictFeedbackReceipt",
    "VerdictIdentity",
    "VerdictMatrixRow",
    "VerdictRequestCreate",
    "VerdictRequestReceipt",
    "VerdictResult",
    "VerdictRoleFinding",
    "VerdictSourceBinding",
]
