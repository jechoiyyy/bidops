"""PostgreSQL 17 coverage for HP-01 STEP-002/003/005 storage, reads, and backfill."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.db import ALEMBIC_HEAD, _json_serializer, schema_bound
from app.core.object_store import FilesystemObjectStore
from app.deep_review.cli import rebuild_segment_manifests
from app.deep_review.models import (
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentBundle,
    DocumentSegment,
    DocumentSegmentManifest,
    DocumentStructure,
    DocumentVersion,
    RequirementInventoryItem,
)
from app.deep_review.services import document_segments
from app.lifecycle.models import Attachment, Notice, Run
from tests.deep_review.test_document_segments import (
    SOURCE_SHA,
    _blocks,
    _native_snapshot,
    _requirement_card_table,
    _structure,
)
from tests.postgres import migrated_engine, requires_postgres, run_alembic, temporary_database


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parents[1]
RUNTIME_PRIVILEGES = (PROJECT_ROOT / "scripts" / "runtime-privileges.sql").read_text(
    encoding="utf-8"
)


def _seed_structure(session: Session) -> tuple[DocumentStructure, DocumentVersion]:
    run = Run(id=f"hp01-segment-{uuid4()}")
    notice = Notice(
        run=run,
        notice_key=f"hp01-segment-notice-{uuid4()}",
        title="합성 HP-01",
        sample_role="analysis",
    )
    session.add(run)
    session.flush()
    attachment = Attachment(notice=notice, name="합성.hwpx", source_url=None)
    content = ContentObject(
        sha256=SOURCE_SHA,
        size_bytes=10,
        detected_mime="application/hwp+zip",
        retention_class="source",
    )
    session.add_all([attachment, content])
    session.flush()
    session.add(
        DocumentBundle(
            notice_id=notice.id,
            revision=1,
            version=1,
            status="draft",
            issues_snapshot=[],
        )
    )
    document = DocumentVersion(
        notice_id=notice.id,
        attachment_id=attachment.id,
        version=1,
        source_kind="manual",
        role="제안요청서",
        is_current=True,
        content_object_id=content.id,
        original_filename="합성.hwpx",
        safety_status="safe",
        created_by_name="담당자",
    )
    session.add(document)
    session.flush()
    structure = DocumentStructure(
        document_version_id=document.id,
        source_sha256=SOURCE_SHA,
        media_type="application/hwp+zip",
        extractor_name="hwpx-stdlib",
        extractor_version="1",
        upstream_commit=None,
        payload_content_object_id=content.id,
        payload_sha256=SOURCE_SHA,
        page_count=1,
        block_count=1,
        validation_status="ready",
    )
    session.add(structure)
    session.flush()
    return structure, document


def _old_manifest(session: Session) -> DocumentSegmentManifest:
    structure, document = _seed_structure(session)
    manifest = DocumentSegmentManifest(
        structure_id=structure.id,
        document_version_id=document.id,
        source_sha256=SOURCE_SHA,
        taxonomy_version="bidops.segment-taxonomy.v1",
        extractor_binding={
            "name": "legacy-segment-extractor",
            "version": "1",
            "taxonomy_version": "bidops.segment-taxonomy.v1",
            "rules_sha256": "a" * 64,
            "schema": "bidops.document-segments.v1",
        },
        extractor_binding_sha256="b" * 64,
        inventory_summary={
            "expected_ids": ["SFR-1"],
            "duplicate_ids": [],
            "ambiguous_items": [],
            "prefixes": ["SFR"],
            "item_count": 1,
        },
        warnings=[],
        coverage={
            "block_count": 1,
            "covered_block_count": 1,
            "segment_count": 1,
            "gap_count": 0,
            "overlap_count": 0,
            "gaps": [],
            "overlaps": [],
            "needs_human_review_count": 0,
            "toc": {
                "entry_count": 0,
                "matched_heading_count": 0,
                "unmatched_entry_count": 0,
            },
        },
        payload_sha256="c" * 64,
    )
    session.add(manifest)
    session.flush()
    return manifest


def _card_structure_payload(structure: DocumentStructure, document: DocumentVersion) -> dict:
    return _structure(
        _blocks([
            {"block_key": "anchor-far", "text": "제1장 기능 요구사항"},
            {"block_key": "anchor-near", "text": "제2장 기능 요구사항"},
            *_requirement_card_table(
                [
                    [
                        ("요구사항분류", "기능"),
                        ("요구사항번호", "SFR-001"),
                        ("요구사항명", "합성 기능 하나"),
                        ("정의", "합성 정의 하나"),
                        ("세부내용", "합성 상세 하나"),
                    ],
                    [
                        ("요구사항분류", "기능"),
                        ("요구사항번호", "SFR-002"),
                        ("요구사항명", "합성 기능 둘"),
                        ("정의", "합성 정의 둘"),
                        ("세부내용", "합성 상세 둘"),
                    ],
                ],
                table_key="card-table-1",
            ),
            {"block_key": "after-table-heading", "text": "제3장 품질 및 보안 요구사항"},
        ]),
        structure_id=structure.id,
        document_version_id=document.id,
    )


def _stored_backfill_structure(
    session: Session,
    store: FilesystemObjectStore,
    *,
    name: str,
) -> tuple[DocumentStructure, str]:
    """CLI가 실제 source/structure 고정 객체를 읽을 수 있는 ready 구조."""

    run = Run(id=f"hp01-backfill-{name}-{uuid4()}")
    notice = Notice(
        run=run,
        notice_key=f"hp01-backfill-notice-{name}-{uuid4()}",
        title=f"합성 backfill {name}",
        sample_role="analysis",
    )
    session.add(run)
    session.flush()
    attachment = Attachment(notice=notice, name=f"{name}.hwpx", source_url=None)
    source_bytes = f"source:{name}:{uuid4()}".encode()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    source_key = f"source/{source_sha256[:16]}-{uuid4().hex}.hwpx"
    source_metadata = store.put(
        "source", source_key, source_bytes, content_type="application/hwp+zip"
    )
    source_content = ContentObject(
        sha256=source_sha256,
        size_bytes=len(source_bytes),
        detected_mime="application/hwp+zip",
        retention_class="source",
    )
    session.add_all([attachment, source_content])
    session.flush()
    session.add_all([
        ContentObjectLocation(
            content_object_id=source_content.id,
            namespace_key="source",
            object_key=source_metadata.object_key,
            object_version_id=source_metadata.object_version_id,
            etag=source_metadata.etag,
            status="verified",
        ),
        ContentScan(
            content_object_id=source_content.id,
            scanner="fixture",
            scanner_version="1",
            status="clean",
            safe_result={"fixture": True},
        ),
    ])
    document = DocumentVersion(
        notice_id=notice.id,
        attachment_id=attachment.id,
        version=1,
        source_kind="manual",
        role="제안요청서",
        is_current=True,
        content_object_id=source_content.id,
        original_filename=f"{name}.hwpx",
        safety_status="safe",
        created_by_name="담당자",
    )
    session.add(document)
    session.flush()

    structure_id = uuid4()
    payload = _card_structure_payload(
        SimpleNamespace(id=structure_id),  # type: ignore[arg-type]
        document,
    )
    payload["source_sha256"] = source_sha256
    payload_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    payload_key = f"structure/{payload_sha256[:16]}-{uuid4().hex}.json"
    payload_metadata = store.put(
        "structure",
        payload_key,
        payload_bytes,
        content_type="application/json",
    )
    payload_content = ContentObject(
        sha256=payload_sha256,
        size_bytes=len(payload_bytes),
        detected_mime="application/json",
        retention_class="structure",
    )
    session.add(payload_content)
    session.flush()
    session.add(
        ContentObjectLocation(
            content_object_id=payload_content.id,
            namespace_key="structure",
            object_key=payload_metadata.object_key,
            object_version_id=payload_metadata.object_version_id,
            etag=payload_metadata.etag,
            status="verified",
        )
    )
    structure = DocumentStructure(
        id=structure_id,
        document_version_id=document.id,
        source_sha256=source_sha256,
        media_type="application/hwp+zip",
        extractor_name="hwpx-stdlib",
        extractor_version="1",
        upstream_commit=None,
        payload_content_object_id=payload_content.id,
        payload_sha256=payload_sha256,
        page_count=len(payload["pages"]),
        block_count=len(payload["blocks"]),
        validation_status="ready",
    )
    session.add(structure)
    session.flush()
    return structure, payload_key


def _cli_environment(
    tmp_path: Path,
    database_url: str,
) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("BIDOPS_")
    }
    environment.update({
        "BIDOPS_ROOT": str(PROJECT_ROOT),
        "BIDOPS_DATA_DIR": str(tmp_path / "data"),
        "BIDOPS_ATTACHMENTS_DIR": str(tmp_path / "objects"),
        "BIDOPS_DATABASE_URL": database_url,
        "BIDOPS_OBJECT_STORE_BACKEND": "filesystem",
        "BIDOPS_TEST_MODE": "1",
        "BIDOPS_OPENAI_ENABLED": "false",
        "BIDOPS_PRESPEC_OVERVIEW_ENABLED": "false",
        "PYTHONPATH": str(BACKEND_ROOT),
    })
    return environment


def _run_rebuild_cli(
    environment: dict[str, str],
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "app.deep_review.cli",
            "rebuild-segment-manifests",
            *arguments,
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _worker_database_url(database_url: str) -> tuple[str, str]:
    """runtime policy를 적용하고 worker 권한을 상속한 일회용 login URL을 만든다."""

    login = f"hp01_worker_{uuid4().hex}"
    password = uuid4().hex
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            for role in ("app", "worker", "ro_backup"):
                if connection.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname=:role"),
                    {"role": role},
                ) is None:
                    connection.exec_driver_sql(f'CREATE ROLE "{role}"')
            connection.exec_driver_sql(
                f'CREATE ROLE "{login}" LOGIN INHERIT PASSWORD \'{password}\''
            )
            connection.exec_driver_sql(f'GRANT worker TO "{login}"')
        with engine.connect() as connection:
            cursor = connection.connection.driver_connection.cursor()
            try:
                cursor.execute(RUNTIME_PRIVILEGES, prepare=False)
            finally:
                cursor.close()
    finally:
        engine.dispose()
    worker_url = make_url(database_url).set(
        username=login,
        password=password,
    ).render_as_string(hide_password=False)
    return worker_url, login


def _drop_test_login(database_url: str, login: str) -> None:
    engine = create_engine(database_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{login}"')
    finally:
        engine.dispose()


def _card_page_map_bytes() -> bytes:
    page_map = {
        "schema": "bidops.para-page-map.v1",
        "page_count": 5,
        "paragraph_count": 0,
        "paragraphs": [],
        "blocks": [
            {
                "block_key": "anchor-near",
                "section": 0,
                "para_index": None,
                "page_first": 4,
                "page_last": 4,
                "match": "page_text",
            },
            {
                "block_key": "card-table-1-r1-c0",
                "section": 0,
                "para_index": None,
                "page_first": 5,
                "page_last": 5,
                "match": "page_text",
            },
        ],
        "unmapped_block_keys": [],
        "mapping": {
            "blocks_total": 2,
            "blocks_mapped": 2,
            "blocks_unmapped": 0,
            "rule": "para-page-align.v1",
        },
    }
    return json.dumps(page_map, ensure_ascii=False).encode("utf-8")


def _legacy_rows(
    session: Session,
    structure: DocumentStructure,
    document: DocumentVersion,
) -> tuple[DocumentSegmentManifest, DocumentSegment, RequirementInventoryItem]:
    manifest = DocumentSegmentManifest(
        structure_id=structure.id,
        document_version_id=document.id,
        source_sha256=SOURCE_SHA,
        taxonomy_version="bidops.segment-taxonomy.v1",
        extractor_binding={
            "name": "legacy-segment-extractor",
            "version": "1",
            "taxonomy_version": "bidops.segment-taxonomy.v1",
            "rules_sha256": "a" * 64,
            "schema": "bidops.document-segments.v1",
        },
        extractor_binding_sha256="b" * 64,
        inventory_summary={
            "expected_ids": ["SFR-1"],
            "duplicate_ids": [],
            "ambiguous_items": [],
            "prefixes": ["SFR"],
            "item_count": 1,
        },
        warnings=[],
        coverage={"block_count": 1, "covered_block_count": 1},
        payload_sha256="c" * 64,
    )
    session.add(manifest)
    session.flush()
    locator = {
        "kind": "paragraph",
        "block_key": "legacy-block",
        "page": 1,
        "ordinal": 0,
        "table_key": None,
        "row": None,
        "column": None,
    }
    segment = DocumentSegment(
        manifest_id=manifest.id,
        segment_id="legacy-segment",
        ordinal=1,
        taxonomy_labels=["technical_functional"],
        title="기존 segment",
        start_locator=locator,
        end_locator=locator,
        requirement_ids=["SFR-1"],
        source_block_keys=["legacy-block"],
        classification_source="deterministic",
        confidence=None,
        status="classified",
    )
    item = RequirementInventoryItem(
        manifest_id=manifest.id,
        raw_id="SFR-01",
        normalized_id="SFR-1",
        locator=locator,
        title="기존 항목",
        ordinal=1,
        source="column_header_table",
        card=None,
    )
    session.add_all([segment, item])
    session.flush()
    return manifest, segment, item


@requires_postgres
def test_pg_0037_preserves_existing_rows_and_round_trips_when_no_new_data() -> None:
    with temporary_database(upgrade_to="0036_company_analysis") as database_url:
        engine = schema_bound(
            create_engine(database_url, json_serializer=_json_serializer, future=True)
        )
        segment_id = uuid4()
        inventory_id = uuid4()
        try:
            with Session(engine) as session:
                manifest = _old_manifest(session)
                session.execute(
                    text(
                        """
                        INSERT INTO bidops.document_segment
                            (id, manifest_id, segment_id, ordinal, taxonomy_labels,
                             title, start_locator, end_locator, requirement_ids,
                             source_block_keys, classification_source, confidence, status)
                        VALUES
                            (:id, :manifest_id, 'legacy-segment', 1,
                             CAST('[\"technical_functional\"]' AS jsonb), NULL,
                             CAST(:locator AS jsonb), CAST(:locator AS jsonb),
                             CAST('[\"SFR-1\"]' AS jsonb), CAST('[\"legacy-block\"]' AS jsonb),
                             'deterministic', NULL, 'classified')
                        """
                    ),
                    {
                        "id": segment_id,
                        "manifest_id": manifest.id,
                        "locator": json.dumps(
                            {
                                "kind": "paragraph",
                                "block_key": "legacy-block",
                                "page": 1,
                                "ordinal": 0,
                                "table_key": None,
                                "row": None,
                                "column": None,
                            }
                        ),
                    },
                )
                session.execute(
                    text(
                        """
                        INSERT INTO bidops.requirement_inventory_item
                            (id, manifest_id, raw_id, normalized_id, locator, title, ordinal)
                        VALUES
                            (:id, :manifest_id, 'SFR-01', 'SFR-1',
                             CAST(:locator AS jsonb), '기존 항목', 1)
                        """
                    ),
                    {
                        "id": inventory_id,
                        "manifest_id": manifest.id,
                        "locator": json.dumps(
                            {
                                "kind": "paragraph",
                                "block_key": "legacy-block",
                                "page": 1,
                                "ordinal": 0,
                                "table_key": None,
                                "row": None,
                                "column": None,
                            }
                        ),
                    },
                )
                session.commit()
        finally:
            engine.dispose()

        upgraded = run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
        engine = create_engine(database_url, future=True)
        try:
            with engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT source, card FROM bidops.requirement_inventory_item "
                        "WHERE id=:id"
                    ),
                    {"id": inventory_id},
                ).one()
                assert row.source == "column_header_table" and row.card is None
                assert connection.scalar(
                    text(
                        "SELECT page_anchor_block_keys FROM bidops.document_segment "
                        "WHERE id=:id"
                    ),
                    {"id": segment_id},
                ) is None
                assert connection.scalar(
                    text("SELECT version_num FROM bidops.alembic_version")
                ) == ALEMBIC_HEAD
                assert connection.scalar(
                    text(
                        "SELECT count(*) FROM bidops.screening_audit_event "
                        "WHERE event_type='db.migration' AND target_id=:revision"
                    ),
                    {"revision": ALEMBIC_HEAD},
                ) == 1
        finally:
            engine.dispose()

        downgraded = run_alembic(database_url, "downgrade", "0036_company_analysis")
        assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
        engine = create_engine(database_url, future=True)
        try:
            with engine.connect() as connection:
                columns = set(
                    connection.scalars(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema='bidops' AND table_name IN "
                            "('document_segment','requirement_inventory_item')"
                        )
                    )
                )
                assert not {"source", "card", "page_anchor_block_keys"} & columns
                assert connection.scalar(
                    text(
                        "SELECT count(*) FROM bidops.screening_audit_event "
                        "WHERE event_type='db.migration' AND target_id=:revision"
                    ),
                    {"revision": ALEMBIC_HEAD},
                ) == 0
        finally:
            engine.dispose()

        reupgraded = run_alembic(database_url, "upgrade", "head")
        assert reupgraded.returncode == 0, reupgraded.stdout + reupgraded.stderr


@requires_postgres
def test_pg_store_manifest_persists_card_source_card_json_and_parallel_anchors() -> None:
    with migrated_engine() as engine:
        with Session(engine) as session:
            structure, document = _seed_structure(session)
            session.commit()
            payload = _structure(
                _blocks(
                    [
                        {"block_key": "anchor-1", "text": "제1장 기능 요구사항"},
                        {"block_key": "anchor-2", "text": "요구사항 카드 목록"},
                        *_requirement_card_table(
                            [[
                                ("요구사항분류", "기능"),
                                ("요구사항번호", "SFR-001"),
                                ("요구사항명", "회원 조회"),
                                ("정의", "회원 정보를 조회한다."),
                                ("세부내용", "권한별 회원 정보를 제공한다."),
                            ]]
                        ),
                    ]
                ),
                structure_id=structure.id,
                document_version_id=document.id,
            )
            built = document_segments.build_manifest_payload(payload)
            card_payload = next(
                item
                for item in built["inventory_items"]
                if item["source"] == "label_value_table"
            )
            card_segment_payload = next(
                segment
                for segment in built["segments"]
                if card_payload["locator"]["block_key"] in segment["source_block_keys"]
            )
            expected_anchors_by_segment_id = {
                segment["segment_id"]: anchors
                for segment, anchors in zip(
                    built["segments"], built["segment_anchors"], strict=True
                )
            }
            manifest = document_segments.store_manifest(session, payload)
            session.commit()

            item = session.scalar(
                select(RequirementInventoryItem).where(
                    RequirementInventoryItem.manifest_id == manifest.id,
                    RequirementInventoryItem.source == "label_value_table",
                    RequirementInventoryItem.normalized_id
                    == card_payload["normalized_id"],
                )
            )
            segment = session.scalar(
                select(DocumentSegment).where(
                    DocumentSegment.manifest_id == manifest.id,
                    DocumentSegment.segment_id
                    == card_segment_payload["segment_id"],
                )
            )
            stored_segments = session.scalars(
                select(DocumentSegment)
                .where(DocumentSegment.manifest_id == manifest.id)
                .order_by(DocumentSegment.ordinal.asc())
            ).all()
            stored_anchors_by_segment_id = {
                row.segment_id: list(row.page_anchor_block_keys or [])
                for row in stored_segments
            }
            assert (
                stored_anchors_by_segment_id == expected_anchors_by_segment_id
            )
            assert item is not None
            assert item.source == "label_value_table"
            assert item.card["category"] == "기능"
            assert item.card["page_anchor_block_keys"] == ["anchor-2", "anchor-1"]
            assert segment is not None
            assert segment.page_anchor_block_keys == ["anchor-2", "anchor-1"]

            # Recalculation is idempotent and preserves the immutable stored rows.
            assert document_segments.store_manifest(session, payload).id == manifest.id
            session.commit()
            assert session.scalar(
                text(
                    "SELECT count(*) FROM bidops.requirement_inventory_item "
                    "WHERE manifest_id=:manifest_id"
                ),
                {"manifest_id": manifest.id},
            ) == 1

        refused = run_alembic(
            engine.url.render_as_string(hide_password=False),
            "downgrade",
            "0036_company_analysis",
        )
        assert refused.returncode != 0
        assert "refuses to discard requirement card or page anchor data" in (
            refused.stdout + refused.stderr
        )


@requires_postgres
def test_pg_current_manifest_reads_inherited_segments_and_requirement_cards(tmp_path) -> None:
    with migrated_engine() as engine:
        store = FilesystemObjectStore(tmp_path)
        with Session(engine) as session:
            structure, document = _seed_structure(session)
            payload = _card_structure_payload(structure, document)
            legacy_manifest, legacy_segment, legacy_item = _legacy_rows(
                session, structure, document
            )
            session.commit()

            current_manifest = document_segments.ensure_manifest(session, payload)
            assert current_manifest is not None
            assert current_manifest.id != legacy_manifest.id
            current_manifest_id = current_manifest.id
            structure_id = structure.id
            document_id = document.id
            legacy_manifest_id = legacy_manifest.id
            legacy_segment_id = legacy_segment.id
            legacy_item_id = legacy_item.id
            session.commit()

        _native_snapshot(
            {"engine": engine, "document_id": document_id, "structure_id": structure_id},
            store,
            _card_page_map_bytes(),
        )

        with Session(engine) as session:
            manifests = session.scalars(
                select(DocumentSegmentManifest).where(
                    DocumentSegmentManifest.structure_id == structure_id
                )
            ).all()
            assert {row.id for row in manifests} == {
                legacy_manifest_id,
                current_manifest_id,
            }
            preserved_segment = session.get(DocumentSegment, legacy_segment_id)
            assert preserved_segment is not None
            assert preserved_segment.segment_id == "legacy-segment"
            preserved_item = session.get(RequirementInventoryItem, legacy_item_id)
            assert preserved_item is not None
            assert (preserved_item.raw_id, preserved_item.card) == ("SFR-01", None)

            view = document_segments.segments_view(session, structure_id, store)
            assert view["taxonomy_version"] == document_segments.TAXONOMY_VERSION
            assert view["extractor_binding_sha256"] == (
                document_segments.EXTRACTOR_BINDING_SHA256
            )
            inherited_segments = [
                segment for segment in view["segments"]
                if segment["mapping_status"] == "inherited"
            ]
            assert inherited_segments
            assert inherited_segments[-1]["page_range"] == {"first": 4, "last": 4}

            cards = document_segments.requirement_cards(session, structure_id, store)
            assert [card["normalized_id"] for card in cards] == ["SFR-1", "SFR-2"]
            assert [card["ordinal"] for card in cards] == sorted(
                card["ordinal"] for card in cards
            )
            assert [(card["mapping_status"], card["page_range"]) for card in cards] == [
                ("mapped", {"first": 5, "last": 5}),
                ("inherited", {"first": 4, "last": 4}),
            ]
            assert all(card["source"] == "label_value_table" for card in cards)
            assert all("page_anchor_block_keys" in card["card"] for card in cards)


@requires_postgres
def test_pg_requirement_cards_fails_closed_when_page_map_hash_is_tampered(tmp_path) -> None:
    with migrated_engine() as engine:
        store = FilesystemObjectStore(tmp_path)
        with Session(engine) as session:
            structure, document = _seed_structure(session)
            payload = _card_structure_payload(structure, document)
            document_segments.store_manifest(session, payload)
            session.commit()
            structure_id = structure.id
            document_id = document.id

        _native_snapshot(
            {"engine": engine, "document_id": document_id, "structure_id": structure_id},
            store,
            _card_page_map_bytes(),
            recorded_sha256="f" * 64,
        )

        with Session(engine) as session:
            try:
                document_segments.requirement_cards(session, structure_id, store)
            except document_segments.SegmentViewError as error:
                assert error.code == "processing_failed"
                assert error.status_code == 500
            else:
                raise AssertionError("변조된 para_page_map을 거부해야 합니다")


@requires_postgres
def test_pg_rebuild_segment_manifests_cli_dry_run_create_repeat_missing_and_hash_mismatch(
    tmp_path: Path,
) -> None:
    """T10: 실제 모듈 진입점이 worker 역할로 멱등 backfill하고 안전하게 실패한다."""

    with temporary_database() as database_url:
        owner_engine = schema_bound(create_engine(database_url, future=True))
        store = FilesystemObjectStore(tmp_path / "objects")
        worker_login: str | None = None
        try:
            with Session(owner_engine) as session:
                structure, _payload_key = _stored_backfill_structure(
                    session, store, name="cli-good"
                )
                structure_id = structure.id
                session.commit()

            worker_url, worker_login = _worker_database_url(database_url)
            worker_engine = schema_bound(create_engine(worker_url, future=True))
            try:
                with worker_engine.connect() as connection:
                    assert connection.scalar(
                        text("SELECT pg_has_role(current_user, 'worker', 'member')")
                    ) is True
                    for table in (
                        "document_segment_manifest",
                        "document_segment",
                        "requirement_inventory_item",
                    ):
                        for privilege in ("SELECT", "INSERT"):
                            assert connection.scalar(
                                text(
                                    "SELECT has_table_privilege(current_user, :table, :privilege)"
                                ),
                                {
                                    "table": f"bidops.{table}",
                                    "privilege": privilege,
                                },
                            ) is True
                        for privilege in ("UPDATE", "DELETE"):
                            assert connection.scalar(
                                text(
                                    "SELECT has_table_privilege(current_user, :table, :privilege)"
                                ),
                                {
                                    "table": f"bidops.{table}",
                                    "privilege": privilege,
                                },
                            ) is False
            finally:
                worker_engine.dispose()

            environment = _cli_environment(tmp_path, worker_url)
            dry_run = _run_rebuild_cli(
                environment,
                "--structure-id",
                str(structure_id),
                "--dry-run",
            )
            assert dry_run.returncode == 0, dry_run.stderr
            assert json.loads(dry_run.stdout) == {
                "structure_id": str(structure_id),
                "created": False,
                "manifest_id": None,
                "errors": [],
            }
            with Session(owner_engine) as session:
                assert session.scalar(
                    select(DocumentSegmentManifest).where(
                        DocumentSegmentManifest.structure_id == structure_id,
                        DocumentSegmentManifest.taxonomy_version
                        == document_segments.TAXONOMY_VERSION,
                        DocumentSegmentManifest.extractor_binding_sha256
                        == document_segments.EXTRACTOR_BINDING_SHA256,
                    )
                ) is None

            created = _run_rebuild_cli(
                environment, "--structure-id", str(structure_id)
            )
            assert created.returncode == 0, created.stderr
            created_body = json.loads(created.stdout)
            assert created_body["structure_id"] == str(structure_id)
            assert created_body["created"] is True
            assert created_body["errors"] == []
            manifest_id = UUID(created_body["manifest_id"])

            repeated = _run_rebuild_cli(
                environment, "--structure-id", str(structure_id)
            )
            assert repeated.returncode == 0, repeated.stderr
            assert json.loads(repeated.stdout) == {
                "structure_id": str(structure_id),
                "created": False,
                "manifest_id": str(manifest_id),
                "errors": [],
            }

            missing_id = uuid4()
            missing = _run_rebuild_cli(
                environment, "--structure-id", str(missing_id)
            )
            assert missing.returncode == 2
            assert json.loads(missing.stdout) == {
                "structure_id": str(missing_id),
                "created": False,
                "manifest_id": None,
                "errors": ["not_found"],
            }

            with Session(owner_engine) as session:
                corrupt_structure, corrupt_key = _stored_backfill_structure(
                    session, store, name="cli-hash-mismatch"
                )
                corrupt_structure_id = corrupt_structure.id
                session.commit()
            store.put(
                "structure",
                corrupt_key,
                b"{}",
                content_type="application/json",
            )
            corrupted = _run_rebuild_cli(
                environment, "--structure-id", str(corrupt_structure_id)
            )
            assert corrupted.returncode == 1
            assert json.loads(corrupted.stdout) == {
                "structure_id": str(corrupt_structure_id),
                "created": False,
                "manifest_id": None,
                "errors": ["structure_unavailable"],
            }
            with Session(owner_engine) as session:
                assert session.scalar(
                    select(DocumentSegmentManifest).where(
                        DocumentSegmentManifest.structure_id == corrupt_structure_id
                    )
                ) is None
                assert session.scalar(
                    select(DocumentSegmentManifest).where(
                        DocumentSegmentManifest.id == manifest_id
                    )
                ) is not None
        finally:
            owner_engine.dispose()
            if worker_login is not None:
                _drop_test_login(database_url, worker_login)


@requires_postgres
def test_pg_rebuild_all_preserves_successful_sibling_savepoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """한 구조의 store 실패가 같은 --all 실행의 성공 manifest를 되돌리지 않는다."""

    with migrated_engine() as engine:
        store = FilesystemObjectStore(tmp_path / "objects")
        with Session(engine) as session:
            failed_structure, _ = _stored_backfill_structure(
                session, store, name="savepoint-failed"
            )
            successful_structure, _ = _stored_backfill_structure(
                session, store, name="savepoint-success"
            )
            excluded_structure, _ = _stored_backfill_structure(
                session, store, name="not-ready-excluded"
            )
            excluded_structure.validation_status = "failed"
            failed_id = failed_structure.id
            successful_id = successful_structure.id
            excluded_id = excluded_structure.id
            session.commit()

            real_store_manifest = document_segments.store_manifest

            def store_or_fail(target_session, payload):
                if payload["structure_id"] == str(failed_id):
                    raise RuntimeError("fixture failure must not escape as text")
                return real_store_manifest(target_session, payload)

            monkeypatch.setattr(
                rebuild_segment_manifests,
                "store_manifest",
                store_or_fail,
            )
            rows, exit_code = rebuild_segment_manifests.rebuild(
                session,
                store,
                all_structures=True,
            )
            session.commit()

            by_structure = {UUID(row["structure_id"]): row for row in rows}
            assert exit_code == 1
            assert by_structure[failed_id]["errors"] == ["processing_failed"]
            assert by_structure[failed_id]["manifest_id"] is None
            assert by_structure[successful_id]["created"] is True
            assert by_structure[successful_id]["errors"] == []
            assert excluded_id not in by_structure
            assert session.scalar(
                select(DocumentSegmentManifest).where(
                    DocumentSegmentManifest.structure_id == failed_id
                )
            ) is None
            assert session.scalar(
                select(DocumentSegmentManifest).where(
                    DocumentSegmentManifest.structure_id == successful_id
                )
            ) is not None
            assert session.scalar(
                select(DocumentSegmentManifest).where(
                    DocumentSegmentManifest.structure_id == excluded_id
                )
            ) is None
