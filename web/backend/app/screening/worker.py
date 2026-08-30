"""FIFO screening worker using only the T4 pure model-call boundary."""

from __future__ import annotations

from datetime import date, datetime, timezone
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import stat
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
from ..models import CompanyProfileSnapshot, Judgment, Notice, NoticeObservation, Run, ScreeningAttempt, ScreeningExecution, ScreeningPolicy
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
from .generation_config import GenerationConfigError, config_from_value, validate_digest
from .execution_store import ScreeningExecutionStore
from .ollama import OllamaCallError, OllamaClient
from .orchestrator import ScreeningCreationError, _notice_common
from .policy import canonical_policy_bytes
from .profile_snapshot import read_profile_snapshot
from .prompts import assemble_counterargument_prompt, assemble_perspective_prompt, assemble_synthesis_prompt, schema_for_stage
from .queue import INTERRUPTED, RUNNING, ScreeningQueueError


class WorkerError(RuntimeError):
    """A safe worker failure category."""


@dataclass
class PublicationHandle:
    """Descriptor-backed identity retained through terminal reconciliation."""

    runs_fd: int
    target_name: str
    closed: bool = False

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            os.close(self.runs_fd)


_INPUT_KEYS = {
    "schema_version", "execution_id", "run_id", "generated_at", "source_window",
    "policy_version", "prompt_version", "company_profile_version", "company_profile_digest",
    "candidate_count", "notices", "generation_config", "generation_config_digest",
}
_DECISIONS_KEYS = {
    "schema_version", "execution_id", "run_id", "generated_at", "screening_basis",
    "model_name", "model_digest", "prompt_version", "policy_version",
    "company_profile_version", "company_profile_digest", "generation_config", "generation_config_digest", "judgments",
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
    "generation_config", "generation_config_digest", "failure_count", "partial_artifact", "failure_artifact", "results",
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


def _aware_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        point = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return point.tzinfo is not None and point.utcoffset() is not None


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


def _open_run_fds(settings: Settings, run_id: str) -> tuple[int, int, int, int]:
    """Open project/data/runs/source as one no-follow descriptor chain.

    The path checks in :func:`_safe_run_dir` are useful for validating the
    persisted run id, but are deliberately not used as authority for the
    subsequent copy.  Every component is reopened relative to the descriptor
    held for its parent, so a ``data``/``runs``/source rename or symlink swap
    cannot redirect a publication to another tree.
    """
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd: int | None = None
    data_fd: int | None = None
    runs_fd: int | None = None
    source_fd: int | None = None
    opened = False
    try:
        root_fd = os.open(Path(settings.bidops_root), flags)
        data_fd = os.open("data", flags, dir_fd=root_fd)
        runs_fd = os.open("runs", flags, dir_fd=data_fd)
        parsed = parse_run_id(run_id)
        name = parsed[0] if parsed else run_id.split("--", 1)[0]
        source_fd = os.open(name, flags, dir_fd=runs_fd)
        if not all(stat.S_ISDIR(os.fstat(fd).st_mode) for fd in (root_fd, data_fd, runs_fd, source_fd)):
            raise WorkerError("input_error")
        opened = True
        return root_fd, data_fd, runs_fd, source_fd
    except WorkerError:
        raise
    except OSError:
        raise WorkerError("input_error") from None
    except Exception:
        raise WorkerError("input_error") from None
    finally:
        # Successful callers own the descriptors.  On every failed open,
        # close only the descriptors that were obtained.
        if not opened:
            for fd in (source_fd, runs_fd, data_fd, root_fd):
                if fd is not None:
                    os.close(fd)


def _open_execution_fd(settings: Settings, execution_id: str) -> tuple[int, int, int, int]:
    """Open the immutable execution artifact directory by descriptor chain."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd: int | None = None
    data_fd: int | None = None
    base_fd: int | None = None
    execution_fd: int | None = None
    opened = False
    try:
        root_fd = os.open(Path(settings.bidops_root), flags)
        data_fd = os.open("data", flags, dir_fd=root_fd)
        base_fd = os.open("screening-executions", flags, dir_fd=data_fd)
        execution_fd = os.open(execution_id, flags, dir_fd=base_fd)
        if not all(stat.S_ISDIR(os.fstat(fd).st_mode) for fd in (root_fd, data_fd, base_fd, execution_fd)):
            raise WorkerError("execution_failure")
        opened = True
        return root_fd, data_fd, base_fd, execution_fd
    except WorkerError:
        raise
    except OSError:
        raise WorkerError("execution_failure") from None
    finally:
        if not opened:
            for fd in (execution_fd, base_fd, data_fd, root_fd):
                if fd is not None:
                    os.close(fd)


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
        try:
            generation_config = config_from_value(input_value["generation_config"])
            validate_digest(generation_config, input_value["generation_config_digest"])
            if row.generation_config_digest != input_value["generation_config_digest"] or row.generation_config_json != generation_config.canonical_value():
                raise WorkerError("generation_config_mismatch")
        except (GenerationConfigError, AttributeError):
            raise WorkerError("generation_config_mismatch") from None
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
                db_notice = session.scalar(select(Notice).where(Notice.notice_key == notice.get("notice_id")))
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
        if identity.model_name != MODEL_NAME or row.model_name != MODEL_NAME or identity.digest != row.model_digest:
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
                result, failed = self._run_notice(row, input_value, notice, policy_body, _profile_sections(profile_raw), store, generation_config=generation_config)
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
        published: tuple[str, Path, PublicationHandle] | None = None
        if row.scope == "full_run":
            if not decisions:
                self.store.finish_failure(row.execution_id, completed_count=completed, failure_count=len(failures), candidate_count=len(notices), error_summary="execution_failure", now=_aware(self.clock))
                return
            result_path = self._merge(row, input_value, store, bool(failures))
            published = self._publish(row, input_value, store, result_path)
        if completed == 0:
            status = "실패"
        elif failures and row.scope in {"full_run", "quality_sample"}:
            status = "부분 성공"
        else:
            status = "실패" if failures else "성공"
        if published is not None:
            try:
                self.store.finish(
                    row.execution_id, status=status, completed_count=completed,
                    failure_count=len(failures), candidate_count=len(notices),
                    published_run_id=published[0], now=_aware(self.clock),
                    error_summary="execution_failure" if failures else None,
                )
                published[2].close()
            except Exception:
                # A finish call may have committed before its connection
                # failed.  Only retain the derived directory when a fresh read
                # proves that the terminal FK binding is durable.
                for attempt in range(3):
                    try:
                        fresh = self._get_execution(row.execution_id)
                    except Exception:
                        fresh = None
                    if fresh is not None and fresh.status in {"성공", "부분 성공"} and fresh.published_run_id == published[0]:
                        published[2].close()
                        return
                    if attempt < 2:
                        self.sleep(0.01)
                # The binding was not proven durable.  Remove both sides of
                # the publication using bounded reconciliation; a cleanup
                # error remains visible to the caller rather than being
                # mistaken for a successful publication.
                try:
                    self._cleanup_publication(
                        published[1], None, published[0],
                        runs_fd=published[2].runs_fd, target_name=published[2].target_name,
                    )
                finally:
                    published[2].close()
                raise WorkerError("execution_failure") from None
        else:
            self.store.finish(row.execution_id, status=status, completed_count=completed, failure_count=len(failures), candidate_count=len(notices), now=_aware(self.clock), error_summary="execution_failure" if failures else None)

    def _verify_binding(self, row: ScreeningExecution, value: Any, raw: bytes) -> None:
        expected_keys = {"schema_version", "execution_id", "run_id", "generated_at", "source_window", "policy_version", "prompt_version", "company_profile_version", "company_profile_digest", "candidate_count", "notices", "generation_config", "generation_config_digest"}
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
        try:
            config = config_from_value(value.get("generation_config"))
            digest = validate_digest(config, value.get("generation_config_digest"))
            if row.generation_config_digest != digest or row.generation_config_json != config.canonical_value():
                raise WorkerError("generation_config_mismatch")
        except (GenerationConfigError, AttributeError):
            raise WorkerError("generation_config_mismatch") from None
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
            if row.scope == "quality_sample" and (
                mode != "신규"
                or notice["carry_over_from"] is not None
                or notice["rejudge_reason"] is not None
            ):
                raise WorkerError("input_error")
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
            "company_profile_digest": row.company_profile_digest,
            "generation_config": input_value["generation_config"], "generation_config_digest": input_value["generation_config_digest"],
            "judgments": judgments,
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
                generation_config_digest=metadata.generation_config_digest, num_ctx=metadata.num_ctx, num_predict=metadata.num_predict,
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
            "generation_config_digest": metadata.generation_config_digest or row.generation_config_digest,
            "num_ctx": metadata.num_ctx,
            "num_predict": metadata.num_predict,
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

    def _run_notice(self, row: ScreeningExecution, input_value: Mapping[str, Any], notice: dict[str, Any], policy: Mapping[str, Any], profile: Mapping[str, Any], store: ArtifactStore, *, generation_config: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
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
                result = self.ollama.generate(prompt.user_message, schema_for_stage(name), execution_id=row.execution_id, notice_id=notice["notice_id"], stage=name, trace_id=trace, validator=lambda value, expected=name: validate_perspective(value, expected_name=expected), attempt_callback=record_failure_attempt, generation_config=generation_config)
                self._record_attempt(row, result.metadata, store, result.value)
                perspectives.append(result.value)
                if self.store.should_stop(row.execution_id):
                    return None, None
            if self.store.should_stop(row.execution_id):
                return None, None
            self.store.update_progress(row.execution_id, current_stage="counterargument")
            counter_prompt = assemble_counterargument_prompt(policy, notice, perspectives)
            counter = self.ollama.generate(counter_prompt.user_message, schema_for_stage("counterargument.v1"), execution_id=row.execution_id, notice_id=notice["notice_id"], stage="counterargument", trace_id=trace, validator=validate_counterargument, attempt_callback=record_failure_attempt, generation_config=generation_config)
            self._record_attempt(row, counter.metadata, store, counter.value)
            if self.store.should_stop(row.execution_id):
                return None, None
            self.store.update_progress(row.execution_id, current_stage="synthesis")
            synthesis_prompt = assemble_synthesis_prompt(policy, notice, perspectives, counter.value)
            synthesis = self.ollama.generate(synthesis_prompt.user_message, schema_for_stage("judgment.v3"), execution_id=row.execution_id, notice_id=notice["notice_id"], stage="synthesis", trace_id=trace, validator=lambda value: validate_judgment(value, notice=notice), attempt_callback=record_failure_attempt, generation_config=generation_config)
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
        try:
            prior_generation = config_from_value(prior_input.get("generation_config"))
            validate_digest(prior_generation, prior_input.get("generation_config_digest"))
            old_generation = config_from_value(old.get("generation_config"))
            validate_digest(old_generation, old.get("generation_config_digest"))
        except (GenerationConfigError, AttributeError):
            return None
        if prior_input.get("generation_config_digest") != old.get("generation_config_digest") or prior_input.get("generation_config_digest") != input_value.get("generation_config_digest"):
            return None
        if prior_input.get("generated_at") != old.get("generated_at"):
            return None
        if not _aware_text(prior_input.get("generated_at")) or not _aware_text(old.get("generated_at")):
            return None
        window = prior_input.get("source_window")
        if not isinstance(window, Mapping) or set(window) != {"from", "to", "timezone"} or window.get("timezone") != "Asia/Seoul":
            return None
        try:
            if not isinstance(window.get("from"), str) or not isinstance(window.get("to"), str) or date.fromisoformat(window["from"]) > date.fromisoformat(window["to"]):
                return None
        except ValueError:
            return None
        if any(
            not isinstance(prior_input.get(key), str) or not prior_input[key].strip()
            for key in ("policy_version", "prompt_version", "company_profile_version")
        ):
            return None
        profile_digest = prior_input.get("company_profile_digest")
        if not isinstance(profile_digest, str) or len(profile_digest) != 64 or any(character not in "0123456789abcdef" for character in profile_digest) or prior_input.get("company_profile_version") != f"company-profile.sha256:{profile_digest}":
            return None
        if not isinstance(prior_input.get("notices"), list) or type(prior_input.get("candidate_count")) is not int or prior_input["candidate_count"] < 0 or prior_input.get("candidate_count") != len(prior_input["notices"]):
            return None
        if not isinstance(old.get("judgments"), list):
            return None
        if any(
            not isinstance(old.get(key), str) or not old[key].strip()
            for key in ("screening_basis", "model_name", "model_digest", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest")
        ):
            return None
        if old["model_name"] != MODEL_NAME or len(old["model_digest"]) != 64 or any(character not in "0123456789abcdef" for character in old["model_digest"]):
            return None
        if len(old["company_profile_digest"]) != 64 or any(character not in "0123456789abcdef" for character in old["company_profile_digest"]) or old["company_profile_version"] != f"company-profile.sha256:{old['company_profile_digest']}":
            return None
        if old.get("prompt_version") != prior_input.get("prompt_version") or old.get("policy_version") != prior_input.get("policy_version") or old.get("company_profile_version") != prior_input.get("company_profile_version") or old.get("company_profile_digest") != prior_input.get("company_profile_digest"):
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
            if not isinstance(values, list) or type(prior_failures.get("failure_count")) is not int or prior_failures["failure_count"] < 0 or prior_failures.get("failure_count") != len(values):
                return None
            for failure in values:
                if not isinstance(failure, Mapping) or set(failure) != item_keys or failure.get("notice_id") not in prior_by_id or failure.get("notice_id") in failure_ids or failure.get("failed_stage") not in _SAFE_FAILURE_STAGES or failure.get("failure_type") not in {"timeout", "truncated_output", "schema_violation", "evidence_missing", "counterargument_repetition"} or failure.get("status") != "사람 검토 대기" or not isinstance(failure.get("retry_count"), int) or isinstance(failure.get("retry_count"), bool) or failure.get("retry_count") < 0 or not _aware_text(failure.get("last_attempt_at")) or failure.get("error_summary") not in {"timeout", "truncated_output", "schema_violation", "evidence_missing", "counterargument_repetition", "execution_failure"}:
                    return None
                if failure.get("failure_context") not in {None, "carried_over_validation"} or (failure.get("failed_stage") == "병합·검증" and (failure.get("trace_id") is not None or failure.get("span_id") is not None)) or (failure.get("failure_context") == "carried_over_validation" and (prior_by_id[failure["notice_id"]].get("judgment_mode") != "승계" or failure.get("failed_stage") != "병합·검증")):
                    return None
                if failure.get("failed_stage") in set(PERSPECTIVE_NAMES) | {"반론 검토", "종합 판정"} and (not isinstance(failure.get("trace_id"), str) or not failure["trace_id"].strip() or not isinstance(failure.get("span_id"), str) or not failure["span_id"].strip()):
                    return None
                failure_ids.add(failure["notice_id"])
        if set(prior_judgments) & failure_ids or set(prior_judgments) | failure_ids != set(prior_by_id):
            return None
        for key in ("policy_version", "prompt_version", "company_profile_version", "company_profile_digest"):
            if prior_input.get(key) != old.get(key):
                return None
        for notice_id, prior_judgment in prior_judgments.items():
            prior_notice = prior_by_id[notice_id]
            mode = prior_notice.get("judgment_mode")
            if prior_judgment.get("judgment_mode") != mode or prior_judgment.get("model_name") != MODEL_NAME or not isinstance(prior_judgment.get("prompt_version"), str) or not prior_judgment["prompt_version"].strip() or not isinstance(prior_judgment.get("policy_version"), str) or not prior_judgment["policy_version"].strip() or not isinstance(prior_judgment.get("company_profile_version"), str) or not prior_judgment["company_profile_version"].strip() or not isinstance(prior_judgment.get("model_digest"), str) or len(prior_judgment["model_digest"]) != 64 or any(character not in "0123456789abcdef" for character in prior_judgment["model_digest"]) or not isinstance(prior_judgment.get("company_profile_digest"), str) or len(prior_judgment["company_profile_digest"]) != 64 or any(character not in "0123456789abcdef" for character in prior_judgment["company_profile_digest"]) or prior_judgment.get("company_profile_version") != f"company-profile.sha256:{prior_judgment.get('company_profile_digest')}":
                return None
            if mode in {"신규", "재판정"}:
                if any(prior_judgment.get(key) != old.get(key) for key in ("model_name", "model_digest", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest")) or prior_judgment.get("judged_in_run") != old.get("run_id") or prior_judgment.get("recorded_in_run") != old.get("run_id") or prior_judgment.get("carried_over") is not False or prior_judgment.get("rejudge_reason") != prior_notice.get("rejudge_reason") or (mode == "신규" and prior_judgment.get("rejudge_reason") is not None):
                    return None
            elif mode == "승계":
                if prior_judgment.get("judged_in_run") != prior_notice.get("carry_over_from") or prior_judgment.get("recorded_in_run") != old.get("run_id") or prior_judgment.get("carried_over") is not True or prior_judgment.get("rejudge_reason") is not None:
                    return None
            else:
                return None
            if prior_judgment.get("rejudge_reason") != prior_notice.get("rejudge_reason"):
                return None
            try:
                base = {key: prior_judgment[key] for key in ("notice_id", "grade", "readiness", "primary_focus", "exclusion_category", "summary", "perspectives", "matched_performances", "counterarguments", "counterargument_resolutions", "verification_items", "next_action")}
                validate_judgment(base, notice=prior_notice)
                axes = add_two_axis_metadata(base)
                if prior_judgment.get("two_axis_mixing_flag") != axes["two_axis_mixing_flag"] or prior_judgment.get("two_axis_mixing_label") != axes["two_axis_mixing_label"]:
                    return None
            except Exception:
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
        try:
            result_config = config_from_value(value.get("generation_config"))
            validate_digest(result_config, value.get("generation_config_digest"))
        except (GenerationConfigError, AttributeError):
            raise WorkerError("execution_failure") from None
        if value.get("generation_config") != input_value.get("generation_config") or value.get("generation_config_digest") != input_value.get("generation_config_digest"):
            raise WorkerError("execution_failure")
        for key in ("model_name", "model_digest"):
            if value.get(key) != getattr(row, key):
                raise WorkerError("execution_failure")
        if value.get("model_name") != MODEL_NAME:
            raise WorkerError("execution_failure")
        if not isinstance(value.get("screening_basis"), str) or not value["screening_basis"].strip():
            raise WorkerError("execution_failure")
        notices = input_value.get("notices")
        count_fields = ("candidate_count", "result_count", "failure_count")
        if any(type(value.get(key)) is not int or value[key] < 0 for key in count_fields):
            raise WorkerError("execution_failure")
        if type(value.get("partial_artifact")) is not bool:
            raise WorkerError("execution_failure")
        if not _aware_text(value.get("generated_at")):
            raise WorkerError("execution_failure")
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
            if judgment.get("rejudge_reason") != source_notice.get("rejudge_reason"):
                raise WorkerError("execution_failure")
            if mode in {"신규", "승계"} and judgment.get("rejudge_reason") is not None:
                raise WorkerError("execution_failure")
            if mode == "재판정" and judgment.get("rejudge_reason") not in {"정정", "재공고", "본공고 전환", "담당자 요청"}:
                raise WorkerError("execution_failure")
            if judgment.get("model_name") != MODEL_NAME or not isinstance(judgment.get("prompt_version"), str) or not judgment["prompt_version"].strip() or not isinstance(judgment.get("policy_version"), str) or not judgment["policy_version"].strip() or not isinstance(judgment.get("company_profile_version"), str) or not judgment["company_profile_version"].strip() or not isinstance(judgment.get("model_digest"), str) or len(judgment["model_digest"]) != 64 or any(character not in "0123456789abcdef" for character in judgment["model_digest"]) or not isinstance(judgment.get("company_profile_digest"), str) or len(judgment["company_profile_digest"]) != 64 or any(character not in "0123456789abcdef" for character in judgment["company_profile_digest"]) or judgment.get("company_profile_version") != f"company-profile.sha256:{judgment.get('company_profile_digest')}":
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
            if not isinstance(failure_values, list) or type(failures.get("failure_count")) is not int or failures["failure_count"] < 0 or failures.get("failure_count") != len(failure_values):
                raise WorkerError("execution_failure")
            seen: set[str] = set()
            for failure in failure_values:
                if not isinstance(failure, Mapping) or set(failure) != item_keys:
                    raise WorkerError("execution_failure")
                notice_id = failure.get("notice_id")
                if notice_id not in input_ids or notice_id in result_ids or notice_id in seen or failure.get("failed_stage") not in _SAFE_FAILURE_STAGES or failure.get("failure_type") not in {"timeout", "truncated_output", "schema_violation", "evidence_missing", "counterargument_repetition"} or failure.get("status") != "사람 검토 대기" or not isinstance(failure.get("retry_count"), int) or isinstance(failure.get("retry_count"), bool) or failure.get("retry_count") < 0 or not _aware_text(failure.get("last_attempt_at")) or failure.get("error_summary") not in {"timeout", "truncated_output", "schema_violation", "evidence_missing", "counterargument_repetition", "execution_failure"}:
                    raise WorkerError("execution_failure")
                if failure.get("failure_context") not in {None, "carried_over_validation"}:
                    raise WorkerError("execution_failure")
                if failure.get("failed_stage") == "병합·검증" and (failure.get("trace_id") is not None or failure.get("span_id") is not None):
                    raise WorkerError("execution_failure")
                source_notice = next((candidate for candidate in notices if candidate.get("notice_id") == notice_id), None)
                if source_notice is None:
                    raise WorkerError("execution_failure")
                if source_notice.get("judgment_mode") == "승계":
                    if failure.get("failure_context") != "carried_over_validation" or failure.get("failed_stage") != "병합·검증":
                        raise WorkerError("execution_failure")
                elif failure.get("failure_context") is not None:
                    raise WorkerError("execution_failure")
                if failure.get("failure_context") == "carried_over_validation" and source_notice.get("judgment_mode") != "승계":
                    raise WorkerError("execution_failure")
                if failure.get("failed_stage") in set(PERSPECTIVE_NAMES) | {"반론 검토", "종합 판정"} and (not isinstance(failure.get("trace_id"), str) or not failure["trace_id"].strip() or not isinstance(failure.get("span_id"), str) or not failure["span_id"].strip()):
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

    def _publish(self, row: ScreeningExecution, input_value: Mapping[str, Any], store: ArtifactStore, result_path: str) -> tuple[str, Path, PublicationHandle]:
        source = _safe_run_dir(self.settings, row.source_run_id)
        runs = source.parent
        # Validate the injected clock before opening any publication
        # descriptors.  An invalid/naive clock must not strand the fd chain.
        stamp = _aware(self.clock).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        root_fd, data_fd, runs_fd, source_fd = _open_run_fds(self.settings, row.source_run_id)
        target: Path | None = None
        target_name: str | None = None
        for _ in range(20):
            candidate_name = f"{source.name}--screen-{stamp}-{uuid4().hex[:8]}"
            try:
                os.stat(candidate_name, dir_fd=runs_fd, follow_symlinks=False)
            except FileNotFoundError:
                target_name = candidate_name
                target = runs / candidate_name
                break
            except OSError:
                continue
        if target is None:
            for fd in (source_fd, runs_fd, data_fd, root_fd):
                os.close(fd)
            raise WorkerError("execution_failure")
        staging: Path | None = None
        staging_name: str | None = None
        staging_fd: int | None = None
        derived_id: str | None = None
        transferred_runs_fd = False
        try:
            for _ in range(20):
                candidate_staging_name = f".{source.name}--screen-{uuid4().hex}"
                try:
                    os.mkdir(candidate_staging_name, 0o700, dir_fd=runs_fd)
                except FileExistsError:
                    continue
                staging_name = candidate_staging_name
                staging = runs / candidate_staging_name
                break
            if staging is None:
                raise WorkerError("execution_failure")
            staging_fd = os.open(
                staging_name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=runs_fd,
            )
            self._copy_tree_fd(source_fd, staging_fd)
            os.fsync(staging_fd)
            # The source run is copied as provenance, but these names are
            # owned by the current screening execution.  Remove every stale
            # copy before installing the immutable current artifacts.  In
            # particular, a previous partial execution must not leak its
            # failure/telemetry files into a later successful replacement.
            for name in (
                "screening-input.json", "screening-decisions.json", "screening-results.json",
                "screening-failures.json", "screening-telemetry.jsonl",
                "screening-replacement-provenance.json", "responses",
            ):
                self._remove_owned_at(staging_fd, name)
            result_name = Path(result_path).name
            if result_name != "screening-results.json":
                raise WorkerError("execution_failure")
            execution_fds = _open_execution_fd(self.settings, row.execution_id)
            execution_fd = execution_fds[3]
            try:
                self._copy_atomic_at(execution_fd, "screening-input.json", staging_fd, "screening-input.json")
                self._copy_atomic_at(execution_fd, result_name, staging_fd, "screening-results.json")
                for name in ("screening-decisions.json", "screening-failures.json", "screening-telemetry.jsonl"):
                    try:
                        info = os.stat(name, dir_fd=execution_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    except OSError:
                        raise WorkerError("execution_failure") from None
                    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                        raise WorkerError("execution_failure")
                    self._copy_atomic_at(execution_fd, name, staging_fd, name)
            finally:
                for fd in reversed(execution_fds):
                    os.close(fd)
            # The current immutable execution input is authoritative; a source
            # run may contain an older screening-input from another execution.
            provenance = {
                "schema_version": "bidops.screening-replacement.v1",
                "source_run_id": row.source_run_id,
                "execution_id": row.execution_id,
                "recorded_at": aware_iso(_aware(self.clock)),
            }
            self._write_atomic_at(staging_fd, "screening-replacement-provenance.json", canonical_bytes(provenance))
            self._fsync_tree_fd(staging_fd)
            staged_input = json.loads(self._read_regular_at(staging_fd, "screening-input.json").decode("utf-8"))
            staged_results = json.loads(self._read_regular_at(staging_fd, "screening-results.json").decode("utf-8"))
            try:
                failure_info = os.stat("screening-failures.json", dir_fd=staging_fd, follow_symlinks=False)
            except FileNotFoundError:
                staged_failures = None
            except OSError:
                raise WorkerError("execution_failure") from None
            else:
                if stat.S_ISLNK(failure_info.st_mode) or not stat.S_ISREG(failure_info.st_mode):
                    raise WorkerError("execution_failure")
                staged_failures = json.loads(self._read_regular_at(staging_fd, "screening-failures.json").decode("utf-8"))
            for name in ("screening-decisions.json", "screening-replacement-provenance.json"):
                self._read_regular_at(staging_fd, name)
            try:
                telemetry_info = os.stat("screening-telemetry.jsonl", dir_fd=staging_fd, follow_symlinks=False)
            except FileNotFoundError:
                telemetry_info = None
            except OSError:
                raise WorkerError("execution_failure") from None
            if telemetry_info is not None:
                if stat.S_ISLNK(telemetry_info.st_mode) or not stat.S_ISREG(telemetry_info.st_mode):
                    raise WorkerError("execution_failure")
                self._read_regular_at(staging_fd, "screening-telemetry.jsonl")
            self._validate_v3_result(row, staged_input, staged_results, staged_failures)
            self._fsync_tree_fd(staging_fd)
            try:
                os.stat(target_name, dir_fd=runs_fd, follow_symlinks=False)
                raise WorkerError("execution_failure")
            except FileNotFoundError:
                pass
            os.replace(staging_name, target_name, src_dir_fd=runs_fd, dst_dir_fd=runs_fd)
            staging = None
            os.fsync(runs_fd)
            with self._session() as session:
                # The loader is the sole owner of deterministic Run.id and
                # Notice/Judgment/count ingestion. It commits its own valid
                # transaction before we bind the execution FK.
                loaded = ingest_run(Path(f"/proc/self/fd/{staging_fd}"), session)
                derived_id = loaded.run_id
                run = session.scalar(select(Run).where(Run.id == derived_id))
                if run is None or loaded.run_id != derived_id:
                    raise WorkerError("execution_failure")
                input_ids = {item.get("notice_id") for item in staged_input.get("notices", []) if isinstance(item, Mapping)}
                result_count = int(staged_results.get("result_count", -1))
                failed_ids = {item.get("notice_id") for item in staged_failures.get("failures", []) if isinstance(item, Mapping)} if isinstance(staged_failures, Mapping) else set()
                actual_notices = session.scalars(
                    select(Notice)
                    .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
                    .where(NoticeObservation.run_id == derived_id)
                ).all()
                actual_notice_ids = {item.notice_key for item in actual_notices}
                actual_judgments = session.scalars(
                    select(Judgment)
                    .join(Notice, Judgment.notice_pk == Notice.id)
                    .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
                    .where(NoticeObservation.run_id == derived_id)
                ).all()
                if actual_notice_ids != input_ids or len(actual_judgments) != result_count or any(item.notice_key in failed_ids and item.judgment is not None for item in actual_notices):
                    raise WorkerError("execution_failure")
                if run.counts_json is None or not isinstance(run.counts_json, dict) or run.counts_json.get("notices") != len(input_ids) or run.counts_json.get("judgments") != result_count:
                    raise WorkerError("execution_failure")
                run.counts_json = {**run.counts_json, "replacement_of": row.source_run_id}
                session.commit()
            if derived_id is None:
                raise WorkerError("execution_failure")
            if target_name is None:
                raise WorkerError("execution_failure")
            handle = PublicationHandle(runs_fd, target_name)
            transferred_runs_fd = True
            return derived_id, target, handle
        except WorkerError as exc:
            self._cleanup_publication(target, staging, derived_id, runs_fd=runs_fd, staging_name=staging_name, target_name=target_name)
            raise exc
        except Exception:
            self._cleanup_publication(target, staging, derived_id, runs_fd=runs_fd, staging_name=staging_name, target_name=target_name)
            raise WorkerError("execution_failure") from None
        finally:
            if staging_fd is not None:
                os.close(staging_fd)
            for fd in (source_fd, data_fd, root_fd):
                os.close(fd)
            if not transferred_runs_fd:
                os.close(runs_fd)

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
        parent_fd: int | None = None
        source_fd: int | None = None
        try:
            parent_fd = os.open(source.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
            source_fd = os.open(source.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
            source_stat = os.fstat(source_fd)
            if not stat.S_ISREG(source_stat.st_mode):
                raise WorkerError("execution_failure")
            raw = cls._read_regular_fd(source_fd)
        except WorkerError:
            raise
        except OSError:
            raise WorkerError("execution_failure") from None
        finally:
            if source_fd is not None:
                os.close(source_fd)
            if parent_fd is not None:
                os.close(parent_fd)
        cls._write_atomic(destination, raw)

    @classmethod
    def _read_regular_at(cls, directory_fd: int, name: str) -> bytes:
        source_fd: int | None = None
        try:
            source_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            if not stat.S_ISREG(os.fstat(source_fd).st_mode):
                raise WorkerError("execution_failure")
            return cls._read_regular_fd(source_fd)
        except WorkerError:
            raise
        except OSError:
            raise WorkerError("execution_failure") from None
        finally:
            if source_fd is not None:
                os.close(source_fd)

    @classmethod
    def _write_atomic_at(cls, directory_fd: int, name: str, raw: bytes) -> None:
        temporary_name = f".screening-{uuid4().hex}.tmp"
        temporary_fd: int | None = None
        try:
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            offset = 0
            while offset < len(raw):
                offset += os.write(temporary_fd, raw[offset:])
            os.fsync(temporary_fd)
            os.fchmod(temporary_fd, 0o600)
            os.close(temporary_fd)
            temporary_fd = None
            os.replace(temporary_name, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
        except OSError:
            raise WorkerError("execution_failure") from None
        finally:
            if temporary_fd is not None:
                os.close(temporary_fd)
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                # A rename may have installed the file already.  The caller
                # will surface any real write error; never follow a path here.
                pass

    @classmethod
    def _copy_atomic_at(cls, source_fd: int, source_name: str, destination_fd: int, destination_name: str) -> None:
        raw = cls._read_regular_at(source_fd, source_name)
        cls._write_atomic_at(destination_fd, destination_name, raw)

    @classmethod
    def _remove_owned_at(cls, directory_fd: int, name: str) -> None:
        try:
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        except OSError:
            raise WorkerError("execution_failure") from None
        if stat.S_ISLNK(info.st_mode):
            raise WorkerError("execution_failure")
        if stat.S_ISDIR(info.st_mode):
            child_fd: int | None = None
            try:
                child_fd = os.open(name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
                with os.scandir(child_fd) as entries:
                    for entry in entries:
                        cls._remove_owned_at(child_fd, entry.name)
                os.rmdir(name, dir_fd=directory_fd)
            except WorkerError:
                raise
            except OSError:
                raise WorkerError("execution_failure") from None
            finally:
                if child_fd is not None:
                    os.close(child_fd)
        elif stat.S_ISREG(info.st_mode):
            try:
                os.unlink(name, dir_fd=directory_fd)
            except OSError:
                raise WorkerError("execution_failure") from None
        else:
            raise WorkerError("execution_failure")

    @classmethod
    def _fsync_tree_fd(cls, directory_fd: int) -> None:
        try:
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    info = os.stat(entry.name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        raise WorkerError("execution_failure")
                    if stat.S_ISDIR(info.st_mode):
                        child_fd = os.open(entry.name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
                        try:
                            cls._fsync_tree_fd(child_fd)
                        finally:
                            os.close(child_fd)
                    elif stat.S_ISREG(info.st_mode):
                        child_fd = os.open(entry.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
                        try:
                            os.fsync(child_fd)
                        finally:
                            os.close(child_fd)
                    else:
                        raise WorkerError("execution_failure")
            os.fsync(directory_fd)
        except WorkerError:
            raise
        except OSError:
            raise WorkerError("execution_failure") from None

    @classmethod
    def _copy_tree_nofollow(cls, source: Path, destination: Path) -> None:
        source_fd: int | None = None
        destination_fd: int | None = None
        try:
            source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
            if not stat.S_ISDIR(os.fstat(source_fd).st_mode):
                raise WorkerError("execution_failure")
            if destination.exists() or destination.is_symlink():
                if destination.is_symlink() or not destination.is_dir():
                    raise WorkerError("execution_failure")
            else:
                destination.mkdir(mode=0o700, exist_ok=False)
            os.chmod(destination, 0o700)
            destination_fd = os.open(destination, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
            if not stat.S_ISDIR(os.fstat(destination_fd).st_mode):
                raise WorkerError("execution_failure")
            cls._copy_tree_fd(source_fd, destination_fd)
            os.fsync(destination_fd)
        except WorkerError:
            raise
        except OSError:
            raise WorkerError("execution_failure") from None
        finally:
            if destination_fd is not None:
                os.close(destination_fd)
            if source_fd is not None:
                os.close(source_fd)

    @classmethod
    def _copy_tree_fd(cls, source_fd: int, destination_fd: int) -> None:
        """Copy one already-open directory using openat-style operations.

        No child operation reconstructs a path from the source root.  A
        rename/symlink swap therefore either causes an O_NOFOLLOW failure or
        copies the inode that was opened for this directory entry.
        """
        with os.scandir(source_fd) as entries:
            for entry in entries:
                name = entry.name
                try:
                    info = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
                except OSError:
                    raise WorkerError("execution_failure") from None
                if stat.S_ISLNK(info.st_mode):
                    raise WorkerError("execution_failure")
                if stat.S_ISDIR(info.st_mode):
                    child_source: int | None = None
                    child_destination: int | None = None
                    try:
                        child_source = os.open(
                            name,
                            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                            dir_fd=source_fd,
                        )
                        if not stat.S_ISDIR(os.fstat(child_source).st_mode):
                            raise WorkerError("execution_failure")
                        os.mkdir(name, 0o700, dir_fd=destination_fd)
                        child_destination = os.open(
                            name,
                            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                            dir_fd=destination_fd,
                        )
                        cls._copy_tree_fd(child_source, child_destination)
                        os.fsync(child_destination)
                    except FileExistsError:
                        raise WorkerError("execution_failure") from None
                    finally:
                        if child_destination is not None:
                            os.close(child_destination)
                        if child_source is not None:
                            os.close(child_source)
                elif stat.S_ISREG(info.st_mode):
                    source_child: int | None = None
                    destination_child: int | None = None
                    try:
                        source_child = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=source_fd)
                        if not stat.S_ISREG(os.fstat(source_child).st_mode):
                            raise WorkerError("execution_failure")
                        destination_child = os.open(
                            name,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                            0o600,
                            dir_fd=destination_fd,
                        )
                        cls._stream_fd(source_child, destination_child)
                        os.fchmod(destination_child, 0o600)
                        os.fsync(destination_child)
                    except FileExistsError:
                        raise WorkerError("execution_failure") from None
                    finally:
                        if destination_child is not None:
                            os.close(destination_child)
                        if source_child is not None:
                            os.close(source_child)
                else:
                    raise WorkerError("execution_failure")

    @staticmethod
    def _read_regular_fd(source_fd: int) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    @staticmethod
    def _stream_fd(source_fd: int, destination_fd: int) -> None:
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                return
            offset = 0
            while offset < len(chunk):
                offset += os.write(destination_fd, chunk[offset:])

    @staticmethod
    def _remove_owned_artifact(path: Path) -> None:
        if path.is_symlink():
            raise WorkerError("execution_failure")
        if not path.exists():
            return
        try:
            if path.is_dir():
                # Responses are an execution-owned directory.  Never follow
                # a symlinked child while removing it.
                for entry in os.scandir(path):
                    ScreeningWorker._remove_owned_artifact(Path(entry.path))
                path.rmdir()
            elif path.is_file():
                path.unlink()
            else:
                raise WorkerError("execution_failure")
        except WorkerError:
            raise
        except OSError:
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

    def _cleanup_publication(
        self,
        target: Path | None,
        staging: Path | None,
        derived_id: str | None,
        *,
        runs_fd: int | None = None,
        staging_name: str | None = None,
        target_name: str | None = None,
    ) -> None:
        db_clean = False
        for attempt in range(3):
            try:
                with self._session() as session:
                    if derived_id:
                        session.execute(update(ScreeningExecution).where(ScreeningExecution.published_run_id == derived_id).values(published_run_id=None))
                        session.execute(delete(Run).where(Run.id == derived_id))
                    session.commit()
                db_clean = True
                break
            except Exception:
                if attempt < 2:
                    self.sleep(0.01)
        if not db_clean:
            raise WorkerError("execution_failure") from None
        if runs_fd is not None:
            names = tuple(name for name in (staging_name, target_name) if name is not None)
            removed = False
            for attempt in range(3):
                try:
                    for name in names:
                        self._remove_owned_at(runs_fd, name)
                    removed = True
                    break
                except WorkerError:
                    if attempt == 2:
                        raise
                if attempt < 2:
                    self.sleep(0.01)
            if not removed:
                raise WorkerError("execution_failure")
            return
        for path in (staging, target):
            if path is None:
                continue
            removed = False
            for attempt in range(3):
                try:
                    if path.is_symlink():
                        raise WorkerError("execution_failure")
                    if path.exists():
                        shutil.rmtree(path)
                    removed = not path.exists() and not path.is_symlink()
                    if removed:
                        break
                except WorkerError:
                    if attempt == 2:
                        raise
                except OSError:
                    if attempt == 2:
                        raise WorkerError("execution_failure") from None
                if attempt < 2:
                    self.sleep(0.01)
            if not removed:
                raise WorkerError("execution_failure")


Worker = ScreeningWorker


__all__ = ["ScreeningWorker", "Worker", "WorkerError"]
