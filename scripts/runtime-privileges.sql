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
    bidops.prespec_overview_review,
    bidops.prespec_overview_snapshot,
    bidops.prespec_overview_attempt,
    bidops.prespec_overview_result,
    bidops.prespec_page_overview,
    bidops.prespec_company_fit_attempt,
    bidops.document_segment_manifest,
    bidops.document_segment,
    bidops.requirement_inventory_item,
    bidops.order_plan_screening_policy,
    bidops.order_plan_screening_execution,
    bidops.order_plan_screening_batch_attempt,
    bidops.order_plan_screening_result,
    bidops.order_plan_screening_artifact,
    bidops.order_plan_screening_feedback
TO app;

-- App-owned create paths include ingestion, UI mutations, orchestration, and
-- append-only audit/result/history rows. C-2 import is an app transaction:
-- worker-owned attempt/artifact/result rows are appendable here, while only
-- the worker receives their later mutable attempt-state UPDATE grant below.
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
    bidops.prespec_overview_review,
    bidops.prespec_overview_snapshot,
    bidops.document_segment_manifest,
    bidops.document_segment,
    bidops.requirement_inventory_item,
    bidops.order_plan_screening_policy,
    bidops.order_plan_screening_execution,
    bidops.order_plan_screening_batch_attempt,
    bidops.order_plan_screening_artifact,
    bidops.order_plan_screening_result,
    bidops.order_plan_screening_feedback
TO app;

-- Mutable source projections expose only their refreshable columns.  Their
-- identifiers and immutable observation snapshots cannot be updated.
GRANT UPDATE (
    window_from, window_to, timezone, screening_basis, status,
    superseded_by, counts_json
) ON bidops.run TO app;
GRANT UPDATE (
    bid_no, bid_ord, source_type, title, agency, published_at, deadline_at,
    budget, estimated_price, method, url, sample_role, sample_stratum,
    collection_bucket, procurement_class_json, region_limit_json,
    lifecycle_json, qualification_flags_json, focus_matches_json,
    performance_matches_json, performance_top_score, candidate_sources_json,
    unknown_fields_json, raw_source
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
GRANT UPDATE (
    version, role, effective_date, replaces_document_version_id, is_current,
    safety_status, needs_human_review
) ON bidops.document_version TO app;

-- Human-facing rows are mutable only through their API-owned fields.  The
-- immutable identity, actor, and creation columns are never update targets.
GRANT UPDATE (
    run_id, disposition, system_judgment_review, corrected_grade,
    corrected_readiness, weakest_perspective, reason, reviewer_snapshot,
    updated_at
) ON bidops.review TO app;
-- Overview review transitions are column-scoped; immutable snapshot rows have
-- no UPDATE grant for either runtime role.
GRANT UPDATE (
    current_snapshot_id, status, result, completed_at, updated_at
) ON bidops.prespec_overview_review TO app;
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
-- No default sequence privilege is installed, so a future sequence remains
-- unavailable until this policy is reviewed after its migration.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA bidops TO app;

-- The shared worker credential covers the analysis worker and the optional
-- pre-spec attachment worker. Reads include the review/snapshot lineage and
-- phase-2 attempt/result/event rows needed by the lifecycle worker. Legacy
-- reviews, screening policy controls, and schedules are not in this list.
GRANT SELECT ON TABLE
    bidops.notice,
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
    bidops.prespec_overview_review,
    bidops.prespec_overview_snapshot,
    bidops.prespec_overview_attempt,
    bidops.prespec_overview_result,
    bidops.prespec_page_overview,
    bidops.prespec_company_fit_attempt,
    bidops.prespec_overview_attempt_event,
    bidops.document_segment_manifest,
    bidops.document_segment,
    bidops.requirement_inventory_item,
    bidops.order_plan,
    bidops.order_plan_observation,
    bidops.order_plan_screening_policy,
    bidops.order_plan_screening_execution,
    bidops.order_plan_screening_batch_attempt,
    bidops.order_plan_screening_artifact
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
    bidops.prespec_overview_review,
    bidops.prespec_overview_snapshot,
    bidops.prespec_overview_attempt,
    bidops.prespec_overview_result,
    bidops.prespec_page_overview,
    bidops.prespec_company_fit_attempt,
    bidops.prespec_overview_attempt_event,
    bidops.document_segment_manifest,
    bidops.document_segment,
    bidops.requirement_inventory_item,
    bidops.order_plan_screening_batch_attempt,
    bidops.order_plan_screening_artifact,
    bidops.order_plan_screening_result
TO worker;

GRANT UPDATE ON TABLE
    bidops.attachment_fetch,
    bidops.deep_review,
    bidops.deep_review_attempt,
    bidops.deep_review_stage,
    bidops.work_job
TO worker;
GRANT UPDATE (
    current_snapshot_id, status, result, completed_at, updated_at
) ON bidops.prespec_overview_review TO worker;
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
GRANT UPDATE (
    status, started_at, completed_at, result_id, lease_owner, lease_expires_at
) ON bidops.prespec_overview_attempt TO worker;
GRANT UPDATE (is_current) ON bidops.document_version TO worker;

GRANT UPDATE (
    status, result_jsonb, result_sha256, raw_response_sha256, error_code,
    lease_owner, lease_expires_at, completed_at, prompt_tokens, output_tokens, latency_ms
) ON bidops.prespec_company_fit_attempt TO worker;

-- Backup remains read-only for every current and future migrated table.
GRANT SELECT ON ALL TABLES IN SCHEMA bidops TO ro_backup;
ALTER DEFAULT PRIVILEGES IN SCHEMA bidops GRANT SELECT ON TABLES TO ro_backup;

COMMIT;
