"""Conservative, deterministic paragraph/page alignment (para-page-align.v1)."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from typing import Any, Mapping

from .contracts import (
    DEFAULT_MAX_BLOCKS, DEFAULT_MAX_PAGES, PARA_PAGE_KINDS, PARA_PAGE_MAP_RULE, PARA_PAGE_MAP_SCHEMA,
    para_page_map_error, validate_para_page_map,
)
from .errors import DocumentProcessingError


def build_para_page_map(
    blocks: list[dict[str, Any]],
    page_dump: Mapping[str, Any],
    page_text: Mapping[str, Any],
    *,
    original_hwpx: bool,
    paragraph_identities: Mapping[str, tuple[int, int]] | None = None,
    deadline: float | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> dict[str, Any]:
    """Join sanitized R1 artifacts and identities captured by extract_hwpx.

    HWP conversion never uses the HWPX ordinal space. A missing paragraph in a
    source HWPX section invalidates that section's ordinal proof, without failing
    the document or substituting a guessed/text-derived paragraph identity.
    """
    def check_deadline() -> None:
        if deadline is not None and time.monotonic() >= deadline:
            raise DocumentProcessingError("timeout", "문단·페이지 대응 시간이 제한을 초과했습니다", source_preserved=True)

    def integer(value: Any) -> bool:
        return type(value) is int and value >= 0

    try:
        check_deadline()
        count = page_dump["pageCount"]
        if not integer(count) or not 1 <= count <= max_pages or page_dump["schemaVersion"] != "1.0":
            raise para_page_map_error()
        if page_text["schema"] != "bidops.rhwp-page-text.v1" or type(page_text["page_count"]) is not int or page_text["page_count"] != count:
            raise para_page_map_error()
        dump_pages, text_pages = page_dump["pages"], page_text["pages"]
        if not isinstance(dump_pages, list) or not isinstance(text_pages, list) or len(dump_pages) != count or len(text_pages) != count:
            raise para_page_map_error()
        paragraphs: dict[tuple[int, int], dict[str, Any]] = {}
        seen_pages: set[int] = set()
        dump_sections: dict[int, int] = {}
        for page in dump_pages:
            check_deadline()
            index, section = page["pageIndex"], page["section"]
            if not integer(index) or index >= count or index in seen_pages or not integer(section):
                raise para_page_map_error()
            seen_pages.add(index)
            dump_sections[index + 1] = section
            if not isinstance(page["columns"], list) or not isinstance(page["extras"], list):
                raise para_page_map_error()
            groups = [(column["items"], False) for column in page["columns"]] + [(page["extras"], True)]
            for items, extras in groups:
                if not isinstance(items, list):
                    raise para_page_map_error()
                for item in items:
                    para, kind = item["paraIndex"], item["kind"]
                    if not integer(para) or not isinstance(kind, str) or kind not in PARA_PAGE_KINDS:
                        raise para_page_map_error()
                    if (kind in {"hiddenEmptyPara", "wrapAroundPara"}) != extras:
                        raise para_page_map_error()
                    endnote = item.get("isEndnote", False) if extras else item["isEndnote"]
                    if type(endnote) is not bool:
                        raise para_page_map_error()
                    if endnote:
                        continue
                    key = (section, para)
                    if key not in paragraphs:
                        paragraphs[key] = {"section": section, "para_index": para, "page_first": index + 1, "page_last": index + 1, "kind": kind}
                    else:
                        target = paragraphs[key]
                        target["page_first"] = min(target["page_first"], index + 1)
                        target["page_last"] = max(target["page_last"], index + 1)
                        # The range combines every item; kind is the lexically
                        # smallest observed kind, independent of dump traversal.
                        target["kind"] = min(target["kind"], kind)

        texts: dict[int, str] = {}
        for page in text_pages:
            number, text = page["number"], page["text"]
            if not integer(number) or not 1 <= number <= count or number in texts or not isinstance(text, str):
                raise para_page_map_error()
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != page["text_sha256"]:
                raise para_page_map_error()
            if "section" in page and (not integer(page["section"]) or page["section"] != dump_sections[number]):
                raise para_page_map_error()
            texts[number] = text

        identities = (paragraph_identities or {}) if original_hwpx else {}
        source_indices: dict[int, set[int]] = defaultdict(set)
        dump_indices: dict[int, set[int]] = defaultdict(set)
        for section, para in identities.values():
            if not integer(section) or not integer(para):
                raise para_page_map_error()
            source_indices[section].add(para)
        for section, para in paragraphs:
            dump_indices[section].add(para)
        proven_sections = {
            section for section, indices in source_indices.items()
            if indices == dump_indices[section] and indices == set(range(len(indices)))
        }

        cache: dict[str, int | None] = {}

        def unique_page(text: str) -> int | None:
            if text not in cache:
                found = None
                for number, full_text in texts.items():
                    check_deadline()
                    offset = full_text.find(text)
                    if offset >= 0:
                        # Count overlapping occurrences as ambiguity too.
                        if found is not None or full_text.find(text, offset + 1) >= 0:
                            cache[text] = None
                            return None
                        found = number
                cache[text] = found
            return cache[text]

        mapped, unmapped = [], []
        keys: set[str] = set()
        for block in blocks:
            check_deadline()
            key, text, kind = block["block_key"], block["text"], block["type"]
            if not isinstance(key, str) or not key or key in keys or not isinstance(text, str) or not isinstance(kind, str):
                raise para_page_map_error()
            keys.add(key)
            identity = identities.get(key)
            if text.strip() and identity is not None and identity[0] in proven_sections and kind in {"paragraph", "table"}:
                paragraph = paragraphs[identity]
                mapped.append({"block_key": key, "section": identity[0], "para_index": identity[1], "page_first": paragraph["page_first"], "page_last": paragraph["page_last"], "match": "exact"})
            elif text.strip() and (kind == "table_cell" or (not original_hwpx and kind == "paragraph")) and (number := unique_page(text)) is not None:
                mapped.append({"block_key": key, "section": None, "para_index": None, "page_first": number, "page_last": number, "match": "page_text"})
            else:
                unmapped.append(key)
        result = {
            "schema": PARA_PAGE_MAP_SCHEMA, "page_count": count, "paragraph_count": len(paragraphs),
            "paragraphs": [paragraphs[key] for key in sorted(paragraphs)],
            "blocks": sorted(mapped, key=lambda item: item["block_key"]),
            "unmapped_block_keys": sorted(unmapped),
            "mapping": {"blocks_total": len(blocks), "blocks_mapped": len(mapped), "blocks_unmapped": len(unmapped), "rule": PARA_PAGE_MAP_RULE},
        }
        return validate_para_page_map(result, block_keys=keys, max_pages=max_pages, max_blocks=max_blocks)
    except DocumentProcessingError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise para_page_map_error() from exc
