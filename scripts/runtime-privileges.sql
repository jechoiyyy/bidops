-- Runtime database privilege policy.  This file is applied by migrate.sh as
-- the migrate role after every successful Alembic upgrade.
--
-- Keep grants table-specific: new tables receive no app/worker DML until
-- their runtime owner and write paths are reviewed and an explicit grant is
-- added here.  Backup is the only role with a read-only default grant.

BEGIN;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA bidops FROM app, worker, ro_backup;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA bidops FROM app, worker, ro_backup;
ALTER DEFAULT PRIVILEGES IN SCHEMA bidops REVOKE ALL ON TABLES FROM app, worker, ro_backup;
ALTER DEFAULT PRIVILEGES IN SCHEMA bidops REVOKE ALL ON SEQUENCES FROM app, worker, ro_backup;

GRANT USAGE ON SCHEMA bidops TO app, worker, ro_backup;

-- FastAPI reads the complete application projection and the Alembic marker.
-- Every named table below exists at the migration head. A new table is denied
-- until this allowlist is deliberately extended.
GRANT SELECT ON TABLE
    bidops.alembic_version,
    bidops.run,
    bidops.notice,
    bidops.notice_observation,
    bidops.order_plan,
    bidops.order_plan_observation,
    bidops.opportunity,
    bidops.opportunity_link,
    bidops.judgment,
    bidops.judgment_revision,
    bidops.perspective,
    bidops.screening_evidence,
    bidops.counterargument,
    bidops.verification_item,
    bidops.matched_performance,
    bidops.attachment,
    bidops.attachment_fetch,
    bidops.agency_portal,
    bidops.review,
    bidops.review_revision,
    bidops.verification_answer,
    bidops.ingest_warning,
    bidops.content_object,
    bidops.content_object_location,
    bidops.content_scan,
    bidops.document_version,
    bidops.document_structure,
    bidops.document_block,
    bidops.document_bundle,
    bidops.document_bundle_item,
    bidops.profile_version,
    bidops.profile_evidence,
    bidops.analysis_policy_version,
    bidops.deep_review,
    bidops.bid_delta_comparison,
    bidops.bid_final_decision,
    bidops.deep_review_attempt,
    bidops.deep_review_stage,
    bidops.claim,
    bidops.evidence_ref,
    bidops.claim_evidence,
    bidops.report_revision,
    bidops.report_revision_evidence,
    bidops.validation_run,
    bidops.validation_check,
    bidops.final_opinion,
    bidops.work_job,
    bidops.idempotency_record,
    bidops.audit_event,
    bidops.screening_execution,
    bidops.screening_attempt,
    bidops.company_profile_snapshot,
    bidops.quality_gate,
    bidops.quality_gate_evaluation,
    bidops.screening_policy,
    bidops.quality_gate_review,
    bidops.schedule_setting,
    bidops.schedule_reservation,
    bidops.schedule_execution,
    bidops.always_on_state,
    bidops.screening_audit_event,
    bidops.prespec_overview_run,
    bidops.prespec_company_fit_attempt,
    bidops.prespec_v4_pdf_snapshot,
    bidops.document_segment_manifest,
    bidops.document_segment,
    bidops.requirement_inventory_item,
    bidops.order_plan_screening_policy,
    bidops.order_plan_screening_execution,
    bidops.order_plan_screening_batch_attempt,
    bidops.order_plan_screening_result,
    bidops.order_plan_screening_artifact,
    bidops.order_plan_screening_feedback,
    bidops.collected_record_index,
    bidops.collected_record_token
TO app;

-- App-owned create paths include ingestion, UI mutations, orchestration, and
-- append-only audit/result/history rows. v4 preparation/enqueue is an app
-- transaction: the app creates the WorkJob and attempt, while only the worker
-- receives the later execution-state UPDATE grant below. App may only cancel
-- an unfinished v4 attempt; the database trigger enforces that transition.
-- UPDATE and DELETE are narrower lists below.
GRANT INSERT ON TABLE
    bidops.run,
    bidops.notice,
    bidops.notice_observation,
    bidops.order_plan,
    bidops.order_plan_observation,
    bidops.opportunity,
    bidops.opportunity_link,
    bidops.judgment,
    bidops.judgment_revision,
    bidops.perspective,
    bidops.screening_evidence,
    bidops.counterargument,
    bidops.verification_item,
    bidops.matched_performance,
    bidops.attachment,
    bidops.attachment_fetch,
    bidops.agency_portal,
    bidops.review,
    bidops.review_revision,
    bidops.verification_answer,
    bidops.ingest_warning,
    bidops.content_object,
    bidops.content_object_location,
    bidops.content_scan,
    bidops.document_version,
    bidops.document_structure,
    bidops.document_block,
    bidops.document_bundle,
    bidops.document_bundle_item,
    bidops.prespec_overview_run,
    bidops.prespec_v4_pdf_snapshot,
    bidops.profile_version,
    bidops.profile_evidence,
    bidops.analysis_policy_version,
    bidops.deep_review,
    bidops.deep_review_attempt,
    bidops.deep_review_stage,
    bidops.claim,
    bidops.evidence_ref,
    bidops.claim_evidence,
    bidops.report_revision,
    bidops.report_revision_evidence,
    bidops.validation_run,
    bidops.validation_check,
    bidops.final_opinion,
    bidops.bid_final_decision,
    bidops.work_job,
    bidops.idempotency_record,
    bidops.audit_event,
    bidops.screening_execution,
    bidops.screening_attempt,
    bidops.company_profile_snapshot,
    bidops.quality_gate,
    bidops.quality_gate_evaluation,
    bidops.screening_policy,
    bidops.quality_gate_review,
    bidops.schedule_setting,
    bidops.schedule_reservation,
    bidops.schedule_execution,
    bidops.always_on_state,
    bidops.screening_audit_event,
    bidops.document_segment_manifest,
    bidops.document_segment,
    bidops.requirement_inventory_item,
    bidops.order_plan_screening_policy,
    bidops.order_plan_screening_execution,
    bidops.order_plan_screening_batch_attempt,
    bidops.order_plan_screening_artifact,
    bidops.order_plan_screening_result,
    bidops.order_plan_screening_feedback,
    bidops.collected_record_index,
    bidops.collected_record_token
TO app;

-- Mutable source projections expose only their refreshable columns.  Their
-- identifiers and immutable observation snapshots cannot be updated.
GRANT UPDATE (
    window_from, window_to, timezone, screening_basis, status,
    superseded_by, counts_json
) ON bidops.run TO app;
GRANT UPDATE (
    bid_no, bid_ord, source_type, title, agency, demand_agency, published_at,
    deadline_at, budget, estimated_price, method, url, sample_role,
    sample_stratum, collection_bucket, procurement_class_json,
    region_limit_json, lifecycle_json, qualification_flags_json,
    focus_matches_json, performance_matches_json, performance_top_score,
    candidate_sources_json, unknown_fields_json, raw_source
) ON bidops.notice TO app;
GRANT UPDATE (
    title, agency_code, agency_name, supervising_agency_name,
    business_division, business_division_code, service_type,
    service_type_code, budget_amount, contract_amount, planned_order_year,
    planned_order_month, procurement_method, contract_method, published_at,
    changed_at, bid_ntice_no_list, notice_posted, source_url,
    first_discovered_at, last_discovered_at, source_sha256,
    unknown_fields_json, raw_source
) ON bidops.order_plan TO app;
GRANT UPDATE (
    name, source_url, origin, file_ext, size_bytes, legacy_stored_path,
    extract_status, source_system, source_attachment_key, last_seen_at,
    retired_at, retired_reason, retired_by_name
) ON bidops.attachment TO app;
-- The collection index is a search projection of immutable run files.  Only
-- the selection outcome is written after insert; the observed record values,
-- run identity, and tokens are never rewritten.  Tokens are append-only.
GRANT UPDATE (
    selection_reason, ingested_notice_id, ingested_order_plan_id
) ON bidops.collected_record_index TO app;
GRANT UPDATE (
    version, role, effective_date, replaces_document_version_id, is_current,
    safety_status, needs_human_review
) ON bidops.document_version TO app;
-- bundle confirm의 행 잠금(FOR UPDATE)에 필요. PostgreSQL은 SELECT ... FOR UPDATE
-- 에도 대상 테이블 한 열의 UPDATE 권한을 요구한다. structure identity는 잠금
-- 대상으로만 쓰며 app은 구조 행을 다시 쓰지 않는다 (`notice.id`와 같은 이유).
GRANT UPDATE (id) ON bidops.document_structure TO app;
-- 최종 Go/No-Go 기록(ADR-0058)이 직전 결정 tip을 `SELECT ... FOR UPDATE`로 잠근다.
-- 결정 행은 append-only이며(trigger가 모든 UPDATE·DELETE를 거부) app은 잠금 대상
-- 식별자 한 열만 갖는다. 비교 계산 계보(comparison·attempt·item·evidence)는 닫혀 있다.
GRANT UPDATE (id) ON bidops.bid_final_decision TO app;

-- Human-facing rows are mutable only through their API-owned fields.  The
-- immutable identity, actor, and creation columns are never update targets.
GRANT UPDATE (
    run_id, disposition, system_judgment_review, corrected_grade,
    corrected_readiness, weakest_perspective, reason, reviewer_snapshot,
    updated_at
) ON bidops.review TO app;
GRANT UPDATE (
    execution_id, decision_digest, evidence_judgment, note, updated_at
) ON bidops.quality_gate_review TO app;
GRANT UPDATE (
    status, active_slot, activated_at, activated_by, quality_gate_result_id
) ON bidops.screening_policy TO app;
GRANT UPDATE (
    policy_status, active_slot, activated_at, activated_by
) ON bidops.order_plan_screening_policy TO app;
GRANT UPDATE (
    status, active_slot, partial_artifact, candidate_count, completed_count,
    failure_count, stage1_selected_count, stage1_filtered_out_count,
    stage1_failed_count, stage2_relevant_count, stage2_not_relevant_count,
    stage2_uncertain_count, stage2_failed_count, stage2_rejected_count,
    human_review_count, error_code, started_at, finished_at
) ON bidops.order_plan_screening_execution TO app;

-- Service-owned mutable state.  Append-only profile/policy inputs, source
-- observations, claims, revision/opinion history, and audit rows are absent.
-- The worker may advance fetch/deep-review queues only.  Overview review
-- transitions below remain column-scoped and snapshots remain immutable.
GRANT UPDATE ON TABLE
    bidops.prespec_overview_run,
    bidops.opportunity,
    bidops.opportunity_link,
    bidops.judgment,
    bidops.attachment_fetch,
    bidops.agency_portal,
    bidops.document_bundle,
    bidops.document_bundle_item,
    bidops.deep_review,
    bidops.deep_review_attempt,
    bidops.deep_review_stage,
    bidops.work_job,
    bidops.screening_execution,
    bidops.quality_gate,
    bidops.schedule_setting,
    bidops.schedule_reservation,
    bidops.schedule_execution,
    bidops.always_on_state
TO app;

-- Deletes are limited to explicit replacement/cleanup behavior.  Human
-- reviews, final opinions, report revisions, profiles, policies, audits, and
-- immutable source observations are deliberately not deletable.
GRANT DELETE ON TABLE
    bidops.run,
    bidops.judgment,
    bidops.perspective,
    bidops.screening_evidence,
    bidops.counterargument,
    bidops.verification_item,
    bidops.matched_performance,
    bidops.attachment,
    bidops.verification_answer,
    bidops.ingest_warning,
    bidops.document_bundle_item
TO app;

-- Current integer identity columns are consumed only by app-owned INSERTs.
-- App/worker inherit no sequence privileges; future runtime use needs review.
-- The backup role separately receives SELECT only, never sequence mutation.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA bidops TO app;

-- The shared worker credential covers the analysis worker and the optional
-- pre-spec attachment worker. Reads include the review/snapshot lineage and
-- phase-2 attempt/result/event rows needed by the lifecycle worker. Legacy
-- reviews, screening policy controls, and schedules are not in this list.
GRANT SELECT ON TABLE
    bidops.alembic_version,
    bidops.notice,
    bidops.judgment,
    bidops.judgment_revision,
    bidops.review,
    bidops.review_revision,
    bidops.attachment,
    bidops.attachment_fetch,
    bidops.content_object,
    bidops.content_object_location,
    bidops.content_scan,
    bidops.document_version,
    bidops.document_structure,
    bidops.document_block,
    bidops.document_bundle,
    bidops.document_bundle_item,
    bidops.profile_version,
    bidops.profile_evidence,
    bidops.analysis_policy_version,
    bidops.deep_review,
    bidops.deep_review_attempt,
    bidops.deep_review_stage,
    bidops.claim,
    bidops.evidence_ref,
    bidops.claim_evidence,
    bidops.report_revision,
    bidops.report_revision_evidence,
    bidops.validation_run,
    bidops.validation_check,
    bidops.final_opinion,
    bidops.work_job,
    bidops.idempotency_record,
    bidops.audit_event,
    bidops.prespec_overview_run,
    bidops.prespec_company_fit_attempt,
    bidops.prespec_v4_pdf_snapshot,
    bidops.document_segment_manifest,
    bidops.document_segment,
    bidops.requirement_inventory_item,
    bidops.order_plan,
    bidops.order_plan_observation,
    bidops.order_plan_screening_policy,
    bidops.order_plan_screening_execution,
    bidops.order_plan_screening_batch_attempt,
    bidops.order_plan_screening_artifact,
    bidops.collected_record_index
TO worker;

GRANT INSERT ON TABLE
    bidops.content_object,
    bidops.content_object_location,
    bidops.content_scan,
    bidops.document_version,
    bidops.document_structure,
    bidops.document_block,
    bidops.claim,
    bidops.evidence_ref,
    bidops.claim_evidence,
    bidops.report_revision,
    bidops.report_revision_evidence,
    bidops.validation_run,
    bidops.validation_check,
    bidops.audit_event,
    bidops.prespec_overview_run,
    bidops.prespec_v4_pdf_snapshot,
    bidops.prespec_company_fit_attempt,
    bidops.document_segment_manifest,
    bidops.document_segment,
    bidops.requirement_inventory_item,
    bidops.order_plan_screening_batch_attempt,
    bidops.order_plan_screening_artifact,
    bidops.order_plan_screening_result
TO worker;

GRANT UPDATE ON TABLE
    bidops.prespec_overview_run,
    bidops.attachment_fetch,
    bidops.deep_review,
    bidops.deep_review_attempt,
    bidops.deep_review_stage,
    bidops.work_job
TO worker;
-- PostgreSQL row locks require UPDATE on at least one column. Notice identity
-- is only used as the lock target; the worker never rewrites notice metadata.
GRANT UPDATE (id) ON bidops.notice TO worker;
GRANT UPDATE (extract_status) ON bidops.attachment TO worker;
GRANT UPDATE (is_current) ON bidops.document_version TO worker;
GRANT UPDATE (
    attempt_status, failure_type, failure_code, response_object_ref,
    input_tokens, cached_input_tokens, output_tokens, total_tokens,
    duration_ms, started_at, finished_at
) ON bidops.order_plan_screening_batch_attempt TO worker;
GRANT UPDATE (
    status, active_slot, partial_artifact, candidate_count, completed_count,
    failure_count, stage1_selected_count, stage1_filtered_out_count,
    stage1_failed_count, stage2_relevant_count, stage2_not_relevant_count,
    stage2_uncertain_count, stage2_failed_count, stage2_rejected_count,
    human_review_count, error_code, started_at, finished_at, heartbeat_at
) ON bidops.order_plan_screening_execution TO worker;
GRANT UPDATE (is_current) ON bidops.document_version TO worker;

GRANT UPDATE (
    status, result_jsonb, result_sha256, raw_response_sha256, error_code,
    lease_owner, lease_expires_at, completed_at, prompt_tokens, output_tokens, latency_ms
) ON bidops.prespec_company_fit_attempt TO worker;

-- 사전규격 첨부 worker의 자동 문서 준비 경로(명세 §6.2·§6.3). 취득 행이 종결되면
-- `prespec_attachments.fetch_claimed`가 `auto_preparation.maybe_auto_prepare`를 부르고,
-- 그 안에서 사람 경로와 **같은** 서비스 함수가 묶음을 만들고 확정한 뒤 개요 run을
-- 큐에 넣는다. 아래는 그 경로가 실제로 실행하는 쓰기만 연다.
-- auto_preparation._prepare_one -> DocumentBundleService.create_bundle: 묶음 초안 INSERT
GRANT INSERT ON TABLE bidops.document_bundle TO worker;
-- create_bundle/confirm의 _seed_bundle_items: 확정 범위 item snapshot INSERT
GRANT INSERT ON TABLE bidops.document_bundle_item TO worker;
-- DocumentBundleService.confirm: 확정 요청 재생을 위한 idempotency 기록 INSERT
GRANT INSERT ON TABLE bidops.idempotency_record TO worker;
-- auto_preparation._enqueue_overview -> overview_runs.enqueue_overview_run: 개요 run의 큐 행 INSERT
GRANT INSERT ON TABLE bidops.work_job TO worker;
-- create_bundle의 issue snapshot 기록과 confirm의 version fence·확정 표식·supersede만
-- 연다. revision·notice_id·created_by_name 같은 계보 열은 닫혀 있고, 이 열 권한이
-- confirm의 `SELECT ... FOR UPDATE` 행 잠금도 함께 만족시킨다.
GRANT UPDATE (
    issues_snapshot, status, version, confirmed_by_name, confirmed_at
) ON bidops.document_bundle TO worker;
-- confirm이 구조 행을 잠그기만 한다(app과 같은 이유). 구조 상태(validation_status)는
-- worker에게 닫혀 있다.
GRANT UPDATE (id) ON bidops.document_structure TO worker;
-- 문서 집합·순서가 그대로면 `_seed_bundle_items`가 draft item을 제자리로 갱신한다.
-- 확정 시 다시 쓰는 snapshot 열만 열고 `ordinal`은 닫아 둔다 — worker는 항목 순서를
-- 바꾸지 못하고, DELETE 없이 확정이 끝난다.
GRANT UPDATE (
    document_version_version, content_object_id, content_sha256, detected_mime,
    size_bytes, original_filename, source_kind, source_system,
    source_attachment_key, source_url, role_at_confirmation,
    effective_date_at_confirmation, replaces_id_at_confirmation,
    is_current_at_confirmation, safety_status_at_confirmation,
    structure_id_at_confirmation, structure_payload_sha256
) ON bidops.document_bundle_item TO worker;

-- Backup reads current/future tables and sequence state without advancing it.
GRANT SELECT ON ALL TABLES IN SCHEMA bidops TO ro_backup;
ALTER DEFAULT PRIVILEGES IN SCHEMA bidops GRANT SELECT ON TABLES TO ro_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA bidops TO ro_backup;
ALTER DEFAULT PRIVILEGES IN SCHEMA bidops GRANT SELECT ON SEQUENCES TO ro_backup;

COMMIT;
