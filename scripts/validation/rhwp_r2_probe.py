"""Run R2 in the isolated R0 image; emit counts/hashes only, never source text."""

import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, "/app/web/backend")

from app.deep_review.document_mcp.contracts import para_page_map_bytes, validate_para_page_map
from app.deep_review.document_mcp.hwpx import extract_hwpx
from app.deep_review.document_mcp.para_page_map import build_para_page_map
from app.deep_review.document_mcp.processor import DocumentProcessor
from app.deep_review.document_mcp.safety import ProcessorOptions


options = ProcessorOptions(
    renderer="rhwp-svg-pdf", prepare_pdf=True, ocr=False,
    timeout_seconds=300, max_output_bytes=64 * 1024 * 1024, max_pdf_objects=100_000,
)
samples = []
for name, filename, media_type in (
    ("notice-142", "notice-142.hwpx", "application/hwp+zip"),
    ("notice-10-rfp", "notice-10-rfp.hwp", "application/x-hwp"),
    ("notice-10-sow", "notice-10-sow.hwp", "application/x-hwp"),
):
    source_path = Path("/input") / filename
    source = source_path.read_bytes()
    started = time.monotonic()
    # This measures conversion only and makes no new ClamAV clean assertion.
    processed = DocumentProcessor().process(source, media_type, options)
    processor_seconds = time.monotonic() - started
    result = processed.para_page_map
    encoded = processed.para_page_map_bytes
    validate_para_page_map(result, block_keys={block["block_key"] for block in processed["blocks"]})
    assert encoded == para_page_map_bytes(result, max_output_bytes=options.max_output_bytes)
    assert "para_page_map" not in dict(processed)
    assert "textPreview" not in encoded.decode()
    assert source_path.read_bytes() == source == processed.original_bytes

    started = time.monotonic()
    identities = {}
    _, blocks, _ = extract_hwpx(
        processed.hwpx_bytes, options,
        paragraph_identities=identities if media_type == "application/hwp+zip" else None,
    )
    assert blocks == processed["blocks"]
    repeated = build_para_page_map(
        blocks, processed.page_dump, processed.page_text,
        original_hwpx=media_type == "application/hwp+zip", paragraph_identities=identities,
        deadline=time.monotonic() + 300,
    )
    repeated_bytes = para_page_map_bytes(repeated, max_output_bytes=options.max_output_bytes)
    assert encoded == repeated_bytes
    mapped_keys = {entry["block_key"] for entry in result["blocks"]}
    by_type = {}
    for block in blocks:
        counts = by_type.setdefault(block["type"], {"total": 0, "mapped": 0, "empty": 0})
        counts["total"] += 1
        counts["mapped"] += block["block_key"] in mapped_keys
        counts["empty"] += not block["text"].strip()
    record = {
        "sample": name, "source_sha256": hashlib.sha256(source).hexdigest(),
        "processor_seconds": round(processor_seconds, 3),
        "repeat_extraction_alignment_seconds": round(time.monotonic() - started, 3),
        "page_count": result["page_count"], "paragraph_count": result["paragraph_count"],
        "mapping": result["mapping"], "by_type": by_type,
        "match_counts": {kind: sum(entry["match"] == kind for entry in result["blocks"]) for kind in ("exact", "page_text")},
        "mapping_percent": round(100 * len(mapped_keys) / len(blocks), 2),
        "map_bytes": len(encoded), "map_sha256": hashlib.sha256(encoded).hexdigest(),
        "repeat_map_sha256": hashlib.sha256(repeated_bytes).hexdigest(),
        "repeat_bytes_identical": True, "structure_blocks_unchanged": True,
        "unmapped_does_not_fail_document": True,
    }
    samples.append(record)
    print(json.dumps(record, sort_keys=True), flush=True)

Path("/out/metrics.json").write_text(json.dumps({
    "schema": "bidops.rhwp-r2-metrics.v1", "samples": samples,
}, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
