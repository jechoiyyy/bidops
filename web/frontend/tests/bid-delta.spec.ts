import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockBidDelta, type BidDeltaMockOptions } from "./api-mock";

const comparisonId = "77777777-7777-4777-8777-777777777777";

const bidOpportunity = {
  id: 501,
  tracking_status: "계속 추적",
  tracking_reason: "입찰공고를 확인하고 변경을 비교합니다.",
  tracking_selected_by: "기존 담당자",
  tracking_selected_at: "2026-08-30T01:00:00Z",
  recheck_signal: true,
  recheck_signal_at: "2026-08-31T03:00:00Z",
  recheck_signal_link_id: 5011,
  first_registered_stage: "pre_spec",
  links: [{
    id: 5011,
    stage: "notice",
    link_type: "official",
    status: "확정",
    search_strategy: null,
    attempted_strategies: [],
    agency_match: null,
    last_searched_at: null,
    evidence_external_no: null,
    evidence_bid_no: null,
    human_decision: null,
    reviewer_name: null,
    reviewed_at: null,
    review_reason: null,
    record_type: "bid_notice",
    record_id: 1102,
    notice_id: 1102,
    order_plan_id: null,
    source_type: "bid_notice",
    title: "접근성 검증 입찰공고",
    agency: "테스트 조달기관",
    external_id: "R26BK00267196",
    record_external_id: "R26BK00267196",
  }],
};

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

async function openComparison(page: Page, options: BidDeltaMockOptions = {}) {
  await mockBidDelta(page, options);
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "비교 상세", exact: true })).toBeVisible();
}

async function mockOpportunity(page: Page): Promise<void> {
  await page.route("**/api/opportunities/501", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(bidOpportunity) });
      return;
    }
    await route.fallback();
  });
}

test.describe("bid-delta calculation status", () => {
  for (const calculationStatus of ["pending", "running", "completed", "failed"] as const) {
    test(`${calculationStatus} 상태를 결과 상태와 분리해 표현한다`, async ({ page }) => {
      await openComparison(page, { calculationStatus });
      const calculation = page.locator('[aria-labelledby="bid-delta-calculation-title"]');
      await expect(calculation).toContainText(calculationStatus === "pending" ? "대기 중" : calculationStatus === "running" ? "계산 중" : calculationStatus === "completed" ? "계산 완료" : "계산 실패");
      if (calculationStatus === "pending" || calculationStatus === "running") {
        await expect(page.getByText("계산 담당 worker는 아직 운영에 없습니다.", { exact: false })).toBeVisible();
      } else {
        await expect(page.getByText("계산 담당 worker는 아직 운영에 없습니다.", { exact: false })).toHaveCount(0);
      }
      await expect(page.getByRole("button", { name: "최종 결정 저장", exact: true })).toBeDisabled();
      if (calculationStatus === "failed") {
        await expect(page.getByRole("button", { name: "재시도", exact: true })).toBeVisible();
      } else {
        await expect(page.getByRole("button", { name: "재시도", exact: true })).toHaveCount(0);
      }
    });
  }
});

test("pending → running → completed polling은 terminal에서 멈춘다", async ({ page }) => {
  const trace = await mockBidDelta(page, { pollingStatuses: ["pending", "running", "completed"] });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByText("변경 있음", { exact: false })).toBeVisible({ timeout: 6_000 });
  await expect.poll(() => trace.comparisonGets, { timeout: 6_000 }).toBeGreaterThanOrEqual(3);
  const terminalGets = trace.comparisonGets;
  await page.waitForTimeout(1_300);
  expect(trace.comparisonGets).toBe(terminalGets);
});

test("후보가 없으면 변경 없음이 아니라 이유가 있는 EmptyState를 표시한다", async ({ page }) => {
  await mockBidDelta(page, { baselineCandidates: false, comparisonCandidates: false });
  await page.goto("/opportunities/501/bid-delta");
  await expect(page.getByText("기준 후보 없음", { exact: true })).toBeVisible();
  await expect(page.getByText("비교 후보 없음", { exact: true })).toBeVisible();
  await expect(page.getByText("이를 변경 없음으로 해석하지 않습니다.", { exact: false })).toHaveCount(2);
  await expect(page.getByRole("button", { name: "비교 시작", exact: true })).toBeDisabled();
});

for (const resultStatus of ["changed", "unchanged", "unknown", "failed"] as const) {
  test(`결과 상태 ${resultStatus}는 계산 상태와 별도로 보존된다`, async ({ page }) => {
    await openComparison(page, { calculationStatus: "completed", resultStatus });
    const result = page.locator('[aria-labelledby="bid-delta-result-title"]');
    await expect(result).toContainText(resultStatus === "changed" ? "변경 있음" : resultStatus === "unchanged" ? "변경 없음" : resultStatus === "unknown" ? "판단 불가" : "분석 실패");
    const firstItem = page.locator(".bid-delta-item").first();
    if (resultStatus === "unknown" || resultStatus === "failed") {
      await expect(firstItem).toContainText(resultStatus === "unknown" ? "판단 불가" : "분석 실패");
      await expect(firstItem.locator(".status-badge").first()).not.toContainText("변경 없음");
      await expect(firstItem).toContainText("오류 코드");
    }
  });
}

test("양쪽 input fence와 evidence locator를 한 쌍으로 표시한다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  await expect(page.getByText("22222222-2222-4222-8222-222222222222", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("55555555-5555-4555-8555-555555555555", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".bid-delta-evidence-pair")).toHaveCount(7);
  await expect(page.locator(".bid-delta-evidence-pair").first()).toContainText("기준 원문 1");
  await expect(page.locator(".bid-delta-evidence-pair").first()).toContainText("비교 원문 1");
  await expect(page.locator(".bid-delta-evidence-pair").first()).toContainText("표 table-1");
});

test("사람 결정은 자동 선택되지 않고 저장 전에는 form 초안을 유지한다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  const decision = page.getByLabel("최종 결정", { exact: true });
  await expect(decision).toHaveValue("");
  await expect(page.getByRole("button", { name: "최종 결정 저장", exact: true })).toBeDisabled();
  await page.getByLabel("최종 결정 담당자 이름").fill("홍길동");
  await decision.selectOption("go");
  await page.getByLabel("결정 이유", { exact: true }).fill("양쪽 원문을 확인하고 참여를 결정했습니다.");
  await expect(page.getByRole("button", { name: "최종 결정 저장", exact: true })).toBeEnabled();
});

test("최종 결정 payload는 actor header와 모든 comparison fence를 포함한다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "unchanged" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "비교 상세", exact: true })).toBeVisible();
  await page.getByLabel("최종 결정 담당자 이름").fill("홍길동");
  await page.getByLabel("최종 결정", { exact: true }).selectOption("no_go");
  await page.getByLabel("결정 이유", { exact: true }).fill("확인된 범위에서 참여하지 않기로 결정했습니다.");
  await page.getByRole("button", { name: "최종 결정 저장", exact: true }).click();
  await expect(page.getByText("No-Go 최종 결정을 append-only로 저장했습니다.", { exact: true })).toBeVisible();
  expect(trace.finalDecisionPosts).toHaveLength(1);
  expect(trace.finalDecisionPosts[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  expect(trace.finalDecisionPosts[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
  expect(trace.finalDecisionPosts[0].body).toMatchObject({
    schema_version: "bidops.bid-final-decision-create.v1",
    expected_comparison_version: 2,
    expected_result_sha256: "e".repeat(64),
    baseline_document_version_id: "22222222-2222-4222-8222-222222222222",
    comparison_document_version_id: "55555555-5555-4555-8555-555555555555",
    supersedes_final_decision_id: null,
    decision: "no_go",
    reason: "확인된 범위에서 참여하지 않기로 결정했습니다.",
  });
  expect(typeof trace.finalDecisionPosts[0].body.request_id).toBe("string");
  expect(String(trace.finalDecisionPosts[0].body.request_id)).toMatch(/^[0-9a-f-]{36}$/);
  await expect(page.getByLabel("최종 결정 담당자 이름")).toHaveValue("");
});

test("실패 비교 재시도는 expected version을 보내고 이전 attempt를 보존한다", async ({ page }) => {
  const retryTrace = await mockBidDelta(page, { calculationStatus: "failed", resultStatus: "failed" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("button", { name: "재시도", exact: true })).toBeVisible();
  await page.getByLabel("재시도 담당자 이름").fill("재시도 담당자");
  await page.getByRole("button", { name: "재시도", exact: true }).click();
  await expect(page.getByText("새 계산 attempt를 추가했습니다. 이전 attempt는 보존됩니다.", { exact: true })).toBeVisible();
  expect(retryTrace.retryPosts[0].body).toMatchObject({ schema_version: "bidops.bid-delta-attempt-create.v1", expected_comparison_version: 2 });
  expect(String(retryTrace.retryPosts[0].body.request_id)).toMatch(/^[0-9a-f-]{36}$/);
  await expect(page.getByText("Attempt 1회", { exact: true })).toBeVisible();
  await expect(page.getByText("Attempt 2회", { exact: true })).toBeVisible();
});

test("과거 final decision 이력은 현재성 문자와 함께 append-only로 모두 보인다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed", withHistory: true });
  const history = page.locator(".bid-delta-decision-history-list > li");
  await expect(history).toHaveCount(2);
  await expect(history.nth(0)).toContainText("No-Go");
  await expect(history.nth(1)).toContainText("Go");
  await expect(history.nth(0)).toContainText("현재 유효");
  await expect(page.locator(".bid-delta-currentness").first()).toContainText("현재 유효");
});

test("요청 conflict는 typed code를 표시하고 최신 상태를 다시 불러와도 입력을 지우지 않는다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed", finalDecisionErrorCode: "bid_delta_comparison_stale" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "비교 상세", exact: true })).toBeVisible();
  await page.getByLabel("최종 결정 담당자 이름").fill("홍길동");
  await page.getByLabel("최종 결정", { exact: true }).selectOption("go");
  await page.getByLabel("결정 이유", { exact: true }).fill("최신 상태에서도 검토할 이유");
  await page.getByRole("button", { name: "최종 결정 저장", exact: true }).click();
  await expect(page.getByText("오류 코드 bid_delta_comparison_stale", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "최신 상태 다시 불러오기", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "최신 상태 다시 불러오기", exact: true }).click();
  await expect(page.getByText("최신 비교와 현재성을 다시 불러왔습니다. 입력한 초안은 유지했습니다.", { exact: true })).toBeVisible();
  await expect(page.getByLabel("최종 결정 담당자 이름")).toHaveValue("홍길동");
  await expect(page.getByLabel("최종 결정", { exact: true })).toHaveValue("go");
  await expect(page.getByLabel("결정 이유", { exact: true })).toHaveValue("최신 상태에서도 검토할 이유");
  expect(trace.workspaceGets).toBeGreaterThanOrEqual(2);
});

test("사업기회 상세 → delta → 저장 → 상세 이동 흐름을 유지한다", async ({ page }) => {
  await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed" });
  await mockOpportunity(page);
  await page.goto("/opportunities/501");
  await page.getByRole("link", { name: "변경 비교", exact: true }).click();
  await expect(page).toHaveURL(/\/opportunities\/501\/bid-delta$/);
  await page.getByRole("link", { name: /비교 #1/ }).click();
  await page.getByLabel("최종 결정 담당자 이름").fill("홍길동");
  await page.getByLabel("최종 결정", { exact: true }).selectOption("go");
  await page.getByLabel("결정 이유", { exact: true }).fill("원문 확인 후 참여합니다.");
  await page.getByRole("button", { name: "최종 결정 저장", exact: true }).click();
  await expect(page.getByText("Go 최종 결정을 append-only로 저장했습니다.", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "← 사업기회 상세", exact: true }).click();
  await expect(page).toHaveURL(/\/opportunities\/501$/);
  await expect(page.getByRole("heading", { name: "사업기회 상세 #501", exact: true })).toBeVisible();
});

test("미저장 최종 결정 초안은 beforeunload와 SPA 이동을 보호한다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  await page.getByLabel("최종 결정 담당자 이름").fill("홍길동");
  await page.getByLabel("최종 결정", { exact: true }).selectOption("go");
  await page.getByLabel("결정 이유", { exact: true }).fill("아직 저장하지 않은 검토 초안");
  expect(await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  })).toBe(true);
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("link", { name: "← 사업기회 상세", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/opportunities/501/bid-delta\\?comparison=${comparisonId}`));
  await expect(page.getByText("저장되지 않은 입찰 최종 결정 초안이 있습니다.", { exact: false })).toBeVisible();
});
