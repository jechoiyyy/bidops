"""PostgreSQL 17 constraints for the immutable v4 prepared-input boundary."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.postgres import migrated_engine, requires_postgres


pytestmark = requires_postgres


def _seed_snapshot(engine):  # type: ignore[no-untyped-def]
    now = datetime(2026, 9, 8, tzinfo=UTC)
    notice_id = None
    document_id = uuid4()
    source_object_id = uuid4()
    page_text_object_id = uuid4()
    source_location_id = uuid4()
    page_text_location_id = uuid4()
    snapshot_id = uuid4()
    with engine.begin() as connection:
        notice_id = connection.scalar(
            text(
                "INSERT INTO bidops.notice (notice_key, source_type) "
                "VALUES (:key, 'pre_spec') RETURNING id"
            ),
            {"key": f"v4-pg-{uuid4()}"},
        )
        for object_id, digest, mime, size in (
            (source_object_id, "a" * 64, "application/pdf", 5),
            (page_text_object_id, "b" * 64, "application/json", 18),
        ):
            connection.execute(
                text(
                    "INSERT INTO bidops.content_object "
                    "(id, sha256, size_bytes, detected_mime, retention_class, created_at) "
                    "VALUES (:id, :sha, :size, :mime, 'document-source', :created_at)"
                ),
                {"id": object_id, "sha": digest, "size": size, "mime": mime, "created_at": now},
            )
        connection.execute(
            text(
                "INSERT INTO bidops.document_version "
                "(id, notice_id, content_object_id, version, source_kind, source_system, "
                "source_attachment_key, original_filename, role, is_current, safety_status, "
                "needs_human_review, created_at) VALUES "
                "(:id, :notice_id, :content_id, 1, 'provider', 'test', 'v4-pg', "
                "'source.pdf', '제안요청서', true, 'safe', false, :created_at)"
            ),
            {"id": document_id, "notice_id": notice_id, "content_id": source_object_id, "created_at": now},
        )
        for location_id, object_id, key in (
            (source_location_id, source_object_id, "source.pdf"),
            (page_text_location_id, page_text_object_id, "page-text.json"),
        ):
            connection.execute(
                text(
                    "INSERT INTO bidops.content_object_location "
                    "(id, content_object_id, namespace_key, object_key, status, verified_at, created_at) "
                    "VALUES (:id, :object_id, 'source', :object_key, 'verified', :verified_at, :created_at)"
                ),
                {
                    "id": location_id,
                    "object_id": object_id,
                    "object_key": key,
                    "verified_at": now,
                    "created_at": now,
                },
            )
        connection.execute(
            text(
                "INSERT INTO bidops.prespec_v4_pdf_snapshot "
                "(id, notice_id, document_version_id, source_content_object_id, source_location_id, "
                "pdf_content_object_id, pdf_location_id, page_text_content_object_id, page_text_location_id, "
                "source_kind, source_sha256, source_size_bytes, pdf_sha256, pdf_size_bytes, pdf_page_count, "
                "page_text_sha256, page_text_size_bytes, pdf_metadata_jsonb, renderer_jsonb, renderer_digest, "
                "font_jsonb, font_digest, config_jsonb, config_sha256, scan_jsonb, binding_sha256, created_at) "
                "VALUES (:id, :notice_id, :document_id, :source_object, :source_location, "
                ":source_object, :source_location, :page_object, :page_location, 'original', "
                ":source_sha, 5, :source_sha, 5, 1, :page_sha, 18, CAST(:metadata AS jsonb), "
                "CAST(:renderer AS jsonb), :renderer_digest, CAST(:font AS jsonb), :font_digest, "
                "CAST(:config AS jsonb), :config_digest, CAST(:scan AS jsonb), :binding, :created_at)"
            ),
            {
                "id": snapshot_id,
                "notice_id": notice_id,
                "document_id": document_id,
                "source_object": source_object_id,
                "source_location": source_location_id,
                "page_object": page_text_object_id,
                "page_location": page_text_location_id,
                "source_sha": "a" * 64,
                "page_sha": "b" * 64,
                "metadata": json.dumps({"schema": "bidops.pdf-snapshot.v1", "page_count": 1}),
                "renderer": json.dumps({"worker_image_digest": "c" * 64}),
                "renderer_digest": "c" * 64,
                "font": json.dumps({"font_manifest_sha256": "d" * 64}),
                "font_digest": "d" * 64,
                "config": json.dumps({"options": {"prepare_pdf": True}}),
                "config_digest": "e" * 64,
                "scan": json.dumps({"verdict": "clean"}),
                "binding": "f" * 64,
                "created_at": now,
            },
        )
    return notice_id, document_id, snapshot_id


def _insert_target(engine, *, notice_id, document_id, snapshot_id, identity: str):  # type: ignore[no-untyped-def]
    with engine.begin() as connection:
        manifest_content_object_id, manifest_location_id = connection.execute(
            text(
                "SELECT page_text_content_object_id, page_text_location_id "
                "FROM bidops.prespec_v4_pdf_snapshot WHERE id = :snapshot_id"
            ),
            {"snapshot_id": snapshot_id},
        ).one()
        connection.execute(
            text(
                "INSERT INTO bidops.prespec_v4_target "
                "(id, notice_id, document_version_id, snapshot_id, observation_kind, observation_jsonb, "
                "selection_status, selection_strategy, start_locator, end_locator, page_numbers_jsonb, "
                "input_text_sha256_jsonb, input_sha256, input_byte_count, selection_manifest_sha256, "
                "identity_sha256, manifest_content_object_id, manifest_location_id, created_at) VALUES "
                "(:id, :notice_id, :document_id, :snapshot_id, 'explicit_sample', CAST(:observation AS jsonb), "
                "'ready', 'heading', CAST(:start AS jsonb), CAST(:end AS jsonb), CAST(:pages AS jsonb), "
                "CAST(:hashes AS jsonb), :input_sha, 4, :manifest_sha, :identity, "
                ":manifest_content_object_id, :manifest_location_id, :created_at)"
            ),
            {
                "id": uuid4(),
                "notice_id": notice_id,
                "document_id": document_id,
                "snapshot_id": snapshot_id,
                "observation": json.dumps({"kind": "explicit_sample"}),
                "start": json.dumps({"page": 1, "line": 0, "char": 0}),
                "end": json.dumps({"page": 1, "line": 1, "char": 4}),
                "pages": json.dumps([1]),
                "hashes": json.dumps(["b" * 64]),
                "input_sha": "1" * 64,
                "manifest_sha": "2" * 64,
                "identity": identity,
                "manifest_content_object_id": manifest_content_object_id,
                "manifest_location_id": manifest_location_id,
                "created_at": datetime(2026, 9, 8, tzinfo=UTC),
            },
        )


def test_v4_postgres_upgrade_fk_duplicate_and_append_only_guards() -> None:
    with migrated_engine() as engine:
        notice_id, document_id, snapshot_id = _seed_snapshot(engine)

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.prespec_v4_pdf_snapshot SET pdf_sha256 = :sha "
                        "WHERE id = :id"
                    ),
                    {"sha": "9" * 64, "id": snapshot_id},
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM bidops.prespec_v4_pdf_snapshot WHERE id = :id"),
                    {"id": snapshot_id},
                )

        _insert_target(
            engine,
            notice_id=notice_id,
            document_id=document_id,
            snapshot_id=snapshot_id,
            identity="3" * 64,
        )
        with pytest.raises(IntegrityError):
            _insert_target(
                engine,
                notice_id=notice_id,
                document_id=document_id,
                snapshot_id=snapshot_id,
                identity="3" * 64,
            )

        other_notice = None
        with engine.begin() as connection:
            other_notice = connection.scalar(
                text(
                    "INSERT INTO bidops.notice (notice_key, source_type) "
                    "VALUES (:key, 'pre_spec') RETURNING id"
                ),
                {"key": f"v4-pg-other-{uuid4()}"},
            )
        with pytest.raises(IntegrityError):
            _insert_target(
                engine,
                notice_id=other_notice,
                document_id=document_id,
                snapshot_id=snapshot_id,
                identity="4" * 64,
            )
