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
  "/opportunities/501/bid-delta",
];

// 탐색과 추적 목록 4화면은 상단바가 경로 대신 화면 이름 하나를 그린다(제목 모드).
// 상세 화면(`/pre-specs/991`·`/opportunities/501`·bid-delta)은
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
      // 2026-11-19(ADR-0076): 옛 경로(breadcrumb) 배치는 없다. 상세는 `‹ 목록` 돌아갈 링크 + 제목이고,
      // 돌아갈 곳이 없는 운영 화면(대시보드·판정 기준·실행 상태 등)은 링크 없이 제목만 있다.
      await expect(shell.locator('header.topbar[data-header-layout="page"]')).toBeAttached();
      await expect(shell.locator("header.topbar .topbar-breadcrumb")).toHaveCount(0);
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
    const panel = element('[data-shell-region="panel"]');
    const topbar = element('[data-shell-region="topbar"]');
    const canvas = element('[data-shell-region="canvas"]');
    const brand = element('.sidebar-brand');
    const rootStyle = getComputedStyle(shell);
    const sidebarStyle = getComputedStyle(sidebar);
    const topbarStyle = getComputedStyle(topbar);
    const canvasStyle = getComputedStyle(canvas);
    const brandStyle = getComputedStyle(brand);
    const panelStyle = getComputedStyle(panel);
    const panelRect = panel.getBoundingClientRect();
    return {
      panelBackground: panelStyle.backgroundColor,
      panelRadius: panelStyle.borderTopLeftRadius,
      panelBorder: panelStyle.borderTopColor,
      panelInset: [panelRect.top, window.innerWidth - panelRect.right, window.innerHeight - panelRect.bottom],
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
      // 2026-11-18 ×0.9 compact 축척을 없앴다. 축척 토큰이 되살아나지 않고 루트 글꼴이
      // 14px, Astryx 간격 토큰이 native 4px 격자 값인지 본다.
      uiScale: rootStyle.getPropertyValue("--bo-ui-scale").trim(),
      rootFontSize: getComputedStyle(document.documentElement).fontSize,
      spacing1: rootStyle.getPropertyValue("--spacing-1").trim(),
      spacing4: rootStyle.getPropertyValue("--spacing-4").trim(),
      sizeElementMd: rootStyle.getPropertyValue("--size-element-md").trim(),
      rootZoom: getComputedStyle(document.documentElement).zoom,
      accentToken: rootStyle.getPropertyValue("--color-accent").trim(),
      // legacy @theme 이 :root 로 방출되어 테마를 이기던 토큰들.
      borderToken: rootStyle.getPropertyValue("--color-border").trim(),
      successToken: rootStyle.getPropertyValue("--color-success").trim(),
    };
  });

  // 색·치수는 2026-11-19 최종 시안(docs/1119_kstyle-shell/mockups/, ADR 초안 승인 대기)과 1:1로 대응한다.
  // 따뜻한 회색 바탕(#EEEDEB) 위에 면 없는 사이드바 + 흰 패널(1px #E4E3E0, radius 12, 바깥 8px).
  expect(metrics).toMatchObject({
    colorScheme: "light",
    shellBackground: "rgb(238, 237, 235)", // --bo-frame
    sidebarBackground: "rgba(0, 0, 0, 0)", // 사이드바는 바탕 위에 면 없이 놓인다
    brandBackground: "rgba(0, 0, 0, 0)", // 워크스페이스 줄은 면 없음
    panelBackground: "rgb(255, 255, 255)",
    panelRadius: "12px",
    panelBorder: "rgb(228, 227, 224)",
    topbarBackground: "rgb(255, 255, 255)",
    canvasBackground: "rgb(255, 255, 255)",
    uiScale: "",
    rootFontSize: "14px",
    spacing1: "4px",
    spacing4: "16px",
    sizeElementMd: "32px",
    rootZoom: "1",
  });
  // 사이드바 228px, 패널 바깥 여백 8px(위·오른쪽·아래). 별도 상단바는 없고 패널 헤더 높이는 화면 글에 따른다.
  expect(metrics.sidebarWidth).toBeCloseTo(228, 1);
  for (const inset of metrics.panelInset) expect(inset).toBeCloseTo(8, 0);
  expect(Number.parseFloat(metrics.shellMinWidth)).toBeCloseTo(1280, 1);
  expect(Number.parseFloat(metrics.bodyMinWidth)).toBeCloseTo(1280, 1);

  // accent 는 시안의 #1D7B4E 다(ADR-0073 개정). 옛 slate·포인트 파생색이 되돌아오지 않았는지 본다.
  expect(metrics.accentToken.toUpperCase()).toContain("1D7B4E");
  expect(metrics.accentToken.toUpperCase()).not.toContain("5B687C");
  expect(metrics.accentToken.toUpperCase()).not.toContain("587A2B");

  // legacy @theme 은 :root 로 방출되어 @layer astryx-theme 을 이긴다. 이름이 겹치는
  // 토큰을 theme.css 에 되살리면 테마 값이 조용히 무시되므로 여기서 막는다.
  expect(metrics.borderToken.toUpperCase()).toContain("E4E3E0");
  expect(metrics.borderToken.toUpperCase()).not.toContain("D4CDCB");
  expect(metrics.borderToken.toUpperCase()).not.toContain("D7E1DB");
  // 성공은 시안의 초록(#1D7B4E)이다.
  expect(metrics.successToken.toUpperCase()).toContain("1D7B4E");

  // canvas 여백은 셸의 기본값이지만 시안을 통째로 옮긴 화면(ERP 대시보드는
  // `padding:0`, 판정 기준·실행 상태는 좌우 24px)이 각자 덮는다. 기본값은
  // 재정의가 없는 화면에서 재야 한다.
  await page.goto("/queue", { waitUntil: "domcontentloaded" });
  const canvasPadding = await page.locator(".page-canvas").evaluate((canvas) => {
    const style = getComputedStyle(canvas);
    return [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft];
  });
  // 모든 화면 같은 캔버스 여백: 위24·좌우32·아래32(2026-11-19 최종 시안 — 패널 헤더와 같은 좌우 32px).
  expect(canvasPadding).toEqual(["24px", "32px", "32px", "32px"]);
});

// 제목 모드는 패널 헤더가 화면의 시각 제목을 맡는다(2026-11-19 최종 시안, 2026-11-20 사용자 요청으로 압축):
// 작은 화면 이름(14px) + 문장형 제목 `<h1>`(24px/700) + 둥근 칸 탭(40px). 고정 설명 줄은 두지 않는다 — 그 순간의
// 데이터를 말하는 문장(브리핑의 마감 요약 등)만 설명 줄에 남는다. 문장은 화면이 이미 받은 건수로만 만든다.
test("제목 모드 패널 헤더가 화면 이름·24px 문장형 제목·탭을 쓰고 고정 설명 줄을 두지 않는다", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "layout-desktop", "치수 기준은 시안 폭에서만 고정한다");

  await page.goto("/order-plans", { waitUntil: "domcontentloaded" });
  const topbar = page.locator("header.topbar");
  await expect(topbar).toHaveAttribute("data-topbar-mode", "title");
  await expect(topbar.locator("h1")).toHaveText("추적을 정할 발주계획이 1건 있어요");
  await expect(topbar.getByTestId("page-header-eyebrow")).toHaveText("발주계획");
  await expect(topbar.locator(".topbar-breadcrumb")).toHaveCount(0);
  await expect(topbar.locator(".topbar-status")).toHaveCount(0);
  // 고정 설명 줄이 없다(빈 문단도 남기지 않는다).
  await expect(topbar.getByTestId("page-header-description")).toHaveCount(0);

  const metrics = await topbar.evaluate((element) => {
    const heading = element.querySelector<HTMLElement>("h1");
    const eyebrow = element.querySelector<HTMLElement>(".topbar-eyebrow");
    const tab = element.querySelector<HTMLElement>("#page-header-tabs .workspace-view-tabs .astryx-button");
    const main = element.querySelector<HTMLElement>(".topbar-main");
    const tabs = element.querySelector<HTMLElement>("#page-header-tabs");
    if (!heading || !eyebrow || !tab || !main || !tabs) throw new Error("missing panel header part");
    return {
      fontSize: getComputedStyle(heading).fontSize,
      fontWeight: getComputedStyle(heading).fontWeight,
      eyebrowSize: getComputedStyle(eyebrow).fontSize,
      tabHeight: tab.getBoundingClientRect().height,
      titleToTabs: tabs.getBoundingClientRect().top - main.getBoundingClientRect().bottom,
      borderBottom: getComputedStyle(element).borderBottomColor,
    };
  });
  expect(metrics).toMatchObject({ fontSize: "24px", fontWeight: "700", eyebrowSize: "14px", borderBottom: "rgb(228, 227, 224)" });
  expect(metrics.tabHeight).toBeCloseTo(40, 0);
  expect(metrics.titleToTabs).toBeCloseTo(12, 0);
});

// 탭 없는 화면의 패널 헤더는 88px 안팎(±8)이다(2026-11-20 사용자 요청). 고정 설명 줄도 없다.
test("탭 없는 패널 헤더는 88px 안팎이고 고정 설명 줄이 없다", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "layout-desktop", "치수 기준은 시안 폭에서만 고정한다");

  await page.goto("/", { waitUntil: "domcontentloaded" });
  const topbar = page.locator("header.topbar");
  await expect(topbar.getByTestId("page-header-eyebrow")).toHaveText("대시보드");
  await expect(topbar.getByTestId("page-header-description")).toHaveCount(0);
  const height = await topbar.evaluate((element) => element.getBoundingClientRect().height);
  expect(Math.abs(height - 88)).toBeLessThanOrEqual(8);
});

test("native compact 셸이 드롭다운·대화상자를 viewport 안에 두고 키보드 초점을 되돌린다", async ({ page }) => {
  await page.goto("/pre-specs", { waitUntil: "domcontentloaded" });
  const viewport = page.viewportSize();
  if (!viewport) throw new Error("viewport 정보를 읽을 수 없어요.");

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
  await listbox.evaluate(async node => { await Promise.all(node.getAnimations({ subtree: true }).map(animation => animation.finished)); });
  const popoverGeometry = await selector.evaluate((trigger) => {
    const panel = [...document.querySelectorAll<HTMLElement>('[role="listbox"]')]
      .find((candidate) => candidate.getBoundingClientRect().width > 0 && candidate.getBoundingClientRect().height > 0);
    if (!panel) throw new Error("업무구분 드롭다운을 찾을 수 없어요.");
    const selectedOption = panel.querySelector<HTMLElement>('[role="option"][aria-selected="true"]');
    if (!selectedOption) throw new Error("업무구분 드롭다운의 선택 항목을 찾을 수 없어요.");
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

  await page.goto("/pre-specs?workspace=all", { waitUntil: "domcontentloaded" });
  const dialogTrigger = page.locator(".pre-specs-detail-actions").getByRole("button", { name: "검토 제외", exact: true });
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

// 2026-11-21 사전규격 상세 읽기 폭(ADR-0076 결정 13): 본문·패널 헤더 안쪽·하단 결정 띠 안쪽이 같은 폭(1040px)이고, 가용
// 폭이 그보다 넓으면(1440) 패널 가운데에 놓인다. 세 곳의 왼쪽 선이 같다. 가용 폭이 좁은 1280은 지금처럼 패널 여백에서
// 시작하며 세 왼쪽 선이 같고 가로 넘침이 없다. 이 두 폭은 project(layout-laptop·layout-desktop)가 나눠 돈다.
test("사전규격 상세의 본문·헤더 안쪽·하단 띠가 같은 읽기 폭과 같은 왼쪽 선을 쓴다", async ({ page }) => {
  await page.goto("/pre-specs/991");
  await expect(page.locator("#ps-summary")).toBeVisible();
  await expect(page.locator("#page-footer .ps-decision-bar-inner")).toBeVisible();
  await expect(page.locator(".app-content")).toHaveAttribute("data-reading-width", "detail");
  await page.waitForLoadState("networkidle");

  const m = await page.evaluate(() => {
    const rect = (selector: string) => document.querySelector(selector)!.getBoundingClientRect();
    const canvas = document.querySelector<HTMLElement>(".page-canvas")!;
    const canvasRect = canvas.getBoundingClientRect();
    const bodyCards = [...document.querySelectorAll<HTMLElement>(".ps-record > [id]")].map((element) => element.getBoundingClientRect());
    const title = rect("header.topbar h1");
    return {
      viewport: window.innerWidth,
      bodyWidths: bodyCards.map((box) => Math.round(box.width)),
      bodyLeft: Math.round(bodyCards[0].left),
      bodyRight: Math.round(bodyCards[0].right),
      canvasLeft: Math.round(canvasRect.left),
      canvasRight: Math.round(canvasRect.left + canvas.clientWidth),
      titleLeft: Math.round(title.left),
      barLeft: Math.round(rect("#page-footer .ps-decision-bar-inner").left),
      barWidth: Math.round(rect("#page-footer .ps-decision-bar-inner").width),
      rootOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      canvasOverflow: canvas.scrollWidth - canvas.clientWidth,
    };
  });

  // 본문 구역은 모두 읽기 폭을 넘지 않고, 헤더 제목·본문·하단 띠 안쪽의 왼쪽 선이 같다.
  for (const width of m.bodyWidths) expect(width).toBeLessThanOrEqual(1040);
  expect(m.barWidth).toBeLessThanOrEqual(1040);
  expect(Math.abs(m.titleLeft - m.bodyLeft)).toBeLessThanOrEqual(1);
  expect(Math.abs(m.barLeft - m.bodyLeft)).toBeLessThanOrEqual(1);
  // 가로 넘침 없음.
  expect(m.rootOverflow).toBe(0);
  expect(m.canvasOverflow).toBe(0);

  if (m.viewport >= 1440) {
    // 가용 폭이 읽기 폭보다 넓다: 본문 폭이 1040이고 패널(스크롤 영역) 가운데에 있다.
    expect(m.bodyWidths[0]).toBe(1040);
    expect(Math.abs((m.bodyLeft - m.canvasLeft) - (m.canvasRight - m.bodyRight))).toBeLessThanOrEqual(2);
    expect(m.bodyLeft).toBeGreaterThan(m.canvasLeft);
  } else {
    // 1280: 가용 폭이 읽기 폭보다 좁아 본문이 패널 안쪽 가득 차고 가운데 여백이 없다.
    expect(m.bodyWidths[0]).toBeLessThan(1040);
    expect(Math.abs((m.bodyLeft - m.canvasLeft) - (m.canvasRight - m.bodyRight))).toBeLessThanOrEqual(2);
  }
});

test("읽기 폭 가운데 배치는 사전규격 상세에만 걸린다", async ({ page }) => {
  for (const route of ["/pre-specs", "/order-plans", "/opportunities/202"]) {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await expect(page.locator(".app-content")).toBeVisible();
    await expect(page.locator(".app-content[data-reading-width]"), route).toHaveCount(0);
  }
});
