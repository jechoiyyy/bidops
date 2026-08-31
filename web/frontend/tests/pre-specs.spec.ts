import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";

const FIXED_TIME = new Date("2026-08-31T09:00:00+09:00");

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
};

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
};

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

const unknownOverview = {
  schema_version: "bidops.prespec-overview-reviews.v1",
  notice_id: 991,
  reviews: [{
    id: "00000000-0000-0000-0000-000000000991",
    notice_id: 991,
    status: "needs_human_review",
    result: null,
    completed_at: null,
    current_snapshot: {
      id: "10000000-0000-0000-0000-000000000991",
      document_version_id: "20000000-0000-0000-0000-000000000991",
      structure_id: "30000000-0000-0000-0000-000000000991",
      source_sha256: "a".repeat(64),
      payload_sha256: "b".repeat(64),
      cut_status: "unknown",
      strategy: null,
      start_locator: null,
      end_locator: null,
      created_at: "2026-08-31T01:00:00Z",
    },
    attempts: [],
  }],
};

interface PreSpecTrace {
  listQueries: URLSearchParams[];
  noticeGets: number[];
  overviewGets: number[];
}

interface PreSpecMockOptions {
  emptyDefault?: boolean;
  overviewNoticeId?: number;
  overviewReviewNoticeId?: number;
  overviewStatus?: number;
  overviewBody?: unknown;
}

async function mockPreSpecs(page: Page, options: PreSpecMockOptions = {}): Promise<PreSpecTrace> {
  const trace: PreSpecTrace = { listQueries: [], noticeGets: [], overviewGets: [] };

  await page.route("**/api/pre-specs**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const overviewMatch = url.pathname.match(/^\/api\/pre-specs\/(\d+)\/overview-reviews$/);

    if (overviewMatch && request.method() === "GET") {
      const id = Number(overviewMatch[1]);
      trace.overviewGets.push(id);
      const overviewBody = options.overviewBody ?? (id === 991 ? {
        ...unknownOverview,
        notice_id: options.overviewNoticeId ?? unknownOverview.notice_id,
        reviews: unknownOverview.reviews.map((review) => ({
          ...review,
          notice_id: options.overviewReviewNoticeId ?? review.notice_id,
        })),
      } : { detail: "사전규격 없음" });
      await route.fulfill({
        status: options.overviewStatus ?? (id === 991 ? 200 : 404),
        contentType: "application/json",
        body: JSON.stringify(overviewBody),
      });
      return;
    }

    if (url.pathname === "/api/pre-specs" && request.method() === "GET") {
      trace.listQueries.push(new URLSearchParams(url.search));
      const swOnly = url.searchParams.get("sw_only") !== "false";
      const items = swOnly
        ? options.emptyDefault ? [] : [trackingException, newPreSpec]
        : [trackingException, newPreSpec, allOnlyPreSpec];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, total: items.length, limit: 50, offset: 0 }),
      });
      return;
    }

    await route.fallback();
  });

  await page.route("**/api/notices/**", async (route) => {
    const request = route.request();
    const match = new URL(request.url()).pathname.match(/^\/api\/notices\/(\d+)$/);
    if (match && request.method() === "GET") {
      const id = Number(match[1]);
      trace.noticeGets.push(id);
      await route.fulfill({
        status: id === 991 ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(id === 991 ? notice991 : { detail: "공고 없음" }),
      });
      return;
    }
    await route.fallback();
  });

  return trace;
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
  await expect(page.getByRole("link", { name: allOnlyPreSpec.title })).toBeVisible();
});

test("추적 예외, 신규, D-day, 문서 차단과 실패를 별도 상태로 표시한다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const trackedRow = page.getByRole("row").filter({ has: page.getByRole("link", { name: trackingException.title }) });
  await expect(trackedRow).toContainText("추적");
  await expect(trackedRow).toContainText("추적 예외");
  await expect(trackedRow).toContainText("N");
  await expect(trackedRow.getByLabel("D-day: D-2")).toBeVisible();
  await expect(trackedRow.getByText("차단 2", { exact: true })).toBeVisible();
  await expect(trackedRow.getByText("실패 1", { exact: true })).toBeVisible();

  const newRow = page.getByRole("row").filter({ has: page.getByRole("link", { name: newPreSpec.title }) });
  await expect(newRow.getByText("신규", { exact: true })).toBeVisible();
});

test("notice 991 정본 상세는 29로 치환되지 않고 unknown을 사람 확인 상태로 보존한다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false&sort=deadline");
  await page.getByRole("link", { name: trackingException.title }).click();

  expect(new URL(page.url()).pathname).toBe("/pre-specs/991");
  expect(new URL(page.url()).search).toBe("?sw_only=false&sort=deadline");
  await expect(page.getByRole("heading", { level: 2, name: trackingException.title })).toBeVisible();
  await expect(page.getByText("notice 991", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("unknown · 사람 확인 필요", { exact: true })).toBeVisible();
  await expect(page.getByText("전체 문서 성공으로 자동 보정하지 않습니다.")).toBeVisible();
  expect(trace.noticeGets).toEqual([991]);
  expect(trace.overviewGets).toEqual([991]);
  expect(trace.noticeGets).not.toContain(29);

  await page.reload();
  await expect(page.getByRole("heading", { level: 2, name: trackingException.title })).toBeVisible();
  expect(trace.noticeGets).toEqual([991, 991]);
  expect(trace.overviewGets).toEqual([991, 991]);
  expect(trace.noticeGets).not.toContain(29);
});

test("overview envelope notice ID가 어긋나면 교차 정본을 렌더링하지 않는다", async ({ page }) => {
  await mockPreSpecs(page, { overviewNoticeId: 992 });
  await page.goto("/pre-specs/991");

  await expect(page.getByRole("heading", { level: 2, name: trackingException.title })).toBeVisible();
  await expect(page.getByText("개요 검토 정본을 확인할 수 없습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("unknown · 사람 확인 필요", { exact: true })).not.toBeVisible();
  await expect(page.getByText("응답의 notice ID가 요청과 일치하지 않아 개요 검토를 표시하지 않습니다.", { exact: true })).toBeVisible();
});

test("overview nested review notice ID가 어긋나면 교차 정본을 렌더링하지 않는다", async ({ page }) => {
  await mockPreSpecs(page, { overviewReviewNoticeId: 992 });
  await page.goto("/pre-specs/991");

  await expect(page.getByRole("heading", { level: 2, name: trackingException.title })).toBeVisible();
  await expect(page.getByText("개요 검토 정본을 확인할 수 없습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("unknown · 사람 확인 필요", { exact: true })).not.toBeVisible();
  await expect(page.getByText("응답의 notice ID가 요청과 일치하지 않아 개요 검토를 표시하지 않습니다.", { exact: true })).toBeVisible();
});

test("overview API 오류는 서버 detail이나 원문을 화면에 노출하지 않는다", async ({ page }) => {
  const secret = "raw-prompt-response-secret";
  await mockPreSpecs(page, { overviewStatus: 500, overviewBody: { detail: secret } });
  await page.goto("/pre-specs/991");

  await expect(page.getByText("개요 검토 상태를 불러오지 못했습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText(secret, { exact: true })).not.toBeVisible();
  await expect(page.getByText("개요 검토 API 응답을 확인할 수 없습니다.", { exact: true })).toBeVisible();
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
