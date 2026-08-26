"""Deep-review Agent commands, projection, and service adapter."""

from .agent import DeepReviewAgent
from .commands import (
    DeepReviewActionCommand,
    DeepReviewRetryCommand,
    DeepReviewStartCommand,
    RetryAttemptAction,
    RetryAttemptCommand,
    RetryAttemptPayload,
    StartReviewAction,
    StartReviewCommand,
    StartReviewPayload,
)
from .projection import (
    STAGE_NAMES,
    STAGE_SEQUENCE,
    DeepReviewProjectionError,
    attempt_artifact_ref,
    bundle_artifact_ref,
    bundle_snapshot_sha256,
    project,
    project_deep_review,
    project_review,
    project_run,
)

__all__ = [
    "DeepReviewActionCommand",
    "DeepReviewAgent",
    "DeepReviewProjectionError",
    "DeepReviewRetryCommand",
    "DeepReviewStartCommand",
    "RetryAttemptAction",
    "RetryAttemptCommand",
    "RetryAttemptPayload",
    "STAGE_NAMES",
    "STAGE_SEQUENCE",
    "StartReviewAction",
    "StartReviewCommand",
    "StartReviewPayload",
    "attempt_artifact_ref",
    "bundle_artifact_ref",
    "bundle_snapshot_sha256",
    "project",
    "project_deep_review",
    "project_review",
    "project_run",
]
