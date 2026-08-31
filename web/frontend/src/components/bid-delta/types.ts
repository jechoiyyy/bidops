export type BidDeltaCategory =
  | "budget_and_economics"
  | "contract_period_and_schedule"
  | "eligibility"
  | "joint_supply_and_subcontracting"
  | "scope_and_requirements"
  | "evaluation"
  | "submission";

export type CalculationStatus = "pending" | "running" | "completed" | "failed";
export type ResultStatus = "changed" | "unchanged" | "unknown" | "failed";
export type Materiality = "material" | "non_material" | "unknown";
export type Currentness = "current" | "stale" | "unknown";
export type BidDecision = "go" | "no_go";

export interface BidDeltaInputFence {
  opportunity_link_id: number;
  notice_id: number;
  bundle_id: string;
  bundle_revision: number;
  bundle_version: number;
  document_version_id: string;
  document_version_version: number;
  structure_id: string;
  source_sha256: string;
  structure_payload_sha256: string;
}

export interface BidDeltaInputRef extends BidDeltaInputFence {
  notice_source_type: string;
  notice_external_id: string;
  bid_ordinal: string | null;
  published_at: string | null;
  document_role: string;
  effective_date: string | null;
}

export interface BidDeltaComparisonCreateRequest {
  schema_version: "bidops.bid-delta-comparison-create.v1";
  request_id: string;
  category_policy_version: string;
  baseline: BidDeltaInputFence;
  comparison: BidDeltaInputFence;
}

export interface BidDeltaAttemptCreateRequest {
  schema_version: "bidops.bid-delta-attempt-create.v1";
  request_id: string;
  expected_comparison_version: number;
}

export interface BidFinalDecisionCreateRequest {
  schema_version: "bidops.bid-final-decision-create.v1";
  request_id: string;
  expected_comparison_version: number;
  expected_result_sha256: string;
  baseline_document_version_id: string;
  comparison_document_version_id: string;
  supersedes_final_decision_id: string | null;
  decision: BidDecision;
  reason: string;
}

export interface BidDeltaEvidenceView {
  id: string;
  side: "baseline" | "comparison";
  document_version_id: string;
  structure_id: string;
  source_sha256: string;
  locator_type: "page" | "paragraph" | "table_cell" | "bbox";
  locator: Record<string, unknown>;
  quote: string | null;
  verification_status: "verified" | "missing" | "mismatch";
}

export interface BidDeltaItemView {
  id: string;
  ordinal: number;
  category: BidDeltaCategory;
  result_status: ResultStatus;
  materiality: Materiality;
  before_value: string | null;
  after_value: string | null;
  summary: string | null;
  baseline_evidence: BidDeltaEvidenceView[];
  comparison_evidence: BidDeltaEvidenceView[];
  error_code: string | null;
}

export interface BidDeltaAttemptView {
  id: string;
  sequence: number;
  status: "queued" | "running" | "completed" | "failed";
  started_at: string | null;
  completed_at: string | null;
  last_error_code: string | null;
}

export interface BidFinalDecisionView {
  schema_version: "bidops.bid-final-decision.v1";
  id: string;
  opportunity_id: number;
  sequence: number;
  comparison_id: string;
  comparison_version: number;
  result_sha256: string;
  baseline_document_version_id: string;
  comparison_document_version_id: string;
  supersedes_final_decision_id: string | null;
  decision: BidDecision;
  reason: string;
  claimed_name: string;
  request_id: string;
  created_at: string;
  currentness: Currentness;
  currentness_reasons: string[];
}

export interface BidDeltaComparisonSummary {
  id: string;
  sequence: number;
  version: number;
  category_policy_version: string;
  calculation_status: CalculationStatus;
  result_status: ResultStatus | null;
  materiality: Materiality;
  baseline: BidDeltaInputRef;
  comparison: BidDeltaInputRef;
  result_sha256: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface BidDeltaComparisonView extends BidDeltaComparisonSummary {
  schema_version: "bidops.bid-delta-comparison.v1";
  opportunity_id: number;
  items: BidDeltaItemView[];
  attempts: BidDeltaAttemptView[];
  last_error_code: string | null;
  final_decisions: BidFinalDecisionView[];
  latest_final_decision: BidFinalDecisionView | null;
  decision_currentness: Currentness;
  currentness_reasons: string[];
}

export interface BidDeltaWorkspaceView {
  schema_version: "bidops.bid-delta-workspace.v1";
  opportunity_id: number;
  baseline_candidates: BidDeltaInputRef[];
  comparison_candidates: BidDeltaInputRef[];
  comparisons: BidDeltaComparisonSummary[];
  latest_final_decision: BidFinalDecisionView | null;
  decision_currentness: Currentness;
  currentness_reasons: string[];
  generated_at: string;
}
