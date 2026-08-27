"""Closed, dependency-free contracts shared by the BidOps agents.

The models in this module are application contracts rather than persistence
models.  In particular, they deliberately contain only safe identifiers and
references; storage paths, credentials, source bytes, prompts, and model
responses do not belong here.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import Generic, Literal, Protocol, TypeVar
from unicodedata import category, normalize
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


class AgentName(str, Enum):
    """The closed set of agent names in the v1 contract."""

    opportunity_discovery = "opportunity_discovery"
    document_preparation = "document_preparation"
    deep_review = "deep_review"
    decision = "decision"

    # Upper-case aliases keep normal Python enum spelling available without
    # adding values to the wire-level enum.
    OPPORTUNITY_DISCOVERY = opportunity_discovery
    DOCUMENT_PREPARATION = document_preparation
    DEEP_REVIEW = deep_review
    DECISION = decision


class AgentRunStatus(str, Enum):
    queued = "queued"
    running = "running"
    waiting_human = "waiting_human"
    blocked = "blocked"
    completed = "completed"
    failed = "failed"
    superseded = "superseded"
    cancelled = "cancelled"

    QUEUED = queued
    RUNNING = running
    WAITING_HUMAN = waiting_human
    BLOCKED = blocked
    COMPLETED = completed
    FAILED = failed
    SUPERSEDED = superseded
    CANCELLED = cancelled


class AgentStepStatus(str, Enum):
    queued = "queued"
    running = "running"
    waiting_human = "waiting_human"
    blocked = "blocked"
    completed = "completed"
    failed = "failed"
    superseded = "superseded"
    cancelled = "cancelled"

    QUEUED = queued
    RUNNING = running
    WAITING_HUMAN = waiting_human
    BLOCKED = blocked
    COMPLETED = completed
    FAILED = failed
    SUPERSEDED = superseded
    CANCELLED = cancelled


class AgentAction(str, Enum):
    start_bundle = "start_bundle"
    register_document = "register_document"
    update_document_metadata = "update_document_metadata"
    confirm_ready = "confirm_ready"
    start_review = "start_review"
    retry_attempt = "retry_attempt"
    create_full_revision = "create_full_revision"
    record_final_opinion = "record_final_opinion"

    START_BUNDLE = start_bundle
    REGISTER_DOCUMENT = register_document
    UPDATE_DOCUMENT_METADATA = update_document_metadata
    CONFIRM_READY = confirm_ready
    START_REVIEW = start_review
    RETRY_ATTEMPT = retry_attempt
    CREATE_FULL_REVISION = create_full_revision
    RECORD_FINAL_OPINION = record_final_opinion


class AgentAggregateType(str, Enum):
    notice = "notice"
    document_bundle = "document_bundle"
    document_version = "document_version"
    deep_review = "deep_review"

    NOTICE = notice
    DOCUMENT_BUNDLE = document_bundle
    DOCUMENT_VERSION = document_version
    DEEP_REVIEW = deep_review


class AgentArtifactType(str, Enum):
    effective_grade_snapshot = "effective_grade_snapshot"
    document_version = "document_version"
    document_structure = "document_structure"
    document_bundle = "document_bundle"
    profile_version = "profile_version"
    policy_version = "policy_version"
    deep_review_attempt = "deep_review_attempt"
    deep_review_stage = "deep_review_stage"
    report_revision = "report_revision"
    validation_run = "validation_run"
    evidence = "evidence"
    final_opinion = "final_opinion"

    EFFECTIVE_GRADE_SNAPSHOT = effective_grade_snapshot
    DOCUMENT_VERSION = document_version
    DOCUMENT_STRUCTURE = document_structure
    DOCUMENT_BUNDLE = document_bundle
    PROFILE_VERSION = profile_version
    POLICY_VERSION = policy_version
    DEEP_REVIEW_ATTEMPT = deep_review_attempt
    DEEP_REVIEW_STAGE = deep_review_stage
    REPORT_REVISION = report_revision
    VALIDATION_RUN = validation_run
    EVIDENCE = evidence
    FINAL_OPINION = final_opinion


class AgentErrorCode(str, Enum):
    invalid_request = "invalid_request"
    actor_name_required = "actor_name_required"
    actor_name_invalid = "actor_name_invalid"
    not_found = "not_found"
    effective_grade_ineligible = "effective_grade_ineligible"
    bundle_not_ready = "bundle_not_ready"
    bundle_has_blocking_issues = "bundle_has_blocking_issues"
    unsafe_document = "unsafe_document"
    structure_unavailable = "structure_unavailable"
    version_conflict = "version_conflict"
    idempotency_conflict = "idempotency_conflict"
    active_attempt_exists = "active_attempt_exists"
    review_not_ready = "review_not_ready"
    evidence_out_of_scope = "evidence_out_of_scope"
    validation_failed = "validation_failed"
    factual_change_evidence_required = "factual_change_evidence_required"
    final_opinion_reason_required = "final_opinion_reason_required"
    service_unavailable = "service_unavailable"
    processing_failed = "processing_failed"

    INVALID_REQUEST = invalid_request
    ACTOR_NAME_REQUIRED = actor_name_required
    ACTOR_NAME_INVALID = actor_name_invalid
    NOT_FOUND = not_found
    EFFECTIVE_GRADE_INELIGIBLE = effective_grade_ineligible
    BUNDLE_NOT_READY = bundle_not_ready
    BUNDLE_HAS_BLOCKING_ISSUES = bundle_has_blocking_issues
    UNSAFE_DOCUMENT = unsafe_document
    STRUCTURE_UNAVAILABLE = structure_unavailable
    VERSION_CONFLICT = version_conflict
    IDEMPOTENCY_CONFLICT = idempotency_conflict
    ACTIVE_ATTEMPT_EXISTS = active_attempt_exists
    REVIEW_NOT_READY = review_not_ready
    EVIDENCE_OUT_OF_SCOPE = evidence_out_of_scope
    VALIDATION_FAILED = validation_failed
    FACTUAL_CHANGE_EVIDENCE_REQUIRED = factual_change_evidence_required
    FINAL_OPINION_REASON_REQUIRED = final_opinion_reason_required
    SERVICE_UNAVAILABLE = service_unavailable
    PROCESSING_FAILED = processing_failed


class AgentWaitReason(str, Enum):
    document_registration_required = "document_registration_required"
    document_metadata_confirmation_required = "document_metadata_confirmation_required"
    document_blocking_issues_resolution_required = "document_blocking_issues_resolution_required"
    machine_report_required = "machine_report_required"
    report_review_required = "report_review_required"
    final_opinion_required = "final_opinion_required"

    DOCUMENT_REGISTRATION_REQUIRED = document_registration_required
    DOCUMENT_METADATA_CONFIRMATION_REQUIRED = document_metadata_confirmation_required
    DOCUMENT_BLOCKING_ISSUES_RESOLUTION_REQUIRED = document_blocking_issues_resolution_required
    MACHINE_REPORT_REQUIRED = machine_report_required
    REPORT_REVIEW_REQUIRED = report_review_required
    FINAL_OPINION_REQUIRED = final_opinion_required


class AgentOutcomeCode(str, Enum):
    ready_bundle = "ready_bundle"
    superseded_by_new_bundle = "superseded_by_new_bundle"
    report_ready_validated = "report_ready_validated"
    report_ready_validation_failed = "report_ready_validation_failed"
    superseded_by_retry = "superseded_by_retry"
    final_opinion_recorded = "final_opinion_recorded"

    READY_BUNDLE = ready_bundle
    SUPERSEDED_BY_NEW_BUNDLE = superseded_by_new_bundle
    REPORT_READY_VALIDATED = report_ready_validated
    REPORT_READY_VALIDATION_FAILED = report_ready_validation_failed
    SUPERSEDED_BY_RETRY = superseded_by_retry
    FINAL_OPINION_RECORDED = final_opinion_recorded


class AgentActorKind(str, Enum):
    human = "human"
    system = "system"

    HUMAN = human
    SYSTEM = system


# A short alias is useful to callers that use the generic name from the
# contract prose, while AgentActorKind remains the descriptive public name.
ActorKind = AgentActorKind


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=False,
        validate_assignment=True,
    )


def _nonblank_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ValueError("identifier must not be blank")
    return value


def _nonnegative(value: int) -> int:
    if value < 0:
        raise ValueError("value must not be negative")
    return value


def _aware_timestamp(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp must be timezone-aware")
    return value


def _normalise_human_name(value: str) -> str:
    # NFC prevents visually equivalent names from being represented in two
    # ways, while leaving ordinary display text untouched apart from the
    # required surrounding trim.
    normalised = normalize("NFC", value.strip())
    if not normalised or any(not character.isprintable() or category(character) == "Cc" for character in normalised):
        raise ValueError("human actor name is invalid")
    # Compare a compatibility-normalised copy so full-width/confusable forms
    # cannot bypass the reserved system actor name, but retain the NFC display
    # value in the model.
    if normalize("NFKC", normalised).casefold() == "system":
        raise ValueError("system is reserved for system actors")
    return normalised


class AgentAggregateRef(_StrictModel):
    aggregate_type: AgentAggregateType
    aggregate_id: StrictStr

    _validate_aggregate_id = field_validator("aggregate_id")(_nonblank_identifier)


_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class AgentArtifactRef(_StrictModel):
    artifact_type: AgentArtifactType
    artifact_id: StrictStr
    version: StrictInt | None = None
    sha256: StrictStr | None = None

    _validate_artifact_id = field_validator("artifact_id")(_nonblank_identifier)

    @field_validator("version")
    @classmethod
    def version_is_nonnegative(cls, value: int | None) -> int | None:
        return None if value is None else _nonnegative(value)

    @field_validator("sha256")
    @classmethod
    def sha256_is_lower_hex(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(_SHA256_PATTERN, value) is None:
            raise ValueError("sha256 must be lowercase hexadecimal")
        return value


class AgentActorRef(_StrictModel):
    actor_kind: AgentActorKind
    claimed_name: StrictStr | None = None

    @model_validator(mode="after")
    def validate_actor(self) -> AgentActorRef:
        if self.actor_kind is AgentActorKind.system:
            if self.claimed_name is not None:
                raise ValueError("system actors must not claim a name")
            return self
        if self.claimed_name is None:
            raise ValueError("human actors require a claimed name")
        object.__setattr__(self, "claimed_name", _normalise_human_name(self.claimed_name))
        return self


class AgentErrorDetails(_StrictModel):
    field: StrictStr | None = None
    reason: StrictStr | None = None


class AgentSafeError(_StrictModel):
    code: AgentErrorCode
    message: StrictStr
    retryable: StrictBool
    details: AgentErrorDetails | None = None

    @model_validator(mode="after")
    def validate_safe_error(self) -> AgentSafeError:
        # Import lazily so errors.py can use the contract enums and models
        # without introducing a module import cycle.
        from .errors import safe_error_spec

        expected = safe_error_spec(self.code)
        if self.message != expected.message or self.retryable is not expected.retryable:
            raise ValueError("message and retryable must match the fixed safe error mapping")
        if self.details is not None:
            raise ValueError("details must be null in v1")
        return self


class AgentWait(_StrictModel):
    reason_code: AgentWaitReason
    message: StrictStr
    required_actions: list[AgentAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_wait(self) -> AgentWait:
        from .errors import wait_spec

        expected = wait_spec(self.reason_code)
        if self.message != expected.message or tuple(self.required_actions) != expected.required_actions:
            raise ValueError("message and required_actions must match the fixed wait mapping")
        return self


class AgentStepView(_StrictModel):
    step_name: StrictStr
    sequence: StrictInt
    status: AgentStepStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_error_code: AgentErrorCode | None = None

    _validate_step_name = field_validator("step_name")(_nonblank_identifier)

    @field_validator("sequence")
    @classmethod
    def sequence_is_nonnegative(cls, value: int) -> int:
        return _nonnegative(value)

    _validate_step_started_at = field_validator("started_at", "completed_at")(_aware_timestamp)


def _artifact_ref_identity(ref: AgentArtifactRef) -> tuple[AgentArtifactType, str, int | None, str | None]:
    return ref.artifact_type, ref.artifact_id, ref.version, ref.sha256


def _refs_are_unique(refs: list[AgentArtifactRef], field_name: str) -> None:
    identities = [_artifact_ref_identity(ref) for ref in refs]
    if len(identities) != len(set(identities)):
        raise ValueError(f"{field_name} must not contain duplicate references")


class AgentRunView(_StrictModel):
    schema: Literal["bidops.agent-run.v1"]
    agent_name: AgentName
    run_id: StrictStr
    aggregate: AgentAggregateRef
    execution_ref: AgentArtifactRef | None = None
    status: AgentRunStatus
    outcome_code: AgentOutcomeCode | None = None
    current_step: StrictStr | None = None
    steps: list[AgentStepView] = Field(default_factory=list)
    input_refs: list[AgentArtifactRef] = Field(default_factory=list)
    output_refs: list[AgentArtifactRef] = Field(default_factory=list)
    wait: AgentWait | None = None
    error: AgentSafeError | None = None
    available_actions: list[AgentAction] = Field(default_factory=list)
    correlation_id: UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    updated_at: datetime
    completed_at: datetime | None = None

    _validate_run_id = field_validator("run_id")(_nonblank_identifier)
    _validate_current_step = field_validator("current_step")(_nonblank_identifier)
    _validate_run_timestamps = field_validator(
        "created_at", "started_at", "updated_at", "completed_at"
    )(_aware_timestamp)

    @model_validator(mode="after")
    def validate_run_invariants(self) -> AgentRunView:
        _refs_are_unique(self.input_refs, "input_refs")
        _refs_are_unique(self.output_refs, "output_refs")

        sequences = [step.sequence for step in self.steps]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("steps must be ordered by unique sequence")

        if len(self.available_actions) != len(set(self.available_actions)):
            raise ValueError("available_actions must not contain duplicates")
        action_order = {action: index for index, action in enumerate(AgentAction)}
        if self.available_actions != sorted(self.available_actions, key=action_order.__getitem__):
            raise ValueError("available_actions must follow the AgentAction declaration order")

        if self.wait is not None and self.status not in {
            AgentRunStatus.waiting_human,
            AgentRunStatus.blocked,
        }:
            raise ValueError("wait is only valid for waiting_human or blocked runs")

        if self.error is not None:
            valid_failed_superseded = (
                self.status is AgentRunStatus.failed
                or (
                    self.status is AgentRunStatus.superseded
                    and self.outcome_code is AgentOutcomeCode.superseded_by_retry
                )
            )
            if not valid_failed_superseded:
                raise ValueError("error is only valid for failed or failed-then-superseded runs")

        if self.wait is not None and self.error is not None:
            raise ValueError("wait and error cannot be present together")

        if self.status in {AgentRunStatus.completed, AgentRunStatus.superseded} and self.current_step is not None:
            raise ValueError("completed and superseded runs must not have a current_step")
        return self


TAction = TypeVar("TAction", bound=BaseModel)
TDomain = TypeVar("TDomain", bound=BaseModel)


class AgentCommand(_StrictModel, Generic[TAction]):
    schema: Literal["bidops.agent-command.v1"]
    agent_name: AgentName
    action: AgentAction
    aggregate: AgentAggregateRef
    actor: AgentActorRef
    request_id: UUID | None = None
    correlation_id: UUID | None = None
    expected_version: StrictInt | None = None
    input_refs: list[AgentArtifactRef] = Field(default_factory=list)
    payload: TAction

    @field_validator("expected_version")
    @classmethod
    def expected_version_is_nonnegative(cls, value: int | None) -> int | None:
        return None if value is None else _nonnegative(value)

    @field_validator("input_refs")
    @classmethod
    def command_refs_are_unique(cls, value: list[AgentArtifactRef]) -> list[AgentArtifactRef]:
        _refs_are_unique(value, "input_refs")
        return value

    @model_validator(mode="after")
    def payload_is_named_strict_model(self) -> AgentCommand[TAction]:
        if not isinstance(self.payload, BaseModel):
            raise ValueError("payload must be a named Pydantic model")
        if self.payload.model_config.get("extra") != "forbid":
            raise ValueError("payload must use extra='forbid'")
        return self


class AgentActionResult(_StrictModel, Generic[TDomain]):
    run: AgentRunView
    result: TDomain

    @model_validator(mode="after")
    def result_is_named_strict_model(self) -> AgentActionResult[TDomain]:
        if not isinstance(self.result, BaseModel):
            raise ValueError("result must be a named Pydantic model")
        if self.result.model_config.get("extra") != "forbid":
            raise ValueError("result must use extra='forbid'")
        return self


StartCommandT = TypeVar("StartCommandT")
ActionCommandT = TypeVar("ActionCommandT")


class WorkflowAgent(Protocol, Generic[StartCommandT, ActionCommandT]):
    name: AgentName

    def start(self, command: StartCommandT) -> AgentRunView: ...

    def act(self, command: ActionCommandT) -> AgentRunView: ...

    def status(self, aggregate: AgentAggregateRef) -> AgentRunView: ...


__all__ = [
    "ActorKind",
    "AgentAction",
    "AgentActionResult",
    "AgentActorKind",
    "AgentActorRef",
    "AgentAggregateRef",
    "AgentAggregateType",
    "AgentArtifactRef",
    "AgentArtifactType",
    "AgentCommand",
    "AgentErrorCode",
    "AgentErrorDetails",
    "AgentName",
    "AgentOutcomeCode",
    "AgentRunStatus",
    "AgentRunView",
    "AgentSafeError",
    "AgentStepStatus",
    "AgentStepView",
    "AgentWait",
    "AgentWaitReason",
    "ActionCommandT",
    "StartCommandT",
    "TAction",
    "TDomain",
    "WorkflowAgent",
]
