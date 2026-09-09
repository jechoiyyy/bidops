import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockBidDelta, type BidDeltaMockOptions } from "./api-mock";
import { comparisonFor, mockGoNoGo, mockDecisionRace, RACE_COMPARISON } from "./go-no-go-fixtures";

/** 상세 화면은 자체 브레드크럼을 갖지 않는다. 되돌아가는 길은 상단 경로
 *  (`nav[aria-label="현재 위치"]`)와 화면 안의 이동 링크뿐이다. */
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
  await expect(page.getByRole("heading", { name: "변경 항목과 근거", exact: true })).toBeVisible();
}

/** 시안의 결정 입력은 Astryx `Selector`다. 빈 값에서 시작하고 사람이 고른다. */
async function chooseDecision(page: Page, label: "Go" | "No-Go"): Promise<void> {
  await page.getByRole("combobox", { name: "최종 결정" }).click();
  await page.getByRole("option", { name: label, exact: true }).click();
}

function decisionSelector(page: Page) {
  return page.getByRole("combobox", { name: "최종 결정" });
}

/** 되돌릴 수 없는 최종 Go/No-Go는 확인 단계를 거쳐야 요청이 나간다. */
async function confirmFinalDecision(page: Page, label: string): Promise<void> {
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: label, exact: true }).click();
}

async function fillDecision(page: Page, value: "Go" | "No-Go", reason: string, actor = "홍길동"): Promise<void> {
  await chooseDecision(page, value);
  await page.getByLabel("결정 이유", { exact: true }).fill(reason);
  await page.getByLabel("최종 결정 담당자 이름").fill(actor);
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
      // 계산 상태는 읽기 칸 머리에, 결과 상태는 항목 바로 위 한 줄에 있다.
      await expect(page.locator("#bid-delta-calculation-title")).toContainText(
        calculationStatus === "pending" ? "대기 중"
          : calculationStatus === "running" ? "계산 중"
            : calculationStatus === "completed" ? "계산 완료" : "계산 실패",
      );
      if (calculationStatus === "pending" || calculationStatus === "running") {
        await expect(page.getByText("계산을 실행하는 프로그램이 아직 운영에 없습니다.", { exact: false })).toBeVisible();
      } else {
        await expect(page.getByText("계산을 실행하는 프로그램이 아직 운영에 없습니다.", { exact: false })).toHaveCount(0);
      }
      await expect(page.getByRole("button", { name: "결정 확인", exact: true })).toBeDisabled();
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
  await expect(page.getByText("변경 있음", { exact: false }).first()).toBeVisible({ timeout: 6_000 });
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
      // 항목 갈래는 `확인 필요`·`분석 실패`이며 변경 없음으로 접히지 않는다.
      await expect(firstItem.locator(".bid-delta-item-statuses")).toContainText(resultStatus === "unknown" ? "확인 필요" : "분석 실패");
      await expect(firstItem.locator(".bid-delta-item-statuses")).not.toContainText("변경 없음");
      await expect(firstItem).toContainText("오류 코드");
    }
  });
}

test("양쪽 input fence와 evidence locator를 한 쌍으로 표시한다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  // 고정 입력 값은 지워지지 않고 접혀 있다.
  await page.getByRole("group").filter({ hasText: "비교 기준·고정 입력·계산 회차 자세히" }).locator("summary").click();
  await expect(page.getByText("22222222-2222-4222-8222-222222222222", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("55555555-5555-4555-8555-555555555555", { exact: true }).first()).toBeVisible();

  // 양쪽 원문 근거는 항목의 `양쪽 근거 보기`가 여는 대화상자에 쌍으로 놓인다.
  await page.locator(".bid-delta-item").first().getByRole("button", { name: /양쪽 근거 보기|미확인 내용 보기/ }).click();
  const pair = page.locator(".bid-delta-evidence-pair").first();
  await expect(pair).toBeVisible();
  await expect(pair).toContainText("기준 원문 1");
  await expect(pair).toContainText("비교 원문 1");
  await expect(pair).toContainText("표 table-1");
});

test("사람 결정은 자동 선택되지 않고 저장 전에는 form 초안을 유지한다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  await expect(decisionSelector(page)).toContainText("Go 또는 No-Go 선택");
  await expect(page.getByRole("button", { name: "결정 확인", exact: true })).toBeDisabled();
  await fillDecision(page, "Go", "양쪽 원문을 확인하고 참여를 결정했습니다.");
  await expect(page.getByRole("button", { name: "결정 확인", exact: true })).toBeEnabled();
});

test("최종 결정 payload는 actor header와 모든 comparison fence를 포함한다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "unchanged" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "변경 항목과 근거", exact: true })).toBeVisible();
  await fillDecision(page, "No-Go", "확인된 범위에서 참여하지 않기로 결정했습니다.");
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
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
  // 회차 이력은 접힌 상세 안에 그대로 남는다.
  await page.getByText("비교 기준·고정 입력·계산 회차 자세히").click();
  await expect(page.getByText("1회차", { exact: true })).toBeVisible();
  await expect(page.getByText("2회차", { exact: true })).toBeVisible();
});

test("과거 final decision 이력은 현재성 문자와 함께 append-only로 모두 보인다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed", withHistory: true });
  const history = page.locator(".bid-delta-decision-history-list > li");
  await expect(history).toHaveCount(2);
  // 최신 결정이 위에 온다.
  await expect(history.nth(0)).toContainText("Go");
  await expect(history.nth(1)).toContainText("No-Go");
  await expect(history.nth(0)).toContainText("현재 유효");
  await expect(page.locator(".bid-delta-currentness").first()).toContainText("현재 유효");
});

test("요청 conflict는 typed code를 표시하고 최신 상태를 다시 불러와도 입력을 지우지 않는다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed", finalDecisionErrorCode: "bid_delta_comparison_stale" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "변경 항목과 근거", exact: true })).toBeVisible();
  await fillDecision(page, "Go", "최신 상태에서도 검토할 이유");
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  await confirmFinalDecision(page, "Go로 최종 결정 저장");
  // 저장에 실패하면 다이얼로그는 닫히고 기존 인라인 오류 표시가 그대로 보인다.
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.getByText("오류 코드 bid_delta_comparison_stale", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "최신 상태 다시 불러오기", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "최신 상태 다시 불러오기", exact: true }).click();
  await expect(page.getByText("최신 비교와 최신 여부를 다시 불러왔습니다. 입력한 초안은 그대로 두었습니다.", { exact: true })).toBeVisible();
  await expect(page.getByLabel("최종 결정 담당자 이름")).toHaveValue("홍길동");
  await expect(decisionSelector(page)).toContainText("Go");
  await expect(page.getByLabel("결정 이유", { exact: true })).toHaveValue("최신 상태에서도 검토할 이유");
  expect(trace.workspaceGets).toBeGreaterThanOrEqual(2);
});

// 비교 목록 → 비교 상세 → 저장 → 사업 추적 상세로 돌아오는 흐름. 사업 추적
// 상세에서 이 화면으로 들어오는 링크(`변경 비교 열기 →`)는 사업 추적 화면이
// 소유하므로 그쪽 spec이 본다.
test("비교 목록 → 결정 저장 → 사업 추적 상세 이동 흐름을 유지한다", async ({ page }) => {
  await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed" });
  await mockOpportunity(page);
  await page.goto("/opportunities/501/bid-delta");
  await page.getByRole("link", { name: /비교 #1/ }).click();
  await fillDecision(page, "Go", "원문 확인 후 참여합니다.");
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  await confirmFinalDecision(page, "Go로 최종 결정 저장");
  await expect(page.getByText("Go 최종 결정을 저장했습니다. 이전 결정은 그대로 남습니다.", { exact: true })).toBeVisible();
  await routeCrumbLink(page, "#501").click();
  await expect(page).toHaveURL(/\/opportunities\/501$/);
  await expect(page.getByRole("heading", { name: "사업 추적 상세 #501", exact: true })).toBeVisible();
});

test("미저장 최종 결정 초안은 beforeunload와 SPA 이동을 보호한다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  await fillDecision(page, "Go", "아직 저장하지 않은 검토 초안");
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

// 시안 정본(design-previews/bidops-go-no-go-erp-20260907/decision-review-*)은 결정
// 확인 액션을 오른쪽 결정 칸의 **고정 바닥**에 둔다. 읽기 칸을 끝까지 내려도 그
// 자리는 사라지지 않는다.
test("결정 확인 액션은 읽기 칸을 끝까지 스크롤해도 뷰포트 안에 남는다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  const confirmAction = page.locator(".bid-delta-decision-footer").getByRole("button", { name: "결정 확인", exact: true });
  await expect(confirmAction).toBeInViewport();
  await page.locator(".bid-delta-reading-scroll").evaluate((element) => element.scrollTo(0, 999_999));
  await expect(confirmAction).toBeInViewport();
});

// 시안의 압축 헤더는 되돌아가는 길·화면 이름·결정 입력으로 이동만 담는다.
// 되돌릴 수 없는 저장 액션을 헤더에 복제하지 않는다.
test("압축 헤더는 뷰포트를 과도하게 차지하지 않고 저장 액션을 복제하지 않는다", async ({ page }, testInfo) => {
  test.skip((testInfo.project.use.viewport?.width ?? 0) < 960, "노트북 폭 이상에서만 검사한다");
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  const ratio = await page.evaluate(() => {
    const head = document.querySelector(".bid-delta-page-header") as HTMLElement | null;
    return head ? head.getBoundingClientRect().height / window.innerHeight : 1;
  });
  expect(ratio).toBeLessThan(0.15);
  await expect(page.getByRole("button", { name: "결정 확인", exact: true })).toHaveCount(1);
  await expect(page.locator(".bid-delta-page-header").getByRole("button", { name: "결정 확인", exact: true })).toHaveCount(0);
});

test("헤더의 결정 입력으로 이동은 결정 입력에 초점을 준다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  await page.getByRole("button", { name: "결정 입력으로 이동", exact: true }).click();
  await expect(decisionSelector(page)).toBeFocused();
});

// 전제조건(계산 완료·결과 failed 아님)을 만족하지 못해 비활성인 상태에서도
// 버튼과 비활성 사유가 스크롤 없이 함께 보여야 한다.
test("계산 대기 중인 비교는 비활성 결정 액션과 사유가 스크롤 없이 함께 보인다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "pending" });
  const saveButton = page.locator(".bid-delta-decision-footer").getByRole("button", { name: "결정 확인", exact: true });
  await expect(saveButton).toBeInViewport();
  await expect(saveButton).toBeDisabled();
  await expect(page.locator("#bid-delta-final-disabled")).toBeInViewport();
  await expect(page.locator("#bid-delta-final-disabled")).toContainText("계산이 완료될 때까지");
  // 막힌 저장 조건 셋이 폼 자리에 그대로 보인다.
  await expect(page.locator(".bid-delta-save-conditions").locator("li")).toHaveCount(3);
  await expect(page.locator(".bid-delta-save-conditions")).toContainText("보류는 최종 결정 값이 아니며 저장되지 않습니다");
});

// 오른쪽 결정 칸은 결정 입력과 결정 이력만 담는다. 계산 회차·고정 입력 같은
// 기술 자료는 왼쪽 읽기 칸의 접힌 상세에 있다.
test("결정 칸은 이력과 최신 여부를 담고 계산 회차는 읽기 칸에 남는다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed", withHistory: true });
  const pane = page.locator(".bid-delta-decision-pane");
  await expect(pane.getByRole("heading", { name: "최종 Go/No-Go 저장 이력", exact: true })).toBeVisible();
  await expect(pane.getByRole("heading", { name: /최종 결정 .*여부|최종 결정 현재성/ })).toBeVisible();
  // 계산 회차 이력은 읽기 칸의 접힌 상세 안에 있다. 지워지지 않았다.
  await expect(page.locator(".bid-delta-reading").locator("h3", { hasText: "계산 회차 이력" })).toHaveCount(1);
  await expect(pane.locator("h3", { hasText: "계산 회차 이력" })).toHaveCount(0);
});

test("보류는 최종 결정 선택지가 아니다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "completed", resultStatus: "changed" });
  await decisionSelector(page).click();
  const options = await page.getByRole("option").allInnerTexts();
  expect(options.map((text) => text.trim())).toEqual(["Go", "No-Go"]);
});

test("계산 실패는 재시도 입력으로 데려가고 실패를 변경 없음으로 읽지 않는다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "failed", resultStatus: "failed" });
  await expect(page.locator("#bid-delta-calculation-title")).toContainText("계산 실패");
  await expect(page.getByText("계산 전체가 실패하여 결과를 확정할 수 없습니다.")).toBeVisible();
  await expect(page.getByLabel("재시도 담당자 이름")).toBeVisible();
  await expect(page.locator("#bid-delta-final-disabled")).toContainText("최종 Go/No-Go를 저장할 수 없습니다");
});

// 화면이 "되돌릴 수 없습니다"라고 쓰면서 submit 한 번에 요청을 보내면 그 문장은
// 경고가 아니라 사후 설명이다. 최종 Go/No-Go는 확인 단계를 거쳐야 나간다.
test("최종 결정은 확인 없이는 요청이 나가지 않고 취소하면 초안만 남는다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "변경 항목과 근거", exact: true })).toBeVisible();
  await fillDecision(page, "Go", "양쪽 원문을 확인하고 참여를 결정했습니다.");

  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
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
  await expect(decisionSelector(page)).toContainText("Go");
  await expect(page.getByLabel("결정 이유", { exact: true })).toHaveValue("양쪽 원문을 확인하고 참여를 결정했습니다.");

  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  await confirmFinalDecision(page, "Go로 최종 결정 저장");
  await expect(page.getByText("Go 최종 결정을 저장했습니다. 이전 결정은 그대로 남습니다.", { exact: true })).toBeVisible();
  expect(trace.finalDecisionPosts).toHaveLength(1);
});

// ── 확인 창이 열려 있는 동안의 스냅숏 경쟁 ────────────────────────────────
//
// 확인 창을 연 뒤 재연결·배경 재조회로 비교 버전·결과 해시·양쪽 문서 버전·
// 대체 대상이 바뀔 수 있다. 저장 시점에 그 최신 값을 다시 읽으면 사람이 읽고
// 확인한 것과 **다른 스냅숏**이 유효한 fence를 달고 저장된다. 확인 창을 열 때
// 얼린 요청만 나가야 하고, 실제로 바뀌었다면 서버가 거절해야 한다.
test("확인 창이 열린 사이 비교가 갱신돼도 사람이 확인한 스냅숏만 저장 요청된다", async ({ page }) => {
  const trace = await mockDecisionRace(page);
  await page.goto(`/opportunities/901/bid-delta?comparison=${RACE_COMPARISON.id}`);
  await expect(page.getByRole("heading", { name: "변경 항목과 근거", exact: true })).toBeVisible();

  await fillDecision(page, "No-Go", "축소된 일정과 늘어난 연계 범위를 검토해 불참합니다.", "검토 담당자");
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("버전 2");

  // 확인 창이 열린 사이 서버 쪽 스냅숏이 바뀌고 화면이 다시 조회한다.
  trace.bump();
  const getsBefore = trace.comparisonGets;
  await page.evaluate(() => {
    window.dispatchEvent(new Event("offline"));
    window.dispatchEvent(new Event("online"));
  });
  await expect.poll(() => trace.comparisonGets, { timeout: 5_000 }).toBeGreaterThan(getsBefore);

  // 요약은 사람이 읽은 값 그대로다. 화면이 최신 값으로 갈아 끼우지 않는다.
  await expect(dialog).toContainText("버전 2");

  await dialog.getByRole("button", { name: "No-Go로 최종 결정 저장", exact: true }).click();

  await expect.poll(() => trace.posts.length).toBe(1);
  const post = trace.posts[0];
  expect(post.body).toMatchObject({
    expected_comparison_version: 2,
    expected_result_sha256: RACE_COMPARISON.oldSha,
    supersedes_final_decision_id: null,
    decision: "no_go",
    reason: "축소된 일정과 늘어난 연계 범위를 검토해 불참합니다.",
  });
  // 갱신된 스냅숏의 값이 몰래 실려 나가지 않았다.
  expect(post.body.expected_result_sha256).not.toBe(RACE_COMPARISON.newSha);
  expect(post.body.supersedes_final_decision_id).not.toBe(RACE_COMPARISON.supersededId);

  // 서버가 오래된 fence를 거절한 사실이 그대로 보인다. 화면이 성공을 흉내내지 않는다.
  await expect(page.getByText("오류 코드 bid_delta_comparison_stale", { exact: false })).toBeVisible();
  await expect(page.getByLabel("결정 이유", { exact: true })).toHaveValue("축소된 일정과 늘어난 연계 범위를 검토해 불참합니다.");
  await expect(page.getByLabel("최종 결정 담당자 이름")).toHaveValue("검토 담당자");
});

test("같은 내용을 다시 확인하면 같은 request_id로, 내용을 고치면 새 request_id로 보낸다", async ({ page }) => {
  const trace = await mockDecisionRace(page);
  await page.goto(`/opportunities/901/bid-delta?comparison=${RACE_COMPARISON.id}`);
  await expect(page.getByRole("heading", { name: "변경 항목과 근거", exact: true })).toBeVisible();

  await fillDecision(page, "No-Go", "같은 내용을 다시 확인합니다.", "검토 담당자");
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  await confirmFinalDecision(page, "No-Go로 최종 결정 저장");
  await expect.poll(() => trace.posts.length).toBe(1);

  // 저장이 실패했다. 같은 초안을 그대로 다시 확인하면 같은 요청이다.
  await expect(page.getByText("오류 코드 bid_delta_comparison_stale", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  await confirmFinalDecision(page, "No-Go로 최종 결정 저장");
  await expect.poll(() => trace.posts.length).toBe(2);
  expect(trace.posts[1].body.request_id).toBe(trace.posts[0].body.request_id);

  // 이유를 고치면 다른 요청이다.
  await page.getByLabel("결정 이유", { exact: true }).fill("이유를 고쳐 다시 저장합니다.");
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  await confirmFinalDecision(page, "No-Go로 최종 결정 저장");
  await expect.poll(() => trace.posts.length).toBe(3);
  expect(trace.posts[2].body.request_id).not.toBe(trace.posts[0].body.request_id);
});


for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`${viewport.width} 결정 입력은 첫 화면에 이유와 기록자까지 보인다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await mockGoNoGo(page);
    await page.goto(`/opportunities/901/bid-delta?comparison=${comparisonFor(0)?.id}`);
    await expect(page.getByLabel("결정 이유", { exact: true })).toBeInViewport({ ratio: 1 });
    await expect(page.getByLabel("최종 결정 담당자 이름")).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole("button", { name: "결정 확인", exact: true })).toBeInViewport({ ratio: 1 });
    if (process.env.BIDOPS_UI_CAPTURE_DIR) {
      await page.screenshot({ path: `${process.env.BIDOPS_UI_CAPTURE_DIR}/review-${viewport.width}.png` });
    }
  });
}
