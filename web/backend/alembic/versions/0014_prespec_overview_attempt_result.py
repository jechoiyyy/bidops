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


def _create_attempt_columns() -> tuple[bool, bool, bool]:
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
    return (
        _ensure_unique_constraint(
            "prespec_overview_attempt",
            "uq_prespec_overview_attempt_snapshot_scope",
            ["id", "snapshot_id"],
        ),
        _ensure_unique_constraint(
            "prespec_overview_attempt",
            "uq_prespec_overview_attempt_review_scope",
            ["id", "review_id"],
        ),
        True,
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
    bind = op.get_bind()
    bind.exec_driver_sql(
        f"""
CREATE FUNCTION {SCHEMA}.tf_prespec_overview_attempt_event_validate() RETURNS trigger
LANGUAGE plpgsql AS $function$
DECLARE
    current_status text;
    expected_sequence integer;
BEGIN
    SELECT status INTO current_status
      FROM {SCHEMA}.prespec_overview_attempt
     WHERE id = NEW.attempt_id
     FOR UPDATE;
    IF current_status IS NULL THEN
        RAISE EXCEPTION 'overview attempt event has no attempt' USING ERRCODE = 'check_violation';
    END IF;
    IF current_status <> NEW.from_status THEN
        RAISE EXCEPTION 'overview attempt event source status mismatch' USING ERRCODE = 'check_violation';
    END IF;
    SELECT COALESCE(MAX(event_sequence), 0) + 1 INTO expected_sequence
      FROM {SCHEMA}.prespec_overview_attempt_event
     WHERE attempt_id = NEW.attempt_id;
    IF NEW.event_sequence <> expected_sequence THEN
        RAISE EXCEPTION 'overview attempt event sequence is not append-only' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$function$;
"""
    )
    bind.exec_driver_sql(
        f"""
CREATE FUNCTION {SCHEMA}.tf_prespec_overview_attempt_lifecycle() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.review_id IS DISTINCT FROM OLD.review_id
       OR NEW.snapshot_id IS DISTINCT FROM OLD.snapshot_id
       OR NEW.sequence IS DISTINCT FROM OLD.sequence
       OR NEW.reference_only IS DISTINCT FROM OLD.reference_only
       OR NEW.deployable IS DISTINCT FROM OLD.deployable
       OR NEW.input_sha256 IS DISTINCT FROM OLD.input_sha256
       OR NEW.provider IS DISTINCT FROM OLD.provider
       OR NEW.model_name IS DISTINCT FROM OLD.model_name
       OR NEW.model_digest IS DISTINCT FROM OLD.model_digest
       OR NEW.prompt_version IS DISTINCT FROM OLD.prompt_version
       OR NEW.binding_digest IS DISTINCT FROM OLD.binding_digest
       OR NEW.result_jsonb IS DISTINCT FROM OLD.result_jsonb
       OR NEW.result_sha256 IS DISTINCT FROM OLD.result_sha256
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'overview attempt input lineage is immutable' USING ERRCODE = 'check_violation';
    END IF;

    IF (OLD.status, NEW.status) NOT IN (
        ('queued','running'), ('queued','failed'), ('queued','cancelled'),
        ('running','completed'), ('running','failed'), ('running','cancelled')
    ) THEN
        RAISE EXCEPTION 'invalid overview attempt status transition' USING ERRCODE = 'check_violation';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM {SCHEMA}.prespec_overview_attempt_event AS event_row
         WHERE event_row.attempt_id = OLD.id
           AND event_row.event_sequence = (
               SELECT MAX(last_event.event_sequence)
                 FROM {SCHEMA}.prespec_overview_attempt_event AS last_event
                WHERE last_event.attempt_id = OLD.id
           )
           AND event_row.from_status = OLD.status
           AND event_row.to_status = NEW.status
    ) THEN
        RAISE EXCEPTION 'overview attempt transition requires an audit event' USING ERRCODE = 'check_violation';
    END IF;

    IF NEW.status = 'running' THEN
        IF NEW.started_at IS NULL OR NEW.completed_at IS NOT NULL OR NEW.result_id IS NOT NULL THEN
            RAISE EXCEPTION 'running overview attempt timestamps are invalid' USING ERRCODE = 'check_violation';
        END IF;
    ELSIF NEW.status = 'completed' THEN
        IF OLD.started_at IS NULL OR NEW.started_at IS DISTINCT FROM OLD.started_at
           OR NEW.completed_at IS NULL OR NEW.result_id IS NULL THEN
            RAISE EXCEPTION 'completed overview attempt requires immutable start and result' USING ERRCODE = 'check_violation';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM {SCHEMA}.prespec_overview_result
             WHERE id = NEW.result_id AND attempt_id = OLD.id
        ) THEN
            RAISE EXCEPTION 'completed overview attempt result reference is invalid' USING ERRCODE = 'check_violation';
        END IF;
    ELSE
        IF NEW.completed_at IS NULL OR NEW.result_id IS NOT NULL THEN
            RAISE EXCEPTION 'failed or cancelled overview attempt metadata is invalid' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'queued' AND NEW.started_at IS NOT NULL THEN
            RAISE EXCEPTION 'queued overview attempt cannot finish with a start time' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'running' AND (OLD.started_at IS NULL OR NEW.started_at IS DISTINCT FROM OLD.started_at) THEN
            RAISE EXCEPTION 'running overview attempt start time is immutable' USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
"""
    )
    bind.exec_driver_sql(
        f"""
CREATE FUNCTION {SCHEMA}.tf_prespec_overview_result_scope() RETURNS trigger
LANGUAGE plpgsql AS $function$
DECLARE
    attempt_row record;
    snapshot_row record;
BEGIN
    SELECT id, review_id, snapshot_id, binding_digest, status
      INTO attempt_row
      FROM {SCHEMA}.prespec_overview_attempt
     WHERE id = NEW.attempt_id;
    IF attempt_row.id IS NULL OR attempt_row.review_id IS NULL
       OR attempt_row.status <> 'running'
       OR attempt_row.review_id IS DISTINCT FROM NEW.review_id
       OR attempt_row.snapshot_id IS DISTINCT FROM NEW.snapshot_id
       OR attempt_row.binding_digest IS DISTINCT FROM NEW.binding_digest THEN
        RAISE EXCEPTION 'overview result attempt scope mismatch' USING ERRCODE = 'check_violation';
    END IF;
    SELECT review_id, source_sha256
      INTO snapshot_row
      FROM {SCHEMA}.prespec_overview_snapshot
     WHERE id = NEW.snapshot_id;
    IF snapshot_row.review_id IS NULL
       OR snapshot_row.review_id IS DISTINCT FROM NEW.review_id
       OR snapshot_row.source_sha256 IS DISTINCT FROM NEW.source_sha256 THEN
        RAISE EXCEPTION 'overview result snapshot scope mismatch' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$function$;
"""
    )
    bind.exec_driver_sql(
        f"""
CREATE FUNCTION {SCHEMA}.tf_prespec_overview_append_only() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION 'prespec overview lifecycle rows are append-only'
        USING ERRCODE = 'check_violation';
END
$function$;
"""
    )
    bind.exec_driver_sql(
        f"""
CREATE TRIGGER tr_prespec_overview_attempt_event_validate
BEFORE INSERT ON {SCHEMA}.prespec_overview_attempt_event
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_prespec_overview_attempt_event_validate();
CREATE TRIGGER tr_prespec_overview_attempt_lifecycle
BEFORE UPDATE ON {SCHEMA}.prespec_overview_attempt
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_prespec_overview_attempt_lifecycle();
CREATE TRIGGER tr_prespec_overview_attempt_delete
BEFORE DELETE ON {SCHEMA}.prespec_overview_attempt
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_prespec_overview_append_only();
CREATE TRIGGER tr_prespec_overview_result_scope
BEFORE INSERT ON {SCHEMA}.prespec_overview_result
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_prespec_overview_result_scope();
CREATE TRIGGER tr_prespec_overview_result_append_only
BEFORE UPDATE OR DELETE ON {SCHEMA}.prespec_overview_result
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_prespec_overview_append_only();
CREATE TRIGGER tr_prespec_overview_attempt_event_append_only
BEFORE UPDATE OR DELETE ON {SCHEMA}.prespec_overview_attempt_event
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_prespec_overview_append_only();
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
        ("tr_prespec_overview_attempt_event_validate", "prespec_overview_attempt_event"),
        ("tr_prespec_overview_attempt_lifecycle", "prespec_overview_attempt"),
        ("tr_prespec_overview_attempt_delete", "prespec_overview_attempt"),
        ("tr_prespec_overview_result_scope", "prespec_overview_result"),
        ("tr_prespec_overview_result_append_only", "prespec_overview_result"),
        ("tr_prespec_overview_attempt_event_append_only", "prespec_overview_attempt_event"),
    ):
        _drop_trigger(name, table)
    for function in (
        "tf_prespec_overview_attempt_event_validate",
        "tf_prespec_overview_attempt_lifecycle",
        "tf_prespec_overview_result_scope",
        "tf_prespec_overview_append_only",
    ):
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
