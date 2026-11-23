import { expect, test } from "@playwright/test";
import {
  expectNoHorizontalOverflow,
  installScreenFixtures,
  lifecycleVisualTargets,
  pages,
} from "./screen-fixtures";
import { mockApi, mockOrderPlanBulkTracking, mockOrderPlans, mockPreSpecs, preSpecListBody, visualPreSpecItems } from "./api-mock";
import { mockWiki } from "./fixtures/company-wiki";
import { mockGoNoGo } from "./go-no-go-fixtures";
import { mockOpportunities } from "./opportunities-fixtures";

// 구조 층 — 지원하는 세 해상도에서 화면이 가로로 넘치지
// 않는지만 본다. 색이나 배치가 바뀌어도 여기는 통과해야 하고, 여기가 깨지면
// 폭 안에 안 들어가는 요소가 생긴 것이다. 픽셀 대조와 달리 기준 이미지가 없다.
//
// 세 층의 구분과 게이트는 `docs/standards.md`에 있다.

installScreenFixtures();

for (const target of pages) {
  test(`${target.name} 화면이 가로로 넘치지 않는다`, async ({ page }) => {
    await page.goto(target.path);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectNoHorizontalOverflow(page);
    if (target.name === "judgment-detail") {
      const canvas = page.locator(".page-canvas");
      await expect(canvas).toHaveAttribute("data-canvas", "flush");
      const detail = canvas.getByRole("region", { name: "공고 상세" });
      const summary = detail.getByRole("region", { name: "공고 요약" });
      await expect(summary).toBeVisible();
      await expect(detail.locator(".workbench-record-rail")).toHaveCount(0);
      const columns = await summary.locator("dl").evaluate((list) =>
        getComputedStyle(list).gridTemplateColumns.split(" ").length,
      );
      expect(columns).toBe(3);
      const list = canvas.getByRole("complementary", { name: "회차 공고 목록" });
      const table = list.getByRole("table", { name: "회차 공고 목록" });
      await expect(table.getByRole("columnheader")).toHaveText(["사업명", "상태", "마감"]);
      const deadlines = table.locator("tbody td .workbench-deadline");
      expect(await deadlines.count()).toBeGreaterThan(0);
      expect(await deadlines.evaluateAll((values) => values.every((value) => {
        const cell = value.closest("td")!;
        return getComputedStyle(value).whiteSpace === "nowrap"
          && value.getBoundingClientRect().right <= cell.getBoundingClientRect().right + 1;
      }))).toBe(true);
      expect(await list.locator(".record-table-viewport").evaluate((viewport) =>
        viewport.scrollWidth - viewport.clientWidth,
      )).toBeLessThanOrEqual(1);
      const [canvasBox, listBox, detailBox] = await Promise.all([canvas.boundingBox(), list.boundingBox(), detail.boundingBox()]);
      expect(listBox!.width / canvasBox!.width).toBeCloseTo(0.4, 2);
      expect(listBox!.x).toBeCloseTo(canvasBox!.x, 0);
      expect(listBox!.x + listBox!.width).toBeCloseTo(detailBox!.x, 0);
      expect(detailBox!.x + detailBox!.width).toBeCloseTo(canvasBox!.x + canvasBox!.width, 0);
    }
    const admin = page.locator(".workbench-admin");
    if (await admin.count()) {
      const nav = admin.getByRole("navigation", { name: /^(판정 기준|실행 상태) 구역$/ });
      const [navBox, mainBox] = await Promise.all([
        nav.boundingBox(),
        admin.locator(".workbench-admin-main").boundingBox(),
      ]);
      expect(navBox!.x + navBox!.width).toBeCloseTo(mainBox!.x, 0);
      expect(mainBox!.x + mainBox!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
    }
  });
}

for (const target of lifecycleVisualTargets) {
  test(`${target.name} 화면이 가로로 넘치지 않는다`, async ({ page }) => {
    await target.setup(page);
    await page.goto(target.path);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectNoHorizontalOverflow(page);
    if (target.name.startsWith("bid-delta-")) {
      const workspace = page.locator(".bid-delta-workspace");
      const [frame, reading, decision] = await Promise.all([
        workspace.boundingBox(),
        workspace.locator(".bid-delta-reading").boundingBox(),
        workspace.locator(".bid-delta-decision-pane").boundingBox(),
      ]);
      expect(reading!.width / frame!.width).toBeCloseTo(0.60, 2);
      expect(decision!.width / frame!.width).toBeCloseTo(0.40, 2);
      expect(reading!.x + reading!.width).toBeCloseTo(decision!.x, 0);
    }
  });
}

test("사전규격의 당일 마감과 예산이 셀 안에 들어간다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.clock.setFixedTime(new Date("2026-11-24T09:00:00+09:00"));
  const item = {
    ...visualPreSpecItems[0],
    deadline_at: "2026-11-24T23:59:00+09:00",
    budget: 52_104_000,
  };
  await page.route(/\/api\/pre-specs(?:\?|$)/, (route) => {
    const search = new URL(route.request().url()).searchParams;
    const items = [item];
    return route.fulfill({ json: preSpecListBody({
      items, total: items.length, limit: Number(search.get("limit") ?? 50), offset: 0,
      statusItems: items, unscoped: items, search,
    }) });
  });

  await page.goto("/pre-specs?workspace=all&sw_only=false");
  const list = page.locator(".pre-specs-list-pane");
  const row = list.getByRole("row", { name: item.title!, exact: true });
  const deadline = row.locator(".pre-specs-row-date");
  const budget = row.locator(".pre-specs-row-budget");
  await expect(deadline).toHaveText("오늘 23:59 · 11.24");
  await expect(budget).toHaveText("5,210.4만원");
  await page.evaluate(() => document.fonts.ready);

  const value = deadline.locator(".workbench-deadline");
  await expect(value).toHaveCSS("font-size", "14px");
  await expect(value).toHaveCSS("font-weight", "700");
  await expect(value).toHaveCSS("white-space", "nowrap");
  for (const cell of [deadline, budget]) {
    const geometry = await cell.evaluate((element) => ({
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
      right: element.getBoundingClientRect().right,
      listRight: element.closest(".pre-specs-list-pane")!.getBoundingClientRect().right,
    }));
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
    expect(geometry.right).toBeLessThanOrEqual(geometry.listRight);
  }
  const title = await row.locator(".record-table-title").boundingBox();
  expect(title!.width).toBeGreaterThanOrEqual(180);
});

// 추적 시작이 가능한 신규·미선택 건을 골라 공용 결정 띠에 조작이 모두 들어가는지 확인한다.
test("pre-specs-tracking-panel 화면이 가로로 넘치지 않는다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");
  await expect(page.locator("h1").first()).toBeVisible();
  const trackedRow = page.getByRole("table", { name: "사전규격", exact: true })
    .getByRole("row", { name: "신규 지능형 행정 지원 사전규격", exact: true });
  await trackedRow.click();
  const decision = page.locator("#pre-specs-tracking-target.workbench-decision");
  await expect(decision).toBeVisible();
  await expect(decision.getByRole("button", { name: "추적 시작하기", exact: true })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expectNoHorizontalOverflow(page);
});

test("LS-BT 발주계획 선택과 확인 대화상자가 지원 폭 안에 보인다", async ({ page }, testInfo) => {
  await mockOrderPlans(page);
  await mockOrderPlanBulkTracking(page, "all-eligible");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().getByRole("checkbox").check();
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 1건");
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("order-plan-selection.png") });
  await page.getByRole("button", { name: "일괄 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  // 한 창 흐름: 열리면 대상 확인이 끝나 요약 줄이 채워진다. 세부를 펼친 가장 긴 상태를 잰다.
  await expect(dialog.getByTestId("order-plan-bulk-summary")).toContainText("추적 시작 1건 중 1건");
  await dialog.getByRole("button", { name: "세부", exact: true }).click();
  await expect(dialog.getByTestId("order-plan-bulk-preview")).toBeVisible();
  await dialog.getByRole("textbox", { name: "담당자 이름 · 감사 표식 (필수)" }).fill("화면 검증 담당자");
  await expect(dialog.getByRole("button", { name: "1건 추적 시작", exact: true })).toBeEnabled();
  const bounds = await dialog.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("order-plan-bulk-confirmation.png") });
});

test("LS-PN 선택 도구와 상세 오류 순회가 지원 폭 안에 보인다", async ({ page }, testInfo) => {
  await mockPreSpecs(page);
  // S3(2026-09-22 규칙): 기본 보기의 fixture 행이 추적 결정으로 빠져 0건이라, 검토할 항목이 남는 `sw_only=false`로 연다.
  await page.goto("/pre-specs?sw_only=false");
  const rows = page.locator(".pre-specs-list-pane tbody > tr.pre-specs-row");
  await rows.first().getByRole("checkbox").check();
  const toolbar = page.locator(".pre-specs-selection-toolbar");
  await expect(toolbar).toContainText("선택 1건");
  await expect(toolbar.getByRole("button", { name: "선택 항목 검토", exact: true })).toBeEnabled();
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("prespec-selection.png") });

  await toolbar.getByRole("button", { name: "선택 항목 검토", exact: true }).click();
  const navigation = page.getByRole("navigation", { name: "사전규격 선택 순회" });
  await expect(navigation).toContainText("1 / 1");
  await expect(navigation.getByRole("button", { name: "이전 선택 사전규격" })).toBeDisabled();
  await expect(navigation.getByRole("button", { name: "다음 선택 사전규격" })).toBeDisabled();
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("prespec-review.png") });

  await page.route("**/api/notices/*", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "temporarily_unavailable", message: "unavailable", details: null } }),
    });
  });
  await page.reload();
  await expect(page.getByText(/상세를 불러오지 못했어요/)).toBeVisible();
  await expect(navigation).toContainText("1 / 1");
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("prespec-review-error.png") });
});

test("pre-specs 제외 확인 창과 전체 이력 필터가 지원 폭 안에 보인다", async ({ page }, testInfo) => {
  await mockPreSpecs(page);
  await page.goto('/pre-specs?workspace=all');
  const toggle = page.getByRole('button', { name: '상세 필터', exact: true });
  await toggle.click();
  const filters = page.getByRole('region', { name: '상세 필터', exact: true });
  await expect(filters.getByRole('combobox', { name: '검토 포함 여부', exact: true })).toBeInViewport();
  await expectNoHorizontalOverflow(page);
  await filters.getByRole('button', { name: '필터 접기', exact: true }).click();
  await page.getByRole('button', { name: '검토 제외', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '선택한 사전규격 검토 제외', exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('textbox', { name: '담당자 이름 · 감사 표식 (필수)' }).fill('화면 검증 담당자');
  await dialog.getByRole('combobox', { name: '제외 사유 (필수)' }).click();
  await page.getByRole('option', { name: '기타 · 직접 입력', exact: true }).click();
  await dialog.getByRole('textbox', { name: '사유 직접 입력' }).fill('긴 사전규격 제목과 검토 범위를 확인하고 목록에서 제외해요.');
  await expect(dialog.getByRole('button', { name: '1건 검토 제외', exact: true })).toBeEnabled();
  await expectNoHorizontalOverflow(page);
  const bounds = await dialog.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  await page.screenshot({ path: testInfo.outputPath('exclusion-dialog.png') });
});

async function expectSearchToolsRightOfTabs(
  page: import("@playwright/test").Page,
  testInfo: import("@playwright/test").TestInfo,
  rowSelector: string,
  expectedChildren: string[],
) {
  await expect(page.locator(rowSelector).first()).toBeVisible();
  const metrics = await page.locator('header.topbar [data-review-primitive="filter-bar"]').evaluate((bar) => {
    const line = bar.querySelector<HTMLElement>(".workspace-filter-line");
    const tools = bar.querySelector<HTMLElement>(".workspace-filter-tools");
    if (!line || !tools) throw new Error("workspace filter rows missing");
    const lineBox = line.getBoundingClientRect();
    const toolsBox = tools.getBoundingClientRect();
    return {
      sameRow: toolsBox.top < lineBox.bottom && toolsBox.bottom > lineBox.top,
      toolsRightOfTabs: toolsBox.left >= lineBox.right - 1,
      toolsRight: toolsBox.right,
      barRight: bar.getBoundingClientRect().right,
      children: [...tools.children].map((child) => child.className),
    };
  });
  expect(metrics.sameRow).toBe(true);
  expect(metrics.toolsRightOfTabs).toBe(true);
  expect(metrics.toolsRight).toBeLessThanOrEqual(metrics.barRight + 1);
  expect(metrics.children).toHaveLength(expectedChildren.length);
  for (const [index, className] of expectedChildren.entries()) {
    expect(metrics.children[index]).toContain(className);
  }
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("search-tools.png") });
}

test("[search-ux] 발주계획 탭 줄 오른쪽에 적용 필터·필터·검색이 순서대로 놓인다", async ({ page }, testInfo) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await expectSearchToolsRightOfTabs(page, testInfo, ".c2l-row", [
    "workbench-filter-tokens", "workspace-advanced-toggle", "workspace-search-field",
  ]);
});

test("[search-ux] 사전규격 필터·검색은 조회 도구 줄에, 날짜·회차·추가 조건은 상세 필터에 있다", async ({ page }, testInfo) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false&observed_from=2026-08-01");
  await expectSearchToolsRightOfTabs(page, testInfo, ".pre-specs-row", [
    "workbench-filter-tokens", "workspace-advanced-toggle", "workspace-search-field",
  ]);
  const tools = page.locator(".pre-specs-filter-tools");

  await tools.getByRole("button", { name: "상세 필터", exact: true }).click();
  const filters = page.getByRole("region", { name: "상세 필터", exact: true });
  const range = filters.locator(".workspace-filter-group").filter({
    has: page.getByRole("heading", { name: "조회 범위", exact: true }),
  });
  await expect(range.getByRole("combobox", { name: "관측 시작일" })).toBeVisible();
  await expect(range.getByRole("combobox", { name: "관측 종료일" })).toBeVisible();
  await expect(range.getByRole("combobox", { name: "검토 포함 여부", exact: true })).toBeVisible();
  await expect(range.getByRole("button", { name: "수집 회차" })).toBeVisible();
  await expect(filters.getByRole("combobox", { name: "마감 상태", exact: true })).toBeVisible();
  const sections = filters.locator(".workspace-filter-advanced > section > h3");
  await expect(sections).toHaveText(["조회 범위", "개요 검토", "추적·일정"]);
  const dateBounds = await range.evaluate((group) => {
    const dates = [...group.querySelectorAll(".pre-specs-observation-date")];
    const bounds = group.getBoundingClientRect();
    return dates.map((date) => {
      const box = date.getBoundingClientRect();
      return box.left >= bounds.left - 1 && box.right <= bounds.right + 1;
    });
  });
  expect(dateBounds).toEqual([true, true]);
  await expectNoHorizontalOverflow(page);
  await expect.poll(() => filters.locator(".workspace-filter-advanced").evaluate((grid) => grid.scrollWidth - grid.clientWidth))
    .toBeLessThanOrEqual(1);
});

test("[search-ux] 사업 추적 도구가 패널 헤더 탭 줄 오른쪽에 필터·검색 순으로 놓인다", async ({ page }, testInfo) => {
  await mockApi(page);
  await mockOpportunities(page);
  await page.goto("/opportunities");
  await expectSearchToolsRightOfTabs(page, testInfo, ".opportunity-table-scroll tbody tr", ["workspace-advanced-toggle", "workspace-search-field"]);
});

test("[search-ux] Go/No-Go 도구는 패널 헤더 탭 줄 오른쪽에 검색만 둔다", async ({ page }, testInfo) => {
  await mockApi(page);
  await mockGoNoGo(page);
  await page.goto("/go-no-go");
  await expectSearchToolsRightOfTabs(page, testInfo, ".gng-row", ["workspace-search-field"]);
});

test("회사 위키에서 긴 실적명과 본문이 목록·상세 폭 안에 들어간다", async ({ page }) => {
  await mockWiki(page);
  await page.goto("/company?view=portfolio&project=P2026-01");
  await page.getByText("위키 원문 보기", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "근거 자료" })).toBeVisible();
  const list = await page.locator(".wiki-list").boundingBox();
  const split = await page.locator(".wiki-split").boundingBox();
  expect(list!.width / split!.width).toBeCloseTo(0.38, 2);
  for (const pane of [".wiki-list", ".wiki-detail"]) {
    expect(await page.locator(pane).evaluate(node => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  }
  await expectNoHorizontalOverflow(page);
});
