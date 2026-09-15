import { expect, test } from "@playwright/test";
import { mockApi } from "./api-mock";
import { installRunStatusMock } from "./run-status-fixtures";

// 두 병렬 구현이 각각 통과해도 탭 모양·시작 위치·목록 폭이 서로 달라질 수 있다.
// 승인 HTML의 논리 실측(탭 37px, 목록 38%, 제목 15px)을 두 페이지의 여덟 탭에
// 적용한다. 전역 UI 배율은 CSS zoom으로 물리 rect만 90%로 그린다.
const UI_SCALE = 0.9;
const physical = (logical: number) => logical * UI_SCALE;
// 업무 값은 기존 API fixture로 공급하며 운영 API에는 접근하지 않는다.
const tabs = [
  { path: "/profile", prefix: "crit" },
  { path: "/policies", prefix: "crit" },
  { path: "/quality-gates", prefix: "crit" },
  { path: "/metrics", prefix: "crit" },
  { path: "/runs", prefix: "rs" },
  { path: "/attachments", prefix: "rs" },
  { path: "/operations", prefix: "rs" },
  { path: "/audit", prefix: "rs" },
];

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`판정 기준과 실행 상태의 8개 탭은 ${viewport.width}px에서 같은 ERP 골격을 쓴다`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await mockApi(page);
    const measurements: Array<Record<string, unknown>> = [];
    let firstWidth: number | undefined;
    let firstLeft: number | undefined;

    for (const { path, prefix } of tabs) {
      await page.goto(path);
      const workspace = page.locator(`.${prefix}-workspace`);
      const queueSelector = prefix === "rs" ? ".rs-list-pane" : ".crit-queue";
      const queue = page.locator(queueSelector);
      const title = queue.locator(`.${prefix}-record-title`).first();
      const footer = page.locator(`.${prefix}-detail-foot`);
      await expect(title, `${path}의 API 목록`).toBeVisible();
      await expect(footer, `${path}의 고정 하단 영역`).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      const metrics = await workspace.evaluate((element, pagePrefix) => {
        const root = element.closest(`.${pagePrefix}-page`)!;
        const list = root.querySelector(pagePrefix === "rs" ? ".rs-list-pane" : ".crit-queue")!;
        const heading = list.querySelector(`.${pagePrefix}-record-title`)!;
        const tabBar = root.querySelector(`.${pagePrefix}-tabs`)!;
        const strip = root.querySelector(`.${pagePrefix}-summary`)!;
        const actions = root.querySelector(`.${pagePrefix}-detail-foot`)!;
        const body = root.querySelector(`.${pagePrefix}-detail-scroll`);
        const bounds = element.getBoundingClientRect();
        const listBounds = list.getBoundingClientRect();
        const button = actions.querySelector("button");
        return {
          x: bounds.x,
          y: bounds.y,
          width: bounds.width,
          listWidth: listBounds.width,
          // getBoundingClientRect()는 물리 폭, clientWidth는 논리 폭이다. 두
          // 페이지의 목록 비율은 같은 좌표계의 물리 폭으로 비교한다.
          ratio: listBounds.width / bounds.width,
          titleFont: getComputedStyle(heading).fontSize,
          titleWeight: getComputedStyle(heading).fontWeight,
          tabsHeight: tabBar.getBoundingClientRect().height,
          summaryHeight: strip.getBoundingClientRect().height,
          summaryBottom: strip.getBoundingClientRect().bottom,
          footerHeight: actions.getBoundingClientRect().height,
          footerTop: actions.getBoundingClientRect().top,
          footerBottom: actions.getBoundingClientRect().bottom,
          buttonFont: button ? getComputedStyle(button).fontSize : null,
          bodyOverflow: body ? getComputedStyle(body).overflowY : null,
          rootOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        };
      }, prefix);
      measurements.push({ path, ...metrics });

      expect(metrics.rootOverflow, path).toBeLessThanOrEqual(1);
      expect(metrics.ratio, `${path} 목록 비율`).toBeCloseTo(0.38, 2);
      expect(metrics.titleFont, `${path} 목록 제목 크기`).toBe("15px");
      expect(metrics.titleWeight, `${path} 목록 제목 굵기`).toBe("600");
      expect(metrics.tabsHeight, `${path} 승인된 밑줄 탭`).toBeCloseTo(physical(37), 0);
      expect(metrics.summaryHeight, `${path} 요약 한 줄`).toBeCloseTo(physical(49), 0);
      // canvas 위 여백 16→12(docs/0915_ui-redesign/spec.md §2.1)로 본문 시작이 4px 올라갔다.
      expect(metrics.y, `${path} 시안 도구 모음 제외 본문 시작`).toBeCloseTo(physical(186), 0);
      expect(Math.abs(metrics.y - metrics.summaryBottom), `${path} 요약과 본문 사이 틈`).toBeLessThanOrEqual(1);
      expect(metrics.footerHeight, `${path} 하단 액션 높이`).toBeCloseTo(physical(57), 0);
      // 작업 영역 카드의 1px 테두리가 그림자로 바뀌어(spec §2.3) 하단 단추가 1px 내려왔다.
      expect(metrics.footerBottom, `${path} 하단 버튼 위치`).toBeCloseTo(viewport.height - physical(37), 0);
      if (metrics.buttonFont) expect(metrics.buttonFont, `${path} 하단 버튼 크기`).toBe("14px");
      if (metrics.bodyOverflow) expect(metrics.bodyOverflow, path).toBe("auto");

      firstWidth ??= metrics.listWidth;
      firstLeft ??= metrics.x;
      expect(Math.abs(metrics.listWidth - firstWidth), `${path} 두 페이지 목록 폭 일치`).toBeLessThanOrEqual(1);
      expect(Math.abs(metrics.x - firstLeft), `${path} 두 페이지 왼쪽 정렬`).toBeLessThanOrEqual(1);

      // 긴 본문을 끝까지 내려도 하단 액션은 이동하지 않아야 한다.
      await page.locator(`.${prefix}-detail-scroll`).evaluateAll((elements) => {
        for (const element of elements) element.scrollTop = element.scrollHeight;
      });
      const afterScroll = await footer.boundingBox();
      expect(Math.abs(afterScroll!.y - metrics.footerTop), `${path} 본문 스크롤과 하단 액션 분리`).toBeLessThanOrEqual(1);
      await expect(page.locator(`.${prefix}-tabs [role="tab"]`)).toHaveCount(4);
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
  const summaryValue = page.locator(".rs-summary-item").first().locator(".rs-summary-value");
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
  await expect(page.locator(".rs-detail-pane")).toContainText("상시 운영을 켰습니다");
});

test("실행 상태 새로고침은 현재 목록과 상세를 갱신하고 닫힌 탭은 조회하지 않는다", async ({ page }) => {
  await installRunStatusMock(page);
  const reads: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "GET") reads.push(new URL(request.url()).pathname);
  });
  await page.goto("/operations");
  await expect(page.locator(".rs-detail-foot")).toBeVisible();
  await page.getByRole("tab", { name: "수집 실행", exact: true }).click();
  await expect(page.locator(".rs-record-title").first()).toBeVisible();
  const refresh = page.locator(".rs-summary").getByRole("button", { name: "새로고침", exact: true });
  await expect(refresh).toBeEnabled();
  reads.length = 0;
  await refresh.click();
  await expect.poll(() => reads.includes("/api/runs"), { timeout: 2000 }).toBe(true);
  await expect.poll(() => reads.some((path) => /^\/api\/runs\/[^/]+$/.test(path)), { timeout: 2000 }).toBe(true);
  expect(reads).not.toContain("/api/schedule/settings");
  expect(reads).not.toContain("/api/schedule/executions");
});
