import type {
  BidDeltaAttemptCreateRequest,
  BidDeltaComparisonCreateRequest,
  BidDeltaComparisonView,
  BidDeltaWorkspaceView,
  BidFinalDecisionCreateRequest,
  BidFinalDecisionView,
} from "./types";

const API_PREFIX = "/api";
const UTF8_ACTOR_PREFIX = "UTF-8''";
const UTF8_ACTOR_FORMAT = "utf-8-percent-v1";
const GENERAL_ERROR_MESSAGE = "요청이 실패했습니다.";
const NETWORK_ERROR_MESSAGE = "API에 연결할 수 없습니다.";

type BidDeltaErrorBody = {
  error: {
    code: string | null;
    message: string;
    details?: unknown;
  };
  request_id?: string | null;
};

export class BidDeltaApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly requestId: string | null;

  constructor(status: number, message: string, code: string | null = null, requestId: string | null = null) {
    super(message);
    this.name = "BidDeltaApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isBidDeltaErrorBody(value: unknown): value is BidDeltaErrorBody {
  if (!isRecord(value) || !isRecord(value.error)) return false;
  return typeof value.error.message === "string"
    && (value.error.code === null || typeof value.error.code === "string");
}

async function readResponseBody(response: Response): Promise<unknown> {
  try {
    const contentType = response.headers.get("content-type") ?? "";
    return contentType.includes("application/json") ? await response.json() : await response.text();
  } catch {
    return null;
  }
}

function isRfc3986Unreserved(byte: number): boolean {
  return (byte >= 0x41 && byte <= 0x5a)
    || (byte >= 0x61 && byte <= 0x7a)
    || (byte >= 0x30 && byte <= 0x39)
    || byte === 0x2d || byte === 0x2e || byte === 0x5f || byte === 0x7e;
}

function percentEncodeUtf8(value: string): string {
  return Array.from(new TextEncoder().encode(value), (byte) => {
    if (isRfc3986Unreserved(byte)) return String.fromCharCode(byte);
    return `%${byte.toString(16).toUpperCase().padStart(2, "0")}`;
  }).join("");
}

/** Claimed actor is an audit marker, never authentication or authorization. */
export function actorHeaders(actorName: string): Record<string, string> {
  const hasNonAscii = Array.from(actorName).some((character) => (character.codePointAt(0) ?? 0) > 0x7f);
  if (!hasNonAscii) return { "X-BidOps-Actor-Name": actorName };
  return {
    "X-BidOps-Actor-Name": `${UTF8_ACTOR_PREFIX}${percentEncodeUtf8(actorName)}`,
    "X-BidOps-Actor-Name-Format": UTF8_ACTOR_FORMAT,
  };
}

function jsonMutationHeaders(actorName: string): Record<string, string> {
  return { "Content-Type": "application/json", ...actorHeaders(actorName) };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch {
    throw new BidDeltaApiError(0, NETWORK_ERROR_MESSAGE);
  }

  const body = await readResponseBody(response);
  if (!response.ok) {
    if (isBidDeltaErrorBody(body)) {
      throw new BidDeltaApiError(response.status, body.error.message, body.error.code, body.request_id ?? null);
    }
    throw new BidDeltaApiError(response.status, GENERAL_ERROR_MESSAGE);
  }
  return body as T;
}

export function getBidDelta(opportunityId: number): Promise<BidDeltaWorkspaceView> {
  return request<BidDeltaWorkspaceView>(`/opportunities/${encodeURIComponent(String(opportunityId))}/bid-delta`);
}

export function getBidDeltaComparison(opportunityId: number, comparisonId: string): Promise<BidDeltaComparisonView> {
  return request<BidDeltaComparisonView>(
    `/opportunities/${encodeURIComponent(String(opportunityId))}/bid-delta/comparisons/${encodeURIComponent(comparisonId)}`,
  );
}

export function createBidDeltaComparison(
  opportunityId: number,
  actorName: string,
  payload: BidDeltaComparisonCreateRequest,
): Promise<BidDeltaComparisonView> {
  return request<BidDeltaComparisonView>(`/opportunities/${encodeURIComponent(String(opportunityId))}/bid-delta/comparisons`, {
    method: "POST",
    headers: jsonMutationHeaders(actorName),
    body: JSON.stringify(payload),
  });
}

export function retryBidDeltaAttempt(
  opportunityId: number,
  comparisonId: string,
  actorName: string,
  payload: BidDeltaAttemptCreateRequest,
): Promise<BidDeltaComparisonView> {
  return request<BidDeltaComparisonView>(
    `/opportunities/${encodeURIComponent(String(opportunityId))}/bid-delta/comparisons/${encodeURIComponent(comparisonId)}/attempts`,
    {
      method: "POST",
      headers: jsonMutationHeaders(actorName),
      body: JSON.stringify(payload),
    },
  );
}

export function saveBidFinalDecision(
  opportunityId: number,
  comparisonId: string,
  actorName: string,
  payload: BidFinalDecisionCreateRequest,
): Promise<BidFinalDecisionView> {
  return request<BidFinalDecisionView>(
    `/opportunities/${encodeURIComponent(String(opportunityId))}/bid-delta/comparisons/${encodeURIComponent(comparisonId)}/final-decisions`,
    {
      method: "POST",
      headers: jsonMutationHeaders(actorName),
      body: JSON.stringify(payload),
    },
  );
}
