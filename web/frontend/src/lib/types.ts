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
  count: number;
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
  collected_count: number;
  candidate_count: number;
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
