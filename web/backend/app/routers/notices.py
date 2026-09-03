"""Notice queue, detail, and cross-run history endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..core.db import get_db
from ..lifecycle import extension_registry
from ..lifecycle.models import Attachment, Notice, NoticeObservation
from ..deep_review.services.attachments import attachment_download_url
from ..schemas import (
    AttachmentResponse,
    HistoryItemResponse,
    NoticeDetailResponse,
    NoticeHistoryResponse,
    NoticeListResponse,
    RelatedNoticeListResponse,
    RelatedNoticeResponse,
    PageFilters,
)
from .common import decimal_float, get_run, latest_notice_observation, notice_list_item


router = APIRouter(prefix="/api/notices", tags=["notices"])


def _list_options():
    return (selectinload(Notice.attachments),)


def _reject_unsupported_judgment_query(
    *,
    grade: str | None,
    readiness: str | None,
    focus: str | None,
    sort: str,
) -> None:
    """판정 제공자가 없으면 등급·준비·focus 필터와 `sort=grade`는 422다(§6.1).

    값이 아니라 "지원하지 않는다"는 사실이므로 registry의 능력 술어로 판단한다.
    """

    if extension_registry().judgment_filters_supported:
        return
    unsupported = [
        name
        for name, value in (("grade", grade), ("readiness", readiness), ("focus", focus))
        if value is not None
    ]
    if sort == "grade":
        unsupported.append("sort=grade")
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail=f"판정 결과를 제공하는 모듈이 없어 사용할 수 없는 조건입니다: {', '.join(unsupported)}",
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
    _reject_unsupported_judgment_query(grade=grade, readiness=readiness, focus=focus, sort=sort)
    run = get_run(session, run_id)
    projection = extension_registry().judgment_projection
    conditions: list[Any] = [NoticeObservation.run_id == run.id]
    if sample_role and sample_role != "all":
        conditions.append(Notice.sample_role == sample_role)
    # 등급·준비·focus 조건은 판정 projection이 공고 집합으로 돌려준다. `None`은
    # "제한하지 않음", 빈 sequence는 "0건 일치"이며 둘을 섞으면 안 된다(§6.1).
    judgment_ids = projection.notice_ids_for_filters(
        session, run_id=run.id, grade=grade, readiness=readiness, focus=focus
    )
    if judgment_ids is not None:
        conditions.append(Notice.id.in_(list(judgment_ids)))
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
        .where(*conditions)
    )
    total = int(session.scalar(count_query) or 0)

    query = (
        select(Notice)
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .where(*conditions)
        .options(*_list_options())
    )
    if sort == "published":
        query = query.order_by(Notice.published_at.desc().nulls_last(), Notice.id.desc())
    else:
        query = query.order_by(Notice.deadline_at.asc().nulls_last(), Notice.id.asc())
    if sort == "grade":
        # 등급 순위는 판정이 정한다. 회차 전체를 한 번에 읽어 메모리에서 정렬한
        # 뒤 잘라내며, 같은 순위 안의 순서는 기존 SQL과 같은 마감·식별자 순이다.
        rows = session.scalars(query).all()
        ranks = projection.grade_rank(session, [notice.id for notice in rows])
        ordered = sorted(
            enumerate(rows),
            key=lambda pair: (ranks.get(pair[1].id, 0), pair[0]),
        )
        rows = [notice for _, notice in ordered][offset : offset + limit]
    else:
        rows = session.scalars(query.offset(offset).limit(limit)).all()
    fields = projection.notice_fields(session, [notice.id for notice in rows])
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
        items=[
            notice_list_item(notice, run.id, fields.get(notice.id, {}))
            for notice in rows
        ],
        total=total,
        filters=filters,
    )


def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _detail_response(notice: Notice, detail: Mapping[str, Any]) -> NoticeDetailResponse:
    observation = latest_notice_observation(notice)
    run = observation.run if observation is not None else None
    judgment = detail.get("judgment")
    base = notice_list_item(
        notice,
        run.id if run is not None else None,
        {
            "grade": getattr(judgment, "grade", None),
            "readiness": getattr(judgment, "readiness", None),
            "focus": getattr(judgment, "primary_focus", None),
        },
    )
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
        judgment=judgment,
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
        reviews=list(detail.get("reviews", [])),
    )


DETAIL_OPTIONS = (
    selectinload(Notice.observations).selectinload(NoticeObservation.run),
    selectinload(Notice.attachments),
)


@router.get("/{notice_pk}", response_model=NoticeDetailResponse)
def notice_detail(notice_pk: int, session: Session = Depends(get_db)) -> NoticeDetailResponse:
    notice = session.scalar(select(Notice).where(Notice.id == notice_pk).options(*DETAIL_OPTIONS))
    if notice is None:
        raise HTTPException(status_code=404, detail=f"공고를 찾을 수 없습니다: {notice_pk}")
    detail = extension_registry().judgment_projection.notice_detail(session, notice.id)
    return _detail_response(notice, detail)


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

    fields = extension_registry().judgment_projection.notice_fields(
        session, [candidate.id for _, candidate, _ in related]
    )
    return RelatedNoticeListResponse(
        notice_pk=current.id,
        items=[
            RelatedNoticeResponse(
                relation=relation,
                notice_pk=candidate.id,
                notice_key=candidate.notice_key,
                title=candidate.title,
                grade=fields.get(candidate.id, {}).get("grade"),
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
        .options(selectinload(NoticeObservation.run))
        .order_by(NoticeObservation.observed_at.asc(), NoticeObservation.id.asc())
    ).all()
    # 이력의 등급·요약과 리뷰 정정값은 판정 projection이 공고별로 돌려준다.
    # 같은 공고가 여러 회차에 관측되므로 공고 단위로 한 번씩만 읽는다(§6.1).
    projection = extension_registry().judgment_projection
    details = {
        notice_id: projection.notice_detail(session, notice_id)
        for notice_id in dict.fromkeys(observation.notice_id for observation in rows)
    }
    history: list[HistoryItemResponse] = []
    for observation in rows:
        row = observation.notice
        run = observation.run
        detail = details.get(row.id, {})
        judgment = detail.get("judgment")
        review = next(
            (item for item in detail.get("reviews", []) if item.run_id == run.id), None
        )
        history.append(
            HistoryItemResponse(
                notice_pk=row.id,
                run_id=run.id,
                window_from=run.window_from,
                window_to=run.window_to,
                timezone=run.timezone,
                generated_at=run.generated_at,
                grade=judgment.grade if judgment else None,
                readiness=judgment.readiness if judgment else None,
                focus=judgment.primary_focus if judgment else None,
                summary=judgment.summary if judgment else None,
                corrected_grade=review.corrected_grade if review else None,
                corrected_readiness=review.corrected_readiness if review else None,
                review_reason=review.reason if review else None,
            )
        )
    return NoticeHistoryResponse(notice_key=current.notice_key, items=history)
