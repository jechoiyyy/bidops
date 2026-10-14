export type StageName = "requirements_and_evaluation" | "delivery_risk_economics" | "synthesis_and_validation";
export type StageStatus = "queued" | "running" | "completed" | "failed";
export type ReviewStatus = "queued" | "running" | "completed" | "failed";
export type ValidationStatus = "passed" | "failed";
export type DocumentRole = "공고" | "정정" | "제안요청서" | "과업지시서" | "내역서" | "제출서식" | "부록" | "기타";
export type SafetyStatus = "quarantined" | "scanning" | "safe" | "blocked";
export type StructureStatus = "pending" | "processing" | "ready" | "failed" | "needs_review";
export type RiskSeverity = "차단" | "중대" | "보통" | "낮음";
export type LocatorType = "none" | "page" | "paragraph" | "table_cell" | "bbox";
export type ReportSectionKey =
  | "project_overview"
  | "eligibility_matrix"
  | "scope_deliverables"
  | "requirements_matrix"
  | "evaluation_strategy"
  | "delivery_plan"
  | "technical_integration_risks"
  | "security_legal_contract_risks"
  | "economics_scenarios"
  | "competitive_proposal_strategy"
  | "questions_internal_actions"
  | "document_bundle_limitations"
  | "decision_card";
export type ReportBlockType = "paragraph" | "matrix" | "decision_card" | "scenario" | "action_list";
export type SystemRecommendation = "추진 검토" | "조건부 추진 검토" | "보류" | "검토 종료";
export type FinalOpinionValue = "추진" | "조건부 추진" | "보류" | "검토 종료";
export type BundleStatus = "draft" | "processing" | "needs_review" | "ready" | "quarantined" | "failed" | "superseded";
/** 심층 검토 실행의 품질 표식. 이 필드가 없던 시절의 revision은 `null`이며
 * 화면은 `표식 없음`으로 보인다 — 미측정으로 승격시키지 않는다. */
export type QualityStatus = "measured" | "unmeasured_reference" | "mock_reference";
export type SegmentStatus = "classified" | "needs_human_review";
export type SegmentLocatorKind = "paragraph" | "table_cell" | "block";
export type TaxonomyLabel =
  | "business_eligibility_evaluation"
  | "technical_functional"
  | "quality_security_constraints"
  | "partnership_governance"
  | "operations_maintenance";

export type EmptyRequest = Record<string, never>;

export interface PatchDocumentVersionPayload {
  role: DocumentRole;
  effective_date: string | null;
  replaces_document_version_id: string | null;
  is_current: boolean;
  version: number;
}

export interface ConfirmedDocument {
  document_version_id: string;
  version: number;
}

export interface ConfirmDocumentBundlePayload {
  request_id: string;
  version: number;
  confirmed_documents: ConfirmedDocument[];
}

export interface CreateDeepReviewPayload {
  preview_id?: string;
  source_verification_enabled?: boolean;
  request_id: string;
  bundle_id: string;
}

export interface CreateDeepReviewAttemptPayload {
  preview_id?: string;
  source_verification_enabled?: boolean;
  request_id: string;
}

export interface DocumentVersionView {
  id: string;
  bundle_id: string;
  version: number;
  role: DocumentRole;
  effective_date: string | null;
  replaces_document_version_id: string | null;
  is_current: boolean;
  safety_status: SafetyStatus;
  structure_status: StructureStatus;
  original_filename: string;
}

export interface BundleIssue {
  issue_id: string;
  code: string;
  severity: RiskSeverity;
  blocking: boolean;
  document_version_id: string | null;
  message: string;
  locator_type: LocatorType;
  locator: Record<string, unknown> | null;
}

export interface BundleView {
  id: string;
  notice_id: number;
  revision: number;
  version: number;
  status: BundleStatus;
  documents: DocumentVersionView[];
  issues: BundleIssue[];
  confirmed_by: string | null;
  confirmed_at: string | null;
  created_at: string;
}

export interface BundleListResponse { items: BundleView[]; }

export interface StageView {
  stage: StageName;
  sequence: number;
  status: StageStatus;
  started_at: string | null;
  completed_at: string | null;
  last_error_code: string | null;
}

export interface AttemptView {
  provider?: string | null;
  model?: string | null;
  reasoning_effort?: string | null;
  preview_id?: string | null;
  source_verification_enabled?: boolean;
  id: string;
  sequence: number;
  status: "queued" | "running" | "completed" | "failed" | "superseded";
  stages: StageView[];
  started_at: string | null;
  completed_at: string | null;
  last_error_code: string | null;
}

export interface DeepReviewView {
  id: string;
  notice_id: number;
  bundle_id: string;
  status: ReviewStatus;
  current_attempt: AttemptView | null;
  attempts: AttemptView[];
  created_at: string;
  completed_at: string | null;
  quality_status: QualityStatus | null;
}

export interface ReportRow {
  row_key: string;
  label: string;
  cells: string[];
  claim_ids: string[];
}

export interface ReportBlock {
  block_id: string;
  type: ReportBlockType;
  title: string | null;
  body: string | null;
  claim_ids: string[];
  rows: ReportRow[];
}

export interface ReportSection {
  section_key: ReportSectionKey;
  title: string;
  blocks: ReportBlock[];
}

export interface ReportClaim {
  claim_id: string;
  category: string;
  claim_type: "fact" | "calculation" | "inference" | "opinion" | "unknown";
  body: string;
  status: "supported" | "unsupported" | "conflicting" | "unknown";
  formula: string | null;
  premise_claim_ids: string[];
  reason: string | null;
  evidence_ids: string[];
}

export interface ValidationSummary {
  status: ValidationStatus;
  failed: number;
  warnings: number;
  passed: number;
}

export interface LegacyDeepReviewReport {
  schema: "bidops.deep-review-report.v1";
  deep_review_id: string;
  notice_id: number;
  bundle_id: string;
  profile_version_id: string;
  policy_version_id: string;
  sections: ReportSection[];
  system_recommendation: SystemRecommendation;
  claims: ReportClaim[];
  unknowns: string[];
  validation_summary: ValidationSummary;
  created_at: string;
  /** 이 필드가 없던 옛 revision은 `null`이다. `null`을 미측정으로 읽지 않는다. */
  quality_status: QualityStatus | null;
}

export type NarrativeSectionKey = "assessment" | "scope" | "company_fit" | "delivery" | "evaluation" | "contract_economics" | "actions" | "decision_conditions";
export type NarrativeRole = "source" | "company_basis" | "impact" | "action" | "decision_condition" | "synthesis" | "recommendation";
export interface NarrativeClaim extends ReportClaim {
  report_section: NarrativeSectionKey;
  narrative_role: NarrativeRole;
  topic_key: string;
  source_unit_ids: string[];
  requirement_ids: string[];
  related_claim_ids: string[];
  is_key_point: boolean;
}
export interface NarrativeBlock extends ReportBlock {
  type: "paragraph";
  narrative_role: NarrativeRole;
  topic_key: string;
  is_key_point: boolean;
}
export interface NarrativeReport extends Omit<LegacyDeepReviewReport, "schema" | "sections" | "claims"> {
  schema: "bidops.deep-review-report.v2";
  generator_version: "narrative-v2";
  sections: { section_key: NarrativeSectionKey; title: string; status: "available" | "not_analyzed"; blocks: NarrativeBlock[] }[];
  claims: NarrativeClaim[];
  analysis_limitations: string[];
  coverage: { source_unit_id: string; status: "reviewed" | "needs_review"; claim_ids: string[]; reason: string | null }[];
}
export type DeepReviewReport = LegacyDeepReviewReport | NarrativeReport;

export interface ValidationCheck {
  check_type: string;
  status: "passed" | "failed" | "warning";
  severity: "차단" | "중대" | "보통" | "낮음";
  message: string;
  related_claim_ids: string[];
  related_evidence_ids: string[];
}

export interface DeepReviewValidation {
  schema: "bidops.deep-review-validation.v1";
  validation_run_id: string;
  report_revision_id: string;
  status: ValidationStatus;
  checks: ValidationCheck[];
  created_at: string;
}

export interface RevisionHistoryItem {
  revision_id: string;
  sequence: number;
  origin: "machine" | "human";
  validation_status: ValidationStatus | null;
  created_by_name: string | null;
  created_at: string;
}

export interface FinalOpinionView {
  id: string;
  sequence: number;
  value: FinalOpinionValue;
  reason: string;
  validation_status_at_opinion: ValidationStatus;
  acknowledged_validation_failure: boolean;
  claimed_name: string;
  created_at: string;
}

export interface ReportView {
  deep_review_id: string;
  current_revision_id: string;
  report: DeepReviewReport;
  validation: DeepReviewValidation;
  history: RevisionHistoryItem[];
  final_opinion: FinalOpinionView | null;
}

export interface EvidenceView {
  source_verification_enabled?: boolean;
  evidence_id: string;
  source_kind: "document" | "profile";
  document_version_id: string | null;
  structure_id: string | null;
  profile_version_id: string | null;
  profile_evidence_id: string | null;
  locator_type: "page" | "paragraph" | "table_cell" | "bbox" | "profile_fact";
  locator: Record<string, string | number | number[] | null>;
  quote: string;
  confidence: number | null;
  source_sha256: string;
  page: {
    structure_id: string;
    page: number;
    metadata: { number: number; width: number; height: number; image_content_object_id: string | null };
    blocks: Array<{
      block_key: string;
      parent_block_key: string | null;
      type: string;
      page: number;
      bbox: number[] | null;
      text: string;
      confidence: number | null;
      attributes: Record<string, unknown>;
    }>;
  } | null;
}

export interface PageMetadata {
  number: number;
  width: number;
  height: number;
  image_content_object_id: string | null;
}

export interface StructureExtractor {
  name: string;
  version: string;
  upstream_commit: string | null;
}

export interface StructureBlock {
  block_key: string;
  parent_block_key: string | null;
  type: string;
  page: number;
  bbox: number[] | null;
  text: string;
  confidence: number | null;
  attributes: Record<string, unknown>;
}

export interface DocumentStructure {
  schema: "bidops.document-structure.v1";
  structure_id: string;
  document_version_id: string;
  source_sha256: string;
  media_type: string;
  extractor: StructureExtractor;
  pages: PageMetadata[];
  blocks: StructureBlock[];
  warnings: string[];
  created_at: string;
}

export interface DocumentStructurePageView {
  structure_id: string;
  page: number;
  metadata: PageMetadata;
  blocks: StructureBlock[];
}

// --- 결정적 segment manifest (bidops.document-segments.v1) --------------------
//
// 이 응답에는 **원문 text가 없다.** segment에 `title`이 없는 것은 누락이 아니라
// 계약이 원문을 싣지 않기로 한 결과이므로, 화면이 제목을 만들어 내거나 다른
// endpoint에서 원문을 받아 다시 짓지 않는다.

export interface SegmentLocator {
  kind: SegmentLocatorKind;
  block_key: string;
  /** 구조 원문을 여는 페이지로, 변환 PDF의 물리 페이지 순번과 다를 수 있다. */
  page: number;
  ordinal: number;
  table_key: string | null;
  row: number | null;
  column: number | null;
}

/** 물리 PDF 순번(1 기준, 표지를 포함한 변환 PDF 기준). */
export interface SegmentPageRange {
  first: number;
  last: number;
}

/** 대응표가 segment의 블록을 PDF 페이지로 얼마나 연결했는지. `inherited`는 앞 문단
 * anchor에서 쪽을 상속한 상태다. `unavailable`이면 `page_range`는 항상 `null`이다. */
export type SegmentMappingStatus = "mapped" | "partial" | "inherited" | "unavailable";

export interface DocumentSegmentView {
  segment_id: string;
  ordinal: number;
  taxonomy_labels: TaxonomyLabel[];
  start_locator: SegmentLocator;
  end_locator: SegmentLocator;
  requirement_ids: string[];
  source_block_keys: string[];
  classification_source: "deterministic";
  /** 결정적 규칙에는 확률이 없다. 계약이 항상 `null`로 둔다. */
  confidence: null;
  status: SegmentStatus;
  /** 대응표로 확인하거나 앞 문단에서 상속한 물리 PDF 페이지 범위. 확인하지 못하면 `null`이다. */
  page_range: SegmentPageRange | null;
  mapping_status: SegmentMappingStatus;
}

export interface RequirementInventoryAmbiguity {
  reason: "prefix_unconfirmed" | "prefix_collision";
  raw_id: string | null;
  raw_prefix: string | null;
  normalized_prefix: string;
  occurrence_count: number;
  locator: SegmentLocator | null;
}

export interface RequirementInventorySummary {
  expected_ids: string[];
  duplicate_ids: string[];
  ambiguous_items: RequirementInventoryAmbiguity[];
  prefixes: string[];
  item_count: number;
  card_item_count: number;
  label_value_table_count: number;
}

export interface SegmentSpan {
  start_ordinal: number;
  end_ordinal: number;
}

export interface SegmentTocSummary {
  entry_count: number;
  matched_heading_count: number;
  unmatched_entry_count: number;
}

export interface SegmentCoverage {
  block_count: number;
  covered_block_count: number;
  segment_count: number;
  gap_count: number;
  overlap_count: number;
  gaps: SegmentSpan[];
  overlaps: SegmentSpan[];
  needs_human_review_count: number;
  toc: SegmentTocSummary;
}

export interface SegmentExtractorBinding {
  name: string;
  version: string;
  taxonomy_version: string;
  rules_sha256: string;
  schema: "bidops.document-segments.v1";
}

export interface DocumentSegmentsView {
  schema: "bidops.document-segments.v1";
  structure_id: string;
  document_version_id: string;
  source_sha256: string;
  taxonomy_version: string;
  extractor_binding: SegmentExtractorBinding;
  extractor_binding_sha256: string;
  payload_sha256: string;
  segments: DocumentSegmentView[];
  inventory_summary: RequirementInventorySummary;
  coverage: SegmentCoverage;
  warnings: string[];
  created_at: string;
}

export interface DeepReviewPreview {
  preview_id: string;
  input_sha256: string;
  provider: string;
  model: string;
  reasoning_effort: string;
  quality_status: "unmeasured_reference";
  source_verification_enabled: boolean;
  input: Record<string, unknown>;
}
