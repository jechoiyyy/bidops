"""Closed commands for the human-in-the-loop decision workflow."""

from __future__ import annotations

from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator, model_validator

from ..common import (
    AgentAction,
    AgentActorKind,
    AgentAggregateType,
    AgentArtifactType,
    AgentCommand,
    AgentName,
)
from ...schemas.reports import DeepReviewReport


class _StrictPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=False,
        validate_assignment=True,
    )


class FullRevisionPayload(_StrictPayload):
    """The full immutable report snapshot carried by a revision action."""

    base_revision_id: UUID
    report: DeepReviewReport
    reason: str
    factual_change_evidence_ids: list[UUID]

    @field_validator("reason")
    @classmethod
    def reason_is_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


class FinalOpinionPayload(_StrictPayload):
    """A human-supplied final opinion; the agent never chooses ``value``."""

    report_revision_id: UUID
    validation_run_id: UUID
    value: Literal["추진", "조건부 추진", "보류", "검토 종료"]
    reason: str
    acknowledged_validation_failure: StrictBool


def _require_action(command: AgentCommand[BaseModel], action: AgentAction) -> None:
    if command.agent_name is not AgentName.decision or command.action is not action:
        raise ValueError("command action does not belong to decision")
    if command.actor.actor_kind is not AgentActorKind.human:
        raise ValueError("decision mutations require a human actor")
    if command.actor.claimed_name is None:
        raise ValueError("decision mutations require a claimed name")


class CreateFullRevisionCommand(AgentCommand[FullRevisionPayload]):
    @model_validator(mode="after")
    def validate_create_full_revision(self) -> CreateFullRevisionCommand:
        _require_action(self, AgentAction.create_full_revision)
        if self.aggregate.aggregate_type is not AgentAggregateType.deep_review:
            raise ValueError("create_full_revision targets a deep review")
        if self.request_id is None:
            raise ValueError("create_full_revision request_id is required")
        if self.expected_version is not None:
            raise ValueError("create_full_revision expected_version must be null")
        if len(self.input_refs) != 1:
            raise ValueError("create_full_revision requires one current report revision ref")
        ref = self.input_refs[0]
        if ref.artifact_type is not AgentArtifactType.report_revision:
            raise ValueError("create_full_revision ref must be a report revision")
        if ref.artifact_id != str(self.payload.base_revision_id):
            raise ValueError("create_full_revision ref and payload must match")
        if ref.version is None or ref.sha256 is None:
            raise ValueError("create_full_revision ref must include version and hash")
        return self


class RecordFinalOpinionCommand(AgentCommand[FinalOpinionPayload]):
    @model_validator(mode="after")
    def validate_record_final_opinion(self) -> RecordFinalOpinionCommand:
        _require_action(self, AgentAction.record_final_opinion)
        if self.aggregate.aggregate_type is not AgentAggregateType.deep_review:
            raise ValueError("record_final_opinion targets a deep review")
        if self.request_id is None:
            raise ValueError("record_final_opinion request_id is required")
        if self.expected_version is not None:
            raise ValueError("record_final_opinion expected_version must be null")
        if len(self.input_refs) != 2:
            raise ValueError("record_final_opinion requires current revision and validation refs")
        revision_ref, validation_ref = self.input_refs
        if revision_ref.artifact_type is not AgentArtifactType.report_revision:
            raise ValueError("record_final_opinion first ref must be a report revision")
        if validation_ref.artifact_type is not AgentArtifactType.validation_run:
            raise ValueError("record_final_opinion second ref must be a validation run")
        if revision_ref.artifact_id != str(self.payload.report_revision_id):
            raise ValueError("record_final_opinion revision ref and payload must match")
        if validation_ref.artifact_id != str(self.payload.validation_run_id):
            raise ValueError("record_final_opinion validation ref and payload must match")
        if revision_ref.version is None or revision_ref.sha256 is None:
            raise ValueError("record_final_opinion revision ref must include version and hash")
        if validation_ref.version is None or validation_ref.sha256 is None:
            raise ValueError("record_final_opinion validation ref must include version and hash")
        return self


# Descriptive aliases are kept as aliases, not additional wire contracts.
CreateFullRevisionPayload = FullRevisionPayload
RecordFinalOpinionPayload = FinalOpinionPayload
CreateFullRevisionAction = FullRevisionPayload
RecordFinalOpinionAction = FinalOpinionPayload
DecisionRevisionCommand = CreateFullRevisionCommand
DecisionOpinionCommand = RecordFinalOpinionCommand

DecisionActionCommand: TypeAlias = CreateFullRevisionCommand | RecordFinalOpinionCommand


__all__ = [
    "CreateFullRevisionAction",
    "CreateFullRevisionCommand",
    "CreateFullRevisionPayload",
    "DecisionActionCommand",
    "DecisionOpinionCommand",
    "DecisionRevisionCommand",
    "FinalOpinionPayload",
    "FullRevisionPayload",
    "RecordFinalOpinionAction",
    "RecordFinalOpinionCommand",
    "RecordFinalOpinionPayload",
]
