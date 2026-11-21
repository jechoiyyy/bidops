import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlans, mockPreSpecs } from "./api-mock";
import { mockOpportunities } from "./opportunities-fixtures";

for (const [path, mock] of [
  ["/order-plans", mockOrderPlans], ["/pre-specs", mockPreSpecs], ["/opportunities", mockOpportunities],
] as const) {
  test(`${path} 레코드 헤더에는 수집 현황과 목록 설명이 없다`, async ({ page }) => {
    await mockApi(page);
    await mock(page);
    await page.goto(path);
    await expect(page.locator(".review-split-workspace")).toBeVisible();
    const header = page.locator("header.topbar");
    await expect(header.locator("[data-testid='collection-status']")).toHaveCount(0);
    await expect(header.getByRole("button", { name: "목록 기준" })).toHaveCount(0);
  });
}
