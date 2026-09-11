import type {
  BidDeltaDecisionQueueQuery,
  BidDeltaDecisionQueueResponse,
  OpportunityTrackingDecisionsResponse,
  OpportunityDeepReviewsResponse,
  WorkloadResponse,
  OrderPlanScreeningExecutionCreateRequest,
  OrderPlanScreeningExecutionCreateResponse,
  OrderPlanScreeningExecutionStopRequest,
  OrderPlanScreeningExecutionStopResponse,
  OrderPlanScreeningError,
  OrderPlanScreeningErrorCode,
  AgencyPortal,
  AlwaysOnSwitchResponse,
  AlwaysOnSwitchUpdateRequest,
  AttachmentProcedureResponse,
  AttachmentQueueResponse,
  CompanyProfileSnapshotListResponse,
  JudgmentExecutionCreateRequest,
  NoticeDetailResponse,
  NoticeHistoryResponse,
  NoticeListResponse,
  OrderPlanDetailResponse,
  OrderPlanListQuery,
  OrderPlanListResponse,
  OrderPlanScreeningExecutionDetailResponse,
  OrderPlanScreeningExecutionListResponse,
  OrderPlanScreeningExecutionQuery,
  OrderPlanScreeningFeedbackCreateRequest,
  OrderPlanScreeningFeedbackCreateResponse,
  OrderPlanScreeningFeedbackListResponse,
  OrderPlanScreeningHistoryResponse,
  OverviewEnvelope,
  OverviewRangeConfirmationResponse,
  OverviewRun,
  PageOverviewCurrent,
  PageOverviewRangeConfirmationRequest,
  PageOverviewRangeConfirmationResponse,
  PageOverviewRangeReview,
  PageOverviewResponse,
  PageOverviewVerification,
  PageOverviewView,
  PreSpecListQuery,
  PreSpecListResponse,
  CompanyFitResponse,
  OpportunityDetailResponse,
  CandidateLinkDecisionRequest,
  OpportunityLinkView,
  OpportunityListQuery,
  OpportunityListResponse,
  PolicyActivationRequest,
  PolicyActivationResponse,
  PolicyCandidateRequest,
  PolicyVersionCreateRequest,
  PolicyVersionListResponse,
  PolicyVersionQuery,
  PolicyVersionResponse,
  ProfileSectionsResponse,
  ProfileUnknownsResponse,
  PipelineExecutionResponse,
  PipelineLogResponse,
  QualityGateCreateRequest,
  QualityGateDetailResponse,
  QualityGateListResponse,
  QualityGateQuery,
  QualityGateReviewUpsertRequest,
  QualityGateResponse,
  RelatedNoticeListResponse,
  ReviewResponse,
  ReviewUpsertRequest,
  RunDetailResponse,
  RunListResponse,
  RunStatsResponse,
  ScheduleExecutionCreateRequest,
  ScheduleExecutionListResponse,
  ScheduleExecutionQuery,
  ScheduleExecutionSummary,
  ScheduleSettingsResponse,
  ScheduleSettingsUpdateRequest,
  ScreeningArtifactKind,
  ScreeningExecutionDetailResponse,
  ScreeningExecutionListResponse,
  ScreeningExecutionQuery,
  ScreeningExecutionResponse,
  ScreeningStopRequest,
  TrackingStatusUpdateRequest,
  ValidationMetricsResponse,
  WarningListResponse,
} from "./types";

const API_PREFIX = "/api";

type ReadRequestOptions = {
  signal?: AbortSignal;
};

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  readonly code: string | null;
  readonly requestId: string | null;

  constructor(status: number, message: string, detail: unknown = null, requestId: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    const code = typeof detail === "object" && detail !== null && "code" in detail ? detail.code : null;
    this.code = typeof code === "string" && /^[a-z][a-z0-9_]*$/.test(code) ? code : null;
    this.requestId = typeof requestId === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(requestId) ? requestId : null;
  }
}

/**
 * Build the audit-marker headers for a Lean mutation.
 *
 * `docs/contracts.md` requires percent encoding plus an explicit format header
 * for non-ASCII names, because a raw non-ASCII header value cannot be sent.
 * This name is an audit marker, never an authentication credential.
 */
function actorHeaders(actorName: string): Record<string, string> {
  const trimmed = actorName.trim();
  // eslint-disable-next-line no-control-regex
  if (/^[\x20-\x7e]+$/.test(trimmed)) return { "X-BidOps-Actor-Name": trimmed };
  return {
    "X-BidOps-Actor-Name": `UTF-8''${encodeURIComponent(trimmed)}`,
    "X-BidOps-Actor-Name-Format": "utf-8-percent-v1",
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...init?.headers,
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "네트워크 요청에 실패했습니다.";
    throw new ApiError(0, `API에 연결할 수 없습니다. ${message}`);
  }

  const contentType = response.headers.get("content-type") ?? "";
  const body: unknown = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail = typeof body === "object" && body !== null && "error" in body
      && typeof body.error === "object" && body.error !== null
      ? body.error
      : typeof body === "object" && body !== null && "detail" in body
        ? body.detail
        : body;
    const message = typeof detail === "string"
      ? detail
      : typeof detail === "object" && detail !== null && "message" in detail
        && typeof detail.message === "string"
        ? detail.message
        : `API 요청이 실패했습니다 (${response.status}).`;
    throw new ApiError(response.status, message, detail,
      typeof body === "object" && body !== null && "request_id" in body ? body.request_id : null);
  }

  return body as T;
}

/**
 * Fetch an artifact without interpreting its media type as JSON.  Artifact
 * paths are served by the API with either JSON or NDJSON content types, but
 * their payload is intentionally not part of the metadata transport model.
 */
async function requestBlob(path: string): Promise<Blob> {
  let response: Response;

  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      headers: { Accept: "application/json, application/x-ndjson" },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "네트워크 요청에 실패했습니다.";
    throw new ApiError(0, `API에 연결할 수 없습니다. ${message}`);
  }

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    const body: unknown = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    const detail = typeof body === "object" && body !== null && "error" in body
      && typeof body.error === "object" && body.error !== null
      ? body.error
      : typeof body === "object" && body !== null && "detail" in body
        ? body.detail
        : body;
    const message = typeof detail === "string"
      ? detail
      : typeof detail === "object" && detail !== null && "message" in detail
        && typeof detail.message === "string"
        ? detail.message
        : `API 요청이 실패했습니다 (${response.status}).`;
    throw new ApiError(response.status, message, detail,
      typeof body === "object" && body !== null && "request_id" in body ? body.request_id : null);
  }

  return response.blob();
}

function query(params: Record<string, string | number | boolean | readonly string[] | null | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") {
      const serializedValue = Array.isArray(value) ? value.join(",") : String(value);
      if (serializedValue !== "") search.set(key, serializedValue);
    }
  });
  const serialized = search.toString();
  return serialized ? `?${serialized}` : "";
}

/* ── 개요 검토 envelope → 화면 view 어댑터 ────────────────────────────────
 *
 * 서버 계약은 `bidops.prespec-overview.v1` 하나다(docs/contracts.md). 개요 화면은
 * run 하나를 "현재 실행 · 결과 본문 · 범위 확인 · 주장 검증" 네 자리로 나눠 읽으므로
 * 그 모양으로 옮긴다. **여기서 하는 일은 자리 옮김뿐이다** — 없는 값을 채우거나
 * 상태를 다시 판정하지 않는다. */

/** 계약과 구조가 다른 응답을 만나면 이 표식을 돌려주고 화면은 아무것도 그리지 않는다. */
const INVALID_PAGE_OVERVIEW: PageOverviewResponse = {
  // 화면의 정본 검사(`schema_version`)가 반드시 실패하도록 계약에 없는 값을 넣는다.
  schema_version: "bidops.prespec-overview-pages.invalid" as PageOverviewResponse["schema_version"],
  notice_id: -1,
  reviews: [],
  current: null,
  range_review: null,
  verification: null,
};

function isOverviewEnvelope(envelope: OverviewEnvelope | null | undefined): envelope is OverviewEnvelope {
  return Boolean(envelope)
    && typeof envelope?.notice_id === "number"
    && envelope.schema === "bidops.prespec-overview.v1"
    && envelope.current !== undefined
    && Array.isArray(envelope.history)
    && envelope.range_review !== undefined
    && envelope.verification !== undefined;
}

function pageOverviewView(noticeId: number, run: OverviewRun): PageOverviewView | null {
  if (run.result === null) return null;
  return {
    id: run.id,
    notice_id: noticeId,
    document_version_id: run.document_version_id ?? "",
    source_sha256: run.source_sha256 ?? "",
    pdf_sha256: run.pdf_sha256 ?? "",
    pdf_page_count: run.pdf_page_count ?? 0,
    reviewed_pages: run.reviewed_pages,
    payload: { schema_version: "bidops.prespec-overview-page-review.v4", ...run.result },
    payload_sha256: run.payload_sha256 ?? "",
    validation_status: run.validation_status,
    validation_errors: run.validation_errors,
    evidence_check_status: run.evidence_check_status,
    evidence_check_errors: run.evidence_check_errors,
    quality_status: run.quality_status,
    model_name: run.model_name,
    model_revision: run.model_revision,
    prompt_version: run.prompt_version,
    created_at: run.created_at,
  };
}

function pageOverviewCurrent(run: OverviewRun): PageOverviewCurrent {
  return {
    attempt_id: run.id,
    status: run.status,
    result_id: run.result_id,
    // 화면은 첫 사유만 표시한다. 나머지 사유는 실행 기록에 남아 있다.
    reason_code: run.reason_codes[0] ?? null,
    prompt_version: run.prompt_version,
    created_at: run.created_at,
    verification_status: run.verification_status,
  };
}

function pageOverviewRangeReview(envelope: OverviewEnvelope): PageOverviewRangeReview | null {
  const review = envelope.range_review;
  if (!review) return null;
  const targetId = review.target_id ?? "";
  const selectedPages = review.selected_pages ?? [];
  const confirmation = review.confirmation;
  return {
    schema_version: "bidops.prespec-overview-range-view.v2",
    target_id: targetId,
    snapshot_id: review.document_version_id,
    // `pending`만 사람 확정 대기다. `ready`·`human_confirmed`는 확정된 자리를 읽는다.
    selection_status: review.status === "pending" ? "needs_human_review" : "ready",
    reason_code: review.reason_code,
    pdf_page_count: review.pdf_page_count,
    created_at: confirmation?.created_at ?? "",
    candidates_mode: review.mode,
    candidate_status: review.candidate_status,
    candidate_count_total: review.candidate_count_total,
    candidate_count_returned: review.candidate_count_returned,
    warning_codes: review.warning_codes,
    selected_pages: [...selectedPages],
    can_confirm: review.can_confirm,
    candidates: review.candidates,
    assisted: null,
    confirmation: confirmation
      ? {
        target_id: targetId,
        confirmed_from_target_id: targetId,
        // 확정 기록은 쪽만 남는다. 절 번호는 계약에 없으므로 지어내지 않는다.
        start_index: null,
        end_index: null,
        first_page: confirmation.page_start,
        last_page: confirmation.page_end,
        page_numbers: Array.from(
          { length: Math.max(0, confirmation.page_end - confirmation.page_start + 1) },
          (_unused, index) => confirmation.page_start + index,
        ),
        actor: confirmation.actor_name,
        note: confirmation.note,
        created_at: confirmation.created_at,
      }
      : null,
  };
}

function pageOverviewVerification(envelope: OverviewEnvelope): PageOverviewVerification | null {
  const verification = envelope.verification;
  if (!verification) return null;
  return {
    verification_id: verification.verification_id,
    status: verification.status,
    reason_codes: verification.reason_codes,
    claims: verification.claims.map((claim) => ({
      claim_id: claim.claim_id,
      text: claim.text,
      deterministic_status: claim.deterministic.status,
      semantic_status: claim.semantic.status,
      reason_codes: [...new Set([...claim.deterministic.reason_codes, ...claim.semantic.reason_codes])],
      verified_evidence: claim.verified_evidence,
    })),
  };
}

/** 개요 envelope 하나를 화면이 읽는 view 모양으로 옮긴다. */
export function toPageOverviewResponse(envelope: OverviewEnvelope): PageOverviewResponse {
  if (!isOverviewEnvelope(envelope)) return INVALID_PAGE_OVERVIEW;
  const noticeId = envelope.notice_id;
  const runs = envelope.current && !envelope.history.some((run) => run.id === envelope.current?.id)
    ? [envelope.current, ...envelope.history]
    : envelope.history;
  return {
    schema_version: "bidops.prespec-overview-pages.v2",
    notice_id: noticeId,
    // 결과 본문이 있는 run만 본문 자리에 온다. 실패·취소는 현재 실행 자리가 말한다.
    reviews: runs.map((run) => pageOverviewView(noticeId, run)).filter((view): view is PageOverviewView => view !== null),
    current: envelope.current ? pageOverviewCurrent(envelope.current) : null,
    range_review: pageOverviewRangeReview(envelope),
    verification: pageOverviewVerification(envelope),
  };
}

export const api = {
  getWorkload: (options?: ReadRequestOptions) => request<WorkloadResponse>("/workload", options),

  getBidDeltaDecisionQueue: (params: BidDeltaDecisionQueueQuery = {}, options?: ReadRequestOptions) =>
    request<BidDeltaDecisionQueueResponse>(`/bid-delta/decision-queue${query({ ...params })}`, options),

  getOpportunityTrackingDecisions: (opportunityId: number, options?: ReadRequestOptions) =>
    request<OpportunityTrackingDecisionsResponse>(`/opportunities/${opportunityId}/tracking-decisions`, options),

  getOpportunityDeepReviews: (opportunityId: number, options?: ReadRequestOptions) =>
    request<OpportunityDeepReviewsResponse>(`/opportunities/${opportunityId}/deep-reviews`, options),

  getRuns: () => request<RunListResponse>("/runs"),

  getRun: (runId: string) => request<RunDetailResponse>(`/runs/${encodeURIComponent(runId)}`),

  getRunStats: (runId: string) =>
    request<RunStatsResponse>(`/runs/${encodeURIComponent(runId)}/stats`),

  getRunWarnings: (runId: string) =>
    request<WarningListResponse>(`/runs/${encodeURIComponent(runId)}/warnings`),

  runPipeline: (runId: string, stage: "collect" | "sample" | "report", fromRaw = false) =>
    request<PipelineExecutionResponse>(`/runs/${encodeURIComponent(runId)}/pipeline/${stage}${query({ from_raw: fromRaw ? "true" : undefined })}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from_raw: fromRaw }),
    }),

  /** Enqueue the full-run judgment request; the server returns HTTP 202. */
  enqueueJudgment: (runId: string, payload: JudgmentExecutionCreateRequest) =>
    request<ScreeningExecutionResponse>(
      `/runs/${encodeURIComponent(runId)}/pipeline/judgment`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  // Keep a descriptive alias for screens that use the existing pipeline
  // terminology.  Both names target the same enqueue-only endpoint.
  startJudgmentPipeline: (runId: string, payload: JudgmentExecutionCreateRequest) =>
    request<ScreeningExecutionResponse>(
      `/runs/${encodeURIComponent(runId)}/pipeline/judgment`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  getScreeningExecutions: (
    params: ScreeningExecutionQuery = {},
    options?: ReadRequestOptions,
  ) =>
    request<ScreeningExecutionListResponse>(
      `/screening/executions${query({ ...params })}`,
      options,
    ),

  listScreeningExecutions: (
    params: ScreeningExecutionQuery = {},
    options?: ReadRequestOptions,
  ) =>
    request<ScreeningExecutionListResponse>(
      `/screening/executions${query({ ...params })}`,
      options,
    ),

  getScreeningExecution: (executionId: string, options?: ReadRequestOptions) =>
    request<ScreeningExecutionDetailResponse>(
      `/screening/executions/${encodeURIComponent(executionId)}`,
      options,
    ),

  getScreeningExecutionDetail: (executionId: string, options?: ReadRequestOptions) =>
    request<ScreeningExecutionDetailResponse>(
      `/screening/executions/${encodeURIComponent(executionId)}`,
      options,
    ),

  stopScreeningExecution: (executionId: string, payload: ScreeningStopRequest) =>
    request<ScreeningExecutionResponse>(
      `/screening/executions/${encodeURIComponent(executionId)}/stop`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  /** Return the server's safe relative API path for a known artifact kind. */
  getScreeningArtifactUrl: (executionId: string, kind: ScreeningArtifactKind) =>
    `${API_PREFIX}/screening/executions/${encodeURIComponent(executionId)}/artifacts/${kind}`,

  /** Download an artifact as a Blob; the artifact body has no invented shape. */
  getScreeningArtifact: (executionId: string, kind: ScreeningArtifactKind) =>
    requestBlob(
      `/screening/executions/${encodeURIComponent(executionId)}/artifacts/${kind}`,
    ),

  // Order-plan C-2 review endpoints are intentionally separate from the
  // legacy notice-screening endpoints above.  The frontend only consumes the
  // projections documented in docs/contracts.md.
  getOrderPlans: (
    params: OrderPlanListQuery = {},
    options?: ReadRequestOptions,
  ) =>
    request<OrderPlanListResponse>(
      `/order-plans${query({ ...params })}`,
      options,
    ),

  getOrderPlan: (orderPlanPk: number, options?: ReadRequestOptions) =>
    request<OrderPlanDetailResponse>(`/order-plans/${orderPlanPk}`, options),

  getOrderPlanScreeningHistory: (orderPlanPk: number, options?: ReadRequestOptions) =>
    request<OrderPlanScreeningHistoryResponse>(
      `/order-plans/${orderPlanPk}/screening-history`,
      options,
    ),

  getOrderPlanScreeningExecutions: (
    params: OrderPlanScreeningExecutionQuery = {},
    options?: ReadRequestOptions,
  ) =>
    request<OrderPlanScreeningExecutionListResponse>(
      `/order-plan-screening/executions${query({ ...params })}`,
      options,
    ),

  getOrderPlanScreeningExecution: (executionId: string, options?: ReadRequestOptions) =>
    request<OrderPlanScreeningExecutionDetailResponse>(
      `/order-plan-screening/executions/${encodeURIComponent(executionId)}`,
      options,
    ),

  createOrderPlanScreeningExecution: (
    payload: OrderPlanScreeningExecutionCreateRequest,
    actorName: string,
  ) => request<OrderPlanScreeningExecutionCreateResponse>("/order-plan-screening/executions", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
    body: JSON.stringify(payload),
  }),

  stopOrderPlanScreeningExecution: (
    executionId: string,
    payload: OrderPlanScreeningExecutionStopRequest,
    actorName: string,
  ) => request<OrderPlanScreeningExecutionStopResponse>(
    `/order-plan-screening/executions/${encodeURIComponent(executionId)}/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify(payload),
    },
  ),

  getOrderPlanScreeningFeedback: (
    orderPlanPk: number,
    executionId?: string | null,
    options?: ReadRequestOptions,
  ) =>
    request<OrderPlanScreeningFeedbackListResponse>(
      `/order-plans/${orderPlanPk}/screening-feedback${query({ execution_id: executionId })}`,
      options,
    ),

  createOrderPlanScreeningFeedback: (
    orderPlanPk: number,
    payload: OrderPlanScreeningFeedbackCreateRequest,
    actorName: string,
  ) =>
    request<OrderPlanScreeningFeedbackCreateResponse>(
      `/order-plans/${orderPlanPk}/screening-feedback`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
        body: JSON.stringify(payload),
      },
    ),

  getPipelineLogs: (
    runId: string,
    executionId?: string,
    options?: ReadRequestOptions,
  ) =>
    request<PipelineLogResponse>(
      `/runs/${encodeURIComponent(runId)}/pipeline/logs${query({ execution_id: executionId })}`,
      options,
    ),

  getValidationMetrics: (runId: string) =>
    request<ValidationMetricsResponse>(`/metrics/validation${query({ run_id: runId })}`),

  getProfileSections: () => request<ProfileSectionsResponse>("/profile/sections"),

  getProfileUnknowns: () => request<ProfileUnknownsResponse>("/profile/unknowns"),

  getProfileSnapshots: () =>
    request<CompanyProfileSnapshotListResponse>("/profile/snapshots"),

  createQualityGate: (payload: QualityGateCreateRequest) =>
    request<QualityGateResponse>("/quality-gates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  getQualityGates: (params: QualityGateQuery = {}, options?: ReadRequestOptions) =>
    request<QualityGateListResponse>(`/quality-gates${query({ ...params })}`, options),

  listQualityGates: (params: QualityGateQuery = {}, options?: ReadRequestOptions) =>
    request<QualityGateListResponse>(`/quality-gates${query({ ...params })}`, options),

  getQualityGate: (gateId: string, options?: ReadRequestOptions) =>
    request<QualityGateDetailResponse>(`/quality-gates/${encodeURIComponent(gateId)}`, options),

  getQualityGateDetail: (gateId: string, options?: ReadRequestOptions) =>
    request<QualityGateDetailResponse>(`/quality-gates/${encodeURIComponent(gateId)}`, options),

  upsertQualityGateReview: (
    gateId: string,
    noticeId: string,
    payload: QualityGateReviewUpsertRequest,
  ) =>
    request<QualityGateDetailResponse>(
      `/quality-gates/${encodeURIComponent(gateId)}/reviews/${encodeURIComponent(noticeId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  saveQualityGateReview: (
    gateId: string,
    noticeId: string,
    payload: QualityGateReviewUpsertRequest,
  ) =>
    request<QualityGateDetailResponse>(
      `/quality-gates/${encodeURIComponent(gateId)}/reviews/${encodeURIComponent(noticeId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  getPolicies: (params: PolicyVersionQuery = {}, options?: ReadRequestOptions) =>
    request<PolicyVersionListResponse>(`/policies${query({ ...params })}`, options),

  listPolicies: (params: PolicyVersionQuery = {}, options?: ReadRequestOptions) =>
    request<PolicyVersionListResponse>(`/policies${query({ ...params })}`, options),

  getPolicy: (policyVersion: string) =>
    request<PolicyVersionResponse>(`/policies/${encodeURIComponent(policyVersion)}`),

  createPolicy: (payload: PolicyVersionCreateRequest, actorName: string) =>
    request<PolicyVersionResponse>("/policies", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify(payload),
    }),

  designatePolicyCandidate: (policyVersion: string, payload: PolicyCandidateRequest, actorName: string) =>
    request<PolicyVersionResponse>(
      `/policies/${encodeURIComponent(policyVersion)}/candidate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
        body: JSON.stringify(payload),
      },
    ),

  activatePolicy: (policyVersion: string, payload: PolicyActivationRequest, actorName: string) =>
    request<PolicyActivationResponse>(
      `/policies/${encodeURIComponent(policyVersion)}/activate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
        body: JSON.stringify(payload),
      },
    ),

  getScheduleSettings: (options?: ReadRequestOptions) =>
    request<ScheduleSettingsResponse>("/schedule/settings", options),

  updateScheduleSettings: (payload: ScheduleSettingsUpdateRequest) =>
    request<ScheduleSettingsResponse>("/schedule/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  createScheduleExecution: (payload: ScheduleExecutionCreateRequest) =>
    request<ScheduleExecutionSummary>("/schedule/executions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  createManualScheduleExecution: (payload: ScheduleExecutionCreateRequest) =>
    request<ScheduleExecutionSummary>("/schedule/executions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  recoverScheduleExecution: (payload: ScheduleExecutionCreateRequest) =>
    request<ScheduleExecutionSummary>("/schedule/executions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  getScheduleExecutions: (
    params: ScheduleExecutionQuery = {},
    options?: ReadRequestOptions,
  ) =>
    request<ScheduleExecutionListResponse>(
      `/schedule/executions${query({ ...params })}`,
      options,
    ),

  listScheduleExecutions: (
    params: ScheduleExecutionQuery = {},
    options?: ReadRequestOptions,
  ) =>
    request<ScheduleExecutionListResponse>(
      `/schedule/executions${query({ ...params })}`,
      options,
    ),

  getAlwaysOn: (options?: ReadRequestOptions) =>
    request<AlwaysOnSwitchResponse>("/schedule/always-on", options),

  getAlwaysOnSwitch: (options?: ReadRequestOptions) =>
    request<AlwaysOnSwitchResponse>("/schedule/always-on", options),

  updateAlwaysOn: (payload: AlwaysOnSwitchUpdateRequest) =>
    request<AlwaysOnSwitchResponse>("/schedule/always-on", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  updateAlwaysOnSwitch: (payload: AlwaysOnSwitchUpdateRequest) =>
    request<AlwaysOnSwitchResponse>("/schedule/always-on", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  getNotices: (params: {
    run_id: string;
    grade?: string;
    readiness?: string;
    focus?: string;
    sample_role?: string;
    attachment?: "any" | "none" | "manual";
    q?: string;
    sort?: "deadline" | "grade" | "published";
    limit?: number;
    offset?: number;
  }) => request<NoticeListResponse>(`/notices${query(params)}`),

  getPreSpecs: (params: PreSpecListQuery = {}, options?: ReadRequestOptions) =>
    request<PreSpecListResponse>(
      `/pre-specs${query({
        notice_pk: params.notice_pk,
        sw_only: params.sw_only === null || params.sw_only === undefined ? undefined : String(params.sw_only),
        business_division: params.business_division,
        auto_preparation_status: params.auto_preparation_status,
        origin: params.origin,
        q: params.q,
        sort: params.sort,
        limit: params.limit,
        offset: params.offset,
      })}`,
      options,
    ),

  getCompanyFit: (noticeId: number, options?: ReadRequestOptions) =>
    request<CompanyFitResponse>(`/pre-specs/${noticeId}/company-fit`, options),

  /** 사전규격 개요 검토 전체(`bidops.prespec-overview.v1`)를 화면 view 모양으로
   * 읽는다(`toPageOverviewResponse`). run이 없으면 `current`가 `null`이며 화면은
   * 그것을 미시작으로 읽는다. */
  getPageOverviews: async (noticeId: number, options?: ReadRequestOptions) =>
    toPageOverviewResponse(await request<OverviewEnvelope>(`/pre-specs/${noticeId}/overview`, options)),

  /**
   * 개요 입력 범위를 사람이 확정한다. 담당자 이름은 감사 표식이며 인증이 아니다.
   *
   * 확정은 그 범위로 개요 검토 run 하나를 예약한다(`attempt_enqueued`는 true).
   * 절 후보로 고른 범위는 `candidate_indices`로, 쪽으로 고른 범위는 `page_start`·
   * `page_end`로 나간다. 오류는 `ApiError.code`의 안전 코드(`run_active`·
   * `document_not_current_safe`·`range_invalid`·`candidate_range_incomplete`·
   * `candidate_range_unavailable`)로만 구분하고 서버 message를 분기 조건으로
   * 쓰지 않는다.
   */
  confirmPageOverviewRange: async (
    noticeId: number,
    payload: PageOverviewRangeConfirmationRequest,
    actorName: string,
  ): Promise<PageOverviewRangeConfirmationResponse> => {
    const note = payload.note === null ? {} : { note: payload.note };
    const body = payload.start_index !== null && payload.end_index !== null
      ? { candidate_indices: [payload.start_index, payload.end_index], ...note }
      : { page_start: payload.first_page, page_end: payload.last_page, ...note };
    const saved = await request<OverviewRangeConfirmationResponse>(
      `/pre-specs/${noticeId}/overview/range-confirmations`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
        body: JSON.stringify(body),
      },
    );
    return {
      target_id: saved.run_id,
      selection_status: "ready",
      first_page: saved.page_start,
      last_page: saved.page_end,
      page_numbers: Array.from(
        { length: Math.max(0, saved.page_end - saved.page_start + 1) },
        (_unused, index) => saved.page_start + index,
      ),
      attempt_enqueued: saved.attempt_enqueued,
    };
  },

  /** run이 고정한 스냅샷 PDF의 안전한 상대 경로. 화면은 이 경로로만 원문을 연다. */
  preSpecOverviewRunPdfUrl: (noticeId: number, runId: string) =>
    `${API_PREFIX}/pre-specs/${noticeId}/overview/runs/${encodeURIComponent(runId)}/pdf`,

  /** run이 아직 없을 때도 여는 최신 안전 snapshot PDF. */
  preSpecOverviewSnapshotPdfUrl: (noticeId: number) =>
    `${API_PREFIX}/pre-specs/${noticeId}/overview/snapshot/pdf`,

  getNotice: (noticePk: number) => request<NoticeDetailResponse>(`/notices/${noticePk}`),

  getNoticeAttachments: (noticePk: number) =>
    request<AttachmentProcedureResponse>(`/notices/${noticePk}/attachments`),

  uploadNoticeAttachments: (noticePk: number, file: File, actorName: string) => {
    const form = new FormData();
    form.append("files", file);
    return request<AttachmentProcedureResponse>(`/notices/${noticePk}/attachments`, {
      method: "POST",
      headers: actorHeaders(actorName),
      body: form,
    });
  },

  deleteAttachment: (attachmentId: number, actorName: string) =>
    request<void>(`/attachments/${attachmentId}`, {
      method: "DELETE",
      headers: actorHeaders(actorName),
    }),

  getAttachmentQueue: (runId: string) =>
    request<AttachmentQueueResponse>(`/attachments/queue${query({ run_id: runId })}`),

  getPortals: () => request<AgencyPortal[]>("/portals"),

  createPortal: (payload: Omit<AgencyPortal, "id">, actorName: string) =>
    request<AgencyPortal>("/portals", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify(payload),
    }),

  updatePortal: (portalId: number, payload: Partial<Omit<AgencyPortal, "id">>, actorName: string) =>
    request<AgencyPortal>(`/portals/${portalId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify(payload),
    }),

  getNoticeHistory: (noticePk: number) =>
    request<NoticeHistoryResponse>(`/notices/${noticePk}/history`),

  getRelatedNotices: (noticePk: number) =>
    request<RelatedNoticeListResponse>(`/notices/${noticePk}/related`),

  getReviews: (runId: string) =>
    request<ReviewResponse[]>(`/reviews${query({ run_id: runId })}`),

  saveReview: (noticePk: number, payload: ReviewUpsertRequest) =>
    request<ReviewResponse>(`/notices/${noticePk}/review`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  getOpportunities: (params: OpportunityListQuery = {}, options?: ReadRequestOptions) =>
    request<OpportunityListResponse>(
      `/opportunities${query({
        section: params.section,
        tracking_status: params.tracking_status,
        first_registered_stage: params.first_registered_stage,
        sort: params.sort,
        limit: params.limit,
        offset: params.offset,
      })}`,
      options,
    ),

  getOpportunity: (opportunityId: number, options?: ReadRequestOptions) =>
    request<OpportunityDetailResponse>(`/opportunities/${opportunityId}`, options),

  /** 후보 연결 하나에 사람 판정을 남긴다. 응답은 갱신된 연결 하나다. */
  decideOpportunityLink: (
    linkId: number,
    payload: CandidateLinkDecisionRequest,
    actorName: string,
  ) =>
    request<OpportunityLinkView>(`/opportunities/links/${linkId}/decision`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify(payload),
    }),

  updateOpportunityTrackingStatus: (
    opportunityId: number,
    payload: TrackingStatusUpdateRequest,
    actorName: string,
  ) =>
    request<OpportunityDetailResponse>(`/opportunities/${opportunityId}/tracking-status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify(payload),
    }),
};


const ORDER_PLAN_SCREENING_ERROR_CODES: readonly OrderPlanScreeningErrorCode[] = [
  "actor_name_required", "actor_name_invalid", "invalid_request", "not_found",
  "source_run_incomplete", "policy_not_active", "binding_mismatch", "service_unavailable",
  "active_execution_exists", "idempotency_conflict", "immutable_conflict",
  "execution_not_stoppable", "artifact_kind_invalid", "artifact_not_ready", "feedback_conflict", "processing_failed",
];

/** Reads only stable codes from the common API parser, never server messages. */
export function parseOrderPlanScreeningError(error: unknown): OrderPlanScreeningError | null {
  if (!(error instanceof ApiError)) return null;
  const code = ORDER_PLAN_SCREENING_ERROR_CODES.find((candidate) => candidate === error.code)
    ?? (error.status === 422 ? "invalid_request" : error.status === 503 ? "service_unavailable" : null);
  return { status: error.status, code, request_id: error.requestId };
}
