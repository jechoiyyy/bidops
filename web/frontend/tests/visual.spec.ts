import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";

// 마감까지 남은 날짜가 화면에 그려지므로, 시각을 고정하지 않으면 매일 스냅샷이 달라진다.
const FIXED_TIME = new Date("2026-08-25T09:00:00+09:00");
const RUN_ID = "20260817-20260823--20260824T090927.138116Z";
const CANDIDATE_GATE_EVALUATION = "gateeval-22222222222222222222222222222222";

const pages = [
  { name: "dashboard", path: "/" },
  { name: "queue", path: "/queue" },
  { name: "judgments", path: "/judgments" },
  { name: "reviews", path: "/reviews" },
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

test("공통 셸이 로컬 글꼴과 기능 아이콘 접근성을 지킨다", async ({ page }) => {
  const remoteFontRequests: string[] = [];
  const localFontRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") remoteFontRequests.push(request.url());
    if (url.pathname.endsWith("/fonts/PretendardVariable.woff2")) localFontRequests.push(request.url());
  });
  await page.goto("/");
  await expect(page.locator("h1").first()).toBeVisible();
  await page.evaluate(async () => {
    await document.fonts.load('400 14px "Pretendard"');
    await document.fonts.ready;
  });

  expect(remoteFontRequests).toEqual([]);
  expect(localFontRequests.length).toBeGreaterThan(0);
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).fontFamily)).toContain("Pretendard");
  const exposedIcons = await page.locator("svg:not([aria-hidden='true'])").count();
  expect(exposedIcons).toBe(0);
  const unnamedButtons = await page.locator("button").evaluateAll((buttons) => buttons
    .filter((button) => !(button.getAttribute("aria-label") ?? button.textContent ?? "").replace(/\s+/g, "").trim())
    .map((button) => button.outerHTML));
  expect(unnamedButtons).toEqual([]);
});

test("대시보드의 마감 링크가 회차와 정렬을 함께 전달한다", async ({ page }) => {
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  await page.getByRole("link", { name: /전체 보기/ }).click();
  await expect.poll(() => new URL(page.url()).pathname).toMatch(/^\/queue(?:\/\d+)?$/);
  const params = new URL(page.url()).searchParams;
  expect(params.get("run")).toBe(RUN_ID);
  expect(params.get("sort")).toBe("deadline");
});

test("마감과 감사 redirect가 기존 쿼리를 보존한다", async ({ page }) => {
  await page.goto(`/deadlines?run=${encodeURIComponent(RUN_ID)}&from=dashboard`);
  await expect.poll(() => new URL(page.url()).pathname).toMatch(/^\/queue(?:\/\d+)?$/);
  let params = new URL(page.url()).searchParams;
  expect(params.get("run")).toBe(RUN_ID);
  expect(params.get("from")).toBe("dashboard");
  expect(params.get("sort")).toBe("deadline");

  await page.goto(`/audit?run=${encodeURIComponent(RUN_ID)}&from=review`);
  await expect.poll(() => new URL(page.url()).pathname).toBe("/runs");
  params = new URL(page.url()).searchParams;
  expect(params.get("run")).toBe(RUN_ID);
  expect(params.get("from")).toBe("review");
});

test("담당자 확인 요청을 펼치고 접을 수 있다", async ({ page }) => {
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  const list = page.locator("#dashboard-verification-list");
  const toggle = page.getByRole("button", { name: /나머지/ });
  await expect(list.locator("li")).toHaveCount(3);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(toggle).toHaveText("나머지 접기");
  expect(await list.locator("li").count()).toBeGreaterThan(3);
});

test("진행 중인 전량 판정은 중복 실행할 수 없다", async ({ page }) => {
  await page.goto(`/runs?run=${encodeURIComponent(RUN_ID)}`);
  await expect(page.getByRole("heading", { name: "전체 후보 판정 실행" })).toBeVisible();
  await expect(page.getByRole("button", { name: "전량 판정 대기열에 넣기" })).toBeDisabled();
  await expect(page.getByText("진행 중인 전량 판정 실행이 있어 새 실행을 시작할 수 없습니다.")).toBeVisible();
});

test("정책 활성화는 최신 운영 게이트와 담당자 없이는 열리지 않는다", async ({ page }) => {
  await page.goto("/policies");
  const candidate = page.locator(".policy-version-card.policy-status-activation_candidate");
  const activate = candidate.getByRole("button", { name: "정책 활성화 확인" });
  const gateSelect = candidate.getByLabel("통과한 최신 운영 evaluation");
  await expect(activate).toBeDisabled();
  const options = await gateSelect.locator("option").allTextContents();
  expect(options.some((option) => option.includes("gate-model-comparison"))).toBe(false);
  await gateSelect.selectOption(CANDIDATE_GATE_EVALUATION);
  await candidate.getByLabel("활성화 담당자").fill("검증 담당자");
  await expect(activate).toBeEnabled();
});

test("상시 운영은 승인 조합 불일치 상태에서 켤 수 없다", async ({ page }) => {
  await page.goto("/operations");
  await expect(page.getByText("상시 운영이 거부되었습니다.")).toBeVisible();
  await expect(page.getByRole("button", { name: "상시 운영 켜기" })).toBeDisabled();
});

test("값 없음·미확인·계산 불가·0을 구분해 표시한다", async ({ page }) => {
  await page.goto("/metrics");
  await expect(page.getByText("계산 불가", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/repeated_notice_keys 0/)).toBeVisible();

  await page.goto("/profile");
  await expect(page.getByText("미확인", { exact: true }).first()).toBeVisible();

  await page.goto("/operations");
  await expect(page.getByText(/후보 값 없음/).first()).toBeVisible();
  await expect(page.getByText(/실패 0/).first()).toBeVisible();
});

test("평가 수치 누락은 0/10이 아니라 계산 불가로 남는다", async ({ page }) => {
  await page.goto("/quality-gates?gate=gate-model-comparison&state=null-review");
  const review = page.locator("section[aria-labelledby='quality-review-heading']");
  await expect(review.getByText("계산 불가/10 유효 리뷰", { exact: true })).toBeVisible();
  await expect(review.getByText("계산 불가/10 서로 다른 공고", { exact: true })).toBeVisible();
});
