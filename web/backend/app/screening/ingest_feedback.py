"""보고서 YAML에서 가져오는 초기 리뷰 적재.

리뷰는 판정에 대한 사람의 결정이므로 screening이 소유한다(명세 §5.1). 회차 적재
hook이 공고 적재를 마친 뒤 같은 transaction에서 부른다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..lifecycle.ingest.contracts import (
    FeedbackArtifact,
    FeedbackReviewContract,
    is_blank,
    model_extra_fields,
)
from ..lifecycle import record_ingest_warning
from ..lifecycle.models import Run
from .models import Review, VerificationAnswer
from .services.revisions import append_review_revision
from .services.reviews import review_revision_payload


def _has_value(value: Any) -> bool:
    if is_blank(value):
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _warning(
    session: Session,
    run_id: str,
    level: str,
    code: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> None:
    # 회차 경고는 lifecycle 테이블이므로 lifecycle 공개 함수로만 쓴다(§4).
    record_ingest_warning(
        session, run_id=run_id, level=level, code=code, message=message, context=context
    )


def _filled_text(value: Any) -> str | None:
    if not _has_value(value):
        return None
    return str(value).strip() if isinstance(value, str) else str(value)


def _feedback_review_model(raw: Any) -> FeedbackReviewContract:
    return raw if isinstance(raw, FeedbackReviewContract) else FeedbackReviewContract.model_validate(raw)


def load_feedback(
    session: Session,
    run: Run,
    notices: dict[str, Any],
    path: str | Path,
) -> int:
    """Import only reviews containing at least one user-provided value.

    A pre-existing DB row is authoritative (ADR-007), even if the YAML has a
    different value.  This makes re-ingesting a report safe after a user has
    started reviewing in the Admin UI.
    """

    feedback_path = Path(path)
    if not feedback_path.is_file():
        return 0
    try:
        raw = yaml.safe_load(feedback_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        _warning(
            session,
            run.id,
            "error",
            "feedback_invalid",
            "review-feedback.yaml을 읽지 못했습니다.",
            {"file": str(feedback_path), "error": str(exc)},
        )
        return 0
    if not isinstance(raw, dict):
        _warning(
            session,
            run.id,
            "error",
            "feedback_invalid",
            "review-feedback.yaml 최상위 값이 객체가 아닙니다.",
            {"file": str(feedback_path)},
        )
        return 0
    try:
        artifact = FeedbackArtifact.model_validate({**raw, "reviews": []})
    except ValidationError as exc:
        _warning(
            session,
            run.id,
            "error",
            "feedback_invalid",
            "review-feedback.yaml 계약을 해석하지 못했습니다.",
            {"file": str(feedback_path), "error": str(exc)},
        )
        return 0
    for field_name in model_extra_fields(artifact):
        _warning(
            session,
            run.id,
            "info",
            "unknown_field",
            f"알 수 없는 필드를 무시했습니다: {field_name}",
            {"file": str(feedback_path), "field": field_name},
        )
    if raw.get("schema_version") != "bidops.feedback.v2":
        _warning(
            session,
            run.id,
            "warning",
            "feedback_schema_mismatch",
            "지원 계약과 다른 리뷰 스키마 버전입니다.",
            {
                "file": str(feedback_path),
                "actual": raw.get("schema_version"),
                "expected": "bidops.feedback.v2",
            },
        )

    raw_reviews = raw.get("reviews")
    if not isinstance(raw_reviews, list):
        return 0
    imported = 0
    for index, raw_review in enumerate(raw_reviews):
        if not isinstance(raw_review, dict):
            _warning(
                session,
                run.id,
                "warning",
                "feedback_review_invalid",
                "리뷰 항목이 객체가 아니어서 건너뛰었습니다.",
                {"file": str(feedback_path), "index": index},
            )
            continue
        try:
            review_model = _feedback_review_model(raw_review)
        except ValidationError as exc:
            _warning(
                session,
                run.id,
                "warning",
                "feedback_review_invalid",
                "리뷰 항목을 해석하지 못해 건너뛰었습니다.",
                {"file": str(feedback_path), "index": index, "error": str(exc)},
            )
            continue
        for field_name in model_extra_fields(review_model, "review"):
            _warning(
                session,
                run.id,
                "info",
                "unknown_field",
                f"알 수 없는 필드를 무시했습니다: {field_name}",
                {"file": str(feedback_path), "field": field_name},
            )

        raw_answers = raw_review.get("verification_answers")
        filled_answers: list[tuple[str | None, str | None]] = []
        if isinstance(raw_answers, list):
            for raw_answer in raw_answers:
                if not isinstance(raw_answer, dict):
                    continue
                item = _filled_text(raw_answer.get("item"))
                answer = _filled_text(raw_answer.get("answer"))
                if item is not None or answer is not None:
                    filled_answers.append((item, answer))
        scalar_fields = (
            "disposition",
            "system_judgment_review",
            "corrected_grade",
            "corrected_readiness",
            "weakest_perspective",
            "reason",
        )
        has_filled_scalar = any(_has_value(raw_review.get(field_name)) for field_name in scalar_fields)
        if not has_filled_scalar and not filled_answers:
            continue

        notice_id = review_model.notice_id
        notice = notices.get(str(notice_id)) if not is_blank(notice_id) else None
        if notice is None:
            _warning(
                session,
                run.id,
                "error",
                "feedback_notice_not_found",
                "리뷰의 공고를 찾지 못해 적재하지 않았습니다.",
                {"file": str(feedback_path), "index": index, "notice_id": notice_id},
            )
            continue
        # Review is canonical per notice.  The run is provenance for the
        # observation in which a new decision was entered, not part of its
        # identity.
        # The application SessionFactory disables autoflush; flush before the
        # lookup so two entries for the same notice in one artifact cannot
        # stage duplicate canonical reviews in the same transaction.
        session.flush()
        existing = session.scalar(select(Review).where(Review.notice_pk == notice.id))
        if existing is not None:
            continue
        review = Review(
            notice=notice,
            run=run,
            disposition=_filled_text(review_model.disposition),
            system_judgment_review=_filled_text(review_model.system_judgment_review),
            corrected_grade=_filled_text(review_model.corrected_grade),
            corrected_readiness=_filled_text(review_model.corrected_readiness),
            weakest_perspective=_filled_text(review_model.weakest_perspective),
            reason=_filled_text(review_model.reason),
            # The compatibility YAML has no reviewer field.  A current
            # deployment setting cannot identify the historical author.
            reviewer=None,
        )
        session.add(review)
        for item, answer in filled_answers:
            session.add(VerificationAnswer(review=review, item=item, answer=answer))
        session.flush()
        append_review_revision(
            session,
            notice_id=notice.id,
            source_kind="legacy_import",
            run_id=run.id,
            judgment_revision_id=None,
            payload=review_revision_payload(
                disposition=review.disposition,
                system_judgment_review=review.system_judgment_review,
                corrected_grade=review.corrected_grade,
                corrected_readiness=review.corrected_readiness,
                weakest_perspective=review.weakest_perspective,
                reason=review.reason,
                reviewer=review.reviewer,
                verification_answers=filled_answers,
            ),
            captured_at=review.updated_at,
        )
        imported += 1
    session.flush()
    return imported
