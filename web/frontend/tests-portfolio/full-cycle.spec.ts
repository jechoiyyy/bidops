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
  await page.goto("/pre-specs"); // default view: 검토할 항목, deadline current
  await expect(page.getByText("검토할 항목 37건", { exact: false })).toBeVisible({ timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${shots}/${info.project.name}-1-pre-specs-list.png` });
});

test("detail with overview (검토할 항목 4190, no engine run)", async ({ page }, info) => {
  await page.goto("/pre-specs/4190");
  await expect(page.getByText("주요 과업", { exact: false }).first()).toBeVisible({ timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${shots}/${info.project.name}-2-detail-overview-4190.png`, fullPage: true });
});

test("analysis result (검토할 항목 4186, imported engine run)", async ({ page }, info) => {
  await page.goto("/pre-specs/4186");
  await expect(page.getByRole("region", { name: "한눈에" })).toBeVisible({ timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${shots}/${info.project.name}-3-detail-analysis-4186.png` });
});
