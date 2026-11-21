import { apiActorHeaders, apiRequest, type ReadRequestOptions } from "./api";

/** Display projection of bid_deep_engine.analysis.schemas.Analysis; no client-side verdicts. */
export interface EngineEvidence {
  quote: string;
  section_id?: string | null;
  page: number | null;
  verified: boolean | null;
  repaired?: boolean | null;
  locations?: { file: string; file_sha256: string; page: number; start: number; end: number }[];
  location_status: "exact" | "ambiguous" | "unavailable";
}
/** `analysis.source_evidence`(BidOps가 덧붙인 검증된 인용의 원문 블록 위치). `evidence_path`는 `/fits/3/evidence`꼴이다. */
export interface EngineSourceEvidence {
  evidence_path: string;
  document_version_id: string;
  source_sha256: string;
  block_key: string;
  page: number | null;
  start: number;
  end: number;
  location_status: "exact" | "ambiguous";
  basis: "cited_section" | "whole_input";
}
export type EngineDecision = "GO" | "CONDITIONAL_GO" | "NO_GO";
export interface EngineStaffingReq {
  role: string;
  grade: "초급" | "중급" | "고급" | "특급" | null;
  count: number | null;
  resident: boolean | null;
  location: string | null;
  min_years: number | null;
  notes: string | null;
  evidence: EngineEvidence;
}
export interface EngineContractTerms {
  subcontract: { allowed: boolean | null; limit_pct: number | null; note: string | null };
  consortium: { allowed: boolean | null; type: string | null; note: string | null };
  ip_ownership: string | null;
  sla: { has: boolean | null; penalty_note: string | null };
  warranty_months: number | null;
  proposal_compensation: string | null;
  proposal_page_limit: number | null;
  remote_work: { allowed: boolean | null; note: string | null };
  evidence: EngineEvidence[];
}
export interface EngineRisk {
  category: string;
  severity: "H" | "M" | "L";
  description: string;
  evidence: EngineEvidence;
  mitigation: string | null;
}
export interface EngineConfirmRequest {
  id: string;
  kind: "company" | "notice" | "execution";
  fields: string[];
  title: string;
  why: string;
  affects: string[];
  blocking: boolean;
  completion: string;
}
export interface EngineProvisionalCondition {
  id: string;
  kind: string;
  title: string;
  check: string;
  if_not: string;
  gate_codes: string[];
}
export interface EngineAnalysis {
  schema_version: number;
  recommendation: {
    decision: "GO" | "CONDITIONAL_GO" | "NO_GO";
    fit_score: number;
    summary: string;
    preconditions: string[];
    why_not: string[];
  };
  assessment: {
    state: "ready" | "abstain";
    decision: "GO" | "CONDITIONAL_GO" | "NO_GO" | null;
    reason_codes: string[];
    score_interval: { min: number; max: number } | null;
    provisional?: {
      decision: EngineDecision;
      basis: "confirmed" | "assumed";
      conditions: EngineProvisionalCondition[];
      fit_coverage: { judged: number; total: number };
    } | null;
  } | null;
  gates: {
    code: string;
    rule_text: string;
    company_value: string;
    verdict: "PASS" | "FAIL" | "UNKNOWN" | "RISK";
    evidence: EngineEvidence[];
    action: string | null;
    unknown_fields: string[];
  }[];
  fits: { req_id: string; fit: "FULL" | "PARTIAL" | "GAP" | "UNKNOWN"; rationale: string; gap_action: string | null; evidence: EngineEvidence | null; evidence_portfolio_ids?: string[] }[];
  data_to_confirm: { field: string; why: string }[];
  /** 아래는 원본 Analysis에 있고 사전규격 상세 분석 완료 화면(mock 빌드 전용)이 읽는다. 옛 응답·fixture에는 없을 수 있다. */
  risks?: EngineRisk[];
  facts?: { staffing?: EngineStaffingReq[]; contract_terms?: EngineContractTerms };
  review_actions?: { requests: EngineConfirmRequest[] } | null;
  source_evidence?: EngineSourceEvidence[];
}
export interface EngineRun {
  id: string;
  company_id: string;
  notice_id: number;
  bundle_id: string;
  request_id: string;
  engine_version: string;
  engine_sha256: string;
  input_currentness: "current" | "stale" | "unknown";
  profile_version_id: string;
  profile_sha256: string;
  graph_version_id: string;
  graph_sha256: string;
  documents: Record<string, string>[];
  quality_status: "mock_reference";
  status: "queued" | "running" | "completed" | "partial" | "failed";
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  input_sha256: string;
  error_code: string | null;
  warnings: string[];
  analysis: EngineAnalysis | null;
}
export interface EngineRunList { items: EngineRun[]; total: number }
const collection = (companyId: string, noticeId: number) => `/companies/${encodeURIComponent(companyId)}/notices/${noticeId}/engine-runs`;
export const engineKeys = {
  list: (companyId: string, noticeId: number) => ["engine-runs", companyId, noticeId] as const,
  detail: (companyId: string, noticeId: number, runId: string | null) => ["engine-run", companyId, noticeId, runId] as const,
};
export const engineApi = {
  list: (companyId: string, noticeId: number, options?: ReadRequestOptions) => apiRequest<EngineRunList>(collection(companyId, noticeId), options),
  get: (id: string, options?: ReadRequestOptions) => apiRequest<EngineRun>(`/engine-runs/${encodeURIComponent(id)}`, options),
  create: (companyId: string, noticeId: number, body: { request_id: string; bundle_id: string; mode: "mock_reference" }, actor: string) => apiRequest<EngineRun>(collection(companyId, noticeId), {
    method: "POST", headers: { "Content-Type": "application/json", ...apiActorHeaders(actor) }, body: JSON.stringify(body),
  }),
};
