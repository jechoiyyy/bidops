"""Add the immutable C-2 order-plan screening storage boundary.

Revision ID: 0016_order_plan_screening
Revises: 0015_bid_delta_final_decision

This migration stores already-produced, strictly validated Phase 1 artifacts.
It does not seed a policy, enqueue work, or contact a model provider.
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_order_plan_screening"
down_revision = "0015_bid_delta_final_decision"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
MIGRATION_EVENT_ID = "audit-2c7f4e1a9b305d6e8f0123456789abcd"


def _create_tables() -> None:
    op.create_table(
        "order_plan_screening_policy",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("producer", sa.String(length=128), nullable=False),
        sa.Column("consumer", sa.String(length=128), nullable=False),
        sa.Column("policy_status", sa.String(length=32), nullable=False),
        sa.Column("decision_scope", sa.String(length=64), nullable=False),
        sa.Column("policy_payload_jsonb", JSONB, nullable=False),
        sa.Column("binding_payload_jsonb", JSONB, nullable=False),
        sa.Column("policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("activation_metadata_jsonb", JSONB, nullable=False),
        sa.Column("quality_gate_status", sa.String(length=32), nullable=True),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_by", sa.String(length=128), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("policy_version", name="uq_order_plan_screening_policy_version"),
        sa.CheckConstraint(
            "schema_version = 'bidops.order-plan-screening-policy.v1'",
            name="ck_order_plan_screening_policy_schema_version",
        ),
        sa.CheckConstraint(
            "producer = 'phase0-contracts' AND consumer = 'phase1-screening-pipeline'",
            name="ck_order_plan_screening_policy_provenance",
        ),
        sa.CheckConstraint(
            "policy_status IN ('draft','activation_candidate','active','retired')",
            name="ck_order_plan_screening_policy_status",
        ),
        sa.CheckConstraint(
            "decision_scope = 'c2_order_plan_first_pass'",
            name="ck_order_plan_screening_policy_scope",
        ),
        sa.CheckConstraint(
            "policy_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_order_plan_screening_policy_sha256",
        ),
        sa.CheckConstraint(
            "binding_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_order_plan_screening_policy_binding_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(policy_payload_jsonb) = 'object'",
            name="ck_order_plan_screening_policy_payload_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(binding_payload_jsonb) = 'object'",
            name="ck_order_plan_screening_policy_binding_object",
        ),
        sa.CheckConstraint(
            "((policy_status = 'active' AND active_slot = 1 AND activated_at IS NOT NULL AND activated_by IS NOT NULL AND length(trim(activated_by)) > 0) OR (policy_status <> 'active' AND active_slot IS NULL))",
            name="ck_order_plan_screening_policy_active_metadata",
        ),
        sa.CheckConstraint(
            "quality_gate_status IS NULL OR quality_gate_status IN ('not_measured','measured','passed','failed')",
            name="ck_order_plan_screening_policy_quality_gate_status",
        ),
        sa.CheckConstraint(
            "length(trim(policy_version)) > 0 AND length(trim(created_by)) > 0",
            name="ck_order_plan_screening_policy_strings",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "order_plan_screening_execution",
        sa.Column("execution_id", UUID, primary_key=True),
        sa.Column("request_id", UUID, nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("producer", sa.String(length=128), nullable=False),
        sa.Column("consumer", sa.String(length=128), nullable=False),
        sa.Column("source_run_id", sa.String(length=160), nullable=False),
        sa.Column("source_artifact_name", sa.String(length=255), nullable=False),
        sa.Column("source_artifact_schema_version", sa.String(length=64), nullable=False),
        sa.Column("source_artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("population_count", sa.Integer(), nullable=False),
        sa.Column("population_sha256", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("stage1_binding_version", sa.String(length=128), nullable=False),
        sa.Column("stage1_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("stage2_binding_version", sa.String(length=128), nullable=False),
        sa.Column("stage2_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("partial_artifact", sa.Boolean(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("stage1_selected_count", sa.Integer(), nullable=False),
        sa.Column("stage1_filtered_out_count", sa.Integer(), nullable=False),
        sa.Column("stage1_failed_count", sa.Integer(), nullable=False),
        sa.Column("stage2_relevant_count", sa.Integer(), nullable=False),
        sa.Column("stage2_not_relevant_count", sa.Integer(), nullable=False),
        sa.Column("stage2_uncertain_count", sa.Integer(), nullable=False),
        sa.Column("stage2_failed_count", sa.Integer(), nullable=False),
        sa.Column("stage2_rejected_count", sa.Integer(), nullable=False),
        sa.Column("human_review_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_order_plan_screening_execution_request"),
        sa.ForeignKeyConstraint(
            ["source_run_id"], [f"{SCHEMA}.run.id"],
            name="fk_order_plan_screening_execution_source_run", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_version"], [f"{SCHEMA}.order_plan_screening_policy.policy_version"],
            name="fk_order_plan_screening_execution_policy", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "schema_version = 'bidops.order-plan-screening-execution-row.v1'",
            name="ck_order_plan_screening_execution_schema_version",
        ),
        sa.CheckConstraint(
            "producer = 'screening-api' AND consumer = 'screening-worker-and-review-api'",
            name="ck_order_plan_screening_execution_provenance",
        ),
        sa.CheckConstraint(
            "status IN ('대기','실행 중','중지 요청','성공','부분 성공','실패','중단됨')",
            name="ck_order_plan_screening_execution_status",
        ),
        sa.CheckConstraint(
            "((status IN ('실행 중','중지 요청') AND active_slot = 1) OR (status NOT IN ('실행 중','중지 요청') AND active_slot IS NULL))",
            name="ck_order_plan_screening_execution_active_slot",
        ),
        sa.CheckConstraint(
            "((status IN ('성공','부분 성공','실패','중단됨') AND started_at IS NOT NULL AND finished_at IS NOT NULL) OR (status IN ('실행 중','중지 요청') AND started_at IS NOT NULL AND finished_at IS NULL) OR (status = '대기' AND started_at IS NULL AND finished_at IS NULL))",
            name="ck_order_plan_screening_execution_lifecycle",
        ),
        sa.CheckConstraint(
            "population_count >= 1 AND population_sha256 IS NOT NULL",
            name="ck_order_plan_screening_execution_population",
        ),
        sa.CheckConstraint(
            "candidate_count >= 0 AND completed_count >= 0 AND failure_count >= 0 AND stage1_selected_count >= 0 AND stage1_filtered_out_count >= 0 AND stage1_failed_count >= 0 AND stage2_relevant_count >= 0 AND stage2_not_relevant_count >= 0 AND stage2_uncertain_count >= 0 AND stage2_failed_count >= 0 AND stage2_rejected_count >= 0 AND human_review_count >= 0",
            name="ck_order_plan_screening_execution_counts",
        ),
        sa.CheckConstraint("source_artifact_sha256 ~ '^[0-9a-f]{64}$'", name="ck_order_plan_screening_execution_source_sha256"),
        sa.CheckConstraint("input_artifact_sha256 ~ '^[0-9a-f]{64}$'", name="ck_order_plan_screening_execution_input_sha256"),
        sa.CheckConstraint("population_sha256 ~ '^[0-9a-f]{64}$'", name="ck_order_plan_screening_execution_population_sha256"),
        sa.CheckConstraint("policy_sha256 ~ '^[0-9a-f]{64}$'", name="ck_order_plan_screening_execution_policy_sha256"),
        sa.CheckConstraint("binding_sha256 ~ '^[0-9a-f]{64}$'", name="ck_order_plan_screening_execution_binding_sha256"),
        sa.CheckConstraint(
            "length(trim(source_artifact_name)) > 0 AND source_artifact_name NOT LIKE '/%' AND position(chr(92) in source_artifact_name) = 0 AND source_artifact_name <> '..' AND source_artifact_name NOT LIKE '../%' AND source_artifact_name NOT LIKE '%/../%' AND source_artifact_name NOT LIKE '%/..'",
            name="ck_order_plan_screening_execution_source_artifact_name",
        ),
        sa.CheckConstraint(
            "length(trim(requested_by)) > 0 AND length(trim(policy_version)) > 0 AND length(trim(stage1_binding_version)) > 0 AND length(trim(stage2_binding_version)) > 0",
            name="ck_order_plan_screening_execution_strings",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "order_plan_screening_batch_attempt",
        sa.Column("attempt_id", UUID, primary_key=True),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("batch_id", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("producer", sa.String(length=128), nullable=False),
        sa.Column("consumer", sa.String(length=128), nullable=False),
        sa.Column("plan_count", sa.Integer(), nullable=False),
        sa.Column("plan_ids_jsonb", JSONB, nullable=False),
        sa.Column("plan_ids_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("model_digest", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("company_profile_version", sa.String(length=128), nullable=False),
        sa.Column("company_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("generation_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("attempt_status", sa.String(length=16), nullable=False),
        sa.Column("failure_type", sa.String(length=32), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("response_object_ref", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("execution_id", "batch_id", "attempt_no", name="uq_order_plan_screening_batch_attempt_scope"),
        sa.ForeignKeyConstraint(
            ["execution_id"], [f"{SCHEMA}.order_plan_screening_execution.execution_id"],
            name="fk_order_plan_screening_batch_attempt_execution", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("schema_version = 'bidops.order-plan-screening-batch-attempt-row.v1'", name="ck_order_plan_screening_batch_attempt_schema_version"),
        sa.CheckConstraint("producer = 'screening-worker' AND consumer = 'screening-merge-and-observability'", name="ck_order_plan_screening_batch_attempt_provenance"),
        sa.CheckConstraint("sequence >= 1 AND attempt_no BETWEEN 1 AND 2 AND plan_count >= 1", name="ck_order_plan_screening_batch_attempt_numbers"),
        sa.CheckConstraint("attempt_status IN ('running','success','failed','rejected')", name="ck_order_plan_screening_batch_attempt_status"),
        sa.CheckConstraint("((attempt_status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR (attempt_status IN ('success','failed','rejected') AND finished_at IS NOT NULL))", name="ck_order_plan_screening_batch_attempt_lifecycle"),
        sa.CheckConstraint("failure_type IS NULL OR failure_type IN ('timeout','truncated_output','schema_violation','id_mismatch','model_mismatch','binding_mismatch','payload_not_approved','transport','policy_rejected','unknown')", name="ck_order_plan_screening_batch_attempt_failure_type"),
        sa.CheckConstraint("((attempt_status = 'success' AND failure_type IS NULL AND failure_code IS NULL) OR (attempt_status IN ('failed','rejected') AND failure_type IS NOT NULL AND failure_code IS NOT NULL AND length(trim(failure_code)) > 0) OR attempt_status = 'running')", name="ck_order_plan_screening_batch_attempt_failure_pair"),
        sa.CheckConstraint("plan_ids_jsonb IS NOT NULL", name="ck_order_plan_screening_batch_attempt_plan_ids_present"),
        sa.CheckConstraint("jsonb_typeof(plan_ids_jsonb) = 'array'", name="ck_order_plan_screening_batch_attempt_plan_ids_array"),
        sa.CheckConstraint("plan_ids_sha256 ~ '^[0-9a-f]{64}$'", name="ck_order_plan_screening_batch_attempt_plan_ids_sha256"),
        sa.CheckConstraint("model_digest ~ '^[0-9a-f]{64}$' AND prompt_sha256 ~ '^[0-9a-f]{64}$' AND company_profile_sha256 ~ '^[0-9a-f]{64}$' AND generation_config_sha256 ~ '^[0-9a-f]{64}$'", name="ck_order_plan_screening_batch_attempt_binding_sha256"),
        sa.CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_order_plan_screening_batch_attempt_input_tokens"),
        sa.CheckConstraint("cached_input_tokens IS NULL OR cached_input_tokens >= 0", name="ck_order_plan_screening_batch_attempt_cached_input_tokens"),
        sa.CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_order_plan_screening_batch_attempt_output_tokens"),
        sa.CheckConstraint("total_tokens IS NULL OR total_tokens >= 0", name="ck_order_plan_screening_batch_attempt_total_tokens"),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_order_plan_screening_batch_attempt_duration"),
        sa.CheckConstraint("length(trim(batch_id)) > 0 AND length(trim(model_name)) > 0 AND length(trim(prompt_version)) > 0 AND length(trim(company_profile_version)) > 0", name="ck_order_plan_screening_batch_attempt_strings"),
        schema=SCHEMA,
    )

    op.create_table(
        "order_plan_screening_result",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("source_run_id", sa.String(length=160), nullable=False),
        sa.Column("order_plan_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("producer", sa.String(length=128), nullable=False),
        sa.Column("consumer", sa.String(length=128), nullable=False),
        sa.Column("input_artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("stage1_rank", sa.Integer(), nullable=True),
        sa.Column("stage1_score", sa.Numeric(20, 10), nullable=True),
        sa.Column("nearest_capability", sa.Text(), nullable=True),
        sa.Column("stage1_status", sa.String(length=16), nullable=False),
        sa.Column("stage2_status", sa.String(length=16), nullable=False),
        sa.Column("qwen_relevance", sa.String(length=16), nullable=True),
        sa.Column("qwen_score", sa.Numeric(20, 10), nullable=True),
        sa.Column("qwen_reason", sa.String(length=500), nullable=True),
        sa.Column("batch_id", sa.String(length=128), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("execution_id", "order_plan_id", name="uq_order_plan_screening_result_plan"),
        sa.ForeignKeyConstraint(["execution_id"], [f"{SCHEMA}.order_plan_screening_execution.execution_id"], name="fk_order_plan_screening_result_execution", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_run_id"], [f"{SCHEMA}.run.id"], name="fk_order_plan_screening_result_source_run", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_plan_id"], [f"{SCHEMA}.order_plan.id"], name="fk_order_plan_screening_result_order_plan", ondelete="RESTRICT"),
        sa.CheckConstraint("schema_version = 'bidops.order-plan-screening-result-row.v1'", name="ck_order_plan_screening_result_schema_version"),
        sa.CheckConstraint("producer = 'order-plan-screening-merge' AND consumer = 'postgres-loader-and-review-api'", name="ck_order_plan_screening_result_provenance"),
        sa.CheckConstraint("stage1_status IN ('selected','filtered_out','failed','rejected')", name="ck_order_plan_screening_result_stage1_status"),
        sa.CheckConstraint("stage2_status IN ('not_attempted','success','failed','rejected','unknown')", name="ck_order_plan_screening_result_stage2_status"),
        sa.CheckConstraint("stage1_rank IS NULL OR stage1_rank >= 1", name="ck_order_plan_screening_result_stage1_rank"),
        sa.CheckConstraint("stage1_score IS NULL OR stage1_score >= 0", name="ck_order_plan_screening_result_stage1_score"),
        sa.CheckConstraint("qwen_score IS NULL OR (qwen_score >= 0 AND qwen_score <= 1)", name="ck_order_plan_screening_result_qwen_score"),
        sa.CheckConstraint("attempt_no IS NULL OR attempt_no BETWEEN 1 AND 2", name="ck_order_plan_screening_result_attempt_no"),
        sa.CheckConstraint("(batch_id IS NULL) = (attempt_no IS NULL)", name="ck_order_plan_screening_result_batch_attempt_pair"),
        sa.CheckConstraint("((stage1_status IN ('failed','rejected') AND stage1_rank IS NULL AND stage1_score IS NULL AND nearest_capability IS NULL AND stage2_status = 'not_attempted') OR (stage1_status = 'filtered_out' AND stage1_rank IS NOT NULL AND stage1_score IS NOT NULL AND stage2_status = 'not_attempted') OR (stage1_status = 'selected' AND stage1_rank IS NOT NULL AND stage1_score IS NOT NULL))", name="ck_order_plan_screening_result_stage1_fields"),
        sa.CheckConstraint("((stage2_status = 'not_attempted' AND qwen_relevance IS NULL AND qwen_score IS NULL AND qwen_reason IS NULL AND batch_id IS NULL AND attempt_no IS NULL AND failure_code IS NULL) OR (stage2_status = 'success' AND qwen_relevance IN ('relevant','not_relevant','uncertain') AND qwen_score IS NOT NULL AND qwen_reason IS NOT NULL AND length(trim(qwen_reason)) > 0 AND length(qwen_reason) <= 500 AND batch_id IS NOT NULL AND attempt_no IS NOT NULL AND failure_code IS NULL) OR (stage2_status IN ('failed','rejected','unknown') AND qwen_relevance IS NULL AND qwen_score IS NULL AND qwen_reason IS NULL AND failure_code IS NOT NULL AND length(trim(failure_code)) > 0))", name="ck_order_plan_screening_result_stage2_fields"),
        sa.CheckConstraint("input_artifact_sha256 ~ '^[0-9a-f]{64}$' AND policy_sha256 ~ '^[0-9a-f]{64}$' AND binding_sha256 ~ '^[0-9a-f]{64}$' AND result_sha256 ~ '^[0-9a-f]{64}$'", name="ck_order_plan_screening_result_hashes"),
        schema=SCHEMA,
    )

    op.create_table(
        "order_plan_screening_artifact",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("producer", sa.String(length=128), nullable=False),
        sa.Column("consumer", sa.String(length=128), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.Column("object_version", sa.String(length=255), nullable=True),
        sa.Column("validation_status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("execution_id", "kind", name="uq_order_plan_screening_artifact_kind"),
        sa.ForeignKeyConstraint(["execution_id"], [f"{SCHEMA}.order_plan_screening_execution.execution_id"], name="fk_order_plan_screening_artifact_execution", ondelete="RESTRICT"),
        sa.CheckConstraint("kind IN ('input','ranking','decisions','failures','telemetry','result','feedback')", name="ck_order_plan_screening_artifact_kind"),
        sa.CheckConstraint("validation_status IN ('pending','valid','invalid')", name="ck_order_plan_screening_artifact_validation_status"),
        sa.CheckConstraint("byte_count >= 0", name="ck_order_plan_screening_artifact_byte_count"),
        sa.CheckConstraint("schema_version IS NOT NULL AND length(trim(schema_version)) > 0 AND length(trim(producer)) > 0 AND length(trim(consumer)) > 0", name="ck_order_plan_screening_artifact_provenance"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_order_plan_screening_artifact_sha256"),
        schema=SCHEMA,
    )

    op.create_table(
        "order_plan_screening_feedback",
        sa.Column("feedback_id", UUID, primary_key=True),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("order_plan_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("producer", sa.String(length=128), nullable=False),
        sa.Column("consumer", sa.String(length=128), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("claimed_name", sa.String(length=128), nullable=False),
        sa.Column("relevance", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("supersedes_feedback_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("execution_id", "order_plan_id", "revision", name="uq_order_plan_screening_feedback_revision"),
        sa.ForeignKeyConstraint(["execution_id"], [f"{SCHEMA}.order_plan_screening_execution.execution_id"], name="fk_order_plan_screening_feedback_execution", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_plan_id"], [f"{SCHEMA}.order_plan.id"], name="fk_order_plan_screening_feedback_order_plan", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_feedback_id"], [f"{SCHEMA}.order_plan_screening_feedback.feedback_id"], name="fk_order_plan_screening_feedback_supersedes", ondelete="RESTRICT"),
        sa.CheckConstraint("schema_version = 'bidops.order-plan-screening-feedback.v1'", name="ck_order_plan_screening_feedback_schema_version"),
        sa.CheckConstraint("producer = 'human-review-api' AND consumer = 'postgres-review-history'", name="ck_order_plan_screening_feedback_provenance"),
        sa.CheckConstraint("actor_kind = 'human'", name="ck_order_plan_screening_feedback_actor_kind"),
        sa.CheckConstraint("relevance IN ('relevant','not_relevant','uncertain')", name="ck_order_plan_screening_feedback_relevance"),
        sa.CheckConstraint("priority IS NULL OR priority IN ('high','medium','low')", name="ck_order_plan_screening_feedback_priority"),
        sa.CheckConstraint("revision >= 1", name="ck_order_plan_screening_feedback_revision"),
        sa.CheckConstraint("length(trim(claimed_name)) > 0 AND (memo IS NULL OR length(trim(memo)) > 0)", name="ck_order_plan_screening_feedback_strings"),
        schema=SCHEMA,
    )


def _create_indexes() -> None:
    op.create_index(
        "uq_order_plan_screening_policy_active",
        "order_plan_screening_policy",
        ["active_slot"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("active_slot IS NOT NULL"),
    )
    op.create_index(
        "uq_order_plan_screening_execution_active",
        "order_plan_screening_execution",
        ["active_slot"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status IN ('실행 중', '중지 요청')"),
    )


def _create_guards() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        f"""
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
       OR NEW.quality_gate_status IS DISTINCT FROM OLD.quality_gate_status
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN RAISE EXCEPTION 'order_plan_screening_policy payload is immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.policy_status IS NOT DISTINCT FROM NEW.policy_status
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
CREATE TRIGGER tr_order_plan_screening_policy_guard
BEFORE UPDATE ON {SCHEMA}.order_plan_screening_policy
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_order_plan_screening_policy_guard();

CREATE OR REPLACE FUNCTION {SCHEMA}.tf_order_plan_screening_execution_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.execution_id IS DISTINCT FROM OLD.execution_id
       OR NEW.request_id IS DISTINCT FROM OLD.request_id
       OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
       OR NEW.producer IS DISTINCT FROM OLD.producer
       OR NEW.consumer IS DISTINCT FROM OLD.consumer
       OR NEW.source_run_id IS DISTINCT FROM OLD.source_run_id
       OR NEW.source_artifact_name IS DISTINCT FROM OLD.source_artifact_name
       OR NEW.source_artifact_schema_version IS DISTINCT FROM OLD.source_artifact_schema_version
       OR NEW.source_artifact_sha256 IS DISTINCT FROM OLD.source_artifact_sha256
       OR NEW.input_artifact_sha256 IS DISTINCT FROM OLD.input_artifact_sha256
       OR NEW.population_count IS DISTINCT FROM OLD.population_count
       OR NEW.population_sha256 IS DISTINCT FROM OLD.population_sha256
       OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
       OR NEW.policy_sha256 IS DISTINCT FROM OLD.policy_sha256
       OR NEW.binding_sha256 IS DISTINCT FROM OLD.binding_sha256
       OR NEW.stage1_binding_version IS DISTINCT FROM OLD.stage1_binding_version
       OR NEW.stage1_binding_sha256 IS DISTINCT FROM OLD.stage1_binding_sha256
       OR NEW.stage2_binding_version IS DISTINCT FROM OLD.stage2_binding_version
       OR NEW.stage2_binding_sha256 IS DISTINCT FROM OLD.stage2_binding_sha256
       OR NEW.requested_by IS DISTINCT FROM OLD.requested_by
       OR NEW.queued_at IS DISTINCT FROM OLD.queued_at
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN RAISE EXCEPTION 'order_plan_screening_execution source binding is immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status IS DISTINCT FROM NEW.status
       AND NOT ((OLD.status = '대기' AND NEW.status IN ('실행 중','중단됨'))
                OR (OLD.status = '실행 중' AND NEW.status IN ('중지 요청','성공','부분 성공','실패'))
                OR (OLD.status = '중지 요청' AND NEW.status = '중단됨'))
    THEN RAISE EXCEPTION 'invalid order plan screening execution status transition' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status IN ('성공','부분 성공','실패','중단됨')
       AND (NEW.status IS DISTINCT FROM OLD.status
            OR NEW.active_slot IS DISTINCT FROM OLD.active_slot
            OR NEW.partial_artifact IS DISTINCT FROM OLD.partial_artifact
            OR NEW.candidate_count IS DISTINCT FROM OLD.candidate_count
            OR NEW.completed_count IS DISTINCT FROM OLD.completed_count
            OR NEW.failure_count IS DISTINCT FROM OLD.failure_count
            OR NEW.stage1_selected_count IS DISTINCT FROM OLD.stage1_selected_count
            OR NEW.stage1_filtered_out_count IS DISTINCT FROM OLD.stage1_filtered_out_count
            OR NEW.stage1_failed_count IS DISTINCT FROM OLD.stage1_failed_count
            OR NEW.stage2_relevant_count IS DISTINCT FROM OLD.stage2_relevant_count
            OR NEW.stage2_not_relevant_count IS DISTINCT FROM OLD.stage2_not_relevant_count
            OR NEW.stage2_uncertain_count IS DISTINCT FROM OLD.stage2_uncertain_count
            OR NEW.stage2_failed_count IS DISTINCT FROM OLD.stage2_failed_count
            OR NEW.stage2_rejected_count IS DISTINCT FROM OLD.stage2_rejected_count
            OR NEW.human_review_count IS DISTINCT FROM OLD.human_review_count
            OR NEW.error_code IS DISTINCT FROM OLD.error_code
            OR NEW.started_at IS DISTINCT FROM OLD.started_at
            OR NEW.finished_at IS DISTINCT FROM OLD.finished_at)
    THEN RAISE EXCEPTION 'terminal order_plan_screening_execution is immutable' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_order_plan_screening_execution_guard
BEFORE UPDATE ON {SCHEMA}.order_plan_screening_execution
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_order_plan_screening_execution_guard();

CREATE OR REPLACE FUNCTION {SCHEMA}.tf_order_plan_screening_batch_attempt_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.attempt_id IS DISTINCT FROM OLD.attempt_id
       OR NEW.execution_id IS DISTINCT FROM OLD.execution_id
       OR NEW.batch_id IS DISTINCT FROM OLD.batch_id
       OR NEW.sequence IS DISTINCT FROM OLD.sequence
       OR NEW.attempt_no IS DISTINCT FROM OLD.attempt_no
       OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
       OR NEW.producer IS DISTINCT FROM OLD.producer
       OR NEW.consumer IS DISTINCT FROM OLD.consumer
       OR NEW.plan_count IS DISTINCT FROM OLD.plan_count
       OR NEW.plan_ids_jsonb IS DISTINCT FROM OLD.plan_ids_jsonb
       OR NEW.plan_ids_sha256 IS DISTINCT FROM OLD.plan_ids_sha256
       OR NEW.model_name IS DISTINCT FROM OLD.model_name
       OR NEW.model_digest IS DISTINCT FROM OLD.model_digest
       OR NEW.prompt_version IS DISTINCT FROM OLD.prompt_version
       OR NEW.prompt_sha256 IS DISTINCT FROM OLD.prompt_sha256
       OR NEW.company_profile_version IS DISTINCT FROM OLD.company_profile_version
       OR NEW.company_profile_sha256 IS DISTINCT FROM OLD.company_profile_sha256
       OR NEW.generation_config_sha256 IS DISTINCT FROM OLD.generation_config_sha256
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN RAISE EXCEPTION 'order_plan_screening_batch_attempt identity is immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.attempt_status <> 'running'
       OR NEW.attempt_status NOT IN ('success','failed','rejected')
    THEN RAISE EXCEPTION 'invalid order plan screening attempt transition' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_order_plan_screening_batch_attempt_guard
BEFORE UPDATE ON {SCHEMA}.order_plan_screening_batch_attempt
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_order_plan_screening_batch_attempt_guard();

CREATE OR REPLACE FUNCTION {SCHEMA}.tf_order_plan_screening_batch_attempt_audit() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO {SCHEMA}.audit_event
        (id, actor_kind, claimed_name, action, aggregate_type, aggregate_id,
         safe_metadata, request_id, created_at)
    VALUES
        (md5('c2-attempt:' || NEW.attempt_id::text || ':' || OLD.attempt_status || ':' || NEW.attempt_status)::uuid,
         'system', NULL, 'order_plan_screening_attempt_transition',
         'order_plan_screening_batch_attempt', NEW.attempt_id::text,
         jsonb_build_object('from_status', OLD.attempt_status,
                            'to_status', NEW.attempt_status,
                            'execution_id', NEW.execution_id::text,
                            'batch_id', NEW.batch_id,
                            'attempt_no', NEW.attempt_no),
         NEW.execution_id::text, now())
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_order_plan_screening_batch_attempt_audit
AFTER UPDATE ON {SCHEMA}.order_plan_screening_batch_attempt
FOR EACH ROW WHEN (OLD.attempt_status IS DISTINCT FROM NEW.attempt_status)
EXECUTE FUNCTION {SCHEMA}.tf_order_plan_screening_batch_attempt_audit();
"""
    )

    for table in (
        "order_plan_screening_result",
        "order_plan_screening_artifact",
        "order_plan_screening_feedback",
    ):
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
            "event_id": MIGRATION_EVENT_ID,
            "revision": revision,
            "occurred_at": "2026-01-01 00:00:16+00",
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
        },
    )


def upgrade() -> None:
    _create_tables()
    _create_indexes()
    _create_guards()
    _record_migration_marker()


def _assert_empty_before_downgrade() -> None:
    bind = op.get_bind()
    tables = (
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_result",
        "order_plan_screening_artifact",
        "order_plan_screening_feedback",
    )
    nonempty = [
        table for table in tables
        if bind.execute(sa.text(f"SELECT 1 FROM {SCHEMA}.{table} LIMIT 1")).first()
    ]
    if nonempty:
        raise RuntimeError(
            "0016 downgrade is blocked while C-2 rows exist: " + ", ".join(nonempty)
        )


def downgrade() -> None:
    _assert_empty_before_downgrade()
    bind = op.get_bind()
    for table in (
        "order_plan_screening_feedback",
        "order_plan_screening_artifact",
        "order_plan_screening_result",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_execution",
        "order_plan_screening_policy",
    ):
        bind.exec_driver_sql(
            f"DROP TRIGGER IF EXISTS tr_{table}_append_only ON {SCHEMA}.{table}"
        )
        if table in {"order_plan_screening_policy", "order_plan_screening_execution", "order_plan_screening_batch_attempt"}:
            bind.exec_driver_sql(
                f"DROP TRIGGER IF EXISTS tr_{table}_guard ON {SCHEMA}.{table}"
            )
        if table == "order_plan_screening_batch_attempt":
            bind.exec_driver_sql(
                f"DROP TRIGGER IF EXISTS tr_{table}_audit ON {SCHEMA}.{table}"
            )
    for function in (
        "tf_order_plan_screening_policy_guard",
        "tf_order_plan_screening_execution_guard",
        "tf_order_plan_screening_batch_attempt_guard",
        "tf_order_plan_screening_batch_attempt_audit",
        "tf_order_plan_screening_result_append_only",
        "tf_order_plan_screening_artifact_append_only",
        "tf_order_plan_screening_feedback_append_only",
    ):
        bind.exec_driver_sql(f"DROP FUNCTION IF EXISTS {SCHEMA}.{function}()")
    for table in (
        "order_plan_screening_feedback",
        "order_plan_screening_artifact",
        "order_plan_screening_result",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_execution",
        "order_plan_screening_policy",
    ):
        op.drop_table(table, schema=SCHEMA)
    bind.execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"
        ),
        {"event_id": MIGRATION_EVENT_ID},
    )
