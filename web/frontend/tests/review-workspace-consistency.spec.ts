import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlans, mockPreSpecs } from "./api-mock";

// 사용자가 두 페이지의 목록 크기를 같게 요청했다. 개별 화면이 넘치지 않는 것만
// 확인하면 한쪽이 고정 px이고 다른 쪽이 비율인 회귀를 놓치므로 함께 비교한다.
test("발주계획과 사전규격은 두 지원 폭에서 같은 38% 목록 폭을 사용한다", async ({ page }) => {
  await mockApi(page);
  await mockOrderPlans(page);
  await mockPreSpecs(page);

  for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/order-plans");
    await expect(page.locator(".c2l-row").first()).toBeVisible();
    const order = await page.locator(".c2l-list-pane").evaluate((pane) => ({
      width: pane.getBoundingClientRect().width,
      workspaceWidth: pane.parentElement!.getBoundingClientRect().width,
    }));

    await page.goto("/pre-specs");
    await expect(page.locator(".pre-specs-row").first()).toBeVisible();
    const preSpec = await page.locator(".pre-specs-list-pane").evaluate((pane) => ({
      width: pane.getBoundingClientRect().width,
      workspaceWidth: pane.parentElement!.getBoundingClientRect().width,
    }));

    expect(Math.abs(order.width - preSpec.width), `${viewport.width}px에서 두 목록 폭`).toBeLessThanOrEqual(1);
    expect(order.width / order.workspaceWidth).toBeCloseTo(0.38, 2);
    expect(preSpec.width / preSpec.workspaceWidth).toBeCloseTo(0.38, 2);
  }
});
