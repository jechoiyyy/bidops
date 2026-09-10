"""결정적 요구사항 inventory와 목적별 segment manifest.

이 모듈은 **모델을 부르지 않는다.** clean ``DocumentStructure`` 하나에서
요구사항 ID inventory와 목적별 segment를 결정적 규칙만으로 뽑고, 그 결과를
structure당 하나의 불변 manifest 행으로 저장한다.

규칙이 label을 정하지 못하거나 둘 이상이 충돌하면 추정하지 않고
``status=needs_human_review``·``confidence=null``로 남긴다. 겹침과 빈 구간도
자동으로 메우지 않고 ``coverage``·``warnings``에 사실대로 남긴다.

저장은 append-only다. 같은 ``(structure_id, taxonomy_version,
extractor_binding_sha256)``으로 다시 계산하면 새 행이 아니라 그 키의 기존 행을
돌려준다. 갱신·삭제 경로는 없다.

조회 응답(:func:`read_manifest_view`)에는 **원문 text를 넣지 않는다.** 제목은
DB에만 남고 wire payload에는 나오지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.object_store import ObjectStore, ObjectStoreError
from ..document_mcp.contracts import validate_para_page_map
from ..document_mcp.errors import DocumentProcessingError
from ..models import (
    ContentObject,
    ContentObjectLocation,
    DocumentSegment,
    DocumentSegmentManifest,
    DocumentStructure,
    DocumentVersion,
    PrespecV4PdfSnapshot,
    RequirementInventoryItem,
)

from .deep_review_validation import validate_document_segments

# 목차 항목과 본문 heading의 문자열 정규화는 개요 절단이 이미 확정한 규칙이다.
# 같은 업무 규칙을 두 벌 만들지 않기 위해 그 helper를 그대로 재사용한다.
from .prespec_overview import (  # noqa: PLC2701 - 개요 절단 heading 규칙 재사용
    _meaningful_heading,
    _normalise_heading_text,
)

logger = logging.getLogger(__name__)

SCHEMA = "bidops.document-segments.v1"
TAXONOMY_VERSION = "bidops.segment-taxonomy.v1"
EXTRACTOR_NAME = "bidops-document-segments"
EXTRACTOR_VERSION = "1"

TAXONOMY_LABELS = (
    "business_eligibility_evaluation",
    "technical_functional",
    "quality_security_constraints",
    "partnership_governance",
)

#: 요구사항 ID 후보. 영문 또는 한글 prefix + 구분자 + 숫자만 받는다. 날짜
#: (``2026-01``)나 조문 번호(``제2-1조``)는 prefix가 문자가 아니라서 걸리지 않는다.
_ID_TOKEN = re.compile(
    r"(?<![0-9A-Za-z가-힣])"
    r"(?P<prefix>[A-Za-z]{2,6}|[가-힣]{2,6})"
    r"[-_]"
    r"(?P<number>[0-9]{1,4}(?:[-.][0-9]{1,4}){0,2})"
    r"(?![0-9A-Za-z가-힣])"
)

#: 표의 요구사항 ID 열 header. 공백을 지운 casefold 문자열로 비교한다.
_ID_COLUMN_HEADERS = frozenset({
    "요구사항id", "요구사항고유번호", "요구사항번호", "요구사항코드", "id", "요구사항식별자",
})
_TITLE_COLUMN_HEADERS = frozenset({
    "요구사항명", "요구사항명칭", "요구사항이름", "제목", "명칭", "요구사항제목",
})

#: 번호형 heading. 장·절 표기, 소수점 번호, 로마 숫자 세 가지만 받는다.
_CHAPTER_HEADING = re.compile(r"^\s*제\s*\d{1,2}\s*[장절편]\s*\S")
_DECIMAL_HEADING = re.compile(r"^\s*\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+\S")
_ROMAN_HEADING = re.compile(r"^\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]{1,4}\s*[.)]\s*\S")

#: 목차 시작 표식과 목차 항목의 쪽 번호 꼬리.
_TOC_MARKERS = frozenset({"목차", "차례", "목 차", "contents", "table of contents"})
_TOC_PAGE_SUFFIX = re.compile(r"(?:\s*[.·…]{2,}\s*|\s{2,})(\d{1,5})\s*$")

_HEADING_MAX_LENGTH = 80
#: 표 밖의 ID는 block 첫머리에 이만큼 나와야 prefix로 확정한다. 산문 안의
#: ``ISO-9001`` 같은 인증 번호를 요구사항으로 만들지 않기 위한 문턱이다.
_MIN_LEADING_OCCURRENCES = 3
#: 확정되지 못했지만 여러 번 보인 prefix는 사람 확인 후보로 남긴다.
_MIN_AMBIGUOUS_OCCURRENCES = 2

#: 국내 제안요청서에서 뜻이 고정된 요구사항 prefix만 label로 연결한다.
#: ``REQ``처럼 목적을 알 수 없는 일반 prefix는 일부러 비운다.
_PREFIX_TAXONOMY: dict[str, tuple[str, ...]] = {
    "SFR": ("technical_functional",),
    "SYR": ("technical_functional",),
    "DAR": ("technical_functional",),
    "INR": ("technical_functional",),
    "TFR": ("technical_functional",),
    "PER": ("quality_security_constraints",),
    "SER": ("quality_security_constraints",),
    "QUR": ("quality_security_constraints",),
    "COR": ("quality_security_constraints",),
    "TER": ("quality_security_constraints",),
    "PMR": ("partnership_governance",),
    "PSR": ("partnership_governance",),
}

#: 제목에서만 본다. 공백을 지운 casefold 제목에 이 토큰이 들어 있으면 label이다.
_TAXONOMY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "business_eligibility_evaluation": (
        "사업개요", "사업목적", "사업기간", "사업예산", "입찰참가자격", "참가자격",
        "제안서평가", "평가배점", "정량평가", "정성평가", "제출서류", "제안서제출",
        "계약방법", "낙찰자결정",
    ),
    "technical_functional": (
        "기능요구사항", "시스템요구사항", "시스템장비구성요구사항", "데이터요구사항",
        "인터페이스요구사항", "기술요구사항", "과업내용", "구축범위",
    ),
    "quality_security_constraints": (
        "품질요구사항", "보안요구사항", "성능요구사항", "제약사항", "제약조건",
        "개인정보", "지식재산", "하자보수", "테스트요구사항", "법규준수",
    ),
    "partnership_governance": (
        "공동수급", "분담이행", "하도급", "추진체계", "보고체계", "역할과책임",
        "사업관리", "프로젝트관리요구사항", "품질보증체계",
    ),
}

#: 추출기 binding의 정체성. 규칙표가 바뀌면 hash가 바뀌고, 그러면 같은 구조라도
#: 새 manifest 행이 만들어진다(기존 행은 그대로 남는다).
_RULES = {
    "id_token": _ID_TOKEN.pattern,
    "id_column_headers": sorted(_ID_COLUMN_HEADERS),
    "title_column_headers": sorted(_TITLE_COLUMN_HEADERS),
    "heading_patterns": [_CHAPTER_HEADING.pattern, _DECIMAL_HEADING.pattern, _ROMAN_HEADING.pattern],
    "toc_markers": sorted(_TOC_MARKERS),
    "toc_page_suffix": _TOC_PAGE_SUFFIX.pattern,
    "min_leading_occurrences": _MIN_LEADING_OCCURRENCES,
    "min_ambiguous_occurrences": _MIN_AMBIGUOUS_OCCURRENCES,
    "prefix_taxonomy": {key: list(value) for key, value in sorted(_PREFIX_TAXONOMY.items())},
    "taxonomy_keywords": {key: list(value) for key, value in sorted(_TAXONOMY_KEYWORDS.items())},
    "taxonomy_labels": list(TAXONOMY_LABELS),
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


RULES_SHA256 = _sha256(_RULES)
EXTRACTOR_BINDING: dict[str, str] = {
    "name": EXTRACTOR_NAME,
    "version": EXTRACTOR_VERSION,
    "taxonomy_version": TAXONOMY_VERSION,
    "rules_sha256": RULES_SHA256,
    "schema": SCHEMA,
}
EXTRACTOR_BINDING_SHA256 = _sha256(EXTRACTOR_BINDING)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _squash(value: str) -> str:
    """비교용 정규화: NFKC → 공백 제거 → casefold."""

    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def _normalize_id(prefix: str, number: str) -> str:
    """정규화 ID: prefix 대문자, 구분자 ``-``, 각 숫자 묶음의 앞 0 제거."""

    parts = [part.lstrip("0") or "0" for part in re.split(r"[-.]", number)]
    return f"{prefix.upper()}-{'-'.join(parts)}"


@dataclass(frozen=True)
class _Block:
    ordinal: int
    block_key: str
    block_type: str
    page: int
    text: str
    table_key: str | None
    row: int | None
    column: int | None


@dataclass
class _Candidate:
    raw_id: str
    normalized_id: str
    raw_prefix: str
    normalized_prefix: str
    locator: dict[str, Any]
    title: str | None
    from_table: bool
    leading: bool
    sort_key: tuple[int, int, int, int] = field(default=(0, 0, 0, 0))


def _locator(block: _Block, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "block_key": block.block_key,
        "page": block.page,
        "ordinal": block.ordinal,
        "table_key": block.table_key,
        "row": block.row,
        "column": block.column,
    }


def _read_blocks(structure_payload: Mapping[str, Any]) -> list[_Block]:
    blocks: list[_Block] = []
    raw_blocks = structure_payload.get("blocks")
    for ordinal, raw in enumerate(raw_blocks if isinstance(raw_blocks, list) else []):
        if not isinstance(raw, Mapping):
            continue
        attributes = raw.get("attributes")
        attributes = attributes if isinstance(attributes, Mapping) else {}
        page = raw.get("page")
        blocks.append(
            _Block(
                ordinal=ordinal,
                block_key=_text(raw.get("block_key")),
                block_type=_text(raw.get("type")).casefold(),
                page=page if isinstance(page, int) and page >= 1 else 1,
                text=_text(raw.get("text")),
                table_key=attributes.get("table_key") if isinstance(attributes.get("table_key"), str) else None,
                row=attributes.get("row") if isinstance(attributes.get("row"), int) else None,
                column=attributes.get("column") if isinstance(attributes.get("column"), int) else None,
            )
        )
    return blocks


# --------------------------------------------------------------------------
# 요구사항 inventory
# --------------------------------------------------------------------------


def _table_columns(blocks: Sequence[_Block]) -> dict[str, tuple[int, int | None, int]]:
    """표별 (ID 열, 제목 열, header 행)을 찾는다.

    header 행은 ID 열 header가 처음 나타난 행이다. 그 아래 행만 값 행으로 읽는다.
    """

    found: dict[str, tuple[int, int | None, int]] = {}
    titles: dict[str, dict[int, int]] = {}
    for block in blocks:
        if block.block_type != "table_cell" or block.table_key is None:
            continue
        if block.row is None or block.column is None:
            continue
        squashed = _squash(block.text)
        if squashed in _ID_COLUMN_HEADERS and block.table_key not in found:
            found[block.table_key] = (block.column, None, block.row)
        elif squashed in _TITLE_COLUMN_HEADERS:
            titles.setdefault(block.table_key, {})[block.row] = block.column
    for table_key, (id_column, _title, header_row) in list(found.items()):
        title_column = titles.get(table_key, {}).get(header_row)
        found[table_key] = (id_column, title_column, header_row)
    return found


def _collect_candidates(blocks: Sequence[_Block]) -> list[_Candidate]:
    """표 열 경로와 문단 경로의 ID 후보를 원문 순서로 모은다."""

    tables = _table_columns(blocks)
    cells: dict[tuple[str, int, int], _Block] = {}
    for block in blocks:
        if block.block_type == "table_cell" and block.table_key and block.row is not None and block.column is not None:
            cells[(block.table_key, block.row, block.column)] = block

    candidates: list[_Candidate] = []
    for block in blocks:
        if block.block_type == "table_cell" and block.table_key in tables:
            id_column, title_column, header_row = tables[block.table_key]
            if block.column != id_column or block.row is None or block.row <= header_row:
                continue
            match = _ID_TOKEN.fullmatch(block.text.strip())
            if match is None:
                continue
            title_cell = cells.get((block.table_key, block.row, title_column)) if title_column is not None else None
            candidates.append(
                _Candidate(
                    raw_id=block.text.strip(),
                    normalized_id=_normalize_id(match.group("prefix"), match.group("number")),
                    raw_prefix=match.group("prefix"),
                    normalized_prefix=match.group("prefix").upper(),
                    locator=_locator(block, "table_cell"),
                    title=title_cell.text.strip() if title_cell and title_cell.text.strip() else None,
                    from_table=True,
                    leading=False,
                    sort_key=(block.ordinal, block.row, block.column, 0),
                )
            )
            continue
        if block.block_type in {"paragraph", "text"}:
            stripped = block.text.lstrip()
            for match in _ID_TOKEN.finditer(block.text):
                leading = match.start() == len(block.text) - len(stripped)
                candidates.append(
                    _Candidate(
                        raw_id=match.group(0),
                        normalized_id=_normalize_id(match.group("prefix"), match.group("number")),
                        raw_prefix=match.group("prefix"),
                        normalized_prefix=match.group("prefix").upper(),
                        locator=_locator(block, "paragraph"),
                        title=None,
                        from_table=False,
                        leading=leading,
                        sort_key=(block.ordinal, 0, 0, match.start()),
                    )
                )
    candidates.sort(key=lambda item: item.sort_key)
    return candidates


def _confirm_prefixes(
    candidates: Sequence[_Candidate],
) -> tuple[set[str], list[dict[str, Any]]]:
    """문서별 prefix 집합을 먼저 확정하고 모호한 것은 따로 남긴다."""

    table_prefixes = {item.normalized_prefix for item in candidates if item.from_table}
    leading_counts: dict[str, int] = {}
    total_counts: dict[str, int] = {}
    raw_forms: dict[str, set[str]] = {}
    first_seen: dict[str, _Candidate] = {}
    for item in candidates:
        total_counts[item.normalized_prefix] = total_counts.get(item.normalized_prefix, 0) + 1
        raw_forms.setdefault(item.normalized_prefix, set()).add(item.raw_prefix)
        first_seen.setdefault(item.normalized_prefix, item)
        if item.leading:
            leading_counts[item.normalized_prefix] = leading_counts.get(item.normalized_prefix, 0) + 1

    confirmed = set(table_prefixes)
    for prefix, count in leading_counts.items():
        if count >= _MIN_LEADING_OCCURRENCES:
            confirmed.add(prefix)

    ambiguous: list[dict[str, Any]] = []
    for prefix in sorted(set(total_counts) - confirmed):
        if total_counts[prefix] < _MIN_AMBIGUOUS_OCCURRENCES:
            continue
        sample = first_seen[prefix]
        ambiguous.append({
            "reason": "prefix_unconfirmed",
            "raw_id": sample.raw_id,
            "raw_prefix": sample.raw_prefix,
            "normalized_prefix": prefix,
            "occurrence_count": total_counts[prefix],
            "locator": sample.locator,
        })
    for prefix in sorted(confirmed):
        forms = raw_forms.get(prefix, set())
        if len(forms) > 1:
            ambiguous.append({
                "reason": "prefix_collision",
                "raw_id": None,
                "raw_prefix": None,
                "normalized_prefix": prefix,
                "occurrence_count": total_counts.get(prefix, len(forms)),
                "locator": None,
            })
    ambiguous.sort(key=lambda item: (item["reason"], item["normalized_prefix"]))
    return confirmed, ambiguous


def _build_inventory(
    blocks: Sequence[_Block],
) -> tuple[list[dict[str, Any]], dict[str, Any], set[str]]:
    candidates = _collect_candidates(blocks)
    confirmed, ambiguous = _confirm_prefixes(candidates)
    items: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for candidate in candidates:
        if candidate.normalized_prefix not in confirmed:
            continue
        seen[candidate.normalized_id] = seen.get(candidate.normalized_id, 0) + 1
        items.append({
            "raw_id": candidate.raw_id,
            "normalized_id": candidate.normalized_id,
            "locator": candidate.locator,
            "title": candidate.title,
            "ordinal": len(items) + 1,
        })
    summary = {
        "expected_ids": sorted(seen),
        "duplicate_ids": sorted(key for key, count in seen.items() if count > 1),
        "ambiguous_items": ambiguous,
        "prefixes": sorted(confirmed),
        "item_count": len(items),
    }
    return items, summary, confirmed


# --------------------------------------------------------------------------
# 경계 탐지와 목차 연결
# --------------------------------------------------------------------------


def _is_numbered_heading(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).strip()
    if not normalized or len(normalized) > _HEADING_MAX_LENGTH:
        return False
    if not (
        _CHAPTER_HEADING.match(normalized)
        or _DECIMAL_HEADING.match(normalized)
        or _ROMAN_HEADING.match(normalized)
    ):
        return False
    return _meaningful_heading(normalized)


def _toc_region(blocks: Sequence[_Block]) -> tuple[set[int], list[str], list[str]]:
    """목차 표식 뒤의 연속 항목 구간을 돌려준다.

    표식이 둘 이상이면 어느 쪽이 정본인지 고를 수 없으므로 목차 구간을 만들지
    않고 경고만 남긴다.
    """

    markers = [
        block.ordinal
        for block in blocks
        if block.block_type in {"paragraph", "text"} and _squash(block.text) in {_squash(item) for item in _TOC_MARKERS}
    ]
    if len(markers) != 1:
        return set(), [], ["toc_marker_ambiguous"] if len(markers) > 1 else []

    indices: set[int] = set()
    entries: list[str] = []
    by_ordinal = {block.ordinal: block for block in blocks}
    for ordinal in range(markers[0] + 1, len(blocks)):
        block = by_ordinal.get(ordinal)
        if block is None or block.block_type not in {"paragraph", "text"}:
            break
        if not block.text.strip():
            indices.add(ordinal)
            continue
        if _TOC_PAGE_SUFFIX.search(unicodedata.normalize("NFKC", block.text)) is None:
            break
        indices.add(ordinal)
        entries.append(_normalise_heading_text(block.text, toc=True))
    indices.add(markers[0])
    return indices, entries, []


def _boundaries(
    blocks: Sequence[_Block],
    toc_indices: set[int],
    requirement_tables: set[str],
) -> list[_Block]:
    found: list[_Block] = []
    seen_tables: set[str] = set()
    for block in blocks:
        if block.ordinal in toc_indices:
            continue
        if block.block_type == "table" and block.table_key in requirement_tables:
            if block.table_key not in seen_tables:
                seen_tables.add(block.table_key)
                found.append(block)
            continue
        if block.block_type in {"paragraph", "text"} and _is_numbered_heading(block.text):
            found.append(block)
    return found


# --------------------------------------------------------------------------
# taxonomy
# --------------------------------------------------------------------------


def _keyword_labels(title: str) -> set[str]:
    squashed = _squash(title)
    return {
        label
        for label, keywords in _TAXONOMY_KEYWORDS.items()
        if any(keyword in squashed for keyword in keywords)
    }


def _prefix_labels(requirement_ids: Iterable[str]) -> set[str]:
    labels: set[str] = set()
    for requirement_id in requirement_ids:
        prefix = requirement_id.split("-", 1)[0]
        labels.update(_PREFIX_TAXONOMY.get(prefix, ()))
    return labels


# --------------------------------------------------------------------------
# manifest payload
# --------------------------------------------------------------------------


def _segment_id(document_version_id: str, start: Mapping[str, Any], end: Mapping[str, Any]) -> str:
    """document version·start/end locator·taxonomy version만으로 만든다.

    제목이나 분류 결과는 identity에 넣지 않는다.
    """

    digest = _sha256({
        "document_version_id": document_version_id,
        "start_locator": dict(start),
        "end_locator": dict(end),
        "taxonomy_version": TAXONOMY_VERSION,
    })
    return f"seg-{digest[:32]}"


def _locator_kind(block: _Block) -> str:
    if block.block_type == "table_cell":
        return "table_cell"
    if block.block_type in {"paragraph", "text"}:
        return "paragraph"
    return "block"


def build_manifest_payload(structure_payload: Mapping[str, Any]) -> dict[str, Any]:
    """clean 구조 payload 하나에서 결정적 manifest payload를 만든다.

    반환값은 wire 계약(``bidops.document-segments.v1``)에 ``inventory_items``를
    더한 것이다. ``inventory_items``는 DB 저장용이며 조회 응답에는 나오지 않는다.
    """

    blocks = _read_blocks(structure_payload)
    warnings: list[str] = []
    items, summary, _confirmed = _build_inventory(blocks)
    if not items:
        warnings.append("inventory_empty")

    tables = _table_columns(blocks)
    toc_indices, toc_entries, toc_warnings = _toc_region(blocks)
    warnings.extend(toc_warnings)
    boundaries = _boundaries(blocks, toc_indices, set(tables))

    heading_titles = [
        _normalise_heading_text(block.text)
        for block in boundaries
        if block.block_type in {"paragraph", "text"}
    ]
    matched = sum(1 for entry in toc_entries if entry and entry in heading_titles)
    toc_summary = {
        "entry_count": len(toc_entries),
        "matched_heading_count": matched,
        "unmatched_entry_count": len(toc_entries) - matched,
    }
    if toc_summary["unmatched_entry_count"]:
        warnings.append(f"toc_entry_unmatched:{toc_summary['unmatched_entry_count']}")

    item_ordinals = {
        index: item["locator"]["ordinal"] for index, item in enumerate(items)
    }
    document_version_id = str(structure_payload.get("document_version_id"))
    segments: list[dict[str, Any]] = []
    titles: list[str | None] = []
    for index, boundary in enumerate(boundaries):
        end_ordinal = (boundaries[index + 1].ordinal - 1) if index + 1 < len(boundaries) else (len(blocks) - 1)
        end_block = blocks[end_ordinal]
        start_locator = _locator(boundary, _locator_kind(boundary))
        end_locator = _locator(end_block, _locator_kind(end_block))
        requirement_ids = sorted({
            items[position]["normalized_id"]
            for position, ordinal in item_ordinals.items()
            if boundary.ordinal <= ordinal <= end_ordinal
        })
        title = boundary.text.strip() or None
        keyword_labels = _keyword_labels(title or "")
        prefix_labels = _prefix_labels(requirement_ids)
        labels = sorted(keyword_labels | prefix_labels)
        conflict = bool(keyword_labels and prefix_labels and not (keyword_labels & prefix_labels))
        status = "classified" if labels and not conflict else "needs_human_review"
        segment_id = _segment_id(document_version_id, start_locator, end_locator)
        if conflict:
            warnings.append(f"taxonomy_conflict:{segment_id}")
        segments.append({
            "segment_id": segment_id,
            "ordinal": index + 1,
            "taxonomy_labels": labels,
            "start_locator": start_locator,
            "end_locator": end_locator,
            "requirement_ids": requirement_ids,
            "source_block_keys": [blocks[ordinal].block_key for ordinal in range(boundary.ordinal, end_ordinal + 1)],
            "classification_source": "deterministic",
            "confidence": None,
            "status": status,
        })
        titles.append(title)

    coverage = _coverage(blocks, segments, toc_summary)
    for gap in coverage["gaps"]:
        warnings.append(f"coverage_gap:{gap['start_ordinal']}-{gap['end_ordinal']}")
    for overlap in coverage["overlaps"]:
        warnings.append(f"coverage_overlap:{overlap['start_ordinal']}-{overlap['end_ordinal']}")
    if not segments:
        warnings.append("no_segment_boundary")

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "structure_id": str(structure_payload.get("structure_id")),
        "document_version_id": document_version_id,
        "source_sha256": str(structure_payload.get("source_sha256")),
        "taxonomy_version": TAXONOMY_VERSION,
        "extractor_binding": dict(EXTRACTOR_BINDING),
        "extractor_binding_sha256": EXTRACTOR_BINDING_SHA256,
        "segments": segments,
        "inventory_summary": summary,
        "coverage": coverage,
        "warnings": warnings,
    }
    payload["payload_sha256"] = _sha256(payload)
    payload["created_at"] = _iso(datetime.now(UTC))
    # ``page_range``·``mapping_status``는 대응표에서 조회 시점에만 계산하는 wire
    # 필드다. 저장 payload의 hash 대상에는 들어가지 않으므로 hash를 계산한 뒤에
    # 기본값(대응표 없음)을 붙인다. 저장 행에도 넣지 않는다.
    for segment in segments:
        segment["page_range"] = None
        segment["mapping_status"] = "unavailable"
    payload["inventory_items"] = items
    payload["segment_titles"] = titles
    return payload


def _coverage(
    blocks: Sequence[_Block],
    segments: Sequence[Mapping[str, Any]],
    toc_summary: Mapping[str, int],
) -> dict[str, Any]:
    """빈 구간과 겹침을 자동으로 메우지 않고 사실대로 센다."""

    spans = sorted(
        (int(segment["start_locator"]["ordinal"]), int(segment["end_locator"]["ordinal"]))
        for segment in segments
    )
    covered: set[int] = set()
    overlaps: list[dict[str, int]] = []
    for start, end in spans:
        current = set(range(start, end + 1))
        shared = sorted(current & covered)
        if shared:
            overlaps.append({"start_ordinal": shared[0], "end_ordinal": shared[-1]})
        covered |= current
    gaps: list[dict[str, int]] = []
    run_start: int | None = None
    for ordinal in range(len(blocks)):
        if ordinal in covered:
            if run_start is not None:
                gaps.append({"start_ordinal": run_start, "end_ordinal": ordinal - 1})
                run_start = None
            continue
        if run_start is None:
            run_start = ordinal
    if run_start is not None:
        gaps.append({"start_ordinal": run_start, "end_ordinal": len(blocks) - 1})
    return {
        "block_count": len(blocks),
        "covered_block_count": len(covered),
        "segment_count": len(segments),
        "gap_count": len(gaps),
        "overlap_count": len(overlaps),
        "gaps": gaps,
        "overlaps": overlaps,
        "needs_human_review_count": sum(1 for segment in segments if segment["status"] == "needs_human_review"),
        "toc": dict(toc_summary),
    }


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def wire_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """조회용 payload. 원문 text(제목·본문)를 포함하지 않는다."""

    return {
        key: value
        for key, value in payload.items()
        if key not in {"inventory_items", "segment_titles"}
    }


# --------------------------------------------------------------------------
# 저장과 조회
# --------------------------------------------------------------------------


def store_manifest(session: Session, structure_payload: Mapping[str, Any]) -> DocumentSegmentManifest:
    """manifest와 자식 행을 한 번만 만든다.

    같은 ``(structure_id, taxonomy_version, extractor_binding_sha256)``이 이미
    있으면 새 행을 만들지 않고 그 행을 돌려준다. 갱신은 하지 않는다.
    """

    structure_id = UUID(str(structure_payload["structure_id"]))
    existing = session.scalar(
        select(DocumentSegmentManifest).where(
            DocumentSegmentManifest.structure_id == structure_id,
            DocumentSegmentManifest.taxonomy_version == TAXONOMY_VERSION,
            DocumentSegmentManifest.extractor_binding_sha256 == EXTRACTOR_BINDING_SHA256,
        )
    )
    if existing is not None:
        return existing

    payload = build_manifest_payload(structure_payload)
    # 계약을 통과하지 못한 payload는 저장하지 않는다. 실패는 호출부의 savepoint가
    # 받아 구조 저장을 되돌리지 않고 경고로 끝낸다.
    validate_document_segments(wire_payload(payload))
    manifest = DocumentSegmentManifest(
        structure_id=structure_id,
        document_version_id=UUID(payload["document_version_id"]),
        source_sha256=payload["source_sha256"],
        taxonomy_version=TAXONOMY_VERSION,
        extractor_binding=dict(EXTRACTOR_BINDING),
        extractor_binding_sha256=EXTRACTOR_BINDING_SHA256,
        inventory_summary=payload["inventory_summary"],
        warnings=payload["warnings"],
        coverage=payload["coverage"],
        payload_sha256=payload["payload_sha256"],
    )
    session.add(manifest)
    session.flush()
    for segment, title in zip(payload["segments"], payload["segment_titles"], strict=True):
        session.add(
            DocumentSegment(
                manifest_id=manifest.id,
                segment_id=segment["segment_id"],
                ordinal=segment["ordinal"],
                taxonomy_labels=segment["taxonomy_labels"],
                title=title,
                start_locator=segment["start_locator"],
                end_locator=segment["end_locator"],
                requirement_ids=segment["requirement_ids"],
                source_block_keys=segment["source_block_keys"],
                classification_source=segment["classification_source"],
                confidence=None,
                status=segment["status"],
            )
        )
    for item in payload["inventory_items"]:
        session.add(
            RequirementInventoryItem(
                manifest_id=manifest.id,
                raw_id=item["raw_id"],
                normalized_id=item["normalized_id"],
                locator=item["locator"],
                title=item["title"],
                ordinal=item["ordinal"],
            )
        )
    session.flush()
    return manifest


def ensure_manifest(session: Session, structure_payload: Mapping[str, Any]) -> DocumentSegmentManifest | None:
    """구조 저장 직후의 공통 helper. 실패해도 구조 저장을 되돌리지 않는다.

    manifest 계산·저장 실패는 구조 자체를 무효로 만들지 않는다. savepoint 안에서
    실행하고, 실패하면 안전한 식별자만 남긴 경고 로그로 끝낸다.
    """

    try:
        with session.begin_nested():
            return store_manifest(session, structure_payload)
    except Exception:  # noqa: BLE001 - 구조 저장을 되돌리지 않기 위한 의도적 경계
        logger.warning(
            "document segment manifest 생성에 실패했습니다",
            extra={"structure_id": str(structure_payload.get("structure_id"))},
        )
        return None


def _manifest_for_structure(session: Session, structure_id: UUID) -> DocumentSegmentManifest | None:
    return session.scalar(
        select(DocumentSegmentManifest).where(
            DocumentSegmentManifest.structure_id == structure_id,
            DocumentSegmentManifest.taxonomy_version == TAXONOMY_VERSION,
            DocumentSegmentManifest.extractor_binding_sha256 == EXTRACTOR_BINDING_SHA256,
        )
    )


def _block_page_ranges(page_map: Mapping[str, Any] | None) -> dict[str, tuple[int, int]] | None:
    """대응표의 매핑된 block만 ``block_key -> (page_first, page_last)``로 편다.

    ``None``은 "대응표 없음"이고 빈 dict는 "대응표는 있으나 매핑 0건"이다. 둘을
    섞으면 미확인과 실제 0건을 구분할 수 없다.
    """

    if page_map is None:
        return None
    return {
        str(block["block_key"]): (int(block["page_first"]), int(block["page_last"]))
        for block in page_map["blocks"]
    }


def _segment_pages(
    source_block_keys: Sequence[str],
    block_pages: Mapping[str, tuple[int, int]] | None,
) -> dict[str, Any]:
    """segment 하나의 ``page_range``·``mapping_status``를 계산한다.

    매핑된 키가 하나도 없으면 페이지를 만들어 내지 않고 ``unavailable``·``null``로
    둔다. 일부만 매핑되면 ``partial``이며 범위는 매핑된 키만으로 계산한다.
    """

    if block_pages is None:
        return {"page_range": None, "mapping_status": "unavailable"}
    mapped = [block_pages[key] for key in source_block_keys if key in block_pages]
    if not mapped:
        return {"page_range": None, "mapping_status": "unavailable"}
    status = "mapped" if len(mapped) == len(source_block_keys) else "partial"
    return {
        "page_range": {"first": min(first for first, _ in mapped), "last": max(last for _, last in mapped)},
        "mapping_status": status,
    }


def read_manifest_view(
    session: Session,
    structure_id: UUID,
    *,
    page_map: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """저장된 manifest를 조회 계약 형태로 읽는다. 원문 text는 넣지 않는다.

    ``page_map``이 있으면 segment마다 ``page_range``·``mapping_status``를 계산해
    붙인다. 없으면 ``unavailable``·``null``이며, 이 값들은 어느 경우에도 저장하지
    않는다.
    """

    block_pages = _block_page_ranges(page_map)
    manifest = _manifest_for_structure(session, structure_id)
    if manifest is None:
        return None
    segments = session.scalars(
        select(DocumentSegment)
        .where(DocumentSegment.manifest_id == manifest.id)
        .order_by(DocumentSegment.ordinal.asc())
    ).all()
    return {
        "schema": SCHEMA,
        "structure_id": str(manifest.structure_id),
        "document_version_id": str(manifest.document_version_id),
        "source_sha256": manifest.source_sha256,
        "taxonomy_version": manifest.taxonomy_version,
        "extractor_binding": dict(manifest.extractor_binding) if isinstance(manifest.extractor_binding, Mapping) else {},
        "extractor_binding_sha256": manifest.extractor_binding_sha256,
        "payload_sha256": manifest.payload_sha256,
        "segments": [{
            "segment_id": row.segment_id,
            "ordinal": row.ordinal,
            "taxonomy_labels": list(row.taxonomy_labels or []),
            "start_locator": dict(row.start_locator or {}),
            "end_locator": dict(row.end_locator or {}),
            "requirement_ids": list(row.requirement_ids or []),
            "source_block_keys": list(row.source_block_keys or []),
            "classification_source": row.classification_source,
            "confidence": None if row.confidence is None else float(row.confidence),
            "status": row.status,
            **_segment_pages(list(row.source_block_keys or []), block_pages),
        } for row in segments],
        "inventory_summary": dict(manifest.inventory_summary or {}),
        "coverage": dict(manifest.coverage or {}),
        "warnings": list(manifest.warnings or []),
        "created_at": _iso(manifest.created_at),
    }


class SegmentViewError(LookupError):
    """조회 경계의 안전한 실패. 내부 경로·원문을 담지 않는다."""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(code)


def _para_page_map_unreadable() -> SegmentViewError:
    """대응표 읽기·검증 실패는 조용히 ``unavailable``로 낮추지 않는다."""

    return SegmentViewError("processing_failed", "문서 작업을 완료할 수 없습니다", status_code=500)


def latest_para_page_map_snapshot(session: Session, structure_id: UUID) -> PrespecV4PdfSnapshot | None:
    """구조를 가리키면서 대응표를 가진 가장 최근 snapshot 하나.

    대응표는 native(``rhwp-svg-pdf``) snapshot만 만든다. 없으면 ``None``이다.
    """

    return session.scalar(
        select(PrespecV4PdfSnapshot)
        .where(
            PrespecV4PdfSnapshot.structure_id == structure_id,
            PrespecV4PdfSnapshot.para_page_map_location_id.is_not(None),
        )
        .order_by(PrespecV4PdfSnapshot.created_at.desc(), PrespecV4PdfSnapshot.id.desc())
        .limit(1)
    )


def _read_para_page_map(
    session: Session,
    snapshot: PrespecV4PdfSnapshot,
    store: ObjectStore,
) -> dict[str, Any]:
    """고정된 객체 version에서 대응표를 읽고 sha256·schema를 다시 확인한다."""

    location = session.get(ContentObjectLocation, snapshot.para_page_map_location_id)
    content = (
        session.get(ContentObject, snapshot.para_page_map_content_object_id)
        if snapshot.para_page_map_content_object_id is not None
        else None
    )
    expected = snapshot.para_page_map_sha256
    if (
        location is None
        or content is None
        or not expected
        or location.content_object_id != content.id
        or location.status != "verified"
        or location.purged_at is not None
        or location.namespace_key != "structure"
        or not location.object_version_id
        or content.sha256 != expected
    ):
        raise _para_page_map_unreadable()
    try:
        data, metadata = store.get(
            "structure",
            location.object_key,
            max_bytes=max(content.size_bytes, 1),
            version_id=location.object_version_id,
        )
    except (ObjectStoreError, OSError, ValueError) as error:
        raise _para_page_map_unreadable() from error
    if (
        metadata.object_version_id != location.object_version_id
        or (location.etag is not None and metadata.etag != location.etag)
        or len(data) != content.size_bytes
        or hashlib.sha256(data).hexdigest() != expected
    ):
        raise _para_page_map_unreadable()
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, ValueError) as error:
        raise _para_page_map_unreadable() from error
    if not isinstance(payload, Mapping):
        raise _para_page_map_unreadable()
    try:
        return validate_para_page_map(payload)
    except DocumentProcessingError as error:
        raise _para_page_map_unreadable() from error


def segments_view(
    session: Session,
    structure_id: UUID,
    store: ObjectStore | None = None,
) -> dict[str, Any]:
    """``GET /api/document-structures/{structure_id}/segments``의 본문.

    구조가 없으면 404 ``not_found``, 문서가 unsafe면 403 ``unsafe_document``,
    manifest가 없으면 404 ``not_found``다. 응답에 원문 text는 없다.

    ``store``는 ``structure`` namespace를 읽는 객체 저장소다. 대응표를 가진
    snapshot이 있는데 저장소가 없거나 읽기·검증이 실패하면 500
    ``processing_failed``이며, 조용히 ``unavailable``로 낮추지 않는다.
    """

    structure = session.get(DocumentStructure, structure_id)
    if structure is None:
        raise SegmentViewError("not_found", "document structure를 찾을 수 없습니다", status_code=404)
    document = session.get(DocumentVersion, structure.document_version_id)
    if document is None or document.safety_status != "safe":
        raise SegmentViewError("unsafe_document", "quarantine 문서는 열람할 수 없습니다", status_code=403)
    snapshot = latest_para_page_map_snapshot(session, structure_id)
    page_map: dict[str, Any] | None = None
    if snapshot is not None:
        if store is None:
            raise _para_page_map_unreadable()
        page_map = _read_para_page_map(session, snapshot, store)
    view = read_manifest_view(session, structure_id, page_map=page_map)
    if view is None:
        raise SegmentViewError("not_found", "document segment manifest를 찾을 수 없습니다", status_code=404)
    return validate_document_segments(view)


def structure_is_readable(session: Session, structure_id: UUID) -> bool:
    """구조가 안전한 문서에 속하는지 확인한다(unsafe면 조회를 막는다)."""

    structure = session.get(DocumentStructure, structure_id)
    if structure is None:
        return False
    document = session.get(DocumentVersion, structure.document_version_id)
    return document is not None and document.safety_status == "safe"


def structure_exists(session: Session, structure_id: UUID) -> bool:
    return session.get(DocumentStructure, structure_id) is not None


def inventory_context(session: Session, structure_ids: Sequence[UUID]) -> dict[str, Any]:
    """묶음의 모든 문서 inventory 합집합과 segment 상태 요약.

    검증(``requirement_inventory``·``segment_coverage``)이 쓰는 유일한 입력이다.
    """

    expected: set[str] = set()
    duplicates: set[str] = set()
    prefixes: set[str] = set()
    needs_review = 0
    gap_count = 0
    overlap_count = 0
    manifest_count = 0
    unique_ids = [structure_id for structure_id in dict.fromkeys(structure_ids)]
    for structure_id in unique_ids:
        manifest = _manifest_for_structure(session, structure_id)
        if manifest is None:
            continue
        manifest_count += 1
        summary = manifest.inventory_summary if isinstance(manifest.inventory_summary, Mapping) else {}
        coverage = manifest.coverage if isinstance(manifest.coverage, Mapping) else {}
        expected.update(str(value) for value in summary.get("expected_ids", []) or [])
        duplicates.update(str(value) for value in summary.get("duplicate_ids", []) or [])
        prefixes.update(str(value) for value in summary.get("prefixes", []) or [])
        needs_review += int(coverage.get("needs_human_review_count", 0) or 0)
        gap_count += int(coverage.get("gap_count", 0) or 0)
        overlap_count += int(coverage.get("overlap_count", 0) or 0)
    return {
        "manifest_count": manifest_count,
        "expected_ids": sorted(expected),
        "duplicate_ids": sorted(duplicates),
        "prefixes": sorted(prefixes),
        "needs_human_review_count": needs_review,
        "gap_count": gap_count,
        "overlap_count": overlap_count,
    }


def observed_requirement_ids(texts: Iterable[str], prefixes: Iterable[str]) -> list[str]:
    """확정된 prefix에 속하는 ID만 텍스트에서 결정적으로 읽는다.

    모델이 보고한 개수를 믿지 않고 텍스트에서 직접 센다. 확정되지 않은 prefix는
    요구사항 ID로 만들지 않는다 — 없는 사실을 만들어 내지 않기 위해서다.
    """

    allowed = {str(prefix).upper() for prefix in prefixes}
    if not allowed:
        return []
    observed: list[str] = []
    for text in texts:
        for match in _ID_TOKEN.finditer(_text(text)):
            if match.group("prefix").upper() not in allowed:
                continue
            observed.append(_normalize_id(match.group("prefix"), match.group("number")))
    return observed


__all__ = [
    "EXTRACTOR_BINDING",
    "EXTRACTOR_BINDING_SHA256",
    "EXTRACTOR_NAME",
    "EXTRACTOR_VERSION",
    "RULES_SHA256",
    "SCHEMA",
    "SegmentViewError",
    "TAXONOMY_LABELS",
    "TAXONOMY_VERSION",
    "build_manifest_payload",
    "ensure_manifest",
    "inventory_context",
    "latest_para_page_map_snapshot",
    "observed_requirement_ids",
    "read_manifest_view",
    "segments_view",
    "store_manifest",
    "structure_exists",
    "structure_is_readable",
    "wire_payload",
]
