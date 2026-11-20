import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import {
  DASH_NOW, blockingList, dashboardWorkload, deadlineItems, deadlineList, holdReviewItems, holdReviewList,
  mockDashboard, newPlanList, opportunityList, overviewAttentionItems, preSpecList, workloadWith,
} from "./dashboard-fixtures";
import { settleFonts } from "./screen-fixtures";
import { dailyNoticeStatus, dailyRunStatus, isBasisStale, latestDailyPlanRun } from "../src/lib/orderPlanDaily";
import { dailyNoticeRunFixture, dailyPlanExecutionFixture, dailyPlanRunFixture, mockApi, mockDailyPlanRun, mockDailyPlanRuns, mockOrderPlans, mockRunWarnings } from "./api-mock";

// 2026-11-18 ×0.9 compact 축척을 없앴다. 시안 치수가 그대로 렌더된다.
const UI_SCALE = 1;
const physical = (logical: number) => logical * UI_SCALE;
const WIDTHS: [number, number][] = [[1280, 800], [1440, 900]];

/** 패널은 `<section aria-label>`이라 region으로 찾는다. */
function panel(page: Page, name: string) {
  return page.getByRole("region", { name, exact: true });
}

test("회차 선택기와 회차 의존 패널이 화면에서 빠졌다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  await expect(panel(page, "마감 임박 추적 건")).toBeVisible();
  // 회차 선택기·회차 자료 줄·`회차 실행 보기`는 운영 화면으로 갔다(ADR-0067).
  await expect(page.getByRole("button", { name: "조회할 실행 회차" })).toHaveCount(0);
  await expect(page.locator(".dash-run-context")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "회차 실행 보기", exact: true })).toHaveCount(0);
  await expect(page.locator(".dash-dashboard-grid")).toHaveCount(0);
  // 회차 의존 패널 넷과 그 문구도 없다.
  for (const gone of ["마감 공고", "담당자 확인 요청", "회차 요약", "검증 상태"]) {
    await expect(panel(page, gone)).toHaveCount(0);
  }
  await expect(page.locator(".dash-page")).not.toContainText("1차 필터 누락");
  await expect(page.locator(".dash-page")).not.toContainText("판정 표본");
  await expect(page.locator(".dash-page")).not.toContainText("읽기 전용");
  await expect(page.locator(".dash-dashboard-foot")).not.toContainText("선택한 회차의 기준 시각");
  await expect(page.locator(".dash-dashboard-foot")).toContainText("최종 참여 판단은 최종 Go/No-Go에서 진행해요.");
  expect(new URL(page.url()).searchParams.has("run")).toBe(false);
});

/** 묶음 머리 건수 띠의 칸 하나(설계고도화안 C-8). */
function countCell(page: Page, key: string) {
  return page.locator(`.dash-count-item[data-count="${key}"]`);
}

// 설계고도화안 C-8: 본문은 세 묶음이고 일일 수집 묶음이 맨 위다. 옛 단계 바로가기 네 칸은 없어졌고
// 그 건수는 묶음의 건수 띠로 옮겼다. 건수 칸마다 목적지 목록의 기본 보기가 같은 건수를 보인다.
test("대시보드는 일일 수집 아래 오늘 결정할 것·확인할 것·새로 볼 것 세 묶음이다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  await expect(page.locator(".dash-block-head h2")).toHaveText(["오늘 결정할 것", "확인할 것", "새로 볼 것"]);
  await expect(page.locator(".dash-journey-strip")).toHaveCount(0);
  const order = await page.evaluate(() => [...document.querySelectorAll(".daily-collection, .dash-block")]
    .map((node) => (node.classList.contains("daily-collection") ? "daily" : node.getAttribute("data-block"))));
  expect(order).toEqual(["daily", "decide", "check", "new"]);
  // 업무 패널은 성격에 맞는 묶음 안에 있다.
  const block = (id: string) => page.locator(`.dash-block[data-block="${id}"]`);
  await expect(block("decide").getByRole("region", { name: "최종 결정 대기", exact: true })).toBeVisible();
  await expect(block("decide").getByRole("region", { name: "보류 재검토", exact: true })).toBeVisible();
  await expect(block("check").getByRole("region", { name: "사람 확인 필요", exact: true })).toBeVisible();
  await expect(block("check").getByRole("region", { name: "마감 임박 추적 건", exact: true })).toBeVisible();
  await expect(block("new").getByRole("region", { name: "새 관련 발주계획", exact: true })).toBeVisible();
});

test("건수 띠의 칸은 목적지 목록의 기본 보기와 같은 정의이고 그 목록으로 잇는다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  const expectations: [string, RegExp | string, string | null][] = [
    // 오늘 결정할 것
    ["order-plan-relevant", "필수 검토 발주계획1건", "/order-plans"],
    ["pre-spec-actionable", /사전규격 검토할 항목\d+건/, "/pre-specs"],
    ["go-no-go", /최종 Go\/No-Go\d+건/, "/go-no-go"],
    ["hold-overdue", "보류 재검토1건", "/opportunities?section=조치 필요&reason=hold_overdue"],
    // 확인할 것
    ["action-required", "사업기회 조치 필요3건", "/opportunities"],
    ["overview-attention", "개요 사람 확인2건", "/pre-specs?workspace=all&sw_only=false&overview_view=attention"],
    // 2026-11-19: 옛 `개요 실패`(누적) 칸은 `사전규격 확인 필요`(기본 보기와 같은 구간)로 바뀌었다.
    ["pre-spec-needs-check", "사전규격 확인 필요3건", "/pre-specs?workspace=needs_check"],
    ["blocking", "확인 항목 미답변1건", "/opportunities?section=조치 필요&reason=blocking_item"],
    ["deadline", "마감 임박 추적 건7건", "/opportunities?section=전체&deadline_within_days=7&sort=deadline"],
    ["order-plan-uncertain", "훑어보기 발주계획1건", "/order-plans?qwen=uncertain&tracking=미선택"],
    // 새로 볼 것(요청 시각 KST 2026-09-17의 전일 이후)
    ["new-order-plan", "새 관련 발주계획12건", "/order-plans?qwen=relevant&tracking=미선택&first_observed_from=2026-09-16"],
    ["new-pre-spec", "새 사전규격4건", "/pre-specs?workspace=recent&observed_from=2026-09-16"],
  ];
  for (const [key, text, href] of expectations) {
    const cell = countCell(page, key);
    await expect(cell, key).toContainText(text);
    if (href === null) await expect(cell.getByRole("link"), key).toHaveCount(0);
    else await expect(cell.getByRole("link"), key).toHaveAttribute("href", href);
  }
  // 판정 확인은 셀 수 있는 기록이 아직 없어 칸 자체가 없다(같은 비숫자를 매일 보이지 않는다).
  await expect(countCell(page, "verdict-confirmation")).toHaveCount(0);
  await expect(page.locator('.dash-block[data-block="decide"] .dash-count-item')).toHaveCount(4);
});

test("`새로`를 셀 수 없으면 0이 아니라 미확인으로 적는다", async ({ page }) => {
  await mockDashboard(page, { workload: workloadWith("order_plan_new_priority", null, "provider_absent") });
  await page.goto("/");
  // 새 관련 발주계획 패널 바닥(workload 키)은 사유를 남기고 0으로 채우지 않는다.
  const foot = panel(page, "새 관련 발주계획").locator(".dash-panel-foot");
  await expect(foot).toContainText("추적 미선택 건수 미확인 · 집계 모듈 없음");
  await expect(foot).not.toContainText("0건");
});

test("누적 패널 다섯이 제목·목적지·기준을 갖는다", async ({ page }) => {
  await mockDashboard(page, { holdReviews: holdReviewList(holdReviewItems.slice(0, 1), 1) });
  await page.goto("/");
  // 두 링크(S1)는 목적지 화면에 **패널의 목록 호출과 같은 조건**을 넘긴다. 마감 임박은
  // 기본 구역이 걸리지 않게 `section=전체`를 함께 건다.
  const expectations: [string, string, string][] = [
    ["마감 임박 추적 건", "사업기회", "/opportunities?section=전체&deadline_within_days=7&sort=deadline"],
    ["최종 결정 대기", "최종 Go/No-Go", "/go-no-go"],
    ["사람 확인 필요", "사전규격", "/pre-specs?workspace=all&sw_only=false&overview_view=attention"],
    ["보류 재검토", "사업기회에서 모두 보기", "/opportunities?section=조치 필요&reason=hold_overdue"],
    ["새 관련 발주계획", "발주계획", "/order-plans?qwen=relevant&tracking=미선택&first_observed_from=2026-09-16"],
  ];
  for (const [title, linkLabel, href] of expectations) {
    const region = panel(page, title);
    await expect(region).toBeVisible();
    await expect(region.getByRole("link", { name: linkLabel, exact: true })).toHaveAttribute("href", href);
  }
  await expect(panel(page, "최종 결정 대기").locator(".dash-panel-foot")).toContainText("입찰 마감순");
  // 바닥 건수는 링크한 Go/No-Go 기본 보기(검토 대상)와 같은 정의다.
  await expect(panel(page, "최종 결정 대기").locator(".dash-panel-foot")).toContainText(/검토 대상 \d+건/);
  await expect(panel(page, "새 관련 발주계획").locator(".dash-panel-foot")).toContainText("전일 수집 이후 처음 관측");
  await expect(panel(page, "새 관련 발주계획").locator(".dash-panel-foot")).toContainText("추적 미선택 12건 중 상위 5건");
  await expect(panel(page, "사람 확인 필요")).toContainText("확인 항목은 추적 상태와 무관하게 세요.");
});

test("건수는 workload가 내고 목록 길이로 덮지 않는다", async ({ page }) => {
  const trace = await mockDashboard(page);
  await page.goto("/");
  const region = panel(page, "마감 임박 추적 건");
  await expect(region.locator(".dash-work-item")).toHaveCount(3);
  await expect(region.locator(".dash-panel-foot")).toContainText("마감 임박 7건");
  await expect(region.locator(".dash-panel-foot")).toContainText("추적 중·보류 사업 중 7일 이내");
  await expect(region.locator(".dash-panel-foot")).toContainText("기준");
  await expect(region.locator(".dash-panel-foot")).not.toContainText("3건");
  const deadlineRequest = trace.requests.find(entry => entry.path === "/api/opportunities" && "deadline_within_days" in entry.params);
  expect(deadlineRequest?.params).toEqual({ deadline_within_days: "7", sort: "deadline", limit: "5" });
  const planRequest = trace.requests.find(entry => entry.path === "/api/order-plans");
  expect(planRequest?.params).toEqual({
    qwen_relevance: "relevant", tracking_status: "미선택",
    // 요청 시각(KST 2026-09-17)의 전일이다. 상한은 두지 않는다.
    first_observed_from: "2026-09-16", limit: "5",
  });
  // 목록이 비어도 건수는 서버 값 그대로다.
  expect(trace.writes).toEqual([]);
});

test("목록이 비어도 건수를 0으로 고치지 않는다", async ({ page }) => {
  await mockDashboard(page, { deadlines: opportunityList([], 7) });
  await page.goto("/");
  const region = panel(page, "마감 임박 추적 건");
  await expect(region).toContainText("7일 이내 마감인 추적 건이 없어요");
  await expect(region.locator(".dash-panel-foot")).toContainText("마감 임박 7건");
});

test("건수를 못 받으면 미확인이며 0으로 쓰지 않는다", async ({ page }) => {
  await mockDashboard(page, { workload: workloadWith("tracking_deadline_imminent", null, "provider_absent") });
  await page.goto("/");
  const foot = panel(page, "마감 임박 추적 건").locator(".dash-panel-foot");
  await expect(foot).toContainText("마감 임박 건수 미확인 · 집계 모듈 없음");
  await expect(foot).not.toContainText("0건");
  // 목록은 그대로 보인다 — 건수가 없다고 목록을 지우지 않는다.
  await expect(panel(page, "마감 임박 추적 건").locator(".dash-work-item")).toHaveCount(3);
});

test("사람 확인 필요는 서버 합계를 쓰고 하위 둘을 따로 적는다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  const region = panel(page, "사람 확인 필요");
  const foot = region.locator(".dash-panel-foot");
  // 합계(9)는 하위 둘(2·3)의 화면 합산이 아니라 서버가 준 값이다(ADR-0067 결정 5).
  await expect(foot).toContainText("사람 확인 필요 9건");
  await expect(foot).toContainText("개요 실패·확인 필요 2 · 공고별 확인 항목 3");
  await expect(foot).not.toContainText("5건");
  const rows = region.locator(".dash-work-item");
  await expect(rows).toHaveCount(3);
  // 개요는 마감순으로 섞이고 종류 표식이 붙는다. 확인 항목은 추적 상태와 무관하다.
  await expect(rows.nth(0)).toContainText("통합 인증·증명 서비스 사전규격");
  await expect(rows.nth(0)).toContainText("개요 검토 · 사람 확인 필요");
  await expect(rows.nth(0)).toContainText("확인");
  await expect(rows.nth(1)).toContainText("안전한 문서 준비 사전규격");
  await expect(rows.nth(1)).toContainText("개요 검토 실패");
  await expect(rows.nth(1)).toContainText("실패");
  await expect(rows.nth(2)).toContainText("지방공기업 업무혁신 및 데이터 연계 체계 고도화");
  await expect(rows.nth(2)).toContainText("공고별 확인 항목 2건");
  await expect(rows.nth(1).getByRole("link")).toHaveAttribute("href", "/pre-specs/801");
  await expect(rows.nth(2).getByRole("link")).toHaveAttribute("href", "/opportunities/601");
});

test("하위 건수가 하나라도 없으면 합계도 미확인이다", async ({ page }) => {
  const workload = {
    ...dashboardWorkload,
    items: dashboardWorkload.items.map(item => item.key === "overview_human_review" ? { ...item, count: null, unavailable_reason: "provider_absent" }
      : item.key === "human_check_required" ? { ...item, count: null, unavailable_reason: "sub_count_unavailable" } : item),
  };
  await mockDashboard(page, { workload });
  await page.goto("/");
  const foot = panel(page, "사람 확인 필요").locator(".dash-panel-foot");
  await expect(foot).toContainText("사람 확인 필요 건수 미확인 · 하위 건수 미확인");
  await expect(foot).toContainText("개요 실패·확인 필요 미확인 · 공고별 확인 항목 3");
  await expect(foot).not.toContainText("0건");
});

test("마감 임박 행은 마감 종류와 D-day를 적고 3일 이내를 강조한다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  const rows = panel(page, "마감 임박 추적 건").locator(".dash-work-item");
  await expect(rows.nth(0)).toContainText("종료된 지능형 업무 시스템 본공고");
  await expect(rows.nth(0)).toContainText("입찰 마감 · 계속 추적");
  await expect(rows.nth(0)).toContainText("D-2");
  await expect(rows.nth(1)).toContainText("의견등록 마감 · 보류");
  await expect(rows.nth(1)).toContainText("D-4");
  // 후보 확인 대기 연결의 더 이른 마감은 고르지 않는다(권위 있는 연결만).
  await expect(rows.nth(2)).toContainText("입찰 마감 · 계속 추적");
  await expect(rows.nth(2)).toContainText("D-7");
  await expect(rows.nth(0).getByRole("link")).toHaveAttribute("href", "/opportunities/501");
  const styles = await page.evaluate(() => {
    const cells = [...document.querySelectorAll(".dash-work-panel .dash-work-due")].slice(0, 3);
    return cells.map(cell => ({
      text: cell.textContent, weight: getComputedStyle(cell).fontWeight, color: getComputedStyle(cell).color,
      urgent: cell.classList.contains("dash-work-due-urgent"),
    }));
  });
  expect(styles[0].urgent).toBe(true);
  expect(styles[1].urgent).toBe(false);
  expect(Number(styles[0].weight)).toBeGreaterThan(Number(styles[1].weight));
  expect(styles[0].color).not.toBe(styles[1].color);
});

test("최종 결정 대기는 추정가격과 마감 미제공을 구분한다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  const rows = panel(page, "최종 결정 대기").locator(".dash-work-item");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("경상남도 · 추정가격 940,000,000원");
  await expect(rows.nth(0)).toContainText("D-2");
  await expect(rows.nth(1)).toContainText("강원특별자치도 · 추정가격 미제공");
  await expect(rows.nth(1)).toContainText("마감 미제공");
  await expect(rows.nth(1)).not.toContainText("D-");
  await expect(rows.nth(0).getByRole("link")).toHaveAttribute("href", "/go-no-go?selected=701");
});

test("새 관련 발주계획 행은 기관·예산·발주 예정과 모델 판단을 적는다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  const rows = panel(page, "새 관련 발주계획").locator(".dash-work-item");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("경기도청 · 1,240,000,000원 · 2026년 11월");
  await expect(rows.nth(0)).toContainText("모델 · 관련");
  // 서버가 값을 주지 않은 칸은 지어내지 않는다.
  await expect(rows.nth(1)).toContainText("예금보험공사 · 예산 미제공 · 2026년 · 월 미제공");
  await expect(rows.nth(0).getByRole("link")).toHaveAttribute("href", "/order-plans?selected=901");
});

test("한 패널의 조회 실패가 다른 패널을 막지 않고 그 패널에서만 다시 조회한다", async ({ page }) => {
  const options = { decisionError: true };
  await mockDashboard(page, options);
  await page.goto("/");
  const failed = panel(page, "최종 결정 대기");
  await expect(failed.getByRole("alert")).toContainText("최종 결정 대기 목록을 불러오지 못했어요");
  // 바닥 건수는 같은 대기열(검토 대상 정의)에서 오므로 대기열이 실패하면 0이 아니라 미확인이다.
  await expect(failed.locator(".dash-panel-foot")).toContainText("검토 대상 미확인");
  await expect(panel(page, "마감 임박 추적 건").locator(".dash-work-item")).toHaveCount(3);
  await expect(panel(page, "새 관련 발주계획").locator(".dash-work-item")).toHaveCount(2);
  await expect(panel(page, "마감 임박 추적 건").getByRole("alert")).toHaveCount(0);
  options.decisionError = false;
  await failed.getByRole("button", { name: "다시 시도", exact: true }).click();
  await expect(failed.locator(".dash-work-item")).toHaveCount(2);
  await expect(failed.getByRole("alert")).toHaveCount(0);
});

test("패널마다 로딩과 빈 상태를 다른 문장으로 구분한다", async ({ page }) => {
  await mockDashboard(page, {
    deadlines: opportunityList([], 0),
    overviewFailed: preSpecList([], 0),
    overviewAttention: preSpecList([], 0),
    blocking: opportunityList([], 0),
  });
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route(url => url.pathname === "/api/bid-delta/decision-queue", async route => { await pending; await route.fallback(); });
  const decision = panel(page, "최종 결정 대기");
  try {
    await page.goto("/");
    await expect(decision.locator(".dash-panel-body").getByRole("status")).toHaveText("최종 결정 대기 목록을 불러오는 중");
    await expect(panel(page, "마감 임박 추적 건")).toContainText("7일 이내 마감인 추적 건이 없어요");
    await expect(panel(page, "사람 확인 필요")).toContainText("사람이 확인할 개요 검토와 확인 항목이 없어요");
  } finally { release(); }
  await expect(decision.locator(".dash-work-item")).toHaveCount(2);
});

test("새로고침은 모든 패널을 다시 조회한다", async ({ page }) => {
  const trace = await mockDashboard(page);
  await page.goto("/");
  await expect(panel(page, "마감 임박 추적 건").locator(".dash-work-item")).toHaveCount(3);
  const before = trace.requests.length;
  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect.poll(() => trace.requests.length).toBeGreaterThanOrEqual(before + 8);
});

// S1 — 표를 다른 업무 패널과 같은 `WorkRow`로 옮겼다. 데이터·호출·건수 키·바닥 문구는
// 그대로이고, 행은 `사업명 / {보류 사유} · {선택자} / 기한` 세 자리다. 기한 지남과
// 기한 미확인은 서로 다른 말로 남기며 날짜를 지어내지 않는다.
test("보류 재검토는 회차 없이 기한순 5건을 업무 패널과 같은 행으로 보여 준다", async ({ page }) => {
  const trace = await mockDashboard(page, { holdReviews: holdReviewList(holdReviewItems, 7), workload: workloadWith("tracking_hold_review_due", 2) });
  await page.goto("/");
  const region = panel(page, "보류 재검토");
  await expect(region).toContainText("보류는 선택 후 14일이 지나면 다시 검토해요.");
  await expect(region.locator(".dash-panel-head")).toContainText("기한 지남 2건");
  // 표가 아니라 행 목록이다(1280 반폭에서 마지막 열이 가로로 밀리던 자리).
  await expect(region.getByRole("table")).toHaveCount(0);
  const rows = region.locator(".dash-work-item");
  await expect(rows).toHaveCount(5);
  const holdRequests = trace.requests.filter(entry => entry.path === "/api/opportunities" && "hold_review" in entry.params);
  expect(holdRequests).toHaveLength(1);
  expect(holdRequests[0].params).toEqual({ hold_review: "attention", sort: "hold_review_due_at", limit: "5" });
  await expect(rows.nth(0)).toContainText("공공데이터 통합관리체계 고도화");
  await expect(rows.nth(0)).toContainText("예산 편성 결과를 확인한 뒤 다시 검토 · 김보류");
  await expect(rows.nth(0)).toContainText("기한 지남");
  // 값이 없는 제목·사유·선택자는 서로 다른 말로 남긴다.
  await expect(rows.nth(1)).toContainText("제목 미확인");
  await expect(rows.nth(1)).toContainText("사유 미확인 · 선택자 미확인");
  await expect(rows.nth(1)).toContainText("기한 지남");
  // 한국 자정 경계(UTC 15:30 → KST 다음 날 00:30)와 마이크로초를 그대로 넘긴다.
  await expect(rows.nth(2)).toContainText("발주처 사업 범위 확정 대기 · 이담당");
  await expect(rows.nth(2)).toContainText("기한 09.18");
  await expect(rows.nth(3)).toContainText("사유 미확인 · 박선택");
  await expect(rows.nth(3)).toContainText("기한 09.19");
  await expect(rows.nth(4)).toContainText("공동수급 조건 확인 필요 · 최담당");
  await expect(rows.nth(4)).toContainText("기한 09.20");
  await expect(rows.nth(0).getByRole("link")).toHaveAttribute("href", "/opportunities/401");
  // 기한 지남만 강조한다(색만으로 전달하지 않도록 문구도 다르다).
  const urgent = await page.evaluate(() => [...document.querySelectorAll(".dash-hold-panel .dash-work-due")]
    .map(cell => ({ text: cell.textContent, urgent: cell.classList.contains("dash-work-due-urgent") })));
  expect(urgent.map(cell => cell.urgent)).toEqual([true, true, false, false, false]);
  await expect(region.locator(".dash-panel-foot")).toContainText("기한 지남·임박 7건 중 5건 표시");
});

test("보류 기한 지남 건수를 받지 못하면 0건으로 채우지 않는다", async ({ page }) => {
  await mockDashboard(page, { holdReviews: holdReviewList(holdReviewItems.slice(0, 1)), workload: workloadWith("tracking_hold_review_due", null, "provider_absent") });
  await page.goto("/");
  const head = panel(page, "보류 재검토").locator(".dash-panel-head");
  await expect(head).toContainText("기한 지남 건수 미확인");
  await expect(head).not.toContainText("0건");
});

// S1 — 패널의 링크가 목적지 화면에서 **같은 집합**을 연다. 여기서는 같은 mock이 패널과
// 목록 화면에 같은 응답을 주므로, 같은 행이 나오는 것으로 모집단이 같음을 본다.
test("마감 임박 바로가기는 사업기회를 같은 조건·같은 집합으로 연다", async ({ page }) => {
  const trace = await mockDashboard(page);
  await page.goto("/");
  const region = panel(page, "마감 임박 추적 건");
  await expect(region.locator(".dash-work-item")).toHaveCount(3);
  const titles = await region.locator(".dash-work-title").allTextContents();
  await region.getByRole("link", { name: "사업기회", exact: true }).click();

  await expect.poll(() => new URL(page.url()).pathname).toBe("/opportunities");
  const params = new URL(page.url()).searchParams;
  expect(params.get("section")).toBe("전체");
  expect(params.get("deadline_within_days")).toBe("7");
  expect(params.get("sort")).toBe("deadline");
  // 목록 화면이 서버에 보낸 조건이 패널이 보낸 것과 같다 — 구역은 `전체`라 보내지 않는다.
  await expect(page.locator(".opportunity-row-title")).toHaveText(titles);
  const listRequest = trace.requests.filter(entry => entry.path === "/api/opportunities" && "deadline_within_days" in entry.params).at(-1);
  expect(listRequest?.params.deadline_within_days).toBe("7");
  expect(listRequest?.params.sort).toBe("deadline");
  expect(listRequest?.params.section).toBeUndefined();
  await expect(page.locator(".opportunity-list-head")).toContainText("전체 · 7일 이내 마감 전체 7건");

  // 걸린 창은 접힘과 무관한 문맥 줄이 말하고 거기서 해제한다.
  const context = page.locator(".opportunity-deadline-context");
  await expect(context).toContainText("7일 이내 마감");
  await context.getByRole("button", { name: "해제", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.has("deadline_within_days")).toBe(false);
  await expect(page.locator(".opportunity-deadline-context")).toHaveCount(0);
  expect(trace.writes).toEqual([]);
});

test("새 관련 발주계획 바로가기는 발주계획을 같은 첫 수집 창·같은 집합으로 연다", async ({ page }) => {
  await mockApi(page); await mockOrderPlans(page);
  // 전일(KST)이 공용 fixture의 첫 관측일 `2026-09-01`이 되는 시각으로 맞춘다.
  await page.clock.setFixedTime(new Date("2026-09-02T03:00:00Z"));
  await page.goto("/");
  const region = panel(page, "새 관련 발주계획");
  await expect(region.locator(".dash-work-item").first()).toBeVisible();
  const titles = await region.locator(".dash-work-title").allTextContents();
  expect(titles.length).toBeGreaterThan(0);
  const link = region.getByRole("link", { name: "발주계획", exact: true });
  await expect(link).toHaveAttribute("href", "/order-plans?qwen=relevant&tracking=미선택&first_observed_from=2026-09-01");
  await link.click();

  await expect.poll(() => new URL(page.url()).pathname).toBe("/order-plans");
  await expect(page.locator(".c2l-observed-context")).toContainText("09-01 이후 첫 수집");
  // 같은 세 조건(첫 수집 창 · 모델 판단 관련 · 추적 미선택)이 목록 화면에 걸린다.
  // 축이 `관련` 탭과 같으므로 머리 한 줄은 탭 이름과 짧은 뜻을 말하고, 더 걸린 첫 수집 창도 밝힌다(2026-11-19 시안).
  await expect(page.locator(".c2l-list-head")).toContainText(/관련 \d+건 · 추적을 정하지 않은 건 · 09-01 이후 첫 수집/);
  await expect(page.locator(".c2l-row-title")).toHaveText(titles);
});

for (const [width, height] of WIDTHS) {
  test(`두 폭에서 2열 격자와 전폭 패널이 넘치지 않는다 ${width}`, async ({ page }, info) => {
    const trace = await mockDashboard(page, { holdReviews: holdReviewList(holdReviewItems, 7) });
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await expect(panel(page, "새 관련 발주계획").locator(".dash-work-item")).toHaveCount(2);
    await settleFonts(page);
    const measured = await page.evaluate(() => {
      const rect = (selector: string) => document.querySelector(selector)!.getBoundingClientRect();
      const panels = [...document.querySelectorAll(".dash-work-grid > .dash-panel")].map(node => {
        const box = node.getBoundingClientRect();
        return { label: node.getAttribute("aria-label"), left: box.left, width: box.width, overflow: node.scrollWidth - node.clientWidth };
      });
      return {
        overflow: document.documentElement.scrollWidth - innerWidth,
        strip: { top: rect(".daily-collection").top, left: rect(".daily-collection").left },
        headerBottom: rect('[data-shell-region="topbar"]').bottom,
        panelLeft: rect('[data-shell-region="panel"]').left,
        gridWidth: rect(".dash-work-grid").width,
        panels,
      };
    });
    expect(measured.overflow).toBe(0);
    // 최종 시안 셸(2026-11-19): 패널 헤더 아래 + canvas 위 여백 24, 흰 패널(사이드바 228 오른쪽, 1px 테두리) + canvas 좌 여백 32.
    // 맨 위는 일일 실행 한 줄(설계고도화안 A-5)이고 바로가기 띠가 그 아래다.
    expect(measured.strip.top).toBeCloseTo(measured.headerBottom + physical(24), 0);
    expect(measured.panelLeft).toBeCloseTo(228, 0);
    expect(measured.strip.left).toBeCloseTo(measured.panelLeft + 1 + physical(32), 0);
    expect(measured.panels).toHaveLength(5);
    // 두 열: 1·3번째 패널이 같은 왼쪽 가장자리에서 시작하고 마지막은 전폭이다.
    expect(measured.panels[2].left).toBeCloseTo(measured.panels[0].left, 0);
    expect(measured.panels[3].left).toBeCloseTo(measured.panels[1].left, 0);
    expect(measured.panels[4].width).toBeCloseTo(measured.gridWidth, 0);
    expect(measured.panels[4].left).toBeCloseTo(measured.panels[0].left, 0);
    await page.screenshot({ path: info.outputPath(`dashboard-${width}.png`), animations: "disabled", fullPage: true });
    expect(trace.writes).toEqual([]);
  });

  test(`긴 한글 사업명에서도 폭을 넘지 않는다 ${width}`, async ({ page }, info) => {
    const long = structuredClone(deadlineItems);
    long[0].links[0].title = "공공데이터 통합관리체계 고도화 및 산하기관 데이터 품질관리·공동활용 기반 구축 사업";
    const longAttention = structuredClone(overviewAttentionItems);
    longAttention[0].title = "지방자치단체 행정정보 공동이용 및 데이터 연계 체계 전면 고도화 사전규격 공고";
    await mockDashboard(page, {
      deadlines: opportunityList(long, 7), blocking: blockingList,
      overviewAttention: preSpecList(longAttention, 2), newPlans: newPlanList,
    });
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await expect(panel(page, "마감 임박 추적 건")).toContainText("공동활용");
    await expect(panel(page, "마감 임박 추적 건").locator(".dash-work-item").first()).toContainText("D-2");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBe(0);
    await page.screenshot({ path: info.outputPath(`dashboard-long-${width}.png`), animations: "disabled", fullPage: true });
  });
}

// 대시보드의 `필수 검토 발주계획 N건`은 발주계획 화면의 누적 기본 보기(관련)와 같은 집합이다(spec §7, A-6·C-8).
// 회차를 고르지 않고 들어가도 화면이 누적으로 열려 같은 건수를 보여야 `누적` 문구가 사실이다.
for (const [width, height] of WIDTHS) {
  test(`필수 검토 발주계획 건수는 회차 없이 누적 기본 보기로 열고 관련 건수와 같다 ${width}`, async ({ page }) => {
    await mockApi(page); await mockOrderPlans(page);
    await page.clock.setFixedTime(new Date(DASH_NOW));
    await page.setViewportSize({ width, height }); await page.goto("/");
    const entry = countCell(page, "order-plan-relevant").getByRole("link");
    await expect(entry).toContainText("1건");
    await entry.click();
    await expect.poll(() => new URL(page.url()).pathname).toBe("/order-plans");
    expect(new URL(page.url()).searchParams.has("source_run_id")).toBe(false);
    // 누적으로 열렸다는 것은 위의 URL(source_run_id 없음)이 말한다. 평상시 누적의
    // 범위 줄은 운영자용 감사 정보라 그리지 않는다(2026-09-21).
    await expect(page.getByTestId("order-plan-list-scope")).toHaveCount(0);
    await expect(page.locator(".c2l-list-head")).toContainText("관련 1건 · 추적을 정하지 않은 건");
    await expect(page.locator(".c2l-row")).toHaveCount(1);
  });
}

// 설계고도화안 A-5: "어제 일일 실행이 돌았는가"에 답하는 한 줄. 스케줄을 약속하지 않고 마지막 실행 사실만 적는다.
test.describe("발주계획 일일 실행 한 줄", () => {
  test("일일 수집 회차가 없으면 확인 필요로 적는다", async ({ page }) => {
    await mockDashboard(page);
    await page.goto("/");
    const line = page.getByTestId("daily-run-status");
    await expect(line).toHaveAttribute("data-state", "warning");
    await expect(line).toContainText("확인 필요");
    await expect(line).toContainText("일일 발주계획 수집 기록이 없어요");
    await expect(line).not.toContainText("다음 일일");
  });

  test("오늘 아침 어제 기준일을 수집·부분 성공이면 정상이고 필수 검토·훑어보기와 판정 실패 건수를 적는다", async ({ page }) => {
    await mockDashboard(page);
    // DASH_NOW = 2026-09-17 12:00 KST. 오늘 07:10 KST 수집, 기준일 09-16(전일).
    const run = dailyPlanRunFixture("2026-09-16", "2026-09-16T22:10:00Z");
    await mockDailyPlanRun(page, run, [dailyPlanExecutionFixture(run.run_id, {
      status: "부분 성공", queued_at: "2026-09-16T22:20:00Z",
      counts: { candidate_count: 1200, completed_count: 1175, failure_count: 25, stage1_selected_count: 300, stage1_filtered_out_count: 900, stage1_failed_count: 0,
        stage2_relevant_count: 63, stage2_not_relevant_count: 172, stage2_uncertain_count: 40, stage2_failed_count: 25, stage2_rejected_count: 0, human_review_count: 128 },
    })]);
    await page.goto("/");
    const line = page.getByTestId("daily-run-status");
    await expect(line).toHaveAttribute("data-state", "ok");
    await expect(line).toContainText("최근 기준일 09-16");
    await expect(line).toContainText("수집 9월 17일 · 오늘");
    await expect(line).toContainText("C-2 부분 성공");
    // 수정안 3B: `사람 검토 N건 (…)` 대신 필수 검토·훑어보기를 나누고, 무판정 몫(128 − 63 − 40 = 25)은 0보다 클 때만
    // `판정 실패`로 붙인다(순위 밖을 포함하는 탭 이름 `모델 미판정`과 섞지 않는다).
    await expect(line).toContainText("필수 검토 63건(관련) · 훑어보기 40건(불확실) · 판정 실패 25건");
    await expect(line).not.toContainText("모델 미판정");
    await expect(line).not.toContainText("사람 검토");
    await expect(line).not.toContainText("모델 판정 없음");
  });

  test("최근 기준일이 어제보다 오래됐거나 실행이 실패로 끝났으면 확인 필요다", async ({ page }) => {
    await mockDashboard(page);
    const run = dailyPlanRunFixture("2026-08-10", "2026-08-11T22:00:00Z");
    await mockDailyPlanRun(page, run, [dailyPlanExecutionFixture(run.run_id, { status: "실패", queued_at: "2026-08-11T22:05:00Z" })]);
    await page.goto("/");
    const line = page.getByTestId("daily-run-status");
    await expect(line).toHaveAttribute("data-state", "warning");
    await expect(line).toContainText("36일 전");
    await expect(line).toContainText("C-2 실패");
    await expect(line).toContainText("최근 기준일이 늦었어요");
    await expect(line).toContainText("C-2 실행이 성공·부분 성공으로 끝나지 않았어요");
  });

  test("회차는 있는데 C-2 운영 실행이 없으면 그 사실을 적는다", async ({ page }) => {
    await mockDashboard(page);
    const run = dailyPlanRunFixture("2026-09-15", "2026-09-15T22:10:00Z");
    // 측정 전용 실행은 일일 실행이 아니다.
    await mockDailyPlanRun(page, run, [dailyPlanExecutionFixture(run.run_id, { purpose: "gate_measurement", status: "성공" })]);
    await page.goto("/");
    const line = page.getByTestId("daily-run-status");
    await expect(line).toHaveAttribute("data-state", "warning");
    await expect(line).toContainText("C-2 실행 없음");
    await expect(line).toContainText("이 회차에는 C-2 운영 실행이 없어요");
  });
});

// 2026-11-18 운영 관측: 지난 날을 메우는 수집이 진행 중일 때 "확인 필요"로 잘못 보였다.
test.describe("발주계획 일일 실행 한 줄 · 기준일과 진행 중", () => {
  const counts = { candidate_count: 559, completed_count: 559, failure_count: 0, stage1_selected_count: 300, stage1_filtered_out_count: 259, stage1_failed_count: 0,
    stage2_relevant_count: 41, stage2_not_relevant_count: 200, stage2_uncertain_count: 59, stage2_failed_count: 0, stage2_rejected_count: 0, human_review_count: 100 };

  test("나중에 수집한 지난 기준일(따라잡기)이 최근 기준일의 결과를 가리지 않는다", async ({ page }) => {
    await mockDashboard(page);
    // DASH_NOW = 2026-09-17 12:00 KST. 어제 아침 09-16 기준일이 끝났고, 오늘 09-09 기준일을 메우는 중이다.
    const yesterday = dailyPlanRunFixture("2026-09-16", "2026-09-16T22:00:00Z");
    const catchUp = dailyPlanRunFixture("2026-09-09", "2026-09-17T02:30:00Z");
    await mockDailyPlanRuns(page, [yesterday, catchUp], [
      dailyPlanExecutionFixture(yesterday.run_id, { status: "성공", queued_at: "2026-09-16T22:05:00Z", counts }),
      dailyPlanExecutionFixture(catchUp.run_id, { status: "실행 중", queued_at: "2026-09-17T02:35:00Z" }),
    ]);
    await page.goto("/");
    const line = page.getByTestId("daily-run-status");
    await expect(line).toHaveAttribute("data-state", "ok");
    await expect(line).toContainText("최근 기준일 09-16");
    await expect(line).toContainText("C-2 성공");
    // 무판정 몫이 0이면(100 − 41 − 59) 판정 실패 조각을 붙이지 않는다.
    await expect(line).toContainText("필수 검토 41건(관련) · 훑어보기 59건(불확실)");
    await expect(line).not.toContainText("판정 실패");
  });

  test("실행 중은 문제가 아니라 진행 중이고 경과 시간을 적는다", async ({ page }) => {
    await mockDashboard(page);
    const run = dailyPlanRunFixture("2026-09-16", "2026-09-17T01:00:00Z");
    await mockDailyPlanRun(page, run, [dailyPlanExecutionFixture(run.run_id, { status: "실행 중", queued_at: "2026-09-17T01:20:00Z" })]);
    await page.goto("/");
    const line = page.getByTestId("daily-run-status");
    await expect(line).toHaveAttribute("data-state", "in_progress");
    await expect(line).toContainText("진행 중");
    await expect(line).toContainText("C-2 실행 중 · 1시간 40분째");
    await expect(line).not.toContainText("확인 필요");
    await expect(line).not.toContainText("필수 검토");
  });

  test("4시간을 넘긴 진행 중은 오래 진행 중으로 확인 필요다", async ({ page }) => {
    await mockDashboard(page);
    const run = dailyPlanRunFixture("2026-09-16", "2026-09-16T21:00:00Z");
    await mockDailyPlanRun(page, run, [dailyPlanExecutionFixture(run.run_id, { status: "대기", queued_at: "2026-09-16T22:00:00Z" })]);
    await page.goto("/");
    const line = page.getByTestId("daily-run-status");
    await expect(line).toHaveAttribute("data-state", "warning");
    await expect(line).toContainText("C-2 대기 · 5시간 0분째");
    await expect(line).toContainText("오래 진행 중 — 실행 상태 확인");
  });

  test("수집 0건 회차에 실행이 없는 것은 문제가 아니다", async ({ page }) => {
    await mockDashboard(page);
    const run = { ...dailyPlanRunFixture("2026-09-16", "2026-09-16T22:00:00Z"), counts: { notices: 0, judgments: 0, reviews: 0, collection: { total: 0 } } };
    await mockDailyPlanRun(page, run, []);
    await page.goto("/");
    const line = page.getByTestId("daily-run-status");
    await expect(line).toHaveAttribute("data-state", "ok");
    await expect(line).toContainText("C-2 실행 없음 · 수집 0건");
  });
});

test("dailyRunStatus: 기준일 선택·진행 중·4시간·종료 실패·부분 성공 건수를 순수 함수로 가른다", () => {
  const now = Date.parse("2026-11-18T03:00:00Z"); // 11-18 12:00 KST
  const y = dailyPlanRunFixture("2026-11-17", "2026-11-17T22:00:00Z");
  const old = dailyPlanRunFixture("2026-11-09", "2026-11-18T02:00:00Z"); // 따라잡기: 늦게 수집한 지난 기준일
  const retry = { ...dailyPlanRunFixture("2026-11-17", "2026-11-18T01:00:00Z"), run_id: "lifecycle-20261117-plans-retry1--20261118T010000.000000Z" };
  expect(latestDailyPlanRun([old, y])?.basisDate).toBe("2026-11-17");
  expect(latestDailyPlanRun([old, y, retry])?.run.run_id).toBe(retry.run_id);

  const at = (status: string, queued: string, extra = {}) => dailyPlanExecutionFixture(y.run_id, { status: status as never, queued_at: queued, ...extra });
  expect(dailyRunStatus([y], [at("실행 중", "2026-11-18T01:00:00Z")], now)).toMatchObject({ state: "in_progress", inProgressMs: 2 * 3_600_000, problems: [], noJudgmentCount: null });
  expect(dailyRunStatus([y], [at("중지 요청", "2026-11-17T22:59:00Z")], now)).toMatchObject({ state: "warning", problems: ["in_progress_too_long"] });
  expect(dailyRunStatus([y], [at("실패", "2026-11-17T22:10:00Z")], now)).toMatchObject({ state: "warning", problems: ["execution_not_done"] });
  expect(dailyRunStatus([y], [], now)).toMatchObject({ state: "warning", problems: ["no_execution"] });
  const partial = dailyRunStatus([y], [at("부분 성공", "2026-11-17T22:10:00Z", { counts: {
    candidate_count: 1, completed_count: 1, failure_count: 0, stage1_selected_count: 0, stage1_filtered_out_count: 0, stage1_failed_count: 0,
    stage2_relevant_count: 63, stage2_not_relevant_count: 0, stage2_uncertain_count: 40, stage2_failed_count: 25, stage2_rejected_count: 0, human_review_count: 128 } })], now);
  expect(partial).toMatchObject({ state: "ok", noJudgmentCount: 25, basisLag: 1 });
  expect(dailyRunStatus([old], [], now).problems).toEqual(["stale", "no_execution"]);
});

// 2026-11-18 G1·G2: 공고 트랙도 같은 묶음의 한 행이고, 자정~정오에는 그저께 기준일까지를 정상으로 본다.
test("isBasisStale·dailyNoticeStatus: 정오 기준 규칙과 공고 트랙 최근 기준일", () => {
  const morning = Date.parse("2026-11-18T02:59:00Z"); // 11:59 KST
  const noon = Date.parse("2026-11-18T03:00:00Z"); // 12:00 KST
  expect(isBasisStale("2026-11-16", morning)).toBe(false);
  expect(isBasisStale("2026-11-15", morning)).toBe(true);
  expect(isBasisStale("2026-11-16", noon)).toBe(true);
  expect(isBasisStale("2026-11-17", noon)).toBe(false);
  expect(isBasisStale("2026-11-16", Date.parse("2026-11-17T15:30:00Z"))).toBe(false); // 00:30 KST
  const y = dailyNoticeRunFixture("2026-11-17", "2026-11-17T22:00:00Z");
  const old = dailyNoticeRunFixture("2026-11-10", "2026-11-18T01:00:00Z");
  const plan = dailyPlanRunFixture("2026-11-17", "2026-11-17T22:00:00Z");
  expect(dailyNoticeStatus([old, y, plan], 3, noon)).toMatchObject({ state: "ok", warningCount: 3, problems: [] });
  expect(dailyNoticeStatus([old, y, plan], 3, noon).latest?.run.run_id).toBe(y.run_id);
  expect(dailyNoticeStatus([old], null, noon)).toMatchObject({ state: "warning", problems: ["stale"] });
  expect(dailyNoticeStatus([plan], null, noon)).toMatchObject({ state: "warning", problems: ["no_daily_run"] });
});

test.describe("일일 수집 묶음 · 공고 트랙", () => {
  test("두 트랙은 한 묶음의 두 행이고 공고 행은 최근 기준일·적재일·적재 경고 수를 적는다", async ({ page }) => {
    await mockDashboard(page);
    const plan = dailyPlanRunFixture("2026-09-16", "2026-09-16T22:10:00Z");
    const notice = dailyNoticeRunFixture("2026-09-16", "2026-09-16T21:40:00Z");
    await mockDailyPlanRuns(page, [plan, notice], [dailyPlanExecutionFixture(plan.run_id, { status: "성공", queued_at: "2026-09-16T22:20:00Z" })]);
    await mockRunWarnings(page, notice.run_id, 2);
    await page.goto("/");
    const block = page.getByTestId("daily-collection");
    await expect(block).toContainText("일일 수집");
    await expect(block).toContainText("오늘 기준일은 아직 수집 전일 수 있어요");
    await expect(block.locator(".daily-run-line")).toHaveCount(2);
    const row = page.getByTestId("daily-notice-status");
    await expect(row).toHaveAttribute("data-state", "ok");
    await expect(row).toContainText("최근 기준일 09-16");
    await expect(row).toContainText("적재 9월 17일 · 오늘");
    await expect(row).toContainText("적재 경고 2건");
  });

  test("공고 트랙의 최근 기준일이 늦으면 그 행만 확인 필요다", async ({ page }) => {
    await mockDashboard(page);
    const plan = dailyPlanRunFixture("2026-09-16", "2026-09-16T22:10:00Z");
    const notice = dailyNoticeRunFixture("2026-09-10", "2026-09-10T21:40:00Z");
    await mockDailyPlanRuns(page, [plan, notice], [dailyPlanExecutionFixture(plan.run_id, { status: "성공", queued_at: "2026-09-16T22:20:00Z" })]);
    await mockRunWarnings(page, notice.run_id, 0);
    await page.goto("/");
    await expect(page.getByTestId("daily-run-status")).toHaveAttribute("data-state", "ok");
    const row = page.getByTestId("daily-notice-status");
    await expect(row).toHaveAttribute("data-state", "warning");
    await expect(row).toContainText("최근 기준일이 늦었어요");
  });

  test("자정과 정오 사이에는 그저께 기준일도 정상이다", async ({ page }) => {
    await mockDashboard(page, { skipClock: true });
    await page.clock.setFixedTime(new Date("2026-09-16T16:00:00Z")); // 09-17 01:00 KST
    const plan = dailyPlanRunFixture("2026-09-15", "2026-09-15T22:10:00Z");
    const notice = dailyNoticeRunFixture("2026-09-15", "2026-09-15T21:40:00Z");
    await mockDailyPlanRuns(page, [plan, notice], [dailyPlanExecutionFixture(plan.run_id, { status: "성공", queued_at: "2026-09-15T22:20:00Z" })]);
    await mockRunWarnings(page, notice.run_id, 0);
    await page.goto("/");
    await expect(page.getByTestId("daily-run-status")).toHaveAttribute("data-state", "ok");
    await expect(page.getByTestId("daily-notice-status")).toHaveAttribute("data-state", "ok");
  });
});
