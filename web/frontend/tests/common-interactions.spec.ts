import { expect, test, type Locator, type Page } from "@playwright/test";
import { mockApi, mockWorkload } from "./api-mock";
import { bidConditionsFixture } from "./go-no-go-fixtures";
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
  throw new Error(`키보드 Tab ${maximumTabs}회 안에 대상 control에 도달하지 못했어요.`);
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

/**
 * 목록 우측 pane에서 사업기회 501을 연다(RL-02 T7). `/opportunities/501`은 이제 사업기회 레코드
 * (`/opportunities/501/activity`)이고, 추적 상태 변경·되돌리기 대화상자와 변경 비교 진입은 목록 pane의
 * 빠른 조작 화면이 그대로 갖는다. `selected`는 받은 목록 안의 id만 유효하므로 전체 구역으로 연다.
 */
async function openOpportunityDetail(page: Page): Promise<void> {
  await page.goto(`/opportunities?section=${encodeURIComponent("전체")}&selected=501`);
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
  await openOpportunityDetail(page);

  const editorToggle = page.getByRole("button", { name: "추적 여부 선택", exact: true });
  await tabTo(page, editorToggle);
  // 승인된 데스크톱 ERP 시안은 이 버튼에 Astryx sm(28px)을 쓴다.
  await expectKeyboardTarget(editorToggle, 28);
  await page.keyboard.press("Enter");

  // C-7: 결정 버튼이 곧 고르는 상태다. 아직 아무도 고르지 않은 건이라 `계속 추적`은 `추적 시작`이다.
  const save = page.getByRole("dialog").getByRole("button", { name: "추적 시작하기", exact: true });
  await expect(save).toBeDisabled();
  await expect(page.locator(`#${await save.getAttribute("aria-describedby")}`)).toContainText("선택 사유");

  const preset = page.getByRole("combobox", { name: "선택 사유", exact: true });
  await tabTo(page, preset);
  await page.keyboard.press("Enter");
  await page.keyboard.press("End");
  await page.keyboard.press("Enter");
  const reason = page.getByLabel("선택 사유 직접 입력");
  await tabTo(page, reason);
  await page.keyboard.type("새 사전규격을 계속 확인해요.");
  const actor = page.getByLabel("담당자 이름 (필수)", { exact: true });
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
  await expect(page.locator(`#${await create.getAttribute("aria-describedby")}`)).toContainText("이름을 입력해 주세요");
  await tabTo(page, actor);
  await expect(actor).toHaveAttribute("aria-describedby", /description/);
  await page.keyboard.type("문서 담당자");
  await tabTo(page, create);

  await expectKeyboardTarget(create);
  await expect(create).toBeEnabled();
  expect(trace.createCount()).toBe(0);
});

test("사업 추적 상세는 변경 비교로 이동하고 추적 저장과 최종 결정 저장을 분리한다", async ({ page }) => {
  await mockOpportunity(page);
  await openOpportunityDetail(page);
  // 목록 pane에서는 변경 비교 링크가 목록 문맥(`returnSearch`)을 함께 싣는다.
  await expect(page.locator('a[href^="/opportunities/501/bid-delta"]')).toHaveCount(1);
  await expect(page.locator('a[href^="/opportunities/501/bid-delta"]')).toHaveAttribute(
    "href",
    `/opportunities/501/bid-delta?section=${encodeURIComponent("전체")}&selected=501`,
  );
  await expect(page.getByRole("button", { name: "최종 결정 저장" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "추적 여부 선택", exact: true })).toHaveCount(1);
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.getByRole("group", { name: "결정 영역", exact: true })).toContainText("미선택");
  await page.getByRole("tab", { name: "추적 이력", exact: true }).click();
  await expect(page.locator("#opportunity-panel-decision")).toContainText("미선택");
  await expect(page.locator("#opportunity-panel-decision")).toContainText("아직 선택하지 않았어요");
});

// ADR-0046 결정 3으로 공고 1차 판정의 리뷰 저장이 사업 추적의 예외 작업으로
// 옮겨갔다. 공통 unsaved guard가 지켜야 할 입력도 함께 옮겨간다. 옛 자리에는
// 지킬 입력이 없고, 새 자리에는 있다.
test("공통 unsaved guard가 옮겨간 예외 작업 입력을 지킨다", async ({ page }) => {
  await mockOpportunity(page);
  await openOpportunityDetail(page);

  await page.getByRole("button", { name: "추적 여부 선택", exact: true }).click();
  await page.getByRole("combobox", { name: "선택 사유", exact: true }).click();
  await page.getByRole("option", { name: "기타 · 직접 입력", exact: true }).click();
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

const SIDEBAR_LINKS = [
  { label: "오늘 할 일", path: "/", title: "오늘 할 일" },
  { label: "발주계획", path: "/order-plans", title: "발주계획" },
  { label: "사전규격", path: "/pre-specs", title: "사전규격" },
  { label: "사업기회", path: "/opportunities", title: "사업기회" },
  { label: "최종 Go/No-Go", path: "/go-no-go", title: "최종 Go/No-Go" },
  { label: "회사 근거", path: "/company", title: "회사 근거" },
  { label: "판정 기준", path: "/criteria", title: "판정 기준" },
  { label: "실행 상태", path: "/run-status", title: "실행 상태" },
];
const SIDEBAR_REMOVED = ["오늘의 브리핑", "추적 중", "마감 임박", "알림", "다음 행동", "공고", "연차 예고", "노트", "보고서", "기관", "새 리스트", "팀원 초대", "도움말", "설정", "검색"];

test("사이드바는 탐색과 관리 메뉴를 묶고 사업기회 보기는 목록에 둔다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const sidebar = page.locator("aside.sidebar");
  await expect(sidebar.locator(".sidebar-group-label")).toHaveText(["탐색", "관리"]);
  for (const item of SIDEBAR_LINKS) {
    await expect(sidebar.getByRole("link", { name: item.label, exact: true })).toHaveCount(1);
  }
  for (const label of SIDEBAR_REMOVED) {
    await expect(sidebar.getByText(label, { exact: true })).toHaveCount(0);
  }
  await expect(sidebar.locator('[aria-disabled="true"]')).toHaveCount(0);
  await expect(sidebar.locator(".sidebar-group").filter({ has: page.getByText("관리", { exact: true }) }).locator(".sidebar-item-label")).toHaveText(["회사 근거", "판정 기준", "실행 상태"]);
  await expect(sidebar.locator(".sidebar-external-link")).toHaveCount(1);
  await expect(sidebar.getByText("준비 중")).toHaveCount(0);
  await expect(sidebar.getByText("탐색과 추적")).toHaveCount(0);
});

test("사이드바 항목 이름은 여는 화면의 제목과 같다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const item of SIDEBAR_LINKS) {
    await page.goto("/");
    await page.locator("aside.sidebar").getByRole("link", { name: item.label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`^[^?]*${item.path.replace(/\//g, "\\/")}(\\?|$)`));
    // 2026-11-19 패널 헤더(ADR-0076): 화면 이름은 제목 위 작은 글자(eyebrow)이고 `<h1>`은 문장형 제목이다.
    // 문장을 올리지 않는 화면(읽기 전·실패)은 `<h1>`이 화면 이름 그대로다. 어느 쪽이든 화면 이름은 사이드바와 같다.
    await expect(page.locator("header.topbar h1")).toBeVisible();
    await expect.poll(() => page.locator("header.topbar").evaluate((topbar) => {
      const eyebrow = topbar.querySelector('[data-testid="page-header-eyebrow"]')?.textContent?.trim();
      return eyebrow ? eyebrow.split(" · ")[0] : topbar.querySelector("h1")?.textContent?.trim() ?? "";
    })).toBe(item.title);
    await expect(page.locator(".lazy-route-error")).toHaveCount(0);
  }
});

// 주소 하나에 활성 항목은 정확히 하나다(2026-11-18: `/opportunities`가 다음 행동, `/go-no-go`가
// 사업기회, `/judgments`가 두 항목을 켜던 결함).
const ACTIVE_CASES = [
  { path: "/", active: "오늘 할 일" },
  { path: "/order-plans", active: "발주계획" },
  { path: "/pre-specs", active: "사전규격" },
  { path: "/pre-specs/991", active: "사전규격" },
  { path: "/opportunities", active: "사업기회" },
  { path: "/opportunities?section=전체", active: "사업기회" },
  { path: "/opportunities?section=추적 중", active: "사업기회" },
  { path: "/opportunities?section=전체&deadline_within_days=7&sort=deadline", active: "사업기회" },
  { path: "/opportunities/501/activity", active: "사업기회" },
  { path: "/go-no-go", active: "최종 Go/No-Go" },
  { path: "/judgments", active: "사업기회" },
  { path: "/queue", active: "사업기회" },
  { path: "/company", active: "회사 근거" },
  { path: "/briefing", active: "오늘 할 일" },
  { path: "/run-status", active: "실행 상태" },
  { path: "/runs", active: "실행 상태" },
  { path: "/criteria", active: "판정 기준" },
  { path: "/order-plan-policies", active: "판정 기준" },
];

test("주소마다 활성 사이드바 항목은 정확히 하나다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const item of ACTIVE_CASES) {
    await page.goto(item.path);
    const active = page.locator('aside.sidebar [aria-current="page"]');
    await expect(active, item.path).toHaveCount(1);
    await expect(active, item.path).toHaveText(new RegExp(`^${item.active.replace("/", "\\/")}\\d*$`));
  }
});

// 오늘 할 일(2026-11-27 시안 C2): 요약 줄과 함께 볼 것의 건수 링크(`data-count`)가 각 업무 목록으로 가는 길이다.
// 발주계획·사전규격 기본 보기 건수는 사이드바가 보여 주므로 화면에 다시 두지 않는다.
const DECISION_STRIP_TARGETS = [
  { key: "deadline", pathname: "/opportunities" },
  { key: "pre-spec-needs-check", pathname: "/pre-specs" },
  { key: "new-order-plan", pathname: "/order-plans" },
  { key: "go-no-go", pathname: "/go-no-go" },
];
const countLink = (page: Page, key: string) => page.locator(`.dash-page a[data-count="${key}"]`);

test("대시보드 건수 링크에서 네 업무 각각으로 이동할 수 있다(회차 선택 상태)", async ({ page }) => {
  await mockApi(page);
  for (const target of DECISION_STRIP_TARGETS) {
    await page.goto("/?run=20260817-20260823--20260824T090927.138116Z");
    await countLink(page, target.key).click();
    await expect.poll(() => new URL(page.url()).pathname).toMatch(new RegExp(`^${target.pathname}`));
    expect(new URL(page.url()).searchParams.has("run")).toBe(false);
  }
});

// 건수 링크 = 링크한 목록 기본 보기의 건수(설계고도화안 C-1·C-8). 칸의 수와 도착한 목록의 수를 대조한다.
test("멈춘 것 건수는 사전규격 확인 필요 보기의 건수이고 같은 보기를 연다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  const item = countLink(page, "pre-spec-needs-check");
  await expect(item).toHaveText(/^\d+건$/);
  const count = Number((await item.textContent())?.match(/(\d+)건/)?.[1]);
  await expect(item).toHaveAttribute("href", "/pre-specs?workspace=needs_check");
  await item.click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs");
  await expect(page.getByRole("button", { name: /확인 필요/ }).first()).toContainText(String(count));
});

test("Go/No-Go 건수 링크는 목록 기본 보기(검토 대상)의 건수이고 같은 보기를 연다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  const item = countLink(page, "go-no-go");
  await expect(item).toContainText(/Go\/No-Go \d+건/);
  const count = Number((await item.textContent())?.match(/Go\/No-Go (\d+)건/)?.[1]);
  await expect(item).toHaveAttribute("href", "/go-no-go");
  await item.click();
  await expect(page.getByRole("button", { name: /검토 대상/ }).first()).toContainText(String(count));
});

test("회차가 없어도 누적 업무와 공고 판정 이력으로 이동할 수 있다", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/runs", route => route.fulfill({ json: { items: [] } }));
  await page.goto("/");
  for (const target of DECISION_STRIP_TARGETS) await expect(countLink(page, target.key)).toBeVisible();
});

test("누적 집계 미확인을 0으로 접지 않는다", async ({ page }) => {
  await mockApi(page);
  // 목록 조회가 실패한 건수 링크는 0으로 접히지 않고 미확인으로 남아야 한다.
  await page.route((url) => url.pathname === "/api/pre-specs", (route) => route.fulfill({ status: 503, json: { detail: "합성 장애" } }));
  await page.route((url) => url.pathname === "/api/bid-delta/decision-queue", (route) => route.fulfill({ status: 503, json: { detail: "합성 장애" } }));
  await page.goto("/");
  const unmeasured = page.locator(".dash-page a[data-count]").filter({ hasText: "미확인" });
  // 사전규격 목록 실패(확인 필요·새 사전규격·개요 사람 확인)와 Go/No-Go 대기열 실패.
  await expect(unmeasured).toHaveCount(4);
  for (const item of await unmeasured.all()) await expect(item).not.toContainText("0건");
});

test("판정 기준은 선별과 공고 판정 트랙에 각 정책 상태를 제공한다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const path of ["/criteria", "/order-plan-policies"]) {
    await page.goto(path);
    await expect(page.locator(".crit-boundary")).toHaveCount(0);
    const c2 = page.getByRole("group", { name: "발주계획 선별 (C-2)", exact: true });
    await expect(c2.getByRole("link", { name: "선별 정책" })).toHaveAttribute("aria-current", "page");
    const policy = page.getByRole("region", { name: "선택한 발주계획 선별 policy" });
    await expect(policy.getByRole("heading", { name: "적재된 발주계획 선별 policy가 없어요" })).toBeVisible();
  }
  for (const path of ["/profile", "/policies", "/quality-gates", "/metrics"]) {
    await page.goto(path);
    await expect(page.locator(".crit-boundary")).toHaveCount(0);
    const c1 = page.getByRole("group", { name: "공고 판정 (C-1)", exact: true });
    await expect(c1.locator('a[aria-current="page"]')).toHaveCount(1);
    await expect(page.locator(".crit-summary")).toContainText("공고 판정(C-1) 정책");
  }
});

test("실행 상태는 모든 탭에서 운영 텔레메트리 위치와 상시 운영 차단 사유를 확인할 수 있다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const path of ["/run-status", "/runs", "/attachments", "/operations", "/audit"]) {
    await page.goto(path);
    await expect(page.locator(".rs-boundary")).toHaveCount(0);
    await page.getByRole("button", { name: "운영 조건", exact: true }).click();
    const conditions = page.getByRole("dialog", { name: "운영 조건과 경계" });
    await expect(conditions).toBeVisible();
    // 판정 화면에서 뺐지만 삭제하지 않았다(ADR-0041 결정 5).
    await conditions.getByText("판정 실행 기록 위치").click();
    await expect(conditions).toContainText("model_digest");
    await expect(conditions).toContainText("duration_ms");
    await expect(conditions).toContainText("거절 사유");
    await expect(conditions).toContainText("승인 조합");
    await expect(conditions).toContainText("startup은 migration·seed·정책 활성화·모델 호출을 수행하지 않아요");
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
  await page.route(/\/api\/opportunities\/\d+\/bid-conditions$/, async (route) => {
    const id = Number(new URL(route.request().url()).pathname.split("/")[3]);
    await route.fulfill({ status: 200, json: bidConditionsFixture(id) });
  });
  return trace;
}

test("최종 Go/No-Go 목록은 사업 이름과 변경 비교 결과 없음을 값으로 보여준다", async ({ page }) => {
  await mockApi(page);
  const trace = await mockDecisionQueueList(page, [queueItem()]);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/go-no-go?show=all");

  const rows = page.locator("tr.gng-row");
  await expect(rows).toHaveCount(1);
  // 식별자만 있는 행은 무슨 사업인지 알 수 없어 결국 하나씩 열어 봐야 한다.
  await expect(rows.nth(0)).toContainText("접근성 검증 입찰공고");
  await expect(rows.nth(0)).toContainText("테스트 조달기관");
  // 비교 0건은 값이다. `비교 0건`으로 눌러 담아 "아직 안 봤다"와 섞지 않는다.
  await expect(rows.nth(0)).toContainText("변경 비교 결과 없음");
  // 선택한 사업의 상세가 그려진 뒤에 요청을 센다.
  await expect(page.getByRole("heading", { name: "직전 차수 변경" })).toBeVisible();
  // 대기열을 한 번에 다 받았으므로 요약은 전체 기준이라고 말한다.
  await expect(page.locator(".gng-pager .review-list-pager-summary")).toHaveText("전체 1건");
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

  await expect(page.locator("tr.gng-row")).toHaveCount(30);
  await expect(page.getByRole("heading", { name: "직전 차수 변경" })).toBeVisible();
  expect(trace.queueQueries).toHaveLength(1);
  expect(trace.queueQueries[0]).toMatchObject({ status: "all", limit: "500", offset: "0" });
  expect(trace.opportunityListRequests).toBe(0);
  // 첫 행이 선택되고 그 사업 하나만 상세를 받는다.
  expect([...new Set(trace.workspaceIds)]).toEqual([600]);
  await expect(page.locator(".gng-pager .review-list-pager-summary")).toHaveText("전체 30건");
  // 공용 페이저는 한 쪽뿐이어도 항상 보이고 단추만 비활성이다(U3, 명세 §2.2).
  const pager = page.getByRole("navigation", { name: "결정 대기열 페이지" });
  await expect(pager).toBeVisible();
  await expect(pager).toContainText("1–30 / 30");
  await expect(pager.getByRole("button", { name: "이전" })).toBeDisabled();
  await expect(pager.getByRole("button", { name: "다음" })).toBeDisabled();

  // 다른 행을 골라도 대기열은 다시 받지 않고 그 행 하나만 조회한다.
  await page.locator("tr.gng-row").filter({ hasText: "결정 대기 사업 12" }).click();
  await expect.poll(() => [...new Set(trace.workspaceIds)].sort()).toEqual([600, 611]);
  expect(trace.queueQueries).toHaveLength(1);
});

// 저장 알림은 읽는 동안 사라지면 안 된다. 자동 소멸 시간을 늘리고, hover·focus
// 중에는 시간을 세지 않는다.
// 되돌릴 수 없는 결정의 확인 단계는 키보드만으로도 취소할 수 있어야 한다.
// 열릴 때 초점은 취소에 있고 Esc는 취소이며, 확인 전에는 요청이 나가지 않는다.
test("UC-05 추적 종료 확인 단계는 취소에 초점이 오고 Esc로 요청 없이 닫힌다", async ({ page }) => {
  const trace = await mockOpportunity(page);
  await openOpportunityDetail(page);

  await page.getByRole("button", { name: "추적 여부 선택", exact: true }).click();
  await page.getByRole("combobox", { name: "선택 사유", exact: true }).click();
  await page.getByRole("option", { name: "기타 · 직접 입력", exact: true }).click();
  await page.getByLabel("선택 사유 직접 입력").fill("현재 범위와 맞지 않아 능동 추적을 종료해요.");
  await page.getByLabel("담당자 이름 (필수)", { exact: true }).fill("홍길동");

  const save = page.getByRole("dialog").getByRole("button", { name: "추적 종료", exact: true });
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
  await expect(page.getByLabel("선택 사유 직접 입력")).toHaveValue("현재 범위와 맞지 않아 능동 추적을 종료해요.");
});
