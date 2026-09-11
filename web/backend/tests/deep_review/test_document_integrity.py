"""Document lineage, current-row, ordinal, and 0013 migration contracts."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import ALEMBIC_HEAD, init_db, schema_bound
from app.deep_review.models import (
    ContentObject,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
)
from app.lifecycle.models import Attachment, Notice
from tests.postgres import requires_postgres, run_alembic, temporary_database


MIGRATION_BASE = "0012_prespec_overview_review"
ATTACHMENT_VERSION_INDEX = "uq_document_version_attachment_version"
ATTACHMENT_CURRENT_INDEX = "uq_document_version_attachment_current"
BUNDLE_ORDINAL_CONSTRAINT = "uq_document_bundle_item_bundle_ordinal"


def _sqlite_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    return engine


def _content(session: Session, token: int) -> ContentObject:
    row = ContentObject(
        sha256=f"{token:064x}",
        size_bytes=token,
        detected_mime="application/pdf",
        retention_class="document-source",
    )
    session.add(row)
    session.flush()
    return row


def _notice(session: Session, label: str) -> Notice:
    row = Notice(notice_key=f"integrity:{label}:{uuid4()}")
    session.add(row)
    session.flush()
    return row


def _attachment(session: Session, notice: Notice, label: str) -> Attachment:
    row = Attachment(notice_id=notice.id, name=f"{label}.pdf", origin="manual")
    session.add(row)
    session.flush()
    return row


def _document(
    session: Session,
    notice: Notice,
    content: ContentObject,
    *,
    attachment: Attachment | None,
    version: int,
    is_current: bool,
) -> DocumentVersion:
    row = DocumentVersion(
        notice_id=notice.id,
        attachment_id=attachment.id if attachment is not None else None,
        content_object_id=content.id,
        version=version,
        source_kind="manual",
        original_filename=f"v{version}-{uuid4()}.pdf",
        role="기타",
        is_current=is_current,
        safety_status="safe",
        needs_human_review=False,
    )
    session.add(row)
    session.flush()
    return row


def _bundle_item(
    session: Session,
    bundle: DocumentBundle,
    document: DocumentVersion,
    content: ContentObject,
    *,
    ordinal: int,
) -> DocumentBundleItem:
    structure = DocumentStructure(
        document_version_id=document.id,
        source_sha256=content.sha256,
        media_type=content.detected_mime,
        extractor_name="fixture",
        extractor_version="1",
        payload_content_object_id=content.id,
        payload_sha256=content.sha256,
        page_count=1,
        block_count=1,
        validation_status="ready",
    )
    session.add(structure)
    session.flush()
    item = DocumentBundleItem(
        bundle_id=bundle.id,
        document_version_id=document.id,
        ordinal=ordinal,
        document_version_version=document.version,
        content_object_id=content.id,
        content_sha256=content.sha256,
        detected_mime=content.detected_mime,
        size_bytes=content.size_bytes,
        original_filename=document.original_filename,
        source_kind=document.source_kind,
        source_system=None,
        source_attachment_key=None,
        source_url=None,
        role_at_confirmation=document.role,
        effective_date_at_confirmation=None,
        replaces_id_at_confirmation=None,
        is_current_at_confirmation=document.is_current,
        safety_status_at_confirmation=document.safety_status,
        structure_id_at_confirmation=structure.id,
        structure_payload_sha256=structure.payload_sha256,
    )
    session.add(item)
    session.flush()
    return item


def test_sqlite_document_partial_unique_constraints_and_null_scope() -> None:
    engine = _sqlite_engine()
    inspector = inspect(engine)
    indexes = {row["name"] for row in inspector.get_indexes("document_version")}
    assert indexes >= {ATTACHMENT_VERSION_INDEX, ATTACHMENT_CURRENT_INDEX}

    with Session(engine) as session:
        notice = _notice(session, "duplicate-version")
        attachment = _attachment(session, notice, "duplicate-version")
        content = _content(session, 1)
        _document(
            session,
            notice,
            content,
            attachment=attachment,
            version=1,
            is_current=False,
        )
        session.commit()
        with pytest.raises(IntegrityError):
            _document(
                session,
                notice,
                content,
                attachment=attachment,
                version=1,
                is_current=False,
            )
        session.rollback()

        current_notice = _notice(session, "duplicate-current")
        current_attachment = _attachment(session, current_notice, "duplicate-current")
        current_content = _content(session, 2)
        _document(
            session,
            current_notice,
            current_content,
            attachment=current_attachment,
            version=1,
            is_current=True,
        )
        session.commit()
        with pytest.raises(IntegrityError):
            _document(
                session,
                current_notice,
                current_content,
                attachment=current_attachment,
                version=2,
                is_current=True,
            )
        session.rollback()

        null_notice = _notice(session, "null-scope")
        null_content = _content(session, 3)
        first = _document(
            session,
            null_notice,
            null_content,
            attachment=None,
            version=1,
            is_current=True,
        )
        second = _document(
            session,
            null_notice,
            null_content,
            attachment=None,
            version=1,
            is_current=True,
        )
        session.commit()
        assert first.id != second.id


def test_sqlite_bundle_ordinal_is_unique() -> None:
    engine = _sqlite_engine()
    with Session(engine) as session:
        notice = _notice(session, "bundle-ordinal")
        bundle = DocumentBundle(
            notice_id=notice.id,
            revision=1,
            version=1,
            status="draft",
            issues_snapshot=[],
        )
        session.add(bundle)
        session.flush()
        first_content = _content(session, 10)
        second_content = _content(session, 11)
        first = _document(
            session,
            notice,
            first_content,
            attachment=None,
            version=1,
            is_current=True,
        )
        second = _document(
            session,
            notice,
            second_content,
            attachment=None,
            version=1,
            is_current=True,
        )
        _bundle_item(session, bundle, first, first_content, ordinal=0)
        session.commit()
        with pytest.raises(IntegrityError):
            _bundle_item(session, bundle, second, second_content, ordinal=0)
        session.rollback()


def _drop_integrity_objects(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"ALTER TABLE bidops.document_bundle_item "
                f"DROP CONSTRAINT IF EXISTS {BUNDLE_ORDINAL_CONSTRAINT}"
            )
        )
        connection.execute(
            text(f"DROP INDEX IF EXISTS bidops.{ATTACHMENT_CURRENT_INDEX}")
        )
        connection.execute(
            text(f"DROP INDEX IF EXISTS bidops.{ATTACHMENT_VERSION_INDEX}")
        )


def _integrity_objects(engine) -> tuple[bool, bool, bool]:
    with engine.connect() as connection:
        version_index = bool(
            connection.scalar(
                text(
                    "SELECT 1 FROM pg_indexes WHERE schemaname = 'bidops' "
                    "AND indexname = :name"
                ),
                {"name": ATTACHMENT_VERSION_INDEX},
            )
        )
        current_index = bool(
            connection.scalar(
                text(
                    "SELECT 1 FROM pg_indexes WHERE schemaname = 'bidops' "
                    "AND indexname = :name"
                ),
                {"name": ATTACHMENT_CURRENT_INDEX},
            )
        )
        ordinal_constraint = bool(
            connection.scalar(
                text(
                    "SELECT 1 FROM pg_constraint AS constraint_row "
                    "JOIN pg_class AS table_row ON table_row.oid = constraint_row.conrelid "
                    "JOIN pg_namespace AS namespace ON namespace.oid = table_row.relnamespace "
                    "WHERE namespace.nspname = 'bidops' "
                    "AND table_row.relname = 'document_bundle_item' "
                    "AND constraint_row.conname = :name"
                ),
                {"name": BUNDLE_ORDINAL_CONSTRAINT},
            )
        )
    return version_index, current_index, ordinal_constraint


def _postgres_engine(database_url: str):
    return schema_bound(create_engine(database_url, future=True))


@requires_postgres
def test_postgresql_document_constraints_match_sqlite_and_allow_null_scope() -> None:
    with temporary_database() as database_url:
        engine = _postgres_engine(database_url)
        assert _integrity_objects(engine) == (True, True, True)
        with Session(engine) as session:
            notice = _notice(session, "pg-version")
            attachment = _attachment(session, notice, "pg-version")
            content = _content(session, 20)
            _document(
                session,
                notice,
                content,
                attachment=attachment,
                version=1,
                is_current=False,
            )
            session.commit()
            with pytest.raises(IntegrityError):
                _document(
                    session,
                    notice,
                    content,
                    attachment=attachment,
                    version=1,
                    is_current=False,
                )
            session.rollback()

            current_notice = _notice(session, "pg-current")
            current_attachment = _attachment(session, current_notice, "pg-current")
            current_content = _content(session, 21)
            _document(
                session,
                current_notice,
                current_content,
                attachment=current_attachment,
                version=1,
                is_current=True,
            )
            session.commit()
            with pytest.raises(IntegrityError):
                _document(
                    session,
                    current_notice,
                    current_content,
                    attachment=current_attachment,
                    version=2,
                    is_current=True,
                )
            session.rollback()

            null_notice = _notice(session, "pg-null")
            null_content = _content(session, 22)
            _document(
                session,
                null_notice,
                null_content,
                attachment=None,
                version=1,
                is_current=True,
            )
            _document(
                session,
                null_notice,
                null_content,
                attachment=None,
                version=1,
                is_current=True,
            )
            session.commit()

            bundle_notice = _notice(session, "pg-bundle")
            bundle = DocumentBundle(
                notice_id=bundle_notice.id,
                revision=1,
                version=1,
                status="draft",
                issues_snapshot=[],
            )
            session.add(bundle)
            session.flush()
            first_content = _content(session, 23)
            second_content = _content(session, 24)
            first = _document(
                session,
                bundle_notice,
                first_content,
                attachment=None,
                version=1,
                is_current=True,
            )
            second = _document(
                session,
                bundle_notice,
                second_content,
                attachment=None,
                version=1,
                is_current=True,
            )
            _bundle_item(session, bundle, first, first_content, ordinal=0)
            session.commit()
            with pytest.raises(IntegrityError):
                _bundle_item(session, bundle, second, second_content, ordinal=0)
            session.rollback()
        engine.dispose()


def _seed_preflight_conflict(session: Session, conflict: str) -> list[str]:
    notice = _notice(session, conflict)
    first_content = _content(session, 30)
    second_content = _content(session, 31)
    if conflict == "duplicate-version":
        attachment = _attachment(session, notice, conflict)
        first = _document(
            session,
            notice,
            first_content,
            attachment=attachment,
            version=7,
            is_current=False,
        )
        second = _document(
            session,
            notice,
            second_content,
            attachment=attachment,
            version=7,
            is_current=False,
        )
        session.commit()
        return [str(attachment.id), "7", str(first.id), str(second.id)]
    if conflict == "multiple-current":
        attachment = _attachment(session, notice, conflict)
        first = _document(
            session,
            notice,
            first_content,
            attachment=attachment,
            version=1,
            is_current=True,
        )
        second = _document(
            session,
            notice,
            second_content,
            attachment=attachment,
            version=2,
            is_current=True,
        )
        session.commit()
        return [str(attachment.id), str(first.id), str(second.id)]

    bundle = DocumentBundle(
        notice_id=notice.id,
        revision=1,
        version=1,
        status="draft",
        issues_snapshot=[],
    )
    session.add(bundle)
    session.flush()
    first = _document(
        session,
        notice,
        first_content,
        attachment=None,
        version=1,
        is_current=True,
    )
    second = _document(
        session,
        notice,
        second_content,
        attachment=None,
        version=1,
        is_current=True,
    )
    _bundle_item(session, bundle, first, first_content, ordinal=4)
    _bundle_item(session, bundle, second, second_content, ordinal=4)
    session.commit()
    return [str(bundle.id), "4", str(first.id), str(second.id)]


@pytest.mark.parametrize(
    ("conflict", "message"),
    [
        ("duplicate-version", "duplicate document attachment/version keys"),
        ("multiple-current", "multiple current document versions for an attachment"),
        ("duplicate-ordinal", "duplicate document bundle ordinals"),
    ],
)
@requires_postgres
def test_0013_preflight_reports_keys_and_keeps_0012(
    conflict: str,
    message: str,
) -> None:
    with temporary_database(upgrade_to=MIGRATION_BASE) as database_url:
        engine = _postgres_engine(database_url)
        _drop_integrity_objects(engine)
        with Session(engine) as session:
            expected_tokens = _seed_preflight_conflict(session, conflict)

        result = run_alembic(database_url, "upgrade", "head")

        assert result.returncode != 0
        output = result.stdout + result.stderr
        assert message in output
        for token in expected_tokens:
            assert token in output
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM bidops.alembic_version")
            ) == MIGRATION_BASE
        assert _integrity_objects(engine) == (False, False, False)
        engine.dispose()


@requires_postgres
def test_0012_to_head_and_0013_downgrade_upgrade_round_trip() -> None:
    with temporary_database(upgrade_to=MIGRATION_BASE) as database_url:
        engine = _postgres_engine(database_url)
        _drop_integrity_objects(engine)
        assert _integrity_objects(engine) == (False, False, False)

        # 0026이 그 아래 downgrade를 닫았으므로 왕복은 0013 판에 고정한다.
        upgraded = run_alembic(database_url, "upgrade", "0013_document_integrity")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
        assert _integrity_objects(engine) == (True, True, True)
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM bidops.alembic_version")
            ) == "0013_document_integrity"

        downgraded = run_alembic(database_url, "downgrade", MIGRATION_BASE)
        assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
        assert _integrity_objects(engine) == (False, False, False)

        reupgraded = run_alembic(database_url, "upgrade", "0013_document_integrity")
        assert reupgraded.returncode == 0, reupgraded.stdout + reupgraded.stderr
        assert _integrity_objects(engine) == (True, True, True)
        engine.dispose()
