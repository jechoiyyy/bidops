import { expect, test } from "@playwright/test";
import { mockApi, mockDailyCollectionStatus, mockOrderPlans, mockPreSpecs } from "./api-mock";
import { mockOpportunities } from "./opportunities-fixtures";

/**
 * 패널 헤더의 수집 상태(2026-11-20). 판정은 `GET /api/daily-collection-status`가 하고 화면은 옮겨 적기만
 * 한다. `complete`만 "수집 완료"이고 나머지는 사실대로 쓰며 실행 상태로 가는 링크를 단다. 조회 실패는
 * 숨기지 않는다. 가짜 응답의 모양은 백엔드 strict 테스트의 실제 응답에서 옮겼다(`api-mock.ts`).
 */

const status = (page: import("@playwright/test").Page) => page.locator('header.topbar [data-testid="collection-status"]');

test("발주계획은 발주계획 트랙이 완료일 때만 수집 완료와 기준일을 쓰고 링크를 달지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await expect(status(page)).toHaveAttribute("data-state", "complete");
  await expect(status(page)).toHaveText("수집 완료 · 9월 1일 기준");
  await expect(status(page).getByRole("link")).toHaveCount(0);
});

test("사전규격은 공고 트랙의 적재 경고를 수집 확인 필요로 쓰고 실행 상태로 보낸다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecs(page);
  await mockDailyCollectionStatus(page, { notices: { state: "incomplete", reasons: ["ingest_warnings"], warning_count: 3 } });
  await page.goto("/pre-specs");
  await expect(status(page)).toHaveAttribute("data-state", "incomplete");
  await expect(status(page)).toContainText("수집 확인 필요 · 9월 1일 기준 · 적재 경고 3건");
  await expect(status(page)).not.toContainText("수집 완료");
  await expect(status(page).getByRole("link", { name: "실행 상태" })).toHaveAttribute("href", "/run-status");
});

test("사업기회는 공고 트랙 기록이 없으면 수집 기록 없음으로 쓰고 완료로 접지 않는다", async ({ page }) => {
  await mockApi(page);
  await mockOpportunities(page);
  await mockDailyCollectionStatus(page, {
    notices: { state: "missing", reasons: ["no_run"], run_id: null, collected_at: null, warning_count: null, latest_basis_date: "2026-08-31" },
  });
  await page.goto("/opportunities");
  await expect(status(page)).toHaveAttribute("data-state", "missing");
  await expect(status(page)).toContainText("수집 기록 없음 · 9월 1일 기준");
  await expect(status(page)).toHaveAttribute("title", "기록이 있는 가장 늦은 기준일 8월 31일");
  await expect(status(page).getByRole("link", { name: "실행 상태" })).toBeVisible();
});

test("수집 상태 조회가 실패하면 표시를 숨기지 않고 확인할 수 없다고 말한다", async ({ page }) => {
  await mockOrderPlans(page);
  await mockDailyCollectionStatus(page, { status: 500 });
  await page.goto("/order-plans");
  await expect(status(page)).toHaveAttribute("data-state", "error");
  await expect(status(page)).toContainText("수집 상태를 확인할 수 없어요");
  await expect(status(page)).not.toContainText("수집 완료");
});
