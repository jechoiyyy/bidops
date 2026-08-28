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
  request_id: string;
  bundle_id: string;
}

export interface CreateDeepReviewAttemptPayload {
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

export interface DeepReviewReport {
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
}

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
