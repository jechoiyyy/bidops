"""Bounded HWPX (ZIP + OWPML) extraction."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterable
from typing import Any
from xml.etree import ElementTree as ET

from .contracts import UPSTREAM_COMMIT
from .errors import DocumentProcessingError
from .safety import ProcessorOptions, validate_zip


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element_text(element: ET.Element) -> str:
    chunks: list[str] = []
    for node in element.iter():
        name = _local(node.tag)
        if name in {"t", "text", "char"} and node.text:
            chunks.append(node.text)
        elif name in {"tab", "lineBreak", "br"}:
            chunks.append("\t" if name == "tab" else "\n")
    return "".join(chunks).strip()


def _has_ancestor(element: ET.Element, parents: dict[int, ET.Element], names: set[str]) -> bool:
    cursor = parents.get(id(element))
    while cursor is not None:
        if _local(cursor.tag) in names:
            return True
        cursor = parents.get(id(cursor))
    return False


def _number_attr(element: ET.Element, names: tuple[str, ...], default: float) -> float:
    for key, value in element.attrib.items():
        if _local(key) in names:
            try:
                return float(value)
            except ValueError:
                return default
    return default


def _page_size(root: ET.Element) -> tuple[float, float]:
    for node in root.iter():
        if _local(node.tag) in {"pageDef", "pageDefn"}:
            return (
                _number_attr(node, ("width", "w"), 595.0),
                _number_attr(node, ("height", "h"), 842.0),
            )
    return 595.0, 842.0


def _parse_xml(raw: bytes) -> ET.Element:
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise DocumentProcessingError("unsafe_xml", "문서 XML 선언이 허용되지 않습니다")
    try:
        return ET.fromstring(raw)
    except (ET.ParseError, ValueError) as exc:
        raise DocumentProcessingError("malformed_hwpx", "HWPX XML을 읽을 수 없습니다") from exc


def extract_hwpx(data: bytes, options: ProcessorOptions) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    archive = validate_zip(data, options)
    try:
        names = [info.filename for info in archive.infolist()]
        section_names = sorted(
            name for name in names
            if name.lower().startswith("contents/") and name.lower().endswith(".xml")
            and "section" in name.lower()
        )
        if not section_names:
            section_names = sorted(name for name in names if name.lower().endswith(".xml") and "content" in name.lower())
        if not section_names:
            raise DocumentProcessingError("malformed_hwpx", "HWPX section을 찾을 수 없습니다")
        pages: list[dict[str, Any]] = []
        blocks: list[dict[str, Any]] = []
        warnings: list[str] = []
        for page_number, name in enumerate(section_names, 1):
            try:
                raw = archive.read(name)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise DocumentProcessingError("malformed_archive", "압축 문서를 읽을 수 없습니다") from exc
            root = _parse_xml(raw)
            width, height = _page_size(root)
            pages.append({"number": page_number, "width": width, "height": height, "image_content_object_id": None})
            parents: dict[int, ET.Element] = {}
            for parent in root.iter():
                for child in list(parent):
                    parents[id(child)] = parent
            table_index = 0
            paragraph_index = 0
            for element in root.iter():
                local = _local(element.tag)
                if local == "tbl":
                    table_index += 1
                    table_key = f"table-{page_number}-{table_index}"
                    table_key_block = f"{table_key}-block"
                    blocks.append({
                        "block_key": table_key_block,
                        "parent_block_key": None,
                        "type": "table",
                        "page": page_number,
                        "bbox": None,
                        "text": "",
                        "confidence": None,
                        "attributes": {"table_key": table_key},
                    })
                    rows = [node for node in element.iter() if _local(node.tag) == "tr"]
                    for row_index, row in enumerate(rows):
                        cells = [node for node in list(row) if _local(node.tag) == "tc"]
                        if not cells:
                            cells = [node for node in row.iter() if _local(node.tag) == "tc"]
                        for column_index, cell in enumerate(cells):
                            text = _element_text(cell)
                            blocks.append({
                                "block_key": f"{table_key}-r{row_index}-c{column_index}",
                                "parent_block_key": table_key_block,
                                "type": "table_cell",
                                "page": page_number,
                                "bbox": None,
                                "text": text,
                                "confidence": None,
                                "attributes": {"table_key": table_key, "row": row_index, "column": column_index},
                            })
                elif local == "p" and not _has_ancestor(element, parents, {"tc", "tbl"}):
                    paragraph_index += 1
                    text = _element_text(element)
                    blocks.append({
                        "block_key": f"paragraph-{page_number}-{paragraph_index}",
                        "parent_block_key": None,
                        "type": "paragraph",
                        "page": page_number,
                        "bbox": None,
                        "text": text,
                        "confidence": None,
                        "attributes": {"paragraph_key": f"p-{page_number}-{paragraph_index}"},
                    })
        return pages, blocks, warnings
    finally:
        archive.close()


def extractor_info() -> dict[str, str | None]:
    return {"name": "hwpx-stdlib", "version": "1", "upstream_commit": UPSTREAM_COMMIT}
