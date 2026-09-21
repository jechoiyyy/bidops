import { expect, test, type Page } from "@playwright/test";
import {
  mockApi,
  inheritedPreSpecOpportunity,
  overviewCompletedEnvelope,
  overviewCompletedRunFixture,
  overviewEnvelopeFixture,
  overviewFallbackQueuedRunFixture,
} from "./api-mock";
import { mkdir, writeFile } from "node:fs/promises";
import { nextActionOf } from "../src/lib/preSpecNextAction";
import type {
  OpportunityDetailResponse,
  OpportunityLinkView,
  PreSpecDisplayAssessment,
  PreSpecListItem,
  PreSpecOrderPlanCandidatesResponse,
} from "../src/lib/types";

const FIXED_TIME = new Date("2026-08-31T09:00:00+09:00");

function displayAssessment(
  grade: PreSpecDisplayAssessment["grade"],
  source: PreSpecDisplayAssessment["source"],
  latestRunStatus: PreSpecDisplayAssessment["latest_run_status"],
): PreSpecDisplayAssessment {
  return {
    grade,
    status: grade === null ? "none" : "graded",
    source,
    basis_run_id: null,
    assessed_at: null,
    quality_status: null,
    reason_codes: [],
    axes: [],
    verification_items: [],
    semantic_status: null,
    semantic_scope: [],
    latest_run_status: latestRunStatus,
  };
}

async function captureRecord(page: Page, name: string) {
  const directory = process.env.PS_RECORD_CAPTURE_DIR;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${directory}/${name}.png` });
  if (name === "normal-1440") {
    const html = await page.evaluate(async () => {
      const copy = document.documentElement.cloneNode(true) as HTMLElement;
      copy.querySelectorAll("script, link[rel=modulepreload]").forEach(node => node.remove());
      for (const link of copy.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')) {
        const style = document.createElement("style");
        style.textContent = await fetch(link.href).then(response => response.text());
        link.replaceWith(style);
      }
      return "<!doctype html>" + copy.outerHTML;
    });
    await writeFile(`${directory}/record-preview.html`, html);
  }
}

const trackingException = {
  notice_pk: 991,
  pre_spec_no: "PRE-991",
  title: "추적 예외 데이터 플랫폼 사전규격",
  agency: "테스트 조달기관",
  published_at: "2026-08-30T00:00:00Z",
  deadline_at: "2026-09-02T00:00:00Z",
  budget: 510_000_000,
  sw_business_status: "N",
  business_division: "기술용역",
  origin: "추적",
  opportunity_id: 77,
  tracking_status: "계속 추적",
  kept_by_tracking: true,
  document: { attachments: 6, "완료": 2, "대기": 1, "진행": 0, "차단": 2, "실패": 1 },
  overview_review_status: "needs_human_review",
  grade: "우선 검토",
  grade_source: "screening_judgment",
  display_assessment: {
    grade: "우선 검토",
    status: "graded",
    source: "preliminary_assessment",
    basis_run_id: "overview-assessment-run-991",
    assessed_at: "2026-08-30T01:00:00Z",
    quality_status: "unmeasured_reference",
    reason_codes: [],
    axes: [{
      axis: "public_si_integration",
      relation: "direct",
      reason: "통합관리 시스템 구축이 계약의 핵심 과업입니다.",
      claim_refs: ["claim-1"],
      company_refs: [],
    }],
    verification_items: ["사업 범위의 운영 이관 조건 확인"],
    semantic_status: "not_run",
    semantic_scope: [],
    latest_run_status: "completed",
  } satisfies PreSpecDisplayAssessment,
  auto_preparation_status: "waiting_attachments",
  auto_preparation_reason: "awaiting_fetch",
  latest_deep_review_id: null,
  first_observed_at: "2026-08-29T00:00:00Z",
  last_observed_at: "2026-08-30T00:00:00Z",
  next_action: "confirm_overview",
};

test("다음 행동은 사람 확인과 차단을 먼저 읽고 추적·실행·마감을 구분한다", () => {
  const base: PreSpecListItem = {
    ...trackingException,
    origin: "추적", tracking_status: "계속 추적",
    grade: "우선 검토", grade_source: "screening_judgment",
    overview_review_status: null, auto_preparation_status: "not_applicable",
    auto_preparation_reason: null, deadline_at: null,
  };
  const cases: [Partial<PreSpecListItem>, string][] = [
    [{ overview_review_status: "needs_human_review", auto_preparation_status: "blocked" }, "사람 확인"],
    [{ overview_review_status: "failed", auto_preparation_status: "blocked" }, "개요 실행 실패·취소 확인"],
    [{ overview_review_status: "cancelled" }, "개요 실행 실패·취소 확인"],
    [{ auto_preparation_status: "blocked", auto_preparation_reason: "unknown_safe_code", origin: "신규", tracking_status: "미선택" }, "문서 차단 사유 확인 · unknown_safe_code"],
    [{ origin: "신규", tracking_status: null, auto_preparation_status: "deep_review_ready_for_click" }, "추적 결정하기"],
    [{ origin: "신규", tracking_status: "미선택" }, "추적 결정하기"],
    [{ tracking_status: "보류", auto_preparation_status: "deep_review_ready_for_click" }, "사업 추적에서 상태 확인"],
    [{ tracking_status: "종료", auto_preparation_status: "deep_review_started" }, "사업 추적에서 상태 확인"],
    [{ auto_preparation_status: "deep_review_ready_for_click" }, "심층 검토 시작 승인"],
    [{ auto_preparation_status: "deep_review_started" }, "심층 검토 진행 확인"],
    [{ auto_preparation_status: "waiting_attachments" }, "문서 준비·개요 진행 중"],
    [{ auto_preparation_status: "bundle_draft" }, "문서 준비·개요 진행 중"],
    [{ auto_preparation_status: "overview_running" }, "문서 준비·개요 진행 중"],
    [{ deadline_at: "2000-01-01T00:00:00Z", overview_review_status: "completed" }, "의견등록 마감 경과 · 본공고 여부는 상세에서 확인"],
    [{ deadline_at: null, overview_review_status: "completed" }, "개요 결과 확인"],
    [{ deadline_at: "invalid-date", overview_review_status: "completed" }, "개요 결과 확인"],
    [{ origin: null, tracking_status: null }, "현재 상태 확인"],
    [{ auto_preparation_status: "bundle_ready" }, "현재 상태 확인"],
  ];
  for (const [patch, expected] of cases) expect(nextActionOf({ ...base, ...patch })).toBe(expected);
});

const newPreSpec = {
  notice_pk: 992,
  pre_spec_no: "PRE-992",
  title: "신규 행정 서비스 사전규격",
  agency: "신규 발주기관",
  published_at: "2026-08-31T00:00:00Z",
  deadline_at: "2026-09-07T00:00:00Z",
  budget: null,
  sw_business_status: "Y",
  business_division: "일반용역",
  origin: "신규",
  opportunity_id: 78,
  tracking_status: "미선택",
  kept_by_tracking: false,
  document: { attachments: 1, "완료": 1, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
  overview_review_status: "failed",
  grade: "검토 권장",
  grade_source: "human_review",
  display_assessment: displayAssessment("검토 권장", "human_review", "failed"),
  auto_preparation_status: "blocked",
  auto_preparation_reason: "processing_failed",
  latest_deep_review_id: null,
  first_observed_at: "2026-08-30T00:00:00Z",
  last_observed_at: "2026-08-30T00:00:00Z",
  next_action: null,
};

const allOnlyPreSpec = {
  notice_pk: 993,
  pre_spec_no: "PRE-993",
  title: "전체 보기 전용 사전규격",
  agency: "전체 발주기관",
  published_at: "2026-08-29T00:00:00Z",
  deadline_at: null,
  budget: null,
  sw_business_status: null,
  business_division: "기술용역",
  origin: null,
  opportunity_id: null,
  tracking_status: null,
  kept_by_tracking: false,
  document: { attachments: 0, "완료": 0, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
  // notice에 prespec_overview_review 행이 아직 없다(개요 검토 미시작). 10값
  // 중 어느 것도 아니며, awaiting_document로 접어 넣지 않는다.
  overview_review_status: null,
  // 판정도 사람 정정도 없다. `판정 없음`이며 다섯 번째 등급이 아니다.
  grade: null,
  grade_source: null,
  display_assessment: displayAssessment(null, "none", null),
  auto_preparation_status: "not_applicable",
  auto_preparation_reason: null,
  latest_deep_review_id: null,
  first_observed_at: "2026-08-31T00:00:00Z",
  last_observed_at: "2026-08-31T00:00:00Z",
  next_action: null,
};

// 사업기회에 연결돼 있지만 서버가 준 추적 상태가 `null`인 건. 사람이 고른
// `미선택`과 다르며 화면은 `미확인`으로 남겨야 한다.
const unknownTrackingPreSpec = {
  ...newPreSpec,
  notice_pk: 994,
  pre_spec_no: "PRE-994",
  title: "추적 상태 미확인 사전규격",
  agency: "미확인 발주기관",
  opportunity_id: 79,
  tracking_status: null,
  overview_review_status: "completed",
  grade: null,
  grade_source: null,
  display_assessment: displayAssessment(null, "none", "completed"),
  budget: 0,
};

const ALL_OVERVIEW_STATUSES: (string | null)[] = [
  "awaiting_document",
  "awaiting_structure",
  "preparing",
  "awaiting_model",
  "queued",
  "running",
  "needs_human_review",
  "completed",
  "failed",
  "cancelled",
  null,
];

function overviewStatusCounts(items: readonly { overview_review_status: string | null }[]) {
  return ALL_OVERVIEW_STATUSES.map((status) => ({
    status,
    count: items.filter((item) => item.overview_review_status === status).length,
  }));
}

function localPreSpecWorkspace(item: { overview_review_status: string | null; auto_preparation_status: string; origin: string | null; tracking_status: string | null }, workspace: string | null): boolean {
  if (!workspace || workspace === "all") return true;
  if (workspace === "tracking") return item.tracking_status === "계속 추적" || item.tracking_status === "보류";
  if (workspace === "recent") return true;
  return item.overview_review_status === "needs_human_review"
    || item.auto_preparation_status === "deep_review_ready_for_click"
    || (item.overview_review_status === "completed" && item.origin === "신규" && (item.tracking_status === null || item.tracking_status === "미선택"));
}

function localPreSpecView(item: { overview_review_status: string | null }, view: string | null): boolean {
  if (!view || view === "all") return true;
  if (view === "attention") return item.overview_review_status === "needs_human_review";
  if (view === "pending") return ["awaiting_document", "awaiting_structure", "preparing", "awaiting_model", "queued", "running"].includes(item.overview_review_status ?? "");
  if (view === "not_started") return item.overview_review_status === null;
  return item.overview_review_status === view;
}

function localPreSpecMatches(
  item: typeof trackingException,
  search: URLSearchParams,
  includeWorkspace = true,
): boolean {
  if (includeWorkspace && !localPreSpecWorkspace(item, search.get("workspace"))) return false;
  if (!localPreSpecView(item, search.get("overview_view"))) return false;
  const grade = search.get("display_grade");
  if (grade && (
    grade === "판단 보류"
      ? item.display_assessment.status !== "held"
      : grade === "판정 없음"
        ? item.display_assessment.status !== "none"
        : item.display_assessment.grade !== grade
  )) return false;
  if (search.get("tracking_decision") === "pending" && !(item.origin === "신규" && (item.tracking_status === null || item.tracking_status === "미선택"))) return false;
  if (search.get("tracking_status") && item.tracking_status !== search.get("tracking_status")) return false;
  if (search.get("deadline_status")) {
    const status = item.deadline_at === null ? "unknown" : Date.parse(item.deadline_at) < Date.now() ? "passed" : "open";
    if (status !== search.get("deadline_status")) return false;
  }
  if (search.get("source_run_id")) {
    const sourceByNotice: Record<number, string> = { 991: "run-a", 992: "run-b", 993: "run-c", 994: "run-b" };
    if (sourceByNotice[item.notice_pk] !== search.get("source_run_id")) return false;
  }
  const from = search.get("observed_from");
  const to = search.get("observed_to");
  if (from && (item.last_observed_at ?? "") < from) return false;
  if (to && (item.first_observed_at ?? "") > `${to}T23:59:59Z`) return false;
  return true;
}

const notice991 = {
  id: 991,
  notice_key: "pre-spec:991",
  run_id: "source-run-not-used-for-routing",
  title: trackingException.title,
  agency: trackingException.agency,
  published_at: trackingException.published_at,
  deadline_at: trackingException.deadline_at,
  estimated_price: null,
  sample_role: null,
  sample_stratum: null,
  collection_bucket: null,
  grade: null,
  readiness: null,
  focus: null,
  attachment_count: 6,
  attachment_status: "g2b",
  bid_no: null,
  bid_ord: null,
  source_type: "pre_spec",
  budget: trackingException.budget,
  method: null,
  url: "https://example.invalid/pre-specs/991",
  timezone: "Asia/Seoul",
  procurement_class: null,
  region_limit: null,
  lifecycle: { pre_spec_no: "PRE-991" },
  qualification_flags: { sw_business_status: "N" },
  focus_matches: [],
  performance_matches: [],
  performance_top_score: null,
  candidate_sources: [],
  judgment: null,
  attachments: [],
  reviews: [],
};

interface PreSpecTrace {
  listQueries: URLSearchParams[];
  noticeGets: number[];
  overviewGets: number[];
  trackingPatches: Array<{ opportunityId: number; trackingStatus: string; reason: string }>;
}

interface PreSpecMockOptions {
  emptyDefault?: boolean;
  trackingSavedActor?: string;
  /** 개요 검토 envelope(`bidops.prespec-overview.v1`). 없으면 run이 없는 공고다. */
  overviewBody?: unknown;
}

async function fillRecordReason(page: Page, text: string) {
  await page.getByRole("combobox", { name: "선택 사유" }).click();
  await page.getByRole("option", { name: "기타 · 직접 입력" }).click();
  await page.getByRole("textbox", { name: "선택 사유 직접 입력 (필수)" }).fill(text);
}

async function mockPreSpecs(page: Page, options: PreSpecMockOptions = {}): Promise<PreSpecTrace> {
  const trace: PreSpecTrace = { listQueries: [], noticeGets: [], overviewGets: [], trackingPatches: [] };
  const trackingByOpportunity = new Map<number, string>([
    [trackingException.opportunity_id, trackingException.tracking_status],
    [newPreSpec.opportunity_id, newPreSpec.tracking_status],
  ]);

  await page.route("**/api/pre-specs**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const overviewMatch = url.pathname.match(/^\/api\/pre-specs\/(\d+)\/overview$/);

    if (overviewMatch && request.method() === "GET") {
      const id = Number(overviewMatch[1]);
      trace.overviewGets.push(id);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(options.overviewBody ?? overviewEnvelopeFixture(id, null)),
      });
      return;
    }

    if (url.pathname === "/api/pre-specs" && request.method() === "GET") {
      trace.listQueries.push(new URLSearchParams(url.search));
      const noticePk = url.searchParams.has("notice_pk") ? Number(url.searchParams.get("notice_pk")) : null;
      const swOnly = url.searchParams.get("sw_only") !== "false";
      const allItems = [
        { ...trackingException, tracking_status: trackingByOpportunity.get(trackingException.opportunity_id) },
        { ...newPreSpec, tracking_status: trackingByOpportunity.get(newPreSpec.opportunity_id) },
        unknownTrackingPreSpec,
        allOnlyPreSpec,
      ];
      const candidates = noticePk !== null
        ? allItems.filter((item) => item.notice_pk === noticePk)
        : swOnly
          ? options.emptyDefault ? [] : allItems.slice(0, 3)
          : allItems;
      const items = candidates.filter((item) => localPreSpecMatches(item, url.searchParams));
      const unscoped = candidates.filter((item) => localPreSpecMatches(item, url.searchParams, false));
      const workspaceCounts = {
        actionable: unscoped.filter((item) => localPreSpecWorkspace(item, "actionable")).length,
        recent: unscoped.filter((item) => localPreSpecWorkspace(item, "recent")).length,
        tracking: unscoped.filter((item) => localPreSpecWorkspace(item, "tracking")).length,
        all: unscoped.length,
      };
      const statusSearch = new URLSearchParams(url.searchParams);
      statusSearch.delete("overview_view");
      const statusItems = candidates.filter((item) => localPreSpecMatches(item, statusSearch));
      const limit = Number(url.searchParams.get("limit") ?? 200);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: items.slice(offset, offset + limit),
          total: items.length,
          limit,
          offset,
          overview_status_counts: overviewStatusCounts(statusItems),
          workspace_counts: workspaceCounts,
          // 계약상 항상 있는 집계다. 이 표본의 마감은 고정 브라우저 시계 기준으로
          // 전부 미래이거나 미확인이라 구간 적용 전 actionable이 전부 `current`다.
          deadline_scope_counts: { current: workspaceCounts.actionable, passed: 0 },
        }),
      });
      return;
    }

    await route.fallback();
  });

  await page.route("**/api/opportunities/77", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({ json: { ...inheritedPreSpecOpportunity, id: 77 } });
  });
  await page.route("**/api/opportunities/*/tracking-status", async (route) => {
    const request = route.request();
    const match = new URL(request.url()).pathname.match(/^\/api\/opportunities\/(\d+)\/tracking-status$/);
    if (request.method() !== "PATCH" || !match) {
      await route.fallback();
      return;
    }
    const body = request.postDataJSON() as { tracking_status?: string; reason?: string };
    const opportunityId = Number(match[1]);
    if (!trackingByOpportunity.has(opportunityId) || !body.tracking_status || !body.reason?.trim()) {
      await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "tracking_reason_required" }) });
      return;
    }
    trackingByOpportunity.set(opportunityId, body.tracking_status);
    trace.trackingPatches.push({
      opportunityId,
      trackingStatus: body.tracking_status,
      reason: body.reason,
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: opportunityId,
        tracking_status: body.tracking_status,
        tracking_reason: body.reason,
        tracking_selected_by: options.trackingSavedActor ?? decodeURIComponent((request.headers()["x-bidops-actor-name"] ?? "테스트 담당자").replace(/^UTF-8''/, "")),
        tracking_selected_at: "2026-09-01T00:00:00Z",
        recheck_signal: false,
        recheck_signal_at: null,
        recheck_signal_link_id: null,
        first_registered_stage: "order_plan",
        links: [],
      }),
    });
  });

  await page.route("**/api/notices/**", async (route) => {
    const request = route.request();
    const match = new URL(request.url()).pathname.match(/^\/api\/notices\/(\d+)$/);
    if (match && request.method() === "GET") {
      const id = Number(match[1]);
      trace.noticeGets.push(id);
      await route.fulfill({
        status: id === 991 || id === 992 || id === 993 ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(id === 991
          ? notice991
          // 992는 발주계획에 없던 신규 사전규격이다. 승계 건(991)과 달리 이 화면이
          // 추적 시작을 묻는 유일한 경우다.
          : id === 992
            ? { ...notice991, id: 992, notice_key: "pre-spec:992", title: newPreSpec.title, agency: newPreSpec.agency, attachment_count: 1, url: null, lifecycle: { pre_spec_no: newPreSpec.pre_spec_no }, qualification_flags: { sw_business_status: "Y" } }
            : id === 993
              ? { ...notice991, id: 993, notice_key: "pre-spec:993", title: allOnlyPreSpec.title, agency: allOnlyPreSpec.agency, attachment_count: 0, url: null, lifecycle: { pre_spec_no: allOnlyPreSpec.pre_spec_no }, qualification_flags: { sw_business_status: null } }
              : { detail: "공고 없음" }),
      });
      return;
    }
    await route.fallback();
  });

  return trace;
}

// 목록은 12열 표가 아니라 리스트 행이다(시안 PreSpecs.png). 한 건을 집는
// 자리를 한곳에 두어 행 구조가 바뀌어도 spec 전체가 같은 곳만 고치면 된다.
function preSpecRow(page: Page, title: string) {
  return page.locator('.pre-specs-list-pane [data-review-primitive="dense-list-row"]').filter({ hasText: title });
}

/** 행 선택은 제목 링크·버튼이 아닌 자리를 눌러야 상세만 바뀐다. */
async function selectPreSpecRow(page: Page, title: string) {
  await preSpecRow(page, title).locator(".pre-specs-row-meta").click();
}

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(FIXED_TIME);
  await mockApi(page);
});

test("URL 누락은 sw_only=true, 전체 보기와 기본값 복원은 서로 다른 query를 보낸다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const defaultView = page.getByRole("checkbox", { name: "SW 중심 · 추적 예외 포함" });
  await expect(defaultView).toBeChecked();
  await expect.poll(() => trace.listQueries.at(-1)?.get("sw_only")).toBe("true");
  expect(new URL(page.url()).searchParams.has("sw_only")).toBe(false);

  // React Router owns this controlled checkbox through the URL. A native
  // `uncheck()` assertion can run before the search-param render commits.
  await defaultView.click();
  await expect.poll(() => trace.listQueries.at(-1)?.get("sw_only")).toBe("false");
  await expect(defaultView).not.toBeChecked();
  expect(new URL(page.url()).searchParams.get("sw_only")).toBe("false");

  await page.getByRole("button", { name: "상세 필터", exact: true }).click();
  await page.getByRole("button", { name: "기본값으로" }).click();
  await expect(defaultView).toBeChecked();
  await expect.poll(() => trace.listQueries.at(-1)?.get("sw_only")).toBe("true");
  expect(new URL(page.url()).searchParams.has("sw_only")).toBe(false);
});

test("기본 보기 빈 상태의 전체 사전규격 보기는 sw_only=false를 명시한다", async ({ page }) => {
  const trace = await mockPreSpecs(page, { emptyDefault: true });
  await page.goto("/pre-specs");

  await expect(page.getByRole("button", { name: "전체 사전규격 보기" })).toBeVisible();
  await page.getByRole("button", { name: "전체 사전규격 보기" }).click();
  await expect.poll(() => trace.listQueries.at(-1)?.get("sw_only")).toBe("false");
  await expect(preSpecRow(page, allOnlyPreSpec.title)).toBeVisible();
});

// 행 구조: 사업명 → 기관 → 예산·발견 구분 → 개요 상태·추적 상태(사용자 정정으로
// 시안의 첫 두 줄을 맞바꿨다). native compact 크기는 사업명·기관 14.4px,
// 나머지 12.6px이며 굵은 글자는 사업명 하나뿐이다.
test("목록 행은 사업명·기관·예산·상태를 정해진 순서와 글자 크기로 보여준다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const row = preSpecRow(page, trackingException.title);
  const agency = row.locator(".pre-specs-row-agency");
  const title = row.locator(".pre-specs-row-title");
  await expect(agency).toHaveText(trackingException.agency);
  await expect(title).toHaveText(trackingException.title);

  const fontSize = (locator: ReturnType<typeof preSpecRow>) => locator
    .evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize));
  expect(await fontSize(agency)).toBe(14.4);
  expect(await fontSize(title)).toBe(14.4);
  const fontWeight = (locator: ReturnType<typeof preSpecRow>) => locator
    .evaluate((element) => Number(getComputedStyle(element).fontWeight));
  expect(await fontWeight(title)).toBeGreaterThanOrEqual(600);
  expect(await fontWeight(agency)).toBeLessThan(600);
  expect(await fontSize(row.locator(".pre-specs-row-meta"))).toBe(12.6);
  expect(await fontSize(row.locator(".pre-specs-row-state"))).toBe(12.6);
  expect(await fontSize(row.locator(".pre-specs-deadline"))).toBe(12.6);

  // 사업명이 기관보다 위에 있고, 마감은 행의 오른쪽 절반에 있다.
  const positions = await row.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const agencyBox = element.querySelector(".pre-specs-row-agency")!.getBoundingClientRect();
    const titleBox = element.querySelector(".pre-specs-row-title")!.getBoundingClientRect();
    const deadlineBox = element.querySelector(".pre-specs-deadline")!.getBoundingClientRect();
    return {
      titleAboveAgency: titleBox.top < agencyBox.top,
      deadlineOnRight: deadlineBox.left > box.left + box.width / 2,
    };
  });
  expect(positions).toEqual({ titleAboveAgency: true, deadlineOnRight: true });

  // 예산은 목록에서 억 단위로 줄이고 정확한 금액은 tooltip과 상세가 갖는다.
  const budget = row.locator(".pre-specs-row-meta span").first();
  await expect(budget).toHaveText("5.1억원");
  await expect(budget).toHaveAttribute("title", "510,000,000원");
  // 마감은 D-day와 짧은 날짜이고 정확한 일시는 tooltip에 남는다.
  await expect(row.getByLabel("D-day: D-2")).toBeVisible();
  await expect(row.locator(".pre-specs-row-deadline-at")).toHaveText("09.02");
});

test("행은 개요 상태와 추적 상태만 상태 줄에 두고 첨부 차단·실패를 숨기지 않는다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");

  const trackedRow = preSpecRow(page, trackingException.title);
  await expect(trackedRow.locator(".pre-specs-row-state")).toContainText("사람 검토 필요");
  await expect(trackedRow.locator(".pre-specs-row-state")).toContainText("계속 추적");
  await expect(trackedRow.locator(".pre-specs-row-attention")).toHaveText("첨부 차단 2 · 실패 1");
  // 추적 예외와 SW 값 없음은 짧은 글자로 남는다(강한 배지로 반복하지 않는다).
  await expect(trackedRow.locator(".pre-specs-row-meta")).toContainText("추적 예외");
  await expect(trackedRow.locator(".pre-specs-row-meta")).toContainText("SW N");

  const newRow = preSpecRow(page, newPreSpec.title);
  await expect(newRow.locator(".pre-specs-row-state")).toContainText("실패");
  await expect(newRow.locator(".pre-specs-row-state")).toContainText("미선택");
  await expect(newRow.locator(".pre-specs-row-attention")).toHaveCount(0);
});

// 상단 workspace는 누적 집합을 바꾸는 탐색 지름길이다. 숫자는 현재 workspace가
// 아니라 같은 조건에서 workspace만 바꿔 센 서버 집계다.
test("상단 workspace는 URL과 동기화되고 서버 workspace 집계를 보여준다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const views = page.locator(".pre-specs-views");
  await expect(views.getByRole("button", { name: /^검토할 항목/ })).toContainText("2");
  await expect(views.getByRole("button", { name: /^전체 이력/ })).toContainText("3");
  await views.getByRole("button", { name: /^최근 수집/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("workspace")).toBe("recent");
  await expect(preSpecRow(page, trackingException.title)).toBeVisible();
  await expect(views.getByRole("button", { name: /^전체 이력/ })).toBeVisible();

  await views.getByRole("button", { name: /^전체 이력/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("workspace")).toBe("all");
  await expect(preSpecRow(page, newPreSpec.title)).toBeVisible();
});

test("개요 상태 고급 필터는 미시작과 진행·대기를 구분한다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");

  await page.getByRole("button", { name: "상세 필터", exact: true }).click();
  const overview = page.getByRole("combobox", { name: "개요 상태" });
  await overview.click();
  await expect(page.getByRole("option", { name: "미시작", exact: true })).toBeVisible();
  await page.getByRole("option", { name: "미시작", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("overview_view")).toBe("not_started");
  await expect(page.locator(".pre-specs-list-foot")).toContainText("전체 1건");
});

// 정렬은 사업 추적과 같은 자리(상세 필터 안 Selector)로 옮겼다. 접히면 보이지
// 않으므로 지금 어떤 순서인지는 목록 머리가 늘 글자로 밝힌다.
test("workspace 기본 정렬과 수동 정렬은 URL·목록 머리에 반영된다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const listHead = page.locator(".pre-specs-list-head");
  await expect(listHead).toContainText("마감 임박순");

  await page.getByRole("button", { name: "상세 필터", exact: true }).click();
  await page.getByRole("combobox", { name: "표시 순서" }).click();
  await page.getByRole("option", { name: "게시 최신순", exact: true }).click();

  await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("published");
  await expect.poll(() => trace.listQueries.at(-1)?.get("sort")).toBe("published");
  await expect(listHead).toContainText("게시 최신순");

  // workspace 기본값(마감 임박순)으로 되돌리면 URL에서 인자가 사라진다.
  await page.getByRole("combobox", { name: "표시 순서" }).click();
  await page.getByRole("option", { name: "마감 임박순", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.has("sort")).toBe(false);
  await expect(listHead).toContainText("마감 임박순");
});

// 제목은 셸 상단바가 그리고 페이지는 같은 이름을 다시 쓰지 않는다. 페이지 상태를
// 쓰는 액션은 portal로 상단바 슬롯에 들어간다.
test("화면 제목과 표시 범위 액션은 상단바에 있고 페이지는 제목 줄을 두지 않는다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const topbar = page.locator("header.topbar");
  await expect(topbar).toHaveAttribute("data-topbar-mode", "title");
  await expect(topbar.locator("h1")).toHaveText("사전규격");
  // 페이지에 남는 것은 `aria-labelledby`가 가리킬 숨긴 제목뿐이고, 제목 줄은 없다.
  await expect(page.locator(".pre-specs-page > h2.visually-hidden#page-title")).toHaveText("사전규격");
  await expect(page.locator(".pre-specs-page-header")).toHaveCount(0);

  const scope = topbar.getByRole("button", { name: "표시 범위" });
  // 이전 페이지 헤더가 남아 있으면 같은 이름의 버튼이 두 개 보인다. 액션은
  // 상단바 portal에 하나만 있어야 한다.
  await expect(page.getByRole("button", { name: "표시 범위", exact: true })).toHaveCount(1);
  await expect(scope).toBeVisible();
  await scope.click();
  await expect(page.getByRole("dialog")).toContainText("현재 조건의 서버 전체 건수는");
});

test("사전규격 workspace가 canvas 남은 높이를 채우고 pane 안에서 스크롤한다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/pre-specs");
  // React Query와 the workspace mount asynchronously after the document shell. Wait
  // for the actual split workspace before reading geometry to avoid racing its first
  // render at a freshly loaded route.
  await expect(page.locator(".pre-specs-split-workspace")).toBeVisible();

  const metrics = await page.locator(".pre-specs-page").evaluate((pageRoot) => {
    const frame = pageRoot.querySelector<HTMLElement>(".workspace-frame");
    const filterBar = pageRoot.querySelector<HTMLElement>(".workspace-filters");
    const workspace = pageRoot.querySelector<HTMLElement>(".pre-specs-split-workspace");
    const listScroll = pageRoot.querySelector<HTMLElement>(".pre-specs-list-scroll");
    const detailScroll = pageRoot.querySelector<HTMLElement>(".pre-specs-detail-scroll");
    if (!frame || !filterBar || !workspace || !listScroll || !detailScroll) {
      throw new Error("사전규격 workspace 구조가 없습니다.");
    }
    const frameRect = frame.getBoundingClientRect();
    const workspaceRect = workspace.getBoundingClientRect();
    return {
      frameBottom: frameRect.bottom,
      pageBottom: pageRoot.getBoundingClientRect().bottom,
      workspaceBottom: workspaceRect.bottom,
      workspaceHeight: workspaceRect.height,
      filterHeight: filterBar.getBoundingClientRect().height,
      frameHeight: frameRect.height,
      listOverflowY: getComputedStyle(listScroll).overflowY,
      detailOverflowY: getComputedStyle(detailScroll).overflowY,
    };
  });

  expect(metrics.workspaceHeight).toBeGreaterThan(0);
  expect(metrics.frameHeight).toBeGreaterThan(metrics.filterHeight);
  expect(Math.abs(metrics.workspaceBottom - metrics.frameBottom)).toBeLessThanOrEqual(1);
  expect(Math.abs(metrics.frameBottom - metrics.pageBottom)).toBeLessThanOrEqual(1);
  expect(metrics.listOverflowY).toBe("auto");
  expect(metrics.detailOverflowY).toBe("auto");
});

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`목록 상세의 읽기 글자·구역 라벨·고정 action은 ${viewport.width}×${viewport.height}에서 계약을 지킨다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await mockPreSpecs(page, { overviewBody: overviewCompletedEnvelope() });
    await page.goto("/pre-specs");

    const detail = page.locator(".pre-specs-detail");
    const scroll = detail.locator(".pre-specs-detail-scroll");
    await expect(detail.locator('.pre-specs-detail-block[aria-label="사업 설명"]')).toContainText("차세대 통합 데이터 플랫폼을 구축하는 사업이다.");
    await expect(scroll.locator(".pre-specs-detail-tasks > li").first()).toBeVisible();
    await expect(scroll.locator(".pre-specs-detail-scale")).toBeVisible();

    const styles = await scroll.evaluate((element) => {
      const styleOf = (selector: string) => {
        const node = element.querySelector<HTMLElement>(selector);
        if (!node) throw new Error(`누락된 상세 요소: ${selector}`);
        const style = getComputedStyle(node);
        return {
          fontSize: Number.parseFloat(style.fontSize),
          fontWeight: Number.parseInt(style.fontWeight, 10),
        };
      };
      const detailPane = element.closest<HTMLElement>(".pre-specs-detail");
      const footer = detailPane?.querySelector<HTMLElement>(".pre-specs-detail-actions");
      const footerStyle = footer ? getComputedStyle(footer) : null;
      const rows = [...element.closest<HTMLElement>(".pre-specs-detail")!.querySelectorAll<HTMLElement>(".pre-specs-action-row")]
        .map((row) => Number.parseFloat(getComputedStyle(row).minHeight));
      const detailScrollStyle = getComputedStyle(element);
      return {
        summary: styleOf(".pre-specs-detail-summary"),
        task: styleOf(".pre-specs-detail-tasks > li"),
        fieldValue: styleOf(".pre-specs-detail-figures dd"),
        caption: styleOf(".pre-specs-detail-caption"),
        fieldLabel: styleOf(".pre-specs-detail-field-label"),
        scale: styleOf(".pre-specs-detail-scale"),
        sectionLabel: styleOf(".pre-specs-detail-section-label"),
        scaleLabel: styleOf(".pre-specs-detail-scale-label"),
        validation: styleOf(".pre-specs-detail-caption > span:last-child"),
        taskText: styleOf(".pre-specs-detail-tasks > li > span:last-child"),
        scaleText: styleOf(".pre-specs-detail-scale-text"),
        rows,
        footerDisplay: footerStyle?.display,
        detailFlexGrow: detailScrollStyle.flexGrow,
        detailMinHeight: detailScrollStyle.minHeight,
        detailOverflowY: detailScrollStyle.overflowY,
      };
    });

    expect(styles.summary.fontSize).toBe(13.5);
    expect(styles.task.fontSize).toBe(13.5);
    expect(styles.fieldValue.fontSize).toBe(13.5);
    expect(styles.caption.fontSize).toBe(11.7);
    expect(styles.fieldLabel.fontSize).toBe(11.7);
    expect(styles.scale.fontSize).toBe(11.7);
    expect(styles.sectionLabel.fontWeight).toBeGreaterThanOrEqual(700);
    expect(styles.fieldLabel.fontWeight).toBeGreaterThanOrEqual(700);
    expect(styles.scaleLabel.fontWeight).toBeGreaterThanOrEqual(700);
    expect(styles.validation.fontWeight).toBeLessThan(600);
    expect(styles.taskText.fontWeight).toBeLessThan(600);
    expect(styles.scaleText.fontWeight).toBeLessThan(600);
    expect(styles.rows).toEqual([32.4, 32.4]);
    expect(styles.footerDisplay).toBe("flex");
    expect(styles.detailFlexGrow).toBe("1");
    expect(styles.detailMinHeight).toBe("0px");
    expect(styles.detailOverflowY).toBe("auto");

    const actionLink = detail.getByRole("link", { name: "상세 페이지 열기 →", exact: true });
    await expect(actionLink).toHaveAttribute("href", /\/pre-specs\/991/);
    const linkStyle = await actionLink.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        minHeight: Number.parseFloat(style.minHeight),
        fontSize: Number.parseFloat(style.fontSize),
        fontWeight: Number.parseInt(style.fontWeight, 10),
        background: style.backgroundColor,
      };
    });
    expect(linkStyle.minHeight).toBe(32.4);
    expect(linkStyle.fontSize).toBe(12.6);
    expect(linkStyle.fontWeight).toBeGreaterThanOrEqual(600);
    expect(linkStyle.background).not.toBe("rgba(0, 0, 0, 0)");

    // 목록 도구줄의 채운 Primary와 상세 진입 링크는 같은 기본·hover 색을
    // 사용한다. 링크가 `<a>`인 것은 그대로 두고, 선택 검토는 실제로 활성화해
    // 두 조작의 스타일 계약만 비교한다.
    await page.locator(".pre-specs-row").first().getByRole("checkbox").check();
    const selectionReview = page.getByRole("button", { name: "선택 항목 검토", exact: true });
    await expect(selectionReview).toBeEnabled();
    const backgroundOf = async (locator: ReturnType<typeof page.locator>) => locator.evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(await backgroundOf(actionLink)).toBe(await backgroundOf(selectionReview));
    await actionLink.hover();
    const linkHoverBackground = await backgroundOf(actionLink);
    await selectionReview.hover();
    expect(linkHoverBackground).toBe(await backgroundOf(selectionReview));

    const footerBefore = await detail.locator(".pre-specs-detail-actions").boundingBox();
    await scroll.evaluate((element) => { element.scrollTop = element.scrollHeight; });
    await expect.poll(async () => (await detail.locator(".pre-specs-detail-actions").boundingBox())?.top)
      .toBe(footerBefore?.top);
    await expect(actionLink).toBeInViewport();
    await expect(scroll).toHaveCSS("overflow-y", "auto");
  });
}

test("예비 등급 필터는 서버 페이지 전에 적용되고 전체 건수와 일치한다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");

  await page.getByRole("button", { name: "상세 필터", exact: true }).click();
  await page.getByRole("combobox", { name: "예비 적합성 등급" }).click();
  await page.getByRole("option", { name: "검토 권장", exact: true }).click();

  await expect.poll(() => new URL(page.url()).searchParams.get("display_grade")).toBe("검토 권장");
  await expect(preSpecRow(page, newPreSpec.title)).toBeVisible();
  await expect(preSpecRow(page, trackingException.title)).toHaveCount(0);
  await expect(page.locator(".pre-specs-list-head")).toContainText("1건");
});

test("구버전 grade URL은 표시 등급 필터로 정규화한다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false&grade=검토%20권장");

  await expect.poll(() => new URL(page.url()).searchParams.get("grade")).toBeNull();
  await expect.poll(() => new URL(page.url()).searchParams.get("display_grade")).toBe("검토 권장");
  await expect(preSpecRow(page, newPreSpec.title)).toBeVisible();
  await expect(preSpecRow(page, trackingException.title)).toHaveCount(0);
});

// 시안의 목록은 행을 고르면 오른쪽 상세만 바뀐다. 사업명을 눌러도 목록을 떠나지
// 않으며, 상세 화면 진입은 상세 pane 바닥의 `상세 페이지 열기`가 소유한다.
test("사업명을 눌러도 목록에 남고 오른쪽 상세만 바뀐다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all");

  const detail = page.locator(".pre-specs-detail-pane");
  // 첫 행이 기본 선택이므로 다른 행의 사업명을 눌러 바뀌는 것을 본다.
  await expect(detail.locator(".pre-specs-detail-title")).toContainText(trackingException.title);
  await preSpecRow(page, newPreSpec.title).locator(".pre-specs-row-title").click();

  expect(new URL(page.url()).pathname).toBe("/pre-specs");
  await expect(detail.locator(".pre-specs-detail-title")).toContainText(newPreSpec.title);
  await expect(page.locator(".pre-specs-list-pane")).toBeVisible();
  // 상세 route는 이미 여러 상태를 찍는다. 목록 route는 여기 한 장이면 충분하며,
  // 다섯 번째 환경변수를 만들지 않고 같은 `PS_RECORD_CAPTURE_DIR`를 쓴다.
  await captureRecord(page, "list-1440");

  // 상세 화면으로 가는 길은 바닥의 결정 블록에 있다.
  await detail.getByRole("link", { name: "상세 페이지 열기 →" }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs/992");
});

// `null`은 사람이 고른 `미선택`이 아니다. 연결이 없는 것과도 다르다.
test("추적 상태의 미확인·미연결·미선택을 서로 다른 표시로 남긴다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");

  await expect(preSpecRow(page, unknownTrackingPreSpec.title).locator(".pre-specs-row-state"))
    .toContainText("미확인");
  await expect(preSpecRow(page, newPreSpec.title).locator(".pre-specs-row-state")).toContainText("미선택");
  await expect(preSpecRow(page, allOnlyPreSpec.title).locator(".pre-specs-row-state"))
    .toContainText("사업기회 미연결");

  // 대화상자가 아니라 바닥 고정 블록의 줄 1이 현재 추적 상태를 말한다(spec §3.3).
  await selectPreSpecRow(page, unknownTrackingPreSpec.title);
  const decision = page.locator(".pre-specs-detail-actions");
  await expect(decision).toContainText("현재 · 미확인");
  await expect(decision).not.toContainText("미선택");

  await selectPreSpecRow(page, allOnlyPreSpec.title);
  await expect(decision).toContainText("사업기회 미연결");
});

// ADR-0046 결정 6: 추적 상태를 묻는 자리는 하나다. 발주계획에서 승계한 건은 이 화면이
// 다시 묻지 않고 승계 사실만 밝힌다 — 인라인 폼 자리에 현재 추적 상태 블록이 온다.
test("발주계획에서 승계한 건은 폼 대신 현재 추적 상태를 보여 주고 다시 묻지 않는다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs");

  await selectPreSpecRow(page, trackingException.title);

  const decision = page.locator(".pre-specs-detail-actions");
  await expect(decision.getByRole("heading", { name: "발주계획에서 추적 결정을 이어받았습니다" })).toBeVisible();
  await expect(decision).toContainText("현재 추적 상태 · 계속 추적");
  await expect(decision.getByRole("button", { name: "추적 시작", exact: true })).toHaveCount(0);
  await expect(decision.getByRole("button", { name: "보류", exact: true })).toHaveCount(0);
  await expect(decision.getByRole("button", { name: "종료", exact: true })).toHaveCount(0);
  await expect(decision.getByRole("link", { name: "사업 추적에서 상태 관리 ↗", exact: true })).toBeVisible();
  expect(trace.trackingPatches).toEqual([]);
});

// PLAN 단계 D 작업 4: 신규 건만 한 조작으로 받는다. 사유는 빈 값으로 시작하는
// 드롭다운이고 `기타`를 골랐을 때만 직접 입력이 열린다.
test("신규 사전규격은 사유 드롭다운과 담당자로 추적을 시작하고 상세로 이어진다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all");

  await selectPreSpecRow(page, newPreSpec.title);

  const decision = page.locator(".pre-specs-detail-actions");
  await expect(decision).toContainText("현재 · 미선택 → 저장하면 계속 추적");
  // 사유는 비어 있는 상태로 시작하고 자유 입력은 열려 있지 않다.
  await expect(decision.locator("textarea")).toHaveCount(0);
  const save = decision.getByRole("button", { name: "추적 시작", exact: true });
  await expect(save).toBeDisabled();

  await fillRecordReason(page, "발주계획에 없던 신규 건");
  await decision.getByRole("textbox", { name: "담당자 이름 (필수)" }).fill("홍길동");
  await save.click();

  await expect.poll(() => trace.trackingPatches).toEqual([{
    opportunityId: 78,
    trackingStatus: "계속 추적",
    reason: "발주계획에 없던 신규 건",
  }]);
  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs/992");
});

test("사유 예시를 고르면 그 문장이 그대로 저장 사유가 된다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all");

  await selectPreSpecRow(page, newPreSpec.title);
  const decision = page.locator(".pre-specs-detail-actions");
  await decision.getByRole("combobox", { name: "선택 사유" }).click();
  await page.getByRole("option", { name: "후속 입찰공고 확인" }).click();
  // 예시를 고른 뒤에는 자유 입력이 열리지 않는다.
  await expect(decision.locator("textarea")).toHaveCount(0);
  await decision.getByRole("textbox", { name: "담당자 이름 (필수)" }).fill("홍길동");
  await decision.getByRole("button", { name: "추적 시작", exact: true }).click();

  await expect.poll(() => trace.trackingPatches).toEqual([{
    opportunityId: 78,
    trackingStatus: "계속 추적",
    reason: "후속 입찰공고 확인",
  }]);
});

// 인라인 폼의 사유·담당자는 저장 전까지 화면에만 있다. 행을 옮기면 사라지므로
// 확인 없이 버리지 않는다(spec §3.3의 `onDirtyChange` → 목록 guard 경로).
test("추적 결정 입력이 있는 채로 행을 옮기면 확인 없이 버리지 않는다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all");

  await selectPreSpecRow(page, newPreSpec.title);
  const decision = page.locator(".pre-specs-detail-actions");
  const actor = decision.getByRole("textbox", { name: "담당자 이름 (필수)" });
  await actor.fill("아직 저장하지 않은 담당자");

  // 취소하면 선택 행도 입력도 그대로다.
  await selectPreSpecRow(page, trackingException.title);
  const guard = page.getByRole("alertdialog");
  await expect(guard).toBeVisible();
  await expect(guard).toContainText("저장하지 않은 추적 결정 사유와 담당자 이름이 있습니다.");
  await guard.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(guard).toHaveCount(0);
  await expect(decision.getByRole("textbox", { name: "담당자 이름 (필수)" })).toHaveValue("아직 저장하지 않은 담당자");

  // 확인하면 행이 바뀌고 저장 요청은 나가지 않는다.
  await selectPreSpecRow(page, trackingException.title);
  await page.getByRole("alertdialog").getByRole("button", { name: "저장하지 않고 옮기기", exact: true }).click();
  await expect(page.locator(".pre-specs-detail-title")).toContainText(trackingException.title);
  expect(trace.trackingPatches).toEqual([]);
});

// 선택한 건의 개요 본문은 목록 응답이 아니라 개요 endpoint의 run envelope에서 온다.
test("선택한 건의 개요 결과·품질 표식·근거 위치를 개요 응답에서 보여준다", async ({ page }) => {
  // 요약 줄은 첫 주장 다음 문장들이다. fixture에 두 번째 주장을 얹어 확인한다.
  const completed = overviewCompletedEnvelope();
  const run = {
    ...overviewCompletedRunFixture,
    result: {
      ...overviewCompletedRunFixture.result!,
      business_overview: [
        ...overviewCompletedRunFixture.result!.business_overview,
        {
          claim_id: "c1b",
          text: "민원·행정 데이터를 통합해 담당자가 업무 현황을 조회한다.",
          evidence: [{ page: 3, quote: "업무 현황 조회" }],
        },
      ],
    },
  };
  const trace = await mockPreSpecs(page, {
    overviewBody: { ...completed, current: run, history: [run] },
  });
  await page.goto("/pre-specs");

  // 우측 정보 영역은 첫 주장을 `사업 설명`으로, 예산·기간 주장을 규모·일정 한 줄로
  // 옮긴다(spec §3.1 2·5행). 확인 조건·문서 근거 목록·품질 표식은 상세가 갖는다.
  const detail = page.locator(".pre-specs-detail-pane");
  const description = detail.locator('.pre-specs-detail-block[aria-label="사업 설명"]');
  await expect(description).toContainText("차세대 통합 데이터 플랫폼을 구축하는 사업이다.");
  await expect(description).toContainText("검증 통과 · passed");
  await expect(detail.locator(".pre-specs-detail-tasks"))
    .toContainText("기존 데이터를 신규 플랫폼으로 이관하고 검증한다.");
  const scale = detail.locator(".pre-specs-detail-scale");
  await expect(scale).toContainText("사업 예산은 510,000,000원(VAT 포함)이고 수행기간은 10개월이다.");
  await expect(scale.getByRole("link", { name: "4쪽 ↗" })).toHaveAttribute(
    "href",
    `/api/pre-specs/991/overview/runs/${run.id}/pdf#page=4`,
  );
  expect(trace.overviewGets).toContain(991);
});

test("개요 결과가 없으면 상태가 무엇을 기다리는지 말하고 결과를 지어내지 않는다", async ({ page }) => {
  await mockPreSpecs(page, {
    overviewBody: overviewEnvelopeFixture(991, overviewFallbackQueuedRunFixture, [overviewFallbackQueuedRunFixture]),
  });
  await page.goto("/pre-specs");

  const detail = page.locator(".pre-specs-detail-pane");
  await expect(detail.locator('.pre-specs-detail-block[aria-label="사업 설명"]'))
    .toContainText("승인된 모델 실행이 큐에서 차례를 기다리고 있습니다.");
  // 결과가 없으면 과업 목록도 규모 한 줄도 만들지 않는다.
  await expect(detail.locator(".pre-specs-detail-tasks")).toHaveCount(0);
  await expect(detail.locator(".pre-specs-detail-scale")).toHaveCount(0);
});

test("개요 응답의 notice ID가 어긋나면 목록 화면도 교차 정본을 그리지 않는다", async ({ page }) => {
  await mockPreSpecs(page, { overviewBody: { ...overviewCompletedEnvelope(), notice_id: 992 } });
  await page.goto("/pre-specs");

  const detail = page.locator(".pre-specs-detail-pane");
  // 담당자 어휘로 적되 교차 표시를 막는 의미는 그대로다(ADR-0055 D11).
  await expect(detail).toContainText("개요 검토 결과를 확인할 수 없습니다.");
  await expect(detail.locator(".pre-specs-detail-tasks")).toHaveCount(0);
});

// 첨부 목록·처리 이력 탭은 우측 정보 영역에서 빠졌다(spec §3.1). 그 내용은
// 사전규격 상세가 소유하며 `prespec-briefing.spec.ts`가 그 자리를 검사한다.

test("notice 991 정본 상세는 29로 치환되지 않고 unknown을 사람 확인 상태로 보존한다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false&sort=deadline");
  await selectPreSpecRow(page, trackingException.title);
  await page.locator(".pre-specs-detail-actions").getByRole("link", { name: "상세 페이지 열기 →" }).click();

  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs/991");
  expect(new URL(page.url()).search).toBe("?sw_only=false&sort=deadline");
  await expect(page.getByRole("heading", { level: 2, name: trackingException.title })).toBeVisible();
  await expect(page.getByText("notice 991", { exact: true }).first()).toBeVisible();
  expect(trace.noticeGets).toEqual([991]);
  expect(trace.noticeGets).not.toContain(29);

  await page.reload();
  await expect(page.getByRole("heading", { level: 2, name: trackingException.title })).toBeVisible();
  expect(trace.noticeGets).toEqual([991, 991]);
  expect(trace.noticeGets).not.toContain(29);
});

test("사전규격 상세는 notice_pk projection의 현재 추적 상태와 첨부 집계를 보여준다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs/991");

  await expect(page.locator(".ps-record-saved-decision")).toContainText("현재 추적 상태 · 계속 추적");
  // 991은 발주계획에서 승계한 건이라 상세도 상태만 밝히고 다시 묻지 않는다.
  await expect(page.getByRole("heading", { name: "발주계획에서 추적 결정을 이어받았습니다" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "첨부 원문 취득 집계", exact: true })).toBeVisible();
  await expect(page.getByText("완료", { exact: true })).toBeVisible();
  await expect(page.getByText("차단", { exact: true })).toBeVisible();
  const assessment = page.getByLabel("예비 적합성 판단 근거");
  await expect(assessment).toContainText("공공 SI/통합관리 직접");
  await expect(assessment).toContainText("선택 의미검증 미실행");
  await expect(assessment.getByRole("link", { name: "원문 근거로 이동" })).toHaveAttribute("href", "#ps-evidence");
  await expect(page.locator(".ps-record-facts")).toContainText("개요 기준 · 개요 예비 판단");
  expect(trace.listQueries.at(-1)?.get("notice_pk")).toBe("991");
  expect(trace.listQueries.at(-1)?.has("sw_only")).toBe(false);
});

test("사유 없이 사전규격 추적 상태를 보낼 수 없다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  // 991은 승계 건이라 결정 form이 없다. 사유 규칙은 신규 건에서 확인한다.
  await page.goto("/pre-specs/992");

  // 저장 버튼과 비활성 사유는 헤더 아래 추적 결정 카드가 함께 소유한다.
  await expect(page.getByRole("button", { name: "추적 시작", exact: true })).toBeDisabled();
  await expect(page.locator("#pre-spec-tracking-save-disabled")).toContainText("추적 결정을 저장하려면 사유를 입력하십시오.");
  expect(trace.trackingPatches).toEqual([]);
});

test("사전규격 추적 선택에 성공하면 사람 결정 상태가 갱신된다", async ({ page }) => {
  const trace = await mockPreSpecs(page, { trackingSavedActor: "테스트 담당자" });
  await page.goto("/pre-specs/992");

  // 사전규격에서 고를 수 있는 값은 `계속 추적` 하나뿐이다(ADR-0046 결정 6).
  await expect(page.getByRole("button", { name: "보류", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "종료", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "계속 추적", exact: true })).toHaveCount(0);
  await fillRecordReason(page, "연계 범위를 확인한 뒤 계속 검토하기로 함");
  await page.getByRole("textbox", { name: "담당자 이름 (필수)" }).fill("홍길동");
  await page.getByRole("button", { name: "추적 시작", exact: true }).click();

  await expect.poll(() => trace.trackingPatches).toEqual([{
    opportunityId: 78,
    trackingStatus: "계속 추적",
    reason: "연계 범위를 확인한 뒤 계속 검토하기로 함",
  }]);
  await expect(page.getByText("추적 시작을 저장했습니다", { exact: true })).toBeVisible();
  // The mock API returns this audit name; the view must use the response, not the draft.
  await expect(page.locator(".ps-record-saved-decision")).toContainText("테스트 담당자");
});

test("사업기회가 없으면 추적 결정을 기록할 수 없는 이유를 보여준다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs/993");

  // 추적 상태 글자는 화면에 한 번만 나온다(spec §4) — ① 머리 카드의 칩이 그 자리다.
  await expect(page.locator(".pre-spec-detail-header")).toContainText("추적 결정 · 사업기회 미연결");
  await expect(page.locator(".mutation-feedback-warning")).toContainText("아직 사업기회에 연결되지 않아 추적 상태를 결정할 수 없습니다.");
  await expect(page.getByRole("button", { name: "계속 추적", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "추적 시작", exact: true })).toBeDisabled();
  await expect(page.locator("#pre-spec-tracking-save-disabled")).toContainText("아직 사업기회에 연결되지 않아");
});

test("사전규격 목록과 상세는 viewport 바깥으로 넘치지 않는다", async ({ page }) => {
  await mockPreSpecs(page);
  for (const path of ["/pre-specs", "/pre-specs/991"]) {
    await page.goto(path);
    await expect(page.locator("header.topbar h1")).toHaveText("사전규격");
    await expect.poll(() => page.evaluate(() => ({
      root: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      canvas: (() => {
        const canvas = document.querySelector<HTMLElement>(".page-canvas");
        return canvas ? canvas.scrollWidth - canvas.clientWidth : 0;
      })(),
    }))).toEqual({ root: 0, canvas: 0 });
  }
});

// 승인 시안(브리핑형): 읽는 헤더에는 조작이 없고, 사유·담당자·저장은 헤더 바로
// 아래 추적 결정 카드 한 자리에서만 다룬다.
test("사전규격 상세는 헤더 아래 추적 결정 카드에서 사유·담당자·저장을 한 줄로 다룬다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs/992");
  const header = page.locator('header[aria-label="사전규격 상세 정보"]');
  const decision = page.getByRole('complementary', { name: '추적 결정', exact: true });
  const saveButton = decision.getByRole('button', { name: '추적 시작', exact: true });
  // 되돌릴 수 없는 입력·저장 조작을 헤더에 올리지 않는다(헤더에 남는 것은 번호 복사·원문뿐).
  await expect(header.getByRole('button', { name: /추적|저장/ })).toHaveCount(0);
  await expect(header.locator('textarea, input, [role="combobox"]')).toHaveCount(0);
  await expect(saveButton).toHaveCount(1);
  await expect(page.getByRole('button', { name: '추적 시작', exact: true })).toHaveCount(1);
  await expect(decision.getByRole('combobox', { name: '선택 사유' })).toBeVisible();
  await expect(decision.getByRole('textbox', { name: '담당자 이름 (필수)' })).toBeVisible();
  await expect(page.locator('.detail-skeleton-main').getByRole('textbox', { name: '선택 사유 직접 입력 (필수)' })).toHaveCount(0);
  await fillRecordReason(page, '후속 입찰공고까지 확인하기로 함');
  await decision.getByRole('textbox', { name: '담당자 이름 (필수)' }).fill('홍길동');
  await saveButton.click();
  await expect(decision.getByRole('heading', { name: '추적 시작을 저장했습니다' })).toBeVisible();
  expect(trace.trackingPatches).toEqual([{
    opportunityId: 78,
    trackingStatus: "계속 추적",
    reason: "후속 입찰공고까지 확인하기로 함",
  }]);
  await expect(page.locator('[data-review-primitive="history-link-rail"]')).toHaveCount(1);
});

// 사업기회에 아직 연결되지 않은 사전규격도 비활성 결정 액션과 그 사유가
// 오른쪽 결정 패널에서 스크롤 없이 함께 보여야 한다.
test("사업기회 미연결 사전규격은 비활성 추적 결정 액션과 사유가 스크롤 없이 함께 보인다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs/993");
  const saveButton = page.getByRole("button", { name: "추적 시작", exact: true });
  await expect(saveButton).toBeInViewport();
  await expect(saveButton).toBeDisabled();
  await expect(page.locator("#pre-spec-tracking-save-disabled")).toBeInViewport();
  await expect(page.locator("#pre-spec-tracking-save-disabled")).toContainText("아직 사업기회에 연결되지 않아");
});

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`사전규격 ERP 상세 ${viewport.width}: 읽기 우선 배치와 긴 제목의 구역 이동`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const trace = await mockPreSpecs(page);
    await page.goto('/pre-specs/992?sw_only=false&sort=deadline');
    // 단일 열이라 본문 카드(① 머리 카드)의 폭을 잰다. 스켈레톤 자리는 조회가 끝나면 사라진다.
    await expect(page.locator('.ps-record .pre-spec-detail-header')).toBeVisible();
    const geometry = await page.evaluate(() => {
      const main = document.querySelector('.ps-record .pre-spec-detail-header')!;
      const canvas = document.querySelector('.page-canvas')!;
      return {
        mainWidth: main.getBoundingClientRect().width,
        rootZoom: Number.parseFloat(getComputedStyle(document.documentElement).zoom) || 1,
        canvasZoom: Number.parseFloat(getComputedStyle(canvas).zoom) || 1,
        agency: getComputedStyle(document.querySelector('.ps-record-agency')!).fontSize,
        overflow: canvas.scrollWidth - canvas.clientWidth,
      };
    });
    const effectiveScale = geometry.rootZoom * geometry.canvasZoom;
    expect(effectiveScale).toBeCloseTo(1, 2);
    // spec §4: 오른쪽 400px 열이 없어지고 단일 열 최대 폭 1040px 가운데 정렬이다.
    expect(geometry.mainWidth).toBeLessThanOrEqual(1040 * effectiveScale + 1);
    expect(geometry.mainWidth).toBeGreaterThan(550 * effectiveScale);
    expect(geometry.agency).toBe('14px');
    expect(geometry.overflow).toBe(0);
    const decision = page.getByRole('complementary', { name: '추적 결정', exact: true });
    await expect(decision.getByRole('combobox', { name: '선택 사유' })).toBeInViewport();
    await expect(decision.getByRole('button', { name: '추적 시작', exact: true })).toBeInViewport();
    const alignment = await page.evaluate(() => {
      const top = (sel: string) => document.querySelector(sel)!.getBoundingClientRect().top;
      const save = document.querySelector('.pre-spec-tracking-save')!.getBoundingClientRect();
      return { selector: top('.ps-record-tracking-card .astryx-selector'), actor: top('.ps-record-tracking-card .actor-field input'), save: save.top, reasonGap: document.querySelector('#pre-spec-tracking-save-disabled')!.getBoundingClientRect().top - save.bottom };
    });
    expect(Math.abs(alignment.selector - alignment.actor)).toBeLessThanOrEqual(1);
    expect(Math.abs(alignment.save - alignment.actor)).toBeLessThanOrEqual(1);
    expect(alignment.reasonGap).toBeGreaterThanOrEqual(0);
    expect(alignment.reasonGap).toBeLessThanOrEqual(12);
    await captureRecord(page, `normal-${viewport.width}`);
    await page.route('**/api/notices/992', route => route.fulfill({ json: {
      ...notice991, id: 992,
      title: '공공데이터 통합관리체계 고도화 및 기관 간 연계 시스템 구축을 위한 정보화 사업 사전규격 검토 '.repeat(3),
      agency: '해솔시청 디지털정책국 공공데이터 통합운영 추진단',
    } }));
    await page.reload();
    await expect(page.locator('.ps-record-agency')).toContainText('해솔시청');
    await captureRecord(page, `long-${viewport.width}`);
    // 구역 이동 nav는 새 배치에 없다. 본문은 한 흐름으로 읽고 결정 카드는 헤더 바로 아래에 있다.
    await expect(decision.getByRole('button', { name: '추적 시작', exact: true })).toBeInViewport();
    await fillRecordReason(page, '세부 과업과 연계 범위를 확인하고 계속 추적');
    await decision.getByRole('textbox', { name: '담당자 이름 (필수)' }).fill('검토 담당자');
    await expect(decision.getByRole('button', { name: '추적 시작', exact: true })).toBeEnabled();
    await captureRecord(page, `documents-${viewport.width}`);
    // 처리 이력과 실행 정보는 접힌 상태로 있다가 펼칠 수 있다.
    await page.getByRole('button', { name: '현재 주장 검증 진단 · 고정 입력과 식별 해시' }).click();
    await captureRecord(page, `history-${viewport.width}`);
    await expect(decision.getByRole('textbox', { name: '선택 사유 직접 입력 (필수)' })).toHaveValue('세부 과업과 연계 범위를 확인하고 계속 추적');
    expect(trace.trackingPatches).toEqual([]);
    await decision.getByRole('button', { name: '추적 시작', exact: true }).click();
    await expect.poll(() => trace.trackingPatches.length).toBe(1);
    await expect(decision.getByRole('heading', { name: '추적 시작을 저장했습니다' })).toBeVisible();
    await expect(decision.getByRole('combobox', { name: '선택 사유' })).toHaveCount(0);
    await page.getByRole('link', { name: '목록으로 돌아가기' }).click();
    expect(new URL(page.url()).searchParams.get('sw_only')).toBe('false');
    expect(new URL(page.url()).searchParams.get('sort')).toBe('deadline');
  });
}

test('사전규격 ERP 상세: 요약 조회 실패를 판정 없음·미선택으로 바꾸지 않는다', async ({ page }) => {
  await mockPreSpecs(page);
  await page.route('**/api/pre-specs?notice_pk=991', route => route.fulfill({ status: 503, json: { detail: 'unavailable' } }));
  await page.goto('/pre-specs/991');
  await expect(page.locator('.pre-spec-detail-grade-row')).toContainText('등급 미확인', { timeout: 15000 });
  await expect(page.getByRole('complementary', { name: '추적 결정', exact: true })).toContainText('사업기회 연결 정보를 확인할 수 없습니다.');
  await expect(page.locator('.ps-record-facts')).not.toContainText('판정 없음');
  await expect(page.locator('.ps-record-facts')).not.toContainText('추적 미선택');
  await captureRecord(page, 'partial-1440');
});

test('사전규격 ERP 상세: 빈 결과와 실제 0건을 구분한다', async ({ page }) => {
  await mockPreSpecs(page);
  await page.route('**/api/notices/993', route => route.fulfill({ json: { ...notice991, id: 993, budget: null, attachment_count: 0 } }));
  await page.goto('/pre-specs/993');
  await expect(page.locator('.ps-record-facts')).toContainText('예산 미확인');
  await expect(page.locator('.ps-record-secondary-facts')).toContainText('0건');
  await captureRecord(page, 'empty-1440');
});

test('사전규격 ERP 상세: 로딩 자리가 본문과 보조 열을 유지한다', async ({ page }) => {
  await mockPreSpecs(page);
  let finish: (() => void) | undefined;
  const pending = new Promise<void>(resolve => { finish = resolve; });
  await page.route('**/api/notices/991', async route => { await pending; await route.fulfill({ json: notice991 }); });
  await page.goto('/pre-specs/991');
  await expect(page.getByRole('status').filter({ hasText: '사전규격 991 상세를 불러오는 중' })).toBeVisible();
  await captureRecord(page, 'loading-1440');
  finish?.();
  await expect(page.locator('#pre-spec-detail-title')).toBeVisible();
});

test('공식 번호는 lifecycle fallback과 복사를 지원하고 내부 PK를 대신 표시하지 않는다', async ({ page }) => {
  await mockPreSpecs(page);
  await page.route('**/api/pre-specs?notice_pk=992', route => route.fulfill({ json: { items: [{ ...newPreSpec, pre_spec_no: null }], total: 1 } }));
  await page.route('**/api/notices/992', route => route.fulfill({ json: { ...notice991, id: 992, lifecycle: { pre_spec_no: 'R26BD00270001' }, url: null } }));
  // The fallback path is needed on Tailscale HTTP, where Clipboard API is absent.
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined });
    document.execCommand = (command: string) => {
      if (command === 'copy') (window as Window & { copiedNumber?: string }).copiedNumber = (document.activeElement as HTMLTextAreaElement).value;
      return command === 'copy';
    };
  });
  await page.goto('/pre-specs/992');
  await expect(page.locator('.ps-record-number')).toHaveText('R26BD00270001');
  await page.getByRole('button', { name: '번호 복사', exact: true }).click();
  await expect(page.getByText('사전규격번호를 복사했습니다.', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as Window & { copiedNumber?: string }).copiedNumber)).toBe('R26BD00270001');
  await expect(page.getByRole('button', { name: '번호 복사', exact: true })).toBeFocused();
  await page.route('**/api/notices/992', route => route.fulfill({ json: { ...notice991, id: 992, lifecycle: {}, url: null } }));
  await page.reload();
  await expect(page.locator('.ps-record-number')).toHaveText('미확인');
  await expect(page.getByRole('button', { name: '번호 복사', exact: true })).toBeDisabled();
});

for (const url of [null, 'javascript:alert(1)', '/guessed-detail/992', 'https://user:password@example.invalid/notice']) {
  test(`원문 주소가 없거나 사용할 수 없으면 추정 링크를 만들지 않는다: ${url?.split(':')[0] ?? 'null'}`, async ({ page }) => {
    await mockPreSpecs(page);
    await page.route('**/api/notices/992', route => route.fulfill({ json: { ...notice991, id: 992, url } }));
    await page.goto('/pre-specs/992');
    await expect(page.locator('.ps-record-source-unavailable')).toContainText(url ? '원문 URL 확인 불가' : '원문 URL 없음');
    await expect(page.getByRole('link', { name: '나라장터 원문', exact: true })).toHaveCount(0);
  });
}

test('수집된 원문 URL을 새 탭으로 열고 추적 저장 실패 시 입력을 보존한다', async ({ page, context }) => {
  await mockPreSpecs(page);
  const sourceUrl = 'https://example.invalid/collected-prespec/992';
  await page.route('**/api/notices/992', route => route.fulfill({ json: { ...notice991, id: 992, url: sourceUrl } }));
  await context.route(sourceUrl, route => route.fulfill({ contentType: 'text/html; charset=utf-8', body: '<h1>수집된 원문 URL · 테스트</h1>' }));
  await page.goto('/pre-specs/992');
  const link = page.getByRole('link', { name: '나라장터 원문', exact: true });
  await expect(link).toHaveAttribute('href', sourceUrl);
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  const popupPromise = context.waitForEvent('page'); await link.click(); const popup = await popupPromise;
  await expect(popup.getByRole('heading', { name: '수집된 원문 URL · 테스트' })).toBeVisible();
  expect(await popup.evaluate(() => window.opener === null)).toBe(true); await popup.close();
  await page.getByRole('combobox', { name: '선택 사유' }).click();
  await page.getByRole('option', { name: '후속 입찰공고 확인', exact: true }).click();
  await page.getByRole('textbox', { name: '담당자 이름 (필수)' }).fill('김기획');
  await page.route('**/api/opportunities/78/tracking-status', route => route.fulfill({ status: 503, json: { detail: 'unavailable' } }));
  await page.getByRole('button', { name: '추적 시작', exact: true }).click();
  await expect(page.getByRole('complementary', { name: '추적 결정', exact: true }).locator('.mutation-feedback-error')).toBeVisible();
  await expect(page.getByRole('combobox', { name: '선택 사유' })).toContainText('후속 입찰공고 확인');
  await expect(page.getByRole('textbox', { name: '담당자 이름 (필수)' })).toHaveValue('김기획');
  await expect(page.getByRole('button', { name: '다시 저장', exact: true })).toBeInViewport();
  await captureRecord(page, 'save-error-1440');
});

// ---------------------------------------------------------------------------
// 발주계획 후보 구역 (docs/0917_opportunity-tracking/spec.md §4.4·§11.4)

function planCandidateLink(id: number, overrides: Partial<OpportunityLinkView> = {}): OpportunityLinkView {
  return {
    id,
    stage: "notice",
    link_type: "candidate",
    status: "후보 확인 대기",
    search_strategy: "full",
    attempted_strategies: ["full"],
    agency_match: true,
    last_searched_at: "2026-08-31T00:00:00Z",
    evidence_external_no: null,
    evidence_bid_no: null,
    human_decision: null,
    reviewer_name: null,
    reviewed_at: null,
    review_reason: null,
    record_type: "notice",
    record_id: 992,
    notice_id: 992,
    order_plan_id: null,
    source_type: "pre_spec",
    title: newPreSpec.title,
    agency: newPreSpec.agency,
    external_id: newPreSpec.pre_spec_no,
    record_external_id: newPreSpec.pre_spec_no,
    ...overrides,
  };
}

const planCandidates: PreSpecOrderPlanCandidatesResponse = {
  notice_pk: 992,
  items: [
    {
      link: planCandidateLink(9001),
      opportunity_id: 301,
      tracking_status: "미선택",
      order_plans: [{
        order_plan_id: 5101,
        order_plan_unty_no: "R26DD00001001",
        title: "신규 행정 서비스 통합 구축",
        agency_name: "신규 발주기관",
        planned_order_year: "2026",
        // 수집 값이 연월이면 같은 연도를 두 번 적지 않는다.
        planned_order_month: "2026-10",
        budget_amount: 1_200_000_000,
      }],
    },
    {
      link: planCandidateLink(9002, {
        search_strategy: "longest_fragment",
        attempted_strategies: ["full", "breaking_split", "normalized", "longest_fragment"],
        agency_match: false,
      }),
      opportunity_id: 302,
      tracking_status: "계속 추적",
      order_plans: [{
        order_plan_id: 5102,
        order_plan_unty_no: "R26DD00001002",
        title: "행정 서비스 고도화 사업",
        agency_name: "다른 발주기관",
        planned_order_year: null,
        planned_order_month: null,
        budget_amount: null,
      }],
    },
  ],
};

function planCandidateOwner(id: number): OpportunityDetailResponse {
  return {
    section: "조치 필요",
    pending_candidate_link_count: 1,
    open_blocking_item_count: 0,
    id,
    tracking_status: "미선택",
    tracking_reason: null,
    tracking_selected_by: null,
    tracking_selected_at: null,
    recheck_signal: false,
    recheck_signal_at: null,
    recheck_signal_link_id: null,
    first_registered_stage: "order_plan",
    action_reasons: ["candidate_pending"],
    hold_review_due_at: null,
    links: [
      planCandidateLink(8001, {
        stage: "order_plan",
        link_type: "official",
        status: "확정",
        search_strategy: null,
        attempted_strategies: [],
        agency_match: null,
        last_searched_at: null,
        record_type: "order_plan",
        record_id: 5101,
        notice_id: null,
        order_plan_id: 5101,
        source_type: null,
        title: "신규 행정 서비스 통합 구축",
        agency: "신규 발주기관",
        external_id: "R26DD00001001",
        record_external_id: "R26DD00001001",
      }),
      planCandidateLink(9001),
    ],
  };
}

interface PlanCandidateTrace {
  candidateGets: number;
  ownerGets: number[];
  decisions: Array<{ linkId: number; body: unknown; headers: Record<string, string> }>;
}

async function mockPlanCandidates(
  page: Page,
  decision: { status: number; body: unknown } = { status: 200, body: planCandidateLink(9001, { status: "사람 확인 병합", human_decision: "accepted" }) },
): Promise<PlanCandidateTrace> {
  const trace: PlanCandidateTrace = { candidateGets: 0, ownerGets: [], decisions: [] };
  await page.route("**/api/pre-specs/992/order-plan-candidates", async (route) => {
    trace.candidateGets += 1;
    const decided = trace.decisions.length > 0 && decision.status === 200;
    await route.fulfill({ json: decided ? { notice_pk: 992, items: [] } : planCandidates });
  });
  await page.route("**/api/opportunities/{301,302}", async (route) => {
    if (route.request().method() !== "GET") { await route.fallback(); return; }
    const id = Number(new URL(route.request().url()).pathname.split("/").at(-1));
    trace.ownerGets.push(id);
    await route.fulfill({ json: planCandidateOwner(id) });
  });
  await page.route("**/api/opportunities/links/*/decision", async (route) => {
    const request = route.request();
    if (request.method() !== "PATCH") { await route.fallback(); return; }
    trace.decisions.push({
      linkId: Number(new URL(request.url()).pathname.split("/").at(-2)),
      body: request.postDataJSON(),
      headers: request.headers(),
    });
    await route.fulfill({ status: decision.status, json: decision.body });
  });
  return trace;
}

async function acceptPlanCandidate(page: Page, title: string) {
  const section = page.locator("#ps-record-plan-candidates");
  await section.getByRole("listitem").filter({ hasText: title }).getByRole("button", { name: "확인", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "판단 사유" }).click();
  await page.getByRole("option", { name: "원천 정보를 비교해 같은 사업임을 확인" }).click();
  await dialog.getByLabel("결정 기록자").fill("홍길동");
  await dialog.getByRole("button", { name: "같은 사업으로 연결" }).click();
  return dialog;
}

test("발주계획 후보는 요약·대조 방식·기관 일치를 보여 주고 수용하면 결정을 보내 다시 읽는다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  const candidates = await mockPlanCandidates(page);
  await page.goto("/pre-specs/992");

  const section = page.locator("#ps-record-plan-candidates");
  // 6단 구조를 늘리지 않고 ⑥ 처리 이력 카드 안에 있다.
  await expect(page.locator("#ps-process #ps-record-plan-candidates")).toHaveCount(1);
  await expect(section.getByRole("heading", { name: "발주계획 후보 2건" })).toBeVisible();
  await expect(section).toContainText("공고명과 기관이 비슷한 발주계획입니다. 같은 사업인지 사람이 확인해야 연결됩니다.");

  const first = section.getByRole("listitem").filter({ hasText: "신규 행정 서비스 통합 구축" });
  await expect(first).toContainText("신규 발주기관 · 발주 예정 2026년 10월 · 예산 1,200,000,000원 · 통합번호 R26DD00001001");
  // 대조 방식 이름은 사업 추적 화면과 같은 이름표(`trackingFlow.searchStrategyLabel`)다.
  await expect(first).toContainText("대조 방식 · 전체 이름 일치");
  await expect(first).toContainText("기관 일치");
  await expect(first).not.toContainText("기관 불일치");
  await expect(first).toContainText("후보 사업기회 추적 · 미선택");
  await expect(first.getByRole("link", { name: "사업기회 #301 →" })).toHaveAttribute("href", "/opportunities/301");

  // null 예정 시기·예산은 0이나 없음으로 접지 않는다.
  const second = section.getByRole("listitem").filter({ hasText: "행정 서비스 고도화 사업" });
  await expect(second).toContainText("다른 발주기관 · 발주 예정 미확인 · 예산 값 없음");
  await expect(second).toContainText("대조 방식 · 가장 긴 조각 일치");
  await expect(second).toContainText("기관 불일치");
  await expect(second).toContainText("후보 사업기회 추적 · 계속 추적");

  const detailQueriesBefore = trace.listQueries.filter((query) => query.get("notice_pk") === "992").length;
  const dialog = await acceptPlanCandidate(page, "신규 행정 서비스 통합 구축");

  await expect.poll(() => candidates.decisions.length).toBe(1);
  expect(candidates.ownerGets).toEqual([301]);
  expect(candidates.decisions[0].linkId).toBe(9001);
  expect(candidates.decisions[0].body).toEqual({ decision: "accepted", reason: "원천 정보를 비교해 같은 사업임을 확인" });
  expect(candidates.decisions[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  await expect(dialog).toHaveCount(0);
  // 결정 응답이 `사람 확인 병합`이므로 수용은 두 사업기회의 병합으로 알린다(CandidateLinkDialog).
  await expect(page.getByText("후보를 수용해 두 사업기회를 병합했습니다(사람 확인 병합).", { exact: true })).toBeVisible();
  await expect(section.getByText("발주계획 후보 없음 (자동 대조는 SW사업대상 사전규격에서만 합니다)", { exact: true })).toBeVisible();
  await expect(section.getByRole("listitem")).toHaveCount(0);
  expect(candidates.candidateGets).toBeGreaterThanOrEqual(2);
  await expect.poll(() => trace.listQueries.filter((query) => query.get("notice_pk") === "992").length).toBeGreaterThan(detailQueriesBefore);
});

test("발주계획 후보 수용이 병합 충돌이면 대화상자 안에서만 양쪽 상태를 한 번 안내하고 후보를 남긴다", async ({ page }) => {
  await mockPreSpecs(page);
  const candidates = await mockPlanCandidates(page, {
    status: 409,
    body: {
      error: {
        code: "candidate_merge_state_conflict",
        message: "두 사업기회 모두 사람 추적 선택 또는 재검토 신호가 있어 병합할 수 없습니다",
        details: {
          opportunities: [
            { id: 301, tracking_status: "계속 추적", tracking_selected_by: "김기획", tracking_selected_at: "2026-09-01T00:00:00Z", recheck_signal: false },
            { id: 78, tracking_status: "보류", tracking_selected_by: null, tracking_selected_at: null, recheck_signal: true },
          ],
        },
      },
      request_id: null,
    },
  });
  await page.goto("/pre-specs/992");

  const dialog = await acceptPlanCandidate(page, "신규 행정 서비스 통합 구축");
  const conflict = dialog.locator(".opportunity-merge-conflict");
  await expect(conflict).toContainText("양쪽 모두 사람이 고른 추적 상태가 있어 병합할 수 없습니다. 한쪽의 추적 결정을 먼저 정리하세요.");
  const states = conflict.getByRole("list", { name: "병합 대상 사업기회의 추적 상태" }).getByRole("listitem");
  await expect(states).toHaveCount(2);
  await expect(states.nth(0)).toContainText("사업 #301 · 계속 추적");
  await expect(states.nth(0)).toContainText("선택자 · 김기획");
  await expect(states.nth(0)).toContainText("재검토 신호 · 없음");
  // 값이 없는 선택자·선택 시각은 미확인으로 남기고 지어내지 않는다.
  await expect(states.nth(1)).toContainText("사업 #078 · 보류");
  await expect(states.nth(1)).toContainText("선택자 · 미확인 · 선택 시각 · 미확인");
  await expect(states.nth(1)).toContainText("재검토 신호 · 있음");
  await expect(conflict).toContainText("연결 상태는 바뀌지 않았습니다");
  await expect(dialog.getByLabel("결정 기록자")).toHaveValue("홍길동");
  // 안내는 대화상자 안에 한 번만 있다. 사전규격 구역이 같은 안내를 다시 그리지 않는다.
  const guidance = page.getByText("양쪽 모두 사람이 고른 추적 상태가 있어 병합할 수 없습니다", { exact: false });
  await expect(guidance).toHaveCount(1);

  await dialog.getByRole("button", { name: "취소", exact: true }).click();
  await dialog.getByRole("button", { name: "입력 버리고 닫기", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // 대화상자를 닫으면 안내도 사라진다. 구역에 병합 충돌 알림이 따로 남지 않는다.
  const section = page.locator("#ps-record-plan-candidates");
  await expect(guidance).toHaveCount(0);
  await expect(section.getByRole("alert")).toHaveCount(0);
  // 연결되지 않았으므로 후보는 그대로 남는다.
  await expect(section.getByRole("heading", { name: "발주계획 후보 2건" })).toBeVisible();
  expect(candidates.decisions).toHaveLength(1);
});

test("발주계획 후보가 없으면 없음으로 단정하지 않는 한 줄 안내만 남긴다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs/992");

  const section = page.locator("#ps-record-plan-candidates");
  await expect(section).toHaveText("발주계획 후보 없음 (자동 대조는 SW사업대상 사전규격에서만 합니다)");
  await expect(section.getByRole("heading")).toHaveCount(0);
  await expect(section.getByRole("button")).toHaveCount(0);
  await expect(page.getByText("발주계획 없음", { exact: true })).toHaveCount(0);
});

test("발주계획 후보 조회가 실패하면 후보 없음 대신 오류를 말하고 다시 시도로 읽는다", async ({ page }) => {
  await mockPreSpecs(page);
  let failing = true;
  await page.route("**/api/pre-specs/992/order-plan-candidates", async (route) => {
    if (failing) {
      await route.fulfill({ status: 503, json: { error: { code: "service_unavailable", message: "unavailable", details: null }, request_id: null } });
      return;
    }
    await route.fulfill({ json: planCandidates });
  });
  await page.goto("/pre-specs/992");

  const section = page.locator("#ps-record-plan-candidates");
  const alert = section.getByRole("alert");
  await expect(alert).toContainText("발주계획 후보를 불러오지 못했습니다.");
  await expect(alert).toContainText("후보가 없다는 뜻이 아닙니다.");
  await expect(section).not.toContainText("발주계획 후보 없음");

  failing = false;
  await section.getByRole("button", { name: "다시 시도", exact: true }).click();
  await expect(section.getByRole("heading", { name: "발주계획 후보 2건" })).toBeVisible();
  await expect(section.getByRole("alert")).toHaveCount(0);
});
