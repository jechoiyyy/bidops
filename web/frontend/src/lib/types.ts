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
export type PreSpecWorkspace = "actionable" | "recent" | "tracking" | "all";
export type PreSpecOverviewView =
  | "all"
  | "attention"
  | "pending"
  | "completed"
  | "failed"
  | "cancelled"
  | "not_started";
export type PreSpecDeadlineStatus = "open" | "passed" | "unknown";
/** 검토할 항목(actionable)의 기본 시야를 나누는 구간(ADR-0064). `current`는
 * `마감 전`과 `마감 미확인`(`deadline_at`이 null)을 함께 담는다 — 미확인을 마감
 * 경과로 접지 않는다. 기존 `deadline_status`와 달리 actionable 술어의 일부다. */
export type PreSpecDeadlineScope = "current" | "passed" | "all";
export type PreSpecNextAction = "confirm_overview" | "open_deep_review" | "decide_tracking";
export type PreSpecSort = "published" | "deadline" | "observed";

/** 사전규격 응답의 `grade`가 어디서 왔는가. 사람 정정이 있으면 `human_review`,
 * 판정만 있으면 `screening_judgment`, 둘 다 없으면 `null`(등급도 `null`)이다. */
export type PreSpecGradeSource = "screening_judgment" | "human_review";
export type PreSpecDisplayAssessmentStatus = "graded" | "held" | "none";
export type PreSpecDisplayAssessmentSource =
  | "human_review"
  | "preliminary_assessment"
  | "screening_judgment"
  | "none";
export interface PreSpecDisplayAssessmentAxis {
  axis: "ai_data" | "blockchain_did" | "public_si_integration";
  relation: "direct" | "partial" | "indirect" | "unrelated" | "unknown";
  reason: string;
  claim_refs: string[];
  company_refs: string[];
}
export interface PreSpecDisplayAssessment {
  grade: "우선 검토" | "검토 권장" | "관찰 대상" | "제외" | null;
  status: PreSpecDisplayAssessmentStatus;
  source: PreSpecDisplayAssessmentSource;
  basis_run_id: string | null;
  assessed_at: string | null;
  quality_status: "unmeasured_reference" | "mock_reference" | null;
  reason_codes: string[];
  axes: PreSpecDisplayAssessmentAxis[];
  verification_items: string[];
  semantic_status: "not_run" | "passed" | "failed" | null;
  semantic_scope: string[];
  latest_run_status: PreSpecOverviewReviewStatus | null;
}

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

export type PreSpecReviewExclusionStatus = "included" | "excluded";
export interface PreSpecReviewExclusionRequest {
  notice_ids: number[];
  status: PreSpecReviewExclusionStatus;
  actor_name: string;
  reason: string;
}
export interface PreSpecReviewExclusionResponse {
  items: { notice_id: number; status: PreSpecReviewExclusionStatus; outcome: "changed" | "unchanged" }[];
}

export interface PreSpecListItem {
  review_exclusion_status: PreSpecReviewExclusionStatus;
  review_exclusion_actor_name: string | null;
  review_exclusion_reason: string | null;
  review_exclusion_changed_at: string | null;
  notice_pk: number;
  pre_spec_no: string | null;
  title: string | null;
  agency: string | null;
  /** 사전규격 원문 `rlDminsttNm`(수요기관). 발주기관 `agency`와 다를 수 있고
   * 값이 없으면 `null`이다. 입찰공고는 `agency`가 이미 수요기관 우선값이라
   * 투영하지 않는다(spec §5). */
  demand_agency: string | null;
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
  /** 목록·상세·필터가 함께 쓰는 화면 대표 판정. 자동 준비용 grade와 분리한다. */
  display_assessment: PreSpecDisplayAssessment;
  /** 서버가 정한 자동 준비 단계. 응답에서 `null`이 되지 않는다. */
  auto_preparation_status: PreSpecAutoPreparationStatus;
  /** 왜 다음 단계로 가지 않는가. 안전한 코드이며 없으면 `null`이다.
   * `null`은 정상이므로 자리표시 문구로 바꾸지 않는다. */
  auto_preparation_reason: string | null;
  /** 자동으로 시작된(또는 마지막) 심층 검토 식별자. 없으면 `null`이다. */
  latest_deep_review_id: string | null;
  latest_deep_review_status?: "queued" | "running" | "completed" | "failed" | null;
  /** 현재 projection에 포함된 관측 중 가장 이른 시각. 없으면 `null`이다. */
  first_observed_at: string | null;
  /** 현재 projection에 포함된 관측 중 가장 늦은 시각. 없으면 `null`이다. */
  last_observed_at: string | null;
  /** 서버가 정한 탐색용 다음 행동. 새 업무 상태가 아니다. */
  next_action: PreSpecNextAction | null;
}

/** 개요 검토 상태 그룹 하나의 전체 건수. `limit`/`offset`과 무관하게 현재
 * 필터에 일치하는 전체 집합을 센다 — 반환된 페이지(`items`)만 세지 않는다. */
export interface PreSpecOverviewStatusCount {
  status: PreSpecOverviewReviewStatus | null;
  count: number;
}

/** 구간을 적용하기 **전** actionable 집합을 두 구간으로 나눈 건수(ADR-0064 결정 5).
 * 활성 workspace·활성 `deadline_scope`와 무관하게 언제나 같은 값이고 언제나 있다. */
export interface PreSpecDeadlineScopeCounts {
  current: number;
  passed: number;
}

export interface PreSpecListResponse {
  items: PreSpecListItem[];
  total: number;
  limit: number;
  offset: number;
  overview_status_counts: PreSpecOverviewStatusCount[];
  /** 활성 workspace를 제외한 나머지 필터 기준의 누적 건수. */
  workspace_counts: Record<PreSpecWorkspace, number>;
  deadline_scope_counts: PreSpecDeadlineScopeCounts;
}

export interface PreSpecListQuery {
  review_exclusion?: "all" | PreSpecReviewExclusionStatus;
  deadline_scope?: PreSpecDeadlineScope;
  notice_pk?: number | null;
  sw_only?: boolean | null;
  auto_preparation_status?: PreSpecAutoPreparationStatus | null;
  business_division?: string | null;
  origin?: PreSpecOrigin | null;
  workspace?: PreSpecWorkspace | null;
  overview_view?: PreSpecOverviewView | null;
  grade?: string | null;
  display_grade?: string | null;
  tracking_decision?: "pending" | null;
  tracking_status?: OpportunityTrackingStatus | null;
  source_run_id?: string | null;
  observed_from?: string | null;
  observed_to?: string | null;
  deadline_status?: PreSpecDeadlineStatus | null;
  q?: string | null;
  sort?: PreSpecSort | null;
  limit?: number | null;
  offset?: number | null;
}

/** 후보가 제시하는 소유 발주계획 요약(spec §4.4). */
export interface PreSpecCandidateOrderPlan {
  order_plan_id: number;
  order_plan_unty_no: string;
  title: string | null;
  agency_name: string | null;
  planned_order_year: string | null;
  planned_order_month: string | null;
  budget_amount: number | null;
}

/**
 * 이 사전규격을 target으로 하는 `후보 확인 대기` 연결 하나(spec §4.4).
 * `order_plans`는 owner 사업기회가 가진 모든 발주계획이며, owner가(병합 확인
 * owner처럼) 발주계획을 하나도 갖지 않으면 빈 배열이다.
 */
export interface PreSpecOrderPlanCandidate {
  link: OpportunityLinkView;
  opportunity_id: number;
  tracking_status: OpportunityTrackingStatus;
  order_plans: PreSpecCandidateOrderPlan[];
}

export interface PreSpecOrderPlanCandidatesResponse {
  notice_pk: number;
  items: PreSpecOrderPlanCandidate[];
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

/** 결정적 검증 상태 셋. `pending`은 검증된 결과가 아직 없다는 뜻이며 실패가
 * 아니다. */
export type PreSpecOverviewValidationStatus = "passed" | "failed" | "pending";

/** 개요 run 하나의 실행 상태. 목록 projection의 `overview_review_status`는 가장
 * 최근 run의 status를 그대로 쓰므로 이 여섯 값은 위 10값의 부분집합이다
 * (docs/contracts.md "사전규격 개요 검토 (MVP, 2026-09-11)"). */
export type OverviewRunStatus = Extract<
  PreSpecOverviewReviewStatus,
  "queued" | "running" | "completed" | "needs_human_review" | "failed" | "cancelled"
>;

/** 읽은 쪽 범위를 누가 정했는가. `auto`는 문서 제목 구조에서 고른 것,
 * `fallback`은 자동 선택이 실패해 앞부분을 읽은 것, `human`은 담당자가 지정한
 * 것이다. 셋을 서로 대신하지 않는다. */
export type OverviewRangeSource = "auto" | "fallback" | "human";

/** 주장 하나가 가리키는 원문 위치. `page`는 표지를 포함해 세는 물리 PDF 쪽이다. */
export interface OverviewEvidence {
  page: number;
  quote: string;
}

export interface OverviewClaim {
  claim_id: string;
  text: string;
  evidence: OverviewEvidence[];
}

/** 검토자 분석은 **의견**이며 사실 주장이 아니다. `supporting_claim_ids`는 그
 * 의견이 딛고 선 주장 id다. */
export interface OverviewReviewerAnalysis {
  id: string;
  text: string;
  supporting_claim_ids: string[];
}

export interface OverviewRunResult {
  business_overview: OverviewClaim[];
  main_tasks: OverviewClaim[];
  budget_and_period: OverviewClaim[];
  /** v7 이후 응답에 없음(심층 검토 몫). */
  important_conditions?: OverviewClaim[];
  /** v7 이후 응답에 없음(심층 검토 몫). */
  reviewer_analysis?: OverviewReviewerAnalysis[];
  /** v7 이후 응답에 없음(심층 검토 몫). */
  unknowns?: string[];
  input_limitations: string[];
}

/** `needs_human_review`에서 사람이 확인해야 하는 주장 하나. `evidence`는 검증을
 * 통과한 인용만 담고, 통과하지 못한 인용은 여기 오지 않는다. */
export interface OverviewFailedClaim {
  claim_id: string;
  section: string;
  text: string;
  reason_codes: string[];
  evidence: OverviewEvidence[];
}

/** `bidops.prespec-overview.v1`의 run 하나. 모델 원문·raw_response_refs·내부
 * 경로는 응답에 없다. */
export interface OverviewRun {
  id: string;
  status: OverviewRunStatus;
  range_source: OverviewRangeSource;
  /** 준비 전이면 `null`이다. 1쪽으로 접지 않는다. */
  page_start: number | null;
  page_end: number | null;
  range_reason_codes: string[];
  reason_codes: string[];
  /** 비차단 경고(수치·역할·날짜 대조 등)의 안전한 코드다. */
  warnings: string[];
  /** `completed`가 아니면 `null`이다. */
  result: OverviewRunResult | null;
  failed_claims: OverviewFailedClaim[];
  model_name: string;
  model_revision: string | null;
  call_count: number;
  actor_name: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  /** `completed`면 run id, 아니면 `null`. */
  result_id: string | null;
  prompt_version: string;
  /** 검증 기록이 없으면 `null`이다. 없음을 통과로 바꾸지 않는다. */
  verification_status: "passed" | "needs_human_review" | null;
  /** 입력 스냅샷의 식별값. 준비 전이면 `null`이다. */
  document_version_id: string | null;
  source_sha256: string | null;
  pdf_sha256: string | null;
  pdf_page_count: number | null;
  /** 읽은 쪽 목록(`page_start`~`page_end`). 준비 전이면 빈 배열이다. */
  reviewed_pages: number[];
  payload_sha256: string | null;
  /** 참조 실행 표식. 운영 완료 근거가 아니다. */
  quality_status: "unmeasured_reference" | "mock_reference";
  validation_status: "passed" | "failed";
  validation_errors: string[];
  evidence_check_status: "passed" | "failed";
  evidence_check_errors: string[];
  contract_version?: "overview-v1" | "overview-assessment-v1";
  assessment?: {
    result: {
      primary_task_claim_ids: string[];
      delivery_role: string;
      axes: PreSpecDisplayAssessmentAxis[];
      verification_items: string[];
      uncertainty_codes: string[];
    } | null;
    checks: Record<string, unknown> | null;
    grade: "우선 검토" | "검토 권장" | "관찰 대상" | "제외" | null;
    status: PreSpecDisplayAssessmentStatus;
    semantic_status: "not_run" | "passed" | "failed";
    semantic_scope: string[];
  } | null;
  input_binding?: {
    policy_digest: string;
    prompt_version: string | null;
    validator_version: string | null;
    profile_version_id: string | null;
    profile_digest: string | null;
    profile_status: "not_configured" | "ready" | "invalid";
    generation_config_digest: string | null;
    input_binding_sha256: string | null;
    reused_from_run_id: string | null;
  };
}

/** 공고 하나의 개요 검토 전체. `current`는 `created_at` 최신 run이고 run이 없으면
 * `null`이다. `history`는 그 공고의 모든 run이다. */
export interface OverviewEnvelope {
  schema: "bidops.prespec-overview.v1" | "bidops.prespec-overview.v2";
  notice_id: number;
  current: OverviewRun | null;
  history: OverviewRun[];
  /** RFP 문서의 최신 안전 snapshot이 없으면 `null`이다. */
  range_review: OverviewRangeReview | null;
  /** 현재 run에 공개 가능한 검증 기록이 없으면 `null`이다. */
  verification: OverviewVerification | null;
}

export interface OverviewRangeConfirmationRequest {
  page_start: number;
  page_end: number;
  note?: string;
}

export interface OverviewRangeConfirmationResponse {
  run_id: string;
  attempt_enqueued: boolean;
  page_start: number;
  page_end: number;
}

/** 절 후보 하나. 사람이 읽을 범위를 고르는 표의 한 행이다. */
export interface OverviewRangeCandidate {
  index: number;
  title: string;
  page: number;
  char_count: number;
}

/** 담당자가 확정한 범위 기록. 감사 표식이며 인증이 아니다. */
export interface OverviewRangeConfirmation {
  page_start: number;
  page_end: number;
  actor_name: string;
  note: string | null;
  created_at: string;
}

/**
 * 개요 입력 범위의 사람 확인 자리. RFP 문서의 최신 안전 snapshot이 없으면
 * envelope에서 `null`이다.
 *
 * `status`는 최신 run이 정한다 — `human_confirmed`(담당자 확정), `pending`(자동
 * 선택 실패·사람 검토 필요·실행 없음), `ready`(자동 선택 결과가 있음). 셋은 서로
 * 대신하지 않는다.
 */
export interface OverviewRangeReview {
  target_id: string | null;
  status: "pending" | "ready" | "human_confirmed";
  document_version_id: string;
  pdf_page_count: number;
  mode: "outline" | "clause" | "page" | null;
  candidate_status: "complete" | "partial" | "unavailable";
  candidate_count_total: number | null;
  candidate_count_returned: number;
  candidates: OverviewRangeCandidate[];
  /** `[시작 쪽, 끝 쪽]`이며 확정 전이면 `null`이다. */
  selected_pages: [number, number] | number[] | null;
  warning_codes: string[];
  reason_code: string | null;
  can_confirm: boolean;
  /** 모델 보조 제안은 계약에 없다. 서버는 항상 `null`을 보낸다. */
  assisted: null;
  confirmation: OverviewRangeConfirmation | null;
}

export interface OverviewVerificationClaim {
  claim_id: string;
  section: string;
  text: string;
  deterministic: { status: "passed" | "failed"; reason_codes: string[] };
  semantic: { status: "supported" | "contradicted" | "insufficient" | "not_run"; reason_codes: string[] };
  verified_evidence: Array<{ page: number; quote: string; start_char: number; end_char: number }>;
}

/** 현재 run의 주장 검증 기록. 검증 기록이 없으면 envelope에서 `null`이다. */
export interface OverviewVerification {
  verification_id: string;
  status: "passed" | "needs_human_review";
  reason_codes: string[];
  claims: OverviewVerificationClaim[];
}

/* ── 개요 검토 화면이 읽는 view 타입군 ─────────────────────────────────────
 *
 * 화면은 새 envelope(`bidops.prespec-overview.v1`)를 `lib/api.ts`의 어댑터로
 * 아래 모양으로 옮겨 읽는다. 서버가 주지 않는 값은 자리만 있고 채워지지 않으며
 * (`?`), 화면은 없는 값을 지어내지 않는다. */

export interface PageOverviewFactV3 { text: string; evidence_pages: number[] }
export interface PageOverviewVerifiedEvidence {
  page: number;
  quote: string;
  /** 주장 검증 기록에만 있다. 완료된 개요 결과의 인용에는 없다. */
  start_char?: number;
  end_char?: number;
  /** 새 계약은 페이지 해시를 응답에 싣지 않는다. 없으면 표시하지 않는다. */
  page_text_sha256?: string;
}
export interface PageOverviewFactV4 {
  claim_id: string;
  text: string;
  evidence: PageOverviewVerifiedEvidence[];
}
export type PageOverviewFact = PageOverviewFactV3 | PageOverviewFactV4;
export interface PageOverviewPayloadV3 {
  schema_version: "bidops.prespec-overview-page-review.v3";
  business_overview: PageOverviewFactV3[];
  main_tasks: PageOverviewFactV3[];
  budget_and_period: PageOverviewFactV3[];
  important_conditions: PageOverviewFactV3[];
  reviewer_analysis: string[];
  unknowns: string[];
  input_limitations: string[];
}
export interface PageOverviewAnalysisV4 {
  id: string;
  text: string;
  supporting_claim_ids: string[];
}
export interface PageOverviewPayloadV4 {
  schema_version: "bidops.prespec-overview-page-review.v4";
  business_overview: PageOverviewFactV4[];
  main_tasks: PageOverviewFactV4[];
  budget_and_period: PageOverviewFactV4[];
  /** v7 이후 응답에 없음(심층 검토 몫). */
  important_conditions?: PageOverviewFactV4[];
  /** v7 이후 응답에 없음(심층 검토 몫). */
  reviewer_analysis?: PageOverviewAnalysisV4[];
  /** v7 이후 응답에 없음(심층 검토 몫). */
  unknowns?: string[];
  input_limitations: string[];
  verification_id?: string;
  verification_sha256?: string;
}
export type PageOverviewPayload = PageOverviewPayloadV3 | PageOverviewPayloadV4;
export interface PageOverviewView {
  id: string;
  notice_id: number;
  document_version_id: string;
  source_sha256: string;
  pdf_sha256: string;
  pdf_page_count: number;
  reviewed_pages: number[];
  payload: PageOverviewPayload;
  payload_sha256: string;
  validation_status: "passed" | "failed";
  validation_errors: string[];
  evidence_check_status: "passed" | "failed";
  evidence_check_errors: string[];
  quality_status: "unmeasured_reference" | "mock_reference";
  model_name: string;
  model_revision: string | null;
  prompt_version: string;
  created_at: string;
}
/** `stale`은 새 계약에 없다. 서버는 보내지 않으며 화면이 만들지도 않는다. */
export type PageOverviewCurrentStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "needs_human_review"
  | "stale"
  | "cancelled";
export interface PageOverviewCurrent {
  attempt_id: string | null;
  status: PageOverviewCurrentStatus;
  result_id: string | null;
  reason_code: string | null;
  prompt_version: string | null;
  created_at: string;
  verification_status: "passed" | "needs_human_review" | null;
}
export interface PageOverviewRangeCandidate {
  index: number;
  title: string;
  page: number;
  char_count: number;
}
export interface PageOverviewRangeAssist {
  start_index: number;
  end_index: number;
  model_name: string;
  quality_status: "unmeasured_reference" | "mock_reference";
  created_at: string;
}
export interface PageOverviewRangeConfirmation {
  target_id: string;
  confirmed_from_target_id: string;
  /** 새 계약의 확정 기록은 쪽만 남긴다. 절 번호는 `null`이며 지어내지 않는다. */
  start_index: number | null;
  end_index: number | null;
  first_page: number;
  last_page: number;
  page_numbers: number[];
  actor: string;
  note: string | null;
  created_at: string;
}
export interface PageOverviewRangeReview {
  schema_version: "bidops.prespec-overview-range-view.v2";
  target_id: string;
  snapshot_id: string;
  selection_status: "needs_human_review" | "ready";
  reason_code: string | null;
  pdf_page_count: number;
  created_at: string;
  candidates_mode: "outline" | "clause" | "page" | null;
  candidate_status: "complete" | "partial" | "unavailable";
  candidate_count_total: number | null;
  candidate_count_returned: number;
  warning_codes: string[];
  selected_pages: number[];
  can_confirm: boolean;
  candidates: PageOverviewRangeCandidate[];
  assisted: PageOverviewRangeAssist | null;
  confirmation: PageOverviewRangeConfirmation | null;
}
export interface PageOverviewRangeConfirmationRequest {
  target_id: string;
  start_index: number | null;
  end_index: number | null;
  first_page: number | null;
  last_page: number | null;
  note: string | null;
}
export interface PageOverviewRangeConfirmationResponse {
  target_id: string;
  selection_status: "ready";
  first_page: number;
  last_page: number;
  page_numbers: number[];
  /** 새 계약의 범위 확정은 그 범위로 개요 검토 run 하나를 예약한다. */
  attempt_enqueued: boolean;
}
export interface PageOverviewVerificationClaim {
  claim_id: string;
  text: string;
  deterministic_status: "passed" | "failed";
  semantic_status: "supported" | "contradicted" | "insufficient" | "not_run";
  reason_codes: string[];
  verified_evidence: PageOverviewVerifiedEvidence[];
}
export interface PageOverviewVerification {
  verification_id: string;
  status: "passed" | "needs_human_review";
  reason_codes: string[];
  claims: PageOverviewVerificationClaim[];
}
export interface PageOverviewResponse {
  schema_version: "bidops.prespec-overview-pages.v2";
  notice_id: number;
  reviews: PageOverviewView[];
  /** 적용 기록 없음은 null이다. 실패/중단일 때 과거 성공을 현재로 대체하지 않는다. */
  current: PageOverviewCurrent | null;
  /** 범위 사람 확인 대상이 없으면 null이다. */
  range_review: PageOverviewRangeReview | null;
  /** 현재 attempt에 공개 가능한 검증 기록이 없으면 null이다. */
  verification: PageOverviewVerification | null;
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
// "사람 확인 병합"은 병합으로 끝난 후보 수락(비소유 행)의 상태다(spec §3, §10).
export type OpportunityLinkStatus = "확정" | "후보 확인 대기" | "사람 확인 완료" | "검색 미확인" | "사람 확인 병합";
// "merge_confirmation"은 사람 상태가 있는 사업기회끼리 자동 병합을 거부했을 때
// 만든 병합 확인 후보의 전략이다(spec §3, §7.1 action reason과 다른 축).
export type OpportunitySearchStrategy =
  | "full"
  | "breaking_split"
  | "normalized"
  | "longest_fragment"
  | "prefix12"
  | "merge_confirmation";

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
  // `검색 미확인` 행이 어느 찾아보기 대상의 기록인지(spec §3.3). 다른 행은 null이다.
  // 이 필드를 싣기 전의 응답·고정 입력에는 없을 수 있어 선택 필드로 둔다.
  search_target_kind?: OpportunitySearchTarget | null;
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
  /** 추가형 투영(spec §5). link 단위 값 — `notice`를 가리키면 `budget`·
   * `deadline_at`을, `order_plan`을 가리키면 `budget`(=`budget_amount`)·
   * `planned_order_year`·`planned_order_month`를 싣는다. 대상이 없거나
   * 해당하지 않으면 `null`이다. 서버는 사업기회 단위의 "대표 마감"을 고르지
   * 않는다. */
  budget: number | null;
  deadline_at: string | null;
  planned_order_year: string | null;
  planned_order_month: string | null;
  record_external_id: string | null;
}

// "신규 입찰공고"는 입찰공고로 처음 등록된 미선택 사업이다. "미결정"은 그 밖의
// 미선택 사업이며 집계 전용이라 목록 필터로는 받지 않는다(spec §7.2).
export type OpportunitySection = "조치 필요" | "추적 중" | "보류" | "추적 종료" | "신규 입찰공고";
export type OpportunitySectionCounts = Record<OpportunitySection | "미결정", number>;

// 조치 필요 사유(spec §7.1). 모든 행에 계산하며 구역과 별개의 축이다.
export type OpportunityActionReason =
  | "new_link"
  | "candidate_pending"
  | "merge_confirmation"
  | "blocking_item"
  | "hold_overdue";

// 보류 재검토 기한 필터(spec §7.3). "attention"은 "overdue"와 "due_soon"의 합집합이다.
export type OpportunityHoldReview = "overdue" | "due_soon" | "attention";

// 찾아보기 대상(spec §4.3).
export type OpportunitySearchTarget = "pre_spec" | "bid_notice";

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
  action_reasons: OpportunityActionReason[];
  /** "보류"일 때만 `tracking_selected_at + 14일`이다. 저장하지 않는 파생값이다. */
  hold_review_due_at: string | null;
}

export interface OpportunityListItem extends OpportunityStateView {
  links: OpportunityLinkView[];
}

export interface OpportunityDetailResponse extends OpportunityStateView {
  links: OpportunityLinkView[];
}

export interface OpportunityListResponse {
  section_counts: OpportunitySectionCounts;
  // 활성 `reason` 필터만 뺀 조건으로 센 사유별 건수. 한 행은 여러 사유에 들어간다.
  action_reason_counts: Record<OpportunityActionReason, number>;
  items: OpportunityListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface OpportunityListQuery {
  section?: OpportunitySection | null;
  tracking_status?: OpportunityTrackingStatus | null;
  first_registered_stage?: OpportunityFirstRegisteredStage | null;
  reason?: OpportunityActionReason | null;
  hold_review?: OpportunityHoldReview | null;
  /** 마감 임박 창(일, 1~365). `hold_review`처럼 추적 대상(`계속 추적`·`보류`)을 함께
   *  좁힌다(ADR-0067 결정 3). 상한은 요청 시각 KST 일자 + N일의 끝이다. */
  deadline_within_days?: number | null;
  /** 서버 검색(공백 정규화·소문자 부분일치), 2~100자(spec §7.5). */
  q?: string | null;
  /** `deadline`은 아직 남은 권위 연결 마감 중 가장 이른 것 오름차순이고, 그런 마감이
   *  없는 사업은 맨 뒤다. 정렬 키일 뿐 응답에 대표 마감 필드는 없다(ADR-0067 결정 4). */
  sort?: "created_at" | "tracking_status" | "first_registered_stage" | "hold_review_due_at" | "deadline" | null;
  limit?: number | null;
  offset?: number | null;
}

export interface TrackingStatusUpdateRequest {
  tracking_status: OpportunityTrackingStatus;
  reason: string;
}

/**
 * 현재 재검토 신호를 확인 처리한다(`POST /opportunities/{id}/recheck-acknowledgements`,
 * spec §6.2). `expected_link_id`는 사람이 실제로 본 근거 연결이며, 신호가 이미 다른
 * 연결로 바뀌었으면 서버가 409 `recheck_signal_changed`로 거절한다. 추적 상태는
 * 바꾸지 않는다.
 */
export interface RecheckAcknowledgementRequest {
  expected_link_id: number;
  note?: string | null;
}

/** `recheck_signal_changed` 409의 `details` (spec §6.2). */
export interface RecheckSignalChangedDetails {
  current_link_id: number;
}

/** `candidate_merge_state_conflict` 409의 `details.opportunities[]` 원소 (spec §11.1). */
export interface OpportunityMergeConflictState {
  id: number;
  tracking_status: OpportunityTrackingStatus;
  tracking_selected_by: string | null;
  tracking_selected_at: string | null;
  recheck_signal: boolean;
  // 신호 시각(2026-09-22 추가, ADR-0068). 상태가 같아도 신호가 있으면 병합이
  // 막히므로 화면이 "언제 온 신호 때문인지"를 말할 수 있어야 한다. 옛 응답에는
  // 없을 수 있으므로 없으면 `null`로 둔다.
  recheck_signal_at: string | null;
}

export interface CandidateMergeStateConflictDetails {
  opportunities: OpportunityMergeConflictState[];
}

/** 서버 측 이름 사다리 찾아보기 요청(`POST /opportunities/{id}/searches`, spec §4.3). */
export interface OpportunitySearchRequest {
  target: OpportunitySearchTarget;
}

/**
 * 찾아보기 응답. `search_unconfirmed`는 검색이 레코드를 확인하지 못했다는
 * 뜻이며 "레코드가 없다"는 주장이 아니다(ADR-0025).
 */
export interface OpportunitySearchResponse {
  searched_at: string;
  target: OpportunitySearchTarget;
  attempted_strategies: OpportunitySearchStrategy[];
  candidates: OpportunityLinkView[];
  search_unconfirmed: boolean;
}

/** v1 contracts for read-only bulk tracking preview and its final receipt. */
export type OrderPlanBulkExcludedStatus = "계속 추적" | "보류" | "종료";
export type OrderPlanBulkEligibility = "eligible" | "excluded" | "failed";
export type OrderPlanBulkOutcome = "succeeded" | "excluded" | "failed";
export type OrderPlanBulkFailureCode =
  | "order_plan_not_found"
  | "owning_opportunity_missing"
  | "owner_changed"
  | "ownership_conflict"
  | "processing_failed"
  | "temporarily_unavailable";

export interface OrderPlanBulkPreviewRequest {
  schema_version: "order-plan-bulk-preview-request.v1";
  order_plan_ids: number[];
}

export interface OrderPlanBulkStartRequest {
  schema_version: "order-plan-bulk-start-request.v1";
  request_id: string;
  order_plan_ids: number[];
  reason: string;
}

export interface OrderPlanBulkStatusCount {
  plan_count: number;
  owner_count: number;
}

export interface OrderPlanBulkPreviewItem {
  order_plan_id: number;
  opportunity_id: number | null;
  tracking_status: OpportunityTrackingStatus | null;
  eligibility: OrderPlanBulkEligibility;
  code: OrderPlanBulkFailureCode | null;
}

export interface OrderPlanBulkPreviewResponse {
  schema_version: "order-plan-bulk-preview-response.v1";
  selected_plan_count: number;
  unique_owner_count: number;
  eligible_plan_count: number;
  eligible_owner_count: number;
  excluded_by_status: Record<OrderPlanBulkExcludedStatus, OrderPlanBulkStatusCount>;
  failure_plan_count: number;
  items: OrderPlanBulkPreviewItem[];
}

export interface OrderPlanBulkStartItem {
  order_plan_id: number;
  opportunity_id: number | null;
  outcome: OrderPlanBulkOutcome;
  status_at_decision: OpportunityTrackingStatus | null;
  code: OrderPlanBulkFailureCode | null;
  audit_event_id: string | null;
}

export interface OrderPlanBulkSummary {
  selected_plan_count: number;
  unique_owner_count: number;
  succeeded_plan_count: number;
  succeeded_owner_count: number;
  excluded_plan_count: number;
  excluded_by_status: Record<OrderPlanBulkExcludedStatus, OrderPlanBulkStatusCount>;
  failed_plan_count: number;
}

export interface OrderPlanBulkStartResponse {
  schema_version: "order-plan-bulk-start-response.v1";
  request_id: string;
  completed_at: string;
  items: OrderPlanBulkStartItem[];
  summary: OrderPlanBulkSummary;
}

/**
 * 발주계획 일괄 추적 종료 v1 (ADR-0063). 목표 상태가 `종료`로 고정된다는 점만
 * bulk-start와 다르고 나머지 wire 모양은 같다.
 */
export interface OrderPlanBulkEndRequest {
  schema_version: "order-plan-bulk-end-request.v1";
  request_id: string;
  order_plan_ids: number[];
  reason: string;
}

export interface OrderPlanBulkEndResponse {
  schema_version: "order-plan-bulk-end-response.v1";
  request_id: string;
  completed_at: string;
  items: OrderPlanBulkStartItem[];
  summary: OrderPlanBulkSummary;
}

/** 화면이 두 작업의 최종 receipt를 같은 모양으로 다루는 자리에 쓰는 union. */
export type OrderPlanBulkReceipt = OrderPlanBulkStartResponse | OrderPlanBulkEndResponse;

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
export type OrderPlanScreeningExecutionPurpose = "operational" | "gate_measurement";
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
  /** 계약방법(`cntrctMthdNm`) 원문. 값이 없으면 `null`이다. */
  contract_method: string | null;
  /** 공고 게시 여부(`ntceNticeYn`) 원문 `Y`/`N`. bool이 아니며 `null`은 `N`이 아니라 미제공이다. */
  notice_posted: string | null;
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
  execution_id: string | null;
  policy_version: string | null;
  first_observed_at: string | null;
}

export interface OrderPlanListResponse {
  schema_version: "order-plan-list-response.v5";
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

/**
 * 누적 모드의 두 목록. 둘 다 policy `activated_at` 오름차순(동률은 버전 오름차순)이다.
 * - `policy_versions`: 범위에 완료 실행이 실제로 있는 버전 — 판정 유무. 범위가 비면 빈 목록이다.
 * - `activated_policy_versions`: 활성화된 적 있는 버전 전부 — 실행 상태를 보일 범위이므로 결과가
 *   아직 없는 대기·실행 중·실패도 포함한다. `policy_versions`는 이것의 부분집합이다.
 */
export interface OrderPlanCumulativeScope {
  mode: "cumulative";
  policy_versions: string[];
  activated_policy_versions: string[];
}

/** 회차 모드: 그 회차의 최신 완료 실행 하나. policy·purpose를 묻지 않는다. */
export interface OrderPlanRunScope {
  mode: "run";
  execution_id: string;
  source_run_id: string;
  status: "성공" | "부분 성공";
  finished_at: string | null;
  policy_version: string;
  purpose: OrderPlanScreeningExecutionPurpose;
}

export type OrderPlanListScope = OrderPlanCumulativeScope | OrderPlanRunScope;

export interface OrderPlanListQuery {
  source_run_id?: string | null;
  stage1_status?: MultiValueFilter<OrderPlanStage1Filter> | null;
  stage2_status?: MultiValueFilter<OrderPlanStage2Filter> | null;
  qwen_relevance?: MultiValueFilter<OrderPlanRelevanceFilter> | null;
  human_relevance?: MultiValueFilter<OrderPlanRelevanceFilter> | null;
  tracking_status?: MultiValueFilter<OpportunityTrackingStatus> | null;
  issue?: boolean | null;
  /** `YYYY-MM-DD`(KST 일자). 그 일자 00:00 KST 이후에 **처음 관측된** 발주계획만
   *  남긴다. 상한은 없다(ADR-0067 결정 6, spec §7.3). */
  first_observed_from?: string | null;
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
  /**
   * 그 실행 행의 목적. `gate_measurement`는 품질 게이트 측정 전용이라 운영 판정이 아니다.
   * 참조 실행은 여기서 `operational`로 보인다 — 목적으로 가리지 말고 `policy_version`이
   * 누적 scope의 `activated_policy_versions`에 있는지로 가린다(기존 계약).
   */
  execution_purpose: OrderPlanScreeningExecutionPurpose;
  /** 실행 행의 두 시각 그대로. 서버가 대표 시각을 고르지 않으므로 둘 다 `null`일 수 있다. */
  execution_started_at: string | null;
  execution_finished_at: string | null;
}

export interface OrderPlanDetailResponse {
  schema_version: "order-plan-detail-response.v4";
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
  supervising_agency_name: string | null;
  /** 조달방법(`prcrmntMethd`) 원문. */
  procurement_method: string | null;
  contract_method: string | null;
  notice_posted: string | null;
  /** 수집 원문 문자열 그대로. 공고번호가 여럿이면 한 문자열에 이어져 있고 서버가 쪼개지 않는다. */
  bid_ntice_no_list: string | null;
  published_at: string | null;
  observations: OrderPlanObservationView[];
  screening_history: OrderPlanScreeningHistoryItem[];
  latest_human_feedback: OrderPlanHumanFeedbackSummary | null;
  tracking: OrderPlanTracking | null;
}

/**
 * `screening-history`는 상세와 같은 `order-plan-detail-response` family 이름을 쓰면서 번호만
 * 따로 올려 왔다(v1). 번호는 family 안에서 한 번만 쓰므로(v2·v3은 옛 상세, v4는 지금 상세)
 * 항목 모델이 바뀐 이번 회차에 v5로 간다.
 */
export interface OrderPlanScreeningHistoryResponse {
  schema_version: "order-plan-detail-response.v5";
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
  purpose: OrderPlanScreeningExecutionPurpose;
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
  schema_version: "execution-list-response.v2";
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
  schema_version: "execution-detail-response.v2";
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

export type OpportunityRecheckEventKind = "created" | "acknowledged" | "cleared_by_decision";

/**
 * 재검토 신호 이벤트 하나(감사 로그 투영, spec §6.3). `note_present`는 확인이
 * 메모를 가졌는지만 말하며 메모 원문은 저장·노출하지 않는다.
 */
export interface OpportunityRecheckEventView {
  kind: OpportunityRecheckEventKind;
  link_id: number | null;
  actor_kind: "human" | "system";
  claimed_name: string | null;
  created_at: string;
  note_present: boolean;
}

export interface OpportunityTrackingDecisionsResponse {
  opportunity_id: number;
  items: OpportunityTrackingDecisionItem[];
  recheck_events: OpportunityRecheckEventView[];
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

// 키 순서 고정(ADR-0053 §1·§4): order_plan_pending, pre_spec_deep_review_ready,
// tracking_action_required, tracking_hold_review_due, bid_final_decision_pending.
/**
 * `GET /api/workload` 항목의 고정 순서이자 전체 어휘
 * (`app/lifecycle/schemas/workload.py`의 `WorkloadKey`와 같은 순서).
 *
 * 앞 다섯은 ADR-0053, 뒤 다섯은 실무자 대시보드 패널 계약(ADR-0067)이 더했다 —
 * 세는 키 넷과 그중 둘의 합계 하나다. `human_check_required`가 그 합계이며
 * `overview_human_review` + `blocking_items_open`이고, 하나라도 `null`이면 합계도
 * `null`(`unavailable_reason="sub_count_unavailable"`)이다. **화면은 합계를 직접
 * 더하지 않는다.**
 */
export type WorkloadKey =
  | "order_plan_pending"
  | "pre_spec_deep_review_ready"
  | "tracking_action_required"
  | "tracking_hold_review_due"
  | "bid_final_decision_pending"
  | "tracking_deadline_imminent"
  | "human_check_required"
  | "overview_human_review"
  | "blocking_items_open"
  | "order_plan_new_priority";
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
  /** 추가형 투영(spec §5). 선택된 입찰공고가 없으면 셋 다 `null`이며 발주계획·
   * 사전규격에서 추정하지 않는다. `budget`·`estimated_price`는 Decimal
   * 문자열이라 부동소수 반올림으로 값을 잃지 않는다(`BidConditionValues`와
   * 같은 관례). */
  deadline_at: string | null;
  budget: string | null;
  estimated_price: string | null;
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
  /** `overview_run`은 새 개요 계약(`prespec_overview_run`)의 run이며 그때
   * `overview_id`는 run id다. 남은 두 값은 이전 세대의 개요 입력이라 열람 경로가
   * 없다 — 링크 대신 위치만 문장으로 남긴다. */
  overview_kind: "overview_run" | "page" | "extractive";
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

// ---------------------------------------------------------------------------
// C-2 일일 운영 계약 (docs/contracts.md "C-2 일일 운영 계약", ADR-0060·0061).
//
// Exact server request/response contracts — field names, nullability, and
// literals are carried over verbatim from the pydantic schemas below. The
// `C2` prefix avoids collisions with the legacy C-1 notice-screening policy
// and quality-gate types above, which are a separate domain.
//   - screening/schemas/order_plan_policies.py
//   - screening/schemas/order_plan_daily_trigger.py
//   - screening/schemas/order_plan_quality_gates.py
//   - screening/schemas/order_plan_audit_sample.py

// -- order_plan_policies.py --------------------------------------------------

export type C2PolicyStatus = "draft" | "activation_candidate" | "active" | "retired";
export type C2PolicyQualityGateStatus = "not_measured" | "measured" | "passed" | "failed";

export interface C2PolicyCandidateRequest {
  schema_version: "policy-candidate-request.v1";
  producer: "human-review-client";
  consumer: "policy-api";
  request_id: string;
  policy_version: string;
  base_policy_sha256: string | null;
  candidate_sha256: string;
  reason: string;
}

export interface C2PolicyActivateRequest {
  schema_version: "policy-activate-request.v1";
  producer: "human-review-client";
  consumer: "policy-api";
  request_id: string;
  policy_sha256: string;
  quality_gate_artifact_sha256: string;
  // `true`로 고정하지 않는다. `false`는 활성화 검증 순서 8번에서 invalid_request가 된다.
  explicit_confirmation: boolean;
}

export interface C2PolicySummary {
  policy_version: string;
  policy_status: C2PolicyStatus;
  quality_gate_status: C2PolicyQualityGateStatus | null;
  policy_sha256: string;
  binding_sha256: string;
  created_by: string;
  created_at: string;
  activated_by: string | null;
  activated_at: string | null;
}

export interface C2PolicyListResponse {
  schema_version: "policy-list-response.v1";
  producer: "policy-api";
  consumer: "human-review-client";
  items: C2PolicySummary[];
  total: number;
}

export interface C2PolicyBlocker {
  code: string;
  detail: string | null;
}

export interface C2PolicyExternalTransportView {
  execution_allowed: boolean | null;
  approval_scope: string | null;
  approved_by: string | null;
  approved_at: string | null;
  approval_required_per_execution: boolean | null;
}

export interface C2PolicyAuditSampleSettingView {
  enabled: boolean | null;
  max_per_execution: number | null;
  review_cadence: string | null;
}

export interface C2PolicyLatestEvaluationView {
  evaluation_id: string;
  revision: number;
  result_status: "통과" | "미달" | "미측정" | "보류";
  artifact_sha256: string;
  evaluated_at: string;
}

export interface C2PolicySelectedGateView {
  gate_id: string;
  evaluation_basis: "product_rerun" | "reference_artifact_rescore";
  thresholds_decided: boolean;
  latest_evaluation: C2PolicyLatestEvaluationView | null;
}

export interface C2PolicyInspectResponse extends C2PolicySummary {
  schema_version: "policy-inspect-response.v1";
  producer: "policy-api";
  consumer: "human-review-client";
  binding_status: string | null;
  policy_file_present: boolean;
  binding_file_present: boolean;
  external_transport: C2PolicyExternalTransportView | null;
  audit_sample: C2PolicyAuditSampleSettingView | null;
  quality_gate: C2PolicySelectedGateView | null;
  activation_allowed: boolean;
  blockers: C2PolicyBlocker[];
}

export interface C2PolicyCandidateResponse {
  schema_version: "policy-candidate-response.v1";
  producer: "policy-api";
  consumer: "human-review-client";
  request_id: string;
  policy_version: string;
  policy_status: "activation_candidate";
  policy_sha256: string;
  binding_sha256: string;
  audit_event_id: string;
}

export interface C2PolicyActivateResponse {
  schema_version: "policy-activate-response.v1";
  producer: "policy-api";
  consumer: "human-review-client";
  request_id: string;
  policy_version: string;
  policy_status: "active";
  quality_gate_status: "passed";
  policy_sha256: string;
  binding_sha256: string;
  gate_id: string;
  evaluation_id: string;
  previous_active_policy_version: string | null;
  activated_by: string;
  activated_at: string;
  audit_event_id: string;
}

// -- order_plan_daily_trigger.py ---------------------------------------------

export type C2DailyTriggerReason =
  | "env_cap_off"
  | "no_active_policy"
  | "switch_off"
  | "switch_bound_to_other_version"
  | "quality_gate_not_passed"
  | "execution_transport_not_allowed"
  | "policy_file_missing";

export interface C2DailyTriggerSetRequest {
  schema_version: "daily-trigger-set-request.v1";
  producer: "human-review-client";
  consumer: "daily-trigger-api";
  request_id: string;
  policy_version: string;
  enabled: boolean;
  reason: string | null;
  // `true`로 고정하지 않는다. `false`는 서비스가 invalid_request로 거부한다.
  explicit_confirmation: boolean;
}

export interface C2DailyTriggerSwitchView {
  enabled: boolean;
  reason: string | null;
  set_by: string;
  set_at: string;
}

export interface C2DailyTriggerStateResponse {
  schema_version: "daily-trigger-state-response.v1";
  producer: "daily-trigger-api";
  consumer: "human-review-client";
  effective_enabled: boolean;
  policy_version: string | null;
  policy_sha256: string | null;
  switch: C2DailyTriggerSwitchView | null;
  reasons: C2DailyTriggerReason[];
}

export interface C2DailyTriggerSetResponse {
  schema_version: "daily-trigger-set-response.v1";
  producer: "daily-trigger-api";
  consumer: "human-review-client";
  request_id: string;
  policy_version: string;
  policy_sha256: string;
  enabled: boolean;
  reason: string | null;
  set_by: string;
  set_at: string;
  audit_event_id: string;
  effective_enabled: boolean;
  reasons: C2DailyTriggerReason[];
}

// -- order_plan_quality_gates.py ----------------------------------------------

export type C2QualityGateResultStatus = "통과" | "미달" | "미측정" | "보류";
export type C2QualityGateEvaluationBasis = "product_rerun" | "reference_artifact_rescore";

export interface C2QualityGatePassMetrics {
  recall_pct: number | null;
  precision_pct: number | null;
  important_missed: number | null;
  review_load: number | null;
}

export interface C2QualityGateCreateRequest {
  schema_version: "order-plan-quality-gate-create-request.v1";
  producer: "human-review-client";
  consumer: "quality-gate-api";
  request_id: string;
  policy_version: string;
  policy_sha256: string;
  binding_sha256: string;
  gold_manifest_sha256: string;
  gold_artifact_sha256: string;
  gold_status: string;
  scoring_input_sha256: string;
  evaluation_basis: C2QualityGateEvaluationBasis;
  measurement_run_ids: string[];
  // 네 key 모두 필수이고 값은 null을 허용한다(null = 사람 결정 전).
  threshold_recall_pct: number | null;
  threshold_precision_pct: number | null;
  threshold_important_missed_max: number | null;
  threshold_review_load_max: number | null;
}

export interface C2QualityGatePassExecutionIds {
  pass_1: string[];
  pass_2: string[] | null;
}

export interface C2QualityGatePassMetricsSet {
  pass_1: C2QualityGatePassMetrics;
  pass_2: C2QualityGatePassMetrics | null;
}

export interface C2QualityEvaluationCreateRequest {
  schema_version: "order-plan-quality-evaluation-create-request.v1";
  producer: "human-review-client";
  consumer: "quality-gate-api";
  request_id: string;
  artifact_sha256: string;
  pass_execution_ids: C2QualityGatePassExecutionIds;
  pass_metrics: C2QualityGatePassMetricsSet;
  agreement_pct: number | null;
  reference_full_window: C2QualityGatePassMetrics | null;
  reasons: string[];
}

export interface C2QualityGateThresholds {
  recall_pct: number | null;
  precision_pct: number | null;
  important_missed_max: number | null;
  review_load_max: number | null;
}

export interface C2QualityGateEvaluationMetrics {
  pass_1: C2QualityGatePassMetrics;
  pass_2: C2QualityGatePassMetrics | null;
  agreement_pct: number | null;
  reference_full_window: C2QualityGatePassMetrics | null;
}

export interface C2QualityGateEvaluationView {
  evaluation_id: string;
  gate_id: string;
  revision: number;
  result_status: C2QualityGateResultStatus;
  pass_execution_ids: C2QualityGatePassExecutionIds;
  measured_recall_pct: number | null;
  measured_precision_pct: number | null;
  measured_important_missed: number | null;
  measured_review_load: number | null;
  metrics: C2QualityGateEvaluationMetrics;
  reasons: string[];
  artifact_sha256: string;
  evaluated_by: string;
  evaluated_at: string;
}

export interface C2QualityGateView {
  gate_id: string;
  policy_version: string;
  policy_sha256: string;
  binding_sha256: string;
  gold_manifest_sha256: string;
  gold_artifact_sha256: string;
  gold_status: string;
  scoring_input_sha256: string;
  evaluation_basis: C2QualityGateEvaluationBasis;
  scoring_unit: "per_published_day";
  measurement_run_ids: string[];
  required_pass_count: 2;
  thresholds: C2QualityGateThresholds;
  created_by: string;
  created_at: string;
  latest_evaluation: C2QualityGateEvaluationView | null;
}

/** `status`는 C-2 실행 상태와 같은 enum이다 (`OrderPlanScreeningStatus`). */
export interface C2QualityGateMeasurementExecution {
  execution_id: string;
  source_run_id: string;
  status: OrderPlanScreeningStatus;
  queued_at: string;
  finished_at: string | null;
}

export interface C2QualityGateListItem extends C2QualityGateView {
  measurement_executions: C2QualityGateMeasurementExecution[];
}

export interface C2QualityGateCreateResponse extends C2QualityGateView {
  schema_version: "order-plan-quality-gate-response.v1";
  producer: "quality-gate-api";
  consumer: "human-review-client";
  request_id: string;
}

export interface C2QualityGateListResponse {
  schema_version: "order-plan-quality-gate-list-response.v1";
  producer: "quality-gate-api";
  consumer: "human-review-client";
  policy_version: string;
  items: C2QualityGateListItem[];
}

export interface C2QualityEvaluationCreateResponse extends C2QualityGateEvaluationView {
  schema_version: "order-plan-quality-evaluation-response.v1";
  producer: "quality-gate-api";
  consumer: "human-review-client";
  request_id: string;
}

// -- order_plan_audit_sample.py -----------------------------------------------

export type C2AuditSampleStratum = "classification_proximity" | "performance_similarity_proximity" | "uniform_hash";
export type C2AuditSampleStatus = "preview" | "drawn" | "pending_human_approval" | "not_applicable";

export interface C2AuditSampleDrawRequest {
  schema_version: "audit-sample-draw-request.v1";
  producer: "human-review-client";
  consumer: "audit-sample-api";
  request_id: string;
}

export interface C2AuditSampleItem {
  order_plan_pk: number;
  order_plan_unty_no: string;
  title: string | null;
  stratum: C2AuditSampleStratum;
  selection_rank: number;
  plan_id_sha256: string;
  stage1_rank: number;
  stage1_score: number;
  nearest_capability: string | null;
}

/** 미리보기와 기록 응답의 공통 field. */
export interface C2AuditSampleView {
  producer: "screening-api";
  consumer: "human-review-client";
  execution_id: string;
  status: C2AuditSampleStatus;
  reason: string | null;
  pending_decision: string | null;
  policy_version: string;
  policy_sha256: string;
  population_count: number;
  filtered_out_count: number;
  max_per_execution: number | null;
  review_cadence: string | null;
  sample: C2AuditSampleItem[] | null;
  drawn_by: string | null;
  drawn_at: string | null;
}

export interface C2AuditSamplePreviewResponse extends C2AuditSampleView {
  schema_version: "audit-sample-preview-response.v1";
}

export interface C2AuditSampleDrawResponse extends C2AuditSampleView {
  schema_version: "audit-sample-draw-response.v1";
  request_id: string;
  audit_event_id: string | null;
}
