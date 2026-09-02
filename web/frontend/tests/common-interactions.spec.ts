import { expect, test, type Locator, type Page } from "@playwright/test";
import { mockApi, mockDeepReviewLifecycle } from "./api-mock";

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

const unknownOverview = {
  schema_version: "bidops.prespec-overview-reviews.v2",
  notice_id: 991,
  reviews: [{
    id: "00000000-0000-0000-0000-000000000991",
    notice_id: 991,
    status: "needs_human_review",
    result: null,
    result_digest: null,
    binding_digest: null,
    validation_status: "pending",
    completed_at: null,
    current_snapshot: {
      id: "10000000-0000-0000-0000-000000000991",
      document_version_id: "20000000-0000-0000-0000-000000000991",
      structure_id: "30000000-0000-0000-0000-000000000991",
      source_sha256: "a".repeat(64),
      payload_sha256: "b".repeat(64),
      cut_status: "unknown",
      strategy: null,
      start_locator: null,
      end_locator: null,
      created_at: "2026-08-31T01:00:00Z",
    },
    attempts: [],
  }],
};

async function tabTo(page: Page, target: Locator, maximumTabs = 120): Promise<void> {
  await target.waitFor({ state: "visible" });
  for (let index = 0; index < maximumTabs; index += 1) {
    if (await target.evaluate((element) => document.activeElement === element)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error(`키보드 Tab ${maximumTabs}회 안에 대상 control에 도달하지 못했습니다.`);
}

async function expectKeyboardTarget(target: Locator): Promise<void> {
  await expect(target).toBeFocused();
  const metrics = await target.evaluate((element) => {
    const style = getComputedStyle(element);
    return { height: element.getBoundingClientRect().height, outline: style.outlineStyle };
  });
  expect(metrics.height).toBeGreaterThanOrEqual(40);
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
  await page.route("**/api/pre-specs/991/overview-reviews/v2", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(unknownOverview) });
  });
  return { createCount: () => creates };
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("UC-01은 키보드만으로 추적 저장 직전까지 이동하고 비활성 사유를 읽는다", async ({ page }) => {
  const trace = await mockOpportunity(page);
  await page.goto("/opportunities/501");

  const editorToggle = page.getByRole("button", { name: "사람 추적 상태 변경" });
  await tabTo(page, editorToggle);
  await expectKeyboardTarget(editorToggle);
  await page.keyboard.press("Enter");

  const save = page.getByRole("button", { name: "추적 상태 저장" });
  await expect(save).toBeDisabled();
  await expect(page.locator(`#${await save.getAttribute("aria-describedby")}`)).toContainText("이유를 입력하십시오");
  const status = page.locator(".opportunity-tracking-form select");
  await tabTo(page, status);
  await page.keyboard.press("ArrowDown");
  const reason = page.getByLabel("이유");
  await tabTo(page, reason);
  await page.keyboard.type("새 사전규격을 계속 확인합니다.");
  const actor = page.getByLabel("담당자 이름");
  await tabTo(page, actor);
  await page.keyboard.type("홍길동");
  await tabTo(page, save);

  await expectKeyboardTarget(save);
  await expect(save).toBeEnabled();
  expect(trace.patchCount()).toBe(0);
});

test("UC-02 상태 문구는 색을 제거해도 unknown과 사람 확인 필요를 보존한다", async ({ page }) => {
  await mockPreSpecWorkbench(page);
  await page.goto("/pre-specs/991");
  await page.addStyleTag({ content: "* { color: #111 !important; background-color: #fff !important; border-color: #111 !important; }" });

  await expect(page.getByText("사람 검토 필요", { exact: true })).toBeVisible();
  await expect(page.getByText("unknown · 사람 확인 필요", { exact: true })).toBeVisible();
  await expect(page.getByText(/전체 문서 성공으로 자동 보정하지 않습니다/)).toBeVisible();
});

test("UC-03은 키보드만으로 draft bundle 생성 직전까지 이동한다", async ({ page }) => {
  const trace = await mockPreSpecWorkbench(page);
  await page.goto("/pre-specs/991");

  const actor = page.getByLabel("담당자 claimed name");
  const create = page.getByRole("button", { name: "새 문서 bundle 만들기" });
  await expect(create).toBeDisabled();
  await expect(page.locator(`#${await create.getAttribute("aria-describedby")}`)).toContainText("claimed name을 입력하십시오");
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

  const actor = page.getByLabel("담당자 claimed name");
  const retry = page.getByRole("button", { name: "새 attempt로 재시도" });
  await expect(retry).toBeDisabled();
  await expect(page.locator(`#${await retry.getAttribute("aria-describedby")}`)).toContainText("claimed name을 입력하십시오");
  await tabTo(page, actor);
  await page.keyboard.type("심층 검토자");
  await tabTo(page, retry);

  await expectKeyboardTarget(retry);
  await expect(retry).toBeEnabled();
  await expect(page.getByText("Attempt 1회", { exact: true })).toBeVisible();
  expect(trace.attemptPosts).toHaveLength(0);
});

test("R-08 이후 상세는 변경 비교로 이동하고 추적 저장과 최종 결정 저장을 분리한다", async ({ page }) => {
  await mockOpportunity(page);
  await page.goto("/opportunities/501");

  await expect(page.getByText("사람의 추적 판단", { exact: true })).toBeVisible();
  await expect(page.locator('a[href="/opportunities/501/bid-delta"]')).toHaveCount(1);
  await expect(page.getByRole("button", { name: "최종 결정 저장" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "추적 상태 변경" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "추적 상태 저장" })).toHaveCount(0);
});

test("공통 unsaved guard가 기존 queue 임시 초안 보호를 유지한다", async ({ page, viewport }) => {
  await page.goto("/queue");
  if ((viewport?.width ?? 0) <= 900) {
    await page.locator(".queue-list-item").first().click();
  } else {
    await page.waitForURL(/\/queue\/\d+/);
  }
  await page.getByLabel("리뷰 사유").fill("공통 guard 회귀 검증 초안");

  const blocked = await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  });
  expect(blocked).toBe(true);
  await expect(page.getByLabel("리뷰 사유")).toHaveValue("공통 guard 회귀 검증 초안");
});

// ─────────────────────────────────────────────────────────────────────────
// docs/design/PLAN.md 2단계 완료 게이트 (ADR-0041)
// ─────────────────────────────────────────────────────────────────────────

const SIDEBAR_ITEMS = [
  { group: "회차 검토", label: "대시보드", path: "/" },
  { group: "회차 검토", label: "검토 대기열", path: "/queue" },
  { group: "누적 추적", label: "발주계획 C-2", path: "/order-plans" },
  { group: "누적 추적", label: "사전규격", path: "/pre-specs" },
  { group: "누적 추적", label: "사업기회", path: "/opportunities" },
  { group: "누적 추적", label: "최종 Go/No-Go", path: "/go-no-go" },
  { group: "기준과 운영", label: "판정 기준", path: "/criteria" },
  { group: "기준과 운영", label: "실행 상태", path: "/run-status" },
];

test("사이드바는 8항목이고 1차 분류가 회차 검토 · 누적 추적 · 기준과 운영이다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const sidebar = page.locator("aside.sidebar");
  await expect(sidebar.locator(".sidebar-item")).toHaveCount(SIDEBAR_ITEMS.length);
  await expect(sidebar.locator(".sidebar-group-label")).toHaveText(["회차 검토", "누적 추적", "기준과 운영"]);

  for (const item of SIDEBAR_ITEMS) {
    const group = sidebar.locator(".sidebar-group", { hasText: item.group });
    await expect(group.getByRole("link", { name: item.label, exact: true })).toHaveCount(1);
  }

  // 리다이렉트 항목과 미구현 안내 항목을 최상위에 두지 않는다.
  await expect(sidebar.getByText("준비 중")).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: "마감 추적" })).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: "산출물 감사 로그" })).toHaveCount(0);
});

test("사이드바 8항목이 모두 실제 화면으로 연결되고 최종 Go/No-Go에 한 번에 도달한다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const item of SIDEBAR_ITEMS) {
    await page.goto("/");
    await page.locator("aside.sidebar").getByRole("link", { name: item.label, exact: true }).click();
    // 실제 화면이 그려진다: 빈 라우트나 오류 경계가 아니라 상단바 제목이 채워진다.
    await expect(page.locator("header.topbar h1")).not.toHaveText("BidOps Admin");
    await expect(page.locator(".lazy-route-error")).toHaveCount(0);
  }

  // 최종 Go/No-Go는 사이드바에서 한 번에 도달한다(중간 화면을 거치지 않는다).
  await page.goto("/");
  await page.locator("aside.sidebar").getByRole("link", { name: "최종 Go/No-Go", exact: true }).click();
  await expect(page.locator("header.topbar h1")).toHaveText("최종 Go/No-Go");
  await expect(page.getByRole("heading", { name: "최종 Go/No-Go", level: 2 })).toBeVisible();
});

test("회차 선택기 표시 여부가 1차 분류와 일치한다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const item of SIDEBAR_ITEMS) {
    await page.goto(item.path);
    const runSelector = page.getByLabel("실행 회차", { exact: true });
    if (item.group === "회차 검토") await expect(runSelector).toBeVisible();
    else await expect(runSelector).toHaveCount(0);
  }
});

test("흡수한 옛 경로는 404를 내지 않고 목적지 화면의 해당 탭으로 열린다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  const absorbed = [
    { path: "/judgments", title: "검토 대기열", tab: "공고 판정 이력" },
    { path: "/reviews", title: "검토 대기열", tab: "담당자 리뷰 기록" },
    { path: "/profile", title: "판정 기준", tab: "회사 프로필" },
    { path: "/policies", title: "판정 기준", tab: "판정 정책" },
    { path: "/quality-gates", title: "판정 기준", tab: "품질 게이트" },
    { path: "/metrics", title: "판정 기준", tab: "검증 지표" },
    { path: "/runs", title: "실행 상태", tab: "수집 실행" },
    { path: "/attachments", title: "실행 상태", tab: "첨부 확보" },
    { path: "/operations", title: "실행 상태", tab: "상시 운영" },
    { path: "/audit", title: "실행 상태", tab: "산출물 감사 로그" },
  ];

  for (const entry of absorbed) {
    await page.goto(entry.path);
    await expect(page.locator("header.topbar h1")).toHaveText(entry.title);
    await expect(page.getByRole("tab", { name: entry.tab, exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(page.locator(".lazy-route-error")).toHaveCount(0);
  }

  // 마감 추적은 검토 대기열의 저장된 뷰다. 리다이렉트가 아니라 그 뷰의 주소이므로
  // 경로가 그대로 남고, 정렬이 마감 임박순으로 열린다. 리다이렉트로 sort를 실어
  // 보내던 방식은 AppShell의 회차 동기화와 경쟁해 파라미터를 잃었다.
  await page.goto("/deadlines");
  await expect(page.locator("header.topbar h1")).toHaveText("검토 대기열");
  await expect(page.getByRole("tab", { name: "검토 대기열", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("정렬", { exact: true })).toHaveValue("deadline");

  // 같은 화면의 기본 주소는 등급순 그대로다: 저장된 뷰가 기본값을 바꾸지 않는다.
  await page.goto("/queue");
  await expect(page.getByLabel("정렬", { exact: true })).toHaveValue("grade");
});

test("심층 검토 보고서 진입점이 사업기회 화면에 명시된다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/opportunities/501");

  const entry = page.locator(".opportunity-deep-review");
  await expect(entry.getByRole("heading", { name: "심층 검토 보고서" })).toBeVisible();
  // 서버가 사업기회별 보고서 목록을 주지 않는다는 사실을 감추지 않는다.
  await expect(entry).toContainText("서버가 사업기회별 보고서 목록을 제공하지 않아");
  await entry.getByLabel("심층 검토 보고서 ID").fill("fixture-review");
  await entry.getByRole("link", { name: "보고서 열기 →" }).click();
  await expect(page).toHaveURL(/\/deep-reviews\/fixture-review/);
});
