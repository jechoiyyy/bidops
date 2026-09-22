"""Closed commands for the deep-review Agent adapter.

The adapter deliberately keeps the command envelope smaller than the
analysis service API.  It carries only the immutable bundle/attempt
reference needed to prove the caller is acting on the persisted snapshot;
worker capabilities and model data never belong in this wire contract.
"""

from __future__ import annotations

from typing import TypeAlias
from uuid import UUID

from pydantic import StrictBool, BaseModel, ConfigDict, model_validator

from ..common import (
    AgentAction,
    AgentActorKind,
    AgentAggregateType,
    AgentArtifactType,
    AgentCommand,
    AgentName,
)


class _StrictPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=False,
        validate_assignment=True,
    )


class StartReviewPayload(_StrictPayload):
    source_verification_enabled: StrictBool = True
    bundle_id: UUID


class RetryAttemptPayload(_StrictPayload):
    source_verification_enabled: StrictBool = True
    """The retry action has no mutable payload beyond its current ref."""


def _require_action(command: AgentCommand[BaseModel], action: AgentAction) -> None:
    if command.agent_name is not AgentName.deep_review or command.action is not action:
        raise ValueError("command action does not belong to deep review")
    if command.actor.actor_kind is not AgentActorKind.human:
        raise ValueError("deep review mutations require a human actor")
    if command.actor.claimed_name is None:
        raise ValueError("deep review mutations require a claimed name")


class StartReviewCommand(AgentCommand[StartReviewPayload]):
    @model_validator(mode="after")
    def validate_start_review(self) -> StartReviewCommand:
        _require_action(self, AgentAction.start_review)
        if self.aggregate.aggregate_type is not AgentAggregateType.notice:
            raise ValueError("start_review targets a notice")
        if self.request_id is None:
            raise ValueError("start_review request_id is required")
        if self.expected_version is not None:
            raise ValueError("start_review expected_version must be null")
        if len(self.input_refs) != 1:
            raise ValueError("start_review requires one ready document bundle ref")
        ref = self.input_refs[0]
        if ref.artifact_type is not AgentArtifactType.document_bundle:
            raise ValueError("start_review ref must be a document bundle")
        if ref.artifact_id != str(self.payload.bundle_id):
            raise ValueError("start_review bundle ref and payload must match")
        if ref.version is None or ref.sha256 is None:
            raise ValueError("start_review bundle ref must include version and hash")
        return self


class RetryAttemptCommand(AgentCommand[RetryAttemptPayload]):
    @model_validator(mode="after")
    def validate_retry_attempt(self) -> RetryAttemptCommand:
        _require_action(self, AgentAction.retry_attempt)
        if self.aggregate.aggregate_type is not AgentAggregateType.deep_review:
            raise ValueError("retry_attempt targets a deep review")
        if self.request_id is None:
            raise ValueError("retry_attempt request_id is required")
        if self.expected_version is not None:
            raise ValueError("retry_attempt expected_version must be null")
        if len(self.input_refs) != 1:
            raise ValueError("retry_attempt requires one current attempt ref")
        ref = self.input_refs[0]
        if ref.artifact_type is not AgentArtifactType.deep_review_attempt:
            raise ValueError("retry_attempt ref must be a deep review attempt")
        if ref.version is None or ref.sha256 is not None:
            raise ValueError("retry_attempt ref must include its sequence and no hash")
        return self


DeepReviewStartCommand = StartReviewCommand
DeepReviewRetryCommand = RetryAttemptCommand
StartReviewAction = StartReviewPayload
RetryAttemptAction = RetryAttemptPayload

DeepReviewActionCommand: TypeAlias = StartReviewCommand | RetryAttemptCommand


__all__ = [
    "DeepReviewActionCommand",
    "DeepReviewRetryCommand",
    "DeepReviewStartCommand",
    "RetryAttemptAction",
    "RetryAttemptCommand",
    "RetryAttemptPayload",
    "StartReviewAction",
    "StartReviewCommand",
    "StartReviewPayload",
]
