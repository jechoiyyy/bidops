"""Screening execution creation and the frozen input boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings
from ..ingest.loader import parse_run_id
from ..models import CompanyProfileSnapshot, Notice, Run, ScreeningPolicy
from .artifacts import ArtifactError, ArtifactStore, aware_iso, sha256_bytes
from .contracts import MODEL_NAME
from .ollama import ModelInspectionError, OllamaClient
from .policy import canonical_policy_bytes, policy_content_digest
from .profile_snapshot import (
    BASELINE_COMMIT,
    ProfileSnapshotError,
    create_profile_snapshot,
    read_profile_snapshot,
)
from .queue import ScreeningQueue, QueueValidationError, TRIGGER_SCOPES


COMMON_NOTICE_KEYS = (
    "notice_id", "source_type", "title", "agency", "method", "url",
    "collection_bucket", "published_at", "deadline_at", "budget",
    "estimated_price", "procurement_class", "region_limit", "lifecycle",
    "qualification_flags", "attachments", "focus_matches",
    "performance_matches", "performance_top_score", "candidate_sources",
    "unknown_fields", "sample_stratum", "sample_role", "raw_source",
)
JUDGMENT_MODES = {"신규", "재판정", "승계"}
REJUDGE_REASONS = {"정정", "재공고", "본공고 전환", "담당자 요청"}
EXECUTION_RE = re.compile(r"^scr-[0-9a-f]{32}$")


class ScreeningCreationError(ValueError):
    """A safe pre-enqueue validation error."""

    def __init__(self, code: str, message: str = "screening input is invalid") -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CreatedExecution:
    execution_id: str
    status: str
    model_name: str
    model_digest: str
    profile_version: str
    artifact_dir: str
    input_artifact_path: str
    input_artifact_digest: str


def _now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScreeningCreationError("input_error", "clock must return an aware timestamp")
    return value


def _json_file(path: Path, code: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ScreeningCreationError(code) from None
    if not isinstance(value, dict):
        raise ScreeningCreationError(code)
    return value


def _safe_run_directory(settings: Settings, run_id: str) -> Path:
    if not isinstance(run_id, str) or not run_id.strip() or "\\" in run_id or Path(run_id).name != run_id:
        raise ScreeningCreationError("input_error")
    parsed = parse_run_id(run_id)
    name = parsed[0] if parsed else run_id.split("--", 1)[0]
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ScreeningCreationError("input_error")
    configured_root = Path(settings.bidops_root)
    if configured_root.is_symlink():
        raise ScreeningCreationError("input_error")
    root = configured_root.resolve()
    runs = root / "data" / "runs"
    for component in (root / "data", runs):
        if component.exists() and component.is_symlink():
            raise ScreeningCreationError("input_error")
    directory = runs / name
    try:
        directory.resolve().relative_to(runs.resolve())
    except (OSError, ValueError):
        raise ScreeningCreationError("input_error") from None
    if directory.is_symlink() or not directory.is_dir():
        raise ScreeningCreationError("input_error")
    return directory


def _policy_body(row: ScreeningPolicy) -> dict[str, Any]:
    body = {
        "schema_version": row.schema_version,
        "policy_version": row.policy_version,
        "prompt_version": row.prompt_version,
        "perspective_prompts": row.perspective_prompts_json,
        "counterargument_prompt": row.counterargument_prompt_json,
        "synthesis_prompt": row.synthesis_prompt_json,
        "candidate_selection": row.candidate_selection_json,
        "thresholds": row.thresholds_json,
    }
    try:
        canonical = canonical_policy_bytes(body)
    except Exception:
        raise ScreeningCreationError("policy_mismatch") from None
    if sha256_bytes(canonical) != row.content_digest:
        raise ScreeningCreationError("policy_mismatch")
    return body


def _notice_common(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ScreeningCreationError("input_error")
    if set(value) != set(COMMON_NOTICE_KEYS):
        raise ScreeningCreationError("input_error")
    result = {key: value[key] for key in COMMON_NOTICE_KEYS}
    if not isinstance(result["notice_id"], str) or not result["notice_id"].strip():
        raise ScreeningCreationError("input_error")
    raw_source = result["raw_source"]
    if not isinstance(raw_source, str) or not raw_source or raw_source.startswith("/") or "\\" in raw_source:
        raise ScreeningCreationError("input_error")
    raw_parts = Path(raw_source).parts
    if any(part in {"", ".", ".."} or ":" in part for part in raw_parts):
        raise ScreeningCreationError("input_error")
    nested = {
        "procurement_class": {"large", "middle", "detail", "code"},
        "region_limit": {"basis", "joint_contract_rate", "joint_contract_regions", "regional_joint_contract_limit"},
        "lifecycle": {"pre_spec_no", "re_notice", "changed_at", "change_reason", "unified_notice_no", "previous_failed_notice_no"},
    }
    for key, required in nested.items():
        if not isinstance(result[key], Mapping) or not required.issubset(result[key]):
            raise ScreeningCreationError("input_error")
    for key in ("attachments", "focus_matches", "performance_matches", "candidate_sources", "unknown_fields"):
        if not isinstance(result[key], list):
            raise ScreeningCreationError("input_error")
    return result


def _source_notices(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    collection = _json_file(directory / "collected-notices.json", "input_error")
    if collection.get("schema_version") != "bidops.collected.v2" or not isinstance(collection.get("notices"), list):
        raise ScreeningCreationError("input_error")
    window = collection.get("source_window")
    if not isinstance(window, dict) or window.get("timezone") != "Asia/Seoul":
        raise ScreeningCreationError("input_error")
    if not isinstance(window.get("from"), str) or not isinstance(window.get("to"), str):
        raise ScreeningCreationError("input_error")
    notices: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in collection["notices"]:
        normalized = _notice_common(item)
        if normalized["notice_id"] in ids:
            raise ScreeningCreationError("input_error")
        ids.add(normalized["notice_id"])
        notices.append(normalized)
    return {"source_window": window, "notices": notices}, collection


def _validation_notices(directory: Path) -> list[str]:
    value = _json_file(directory / "validation-set.json", "input_error")
    if value.get("schema_version") != "bidops.validation-set.v2" or not isinstance(value.get("notices"), list):
        raise ScreeningCreationError("input_error")
    result: list[str] = []
    for item in value["notices"]:
        if not isinstance(item, Mapping) or not isinstance(item.get("notice_id"), str):
            raise ScreeningCreationError("input_error")
        result.append(item["notice_id"])
    if len(set(result)) != len(result):
        raise ScreeningCreationError("input_error")
    return result


def _prior_maps(directory: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Read adjacent prior v3 input/decisions, without modifying either."""
    input_path = directory / "screening-input.json"
    decisions_path = directory / "screening-decisions.json"
    if not input_path.is_file() or not decisions_path.is_file():
        return {}, {}
    try:
        source = _json_file(input_path, "input_error")
        decisions = _json_file(decisions_path, "input_error")
    except ScreeningCreationError:
        return {}, {}
    if source.get("schema_version") != "bidops.screening-input.v1" or decisions.get("schema_version") != "bidops.decisions.v3":
        return {}, {}
    old_notices = {item.get("notice_id"): item for item in source.get("notices", []) if isinstance(item, dict)}
    old_judgments = {item.get("notice_id"): item for item in decisions.get("judgments", []) if isinstance(item, dict)}
    return old_notices, old_judgments


def _mode_for(item: Mapping[str, Any], scope: str, old_notice: Mapping[str, Any] | None, old_judgment: Mapping[str, Any] | None) -> tuple[str, str | None, str | None]:
    if scope in {"quality_sample", "single_notice"}:
        return "신규", None, None
    if not old_notice or not old_judgment:
        return "신규", None, None
    if old_judgment.get("schema_version") not in (None, "bidops.decisions.v3"):
        return "신규", None, None
    old_lifecycle = old_notice.get("lifecycle")
    current_lifecycle = item.get("lifecycle")
    if old_lifecycle == current_lifecycle:
        return "승계", str(old_judgment.get("recorded_in_run") or old_judgment.get("judged_in_run") or ""), None
    if isinstance(old_lifecycle, Mapping) and isinstance(current_lifecycle, Mapping):
        for key, reason in (("correction", "정정"), ("정정", "정정"), ("republish", "재공고"), ("재공고", "재공고"), ("award_transition", "본공고 전환"), ("본공고 전환", "본공고 전환")):
            if old_lifecycle.get(key) != current_lifecycle.get(key):
                return "재판정", None, reason
    return "재판정", None, "담당자 요청"


class ScreeningOrchestrator:
    """Create a frozen execution then append its queue row with that ID."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: Any | None = None,
        queue: ScreeningQueue | None = None,
        ollama: OllamaClient | Any | None = None,
        ollama_client: OllamaClient | Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if isinstance(session_factory, Session):
            session_factory = sessionmaker(bind=session_factory.get_bind(), class_=Session, autoflush=False, expire_on_commit=False)
        self.session_factory = session_factory
        self.queue = queue or ScreeningQueue(session_factory=session_factory, settings=self.settings)
        self.ollama = ollama or ollama_client or OllamaClient(settings=self.settings)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def create_execution(
        self,
        *,
        run_id: str,
        policy_version: str,
        profile_source: str = "current",
        requested_by: str,
        scope: str = "full_run",
        notice_id: str | None = None,
        trigger: str | None = None,
    ) -> CreatedExecution:
        if scope not in {"single_notice", "full_run", "quality_sample"}:
            raise ScreeningCreationError("input_error")
        trigger = trigger or {"single_notice": "cli_single", "full_run": "manual_run", "quality_sample": "quality_gate"}[scope]
        if TRIGGER_SCOPES.get(trigger) != scope:
            raise ScreeningCreationError("input_error")
        execution_id = "scr-" + uuid4().hex
        source_dir = _safe_run_directory(self.settings, run_id)
        source, _collection = _source_notices(source_dir)
        notices = source["notices"]
        if scope == "full_run":
            buckets = body.get("candidate_selection", {}).get("include_collection_buckets", ["candidate_pool"])
            if not isinstance(buckets, list) or any(not isinstance(bucket, str) for bucket in buckets):
                raise ScreeningCreationError("policy_mismatch")
            selected = [item for item in notices if item.get("collection_bucket") in buckets]
        elif scope == "quality_sample":
            order = _validation_notices(source_dir)
            by_id = {item["notice_id"]: item for item in notices}
            if any(value not in by_id for value in order):
                raise ScreeningCreationError("input_error")
            selected = [by_id[value] for value in order]
        else:
            selected = [item for item in notices if item["notice_id"] == notice_id]
            if len(selected) != 1:
                raise ScreeningCreationError("input_error")

        old_notices, old_judgments = _prior_maps(source_dir)
        with self._session() as session:
            run = session.scalar(select(Run).where(Run.id == run_id))
            if run is None or run.status not in {"active", "complete", "성공", "부분 성공"}:
                raise ScreeningCreationError("input_error")
            policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == policy_version))
            if policy is None:
                raise ScreeningCreationError("policy_mismatch")
            body = _policy_body(policy)
            if policy.status not in ({"activation_candidate", "active"} if trigger != "schedule" else {"active"}):
                raise ScreeningCreationError("input_error")
            try:
                snapshot = create_profile_snapshot(session, profile_source=profile_source, project_root=Path(self.settings.bidops_root))
                profile_digest = snapshot.digest
                profile_version = snapshot.version
                model_identity = self.ollama.inspect_model()
            except (ProfileSnapshotError, ModelInspectionError, OSError):
                raise ScreeningCreationError("precondition_failed") from None
            if model_identity.model_name != MODEL_NAME:
                raise ScreeningCreationError("model_inspection")
            # Ensure every selected normalized notice corresponds to this DB run
            # and preserve its source values byte-for-byte in the input.
            for item in selected:
                row = session.scalar(select(Notice).where(Notice.run_id == run_id, Notice.notice_key == item["notice_id"]))
                if row is None:
                    raise ScreeningCreationError("input_error")
            generated_at = aware_iso(_now(self.clock))
            frozen: list[dict[str, Any]] = []
            for item in selected:
                mode, carry, reason = _mode_for(item, scope, old_notices.get(item["notice_id"]), old_judgments.get(item["notice_id"]))
                frozen.append({**item, "judgment_mode": mode, "carry_over_from": carry if mode == "승계" else None, "rejudge_reason": reason if mode == "재판정" else None})
            input_value = {
                "schema_version": "bidops.screening-input.v1", "execution_id": execution_id, "run_id": run_id,
                "generated_at": generated_at, "source_window": source["source_window"],
                "policy_version": policy.policy_version, "prompt_version": policy.prompt_version,
                "company_profile_version": profile_version, "company_profile_digest": profile_digest,
                "candidate_count": len(frozen), "notices": frozen,
            }
            try:
                store = ArtifactStore(Path(self.settings.bidops_root))
                store.execution_dir(execution_id, create=True)
                input_path, input_digest = store.write_json(execution_id, "screening-input.json", input_value)
            except ArtifactError:
                raise ScreeningCreationError("artifact_write") from None
            # The profile snapshot is part of the immutable preflight binding;
            # commit it before Queue opens its own fresh session.
            session.commit()
        policy_identity = policy_version
        prompt_identity = input_value["prompt_version"]
        model_name = model_identity.model_name
        model_digest = model_identity.digest
        try:
            row = self.queue.enqueue(
                execution_id=execution_id, trigger=trigger, source_run_id=run_id, scope=scope,
                requested_by=requested_by, policy_version=policy_identity, prompt_version=prompt_identity,
                model_name=model_name, model_digest=model_digest,
                company_profile_version=profile_version, company_profile_digest=profile_digest,
                input_artifact_path=input_path, input_artifact_digest=input_digest,
                artifact_dir=f"data/screening-executions/{execution_id}", candidate_count=len(frozen),
                **({"notice_pk": self._notice_pk(run_id, notice_id), "notice_id": notice_id} if scope == "single_notice" else {}),
            )
        except Exception as exc:
            if isinstance(exc, QueueValidationError):
                raise ScreeningCreationError("input_error") from None
            raise ScreeningCreationError("queue_failure") from None
        return CreatedExecution(row.execution_id, row.status, row.model_name, row.model_digest, row.company_profile_version, row.artifact_dir, row.input_artifact_path, row.input_artifact_digest)

    create = create_execution
    enqueue = create_execution

    def _session(self) -> Session:
        if self.session_factory is None:
            from ..db import SessionLocal
            return SessionLocal()
        value = self.session_factory()
        if not isinstance(value, Session):
            raise TypeError("session factory did not return a Session")
        return value

    def _notice_pk(self, run_id: str, notice_id: str | None) -> int:
        with self._session() as session:
            row = session.scalar(select(Notice).where(Notice.run_id == run_id, Notice.notice_key == notice_id))
            if row is None:
                raise ScreeningCreationError("input_error")
            return row.id


ExecutionOrchestrator = ScreeningOrchestrator
ScreeningExecutionOrchestrator = ScreeningOrchestrator
ScreeningExecutionService = ScreeningOrchestrator
create_execution = ScreeningOrchestrator.create_execution


__all__ = ["CreatedExecution", "ExecutionOrchestrator", "ScreeningCreationError", "ScreeningExecutionOrchestrator", "ScreeningExecutionService", "ScreeningOrchestrator", "create_execution"]
