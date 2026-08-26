"""Freeze stage-aware generation budgets and bind them to executions.

The migration deliberately backfills every existing row with one canonical
legacy config (all stages 2048, context 16384, think/stream false).  New
executions may use the synthesis-specific 4096 budget, but neither an input
artifact nor a gate can be changed after it has been queued.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_generation_config_binding"
down_revision = "0004_migration_audit"
branch_labels = None
depends_on = None

_DIGEST = "f5005da40315a4d24edba05b9394e71dba6c1c3c5790c84e5cc43673215134aa"
_EVENT_ID = "audit-6c2e6a9b3c9c4b3e8e3e9adf66f8c905"
_DETAILS = '{"migration_revision":"0005_generation_config_binding","action":"upgrade"}'
_JSON = (
    '{"num_ctx":16384,"num_predict":{"counterargument":2048,"perspective":2048,'
    '"synthesis":2048},"schema_version":"bidops.generation-config.v1",'
    '"stream":false,"think":false}'
)


def _json_default() -> sa.TextClause:
    # SQLite only permits a constant expression while adding a NOT NULL
    # column to a table that already has rows.  A JSON text literal is still
    # valid JSON for SQLite's JSON affinity; the explicit UPDATE below writes
    # the same canonical value to every pre-existing row.
    return sa.text("'" + _JSON.replace("'", "''") + "'")


def _add(table: str, name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    if name not in {item["name"] for item in sa.inspect(bind).get_columns(table)}:
        op.add_column(table, column)


def upgrade() -> None:
    _add("screening_execution", "generation_config_json", sa.Column("generation_config_json", sa.JSON(), nullable=False, server_default=_json_default()))
    _add("screening_execution", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=False, server_default=_DIGEST))
    _add("screening_attempt", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=True))
    _add("screening_attempt", "num_ctx", sa.Column("num_ctx", sa.Integer(), nullable=True))
    _add("screening_attempt", "num_predict", sa.Column("num_predict", sa.Integer(), nullable=True))
    _add("quality_gate", "generation_config_json", sa.Column("generation_config_json", sa.JSON(), nullable=False, server_default=_json_default()))
    _add("quality_gate", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=False, server_default=_DIGEST))
    _add("quality_gate_evaluation", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=False, server_default=_DIGEST))
    _add("schedule_execution", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=True))
    _add("always_on_state", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=True))

    # Explicit updates make the backfill deterministic even on SQLite builds
    # that ignore a column server default during ALTER TABLE.
    for table in ("screening_execution", "quality_gate"):
        op.get_bind().execute(sa.text(f"UPDATE {table} SET generation_config_json=json(:config), generation_config_digest=:digest"), {"config": _JSON, "digest": _DIGEST})
    op.get_bind().execute(sa.text("UPDATE quality_gate_evaluation SET generation_config_digest=:digest"), {"digest": _DIGEST})
    op.get_bind().execute(sa.text("UPDATE screening_attempt SET generation_config_digest=:digest, num_ctx=16384, num_predict=2048"), {"digest": _DIGEST})

    # Config is frozen at enqueue.  State/progress columns remain mutable by
    # the worker; only generation identity is guarded here.
    op.execute("CREATE TRIGGER screening_execution_generation_config_immutable BEFORE UPDATE OF generation_config_json, generation_config_digest ON screening_execution BEGIN SELECT RAISE(ABORT, 'screening execution generation config is immutable'); END")
    op.execute("CREATE TRIGGER screening_execution_generation_shape_insert BEFORE INSERT ON screening_execution WHEN json_valid(NEW.generation_config_json) = 0 OR json_type(NEW.generation_config_json) <> 'object' OR length(NEW.generation_config_digest) <> 64 OR NEW.generation_config_digest GLOB '*[^0-9a-f]*' BEGIN SELECT RAISE(ABORT, 'screening execution generation config is invalid'); END")
    op.execute("CREATE TRIGGER quality_gate_generation_config_immutable BEFORE UPDATE OF generation_config_json, generation_config_digest ON quality_gate BEGIN SELECT RAISE(ABORT, 'quality gate generation config is immutable'); END")
    op.execute("CREATE TRIGGER quality_gate_generation_shape_insert BEFORE INSERT ON quality_gate WHEN json_valid(NEW.generation_config_json) = 0 OR json_type(NEW.generation_config_json) <> 'object' OR length(NEW.generation_config_digest) <> 64 OR NEW.generation_config_digest GLOB '*[^0-9a-f]*' BEGIN SELECT RAISE(ABORT, 'quality gate generation config is invalid'); END")
    op.execute("CREATE TRIGGER quality_gate_generation_binding_insert BEFORE INSERT ON quality_gate WHEN NOT EXISTS (SELECT 1 FROM screening_execution a JOIN screening_execution b ON a.execution_id=NEW.pass_a_execution_id AND b.execution_id=NEW.pass_b_execution_id WHERE a.generation_config_digest=NEW.generation_config_digest AND b.generation_config_digest=NEW.generation_config_digest AND a.generation_config_json=b.generation_config_json AND a.generation_config_json=NEW.generation_config_json) BEGIN SELECT RAISE(ABORT, 'quality gate generation config mismatch'); END")
    op.execute("CREATE TRIGGER quality_gate_generation_binding_update BEFORE UPDATE OF pass_a_execution_id, pass_b_execution_id, generation_config_json, generation_config_digest ON quality_gate WHEN NOT EXISTS (SELECT 1 FROM screening_execution a JOIN screening_execution b ON a.execution_id=NEW.pass_a_execution_id AND b.execution_id=NEW.pass_b_execution_id WHERE a.generation_config_digest=NEW.generation_config_digest AND b.generation_config_digest=NEW.generation_config_digest AND a.generation_config_json=b.generation_config_json AND a.generation_config_json=NEW.generation_config_json) BEGIN SELECT RAISE(ABORT, 'quality gate generation config mismatch'); END")
    op.execute("CREATE TRIGGER quality_gate_evaluation_generation_binding BEFORE INSERT ON quality_gate_evaluation WHEN (SELECT generation_config_digest FROM quality_gate WHERE gate_id=NEW.gate_id) IS NULL OR NEW.generation_config_digest <> (SELECT generation_config_digest FROM quality_gate WHERE gate_id=NEW.gate_id) BEGIN SELECT RAISE(ABORT, 'quality gate evaluation generation config mismatch'); END")
    op.execute("CREATE TRIGGER quality_gate_evaluation_generation_binding_update BEFORE UPDATE OF gate_id, generation_config_digest ON quality_gate_evaluation WHEN (SELECT generation_config_digest FROM quality_gate WHERE gate_id=NEW.gate_id) IS NULL OR NEW.generation_config_digest <> (SELECT generation_config_digest FROM quality_gate WHERE gate_id=NEW.gate_id) BEGIN SELECT RAISE(ABORT, 'quality gate evaluation generation config mismatch'); END")
    op.get_bind().execute(sa.text(
        "INSERT OR IGNORE INTO audit_event (event_id, event_type, actor, target_type, target_id, occurred_at, details_json) "
        "VALUES (:event_id, 'db.migration', 'system:migration', 'database', '0005_generation_config_binding', '2026-01-01 00:00:01', :details)"
    ), {"event_id": _EVENT_ID, "details": _DETAILS})


def downgrade() -> None:
    for name in (
        "quality_gate_evaluation_generation_binding",
        "quality_gate_generation_binding_update",
        "quality_gate_generation_binding_insert",
        "quality_gate_generation_config_immutable",
        "quality_gate_generation_shape_insert",
        "screening_execution_generation_shape_insert",
        "screening_execution_generation_config_immutable",
        "quality_gate_evaluation_generation_binding_update",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    for table, name in (
        ("always_on_state", "generation_config_digest"),
        ("schedule_execution", "generation_config_digest"),
        ("quality_gate_evaluation", "generation_config_digest"),
        ("quality_gate", "generation_config_digest"),
        ("quality_gate", "generation_config_json"),
        ("screening_attempt", "num_predict"),
        ("screening_attempt", "num_ctx"),
        ("screening_attempt", "generation_config_digest"),
        ("screening_execution", "generation_config_digest"),
        ("screening_execution", "generation_config_json"),
    ):
        bind = op.get_bind()
        if name in {item["name"] for item in sa.inspect(bind).get_columns(table)}:
            op.drop_column(table, name)
    op.get_bind().execute(sa.text(
        "DELETE FROM audit_event WHERE event_id=:event_id AND event_type='db.migration' AND actor='system:migration' AND target_id='0005_generation_config_binding'"
    ), {"event_id": _EVENT_ID})
