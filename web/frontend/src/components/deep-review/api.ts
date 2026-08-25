import type { DeepReviewView, EvidenceView, ReportView, DeepReviewReport, FinalOpinionValue, FinalOpinionView } from "./types";

const API_PREFIX = "/api";

export class DeepReviewApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "DeepReviewApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch (error) {
    throw new DeepReviewApiError(0, error instanceof Error ? error.message : "API에 연결할 수 없습니다.");
  }
  const contentType = response.headers.get("content-type") ?? "";
  const body: unknown = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof body === "object" && body !== null && "error" in body
      ? String((body as { error?: { message?: string } }).error?.message ?? "요청이 실패했습니다.")
      : "요청이 실패했습니다.";
    throw new DeepReviewApiError(response.status, message);
  }
  return body as T;
}

export function getDeepReview(id: string): Promise<DeepReviewView> {
  return request<DeepReviewView>(`/deep-reviews/${encodeURIComponent(id)}`);
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
    headers: { "Content-Type": "application/json", "X-BidOps-Actor-Name": actorName },
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
    headers: { "Content-Type": "application/json", "X-BidOps-Actor-Name": actorName },
    body: JSON.stringify(payload),
  });
}
