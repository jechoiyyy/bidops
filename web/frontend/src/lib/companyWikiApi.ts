import { queryOptions } from "@tanstack/react-query";
import { apiRequest } from "./api";

export type WikiKind = "category" | "capability" | "portfolio" | "rule" | "glossary";
type Text = string | null;
interface Bundle { bundle_sha256: string }

export interface WikiSummary extends Bundle {
  slug: string;
  company_name: Text;
  work_units_available: boolean;
  counts: {
    pages_by_kind: Record<WikiKind, number>;
    portfolio_items: number;
    portfolio_pages: number;
    ingested_projects: number | null;
    work_topics: number | null;
    work_units: number | null;
    evidence_links: number | null;
    units_without_evidence: number | null;
  };
  log: { date: string; text: string }[];
}

export interface WikiFact { path: string; section: string; value: Text; level: Text }
export interface WikiProject {
  id: string;
  title: Text;
  client: Text;
  period_start: Text;
  period_end: Text;
  type: Text;
  role: Text;
  has_page: boolean;
  requirement_count: number | null;
  ingested: boolean | null;
  ingested_at: Text;
  evidence_links: number | null;
}
interface WikiTopic {
  id: string;
  title: string;
  scope: Text;
  units: {
    id: string;
    title: string;
    covers: Text;
    not: Text;
    projects: { project: string; req_ids: string[] }[];
    no_record: { note: string; as_of: Text; source: Text }[];
  }[];
}
interface WikiPage {
  kind: WikiKind;
  slug: string;
  title: string;
  updated: Text;
  confidence: Text;
}
export interface WikiEntry extends WikiPage { chars: number }

function resource<T extends Bundle>(path: string) {
  return queryOptions({
    queryKey: ["company-wiki", path],
    queryFn: ({ signal }) => apiRequest<T>(`/company-wiki${path}`, { signal }),
    retry: false,
  });
}

export const wiki = {
  summary: resource<WikiSummary>(""),
  profile: resource<Bundle & { facts: WikiFact[] }>("/profile"),
  portfolio: resource<Bundle & { items: WikiProject[] }>("/portfolio"),
  topics: resource<Bundle & { topics: WikiTopic[] }>("/work-units"),
  pages: resource<Bundle & { pages: WikiEntry[] }>("/pages"),
  detail: (kind: WikiKind, slug: string) =>
    resource<Bundle & WikiPage & { sources: string[]; body: string }>(
      `/pages/${kind}/${encodeURIComponent(slug)}`,
    ),
};
