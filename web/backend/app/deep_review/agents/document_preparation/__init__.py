"""Document preparation agent commands, projection, and adapter."""

from .agent import DocumentPreparationAgent
from .commands import (
    ConfirmReadyAction,
    ConfirmReadyCommand,
    ConfirmReadyPayload,
    ConfirmedDocumentPayload,
    DocumentPreparationActionCommand,
    DocumentPreparationConfirmCommand,
    DocumentPreparationMetadataCommand,
    DocumentPreparationRegisterCommand,
    DocumentPreparationStartCommand,
    DocumentRole,
    EmptyActionPayload,
    RegisterDocumentAction,
    RegisterDocumentCommand,
    RegisterDocumentPayload,
    StartBundleAction,
    StartBundleCommand,
    StartBundlePayload,
    UpdateDocumentMetadataAction,
    UpdateDocumentMetadataCommand,
    UpdateDocumentMetadataPayload,
)
from .projection import (
    STEP_NAMES,
    build_document_preparation_run,
    project,
    project_bundle,
    project_document_preparation,
    project_run,
)

__all__ = [name for name in globals() if not name.startswith("_")]
