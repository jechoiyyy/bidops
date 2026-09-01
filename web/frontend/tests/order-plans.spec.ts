import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlans } from "./api-mock";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("기본 목록은 최신 성공/부분 성공 실행의 relevant·uncertain만 보여주고 두 신호를 분리한다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  await expect(page.locator("section.c2-page").getByRole("heading", { name: "발주계획 C-2 검토" })).toBeVisible();
  await expect(page.locator(".c2-plan-card")).toHaveCount(2);
  await expect(page.locator(".c2-plan-card").first()).toContainText("relevant");
  await expect(page.locator(".c2-plan-card").nth(1)).toContainText("uncertain");
  await expect(page.locator(".c2-signal-bm25").first()).toContainText("nearest capability");
  await expect(page.locator(".c2-signal-qwen").first()).toContainText("Qwen relevance 신호");
  await expect(page.locator(".c2-plan-card").first()).toContainText("125,000,000");
  await expect(page.locator(".c2-plan-card").first()).toContainText("데이터 플랫폼 구축·운영");
  await expect(page.locator(".c2-execution-panel")).toContainText("policy/binding");
  await expect(page.locator(".c2-execution-panel")).toContainText("qwen3.8-27B");
  await expect(page.locator(".c2-execution-panel")).toContainText("prompt-v3");
  await expect(page.locator(".c2-execution-panel")).toContainText("profile-v1");
  await expect(page.locator(".c2-execution-panel")).toContainText("qwen_timeout");
  await expect(page.locator(".c2-execution-panel")).toContainText("120,000");
});

test("C-2의 네 가지 결과 필터는 계약 상태를 섞지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  await page.getByRole("button", { name: /전체/ }).click();
  await expect(page).toHaveURL(/filter=all/);
  await expect(page.locator(".c2-plan-card")).toHaveCount(6);

  await page.getByRole("button", { name: /BM25 탈락/ }).click();
  await expect(page).toHaveURL(/filter=bm25-filtered-out/);
  await expect(page.locator(".c2-plan-card")).toHaveCount(1);
  await expect(page.locator(".c2-plan-card")).toContainText("BM25 탈락");

  await page.getByRole("button", { name: /Qwen 비관련/ }).click();
  await expect(page).toHaveURL(/filter=qwen-not-relevant/);
  await expect(page.locator(".c2-plan-card")).toHaveCount(1);
  await expect(page.locator(".c2-plan-card")).toContainText("not_relevant");

  await page.getByRole("button", { name: /실패/ }).click();
  await expect(page).toHaveURL(/filter=failure/);
  await expect(page.locator(".c2-plan-card")).toHaveCount(2);
  await expect(page.locator(".c2-plan-card").first()).toContainText("실패");
});

test("1200건 결과에서 review·failure 필터와 페이지 경계를 전체 모집단 기준으로 계산한다", async ({ page }) => {
  await mockOrderPlans(page, "large");
  await page.goto("/order-plans");

  await expect(page.locator(".c2-plan-card")).toHaveCount(500);
  await expect(page.locator(".c2-results-heading")).toContainText("현재 필터 결과 900건");
  await expect(page.locator(".c2-pagination")).toContainText("1–500 / 900");
  await page.getByRole("button", { name: "다음" }).click();
  await expect(page.locator(".c2-plan-card")).toHaveCount(400);
  await expect(page.locator(".c2-pagination")).toContainText("501–900 / 900");

  await page.getByRole("button", { name: /실패/ }).click();
  await expect(page.locator(".c2-plan-card")).toHaveCount(300);
  await expect(page.locator(".c2-plan-card").first()).toContainText("OP-2026-20900");
  await expect(page.locator(".c2-pagination")).toHaveCount(0);
});

test("상세는 관측·실행·실패 투영·artifact와 append-only 사람 feedback을 보여준다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans/101");

  await expect(page.getByRole("heading", { name: "관측 history" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "screening execution history" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "사람 피드백 revision history" })).toBeVisible();
  await expect(page.locator(".c2-history-card")).toHaveCount(2);
  await expect(page.locator(".c2-history-card").first()).toContainText("batch-20260901-01");
  await expect(page.locator(".c2-history-card").first()).toContainText("attempt 2");
  await expect(page.locator(".c2-history-card").first()).toContainText("nearest capability");
  await expect(page.locator(".c2-history-card").first()).toContainText("qwen3.8-27B");
  await expect(page.locator(".c2-history-card").first()).toContainText("timeout");
  await expect(page.locator(".c2-history-card").first()).toContainText("null (미측정)");
  await expect(page.locator(".c2-artifact-summary").first()).toContainText("screening_input");
  await expect(page.getByText("response_object_ref", { exact: true })).toHaveCount(0);
  await expect(page.getByText("plan_ids_jsonb", { exact: true })).toHaveCount(0);
  await expect(page.locator(".c2-feedback-history")).toContainText("revision 1");

  await page.getByLabel("relevance").selectOption("uncertain");
  await page.getByLabel("담당자 claimed name").fill("Phase4 tester");
  await page.getByRole("button", { name: "새 revision 저장" }).click();
  await expect(page.getByText("새 사람 피드백 revision을 저장했습니다.")).toBeVisible();
  await expect(page.locator(".c2-feedback-history > li")).toHaveCount(2);

  expect(trace.feedbackPosts).toHaveLength(1);
  expect(trace.feedbackPosts[0].body).toMatchObject({
    schema_version: "feedback-create-request.v1",
    producer: "human-review-client",
    consumer: "review-api",
    execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010101",
    relevance: "uncertain",
    expected_revision: 1,
  });
  expect(trace.feedbackPosts[0].headers["x-bidops-actor-name"]).toBe("Phase4 tester");
});

test("실패·결과 없음·중지/비허용 상태를 성공 결과로 바꾸지 않는다", async ({ page }) => {
  await mockOrderPlans(page, "failure");
  await page.goto("/order-plans");
  await expect(page.getByText("검토에 사용할 성공/부분 성공 결과가 없습니다.")).toBeVisible();
  await expect(page.locator(".empty-state")).toContainText("실패");

  await mockOrderPlans(page, "no-results");
  await page.goto("/order-plans");
  await expect(page.getByText("C-2 실행 결과가 없습니다.")).toBeVisible();

  await mockOrderPlans(page, "live-disabled");
  await page.goto("/order-plans");
  await expect(page.locator(".c2-execution-panel")).toContainText("policy/binding 비허용");
});
