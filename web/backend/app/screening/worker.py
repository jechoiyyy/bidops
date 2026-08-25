"""FIFO screening worker using only the T4 pure model-call boundary."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from threading import Event
from typing import Any, Callable, Mapping
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings
from ..ingest.loader import ingest_run, parse_run_id
from ..models import CompanyProfileSnapshot, Judgment, Notice, Run, ScreeningAttempt, ScreeningExecution, ScreeningPolicy
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


_INPUT_KEYS = {
    "schema_version", "execution_id", "run_id", "generated_at", "source_window",
    "policy_version", "prompt_version", "company_profile_version", "company_profile_digest",
    "candidate_count", "notices",
}
_DECISIONS_KEYS = {
    "schema_version", "execution_id", "run_id", "generated_at", "screening_basis",
    "model_name", "model_digest", "prompt_version", "policy_version",
    "company_profile_version", "company_profile_digest", "judgments",
}
_JUDGMENT_KEYS = {
    "notice_id", "judgment_mode", "model_name", "model_digest", "prompt_version",
    "policy_version", "company_profile_version", "company_profile_digest",
    "judged_in_run", "recorded_in_run", "carried_over", "rejudge_reason", "grade",
    "readiness", "primary_focus", "exclusion_category", "summary", "next_action",
    "perspectives", "matched_performances", "counterarguments",
    "counterargument_resolutions", "verification_items", "two_axis_mixing_flag",
    "two_axis_mixing_label",
}
_RESULT_KEYS = {
    "schema_version", "execution_id", "generated_at", "screening_basis", "source_window",
    "model_name", "model_digest", "prompt_version", "policy_version",
    "company_profile_version", "company_profile_digest", "candidate_count", "result_count",
    "failure_count", "partial_artifact", "failure_artifact", "results",
}
_RESULT_ITEM_KEYS = {"notice", "judgment"}
_SAFE_FAILURE_STAGES = set(PERSPECTIVE_NAMES) | {"반론 검토", "종합 판정", "병합·검증"}


def _notice_input_keys() -> tuple[str, ...]:
    return (
        "notice_id", "source_type", "title", "agency", "method", "url",
        "collection_bucket", "published_at", "deadline_at", "budget",
        "estimated_price", "procurement_class", "region_limit", "lifecycle",
        "qualification_flags", "attachments", "focus_matches", "performance_matches",
        "performance_top_score", "candidate_sources", "unknown_fields", "sample_stratum",
        "sample_role", "raw_source", "judgment_mode", "carry_over_from", "rejudge_reason",
    )


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
            if row.scope == "single_notice":
                notice = input_value["notices"][0]
                db_notice = session.scalar(select(Notice).where(Notice.run_id == row.source_run_id, Notice.notice_key == notice.get("notice_id")))
                if db_notice is None or db_notice.id != row.notice_pk:
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
        identity = self.ollama.inspect_model(refresh=True)
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
        elif failures and row.scope in {"full_run", "quality_sample"}:
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
        return {
            "schema_version": "bidops.screening-telemetry.v1", "execution_id": row.execution_id,
            "trace_id": metadata.trace_id, "span_id": metadata.span_id, "notice_id": metadata.notice_id,
            "stage": metadata.stage, "attempt_no": metadata.attempt_no, "status": metadata.status,
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
        input_path = source_dir / "screening-input.json"
        decisions_path = source_dir / "screening-decisions.json"
        failures_path = source_dir / "screening-failures.json"
        if not input_path.is_file() or not decisions_path.is_file():
            return None
        try:
            prior_input_raw = input_path.read_bytes()
            prior_input = _read_json(input_path)
            prior_decisions_raw = decisions_path.read_bytes()
            old = _read_json(decisions_path)
            if canonical_bytes(prior_input) != prior_input_raw or canonical_bytes(old) != prior_decisions_raw:
                return None
            prior_failures = None
            if failures_path.exists():
                prior_failures_raw = failures_path.read_bytes()
                prior_failures = _read_json(failures_path)
                if canonical_bytes(prior_failures) != prior_failures_raw:
                    return None
        except (WorkerError, OSError, ArtifactError):
            return None
        if not isinstance(prior_input, Mapping) or not isinstance(old, Mapping):
            return None
        if set(prior_input) != _INPUT_KEYS or prior_input.get("schema_version") != "bidops.screening-input.v1":
            return None
        if set(old) != _DECISIONS_KEYS or old.get("schema_version") != "bidops.decisions.v3":
            return None
        if prior_input.get("execution_id") != old.get("execution_id") or prior_input.get("run_id") != old.get("run_id"):
            return None
        if prior_input.get("generated_at") != old.get("generated_at"):
            return None
        if not isinstance(prior_input.get("notices"), list) or prior_input.get("candidate_count") != len(prior_input["notices"]):
            return None
        if not isinstance(old.get("judgments"), list):
            return None
        prior_by_id: dict[str, Mapping[str, Any]] = {}
        for item in prior_input["notices"]:
            if not isinstance(item, Mapping) or set(item) != set(_notice_input_keys()):
                return None
            try:
                _notice_common({key: item[key] for key in _notice_input_keys() if key not in {"judgment_mode", "carry_over_from", "rejudge_reason"}})
            except ScreeningCreationError:
                return None
            notice_id = item.get("notice_id")
            if not isinstance(notice_id, str) or notice_id in prior_by_id:
                return None
            prior_by_id[notice_id] = item
        prior_judgments: dict[str, Mapping[str, Any]] = {}
        for item in old["judgments"]:
            if not isinstance(item, Mapping) or set(item) != _JUDGMENT_KEYS:
                return None
            notice_id = item.get("notice_id")
            if not isinstance(notice_id, str) or notice_id in prior_judgments or notice_id not in prior_by_id:
                return None
            prior_judgments[notice_id] = item
        failure_ids: set[str] = set()
        if prior_failures is not None:
            failure_keys = {"schema_version", "execution_id", "run_id", "generated_at", "failure_count", "failures"}
            item_keys = {"notice_id", "failed_stage", "failure_type", "last_attempt_at", "retry_count", "status", "failure_context", "trace_id", "span_id", "error_summary"}
            if not isinstance(prior_failures, Mapping) or set(prior_failures) != failure_keys or prior_failures.get("schema_version") != "bidops.screening-failures.v1" or prior_failures.get("execution_id") != prior_input.get("execution_id") or prior_failures.get("run_id") != prior_input.get("run_id") or prior_failures.get("generated_at") != prior_input.get("generated_at"):
                return None
            values = prior_failures.get("failures")
            if not isinstance(values, list) or prior_failures.get("failure_count") != len(values):
                return None
            for failure in values:
                if not isinstance(failure, Mapping) or set(failure) != item_keys or failure.get("notice_id") not in prior_by_id or failure.get("notice_id") in failure_ids:
                    return None
                failure_ids.add(failure["notice_id"])
        if set(prior_judgments) & failure_ids or set(prior_judgments) | failure_ids != set(prior_by_id):
            return None
        for key in ("policy_version", "prompt_version", "company_profile_version", "company_profile_digest"):
            if prior_input.get(key) != old.get(key):
                return None
        prior_run_id = old.get("run_id")
        if not isinstance(prior_run_id, str) or not prior_run_id:
            return None
        # A published replacement keeps the frozen source run_id in its
        # copied input.  Follow-up provenance is accepted only when the
        # explicit replacement marker points back to that frozen source.
        if prior_run_id != row.source_run_id:
            provenance_path = source_dir / "screening-replacement-provenance.json"
            try:
                provenance = _read_json(provenance_path)
                if set(provenance) != {"schema_version", "source_run_id", "execution_id", "recorded_at"}:
                    return None
                if provenance.get("schema_version") != "bidops.screening-replacement.v1" or provenance.get("source_run_id") != prior_run_id or provenance.get("execution_id") != prior_input.get("execution_id"):
                    return None
            except WorkerError:
                return None
        current_id = notice.get("notice_id")
        prior_notice = prior_by_id.get(current_id)
        judgment = prior_judgments.get(current_id)
        if prior_notice is None or judgment is None:
            return None
        if prior_notice.get("lifecycle") != notice.get("lifecycle"):
            return None
        if judgment.get("judged_in_run") != notice.get("carry_over_from"):
            return None
        if not isinstance(judgment.get("judged_in_run"), str) or not judgment["judged_in_run"]:
            return None
        if judgment.get("judgment_mode") not in {"신규", "재판정", "승계"}:
            return None
        if judgment.get("judgment_mode") == "승계":
            if judgment.get("carried_over") is not True:
                return None
        elif judgment.get("carried_over") is not False or judgment.get("recorded_in_run") != judgment.get("judged_in_run"):
            return None
        if judgment.get("judgment_mode") == "신규" and judgment.get("rejudge_reason") is not None:
            return None
        if judgment.get("judgment_mode") == "재판정" and judgment.get("rejudge_reason") not in {"정정", "재공고", "본공고 전환", "담당자 요청"}:
            return None
        if judgment.get("judgment_mode") == "승계" and judgment.get("rejudge_reason") is not None:
            return None
        # New/rejudged source judgments must retain the source decisions
        # identity; a carried chain may retain its original model binding.
        if judgment.get("judgment_mode") in {"신규", "재판정"}:
            for key in ("model_name", "model_digest", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest"):
                if judgment.get(key) != old.get(key):
                    return None
        try:
            base = {key: judgment[key] for key in ("notice_id", "grade", "readiness", "primary_focus", "exclusion_category", "summary", "perspectives", "matched_performances", "counterarguments", "counterargument_resolutions", "verification_items", "next_action")}
            validate_judgment(base, notice=prior_notice)
            axes = add_two_axis_metadata(base)
            if judgment.get("two_axis_mixing_flag") != axes["two_axis_mixing_flag"] or judgment.get("two_axis_mixing_label") != axes["two_axis_mixing_label"]:
                return None
        except Exception:
            return None
        judgment = dict(judgment)
        judgment["judgment_mode"] = "승계"
        judgment["recorded_in_run"] = row.source_run_id
        judgment["carried_over"] = True
        return judgment

    def _validate_v3_result(self, row: ScreeningExecution, input_value: Mapping[str, Any], value: Any, failures: Any | None) -> None:
        if not isinstance(value, Mapping) or set(value) != _RESULT_KEYS or value.get("schema_version") != "bidops.screening.v3":
            raise WorkerError("execution_failure")
        for key in ("execution_id", "generated_at", "source_window", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest"):
            if value.get(key) != input_value.get(key):
                raise WorkerError("execution_failure")
        for key in ("model_name", "model_digest"):
            if value.get(key) != getattr(row, key):
                raise WorkerError("execution_failure")
        if not isinstance(value.get("screening_basis"), str) or not value["screening_basis"].strip():
            raise WorkerError("execution_failure")
        notices = input_value.get("notices")
        if not isinstance(notices, list) or value.get("candidate_count") != len(notices):
            raise WorkerError("execution_failure")
        input_ids = {item.get("notice_id") for item in notices if isinstance(item, Mapping)}
        if len(input_ids) != len(notices):
            raise WorkerError("execution_failure")
        results = value.get("results")
        if not isinstance(results, list) or value.get("result_count") != len(results):
            raise WorkerError("execution_failure")
        result_ids: set[str] = set()
        for result in results:
            if not isinstance(result, Mapping) or set(result) != _RESULT_ITEM_KEYS:
                raise WorkerError("execution_failure")
            notice_value = result.get("notice")
            judgment = result.get("judgment")
            common_keys = set(_notice_input_keys()) - {"judgment_mode", "carry_over_from", "rejudge_reason"}
            if not isinstance(notice_value, Mapping) or set(notice_value) != common_keys:
                raise WorkerError("execution_failure")
            try:
                common = _notice_common(notice_value)
            except ScreeningCreationError:
                raise WorkerError("execution_failure") from None
            notice_id = common.get("notice_id")
            if notice_id not in input_ids or notice_id in result_ids or not isinstance(judgment, Mapping) or set(judgment) != (_JUDGMENT_KEYS - {"notice_id"}):
                raise WorkerError("execution_failure")
            result_ids.add(notice_id)
            source_notice = next((candidate for candidate in notices if candidate.get("notice_id") == notice_id), None)
            if source_notice is None:
                raise WorkerError("execution_failure")
            expected_common = {key: source_notice[key] for key in common_keys}
            if dict(common) != expected_common:
                raise WorkerError("execution_failure")
            try:
                judgment = {"notice_id": notice_id, **judgment}
                base = {key: judgment[key] for key in ("notice_id", "grade", "readiness", "primary_focus", "exclusion_category", "summary", "perspectives", "matched_performances", "counterarguments", "counterargument_resolutions", "verification_items", "next_action")}
                validate_judgment(base, notice=source_notice)
            except Exception:
                raise WorkerError("execution_failure") from None
            mode = source_notice.get("judgment_mode")
            if judgment.get("judgment_mode") != mode or judgment.get("carried_over") is not (mode == "승계"):
                raise WorkerError("execution_failure")
            expected_judged = source_notice.get("carry_over_from") if mode == "승계" else row.source_run_id
            if judgment.get("judged_in_run") != expected_judged or judgment.get("recorded_in_run") != row.source_run_id:
                raise WorkerError("execution_failure")
            if mode != "승계":
                for key in ("model_name", "model_digest", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest"):
                    if judgment.get(key) != getattr(row, key):
                        raise WorkerError("execution_failure")
            axes = add_two_axis_metadata(base)
            if judgment.get("two_axis_mixing_flag") != axes["two_axis_mixing_flag"] or judgment.get("two_axis_mixing_label") != axes["two_axis_mixing_label"]:
                raise WorkerError("execution_failure")
        failure_values: list[Any] = []
        if failures is not None:
            failure_keys = {"schema_version", "execution_id", "run_id", "generated_at", "failure_count", "failures"}
            item_keys = {"notice_id", "failed_stage", "failure_type", "last_attempt_at", "retry_count", "status", "failure_context", "trace_id", "span_id", "error_summary"}
            if not isinstance(failures, Mapping) or set(failures) != failure_keys or failures.get("schema_version") != "bidops.screening-failures.v1" or failures.get("execution_id") != row.execution_id or failures.get("run_id") != row.source_run_id or failures.get("generated_at") != input_value.get("generated_at"):
                raise WorkerError("execution_failure")
            failure_values = failures.get("failures")
            if not isinstance(failure_values, list) or failures.get("failure_count") != len(failure_values):
                raise WorkerError("execution_failure")
            seen: set[str] = set()
            for failure in failure_values:
                if not isinstance(failure, Mapping) or set(failure) != item_keys:
                    raise WorkerError("execution_failure")
                notice_id = failure.get("notice_id")
                if notice_id not in input_ids or notice_id in result_ids or notice_id in seen or failure.get("failed_stage") not in _SAFE_FAILURE_STAGES or failure.get("failure_type") not in {"timeout", "truncated_output", "schema_violation", "evidence_missing", "counterargument_repetition"} or failure.get("status") != "사람 검토 대기" or not isinstance(failure.get("retry_count"), int) or isinstance(failure.get("retry_count"), bool) or failure.get("retry_count") < 0 or not isinstance(failure.get("last_attempt_at"), str) or not isinstance(failure.get("error_summary"), str) or not failure.get("error_summary").strip():
                    raise WorkerError("execution_failure")
                seen.add(notice_id)
        failure_ids = {failure.get("notice_id") for failure in failure_values if isinstance(failure, Mapping)}
        if result_ids & failure_ids or result_ids | failure_ids != input_ids:
            raise WorkerError("execution_failure")
        if value.get("failure_count") != len(failure_values) or value.get("partial_artifact") is not (bool(failure_values)) or value.get("failure_artifact") != ("screening-failures.json" if failure_values else None):
            raise WorkerError("execution_failure")

    def _merge(self, row: ScreeningExecution, input_value: Mapping[str, Any], store: ArtifactStore, has_failures: bool) -> str:
        root = Path(self.settings.bidops_root)
        input_path = root / row.input_artifact_path
        decisions_path = root / row.artifact_dir / "screening-decisions.json"
        failures_path = root / row.artifact_dir / "screening-failures.json"
        script = root / "skills" / "bidops-screen" / "scripts" / "build_screening_results.py"
        output_path: Path | None = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".screening-results-", suffix=".tmp", dir=str(store.execution_dir(row.execution_id)))
            os.close(fd)
            output_path = Path(temporary)
            output_path.unlink()
            argv = [sys.executable, str(script), str(input_path), str(decisions_path), "--output", str(output_path)]
            if has_failures:
                argv[3:3] = ["--failures", str(failures_path)]
            completed = self._popen(argv, cwd=str(root), shell=False, capture_output=True, text=True, check=False)
            if completed.returncode != 0 or output_path.is_symlink() or not output_path.is_file():
                raise WorkerError("execution_failure")
            raw = output_path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
            if canonical_bytes(value) != raw:
                raise WorkerError("execution_failure")
            failure_value = _read_json(failures_path) if has_failures else None
            self._validate_v3_result(row, input_value, value, failure_value)
            final_path, _ = store.write_bytes(row.execution_id, "screening-results.json", raw)
            return str(root / final_path)
        except WorkerError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, subprocess.SubprocessError, ArtifactError):
            raise WorkerError("execution_failure") from None
        finally:
            if output_path is not None:
                try:
                    if output_path.is_file() or output_path.is_symlink():
                        output_path.unlink()
                except OSError:
                    pass

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
        staging: Path | None = None
        derived_id: str | None = None
        try:
            staging = Path(tempfile.mkdtemp(prefix=f".{source.name}--screen-", dir=str(runs)))
            if staging.is_symlink():
                raise WorkerError("execution_failure")
            shutil.copytree(source, staging, symlinks=False, dirs_exist_ok=True)
            self._assert_no_symlinks(source)
            root = Path(self.settings.bidops_root)
            # The current immutable execution input is authoritative; a source
            # run may contain an older screening-input from another execution.
            self._copy_atomic(root / row.input_artifact_path, staging / "screening-input.json")
            self._copy_atomic(Path(result_path), staging / "screening-results.json")
            execution_dir = Path(self.settings.bidops_root) / row.artifact_dir
            for name in ("screening-decisions.json", "screening-failures.json", "screening-telemetry.jsonl"):
                source_file = execution_dir / name
                if source_file.is_file():
                    self._copy_atomic(source_file, staging / name)
            provenance = {
                "schema_version": "bidops.screening-replacement.v1",
                "source_run_id": row.source_run_id,
                "execution_id": row.execution_id,
                "recorded_at": aware_iso(_aware(self.clock)),
            }
            self._write_atomic(staging / "screening-replacement-provenance.json", canonical_bytes(provenance))
            self._assert_no_symlinks(staging)
            staged_input = _read_json(staging / "screening-input.json")
            staged_results = _read_json(staging / "screening-results.json")
            staged_failures = _read_json(staging / "screening-failures.json") if (staging / "screening-failures.json").is_file() else None
            self._validate_v3_result(row, staged_input, staged_results, staged_failures)
            self._fsync_tree(staging)
            if target.exists() or target.is_symlink():
                raise WorkerError("execution_failure")
            os.replace(staging, target)
            staging = None
            self._fsync_directory(runs)
            with self._session() as session:
                # The loader is the sole owner of deterministic Run.id and
                # Notice/Judgment/count ingestion. It commits its own valid
                # transaction before we bind the execution FK.
                loaded = ingest_run(target, session)
                derived_id = loaded.run_id
                run = session.scalar(select(Run).where(Run.id == derived_id))
                if run is None or loaded.run_id != derived_id:
                    raise WorkerError("execution_failure")
                input_ids = {item.get("notice_id") for item in staged_input.get("notices", []) if isinstance(item, Mapping)}
                result_count = int(staged_results.get("result_count", -1))
                failed_ids = {item.get("notice_id") for item in staged_failures.get("failures", []) if isinstance(item, Mapping)} if isinstance(staged_failures, Mapping) else set()
                actual_notices = session.scalars(select(Notice).where(Notice.run_id == derived_id)).all()
                actual_notice_ids = {item.notice_key for item in actual_notices}
                actual_judgments = session.scalars(select(Judgment).join(Notice, Judgment.notice_pk == Notice.id).where(Notice.run_id == derived_id)).all()
                if actual_notice_ids != input_ids or len(actual_judgments) != result_count or any(item.notice_key in failed_ids and item.judgment is not None for item in actual_notices):
                    raise WorkerError("execution_failure")
                if run.counts_json is None or not isinstance(run.counts_json, dict) or run.counts_json.get("notices") != len(input_ids) or run.counts_json.get("judgments") != result_count:
                    raise WorkerError("execution_failure")
                run.counts_json = {**run.counts_json, "replacement_of": row.source_run_id}
                session.commit()
            with self._session() as session:
                bound = session.execute(update(ScreeningExecution).where(ScreeningExecution.execution_id == row.execution_id, ScreeningExecution.published_run_id.is_(None)).values(published_run_id=derived_id))
                if bound.rowcount != 1:
                    raise WorkerError("execution_failure")
                session.commit()
        except WorkerError as exc:
            self._cleanup_publication(target, staging, derived_id)
            raise exc
        except Exception:
            self._cleanup_publication(target, staging, derived_id)
            raise WorkerError("execution_failure") from None

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        try:
            fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            raise WorkerError("execution_failure") from None

    @classmethod
    def _fsync_tree(cls, root: Path) -> None:
        try:
            for entry in os.scandir(root):
                path = Path(entry.path)
                if entry.is_symlink():
                    raise WorkerError("execution_failure")
                if entry.is_dir(follow_symlinks=False):
                    cls._fsync_tree(path)
                else:
                    with path.open("rb") as handle:
                        os.fsync(handle.fileno())
            cls._fsync_directory(root)
        except WorkerError:
            raise
        except OSError:
            raise WorkerError("execution_failure") from None

    @classmethod
    def _write_atomic(cls, destination: Path, raw: bytes) -> None:
        if destination.is_symlink() or not destination.parent.is_dir():
            raise WorkerError("execution_failure")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, prefix=".screening-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            temporary = None
            cls._fsync_directory(destination.parent)
        except WorkerError:
            raise
        except OSError:
            raise WorkerError("execution_failure") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    @classmethod
    def _copy_atomic(cls, source: Path, destination: Path) -> None:
        if source.is_symlink() or not source.is_file():
            raise WorkerError("execution_failure")
        try:
            raw = source.read_bytes()
        except OSError:
            raise WorkerError("execution_failure") from None
        cls._write_atomic(destination, raw)

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

    def _cleanup_publication(self, target: Path | None, staging: Path | None, derived_id: str | None) -> None:
        try:
            with self._session() as session:
                if derived_id:
                    session.execute(update(ScreeningExecution).where(ScreeningExecution.published_run_id == derived_id).values(published_run_id=None))
                    session.execute(delete(Run).where(Run.id == derived_id))
                session.commit()
        except Exception:
            raise WorkerError("execution_failure") from None
        for path in (staging, target):
            if path is None:
                continue
            if path.is_symlink():
                raise WorkerError("execution_failure")
            if path.exists():
                try:
                    shutil.rmtree(path)
                except OSError:
                    raise WorkerError("execution_failure") from None


Worker = ScreeningWorker


__all__ = ["ScreeningWorker", "Worker", "WorkerError"]
