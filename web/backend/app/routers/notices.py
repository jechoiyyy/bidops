"""Notice queue, detail, and cross-run history endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from ..constants import GRADE_ORDER
from ..db import get_db
from ..models import Attachment, Judgment, Notice, NoticeObservation, Perspective, Review
from ..services.attachments import attachment_download_url
from ..schemas import (
    AttachmentResponse,
    CounterargumentResponse,
    EvidenceResponse,
    HistoryItemResponse,
    JudgmentResponse,
    MatchedPerformanceResponse,
    NoticeDetailResponse,
    NoticeHistoryResponse,
    NoticeListResponse,
    RelatedNoticeListResponse,
    RelatedNoticeResponse,
    PageFilters,
    PerspectiveResponse,
    ReviewAnswerResponse,
    ReviewResponse,
    VerificationItemResponse,
)
from .common import decimal_float, get_run, latest_notice_observation, notice_list_item


router = APIRouter(prefix="/api/notices", tags=["notices"])


def _list_options():
    return (
        selectinload(Notice.judgment),
        selectinload(Notice.attachments),
    )


def _list_filters(
    *,
    run_id: str,
    grade: str | None,
    readiness: str | None,
    focus: str | None,
    sample_role: str | None,
    attachment: Literal["any", "none", "manual"],
    q: str | None,
    sort: Literal["deadline", "grade", "published"],
    limit: int,
    offset: int,
) -> PageFilters:
    return PageFilters(
        run_id=run_id,
        grade=grade,
        readiness=readiness,
        focus=focus,
        sample_role=sample_role,
        attachment=attachment,
        q=q,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("", response_model=NoticeListResponse)
def list_notices(
    run_id: str = Query(...),
    grade: str | None = Query(default=None),
    readiness: str | None = Query(default=None),
    focus: str | None = Query(default=None),
    sample_role: str | None = Query(default="analysis"),
    attachment: Literal["any", "none", "manual"] = Query(default="any"),
    q: str | None = Query(default=None),
    sort: Literal["deadline", "grade", "published"] = Query(default="deadline"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> NoticeListResponse:
    run = get_run(session, run_id)
    conditions: list[Any] = [NoticeObservation.run_id == run.id]
    if sample_role and sample_role != "all":
        conditions.append(Notice.sample_role == sample_role)
    if grade and grade != "all":
        conditions.append(Judgment.grade == grade)
    elif grade != "all":
        conditions.append(Judgment.grade != "제외")
    if readiness:
        conditions.append(Judgment.readiness == readiness)
    if focus:
        conditions.append(Judgment.primary_focus == focus)
    if attachment == "none":
        conditions.append(~Notice.attachments.any())
    elif attachment == "any":
        # ``any`` is the unrestricted attachment state.  The queue must not
        # hide an analysis notice merely because its attachment is still to
        # be secured; ``none`` is the explicit missing-attachment filter.
        pass
    elif attachment == "manual":
        conditions.append(Notice.attachments.any(Attachment.origin == "manual"))
    if q:
        needle = f"%{q}%"
        conditions.append((Notice.title.ilike(needle)) | (Notice.agency.ilike(needle)))

    count_query = (
        select(func.count(func.distinct(Notice.id)))
        .select_from(Notice)
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .outerjoin(Judgment, Judgment.notice_pk == Notice.id)
        .where(*conditions)
    )
    total = int(session.scalar(count_query) or 0)

    query = (
        select(Notice)
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .outerjoin(Judgment, Judgment.notice_pk == Notice.id)
        .where(*conditions)
        .options(*_list_options())
    )
    if sort == "grade":
        grade_rank = case(
            *[(Judgment.grade == value, index) for index, value in enumerate(GRADE_ORDER)],
            else_=len(GRADE_ORDER),
        )
        query = query.order_by(grade_rank.asc(), Notice.deadline_at.asc().nulls_last(), Notice.id.asc())
    elif sort == "published":
        query = query.order_by(Notice.published_at.desc().nulls_last(), Notice.id.desc())
    else:
        query = query.order_by(Notice.deadline_at.asc().nulls_last(), Notice.id.asc())
    rows = session.scalars(query.offset(offset).limit(limit)).all()
    filters = _list_filters(
        run_id=run.id,
        grade=grade,
        readiness=readiness,
        focus=focus,
        sample_role=sample_role,
        attachment=attachment,
        q=q,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return NoticeListResponse(
        items=[notice_list_item(notice, run.id) for notice in rows],
        total=total,
        filters=filters,
    )


def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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
            ReviewAnswerResponse(id=answer.id, item=answer.item, answer=answer.answer)
            for answer in review.answers
        ],
    )


def _judgment_response(judgment: Judgment | None) -> JudgmentResponse | None:
    if judgment is None:
        return None
    return JudgmentResponse(
        id=judgment.id,
        schema_version=judgment.schema_version,
        grade=judgment.grade,
        readiness=judgment.readiness,
        primary_focus=judgment.primary_focus,
        exclusion_category=judgment.exclusion_category,
        summary=judgment.summary,
        next_action=judgment.next_action,
        perspectives=[
            PerspectiveResponse(
                id=perspective.id,
                position=perspective.position,
                name=perspective.name,
                assessment=perspective.assessment,
                reason=perspective.reason,
                evidence=[
                    EvidenceResponse(
                        id=evidence.id,
                        source=evidence.source,
                        status=evidence.status,
                        fact=evidence.fact,
                    )
                    for evidence in perspective.evidence
                ],
            )
            for perspective in judgment.perspectives
        ],
        counterarguments=[
            CounterargumentResponse(id=item.id, position=item.position, text=item.text)
            for item in judgment.counterarguments
        ],
        verification_items=[
            VerificationItemResponse(
                id=item.id,
                item=item.item,
                why=item.why,
                blocking=item.blocking,
                status=item.status,
            )
            for item in judgment.verification_items
        ],
        matched_performances=[
            MatchedPerformanceResponse(
                id=item.id,
                name=item.name,
                match_reason=item.match_reason,
                mismatch_or_limit=item.mismatch_or_limit,
                source=item.source,
                status=item.status,
            )
            for item in judgment.matched_performances
        ],
    )


def _detail_response(notice: Notice) -> NoticeDetailResponse:
    observation = latest_notice_observation(notice)
    run = observation.run if observation is not None else None
    base = notice_list_item(notice, run.id if run is not None else None)
    return NoticeDetailResponse(
        **base.model_dump(),
        bid_no=notice.bid_no,
        bid_ord=notice.bid_ord,
        source_type=notice.source_type,
        budget=decimal_float(notice.budget),
        method=notice.method,
        url=notice.url,
        timezone=run.timezone if run is not None else "Asia/Seoul",
        procurement_class=notice.procurement_class_json,
        region_limit=notice.region_limit_json,
        lifecycle=notice.lifecycle_json,
        qualification_flags=notice.qualification_flags_json,
        focus_matches=_json_list(notice.focus_matches_json),
        performance_matches=_json_list(notice.performance_matches_json),
        performance_top_score=notice.performance_top_score,
        candidate_sources=_json_list(notice.candidate_sources_json),
        judgment=_judgment_response(notice.judgment),
        attachments=[
            AttachmentResponse(
                id=attachment.id,
                name=attachment.name,
                url=attachment_download_url(attachment),
                origin=attachment.origin,
                file_ext=attachment.file_ext,
                size_bytes=attachment.size_bytes,
                extract_status=attachment.extract_status,
                created_at=attachment.created_at,
            )
            for attachment in notice.attachments
        ],
        reviews=[_review_response(review) for review in notice.reviews],
    )


DETAIL_OPTIONS = (
    selectinload(Notice.observations).selectinload(NoticeObservation.run),
    selectinload(Notice.attachments),
    selectinload(Notice.reviews).selectinload(Review.answers),
    selectinload(Notice.judgment).selectinload(Judgment.perspectives).selectinload(Perspective.evidence),
    selectinload(Notice.judgment).selectinload(Judgment.counterarguments),
    selectinload(Notice.judgment).selectinload(Judgment.verification_items),
    selectinload(Notice.judgment).selectinload(Judgment.matched_performances),
)


@router.get("/{notice_pk}", response_model=NoticeDetailResponse)
def notice_detail(notice_pk: int, session: Session = Depends(get_db)) -> NoticeDetailResponse:
    notice = session.scalar(select(Notice).where(Notice.id == notice_pk).options(*DETAIL_OPTIONS))
    if notice is None:
        raise HTTPException(status_code=404, detail=f"공고를 찾을 수 없습니다: {notice_pk}")
    return _detail_response(notice)


def _lifecycle_value(notice: Notice, key: str) -> Any:
    lifecycle = notice.lifecycle_json
    if not isinstance(lifecycle, dict):
        return None
    value = lifecycle.get(key)
    if isinstance(value, str):
        return value.strip() or None
    return value


def _related_relation(current: Notice, candidate: Notice) -> Literal["ordinal", "unified", "pre_spec"] | None:
    if (
        current.bid_no
        and current.bid_ord
        and candidate.bid_no
        and candidate.bid_ord
        and current.bid_no == candidate.bid_no
        and current.bid_ord != candidate.bid_ord
    ):
        return "ordinal"

    current_unified = _lifecycle_value(current, "unified_notice_no")
    candidate_unified = _lifecycle_value(candidate, "unified_notice_no")
    if current_unified is not None and candidate_unified is not None and current_unified == candidate_unified:
        return "unified"

    current_pre_spec = _lifecycle_value(current, "pre_spec_no")
    candidate_pre_spec = _lifecycle_value(candidate, "pre_spec_no")
    if current_pre_spec is not None and candidate_pre_spec is not None and current_pre_spec == candidate_pre_spec:
        return "pre_spec"
    return None


@router.get("/{notice_pk}/related", response_model=RelatedNoticeListResponse)
def related_notices(notice_pk: int, session: Session = Depends(get_db)) -> RelatedNoticeListResponse:
    current = session.scalar(select(Notice).where(Notice.id == notice_pk))
    if current is None:
        raise HTTPException(status_code=404, detail=f"공고를 찾을 수 없습니다: {notice_pk}")

    candidates = session.scalars(
        select(Notice)
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .where(
            NoticeObservation.run_id.in_(
                select(NoticeObservation.run_id).where(
                    NoticeObservation.notice_id == current.id
                )
            ),
            Notice.id != current.id,
        )
        .distinct()
        .options(selectinload(Notice.judgment))
        .order_by(Notice.published_at.asc().nulls_last(), Notice.id.asc())
    ).all()
    relation_order = {"ordinal": 0, "unified": 1, "pre_spec": 2}
    related: list[tuple[int, Notice, Literal["ordinal", "unified", "pre_spec"]]] = []
    for candidate in candidates:
        relation = _related_relation(current, candidate)
        if relation is not None:
            related.append((relation_order[relation], candidate, relation))
    # 공고일이 없는 후보는 뒤로 보내고, 그 안에서는 식별자 순서로 고정한다.
    # 정렬 키에 None 이 섞이면 비교 자체가 실패하므로 최소 시각으로 치환한다.
    epoch = datetime(1, 1, 1, tzinfo=timezone.utc)
    related.sort(
        key=lambda item: (
            item[0],
            item[1].published_at is None,
            item[1].published_at or epoch,
            item[1].id,
        )
    )

    return RelatedNoticeListResponse(
        notice_pk=current.id,
        items=[
            RelatedNoticeResponse(
                relation=relation,
                notice_pk=candidate.id,
                notice_key=candidate.notice_key,
                title=candidate.title,
                grade=candidate.judgment.grade if candidate.judgment else None,
                published_at=candidate.published_at,
                change_reason=_lifecycle_value(candidate, "change_reason"),
            )
            for _, candidate, relation in related
        ],
    )


@router.get("/{notice_pk}/history", response_model=NoticeHistoryResponse)
def notice_history(notice_pk: int, session: Session = Depends(get_db)) -> NoticeHistoryResponse:
    current = session.scalar(select(Notice).where(Notice.id == notice_pk))
    if current is None:
        raise HTTPException(status_code=404, detail=f"공고를 찾을 수 없습니다: {notice_pk}")
    rows = session.scalars(
        select(NoticeObservation)
        .join(Notice, NoticeObservation.notice_id == Notice.id)
        .where(Notice.notice_key == current.notice_key)
        .options(
            selectinload(NoticeObservation.run),
            selectinload(NoticeObservation.notice).selectinload(Notice.judgment),
            selectinload(NoticeObservation.notice).selectinload(Notice.reviews),
        )
        .order_by(NoticeObservation.observed_at.asc(), NoticeObservation.id.asc())
    ).all()
    history: list[HistoryItemResponse] = []
    for observation in rows:
        row = observation.notice
        run = observation.run
        review = next((item for item in row.reviews if item.run_id == run.id), None)
        history.append(
            HistoryItemResponse(
                notice_pk=row.id,
                run_id=run.id,
                window_from=run.window_from,
                window_to=run.window_to,
                timezone=run.timezone,
                generated_at=run.generated_at,
                grade=row.judgment.grade if row.judgment else None,
                readiness=row.judgment.readiness if row.judgment else None,
                focus=row.judgment.primary_focus if row.judgment else None,
                summary=row.judgment.summary if row.judgment else None,
                corrected_grade=review.corrected_grade if review else None,
                corrected_readiness=review.corrected_readiness if review else None,
                review_reason=review.reason if review else None,
            )
        )
    return NoticeHistoryResponse(notice_key=current.notice_key, items=history)
