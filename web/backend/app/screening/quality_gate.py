"""Persistence and orchestration boundary for model-quality gates.

Gate creation validates the immutable 40-notice input before touching the
database.  The two passes are ordinary ``quality_sample`` executions and are
therefore subject to the same FIFO worker as every other Qwen call.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4

from sqlalchemy import Engine, func, select
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
from .artifacts import ArtifactError, ArtifactStore, sha256_bytes
from .execution_store import ScreeningExecutionStore
from .orchestrator import CreatedExecution, ScreeningCreationError, ScreeningOrchestrator
from .profile_snapshot import BASELINE_COMMIT
from .quality_metrics import (
    QualityMetricError,
    calculate_metrics,
    frozen_input_digest,
    judgment_digest,
    required_metrics_pass,
)


FIXED_RUN_ID = "20260817-20260823"
FIXED_SAMPLE_RELATIVE = "data/runs/20260817-20260823/validation-set.json"
FIXED_BASELINE_RELATIVE = "data/runs/20260817-20260823/screening-decisions.json"
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


class _StagedQualityQueue:
    """Capture orchestrator queue rows until the gate transaction is ready.

    ``ScreeningOrchestrator`` owns all expensive preflight work and artifact
    construction, but its normal queue commits one row per call.  Quality
    gates need a different visibility boundary: both rows and the gate must
    become visible together.  This narrow adapter preserves the orchestrator
    contract while keeping its generated IDs/artifact bindings for one final
    transaction.
    """

    def __init__(self) -> None:
        self.rows: list[ScreeningExecution] = []

    def enqueue(self, **kwargs: Any) -> ScreeningExecution:
        row = ScreeningExecution(
            execution_id=kwargs["execution_id"],
            trigger=kwargs["trigger"],
            source_run_id=kwargs["source_run_id"],
            scope=kwargs["scope"],
            notice_pk=kwargs.get("notice_pk"),
            notice_id=kwargs.get("notice_id"),
            status="대기",
            requested_by=kwargs["requested_by"],
            policy_version=kwargs["policy_version"],
            prompt_version=kwargs["prompt_version"],
            model_name=kwargs["model_name"],
            model_digest=kwargs["model_digest"],
            company_profile_version=kwargs["company_profile_version"],
            company_profile_digest=kwargs["company_profile_digest"],
            input_artifact_path=kwargs["input_artifact_path"],
            input_artifact_digest=kwargs["input_artifact_digest"],
            artifact_dir=kwargs["artifact_dir"],
            queued_at=kwargs.get("queued_at") or datetime.now(timezone.utc),
            candidate_count=kwargs.get("candidate_count", 0),
            completed_count=0,
            failure_count=0,
        )
        self.rows.append(row)
        return row


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


def _load_execution_artifact(root: Path, execution_id: str, filename: str) -> dict[str, Any]:
    try:
        value = ArtifactStore(root).read_json(execution_id, filename)
    except ArtifactError as exc:
        raise QualityGateValidationError("quality execution artifact is unavailable") from exc
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
        clock: Any | None = None,
        busy_retries: int = 5,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = _factory(session_factory)
        self.orchestrator = orchestrator or ScreeningOrchestrator(settings=self.settings, session_factory=self.session_factory)
        self.queue = queue or ScreeningExecutionStore(session_factory=self.session_factory, settings=self.settings)
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

    def _create_pass(self, *, run_id: str, policy_version: str, profile_source: str, actor: str) -> CreatedExecution:
        try:
            return self.orchestrator.create_execution(
                run_id=run_id,
                policy_version=policy_version,
                profile_source=profile_source,
                requested_by=actor,
                scope="quality_sample",
                trigger="quality_gate",
            )
        except (ScreeningCreationError, QualityGateError):
            raise
        except Exception as exc:
            raise QualityGateError("quality pass could not be queued") from exc

    def _create_staged_passes(
        self,
        *,
        run_id: str,
        policy_version: str,
        profile_source: str,
        actor: str,
    ) -> tuple[CreatedExecution, CreatedExecution, list[ScreeningExecution], list[str]]:
        """Run both orchestrator preflights without publishing queue rows."""

        staged = _StagedQualityQueue()
        original_queue = getattr(self.orchestrator, "queue", None)
        if original_queue is None:
            raise QualityGateConflict("quality orchestrator has no queue boundary")
        self.orchestrator.queue = staged
        created_ids: list[str] = []
        try:
            first = self._create_pass(run_id=run_id, policy_version=policy_version, profile_source=profile_source, actor=actor)
            created_ids.append(first.execution_id)
            second = self._create_pass(run_id=run_id, policy_version=policy_version, profile_source=profile_source, actor=actor)
            created_ids.append(second.execution_id)
            if len(staged.rows) != 2 or first.execution_id == second.execution_id:
                raise QualityGateConflict("quality passes must be independent")
            return first, second, list(staged.rows), created_ids
        finally:
            self.orchestrator.queue = original_queue

    def _cleanup_staged_artifacts(self, execution_ids: Sequence[str]) -> None:
        """Remove only known, never-queued execution staging directories."""

        store = ArtifactStore(Path(self.settings.bidops_root))
        for execution_id in dict.fromkeys(execution_ids):
            try:
                store.remove_execution(execution_id)
            except (ArtifactError, OSError):
                # A failed preflight may not have created its directory.  No
                # database row was published, and an absent path is already
                # the desired state.
                continue

    def _cleanup_unbound_passes(self, execution_ids: Sequence[str]) -> None:
        """Rollback compatibility-adapter rows before removing their files."""

        ids = list(dict.fromkeys(execution_ids))
        if not ids:
            return
        try:
            with self._session(immediate=True) as session:
                rows = session.scalars(select(ScreeningExecution).where(ScreeningExecution.execution_id.in_(ids))).all()
                for row in rows:
                    # A gate never owns a partially-running compatibility row;
                    # leave a worker-owned row for its normal lifecycle rather
                    # than deleting active runtime history.
                    if row.status != "대기":
                        continue
                    session.delete(row)
        finally:
            self._cleanup_staged_artifacts(ids)

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

        # The orchestrator performs model inspection, profile snapshot, and
        # artifact creation.  Its normal queue commits one row immediately;
        # the production implementation is intercepted until both passes are
        # ready, so no worker can claim A while B is being built.
        root = Path(self.settings.bidops_root)
        staged_rows: list[ScreeningExecution] = []
        created_ids: list[str] = []
        try:
            if isinstance(self.orchestrator, ScreeningOrchestrator):
                first, second, staged_rows, created_ids = self._create_staged_passes(
                    run_id=run_id, policy_version=policy_version, profile_source=profile_source, actor=actor
                )
            else:
                # Keep compatibility with injected test/delivery adapters;
                # their queue can be an externally managed transaction-aware
                # implementation.  Any rows they publish are still cleaned
                # by the adapter on a failed logical operation.
                first = self._create_pass(run_id=run_id, policy_version=policy_version, profile_source=profile_source, actor=actor)
                created_ids.append(first.execution_id)
                second = self._create_pass(run_id=run_id, policy_version=policy_version, profile_source=profile_source, actor=actor)
                created_ids.append(second.execution_id)
                if first.execution_id == second.execution_id:
                    raise QualityGateConflict("quality passes must be independent")

            input_a = _load_execution_artifact(root, first.execution_id, "screening-input.json")
            input_b = _load_execution_artifact(root, second.execution_id, "screening-input.json")
            if _canonical_pass_input(input_a) != _canonical_pass_input(input_b):
                raise QualityGateConflict("quality pass frozen input combination differs")
            if input_a.get("candidate_count") != 40 or input_b.get("candidate_count") != 40:
                raise QualityGateValidationError("quality pass must contain exactly 40 notices")
            if not _input_matches_fixed_sample(input_a, sample, sample_ids) or not _input_matches_fixed_sample(input_b, sample, sample_ids):
                raise QualityGateConflict("quality pass notices do not match the fixed sample")
            # The fixed raw bytes, rather than a parsed/reformatted value, are
            # the authoritative input identity stored on the gate.
            sample_digest = sha256_bytes(sample_raw)
            baseline_digest = sha256_bytes(baseline_raw)
            now = _now(self.clock())
            gate_id = "gate-" + uuid4().hex
            with self._session(immediate=True) as session:
                # Recheck all immutable identities in the same transaction as
                # the gate row, so a concurrent policy/profile change cannot
                # bind a different combination.
                policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == policy_version))
                if staged_rows:
                    session.add_all(staged_rows)
                    session.flush()
                execution_a = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == first.execution_id))
                execution_b = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == second.execution_id))
                if policy is None or execution_a is None or execution_b is None:
                    raise QualityGateConflict("quality pass rows disappeared")
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
                    gate_id=gate_id,
                    purpose=purpose,
                    execution_status="대기",
                    result_status="미측정",
                    baseline_run_id=run_id,
                    sample_artifact_path=_safe_relative(FIXED_SAMPLE_RELATIVE),
                    sample_artifact_digest=sample_digest,
                    baseline_decisions_path=_safe_relative(FIXED_BASELINE_RELATIVE),
                    baseline_decisions_digest=baseline_digest,
                    policy_version=policy_version,
                    prompt_version=execution_a.prompt_version,
                    model_name=execution_a.model_name,
                    model_digest=execution_a.model_digest,
                    company_profile_version=execution_a.company_profile_version,
                    company_profile_digest=execution_a.company_profile_digest,
                    pass_a_execution_id=first.execution_id,
                    pass_b_execution_id=second.execution_id,
                    created_by=actor,
                    created_at=now,
                    completed_at=None,
                    metrics_json=_initial_metrics(sample_ids),
                    reasons_json=["execution_pending"],
                )
                session.add(gate)
                session.flush()
                session.add(QualityGateEvaluation(
                    evaluation_id=_evaluation_id(), gate_id=gate_id, revision=1,
                    result_status="미측정", metrics_json=gate.metrics_json,
                    reasons_json=["execution_pending"], valid_review_count=0,
                    distinct_notice_review_count=0, created_at=now,
                ))
                session.add(AuditEvent(
                    event_id="audit-" + uuid4().hex,
                    event_type="quality_gate.created",
                    actor=actor,
                    target_type="quality_gate",
                    target_id=gate_id,
                    occurred_at=now,
                    details_json={
                        "purpose": purpose,
                        "policy_version": policy_version,
                        "prompt_version": execution_a.prompt_version,
                        "model_name": execution_a.model_name,
                        "model_digest": execution_a.model_digest,
                        "company_profile_version": execution_a.company_profile_version,
                        "company_profile_digest": execution_a.company_profile_digest,
                        "sample_artifact_digest": sample_digest,
                        "baseline_decisions_digest": baseline_digest,
                        "pass_a_execution_id": first.execution_id,
                        "pass_b_execution_id": second.execution_id,
                    },
                ))
                session.flush()
                return gate
        except Exception:
            # Staged IDs are never queue-visible.  Cleanup is narrowly scoped
            # to those generated execution directories and therefore cannot
            # delete an unrelated caller artifact.
            if staged_rows or isinstance(self.orchestrator, ScreeningOrchestrator):
                self._cleanup_staged_artifacts(created_ids)
            else:
                self._cleanup_unbound_passes(created_ids)
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

        root = Path(self.settings.bidops_root)
        with self._session(immediate=True) as session:
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
                    input_a = _load_execution_artifact(root, a.execution_id, "screening-input.json")
                    input_b = _load_execution_artifact(root, b.execution_id, "screening-input.json")
                    decisions_a = _load_execution_artifact(root, a.execution_id, "screening-decisions.json")
                    decisions_b = _load_execution_artifact(root, b.execution_id, "screening-decisions.json")
                    sample_raw, baseline_raw, sample, baseline, ids = self._fixed_for_metrics(root, gate)
                    structure: list[str] = []
                    if input_a.get("execution_id") != a.execution_id or input_b.get("execution_id") != b.execution_id:
                        structure.append("execution_identity_mismatch")
                    if input_a.get("run_id") != gate.baseline_run_id or input_b.get("run_id") != gate.baseline_run_id:
                        structure.append("run_identity_mismatch")
                    if not _input_matches_fixed_sample(input_a, sample, ids) or not _input_matches_fixed_sample(input_b, sample, ids):
                        structure.append("fixed_input_notice_mismatch")
                    if any(
                        value.get("policy_version") != gate.policy_version
                        or value.get("prompt_version") != gate.prompt_version
                        or value.get("company_profile_version") != gate.company_profile_version
                        or value.get("company_profile_digest") != gate.company_profile_digest
                        for value in (input_a, input_b)
                    ):
                        structure.append("metadata_identity_mismatch")
                    for value, execution in ((decisions_a, a), (decisions_b, b)):
                        if (
                            value.get("execution_id") != execution.execution_id
                            or value.get("run_id") != gate.baseline_run_id
                            or value.get("model_name") != gate.model_name
                            or value.get("model_digest") != gate.model_digest
                            or value.get("prompt_version") != gate.prompt_version
                            or value.get("policy_version") != gate.policy_version
                            or value.get("company_profile_version") != gate.company_profile_version
                            or value.get("company_profile_digest") != gate.company_profile_digest
                        ):
                            structure.append("decision_metadata_mismatch")
                    if _canonical_pass_input(input_a) != _canonical_pass_input(input_b):
                        structure.append("ab_input_digest_mismatch")
                    if sha256_bytes(sample_raw) != gate.sample_artifact_digest or sha256_bytes(baseline_raw) != gate.baseline_decisions_digest:
                        structure.append("input_digest_mismatch")
                    metrics = calculate_metrics(decisions_a, decisions_b, baseline=baseline, reviews=reviews, sample_ids=ids, expected_sample_count=40, input_a=input_a, input_b=input_b)
                    if "fixed_input_notice_mismatch" in structure:
                        for pass_name, value in (("A", input_a), ("B", input_b)):
                            if not _input_matches_fixed_sample(value, sample, ids):
                                metrics["excluded_notices"].extend(
                                    {"notice_id": notice_id, "pass": pass_name, "reason": "fixed_input_notice_mismatch"}
                                    for notice_id in ids
                                )
                    if "ab_input_digest_mismatch" in structure:
                        metrics["excluded_notices"].extend(
                            {"notice_id": notice_id, "pass": pass_name, "reason": "input_digest_mismatch"}
                            for pass_name in ("A", "B") for notice_id in ids
                        )
                    if "metadata_identity_mismatch" in structure:
                        metrics["excluded_notices"].extend(
                            {"notice_id": notice_id, "pass": pass_name, "reason": "metadata_identity_mismatch"}
                            for pass_name in ("A", "B") for notice_id in ids
                        )
                    if "decision_metadata_mismatch" in structure:
                        metrics["excluded_notices"].extend(
                            {"notice_id": notice_id, "pass": pass_name, "reason": "decision_metadata_mismatch"}
                            for pass_name in ("A", "B") for notice_id in ids
                        )
                    valid_count = int((metrics.get("evidence_validity") or {}).get("valid_review_count", 0))
                    distinct_count = int((metrics.get("evidence_validity") or {}).get("distinct_notice_review_count", 0))
                    structure.extend(_metric_structure_reasons(metrics))
                    result, reasons = _result_for_metrics(execution_status=aggregate, metrics=metrics, valid_review_count=valid_count, distinct_notice_review_count=distinct_count, structure_reasons=structure)
                except (QualityGateError, ArtifactError, QualityMetricError, KeyError, TypeError, ValueError):
                    metrics = gate.metrics_json if isinstance(gate.metrics_json, dict) else {}
                    valid_count = 0
                    distinct_count = 0
                    result, reasons = "보류", ["calculation_impossible"]
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
            gate, a, _b = self._gate_and_rows(session, gate_id)
            if a.status not in EXECUTION_COMPLETED:
                raise QualityGateConflict("pass A is not a completed execution")
            decisions = _load_execution_artifact(root, a.execution_id, "screening-decisions.json")
            judgments, _ = self._judgments_by_id(decisions)
            judgment = judgments.get(notice_id)
            if judgment is None:
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
            aggregate = _status_for_executions(a.status, _b.status)
            reviews = self._reviews(session, gate_id)
            if aggregate == "완료":
                try:
                    decisions_b = _load_execution_artifact(root, _b.execution_id, "screening-decisions.json")
                    _sample, baseline, _sample_raw, _baseline_raw, ids = validate_fixed_inputs(root)
                    decisions_a = decisions
                    metrics = calculate_metrics(decisions_a, decisions_b, baseline=baseline, reviews=reviews, sample_ids=ids, expected_sample_count=40)
                    valid = int((metrics.get("evidence_validity") or {}).get("valid_review_count", 0))
                    distinct = int((metrics.get("evidence_validity") or {}).get("distinct_notice_review_count", 0))
                    result, reasons = _result_for_metrics(execution_status=aggregate, metrics=metrics, valid_review_count=valid, distinct_notice_review_count=distinct, structure_reasons=_metric_structure_reasons(metrics))
                except Exception:
                    metrics, valid, distinct, result, reasons = gate.metrics_json, 0, 0, "보류", ["calculation_impossible"]
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
        """Return whether an immutable evaluation is an activation authority."""

        with self._session() as session:
            evaluation = session.scalar(select(QualityGateEvaluation).where(QualityGateEvaluation.evaluation_id == evaluation_id))
            if evaluation is None:
                raise QualityGateActivationError("quality evaluation was not found")
            gate = session.scalar(select(QualityGate).where(QualityGate.gate_id == evaluation.gate_id))
            if gate is None or gate.purpose != "operational_approval":
                raise QualityGateActivationError("only operational approval can activate")
            latest = self._latest(session, gate.gate_id)
            if latest.evaluation_id != evaluation_id or evaluation.result_status != "통과" or gate.execution_status != "완료":
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
