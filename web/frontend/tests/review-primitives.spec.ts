import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlans, mockPreSpecs } from "./api-mock";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("검토 대기열은 공통 필터·밀집 행·sticky 결정 헤더를 사용한다", async ({ page, viewport }) => {
  test.skip((viewport?.width ?? 0) <= 900, "좁은 화면의 목록·상세 전환은 별도 회귀에서 확인한다");
  await page.goto("/queue");

  const filterBar = page.locator('[data-review-primitive="filter-bar"]');
  await expect(filterBar).toBeVisible();
  await expect(filterBar.locator('[data-review-primitive="filter-selector"]')).toHaveCount(5);
  await expect(filterBar.locator('[data-review-primitive="text-input"]')).toHaveCount(1);
  await expect(page.locator('[data-review-primitive="dense-list"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="dense-list-row"]')).not.toHaveCount(0);
  await expect(page.locator('[data-review-primitive="sticky-decision-header"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="segmented-control"]')).toBeVisible();

  const headerPosition = await page.locator('[data-review-primitive="sticky-decision-header"]').evaluate((element) => getComputedStyle(element).position);
  expect(headerPosition).toBe("sticky");

  const rows = page.locator('[data-review-primitive="dense-list-row"]');
  await rows.nth(1).focus();
  await page.keyboard.press("Enter");
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");

  const grade = page.getByRole("combobox", { name: "등급", exact: true });
  await grade.click();
  await page.getByRole("option", { name: "우선 검토", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("grade")).toBe("우선 검토");
  const reset = page.getByRole("button", { name: "필터 1개 해제", exact: true });
  await expect(reset).toBeVisible();
  await reset.click();
  await expect(page).not.toHaveURL(/grade=/);
});

test("발주계획 C-2는 공통 필터·목록·상세·상태·결정 action을 한 화면에서 조합한다", async ({ page, viewport }) => {
  test.skip((viewport?.width ?? 0) <= 900, "좁은 화면의 목록·상세 전환은 order-plans 회귀에서 확인한다");
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  await expect(page.locator('[data-review-primitive="filter-bar"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="text-input"]')).not.toHaveCount(0);
  await expect(page.locator('[data-review-primitive="dense-list"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="dense-list-row"]')).toHaveCount(2);
  await expect(page.locator('[data-review-primitive="split-workspace"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="sticky-decision-header"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="status"]')).not.toHaveCount(0);
  await expect(page.locator('[data-review-primitive="value"]')).not.toHaveCount(0);
  await expect(page.locator('[data-review-primitive="decision-action"]')).toHaveCount(2);
  const disabledReasons = page.getByText("담당자 claimed name을 입력하면 저장할 수 있습니다.", { exact: true });
  await expect(disabledReasons).toHaveCount(2);
  await expect(page.getByRole("button", { name: "저장", exact: true })).toHaveAttribute("aria-describedby", /review-decision-reason-/);

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("좁은 화면에서 검토 대기열은 목록과 상세를 한 번에 하나만 보여준다", async ({ page, viewport }) => {
  test.skip((viewport?.width ?? 0) > 900, "좁은 화면 전용 회귀");
  await page.goto("/queue");

  const workspace = page.locator('[data-review-primitive="split-workspace"]');
  await expect(workspace).toHaveAttribute("data-mobile-view", "list");
  await expect(page.locator(".queue-list-pane")).toBeVisible();
  await expect(page.locator(".queue-detail-pane")).toBeHidden();

  await page.locator('[data-review-primitive="dense-list-row"]').first().click();
  await expect(workspace).toHaveAttribute("data-mobile-view", "detail");
  await expect(page.locator(".queue-list-pane")).toBeHidden();
  await expect(page.locator('[data-review-primitive="sticky-decision-header"]')).toBeVisible();

  await page.getByRole("link", { name: "목록으로" }).click();
  await expect(workspace).toHaveAttribute("data-mobile-view", "list");
  await expect(page.locator(".queue-list-pane")).toBeVisible();
  await expect(page.locator(".queue-detail-pane")).toBeHidden();
});

test("사전규격 상태 그룹은 공통 collapsible primitive로 0건·미시작 상태를 보존한다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");

  const groups = page.locator('[data-review-primitive="state-group"]');
  await expect(groups).toHaveCount(11);
  await expect(page.getByRole("button", { name: /^사람 검토 필요/ })).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("button", { name: /^실패/ })).toHaveAttribute("aria-expanded", "true");
  const notStarted = page.getByRole("button", { name: /^개요 검토 미시작/ });
  await expect(notStarted).toHaveAttribute("aria-expanded", "false");
  await notStarted.click();
  await expect(notStarted).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText("개요 검토 미시작", { exact: true })).toBeVisible();
});
