import { expect, test } from "@playwright/test";
import { mockApi, mockRealCompany } from "./api-mock";

// /company가 위키를 열므로 옛 사실 그래프 본문의 그룹·수치·버전·표현·복사·배치 검사는 제거했다.
// 사이드바의 회사 이름과 건수는 계속 사실 그래프 API를 사용한다.
test("T8: 사이드바 회사 근거는 /company로 가고 건수와 워크스페이스 이름을 API에서 읽는다", async ({ page }) => {
  await mockApi(page);
  await mockRealCompany(page);
  await page.goto("/company");
  const sidebar = page.locator("aside.sidebar");
  const link = sidebar.getByRole("link", { name: "회사 근거", exact: true });
  await expect(link).toHaveAttribute("href", "/company");
  await expect(link).toHaveAttribute("aria-current", "page");
  await expect(link.locator(".sidebar-item-count")).toHaveText("6");
  await expect(sidebar.locator(".sidebar-brand strong")).toHaveText("루트랩");
  // 2026-11-19 최종 시안: 머리글자 아이콘 대신 제품 이름 + 회사 이름이다.
  await expect(sidebar.locator(".sidebar-brand-product")).toHaveText("BidOps");
  // 같은 이름의 항목이 하나뿐이다(설정 아래 판정 기준 `/profile`은 사이드바 항목이 아니다).
  await expect(sidebar.getByRole("link", { name: "회사 근거", exact: true })).toHaveCount(1);

  await page.goto("/briefing");
  await sidebar.getByRole("link", { name: "회사 근거", exact: true }).click();
  await expect(page).toHaveURL(/\/company$/);
  await expect(page.getByTestId("page-header-eyebrow")).toHaveText("회사 근거");
});

test("등록 회사나 활성 버전이 없으면 사이드바에 건수가 없어요", async ({ page }) => {
  await mockApi(page);
  for (const options of [{ notRegistered: true }, { noActiveVersion: true }]) {
    await mockRealCompany(page, options);
    await page.goto("/company");
    const sidebar = page.locator("aside.sidebar");
    await expect(page.getByRole("group", { name: "회사 근거 보기" })).toBeVisible();
    if (options.notRegistered) await expect(sidebar.locator(".sidebar-brand strong")).toHaveText("BidOps");
    await expect(sidebar.getByRole("link", { name: "회사 근거", exact: true }).locator(".sidebar-item-count")).toHaveCount(0);
  }
});
