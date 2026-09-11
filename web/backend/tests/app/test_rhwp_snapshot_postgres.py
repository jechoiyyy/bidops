"""0023 compatibility, append-only storage and effective worker grants."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.object_store import FilesystemObjectStore
from app.core.db import ensure_database_current
from app.deep_review.models import PrespecV4PdfSnapshot
from tests.postgres import migrated_engine, requires_postgres, run_alembic
from tests.deep_review.test_rhwp_snapshot import NativeConverter, native_processed, prepare, seed_native
from tests.app.test_runtime_database_privileges import _ensure_roles, _apply_policy, _column_privilege, _table_privilege

pytestmark = requires_postgres
CANDIDATE_COLUMNS = ("section_candidates_content_object_id", "section_candidates_location_id", "section_candidates_sha256")
RHWP_COLUMNS = ("hwpx_content_object_id", "hwpx_location_id", "hwpx_verify_jsonb", "structure_id", "structure_location_id", "para_page_map_content_object_id", "para_page_map_location_id", "para_page_map_sha256", "rhwp_binary_sha256", "rhwp_version")
NEW_COLUMNS = (*RHWP_COLUMNS, *CANDIDATE_COLUMNS)
CANDIDATE_FOREIGN_KEYS = """
SELECT c.conname, a.attname, c.confdeltype, t.relname
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
JOIN pg_class t ON t.oid = c.confrelid
WHERE c.conrelid = 'bidops.prespec_v4_pdf_snapshot'::regclass AND c.contype = 'f'
  AND c.conname LIKE 'fk_section_candidates_%'
"""


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


def test_0023_preserves_old_rows_and_reversible_when_unpopulated():
    with migrated_engine(upgrade_to="0022_prespec_v4_attempt") as engine:
        _notice, _document, snapshot_id = _seed_snapshot(engine)
        with engine.connect() as connection:
            before = connection.scalar(text("SELECT to_jsonb(s) FROM bidops.prespec_v4_pdf_snapshot s WHERE id=:id"), {"id": snapshot_id})
        with pytest.raises(RuntimeError, match="migration required"):
            ensure_database_current(engine)
        url = engine.url.render_as_string(hide_password=False)
        result = run_alembic(url, "upgrade", "0023_rhwp_snapshot")
        assert result.returncode == 0, result.stderr
        with engine.connect() as connection:
            after = connection.scalar(text("SELECT to_jsonb(s) FROM bidops.prespec_v4_pdf_snapshot s WHERE id=:id"), {"id": snapshot_id})
        assert {key: value for key, value in after.items() if key not in RHWP_COLUMNS} == before
        assert all(after[key] is None for key in RHWP_COLUMNS)
        for statement in ("UPDATE bidops.prespec_v4_pdf_snapshot SET rhwp_version='0.8.6' WHERE id=:id", "DELETE FROM bidops.prespec_v4_pdf_snapshot WHERE id=:id"):
            with pytest.raises(DBAPIError), engine.begin() as connection:
                connection.execute(text(statement), {"id": snapshot_id})
        result = run_alembic(url, "downgrade", "0022_prespec_v4_attempt")
        assert result.returncode == 0, result.stderr
        with engine.connect() as connection:
            restored = connection.scalar(text("SELECT to_jsonb(s) FROM bidops.prespec_v4_pdf_snapshot s WHERE id=:id"), {"id": snapshot_id})
            guard = connection.scalar(text("SELECT pg_get_functiondef('bidops.tf_prespec_v4_attempt_guard()'::regprocedure)"))
        assert restored == before
        assert "validation_warnings" not in guard


def test_0024_adds_restricted_nullable_candidate_refs_and_is_reversible():
    with migrated_engine(upgrade_to="0023_rhwp_snapshot") as engine:
        _notice, _document, snapshot_id = _seed_snapshot(engine)
        with engine.connect() as connection:
            before = connection.scalar(text("SELECT to_jsonb(s) FROM bidops.prespec_v4_pdf_snapshot s WHERE id=:id"), {"id": snapshot_id})
        with pytest.raises(RuntimeError, match="migration required"):
            ensure_database_current(engine)
        url = engine.url.render_as_string(hide_password=False)
        result = run_alembic(url, "upgrade", "0024_section_candidates")
        assert result.returncode == 0, result.stderr
        with engine.connect() as connection:
            after = connection.scalar(text("SELECT to_jsonb(s) FROM bidops.prespec_v4_pdf_snapshot s WHERE id=:id"), {"id": snapshot_id})
            foreign_keys = set(connection.execute(text(CANDIDATE_FOREIGN_KEYS)).all())
        # The pre-0024 row keeps every stored value and gains three NULLs.
        assert {key: value for key, value in after.items() if key not in CANDIDATE_COLUMNS} == before
        assert all(after[key] is None for key in CANDIDATE_COLUMNS)
        assert foreign_keys == {
            ("fk_section_candidates_section_candidates_content_object_id", "section_candidates_content_object_id", "r", "content_object"),
            ("fk_section_candidates_section_candidates_location_id", "section_candidates_location_id", "r", "content_object_location"),
        }
        result = run_alembic(url, "downgrade", "0023_rhwp_snapshot")
        assert result.returncode == 0, result.stderr
        with engine.connect() as connection:
            restored = connection.scalar(text("SELECT to_jsonb(s) FROM bidops.prespec_v4_pdf_snapshot s WHERE id=:id"), {"id": snapshot_id})
            assert connection.scalar(text("SELECT count(*) FROM bidops.screening_audit_event WHERE target_id='0024_section_candidates'")) == 0
        assert restored == before


@pytest.mark.parametrize("hwp", [False, True])
def test_native_snapshot_roundtrip_worker_insert_and_immutability(tmp_path, hwp):
    _ensure_roles()
    with migrated_engine() as engine:
        policy = _apply_policy(engine.url.render_as_string(hide_password=False))
        policy.dispose()
        processed = native_processed(hwp=hwp)
        converter = NativeConverter(processed)
        store = FilesystemObjectStore(tmp_path)
        with Session(engine) as session:
            document, location = seed_native(session, store, processed)
            session.commit()
            session.connection().exec_driver_sql("SET LOCAL ROLE worker")
            snapshot = prepare(session, store, document, location, converter)
            session.commit()
            snapshot_id = snapshot.id
            assert prepare(session, store, document, location, converter).id == snapshot_id
            assert converter.calls == 1
            assert (snapshot.hwpx_verify_jsonb is not None) == hwp
            assert snapshot.section_candidates_sha256 == hashlib.sha256(processed.section_candidates_bytes).hexdigest()
        with engine.connect() as connection:
            for column in NEW_COLUMNS:
                assert _column_privilege(connection, "worker", "prespec_v4_pdf_snapshot", column, "INSERT")
                assert not _column_privilege(connection, "worker", "prespec_v4_pdf_snapshot", column, "UPDATE")
            assert not _table_privilege(connection, "worker", "prespec_v4_pdf_snapshot", "DELETE")
        with pytest.raises(ValueError, match="append-only"), Session(engine) as session:
            row = session.get(PrespecV4PdfSnapshot, snapshot_id)
            row.para_page_map_sha256 = "d" * 64
            session.flush()
        for statement in ("UPDATE bidops.prespec_v4_pdf_snapshot SET rhwp_version='wrong' WHERE id=:id", "DELETE FROM bidops.prespec_v4_pdf_snapshot WHERE id=:id"):
            with pytest.raises(DBAPIError), engine.begin() as connection:
                connection.execute(text(statement), {"id": snapshot_id})
        # 0026은 되돌리지 않는다. 그 아래로 내려가려는 시도는 전부 실패해야 한다.
        for target in ("0023_rhwp_snapshot", "0022_prespec_v4_attempt"):
            result = run_alembic(engine.url.render_as_string(hide_password=False), "downgrade", target)
            assert result.returncode != 0
