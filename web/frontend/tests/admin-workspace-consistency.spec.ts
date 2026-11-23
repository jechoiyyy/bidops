import { expect, test } from "@playwright/test";
import { installRunStatusMock } from "./run-status-fixtures";

const sections = [
  { path: "/profile", label: "판정용 프로필 사본", nav: "판정 기준 구역" },
  { path: "/policies", label: "판정 정책", nav: "판정 기준 구역" },
  { path: "/quality-gates", label: "품질 게이트", nav: "판정 기준 구역" },
  { path: "/metrics", label: "회차 검증 지표", nav: "판정 기준 구역" },
  { path: "/runs", label: "수집 실행", nav: "실행 상태 구역" },
  { path: "/attachments", label: "첨부 확보", nav: "실행 상태 구역" },
  { path: "/operations", label: "상시 운영", nav: "실행 상태 구역" },
  { path: "/audit", label: "산출물 감사 로그", nav: "실행 상태 구역" },
];

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
  test(`판정 기준과 실행 상태가 ${viewport.width}px에서 같은 구역 메뉴와 표 작업대를 쓴다`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await installRunStatusMock(page);
    const measurements: Array<Record<string, unknown>> = [];
    let reference: { listWidth: number; left: number } | undefined;

    for (const { path, label, nav: navName } of sections) {
      await page.goto(path);
      const nav = page.getByRole("navigation", { name: navName });
      await expect(nav.getByRole("link")).toHaveCount(navName === "판정 기준 구역" ? 5 : 4);
      await expect(nav.locator('a[aria-current="page"]')).toHaveText(label);
      await expect(page.locator("header.topbar").getByRole("tab")).toHaveCount(0);

      const collection = page.getByRole("region", { name: "일일 수집 상태" });
      if (path === "/runs") {
        await expect(collection.getByRole("listitem")).toHaveText([
          /발주계획.*수집 완료/,
          /공고\(사전규격·입찰공고\).*수집 완료/,
        ]);
      } else {
        await expect(collection).toHaveCount(0);
      }

      const workspace = page.locator(".workbench-admin-workspace");
      const list = workspace.locator(".review-split-list");
      if (path === "/runs") {
        const listHead = list.locator(".workbench-admin-list-head");
        const views = listHead.getByRole("radiogroup", { name: "회차 보기" });
        const search = listHead.getByRole("textbox", { name: "실행 회차 검색" });
        await expect(views.getByRole("radio", { name: /^전체 / })).toBeChecked();
        await expect(search).toBeVisible();
        await expect(listHead.locator(".astryx-text-input")).toHaveCSS("height", "32px");
        const [viewsBox, searchBox] = await Promise.all([views.boundingBox(), search.boundingBox()]);
        expect(viewsBox!.y + viewsBox!.height / 2).toBeCloseTo(searchBox!.y + searchBox!.height / 2, 0);
        const overview = page.locator(".rs-overview");
        await expect(overview.locator(".rs-summary-label", { hasText: "발주계획" })).toHaveCSS("font-size", "12px");
        await expect(overview.locator(".rs-summary-item", { hasText: "스케줄러" }).locator(".rs-summary-value")).toHaveCSS("font-size", "14px");
      }
      const table = list.getByRole("table");
      await expect(table.getByRole("columnheader")).toHaveText(["이름", "구분·식별", "상태"]);
      const title = table.locator('[aria-current="true"] .record-table-title');
      await expect(title, `${path}의 선택된 행`).toBeVisible();
      await expect(title).toHaveCSS("font-size", "14px");
      await expect(title).toHaveCSS("font-weight", "700");

      const preview = workspace.locator(".review-split-detail");
      const footer = preview.getByRole("group", { name: "결정 영역", exact: true });
      await expect(footer).toBeInViewport({ ratio: 1 });
      await page.evaluate(() => document.fonts.ready);

      const metrics = await workspace.evaluate((element) => {
        const main = element.closest(".workbench-admin-main")!;
        const menu = main.previousElementSibling!.getBoundingClientRect();
        const listBox = element.querySelector(".review-split-list")!.getBoundingClientRect();
        const previewBox = element.querySelector(".review-split-detail")!.getBoundingClientRect();
        const footerBox = element.querySelector(".workbench-decision")!.getBoundingClientRect();
        const strip = main.querySelector(".workbench-admin-summary")!.getBoundingClientRect();
        const collectionBox = main.querySelector(".rs-collection")?.getBoundingClientRect();
        const previousBox = (main.querySelector(".crit-verification-requests") ?? main.querySelector(".workbench-admin-summary"))!.getBoundingClientRect();
        const canvas = main.closest(".page-canvas")!.getBoundingClientRect();
        const box = element.getBoundingClientRect();
        return {
          left: box.left,
          right: box.right,
          bottom: box.bottom,
          top: box.top,
          listWidth: listBox.width,
          listRatio: listBox.width / box.width,
          previewRatio: previewBox.width / box.width,
          previewLeft: previewBox.left,
          listRight: listBox.right,
          navLeft: menu.left,
          navRight: menu.right,
          navWidth: menu.width,
          navTop: menu.top,
          navBottom: menu.bottom,
          canvasLeft: canvas.left,
          canvasRight: canvas.right,
          canvasTop: canvas.top,
          canvasBottom: canvas.bottom,
          stripLeft: strip.left,
          stripRight: strip.right,
          stripTop: strip.top,
          collectionLeft: collectionBox?.left,
          collectionTop: collectionBox?.top,
          collectionBottom: collectionBox?.bottom,
          stripBottom: strip.bottom,
          previousBottom: previousBox.bottom,
          footerTop: footerBox.top,
          footerBottom: footerBox.bottom,
          rootOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        };
      });
      measurements.push({ path, ...metrics });

      expect(metrics.rootOverflow, path).toBeLessThanOrEqual(1);
      expect(metrics.navWidth, path).toBeCloseTo(200, 0);
      expect(metrics.navLeft, path).toBeCloseTo(metrics.canvasLeft, 0);
      expect(metrics.navRight, path).toBeCloseTo(metrics.left, 0);
      expect(metrics.navTop, path).toBeCloseTo(metrics.canvasTop, 0);
      expect(metrics.navBottom, path).toBeCloseTo(metrics.canvasBottom, 0);
      expect(metrics.right, path).toBeCloseTo(metrics.canvasRight, 0);
      expect(metrics.bottom, path).toBeCloseTo(metrics.canvasBottom, 0);
      expect(metrics.listRatio, path).toBeCloseTo(0.60, 2);
      expect(metrics.previewRatio, path).toBeCloseTo(0.40, 2);
      expect(metrics.listRight, path).toBeCloseTo(metrics.previewLeft, 0);
      expect(metrics.stripLeft, path).toBeCloseTo(metrics.left, 0);
      expect(metrics.stripRight, path).toBeCloseTo(metrics.right, 0);
      expect(metrics.stripTop, path).toBeCloseTo(metrics.canvasTop, 0);
      if (path === "/runs") {
        expect(metrics.collectionLeft!, path).toBeGreaterThanOrEqual(metrics.stripLeft);
        expect(metrics.collectionTop!, path).toBeGreaterThanOrEqual(metrics.stripTop);
        expect(metrics.collectionBottom!, path).toBeLessThanOrEqual(metrics.stripBottom);
      }
      expect(metrics.top - metrics.previousBottom, path).toBeGreaterThanOrEqual(0);
      expect(metrics.top - metrics.previousBottom, path).toBeLessThanOrEqual(12);
      expect(metrics.footerBottom, path).toBeCloseTo(metrics.bottom, 0);

      reference ??= { listWidth: metrics.listWidth, left: metrics.left };
      expect(metrics.listWidth, path).toBeCloseTo(reference.listWidth, 0);
      expect(metrics.left, path).toBeCloseTo(reference.left, 0);

      const scroll = preview.locator(".workbench-admin-detail-scroll");
      await expect(scroll).toHaveCSS("overflow-y", "auto");
      await scroll.evaluate((element) => { element.scrollTop = element.scrollHeight; });
      const afterScroll = await footer.boundingBox();
      expect(afterScroll!.y, `${path} 본문 스크롤과 결정 띠 분리`).toBeCloseTo(metrics.footerTop, 0);
      await page.screenshot({ path: testInfo.outputPath(`${path.slice(1)}-${viewport.width}.png`), animations: "disabled" });
    }
    await testInfo.attach("admin-workspace-geometry", {
      body: JSON.stringify({ viewport, measurements }, null, 2),
      contentType: "application/json",
    });
  });
}

test("상시 운영 변경은 상세와 상단 요약에 함께 반영된다", async ({ page }) => {
  const trace = await installRunStatusMock(page, { activationReady: true });
  await page.goto("/operations");
  const summaryValue = page.locator(".rs-summary-item").filter({ hasText: "공고 판정(C-1) 스케줄러" }).locator(".rs-summary-value");
  await expect(summaryValue).toHaveText("꺼짐");
  await page.getByRole("button", { name: "상시 운영 켜기", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toHaveAttribute("data-astryx-theme", "bidops");
  await dialog.getByLabel("변경 담당자").fill("통합 검증 담당자");
  await dialog.getByLabel("게이트 결과 ID 확인").fill("gateeval-11111111111111111111111111111111");
  await dialog.getByRole("button", { name: "상시 운영 켜기", exact: true }).click();
  await expect.poll(() => trace.alwaysOnPuts.length).toBe(1);
  await expect(dialog).toBeHidden();
  await expect(summaryValue).toHaveText("켜짐");
  await expect(page.locator(".rs-detail-pane")).toContainText("상시 운영을 켰어요");
});

test("실행 상태 새로고침은 현재 목록과 상세를 갱신하고 닫힌 탭은 조회하지 않는다", async ({ page }) => {
  await installRunStatusMock(page);
  const reads: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "GET") reads.push(new URL(request.url()).pathname);
  });
  await page.goto("/operations");
  await expect(page.getByRole("group", { name: "결정 영역", exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "실행 상태 구역" }).getByRole("link", { name: "수집 실행", exact: true }).click();
  await expect(page.getByRole("table", { name: "실행 회차 목록", exact: true }).locator('[aria-current="true"] .record-table-title')).toBeVisible();
  const refresh = page.locator("header.topbar").getByRole("button", { name: "새로고침", exact: true });
  await expect(refresh).toBeEnabled();
  reads.length = 0;
  await refresh.click();
  await expect.poll(() => reads.includes("/api/runs"), { timeout: 2000 }).toBe(true);
  await expect.poll(() => reads.some((path) => /^\/api\/runs\/[^/]+$/.test(path)), { timeout: 2000 }).toBe(true);
  expect(reads).not.toContain("/api/schedule/settings");
  expect(reads).not.toContain("/api/schedule/executions");
});
