import { expect, test } from "@playwright/test";

const shots = "/Users/temp/orca/bidops-portfolio-build/docs/validation-runs/20261124-portfolio-full-cycle/shots";
const errors: string[] = [];
test.beforeEach(({ page }) => {
  page.on("pageerror", (error) => errors.push(error.message));
});
test.afterEach(() => {
  expect(errors, "page errors").toEqual([]);
});

test("검토할 항목 list", async ({ page }, info) => {
  await page.goto("/pre-specs?deadline_scope=passed"); // all 47 review items are past the opinion deadline in this snapshot
  await expect(page.getByText("검토할 항목 47건", { exact: false })).toBeVisible({ timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${shots}/${info.project.name}-1-pre-specs-list.png` });
});

test("detail with overview (untracked 721)", async ({ page }, info) => {
  await page.goto("/pre-specs/721");
  await expect(page.getByText("주요 과업", { exact: false }).first()).toBeVisible({ timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${shots}/${info.project.name}-2-detail-overview-721.png`, fullPage: true });
});

test("analysis result (tracked 4186, imported engine run)", async ({ page }, info) => {
  await page.goto("/pre-specs/4186");
  await expect(page.locator("#pa-summary")).toBeVisible({ timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${shots}/${info.project.name}-3-detail-analysis-4186.png` });
});
