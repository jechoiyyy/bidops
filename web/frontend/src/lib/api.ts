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
