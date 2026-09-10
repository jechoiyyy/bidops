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
from tests.deep_review.test_prespec_v4_postgres import _seed_snapshot, _insert_target
from tests.deep_review.test_rhwp_snapshot import NativeConverter, native_processed, prepare, seed_native
from tests.app.test_runtime_database_privileges import _ensure_roles, _apply_policy, _column_privilege, _table_privilege

pytestmark = requires_postgres
CANDIDATE_COLUMNS = ("section_candidates_content_object_id", "section_candidates_location_id", "section_candidates_sha256")
NEW_COLUMNS = ("hwpx_content_object_id", "hwpx_location_id", "hwpx_verify_jsonb", "structure_id", "structure_location_id", "para_page_map_content_object_id", "para_page_map_location_id", "para_page_map_sha256", "rhwp_binary_sha256", "rhwp_version", *CANDIDATE_COLUMNS)
CANDIDATE_FOREIGN_KEYS = """
SELECT c.conname, a.attname, c.confdeltype, t.relname
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
JOIN pg_class t ON t.oid = c.confrelid
WHERE c.conrelid = 'bidops.prespec_v4_pdf_snapshot'::regclass AND c.contype = 'f'
  AND c.conname LIKE 'fk_section_candidates_%'
"""


def test_0023_preserves_old_rows_and_reversible_when_unpopulated():
    with migrated_engine(upgrade_to="0022_prespec_v4_attempt") as engine:
        _notice, _document, snapshot_id = _seed_snapshot(engine)
        with engine.connect() as connection:
            before = connection.scalar(text("SELECT to_jsonb(s) FROM bidops.prespec_v4_pdf_snapshot s WHERE id=:id"), {"id": snapshot_id})
        with pytest.raises(RuntimeError, match="migration required"):
            ensure_database_current(engine)
        url = engine.url.render_as_string(hide_password=False)
        result = run_alembic(url, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        ensure_database_current(engine)
        with engine.connect() as connection:
            after = connection.scalar(text("SELECT to_jsonb(s) FROM bidops.prespec_v4_pdf_snapshot s WHERE id=:id"), {"id": snapshot_id})
        assert {key: value for key, value in after.items() if key not in NEW_COLUMNS} == before
        assert all(after[key] is None for key in NEW_COLUMNS)
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
        result = run_alembic(url, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        ensure_database_current(engine)
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
            assert _column_privilege(connection, "worker", "prespec_v4_attempt", "validation_warnings", "UPDATE")
        with pytest.raises(ValueError, match="append-only"), Session(engine) as session:
            row = session.get(PrespecV4PdfSnapshot, snapshot_id)
            row.para_page_map_sha256 = "d" * 64
            session.flush()
        for statement in ("UPDATE bidops.prespec_v4_pdf_snapshot SET rhwp_version='wrong' WHERE id=:id", "DELETE FROM bidops.prespec_v4_pdf_snapshot WHERE id=:id"):
            with pytest.raises(DBAPIError), engine.begin() as connection:
                connection.execute(text(statement), {"id": snapshot_id})
        for target in ("0023_rhwp_snapshot", "0022_prespec_v4_attempt"):
            result = run_alembic(engine.url.render_as_string(hide_password=False), "downgrade", target)
            assert result.returncode != 0 and "downgrade refused" in result.stderr


def test_validation_warnings_only_change_with_nonterminal_outcome():
    _ensure_roles()
    with migrated_engine() as engine:
        policy = _apply_policy(engine.url.render_as_string(hide_password=False))
        policy.dispose()
        notice_id, document_id, snapshot_id = _seed_snapshot(engine)
        _insert_target(engine, notice_id=notice_id, document_id=document_id, snapshot_id=snapshot_id, identity="5" * 64)
        attempt_id = uuid4()
        with engine.begin() as connection:
            target_id = connection.scalar(text("SELECT id FROM bidops.prespec_v4_target WHERE snapshot_id=:id"), {"id": snapshot_id})
            connection.execute(text("""INSERT INTO bidops.prespec_v4_attempt
                (id,notice_id,document_version_id,target_id,sequence,quality_status,status,created_at)
                VALUES (:id,:notice,:document,:target,1,'unmeasured_reference','queued',:now)"""),
                {"id": attempt_id, "notice": notice_id, "document": document_id, "target": target_id, "now": datetime.now(UTC)})
        warnings = [{"code": "pdf_inline_locator_normalized"}]
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE worker")
            connection.execute(text("""UPDATE bidops.prespec_v4_attempt SET status='failed',
                completed_at=now(),error_code='test',validation_warnings=CAST(:warnings AS jsonb) WHERE id=:id"""),
                {"id": attempt_id, "warnings": json.dumps(warnings)})
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT validation_warnings FROM bidops.prespec_v4_attempt WHERE id=:id"), {"id": attempt_id}) == warnings
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(text("UPDATE bidops.prespec_v4_attempt SET validation_warnings='[]'::jsonb WHERE id=:id"), {"id": attempt_id})
