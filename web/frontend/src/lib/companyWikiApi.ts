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
  last_changed: Text;
  labels_available: boolean;
  log: WikiLog[];
}

export interface WikiLog {
  date: Text;
  kind: "ingest" | "feedback" | "init" | "other";
  text: string;
  project: Text;
  project_title: Text;
  requirement_count: number | null;
  unassigned_count: number | null;
}

export interface WikiFact { path: string; label: Text; value: Text; display_value: Text; level: Text }
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
export interface Requirement { req_id: string; name: Text }
interface TopicInfo { id: string; title: string; scope: Text }
interface WikiTopic extends TopicInfo {
  unit_count: number;
  units_without_evidence: number;
  project_count: number;
}
export interface WikiUnit {
  id: string;
  title: string;
  covers: Text;
  not: Text;
  project_count: number;
  latest_year: number | null;
  projects: {
    project: string; title: Text; client: Text; period_start: Text; period_end: Text;
    year: number | null; requirements: Requirement[];
  }[];
  no_record: { note: string; as_of: Text; source: Text }[];
}
interface ProjectDetail extends WikiProject {
  domain: string[] | Text;
  scope_lines: string[];
  work_units: { topic_id: string; topic_title: string; units: { id: string; title: string }[] }[];
  requirements: Requirement[];
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

export interface WikiMetric { group: "answer" | "diagnostic"; label: string; numerator: number; denominator: number }

interface WikiEvaluation {
  reviewed_on: string; reviewer: string; model_version: string; dataset_version: string; rubric_version: string;
  judge_version: string | null;
  cases: { id: string; question: string; expected_answer: string; answer: string; correct: boolean; reviewer_note: string;
    claims: { text: string; grounded: boolean; citations: { page: string; quote: string; supports_claim: boolean }[] }[];
    required_groups: string[][]; read_pages: string[] | null; duration_ms: number | null; judge_correct: boolean | null; tool_calls: number | null; tokens: number | null }[];
}

export const wiki = {
  quality: resource<Bundle & { status: "unmeasured" | "stale" | "reviewed"; evaluation: WikiEvaluation | null;
    metrics: WikiMetric[] }>("/quality"),
  summary: resource<WikiSummary>(""),
  profile: resource<Bundle & { sections: { key: string; label: Text; facts: WikiFact[] }[] }>("/profile"),
  portfolio: resource<Bundle & { items: WikiProject[] }>("/portfolio"),
  topics: resource<Bundle & { topics: WikiTopic[] }>("/work-units"),
  topic: (id: string) => resource<Bundle & TopicInfo & { units: WikiUnit[] }>(`/work-units/${encodeURIComponent(id)}`),
  project: (id: string) => resource<Bundle & ProjectDetail>(`/portfolio/${encodeURIComponent(id)}`),
  requirement: (project: string, id: string) => resource<Bundle & Requirement & { project: string; text: string }>(
    `/portfolio/${encodeURIComponent(project)}/requirements/${encodeURIComponent(id)}`),
  pages: resource<Bundle & { pages: WikiEntry[] }>("/pages"),
  detail: (kind: WikiKind, slug: string) =>
    resource<Bundle & WikiPage & { sources: string[]; body: string }>(
      `/pages/${kind}/${encodeURIComponent(slug)}`,
    ),
};
