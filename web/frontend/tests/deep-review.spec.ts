import { test, expect } from "@playwright/test";

test.describe("심층 검토 보고서 접근성·반응형 계약", () => {
  test.skip(true, "T7가 DeepReviewPage를 routes.tsx에 등록하고 #9/#11-14 fixture를 연결한 뒤 실행합니다.");

  test("키보드 focus, 좁은 화면, 긴 matrix containment", async ({ page }) => {
    await page.goto("/deep-reviews/fixture-review");
    await expect(page.getByRole("heading", { name: "심층 검토 보고서" })).toBeVisible();
    await page.getByRole("button", { name: /근거/ }).first().focus();
    await expect(page.getByRole("button", { name: /근거/ }).first()).toBeFocused();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await expect(page.locator("table").first()).toBeVisible();
  });
});
