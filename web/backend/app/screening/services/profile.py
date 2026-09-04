"""Reference accounting for the company profile.

문서 파싱 자체는 `app.core.company_profile`이 소유하고, 여기에는 판정 근거가
프로필 항목을 몇 번 인용했는지 세는 선별 쪽 계산만 남는다.
"""

from __future__ import annotations

import re
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.company_profile import (
    PROFILE_PARSE_ERROR_CODES,
    PROFILE_REFERENCE_FIELDS,
    PROFILE_STATUSES,
    ParsedItem,
    ParsedProfile,
    ParsedSection,
    parse_profile,
    parse_profile_text,
    profile_path,
    walk_sections,
)
from ..models import Evidence, VerificationItem

PROFILE_PROJECTION_SCHEMA: Final[str] = "bidops.profile-projection.v1"


def reference_texts(session: Session) -> list[str]:
    """Load only the evidence and verification prose used for accounting."""

    texts: list[str] = []
    for source, fact in session.execute(select(Evidence.source, Evidence.fact)).all():
        if source:
            texts.append(source)
        if fact:
            texts.append(fact)
    for (why,) in session.execute(select(VerificationItem.why)).all():
        if why:
            texts.append(why)
    return texts


def _reference_pattern(section_number: str | None, key: str) -> re.Pattern[str] | None:
    terms: list[str] = []
    if section_number:
        terms.append(rf"(?<!\d){re.escape(section_number)}(?!\d)")
    if key:
        terms.append(re.escape(key))
        leaf = key.rsplit(".", 1)[-1]
        if leaf and leaf not in {"value", "status"}:
            terms.append(re.escape(leaf))
            terms.append(re.escape(leaf.replace("_", " ")))
    if not terms:
        return None
    return re.compile("(?:" + "|".join(sorted(set(terms), key=len, reverse=True)) + ")", re.IGNORECASE)


def count_reference_mentions(item: ParsedItem, texts: list[str]) -> int:
    pattern = _reference_pattern(item.section_number, item.key)
    if pattern is None:
        return 0
    return sum(len(pattern.findall(text)) for text in texts)
