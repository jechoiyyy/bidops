import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";

type OpportunityFixture = Record<string, unknown> & { id: number };

const baseLink = {
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
};

const unselected: OpportunityFixture = {
  id: 101,
  tracking_status: "미선택",
  tracking_reason: null,
  tracking_selected_by: null,
  tracking_selected_at: null,
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [{
    ...baseLink,
    id: 1001,
    stage: "order_plan",
    link_type: "official",
    status: "확정",
    record_type: "order_plan",
    record_id: 51,
    notice_id: null,
    order_plan_id: 51,
    source_type: null,
    title: "미선택 공공 데이터 플랫폼 구축",
    agency: "테스트 기관",
    external_id: "PLAN-101",
    record_external_id: "PLAN-101",
  }],
};

const endedWithRecheck: OpportunityFixture = {
  id: 202,
  tracking_status: "종료",
  tracking_reason: "현재 범위와 맞지 않아 능동 추적을 종료함",
  tracking_selected_by: "기존 담당자",
  tracking_selected_at: "2026-08-20T09:00:00Z",
  recheck_signal: true,
  recheck_signal_at: "2026-08-31T01:30:00Z",
  recheck_signal_link_id: 2002,
  first_registered_stage: "pre_spec",
  links: [{
    ...baseLink,
    id: 2001,
    stage: "notice",
    link_type: "official",
    status: "확정",
    record_type: "pre_spec",
    record_id: 61,
    notice_id: 61,
    order_plan_id: null,
    source_type: "pre_spec",
    title: "종료된 지능형 업무 시스템 사전규격",
    agency: "테스트 기관",
    external_id: "PRE-202",
    record_external_id: "PRE-202",
  }, {
    ...baseLink,
    id: 2002,
    stage: "notice",
    link_type: "official",
    status: "확정",
    record_type: "bid_notice",
    record_id: 62,
    notice_id: 62,
    order_plan_id: null,
    source_type: "bid_notice",
    title: "종료된 지능형 업무 시스템 본공고",
    agency: "테스트 기관",
    external_id: "BID-202",
    record_external_id: "BID-202",
  }],
};

const candidateRelation: OpportunityFixture = {
  id: 303,
  tracking_status: "계속 추적",
  tracking_reason: "후보 관계를 사람이 확인할 때까지 계속 추적",
  tracking_selected_by: "검토 담당자",
  tracking_selected_at: "2026-08-29T02:00:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [{
    ...baseLink,
    id: 3001,
    stage: "notice",
    link_type: "candidate",
    status: "후보 확인 대기",
    search_strategy: "normalized",
    attempted_strategies: ["full", "normalized"],
    agency_match: true,
    last_searched_at: "2026-08-30T03:00:00Z",
    record_type: "pre_spec",
    record_id: 71,
    notice_id: 71,
    order_plan_id: null,
    source_type: "pre_spec",
    title: "후보 관계 사전규격",
    agency: "후보 기관",
    external_id: "PRE-303",
    record_external_id: "PRE-303",
  }],
};

interface OpportunityTrace {
  listQueries: URLSearchParams[];
  detailGets: number[];
  patches: Array<{ id: number; body: Record<string, unknown>; headers: Record<string, string> }>;
}

async function mockOpportunities(page: Page): Promise<OpportunityTrace> {
  const trace: OpportunityTrace = { listQueries: [], detailGets: [], patches: [] };
  const details = new Map<number, OpportunityFixture>([
    [unselected.id, structuredClone(unselected)],
    [endedWithRecheck.id, structuredClone(endedWithRecheck)],
    [candidateRelation.id, structuredClone(candidateRelation)],
  ]);

  await page.route("**/api/opportunities**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const match = url.pathname.match(/^\/api\/opportunities\/(\d+)$/);

    if (url.pathname === "/api/opportunities" && request.method() === "GET") {
      trace.listQueries.push(new URLSearchParams(url.search));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [...details.values()], total: 53, limit: 50, offset: Number(url.searchParams.get("offset") ?? 0) }),
      });
      return;
    }

    if (match && request.method() === "GET") {
      const id = Number(match[1]);
      trace.detailGets.push(id);
      const detail = details.get(id);
      await route.fulfill({
        status: detail ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(detail ?? { error: { code: "opportunity_not_found", message: "사업기회를 찾을 수 없습니다", details: null }, request_id: null }),
      });
      return;
    }

    const trackingMatch = url.pathname.match(/^\/api\/opportunities\/(\d+)\/tracking-status$/);
    if (trackingMatch && request.method() === "PATCH") {
      const id = Number(trackingMatch[1]);
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.patches.push({ id, body, headers: request.headers() });
      const current = details.get(id)!;
      const saved = {
        ...current,
        tracking_status: body.tracking_status,
        tracking_reason: body.reason,
        tracking_selected_by: "홍길동",
        tracking_selected_at: "2026-08-31T04:00:00Z",
      };
      details.set(id, saved);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(saved) });
      return;
    }

    await route.fallback();
  });

  return trace;
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("목록 선택, 상세 새로고침, 뒤로 가기가 filter/sort/offset URL을 복원한다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  const query = "tracking_status=종료&first_registered_stage=pre_spec&sort=tracking_status&offset=50";
  await page.goto(`/opportunities?${query}`);

  const row = page.getByRole("heading", { name: "종료된 지능형 업무 시스템 사전규격" }).locator("..");
  await row.getByRole("link", { name: "자세히 보기" }).click();
  await expect(page.getByRole("heading", { name: "사업기회 상세 #202" })).toBeVisible();
  const detailUrl = new URL(page.url());
  expect(detailUrl.pathname).toBe("/opportunities/202");
  expect(Object.fromEntries(detailUrl.searchParams)).toEqual({
    tracking_status: "종료",
    first_registered_stage: "pre_spec",
    sort: "tracking_status",
    offset: "50",
  });
  expect(trace.detailGets).toEqual([202]);

  await page.reload();
  await expect(page.getByRole("heading", { name: "사업기회 상세 #202" })).toBeVisible();
  expect(trace.detailGets).toEqual([202, 202]);

  await page.goBack();
  await expect(page.getByRole("heading", { level: 2, name: "사업기회" })).toBeVisible();
  const listUrl = new URL(page.url());
  expect(listUrl.pathname).toBe("/opportunities");
  expect(Object.fromEntries(listUrl.searchParams)).toEqual({
    tracking_status: "종료",
    first_registered_stage: "pre_spec",
    sort: "tracking_status",
    offset: "50",
  });
  const filters = page.locator(".opportunities-filters select");
  await expect(filters.nth(0)).toHaveValue("종료");
  await expect(filters.nth(1)).toHaveValue("pre_spec");
  await expect(filters.nth(2)).toHaveValue("tracking_status");
  expect(trace.listQueries.some((params) => params.get("offset") === "50" && params.get("sort") === "tracking_status")).toBe(true);
});

test("미선택 상세는 사람 판정과 재검토 신호 없음 상태를 각각 표시한다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/101?sort=created_at");

  await expect(page.locator(".opportunity-human-decision")).toContainText("미선택");
  await expect(page.locator(".opportunity-human-decision")).toContainText("기록된 이유 없음");
  await expect(page.locator(".opportunity-signal")).toContainText("현재 재검토 신호가 없습니다.");
  expect(trace.detailGets).toEqual([101]);
  expect(trace.listQueries).toHaveLength(0);
});

test("종료 상태와 재검토 필요 신호를 서로 다른 영역에 보존한다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/202");

  const signal = page.locator(".opportunity-signal");
  const decision = page.locator(".opportunity-human-decision");
  await expect(signal).toContainText("재검토 필요");
  await expect(signal).toContainText("BID-202");
  await expect(decision).toContainText("종료");
  await expect(decision).toContainText("현재 범위와 맞지 않아 능동 추적을 종료함");
  await expect(decision).not.toContainText("재검토 필요");
});

test("candidate relation fixture를 확정 관계로 바꾸지 않고 표시한다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/303");

  const relation = page.locator(".opportunity-link");
  await expect(relation).toContainText("후보");
  await expect(relation).toContainText("후보 확인 대기");
  await expect(relation).toContainText("공식 번호가 아닌 후보 관계다. 사람 확인이 필요하다.");
  await expect(relation).not.toContainText("공식 통합번호로 확정된 관계다.");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("추적 form은 접기와 route 이탈을 보호하고 기존 mutation 계약을 유지한다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/101?sort=created_at");
  await page.getByRole("button", { name: "사람 추적 상태 변경" }).click();
  await page.locator(".opportunity-tracking-form select").selectOption("계속 추적");
  await page.getByLabel("이유").fill("새 사전규격 공개 여부를 계속 확인");
  await page.getByLabel("담당자 이름").fill("홍길동");
  await expect(page.getByText("저장되지 않은 추적 상태 변경이 있습니다.")).toBeVisible();
  expect(await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  })).toBe(true);

  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "사람 추적 상태 변경" }).click();
  await expect(page.getByLabel("이유")).toHaveValue("새 사전규격 공개 여부를 계속 확인");

  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("link", { name: "사업기회 목록" }).click();
  await expect(page).toHaveURL(/\/opportunities\/101\?sort=created_at$/);

  await page.getByRole("button", { name: "추적 상태 저장" }).click();
  await expect(page.getByText("추적 상태를 저장했습니다.")).toBeVisible();
  expect(trace.patches).toHaveLength(1);
  expect(trace.patches[0].body).toEqual({ tracking_status: "계속 추적", reason: "새 사전규격 공개 여부를 계속 확인" });
  expect(trace.patches[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  expect(trace.patches[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
});
