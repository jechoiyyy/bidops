"""Core append/read operations for immutable judgment and review revisions.

Callers own projection construction and pass an ID-free JSON object.  This
module owns canonical encoding, hashes, notice-scoped locking, sequence
allocation, and lineage validation; it deliberately does not update the
legacy ``Judgment`` or ``Review`` projections.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    JudgmentRevision,
    Notice,
    NoticeObservation,
    ReviewRevision,
    ScreeningExecution,
)


JUDGMENT_PAYLOAD_SCHEMA = "bidops.judgment-revision-payload.v1"
REVIEW_PAYLOAD_SCHEMA = "bidops.review-revision-payload.v1"
JudgmentSourceKind = Literal["runtime", "legacy_import", "carry_over"]
ReviewSourceKind = Literal["human", "legacy_import"]


class RevisionError(RuntimeError):
    """Base error for revision validation and append conflicts."""


class RevisionNotFoundError(RevisionError):
    pass


class RevisionValidationError(RevisionError):
    pass


class RevisionConflictError(RevisionError):
    pass


def canonical_payload_json(payload: Mapping[str, Any]) -> str:
    """Return the one canonical UTF-8 JSON representation used for hashing."""

    if not isinstance(payload, Mapping):
        raise RevisionValidationError("revision payload must be a JSON object")
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RevisionValidationError("revision payload is not valid JSON") from exc


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_payload_json(payload).encode("utf-8")).hexdigest()


def canonical_payload_and_hash(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    encoded = canonical_payload_json(payload)
    # The detached value prevents later caller mutation from changing a
    # pending ORM row after its digest was computed.
    canonical_value = json.loads(encoded)
    return canonical_value, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _aware(value: datetime | None) -> datetime:
    captured_at = value or datetime.now(timezone.utc)
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise RevisionValidationError("captured_at must be timezone-aware")
    return captured_at.astimezone(timezone.utc)


def _nonblank(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RevisionValidationError(f"{field} must be nonblank")
    return value


def _lock_notice(session: Session, notice_id: int) -> Notice:
    notice = session.scalar(
        select(Notice).where(Notice.id == notice_id).with_for_update()
    )
    if notice is None:
        raise RevisionNotFoundError(f"notice {notice_id} does not exist")
    return notice


def _require_observation(
    session: Session, *, notice_id: int, run_id: str | None
) -> NoticeObservation | None:
    if run_id is None:
        return None
    observation = session.scalar(
        select(NoticeObservation).where(
            NoticeObservation.notice_id == notice_id,
            NoticeObservation.run_id == run_id,
        )
    )
    if observation is None:
        raise RevisionValidationError(
            f"run {run_id!r} did not observe notice {notice_id}"
        )
    return observation


def _require_execution(
    session: Session,
    *,
    notice_id: int,
    run_id: str,
    execution_id: str,
) -> ScreeningExecution:
    execution = session.scalar(
        select(ScreeningExecution).where(
            ScreeningExecution.execution_id == execution_id
        )
    )
    if execution is None:
        raise RevisionNotFoundError(
            f"screening execution {execution_id!r} does not exist"
        )
    if execution.source_run_id != run_id:
        raise RevisionValidationError(
            "recording execution and revision run do not match"
        )
    if execution.scope == "single_notice" and execution.notice_pk != notice_id:
        raise RevisionValidationError(
            "single-notice execution and revision notice do not match"
        )
    return execution


def _next_judgment_sequence(session: Session, notice_id: int) -> int:
    current = session.scalar(
        select(func.max(JudgmentRevision.sequence)).where(
            JudgmentRevision.notice_id == notice_id
        )
    )
    return int(current or 0) + 1


def _next_review_sequence(session: Session, notice_id: int) -> int:
    current = session.scalar(
        select(func.max(ReviewRevision.sequence)).where(
            ReviewRevision.notice_id == notice_id
        )
    )
    return int(current or 0) + 1


def _judgment_replay_matches(
    row: JudgmentRevision,
    *,
    source_kind: str,
    run_id: str | None,
    source_revision_id: int | None,
    payload_schema_version: str,
    payload: dict[str, Any],
    payload_sha256: str,
) -> bool:
    return (
        row.source_kind == source_kind
        and row.run_id == run_id
        and row.source_revision_id == source_revision_id
        and row.payload_schema_version == payload_schema_version
        and row.payload_sha256 == payload_sha256
        and row.payload_jsonb == payload
    )


def append_judgment_revision(
    session: Session,
    *,
    notice_id: int,
    source_kind: JudgmentSourceKind,
    payload: Mapping[str, Any],
    run_id: str | None = None,
    recording_execution_id: str | None = None,
    source_revision_id: int | None = None,
    payload_schema_version: str = JUDGMENT_PAYLOAD_SCHEMA,
    captured_at: datetime | None = None,
) -> JudgmentRevision:
    """Append a judgment snapshot, returning an exact execution replay."""

    _lock_notice(session, notice_id)
    schema_version = _nonblank(payload_schema_version, "payload_schema_version")
    canonical_payload, digest = canonical_payload_and_hash(payload)

    if source_kind == "runtime":
        if run_id is None or recording_execution_id is None or source_revision_id is not None:
            raise RevisionValidationError(
                "runtime revisions require run and execution and cannot have a parent"
            )
    elif source_kind == "carry_over":
        if run_id is None or recording_execution_id is None or source_revision_id is None:
            raise RevisionValidationError(
                "carry-over revisions require run, execution, and parent"
            )
    elif source_kind == "legacy_import":
        if recording_execution_id is not None or source_revision_id is not None:
            raise RevisionValidationError(
                "legacy revisions cannot infer execution or parent"
            )
    else:
        raise RevisionValidationError(f"unsupported judgment source_kind {source_kind!r}")

    _require_observation(session, notice_id=notice_id, run_id=run_id)
    if recording_execution_id is not None:
        assert run_id is not None
        _require_execution(
            session,
            notice_id=notice_id,
            run_id=run_id,
            execution_id=recording_execution_id,
        )

    if source_revision_id is not None:
        parent = session.scalar(
            select(JudgmentRevision).where(
                JudgmentRevision.id == source_revision_id,
                JudgmentRevision.notice_id == notice_id,
            )
        )
        if parent is None:
            raise RevisionValidationError(
                "carry-over parent must be a judgment revision for the same notice"
            )
        if (
            parent.payload_schema_version != schema_version
            or parent.payload_sha256 != digest
            or parent.payload_jsonb != canonical_payload
        ):
            raise RevisionValidationError(
                "carry-over revision must preserve the parent payload and schema exactly"
            )

    if recording_execution_id is not None:
        existing = session.scalar(
            select(JudgmentRevision).where(
                JudgmentRevision.notice_id == notice_id,
                JudgmentRevision.recording_execution_id == recording_execution_id,
            )
        )
        if existing is not None:
            if _judgment_replay_matches(
                existing,
                source_kind=source_kind,
                run_id=run_id,
                source_revision_id=source_revision_id,
                payload_schema_version=schema_version,
                payload=canonical_payload,
                payload_sha256=digest,
            ):
                return existing
            raise RevisionConflictError(
                "recording execution already produced a different revision for this notice"
            )

    if source_kind == "legacy_import" and run_id is not None:
        existing_legacy = session.scalar(
            select(JudgmentRevision)
            .where(
                JudgmentRevision.notice_id == notice_id,
                JudgmentRevision.run_id == run_id,
                JudgmentRevision.source_kind == "legacy_import",
            )
            .order_by(JudgmentRevision.sequence)
            .limit(1)
        )
        if existing_legacy is not None:
            if _judgment_replay_matches(
                existing_legacy,
                source_kind=source_kind,
                run_id=run_id,
                source_revision_id=None,
                payload_schema_version=schema_version,
                payload=canonical_payload,
                payload_sha256=digest,
            ):
                return existing_legacy
            raise RevisionConflictError(
                "legacy import run already produced a different revision for this notice"
            )

    row = JudgmentRevision(
        notice_id=notice_id,
        sequence=_next_judgment_sequence(session, notice_id),
        source_kind=source_kind,
        run_id=run_id,
        recording_execution_id=recording_execution_id,
        source_revision_id=source_revision_id,
        payload_schema_version=schema_version,
        payload_jsonb=canonical_payload,
        payload_sha256=digest,
        captured_at=_aware(captured_at),
    )
    session.add(row)
    session.flush()
    return row


def append_review_revision(
    session: Session,
    *,
    notice_id: int,
    source_kind: ReviewSourceKind,
    payload: Mapping[str, Any],
    run_id: str | None = None,
    judgment_revision_id: int | None = None,
    payload_schema_version: str = REVIEW_PAYLOAD_SCHEMA,
    captured_at: datetime | None = None,
) -> ReviewRevision:
    """Append a review snapshot; an exact latest replay is a no-op."""

    _lock_notice(session, notice_id)
    schema_version = _nonblank(payload_schema_version, "payload_schema_version")
    canonical_payload, digest = canonical_payload_and_hash(payload)
    if source_kind == "human":
        if run_id is None:
            raise RevisionValidationError("human review revisions require a run")
    elif source_kind != "legacy_import":
        raise RevisionValidationError(f"unsupported review source_kind {source_kind!r}")

    _require_observation(session, notice_id=notice_id, run_id=run_id)
    if judgment_revision_id is not None:
        judgment_revision = session.scalar(
            select(JudgmentRevision).where(
                JudgmentRevision.id == judgment_revision_id,
                JudgmentRevision.notice_id == notice_id,
            )
        )
        if judgment_revision is None:
            raise RevisionValidationError(
                "review judgment revision must belong to the same notice"
            )

    latest = current_review_revision(session, notice_id)
    if latest is not None and (
        latest.source_kind == source_kind
        and latest.run_id == run_id
        and latest.judgment_revision_id == judgment_revision_id
        and latest.payload_schema_version == schema_version
        and latest.payload_sha256 == digest
        and latest.payload_jsonb == canonical_payload
    ):
        return latest

    row = ReviewRevision(
        notice_id=notice_id,
        sequence=_next_review_sequence(session, notice_id),
        source_kind=source_kind,
        run_id=run_id,
        judgment_revision_id=judgment_revision_id,
        payload_schema_version=schema_version,
        payload_jsonb=canonical_payload,
        payload_sha256=digest,
        captured_at=_aware(captured_at),
    )
    session.add(row)
    session.flush()
    return row


def get_judgment_revision(session: Session, revision_id: int) -> JudgmentRevision:
    row = session.get(JudgmentRevision, revision_id)
    if row is None:
        raise RevisionNotFoundError(f"judgment revision {revision_id} does not exist")
    return row


def get_review_revision(session: Session, revision_id: int) -> ReviewRevision:
    row = session.get(ReviewRevision, revision_id)
    if row is None:
        raise RevisionNotFoundError(f"review revision {revision_id} does not exist")
    return row


def judgment_revision_history(
    session: Session, notice_id: int
) -> list[JudgmentRevision]:
    return list(
        session.scalars(
            select(JudgmentRevision)
            .where(JudgmentRevision.notice_id == notice_id)
            .order_by(JudgmentRevision.sequence)
        )
    )


def review_revision_history(session: Session, notice_id: int) -> list[ReviewRevision]:
    return list(
        session.scalars(
            select(ReviewRevision)
            .where(ReviewRevision.notice_id == notice_id)
            .order_by(ReviewRevision.sequence)
        )
    )


def current_judgment_revision(
    session: Session, notice_id: int
) -> JudgmentRevision | None:
    return session.scalar(
        select(JudgmentRevision)
        .where(JudgmentRevision.notice_id == notice_id)
        .order_by(JudgmentRevision.sequence.desc())
        .limit(1)
    )


def current_review_revision(session: Session, notice_id: int) -> ReviewRevision | None:
    return session.scalar(
        select(ReviewRevision)
        .where(ReviewRevision.notice_id == notice_id)
        .order_by(ReviewRevision.sequence.desc())
        .limit(1)
    )


def origin_execution_for_judgment_revision(
    session: Session, revision: JudgmentRevision | int
) -> ScreeningExecution | None:
    """Resolve the runtime execution at the root of a carry-over chain."""

    current = (
        get_judgment_revision(session, revision)
        if isinstance(revision, int)
        else revision
    )
    visited: set[int] = set()
    while current.source_kind == "carry_over":
        if current.id in visited:
            raise RevisionValidationError("judgment carry-over lineage contains a cycle")
        visited.add(current.id)
        if current.source_revision_id is None:
            raise RevisionValidationError("carry-over revision has no parent")
        parent = session.scalar(
            select(JudgmentRevision).where(
                JudgmentRevision.id == current.source_revision_id,
                JudgmentRevision.notice_id == current.notice_id,
            )
        )
        if parent is None:
            raise RevisionValidationError("carry-over parent is missing or out of scope")
        current = parent

    if current.source_kind != "runtime" or current.recording_execution_id is None:
        return None
    execution = session.scalar(
        select(ScreeningExecution).where(
            ScreeningExecution.execution_id == current.recording_execution_id
        )
    )
    if execution is None:
        raise RevisionValidationError("origin screening execution is missing")
    return execution


def require_carry_origin_run(
    session: Session,
    parent_revision: JudgmentRevision | int,
    *,
    expected_source_run_id: str,
) -> ScreeningExecution:
    """Require a carry parent rooted in the exactly declared source run."""

    expected = _nonblank(expected_source_run_id, "expected_source_run_id")
    execution = origin_execution_for_judgment_revision(session, parent_revision)
    if execution is None or execution.source_run_id != expected:
        raise RevisionValidationError(
            "carry-over parent origin does not match the declared source run; "
            "rejudgment is required"
        )
    return execution


__all__ = [
    "JUDGMENT_PAYLOAD_SCHEMA",
    "REVIEW_PAYLOAD_SCHEMA",
    "RevisionConflictError",
    "RevisionError",
    "RevisionNotFoundError",
    "RevisionValidationError",
    "append_judgment_revision",
    "append_review_revision",
    "canonical_payload_and_hash",
    "canonical_payload_json",
    "canonical_payload_sha256",
    "current_judgment_revision",
    "current_review_revision",
    "get_judgment_revision",
    "get_review_revision",
    "judgment_revision_history",
    "origin_execution_for_judgment_revision",
    "require_carry_origin_run",
    "review_revision_history",
]
