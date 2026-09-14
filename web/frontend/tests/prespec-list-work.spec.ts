import { expect, test, type Page } from "@playwright/test";
import {
  mockApi,
  mockPreSpecMatrix,
  mockPreSpecs,
  overviewCompletedRunFixture,
  overviewEnvelopeFixture,
} from "./api-mock";

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
      };
    });
    await route.fulfill({
      json: {
        items,
        total,
        limit,
        offset,
        overview_status_counts: [{ status: "completed", count: total }],
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

test("자동 준비 필터는 서버 질의에 실리고 추적 결정 대기는 페이지 한정임을 밝힌다", async ({ page }) => {
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

  // 추적 결정 대기는 서버 인자가 아니므로 질의에 실리지 않고 고지만 남는다.
  await page.goto("/pre-specs?tracking_decision=pending&sw_only=false");
  await expect(page.locator(".pre-specs-grade-filter-note")).toContainText("추적 결정 필터는 불러온 페이지에만 적용됩니다");
  expect(queries.at(-1)?.has("tracking_decision")).toBe(false);

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
    .toHaveAttribute("href", "/pre-specs?auto_preparation_status=deep_review_ready_for_click&sw_only=false&sort=deadline");
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
    }));
    await route.fulfill({ json: { items, total, limit, offset, overview_status_counts: [{ status: "completed", count: total }] } });
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
  await page.getByRole("option", { name: "신규", exact: true }).click();
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
      };
    });
    await route.fulfill({ json: { items, total, limit, offset, overview_status_counts: [{ status: "completed", count: total }] } });
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
  await page.getByRole("option", { name: "추적", exact: true }).click();
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
  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await rows.nth(1).getByRole("checkbox").check();
  await rows.first().getByRole("checkbox").check();
  await page.getByRole("button", { name: "선택 항목 검토", exact: true }).click();
  await expect(page).toHaveURL(/\/pre-specs\/992\?.*selection_review=[0-9a-f-]+/);
  await expect(page).toHaveURL(/selection_review=/);
});

for (const sort of ["published", "deadline"] as const) {
  test(`PN-01 cross-page metadata preserves timezone ties microseconds and nulls (${sort})`, async ({ page }, testInfo) => {
    await mockApi(page);
    const selected = [199, 201, 202, 204];
    const fillers = Array.from({ length: 204 }, (_, index) => index + 1).filter((id) => !selected.includes(id));
    const expected = sort === "published" ? [199, 202, 201, 204] : [199, 201, 202, 204];
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
        ...(timestamps[noticePk as keyof typeof timestamps] ?? {
          published_at: "2026-09-01T00:00:00Z", deadline_at: "2026-10-01T00:00:00Z",
        }),
      }));
      await route.fulfill({ json: { items, total: 204, limit, offset, overview_status_counts: [{ status: "completed", count: 204 }] } });
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
    await expect(page).toHaveURL(/\/pre-specs\/199\?.*selection_review=/);
    const token = new URL(page.url()).searchParams.get("selection_review");
    const snapshot = await page.evaluate((reviewToken) => {
      const raw = sessionStorage.getItem(`bidops.pre-specs.review.v1.${reviewToken}`);
      return raw ? JSON.parse(raw) : null;
    }, token);
    expect(snapshot.orderedNoticeIds).toEqual(expected);
    expect(snapshot.entryNoticeId).toBe(199);
    const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
    await expect(navigation).toContainText("1 / 4");
    await expect(navigation.getByRole("button", { name: "이전 선택 사전규격" })).toBeDisabled();
    await expect(navigation.getByRole("button", { name: "다음 선택 사전규격" })).toBeEnabled();
    await page.screenshot({ path: testInfo.outputPath(`cross-page-${sort}.png`) });
  });
}

test("PN-03 선택 행의 상세 링크는 같은 순회 index를 시작하고 미선택 행은 단건 URL을 쓴다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await rows.nth(0).getByRole("checkbox").check();
  await rows.nth(1).getByRole("checkbox").check();
  await rows.nth(1).click();
  const selectedDetail = page.getByRole("link", { name: "상세 검토 열기 →", exact: true });
  await expect(selectedDetail).toHaveAttribute("href", /\/pre-specs\/992\?.*sw_only=false/);
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
  await expect(page).toHaveURL(/\/pre-specs\?sw_only=false/);
  const returnedRows = page.locator(".pre-specs-row");
  await expect(returnedRows.nth(1)).toHaveAttribute("aria-current", "true");
  await expect(returnedRows.nth(0).getByRole("checkbox")).toBeChecked();
  await expect(returnedRows.nth(1).getByRole("checkbox")).toBeChecked();
  await returnedRows.nth(2).click();
  const unselectedDetail = page.getByRole("link", { name: "상세 검토 열기 →", exact: true });
  await expect(unselectedDetail).toHaveAttribute("href", /\/pre-specs\/993\?.*sw_only=false/);
  await unselectedDetail.click();
  await expect(page).toHaveURL(/\/pre-specs\/993\?.*sw_only=false(?!.*selection_review)/);
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
  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await rows.nth(1).click();
  await rows.nth(1).getByRole("checkbox").check();
  await page.getByRole("button", { name: "추적 선택 변경", exact: true }).click();
  const dialog = page.getByRole("dialog");
  const actor = dialog.getByRole("textbox", { name: "담당자 이름 (필수)" });
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
      .find((candidate) => candidate.textContent?.trim() === "상세 검토 열기 →") as HTMLAnchorElement | undefined;
    link?.click();
  });
  const detailGuard = page.getByRole("alertdialog");
  await expect(detailGuard).toBeVisible();
  await detailGuard.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(page).toHaveURL(beforeUrl);
  await expect(actor).toHaveValue("guard 취소 담당자");
  await expect(actor).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(page.locator(".pre-specs-dialog-guard")).toBeVisible();
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");
  await page.locator(".pre-specs-dialog-guard").getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(actor).toHaveValue("guard 취소 담당자");
});

test("LS-06 pager guard 취소는 경계 URL·active·check·입력을 보존한다", async ({ page }) => {
  await mockApi(page);
  await mockPagedPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-row");
  await rows.first().click();
  await rows.first().getByRole("checkbox").check();
  await page.getByRole("button", { name: "추적 선택 변경", exact: true }).click();
  const dialog = page.getByRole("dialog");
  const actor = dialog.getByRole("textbox", { name: "담당자 이름 (필수)" });
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
  await expect(page.locator(".pre-specs-detail")).toBeVisible();
  // 결과 본문 구역이 둘이면 같은 주장이 두 번 보인다(ADR-0055 D7).
  await expect(page.locator(".pre-specs-overview-section.is-result")).toHaveCount(1);
  // 결과 머리줄이 이미 첫 주장을 말하므로 `문서 근거` 목록은 그것을 다시 적지 않는다.
  const firstClaim = overviewCompletedRunFixture.result!.business_overview[0].text;
  await expect(page.locator(".pre-specs-overview").getByText(firstClaim, { exact: false })).toHaveCount(1);
  // 구역 밖까지 넓혀, 미확인 목록이 탭 안에서 두 번 나오지 않는지도 본다(ADR-0055 D7).
  // 접힌 이력 안의 과거 결과는 그 회차의 내용을 갖는 것이 정상이다. 중복이란
  // 한 번에 **보이는** 자리에서 같은 문장을 두 번 읽는 것을 말한다.
  const unknowns = overviewCompletedRunFixture.result!.unknowns;
  if (unknowns.length > 0) {
    const visible = page.locator(".pre-specs-detail-pane")
      .getByText(unknowns[0], { exact: false })
      .locator("visible=true");
    await expect(visible).toHaveCount(1);
  }
  // 이전 결과가 실제로 한 건 그려진 상태여야 이 검사가 의미를 갖는다.
  await expect(page.getByText("이전 개요 결과 1건", { exact: true })).toBeVisible();
  // 근거 링크가 가리키는 anchor id는 문서 안에서 유일해야 한다 — 이력까지
  // anchor를 달면 같은 id가 둘이 되고 근거 링크가 엉뚜곳으로 뛰다.
  const anchorIds = await page.evaluate(() =>
    [...document.querySelectorAll('[id^="claim-"]')].map((node) => node.id));
  expect(anchorIds.length).toBeGreaterThan(0);
  expect(anchorIds.length).toBe(new Set(anchorIds).size);
});
