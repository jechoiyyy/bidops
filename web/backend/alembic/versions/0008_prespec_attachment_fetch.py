"""Add the re-evaluated pre-specification attachment fetch queue.

The queue is introduced after the cumulative lifecycle tables so an existing
0007 database can be upgraded in place.  Provider bytes remain outside the
database transaction; this revision only adds the lease and provenance
pointer needed by the backend worker.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_prespec_attachment_fetch"
down_revision = "0007_opportunity_tracking_state"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-7b4e1c9a2d6f4380a5e3b7c1d9f20468"


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _schema() -> str | None:
    return None if _is_sqlite() else SCHEMA


def _table(name: str) -> str:
    return name if _is_sqlite() else f"{SCHEMA}.{name}"


def _record_migration_marker() -> None:
    table = _table("screening_audit_event")
    bind = op.get_bind()
    if _is_sqlite():
        bind.execute(
            sa.text(
                f"""
                INSERT INTO {table}
                    (event_id, event_type, actor, target_type, target_id,
                     occurred_at, details_json)
                VALUES (:event_id, 'db.migration', 'system:migration', 'database',
                        :revision, :occurred_at, :details)
                ON CONFLICT (event_id) DO NOTHING
                """
            ),
            {
                "event_id": _MIGRATION_EVENT_ID,
                "revision": revision,
                "details": '{"migration_revision":"0008_prespec_attachment_fetch","action":"upgrade"}',
                "occurred_at": "2026-01-01 00:00:05+00:00",
            },
        )
        return

    bind.execute(
        sa.text(
            f"""
            INSERT INTO {table}
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
            "details": '{"migration_revision":"0008_prespec_attachment_fetch","action":"upgrade"}',
            "occurred_at": "2026-01-01 00:00:05+00",
        },
    )


def upgrade() -> None:
    schema = _schema()
    attachment_fk = "attachment.id" if _is_sqlite() else f"{SCHEMA}.attachment.id"
    document_version_fk = "document_version.id" if _is_sqlite() else f"{SCHEMA}.document_version.id"

    op.create_table(
        "attachment_fetch",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attachment_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("eligibility_reason", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_fence", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("document_version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["attachment_id"], [attachment_fk], ondelete="CASCADE",
            name="fk_attachment_fetch_attachment",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"], [document_version_fk],
            name="fk_attachment_fetch_document_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attachment_fetch"),
        sa.UniqueConstraint("attachment_id", name="uq_attachment_fetch_attachment"),
        sa.CheckConstraint(
            "status IN ('대기','진행','완료','차단','실패')",
            name="ck_attachment_fetch_status",
        ),
        sa.CheckConstraint(
            "eligibility_reason IN ('sw_business_object','tracked_order_plan','both')",
            name="ck_attachment_fetch_eligibility_reason",
        ),
        sa.CheckConstraint(
            "status <> '완료' OR document_version_id IS NOT NULL",
            name="ck_attachment_fetch_completed_document",
        ),
        sa.CheckConstraint(
            "(status = '진행') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_attachment_fetch_lease",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_attachment_fetch_status_next_attempt",
        "attachment_fetch",
        ["status", "next_attempt_at"],
        schema=schema,
    )
    _record_migration_marker()


def _assert_downgrade_safe() -> None:
    if op.get_bind().scalar(
        sa.text(f"SELECT 1 FROM {_table('attachment_fetch')} LIMIT 1")
    ) is not None:
        raise RuntimeError(
            "0008 downgrade refuses to discard pre-spec attachment fetch state; "
            "reconcile or export the queue before retrying"
        )


def downgrade() -> None:
    _assert_downgrade_safe()
    schema = _schema()
    op.drop_index(
        "ix_attachment_fetch_status_next_attempt",
        table_name="attachment_fetch",
        schema=schema,
    )
    op.drop_table("attachment_fetch", schema=schema)
    op.get_bind().execute(
        sa.text(f"DELETE FROM {_table('screening_audit_event')} WHERE event_id = :event_id"),
        {"event_id": _MIGRATION_EVENT_ID},
    )
