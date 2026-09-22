"""Audit-only operator boundary for draining old queued reviews before deployment."""
import argparse
import json
from uuid import UUID

from sqlalchemy import select
from ..models import DeepReview, DeepReviewAttempt, WorkJob
from ...core.models import AuditEvent
from ..services.deep_reviews import _validate_actor, DeepReviewServiceError, DeepReviewService


def close_queued(session, review_id, actor):
    actor = _validate_actor(actor)
    review = session.scalar(select(DeepReview).where(DeepReview.id == review_id).with_for_update())
    if review is None:
        raise DeepReviewServiceError('not_found', '검토 없음', status_code=404)
    attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
    job = session.scalar(select(WorkJob).where(WorkJob.id == attempt.work_job_id).with_for_update()) if attempt else None
    if review.status != 'queued' or attempt is None or attempt.status != 'queued' or job is None or job.status != 'queued':
        raise DeepReviewServiceError('review_not_queued', '대기 실행만 중단할 수 있습니다', status_code=409)
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    review.status = attempt.status = job.status = 'failed'
    attempt.completed_at = job.completed_at = now
    job.last_error_code = 'operator_close'
    for stage in DeepReviewService._stages(session, attempt.id):
        stage.status = 'failed'
        stage.completed_at = now
        stage.invocation_metadata = [{'error_code':'operator_close'}]
    session.add(AuditEvent(actor_kind='human', claimed_name=actor, action='deep_review.operator_close', aggregate_type='deep_review', aggregate_id=str(review.id), safe_metadata={'attempt_id':str(attempt.id),'job_id':str(job.id),'reason':'operator_close'}))
    session.commit()
    return {'review_id':str(review.id),'status':'failed','reason':'operator_close'}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--review-id',type=UUID)
    parser.add_argument('--actor-name')
    parser.add_argument('--list-active',action='store_true')
    args=parser.parse_args(argv)
    from ...core.db import SessionLocal
    with SessionLocal() as session:
        try:
            if args.list_active:
                result=[{'review_id':str(row.id),'status':row.status,'policy_version_id':str(row.policy_version_id)} for row in session.scalars(select(DeepReview).where(DeepReview.status.in_(('queued','running'))))]
            elif args.review_id:
                result=close_queued(session,args.review_id,args.actor_name)
            else:
                parser.error('--list-active or --review-id required')
            print(json.dumps(result))
            return 0
        except DeepReviewServiceError as error:
            session.rollback(); print(json.dumps({'error':error.code})); return 2
        except Exception:
            session.rollback(); print(json.dumps({'error':'processing_failed'})); return 2
