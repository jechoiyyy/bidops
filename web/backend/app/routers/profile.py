"""Read-only company profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import (
    ProfileItemResponse,
    ProfileRawBlockResponse,
    ProfileSectionResponse,
    ProfileSectionsResponse,
    ProfileUnknownResponse,
    ProfileUnknownsResponse,
)
from ..services.profile import (
    ParsedSection,
    PROFILE_REFERENCE_FIELDS,
    count_reference_mentions,
    parse_profile,
    reference_texts,
)


router = APIRouter(prefix="/api/profile", tags=["profile"])


def _item_response(item) -> ProfileItemResponse:  # type: ignore[no-untyped-def]
    return ProfileItemResponse(
        key=item.key,
        label=item.label,
        section_id=item.section_id,
        section_number=item.section_number,
        status=item.status,
        value=item.value,
        source_line=item.source_line,
    )


def _raw_for(section: ParsedSection) -> str | None:
    """Return the source text a section would otherwise lose.

    파싱하지 못한 블록이 있으면 절 원문을 그대로 내려보낸다. 블록이 정상이어도
    상태 항목으로 구조화되지 않은 본문(예: 목록만 있는 절)이 남아 있으면 그
    본문을 내려보낸다. 인식하지 못한 내용을 조용히 버리면 화면에서는 절이 비어
    있는 것과 구분되지 않는다.
    """

    if section.raw_blocks:
        return section.raw
    if section.items:
        return None
    return section.body or None


def _section_response(section) -> ProfileSectionResponse:  # type: ignore[no-untyped-def]
    return ProfileSectionResponse(
        id=section.id,
        number=section.number,
        title=section.title,
        heading=section.heading,
        level=section.level,
        state=section.state,
        status_counts=dict(section.status_counts),
        items=[_item_response(item) for item in section.items],
        raw_blocks=[
            ProfileRawBlockResponse(
                line_start=block.line_start,
                raw=block.raw,
                error=block.error,
            )
            for block in section.raw_blocks
        ],
        raw=_raw_for(section),
        children=[_section_response(child) for child in section.children],
    )


@router.get("/sections", response_model=ProfileSectionsResponse)
def profile_sections() -> ProfileSectionsResponse:
    profile = parse_profile()
    return ProfileSectionsResponse(
        source=profile.source,
        sections=[_section_response(section) for section in profile.sections],
        status_counts=dict(profile.status_counts),
        parse_errors=profile.parse_errors,
    )


@router.get("/unknowns", response_model=ProfileUnknownsResponse)
def profile_unknowns(session: Session = Depends(get_db)) -> ProfileUnknownsResponse:
    profile = parse_profile()
    references_available = True
    try:
        texts = reference_texts(session)
    except Exception:
        # A database read failure is different from a successful zero-match
        # count.  Keep the distinction visible to the client.
        texts = []
        references_available = False

    items: list[ProfileUnknownResponse] = []
    for section, item in profile.unknown_items:
        count = count_reference_mentions(item, texts) if references_available else None
        items.append(
            ProfileUnknownResponse(
                key=item.key,
                label=item.label,
                section_id=item.section_id,
                section_number=item.section_number,
                section_title=section.title,
                value=item.value,
                reference_count=count,
                reference_status="counted" if references_available else "unavailable",
            )
        )
    return ProfileUnknownsResponse(
        source=profile.source,
        items=items,
        total=len(items),
        reference_fields=PROFILE_REFERENCE_FIELDS,
        parse_errors=profile.parse_errors,
    )
