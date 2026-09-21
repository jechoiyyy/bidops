"""Team-wide review visibility; independent of tracking and analysis eligibility."""
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.models import AuditEvent
from ..models import Notice
from ..schemas.pre_specs import (
    PreSpecReviewExclusionRequest,
    PreSpecReviewExclusionResponse,
    PreSpecReviewExclusionResult,
)


def change_review_exclusions(
    session: Session, request: PreSpecReviewExclusionRequest,
) -> PreSpecReviewExclusionResponse:
    # Lock in a common order, refresh even if this session already read a row.
    rows = session.scalars(
        select(Notice).where(Notice.id.in_(request.notice_ids))
        .order_by(Notice.id).with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    if len(rows) != len(request.notice_ids) or any(row.source_type != "pre_spec" for row in rows):
        raise HTTPException(status_code=422, detail="invalid_pre_spec_notice_ids")
    now = datetime.now(UTC)
    results = {}
    for row in rows:
        previous = row.review_exclusion_status
        changed = previous != request.status
        if changed:
            row.review_exclusion_status = request.status
            row.review_exclusion_actor_name = request.actor_name
            row.review_exclusion_reason = request.reason
            row.review_exclusion_changed_at = now
            session.add(AuditEvent(
                actor_kind="human", claimed_name=request.actor_name,
                action="pre_spec.review_exclusion_changed", aggregate_type="notice",
                aggregate_id=str(row.id), created_at=now,
                safe_metadata={
                    "previous_status": previous, "status": request.status,
                    "actor_name": request.actor_name, "reason": request.reason,
                    "changed_at": now.isoformat(),
                },
            ))
        results[row.id] = PreSpecReviewExclusionResult(
            notice_id=row.id, status=request.status,
            outcome="changed" if changed else "unchanged",
        )
    session.flush()
    return PreSpecReviewExclusionResponse(items=[results[key] for key in request.notice_ids])
