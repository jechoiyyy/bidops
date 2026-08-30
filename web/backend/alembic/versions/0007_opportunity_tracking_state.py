"""Add human tracking state and an independent recheck signal to opportunities.

Revision ID: 0007_opportunity_tracking_state
Revises: 0006_bid_first_opportunity_registration

Every opportunity receives the human-only ``미선택`` default.  A system
recheck signal keeps its timestamp and points to the exact official
``opportunity_link`` that caused it; it never occupies the human selection
columns.  Existing rows are explicitly backfilled to ``미선택`` before the
status column becomes NOT NULL.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_opportunity_tracking_state"
down_revision = "0006_bid_first_opportunity_registration"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-4f7a9c2e1d6b4385a0f3e8c7b2d19460"
_TRACKING_STATUS_DEFAULT = "'미선택'"

_TRACKING_STATUS_CHECK = "tracking_status IN ('미선택', '계속 추적', '보류', '종료')"
_TRACKING_METADATA_CHECK = (
    "((tracking_status = '미선택' AND tracking_selected_by IS NULL "
    "AND tracking_reason IS NULL AND tracking_selected_at IS NULL) OR "
    "(tracking_status <> '미선택' AND tracking_selected_by IS NOT NULL "
    "AND length(trim(tracking_selected_by)) > 0 "
    "AND tracking_selected_at IS NOT NULL))"
)
_RECHECK_SIGNAL_PAIR_CHECK = (
    "(recheck_signal_at IS NULL AND recheck_signal_link_id IS NULL) OR "
    "(recheck_signal_at IS NOT NULL AND recheck_signal_link_id IS NOT NULL)"
)


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _qualified_opportunity() -> str:
    return "opportunity" if _is_sqlite() else f"{SCHEMA}.opportunity"


def _add_columns() -> None:
    columns = (
        sa.Column(
            "tracking_status",
            sa.String(length=32),
            server_default=sa.text(_TRACKING_STATUS_DEFAULT),
            nullable=True,
        ),
        sa.Column("tracking_reason", sa.Text(), nullable=True),
        sa.Column("tracking_selected_by", sa.String(length=128), nullable=True),
        sa.Column(
            "tracking_selected_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("recheck_signal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recheck_signal_link_id", sa.Integer(), nullable=True),
    )

    if _is_sqlite():
        # SQLite cannot ALTER TABLE to add a foreign key or CHECK constraint;
        # batch recreation keeps this direct revision testable without
        # weakening the PostgreSQL DDL contract.
        with op.batch_alter_table("opportunity", recreate="always") as batch:
            for column in columns:
                batch.add_column(column)
        return

    for column in columns:
        op.add_column("opportunity", column, schema=SCHEMA)


def _backfill_existing_rows() -> None:
    # Keep this explicit even though the temporary server default also fills
    # rows on PostgreSQL.  It documents and verifies the intended behavior for
    # databases that already contain opportunities at upgrade time.
    op.get_bind().execute(
        sa.text(
            f"UPDATE {_qualified_opportunity()} "
            "SET tracking_status = :default_status "
            "WHERE tracking_status IS NULL"
        ),
        {"default_status": "미선택"},
    )


def _add_constraints() -> None:
    if _is_sqlite():
        with op.batch_alter_table("opportunity", recreate="always") as batch:
            batch.alter_column(
                "tracking_status",
                existing_type=sa.String(length=32),
                existing_server_default=sa.text(_TRACKING_STATUS_DEFAULT),
                nullable=False,
            )
            batch.create_check_constraint(
                "ck_opportunity_tracking_status", _TRACKING_STATUS_CHECK
            )
            batch.create_check_constraint(
                "ck_opportunity_tracking_metadata", _TRACKING_METADATA_CHECK
            )
            batch.create_check_constraint(
                "ck_opportunity_recheck_signal_pair", _RECHECK_SIGNAL_PAIR_CHECK
            )
            batch.create_foreign_key(
                "fk_opportunity_recheck_signal_link",
                "opportunity_link",
                ["recheck_signal_link_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        return

    op.alter_column(
        "opportunity",
        "tracking_status",
        existing_type=sa.String(length=32),
        existing_server_default=sa.text(_TRACKING_STATUS_DEFAULT),
        nullable=False,
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_opportunity_tracking_status",
        "opportunity",
        _TRACKING_STATUS_CHECK,
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_opportunity_tracking_metadata",
        "opportunity",
        _TRACKING_METADATA_CHECK,
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_opportunity_recheck_signal_pair",
        "opportunity",
        _RECHECK_SIGNAL_PAIR_CHECK,
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_opportunity_recheck_signal_link",
        "opportunity",
        "opportunity_link",
        ["recheck_signal_link_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )


def _record_migration_marker() -> None:
    table = "screening_audit_event" if _is_sqlite() else f"{SCHEMA}.screening_audit_event"
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
                "details": '{"migration_revision":"0007_opportunity_tracking_state","action":"upgrade"}',
                "occurred_at": "2026-01-01 00:00:04+00:00",
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
            "details": '{"migration_revision":"0007_opportunity_tracking_state","action":"upgrade"}',
            "occurred_at": "2026-01-01 00:00:04+00:00",
        },
    )


def upgrade() -> None:
    _add_columns()
    _backfill_existing_rows()
    _add_constraints()
    _record_migration_marker()


def _assert_downgrade_safe() -> None:
    # A rollback must not silently discard human decisions, reasons, or
    # recheck evidence.  Default-only rows are safe to remove with the new
    # columns; populated tracking data must be reconciled first.
    if op.get_bind().scalar(
        sa.text(
            f"SELECT 1 FROM {_qualified_opportunity()} WHERE "
            "tracking_status <> '미선택' "
            "OR tracking_reason IS NOT NULL "
            "OR tracking_selected_by IS NOT NULL "
            "OR tracking_selected_at IS NOT NULL "
            "OR recheck_signal_at IS NOT NULL "
            "OR recheck_signal_link_id IS NOT NULL LIMIT 1"
        )
    ) is not None:
        raise RuntimeError(
            "0007 downgrade refuses to discard opportunity tracking choices "
            "or recheck evidence; export or reconcile them before retrying"
        )


def _remove_columns() -> None:
    if _is_sqlite():
        with op.batch_alter_table("opportunity", recreate="always") as batch:
            batch.drop_constraint(
                "fk_opportunity_recheck_signal_link", type_="foreignkey"
            )
            batch.drop_constraint(
                "ck_opportunity_recheck_signal_pair", type_="check"
            )
            batch.drop_constraint(
                "ck_opportunity_tracking_metadata", type_="check"
            )
            batch.drop_constraint(
                "ck_opportunity_tracking_status", type_="check"
            )
            for column_name in (
                "recheck_signal_link_id",
                "recheck_signal_at",
                "tracking_selected_at",
                "tracking_selected_by",
                "tracking_reason",
                "tracking_status",
            ):
                batch.drop_column(column_name)
        return

    op.drop_constraint(
        "fk_opportunity_recheck_signal_link",
        table_name="opportunity",
        schema=SCHEMA,
        type_="foreignkey",
    )
    for name in (
        "ck_opportunity_recheck_signal_pair",
        "ck_opportunity_tracking_metadata",
        "ck_opportunity_tracking_status",
    ):
        op.drop_constraint(name, table_name="opportunity", schema=SCHEMA, type_="check")
    for column_name in (
        "recheck_signal_link_id",
        "recheck_signal_at",
        "tracking_selected_at",
        "tracking_selected_by",
        "tracking_reason",
        "tracking_status",
    ):
        op.drop_column("opportunity", column_name, schema=SCHEMA)


def _delete_migration_marker() -> None:
    table = "screening_audit_event" if _is_sqlite() else f"{SCHEMA}.screening_audit_event"
    op.get_bind().execute(
        sa.text(f"DELETE FROM {table} WHERE event_id = :event_id"),
        {"event_id": _MIGRATION_EVENT_ID},
    )


def downgrade() -> None:
    _assert_downgrade_safe()
    _remove_columns()
    _delete_migration_marker()
