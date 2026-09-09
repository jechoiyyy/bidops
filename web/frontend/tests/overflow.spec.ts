import { expect, test } from "@playwright/test";
import {
  expectNoHorizontalOverflow,
  installScreenFixtures,
  lifecycleVisualTargets,
  pages,
} from "./screen-fixtures";
import { mockPreSpecs } from "./api-mock";

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

// 사전규격 목록에서 심층 추적 승인 패널을 연 상태는 단순 goto만으로 도달할 수
// 없는 상호작용이라 별도 타깃으로 둔다(목록 타깃은 패널이 닫힌 기본 상태다).
test("pre-specs-tracking-panel 화면이 가로로 넘치지 않는다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");
  await expect(page.locator("h1").first()).toBeVisible();
  const trackedRow = page
    .locator('.pre-specs-list-pane [data-review-primitive="dense-list-row"]')
    .filter({ hasText: "안전한 문서 준비 사전규격" });
  await trackedRow.click();
  await page.getByRole("button", { name: "추적 선택 변경", exact: true }).click();
  await expect(page.locator("#pre-specs-tracking-target")).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expectNoHorizontalOverflow(page);
});
