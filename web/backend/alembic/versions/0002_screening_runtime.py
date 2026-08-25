"""Add the durable screening, quality-gate, schedule, and audit model."""

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
    if len(value) == 5 and value[2] == ":":
        try:
            hour, minute = int(value[:2]), int(value[3:])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return value
        except ValueError:
            pass
    return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upgrade() -> None:
    op.create_table(
        "screening_execution",
        sa.Column("queue_no", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("source_run_id", sa.String(length=160), sa.ForeignKey("run.id"), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("notice_pk", sa.Integer(), sa.ForeignKey("notice.id"), nullable=True),
        sa.Column("notice_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="대기"),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("policy_version", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("model_version", sa.String(length=255), nullable=True),
        sa.Column("profile_digest", sa.String(length=64), sa.ForeignKey("company_profile_snapshot.digest"), nullable=True),
        sa.Column("input_metadata", sa.JSON(), nullable=True),
        sa.Column("input_artifact_path", sa.Text(), nullable=True),
        sa.Column("artifact_dir", sa.Text(), nullable=True),
        sa.Column("current_notice_id", sa.String(length=255), nullable=True),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_requested_by", sa.String(length=255), nullable=True),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notice_count", sa.Integer(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=True),
        sa.Column("published_run_id", sa.String(length=160), sa.ForeignKey("run.id"), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.UniqueConstraint("execution_id", name="uq_screening_execution_id"),
        sa.UniqueConstraint("input_artifact_path", name="uq_screening_execution_input_artifact_path"),
        sa.UniqueConstraint("artifact_dir", name="uq_screening_execution_artifact_dir"),
        sa.UniqueConstraint("published_run_id", name="uq_screening_execution_published_run"),
        sa.CheckConstraint("length(execution_id) = 36 AND substr(execution_id, 1, 4) = 'scr-' AND substr(execution_id, 5) NOT GLOB '*[^0-9a-f]*'", name="ck_screening_execution_id"),
        sa.CheckConstraint("trigger IN ('cli_single', 'manual_run', 'quality_gate', 'schedule')", name="ck_screening_execution_trigger"),
        sa.CheckConstraint("scope IN ('single_notice', 'full_run', 'quality_sample')", name="ck_screening_execution_scope"),
        sa.CheckConstraint("status IN ('대기', '실행 중', '중지 요청', '성공', '부분 성공', '실패', '중단됨')", name="ck_screening_execution_status"),
        sa.CheckConstraint("((scope = 'single_notice' AND notice_pk IS NOT NULL AND notice_id IS NOT NULL) OR (scope <> 'single_notice' AND notice_pk IS NULL AND notice_id IS NULL))", name="ck_screening_execution_single_notice"),
        sa.CheckConstraint("((status IN ('실행 중', '중지 요청') AND active_slot = 1) OR (status NOT IN ('실행 중', '중지 요청') AND active_slot IS NULL))", name="ck_screening_execution_active_slot"),
        sa.CheckConstraint("((status IN ('성공', '부분 성공', '실패', '중단됨') AND finished_at IS NOT NULL) OR (status NOT IN ('성공', '부분 성공', '실패', '중단됨') AND finished_at IS NULL))", name="ck_screening_execution_terminal"),
        sa.CheckConstraint("stop_reason IS NULL OR stop_reason IN ('user_requested', 'process_interrupted')", name="ck_screening_execution_stop_reason"),
        sa.CheckConstraint("queued_at IS NOT NULL", name="ck_screening_execution_queued_at"),
        sa.CheckConstraint("notice_count IS NULL OR notice_count >= 0", name="ck_screening_execution_notice_count"),
        sa.CheckConstraint("success_count IS NULL OR success_count >= 0", name="ck_screening_execution_success_count"),
        sa.CheckConstraint("failure_count IS NULL OR failure_count >= 0", name="ck_screening_execution_failure_count"),
        sa.CheckConstraint("review_count IS NULL OR review_count >= 0", name="ck_screening_execution_review_count"),
        sa.CheckConstraint("requested_by IS NULL OR length(trim(requested_by)) > 0", name="ck_screening_execution_requested_by"),
        sa.CheckConstraint("stop_requested_by IS NULL OR length(trim(stop_requested_by)) > 0", name="ck_screening_execution_stop_requested_by"),
        sa.CheckConstraint("input_metadata IS NULL OR json_valid(input_metadata)", name="ck_screening_execution_input_metadata_json"),
        sa.CheckConstraint("input_artifact_path IS NULL OR (length(trim(input_artifact_path)) > 0 AND input_artifact_path NOT LIKE '/%' AND input_artifact_path NOT LIKE '%\\%' AND input_artifact_path NOT LIKE '%..%')", name="ck_screening_execution_input_artifact_path"),
        sa.CheckConstraint("artifact_dir IS NULL OR (length(trim(artifact_dir)) > 0 AND artifact_dir NOT LIKE '/%' AND artifact_dir NOT LIKE '%\\%' AND artifact_dir NOT LIKE '%..%')", name="ck_screening_execution_artifact_dir"),
    )
    op.create_index("uq_screening_execution_active_slot", "screening_execution", ["active_slot"], unique=True, sqlite_where=sa.text("active_slot IS NOT NULL"))

    op.create_table(
        "screening_attempt",
        sa.Column("attempt_id", sa.String(length=255), primary_key=True),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("screening_execution.execution_id", ondelete="CASCADE"), nullable=False),
        sa.Column("notice_id", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failure_type", sa.String(length=32), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=False),
        sa.Column("span_id", sa.String(length=255), nullable=False),
        sa.Column("done_reason", sa.String(length=64), nullable=True),
        sa.Column("prompt_eval_count", sa.Integer(), nullable=True),
        sa.Column("eval_count", sa.Integer(), nullable=True),
        sa.Column("prompt_eval_duration", sa.Integer(), nullable=True),
        sa.Column("eval_duration", sa.Integer(), nullable=True),
        sa.Column("load_duration", sa.Integer(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_artifact_path", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint("execution_id", "notice_id", "stage", "attempt_no", name="uq_screening_attempt_number"),
        sa.UniqueConstraint("span_id", name="uq_screening_attempt_span"),
        sa.CheckConstraint("attempt_no >= 1", name="ck_screening_attempt_no"),
        sa.CheckConstraint("stage IN ('기술 적합성', '실적 정합성', '공공 SI 적합성', '사업성·자격 제약', '전략 부합', 'counterargument', 'synthesis', 'carried_over_validation')", name="ck_screening_attempt_stage"),
        sa.CheckConstraint("status IN ('success', 'failure')", name="ck_screening_attempt_status"),
        sa.CheckConstraint("failure_type IS NULL OR failure_type IN ('timeout', 'truncated_output', 'schema_violation', 'evidence_missing', 'counterargument_repetition')", name="ck_screening_attempt_failure_type"),
        sa.CheckConstraint("prompt_eval_count IS NULL OR prompt_eval_count >= 0", name="ck_screening_attempt_prompt_eval_count"),
        sa.CheckConstraint("eval_count IS NULL OR eval_count >= 0", name="ck_screening_attempt_eval_count"),
        sa.CheckConstraint("prompt_eval_duration IS NULL OR prompt_eval_duration >= 0", name="ck_screening_attempt_prompt_eval_duration"),
        sa.CheckConstraint("eval_duration IS NULL OR eval_duration >= 0", name="ck_screening_attempt_eval_duration"),
        sa.CheckConstraint("load_duration IS NULL OR load_duration >= 0", name="ck_screening_attempt_load_duration"),
        sa.CheckConstraint("((status = 'success' AND response_artifact_path IS NOT NULL AND failure_type IS NULL) OR (status = 'failure' AND failure_type IS NOT NULL))", name="ck_screening_attempt_success_artifact"),
    )

    op.create_table(
        "company_profile_snapshot",
        sa.Column("digest", sa.String(length=64), primary_key=True),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("version", name="uq_company_profile_snapshot_version"),
        sa.UniqueConstraint("artifact_path", name="uq_company_profile_snapshot_artifact_path"),
        sa.CheckConstraint("length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'", name="ck_profile_digest"),
        sa.CheckConstraint("source_kind IN ('working_tree', 'git_blob')", name="ck_profile_source_kind"),
        sa.CheckConstraint("length(trim(source_ref)) > 0", name="ck_profile_source_ref"),
        sa.CheckConstraint("version = 'company-profile.sha256:' || digest", name="ck_profile_version_digest"),
    )

    op.create_table(
        "quality_gate",
        sa.Column("gate_id", sa.String(length=37), primary_key=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("execution_status", sa.String(length=16), nullable=False),
        sa.Column("result_status", sa.String(length=16), nullable=False),
        sa.Column("baseline_run_id", sa.String(length=160), sa.ForeignKey("run.id"), nullable=True),
        sa.Column("sample_artifact_path", sa.Text(), nullable=True),
        sa.Column("sample_digest", sa.String(length=64), nullable=True),
        sa.Column("baseline_decision_path", sa.Text(), nullable=True),
        sa.Column("baseline_decision_digest", sa.String(length=64), nullable=True),
        sa.Column("policy_version", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("model_version", sa.String(length=255), nullable=True),
        sa.Column("profile_digest", sa.String(length=64), sa.ForeignKey("company_profile_snapshot.digest"), nullable=True),
        sa.Column("execution_a_id", sa.String(length=36), sa.ForeignKey("screening_execution.execution_id"), nullable=False),
        sa.Column("execution_b_id", sa.String(length=36), sa.ForeignKey("screening_execution.execution_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_metrics", sa.JSON(), nullable=True),
        sa.Column("latest_reasons", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("execution_a_id", name="uq_quality_gate_execution_a"),
        sa.UniqueConstraint("execution_b_id", name="uq_quality_gate_execution_b"),
        sa.CheckConstraint("length(gate_id) = 37 AND substr(gate_id, 1, 5) = 'gate-' AND substr(gate_id, 6) NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_id"),
        sa.CheckConstraint("purpose IN ('model_comparison', 'operational_approval')", name="ck_quality_gate_purpose"),
        sa.CheckConstraint("execution_status IN ('대기', '실행 중', '성공', '부분 성공', '실패')", name="ck_quality_gate_execution_status"),
        sa.CheckConstraint("result_status IN ('계산 중', '통과', '미달', '미측정', '계산 불가')", name="ck_quality_gate_result_status"),
        sa.CheckConstraint("execution_a_id <> execution_b_id", name="ck_quality_gate_distinct_executions"),
        sa.CheckConstraint("created_by IS NULL OR length(trim(created_by)) > 0", name="ck_quality_gate_created_by"),
        sa.CheckConstraint("(sample_digest IS NULL OR (length(sample_digest) = 64 AND sample_digest NOT GLOB '*[^0-9a-f]*'))", name="ck_quality_gate_sample_digest"),
        sa.CheckConstraint("(baseline_decision_digest IS NULL OR (length(baseline_decision_digest) = 64 AND baseline_decision_digest NOT GLOB '*[^0-9a-f]*'))", name="ck_quality_gate_baseline_decision_digest"),
        sa.CheckConstraint("latest_metrics IS NULL OR json_valid(latest_metrics)", name="ck_quality_gate_latest_metrics_json"),
        sa.CheckConstraint("latest_reasons IS NULL OR json_valid(latest_reasons)", name="ck_quality_gate_latest_reasons_json"),
    )

    op.create_table(
        "quality_gate_evaluation",
        sa.Column("gateeval_id", sa.String(length=40), primary_key=True),
        sa.Column("gate_id", sa.String(length=37), sa.ForeignKey("quality_gate.gate_id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("result_status", sa.String(length=16), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=True),
        sa.Column("agreement_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("gate_id", "revision", name="uq_quality_gate_evaluation_revision"),
        sa.CheckConstraint("length(gateeval_id) = 40 AND substr(gateeval_id, 1, 8) = 'gateeval-' AND substr(gateeval_id, 9) NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_evaluation_id"),
        sa.CheckConstraint("revision >= 1", name="ck_quality_gate_evaluation_revision"),
        sa.CheckConstraint("result_status IN ('계산 중', '통과', '미달', '미측정', '계산 불가')", name="ck_quality_gate_evaluation_result_status"),
        sa.CheckConstraint("review_count IS NULL OR review_count >= 0", name="ck_quality_gate_evaluation_review_count"),
        sa.CheckConstraint("agreement_count IS NULL OR agreement_count >= 0", name="ck_quality_gate_evaluation_agreement_count"),
        sa.CheckConstraint("metrics IS NULL OR json_valid(metrics)", name="ck_quality_gate_evaluation_metrics_json"),
        sa.CheckConstraint("reasons IS NULL OR json_valid(reasons)", name="ck_quality_gate_evaluation_reasons_json"),
    )

    op.create_table(
        "screening_policy",
        sa.Column("policy_version", sa.String(length=255), primary_key=True),
        sa.Column("schema_version", sa.String(length=64), nullable=False, server_default="bidops.screening-policy.v1"),
        sa.Column("prompt_version", sa.String(length=255), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("technical_fit_body", sa.JSON(), nullable=False),
        sa.Column("performance_fit_body", sa.JSON(), nullable=False),
        sa.Column("public_si_fit_body", sa.JSON(), nullable=False),
        sa.Column("business_qualification_body", sa.JSON(), nullable=False),
        sa.Column("strategic_fit_body", sa.JSON(), nullable=False),
        sa.Column("counterargument_body", sa.JSON(), nullable=True),
        sa.Column("synthesis_body", sa.JSON(), nullable=True),
        sa.Column("candidate_selection_body", sa.JSON(), nullable=True),
        sa.Column("thresholds_body", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.String(length=255), nullable=True),
        sa.Column("quality_gate_result_id", sa.String(length=40), sa.ForeignKey("quality_gate_evaluation.gateeval_id"), nullable=True),
        sa.CheckConstraint("schema_version = 'bidops.screening-policy.v1'", name="ck_screening_policy_schema_version"),
        sa.CheckConstraint("status IN ('draft', 'activation_candidate', 'active')", name="ck_screening_policy_status"),
        sa.CheckConstraint("length(trim(prompt_version)) > 0", name="ck_screening_policy_prompt_version"),
        sa.CheckConstraint("length(content_digest) = 64 AND content_digest NOT GLOB '*[^0-9a-f]*'", name="ck_screening_policy_content_digest"),
        sa.CheckConstraint("((status = 'active' AND active_slot = 1 AND activated_at IS NOT NULL AND activated_by IS NOT NULL AND quality_gate_result_id IS NOT NULL) OR (status <> 'active' AND active_slot IS NULL))", name="ck_screening_policy_active"),
        sa.CheckConstraint("created_by IS NULL OR length(trim(created_by)) > 0", name="ck_screening_policy_created_by"),
        sa.CheckConstraint("activated_by IS NULL OR length(trim(activated_by)) > 0", name="ck_screening_policy_activated_by"),
        sa.CheckConstraint("json_valid(technical_fit_body) AND json_valid(performance_fit_body) AND json_valid(public_si_fit_body) AND json_valid(business_qualification_body) AND json_valid(strategic_fit_body)", name="ck_screening_policy_body_json"),
        sa.CheckConstraint("counterargument_body IS NULL OR json_valid(counterargument_body)", name="ck_screening_policy_counterargument_json"),
        sa.CheckConstraint("synthesis_body IS NULL OR json_valid(synthesis_body)", name="ck_screening_policy_synthesis_json"),
        sa.CheckConstraint("candidate_selection_body IS NULL OR json_valid(candidate_selection_body)", name="ck_screening_policy_candidate_selection_json"),
        sa.CheckConstraint("thresholds_body IS NULL OR json_valid(thresholds_body)", name="ck_screening_policy_thresholds_json"),
    )
    op.create_index("uq_screening_policy_active_slot", "screening_policy", ["active_slot"], unique=True, sqlite_where=sa.text("active_slot IS NOT NULL"))
    op.execute("CREATE TRIGGER screening_policy_immutable_update BEFORE UPDATE OF content_digest, technical_fit_body, performance_fit_body, public_si_fit_body, business_qualification_body, strategic_fit_body ON screening_policy BEGIN SELECT RAISE(ABORT, 'screening policy body is immutable'); END")

    op.create_table(
        "quality_gate_review",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("gate_id", sa.String(length=37), sa.ForeignKey("quality_gate.gate_id", ondelete="CASCADE"), nullable=False),
        sa.Column("pass_a_execution_id", sa.String(length=36), sa.ForeignKey("screening_execution.execution_id"), nullable=False),
        sa.Column("notice_id", sa.String(length=255), nullable=False),
        sa.Column("decision_digest", sa.String(length=64), nullable=False),
        sa.Column("reviewer", sa.String(length=255), nullable=False),
        sa.Column("judgment", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("gate_id", "notice_id", "reviewer", name="uq_quality_gate_review_notice_reviewer"),
        sa.CheckConstraint("judgment IN ('동의', '근거 부족', '판단 보류')", name="ck_quality_gate_review_judgment"),
        sa.CheckConstraint("length(trim(reviewer)) > 0", name="ck_quality_gate_review_reviewer"),
        sa.CheckConstraint("length(decision_digest) = 64 AND decision_digest NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_review_decision_digest"),
    )

    op.create_table(
        "schedule_setting",
        sa.Column("singleton_id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("timezone", sa.String(length=32), nullable=False, server_default="Asia/Seoul"),
        sa.Column("daily_time", sa.String(length=5), nullable=False, server_default="02:00"),
        sa.Column("weekly_time", sa.String(length=5), nullable=False, server_default="06:00"),
        sa.Column("prespec_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False, server_default="system:migration"),
        sa.CheckConstraint("singleton_id = 1", name="ck_schedule_setting_singleton"),
        sa.CheckConstraint("timezone = 'Asia/Seoul'", name="ck_schedule_setting_timezone"),
        sa.CheckConstraint("daily_time GLOB '[0-2][0-9]:[0-5][0-9]' AND substr(daily_time, 1, 2) <= '23'", name="ck_schedule_setting_daily_time"),
        sa.CheckConstraint("weekly_time GLOB '[0-2][0-9]:[0-5][0-9]' AND substr(weekly_time, 1, 2) <= '23'", name="ck_schedule_setting_weekly_time"),
        sa.CheckConstraint("updated_by IS NULL OR length(trim(updated_by)) > 0", name="ck_schedule_setting_updated_by"),
    )
    op.create_table(
        "schedule_reservation",
        sa.Column("run_key", sa.String(length=32), primary_key=True),
        sa.Column("job_kind", sa.String(length=16), nullable=False),
        sa.Column("window_from", sa.Date(), nullable=False),
        sa.Column("window_to", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=32), nullable=False, server_default="Asia/Seoul"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.CheckConstraint("job_kind IN ('daily', 'weekly')", name="ck_schedule_reservation_job_kind"),
        sa.CheckConstraint("window_from <= window_to", name="ck_schedule_reservation_window"),
        sa.CheckConstraint("timezone = 'Asia/Seoul'", name="ck_schedule_reservation_timezone"),
        sa.CheckConstraint("created_by IS NULL OR length(trim(created_by)) > 0", name="ck_schedule_reservation_created_by"),
    )
    op.create_table(
        "schedule_execution",
        sa.Column("execution_id", sa.String(length=38), primary_key=True),
        sa.Column("run_key", sa.String(length=32), sa.ForeignKey("schedule_reservation.run_key"), nullable=False),
        sa.Column("job_kind", sa.String(length=16), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="예약"),
        sa.Column("duplicate_of_execution_id", sa.String(length=38), sa.ForeignKey("schedule_execution.execution_id"), nullable=True),
        sa.Column("recovered_from_execution_id", sa.String(length=38), sa.ForeignKey("schedule_execution.execution_id"), nullable=True),
        sa.Column("run_id", sa.String(length=160), sa.ForeignKey("run.id"), nullable=True),
        sa.Column("screening_execution_id", sa.String(length=36), sa.ForeignKey("screening_execution.execution_id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=True),
        sa.Column("partial_artifact", sa.Boolean(), nullable=True),
        sa.Column("policy_version", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("model_version", sa.String(length=255), nullable=True),
        sa.Column("profile_digest", sa.String(length=64), sa.ForeignKey("company_profile_snapshot.digest"), nullable=True),
        sa.CheckConstraint("length(execution_id) = 38 AND substr(execution_id, 1, 6) = 'sched-' AND substr(execution_id, 7) NOT GLOB '*[^0-9a-f]*'", name="ck_schedule_execution_id"),
        sa.CheckConstraint("job_kind IN ('daily', 'weekly')", name="ck_schedule_execution_job_kind"),
        sa.CheckConstraint("trigger IN ('schedule', 'manual')", name="ck_schedule_execution_trigger"),
        sa.CheckConstraint("status IN ('예약', '실행 중', '성공', '부분 성공', '실패', '건너뜀')", name="ck_schedule_execution_status"),
        sa.CheckConstraint("NOT (duplicate_of_execution_id IS NOT NULL AND recovered_from_execution_id IS NOT NULL)", name="ck_schedule_execution_recovery_one"),
        sa.CheckConstraint("actor IS NULL OR length(trim(actor)) > 0", name="ck_schedule_execution_actor"),
        sa.CheckConstraint("candidate_count IS NULL OR candidate_count >= 0", name="ck_schedule_execution_candidate_count"),
        sa.CheckConstraint("result_count IS NULL OR result_count >= 0", name="ck_schedule_execution_result_count"),
        sa.CheckConstraint("failure_count IS NULL OR failure_count >= 0", name="ck_schedule_execution_failure_count"),
    )
    op.execute("""
        CREATE TRIGGER schedule_execution_job_kind_match_insert
        BEFORE INSERT ON schedule_execution
        WHEN (SELECT job_kind FROM schedule_reservation WHERE run_key = NEW.run_key) <> NEW.job_kind
        BEGIN SELECT RAISE(ABORT, 'schedule execution job kind does not match reservation'); END
    """)
    op.execute("""
        CREATE TRIGGER schedule_execution_job_kind_match_update
        BEFORE UPDATE OF run_key, job_kind ON schedule_execution
        WHEN (SELECT job_kind FROM schedule_reservation WHERE run_key = NEW.run_key) <> NEW.job_kind
        BEGIN SELECT RAISE(ABORT, 'schedule execution job kind does not match reservation'); END
    """)
    op.create_table(
        "always_on_state",
        sa.Column("singleton_id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quality_gate_result_id", sa.String(length=40), sa.ForeignKey("quality_gate_evaluation.gateeval_id"), nullable=True),
        sa.Column("policy_version", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=255), nullable=True),
        sa.Column("profile_digest", sa.String(length=64), sa.ForeignKey("company_profile_snapshot.digest"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False, server_default="system:migration"),
        sa.CheckConstraint("singleton_id = 1", name="ck_always_on_singleton"),
        sa.CheckConstraint("updated_by IS NULL OR length(trim(updated_by)) > 0", name="ck_always_on_updated_by"),
        sa.CheckConstraint("((enabled = 0) OR (quality_gate_result_id IS NOT NULL AND policy_version IS NOT NULL AND model_name IS NOT NULL AND prompt_version IS NOT NULL AND profile_digest IS NOT NULL))", name="ck_always_on_enabled_metadata"),
    )
    op.create_table(
        "audit_event",
        sa.Column("event_id", sa.String(length=38), primary_key=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=128), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.CheckConstraint("length(event_id) = 38 AND substr(event_id, 1, 6) = 'audit-' AND substr(event_id, 7) NOT GLOB '*[^0-9a-f]*'", name="ck_audit_event_id"),
        sa.CheckConstraint("length(trim(event_type)) > 0", name="ck_audit_event_type"),
        sa.CheckConstraint("length(trim(actor)) > 0", name="ck_audit_event_actor"),
        sa.CheckConstraint("length(trim(target_type)) > 0", name="ck_audit_event_target_type"),
        sa.CheckConstraint("length(trim(target_id)) > 0", name="ck_audit_event_target_id"),
        sa.CheckConstraint("json_valid(details)", name="ck_audit_event_details_json"),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO schedule_setting(singleton_id, timezone, daily_time, weekly_time, prespec_enabled, updated_at, updated_by) "
            "VALUES (1, 'Asia/Seoul', :daily, :weekly, :prespec, :now, 'system:migration')"
        ),
        {"daily": _time_value("BIDOPS_SCHEDULE_DAILY_TIME", "02:00"), "weekly": _time_value("BIDOPS_SCHEDULE_WEEKLY_TIME", "06:00"), "prespec": 1 if os.environ.get("BIDOPS_PRESPEC_ENABLED", os.environ.get("BIDOPS_SCHEDULE_PRESPEC", "false")).lower() in {"1", "true", "yes", "on"} else 0, "now": _now()},
    )
    bind.execute(
        sa.text("INSERT INTO always_on_state(singleton_id, enabled, updated_at, updated_by) VALUES (1, 0, :now, 'system:migration')"),
        {"now": _now()},
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS screening_policy_immutable_update")
    op.execute("DROP TRIGGER IF EXISTS schedule_execution_job_kind_match_update")
    op.execute("DROP TRIGGER IF EXISTS schedule_execution_job_kind_match_insert")
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
    op.drop_table("company_profile_snapshot")
    op.drop_table("screening_attempt")
    op.drop_index("uq_screening_execution_active_slot", table_name="screening_execution")
    op.drop_table("screening_execution")
