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
import type { PreSpecListItem } from "../src/lib/types";

const FIXED_TIME = new Date("2026-08-31T09:00:00+09:00");

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
  auto_preparation_status: "waiting_attachments",
  auto_preparation_reason: "awaiting_fetch",
  latest_deep_review_id: null,
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
  auto_preparation_status: "blocked",
  auto_preparation_reason: "processing_failed",
  latest_deep_review_id: null,
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
  auto_preparation_status: "not_applicable",
  auto_preparation_reason: null,
  latest_deep_review_id: null,
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
      const items = noticePk !== null
        ? allItems.filter((item) => item.notice_pk === noticePk)
        : swOnly
          ? options.emptyDefault ? [] : allItems.slice(0, 3)
          : allItems;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items,
          total: items.length,
          limit: 50,
          offset: 0,
          overview_status_counts: overviewStatusCounts(items),
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
// 시안의 첫 두 줄을 맞바꿨다). 사업명·기관은 16px이고 굵은 글자는 사업명 하나뿐이며,
// 나머지는 14px이고 마감은 오른쪽 열이다.
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
  expect(await fontSize(agency)).toBe(16);
  expect(await fontSize(title)).toBe(16);
  const fontWeight = (locator: ReturnType<typeof preSpecRow>) => locator
    .evaluate((element) => Number(getComputedStyle(element).fontWeight));
  expect(await fontWeight(title)).toBeGreaterThanOrEqual(600);
  expect(await fontWeight(agency)).toBeLessThan(600);
  expect(await fontSize(row.locator(".pre-specs-row-meta"))).toBe(14);
  expect(await fontSize(row.locator(".pre-specs-row-state"))).toBe(14);
  expect(await fontSize(row.locator(".pre-specs-deadline"))).toBe(14);

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
  await page.goto("/pre-specs");

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

// 상단 보기는 목록을 좁히는 탐색 묶음이다. 건수는 서버 전체 집계이고 목록은
// 불러온 페이지 기준이므로 두 숫자가 다를 수 있다는 사실을 화면이 밝힌다.
test("상단 보기는 URL과 동기화되고 건수의 기준을 밝힌다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const views = page.locator(".pre-specs-views");
  const attention = views.getByRole("button", { name: /^사람 확인/ });
  await expect(attention).toContainText("1");
  await attention.click();
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("attention");
  await expect(preSpecRow(page, trackingException.title)).toBeVisible();
  await expect(preSpecRow(page, newPreSpec.title)).toHaveCount(0);

  await views.getByRole("button", { name: /^전체/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.has("view")).toBe(false);
  await expect(preSpecRow(page, newPreSpec.title)).toBeVisible();
});

// 나열 순서는 사람이 찾는 차례다(사용자 결정 2026-09-08): 전체 → 끝난 건 →
// 손이 필요한 건 → 아직 도는 건 → 예외. 건수가 0인 `취소`는 자리만 차지하므로
// 지금 보고 있지 않으면 그리지 않는다.
test("보기 탭은 전체·개요 완료·사람 확인·진행·대기·실패 차례로 늘어선다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const tabs = page.locator(".pre-specs-views").getByRole("button");
  await expect(tabs).toHaveCount(5);
  // 건수는 접근 이름의 일부라 라벨만 떼어 비교한다(`${라벨}  ${건수}`).
  await expect.poll(async () => (await tabs.allTextContents()).map((text) => text.replace(/[\s\u00a0]*[\d,–]*$/u, "").trim()))
    .toEqual(["전체", "개요 완료", "사람 확인", "진행·대기", "실패"]);
});

// 정렬은 사업 추적과 같은 자리(상세 필터 안 Selector)로 옮겼다. 접히면 보이지
// 않으므로 지금 어떤 순서인지는 목록 머리가 늘 글자로 밝힌다.
test("표시 순서 Selector는 sort=deadline을 기록하고 목록 머리가 그 순서를 밝힌다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const listHead = page.locator(".pre-specs-list-head");
  await expect(listHead).not.toContainText("마감 임박순");

  await page.getByRole("button", { name: "상세 필터", exact: true }).click();
  await page.getByRole("combobox", { name: "표시 순서" }).click();
  await page.getByRole("option", { name: "마감 임박순", exact: true }).click();

  await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("deadline");
  await expect.poll(() => trace.listQueries.at(-1)?.get("sort")).toBe("deadline");
  await expect(listHead).toContainText("마감 임박순");

  // 기본값(게시 최신순)으로 되돌리면 URL에서 인자가 사라진다.
  await page.getByRole("combobox", { name: "표시 순서" }).click();
  await page.getByRole("option", { name: "게시 최신순", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.has("sort")).toBe(false);
  await expect(listHead).not.toContainText("마감 임박순");
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

test("등급 필터는 불러온 페이지에만 적용된다는 사실을 화면이 밝힌다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

  await page.getByRole("button", { name: "상세 필터", exact: true }).click();
  await page.getByRole("combobox", { name: "적합성 등급" }).click();
  await page.getByRole("option", { name: "검토 권장", exact: true }).click();

  await expect.poll(() => new URL(page.url()).searchParams.get("grade")).toBe("검토 권장");
  await expect(page.locator(".pre-specs-grade-filter-note")).toContainText("불러온 페이지에만 적용됩니다");
  await expect(preSpecRow(page, newPreSpec.title)).toBeVisible();
  await expect(preSpecRow(page, trackingException.title)).toHaveCount(0);
});

// 시안의 목록은 행을 고르면 오른쪽 상세만 바뀐다. 사업명을 눌러도 목록을 떠나지
// 않으며, 상세 화면 진입은 상세 pane 바닥의 `상세 검토 열기`가 소유한다.
test("사업명을 눌러도 목록에 남고 오른쪽 상세만 바뀐다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

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
  await detail.getByRole("link", { name: "상세 검토 열기 →" }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs/992");
});

// `null`은 사람이 고른 `미선택`이 아니다. 연결이 없는 것과도 다르다.
test("추적 상태의 미확인·미연결·미선택을 서로 다른 표시로 남긴다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");

  await expect(preSpecRow(page, unknownTrackingPreSpec.title).locator(".pre-specs-row-state"))
    .toContainText("미확인");
  await expect(preSpecRow(page, newPreSpec.title).locator(".pre-specs-row-state")).toContainText("미선택");
  await expect(preSpecRow(page, allOnlyPreSpec.title).locator(".pre-specs-row-state"))
    .toContainText("사업기회 미연결");

  await selectPreSpecRow(page, unknownTrackingPreSpec.title);
  await page.locator(".pre-specs-detail-actions").getByRole("button", { name: "추적 선택 변경" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("현재 추적 상태")).toContainText("미확인");
  await expect(dialog.getByLabel("현재 추적 상태")).not.toContainText("미선택");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();

  await selectPreSpecRow(page, allOnlyPreSpec.title);
  await expect(page.locator(".pre-specs-detail-actions")).toContainText("사업기회 미연결");
});

// ADR-0046 결정 6: 추적 상태를 묻는 자리는 하나다. 발주계획에서 승계한 건은 이 화면이
// 다시 묻지 않고 승계 사실만 밝힌다.
test("발주계획에서 승계한 건은 추적 대화상자에서 다시 묻지 않는다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs");

  await selectPreSpecRow(page, trackingException.title);
  await page.locator(".pre-specs-detail-actions").getByRole("button", { name: "추적 선택 변경" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "추적 상태 · 발주계획에서 승계" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "추적 상태 저장", exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "보류", exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "종료", exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("link", { name: "사업 추적" })).toBeVisible();
  expect(trace.trackingPatches).toEqual([]);
});

// PLAN 단계 D 작업 4: 신규 건만 한 조작으로 받는다. 사유는 빈 값으로 시작하는
// 드롭다운이고 `기타`를 골랐을 때만 직접 입력이 열린다.
test("신규 사전규격은 사유 드롭다운과 담당자로 추적을 시작하고 상세로 이어진다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs");

  await selectPreSpecRow(page, newPreSpec.title);
  await page.locator(".pre-specs-detail-actions").getByRole("button", { name: "추적 선택 변경" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "심층 검토 추적 선택" })).toBeVisible();
  // 사유는 비어 있는 상태로 시작하고 자유 입력은 열려 있지 않다.
  await expect(dialog.locator("textarea")).toHaveCount(0);
  await expect(dialog.locator(".pre-spec-tracking-reason-preset input")).toHaveCount(0);
  const save = dialog.getByRole("button", { name: "추적 시작하고 심층 검토", exact: true });
  await expect(save).toBeDisabled();

  await dialog.getByRole("combobox", { name: "선택 사유" }).click();
  await page.getByRole("option", { name: "기타 · 직접 입력" }).click();
  const custom = dialog.locator(".pre-spec-tracking-reason-preset input");
  await expect(custom).toBeVisible();
  await custom.fill("발주계획에 없던 신규 건");
  await dialog.getByRole("textbox", { name: "담당자 이름 (필수)" }).fill("홍길동");
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
  await page.goto("/pre-specs");

  await selectPreSpecRow(page, newPreSpec.title);
  await page.locator(".pre-specs-detail-actions").getByRole("button", { name: "추적 선택 변경" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "선택 사유" }).click();
  await page.getByRole("option", { name: "후속 입찰공고 확인" }).click();
  // 예시를 고른 뒤에는 자유 입력이 열리지 않는다.
  await expect(dialog.locator(".pre-spec-tracking-reason-preset input")).toHaveCount(0);
  await dialog.getByRole("textbox", { name: "담당자 이름 (필수)" }).fill("홍길동");
  await dialog.getByRole("button", { name: "추적 시작하고 심층 검토", exact: true }).click();

  await expect.poll(() => trace.trackingPatches).toEqual([{
    opportunityId: 78,
    trackingStatus: "계속 추적",
    reason: "후속 입찰공고 확인",
  }]);
});

// 대화상자의 사유·담당자는 저장 전까지 화면에만 있다. 창을 닫으면 사라지므로
// 확인 없이 버리지 않는다.
test("추적 결정 입력이 있는 채로 창을 닫으면 확인 없이 버리지 않는다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs");

  await selectPreSpecRow(page, newPreSpec.title);
  await page.locator(".pre-specs-detail-actions").getByRole("button", { name: "추적 선택 변경" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: "담당자 이름 (필수)" }).fill("아직 저장하지 않은 담당자");

  // 취소하면 창도 입력도 그대로다.
  await page.keyboard.press("Escape");
  const guard = dialog.locator(".pre-specs-dialog-guard");
  await expect(guard).toBeVisible();
  await expect(guard).toContainText("저장하지 않은 추적 결정 사유와 담당자 이름이 있습니다.");
  await guard.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(guard).toHaveCount(0);
  await expect(dialog.getByRole("textbox", { name: "담당자 이름 (필수)" })).toHaveValue("아직 저장하지 않은 담당자");

  // 확인하면 창이 닫히고 저장 요청은 나가지 않는다.
  await page.keyboard.press("Escape");
  await dialog.locator(".pre-specs-dialog-guard").getByRole("button", { name: "저장하지 않고 닫기", exact: true }).click();
  await expect(dialog).toHaveCount(0);
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

  const overview = page.locator(".pre-specs-detail-pane .pre-specs-overview");
  await expect(overview.getByRole("heading", { name: "개요 검토 결과" })).toBeVisible();
  await expect(overview).toContainText("차세대 통합 데이터 플랫폼을 구축하는 사업이다.");
  await expect(overview.locator(".pre-specs-overview-summary")).toHaveText("민원·행정 데이터를 통합해 담당자가 업무 현황을 조회한다.");
  await expect(overview).toContainText("검증 통과 · passed");
  // 품질 표식은 표식 그대로 남는다 — 참조 실행을 완료로 바꾸지 않는다.
  await expect(overview.locator(".pre-specs-overview-quality")).toContainText("참조 실행 · 품질 미측정");
  await expect(overview.getByRole("heading", { name: "확인 조건" })).toBeVisible();
  await expect(overview.getByRole("heading", { name: "문서 근거" })).toBeVisible();
  const locator = overview.getByLabel("근거 위치").first();
  await expect(locator).toContainText("3쪽");
  await expect(locator.getByRole("link", { name: "3쪽" })).toHaveAttribute(
    "href",
    `/api/pre-specs/991/overview/runs/${run.id}/pdf#page=3`,
  );
  await expect(overview.getByRole("link", { name: "상세에서 근거 원문 열기 →" })).toBeVisible();
  expect(trace.overviewGets).toContain(991);
});

test("개요 결과가 없으면 상태가 무엇을 기다리는지 말하고 결과를 지어내지 않는다", async ({ page }) => {
  await mockPreSpecs(page, {
    overviewBody: overviewEnvelopeFixture(991, overviewFallbackQueuedRunFixture, [overviewFallbackQueuedRunFixture]),
  });
  await page.goto("/pre-specs");

  const overview = page.locator(".pre-specs-detail-pane .pre-specs-overview");
  await expect(overview).toContainText("검토 결과 미확정");
  await expect(overview).toContainText("승인된 모델 실행이 큐에서 차례를 기다리고 있습니다.");
  await expect(overview.getByRole("heading", { name: "문서 근거" })).toHaveCount(0);
});

test("개요 응답의 notice ID가 어긋나면 목록 화면도 교차 정본을 그리지 않는다", async ({ page }) => {
  await mockPreSpecs(page, { overviewBody: { ...overviewCompletedEnvelope(), notice_id: 992 } });
  await page.goto("/pre-specs");

  const detail = page.locator(".pre-specs-detail-pane");
  // 담당자 어휘로 적되 교차 표시를 막는 의미는 그대로다(ADR-0055 D11).
  await expect(detail).toContainText("개요 검토 결과를 확인할 수 없습니다.");
  await expect(detail.locator(".pre-specs-overview")).toHaveCount(0);
});

test("상세 탭은 첨부 집계와 실행 이력을 각자 자리에서 보여준다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const detail = page.locator(".pre-specs-detail-pane");
  await detail.locator(".pre-specs-detail-tab", { hasText: "첨부 문서" }).click();
  await expect(detail.getByRole("heading", { name: "첨부 원문 취득 집계" })).toBeVisible();
  await expect(detail.locator(".pre-specs-document-counts")).toContainText("차단");

  await detail.locator(".pre-specs-detail-tab", { hasText: "처리 이력" }).click();
  await expect(detail.getByRole("heading", { name: "개요 실행 이력" })).toBeVisible();
  await expect(detail.getByRole("heading", { name: "사람의 선택과 자동 준비" })).toBeVisible();
  await expect(detail.locator(".pre-specs-history-facts").last()).toContainText("첨부 취득 대기");
});

test("notice 991 정본 상세는 29로 치환되지 않고 unknown을 사람 확인 상태로 보존한다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false&sort=deadline");
  await selectPreSpecRow(page, trackingException.title);
  await page.locator(".pre-specs-detail-actions").getByRole("link", { name: "상세 검토 열기 →" }).click();

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

  await expect(page.getByText("사업기회 미연결", { exact: true })).toBeVisible();
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
    await expect(page.locator('.ps-record .detail-skeleton-main')).toBeVisible();
    const geometry = await page.evaluate(() => {
      const main = document.querySelector('.ps-record .detail-skeleton-main')!;
      const side = document.querySelector('.ps-record-side')!;
      const canvas = document.querySelector('.page-canvas')!;
      const uiScale = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--bo-ui-scale")) || 1;
      const canvasZoom = Number.parseFloat(getComputedStyle(canvas).zoom) || 1;
      return {
        sideWidth: side.getBoundingClientRect().width,
        mainWidth: main.getBoundingClientRect().width,
        uiScale,
        canvasZoom,
        agency: getComputedStyle(document.querySelector('.ps-record-agency')!).fontSize,
        overflow: canvas.scrollWidth - canvas.clientWidth,
      };
    });
    const effectiveScale = geometry.uiScale * geometry.canvasZoom;
    expect(effectiveScale).toBeCloseTo(1, 2);
    expect(geometry.sideWidth).toBeCloseTo(400 * effectiveScale, 0);
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
    await page.getByRole('button', { name: '처리 이력과 실행 정보' }).click();
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
