"""Safe review index for every notice linked to an opportunity."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...lifecycle.models import Notice, Opportunity, OpportunityLink
from ..models import DeepReview, DeepReviewAttempt, FinalOpinion
from .deep_reviews import DeepReviewServiceError, quality_status_for_reviews


def opportunity_reviews(session: Session, opportunity_id: int) -> dict:
    if session.scalar(select(Opportunity.id).where(Opportunity.id == opportunity_id)) is None:
        raise DeepReviewServiceError("not_found", "사업기회를 찾을 수 없습니다", status_code=404)
    # IN deduplicates multiple historical links. This index intentionally also
    # includes candidate links; it does not confer authoritative ownership.
    linked_notices = select(OpportunityLink.notice_id).where(OpportunityLink.opportunity_id == opportunity_id)
    rows = session.execute(select(DeepReview, Notice.title, DeepReviewAttempt.status)
        .join(Notice, Notice.id == DeepReview.notice_id)
        .outerjoin(DeepReviewAttempt, DeepReviewAttempt.id == DeepReview.current_attempt_id)
        .where(DeepReview.notice_id.in_(linked_notices))
        .order_by(DeepReview.created_at.desc(), DeepReview.id.desc())).all()
    ids = [review.id for review, _title, _status in rows]
    quality = quality_status_for_reviews(session, ids)
    latest = {}
    if ids:
        sequences = select(FinalOpinion.deep_review_id, func.max(FinalOpinion.sequence).label("sequence")).where(
            FinalOpinion.deep_review_id.in_(ids)).group_by(FinalOpinion.deep_review_id).subquery()
        for review_id, value, created_at in session.execute(select(FinalOpinion.deep_review_id, FinalOpinion.value, FinalOpinion.created_at)
            .join(sequences, (sequences.c.deep_review_id == FinalOpinion.deep_review_id)
                & (sequences.c.sequence == FinalOpinion.sequence))).all():
            latest[review_id] = {"value": value, "decided_at": created_at}
    return {"opportunity_id": opportunity_id, "items": [{
        "deep_review_id": str(review.id), "notice_id": review.notice_id, "notice_title": title,
        "status": review.status, "quality_status": quality.get(review.id), "created_at": review.created_at,
        "current_attempt_status": attempt_status, "latest_final_opinion": latest.get(review.id),
    } for review, title, attempt_status in rows]}
