import { expect, test } from "@playwright/test";
import { mockApi } from "./api-mock";

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

// 탐색과 추적 목록 4화면은 상단바가 경로 대신 화면 이름 하나를 그린다(제목 모드).
// 상세 화면(`/order-plans/101`·`/pre-specs/991`·`/opportunities/501`·bid-delta·
// deep-reviews)은 목록으로 돌아갈 링크가 필요하므로 경로 모드로 남는다.
const TITLE_ROUTES = ["/order-plans", "/pre-specs", "/opportunities", "/go-no-go"];

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
    // 두 모드 어느 쪽이든 문서의 level 1 제목은 하나로 유지된다. 경로 모드는
    // 화면 이름 칸이, 제목 모드는 상단바의 화면 이름이 그 `<h1>`이다.
    if (TITLE_ROUTES.includes(route)) {
      await expect(shell.locator("header.topbar nav[aria-label='현재 위치']")).toHaveCount(0);
      await expect(shell.locator('header.topbar[data-topbar-mode="title"] h1')).toHaveCount(1);
    } else {
      await expect(shell.locator("header.topbar nav[aria-label='현재 위치']")).toBeAttached();
      await expect(shell.locator('header.topbar[data-topbar-mode="breadcrumb"]')).toBeAttached();
    }
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

// 폭 하나에서만 도는 검사의 조건은 `layout-desktop`이다. 이 파일은 layout project
// 두 개(`layout-laptop`·`layout-desktop`)에서만 돌므로 옛 이름(`desktop`)으로 비교하면
// 두 폭 모두에서 skip되어 검사가 조용히 죽는다.
test("1440px 셸의 무드보드 색과 기준 치수를 고정한다", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "layout-desktop", "desktop fixture only");

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

  // canvas 여백은 셸의 기본값이지만 시안을 통째로 옮긴 화면(ERP 대시보드는
  // `padding:0`, 판정 기준·실행 상태는 좌우 24px)이 각자 덮는다. 기본값은
  // 재정의가 없는 화면에서 재야 한다.
  await page.goto("/queue", { waitUntil: "domcontentloaded" });
  const canvasPadding = await page.locator(".page-canvas").evaluate((canvas) => {
    const style = getComputedStyle(canvas);
    return [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft];
  });
  expect(canvasPadding).toEqual(["16px", "18px", "16px", "18px"]);
});

// 제목 모드는 상단바가 화면의 시각 제목을 맡는다. 페이지가 제목 줄을 지운 뒤
// 이 글자가 20px 위계를 잃으면 화면에서 제목이 사라진 것과 같으므로 값을 고정한다.
// 상단바 높이는 두 모드가 같아야 한다(76px, PRD §5) — 모드에 따라 셸이 흔들리면
// 목록과 상세를 오갈 때마다 본문이 위아래로 튄다.
test("제목 모드 상단바가 20px 제목을 쓰고 높이는 76px 그대로다", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "layout-desktop", "치수 기준은 시안 폭에서만 고정한다");

  await page.goto("/order-plans", { waitUntil: "domcontentloaded" });
  const topbar = page.locator("header.topbar");
  await expect(topbar).toHaveAttribute("data-topbar-mode", "title");
  await expect(topbar.locator("h1")).toHaveText("발주계획");
  await expect(topbar.locator(".topbar-breadcrumb")).toHaveCount(0);
  await expect(topbar.locator(".topbar-status")).toHaveCount(0);

  const metrics = await topbar.evaluate((element) => {
    const heading = element.querySelector<HTMLElement>("h1");
    if (!heading) throw new Error("missing topbar h1");
    const headingStyle = getComputedStyle(heading);
    return {
      fontSize: headingStyle.fontSize,
      fontWeight: headingStyle.fontWeight,
      topbarHeight: element.getBoundingClientRect().height,
    };
  });
  expect(metrics).toMatchObject({ fontSize: "20px", fontWeight: "600", topbarHeight: 76 });
});

test("지원 폭 1280·1440·1920px에서 셸이 가로로 넘치지 않는다", async ({ page }, testInfo) => {
  // ADR-0047: 지원 폭은 1280~1920px. 1920px는 가로 스크롤 없음만 확인한다(PLAN §5.3).
  test.skip(testInfo.project.name !== "layout-desktop", "폭 검사는 한 project에서만 돈다");

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

// 이 검사는 **셸의 계약**이다: canvas 가 넘칠 때 사이드바가 따라 움직이지 않는다.
// 어느 화면의 높이에 기대면 그 화면이 밀도를 바꿀 때마다(발주계획·사전규격이 최근
// 그랬다) 검사가 통째로 무의미해지므로, canvas 에 높은 블록을 직접 넣어 스크롤을
// 만들고 셸만 본다.
test("콘텐츠를 스크롤해도 사이드바는 viewport에 고정되어 메뉴 이동을 유지한다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.locator("h1").first()).toBeVisible();
  await page.locator(".page-canvas").evaluate((canvas) => {
    const filler = document.createElement("div");
    filler.style.height = "3000px";
    canvas.append(filler);
  });

  const sidebar = page.locator("aside.sidebar");
  await expect(sidebar).toHaveCSS("position", "sticky");
  const before = await sidebar.evaluate((element) => element.getBoundingClientRect().top);
  const canvas = page.locator(".page-canvas");
  await canvas.evaluate((element) => element.scrollTo({ top: element.scrollHeight, behavior: "instant" }));
  await expect.poll(() => canvas.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  const after = await sidebar.evaluate((element) => element.getBoundingClientRect().top);
  expect(Math.abs(after - before)).toBeLessThanOrEqual(1);
});
