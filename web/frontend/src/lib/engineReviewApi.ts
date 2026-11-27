import { apiActorHeaders, apiRequest, type ReadRequestOptions } from "./api";
import type { EngineRun } from "./engineApi";

type Command = { request_id: string };
export type EngineReviewOrigin = "tracking_start" | "manual";
type RequestCommand = Command & { origin: EngineReviewOrigin };
type BatchCommand = Command & { origin: "tracking_start"; notice_ids: number[] };
type ApprovalCommand = Command & { preview_id: string; manifest_sha256: string };
type DismissalCommand = Command & { preview_id: string };
type AcknowledgmentCommand = Command & { result_id: string };

interface RequestReceipt {
  id: string;
  notice_id: number;
  opportunity_id: number;
  company_bundle_slug: string;
  origin: EngineReviewOrigin;
  requested_by: string;
  requested_at: string;
  request_id: string;
  closed_at: string | null;
  closed_reason: string | null;
  closed_by: string | null;
}

/** Metadata projected by engine_review_inputs.freeze and the engine's preview selector. */
export interface EngineReviewManifest {
  schema_version: "bidops.engine-review-manifest.v1";
  input_schema_version: string;
  notice_id: number;
  title: string;
  bundle_id: string;
  bundle_revision: number;
  primary_format: string;
  engine_version: string;
  engine_sha256: string;
  mode: "mock_reference" | "live";
  policy: string;
  strategy: string;
  model: string;
  planned_calls: number;
  remaining_calls: number;
  company_bundle_slug: string;
  company_bundle_sha256: string;
  documents: {
    document_version_id: string;
    source_sha256: string;
    structure_id: string;
    structure_sha256: string;
    version: number;
    filename: string;
    page_count: number | null;
  }[];
  sections: { id: string; heading: string; page_start: number | null; page_end: number | null }[];
  wiki_pages: string[];
  wiki_pages_skipped: string[];
  wiki_chars: number;
  valid_from: string;
}

export interface EngineReviewPreview {
  preview_id: string;
  manifest_sha256: string;
  created_at: string;
  expires_at: string;
  manifest: EngineReviewManifest;
}

interface ApprovalReceipt {
  approval_id: string;
  run_id: string;
  state: EngineRun["status"];
}

interface DismissalReceipt {
  dismissal_id: string;
  request: RequestReceipt;
}

interface AcknowledgmentReceipt {
  acknowledgment_id: string;
  result_id: string;
  request_id: string;
  acknowledged_by: string;
  acknowledged_at: string;
}

export type EngineReviewState =
  | "not_requested" | "preparing" | "blocked" | "awaiting_approval" | "queued"
  | "running" | "result_ready" | "acknowledged" | "stale";

export type EngineReviewReason =
  | "tracking_required" | "documents_pending" | "original_hwp_required" | "unsafe_document"
  | "structure_unavailable" | "company_bundle_unavailable" | "company_bundle_invalid"
  | "engine_disabled" | "engine_live_disabled" | "budget_exhausted" | "input_changed";

/** EngineRunView for wiki-scoped runs. Company-scoped callers keep their existing type. */
export interface EngineReviewResult extends Omit<EngineRun,
  "company_id" | "profile_version_id" | "profile_sha256" | "graph_version_id" | "graph_sha256"> {
  company_id: string | null;
  profile_version_id: string | null;
  profile_sha256: string | null;
  graph_version_id: string | null;
  graph_sha256: string | null;
  company_bundle_slug: string | null;
  company_bundle_sha256: string | null;
}

export interface EngineReviewView {
  state: EngineReviewState;
  next_action: "request" | "resolve_exception" | "approve" | "review_result" | null;
  reason: EngineReviewReason | null;
  request: RequestReceipt | null;
  preview: EngineReviewPreview | null;
  current_result: EngineReviewResult | null;
  review_receipt: AcknowledgmentReceipt | null;
}

interface RequestResponse {
  request: RequestReceipt;
  state: EngineReviewState;
}

export interface EngineReviewBatchResult {
  notice_id: number;
  outcome: "requested" | "already_requested" | "ineligible";
  request: RequestReceipt | null;
  reason: string | null;
}

interface BatchResponse {
  items: EngineReviewBatchResult[];
}

const path = (noticeId: number) => `/pre-specs/${noticeId}/engine-review`;

function post<T>(url: string, body: Command, actor: string) {
  return apiRequest<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...apiActorHeaders(actor) },
    body: JSON.stringify(body),
  });
}

export const engineReviewApi = {
  get: (noticeId: number, options?: ReadRequestOptions) => apiRequest<EngineReviewView>(path(noticeId), options),
  request: (noticeId: number, body: RequestCommand, actor: string) =>
    post<RequestResponse>(`${path(noticeId)}/requests`, body, actor),
  batch: (body: BatchCommand, actor: string) =>
    post<BatchResponse>("/pre-specs/engine-review/requests:batch", body, actor),
  preview: (noticeId: number, body: Command, actor: string) =>
    post<EngineReviewPreview>(`${path(noticeId)}/previews`, body, actor),
  approve: (noticeId: number, body: ApprovalCommand, actor: string) =>
    post<ApprovalReceipt>(`${path(noticeId)}/approvals`, body, actor),
  dismiss: (noticeId: number, body: DismissalCommand, actor: string) =>
    post<DismissalReceipt>(`${path(noticeId)}/dismissals`, body, actor),
  acknowledge: (noticeId: number, body: AcknowledgmentCommand, actor: string) =>
    post<AcknowledgmentReceipt>(`${path(noticeId)}/acknowledgments`, body, actor),
};
