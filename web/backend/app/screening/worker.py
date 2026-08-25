"""FIFO screening worker using only the T4 pure model-call boundary."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from threading import Event
from typing import Any, Callable, Mapping
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings
from ..ingest.loader import ingest_run, parse_run_id
from ..models import CompanyProfileSnapshot, Notice, Run, ScreeningAttempt, ScreeningExecution, ScreeningPolicy
from .artifacts import ArtifactError, ArtifactStore, aware_iso, canonical_bytes, sha256_bytes
from .contracts import (
    MODEL_NAME,
    PERSPECTIVE_NAMES,
    add_two_axis_metadata,
    new_trace_id,
    validate_counterargument,
    validate_judgment,
    validate_perspective,
)
from .execution_store import ScreeningExecutionStore
from .ollama import OllamaCallError, OllamaClient
from .orchestrator import ScreeningCreationError, _notice_common
from .policy import canonical_policy_bytes
from .profile_snapshot import read_profile_snapshot
from .prompts import assemble_counterargument_prompt, assemble_perspective_prompt, assemble_synthesis_prompt, schema_for_stage
from .queue import INTERRUPTED, RUNNING, ScreeningQueueError


class WorkerError(RuntimeError):
    """A safe worker failure category."""


def _aware(clock: Callable[[], datetime]) -> datetime:
    point = clock()
    if point.tzinfo is None or point.utcoffset() is None:
        raise WorkerError("invalid_state")
    return point


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise WorkerError("execution_failure") from None


def _safe_run_dir(settings: Settings, run_id: str) -> Path:
    if not isinstance(run_id, str) or not run_id or "\\" in run_id or Path(run_id).name != run_id:
        raise WorkerError("input_error")
    configured_root = Path(settings.bidops_root)
    if configured_root.is_symlink():
        raise WorkerError("input_error")
    root = configured_root.resolve()
    data = root / "data"
    base = data / "runs"
    if data.is_symlink() or base.is_symlink():
        raise WorkerError("input_error")
    parsed = parse_run_id(run_id)
    name = parsed[0] if parsed else run_id.split("--", 1)[0]
    candidate = base / name
    try:
        candidate.resolve().relative_to(base.resolve())
    except (OSError, ValueError):
        raise WorkerError("input_error") from None
    if candidate.is_symlink() or not candidate.is_dir():
        raise WorkerError("input_error")
    return candidate


def _profile_sections(raw: bytes) -> dict[str, str]:
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        stripped = line.rstrip("\r\n")
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            number = heading.split(" ", 1)[0].rstrip(".")
            current = number if number and number[0].isdigit() else heading
            sections.setdefault(current, []).append(line)
        elif current is not None:
            sections[current].append(line)
    if not sections:
        return {"1": text}
    return {key: "".join(value) for key, value in sections.items()}


def _stage_failure(exc: BaseException) -> str:
    value = getattr(exc, "failure_type", None)
    return value if value in {"timeout", "truncated_output", "schema_violation", "evidence_missing", "counterargument_repetition"} else "schema_violation"


class ScreeningWorker:
    """Claim, verify, process and finish one globally active execution."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        store: ScreeningExecutionStore | None = None,
        session_factory: Any | None = None,
        ollama: OllamaClient | Any | None = None,
        ollama_client: OllamaClient | Any | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        poll_seconds: float = 1.0,
        popen: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.settings = settings or get_settings()
        if isinstance(session_factory, Session):
            session_factory = sessionmaker(bind=session_factory.get_bind(), class_=Session, autoflush=False, expire_on_commit=False)
        self.session_factory = session_factory
        self.store = store or ScreeningExecutionStore(session_factory=session_factory, settings=self.settings)
        self.ollama = ollama or ollama_client or OllamaClient(settings=self.settings)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self.poll_seconds = max(0.01, float(poll_seconds))
        self._popen = popen

    def run_once(self) -> ScreeningExecution | None:
        row = self.store.claim(now=_aware(self.clock))
        if row is None:
            return None
        try:
            self._process(row)
        except WorkerError as exc:
            # A terminal transition is part of the durable contract.  If it
            # cannot be written, surface that storage failure to the caller
            # instead of silently leaving an active slot behind.
            self.store.finish_failure(row.execution_id, error_summary=str(exc), now=_aware(self.clock))
        except Exception:
            self.store.finish_failure(row.execution_id, error_summary="execution_failure", now=_aware(self.clock))
        return self._get_execution(row.execution_id)

    def run_forever(self, stop_event: Event | None = None, *, poll_seconds: float | None = None) -> None:
        event = stop_event or Event()
        delay = self.poll_seconds if poll_seconds is None else max(0.01, poll_seconds)
        while not event.is_set():
            row = self.run_once()
            if row is None:
                self.sleep(delay)

    def run_until(self, target_execution_id: str, *, stop_event: Event | None = None, poll_seconds: float | None = None) -> ScreeningExecution:
        event = stop_event or Event()
        delay = self.poll_seconds if poll_seconds is None else max(0.01, poll_seconds)
        while True:
            target = self._get_execution(target_execution_id)
            if target is None:
                raise WorkerError("input_error")
            if target.status in {"성공", "부분 성공", "실패", INTERRUPTED}:
                return target
            # Claiming itself enforces FIFO and the one active slot.  An active
            # earlier row is therefore processed before this target.
            self.run_once()
            if event.is_set():
                return self._get_execution(target_execution_id) or target
            latest = self._get_execution(target_execution_id)
            if latest and latest.status in {"성공", "부분 성공", "실패", INTERRUPTED}:
                return latest
            self.sleep(delay)

    process_once = run_once
    process = run_once

    def _session(self) -> Session:
        if self.session_factory is None:
            from ..db import SessionLocal
            return SessionLocal()
        value = self.session_factory()
        if not isinstance(value, Session):
            raise TypeError("session factory did not return Session")
        return value

    def _get_execution(self, execution_id: str) -> ScreeningExecution | None:
        with self._session() as session:
            return session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id))

    def _process(self, row: ScreeningExecution) -> None:
        store = ArtifactStore(Path(self.settings.bidops_root))
        expected_dir = f"data/screening-executions/{row.execution_id}"
        if row.artifact_dir != expected_dir or row.input_artifact_path != f"{expected_dir}/screening-input.json":
            raise WorkerError("input_mismatch")
        input_raw = store.read_bytes(row.execution_id, "screening-input.json", expected_digest=row.input_artifact_digest)
        input_value = _read_json(store.execution_dir(row.execution_id) / "screening-input.json")
        self._verify_binding(row, input_value, input_raw)
        with self._session() as session:
            policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == row.policy_version))
            profile = session.scalar(select(CompanyProfileSnapshot).where(CompanyProfileSnapshot.version == row.company_profile_version))
            source_run = session.scalar(select(Run).where(Run.id == row.source_run_id))
            if policy is None or profile is None or source_run is None:
                raise WorkerError("input_error")
            if source_run.status not in {"active", "complete", "성공", "부분 성공"}:
                raise WorkerError("input_error")
            for notice in input_value["notices"]:
                db_notice = session.scalar(select(Notice).where(Notice.run_id == row.source_run_id, Notice.notice_key == notice.get("notice_id")))
                if db_notice is None or (row.scope == "single_notice" and db_notice.id != row.notice_pk):
                    raise WorkerError("input_mismatch")
            policy_body = {
                "schema_version": policy.schema_version, "policy_version": policy.policy_version,
                "prompt_version": policy.prompt_version, "perspective_prompts": policy.perspective_prompts_json,
                "counterargument_prompt": policy.counterargument_prompt_json, "synthesis_prompt": policy.synthesis_prompt_json,
                "candidate_selection": policy.candidate_selection_json, "thresholds": policy.thresholds_json,
            }
            try:
                if policy.schema_version != "bidops.screening-policy.v1" or policy.policy_version != row.policy_version or policy.prompt_version != row.prompt_version or policy.content_digest != sha256_bytes(canonical_policy_bytes(policy_body)):
                    raise WorkerError("policy_mismatch")
                allowed_policy_statuses = {
                    "schedule": {"active"},
                    "cli_single": {"activation_candidate", "active"},
                    "manual_run": {"activation_candidate", "active"},
                    "quality_gate": {"activation_candidate", "active"},
                }
                if policy.status not in allowed_policy_statuses.get(row.trigger, set()):
                    raise WorkerError("input_error")
                if profile.version != row.company_profile_version or profile.digest != row.company_profile_digest or profile.version != f"company-profile.sha256:{profile.digest}":
                    raise WorkerError("profile_mismatch")
                if sha256_bytes(canonical_policy_bytes(policy_body)) != policy.content_digest:
                    raise WorkerError("policy_mismatch")
                profile_raw = read_profile_snapshot(session, version=row.company_profile_version, project_root=Path(self.settings.bidops_root))
            except WorkerError:
                raise
            except Exception:
                raise WorkerError("execution_failure") from None
        identity = self.ollama.inspect_model()
        if identity.model_name != row.model_name or identity.digest != row.model_digest:
            raise WorkerError("model_mismatch")
        notices = input_value["notices"]
        completed = 0
        failures: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        decisions_value = self._decisions(row, input_value, decisions)
        store.replace_json(row.execution_id, "screening-decisions.json", decisions_value)
        with self.store.heartbeat_pump(row.execution_id):
            for notice in notices:
                if self.store.should_stop(row.execution_id):
                    self.store.finish_interrupted(row.execution_id, now=_aware(self.clock))
                    return
                self.store.update_progress(row.execution_id, current_notice_id=notice["notice_id"], current_stage="기술 적합성")
                mode = notice["judgment_mode"]
                if mode == "승계":
                    carried = self._carry(row, input_value, notice)
                    if carried is None:
                        failure = self._failure(notice, "병합·검증", "schema_violation", 0, None, None, "carried_over_validation")
                        failures.append(failure)
                        self._persist_failures(store, row, input_value, failures)
                        self.store.update_progress(row.execution_id, failure_count=len(failures))
                    else:
                        decisions.append(carried)
                        self._persist_decisions(store, row, input_value, decisions)
                        completed += 1
                        self.store.update_progress(row.execution_id, completed_count=completed)
                    continue
                result, failed = self._run_notice(row, input_value, notice, policy_body, _profile_sections(profile_raw), store)
                if result is None and failed is None:
                    # A stop may be observed after a blocking call returned and
                    # its attempts were persisted. Never assert or classify
                    # that boundary as a notice failure.
                    if self.store.should_stop(row.execution_id):
                        self.store.finish_interrupted(row.execution_id, now=_aware(self.clock))
                        return
                    raise WorkerError("execution_failure")
                if failed is not None:
                    failures.append(failed)
                    self._persist_failures(store, row, input_value, failures)
                    self.store.update_progress(row.execution_id, failure_count=len(failures))
                else:
                    assert result is not None
                    decisions.append(result)
                    self._persist_decisions(store, row, input_value, decisions)
                    completed += 1
                    self.store.update_progress(row.execution_id, completed_count=completed)
                if self.store.should_stop(row.execution_id):
                    self.store.finish_interrupted(row.execution_id, now=_aware(self.clock))
                    return
        if row.scope == "full_run":
            if not decisions:
                self.store.finish_failure(row.execution_id, completed_count=completed, failure_count=len(failures), candidate_count=len(notices), error_summary="execution_failure", now=_aware(self.clock))
                return
            result_path = self._merge(row, input_value, store, bool(failures))
            self._publish(row, input_value, store, result_path)
        if completed == 0:
            status = "실패"
        elif failures and row.scope == "full_run":
            status = "부분 성공"
        else:
            status = "실패" if failures else "성공"
        self.store.finish(row.execution_id, status=status, completed_count=completed, failure_count=len(failures), candidate_count=len(notices), now=_aware(self.clock), error_summary="execution_failure" if failures else None)

    def _verify_binding(self, row: ScreeningExecution, value: Any, raw: bytes) -> None:
        expected_keys = {"schema_version", "execution_id", "run_id", "generated_at", "source_window", "policy_version", "prompt_version", "company_profile_version", "company_profile_digest", "candidate_count", "notices"}
        if not isinstance(value, dict) or set(value) != expected_keys or value.get("schema_version") != "bidops.screening-input.v1":
            raise WorkerError("input_error")
        try:
            if canonical_bytes(value) != raw:
                raise WorkerError("input_mismatch")
        except ArtifactError:
            raise WorkerError("input_error") from None
        if value.get("execution_id") != row.execution_id or value.get("run_id") != row.source_run_id:
            raise WorkerError("input_mismatch")
        expected = {"single_notice": 1, "full_run": None, "quality_sample": None}[row.scope]
        notices = value.get("notices")
        if not isinstance(notices, list) or value.get("candidate_count") != len(notices) or (expected is not None and len(notices) != expected):
            raise WorkerError("input_error")
        if row.scope == "single_notice" and (notices[0].get("notice_id") != row.notice_id):
            raise WorkerError("input_mismatch")
        if value.get("policy_version") != row.policy_version or value.get("prompt_version") != row.prompt_version or value.get("company_profile_version") != row.company_profile_version or value.get("company_profile_digest") != row.company_profile_digest:
            raise WorkerError("input_mismatch")
        window = value.get("source_window")
        if not isinstance(window, dict) or set(window) != {"from", "to", "timezone"} or window.get("timezone") != "Asia/Seoul":
            raise WorkerError("input_error")
        try:
            if not isinstance(value.get("generated_at"), str):
                raise WorkerError("input_error")
            generated = datetime.fromisoformat(value["generated_at"].replace("Z", "+00:00"))
            if generated.tzinfo is None or generated.utcoffset() is None:
                raise WorkerError("input_error")
            window_from = date.fromisoformat(window["from"])
            window_to = date.fromisoformat(window["to"])
            if window_from > window_to:
                raise WorkerError("input_error")
        except (TypeError, ValueError):
            raise WorkerError("input_error") from None
        notice_keys = {
            "notice_id", "source_type", "title", "agency", "method", "url", "collection_bucket",
            "published_at", "deadline_at", "budget", "estimated_price", "procurement_class",
            "region_limit", "lifecycle", "qualification_flags", "attachments", "focus_matches",
            "performance_matches", "performance_top_score", "candidate_sources", "unknown_fields",
            "sample_stratum", "sample_role", "raw_source", "judgment_mode", "carry_over_from",
            "rejudge_reason",
        }
        if any(
            not isinstance(n, dict)
            or set(n) != notice_keys
            or n.get("notice_id") in (None, "")
            or n.get("judgment_mode") not in {"신규", "재판정", "승계"}
            for n in notices
        ):
            raise WorkerError("input_error")
        seen: set[str] = set()
        for notice in notices:
            if notice["notice_id"] in seen:
                raise WorkerError("input_error")
            seen.add(notice["notice_id"])
            try:
                _notice_common({key: notice[key] for key in notice_keys if key not in {"judgment_mode", "carry_over_from", "rejudge_reason"}})
            except ScreeningCreationError:
                raise WorkerError("input_error") from None
            mode = notice["judgment_mode"]
            if mode == "신규" and (notice["carry_over_from"] is not None or notice["rejudge_reason"] is not None):
                raise WorkerError("input_error")
            if mode == "재판정" and (notice["carry_over_from"] is not None or notice["rejudge_reason"] not in {"정정", "재공고", "본공고 전환", "담당자 요청"}):
                raise WorkerError("input_error")
            if mode == "승계" and (not isinstance(notice["carry_over_from"], str) or not notice["carry_over_from"].strip() or notice["carry_over_from"] == row.source_run_id or notice["rejudge_reason"] is not None):
                raise WorkerError("input_error")

    def _decisions(self, row: ScreeningExecution, input_value: Mapping[str, Any], judgments: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schema_version": "bidops.decisions.v3", "execution_id": row.execution_id, "run_id": row.source_run_id,
            "generated_at": input_value["generated_at"], "screening_basis": "회차에 고정된 정규화 공고와 회사 프로필·정책 버전",
            "model_name": row.model_name, "model_digest": row.model_digest, "prompt_version": row.prompt_version,
            "policy_version": row.policy_version, "company_profile_version": row.company_profile_version,
            "company_profile_digest": row.company_profile_digest, "judgments": judgments,
        }

    def _persist_decisions(self, store: ArtifactStore, row: ScreeningExecution, input_value: Mapping[str, Any], judgments: list[dict[str, Any]]) -> None:
        store.replace_json(row.execution_id, "screening-decisions.json", self._decisions(row, input_value, judgments))

    def _persist_failures(self, store: ArtifactStore, row: ScreeningExecution, input_value: Mapping[str, Any], failures: list[dict[str, Any]]) -> None:
        store.replace_json(row.execution_id, "screening-failures.json", {"schema_version": "bidops.screening-failures.v1", "execution_id": row.execution_id, "run_id": row.source_run_id, "generated_at": input_value["generated_at"], "failure_count": len(failures), "failures": failures})

    def _persist_metadata(self, row: ScreeningExecution, metadata: Any, response_path: str | None, value: Any | None) -> None:
        with self._session() as session:
            session.add(ScreeningAttempt(
                execution_id=row.execution_id, notice_id=metadata.notice_id, stage=metadata.stage,
                attempt_no=metadata.attempt_no, status="success" if metadata.status == "success" else "failure",
                failure_type=metadata.failure_type, trace_id=metadata.trace_id, span_id=metadata.span_id,
                done_reason=metadata.done_reason, prompt_eval_count=metadata.prompt_eval_count, eval_count=metadata.eval_count,
                prompt_eval_duration_ns=metadata.prompt_eval_duration_ns, eval_duration_ns=metadata.eval_duration_ns,
                load_duration_ns=metadata.load_duration_ns, total_duration_ns=metadata.total_duration_ns,
                started_at=metadata.started_at, finished_at=metadata.finished_at or metadata.started_at,
                response_artifact_path=response_path, error_summary=(metadata.failure_type or "execution_failure") if metadata.status != "success" else None,
            ))
            session.commit()

    def _telemetry(self, row: ScreeningExecution, metadata: Any) -> dict[str, Any]:
        stage = {"counterargument": "반론 검토", "synthesis": "종합 판정"}.get(metadata.stage, metadata.stage)
        return {
            "schema_version": "bidops.screening-telemetry.v1", "execution_id": row.execution_id,
            "trace_id": metadata.trace_id, "span_id": metadata.span_id, "notice_id": metadata.notice_id,
            "stage": stage, "attempt_no": metadata.attempt_no, "status": metadata.status,
            "failure_type": metadata.failure_type, "done_reason": metadata.done_reason,
            "model_name": row.model_name, "model_digest": row.model_digest,
            "prompt_eval_count": metadata.prompt_eval_count, "eval_count": metadata.eval_count,
            "prompt_eval_duration_ns": metadata.prompt_eval_duration_ns,
            "eval_duration_ns": metadata.eval_duration_ns, "load_duration_ns": metadata.load_duration_ns,
            "total_duration_ns": metadata.total_duration_ns,
            "started_at": aware_iso(metadata.started_at),
            "finished_at": aware_iso(metadata.finished_at or metadata.started_at),
        }

    def _record_attempt(self, row: ScreeningExecution, metadata: Any, store: ArtifactStore, value: Any | None = None) -> None:
        response_path = None
        if metadata.status == "success" and value is not None:
            safe_notice = sha256_bytes(metadata.notice_id.encode())[:16]
            response_path, _ = store.write_json(row.execution_id, f"responses/{safe_notice}/{metadata.stage}-{metadata.attempt_no}.json", value)
        self._persist_metadata(row, metadata, response_path, value)
        store.append_jsonl(row.execution_id, "screening-telemetry.jsonl", self._telemetry(row, metadata))

    def _run_notice(self, row: ScreeningExecution, input_value: Mapping[str, Any], notice: dict[str, Any], policy: Mapping[str, Any], profile: Mapping[str, Any], store: ArtifactStore) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        trace = new_trace_id()
        perspectives: list[dict[str, Any]] = []

        def record_failure_attempt(metadata: Any) -> None:
            # T4 invokes this callback as soon as each HTTP/validation attempt
            # finishes.  Success is recorded below once its parsed canonical
            # value is available for the restricted response artifact; failed
            # retries must not wait for the whole stage or notice.
            if metadata.status == "failure":
                self._record_attempt(row, metadata, store)

        try:
            for name in PERSPECTIVE_NAMES:
                if self.store.should_stop(row.execution_id):
                    return None, None
                self.store.update_progress(row.execution_id, current_notice_id=notice["notice_id"], current_stage=name)
                prompt = assemble_perspective_prompt(policy, name, notice, profile)
                result = self.ollama.generate(prompt.user_message, schema_for_stage(name), execution_id=row.execution_id, notice_id=notice["notice_id"], stage=name, trace_id=trace, validator=lambda value, expected=name: validate_perspective(value, expected_name=expected), attempt_callback=record_failure_attempt)
                self._record_attempt(row, result.metadata, store, result.value)
                perspectives.append(result.value)
                if self.store.should_stop(row.execution_id):
                    return None, None
            if self.store.should_stop(row.execution_id):
                return None, None
            self.store.update_progress(row.execution_id, current_stage="counterargument")
            counter_prompt = assemble_counterargument_prompt(policy, notice, perspectives)
            counter = self.ollama.generate(counter_prompt.user_message, schema_for_stage("counterargument.v1"), execution_id=row.execution_id, notice_id=notice["notice_id"], stage="counterargument", trace_id=trace, validator=validate_counterargument, attempt_callback=record_failure_attempt)
            self._record_attempt(row, counter.metadata, store, counter.value)
            if self.store.should_stop(row.execution_id):
                return None, None
            self.store.update_progress(row.execution_id, current_stage="synthesis")
            synthesis_prompt = assemble_synthesis_prompt(policy, notice, perspectives, counter.value)
            synthesis = self.ollama.generate(synthesis_prompt.user_message, schema_for_stage("judgment.v3"), execution_id=row.execution_id, notice_id=notice["notice_id"], stage="synthesis", trace_id=trace, validator=lambda value: validate_judgment(value, notice=notice), attempt_callback=record_failure_attempt)
            self._record_attempt(row, synthesis.metadata, store, synthesis.value)
            judgment = add_two_axis_metadata(synthesis.value)
            judgment.update({
                "judgment_mode": notice["judgment_mode"], "model_name": row.model_name, "model_digest": row.model_digest,
                "prompt_version": row.prompt_version, "policy_version": row.policy_version,
                "company_profile_version": row.company_profile_version, "company_profile_digest": row.company_profile_digest,
                "judged_in_run": row.source_run_id, "recorded_in_run": row.source_run_id, "carried_over": False,
                "rejudge_reason": notice.get("rejudge_reason"),
            })
            return judgment, None
        except OllamaCallError as exc:
            metadata = exc.metadata
            return None, self._failure(notice, metadata.stage, _stage_failure(exc), max(0, len(exc.attempts) - 1), metadata, trace, None)
        except WorkerError:
            raise
        except Exception:
            raise WorkerError("execution_failure") from None

    def _failure(self, notice: Mapping[str, Any], stage: str, failure_type: str, retry_count: int, metadata: Any | None, trace: str | None, context: str | None) -> dict[str, Any]:
        stage_value = {"counterargument": "반론 검토", "synthesis": "종합 판정"}.get(stage, stage)
        if stage_value not in set(PERSPECTIVE_NAMES) | {"반론 검토", "종합 판정"}:
            stage_value = "종합 판정"
        return {"notice_id": notice["notice_id"], "failed_stage": stage_value, "failure_type": failure_type, "last_attempt_at": aware_iso(metadata.finished_at if metadata and metadata.finished_at else _aware(self.clock)), "retry_count": retry_count, "status": "사람 검토 대기", "failure_context": context, "trace_id": metadata.trace_id if metadata else trace, "span_id": metadata.span_id if metadata else None, "error_summary": failure_type}

    def _carry(self, row: ScreeningExecution, input_value: Mapping[str, Any], notice: Mapping[str, Any]) -> dict[str, Any] | None:
        source_dir = _safe_run_dir(self.settings, row.source_run_id)
        decisions_path = source_dir / "screening-decisions.json"
        if not decisions_path.is_file():
            return None
        try:
            old = _read_json(decisions_path)
        except WorkerError:
            return None
        if not isinstance(old, Mapping):
            return None
        top_keys = {
            "schema_version", "execution_id", "run_id", "generated_at", "screening_basis",
            "model_name", "model_digest", "prompt_version", "policy_version",
            "company_profile_version", "company_profile_digest", "judgments",
        }
        if set(old) != top_keys or old.get("run_id") != row.source_run_id or not isinstance(old.get("judgments"), list):
            return None
        values = [item for item in old.get("judgments", []) if isinstance(item, dict) and item.get("notice_id") == notice["notice_id"]]
        if len(values) != 1 or old.get("schema_version") != "bidops.decisions.v3":
            return None
        judgment = dict(values[0])
        required = {
            "notice_id", "judgment_mode", "model_name", "model_digest", "prompt_version", "policy_version",
            "company_profile_version", "company_profile_digest", "judged_in_run", "recorded_in_run",
            "carried_over", "rejudge_reason", "grade", "readiness", "primary_focus", "exclusion_category",
            "summary", "next_action", "perspectives", "matched_performances", "counterarguments",
            "counterargument_resolutions", "verification_items", "two_axis_mixing_flag", "two_axis_mixing_label",
        }
        if set(judgment) != required:
            return None
        if judgment.get("judgment_mode") not in {"신규", "재판정"} or judgment.get("carried_over") is not False:
            return None
        if judgment.get("recorded_in_run") != judgment.get("judged_in_run"):
            return None
        try:
            base = {key: judgment[key] for key in ("notice_id", "grade", "readiness", "primary_focus", "exclusion_category", "summary", "perspectives", "matched_performances", "counterarguments", "counterargument_resolutions", "verification_items", "next_action")}
            validate_judgment(base, notice=notice)
            axes = add_two_axis_metadata(base)
            if judgment.get("two_axis_mixing_flag") != axes["two_axis_mixing_flag"] or judgment.get("two_axis_mixing_label") != axes["two_axis_mixing_label"]:
                return None
        except Exception:
            return None
        judgment["judgment_mode"] = "승계"
        judgment["recorded_in_run"] = row.source_run_id
        judgment["carried_over"] = True
        judgment["rejudge_reason"] = None
        return judgment

    def _merge(self, row: ScreeningExecution, input_value: Mapping[str, Any], store: ArtifactStore, has_failures: bool) -> str:
        root = Path(self.settings.bidops_root)
        input_path = root / row.input_artifact_path
        decisions_path = root / row.artifact_dir / "screening-decisions.json"
        failures_path = root / row.artifact_dir / "screening-failures.json"
        output_path = root / row.artifact_dir / "screening-results.json"
        script = root / "skills" / "bidops-screen" / "scripts" / "build_screening_results.py"
        argv = [sys.executable, str(script), str(input_path), str(decisions_path), "--output", str(output_path)]
        if has_failures:
            argv[3:3] = ["--failures", str(failures_path)]
        try:
            completed = self._popen(argv, cwd=str(root), shell=False, capture_output=True, text=True, check=False)
        except (OSError, subprocess.SubprocessError):
            raise WorkerError("execution_failure") from None
        if completed.returncode != 0 or not output_path.is_file():
            raise WorkerError("execution_failure")
        value = _read_json(output_path)
        if not isinstance(value, dict) or value.get("schema_version") != "bidops.screening.v3":
            raise WorkerError("execution_failure")
        return str(output_path)

    def _publish(self, row: ScreeningExecution, input_value: Mapping[str, Any], store: ArtifactStore, result_path: str) -> None:
        source = _safe_run_dir(self.settings, row.source_run_id)
        runs = source.parent
        self._assert_no_symlinks(source)
        stamp = _aware(self.clock).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        target: Path | None = None
        for _ in range(20):
            candidate = runs / f"{source.name}--screen-{stamp}-{uuid4().hex[:8]}"
            if not candidate.exists() and not candidate.is_symlink():
                target = candidate
                break
        if target is None:
            raise WorkerError("execution_failure")
        derived_id: str | None = None
        try:
            shutil.copytree(source, target, symlinks=False)
            # The current immutable execution input is authoritative; a source
            # run may contain an older screening-input from another execution.
            shutil.copy2(Path(self.settings.bidops_root) / row.input_artifact_path, target / "screening-input.json")
            shutil.copy2(result_path, target / "screening-results.json")
            execution_dir = Path(self.settings.bidops_root) / row.artifact_dir
            for name in ("screening-decisions.json", "screening-failures.json", "screening-telemetry.jsonl"):
                source_file = execution_dir / name
                if source_file.is_file():
                    shutil.copy2(source_file, target / name)
            provenance = {
                "schema_version": "bidops.screening-replacement.v1",
                "source_run_id": row.source_run_id,
                "execution_id": row.execution_id,
                "recorded_at": aware_iso(_aware(self.clock)),
            }
            (target / "screening-replacement-provenance.json").write_bytes(canonical_bytes(provenance))
            with (target / "screening-replacement-provenance.json").open("rb") as handle:
                provenance_bytes = handle.read()
            if sha256_bytes(provenance_bytes) != sha256_bytes(canonical_bytes(provenance)):
                raise WorkerError("execution_failure")
            with self._session() as session:
                # The loader is the sole owner of deterministic Run.id and
                # Notice/Judgment/count ingestion. It commits its own valid
                # transaction before we bind the execution FK.
                loaded = ingest_run(target, session)
                derived_id = loaded.run_id
                run = session.scalar(select(Run).where(Run.id == derived_id))
                if run is None or loaded.run_id != derived_id:
                    raise WorkerError("execution_failure")
                if run.counts_json is None or not isinstance(run.counts_json, dict):
                    raise WorkerError("execution_failure")
                run.counts_json = {**run.counts_json, "replacement_of": row.source_run_id}
                session.commit()
            with self._session() as session:
                bound = session.execute(update(ScreeningExecution).where(ScreeningExecution.execution_id == row.execution_id, ScreeningExecution.published_run_id.is_(None)).values(published_run_id=derived_id))
                if bound.rowcount != 1:
                    raise WorkerError("execution_failure")
                session.commit()
        except WorkerError:
            self._cleanup_publication(target, derived_id)
            raise
        except Exception:
            self._cleanup_publication(target, derived_id)
            raise WorkerError("execution_failure") from None

    @staticmethod
    def _assert_no_symlinks(root: Path) -> None:
        if root.is_symlink():
            raise WorkerError("execution_failure")
        try:
            for entry in os.scandir(root):
                path = Path(entry.path)
                if entry.is_symlink():
                    raise WorkerError("execution_failure")
                if entry.is_dir(follow_symlinks=False):
                    ScreeningWorker._assert_no_symlinks(path)
        except OSError:
            raise WorkerError("execution_failure") from None

    def _cleanup_publication(self, target: Path, derived_id: str | None) -> None:
        if derived_id:
            try:
                with self._session() as session:
                    session.execute(delete(Run).where(Run.id == derived_id))
                    session.commit()
            except Exception:
                pass
        try:
            shutil.rmtree(target)
        except OSError:
            pass


Worker = ScreeningWorker


__all__ = ["ScreeningWorker", "Worker", "WorkerError"]
