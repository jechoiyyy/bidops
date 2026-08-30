export type JsonValue = unknown;

export interface PageFilters {
  run_id: string;
  grade: string | null;
  readiness: string | null;
  focus: string | null;
  sample_role: string | null;
  attachment: "any" | "none" | "manual";
  q: string | null;
  sort: "deadline" | "grade" | "published";
  limit: number;
  offset: number;
}

export interface AttachmentResponse {
  id: number;
  name: string | null;
  url: string | null;
  origin: string | null;
  file_ext: string | null;
  size_bytes: number | null;
  stored_path: string | null;
  extract_status: string | null;
  created_at: string | null;
}

export interface AgencyPortal {
  id: number;
  agency_pattern: string;
  system_name: string;
  search_url_template: string;
  enabled: boolean;
  note: string | null;
}

export interface AttachmentProcedureResponse {
  notice_pk: number;
  agency: string | null;
  bid_no: string | null;
  title: string | null;
  status: "provided" | "missing" | "completed" | string;
  matched_portal: AgencyPortal | null;
  search_url: string | null;
  portal_message: string;
  steps: string[];
  attachments: AttachmentResponse[];
}

export interface AttachmentQueueItem extends NoticeListItem {
  bid_no: string | null;
  matched_portal: AgencyPortal | null;
  search_url: string | null;
  portal_message: string;
}

export interface AttachmentQueueResponse {
  run_id: string;
  total: number;
  items: AttachmentQueueItem[];
}

export interface EvidenceResponse {
  id: number;
  source: string | null;
  status: string | null;
  fact: string | null;
}

export interface PerspectiveResponse {
  id: number;
  position: number | null;
  name: string | null;
  assessment: string | null;
  reason: string | null;
  evidence: EvidenceResponse[];
}

export interface CounterargumentResponse {
  id: number;
  position: number | null;
  text: string | null;
}

export interface VerificationItemResponse {
  id: number;
  item: string | null;
  why: string | null;
  blocking: boolean;
  status: string | null;
}

export interface MatchedPerformanceResponse {
  id: number;
  name: string | null;
  match_reason: string | null;
  mismatch_or_limit: string | null;
  source: string | null;
  status: string | null;
}

export interface ReviewAnswerResponse {
  id: number;
  item: string | null;
  answer: string | null;
}

export interface ReviewAnswerInput {
  item: string | null;
  answer: string | null;
}

export interface ReviewUpsertRequest {
  run_id: string;
  disposition: string | null;
  system_judgment_review: string | null;
  corrected_grade: string | null;
  corrected_readiness: string | null;
  weakest_perspective: string | null;
  reason: string | null;
  reviewer?: string | null;
  verification_answers: ReviewAnswerInput[];
}

export interface ReviewResponse {
  id: number;
  run_id: string;
  notice_pk: number;
  disposition: string | null;
  system_judgment_review: string | null;
  corrected_grade: string | null;
  corrected_readiness: string | null;
  weakest_perspective: string | null;
  reason: string | null;
  reviewer: string | null;
  created_at: string | null;
  updated_at: string | null;
  answers: ReviewAnswerResponse[];
}

export interface JudgmentResponse {
  id: number;
  schema_version: string | null;
  grade: string | null;
  readiness: string | null;
  primary_focus: string | null;
  exclusion_category: string | null;
  summary: string | null;
  next_action: string | null;
  perspectives: PerspectiveResponse[];
  counterarguments: CounterargumentResponse[];
  verification_items: VerificationItemResponse[];
  matched_performances: MatchedPerformanceResponse[];
}

export interface NoticeListItem {
  id: number;
  notice_key: string;
  run_id: string;
  title: string | null;
  agency: string | null;
  published_at: string | null;
  deadline_at: string | null;
  estimated_price: number | null;
  sample_role: string | null;
  sample_stratum: string | null;
  collection_bucket: string | null;
  grade: string | null;
  readiness: string | null;
  focus: string | null;
  attachment_count: number;
  attachment_status: "none" | "g2b" | "manual";
}

export interface NoticeDetailResponse extends NoticeListItem {
  bid_no: string | null;
  bid_ord: string | null;
  source_type: string | null;
  budget: number | null;
  method: string | null;
  url: string | null;
  timezone: string;
  procurement_class: JsonValue;
  region_limit: JsonValue;
  lifecycle: JsonValue;
  qualification_flags: JsonValue;
  focus_matches: JsonValue[];
  performance_matches: JsonValue[];
  performance_top_score: number | null;
  candidate_sources: JsonValue[];
  judgment: JudgmentResponse | null;
  attachments: AttachmentResponse[];
  reviews: ReviewResponse[];
}

export interface NoticeListResponse {
  items: NoticeListItem[];
  total: number;
  filters: PageFilters;
}

export interface HistoryItemResponse {
  notice_pk: number;
  run_id: string;
  window_from: string | null;
  window_to: string | null;
  timezone: string;
  generated_at: string;
  grade: string | null;
  readiness: string | null;
  focus: string | null;
  summary: string | null;
  corrected_grade: string | null;
  corrected_readiness: string | null;
  review_reason: string | null;
}

export interface NoticeHistoryResponse {
  notice_key: string;
  items: HistoryItemResponse[];
}

export type RelatedNoticeRelation = "ordinal" | "unified" | "pre_spec";

export interface RelatedNoticeResponse {
  relation: RelatedNoticeRelation;
  notice_pk: number;
  notice_key: string;
  title: string | null;
  grade: string | null;
  published_at: string | null;
  change_reason: string | null;
}

export interface RelatedNoticeListResponse {
  notice_pk: number;
  items: RelatedNoticeResponse[];
}

export interface WarningResponse {
  id: number;
  run_id: string;
  level: string;
  code: string;
  message: string;
  context: JsonValue;
}

export interface WarningListResponse {
  run_id: string;
  items: WarningResponse[];
  total: number;
  level: string | null;
  code: string | null;
}

export interface RunCounts {
  notices: number;
  judgments: number;
  reviews: number;
  collection: Record<string, JsonValue>;
}

export interface RunSummary {
  run_id: string;
  window_from: string | null;
  window_to: string | null;
  timezone: string;
  generated_at: string;
  screening_basis: string | null;
  status: string;
  superseded_by: string | null;
  counts: RunCounts;
}

export interface RunListResponse {
  items: RunSummary[];
  total: number;
}

export interface ArtifactValidationResponse {
  name: string;
  present: boolean;
  schema_version: string | null;
  expected_schema_version: string | null;
  valid: boolean | null;
  warnings: string[];
}

export interface PipelineStageResponse {
  name: string;
  status: string;
  artifact: string | null;
  script: string | null;
  execution_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  execution_allowed: boolean;
  message: string | null;
}

export interface CollectionScopeResponse {
  window_from: string | null;
  window_to: string | null;
  timezone: string;
  business_area: string | null;
  pre_spec_available: boolean | null;
  pre_spec_reason: string | null;
  focus_axes: string[];
  performance_reference_count: number | null;
}

export interface RunDetailResponse extends RunSummary {
  collection_scope: CollectionScopeResponse;
  pipeline: PipelineStageResponse[];
  artifacts: ArtifactValidationResponse[];
  warning_counts: Record<string, number>;
}

export interface PipelineExecutionResponse {
  execution_id: string;
  source_run_id: string;
  result_run_id: string | null;
  stage: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  error: string | null;
  log_count: number;
}

export interface PipelineLogLineResponse {
  timestamp: string;
  stream: string;
  level: string;
  message: string;
}

export interface PipelineLogResponse {
  run_id: string;
  executions: PipelineExecutionResponse[];
  items: PipelineLogLineResponse[];
  total: number;
}

export interface FunnelItem {
  key: string;
  label: string;
  count: number | null;
}

export interface DistributionItem {
  key: string;
  label: string;
  count: number;
}

export interface VerificationRequest {
  item: string;
  count: number;
  notice_pks: number[];
  profile_sections: string[];
}

export interface DeadlineNotice extends NoticeListItem {
  blocking_verification_items: string[];
}

export interface RunStatsResponse {
  run_id: string;
  timezone: string;
  generated_at: string;
  collected_count: number | null;
  candidate_count: number | null;
  sample_count: number;
  priority_review_count: number;
  audit_missed_count: number;
  funnel: FunnelItem[];
  grade_distribution: DistributionItem[];
  readiness_distribution: DistributionItem[];
  focus_distribution: DistributionItem[];
  verification_requests: VerificationRequest[];
  imminent_deadlines: DeadlineNotice[];
}

export interface IngestRequest {
  run_id: string | null;
}

export interface IngestResponse {
  run_id: string;
  notices: number;
  judgments: number;
  reviews: number;
  warnings: WarningResponse[];
  warning_counts: Record<string, number>;
}

export interface MetricBasis {
  numerator: number;
  denominator: number;
  detail: Record<string, JsonValue>;
}

export interface ValidationMetric {
  key: string;
  label: string;
  value: number | null;
  percentage: number | null;
  threshold: JsonValue;
  meets_threshold: boolean | null;
  status: "pass" | "fail" | "measured" | "not_measurable";
  basis: MetricBasis;
  reason: string | null;
}

export interface ValidationMetricsResponse {
  run_id: string;
  metrics: ValidationMetric[];
}

export type ProfileStatus = "confirmed" | "inferred" | "unknown";
export type ProfileSectionState = ProfileStatus | "mixed" | "unrecorded";

export interface ProfileRawBlock {
  line_start: number;
  raw: string;
  error: string;
}

export interface ProfileItem {
  key: string;
  label: string;
  section_id: string;
  section_number: string | null;
  status: ProfileStatus;
  value: JsonValue;
  source_line: number | null;
}

export interface ProfileSection {
  id: string;
  number: string | null;
  title: string;
  heading: string;
  level: number;
  state: ProfileSectionState;
  status_counts: Record<string, number>;
  items: ProfileItem[];
  raw_blocks: ProfileRawBlock[];
  raw: string | null;
  children: ProfileSection[];
}

export interface ProfileSectionsResponse {
  source: string;
  sections: ProfileSection[];
  status_counts: Record<string, number>;
  parse_errors: string[];
}

export interface ProfileUnknown {
  key: string;
  label: string;
  section_id: string;
  section_number: string | null;
  section_title: string;
  status: "unknown";
  value: JsonValue;
  reference_count: number | null;
  reference_status: "counted" | "unavailable";
}

export interface ProfileUnknownsResponse {
  source: string;
  items: ProfileUnknown[];
  total: number;
  reference_fields: string[];
  parse_errors: string[];
}

// ---------------------------------------------------------------------------
// Screening runtime REST contracts
//
// These types intentionally mirror the strict metadata-only contracts in
// backend/app/schemas.py.  Datetimes and dates remain ISO strings at the
// transport boundary; callers can format them for display without losing the
// timezone or the original date value.

export type Actor = string;
export type Digest = string;
export type CompanyProfileVersion = string;
export type ProfileSource = "current" | `git:${string}`;

export type ScreeningTrigger = "cli_single" | "manual_run" | "quality_gate" | "schedule";
export type ScreeningScope = "single_notice" | "full_run" | "quality_sample";
export type ScreeningStatus =
  | "대기"
  | "실행 중"
  | "중지 요청"
  | "성공"
  | "부분 성공"
  | "실패"
  | "중단됨";
export type ScreeningStage =
  | "기술 적합성"
  | "실적 정합성"
  | "공공 SI 적합성"
  | "사업성·자격 제약"
  | "전략 부합"
  | "counterargument"
  | "synthesis"
  | "merge"
  | "publish";
export type ScreeningAttemptStage =
  | "기술 적합성"
  | "실적 정합성"
  | "공공 SI 적합성"
  | "사업성·자격 제약"
  | "전략 부합"
  | "counterargument"
  | "synthesis"
  | "carried_over_validation";
export type ScreeningFailureType =
  | "timeout"
  | "truncated_output"
  | "schema_violation"
  | "evidence_missing"
  | "counterargument_repetition";
export type ScreeningArtifactKind = "decisions" | "failures" | "telemetry" | "screening_result";

export interface JudgmentExecutionCreateRequest {
  policy_version: string;
  profile_source: ProfileSource;
  requested_by: Actor;
}

export interface ScreeningStopRequest {
  requested_by: Actor;
}

export interface ScreeningArtifactUrls {
  decisions: string | null;
  failures: string | null;
  telemetry: string | null;
  screening_result: string | null;
  published_run: string | null;
}

export interface ScreeningExecutionResponse {
  queue_no: number;
  execution_id: string;
  trigger: ScreeningTrigger;
  source_run_id: string;
  scope: ScreeningScope;
  notice_id: string | null;
  status: ScreeningStatus;
  requested_by: Actor;
  policy_version: string;
  prompt_version: string;
  model_name: string;
  model_digest: Digest;
  company_profile_version: CompanyProfileVersion;
  company_profile_digest: Digest;
  input_artifact_digest: Digest;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
  stop_requested_at: string | null;
  stop_requested_by: Actor | null;
  stop_reason: "user_requested" | "process_interrupted" | null;
  candidate_count: number;
  completed_count: number;
  failure_count: number;
  published_run_id: string | null;
  error_summary: string | null;
  queue_position: number | null;
  current_notice_id: string | null;
  current_stage: ScreeningStage | null;
  result_urls: ScreeningArtifactUrls;
}

export interface ScreeningAttemptResponse {
  attempt_id: number;
  execution_id: string;
  notice_id: string;
  stage: ScreeningAttemptStage;
  attempt_no: number;
  status: "success" | "failure";
  failure_type: ScreeningFailureType | null;
  done_reason: string | null;
  trace_id: string;
  span_id: string;
  prompt_eval_count: number | null;
  eval_count: number | null;
  prompt_eval_duration_ns: number | null;
  eval_duration_ns: number | null;
  load_duration_ns: number | null;
  total_duration_ns: number | null;
  started_at: string;
  finished_at: string;
  error_summary: string | null;
}

export type ScreeningFailureStage =
  | "기술 적합성"
  | "실적 정합성"
  | "공공 SI 적합성"
  | "사업성·자격 제약"
  | "전략 부합"
  | "반론 검토"
  | "종합 판정"
  | "병합·검증";

export interface ScreeningFailureItem {
  notice_id: string;
  failed_stage: ScreeningFailureStage;
  failure_type: ScreeningFailureType;
  last_attempt_at: string;
  retry_count: number;
  status: "사람 검토 대기";
  failure_context: "carried_over_validation" | null;
  trace_id: string | null;
  span_id: string | null;
  error_summary: string;
}

export interface ScreeningExecutionListResponse {
  items: ScreeningExecutionResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface ScreeningExecutionDetailResponse extends ScreeningExecutionResponse {
  attempts: ScreeningAttemptResponse[];
  failures: ScreeningFailureItem[];
}

export interface ScreeningExecutionQuery {
  status?: ScreeningStatus;
  trigger?: ScreeningTrigger;
  run_id?: string;
  limit?: number;
  offset?: number;
}

export type CompanyProfileSnapshotSourceKind = "working_tree" | "git_blob";

export interface CompanyProfileSnapshotResponse {
  version: CompanyProfileVersion;
  digest: Digest;
  source_kind: CompanyProfileSnapshotSourceKind;
  source_ref: string;
  created_at: string;
}

export interface CompanyProfileSnapshotListResponse {
  items: CompanyProfileSnapshotResponse[];
  total: number;
}

export type QualityGatePurpose = "model_comparison" | "operational_approval";
export type QualityGateExecutionStatus = "대기" | "실행 중" | "완료" | "실패" | "중단됨";
export type QualityGateResultStatus = "통과" | "미달" | "미측정" | "보류";
export type QualityGateEvidenceJudgment = "동의" | "근거 부족" | "판단 보류";
export type RuntimeJsonObject = Record<string, JsonValue>;

export interface QualityGateCreateRequest {
  purpose: QualityGatePurpose;
  policy_version: string;
  profile_source: ProfileSource;
  created_by: Actor;
}

export interface QualityGateEvaluationResponse {
  evaluation_id: string;
  gate_id: string;
  revision: number;
  result_status: QualityGateResultStatus;
  metrics: RuntimeJsonObject;
  reasons: string[];
  valid_review_count: number;
  distinct_notice_review_count: number;
  created_at: string;
}

export interface QualityGateReviewResponse {
  review_id: number;
  gate_id: string;
  execution_id: string;
  notice_id: string;
  decision_digest: Digest;
  reviewer: Actor;
  evidence_judgment: QualityGateEvidenceJudgment;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface QualityGateReviewUpsertRequest {
  reviewer: Actor;
  evidence_judgment: QualityGateEvidenceJudgment;
  note: string | null;
}

export interface QualityGateResponse {
  gate_id: string;
  purpose: QualityGatePurpose;
  execution_status: QualityGateExecutionStatus;
  result_status: QualityGateResultStatus;
  baseline_run_id: string;
  sample_artifact_digest: Digest;
  baseline_decisions_digest: Digest;
  policy_version: string;
  prompt_version: string;
  model_name: string;
  model_digest: Digest;
  company_profile_version: CompanyProfileVersion;
  company_profile_digest: Digest;
  pass_a_execution_id: string;
  pass_b_execution_id: string;
  created_by: Actor;
  created_at: string;
  completed_at: string | null;
  latest_evaluation_id: string;
  metrics: RuntimeJsonObject;
  reasons: string[];
}

export interface QualityGateDetailResponse extends QualityGateResponse {
  pass_a: ScreeningExecutionResponse;
  pass_b: ScreeningExecutionResponse;
  evaluations: QualityGateEvaluationResponse[];
  reviews: QualityGateReviewResponse[];
}

export interface QualityGateListResponse {
  items: QualityGateResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface QualityGateQuery {
  purpose?: QualityGatePurpose;
  execution_status?: QualityGateExecutionStatus;
  result_status?: QualityGateResultStatus;
  limit?: number;
  offset?: number;
}

export type PolicyStatus = "draft" | "activation_candidate" | "active";

export interface PolicyVersionCreateRequest {
  policy_version: string;
  created_by: Actor;
  prompt_version: string;
  perspective_prompts: RuntimeJsonObject;
  counterargument_prompt: RuntimeJsonObject;
  synthesis_prompt: RuntimeJsonObject;
  candidate_selection: RuntimeJsonObject;
  thresholds: RuntimeJsonObject;
}

export interface PolicyCandidateRequest {
  confirmed_by: Actor;
}

export interface PolicyActivationRequest {
  quality_gate_result_id: string;
  confirmed_by: Actor;
}

export interface PolicyVersionResponse {
  schema_version: "bidops.screening-policy.v1";
  policy_version: string;
  prompt_version: string;
  perspective_prompts: RuntimeJsonObject;
  counterargument_prompt: RuntimeJsonObject;
  synthesis_prompt: RuntimeJsonObject;
  candidate_selection: RuntimeJsonObject;
  thresholds: RuntimeJsonObject;
  content_digest: Digest;
  status: PolicyStatus;
  created_at: string;
  created_by: Actor;
  activated_at: string | null;
  activated_by: Actor | null;
  quality_gate_result_id: string | null;
}

export interface PolicyVersionListResponse {
  items: PolicyVersionResponse[];
  total: number;
  active_policy_version: string | null;
}

export interface PolicyVersionQuery {
  status?: PolicyStatus;
}

export interface PolicyActivationResponse {
  policy: PolicyVersionResponse;
  previous_active_policy_version: string | null;
  quality_gate_result_id: string;
  activation_status: "activated";
  activated_at: string;
}

export interface ScheduleSettingsResponse {
  timezone: "Asia/Seoul";
  daily_time: string;
  weekly_time: string;
  prespec_enabled: boolean;
  updated_at: string;
  updated_by: Actor;
}

export interface ScheduleSettingsUpdateRequest {
  daily_time?: string;
  weekly_time?: string;
  prespec_enabled?: boolean;
  updated_by: Actor;
}

export type ScheduleJobKind = "daily" | "weekly";
export type ScheduleStatus = "예약" | "실행 중" | "성공" | "부분 성공" | "실패" | "건너뜀";
export type ScheduleTrigger = "schedule" | "manual";

export interface ScheduleExecutionCreateRequest {
  job_kind: ScheduleJobKind;
  window_from: string;
  window_to: string;
  recovery_of_execution_id: string | null;
  requested_by: Actor;
}

export interface ScheduleExecutionSummary {
  run_key: string;
  run_id: string | null;
  window_from: string;
  window_to: string;
  job_kind: ScheduleJobKind;
  status: ScheduleStatus;
  execution_id: string;
  trigger: ScheduleTrigger;
  duplicate_of_execution_id: string | null;
  recovery_of_execution_id: string | null;
  skip_reason: string | null;
  failure_reason: string | null;
  requested_by: Actor;
  started_at: string | null;
  finished_at: string | null;
  candidate_count: number | null;
  result_count: number | null;
  failure_count: number | null;
  partial_artifact: boolean | null;
  policy_version: string | null;
  model_name: string | null;
  model_digest: Digest | null;
  prompt_version: string | null;
  company_profile_version: CompanyProfileVersion | null;
  company_profile_digest: Digest | null;
}

export interface ScheduleExecutionListResponse {
  items: ScheduleExecutionSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ScheduleExecutionQuery {
  job_kind?: ScheduleJobKind;
  status?: ScheduleStatus;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}

export interface AlwaysOnSwitchUpdateRequest {
  enabled: boolean;
  confirmed_by: Actor;
  quality_gate_result_id: string | null;
}

export interface AlwaysOnSwitchResponse {
  configured_enabled: boolean;
  effective_enabled: boolean;
  environment_enabled: boolean;
  quality_gate_status: QualityGateResultStatus | null;
  quality_gate_result_id: string | null;
  policy_version: string | null;
  model_name: string | null;
  model_digest: Digest | null;
  prompt_version: string | null;
  company_profile_version: CompanyProfileVersion | null;
  company_profile_digest: Digest | null;
  updated_at: string;
  updated_by: Actor;
  rejection_reason: string | null;
}

// 누적 사업기회. 회차 단위 공고 목록과 달리 외부 식별자로 누적된다.
// 계약은 docs/contracts.md의 `## 현재 REST 경로`에 있다.
export type OpportunityTrackingStatus = "미선택" | "계속 추적" | "보류" | "종료";
export type OpportunityFirstRegisteredStage = "order_plan" | "pre_spec" | "bid_notice";
export type OpportunityLinkStage = "order_plan" | "notice";
export type OpportunityLinkType = "official" | "candidate";
export type OpportunityLinkStatus = "확정" | "후보 확인 대기" | "사람 확인 완료" | "검색 미확인";
export type OpportunitySearchStrategy =
  | "full"
  | "breaking_split"
  | "normalized"
  | "longest_fragment"
  | "prefix12";

export interface OpportunityLinkView {
  id: number;
  stage: OpportunityLinkStage;
  link_type: OpportunityLinkType;
  status: OpportunityLinkStatus;
  search_strategy: OpportunitySearchStrategy | null;
  attempted_strategies: OpportunitySearchStrategy[];
  agency_match: boolean | null;
  last_searched_at: string | null;
  evidence_external_no: string | null;
  evidence_bid_no: string | null;
  human_decision: "accepted" | "rejected" | null;
  reviewer_name: string | null;
  reviewed_at: string | null;
  review_reason: string | null;
  record_type: string | null;
  record_id: number | null;
  notice_id: number | null;
  order_plan_id: number | null;
  source_type: string | null;
  title: string | null;
  agency: string | null;
  external_id: string | null;
  record_external_id: string | null;
}

export interface OpportunityStateView {
  id: number;
  tracking_status: OpportunityTrackingStatus;
  tracking_reason: string | null;
  tracking_selected_by: string | null;
  tracking_selected_at: string | null;
  recheck_signal: boolean;
  recheck_signal_at: string | null;
  recheck_signal_link_id: number | null;
  first_registered_stage: OpportunityFirstRegisteredStage;
}

export interface OpportunityListItem extends OpportunityStateView {
  links: OpportunityLinkView[];
}

export interface OpportunityDetailResponse extends OpportunityStateView {
  links: OpportunityLinkView[];
}

export interface OpportunityListResponse {
  items: OpportunityListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface OpportunityListQuery {
  tracking_status?: OpportunityTrackingStatus | null;
  first_registered_stage?: OpportunityFirstRegisteredStage | null;
  sort?: "created_at" | "tracking_status" | "first_registered_stage" | null;
  limit?: number | null;
  offset?: number | null;
}

export interface TrackingStatusUpdateRequest {
  tracking_status: OpportunityTrackingStatus;
  reason: string;
}
