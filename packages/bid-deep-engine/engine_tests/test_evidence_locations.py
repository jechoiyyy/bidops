"""REV-03 T1~T3: source hash와 인용의 파일별 물리 페이지 정확 위치."""

import hashlib
import unicodedata

import pytest
from pydantic import ValidationError

from bid_deep_engine.analysis.evidence import verify
from bid_deep_engine.analysis.evidence_locations import (
    EvidenceLocationRecord,
    EvidenceLocations,
    build_evidence_locations,
    canonical_source_payload,
    evidence_id,
    locate_evidence,
    project_evidence,
    resolve_locations,
    source_hash,
)
from bid_deep_engine.analysis.schemas import Evidence, SourceLocation
from bid_deep_engine.ingest.models import (
    NoticeBundle,
    PageBound,
    RawDoc,
    RawMeta,
    RfpDocument,
    Section,
    SourceFile,
    SourceQuality,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _source(path: str, *, format: str = "pdf", sha256: str | None = None) -> SourceFile:
    return SourceFile(
        path=path,
        format=format,
        role="reference",
        size_bytes=1,
        sha256=_sha(path) if sha256 is None else sha256,
    )


def _bundle(*sources: SourceFile) -> NoticeBundle:
    return NoticeBundle(
        slug="fixture",
        title="합성 공고",
        manifest_matched=True,
        files=list(sources),
        primary_format=sources[0].format,
        status="ok",
        created_at="2026-10-24T00:00:00+09:00",
    )


def _meta(format: str, pages: int | None) -> RawMeta:
    extractor = "pypdf" if format == "pdf" else "hwpx-lxml"
    return RawMeta(
        chars=0,
        digits=0,
        paragraphs=0,
        tables=0,
        pages=pages,
        extractor=extractor,
        extractor_version="fixture",
    )


def _raw(
    format: str,
    source_paths: list[str],
    *,
    page_texts: list[str] | None = None,
    page_bounds: list[PageBound] | None = None,
) -> RawDoc:
    return RawDoc(
        slug="fixture",
        format=format,
        source_paths=source_paths,
        blocks=[],
        tables=[],
        page_texts=page_texts,
        page_bounds=page_bounds,
        meta=_meta(format, None if page_texts is None else len(page_texts)),
    )


def _document(full_text: str, source_files: list[str]) -> RfpDocument:
    return RfpDocument(
        slug="fixture",
        title="합성 공고",
        source_files=source_files,
        primary_format="pdf",
        sections=[],
        requirements=[],
        tables=[],
        full_text=full_text,
        source_quality=SourceQuality(
            primary_format="pdf",
            primary_chars=len(full_text),
            primary_digits=0,
            has_tables=False,
            requirements_found=0,
            sections_mapped_to_pages=0,
        ),
    )


def test_t1_global_page_maps_to_file_local_page():
    attachment = _source("files/attachment.pdf")
    rfp = _source("files/rfp.pdf")
    pages = [f"첨부 {page}" for page in range(1, 7)] + [f"RFP {page}" for page in range(1, 16)]
    pages[-1] = "마지막 쪽의 정확한 근거 문구"
    raw = _raw(
        "pdf",
        [attachment.path, rfp.path],
        page_texts=pages,
        page_bounds=[
            PageBound(file=attachment.path, first_page=1, last_page=6),
            PageBound(file=rfp.path, first_page=7, last_page=21),
        ],
    )

    locations, status = resolve_locations("정확한 근거 문구", _bundle(attachment, rfp), [raw])

    assert status == "exact"
    assert locations == [
        SourceLocation(
            file=rfp.path,
            file_sha256=rfp.sha256,
            page=15,
            start=7,
            end=16,
        )
    ]


def test_t2_repeated_quote_nfc_whitespace_offsets_and_verified_independence():
    source = _source("notice.pdf")
    decomposed = unicodedata.normalize("NFD", "상주 인력")
    page3 = f"앞  {decomposed}\n 3명 뒤"
    page9 = "반복 상주 인력  3명 끝"
    pages = [""] * 9
    pages[2] = page3
    pages[8] = page9
    raw = _raw(
        "pdf",
        [source.path],
        page_texts=pages,
        page_bounds=[PageBound(file=source.path, first_page=1, last_page=9)],
    )
    bundle = _bundle(source)

    locations, status = resolve_locations("상주  인력 3명", bundle, [raw])

    assert status == "ambiguous"
    assert [location.page for location in locations] == [3, 9]
    nfc_pages = [unicodedata.normalize("NFC", page3), unicodedata.normalize("NFC", page9)]
    for location, page in zip(locations, nfc_pages, strict=True):
        assert page[location.start : location.end] in {"상주 인력\n 3명", "상주 인력  3명"}
        assert (
            unicodedata.normalize("NFC", page[location.start : location.end])
            == page[location.start : location.end]
        )

    unverified = Evidence(quote="상주  인력 3명", page=99, verified=False, repaired=True)
    located = locate_evidence(unverified, bundle, [raw])
    assert located.verified is False and located.repaired is True and located.page == 99
    assert located.location_status == "ambiguous" and list(located.locations) == locations


def test_t2_repaired_quote_is_searched_exactly_on_current_page_only():
    source = _source("notice.pdf")
    page = "계약 상대자는 지정 장소에 상주하여야 한다."
    raw = _raw(
        "pdf",
        [source.path],
        page_texts=[page],
        page_bounds=[PageBound(file=source.path, first_page=1, last_page=1)],
    )
    section = Section(
        id="S001",
        heading="계약",
        level=1,
        kind="contract",
        block_start=0,
        block_end=0,
        text=page,
        page_start=77,
    )
    checked, _ = verify(
        Evidence(quote="계약 상대자는 지정 장소에 상쥬하여야 한다.", section_id="S001"),
        page,
        [section],
    )
    assert checked.verified is True and checked.repaired is True and checked.page == 77

    located = locate_evidence(checked, _bundle(source), [raw])
    assert located.quote == page
    assert located.location_status == "exact"
    assert located.locations[0].page == 1  # legacy section 시작 77을 사용하지 않는다


def test_t3_hwp_logical_pages_and_cross_page_quote_are_unavailable():
    hwp = _source("notice.hwp", format="hwp")
    logical_raw = _raw(
        "hwp",
        [hwp.path],
        page_texts=["논리 분할 문구"],
        page_bounds=[PageBound(file=hwp.path, first_page=1, last_page=1)],
    )
    assert resolve_locations("논리 분할 문구", _bundle(hwp), [logical_raw]) == (
        [],
        "unavailable",
    )

    pdf = _source("notice.pdf")
    split_raw = _raw(
        "pdf",
        [pdf.path],
        page_texts=["페이지 경계", "문구는 위치 없음"],
        page_bounds=[PageBound(file=pdf.path, first_page=1, last_page=2)],
    )
    assert resolve_locations("페이지 경계 문구", _bundle(pdf), [split_raw]) == (
        [],
        "unavailable",
    )


@pytest.mark.parametrize(
    "path",
    ["/absolute.pdf", "../escape.pdf", "a/../../escape.pdf", r"a\windows.pdf", "C:/x.pdf"],
)
def test_legacy_source_file_accepts_unsafe_path_but_resolver_does_not_connect(path: str):
    source = _source(path)
    raw = _raw(
        "pdf",
        [path],
        page_texts=["근거"],
        page_bounds=[PageBound(file=path, first_page=1, last_page=1)],
    )
    assert resolve_locations("근거", _bundle(source), [raw]) == ([], "unavailable")
    with pytest.raises(ValidationError):
        SourceLocation(file=path, file_sha256=_sha("x"), page=1, start=0, end=1)


@pytest.mark.parametrize("bad_hash", ["A" * 64, "0" * 63, "g" * 64, ""])
def test_legacy_source_file_accepts_bad_sha_but_resolver_does_not_connect(bad_hash: str):
    source = _source("notice.pdf", sha256=bad_hash)
    raw = _raw(
        "pdf",
        [source.path],
        page_texts=["근거"],
        page_bounds=[PageBound(file=source.path, first_page=1, last_page=1)],
    )
    assert resolve_locations("근거", _bundle(source), [raw]) == ([], "unavailable")
    with pytest.raises(ValidationError):
        SourceLocation(file="notice.pdf", file_sha256=bad_hash, page=1, start=0, end=1)


@pytest.mark.parametrize(
    "values",
    [
        {"page": 0, "start": 0, "end": 1},
        {"page": True, "start": 0, "end": 1},
        {"page": 1, "start": -1, "end": 1},
        {"page": 1, "start": 1, "end": 1},
        {"page": 1, "start": 0, "end": "1"},
    ],
)
def test_source_location_rejects_non_physical_or_non_integer_span(values: dict[str, object]):
    with pytest.raises(ValidationError):
        SourceLocation(file="notice.pdf", file_sha256=_sha("x"), **values)


def test_bad_exact_mapping_overlap_invalid_sha_and_basename_guess_are_unavailable():
    good = _source("folder/notice.pdf")
    bundle = _bundle(good)
    overlap = _raw(
        "pdf",
        [good.path],
        page_texts=["근거"],
        page_bounds=[
            PageBound(file=good.path, first_page=1, last_page=1),
            PageBound(file=good.path, first_page=1, last_page=1),
        ],
    )
    assert resolve_locations("근거", bundle, [overlap])[1] == "unavailable"

    inverted = _raw(
        "pdf",
        [good.path],
        page_texts=["근거"],
        page_bounds=[PageBound(file=good.path, first_page=2, last_page=1)],
    )
    assert resolve_locations("근거", bundle, [inverted])[1] == "unavailable"

    basename_only = _raw(
        "pdf",
        ["other/notice.pdf"],
        page_texts=["근거"],
        page_bounds=[PageBound(file="notice.pdf", first_page=1, last_page=1)],
    )
    assert resolve_locations("근거", bundle, [basename_only])[1] == "unavailable"

    invalid = SourceFile(
        path="folder/notice.pdf", format="pdf", role="reference", size_bytes=1, sha256="bad"
    )
    bad_bundle = _bundle(invalid)
    assert resolve_locations("근거", bad_bundle, [overlap])[1] == "unavailable"


def test_noncontinuous_bounds_invalidate_only_that_file_and_preserve_good_file():
    bad = _source("bad.pdf")
    good = _source("good.pdf")
    raw = _raw(
        "pdf",
        [bad.path, good.path],
        page_texts=["needle bad p1", "needle bad p2", "needle good"],
        page_bounds=[
            PageBound(file=bad.path, first_page=1, last_page=1),
            PageBound(file=bad.path, first_page=2, last_page=2),
            PageBound(file=good.path, first_page=3, last_page=3),
        ],
    )

    locations, status = resolve_locations("needle", _bundle(bad, good), [raw])

    assert status == "exact"
    assert [(item.file, item.page) for item in locations] == [(good.path, 1)]


def test_duplicate_invalid_file_claim_overlapping_good_file_makes_page_unavailable():
    bad = _source("bad.pdf")
    good = _source("good.pdf")
    raw = _raw(
        "pdf",
        [bad.path, good.path],
        page_texts=["needle"],
        page_bounds=[
            PageBound(file=bad.path, first_page=1, last_page=1),
            PageBound(file=bad.path, first_page=1, last_page=1),
            PageBound(file=good.path, first_page=1, last_page=1),
        ],
    )

    assert resolve_locations("needle", _bundle(bad, good), [raw]) == ([], "unavailable")


@pytest.mark.parametrize("kind", ["invalid-hash", "unsafe-path", "missing-file"])
def test_unconnectable_claim_overlapping_good_file_makes_page_unavailable(kind: str):
    good = _source("good.pdf")
    if kind == "invalid-hash":
        bad_path = "bad.pdf"
        bundle = _bundle(good, _source(bad_path, sha256="bad"))
    elif kind == "unsafe-path":
        bad_path = "../bad.pdf"
        bundle = _bundle(good, _source(bad_path))
    else:
        bad_path = "missing.pdf"
        bundle = _bundle(good)
    raw = _raw(
        "pdf",
        [good.path, bad_path],
        page_texts=["needle"],
        page_bounds=[
            PageBound(file=good.path, first_page=1, last_page=1),
            PageBound(file=bad_path, first_page=1, last_page=1),
        ],
    )

    assert resolve_locations("needle", bundle, [raw]) == ([], "unavailable")


@pytest.mark.parametrize("kind", ["invalid-hash", "unsafe-path", "missing-file"])
def test_unconnectable_claim_on_other_page_preserves_good_file(kind: str):
    good = _source("good.pdf")
    if kind == "invalid-hash":
        bad_path = "bad.pdf"
        bundle = _bundle(good, _source(bad_path, sha256="bad"))
    elif kind == "unsafe-path":
        bad_path = "../bad.pdf"
        bundle = _bundle(good, _source(bad_path))
    else:
        bad_path = "missing.pdf"
        bundle = _bundle(good)
    raw = _raw(
        "pdf",
        [good.path, bad_path],
        page_texts=["needle good", "needle bad"],
        page_bounds=[
            PageBound(file=good.path, first_page=1, last_page=1),
            PageBound(file=bad_path, first_page=2, last_page=2),
        ],
    )

    locations, status = resolve_locations("needle", bundle, [raw])

    assert status == "exact"
    assert [(item.file, item.page) for item in locations] == [(good.path, 1)]


@pytest.mark.parametrize("first", [0, 1])
def test_out_of_range_claim_overlap_is_clamped_to_actual_pages(first: int):
    good = _source("good.pdf")
    raw = _raw(
        "pdf",
        [good.path, "missing.pdf"],
        page_texts=["needle"],
        page_bounds=[
            PageBound(file=good.path, first_page=1, last_page=1),
            PageBound(file="missing.pdf", first_page=first, last_page=10**12),
        ],
    )

    assert resolve_locations("needle", _bundle(good), [raw]) == ([], "unavailable")


def test_out_of_range_claim_on_other_actual_page_preserves_good_file():
    good = _source("good.pdf")
    raw = _raw(
        "pdf",
        [good.path, "missing.pdf"],
        page_texts=["needle good", "needle missing"],
        page_bounds=[
            PageBound(file=good.path, first_page=1, last_page=1),
            PageBound(file="missing.pdf", first_page=2, last_page=10**12),
        ],
    )

    locations, status = resolve_locations("needle", _bundle(good), [raw])

    assert status == "exact"
    assert [(item.file, item.page) for item in locations] == [(good.path, 1)]


def test_overlap_duplicate_and_gap_do_not_discard_unrelated_valid_locations():
    overlap_a = _source("overlap-a.pdf")
    overlap_b = _source("overlap-b.pdf")
    duplicate = _source("duplicate.pdf")
    good = _source("good.pdf")
    raw = _raw(
        "pdf",
        [overlap_a.path, overlap_b.path, duplicate.path, good.path],
        page_texts=["needle"] * 8,
        page_bounds=[
            PageBound(file=overlap_a.path, first_page=1, last_page=2),
            PageBound(file=overlap_b.path, first_page=2, last_page=3),
            # global 4 is a gap
            PageBound(file=duplicate.path, first_page=5, last_page=5),
            PageBound(file=duplicate.path, first_page=5, last_page=5),
            PageBound(file=good.path, first_page=7, last_page=8),
        ],
    )

    locations, status = resolve_locations(
        "needle", _bundle(overlap_a, overlap_b, duplicate, good), [raw]
    )

    assert status == "ambiguous"
    assert [(item.file, item.page) for item in locations] == [(good.path, 1), (good.path, 2)]


def test_canonical_payload_null_empty_order_and_golden_hash():
    z = _source("z.pdf")
    a = _source("a.hwpx", format="hwpx")
    bundle = _bundle(z, a)
    document = _document("원문 전문", [z.path, a.path])
    pdf = _raw("pdf", [z.path], page_texts=[], page_bounds=[])
    hwpx = _raw("hwpx", [a.path])

    payload = canonical_source_payload(bundle, document, [pdf, hwpx])

    assert payload == {
        "schema_version": 1,
        "source_files": [
            {"path": z.path, "sha256": z.sha256},
            {"path": a.path, "sha256": a.sha256},
        ],
        "full_text": "원문 전문",
        "raw": [
            {
                "format": "hwpx",
                "source_paths": [a.path],
                "page_texts": None,
                "page_bounds": None,
            },
            {
                "format": "pdf",
                "source_paths": [z.path],
                "page_texts": [],
                "page_bounds": [],
            },
        ],
    }
    assert source_hash(bundle, document, [pdf, hwpx]) == (
        "3bd27709ba6cdab5217173492b8bc92ba60d0347df4017ace9c514a6ab60d4d5"
    )
    assert canonical_source_payload(bundle, document, [])["raw"] == []


def test_records_group_normalized_quote_choose_representative_dedup_and_bundle_sort():
    z = _source("z.pdf")
    a = _source("a.pdf")
    bundle = _bundle(z, a)  # 파일명 사전순과 반대인 bundle 순서가 정본
    raw = _raw(
        "pdf",
        [z.path, a.path],
        page_texts=["가   나", "가 나"],
        page_bounds=[
            PageBound(file=z.path, first_page=1, last_page=1),
            PageBound(file=a.path, first_page=2, last_page=2),
        ],
    )
    document = _document("가 나", [z.path, a.path])
    quotes = [
        Evidence(quote="가 나"),
        Evidence(quote="가  나"),
        Evidence(quote=unicodedata.normalize("NFD", "가 나")),
    ]

    sidecar = build_evidence_locations(bundle, document, [raw], quotes)

    assert len(sidecar.records) == 1
    record = sidecar.records[0]
    assert record.evidence_id == evidence_id("가 나") == evidence_id("가  나")
    assert record.quote == "가  나"  # NFC 후 Python 문자열 사전순 최소
    assert record.location_status == "ambiguous"
    assert [location.file for location in record.locations] == [z.path, a.path]
    assert len(record.locations) == 2


def test_evidence_id_golden_and_nfc_whitespace_equivalence():
    assert evidence_id("가\t나") == evidence_id(unicodedata.normalize("NFD", "가  나"))
    assert (
        evidence_id("가 나") == "ff22d858c6a624ba72a8d2341933b8741ebc79167578bed79ae97560bcb631a0"
    )


def test_record_rejects_evidence_id_that_does_not_match_normalized_quote():
    with pytest.raises(ValidationError, match="evidence_id must equal"):
        EvidenceLocationRecord(
            evidence_id=evidence_id("다른 인용"),
            quote="현재 인용",
            locations=[],
            location_status="unavailable",
        )


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_sidecar_schema_version_requires_integer_one(value: object):
    with pytest.raises(ValidationError, match="schema_version must be integer 1"):
        EvidenceLocations(schema_version=value, source_hash="0" * 64, records=[])


def test_projection_matching_sidecar_unavailable_overrides_valid_inline():
    source = _source("notice.pdf")
    bundle = _bundle(source)
    raw = _raw(
        "pdf",
        [source.path],
        page_texts=["앞 정확 근거 뒤"],
        page_bounds=[PageBound(file=source.path, first_page=1, last_page=1)],
    )
    document = _document("정확 근거", [source.path])
    inline = locate_evidence(Evidence(quote="정확 근거", page=99), bundle, [raw])
    sidecar = EvidenceLocations(
        source_hash=source_hash(bundle, document, [raw]),
        records=[
            EvidenceLocationRecord(
                evidence_id=evidence_id(inline.quote),
                quote=inline.quote,
                locations=[],
                location_status="unavailable",
            )
        ],
    )

    projected = project_evidence(inline, bundle, document, [raw], sidecar)

    assert projected.locations == []
    assert projected.location_status == "unavailable"
    assert projected.page == 99  # legacy 필드는 보존하지만 fallback에는 쓰지 않는다.


def test_projection_hash_mismatch_falls_back_to_only_exact_current_inline_locations():
    source = _source("notice.pdf")
    bundle = _bundle(source)
    raw = _raw(
        "pdf",
        [source.path],
        page_texts=["정확 근거"],
        page_bounds=[PageBound(file=source.path, first_page=1, last_page=1)],
    )
    document = _document("정확 근거", [source.path])
    exact = locate_evidence(Evidence(quote="정확 근거"), bundle, [raw]).locations[0]
    wrong = exact.model_copy(update={"file_sha256": _sha("wrong")})
    inline = Evidence(
        quote="정확 근거",
        page=77,
        locations=[wrong, exact],
        location_status="ambiguous",
    )
    stale = EvidenceLocations(source_hash="0" * 64, records=[])

    projected = project_evidence(inline, bundle, document, [raw], stale)

    assert projected.locations == [exact]
    assert projected.location_status == "exact"
    assert projected.page == 77


def test_projection_does_not_fallback_to_legacy_page_without_verified_inline_span():
    source = _source("notice.pdf")
    raw = _raw(
        "pdf",
        [source.path],
        page_texts=["정확 근거"],
        page_bounds=[PageBound(file=source.path, first_page=1, last_page=1)],
    )
    bundle = _bundle(source)
    evidence = Evidence(quote="정확 근거", page=1)

    projected = project_evidence(evidence, bundle, _document("정확 근거", [source.path]), [raw])

    assert projected.locations == []
    assert projected.location_status == "unavailable"
