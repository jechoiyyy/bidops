"""Strict commands for the document-preparation workflow.

The common agent envelope deliberately remains generic.  This module closes
that envelope for the four document actions and keeps the multipart upload
capability outside the serialized command.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from ..common import (
    AgentAction,
    AgentAggregateType,
    AgentArtifactType,
    AgentCommand,
)


DocumentRole: TypeAlias = Literal[
    "공고",
    "정정",
    "제안요청서",
    "과업지시서",
    "내역서",
    "제출서식",
    "부록",
    "기타",
]


class _StrictPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=False,
        validate_assignment=True,
    )


class EmptyActionPayload(_StrictPayload):
    """The intentionally empty payload used by start/upload actions."""


class StartBundlePayload(EmptyActionPayload):
    pass


class RegisterDocumentPayload(EmptyActionPayload):
    pass


class UpdateDocumentMetadataPayload(_StrictPayload):
    role: DocumentRole
    effective_date: date | None
    replaces_document_version_id: UUID | None
    is_current: StrictBool


class ConfirmedDocumentPayload(_StrictPayload):
    document_version_id: UUID
    version: StrictInt = Field(ge=1)


class ConfirmReadyPayload(_StrictPayload):
    confirmed_documents: list[ConfirmedDocumentPayload]

    @model_validator(mode="after")
    def confirmed_documents_are_unique(self) -> ConfirmReadyPayload:
        identities = [
            (item.document_version_id, item.version)
            for item in self.confirmed_documents
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("confirmed_documents must not contain duplicate IDs/versions")
        if len({item.document_version_id for item in self.confirmed_documents}) != len(self.confirmed_documents):
            raise ValueError("confirmed_documents must not contain duplicate document IDs")
        return self


def _require_action(command: AgentCommand[BaseModel], action: AgentAction) -> None:
    if command.agent_name.value != "document_preparation" or command.action is not action:
        raise ValueError("command action does not belong to document preparation")


class StartBundleCommand(AgentCommand[StartBundlePayload]):
    @model_validator(mode="after")
    def validate_start_bundle(self) -> StartBundleCommand:
        _require_action(self, AgentAction.start_bundle)
        if self.aggregate.aggregate_type is not AgentAggregateType.notice:
            raise ValueError("start_bundle targets a notice")
        if self.request_id is not None:
            raise ValueError("start_bundle request_id must be null")
        if self.expected_version is not None:
            raise ValueError("start_bundle expected_version must be null")
        if self.input_refs:
            raise ValueError("start_bundle input_refs must be empty")
        if self.correlation_id is not None:
            raise ValueError("start_bundle correlation_id is allocated by the adapter")
        return self


class RegisterDocumentCommand(AgentCommand[RegisterDocumentPayload]):
    @model_validator(mode="after")
    def validate_register_document(self) -> RegisterDocumentCommand:
        _require_action(self, AgentAction.register_document)
        if self.aggregate.aggregate_type is not AgentAggregateType.document_bundle:
            raise ValueError("register_document targets a document bundle")
        if self.request_id is None:
            raise ValueError("register_document request_id is required")
        if self.expected_version is not None:
            raise ValueError("register_document expected_version must be null")
        if self.input_refs:
            raise ValueError("register_document input_refs must be empty")
        return self


class UpdateDocumentMetadataCommand(AgentCommand[UpdateDocumentMetadataPayload]):
    @model_validator(mode="after")
    def validate_update_document_metadata(self) -> UpdateDocumentMetadataCommand:
        _require_action(self, AgentAction.update_document_metadata)
        if self.aggregate.aggregate_type is not AgentAggregateType.document_version:
            raise ValueError("update_document_metadata targets a document version")
        if self.request_id is not None:
            raise ValueError("update_document_metadata request_id must be null")
        if self.expected_version is None or self.expected_version < 1:
            raise ValueError("update_document_metadata expected_version is required")
        if len(self.input_refs) != 1:
            raise ValueError("update_document_metadata requires one latest bundle ref")
        ref = self.input_refs[0]
        if ref.artifact_type is not AgentArtifactType.document_bundle:
            raise ValueError("update_document_metadata ref must be a document bundle")
        return self


class ConfirmReadyCommand(AgentCommand[ConfirmReadyPayload]):
    @model_validator(mode="after")
    def validate_confirm_ready(self) -> ConfirmReadyCommand:
        _require_action(self, AgentAction.confirm_ready)
        if self.aggregate.aggregate_type is not AgentAggregateType.document_bundle:
            raise ValueError("confirm_ready targets a document bundle")
        if self.request_id is None:
            raise ValueError("confirm_ready request_id is required")
        if self.expected_version is None or self.expected_version < 1:
            raise ValueError("confirm_ready expected_version is required")
        ref_identities = [
            (ref.artifact_id, ref.version)
            for ref in self.input_refs
            if ref.artifact_type is AgentArtifactType.document_version
        ]
        if len(ref_identities) != len(self.input_refs):
            raise ValueError("confirm_ready refs must be document versions")
        payload_identities = [
            (str(item.document_version_id), item.version)
            for item in self.payload.confirmed_documents
        ]
        if ref_identities != payload_identities:
            raise ValueError("confirm_ready refs and payload must have the same ordinal order")
        return self


DocumentPreparationStartCommand = StartBundleCommand
DocumentPreparationRegisterCommand = RegisterDocumentCommand
DocumentPreparationMetadataCommand = UpdateDocumentMetadataCommand
DocumentPreparationConfirmCommand = ConfirmReadyCommand

DocumentPreparationActionCommand: TypeAlias = (
    StartBundleCommand
    | RegisterDocumentCommand
    | UpdateDocumentMetadataCommand
    | ConfirmReadyCommand
)

# The shorter names are useful to callers that use action rather than
# payload terminology; they are aliases, not second wire contracts.
StartBundleAction = StartBundlePayload
RegisterDocumentAction = RegisterDocumentPayload
UpdateDocumentMetadataAction = UpdateDocumentMetadataPayload
ConfirmReadyAction = ConfirmReadyPayload


__all__ = [
    "ConfirmReadyAction",
    "ConfirmReadyCommand",
    "ConfirmReadyPayload",
    "ConfirmedDocumentPayload",
    "DocumentPreparationActionCommand",
    "DocumentPreparationConfirmCommand",
    "DocumentPreparationMetadataCommand",
    "DocumentPreparationRegisterCommand",
    "DocumentPreparationStartCommand",
    "DocumentRole",
    "EmptyActionPayload",
    "RegisterDocumentAction",
    "RegisterDocumentCommand",
    "RegisterDocumentPayload",
    "StartBundleAction",
    "StartBundleCommand",
    "StartBundlePayload",
    "UpdateDocumentMetadataAction",
    "UpdateDocumentMetadataCommand",
    "UpdateDocumentMetadataPayload",
]
