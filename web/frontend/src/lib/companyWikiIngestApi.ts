import { queryOptions } from "@tanstack/react-query";
import { apiActorHeaders, apiRequest } from "./api";

export type IngestStatus = "queued" | "extracting" | "classifying" | "awaiting_review" |
  "approved" | "applying" | "applied" | "rejected" | "failed" | "aborted";

export interface IngestSummary {
  id: string;
  request_id: string;
  project_id: string;
  project_title: string;
  status: IngestStatus;
  quality_status: "mock_reference";
  error_code: string | null;
  source_filename: string;
  source_size_bytes: number;
  source_media_type: string;
  requirement_count: number | null;
  created_at: string;
  updated_at: string;
}

export interface IngestDetail extends IngestSummary {
  unlisted_id_count: number | null;
  unassigned_count: number | null;
  units: { id: string; title: string; count: number }[];
  assignments: { req_id: string; name: string; unit_titles: string[] }[];
  new_units: Record<string, string>[];
  classification_attempts: number;
  apply_allowed: boolean;
  wiki_sha256_before: string | null;
  wiki_sha256_after: string | null;
  backup_name: string | null;
  created_by_name: string;
  decided_by_name: string | null;
  decision_reason: string | null;
  decided_at: string | null;
  applied_at: string | null;
}

const path = "/company-wiki/ingests";
export const ingestListKey = ["wiki-ingests", "list"] as const;
export const ingestLimit = 20;

export function inProgress(run?: IngestSummary) {
  return run && ["queued", "extracting", "classifying", "approved", "applying"].includes(run.status);
}

export const ingestList = (offset: number) => queryOptions({
  queryKey: [...ingestListKey, offset],
  queryFn: ({ signal }) => apiRequest<{ items: IngestSummary[]; total: number }>(
    `${path}?limit=${ingestLimit}&offset=${offset}`, { signal }),
  retry: false,
});

export const ingestDetail = (id: string) => queryOptions({
  queryKey: ["wiki-ingests", "detail", id],
  queryFn: ({ signal }) => apiRequest<IngestDetail>(`${path}/${encodeURIComponent(id)}`, { signal }),
  refetchInterval: query => inProgress(query.state.data) ? 1500 : false,
  retry: false,
});

export function uploadIngest(project: string, file: File, actor: string, key: string) {
  const form = new FormData();
  form.append("project_id", project);
  form.append("file", file);
  return apiRequest<IngestDetail>(path, {
    method: "POST", headers: { ...apiActorHeaders(actor), "Idempotency-Key": key }, body: form,
  });
}

export function decideIngest(id: string, actor: string, reason: string | null) {
  return apiRequest<IngestDetail>(`${path}/${encodeURIComponent(id)}/${reason === null ? "approve" : "reject"}`, {
    method: "POST", headers: { ...apiActorHeaders(actor), "Content-Type": "application/json" },
    body: JSON.stringify({ expected_status: "awaiting_review", ...(reason === null ? {} : { reason }) }),
  });
}
