import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlans } from "./api-mock";

const shellRoutes = [
  "/",
  "/queue",
  "/judgments",
  "/reviews",
  "/runs",
  "/attachments",
  "/profile",
  "/metrics",
  "/quality-gates",
  "/quality-gates?gate=gate-model-comparison",
  "/policies",
  "/operations",
  "/audit",
  "/criteria",
  "/run-status",
  "/opportunities",
  "/go-no-go",
  "/order-plans",
  "/order-plans/101",
  "/pre-specs",
  "/pre-specs/991",
  "/opportunities/202",
  "/opportunities/501",
  "/deep-reviews/fixture-review",
  "/opportunities/501/bid-delta",
];

test.beforeEach(async ({ page }) => {
  await page.route("**://fonts.googleapis.com/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "text/css", body: "" });
  });
  await page.route("**://fonts.gstatic.com/**", async (route) => {
    await route.fulfill({ status: 204, body: "" });
  });
  await mockApi(page);
});

test("모든 시안 대상 route가 공통 bidops light 셸 안에서 렌더링된다", async ({ page }) => {
  for (const route of shellRoutes) {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    const shell = page.locator(".app-shell");
    await expect(shell).toHaveAttribute("data-astryx-theme", "bidops");
    await expect(shell).toHaveAttribute("data-theme", "light");
    await expect(shell.locator('[data-shell-region="sidebar"]')).toBeAttached();
    await expect(shell.locator('[data-shell-region="topbar"]')).toBeAttached();
    await expect(shell.locator('[data-shell-region="canvas"]')).toBeAttached();
    // 상단바는 제목을 반복하지 않고 현재 위치를 보여 준다. 화면 이름 칸이
    // `<h1>`이므로 문서의 level 1 제목은 하나로 유지된다.
    await expect(shell.locator("header.topbar nav[aria-label='현재 위치']")).toBeAttached();
    await expect(shell.locator("header.topbar h1")).toHaveCount(1);
  }
});

// ADR-0047: 지원 폭은 1280~1920px뿐이다. 좁은 폭 서랍(메뉴 단추·backdrop)은
// 지원 폭에서 한 번도 열리지 않는 죽은 코드였다. 사이드바는 늘 보인다.
test("셸에 좁은 폭 서랍이 없고 사이드바가 항상 보인다", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: /주 메뉴/ })).toHaveCount(0);
  await expect(page.locator(".topbar-menu")).toHaveCount(0);
  await expect(page.locator(".sidebar-backdrop")).toHaveCount(0);
  await expect(page.locator("aside.sidebar")).toBeVisible();
});

test("1440px 셸의 무드보드 색과 기준 치수를 고정한다", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop fixture only");

  await page.goto("/", { waitUntil: "domcontentloaded" });
  const metrics = await page.locator(".app-shell").evaluate((shell) => {
    const element = (selector: string): HTMLElement => {
      const found = shell.querySelector<HTMLElement>(selector);
      if (!found) throw new Error(`missing shell element: ${selector}`);
      return found;
    };
    const sidebar = element('[data-shell-region="sidebar"]');
    const topbar = element('[data-shell-region="topbar"]');
    const canvas = element('[data-shell-region="canvas"]');
    const rootStyle = getComputedStyle(shell);
    const sidebarStyle = getComputedStyle(sidebar);
    const topbarStyle = getComputedStyle(topbar);
    const canvasStyle = getComputedStyle(canvas);
    return {
      colorScheme: rootStyle.colorScheme,
      shellBackground: rootStyle.backgroundColor,
      sidebarBackground: sidebarStyle.backgroundColor,
      sidebarWidth: sidebar.getBoundingClientRect().width,
      topbarBackground: topbarStyle.backgroundColor,
      topbarHeight: topbar.getBoundingClientRect().height,
      canvasBackground: canvasStyle.backgroundColor,
      canvasPadding: [canvasStyle.paddingTop, canvasStyle.paddingRight, canvasStyle.paddingBottom, canvasStyle.paddingLeft],
      // 1280px 미만은 별도 레이아웃이 아니라 가로 스크롤이다(ADR-0047).
      shellMinWidth: rootStyle.minWidth,
      bodyMinWidth: getComputedStyle(document.body).minWidth,
      accentToken: rootStyle.getPropertyValue("--color-accent").trim(),
      // legacy @theme 이 :root 로 방출되어 테마를 이기던 토큰들(ADR-0048 §4-1).
      borderToken: rootStyle.getPropertyValue("--color-border").trim(),
      successToken: rootStyle.getPropertyValue("--color-success").trim(),
    };
  });

  // 색은 docs/design/PRD.md §4.1 의 무드보드 토큰 표와 1:1로 대응한다.
  expect(metrics).toMatchObject({
    colorScheme: "light",
    shellBackground: "rgb(242, 240, 239)", // #F2F0EF greige 30% + white
    sidebarBackground: "rgb(22, 27, 47)", // #161B2F navy anchor
    sidebarWidth: 248,
    topbarBackground: "rgb(255, 255, 255)",
    topbarHeight: 76,
    canvasBackground: "rgb(242, 240, 239)",
    canvasPadding: ["16px", "18px", "16px", "18px"],
    shellMinWidth: "1280px",
    bodyMinWidth: "1280px",
  });

  // accent 는 무드보드 slate 다. RootLab 녹색이 되돌아오지 않았는지도 함께 본다.
  expect(metrics.accentToken.toUpperCase()).toContain("5B687C");
  expect(metrics.accentToken).not.toContain("1D7B4E");
  expect(metrics.accentToken).not.toContain("7FD9AE");

  // legacy @theme 은 :root 로 방출되어 @layer astryx-theme 을 이긴다. 이름이 겹치는
  // 토큰을 theme.css 에 되살리면 테마 값이 조용히 무시되므로 여기서 막는다.
  expect(metrics.borderToken.toUpperCase()).toContain("D4CDCB");
  expect(metrics.borderToken.toUpperCase()).not.toContain("D7E1DB");
  expect(metrics.successToken).not.toContain("276238");
});

test("지원 폭 1280·1440·1920px에서 셸이 가로로 넘치지 않는다", async ({ page }, testInfo) => {
  // ADR-0047: 지원 폭은 1280~1920px. 1920px는 가로 스크롤 없음만 확인한다(PLAN §5.3).
  test.skip(testInfo.project.name !== "desktop", "폭 검사는 한 project에서만 돈다");

  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of ["/", "/order-plans", "/pre-specs", "/go-no-go", "/criteria", "/run-status"]) {
      await page.goto(route, { waitUntil: "domcontentloaded" });
      await expect(page.locator(".app-shell")).toBeVisible();
      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(
        overflow.scrollWidth,
        `${route} @ ${width}px 에서 가로 오버플로 (scrollWidth ${overflow.scrollWidth} > clientWidth ${overflow.clientWidth})`,
      ).toBeLessThanOrEqual(overflow.clientWidth);
    }
  }
});

test("콘텐츠를 스크롤해도 사이드바는 viewport에 고정되어 메뉴 이동을 유지한다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/order-plans");
  await expect(page.locator(".c2l-workspace")).toBeVisible();

  const sidebar = page.locator("aside.sidebar");
  await expect(sidebar).toHaveCSS("position", "sticky");
  const before = await sidebar.evaluate((element) => element.getBoundingClientRect().top);
  const canvas = page.locator(".page-canvas");
  await canvas.evaluate((element) => element.scrollTo({ top: element.scrollHeight, behavior: "instant" }));
  await expect.poll(() => canvas.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  const after = await sidebar.evaluate((element) => element.getBoundingClientRect().top);
  expect(Math.abs(after - before)).toBeLessThanOrEqual(1);
});
