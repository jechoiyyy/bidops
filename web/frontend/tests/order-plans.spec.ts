import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlans } from "./api-mock";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

/** 추적 사유는 초기값이 비어 있는 드롭다운이다. 저장하려면 사람이 골라야 한다. */
async function selectReason(page: import("@playwright/test").Page, label: string) {
  await page.getByRole("combobox", { name: "선택 사유" }).click();
  await page.getByRole("option", { name: label, exact: true }).click();
}

/** 기술 축 필터는 `상세 필터` 뒤에 접혀 있다. 열어야 축과 `필터 초기화`를 쓸 수 있다. */
async function openAdvancedFilters(page: import("@playwright/test").Page) {
  const toggle = page.getByRole("button", { name: "상세 필터", exact: true });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
}

/**
 * 보기 탭은 라디오가 아니라 `aria-pressed` 버튼이고 이름에 건수가 붙는다
 * (`전체  9`). 라벨 앞부분으로만 찾는다 — 건수가 바뀌어도 같은 탭을 가리켜야 한다.
 */
function presetTab(page: import("@playwright/test").Page, label: string) {
  return page.locator(".c2l-filters .workspace-view-tabs")
    .getByRole("button", { name: new RegExp(`^${label}(\\s|$)`) });
}

async function clickPreset(page: import("@playwright/test").Page, label: string) {
  await presetTab(page, label).click();
}

/** 상세 필터 안의 초기화. 빈 상태 안내의 같은 이름 버튼과 섞이지 않게 필터 바로 좁힌다. */
async function resetFilters(page: import("@playwright/test").Page) {
  await openAdvancedFilters(page);
  await page.locator(".c2l-filters").getByRole("button", { name: "필터 초기화", exact: true }).click();
}

const TEST_ORDER_PLAN_SOURCE_RUN_ID = "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101";

function testOrderPlanItem(orderPlanPk: number, relevance: "relevant" | "uncertain" | "not_relevant" | null, title: string) {
  return {
    order_plan_pk: orderPlanPk,
    order_plan_unty_no: `OP-TEST-${String(orderPlanPk).padStart(5, "0")}`,
    title,
    agency_name: `테스트 기관 ${orderPlanPk}`,
    business_division: "정보화",
    budget_amount: null,
    planned_order_year: null,
    planned_order_month: null,
    source_run_id: TEST_ORDER_PLAN_SOURCE_RUN_ID,
    observed_at: "2026-09-01T01:00:00Z",
    stage1_status: "selected",
    stage1_rank: orderPlanPk,
    stage1_score: 0.5,
    nearest_capability: null,
    stage2_status: relevance === null ? "unknown" : "success",
    qwen_relevance: relevance,
    qwen_score: relevance === null ? null : 0.5,
    qwen_reason: null,
    human_feedback: null,
    tracking: {
      opportunity_id: 5000 + orderPlanPk,
      tracking_status: "미선택",
      tracking_reason: null,
      tracking_selected_by: null,
      tracking_selected_at: null,
    },
  };
}

/** The browser fetches all pages, so this keeps API order deliberately different from relevance order. */
async function mockReorderedOrderPlanList(
  page: import("@playwright/test").Page,
  items: ReturnType<typeof testOrderPlanItem>[],
) {
  await mockOrderPlans(page);
  await page.route("**/api/order-plans**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() !== "GET" || url.pathname !== "/api/order-plans") {
      await route.fallback();
      return;
    }
    const limit = Number(url.searchParams.get("limit") ?? 100);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "order-plan-list-response.v2",
        producer: "order-plan-review-api",
        consumer: "order-plan-review-client",
        scope: {
          execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010101",
          source_run_id: TEST_ORDER_PLAN_SOURCE_RUN_ID,
          status: "부분 성공",
          finished_at: "2026-09-01T02:05:00Z",
        },
        items: items.slice(offset, offset + limit),
        total: items.length,
        limit,
        offset,
      }),
    });
  });
}

// 화면 제목은 `발주계획` 한 낱말이고(승인 시안), 목록 행은 사업명 → 상태 배지 → metadata(발주기관·
// 예산·시기) 차례를 그대로 지킨다. 발주기관은 자리를 옮기지 않고 크기만
// 보조 글자에서 본문 굵은 글자로 키운다.
test("기본 목록은 밀집 행이고 판정에 필요한 값만 담으며, 신호 세부·실행 기록은 별도 대화상자에 남는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  // 화면 제목은 상단바의 h1 하나다. 페이지는 같은 이름을 다시 그리지 않는다(제목 모드).
  await expect(page.locator("header.topbar h1")).toHaveText("발주계획");
  await expect(page.locator("header.topbar").getByRole("combobox", { name: "발주계획 수집 회차" })).toBeVisible();
  // 페이지에 남는 것은 문서 구조와 `aria-labelledby`를 위한 숨긴 제목 하나뿐이다.
  await expect(page.locator("section.c2l-page > h2.visually-hidden")).toHaveText("발주계획");
  await expect(page.locator("section.c2l-page .c2l-page-header")).toHaveCount(0);
  await expect(page.locator(".c2l-row")).toHaveCount(2);
  await expect(page.locator(".c2l-row").first()).toContainText("모델 관련");
  await expect(page.locator(".c2l-row").nth(1)).toContainText("모델 판단 보류");
  await expect(page.locator(".c2l-row").first()).toContainText("1.3억원");
  // 수집 API의 연월 형식도 연도 중복 없이 읽힌다. 다음 행은 월만 온다.
  await expect(page.locator(".c2l-row").first()).toContainText("2026년 11월");
  await expect(page.locator(".c2l-row").nth(1)).toContainText("2027년 03월");
  await expect(page.locator(".c2l-detail-facts")).toContainText("2026년 11월");
  await expect(page.locator(".c2l-row").first().getByTitle("예산 125,000,000원", { exact: true })).toBeVisible();
  await expect(page.locator(".c2l-row").first()).not.toContainText("nearest capability");

  // 사업명이 행의 첫 줄이고 발주기관은 metadata 줄의 첫 항목이다. 순서를 뒤집지 않는다.
  // 강조는 사업명 하나만 갖는다: 본문보다 한 단 큰 굵은 글자이고, 발주기관은 같은 본문
  // 크기의 보통 굵기다(사용자 정정).
  const firstRow = page.locator(".c2l-row").first();
  await expect(firstRow.locator(".c2l-row-title")).toContainText("공공데이터 통합");
  await expect(firstRow.locator(".c2l-row-meta")).toContainText("서울특별시 디지털정책관");
  const geometry = await firstRow.evaluate((row) => {
    const title = row.querySelector<HTMLElement>(".c2l-row-title");
    const agency = row.querySelector<HTMLElement>(".c2l-row-agency");
    if (!title || !agency) throw new Error("행의 사업명·발주기관을 찾을 수 없습니다.");
    return {
      titleTop: title.getBoundingClientRect().top,
      agencyTop: agency.getBoundingClientRect().top,
      titleFontSize: Number.parseFloat(getComputedStyle(title).fontSize),
      titleWeight: Number(getComputedStyle(title).fontWeight),
      agencyFontSize: Number.parseFloat(getComputedStyle(agency).fontSize),
      agencyWeight: Number(getComputedStyle(agency).fontWeight),
    };
  });
  expect(geometry.titleTop).toBeLessThan(geometry.agencyTop);
  expect(geometry.titleFontSize).toBe(geometry.agencyFontSize + 1);
  expect(geometry.titleWeight).toBeGreaterThanOrEqual(600);
  expect(geometry.agencyFontSize).toBeGreaterThanOrEqual(14);
  expect(geometry.agencyWeight).toBeLessThan(600);

  // 상세 pane은 행을 고른 뒤에 채워진다.
  await firstRow.click();

  // 신호 세부(BM25 rank/score/nearest capability, Qwen score/reason)는 행에도 기본
  // 상세에도 없고, 보조 대화상자에 그대로 남는다.
  await page.getByRole("button", { name: "선별 신호와 실행 기록 열기" }).click();
  await expect(page.locator("#c2l-panel-signals")).toContainText("nearest capability");
  await expect(page.locator("#c2l-panel-signals")).toContainText("Qwen relevance 신호");

  // 운영 텔레메트리(model_digest, token 수, duration_ms, binding sha256, artifact 요약)도
  // 삭제하지 않고 같은 대화상자의 `실행 기록` 탭으로 옮겼다.
  await page.getByRole("tab", { name: "실행 기록" }).click();
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("정책·모델 연결");
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("qwen3.8-27B");
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("prompt-v3");
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("profile-v1");
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("qwen_timeout");
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("120,000");
});

test("발주계획의 기존 머리글 액션은 상단바 슬롯에 한 번씩만 남는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  const topbar = page.locator("header.topbar");
  const actions = topbar.locator("#page-header-actions");

  // 제목은 셸이 하나만 그린다. 페이지 안에는 보조 접근성 제목만 남고, 예전 머리글
  // 또는 portal wrapper의 복제본이 다시 생기면 안 된다.
  await expect(topbar.locator("h1")).toHaveText("발주계획");
  await expect(page.locator(".c2l-page-header")).toHaveCount(0);
  await expect(page.locator(".c2l-page > .c2l-header-actions")).toHaveCount(0);
  await expect(actions.locator(".c2l-header-actions")).toHaveCount(1);

  // 기존 머리글이 제공하던 네 가지 동선을 모두 같은 portal 아래에서 확인한다.
  await expect(actions.getByRole("combobox", { name: "발주계획 수집 회차" })).toBeVisible();
  await expect(actions.locator(".c2l-status-chip")).toHaveCount(1);
  await expect(actions.getByRole("button", { name: "실행 상태", exact: true })).toHaveCount(1);
  await expect(actions.getByRole("link", { name: "실행 상세 →", exact: true })).toHaveCount(1);
});

// 기본 상세는 실제로 있는 값만 싣는다. 모델 근거는 서버가 준 `qwen_reason` 그대로이고,
// 출처는 알려진 필드 이름(발주계획 사업명)으로만 적으며 원문 인용을 만들지 않는다.
test("기본 상세는 실제 모델 근거와 알려진 출처 필드만 보여주고 원문 인용을 만들지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  const evidence = page.locator(".c2l-evidence");
  await expect(evidence.locator(".c2l-evidence-body")).toHaveText("데이터 플랫폼 구축과 운영 범위가 확인됩니다.");
  await expect(evidence.locator(".c2l-evidence-source dt")).toHaveText("근거 위치 · 발주계획 사업명");
  await expect(evidence.locator(".c2l-evidence-source dd")).toContainText("공공데이터 통합");
  await expect(evidence.locator(".c2l-evidence-scope")).toHaveText("계획 정보 기반 탐색 신호 · 회사 적합성과 참여 자격은 미확인");

  // 발주기관은 상세에서 라벨과 함께 강조 영역으로 먼저 읽힌다.
  const head = page.locator(".c2l-detail-head");
  await expect(head.locator(".c2l-agency-label")).toHaveText("발주기관");
  await expect(head.locator(".c2l-agency-name")).toHaveText("서울특별시 디지털정책관");

  // 시안 기준 글자 크기: 사업명 20px, 발주기관 14px 굵게. Astryx rem 기본값(12.25px)으로
  // 되돌아가면 화면 전체가 시안보다 작아진다(docs/engineering-notes.md).
  const type = await page.locator(".c2l-detail-pane").evaluate((pane) => {
    const size = (selector: string) => {
      const element = pane.querySelector<HTMLElement>(selector);
      if (!element) throw new Error(`${selector} 를 찾을 수 없습니다.`);
      return { fontSize: Number.parseFloat(getComputedStyle(element).fontSize), weight: Number(getComputedStyle(element).fontWeight) };
    };
    return { title: size("h4"), agency: size(".c2l-agency-name"), body: size(".c2l-evidence-body") };
  });
  expect(type.title.fontSize).toBe(20);
  expect(type.agency.fontSize).toBe(14);
  expect(type.agency.weight).toBeGreaterThanOrEqual(600);
  expect(type.body.fontSize).toBe(14);
});

test("토큰 필터는 축끼리 AND, 축 안에서는 OR로 조합되고 프리셋은 이름 붙은 지름길일 뿐이다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  await clickPreset(page, "전체");
  await expect(page).toHaveURL(/qwen=(&|$)/);
  await expect(page.locator(".c2l-row")).toHaveCount(9);

  await clickPreset(page, "BM25 탈락");
  await expect(page).toHaveURL(/stage1=filtered_out/);
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("BM25 탈락");

  // Qwen 비관련은 더 이상 고정 프리셋이 아니라 relevance 축의 한 값이다.
  await clickPreset(page, "전체");
  await openAdvancedFilters(page);
  await page.locator(".c2l-filter-axis", { hasText: "Qwen relevance" }).getByRole("button", { name: "not_relevant" }).click();
  await expect(page).toHaveURL(/qwen=not_relevant/);
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("모델 비관련");

  // "실패·거부" 프리셋은 BM25 단계 실패(106)와 Qwen 단계 실패(105)·거부(108)를 모두 포함하고,
  // Qwen 미시도(104)나 unknown(107)은 포함하지 않는다. 행은 제목이 아니라 상태 문구로 식별한다.
  await clickPreset(page, "전체");
  await clickPreset(page, "실패·거부");
  await expect(page).toHaveURL(/issue=yes/);
  const issueRows = page.locator(".c2l-row");
  await expect(issueRows).toHaveCount(3);
  await expect(issueRows.filter({ hasText: "BM25 실패" })).toHaveCount(1);
  await expect(issueRows.filter({ hasText: "Qwen 실패" })).toHaveCount(1);
  await expect(issueRows.filter({ hasText: "Qwen 거부" })).toHaveCount(1);
  await expect(issueRows.filter({ hasText: "Qwen unknown" })).toHaveCount(0);

  // 필터 초기화는 검토 대상(기본) 조합으로 되돌린다.
  await resetFilters(page);
  await expect(page.locator(".c2l-row")).toHaveCount(2);
});

test("검토 목록은 relevance 우선순위로 정렬하고 선택 순서와 같은 relevance의 원래 순서를 보존한다", async ({ page }) => {
  const items = [
    testOrderPlanItem(102, "uncertain", "API 순서 불확실 사업"),
    testOrderPlanItem(101, "relevant", "API 순서 관련 사업"),
    testOrderPlanItem(104, null, "API 순서 값 없음 첫 번째"),
    testOrderPlanItem(103, "not_relevant", "API 순서 비관련 사업"),
    testOrderPlanItem(105, null, "API 순서 값 없음 두 번째"),
  ];
  await mockReorderedOrderPlanList(page, items);
  await page.goto("/order-plans");

  await expect(page.locator(".c2l-list-sort")).toHaveText("정렬 · 관련 → 판단 보류 → 비관련 → 값 없음");
  await clickPreset(page, "전체");

  const rows = page.locator(".c2l-row");
  await expect(rows).toHaveCount(5);
  expect((await rows.locator(".c2l-row-model").allTextContents()).map((label) => label.trim())).toEqual([
    "모델 관련",
    "모델 판단 보류",
    "모델 비관련",
    "Qwen unknown",
    "Qwen unknown",
  ]);

  // null relevance 안에서는 API가 준 104→105 순서가 유지되어 실행 상태를 relevance로
  // 추정하거나 같은 그룹을 제목·점수로 다시 정렬하지 않는다.
  const titles = await rows.locator(".c2l-row-title").allTextContents();
  const stableNullTitles = [
    "API 순서 값 없음 첫 번째",
    "API 순서 값 없음 두 번째",
  ];
  expect(titles.slice(3).map((title) => title.trim())).toEqual(stableNullTitles);

  // URL의 선택 토큰이 uncertain,relevant 순서여도 사람이 보는 우선순위는 고정된다.
  await page.goto("/order-plans?qwen=uncertain,relevant");
  await expect.poll(() => new URL(page.url()).searchParams.get("qwen")).toBe("uncertain,relevant");
  await expect(rows).toHaveCount(2);
  expect((await rows.locator(".c2l-row-model").allTextContents()).map((label) => label.trim())).toEqual(["모델 관련", "모델 판단 보류"]);
  await expect(rows.first()).toContainText("API 순서 관련 사업");
  await expect(rows.nth(1)).toContainText("API 순서 불확실 사업");
});

test("relevance 정렬은 500건 페이지를 자르기 전에 적용되고 페이지 끝 키보드 이동도 이어진다", async ({ page }) => {
  const items = [
    ...Array.from({ length: 200 }, (_, index) => testOrderPlanItem(102 + index, null, `대량 값 없음 ${index + 1}`)),
    ...Array.from({ length: 100 }, (_, index) => testOrderPlanItem(302 + index, "not_relevant", `대량 비관련 ${index + 1}`)),
    ...Array.from({ length: 200 }, (_, index) => testOrderPlanItem(402 + index, "uncertain", `대량 판단 보류 ${index + 1}`)),
    testOrderPlanItem(101, "relevant", "대량 관련 1"),
    ...Array.from({ length: 99 }, (_, index) => testOrderPlanItem(602 + index, "relevant", `대량 관련 ${index + 2}`)),
  ];
  await mockReorderedOrderPlanList(page, items);
  await page.goto("/order-plans");
  await clickPreset(page, "전체");

  await expect(page.locator(".c2l-list-head")).toContainText("현재 필터 결과 600건");
  await expect(page.locator(".c2l-pager")).toContainText("1–500 / 600");
  const rows = page.locator(".c2l-row");
  await expect(rows).toHaveCount(500);
  await expect(rows.first()).toContainText("대량 관련 1");
  await expect(rows.nth(99)).toContainText("대량 관련 100");
  await expect(rows.nth(100)).toContainText("대량 판단 보류 1");
  await expect(rows.nth(399)).toContainText("대량 비관련 100");
  await expect(rows.nth(400)).toContainText("대량 값 없음 1");

  await rows.nth(499).click();
  await expect(rows.nth(499)).toHaveAttribute("aria-current", "true");
  await rows.nth(499).focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator(".c2l-pager")).toContainText("501–600 / 600");
  await expect(rows).toHaveCount(100);
  await expect(rows.first()).toContainText("대량 값 없음 101");
  await expect(rows.first().locator(".c2l-row-model")).toHaveText("Qwen unknown");
});

test("1200건 결과에서 기본 review 필터·실패·거부 필터와 페이지 경계를 전체 모집단 기준으로 계산한다", async ({ page }) => {
  await mockOrderPlans(page, "large");
  await page.goto("/order-plans");

  // 기본(review) 필터는 서버가 돌려준 첫 페이지(500건)가 아니라 전체 1,200건 모집단 위에서
  // relevant를 계산한다: index<900은 relevant, 나머지 300은 Qwen 단계 실패라 900건만 남는다.
  // 페이지 하나만 세는 회귀였다면 이 900이라는 숫자가 나오지 않는다.
  await expect(page.locator(".c2l-row")).toHaveCount(500);
  await expect(page.locator(".c2l-list-head")).toContainText("현재 필터 결과 900건");
  await expect(page.locator(".c2l-pager")).toContainText("1–500 / 900");

  await clickPreset(page, "전체");
  await expect(page.locator(".c2l-row")).toHaveCount(500);
  await expect(page.locator(".c2l-list-head")).toContainText("현재 필터 결과 1,200건");
  await expect(page.locator(".c2l-pager")).toContainText("1–500 / 1,200");
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(500);
  await expect(page.locator(".c2l-pager")).toContainText("501–1,000 / 1,200");

  await clickPreset(page, "실패·거부");
  await expect(page.locator(".c2l-row")).toHaveCount(300);
  await expect(page.locator(".c2l-row").first()).toContainText("대규모 페이지네이션 회귀 발주계획 901");
  await expect(page.locator(".c2l-pager")).toHaveCount(0);
});

test("검토 목록은 고정 높이 안에서 스크롤되고 상세와 같은 높이로 저장 액션을 노출한다", async ({ page }) => {
  await mockOrderPlans(page, "large");
  await page.goto("/order-plans");

  const list = page.locator(".c2l-list-scroll");
  await expect(list).toBeVisible();
  await expect.poll(() => list.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }))).toMatchObject({ clientHeight: expect.any(Number), scrollHeight: expect.any(Number) });

  const scrollMetrics = await list.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  expect(scrollMetrics.scrollHeight).toBeGreaterThan(scrollMetrics.clientHeight);
  await list.evaluate((element) => element.scrollTo({ top: element.scrollHeight, behavior: "instant" }));
  await expect.poll(() => list.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);

  const geometry = await page.locator(".c2l-workspace").evaluate((workspace) => {
    const listPane = workspace.querySelector<HTMLElement>(".c2l-list-pane");
    const detailPane = workspace.querySelector<HTMLElement>(".c2l-detail-pane");
    const actions = workspace.querySelector<HTMLElement>(".c2l-detail-actions");
    const pageRoot = workspace.closest<HTMLElement>(".c2l-page");
    if (!listPane || !detailPane || !actions || !pageRoot) throw new Error("발주계획 목록·상세 영역을 찾을 수 없습니다.");
    const listRect = listPane.getBoundingClientRect();
    const detailRect = detailPane.getBoundingClientRect();
    const actionsRect = actions.getBoundingClientRect();
    const workspaceRect = workspace.getBoundingClientRect();
    const pageRect = pageRoot.getBoundingClientRect();
    return {
      listHeight: listRect.height,
      detailHeight: detailRect.height,
      detailBottom: detailRect.bottom,
      actionsBottom: actionsRect.bottom,
      workspaceBottom: workspaceRect.bottom,
      pageBottom: pageRect.bottom,
    };
  });
  expect(Math.abs(geometry.listHeight - geometry.detailHeight)).toBeLessThanOrEqual(1);
  expect(geometry.actionsBottom).toBeLessThanOrEqual(geometry.detailBottom + 1);
  // WorkspaceFrame owns the remaining canvas height; a short workspace would let the
  // page canvas scroll and hide the decision bar below the first viewport.
  expect(Math.abs(geometry.workspaceBottom - geometry.pageBottom)).toBeLessThanOrEqual(1);

  await page.locator(".c2l-workspace").scrollIntoViewIfNeeded();
  for (const label of ["추적 시작", "보류", "추적 종료", "이번 건 넘기기"]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toBeInViewport();
  }
});

test("사람 판단 수정은 접힌 영역에서 새 revision만 저장하고 추적 상태를 건드리지 않는다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");
  const pathnameBefore = new URL(page.url()).pathname;

  await expect(page.locator(".c2l-row").first()).toContainText("공공데이터 통합");
  await page.locator(".c2l-row").first().click();

  // 사람 판단 수정은 pane 바닥의 결정이 아니라 별도 대화상자다(ADR-0046 결정 5).
  await page.getByRole("button", { name: "사람 판단 수정 열기" }).click();
  await page.getByRole("radiogroup", { name: "사람 relevance 판단" }).getByRole("radio", { name: "uncertain" }).click();
  await page.getByLabel("사람 판단 담당자 이름").fill("Phase4 tester");
  await page.getByRole("button", { name: "새 수정본 저장", exact: true }).click();

  await expect(page.getByText("사람 피드백 수정본을 저장했습니다. 추적 상태는 바뀌지 않았습니다.")).toBeVisible();
  expect(trace.feedbackPosts).toHaveLength(1);
  expect(trace.feedbackPosts[0].body).toMatchObject({
    schema_version: "feedback-create-request.v1",
    producer: "human-review-client",
    consumer: "review-api",
    execution_id: "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010101",
    relevance: "uncertain",
    expected_revision: 1,
  });
  expect(trace.feedbackPosts[0].headers["x-bidops-actor-name"]).toBe("Phase4 tester");

  // 추적 결정 경로로는 아무것도 가지 않았다. 두 결정은 서로 다른 요청이다.
  expect(trace.trackingPatches).toHaveLength(0);
  await expect(page.locator(".c2l-tracking")).toContainText("추적 결정 없음");

  // 페이지 이동 0회이고, 사람 판단 저장은 다음 건으로 이동하지 않는다.
  expect(new URL(page.url()).pathname).toBe(pathnameBefore);
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("공공데이터 통합");
});

// ADR-0046 결정 4·5: 결정 1은 추적 결정이고 사람 판단 수정과 저장 경로를 공유하지 않는다.
// 서버 계약은 아직 없다 — fixture 는 docs/design/order-plan-tracking-contract-request.md §2 의
// wire shape 를 mock 하며 구현 완료의 근거가 아니다.
test("추적 결정은 별도 요청으로 저장되고 선택 즉시 다음 발주계획으로 이동한다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");
  const pathnameBefore = new URL(page.url()).pathname;

  await page.locator(".c2l-row").first().click();
  await expect(page.locator(".c2l-tracking")).toContainText("추적 결정 없음");

  // 사유는 자동으로 고르지 않는다. 사유와 담당자가 모두 있어야 저장 액션이 열린다.
  const start = page.getByRole("button", { name: "추적 시작", exact: true });
  await expect(start).toBeDisabled();
  await expect(page.getByText("선택 사유와 담당자 이름을 입력하면 추적 결정을 기록할 수 있습니다.")).toBeVisible();

  await selectReason(page, "후속 사전규격·공고 확인");
  await expect(start).toBeDisabled();
  await expect(page.getByText("담당자 이름을 입력하면 추적 결정을 기록할 수 있습니다.")).toBeVisible();

  await page.getByLabel("담당자 이름 · 감사 표식").fill("홍길동");
  await expect(start).toBeEnabled();
  await start.click();

  await expect(page.getByText("추적 상태를 계속 추적(으)로 기록했습니다. 다음 발주계획으로 이동합니다.")).toBeVisible();
  expect(trace.trackingPatches).toHaveLength(1);
  expect(trace.trackingPatches[0].opportunityId).toBe(5101);
  expect(trace.trackingPatches[0].body).toMatchObject({
    tracking_status: "계속 추적",
    reason: "후속 사전규격·공고 확인",
  });
  // 한글 담당자 이름은 RFC 5987 로 인코딩해 보낸다(기존 actor header 규칙).
  expect(trace.trackingPatches[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  expect(trace.trackingPatches[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");

  // 사람 판단 수정 경로로는 아무것도 가지 않았다.
  expect(trace.feedbackPosts).toHaveLength(0);

  // 페이지 이동 0회이고 다음 건이 선택된다.
  expect(new URL(page.url()).pathname).toBe(pathnameBefore);
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");
});

// 추적 `종료`는 되돌릴 수 없는 결정이므로 확인 단계를 거쳐야 요청이 나간다. 확인 문구는
// 사전규격(TrackingDecisionControl)·사업 추적(OpportunitiesPage)과 같은 자리에서 만든다.
test("발주계획 추적 종료는 확인 없이는 요청이 나가지 않고 취소하면 초안만 남는다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();
  await selectReason(page, "후속 사전규격·공고 확인");
  await page.getByLabel("담당자 이름 · 감사 표식").fill("홍길동");

  await page.getByRole("button", { name: "추적 종료", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("되돌릴 수 없습니다");
  await expect(dialog).toContainText("종료 · 추적 종료");
  await expect(dialog).toContainText("발주계획 OP-2026-00101");
  await expect(dialog).toContainText("후속 사전규격·공고 확인");
  expect(trace.trackingPatches).toHaveLength(0);

  // 취소하면 요청은 나가지 않고 초안(사유·담당자)은 그대로 남는다.
  await dialog.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(trace.trackingPatches).toHaveLength(0);
  await expect(page.getByLabel("담당자 이름 · 감사 표식")).toHaveValue("홍길동");
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("공공데이터 통합");

  await page.getByRole("button", { name: "추적 종료", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "종료 상태로 저장", exact: true }).click();
  await expect(page.getByText("추적 상태를 종료(으)로 기록했습니다. 다음 발주계획으로 이동합니다.")).toBeVisible();
  expect(trace.trackingPatches).toHaveLength(1);
  expect(trace.trackingPatches[0].body).toMatchObject({ tracking_status: "종료", reason: "후속 사전규격·공고 확인" });
});

// 되돌릴 수 있는 `계속 추적`·`보류`는 확인 단계를 두지 않는다. 확인을 모든 결정에 걸면
// 확인이 뜻을 잃는다.
test("계속 추적과 보류는 확인 단계 없이 그대로 저장된다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();
  await selectReason(page, "후속 사전규격·공고 확인");
  await page.getByLabel("담당자 이름 · 감사 표식").fill("홍길동");

  await page.getByRole("button", { name: "보류", exact: true }).click();
  await expect(page.getByText("추적 상태를 보류(으)로 기록했습니다. 다음 발주계획으로 이동합니다.")).toBeVisible();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(trace.trackingPatches).toHaveLength(1);
});

// P1: 행이 바뀌면 사람 판단 수정 입력이 초기화된다. 초기화 자체는 유지하되 사람이
// 그 사실을 확인한 뒤에만 일어난다.
test("행을 바꾸기 전에 저장하지 않은 사람 판단 입력을 확인하고 취소하면 입력이 남는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  await page.getByRole("button", { name: "사람 판단 수정 열기" }).click();
  await page.getByLabel("memo").fill("아직 저장하지 않은 검토 근거");
  // 대화상자를 닫아도 입력은 화면에 남는다. 사라지는 것은 행을 바꿀 때다.
  await page.keyboard.press("Escape");

  await page.locator(".c2l-row").nth(1).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("다른 발주계획으로 이동합니다");
  // 무엇이 사라지고 무엇이 남는지 화면이 함께 말한다.
  await expect(dialog).toContainText("담당자 이름은 그대로 남습니다");
  await expect(dialog).toContainText("아직 저장하지 않은 검토 근거");

  await dialog.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("공공데이터 통합");
  await page.getByRole("button", { name: "사람 판단 수정 열기" }).click();
  await expect(page.getByLabel("memo")).toHaveValue("아직 저장하지 않은 검토 근거");
  await page.keyboard.press("Escape");

  await page.locator(".c2l-row").nth(1).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "저장하지 않고 이동", exact: true }).click();
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");
  // 초기화되는 것은 입력값이다.
  await page.getByRole("button", { name: "사람 판단 수정 열기" }).click();
  await expect(page.getByLabel("memo")).toHaveValue("");
});

// 필터는 보이는 모집단과 선택된 행을 함께 바꾼다. 같은 확인을 건다.
test("필터를 바꾸기 전에도 저장하지 않은 사람 판단 입력을 확인한다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();
  await page.getByRole("button", { name: "사람 판단 수정 열기" }).click();
  await page.getByLabel("memo").fill("필터 확인용 미저장 입력");
  await page.keyboard.press("Escape");

  await clickPreset(page, "전체");
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(2);
  await page.getByRole("button", { name: "사람 판단 수정 열기" }).click();
  await expect(page.getByLabel("memo")).toHaveValue("필터 확인용 미저장 입력");
  await page.keyboard.press("Escape");

  await clickPreset(page, "전체");
  await page.getByRole("alertdialog").getByRole("button", { name: "저장하지 않고 이동", exact: true }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(9);
});

// route 이동은 사람 판단 입력과 추적 결정 초안을 잃는다. 담당자 이름은 이 탭에 남으므로
// (sessionStorage) 그 이름만 적어 둔 상태는 더 이상 이동을 막지 않는다.
test("화면을 떠나기 전에 저장하지 않은 입력을 화면 다이얼로그로 확인한다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  // 담당자 이름만으로는 잃을 것이 없다. 확인 없이 그대로 이동한다.
  await page.getByLabel("담당자 이름 · 감사 표식").fill("홍길동");
  expect(await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  })).toBe(false);

  await selectReason(page, "후속 사전규격·공고 확인");

  // 브라우저 종료·새로고침은 native 경고만 가능하므로 beforeunload는 그대로다.
  expect(await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  })).toBe(true);

  await page.getByRole("link", { name: "실행 상세 →" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("발주계획 검토 화면을 떠납니다");
  await expect(dialog).toContainText("선택 사유 초안");
  await dialog.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/order-plans");
  await expect(page.getByLabel("담당자 이름 · 감사 표식")).toHaveValue("홍길동");

  await page.getByRole("link", { name: "실행 상세 →" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "저장하지 않고 이동", exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/run-status");
});

test("이번 건 넘기기는 아무것도 저장하지 않고 미선택을 종료로 바꾸지 않는다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  // 담당자 이름 없이도 넘기기는 가능하다. 저장하지 않기 때문이다.
  await page.getByRole("button", { name: "이번 건 넘기기", exact: true }).click();

  await expect(page.getByText("추적 상태를 바꾸지 않고 다음 발주계획으로 이동했습니다. 미선택은 추적 종료가 아닙니다.")).toBeVisible();
  expect(trace.trackingPatches).toHaveLength(0);
  expect(trace.feedbackPosts).toHaveLength(0);
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");
  await expect(page.locator(".c2l-tracking")).toContainText("추적 결정 없음");
});

// 요청안 §7 규칙 2·3. 계약이 없는 현재 서버에서 결정을 눌러도 저장된 것처럼 보이지 않는다.
test("추적 결정 계약이 없으면 계약 미구현으로 표시하고 미선택으로 바꾸지 않는다", async ({ page }) => {
  const trace = await mockOrderPlans(page, "default", { omitTracking: true });
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  const tracking = page.locator(".c2l-tracking");
  await expect(tracking).toContainText("계약 미구현");
  await expect(tracking).not.toContainText("추적 결정 없음");
  // 왜 저장할 수 없는지는 결정 줄 아래 한 문장이 진다(버튼마다 되풀이하지 않는다).
  await expect(page.locator(".c2l-detail-actions")).toContainText("추적 결정을 저장할 서버 계약이 아직 구현되지 않았습니다.");

  for (const label of ["추적 시작", "보류", "추적 종료"]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toBeDisabled();
  }
  // 저장하지 않는 넘기기는 계약이 없어도 쓸 수 있다.
  await expect(page.getByRole("button", { name: "이번 건 넘기기", exact: true })).toBeEnabled();
  expect(trace.trackingPatches).toHaveLength(0);

  // 사람 판단 수정은 계약이 있으므로 계속 저장할 수 있다.
  await page.getByRole("button", { name: "사람 판단 수정 열기" }).click();
  await expect(page.getByLabel("사람 판단 담당자 이름")).toBeVisible();
});

test("소유 사업기회를 확인하지 못하면 저장을 시도하지 않고 다음 건으로도 이동하지 않는다", async ({ page }) => {
  const trace = await mockOrderPlans(page, "no-owning-opportunity");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  const tracking = page.locator(".c2l-tracking");
  await expect(tracking).toContainText("사업기회 미연결");
  await expect(tracking).not.toContainText("추적 결정 없음");
  await expect(page.getByRole("button", { name: "추적 시작", exact: true })).toBeDisabled();
  await expect(page.locator(".c2l-detail-actions")).toContainText("이 발주계획을 소유한 사업기회를 확인하지 못해 추적 결정을 기록할 수 없습니다.");

  expect(trace.trackingPatches).toHaveLength(0);
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("공공데이터 통합");
});

test("filtered_out·not_relevant·unknown·null이 서로 바뀌어 표시되지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await clickPreset(page, "전체");

  const rows = page.locator(".c2l-row");
  await expect(rows).toHaveCount(9);

  // filtered_out(BM25 탈락, 104)과 not_relevant(Qwen 비관련, 103)는 서로 다른 행, 다른 문구다.
  await expect(rows.filter({ hasText: "BM25 탈락" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "모델 비관련" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "BM25 탈락" })).not.toContainText("모델 비관련");

  // unknown(107 · 정보 부족)은 relevance null과 다른 문구로 남아야 하고, not_attempted(104·106)·
  // failed(105)·rejected(108)와도 서로 바뀌어 표시되지 않는다. relevance가 null이라고 이 넷을
  // 전부 같은 문구로 뭉개면 F1 회귀다.
  await expect(rows.filter({ hasText: "Qwen unknown" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "Qwen unknown" })).not.toContainText("모델 비관련");
  await expect(rows.filter({ hasText: "Qwen unknown" })).not.toContainText("Qwen 미시도");
  await expect(rows.filter({ hasText: "Qwen unknown" })).not.toContainText("Qwen 실패");
  await expect(rows.filter({ hasText: "Qwen unknown" })).not.toContainText("Qwen 거부");
  // not_attempted는 104(필터 탈락)와 106(BM25 실패) 두 건이다: 서로 다른 두 건이 같은 stage2
  // 값을 갖는 것은 정상이며, unknown·failed·rejected와 섞이지만 않으면 된다.
  await expect(rows.filter({ hasText: "Qwen 미시도" })).toHaveCount(2);
  await expect(rows.filter({ hasText: "Qwen 실패" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "Qwen 거부" })).toHaveCount(1);

  // 신호 세부 탭에서도 status(stage2_status)와 relevance(null)가 같은 문구로 뭉개지지 않는다.
  await rows.filter({ hasText: "Qwen unknown" }).first().click();
  await page.getByRole("button", { name: "선별 신호와 실행 기록 열기" }).click();
  await expect(page.locator("#c2l-panel-signals")).toContainText("Qwen unknown");
  await expect(page.locator("#c2l-panel-signals")).toContainText("null (값 없음/미적용)");
});

test("실패·결과 없음·중지/비허용 상태를 성공 결과로 바꾸지 않는다", async ({ page }) => {
  await mockOrderPlans(page, "failure");
  await page.goto("/order-plans");
  await expect(page.getByText("검토에 사용할 성공/부분 성공 결과가 없습니다.")).toBeVisible();
  await expect(page.locator(".c2l-execution-empty")).toContainText("실패");

  await mockOrderPlans(page, "no-results");
  await page.goto("/order-plans");
  await expect(page.getByText("C-2 실행 결과가 없습니다.")).toBeVisible();

  await mockOrderPlans(page, "live-disabled");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();
  await page.getByRole("button", { name: "선별 신호와 실행 기록 열기" }).click();
  await page.getByRole("tab", { name: "실행 기록" }).click();
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("정책·모델 연결 비허용");
});

test("크기 조절 가능한 상세 영역: 드래그와 화살표 키로 폭을 조절하고 localStorage에 남긴다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  const separator = page.getByRole("separator", { name: "목록 폭 조절" });
  await expect(separator).toBeVisible();
  await separator.focus();
  const before = await separator.getAttribute("aria-valuenow");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  const after = await separator.getAttribute("aria-valuenow");
  expect(Number(after)).toBeGreaterThan(Number(before));

  const stored = await page.evaluate(() => window.localStorage.getItem("bidops.order-plans.listWidth"));
  expect(Number(stored)).toBe(Number(after));

  await page.reload();
  const separatorAfterReload = page.getByRole("separator", { name: "목록 폭 조절" });
  await expect(separatorAfterReload).toHaveAttribute("aria-valuenow", String(after));

  // `clientX`는 화면에 그려진 좌표이고 aria 값·localStorage는 논리 CSS px이다.
  // 전역 UI zoom이 있어도 두 지원 폭에서 손잡이가 실제 포인터 이동만큼 따라가야 한다.
  for (const width of [1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => window.localStorage.removeItem("bidops.order-plans.listWidth"));
    await page.reload();

    const scaledSeparator = page.getByRole("separator", { name: "목록 폭 조절" });
    const listPane = page.locator(".c2l-list-pane");
    await expect(scaledSeparator).toBeVisible();
    const before = Number(await scaledSeparator.getAttribute("aria-valuenow"));
    const geometry = await Promise.all([
      scaledSeparator.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, left: rect.left };
      }),
      listPane.evaluate((element) => {
        const renderedWidth = element.getBoundingClientRect().width;
        const layoutWidth = element.offsetWidth;
        return { renderedWidth, layoutWidth, scale: renderedWidth / layoutWidth };
      }),
    ]);
    const [pointer, pane] = geometry;
    expect(pane.scale).toBeGreaterThan(0);
    const dragDistance = 36;

    await page.mouse.move(pointer.x, pointer.y);
    await page.mouse.down();
    await page.mouse.move(pointer.x + dragDistance, pointer.y);
    await page.mouse.up();

    const expected = Math.round(before + dragDistance / pane.scale);
    await expect.poll(async () => Number(await scaledSeparator.getAttribute("aria-valuenow"))).toBe(expected);
    const afterLeft = await scaledSeparator.evaluate((element) => element.getBoundingClientRect().left);
    // Layout rounding can move the edge by a fraction of a physical pixel after
    // converting the logical width back through the rendered scale.
    expect(Math.abs(afterLeft - pointer.left - dragDistance)).toBeLessThanOrEqual(2);
  }
});

test("저장된 뷰: 이름 붙여 저장한 조합만 localStorage에 남고 다시 불러와 복원한다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  // 프리셋 어디에도 없는 커스텀 조합을 만든다: BM25 selected AND Qwen not_relevant.
  await clickPreset(page, "전체");
  await openAdvancedFilters(page);
  await page.locator(".c2l-filter-axis", { hasText: "BM25 stage1" }).getByRole("button", { name: "selected", exact: true }).click();
  await page.locator(".c2l-filter-axis", { hasText: "Qwen relevance" }).getByRole("button", { name: "not_relevant" }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(1);

  await page.getByRole("button", { name: "현재 필터를 뷰로 저장" }).click();
  await page.getByLabel("뷰 이름").fill("탈락 확인용");
  await page.getByRole("button", { name: "뷰 저장", exact: true }).click();

  const stored = await page.evaluate(() => window.localStorage.getItem("bidops.order-plans.views"));
  expect(stored).toBeTruthy();
  expect(JSON.parse(stored ?? "[]")).toHaveLength(1);
  expect(JSON.parse(stored ?? "[]")[0]).toMatchObject({ name: "탈락 확인용" });

  // 프리셋 클릭 후에도 저장된 뷰를 다시 골라 복원할 수 있다.
  await clickPreset(page, "검토 대상");
  await expect(page.locator(".c2l-row")).toHaveCount(2);

  await page.getByRole("combobox", { name: "저장된 뷰", exact: true }).click();
  await page.getByRole("option", { name: "탈락 확인용" }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page).toHaveURL(/stage1=selected/);
  await expect(page).toHaveURL(/qwen=not_relevant/);
});

// ADR-0047 이 지원 폭을 1280~1920px 로 좁히면서, 390px 에서 상세가 목록을 덮고
// "← 목록으로" 로 되돌아오던 동작은 없앴다. 그 자리에 반대 불변식을 고정한다:
// 지원 폭 어디에서도 두 pane 이 함께 남고, 행 선택은 상세 pane 만 제자리에서
// 바꾸며 페이지를 이동하지 않는다(PLAN 단계 B).
test("지원 폭 전체에서 목록과 상세 두 pane이 함께 남고 행 선택은 상세만 제자리에서 바꾼다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  const workspace = page.locator('[data-review-primitive="split-workspace"]');
  await expect(workspace).not.toHaveAttribute("data-mobile-view", /.*/);

  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator(".c2l-list-pane"), `${width}px 에서 목록 pane`).toBeVisible();
    await expect(page.locator(".c2l-detail-pane"), `${width}px 에서 상세 pane`).toBeVisible();
  }

  const pathnameBefore = new URL(page.url()).pathname;
  await page.locator(".c2l-row").nth(1).click();
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");
  await expect(page.locator(".c2l-detail-pane")).toContainText("지방공기업");
  // 제자리 pane 교체다. /order-plans/:pk 로 이동하지 않는다.
  expect(new URL(page.url()).pathname).toBe(pathnameBefore);
  await expect(page.locator(".c2l-list-pane")).toBeVisible();
  await expect(page.getByRole("button", { name: "← 목록으로" })).toHaveCount(0);
});

test("사람 피드백 축과 텍스트 검색도 다른 축과 AND로 조합된다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await clickPreset(page, "전체");
  await expect(page.locator(".c2l-row")).toHaveCount(9);

  // 사람 피드백 "있음"은 revision이 있는 101 한 건만 남긴다.
  await openAdvancedFilters(page);
  await page.locator(".c2l-filter-axis", { hasText: "사람 피드백" }).getByRole("button", { name: "있음" }).click();
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("피드백 수정본 1");

  // 필터 초기화 후 텍스트 검색만으로 제목·계획번호를 좁힌다.
  await resetFilters(page);
  await clickPreset(page, "전체");
  // 지우기 단추가 라벨 이름을 품으므로 입력은 role 로만 찾는다. 적용은 Enter 하나다.
  await page.getByRole("textbox", { name: "사업명·발주기관·계획번호 검색" }).fill("지방공기업");
  await page.getByRole("textbox", { name: "사업명·발주기관·계획번호 검색" }).press("Enter");
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("지방공기업");
});

// docs/design/PLAN.md 단계 F 작업 1: 발주계획 상세(사람 relevance·priority·memo
// 저장, 결정 1)도 사전규격 상세·입찰 변경 비교와 같은 골격을 쓴다. 결정 **액션**은
// 요약 헤더에 고정되어 스크롤 위치와 무관하게 첫 화면에서 보이고, 되돌릴 수 없는
// 입력 **form**은 헤더에 올라가지 않는다(단계 F 완료 게이트).
test("발주계획 상세는 결정 액션만 헤더에 고정하고 입력 form은 본문에 둔다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/101");
  await expect(page.getByRole("heading", { level: 2 })).toBeVisible();

  const header = page.locator(".c2-page-header");
  const saveButton = header.getByRole("button", { name: "새 수정본 저장", exact: true });
  await expect(saveButton).toBeInViewport();
  await expect(header.getByRole("button", { name: "사람 판단 입력으로 이동", exact: true })).toBeInViewport();

  // 입력 필드는 헤더가 아니라 본문 열의 패널 안에 있다.
  await expect(header.locator("textarea")).toHaveCount(0);
  await expect(header.getByLabel("담당자 이름")).toHaveCount(0);
  await expect(page.locator(".c2-feedback-panel").getByLabel("담당자 이름")).toHaveCount(1);

  await page.evaluate(() => document.querySelector(".page-canvas")?.scrollTo(0, 999_999));
  await expect(saveButton).toBeInViewport();
});

// 시안 `OrderPlanDetail`은 사람 피드백 수정본 이력과 새 revision 입력을 본문
// 열에 함께 둔다. 지금 저장하려는 값과 직전 revision을 한눈에 대조해야 하기
// 때문이다. 레일은 관측·실행 이력과 연결만 담는다.
test("발주계획 상세 헤더는 상태를 요약하고, revision 이력은 본문 열, 레일은 관측 이력만 담는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/101");

  const header = page.locator(".c2-page-header");
  await expect(header.getByText("최근 실행 부분 성공", { exact: true })).toBeVisible();
  await expect(header.getByText("최근 피드백 수정본 1", { exact: true })).toBeVisible();

  const feedbackPanel = page.locator(".c2-feedback-panel");
  await expect(feedbackPanel.getByRole("heading", { name: "사람 피드백 수정본 이력", exact: true })).toBeVisible();
  await expect(feedbackPanel).toContainText("append-only");

  const rail = page.locator(".detail-skeleton-rail");
  await expect(rail).toHaveAttribute("data-review-primitive", "history-link-rail");
  await expect(rail.getByRole("heading", { name: "관측 history", exact: true })).toBeVisible();
  await expect(rail.getByRole("link", { name: "발주계획 목록 →", exact: true })).toBeVisible();
  // 이력은 본문 열이 소유한다. 레일에 복제하지 않는다.
  await expect(rail.getByRole("heading", { name: "사람 피드백 수정본 이력", exact: true })).toHaveCount(0);
  // 결정 액션(저장 버튼)도 레일에 복제하지 않는다.
  await expect(rail.getByRole("button", { name: /revision 저장/ })).toHaveCount(0);
});

test("발주계획 상세는 viewport 바깥으로 넘치지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/101");
  await expect(page.locator("header.topbar h1")).toHaveText("발주계획 C-2 상세");
  await expect.poll(() => page.evaluate(() => ({
    root: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    canvas: (() => {
      const canvas = document.querySelector<HTMLElement>(".page-canvas");
      return canvas ? canvas.scrollWidth - canvas.clientWidth : 0;
    })(),
  }))).toEqual({ root: 0, canvas: 0 });
});

test("선별 전 수집 회차도 전체 원본을 조회하고 URL의 회차를 새로고침 후 유지한다", async ({ page }) => {
  await mockOrderPlans(page, "no-completed-execution");
  const runId = "91d8c2e4-3f09-4e6a-9bd9-0c2e4e6d0101";
  await page.route("**/api/runs", (route) => route.fulfill({ json: {
    items: [{ kind: "order_plans", run_id: runId, generated_at: "2026-09-07T06:51:55Z",
      window_from: "2026-09-03", window_to: "2026-09-08", timezone: "Asia/Seoul",
      screening_basis: null, status: "collected", superseded_by: null,
      counts: { notices: 0, judgments: 0, reviews: 0, collection: {} } }], total: 1,
  } }));
  await page.goto(`/order-plans?source_run_id=${encodeURIComponent(runId)}`);
  await expect(page.getByText("선별 전 · 수집 데이터 조회", { exact: true })).toBeVisible();
  await expect(page.locator(".c2l-row")).toHaveCount(9);
  await expect(presetTab(page, "전체")).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.locator(".c2l-row")).toHaveCount(9);
  await expect(page).toHaveURL(new RegExp(`source_run_id=${encodeURIComponent(runId)}`));
});

// 사유는 화면이 만들어 내지 않는다. 초기값이 비어 있고, 공백만 적은 `기타`는 사유가 아니다.
test("추적 사유는 초기값이 비어 있고 공백만 있는 직접 입력으로는 저장할 수 없다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();
  await page.getByLabel("담당자 이름 · 감사 표식").fill("홍길동");

  const reason = page.getByRole("combobox", { name: "선택 사유" });
  await expect(reason).toContainText("사유를 선택하세요");
  for (const label of ["추적 시작", "보류", "추적 종료"]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toBeDisabled();
  }
  await expect(page.locator(".c2l-detail-actions")).toContainText("선택 사유를 고르면 추적 결정을 기록할 수 있습니다.");

  // `기타`는 값이 아니라 자유 입력을 여는 표식이다. 공백만으로는 여전히 막힌다.
  await selectReason(page, "기타 · 직접 입력");
  const custom = page.getByLabel("선택 사유 직접 입력");
  await expect(custom).toBeVisible();
  await custom.fill("   ");
  await expect(page.getByRole("button", { name: "추적 시작", exact: true })).toBeDisabled();
  await expect(page.locator(".c2l-detail-actions")).toContainText("선택 사유를 직접 입력하면 추적 결정을 기록할 수 있습니다.");

  // 같은 건 안에서 선택지를 왕복해도 적어 둔 문구는 남는다.
  await custom.fill("기존 사업과의 연계 범위를 사전규격에서 확인");
  await selectReason(page, "예산·시기 추가 확인 필요");
  await expect(page.getByLabel("선택 사유 직접 입력")).toHaveCount(0);
  await selectReason(page, "기타 · 직접 입력");
  await expect(page.getByLabel("선택 사유 직접 입력")).toHaveValue("기존 사업과의 연계 범위를 사전규격에서 확인");

  await page.getByRole("button", { name: "추적 시작", exact: true }).click();
  await expect(page.getByText(/추적 상태를 계속 추적\(으\)로 기록했습니다/)).toBeVisible();
  expect(trace.trackingPatches).toHaveLength(1);
  // 계약에 실리는 것은 `기타`라는 표식이 아니라 사람이 적은 문장이다.
  expect(trace.trackingPatches[0].body).toMatchObject({
    tracking_status: "계속 추적",
    reason: "기존 사업과의 연계 범위를 사전규격에서 확인",
  });

  // 다음 건으로 옮겨 가면 사유는 비고 담당자 이름은 남는다.
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");
  await expect(page.getByRole("combobox", { name: "선택 사유" })).toContainText("사유를 선택하세요");
  await expect(page.getByLabel("담당자 이름 · 감사 표식")).toHaveValue("홍길동");
});

// 마지막 건에서 저장하면 옮겨 갈 다음 건이 없다. 그래도 사유는 비워야 하고, 화면이
// 이동했다고 말해서는 안 된다. 비우지 않으면 방금 저장한 사유가 남아 다음 저장에
// 그대로 실리고 "저장되지 않은 입력" 경고도 계속 뜬다.
test("목록의 마지막 건을 저장하면 사유를 비우고 이동하지 않았다고 밝힌다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");

  // 기본 보기는 두 건이다. 두 번째(마지막) 건을 고른다.
  await expect(page.locator(".c2l-row")).toHaveCount(2);
  await page.locator(".c2l-row").nth(1).click();
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");

  await selectReason(page, "예산·시기 추가 확인 필요");
  await page.getByLabel("담당자 이름 · 감사 표식").fill("홍길동");
  await page.getByRole("button", { name: "보류", exact: true }).click();

  await expect(page.getByText("추적 상태를 보류(으)로 기록했습니다. 현재 목록의 마지막 발주계획이라 이동하지 않습니다.")).toBeVisible();
  await expect(page.getByText(/다음 발주계획으로 이동합니다/)).toHaveCount(0);
  expect(trace.trackingPatches).toHaveLength(1);
  expect(trace.trackingPatches[0].body).toMatchObject({ tracking_status: "보류", reason: "예산·시기 추가 확인 필요" });

  // 선택은 그대로 남고 사유만 비었다. 담당자는 감사 표식이라 남는다.
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");
  await expect(page.getByRole("combobox", { name: "선택 사유" })).toContainText("사유를 선택하세요");
  await expect(page.getByLabel("담당자 이름 · 감사 표식")).toHaveValue("홍길동");
  await expect(page.getByRole("button", { name: "추적 시작", exact: true })).toBeDisabled();

  // 저장이 끝났으므로 화면을 떠나도 "저장되지 않은 입력" 확인이 뜨지 않는다.
  await page.getByRole("link", { name: "실행 상세 →" }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect.poll(() => new URL(page.url()).pathname).toBe("/run-status");
});

// 결정 줄에서 뺀 상태 설명은 사라지지 않고 `실행 상태` 대화상자가 진다.
test("실행 상태 대화상자가 미선택·filtered_out·not_relevant의 뜻을 그대로 보존한다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  // 기본 화면의 결정 줄에는 긴 설명 문단이 없다.
  await expect(page.locator(".c2l-tracking")).not.toContainText("미선택은 추적 종료가 아닙니다");

  await page.getByRole("button", { name: "실행 상태", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("미선택은 추적 종료가 아닙니다.");
  await expect(dialog).toContainText("모델 판단·적합성 등급·참여 준비 상태·최종 Go/No-Go를 바꾸지 않습니다.");
  await expect(dialog).toContainText("filtered_out");
  await expect(dialog).toContainText("not_relevant");
  await expect(dialog).toContainText("unknown");
  await expect(dialog).toContainText("부분 성공");
});

// 결정 줄은 시안처럼 한 가로 줄이다. 버튼마다 다른 높이를 갖거나 줄이 갈라지면
// 어느 버튼이 주 결정인지 화면이 말해 주지 못한다.
test("결정 버튼은 같은 높이의 한 줄이고 비활성 사유는 그 줄 아래 한 번만 나온다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  const layout = await page.locator(".c2l-detail-actions").evaluate((bar) => {
    const buttons = Array.from(bar.querySelectorAll<HTMLElement>(".review-decision-bar-actions button"));
    const hint = bar.querySelector<HTMLElement>(".c2l-decision-hint");
    if (!hint) throw new Error("결정 안내 문장을 찾을 수 없습니다.");
    const rects = buttons.map((button) => button.getBoundingClientRect());
    return {
      count: buttons.length,
      tops: rects.map((rect) => Math.round(rect.top)),
      heights: rects.map((rect) => Math.round(rect.height)),
      primaryWidth: Math.round(rects[0].width),
      secondaryWidth: Math.round(rects[1].width),
      hintTop: Math.round(hint.getBoundingClientRect().top),
      buttonsBottom: Math.round(Math.max(...rects.map((rect) => rect.bottom))),
    };
  });
  expect(layout.count).toBe(4);
  expect(new Set(layout.tops).size).toBe(1);
  expect(new Set(layout.heights).size).toBe(1);
  // 주 결정은 남는 폭을 차지하고 나머지는 최소 폭이다.
  expect(layout.primaryWidth).toBeGreaterThan(layout.secondaryWidth);
  // 공통 비활성 사유는 버튼 줄 아래 한 줄이다.
  expect(layout.hintTop).toBeGreaterThanOrEqual(layout.buttonsBottom);
  await expect(page.getByText("선택 사유와 담당자 이름을 입력하면 추적 결정을 기록할 수 있습니다.", { exact: true })).toHaveCount(1);
});

// ─────────────────────────────────────────────────────────────────────────
// 목록 키보드 이동 · 추적 시작 간편화 (계획서 §4·§5·§7)
// ─────────────────────────────────────────────────────────────────────────

// 목록은 한 손으로 훑는 자리다. ↑↓가 선택·초점·URL을 함께 옮기지 않으면 사람이 매번
// 마우스로 돌아가야 하고, 그 순간 검토 속도가 마우스 이동 거리에 묶인다.
test("검토 목록에서 ↑↓로 행을 옮기면 선택·초점·URL이 함께 따라간다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  const rows = page.locator(".c2l-row");
  await expect(rows).toHaveCount(2);
  await rows.first().focus();
  await expect(rows.first()).toHaveAttribute("aria-current", "true");

  await page.keyboard.press("ArrowDown");
  await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");
  await expect.poll(() => new URL(page.url()).searchParams.get("selected")).toBe("102");
  expect(await rows.nth(1).evaluate((row) => row === document.activeElement)).toBe(true);
  await expect(page.locator(".c2l-detail-pane")).toContainText("지방공기업");

  await page.keyboard.press("ArrowUp");
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
  await expect.poll(() => new URL(page.url()).searchParams.get("selected")).toBe("101");
  expect(await rows.first().evaluate((row) => row === document.activeElement)).toBe(true);

  // 목록 밖(상세 pane)의 방향키는 목록을 움직이지 않는다. 리스너가 목록 컨테이너에만 있다.
  await page.getByLabel("담당자 이름 · 감사 표식").focus();
  await page.keyboard.press("ArrowDown");
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
});

// 페이지 경계는 hook이 모른다(화면만 offset을 안다). ↓가 페이지 끝에서 멈추면 500건마다
// 사람이 `다음` 버튼을 찾아 마우스로 돌아가야 한다.
test("페이지 끝에서 ↓를 누르면 다음 페이지 첫 행으로 이어진다", async ({ page }) => {
  await mockOrderPlans(page, "large");
  await page.goto("/order-plans");
  await clickPreset(page, "전체");
  // 보기 전환이 URL에 반영된 뒤에 행을 고른다. 두 조작이 겹치면 나중 것이 앞의 선택을 덮는다.
  await expect(page.locator(".c2l-list-head")).toContainText("현재 필터 결과 1,200건");

  const rows = page.locator(".c2l-row");
  await expect(rows).toHaveCount(500);
  await rows.nth(499).click();
  // 선택이 실제로 옮겨진 뒤에 눌러야 한다 — 이동은 URL(선택)이 정본이고 키 입력은 그 위에서 센다.
  await expect(rows.nth(499)).toHaveAttribute("aria-current", "true");
  await rows.nth(499).focus();
  await page.keyboard.press("ArrowDown");

  await expect(page.locator(".c2l-pager")).toContainText("501–1,000 / 1,200");
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
  expect(await rows.first().evaluate((row) => row === document.activeElement)).toBe(true);
});

// ↑↓도 행을 바꾸는 조작이다. 마우스 클릭과 다른 문을 열어 두면 저장하지 않은 입력이
// 키보드로만 조용히 사라진다.
test("저장하지 않은 사유가 있으면 ↓ 이동도 확인을 거치고 취소하면 선택이 남는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  const rows = page.locator(".c2l-row");
  await rows.first().click();
  await selectReason(page, "예산·시기 추가 확인 필요");

  await rows.first().focus();
  await page.keyboard.press("ArrowDown");
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("다른 발주계획으로 이동합니다");

  await page.keyboard.press("Escape");
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("combobox", { name: "선택 사유" })).toContainText("예산·시기 추가 확인 필요");
});

// BM25 `선정`은 거의 모든 행에 붙는 기본값이라 배지로 그리면 아무것도 구분하지 못한다.
// 숨기는 것은 그 하나뿐이고 탈락·실패·거부·null은 그대로 보인다.
test("행 배지는 모델 판단을 우상단에 두고 BM25 선정만 감춘다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  const first = page.locator(".c2l-row").first();
  await expect(first.locator(".c2l-row-head .astryx-badge")).toHaveText("모델 관련");
  await expect(first.locator(".c2l-row-badges")).not.toContainText("BM25");
  // 사람 피드백이 있는 행은 그 사실만 배지 줄에 남는다.
  await expect(first.locator(".c2l-row-badges")).toHaveText("피드백 수정본 1");
  // 그릴 배지가 하나도 없으면 줄 자체를 만들지 않는다(빈 줄이 행 높이를 흔든다).
  await expect(page.locator(".c2l-row").nth(1).locator(".c2l-row-badges")).toHaveCount(0);

  // 모델 배지는 제목의 **첫 줄**에 붙는다. 제목이 두 줄로 잘려도 아래로 밀리지 않는다.
  const geometry = await first.evaluate((row) => {
    const title = row.querySelector<HTMLElement>(".c2l-row-title");
    const badge = row.querySelector<HTMLElement>(".c2l-row-head .astryx-badge");
    if (!title || !badge) throw new Error("행의 제목·모델 배지를 찾을 수 없습니다.");
    const titleRect = title.getBoundingClientRect();
    const badgeRect = badge.getBoundingClientRect();
    return {
      titleTop: titleRect.top,
      titleLines: titleRect.height,
      badgeTop: badgeRect.top,
      badgeRight: badgeRect.right,
      titleRight: titleRect.right,
    };
  });
  // 첫 줄 안이다: 두 줄짜리 제목의 둘째 줄로 내려가면 이 차이가 줄 높이만큼 벌어진다.
  expect(geometry.badgeTop - geometry.titleTop).toBeLessThan(geometry.titleLines / 2);
  expect(geometry.badgeTop - geometry.titleTop).toBeGreaterThan(-12);
  // 배지는 행 오른쪽 끝, 제목은 그 왼쪽이다.
  expect(geometry.badgeRight).toBeGreaterThan(geometry.titleRight);

  // 예외(탈락)는 그대로 배지로 남는다.
  await clickPreset(page, "BM25 탈락");
  await expect(page.locator(".c2l-row .c2l-row-badges")).toContainText("BM25 탈락");
});

// 방안 1의 한 손 동선: [↓] → [직전 사유 다시 쓰기] → [Ctrl+Enter]. 준비되지 않은 상태에서
// 한 키가 사유를 지어내면 감사 기록이 사람의 판단이 아니게 되므로, 그때는 안내만 한다.
test("목록 행의 Ctrl+Enter는 준비됐을 때만 추적을 시작한다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");

  const rows = page.locator(".c2l-row");
  await rows.first().focus();
  await page.keyboard.press("Control+Enter");

  await expect(page.getByText("사유와 담당자를 입력하면 Ctrl+Enter로 추적을 시작합니다.")).toBeVisible();
  expect(trace.trackingPatches).toHaveLength(0);
  // 무엇이 비었는지 말하고 그 자리로 초점을 옮긴다. 값은 채우지 않는다.
  await expect(page.getByRole("combobox", { name: "선택 사유" })).toBeFocused();
  await expect(page.getByRole("combobox", { name: "선택 사유" })).toContainText("사유를 선택하세요");

  await selectReason(page, "후속 사전규격·공고 확인");
  await page.getByLabel("담당자 이름 · 감사 표식").fill("홍길동");
  await rows.first().focus();
  await page.keyboard.press("Control+Enter");

  await expect(page.getByText("추적 상태를 계속 추적(으)로 기록했습니다. 다음 발주계획으로 이동합니다.")).toBeVisible();
  expect(trace.trackingPatches).toHaveLength(1);
  expect(trace.trackingPatches[0].body).toMatchObject({ tracking_status: "계속 추적", reason: "후속 사전규격·공고 확인" });
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");
});

// 사유는 건마다 다시 고르는 값이라 저장에 성공하면 비운다(PRD §3.3). 그래도 연속 검토에서
// 같은 사유를 손으로 다시 고르는 일이 잦으므로 **사람이 누를 때에만** 채우는 지름길을 둔다.
test("저장한 뒤에는 직전 사유를 한 번에 다시 쓸 수 있다", async ({ page }) => {
  const trace = await mockOrderPlans(page);
  await page.goto("/order-plans");

  await page.locator(".c2l-row").first().click();
  await selectReason(page, "후속 사전규격·공고 확인");
  await page.getByLabel("담당자 이름 · 감사 표식").fill("홍길동");
  await page.getByRole("button", { name: "추적 시작", exact: true }).click();
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("지방공기업");

  // 드롭다운은 여전히 빈 값에서 시작한다. 다시 쓰기는 단추 하나로만 열린다.
  await expect(page.getByRole("combobox", { name: "선택 사유" })).toContainText("사유를 선택하세요");
  const reuse = page.getByRole("button", { name: "직전 사유 다시 쓰기 · 후속 사전규격·공고 확인" });
  await expect(reuse).toBeVisible();
  await reuse.click();
  await expect(page.getByRole("combobox", { name: "선택 사유" })).toContainText("후속 사전규격·공고 확인");
  await expect(reuse).toHaveCount(0);

  expect(await page.evaluate(() => window.sessionStorage.getItem("bidops.order-plans.lastTrackingReason")))
    .toBe("후속 사전규격·공고 확인");
  expect(trace.trackingPatches).toHaveLength(1);
});

// 담당자 이름은 감사 표식이고 여러 건에 다시 쓰는 값이다. 탭 세션 동안만 남으며
// (localStorage가 아니다) 인증도 계정도 아니다.
test("담당자 이름은 새로고침 뒤에도 이 탭에 남는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();

  await page.getByLabel("담당자 이름 · 감사 표식").fill("홍길동");
  expect(await page.evaluate(() => window.sessionStorage.getItem("bidops.order-plans.trackingActor"))).toBe("홍길동");

  await page.reload();
  await expect(page.getByLabel("담당자 이름 · 감사 표식")).toHaveValue("홍길동");
});
