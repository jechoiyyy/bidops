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
  { name: "quality-gates", path: "/quality-gates" },
  // The default gate is operational approval (10/10); this second target
  // keeps the model-comparison "not eligible for activation" warning under
  // responsive visual coverage as well.
  { name: "quality-gates-comparison", path: "/quality-gates?gate=gate-model-comparison" },
  { name: "policies", path: "/policies" },
  { name: "operations", path: "/operations" },
];

test.beforeEach(async ({ page }) => {
  // The app theme imports Google Fonts. Keep visual tests entirely local: an
  // empty CSS response prevents any gstatic font-face follow-up, while the
  // second route closes the gap if a future import adds one.
  await page.route("**://fonts.googleapis.com/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "text/css", body: "" });
  });
  await page.route("**://fonts.gstatic.com/**", async (route) => {
    await route.fulfill({ status: 204, body: "" });
  });
  await page.clock.setFixedTime(FIXED_TIME);
  await mockApi(page);
});

/**
 * Google Fonts가 없어도 레이아웃 측정을 기다리는 동안 같은 글꼴을 쓴다.
 * theme의 IBM Plex 변수는 Playwright 이미지에 설치된 로컬 글꼴로
 * 덮어쓰므로 폰트 서버의 성공 여부에 따라 스냅샷이 달라지지 않는다.
 */
async function settleFonts(page: Page): Promise<void> {
  await page.addStyleTag({
    content: `
      :root {
        --font-sans: "WenQuanYi Zen Hei", sans-serif;
        --font-mono: "Liberation Mono", monospace;
      }
    `,
  });
  await page.evaluate(async () => {
    const text = document.documentElement.textContent ?? "";
    await Promise.all([
      document.fonts.load('400 13px "WenQuanYi Zen Hei"', text),
      document.fonts.load('400 13px "Liberation Mono"', text),
    ]);
    await document.fonts.ready;
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
  });
}

for (const target of pages) {
  test(`${target.name} 화면이 가로로 넘치지 않는다`, async ({ page }) => {
    await page.goto(target.path);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => {
      const viewport = document.documentElement.clientWidth;
      const isContainedByIntentionalScroller = (element: Element): boolean => {
        let parent = element.parentElement;
        while (parent) {
          const overflowX = getComputedStyle(parent).overflowX;
          if (overflowX === "auto" || overflowX === "scroll") return true;
          parent = parent.parentElement;
        }
        return false;
      };
      // The operations history is intentionally scrollable as a local data
      // table on narrow viewports. Measure content escaping the page itself,
      // while excluding descendants inside that local scroller.
      return Math.max(0, ...[...document.querySelectorAll<HTMLElement>("body *")]
        .filter((element) => !isContainedByIntentionalScroller(element))
        .map((element) => {
          const rect = element.getBoundingClientRect();
          if (rect.right <= 0 || rect.left >= viewport) return 0;
          return Math.max(rect.right - viewport, -rect.left);
        }));
    });
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test(`${target.name} 화면 스냅샷`, async ({ page }) => {
    await page.goto(target.path);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`${target.name}.png`, {
      fullPage: true,
      animations: "disabled",
    });
  });
}
