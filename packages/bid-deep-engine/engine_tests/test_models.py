import json

import pytest
from pydantic import ValidationError

from bid_deep_engine.ingest.models import (
    Block,
    NoticeBundle,
    PageBound,
    RawDoc,
    RawMeta,
    RawTable,
    SourceFile,
)
from engine_tests.ingest_writer import dump_json, write_bundle


def make_source(**kw) -> SourceFile:
    base = dict(
        path="a/제안요청서.hwpx", format="hwpx", role="primary", size_bytes=3, sha256="0" * 64
    )
    return SourceFile(**{**base, **kw})


def make_bundle(**kw) -> NoticeBundle:
    base = dict(
        slug="mofa-homepage-maint-2027",
        title="2027년 외교부 홈페이지 유지관리 용역",
        manifest_matched=True,
        files=[make_source(), make_source(path="a/제안요청서.pdf", format="pdf", role="reference")],
        primary_format="hwpx",
        status="ok",
        warnings=["pdf digits << primary digits"],
        created_at="2026-10-22T09:00:00+09:00",
    )
    return NoticeBundle(**{**base, **kw})


def make_hwpx_raw() -> RawDoc:
    return RawDoc(
        slug="mofa-homepage-maint-2027",
        format="hwpx",
        source_paths=["a/제안요청서.hwpx"],
        blocks=[
            Block(idx=0, kind="paragraph", text="사업비 430,000,000원"),
            Block(idx=1, kind="table", text="a | b / 1 | 2", table_id="T001"),
        ],
        tables=[RawTable(id="T001", block_idx=1, rows=[["a", "b"], ["1", "2"]])],
        meta=RawMeta(
            chars=20,
            digits=10,
            paragraphs=1,
            tables=1,
            extractor="hwpx-lxml",
            extractor_version="5.0",
        ),
    )


def make_pdf_raw() -> RawDoc:
    return RawDoc(
        slug="mofa-homepage-maint-2027",
        format="pdf",
        source_paths=["a/제안요청서.pdf"],
        blocks=[Block(idx=0, kind="paragraph", text="1쪽 본문", page=1)],
        tables=[],
        page_texts=["1쪽 본문"],
        page_bounds=[PageBound(file="a/제안요청서.pdf", first_page=1, last_page=1)],
        meta=RawMeta(
            chars=5,
            digits=1,
            paragraphs=1,
            tables=0,
            pages=1,
            extractor="pypdf",
            extractor_version="6.0",
        ),
    )


@pytest.mark.parametrize("model", [make_bundle(), make_hwpx_raw(), make_pdf_raw()])
def test_roundtrip(model):
    again = type(model).model_validate(json.loads(dump_json(model)))
    assert again == model


def test_defaults():
    raw = make_hwpx_raw()
    assert raw.page_texts is None and raw.page_bounds is None
    assert raw.blocks[0].table_id is None and raw.blocks[0].page is None
    assert raw.meta.pages is None and raw.meta.warnings == []
    assert raw.meta.warnings is not make_hwpx_raw().meta.warnings


def test_dump_deterministic_and_unescaped():
    a, b = dump_json(make_hwpx_raw()), dump_json(make_hwpx_raw())
    assert a == b
    assert a.endswith("}\n")
    assert "사업비 430,000,000원" in a
    assert "\\u" not in a


def test_key_order_follows_declaration():
    data = json.loads(dump_json(make_bundle()))
    assert list(data) == list(NoticeBundle.model_fields)
    raw = json.loads(dump_json(make_hwpx_raw()))
    assert list(raw) == list(RawDoc.model_fields)
    assert list(raw["meta"]) == list(RawMeta.model_fields)


def test_write_bundle(tmp_path):
    out = tmp_path / "out"
    slug_dir = out / "mofa-homepage-maint-2027"
    slug_dir.mkdir(parents=True)
    (slug_dir / "keep.txt").write_text("keep", encoding="utf-8")
    (slug_dir / "bundle.json").write_text("stale", encoding="utf-8")

    bundle = make_bundle()
    raws = {"hwpx": make_hwpx_raw(), "pdf": make_pdf_raw()}
    result = write_bundle(out, bundle, raws)

    assert result == slug_dir
    assert sorted(p.name for p in slug_dir.iterdir()) == [
        "bundle.json",
        "keep.txt",
        "raw.hwpx.json",
        "raw.pdf.json",
    ]
    assert (slug_dir / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (slug_dir / "bundle.json").read_text(encoding="utf-8") == dump_json(bundle)
    assert (slug_dir / "raw.pdf.json").read_text(encoding="utf-8") == dump_json(raws["pdf"])
    assert RawDoc.model_validate_json((slug_dir / "raw.hwpx.json").read_bytes()) == raws["hwpx"]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: make_source(role="ignored"),
        lambda: make_source(format="hwpz"),
        lambda: make_bundle(status="partial"),
        lambda: Block(idx=0, kind="heading", text=""),
        lambda: RawMeta(
            chars=0, digits=0, paragraphs=0, tables=0, extractor="x", extractor_version=""
        ),
    ],
)
def test_literal_rejects_out_of_range(factory):
    with pytest.raises(ValidationError):
        factory()


def test_m0_03_values_are_accepted():
    assert make_source(role="skipped").role == "skipped"
    assert make_bundle(status="degraded").status == "degraded"
