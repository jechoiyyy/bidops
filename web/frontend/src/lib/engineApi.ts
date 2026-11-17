import { apiActorHeaders, apiRequest, type ReadRequestOptions } from "./api";

/** Display projection of bid_deep_engine.analysis.schemas.Analysis; no client-side verdicts. */
export interface EngineEvidence {
  quote: string;
  page: number | null;
  verified: boolean | null;
  location_status: "exact" | "ambiguous" | "unavailable";
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
  fits: { req_id: string; fit: "FULL" | "PARTIAL" | "GAP" | "UNKNOWN"; rationale: string; gap_action: string | null; evidence: EngineEvidence | null }[];
  data_to_confirm: { field: string; why: string }[];
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
