import { expect, test } from "@playwright/test";
import {
  expectNoHorizontalOverflow,
  installScreenFixtures,
  lifecycleVisualTargets,
  pages,
} from "./screen-fixtures";
import { mockApi, mockOrderPlanBulkTracking, mockOrderPlans, mockPreSpecs } from "./api-mock";
import { mockGoNoGo } from "./go-no-go-fixtures";
import { mockOpportunities } from "./opportunities-fixtures";

// 구조 층 — 지원 폭 두 곳(laptop 1280 · desktop 1440)에서 화면이 가로로 넘치지
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
  });
}

for (const target of lifecycleVisualTargets) {
  test(`${target.name} 화면이 가로로 넘치지 않는다`, async ({ page }) => {
    await target.setup(page);
    await page.goto(target.path);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectNoHorizontalOverflow(page);
  });
}

// 추적 결정은 대화상자가 아니라 우측 정보 영역 바닥의 인라인 폼이다
// (docs/0915_ui-redesign/spec.md §3.3). 폼이 실제로 그려지는 건(신규·미선택)을
// 골라야 사유 Selector·담당자 칸·저장 단추가 같은 줄에 들어가는지 잰다.
test("pre-specs-tracking-panel 화면이 가로로 넘치지 않는다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");
  await expect(page.locator("h1").first()).toBeVisible();
  const trackedRow = page
    .locator('.pre-specs-list-pane [data-review-primitive="dense-list-row"]')
    .filter({ hasText: "신규 지능형 행정 지원 사전규격" });
  await trackedRow.click();
  await expect(page.locator("#pre-specs-tracking-target .pre-spec-tracking-form")).toBeVisible();
  await expect(page.locator("#pre-specs-tracking-target")).toBeVisible();
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
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await expect(dialog.getByTestId("order-plan-bulk-preview")).toBeVisible();
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("화면 검증 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("합성 입력의 확인 화면 검증");
  await expect(dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true })).toBeEnabled();
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
  await page.goto("/pre-specs");
  const rows = page.locator('.pre-specs-list-pane [data-review-primitive="dense-list-row"]');
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
  await expect(page.getByText(/상세를 불러오지 못했습니다/)).toBeVisible();
  await expect(navigation).toContainText("1 / 1");
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("prespec-review-error.png") });
});

test("pre-specs 제외 확인 창과 전체 이력 필터가 지원 폭 안에 보인다", async ({ page }, testInfo) => {
  await mockPreSpecs(page);
  await page.goto('/pre-specs?workspace=all');
  await expect(page.getByRole('combobox', { name: '검토 포함 여부', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '검토 제외', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '검토 제외', exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('textbox', { name: /^담당자/ }).fill('화면 검증 담당자');
  await dialog.getByRole('textbox', { name: /^사유/ }).fill('긴 사전규격 제목과 검토 범위를 확인하고 목록에서 제외합니다.');
  await expect(dialog.getByRole('button', { name: '검토 제외', exact: true })).toBeEnabled();
  await expectNoHorizontalOverflow(page);
  const bounds = await dialog.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  await page.screenshot({ path: testInfo.outputPath('exclusion-dialog.png') });
});

async function expectSearchToolsBelowTabs(
  page: import("@playwright/test").Page,
  testInfo: import("@playwright/test").TestInfo,
  rowSelector: string,
  expectedChildren: string[],
) {
  await expect(page.locator(rowSelector).first()).toBeVisible();
  const metrics = await page.locator('[data-review-primitive="filter-bar"]').evaluate((bar) => {
    const line = bar.querySelector<HTMLElement>(".workspace-filter-line");
    const tools = bar.querySelector<HTMLElement>(".workspace-filter-tools");
    if (!line || !tools) throw new Error("workspace filter rows missing");
    return {
      lineBottom: line.getBoundingClientRect().bottom,
      toolsTop: tools.getBoundingClientRect().top,
      children: [...tools.children].map((child) => child.className),
    };
  });
  expect(metrics.toolsTop).toBeGreaterThanOrEqual(metrics.lineBottom - 1);
  for (const [index, className] of expectedChildren.entries()) {
    expect(metrics.children[index]).toContain(className);
  }
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("search-tools.png") });
}

test("[search-ux] 발주계획 도구가 탭 아래 필터·검색·회차 순으로 놓인다", async ({ page }, testInfo) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await expectSearchToolsBelowTabs(page, testInfo, ".c2l-row", ["workspace-advanced-toggle", "workspace-search-field", "c2l-filter-context-range"]);
});

test("[search-ux] 사전규격 도구가 탭 아래 필터·검색·회차·추가 조건 순으로 놓인다", async ({ page }, testInfo) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?workspace=all&sw_only=false");
  await expectSearchToolsBelowTabs(page, testInfo, ".pre-specs-row", ["workspace-advanced-toggle", "workspace-search-field", "pre-specs-filter-context-range", "astryx-field"]);
});

test("[search-ux] 사업 추적 도구가 탭 아래 필터·검색 순으로 놓인다", async ({ page }, testInfo) => {
  await mockApi(page);
  await mockOpportunities(page);
  await page.goto("/opportunities");
  await expectSearchToolsBelowTabs(page, testInfo, ".opportunity-table-scroll tbody tr", ["workspace-advanced-toggle", "workspace-search-field"]);
});

test("[search-ux] Go/No-Go 도구는 탭 아래 검색만 둔다", async ({ page }, testInfo) => {
  await mockApi(page);
  await mockGoNoGo(page);
  await page.goto("/go-no-go");
  await expectSearchToolsBelowTabs(page, testInfo, ".gng-row", ["workspace-search-field"]);
});
