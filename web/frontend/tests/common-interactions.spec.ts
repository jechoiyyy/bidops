import { expect, test, type Locator, type Page } from "@playwright/test";
import { mockApi, mockDeepReviewLifecycle, mockWorkload } from "./api-mock";
import type { BidDeltaDecisionQueueItem } from "../src/lib/types";

const opportunity = {
  id: 501,
  tracking_status: "미선택",
  tracking_reason: null,
  tracking_selected_by: null,
  tracking_selected_at: null,
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
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

const preSpecNotice = {
  id: 991,
  notice_key: "pre-spec:991",
  run_id: "fixture-run",
  title: "접근성 검증 사전규격",
  agency: "테스트 조달기관",
  published_at: "2026-08-30T00:00:00Z",
  deadline_at: "2026-09-02T00:00:00Z",
  estimated_price: null,
  sample_role: null,
  sample_stratum: null,
  collection_bucket: null,
  grade: "우선 검토",
  readiness: null,
  focus: null,
  attachment_count: 1,
  attachment_status: "g2b",
  bid_no: null,
  bid_ord: null,
  source_type: "pre_spec",
  budget: null,
  method: null,
  url: "https://example.invalid/pre-specs/991",
  timezone: "Asia/Seoul",
  procurement_class: null,
  region_limit: null,
  lifecycle: { pre_spec_no: "PRE-991" },
  qualification_flags: { sw_business_status: "Y" },
  focus_matches: [],
  performance_matches: [],
  performance_top_score: null,
  candidate_sources: [],
  judgment: null,
  attachments: [],
  reviews: [],
};

async function tabTo(page: Page, target: Locator, maximumTabs = 120): Promise<void> {
  await target.waitFor({ state: "visible" });
  for (let index = 0; index < maximumTabs; index += 1) {
    if (await target.evaluate((element) => document.activeElement === element)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error(`키보드 Tab ${maximumTabs}회 안에 대상 control에 도달하지 못했습니다.`);
}

// Native compact CSS preserves the former 90% physical control size without a
// document zoom. Focus and visible outline remain required at that density.
const APPROVED_UI_SCALE = 0.9;

async function expectKeyboardTarget(target: Locator, minimumHeight = 40): Promise<void> {
  await expect(target).toBeFocused();
  const metrics = await target.evaluate((element) => {
    const style = getComputedStyle(element);
    return { height: element.getBoundingClientRect().height, outline: style.outlineStyle };
  });
  expect(metrics.height).toBeGreaterThanOrEqual(minimumHeight * APPROVED_UI_SCALE - 0.2);
  expect(metrics.outline).not.toBe("none");
}

async function mockOpportunity(page: Page): Promise<{ patchCount: () => number }> {
  let patches = 0;
  await page.route("**/api/opportunities/501**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/opportunities/501" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(opportunity) });
      return;
    }
    if (pathname === "/api/opportunities/501/tracking-status" && request.method() === "PATCH") {
      patches += 1;
    }
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "mutation must not run" }) });
  });
  return { patchCount: () => patches };
}

async function mockPreSpecWorkbench(page: Page): Promise<{ createCount: () => number }> {
  let creates = 0;
  await page.route("**/api/notices/991**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/notices/991" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(preSpecNotice) });
      return;
    }
    if (pathname === "/api/notices/991/document-bundles" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) });
      return;
    }
    if (pathname === "/api/notices/991/document-bundles" && request.method() === "POST") creates += 1;
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "mutation must not run" }) });
  });
  return { createCount: () => creates };
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("UC-01은 키보드만으로 추적 저장 직전까지 이동하고 비활성 사유를 읽는다", async ({ page }) => {
  const trace = await mockOpportunity(page);
  await page.goto("/opportunities/501");

  const editorToggle = page.getByRole("button", { name: "추적 상태 변경", exact: true });
  await tabTo(page, editorToggle);
  // 승인된 데스크톱 ERP 시안은 이 버튼에 Astryx sm(28px)을 쓴다.
  await expectKeyboardTarget(editorToggle, 28);
  await page.keyboard.press("Enter");

  const save = page.getByRole("button", { name: "변경 사항 적용", exact: true });
  await expect(save).toBeDisabled();
  await expect(page.locator(`#${await save.getAttribute("aria-describedby")}`)).toContainText("추적 상태를 고르십시오");
  const status = page.getByRole("combobox", { name: "추적 상태", exact: true });
  await tabTo(page, status);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Home");
  await page.keyboard.press("Enter");
  await expect(status).toContainText("계속 추적");
  await expect(page.locator(`#${await save.getAttribute("aria-describedby")}`)).toContainText("선택 사유");

  const preset = page.getByRole("combobox", { name: "선택 사유", exact: true });
  await tabTo(page, preset);
  await page.keyboard.press("Enter");
  await page.keyboard.press("End");
  await page.keyboard.press("Enter");
  const reason = page.getByLabel("선택 사유 직접 입력");
  await tabTo(page, reason);
  await page.keyboard.type("새 사전규격을 계속 확인합니다.");
  const actor = page.getByLabel("결정 기록자", { exact: true });
  await tabTo(page, actor);
  await page.keyboard.type("홍길동");
  await tabTo(page, save);
  await expectKeyboardTarget(save, 28);
  await expect(save).toBeEnabled();
  expect(trace.patchCount()).toBe(0);
});

test("UC-03은 키보드만으로 draft bundle 생성 직전까지 이동한다", async ({ page }) => {
  const trace = await mockPreSpecWorkbench(page);
  await page.goto("/pre-specs/991");

  const actor = page.getByLabel("문서 준비 담당자 이름");
  const create = page.getByRole("button", { name: "새 문서 묶음 만들기" });
  await expect(create).toBeDisabled();
  await expect(page.locator(`#${await create.getAttribute("aria-describedby")}`)).toContainText("이름을 입력하십시오");
  await tabTo(page, actor);
  await expect(actor).toHaveAttribute("aria-describedby", /description/);
  await page.keyboard.type("문서 담당자");
  await tabTo(page, create);

  await expectKeyboardTarget(create);
  await expect(create).toBeEnabled();
  expect(trace.createCount()).toBe(0);
});

test("UC-04는 키보드만으로 append-only 재시작 직전까지 이동한다", async ({ page }) => {
  const trace = await mockDeepReviewLifecycle(page, "failed");
  await page.goto("/deep-reviews/fixture-review");

  const actor = page.getByLabel("담당자 이름");
  const retry = page.getByRole("button", { name: "새 분석 회차로 재시도" });
  await expect(retry).toBeDisabled();
  await expect(page.locator(`#${await retry.getAttribute("aria-describedby")}`)).toContainText("이름을 입력하십시오");
  await tabTo(page, actor);
  await page.keyboard.type("심층 검토자");
  await tabTo(page, retry);

  await expectKeyboardTarget(retry);
  await expect(retry).toBeEnabled();
  await expect(page.getByText("1회차", { exact: true })).toBeVisible();
  expect(trace.attemptPosts).toHaveLength(0);
});

test("사업 추적 상세는 변경 비교로 이동하고 추적 저장과 최종 결정 저장을 분리한다", async ({ page }) => {
  await mockOpportunity(page);
  await page.goto("/opportunities/501");
  await expect(page.locator('a[href="/opportunities/501/bid-delta"]')).toHaveCount(1);
  await expect(page.getByRole("button", { name: "최종 결정 저장" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "추적 상태 변경", exact: true })).toHaveCount(1);
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.locator(".opportunity-action-footer")).toContainText("미선택");
  await page.getByRole("tab", { name: "추적 이력", exact: true }).click();
  await expect(page.locator("#opportunity-panel-decision")).toContainText("미선택");
  await expect(page.locator("#opportunity-panel-decision")).toContainText("아직 선택하지 않았습니다");
});

// ADR-0046 결정 3으로 공고 1차 판정의 리뷰 저장이 사업 추적의 예외 작업으로
// 옮겨갔다. 공통 unsaved guard가 지켜야 할 입력도 함께 옮겨간다. 옛 자리에는
// 지킬 입력이 없고, 새 자리에는 있다.
test("공통 unsaved guard가 옮겨간 예외 작업 입력을 지킨다", async ({ page }) => {
  await mockOpportunity(page);
  await page.goto("/opportunities/501");

  await page.getByRole("button", { name: "추적 상태 변경", exact: true }).click();
  await page.getByRole("combobox", { name: "추적 상태", exact: true }).click();
  await page.getByRole("option", { name: "계속 추적", exact: true }).click();
  await page.getByRole("combobox", { name: "선택 사유", exact: true }).click();
  await page.getByRole("option", { name: "기타", exact: true }).click();
  await page.getByLabel("선택 사유 직접 입력").fill("공통 guard 회귀 검증 초안");

  const blocked = await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  });
  expect(blocked).toBe(true);
  await expect(page.getByLabel("선택 사유 직접 입력")).toHaveValue("공통 guard 회귀 검증 초안");
});

// ─────────────────────────────────────────────────────────────────────────
// docs/design/PLAN.md 단계 E 완료 게이트 (ADR-0046가 ADR-0041 결정 1·2를 개정)
// ─────────────────────────────────────────────────────────────────────────

// RL 사이드바(ui-spec §1.2, 시안 v26): 빠른 이동 / 레코드 / 리스트 / 하단.
// 화면이 없는 항목(노트·보고서·기관·새 리스트·팀원 초대·도움말)은 링크가 아니라
// 비활성 자리다.
const SIDEBAR_LINKS = [
  { group: null, label: "알림", path: "/" },
  { group: null, label: "다음 행동", path: "/opportunities" },
  { group: "레코드", label: "공고", path: "/pre-specs" },
  { group: "레코드", label: "사업기회", path: "/opportunities" },
  { group: "레코드", label: "회사 근거", path: "/profile" },
  { group: "리스트", label: "오늘의 브리핑", path: "/briefing" },
  { group: "리스트", label: "추적 중", path: "/opportunities" },
  { group: "리스트", label: "연차 예고", path: "/order-plans" },
  { group: "리스트", label: "마감 임박", path: "/opportunities" },
];
const SIDEBAR_DISABLED = ["노트", "보고서", "기관", "새 리스트", "팀원 초대", "도움말"];

test("사이드바는 시안 v26 구조(빠른 이동·레코드·리스트·하단)이고 미구현 항목은 비활성이다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const sidebar = page.locator("aside.sidebar");
  await expect(sidebar.locator(".sidebar-group-label")).toHaveText(["레코드", "리스트"]);
  for (const item of SIDEBAR_LINKS) {
    await expect(sidebar.getByRole("link", { name: item.label, exact: true })).toHaveCount(1);
  }
  for (const label of SIDEBAR_DISABLED) {
    const entry = sidebar.locator(".sidebar-item.is-disabled", { hasText: label });
    await expect(entry).toHaveCount(1);
    await expect(entry).toHaveAttribute("aria-disabled", "true");
    await expect(sidebar.getByRole("link", { name: label, exact: true })).toHaveCount(0);
  }
  // 하단: 설정이 운영 메뉴(판정 기준·실행 상태)로 가는 유일한 진입이다.
  await expect(sidebar.locator(".sidebar-footer").getByRole("link", { name: "설정", exact: true })).toHaveAttribute("href", "/criteria");
  await expect(sidebar.locator(".sidebar-external-link")).toHaveCount(1);
  // 옛 1차 분류와 "준비 중" 안내는 없다.
  await expect(sidebar.getByText("준비 중")).toHaveCount(0);
  await expect(sidebar.getByText("탐색과 추적")).toHaveCount(0);
});

test("사이드바 링크가 모두 실제 화면으로 연결되고 설정이 판정 기준을 연다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const item of SIDEBAR_LINKS) {
    await page.goto("/");
    await page.locator("aside.sidebar").getByRole("link", { name: item.label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`^[^?]*${item.path.replace(/\//g, "\\/")}(\\?|$)`));
    // 실제 화면이 그려진다: 빈 라우트나 오류 경계가 아니라 상단바 제목이 채워진다.
    await expect(page.locator("header.topbar h1")).not.toHaveText("BidOps Admin");
    await expect(page.locator(".lazy-route-error")).toHaveCount(0);
  }

  await page.goto("/");
  await page.locator("aside.sidebar").getByRole("link", { name: "설정", exact: true }).click();
  await expect(page.locator("header.topbar h1")).toHaveText("판정 기준");
});

// 승인된 대시보드는 누적 업무 4곳을 회차 자료 위에 고정한다.
const DECISION_STRIP_TARGETS = [
  { title: /발주계획/, pathname: "/order-plans" },
  { title: /사전규격/, pathname: "/pre-specs" },
  { title: /사업 추적/, pathname: "/opportunities" },
  { title: /최종 Go\/No-Go/, pathname: "/go-no-go" },
];

test("대시보드 바로가기에서 네 업무 각각으로 이동할 수 있다(회차 선택 상태)", async ({ page }) => {
  await mockApi(page);
  for (const target of DECISION_STRIP_TARGETS) {
    await page.goto("/?run=20260817-20260823--20260824T090927.138116Z");
    const strip = page.getByRole("navigation", { name: "업무 바로가기 · 회차와 무관한 누적 업무" });
    await expect(strip.getByRole("link")).toHaveCount(4);
    await strip.getByRole("link", { name: target.title }).click();
    await expect.poll(() => new URL(page.url()).pathname).toMatch(new RegExp(`^${target.pathname}`));
    expect(new URL(page.url()).searchParams.has("run")).toBe(false);
  }
});

test("사전규격 결정 대기 건수를 서버 집계로 보여 주고 마감 순으로 이동한다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  const item = page.locator(".dash-journey-strip").getByRole("link", { name: /사전규격/ });
  await expect(item).toContainText("결정 대기 1건");
  await item.click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs");
  expect(new URL(page.url()).searchParams.get("sort")).toBe("deadline");
});

test("Go/No-Go 결정 대기 건수를 서버 집계로 보여 주고 이동을 제공한다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  const item = page.locator(".dash-journey-strip").getByRole("link", { name: /최종 Go\/No-Go/ });
  await expect(item).toContainText("결정 대기 2건");
  await expect(item).toHaveAttribute("href", "/go-no-go");
});

test("회차가 없어도 누적 업무와 공고 판정 이력으로 이동할 수 있다", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/runs", route => route.fulfill({ json: { items: [] } }));
  await page.goto("/");
  const strip = page.locator(".dash-journey-strip");
  for (const target of DECISION_STRIP_TARGETS) await expect(strip.getByRole("link", { name: target.title })).toBeVisible();
});

test("누적 집계 미확인을 0으로 접지 않는다", async ({ page }) => {
  await mockApi(page);
  // 서버가 건수를 낼 수 없다고 답한 세 칸은 0으로 접히지 않고 미확인으로 남아야 한다.
  await mockWorkload(page, { generated_at: "2026-09-01T09:00:00Z", items: [
    { key: "order_plan_pending", count: 24, unavailable_reason: null },
    { key: "pre_spec_deep_review_ready", count: null, unavailable_reason: "provider_absent" },
    { key: "tracking_action_required", count: null, unavailable_reason: "provider_absent" },
    { key: "tracking_hold_review_due", count: 2, unavailable_reason: null },
    { key: "bid_final_decision_pending", count: null, unavailable_reason: null },
    { key: "tracking_deadline_imminent", count: 4, unavailable_reason: null },
    { key: "human_check_required", count: null, unavailable_reason: "sub_count_unavailable" },
    { key: "overview_human_review", count: null, unavailable_reason: null },
    { key: "blocking_items_open", count: 3, unavailable_reason: null },
    { key: "order_plan_new_priority", count: 6, unavailable_reason: null },
  ] });
  await page.goto("/");
  const unmeasured = page.locator(".dash-journey-item").filter({ hasText: "미확인" });
  await expect(unmeasured).toHaveCount(3);
  for (const item of await unmeasured.all()) await expect(item).not.toContainText("0건");
});

test("판정 기준은 모든 탭에 별도 판단과 소급 변경의 경계를 남긴다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const path of ["/criteria", "/profile", "/policies", "/quality-gates", "/metrics"]) {
    await page.goto(path);
    // 승인 ERP 시안은 큰 경계 패널을 각주와 관련 조작 옆의 안내로 옮긴다.
    // 별도 판단이라는 사실은 어느 탭에서도 읽혀야 한다.
    const boundary = page.locator(".crit-boundary");
    await expect(boundary).toBeVisible();
    await expect(boundary).toContainText("적합성 등급");
    await expect(boundary).toContainText("참여 준비");
    await expect(boundary).toContainText("추적");
    await expect(boundary).toContainText("Go/No-Go");
    await expect(boundary).toContainText(/이후|소급/);
    await expect(page.locator(".crit-summary")).toContainText("판정 정책");
  }
});

test("실행 상태는 모든 탭에서 운영 텔레메트리 위치와 상시 운영 차단 사유를 확인할 수 있다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const path of ["/run-status", "/runs", "/attachments", "/operations", "/audit"]) {
    await page.goto(path);
    const boundary = page.locator(".rs-boundary");
    await expect(boundary).toBeVisible();
    await expect(boundary).toContainText("진행 상태와 품질 표식은 별도");
    await expect(boundary).toContainText("미확인·미측정");
    await page.getByRole("button", { name: "운영 조건", exact: true }).click();
    const conditions = page.getByRole("dialog", { name: "운영 조건과 경계" });
    await expect(conditions).toBeVisible();
    // 판정 화면에서 뺐지만 삭제하지 않았다(ADR-0041 결정 5).
    await expect(conditions).toContainText("삭제하지 않았습니다");
    await expect(conditions).toContainText("model_digest");
    await expect(conditions).toContainText("duration_ms");
    await expect(conditions).toContainText("거절 사유");
    await expect(conditions).toContainText("승인 조합");
    await expect(conditions).toContainText("startup은 migration·seed·정책 활성화·모델 호출을 수행하지 않습니다");
    await conditions.getByRole("button", { name: "확인", exact: true }).click();
  }
});

/** 결정 대기열 한 행. 목록의 사업 이름·비교 건수·사람 결정은 이 응답이 준 값이다. */
function queueItem(overrides: Partial<BidDeltaDecisionQueueItem> = {}): BidDeltaDecisionQueueItem {
  return {
    opportunity_id: 501,
    title: "접근성 검증 입찰공고",
    agency: "테스트 조달기관",
    tracking_status: "계속 추적",
    first_registered_stage: "order_plan",
    recheck_signal: false,
    bid_notice_external_id: "R26BK00267196",
    comparison_count: 0,
    latest_final_decision: null,
    decision_currentness: "unknown",
    ...overrides,
  };
}

/** 비교가 하나도 없는 workspace. 선택한 사업 하나의 상세에만 쓰인다. */
function emptyWorkspace(opportunityId: number) {
  return {
    schema_version: "bidops.bid-delta-workspace.v1",
    opportunity_id: opportunityId,
    baseline_candidates: [],
    comparison_candidates: [],
    comparisons: [],
    latest_final_decision: null,
    final_decisions: [],
    decision_currentness: "unknown",
    currentness_reasons: [],
  };
}

interface GoNoGoRequestTrace {
  queueQueries: Array<Record<string, string>>;
  opportunityListRequests: number;
  workspaceIds: number[];
}

/** 대기열·workspace를 고정하고 목록이 실제로 보낸 요청을 센다. `mockApi` 뒤에 부른다. */
async function mockDecisionQueueList(page: Page, items: BidDeltaDecisionQueueItem[]): Promise<GoNoGoRequestTrace> {
  const trace: GoNoGoRequestTrace = { queueQueries: [], opportunityListRequests: 0, workspaceIds: [] };
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/bid-delta/decision-queue") trace.queueQueries.push(Object.fromEntries(url.searchParams.entries()));
    if (url.pathname === "/api/opportunities") trace.opportunityListRequests += 1;
    const workspace = /^\/api\/opportunities\/(\d+)\/bid-delta$/.exec(url.pathname);
    if (workspace) trace.workspaceIds.push(Number(workspace[1]));
  });
  await page.route("**/api/bid-delta/decision-queue**", async (route) => {
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get("limit") ?? "50");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: items.slice(offset, offset + limit), total: items.length, limit, offset }),
    });
  });
  await page.route(/\/api\/opportunities\/\d+\/bid-delta$/, async (route) => {
    const id = Number(/\/api\/opportunities\/(\d+)\/bid-delta$/.exec(new URL(route.request().url()).pathname)?.[1] ?? 0);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(emptyWorkspace(id)) });
  });
  return trace;
}

test("최종 Go/No-Go 목록은 사업 이름과 변경 비교 결과 없음을 값으로 보여준다", async ({ page }) => {
  await mockApi(page);
  const trace = await mockDecisionQueueList(page, [queueItem()]);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/go-no-go?show=all");

  const rows = page.locator(".gng-row");
  await expect(rows).toHaveCount(1);
  // 식별자만 있는 행은 무슨 사업인지 알 수 없어 결국 하나씩 열어 봐야 한다.
  await expect(rows.nth(0)).toContainText("접근성 검증 입찰공고");
  await expect(rows.nth(0)).toContainText("테스트 조달기관");
  // 비교 0건은 값이다. `비교 0건`으로 눌러 담아 "아직 안 봤다"와 섞지 않는다.
  await expect(rows.nth(0)).toContainText("변경 비교 결과 없음");
  // 선택한 사업의 상세가 그려진 뒤에 요청을 센다.
  await expect(page.getByRole("heading", { name: "변경 비교 결과가 아직 없습니다" })).toBeVisible();
  // 대기열을 한 번에 다 받았으므로 요약은 전체 기준이라고 말한다.
  await expect(page.locator(".gng-summary")).toHaveText("전체 1건 기준 · 1건 표시");
  expect(trace.queueQueries).toHaveLength(1);
  expect(trace.queueQueries[0]).toMatchObject({ status: "all", offset: "0" });
  expect(trace.opportunityListRequests).toBe(0);
});

// 결정 대기 목록은 서버의 결정 대기열 한 번으로 그린다(spec §11.3). 행마다 workspace를
// 조회하던 N+1을 되살리지 않는다 — 상세는 선택한 사업 하나만 받는다.
test("최종 Go/No-Go 목록은 결정 대기열 한 번으로 그리고 행마다 workspace를 조회하지 않는다", async ({ page }) => {
  await mockApi(page);
  const many = Array.from({ length: 30 }, (_, index) => queueItem({
    opportunity_id: 600 + index,
    title: `결정 대기 사업 ${index + 1}`,
    bid_notice_external_id: `BID-${600 + index}`,
  }));
  const trace = await mockDecisionQueueList(page, many);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/go-no-go?show=all");

  await expect(page.locator(".gng-row")).toHaveCount(30);
  await expect(page.getByRole("heading", { name: "변경 비교 결과가 아직 없습니다" })).toBeVisible();
  expect(trace.queueQueries).toHaveLength(1);
  expect(trace.queueQueries[0]).toMatchObject({ status: "all", limit: "500", offset: "0" });
  expect(trace.opportunityListRequests).toBe(0);
  // 첫 행이 선택되고 그 사업 하나만 상세를 받는다.
  expect([...new Set(trace.workspaceIds)]).toEqual([600]);
  await expect(page.locator(".gng-summary")).toHaveText("전체 30건 기준 · 30건 표시");
  // 공용 페이저는 한 쪽뿐이어도 항상 보이고 단추만 비활성이다(U3, 명세 §2.2).
  const pager = page.getByRole("navigation", { name: "결정 대기열 페이지" });
  await expect(pager).toBeVisible();
  await expect(pager).toContainText("1–30 / 30");
  await expect(pager.getByRole("button", { name: "이전" })).toBeDisabled();
  await expect(pager.getByRole("button", { name: "다음" })).toBeDisabled();

  // 다른 행을 골라도 대기열은 다시 받지 않고 그 행 하나만 조회한다.
  await page.locator(".gng-row").filter({ hasText: "결정 대기 사업 12" }).click();
  await expect.poll(() => [...new Set(trace.workspaceIds)].sort()).toEqual([600, 611]);
  expect(trace.queueQueries).toHaveLength(1);
});

// 저장 알림은 읽는 동안 사라지면 안 된다. 자동 소멸 시간을 늘리고, hover·focus
// 중에는 시간을 세지 않는다.
test("저장 알림은 hover 중에 사라지지 않고 명시적으로 닫을 수 있다", async ({ page }) => {
  const trace = await mockDeepReviewLifecycle(page, "failed");
  await page.goto("/deep-reviews/fixture-review");

  await page.getByLabel("담당자 이름").fill("알림 담당자");
  await page.getByRole("button", { name: "새 분석 회차로 재시도" }).click();

  const toast = page.locator(".toast");
  await expect(toast).toBeVisible();
  await toast.hover();
  await expect(toast).toHaveAttribute("data-toast-held", "true");
  // 옛 자동 소멸 시간(6초)을 넘겨도 hover 중에는 남아 있다.
  await page.waitForTimeout(7_000);
  await expect(toast).toBeVisible();

  await toast.getByRole("button", { name: "알림 닫기" }).click();
  await expect(page.locator(".toast")).toHaveCount(0);
  expect(trace.attemptPosts).toHaveLength(1);
});

// 되돌릴 수 없는 결정의 확인 단계는 키보드만으로도 취소할 수 있어야 한다.
// 열릴 때 초점은 취소에 있고 Esc는 취소이며, 확인 전에는 요청이 나가지 않는다.
test("UC-05 추적 종료 확인 단계는 취소에 초점이 오고 Esc로 요청 없이 닫힌다", async ({ page }) => {
  const trace = await mockOpportunity(page);
  await page.goto("/opportunities/501");

  await page.getByRole("button", { name: "추적 상태 변경", exact: true }).click();
  await page.getByRole("combobox", { name: "추적 상태", exact: true }).click();
  await page.getByRole("option", { name: "종료 · 추적 종료", exact: true }).click();
  await page.getByRole("combobox", { name: "선택 사유", exact: true }).click();
  await page.getByRole("option", { name: "기타", exact: true }).click();
  await page.getByLabel("선택 사유 직접 입력").fill("현재 범위와 맞지 않아 능동 추적을 종료합니다.");
  await page.getByLabel("결정 기록자", { exact: true }).fill("홍길동");

  const save = page.getByRole("button", { name: "추적 종료로 변경", exact: true });
  await expect(save).toBeEnabled();
  await tabTo(page, save);
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  const cancel = dialog.getByRole("button", { name: "취소", exact: true });
  await expectKeyboardTarget(cancel);
  expect(trace.patchCount()).toBe(0);

  await page.keyboard.press("Escape");
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(trace.patchCount()).toBe(0);
  await expect(page.getByLabel("선택 사유 직접 입력")).toHaveValue("현재 범위와 맞지 않아 능동 추적을 종료합니다.");
});
