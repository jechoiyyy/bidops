"""Persist pre-spec overview cut lineage and future model attempts.

Revision ID: 0012_prespec_overview_review
Revises: 0011_judgment_review_revisions

The logical review owns only its current state and current snapshot pointer.
Document/input lineage is immutable in ``prespec_overview_snapshot`` and
future model executions are append-only in ``prespec_overview_attempt``.
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_prespec_overview_review"
down_revision = "0011_judgment_review_revisions"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-7c4d8e2f1a6940b3b6e9d2f7158ac031"

_REVIEW_STATUSES = (
    "'awaiting_document','awaiting_structure','preparing','awaiting_model',"
    "'queued','running','needs_human_review','completed','failed','cancelled'"
)


def _ensure_unique_constraint(table: str, name: str, columns: list[str]) -> bool:
    """Create a composite FK target only when the base schema lacks it.

    ``0001`` builds its table set from the declarative metadata.  New code
    therefore creates these constraints on a fresh database before 0012,
    while an already-migrated installation needs 0012 to add them.  Keeping
    this migration conditional makes both paths converge without duplicate
    DDL; the return value is recorded for a safe downgrade.
    """

    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_unique_constraints(table, schema=SCHEMA)
    if any(
        constraint.get("name") == name
        or constraint.get("column_names") == columns
        for constraint in existing
    ):
        return False
    op.create_unique_constraint(name, table, columns, schema=SCHEMA)
    return True


def _create_tables() -> tuple[bool, bool]:
    jsonb = postgresql.JSONB(astext_type=sa.Text())

    # Composite foreign keys below use these pairs as PostgreSQL reference
    # targets.  The component UUID/PK constraints alone cannot prove that a
    # document belongs to the snapshot notice or that a structure belongs to
    # the snapshot document version.
    document_version_scope_created = _ensure_unique_constraint(
        "document_version",
        "uq_document_version_notice_scope",
        ["notice_id", "id"],
    )
    document_structure_scope_created = _ensure_unique_constraint(
        "document_structure",
        "uq_document_structure_document_version_scope",
        ["document_version_id", "id"],
    )

    op.create_table(
        "prespec_overview_review",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("current_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'awaiting_document'"),
            nullable=False,
        ),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("notice_id", name="uq_prespec_overview_review_notice"),
        sa.UniqueConstraint("id", "notice_id", name="uq_prespec_overview_review_scope"),
        sa.CheckConstraint(
            f"status IN ({_REVIEW_STATUSES})",
            name="ck_prespec_overview_review_status",
        ),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('추진 검토','조건부 추진 검토','보류','검토 종료')",
            name="ck_prespec_overview_review_result",
        ),
        sa.CheckConstraint(
            "((status = 'completed' AND result IS NOT NULL AND completed_at IS NOT NULL) "
            "OR (status <> 'completed' AND result IS NULL AND completed_at IS NULL))",
            name="ck_prespec_overview_review_completion",
        ),
        sa.ForeignKeyConstraint(
            ["notice_id"],
            [f"{SCHEMA}.notice.id"],
            name="fk_prespec_overview_review_notice",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "prespec_overview_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("structure_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "cut_status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("strategy", sa.String(length=32), nullable=True),
        sa.Column("start_locator", jsonb, nullable=True),
        sa.Column("end_locator", jsonb, nullable=True),
        sa.Column("input_block_keys", jsonb, nullable=True),
        sa.Column("unknown_reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "review_id",
            "document_version_id",
            "structure_id",
            "source_sha256",
            "payload_sha256",
            name="uq_prespec_overview_snapshot_input",
        ),
        sa.UniqueConstraint(
            "review_id",
            "id",
            name="uq_prespec_overview_snapshot_review_scope",
        ),
        sa.CheckConstraint(
            "cut_status IN ('pending','ready','unknown','failed')",
            name="ck_prespec_overview_snapshot_cut_status",
        ),
        sa.CheckConstraint(
            "strategy IS NULL OR strategy IN ('toc_body_match','topic_heading')",
            name="ck_prespec_overview_snapshot_strategy",
        ),
        sa.CheckConstraint(
            "((cut_status = 'ready' AND strategy IS NOT NULL "
            "AND start_locator IS NOT NULL AND end_locator IS NOT NULL) "
            "OR (cut_status <> 'ready'))",
            name="ck_prespec_overview_snapshot_ready_inputs",
        ),
        sa.CheckConstraint(
            "((cut_status = 'unknown' AND unknown_reason_code IS NOT NULL "
            "AND length(trim(unknown_reason_code)) > 0) "
            "OR (cut_status <> 'unknown' AND unknown_reason_code IS NULL))",
            name="ck_prespec_overview_snapshot_unknown_reason",
        ),
        sa.CheckConstraint(
            "length(source_sha256) = 64 AND source_sha256 ~ '^[0-9a-f]{64}$' "
            "AND length(payload_sha256) = 64 AND payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_prespec_overview_snapshot_hashes",
        ),
        sa.CheckConstraint(
            "start_locator IS NULL OR jsonb_typeof(start_locator) = 'object'",
            name="ck_prespec_overview_snapshot_start_locator",
        ),
        sa.CheckConstraint(
            "end_locator IS NULL OR jsonb_typeof(end_locator) = 'object'",
            name="ck_prespec_overview_snapshot_end_locator",
        ),
        sa.CheckConstraint(
            "input_block_keys IS NULL OR jsonb_typeof(input_block_keys) = 'array'",
            name="ck_prespec_overview_snapshot_input_block_keys",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            [f"{SCHEMA}.prespec_overview_review.id"],
            name="fk_prespec_overview_snapshot_review",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_id", "notice_id"],
            [
                f"{SCHEMA}.prespec_overview_review.id",
                f"{SCHEMA}.prespec_overview_review.notice_id",
            ],
            name="fk_prespec_overview_snapshot_review_notice_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notice_id"],
            [f"{SCHEMA}.notice.id"],
            name="fk_prespec_overview_snapshot_notice",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            [f"{SCHEMA}.document_version.id"],
            name="fk_prespec_overview_snapshot_document_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notice_id", "document_version_id"],
            [
                f"{SCHEMA}.document_version.notice_id",
                f"{SCHEMA}.document_version.id",
            ],
            name="fk_prespec_overview_snapshot_document_notice_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["structure_id"],
            [f"{SCHEMA}.document_structure.id"],
            name="fk_prespec_overview_snapshot_structure",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "structure_id"],
            [
                f"{SCHEMA}.document_structure.document_version_id",
                f"{SCHEMA}.document_structure.id",
            ],
            name="fk_prespec_overview_snapshot_structure_document_scope",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "prespec_overview_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("reference_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deployable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider", sa.String(length=128), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("model_digest", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=128), nullable=True),
        sa.Column("result_jsonb", jsonb, nullable=True),
        sa.Column("result_sha256", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "snapshot_id", "sequence", name="uq_prespec_overview_attempt_sequence"
        ),
        sa.CheckConstraint(
            "sequence >= 1", name="ck_prespec_overview_attempt_sequence"
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_prespec_overview_attempt_status",
        ),
        sa.CheckConstraint(
            "(NOT reference_only) OR deployable IS FALSE",
            name="ck_prespec_overview_attempt_reference_boundary",
        ),
        sa.CheckConstraint(
            "((status = 'completed' AND result_jsonb IS NOT NULL AND completed_at IS NOT NULL) "
            "OR (status <> 'completed' AND result_jsonb IS NULL AND completed_at IS NULL))",
            name="ck_prespec_overview_attempt_completion",
        ),
        sa.CheckConstraint(
            "result_jsonb IS NULL OR jsonb_typeof(result_jsonb) = 'object'",
            name="ck_prespec_overview_attempt_result_object",
        ),
        sa.CheckConstraint(
            "result_sha256 IS NULL OR result_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_prespec_overview_attempt_result_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            [f"{SCHEMA}.prespec_overview_snapshot.id"],
            name="fk_prespec_overview_attempt_snapshot",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    op.create_foreign_key(
        "fk_prespec_overview_review_current_snapshot_scope",
        "prespec_overview_review",
        "prespec_overview_snapshot",
        ["id", "current_snapshot_id"],
        ["review_id", "id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_prespec_overview_snapshot_notice",
        "prespec_overview_snapshot",
        ["notice_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_prespec_overview_attempt_snapshot",
        "prespec_overview_attempt",
        ["snapshot_id", "created_at"],
        schema=SCHEMA,
    )
    return document_version_scope_created, document_structure_scope_created


def _create_append_only_guards() -> None:
    bind = op.get_bind()
    for table in ("prespec_overview_snapshot", "prespec_overview_attempt"):
        function = f"tf_{table}_append_only"
        trigger = f"tr_{table}_append_only"
        bind.exec_driver_sql(
            f"""
CREATE FUNCTION {SCHEMA}.{function}() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION '{table} is append-only'
        USING ERRCODE = 'check_violation';
END
$function$;
"""
        )
        bind.exec_driver_sql(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE "
            f"ON {SCHEMA}.{table} FOR EACH ROW "
            f"EXECUTE FUNCTION {SCHEMA}.{function}();"
        )


def _record_migration_marker(scope_constraints_created: tuple[bool, bool]) -> None:
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
            "occurred_at": "2026-01-01 00:00:09+00",
            "details": json.dumps(
                {
                    "migration_revision": revision,
                    "action": "upgrade",
                    "scope_constraints_created": {
                        "document_version": scope_constraints_created[0],
                        "document_structure": scope_constraints_created[1],
                    },
                },
                separators=(",", ":"),
            ),
        },
    )


def upgrade() -> None:
    scope_constraints_created = _create_tables()
    _create_append_only_guards()
    _record_migration_marker(scope_constraints_created)


def _assert_downgrade_safe() -> None:
    counts = op.get_bind().execute(
        sa.text(
            f"""
            SELECT
                (SELECT count(*) FROM {SCHEMA}.prespec_overview_attempt),
                (SELECT count(*) FROM {SCHEMA}.prespec_overview_snapshot),
                (SELECT count(*) FROM {SCHEMA}.prespec_overview_review)
            """
        )
    ).one()
    if any(counts):
        raise RuntimeError(
            "0012 downgrade refuses to discard pre-spec overview lineage; "
            "export or reconcile review rows before retrying"
        )


def _scope_constraints_created_by_migration() -> tuple[bool, bool]:
    """Read the upgrade marker before removing any shared base constraint."""

    raw_details = op.get_bind().execute(
        sa.text(
            f"SELECT details_json FROM {SCHEMA}.screening_audit_event "
            "WHERE event_id = :event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    ).scalar_one_or_none()
    if isinstance(raw_details, dict):
        details = raw_details
    else:
        try:
            details = json.loads(raw_details) if raw_details else {}
        except (TypeError, ValueError):
            details = {}
    if not isinstance(details, dict):
        return False, False
    created = details.get("scope_constraints_created", {})
    if not isinstance(created, dict):
        return False, False
    return bool(created.get("document_version")), bool(created.get("document_structure"))


def downgrade() -> None:
    _assert_downgrade_safe()
    scope_constraints_created = _scope_constraints_created_by_migration()
    op.drop_constraint(
        "fk_prespec_overview_review_current_snapshot_scope",
        table_name="prespec_overview_review",
        type_="foreignkey",
        schema=SCHEMA,
    )
    for table in ("prespec_overview_attempt", "prespec_overview_snapshot"):
        trigger = f"tr_{table}_append_only"
        function = f"tf_{table}_append_only"
        op.execute(sa.text(f"DROP TRIGGER {trigger} ON {SCHEMA}.{table}"))
        op.execute(sa.text(f"DROP FUNCTION {SCHEMA}.{function}()"))
    op.drop_index(
        "ix_prespec_overview_attempt_snapshot",
        table_name="prespec_overview_attempt",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_prespec_overview_snapshot_notice",
        table_name="prespec_overview_snapshot",
        schema=SCHEMA,
    )
    op.drop_table("prespec_overview_attempt", schema=SCHEMA)
    op.drop_table("prespec_overview_snapshot", schema=SCHEMA)
    op.drop_table("prespec_overview_review", schema=SCHEMA)
    if scope_constraints_created[1]:
        op.drop_constraint(
            "uq_document_structure_document_version_scope",
            table_name="document_structure",
            type_="unique",
            schema=SCHEMA,
        )
    if scope_constraints_created[0]:
        op.drop_constraint(
            "uq_document_version_notice_scope",
            table_name="document_version",
            type_="unique",
            schema=SCHEMA,
        )
    op.get_bind().execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
