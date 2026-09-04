"""Decision agent command, projection, and service adapter."""

from .agent import DecisionAgent
from .commands import (
    CreateFullRevisionCommand,
    CreateFullRevisionPayload,
    DecisionActionCommand,
    FinalOpinionPayload,
    FullRevisionPayload,
    RecordFinalOpinionCommand,
    RecordFinalOpinionPayload,
)
from .projection import (
    DecisionProjectionError,
    STEP_NAMES,
    build_decision_run,
    canonical_json_hash,
    evidence_artifact_ref,
    final_opinion_artifact_ref,
    final_opinion_snapshot_payload,
    final_opinion_snapshot_sha256,
    project_decision,
    validation_artifact_ref,
    validation_snapshot_payload,
    validation_snapshot_sha256,
)

__all__ = [
    "CreateFullRevisionCommand",
    "CreateFullRevisionPayload",
    "DecisionActionCommand",
    "DecisionAgent",
    "DecisionProjectionError",
    "FinalOpinionPayload",
    "FullRevisionPayload",
    "RecordFinalOpinionCommand",
    "RecordFinalOpinionPayload",
    "STEP_NAMES",
    "build_decision_run",
    "canonical_json_hash",
    "evidence_artifact_ref",
    "final_opinion_artifact_ref",
    "final_opinion_snapshot_payload",
    "final_opinion_snapshot_sha256",
    "project_decision",
    "validation_artifact_ref",
    "validation_snapshot_payload",
    "validation_snapshot_sha256",
]
