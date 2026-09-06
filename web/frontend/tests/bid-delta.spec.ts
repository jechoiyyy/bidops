import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockBidDelta, type BidDeltaMockOptions } from "./api-mock";

/** 상세 화면은 자체 브레드크럼을 갖지 않는다. 되돌아가는 길은 상단 경로
 *  (`nav[aria-label="현재 위치"]`)와 우측 레일의 목록 링크뿐이다. */
function routeCrumbLink(page: Page, name: string) {
  return page.locator('nav[aria-label="현재 위치"]').getByRole("link", { name, exact: true });
}

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

// 되돌릴 수 없는 최종 Go/No-Go는 확인 단계를 거쳐야 요청이 나간다. 헤더·본문의
// 저장 버튼은 확인 다이얼로그를 열 뿐이고, 실제 저장은 이 확인 버튼이 보낸다.
async function confirmFinalDecision(page: Page, label: string): Promise<void> {
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: label, exact: true }).click();
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
        await expect(page.getByText("계산을 실행하는 프로그램이 아직 운영에 없습니다.", { exact: false })).toBeVisible();
      } else {
        await expect(page.getByText("계산을 실행하는 프로그램이 아직 운영에 없습니다.", { exact: false })).toHaveCount(0);
      }
      await expect(page.getByRole("button", { name: "결정 저장", exact: true })).toBeDisabled();
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
  await expect(page.getByRole("button", { name: "결정 저장", exact: true })).toBeDisabled();
  await page.getByLabel("최종 결정 담당자 이름").fill("홍길동");
  await decision.selectOption("go");
  await page.getByLabel("결정 이유", { exact: true }).fill("양쪽 원문을 확인하고 참여를 결정했습니다.");
  await expect(page.getByRole("button", { name: "결정 저장", exact: true })).toBeEnabled();
});

test("최종 결정 payload는 actor header와 모든 comparison fence를 포함한다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "unchanged" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "비교 상세", exact: true })).toBeVisible();
  await page.getByLabel("최종 결정 담당자 이름").fill("홍길동");
  await page.getByLabel("최종 결정", { exact: true }).selectOption("no_go");
  await page.getByLabel("결정 이유", { exact: true }).fill("확인된 범위에서 참여하지 않기로 결정했습니다.");
  await page.getByRole("button", { name: "결정 저장", exact: true }).click();
  await confirmFinalDecision(page, "No-Go로 최종 결정 저장");
  await expect(page.getByText("No-Go 최종 결정을 저장했습니다. 이전 결정은 그대로 남습니다.", { exact: true })).toBeVisible();
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
  await expect(page.getByText("새 계산 회차를 시작했습니다. 이전 회차는 그대로 남습니다.", { exact: true })).toBeVisible();
  expect(retryTrace.retryPosts[0].body).toMatchObject({ schema_version: "bidops.bid-delta-attempt-create.v1", expected_comparison_version: 2 });
  expect(String(retryTrace.retryPosts[0].body.request_id)).toMatch(/^[0-9a-f-]{36}$/);
  await expect(page.getByText("1회차", { exact: true })).toBeVisible();
  await expect(page.getByText("2회차", { exact: true })).toBeVisible();
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
  await page.getByRole("button", { name: "결정 저장", exact: true }).click();
  await confirmFinalDecision(page, "Go로 최종 결정 저장");
  // 저장에 실패하면 다이얼로그는 닫히고 기존 인라인 오류 표시가 그대로 보인다.
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.getByText("오류 코드 bid_delta_comparison_stale", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "최신 상태 다시 불러오기", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "최신 상태 다시 불러오기", exact: true }).click();
  await expect(page.getByText("최신 비교와 최신 여부를 다시 불러왔습니다. 입력한 초안은 그대로 두었습니다.", { exact: true })).toBeVisible();
  await expect(page.getByLabel("최종 결정 담당자 이름")).toHaveValue("홍길동");
  await expect(page.getByLabel("최종 결정", { exact: true })).toHaveValue("go");
  await expect(page.getByLabel("결정 이유", { exact: true })).toHaveValue("최신 상태에서도 검토할 이유");
  expect(trace.workspaceGets).toBeGreaterThanOrEqual(2);
});

test("사업 추적 상세 → delta → 저장 → 상세 이동 흐름을 유지한다", async ({ page }) => {
  await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed" });
  await mockOpportunity(page);
  await page.goto("/opportunities/501");
  await page.getByRole("link", { name: "변경 비교", exact: true }).click();
  await expect(page).toHaveURL(/\/opportunities\/501\/bid-delta$/);
  await page.getByRole("link", { name: /비교 #1/ }).click();
  await page.getByLabel("최종 결정 담당자 이름").fill("홍길동");
  await page.getByLabel("최종 결정", { exact: true }).selectOption("go");
  await page.getByLabel("결정 이유", { exact: true }).fill("원문 확인 후 참여합니다.");
  await page.getByRole("button", { name: "결정 저장", exact: true }).click();
  await confirmFinalDecision(page, "Go로 최종 결정 저장");
  await expect(page.getByText("Go 최종 결정을 저장했습니다. 이전 결정은 그대로 남습니다.", { exact: true })).toBeVisible();
  await routeCrumbLink(page, "#501").click();
  await expect(page).toHaveURL(/\/opportunities\/501$/);
  await expect(page.getByRole("heading", { name: "사업 추적 상세 #501", exact: true })).toBeVisible();
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
  // 이탈 확인은 브라우저 confirm이 아니라 화면 다이얼로그다. 같은 문구가 본문
  // 인라인 안내에도 있으므로 alertdialog 안으로 좁혀 찾는다.
  await routeCrumbLink(page, "#501").click();
  const unsavedDialog = page.getByRole("alertdialog");
  await expect(unsavedDialog).toBeVisible();
  await expect(unsavedDialog).toContainText("저장되지 않은 입찰 최종 결정 초안이 있습니다.");
  await unsavedDialog.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/opportunities/501/bid-delta\\?comparison=${comparisonId}`));
  await expect(page.getByLabel("결정 이유", { exact: true })).toHaveValue("아직 저장하지 않은 검토 초안");
});

// docs/design/PLAN.md 4단계 완료 게이트: 되돌릴 수 없는 최종 Go/No-Go 저장은
// 요약 헤더에 고정되어 스크롤 위치와 무관하게 첫 화면에서 보여야 한다.
test("최종 결정 저장 액션은 본문을 끝까지 스크롤해도 뷰포트 안에 남는다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  const headerSave = page.locator(".detail-skeleton-head").getByRole("button", { name: "결정 저장", exact: true });
  await expect(headerSave).toBeInViewport();
  await page.evaluate(() => document.querySelector(".page-canvas")?.scrollTo(0, 999_999));
  await expect(headerSave).toBeInViewport();
});

// 시안 정본(docs/design/mockups/screens_more.py biddelta_screen)은 헤더에
// 액션만 두고 입력 폼은 본문에 둔다. 폼째로 sticky 헤더에 올린 구현은 노트북
// 폭에서 헤더가 뷰포트의 70%를 차지해, 액션은 보이지만 정작 판단 근거인
// 범주별 분석이 가려졌다. 헤더가 뷰포트의 3분의 1을 넘지 않도록 고정한다.
test("고정 헤더가 노트북 폭에서 뷰포트를 과도하게 차지하지 않는다", async ({ page }, testInfo) => {
  // 좁은 폭은 PRD §5가 인정하는 degraded case다(상세가 목록을 덮고 레일이
  // 본문 아래로 내려간다). 이 비율 게이트는 본문과 레일이 함께 보여야 하는
  // 960px 이상에서만 뜻이 있다.
  test.skip((testInfo.project.use.viewport?.width ?? 0) < 960, "노트북 폭 이상에서만 검사한다");
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  const ratio = await page.evaluate(() => {
    const head = document.querySelector(".detail-skeleton-head") as HTMLElement | null;
    return head ? head.getBoundingClientRect().height / window.innerHeight : 1;
  });
  expect(ratio).toBeLessThan(0.34);
});

// 헤더의 저장 버튼은 본문 폼을 form 속성으로 submit한다. 같은 finalReady를
// 쓰므로 전제조건이 헤더와 본문에서 갈라지지 않는다.
test("헤더 저장 버튼은 본문 결정 폼과 같은 전제조건을 쓴다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  const headerSave = page.locator(".detail-skeleton-head").getByRole("button", { name: "결정 저장", exact: true });
  const formSave = page.locator(".bid-delta-final-decision-panel").getByRole("button", { name: "최종 결정 저장", exact: true });
  await expect(headerSave).toHaveAttribute("form", "bid-delta-final-form");
  await expect(headerSave).toBeDisabled();
  await expect(formSave).toBeDisabled();

  await page.getByLabel("최종 결정 담당자 이름").fill("홍길동");
  await page.getByLabel("최종 결정", { exact: true }).selectOption("go");
  await page.getByLabel("결정 이유", { exact: true }).fill("추정가격 하락 확인");
  await expect(headerSave).toBeEnabled();
  await expect(formSave).toBeEnabled();
});

// 전제조건(계산 완료·결과 failed 아님)을 만족하지 못해 비활성인 상태에서도
// 버튼과 비활성 사유가 스크롤 없이 함께 보여야 한다 — 버튼만 헤더에 띄우고
// 이유를 본문 깊숙이 남기지 않는다.
test("계산 대기 중인 비교는 비활성 최종 결정 액션과 사유가 스크롤 없이 함께 보인다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "pending" });
  const saveButton = page.locator(".detail-skeleton-head").getByRole("button", { name: "결정 저장", exact: true });
  await expect(saveButton).toBeInViewport();
  await expect(saveButton).toBeDisabled();
  await expect(page.locator("#bid-delta-final-disabled")).toBeInViewport();
  await expect(page.locator("#bid-delta-final-disabled")).toContainText("계산이 완료될 때까지");
});

// 우측 레일은 이력과 연결만 담고 결정 액션을 복제하지 않는다.
test("우측 레일은 attempt·결정 이력과 연결 링크만 담고 최종 결정 액션을 복제하지 않는다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed", withHistory: true });
  const rail = page.locator(".detail-skeleton-rail");
  await expect(page.locator('[data-review-primitive="sticky-decision-header"]')).toBeVisible();
  await expect(page.locator('[data-review-primitive="history-link-rail"]')).toHaveCount(1);
  await expect(page.locator('[data-review-primitive="decision-action"]')).toHaveCount(1);
  await expect(rail.getByRole("heading", { name: "계산 회차 이력", exact: true })).toBeVisible();
  await expect(rail.getByRole("heading", { name: "최종 Go/No-Go 저장 이력", exact: true })).toBeVisible();
  await expect(rail.getByRole("heading", { name: "최종 결정 최신 여부", exact: true })).toBeVisible();
  await expect(rail.getByRole("link", { name: "사업 추적 상세 →", exact: true })).toBeVisible();
  await expect(rail.getByRole("button", { name: "결정 저장", exact: true })).toHaveCount(0);
});

// ── PLAN 단계 F 작업 2·3 ───────────────────────────────────────────────────

test("범주 목록 바로 위에 무엇을 언제 비교했는지 남긴다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });

  const basis = page.locator(".bid-delta-basis");
  await expect(basis).toBeVisible();
  await expect(basis).toContainText("기준 사전규격");
  await expect(basis).toContainText("대상 입찰공고");
  await expect(basis).toContainText("문서 묶음 상태");
  await expect(basis).toContainText("계산 시각");
  await expect(basis).toContainText("범주 정책");
});

test("저장 조건 셋이 결정 폼 바로 위에서 현재 값과 함께 보인다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });

  const conditions = page.locator(".bid-delta-save-conditions");
  await expect(conditions.locator("li")).toHaveCount(3);
  await expect(conditions).toContainText("completed");
  await expect(conditions).toContainText("분석 실패가 아니어야");
  // 보류는 최종 결정 값이 아니며 기록을 만들지 않는다(단계 F 작업 4).
  await expect(conditions).toContainText("보류는 최종 결정 값이 아니며 저장되지 않습니다");
  // 결정 select에도 보류는 없다.
  const options = await page.getByLabel("최종 결정", { exact: true }).locator("option").allInnerTexts();
  expect(options).toEqual(["선택하십시오", "Go", "No-Go"]);
});

test("계산 실패는 헤더에서 비교 재계산으로, 본문 재시도 입력으로 데려간다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "failed", resultStatus: "failed" });

  const header = page.locator('[data-review-primitive="sticky-decision-header"]');
  const recalculate = header.getByRole("button", { name: "비교 재계산", exact: true });
  await expect(recalculate).toBeInViewport();
  // 재계산도 담당자 이름을 받으므로 헤더에서 바로 실행하지 않는다.
  await expect(header.getByLabel("재시도 담당자 이름")).toHaveCount(0);

  await recalculate.click();
  await expect(page.getByLabel("재시도 담당자 이름")).toBeFocused();
});

// 화면이 "되돌릴 수 없습니다"라고 쓰면서 submit 한 번에 요청을 보내면 그 문장은
// 경고가 아니라 사후 설명이다. 최종 Go/No-Go는 확인 단계를 거쳐야 나간다.
test("최종 결정은 확인 없이는 요청이 나가지 않고 취소하면 초안만 남는다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "비교 상세", exact: true })).toBeVisible();
  await page.getByLabel("최종 결정 담당자 이름").fill("홍길동");
  await page.getByLabel("최종 결정", { exact: true }).selectOption("go");
  await page.getByLabel("결정 이유", { exact: true }).fill("양쪽 원문을 확인하고 참여를 결정했습니다.");

  await page.getByRole("button", { name: "결정 저장", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  // 무엇을 저장하는지 다시 보여 준다.
  await expect(dialog).toContainText("되돌릴 수 없습니다");
  await expect(dialog).toContainText("Go · 참여");
  await expect(dialog).toContainText("홍길동");
  await expect(dialog).toContainText("양쪽 원문을 확인하고 참여를 결정했습니다.");
  // 확인 전에는 요청이 없다.
  expect(trace.finalDecisionPosts).toHaveLength(0);

  await dialog.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(trace.finalDecisionPosts).toHaveLength(0);
  // 취소는 초안을 지우지 않는다.
  await expect(page.getByLabel("최종 결정", { exact: true })).toHaveValue("go");
  await expect(page.getByLabel("결정 이유", { exact: true })).toHaveValue("양쪽 원문을 확인하고 참여를 결정했습니다.");

  await page.getByRole("button", { name: "결정 저장", exact: true }).click();
  await confirmFinalDecision(page, "Go로 최종 결정 저장");
  await expect(page.getByText("Go 최종 결정을 저장했습니다. 이전 결정은 그대로 남습니다.", { exact: true })).toBeVisible();
  expect(trace.finalDecisionPosts).toHaveLength(1);
});
