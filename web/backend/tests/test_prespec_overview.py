"""T-23 deterministic pre-spec overview lineage tests.

These tests exercise the SQLite-compatible ORM/service surface only.  The
PostgreSQL CHECK and runtime privilege contracts remain covered by the
PostgreSQL migration suite when ``BIDOPS_TEST_POSTGRES_URL`` is configured.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.models import (
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentBlock,
    DocumentStructure,
    DocumentVersion,
    Notice,
    PreSpecOverviewAttempt,
    PreSpecOverviewReview,
    PreSpecOverviewSnapshot,
)
from app.routers.deep_reviews import get_pre_spec_overview_reviews
from app.services import assets, prespec_overview
from app.services.prespec_overview import (
    deterministic_prefix_cut,
    get_overview_reviews,
    prepare_overview_review,
)


def _block(
    key: str,
    block_type: str,
    text: str,
    *,
    level: int = 1,
    toc: bool = False,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {"heading_level": level} if block_type == "heading" else {}
    if toc:
        attributes["is_toc"] = True
    return {
        "block_key": key,
        "parent_block_key": None,
        "type": block_type,
        "page": 1,
        "bbox": [0.0, 0.0, 100.0, 20.0],
        "text": text,
        "confidence": 1.0,
        "attributes": attributes,
    }


def _processor_paragraph(
    key: str,
    text: str,
    *,
    page: int = 1,
    source: str | None = None,
) -> dict[str, Any]:
    """Shape emitted by the canonical processor (no synthetic heading flag)."""

    attributes: dict[str, Any] = {"paragraph_key": f"p-{key}"}
    if source is not None:
        attributes["source"] = source
    return {
        "block_key": key,
        "parent_block_key": None,
        "type": "paragraph",
        "page": page,
        "bbox": None,
        "text": text,
        "confidence": None,
        "attributes": attributes,
    }


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    return engine


def _structure_payload(
    document_id: str,
    structure_id: str,
    source_sha256: str,
    blocks: list[dict[str, Any]],
    *,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "bidops.document-structure.v1",
        "structure_id": structure_id,
        "document_version_id": document_id,
        "source_sha256": source_sha256,
        "media_type": "application/pdf",
        "extractor": {"name": "test", "version": "1", "upstream_commit": None},
        "pages": [
            {
                "number": 1,
                "width": 100.0,
                "height": 100.0,
                "image_content_object_id": None,
            }
        ],
        "blocks": blocks,
        "warnings": warnings or [],
        "created_at": "2026-08-31T00:00:00Z",
    }


def _seed_document(
    session: Session,
    root: Path,
    notice: Notice,
    blocks: list[dict[str, Any]],
    *,
    source_suffix: str = "one",
    created_at: datetime | None = None,
    warnings: list[str] | None = None,
) -> tuple[DocumentVersion, DocumentStructure, bytes, bytes]:
    source_bytes = f"source-{source_suffix}".encode("utf-8")
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    _source_path, source_metadata = assets.store_named(
        "source", f"source/t23-{source_suffix}.pdf", source_bytes, root=root
    )
    source = ContentObject(
        sha256=source_sha256,
        size_bytes=len(source_bytes),
        detected_mime="application/pdf",
        retention_class="document-source",
    )
    session.add(source)
    session.flush()
    session.add(
        ContentObjectLocation(
            content_object_id=source.id,
            namespace_key="source",
            object_key=source_metadata.object_key,
            object_version_id=source_metadata.object_version_id,
            etag=source_metadata.etag,
            status="verified",
        )
    )
    session.add(
        ContentScan(
            content_object_id=source.id,
            scanner="test",
            scanner_version="1",
            status="clean",
            safe_result={},
        )
    )
    document = DocumentVersion(
        notice_id=notice.id,
        content_object_id=source.id,
        version=1,
        source_kind="provider",
        source_system="g2b",
        source_attachment_key=f"T23:{source_suffix}",
        original_filename=f"{source_suffix}.pdf",
        role="제안요청서",
        is_current=True,
        safety_status="safe",
        needs_human_review=False,
        created_at=created_at or datetime.now(UTC),
    )
    session.add(document)
    session.flush()
    structure_id = uuid4()
    payload = _structure_payload(
        str(document.id), str(structure_id), source_sha256, blocks, warnings=warnings
    )
    structure_bytes = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    structure_sha256 = hashlib.sha256(structure_bytes).hexdigest()
    _structure_path, structure_metadata = assets.store_named(
        "structure",
        f"structure/t23-{source_suffix}.json",
        structure_bytes,
        root=root,
        content_type="application/json",
    )
    structure_content = ContentObject(
        sha256=structure_sha256,
        size_bytes=len(structure_bytes),
        detected_mime="application/json",
        retention_class="document-structure",
    )
    session.add(structure_content)
    session.flush()
    session.add(
        ContentObjectLocation(
            content_object_id=structure_content.id,
            namespace_key="structure",
            object_key=structure_metadata.object_key,
            object_version_id=structure_metadata.object_version_id,
            etag=structure_metadata.etag,
            status="verified",
        )
    )
    structure = DocumentStructure(
        id=structure_id,
        document_version_id=document.id,
        source_sha256=source_sha256,
        media_type="application/pdf",
        extractor_name="test",
        extractor_version="1",
        payload_content_object_id=structure_content.id,
        payload_sha256=structure_sha256,
        page_count=1,
        block_count=len(blocks),
        validation_status="ready",
    )
    session.add(structure)
    session.flush()
    for block in blocks:
        session.add(
            DocumentBlock(
                structure_id=structure.id,
                block_key=block["block_key"],
                parent_block_key=None,
                block_type=block["type"],
                page=1,
                bbox=block["bbox"],
                content=block["text"],
                confidence=block["confidence"],
                attributes=block["attributes"],
            )
        )
    session.flush()
    return document, structure, source_bytes, structure_bytes


def _notice(session: Session, key: str = "t23") -> Notice:
    notice = Notice(
        notice_key=f"pre:{key}:{uuid4()}",
        source_type="pre_spec",
        title="T-23 테스트",
    )
    session.add(notice)
    session.flush()
    return notice


def test_toc_body_match_and_topic_heading_use_exclusive_end_locator() -> None:
    toc = [
        _block("toc-1", "heading", "1. 사업개요 ..... 3", toc=True),
        _block("body-1", "heading", "1. 사업개요"),
        _block("body-p", "paragraph", "사업 목적"),
        _block("body-2", "heading", "2. 과업내용"),
    ]
    toc_result = deterministic_prefix_cut({"warnings": [], "blocks": toc})
    assert toc_result.cut_status == "ready"
    assert toc_result.strategy == "toc_body_match"
    assert toc_result.start_locator == {"block_key": "body-1", "page": 1, "ordinal": 1}
    assert toc_result.end_locator == {"block_key": "body-2", "page": 1, "ordinal": 3}
    assert toc_result.input_block_keys == ["body-1", "body-p"]

    topic_result = deterministic_prefix_cut(
        {
            "warnings": [],
            "blocks": [
                _block("topic-1", "heading", "사업개요"),
                _block("topic-p", "paragraph", "내용"),
                _block("topic-2", "heading", "과업내용"),
            ],
        }
    )
    assert topic_result.cut_status == "ready"
    assert topic_result.strategy == "topic_heading"


def test_processor_shaped_paragraphs_use_exact_topic_boundaries() -> None:
    result = deterministic_prefix_cut(
        {
            "warnings": [],
            "blocks": [
                _processor_paragraph("p1", "1. 사업개요"),
                _processor_paragraph("p2", "사업의 목적과 범위"),
                _processor_paragraph("p3", "2. 과업내용"),
            ],
        }
    )

    assert result.cut_status == "ready"
    assert result.strategy == "topic_heading"
    assert result.start_locator == {"block_key": "p1", "page": 1, "ordinal": 0}
    assert result.end_locator == {"block_key": "p3", "page": 1, "ordinal": 2}
    assert result.input_block_keys == ["p1", "p2"]


def test_processor_shaped_paragraph_toc_requires_explicit_body_duplicate() -> None:
    result = deterministic_prefix_cut(
        {
            "warnings": [],
            "blocks": [
                _processor_paragraph("toc-title", "목차"),
                _processor_paragraph("toc-start", "1. 사업개요 ..... 3"),
                _processor_paragraph("toc-end", "2. 과업내용 ..... 5"),
                _processor_paragraph("body-start", "1. 사업개요"),
                _processor_paragraph("body", "사업의 목적과 범위"),
                _processor_paragraph("body-end", "2. 과업내용"),
            ],
        }
    )

    assert result.cut_status == "ready"
    assert result.strategy == "toc_body_match"
    assert result.start_locator == {"block_key": "body-start", "page": 1, "ordinal": 3}
    assert result.end_locator == {"block_key": "body-end", "page": 1, "ordinal": 5}
    assert result.input_block_keys == ["body-start", "body"]


def test_processor_topic_vocabulary_is_exactly_the_t21_observed_set() -> None:
    assert prespec_overview._TOPIC_HEADING_VOCABULARY == {
        "추진배경",
        "사업개요",
        "용역개요",
        "추진목표",
        "제안절차",
        "일반사항",
        "사업예산",
        "과업내용",
        "사업기간",
    }


@pytest.mark.parametrize(
    ("prefix", "topic"),
    [
        ("1. ", "사업개요"),
        ("가. ", "용역개요"),
        ("Ⅰ. ", "추진배경"),
        ("(1) ", "추진목표"),
        ("○ ", "제안절차"),
        ("【", "일반사항】"),
        ("[2] ", "사업예산"),
        ("- ", "과업내용"),
        ("· ", "사업기간"),
    ],
)
def test_processor_topic_headings_accept_only_observed_prefix_normalization(
    prefix: str, topic: str
) -> None:
    result = deterministic_prefix_cut(
        {
            "warnings": [],
            "blocks": [
                _processor_paragraph("start", f"{prefix}{topic}"),
                _processor_paragraph("body", "사업의 목적과 범위"),
                _processor_paragraph("end", "사업개요"),
            ],
        }
    )

    assert result.cut_status == "ready"
    assert result.strategy == "topic_heading"
    assert result.start_locator == {"block_key": "start", "page": 1, "ordinal": 0}
    assert result.end_locator == {"block_key": "end", "page": 1, "ordinal": 2}


@pytest.mark.parametrize(
    "text",
    ["1.", "사업개요에 대한 내용", "공고의 사업개요", "사업개요서"],
)
def test_processor_paragraphs_reject_number_only_and_non_exact_prose(text: str) -> None:
    result = deterministic_prefix_cut(
        {"warnings": [], "blocks": [_processor_paragraph("body", text)]}
    )

    assert result.cut_status == "unknown"
    assert result.unknown_reason_code == "no_topic_heading"
    assert result.input_block_keys is None


@pytest.mark.parametrize(
    ("blocks", "warnings", "reason"),
    [
        ([_block("one", "heading", "사업개요")], [], "no_end_heading"),
        ([_block("one", "heading", "1."), _block("two", "heading", "2.")], [], "no_topic_heading"),
        ([_block("one", "paragraph", "사업개요"), _block("two", "paragraph", "과업내용")], [], "no_topic_heading"),
        ([_block("one", "heading", "사업개요"), _block("two", "heading", "과업내용")], ["needs_review"], "structure_warning"),
    ],
)
def test_cut_unknown_never_falls_back_to_fixed_count_or_full_document(
    blocks: list[dict[str, Any]], warnings: list[str], reason: str
) -> None:
    result = deterministic_prefix_cut({"warnings": warnings, "blocks": blocks})
    assert result.cut_status == "unknown"
    assert result.unknown_reason_code == reason
    assert result.input_block_keys is None


def test_input_limit_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prespec_overview, "MAX_OVERVIEW_INPUT_BLOCKS", 1)
    result = deterministic_prefix_cut(
        {
            "warnings": [],
            "blocks": [_block("one", "heading", "사업개요"), _block("two", "heading", "과업내용")],
        }
    )
    assert result.cut_status == "unknown"
    assert result.unknown_reason_code == "input_limit"


def test_prepare_is_idempotent_and_keeps_new_structure_lineage(tmp_path: Path) -> None:
    engine = _engine()
    with Session(engine) as session:
        notice = _notice(session)
        first_document, first_structure, _source, _payload = _seed_document(
            session,
            tmp_path,
            notice,
            [
                _block("start-1", "heading", "사업개요"),
                _block("body-1", "paragraph", "내용"),
                _block("end-1", "heading", "과업내용"),
            ],
            source_suffix="first",
            created_at=datetime(2026, 8, 31, 0, 0, tzinfo=UTC),
        )
        review = prepare_overview_review(session, notice.id, root=tmp_path)
        session.commit()
        snapshot_id = review.current_snapshot_id
        assert review.status == "awaiting_model"
        assert session.query(PreSpecOverviewSnapshot).count() == 1

        repeated = prepare_overview_review(session, notice.id, root=tmp_path)
        session.commit()
        assert repeated.current_snapshot_id == snapshot_id
        assert session.query(PreSpecOverviewSnapshot).count() == 1

        completed_at = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
        repeated.status = "completed"
        repeated.result = "추진 검토"
        repeated.completed_at = completed_at
        session.commit()
        preserved = prepare_overview_review(session, notice.id, root=tmp_path)
        session.commit()
        assert preserved.status == "completed"
        assert preserved.result == "추진 검토"
        assert preserved.completed_at == completed_at

        first_document.is_current = False
        second_document, second_structure, _source2, _payload2 = _seed_document(
            session,
            tmp_path,
            notice,
            [
                _block("start-2", "heading", "사업개요"),
                _block("body-2", "paragraph", "새 내용"),
                _block("end-2", "heading", "과업내용"),
            ],
            source_suffix="second",
            created_at=datetime(2026, 8, 31, 0, 1, tzinfo=UTC),
        )
        second_document.version = 1
        second_review = prepare_overview_review(session, notice.id, root=tmp_path)
        session.commit()
        assert second_review.current_snapshot_id != snapshot_id
        snapshots = session.scalars(
            select(PreSpecOverviewSnapshot).where(
                PreSpecOverviewSnapshot.review_id == second_review.id
            )
        ).all()
        assert len(snapshots) == 2
        assert {item.structure_id for item in snapshots} == {
            first_structure.id,
            second_structure.id,
        }


def test_human_rfp_role_remains_selected_when_newer_appendix_arrives(
    tmp_path: Path,
) -> None:
    engine = _engine()
    with Session(engine) as session:
        notice = _notice(session, "appendix")
        rfp, _structure, _source, _payload = _seed_document(
            session,
            tmp_path,
            notice,
            [
                _block("start", "heading", "사업개요"),
                _block("body", "paragraph", "내용"),
                _block("end", "heading", "과업내용"),
            ],
            source_suffix="appendix-rfp",
            created_at=datetime(2026, 8, 31, 0, 0, tzinfo=UTC),
        )
        review = prepare_overview_review(session, notice.id, root=tmp_path)
        session.commit()
        snapshot_id = review.current_snapshot_id
        assert snapshot_id is not None

        appendix_bytes = b"appendix"
        appendix_content = ContentObject(
            sha256=hashlib.sha256(appendix_bytes).hexdigest(),
            size_bytes=len(appendix_bytes),
            detected_mime="application/pdf",
            retention_class="document-source",
        )
        session.add(appendix_content)
        session.flush()
        session.add(
            DocumentVersion(
                notice_id=notice.id,
                content_object_id=appendix_content.id,
                version=1,
                source_kind="provider",
                source_system="g2b",
                source_attachment_key="appendix",
                original_filename="부록_서식.pdf",
                role="기타",
                is_current=True,
                safety_status="safe",
                needs_human_review=False,
                created_at=datetime(2026, 8, 31, 0, 1, tzinfo=UTC),
            )
        )
        session.commit()

        preserved = prepare_overview_review(session, notice.id, root=tmp_path)
        session.commit()
        assert preserved.status == "awaiting_model"
        assert preserved.current_snapshot_id == snapshot_id
        assert preserved.current_snapshot.document_version_id == rfp.id


def test_unclassified_current_documents_clear_previous_snapshot(tmp_path: Path) -> None:
    engine = _engine()
    with Session(engine) as session:
        notice = _notice(session, "unclassified")
        document, _structure, _source, _payload = _seed_document(
            session,
            tmp_path,
            notice,
            [
                _block("start", "heading", "사업개요"),
                _block("body", "paragraph", "내용"),
                _block("end", "heading", "과업내용"),
            ],
            source_suffix="unclassified-rfp",
        )
        review = prepare_overview_review(session, notice.id, root=tmp_path)
        session.commit()
        snapshot_id = review.current_snapshot_id
        assert review.status == "awaiting_model"
        assert snapshot_id is not None

        document.is_current = False
        appendix_source = ContentObject(
            sha256="c" * 64,
            size_bytes=1,
            detected_mime="application/pdf",
            retention_class="document-source",
        )
        session.add(appendix_source)
        session.flush()
        session.add(
            DocumentVersion(
                notice_id=notice.id,
                content_object_id=appendix_source.id,
                version=1,
                source_kind="manual",
                original_filename="부록_서식.pdf",
                role="기타",
                is_current=True,
                safety_status="safe",
                needs_human_review=False,
            )
        )
        session.commit()

        blocked = prepare_overview_review(session, notice.id, root=tmp_path)
        session.commit()
        assert blocked.status == "needs_human_review"
        assert blocked.current_snapshot_id is None
        assert session.query(PreSpecOverviewSnapshot).count() == 1


def test_hash_mismatch_warning_and_no_attempt(tmp_path: Path) -> None:
    engine = _engine()
    with Session(engine) as session:
        notice = _notice(session, "hash")
        document, structure, _source, _payload = _seed_document(
            session,
            tmp_path,
            notice,
            [
                _block("start", "heading", "사업개요"),
                _block("body", "paragraph", "내용"),
                _block("end", "heading", "과업내용"),
            ],
            source_suffix="hash",
        )
        structure.payload_sha256 = "f" * 64
        review = prepare_overview_review(session, notice.id, root=tmp_path)
        session.commit()
        snapshot = session.get(PreSpecOverviewSnapshot, review.current_snapshot_id)
        assert snapshot is not None
        assert snapshot.cut_status == "unknown"
        assert snapshot.unknown_reason_code == "hash_mismatch"
        assert review.status == "needs_human_review"
        assert session.query(PreSpecOverviewAttempt).count() == 0
        assert session.get(DocumentVersion, document.id) is not None


def test_api_404_and_safe_projection_do_not_expose_storage_or_model_payload(tmp_path: Path) -> None:
    engine = _engine()
    with Session(engine) as session:
        missing = get_pre_spec_overview_reviews(999999, session)
        assert isinstance(missing, JSONResponse)
        assert missing.status_code == 404
        notice = _notice(session, "api")
        _document, _structure, _source, _payload = _seed_document(
            session,
            tmp_path,
            notice,
            [
                _block("start", "heading", "사업개요"),
                _block("body", "paragraph", "내용"),
                _block("end", "heading", "과업내용"),
            ],
            source_suffix="api",
        )
        get_overview_reviews(session, notice.id, root=tmp_path)
        first_snapshot = session.scalar(select(PreSpecOverviewSnapshot))
        assert first_snapshot is not None
        session.add(
            PreSpecOverviewAttempt(
                snapshot_id=first_snapshot.id,
                sequence=1,
                status="queued",
                provider="secret-provider",
                model_name="secret-model",
                prompt_version="secret-prompt",
            )
        )
        session.commit()
        response = get_overview_reviews(session, notice.id, root=tmp_path)
        encoded = json.dumps(response.model_dump(mode="json"), ensure_ascii=False)
        assert response.schema_version == "bidops.prespec-overview-reviews.v1"
        assert "source/t23-api.pdf" not in encoded
        assert "structure/t23-api.json" not in encoded
        assert "prompt" not in encoded
        assert "response" not in encoded
        assert "사업개요" not in encoded
        assert "body" not in encoded
        assert response.reviews[0].current_snapshot is not None
        assert response.reviews[0].current_snapshot.start_locator is not None
        assert response.reviews[0].attempts[0].snapshot_id == first_snapshot.id


def test_missing_document_and_structure_keep_waiting_states() -> None:
    engine = _engine()
    with Session(engine) as session:
        notice = _notice(session, "waiting")
        review = prepare_overview_review(session, notice.id)
        assert review.status == "awaiting_document"
        session.commit()
        source = ContentObject(
            sha256="a" * 64,
            size_bytes=1,
            detected_mime="application/pdf",
            retention_class="document-source",
        )
        session.add(source)
        session.flush()
        document = DocumentVersion(
            notice_id=notice.id,
            content_object_id=source.id,
            version=1,
            source_kind="provider",
            source_system="g2b",
            source_attachment_key="waiting",
            original_filename="waiting.pdf",
            role="제안요청서",
            is_current=True,
            safety_status="safe",
            needs_human_review=False,
        )
        session.add(document)
        session.commit()
        review = prepare_overview_review(session, notice.id)
        assert review.status == "awaiting_structure"
