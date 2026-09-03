"""Create the screening runtime on PostgreSQL 17.

Revision ID: 0003_screening_runtime_pg
Revises: 0002_screening_basis_text

The T15 branch built this runtime on SQLite: cross-row invariants were
``BEFORE ... RAISE(ABORT)`` triggers, and the frozen generation-config binding
was enforced by CHECK constraints calling four Python user-defined functions
registered on every SQLite connection.  Neither construct exists in
PostgreSQL, so this revision reproduces the same rules natively:

* the canonical-JSON and SHA-256 digest validators become two ``IMMUTABLE``
  functions in the ``bidops`` schema, computing byte-identical output to
  :mod:`app.core.generation_config`;
* every trigger becomes a ``plpgsql`` function raising ``check_violation``
  (SQLSTATE 23514), so a violated invariant still surfaces as an
  ``IntegrityError`` rather than a generic failure.

The trigger set is the T15 head state: revision ``0002_screening_runtime`` as
amended by ``0003_schedule_skipped_recovery`` (skipped executions are
recoverable, and always-on disable writes an audit row before the update) and
extended by ``0005_generation_config_binding``.  There is no SQLite history to
replay on PostgreSQL, so the intermediate shapes are not recreated.
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

from app.models import SCREENING_RUNTIME_TABLES
from app.core import (
    Base,
    GENERATION_CONFIG_SCHEMA,
    MAX_NUM_CTX,
    MAX_NUM_PREDICT,
    MIN_NUM_CTX,
    MIN_NUM_PREDICT,
)


revision = "0003_screening_runtime_pg"
down_revision = "0002_screening_basis_text"
branch_labels = None
depends_on = None

SCHEMA = "bidops"

_EVENT_ID = "audit-3b1c9f5d47a24f6ea0d3e2c8b7561f04"
_DETAILS = json.dumps(
    {"migration_revision": revision, "action": "upgrade"}, separators=(",", ":")
)


# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------


def _runtime_tables() -> list[sa.Table]:
    """Return the screening runtime tables bound to the application schema."""

    for table in Base.metadata.tables.values():
        table.schema = SCHEMA
    return [Base.metadata.tables[name] for name in SCREENING_RUNTIME_TABLES]


# ---------------------------------------------------------------------------
# Generation-config validators
#
# ``app.core.generation_config`` is the single source of truth for the
# canonical representation.  These functions must produce the same bytes, so
# the bounds and the schema string are imported rather than restated.
# ---------------------------------------------------------------------------

_CANONICAL_JSON_FUNCTION = f"""
CREATE FUNCTION {SCHEMA}.generation_config_canonical_json(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $function$
DECLARE
    doc jsonb;
    budgets jsonb;
    num_ctx bigint;
    perspective bigint;
    counterargument bigint;
    synthesis bigint;
BEGIN
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    BEGIN
        doc := value::jsonb;
    EXCEPTION WHEN others THEN
        RETURN NULL;
    END;
    IF jsonb_typeof(doc) <> 'object' THEN
        RETURN NULL;
    END IF;
    -- The Python parser requires exactly this key set, not a superset.
    IF (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(doc) AS k)
       <> ARRAY['num_ctx', 'num_predict', 'schema_version', 'stream', 'think'] THEN
        RETURN NULL;
    END IF;
    IF doc ->> 'schema_version' IS DISTINCT FROM '{GENERATION_CONFIG_SCHEMA}' THEN
        RETURN NULL;
    END IF;
    -- think and stream must both be the JSON boolean false.
    IF doc -> 'think' <> 'false'::jsonb OR doc -> 'stream' <> 'false'::jsonb THEN
        RETURN NULL;
    END IF;
    budgets := doc -> 'num_predict';
    IF jsonb_typeof(budgets) <> 'object' THEN
        RETURN NULL;
    END IF;
    IF (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(budgets) AS k)
       <> ARRAY['counterargument', 'perspective', 'synthesis'] THEN
        RETURN NULL;
    END IF;

    num_ctx := {SCHEMA}.generation_config_strict_int(
        doc -> 'num_ctx', {MIN_NUM_CTX}, {MAX_NUM_CTX});
    perspective := {SCHEMA}.generation_config_strict_int(
        budgets -> 'perspective', {MIN_NUM_PREDICT}, {MAX_NUM_PREDICT});
    counterargument := {SCHEMA}.generation_config_strict_int(
        budgets -> 'counterargument', {MIN_NUM_PREDICT}, {MAX_NUM_PREDICT});
    synthesis := {SCHEMA}.generation_config_strict_int(
        budgets -> 'synthesis', {MIN_NUM_PREDICT}, {MAX_NUM_PREDICT});
    IF num_ctx IS NULL OR perspective IS NULL
       OR counterargument IS NULL OR synthesis IS NULL THEN
        RETURN NULL;
    END IF;
    IF perspective > num_ctx OR counterargument > num_ctx OR synthesis > num_ctx THEN
        RETURN NULL;
    END IF;

    -- json.dumps(..., sort_keys=True, separators=(",", ":")) byte for byte.
    -- Concatenation rather than format(): a '%s' in DDL is consumed as a
    -- driver placeholder before PostgreSQL ever sees the function body.
    RETURN '{{"num_ctx":' || num_ctx::text
        || ',"num_predict":{{"counterargument":' || counterargument::text
        || ',"perspective":' || perspective::text
        || ',"synthesis":' || synthesis::text
        || '}},"schema_version":"{GENERATION_CONFIG_SCHEMA}","stream":false,"think":false}}';
END
$function$;
"""

_STRICT_INT_FUNCTION = f"""
CREATE FUNCTION {SCHEMA}.generation_config_strict_int(value jsonb, minimum bigint, maximum bigint)
RETURNS bigint
LANGUAGE plpgsql
IMMUTABLE
AS $function$
DECLARE
    literal text;
    parsed bigint;
BEGIN
    -- Mirrors ``type(value) is not int``: JSON booleans, floats, and numeric
    -- strings are all rejected rather than coerced.
    IF value IS NULL OR jsonb_typeof(value) <> 'number' THEN
        RETURN NULL;
    END IF;
    literal := value #>> '{{}}';
    IF literal !~ '^(0|-?[1-9][0-9]*)$' THEN
        RETURN NULL;
    END IF;
    parsed := literal::bigint;
    IF parsed < minimum OR parsed > maximum THEN
        RETURN NULL;
    END IF;
    RETURN parsed;
END
$function$;
"""

_DIGEST_FUNCTION = f"""
CREATE FUNCTION {SCHEMA}.generation_config_digest(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $function$
    SELECT encode(
        sha256(convert_to({SCHEMA}.generation_config_canonical_json($1), 'UTF8')),
        'hex')
$function$;
"""

_FUNCTIONS = (_STRICT_INT_FUNCTION, _CANONICAL_JSON_FUNCTION, _DIGEST_FUNCTION)
_FUNCTION_SIGNATURES = (
    "generation_config_digest(text)",
    "generation_config_canonical_json(text)",
    "generation_config_strict_int(jsonb, bigint, bigint)",
)


# ---------------------------------------------------------------------------
# Trigger helpers
# ---------------------------------------------------------------------------


def _guard(name: str, table: str, event: str, when: str, message: str) -> tuple[str, str]:
    """Build a guard trigger that rejects a row when ``when`` holds.

    The SQLite original was ``BEFORE <event> ON t WHEN <cond>
    BEGIN SELECT RAISE(ABORT, '<msg>'); END``.  ``check_violation`` keeps the
    failure surfacing as an ``IntegrityError`` in SQLAlchemy.
    """

    function = f"""
CREATE FUNCTION {SCHEMA}.tf_{name}() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    IF {when} THEN
        RAISE EXCEPTION '{message}' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$function$;
"""
    trigger = (
        f"CREATE TRIGGER {name} BEFORE {event} ON {SCHEMA}.{table} "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_{name}();"
    )
    return function, trigger


def _effect(name: str, table: str, event: str, when: str | None, body: str) -> tuple[str, str]:
    """Build an AFTER trigger that performs ``body`` as a side effect."""

    condition = f" WHEN ({when})" if when else ""
    function = f"""
CREATE FUNCTION {SCHEMA}.tf_{name}() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
{body}
    RETURN NULL;
END
$function$;
"""
    trigger = (
        f"CREATE TRIGGER {name} AFTER {event} ON {SCHEMA}.{table} "
        f"FOR EACH ROW{condition} EXECUTE FUNCTION {SCHEMA}.tf_{name}();"
    )
    return function, trigger


# Cross-row invariants that a CHECK constraint cannot express.
_PROFILE_PAIR_MISMATCH = (
    "(SELECT digest FROM {schema}.company_profile_snapshot"
    " WHERE version = NEW.company_profile_version) IS DISTINCT FROM NEW.company_profile_digest"
).format(schema=SCHEMA)

_NOTICE_IDENTITY_MISMATCH = (
    "NEW.scope = 'single_notice' AND ("
    " (SELECT notice_key FROM {schema}.notice WHERE id = NEW.notice_pk) IS DISTINCT FROM NEW.notice_id"
    " OR (SELECT run_id FROM {schema}.notice WHERE id = NEW.notice_pk) IS DISTINCT FROM NEW.source_run_id"
    ")"
).format(schema=SCHEMA)

_ACTIVE_GATE_MISSING = (
    "NEW.status = 'active' AND NOT EXISTS ("
    " SELECT 1 FROM {schema}.quality_gate_evaluation e"
    " JOIN {schema}.quality_gate g ON g.gate_id = e.gate_id"
    " WHERE e.evaluation_id = NEW.quality_gate_result_id"
    " AND e.revision = (SELECT MAX(latest.revision) FROM {schema}.quality_gate_evaluation latest"
    "                   WHERE latest.gate_id = e.gate_id)"
    " AND e.result_status = '통과' AND g.purpose = 'operational_approval'"
    " AND g.execution_status = '완료' AND g.policy_version = NEW.policy_version"
    " AND g.prompt_version = NEW.prompt_version)"
).format(schema=SCHEMA)

_ALWAYS_ON_GATE_MISSING = (
    "NEW.enabled AND NOT EXISTS ("
    " SELECT 1 FROM {schema}.screening_policy p"
    " JOIN {schema}.quality_gate_evaluation e ON e.evaluation_id = p.quality_gate_result_id"
    " JOIN {schema}.quality_gate g ON g.gate_id = e.gate_id"
    " WHERE p.policy_version = NEW.policy_version AND p.status = 'active' AND p.active_slot = 1"
    " AND p.prompt_version = NEW.prompt_version"
    " AND e.evaluation_id = NEW.quality_gate_result_id"
    " AND e.revision = (SELECT MAX(latest.revision) FROM {schema}.quality_gate_evaluation latest"
    "                   WHERE latest.gate_id = e.gate_id)"
    " AND e.result_status = '통과' AND g.purpose = 'operational_approval'"
    " AND g.policy_version = NEW.policy_version AND g.prompt_version = p.prompt_version"
    " AND g.model_name = NEW.model_name AND g.model_digest = NEW.model_digest"
    " AND g.company_profile_version = NEW.company_profile_version"
    " AND g.company_profile_digest = NEW.company_profile_digest)"
).format(schema=SCHEMA)

# ``0003_schedule_skipped_recovery`` added '건너뜀' so a skipped execution can
# be recovered manually.
_RECOVERABLE = "'실패', '부분 성공', '건너뜀'"

_RELATION_MISMATCH = (
    "(NEW.duplicate_of_execution_id IS NOT NULL AND NOT EXISTS ("
    "  SELECT 1 FROM {schema}.schedule_execution target"
    "  WHERE target.execution_id = NEW.duplicate_of_execution_id"
    "  AND target.run_key = NEW.run_key AND target.job_kind = NEW.job_kind))"
    " OR (NEW.recovery_of_execution_id IS NOT NULL AND NOT EXISTS ("
    "  SELECT 1 FROM {schema}.schedule_execution target"
    "  WHERE target.execution_id = NEW.recovery_of_execution_id"
    "  AND target.run_key = NEW.run_key AND target.job_kind = NEW.job_kind"
    "  AND target.status IN ({recoverable})))"
).format(schema=SCHEMA, recoverable=_RECOVERABLE)

_RELATION_TARGET_MISMATCH = (
    "EXISTS (SELECT 1 FROM {schema}.schedule_execution child"
    " WHERE (child.duplicate_of_execution_id = NEW.execution_id"
    "        OR child.recovery_of_execution_id = NEW.execution_id)"
    " AND (NEW.run_key <> OLD.run_key OR NEW.job_kind <> OLD.job_kind"
    "      OR (child.recovery_of_execution_id = NEW.execution_id"
    "          AND NEW.status NOT IN ({recoverable}))))"
).format(schema=SCHEMA, recoverable=_RECOVERABLE)

_INTEGRITY_GUARDS = (
    ("screening_execution_profile_pair_insert", "screening_execution", "INSERT",
     _PROFILE_PAIR_MISMATCH, "company profile version/digest mismatch"),
    ("screening_execution_profile_pair_update", "screening_execution",
     "UPDATE OF company_profile_version, company_profile_digest",
     _PROFILE_PAIR_MISMATCH, "company profile version/digest mismatch"),
    ("screening_execution_notice_identity_insert", "screening_execution", "INSERT",
     _NOTICE_IDENTITY_MISMATCH, "single notice identity mismatch"),
    ("screening_execution_notice_identity_update", "screening_execution",
     "UPDATE OF scope, notice_pk, notice_id, source_run_id",
     _NOTICE_IDENTITY_MISMATCH, "single notice identity mismatch"),
    ("quality_gate_profile_pair_insert", "quality_gate", "INSERT",
     _PROFILE_PAIR_MISMATCH, "quality gate profile mismatch"),
    ("quality_gate_profile_pair_update", "quality_gate",
     "UPDATE OF company_profile_version, company_profile_digest",
     _PROFILE_PAIR_MISMATCH, "quality gate profile mismatch"),
    ("quality_gate_input_immutable", "quality_gate",
     "UPDATE OF purpose, baseline_run_id, sample_artifact_path, sample_artifact_digest,"
     " baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version,"
     " model_name, model_digest, company_profile_version, company_profile_digest,"
     " pass_a_execution_id, pass_b_execution_id, created_at, created_by",
     "TRUE", "quality gate input is immutable"),
    ("quality_gate_evaluation_append", "quality_gate_evaluation", "INSERT",
     "NEW.revision <> COALESCE((SELECT MAX(revision) + 1 FROM {schema}.quality_gate_evaluation"
     " WHERE gate_id = NEW.gate_id), 1)".format(schema=SCHEMA),
     "quality gate evaluations must append sequentially"),
    ("quality_gate_evaluation_no_update", "quality_gate_evaluation", "UPDATE",
     "TRUE", "quality gate evaluation is immutable"),
    ("screening_policy_body_immutable", "screening_policy",
     "UPDATE OF policy_version, schema_version, prompt_version, content_digest,"
     " perspective_prompts_json, counterargument_prompt_json, synthesis_prompt_json,"
     " candidate_selection_json, thresholds_json",
     "TRUE", "screening policy identity/body is immutable"),
    ("screening_policy_active_gate_insert", "screening_policy", "INSERT",
     _ACTIVE_GATE_MISSING, "active policy requires latest passing operational approval"),
    ("screening_policy_active_gate_update", "screening_policy",
     "UPDATE OF status, active_slot, activated_at, activated_by, quality_gate_result_id",
     _ACTIVE_GATE_MISSING, "active policy requires latest passing operational approval"),
    ("quality_gate_review_pass_a_insert", "quality_gate_review", "INSERT",
     "(SELECT pass_a_execution_id FROM {schema}.quality_gate WHERE gate_id = NEW.gate_id)"
     " IS DISTINCT FROM NEW.execution_id".format(schema=SCHEMA),
     "review execution must be gate pass A"),
    ("quality_gate_review_pass_a_update", "quality_gate_review",
     "UPDATE OF gate_id, execution_id",
     "(SELECT pass_a_execution_id FROM {schema}.quality_gate WHERE gate_id = NEW.gate_id)"
     " IS DISTINCT FROM NEW.execution_id".format(schema=SCHEMA),
     "review execution must be gate pass A"),
    ("schedule_execution_job_kind_insert", "schedule_execution", "INSERT",
     "(SELECT job_kind FROM {schema}.schedule_reservation WHERE run_key = NEW.run_key)"
     " IS DISTINCT FROM NEW.job_kind".format(schema=SCHEMA),
     "schedule execution job kind mismatch"),
    ("schedule_execution_job_kind_update", "schedule_execution",
     "UPDATE OF run_key, job_kind",
     "(SELECT job_kind FROM {schema}.schedule_reservation WHERE run_key = NEW.run_key)"
     " IS DISTINCT FROM NEW.job_kind".format(schema=SCHEMA),
     "schedule execution job kind mismatch"),
    ("schedule_execution_relation_insert", "schedule_execution", "INSERT",
     _RELATION_MISMATCH, "schedule execution relation mismatch"),
    ("schedule_execution_relation_update", "schedule_execution",
     "UPDATE OF run_key, job_kind, duplicate_of_execution_id, recovery_of_execution_id",
     _RELATION_MISMATCH, "schedule execution relation mismatch"),
    ("schedule_execution_relation_target_update", "schedule_execution",
     "UPDATE OF run_key, job_kind, status",
     _RELATION_TARGET_MISMATCH, "schedule execution target relation mismatch"),
    ("always_on_enabled_insert", "always_on_state", "INSERT",
     _ALWAYS_ON_GATE_MISSING, "always-on requires matching active operational approval"),
    ("always_on_enabled_update", "always_on_state",
     "UPDATE OF enabled, quality_gate_result_id, policy_version, model_name, model_digest,"
     " prompt_version, company_profile_version, company_profile_digest",
     _ALWAYS_ON_GATE_MISSING, "always-on requires matching active operational approval"),
)


# Projection triggers. ``0003_schedule_skipped_recovery`` made the always-on
# disable write its audit row before the update, so the ``enabled`` predicate
# is still evaluated against the pre-update state inside the caller's
# transaction.
_AUDIT_INSERT = """
    INSERT INTO {schema}.screening_audit_event
        (event_id, event_type, actor, target_type, target_id, occurred_at, details_json)
    -- md5/random/clock_timestamp are PostgreSQL built-ins; keeping this
    -- extension-free lets a restricted migration role install the schema.
    SELECT 'audit-' || md5(clock_timestamp()::text || random()::text), 'schedule.always_on_disabled',
           '{actor}', 'schedule', '1', {occurred_at},
           json_build_object('reason', '{reason}')
    FROM {schema}.always_on_state
    WHERE {predicate};
"""

_POLICY_PROJECTION_PREDICATE = "enabled AND policy_version = NEW.policy_version"
_GATE_PROJECTION_PREDICATE = (
    "enabled AND NEW.result_status IN ('미달', '미측정', '보류')"
    " AND quality_gate_result_id IN ("
    "   SELECT evaluation_id FROM {schema}.quality_gate_evaluation WHERE gate_id = NEW.gate_id)"
).format(schema=SCHEMA)

_POLICY_PROJECTION_BODY = _AUDIT_INSERT.format(
    schema=SCHEMA,
    actor="system:policy",
    occurred_at="COALESCE(NEW.activated_at, OLD.activated_at, CURRENT_TIMESTAMP)",
    reason="policy_inactive",
    predicate=_POLICY_PROJECTION_PREDICATE,
) + f"""
    UPDATE {SCHEMA}.always_on_state
    SET enabled = false,
        updated_at = COALESCE(NEW.activated_at, OLD.activated_at, CURRENT_TIMESTAMP),
        updated_by = 'system:policy'
    WHERE {_POLICY_PROJECTION_PREDICATE};
"""

_GATE_PROJECTION_BODY = f"""
    UPDATE {SCHEMA}.quality_gate
    SET result_status = NEW.result_status,
        metrics_json = NEW.metrics_json,
        reasons_json = NEW.reasons_json
    WHERE gate_id = NEW.gate_id;
""" + _AUDIT_INSERT.format(
    schema=SCHEMA,
    actor="system:quality-gate",
    occurred_at="NEW.created_at",
    reason="quality_gate_not_passing",
    predicate=_GATE_PROJECTION_PREDICATE,
) + f"""
    UPDATE {SCHEMA}.always_on_state
    SET enabled = false, updated_at = NEW.created_at, updated_by = 'system:quality-gate'
    WHERE {_GATE_PROJECTION_PREDICATE};
"""

_PROJECTION_EFFECTS = (
    ("screening_policy_projection_changed", "screening_policy",
     "UPDATE OF status, active_slot, quality_gate_result_id",
     "NEW.status <> 'active' OR NEW.active_slot IS NULL"
     " OR NEW.quality_gate_result_id IS DISTINCT FROM OLD.quality_gate_result_id",
     _POLICY_PROJECTION_BODY),
    ("quality_gate_evaluation_projection_changed", "quality_gate_evaluation",
     "INSERT", None, _GATE_PROJECTION_BODY),
)


# ---------------------------------------------------------------------------
# Frozen generation-config binding (T15 revision 0005)
# ---------------------------------------------------------------------------

def _canonical(value: str, digest: str) -> str:
    """The stored pair must be canonical and its digest must match the bytes."""

    return (
        f"{SCHEMA}.generation_config_canonical_json({value}) IS NULL"
        f" OR {value} IS DISTINCT FROM {SCHEMA}.generation_config_canonical_json({value})"
        f" OR {SCHEMA}.generation_config_digest({value}) IS DISTINCT FROM {digest}"
    )


def _self(column: str = "generation_config_json") -> str:
    # A PostgreSQL ``json`` column preserves the exact stored text, so the byte
    # comparison that SQLite performed on TEXT still applies.
    return f"NEW.{column}::text"


_EXEC_CANONICAL = _canonical(_self(), "NEW.generation_config_digest")

_ATTEMPT_PARENT = (
    f"(SELECT generation_config_json::text FROM {SCHEMA}.screening_execution"
    " WHERE execution_id = NEW.execution_id)"
)
_ATTEMPT_DIGEST = (
    f"(SELECT generation_config_digest FROM {SCHEMA}.screening_execution"
    " WHERE execution_id = NEW.execution_id)"
)
_ATTEMPT_BUDGET = (
    "CASE"
    " WHEN NEW.stage IN ('기술 적합성','실적 정합성','공공 SI 적합성','사업성·자격 제약','전략 부합')"
    f" THEN ({_ATTEMPT_PARENT}::json -> 'num_predict' ->> 'perspective')::int"
    " WHEN NEW.stage IN ('counterargument','반론 검토')"
    f" THEN ({_ATTEMPT_PARENT}::json -> 'num_predict' ->> 'counterargument')::int"
    " WHEN NEW.stage IN ('synthesis','judgment.v3','종합 판정')"
    f" THEN ({_ATTEMPT_PARENT}::json -> 'num_predict' ->> 'synthesis')::int"
    " END"
)
_ATTEMPT_MISMATCH = (
    f"({_canonical(_ATTEMPT_PARENT, _ATTEMPT_DIGEST)})"
    f" OR (NEW.generation_config_digest IS NOT NULL"
    f"     AND NEW.generation_config_digest IS DISTINCT FROM {_ATTEMPT_DIGEST})"
    f" OR (NEW.num_ctx IS NOT NULL"
    f"     AND NEW.num_ctx IS DISTINCT FROM ({_ATTEMPT_PARENT}::json ->> 'num_ctx')::int)"
    f" OR (NEW.num_predict IS NOT NULL AND NEW.num_predict IS DISTINCT FROM ({_ATTEMPT_BUDGET}))"
)

_GATE_PAIR_MISMATCH = (
    f"NOT EXISTS (SELECT 1 FROM {SCHEMA}.screening_execution a"
    f" JOIN {SCHEMA}.screening_execution b ON a.execution_id = NEW.pass_a_execution_id"
    " AND b.execution_id = NEW.pass_b_execution_id"
    " WHERE a.generation_config_digest = NEW.generation_config_digest"
    " AND b.generation_config_digest = NEW.generation_config_digest"
    " AND a.generation_config_json::text = b.generation_config_json::text"
    " AND a.generation_config_json::text = NEW.generation_config_json::text)"
)

_GATE_PARENT = (
    f"(SELECT generation_config_json::text FROM {SCHEMA}.quality_gate WHERE gate_id = NEW.gate_id)"
)
_GATE_PARENT_DIGEST = (
    f"(SELECT generation_config_digest FROM {SCHEMA}.quality_gate WHERE gate_id = NEW.gate_id)"
)
_EVALUATION_MISMATCH = (
    f"({_canonical(_GATE_PARENT, _GATE_PARENT_DIGEST)})"
    f" OR NEW.generation_config_digest IS DISTINCT FROM {_GATE_PARENT_DIGEST}"
)

_SCHEDULE_PARENT = (
    f"(SELECT generation_config_json::text FROM {SCHEMA}.screening_execution"
    " WHERE execution_id = NEW.screening_execution_id)"
)
_SCHEDULE_DIGEST = (
    f"(SELECT generation_config_digest FROM {SCHEMA}.screening_execution"
    " WHERE execution_id = NEW.screening_execution_id)"
)
_SCHEDULE_MISMATCH = (
    "NEW.generation_config_digest IS NOT NULL AND ("
    " NEW.screening_execution_id IS NULL"
    f" OR NEW.generation_config_digest IS DISTINCT FROM {_SCHEDULE_DIGEST}"
    f" OR ({_canonical(_SCHEDULE_PARENT, _SCHEDULE_DIGEST)}))"
)

_ALWAYS_PARENT = (
    f"(SELECT g.generation_config_json::text FROM {SCHEMA}.quality_gate_evaluation e"
    f" JOIN {SCHEMA}.quality_gate g ON g.gate_id = e.gate_id"
    " WHERE e.evaluation_id = NEW.quality_gate_result_id)"
)
_ALWAYS_DIGEST = (
    f"(SELECT generation_config_digest FROM {SCHEMA}.quality_gate_evaluation"
    " WHERE evaluation_id = NEW.quality_gate_result_id)"
)
_ALWAYS_MISMATCH = (
    "NEW.generation_config_digest IS NOT NULL AND ("
    " NEW.quality_gate_result_id IS NULL"
    f" OR NEW.generation_config_digest IS DISTINCT FROM {_ALWAYS_DIGEST}"
    f" OR ({_canonical(_ALWAYS_PARENT, _ALWAYS_DIGEST)}))"
)

_BINDING_GUARDS = (
    ("screening_execution_generation_config_immutable", "screening_execution",
     "UPDATE OF generation_config_json, generation_config_digest",
     "TRUE", "screening execution generation config is immutable"),
    ("screening_execution_generation_canonical_insert", "screening_execution", "INSERT",
     _EXEC_CANONICAL, "screening execution generation config is invalid"),
    ("quality_gate_generation_config_immutable", "quality_gate",
     "UPDATE OF generation_config_json, generation_config_digest",
     "TRUE", "quality gate generation config is immutable"),
    ("quality_gate_generation_canonical_insert", "quality_gate", "INSERT",
     _EXEC_CANONICAL, "quality gate generation config is invalid"),
    ("quality_gate_generation_binding_insert", "quality_gate", "INSERT",
     _GATE_PAIR_MISMATCH, "quality gate generation config mismatch"),
    ("quality_gate_generation_binding_update", "quality_gate",
     "UPDATE OF pass_a_execution_id, pass_b_execution_id, generation_config_json,"
     " generation_config_digest",
     _GATE_PAIR_MISMATCH, "quality gate generation config mismatch"),
    ("quality_gate_evaluation_generation_binding", "quality_gate_evaluation", "INSERT",
     _EVALUATION_MISMATCH, "quality gate evaluation generation config mismatch"),
    ("quality_gate_evaluation_generation_binding_update", "quality_gate_evaluation",
     "UPDATE OF gate_id, generation_config_digest",
     _EVALUATION_MISMATCH, "quality gate evaluation generation config mismatch"),
    ("screening_attempt_generation_binding_insert", "screening_attempt", "INSERT",
     _ATTEMPT_MISMATCH, "screening attempt generation config mismatch"),
    ("screening_attempt_generation_binding_update", "screening_attempt",
     "UPDATE OF execution_id, stage, generation_config_digest, num_ctx, num_predict",
     _ATTEMPT_MISMATCH, "screening attempt generation config mismatch"),
    ("schedule_execution_generation_binding_insert", "schedule_execution", "INSERT",
     _SCHEDULE_MISMATCH, "schedule execution generation config mismatch"),
    ("schedule_execution_generation_binding_update", "schedule_execution",
     "UPDATE OF screening_execution_id, generation_config_digest",
     _SCHEDULE_MISMATCH, "schedule execution generation config mismatch"),
    ("always_on_generation_binding_insert", "always_on_state", "INSERT",
     _ALWAYS_MISMATCH, "always-on generation config mismatch"),
    ("always_on_generation_binding_update", "always_on_state",
     "UPDATE OF quality_gate_result_id, generation_config_digest",
     _ALWAYS_MISMATCH, "always-on generation config mismatch"),
)


_ALL_GUARDS = _INTEGRITY_GUARDS + _BINDING_GUARDS


def _time_value(name: str, default: str) -> str:
    """Read an operator HH:MM default, falling back on anything malformed."""

    import os

    value = os.environ.get(name, default)
    try:
        hour, minute = int(value[:2]), int(value[3:])
    except (ValueError, IndexError):
        return default
    if len(value) == 5 and value[2] == ":" and 0 <= hour <= 23 and 0 <= minute <= 59:
        return value
    return default


def _flag(name: str) -> bool:
    import os

    return os.environ.get(name, "false").lower() in {"1", "true", "yes", "on"}


def upgrade() -> None:
    connection = op.get_bind()

    Base.metadata.create_all(bind=connection, tables=_runtime_tables(), checkfirst=False)

    # Function and trigger bodies contain ``::`` casts, ``%s`` format
    # placeholders, and clock literals. ``sa.text`` would read parts of them as
    # bind parameters, so this DDL goes straight to the driver.
    for function in _FUNCTIONS:
        connection.exec_driver_sql(function)

    for name, table, event, when, message in _ALL_GUARDS:
        function, trigger = _guard(name, table, event, when, message)
        connection.exec_driver_sql(function)
        connection.exec_driver_sql(trigger)

    for name, table, event, when, body in _PROJECTION_EFFECTS:
        function, trigger = _effect(name, table, event, when, body)
        connection.exec_driver_sql(function)
        connection.exec_driver_sql(trigger)

    # Schedule and always-on singletons. A fresh database gets the operator
    # defaults with always-on off; policy and portal rows stay empty and need
    # an explicit seed command.
    connection.execute(
        sa.text(
            f"INSERT INTO {SCHEMA}.schedule_setting"
            " (singleton_id, timezone, daily_time, weekly_time, prespec_enabled,"
            "  updated_at, updated_by)"
            " VALUES (1, 'Asia/Seoul', :daily, :weekly, :prespec,"
            "         CURRENT_TIMESTAMP, 'system:migration')"
        ),
        {
            "daily": _time_value("BIDOPS_SCHEDULE_DAILY_TIME", "02:00"),
            "weekly": _time_value("BIDOPS_SCHEDULE_WEEKLY_TIME", "06:00"),
            "prespec": _flag("BIDOPS_PRESPEC_ENABLED"),
        },
    )
    connection.execute(
        sa.text(
            f"INSERT INTO {SCHEMA}.always_on_state"
            " (singleton_id, enabled, updated_at, updated_by)"
            " VALUES (1, false, CURRENT_TIMESTAMP, 'system:migration')"
        )
    )

    # A deterministic marker so a fresh database and an upgraded Lean v1
    # database carry the same auditable migration record.
    connection.execute(
        sa.text(
            f"INSERT INTO {SCHEMA}.screening_audit_event"
            " (event_id, event_type, actor, target_type, target_id, occurred_at, details_json)"
            " VALUES (:event_id, 'db.migration', 'system:migration', 'database',"
            "         :revision, CAST(:occurred_at AS timestamptz), CAST(:details AS json))"
            " ON CONFLICT (event_id) DO NOTHING"
        ),
        {
            "event_id": _EVENT_ID,
            "revision": revision,
            "occurred_at": "2026-01-01 00:00:00+00",
            "details": _DETAILS,
        },
    )


def downgrade() -> None:
    connection = op.get_bind()

    for name, table, *_ in reversed(_PROJECTION_EFFECTS):
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {SCHEMA}.{table}")
        connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS {SCHEMA}.tf_{name}()")
    for name, table, *_ in reversed(_ALL_GUARDS):
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {SCHEMA}.{table}")
        connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS {SCHEMA}.tf_{name}()")
    for signature in _FUNCTION_SIGNATURES:
        connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS {SCHEMA}.{signature}")

    # The runtime deliberately participates in a FK cycle (policy ->
    # evaluation -> gate -> execution -> policy). PostgreSQL can drop this
    # subgraph transactionally with CASCADE, while SQLAlchemy's dependency
    # sorter cannot order unnamed single-column FKs in a cycle.
    for table in reversed(SCREENING_RUNTIME_TABLES):
        connection.exec_driver_sql(f"DROP TABLE IF EXISTS {SCHEMA}.{table} CASCADE")
