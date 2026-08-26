"""Persistence and orchestration boundary for model-quality gates.

Gate creation validates the immutable 40-notice input before touching the
database.  The two passes are ordinary ``quality_sample`` executions and are
therefore subject to the same FIFO worker as every other Qwen call.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session, selectinload, sessionmaker

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
    Notice,
    Judgment,
    Perspective,
)
from .artifacts import ArtifactError, ArtifactStore, ExecutionWorkspace, sha256_bytes
from ..ingest.loader import deterministic_run_id
from .generation_config import GenerationConfigError, config_from_value, legacy_generation_config, validate_digest
from .execution_store import ScreeningExecutionStore
from .orchestrator import (
    ScreeningCreationError,
    ScreeningOrchestrator,
    _make_quality_sample_binding,
)
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
FIXED_RESULTS_RELATIVE = "data/runs/20260817-20260823/screening-results.json"
# These are the byte-level identities of the reviewed, historical inputs.  A
# JSON re-serialization is not equivalent: whitespace, ordering, and Unicode
# escaping are all part of the frozen evidence contract.
FIXED_SAMPLE_DIGEST = "2ea6a21e6b121f691195bbc891b8ec7766817f821d6b343c20b12b608f3e47e3"
FIXED_BASELINE_DIGEST = "69a444e5ec9846c592de4b454472817477abaa4a109c97dbe84787dff9c6789d"
FIXED_RESULTS_DIGEST = "fb9160602771ff057b708d69b197b9fc7e464f9e021615a7ebaa83a94733903b"
FIXED_SOURCE_WINDOW = {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"}
PURPOSES = frozenset({"model_comparison", "operational_approval"})
EXECUTION_TERMINAL = frozenset({"성공", "부분 성공", "실패", "중단됨"})
EXECUTION_COMPLETED = frozenset({"성공", "부분 성공"})
RESULT_STATUSES = frozenset({"통과", "미달", "미측정", "보류"})
FIXED_SAMPLE_ROLES = frozenset({"analysis", "audit"})
FIXED_SAMPLE_STRATA = frozenset({"AI/데이터", "블록체인·DID", "공공 SI·통합관리", "수행실적 유사", "분류 근접", "실적 유사 근접", "무작위"})


class QualityGateError(RuntimeError):
    """Base class for safe gate errors."""


class QualityGateValidationError(QualityGateError, ScreeningCreationError):
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


@dataclass(frozen=True)
class _FixedInputSnapshot:
    """One trusted, immutable raw/parsed snapshot of all fixed inputs."""

    root: Path
    sample: dict[str, Any]
    baseline: dict[str, Any]
    results: dict[str, Any]
    sample_raw: bytes
    baseline_raw: bytes
    results_raw: bytes
    sample_digest: str
    baseline_digest: str
    results_digest: str
    ids: tuple[str, ...]
    token: object


_FIXED_SNAPSHOT_TOKEN = object()


FIXED_INPUT_MAX_BYTES = 8 * 1024 * 1024
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _absolute_root(project_root: Path | str) -> Path:
    root = Path(project_root)
    if not root.is_absolute():
        root = Path(os.path.abspath(root))
    return root


def _open_trusted_root(project_root: Path | str) -> tuple[int, Path]:
    """Open the configured root without following its final symlink."""

    root = _absolute_root(project_root)
    root_fd: int | None = None
    try:
        root_fd = os.open(str(root), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC)
        root_stat = os.fstat(root_fd)
    except OSError:
        if root_fd is not None:
            try:
                os.close(root_fd)
            except OSError:
                pass
        raise QualityGateValidationError("fixed quality input is invalid") from None
    if not stat.S_ISDIR(root_stat.st_mode):
        os.close(root_fd)
        raise QualityGateValidationError("fixed quality input is invalid")
    return root_fd, root


def _open_fixed_relative(root_fd: int, relative: str) -> int:
    """Open a fixed relative file through directory FDs and no-follow flags."""

    path = Path(relative)
    parts = path.parts
    if not parts or path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise QualityGateValidationError("fixed quality input is invalid")
    parent_fd = root_fd
    opened_dirs: list[int] = []
    try:
        for component in parts[:-1]:
            child_fd = os.open(
                component,
                os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                dir_fd=parent_fd,
            )
            opened_dirs.append(child_fd)
            parent_fd = child_fd
        final_fd = os.open(
            parts[-1], os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC, dir_fd=parent_fd
        )
        final_stat = os.fstat(final_fd)
        if not stat.S_ISREG(final_stat.st_mode):
            os.close(final_fd)
            raise QualityGateValidationError("fixed quality input is invalid")
        return final_fd
    except OSError:
        raise QualityGateValidationError("fixed quality input is invalid") from None
    finally:
        for descriptor in reversed(opened_dirs):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _read_bounded_fd(file_fd: int) -> bytes:
    try:
        initial_size = os.fstat(file_fd).st_size
        if initial_size < 0 or initial_size > FIXED_INPUT_MAX_BYTES:
            raise QualityGateValidationError("fixed quality input is invalid")
        chunks: list[bytes] = []
        total = 0
        while total <= FIXED_INPUT_MAX_BYTES:
            chunk = os.read(file_fd, min(1024 * 1024, FIXED_INPUT_MAX_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > FIXED_INPUT_MAX_BYTES:
            raise QualityGateValidationError("fixed quality input is invalid")
        return b"".join(chunks)
    except OSError:
        raise QualityGateValidationError("fixed quality input is invalid") from None


def _read_pinned_json_fd(root_fd: int, relative: str, expected_digest: str) -> tuple[bytes, dict[str, Any]]:
    """Read one pinned artifact through a secure FD with a bounded size."""

    file_fd = _open_fixed_relative(root_fd, relative)
    try:
        raw = _read_bounded_fd(file_fd)
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise QualityGateValidationError("fixed quality input is invalid") from None
    finally:
        try:
            os.close(file_fd)
        except OSError:
            pass
    if sha256_bytes(raw) != expected_digest or not isinstance(value, dict):
        raise QualityGateValidationError("fixed quality input is invalid")
    return raw, value


def _validate_fixed_shape(
    sample: Mapping[str, Any], baseline: Mapping[str, Any], results: Mapping[str, Any]
) -> list[str]:
    """Validate the closed, historical three-file source contract."""

    if set(sample) != {"schema_version", "source_window", "selection", "warnings", "notices"}:
        raise QualityGateValidationError("fixed quality input is invalid")
    if sample.get("schema_version") != "bidops.validation-set.v2" or sample.get("source_window") != FIXED_SOURCE_WINDOW:
        raise QualityGateValidationError("fixed quality input is invalid")
    notices = sample.get("notices")
    if not isinstance(notices, list) or len(notices) != 40:
        raise QualityGateValidationError("fixed quality input is invalid")
    ids: list[str] = []
    for item in notices:
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("notice_id"), str)
            or not item["notice_id"].strip()
            or not isinstance(item.get("sample_stratum"), str)
            or item["sample_stratum"] not in FIXED_SAMPLE_STRATA
            or not isinstance(item.get("sample_role"), str)
            or item["sample_role"] not in FIXED_SAMPLE_ROLES
        ):
            raise QualityGateValidationError("fixed quality input is invalid")
        ids.append(item["notice_id"])
    if len(set(ids)) != 40:
        raise QualityGateValidationError("fixed quality input is invalid")

    if set(baseline) != {"schema_version", "screening_basis", "judgments"} or baseline.get("schema_version") != "bidops.decisions.v2":
        raise QualityGateValidationError("fixed quality input is invalid")
    judgments = baseline.get("judgments")
    baseline_ids: list[str] = []
    if not isinstance(judgments, list) or len(judgments) != 40:
        raise QualityGateValidationError("fixed quality input is invalid")
    for item in judgments:
        if not isinstance(item, Mapping) or not isinstance(item.get("notice_id"), str) or not item["notice_id"].strip():
            raise QualityGateValidationError("fixed quality input is invalid")
        baseline_ids.append(item["notice_id"])
    if baseline_ids != ids or len(set(baseline_ids)) != 40:
        raise QualityGateValidationError("fixed quality input is invalid")

    if set(results) != {"schema_version", "generated_at", "screening_basis", "source_window", "results"}:
        raise QualityGateValidationError("fixed quality input is invalid")
    if results.get("schema_version") != "bidops.screening.v2" or results.get("source_window") != FIXED_SOURCE_WINDOW:
        raise QualityGateValidationError("fixed quality input is invalid")
    generated_at = results.get("generated_at")
    try:
        parsed = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise QualityGateValidationError("fixed quality input is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QualityGateValidationError("fixed quality input is invalid")
    result_rows = results.get("results")
    if not isinstance(result_rows, list) or len(result_rows) != 40:
        raise QualityGateValidationError("fixed quality input is invalid")
    result_ids: list[str] = []
    for row in result_rows:
        if not isinstance(row, Mapping) or set(row) != {"notice", "judgment"} or not isinstance(row.get("notice"), Mapping) or not isinstance(row.get("judgment"), Mapping):
            raise QualityGateValidationError("fixed quality input is invalid")
        notice_id = row["notice"].get("notice_id")
        if not isinstance(notice_id, str) or not notice_id.strip():
            raise QualityGateValidationError("fixed quality input is invalid")
        result_ids.append(notice_id)
    if result_ids != ids:
        raise QualityGateValidationError("fixed quality input is invalid")
    return ids


def _read_strict_fixed_snapshot(project_root: Path | str) -> _FixedInputSnapshot:
    """Read and validate all fixed files as one reusable immutable snapshot."""

    root_fd, root = _open_trusted_root(project_root)
    try:
        sample_raw, sample = _read_pinned_json_fd(root_fd, FIXED_SAMPLE_RELATIVE, FIXED_SAMPLE_DIGEST)
        baseline_raw, baseline = _read_pinned_json_fd(root_fd, FIXED_BASELINE_RELATIVE, FIXED_BASELINE_DIGEST)
        results_raw, results = _read_pinned_json_fd(root_fd, FIXED_RESULTS_RELATIVE, FIXED_RESULTS_DIGEST)
    finally:
        try:
            os.close(root_fd)
        except OSError:
            pass
    ids = _validate_fixed_shape(sample, baseline, results)
    return _FixedInputSnapshot(
        root=root, sample=sample, baseline=baseline, results=results,
        sample_raw=sample_raw, baseline_raw=baseline_raw, results_raw=results_raw,
        sample_digest=FIXED_SAMPLE_DIGEST, baseline_digest=FIXED_BASELINE_DIGEST,
        results_digest=FIXED_RESULTS_DIGEST,
        ids=tuple(ids),
        token=_FIXED_SNAPSHOT_TOKEN,
    )


def _read_strict_fixed_inputs(project_root: Path | str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes, bytes, bytes, list[str]]:
    snapshot = _read_strict_fixed_snapshot(project_root)
    return (
        snapshot.sample, snapshot.baseline, snapshot.results,
        snapshot.sample_raw, snapshot.baseline_raw, snapshot.results_raw,
        list(snapshot.ids),
    )


def validate_fixed_inputs(
    project_root: Path | str, *, strict: bool = False
) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes, list[str]]:
    """Validate the fixed sample and Claude baseline before DB writes.

    ``strict=True`` is used by quality gates and additionally verifies the
    trusted results artifact, path components, closed schemas, and all three
    pinned byte digests.  The small compatibility mode keeps the historical
    importer-facing helper useful for synthetic unit fixtures; it is never a
    gate preflight.
    """

    if strict:
        snapshot = _read_strict_fixed_snapshot(project_root)
        return snapshot.sample, snapshot.baseline, snapshot.sample_raw, snapshot.baseline_raw, list(snapshot.ids)
    root = Path(project_root).resolve()
    sample_raw, sample = _read_json(root / FIXED_SAMPLE_RELATIVE)
    baseline_raw, baseline = _read_json(root / FIXED_BASELINE_RELATIVE)
    if sample.get("schema_version") != "bidops.validation-set.v2":
        raise QualityGateValidationError("validation sample schema is invalid")
    notices = sample.get("notices")
    if not isinstance(notices, list) or len(notices) != 40:
        raise QualityGateValidationError("validation sample must contain exactly 40 notices")
    if sample.get("source_window") != FIXED_SOURCE_WINDOW:
        raise QualityGateValidationError("validation sample source window is invalid")
    ids: list[str] = []
    for item in notices:
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("notice_id"), str)
            or not item["notice_id"].strip()
            or not isinstance(item.get("sample_stratum"), str)
            or item["sample_stratum"] not in FIXED_SAMPLE_STRATA
            or not isinstance(item.get("sample_role"), str)
            or item["sample_role"] not in FIXED_SAMPLE_ROLES
        ):
            raise QualityGateValidationError("validation notice identity is invalid")
        ids.append(item["notice_id"])
    if len(set(ids)) != 40 or baseline.get("schema_version") != "bidops.decisions.v2":
        raise QualityGateValidationError("fixed quality input is invalid")
    judgments = baseline.get("judgments")
    baseline_ids = [item.get("notice_id") for item in judgments] if isinstance(judgments, list) else []
    if len(baseline_ids) != 40 or baseline_ids != ids or len(set(baseline_ids)) != 40:
        raise QualityGateValidationError("validation and Claude baseline notice correspondence is invalid")
    return sample, baseline, sample_raw, baseline_raw, ids


def _canonical_pass_input(value: Mapping[str, Any]) -> str:
    try:
        return frozen_input_digest(value)
    except (QualityMetricError, ArtifactError):
        raise QualityGateValidationError("quality pass input is invalid") from None


def _validated_generation_binding(row: ScreeningExecution | QualityGate) -> tuple[Any, str]:
    """Return canonical persisted config and its verified digest."""

    try:
        config = config_from_value(getattr(row, "generation_config_json", None))
        digest = validate_digest(config, getattr(row, "generation_config_digest", None))
    except (GenerationConfigError, TypeError, ValueError):
        raise QualityGateValidationError("generation config binding is invalid") from None
    if getattr(row, "generation_config_json", None) != config.canonical_value():
        raise QualityGateValidationError("generation config is not canonical")
    return config, digest


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


_FIXED_RUN_ELIGIBLE_STATUSES = frozenset({"active", "complete", "성공", "부분 성공"})


def _fixed_run_load_options() -> tuple[Any, ...]:
    """Eagerly load the complete fixed projection used by the resolver."""

    notices = selectinload(Run.notices)
    judgment = notices.selectinload(Notice.judgment)
    perspectives = judgment.selectinload(Judgment.perspectives)
    return (
        notices.selectinload(Notice.attachments),
        perspectives.selectinload(Perspective.evidence),
        judgment.selectinload(Judgment.counterarguments),
        judgment.selectinload(Judgment.verification_items),
        judgment.selectinload(Judgment.matched_performances),
    )


def _identity_datetime(value: Any) -> str | None:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _identity_decimal(value: Any) -> str | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not parsed.is_finite():
        return None
    normalized = format(parsed, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _identity_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _identity_decimal(value)
    if isinstance(value, datetime):
        return _identity_datetime(value)
    if isinstance(value, Mapping):
        return {key: _identity_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_identity_value(item) for item in value]
    return value


def _normalized_fixed_notice(value: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: _identity_value(value.get(key)) for key in (
        "notice_id", "source_type", "title", "agency", "published_at", "deadline_at",
        "budget", "estimated_price", "method", "url", "procurement_class", "region_limit",
        "lifecycle", "attachments", "qualification_flags", "focus_matches", "performance_matches",
        "performance_top_score", "candidate_sources", "collection_bucket", "unknown_fields",
        "raw_source", "sample_role", "sample_stratum",
    )}
    for key in ("published_at", "deadline_at"):
        result[key] = _identity_datetime(result[key])
    for key in ("budget", "estimated_price"):
        result[key] = _identity_decimal(result[key])
    return result


def _ordered_children(rows: Sequence[Any], *, positioned: bool, label: str) -> list[Any]:
    """Return deterministic child order and reject malformed position contracts."""

    if positioned:
        positions = [getattr(row, "position", None) for row in rows]
        if any(type(position) is not int or position <= 0 for position in positions):
            raise QualityGateValidationError("fixed quality run is invalid")
        expected = list(range(1, len(positions) + 1))
        if sorted(positions) != expected:
            raise QualityGateValidationError("fixed quality run is invalid")
        return sorted(rows, key=lambda row: (row.position, row.id or 0))
    return sorted(rows, key=lambda row: (row.id is None, row.id or 0))


def _db_notice_identity(notice: Notice) -> dict[str, Any]:
    return _normalized_fixed_notice({
        "notice_id": notice.notice_key,
        "source_type": notice.source_type,
        "title": notice.title,
        "agency": notice.agency,
        "published_at": notice.published_at,
        "deadline_at": notice.deadline_at,
        "budget": notice.budget,
        "estimated_price": notice.estimated_price,
        "method": notice.method,
        "url": notice.url,
        "procurement_class": notice.procurement_class_json,
        "region_limit": notice.region_limit_json,
        "lifecycle": notice.lifecycle_json,
        "attachments": [{"name": item.name, "url": item.url} for item in _ordered_children(notice.attachments, positioned=False, label="attachments")],
        "qualification_flags": notice.qualification_flags_json,
        "focus_matches": notice.focus_matches_json,
        "performance_matches": notice.performance_matches_json,
        "performance_top_score": notice.performance_top_score,
        "candidate_sources": notice.candidate_sources_json,
        "collection_bucket": notice.collection_bucket,
        "unknown_fields": notice.unknown_fields_json,
        "raw_source": notice.raw_source,
        "sample_role": notice.sample_role,
        "sample_stratum": notice.sample_stratum,
    })


def _db_judgment_identity(notice: Notice) -> dict[str, Any] | None:
    judgment = notice.judgment
    if judgment is None:
        return None
    return {
        "notice_id": notice.notice_key,
        "grade": judgment.grade,
        "readiness": judgment.readiness,
        "primary_focus": judgment.primary_focus,
        "exclusion_category": judgment.exclusion_category,
        "summary": judgment.summary,
        "perspectives": [
            {
                "name": perspective.name,
                "assessment": perspective.assessment,
                "reason": perspective.reason,
                "evidence": [
                    {"source": evidence.source, "status": evidence.status, "fact": evidence.fact}
                    for evidence in _ordered_children(perspective.evidence, positioned=False, label="evidence")
                ],
            }
            for perspective in _ordered_children(judgment.perspectives, positioned=True, label="perspectives")
        ],
        "matched_performances": [
            {
                "name": item.name,
                "match_reason": item.match_reason,
                "mismatch_or_limit": item.mismatch_or_limit,
                "source": item.source,
                "status": item.status,
            }
            for item in _ordered_children(judgment.matched_performances, positioned=False, label="matched_performances")
        ],
        "counterarguments": [item.text for item in _ordered_children(judgment.counterarguments, positioned=True, label="counterarguments")],
        "verification_items": [
            {"item": item.item, "why": item.why, "blocking": item.blocking, "status": item.status}
            for item in _ordered_children(judgment.verification_items, positioned=False, label="verification_items")
        ],
        "next_action": judgment.next_action,
    }


def resolve_fixed_run(
    session: Session,
    project_root: Path | str,
    *,
    run_alias: str = FIXED_RUN_ID,
    snapshot: _FixedInputSnapshot | None = None,
) -> Run:
    """Resolve the trusted artifact alias to exactly one canonical Run row.

    This function is deliberately read-only.  It performs every source, DB,
    notice, judgment, and provenance check before a quality gate can create a
    profile snapshot, queue row, artifact, or gate/evaluation row.
    """

    if run_alias != FIXED_RUN_ID:
        raise QualityGateValidationError("fixed quality run is invalid")
    fixed = snapshot or _read_strict_fixed_snapshot(project_root)
    if not isinstance(fixed, _FixedInputSnapshot) or fixed.token is not _FIXED_SNAPSHOT_TOKEN:
        raise QualityGateValidationError("fixed quality input is invalid")
    requested_root = _absolute_root(project_root)
    if fixed.root != requested_root:
        raise QualityGateValidationError("fixed quality input is invalid")
    sample, baseline, results, sample_ids = fixed.sample, fixed.baseline, fixed.results, list(fixed.ids)
    try:
        generated_at = datetime.fromisoformat(str(results["generated_at"]).replace("Z", "+00:00"))
    except (TypeError, ValueError, KeyError):
        raise QualityGateValidationError("fixed quality run is invalid") from None
    canonical_id = deterministic_run_id(run_alias, generated_at)
    # An alias row is never a valid fallback.  It was the original Phase 2
    # defect and accepting it would make foreign keys point at the wrong row.
    if session.get(Run, run_alias) is not None:
        raise QualityGateValidationError("fixed quality run is invalid")
    candidates = session.scalars(
        select(Run)
        .where(Run.id.like(f"{run_alias}--%"))
        .options(*_fixed_run_load_options())
    ).all()
    if not candidates:
        raise QualityGateValidationError("quality gate run or policy is missing")
    eligible = [row for row in candidates if row.status in _FIXED_RUN_ELIGIBLE_STATUSES and row.superseded_by is None]
    if len(eligible) != 1 or eligible[0].id != canonical_id:
        raise QualityGateValidationError("fixed quality run is invalid")
    run = eligible[0]
    if (
        run.window_from != date(2026, 8, 17)
        or run.window_to != date(2026, 8, 23)
        or run.timezone != "Asia/Seoul"
        or _identity_datetime(run.generated_at) != _identity_datetime(generated_at)
        or run.screening_basis != results.get("screening_basis")
    ):
        raise QualityGateValidationError("fixed quality run is invalid")

    # The resolver touches every child projection below.  Keep this as one
    # bounded select-in graph rather than triggering a query per notice and
    # per judgment child collection.
    db_notices = sorted(run.notices, key=lambda row: row.id)
    if len(db_notices) != 40 or [row.notice_key for row in db_notices] != sample_ids:
        raise QualityGateValidationError("fixed quality run is invalid")
    expected_notices = sample["notices"]
    for db_notice, expected in zip(db_notices, expected_notices):
        if _normalized_fixed_notice(expected) != _db_notice_identity(db_notice):
            raise QualityGateValidationError("fixed quality run is invalid")
    if sum(
        1
        for row in db_notices
        if row.judgment is not None and row.judgment.schema_version == "bidops.decisions.v2"
    ) != 40:
        raise QualityGateValidationError("fixed quality run is invalid")
    baseline_judgments = baseline["judgments"]
    for db_notice, expected in zip(db_notices, baseline_judgments):
        if _db_judgment_identity(db_notice) != _identity_value(dict(expected)):
            raise QualityGateValidationError("fixed quality run is invalid")
    return run


_INPUT_KEYS = frozenset({
    "schema_version", "execution_id", "run_id", "generated_at", "source_window",
    "policy_version", "prompt_version", "company_profile_version", "company_profile_digest",
    "candidate_count", "notices", "generation_config", "generation_config_digest",
})


def _input_binding_valid(
    value: Mapping[str, Any], execution: ScreeningExecution, sample: Mapping[str, Any], sample_ids: Sequence[str],
    *, expected_source_window: Mapping[str, Any] | None = None,
) -> bool:
    if set(value) == _INPUT_KEYS - {"generation_config", "generation_config_digest"}:
        # Historical pre-binding artifacts remain readable for compatibility;
        # the persisted execution row still supplies the deterministic legacy
        # binding. New execution artifacts always carry explicit fields.
        legacy = legacy_generation_config()
        if execution.generation_config_digest != legacy.digest():
            return False
        value = {**value, "generation_config": legacy.canonical_value(), "generation_config_digest": legacy.digest()}
    if set(value) != _INPUT_KEYS or value.get("schema_version") != "bidops.screening-input.v1":
        return False
    if value.get("execution_id") != execution.execution_id or value.get("run_id") != execution.source_run_id:
        return False
    if value.get("policy_version") != execution.policy_version or value.get("prompt_version") != execution.prompt_version:
        return False
    if value.get("company_profile_version") != execution.company_profile_version or value.get("company_profile_digest") != execution.company_profile_digest:
        return False
    try:
        execution_config, execution_digest = _validated_generation_binding(execution)
        generation_config = config_from_value(value.get("generation_config"))
        if validate_digest(generation_config, value.get("generation_config_digest")) != execution_digest:
            return False
        if execution_config.canonical_value() != generation_config.canonical_value():
            return False
    except (GenerationConfigError, QualityGateValidationError, AttributeError):
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
    legacy = legacy_generation_config()
    expected_input_config = input_value.get("generation_config")
    expected_input_digest = input_value.get("generation_config_digest")
    if expected_input_config is None and execution.generation_config_digest == legacy.digest():
        expected_input_config = legacy.canonical_value()
        expected_input_digest = legacy.digest()
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
        "generation_config": expected_input_config,
        "generation_config_digest": expected_input_digest or execution.generation_config_digest,
    }
    top_reasons: list[str] = []
    if set(value) == {"schema_version", "execution_id", "run_id", "generated_at", "screening_basis", "model_name", "model_digest", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest", "judgments"}:
        if execution.generation_config_digest == legacy.digest():
            value = {**value, "generation_config": legacy.canonical_value(), "generation_config_digest": legacy.digest()}
    if set(value) != {"schema_version", "execution_id", "run_id", "generated_at", "screening_basis", "model_name", "model_digest", "prompt_version", "policy_version", "company_profile_version", "company_profile_digest", "generation_config", "generation_config_digest", "judgments"}:
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


def _metric_structure_reasons(
    metrics: Mapping[str, Any], *, partial_passes: frozenset[str] = frozenset()
) -> list[str]:
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
        # A partial-success execution is allowed to have a missing/failed
        # notice.  Those notices remain in the fixed 40-item denominator and
        # are reported as a mismatch by the metric itself; they do not make a
        # completed gate structurally impossible.  A fully successful pass,
        # by contrast, promised one judgment for every fixed notice, so its
        # missing entry remains a hold-worthy contract failure.
        if row["pass"] in partial_passes and reason == "missing_judgment":
            continue
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

    def _cleanup_prepared_artifacts(self, prepared: Sequence[tuple[str, ExecutionWorkspace]]) -> None:
        """Remove only directories whose fresh workspace is still held."""

        store = ArtifactStore(Path(self.settings.bidops_root))
        seen: set[tuple[str, int, int]] = set()
        for execution_id, workspace in prepared:
            key = (execution_id, workspace.device, workspace.inode)
            if key in seen:
                continue
            seen.add(key)
            try:
                store.remove_execution(workspace)
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
        fixed = _read_strict_fixed_snapshot(self.settings.bidops_root)
        sample, baseline, sample_raw, baseline_raw, sample_ids = (
            fixed.sample, fixed.baseline, fixed.sample_raw, fixed.baseline_raw, list(fixed.ids)
        )

        with self._session() as session:
            run = resolve_fixed_run(session, self.settings.bidops_root, run_alias=run_id, snapshot=fixed)
            policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == policy_version))
            if policy is None:
                raise QualityGateValidationError("quality gate run or policy is missing")
            if policy.status not in {"activation_candidate", "active"}:
                raise QualityGateValidationError("policy is not selectable")
            resolved_run_id = run.id

        root = Path(self.settings.bidops_root)
        prepared_artifacts: list[tuple[str, ExecutionWorkspace]] = []
        quality_binding = _make_quality_sample_binding(
            resolved_run_id, fixed.sample["source_window"], fixed.sample["notices"]
        )
        try:
            if self.transaction_preparer is None:
                raise QualityGateConflict("quality gate requires a transaction-aware execution preparer")
            sample_digest = FIXED_SAMPLE_DIGEST
            baseline_digest = FIXED_BASELINE_DIGEST
            now = _now(self.clock())
            gate_id = "gate-" + uuid4().hex
            with self._session(immediate=True) as session:
                # Re-resolve while holding the same write transaction that
                # will publish both passes and the gate.  A stale, changed,
                # superseded, or ambiguous row cannot leak into any side
                # effect, even if the first read raced a DB writer.
                resolved = resolve_fixed_run(session, self.settings.bidops_root, run_alias=run_id, snapshot=fixed)
                if resolved.id != resolved_run_id:
                    raise QualityGateConflict("fixed quality run changed")
                policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == policy_version))
                if policy is None or policy.status not in {"activation_candidate", "active"}:
                    raise QualityGateValidationError("quality gate policy is not selectable")
                prepared_a = self.transaction_preparer(
                    session, run_id=resolved_run_id, policy_version=policy_version, profile_source=profile_source,
                    requested_by=actor, scope="quality_sample", trigger="quality_gate",
                    _quality_binding=quality_binding,
                )
                if not isinstance(getattr(prepared_a, "workspace", None), ExecutionWorkspace):
                    raise QualityGateConflict("quality pass ownership was not retained")
                prepared_artifacts.append((prepared_a.created.execution_id, prepared_a.workspace))
                prepared_b = self.transaction_preparer(
                    session, run_id=resolved_run_id, policy_version=policy_version, profile_source=profile_source,
                    requested_by=actor, scope="quality_sample", trigger="quality_gate",
                    _quality_binding=quality_binding,
                )
                if not isinstance(getattr(prepared_b, "workspace", None), ExecutionWorkspace):
                    raise QualityGateConflict("quality pass ownership was not retained")
                prepared_artifacts.append((prepared_b.created.execution_id, prepared_b.workspace))
                first, second = prepared_a.created, prepared_b.created
                if first.execution_id == second.execution_id:
                    raise QualityGateConflict("quality passes must be independent")
                execution_a, execution_b = prepared_a.row, prepared_b.row
                if (
                    execution_a.source_run_id != resolved_run_id
                    or execution_b.source_run_id != resolved_run_id
                ):
                    raise QualityGateConflict("quality pass source run identity is invalid")
                prepared_a.workspace.require_named()
                prepared_b.workspace.require_named()
                input_a = prepared_a.workspace.read_json("screening-input.json", expected_digest=execution_a.input_artifact_digest)
                input_b = prepared_b.workspace.read_json("screening-input.json", expected_digest=execution_b.input_artifact_digest)
                if not _input_binding_valid(input_a, execution_a, sample, sample_ids, expected_source_window=sample.get("source_window")) or not _input_binding_valid(input_b, execution_b, sample, sample_ids, expected_source_window=sample.get("source_window")):
                    raise QualityGateConflict("quality pass input binding is invalid")
                if _canonical_pass_input(input_a) != _canonical_pass_input(input_b):
                    raise QualityGateConflict("quality pass frozen input combination differs")
                if input_a.get("candidate_count") != 40 or input_b.get("candidate_count") != 40:
                    raise QualityGateValidationError("quality pass must contain exactly 40 notices")
                if not _input_matches_fixed_sample(input_a, sample, sample_ids) or not _input_matches_fixed_sample(input_b, sample, sample_ids):
                    raise QualityGateConflict("quality pass notices do not match the fixed sample")
                # The artifact row paths are only useful if the original
                # names still identify the same inodes immediately before the
                # gate projection is created.
                prepared_a.workspace.require_named()
                prepared_b.workspace.require_named()
                if execution_a.scope != "quality_sample" or execution_b.scope != "quality_sample":
                    raise QualityGateConflict("quality pass scope is invalid")
                profile = session.scalar(select(CompanyProfileSnapshot).where(CompanyProfileSnapshot.version == execution_a.company_profile_version))
                if profile is None or profile.digest != execution_a.company_profile_digest:
                    raise QualityGateConflict("quality pass profile identity is invalid")
                try:
                    config_a, digest_a = _validated_generation_binding(execution_a)
                    config_b, digest_b = _validated_generation_binding(execution_b)
                except QualityGateValidationError:
                    raise QualityGateConflict("quality pass generation config is invalid") from None
                if (
                    execution_a.policy_version != policy_version
                    or execution_b.policy_version != policy_version
                    or execution_a.prompt_version != execution_b.prompt_version
                    or execution_a.model_name != execution_b.model_name
                    or execution_a.model_digest != execution_b.model_digest
                    or execution_a.company_profile_version != execution_b.company_profile_version
                    or execution_a.company_profile_digest != execution_b.company_profile_digest
                    or digest_a != digest_b
                    or config_a.canonical_value() != config_b.canonical_value()
                    or execution_a.candidate_count != 40
                    or execution_b.candidate_count != 40
                ):
                    raise QualityGateConflict("quality pass policy identity differs")
                final_resolved = resolve_fixed_run(
                    session, self.settings.bidops_root, run_alias=run_id, snapshot=fixed
                )
                if final_resolved.id != resolved_run_id:
                    raise QualityGateConflict("fixed quality run changed")
                gate = QualityGate(
                    gate_id=gate_id, purpose=purpose, execution_status="대기", result_status="미측정",
                    baseline_run_id=resolved_run_id, sample_artifact_path=_safe_relative(FIXED_SAMPLE_RELATIVE),
                    sample_artifact_digest=sample_digest, baseline_decisions_path=_safe_relative(FIXED_BASELINE_RELATIVE),
                    baseline_decisions_digest=baseline_digest, policy_version=policy_version,
                    prompt_version=execution_a.prompt_version, model_name=execution_a.model_name,
                    model_digest=execution_a.model_digest, company_profile_version=execution_a.company_profile_version,
                    company_profile_digest=execution_a.company_profile_digest,
                    generation_config_json=config_a.canonical_value(),
                    generation_config_digest=digest_a,
                    pass_a_execution_id=first.execution_id, pass_b_execution_id=second.execution_id,
                    created_by=actor, created_at=now, completed_at=None, metrics_json=_initial_metrics(sample_ids),
                    reasons_json=["execution_pending"],
                )
                session.add(gate)
                session.flush()
                initial_evaluation = QualityGateEvaluation(
                    evaluation_id=_evaluation_id(), gate_id=gate_id, revision=1, result_status="미측정",
                    metrics_json=gate.metrics_json, reasons_json=["execution_pending"], valid_review_count=0,
                    distinct_notice_review_count=0, generation_config_digest=digest_a, created_at=now,
                )
                if hasattr(initial_evaluation, "generation_config_json"):
                    initial_evaluation.generation_config_json = config_a.canonical_value()
                session.add(initial_evaluation)
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
                prepared_a.workspace.require_named()
                prepared_b.workspace.require_named()
                return gate
        except Exception:
            self._cleanup_prepared_artifacts(prepared_artifacts)
            raise
        finally:
            for _execution_id, workspace in prepared_artifacts:
                workspace.close()

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
            generation_config_digest=gate.generation_config_digest,
            created_at=_now(self.clock()),
        )
        if hasattr(evaluation, "generation_config_json"):
            evaluation.generation_config_json = gate.generation_config_json
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
                except QualityGateValidationError:
                    # A trusted fixed-file failure is a transaction failure,
                    # not a metric result.  Do not append an evaluation that
                    # would make a tampered source look auditable.
                    raise
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
        snapshot = _read_strict_fixed_snapshot(root)
        if (
            gate.sample_artifact_path != FIXED_SAMPLE_RELATIVE
            or gate.baseline_decisions_path != FIXED_BASELINE_RELATIVE
            or gate.sample_artifact_digest != FIXED_SAMPLE_DIGEST
            or gate.baseline_decisions_digest != FIXED_BASELINE_DIGEST
        ):
            raise QualityGateValidationError("fixed quality input binding is invalid")
        # Reading the results file is part of the strict source contract even
        # though refresh metrics consume the sample and baseline projections.
        if sha256_bytes(snapshot.results_raw) != FIXED_RESULTS_DIGEST:
            raise QualityGateValidationError("fixed quality input binding is invalid")
        return snapshot.sample_raw, snapshot.baseline_raw, snapshot.sample, snapshot.baseline, list(snapshot.ids)

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
        try:
            gate_config, gate_digest = _validated_generation_binding(gate)
            execution_config_a, execution_digest_a = _validated_generation_binding(execution_a)
            execution_config_b, execution_digest_b = _validated_generation_binding(execution_b)
        except QualityGateValidationError:
            raise
        if (
            gate_digest != gate.generation_config_digest
            or execution_digest_a != gate_digest
            or execution_digest_b != gate_digest
            or gate_config.canonical_value() != execution_config_a.canonical_value()
            or gate_config.canonical_value() != execution_config_b.canonical_value()
        ):
            raise QualityGateValidationError("quality gate generation config binding is invalid")
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
        partial_passes = frozenset(
            pass_name
            for pass_name, execution in (("A", execution_a), ("B", execution_b))
            if execution.status == "부분 성공"
        )
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
        structural_binding_issues = [
            row
            for row in binding_issues
            if not (row.get("pass") in partial_passes and row.get("reason") == "missing_judgment")
        ]
        if structural_binding_issues:
            structure.append("decisions_binding_invalid")
        if any(reason.endswith("fixed_input_notice_mismatch") for reason in structure):
            for pass_name, input_value in (("A", input_a), ("B", input_b)):
                if not _input_matches_fixed_sample(input_value, sample, ids):
                    metrics["excluded_notices"].extend({"notice_id": notice_id, "pass": pass_name, "reason": "fixed_input_notice_mismatch"} for notice_id in ids)
        valid = int((metrics.get("evidence_validity") or {}).get("valid_review_count", 0))
        distinct = int((metrics.get("evidence_validity") or {}).get("distinct_notice_review_count", 0))
        structure.extend(_metric_structure_reasons(metrics, partial_passes=partial_passes))
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
        # Resolve the immutable evaluation ID first, then acquire the same
        # gate lock used by refresh/review.  On SQLite _lock_gate performs a
        # no-op UPDATE to obtain RESERVED before any authoritative re-read.
        gate = QualityGateService._lock_gate(session, evaluation.gate_id)
        evaluation = session.scalar(select(QualityGateEvaluation).where(QualityGateEvaluation.evaluation_id == evaluation_id))
        if evaluation is None:
            raise QualityGateActivationError("quality evaluation was not found")
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
        # Generation configuration is part of the approval identity. Check
        # the immutable gate projection, both frozen pass executions, and the
        # selected evaluation together.
        try:
            gate_config = config_from_value(gate.generation_config_json)
            validate_digest(gate_config, gate.generation_config_digest)
        except (GenerationConfigError, AttributeError, TypeError, ValueError):
            raise QualityGateActivationError("generation config is invalid") from None
        if evaluation.generation_config_digest != gate.generation_config_digest:
            raise QualityGateActivationError("evaluation generation config does not match quality gate")
        if hasattr(evaluation, "generation_config_json"):
            try:
                evaluation_config = config_from_value(evaluation.generation_config_json)
                validate_digest(evaluation_config, evaluation.generation_config_digest)
            except (GenerationConfigError, TypeError, ValueError, AttributeError):
                raise QualityGateActivationError("evaluation generation config is invalid") from None
            if evaluation_config.canonical_value() != gate_config.canonical_value():
                raise QualityGateActivationError("evaluation generation config does not match quality gate")
        # execution_id is the public immutable identifier; queue_no is the
        # ORM primary key, so do not use Session.get with the wrong key.
        passes = [
            session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id))
            for execution_id in (gate.pass_a_execution_id, gate.pass_b_execution_id)
        ]
        if any(
            execution is None
            or execution.generation_config_digest != gate.generation_config_digest
            or execution.generation_config_json != gate_config.canonical_value()
            for execution in passes
        ):
            raise QualityGateActivationError("quality pass generation config does not match quality gate")
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
