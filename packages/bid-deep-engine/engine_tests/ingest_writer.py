"""Test-only stand-in for upstream `bidops.ingest.writer` (not vendored: BidOps owns storage).

Only the two functions the vendored `test_models.py`/`test_normalize.py` import are kept,
with the upstream serialization rules (declaration key order, non-escaped Korean,
indent 2, trailing newline; `write_bundle` overwrites bundle.json and raw.<key>.json only).
"""

import json
from pathlib import Path

from pydantic import BaseModel

from bid_deep_engine.ingest.models import NoticeBundle, RawDoc


def dump_json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"


def write_bundle(out_dir: Path, bundle: NoticeBundle, raws: dict[str, RawDoc]) -> Path:
    slug_dir = out_dir / bundle.slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    (slug_dir / "bundle.json").write_text(dump_json(bundle), encoding="utf-8")
    for key, raw in raws.items():
        (slug_dir / f"raw.{key}.json").write_text(dump_json(raw), encoding="utf-8")
    return slug_dir
