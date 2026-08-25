"""Persistence and orchestration boundary for model-quality gates.

Gate creation validates the immutable 40-notice input before touching the
database.  The two passes are ordinary ``quality_sample`` executions and are
therefore subject to the same FIFO worker as every other Qwen call.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings
from ..models import (
    AuditEvent,
    CompanyProfileSnapshot,
    QualityGate,
    QualityGateEvaluation,
    QualityGateReview,
    Run,
    ScreeningExecution,
    ScreeningPolicy,
)
from .artifacts import ArtifactError, ArtifactStore, ExecutionOwnership, sha256_bytes
from .execution_store import ScreeningExecutionStore
from .orchestrator import ScreeningOrchestrator
from .profile_snapshot import BASELINE_COMMIT
from .quality_metrics import (
    QualityMetricError,
    SCREENING_BASIS,
    _judgment_map,
    calculate_metrics,
    frozen_input_digest,
    judgment_digest,
    required_metrics_pass,
)


FIXED_RUN_ID = "20260817-20260823"
FIXED_SAMPLE_RELATIVE = "data/runs/20260817-20260823/validation-set.json"
FIXED_BASELINE_RELATIVE = "data/runs/20260817-20260823/screening-decisions.json"
FIXED_SOURCE_WINDOW = {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"}
PURPOSES = frozenset({"model_comparison", "operational_approval"})
EXECUTION_TERMINAL = frozenset({"성공", "부분 성공", "실패", "중단됨"})
EXECUTION_COMPLETED = frozenset({"성공", "부분 성공"})
RESULT_STATUSES = frozenset({"통과", "미달", "미측정", "보류"})


class QualityGateError(RuntimeError):
    """Base class for safe gate errors."""


class QualityGateValidationError(QualityGateError, ValueError):
    """Input or profile/source correspondence is invalid."""


class QualityGateConflict(QualityGateError):
    """A review or evaluation conflicts with immutable gate state."""


class QualityGateActivationError(QualityGateConflict):
    """A quality result cannot be used for operational activation."""


def _factory(value: Any | None) -> sessionmaker[Session]:
    if value is None:
        from ..db import SessionLocal

        return SessionLocal
    if isinstance(value, Session):
        bind = value.get_bind()
        if not isinstance(bind, Engine):
            raise TypeError("session must be bound to an Engine")
        return sessionmaker(bind=bind, class_=Session, autoflush=False, expire_on_commit=False)
    if isinstance(value, Engine):
        return sessionmaker(bind=value, class_=Session, autoflush=False, expire_on_commit=False)
    if callable(value):
        return value
    raise TypeError("session_factory must be a Session, Engine, or factory")


def _now(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise QualityGateValidationError("timestamp must be timezone-aware")
    return result.astimezone(timezone.utc)


def _actor(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise QualityGateValidationError("created_by/reviewer must be nonblank")
    return value.strip()


def _safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise QualityGateValidationError("artifact path is invalid")
    parts = value.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise QualityGateValidationError("artifact path is invalid")
    return value


def _read_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualityGateValidationError("fixed quality input is unreadable") from exc
    if not isinstance(value, dict):
        raise QualityGateValidationError("fixed quality input must be an object")
    return raw, value


def validate_fixed_inputs(project_root: Path | str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes, list[str]]:
    """Validate the exact fixed sample and Claude baseline before DB writes."""

    root = Path(project_root).resolve()
    sample_path = root / FIXED_SAMPLE_RELATIVE
    baseline_path = root / FIXED_BASELINE_RELATIVE
    sample_raw, sample = _read_json(sample_path)
    baseline_raw, baseline = _read_json(baseline_path)
    if sample.get("schema_version") != "bidops.validation-set.v2":
        raise QualityGateValidationError("validation sample schema is invalid")
    notices = sample.get("notices")
    if not isinstance(notices, list) or len(notices) != 40:
        raise QualityGateValidationError("validation sample must contain exactly 40 notices")
    if sample.get("source_window") != FIXED_SOURCE_WINDOW:
        raise QualityGateValidationError("validation sample source window is invalid")
    ids: list[str] = []
    for item in notices:
        if not isinstance(item, Mapping) or not isinstance(item.get("notice_id"), str) or not item["notice_id"].strip():
            raise QualityGateValidationError("validation notice identity is invalid")
        ids.append(item["notice_id"])
    if len(set(ids)) != 40:
        raise QualityGateValidationError("validation notice IDs must be unique")
    if baseline.get("schema_version") != "bidops.decisions.v2":
        raise QualityGateValidationError("Claude baseline schema is invalid")
    judgments = baseline.get("judgments")
    if not isinstance(judgments, list) or len(judgments) != 40:
        raise QualityGateValidationError("Claude baseline must contain exactly 40 judgments")
    baseline_ids: list[str] = []
    for item in judgments:
        if not isinstance(item, Mapping) or not isinstance(item.get("notice_id"), str) or not item["notice_id"].strip():
            raise QualityGateValidationError("Claude baseline identity is invalid")
        baseline_ids.append(item["notice_id"])
    if baseline_ids != ids or len(set(baseline_ids)) != 40:
        raise QualityGateValidationError("validation and Claude baseline notice correspondence is invalid")
    return sample, baseline, sample_raw, baseline_raw, ids


def _canonical_pass_input(value: Mapping[str, Any]) -> str:
    try:
        return frozen_input_digest(value)
    except (QualityMetricError, ArtifactError):
        raise QualityGateValidationError("quality pass input is invalid") from None


def _input_matches_fixed_sample(value: Mapping[str, Any], sample: Mapping[str, Any], sample_ids: Sequence[str]) -> bool:
    notices = value.get("notices")
    expected = sample.get("notices")
    if not isinstance(notices, list) or not isinstance(expected, list) or len(notices) != len(expected) or len(notices) != len(sample_ids):
        return False
    if [item.get("notice_id") if isinstance(item, Mapping) else None for item in notices] != list(sample_ids):
        return False
    for actual, fixed in zip(notices, expected):
        if not isinstance(actual, Mapping) or not isinstance(fixed, Mapping):
            return False
        if any(actual.get(key) != fixed_value for key, fixed_value in fixed.items()):
            return False
    return True


_INPUT_KEYS = frozenset({
    "schema_version", "execution_id", "run_id", "generated_at", "source_window",
    "policy_version", "prompt_version", "company_profile_version", "company_profile_digest",
    "candidate_count", "notices",
})


def _input_binding_valid(
    value: Mapping[str, Any], execution: ScreeningExecution, sample: Mapping[str, Any], sample_ids: Sequence[str],
    *, expected_source_window: Mapping[str, Any] | None = None,
) -> bool:
    if set(value) != _INPUT_KEYS or value.get("schema_version") != "bidops.screening-input.v1":
        return False
    if value.get("execution_id") != execution.execution_id or value.get("run_id") != execution.source_run_id:
        return False
    if value.get("policy_version") != execution.policy_version or value.get("prompt_version") != execution.prompt_version:
        return False
    if value.get("company_profile_version") != execution.company_profile_version or value.get("company_profile_digest") != execution.company_profile_digest:
        return False
    profile_digest = value.get("company_profile_digest")
    if not isinstance(profile_digest, str) or len(profile_digest) != 64 or any(char not in "0123456789abcdef" for char in profile_digest):
        return False
    if value.get("company_profile_version") != f"company-profile.sha256:{profile_digest}":
        return False
    if execution.candidate_count != len(sample_ids) or execution.input_artifact_path != f"data/screening-executions/{execution.execution_id}/screening-input.json" or execution.artifact_dir != f"data/screening-executions/{execution.execution_id}":
        return False
    try:
        generated = datetime.fromisoformat(str(value.get("generated_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if generated.tzinfo is None or generated.utcoffset() is None:
        return False
    window = value.get("source_window")
    if not isinstance(window, Mapping) or set(window) != {"from", "to", "timezone"} or window.get("timezone") != "Asia/Seoul":
        return False
    if expected_source_window is not None and dict(window) != dict(expected_source_window):
        return False
    try:
        if not isinstance(window.get("from"), str) or not isinstance(window.get("to"), str) or date.fromisoformat(window["from"]) > date.fromisoformat(window["to"]):
            return False
    except ValueError:
        return False
    notices = value.get("notices")
    if not isinstance(notices, list) or value.get("candidate_count") != len(notices) or len(notices) != len(sample_ids) or not _input_matches_fixed_sample(value, sample, sample_ids):
        return False
    fixed_by_id = {item["notice_id"]: item for item in sample.get("notices", []) if isinstance(item, Mapping) and isinstance(item.get("notice_id"), str)}
    for item in notices:
        if not isinstance(item, Mapping) or set(item) != set(fixed_by_id.get(item.get("notice_id"), {})) | {"judgment_mode", "carry_over_from", "rejudge_reason"}:
            return False
        mode = item.get("judgment_mode")
        if mode not in {"신규", "재판정", "승계"}:
            return False
        if mode == "신규" and (item.get("carry_over_from") is not None or item.get("rejudge_reason") is not None):
            return False
        if mode == "재판정" and (item.get("carry_over_from") is not None or item.get("rejudge_reason") not in {"정정", "재공고", "본공고 전환", "담당자 요청"}):
            return False
        if mode == "승계" and (not isinstance(item.get("carry_over_from"), str) or not item["carry_over_from"].strip() or item.get("rejudge_reason") is not None):
            return False
        if execution.scope == "quality_sample" and (mode != "신규" or item.get("carry_over_from") is not None or item.get("rejudge_reason") is not None):
            return False
    return True


def _decisions_binding_issues(
    value: Mapping[str, Any],
    execution: ScreeningExecution,
    input_value: Mapping[str, Any],
    sample_ids: Sequence[str],
    *,
    pass_name: str,
    expected_source_window: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Validate the complete decisions.v3 artifact and all provenance links."""

    def issue(notice_id: str, reason: str) -> dict[str, str]:
        return {"notice_id": notice_id, "pass": pass_name, "reason": reason}

    if not _input_binding_valid(
        input_value, execution, {"notices": input_value.get("notices"), "source_window": input_value.get("source_window")},
        sample_ids, expected_source_window=expected_source_window,
    ):
        return [issue(notice_id, "screening_input_binding_invalid") for notice_id in sample_ids]
    expected_top = {
        "execution_id": execution.execution_id,
        "run_id": execution.source_run_id,
        "generated_at": input_value.get("generated_at"),
        "model_name": execution.model_name,
        "model_digest": execution.model_digest,
        "prompt_version": execution.prompt_version,
        "policy_version": execution.policy_version,
        "company_profile_version": execution.company_profile_version,
        "company_profile_digest": execution.company_profile_digest,
    }
    top_reasons: list[str] = []
    if set(value) != {"schema_version", "execution_id", "run_id", "generated_at", "screening_basis", "model_name", "model_digest", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest", "judgments"}:
        top_reasons.append("decisions_top_level_invalid")
    if value.get("schema_version") != "bidops.decisions.v3":
        top_reasons.append("decisions_schema_invalid")
    for key, expected in expected_top.items():
        if value.get(key) != expected:
            top_reasons.append(f"decisions_{key}_binding_mismatch")
    if value.get("screening_basis") != SCREENING_BASIS:
        top_reasons.append("decisions_screening_basis_invalid")
    if top_reasons:
        reason = ":".join(dict.fromkeys(top_reasons))
        return [issue(notice_id, reason) for notice_id in sample_ids]
    notices = {
        item["notice_id"]: item
        for item in input_value.get("notices", [])
        if isinstance(item, Mapping) and isinstance(item.get("notice_id"), str)
    }
    _valid, issues = _judgment_map(value, pass_name=pass_name, notices=notices)
    result = list(issues)
    judgments = value.get("judgments")
    if not isinstance(judgments, list):
        return result + [issue(notice_id, "judgments_missing") for notice_id in sample_ids]
    by_id = {item.get("notice_id"): item for item in judgments if isinstance(item, Mapping) and isinstance(item.get("notice_id"), str)}
    for notice_id, judgment in by_id.items():
        notice = notices.get(notice_id)
        if notice is None:
            continue
        mode = notice.get("judgment_mode")
        expected_carry = mode == "승계"
        expected_judged = notice.get("carry_over_from") if expected_carry else execution.source_run_id
        if (
            judgment.get("judgment_mode") != mode
            or judgment.get("carried_over") is not expected_carry
            or judgment.get("rejudge_reason") != notice.get("rejudge_reason")
            or judgment.get("judged_in_run") != expected_judged
            or judgment.get("recorded_in_run") != execution.source_run_id
        ):
            result.append(issue(notice_id, "judgment_input_provenance_mismatch"))
        if mode != "승계" and any(judgment.get(key) != getattr(execution, key) for key in ("model_name", "model_digest", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest")):
            result.append(issue(notice_id, "judgment_execution_metadata_mismatch"))
    known = {row["notice_id"] for row in result if row["notice_id"]}
    for notice_id in sample_ids:
        if notice_id not in by_id and notice_id not in known:
            result.append(issue(notice_id, "missing_judgment"))
    for notice_id in by_id:
        if notice_id not in set(sample_ids):
            result.append(issue(notice_id, "out_of_sample"))
    return result


def _load_execution_artifact(root: Path, execution_id: str, filename: str, *, expected_digest: str | None = None) -> dict[str, Any]:
    try:
        raw = ArtifactStore(root).read_bytes(execution_id, filename, expected_digest=expected_digest)
        value = json.loads(raw)
    except ArtifactError as exc:
        raise QualityGateValidationError("quality execution artifact is unavailable") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise QualityGateValidationError("quality execution artifact is invalid") from exc
    if not isinstance(value, dict):
        raise QualityGateValidationError("quality execution artifact is invalid")
    return value


def _initial_metrics(ids: Sequence[str]) -> dict[str, Any]:
    # The shape is fixed from the first revision.  It is still an honest
    # calculation: no pass has yielded a valid judgment yet.
    return calculate_metrics({}, {}, sample_ids=ids, expected_sample_count=40)


def _status_for_executions(a: str, b: str) -> str:
    if a == "대기" and b == "대기":
        return "대기"
    if a == "중단됨" or b == "중단됨":
        return "중단됨"
    if a == "실패" or b == "실패":
        return "실패"
    if a in EXECUTION_TERMINAL and b in EXECUTION_TERMINAL:
        return "완료"
    return "실행 중"


def _result_for_metrics(
    *,
    execution_status: str,
    metrics: Mapping[str, Any],
    valid_review_count: int,
    distinct_notice_review_count: int,
    structure_reasons: Sequence[str] = (),
) -> tuple[str, list[str]]:
    if execution_status in {"실패", "중단됨"} or execution_status != "완료":
        return "미측정", ["execution_not_terminal"] if execution_status == "실행 중" else [f"execution_{execution_status}"]
    if valid_review_count < 10 or distinct_notice_review_count < 10:
        return "미측정", ["review_count_below_minimum"]
    if structure_reasons:
        return "보류", list(structure_reasons)
    passed, reasons = required_metrics_pass(metrics)
    return ("통과", []) if passed else ("미달", reasons)


def _metric_structure_reasons(metrics: Mapping[str, Any]) -> list[str]:
    """Convert explicit pass-sample exclusions into a deterministic hold.

    A review mismatch is a usable, auditable exclusion.  An A/B identity or
    contract failure is different: it means the fixed sample was not actually
    evaluated as promised, so a completed gate must remain 보류.
    """

    reasons: list[str] = []
    for row in metrics.get("excluded_notices", ()) if isinstance(metrics, Mapping) else ():
        if not isinstance(row, Mapping) or row.get("pass") not in {"A", "B"}:
            continue
        notice_id = str(row.get("notice_id") or "")
        reason = str(row.get("reason") or "invalid_exclusion")
        reasons.append(f"{row['pass']}_structure:{notice_id}:{reason}")
    return list(dict.fromkeys(reasons))


def _evaluation_id() -> str:
    return "gateeval-" + uuid4().hex


class QualityGateService:
    """Create, evaluate, and review immutable quality gates."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: Any | None = None,
        orchestrator: ScreeningOrchestrator | Any | None = None,
        queue: ScreeningExecutionStore | Any | None = None,
        transaction_preparer: Any | None = None,
        clock: Any | None = None,
        busy_retries: int = 5,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = _factory(session_factory)
        self.orchestrator = orchestrator or ScreeningOrchestrator(settings=self.settings, session_factory=self.session_factory)
        self.queue = queue or ScreeningExecutionStore(session_factory=self.session_factory, settings=self.settings)
        self.transaction_preparer = transaction_preparer or getattr(self.orchestrator, "prepare_execution", None)
        self.clock = clock or _now
        self.busy_retries = max(0, busy_retries)

    @contextmanager
    def _session(self, *, immediate: bool = False) -> Iterator[Session]:
        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("session factory did not return Session")
        session.expire_on_commit = False
        try:
            if immediate and session.get_bind().dialect.name == "sqlite":
                session.connection().exec_driver_sql("PRAGMA busy_timeout = 5000")
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _cleanup_prepared_artifacts(self, prepared: Sequence[tuple[str, ExecutionOwnership]]) -> None:
        """Remove only directories whose fresh inode ownership is retained."""

        store = ArtifactStore(Path(self.settings.bidops_root))
        seen: set[tuple[str, int, int]] = set()
        for execution_id, ownership in prepared:
            key = (execution_id, ownership.device, ownership.inode)
            if key in seen:
                continue
            seen.add(key)
            try:
                store.remove_execution(execution_id, ownership)
            except (ArtifactError, OSError):
                # A failed preflight may not have created its directory.  No
                # database row was published, and an absent path is already
                # the desired state.
                continue

    def create_gate(
        self,
        *,
        purpose: str,
        policy_version: str,
        profile_source: str,
        created_by: str,
        run_id: str = FIXED_RUN_ID,
    ) -> QualityGate:
        """Validate fixed inputs, then queue independent A/B passes."""

        actor = _actor(created_by)
        if purpose not in PURPOSES:
            raise QualityGateValidationError("quality gate purpose is invalid")
        expected_source = f"git:{BASELINE_COMMIT}" if purpose == "model_comparison" else "current"
        if profile_source != expected_source:
            raise QualityGateValidationError("profile source is not permitted for this purpose")
        if run_id != FIXED_RUN_ID:
            raise QualityGateValidationError("quality gate must use the fixed baseline run")
        # This is deliberately the first operation.  Invalid correspondence
        # must leave no gate, snapshot, or queue rows behind.
        sample, baseline, sample_raw, baseline_raw, sample_ids = validate_fixed_inputs(self.settings.bidops_root)

        with self._session() as session:
            run = session.scalar(select(Run).where(Run.id == run_id))
            policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == policy_version))
            if run is None or policy is None:
                raise QualityGateValidationError("quality gate run or policy is missing")
            if policy.status not in {"activation_candidate", "active"}:
                raise QualityGateValidationError("policy is not selectable")

        root = Path(self.settings.bidops_root)
        prepared_artifacts: list[tuple[str, ExecutionOwnership]] = []
        try:
            if self.transaction_preparer is None:
                raise QualityGateConflict("quality gate requires a transaction-aware execution preparer")
            sample_digest = sha256_bytes(sample_raw)
            baseline_digest = sha256_bytes(baseline_raw)
            now = _now(self.clock())
            gate_id = "gate-" + uuid4().hex
            with self._session(immediate=True) as session:
                policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == policy_version))
                if policy is None or policy.status not in {"activation_candidate", "active"}:
                    raise QualityGateValidationError("quality gate policy is not selectable")
                prepared_a = self.transaction_preparer(
                    session, run_id=run_id, policy_version=policy_version, profile_source=profile_source,
                    requested_by=actor, scope="quality_sample", trigger="quality_gate",
                )
                if not isinstance(getattr(prepared_a, "ownership", None), ExecutionOwnership):
                    raise QualityGateConflict("quality pass ownership was not retained")
                prepared_artifacts.append((prepared_a.created.execution_id, prepared_a.ownership))
                prepared_b = self.transaction_preparer(
                    session, run_id=run_id, policy_version=policy_version, profile_source=profile_source,
                    requested_by=actor, scope="quality_sample", trigger="quality_gate",
                )
                if not isinstance(getattr(prepared_b, "ownership", None), ExecutionOwnership):
                    raise QualityGateConflict("quality pass ownership was not retained")
                prepared_artifacts.append((prepared_b.created.execution_id, prepared_b.ownership))
                first, second = prepared_a.created, prepared_b.created
                if first.execution_id == second.execution_id:
                    raise QualityGateConflict("quality passes must be independent")
                execution_a, execution_b = prepared_a.row, prepared_b.row
                input_a = _load_execution_artifact(root, first.execution_id, "screening-input.json", expected_digest=execution_a.input_artifact_digest)
                input_b = _load_execution_artifact(root, second.execution_id, "screening-input.json", expected_digest=execution_b.input_artifact_digest)
                if not _input_binding_valid(input_a, execution_a, sample, sample_ids, expected_source_window=sample.get("source_window")) or not _input_binding_valid(input_b, execution_b, sample, sample_ids, expected_source_window=sample.get("source_window")):
                    raise QualityGateConflict("quality pass input binding is invalid")
                if _canonical_pass_input(input_a) != _canonical_pass_input(input_b):
                    raise QualityGateConflict("quality pass frozen input combination differs")
                if input_a.get("candidate_count") != 40 or input_b.get("candidate_count") != 40:
                    raise QualityGateValidationError("quality pass must contain exactly 40 notices")
                if not _input_matches_fixed_sample(input_a, sample, sample_ids) or not _input_matches_fixed_sample(input_b, sample, sample_ids):
                    raise QualityGateConflict("quality pass notices do not match the fixed sample")
                if execution_a.scope != "quality_sample" or execution_b.scope != "quality_sample":
                    raise QualityGateConflict("quality pass scope is invalid")
                profile = session.scalar(select(CompanyProfileSnapshot).where(CompanyProfileSnapshot.version == execution_a.company_profile_version))
                if profile is None or profile.digest != execution_a.company_profile_digest:
                    raise QualityGateConflict("quality pass profile identity is invalid")
                if (
                    execution_a.policy_version != policy_version
                    or execution_b.policy_version != policy_version
                    or execution_a.prompt_version != execution_b.prompt_version
                    or execution_a.model_name != execution_b.model_name
                    or execution_a.model_digest != execution_b.model_digest
                    or execution_a.company_profile_version != execution_b.company_profile_version
                    or execution_a.company_profile_digest != execution_b.company_profile_digest
                    or execution_a.candidate_count != 40
                    or execution_b.candidate_count != 40
                ):
                    raise QualityGateConflict("quality pass policy identity differs")
                gate = QualityGate(
                    gate_id=gate_id, purpose=purpose, execution_status="대기", result_status="미측정",
                    baseline_run_id=run_id, sample_artifact_path=_safe_relative(FIXED_SAMPLE_RELATIVE),
                    sample_artifact_digest=sample_digest, baseline_decisions_path=_safe_relative(FIXED_BASELINE_RELATIVE),
                    baseline_decisions_digest=baseline_digest, policy_version=policy_version,
                    prompt_version=execution_a.prompt_version, model_name=execution_a.model_name,
                    model_digest=execution_a.model_digest, company_profile_version=execution_a.company_profile_version,
                    company_profile_digest=execution_a.company_profile_digest,
                    pass_a_execution_id=first.execution_id, pass_b_execution_id=second.execution_id,
                    created_by=actor, created_at=now, completed_at=None, metrics_json=_initial_metrics(sample_ids),
                    reasons_json=["execution_pending"],
                )
                session.add(gate)
                session.flush()
                session.add(QualityGateEvaluation(
                    evaluation_id=_evaluation_id(), gate_id=gate_id, revision=1, result_status="미측정",
                    metrics_json=gate.metrics_json, reasons_json=["execution_pending"], valid_review_count=0,
                    distinct_notice_review_count=0, created_at=now,
                ))
                session.add(AuditEvent(
                    event_id="audit-" + uuid4().hex, event_type="quality_gate.created", actor=actor,
                    target_type="quality_gate", target_id=gate_id, occurred_at=now,
                    details_json={
                        "purpose": purpose, "policy_version": policy_version,
                        "prompt_version": execution_a.prompt_version, "model_name": execution_a.model_name,
                        "model_digest": execution_a.model_digest,
                        "company_profile_version": execution_a.company_profile_version,
                        "company_profile_digest": execution_a.company_profile_digest,
                        "sample_artifact_digest": sample_digest, "baseline_decisions_digest": baseline_digest,
                        "pass_a_execution_id": first.execution_id, "pass_b_execution_id": second.execution_id,
                    },
                ))
                session.flush()
                return gate
        except Exception:
            self._cleanup_prepared_artifacts(prepared_artifacts)
            raise

    create = create_gate

    def _gate_and_rows(self, session: Session, gate_id: str) -> tuple[QualityGate, ScreeningExecution, ScreeningExecution]:
        gate = session.scalar(select(QualityGate).where(QualityGate.gate_id == gate_id))
        if gate is None:
            raise QualityGateValidationError("quality gate was not found")
        a = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == gate.pass_a_execution_id))
        b = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == gate.pass_b_execution_id))
        if a is None or b is None:
            raise QualityGateConflict("quality pass execution is missing")
        return gate, a, b

    @staticmethod
    def _lock_gate(session: Session, gate_id: str) -> QualityGate:
        if session.get_bind().dialect.name == "sqlite":
            # SQLite ignores FOR UPDATE.  A no-op write takes the RESERVED
            # lock while retaining the caller's transaction, preventing a
            # review writer from committing between validation and activation.
            session.execute(
                update(QualityGate)
                .where(QualityGate.gate_id == gate_id)
                .values(result_status=QualityGate.result_status)
            )
        gate = session.scalar(select(QualityGate).where(QualityGate.gate_id == gate_id).with_for_update())
        if gate is None:
            raise QualityGateValidationError("quality gate was not found")
        return gate

    def _reviews(self, session: Session, gate_id: str) -> list[dict[str, Any]]:
        return [
            {
                "notice_id": row.notice_id,
                "decision_digest": row.decision_digest,
                "reviewer": row.reviewer,
                "evidence_judgment": row.evidence_judgment,
                "note": row.note,
            }
            for row in session.scalars(select(QualityGateReview).where(QualityGateReview.gate_id == gate_id).order_by(QualityGateReview.review_id))
        ]

    @staticmethod
    def _latest(session: Session, gate_id: str) -> QualityGateEvaluation:
        row = session.scalar(select(QualityGateEvaluation).where(QualityGateEvaluation.gate_id == gate_id).order_by(QualityGateEvaluation.revision.desc()).limit(1))
        if row is None:
            raise QualityGateConflict("quality gate has no evaluation")
        return row

    def _append_evaluation(
        self,
        session: Session,
        gate: QualityGate,
        *,
        result_status: str,
        metrics: Mapping[str, Any],
        reasons: Sequence[str],
        valid_reviews: int,
        distinct_reviews: int,
        force: bool = False,
    ) -> QualityGateEvaluation:
        if result_status not in RESULT_STATUSES:
            raise QualityGateValidationError("evaluation result status is invalid")
        # Serialize revision allocation with the gate row on databases that
        # support row locks.  SQLite callers already hold BEGIN IMMEDIATE.
        session.scalar(select(QualityGate.gate_id).where(QualityGate.gate_id == gate.gate_id).with_for_update())
        latest = self._latest(session, gate.gate_id)
        reasons_list = list(dict.fromkeys(str(reason) for reason in reasons))
        same = latest.result_status == result_status and latest.metrics_json == dict(metrics) and latest.reasons_json == reasons_list and latest.valid_review_count == valid_reviews and latest.distinct_notice_review_count == distinct_reviews
        if same and not force:
            return latest
        revision = int(session.scalar(select(func.max(QualityGateEvaluation.revision)).where(QualityGateEvaluation.gate_id == gate.gate_id)) or 0) + 1
        evaluation = QualityGateEvaluation(
            evaluation_id=_evaluation_id(), gate_id=gate.gate_id, revision=revision,
            result_status=result_status, metrics_json=dict(metrics), reasons_json=reasons_list,
            valid_review_count=valid_reviews, distinct_notice_review_count=distinct_reviews,
            created_at=_now(self.clock()),
        )
        session.add(evaluation)
        gate.result_status = result_status
        gate.metrics_json = dict(metrics)
        gate.reasons_json = reasons_list
        session.flush()
        return evaluation

    def refresh(self, gate_id: str) -> QualityGateEvaluation:
        """Reconcile pass statuses and append the newest immutable evaluation."""

        with self._session(immediate=True) as session:
            # PostgreSQL needs the row lock before any artifact/review read;
            # SQLite's BEGIN IMMEDIATE provides the same serialization.
            self._lock_gate(session, gate_id)
            gate, a, b = self._gate_and_rows(session, gate_id)
            aggregate = _status_for_executions(a.status, b.status)
            completed_at = (
                gate.completed_at
                if aggregate in {"완료", "실패", "중단됨"} and gate.execution_status == aggregate and gate.completed_at is not None
                else (_now(self.clock()) if aggregate in {"완료", "실패", "중단됨"} else None)
            )
            gate.execution_status = aggregate
            gate.completed_at = completed_at
            reviews = self._reviews(session, gate.gate_id)
            if aggregate == "완료":
                try:
                    metrics, valid_count, distinct_count, structure = self._calculate_gate_metrics(
                        gate=gate, execution_a=a, execution_b=b, reviews=reviews,
                    )
                    result, reasons = _result_for_metrics(execution_status=aggregate, metrics=metrics, valid_review_count=valid_count, distinct_notice_review_count=distinct_count, structure_reasons=structure)
                except (QualityGateError, ArtifactError, QualityMetricError, KeyError, TypeError, ValueError):
                    metrics = gate.metrics_json if isinstance(gate.metrics_json, dict) else {}
                    valid_count = sum(row.get("evidence_judgment") in {"동의", "근거 부족"} for row in reviews)
                    distinct_count = len({row.get("notice_id") for row in reviews if row.get("evidence_judgment") in {"동의", "근거 부족"}})
                    result, reasons = _result_for_metrics(
                        execution_status=aggregate, metrics=metrics,
                        valid_review_count=valid_count, distinct_notice_review_count=distinct_count,
                        structure_reasons=["calculation_impossible"],
                    )
            else:
                metrics = dict(gate.metrics_json) if isinstance(gate.metrics_json, dict) else {}
                excluded = list(metrics.get("excluded_notices", []))
                if a.status not in EXECUTION_COMPLETED:
                    excluded.append({"notice_id": "", "pass": "A", "reason": f"execution_{a.status}"})
                if b.status not in EXECUTION_COMPLETED:
                    excluded.append({"notice_id": "", "pass": "B", "reason": f"execution_{b.status}"})
                metrics["excluded_notices"] = excluded
                valid_count = 0
                distinct_count = 0
                result, reasons = _result_for_metrics(execution_status=aggregate, metrics=metrics, valid_review_count=0, distinct_notice_review_count=0)
            evaluation = self._append_evaluation(session, gate, result_status=result, metrics=metrics, reasons=reasons + [f"execution_status:{aggregate}"], valid_reviews=valid_count, distinct_reviews=distinct_count)
            return evaluation

    evaluate = refresh
    recalculate = refresh

    @staticmethod
    def _fixed_for_metrics(root: Path, gate: QualityGate) -> tuple[bytes, bytes, dict[str, Any], dict[str, Any], list[str]]:
        sample_raw, sample = _read_json(root / gate.sample_artifact_path)
        baseline_raw, baseline = _read_json(root / gate.baseline_decisions_path)
        _sample, _baseline, _sample_raw, _baseline_raw, ids = validate_fixed_inputs(root)
        return sample_raw, baseline_raw, sample, baseline, ids

    def _calculate_gate_metrics(
        self,
        *,
        gate: QualityGate,
        execution_a: ScreeningExecution,
        execution_b: ScreeningExecution,
        reviews: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], int, int, list[str]]:
        """Load and validate one authoritative A/B calculation input set.

        Refresh and review PUT deliberately call this same routine.  Every
        execution, input, decision, fixed-file, and review binding is checked
        before a metric is allowed to contribute to a denominator.
        """

        root = Path(self.settings.bidops_root)
        input_a = _load_execution_artifact(root, execution_a.execution_id, "screening-input.json", expected_digest=execution_a.input_artifact_digest)
        input_b = _load_execution_artifact(root, execution_b.execution_id, "screening-input.json", expected_digest=execution_b.input_artifact_digest)
        decisions_a = _load_execution_artifact(root, execution_a.execution_id, "screening-decisions.json")
        decisions_b = _load_execution_artifact(root, execution_b.execution_id, "screening-decisions.json")
        sample_raw, baseline_raw, sample, baseline, ids = self._fixed_for_metrics(root, gate)
        structure: list[str] = []
        input_binding = {}
        for pass_name, execution, input_value in (("A", execution_a, input_a), ("B", execution_b, input_b)):
            input_binding[pass_name] = _input_binding_valid(input_value, execution, sample, ids, expected_source_window=sample.get("source_window"))
            if not input_binding[pass_name]:
                structure.append(f"{pass_name}_input_binding_invalid")
            if not _input_matches_fixed_sample(input_value, sample, ids):
                structure.append(f"{pass_name}_fixed_input_notice_mismatch")
        frozen_mismatch = _canonical_pass_input(input_a) != _canonical_pass_input(input_b)
        if frozen_mismatch:
            structure.append("ab_input_digest_mismatch")
        fixed_digest_mismatch = sha256_bytes(sample_raw) != gate.sample_artifact_digest or sha256_bytes(baseline_raw) != gate.baseline_decisions_digest
        if fixed_digest_mismatch:
            structure.append("input_digest_mismatch")
        binding_issues = _decisions_binding_issues(decisions_a, execution_a, input_a, ids, pass_name="A", expected_source_window=sample.get("source_window"))
        binding_issues.extend(_decisions_binding_issues(decisions_b, execution_b, input_b, ids, pass_name="B", expected_source_window=sample.get("source_window")))
        invalid_by_pass = {
            pass_name: {row["notice_id"] for row in binding_issues if row.get("pass") == pass_name and row.get("notice_id")}
            for pass_name in ("A", "B")
        }
        if not input_binding["A"]:
            invalid_by_pass["A"].update(ids)
        if not input_binding["B"]:
            invalid_by_pass["B"].update(ids)
        if frozen_mismatch or fixed_digest_mismatch:
            invalid_by_pass["A"].update(ids)
            invalid_by_pass["B"].update(ids)

        def valid_decisions(value: Mapping[str, Any], pass_name: str) -> Mapping[str, Any]:
            invalid = invalid_by_pass[pass_name]
            if not invalid or not isinstance(value.get("judgments"), list):
                return value
            filtered = dict(value)
            filtered["judgments"] = [
                item for item in value["judgments"]
                if not isinstance(item, Mapping) or item.get("notice_id") not in invalid
            ]
            return filtered

        metrics = calculate_metrics(
            valid_decisions(decisions_a, "A"), valid_decisions(decisions_b, "B"), baseline=baseline, reviews=reviews,
            sample_ids=ids, expected_sample_count=40, input_a=input_a, input_b=input_b,
        )
        if not input_binding["A"]:
            metrics["excluded_notices"].extend({"notice_id": notice_id, "pass": "A", "reason": "screening_input_binding_invalid"} for notice_id in ids)
        if not input_binding["B"]:
            metrics["excluded_notices"].extend({"notice_id": notice_id, "pass": "B", "reason": "screening_input_binding_invalid"} for notice_id in ids)
        if frozen_mismatch:
            metrics["excluded_notices"].extend(
                {"notice_id": notice_id, "pass": pass_name, "reason": "input_digest_mismatch"}
                for pass_name in ("A", "B") for notice_id in ids
            )
        if fixed_digest_mismatch:
            metrics["excluded_notices"].extend(
                {"notice_id": notice_id, "pass": pass_name, "reason": "fixed_artifact_digest_mismatch"}
                for pass_name in ("A", "B") for notice_id in ids
            )
        metrics["excluded_notices"].extend(binding_issues)
        if binding_issues:
            structure.append("decisions_binding_invalid")
        if any(reason.endswith("fixed_input_notice_mismatch") for reason in structure):
            for pass_name, input_value in (("A", input_a), ("B", input_b)):
                if not _input_matches_fixed_sample(input_value, sample, ids):
                    metrics["excluded_notices"].extend({"notice_id": notice_id, "pass": pass_name, "reason": "fixed_input_notice_mismatch"} for notice_id in ids)
        valid = int((metrics.get("evidence_validity") or {}).get("valid_review_count", 0))
        distinct = int((metrics.get("evidence_validity") or {}).get("distinct_notice_review_count", 0))
        structure.extend(_metric_structure_reasons(metrics))
        return metrics, valid, distinct, list(dict.fromkeys(structure))

    def upsert_review(
        self,
        gate_id: str,
        notice_id: str,
        *,
        reviewer: str,
        evidence_judgment: str,
        decision_digest: str,
        note: str | None = None,
    ) -> QualityGateReview:
        actor = _actor(reviewer)
        if not isinstance(notice_id, str) or not notice_id.strip():
            raise QualityGateValidationError("notice_id is invalid")
        if evidence_judgment not in {"동의", "근거 부족", "판단 보류"}:
            raise QualityGateValidationError("evidence_judgment is invalid")
        if not isinstance(decision_digest, str) or len(decision_digest) != 64 or any(char not in "0123456789abcdef" for char in decision_digest):
            raise QualityGateValidationError("decision_digest is invalid")
        if note is not None and (not isinstance(note, str) or not note.strip()):
            raise QualityGateValidationError("note must be null or nonblank")
        root = Path(self.settings.bidops_root)
        with self._session(immediate=True) as session:
            self._lock_gate(session, gate_id)
            gate, a, b = self._gate_and_rows(session, gate_id)
            if a.status not in EXECUTION_COMPLETED:
                raise QualityGateConflict("pass A is not a completed execution")
            input_a = _load_execution_artifact(root, a.execution_id, "screening-input.json", expected_digest=a.input_artifact_digest)
            decisions_a = _load_execution_artifact(root, a.execution_id, "screening-decisions.json")
            _sample_raw, _baseline_raw, _sample, _baseline, ids = self._fixed_for_metrics(root, gate)
            binding_issues = _decisions_binding_issues(decisions_a, a, input_a, ids, pass_name="A", expected_source_window=_sample.get("source_window"))
            valid_judgments, _ = _judgment_map(
                decisions_a,
                pass_name="A",
                notices={item["notice_id"]: item for item in input_a.get("notices", []) if isinstance(item, Mapping) and isinstance(item.get("notice_id"), str)},
            )
            if notice_id not in ids or notice_id not in valid_judgments or any(row.get("notice_id") == notice_id for row in binding_issues):
                raise QualityGateValidationError("notice is not a pass A judgment")
            # A mismatch is retained as a review row but excluded from the
            # denominator, making the audit trail explicit and reversible.
            previous = session.scalar(select(QualityGateReview).where(QualityGateReview.gate_id == gate_id, QualityGateReview.notice_id == notice_id, QualityGateReview.reviewer == actor))
            before = None if previous is None else {
                "execution_id": previous.execution_id,
                "decision_digest": previous.decision_digest,
                "evidence_judgment": previous.evidence_judgment,
                "note": previous.note,
            }
            if previous is None:
                previous = QualityGateReview(gate_id=gate_id, execution_id=a.execution_id, notice_id=notice_id, decision_digest=decision_digest, reviewer=actor, evidence_judgment=evidence_judgment, note=note, created_at=_now(self.clock()), updated_at=_now(self.clock()))
                session.add(previous)
            else:
                previous.execution_id = a.execution_id
                previous.decision_digest = decision_digest
                previous.evidence_judgment = evidence_judgment
                previous.note = note
                previous.updated_at = _now(self.clock())
            session.flush()
            session.add(AuditEvent(
                event_id="audit-" + uuid4().hex,
                event_type="quality_gate.review_updated",
                actor=actor,
                target_type="quality_gate_review",
                target_id=f"{gate_id}:{notice_id}:{actor}",
                occurred_at=_now(self.clock()),
                details_json={"before": before, "after": {"execution_id": a.execution_id, "decision_digest": decision_digest, "evidence_judgment": evidence_judgment, "note": note}},
            ))
            session.flush()
            # A review update creates a revision even when its value is the
            # same; the review PUT itself is an immutable evaluation event.
            aggregate = _status_for_executions(a.status, b.status)
            reviews = self._reviews(session, gate_id)
            if aggregate == "완료":
                try:
                    metrics, valid, distinct, structure = self._calculate_gate_metrics(
                        gate=gate, execution_a=a, execution_b=b, reviews=reviews,
                    )
                    result, reasons = _result_for_metrics(execution_status=aggregate, metrics=metrics, valid_review_count=valid, distinct_notice_review_count=distinct, structure_reasons=structure)
                except Exception:
                    metrics = gate.metrics_json if isinstance(gate.metrics_json, dict) else {}
                    valid = sum(row.get("evidence_judgment") in {"동의", "근거 부족"} for row in reviews)
                    distinct = len({row.get("notice_id") for row in reviews if row.get("evidence_judgment") in {"동의", "근거 부족"}})
                    result, reasons = _result_for_metrics(
                        execution_status=aggregate, metrics=metrics,
                        valid_review_count=valid, distinct_notice_review_count=distinct,
                        structure_reasons=["calculation_impossible"],
                    )
            else:
                metrics, valid, distinct, result, reasons = gate.metrics_json, 0, 0, "미측정", ["execution_not_terminal"]
            self._append_evaluation(session, gate, result_status=result, metrics=metrics, reasons=reasons + ["review_updated"], valid_reviews=valid, distinct_reviews=distinct, force=True)
            return previous

    review = upsert_review

    @staticmethod
    def _judgments_by_id(decisions: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
        values = decisions.get("judgments")
        if not isinstance(values, list):
            raise QualityGateValidationError("decisions judgments are missing")
        result: dict[str, Mapping[str, Any]] = {}
        for value in values:
            if isinstance(value, Mapping) and isinstance(value.get("notice_id"), str):
                result[value["notice_id"]] = value
        return result, []

    def latest_evaluation(self, gate_id: str) -> QualityGateEvaluation:
        with self._session() as session:
            return self._latest(session, gate_id)

    def can_activate(
        self,
        evaluation_id: str,
        *,
        policy_version: str | None = None,
        prompt_version: str | None = None,
        model_name: str | None = None,
        model_digest: str | None = None,
        company_profile_version: str | None = None,
        company_profile_digest: str | None = None,
    ) -> bool:
        """Check a point-in-time activation authority with a coherent lock."""

        with self._session(immediate=True) as session:
            return self.validate_activation_in_session(
                session, evaluation_id, policy_version=policy_version,
                prompt_version=prompt_version, model_name=model_name,
                model_digest=model_digest, company_profile_version=company_profile_version,
                company_profile_digest=company_profile_digest,
            )

    @staticmethod
    def validate_activation_in_session(
        session: Session,
        evaluation_id: str,
        *,
        policy_version: str | None = None,
        prompt_version: str | None = None,
        model_name: str | None = None,
        model_digest: str | None = None,
        company_profile_version: str | None = None,
        company_profile_digest: str | None = None,
    ) -> bool:
        """Validate activation while holding the gate row lock.

        Policy activation calls this inside its own transaction.  Review
        updates take the same lock before calculation, so no newer revision
        can commit between this check and the policy flush/commit.
        """

        evaluation = session.scalar(select(QualityGateEvaluation).where(QualityGateEvaluation.evaluation_id == evaluation_id))
        if evaluation is None:
            raise QualityGateActivationError("quality evaluation was not found")
        gate = session.scalar(select(QualityGate).where(QualityGate.gate_id == evaluation.gate_id).with_for_update())
        if gate is None or gate.purpose != "operational_approval":
            raise QualityGateActivationError("only operational approval can activate")
        latest = session.scalar(
            select(QualityGateEvaluation)
            .where(QualityGateEvaluation.gate_id == gate.gate_id)
            .order_by(QualityGateEvaluation.revision.desc())
            .limit(1)
        )
        if (
            latest is None or latest.evaluation_id != evaluation_id
            or latest.result_status != "통과" or gate.result_status != "통과"
            or gate.execution_status != "완료"
        ):
            raise QualityGateActivationError("evaluation is not the latest passing result")
        if policy_version is not None and gate.policy_version != policy_version:
            raise QualityGateActivationError("policy identity does not match quality gate")
        if prompt_version is not None and gate.prompt_version != prompt_version:
            raise QualityGateActivationError("prompt identity does not match quality gate")
        if model_name is not None and gate.model_name != model_name:
            raise QualityGateActivationError("model identity does not match quality gate")
        if model_digest is not None and gate.model_digest != model_digest:
            raise QualityGateActivationError("model digest does not match quality gate")
        if company_profile_version is not None and gate.company_profile_version != company_profile_version:
            raise QualityGateActivationError("profile identity does not match quality gate")
        if company_profile_digest is not None and gate.company_profile_digest != company_profile_digest:
            raise QualityGateActivationError("profile digest does not match quality gate")
        return True

    validate_activation = can_activate
    validate_latest_evaluation = can_activate


# Compatibility names make the service discoverable to the T9 API layer.
QualityGateRepository = QualityGateService
QualityGateManager = QualityGateService
QualityGateStore = QualityGateService
create_quality_gate = QualityGateService.create_gate


__all__ = [
    "FIXED_BASELINE_RELATIVE",
    "FIXED_RUN_ID",
    "FIXED_SAMPLE_RELATIVE",
    "FIXED_SOURCE_WINDOW",
    "QualityGateActivationError",
    "QualityGateConflict",
    "QualityGateError",
    "QualityGateService",
    "QualityGateValidationError",
    "QualityGateRepository",
    "QualityGateStore",
    "create_quality_gate",
    "validate_fixed_inputs",
]
