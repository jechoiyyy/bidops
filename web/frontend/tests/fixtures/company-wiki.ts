import type { Page } from "@playwright/test";
import { mockApi } from "../api-mock";
import type { WikiEntry, WikiProject, WikiSummary } from "../../src/lib/companyWikiApi";

export const digest = "0123456789abcdef".repeat(4);
const counts = { pages_by_kind: { rule: 1, portfolio: 2, category: 0, glossary: 0, capability: 1 },
  portfolio_items: 3, portfolio_pages: 2, ingested_projects: 1, work_topics: 1, work_units: 2, evidence_links: 1, units_without_evidence: 1 };
export const summary: WikiSummary = { bundle_sha256: digest, counts, slug: "sample", company_name: "예시 회사",
  work_units_available: true, log: [{ date: "2026-11-22", text: "규칙을 정리했어요." }] };
const base = { updated: null, confidence: null, chars: 30 };
const pages: WikiEntry[] = [
  { ...base, kind: "rule", slug: "guide", title: "검토 규칙" },
  { ...base, kind: "portfolio", slug: "P1", title: "실적 원문" },
  { ...base, kind: "portfolio", slug: "P2", title: "두 번째 원문" },
  { ...base, kind: "capability", slug: "work-read", title: "업무별 원문" },
];
export const project: WikiProject = { id: "P1", title: "긴 한글 사업명".repeat(15), client: "unknown", period_start: "2025", period_end: null,
  type: null, role: null, has_page: true, requirement_count: 0, ingested: true, ingested_at: "2026-11-22", evidence_links: 1 };
const items = [project, { ...project, id: "P2", requirement_count: null, ingested: false, ingested_at: null, evidence_links: 0 },
  { ...project, id: "P3", requirement_count: null, ingested: false, ingested_at: null, evidence_links: 0, has_page: false }];
const facts = [
  { path: "company.name", section: "company", value: "예시 회사", level: "confirmed" },
  { path: "schema_version", section: "schema_version", value: "1", level: null },
  { path: "custom.value", section: "custom", value: "기타", level: null },
  { path: "people.lead", section: "people", value: "unknown", level: null },
  { path: "people.total", section: "people", value: null, level: "estimate" },
];
const unit = { id: "a", title: "문서 검토", covers: "요구사항", not: null, projects: [{ project: "P1", req_ids: ["REQ-1"] }], no_record: [] };
const topics = [{ id: "read", title: "문서", scope: "검토", units: [unit, { ...unit, id: "b", title: "원문 대조", not: "",
  projects: [], no_record: [{ note: "검토 기록을 확인했어요.", as_of: "2026-11-22", source: null }] }] }];

export async function mockWiki(page: Page, overrides: Record<string, object> = {}) {
  await mockApi(page);
  const routes: Record<string, object> = { "": summary, "/profile": { facts }, "/portfolio": { items },
    "/ingests": { items: [], total: 0 }, "/pages": { pages }, "/work-units": { topics },
    "/pages/rule/guide": { kind: "rule", slug: "guide", title: "검토 규칙", updated: null, confidence: null, body: "## 참고 실적\n- [[P1]]\n- [[work-read]]", sources: [] },
    "/pages/portfolio/P1": { kind: "portfolio", slug: "P1", title: "실적 원문", updated: null, confidence: null, body: "### 근거 자료\n[[guide]]\n\n<img src=x>", sources: [] }, ...overrides };
  await page.route(/\/api\/company-wiki(?:\/|$)/, route => {
    const path = new URL(route.request().url()).pathname.slice("/api/company-wiki".length);
    const response = routes[path];
    if (!response || route.request().method() !== "GET") throw new Error(`예상 밖의 요청: ${path}`);
    if ("error" in response) return route.fulfill({ status: "status" in response ? Number(response.status) : 404, json: { error: response.error } });
    return route.fulfill({ json: path === "/ingests" ? response : { bundle_sha256: digest, ...response } });
  });
}
