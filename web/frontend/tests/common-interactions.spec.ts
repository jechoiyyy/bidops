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
  links: [],
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
  schema_version: "bidops.prespec-overview-reviews.v1",
  notice_id: 991,
  reviews: [{
    id: "00000000-0000-0000-0000-000000000991",
    notice_id: 991,
    status: "needs_human_review",
    result: null,
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
  await page.route("**/api/pre-specs/991/overview-reviews", async (route) => {
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

test("UC-05는 계약 승인 전 변경 비교 navigation과 최종 결정 저장 control을 노출하지 않는다", async ({ page }) => {
  const bidDeltaRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith("/bid-delta")) bidDeltaRequests.push(request.url());
  });
  await mockOpportunity(page);
  await page.goto("/opportunities/501");

  await expect(page.getByText("사람의 추적 판단", { exact: true })).toBeVisible();
  await expect(page.locator('a[href="/opportunities/501/bid-delta"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Go|No-Go|저장/ })).toHaveCount(0);
  expect(bidDeltaRequests).toHaveLength(0);
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
