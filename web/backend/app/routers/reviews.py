"""Review persistence and YAML export endpoints."""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..core.config import get_settings
from ..core.db import get_db
from ..lifecycle.models import Notice, NoticeObservation
from ..screening.models import Review
from ..schemas import (
    ReviewAnswerResponse,
    ReviewResponse,
    ReviewUpsertRequest,
)
from ..schemas.revisions import (
    JudgmentRevisionHistoryItem,
    NoticeRevisionHistoryResponse,
    ReviewRevisionHistoryItem,
)
from ..services import reviews as review_service
from .common import get_run


router = APIRouter(prefix="/api/reviews", tags=["reviews"])
notice_router = APIRouter(prefix="/api/notices", tags=["reviews"])


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


_ERRORS: dict[str, tuple[int, str]] = {
    "reviewer_required": (422, "리뷰 담당자 이름이 필요합니다"),
    "review_invalid": (422, "리뷰 요청이 올바르지 않습니다"),
    "notice_not_found": (404, "공고를 찾을 수 없습니다"),
    "run_not_found": (404, "회차를 찾을 수 없습니다"),
    "review_observation_required": (
        409,
        "선택한 회차에서 관측된 공고만 리뷰할 수 있습니다",
    ),
    "review_conflict": (409, "리뷰 리비전이 현재 상태와 충돌합니다"),
    "revision_history_conflict": (409, "리비전 계보를 확인할 수 없습니다"),
}


def _error_response(error: review_service.ReviewServiceError) -> JSONResponse:
    status_code, message = _ERRORS.get(
        error.code, (500, "리뷰 작업을 완료할 수 없습니다")
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": error.code if error.code in _ERRORS else "processing_failed",
                "message": message,
                "details": None,
            },
            "request_id": None,
        },
    )


def _unexpected() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "processing_failed",
                "message": "리뷰 작업을 완료할 수 없습니다",
                "details": None,
            },
            "request_id": None,
        },
    )


@router.get("", response_model=list[ReviewResponse])
def list_reviews(
    run_id: str = Query(...),
    session: Session = Depends(get_db),
) -> list[ReviewResponse]:
    """Return canonical reviews for notices observed in one run."""

    run = get_run(session, run_id)
    reviews = session.scalars(
        select(Review)
        .join(Notice, Review.notice_pk == Notice.id)
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .where(NoticeObservation.run_id == run.id)
        .options(selectinload(Review.answers))
        .order_by(Review.notice_pk.asc())
    ).all()
    return [_review_response(review) for review in reviews]


@notice_router.put("/{notice_pk}/review", response_model=ReviewResponse)
def upsert_review(
    notice_pk: int,
    payload: ReviewUpsertRequest,
    session: Session = Depends(get_db),
) -> ReviewResponse | JSONResponse:
    """Create or update exactly one canonical review for a notice."""

    try:
        review = review_service.save_human_review(
            session,
            notice_id=notice_pk,
            run_id=payload.run_id,
            disposition=payload.disposition,
            system_judgment_review=payload.system_judgment_review,
            corrected_grade=payload.corrected_grade,
            corrected_readiness=payload.corrected_readiness,
            weakest_perspective=payload.weakest_perspective,
            reason=payload.reason,
            reviewer=payload.reviewer,
            reviewer_fallback=get_settings().reviewer_name,
            verification_answers=(
                (answer.item, answer.answer)
                for answer in payload.verification_answers
            ),
        )
        response = _review_response(review)
        session.commit()
        return response
    except review_service.ReviewServiceError as error:
        session.rollback()
        return _error_response(error)
    except IntegrityError:
        session.rollback()
        return _error_response(
            review_service.ReviewServiceError(
                "review_conflict", "리뷰 리비전이 현재 상태와 충돌합니다"
            )
        )
    except Exception:  # pragma: no cover - defensive API boundary
        session.rollback()
        return _unexpected()


@notice_router.get(
    "/{notice_pk}/revision-history",
    response_model=NoticeRevisionHistoryResponse,
)
def revision_history(
    notice_pk: int,
    session: Session = Depends(get_db),
) -> NoticeRevisionHistoryResponse | JSONResponse:
    """Return append-only judgment and human-review history for one notice."""

    try:
        history = review_service.get_revision_history(session, notice_pk)
        return NoticeRevisionHistoryResponse(
            notice_pk=history.notice_id,
            judgments=[
                JudgmentRevisionHistoryItem(
                    id=revision.id,
                    sequence=revision.sequence,
                    source_kind=revision.source_kind,
                    run_id=revision.run_id,
                    recording_execution_id=revision.recording_execution_id,
                    source_revision_id=revision.source_revision_id,
                    origin_execution_id=origin_execution_id,
                    payload_schema_version=revision.payload_schema_version,
                    payload=revision.payload_jsonb,
                    payload_sha256=revision.payload_sha256,
                    captured_at=revision.captured_at,
                )
                for revision, origin_execution_id in history.judgments
            ],
            reviews=[
                ReviewRevisionHistoryItem(
                    id=revision.id,
                    sequence=revision.sequence,
                    source_kind=revision.source_kind,
                    run_id=revision.run_id,
                    judgment_revision_id=revision.judgment_revision_id,
                    origin_execution_id=origin_execution_id,
                    payload_schema_version=revision.payload_schema_version,
                    payload=revision.payload_jsonb,
                    payload_sha256=revision.payload_sha256,
                    captured_at=revision.captured_at,
                )
                for revision, origin_execution_id in history.reviews
            ],
        )
    except review_service.ReviewServiceError as error:
        return _error_response(error)
    except Exception:  # pragma: no cover - defensive API boundary
        return _unexpected()


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
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .where(NoticeObservation.run_id == run.id)
        .order_by(Notice.id.asc())
    ).all()
    # 공고는 리뷰로 향하는 relationship 을 갖지 않는다(§4). 리뷰의 소유 모듈이므로
    # 여기서 회차 범위를 한 번에 읽어 공고별로 묶는다.
    reviews_by_notice = {
        review.notice_pk: review
        for review in session.scalars(
            select(Review)
            .where(Review.notice_id.in_([notice.id for notice in notices]))
            .options(selectinload(Review.answers))
        ).all()
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
