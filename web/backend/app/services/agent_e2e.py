"""T7 acceptance flow for the persisted agent projections.

The existing :func:`run_bc_e2e` owns the document-bundle to machine-report
boundary. This module composes that flow with the already-approved report
mutation endpoints and reads the three agent projections from a fresh
database session. It deliberately adds no REST endpoint and no persistence
model: the returned JSON is an operator evidence file only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agents import (
    AgentAction,
    AgentAggregateRef,
    AgentAggregateType,
    AgentRunStatus,
    DecisionAgent,
    DeepReviewAgent,
    DocumentPreparationAgent,
)
from ..core.config import get_settings
from ..core.db import SessionLocal
from ..core.models import AuditEvent
from ..deep_review.models import DeepReviewAttempt, DeepReviewStage, WorkJob
from .bc_e2e import AcceptanceApi, BcE2EError, BcE2EManifest, run_bc_e2e
from .document_bundles import DocumentBundleService


T7_E2E_RESULT_SCHEMA = "bidops.t7-e2e-result.v1"
MOCK_PROVIDER = "mock-analysis"
MOCK_MODEL = "bidops-deterministic-mock-v1"


@dataclass(frozen=True)
class AgentProjectionSnapshot:
    """The three projections read from one persisted database snapshot."""

    document_preparation: Any
    deep_review: Any
    decision: Any


class T7ProjectionReader(Protocol):
    """Internal reader boundary used by the workflow and deterministic tests."""

    def validate_mock_context(self) -> None: ...

    def read(self, bundle_id: str, review_id: str) -> AgentProjectionSnapshot: ...

    def active_work_jobs(self) -> int: ...

    def provider_context(self, review_ids: Sequence[str]) -> list[dict[str, Any]]: ...


class PersistedAgentProjectionReader:
    """Read agent state through the existing agents, never through a new API."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self.session_factory = session_factory
        # Status projection does not invoke the mutation service. Passing a
        # capability-less object to the two read-only adapters prevents a
        # projection check from constructing or using a model client.
        self._document_agent = DocumentPreparationAgent(DocumentBundleService())
        self._deep_review_agent = DeepReviewAgent(service=object())  # type: ignore[arg-type]
        self._decision_agent = DecisionAgent(service=object())  # type: ignore[arg-type]

    @staticmethod
    def _uuid(value: str, field_name: str) -> UUID:
        try:
            return UUID(value)
        except (AttributeError, TypeError, ValueError) as error:
            raise BcE2EError("projection_invalid", f"persisted {field_name} is not a UUID") from error

    def read(self, bundle_id: str, review_id: str) -> AgentProjectionSnapshot:
        bundle_uuid = self._uuid(bundle_id, "bundle_id")
        review_uuid = self._uuid(review_id, "review_id")
        try:
            with self.session_factory() as session:
                document = self._document_agent.status(
                    session,
                    AgentAggregateRef(
                        aggregate_type=AgentAggregateType.document_bundle,
                        aggregate_id=str(bundle_uuid),
                    ),
                )
                deep_review = self._deep_review_agent.status(
                    session,
                    AgentAggregateRef(
                        aggregate_type=AgentAggregateType.deep_review,
                        aggregate_id=str(review_uuid),
                    ),
                )
                decision = self._decision_agent.status(
                    session,
                    AgentAggregateRef(
                        aggregate_type=AgentAggregateType.deep_review,
                        aggregate_id=str(review_uuid),
                    ),
                )
                return AgentProjectionSnapshot(
                    document_preparation=document,
                    deep_review=deep_review,
                    decision=decision,
                )
        except BcE2EError:
            raise
        except Exception as error:
            raise BcE2EError("projection_unavailable", "persisted agent projection could not be read") from error

    @staticmethod
    def validate_mock_context() -> None:
        settings = get_settings()
        if (
            settings.analysis_provider != "mock"
            or settings.vllm_model != MOCK_MODEL
            or settings.openai_enabled
            or not settings.reference_workflow_mode
        ):
            raise BcE2EError(
                "mock_provider_required",
                "T7 requires mock-analysis/bidops-deterministic-mock-v1 with OpenAI disabled",
            )

    def active_work_jobs(self) -> int:
        try:
            with self.session_factory() as session:
                count = session.scalar(
                    select(func.count(WorkJob.id)).where(WorkJob.status.in_(("queued", "running")))
                )
                return int(count or 0)
        except Exception as error:
            raise BcE2EError("work_jobs_unavailable", "active WorkJob state could not be read") from error

    def provider_context(self, review_ids: Sequence[str]) -> list[dict[str, Any]]:
        ids = [self._uuid(value, "review_id") for value in review_ids]
        self.validate_mock_context()
        try:
            with self.session_factory() as session:
                rows = session.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.action == "deep_review.create",
                        AuditEvent.aggregate_type == "deep_review",
                        AuditEvent.aggregate_id.in_([str(value) for value in ids]),
                    )
                    .order_by(AuditEvent.aggregate_id.asc(), AuditEvent.created_at.asc(), AuditEvent.id.asc())
                ).all()
                stages = session.scalars(
                    select(DeepReviewStage)
                    .join(DeepReviewAttempt, DeepReviewStage.attempt_id == DeepReviewAttempt.id)
                    .where(DeepReviewAttempt.deep_review_id.in_(ids))
                ).all()
                if not stages:
                    raise BcE2EError("provider_context_invalid", "deep review invocation audit is missing")
                attempts = session.scalars(
                    select(DeepReviewAttempt).where(DeepReviewAttempt.deep_review_id.in_(ids))
                ).all()
                review_by_attempt = {str(attempt.id): str(attempt.deep_review_id) for attempt in attempts}
                invocation_counts = {str(review_id): 0 for review_id in ids}
                for stage in stages:
                    review_id = review_by_attempt.get(str(stage.attempt_id))
                    if review_id is None:
                        raise BcE2EError("provider_context_invalid", "deep review attempt scope is invalid")
                    metadata_rows = stage.invocation_metadata
                    if isinstance(metadata_rows, Mapping):
                        metadata_rows = [metadata_rows] if metadata_rows else []
                    if not isinstance(metadata_rows, list):
                        raise BcE2EError("provider_context_invalid", "deep review invocation metadata is invalid")
                    for metadata_row in metadata_rows:
                        if not isinstance(metadata_row, Mapping):
                            raise BcE2EError("provider_context_invalid", "deep review invocation metadata is invalid")
                        if (
                            metadata_row.get("provider") != MOCK_PROVIDER
                            or metadata_row.get("model") != MOCK_MODEL
                        ):
                            raise BcE2EError("provider_context_invalid", "a non-mock analysis invocation is persisted")
                        invocation_counts[review_id] += 1
                by_review: dict[str, list[AuditEvent]] = {}
                for row in rows:
                    by_review.setdefault(str(row.aggregate_id), []).append(row)
                result: list[dict[str, Any]] = []
                for review_id in review_ids:
                    if invocation_counts.get(review_id, 0) == 0:
                        raise BcE2EError("provider_context_invalid", "deep review has no persisted analysis invocations")
                    candidates = by_review.get(review_id, [])
                    if len(candidates) != 1:
                        raise BcE2EError("provider_context_invalid", "deep review provider audit is missing or duplicated")
                    metadata = candidates[0].safe_metadata
                    if not isinstance(metadata, Mapping):
                        raise BcE2EError("provider_context_invalid", "deep review provider audit metadata is invalid")
                    if (
                        metadata.get("analysis_provider") != MOCK_PROVIDER
                        or metadata.get("runtime_model") != MOCK_MODEL
                        or metadata.get("reference_workflow_mode") is not True
                        or metadata.get("external_provider_approved") is not False
                    ):
                        raise BcE2EError("provider_context_invalid", "persisted deep review provider context is not the T7 mock context")
                    result.append({
                        "review_id": review_id,
                        "provider": metadata.get("analysis_provider"),
                        "model": metadata.get("runtime_model"),
                        "analysis_path": "mock-analysis-local",
                        "mock_invocation_count": invocation_counts[review_id],
                        "policy_model": metadata.get("policy_model_name"),
                        "reference_workflow_mode": metadata.get("reference_workflow_mode"),
                        "external_provider_approved": metadata.get("external_provider_approved"),
                        "external_calls": {"openai": 0, "qwen": 0, "total": 0},
                    })
                return result
        except BcE2EError:
            raise
        except Exception as error:
            raise BcE2EError("provider_context_unavailable", "provider/model audit state could not be read") from error


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise BcE2EError("invalid_api_response", f"T7 response is missing {key}")
    return value


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise BcE2EError("invalid_api_response", f"T7 response is missing object {key}")
    return value


def _required_uuid(payload: Mapping[str, Any], key: str) -> str:
    value = _required_string(payload, key)
    try:
        UUID(value)
    except (TypeError, ValueError, AttributeError) as error:
        raise BcE2EError("invalid_api_response", f"T7 response has an invalid UUID in {key}") from error
    return value


def _projection_evidence(view: Any) -> dict[str, Any]:
    """Keep the contract fields visible without copying report prose."""

    try:
        dumped = view.model_dump(mode="json")
    except AttributeError as error:
        raise BcE2EError("projection_invalid", "agent projection is not a persisted AgentRunView") from error
    return {
        "run_id": dumped.get("run_id"),
        "status": dumped.get("status"),
        "current_step": dumped.get("current_step"),
        "outcome": dumped.get("outcome_code"),
        "refs": {
            "input": dumped.get("input_refs", []),
            "output": dumped.get("output_refs", []),
        },
        "lineage": dumped.get("correlation_id"),
        "wait": dumped.get("wait"),
        "available_actions": dumped.get("available_actions", []),
    }


def _assert_projection(
    view: Any,
    *,
    label: str,
    expected_run_id: str,
    expected_status: AgentRunStatus,
    expected_step: str | None,
    expected_outcome: str | None,
    lineage: UUID | None = None,
    require_lineage: bool = True,
    wait_reason: str | None = None,
    actions: Sequence[AgentAction] = (),
    input_types: Sequence[str] | None = None,
    output_types: Sequence[str] | None = None,
) -> dict[str, Any]:
    evidence = _projection_evidence(view)
    if evidence["run_id"] != expected_run_id:
        raise BcE2EError("projection_invalid", f"{label} run_id does not match persisted identifiers")
    if evidence["status"] != expected_status.value:
        raise BcE2EError("projection_invalid", f"{label} status is not the expected persisted status")
    if evidence["current_step"] != expected_step:
        raise BcE2EError("projection_invalid", f"{label} current_step is not the expected persisted step")
    if evidence["outcome"] != expected_outcome:
        raise BcE2EError("projection_invalid", f"{label} outcome is not the expected persisted outcome")
    actual_lineage = evidence["lineage"]
    if require_lineage and not actual_lineage:
        raise BcE2EError("lineage_missing", f"{label} is missing persisted lineage")
    if lineage is not None and actual_lineage != str(lineage):
        raise BcE2EError("lineage_mismatch", f"{label} lineage does not match the bundle lineage")
    wait = evidence["wait"]
    actual_wait_reason = wait.get("reason_code") if isinstance(wait, Mapping) else None
    if actual_wait_reason != wait_reason:
        raise BcE2EError("projection_invalid", f"{label} wait state is not the expected persisted state")
    actual_actions = evidence["available_actions"]
    expected_actions = [action.value for action in actions]
    if actual_actions != expected_actions:
        raise BcE2EError("projection_invalid", f"{label} available_actions are not the expected persisted actions")
    for key, expected_types in (("input", input_types), ("output", output_types)):
        if expected_types is None:
            continue
        refs = evidence["refs"][key]
        actual_types = [ref.get("artifact_type") for ref in refs if isinstance(ref, Mapping)]
        if actual_types[: len(expected_types)] != list(expected_types):
            raise BcE2EError("projection_invalid", f"{label} {key}_refs are not in the expected order")
    return evidence


def _uploaded_ids(flow: Mapping[str, Any]) -> list[str]:
    bundle = _required_mapping(flow, "bundle")
    documents = bundle.get("documents")
    if not isinstance(documents, list):
        raise BcE2EError("invalid_api_response", "T7 bundle evidence has no document list")
    return [
        _required_string(document, "document_version_id")
        for document in documents
        if isinstance(document, Mapping) and document.get("uploaded_in_run") is True
    ]


def _machine_report(api: AcceptanceApi, review_id: str) -> dict[str, Any]:
    report = api.request_json("GET", f"/api/deep-reviews/{review_id}/report", retryable=True)
    report_payload = _required_mapping(report, "report")
    _required_uuid(report, "current_revision_id")
    if _required_string(report_payload, "deep_review_id") != review_id:
        raise BcE2EError("report_scope_invalid", "report is outside the persisted deep review")
    validation = _required_mapping(report, "validation")
    if _required_string(validation, "status") != "passed":
        raise BcE2EError("validation_failed", "T7 mock machine validation did not pass")
    history = report.get("history")
    if not isinstance(history, list) or not history:
        raise BcE2EError("report_revision_invalid", "report history is missing")
    return report


def _human_report_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = deepcopy(dict(_required_mapping(report, "report")))
    # Change presentation metadata only. This is a full human revision and
    # revalidation, but it does not invent or alter a document fact.
    sections = payload.get("sections")
    if isinstance(sections, list) and sections and isinstance(sections[0], dict):
        title = sections[0].get("title")
        if isinstance(title, str) and title:
            sections[0]["title"] = f"{title} (T7 human review)"
    return payload


def _revision_summary(report: Mapping[str, Any], *, expected_origin: str) -> dict[str, Any]:
    current_revision_id = _required_uuid(report, "current_revision_id")
    validation = _required_mapping(report, "validation")
    validation_id = _required_uuid(validation, "validation_run_id")
    history = report.get("history")
    if not isinstance(history, list) or not history or not isinstance(history[-1], Mapping):
        raise BcE2EError("report_revision_invalid", "report history is invalid")
    if history[-1].get("origin") != expected_origin:
        raise BcE2EError("report_revision_invalid", "report history origin is not persisted as expected")
    return {
        "revision_id": current_revision_id,
        "validation_run_id": validation_id,
        "validation_status": validation.get("status"),
        "origin": history[-1].get("origin"),
        "history": [
            {
                "revision_id": item.get("revision_id"),
                "sequence": item.get("sequence"),
                "origin": item.get("origin"),
                "validation_status": item.get("validation_status"),
            }
            for item in history
            if isinstance(item, Mapping)
        ],
    }


def _review_attempt_ids(review: Mapping[str, Any]) -> list[str]:
    attempts = review.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise BcE2EError("attempt_history_missing", "deep review attempt history is missing")
    return [_required_uuid(attempt, "id") for attempt in attempts if isinstance(attempt, Mapping)]


def _verify_bundle_history(api: AcceptanceApi, notice_id: int, first_id: str, second_id: str) -> dict[str, Any]:
    response = api.request_json("GET", f"/api/notices/{notice_id}/document-bundles", retryable=True)
    items = response.get("items")
    if not isinstance(items, list):
        raise BcE2EError("bundle_history_missing", "document bundle history is missing")
    by_id = {
        _required_string(item, "id"): item
        for item in items
        if isinstance(item, Mapping)
    }
    if first_id not in by_id or second_id not in by_id:
        raise BcE2EError("bundle_history_missing", "both T7 bundles are not present in persisted history")
    if by_id[first_id].get("status") != "superseded" or by_id[second_id].get("status") != "ready":
        raise BcE2EError("bundle_history_invalid", "new ready bundle did not preserve the prior bundle")
    return {
        "bundle_ids": [first_id, second_id],
        "statuses": {first_id: by_id[first_id].get("status"), second_id: by_id[second_id].get("status")},
    }


def _flow_projection_evidence(
    projections: AgentProjectionSnapshot,
    *,
    bundle_id: str,
    review_id: str,
    attempt_id: str,
    lineage: UUID | None,
    decision_state: str,
    document_state: str = "ready",
) -> dict[str, Any]:
    if document_state == "ready":
        document = _assert_projection(
            projections.document_preparation,
            label=f"document_preparation:{bundle_id}",
            expected_run_id=f"document-preparation:{bundle_id}",
            expected_status=AgentRunStatus.completed,
            expected_step=None,
            expected_outcome="ready_bundle",
            lineage=lineage,
            wait_reason=None,
            output_types=("document_structure",),
        )
    elif document_state == "superseded":
        document = _assert_projection(
            projections.document_preparation,
            label=f"document_preparation:{bundle_id}:preserved",
            expected_run_id=f"document-preparation:{bundle_id}",
            expected_status=AgentRunStatus.superseded,
            expected_step=None,
            expected_outcome="superseded_by_new_bundle",
            lineage=lineage,
            wait_reason=None,
            output_types=("document_structure",),
        )
    else:
        raise BcE2EError("projection_invalid", "unknown T7 document checkpoint")
    deep_review = _assert_projection(
        projections.deep_review,
        label=f"deep_review:{review_id}",
        expected_run_id=f"deep-review:{review_id}:attempt:{attempt_id}",
        expected_status=AgentRunStatus.completed,
        expected_step=None,
        expected_outcome="report_ready_validated",
        lineage=lineage,
        wait_reason=None,
        actions=(AgentAction.retry_attempt,),
        input_types=("document_bundle", "profile_version", "policy_version"),
        output_types=("deep_review_stage", "deep_review_stage", "deep_review_stage", "report_revision", "validation_run"),
    )
    if decision_state == "machine":
        decision = _assert_projection(
            projections.decision,
            label=f"decision:{review_id}:machine",
            expected_run_id=f"decision:{review_id}",
            expected_status=AgentRunStatus.waiting_human,
            expected_step="review_report_and_evidence",
            expected_outcome=None,
            lineage=lineage,
            wait_reason="report_review_required",
            actions=(AgentAction.create_full_revision, AgentAction.record_final_opinion),
            input_types=("report_revision", "validation_run"),
        )
    elif decision_state == "human":
        decision = _assert_projection(
            projections.decision,
            label=f"decision:{review_id}:human",
            expected_run_id=f"decision:{review_id}",
            expected_status=AgentRunStatus.waiting_human,
            expected_step="record_final_opinion",
            expected_outcome=None,
            lineage=lineage,
            wait_reason="final_opinion_required",
            actions=(AgentAction.create_full_revision, AgentAction.record_final_opinion),
            input_types=("report_revision", "validation_run"),
            output_types=("report_revision", "validation_run"),
        )
    elif decision_state == "final":
        decision = _assert_projection(
            projections.decision,
            label=f"decision:{review_id}:final",
            expected_run_id=f"decision:{review_id}",
            expected_status=AgentRunStatus.completed,
            expected_step=None,
            expected_outcome="final_opinion_recorded",
            lineage=lineage,
            wait_reason=None,
            actions=(AgentAction.create_full_revision,),
            input_types=("report_revision", "validation_run"),
            output_types=("report_revision", "validation_run", "final_opinion"),
        )
    else:
        raise BcE2EError("projection_invalid", "unknown T7 decision checkpoint")
    return {
        "document_preparation": document,
        "deep_review": deep_review,
        "decision": decision,
    }


def _lineage_from_projection(projections: AgentProjectionSnapshot) -> UUID:
    values = [
        projections.document_preparation.correlation_id,
        projections.deep_review.correlation_id,
        projections.decision.correlation_id,
    ]
    if not all(isinstance(value, UUID) for value in values) or len(set(values)) != 1:
        raise BcE2EError("lineage_mismatch", "the three persisted agent projections do not share one lineage")
    return values[0]  # type: ignore[return-value]


def run_t7_e2e(
    manifest: BcE2EManifest,
    api: AcceptanceApi,
    projection_reader: T7ProjectionReader,
    *,
    timeout_seconds: float = 3600,
    poll_seconds: float = 2,
    sleep: Any = None,
    monotonic: Any = None,
) -> dict[str, Any]:
    """Run the complete isolated T7 mock-reference acceptance workflow."""

    validate_mock_context = getattr(projection_reader, "validate_mock_context", None)
    if callable(validate_mock_context):
        validate_mock_context()
    runner_options: dict[str, Any] = {"timeout_seconds": timeout_seconds, "poll_seconds": poll_seconds}
    if sleep is not None:
        runner_options["sleep"] = sleep
    if monotonic is not None:
        runner_options["monotonic"] = monotonic

    first = run_bc_e2e(manifest, api, **runner_options)
    first_bundle = _required_mapping(first, "bundle")
    first_bundle_id = _required_string(first_bundle, "id")
    first_review = _required_mapping(first, "deep_review")
    first_review_id = _required_string(first_review, "id")
    first_review_view = api.request_json("GET", f"/api/deep-reviews/{first_review_id}", retryable=True)
    first_attempt_ids = _review_attempt_ids(first_review_view)
    first_attempt_id = first_attempt_ids[-1]
    first_machine = projection_reader.read(first_bundle_id, first_review_id)
    first_lineage = _lineage_from_projection(first_machine)
    first_machine_projection = _flow_projection_evidence(
        first_machine,
        bundle_id=first_bundle_id,
        review_id=first_review_id,
        attempt_id=first_attempt_id,
        lineage=first_lineage,
        decision_state="machine",
    )
    machine_report = _machine_report(api, first_review_id)
    machine_revision_id = _required_uuid(machine_report, "current_revision_id")
    machine_validation_id = _required_uuid(_required_mapping(machine_report, "validation"), "validation_run_id")

    revision_request_id = str(uuid4())
    human_report = api.request_json(
        "POST",
        f"/api/deep-reviews/{first_review_id}/report-revisions",
        payload={
            "request_id": revision_request_id,
            "base_revision_id": machine_revision_id,
            "report": _human_report_payload(machine_report),
            "reason": "T7 human full revision fixture: 담당자가 machine report 전체를 검토했습니다.",
            "factual_change_evidence_ids": [],
        },
        actor=manifest.actor_name,
        retryable=True,
    )
    human_revision = _revision_summary(human_report, expected_origin="human")
    if human_revision["validation_status"] != "passed":
        raise BcE2EError("validation_failed", "human full revision revalidation did not pass")
    human_projection = projection_reader.read(first_bundle_id, first_review_id)
    human_projection_evidence = _flow_projection_evidence(
        human_projection,
        bundle_id=first_bundle_id,
        review_id=first_review_id,
        attempt_id=first_attempt_id,
        lineage=first_lineage,
        decision_state="human",
    )

    opinion_request_id = str(uuid4())
    final_opinion = api.request_json(
        "POST",
        f"/api/deep-reviews/{first_review_id}/final-opinions",
        payload={
            "request_id": opinion_request_id,
            "report_revision_id": human_revision["revision_id"],
            "validation_run_id": human_revision["validation_run_id"],
            "value": "조건부 추진",
            "reason": "T7 explicit human opinion fixture; 운영 참여 결정이나 모델 품질 판정이 아닙니다.",
            "acknowledged_validation_failure": False,
        },
        actor=manifest.actor_name,
        retryable=True,
    )
    opinion_id = _required_uuid(final_opinion, "id")
    if final_opinion.get("claimed_name") != manifest.actor_name:
        raise BcE2EError("opinion_invalid", "final opinion was not persisted with the claimed human actor")
    final_projection = projection_reader.read(first_bundle_id, first_review_id)
    final_projection_evidence = _flow_projection_evidence(
        final_projection,
        bundle_id=first_bundle_id,
        review_id=first_review_id,
        attempt_id=first_attempt_id,
        lineage=first_lineage,
        decision_state="final",
    )

    first_report_after_human = api.request_json("GET", f"/api/deep-reviews/{first_review_id}/report", retryable=True)
    first_revision_history = _revision_summary(first_report_after_human, expected_origin="human")
    if len(first_revision_history["history"]) != 2:
        raise BcE2EError("revision_history_invalid", "machine and human report revisions are not both preserved")
    if first_revision_history["revision_id"] != human_revision["revision_id"]:
        raise BcE2EError("revision_history_invalid", "human revision is not the current persisted revision")
    persisted_opinion = first_report_after_human.get("final_opinion")
    if not isinstance(persisted_opinion, Mapping) or _required_uuid(persisted_opinion, "id") != opinion_id:
        raise BcE2EError("opinion_invalid", "final opinion is missing from the persisted report history")

    second = run_bc_e2e(manifest, api, **runner_options)
    second_bundle = _required_mapping(second, "bundle")
    second_bundle_id = _required_string(second_bundle, "id")
    second_review = _required_mapping(second, "deep_review")
    second_review_id = _required_string(second_review, "id")
    second_review_view = api.request_json("GET", f"/api/deep-reviews/{second_review_id}", retryable=True)
    second_attempt_ids = _review_attempt_ids(second_review_view)
    second_attempt_id = second_attempt_ids[-1]
    second_projection = projection_reader.read(second_bundle_id, second_review_id)
    second_lineage = _lineage_from_projection(second_projection)
    second_projection_evidence = _flow_projection_evidence(
        second_projection,
        bundle_id=second_bundle_id,
        review_id=second_review_id,
        attempt_id=second_attempt_id,
        lineage=second_lineage,
        decision_state="machine",
    )
    if first_bundle_id == second_bundle_id or first_review_id == second_review_id:
        raise BcE2EError("new_scope_invalid", "second T7 bundle/review reused the first persisted identity")
    first_uploaded = _uploaded_ids(first)
    second_uploaded = _uploaded_ids(second)
    if not first_uploaded or not second_uploaded or set(first_uploaded) & set(second_uploaded):
        raise BcE2EError("new_attachment_invalid", "second T7 flow did not create a new uploaded attachment")
    if first_lineage == second_lineage:
        raise BcE2EError("lineage_reused", "second document bundle reused the first lineage")

    first_review_after = api.request_json("GET", f"/api/deep-reviews/{first_review_id}", retryable=True)
    if _review_attempt_ids(first_review_after) != first_attempt_ids:
        raise BcE2EError("attempt_history_invalid", "first deep review attempt history changed after the second flow")
    first_report_after_second = api.request_json("GET", f"/api/deep-reviews/{first_review_id}/report", retryable=True)
    second_history = _revision_summary(first_report_after_second, expected_origin="human")
    if [item["revision_id"] for item in second_history["history"]] != [item["revision_id"] for item in first_revision_history["history"]]:
        raise BcE2EError("revision_history_invalid", "first report revision history changed after the second flow")
    after_opinion = first_report_after_second.get("final_opinion")
    if not isinstance(after_opinion, Mapping) or _required_uuid(after_opinion, "id") != opinion_id:
        raise BcE2EError("opinion_history_invalid", "first final opinion changed after the second flow")
    historical_projection = projection_reader.read(first_bundle_id, first_review_id)
    historical_lineage = _lineage_from_projection(historical_projection)
    if historical_lineage != first_lineage:
        raise BcE2EError("lineage_history_invalid", "first lineage was not preserved after the second flow")
    historical_projection_evidence = _flow_projection_evidence(
        historical_projection,
        bundle_id=first_bundle_id,
        review_id=first_review_id,
        attempt_id=first_attempt_id,
        lineage=first_lineage,
        decision_state="final",
        document_state="superseded",
    )
    bundle_history = _verify_bundle_history(api, manifest.notice_id, first_bundle_id, second_bundle_id)

    provider_context = projection_reader.provider_context((first_review_id, second_review_id))
    if len(provider_context) != 2 or any(
        context.get("provider") != MOCK_PROVIDER
        or context.get("model") != MOCK_MODEL
        or context.get("external_calls") != {"openai": 0, "qwen": 0, "total": 0}
        for context in provider_context
    ):
        raise BcE2EError("provider_context_invalid", "T7 provider/model or external-call guard is invalid")
    active_jobs = projection_reader.active_work_jobs()
    if active_jobs != 0:
        raise BcE2EError("active_work_jobs", "queued/running WorkJob rows remain at T7 completion")

    first_report_evidence = first.get("report")
    evidence_rows = first_report_evidence.get("evidence", []) if isinstance(first_report_evidence, Mapping) else []
    return {
        "schema": T7_E2E_RESULT_SCHEMA,
        "workflow": "t7-mock-reference",
        "api_base": manifest.api_base,
        "notice_id": manifest.notice_id,
        "first_flow": {
            "bundle_id": first_bundle_id,
            "review_id": first_review_id,
            "attempt_ids": first_attempt_ids,
            "uploaded_document_version_ids": first_uploaded,
            "lineage": str(first_lineage),
            "machine": {
                "revision_id": machine_revision_id,
                "validation_run_id": machine_validation_id,
                "validation_status": "passed",
                "evidence_ids": [
                    row["evidence_id"]
                    for row in evidence_rows
                    if isinstance(row, Mapping) and isinstance(row.get("evidence_id"), str)
                ],
            },
            "human_revision": {"request_id": revision_request_id, **human_revision},
            "final_opinion": {
                "request_id": opinion_request_id,
                "id": opinion_id,
                "value": final_opinion.get("value"),
                "claimed_name": final_opinion.get("claimed_name"),
            },
            "projections": {
                "after_machine_report": first_machine_projection,
                "after_human_revision": human_projection_evidence,
                "after_final_opinion": final_projection_evidence,
                "preserved_after_second_flow": historical_projection_evidence,
            },
            "preserved_history": {
                "attempt_ids": first_attempt_ids,
                "revision_ids": [item["revision_id"] for item in second_history["history"]],
                "final_opinion_id": opinion_id,
            },
        },
        "second_flow": {
            "bundle_id": second_bundle_id,
            "review_id": second_review_id,
            "attempt_ids": second_attempt_ids,
            "uploaded_document_version_ids": second_uploaded,
            "lineage": str(second_lineage),
            "projections": second_projection_evidence,
        },
        "lineage": {
            "first": str(first_lineage),
            "second": str(second_lineage),
            "distinct": True,
            "each_flow_shared_by_bundle_review_and_decision": True,
        },
        "bundle_history": bundle_history,
        "provider_model": {
            "contexts": provider_context,
            "external_calls": {"openai": 0, "qwen": 0, "total": 0},
            "basis": "mock-analysis path is local and does not invoke OpenAI or Qwen",
        },
        "work_jobs": {"queued": 0, "running": 0, "active": active_jobs},
        "mock_quality": {
            "evaluated": False,
            "note": "Mock output proves workflow, persistence, validation, and lineage wiring only; it is not model-quality evidence.",
        },
        "passed": True,
    }


__all__ = [
    "AgentProjectionSnapshot",
    "MOCK_MODEL",
    "MOCK_PROVIDER",
    "PersistedAgentProjectionReader",
    "T7ProjectionReader",
    "T7_E2E_RESULT_SCHEMA",
    "run_t7_e2e",
]
