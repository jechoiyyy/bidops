import type { QueryClient } from "@tanstack/react-query";
import { apiActorHeaders, apiQueryString, apiRequest, type ReadRequestOptions } from "./api";
import type {
  AttemptView,
  DeepReviewPreview,
  DeepReviewView,
  EvidenceView,
  ReportView,
} from "../components/deep-review/types";

/*
 * 가상회사 데모의 typed REST client (`docs/work/demo-contract.md` §1·2·4·6·9).
 *
 * 타입은 backend pydantic schema에서 그대로 옮겼다. 정본은 아래 파일이다.
 *
 * - `app/lifecycle/schemas/companies.py` (CompanyDTO·TrackingDTO)
 * - `app/deep_review/schemas/company_knowledge.py` (profile·graph·profile evidence)
 * - `app/deep_review/schemas/company_analysis.py` (목록·상세·핏·심층·보고서·비교)
 * - `app/deep_review/routers/company_analysis.py` (심층 preview·생성·재시도 body)
 * - `app/main.py`의 `GET /api/demo-config` (`{enabled:bool}` 하나)
 *
 * 이 파일은 값을 판정하지 않는다. unknown·null·is_current=false·comparison_status를
 * 서버가 준 그대로 옮기며, 순위·점수·관계를 만들지 않는다.
 *
 * Query key는 `["company", company_id, resource, ...filters/version]`이다. 회사가 다른
 * 결과가 같은 key를 공유하지 않으므로 회사 전환 뒤 다른 회사의 cache가 화면에 남지
 * 않는다. 원문 공고처럼 회사와 무관한 데이터만 기존 공통 key(`["notice", id]` 등)를
 * 공유한다. 3사 비교는 여러 회사의 행을 한 응답에 담으므로 회사 key 밖의
 * `["company-comparison", notice_id]`다.
 */

// ---------------------------------------------------------------------------
// 공통 원시형

/** canonical UUID 문자열. */
export type Uuid = string;
/** lowercase hex64. */
export type Sha256 = string;
/** timezone을 포함한 RFC3339 시각. */
export type Timestamp = string;

/** pydantic `JsonValue`. 가상 설정 값은 구조화 JSON만 허용한다(계약 §3). */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

// ---------------------------------------------------------------------------
// §1 demo-config

export interface DemoConfig {
  enabled: boolean;
}

// ---------------------------------------------------------------------------
// §2 회사·추적

export interface CompanyDTO {
  company_id: Uuid;
  slug: string;
  name: string;
  is_fictional: boolean;
  created_at: Timestamp;
}

export interface CompanyListResponse {
  items: CompanyDTO[];
  total: number;
  limit: number;
  offset: number;
}

export const COMPANY_TRACKING_STATUSES = ["미선택", "계속 추적", "보류", "종료"] as const;
export type CompanyTrackingStatus = (typeof COMPANY_TRACKING_STATUSES)[number];
/** 회사 경로 화면이 저장하는 세 상태(계약 §2, 2026-09-17 결정의 데모 한정 예외). */
export const COMPANY_TRACKING_DECISIONS = ["계속 추적", "보류", "종료"] as const satisfies readonly CompanyTrackingStatus[];

export interface CompanyTrackingDTO {
  company_id: Uuid;
  opportunity_id: number;
  tracking_status: CompanyTrackingStatus;
  reason: string | null;
  selected_by: string | null;
  selected_at: Timestamp | null;
  revision: number;
}

export interface CompanyTrackingUpdateRequest {
  tracking_status: CompanyTrackingStatus;
  reason: string;
  expected_revision: number;
  request_id: Uuid;
}

// ---------------------------------------------------------------------------
// §4 프로필·그래프·프로필 근거

export type CompanyFactStatus = "confirmed" | "inferred" | "unknown";
export type CompanyNodeOrigin = "fictional_scenario" | "public_document" | "model_inference";
export type CompanyNodeType =
  | "company"
  | "capability"
  | "technology"
  | "domain"
  | "staff_group"
  | "project"
  | "qualification"
  | "notice"
  | "requirement"
  | "evidence";
export type CompanyRelationType =
  | "has_capability"
  | "uses_technology"
  | "operates_in"
  | "has_staff"
  | "performed"
  | "supports_capability"
  | "holds_qualification"
  | "supported_by"
  | "has_requirement"
  | "requires_capability"
  | "requires_qualification";

export interface CompanyProfileFact {
  fact_key: string;
  label: string;
  status: CompanyFactStatus;
  origin: "fictional_scenario";
  value: JsonValue;
  evidence_ids: Uuid[];
}

export interface CompanyProfileView {
  schema_version: "bidops.company-profile-view.v1";
  company: CompanyDTO;
  profile_version_id: Uuid;
  profile_sha256: Sha256;
  graph_version_id: Uuid;
  graph_sha256: Sha256;
  ontology_version: string;
  facts: CompanyProfileFact[];
}

export interface PublicKnowledgeNode {
  id: string;
  type: CompanyNodeType;
  label: string;
  concept_id: string | null;
  status: CompanyFactStatus;
  origin: CompanyNodeOrigin;
  value: JsonValue;
  evidence_ids: Uuid[];
}

export interface PublicKnowledgeEdge {
  id: string;
  type: CompanyRelationType;
  from_id: string;
  to_id: string;
  status: CompanyFactStatus;
  origin: CompanyNodeOrigin;
  evidence_ids: Uuid[];
}

export interface CompanyKnowledgeGraphView {
  schema_version: "bidops.company-knowledge-graph.v1";
  company_id: Uuid;
  graph_version_id: Uuid;
  graph_sha256: Sha256;
  ontology_version: string;
  nodes: PublicKnowledgeNode[];
  edges: PublicKnowledgeEdge[];
  truncated: boolean;
  omitted_node_count: number;
}

/** depth 1..3(기본 2), limit 1..500(기본 200), root 생략은 company 노드(계약 §4). */
export interface CompanyKnowledgeGraphQuery {
  graph_version_id?: Uuid | null;
  root_node_id?: string | null;
  depth?: number | null;
  limit?: number | null;
}

export const COMPANY_GRAPH_DEFAULT_DEPTH = 2;
export const COMPANY_GRAPH_DEFAULT_LIMIT = 200;

export interface CompanyProfileEvidenceView {
  evidence_id: Uuid;
  profile_version_id: Uuid;
  fact_key: string;
  origin: "fictional_scenario";
  quote: string;
  source_sha256: Sha256;
}

// ---------------------------------------------------------------------------
// §5·6 회사별 분석

export type CompanyFitDecision = "matched" | "mismatch" | "unknown";
export type CompanyFitStatus = "queued" | "running" | "completed" | "failed" | "needs_human_review";
export type CompanyReviewStatus = "queued" | "running" | "completed" | "failed";

export interface CompanyFitSummary {
  attempt_id: Uuid;
  status: CompanyFitStatus;
  /** completed일 때만 값이 있다. 그 밖의 상태는 null이며 판정으로 읽지 않는다. */
  decision: CompanyFitDecision | null;
  summary: string | null;
  is_current: boolean;
}

export interface CompanyReviewSummary {
  review_id: Uuid;
  status: CompanyReviewStatus;
  is_current: boolean;
}

export interface CompanyNotice {
  notice_id: number;
  opportunity_id: number | null;
  title: string | null;
  posted_at: Timestamp | null;
  deadline_at: Timestamp | null;
  fit: CompanyFitSummary | null;
  review: CompanyReviewSummary | null;
  /** 사업기회 미연결이면 null이다(계약 §6). */
  tracking: CompanyTrackingDTO | null;
}

export interface CompanyPreSpecListResponse {
  schema_version: "bidops.company-pre-spec-list.v1";
  items: CompanyNotice[];
  total: number;
  limit: number;
  offset: number;
}

export type CompanyPreSpecSort = "posted_at_desc" | "deadline_asc";

export interface CompanyPreSpecListQuery {
  q?: string | null;
  fit?: CompanyFitDecision | null;
  tracking_status?: CompanyTrackingStatus | null;
  sort?: CompanyPreSpecSort | null;
  limit?: number | null;
  offset?: number | null;
}

export interface CompanyNoticeDetail extends CompanyNotice {
  overview_run_id: Uuid | null;
  bundle_id: Uuid | null;
  document_version_ids: Uuid[];
  company_id: Uuid;
}

export interface GraphPath {
  requirement_id: string;
  node_ids: string[];
  edge_ids: string[];
  profile_evidence_ids: Uuid[];
  relation: "direct" | "partial" | "unmapped";
}

export interface FrozenDocument {
  document_version_id: Uuid;
  source_sha256: Sha256;
}

export interface FrozenProvenance {
  input_sha256: Sha256;
  purpose: "company_fit" | "deep_review";
  company_id: Uuid;
  profile_version_id: Uuid;
  profile_sha256: Sha256;
  graph_version_id: Uuid;
  graph_sha256: Sha256;
  ontology_version: string;
  ontology_sha256: Sha256;
  documents: FrozenDocument[];
  overview_run_id: Uuid;
  overview_sha256: Sha256;
  bundle_id: Uuid | null;
  policy_version_id: Uuid;
  policy_sha256: Sha256;
  model_name: string;
  model_revision: string | null;
  generation_config_sha256: Sha256;
}

export interface CompanyFitReasonV2 {
  kind: "scope_match" | "scope_mismatch" | "information_gap";
  explanation: string;
  notice_refs: string[];
  company_refs: string[];
  /** frozen `input.graph_paths`의 0-based index. */
  graph_path_indexes: number[];
}

export interface CompanyFitResultV2 {
  schema_version: "bidops.prespec-company-fit-result.v2";
  decision: CompanyFitDecision;
  summary: string;
  reasons: CompanyFitReasonV2[];
  verification_items: string[];
}

export interface CompanyFitNoticeFact {
  ref: string;
  text: string;
  pages: number[];
  block_key: string | null;
}

export interface CompanyFitCompanyFact {
  ref: string;
  fact_key: string;
  status: CompanyFactStatus;
  value: JsonValue;
}

/** `CompanyScopedFitView`: 기존 CompanyFitView + 열거된 회사 필드(계약 §6·§9). */
export interface CompanyScopedFitView {
  id: Uuid;
  notice_id: number;
  status: CompanyFitStatus;
  result: CompanyFitResultV2 | null;
  error_code: string | null;
  is_current: boolean;
  overview_kind: "overview_run";
  overview_id: Uuid;
  document_version_id: Uuid;
  overview_sha256: Sha256;
  profile_version_id: Uuid;
  profile_sha256: Sha256;
  policy_digest: Sha256;
  model_name: string;
  model_revision: string | null;
  prompt_version: string;
  quality_status: "unmeasured_reference" | "mock_reference";
  notice_facts: CompanyFitNoticeFact[];
  company_facts: CompanyFitCompanyFact[];
  created_at: Timestamp;
  completed_at: Timestamp | null;
  prompt_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  company_id: Uuid;
  graph_version_id: Uuid;
  graph_sha256: Sha256;
  ontology_version: string;
  input_sha256: Sha256;
  paths: GraphPath[];
  provenance: FrozenProvenance;
}

export interface CompanyFitAttemptsView {
  company_id: Uuid;
  notice_id: number;
  /** created_at DESC, id DESC. */
  attempts: CompanyScopedFitView[];
}

// ---------------------------------------------------------------------------
// §6·9 심층 preview·승인 (기존 Luna 재사용)

export interface CompanyDeepReviewPreviewRequest {
  bundle_id: Uuid;
  source_verification_enabled: true;
  /** 재시도 preview일 때만 기존 review UUID를 준다. */
  review_id?: Uuid | null;
}

/**
 * 기존 Luna preview + 회사 identity. `input`은 CompanyAnalysisInput(purpose=deep_review)이며
 * 명시적 전송 승인 화면에만 보여 준다(계약 §6).
 */
export interface CompanyDeepReviewPreview extends DeepReviewPreview {
  provider: "codex-exec";
  model: "gpt-6-luna";
  reasoning_effort: "high";
  company_id: Uuid;
  profile_version_id: Uuid;
  graph_version_id: Uuid;
  graph_sha256: Sha256;
  ontology_version: string;
}

export interface CompanyDeepReviewCreateRequest {
  preview_id: Uuid;
  source_verification_enabled: true;
  request_id: Uuid;
  bundle_id: Uuid;
}

export interface CompanyDeepReviewAttemptRequest {
  preview_id: Uuid;
  source_verification_enabled: true;
  request_id: Uuid;
}

export interface CompanyReviewView extends DeepReviewView {
  company_id: Uuid;
  profile_version_id: Uuid;
  graph_version_id: Uuid;
  graph_sha256: Sha256;
  ontology_version: string;
  input_sha256: Sha256;
  is_current: boolean;
  provenance: FrozenProvenance;
}

/** 기존 ReportView를 `view`에 그대로 담는다. reader에는 `view`를 넘긴다. */
export interface CompanyReportView {
  schema_version: "bidops.company-report-view.v1";
  company_id: Uuid;
  graph_version_id: Uuid;
  graph_sha256: Sha256;
  ontology_version: string;
  profile_version_id: Uuid;
  view: ReportView;
}

// ---------------------------------------------------------------------------
// §6 3사 비교

export type CompanyComparisonStatus = "comparable" | "stale" | "missing" | "different_input";

export interface CompanyComparisonItem {
  company: CompanyDTO;
  fit: CompanyFitSummary | null;
  review: CompanyReviewSummary | null;
  tracking: CompanyTrackingDTO | null;
  graph_version_id: Uuid | null;
  comparison_status: CompanyComparisonStatus;
}

export interface CompanyComparisonView {
  schema_version: "bidops.company-comparison.v1";
  notice_id: number;
  document_version_ids: Uuid[];
  /** §7의 세 slug만, slug 오름차순. */
  items: CompanyComparisonItem[];
}

// ---------------------------------------------------------------------------
// 식별자 검사

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** 주소의 company_id·review_id가 UUID 모양인지. 아니면 API를 부르지 않는다. */
export function isCompanyUuid(value: string | null | undefined): value is Uuid {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

/** 주소의 notice_id가 양의 정수인지. */
export function parseNoticeId(value: string | null | undefined): number | null {
  if (typeof value !== "string" || !/^[1-9][0-9]*$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function companyBase(companyId: Uuid): string {
  return `/companies/${encodeURIComponent(companyId)}`;
}

// ---------------------------------------------------------------------------
// fetch 함수 — 모두 `api.ts`의 요청·오류 규칙(`ApiError`)을 그대로 쓴다.

const DEMO_CONFIG_TIMEOUT_MS = 5_000;

/**
 * `GET /api/demo-config`. 계약은 `{enabled:bool}` 하나다.
 *
 * - 이 세션의 첫 결정(`previous` 없음): 요청이 실패하거나 모양이 다르면 **비활성으로 닫는다**
 *   (fail closed). 회사 route는 `enabled === true`에서만 연다.
 * - 이미 결정한 뒤의 재조회: 실패·모양 오류는 일시 장애로 보고 앞선 결정을 그대로 둔다.
 *   실패를 비활성으로 바꾸면 route 표가 다시 만들어져 쓰는 중인 회사 화면이 사라진다.
 *   서버가 정상 응답으로 값을 바꾼 경우만 따른다.
 */
export async function getDemoConfig(previous?: DemoConfig): Promise<DemoConfig> {
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), DEMO_CONFIG_TIMEOUT_MS) : null;
  const fallback: DemoConfig = previous ? { enabled: previous.enabled } : { enabled: false };
  try {
    const body = await apiRequest<unknown>("/demo-config", controller ? { signal: controller.signal } : undefined);
    const enabled = typeof body === "object" && body !== null && !Array.isArray(body)
      ? (body as Record<string, unknown>).enabled
      : undefined;
    return typeof enabled === "boolean" ? { enabled } : fallback;
  } catch {
    return fallback;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/** actor 헤더(감사 표식)와 JSON body로 회사 mutation을 보낸다. */
function companyMutationInit(method: "POST" | "PATCH", actorName: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json", ...apiActorHeaders(actorName) },
    body: JSON.stringify(body),
  };
}

export const companyApi = {
  getDemoConfig,

  listCompanies: (params: { limit?: number; offset?: number } = {}, options?: ReadRequestOptions) =>
    apiRequest<CompanyListResponse>(`/companies${apiQueryString({ limit: params.limit, offset: params.offset })}`, options),

  getCompany: (companyId: Uuid, options?: ReadRequestOptions) =>
    apiRequest<CompanyDTO>(companyBase(companyId), options),

  listPreSpecs: (companyId: Uuid, params: CompanyPreSpecListQuery = {}, options?: ReadRequestOptions) =>
    apiRequest<CompanyPreSpecListResponse>(`${companyBase(companyId)}/pre-specs${apiQueryString({ ...params })}`, options),

  getPreSpec: (companyId: Uuid, noticeId: number, options?: ReadRequestOptions) =>
    apiRequest<CompanyNoticeDetail>(`${companyBase(companyId)}/pre-specs/${noticeId}`, options),

  getCompanyFit: (companyId: Uuid, noticeId: number, options?: ReadRequestOptions) =>
    apiRequest<CompanyFitAttemptsView>(`${companyBase(companyId)}/pre-specs/${noticeId}/company-fit`, options),

  getProfile: (companyId: Uuid, graphVersionId: Uuid | null = null, options?: ReadRequestOptions) =>
    apiRequest<CompanyProfileView>(`${companyBase(companyId)}/profile${apiQueryString({ graph_version_id: graphVersionId })}`, options),

  getKnowledgeGraph: (companyId: Uuid, params: CompanyKnowledgeGraphQuery = {}, options?: ReadRequestOptions) =>
    apiRequest<CompanyKnowledgeGraphView>(`${companyBase(companyId)}/knowledge-graph${apiQueryString({ ...params })}`, options),

  getProfileEvidence: (companyId: Uuid, evidenceId: Uuid, options?: ReadRequestOptions) =>
    apiRequest<CompanyProfileEvidenceView>(`${companyBase(companyId)}/profile-evidence/${encodeURIComponent(evidenceId)}`, options),

  getTracking: (companyId: Uuid, opportunityId: number, options?: ReadRequestOptions) =>
    apiRequest<CompanyTrackingDTO>(`${companyBase(companyId)}/opportunities/${opportunityId}/tracking`, options),

  /** 재시도에는 같은 `request_id`를 그대로 넘긴다. 새 저장 의도에만 새 UUID를 만든다. */
  updateTracking: (companyId: Uuid, opportunityId: number, payload: CompanyTrackingUpdateRequest, actorName: string) =>
    apiRequest<CompanyTrackingDTO>(
      `${companyBase(companyId)}/opportunities/${opportunityId}/tracking`,
      companyMutationInit("PATCH", actorName, payload),
    ),

  /** 전송 미리보기. 모델 호출이 아니며 승인 전에는 아무것도 enqueue하지 않는다. */
  createDeepReviewPreview: (companyId: Uuid, noticeId: number, payload: CompanyDeepReviewPreviewRequest) =>
    apiRequest<CompanyDeepReviewPreview>(`${companyBase(companyId)}/pre-specs/${noticeId}/deep-review-previews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  createDeepReview: (companyId: Uuid, noticeId: number, payload: CompanyDeepReviewCreateRequest, actorName: string) =>
    apiRequest<CompanyReviewView>(
      `${companyBase(companyId)}/pre-specs/${noticeId}/deep-reviews`,
      companyMutationInit("POST", actorName, payload),
    ),

  getDeepReview: (companyId: Uuid, reviewId: Uuid, options?: ReadRequestOptions) =>
    apiRequest<CompanyReviewView>(`${companyBase(companyId)}/deep-reviews/${encodeURIComponent(reviewId)}`, options),

  createDeepReviewAttempt: (companyId: Uuid, reviewId: Uuid, payload: CompanyDeepReviewAttemptRequest, actorName: string) =>
    apiRequest<AttemptView>(
      `${companyBase(companyId)}/deep-reviews/${encodeURIComponent(reviewId)}/attempts`,
      companyMutationInit("POST", actorName, payload),
    ),

  getReport: (companyId: Uuid, reviewId: Uuid, options?: ReadRequestOptions) =>
    apiRequest<CompanyReportView>(`${companyBase(companyId)}/deep-reviews/${encodeURIComponent(reviewId)}/report`, options),

  getReviewEvidence: (companyId: Uuid, reviewId: Uuid, evidenceId: Uuid, options?: ReadRequestOptions) =>
    apiRequest<EvidenceView>(
      `${companyBase(companyId)}/deep-reviews/${encodeURIComponent(reviewId)}/evidence/${encodeURIComponent(evidenceId)}`,
      options,
    ),

  getComparison: (noticeId: number, options?: ReadRequestOptions) =>
    apiRequest<CompanyComparisonView>(`/pre-specs/${noticeId}/company-comparison`, options),
};

// ---------------------------------------------------------------------------
// Query key factory

/** 회사 목록 조회 한도. 계약상 limit 최대값이 100이다. */
export const COMPANY_DIRECTORY_LIMIT = 100;

export const demoConfigQueryKey = ["demo-config"] as const;

export const companyKeys = {
  /** 회사 디렉터리(회사 선택기). 회사 결과가 아니라 회사 identity 목록이다. */
  directory: () => ["company-directory", { limit: COMPANY_DIRECTORY_LIMIT, offset: 0 }] as const,
  /** 한 회사의 모든 결과. 회사 전환 뒤 무효화는 언제나 이 prefix 안에서만 한다. */
  scope: (companyId: Uuid) => ["company", companyId] as const,
  detail: (companyId: Uuid) => ["company", companyId, "detail"] as const,
  preSpecLists: (companyId: Uuid) => ["company", companyId, "pre-specs", "list"] as const,
  preSpecList: (companyId: Uuid, filters: CompanyPreSpecListQuery) =>
    ["company", companyId, "pre-specs", "list", normalizedFilters(filters)] as const,
  preSpec: (companyId: Uuid, noticeId: number) => ["company", companyId, "pre-specs", "detail", noticeId] as const,
  companyFit: (companyId: Uuid, noticeId: number) => ["company", companyId, "pre-specs", "company-fit", noticeId] as const,
  profile: (companyId: Uuid, graphVersionId: Uuid | null = null) =>
    ["company", companyId, "profile", { graph_version_id: graphVersionId }] as const,
  knowledgeGraph: (companyId: Uuid, query: CompanyKnowledgeGraphQuery = {}) =>
    ["company", companyId, "knowledge-graph", {
      graph_version_id: query.graph_version_id ?? null,
      root_node_id: query.root_node_id ?? null,
      depth: query.depth ?? COMPANY_GRAPH_DEFAULT_DEPTH,
      limit: query.limit ?? COMPANY_GRAPH_DEFAULT_LIMIT,
    }] as const,
  profileEvidence: (companyId: Uuid, evidenceId: Uuid) => ["company", companyId, "profile-evidence", evidenceId] as const,
  tracking: (companyId: Uuid, opportunityId: number) => ["company", companyId, "tracking", opportunityId] as const,
  deepReview: (companyId: Uuid, reviewId: Uuid) => ["company", companyId, "deep-review", reviewId] as const,
  report: (companyId: Uuid, reviewId: Uuid) => ["company", companyId, "deep-review", reviewId, "report"] as const,
  reviewEvidence: (companyId: Uuid, reviewId: Uuid, evidenceId: Uuid) =>
    ["company", companyId, "deep-review", reviewId, "evidence", evidenceId] as const,
  /** 3사 비교는 여러 회사 행을 담는 교차 화면이다. */
  comparison: (noticeId: number) => ["company-comparison", noticeId] as const,
};

function normalizedFilters(filters: CompanyPreSpecListQuery): Record<keyof CompanyPreSpecListQuery, string | number | null> {
  return {
    q: filters.q?.trim() ? filters.q.trim() : null,
    fit: filters.fit ?? null,
    tracking_status: filters.tracking_status ?? null,
    sort: filters.sort ?? null,
    limit: filters.limit ?? null,
    offset: filters.offset ?? null,
  };
}

/**
 * 회사 A에서 시작한 추적 저장이 끝났을 때의 cache 반영.
 *
 * `variables.companyId`는 **저장을 시작한 순간의 회사**다. 사람이 그사이 회사 B로
 * 옮겼어도 A의 key만 갱신·무효화하며 B 화면의 cache는 건드리지 않는다. 3사 비교는
 * A의 행을 담으므로 그 공고의 비교만 함께 무효화한다.
 */
export function applyCompanyTrackingSaved(
  queryClient: QueryClient,
  variables: { companyId: Uuid; opportunityId: number; noticeId: number | null },
  saved: CompanyTrackingDTO,
): void {
  if (saved.company_id !== variables.companyId || saved.opportunity_id !== variables.opportunityId) {
    // 응답이 시작한 회사·사업기회와 다르면 어느 화면에도 반영하지 않고 다시 읽는다.
    void queryClient.invalidateQueries({ queryKey: companyKeys.scope(variables.companyId) });
    return;
  }
  queryClient.setQueryData(companyKeys.tracking(variables.companyId, variables.opportunityId), saved);
  void queryClient.invalidateQueries({ queryKey: companyKeys.preSpecLists(variables.companyId) });
  if (variables.noticeId !== null) {
    void queryClient.invalidateQueries({ queryKey: companyKeys.preSpec(variables.companyId, variables.noticeId) });
    void queryClient.invalidateQueries({ queryKey: companyKeys.comparison(variables.noticeId) });
  }
}

// ---------------------------------------------------------------------------
// 표시 문구 — 서버 값을 옮길 뿐 재판정하지 않는다.

/** matched=부합, mismatch=불일치, unknown=미확인, null=판정 없음. C-1 등급과 섞지 않는다. */
export function companyFitDecisionLabel(decision: CompanyFitDecision | null): string {
  switch (decision) {
    case "matched":
      return "부합";
    case "mismatch":
      return "불일치";
    case "unknown":
      return "미확인";
    default:
      return "판정 없음";
  }
}

export function companyFitStatusLabel(status: CompanyFitStatus): string {
  switch (status) {
    case "queued":
      return "대기";
    case "running":
      return "실행 중";
    case "completed":
      return "완료";
    case "failed":
      return "실패";
    case "needs_human_review":
      return "사람 검토 필요";
  }
}

export function companyReviewStatusLabel(status: CompanyReviewStatus): string {
  switch (status) {
    case "queued":
      return "대기";
    case "running":
      return "실행 중";
    case "completed":
      return "완료";
    case "failed":
      return "실패";
  }
}

export function companyFactStatusLabel(status: CompanyFactStatus): string {
  switch (status) {
    case "confirmed":
      return "시나리오 확정";
    case "inferred":
      return "추정";
    case "unknown":
      return "미확인";
  }
}

export function companyOriginLabel(origin: CompanyNodeOrigin): string {
  switch (origin) {
    case "fictional_scenario":
      return "가상 설정";
    case "public_document":
      return "공개 문서 사실";
    case "model_inference":
      return "모델 해석";
  }
}

/**
 * 그래프 노드·관계의 확실성 문구. 가상 설정(`fictional_scenario`)의 confirmed는
 * "시나리오 확정"이며 실제 회사 사실이 아니다. 다른 출처의 confirmed만 "확정"이다.
 */
export function companyNodeStatusLabel(status: CompanyFactStatus, origin: CompanyNodeOrigin): string {
  if (status === "confirmed") return origin === "fictional_scenario" ? "시나리오 확정" : "확정";
  return companyFactStatusLabel(status);
}

const NODE_TYPE_LABEL: Record<CompanyNodeType, string> = {
  company: "회사",
  capability: "역량",
  technology: "기술",
  domain: "업무 분야",
  staff_group: "인력군",
  project: "실적 사업",
  qualification: "자격",
  notice: "공고",
  requirement: "요구사항",
  evidence: "원본 근거",
};

/** 노드 유형의 표시 순서(묶음 순서일 뿐 순위가 아니다). */
export const COMPANY_NODE_TYPE_ORDER: readonly CompanyNodeType[] = [
  "company",
  "capability",
  "technology",
  "domain",
  "staff_group",
  "project",
  "qualification",
  "notice",
  "requirement",
  "evidence",
];

export function companyNodeTypeLabel(type: CompanyNodeType): string {
  return NODE_TYPE_LABEL[type] ?? type;
}

/** 관계 유형 문구(계약 §3 표의 "의미"). */
const RELATION_TYPE_LABEL: Record<CompanyRelationType, string> = {
  has_capability: "수행 역량",
  uses_technology: "사용 기술",
  operates_in: "업무 분야",
  has_staff: "인력군",
  performed: "수행 실적",
  supports_capability: "역량 관련 근거(충족 보증 아님)",
  holds_qualification: "자격 보유 주장",
  supported_by: "원본 근거",
  has_requirement: "문서 요구",
  requires_capability: "요구 역량",
  requires_qualification: "요구 자격",
};

export function companyRelationTypeLabel(type: CompanyRelationType): string {
  return RELATION_TYPE_LABEL[type] ?? type;
}

export function companyComparisonStatusLabel(status: CompanyComparisonStatus): string {
  switch (status) {
    case "comparable":
      return "비교 가능";
    case "stale":
      return "이전 입력";
    case "missing":
      return "결과 없음";
    case "different_input":
      return "다른 입력";
  }
}

/**
 * 비교 상태가 무엇을 뜻하는지의 설명(계약 §6). 서버가 정한 상태를 풀어 적을 뿐
 * 브라우저가 상태를 다시 계산하지 않는다. 우선순위는 다른 입력 > 이전 입력 > 결과 없음 > 비교 가능이다.
 */
export function companyComparisonStatusNote(status: CompanyComparisonStatus): string {
  switch (status) {
    case "comparable":
      return "핏과 심층 검토가 모두 있고 현재 입력 기준입니다. 비교할 수 있다는 뜻일 뿐 각 실행이 성공했다는 뜻은 아닙니다.";
    case "stale":
      return "핏 또는 심층 검토가 현재 회사 지식·문서가 아닌 이전 입력으로 만든 결과입니다. 현재 판정으로 읽지 마십시오.";
    case "missing":
      return "핏 또는 심층 검토 실행 기록이 없습니다. 기록 없음은 불일치나 낮은 평가가 아닙니다.";
    case "different_input":
      return "이 회사의 결과가 다른 문서 버전을 입력으로 삼았습니다. 다른 회사와 같은 기준으로 비교할 수 없습니다.";
  }
}

/** 서버가 정한 비교 상태의 표시 순서가 아니라 설명 목록용 고정 순서(우선순위 순). */
export const COMPANY_COMPARISON_STATUS_PRIORITY: readonly CompanyComparisonStatus[] = [
  "different_input",
  "stale",
  "missing",
  "comparable",
];

/** 긴 hash·UUID를 앞쪽 몇 글자로 줄여 보여 준다. 전체 값은 호출자가 `title`에 둔다. */
export function shortIdentity(value: string | null | undefined, length = 12): string {
  if (!value) return "없음";
  return value.length <= length ? value : value.slice(0, length);
}

export function companyFitReasonKindLabel(kind: CompanyFitReasonV2["kind"]): string {
  switch (kind) {
    case "scope_match":
      return "범위가 맞는 근거";
    case "scope_mismatch":
      return "범위가 다른 근거";
    case "information_gap":
      return "정보가 부족한 부분";
    default:
      return kind;
  }
}

export function graphPathRelationLabel(relation: GraphPath["relation"]): string {
  switch (relation) {
    case "direct":
      return "직접 연결";
    case "partial":
      return "부분 연결";
    case "unmapped":
      return "연결 없음";
    default:
      return relation;
  }
}

// ---------------------------------------------------------------------------
// 회사 사전규격 목록의 주소 검색 인자(URL이 정본)

export const COMPANY_PRE_SPEC_DEFAULT_LIMIT = 20;
/** 화면이 요청하는 쪽 크기 상한. 서버 허용(500)보다 작게 둔다. */
export const COMPANY_PRE_SPEC_MAX_LIMIT = 100;
export const COMPANY_PRE_SPEC_DEFAULT_SORT: CompanyPreSpecSort = "posted_at_desc";
export const COMPANY_PRE_SPEC_QUERY_MAX_LENGTH = 100;
export const COMPANY_FIT_FILTERS = ["matched", "mismatch", "unknown"] as const satisfies readonly CompanyFitDecision[];
export const COMPANY_PRE_SPEC_SORTS = ["posted_at_desc", "deadline_asc"] as const satisfies readonly CompanyPreSpecSort[];

/** 주소에서 읽어 허용값으로 걸러낸 목록 조건. 허용값 밖은 기본값(전체)으로 복원한다. */
export interface CompanyPreSpecListState {
  fit: CompanyFitDecision | null;
  trackingStatus: CompanyTrackingStatus | null;
  q: string;
  sort: CompanyPreSpecSort;
  limit: number;
  offset: number;
}

function parseNonNegativeInt(raw: string | null): number | null {
  if (raw === null || !/^[0-9]+$/.test(raw)) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) ? value : null;
}

export function parseCompanyPreSpecListParams(params: URLSearchParams): CompanyPreSpecListState {
  const fitRaw = params.get("fit");
  const trackingRaw = params.get("tracking_status");
  const sortRaw = params.get("sort");
  const qRaw = (params.get("q") ?? "").trim();
  const limitRaw = parseNonNegativeInt(params.get("limit"));
  const offsetRaw = parseNonNegativeInt(params.get("offset"));
  return {
    fit: (COMPANY_FIT_FILTERS as readonly string[]).includes(fitRaw ?? "") ? (fitRaw as CompanyFitDecision) : null,
    trackingStatus: (COMPANY_TRACKING_STATUSES as readonly string[]).includes(trackingRaw ?? "")
      ? (trackingRaw as CompanyTrackingStatus)
      : null,
    q: Array.from(qRaw).length <= COMPANY_PRE_SPEC_QUERY_MAX_LENGTH ? qRaw : "",
    sort: (COMPANY_PRE_SPEC_SORTS as readonly string[]).includes(sortRaw ?? "")
      ? (sortRaw as CompanyPreSpecSort)
      : COMPANY_PRE_SPEC_DEFAULT_SORT,
    limit: limitRaw !== null && limitRaw >= 1 && limitRaw <= COMPANY_PRE_SPEC_MAX_LIMIT ? limitRaw : COMPANY_PRE_SPEC_DEFAULT_LIMIT,
    offset: offsetRaw ?? 0,
  };
}

/** 서버로 보낼 조건. 전체(null)인 필터는 보내지 않는다. 모든 필터는 서버가 pagination 전에 적용한다. */
export function companyPreSpecListQuery(state: CompanyPreSpecListState): CompanyPreSpecListQuery {
  return {
    q: state.q || null,
    fit: state.fit,
    tracking_status: state.trackingStatus,
    sort: state.sort,
    limit: state.limit,
    offset: state.offset,
  };
}

/**
 * 선택을 비우는 의미 필터(검색 적용값 포함)의 지문. 정렬·offset·쪽 크기는 의미 필터가 아니라
 * 선택을 유지한다(`web/frontend/AGENTS.md` 검토 흐름).
 */
export function companyPreSpecFilterFingerprint(state: Pick<CompanyPreSpecListState, "fit" | "trackingStatus" | "q">): string {
  return `company-pre-specs:${JSON.stringify({ fit: state.fit, tracking_status: state.trackingStatus, q: state.q })}`;
}

// ---------------------------------------------------------------------------
// 회사별 탭 저장소 key

/**
 * 선택·상세 순회 `sessionStorage` key는 회사마다 다르다. 회사 A의 선택이 B 목록에서
 * 복원되지 않는다. 읽기·쓰기는 호출자가 try/catch로 감싼다(`lib/listSelection.ts`).
 */
export function companySessionKey(companyId: Uuid, name: "pre-specs.selection" | "pre-specs.traversal"): string {
  return `bidops.companies.${companyId}.${name}.v1`;
}
