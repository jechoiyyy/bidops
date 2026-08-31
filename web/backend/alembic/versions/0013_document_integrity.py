"""Enforce document lineage and bundle ordinal integrity.

Revision ID: 0013_document_integrity
Revises: 0012_prespec_overview_review

Fresh installs may already have these constraints because revision 0001 uses
the current closed ORM table set.  This revision therefore always audits the
existing rows, then creates each catalog object only when it is absent.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_document_integrity"
down_revision = "0012_prespec_overview_review"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-8d5e7f3a2b6149c0a4f6d8e1937b205c"
_ATTACHMENT_VERSION_INDEX = "uq_document_version_attachment_version"
_ATTACHMENT_CURRENT_INDEX = "uq_document_version_attachment_current"
_BUNDLE_ORDINAL_CONSTRAINT = "uq_document_bundle_item_bundle_ordinal"


def _preflight_attachment_versions() -> None:
    rows = op.get_bind().execute(
        sa.text(
            f"""
            SELECT
                attachment_id,
                version,
                array_agg(id::text ORDER BY id::text) AS document_version_ids
            FROM {SCHEMA}.document_version
            WHERE attachment_id IS NOT NULL
            GROUP BY attachment_id, version
            HAVING count(*) > 1
            ORDER BY attachment_id, version
            LIMIT 50
            """
        )
    ).all()
    if rows:
        detail = "; ".join(
            "attachment_id={} version={} document_version_ids=[{}]".format(
                row.attachment_id,
                row.version,
                ", ".join(row.document_version_ids),
            )
            for row in rows
        )
        raise RuntimeError(
            "0013 upgrade found duplicate document attachment/version keys; "
            "reconcile these rows without guessing, then retry: " + detail
        )


def _preflight_attachment_current() -> None:
    rows = op.get_bind().execute(
        sa.text(
            f"""
            SELECT
                attachment_id,
                array_agg(id::text ORDER BY id::text) AS document_version_ids
            FROM {SCHEMA}.document_version
            WHERE attachment_id IS NOT NULL
              AND is_current IS TRUE
            GROUP BY attachment_id
            HAVING count(*) > 1
            ORDER BY attachment_id
            LIMIT 50
            """
        )
    ).all()
    if rows:
        detail = "; ".join(
            "attachment_id={} current_document_version_ids=[{}]".format(
                row.attachment_id,
                ", ".join(row.document_version_ids),
            )
            for row in rows
        )
        raise RuntimeError(
            "0013 upgrade found multiple current document versions for an attachment; "
            "reconcile these rows without guessing, then retry: " + detail
        )


def _preflight_bundle_ordinals() -> None:
    rows = op.get_bind().execute(
        sa.text(
            f"""
            SELECT
                bundle_id::text AS bundle_id,
                ordinal,
                array_agg(document_version_id::text ORDER BY document_version_id::text)
                    AS document_version_ids
            FROM {SCHEMA}.document_bundle_item
            GROUP BY bundle_id, ordinal
            HAVING count(*) > 1
            ORDER BY bundle_id, ordinal
            LIMIT 50
            """
        )
    ).all()
    if rows:
        detail = "; ".join(
            "bundle_id={} ordinal={} document_version_ids=[{}]".format(
                row.bundle_id,
                row.ordinal,
                ", ".join(row.document_version_ids),
            )
            for row in rows
        )
        raise RuntimeError(
            "0013 upgrade found duplicate document bundle ordinals; "
            "reconcile these rows without guessing, then retry: " + detail
        )


def _preflight() -> None:
    # Run every data check before any DDL.  A failed upgrade must leave both
    # the schema and Alembic revision at 0012.
    _preflight_attachment_versions()
    _preflight_attachment_current()
    _preflight_bundle_ordinals()


def _index_exists(name: str) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                """
                SELECT 1
                FROM pg_catalog.pg_class AS index_class
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = index_class.relnamespace
                WHERE namespace.nspname = :schema
                  AND index_class.relkind = 'i'
                  AND index_class.relname = :name
                """
            ),
            {"schema": SCHEMA, "name": name},
        )
    )


def _constraint_exists(table: str, name: str) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                """
                SELECT 1
                FROM pg_catalog.pg_constraint AS constraint_row
                JOIN pg_catalog.pg_class AS table_class
                  ON table_class.oid = constraint_row.conrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = table_class.relnamespace
                WHERE namespace.nspname = :schema
                  AND table_class.relname = :table
                  AND constraint_row.conname = :name
                """
            ),
            {"schema": SCHEMA, "table": table, "name": name},
        )
    )


def _create_constraints() -> None:
    if not _index_exists(_ATTACHMENT_VERSION_INDEX):
        op.create_index(
            _ATTACHMENT_VERSION_INDEX,
            "document_version",
            ["attachment_id", "version"],
            unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text("attachment_id IS NOT NULL"),
        )
    if not _index_exists(_ATTACHMENT_CURRENT_INDEX):
        op.create_index(
            _ATTACHMENT_CURRENT_INDEX,
            "document_version",
            ["attachment_id"],
            unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text(
                "attachment_id IS NOT NULL AND is_current IS TRUE"
            ),
        )
    if not _constraint_exists("document_bundle_item", _BUNDLE_ORDINAL_CONSTRAINT):
        op.create_unique_constraint(
            _BUNDLE_ORDINAL_CONSTRAINT,
            "document_bundle_item",
            ["bundle_id", "ordinal"],
            schema=SCHEMA,
        )


def _record_migration_marker() -> None:
    op.get_bind().execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA}.screening_audit_event
                (event_id, event_type, actor, target_type, target_id,
                 occurred_at, details_json)
            VALUES (:event_id, 'db.migration', 'system:migration', 'database',
                    :revision, CAST(:occurred_at AS timestamptz),
                    CAST(:details AS json))
            ON CONFLICT (event_id) DO NOTHING
            """
        ),
        {
            "event_id": _MIGRATION_EVENT_ID,
            "revision": revision,
            "occurred_at": "2026-01-01 00:00:10+00",
            "details": (
                '{"migration_revision":"0013_document_integrity",'
                '"action":"upgrade"}'
            ),
        },
    )


def upgrade() -> None:
    _preflight()
    _create_constraints()
    _record_migration_marker()


def downgrade() -> None:
    # Removing these constraints discards no rows.  Catalog checks keep the
    # downgrade safe for both the fresh-install and 0012-upgrade paths.
    if _constraint_exists("document_bundle_item", _BUNDLE_ORDINAL_CONSTRAINT):
        op.drop_constraint(
            _BUNDLE_ORDINAL_CONSTRAINT,
            table_name="document_bundle_item",
            type_="unique",
            schema=SCHEMA,
        )
    if _index_exists(_ATTACHMENT_CURRENT_INDEX):
        op.drop_index(
            _ATTACHMENT_CURRENT_INDEX,
            table_name="document_version",
            schema=SCHEMA,
        )
    if _index_exists(_ATTACHMENT_VERSION_INDEX):
        op.drop_index(
            _ATTACHMENT_VERSION_INDEX,
            table_name="document_version",
            schema=SCHEMA,
        )
    op.get_bind().execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
