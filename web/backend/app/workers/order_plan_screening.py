"""Single-slot, request-separated worker for manual C-2 executions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..ingest.contracts import (
    OrderPlanScreeningDecisionsArtifact,
    OrderPlanScreeningFailuresArtifact,
    OrderPlanScreeningInputArtifact,
    OrderPlanScreeningPolicyArtifact,
    OrderPlanScreeningRankingArtifact,
    OrderPlanScreeningResultArtifact,
    OrderPlanScreeningTelemetryArtifact,
)
from ..models import (
    AuditEvent,
    OrderPlan,
    OrderPlanObservation,
    OrderPlanScreeningArtifact,
    OrderPlanScreeningBatchAttempt,
    OrderPlanScreeningExecution,
    OrderPlanScreeningResult,
)
from ..services.object_store import EncryptedModelResponseStore, ObjectStoreError
from ..services.order_plan_screening import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    OrderPlanScreeningService,
    _canonical,
    _no_duplicate_pairs,
    _sha256_bytes,
    _sha256_json,
    execution_directory,
)
from ..services.vllm_client import OrderPlanVllmAdapter, OrderPlanVllmError


BATCH_PROGRESS_SCHEMA = "bidops.order-plan-screening-batch-progress.v1"


class C2WorkerError(RuntimeError):
    """Internal worker error with an API-safe terminal code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class C2ScreeningWorker:
    """Claim and process at most one C-2 execution per call."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        adapter: Any | None = None,
        raw_response_store: Any | None = None,
        command_runner: Callable[..., Any] | None = None,
        service: OrderPlanScreeningService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.adapter = adapter
        self.raw_response_store = raw_response_store
        self.command_runner = command_runner or subprocess.run
        self.service = service or OrderPlanScreeningService(self.settings)
        self.clock = clock or (lambda: datetime.now(UTC))

    def _recover_stale(self, session: Session) -> None:
        cutoff = self.clock() - timedelta(seconds=self.settings.c2_worker_stale_seconds)
        rows = session.scalars(
            select(OrderPlanScreeningExecution).where(
                OrderPlanScreeningExecution.status.in_(ACTIVE_STATUSES),
                or_(
                    OrderPlanScreeningExecution.heartbeat_at < cutoff,
                    and_(
                        OrderPlanScreeningExecution.heartbeat_at.is_(None),
                        OrderPlanScreeningExecution.started_at < cutoff,
                    ),
                ),
            ).with_for_update()
        ).all()
        for execution in rows:
            try:
                with session.begin_nested():
                    self._recover_partial_artifacts(session, execution)
            except Exception:
                # A damaged optional journal must not keep an abandoned
                # execution active. The lifecycle/audit transition below is
                # still committed independently.
                pass
            if execution.status == "실행 중":
                execution.status = "중지 요청"
                session.flush()
            execution.status = "중단됨"
            execution.active_slot = None
            execution.finished_at = self.clock()
            execution.partial_artifact = True
            execution.error_code = "stale_execution"
            session.add(AuditEvent(
                id=uuid4(),
                actor_kind="system",
                claimed_name=self.settings.worker_id,
                action="c2.execution_stale_recovered",
                aggregate_type="order_plan_screening_execution",
                aggregate_id=str(execution.execution_id),
                safe_metadata={"status": "중단됨", "error_code": "stale_execution"},
                request_id=str(execution.request_id),
                created_at=self.clock(),
            ))
        if rows:
            session.commit()

    def _claim(self, session: Session) -> OrderPlanScreeningExecution | None:
        self._recover_stale(session)
        active = session.scalar(
            select(func.count()).select_from(OrderPlanScreeningExecution).where(
                OrderPlanScreeningExecution.status.in_(ACTIVE_STATUSES)
            )
        )
        if active:
            return None
        execution = session.scalar(
            select(OrderPlanScreeningExecution).where(
                OrderPlanScreeningExecution.status == "대기",
            ).order_by(OrderPlanScreeningExecution.queued_at, OrderPlanScreeningExecution.execution_id).with_for_update(skip_locked=True)
        )
        if execution is None:
            return None
        now = self.clock()
        execution.status = "실행 중"
        execution.active_slot = 1
        execution.started_at = now
        execution.heartbeat_at = now
        session.add(execution)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return None
        return execution

    def run_once(self, session: Session) -> dict[str, Any] | None:
        execution = self._claim(session)
        if execution is None:
            return None
        try:
            return self._run_execution(session, execution)
        except C2WorkerError as error:
            session.rollback()
            self._fail_execution(session, execution.execution_id, error.code)
            return {"execution_id": str(execution.execution_id), "status": "실패", "error_code": error.code}
        except Exception:
            session.rollback()
            self._fail_execution(session, execution.execution_id, "worker_failed")
            return {"execution_id": str(execution.execution_id), "status": "실패", "error_code": "worker_failed"}

    def _fail_execution(self, session: Session, execution_id: UUID, code: str) -> None:
        execution = session.get(OrderPlanScreeningExecution, execution_id)
        if execution is None or execution.status in TERMINAL_STATUSES:
            return
        now = self.clock()
        if execution.started_at is None:
            execution.started_at = now
        stopped = execution.status == "중지 요청"
        execution.status = "중단됨" if stopped else "실패"
        execution.active_slot = None
        execution.finished_at = now
        execution.partial_artifact = True
        execution.error_code = "user_requested" if stopped else code
        try:
            session.commit()
        except Exception:
            session.rollback()

    def _execution_dir(self, execution: OrderPlanScreeningExecution) -> Path:
        return execution_directory(self.settings, execution.source_run_id, execution.execution_id)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise C2WorkerError("artifact_not_ready")
        try:
            value = json.loads(
                path.read_bytes().decode("utf-8"),
                object_pairs_hook=_no_duplicate_pairs,
                parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            raise C2WorkerError("artifact_invalid") from None
        if not isinstance(value, dict):
            raise C2WorkerError("artifact_invalid")
        return value

    @staticmethod
    def _write_json(path: Path, value: Mapping[str, Any]) -> tuple[str, int]:
        data = _canonical(value)
        try:
            with path.open("xb") as handle:
                handle.write(data)
        except (FileExistsError, OSError) as error:
            raise C2WorkerError("immutable_conflict") from error
        return _sha256_bytes(data), len(data)

    def _load_input(self, directory: Path, execution: OrderPlanScreeningExecution) -> OrderPlanScreeningInputArtifact:
        try:
            model = OrderPlanScreeningInputArtifact.model_validate(self._read_json(directory / "screening-input.json"))
        except (ValidationError, C2WorkerError):
            raise C2WorkerError("input_invalid") from None
        if model.execution_id != str(execution.execution_id) or model.source_run_id != execution.source_run_id:
            raise C2WorkerError("binding_mismatch")
        if model.population_count != execution.population_count or model.population_sha256 != execution.population_sha256:
            raise C2WorkerError("binding_mismatch")
        return model

    @staticmethod
    def _assert_claim(session: Session, execution_id: UUID) -> OrderPlanScreeningExecution:
        execution = session.get(OrderPlanScreeningExecution, execution_id)
        if execution is None or execution.status not in ACTIVE_STATUSES or execution.active_slot != 1:
            raise C2WorkerError("stale_execution")
        return execution

    def _run_cli(self, script: Path, args: list[str]) -> None:
        if script.is_symlink() or not script.is_file():
            raise C2WorkerError("pipeline_unavailable")
        try:
            completed = self.command_runner(
                [sys.executable, str(script), *args],
                cwd=str(self.settings.bidops_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            raise C2WorkerError("pipeline_timeout") from None
        except (OSError, ValueError):
            raise C2WorkerError("pipeline_unavailable") from None
        if getattr(completed, "returncode", 1) != 0:
            raise C2WorkerError("pipeline_failed")

    def _load_binding_inputs(self, directory: Path, input_model: OrderPlanScreeningInputArtifact) -> tuple[dict[str, Any], dict[str, str], dict[str, Any], str, dict[str, Any]]:
        binding = self._read_json(directory / "binding.json")
        policy = self._read_json(directory / "policy.json")
        try:
            policy_model = OrderPlanScreeningPolicyArtifact.model_validate(policy)
        except ValidationError:
            raise C2WorkerError("binding_mismatch") from None
        if (
            policy_model.policy_status != "active"
            or policy_model.policy_version != input_model.policy.version
            or _sha256_bytes((directory / "policy.json").read_bytes()) != input_model.policy.sha256
        ):
            raise C2WorkerError("binding_mismatch")
        if (
            binding.get("schema_version") != "bidops.order-plan-screening-phase0-binding.v1"
            or binding.get("producer") != "phase0-contracts"
            or binding.get("consumer") != "phase1-screening-pipeline"
            or binding.get("status") != "blocked"
        ):
            raise C2WorkerError("binding_mismatch")
        policy_ref = binding.get("policy")
        if (
            not isinstance(policy_ref, Mapping)
            or policy_ref.get("schema_version") != policy_model.schema_version
            or policy_ref.get("policy_version") != policy_model.policy_version
            or policy_ref.get("policy_status") != policy_model.policy_status
            or policy_ref.get("sha256") != input_model.policy.sha256
        ):
            raise C2WorkerError("binding_mismatch")
        stage1 = binding.get("stage1_binding")
        stage2 = binding.get("stage2_binding")
        policy_stage1 = policy_model.stage1
        policy_stage2 = policy_model.stage2
        if not isinstance(stage1, Mapping) or not isinstance(stage2, Mapping) or not isinstance(policy_stage1, Mapping) or not isinstance(policy_stage2, Mapping):
            raise C2WorkerError("binding_mismatch")
        stage1_config = policy_stage1.get("config")
        policy_generation = policy_stage2.get("generation_config")
        policy_prompt = policy_stage2.get("prompt")
        policy_profile = policy_stage2.get("company_profile")
        if (
            stage1.get("method") != "bm25"
            or stage1.get("schema_version") != "bidops.order-plan-bm25.v1"
            or stage1.get("top_k") != 300
            or stage1.get("tie_break") != ["score_desc", "order_plan_unty_no_asc"]
            or not isinstance(stage1_config, Mapping)
            or stage1.get("sha256") != stage1_config.get("sha256")
            or not isinstance(policy_generation, Mapping)
            or not isinstance(policy_prompt, Mapping)
            or not isinstance(policy_profile, Mapping)
        ):
            raise C2WorkerError("binding_mismatch")
        expected = {
            "generation_config_version": stage2.get("generation_config_version"),
            "model_name": stage2.get("model_name"),
            "model_digest": stage2.get("model_digest"),
            "generation_config_version": stage2.get("generation_config_version"),
            "prompt_version": stage2.get("prompt_version"),
            "prompt_sha256": stage2.get("prompt_sha256"),
            "company_profile_version": stage2.get("company_profile_version"),
            "company_profile_sha256": stage2.get("company_profile_sha256"),
            "generation_config_sha256": stage2.get("generation_config_sha256"),
        }
        if not all(isinstance(value, str) and value for value in expected.values()):
            raise C2WorkerError("binding_mismatch")
        expected_policy = {
            "provider": policy_stage2.get("provider"),
            "model_name": policy_stage2.get("model_name"),
            "model_digest": policy_stage2.get("model_digest"),
            "generation_config_version": policy_generation.get("version"),
            "generation_config_sha256": policy_generation.get("sha256"),
            "prompt_version": policy_prompt.get("version"),
            "prompt_sha256": policy_prompt.get("sha256"),
            "company_profile_version": policy_profile.get("version"),
            "company_profile_sha256": policy_profile.get("sha256"),
        }
        if (
            expected["model_name"] != "qwen3.8-27B"
            or any(expected.get(key) != value for key, value in expected_policy.items() if key != "provider")
            or stage2.get("provider") != "approved_private_vllm"
            or stage2.get("payload_fields") != ["title"]
            or stage2.get("company_payload_fields") != ["profile_version", "capabilities"]
            or stage2.get("batch_size") != 25
            or stage2.get("max_attempts") != 2
            or stage2.get("concurrency") != 1
            or input_model.stage1_binding.sha256 != stage1.get("sha256")
            or input_model.stage2_binding.sha256 != _sha256_bytes((directory / "binding.json").read_bytes())
            or not isinstance(binding.get("external_transport"), Mapping)
            or binding["external_transport"].get("execution_allowed") is not True
        ):
            raise C2WorkerError("binding_mismatch")
        capabilities_raw = self._read_json(directory / "capabilities.json")
        if capabilities_raw.get("schema_version") != "bidops.order-plan-capabilities.v1" or capabilities_raw.get("approval_status") != "approved":
            raise C2WorkerError("payload_not_approved")
        capabilities = capabilities_raw.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            raise C2WorkerError("payload_not_approved")
        capability_rows: list[dict[str, str]] = []
        for row in capabilities:
            if not isinstance(row, Mapping) or not isinstance(row.get("id"), str) or not isinstance(row.get("summary"), str) or not row["id"].strip() or not row["summary"].strip():
                raise C2WorkerError("payload_not_approved")
            capability_rows.append({"id": row["id"], "summary": row["summary"]})
        if capabilities_raw.get("profile_version") != expected["company_profile_version"] or _sha256_bytes((directory / "capabilities.json").read_bytes()) != expected["company_profile_sha256"]:
            raise C2WorkerError("binding_mismatch")
        try:
            prompt = (directory / "prompt.txt").read_bytes().decode("utf-8")
        except (OSError, UnicodeError):
            raise C2WorkerError("payload_not_approved") from None
        if _sha256_bytes(prompt.encode("utf-8")) != expected["prompt_sha256"] or not prompt.strip():
            raise C2WorkerError("binding_mismatch")
        # The approved generation config decides max_tokens, the timeout, and
        # the thinking switch.  Reading it here keeps the recorded
        # ``generation_config_sha256`` and the values that actually go on the
        # wire the same artifact ([ADR-0044]).
        generation = self._read_json(directory / "generation-config.json")
        if _sha256_bytes((directory / "generation-config.json").read_bytes()) != expected["generation_config_sha256"]:
            raise C2WorkerError("binding_mismatch")
        if (
            generation.get("method_version") != expected["generation_config_version"]
            or generation.get("model_name") != expected["model_name"]
            or generation.get("model_revision") != expected["model_digest"]
            or generation.get("prompt_sha256") != expected["prompt_sha256"]
            or generation.get("api_style") != "openai_compatible"
            or generation.get("batch_size") != 25
        ):
            raise C2WorkerError("binding_mismatch")
        company = {
            "profile_version": capabilities_raw["profile_version"],
            "capabilities": capability_rows,
        }
        return binding, expected, company, prompt, generation

    def _load_ranking(self, directory: Path, input_model: OrderPlanScreeningInputArtifact) -> OrderPlanScreeningRankingArtifact:
        ranking_path = directory / "screening-ranking.json"
        if not ranking_path.exists():
            self._run_cli(
                Path(self.settings.c2_bm25_script or ""),
                [
                    "--input", str(directory / "screening-input.json"),
                    "--capabilities", str(directory / "capabilities.json"),
                    "--output", str(ranking_path),
                    "--policy", str(directory / "policy.json"),
                    "--binding", str(directory / "binding.json"),
                ],
            )
        try:
            model = OrderPlanScreeningRankingArtifact.model_validate(self._read_json(ranking_path))
        except (ValidationError, C2WorkerError):
            raise C2WorkerError("ranking_invalid") from None
        input_ids = [item.plan_id for item in input_model.items]
        if (
            model.execution_id != input_model.execution_id
            or model.source_run_id != input_model.source_run_id
            or model.input_artifact_sha256 != _sha256_bytes((directory / "screening-input.json").read_bytes())
            # The ranker emits the full population in rank order and carries the
            # order in each item's ``rank``.  Only the covered set has to match
            # the frozen input; the artifact model already rejects duplicates.
            or sorted(item.plan_id for item in model.items) != sorted(input_ids)
            or model.population_count != input_model.population_count
            or model.selected_count > 300
        ):
            raise C2WorkerError("ranking_invalid")
        return model

    def _write_batch_progress(
        self,
        directory: Path,
        execution: OrderPlanScreeningExecution,
        batch: Mapping[str, Any],
        decision_batch: Mapping[str, Any],
        decision_items: list[Mapping[str, Any]],
        failure: Mapping[str, Any] | None,
        telemetry_batch: Mapping[str, Any],
    ) -> None:
        document = {
            "schema_version": BATCH_PROGRESS_SCHEMA,
            "producer": "order-plan-screening-qwen-worker",
            "consumer": "order-plan-screening-worker-recovery",
            "execution_id": str(execution.execution_id),
            "source_run_id": execution.source_run_id,
            "batch_id": batch["batch_id"],
            "sequence": batch["sequence"],
            "plan_ids": [item.plan_id for item in batch["items"]],
            "decision_batch": dict(decision_batch),
            "decision_items": [dict(item) for item in decision_items],
            "failure": dict(failure) if failure is not None else None,
            "telemetry_batch": dict(telemetry_batch),
        }
        self._write_json(
            directory / f"screening-batch-progress-{int(batch['sequence']):04d}.json",
            document,
        )

    @staticmethod
    def _attempt_measurement(attempt: OrderPlanScreeningBatchAttempt) -> dict[str, Any]:
        return {
            "attempt_no": attempt.attempt_no,
            "status": attempt.attempt_status,
            "started_at": attempt.started_at.isoformat() if attempt.started_at is not None else None,
            "finished_at": attempt.finished_at.isoformat() if attempt.finished_at is not None else None,
            "measurement": {
                "started_at": attempt.started_at.isoformat() if attempt.started_at is not None else None,
                "finished_at": attempt.finished_at.isoformat() if attempt.finished_at is not None else None,
                "duration_ms": attempt.duration_ms,
                "input_tokens": attempt.input_tokens,
                "cached_input_tokens": attempt.cached_input_tokens,
                "output_tokens": attempt.output_tokens,
                "total_tokens": attempt.total_tokens,
            },
        }

    def _load_batch_progress(
        self,
        directory: Path,
        execution: OrderPlanScreeningExecution,
        batch_specs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        paths = sorted(directory.glob("screening-batch-progress-*.json"))
        documents: list[dict[str, Any]] = []
        required_keys = {
            "schema_version", "producer", "consumer", "execution_id", "source_run_id",
            "batch_id", "sequence", "plan_ids", "decision_batch", "decision_items",
            "failure", "telemetry_batch",
        }
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise C2WorkerError("artifact_invalid")
            document = self._read_json(path)
            if set(document) != required_keys or document["schema_version"] != BATCH_PROGRESS_SCHEMA or document["producer"] != "order-plan-screening-qwen-worker" or document["consumer"] != "order-plan-screening-worker-recovery":
                raise C2WorkerError("artifact_invalid")
            if document["execution_id"] != str(execution.execution_id) or document["source_run_id"] != execution.source_run_id:
                raise C2WorkerError("binding_mismatch")
            sequence = document["sequence"]
            if not isinstance(sequence, int) or sequence != len(documents) + 1 or sequence > len(batch_specs):
                raise C2WorkerError("artifact_invalid")
            batch = batch_specs[sequence - 1]
            expected_ids = [item.plan_id for item in batch["items"]]
            if document["batch_id"] != batch["batch_id"] or document["plan_ids"] != expected_ids:
                raise C2WorkerError("binding_mismatch")
            decision_batch = document["decision_batch"]
            decision_items = document["decision_items"]
            telemetry_batch = document["telemetry_batch"]
            if not isinstance(decision_batch, Mapping) or not isinstance(decision_items, list) or not isinstance(telemetry_batch, Mapping):
                raise C2WorkerError("artifact_invalid")
            if (
                decision_batch.get("batch_id") != batch["batch_id"]
                or decision_batch.get("sequence") != sequence
                or decision_batch.get("plan_ids") != expected_ids
                or telemetry_batch.get("batch_id") != batch["batch_id"]
                or telemetry_batch.get("sequence") != sequence
                or not isinstance(telemetry_batch.get("attempts"), list)
            ):
                raise C2WorkerError("binding_mismatch")
            if decision_batch.get("status") == "success":
                if document["failure"] is not None or sorted(item.get("plan_id") for item in decision_items if isinstance(item, Mapping)) != sorted(expected_ids):
                    raise C2WorkerError("artifact_invalid")
            elif document["failure"] is None or decision_items:
                raise C2WorkerError("artifact_invalid")
            documents.append(document)
        return documents

    def _recovery_state(
        self,
        session: Session,
        execution: OrderPlanScreeningExecution,
        input_model: OrderPlanScreeningInputArtifact,
        ranking: OrderPlanScreeningRankingArtifact,
        stage2: Mapping[str, str],
        batch_specs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        directory = self._execution_dir(execution)
        progress = self._load_batch_progress(directory, execution, batch_specs)
        decision_batches = [dict(document["decision_batch"]) for document in progress]
        decision_items = [
            dict(item)
            for document in progress
            for item in document["decision_items"]
        ]
        failures = [dict(document["failure"]) for document in progress if document["failure"] is not None]
        telemetry_batches = [dict(document["telemetry_batch"]) for document in progress]
        progress_ids = {document["batch_id"] for document in progress}
        attempts = session.scalars(
            select(OrderPlanScreeningBatchAttempt).where(
                OrderPlanScreeningBatchAttempt.execution_id == execution.execution_id,
            ).order_by(OrderPlanScreeningBatchAttempt.sequence, OrderPlanScreeningBatchAttempt.attempt_no)
        ).all()
        attempts_by_batch: dict[str, list[OrderPlanScreeningBatchAttempt]] = {}
        for attempt in attempts:
            attempts_by_batch.setdefault(attempt.batch_id, []).append(attempt)
        rejection_types = {"model_mismatch", "binding_mismatch", "payload_not_approved", "policy_rejected"}
        for batch in batch_specs:
            batch_id = batch["batch_id"]
            if batch_id in progress_ids:
                continue
            batch_attempts = attempts_by_batch.get(batch_id, [])
            if not batch_attempts:
                continue
            now = self.clock()
            for attempt in batch_attempts:
                if attempt.attempt_status != "running":
                    continue
                attempt.attempt_status = "failed"
                attempt.failure_type = "unknown"
                attempt.failure_code = "stale_execution"
                attempt.finished_at = now
                attempt.duration_ms = max(0, int((now - attempt.started_at).total_seconds() * 1000)) if attempt.started_at else 0
            latest = batch_attempts[-1]
            failure_type = latest.failure_type if latest.failure_type in {
                "timeout", "truncated_output", "schema_violation", "id_mismatch", "model_mismatch",
                "binding_mismatch", "payload_not_approved", "transport", "policy_rejected", "unknown",
            } else "unknown"
            failure_code = latest.failure_code or "stale_execution"
            outcome = "rejected" if latest.attempt_status == "rejected" or failure_type in rejection_types else "unknown" if failure_type == "unknown" else "failed"
            decision_batches.append({
                "batch_id": batch_id,
                "sequence": batch["sequence"],
                "plan_ids": [item.plan_id for item in batch["items"]],
                "attempt_count": len(batch_attempts),
                "status": "rejected" if outcome == "rejected" else "failed",
            })
            failures.append({
                "batch_id": batch_id,
                "sequence": batch["sequence"],
                "plan_ids": [item.plan_id for item in batch["items"]],
                "attempt_count": len(batch_attempts),
                "max_attempts": 2,
                "failure_type": failure_type,
                "outcome": outcome,
                "status": "human_review_required",
                "error_code": failure_code,
            })
            telemetry_batches.append({
                "batch_id": batch_id,
                "sequence": batch["sequence"],
                "status": "rejected" if outcome == "rejected" else "failed",
                "attempts": [self._attempt_measurement(attempt) for attempt in batch_attempts],
            })
        candidate_count = sum(len(batch["items"]) for batch in batch_specs)
        success_count = len(decision_items)
        failure_status = "none" if not failures else "rejected" if all(item["outcome"] == "rejected" for item in failures) else "failed" if all(item["outcome"] == "failed" for item in failures) else "partial"
        decisions_status = "성공" if not failures and success_count == candidate_count else "부분 성공" if success_count else "실패"
        return {
            "binding": {},
            "stage2": dict(stage2),
            "batch_specs": batch_specs,
            "decision_batches": decision_batches,
            "decision_items": decision_items,
            "failures": failures,
            "failure_status": failure_status,
            "decisions_status": decisions_status,
            "telemetry_batches": telemetry_batches,
            "overall_started": execution.started_at or self.clock(),
            "overall_finished": self.clock(),
            "candidate_count": candidate_count,
            "success_count": success_count,
        }

    def _recover_partial_artifacts(self, session: Session, execution: OrderPlanScreeningExecution) -> None:
        directory = self._execution_dir(execution)
        if directory.is_symlink() or not directory.is_dir():
            return
        progress_exists = any(directory.glob("screening-batch-progress-*.json"))
        attempts_exist = session.scalar(
            select(OrderPlanScreeningBatchAttempt.attempt_id).where(
                OrderPlanScreeningBatchAttempt.execution_id == execution.execution_id,
            ).limit(1)
        ) is not None
        if not progress_exists and not attempts_exist:
            return
        if any((directory / filename).exists() for filename in ("screening-decisions.json", "screening-failures.json", "screening-telemetry.json")):
            return
        input_model = self._load_input(directory, execution)
        binding, stage2, _, _, _ = self._load_binding_inputs(directory, input_model)
        ranking_path = directory / "screening-ranking.json"
        if ranking_path.is_symlink() or not ranking_path.is_file():
            return
        ranking = self._load_ranking(directory, input_model)
        selected = sorted(
            (item for item in ranking.items if item.stage1_status == "selected"),
            key=lambda item: (item.rank or 0, item.plan_id),
        )
        batches = [selected[index : index + 25] for index in range(0, len(selected), 25)]
        batch_specs = [
            {"batch_id": f"batch-{sequence:04d}", "sequence": sequence, "items": batch}
            for sequence, batch in enumerate(batches, start=1)
        ]
        state = self._recovery_state(session, execution, input_model, ranking, stage2, batch_specs)
        state["binding"] = dict(binding)
        self._write_worker_artifacts(
            session,
            execution,
            input_model,
            ranking,
            stage2,
            state,
            require_claim=False,
            commit=False,
        )

    def _run_execution(self, session: Session, execution: OrderPlanScreeningExecution) -> dict[str, Any]:
        directory = self._execution_dir(execution)
        if directory.is_symlink() or not directory.is_dir():
            raise C2WorkerError("artifact_not_ready")
        input_model = self._load_input(directory, execution)
        binding, stage2, company, prompt, generation = self._load_binding_inputs(directory, input_model)
        ranking = self._load_ranking(directory, input_model)
        selected = sorted(
            (item for item in ranking.items if item.stage1_status == "selected"),
            key=lambda item: (item.rank or 0, item.plan_id),
        )
        batches = [selected[index : index + 25] for index in range(0, len(selected), 25)]
        batch_specs = [
            {"batch_id": f"batch-{sequence:04d}", "sequence": sequence, "items": batch}
            for sequence, batch in enumerate(batches, start=1)
        ]
        state = self._process_batches(session, execution, input_model, binding, stage2, company, prompt, generation, batch_specs)
        self._write_worker_artifacts(session, execution, input_model, ranking, stage2, state)
        current = self._assert_claim(session, execution.execution_id)
        current.heartbeat_at = self.clock()
        session.commit()
        self._run_cli(
            Path(self.settings.c2_merge_script or ""),
            [
                "--input", str(directory / "screening-input.json"),
                "--ranking", str(directory / "screening-ranking.json"),
                "--decisions", str(directory / "screening-decisions.json"),
                "--failures", str(directory / "screening-failures.json"),
                "--telemetry", str(directory / "screening-telemetry.json"),
                "--output", str(directory / "screening-results.json"),
                "--policy", str(directory / "policy.json"),
                "--binding", str(directory / "binding.json"),
            ],
        )
        return self._publish(session, execution, input_model, stage2, state)

    def _adapter(self, stage2: Mapping[str, str], generation: Mapping[str, Any]) -> Any:
        if self.adapter is not None:
            return self.adapter
        try:
            self.adapter = OrderPlanVllmAdapter(
                base_url=self.settings.vllm_base_url,
                allowed_hosts=self.settings.vllm_allowed_hosts,
                api_key=self.settings.vllm_api_key.get_secret_value(),
                model=str(stage2["model_name"]),
                model_digest=str(stage2["model_digest"]),
                deployed_revision=self.settings.vllm_model_revision,
                generation_config=generation,
            )
        except (KeyError, TypeError, ValueError):
            raise C2WorkerError("binding_mismatch") from None
        return self.adapter

    @staticmethod
    def _output_items(value: Any, expected_ids: list[str]) -> list[dict[str, Any]]:
        """Map the model's batch-local ``item_id`` rows back onto plan ids.

        The model only ever sees ``item_id`` (see ``_process_batches``), so the
        order-plan identity is restored here from the batch position.  Every
        index in ``0..len-1`` must appear exactly once; the model may return
        them in any order.
        """

        if not isinstance(value, Mapping) or set(value) != {"items"} or not isinstance(value.get("items"), list):
            raise C2WorkerError("schema_violation")
        rows = value["items"]
        if len(rows) != len(expected_ids):
            raise C2WorkerError("id_mismatch")
        by_index: dict[int, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {"item_id", "relevance", "score", "reason"}:
                raise C2WorkerError("schema_violation")
            item_id = row["item_id"]
            score = row["score"]
            reason = row["reason"]
            if (
                isinstance(item_id, bool)
                or not isinstance(item_id, int)
                or item_id in by_index
                or not 0 <= item_id < len(expected_ids)
            ):
                raise C2WorkerError("id_mismatch")
            if row["relevance"] not in {"relevant", "not_relevant", "uncertain"}:
                raise C2WorkerError("schema_violation")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)) or not 0 <= float(score) <= 1:
                raise C2WorkerError("schema_violation")
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
                raise C2WorkerError("schema_violation")
            by_index[item_id] = {
                "plan_id": expected_ids[item_id],
                "relevance": row["relevance"],
                "score": float(score),
                "reason": reason,
            }
        if set(by_index) != set(range(len(expected_ids))):
            raise C2WorkerError("id_mismatch")
        return [by_index[index] for index in range(len(expected_ids))]

    @staticmethod
    def _failure(value: Any) -> tuple[str, str]:
        if isinstance(value, OrderPlanVllmError):
            return value.failure_type, value.code
        if isinstance(value, C2WorkerError):
            mapping = {
                "schema_violation": "schema_violation",
                "id_mismatch": "id_mismatch",
                "binding_mismatch": "binding_mismatch",
                "payload_not_approved": "payload_not_approved",
                "transport": "transport",
                "policy_rejected": "policy_rejected",
            }
            failure_type = mapping.get(value.code, "unknown")
            return failure_type, value.code
        if isinstance(value, TimeoutError):
            return "timeout", "timeout"
        return "unknown", "worker_error"

    def _new_attempt(
        self,
        session: Session,
        execution: OrderPlanScreeningExecution,
        batch: Mapping[str, Any],
        attempt_no: int,
        stage2: Mapping[str, str],
    ) -> tuple[OrderPlanScreeningBatchAttempt, datetime]:
        started = self.clock()
        plan_ids = [item.plan_id for item in batch["items"]]
        attempt = OrderPlanScreeningBatchAttempt(
            attempt_id=uuid4(),
            execution_id=execution.execution_id,
            batch_id=batch["batch_id"],
            sequence=batch["sequence"],
            attempt_no=attempt_no,
            schema_version="bidops.order-plan-screening-batch-attempt-row.v1",
            producer="screening-worker",
            consumer="screening-merge-and-observability",
            plan_count=len(plan_ids),
            plan_ids_jsonb=plan_ids,
            plan_ids_sha256=_sha256_json(plan_ids),
            model_name=stage2["model_name"],
            model_digest=stage2["model_digest"],
            prompt_version=stage2["prompt_version"],
            prompt_sha256=stage2["prompt_sha256"],
            company_profile_version=stage2["company_profile_version"],
            company_profile_sha256=stage2["company_profile_sha256"],
            generation_config_sha256=stage2["generation_config_sha256"],
            attempt_status="running",
            started_at=started,
            finished_at=None,
            created_at=started,
        )
        session.add(attempt)
        session.commit()
        return attempt, started

    def _finish_attempt(
        self,
        session: Session,
        attempt: OrderPlanScreeningBatchAttempt,
        *,
        status: str,
        started: datetime,
        failure_type: str | None = None,
        failure_code: str | None = None,
        response_ref: str | None = None,
        input_tokens: int | None = None,
        cached_input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        claimed = self._assert_claim(session, attempt.execution_id)
        finished = self.clock()
        claimed.heartbeat_at = finished
        attempt.attempt_status = status
        attempt.failure_type = failure_type
        attempt.failure_code = failure_code
        attempt.response_object_ref = response_ref
        attempt.input_tokens = input_tokens
        attempt.cached_input_tokens = cached_input_tokens
        attempt.output_tokens = output_tokens
        attempt.total_tokens = total_tokens
        attempt.duration_ms = duration_ms if duration_ms is not None else max(0, int((finished - started).total_seconds() * 1000))
        attempt.finished_at = finished
        session.commit()
        return {
            "attempt_no": attempt.attempt_no,
            "status": status,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "measurement": {
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "duration_ms": attempt.duration_ms,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            },
        }

    def _process_batches(
        self,
        session: Session,
        execution: OrderPlanScreeningExecution,
        input_model: OrderPlanScreeningInputArtifact,
        binding: Mapping[str, Any],
        stage2: Mapping[str, str],
        company: Mapping[str, Any],
        prompt: str,
        generation: Mapping[str, Any],
        batch_specs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        adapter = self._adapter(stage2, generation)
        progress_directory = self._execution_dir(execution)
        input_titles = {item.plan_id: item.title for item in input_model.items}
        decision_batches: list[dict[str, Any]] = []
        decision_items: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        telemetry_batches: list[dict[str, Any]] = []
        overall_started = execution.started_at or self.clock()
        for index, batch in enumerate(batch_specs):
            session.expire_all()
            current = session.get(OrderPlanScreeningExecution, execution.execution_id)
            if current is None:
                raise C2WorkerError("execution_not_found")
            if current.status not in ACTIVE_STATUSES or current.active_slot != 1:
                raise C2WorkerError("stale_execution")
            current.heartbeat_at = self.clock()
            session.commit()
            if current.status == "중지 요청":
                break
            expected_ids = [item.plan_id for item in batch["items"]]
            # The approved prompt contracts a batch-local ``item_id`` and a
            # ``company_capabilities`` object, and the C-2 selection experiment
            # sends exactly this shape.  The real order-plan number never
            # leaves the boundary; it is restored from the batch position
            # below ([ADR-0044]).
            payload = {
                "company_capabilities": company,
                "items": [
                    {"item_id": index, "title": input_titles[plan_id]}
                    for index, plan_id in enumerate(expected_ids)
                ],
            }
            batch_attempts: list[dict[str, Any]] = []
            batch_status = "failed"
            batch_failure: tuple[str, str] | None = None
            attempt_count = 0
            for attempt_no in (1, 2):
                attempt_count = attempt_no
                attempt, started = self._new_attempt(session, current, batch, attempt_no, stage2)
                try:
                    current.heartbeat_at = self.clock()
                    session.commit()
                    current = self._assert_claim(session, execution.execution_id)
                    if current.status != "실행 중" or not self.settings.c2_execution_allowed:
                        raise C2WorkerError("policy_rejected")
                    # The adapter puts the approved prompt in the system
                    # message and the payload in the user message.
                    response = adapter.invoke(prompt=prompt, payload=payload, expected_model=stage2["model_name"])
                    structured = response.structured_output if hasattr(response, "structured_output") else response["structured_output"]
                    output = self._output_items(structured, expected_ids)
                    raw = response.approved_raw_response if hasattr(response, "approved_raw_response") else response.get("approved_raw_response")
                    if not isinstance(raw, bytes):
                        raise C2WorkerError("transport")
                    store = self.raw_response_store or EncryptedModelResponseStore(self.settings)
                    try:
                        stored = store.put_encrypted(raw, retention_days=self.settings.c2_response_retention_days, content_type="application/json")
                    except (ObjectStoreError, OSError):
                        raise C2WorkerError("transport") from None
                    response_ref = json.dumps(
                        {
                            key: stored.get(key)
                            for key in (
                                "object_key", "object_version_id", "etag", "encryption_key_ref",
                                "plaintext_sha256", "plaintext_size_bytes",
                            )
                            if isinstance(stored.get(key), (str, int))
                        },
                        sort_keys=True,
                    )
                    measurement = self._finish_attempt(
                        session,
                        attempt,
                        status="success",
                        started=started,
                        response_ref=response_ref,
                        input_tokens=getattr(response, "input_tokens", None),
                        cached_input_tokens=getattr(response, "cached_input_tokens", None),
                        output_tokens=getattr(response, "output_tokens", None),
                        total_tokens=getattr(response, "total_tokens", None),
                        duration_ms=getattr(response, "duration_ms", None),
                    )
                    batch_attempts.append(measurement)
                    decision_batches.append({"batch_id": batch["batch_id"], "sequence": batch["sequence"], "plan_ids": expected_ids, "attempt_count": attempt_count, "status": "success"})
                    for item in output:
                        decision_items.append({**item, "batch_id": batch["batch_id"], "attempt_no": attempt_no})
                    batch_status = "success"
                    break
                except Exception as error:
                    failure_type, failure_code = self._failure(error)
                    retryable = failure_type in {"timeout", "truncated_output", "schema_violation", "id_mismatch", "transport"}
                    attempt_status = "rejected" if failure_type in {"model_mismatch", "binding_mismatch", "payload_not_approved", "policy_rejected"} else "failed"
                    measurement = self._finish_attempt(session, attempt, status=attempt_status, started=started, failure_type=failure_type, failure_code=failure_code)
                    batch_attempts.append(measurement)
                    batch_failure = (failure_type, failure_code)
                    if retryable and attempt_no < 2:
                        continue
                    outcome = "rejected" if attempt_status == "rejected" else "unknown" if failure_type == "unknown" else "failed"
                    failures.append({"batch_id": batch["batch_id"], "sequence": batch["sequence"], "plan_ids": expected_ids, "attempt_count": attempt_count, "max_attempts": 2, "failure_type": failure_type, "outcome": outcome, "status": "human_review_required", "error_code": failure_code})
                    decision_batches.append({"batch_id": batch["batch_id"], "sequence": batch["sequence"], "plan_ids": expected_ids, "attempt_count": attempt_count, "status": attempt_status})
                    break
            telemetry_batches.append({"batch_id": batch["batch_id"], "sequence": batch["sequence"], "status": batch_status if batch_status == "success" else ("rejected" if batch_failure and batch_failure[0] in {"model_mismatch", "binding_mismatch", "payload_not_approved", "policy_rejected"} else "failed"), "attempts": batch_attempts})
            current = self._assert_claim(session, execution.execution_id)
            current.heartbeat_at = self.clock()
            session.commit()
            self._write_batch_progress(
                progress_directory,
                execution,
                batch,
                decision_batches[-1],
                [item for item in decision_items if item["batch_id"] == batch["batch_id"]],
                failures[-1] if failures and failures[-1]["batch_id"] == batch["batch_id"] else None,
                telemetry_batches[-1],
            )
        finished = self.clock()
        success_count = len(decision_items)
        failure_status = "none" if not failures else "rejected" if all(item["outcome"] == "rejected" for item in failures) else "failed" if all(item["outcome"] == "failed" for item in failures) else "partial"
        candidate_count = sum(len(batch["items"]) for batch in batch_specs)
        decisions_status = "성공" if not failures and success_count == candidate_count else "부분 성공" if success_count else "실패"
        return {
            "binding": dict(binding),
            "stage2": dict(stage2),
            "batch_specs": batch_specs,
            "decision_batches": decision_batches,
            "decision_items": decision_items,
            "failures": failures,
            "failure_status": failure_status,
            "decisions_status": decisions_status,
            "telemetry_batches": telemetry_batches,
            "overall_started": overall_started,
            "overall_finished": finished,
            "candidate_count": candidate_count,
            "success_count": success_count,
        }

    def _register_artifact(self, session: Session, execution_id: UUID, kind: str, path: Path, document: Mapping[str, Any]) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            raise C2WorkerError("artifact_invalid") from None
        session.add(OrderPlanScreeningArtifact(
            execution_id=execution_id,
            kind=kind,
            schema_version=str(document["schema_version"]),
            producer=str(document["producer"]),
            consumer=str(document["consumer"]),
            sha256=_sha256_bytes(data),
            byte_count=len(data),
            object_version=_sha256_bytes(data),
            validation_status="valid",
            created_at=self.clock(),
        ))

    def _write_worker_artifacts(
        self,
        session: Session,
        execution: OrderPlanScreeningExecution,
        input_model: OrderPlanScreeningInputArtifact,
        ranking: OrderPlanScreeningRankingArtifact,
        stage2: Mapping[str, str],
        state: Mapping[str, Any],
        *,
        require_claim: bool = True,
        commit: bool = True,
    ) -> None:
        claimed = self._assert_claim(session, execution.execution_id) if require_claim else session.get(OrderPlanScreeningExecution, execution.execution_id)
        if claimed is None:
            raise C2WorkerError("execution_not_found")
        directory = self._execution_dir(execution)
        input_digest = _sha256_bytes((directory / "screening-input.json").read_bytes())
        ranking_digest = _sha256_bytes((directory / "screening-ranking.json").read_bytes())
        created_at = input_model.created_at.isoformat()
        decisions = {
            "schema_version": "bidops.order-plan-screening-decisions.v1",
            "producer": "order-plan-screening-qwen-worker",
            "consumer": "order-plan-screening-merge",
            "execution_id": str(execution.execution_id),
            "source_run_id": execution.source_run_id,
            "input_artifact_sha256": input_digest,
            "ranking_artifact_sha256": ranking_digest,
            "binding": {
                "model_name": stage2["model_name"],
                "model_digest": stage2["model_digest"],
                "prompt_version": stage2["prompt_version"],
                "prompt_sha256": stage2["prompt_sha256"],
                "company_profile_version": stage2["company_profile_version"],
                "company_profile_sha256": stage2["company_profile_sha256"],
                "generation_config_sha256": stage2["generation_config_sha256"],
            },
            "status": state["decisions_status"],
            "candidate_count": state["candidate_count"],
            "success_count": state["success_count"],
            "failure_count": len(state["failures"]),
            "batch_count": len(state["decision_batches"]),
            "batches": state["decision_batches"],
            "items": state["decision_items"],
            "created_at": created_at,
        }
        failures = {
            "schema_version": "bidops.order-plan-screening-failures.v1",
            "producer": "order-plan-screening-worker",
            "consumer": "order-plan-screening-review-and-merge",
            "execution_id": str(execution.execution_id),
            "source_run_id": execution.source_run_id,
            "status": state["failure_status"],
            "failure_count": len(state["failures"]),
            "failures": state["failures"],
            "created_at": created_at,
        }
        failure_by_batch = {row["batch_id"]: row for row in state["failures"]}
        telemetry_batches = []
        for row in state["telemetry_batches"]:
            failure = failure_by_batch.get(row["batch_id"])
            status = "success" if failure is None else "unknown" if failure["outcome"] == "unknown" else failure["outcome"]
            telemetry_batches.append({**row, "status": status})
        finished = state["overall_finished"]
        started = state["overall_started"]
        telemetry = {
            "schema_version": "bidops.order-plan-screening-telemetry.v1",
            "producer": "order-plan-screening-worker",
            "consumer": "observability-and-merge",
            "execution_id": str(execution.execution_id),
            "source_run_id": execution.source_run_id,
            "status": "complete" if not state["failures"] and len(state["decision_batches"]) == len(state["batch_specs"]) else "partial",
            "execution": {
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "duration_ms": max(0, int((finished - started).total_seconds() * 1000)),
                "input_tokens": None,
                "cached_input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            },
            "batches": telemetry_batches,
            "created_at": created_at,
        }
        try:
            decisions = OrderPlanScreeningDecisionsArtifact.model_validate(decisions).model_dump(mode="json")
            failures = OrderPlanScreeningFailuresArtifact.model_validate(failures).model_dump(mode="json")
            telemetry = OrderPlanScreeningTelemetryArtifact.model_validate(telemetry).model_dump(mode="json")
        except ValidationError:
            raise C2WorkerError("artifact_invalid") from None
        for kind, filename, document in (("decisions", "screening-decisions.json", decisions), ("failures", "screening-failures.json", failures), ("telemetry", "screening-telemetry.json", telemetry)):
            self._write_json(directory / filename, document)
            self._register_artifact(session, execution.execution_id, kind, directory / filename, document)
        self._register_artifact(session, execution.execution_id, "ranking", directory / "screening-ranking.json", ranking.model_dump(mode="json"))
        if require_claim:
            claimed.heartbeat_at = self.clock()
        if commit:
            session.commit()

    def _publish(
        self,
        session: Session,
        execution: OrderPlanScreeningExecution,
        input_model: OrderPlanScreeningInputArtifact,
        stage2: Mapping[str, str],
        state: Mapping[str, Any],
    ) -> dict[str, Any]:
        claimed = self._assert_claim(session, execution.execution_id)
        claimed.heartbeat_at = self.clock()
        directory = self._execution_dir(execution)
        try:
            result = OrderPlanScreeningResultArtifact.model_validate(self._read_json(directory / "screening-results.json"))
        except (ValidationError, C2WorkerError):
            raise C2WorkerError("result_invalid") from None
        input_digest = _sha256_bytes((directory / "screening-input.json").read_bytes())
        if (
            result.execution_id != str(execution.execution_id)
            or result.source_run_id != execution.source_run_id
            or result.input_artifact_sha256 != input_digest
            or result.policy_version != execution.policy_version
            or result.policy_sha256 != execution.policy_sha256
            or len(result.items) != input_model.population_count
        ):
            raise C2WorkerError("result_invalid")
        plan_ids = {item.plan_id for item in input_model.items}
        plans = {
            row.order_plan_unty_no: row
            for row in session.scalars(
                select(OrderPlan).join(OrderPlanObservation).where(OrderPlanObservation.run_id == execution.source_run_id)
            ).all()
        }
        if set(plans) != plan_ids:
            raise C2WorkerError("source_run_incomplete")
        result_digest = _sha256_bytes((directory / "screening-results.json").read_bytes())
        for item in result.items:
            plan = plans.get(item.plan_id)
            if plan is None:
                raise C2WorkerError("result_invalid")
            session.add(OrderPlanScreeningResult(
                id=uuid4(),
                execution_id=execution.execution_id,
                source_run_id=execution.source_run_id,
                order_plan_id=plan.id,
                schema_version="bidops.order-plan-screening-result-row.v1",
                producer="order-plan-screening-merge",
                consumer="postgres-loader-and-review-api",
                input_artifact_sha256=input_digest,
                policy_version=result.policy_version,
                policy_sha256=result.policy_sha256,
                binding_sha256=execution.binding_sha256,
                result_sha256=_sha256_json(item.model_dump(mode="json")),
                stage1_rank=item.stage1_rank,
                stage1_score=item.stage1_score,
                nearest_capability=item.nearest_capability,
                stage1_status=item.stage1_status,
                stage2_status=item.stage2_status,
                qwen_relevance=item.qwen_relevance,
                qwen_score=item.qwen_score,
                qwen_reason=item.qwen_reason,
                batch_id=item.batch_id,
                attempt_no=item.attempt_no,
                failure_code=item.failure_code,
                created_at=result.created_at,
            ))
        self._register_artifact(session, execution.execution_id, "result", directory / "screening-results.json", result.model_dump(mode="json"))
        current = session.get(OrderPlanScreeningExecution, execution.execution_id)
        if current is None:
            raise C2WorkerError("execution_not_found")
        counts = result.counts
        successful = counts.stage2_relevant + counts.stage2_not_relevant + counts.stage2_uncertain
        failures = counts.stage1_failed + counts.stage2_failed + counts.stage2_rejected + sum(item.stage2_status == "unknown" for item in result.items)
        stopped = current.status == "중지 요청"
        current.status = "중단됨" if stopped else "실패" if result.status == "거부됨" else result.status
        current.active_slot = None
        current.finished_at = self.clock()
        current.partial_artifact = result.partial_artifact or stopped
        current.error_code = "user_requested" if stopped else None if current.status in {"성공", "부분 성공"} else "result_failed"
        current.candidate_count = counts.stage1_selected
        current.completed_count = successful
        current.failure_count = failures
        current.stage1_selected_count = counts.stage1_selected
        current.stage1_filtered_out_count = counts.stage1_filtered_out
        current.stage1_failed_count = counts.stage1_failed
        current.stage2_relevant_count = counts.stage2_relevant
        current.stage2_not_relevant_count = counts.stage2_not_relevant
        current.stage2_uncertain_count = counts.stage2_uncertain
        current.stage2_failed_count = counts.stage2_failed
        current.stage2_rejected_count = counts.stage2_rejected
        current.human_review_count = counts.human_review_count
        session.commit()
        return {"execution_id": str(current.execution_id), "status": current.status, "result_sha256": result_digest}
