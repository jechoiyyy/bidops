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
/** 최종 결정의 근거 종류(ADR-0058). `comparison`은 기존 비교 결과, `notice_conditions`는
 * 입찰공고 조건 요약(§9.1)만으로 한 결정이다. */
export type FinalDecisionBasisKind = "comparison" | "notice_conditions";
export type ChangeStatus = "changed" | "unchanged" | "unknown";

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

/**
 * 최신 입찰공고 조건만으로 한 최종 결정(`POST /opportunities/{id}/final-decisions`,
 * spec §9.2). 두 기대값은 사람이 실제로 검토한 공고와 그 관측을 고정한다 — 서버가
 * 임의로 최신 공고를 고르지 않는다.
 */
export interface BidNoticeFinalDecisionCreateRequest {
  request_id: string;
  expected_notice_id: number;
  expected_observation_sha256: string;
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

/**
 * v2(ADR-0058): `basis_kind`·`basis_*`가 추가되고 비교 다섯 필드는 nullable이
 * 됐다. `basis_kind==="comparison"`이면 비교 다섯 필드가 채워지고 `basis_*`는
 * `null`이며, `notice_conditions`면 반대다(DB CHECK와 같은 규칙). replay로 저장된
 * v1 receipt를 그대로 다시 받을 수 있어 두 schema_version을 모두 허용한다.
 */
export interface BidFinalDecisionView {
  schema_version: "bidops.bid-final-decision.v1" | "bidops.bid-final-decision.v2";
  id: string;
  opportunity_id: number;
  sequence: number;
  basis_kind: FinalDecisionBasisKind;
  comparison_id: string | null;
  comparison_version: number | null;
  result_sha256: string | null;
  baseline_document_version_id: string | null;
  comparison_document_version_id: string | null;
  basis_notice_id: number | null;
  basis_observation_sha256: string | null;
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

// ---------------------------------------------------------------------------
// 공고 조건 요약 (`GET /opportunities/{id}/bid-conditions`, spec §9.1).
// 모델 호출 없는 결정적 값이며, 어느 한쪽이 `null`이면 비교 결과는 `unknown`이다
// (`unchanged`로 추정하지 않는다).

export type BidConditionField =
  | "budget"
  | "estimated_price"
  | "deadline_at"
  | "opening_at"
  | "method"
  | "participation_limited"
  | "industry_limited"
  | "sw_industry_1468"
  | "joint_contract_method"
  | "successful_bid_method"
  | "technical_evaluation_rate"
  | "region_limit_basis"
  | "joint_contract_regions"
  | "change_reason"
  | "re_notice";

/** 수집된 공고에서 읽은 결정적 조건 값. 금액은 Decimal 문자열이며 `null`은
 * "관측되지 않음"이고 "없음"·`N`으로 읽지 않는다. */
export interface BidConditionValues {
  budget: string | null;
  estimated_price: string | null;
  deadline_at: string | null;
  opening_at: string | null;
  method: string | null;
  participation_limited: string | null;
  industry_limited: string | null;
  sw_industry_1468: string | null;
  joint_contract_method: string | null;
  successful_bid_method: string | null;
  technical_evaluation_rate: string | null;
  region_limit_basis: string | null;
  joint_contract_regions: string[] | null;
  change_reason: string | null;
  re_notice: string | null;
}

export interface BidConditionChange {
  field: BidConditionField;
  status: ChangeStatus;
  before: unknown;
  after: unknown;
}

export interface BidConditionNotice {
  notice_id: number;
  bid_no: string | null;
  bid_ord: string | null;
  published_at: string | null;
  observation_sha256: string | null;
  conditions: BidConditionValues;
  /** 차수 간 변경. 첫 차수는 빈 배열이다. */
  changes_from_previous: BidConditionChange[];
}

export interface BidConditionPreSpec {
  notice_id: number;
  title: string | null;
  agency: string | null;
  budget: string | null;
}

export interface BidConditionPreSpecChange {
  field: "budget" | "title";
  status: ChangeStatus;
  before: string | null;
  after: string | null;
}

export interface BidConditionsView {
  opportunity_id: number;
  generated_at: string;
  /** `notice_conditions` 최종 결정이 보내야 할 정확한 fence. 둘 다 authoritative
   * 입찰공고가 없거나 최신 공고를 정할 수 없으면 `null`이다. */
  latest_notice_id: number | null;
  latest_observation_sha256: string | null;
  pre_spec: BidConditionPreSpec | null;
  bid_notices: BidConditionNotice[];
  /** 의미가 같은 `budget`·`title`만. `deadline_at`은 `not_comparable`에 있다. */
  pre_spec_comparison: BidConditionPreSpecChange[];
  not_comparable: "deadline_at"[];
}
