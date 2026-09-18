"""C-2 품질 게이트·감사 표본·일일 스위치 저장소와 실행 용도를 더한다.

Revision ID: 0029_c2_quality_gate
Revises: 0028_final_decision_basis

일일 운영 고도화 명세(``docs/0918_daily-operation/spec.md`` §2)의 구조만 만든다.

- 신규 4테이블: ``order_plan_screening_quality_gate``,
  ``order_plan_screening_quality_evaluation``, ``order_plan_screening_audit_sample``,
  ``order_plan_screening_daily_trigger``. 넷 다 UPDATE·DELETE를 거부한다(gate는
  payload·digest immutable, 나머지는 append-only).
- evaluation BEFORE INSERT trigger가 gate 행의 임계값 4개를 읽어, 하나라도 NULL이면
  ``result_status='미측정'``만 받는다. 두 테이블에 걸친 규칙이라 CHECK로 쓰지 못한다.
- ``order_plan_screening_execution.purpose``(``operational`` | ``gate_measurement``).
  ``ADD COLUMN ... DEFAULT``가 기존 행을 ``operational``로 채우므로 execution guard
  trigger가 발동하지 않는다. 값은 INSERT 때만 정하고 이후 UPDATE를 거부한다.
- policy guard가 ``quality_gate_status`` 변경을 전부 막고 있었으므로, 활성화 전이
  (``activation_candidate`` → ``active``)에서 ``passed``로 쓰는 것만 허용하도록 다시
  만든다(명세 §3.3 9번). 그 밖의 payload 불변 조건은 0016 그대로다.

값·서비스·REST는 만들지 않는다. 임계값은 NULL로 남는다. 권한은
``scripts/runtime-privileges.sql``이 migration 뒤에 적용한다.
"""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0029_c2_quality_gate"
down_revision = "0028_final_decision_basis"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
_MIGRATION_EVENT_ID = "audit-" + uuid5(NAMESPACE_URL, "bidops:db.migration:" + revision).hex

GATE = "order_plan_screening_quality_gate"
EVALUATION = "order_plan_screening_quality_evaluation"
AUDIT_SAMPLE = "order_plan_screening_audit_sample"
DAILY_TRIGGER = "order_plan_screening_daily_trigger"
NEW_TABLES = (GATE, EVALUATION, AUDIT_SAMPLE, DAILY_TRIGGER)
EXECUTION = "order_plan_screening_execution"

_HEX64 = "{column} ~ '^[0-9a-f]{{64}}$'"


def _hex64(*columns: str) -> str:
    return " AND ".join(_HEX64.format(column=column) for column in columns)


def _pct(column: str) -> str:
    return f"{column} IS NULL OR ({column} >= 0 AND {column} <= 100)"


def _create_tables() -> None:
    op.create_table(
        GATE,
        sa.Column("gate_id", sa.String(length=39), primary_key=True),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("gold_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("gold_artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("gold_status", sa.String(length=32), nullable=False),
        sa.Column("scoring_input_sha256", sa.String(length=64), nullable=False),
        sa.Column("evaluation_basis", sa.String(length=32), nullable=False),
        sa.Column("scoring_unit", sa.String(length=32), nullable=False),
        sa.Column("measurement_run_ids_json", JSONB, nullable=False),
        sa.Column("required_pass_count", sa.Integer(), nullable=False),
        sa.Column("threshold_recall_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("threshold_precision_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("threshold_important_missed_max", sa.Integer(), nullable=True),
        sa.Column("threshold_review_load_max", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_version"], [f"{SCHEMA}.order_plan_screening_policy.policy_version"],
            name="fk_order_plan_screening_quality_gate_policy", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "gate_id ~ '^c2gate-[0-9a-f]{32}$'", name="ck_order_plan_screening_quality_gate_id"
        ),
        sa.CheckConstraint(
            _hex64(
                "policy_sha256", "binding_sha256", "gold_manifest_sha256",
                "gold_artifact_sha256", "scoring_input_sha256",
            ),
            name="ck_order_plan_screening_quality_gate_hashes",
        ),
        sa.CheckConstraint(
            "evaluation_basis IN ('product_rerun','reference_artifact_rescore')",
            name="ck_order_plan_screening_quality_gate_basis",
        ),
        sa.CheckConstraint(
            "scoring_unit = 'per_published_day'",
            name="ck_order_plan_screening_quality_gate_scoring_unit",
        ),
        sa.CheckConstraint(
            "required_pass_count = 2", name="ck_order_plan_screening_quality_gate_pass_count"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(measurement_run_ids_json) = 'array'",
            name="ck_order_plan_screening_quality_gate_run_ids",
        ),
        sa.CheckConstraint(
            f"({_pct('threshold_recall_pct')}) AND ({_pct('threshold_precision_pct')}) "
            "AND (threshold_important_missed_max IS NULL OR threshold_important_missed_max >= 0) "
            "AND (threshold_review_load_max IS NULL OR threshold_review_load_max >= 0)",
            name="ck_order_plan_screening_quality_gate_thresholds",
        ),
        sa.CheckConstraint(
            "length(trim(gold_status)) > 0 AND length(trim(created_by)) > 0",
            name="ck_order_plan_screening_quality_gate_strings",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        EVALUATION,
        sa.Column("evaluation_id", sa.String(length=43), primary_key=True),
        sa.Column("gate_id", sa.String(length=39), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("result_status", sa.String(length=16), nullable=False),
        sa.Column("pass_execution_ids_json", JSONB, nullable=False),
        sa.Column("measured_recall_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("measured_precision_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("measured_important_missed", sa.Integer(), nullable=True),
        sa.Column("measured_review_load", sa.Integer(), nullable=True),
        sa.Column("metrics_json", JSONB, nullable=False),
        sa.Column("reasons_json", JSONB, nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("evaluated_by", sa.String(length=128), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("gate_id", "revision", name="uq_order_plan_screening_quality_evaluation_revision"),
        sa.ForeignKeyConstraint(
            ["gate_id"], [f"{SCHEMA}.{GATE}.gate_id"],
            name="fk_order_plan_screening_quality_evaluation_gate", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "evaluation_id ~ '^c2gateeval-[0-9a-f]{32}$'",
            name="ck_order_plan_screening_quality_evaluation_id",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_order_plan_screening_quality_evaluation_revision"),
        sa.CheckConstraint(
            "result_status IN ('통과','미달','미측정','보류')",
            name="ck_order_plan_screening_quality_evaluation_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(pass_execution_ids_json) = 'object' "
            "AND jsonb_typeof(metrics_json) = 'object' AND jsonb_typeof(reasons_json) = 'array'",
            name="ck_order_plan_screening_quality_evaluation_json",
        ),
        sa.CheckConstraint(
            f"({_pct('measured_recall_pct')}) AND ({_pct('measured_precision_pct')}) "
            "AND (measured_important_missed IS NULL OR measured_important_missed >= 0) "
            "AND (measured_review_load IS NULL OR measured_review_load >= 0)",
            name="ck_order_plan_screening_quality_evaluation_measured",
        ),
        sa.CheckConstraint(
            _hex64("artifact_sha256"), name="ck_order_plan_screening_quality_evaluation_artifact"
        ),
        sa.CheckConstraint(
            "length(trim(evaluated_by)) > 0", name="ck_order_plan_screening_quality_evaluation_strings"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        AUDIT_SAMPLE,
        sa.Column("id", UUID, primary_key=True),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("order_plan_id", sa.Integer(), nullable=False),
        sa.Column("stratum", sa.String(length=48), nullable=False),
        sa.Column("selection_rank", sa.Integer(), nullable=False),
        sa.Column("plan_id_sha256", sa.String(length=64), nullable=False),
        sa.Column("filtered_out_count", sa.Integer(), nullable=False),
        sa.Column("max_per_execution", sa.Integer(), nullable=False),
        sa.Column("review_cadence", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("drawn_by", sa.String(length=128), nullable=False),
        sa.Column("drawn_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("execution_id", "order_plan_id", name="uq_order_plan_screening_audit_sample_plan"),
        sa.ForeignKeyConstraint(
            ["execution_id"], [f"{SCHEMA}.{EXECUTION}.execution_id"],
            name="fk_order_plan_screening_audit_sample_execution", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_plan_id"], [f"{SCHEMA}.order_plan.id"],
            name="fk_order_plan_screening_audit_sample_order_plan", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "stratum IN ('classification_proximity','performance_similarity_proximity','uniform_hash')",
            name="ck_order_plan_screening_audit_sample_stratum",
        ),
        sa.CheckConstraint(
            "selection_rank >= 1 AND filtered_out_count >= 0 AND max_per_execution >= 1",
            name="ck_order_plan_screening_audit_sample_numbers",
        ),
        sa.CheckConstraint(
            _hex64("plan_id_sha256", "policy_sha256"),
            name="ck_order_plan_screening_audit_sample_hashes",
        ),
        sa.CheckConstraint(
            "length(trim(review_cadence)) > 0 AND length(trim(policy_version)) > 0 "
            "AND length(trim(drawn_by)) > 0",
            name="ck_order_plan_screening_audit_sample_strings",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        DAILY_TRIGGER,
        sa.Column("id", UUID, primary_key=True),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("set_by", sa.String(length=128), nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", UUID, nullable=False),
        sa.UniqueConstraint("request_id", name="uq_order_plan_screening_daily_trigger_request"),
        sa.ForeignKeyConstraint(
            ["policy_version"], [f"{SCHEMA}.order_plan_screening_policy.policy_version"],
            name="fk_order_plan_screening_daily_trigger_policy", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            _hex64("policy_sha256"), name="ck_order_plan_screening_daily_trigger_policy_sha256"
        ),
        sa.CheckConstraint(
            "length(trim(set_by)) > 0 AND (reason IS NULL OR length(trim(reason)) > 0)",
            name="ck_order_plan_screening_daily_trigger_strings",
        ),
        schema=SCHEMA,
    )
    # 스위치의 현재 값 = 그 policy_version의 최신 행(명세 §2.1).
    op.create_index(
        "ix_order_plan_screening_daily_trigger_latest",
        DAILY_TRIGGER,
        ["policy_version", "set_at"],
        schema=SCHEMA,
    )


def _add_execution_purpose() -> None:
    op.add_column(
        EXECUTION,
        sa.Column(
            "purpose",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'operational'"),
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_order_plan_screening_execution_purpose",
        EXECUTION,
        "purpose IN ('operational','gate_measurement')",
        schema=SCHEMA,
    )


def _create_guards() -> None:
    bind = op.get_bind()
    for table in NEW_TABLES:
        bind.exec_driver_sql(
            f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.tf_{table}_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '{table} is append-only' USING ERRCODE = 'check_violation';
END;
$$;
CREATE TRIGGER tr_{table}_append_only
BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_{table}_append_only();
"""
        )
    bind.exec_driver_sql(
        f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.tf_{EVALUATION}_thresholds() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    undecided boolean;
BEGIN
    SELECT (threshold_recall_pct IS NULL
            OR threshold_precision_pct IS NULL
            OR threshold_important_missed_max IS NULL
            OR threshold_review_load_max IS NULL)
      INTO undecided
      FROM {SCHEMA}.{GATE}
     WHERE gate_id = NEW.gate_id;
    -- 없는 gate는 FK가 거부한다.
    IF undecided AND NEW.result_status <> '미측정'
    THEN RAISE EXCEPTION 'quality gate thresholds are undecided; only 미측정 is allowed'
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_{EVALUATION}_thresholds
BEFORE INSERT ON {SCHEMA}.{EVALUATION}
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_{EVALUATION}_thresholds();

CREATE OR REPLACE FUNCTION {SCHEMA}.tf_{EXECUTION}_purpose_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.purpose IS DISTINCT FROM OLD.purpose
    THEN RAISE EXCEPTION 'order_plan_screening_execution purpose is immutable'
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_{EXECUTION}_purpose_guard
BEFORE UPDATE OF purpose ON {SCHEMA}.{EXECUTION}
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_{EXECUTION}_purpose_guard();
"""
    )


def _policy_guard_sql(*, allow_gate_status_on_activation: bool) -> str:
    """0016의 policy guard 본문. 0029는 ``quality_gate_status`` 한 줄만 바꾼다."""

    gate_status_immutable = (
        "" if allow_gate_status_on_activation
        else "       OR NEW.quality_gate_status IS DISTINCT FROM OLD.quality_gate_status\n"
    )
    gate_status_on_activation = (
        """    IF NEW.quality_gate_status IS DISTINCT FROM OLD.quality_gate_status
       AND NOT (OLD.policy_status = 'activation_candidate'
                AND NEW.policy_status = 'active'
                AND NEW.quality_gate_status = 'passed')
    THEN RAISE EXCEPTION 'order_plan_screening_policy quality_gate_status is written only on activation' USING ERRCODE = 'check_violation';
    END IF;
"""
        if allow_gate_status_on_activation
        else ""
    )
    return f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.tf_order_plan_screening_policy_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
       OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
       OR NEW.producer IS DISTINCT FROM OLD.producer
       OR NEW.consumer IS DISTINCT FROM OLD.consumer
       OR NEW.decision_scope IS DISTINCT FROM OLD.decision_scope
       OR NEW.policy_payload_jsonb IS DISTINCT FROM OLD.policy_payload_jsonb
       OR NEW.binding_payload_jsonb IS DISTINCT FROM OLD.binding_payload_jsonb
       OR NEW.policy_sha256 IS DISTINCT FROM OLD.policy_sha256
       OR NEW.binding_sha256 IS DISTINCT FROM OLD.binding_sha256
       OR NEW.activation_metadata_jsonb IS DISTINCT FROM OLD.activation_metadata_jsonb
{gate_status_immutable}       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN RAISE EXCEPTION 'order_plan_screening_policy payload is immutable' USING ERRCODE = 'check_violation';
    END IF;
{gate_status_on_activation}    IF OLD.policy_status IS NOT DISTINCT FROM NEW.policy_status
       AND (NEW.active_slot IS DISTINCT FROM OLD.active_slot
            OR NEW.activated_by IS DISTINCT FROM OLD.activated_by
            OR NEW.activated_at IS DISTINCT FROM OLD.activated_at)
    THEN RAISE EXCEPTION 'order_plan_screening_policy activation metadata requires a status transition' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.policy_status IS DISTINCT FROM NEW.policy_status
       AND NOT ((OLD.policy_status = 'draft' AND NEW.policy_status = 'activation_candidate')
                OR (OLD.policy_status = 'activation_candidate' AND NEW.policy_status = 'active')
                OR (OLD.policy_status = 'active' AND NEW.policy_status = 'retired'))
    THEN RAISE EXCEPTION 'invalid order plan screening policy status transition' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.policy_status = 'draft' AND NEW.policy_status = 'activation_candidate'
       AND (NEW.active_slot IS NOT NULL OR NEW.activated_by IS NOT NULL OR NEW.activated_at IS NOT NULL)
    THEN RAISE EXCEPTION 'policy activation metadata is premature' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.policy_status = 'activation_candidate' AND NEW.policy_status = 'active'
       AND (NEW.active_slot IS DISTINCT FROM 1 OR NEW.activated_by IS NULL OR NEW.activated_at IS NULL)
    THEN RAISE EXCEPTION 'active policy requires activation metadata' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.policy_status = 'active' AND NEW.policy_status = 'retired'
       AND (NEW.active_slot IS NOT NULL
            OR NEW.activated_by IS DISTINCT FROM OLD.activated_by
            OR NEW.activated_at IS DISTINCT FROM OLD.activated_at)
    THEN RAISE EXCEPTION 'retired policy must retain activation provenance' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""


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
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
            "occurred_at": "2026-01-01 00:00:29+00",
        },
    )


def upgrade() -> None:
    _create_tables()
    _add_execution_purpose()
    _create_guards()
    op.get_bind().exec_driver_sql(_policy_guard_sql(allow_gate_status_on_activation=True))
    _record_migration_marker()


def _assert_nothing_to_discard() -> None:
    bind = op.get_bind()
    nonempty = [
        table for table in NEW_TABLES
        if bind.execute(sa.text(f"SELECT 1 FROM {SCHEMA}.{table} LIMIT 1")).first()
    ]
    if bind.execute(
        sa.text(f"SELECT 1 FROM {SCHEMA}.{EXECUTION} WHERE purpose <> 'operational' LIMIT 1")
    ).first():
        nonempty.append(f"{EXECUTION}.purpose")
    if nonempty:
        raise RuntimeError(
            "0029 downgrade is blocked while C-2 gate rows exist: " + ", ".join(nonempty)
        )
    # 0016 guard는 quality_gate_status 변경을 모른다. 0029에서만 생길 수 있는 값을
    # 남긴 채 되돌리면 되돌린 guard가 그 행을 설명하지 못한다.
    if bind.execute(
        sa.text(
            f"SELECT 1 FROM {SCHEMA}.order_plan_screening_policy "
            "WHERE quality_gate_status = 'passed' LIMIT 1"
        )
    ).first():
        raise RuntimeError(
            "0029 downgrade is blocked while a C-2 policy records quality_gate_status='passed'"
        )


def downgrade() -> None:
    _assert_nothing_to_discard()
    bind = op.get_bind()
    bind.exec_driver_sql(_policy_guard_sql(allow_gate_status_on_activation=False))
    bind.exec_driver_sql(
        f"DROP TRIGGER IF EXISTS tr_{EXECUTION}_purpose_guard ON {SCHEMA}.{EXECUTION}"
    )
    bind.exec_driver_sql(f"DROP FUNCTION IF EXISTS {SCHEMA}.tf_{EXECUTION}_purpose_guard()")
    bind.exec_driver_sql(
        f"DROP TRIGGER IF EXISTS tr_{EVALUATION}_thresholds ON {SCHEMA}.{EVALUATION}"
    )
    bind.exec_driver_sql(f"DROP FUNCTION IF EXISTS {SCHEMA}.tf_{EVALUATION}_thresholds()")
    for table in reversed(NEW_TABLES):
        bind.exec_driver_sql(
            f"DROP TRIGGER IF EXISTS tr_{table}_append_only ON {SCHEMA}.{table}"
        )
        bind.exec_driver_sql(f"DROP FUNCTION IF EXISTS {SCHEMA}.tf_{table}_append_only()")
    op.drop_index(
        "ix_order_plan_screening_daily_trigger_latest", table_name=DAILY_TRIGGER, schema=SCHEMA
    )
    for table in reversed(NEW_TABLES):
        op.drop_table(table, schema=SCHEMA)
    op.drop_constraint(
        "ck_order_plan_screening_execution_purpose", EXECUTION, type_="check", schema=SCHEMA
    )
    op.drop_column(EXECUTION, "purpose", schema=SCHEMA)
    bind.execute(
        sa.text(f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"),
        {"event_id": _MIGRATION_EVENT_ID},
    )
