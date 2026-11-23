import type { Page } from "@playwright/test";
import { mockApi } from "../api-mock";
import type { WikiEntry, WikiLog, WikiProject, WikiSummary } from "../../src/lib/companyWikiApi";

export const digest = "0123456789abcdef".repeat(4);
const day = "2026-11-22";
const logBase: WikiLog = { date: day, kind: "other", text: "규칙을 정리했어요.", project: null,
  project_title: null, requirement_count: null, unassigned_count: null };
const counts = { pages_by_kind: { rule: 1, portfolio: 4, category: 0, glossary: 0, capability: 1 },
  portfolio_items: 5, portfolio_pages: 4, ingested_projects: 4, work_topics: 1, work_units: 2, evidence_links: 5, units_without_evidence: 1 };
export const summary: WikiSummary = { bundle_sha256: digest, counts, slug: "sample", company_name: "예시 회사",
  work_units_available: true, labels_available: true, last_changed: day,
  log: [logBase, { ...logBase, kind: "init" }, { ...logBase, kind: "feedback" },
    { ...logBase, kind: "ingest", project: "P2026-01", project_title: "문서 보관", requirement_count: 2, unassigned_count: 1 },
    { ...logBase, kind: "ingest", project: "P2020-01", requirement_count: 0, unassigned_count: 0 }] };
const base = { updated: null, confidence: null, chars: 30 };
export const project: WikiProject = { id: "P2026-01", title: "긴 한글 사업명".repeat(15), client: "unknown", period_start: "2026", period_end: null,
  type: null, role: "unknown", has_page: true, requirement_count: 2, ingested: true, ingested_at: day, evidence_links: 2 };
const items = [project, ...["기록 정리", "문서 등록", "예전 사업"].map((title, i) => ({
  ...project, id: `P${2025 - i}-01`, title, requirement_count: i === 0 ? 0 : null, evidence_links: 1,
})), { ...project, id: "P2022-01", title: "페이지 없는 사업", requirement_count: null,
  ingested: false, ingested_at: null, evidence_links: 0, has_page: false }];
const pages: WikiEntry[] = [
  { ...base, kind: "rule", slug: "guide", title: "검토 규칙" },
  ...items.filter(item => item.has_page).map(item => ({ ...base, kind: "portfolio" as const, slug: item.id, title: "실적 원문" })),
  { ...base, kind: "capability", slug: "work-read", title: "업무별 원문" },
];
const sections = [
  { key: "company", label: "회사", facts: [
    { path: "company.name", label: "회사명", value: "예시 회사", display_value: "예시 회사", level: "confirmed" },
    { path: "company.count", label: "등록 건수", value: "0", display_value: "0건", level: "public" }] },
  { key: "people", label: "인력", facts: [
    { path: "people.lead", label: null, value: "unknown", display_value: "unknown", level: null },
    { path: "people.total", label: null, value: null, display_value: null, level: "estimate" }] },
  { key: "custom", label: null, facts: [{ path: "custom.value", label: null, value: "", display_value: "", level: null }] },
];
const requirements = [{ req_id: "REQ-1", name: "문서 분류" }, { req_id: "REQ-2", name: "문서 검색" }];
const projects = items.slice(0, 4).map((item, i) => ({
  project: item.id, title: item.title, client: item.client, year: 2026 - i, period_start: item.period_start, period_end: item.period_end,
  requirements: i ? [{ req_id: "ALT-" + i, name: null }] : requirements,
}));
const read = { id: "read", title: "문서", scope: "검토" };
const topics = [{ ...read, unit_count: 2, project_count: 4, units_without_evidence: 1 }];
const units = [{ id: "a", title: "문서 검토", covers: "요구사항", not: null, projects, project_count: 4, latest_year: 2026, no_record: [] },
  { id: "b", title: "원문 대조", covers: null, not: "", projects: [], project_count: 0, latest_year: null,
    no_record: [{ note: "검토 기록을 확인했어요.", as_of: day, source: null }] }];

export const projectDetail = { ...project, scope_lines: ["문서 목록을 관리해요."], domain: null,
  work_units: [{ topic_id: "read", topic_title: "문서", units: [{ id: "a", title: "문서 검토" }] }], requirements };

export async function mockWiki(page: Page, overrides: Record<string, object> = {}) {
  await mockApi(page);
  const routes: Record<string, object> = { "": summary, "/profile": { sections }, "/portfolio": { items },
    "/ingests": { items: [], total: 0 }, "/pages": { pages }, "/work-units": { topics }, "/work-units/read": { ...read, units },
    ["/portfolio/" + project.id]: projectDetail,
    [`/portfolio/${project.id}/requirements/REQ-1`]: { project: project.id, ...requirements[0], text: "문서 분류 원문이에요." },
    [`/portfolio/${project.id}/requirements/REQ-2`]: { status: 404, error: { code: "company_wiki_requirement_not_found" } },
    "/pages/rule/guide": { kind: "rule", slug: "guide", title: "검토 규칙", updated: null, confidence: null, body: `## 참고 실적\n- [[${project.id}]]\n- [[work-read]]`, sources: [] },
    ["/pages/portfolio/" + project.id]: { kind: "portfolio", slug: project.id, title: "실적 원문", updated: null, confidence: null, body: "### 근거 자료\n[[guide]]\n\n<img src=x>", sources: [] }, ...overrides };
  await page.route(/\/api\/company-wiki(?:\/|$)/, route => {
    const path = new URL(route.request().url()).pathname.slice("/api/company-wiki".length);
    const response = routes[path];
    if (!response || route.request().method() !== "GET") throw new Error(`예상 밖의 요청: ${path}`);
    if ("error" in response) return route.fulfill({ status: "status" in response ? Number(response.status) : 404, json: { error: response.error } });
    return route.fulfill({ json: path === "/ingests" ? response : { bundle_sha256: digest, ...response } });
  });
}
