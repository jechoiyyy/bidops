import { expect, test, type Page } from "@playwright/test";
import {
  mockApi,
  mockPreSpecMatrix,
  mockPreSpecs,
  overviewCompletedRunFixture,
  overviewEnvelopeFixture,
} from "./api-mock";
import {
  mockPreSpecCautionSample,
  PRE_SPEC_CAUTION_SAMPLE_BID_NOTICE_NO,
  PRE_SPEC_CAUTION_SAMPLE_DESCRIPTION,
  PRE_SPEC_CAUTION_SAMPLE_HEADLINE,
  PRE_SPEC_CAUTION_SAMPLE_TASKS,
} from "./screen-fixtures";
import { formatPreSpecCaution, preSpecCautions } from "../src/lib/preSpecCautions";
import type { PageOverviewVerification, PreSpecListItem } from "../src/lib/types";

async function mockPagedPreSpecs(page: Page, total = 220): Promise<void> {
  await page.route("**/api/pre-specs**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname !== "/api/pre-specs" || route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    const limit = Number(url.searchParams.get("limit") ?? 200);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const items = Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, index) => {
      const noticePk = 12000 + offset + index;
      return {
        notice_pk: noticePk,
        pre_spec_no: `PRE-${noticePk}`,
        title: `페이지 가드 표본 ${noticePk}`,
        agency: "표본 발주기관",
        published_at: `2026-08-${String(30 - (index % 20)).padStart(2, "0")}T00:00:00Z`,
        deadline_at: null,
        budget: null,
        sw_business_status: "Y",
        business_division: "일반용역",
        origin: "신규",
        opportunity_id: offset + index === 0 ? 78 : null,
        tracking_status: offset + index === 0 ? "미선택" : null,
        kept_by_tracking: false,
        document: { attachments: 0, "완료": 0, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
        overview_review_status: "completed",
        grade: null,
        grade_source: null,
        auto_preparation_status: "not_applicable",
        auto_preparation_reason: null,
        latest_deep_review_id: null,
        first_observed_at: null,
        last_observed_at: null,
        next_action: null,
      };
    });
    await route.fulfill({
      json: {
        items,
        total,
        limit,
        offset,
        overview_status_counts: [{ status: "completed", count: total }],
        workspace_counts: { actionable: total, recent: total, tracking: 0, all: total },
      },
    });
  });
}

test("행은 색 없는 등급 글자 토큰을 두고 판정 없음을 접지 않는다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecMatrix(page);
  await page.goto("/pre-specs");
  const grades = page.locator(".pre-specs-row-grade");
  await expect(grades).toHaveCount(8);
  await expect(grades.filter({ hasText: "판정 없음" })).toHaveCount(1);
  // 색이 아니라 글자로 말한다: 등급별 색 클래스를 만들지 않는다.
  const classes = await grades.evaluateAll((nodes) => nodes.map((node) => node.className));
  expect([...new Set(classes)]).toEqual(["pre-specs-row-grade"]);
});

test("새 사전규격 필터는 페이지 전에 서버 질의로 적용된다", async ({ page }) => {
  const queries: URLSearchParams[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/pre-specs") queries.push(url.searchParams);
  });
  await mockApi(page);
  await mockPreSpecs(page);

  await page.goto("/pre-specs?auto_preparation_status=deep_review_ready_for_click&sw_only=false");
  await expect.poll(() => queries.at(-1)?.get("auto_preparation_status")).toBe("deep_review_ready_for_click");
  expect(queries.at(-1)?.get("sw_only")).toBe("false");
  // 예전 대시보드 링크는 workspace가 없었으므로 누적 결과 전체를 유지한다.
  expect(queries.at(-1)?.get("workspace")).toBe("all");

  // 추적 결정 대기도 서버 인자이며, 페이지 한정 필터 안내는 만들지 않는다.
  await page.goto("/pre-specs?tracking_decision=pending&sw_only=false");
  await expect.poll(() => queries.at(-1)?.get("tracking_decision")).toBe("pending");
  await expect(page.locator(".pre-specs-grade-filter-note")).toHaveCount(0);

  // 허용값이 아니면 무시하고 전체로 떨어진다 — 빈 목록을 지어내지 않는다.
  await page.goto("/pre-specs?auto_preparation_status=not_a_status&tracking_decision=yes&sw_only=false");
  await expect.poll(() => queries.at(-1)?.has("auto_preparation_status")).toBe(false);
  await expect(page.locator(".pre-specs-grade-filter-note")).toHaveCount(0);
});

test("대시보드 결정 대기 링크가 같은 집합의 목록 필터로 잇는다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  // 사이드바에도 같은 이름의 링크가 있으므로 업무 바로가기 띄로 좁힌다.
  await expect(page.locator(".dash-journey-strip").getByRole("link", { name: /사전규격/ }))
    .toHaveAttribute("href", "/pre-specs?workspace=all&auto_preparation_status=deep_review_ready_for_click&sw_only=false&sort=deadline");
});

test("최근 workspace는 KST 관측 범위 기본값과 수집 회차를 API에 전달한다", async ({ page }) => {
  const queries: URLSearchParams[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/pre-specs") queries.push(url.searchParams);
  });
  await mockApi(page);
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=recent&sw_only=false");

  await expect.poll(() => queries.at(-1)?.get("workspace")).toBe("recent");
  const query = queries.at(-1);
  expect(query?.get("workspace")).toBe("recent");
  expect(query?.get("sort")).toBe("observed");
  // The picker shows the derived seven-day Korea range, while omitted wire
  // bounds let the server apply that default only to the recent bucket.
  expect(query?.has("observed_from")).toBe(false);
  expect(query?.has("observed_to")).toBe(false);
  await expect(page.getByRole("button", { name: "수집 회차" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "관측 시작일" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "관측 종료일" })).toBeVisible();

  await page.getByRole("button", { name: "수집 회차" }).click();
  const sourceRun = page.getByRole("option", { name: /2026-09-14 ~ 2026-09-15 수집/ });
  await expect(sourceRun).toBeVisible();
  await sourceRun.click();
  await expect.poll(() => queries.at(-1)?.get("source_run_id")).toBe("pre-spec-run-b");

  await page.getByRole("button", { name: /^전체 이력/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("workspace")).toBe("all");
  const allParams = new URL(page.url()).searchParams;
  expect(allParams.has("observed_from")).toBe(false);
  expect(allParams.has("observed_to")).toBe(false);
  expect(allParams.has("sort")).toBe(false);

  // 날짜를 직접 고른 recent 탭도 빠져나가면 recent 전용 범위를 남기지 않는다.
  await page.goto("/pre-specs?workspace=recent&sw_only=false&observed_from=2026-09-10&observed_to=2026-09-15&sort=published");
  await page.getByRole("button", { name: /^전체 이력/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("workspace")).toBe("all");
  const resetParams = new URL(page.url()).searchParams;
  expect(resetParams.has("observed_from")).toBe(false);
  expect(resetParams.has("observed_to")).toBe(false);
  expect(resetParams.has("sort")).toBe(false);
});

test("기존 view URL은 전체 workspace의 overview_view로 정규화된다", async ({ page }) => {
  const queries: URLSearchParams[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/pre-specs") queries.push(url.searchParams);
  });
  await mockApi(page);
  await mockPreSpecs(page);
  await page.goto("/pre-specs?view=completed&sw_only=false");

  await expect.poll(() => queries.at(-1)?.get("workspace")).toBe("all");
  await expect.poll(() => queries.at(-1)?.get("overview_view")).toBe("completed");
  await expect.poll(() => new URL(page.url()).searchParams.get("workspace")).toBe("all");
  expect(new URL(page.url()).searchParams.get("overview_view")).toBe("completed");
  expect(new URL(page.url()).searchParams.has("view")).toBe(false);
});

test("목록에서 방향키로 행을 옮기고 선택이 화면에 남는다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThan(1);

  // 첫 행이 이미 선택된 상태로 시작한다.
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
  await rows.first().focus();
  await page.keyboard.press("ArrowDown");
  // 선택은 hook이 아니라 화면이 소유하므로 선택 이동을 먼저 확인한다.
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");
  await expect(rows.nth(1)).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
  await expect(rows.first()).toBeFocused();
});

test("경계에서 방향키가 페이지를 넘기고 필터 변경은 첫 페이지로 돌린다", async ({ page }) => {
  // 한 페이지(200건)를 넘는 모집단이어야 경계 이동이 의미를 갖는다.
  const total = 260;
  await mockApi(page);
  await page.route("**/api/pre-specs**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname !== "/api/pre-specs" || route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    const limit = Number(url.searchParams.get("limit") ?? 200);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const items = Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, index) => ({
      notice_pk: 9000 + offset + index,
      pre_spec_no: `PRE-${9000 + offset + index}`,
      title: `페이지 표본 ${offset + index + 1}`,
      agency: "표본 발주기관",
      published_at: "2026-08-30T00:00:00Z", deadline_at: null, budget: null,
      sw_business_status: "Y", business_division: "일반용역", origin: "신규",
      opportunity_id: null, tracking_status: null, kept_by_tracking: false,
      document: { attachments: 0, "완료": 0, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
      overview_review_status: "completed", grade: null, grade_source: null,
      auto_preparation_status: "not_applicable", auto_preparation_reason: null,
      latest_deep_review_id: null,
      first_observed_at: null, last_observed_at: null, next_action: null,
    }));
    await route.fulfill({ json: { items, total, limit, offset, overview_status_counts: [{ status: "completed", count: total }], workspace_counts: { actionable: total, recent: total, tracking: 0, all: total } } });
  });

  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await expect(rows).toHaveCount(200);
  // 마지막 행에서 한 번 더 내려가면 다음 페이지로 넘어간다.
  await rows.last().click();
  await rows.last().focus();
  await page.keyboard.press("ArrowDown");
  await expect.poll(() => new URL(page.url()).searchParams.get("offset")).toBe("200");
  await expect(rows).toHaveCount(60);
  // Boundary intent wins over a restored active row: next lands on the first
  // row of page 2 and transfers real DOM focus after the response arrives.
  await expect(rows.first()).toBeFocused();
  await rows.first().focus();
  await page.keyboard.press("ArrowUp");
  await expect.poll(() => new URL(page.url()).searchParams.get("offset")).toBeNull();
  await expect(rows).toHaveCount(200);
  // Previous reverses the intent and lands on the last row of page 1.
  await expect(rows.last()).toBeFocused();

  // 반대로 필터를 바꾸면 사람이 요청한 적 없는 3페이지째를 보여 주지 않는다.
  await page.getByRole("button", { name: "상세 필터" }).click();
  await page.getByRole("combobox", { name: "발견 구분" }).click();
  await page.getByRole("option", { name: "독립 발견", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("offset")).toBeNull();
});

test("LS-04 선택은 두 페이지·새로고침·정렬에 남고 실제 필터 변경에서만 비워진다", async ({ page }) => {
  const total = 220;
  await mockApi(page);
  await page.route("**/api/pre-specs**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname !== "/api/pre-specs" || route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    const limit = Number(url.searchParams.get("limit") ?? 200);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const items = Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, index) => {
      const noticePk = 9700 + offset + index;
      return {
        notice_pk: noticePk,
        pre_spec_no: `PRE-${noticePk}`,
        title: `선택 표본 ${noticePk}`,
        agency: "표본 발주기관",
        published_at: `2026-08-${String(30 - (index % 20)).padStart(2, "0")}T00:00:00Z`,
        deadline_at: null,
        budget: null,
        sw_business_status: "Y",
        business_division: "일반용역",
        origin: "신규",
        opportunity_id: null,
        tracking_status: null,
        kept_by_tracking: false,
        document: { attachments: 0, "완료": 0, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
        overview_review_status: "completed",
        grade: null,
        grade_source: null,
        auto_preparation_status: "not_applicable",
        auto_preparation_reason: null,
        latest_deep_review_id: null,
        first_observed_at: null,
        last_observed_at: null,
        next_action: null,
      };
    });
    await route.fulfill({ json: { items, total, limit, offset, overview_status_counts: [{ status: "completed", count: total }], workspace_counts: { actionable: total, recent: total, tracking: 0, all: total } } });
  });

  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await expect(rows).toHaveCount(200);
  await rows.first().getByRole("checkbox").check();
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(rows).toHaveCount(20);
  await rows.nth(5).click();
  await rows.nth(5).getByRole("checkbox").check();
  await expect(page.getByText("선택 2건", { exact: true })).toBeVisible();
  const savedScrollTop = await page.locator(".pre-specs-list-scroll").evaluate((element) => {
    const target = Math.max(1, Math.min(140, element.scrollHeight - element.clientHeight));
    element.scrollTop = target;
    element.dispatchEvent(new Event("scroll", { bubbles: true }));
    return element.scrollTop;
  });
  await expect.poll(() => page.evaluate(() => {
    const raw = window.sessionStorage.getItem("bidops.pre-specs.selection.v1");
    return raw ? JSON.parse(raw).listScrollTop : -1;
  })).toBe(savedScrollTop);
  await page.reload();
  await expect(page.getByText("선택 2건", { exact: true })).toBeVisible();
  await expect(rows.nth(5)).toHaveAttribute("aria-current", "true");
  await expect.poll(() => page.locator(".pre-specs-list-scroll").evaluate((element) => element.scrollTop)).toBe(savedScrollTop);
  await page.getByRole("button", { name: "상세 필터", exact: true }).click();
  await page.getByRole("combobox", { name: "표시 순서" }).click();
  await page.getByRole("option", { name: "마감 임박순", exact: true }).click();
  await expect(page.getByText("선택 2건", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "발견 구분" }).click();
  await page.getByRole("option", { name: "발주계획 연계", exact: true }).click();
  await expect(page.getByText("선택 0건", { exact: true })).toBeVisible();
});

test("LS-02 native checkbox toggles without changing active row or detail draft", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await rows.first().click();
  await rows.first().focus();
  await page.keyboard.press("Space");
  await expect(rows.first().getByRole("checkbox")).toBeChecked();
  await rows.nth(1).getByRole("checkbox").check();
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
  await expect(rows.nth(1).getByRole("checkbox")).toBeChecked();
  await rows.nth(1).getByRole("checkbox").press("Space");
  await expect(rows.nth(1).getByRole("checkbox")).not.toBeChecked();
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
  await expect(page.locator(".pre-specs-selection-count")).toHaveAttribute("aria-live", "polite");
  await page.getByRole("button", { name: "선택 전체 해제", exact: true }).click();
  await expect(page.getByText("선택 0건", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "선택 전체 해제", exact: true })).toBeDisabled();
});

test("PN-01 선택 검토는 목록 정렬의 첫 ID를 opaque context로 연다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");
  const rowFor = (title: string) => page.locator(".pre-specs-row").filter({ hasText: title });
  await rowFor("신규 지능형 행정 지원 사전규격").getByRole("checkbox").check();
  await rowFor("안전한 문서 준비 사전규격").getByRole("checkbox").check();
  await page.getByRole("button", { name: "선택 항목 검토", exact: true }).click();
  await expect(page).toHaveURL(/\/pre-specs\/992\?.*selection_review=[0-9a-f-]+/);
  await expect(page).toHaveURL(/selection_review=/);
});

for (const sort of ["published", "deadline"] as const) {
  test(`PN-01 cross-page metadata preserves timezone ties microseconds and nulls (${sort})`, async ({ page }, testInfo) => {
    await page.clock.setFixedTime(new Date("2026-09-16T09:00:00+09:00"));
    await mockApi(page);
    const selected = [199, 201, 202, 204];
    const fillers = Array.from({ length: 204 }, (_, index) => index + 1).filter((id) => !selected.includes(id));
    const expected = sort === "published" ? [199, 202, 201, 204] : [201, 202, 199, 204];
    const serverIds = [...expected.slice(0, 3), ...fillers.sort((a, b) => sort === "published" ? b - a : a - b), 204];
    const timestamps = {
      199: { published_at: "2026-09-02T00:00:00.000002Z", deadline_at: "2026-09-02T00:00:00.000001Z" },
      201: { published_at: "2026-09-02T00:00:00.000001Z", deadline_at: "2026-09-02T00:00:00.000002Z" },
      202: { published_at: "2026-09-02T09:00:00.000001+09:00", deadline_at: "2026-09-02T09:00:00.000002+09:00" },
      204: { published_at: null, deadline_at: null },
    };
    await page.route("**/api/pre-specs**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname !== "/api/pre-specs") return route.fallback();
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 200);
      const items = serverIds.slice(offset, offset + limit).map((noticePk) => ({
        notice_pk: noticePk, pre_spec_no: `EDGE-${noticePk}`, title: `순서 표본 ${noticePk}`,
        agency: "합성 발주기관", budget: null, sw_business_status: "Y",
        business_division: "일반용역", origin: "신규", opportunity_id: null, tracking_status: null,
        kept_by_tracking: false,
        document: { attachments: 0, "완료": 0, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
        overview_review_status: "completed", grade: null, grade_source: null,
        auto_preparation_status: "not_applicable", auto_preparation_reason: null, latest_deep_review_id: null,
        first_observed_at: null, last_observed_at: null, next_action: null,
        ...(timestamps[noticePk as keyof typeof timestamps] ?? {
          published_at: "2026-09-01T00:00:00Z", deadline_at: "2026-10-01T00:00:00Z",
        }),
      }));
      await route.fulfill({ json: { items, total: 204, limit, offset, overview_status_counts: [{ status: "completed", count: 204 }], workspace_counts: { actionable: 204, recent: 204, tracking: 0, all: 204 } } });
    });
    await page.goto(`/pre-specs?sw_only=false&sort=${sort}`);
    const checkbox = (id: number) => page.getByRole("checkbox", { name: `사전규격 선택 · 순서 표본 ${id}`, exact: true });
    await checkbox(201).check();
    await page.getByRole("button", { name: "다음", exact: true }).click();
    await expect(page).toHaveURL(/offset=200/);
    await checkbox(204).check();
    await page.getByRole("button", { name: "이전", exact: true }).click();
    await checkbox(199).check();
    await checkbox(202).check();
    await expect(page.locator(".pre-specs-selection-toolbar")).toContainText("선택 4건");
    await page.getByRole("button", { name: "선택 항목 검토", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`\\/pre-specs\\/${expected[0]}\\?.*selection_review=`));
    const token = new URL(page.url()).searchParams.get("selection_review");
    const snapshot = await page.evaluate((reviewToken) => {
      const raw = sessionStorage.getItem(`bidops.pre-specs.review.v1.${reviewToken}`);
      return raw ? JSON.parse(raw) : null;
    }, token);
    expect(snapshot.orderedNoticeIds).toEqual(expected);
    expect(snapshot.entryNoticeId).toBe(expected[0]);
    const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
    await expect(navigation).toContainText("1 / 4");
    await expect(navigation.getByRole("button", { name: "이전 선택 사전규격" })).toBeDisabled();
    await expect(navigation.getByRole("button", { name: "다음 선택 사전규격" })).toBeEnabled();
    await page.screenshot({ path: testInfo.outputPath(`cross-page-${sort}.png`) });
  });
}

test("PN-03 선택 행의 상세 링크는 같은 순회 index를 시작하고 미선택 행은 단건 URL을 쓴다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");
  const rowFor = (title: string) => page.locator(".pre-specs-row").filter({ hasText: title });
  await rowFor("신규 지능형 행정 지원 사전규격").getByRole("checkbox").check();
  await rowFor("안전한 문서 준비 사전규격").getByRole("checkbox").check();
  await rowFor("신규 지능형 행정 지원 사전규격").click();
  const selectedDetail = page.getByRole("link", { name: "상세 페이지 열기 →", exact: true });
  await expect(selectedDetail).toHaveAttribute("href", /\/pre-specs\/992\?.*workspace=all.*sw_only=false/);
  await selectedDetail.click();
  await expect(page).toHaveURL(/\/pre-specs\/992\?.*selection_review=[0-9a-f-]+/);
  const selectedUrl = new URL(page.url());
  const token = selectedUrl.searchParams.get("selection_review");
  expect(token).toMatch(/^[0-9a-f-]+$/);
  const snapshot = await page.evaluate((reviewToken) => {
    const raw = window.sessionStorage.getItem(`bidops.pre-specs.review.v1.${reviewToken}`);
    return raw ? JSON.parse(raw) as { orderedNoticeIds: number[]; entryNoticeId: number } : null;
  }, token);
  expect(snapshot?.orderedNoticeIds).toEqual([992, 991]);
  expect(snapshot?.entryNoticeId).toBe(992);

  await page.goBack();
  await expect(page).toHaveURL(/\/pre-specs\?workspace=all&sw_only=false/);
  await expect(rowFor("신규 지능형 행정 지원 사전규격")).toHaveAttribute("aria-current", "true");
  await expect(rowFor("신규 지능형 행정 지원 사전규격").getByRole("checkbox")).toBeChecked();
  await expect(rowFor("안전한 문서 준비 사전규격").getByRole("checkbox")).toBeChecked();
  await rowFor("독립 수집된 심층 검토 클릭 대기 사전규격").click();
  const unselectedDetail = page.getByRole("link", { name: "상세 페이지 열기 →", exact: true });
  await expect(unselectedDetail).toHaveAttribute("href", /\/pre-specs\/993\?.*workspace=all.*sw_only=false/);
  await unselectedDetail.click();
  await expect(page).toHaveURL(/\/pre-specs\/993\?.*workspace=all.*sw_only=false(?!.*selection_review)/);
});

test("PN-03 선택 저장소를 사용할 수 없으면 검토 순서를 성공인 것처럼 열지 않는다", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "sessionStorage", {
      configurable: true,
      get() {
        throw new Error("session storage blocked");
      },
    });
  });
  await mockApi(page);
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  await page.locator(".pre-specs-row").first().getByRole("checkbox").check();
  const review = page.getByRole("button", { name: "선택 항목 검토", exact: true });
  await expect(review).toBeDisabled();
  await expect(page.locator("#pre-specs-selection-disabled")).toContainText("선택 저장소");
});

test("LS-06 필터·상세 이탈 guard 취소는 URL·active·check·입력을 보존한다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await rows.nth(1).click();
  await rows.nth(1).getByRole("checkbox").check();
  // 대화상자는 없다(spec §3.3). 추적 폼은 상세 pane 바닥에 늘 열려 있다.
  const decision = page.locator(".pre-specs-detail-actions");
  const actor = decision.getByRole("textbox", { name: "담당자 이름 (필수)" });
  await actor.fill("guard 취소 담당자");
  await actor.focus();
  const beforeUrl = page.url();
  const swToggle = page.locator(".pre-specs-switch input");
  await expect(swToggle).not.toBeChecked();

  // The tracking dialog is intentionally still open. Trigger the page-owned
  // filter transition through the page's own event path; the guard must catch
  // it before the URL changes.
  await page.evaluate(() => {
    const toggle = document.querySelector<HTMLInputElement>(".pre-specs-switch input");
    toggle?.click();
  });
  const guard = page.getByRole("alertdialog");
  await expect(guard).toBeVisible();
  // The modal layer disables body hit-testing; the portal surface must remain
  // pointer-interactive so this is a real click, not a forced test bypass.
  await expect(guard).toHaveCSS("pointer-events", "auto");
  await guard.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(page).toHaveURL(beforeUrl);
  await expect(swToggle).not.toBeChecked();
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");
  await expect(rows.nth(1).getByRole("checkbox")).toBeChecked();
  await expect(actor).toHaveValue("guard 취소 담당자");
  await expect(actor).toBeFocused();

  await page.evaluate(() => {
    const link = [...document.querySelectorAll("a")]
      .find((candidate) => candidate.textContent?.trim() === "상세 페이지 열기 →") as HTMLAnchorElement | undefined;
    link?.click();
  });
  const detailGuard = page.getByRole("alertdialog");
  await expect(detailGuard).toBeVisible();
  await detailGuard.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(page).toHaveURL(beforeUrl);
  await expect(actor).toHaveValue("guard 취소 담당자");
  await expect(actor).toBeFocused();

  // 행 전환도 같은 guard를 거친다 — 저장하지 않은 입력을 확인 없이 버리지 않는다.
  await rows.nth(2).click();
  const rowGuard = page.getByRole("alertdialog");
  await expect(rowGuard).toBeVisible();
  await rowGuard.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");
  await expect(actor).toHaveValue("guard 취소 담당자");
});

test("LS-06 pager guard 취소는 경계 URL·active·check·입력을 보존한다", async ({ page }) => {
  await mockApi(page);
  await mockPagedPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await rows.first().click();
  await rows.first().getByRole("checkbox").check();
  const actor = page.locator(".pre-specs-detail-actions").getByRole("textbox", { name: "담당자 이름 (필수)" });
  await actor.fill("pager guard 취소 담당자");
  await actor.focus();
  const beforeUrl = page.url();
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")]
      .find((candidate) => candidate.textContent?.trim() === "다음") as HTMLButtonElement | undefined;
    button?.click();
  });
  const guard = page.getByRole("alertdialog");
  await expect(guard).toBeVisible();
  await guard.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(page).toHaveURL(beforeUrl);
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
  await expect(rows.first().getByRole("checkbox")).toBeChecked();
  await expect(actor).toHaveValue("pager guard 취소 담당자");
  await expect(actor).toBeFocused();
});

test("개요 결과 본문과 첫 주장은 한 번만 렌더된다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecs(page);
  // 결과가 있는 개요 응답을 준다. 기본 mock은 결과 없음(absent) envelope이라
  // 중복 렌더 자체가 드러나지 않는다.
  // 이전 결과를 **다른 id**로 하나 더 둔다. 같은 run을 두 번 주면 history filter가
  // 그것을 걸러 내 이력이 비고, 그러면 anchor 중복을 검사할 수 없다.
  const previousRun = {
    ...overviewCompletedRunFixture,
    id: "00000000-0000-0000-0000-0000000009a1",
    result_id: "00000000-0000-0000-0000-0000000009a1",
    created_at: "2026-09-01T00:00:00Z",
  };
  await page.route("**/api/pre-specs/991/overview", (route) => route.fulfill({
    json: overviewEnvelopeFixture(991, overviewCompletedRunFixture, [overviewCompletedRunFixture, previousRun]),
  }));
  await page.goto("/pre-specs?notice_pk=991&sw_only=false");
  const detail = page.locator(".pre-specs-detail");
  await expect(detail).toBeVisible();
  // 우측 정보 영역에는 결과 본문 구역이 하나뿐이다(spec §3.1 2행). 첫 주장은
  // `사업 설명`이 갖고 다른 구역이 같은 문장을 한 번 더 그리지 않는다.
  const firstClaim = overviewCompletedRunFixture.result!.business_overview[0].text;
  await expect(detail.locator(".pre-specs-detail-summary")).toHaveCount(1);
  await expect(detail.getByText(firstClaim, { exact: false })).toHaveCount(1);
  await expect(detail.locator('.pre-specs-detail-block[aria-label="사업 설명"]')).toContainText(firstClaim);
  // 과업 요약은 과업 주장만 갖고 첫 주장을 되풀이하지 않는다.
  await expect(detail.locator(".pre-specs-detail-tasks"))
    .toContainText(overviewCompletedRunFixture.result!.main_tasks[0].text);
  await expect(detail.locator(".pre-specs-detail-tasks")).not.toContainText(firstClaim);
});

// docs/0915_ui-redesign/spec.md §6 A3 — 긴 판단 문장을 말줄임하지 않고
// 폭 안에서 줄바꿈한다. 높이가 넘치면 본문만 스크롤하고 추적 조작은 남는다.
test("우측 정보 영역은 긴 내용을 생략하지 않고 필요하면 본문만 스크롤한다", async ({ page }) => {
  // 이 spec은 `app` project(1440×900)로 돌므로 최소 지원 폭을 여기서 만든다.
  await page.setViewportSize({ width: 1280, height: 800 });
  await mockApi(page);
  await mockPreSpecCautionSample(page);
  await page.goto("/pre-specs?sw_only=false");

  const detail = page.locator(".pre-specs-detail");
  await expect(detail).toBeVisible();
  // 개요 결과·주의 줄·본공고까지 다 온 뒤에 재야 실제 높이를 잰다.
  await expect(detail.locator('.pre-specs-detail-block[aria-label="사업 설명"]'))
    .toContainText(PRE_SPEC_CAUTION_SAMPLE_DESCRIPTION);
  await expect(detail.locator(".pre-specs-detail-caution")).toContainText("주의 1건");
  await expect(detail.locator(".pre-specs-detail-figures")).toContainText(PRE_SPEC_CAUTION_SAMPLE_BID_NOTICE_NO);

  const scroll = detail.locator(".pre-specs-detail-scroll");
  const metrics = await scroll.evaluate((element) => {
    const textStyle = (selector: string) => {
      const node = element.querySelector<HTMLElement>(selector);
      if (!node) throw new Error(`누락된 상세 요소: ${selector}`);
      const style = getComputedStyle(node);
      return {
        lineClamp: style.getPropertyValue("-webkit-line-clamp"),
        overflow: style.overflow,
        textOverflow: style.textOverflow,
        whiteSpace: style.whiteSpace,
        overflowWrap: style.overflowWrap,
      };
    };
    element.scrollTop = element.scrollHeight;
    return {
      summary: textStyle(".pre-specs-detail-summary"),
      task: textStyle(".pre-specs-detail-tasks > li > span:last-child"),
      scale: textStyle(".pre-specs-detail-scale-text"),
      caution: textStyle(".pre-specs-detail-caution-text"),
      overflowY: getComputedStyle(element).overflowY,
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
      scrollTop: element.scrollTop,
    };
  });

  for (const style of [metrics.summary, metrics.task, metrics.scale, metrics.caution]) {
    expect(style.lineClamp).toBe("none");
    expect(style.textOverflow).toBe("clip");
    expect(style.whiteSpace).toBe("normal");
    expect(style.overflowWrap).toBe("anywhere");
  }
  expect(metrics.summary.overflow).toBe("visible");
  expect(metrics.task.overflow).toBe("visible");
  expect(metrics.overflowY).toBe("auto");
  expect(metrics.scrollHeight).toBeGreaterThanOrEqual(metrics.clientHeight);
  expect(metrics.scrollTop).toBe(metrics.scrollHeight - metrics.clientHeight);

  // 바닥 고정 블록의 상세 진입은 본문을 끝까지 굴려도 계속 보인다.
  await expect(detail.getByRole("link", { name: "상세 페이지 열기 →", exact: true })).toBeInViewport();
});

// spec §3.4 / §6 A4 — `전체 선택`은 **지금 페이지에 그려진 행만** 더한다.
test("LS-08 전체 선택은 현재 페이지만 더하고 다른 페이지 선택을 유지한다", async ({ page }) => {
  await mockApi(page);
  // 220건 = 1페이지 200건 + 2페이지 20건.
  await mockPagedPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await expect(rows).toHaveCount(200);
  const selectPage = page.getByRole("button", { name: "현재 페이지 전체 선택", exact: true });
  await expect(selectPage).toBeEnabled();

  await rows.first().getByRole("checkbox").check();
  await expect(page.getByText("선택 1건", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(rows).toHaveCount(20);
  await selectPage.click();
  // 1건(1페이지) + 20건(2페이지). 페이지를 넘나든 선택이 합쳐진다.
  await expect(page.getByText("선택 21건", { exact: true })).toBeVisible();
  await expect(selectPage).toBeDisabled();

  await page.getByRole("button", { name: "이전", exact: true }).click();
  await expect(rows).toHaveCount(200);
  await expect(rows.first().getByRole("checkbox")).toBeChecked();
  await expect(page.getByText("선택 21건", { exact: true })).toBeVisible();

  // 1페이지는 아직 전부 선택되지 않았으므로 다시 누를 수 있고, 이미 고른 한 건은
  // 두 번 더해지지 않는다(220건이지 221건이 아니다).
  await expect(selectPage).toBeEnabled();
  await selectPage.click();
  await expect(page.getByText("선택 220건", { exact: true })).toBeVisible();
  await expect(selectPage).toBeDisabled();
});

// spec §6 A5 — 구역 순서와 값 없음 표기. 시안(mockups/shots/Main.png)과 spec §3.1은
// 발주기관을 사업명 위에 두므로 DOM 순서도 그대로다.
test("우측 정보 영역은 사업명·기관·설명·과업 3건·예산·마감·게시·본공고·주의 한 줄·추적 폼·상세 링크를 순서대로 둔다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecCautionSample(page);
  await page.goto("/pre-specs?sw_only=false");

  const detail = page.locator(".pre-specs-detail");
  await expect(detail.locator(".pre-specs-detail-caution")).toContainText("주의 1건");

  const SECTIONS = [
    ["기관", ".pre-specs-detail-agency"],
    ["사업명", ".pre-specs-detail-title"],
    ["식별", ".pre-specs-detail-facts"],
    ["사업 설명", ".pre-specs-detail-summary"],
    ["주요 과업", ".pre-specs-detail-tasks"],
    ["예산·일정 4칸", ".pre-specs-detail-figures"],
    ["규모·일정 한 줄", ".pre-specs-detail-scale"],
    ["주의사항", ".pre-specs-detail-caution"],
    ["추적 폼", ".pre-spec-tracking-form"],
    ["상세 링크", ".pre-specs-detail-open"],
  ] as const;
  const found = await detail.evaluate((root, selectors) => {
    const all = [...root.querySelectorAll("*")];
    return selectors.map(([name, selector]) => {
      const node = root.querySelector(selector);
      return { name, index: node ? all.indexOf(node) : -1 };
    });
  }, SECTIONS.map(([name, selector]) => [name, selector] as [string, string]));
  expect(found.filter((entry) => entry.index < 0)).toEqual([]);
  const indexes = found.map((entry) => entry.index);
  expect(indexes, JSON.stringify(found)).toEqual([...indexes].sort((left, right) => left - right));

  // 과업은 앞 세 건만 오고 전체 건수를 숨기지 않는다.
  await expect(detail.locator(".pre-specs-detail-tasks > li")).toHaveCount(3);
  await expect(detail.locator(".pre-specs-detail-tasks")).toContainText(PRE_SPEC_CAUTION_SAMPLE_TASKS[2]);
  await expect(detail.locator(".pre-specs-detail-tasks")).not.toContainText(PRE_SPEC_CAUTION_SAMPLE_TASKS[3]);
  await expect(detail.locator('.pre-specs-detail-block[aria-label="주요 과업 요약"]'))
    .toContainText("4건 중 3건 · 전체는 상세에서");

  const figures = detail.locator(".pre-specs-detail-figures");
  await expect(figures).toContainText("49,844,864원");
  await expect(figures).toContainText(PRE_SPEC_CAUTION_SAMPLE_BID_NOTICE_NO);
  await expect(figures.locator(".pre-specs-detail-deadline")).toContainText("D-");
  await expect(detail.locator(".pre-specs-detail-caution")).toContainText(PRE_SPEC_CAUTION_SAMPLE_HEADLINE);
  // 목록 상세는 심층 검토 보고서를 읽지 않으므로(그 경로가 없다) 미확인 건수는
  // 알 수 없다고 남기고 "미확인 0건"처럼 측정한 값으로 지어내지 않는다(ADR-0057).
  await expect(detail.locator(".pre-specs-detail-caution")).not.toContainText("미확인");

  // 값이 없는 건은 지어내지 않고 `미확인` 계열로 남는다.
  await page.locator(".pre-specs-row").nth(1).click();
  await expect(detail.locator(".pre-specs-detail-agency")).toContainText("발주기관 미확인");
  await expect(detail.locator(".pre-specs-detail-title")).toContainText("사업명 미확인");
  await expect(detail.locator(".pre-specs-detail-facts")).toContainText("번호 미확인");
  await expect(detail.locator(".pre-specs-detail-facts")).toContainText("판정 없음");
  await expect(detail.locator(".pre-specs-detail-chips")).toContainText("SW 미확인");
  await expect(detail.locator(".pre-specs-detail-figures")).toContainText("예산 미확인");
  await expect(detail.locator(".pre-specs-detail-figures")).toContainText("마감 일시 없음");
  await expect(detail.locator(".pre-specs-detail-figures")).toContainText("미확인");
  await expect(detail.locator(".pre-specs-detail-tasks")).toHaveCount(0);
});

// docs/0915_ui-redesign/spec.md §3.2 — 주의사항 한 줄은 결정적 산출이고 모델
// 호출이 없다. 화면 없이 순수 함수만 부른다(화면 검사는 P2-C가 붙인다).
test.describe("preSpecCautions (spec §3.2)", () => {
  const cautionItem = (overrides: Partial<PreSpecListItem> = {}): PreSpecListItem => ({
    notice_pk: 991,
    pre_spec_no: "PRE-991",
    title: "주의 표본",
    agency: "표본 발주기관",
    published_at: "2026-09-01T00:00:00Z",
    deadline_at: null,
    budget: null,
    sw_business_status: "Y",
    business_division: "일반용역",
    origin: "신규",
    opportunity_id: null,
    tracking_status: null,
    kept_by_tracking: false,
    document: { attachments: 0, "완료": 0, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
    overview_review_status: "completed",
    grade: null,
    grade_source: null,
    auto_preparation_status: "not_applicable",
    auto_preparation_reason: null,
    latest_deep_review_id: null,
    first_observed_at: null,
    last_observed_at: null,
    next_action: null,
    ...overrides,
  });

  const verification = (claims: PageOverviewVerification["claims"]): PageOverviewVerification => ({
    verification_id: "v-991",
    status: "needs_human_review",
    reason_codes: [],
    claims,
  });

  const claim = (
    claim_id: string,
    text: string,
    deterministic_status: "passed" | "failed",
  ): PageOverviewVerification["claims"][number] => ({
    claim_id,
    text,
    deterministic_status,
    semantic_status: "not_run",
    reason_codes: [],
    verified_evidence: [],
  });

  test("결정적 검사가 실패한 주장만 있으면 그 주장 문장이 한 줄이 된다", () => {
    // 통과한 주장은 세지 않는다. `deterministic_status === "failed"`만 주의다.
    const result = preSpecCautions({
      item: cautionItem(),
      verification: verification([
        claim("c-1", "총 사업비는 12억원이다", "passed"),
        claim("c-2", "의견등록 마감은 9월 20일이다", "failed"),
      ]),
      // 심층 검토 보고서를 읽지 않는 호출은 `null`이다(ADR-0057).
      deepReviewUnknownCount: null,
    });
    expect(result.count).toBe(1);
    expect(result.unknownCount).toBeNull();
    expect(result.headline).toBe("의견등록 마감은 9월 20일이다");
    expect(result.tone).toBe("caution");
    expect(formatPreSpecCaution(result)).toBe("주의 1건 · 의견등록 마감은 9월 20일이다");
  });

  test("첨부 차단·실패만 있으면 건수를 더하고 첨부 문구를 쓴다", () => {
    const result = preSpecCautions({
      item: cautionItem({ document: { attachments: 5, "완료": 2, "대기": 0, "진행": 0, "차단": 2, "실패": 1 } }),
      verification: null,
      deepReviewUnknownCount: null,
    });
    expect(result.count).toBe(3);
    expect(result.unknownCount).toBeNull();
    expect(result.headline).toBe("첨부 차단 2 · 실패 1");
    expect(result.tone).toBe("caution");
    expect(formatPreSpecCaution(result)).toBe("주의 3건 · 첨부 차단 2 · 실패 1");
  });

  test("자동 준비 blocked와 심층 검토 미확인이 함께 있으면 사유 라벨과 미확인 수를 함께 말한다", () => {
    const result = preSpecCautions({
      item: cautionItem({
        auto_preparation_status: "blocked",
        auto_preparation_reason: "bundle_has_blocking_issues",
      }),
      verification: null,
      // 심층 검토 보고서를 읽어 얻은 실제 건수다.
      deepReviewUnknownCount: 1,
    });
    expect(result.count).toBe(1);
    expect(result.unknownCount).toBe(1);
    expect(result.headline).toBe("묶음에 차단 issue가 있습니다.");
    expect(result.tone).toBe("caution");
    expect(formatPreSpecCaution(result)).toBe("주의 1건 · 묶음에 차단 issue가 있습니다. · 미확인 1");
  });

  test("심층 검토 미확인만 있으면 주의는 0건이고 미확인 수만 말한다", () => {
    const result = preSpecCautions({
      item: cautionItem(),
      verification: verification([claim("c-1", "총 사업비는 12억원이다", "passed")]),
      // 개요 결과에는 더 이상 unknowns 텍스트가 없으므로 headline은 건수의
      // 출처가 되지 못한다 — 심층 검토 미확인은 건수만 말한다(ADR-0057).
      deepReviewUnknownCount: 2,
    });
    expect(result.count).toBe(0);
    expect(result.headline).toBeNull();
    expect(result.tone).toBe("none");
    expect(formatPreSpecCaution(result)).toBe("주의 없음 · 미확인 2");
  });

  test("심층 검토 보고서를 읽지 않았으면 미확인 0건으로 지어내지 않고 캡션을 내지 않는다", () => {
    const result = preSpecCautions({ item: cautionItem(), verification: null, deepReviewUnknownCount: null });
    expect(result.count).toBe(0);
    expect(result.unknownCount).toBeNull();
    expect(result.headline).toBeNull();
    expect(result.tone).toBe("none");
    expect(formatPreSpecCaution(result)).toBe("주의 없음");
  });
});
