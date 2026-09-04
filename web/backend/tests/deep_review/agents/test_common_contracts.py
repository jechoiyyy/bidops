"""T2 contract and pure-projection tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.deep_review.agents.common import (
    AgentAction,
    AgentActionResult,
    AgentActorRef,
    AgentAggregateRef,
    AgentAggregateType,
    AgentArtifactRef,
    AgentArtifactType,
    AgentCommand,
    AgentErrorCode,
    AgentName,
    AgentOutcomeCode,
    AgentRunStatus,
    AgentRunView,
    AgentSafeError,
    AgentStepStatus,
    AgentStepView,
    AgentWait,
    AgentWaitReason,
    classify_error_code,
    decision_run_id,
    deep_review_run_id,
    document_preparation_run_id,
    latest_timestamp,
    make_safe_error,
    make_wait,
    sort_unique_refs,
)
from app.deep_review.agents.common.errors import SAFE_ERROR_MAPPING, WAIT_MAPPING


NOW = datetime(2026, 8, 26, 1, 2, 3, tzinfo=UTC)


def artifact(identifier: str, *, version: int | None = None) -> AgentArtifactRef:
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.document_version,
        artifact_id=identifier,
        version=version,
        sha256=None,
    )


def aggregate() -> AgentAggregateRef:
    return AgentAggregateRef(aggregate_type=AgentAggregateType.notice, aggregate_id="notice-1")


def run(**overrides: object) -> AgentRunView:
    values: dict[str, object] = {
        "schema": "bidops.agent-run.v1",
        "agent_name": AgentName.deep_review,
        "run_id": "deep-review:review-1:attempt:attempt-1",
        "aggregate": aggregate(),
        "execution_ref": None,
        "status": AgentRunStatus.running,
        "outcome_code": None,
        "current_step": "requirements_and_evaluation",
        "steps": [
            AgentStepView(
                step_name="requirements_and_evaluation",
                sequence=0,
                status=AgentStepStatus.running,
                started_at=NOW,
                completed_at=None,
                last_error_code=None,
            )
        ],
        "input_refs": [artifact("bundle-1")],
        "output_refs": [],
        "wait": None,
        "error": None,
        "available_actions": [AgentAction.retry_attempt],
        "correlation_id": None,
        "created_at": NOW,
        "started_at": NOW,
        "updated_at": NOW,
        "completed_at": None,
    }
    values.update(overrides)
    return AgentRunView(**values)


@pytest.mark.parametrize(
    ("enum_type", "value"),
    [
        (AgentName, "unknown"),
        (AgentRunStatus, "done"),
        (AgentAction, "cancel"),
        (AgentErrorCode, "secret_error"),
    ],
)
def test_unknown_enum_values_are_rejected(enum_type: type[object], value: str) -> None:
    with pytest.raises(ValueError):
        enum_type(value)  # type: ignore[call-arg]


def test_models_reject_extra_fields_and_blank_identifiers() -> None:
    with pytest.raises(ValidationError):
        AgentAggregateRef(aggregate_type="notice", aggregate_id="notice-1", internal_path="/secret")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        AgentAggregateRef(aggregate_type="notice", aggregate_id="   ")
    with pytest.raises(ValidationError):
        AgentArtifactRef(artifact_type="evidence", artifact_id="")


@pytest.mark.parametrize("name", [None, "", "   ", "SYSTEM", "system\nname", "system\x00name"])
def test_actor_boundaries_are_closed(name: str | None) -> None:
    with pytest.raises(ValidationError):
        AgentActorRef(actor_kind="human", claimed_name=name)
    with pytest.raises(ValidationError):
        AgentActorRef(actor_kind="system", claimed_name="worker")
    actor = AgentActorRef(actor_kind="human", claimed_name="  Alice  ")
    assert actor.claimed_name == "Alice"
    assert AgentActorRef(actor_kind="system", claimed_name=None).claimed_name is None


@pytest.mark.parametrize("value", ["A" * 64, "g" * 64, "a" * 63, "a" * 65])
def test_sha256_requires_lowercase_hex_64(value: str) -> None:
    with pytest.raises(ValidationError):
        AgentArtifactRef(artifact_type="evidence", artifact_id="e-1", sha256=value)


def test_negative_versions_and_sequences_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentArtifactRef(artifact_type="evidence", artifact_id="e-1", version=-1)
    with pytest.raises(ValidationError):
        AgentStepView(step_name="one", sequence=-1, status="queued")


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentStepView(step_name="one", sequence=0, status="queued", started_at=datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        run(created_at=datetime(2026, 1, 1))


def test_fixed_safe_error_table_and_no_details() -> None:
    assert len(SAFE_ERROR_MAPPING) == 19
    for code, spec in SAFE_ERROR_MAPPING.items():
        error = make_safe_error(code)
        assert error.code is code
        assert error.message == spec.message
        assert error.retryable is spec.retryable
        assert error.details is None
        with pytest.raises(ValidationError):
            AgentSafeError(code=code, message="internal detail", retryable=spec.retryable)
        with pytest.raises(ValidationError):
            AgentSafeError(code=code, message=spec.message, retryable=spec.retryable, details={"field": "x"})


def test_safe_error_collapses_legacy_and_internal_codes_without_message_leak() -> None:
    assert classify_error_code("malware_detected") is AgentErrorCode.unsafe_document
    assert classify_error_code("provider_unavailable") is AgentErrorCode.service_unavailable
    assert classify_error_code("some_internal_exception") is AgentErrorCode.processing_failed
    error = make_safe_error("some_internal_exception")
    assert "some_internal_exception" not in error.message


def test_fixed_wait_table() -> None:
    assert len(WAIT_MAPPING) == 6
    for reason, spec in WAIT_MAPPING.items():
        waiting = make_wait(reason)
        assert waiting.reason_code is reason
        assert waiting.message == spec.message
        assert tuple(waiting.required_actions) == spec.required_actions
        with pytest.raises(ValidationError):
            AgentWait(reason_code=reason, message="internal wait", required_actions=[])


def test_reference_collections_and_step_order_are_validated() -> None:
    duplicate = artifact("same")
    with pytest.raises(ValidationError):
        run(input_refs=[duplicate, duplicate])
    with pytest.raises(ValidationError):
        run(
            steps=[
                AgentStepView(step_name="two", sequence=2, status="queued"),
                AgentStepView(step_name="one", sequence=1, status="queued"),
            ]
        )
    with pytest.raises(ValidationError):
        run(available_actions=[AgentAction.retry_attempt, AgentAction.retry_attempt])
    with pytest.raises(ValidationError):
        run(available_actions=[AgentAction.retry_attempt, AgentAction.start_review])


def test_run_status_invariants_keep_wait_and_error_closed() -> None:
    waiting = run(status=AgentRunStatus.waiting_human, current_step=None, wait=make_wait(AgentWaitReason.machine_report_required))
    assert waiting.wait is not None
    with pytest.raises(ValidationError):
        run(status=AgentRunStatus.completed, current_step=None, wait=make_wait(AgentWaitReason.machine_report_required))
    with pytest.raises(ValidationError):
        run(status=AgentRunStatus.completed, current_step="leftover")
    with pytest.raises(ValidationError):
        run(status=AgentRunStatus.completed, current_step=None, error=make_safe_error(AgentErrorCode.validation_failed))
    failed = run(status=AgentRunStatus.failed, current_step="failed-step", error=make_safe_error(AgentErrorCode.processing_failed))
    assert failed.error is not None
    superseded = run(
        status=AgentRunStatus.superseded,
        outcome_code=AgentOutcomeCode.superseded_by_retry,
        current_step=None,
        error=make_safe_error(AgentErrorCode.processing_failed),
    )
    assert superseded.error is not None


def test_fixed_schema_and_correlation_round_trip_are_deterministic() -> None:
    correlation = uuid4()
    first = run(correlation_id=correlation)
    second = AgentRunView.model_validate(first.model_dump())
    assert first.model_dump() == second.model_dump()
    assert second.correlation_id == correlation
    assert run().correlation_id is None
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str


def test_command_preserves_named_payload_and_rejects_payload_extra() -> None:
    payload = StrictPayload(bundle_id="bundle-1")
    command = AgentCommand[StrictPayload](
        schema="bidops.agent-command.v1",
        agent_name="deep_review",
        action="start_review",
        aggregate=aggregate(),
        actor={"actor_kind": "human", "claimed_name": "Reviewer"},
        request_id=None,
        correlation_id=None,
        expected_version=None,
        input_refs=[],
        payload=payload,
    )
    assert command.payload is payload
    assert command.model_dump()["payload"] == {"bundle_id": "bundle-1"}
    with pytest.raises(ValidationError):
        AgentCommand[StrictPayload](
            schema="bidops.agent-command.v1",
            agent_name="document_preparation",
            action="start_bundle",
            aggregate=aggregate(),
            actor={"actor_kind": "system", "claimed_name": None},
            input_refs=[],
            payload={"bundle_id": "bundle-1", "raw_model_output": "secret"},
        )


class DomainResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


def test_generic_action_result_preserves_named_domain_model() -> None:
    result = AgentActionResult[DomainResult](run=run(), result=DomainResult(value="ok"))
    assert isinstance(result.result, DomainResult)
    assert result.model_dump()["result"] == {"value": "ok"}


def test_pure_projection_helpers_are_deterministic_and_side_effect_free() -> None:
    later = NOW + timedelta(seconds=2)
    assert latest_timestamp() is None
    assert latest_timestamp([None, NOW, later]) == later
    assert latest_timestamp(NOW, None) == NOW
    with pytest.raises(ValueError):
        latest_timestamp(datetime(2026, 1, 1))

    refs = [artifact("b"), artifact("a"), artifact("c")]
    original = list(refs)
    assert [ref.artifact_id for ref in sort_unique_refs(refs)] == ["a", "b", "c"]
    assert refs == original
    assert [ref.artifact_id for ref in sort_unique_refs(refs, domain_ordinals={"b": 1, "a": 0, "c": 2})] == ["a", "b", "c"]
    with pytest.raises(ValueError):
        sort_unique_refs([artifact("a"), artifact("a")])

    assert document_preparation_run_id("bundle-1") == "document-preparation:bundle-1"
    assert deep_review_run_id("review-1", "attempt-2") == "deep-review:review-1:attempt:attempt-2"
    assert decision_run_id("review-1") == "decision:review-1"
    with pytest.raises(ValueError):
        decision_run_id(" ")


def test_action_result_and_command_do_not_create_uuid_or_time_defaults() -> None:
    command = AgentCommand[StrictPayload](
        schema="bidops.agent-command.v1",
        agent_name="document_preparation",
        action="start_bundle",
        aggregate=aggregate(),
        actor={"actor_kind": "system", "claimed_name": None},
        input_refs=[],
        payload=StrictPayload(bundle_id="bundle-1"),
    )
    assert command.request_id is None
    assert command.correlation_id is None


def test_projection_does_not_depend_on_runtime_modules() -> None:
    import app.deep_review.agents.common.projection as projection

    names = set(projection.__dict__)
    assert not any(name in names for name in {"Session", "select", "uuid4", "datetime_now"})
