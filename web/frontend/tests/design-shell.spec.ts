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
  "/pre-specs",
  "/pre-specs/991",
  "/opportunities/202",
  "/opportunities/501",
  "/deep-reviews/fixture-review",
  "/opportunities/501/bid-delta",
];

// 탐색과 추적 목록 4화면은 상단바가 경로 대신 화면 이름 하나를 그린다(제목 모드).
// 상세 화면(`/pre-specs/991`·`/opportunities/501`·bid-delta·deep-reviews)은
// 목록으로 돌아갈 링크가 필요하므로 경로 모드로 남는다. 발주계획은 목록의
// 우측 pane에서 상세를 보여 주므로 별도 상세 route가 없다.
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
  test.setTimeout(90_000);
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

test("나라장터 바로가기가 주 메뉴 하단에서 새 탭 링크로 제공된다", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const link = page.getByRole("link", { name: "나라장터 바로가기 (새 탭에서 열림)" });
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", "https://www.g2b.go.kr/");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  await expect(link).not.toHaveAttribute("aria-current", "page");
  await link.focus();
  await expect(link).toBeFocused();

  const positions = await page.locator("aside.sidebar").evaluate((sidebar) => {
    const lastGroup = sidebar.querySelector(".sidebar-group:last-of-type");
    const link = sidebar.querySelector(".sidebar-external-link");
    const nav = sidebar.querySelector(".sidebar-nav");
    const footer = sidebar.querySelector(".sidebar-footer");
    if (!lastGroup || !link || !nav || !footer) throw new Error("sidebar layout element missing");
    return {
      groupBottom: lastGroup.getBoundingClientRect().bottom,
      linkTop: link.getBoundingClientRect().top,
      linkBottom: link.getBoundingClientRect().bottom,
      navBottom: nav.getBoundingClientRect().bottom,
      footerTop: footer.getBoundingClientRect().top,
    };
  });
  expect(positions.linkTop).toBeGreaterThan(positions.groupBottom);
  expect(positions.navBottom - positions.linkBottom).toBeLessThan(30);
  expect(positions.linkBottom).toBeLessThan(positions.footerTop);
});

// 폭 하나에서만 도는 검사의 조건은 `layout-desktop`이다. 이 파일은 layout project
// 두 개(`layout-laptop`·`layout-desktop`)에서만 돌므로 옛 이름(`desktop`)으로 비교하면
// 두 폭 모두에서 skip되어 검사가 조용히 죽는다.
test("1440px 셸의 팔레트 색과 기준 치수를 고정한다", async ({ page }, testInfo) => {
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
    const brand = element('.sidebar-brand');
    const rootStyle = getComputedStyle(shell);
    const sidebarStyle = getComputedStyle(sidebar);
    const topbarStyle = getComputedStyle(topbar);
    const canvasStyle = getComputedStyle(canvas);
    const brandStyle = getComputedStyle(brand);
    return {
      colorScheme: rootStyle.colorScheme,
      shellBackground: rootStyle.backgroundColor,
      sidebarBackground: sidebarStyle.backgroundColor,
      brandBackground: brandStyle.backgroundColor,
      sidebarWidth: sidebar.getBoundingClientRect().width,
      topbarBackground: topbarStyle.backgroundColor,
      topbarHeight: topbar.getBoundingClientRect().height,
      canvasBackground: canvasStyle.backgroundColor,
      // 1280px 미만은 별도 레이아웃이 아니라 가로 스크롤이다(ADR-0047).
      shellMinWidth: rootStyle.minWidth,
      bodyMinWidth: getComputedStyle(document.body).minWidth,
      uiScale: Number.parseFloat(rootStyle.getPropertyValue("--bo-ui-scale")),
      rootZoom: getComputedStyle(document.documentElement).zoom,
      accentToken: rootStyle.getPropertyValue("--color-accent").trim(),
      // legacy @theme 이 :root 로 방출되어 테마를 이기던 토큰들.
      borderToken: rootStyle.getPropertyValue("--color-border").trim(),
      successToken: rootStyle.getPropertyValue("--color-success").trim(),
    };
  });

  // 색은 docs/0915_ui-redesign/spec.md §2.1 의 셸 표와 1:1로 대응한다.
  // 사이드바·상단바는 더는 어두운 면·흰 면이 아니라 canvas와 같은 회녹 바탕이다.
  expect(metrics).toMatchObject({
    colorScheme: "light",
    shellBackground: "rgb(246, 247, 244)", // #F6F7F4 회녹 canvas
    sidebarBackground: "rgb(246, 247, 244)", // 셸과 같은 면
    brandBackground: "rgba(0, 0, 0, 0)", // 면 없음(C안, spec §2.1)
    topbarBackground: "rgb(246, 247, 244)",
    canvasBackground: "rgb(246, 247, 244)",
    uiScale: 0.9,
    rootZoom: "1",
  });
  // Native compact CSS keeps the former rendered geometry without scaling the
  // document. Chromium can serialize fractional values differently.
  expect(metrics.sidebarWidth).toBeCloseTo(248 * 0.9, 1);
  expect(metrics.topbarHeight).toBeCloseTo(76 * 0.9, 1);
  expect(Number.parseFloat(metrics.shellMinWidth)).toBeCloseTo(1280, 1);
  expect(Number.parseFloat(metrics.bodyMinWidth)).toBeCloseTo(1280, 1);

  // accent 는 회사 포인트색을 한 단계 내린 #587A2B 다(spec §1.1). 옛 slate 와
  // RootLab 녹색이 되돌아오지 않았는지도 함께 본다.
  expect(metrics.accentToken.toUpperCase()).toContain("587A2B");
  expect(metrics.accentToken.toUpperCase()).not.toContain("5B687C");
  expect(metrics.accentToken).not.toContain("1D7B4E");
  expect(metrics.accentToken).not.toContain("7FD9AE");

  // legacy @theme 은 :root 로 방출되어 @layer astryx-theme 을 이긴다. 이름이 겹치는
  // 토큰을 theme.css 에 되살리면 테마 값이 조용히 무시되므로 여기서 막는다.
  expect(metrics.borderToken.toUpperCase()).toContain("E2E5DF");
  expect(metrics.borderToken.toUpperCase()).not.toContain("D4CDCB");
  expect(metrics.borderToken.toUpperCase()).not.toContain("D7E1DB");
  // 성공만 포인트 초록 계열로 옮겼다(intent 결정 1).
  expect(metrics.successToken.toUpperCase()).toContain("3F5A1C");
  expect(metrics.successToken).not.toContain("276238");

  // canvas 여백은 셸의 기본값이지만 시안을 통째로 옮긴 화면(ERP 대시보드는
  // `padding:0`, 판정 기준·실행 상태는 좌우 24px)이 각자 덮는다. 기본값은
  // 재정의가 없는 화면에서 재야 한다.
  await page.goto("/queue", { waitUntil: "domcontentloaded" });
  const canvasPadding = await page.locator(".page-canvas").evaluate((canvas) => {
    const style = getComputedStyle(canvas);
    return [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft];
  });
  expect(canvasPadding).toEqual(["10.8px", "16.2px", "14.4px", "16.2px"]);
});

// 제목 모드는 상단바가 화면의 시각 제목을 맡는다. 페이지가 제목 줄을 지운 뒤
// 이 글자는 기존 물리 크기인 18px 위계를 유지해야 한다.
// 상단바 높이는 두 모드가 같아야 한다. native compact CSS가 기존 68.4px을
// 직접 소유하며, 모드에 따라 셸이 흔들리면
// 목록과 상세를 오갈 때마다 본문이 위아래로 튄다.
test("제목 모드 상단바가 18px 제목을 쓰고 높이는 68.4px다", async ({ page }, testInfo) => {
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
  expect(metrics).toMatchObject({ fontSize: "18px", fontWeight: "600" });
  expect(metrics.topbarHeight).toBeCloseTo(68.4, 1);
});

test("native compact 셸이 드롭다운·대화상자를 viewport 안에 두고 키보드 초점을 되돌린다", async ({ page }) => {
  await page.goto("/pre-specs", { waitUntil: "domcontentloaded" });
  const viewport = page.viewportSize();
  if (!viewport) throw new Error("viewport 정보를 읽을 수 없습니다.");

  // 사전규격의 실제 Selector는 body layer로 목록을 그린다. 먼저 비동기 목록과
  // 상세 필터를 열어야 combobox가 DOM에 생긴다.
  await expect(page.locator(".pre-specs-split-workspace")).toBeVisible();
  const advancedToggle = page.getByRole("button", { name: "상세 필터", exact: true });
  await expect(advancedToggle).toBeVisible();
  await advancedToggle.click();
  const selector = page.getByRole("combobox", { name: "업무구분", exact: true });
  await expect(selector).toBeVisible();
  await selector.click();
  const listbox = page.getByRole("listbox");
  await expect(listbox).toBeVisible();
  const popoverGeometry = await selector.evaluate((trigger) => {
    const panel = [...document.querySelectorAll<HTMLElement>('[role="listbox"]')]
      .find((candidate) => candidate.getBoundingClientRect().width > 0 && candidate.getBoundingClientRect().height > 0);
    if (!panel) throw new Error("업무구분 드롭다운을 찾을 수 없습니다.");
    const selectedOption = panel.querySelector<HTMLElement>('[role="option"][aria-selected="true"]');
    if (!selectedOption) throw new Error("업무구분 드롭다운의 선택 항목을 찾을 수 없습니다.");
    const triggerRect = trigger.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    const selectedRect = selectedOption.getBoundingClientRect();
    return {
      triggerLeft: triggerRect.left,
      triggerRight: triggerRect.right,
      triggerTop: triggerRect.top,
      triggerBottom: triggerRect.bottom,
      panelTop: panelRect.top,
      panelLeft: panelRect.left,
      panelRight: panelRect.right,
      panelBottom: panelRect.bottom,
      selectedLeft: selectedRect.left,
      selectedRight: selectedRect.right,
      selectedTop: selectedRect.top,
      selectedBottom: selectedRect.bottom,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    };
  });
  // Selector uses Astryx's selected-item overlay: the listbox can extend above
  // the trigger so the selected row stays aligned with it. Check that row's
  // physical placement instead of requiring the panel edge to sit below the
  // trigger, while still checking the complete panel stays in the viewport.
  expect(popoverGeometry.panelLeft).toBeGreaterThanOrEqual(-1);
  expect(popoverGeometry.panelRight).toBeLessThanOrEqual(popoverGeometry.viewportWidth + 1);
  expect(popoverGeometry.panelTop).toBeGreaterThanOrEqual(-1);
  expect(popoverGeometry.panelBottom).toBeLessThanOrEqual(popoverGeometry.viewportHeight + 1);
  // The selected row is the library's anchor when the default overlay placement
  // is used. It must intersect the trigger in both axes, and its center should
  // remain aligned after the global zoom even though the panel extends above it.
  expect(popoverGeometry.selectedRight).toBeGreaterThan(popoverGeometry.triggerLeft - 1);
  expect(popoverGeometry.selectedLeft).toBeLessThan(popoverGeometry.triggerRight + 1);
  expect(popoverGeometry.selectedBottom).toBeGreaterThan(popoverGeometry.triggerTop - 1);
  expect(popoverGeometry.selectedTop).toBeLessThan(popoverGeometry.triggerBottom + 1);
  const triggerCenter = (popoverGeometry.triggerTop + popoverGeometry.triggerBottom) / 2;
  const selectedCenter = (popoverGeometry.selectedTop + popoverGeometry.selectedBottom) / 2;
  expect(Math.abs(selectedCenter - triggerCenter)).toBeLessThanOrEqual(4);

  await page.keyboard.press("Escape");
  await expect(listbox).toBeHidden();
  await expect(selector).toBeFocused();

  await page.goto("/order-plans", { waitUntil: "domcontentloaded" });
  const dialogTrigger = page.getByRole("button", { name: "목록 기준", exact: true });
  await expect(dialogTrigger).toBeVisible();
  await dialogTrigger.focus();
  await dialogTrigger.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const dialogGeometry = await dialog.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height };
  });
  expect(dialogGeometry.left).toBeGreaterThanOrEqual(-1);
  expect(dialogGeometry.top).toBeGreaterThanOrEqual(-1);
  expect(dialogGeometry.right).toBeLessThanOrEqual(viewport.width + 1);
  expect(dialogGeometry.bottom).toBeLessThanOrEqual(viewport.height + 1);
  expect(dialogGeometry.width).toBeGreaterThan(0);
  expect(dialogGeometry.height).toBeGreaterThan(0);

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(dialogTrigger).toBeFocused();
});

test("지원 폭 1280·1440·1920px에서 셸이 가로로 넘치지 않는다", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
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
