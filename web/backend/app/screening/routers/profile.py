"""Read-only company profile endpoints."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import get_db
from ..models import CompanyProfileSnapshot
from ..schemas import (
    CompanyProfileSnapshotListResponse,
    CompanyProfileSnapshotResponse,
    ProfileItemResponse,
    ProfileSectionResponse,
    ProfileSectionsResponse,
    ProfileUnknownResponse,
    ProfileUnknownsResponse,
)
from ..services.profile import (
    ParsedSection,
    ParsedProfile,
    PROFILE_REFERENCE_FIELDS,
    PROFILE_PROJECTION_SCHEMA,
    count_reference_mentions,
    parse_profile_text,
    reference_texts,
)
from ..profile_snapshot import ProfileSnapshotError, read_profile_snapshot


router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get(
    "/snapshots",
    response_model=CompanyProfileSnapshotListResponse,
    response_model_exclude_none=True,
)
def profile_snapshots(
    session: Session = Depends(get_db),
) -> CompanyProfileSnapshotListResponse:
    """List immutable profile snapshot metadata without body or filesystem path."""

    total = int(
        session.scalar(select(func.count()).select_from(CompanyProfileSnapshot)) or 0
    )
    rows = session.scalars(
        select(CompanyProfileSnapshot).order_by(
            CompanyProfileSnapshot.created_at.desc(),
            CompanyProfileSnapshot.digest.desc(),
        )
    ).all()
    return CompanyProfileSnapshotListResponse(
        items=[
            CompanyProfileSnapshotResponse(
                version=row.version,
                digest=row.digest,
                source_kind=row.source_kind,
                source_ref=row.source_ref if row.source_kind == "git_blob" else None,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
    )


def _item_response(item) -> ProfileItemResponse:  # type: ignore[no-untyped-def]
    return ProfileItemResponse(
        key=item.key,
        label=item.label,
        section_id=item.section_id,
        section_number=item.section_number,
        status=item.status,
        value=item.value,
    )


def _section_response(section: ParsedSection) -> ProfileSectionResponse:
    return ProfileSectionResponse(
        id=section.id,
        number=section.number,
        title=section.title,
        heading=section.heading,
        level=section.level,
        state=section.state,
        status_counts=dict(section.status_counts),
        items=[_item_response(item) for item in section.items],
        error_codes=list(section.error_codes),
        children=[_section_response(child) for child in section.children],
    )


def _latest_profile_snapshot(session: Session) -> CompanyProfileSnapshot | None:
    current = session.scalar(
        select(CompanyProfileSnapshot)
        .where(CompanyProfileSnapshot.source_kind == "working_tree")
        .order_by(
            CompanyProfileSnapshot.created_at.desc(),
            CompanyProfileSnapshot.digest.desc(),
        )
        .limit(1)
    )
    if current is not None:
        return current
    return session.scalar(
        select(CompanyProfileSnapshot)
        .order_by(
            CompanyProfileSnapshot.created_at.desc(),
            CompanyProfileSnapshot.digest.desc(),
        )
        .limit(1)
    )


def _load_profile_snapshot(session: Session) -> tuple[CompanyProfileSnapshot, ParsedProfile]:
    snapshot = _latest_profile_snapshot(session)
    if snapshot is None:
        # There is no safe identity to attach to a projection.  Do not fall
        # back to reading the current working tree without a snapshot.
        raise HTTPException(status_code=503, detail="profile_snapshot_unavailable")
    try:
        raw = read_profile_snapshot(
            session,
            version=snapshot.version,
            project_root=get_settings().bidops_root,
        )
        text = raw.decode("utf-8")
    except (ProfileSnapshotError, UnicodeError):
        return snapshot, ParsedProfile(
            source=snapshot.version,
            sections=[],
            status_counts=Counter(),
            parse_errors=["profile_snapshot_unavailable"],
        )
    return snapshot, parse_profile_text(text, source_name=snapshot.version)


@router.get("/sections", response_model=ProfileSectionsResponse)
def profile_sections(session: Session = Depends(get_db)) -> ProfileSectionsResponse:
    snapshot, profile = _load_profile_snapshot(session)
    return ProfileSectionsResponse(
        schema_version=PROFILE_PROJECTION_SCHEMA,
        profile_version=snapshot.version,
        profile_digest=snapshot.digest,
        sections=[_section_response(section) for section in profile.sections],
        status_counts=dict(profile.status_counts),
        error_codes=profile.parse_errors,
    )


@router.get("/unknowns", response_model=ProfileUnknownsResponse)
def profile_unknowns(session: Session = Depends(get_db)) -> ProfileUnknownsResponse:
    snapshot, profile = _load_profile_snapshot(session)
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
    error_codes = list(profile.parse_errors)
    if not references_available and "profile_references_unavailable" not in error_codes:
        error_codes.append("profile_references_unavailable")
    return ProfileUnknownsResponse(
        schema_version=PROFILE_PROJECTION_SCHEMA,
        profile_version=snapshot.version,
        profile_digest=snapshot.digest,
        items=items,
        total=len(items),
        reference_fields=PROFILE_REFERENCE_FIELDS,
        error_codes=error_codes,
    )
