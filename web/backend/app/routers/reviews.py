"""Review persistence and YAML export endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..db import get_db
from ..models import Notice, Review, Run, VerificationAnswer
from ..schemas import (
    ReviewAnswerResponse,
    ReviewResponse,
    ReviewUpsertRequest,
)
from .common import get_run


router = APIRouter(prefix="/api/reviews", tags=["reviews"])
notice_router = APIRouter(prefix="/api/notices", tags=["reviews"])


def _nullable_text(value: Any) -> str | None:
    """Normalize optional form values without persisting empty strings."""

    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return str(value)


def _review_response(review: Review) -> ReviewResponse:
    return ReviewResponse(
        id=review.id,
        run_id=review.run_id,
        notice_pk=review.notice_pk,
        disposition=review.disposition,
        system_judgment_review=review.system_judgment_review,
        corrected_grade=review.corrected_grade,
        corrected_readiness=review.corrected_readiness,
        weakest_perspective=review.weakest_perspective,
        reason=review.reason,
        reviewer=review.reviewer,
        created_at=review.created_at,
        updated_at=review.updated_at,
        answers=[
            ReviewAnswerResponse(
                id=answer.id,
                item=answer.item,
                answer=answer.answer,
            )
            for answer in review.answers
        ],
    )


def _load_review(session: Session, review_id: int) -> Review:
    review = session.scalar(
        select(Review)
        .where(Review.id == review_id)
        .options(selectinload(Review.answers))
    )
    if review is None:
        raise HTTPException(status_code=404, detail="리뷰를 저장하지 못했습니다.")
    return review


@router.get("", response_model=list[ReviewResponse])
def list_reviews(
    run_id: str = Query(...),
    session: Session = Depends(get_db),
) -> list[ReviewResponse]:
    """Return the database-authoritative reviews for one run."""

    run = get_run(session, run_id)
    reviews = session.scalars(
        select(Review)
        .where(Review.run_id == run.id)
        .options(selectinload(Review.answers))
        .order_by(Review.notice_pk.asc())
    ).all()
    return [_review_response(review) for review in reviews]


@notice_router.put("/{notice_pk}/review", response_model=ReviewResponse)
def upsert_review(
    notice_pk: int,
    payload: ReviewUpsertRequest,
    session: Session = Depends(get_db),
) -> ReviewResponse:
    """Create or update exactly one review for a notice/run pair."""

    run = get_run(session, payload.run_id)
    notice = session.scalar(select(Notice).where(Notice.id == notice_pk))
    if notice is None:
        raise HTTPException(status_code=404, detail=f"공고를 찾을 수 없습니다: {notice_pk}")
    if notice.run_id != run.id:
        raise HTTPException(status_code=404, detail="공고와 회차가 일치하지 않습니다.")

    review = session.scalar(
        select(Review)
        .where(Review.notice_pk == notice_pk, Review.run_id == run.id)
        .options(selectinload(Review.answers))
    )
    reviewer = _nullable_text(payload.reviewer)
    if reviewer is None:
        reviewer = _nullable_text(get_settings().reviewer_name)

    if review is None:
        review = Review(
            notice_pk=notice_pk,
            run_id=run.id,
            created_at=datetime.now(timezone.utc),
        )
        session.add(review)
        session.flush()

    review.disposition = _nullable_text(payload.disposition)
    review.system_judgment_review = _nullable_text(payload.system_judgment_review)
    review.corrected_grade = _nullable_text(payload.corrected_grade)
    review.corrected_readiness = _nullable_text(payload.corrected_readiness)
    review.weakest_perspective = _nullable_text(payload.weakest_perspective)
    review.reason = _nullable_text(payload.reason)
    review.reviewer = reviewer
    review.updated_at = datetime.now(timezone.utc)

    # Answers are intentionally replaced as one set on every save.  This makes
    # clearing an answer deterministic and prevents stale items surviving a
    # second review of the same notice.
    review.answers.clear()
    for answer in payload.verification_answers:
        review.answers.append(
            VerificationAnswer(
                item=_nullable_text(answer.item),
                answer=_nullable_text(answer.answer),
            )
        )

    session.flush()
    session.commit()
    return _review_response(_load_review(session, review.id))


def _export_row(notice: Notice, review: Review | None) -> dict[str, Any]:
    answers = []
    if review is not None:
        answers = [
            {"item": answer.item, "answer": answer.answer}
            for answer in review.answers
        ]
    return {
        "notice_id": notice.notice_key,
        "disposition": review.disposition if review else None,
        "system_judgment_review": review.system_judgment_review if review else None,
        "corrected_grade": review.corrected_grade if review else None,
        "corrected_readiness": review.corrected_readiness if review else None,
        "weakest_perspective": review.weakest_perspective if review else None,
        "reason": review.reason if review else None,
        "verification_answers": answers,
    }


@router.get("/export")
def export_reviews(
    run_id: str = Query(...),
    session: Session = Depends(get_db),
) -> Response:
    """Render the DB reviews in the established review-feedback.v2 shape."""

    run = get_run(session, run_id)
    notices = session.scalars(
        select(Notice)
        .where(Notice.run_id == run.id)
        .options(selectinload(Notice.reviews).selectinload(Review.answers))
        .order_by(Notice.id.asc())
    ).all()
    reviews_by_notice = {
        review.notice_pk: review
        for notice in notices
        for review in notice.reviews
        if review.run_id == run.id
    }
    document = {
        "schema_version": "bidops.feedback.v2",
        "reviews": [
            _export_row(notice, reviews_by_notice.get(notice.id))
            for notice in notices
        ],
    }
    content = yaml.safe_dump(
        document,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return Response(
        content=content,
        media_type="application/yaml",
        headers={
            "Content-Disposition": 'attachment; filename="review-feedback.yaml"',
        },
    )
