import { expect, test } from "@playwright/test";
import { mockApi } from "./api-mock";

const RUN_ID = "20260817-20260823--20260824T090927.138116Z";

type RouteContextCase = {
  name: string;
  path: string;
  title: string;
  dataScope: "run" | "cumulative";
  editScope: string | null;
  runSelectorVisible: boolean;
};

const routeContexts: RouteContextCase[] = [
  { name: "dashboard", path: `/?run=${RUN_ID}`, title: "대시보드", dataScope: "run", editScope: null, runSelectorVisible: true },
  { name: "queue list", path: `/queue?run=${RUN_ID}`, title: "검토 대기열", dataScope: "run", editScope: "리뷰 저장 가능", runSelectorVisible: true },
  { name: "queue detail", path: `/queue/29?run=${RUN_ID}`, title: "검토 대기열", dataScope: "run", editScope: "리뷰 저장 가능", runSelectorVisible: true },
  { name: "opportunities", path: `/opportunities?run=${RUN_ID}`, title: "사업기회", dataScope: "cumulative", editScope: "추적 상태 저장 가능", runSelectorVisible: false },
  { name: "bid delta", path: `/opportunities/501/bid-delta?run=${RUN_ID}`, title: "입찰 변경 비교", dataScope: "cumulative", editScope: "최종 Go/No-Go 저장 가능", runSelectorVisible: false },
  { name: "pre-specs", path: `/pre-specs?run=${RUN_ID}`, title: "사전규격", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "pre-spec detail", path: `/pre-specs/991?run=${RUN_ID}`, title: "사전규격", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "judgments list", path: `/judgments?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", editScope: "판정 원문 읽기 전용", runSelectorVisible: true },
  { name: "judgments detail", path: `/judgments/29?run=${RUN_ID}`, title: "공고 판정 이력", dataScope: "run", editScope: "판정 원문 읽기 전용", runSelectorVisible: true },
  { name: "reviews", path: `/reviews?run=${RUN_ID}`, title: "담당자 리뷰 기록", dataScope: "run", editScope: null, runSelectorVisible: true },
  { name: "profile", path: `/profile?run=${RUN_ID}`, title: "회사 프로필", dataScope: "cumulative", editScope: "원본 문서에서 관리", runSelectorVisible: false },
  { name: "metrics", path: `/metrics?run=${RUN_ID}`, title: "검증 지표", dataScope: "run", editScope: null, runSelectorVisible: true },
  { name: "quality gates", path: `/quality-gates?run=${RUN_ID}`, title: "품질 게이트", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "policies", path: `/policies?run=${RUN_ID}`, title: "판정 정책", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "runs", path: `/runs?run=${RUN_ID}`, title: "수집 실행", dataScope: "run", editScope: null, runSelectorVisible: true },
  { name: "attachments", path: `/attachments?run=${RUN_ID}`, title: "첨부 확보", dataScope: "run", editScope: null, runSelectorVisible: true },
  { name: "operations", path: `/operations?run=${RUN_ID}`, title: "상시 운영", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
  { name: "deep review", path: `/deep-reviews/fixture-review?run=${RUN_ID}`, title: "심층 검토 보고서", dataScope: "cumulative", editScope: null, runSelectorVisible: false },
];

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

for (const context of routeContexts) {
  test(`${context.name} route context`, async ({ page }) => {
    await page.goto(context.path);

    const topbar = page.locator("header.topbar");
    await expect(topbar.locator("h1")).toHaveText(context.title);
    await expect(topbar).toHaveAttribute("data-route-data-scope", context.dataScope);

    const runSelector = page.getByLabel("실행 회차", { exact: true });
    if (context.runSelectorVisible) {
      await expect(runSelector).toBeVisible();
      await expect(runSelector).toHaveValue(RUN_ID);
    } else {
      await expect(runSelector).toHaveCount(0);
    }

    const editScope = topbar.locator(".topbar-status");
    if (context.editScope) {
      await expect(editScope).toHaveText(context.editScope);
      await expect(editScope).toHaveAttribute("aria-label", `페이지별 편집 범위: ${context.editScope}`);
    } else {
      await expect(editScope).toHaveCount(0);
    }
  });
}

test("직접 진입한 lazy route가 metadata와 실제 화면을 함께 렌더링한다", async ({ page }) => {
  await page.goto(`/opportunities?run=${RUN_ID}`);

  const topbar = page.locator("header.topbar");
  await expect(topbar.locator("h1")).toHaveText("사업기회");
  await expect(topbar).toHaveAttribute("data-route-data-scope", "cumulative");
  await expect(topbar.locator(".topbar-status")).toHaveText("추적 상태 저장 가능");
  await expect(page.getByLabel("실행 회차", { exact: true })).toHaveCount(0);
  await expect(page.locator(".opportunities-page")).toBeVisible();
});

test("SPA 내부 link click으로 lazy route에 들어가도 metadata와 화면이 유지된다", async ({ page }) => {
  await page.goto(`/judgments/29?run=${RUN_ID}`);
  await page.getByRole("link", { name: "검토 대기열" }).click();

  const topbar = page.locator("header.topbar");
  await expect(topbar.locator("h1")).toHaveText("검토 대기열");
  await expect(topbar).toHaveAttribute("data-route-data-scope", "run");
  await expect(topbar.locator(".topbar-status")).toHaveText("리뷰 저장 가능");
  await expect(page.getByLabel("실행 회차", { exact: true })).toHaveValue(RUN_ID);
  await expect(page.locator(".queue-page")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("run")).toBe(RUN_ID);
});

test("누적 화면은 회차 API 실패와 무관하게 열린다", async ({ page }) => {
  let runRequestCount = 0;
  await page.route("**/api/runs**", async (route) => {
    runRequestCount += 1;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "run fixture unavailable" }),
    });
  });

  await page.goto(`/opportunities?run=${RUN_ID}`);
  await expect(page.locator("header.topbar h1")).toHaveText("사업기회");
  await expect(page.getByLabel("실행 회차", { exact: true })).toHaveCount(0);
  await expect(page.locator(".opportunities-page")).toBeVisible();
  await expect(page.locator(".shell-notice")).toHaveCount(0);
  expect(runRequestCount).toBe(0);
  expect(new URL(page.url()).searchParams.get("run")).toBe(RUN_ID);
});
