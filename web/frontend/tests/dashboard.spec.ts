import { expect, test } from "@playwright/test";
import { deadlineLabel, remainingDeadlineDays } from "../src/lib/deadline";
import type { Page } from "@playwright/test";
import {
  DASH_NOW, actionRequiredList, deadlineItems, decisionItems, mockDashboard, opportunityList, preSpecList,
} from "./dashboard-fixtures";
import { settleFonts } from "./screen-fixtures";
import { dailyNoticeStatus, dailyRunStatus, isBasisStale, latestDailyPlanRun } from "../src/lib/orderPlanDaily";
import { compactWon } from "../src/components/dashboard/agendaModel";
import { dailyNoticeRunFixture, dailyPlanExecutionFixture, dailyPlanRunFixture, mockDailyPlanRun, mockDailyPlanRuns, mockRunWarnings } from "./api-mock";

// 2026-11-27 시안 C2(`docs/1127_today-simplify/`): 요약 줄 · 추적 중인 사업 마감 일정 · 함께 볼 것 한 줄.
// 고정 시각은 KST 2026-09-17(목) 12:00이다.
const WIDTHS: [number, number][] = [[1280, 800], [1440, 900]];

function agenda(page: Page) {
  return page.getByRole("list", { name: "마감 일정", exact: true });
}
function agendaRows(page: Page, kind?: "tracking" | "final") {
  return agenda(page).locator(kind ? `.dash-agenda-item[data-kind="${kind}"]` : ".dash-agenda-item");
}
function agendaBody(page: Page) {
  return page.locator('.dash-block[data-block="agenda"] .dash-agenda-body');
}
function summary(page: Page, id: string) {
  return page.locator(`.dash-summary-cell[data-summary="${id}"]`);
}
function countLink(page: Page, key: string) {
  return page.locator(`.dash-page a[data-count="${key}"]`);
}

test("회차 선택기와 회차 의존 패널이 화면에서 빠졌다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  await expect(agenda(page)).toBeVisible();
  await expect(page.getByRole("button", { name: "조회할 실행 회차" })).toHaveCount(0);
  await expect(page.locator(".dash-run-context")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "회차 실행 보기", exact: true })).toHaveCount(0);
  await expect(page.locator(".dash-page")).not.toContainText("1차 필터 누락");
  await expect(page.locator(".dash-page")).not.toContainText("판정 표본");
  expect(new URL(page.url()).searchParams.has("run")).toBe(false);
});

test("한 장 구성: 요약 줄 · 마감 일정 · 함께 볼 것만 있고 다른 화면과 겹치는 묶음은 없다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  await expect(page.locator(".dash-summary-cell")).toHaveCount(3);
  await expect(page.locator(".dash-summary-title")).toHaveText(["결정할 것", "멈춘 것", "새로 들어온 것"]);
  await expect(page.locator(".dash-block-head h2")).toHaveText(["추적 중인 사업 · 마감 일정"]);
  const order = await page.evaluate(() => [...document.querySelectorAll(".dash-page > *")].map(node => node.className.split(" ")[0]));
  expect(order).toEqual(["dash-summary", "dash-block", "dash-also"]);
  // 사이드바·목록 화면과 겹치던 것: 건수 띠, 필수 검토·훑어보기 발주계획, 사람 확인 목록, 새 발주계획 상위 5건.
  await expect(page.locator(".dash-count-strip")).toHaveCount(0);
  for (const gone of ["필수 검토 발주계획", "훑어보기 발주계획", "사전규격 검토할 항목"]) {
    await expect(page.locator(".dash-page")).not.toContainText(gone);
  }
  for (const gone of ["사람 확인 필요", "보류 재검토", "새 관련 발주계획", "오늘의 브리핑"]) {
    await expect(page.getByRole("region", { name: gone, exact: true })).toHaveCount(0);
  }
  // 일일 수집 세부는 본문이 아니라 헤더의 접힌 상태 줄 안에 있다.
  await expect(page.locator(".dash-page [data-testid='daily-collection']")).toHaveCount(0);
  await expect(page.getByTestId("daily-collection")).toBeHidden();
});

test("요약 줄의 건수는 목적지 목록의 기본 보기와 같은 정의이고 그 목록으로 잇는다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  const expectations: [string, string, string][] = [
    ["deadline", "7건", "/opportunities?section=전체&deadline_within_days=7&sort=deadline"],
    ["go-no-go", "최종 Go/No-Go 4건", "/go-no-go"],
    ["pre-spec-needs-check", "3건", "/pre-specs?workspace=needs_check"],
    ["new-order-plan", "발주계획 12건", "/order-plans?qwen=relevant&tracking=미선택&first_observed_from=2026-09-16"],
    ["new-pre-spec", "사전규격 4건", "/pre-specs?workspace=recent&observed_from=2026-09-16"],
  ];
  for (const [key, text, href] of expectations) {
    await expect(countLink(page, key), key).toHaveText(text);
    await expect(countLink(page, key), key).toHaveAttribute("href", href);
  }
  await expect(summary(page, "decide")).toContainText("마감 7일 이내 추적 건");
  await expect(summary(page, "stuck")).toContainText("사전규격 개요 실패·취소 · 문서 준비 중단");
  await expect(summary(page, "new")).toContainText("관련 발주계획·SW 사전규격 · 09-16 이후 첫 수집");
  // 두 대기열은 서로 다른 목록이라 더하지 않는다(7 + 4 = 11을 쓰지 않는다).
  await expect(summary(page, "decide")).not.toContainText("11");
});

test("건수를 셀 수 없으면 0이 아니라 미확인으로 적는다", async ({ page }) => {
  await mockDashboard(page, { newPlanError: true, deadlineError: true });
  await page.goto("/");
  await expect(countLink(page, "new-order-plan")).toHaveText("발주계획 미확인");
  await expect(countLink(page, "deadline")).toHaveText("미확인");
  await expect(summary(page, "decide")).not.toContainText("0건");
});

test("마감 일정은 한국 날짜별로 묶고 빈 날은 한 줄로 접는다", async ({ page }) => {
  const trace = await mockDashboard(page);
  await page.goto("/");
  const days = agenda(page).locator(":scope > li");
  await expect(days).toHaveCount(5);
  expect(await days.evaluateAll(nodes => nodes.map(node => node.getAttribute("data-entry")))).toEqual(["day", "gap", "day", "gap", "day"]);
  // 한 날의 행이 모두 같은 마감 종류면 날짜 칸에 한 번만 적는다.
  await expect(days.locator(".dash-agenda-rail")).toHaveText(["09.19토D-22건입찰 마감", "09.20", "09.21월D-41건의견등록 마감", "09.22", "09.23수D-61건입찰 마감"]);
  await expect(days.nth(1)).toContainText("마감 없음");
  // 3일 이내만 강조한다. 문구(D-n)가 함께 정보를 싣는다.
  expect(await days.locator(".dash-agenda-due").evaluateAll(nodes => nodes.map(node => node.classList.contains("is-urgent")))).toEqual([true, false, false]);
  // 같은 날의 추적 건과 최종 결정 대기가 한 묶음에 있다.
  await expect(days.nth(0).locator(".dash-agenda-item")).toHaveCount(2);
  await expect(agendaRows(page, "tracking")).toHaveCount(3);
  await expect(agendaRows(page, "final")).toHaveCount(1);
  const deadlineRequest = trace.requests.find(entry => entry.path === "/api/opportunities" && "deadline_within_days" in entry.params);
  expect(deadlineRequest?.params).toEqual({ deadline_within_days: "7", sort: "deadline", limit: "200" });
  const queueRequest = trace.requests.find(entry => entry.path === "/api/bid-delta/decision-queue");
  expect(queueRequest?.params).toEqual({ status: "pending", limit: "200" });
  expect(trace.writes).toEqual([]);
});

test("오늘 묶음은 마감 시각이 지나도 오늘이고 지난 행에는 지남을 적는다", async ({ page }) => {
  const items = structuredClone(deadlineItems.slice(0, 1));
  // 고정 시각(12:00 KST)보다 이른 오늘 09:00 마감을 가진 최종 결정 대기와 오늘 23:59 추적 건.
  items[0].links[0].deadline_at = "2026-09-17T14:59:00Z";
  await mockDashboard(page, {
    deadlines: opportunityList(items, 1),
    decisions: { items: [{ ...decisionItems[0], opportunity_id: 799, deadline_at: "2026-09-17T00:00:00Z" }], total: 1, limit: 200, offset: 0 },
  });
  await page.goto("/");
  await expect(agenda(page).locator(".dash-agenda-rail")).toHaveText(["09.17목오늘1건입찰 마감"]);
  await expect(agendaBody(page).locator('[data-source="final-outside"]')).toContainText("마감 지남 1건");
  await expect(agendaRows(page, "tracking").locator(".dash-agenda-time")).toHaveText("23:59");
});

test("추적 건 행은 시각·예산과 지금 다가오는 단계를 적고 마감 종류는 날짜 칸에 한 번 적는다", async ({ page }) => {
  const items = structuredClone(deadlineItems);
  // 사전규격 마감 건에 발주계획 연결과 예산을 더한다. 기각된 후보 연결은 단계로 세지 않는다.
  items[1].links[0].budget = 592_000_000;
  items[1].links.push({ ...items[1].links[0], id: 5021, stage: "order_plan", source_type: null, record_type: "order_plan", order_plan_id: 77, deadline_at: null });
  items[1].tracking_selected_by = "루트랩 실무자(에이전트)";
  await mockDashboard(page, { deadlines: opportunityList(items, 7) });
  await page.goto("/");
  const rows = agendaRows(page, "tracking");
  const bid = rows.filter({ hasText: "종료된 지능형 업무 시스템 본공고" });
  await expect(bid.locator(".dash-agenda-time")).toHaveText("09:00");
  await expect(bid.locator(".dash-agenda-step")).toHaveText(["입찰공고 마감 지금 단계"]);
  await expect(bid).toContainText("경상남도 · 예산 미제공");
  await expect(bid.getByRole("link")).toHaveAttribute("href", "/opportunities/501");

  const pre = rows.filter({ hasText: "신규 지능형 행정 지원 사전규격" });
  await expect(pre.locator(".dash-agenda-time")).toHaveText("11:00");
  await expect(pre).toContainText("해솔시청 · 예산 5억 9,200만 원");
  await expect(pre.locator(".dash-agenda-step")).toHaveText(["발주계획 ✓ 연결됨", "사전규격 의견등록 지금 단계", "입찰공고 아직 없음"]);
  expect(await pre.locator(".dash-agenda-step").evaluateAll(nodes => nodes.map(node => node.getAttribute("data-state")))).toEqual(["linked", "current", "absent"]);
  // 결정자 이름은 행마다 싣지 않고, 미리 넣은 에이전트 결정만 `예시 결정`으로 남긴다.
  await expect(pre.locator(".dash-agenda-status")).toHaveText("보류예시 결정");
  await expect(pre.locator(".dash-agenda-status")).not.toContainText("루트랩 실무자");

  // 후보 확인 대기 연결의 더 이른 마감(09-17 18:00)은 고르지 않는다.
  const candidate = rows.filter({ hasText: "행정정보 연계시스템 유지관리 공고" });
  await expect(candidate.locator(".dash-agenda-time")).toHaveText("14:00");
});

test("한 날에 마감 종류가 섞이면 날짜 칸 대신 행마다 마감 종류를 적는다", async ({ page }) => {
  const items = structuredClone(deadlineItems);
  // 사전규격 의견등록 마감을 본공고 입찰 마감과 같은 날(09-19 11:00 KST)로 옮긴다.
  items[1].links[0].deadline_at = "2026-09-19T02:00:00Z";
  await mockDashboard(page, { deadlines: opportunityList(items, 7) });
  await page.goto("/");
  const day = agenda(page).locator(":scope > li").first();
  await expect(day.locator(".dash-agenda-rail")).not.toContainText("마감");
  const rows = agendaRows(page, "tracking");
  await expect(rows.filter({ hasText: "종료된 지능형 업무 시스템 본공고" }).locator(".dash-agenda-time")).toHaveText("09:00입찰 마감");
  await expect(rows.filter({ hasText: "신규 지능형 행정 지원 사전규격" }).locator(".dash-agenda-time")).toHaveText("11:00의견등록 마감");
});

test("최종 결정 대기 행은 추정가격·결정 단계를 적고 일정 밖 대기는 건수로만 센다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  const rows = agendaRows(page, "final");
  await expect(rows).toHaveCount(1);
  await expect(rows.nth(0)).toContainText("경상남도 · 추정가격 9억 4,000만 원");
  await expect(rows.nth(0).locator(".dash-agenda-step")).toHaveText(["입찰공고 ✓ 연결됨", "Go/No-Go 결정 지금 단계"]);
  await expect(rows.nth(0).locator(".dash-agenda-status")).toContainText("Go/No-Go 상태 미확인");
  await expect(rows.nth(0).locator(".dash-agenda-status")).toContainText("최종 결정 대기");
  await expect(rows.nth(0).getByRole("link")).toHaveAttribute("href", "/go-no-go?selected=701");
  // 마감이 없는 대기(702)는 날짜를 지어내지 않고 일정 밖 건수로 센다.
  await expect(agenda(page)).not.toContainText("강원특별자치도");
  const outside = agendaBody(page).locator('[data-source="final-outside"]');
  await expect(outside).toContainText("일정 밖 최종 결정 대기: 7일 밖·마감 미제공 1건 (대기열 4건 중 2건 기준)");
  await expect(outside.getByRole("link", { name: "최종 Go/No-Go에서 보기" })).toHaveAttribute("href", "/go-no-go");
});

test("같은 사업이 최종 결정 대기열에도 있으면 한 행으로 합치고 결정 상태를 앞에 적는다", async ({ page }) => {
  await mockDashboard(page, {
    decisions: { items: [{ ...decisionItems[0], opportunity_id: 503, review_state: "undecided" }], total: 1, limit: 200, offset: 0 },
  });
  await page.goto("/");
  await expect(agendaRows(page, "final")).toHaveCount(0);
  const row = agendaRows(page, "tracking").filter({ hasText: "행정정보 연계시스템 유지관리 공고" });
  await expect(row).toHaveCount(1);
  await expect(row.locator(".dash-agenda-status")).toContainText("Go/No-Go 미결정");
  await expect(row.locator(".dash-agenda-status")).toContainText("계속 추적");
  await expect(row.getByRole("link")).toHaveAttribute("href", "/opportunities/503");
});

test("행이 많으면 가까운 마감부터 5행만 펼치고 나머지 날은 건수와 보기 버튼만 남긴다", async ({ page }) => {
  const base = deadlineItems[0];
  const many = Array.from({ length: 12 }, (_, index) => ({
    ...structuredClone(base), id: 1000 + index,
    links: [{ ...structuredClone(base.links[0]), title: `많은 마감 사업 ${index + 1}`, deadline_at: index < 7 ? "2026-09-18T05:00:00Z" : "2026-09-20T05:00:00Z" }],
  }));
  await mockDashboard(page, { deadlines: opportunityList(many, 12), decisions: { items: [], total: 0, limit: 200, offset: 0 } });
  await page.goto("/");
  await expect(agendaRows(page)).toHaveCount(5);
  const days = agenda(page).locator(':scope > li[data-entry="day"]');
  await expect(days.nth(0).getByRole("button")).toHaveText("2건 더 보기");
  await expect(days.nth(1)).toHaveClass(/is-folded/);
  await expect(days.nth(1).getByRole("button")).toHaveText("5건 보기");
  await days.nth(1).getByRole("button", { name: "5건 보기" }).click();
  await expect(agendaRows(page)).toHaveCount(10);
  await expect(days.nth(1).getByRole("button")).toHaveText("접기");
  await days.nth(0).getByRole("button", { name: "2건 더 보기" }).click();
  await expect(agendaRows(page)).toHaveCount(12);
});

test("compactWon은 만 원 단위로 줄이고 만 원 미만은 그대로 적는다", () => {
  expect(compactWon(592_000_000)).toBe("5억 9,200만 원");
  expect(compactWon(80_069_091)).toBe("8,007만 원");
  expect(compactWon(1_264_042_120)).toBe("12억 6,404만 원");
  expect(compactWon(300_000_000)).toBe("3억 원");
  expect(compactWon(9_000)).toBe("9,000원");
});

test("받은 것보다 건수가 많으면 몇 건 중 몇 건인지 적는다", async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/");
  const more = agendaBody(page).locator('[data-source="tracking-more"]');
  await expect(more).toContainText("마감 임박 추적 건 7건 중 마감이 가까운 3건을 받았어요.");
  await expect(more.getByRole("link", { name: "사업기회에서 모두 보기" })).toHaveAttribute("href", "/opportunities?section=전체&deadline_within_days=7&sort=deadline");
});

test("한 목록이 실패해도 다른 행은 보이고 실패한 목록만 다시 조회한다", async ({ page }) => {
  const options = { decisionError: true };
  await mockDashboard(page, options);
  await page.goto("/");
  const failed = agendaBody(page).locator('[data-source="final"][role="alert"]');
  await expect(failed).toContainText("최종 결정 대기 목록을 불러오지 못했어요");
  await expect(countLink(page, "go-no-go")).toHaveText("최종 Go/No-Go 미확인");
  await expect(agendaRows(page, "tracking")).toHaveCount(3);
  await expect(agendaBody(page).locator('[data-source="tracking"][role="alert"]')).toHaveCount(0);
  options.decisionError = false;
  await failed.getByRole("button", { name: "다시 시도", exact: true }).click();
  await expect(agendaRows(page, "final")).toHaveCount(1);
  await expect(failed).toHaveCount(0);
});

test("한 목록의 로딩과 다른 목록의 결과를 구분한다", async ({ page }) => {
  await mockDashboard(page, { deadlines: opportunityList([], 0) });
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route(url => url.pathname === "/api/bid-delta/decision-queue", async route => { await pending; await route.fallback(); });
  try {
    await page.goto("/");
    await expect(agendaBody(page).locator('[data-source="final"][role="status"]')).toHaveText("최종 결정 대기 목록을 불러오는 중이에요.");
    await expect(agendaBody(page).getByText("이번 주 마감인 추적 사업이 없어요")).toHaveCount(0);
  } finally { release(); }
  await expect(agendaRows(page, "final")).toHaveCount(1);
});

test("두 목록이 모두 비면 빈 상태 하나를 표시한다", async ({ page }) => {
  await mockDashboard(page, { deadlines: opportunityList([], 0), decisions: { items: [], total: 0, limit: 5, offset: 0 } });
  await page.goto("/");
  await expect(agendaBody(page)).toContainText("이번 주 마감인 추적 사업이 없어요");
  await expect(agenda(page)).toHaveCount(0);
  await expect(countLink(page, "deadline")).toHaveText("0건");
  await expect(countLink(page, "go-no-go")).toHaveText("최종 Go/No-Go 0건");
});

test("함께 볼 것은 0건을 한 줄로 모으고 셀 수 없는 것은 숨기지 않는다", async ({ page }) => {
  await mockDashboard(page, {
    actionRequired: { ...actionRequiredList, total: 2, action_reason_counts: { ...actionRequiredList.action_reason_counts, hold_overdue: 0, blocking_item: 0 } },
    overviewAttention: preSpecList([], 2),
  });
  await page.goto("/");
  const also = page.getByRole("navigation", { name: "함께 볼 것", exact: true });
  await expect(also.locator(".dash-also-link")).toHaveText(["개요 사람 확인 2건", "사업기회 조치 필요 2건"]);
  await expect(countLink(page, "overview-attention")).toHaveAttribute("href", "/pre-specs?workspace=all&sw_only=false&overview_view=attention");
  await expect(countLink(page, "action-required")).toHaveAttribute("href", "/opportunities");
  await expect(also.locator(".dash-also-zero")).toHaveText("보류 재검토·확인 항목 미답변 0건");

  await page.unroute("**/api/**");
  await mockDashboard(page, { overviewError: true });
  await page.goto("/");
  await expect(countLink(page, "overview-attention")).toHaveText("개요 사람 확인 미확인");
  await expect(countLink(page, "hold-overdue")).toHaveText("보류 재검토 1건");
  await expect(countLink(page, "hold-overdue")).toHaveAttribute("href", "/opportunities?section=조치 필요&reason=hold_overdue");
  await expect(countLink(page, "blocking")).toHaveAttribute("href", "/opportunities?section=조치 필요&reason=blocking_item");
});

test("헤더의 수집 상태 줄은 트랙 상태를 적고 누르면 일일 수집 세부를 펼친다", async ({ page }) => {
  await mockDashboard(page);
  await page.route("**/api/daily-collection-status", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({
      schema_version: "bidops.daily-collection-status.v1", generated_at: DASH_NOW, timezone: "Asia/Seoul", today: "2026-09-17",
      tracks: [
        { track: "order-plans", basis_date: "2026-09-16", state: "complete", reasons: [], run_id: "p", collected_at: DASH_NOW, warning_count: 0, latest_basis_date: "2026-09-16" },
        { track: "notices", basis_date: "2026-09-16", state: "incomplete", reasons: ["ingest_warnings"], run_id: "n", collected_at: DASH_NOW, warning_count: 388, latest_basis_date: "2026-09-16" },
      ],
    }),
  }));
  await page.goto("/");
  const health = page.locator(".dash-health");
  await expect(health).toHaveAttribute("data-state", "warning");
  await expect(health.locator("summary")).toHaveText("09-16 기준 · 발주계획 수집 완료 · 공고 적재 확인 필요");
  await expect(page.getByTestId("daily-collection")).toBeHidden();
  await health.locator("summary").click();
  await expect(page.getByTestId("daily-collection")).toBeVisible();
  await expect(page.getByTestId("daily-collection")).toContainText("기준일 적재 경고 보기");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("daily-collection")).toBeHidden();
});

test("새로고침은 모든 조회를 다시 한다", async ({ page }) => {
  const trace = await mockDashboard(page);
  await page.goto("/");
  await expect(agendaRows(page, "tracking")).toHaveCount(3);
  const before = trace.requests.length;
  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect.poll(() => trace.requests.length).toBeGreaterThanOrEqual(before + 7);
});

test("마감 일정의 사업기회 바로가기는 같은 조건·같은 집합을 연다", async ({ page }) => {
  const trace = await mockDashboard(page);
  await page.goto("/");
  await expect(agendaRows(page, "tracking")).toHaveCount(3);
  const titles = await agendaRows(page, "tracking").locator(".dash-agenda-title").allTextContents();
  await page.locator('.dash-block[data-block="agenda"] .dash-block-actions').getByRole("link", { name: "사업기회", exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/opportunities");
  const params = new URL(page.url()).searchParams;
  expect(params.get("section")).toBe("전체");
  expect(params.get("deadline_within_days")).toBe("7");
  expect(params.get("sort")).toBe("deadline");
  await expect(page.locator(".opportunity-row-title")).toHaveText(titles);
  expect(trace.writes).toEqual([]);
});

for (const [width, height] of WIDTHS) {
  test(`한 장에 들어가고 긴 사업명에서도 폭을 넘지 않는다 ${width}`, async ({ page }, info) => {
    const long = structuredClone(deadlineItems);
    long[0].links[0].title = "공공데이터 통합관리체계 고도화 및 산하기관 데이터 품질관리·공동활용 기반 구축 사업";
    await mockDashboard(page, { deadlines: opportunityList(long, 7) });
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await expect(agendaRows(page)).toHaveCount(4);
    await settleFonts(page);
    const measured = await page.evaluate(() => {
      const rows = [...document.querySelectorAll(".dash-agenda-item")];
      return {
        overflow: document.documentElement.scrollWidth - innerWidth,
        rowOverflow: rows.map(row => row.scrollWidth - row.clientWidth),
        titleEllipsis: getComputedStyle(document.querySelector(".dash-agenda-title")!).textOverflow,
      };
    });
    expect(measured.overflow).toBe(0);
    expect(Math.max(...measured.rowOverflow)).toBeLessThanOrEqual(1);
    expect(measured.titleEllipsis).toBe("ellipsis");
    await expect(agendaRows(page).first().locator(".dash-agenda-title")).toHaveAttribute("title", /공동활용 기반 구축 사업$/);
    await page.screenshot({ path: info.outputPath(`dashboard-${width}.png`), animations: "disabled", fullPage: true });
  });
}

// 일일 수집 세부(설계고도화안 A-5)는 헤더 상태 줄 안으로 옮겼다. 아래 검사는 펼침과 무관하게 같은 요소를 본다.
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

test("한국 자정과 마감 시각을 기준으로 오늘·내일·마감 지남을 구분한다", () => {
  const deadline = new Date("2026-11-21T15:05:00Z");
  for (const [instant, expected] of [
    ["2026-11-21T14:59:59Z", "내일 마감"],
    ["2026-11-21T15:00:00Z", "오늘 00:05 마감"],
    ["2026-11-21T15:05:01Z", "마감 지남"],
  ]) {
    expect(deadlineLabel(remainingDeadlineDays(deadline, new Date(instant)), deadline)).toBe(expected);
  }
});
