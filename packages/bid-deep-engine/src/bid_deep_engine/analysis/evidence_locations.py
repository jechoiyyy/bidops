"""현재 ingest 캐시에서 인용의 파일별 물리 페이지 위치를 정확히 찾는다.

위치 검색은 인용 문자열 검증과 독립이다. ``Evidence.verified``를 신뢰하거나 바꾸지 않고,
``raw.*.json``에 실제 페이지 텍스트와 파일 경계가 있을 때만 페이지 안의 정확 일치를 반환한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from bid_deep_engine.analysis.evidence import normalize, table_quote_spans
from bid_deep_engine.analysis.schemas import (
    Analysis,
    Evidence,
    LocationStatus,
    RequirementFit,
    SourceBlockLocation,
    SourceLocation,
    iter_evidence,
)
from bid_deep_engine.ingest.models import NoticeBundle, PageBound, RawDoc, RfpDocument, SourceFile

SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceLocationRecord(BaseModel):
    evidence_id: str
    quote: str
    locations: list[SourceLocation] = Field(default_factory=list)
    location_status: LocationStatus = "unavailable"

    @field_validator("evidence_id")
    @classmethod
    def _valid_evidence_id(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("evidence_id must be 64 lowercase hex characters")
        return value

    @model_validator(mode="after")
    def _status_matches_count(self) -> EvidenceLocationRecord:
        if self.evidence_id != evidence_id(self.quote):
            raise ValueError("evidence_id must equal SHA256(normalize(quote))")
        expected = location_status(len(self.locations))
        if self.location_status != expected:
            raise ValueError(
                f"location_status must be {expected} for {len(self.locations)} locations"
            )
        keys = [(x.file, x.page, x.start, x.end) for x in self.locations]
        if len(keys) != len(set(keys)):
            raise ValueError("locations must not contain duplicates")
        return self


class EvidenceLocations(BaseModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    source_hash: str
    records: list[EvidenceLocationRecord] = Field(default_factory=list)

    @field_validator("schema_version", mode="before")
    @classmethod
    def _strict_schema_version(cls, value: object) -> object:
        if type(value) is not int or value != SCHEMA_VERSION:
            raise ValueError("schema_version must be integer 1")
        return value

    @field_validator("source_hash")
    @classmethod
    def _valid_source_hash(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("source_hash must be 64 lowercase hex characters")
        return value

    @model_validator(mode="after")
    def _records_are_unique_and_sorted(self) -> EvidenceLocations:
        ids = [record.evidence_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("records must contain one record per evidence_id")
        if ids != sorted(ids):
            raise ValueError("records must be sorted by evidence_id")
        return self


def _raw_documents(raws: Iterable[RawDoc] | Mapping[str, RawDoc]) -> list[RawDoc]:
    values = list(raws.values()) if isinstance(raws, Mapping) else list(raws)
    formats = [raw.format for raw in values]
    if len(formats) != len(set(formats)):
        raise ValueError("raw documents must contain at most one document per format")
    return sorted(values, key=lambda raw: raw.format)


def canonical_source_payload(
    bundle: NoticeBundle,
    document: RfpDocument,
    raws: Iterable[RawDoc] | Mapping[str, RawDoc],
) -> dict[str, Any]:
    """Spec의 source_hash payload를 만든다. 배열 순서와 null/빈 배열을 그대로 보존한다."""
    raw_payload: list[dict[str, Any]] = []
    for raw in _raw_documents(raws):
        bounds = (
            None
            if raw.page_bounds is None
            else [
                {
                    "file": bound.file,
                    "first_page": bound.first_page,
                    "last_page": bound.last_page,
                }
                for bound in raw.page_bounds
            ]
        )
        raw_payload.append(
            {
                "format": raw.format,
                "source_paths": list(raw.source_paths),
                "page_texts": None if raw.page_texts is None else list(raw.page_texts),
                "page_bounds": bounds,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "source_files": [{"path": source.path, "sha256": source.sha256} for source in bundle.files],
        "full_text": document.full_text,
        "raw": raw_payload,
    }


def canonical_json(value: Any) -> bytes:
    """해시 계약의 canonical JSON UTF-8 bytes."""
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def source_hash(
    bundle: NoticeBundle,
    document: RfpDocument,
    raws: Iterable[RawDoc] | Mapping[str, RawDoc],
) -> str:
    return hashlib.sha256(
        canonical_json(canonical_source_payload(bundle, document, raws))
    ).hexdigest()


def evidence_id(quote: str) -> str:
    """기존 quote 정규화 문자열의 전체 SHA256."""
    normalized, _ = normalize(quote)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def location_status(count: int) -> LocationStatus:
    if count == 0:
        return "unavailable"
    if count == 1:
        return "exact"
    return "ambiguous"


def _valid_source_files(bundle: NoticeBundle) -> tuple[dict[str, SourceFile], dict[str, int]]:
    """정확히 한 번 나온 안전한 path와 유효 lowercase SHA만 연결 대상으로 돌려준다."""
    counts: dict[str, int] = {}
    for source in bundle.files:
        counts[source.path] = counts.get(source.path, 0) + 1
    files = {
        source.path: source
        for source in bundle.files
        if counts[source.path] == 1
        and _SHA256_RE.fullmatch(source.sha256)
        and _is_relative_source_path(source.path)
    }
    order = {source.path: i for i, source in enumerate(bundle.files) if counts[source.path] == 1}
    return files, order


def _is_relative_source_path(value: str) -> bool:
    return bool(
        value
        and "\\" not in value
        and not value.startswith("/")
        and not re.match(r"^[A-Za-z]:/", value)
        and all(part not in {"", ".", ".."} for part in value.split("/"))
        and not PurePosixPath(value).is_absolute()
    )


def _valid_bound(
    bound: PageBound,
    raw: RawDoc,
    files: Mapping[str, SourceFile],
    page_count: int,
) -> bool:
    return (
        _page_claim_interval(bound, page_count) == (bound.first_page, bound.last_page)
        and raw.source_paths.count(bound.file) == 1
        and bound.file in files
        and files[bound.file].format == raw.format
    )


def _page_claim_interval(bound: PageBound, page_count: int) -> tuple[int, int] | None:
    """Bound와 실제 page_texts 범위의 교집합. 거대한 잘못된 범위도 실제 쪽수만 claim한다."""
    if (
        not isinstance(bound.first_page, int)
        or isinstance(bound.first_page, bool)
        or not isinstance(bound.last_page, int)
        or isinstance(bound.last_page, bool)
        or bound.first_page > bound.last_page
    ):
        return None
    first = max(1, bound.first_page)
    last = min(page_count, bound.last_page)
    return None if first > last else (first, last)


def _physical_pages(
    bundle: NoticeBundle,
    raws: Iterable[RawDoc] | Mapping[str, RawDoc],
) -> tuple[list[tuple[str, str, int, str]], dict[str, int]]:
    """``(file, sha, local_page, page_text)``. 불명확한 global page mapping은 버린다."""
    files, order = _valid_source_files(bundle)
    pages: list[tuple[str, str, int, str]] = []
    for raw in _raw_documents(raws):
        # 현재 ingest 계약에서 물리 페이지 텍스트를 만드는 추출기는 PDF뿐이다. HWP/HWPX의
        # 논리 section/page 분할을 같은 모양으로 주입해도 물리 페이지로 승격하지 않는다.
        if raw.format != "pdf":
            continue
        if raw.page_texts is None or raw.page_bounds is None:
            continue
        page_count = len(raw.page_texts)
        by_file: dict[str, list[PageBound]] = {}
        for bound in raw.page_bounds:
            by_file.setdefault(bound.file, []).append(bound)

        # path/SHA/source 연결을 먼저 버리면 그 잘못된 claim과 같은 global page를 주장하는 정상
        # 파일이 exact로 남는다. 범위만 해석 가능한 모든 claim으로 소유 충돌을 먼저 판정한다.
        owners: list[list[PageBound]] = [[] for _ in range(page_count)]
        for bound in raw.page_bounds:
            interval = _page_claim_interval(bound, page_count)
            if interval is None:
                continue
            for global_page in range(interval[0], interval[1] + 1):
                owners[global_page - 1].append(bound)
        overlapping = {
            bound.file for page_claims in owners if len(page_claims) > 1 for bound in page_claims
        }

        # 한 파일은 하나의 연속 global 구간으로만 파일-local page를 계산할 수 있다. 같은 파일이
        # 여러 bound에 나오면 ([1,1],[2,2] 포함) 어느 bound의 local p1인지 결정하지 않는다.
        unambiguous: dict[str, PageBound] = {}
        for file, bounds in by_file.items():
            if (
                len(bounds) != 1
                or file in overlapping
                or not _valid_bound(bounds[0], raw, files, page_count)
            ):
                continue
            unambiguous[file] = bounds[0]

        mapping: list[PageBound | None] = [None] * page_count
        for bound in unambiguous.values():
            for global_page in range(bound.first_page, bound.last_page + 1):
                mapping[global_page - 1] = bound

        for global_page, (text, bound) in enumerate(
            zip(raw.page_texts, mapping, strict=True), start=1
        ):
            if bound is None:  # gap, overlap, duplicate/non-contiguous file bound
                continue
            source = files[bound.file]
            local_page = global_page - bound.first_page + 1
            pages.append((source.path, source.sha256, local_page, text))
    return pages, order


def _page_matches(quote: str, page_text: str) -> list[tuple[int, int]]:
    norm_quote, _ = normalize(quote)
    if not norm_quote:
        return []
    _nfc_page = unicodedata.normalize("NFC", page_text)
    norm_page, offsets = normalize(_nfc_page)
    matches: list[tuple[int, int]] = []
    start = 0
    while True:
        found = norm_page.find(norm_quote, start)
        if found < 0:
            break
        end = found + len(norm_quote)
        matches.append((offsets[found], offsets[end - 1] + 1))
        start = found + 1  # 겹치는 반복도 모두 보존
    return matches


def _dedup_sort_locations(
    locations: Iterable[SourceLocation], bundle_order: Mapping[str, int]
) -> list[SourceLocation]:
    unique: dict[tuple[str, int, int, int], SourceLocation] = {}
    for item in locations:
        unique.setdefault((item.file, item.page, item.start, item.end), item)
    return sorted(
        unique.values(),
        key=lambda item: (bundle_order[item.file], item.page, item.start, item.end),
    )


def resolve_locations(
    quote: str,
    bundle: NoticeBundle,
    raws: Iterable[RawDoc] | Mapping[str, RawDoc],
) -> tuple[list[SourceLocation], LocationStatus]:
    """각 실제 페이지 안에서 quote의 모든 정확 일치를 찾는다.

    섹션 번호, legacy ``Evidence.page``, ``verified``는 입력으로 받지 않으므로 위치 판정에
    영향을 줄 수 없다. 페이지 경계를 넘는 문자열은 어느 페이지에서도 일치하지 않는다.
    """
    pages, order = _physical_pages(bundle, raws)
    locations: list[SourceLocation] = []
    for file, sha256, local_page, text in pages:
        for start, end in _page_matches(quote, text):
            locations.append(
                SourceLocation(
                    file=file,
                    file_sha256=sha256,
                    page=local_page,
                    start=start,
                    end=end,
                )
            )
    result = _dedup_sort_locations(locations, order)
    return result, location_status(len(result))


def locate_evidence(
    evidence: Evidence,
    bundle: NoticeBundle,
    raws: Iterable[RawDoc] | Mapping[str, RawDoc],
) -> Evidence:
    """quote/legacy/검증 필드는 보존하고 위치 필드만 채운 새 Evidence를 반환한다."""
    locations, status = resolve_locations(evidence.quote, bundle, raws)
    return evidence.model_copy(update={"locations": locations, "location_status": status})


def build_evidence_locations(
    bundle: NoticeBundle,
    document: RfpDocument,
    raws: Iterable[RawDoc] | Mapping[str, RawDoc],
    evidences: Iterable[Evidence],
) -> EvidenceLocations:
    """sidecar 저장 계층이 그대로 직렬화할 결정적 메모리 모델을 만든다."""
    raw_list = _raw_documents(raws)
    grouped: dict[str, list[str]] = {}
    for evidence in evidences:
        grouped.setdefault(evidence_id(evidence.quote), []).append(evidence.quote)

    records: list[EvidenceLocationRecord] = []
    _, order = _valid_source_files(bundle)
    for identifier in sorted(grouped):
        quotes = grouped[identifier]
        representative = min(unicodedata.normalize("NFC", quote) for quote in quotes)
        all_locations: list[SourceLocation] = []
        for quote in quotes:
            found, _ = resolve_locations(quote, bundle, raw_list)
            all_locations.extend(found)
        locations = _dedup_sort_locations(all_locations, order)
        records.append(
            EvidenceLocationRecord(
                evidence_id=identifier,
                quote=representative,
                locations=locations,
                location_status=location_status(len(locations)),
            )
        )
    return EvidenceLocations(
        source_hash=source_hash(bundle, document, raw_list),
        records=records,
    )


def write_evidence_locations(path: Path, value: EvidenceLocations) -> None:
    """같은 폴더의 임시 파일을 fsync한 뒤 atomic replace한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value.model_dump(mode="json"), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def locate_model_evidence[ModelT: BaseModel](
    model: ModelT,
    bundle: NoticeBundle | None,
    raws: Iterable[RawDoc] | Mapping[str, RawDoc],
    *,
    document: RfpDocument | None = None,
) -> ModelT:
    """현재 raw 캐시에서 검증된 인용에 물리 쪽과 원문 블록 위치를 붙인다."""
    result = model.model_copy(deep=True)
    raw_list = _raw_documents(raws)
    requirements = {} if document is None else {req.key: req for req in document.requirements}
    primary = (
        None
        if document is None
        else next((raw for raw in raw_list if raw.format == document.primary_format), None)
    )
    sections = {} if document is None else {sec.id: sec for sec in document.sections}
    table_blocks = {} if primary is None else {t.id: t.block_idx for t in primary.tables}
    table_rows = {} if primary is None else {t.block_idx: t.rows for t in primary.tables}
    fits: list[RequirementFit] = []
    if isinstance(result, Analysis):
        fits = result.fits
    elif isinstance(result, RequirementFit):
        fits = [result]
    markup_quotes = {
        id(f.evidence) for f in fits if f.evidence and f.evidence.quote.lstrip().startswith("|")
    }
    fit_blocks: dict[int, int] = {}
    for fit in fits:
        requirement = requirements.get(fit.key)
        if document is not None:
            fit.name = requirement.source_name if requirement else None
            fit.definition = requirement.definition if requirement else None
        if fit.evidence is not None and requirement and requirement.table_id in table_blocks:
            fit_blocks[id(fit.evidence)] = table_blocks[requirement.table_id]

    block_source = None
    if bundle is not None and primary is not None and len(primary.source_paths) == 1:
        files, _ = _valid_source_files(bundle)
        candidate = files.get(primary.source_paths[0])
        if candidate is not None and candidate.format == primary.format:
            block_source = candidate
    pages_available = bool(bundle is not None and _physical_pages(bundle, raw_list)[0])

    for evidence in iter_evidence(result, include_conflicts=True):
        evidence.locations = []
        evidence.location_status = "unavailable"
        evidence.block_locations = []
        evidence.block_location_status = "unavailable"
        if document is None:
            if bundle is not None:
                located = locate_evidence(evidence, bundle, raw_list)
                evidence.locations = located.locations
                evidence.location_status = located.location_status
            continue

        evidence.page = None
        if id(evidence) in markup_quotes and (
            block_source is None or id(evidence) not in fit_blocks
        ):
            evidence.verified = False
        if evidence.repaired is True:
            evidence.verified = False
        if evidence.verified is not True:
            continue

        if block_source is not None and primary is not None:
            section = sections.get(evidence.section_id)
            fit_block = fit_blocks.get(id(evidence))
            for block in primary.blocks:
                if fit_block is not None and block.idx != fit_block:
                    continue
                if section and not section.block_start <= block.idx <= section.block_end:
                    continue
                evidence.block_locations.extend(
                    SourceBlockLocation(
                        file=block_source.path,
                        file_sha256=block_source.sha256,
                        block_idx=block.idx,
                        start=start,
                        end=end,
                    )
                    for start, end in (
                        table_quote_spans(evidence.quote, table_rows[fit_block], block.text)
                        if fit_block is not None and evidence.quote.lstrip().startswith("|")
                        else _page_matches(evidence.quote, block.text)
                    )
                )
            evidence.block_location_status = location_status(len(evidence.block_locations))
            if primary.format != "pdf" and not evidence.block_locations:
                evidence.verified = False
                continue

        if pages_available and bundle is not None:
            evidence.locations, evidence.location_status = resolve_locations(
                evidence.quote, bundle, raw_list
            )
            if evidence.location_status == "exact":
                evidence.page = evidence.locations[0].page
            if primary is not None and primary.format == "pdf" and not evidence.locations:
                evidence.verified = False
    return result


def load_location_sources(
    slug_dir: Path,
    *,
    document: RfpDocument | None = None,
    require_bundle: bool = True,
) -> tuple[NoticeBundle | None, RfpDocument, list[RawDoc]]:
    """slug 폴더의 bundle/rfp/raw 캐시만 읽는다.

    CLI는 bundle을 필수로 읽고, 생성 pipeline은 legacy fixture를 위해 bundle 누락을 허용한다.
    존재하는 raw 하나라도 손상됐거나 slug가 섞였으면 일부 캐시만 사용하지 않는다.
    """
    if document is None:
        document = RfpDocument.model_validate_json(
            (slug_dir / "rfp.json").read_text(encoding="utf-8")
        )
    bundle_path = slug_dir / "bundle.json"
    if bundle_path.is_file():
        bundle: NoticeBundle | None = NoticeBundle.model_validate_json(
            bundle_path.read_text(encoding="utf-8")
        )
    elif require_bundle:
        raise FileNotFoundError(bundle_path)
    else:
        bundle = None

    raws = [
        RawDoc.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(slug_dir.glob("raw.*.json"), key=lambda path: path.name)
    ]
    if bundle is not None and bundle.slug != document.slug:
        raise ValueError("bundle/rfp slug mismatch")
    if any(raw.slug != document.slug for raw in raws):
        raise ValueError("raw/rfp slug mismatch")
    return bundle, document, _raw_documents(raws)


def project_evidence(
    evidence: Evidence,
    bundle: NoticeBundle,
    document: RfpDocument,
    raws: Iterable[RawDoc] | Mapping[str, RawDoc],
    sidecar: EvidenceLocations | None = None,
) -> Evidence:
    """현재 캐시 기준 sidecar/inline 우선순위를 적용한 읽기 전용 projection."""
    raw_list = _raw_documents(raws)
    if sidecar is not None and sidecar.source_hash == source_hash(bundle, document, raw_list):
        identifier = evidence_id(evidence.quote)
        record = next((item for item in sidecar.records if item.evidence_id == identifier), None)
        if record is not None:  # unavailable record도 inline보다 우선한다.
            return evidence.model_copy(
                update={
                    "locations": list(record.locations),
                    "location_status": record.location_status,
                }
            )

    current, _ = resolve_locations(evidence.quote, bundle, raw_list)
    provided = {
        (item.file, item.file_sha256, item.page, item.start, item.end)
        for item in evidence.locations
    }
    valid = [
        item
        for item in current
        if (item.file, item.file_sha256, item.page, item.start, item.end) in provided
    ]
    return evidence.model_copy(
        update={"locations": valid, "location_status": location_status(len(valid))}
    )


def project_model_evidence[ModelT: BaseModel](
    model: ModelT,
    bundle: NoticeBundle,
    document: RfpDocument,
    raws: Iterable[RawDoc] | Mapping[str, RawDoc],
    sidecar: EvidenceLocations | None = None,
) -> ModelT:
    """모델을 쓰지 않고 모든 Evidence에 읽기 projection을 적용한 deep copy를 반환한다."""
    result = model.model_copy(deep=True)
    raw_list = _raw_documents(raws)
    for evidence in iter_evidence(result, include_conflicts=True):
        projected = project_evidence(evidence, bundle, document, raw_list, sidecar)
        evidence.locations = list(projected.locations)
        evidence.location_status = projected.location_status
    return result


def project_analysis_evidence_locations(slug_dir: Path) -> Analysis:
    """REV 읽기 모델용 공개 진입점. source/analysis/sidecar를 읽기만 한다."""
    bundle, document, raws = load_location_sources(slug_dir)
    assert bundle is not None
    analysis = Analysis.model_validate_json(
        (slug_dir / "analysis.json").read_text(encoding="utf-8")
    )
    sidecar: EvidenceLocations | None = None
    sidecar_path = slug_dir / "evidence_locations.json"
    if sidecar_path.is_file():
        try:
            sidecar = EvidenceLocations.model_validate_json(
                sidecar_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            sidecar = None
    return project_model_evidence(analysis, bundle, document, raws, sidecar)
