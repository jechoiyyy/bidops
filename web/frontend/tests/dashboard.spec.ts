import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import {
  DASH_NOW, blockingList, dashboardWorkload, deadlineItems, deadlineList, holdReviewItems, holdReviewList,
  mockDashboard, newPlanList, opportunityList, overviewAttentionItems, preSpecList, workloadWith,
} from "./dashboard-fixtures";
import { settleFonts } from "./screen-fixtures";
import { mockApi, mockOrderPlans } from "./api-mock";

const UI_SCALE = 0.9;
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
  await expect(page.locator(".dash-dashboard-foot")).toContainText("최종 참여 판단은 최종 Go/No-Go에서 진행합니다.");
  expect(new URL(page.url()).searchParams.has("run")).toBe(false);
});

test("네 업무 바로가기와 발주계획 타일의 `새로`", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  const links = page.locator(".dash-journey-item");
  await expect(links).toHaveCount(4);
  await expect(links.nth(0)).toContainText("검토 후보 24건 · 누적 · 새로 12");
  await expect(links.nth(1)).toContainText("결정 대기 7건");
  await expect(links.nth(2)).toContainText("조치 필요 3건");
  await expect(links.nth(3)).toContainText("결정 대기 4건");
  await expect(links.nth(2)).toHaveAttribute("href", "/opportunities?section=조치 필요");
  await expect(links.nth(3)).toHaveAttribute("href", "/go-no-go");
});

test("`새로`를 셀 수 없으면 0이 아니라 미확인으로 적는다", async ({ page }) => {
  await mockDashboard(page, { workload: workloadWith("order_plan_new_priority", null, "provider_absent") });
  await page.goto("/");
  const tile = page.locator(".dash-journey-item").first();
  await expect(tile).toContainText("검토 후보 24건 · 누적 · 새로 미확인");
  await expect(tile).not.toContainText("새로 0");
  // 같은 키를 쓰는 패널 바닥도 사유를 남기고 0으로 채우지 않는다.
  const foot = panel(page, "새 우선 검토 발주계획").locator(".dash-panel-foot");
  await expect(foot).toContainText("추적 미선택 건수 미확인 · 집계 모듈 없음");
  await expect(foot).not.toContainText("0건");
});

test("누적 패널 다섯이 제목·목적지·기준을 갖는다", async ({ page }) => {
  await mockDashboard(page, { holdReviews: holdReviewList(holdReviewItems.slice(0, 1), 1) });
  await page.goto("/");
  // 두 링크(S1)는 목적지 화면에 **패널의 목록 호출과 같은 조건**을 넘긴다. 마감 임박은
  // 기본 구역이 걸리지 않게 `section=전체`를 함께 건다.
  const expectations: [string, string, string][] = [
    ["마감 임박 추적 건", "사업 추적", "/opportunities?section=전체&deadline_within_days=7&sort=deadline"],
    ["최종 결정 대기", "최종 Go/No-Go", "/go-no-go"],
    ["사람 확인 필요", "사전규격", "/pre-specs?workspace=all&sw_only=false&overview_view=attention"],
    ["보류 재검토", "사업 추적에서 모두 보기", "/opportunities?section=조치 필요&reason=hold_overdue"],
    ["새 우선 검토 발주계획", "발주계획", "/order-plans?qwen=relevant&tracking=미선택&first_observed_from=2026-09-16"],
  ];
  for (const [title, linkLabel, href] of expectations) {
    const region = panel(page, title);
    await expect(region).toBeVisible();
    await expect(region.getByRole("link", { name: linkLabel, exact: true })).toHaveAttribute("href", href);
  }
  await expect(panel(page, "최종 결정 대기").locator(".dash-panel-foot")).toContainText("입찰 마감순");
  await expect(panel(page, "최종 결정 대기").locator(".dash-panel-foot")).toContainText("결정 없음 4건");
  await expect(panel(page, "새 우선 검토 발주계획").locator(".dash-panel-foot")).toContainText("전일 수집 이후 처음 관측");
  await expect(panel(page, "새 우선 검토 발주계획").locator(".dash-panel-foot")).toContainText("추적 미선택 12건 중 상위 5건");
  await expect(panel(page, "사람 확인 필요")).toContainText("확인 항목은 추적 상태와 무관하게 셉니다.");
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
  await expect(region).toContainText("7일 이내 마감인 추적 건이 없습니다");
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

test("새 우선 검토 발주계획 행은 기관·예산·발주 예정과 모델 판단을 적는다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  const rows = panel(page, "새 우선 검토 발주계획").locator(".dash-work-item");
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
  await expect(failed.getByRole("alert")).toContainText("최종 결정 대기 목록을 불러오지 못했습니다");
  // 건수는 workload에서 오므로 목록이 실패해도 그대로 남는다.
  await expect(failed.locator(".dash-panel-foot")).toContainText("결정 없음 4건");
  await expect(panel(page, "마감 임박 추적 건").locator(".dash-work-item")).toHaveCount(3);
  await expect(panel(page, "새 우선 검토 발주계획").locator(".dash-work-item")).toHaveCount(2);
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
    await expect(panel(page, "마감 임박 추적 건")).toContainText("7일 이내 마감인 추적 건이 없습니다");
    await expect(panel(page, "사람 확인 필요")).toContainText("사람이 확인할 개요 검토와 확인 항목이 없습니다");
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
  await expect(region).toContainText("보류는 선택 후 14일이 지나면 다시 검토합니다.");
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
test("마감 임박 바로가기는 사업 추적을 같은 조건·같은 집합으로 연다", async ({ page }) => {
  const trace = await mockDashboard(page);
  await page.goto("/");
  const region = panel(page, "마감 임박 추적 건");
  await expect(region.locator(".dash-work-item")).toHaveCount(3);
  const titles = await region.locator(".dash-work-title").allTextContents();
  await region.getByRole("link", { name: "사업 추적", exact: true }).click();

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

test("새 우선 검토 바로가기는 발주계획을 같은 첫 수집 창·같은 집합으로 연다", async ({ page }) => {
  await mockApi(page); await mockOrderPlans(page);
  // 전일(KST)이 공용 fixture의 첫 관측일 `2026-09-01`이 되는 시각으로 맞춘다.
  await page.clock.setFixedTime(new Date("2026-09-02T03:00:00Z"));
  await page.goto("/");
  const region = panel(page, "새 우선 검토 발주계획");
  await expect(region.locator(".dash-work-item").first()).toBeVisible();
  const titles = await region.locator(".dash-work-title").allTextContents();
  expect(titles.length).toBeGreaterThan(0);
  const link = region.getByRole("link", { name: "발주계획", exact: true });
  await expect(link).toHaveAttribute("href", "/order-plans?qwen=relevant&tracking=미선택&first_observed_from=2026-09-01");
  await link.click();

  await expect.poll(() => new URL(page.url()).pathname).toBe("/order-plans");
  await expect(page.locator(".c2l-observed-context")).toContainText("09-01 이후 첫 수집");
  // 같은 세 조건(첫 수집 창 · 모델 판단 관련 · 추적 미선택)이 목록 화면에 걸린다.
  await expect(page.locator(".c2l-list-head")).toContainText("09-01 이후 첫 수집 AND 모델 판단 관련 AND 추적 미선택");
  await expect(page.locator(".c2l-row-title")).toHaveText(titles);
});

for (const [width, height] of WIDTHS) {
  test(`두 폭에서 2열 격자와 전폭 패널이 넘치지 않는다 ${width}`, async ({ page }, info) => {
    const trace = await mockDashboard(page, { holdReviews: holdReviewList(holdReviewItems, 7) });
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await expect(panel(page, "새 우선 검토 발주계획").locator(".dash-work-item")).toHaveCount(2);
    await settleFonts(page);
    const measured = await page.evaluate(() => {
      const rect = (selector: string) => document.querySelector(selector)!.getBoundingClientRect();
      const panels = [...document.querySelectorAll(".dash-work-grid > .dash-panel")].map(node => {
        const box = node.getBoundingClientRect();
        return { label: node.getAttribute("aria-label"), left: box.left, width: box.width, overflow: node.scrollWidth - node.clientWidth };
      });
      return {
        overflow: document.documentElement.scrollWidth - innerWidth,
        strip: { top: rect(".dash-journey-strip").top, left: rect(".dash-journey-strip").left },
        gridWidth: rect(".dash-work-grid").width,
        panels,
      };
    });
    expect(measured.overflow).toBe(0);
    expect(measured.strip.top).toBeCloseTo(physical(92), 0);
    expect(measured.strip.left).toBeCloseTo(physical(272), 0);
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

// 대시보드의 `발주계획 · 검토 후보 N건 · 누적`은 발주계획 화면의 누적 기본 보기와 같은 집합이다(spec §7).
// 회차를 고르지 않고 들어가도 화면이 누적으로 열려 같은 건수를 보여야 `누적` 문구가 사실이다.
for (const [width, height] of WIDTHS) {
  test(`발주계획 바로가기는 회차 없이 누적 기본 보기로 열고 검토 후보 건수와 같다 ${width}`, async ({ page }) => {
    await mockApi(page); await mockOrderPlans(page);
    await page.clock.setFixedTime(new Date(DASH_NOW));
    await page.setViewportSize({ width, height }); await page.goto("/");
    const entry = page.locator(".dash-journey-item").first();
    await expect(entry).toContainText("검토 후보 2건");
    await entry.click();
    await expect.poll(() => new URL(page.url()).pathname).toBe("/order-plans");
    expect(new URL(page.url()).searchParams.has("source_run_id")).toBe(false);
    // 누적으로 열렸다는 것은 위의 URL(source_run_id 없음)이 말한다. 평상시 누적의
    // 범위 줄은 운영자용 감사 정보라 그리지 않는다(2026-09-21).
    await expect(page.getByTestId("order-plan-list-scope")).toHaveCount(0);
    await expect(page.locator(".c2l-list-head")).toContainText("발주계획 목록 · 2건");
    await expect(page.locator(".c2l-row")).toHaveCount(2);
  });
}
