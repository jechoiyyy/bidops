import type {
  BidDeltaDecisionQueueQuery,
  BriefingItemView,
  BriefingReactionRequest,
  BriefingView,
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
  C2PolicyListResponse,
  C2PolicyInspectResponse,
  C2PolicyCandidateRequest,
  C2PolicyCandidateResponse,
  C2PolicyActivateRequest,
  C2PolicyActivateResponse,
  C2QualityGateListResponse,
  C2DailyTriggerStateResponse,
  C2DailyTriggerSetRequest,
  C2DailyTriggerSetResponse,
  C2AuditSamplePreviewResponse,
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
  PreSpecReviewExclusionRequest,
  PreSpecReviewExclusionResponse,
  PreSpecListQuery,
  PreSpecListResponse,
  PreSpecOrderPlanCandidatesResponse,
  CompanyFitResponse,
  OpportunityDetailResponse,
  OpportunityActivityQuery,
  OpportunityActivityResponse,
  OpportunityNoteCreateRequest,
  OpportunityNoteView,
  CandidateLinkDecisionRequest,
  OpportunityLinkView,
  OpportunityListQuery,
  OpportunityListResponse,
  OpportunitySearchRequest,
  OpportunitySearchResponse,
  OpportunityTrackingStatus,
  RecheckAcknowledgementRequest,
  OrderPlanBulkEndRequest,
  OrderPlanBulkEndResponse,
  OrderPlanBulkExcludedStatus,
  OrderPlanBulkFailureCode,
  OrderPlanBulkPreviewItem,
  OrderPlanBulkPreviewResponse,
  OrderPlanBulkStartItem,
  OrderPlanBulkStartRequest,
  OrderPlanBulkStartResponse,
  OrderPlanBulkStatusCount,
  OrderPlanBulkSummary,
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

/** A response was received, but it cannot safely be treated as a bulk receipt. */
export class OrderPlanBulkTrackingResultUnconfirmedError extends ApiError {
  constructor() {
    super(0, "일괄 추적 결과를 확인할 수 없습니다.", { code: "result_unconfirmed" });
    this.name = "OrderPlanBulkTrackingResultUnconfirmedError";
  }
}

/** ADR-0063: 일괄 추적 종료 한 요청의 상한(PoC 값). 서버는 초과를 422 `too_long`으로 거부한다. */
export const ORDER_PLAN_BULK_END_MAX_SELECTION = 200;

const BULK_EXCLUDED_STATUSES = ["계속 추적", "보류", "종료"] as const;
const BULK_TRACKING_STATUSES = ["미선택", ...BULK_EXCLUDED_STATUSES] as const;
const BULK_ELIGIBILITIES = ["eligible", "excluded", "failed"] as const;
const BULK_OUTCOMES = ["succeeded", "excluded", "failed"] as const;
const BULK_FAILURE_CODES = [
  "order_plan_not_found",
  "owning_opportunity_missing",
  "owner_changed",
  "ownership_conflict",
  "processing_failed",
  "temporarily_unavailable",
] as const;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const AWARE_TIMESTAMP_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

const PREVIEW_RESPONSE_KEYS = [
  "schema_version", "selected_plan_count", "unique_owner_count",
  "eligible_plan_count", "eligible_owner_count", "excluded_by_status",
  "failure_plan_count", "items",
] as const;
const PREVIEW_ITEM_KEYS = [
  "order_plan_id", "opportunity_id", "tracking_status", "eligibility", "code",
] as const;
const START_RESPONSE_KEYS = ["schema_version", "request_id", "completed_at", "items", "summary"] as const;
const START_ITEM_KEYS = [
  "order_plan_id", "opportunity_id", "outcome", "status_at_decision", "code", "audit_event_id",
] as const;
const SUMMARY_KEYS = [
  "selected_plan_count", "unique_owner_count", "succeeded_plan_count",
  "succeeded_owner_count", "excluded_plan_count", "excluded_by_status", "failed_plan_count",
] as const;
const STATUS_COUNT_KEYS = ["plan_count", "owner_count"] as const;

type UnknownRecord = Record<string, unknown>;

function exactRecord(value: unknown, keys: readonly string[]): UnknownRecord | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const actual = Object.keys(value);
  if (actual.length !== keys.length || !keys.every((key) => actual.includes(key))) return null;
  const record: UnknownRecord = {};
  for (const key of actual) {
    record[key] = Object.getOwnPropertyDescriptor(value, key)?.value;
  }
  return record;
}

function strictInteger(value: unknown, minimum = 0): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum;
}

function positiveId(value: unknown): value is number {
  return strictInteger(value, 1);
}

function nullablePositiveId(value: unknown): number | null | undefined {
  if (value === null) return null;
  return positiveId(value) ? value : undefined;
}

function nullableTrackingStatus(value: unknown): OpportunityTrackingStatus | null | undefined {
  if (value === null) return null;
  for (const status of BULK_TRACKING_STATUSES) {
    if (value === status) return status;
  }
  return undefined;
}

function nullableFailureCode(value: unknown): OrderPlanBulkFailureCode | null | undefined {
  if (value === null) return null;
  for (const code of BULK_FAILURE_CODES) {
    if (value === code) return code;
  }
  return undefined;
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

function isAwareTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = AWARE_TIMESTAMP_PATTERN.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return year >= 1
    && month >= 1 && month <= 12
    && day >= 1 && day <= daysInMonth
    && hour >= 0 && hour <= 23
    && minute >= 0 && minute <= 59
    && second >= 0 && second <= 59
    && Number.isFinite(Date.parse(value));
}

function normalizedPlanIds(ids: readonly number[]): number[] {
  if (!Array.isArray(ids) || ids.length === 0 || ids.some((id) => !positiveId(id))) {
    throw new ApiError(422, "요청 형식이 올바르지 않습니다.", { code: "invalid_request" });
  }
  return [...new Set(ids)].sort((left, right) => left - right);
}

function parseStatusCount(value: unknown): OrderPlanBulkStatusCount | null {
  const record = exactRecord(value, STATUS_COUNT_KEYS);
  if (!record || !strictInteger(record.plan_count) || !strictInteger(record.owner_count)) return null;
  return { plan_count: record.plan_count, owner_count: record.owner_count };
}

function parseExcludedByStatus(
  value: unknown,
): Record<OrderPlanBulkExcludedStatus, OrderPlanBulkStatusCount> | null {
  const record = exactRecord(value, BULK_EXCLUDED_STATUSES);
  if (!record) return null;
  const continueCount = parseStatusCount(record["계속 추적"]);
  const holdCount = parseStatusCount(record["보류"]);
  const endCount = parseStatusCount(record["종료"]);
  if (!continueCount || !holdCount || !endCount) return null;
  return { "계속 추적": continueCount, "보류": holdCount, "종료": endCount };
}

function parsePreviewItem(value: unknown): OrderPlanBulkPreviewItem | null {
  const record = exactRecord(value, PREVIEW_ITEM_KEYS);
  if (!record || !positiveId(record.order_plan_id)) return null;
  const opportunityId = nullablePositiveId(record.opportunity_id);
  const trackingStatus = nullableTrackingStatus(record.tracking_status);
  const code = nullableFailureCode(record.code);
  if (opportunityId === undefined || trackingStatus === undefined || code === undefined) return null;
  let eligibility: OrderPlanBulkPreviewItem["eligibility"] | undefined;
  for (const candidate of BULK_ELIGIBILITIES) {
    if (record.eligibility === candidate) {
      eligibility = candidate;
      break;
    }
  }
  if (!eligibility) return null;
  if (eligibility === "eligible" && (opportunityId === null || trackingStatus !== "미선택" || code !== null)) return null;
  if (
    eligibility === "excluded"
    && (opportunityId === null
      || trackingStatus === null
      || !BULK_EXCLUDED_STATUSES.some((status) => status === trackingStatus)
      || code !== null)
  ) return null;
  if (eligibility === "failed" && code === null) return null;
  return {
    order_plan_id: record.order_plan_id,
    opportunity_id: opportunityId,
    tracking_status: trackingStatus,
    eligibility,
    code,
  };
}

function parsePreviewResponse(
  value: unknown,
  expectedIds: readonly number[],
): OrderPlanBulkPreviewResponse {
  const record = exactRecord(value, PREVIEW_RESPONSE_KEYS);
  if (!record || record.schema_version !== "order-plan-bulk-preview-response.v1") {
    throw new OrderPlanBulkTrackingResultUnconfirmedError();
  }
  const excludedByStatus = parseExcludedByStatus(record.excluded_by_status);
  if (!excludedByStatus || !strictInteger(record.selected_plan_count, 1)
      || !strictInteger(record.unique_owner_count)
      || !strictInteger(record.eligible_plan_count)
      || !strictInteger(record.eligible_owner_count)
      || !strictInteger(record.failure_plan_count)
      || !Array.isArray(record.items)
      || record.items.length !== expectedIds.length) {
    throw new OrderPlanBulkTrackingResultUnconfirmedError();
  }
  const items: OrderPlanBulkPreviewItem[] = [];
  for (let index = 0; index < record.items.length; index += 1) {
    const item = parsePreviewItem(record.items[index]);
    if (!item || item.order_plan_id !== expectedIds[index]) {
      throw new OrderPlanBulkTrackingResultUnconfirmedError();
    }
    items.push(item);
  }
  if (
    record.selected_plan_count !== expectedIds.length
    || new Set(items.map((item) => item.order_plan_id)).size !== expectedIds.length
  ) {
    throw new OrderPlanBulkTrackingResultUnconfirmedError();
  }
  const eligible = items.filter((item) => item.eligibility === "eligible");
  const excluded = items.filter((item) => item.eligibility === "excluded");
  const failed = items.filter((item) => item.eligibility === "failed");
  const ownerIds = new Set(items.flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id]));
  const eligibleOwnerIds = new Set(
    eligible.flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id]),
  );
  if (
    record.unique_owner_count !== ownerIds.size
    || record.eligible_plan_count !== eligible.length
    || record.eligible_owner_count !== eligibleOwnerIds.size
    || record.failure_plan_count !== failed.length
  ) {
    throw new OrderPlanBulkTrackingResultUnconfirmedError();
  }
  const ownerEligibility = new Map<number, string>();
  for (const item of items) {
    if (item.opportunity_id === null) continue;
    const resultKey = [item.eligibility, item.tracking_status, item.code].join("|");
    const previous = ownerEligibility.get(item.opportunity_id);
    if (previous !== undefined && previous !== resultKey) {
      throw new OrderPlanBulkTrackingResultUnconfirmedError();
    }
    ownerEligibility.set(item.opportunity_id, resultKey);
  }
  for (const status of BULK_EXCLUDED_STATUSES) {
    const matching = excluded.filter((item) => item.tracking_status === status);
    const count = excludedByStatus[status];
    if (
      count.plan_count !== matching.length
      || count.owner_count !== new Set(
        matching.flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id]),
      ).size
    ) {
      throw new OrderPlanBulkTrackingResultUnconfirmedError();
    }
  }
  return {
    schema_version: "order-plan-bulk-preview-response.v1",
    selected_plan_count: record.selected_plan_count,
    unique_owner_count: record.unique_owner_count,
    eligible_plan_count: record.eligible_plan_count,
    eligible_owner_count: record.eligible_owner_count,
    excluded_by_status: excludedByStatus,
    failure_plan_count: record.failure_plan_count,
    items,
  };
}

/**
 * bulk-start·bulk-end 항목 공통 파서. 둘은 목표 상태(`succeededStatus`)만 다르고
 * 나머지 wire 모양·검증 규칙은 같다(ADR-0063).
 */
function parseBulkTargetItem(
  value: unknown,
  succeededStatus: OpportunityTrackingStatus,
): OrderPlanBulkStartItem | null {
  const record = exactRecord(value, START_ITEM_KEYS);
  if (!record || !positiveId(record.order_plan_id)) return null;
  const opportunityId = nullablePositiveId(record.opportunity_id);
  const status = nullableTrackingStatus(record.status_at_decision);
  const code = nullableFailureCode(record.code);
  const auditEventId = record.audit_event_id === null
    ? null
    : isUuid(record.audit_event_id) ? record.audit_event_id : undefined;
  if (opportunityId === undefined || status === undefined || code === undefined || auditEventId === undefined) return null;
  let outcome: OrderPlanBulkStartItem["outcome"] | undefined;
  for (const candidate of BULK_OUTCOMES) {
    if (record.outcome === candidate) {
      outcome = candidate;
      break;
    }
  }
  if (!outcome) return null;
  if (
    outcome === "succeeded"
    && (opportunityId === null || status !== succeededStatus || code !== null || auditEventId === null)
  ) return null;
  if (
    outcome === "excluded"
    && (opportunityId === null
      || status === null
      || !BULK_EXCLUDED_STATUSES.some((candidate) => candidate === status)
      || code !== null
      || auditEventId !== null)
  ) return null;
  if (outcome === "failed" && (code === null || auditEventId !== null)) return null;
  return {
    order_plan_id: record.order_plan_id,
    opportunity_id: opportunityId,
    outcome,
    status_at_decision: status,
    code,
    audit_event_id: auditEventId,
  };
}

function parseStartItem(value: unknown): OrderPlanBulkStartItem | null {
  return parseBulkTargetItem(value, "계속 추적");
}

function parseEndItem(value: unknown): OrderPlanBulkStartItem | null {
  return parseBulkTargetItem(value, "종료");
}

function parseSummary(value: unknown): OrderPlanBulkSummary | null {
  const record = exactRecord(value, SUMMARY_KEYS);
  if (
    !record
    || !strictInteger(record.selected_plan_count, 1)
    || !strictInteger(record.unique_owner_count)
    || !strictInteger(record.succeeded_plan_count)
    || !strictInteger(record.succeeded_owner_count)
    || !strictInteger(record.excluded_plan_count)
    || !strictInteger(record.failed_plan_count)
  ) return null;
  const excludedByStatus = parseExcludedByStatus(record.excluded_by_status);
  if (!excludedByStatus) return null;
  return {
    selected_plan_count: record.selected_plan_count,
    unique_owner_count: record.unique_owner_count,
    succeeded_plan_count: record.succeeded_plan_count,
    succeeded_owner_count: record.succeeded_owner_count,
    excluded_plan_count: record.excluded_plan_count,
    excluded_by_status: excludedByStatus,
    failed_plan_count: record.failed_plan_count,
  };
}

/**
 * Parse a v1 preview and verify that the response is for exactly the selected
 * set.  This is exported so consumers cannot accidentally bypass the wire
 * contract when supplying a custom transport.
 */
export function parseOrderPlanBulkPreviewResponse(
  value: unknown,
  requestedIds: readonly number[],
): OrderPlanBulkPreviewResponse {
  return parsePreviewResponse(value, normalizedPlanIds(requestedIds));
}

/**
 * Parse a v1 final receipt.  The expected request ID is optional for callers
 * that only have a stored receipt; the API client always supplies it.
 */
/**
 * bulk-start·bulk-end 최종 receipt 공통 검증. 스키마 버전 리터럴과 항목 파서만
 * 호출자가 주고, 나머지 원자성·집계 대조는 두 작업이 완전히 같다(ADR-0063).
 */
function parseBulkTargetResponse<S extends string>(
  value: unknown,
  requestedIds: readonly number[],
  expectedSchemaVersion: S,
  itemParser: (item: unknown) => OrderPlanBulkStartItem | null,
  expectedRequestId?: string,
): { schema_version: S; request_id: string; completed_at: string; items: OrderPlanBulkStartItem[]; summary: OrderPlanBulkSummary } {
  const expectedIds = normalizedPlanIds(requestedIds);
  const record = exactRecord(value, START_RESPONSE_KEYS);
  if (
    !record
    || record.schema_version !== expectedSchemaVersion
    || !isUuid(record.request_id)
    || (expectedRequestId !== undefined && record.request_id.toLowerCase() !== expectedRequestId.toLowerCase())
    || !isAwareTimestamp(record.completed_at)
    || !Array.isArray(record.items)
    || record.items.length !== expectedIds.length
  ) throw new OrderPlanBulkTrackingResultUnconfirmedError();
  const summary = parseSummary(record.summary);
  if (!summary) throw new OrderPlanBulkTrackingResultUnconfirmedError();
  const items: OrderPlanBulkStartItem[] = [];
  for (let index = 0; index < record.items.length; index += 1) {
    const item = itemParser(record.items[index]);
    if (!item || item.order_plan_id !== expectedIds[index]) {
      throw new OrderPlanBulkTrackingResultUnconfirmedError();
    }
    items.push(item);
  }
  const succeeded = items.filter((item) => item.outcome === "succeeded");
  const excluded = items.filter((item) => item.outcome === "excluded");
  const failed = items.filter((item) => item.outcome === "failed");
  const ownerIds = new Set(items.flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id]));
  const succeededOwnerIds = new Set(
    succeeded.flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id]),
  );
  if (
    summary.selected_plan_count !== expectedIds.length
    || new Set(items.map((item) => item.order_plan_id)).size !== expectedIds.length
    || summary.succeeded_plan_count !== succeeded.length
    || summary.excluded_plan_count !== excluded.length
    || summary.failed_plan_count !== failed.length
    || summary.unique_owner_count !== ownerIds.size
    || summary.succeeded_owner_count !== succeededOwnerIds.size
    || summary.selected_plan_count
      !== summary.succeeded_plan_count + summary.excluded_plan_count + summary.failed_plan_count
  ) throw new OrderPlanBulkTrackingResultUnconfirmedError();
  const ownerResults = new Map<number, string>();
  for (const item of items) {
    if (item.opportunity_id === null) continue;
    const resultKey = [
      item.outcome,
      item.status_at_decision,
      item.code,
      item.audit_event_id,
    ].join("|");
    const previous = ownerResults.get(item.opportunity_id);
    if (previous !== undefined && previous !== resultKey) {
      throw new OrderPlanBulkTrackingResultUnconfirmedError();
    }
    ownerResults.set(item.opportunity_id, resultKey);
  }
  for (const status of BULK_EXCLUDED_STATUSES) {
    const matching = excluded.filter((item) => item.status_at_decision === status);
    const count = summary.excluded_by_status[status];
    if (
      count.plan_count !== matching.length
      || count.owner_count !== new Set(
        matching.flatMap((item) => item.opportunity_id === null ? [] : [item.opportunity_id]),
      ).size
    ) throw new OrderPlanBulkTrackingResultUnconfirmedError();
  }
  return {
    schema_version: expectedSchemaVersion,
    request_id: record.request_id,
    completed_at: record.completed_at,
    items,
    summary,
  };
}

export function parseOrderPlanBulkStartResponse(
  value: unknown,
  requestedIds: readonly number[],
  expectedRequestId?: string,
): OrderPlanBulkStartResponse {
  return parseBulkTargetResponse(
    value, requestedIds, "order-plan-bulk-start-response.v1", parseStartItem, expectedRequestId,
  );
}

/**
 * bulk-end 최종 receipt 파서(ADR-0063). 성공 항목의 목표 상태는 `종료`로 고정된다.
 */
export function parseOrderPlanBulkEndResponse(
  value: unknown,
  requestedIds: readonly number[],
  expectedRequestId?: string,
): OrderPlanBulkEndResponse {
  return parseBulkTargetResponse(
    value, requestedIds, "order-plan-bulk-end-response.v1", parseEndItem, expectedRequestId,
  );
}

async function requestBulkResponse<T>(
  path: string,
  init: RequestInit,
  parse: (body: unknown) => T,
): Promise<T> {
  let body: unknown;
  try {
    body = await request<unknown>(path, init);
  } catch (error) {
    if (error instanceof ApiError && error.status !== 0) throw error;
    throw new OrderPlanBulkTrackingResultUnconfirmedError();
  }
  try {
    return parse(body);
  } catch (error) {
    if (error instanceof OrderPlanBulkTrackingResultUnconfirmedError) throw error;
    throw new OrderPlanBulkTrackingResultUnconfirmedError();
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
 * 서버 계약은 구버전 `v1`과 예비 판단을 더한 `v2`다(docs/contracts.md). 개요 화면은
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
    && (envelope.schema === "bidops.prespec-overview.v1" || envelope.schema === "bidops.prespec-overview.v2")
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

  /** RL-01 가장 최근 브리핑. 없으면 404 `briefing_not_found`. */
  getLatestBriefing: (options?: ReadRequestOptions) => request<BriefingView>("/briefings/latest", options),

  /** RL-01 날짜별 브리핑(`YYYY-MM-DD`). 없으면 404 `briefing_not_found`, 날짜 형식 오류는 422. */
  getBriefing: (date: string, options?: ReadRequestOptions) =>
    request<BriefingView>(`/briefings/${encodeURIComponent(date)}`, options),

  /**
   * RL-01 추천 항목에 반응을 남긴다(추적 상태는 바꾸지 않는다). 되돌리기는 이전 값으로의
   * 새 PATCH다. 409 `version_conflict`(그사이 다른 사람이 반응), `idempotency_conflict`,
   * `reaction_not_allowed`(추적 변화 행)는 안정 코드로 읽는다.
   */
  reactBriefingItem: (itemId: string, payload: BriefingReactionRequest, actorName: string) =>
    request<BriefingItemView>(`/briefings/items/${encodeURIComponent(itemId)}/reaction`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify(payload),
    }),

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

  // C-2 일일 운영 계약 (docs/contracts.md "C-2 일일 운영 계약") — policy·품질
  // 게이트·일일 자동 실행 스위치·감사 표본. 발주계획 목록·실행 endpoint와
  // 같은 actor header·request_id idempotency 관례를 그대로 쓴다.
  listC2Policies: (options?: ReadRequestOptions) =>
    request<C2PolicyListResponse>("/order-plan-screening/policies", options),

  getC2Policy: (policyVersion: string, options?: ReadRequestOptions) =>
    request<C2PolicyInspectResponse>(
      `/order-plan-screening/policies/${encodeURIComponent(policyVersion)}`,
      options,
    ),

  designateC2PolicyCandidate: (payload: C2PolicyCandidateRequest, actorName: string) =>
    request<C2PolicyCandidateResponse>("/order-plan-screening/policies/candidate", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify(payload),
    }),

  activateC2Policy: (
    policyVersion: string,
    payload: C2PolicyActivateRequest,
    actorName: string,
  ) =>
    request<C2PolicyActivateResponse>(
      `/order-plan-screening/policies/${encodeURIComponent(policyVersion)}/activate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
        body: JSON.stringify(payload),
      },
    ),

  listC2QualityGates: (policyVersion: string, options?: ReadRequestOptions) =>
    request<C2QualityGateListResponse>(
      `/order-plan-screening/quality-gates${query({ policy_version: policyVersion })}`,
      options,
    ),

  getC2DailyTrigger: (options?: ReadRequestOptions) =>
    request<C2DailyTriggerStateResponse>("/order-plan-screening/daily-trigger", options),

  setC2DailyTrigger: (payload: C2DailyTriggerSetRequest, actorName: string) =>
    request<C2DailyTriggerSetResponse>("/order-plan-screening/daily-trigger", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify(payload),
    }),

  getC2AuditSample: (executionId: string, options?: ReadRequestOptions) =>
    request<C2AuditSamplePreviewResponse>(
      `/order-plan-screening/executions/${encodeURIComponent(executionId)}/audit-sample`,
      options,
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

  changePreSpecReviewExclusions: (body: PreSpecReviewExclusionRequest) =>
    request<PreSpecReviewExclusionResponse>("/pre-specs/review-exclusions", {
      method: "POST",
      // 이 헤더가 없으면 FastAPI가 본문을 JSON으로 읽지 않아 422로 거부한다(2026-09-23 운영 결함).
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  getPreSpecs: (params: PreSpecListQuery = {}, options?: ReadRequestOptions) =>
    request<PreSpecListResponse>(
      `/pre-specs${query({
        notice_pk: params.notice_pk,
        review_exclusion: params.review_exclusion,
        deadline_scope: params.deadline_scope,
        sw_only: params.sw_only === null || params.sw_only === undefined ? undefined : String(params.sw_only),
        business_division: params.business_division,
        auto_preparation_status: params.auto_preparation_status,
        origin: params.origin,
        workspace: params.workspace,
        overview_view: params.overview_view,
        grade: params.grade,
        display_grade: params.display_grade,
        tracking_decision: params.tracking_decision,
        tracking_status: params.tracking_status,
        source_run_id: params.source_run_id,
        observed_from: params.observed_from,
        observed_to: params.observed_to,
        deadline_status: params.deadline_status,
        q: params.q,
        sort: params.sort,
        limit: params.limit,
        offset: params.offset,
      })}`,
      options,
    ),

  getCompanyFit: (noticeId: number, options?: ReadRequestOptions) =>
    request<CompanyFitResponse>(`/pre-specs/${noticeId}/company-fit`, options),

  /** 이 사전규격을 target으로 하는 `후보 확인 대기` 발주계획 연결 목록(spec §4.4). */
  getPreSpecOrderPlanCandidates: (noticePk: number, options?: ReadRequestOptions) =>
    request<PreSpecOrderPlanCandidatesResponse>(`/pre-specs/${noticePk}/order-plan-candidates`, options),

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

  getNotice: (noticePk: number, options: ReadRequestOptions = {}) =>
    request<NoticeDetailResponse>(`/notices/${noticePk}`, { signal: options.signal }),

  getNoticeAttachments: (noticePk: number) =>
    request<AttachmentProcedureResponse>(`/notices/${noticePk}/attachments`),

  attachmentDownloadUrl: (attachmentId: number) =>
    `${API_PREFIX}/attachments/${attachmentId}/download`,

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
        reason: params.reason,
        hold_review: params.hold_review,
        deadline_within_days: params.deadline_within_days,
        q: params.q,
        sort: params.sort,
        limit: params.limit,
        offset: params.offset,
      })}`,
      options,
    ),

  getOpportunity: (opportunityId: number, options?: ReadRequestOptions) =>
    request<OpportunityDetailResponse>(`/opportunities/${opportunityId}`, options),

  /**
   * 사업기회 레코드의 6단계와 활동 피드(RL-02). 병합된 사업기회도 200이며
   * `merged_into_opportunity_id`로 화면이 이동한다. `before`는 서버가 준 불투명 커서다.
   */
  getOpportunityActivity: (
    opportunityId: number,
    params: OpportunityActivityQuery = {},
    options?: ReadRequestOptions,
  ) =>
    request<OpportunityActivityResponse>(
      `/opportunities/${opportunityId}/activity${query({
        kinds: params.kinds ?? undefined,
        limit: params.limit,
        before: params.before,
      })}`,
      options,
    ),

  /** 노트·다음 행동을 남긴다(append-only). 같은 `request_id`의 재전송은 저장된 결과를 돌려받는다. */
  createOpportunityNote: (
    opportunityId: number,
    payload: OpportunityNoteCreateRequest,
    actorName: string,
  ) =>
    request<OpportunityNoteView>(`/opportunities/${opportunityId}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify(payload),
    }),

  /** 다음 행동을 완료로 표시한다. 이미 완료면 서버가 그대로 200을 준다. */
  completeOpportunityNoteAction: (
    opportunityId: number,
    noteId: string,
    requestId: string,
    actorName: string,
  ) =>
    request<OpportunityNoteView>(`/opportunities/${opportunityId}/notes/${encodeURIComponent(noteId)}/done`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify({ request_id: requestId }),
    }),

  /** Preview the selected plans without creating a decision or receipt. */
  previewOrderPlanTracking: (orderPlanIds: readonly number[], options?: ReadRequestOptions) =>
    requestBulkResponse(
      "/opportunities/order-plan-tracking/preview",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          schema_version: "order-plan-bulk-preview-request.v1",
          order_plan_ids: orderPlanIds,
        }),
        signal: options?.signal,
      },
      (body) => parseOrderPlanBulkPreviewResponse(body, orderPlanIds),
    ),

  /** Start tracking and return the server's durable, replayable receipt. */
  startOrderPlanTracking: (payload: OrderPlanBulkStartRequest, actorName: string) =>
    requestBulkResponse(
      "/opportunities/order-plan-tracking/bulk-start",
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
        body: JSON.stringify(payload),
      },
      (body) => parseOrderPlanBulkStartResponse(body, payload.order_plan_ids, payload.request_id),
    ),

  /**
   * 일괄 추적을 종료하고 서버의 durable·replayable receipt를 돌려준다(ADR-0063).
   * 한 요청 상한은 `ORDER_PLAN_BULK_END_MAX_SELECTION`이며 초과는 서버가 422로 거부한다.
   */
  endOrderPlanTracking: (payload: OrderPlanBulkEndRequest, actorName: string) =>
    requestBulkResponse(
      "/opportunities/order-plan-tracking/bulk-end",
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
        body: JSON.stringify(payload),
      },
      (body) => parseOrderPlanBulkEndResponse(body, payload.order_plan_ids, payload.request_id),
    ),

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

  /**
   * 현재 재검토 신호를 확인 처리한다(spec §6.2). 추적 상태는 바꾸지 않는다.
   * 신호가 없으면 409 `recheck_signal_absent`, 근거 연결이 바뀌었으면 409
   * `recheck_signal_changed`(`details.current_link_id`)로 거절된다.
   */
  acknowledgeRecheckSignal: (
    opportunityId: number,
    payload: RecheckAcknowledgementRequest,
    actorName: string,
  ) =>
    request<OpportunityDetailResponse>(`/opportunities/${opportunityId}/recheck-acknowledgements`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...actorHeaders(actorName) },
      body: JSON.stringify(payload),
    }),

  /**
   * 수집 색인에서 사전규격·입찰공고를 동기로 찾아본다(spec §4.3). 소유
   * 발주계획·사전규격이 없으면 422 `search_source_missing`이다.
   */
  searchOpportunityRecords: (
    opportunityId: number,
    payload: OpportunitySearchRequest,
    actorName: string,
  ) =>
    request<OpportunitySearchResponse>(`/opportunities/${opportunityId}/searches`, {
      method: "POST",
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

/**
 * 같은 요청·오류 envelope 규칙을 다른 typed client(`lib/companyApi.ts`)가 다시
 * 구현하지 않도록 내보낸다. 오류는 언제나 `ApiError`(status·안전한 code)이며
 * 서버 message로 분기하지 않는다.
 */
export { request as apiRequest, query as apiQueryString, actorHeaders as apiActorHeaders };
export type { ReadRequestOptions };
