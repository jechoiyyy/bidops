"""Human review mutation and combined revision-history domain service."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AuditEvent,
    JudgmentRevision,
    Notice,
    NoticeObservation,
    Review,
    ReviewRevision,
    Run,
    VerificationAnswer,
)
from app.services.revisions import (
    RevisionConflictError,
    RevisionValidationError,
    append_review_revision,
    judgment_revision_history,
    origin_execution_for_judgment_revision,
    review_revision_history,
)


REVIEW_SAVE_ACTION = "review.save"


class ReviewServiceError(RuntimeError):
    """Stable domain error that is safe for the API boundary to map."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ReviewAnswerValue:
    item: str | None
    answer: str | None


@dataclass(frozen=True)
class ReviewHistory:
    notice_id: int
    judgments: list[tuple[JudgmentRevision, str | None]]
    reviews: list[tuple[ReviewRevision, str | None]]


def nullable_text(value: Any) -> str | None:
    """Preserve meaningful values while retaining legacy blank-to-null behavior."""

    if value is None:
        return None
    if isinstance(value, str):
        clean = value.strip()
        return clean or None
    return str(value)


def review_revision_payload(
    *,
    disposition: str | None,
    system_judgment_review: str | None,
    corrected_grade: str | None,
    corrected_readiness: str | None,
    weakest_perspective: str | None,
    reason: str | None,
    reviewer: str | None,
    verification_answers: Iterable[ReviewAnswerValue | tuple[str | None, str | None]],
) -> dict[str, Any]:
    """Build the deterministic, ID-free ``review-revision-payload.v1`` value.

    Answer order is part of the human snapshot.  Nulls and explicit values
    such as ``unknown`` are retained without inference or coercion.
    """

    answers: list[dict[str, str | None]] = []
    for value in verification_answers:
        if isinstance(value, ReviewAnswerValue):
            item, answer = value.item, value.answer
        else:
            item, answer = value
        answers.append({"item": item, "answer": answer})
    return {
        "disposition": disposition,
        "system_judgment_review": system_judgment_review,
        "corrected_grade": corrected_grade,
        "corrected_readiness": corrected_readiness,
        "weakest_perspective": weakest_perspective,
        "reason": reason,
        "reviewer": reviewer,
        "verification_answers": answers,
    }


def _load_review(session: Session, notice_id: int, *, lock: bool = False) -> Review | None:
    query = (
        select(Review)
        .where(Review.notice_id == notice_id)
        .options(selectinload(Review.answers))
    )
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


def _latest_judgment_revision(
    session: Session, notice_id: int
) -> JudgmentRevision | None:
    return session.scalar(
        select(JudgmentRevision)
        .where(JudgmentRevision.notice_id == notice_id)
        .order_by(JudgmentRevision.sequence.desc())
        .limit(1)
        .with_for_update()
    )


def _latest_review_revision(session: Session, notice_id: int) -> ReviewRevision | None:
    return session.scalar(
        select(ReviewRevision)
        .where(ReviewRevision.notice_id == notice_id)
        .order_by(ReviewRevision.sequence.desc())
        .limit(1)
        .with_for_update()
    )


def save_human_review(
    session: Session,
    *,
    notice_id: int,
    run_id: str,
    disposition: Any = None,
    system_judgment_review: Any = None,
    corrected_grade: Any = None,
    corrected_readiness: Any = None,
    weakest_perspective: Any = None,
    reason: Any = None,
    reviewer: Any = None,
    reviewer_fallback: Any = None,
    verification_answers: Iterable[tuple[Any, Any]] = (),
    saved_at: datetime | None = None,
) -> Review:
    """Append one human snapshot and update its current projection atomically.

    The caller owns commit/rollback.  This service performs every validation,
    lock, revision append, projection replacement, and audit write before it
    returns, so the router cannot partially apply the business mutation.
    """

    clean_reviewer = nullable_text(reviewer) or nullable_text(reviewer_fallback)
    if clean_reviewer is None:
        raise ReviewServiceError("reviewer_required", "리뷰 담당자 이름이 필요합니다")

    event_at = saved_at or datetime.now(timezone.utc)
    if event_at.tzinfo is None or event_at.utcoffset() is None:
        raise ReviewServiceError("review_invalid", "리뷰 저장 시각이 올바르지 않습니다")
    event_at = event_at.astimezone(timezone.utc)

    clean_answers = [
        ReviewAnswerValue(nullable_text(item), nullable_text(answer))
        for item, answer in verification_answers
    ]
    payload = review_revision_payload(
        disposition=nullable_text(disposition),
        system_judgment_review=nullable_text(system_judgment_review),
        corrected_grade=nullable_text(corrected_grade),
        corrected_readiness=nullable_text(corrected_readiness),
        weakest_perspective=nullable_text(weakest_perspective),
        reason=nullable_text(reason),
        reviewer=clean_reviewer,
        verification_answers=clean_answers,
    )

    # Notice locking is the serialization boundary shared with the core
    # append functions.  Run/observation validation happens before any
    # projection row or child answer can be written.
    notice = session.scalar(
        select(Notice).where(Notice.id == notice_id).with_for_update()
    )
    if notice is None:
        raise ReviewServiceError("notice_not_found", "공고를 찾을 수 없습니다")
    if session.get(Run, run_id) is None:
        raise ReviewServiceError("run_not_found", "회차를 찾을 수 없습니다")
    observation = session.scalar(
        select(NoticeObservation).where(
            NoticeObservation.notice_id == notice_id,
            NoticeObservation.run_id == run_id,
        )
    )
    if observation is None:
        raise ReviewServiceError(
            "review_observation_required",
            "선택한 회차에서 관측된 공고만 리뷰할 수 있습니다",
        )

    pinned_judgment = _latest_judgment_revision(session, notice_id)
    previous_revision = _latest_review_revision(session, notice_id)
    try:
        revision = append_review_revision(
            session,
            notice_id=notice_id,
            source_kind="human",
            run_id=run_id,
            judgment_revision_id=(pinned_judgment.id if pinned_judgment else None),
            payload=payload,
            captured_at=event_at,
        )
    except (RevisionConflictError, RevisionValidationError) as error:
        raise ReviewServiceError(
            "review_conflict", "리뷰 리비전이 현재 상태와 충돌합니다"
        ) from error

    review = _load_review(session, notice_id, lock=True)
    if previous_revision is not None and revision.id == previous_revision.id:
        if review is None:
            raise ReviewServiceError(
                "review_conflict", "리뷰 리비전과 현재 projection이 일치하지 않습니다"
            )
        return review

    if review is None:
        review = Review(
            notice_id=notice_id,
            run_id=run_id,
            created_at=event_at,
            updated_at=event_at,
        )
        session.add(review)
        session.flush()
    else:
        review.run_id = run_id
        review.updated_at = event_at

    review.disposition = payload["disposition"]
    review.system_judgment_review = payload["system_judgment_review"]
    review.corrected_grade = payload["corrected_grade"]
    review.corrected_readiness = payload["corrected_readiness"]
    review.weakest_perspective = payload["weakest_perspective"]
    review.reason = payload["reason"]
    review.reviewer = clean_reviewer
    review.answers.clear()
    for answer in clean_answers:
        review.answers.append(
            VerificationAnswer(item=answer.item, answer=answer.answer)
        )

    session.flush()
    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=clean_reviewer,
            action=REVIEW_SAVE_ACTION,
            aggregate_type="review",
            aggregate_id=str(review.id),
            safe_metadata={
                "notice_id": notice_id,
                "run_id": run_id,
                "review_revision_id": revision.id,
                "review_revision_sequence": revision.sequence,
                "judgment_revision_id": revision.judgment_revision_id,
            },
            request_id=None,
            created_at=event_at,
        )
    )
    session.flush()
    return review


def get_revision_history(session: Session, notice_id: int) -> ReviewHistory:
    """Return ordered judgment/review histories with resolved execution roots."""

    if session.get(Notice, notice_id) is None:
        raise ReviewServiceError("notice_not_found", "공고를 찾을 수 없습니다")

    judgments = judgment_revision_history(session, notice_id)
    judgment_origins: dict[int, str | None] = {}
    try:
        for revision in judgments:
            execution = origin_execution_for_judgment_revision(session, revision)
            judgment_origins[revision.id] = (
                execution.execution_id if execution is not None else None
            )
        reviews = review_revision_history(session, notice_id)
        review_items: list[tuple[ReviewRevision, str | None]] = []
        by_id = {revision.id: revision for revision in judgments}
        for revision in reviews:
            origin_execution_id = None
            if revision.judgment_revision_id is not None:
                judgment = by_id.get(revision.judgment_revision_id)
                if judgment is None:
                    raise RevisionValidationError(
                        "review judgment revision is missing or out of scope"
                    )
                execution = origin_execution_for_judgment_revision(session, judgment)
                origin_execution_id = (
                    execution.execution_id if execution is not None else None
                )
            review_items.append((revision, origin_execution_id))
    except RevisionValidationError as error:
        raise ReviewServiceError(
            "revision_history_conflict", "리비전 계보를 확인할 수 없습니다"
        ) from error

    return ReviewHistory(
        notice_id=notice_id,
        judgments=[
            (revision, judgment_origins[revision.id]) for revision in judgments
        ],
        reviews=review_items,
    )


__all__ = [
    "REVIEW_SAVE_ACTION",
    "ReviewAnswerValue",
    "ReviewHistory",
    "ReviewServiceError",
    "get_revision_history",
    "nullable_text",
    "review_revision_payload",
    "save_human_review",
]
