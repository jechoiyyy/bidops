"""Read-only parsing and reference accounting for the company profile."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Evidence, VerificationItem


PROFILE_REFERENCE_FIELDS = ["evidence.source", "evidence.fact", "verification_item.why"]
PROFILE_STATUSES = ("confirmed", "inferred", "unknown")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:\.)?\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*```\s*(yaml|yml)\s*$", re.IGNORECASE)
_CLOSE_FENCE_RE = re.compile(r"^\s*```\s*$")


@dataclass
class ParsedItem:
    key: str
    label: str
    section_id: str
    section_number: str | None
    status: str
    value: Any
    source_line: int


@dataclass
class RawBlock:
    line_start: int
    raw: str
    error: str


@dataclass
class ParsedSection:
    id: str
    number: str | None
    title: str
    heading: str
    level: int
    start_line: int
    end_line: int
    parent: "ParsedSection | None" = None
    children: list["ParsedSection"] = field(default_factory=list)
    items: list[ParsedItem] = field(default_factory=list)
    raw_blocks: list[RawBlock] = field(default_factory=list)
    raw: str = ""
    # 하위 절을 뺀 이 절 자체의 본문. 상태 항목으로 구조화되지 않은 내용도
    # 화면에서 볼 수 있어야 하므로 별도로 보관한다.
    body: str = ""
    status_counts: Counter[str] = field(default_factory=Counter)

    @property
    def state(self) -> str:
        active = [status for status in PROFILE_STATUSES if self.status_counts[status]]
        if not active:
            return "unrecorded"
        if len(active) == 1:
            return active[0]
        return "mixed"


@dataclass
class ParsedProfile:
    source: str
    sections: list[ParsedSection]
    status_counts: Counter[str]
    parse_errors: list[str]

    @property
    def unknown_items(self) -> list[tuple[ParsedSection, ParsedItem]]:
        return [
            (section, item)
            for section in walk_sections(self.sections)
            for item in section.items
            if item.status == "unknown"
        ]


def profile_path() -> Path:
    """Return the configured, read-only source document path."""

    return get_settings().bidops_root / "docs" / "reference" / "company-profile.md"


def _section_id(parent: ParsedSection | None, number: str | None, line_index: int) -> str:
    if number:
        return number
    if parent:
        return f"{parent.id}/heading-{line_index + 1}"
    return f"heading-{line_index + 1}"


def _new_sections(lines: list[str]) -> list[ParsedSection]:
    candidates: list[tuple[int, int, str, str | None]] = []
    for line_index, line in enumerate(lines):
        match = _HEADING_RE.match(line.rstrip("\r\n"))
        if not match:
            continue
        heading = match.group(2)
        # The document title is a page title, not one of the profile's numbered
        # sections.  Other headings are retained so the tree does not discard
        # information under a numbered section.
        if line_index == 0 and heading == "회사 프로필":
            continue
        numbered = _NUMBERED_HEADING_RE.match(heading)
        number = numbered.group(1) if numbered else None
        title = numbered.group(2) if numbered else heading
        candidates.append((line_index, len(match.group(1)), title, number))

    roots: list[ParsedSection] = []
    stack: list[ParsedSection] = []
    for line_index, level, title, number in candidates:
        while stack and stack[-1].level >= level:
            stack.pop()
        parent = stack[-1] if stack else None
        node = ParsedSection(
            id=_section_id(parent, number, line_index),
            number=number,
            title=title,
            heading=f"{'#' * level} {title if not number else number + '. ' + title}",
            level=level,
            start_line=line_index,
            end_line=len(lines),
            parent=parent,
        )
        if parent:
            parent.children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    all_sections = list(walk_sections(roots))
    for node in all_sections:
        for following in all_sections:
            if following.start_line <= node.start_line or following.level > node.level:
                continue
            if following.start_line < node.end_line:
                node.end_line = following.start_line
        node.raw = "".join(lines[node.start_line:node.end_line])
    return roots


def walk_sections(sections: list[ParsedSection]) -> list[ParsedSection]:
    result: list[ParsedSection] = []
    for section in sections:
        result.append(section)
        result.extend(walk_sections(section.children))
    return result


def _owner_for_line(sections: list[ParsedSection], line_index: int) -> ParsedSection | None:
    candidates = [
        section
        for section in walk_sections(sections)
        if section.start_line <= line_index < section.end_line
    ]
    return max(candidates, key=lambda section: section.start_line, default=None)


def _status_items(
    value: Any,
    *,
    path: tuple[str, ...],
    section: ParsedSection,
    source_line: int,
) -> list[ParsedItem]:
    items: list[ParsedItem] = []
    if isinstance(value, dict):
        status = value.get("status")
        if status in PROFILE_STATUSES:
            key = ".".join(path)
            stored_value = value.get("value") if "value" in value else None
            items.append(
                ParsedItem(
                    key=key,
                    label=path[-1] if path else "항목",
                    section_id=section.id,
                    section_number=section.number,
                    status=status,
                    value=stored_value,
                    source_line=source_line,
                )
            )
        for key, child in value.items():
            if key == "status":
                continue
            if isinstance(key, str):
                items.extend(
                    _status_items(
                        child,
                        path=(*path, key),
                        section=section,
                        source_line=source_line,
                    )
                )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            items.extend(
                _status_items(
                    child,
                    path=(*path, f"[{index}]"),
                    section=section,
                    source_line=source_line,
                )
            )
    return items


def _refresh_status_counts(section: ParsedSection) -> Counter[str]:
    counts: Counter[str] = Counter(item.status for item in section.items)
    for child in section.children:
        counts.update(_refresh_status_counts(child))
    section.status_counts = counts
    return counts


def parse_profile(path: Path | None = None) -> ParsedProfile:
    """Parse the profile without changing the source file.

    A malformed YAML block remains attached to its section as ``RawBlock``.
    This is intentional: the UI must be able to show the source rather than
    silently making a broken section disappear.
    """

    source_path = path or profile_path()
    source_name = str(source_path)
    try:
        text = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return ParsedProfile(
            source=source_name,
            sections=[],
            status_counts=Counter(),
            parse_errors=[f"프로필 원문을 읽지 못했습니다: {error}"],
        )

    lines = text.splitlines(keepends=True)
    sections = _new_sections(lines)
    errors: list[str] = []
    line_index = 0
    while line_index < len(lines):
        opening = _FENCE_RE.match(lines[line_index].rstrip("\r\n"))
        if not opening:
            line_index += 1
            continue
        block_start = line_index
        line_index += 1
        body_start = line_index
        while line_index < len(lines) and not _CLOSE_FENCE_RE.match(lines[line_index].rstrip("\r\n")):
            line_index += 1
        closed = line_index < len(lines)
        body = "".join(lines[body_start:line_index])
        if closed:
            line_index += 1
        raw = "".join(lines[block_start:line_index])
        owner = _owner_for_line(sections, block_start)
        if owner is None:
            continue
        if not closed:
            error_text = "YAML 코드 블록의 닫는 펜스가 없습니다."
            owner.raw_blocks.append(RawBlock(block_start + 1, raw, error_text))
            errors.append(f"{owner.heading} {block_start + 1}행: {error_text}")
            continue
        try:
            value = yaml.safe_load(body)
        except yaml.YAMLError as error:
            error_text = f"YAML 파싱에 실패했습니다: {error}"
            owner.raw_blocks.append(RawBlock(block_start + 1, raw, error_text))
            errors.append(f"{owner.heading} {block_start + 1}행: {error_text}")
            continue
        owner.items.extend(
            _status_items(
                value,
                path=(),
                section=owner,
                source_line=block_start + 1,
            )
        )

    for section in walk_sections(sections):
        section.raw = "".join(lines[section.start_line:section.end_line])
        body_end = min(
            [child.start_line for child in section.children] or [section.end_line]
        )
        section.body = "".join(lines[section.start_line + 1:body_end]).strip()
    counts = _refresh_status_counts_for_roots(sections)
    return ParsedProfile(source=source_name, sections=sections, status_counts=counts, parse_errors=errors)


def _refresh_status_counts_for_roots(sections: list[ParsedSection]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for section in sections:
        counts.update(_refresh_status_counts(section))
    return counts


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
