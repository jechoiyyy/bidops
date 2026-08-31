"""Add the ADR-0035 pre-spec overview attempt/result lifecycle.

Revision ID: 0014_prespec_overview_attempt_result
Revises: 0013_document_integrity

The phase-1 attempt row remains the durable input/binding identity.  Phase 2
adds only lifecycle columns to it, stores validated payloads in a separate
immutable result row, and records each status transition in an immutable event
row.  No model provider is contacted by this migration.
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_prespec_overview_attempt_result"
down_revision = "0013_document_integrity"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-9e7b4c2d1f6840a3b5c6d7e8f9012345"


def _preflight_legacy_completion() -> None:
    """Do not guess a phase-1 result while installing phase-2 constraints."""

    rows = op.get_bind().execute(
        sa.text(
            f"""
            SELECT id::text, snapshot_id::text, status
            FROM {SCHEMA}.prespec_overview_attempt
            WHERE status = 'completed'
               OR result_jsonb IS NOT NULL
               OR result_sha256 IS NOT NULL
               OR (status = 'queued' AND (started_at IS NOT NULL OR completed_at IS NOT NULL))
               OR (status = 'running' AND (started_at IS NULL OR completed_at IS NOT NULL))
               OR (status IN ('failed','cancelled') AND completed_at IS NULL)
            ORDER BY id::text
            LIMIT 50
            """
        )
    ).all()
    if rows:
        detail = "; ".join(
            f"id={row.id} snapshot_id={row.snapshot_id} status={row.status}"
            for row in rows
        )
        raise RuntimeError(
            "0014 found phase-1 overview attempts incompatible with the phase-2 lifecycle; "
            "reconcile their status/result/timestamps without guessing, then retry: "
            + detail
        )


def _ensure_unique_constraint(table: str, name: str, columns: list[str]) -> bool:
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


def _create_attempt_columns() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.add_column(
        "prespec_overview_attempt",
        sa.Column("review_id", uuid, nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "prespec_overview_attempt",
        sa.Column("input_sha256", sa.String(length=64), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "prespec_overview_attempt",
        sa.Column("binding_digest", sa.String(length=64), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "prespec_overview_attempt",
        sa.Column("result_id", uuid, nullable=True),
        schema=SCHEMA,
    )
    _ensure_unique_constraint(
        "prespec_overview_attempt",
        "uq_prespec_overview_attempt_snapshot_scope",
        ["id", "snapshot_id"],
    )
    _ensure_unique_constraint(
        "prespec_overview_attempt",
        "uq_prespec_overview_attempt_review_scope",
        ["id", "review_id"],
    )


def _create_result_and_event_tables() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "prespec_overview_result",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("attempt_id", uuid, nullable=False),
        sa.Column("review_id", uuid, nullable=False),
        sa.Column("snapshot_id", uuid, nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("payload_jsonb", jsonb, nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("binding_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "validation_status",
            sa.String(length=16),
            server_default=sa.text("'passed'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("attempt_id", name="uq_prespec_overview_result_attempt"),
        sa.UniqueConstraint(
            "id", "attempt_id", name="uq_prespec_overview_result_attempt_scope"
        ),
        sa.CheckConstraint(
            "schema_version = 'bidops.prespec-overview-result.v1'",
            name="ck_prespec_overview_result_schema_version",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload_jsonb) = 'object'",
            name="ck_prespec_overview_result_payload_object",
        ),
        sa.CheckConstraint(
            "CASE WHEN jsonb_typeof(payload_jsonb -> 'evidence') = 'array' "
            "THEN jsonb_array_length(payload_jsonb -> 'evidence') >= 1 ELSE FALSE END",
            name="ck_prespec_overview_result_evidence_nonempty",
        ),
        sa.CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_prespec_overview_result_payload_sha256",
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_prespec_overview_result_source_sha256",
        ),
        sa.CheckConstraint(
            "binding_digest ~ '^[0-9a-f]{64}$'",
            name="ck_prespec_overview_result_binding_digest",
        ),
        sa.CheckConstraint(
            "validation_status = 'passed'",
            name="ck_prespec_overview_result_validation_status",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            [f"{SCHEMA}.prespec_overview_attempt.id"],
            name="fk_prespec_overview_result_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "snapshot_id"],
            [
                f"{SCHEMA}.prespec_overview_attempt.id",
                f"{SCHEMA}.prespec_overview_attempt.snapshot_id",
            ],
            name="fk_prespec_overview_result_attempt_snapshot_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "review_id"],
            [
                f"{SCHEMA}.prespec_overview_attempt.id",
                f"{SCHEMA}.prespec_overview_attempt.review_id",
            ],
            name="fk_prespec_overview_result_attempt_review_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_id", "snapshot_id"],
            [
                f"{SCHEMA}.prespec_overview_snapshot.review_id",
                f"{SCHEMA}.prespec_overview_snapshot.id",
            ],
            name="fk_prespec_overview_result_review_snapshot_scope",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "prespec_overview_attempt_event",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("attempt_id", uuid, nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=False),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "attempt_id", "event_sequence",
            name="uq_prespec_overview_attempt_event_sequence",
        ),
        sa.CheckConstraint(
            "event_sequence >= 1",
            name="ck_prespec_overview_event_sequence",
        ),
        sa.CheckConstraint(
            "from_status <> to_status AND ((from_status = 'queued' AND to_status IN ('running','failed','cancelled')) OR (from_status = 'running' AND to_status IN ('completed','failed','cancelled')))" ,
            name="ck_prespec_overview_event_transition",
        ),
        sa.CheckConstraint(
            "actor_kind IN ('worker','human','system') AND length(trim(actor_id)) > 0",
            name="ck_prespec_overview_event_actor",
        ),
        sa.CheckConstraint(
            "length(trim(reason_code)) > 0",
            name="ck_prespec_overview_event_reason",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            [f"{SCHEMA}.prespec_overview_attempt.id"],
            name="fk_prespec_overview_attempt_event_attempt",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )


def _replace_attempt_constraints() -> None:
    # 0012 installed a table-wide append-only trigger and an inline-result
    # completion check.  Phase 2 replaces both with lifecycle/ref checks.
    op.drop_constraint(
        "ck_prespec_overview_attempt_completion",
        table_name="prespec_overview_attempt",
        type_="check",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_overview_attempt_completion",
        "prespec_overview_attempt",
        "((status = 'queued' AND started_at IS NULL AND completed_at IS NULL AND result_id IS NULL) OR (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND result_id IS NULL) OR (status IN ('failed','cancelled') AND completed_at IS NOT NULL AND result_id IS NULL) OR (status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND result_id IS NOT NULL))",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_overview_attempt_completed_binding",
        "prespec_overview_attempt",
        "status <> 'completed' OR (reference_only IS FALSE AND deployable IS TRUE)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_overview_attempt_review_input",
        "prespec_overview_attempt",
        "review_id IS NULL OR input_sha256 IS NOT NULL",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_overview_attempt_input_sha256",
        "prespec_overview_attempt",
        "input_sha256 IS NULL OR input_sha256 ~ '^[0-9a-f]{64}$'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_overview_attempt_binding_digest",
        "prespec_overview_attempt",
        "binding_digest IS NULL OR binding_digest ~ '^[0-9a-f]{64}$'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_overview_attempt_binding_pair",
        "prespec_overview_attempt",
        "review_id IS NULL OR (binding_digest IS NOT NULL AND provider IS NOT NULL AND model_name IS NOT NULL AND model_digest IS NOT NULL AND prompt_version IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_overview_attempt_result_reference_status",
        "prespec_overview_attempt",
        "result_id IS NULL OR status = 'completed'",
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_prespec_overview_attempt_review_snapshot_scope",
        "prespec_overview_attempt",
        "prespec_overview_snapshot",
        ["review_id", "snapshot_id"],
        ["review_id", "id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )


def _drop_phase1_attempt_trigger() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        f"DROP TRIGGER IF EXISTS tr_prespec_overview_attempt_append_only ON {SCHEMA}.prespec_overview_attempt"
    )
    bind.exec_driver_sql(
        f"DROP FUNCTION IF EXISTS {SCHEMA}.tf_prespec_overview_attempt_append_only()"
    )


def _create_lifecycle_triggers() -> None:
    """Install the one database-owned lifecycle edge guard.

    CHECK constraints own the shape of lifecycle metadata, the service owns
    cross-table scope and review completion, and runtime column grants own
    immutable input/result/event lineage.  The database only needs to reject
    impossible status edges (including reopening a terminal attempt).
    """
    bind = op.get_bind()
    bind.exec_driver_sql(
        f"""
CREATE FUNCTION {SCHEMA}.tf_prespec_overview_attempt_transition() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
        RETURN NEW;
    END IF;
    IF (OLD.status, NEW.status) NOT IN (
        ('queued','running'), ('queued','failed'), ('queued','cancelled'),
        ('running','completed'), ('running','failed'), ('running','cancelled')
    ) THEN
        RAISE EXCEPTION 'invalid overview attempt status transition' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER tr_prespec_overview_attempt_transition
BEFORE UPDATE OF status ON {SCHEMA}.prespec_overview_attempt
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_prespec_overview_attempt_transition();
"""
    )


def _add_attempt_result_fk() -> None:
    op.create_foreign_key(
        "fk_prespec_overview_attempt_result",
        "prespec_overview_attempt",
        "prespec_overview_result",
        ["result_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
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
            "occurred_at": "2026-01-01 00:00:11+00",
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
        },
    )


def upgrade() -> None:
    _preflight_legacy_completion()
    _drop_phase1_attempt_trigger()
    _create_attempt_columns()
    _replace_attempt_constraints()
    _create_result_and_event_tables()
    _add_attempt_result_fk()
    _create_lifecycle_triggers()
    _record_migration_marker()


def _assert_downgrade_safe() -> None:
    bind = op.get_bind()
    result_count, event_count, attempt_count = bind.execute(
        sa.text(
            f"""
            SELECT
                (SELECT count(*) FROM {SCHEMA}.prespec_overview_result),
                (SELECT count(*) FROM {SCHEMA}.prespec_overview_attempt_event),
                (SELECT count(*) FROM {SCHEMA}.prespec_overview_attempt
                  WHERE review_id IS NOT NULL OR input_sha256 IS NOT NULL
                     OR binding_digest IS NOT NULL OR result_id IS NOT NULL)
            """
        )
    ).one()
    if any((result_count, event_count, attempt_count)):
        raise RuntimeError(
            "0014 downgrade refuses to discard overview result/event or phase-2 lineage rows; "
            "export or reconcile them before retrying"
        )


def _drop_trigger(name: str, table: str) -> None:
    op.get_bind().exec_driver_sql(
        f"DROP TRIGGER IF EXISTS {name} ON {SCHEMA}.{table}"
    )


def downgrade() -> None:
    _assert_downgrade_safe()
    bind = op.get_bind()
    for name, table in (
        ("tr_prespec_overview_attempt_transition", "prespec_overview_attempt"),
    ):
        _drop_trigger(name, table)
    for function in ("tf_prespec_overview_attempt_transition",):
        bind.exec_driver_sql(f"DROP FUNCTION IF EXISTS {SCHEMA}.{function}()")

    op.drop_constraint(
        "fk_prespec_overview_attempt_result",
        table_name="prespec_overview_attempt",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_table("prespec_overview_attempt_event", schema=SCHEMA)
    op.drop_table("prespec_overview_result", schema=SCHEMA)
    op.drop_constraint(
        "fk_prespec_overview_attempt_review_snapshot_scope",
        table_name="prespec_overview_attempt",
        type_="foreignkey",
        schema=SCHEMA,
    )
    for name in (
        "ck_prespec_overview_attempt_result_reference_status",
        "ck_prespec_overview_attempt_completed_binding",
        "ck_prespec_overview_attempt_binding_pair",
        "ck_prespec_overview_attempt_binding_digest",
        "ck_prespec_overview_attempt_input_sha256",
        "ck_prespec_overview_attempt_review_input",
        "ck_prespec_overview_attempt_completion",
    ):
        op.drop_constraint(
            name,
            table_name="prespec_overview_attempt",
            type_="check",
            schema=SCHEMA,
        )
    op.create_check_constraint(
        "ck_prespec_overview_attempt_completion",
        "prespec_overview_attempt",
        "((status = 'completed' AND result_jsonb IS NOT NULL AND completed_at IS NOT NULL) OR (status <> 'completed' AND result_jsonb IS NULL AND completed_at IS NULL))",
        schema=SCHEMA,
    )
    for name in (
        "uq_prespec_overview_attempt_review_scope",
        "uq_prespec_overview_attempt_snapshot_scope",
    ):
        op.drop_constraint(
            name,
            table_name="prespec_overview_attempt",
            type_="unique",
            schema=SCHEMA,
        )
    op.drop_column("prespec_overview_attempt", "result_id", schema=SCHEMA)
    op.drop_column("prespec_overview_attempt", "binding_digest", schema=SCHEMA)
    op.drop_column("prespec_overview_attempt", "input_sha256", schema=SCHEMA)
    op.drop_column("prespec_overview_attempt", "review_id", schema=SCHEMA)

    # Restore the phase-1 attempt guard after removing phase-2 lifecycle.
    bind.exec_driver_sql(
        f"""
CREATE FUNCTION {SCHEMA}.tf_prespec_overview_attempt_append_only() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION 'prespec_overview_attempt is append-only'
        USING ERRCODE = 'check_violation';
END
$function$;
CREATE TRIGGER tr_prespec_overview_attempt_append_only
BEFORE UPDATE OR DELETE ON {SCHEMA}.prespec_overview_attempt
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_prespec_overview_attempt_append_only();
"""
    )
    bind.execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
