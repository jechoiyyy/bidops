import type {
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
  ValidationMetricsResponse,
  WarningListResponse,
} from "./types";

const API_PREFIX = "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
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
    const detail = typeof body === "object" && body !== null && "detail" in body
      ? body.detail
      : body;
    const message = typeof detail === "string" ? detail : `API 요청이 실패했습니다 (${response.status}).`;
    throw new ApiError(response.status, message, detail);
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
    const detail = typeof body === "object" && body !== null && "detail" in body
      ? body.detail
      : body;
    const message = typeof detail === "string" ? detail : `API 요청이 실패했습니다 (${response.status}).`;
    throw new ApiError(response.status, message, detail);
  }

  return response.blob();
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const serialized = search.toString();
  return serialized ? `?${serialized}` : "";
}

export const api = {
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

  getScreeningExecutions: (params: ScreeningExecutionQuery = {}) =>
    request<ScreeningExecutionListResponse>(`/screening/executions${query({ ...params })}`),

  listScreeningExecutions: (params: ScreeningExecutionQuery = {}) =>
    request<ScreeningExecutionListResponse>(`/screening/executions${query({ ...params })}`),

  getScreeningExecution: (executionId: string) =>
    request<ScreeningExecutionDetailResponse>(
      `/screening/executions/${encodeURIComponent(executionId)}`,
    ),

  getScreeningExecutionDetail: (executionId: string) =>
    request<ScreeningExecutionDetailResponse>(
      `/screening/executions/${encodeURIComponent(executionId)}`,
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

  getPipelineLogs: (runId: string, executionId?: string) =>
    request<PipelineLogResponse>(`/runs/${encodeURIComponent(runId)}/pipeline/logs${query({ execution_id: executionId })}`),

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

  getQualityGates: (params: QualityGateQuery = {}) =>
    request<QualityGateListResponse>(`/quality-gates${query({ ...params })}`),

  listQualityGates: (params: QualityGateQuery = {}) =>
    request<QualityGateListResponse>(`/quality-gates${query({ ...params })}`),

  getQualityGate: (gateId: string) =>
    request<QualityGateDetailResponse>(`/quality-gates/${encodeURIComponent(gateId)}`),

  getQualityGateDetail: (gateId: string) =>
    request<QualityGateDetailResponse>(`/quality-gates/${encodeURIComponent(gateId)}`),

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

  getPolicies: (params: PolicyVersionQuery = {}) =>
    request<PolicyVersionListResponse>(`/policies${query({ ...params })}`),

  listPolicies: (params: PolicyVersionQuery = {}) =>
    request<PolicyVersionListResponse>(`/policies${query({ ...params })}`),

  getPolicy: (policyVersion: string) =>
    request<PolicyVersionResponse>(`/policies/${encodeURIComponent(policyVersion)}`),

  createPolicy: (payload: PolicyVersionCreateRequest) =>
    request<PolicyVersionResponse>("/policies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  designatePolicyCandidate: (policyVersion: string, payload: PolicyCandidateRequest) =>
    request<PolicyVersionResponse>(
      `/policies/${encodeURIComponent(policyVersion)}/candidate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  activatePolicy: (policyVersion: string, payload: PolicyActivationRequest) =>
    request<PolicyActivationResponse>(
      `/policies/${encodeURIComponent(policyVersion)}/activate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  getScheduleSettings: () =>
    request<ScheduleSettingsResponse>("/schedule/settings"),

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

  getScheduleExecutions: (params: ScheduleExecutionQuery = {}) =>
    request<ScheduleExecutionListResponse>(`/schedule/executions${query({ ...params })}`),

  listScheduleExecutions: (params: ScheduleExecutionQuery = {}) =>
    request<ScheduleExecutionListResponse>(`/schedule/executions${query({ ...params })}`),

  getAlwaysOn: () =>
    request<AlwaysOnSwitchResponse>("/schedule/always-on"),

  getAlwaysOnSwitch: () =>
    request<AlwaysOnSwitchResponse>("/schedule/always-on"),

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

  getNotice: (noticePk: number) => request<NoticeDetailResponse>(`/notices/${noticePk}`),

  getNoticeAttachments: (noticePk: number) =>
    request<AttachmentProcedureResponse>(`/notices/${noticePk}/attachments`),

  uploadNoticeAttachments: (noticePk: number, file: File) => {
    const form = new FormData();
    form.append("files", file);
    return request<AttachmentProcedureResponse>(`/notices/${noticePk}/attachments`, {
      method: "POST",
      body: form,
    });
  },

  deleteAttachment: (attachmentId: number) =>
    request<void>(`/attachments/${attachmentId}`, { method: "DELETE" }),

  getAttachmentQueue: (runId: string) =>
    request<AttachmentQueueResponse>(`/attachments/queue${query({ run_id: runId })}`),

  getPortals: () => request<AgencyPortal[]>("/portals"),

  createPortal: (payload: Omit<AgencyPortal, "id">) =>
    request<AgencyPortal>("/portals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  updatePortal: (portalId: number, payload: Partial<Omit<AgencyPortal, "id">>) =>
    request<AgencyPortal>(`/portals/${portalId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
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
};
