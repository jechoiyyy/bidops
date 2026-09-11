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

export type PreSpecOrigin = "추적" | "신규";
export type PreSpecSort = "published" | "deadline";

/** 사전규격 응답의 `grade`가 어디서 왔는가. 사람 정정이 있으면 `human_review`,
 * 판정만 있으면 `screening_judgment`, 둘 다 없으면 `null`(등급도 `null`)이다. */
export type PreSpecGradeSource = "screening_judgment" | "human_review";

/** 자동 문서 준비가 어디까지 갔는가. `not_applicable`은 "대상이 아니다"이며
 * "알 수 없다"가 아니다 — 제공자가 없는 배포에서도 같은 값이다. 8값 전부
 * 서버가 정하고 화면은 재계산하지 않는다. */
export type PreSpecAutoPreparationStatus =
  | "not_applicable"
  | "waiting_attachments"
  | "bundle_draft"
  | "bundle_ready"
  | "overview_running"
  | "deep_review_started"
  | "deep_review_ready_for_click"
  | "blocked";

export interface PreSpecDocumentSummary {
  attachments: number;
  "완료": number;
  "대기": number;
  "진행": number;
  "차단": number;
  "실패": number;
}

export interface PreSpecListItem {
  notice_pk: number;
  pre_spec_no: string | null;
  title: string | null;
  agency: string | null;
  published_at: string | null;
  deadline_at: string | null;
  budget: number | null;
  sw_business_status: string | null;
  business_division: string | null;
  origin: PreSpecOrigin | null;
  opportunity_id: number | null;
  tracking_status: OpportunityTrackingStatus | null;
  kept_by_tracking: boolean;
  document: PreSpecDocumentSummary;
  /** null이면 이 notice에 아직 prespec_overview_review 행이 없다(개요 검토
   * 미시작). 10개 계약값 중 어느 것도 아니므로 awaiting_document로 접어
   * 넣지 않는다. */
  overview_review_status: PreSpecOverviewReviewStatus | null;
  /** 판정도 사람 정정도 없으면 `null`이고 그때 `grade_source`도 `null`이다.
   * 화면은 `판정 없음`으로 보이며 다섯 번째 등급으로 접지 않는다. */
  grade: string | null;
  grade_source: PreSpecGradeSource | null;
  /** 서버가 정한 자동 준비 단계. 응답에서 `null`이 되지 않는다. */
  auto_preparation_status: PreSpecAutoPreparationStatus;
  /** 왜 다음 단계로 가지 않는가. 안전한 코드이며 없으면 `null`이다.
   * `null`은 정상이므로 자리표시 문구로 바꾸지 않는다. */
  auto_preparation_reason: string | null;
  /** 자동으로 시작된(또는 마지막) 심층 검토 식별자. 없으면 `null`이다. */
  latest_deep_review_id: string | null;
}

/** 개요 검토 상태 그룹 하나의 전체 건수. `limit`/`offset`과 무관하게 현재
 * 필터에 일치하는 전체 집합을 센다 — 반환된 페이지(`items`)만 세지 않는다. */
export interface PreSpecOverviewStatusCount {
  status: PreSpecOverviewReviewStatus | null;
  count: number;
}

export interface PreSpecListResponse {
  items: PreSpecListItem[];
  total: number;
  limit: number;
  offset: number;
  overview_status_counts: PreSpecOverviewStatusCount[];
}

export interface PreSpecListQuery {
  notice_pk?: number | null;
  sw_only?: boolean | null;
  auto_preparation_status?: PreSpecAutoPreparationStatus | null;
  business_division?: string | null;
  origin?: PreSpecOrigin | null;
  q?: string | null;
  sort?: PreSpecSort | null;
  limit?: number | null;
  offset?: number | null;
}

/** 개요 검토 실행 상태 10값. 목록·상세가 배지·라벨에 쓰는 계약값이며, 개요 실행
 * 세부 view 타입군(v2 리뷰·attempt·결과)은 새 계약(prespec_overview_run)으로
 * 대체되어 삭제됐지만 이 열거값 자체는 목록 계약(`overview_review_status`,
 * `PreSpecOverviewStatusCount`)이 계속 쓴다. */
export type PreSpecOverviewReviewStatus =
  | "awaiting_document"
  | "awaiting_structure"
  | "preparing"
  | "awaiting_model"
  | "queued"
  | "running"
  | "needs_human_review"
  | "completed"
  | "failed"
  | "cancelled";

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

export type RunKind = "order_plans" | "notices" | "mixed" | "unknown";

export interface RunSummary {
  kind: RunKind;
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

export type ProfileErrorCode =
  | "profile_snapshot_unavailable"
  | "profile_source_unavailable"
  | "profile_yaml_unclosed"
  | "profile_yaml_invalid"
  | "profile_section_unstructured"
  | "profile_references_unavailable";

export interface ProfileItem {
  key: string;
  label: string;
  section_id: string;
  section_number: string | null;
  status: ProfileStatus;
  value: JsonValue;
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
  error_codes: ProfileErrorCode[];
  children: ProfileSection[];
}

export interface ProfileSectionsResponse {
  schema_version: "bidops.profile-projection.v1";
  profile_version: CompanyProfileVersion;
  profile_digest: Digest;
  sections: ProfileSection[];
  status_counts: Record<string, number>;
  error_codes: ProfileErrorCode[];
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
  schema_version: "bidops.profile-projection.v1";
  profile_version: CompanyProfileVersion;
  profile_digest: Digest;
  items: ProfileUnknown[];
  total: number;
  reference_fields: string[];
  error_codes: ProfileErrorCode[];
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
  source_ref?: string;
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

export type OpportunitySection = "조치 필요" | "추적 중" | "보류" | "추적 종료";
export type OpportunitySectionCounts = Record<OpportunitySection | "미결정", number>;

export interface OpportunityStateView {
  section: OpportunitySection | null;
  pending_candidate_link_count: number;
  open_blocking_item_count: number;
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
  section_counts: OpportunitySectionCounts;
  items: OpportunityListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface OpportunityListQuery {
  section?: OpportunitySection | null;
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

/**
 * 후보 연결 하나에 대한 사람 판정 (`PATCH /opportunities/links/{id}/decision`).
 *
 * 서버는 이 계약을 이미 갖고 있었지만 화면에 진입점이 없어 `후보 확인 대기`
 * 연결을 사람이 해소할 길이 없었다. 사업 추적의 예외 작업 경로가 그 자리다
 * (ADR-0046 결정 3, PLAN 단계 E 작업 3-2).
 *
 * `accepted`는 이 후보를 이 사업기회의 관계로 확정하고, `rejected`는 관계가
 * 아니라고 기록한다. 어느 쪽도 추적 상태·적합성 등급·최종 Go/No-Go를 바꾸지
 * 않는다. 이유는 서버가 필수로 받는다(`min_length=1`).
 */
export interface CandidateLinkDecisionRequest {
  decision: "accepted" | "rejected";
  reason: string;
}

// ---------------------------------------------------------------------------
// Order-plan C-2 review REST contracts
//
// These are intentionally separate from the legacy notice screening types
// above. C-2 relevance is a title-screening signal, not a judgment grade,
// readiness, tracking decision, or final bid decision.

export type OrderPlanStage1Status = "selected" | "filtered_out" | "failed" | "rejected";
export type OrderPlanStage2Status = "not_attempted" | "success" | "failed" | "rejected" | "unknown";
export type OrderPlanRelevance = "relevant" | "not_relevant" | "uncertain";
export type OrderPlanScreeningStatus = "대기" | "실행 중" | "중지 요청" | "성공" | "부분 성공" | "실패" | "중단됨";
export type OrderPlanScreeningAttemptStatus = "running" | "success" | "failed" | "rejected";
export type OrderPlanScreeningFailureType =
  | "timeout"
  | "truncated_output"
  | "schema_violation"
  | "id_mismatch"
  | "model_mismatch"
  | "binding_mismatch"
  | "payload_not_approved"
  | "transport"
  | "policy_rejected"
  | "unknown";
export type OrderPlanScreeningArtifactKind =
  | "screening_input"
  | "ranking"
  | "decisions"
  | "failures"
  | "telemetry"
  | "screening_result";
export type OrderPlanArtifactValidationStatus = "pending" | "valid" | "invalid";
export type OrderPlanFeedbackPriority = "high" | "medium" | "low";

export interface OrderPlanHumanFeedbackSummary {
  revision: number;
  relevance: OrderPlanRelevance;
  priority: OrderPlanFeedbackPriority | null;
  memo: string | null;
  claimed_name: string;
  created_at: string;
}

/** Active authoritative order-plan owner. null means no owner, never 미선택. */
export interface OrderPlanTracking {
  opportunity_id: number;
  tracking_status: OpportunityTrackingStatus;
  tracking_reason: string | null;
  tracking_selected_by: string | null;
  tracking_selected_at: string | null;
}

export interface OrderPlanListItem {
  order_plan_pk: number;
  order_plan_unty_no: string;
  source_url: string | null;
  title: string | null;
  agency_name: string | null;
  business_division: string | null;
  budget_amount: number | null;
  planned_order_year: string | null;
  planned_order_month: string | null;
  source_run_id: string | null;
  observed_at: string | null;
  stage1_status: OrderPlanStage1Status | null;
  stage1_rank: number | null;
  stage1_score: number | null;
  nearest_capability: string | null;
  stage2_status: OrderPlanStage2Status | null;
  qwen_relevance: OrderPlanRelevance | null;
  qwen_score: number | null;
  qwen_reason: string | null;
  human_feedback: OrderPlanHumanFeedbackSummary | null;
  tracking: OrderPlanTracking | null;
}

export interface OrderPlanListResponse {
  schema_version: "order-plan-list-response.v3";
  scope: OrderPlanListScope | null;
  producer: "order-plan-review-api";
  consumer: "order-plan-review-client";
  items: OrderPlanListItem[];
  total: number;
  limit: number;
  offset: number;
}

/** Search-only missing is SQL NULL; response enums never contain missing. */
export type MissingFilter = "missing";
export type MultiValueFilter<T extends string> = T | readonly T[];
export type OrderPlanStage1Filter = OrderPlanStage1Status | MissingFilter;
export type OrderPlanStage2Filter = OrderPlanStage2Status | MissingFilter;
export type OrderPlanRelevanceFilter = OrderPlanRelevance | MissingFilter;

export interface OrderPlanListScope {
  execution_id: string;
  source_run_id: string;
  status: "성공" | "부분 성공";
  finished_at: string | null;
}

export interface OrderPlanListQuery {
  source_run_id?: string | null;
  stage1_status?: MultiValueFilter<OrderPlanStage1Filter> | null;
  stage2_status?: MultiValueFilter<OrderPlanStage2Filter> | null;
  qwen_relevance?: MultiValueFilter<OrderPlanRelevanceFilter> | null;
  human_relevance?: MultiValueFilter<OrderPlanRelevanceFilter> | null;
  tracking_status?: MultiValueFilter<OpportunityTrackingStatus> | null;
  issue?: boolean | null;
  q?: string | null;
  limit?: number | null;
  offset?: number | null;
}

export interface OrderPlanObservationView {
  source_run_id: string;
  observed_at: string;
  source_sha256: string | null;
}

export interface OrderPlanScreeningHistoryItem {
  execution_id: string;
  source_run_id: string;
  policy_version: string;
  policy_sha256: string;
  binding_sha256: string;
  execution_status: OrderPlanScreeningStatus;
  stage1_status: OrderPlanStage1Status;
  stage1_rank: number | null;
  stage1_score: number | null;
  nearest_capability: string | null;
  batch_id: string | null;
  attempt_no: number | null;
  stage2_status: OrderPlanStage2Status;
  qwen_relevance: OrderPlanRelevance | null;
  qwen_score: number | null;
  qwen_reason: string | null;
  feedback_revision_count: number;
}

export interface OrderPlanDetailResponse {
  schema_version: "order-plan-detail-response.v3";
  producer: "screening-api";
  consumer: "order-plan-review-client";
  order_plan_pk: number;
  order_plan_unty_no: string;
  source_url: string | null;
  title: string | null;
  agency_name: string | null;
  business_division: string | null;
  business_division_code: string | null;
  service_type: string | null;
  budget_amount: number | null;
  planned_order_year: string | null;
  planned_order_month: string | null;
  observations: OrderPlanObservationView[];
  screening_history: OrderPlanScreeningHistoryItem[];
  latest_human_feedback: OrderPlanHumanFeedbackSummary | null;
  tracking: OrderPlanTracking | null;
}

export interface OrderPlanScreeningHistoryResponse {
  schema_version: "order-plan-detail-response.v1";
  producer: "screening-api";
  consumer: "order-plan-review-client";
  order_plan_pk: number;
  items: OrderPlanScreeningHistoryItem[];
}

export interface OrderPlanScreeningFeedbackView {
  feedback_id: string;
  execution_id: string;
  order_plan_pk: number;
  revision: number;
  relevance: OrderPlanRelevance;
  priority: OrderPlanFeedbackPriority | null;
  memo: string | null;
  claimed_name: string;
  created_at: string;
}

export interface OrderPlanScreeningFeedbackListResponse {
  schema_version: "feedback-list-response.v1";
  producer: "screening-api";
  consumer: "order-plan-review-client";
  items: OrderPlanScreeningFeedbackView[];
}

export interface OrderPlanScreeningFeedbackCreateRequest {
  schema_version: "feedback-create-request.v1";
  producer: "human-review-client";
  consumer: "review-api";
  request_id: string;
  execution_id: string;
  relevance: OrderPlanRelevance;
  priority: OrderPlanFeedbackPriority | null;
  memo: string | null;
  expected_revision?: number | null;
}

export interface OrderPlanScreeningFeedbackCreateResponse extends OrderPlanScreeningFeedbackView {
  schema_version: "feedback-create-response.v1";
  producer: "human-review-api";
  consumer: "postgres-history";
}

export interface OrderPlanScreeningArtifactSummary {
  kind: OrderPlanScreeningArtifactKind;
  artifact_schema_version: string;
  artifact_producer: string;
  artifact_consumer: string;
  sha256: string;
  byte_count: number;
  object_version: string | null;
  validation_status: OrderPlanArtifactValidationStatus;
  created_at: string;
}

export interface OrderPlanScreeningExecutionCounts {
  candidate_count: number;
  completed_count: number;
  failure_count: number;
  stage1_selected_count: number;
  stage1_filtered_out_count: number;
  stage1_failed_count: number;
  stage2_relevant_count: number;
  stage2_not_relevant_count: number;
  stage2_uncertain_count: number;
  stage2_failed_count: number;
  stage2_rejected_count: number;
  human_review_count: number;
}

export interface OrderPlanScreeningExecutionSummary {
  execution_id: string;
  request_id: string;
  source_run_id: string;
  policy_version: string;
  status: OrderPlanScreeningStatus;
  requested_by: string;
  execution_allowed: boolean;
  population_count: number;
  population_sha256: string;
  policy_sha256: string;
  binding_sha256: string;
  stage1_binding_version: string;
  stage1_binding_sha256: string;
  stage2_binding_version: string;
  stage2_binding_sha256: string;
  counts: OrderPlanScreeningExecutionCounts;
  partial_artifact: boolean;
  error_code: string | null;
  queued_at: string;
  started_at: string | null;
  heartbeat_at: string | null;
  finished_at: string | null;
}

export interface OrderPlanScreeningExecutionListResponse {
  schema_version: "execution-list-response.v1";
  producer: "screening-api";
  consumer: "human-review-client";
  items: OrderPlanScreeningExecutionSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface OrderPlanScreeningAttemptSummary {
  attempt_id: string;
  batch_id: string;
  sequence: number;
  attempt_no: number;
  model_name: string;
  model_digest: string;
  prompt_version: string;
  prompt_sha256: string;
  company_profile_version: string;
  company_profile_sha256: string;
  generation_config_sha256: string;
  attempt_status: OrderPlanScreeningAttemptStatus;
  failure_type: OrderPlanScreeningFailureType | null;
  failure_code: string | null;
  input_tokens: number | null;
  cached_input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  duration_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface OrderPlanScreeningExecutionDetailResponse extends OrderPlanScreeningExecutionSummary {
  schema_version: "execution-detail-response.v1";
  producer: "screening-api";
  consumer: "human-review-client";
  artifacts: OrderPlanScreeningArtifactSummary[];
  attempts: OrderPlanScreeningAttemptSummary[];
}

export interface OrderPlanScreeningExecutionQuery {
  source_run_id?: string | null;
  status?: OrderPlanScreeningStatus | null;
  limit?: number | null;
  offset?: number | null;
}


export interface OpportunityTrackingDecisionItem {
  decided_at: string;
  tracking_status: string;
  previous_tracking_status: string | null;
  reason: string | null;
  claimed_name: string | null;
  audit_event_id: string;
  cleared_recheck_signal: boolean;
}

export interface OpportunityTrackingDecisionsResponse {
  opportunity_id: number;
  items: OpportunityTrackingDecisionItem[];
}

export interface OpportunityDeepReviewItem {
  deep_review_id: string;
  notice_id: number;
  notice_title: string | null;
  status: string;
  quality_status: string | null;
  created_at: string;
  current_attempt_status: string | null;
  latest_final_opinion: { value: string; decided_at: string } | null;
}

export interface OpportunityDeepReviewsResponse {
  opportunity_id: number;
  items: OpportunityDeepReviewItem[];
}

export type WorkloadKey = "order_plan_pending" | "pre_spec_deep_review_ready" | "tracking_action_required" | "bid_final_decision_pending";
export interface WorkloadItem {
  key: WorkloadKey;
  count: number | null;
  unavailable_reason: string | null;
}
export interface WorkloadResponse {
  generated_at: string;
  items: WorkloadItem[];
}

export interface BidDeltaDecisionQueueQuery {
  status?: "pending" | "all" | null;
  limit?: number | null;
  offset?: number | null;
}
export interface BidDeltaDecisionQueueItem {
  opportunity_id: number;
  title: string | null;
  agency: string | null;
  tracking_status: string;
  first_registered_stage: string;
  recheck_signal: boolean;
  bid_notice_external_id: string | null;
  comparison_count: number;
  latest_final_decision: { decision: "go" | "no_go"; decided_at: string; claimed_name: string } | null;
  decision_currentness: "current" | "stale" | "unknown";
}
export interface BidDeltaDecisionQueueResponse {
  items: BidDeltaDecisionQueueItem[];
  total: number;
  limit: number;
  offset: number;
}

// Exact server request/response contracts: screening/schemas/order_plans.py.
// Actor is a required API adapter argument, carried only in the audit header.
export interface OrderPlanScreeningExecutionCreateRequest {
  schema_version: "execution-create-request.v1";
  producer: "human-review-client";
  consumer: "screening-api";
  request_id: string;
  source_run_id: string;
  policy_version: string;
}
export interface OrderPlanScreeningExecutionCreateResponse {
  schema_version: "execution-create-response.v1";
  producer: "screening-api";
  consumer: "human-review-client";
  execution_id: string;
  request_id: string;
  source_run_id: string;
  policy_version: string;
  status: "대기";
  binding_sha256: string;
  stage1_binding_sha256: string;
  stage2_binding_sha256: string;
  execution_allowed: boolean;
}
export interface OrderPlanScreeningExecutionStopRequest {
  schema_version: "execution-stop-request.v1";
  producer: "human-review-client";
  consumer: "screening-api";
  request_id: string;
  reason: "user_requested";
}
export interface OrderPlanScreeningExecutionStopResponse {
  schema_version: "execution-stop-response.v1";
  producer: "screening-api";
  consumer: "human-review-client";
  execution_id: string;
  request_id: string;
  status: "중지 요청" | "중단됨";
}
export type OrderPlanScreeningErrorCode =
  | "actor_name_required" | "actor_name_invalid" | "invalid_request" | "not_found"
  | "source_run_incomplete" | "policy_not_active" | "binding_mismatch" | "service_unavailable"
  | "active_execution_exists" | "idempotency_conflict" | "immutable_conflict"
  | "execution_not_stoppable" | "artifact_kind_invalid" | "artifact_not_ready"
  | "feedback_conflict" | "processing_failed";
export interface OrderPlanScreeningErrorResponse {
  error: { code: OrderPlanScreeningErrorCode; message: string; details: null };
  request_id: string | null;
}
export interface OrderPlanScreeningError {
  status: number;
  code: OrderPlanScreeningErrorCode | null;
  request_id: string | null;
}

export interface CompanyFitResult {
  schema_version: "bidops.prespec-company-fit-result.v1";
  decision: "matched" | "mismatch" | "unknown";
  summary: string;
  reasons: { kind: "scope_match" | "scope_mismatch" | "information_gap"; explanation: string; notice_refs: string[]; company_refs: string[] }[];
  verification_items: string[];
}

export interface CompanyFitAttempt {
  id: string;
  notice_id: number;
  status: "queued" | "running" | "completed" | "failed" | "needs_human_review";
  result: CompanyFitResult | null;
  error_code: string | null;
  is_current: boolean;
  overview_kind: "page" | "extractive";
  overview_id: string;
  document_version_id: string;
  overview_sha256: string;
  profile_version_id: string;
  profile_sha256: string;
  policy_digest: string;
  model_name: string;
  model_revision: string;
  prompt_version: string;
  quality_status: "unmeasured_reference" | "mock_reference";
  notice_facts: { ref: string; text: string; pages: number[]; block_key: string | null }[];
  company_facts: { ref: string; fact_key: string; status: "confirmed" | "inferred" | "unknown"; value: unknown }[];
  created_at: string;
  completed_at: string | null;
  prompt_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
}

export interface CompanyFitResponse {
  schema_version: "bidops.prespec-company-fit.v1";
  notice_id: number;
  attempts: CompanyFitAttempt[];
  automation_enabled: boolean;
  auto_deep_review_reason: string | null;
  deep_review_id: string | null;
}
