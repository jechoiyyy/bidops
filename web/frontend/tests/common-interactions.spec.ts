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

  // 추적 상태 변경은 상세 pane 바닥의 접힌 보조 입력이다(PLAN 단계 E 작업 3-3).
  const editorToggle = page.getByRole("button", { name: "추적 상태 변경 열기" });
  await tabTo(page, editorToggle);
  await expectKeyboardTarget(editorToggle);
  await page.keyboard.press("Enter");

  const save = page.getByRole("button", { name: "추적 상태 저장" });
  await expect(save).toBeDisabled();
  // 미선택 건은 아무 상태도 미리 골라 두지 않으므로 첫 비활성 사유가 상태 선택이다.
  await expect(page.locator(`#${await save.getAttribute("aria-describedby")}`)).toContainText("추적 상태를 고르십시오");
  const status = page.locator(".opportunity-tracking-form select");
  await tabTo(page, status);
  await page.keyboard.press("ArrowDown");
  await expect(page.locator(`#${await save.getAttribute("aria-describedby")}`)).toContainText("이유를 입력하십시오");
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

  await expect(page.locator('a[href="/opportunities/501/bid-delta"]')).toHaveCount(1);
  await expect(page.getByRole("button", { name: "최종 결정 저장" })).toHaveCount(0);
  // 추적 상태 변경은 접혀 있고, 접힌 상태에서도 현재 값이 그대로 보인다.
  await expect(page.getByRole("button", { name: "추적 상태 변경 열기" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "추적 상태 저장" })).toHaveCount(0);
  await expect(page.locator('[data-review-primitive="secondary-input"]')).toHaveAttribute("data-open", "false");

  // 사람의 추적 판단은 추적 이력 탭이 소유한다. 무엇을 골랐고 누가 언제 골랐는지
  // 그 탭 하나에서 읽는다.
  await page.getByRole("tab", { name: "추적 이력", exact: true }).click();
  await expect(page.locator("#opportunity-panel-history")).toContainText("미선택");
  await expect(page.locator("#opportunity-panel-history")).toContainText("기록된 이유 없음");
});

// ADR-0046 결정 3으로 공고 1차 판정의 리뷰 저장이 사업 추적의 예외 작업으로
// 옮겨갔다. 공통 unsaved guard가 지켜야 할 입력도 함께 옮겨간다. 옛 자리에는
// 지킬 입력이 없고, 새 자리에는 있다.
test("공통 unsaved guard가 옮겨간 예외 작업 입력을 지킨다", async ({ page }) => {
  await mockOpportunity(page);
  await page.goto("/opportunities/501");

  await page.getByRole("button", { name: "추적 상태 변경 열기" }).click();
  await page.getByLabel("이유").fill("공통 guard 회귀 검증 초안");

  const blocked = await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  });
  expect(blocked).toBe(true);
  await expect(page.getByLabel("이유")).toHaveValue("공통 guard 회귀 검증 초안");
});

// ─────────────────────────────────────────────────────────────────────────
// docs/design/PLAN.md 단계 E 완료 게이트 (ADR-0046가 ADR-0041 결정 1·2를 개정)
// ─────────────────────────────────────────────────────────────────────────

const SIDEBAR_ITEMS = [
  { group: "오늘의 업무", label: "대시보드", path: "/" },
  { group: "탐색과 추적", label: "발주계획", path: "/order-plans" },
  { group: "탐색과 추적", label: "사전규격", path: "/pre-specs" },
  { group: "탐색과 추적", label: "사업 추적", path: "/opportunities" },
  { group: "탐색과 추적", label: "최종 Go/No-Go", path: "/go-no-go" },
  { group: "기준과 운영", label: "판정 기준", path: "/criteria" },
  { group: "기준과 운영", label: "실행 상태", path: "/run-status" },
];

test("사이드바는 7항목이고 1차 분류가 오늘의 업무 · 탐색과 추적 · 기준과 운영이다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const sidebar = page.locator("aside.sidebar");
  await expect(sidebar.locator(".sidebar-item")).toHaveCount(SIDEBAR_ITEMS.length);
  await expect(sidebar.locator(".sidebar-group-label")).toHaveText(["오늘의 업무", "탐색과 추적", "기준과 운영"]);

  for (const item of SIDEBAR_ITEMS) {
    const group = sidebar.locator(".sidebar-group", { hasText: item.group });
    await expect(group.getByRole("link", { name: item.label, exact: true })).toHaveCount(1);
  }

  // 리다이렉트 항목과 미구현 안내 항목을 최상위에 두지 않는다.
  await expect(sidebar.getByText("준비 중")).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: "마감 추적" })).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: "산출물 감사 로그" })).toHaveCount(0);
  // ADR-0046 결정 2: 회차 축 목록인 검토 대기열은 사이드바에서 사라진다.
  // 경로는 남지만(아래 흡수 경로 테스트) 최상위 진입점은 사업 추적 하나다.
  await expect(sidebar.getByRole("link", { name: "검토 대기열" })).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: "사업기회", exact: true })).toHaveCount(0);
});

test("사이드바 7항목이 모두 실제 화면으로 연결되고 최종 Go/No-Go에 한 번에 도달한다", async ({ page }) => {
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

// ADR-0046 결정 7: 회차 축은 대시보드와 공고 판정 이력 두 화면뿐이다. 공고 판정
// 이력은 사이드바 항목이 아니므로, 사이드바만 보면 회차 선택기가 보이는 자리는
// 대시보드 하나로 예측된다.
test("회차 선택기는 사이드바에서 대시보드에만 나타난다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const item of SIDEBAR_ITEMS) {
    await page.goto(item.path);
    const runSelector = page.getByLabel("실행 회차", { exact: true });
    if (item.path === "/") await expect(runSelector).toBeVisible();
    else await expect(runSelector).toHaveCount(0);
  }
});

test("사이드바 밖의 회차 축 화면은 공고 판정 이력 하나다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto("/judgments");
  await expect(page.locator("header.topbar h1")).toHaveText("공고 판정 이력");
  await expect(page.getByLabel("실행 회차", { exact: true })).toBeVisible();

  // 같은 화면의 다른 두 탭은 회차 종속이지만 선택기를 갖지 않는다. 회차를 못
  // 바꾼다고 오인하지 않도록 어디서 고르는지 화면이 직접 말한다.
  await page.goto("/queue");
  await expect(page.getByLabel("실행 회차", { exact: true })).toHaveCount(0);
  await expect(page.locator(".ws-run-note")).toContainText("공고 판정 이력");
  await page.goto("/reviews");
  await expect(page.getByLabel("실행 회차", { exact: true })).toHaveCount(0);
});

test("흡수한 옛 경로는 404를 내지 않고 목적지 화면의 해당 탭으로 열린다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  const absorbed = [
    { path: "/judgments", title: "공고 판정 이력", tab: "공고 판정 이력" },
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

test("심층 검토 보고서 진입점이 사업 추적 화면에 명시된다", async ({ page }) => {
  await mockApi(page);
  await mockOpportunity(page);
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

// docs/design/PLAN.md 단계 E 작업 7 게이트: 대시보드 "지금 처리할 일" 스트립에서
// 네 결정 화면 각각으로 한 번에 이동할 수 있다. 건수가 0이거나 확인 불가여도
// 이동 경로 자체는 항상 있어야 한다.
//
// ADR-0046 결정 3으로 공고 1차 판정이 읽기 전용 이력이 되면서 넷째 자리가
// `공고 1차 판정`에서 `예외 조치`로 바뀌었다. 사람이 손대야 하는 것은 회차
// 표본 전수가 아니라 근거 없음·검증 실패·연결 불확실이다.
const DECISION_STRIP_TARGETS = [
  { title: /발주계획 추적 결정/, pathname: "/order-plans" },
  { title: /사전규격 심층 검토 승인/, pathname: "/pre-specs" },
  { title: /예외 조치가 남아 있을 수 있다/, pathname: "/opportunities" },
  { title: /최종 Go\/No-Go 결정/, pathname: "/go-no-go" },
];

test("대시보드 할 일 스트립에서 네 결정 화면 각각으로 이동할 수 있다(회차 선택 상태)", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const strip = page.locator(".dashboard-action-strip");
  await expect(strip).toContainText("지금 처리할 일");
  for (const target of DECISION_STRIP_TARGETS) {
    await page.goto("/");
    const link = strip.getByRole("link", { name: target.title });
    await expect(link).toBeVisible();
    await link.click();
    await expect.poll(() => new URL(page.url()).pathname).toMatch(new RegExp(`^${target.pathname}`));
  }
});

// 사전규격 마감 임박 건수는 클라이언트에서 구할 수 없다. `GET /api/pre-specs`에
// 마감 구간 필터도 집계도 없고 `sort=deadline`이 마감 오름차순이라 첫 페이지가
// 이미 지난 마감으로 채워진다 — 한 페이지를 세면 지난 마감을 임박으로 세고,
// 임박 구간에는 도달하지도 못한다(docs/tracking/findings.md). 그럴듯한 숫자
// 대신 "확인 불가"가 표시되는 것을 고정한다.
test("사전규격 마감 임박 건수는 서버 집계가 없어 확인 불가로 표시되고, 이동은 항상 가능하다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const deadlineItem = page.locator(".dashboard-action-strip").getByRole("link", { name: /사전규격 심층 검토 승인/ });
  await expect(deadlineItem.locator("strong")).toHaveText("확인 불가");
  await deadlineItem.click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs");
  await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("deadline");
});

test("Go/No-Go 대기 건수는 서버 집계가 없어 확인 불가로 표시되고, 이동은 항상 가능하다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const goNoGoItem = page.locator(".dashboard-action-strip").getByRole("link", { name: /최종 Go\/No-Go 결정/ });
  await expect(goNoGoItem.locator("strong")).toHaveText("확인 불가");
  await expect(goNoGoItem).toContainText("건수 확인 불가");
});

test("회차를 선택하지 않아도 누적 추적 항목은 할 일 스트립에서 확인·이동할 수 있다", async ({ page }) => {
  // /api/runs를 빈 목록으로 덮어써 AppShell이 회차를 자동 선택하지 못하게 한다.
  await mockApi(page);
  await page.route("**/api/runs", async (route) => {
    if (route.request().method() !== "GET") { await route.fallback(); return; }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  await expect(page.getByText("선택된 회차가 없습니다.", { exact: true })).toBeVisible();
  const strip = page.locator(".dashboard-action-strip");
  // 누적 추적 항목(C-2·사전규격·Go/No-Go)은 회차와 무관하므로 여전히 보인다.
  await expect(strip.getByRole("link", { name: /발주계획 추적 결정/ })).toBeVisible();
  await expect(strip.getByRole("link", { name: /사전규격 심층 검토 승인/ })).toBeVisible();
  await expect(strip.getByRole("link", { name: /예외 조치가 남아 있을 수 있다/ })).toBeVisible();
  await expect(strip.getByRole("link", { name: /최종 Go\/No-Go 결정/ })).toBeVisible();
  // 회차 자료는 읽기 전용 이력이다. 회차가 있어야 건수를 알 수 있지만 이동
  // 경로 자체는 회차 없이도 남는다.
  const queueItem = strip.getByRole("link", { name: /공고 1차 판정 이력 확인/ });
  await expect(queueItem).toBeVisible();
  await expect(queueItem.locator("strong")).toHaveText("확인 불가");
  await queueItem.click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/queue");
});

// ── PLAN 단계 E 작업 6·7 ──────────────────────────────────────────────────

test("할 일 스트립은 확인 불가를 0으로 바꾸지 않는다고 화면에 적는다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const note = page.locator(".dashboard-action-note");
  await expect(note).toContainText("확인 불가");
  await expect(note).toContainText("0건이 아닙니다");
  await expect(note).toContainText("읽기 전용");
});

test("판정 기준은 이 화면이 정하지 않는 것과 정책 차단 사유를 모든 탭에서 남긴다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const path of ["/criteria", "/profile", "/policies", "/quality-gates", "/metrics"]) {
    await page.goto(path);
    const guardrails = page.locator(".criteria-guardrails");
    await expect(guardrails.getByRole("heading", { name: "이 화면이 정하지 않는 것" })).toBeVisible();
    // 네 판단은 각각 별도 조작이다. 기준 편집이 판정을 소급해 바꾸지 않는다.
    await expect(guardrails).toContainText("적합성 등급 4값");
    await expect(guardrails).toContainText("참여 준비 상태 4값");
    await expect(guardrails).toContainText("심층 검토 실행 승인");
    await expect(guardrails).toContainText("최종 입찰 Go/No-Go");
    await expect(guardrails).toContainText("소급해 바꾸지 않습니다");
    await expect(guardrails.getByRole("heading", { name: "활성화 대기 판정 정책" })).toBeVisible();
  }
});

test("실행 상태는 운영 텔레메트리 위치와 상시 운영 차단 사유를 모든 탭에서 남긴다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const path of ["/run-status", "/runs", "/attachments", "/operations", "/audit"]) {
    await page.goto(path);
    const guardrails = page.locator(".runstatus-guardrails");
    await expect(guardrails.getByRole("heading", { name: "운영 텔레메트리" })).toBeVisible();
    // 판정 화면에서 뺐지만 삭제하지 않았다(ADR-0041 결정 5).
    await expect(guardrails).toContainText("삭제하지 않았습니다");
    await expect(guardrails).toContainText("model_digest");
    await expect(guardrails).toContainText("duration_ms");
    await expect(guardrails.getByRole("heading", { name: "상시 운영" })).toBeVisible();
    await expect(guardrails).toContainText("차단 사유");
    await expect(guardrails).toContainText("startup은 migration·seed·정책 활성화·모델 호출을 수행하지 않습니다");
  }
});

test("최종 Go/No-Go 목록은 사업 이름과 변경 비교 결과 없음을 값으로 보여준다", async ({ page }) => {
  await mockApi(page);
  await page.route(/\/api\/opportunities(\?|$)/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [opportunity], total: 1, limit: 100, offset: 0 }),
    });
  });
  // 비교가 하나도 없는 workspace다. `비교 0건`이 아니라 값으로 읽혀야 한다.
  await page.route(/\/api\/opportunities\/501\/bid-delta/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "bidops.bid-delta-workspace.v1",
        opportunity_id: 501,
        baseline_candidates: [],
        comparison_candidates: [],
        comparisons: [],
        latest_final_decision: null,
        final_decisions: [],
        decision_currentness: "unknown",
      }),
    });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/go-no-go?show=all");

  const rows = page.locator(".gng-row");
  await expect(rows.first()).toBeVisible();
  // 식별자만 있는 행은 무슨 사업인지 알 수 없어 결국 하나씩 열어 봐야 한다.
  await expect(rows.first()).toContainText("접근성 검증 입찰공고");
  await expect(rows.first()).toContainText("테스트 조달기관");
  // 비교 0건은 값이다. `비교 0건`으로 눌러 담아 "아직 안 봤다"와 섞지 않는다.
  await expect(rows.first()).toContainText("변경 비교 결과 없음");
  // 받은 목록에서 센 값이라는 사실을 요약이 직접 말한다.
  await expect(page.locator(".gng-summary")).toContainText("전체 총계가 아닙니다");
});
