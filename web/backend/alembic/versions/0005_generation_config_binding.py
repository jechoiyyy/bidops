"""Bind stage-aware generation configuration to durable runtime rows.

The migration is retry-safe on SQLite, where DDL can survive a failed
Alembic transaction. Existing rows use the deterministic legacy (all-2048)
configuration; column defaults retained by the final schema use the current
4096 synthesis configuration for new rows.
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa

from app.screening.generation_config import GenerationConfig, legacy_generation_config


revision = "0005_generation_config_binding"
down_revision = "0004_migration_audit"
branch_labels = None
depends_on = None

_LEGACY = legacy_generation_config()
_LEGACY_JSON = _LEGACY.canonical_json()
_LEGACY_DIGEST = _LEGACY.digest()
_DEFAULT = GenerationConfig()
_DEFAULT_JSON = _DEFAULT.canonical_json()
_DEFAULT_DIGEST = _DEFAULT.digest()
_EVENT_ID = "audit-6c2e6a9b3c9c4b3e8e3e9adf66f8c905"
_DETAILS = '{"migration_revision":"0005_generation_config_binding","action":"upgrade"}'

_OWN_TRIGGERS = (
    "screening_execution_generation_config_immutable",
    "screening_execution_generation_shape_insert",
    "screening_execution_generation_canonical_insert",
    "quality_gate_generation_config_immutable",
    "quality_gate_generation_shape_insert",
    "quality_gate_generation_canonical_insert",
    "quality_gate_generation_binding_insert",
    "quality_gate_generation_binding_update",
    "quality_gate_evaluation_generation_binding",
    "quality_gate_evaluation_generation_binding_update",
    "screening_attempt_generation_binding_insert",
    "screening_attempt_generation_binding_update",
    "schedule_execution_generation_binding_insert",
    "schedule_execution_generation_binding_update",
    "always_on_generation_binding_insert",
    "always_on_generation_binding_update",
)


def _json_default(value: str) -> str:
    """Return a plain server-default value, never raw JSON passed to ``sa.text``."""

    # SQLAlchemy quotes string server defaults itself. Passing a TextClause
    # makes colon-containing JSON look like bind parameters and produces
    # malformed defaults such as ``"num_ctx"NULL`` on SQLite.
    return value


def _bind():
    return op.get_bind()


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(_bind()).get_columns(table)}


def _add(table: str, name: str, column: sa.Column) -> None:
    if name not in _columns(table):
        op.add_column(table, column)


def _repair_server_defaults(table: str, expected: dict[str, str]) -> None:
    """Repair all generation defaults for a table in one schema rewrite."""

    connection = _bind()
    row = connection.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=:name", {"name": table}
    ).fetchone()
    if row is None:
        return
    repaired = str(row[0])
    changed = False
    for column, value in expected.items():
        info = next(
            (item for item in connection.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall() if item[1] == column),
            None,
        )
        if info is None or info[4] is None:
            continue
        old_default = str(info[4])
        new_default = "'" + value.replace("'", "''") + "'"
        if old_default == new_default:
            continue
        column_match = re.search(
            r'(?i)(?:"' + re.escape(column) + r'"|`' + re.escape(column) + r'`|(?<![A-Za-z0-9_])' + re.escape(column) + r'(?![A-Za-z0-9_]))',
            repaired,
        )
        if column_match is None:
            raise RuntimeError(f"cannot repair {table}.{column} server default safely")
        column_end = repaired.find(",", column_match.end())
        if column_end < 0:
            column_end = len(repaired)
        fragment = repaired[column_match.end() : column_end]
        match = re.search(r"\bDEFAULT\s+" + re.escape(old_default), fragment, flags=re.IGNORECASE)
        if match is None:
            raise RuntimeError(f"cannot repair {table}.{column} server default safely")
        start = column_match.end() + match.start()
        end = column_match.end() + match.end()
        repaired = repaired[:start] + "DEFAULT " + new_default + repaired[end:]
        changed = True
    if not changed:
        return
    connection.exec_driver_sql("PRAGMA writable_schema=ON")
    try:
        connection.execute(
            sa.text("UPDATE sqlite_master SET sql=:sql WHERE type='table' AND name=:name"),
            {"sql": repaired, "name": table},
        )
        schema_version = int(connection.exec_driver_sql("PRAGMA schema_version").scalar_one())
        connection.exec_driver_sql(f"PRAGMA schema_version = {schema_version + 1}")
    finally:
        connection.exec_driver_sql("PRAGMA writable_schema=OFF")


def _drop_trigger(name: str) -> None:
    _bind().exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")


def _exec(sql: str) -> None:
    """Execute trigger DDL without SQLAlchemy's colon bind parsing."""

    _bind().exec_driver_sql(sql)


def _drop_triggers(names: tuple[str, ...]) -> None:
    for name in names:
        _drop_trigger(name)


def _config_is_canonical(alias: str, json_column: str = "generation_config_json", digest_column: str = "generation_config_digest") -> str:
    value = f"{alias}.{json_column}"
    digest = f"{alias}.{digest_column}"
    canonical = f"bidops_generation_config_canonical_json({value})"
    computed = f"bidops_generation_config_digest({value})"
    # JSON1 only checks syntax. The byte comparison prevents whitespace or
    # key-order tampering and the digest comparison binds the exact bytes.
    return (
        f"{canonical} IS NULL OR CAST({value} AS TEXT) <> {canonical} "
        f"OR {computed} IS NULL OR {computed} <> {digest}"
    )


def _config_shape(alias: str) -> str:
    value = f"{alias}.generation_config_json"
    digest = f"{alias}.generation_config_digest"
    return (
        f"json_valid({value}) = 0 OR json_type({value}) <> 'object' "
        f"OR length({digest}) <> 64 OR {digest} GLOB '*[^0-9a-f]*'"
    )


def _known_config(alias: str) -> str:
    value = f"CAST({alias}.generation_config_json AS TEXT)"
    digest = f"{alias}.generation_config_digest"
    # Raw connections without the UDF are allowed to use only the two
    # migration-established constants. Any custom or tampered value must go
    # through the registered validator and consequently fails closed.
    return (
        f"({value} IN ('{_LEGACY_JSON}', '{_DEFAULT_JSON}') "
        f"AND {digest} IN ('{_LEGACY_DIGEST}', '{_DEFAULT_DIGEST}'))"
    )


def _create_triggers() -> None:
    _drop_triggers(_OWN_TRIGGERS)

    _exec(
        "CREATE TRIGGER screening_execution_generation_config_immutable "
        "BEFORE UPDATE OF generation_config_json, generation_config_digest ON screening_execution "
        "BEGIN SELECT RAISE(ABORT, 'screening execution generation config is immutable'); END"
    )
    _exec(
        "CREATE TRIGGER screening_execution_generation_shape_insert "
        "BEFORE INSERT ON screening_execution "
        f"WHEN {_config_shape('NEW')} "
        "BEGIN SELECT RAISE(ABORT, 'screening execution generation config is invalid'); END"
    )
    _exec(
        "CREATE TRIGGER screening_execution_generation_canonical_insert "
        "BEFORE INSERT ON screening_execution "
        f"WHEN CASE WHEN {_known_config('NEW')} THEN 0 ELSE CASE WHEN {_config_is_canonical('NEW')} THEN 1 ELSE 0 END END "
        "BEGIN SELECT RAISE(ABORT, 'screening execution generation config is invalid'); END"
    )
    _exec(
        "CREATE TRIGGER quality_gate_generation_config_immutable "
        "BEFORE UPDATE OF generation_config_json, generation_config_digest ON quality_gate "
        "BEGIN SELECT RAISE(ABORT, 'quality gate generation config is immutable'); END"
    )
    _exec(
        "CREATE TRIGGER quality_gate_generation_shape_insert "
        "BEFORE INSERT ON quality_gate "
        f"WHEN {_config_shape('NEW')} "
        "BEGIN SELECT RAISE(ABORT, 'quality gate generation config is invalid'); END"
    )
    _exec(
        "CREATE TRIGGER quality_gate_generation_canonical_insert "
        "BEFORE INSERT ON quality_gate "
        f"WHEN CASE WHEN {_known_config('NEW')} THEN 0 ELSE CASE WHEN {_config_is_canonical('NEW')} THEN 1 ELSE 0 END END "
        "BEGIN SELECT RAISE(ABORT, 'quality gate generation config is invalid'); END"
    )
    _exec(
        "CREATE TRIGGER quality_gate_generation_binding_insert "
        "BEFORE INSERT ON quality_gate "
        "WHEN NOT EXISTS (SELECT 1 FROM screening_execution a "
        "JOIN screening_execution b ON a.execution_id=NEW.pass_a_execution_id "
        "AND b.execution_id=NEW.pass_b_execution_id "
        "WHERE a.generation_config_digest=NEW.generation_config_digest "
        "AND b.generation_config_digest=NEW.generation_config_digest "
        "AND a.generation_config_json=b.generation_config_json "
        "AND a.generation_config_json=NEW.generation_config_json) "
        "BEGIN SELECT RAISE(ABORT, 'quality gate generation config mismatch'); END"
    )
    _exec(
        "CREATE TRIGGER quality_gate_generation_binding_update "
        "BEFORE UPDATE OF pass_a_execution_id, pass_b_execution_id, generation_config_json, generation_config_digest ON quality_gate "
        "WHEN NOT EXISTS (SELECT 1 FROM screening_execution a "
        "JOIN screening_execution b ON a.execution_id=NEW.pass_a_execution_id "
        "AND b.execution_id=NEW.pass_b_execution_id "
        "WHERE a.generation_config_digest=NEW.generation_config_digest "
        "AND b.generation_config_digest=NEW.generation_config_digest "
        "AND a.generation_config_json=b.generation_config_json "
        "AND a.generation_config_json=NEW.generation_config_json) "
        "BEGIN SELECT RAISE(ABORT, 'quality gate generation config mismatch'); END"
    )
    _exec(
        "CREATE TRIGGER quality_gate_evaluation_generation_binding "
        "BEFORE INSERT ON quality_gate_evaluation "
        "WHEN CASE WHEN COALESCE((SELECT " + _known_config("g") + " FROM quality_gate g WHERE g.gate_id=NEW.gate_id), 0) THEN 0 "
        "ELSE CASE WHEN bidops_generation_config_digest((SELECT generation_config_json FROM quality_gate WHERE gate_id=NEW.gate_id)) IS NULL THEN 1 ELSE 0 END END "
        "OR NEW.generation_config_digest <> (SELECT generation_config_digest FROM quality_gate WHERE gate_id=NEW.gate_id) "
        "BEGIN SELECT RAISE(ABORT, 'quality gate evaluation generation config mismatch'); END"
    )
    _exec(
        "CREATE TRIGGER quality_gate_evaluation_generation_binding_update "
        "BEFORE UPDATE OF gate_id, generation_config_digest ON quality_gate_evaluation "
        "WHEN CASE WHEN COALESCE((SELECT " + _known_config("g") + " FROM quality_gate g WHERE g.gate_id=NEW.gate_id), 0) THEN 0 "
        "ELSE CASE WHEN bidops_generation_config_digest((SELECT generation_config_json FROM quality_gate WHERE gate_id=NEW.gate_id)) IS NULL THEN 1 ELSE 0 END END "
        "OR NEW.generation_config_digest <> (SELECT generation_config_digest FROM quality_gate WHERE gate_id=NEW.gate_id) "
        "BEGIN SELECT RAISE(ABORT, 'quality gate evaluation generation config mismatch'); END"
    )

    # Attempt metadata is a projection of its parent execution. The digest is
    # nullable for old/manual rows, but every supplied value must agree with
    # the frozen parent. Calling the UDF makes an unregistered direct SQLite
    # connection fail closed instead of becoming a bypass.
    attempt_parent = "(SELECT generation_config_json FROM screening_execution WHERE execution_id=NEW.execution_id)"
    attempt_digest = "(SELECT generation_config_digest FROM screening_execution WHERE execution_id=NEW.execution_id)"
    attempt_budget = (
        "CASE WHEN NEW.stage IN ('기술 적합성','실적 정합성','공공 SI 적합성','사업성·자격 제약','전략 부합') "
        f"THEN json_extract({attempt_parent}, '$.num_predict.perspective') "
        "WHEN NEW.stage IN ('counterargument','반론 검토') "
        f"THEN json_extract({attempt_parent}, '$.num_predict.counterargument') "
        "WHEN NEW.stage IN ('synthesis','judgment.v3','종합 판정') "
        f"THEN json_extract({attempt_parent}, '$.num_predict.synthesis') END"
    )
    attempt_when = (
        f"CASE WHEN ({_known_config('p').replace('p.generation_config_json', attempt_parent).replace('p.generation_config_digest', attempt_digest)}) THEN 0 "
        f"ELSE CASE WHEN bidops_generation_config_digest({attempt_parent}) IS NULL THEN 1 ELSE 0 END END "
        f"OR (NEW.generation_config_digest IS NOT NULL AND NEW.generation_config_digest <> {attempt_digest}) "
        f"OR (NEW.num_ctx IS NOT NULL AND NEW.num_ctx <> json_extract({attempt_parent}, '$.num_ctx')) "
        f"OR (NEW.num_predict IS NOT NULL AND NEW.num_predict <> ({attempt_budget}))"
    )
    _exec(
        "CREATE TRIGGER screening_attempt_generation_binding_insert BEFORE INSERT ON screening_attempt "
        f"WHEN {attempt_when} BEGIN SELECT RAISE(ABORT, 'screening attempt generation config mismatch'); END"
    )
    _exec(
        "CREATE TRIGGER screening_attempt_generation_binding_update "
        "BEFORE UPDATE OF execution_id, stage, generation_config_digest, num_ctx, num_predict ON screening_attempt "
        f"WHEN {attempt_when} BEGIN SELECT RAISE(ABORT, 'screening attempt generation config mismatch'); END"
    )

    schedule_parent = "(SELECT generation_config_json FROM screening_execution WHERE execution_id=NEW.screening_execution_id)"
    schedule_digest = "(SELECT generation_config_digest FROM screening_execution WHERE execution_id=NEW.screening_execution_id)"
    for operation in ("INSERT", "UPDATE OF screening_execution_id, generation_config_digest"):
        suffix = "insert" if operation == "INSERT" else "update"
        _exec(
            f"CREATE TRIGGER schedule_execution_generation_binding_{suffix} BEFORE {operation} ON schedule_execution "
            "WHEN NEW.generation_config_digest IS NOT NULL BEGIN "
            "SELECT CASE WHEN NEW.screening_execution_id IS NULL THEN RAISE(ABORT, 'schedule execution generation config mismatch') "
            f"WHEN NEW.generation_config_digest <> {schedule_digest} THEN RAISE(ABORT, 'schedule execution generation config mismatch') "
            f"WHEN NOT ({_known_config('p').replace('p.generation_config_json', schedule_parent).replace('p.generation_config_digest', schedule_digest)}) "
            f"THEN CASE WHEN bidops_generation_config_digest({schedule_parent}) IS NULL THEN RAISE(ABORT, 'schedule execution generation config mismatch') END "
            "END; END"
        )

    always_parent = "(SELECT g.generation_config_json FROM quality_gate_evaluation e JOIN quality_gate g ON g.gate_id = e.gate_id WHERE e.evaluation_id=NEW.quality_gate_result_id)"
    always_digest = "(SELECT generation_config_digest FROM quality_gate_evaluation WHERE evaluation_id=NEW.quality_gate_result_id)"
    for operation in ("INSERT", "UPDATE OF quality_gate_result_id, generation_config_digest"):
        suffix = "insert" if operation == "INSERT" else "update"
        _exec(
            f"CREATE TRIGGER always_on_generation_binding_{suffix} BEFORE {operation} ON always_on_state "
            "WHEN NEW.generation_config_digest IS NOT NULL BEGIN "
            "SELECT CASE WHEN NEW.quality_gate_result_id IS NULL THEN RAISE(ABORT, 'always-on generation config mismatch') "
            f"WHEN NEW.generation_config_digest <> {always_digest} THEN RAISE(ABORT, 'always-on generation config mismatch') "
            f"WHEN NOT ({_known_config('p').replace('p.generation_config_json', always_parent).replace('p.generation_config_digest', always_digest)}) "
            f"THEN CASE WHEN bidops_generation_config_digest({always_parent}) IS NULL THEN RAISE(ABORT, 'always-on generation config mismatch') END "
            "END; END"
        )


def upgrade() -> None:
    # A failed SQLite migration can leave columns/triggers in place while
    # Alembic remains at 0004. Rebuild our trigger set on every invocation.
    _drop_triggers(_OWN_TRIGGERS)
    # 0002's immutable evaluation trigger blocks the required digest update.
    _drop_trigger("quality_gate_evaluation_no_update")

    # New rows receive the current config from these defaults. Existing rows
    # are explicitly rewritten to the deterministic legacy config below.
    _add("screening_execution", "generation_config_json", sa.Column("generation_config_json", sa.JSON(), nullable=False, server_default=_json_default(_DEFAULT_JSON)))
    _add("screening_execution", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=False, server_default=_DEFAULT_DIGEST))
    _add("screening_attempt", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=True, server_default=_DEFAULT_DIGEST))
    _add("screening_attempt", "num_ctx", sa.Column("num_ctx", sa.Integer(), nullable=True))
    _add("screening_attempt", "num_predict", sa.Column("num_predict", sa.Integer(), nullable=True))
    _add("quality_gate", "generation_config_json", sa.Column("generation_config_json", sa.JSON(), nullable=False, server_default=_json_default(_DEFAULT_JSON)))
    _add("quality_gate", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=False, server_default=_DEFAULT_DIGEST))
    _add("quality_gate_evaluation", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=False, server_default=_DEFAULT_DIGEST))
    _add("schedule_execution", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=True))
    _add("always_on_state", "generation_config_digest", sa.Column("generation_config_digest", sa.String(64), nullable=True))

    # A prior implementation passed raw JSON to sa.text(), leaving malformed
    # defaults behind on a partial non-transactional DDL attempt. Repair only
    # those defaults; no table data is rewritten by this operation.
    _repair_server_defaults(
        "screening_execution",
        {"generation_config_json": _DEFAULT_JSON, "generation_config_digest": _DEFAULT_DIGEST},
    )
    _repair_server_defaults("screening_attempt", {"generation_config_digest": _DEFAULT_DIGEST})
    _repair_server_defaults(
        "quality_gate",
        {"generation_config_json": _DEFAULT_JSON, "generation_config_digest": _DEFAULT_DIGEST},
    )
    _repair_server_defaults("quality_gate_evaluation", {"generation_config_digest": _DEFAULT_DIGEST})

    connection = _bind()
    for table in ("screening_execution", "quality_gate"):
        connection.execute(
            sa.text(f"UPDATE {table} SET generation_config_json=:json, generation_config_digest=:digest"),
            {"json": _LEGACY_JSON, "digest": _LEGACY_DIGEST},
        )
    connection.execute(sa.text("UPDATE quality_gate_evaluation SET generation_config_digest=:digest"), {"digest": _LEGACY_DIGEST})
    connection.execute(
        sa.text("UPDATE screening_attempt SET generation_config_digest=:digest, num_ctx=16384, num_predict=2048"),
        {"digest": _LEGACY_DIGEST},
    )
    for table in ("schedule_execution", "always_on_state"):
        connection.execute(
            sa.text(f"UPDATE {table} SET generation_config_digest=:digest WHERE generation_config_digest IS NOT NULL"),
            {"digest": _LEGACY_DIGEST},
        )

    _create_triggers()
    # Restore the core immutable evaluation contract from 0002 exactly.
    _exec(
        "CREATE TRIGGER quality_gate_evaluation_no_update BEFORE UPDATE ON quality_gate_evaluation "
        "BEGIN SELECT RAISE(ABORT, 'quality gate evaluation is immutable'); END"
    )
    connection.execute(
        sa.text(
            "INSERT OR IGNORE INTO audit_event "
            "(event_id, event_type, actor, target_type, target_id, occurred_at, details_json) "
            "VALUES (:event_id, 'db.migration', 'system:migration', 'database', "
            "'0005_generation_config_binding', '2026-01-01 00:00:01', :details)"
        ),
        {"event_id": _EVENT_ID, "details": _DETAILS},
    )


def downgrade() -> None:
    _drop_triggers(_OWN_TRIGGERS)
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
        if name in _columns(table):
            op.drop_column(table, name)
    _bind().execute(
        sa.text(
            "DELETE FROM audit_event WHERE event_id=:event_id "
            "AND event_type='db.migration' AND actor='system:migration' "
            "AND target_id='0005_generation_config_binding'"
        ),
        {"event_id": _EVENT_ID},
    )
