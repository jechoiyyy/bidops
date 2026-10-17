import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockBidDelta, type BidDeltaMockOptions } from "./api-mock";
import {
  bidConditionsFixture,
  comparisonFor,
  mockBidConditions,
  mockDecisionRace,
  mockGoNoGo,
  noticeBasisDecision,
  RACE_COMPARISON,
} from "./go-no-go-fixtures";

/**
 * 폼 오류의 안전 코드가 그대로 남아 있는지 본다.
 *
 * 코드는 문장 옆 **접힌 `기술 정보`** 안으로 옮겼고(ADR-0066 §3.3, 시안 M4 결정 3),
 * 같은 문장이 시각적으로만 감춰진 채 한 번 더 있어 `role="alert"`이 읽을 때 함께
 * 읽힌다. 그래서 눈에 보이는지가 아니라 **오류 영역 안에 있는지**로 본다. 접힘의
 * 구조 자체는 아래 전용 검사가 따로 본다.
 */
function expectErrorCode(page: Page, code: string) {
  return expect(page.locator(".mutation-feedback")).toContainText(`오류 코드 ${code}`);
}

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
  await expect(page.getByRole("heading", { name: "공고 조건과 변경 비교", exact: true })).toBeVisible();
}

/** 최종 결정 값은 Go·No-Go 두 radio다. 빈 값에서 시작하고 사람이 고른다. */
function decisionGroup(page: Page) {
  return page.getByRole("radiogroup", { name: "최종 결정" });
}

async function chooseDecision(page: Page, label: "Go" | "No-Go"): Promise<void> {
  await decisionGroup(page).getByRole("radio", { name: label, exact: true }).check();
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

// 비교를 계산하는 프로그램이 없어 대기 상태는 스스로 바뀌지 않는다. 1초마다 같은
// 대기 응답을 다시 받던 조회를 없앴다. 사람이 누를 때만 다시 읽는다.
test("계산 대기 비교는 자동으로 다시 조회하지 않고 사람이 누를 때만 다시 읽는다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "pending" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByText("계산 대기 상태입니다.", { exact: true })).toBeVisible();
  const loadedGets = trace.comparisonGets;
  // 예전 주기(1초)를 넘는 짧은 창에서 조회 수가 그대로인지 본다.
  await page.waitForTimeout(1_500);
  expect(trace.comparisonGets).toBe(loadedGets);

  await page.getByRole("button", { name: "상태 다시 조회", exact: true }).click();
  await expect.poll(() => trace.comparisonGets).toBe(loadedGets + 1);
});

test("후보가 없으면 변경 없음이 아니라 이유가 있는 EmptyState를 표시한다", async ({ page }) => {
  await mockBidDelta(page, { baselineCandidates: false, comparisonCandidates: false });
  await page.goto("/opportunities/501/bid-delta");
  await expect(page.getByText("기준 후보 없음", { exact: true })).toBeVisible();
  await expect(page.getByText("비교 후보 없음", { exact: true })).toBeVisible();
  await expect(page.getByText("이를 변경 없음으로 해석하지 않습니다.", { exact: false })).toHaveCount(2);
  await expect(page.getByRole("button", { name: "비교 시작", exact: true })).toBeDisabled();
});

// spec §11.3: 비교 생성 endpoint는 남기되 화면의 생성 단추는 비활성이다. 후보가 양쪽에
// 다 있어도 만들지 않는다 — 계산 프로그램이 없어 대기에 머물기 때문이다.
test("후보가 있어도 비교 만들기는 비활성이고 비교 계산 프로그램 미구현을 적는다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed" });
  await page.goto("/opportunities/501/bid-delta");
  await expect(page.locator(".bid-delta-candidate-selected")).toHaveCount(2);
  const create = page.getByRole("button", { name: "비교 시작", exact: true });
  await expect(create).toBeDisabled();
  await expect(page.locator("#bid-delta-create-disabled")).toHaveText("비교 계산 프로그램 미구현");
  await expect(create).toHaveAttribute("aria-describedby", "bid-delta-create-disabled");
  await expect(page.getByLabel("비교 요청 담당자 이름")).toHaveCount(0);
  expect(trace.comparisonPosts).toHaveLength(0);
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
  await expect(decisionGroup(page).getByRole("radio", { name: "Go", exact: true })).not.toBeChecked();
  await expect(decisionGroup(page).getByRole("radio", { name: "No-Go", exact: true })).not.toBeChecked();
  await expect(page.getByRole("button", { name: "결정 확인", exact: true })).toBeDisabled();
  await fillDecision(page, "Go", "양쪽 원문을 확인하고 참여를 결정했습니다.");
  await expect(page.getByRole("button", { name: "결정 확인", exact: true })).toBeEnabled();
});

test("최종 결정 payload는 actor header와 모든 comparison fence를 포함한다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "unchanged" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "공고 조건과 변경 비교", exact: true })).toBeVisible();
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
  await expect(history.nth(0)).toContainText("비교 결과 기준 · 비교 버전 2");
  await expect(page.locator(".bid-delta-currentness").first()).toContainText("현재 유효");
});

// ADR-0058: 공고 조건 근거 결정은 비교에 묶이지 않는다. 이력은 근거 종류를 문자로
// 적고, 공고 조건 근거에는 비교 필드 대신 기준 입찰공고 ID와 짧은 관측 해시를 둔다.
test("결정 이력은 근거 종류를 적고 공고 조건 근거는 공고 ID와 짧은 해시를 보인다", async ({ page }) => {
  await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed", withHistory: true });
  const noticeLatest = noticeBasisDecision(501, 3, { supersedes_final_decision_id: "aaaaaaaa-1111-4111-8111-aaaaaaaaaaa2" });
  // 사업기회의 마지막 결정만 공고 조건 근거로 바꾼 workspace. 비교 상세의 이력(비교 근거 2건)은 그대로다.
  await page.route("**/api/opportunities/501/bid-delta", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      schema_version: "bidops.bid-delta-workspace.v1",
      opportunity_id: 501,
      baseline_candidates: [],
      comparison_candidates: [],
      comparisons: [],
      latest_final_decision: noticeLatest,
      decision_currentness: "current",
      currentness_reasons: [],
      generated_at: "2026-09-12T02:05:00Z",
    }) });
  });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  const history = page.locator(".bid-delta-decision-history-list > li");
  await expect(history).toHaveCount(3);
  await expect(history.nth(0)).toContainText("3번째 결정 · 조건 검토자");
  await expect(history.nth(0)).toContainText("공고 조건 기준 · 기준 입찰공고 ID 1102 · 관측 해시 eeeeeeeeeeee");
  await expect(history.nth(0)).not.toContainText("비교 버전");
  await expect(history.nth(1)).toContainText("비교 결과 기준");

  // 비교를 고르지 않은 화면의 최신 결정 칸도 같은 근거 문자를 쓴다.
  await page.goto("/opportunities/501/bid-delta");
  await expect(page.locator(".bid-delta-currentness")).toContainText("공고 조건 기준 · 기준 입찰공고 ID 1102 · 관측 해시 eeeeeeeeeeee");
});

test("요청 conflict는 typed code를 표시하고 최신 상태를 다시 불러와도 입력을 지우지 않는다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed", finalDecisionErrorCode: "bid_delta_comparison_stale" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "공고 조건과 변경 비교", exact: true })).toBeVisible();
  await fillDecision(page, "Go", "최신 상태에서도 검토할 이유");
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  await confirmFinalDecision(page, "Go로 최종 결정 저장");
  // 저장에 실패하면 다이얼로그는 닫히고 기존 인라인 오류 표시가 그대로 보인다.
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expectErrorCode(page, "bid_delta_comparison_stale");
  await expect(page.getByRole("button", { name: "최신 상태 다시 불러오기", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "최신 상태 다시 불러오기", exact: true }).click();
  await expect(page.getByText("최신 비교·공고 조건과 최신 여부를 다시 불러왔습니다. 입력한 초안은 그대로 두었습니다.", { exact: true })).toBeVisible();
  await expect(page.getByLabel("최종 결정 담당자 이름")).toHaveValue("홍길동");
  await expect(decisionGroup(page).getByRole("radio", { name: "Go", exact: true })).toBeChecked();
  await expect(page.getByLabel("결정 이유", { exact: true })).toHaveValue("최신 상태에서도 검토할 이유");
  expect(trace.workspaceGets).toBeGreaterThanOrEqual(2);
});

// 폼 오류 한 줄(`components/common/MutationFeedback.tsx`)은 모든 저장 폼이 공유한다.
// 안전 코드는 지우지 않고 문장 옆 접힌 `기술 정보`로 옮겼다(ADR-0066 §3.3, 시안 M4
// 결정 3). 코드 값·분기·검열은 그대로이며 바뀐 것은 놓인 자리뿐이다.
test("폼 오류의 안전 코드는 접힌 기술 정보에 있고 보조기술에는 계속 읽힌다", async ({ page }) => {
  await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed", finalDecisionErrorCode: "bid_delta_comparison_stale" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "공고 조건과 변경 비교", exact: true })).toBeVisible();
  await fillDecision(page, "Go", "접힌 기술 정보를 확인합니다.");
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  await confirmFinalDecision(page, "Go로 최종 결정 저장");

  const feedback = page.locator(".mutation-feedback");
  // 사람 말이 먼저다. 제목·다음 행동은 접히지 않는다.
  await expect(feedback).toContainText("새 비교 입력이 생겨 이 결정은 최신이 아닙니다.");
  await expect(feedback).toContainText("최신 상태를 다시 불러온 뒤");
  // 코드 줄은 접혀 있어 눈에 보이지 않는다.
  const codeLine = feedback.locator(".mutation-feedback-code");
  await expect(codeLine).toBeHidden();
  // 그래도 오류 영역은 `role="alert"`이고, 그 안에 읽히는 설명으로 코드가 남는다.
  await expect(feedback).toHaveAttribute("role", "alert");
  await expect(feedback).toContainText("오류 코드 bid_delta_comparison_stale");
  // 펴면 코드가 **전문** 그대로 보인다. 운영자에게 전할 때 여기서 복사한다.
  await feedback.locator("details.deep-review-technical > summary").click();
  await expect(codeLine).toHaveText("오류 코드 bid_delta_comparison_stale");
});

// 비교 목록 → 비교 상세 → 저장 → 사업기회 레코드로 돌아오는 흐름. 사업 추적
// 목록 pane에서 이 화면으로 들어오는 링크(`변경 비교 열기 →`)는 사업 추적 화면이
// 소유하므로 그쪽 spec이 본다.
test("비교 목록 → 결정 저장 → 사업기회 레코드 이동 흐름을 유지한다", async ({ page }) => {
  await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed" });
  await mockOpportunity(page);
  await page.goto("/opportunities/501/bid-delta");
  await page.getByRole("link", { name: /비교 #1/ }).click();
  await fillDecision(page, "Go", "원문 확인 후 참여합니다.");
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  await confirmFinalDecision(page, "Go로 최종 결정 저장");
  await expect(page.getByText("Go 최종 결정을 저장했습니다. 이전 결정은 그대로 남습니다.", { exact: true })).toBeVisible();
  // `#501` 칸은 사업기회 레코드로 돌아간다(`/opportunities/501` → `/activity`, RL-02). 레코드 본문은
  // opportunity-record.spec.ts가 보므로 여기서는 활동 응답 하나만 두고 레코드가 열리는지만 본다.
  await page.route("**/api/opportunities/501/activity**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      schema_version: "bidops.opportunity-activity.v1",
      opportunity_id: 501,
      merged_into_opportunity_id: null,
      title: "최종 결정 대기 사업",
      stages: [],
      items: [],
      next_before: null,
    }),
  }));
  await routeCrumbLink(page, "#501").click();
  await expect(page).toHaveURL(/\/opportunities\/501\/activity$/);
  await expect(page.getByTestId("record-title")).toHaveText("최종 결정 대기 사업");
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
  await expect(decisionGroup(page).getByRole("radio", { name: "Go", exact: true })).toBeFocused();
});

// 완료되지 않은 비교를 보고 있어도 결정의 근거는 공고 조건이다. 입력 전 비활성
// 버튼과 사유, 저장 조건 셋이 스크롤 없이 함께 보여야 한다.
test("계산 대기 중인 비교를 보면 공고 조건 근거 폼과 비활성 사유가 스크롤 없이 함께 보인다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "pending" });
  const saveButton = page.locator(".bid-delta-decision-footer").getByRole("button", { name: "결정 확인", exact: true });
  await expect(saveButton).toBeInViewport();
  await expect(saveButton).toBeDisabled();
  await expect(page.locator("#bid-delta-final-disabled")).toBeInViewport();
  await expect(page.locator("#bid-delta-final-disabled")).toContainText("결정 기록자 이름을 입력해 주세요.");
  await expect(page.locator(".bid-delta-decision-conditions")).toContainText("결정 근거 · 공고 조건 기준");
  // 저장 조건 셋: 최신 차수 확인 · 사유 입력 · 담당자 이름. 충족 여부를 문자로 적는다.
  const conditions = page.locator(".bid-delta-save-conditions > li");
  await expect(conditions).toHaveCount(3);
  await expect(conditions.nth(0)).toContainText("확인됨");
  await expect(conditions.nth(0)).toContainText("최신 차수 확인");
  await expect(conditions.nth(1)).toContainText("필요");
  await expect(conditions.nth(1)).toContainText("사유 입력");
  await expect(conditions.nth(2)).toContainText("담당자 이름");
  await expect(page.locator(".bid-delta-form-note")).toContainText("보류는 최종 결정 값이 아니며 저장되지 않습니다");
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
  const radios = decisionGroup(page).getByRole("radio");
  await expect(radios).toHaveCount(2);
  await expect(decisionGroup(page).getByRole("radio", { name: "Go", exact: true })).toHaveCount(1);
  await expect(decisionGroup(page).getByRole("radio", { name: "No-Go", exact: true })).toHaveCount(1);
});

test("계산 실패는 재시도 입력으로 데려가고 실패를 변경 없음으로 읽지 않는다", async ({ page }) => {
  await openComparison(page, { calculationStatus: "failed", resultStatus: "failed" });
  await expect(page.locator("#bid-delta-calculation-title")).toContainText("계산 실패");
  await expect(page.getByText("계산 전체가 실패하여 결과를 확정할 수 없습니다.")).toBeVisible();
  await expect(page.getByLabel("재시도 담당자 이름")).toBeVisible();
  // 실패한 비교는 결정 근거가 될 수 없다. 근거는 공고 조건으로 넘어가고 비교 근거 선택지는 없다.
  await expect(page.locator(".bid-delta-decision-conditions")).toContainText("결정 근거 · 공고 조건 기준");
  await expect(page.getByRole("radiogroup", { name: "결정 근거" })).toHaveCount(0);
});

// 화면이 "되돌릴 수 없습니다"라고 쓰면서 submit 한 번에 요청을 보내면 그 문장은
// 경고가 아니라 사후 설명이다. 최종 Go/No-Go는 확인 단계를 거쳐야 나간다.
test("최종 결정은 확인 없이는 요청이 나가지 않고 취소하면 초안만 남는다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  await expect(page.getByRole("heading", { name: "공고 조건과 변경 비교", exact: true })).toBeVisible();
  await fillDecision(page, "Go", "양쪽 원문을 확인하고 참여를 결정했습니다.");

  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  // 무엇을 저장하는지 다시 보여 준다.
  await expect(dialog).toContainText("되돌릴 수 없습니다");
  await expect(dialog).toContainText("비교 결과 기준");
  await expect(dialog).toContainText("Go · 참여");
  await expect(dialog).toContainText("홍길동");
  await expect(dialog).toContainText("양쪽 원문을 확인하고 참여를 결정했습니다.");
  // 확인 전에는 요청이 없다.
  expect(trace.finalDecisionPosts).toHaveLength(0);

  await dialog.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(trace.finalDecisionPosts).toHaveLength(0);
  // 취소는 초안을 지우지 않는다.
  await expect(decisionGroup(page).getByRole("radio", { name: "Go", exact: true })).toBeChecked();
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
  await expect(page.getByRole("heading", { name: "공고 조건과 변경 비교", exact: true })).toBeVisible();

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
  await expectErrorCode(page, "bid_delta_comparison_stale");
  await expect(page.getByLabel("결정 이유", { exact: true })).toHaveValue("축소된 일정과 늘어난 연계 범위를 검토해 불참합니다.");
  await expect(page.getByLabel("최종 결정 담당자 이름")).toHaveValue("검토 담당자");
});

test("같은 내용을 다시 확인하면 같은 request_id로, 내용을 고치면 새 request_id로 보낸다", async ({ page }) => {
  const trace = await mockDecisionRace(page);
  await page.goto(`/opportunities/901/bid-delta?comparison=${RACE_COMPARISON.id}`);
  await expect(page.getByRole("heading", { name: "공고 조건과 변경 비교", exact: true })).toBeVisible();

  await fillDecision(page, "No-Go", "같은 내용을 다시 확인합니다.", "검토 담당자");
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  await confirmFinalDecision(page, "No-Go로 최종 결정 저장");
  await expect.poll(() => trace.posts.length).toBe(1);

  // 저장이 실패했다. 같은 초안을 그대로 다시 확인하면 같은 요청이다.
  await expectErrorCode(page, "bid_delta_comparison_stale");
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


// ── 공고 조건 요약과 공고 조건 기준 최종 결정 (spec §9·§11.3) ─────────────────

test("공고 조건 표는 최신 차수 값을 보이고 값 없음·미확인·실제 N을 구분한다", async ({ page }) => {
  await mockBidDelta(page, { calculationStatus: "completed" });
  await mockBidConditions(page, 501, [bidConditionsFixture(501)]);
  await page.goto("/opportunities/501/bid-delta");
  const section = page.locator(".bid-delta-conditions");
  await expect(section.getByRole("heading", { name: "공고 조건", exact: true })).toBeVisible();

  // 최신 차수는 서버의 `latest_notice_id`가 가리키는 공고다.
  const table = section.getByRole("table");
  await expect(table).toHaveAccessibleName("최신 차수 공고 조건 · R26BK00267196 · 차수 002");
  await expect(table.locator("td[data-condition-field]")).toHaveCount(15);
  const cell = (field: string) => table.locator(`td[data-condition-field="${field}"]`);
  await expect(cell("budget")).toHaveText("160,000,000원");
  // `null`은 관측되지 않은 값이고, `N`은 실제로 관측된 값이다. 둘을 같은 말로 쓰지 않는다.
  await expect(cell("estimated_price")).toHaveText("값 없음");
  await expect(cell("region_limit_basis")).toHaveText("값 없음");
  await expect(cell("sw_industry_1468")).toHaveText("N · 1468 표시 없음");
  await expect(cell("joint_contract_regions")).toHaveText("지정 지역 없음");
  await expect(cell("change_reason")).toHaveText("입찰마감 일시 연장");

  // 차수 간 변경: 변경은 펼쳐 강조하고, 미확인은 따로 보이며, 변경 없음은 건수로 접는다.
  const rounds = section.locator(".bid-delta-round");
  await expect(rounds).toHaveCount(2);
  const first = rounds.nth(0);
  await expect(first).toContainText("변경 1건 · 미확인 4건 · 변경 없음 10건");
  const budget = first.locator('li[data-condition-field="budget"]');
  await expect(budget).toHaveAttribute("data-change-status", "changed");
  await expect(budget.locator(".astryx-token")).toHaveText("변경");
  await expect(budget).toContainText("150,000,000원");
  await expect(budget).toContainText("160,000,000원");
  const rate = first.locator('li[data-condition-field="technical_evaluation_rate"]');
  await expect(rate).toHaveAttribute("data-change-status", "unknown");
  await expect(rate.locator(".astryx-token")).toHaveText("미확인");
  await expect(rate).toContainText("값 없음");
  await expect(first.locator('li[data-change-status="unchanged"]')).toHaveCount(0);
  await expect(first.locator("details > summary")).toHaveText("변경 없음 10개 항목 보기");
  await expect(rounds.nth(1)).toContainText("(최신)");
  await expect(rounds.nth(1).locator('li[data-change-status="changed"]')).toHaveCount(1);
  await expect(rounds.nth(1).locator('li[data-condition-field="deadline_at"]')).toHaveAttribute("data-change-status", "changed");

  // 사전규격 대비는 의미가 같은 예산·사업명만. 마감은 비교하지 않는다고 적는다.
  const preSpec = section.locator('[aria-labelledby="bid-delta-prespec-compare-title"]');
  await expect(preSpec.locator('li[data-prespec-field="budget"] .astryx-token')).toHaveText("변경");
  await expect(preSpec.locator('li[data-prespec-field="title"] .astryx-token')).toHaveText("변경 없음");
  await expect(preSpec).toContainText("비교 불가: 입찰 마감(사전규격 의견등록마감과 의미가 다름)");
});

test("공고 조건 기준 결정은 최신 공고 fence·대체 대상·사유를 계약 필드 그대로 보낸다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", withHistory: true });
  await mockBidConditions(page, 501, [bidConditionsFixture(501)]);
  await page.goto("/opportunities/501/bid-delta");
  await expect(page.locator(".bid-delta-decision-conditions")).toContainText("결정 근거 · 공고 조건 기준");
  const checklist = page.locator(".bid-delta-save-conditions > li");
  await expect(checklist.nth(0)).toContainText("확인됨");
  await expect(checklist.nth(0)).toContainText("최신 차수 확인 · R26BK00267196 · 차수 002");
  await expect(page.getByRole("button", { name: "결정 확인", exact: true })).toBeDisabled();

  await fillDecision(page, "Go", "공고 조건과 차수 간 변경을 확인하고 참여합니다.");
  await expect(page.locator('.bid-delta-save-conditions > li[data-met="true"]')).toHaveCount(3);
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("공고 조건 기준");
  await expect(dialog).toContainText("R26BK00267196 · 차수 002 · 공고 ID 1102");
  expect(trace.finalDecisionPosts).toHaveLength(0);

  const posted = page.waitForRequest((request) => request.method() === "POST"
    && new URL(request.url()).pathname === "/api/opportunities/501/final-decisions");
  await confirmFinalDecision(page, "Go로 최종 결정 저장");
  await posted;
  await expect(page.getByText("Go 최종 결정을 저장했습니다. 이전 결정은 그대로 남습니다.", { exact: true })).toBeVisible();
  expect(trace.finalDecisionPosts).toHaveLength(1);
  const post = trace.finalDecisionPosts[0];
  // 서버 계약은 모르는 필드를 거부한다. 비교 근거의 필드를 섞어 보내지 않는다.
  expect(Object.keys(post.body).sort()).toEqual([
    "decision", "expected_notice_id", "expected_observation_sha256", "reason", "request_id", "supersedes_final_decision_id",
  ]);
  expect(post.body).toMatchObject({
    expected_notice_id: 1102,
    expected_observation_sha256: "e".repeat(64),
    supersedes_final_decision_id: "aaaaaaaa-1111-4111-8111-aaaaaaaaaaa2",
    decision: "go",
    reason: "공고 조건과 차수 간 변경을 확인하고 참여합니다.",
  });
  expect(String(post.body.request_id)).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(post.headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  await expect(page.getByLabel("최종 결정 담당자 이름")).toHaveValue("");
});

for (const [label, options] of [
  ["최신 입찰공고를 정할 수 없는 경우", { latestNoticeId: null, latestObservation: null }],
  ["최신 공고의 관측 해시가 없는 경우", { latestObservation: null }],
] as const) {
  test(`${label} 공고 조건 결정을 막고 이유를 적는다`, async ({ page }) => {
    const trace = await mockBidDelta(page, { calculationStatus: "completed" });
    await mockBidConditions(page, 501, [bidConditionsFixture(501, options)]);
    await page.goto("/opportunities/501/bid-delta");
    await expect(page.locator(".bid-delta-conditions").getByRole("heading", { name: "공고 조건", exact: true })).toBeVisible();
    if (options.latestNoticeId === null) {
      // 목록 끝을 최신으로 대신하지 않는다.
      await expect(page.locator(".bid-delta-conditions")).toContainText("최신 차수를 확정할 수 없습니다.");
      await expect(page.locator(".bid-delta-conditions-table")).toHaveCount(0);
    }
    await expect(page.locator("#bid-delta-final-disabled")).toHaveText("최신 입찰공고를 확정할 수 없어 저장할 수 없습니다");
    await expect(page.getByRole("button", { name: "결정 확인", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "결정 입력으로 이동", exact: true })).toBeDisabled();
    await expect(page.getByRole("radiogroup", { name: "최종 결정" })).toHaveCount(0);
    await expect(page.locator(".bid-delta-save-conditions > li").nth(0)).toContainText("필요");
    expect(trace.finalDecisionPosts).toHaveLength(0);
  });
}

for (const code of ["final_decision_notice_not_latest", "final_decision_observation_changed"] as const) {
  test(`409 ${code}는 공고 조건을 다시 읽고 초안을 지킨 채 새 fence로 다시 확인하게 한다`, async ({ page }) => {
    await mockBidDelta(page, { calculationStatus: "completed" });
    const refreshed = code === "final_decision_notice_not_latest"
      ? bidConditionsFixture(501, { firstNoticeId: 1101, latestObservation: "f".repeat(64) })
      : bidConditionsFixture(501, { latestObservation: "f".repeat(64) });
    const conditionsTrace = await mockBidConditions(page, 501, [bidConditionsFixture(501), refreshed]);
    const posts: Array<Record<string, unknown>> = [];
    await page.route("**/api/opportunities/501/final-decisions", async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      posts.push(body);
      if (posts.length === 1) {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({
          error: { code, message: "고정 conflict fixture", details: null },
          request_id: body.request_id,
        }) });
        return;
      }
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(noticeBasisDecision(501, 1, {
        basis_notice_id: body.expected_notice_id,
        basis_observation_sha256: body.expected_observation_sha256,
        decision: body.decision,
        reason: body.reason,
        request_id: body.request_id,
      })) });
    });
    await page.goto("/opportunities/501/bid-delta");
    await expect(page.locator(".bid-delta-save-conditions > li").nth(0)).toContainText("확인됨");
    await fillDecision(page, "No-Go", "차수 002 조건을 검토해 불참합니다.");
    await page.getByRole("button", { name: "결정 확인", exact: true }).click();
    await confirmFinalDecision(page, "No-Go로 최종 결정 저장");

    const feedback = page.locator(".mutation-feedback");
    await expect(feedback).toContainText("입찰공고가 바뀌었습니다. 공고 조건을 다시 읽은 뒤 결정하세요.");
    await expect(feedback).toContainText(`오류 코드 ${code}`);
    // 화면이 곧바로 공고 조건을 다시 읽는다. 초안은 지우지 않는다.
    await expect.poll(() => conditionsTrace.gets).toBeGreaterThanOrEqual(2);
    await expect(page.locator(".bid-delta-conditions")).toContainText(
      code === "final_decision_notice_not_latest" ? "공고 ID 1103" : "관측 해시 ffffffffffff",
    );
    await expect(page.getByLabel("결정 이유", { exact: true })).toHaveValue("차수 002 조건을 검토해 불참합니다.");
    await expect(page.getByLabel("최종 결정 담당자 이름")).toHaveValue("홍길동");

    await page.getByRole("button", { name: "결정 확인", exact: true }).click();
    await confirmFinalDecision(page, "No-Go로 최종 결정 저장");
    await expect.poll(() => posts.length).toBe(2);
    expect(posts[0]).toMatchObject({ expected_notice_id: 1102, expected_observation_sha256: "e".repeat(64) });
    expect(posts[1]).toMatchObject({
      expected_notice_id: code === "final_decision_notice_not_latest" ? 1103 : 1102,
      expected_observation_sha256: "f".repeat(64),
    });
    // 확인한 fence가 달라졌으므로 같은 요청이 아니다.
    expect(posts[1].request_id).not.toBe(posts[0].request_id);
    await expect(page.getByText("No-Go 최종 결정을 저장했습니다. 이전 결정은 그대로 남습니다.", { exact: true })).toBeVisible();
  });
}

for (const [code, status, title] of [
  ["bid_delta_currentness_unavailable", 503, "최신 입찰공고를 확정할 수 없습니다."],
  ["final_decision_bid_notice_missing", 409, "최종 결정할 입찰공고가 없습니다."],
] as const) {
  test(`공고 조건 결정의 ${status} ${code}는 코드별 문장으로 알리고 저장을 흉내내지 않는다`, async ({ page }) => {
    await mockBidDelta(page, { calculationStatus: "completed" });
    await mockBidConditions(page, 501, [bidConditionsFixture(501)]);
    await page.route("**/api/opportunities/501/final-decisions", async (route) => {
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify({
        error: { code, message: "고정 fixture", details: null },
        request_id: null,
      }) });
    });
    await page.goto("/opportunities/501/bid-delta");
    await fillDecision(page, "Go", "조건을 확인했습니다.");
    await page.getByRole("button", { name: "결정 확인", exact: true }).click();
    await confirmFinalDecision(page, "Go로 최종 결정 저장");
    const feedback = page.locator(".mutation-feedback");
    await expect(feedback).toContainText(title);
    await expect(feedback).toContainText(`오류 코드 ${code}`);
    await expect(page.getByText("최종 결정을 저장했습니다.", { exact: false })).toHaveCount(0);
    await expect(page.getByLabel("결정 이유", { exact: true })).toHaveValue("조건을 확인했습니다.");
  });
}

test("완료된 비교를 보면 결정 근거를 고를 수 있고 공고 조건 기준은 공고 조건 endpoint로 보낸다", async ({ page }) => {
  const trace = await mockBidDelta(page, { calculationStatus: "completed", resultStatus: "changed" });
  await page.goto(`/opportunities/501/bid-delta?comparison=${comparisonId}`);
  const basis = page.getByRole("radiogroup", { name: "결정 근거" });
  await expect(basis.getByRole("radio", { name: "비교 결과 기준", exact: true })).toBeChecked();
  await basis.getByRole("radio", { name: "공고 조건 기준", exact: true }).check();
  await expect(page.locator(".bid-delta-decision-conditions")).toContainText("결정 근거 · 공고 조건 기준");
  await fillDecision(page, "No-Go", "비교 결과가 아니라 공고 조건을 근거로 불참합니다.");
  const posted = page.waitForRequest((request) => request.method() === "POST"
    && new URL(request.url()).pathname === "/api/opportunities/501/final-decisions");
  await page.getByRole("button", { name: "결정 확인", exact: true }).click();
  await confirmFinalDecision(page, "No-Go로 최종 결정 저장");
  await posted;
  expect(trace.finalDecisionPosts).toHaveLength(1);
  expect(trace.finalDecisionPosts[0].body).not.toHaveProperty("expected_comparison_version");
  expect(trace.finalDecisionPosts[0].body).toMatchObject({
    expected_notice_id: 1102,
    expected_observation_sha256: "e".repeat(64),
    decision: "no_go",
  });
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
