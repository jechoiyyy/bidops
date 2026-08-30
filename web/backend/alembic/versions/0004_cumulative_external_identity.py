"""Make notices cumulative and add observation-backed order plans.

Revision ID: 0004_cumulative_external_identity
Revises: 0003_screening_runtime_pg

The pre-0004 schema made ``run`` the owner of a notice.  This revision first
materializes one observation for every existing notice, then removes that
ownership column.  Duplicate external keys are rejected before any DDL is
committed: choosing one of two existing rows would silently discard data.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_cumulative_external_identity"
down_revision = "0003_screening_runtime_pg"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-4f9f8e2c1a0d4b7c9e6f1234567890ab"


def _foreign_keys(table: str, column: str) -> list[str]:
    """Find generated PostgreSQL FK names without assuming SQLAlchemy naming."""

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT constraint_name
            FROM information_schema.key_column_usage
            WHERE table_schema = :schema
              AND table_name = :table_name
              AND column_name = :column_name
              AND constraint_name IN (
                  SELECT constraint_name
                  FROM information_schema.table_constraints
                  WHERE table_schema = :schema
                    AND table_name = :table_name
                    AND constraint_type = 'FOREIGN KEY'
              )
            """
        ),
        {"schema": SCHEMA, "table_name": table, "column_name": column},
    )
    return [row[0] for row in rows]


def _drop_foreign_keys(table: str, column: str) -> None:
    for name in _foreign_keys(table, column):
        op.drop_constraint(name, table, type_="foreignkey", schema=SCHEMA)


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.scalar(
            sa.text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = :schema
                  AND table_name = :table_name
                  AND column_name = :column_name
                """
            ),
            {"schema": SCHEMA, "table_name": table, "column_name": column},
        )
    )


def _constraint_exists(table: str, constraint: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.scalar(
            sa.text(
                """
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = :schema
                  AND t.relname = :table_name
                  AND c.conname = :constraint_name
                """
            ),
            {"schema": SCHEMA, "table_name": table, "constraint_name": constraint},
        )
    )


def _index_exists(index: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.scalar(
            sa.text(
                """
                SELECT 1
                FROM pg_class i
                JOIN pg_namespace n ON n.oid = i.relnamespace
                WHERE n.nspname = :schema
                  AND i.relname = :index_name
                  AND i.relkind IN ('i', 'I')
                """
            ),
            {"schema": SCHEMA, "index_name": index},
        )
    )


def _drop_legacy_notice_identity_guard() -> None:
    """Remove the 0003 trigger whose body reads the retiring run_id column."""

    bind = op.get_bind()
    for event_name in (
        "screening_execution_notice_identity_insert",
        "screening_execution_notice_identity_update",
    ):
        bind.exec_driver_sql(
            f"DROP TRIGGER IF EXISTS {event_name} ON {SCHEMA}.screening_execution"
        )
        bind.exec_driver_sql(
            f"DROP FUNCTION IF EXISTS {SCHEMA}.tf_{event_name}()"
        )


def _create_observation_notice_identity_guards() -> None:
    """Recreate the single-notice guard against the observation relation."""

    bind = op.get_bind()
    condition = (
        f"NEW.scope = 'single_notice' AND ("
        f"(SELECT notice_key FROM {SCHEMA}.notice WHERE id = NEW.notice_pk) "
        f"IS DISTINCT FROM NEW.notice_id OR NOT EXISTS ("
        f"SELECT 1 FROM {SCHEMA}.notice_observation observation "
        f"WHERE observation.notice_id = NEW.notice_pk "
        f"AND observation.run_id = NEW.source_run_id))"
    )
    for event_name, event_spec in (
        (
            "screening_execution_notice_identity_insert",
            "BEFORE INSERT",
        ),
        (
            "screening_execution_notice_identity_update",
            "BEFORE UPDATE OF scope, notice_pk, notice_id, source_run_id",
        ),
    ):
        bind.exec_driver_sql(
            f"""
CREATE FUNCTION {SCHEMA}.tf_{event_name}() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    IF {condition} THEN
        RAISE EXCEPTION 'single notice identity mismatch'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$function$;
"""
        )
        bind.exec_driver_sql(
            f"CREATE TRIGGER {event_name} {event_spec} ON {SCHEMA}.screening_execution "
            f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_{event_name}();"
        )


def _assert_upgrade_safe() -> None:
    bind = op.get_bind()
    if _column_exists("notice", "run_id"):
        duplicate = bind.scalar(
            sa.text(
                """
                SELECT notice_key
                FROM bidops.notice
                GROUP BY notice_key
                HAVING count(*) > 1
                LIMIT 1
                """
            )
        )
        if duplicate is not None:
            raise RuntimeError(
                "0004 refuses to merge duplicate notice_key rows; "
                "export and reconcile the non-empty database before retrying"
            )
        missing_run = bind.scalar(
            sa.text(
                """
                SELECT 1
                FROM bidops.notice AS n
                LEFT JOIN bidops.run AS r ON r.id = n.run_id
                WHERE r.id IS NULL
                LIMIT 1
                """
            )
        )
        if missing_run is not None:
            raise RuntimeError(
                "0004 refuses to remove notice.run_id while an existing notice "
                "does not have a valid run observation"
            )
    elif bind.scalar(sa.text("SELECT count(*) FROM bidops.notice")):
        # 0001 builds from the current declarative metadata.  A newly-created
        # pre-0004 database can therefore already lack run_id, but it has no
        # trustworthy timestamp from which to invent observations for rows
        # inserted before this migration.
        raise RuntimeError(
            "0004 refuses a non-empty schema without notice.run_id; "
            "the observation timestamp cannot be reconstructed safely"
        )
    duplicate_review = bind.scalar(
        sa.text(
            """
            SELECT notice_id
            FROM bidops.review
            GROUP BY notice_id
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    )
    if duplicate_review is not None:
        raise RuntimeError(
            "0004 refuses to merge duplicate review rows for one notice; "
            "export and reconcile the non-empty database before retrying"
        )


def _create_observation_tables() -> None:
    jsonb = postgresql.JSONB()
    op.create_table(
        "notice_observation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "notice_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.notice.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(length=160),
            sa.ForeignKey(f"{SCHEMA}.run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "changed_fields_json",
            jsonb,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "notice_id", "run_id", name="uq_notice_observation_notice_run"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_notice_observation_run",
        "notice_observation",
        ["run_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_notice_observation_notice",
        "notice_observation",
        ["notice_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "order_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_plan_unty_no", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("agency_code", sa.String(length=64), nullable=True),
        sa.Column("agency_name", sa.String(length=255), nullable=True),
        sa.Column("supervising_agency_name", sa.String(length=255), nullable=True),
        sa.Column("business_division", sa.String(length=128), nullable=True),
        sa.Column("business_division_code", sa.String(length=64), nullable=True),
        sa.Column("service_type", sa.String(length=128), nullable=True),
        sa.Column("service_type_code", sa.String(length=64), nullable=True),
        sa.Column("budget_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("contract_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("planned_order_year", sa.String(length=4), nullable=True),
        sa.Column("planned_order_month", sa.String(length=7), nullable=True),
        sa.Column("procurement_method", sa.String(length=128), nullable=True),
        sa.Column("contract_method", sa.String(length=128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bid_ntice_no_list", sa.Text(), nullable=True),
        sa.Column("notice_posted", sa.String(length=8), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("unknown_fields_json", jsonb, nullable=True),
        sa.Column("raw_source", jsonb, nullable=True),
        sa.UniqueConstraint("order_plan_unty_no", name="uq_order_plan_unty_no"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_order_plan_published_at", "order_plan", ["published_at"], schema=SCHEMA
    )

    op.create_table(
        "order_plan_observation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_plan_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.order_plan.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(length=160),
            sa.ForeignKey(f"{SCHEMA}.run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "changed_fields_json",
            jsonb,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "order_plan_id", "run_id", name="uq_order_plan_observation_plan_run"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_order_plan_observation_run",
        "order_plan_observation",
        ["run_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_order_plan_observation_plan",
        "order_plan_observation",
        ["order_plan_id"],
        schema=SCHEMA,
    )


def upgrade() -> None:
    _assert_upgrade_safe()
    _create_observation_tables()

    # ``generated_at`` is the immutable timestamp of the old run snapshot and
    # is the only trustworthy observation timestamp available during upgrade.
    if _column_exists("notice", "run_id"):
        op.execute(
            sa.text(
                """
                INSERT INTO bidops.notice_observation
                    (notice_id, run_id, observed_at, changed_fields_json)
                SELECT n.id, n.run_id, r.generated_at, '[]'::jsonb
                FROM bidops.notice AS n
                JOIN bidops.run AS r ON r.id = n.run_id
                """
            )
        )

    _drop_foreign_keys("review", "run_id")
    if _constraint_exists("review", "uq_review_notice_run"):
        op.drop_constraint("uq_review_notice_run", "review", type_="unique", schema=SCHEMA)
    op.alter_column("review", "run_id", nullable=True, schema=SCHEMA)
    op.create_foreign_key(
        "fk_review_run",
        "review",
        "run",
        ["run_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="SET NULL",
    )
    if not _constraint_exists("review", "uq_review_notice"):
        op.create_unique_constraint(
            "uq_review_notice", "review", ["notice_id"], schema=SCHEMA
        )

    _drop_legacy_notice_identity_guard()
    if _column_exists("notice", "run_id"):
        if _index_exists("ix_notice_run_collection_sample"):
            op.drop_index("ix_notice_run_collection_sample", table_name="notice", schema=SCHEMA)
        _drop_foreign_keys("notice", "run_id")
        if _constraint_exists("notice", "uq_notice_run_key"):
            op.drop_constraint("uq_notice_run_key", "notice", type_="unique", schema=SCHEMA)
        op.drop_column("notice", "run_id", schema=SCHEMA)
    if not _constraint_exists("notice", "uq_notice_key"):
        op.create_unique_constraint("uq_notice_key", "notice", ["notice_key"], schema=SCHEMA)
    if not _index_exists("ix_notice_collection_sample"):
        op.create_index(
            "ix_notice_collection_sample",
            "notice",
            ["collection_bucket", "sample_role"],
            schema=SCHEMA,
        )
    _create_observation_notice_identity_guards()
    # Migration audit events are append-only.  Keep 0003's marker intact and
    # add a distinct deterministic marker for this revision.
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO bidops.screening_audit_event
                (event_id, event_type, actor, target_type, target_id,
                 occurred_at, details_json)
            VALUES (:event_id, 'db.migration', 'system:migration', 'database',
                    :revision, CAST(:occurred_at AS timestamptz),
                    CAST(:details AS json))
            ON CONFLICT (event_id) DO NOTHING
            """
        ),
        {
            "revision": revision,
            "details": '{"migration_revision":"0004_cumulative_external_identity","action":"upgrade"}',
            "event_id": _MIGRATION_EVENT_ID,
            "occurred_at": "2026-01-01 00:00:01+00",
        },
    )


def _assert_downgrade_safe() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT count(*) FROM bidops.order_plan")):
        raise RuntimeError("0004 downgrade refuses to discard order_plan rows")
    if bind.scalar(sa.text("SELECT count(*) FROM bidops.order_plan_observation")):
        raise RuntimeError("0004 downgrade refuses to discard order_plan_observation rows")
    if bind.scalar(
        sa.text(
            "SELECT 1 FROM bidops.notice AS n "
            "LEFT JOIN bidops.notice_observation AS o ON o.notice_id = n.id "
            "GROUP BY n.id HAVING count(o.id) <> 1 LIMIT 1"
        )
    ) is not None:
        raise RuntimeError(
            "0004 downgrade requires exactly one observation per notice; "
            "historical observations would be discarded"
        )
    if bind.scalar(sa.text("SELECT 1 FROM bidops.review WHERE run_id IS NULL LIMIT 1")) is not None:
        raise RuntimeError("0004 downgrade refuses to turn a nullable review.run_id into NOT NULL")


def downgrade() -> None:
    _assert_downgrade_safe()

    _drop_legacy_notice_identity_guard()
    _drop_foreign_keys("review", "run_id")
    op.drop_constraint("uq_review_notice", "review", type_="unique", schema=SCHEMA)
    op.alter_column("review", "run_id", nullable=False, schema=SCHEMA)
    op.create_foreign_key(
        "review_run_id_fkey",
        "review",
        "run",
        ["run_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )

    op.drop_constraint("uq_notice_key", "notice", type_="unique", schema=SCHEMA)
    op.drop_index("ix_notice_collection_sample", table_name="notice", schema=SCHEMA)
    op.add_column(
        "notice",
        sa.Column("run_id", sa.String(length=160), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        sa.text(
            """
            UPDATE bidops.notice AS n
            SET run_id = o.run_id
            FROM bidops.notice_observation AS o
            WHERE o.notice_id = n.id
            """
        )
    )
    op.alter_column("notice", "run_id", nullable=False, schema=SCHEMA)
    op.create_foreign_key(
        "notice_run_id_fkey",
        "notice",
        "run",
        ["run_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_notice_run_key", "notice", ["run_id", "notice_key"], schema=SCHEMA
    )
    op.create_index(
        "ix_notice_run_collection_sample",
        "notice",
        ["run_id", "collection_bucket", "sample_role"],
        schema=SCHEMA,
    )

    bind = op.get_bind()
    legacy_condition = (
        f"NEW.scope = 'single_notice' AND ("
        f"(SELECT notice_key FROM {SCHEMA}.notice WHERE id = NEW.notice_pk) "
        f"IS DISTINCT FROM NEW.notice_id OR (SELECT run_id FROM {SCHEMA}.notice "
        f"WHERE id = NEW.notice_pk) IS DISTINCT FROM NEW.source_run_id)"
    )
    for event_name, event_spec in (
        (
            "screening_execution_notice_identity_insert",
            "BEFORE INSERT",
        ),
        (
            "screening_execution_notice_identity_update",
            "BEFORE UPDATE OF scope, notice_pk, notice_id, source_run_id",
        ),
    ):
        bind.exec_driver_sql(
            f"""
CREATE FUNCTION {SCHEMA}.tf_{event_name}() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    IF {legacy_condition} THEN
        RAISE EXCEPTION 'single notice identity mismatch'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$function$;
"""
        )
        bind.exec_driver_sql(
            f"CREATE TRIGGER {event_name} {event_spec} ON {SCHEMA}.screening_execution "
            f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_{event_name}();"
        )

    # Only remove this revision's marker; the previous revision's append-only
    # event remains as the audit record for the downgraded head.
    bind.execute(
        sa.text(
            "DELETE FROM bidops.screening_audit_event WHERE event_id = :event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )

    op.drop_table("order_plan_observation", schema=SCHEMA)
    op.drop_table("order_plan", schema=SCHEMA)
    op.drop_table("notice_observation", schema=SCHEMA)
