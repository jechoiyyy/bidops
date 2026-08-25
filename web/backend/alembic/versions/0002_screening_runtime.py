"""Add the durable screening runtime and operational quality model."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0002_screening_runtime"
down_revision = "0001_existing_schema"
branch_labels = None
depends_on = None


def _time_value(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    try:
        hour, minute = int(value[:2]), int(value[3:])
        if len(value) == 5 and value[2] == ":" and 0 <= hour <= 23 and 0 <= minute <= 59:
            return value
    except (ValueError, IndexError):
        pass
    return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hex(column: str, length: int, prefix: str, name: str) -> sa.CheckConstraint:
    start = len(prefix) + 1
    return sa.CheckConstraint(
        f"length({column}) = {length} AND substr({column}, 1, {len(prefix)}) = '{prefix}' "
        f"AND substr({column}, {start}) NOT GLOB '*[^0-9a-f]*'",
        name=name,
    )


def upgrade() -> None:
    op.create_table(
        "company_profile_snapshot",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(512), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("version", name="uq_company_profile_snapshot_version"),
        sa.UniqueConstraint("artifact_path", name="uq_company_profile_snapshot_artifact_path"),
        sa.CheckConstraint("length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'", name="ck_profile_digest"),
        sa.CheckConstraint("version = 'company-profile.sha256:' || digest", name="ck_profile_version_digest"),
        sa.CheckConstraint("source_kind IN ('working_tree', 'git_blob')", name="ck_profile_source_kind"),
        sa.CheckConstraint("(source_kind = 'working_tree' AND length(trim(source_ref)) > 0 AND source_ref NOT LIKE '/%' AND source_ref NOT LIKE '%' || char(92) || '%' AND source_ref <> '..' AND source_ref NOT LIKE '../%' AND source_ref NOT LIKE '%/../%' AND source_ref NOT LIKE '%/..') OR (source_kind = 'git_blob' AND length(source_ref) = 40 AND source_ref NOT GLOB '*[^0-9a-f]*')", name="ck_profile_source_ref"),
        sa.CheckConstraint("artifact_path = 'web/data/profile-snapshots/' || digest || '.md'", name="ck_profile_artifact_path_exact"),
    )

    op.create_table(
        "screening_execution",
        sa.Column("queue_no", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.String(36), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("source_run_id", sa.String(160), sa.ForeignKey("run.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("notice_pk", sa.Integer(), sa.ForeignKey("notice.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("notice_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="대기"),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("policy_version", sa.String(255), sa.ForeignKey("screening_policy.policy_version", ondelete="RESTRICT"), nullable=False),
        sa.Column("prompt_version", sa.String(255), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("model_digest", sa.String(64), nullable=False),
        sa.Column("company_profile_version", sa.String(128), sa.ForeignKey("company_profile_snapshot.version", ondelete="RESTRICT"), nullable=False),
        sa.Column("company_profile_digest", sa.String(64), sa.ForeignKey("company_profile_snapshot.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("input_artifact_path", sa.Text(), nullable=False),
        sa.Column("input_artifact_digest", sa.String(64), nullable=False),
        sa.Column("artifact_dir", sa.Text(), nullable=False),
        sa.Column("current_notice_id", sa.String(255), nullable=True),
        sa.Column("current_stage", sa.String(64), nullable=True),
        sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_requested_by", sa.String(255), nullable=True),
        sa.Column("stop_reason", sa.String(32), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_run_id", sa.String(160), sa.ForeignKey("run.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.UniqueConstraint("execution_id", name="uq_screening_execution_id"),
        sa.UniqueConstraint("input_artifact_path", name="uq_screening_execution_input_artifact_path"),
        sa.UniqueConstraint("artifact_dir", name="uq_screening_execution_artifact_dir"),
        sa.UniqueConstraint("published_run_id", name="uq_screening_execution_published_run"),
        _hex("execution_id", 36, "scr-", "ck_screening_execution_id"),
        sa.CheckConstraint("trigger IN ('cli_single', 'manual_run', 'quality_gate', 'schedule')", name="ck_screening_execution_trigger"),
        sa.CheckConstraint("scope IN ('single_notice', 'full_run', 'quality_sample')", name="ck_screening_execution_scope"),
        sa.CheckConstraint("status IN ('대기', '실행 중', '중지 요청', '성공', '부분 성공', '실패', '중단됨')", name="ck_screening_execution_status"),
        sa.CheckConstraint("((scope = 'single_notice' AND notice_pk IS NOT NULL AND notice_id IS NOT NULL) OR (scope <> 'single_notice' AND notice_pk IS NULL AND notice_id IS NULL))", name="ck_screening_execution_single_notice"),
        sa.CheckConstraint("((status IN ('실행 중', '중지 요청') AND active_slot = 1) OR (status NOT IN ('실행 중', '중지 요청') AND active_slot IS NULL))", name="ck_screening_execution_active_slot"),
        sa.CheckConstraint("((status IN ('성공', '부분 성공', '실패', '중단됨') AND finished_at IS NOT NULL) OR (status NOT IN ('성공', '부분 성공', '실패', '중단됨') AND finished_at IS NULL))", name="ck_screening_execution_terminal"),
        sa.CheckConstraint("stop_reason IS NULL OR stop_reason IN ('user_requested', 'process_interrupted')", name="ck_screening_execution_stop_reason"),
        sa.CheckConstraint("length(trim(requested_by)) > 0", name="ck_screening_execution_requested_by"),
        sa.CheckConstraint("stop_requested_by IS NULL OR length(trim(stop_requested_by)) > 0", name="ck_screening_execution_stop_requested_by"),
        sa.CheckConstraint("length(trim(source_run_id)) > 0 AND length(trim(policy_version)) > 0 AND length(trim(prompt_version)) > 0 AND length(trim(model_name)) > 0 AND length(trim(company_profile_version)) > 0 AND (notice_id IS NULL OR length(trim(notice_id)) > 0) AND (current_notice_id IS NULL OR length(trim(current_notice_id)) > 0) AND (current_stage IS NULL OR length(trim(current_stage)) > 0) AND (stop_requested_by IS NULL OR length(trim(stop_requested_by)) > 0) AND (error_summary IS NULL OR length(trim(error_summary)) > 0)", name="ck_screening_execution_strings"),
        sa.CheckConstraint("candidate_count >= 0 AND completed_count >= 0 AND failure_count >= 0", name="ck_screening_execution_counts"),
        sa.CheckConstraint("length(model_digest) = 64 AND model_digest NOT GLOB '*[^0-9a-f]*'", name="ck_screening_execution_model_digest"),
        sa.CheckConstraint("length(company_profile_digest) = 64 AND company_profile_digest NOT GLOB '*[^0-9a-f]*'", name="ck_screening_execution_profile_digest"),
        sa.CheckConstraint("length(input_artifact_digest) = 64 AND input_artifact_digest NOT GLOB '*[^0-9a-f]*'", name="ck_screening_execution_input_artifact_digest"),
        sa.CheckConstraint("length(trim(input_artifact_path)) > 0", name="ck_screening_execution_input_artifact_nonempty"),
        sa.CheckConstraint("length(trim(artifact_dir)) > 0", name="ck_screening_execution_artifact_dir_nonempty"),
        sa.CheckConstraint("input_artifact_path NOT LIKE '/%' AND input_artifact_path NOT LIKE '%\\%' AND input_artifact_path <> '..' AND input_artifact_path NOT LIKE '../%' AND input_artifact_path NOT LIKE '%/../%' AND input_artifact_path NOT LIKE '%/..'", name="ck_screening_execution_input_artifact_path"),
        sa.CheckConstraint("artifact_dir NOT LIKE '/%' AND artifact_dir NOT LIKE '%\\%' AND artifact_dir <> '..' AND artifact_dir NOT LIKE '../%' AND artifact_dir NOT LIKE '%/../%' AND artifact_dir NOT LIKE '%/..'", name="ck_screening_execution_artifact_dir"),
    )
    op.create_index("uq_screening_execution_active_slot", "screening_execution", ["active_slot"], unique=True, sqlite_where=sa.text("active_slot IS NOT NULL"))

    op.create_table(
        "screening_attempt",
        sa.Column("attempt_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("screening_execution.execution_id", ondelete="CASCADE"), nullable=False),
        sa.Column("notice_id", sa.String(255), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_type", sa.String(32), nullable=True),
        sa.Column("trace_id", sa.String(255), nullable=False),
        sa.Column("span_id", sa.String(255), nullable=False),
        sa.Column("done_reason", sa.String(64), nullable=True),
        sa.Column("prompt_eval_count", sa.Integer(), nullable=True),
        sa.Column("eval_count", sa.Integer(), nullable=True),
        sa.Column("prompt_eval_duration_ns", sa.Integer(), nullable=True),
        sa.Column("eval_duration_ns", sa.Integer(), nullable=True),
        sa.Column("load_duration_ns", sa.Integer(), nullable=True),
        sa.Column("total_duration_ns", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_artifact_path", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.UniqueConstraint("execution_id", "notice_id", "stage", "attempt_no", name="uq_screening_attempt_number"),
        sa.UniqueConstraint("span_id", name="uq_screening_attempt_span"),
        sa.CheckConstraint("attempt_no >= 1", name="ck_screening_attempt_no"),
        sa.CheckConstraint("stage IN ('기술 적합성', '실적 정합성', '공공 SI 적합성', '사업성·자격 제약', '전략 부합', 'counterargument', 'synthesis', 'carried_over_validation')", name="ck_screening_attempt_stage"),
        sa.CheckConstraint("status IN ('success', 'failure')", name="ck_screening_attempt_status"),
        sa.CheckConstraint("failure_type IS NULL OR failure_type IN ('timeout', 'truncated_output', 'schema_violation', 'evidence_missing', 'counterargument_repetition')", name="ck_screening_attempt_failure_type"),
        sa.CheckConstraint("prompt_eval_count IS NULL OR prompt_eval_count >= 0", name="ck_screening_attempt_prompt_eval_count"),
        sa.CheckConstraint("eval_count IS NULL OR eval_count >= 0", name="ck_screening_attempt_eval_count"),
        sa.CheckConstraint("prompt_eval_duration_ns IS NULL OR prompt_eval_duration_ns >= 0", name="ck_screening_attempt_prompt_eval_duration_ns"),
        sa.CheckConstraint("eval_duration_ns IS NULL OR eval_duration_ns >= 0", name="ck_screening_attempt_eval_duration_ns"),
        sa.CheckConstraint("load_duration_ns IS NULL OR load_duration_ns >= 0", name="ck_screening_attempt_load_duration_ns"),
        sa.CheckConstraint("total_duration_ns IS NULL OR total_duration_ns >= 0", name="ck_screening_attempt_total_duration_ns"),
        sa.CheckConstraint("finished_at >= started_at", name="ck_screening_attempt_finished_after_started"),
        sa.CheckConstraint("length(trim(execution_id)) > 0 AND length(trim(notice_id)) > 0 AND length(trim(stage)) > 0 AND length(trim(status)) > 0 AND (failure_type IS NULL OR length(trim(failure_type)) > 0) AND length(trim(trace_id)) > 0 AND length(trim(span_id)) > 0 AND (done_reason IS NULL OR length(trim(done_reason)) > 0) AND (response_artifact_path IS NULL OR length(trim(response_artifact_path)) > 0) AND (error_summary IS NULL OR length(trim(error_summary)) > 0)", name="ck_screening_attempt_strings"),
        sa.CheckConstraint("response_artifact_path IS NULL OR (response_artifact_path NOT LIKE '/%' AND response_artifact_path NOT LIKE '%\\%' AND response_artifact_path <> '..' AND response_artifact_path NOT LIKE '../%' AND response_artifact_path NOT LIKE '%/../%' AND response_artifact_path NOT LIKE '%/..')", name="ck_screening_attempt_response_artifact_path"),
        sa.CheckConstraint("((status = 'success' AND response_artifact_path IS NOT NULL AND failure_type IS NULL) OR (status = 'failure' AND failure_type IS NOT NULL))", name="ck_screening_attempt_success_artifact"),
    )

    op.create_table(
        "quality_gate",
        sa.Column("gate_id", sa.String(37), primary_key=True),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("execution_status", sa.String(16), nullable=False),
        sa.Column("result_status", sa.String(16), nullable=False),
        sa.Column("baseline_run_id", sa.String(160), sa.ForeignKey("run.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sample_artifact_path", sa.Text(), nullable=False),
        sa.Column("sample_artifact_digest", sa.String(64), nullable=False),
        sa.Column("baseline_decisions_path", sa.Text(), nullable=False),
        sa.Column("baseline_decisions_digest", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(255), sa.ForeignKey("screening_policy.policy_version", ondelete="RESTRICT"), nullable=False),
        sa.Column("prompt_version", sa.String(255), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("model_digest", sa.String(64), nullable=False),
        sa.Column("company_profile_version", sa.String(128), sa.ForeignKey("company_profile_snapshot.version", ondelete="RESTRICT"), nullable=False),
        sa.Column("company_profile_digest", sa.String(64), sa.ForeignKey("company_profile_snapshot.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("pass_a_execution_id", sa.String(36), sa.ForeignKey("screening_execution.execution_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pass_b_execution_id", sa.String(36), sa.ForeignKey("screening_execution.execution_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("reasons_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.UniqueConstraint("pass_a_execution_id", name="uq_quality_gate_pass_a"),
        sa.UniqueConstraint("pass_b_execution_id", name="uq_quality_gate_pass_b"),
        _hex("gate_id", 37, "gate-", "ck_quality_gate_id"),
        sa.CheckConstraint("purpose IN ('model_comparison', 'operational_approval')", name="ck_quality_gate_purpose"),
        sa.CheckConstraint("execution_status IN ('대기', '실행 중', '완료', '실패', '중단됨')", name="ck_quality_gate_execution_status"),
        sa.CheckConstraint("result_status IN ('통과', '미달', '미측정', '보류')", name="ck_quality_gate_result_status"),
        sa.CheckConstraint("pass_a_execution_id <> pass_b_execution_id", name="ck_quality_gate_distinct_executions"),
        sa.CheckConstraint("length(trim(created_by)) > 0", name="ck_quality_gate_created_by"),
        sa.CheckConstraint("length(trim(baseline_run_id)) > 0 AND length(trim(sample_artifact_path)) > 0 AND length(trim(baseline_decisions_path)) > 0 AND length(trim(policy_version)) > 0 AND length(trim(prompt_version)) > 0 AND length(trim(model_name)) > 0 AND length(trim(company_profile_version)) > 0 AND length(trim(pass_a_execution_id)) > 0 AND length(trim(pass_b_execution_id)) > 0", name="ck_quality_gate_strings"),
        sa.CheckConstraint("length(model_digest) = 64 AND model_digest NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_model_digest"),
        sa.CheckConstraint("length(company_profile_digest) = 64 AND company_profile_digest NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_profile_digest"),
        sa.CheckConstraint("length(sample_artifact_digest) = 64 AND sample_artifact_digest NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_sample_digest"),
        sa.CheckConstraint("length(baseline_decisions_digest) = 64 AND baseline_decisions_digest NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_baseline_decision_digest"),
        sa.CheckConstraint("json_valid(metrics_json) AND json_type(metrics_json) = 'object'", name="ck_quality_gate_metrics_json"),
        sa.CheckConstraint("json_valid(reasons_json) AND json_type(reasons_json) = 'array'", name="ck_quality_gate_reasons_json"),
        sa.CheckConstraint("((execution_status IN ('완료', '실패', '중단됨') AND completed_at IS NOT NULL) OR (execution_status NOT IN ('완료', '실패', '중단됨') AND completed_at IS NULL))", name="ck_quality_gate_completed"),
    )

    op.create_table(
        "quality_gate_evaluation",
        sa.Column("evaluation_id", sa.String(41), primary_key=True),
        sa.Column("gate_id", sa.String(37), sa.ForeignKey("quality_gate.gate_id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("result_status", sa.String(16), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("reasons_json", sa.JSON(), nullable=False),
        sa.Column("valid_review_count", sa.Integer(), nullable=False),
        sa.Column("distinct_notice_review_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("gate_id", "revision", name="uq_quality_gate_evaluation_revision"),
        _hex("evaluation_id", 41, "gateeval-", "ck_quality_gate_evaluation_id"),
        sa.CheckConstraint("revision >= 1", name="ck_quality_gate_evaluation_revision"),
        sa.CheckConstraint("result_status IN ('통과', '미달', '미측정', '보류')", name="ck_quality_gate_evaluation_result_status"),
        sa.CheckConstraint("length(trim(gate_id)) > 0", name="ck_quality_gate_evaluation_strings"),
        sa.CheckConstraint("valid_review_count >= 0 AND distinct_notice_review_count >= 0", name="ck_quality_gate_evaluation_counts"),
        sa.CheckConstraint("json_valid(metrics_json) AND json_type(metrics_json) = 'object'", name="ck_quality_gate_evaluation_metrics_json"),
        sa.CheckConstraint("json_valid(reasons_json) AND json_type(reasons_json) = 'array'", name="ck_quality_gate_evaluation_reasons_json"),
    )

    op.create_table(
        "screening_policy",
        sa.Column("policy_version", sa.String(255), primary_key=True),
        sa.Column("schema_version", sa.String(64), nullable=False, server_default="bidops.screening-policy.v1"),
        sa.Column("prompt_version", sa.String(255), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("perspective_prompts_json", sa.JSON(), nullable=False),
        sa.Column("counterargument_prompt_json", sa.JSON(), nullable=False),
        sa.Column("synthesis_prompt_json", sa.JSON(), nullable=False),
        sa.Column("candidate_selection_json", sa.JSON(), nullable=False),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.String(255), nullable=True),
        sa.Column("quality_gate_result_id", sa.String(41), sa.ForeignKey("quality_gate_evaluation.evaluation_id", ondelete="RESTRICT"), nullable=True),
        sa.CheckConstraint("schema_version = 'bidops.screening-policy.v1'", name="ck_screening_policy_schema_version"),
        sa.CheckConstraint("status IN ('draft', 'activation_candidate', 'active')", name="ck_screening_policy_status"),
        sa.CheckConstraint("length(trim(prompt_version)) > 0 AND length(trim(created_by)) > 0", name="ck_screening_policy_actor_fields"),
        sa.CheckConstraint("length(trim(policy_version)) > 0 AND length(trim(schema_version)) > 0 AND length(trim(status)) > 0", name="ck_screening_policy_strings"),
        sa.CheckConstraint("length(content_digest) = 64 AND content_digest NOT GLOB '*[^0-9a-f]*'", name="ck_screening_policy_content_digest"),
        sa.CheckConstraint("((status = 'active' AND active_slot = 1 AND activated_at IS NOT NULL AND activated_by IS NOT NULL AND quality_gate_result_id IS NOT NULL) OR (status <> 'active' AND active_slot IS NULL))", name="ck_screening_policy_active"),
        sa.CheckConstraint("activated_by IS NULL OR length(trim(activated_by)) > 0", name="ck_screening_policy_activated_by"),
        sa.CheckConstraint("json_valid(perspective_prompts_json) AND json_type(perspective_prompts_json) = 'object'", name="ck_screening_policy_perspective_json"),
        sa.CheckConstraint("json_valid(counterargument_prompt_json) AND json_type(counterargument_prompt_json) = 'object'", name="ck_screening_policy_counterargument_json"),
        sa.CheckConstraint("json_valid(synthesis_prompt_json) AND json_type(synthesis_prompt_json) = 'object'", name="ck_screening_policy_synthesis_json"),
        sa.CheckConstraint("json_valid(candidate_selection_json) AND json_type(candidate_selection_json) = 'object'", name="ck_screening_policy_candidate_selection_json"),
        sa.CheckConstraint("json_valid(thresholds_json) AND json_type(thresholds_json) = 'object'", name="ck_screening_policy_thresholds_json"),
    )
    op.create_index("uq_screening_policy_active_slot", "screening_policy", ["active_slot"], unique=True, sqlite_where=sa.text("active_slot IS NOT NULL"))

    op.create_table(
        "quality_gate_review",
        sa.Column("review_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("gate_id", sa.String(37), sa.ForeignKey("quality_gate.gate_id", ondelete="CASCADE"), nullable=False),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("screening_execution.execution_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("notice_id", sa.String(255), nullable=False),
        sa.Column("decision_digest", sa.String(64), nullable=False),
        sa.Column("reviewer", sa.String(255), nullable=False),
        sa.Column("evidence_judgment", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("gate_id", "notice_id", "reviewer", name="uq_quality_gate_review_notice_reviewer"),
        sa.CheckConstraint("evidence_judgment IN ('동의', '근거 부족', '판단 보류')", name="ck_quality_gate_review_judgment"),
        sa.CheckConstraint("length(trim(reviewer)) > 0", name="ck_quality_gate_review_reviewer"),
        sa.CheckConstraint("length(trim(gate_id)) > 0 AND length(trim(execution_id)) > 0 AND length(trim(notice_id)) > 0 AND length(trim(reviewer)) > 0 AND length(trim(evidence_judgment)) > 0 AND (note IS NULL OR length(trim(note)) > 0)", name="ck_quality_gate_review_strings"),
        sa.CheckConstraint("length(decision_digest) = 64 AND decision_digest NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_review_decision_digest"),
    )

    op.create_table(
        "schedule_setting",
        sa.Column("singleton_id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("timezone", sa.String(32), nullable=False, server_default="Asia/Seoul"),
        sa.Column("daily_time", sa.String(5), nullable=False, server_default="02:00"),
        sa.Column("weekly_time", sa.String(5), nullable=False, server_default="06:00"),
        sa.Column("prespec_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False, server_default="system:migration"),
        sa.CheckConstraint("singleton_id = 1", name="ck_schedule_setting_singleton"),
        sa.CheckConstraint("timezone = 'Asia/Seoul'", name="ck_schedule_setting_timezone"),
        sa.CheckConstraint("daily_time GLOB '[0-2][0-9]:[0-5][0-9]' AND substr(daily_time, 1, 2) <= '23'", name="ck_schedule_setting_daily_time"),
        sa.CheckConstraint("weekly_time GLOB '[0-2][0-9]:[0-5][0-9]' AND substr(weekly_time, 1, 2) <= '23'", name="ck_schedule_setting_weekly_time"),
        sa.CheckConstraint("length(trim(updated_by)) > 0", name="ck_schedule_setting_updated_by"),
    )
    op.create_table(
        "schedule_reservation",
        sa.Column("run_key", sa.String(32), primary_key=True),
        sa.Column("job_kind", sa.String(16), nullable=False),
        sa.Column("window_from", sa.Date(), nullable=False),
        sa.Column("window_to", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(32), nullable=False, server_default="Asia/Seoul"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("job_kind IN ('daily', 'weekly')", name="ck_schedule_reservation_job_kind"),
        sa.CheckConstraint("window_from <= window_to", name="ck_schedule_reservation_window"),
        sa.CheckConstraint("timezone = 'Asia/Seoul'", name="ck_schedule_reservation_timezone"),
        sa.CheckConstraint("length(trim(run_key)) > 0 AND length(trim(job_kind)) > 0 AND length(trim(timezone)) > 0", name="ck_schedule_reservation_strings"),
    )
    op.create_table(
        "schedule_execution",
        sa.Column("execution_id", sa.String(38), primary_key=True),
        sa.Column("run_key", sa.String(32), sa.ForeignKey("schedule_reservation.run_key", ondelete="RESTRICT"), nullable=False),
        sa.Column("job_kind", sa.String(16), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="예약"),
        sa.Column("duplicate_of_execution_id", sa.String(38), sa.ForeignKey("schedule_execution.execution_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("recovery_of_execution_id", sa.String(38), sa.ForeignKey("schedule_execution.execution_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("run_id", sa.String(160), sa.ForeignKey("run.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("screening_execution_id", sa.String(36), sa.ForeignKey("screening_execution.execution_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=True),
        sa.Column("partial_artifact", sa.Boolean(), nullable=True),
        sa.Column("policy_version", sa.String(255), sa.ForeignKey("screening_policy.policy_version", ondelete="RESTRICT"), nullable=True),
        sa.Column("model_name", sa.String(255), nullable=True),
        sa.Column("model_digest", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(255), nullable=True),
        sa.Column("company_profile_version", sa.String(128), sa.ForeignKey("company_profile_snapshot.version", ondelete="RESTRICT"), nullable=True),
        sa.Column("company_profile_digest", sa.String(64), sa.ForeignKey("company_profile_snapshot.digest", ondelete="RESTRICT"), nullable=True),
        _hex("execution_id", 38, "sched-", "ck_schedule_execution_id"),
        sa.CheckConstraint("job_kind IN ('daily', 'weekly')", name="ck_schedule_execution_job_kind"),
        sa.CheckConstraint("trigger IN ('schedule', 'manual')", name="ck_schedule_execution_trigger"),
        sa.CheckConstraint("status IN ('예약', '실행 중', '성공', '부분 성공', '실패', '건너뜀')", name="ck_schedule_execution_status"),
        sa.CheckConstraint("NOT (duplicate_of_execution_id IS NOT NULL AND recovery_of_execution_id IS NOT NULL)", name="ck_schedule_execution_recovery_one"),
        sa.CheckConstraint("length(trim(requested_by)) > 0", name="ck_schedule_execution_requested_by"),
        sa.CheckConstraint("length(trim(run_key)) > 0 AND length(trim(job_kind)) > 0 AND length(trim(trigger)) > 0 AND length(trim(status)) > 0 AND (duplicate_of_execution_id IS NULL OR length(trim(duplicate_of_execution_id)) > 0) AND (recovery_of_execution_id IS NULL OR length(trim(recovery_of_execution_id)) > 0) AND (skip_reason IS NULL OR length(trim(skip_reason)) > 0) AND (failure_reason IS NULL OR length(trim(failure_reason)) > 0) AND (policy_version IS NULL OR length(trim(policy_version)) > 0) AND (prompt_version IS NULL OR length(trim(prompt_version)) > 0) AND (model_name IS NULL OR length(trim(model_name)) > 0) AND (company_profile_version IS NULL OR length(trim(company_profile_version)) > 0)", name="ck_schedule_execution_strings"),
        sa.CheckConstraint("(run_id IS NULL OR length(trim(run_id)) > 0) AND (screening_execution_id IS NULL OR length(trim(screening_execution_id)) > 0) AND (model_digest IS NULL OR (length(model_digest) = 64 AND model_digest NOT GLOB '*[^0-9a-f]*')) AND (company_profile_digest IS NULL OR (length(company_profile_digest) = 64 AND company_profile_digest NOT GLOB '*[^0-9a-f]*'))", name="ck_schedule_execution_digests"),
        sa.CheckConstraint("((status = '건너뜀' AND skip_reason IS NOT NULL) OR (status <> '건너뜀' AND skip_reason IS NULL))", name="ck_schedule_execution_skip_reason"),
        sa.CheckConstraint("candidate_count IS NULL OR candidate_count >= 0", name="ck_schedule_execution_candidate_count"),
        sa.CheckConstraint("result_count IS NULL OR result_count >= 0", name="ck_schedule_execution_result_count"),
        sa.CheckConstraint("failure_count IS NULL OR failure_count >= 0", name="ck_schedule_execution_failure_count"),
    )

    op.create_table(
        "always_on_state",
        sa.Column("singleton_id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quality_gate_result_id", sa.String(41), sa.ForeignKey("quality_gate_evaluation.evaluation_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("policy_version", sa.String(255), sa.ForeignKey("screening_policy.policy_version", ondelete="RESTRICT"), nullable=True),
        sa.Column("model_name", sa.String(255), nullable=True),
        sa.Column("model_digest", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(255), nullable=True),
        sa.Column("company_profile_version", sa.String(128), sa.ForeignKey("company_profile_snapshot.version", ondelete="RESTRICT"), nullable=True),
        sa.Column("company_profile_digest", sa.String(64), sa.ForeignKey("company_profile_snapshot.digest", ondelete="RESTRICT"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False, server_default="system:migration"),
        sa.CheckConstraint("singleton_id = 1", name="ck_always_on_singleton"),
        sa.CheckConstraint("length(trim(updated_by)) > 0", name="ck_always_on_updated_by"),
        sa.CheckConstraint("(quality_gate_result_id IS NULL OR length(trim(quality_gate_result_id)) > 0) AND (policy_version IS NULL OR length(trim(policy_version)) > 0) AND (model_name IS NULL OR length(trim(model_name)) > 0) AND (prompt_version IS NULL OR length(trim(prompt_version)) > 0) AND (company_profile_version IS NULL OR length(trim(company_profile_version)) > 0)", name="ck_always_on_strings"),
        sa.CheckConstraint("(model_digest IS NULL OR (length(model_digest) = 64 AND model_digest NOT GLOB '*[^0-9a-f]*')) AND (company_profile_digest IS NULL OR (length(company_profile_digest) = 64 AND company_profile_digest NOT GLOB '*[^0-9a-f]*'))", name="ck_always_on_digests"),
        sa.CheckConstraint("((enabled = 0) OR (quality_gate_result_id IS NOT NULL AND policy_version IS NOT NULL AND model_name IS NOT NULL AND model_digest IS NOT NULL AND prompt_version IS NOT NULL AND company_profile_version IS NOT NULL AND company_profile_digest IS NOT NULL))", name="ck_always_on_enabled_metadata"),
    )
    op.create_table(
        "audit_event",
        sa.Column("event_id", sa.String(38), primary_key=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("target_type", sa.String(128), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        _hex("event_id", 38, "audit-", "ck_audit_event_id"),
        sa.CheckConstraint("length(trim(event_type)) > 0 AND length(trim(actor)) > 0 AND length(trim(target_type)) > 0 AND length(trim(target_id)) > 0", name="ck_audit_event_strings"),
        sa.CheckConstraint("json_valid(details_json) AND json_type(details_json) = 'object'", name="ck_audit_event_details_json"),
    )

    bind = op.get_bind()
    bind.execute(sa.text("INSERT INTO schedule_setting(singleton_id, timezone, daily_time, weekly_time, prespec_enabled, updated_at, updated_by) VALUES (1, 'Asia/Seoul', :daily, :weekly, :prespec, :now, 'system:migration')"), {"daily": _time_value("BIDOPS_SCHEDULE_DAILY_TIME", "02:00"), "weekly": _time_value("BIDOPS_SCHEDULE_WEEKLY_TIME", "06:00"), "prespec": 1 if os.environ.get("BIDOPS_PRESPEC_ENABLED", "false").lower() in {"1", "true", "yes", "on"} else 0, "now": _now()})
    bind.execute(sa.text("INSERT INTO always_on_state(singleton_id, enabled, updated_at, updated_by) VALUES (1, 0, :now, 'system:migration')"), {"now": _now()})

    # Cross-row invariants cannot be represented by SQLite CHECK constraints.
    op.execute("CREATE TRIGGER screening_execution_profile_pair_insert BEFORE INSERT ON screening_execution WHEN (SELECT version FROM company_profile_snapshot WHERE version = NEW.company_profile_version) IS NULL OR (SELECT digest FROM company_profile_snapshot WHERE version = NEW.company_profile_version) <> NEW.company_profile_digest BEGIN SELECT RAISE(ABORT, 'company profile version/digest mismatch'); END")
    op.execute("CREATE TRIGGER screening_execution_profile_pair_update BEFORE UPDATE OF company_profile_version, company_profile_digest ON screening_execution WHEN (SELECT digest FROM company_profile_snapshot WHERE version = NEW.company_profile_version) IS NULL OR (SELECT digest FROM company_profile_snapshot WHERE version = NEW.company_profile_version) <> NEW.company_profile_digest BEGIN SELECT RAISE(ABORT, 'company profile version/digest mismatch'); END")
    op.execute("CREATE TRIGGER screening_execution_notice_identity_insert BEFORE INSERT ON screening_execution WHEN NEW.scope = 'single_notice' AND ((SELECT notice_key FROM notice WHERE id = NEW.notice_pk) IS NULL OR (SELECT notice_key FROM notice WHERE id = NEW.notice_pk) <> NEW.notice_id OR (SELECT run_id FROM notice WHERE id = NEW.notice_pk) IS NULL OR (SELECT run_id FROM notice WHERE id = NEW.notice_pk) <> NEW.source_run_id) BEGIN SELECT RAISE(ABORT, 'single notice identity mismatch'); END")
    op.execute("CREATE TRIGGER screening_execution_notice_identity_update BEFORE UPDATE OF scope, notice_pk, notice_id, source_run_id ON screening_execution WHEN NEW.scope = 'single_notice' AND ((SELECT notice_key FROM notice WHERE id = NEW.notice_pk) IS NULL OR (SELECT notice_key FROM notice WHERE id = NEW.notice_pk) <> NEW.notice_id OR (SELECT run_id FROM notice WHERE id = NEW.notice_pk) IS NULL OR (SELECT run_id FROM notice WHERE id = NEW.notice_pk) <> NEW.source_run_id) BEGIN SELECT RAISE(ABORT, 'single notice identity mismatch'); END")
    op.execute("CREATE TRIGGER quality_gate_profile_pair_insert BEFORE INSERT ON quality_gate WHEN (SELECT digest FROM company_profile_snapshot WHERE version = NEW.company_profile_version) IS NULL OR (SELECT digest FROM company_profile_snapshot WHERE version = NEW.company_profile_version) <> NEW.company_profile_digest BEGIN SELECT RAISE(ABORT, 'quality gate profile mismatch'); END")
    op.execute("CREATE TRIGGER quality_gate_profile_pair_update BEFORE UPDATE OF company_profile_version, company_profile_digest ON quality_gate WHEN (SELECT digest FROM company_profile_snapshot WHERE version = NEW.company_profile_version) IS NULL OR (SELECT digest FROM company_profile_snapshot WHERE version = NEW.company_profile_version) <> NEW.company_profile_digest BEGIN SELECT RAISE(ABORT, 'quality gate profile mismatch'); END")
    op.execute("CREATE TRIGGER quality_gate_input_immutable BEFORE UPDATE OF purpose, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, created_by ON quality_gate BEGIN SELECT RAISE(ABORT, 'quality gate input is immutable'); END")
    op.execute("CREATE TRIGGER quality_gate_evaluation_append BEFORE INSERT ON quality_gate_evaluation WHEN NEW.revision <> COALESCE((SELECT MAX(revision) + 1 FROM quality_gate_evaluation WHERE gate_id = NEW.gate_id), 1) BEGIN SELECT RAISE(ABORT, 'quality gate evaluations must append sequentially'); END")
    op.execute("CREATE TRIGGER quality_gate_evaluation_no_update BEFORE UPDATE ON quality_gate_evaluation BEGIN SELECT RAISE(ABORT, 'quality gate evaluation is immutable'); END")
    op.execute("CREATE TRIGGER quality_gate_evaluation_no_delete BEFORE DELETE ON quality_gate_evaluation BEGIN SELECT RAISE(ABORT, 'quality gate evaluation is immutable'); END")
    op.execute("CREATE TRIGGER screening_policy_body_immutable BEFORE UPDATE OF policy_version, schema_version, prompt_version, content_digest, perspective_prompts_json, counterargument_prompt_json, synthesis_prompt_json, candidate_selection_json, thresholds_json ON screening_policy BEGIN SELECT RAISE(ABORT, 'screening policy identity/body is immutable'); END")
    op.execute("CREATE TRIGGER screening_policy_active_gate_insert BEFORE INSERT ON screening_policy WHEN NEW.status = 'active' AND NOT EXISTS (SELECT 1 FROM quality_gate_evaluation e JOIN quality_gate g ON g.gate_id = e.gate_id WHERE e.evaluation_id = NEW.quality_gate_result_id AND e.revision = (SELECT MAX(latest.revision) FROM quality_gate_evaluation latest WHERE latest.gate_id = e.gate_id) AND e.result_status = '통과' AND g.purpose = 'operational_approval' AND g.policy_version = NEW.policy_version AND g.prompt_version = NEW.prompt_version) BEGIN SELECT RAISE(ABORT, 'active policy requires latest passing operational approval'); END")
    op.execute("CREATE TRIGGER screening_policy_active_gate_update BEFORE UPDATE OF status, active_slot, activated_at, activated_by, quality_gate_result_id ON screening_policy WHEN NEW.status = 'active' AND NOT EXISTS (SELECT 1 FROM quality_gate_evaluation e JOIN quality_gate g ON g.gate_id = e.gate_id WHERE e.evaluation_id = NEW.quality_gate_result_id AND e.revision = (SELECT MAX(latest.revision) FROM quality_gate_evaluation latest WHERE latest.gate_id = e.gate_id) AND e.result_status = '통과' AND g.purpose = 'operational_approval' AND g.policy_version = NEW.policy_version AND g.prompt_version = NEW.prompt_version) BEGIN SELECT RAISE(ABORT, 'active policy requires latest passing operational approval'); END")
    op.execute("CREATE TRIGGER screening_policy_projection_changed AFTER UPDATE OF status, active_slot, quality_gate_result_id ON screening_policy WHEN NEW.status <> 'active' OR NEW.active_slot IS NULL OR NEW.quality_gate_result_id IS NOT OLD.quality_gate_result_id BEGIN UPDATE always_on_state SET enabled = 0, updated_at = COALESCE(NEW.activated_at, OLD.activated_at, CURRENT_TIMESTAMP), updated_by = 'system:policy' WHERE enabled = 1 AND policy_version = NEW.policy_version; END")
    op.execute("CREATE TRIGGER quality_gate_evaluation_projection_changed AFTER INSERT ON quality_gate_evaluation BEGIN UPDATE always_on_state SET enabled = 0, updated_at = NEW.created_at, updated_by = 'system:quality-gate' WHERE enabled = 1 AND quality_gate_result_id IN (SELECT evaluation_id FROM quality_gate_evaluation WHERE gate_id = NEW.gate_id AND evaluation_id <> NEW.evaluation_id); UPDATE screening_policy SET status = 'activation_candidate', active_slot = NULL, activated_at = NULL, activated_by = NULL, quality_gate_result_id = NULL WHERE status = 'active' AND quality_gate_result_id IN (SELECT evaluation_id FROM quality_gate_evaluation WHERE gate_id = NEW.gate_id AND evaluation_id <> NEW.evaluation_id); END")
    op.execute("CREATE TRIGGER quality_gate_review_pass_a_insert BEFORE INSERT ON quality_gate_review WHEN (SELECT pass_a_execution_id FROM quality_gate WHERE gate_id = NEW.gate_id) <> NEW.execution_id BEGIN SELECT RAISE(ABORT, 'review execution must be gate pass A'); END")
    op.execute("CREATE TRIGGER quality_gate_review_pass_a_update BEFORE UPDATE OF gate_id, execution_id ON quality_gate_review WHEN (SELECT pass_a_execution_id FROM quality_gate WHERE gate_id = NEW.gate_id) <> NEW.execution_id BEGIN SELECT RAISE(ABORT, 'review execution must be gate pass A'); END")
    op.execute("CREATE TRIGGER schedule_execution_job_kind_insert BEFORE INSERT ON schedule_execution WHEN (SELECT job_kind FROM schedule_reservation WHERE run_key = NEW.run_key) <> NEW.job_kind BEGIN SELECT RAISE(ABORT, 'schedule execution job kind mismatch'); END")
    op.execute("CREATE TRIGGER schedule_execution_job_kind_update BEFORE UPDATE OF run_key, job_kind ON schedule_execution WHEN (SELECT job_kind FROM schedule_reservation WHERE run_key = NEW.run_key) <> NEW.job_kind BEGIN SELECT RAISE(ABORT, 'schedule execution job kind mismatch'); END")
    op.execute("CREATE TRIGGER schedule_execution_relation_insert BEFORE INSERT ON schedule_execution WHEN (NEW.duplicate_of_execution_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM schedule_execution target WHERE target.execution_id = NEW.duplicate_of_execution_id AND target.run_key = NEW.run_key AND target.job_kind = NEW.job_kind)) OR (NEW.recovery_of_execution_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM schedule_execution target WHERE target.execution_id = NEW.recovery_of_execution_id AND target.run_key = NEW.run_key AND target.job_kind = NEW.job_kind AND target.status IN ('실패', '부분 성공'))) BEGIN SELECT RAISE(ABORT, 'schedule execution relation mismatch'); END")
    op.execute("CREATE TRIGGER schedule_execution_relation_update BEFORE UPDATE OF run_key, job_kind, duplicate_of_execution_id, recovery_of_execution_id ON schedule_execution WHEN (NEW.duplicate_of_execution_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM schedule_execution target WHERE target.execution_id = NEW.duplicate_of_execution_id AND target.run_key = NEW.run_key AND target.job_kind = NEW.job_kind)) OR (NEW.recovery_of_execution_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM schedule_execution target WHERE target.execution_id = NEW.recovery_of_execution_id AND target.run_key = NEW.run_key AND target.job_kind = NEW.job_kind AND target.status IN ('실패', '부분 성공'))) BEGIN SELECT RAISE(ABORT, 'schedule execution relation mismatch'); END")
    op.execute("CREATE TRIGGER schedule_execution_relation_target_update BEFORE UPDATE OF run_key, job_kind, status ON schedule_execution WHEN EXISTS (SELECT 1 FROM schedule_execution child WHERE (child.duplicate_of_execution_id = NEW.execution_id OR child.recovery_of_execution_id = NEW.execution_id) AND (NEW.run_key <> OLD.run_key OR NEW.job_kind <> OLD.job_kind OR (child.recovery_of_execution_id = NEW.execution_id AND NEW.status NOT IN ('실패', '부분 성공')))) BEGIN SELECT RAISE(ABORT, 'schedule execution target relation mismatch'); END")
    op.execute("CREATE TRIGGER always_on_enabled_insert BEFORE INSERT ON always_on_state WHEN NEW.enabled = 1 AND NOT EXISTS (SELECT 1 FROM screening_policy p JOIN quality_gate_evaluation e ON e.evaluation_id = p.quality_gate_result_id JOIN quality_gate g ON g.gate_id = e.gate_id WHERE p.policy_version = NEW.policy_version AND p.status = 'active' AND p.active_slot = 1 AND p.prompt_version = NEW.prompt_version AND e.evaluation_id = NEW.quality_gate_result_id AND e.revision = (SELECT MAX(latest.revision) FROM quality_gate_evaluation latest WHERE latest.gate_id = e.gate_id) AND e.result_status = '통과' AND g.purpose = 'operational_approval' AND g.policy_version = NEW.policy_version AND g.prompt_version = p.prompt_version AND g.model_name = NEW.model_name AND g.model_digest = NEW.model_digest AND g.company_profile_version = NEW.company_profile_version AND g.company_profile_digest = NEW.company_profile_digest) BEGIN SELECT RAISE(ABORT, 'always-on requires matching active operational approval'); END")
    op.execute("CREATE TRIGGER always_on_enabled_update BEFORE UPDATE OF enabled, quality_gate_result_id, policy_version, model_name, model_digest, prompt_version, company_profile_version, company_profile_digest ON always_on_state WHEN NEW.enabled = 1 AND NOT EXISTS (SELECT 1 FROM screening_policy p JOIN quality_gate_evaluation e ON e.evaluation_id = p.quality_gate_result_id JOIN quality_gate g ON g.gate_id = e.gate_id WHERE p.policy_version = NEW.policy_version AND p.status = 'active' AND p.active_slot = 1 AND p.prompt_version = NEW.prompt_version AND e.evaluation_id = NEW.quality_gate_result_id AND e.revision = (SELECT MAX(latest.revision) FROM quality_gate_evaluation latest WHERE latest.gate_id = e.gate_id) AND e.result_status = '통과' AND g.purpose = 'operational_approval' AND g.policy_version = NEW.policy_version AND g.prompt_version = p.prompt_version AND g.model_name = NEW.model_name AND g.model_digest = NEW.model_digest AND g.company_profile_version = NEW.company_profile_version AND g.company_profile_digest = NEW.company_profile_digest) BEGIN SELECT RAISE(ABORT, 'always-on requires matching active operational approval'); END")


def downgrade() -> None:
    for name in (
        "always_on_enabled_update", "always_on_enabled_insert", "quality_gate_evaluation_projection_changed", "screening_policy_projection_changed", "screening_policy_active_gate_update", "screening_policy_active_gate_insert", "screening_policy_body_immutable", "schedule_execution_relation_target_update", "schedule_execution_relation_update", "schedule_execution_relation_insert", "schedule_execution_job_kind_update", "schedule_execution_job_kind_insert", "quality_gate_review_pass_a_update", "quality_gate_review_pass_a_insert", "quality_gate_evaluation_no_delete", "quality_gate_evaluation_no_update", "quality_gate_evaluation_append", "quality_gate_input_immutable", "quality_gate_profile_pair_update", "quality_gate_profile_pair_insert", "screening_execution_notice_identity_update", "screening_execution_notice_identity_insert", "screening_execution_profile_pair_update", "screening_execution_profile_pair_insert",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table("audit_event")
    op.drop_table("always_on_state")
    op.drop_table("schedule_execution")
    op.drop_table("schedule_reservation")
    op.drop_table("schedule_setting")
    op.drop_table("quality_gate_review")
    op.drop_index("uq_screening_policy_active_slot", table_name="screening_policy")
    op.drop_table("screening_policy")
    op.drop_table("quality_gate_evaluation")
    op.drop_table("quality_gate")
    op.drop_index("uq_screening_execution_active_slot", table_name="screening_execution")
    op.drop_table("screening_attempt")
    op.drop_table("screening_execution")
    op.drop_table("company_profile_snapshot")
