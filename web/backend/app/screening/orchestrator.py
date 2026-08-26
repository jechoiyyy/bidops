"""Screening execution creation and the frozen input boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings
from ..ingest.loader import parse_run_id
from ..models import CompanyProfileSnapshot, Notice, Run, ScreeningExecution, ScreeningPolicy
from .artifacts import ArtifactError, ArtifactStore, ExecutionWorkspace, aware_iso, sha256_bytes
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
    profile_digest: str
    artifact_dir: str
    input_artifact_path: str
    input_artifact_digest: str


@dataclass(frozen=True)
class PreparedExecution:
    """An execution prepared in, but not committed from, a caller session."""

    created: CreatedExecution
    row: ScreeningExecution
    workspace: ExecutionWorkspace


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
    # Collection output predates validation sampling and may omit the two
    # sample annotations.  They are optional in the ingest contract; preserve
    # their absence as explicit nulls instead of rejecting the notice or
    # inventing a stratum/role before the sample stage.
    optional_keys = {"sample_stratum", "sample_role"}
    required_keys = set(COMMON_NOTICE_KEYS).difference(optional_keys)
    if not required_keys.issubset(value) or set(value).difference(COMMON_NOTICE_KEYS):
        raise ScreeningCreationError("input_error")
    result = {key: value.get(key) for key in COMMON_NOTICE_KEYS}
    if not isinstance(result["notice_id"], str) or not result["notice_id"].strip():
        raise ScreeningCreationError("input_error")
    raw_source = result["raw_source"]
    if not isinstance(raw_source, str) or not raw_source or raw_source.startswith("/") or "\\" in raw_source:
        raise ScreeningCreationError("input_error")
    raw_parts = raw_source.split("/")
    if any(part in {"", ".", ".."} or ":" in part for part in raw_parts):
        raise ScreeningCreationError("input_error")
    _validate_collected_notice(result)
    return result


_PROCUREMENT_KEYS = ("large", "middle", "detail", "code")
_REGION_KEYS = ("basis", "joint_contract_regions", "joint_contract_rate", "regional_joint_contract_limit")
_LIFECYCLE_KEYS = ("pre_spec_no", "re_notice", "changed_at", "change_reason", "unified_notice_no", "previous_failed_notice_no")
_QUALIFICATION_KEYS = ("participation_limited", "industry_limited", "information_business", "general_service", "service_division", "joint_contract_method", "performance_restricted_competition", "pq_evaluation", "technical_evaluation", "technical_evaluation_rate", "successful_bid_method")
_SAMPLE_ROLES = {"analysis", "audit"}
_SAMPLE_STRATA = {"AI/데이터", "블록체인·DID", "공공 SI·통합관리", "수행실적 유사", "분류 근접", "실적 유사 근접", "무작위"}


def _nullable_string(value: Any) -> bool:
    return value is None or (isinstance(value, str) and bool(value.strip()))


def _aware_datetime(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _decimal_string(value: Any) -> bool:
    return value is None or (isinstance(value, str) and bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value)))


def _exact_object(value: Any, keys: tuple[str, ...]) -> bool:
    return isinstance(value, Mapping) and set(value) == set(keys)


def _validate_collected_notice(item: Mapping[str, Any]) -> None:
    if item.get("source_type") not in {"bid_notice", "pre_spec"}:
        raise ScreeningCreationError("input_error")
    if not isinstance(item.get("collection_bucket"), str) or item["collection_bucket"] not in {"candidate_pool", "audit_pool"}:
        raise ScreeningCreationError("input_error")
    for key in ("title", "agency", "method", "url"):
        if not _nullable_string(item.get(key)):
            raise ScreeningCreationError("input_error")
    for key in ("published_at", "deadline_at"):
        if not _aware_datetime(item.get(key)):
            raise ScreeningCreationError("input_error")
    for key in ("budget", "estimated_price"):
        if not _decimal_string(item.get(key)):
            raise ScreeningCreationError("input_error")
    for key, keys in (("procurement_class", _PROCUREMENT_KEYS), ("region_limit", _REGION_KEYS), ("lifecycle", _LIFECYCLE_KEYS)):
        if not _exact_object(item.get(key), keys):
            raise ScreeningCreationError("input_error")
    procurement = item["procurement_class"]
    if any(not _nullable_string(procurement[key]) for key in _PROCUREMENT_KEYS):
        raise ScreeningCreationError("input_error")
    region = item["region_limit"]
    if any(not _nullable_string(region[key]) for key in ("basis", "joint_contract_rate", "regional_joint_contract_limit")):
        raise ScreeningCreationError("input_error")
    if not isinstance(region["joint_contract_regions"], list) or any(not isinstance(v, str) or not v.strip() for v in region["joint_contract_regions"]):
        raise ScreeningCreationError("input_error")
    lifecycle = item["lifecycle"]
    if not _aware_datetime(lifecycle["changed_at"]):
        raise ScreeningCreationError("input_error")
    if any(not _nullable_string(lifecycle[key]) for key in ("pre_spec_no", "re_notice", "change_reason", "unified_notice_no", "previous_failed_notice_no")):
        raise ScreeningCreationError("input_error")
    qualification = item["qualification_flags"]
    if not isinstance(qualification, Mapping) or (qualification and set(qualification) != set(_QUALIFICATION_KEYS)):
        raise ScreeningCreationError("input_error")
    if qualification and any(not _nullable_string(qualification[key]) for key in _QUALIFICATION_KEYS):
        raise ScreeningCreationError("input_error")
    for key in ("attachments", "focus_matches", "performance_matches"):
        if not isinstance(item[key], list):
            raise ScreeningCreationError("input_error")
    for child in item["attachments"]:
        if not _exact_object(child, ("name", "url")) or any(not isinstance(child[key], str) or not child[key].strip() for key in ("name", "url")):
            raise ScreeningCreationError("input_error")
    for child in item["focus_matches"]:
        keys = ("axis", "label", "matched_field", "matched_text", "field_kind")
        if not _exact_object(child, keys) or child.get("field_kind") not in {"title", "classification", "other"} or any(not isinstance(child[key], str) or not child[key].strip() for key in ("axis", "label", "matched_field", "matched_text")):
            raise ScreeningCreationError("input_error")
    for child in item["performance_matches"]:
        keys = ("project_name", "source_page", "similarity", "common_fragment", "legal_qualification_status")
        if not _exact_object(child, keys) or any(not isinstance(child[key], str) or not child[key].strip() for key in ("project_name", "legal_qualification_status")):
            raise ScreeningCreationError("input_error")
        source_page = child["source_page"]
        if isinstance(source_page, bool) or not isinstance(source_page, (str, int)) or (isinstance(source_page, str) and not source_page.strip()) or (isinstance(source_page, int) and source_page < 0):
            raise ScreeningCreationError("input_error")
        if isinstance(child["similarity"], bool) or not isinstance(child["similarity"], (int, float)) or not math.isfinite(float(child["similarity"])):
            raise ScreeningCreationError("input_error")
        if child["common_fragment"] is not None and (not isinstance(child["common_fragment"], str) or not child["common_fragment"].strip()):
            raise ScreeningCreationError("input_error")
    for key in ("candidate_sources", "unknown_fields"):
        if not isinstance(item[key], list) or any(not isinstance(value, str) or not value.strip() for value in item[key]):
            raise ScreeningCreationError("input_error")
    if item["sample_stratum"] is not None and (not isinstance(item["sample_stratum"], str) or item["sample_stratum"] not in _SAMPLE_STRATA):
        raise ScreeningCreationError("input_error")
    if item["sample_role"] is not None and (not isinstance(item["sample_role"], str) or item["sample_role"] not in _SAMPLE_ROLES):
        raise ScreeningCreationError("input_error")
    score = item["performance_top_score"]
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score))):
        raise ScreeningCreationError("input_error")


def _source_notices(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    collection = _json_file(directory / "collected-notices.json", "input_error")
    if collection.get("schema_version") != "bidops.collected.v2" or not isinstance(collection.get("notices"), list):
        raise ScreeningCreationError("input_error")
    window = collection.get("source_window")
    if not isinstance(window, dict) or set(window) != {"from", "to", "timezone"} or window.get("timezone") != "Asia/Seoul":
        raise ScreeningCreationError("input_error")
    if not isinstance(window.get("from"), str) or not isinstance(window.get("to"), str):
        raise ScreeningCreationError("input_error")
    try:
        window_from = date.fromisoformat(window["from"])
        window_to = date.fromisoformat(window["to"])
    except ValueError:
        raise ScreeningCreationError("input_error") from None
    if window_from > window_to:
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
        if not isinstance(item, Mapping):
            raise ScreeningCreationError("input_error")
        normalized = _notice_common(item)
        result.append(normalized["notice_id"])
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
        # The source judgment's first-judged run is the provenance identity
        # carried into the new input.  It must never be replaced by the
        # current run merely because a prior artifact was recorded there.
        return "승계", str(old_judgment.get("judged_in_run") or ""), None
    if isinstance(old_lifecycle, Mapping) and isinstance(current_lifecycle, Mapping):
        change_reason = current_lifecycle.get("change_reason")
        if change_reason in REJUDGE_REASONS - {"담당자 요청"} and change_reason != old_lifecycle.get("change_reason"):
            return "재판정", None, str(change_reason)
        if current_lifecycle.get("re_notice") != old_lifecycle.get("re_notice") and current_lifecycle.get("re_notice") not in (None, "", "N", "아니오", False):
            return "재판정", None, "재공고"
        old_pre = old_lifecycle.get("pre_spec_no")
        current_pre = current_lifecycle.get("pre_spec_no")
        old_unified = old_lifecycle.get("unified_notice_no")
        current_unified = current_lifecycle.get("unified_notice_no")
        if current_unified and current_unified != old_unified and (old_pre or current_pre):
            return "재판정", None, "본공고 전환"
        # A changed_at-only or otherwise ambiguous difference is not evidence
        # for a 담당자 요청; keep it 신규 until an explicit request exists.
        return "신규", None, None
    return "신규", None, None


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
        workspace: ExecutionWorkspace | None = None
        source_dir = _safe_run_directory(self.settings, run_id)
        source, _collection = _source_notices(source_dir)
        notices = source["notices"]
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
            # Candidate selection is policy-controlled.  Read and validate the
            # immutable policy body before consulting any source candidates.
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
            # A single-notice execution binds one DB Notice row. Full and
            # quality executions are artifact-authoritative and may contain
            # collected candidates outside the validation-set DB projection.
            if scope == "single_notice":
                db_notice = session.scalar(select(Notice).where(Notice.run_id == run_id, Notice.notice_key == notice_id))
                if db_notice is None:
                    raise ScreeningCreationError("input_error")
            try:
                snapshot = create_profile_snapshot(session, profile_source=profile_source, project_root=Path(self.settings.bidops_root))
                profile_digest = snapshot.digest
                profile_version = snapshot.version
            except (ProfileSnapshotError, OSError):
                raise ScreeningCreationError("profile_snapshot") from None
            try:
                model_identity = self.ollama.inspect_model()
            except (ModelInspectionError, OSError, ConnectionError, TimeoutError):
                raise ScreeningCreationError("model_inspection") from None
            if model_identity.model_name != MODEL_NAME:
                raise ScreeningCreationError("model_inspection")
            generated_at = aware_iso(_now(self.clock))
            frozen: list[dict[str, Any]] = []
            for item in selected:
                mode, carry, reason = ("신규", None, None) if scope == "quality_sample" else _mode_for(item, scope, old_notices.get(item["notice_id"]), old_judgments.get(item["notice_id"]))
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
                workspace = store.create_execution_workspace(execution_id)
                input_path, input_digest = workspace.write_json("screening-input.json", input_value)
            except ArtifactError:
                if workspace is not None:
                    try:
                        store.remove_execution(workspace)
                    except ArtifactError:
                        pass
                    finally:
                        workspace.close()
                raise ScreeningCreationError("artifact_write") from None
            # The profile snapshot is part of the immutable preflight binding;
            # commit it before Queue opens its own fresh session.
            try:
                session.commit()
            except Exception:
                if workspace is not None:
                    try:
                        store.remove_execution(workspace)
                    except ArtifactError:
                        pass
                    finally:
                        workspace.close()
                raise
        policy_identity = policy_version
        prompt_identity = input_value["prompt_version"]
        model_name = model_identity.model_name
        model_digest = model_identity.digest
        notice_pk: int | None = None
        try:
            if scope == "single_notice":
                notice_pk = self._notice_pk(run_id, notice_id)
            if workspace is None:
                raise ScreeningCreationError("artifact_write")
            workspace.require_named()
            row = self.queue.enqueue(
                execution_id=execution_id, trigger=trigger, source_run_id=run_id, scope=scope,
                requested_by=requested_by, policy_version=policy_identity, prompt_version=prompt_identity,
                model_name=model_name, model_digest=model_digest,
                company_profile_version=profile_version, company_profile_digest=profile_digest,
                input_artifact_path=input_path, input_artifact_digest=input_digest,
                artifact_dir=f"data/screening-executions/{execution_id}", candidate_count=len(frozen),
                **({"notice_pk": notice_pk, "notice_id": notice_id} if scope == "single_notice" else {}),
            )
        except Exception as exc:
            try:
                if workspace is not None:
                    ArtifactStore(Path(self.settings.bidops_root)).remove_execution(workspace)
            except ArtifactError:
                # The queue row was not created, but leaving an explicitly
                # nonpublished orphan is safer than deleting an unexpected
                # path. The fresh execution ID remains unreferenced.
                pass
            if isinstance(exc, QueueValidationError):
                raise ScreeningCreationError("input_error") from None
            raise ScreeningCreationError("queue_failure") from None
        finally:
            if workspace is not None:
                workspace.close()
        return CreatedExecution(row.execution_id, row.status, row.model_name, row.model_digest, row.company_profile_version, row.company_profile_digest, row.artifact_dir, row.input_artifact_path, row.input_artifact_digest)

    def prepare_execution(
        self,
        session: Session,
        *,
        run_id: str,
        policy_version: str,
        profile_source: str = "current",
        requested_by: str,
        scope: str = "full_run",
        notice_id: str | None = None,
        trigger: str | None = None,
    ) -> PreparedExecution:
        """Prepare one execution in a caller-owned transaction.

        Unlike ``create_execution``, this method never opens a queue session
        or commits.  It is the transaction boundary used by quality gates to
        prepare both ordinary FIFO rows before publishing either one.
        """

        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        if scope not in {"single_notice", "full_run", "quality_sample"}:
            raise ScreeningCreationError("input_error")
        trigger = trigger or {"single_notice": "cli_single", "full_run": "manual_run", "quality_sample": "quality_gate"}[scope]
        if TRIGGER_SCOPES.get(trigger) != scope:
            raise ScreeningCreationError("input_error")
        execution_id = "scr-" + uuid4().hex
        workspace: ExecutionWorkspace | None = None
        source_dir = _safe_run_directory(self.settings, run_id)
        source, _collection = _source_notices(source_dir)
        notices = source["notices"]
        old_notices, old_judgments = _prior_maps(source_dir)
        run = session.scalar(select(Run).where(Run.id == run_id))
        if run is None or run.status not in {"active", "complete", "성공", "부분 성공"}:
            raise ScreeningCreationError("input_error")
        policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == policy_version))
        if policy is None:
            raise ScreeningCreationError("policy_mismatch")
        body = _policy_body(policy)
        if policy.status not in ({"activation_candidate", "active"} if trigger != "schedule" else {"active"}):
            raise ScreeningCreationError("input_error")
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
            db_notice = session.scalar(select(Notice).where(Notice.run_id == run_id, Notice.notice_key == notice_id))
            if db_notice is None:
                raise ScreeningCreationError("input_error")
        try:
            snapshot = create_profile_snapshot(session, profile_source=profile_source, project_root=Path(self.settings.bidops_root))
            profile_digest = snapshot.digest
            profile_version = snapshot.version
        except (ProfileSnapshotError, OSError):
            raise ScreeningCreationError("profile_snapshot") from None
        try:
            model_identity = self.ollama.inspect_model()
        except (ModelInspectionError, OSError, ConnectionError, TimeoutError):
            raise ScreeningCreationError("model_inspection") from None
        if model_identity.model_name != MODEL_NAME:
            raise ScreeningCreationError("model_inspection")
        generated_at = aware_iso(_now(self.clock))
        frozen: list[dict[str, Any]] = []
        for item in selected:
            mode, carry, reason = ("신규", None, None) if scope == "quality_sample" else _mode_for(item, scope, old_notices.get(item["notice_id"]), old_judgments.get(item["notice_id"]))
            frozen.append({**item, "judgment_mode": mode, "carry_over_from": carry if mode == "승계" else None, "rejudge_reason": reason if mode == "재판정" else None})
        input_value = {
            "schema_version": "bidops.screening-input.v1", "execution_id": execution_id, "run_id": run_id,
            "generated_at": generated_at, "source_window": source["source_window"],
            "policy_version": policy.policy_version, "prompt_version": policy.prompt_version,
            "company_profile_version": profile_version, "company_profile_digest": profile_digest,
            "candidate_count": len(frozen), "notices": frozen,
        }
        store = ArtifactStore(Path(self.settings.bidops_root))
        try:
            workspace = store.create_execution_workspace(execution_id)
            input_path, input_digest = workspace.write_json("screening-input.json", input_value)
            workspace.require_named()
            queue_notice = selected[0]["notice_id"] if scope == "single_notice" else None
            queue_notice_pk = db_notice.id if scope == "single_notice" else None
            row = self.queue.enqueue_in_session(
                session,
                execution_id=execution_id,
                trigger=trigger,
                source_run_id=run_id,
                scope=scope,
                requested_by=requested_by,
                policy_version=policy_version,
                prompt_version=input_value["prompt_version"],
                model_name=model_identity.model_name,
                model_digest=model_identity.digest,
                company_profile_version=profile_version,
                company_profile_digest=profile_digest,
                input_artifact_path=input_path,
                input_artifact_digest=input_digest,
                artifact_dir=f"data/screening-executions/{execution_id}",
                candidate_count=len(frozen),
                **({"notice_pk": queue_notice_pk, "notice_id": queue_notice} if scope == "single_notice" else {}),
            )
        except Exception as exc:
            try:
                if workspace is not None:
                    store.remove_execution(workspace)
            except ArtifactError:
                pass
            finally:
                if workspace is not None:
                    workspace.close()
            if isinstance(exc, (ArtifactError, QueueValidationError)):
                raise ScreeningCreationError("artifact_write" if isinstance(exc, ArtifactError) else "input_error") from None
            raise ScreeningCreationError("queue_failure") from None
        created = CreatedExecution(row.execution_id, row.status, row.model_name, row.model_digest, row.company_profile_version, row.company_profile_digest, row.artifact_dir, row.input_artifact_path, row.input_artifact_digest)
        if workspace is None:
            raise ScreeningCreationError("artifact_write")
        return PreparedExecution(created=created, row=row, workspace=workspace)

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


__all__ = ["CreatedExecution", "ExecutionOrchestrator", "PreparedExecution", "ScreeningCreationError", "ScreeningExecutionOrchestrator", "ScreeningExecutionService", "ScreeningOrchestrator", "create_execution"]
