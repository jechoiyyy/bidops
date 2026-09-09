import { expect, test, type Page } from "@playwright/test";
import {
  mockApi,
  mockBidDelta,
  mockDeepReviewLifecycle,
  mockDocumentPreparationVisual,
  mockOpportunity,
  mockOrderPlans,
  mockPreSpecs,
} from "./api-mock";

// 화면 검사 세 층(의미·구조·픽셀)이 같은 고정 입력에서 출발하도록 여기 모은다.
// 층을 나눈 이유와 각 층의 게이트는 `docs/standards.md`에 있다.

// 마감까지 남은 날짜가 화면에 그려지므로, 시각을 고정하지 않으면 매일 스냅샷이 달라진다.
const FIXED_TIME = new Date("2026-08-25T09:00:00+09:00");

/** 고정 mock만으로 도달하는 화면. 세 층이 같은 목록을 순회한다. */
export const pages = [
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
  // docs/design/PLAN.md 2단계에서 새로 생긴 사이드바 항목과, 흡수한 탭 중
  // 이전에 리다이렉트라 기준선이 없던 산출물 감사 로그를 덮는다. 위 타깃들은
  // 이제 합친 화면의 각 탭을 찍는다(경로가 그대로 각 탭의 주소다).
  { name: "audit", path: "/audit" },
  { name: "criteria", path: "/criteria" },
  { name: "run-status", path: "/run-status" },
  { name: "go-no-go", path: "/go-no-go" },
];

/** 세 층이 공유하는 고정 입력. 각 spec의 `beforeEach`가 이것만 부른다. */
export function installScreenFixtures(): void {
  test.beforeEach(async ({ page }) => {
    // Keep visual tests on the local Pretendard contract. These defensive routes
    // also make an accidental future Google Fonts import fail closed without
    // allowing a remote font to affect a snapshot.
    await page.route("**://fonts.googleapis.com/**", async (route) => {
      await route.fulfill({ status: 200, contentType: "text/css", body: "" });
    });
    await page.route("**://fonts.gstatic.com/**", async (route) => {
      await route.fulfill({ status: 204, body: "" });
    });
    await page.clock.setFixedTime(FIXED_TIME);
    await mockApi(page);
  });
}

/** 로컬 Pretendard가 적용된 뒤에만 레이아웃을 안정화하고 스냅샷을 찍는다. */
export async function settleFonts(page: Page): Promise<void> {
  const fontState = await page.evaluate(async () => {
    const text = document.documentElement.textContent ?? "";
    await Promise.all([
      document.fonts.load('400 14px "Pretendard"', text),
      document.fonts.load('400 13px "Liberation Mono"', text),
    ]);
    await document.fonts.ready;
    await new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      });
    return {
      computedFontFamily: getComputedStyle(document.documentElement).fontFamily,
      pretendardLoaded: document.fonts.check('400 14px "Pretendard"'),
    };
  });
  expect(fontState.computedFontFamily).toContain("Pretendard");
  expect(fontState.pretendardLoaded).toBe(true);
}

/** Existing responsive regression contract, shared by legacy and lifecycle screens. */
export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    const canvas = document.querySelector<HTMLElement>(".page-canvas");
    const widthOverflow = (element: HTMLElement): number => Math.max(0, element.scrollWidth - element.clientWidth);
    const actualLocalScrollers = new Set(
      [...document.querySelectorAll<HTMLElement>("body *")].filter((element) => {
        if (element === canvas) return false;
        const style = getComputedStyle(element);
        return (style.overflowX === "auto" || style.overflowX === "scroll")
          && element.scrollWidth > element.clientWidth;
      }),
    );
    const allowedScrollers = actualLocalScrollers;
    const isContainedByAllowedScroller = (element: Element): boolean => {
      let parent = element.parentElement;
      while (parent) {
        if (allowedScrollers.has(parent)) return true;
        parent = parent.parentElement;
      }
      return false;
    };
    const viewport = root.clientWidth;
    // Descendant exclusions require a real local horizontal scroller with
    // overflow-x auto/scroll and measurable scrollWidth excess; page-canvas
    // itself is never an exclusion.
    const overflowingDescendants = [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((element) => !isContainedByAllowedScroller(element))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        if (rect.right <= 0 || rect.left >= viewport) return 0;
        return Math.max(rect.right - viewport, -rect.left);
      });
    const descendantOverflow = Math.max(0, ...overflowingDescendants);
    return {
      documentElement: widthOverflow(root),
      pageCanvas: canvas ? widthOverflow(canvas) : 0,
      descendants: descendantOverflow,
    };
  });
  expect(overflow.documentElement).toBeLessThanOrEqual(1);
  expect(overflow.pageCanvas, JSON.stringify(overflow)).toBeLessThanOrEqual(1);
  expect(overflow.descendants, JSON.stringify(overflow)).toBeLessThanOrEqual(1);
}

const VISUAL_COMPARISON_ID = "77777777-7777-4777-8777-777777777777";

export type LifecycleVisualTarget = {
  name: string;
  path: string;
  setup: (page: Page) => Promise<void>;
};

/** 화면마다 별도 setup이 필요한 생애주기 타깃. */
export const lifecycleVisualTargets: LifecycleVisualTarget[] = [
  { name: "opportunities-list", path: "/opportunities", setup: async (page) => { await mockOpportunity(page); } },
  { name: "opportunity-detail", path: "/opportunities/202", setup: async (page) => { await mockOpportunity(page); } },
  { name: "order-plans-list", path: "/order-plans", setup: async (page) => { await mockOrderPlans(page); } },
  { name: "pre-specs-list", path: "/pre-specs", setup: async (page) => { await mockPreSpecs(page); } },
  { name: "pre-spec-detail", path: "/pre-specs/991", setup: async (page) => { await mockPreSpecs(page); } },
  { name: "pre-spec-unknown", path: "/pre-specs/991", setup: async (page) => { await mockPreSpecs(page, "unknown"); } },
  ...(["draft", "processing", "blocked", "ready"] as const).map((state) => ({
    name: `document-preparation-${state}`,
    path: "/pre-specs/991",
    setup: async (page: Page) => { await mockDocumentPreparationVisual(page, state); },
  })),
  ...(["queued", "running", "failed", "completed"] as const).map((state) => ({
    name: `deep-review-${state === "completed" ? "complete" : state}`,
    path: "/deep-reviews/fixture-review",
    setup: async (page: Page) => { await mockDeepReviewLifecycle(page, state); },
  })),
  ...(["unchanged", "changed", "unknown", "failed"] as const).map((state) => ({
    name: `bid-delta-${state}`,
    path: `/opportunities/501/bid-delta?comparison=${VISUAL_COMPARISON_ID}`,
    setup: async (page: Page) => { await mockBidDelta(page, { calculationStatus: "completed", resultStatus: state }); },
  })),
];


/** Shared v2 contract scenarios for the following screen tasks. */
export const contractFixtureScenarios = {
  orderPlansWithoutCompletedExecution: (page: Page) => mockOrderPlans(page, "no-completed-execution"),
  orderPlansWithoutOwner: (page: Page) => mockOrderPlans(page, "no-owning-opportunity"),
  preSpecClickReadyWithoutOrderPlan: {
    path: "/pre-specs?sw_only=false&auto_preparation_status=deep_review_ready_for_click",
    setup: (page: Page) => mockPreSpecs(page),
  },
} as const;
