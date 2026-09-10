from __future__ import annotations

import copy
import hashlib
import io
import json
import time
import zipfile

import pytest

from app.deep_review.document_mcp.contracts import (
    para_page_map_bytes, validate_para_page_map,
)
from app.deep_review.document_mcp.errors import DocumentProcessingError
from app.deep_review.document_mcp.hwpx import extract_hwpx
from app.deep_review.document_mcp.para_page_map import build_para_page_map
from app.deep_review.document_mcp.safety import ProcessorOptions


def hwpx(sections: dict[str, str], *, spine: list[str] | None = None, manifest: bool = True) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in sections.items():
            archive.writestr(name, f'<sec>{body}</sec>')
        if manifest:
            items = ''.join(f'<item id="s{i}" href="{name}" media-type="application/xml"/>' for i, name in enumerate(sections))
            refs = ''.join(f'<itemref idref="{ref}"/>' for ref in (spine if spine is not None else [f's{i}' for i in range(len(sections))]))
            archive.writestr("Contents/content.hpf", f'<package><manifest>{items}</manifest><spine>{refs}</spine></package>')
    return output.getvalue()


def paragraph(text: str) -> str:
    return f'<p><run><t>{text}</t></run></p>'


def block(key: str, text: str, kind: str = "paragraph") -> dict:
    return {"block_key": key, "type": kind, "text": text}


def item(para: int, kind: str = "fullParagraph", **extra) -> dict:
    return {"paraIndex": para, "kind": kind, "isEndnote": False, **extra}


def dump_page(number: int, section: int, items: list[dict], extras: list[dict] | None = None) -> dict:
    return {"pageIndex": number - 1, "section": section, "columns": [{"items": items}], "extras": extras or []}


def artifacts(texts: list[str], pages: list[dict] | None = None) -> tuple[dict, dict]:
    return (
        {"schemaVersion": "1.0", "pageCount": len(texts), "pages": pages if pages is not None else [dump_page(i + 1, 0, []) for i in range(len(texts))]},
        {"schema": "bidops.rhwp-page-text.v1", "page_count": len(texts), "pages": [
            {"number": i + 1, "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
            for i, text in enumerate(texts)
        ]},
    )


def test_source_identity_comes_from_spine_and_xml_not_block_order() -> None:
    # The nested text-box paragraph is emitted by the legacy extractor, but is
    # not a body paragraph. Section spine order also differs from filename order.
    source = hwpx({
        "Contents/section0.xml": paragraph("zero"),
        "Contents/section1.xml": '<p><run><t>body</t><shape><p><run><t>nested</t></run></p></shape></run></p>' + paragraph("next"),
    }, spine=["s1", "s0"])
    identities = {}
    pages, blocks, warnings = extract_hwpx(source, ProcessorOptions(), paragraph_identities=identities)
    assert (pages, blocks, warnings) == extract_hwpx(source, ProcessorOptions())
    assert identities == {
        "paragraph-1-1": (1, 0), "paragraph-2-1": (0, 0), "paragraph-2-3": (0, 1),
    }
    dump, text = artifacts(["irrelevant", "irrelevant"], [dump_page(1, 0, [item(0), item(1)]), dump_page(2, 1, [item(0)])])
    result = build_para_page_map(blocks, dump, text, original_hwpx=True, paragraph_identities=identities)
    by_key = {entry["block_key"]: entry for entry in result["blocks"]}
    assert by_key["paragraph-1-1"]["page_first"] == 2
    assert by_key["paragraph-2-3"]["para_index"] == 1
    assert result["unmapped_block_keys"] == ["paragraph-2-2"]


def test_body_control_owner_and_cell_have_distinct_identity() -> None:
    source = hwpx({"Contents/section0.xml": '<p><run><tbl><tr><tc>' + paragraph("unique cell") + '</tc></tr></tbl></run></p>'})
    identities = {}
    _, blocks, _ = extract_hwpx(source, ProcessorOptions(), paragraph_identities=identities)
    assert identities == {"paragraph-1-1": (0, 0), "table-1-1-block": (0, 0)}
    dump, text = artifacts(["unique cell"], [dump_page(1, 0, [item(0, "table")])])
    result = build_para_page_map(blocks, dump, text, original_hwpx=True, paragraph_identities=identities)
    assert [(entry["block_key"], entry["match"], entry["para_index"]) for entry in result["blocks"]] == [
        ("paragraph-1-1", "exact", 0), ("table-1-1-r0-c0", "page_text", None),
    ]
    assert result["unmapped_block_keys"] == ["table-1-1-block"]  # Empty control blocks stay unmapped.


@pytest.mark.parametrize("manifest,spine", [(False, None), (True, ["unknown"]), (True, ["s0", "s0"])])
def test_unproven_package_order_does_not_invent_identity(manifest, spine) -> None:
    identities = {}
    source = hwpx({"Contents/section0.xml": paragraph("text")}, manifest=manifest, spine=spine)
    extract_hwpx(source, ProcessorOptions(), paragraph_identities=identities)
    assert identities == {}


def test_spanning_paragraph_extras_endnotes_and_section_local_indices() -> None:
    blocks = [block("body", "spanning"), block("empty", "  \n"), block("wrap", "wrapped"), block("other", "same index"), block("note", "endnote")]
    dump, text = artifacts(["one", "two", "three"], [
        dump_page(1, 0, [item(0, "partialParagraph"), item(5, isEndnote=True)], [{"kind": "hiddenEmptyPara", "paraIndex": 1}]),
        dump_page(2, 0, [item(0, "partialParagraph"), item(0, "table")], [{"kind": "wrapAroundPara", "paraIndex": 2}]),
        dump_page(3, 1, [item(0)]),
    ])
    result = build_para_page_map(blocks, dump, text, original_hwpx=True, paragraph_identities={"body": (0, 0), "empty": (0, 1), "wrap": (0, 2), "other": (1, 0)})
    by_key = {entry["block_key"]: entry for entry in result["blocks"]}
    assert (by_key["body"]["page_first"], by_key["body"]["page_last"]) == (1, 2)
    assert by_key["wrap"]["page_first"] == 2
    assert by_key["other"]["page_first"] == 3
    assert result["paragraph_count"] == 4
    assert result["unmapped_block_keys"] == ["empty", "note"]


@pytest.mark.parametrize("original_hwpx,kind", [(False, "paragraph"), (False, "table_cell"), (True, "table_cell")])
@pytest.mark.parametrize("value,texts,expected", [
    ("full text", ["prefix full text suffix"], 1),
    ("full text", ["other", "full text"], 2),
    ("full text", ["full text full text"], None),
    ("full text", ["full text", "full text"], None),
    ("aa", ["aaa"], None),
    ("full text", ["full  text"], None),
    ("full text", ["full", "text"], None),
    ("full text extra", ["full text"], None),
    (" full text ", ["full text"], None),
    (" \n", [" \n"], None),
    ("", ["anything"], None),
])
def test_hwp_and_cells_require_single_full_text_occurrence(original_hwpx, kind, value, texts, expected) -> None:
    dump, text = artifacts(texts, [dump_page(i + 1, 0, [item(0)]) for i in range(len(texts))])
    result = build_para_page_map([block("b", value, kind)], dump, text, original_hwpx=original_hwpx, paragraph_identities={"b": (0, 0)})
    if expected is None:
        assert result["blocks"] == []
        assert result["unmapped_block_keys"] == ["b"]
    else:
        assert result["blocks"] == [{"block_key": "b", "section": None, "para_index": None, "page_first": expected, "page_last": expected, "match": "page_text"}]


def test_count_mismatch_disables_section_without_text_or_neighbor_fallback() -> None:
    blocks = [block("body", "unique"), block("empty", ""), block("cell", "cell", "table_cell")]
    dump, text = artifacts(["unique cell"], [dump_page(1, 0, [item(0)])])
    result = build_para_page_map(blocks, dump, text, original_hwpx=True, paragraph_identities={"body": (0, 0), "empty": (0, 1)})
    assert result["unmapped_block_keys"] == ["body", "empty"]
    assert result["blocks"][0]["match"] == "page_text"


def test_equal_count_with_missing_index_does_not_prove_identity() -> None:
    dump, text = artifacts(["a b"], [dump_page(1, 0, [item(0), item(2)])])
    result = build_para_page_map(
        [block("a", "a"), block("b", "b")], dump, text, original_hwpx=True,
        paragraph_identities={"a": (0, 0), "b": (0, 1)},
    )
    assert result["unmapped_block_keys"] == ["a", "b"]


def test_non_body_root_paragraphs_do_not_prove_identity() -> None:
    source = hwpx({"Contents/section0.xml": paragraph("body") + '<wrapper>' + paragraph("unproven") + '</wrapper>'})
    identities = {}
    _, blocks, _ = extract_hwpx(source, ProcessorOptions(), paragraph_identities=identities)
    assert len(blocks) == 2
    assert identities == {}


def test_empty_source_paragraph_still_participates_in_ordinal_proof() -> None:
    source = hwpx({"Contents/section0.xml": '<p/>' + paragraph("body")})
    identities = {}
    _, blocks, _ = extract_hwpx(source, ProcessorOptions(), paragraph_identities=identities)
    assert identities == {"paragraph-1-1": (0, 0), "paragraph-1-2": (0, 1)}
    # Pinned rhwp skips a self-closing p: incomplete indices disable the section.
    dump, text = artifacts(["body"], [dump_page(1, 0, [item(0)])])
    result = build_para_page_map(blocks, dump, text, original_hwpx=True, paragraph_identities=identities)
    assert result["blocks"] == []


def test_zero_mapping_is_valid_and_preview_cannot_change_identity() -> None:
    dump, text = artifacts(["text"], [dump_page(1, 0, [item(0, textPreview="secret document instruction")])])
    result = build_para_page_map([block("b", "text")], dump, text, original_hwpx=True)
    assert result["mapping"]["blocks_mapped"] == 0
    assert "secret" not in para_page_map_bytes(result, max_output_bytes=10000).decode()
    assert validate_para_page_map(result, block_keys={"b"}) == result


def test_map_bytes_ignore_traversal_order_and_are_repeatable() -> None:
    blocks = [block("z", "z"), block("a", "a")]
    dump, text = artifacts(["z", "a"], [dump_page(1, 0, [item(0, "partialParagraph")]), dump_page(2, 0, [item(0), item(1)])])
    kwargs = {"original_hwpx": True, "paragraph_identities": {"z": (0, 0), "a": (0, 1)}}
    one = build_para_page_map(blocks, dump, text, **kwargs)
    dump["pages"].reverse()
    for page in dump["pages"]:
        page["columns"][0]["items"].reverse()
    text["pages"].reverse()
    two = build_para_page_map(list(reversed(blocks)), dump, text, **kwargs)
    assert para_page_map_bytes(one, max_output_bytes=10000) == para_page_map_bytes(two, max_output_bytes=10000)
    assert json.loads(para_page_map_bytes(one, max_output_bytes=10000)) == one


def valid_map() -> dict:
    dump, text = artifacts(["x"], [dump_page(1, 0, [item(0)])])
    return build_para_page_map([block("b", "x")], dump, text, original_hwpx=True, paragraph_identities={"b": (0, 0)})


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(schema="wrong"),
    lambda r: r.update(textPreview="secret"),
    lambda r: r.update(page_count=True),
    lambda r: r.update(paragraph_count=2),
    lambda r: r["paragraphs"].append(copy.deepcopy(r["paragraphs"][0])),
    lambda r: r["paragraphs"][0].update(kind="invented"),
    lambda r: r["paragraphs"][0].update(section=None),
    lambda r: r["blocks"][0].update(page_first=0),
    lambda r: r["blocks"][0].update(page_last=2),
    lambda r: r["blocks"][0].update(section=True),
    lambda r: r["blocks"][0].update(para_index=2),
    lambda r: r["blocks"][0].update(match="fuzzy"),
    lambda r: r["blocks"][0].update(match="page_text"),
    lambda r: r["blocks"].append(copy.deepcopy(r["blocks"][0])),
    lambda r: r["unmapped_block_keys"].append("b"),
    lambda r: r["mapping"].update(blocks_mapped=False),
    lambda r: r["mapping"].update(rule="unknown"),
])
def test_contract_rejects_forged_or_inconsistent_mapping(mutation) -> None:
    result = valid_map()
    mutation(result)
    with pytest.raises(DocumentProcessingError) as caught:
        validate_para_page_map(result)
    assert caught.value.code == "para_page_map_invalid"
    assert "secret" not in str(caught.value)
    assert caught.value.source_preserved


def test_contract_requires_exact_block_partition_and_artifact_budget() -> None:
    result = valid_map()
    with pytest.raises(DocumentProcessingError, match="대응표 계약"):
        validate_para_page_map(result, block_keys={"different"})
    size = len(para_page_map_bytes(result, max_output_bytes=10000))
    with pytest.raises(DocumentProcessingError) as caught:
        para_page_map_bytes(result, max_output_bytes=size - 1)
    assert caught.value.code == "output_size_limit"


@pytest.mark.parametrize("mutation", [
    lambda d, t: d.update(pageCount=True),
    lambda d, t: d["pages"][0].update(pageIndex=1),
    lambda d, t: d["pages"][0].update(section=True),
    lambda d, t: d["pages"][0]["columns"][0]["items"][0].update(isEndnote="false"),
    lambda d, t: t["pages"][0].update(text_sha256="0" * 64),
    lambda d, t: t["pages"][0].update(number=True),
    lambda d, t: t["pages"][0].update(section=9),
])
def test_invalid_input_artifacts_are_safe_failures(mutation) -> None:
    dump, text = artifacts(["x"], [dump_page(1, 0, [item(0)])])
    mutation(dump, text)
    with pytest.raises(DocumentProcessingError) as caught:
        build_para_page_map([], dump, text, original_hwpx=False)
    assert caught.value.code == "para_page_map_invalid"


def test_alignment_respects_shared_deadline() -> None:
    dump, text = artifacts(["x"])
    with pytest.raises(DocumentProcessingError) as caught:
        build_para_page_map([], dump, text, original_hwpx=False, deadline=time.monotonic() - 1)
    assert caught.value.code == "timeout"


def test_mapping_honors_explicit_page_limit_instead_of_hardcoding_default() -> None:
    dump, text = artifacts(["x"] * 513)
    result = build_para_page_map([], dump, text, original_hwpx=False, max_pages=513)
    assert para_page_map_bytes(result, max_output_bytes=10000, max_pages=513)
    with pytest.raises(DocumentProcessingError) as caught:
        build_para_page_map([], dump, text, original_hwpx=False, max_pages=512)
    assert caught.value.code == "para_page_map_invalid"
