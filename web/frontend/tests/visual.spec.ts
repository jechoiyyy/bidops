import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";

// 마감까지 남은 날짜가 화면에 그려지므로, 시각을 고정하지 않으면 매일 스냅샷이 달라진다.
const FIXED_TIME = new Date("2026-08-25T09:00:00+09:00");

const pages = [
  { name: "dashboard", path: "/" },
  { name: "queue", path: "/queue" },
  { name: "judgments", path: "/judgments" },
  { name: "runs", path: "/runs" },
  { name: "attachments", path: "/attachments" },
  { name: "profile", path: "/profile" },
  { name: "metrics", path: "/metrics" },
];

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(FIXED_TIME);
  await mockApi(page);
});

/**
 * 본문 글꼴은 Google Fonts에서 유니코드 구간별로 나뉘어 도착한다.
 * document.fonts.ready는 그 시점까지 요청된 구간만 보장하므로, select 같은
 * 네이티브 컨트롤의 글자가 뒤늦게 바뀌어 스냅샷이 흔들린다.
 * 화면에 실제로 놓인 글자를 넘겨 필요한 구간을 모두 받아 온 뒤에 촬영한다.
 */
async function settleFonts(page: Page): Promise<void> {
  await page.evaluate(async () => {
    const text = document.body.innerText;
    for (const weight of ["300", "400", "500", "600"]) {
      await document.fonts.load(`${weight} 13px "IBM Plex Sans KR"`, text);
    }
    await document.fonts.load("400 13px \"IBM Plex Mono\"", text);
    await document.fonts.ready;
  });
}

for (const target of pages) {
  test(`${target.name} 화면이 가로로 넘치지 않는다`, async ({ page }) => {
    await page.goto(target.path);
    await expect(page.locator("h1")).toBeVisible();
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test(`${target.name} 화면 스냅샷`, async ({ page }) => {
    await page.goto(target.path);
    await expect(page.locator("h1")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`${target.name}.png`, {
      fullPage: true,
      animations: "disabled",
    });
  });
}
