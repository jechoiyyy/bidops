import type {
  BundleListResponse,
  BundleView,
  ConfirmDocumentBundlePayload,
  CreateDeepReviewAttemptPayload,
  CreateDeepReviewPayload,
  DeepReviewReport,
  DeepReviewView,
  DocumentStructure,
  DocumentStructurePageView,
  DocumentVersionView,
  EmptyRequest,
  EvidenceView,
  FinalOpinionValue,
  FinalOpinionView,
  AttemptView,
  PatchDocumentVersionPayload,
  ReportView,
} from "./types";

const API_PREFIX = "/api";
const UTF8_ACTOR_PREFIX = "UTF-8''";
const UTF8_ACTOR_FORMAT = "utf-8-percent-v1";
const GENERAL_ERROR_MESSAGE = "요청이 실패했습니다.";
const NETWORK_ERROR_MESSAGE = "API에 연결할 수 없습니다.";

type LeanErrorBody = {
  error: {
    code: string | null;
    message: string;
  };
};

export class DeepReviewApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.name = "DeepReviewApiError";
    this.status = status;
    this.code = code;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isLeanErrorBody(value: unknown): value is LeanErrorBody {
  if (!isRecord(value) || !isRecord(value.error) || typeof value.error.message !== "string" || !("code" in value.error)) {
    return false;
  }
  return value.error.code === null || typeof value.error.code === "string";
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
  return (
    (byte >= 0x41 && byte <= 0x5a) ||
    (byte >= 0x61 && byte <= 0x7a) ||
    (byte >= 0x30 && byte <= 0x39) ||
    byte === 0x2d ||
    byte === 0x2e ||
    byte === 0x5f ||
    byte === 0x7e
  );
}

function percentEncodeUtf8(value: string): string {
  return Array.from(new TextEncoder().encode(value), (byte) => {
    if (isRfc3986Unreserved(byte)) {
      return String.fromCharCode(byte);
    }
    return `%${byte.toString(16).toUpperCase().padStart(2, "0")}`;
  }).join("");
}

/** Build the claimed-name header without changing the name's server meaning. */
export function actorHeaders(actorName: string): Record<string, string> {
  const hasNonAscii = Array.from(actorName).some((character) => (character.codePointAt(0) ?? 0) > 0x7f);
  if (!hasNonAscii) {
    return { "X-BidOps-Actor-Name": actorName };
  }
  return {
    "X-BidOps-Actor-Name": `${UTF8_ACTOR_PREFIX}${percentEncodeUtf8(actorName)}`,
    "X-BidOps-Actor-Name-Format": UTF8_ACTOR_FORMAT,
  };
}

function jsonMutationHeaders(actorName: string): Record<string, string> {
  return {
    "Content-Type": "application/json",
    ...actorHeaders(actorName),
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch {
    throw new DeepReviewApiError(0, NETWORK_ERROR_MESSAGE);
  }
  const body: unknown = await readResponseBody(response);
  if (!response.ok) {
    if (isLeanErrorBody(body)) {
      throw new DeepReviewApiError(response.status, body.error.message, body.error.code);
    }
    throw new DeepReviewApiError(response.status, GENERAL_ERROR_MESSAGE);
  }
  return body as T;
}

export function getDeepReview(id: string): Promise<DeepReviewView> {
  return request<DeepReviewView>(`/deep-reviews/${encodeURIComponent(id)}`);
}

export function getDocumentBundles(noticeId: number): Promise<BundleListResponse> {
  return request<BundleListResponse>(`/notices/${encodeURIComponent(noticeId)}/document-bundles`);
}

export function createDocumentBundle(noticeId: number, actorName: string): Promise<BundleView> {
  const payload: EmptyRequest = {};
  return request<BundleView>(`/notices/${encodeURIComponent(noticeId)}/document-bundles`, {
    method: "POST",
    headers: jsonMutationHeaders(actorName),
    body: JSON.stringify(payload),
  });
}

export function uploadDocument(
  bundleId: string,
  file: File,
  actorName: string,
  requestId: string = crypto.randomUUID(),
): Promise<DocumentVersionView> {
  const form = new FormData();
  form.append("file", file);
  form.append("request_id", requestId);
  return request<DocumentVersionView>(`/document-bundles/${encodeURIComponent(bundleId)}/documents`, {
    method: "POST",
    headers: actorHeaders(actorName),
    body: form,
  });
}

export function patchDocumentVersion(
  documentVersionId: string,
  actorName: string,
  payload: PatchDocumentVersionPayload,
): Promise<DocumentVersionView> {
  return request<DocumentVersionView>(`/document-versions/${encodeURIComponent(documentVersionId)}`, {
    method: "PATCH",
    headers: jsonMutationHeaders(actorName),
    body: JSON.stringify(payload),
  });
}

export function confirmDocumentBundle(
  bundleId: string,
  actorName: string,
  payload: ConfirmDocumentBundlePayload,
): Promise<BundleView> {
  return request<BundleView>(`/document-bundles/${encodeURIComponent(bundleId)}/confirm`, {
    method: "POST",
    headers: jsonMutationHeaders(actorName),
    body: JSON.stringify(payload),
  });
}

export function getDocumentStructure(structureId: string): Promise<DocumentStructure> {
  return request<DocumentStructure>(`/document-structures/${encodeURIComponent(structureId)}`);
}

export function getDocumentStructurePage(structureId: string, page: number): Promise<DocumentStructurePageView> {
  return request<DocumentStructurePageView>(
    `/document-structures/${encodeURIComponent(structureId)}/pages/${encodeURIComponent(String(page))}`,
  );
}

export function createDeepReview(noticeId: number, bundleId: string, actorName: string): Promise<DeepReviewView> {
  const payload: CreateDeepReviewPayload = {
    request_id: crypto.randomUUID(),
    bundle_id: bundleId,
  };
  return request<DeepReviewView>(`/notices/${encodeURIComponent(noticeId)}/deep-reviews`, {
    method: "POST",
    headers: jsonMutationHeaders(actorName),
    body: JSON.stringify(payload),
  });
}

export function createDeepReviewAttempt(
  deepReviewId: string,
  actorName: string,
  requestId: string = crypto.randomUUID(),
): Promise<AttemptView> {
  const payload: CreateDeepReviewAttemptPayload = { request_id: requestId };
  return request<AttemptView>(`/deep-reviews/${encodeURIComponent(deepReviewId)}/attempts`, {
    method: "POST",
    headers: jsonMutationHeaders(actorName),
    body: JSON.stringify(payload),
  });
}

export function getReport(id: string): Promise<ReportView> {
  return request<ReportView>(`/deep-reviews/${encodeURIComponent(id)}/report`);
}

export function getEvidence(id: string): Promise<EvidenceView> {
  return request<EvidenceView>(`/evidence/${encodeURIComponent(id)}`);
}

export function saveRevision(
  id: string,
  actorName: string,
  payload: { request_id: string; base_revision_id: string; report: DeepReviewReport; reason: string; factual_change_evidence_ids: string[] },
): Promise<ReportView> {
  return request<ReportView>(`/deep-reviews/${encodeURIComponent(id)}/report-revisions`, {
    method: "POST",
    headers: jsonMutationHeaders(actorName),
    body: JSON.stringify(payload),
  });
}

export function saveFinalOpinion(
  id: string,
  actorName: string,
  payload: { request_id: string; report_revision_id: string; validation_run_id: string; value: FinalOpinionValue; reason: string; acknowledged_validation_failure: boolean },
): Promise<FinalOpinionView> {
  return request<FinalOpinionView>(`/deep-reviews/${encodeURIComponent(id)}/final-opinions`, {
    method: "POST",
    headers: jsonMutationHeaders(actorName),
    body: JSON.stringify(payload),
  });
}
