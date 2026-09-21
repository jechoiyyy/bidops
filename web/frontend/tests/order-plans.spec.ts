import { expect, test } from "@playwright/test";
import { mockApi, mockOrderPlanBulkTracking, mockOrderPlans } from "./api-mock";
import {
  ApiError,
  OrderPlanBulkTrackingResultUnconfirmedError,
  parseOrderPlanBulkPreviewResponse,
  parseOrderPlanBulkStartResponse,
} from "../src/lib/api";
import {
  describeOrderPlanBulkTrackingError,
  parseOrderPlanBulkTrackingError,
} from "../src/lib/apiErrors";
import type {
  OrderPlanBulkPreviewResponse,
  OrderPlanBulkStartResponse,
} from "../src/lib/types";

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
/** 공용 mock의 최신 완료 운영 실행(부분 성공)과 그보다 앞선 성공 실행. */
const TEST_LATEST_EXECUTION_ID = "a2f4d7c1-0a61-4a07-8d2e-7f1d1d010101";
const TEST_OLDER_EXECUTION_ID = "a2f4d7c1-0a61-4a07-8d2e-7f1d1d083101";

function testOrderPlanItem(orderPlanPk: number, relevance: "relevant" | "uncertain" | "not_relevant" | null, title: string) {
  return {
    order_plan_pk: orderPlanPk,
    order_plan_unty_no: `OP-TEST-${String(orderPlanPk).padStart(5, "0")}`,
    source_url: `https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=OP-TEST-${String(orderPlanPk).padStart(5, "0")}`,
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
      tracking_status: "미선택" as "미선택" | "계속 추적" | "보류" | "종료",
      tracking_reason: null,
      tracking_selected_by: null,
      tracking_selected_at: null,
    },
    // v4: 그 행의 결과를 낸 실행과 policy, 발주계획의 첫 관측 시각.
    execution_id: relevance === null ? null as string | null : TEST_LATEST_EXECUTION_ID,
    policy_version: relevance === null ? null as string | null : "c2-policy.v1",
    first_observed_at: "2026-08-31T16:30:00Z" as string | null,
  };
}

/** The browser fetches all pages, so this keeps API order deliberately different from relevance order. */
async function mockReorderedOrderPlanList(
  page: import("@playwright/test").Page,
  items: ReturnType<typeof testOrderPlanItem>[],
) {
  const trace = await mockOrderPlans(page);
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
        schema_version: "order-plan-list-response.v4",
        producer: "order-plan-review-api",
        consumer: "order-plan-review-client",
        scope: { mode: "cumulative", policy_versions: ["c2-policy.v1"], activated_policy_versions: ["c2-policy.v1"] },
        items: items.slice(offset, offset + limit),
        total: items.length,
        limit,
        offset,
      }),
    });
  });
  return trace;
}

// 화면 제목은 `발주계획` 한 낱말이고(승인 시안), 목록 행은 사업명 → 상태 배지 → metadata(발주기관·
// 예산·시기) 차례를 그대로 지킨다. 발주기관은 자리를 옮기지 않고 크기만
// 보조 글자에서 본문 굵은 글자로 키운다.
test("기본 목록은 밀집 행이고 판정에 필요한 값만 담으며, 신호 세부·실행 기록은 별도 대화상자에 남는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  // 화면 제목은 상단바의 h1 하나다. 페이지는 같은 이름을 다시 그리지 않는다(제목 모드).
  await expect(page.locator("header.topbar h1")).toHaveText("발주계획");
  // ADR-0062 ⓓ — 회차 선택은 상단바가 아니라 필터 아래 줄(사전규격과 같은 자리)이다.
  await expect(page.locator("header.topbar").getByRole("combobox", { name: "수집 회차" })).toHaveCount(0);
  await expect(page.locator(".c2l-filter-tools").getByRole("combobox", { name: "수집 회차" })).toBeVisible();
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
  await expect(firstRow.locator(".c2l-row-agency")).toHaveText("서울특별시 디지털정책관");
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
  // ADR-0062 ⓒ — 목록 글자는 사전규격과 같다: 사업명과 발주기관이 같은 크기
  // (본문 +2px)이고 굵기만 다르다.
  expect(geometry.titleFontSize).toBeCloseTo(geometry.agencyFontSize, 1);
  expect(geometry.titleWeight).toBeGreaterThanOrEqual(600);
  expect(geometry.agencyFontSize).toBeGreaterThan(12.6);
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

  // 기존 머리글이 제공하던 동선. 회차 선택만 필터 아래 줄로 내려갔고(ADR-0062 ⓓ)
  // 실행 상태 표시·실행 상세 링크는 그대로 상단바 슬롯에 남는다.
  await expect(actions.getByRole("combobox", { name: "수집 회차" })).toHaveCount(0);
  await expect(page.locator(".c2l-filter-tools").getByRole("combobox", { name: "수집 회차" })).toHaveCount(1);
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

  const sourceLink = page.locator(".c2l-detail-scroll").getByRole("link", { name: "공고 바로가기", exact: true });
  await expect(sourceLink).toBeVisible();
  await expect(sourceLink).toHaveAttribute("href", "https://www.g2b.go.kr/link/PRPA015_01/single/?oderPlanNo=OP-2026-00101");
  await expect(sourceLink).toHaveAttribute("target", "_blank");
  await expect(sourceLink).toHaveAttribute("rel", "noopener noreferrer");

  // 발주기관은 상세에서 라벨과 함께 강조 영역으로 먼저 읽힌다.
  const head = page.locator(".c2l-detail-head");
  await expect(head.locator(".c2l-agency-label")).toHaveText("발주기관");
  await expect(head.locator(".c2l-agency-name")).toHaveText("서울특별시 디지털정책관");

  // 전역 zoom 때의 물리 크기: 사업명 18px, 발주기관 12.6px 굵게.
  const type = await page.locator(".c2l-detail-pane").evaluate((pane) => {
    const size = (selector: string) => {
      const element = pane.querySelector<HTMLElement>(selector);
      if (!element) throw new Error(`${selector} 를 찾을 수 없습니다.`);
      return { fontSize: Number.parseFloat(getComputedStyle(element).fontSize), weight: Number(getComputedStyle(element).fontWeight) };
    };
    return { title: size("h4"), agency: size(".c2l-agency-name"), body: size(".c2l-evidence-body") };
  });
  expect(type.title.fontSize).toBe(18);
  expect(type.agency.fontSize).toBe(12.6);
  expect(type.agency.weight).toBeGreaterThanOrEqual(600);
  expect(type.body.fontSize).toBe(12.6);
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

  // 정렬 설명 줄은 지웠다 — 행마다 관련도 표식이 있어 순서가 자명하다(2026-09-21).
  // 실제 순서는 아래에서 행으로 검증한다.
  await expect(page.locator(".c2l-list-sort")).toHaveCount(0);
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
  // B3(0920 검수): 페이저 줄은 한 페이지뿐이어도 "전체 N건"과 범위를 보이며,
  // 이전/다음만 비활성이다(더 이상 여러 페이지일 때만 나타나지 않는다).
  await expect(page.locator(".c2l-pager")).toContainText("전체 300건");
  await expect(page.locator(".c2l-pager")).toContainText("1–300 / 300");
  await expect(page.getByRole("button", { name: "이전", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "다음", exact: true })).toBeDisabled();
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
  // 기본 보기는 추적 `미선택`만 보인다. 추적 계약이 없는 행은 미선택이 아니므로 관련도 축만 건다.
  await page.goto("/order-plans?qwen=relevant,uncertain");
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
  // 소유 사업기회가 없는 행은 추적 `미선택`이 아니라 기본 보기에 없다. 관련도 축만 건다.
  await page.goto("/order-plans?qwen=relevant,uncertain");
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
  // 누적 범위에 판정이 없으면 원본을 그대로 보이고, 실패한 실행을 성공처럼 말하지 않는다.
  await mockOrderPlans(page, "failure");
  await page.goto("/order-plans");
  const noJudgment = page.getByRole("status").filter({ hasText: "누적 판정 없음 · 수집 데이터 조회" });
  await expect(noJudgment).toBeVisible();
  await expect(noJudgment).toContainText("최근 운영 실행: 실패 (a2f4d7c1)");
  await expect(page.locator(".c2l-row")).toHaveCount(9);
  await expect(page.locator(".c2l-row").first().locator(".c2l-row-verdict")).toContainText("판정 없음");
  await expect(page.getByTestId("order-plan-list-scope")).toContainText("누적 · 판정 policy 없음");

  // 한 번도 활성화되지 않은 policy의 운영 목적 실행(참조 실행)은 누적 범위 밖이다.
  // 배너는 그것을 "최근 운영 실행"으로 적지 않는다 — 참조 실행을 운영 결과로 말하지 않는다.
  await mockOrderPlans(page, "failure", { activatedPolicyVersions: [] });
  await page.goto("/order-plans");
  const neverActivated = page.getByRole("status").filter({ hasText: "누적 판정 없음 · 수집 데이터 조회" });
  await expect(neverActivated).toBeVisible();
  await expect(neverActivated).not.toContainText("최근 운영 실행");

  await mockOrderPlans(page, "no-results");
  await page.goto("/order-plans");
  await expect(page.getByText("누적 판정 없음 · 수집 데이터 조회", { exact: true })).toBeVisible();
  await expect(page.locator(".c2l-list-pane").getByText("조건에 맞는 계획이 없습니다")).toBeVisible();

  await mockOrderPlans(page, "live-disabled");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();
  await page.getByRole("button", { name: "선별 신호와 실행 기록 열기" }).click();
  await page.getByRole("tab", { name: "실행 기록" }).click();
  await expect(page.locator("#c2l-panel-telemetry")).toContainText("정책·모델 연결 비허용");
});

// ADR-0062 ⓐ — 목록 폭 드래그 리사이저는 제거했다(38% 고정, 사전규격과 같은 값).
// 폭을 기억하던 localStorage 키도 더 쓰지 않는다.
test("목록 폭은 두 지원 폭에서 38% 고정이고 폭 조절 손잡이가 없다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  await expect(page.getByRole("separator", { name: "목록 폭 조절" })).toHaveCount(0);

  for (const width of [1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.reload();
    const ratio = await page.locator(".c2l-workspace").evaluate((workspace) => {
      const listPane = workspace.querySelector<HTMLElement>(".c2l-list-pane")!;
      return listPane.getBoundingClientRect().width / workspace.getBoundingClientRect().width;
    });
    expect(ratio, `${width}px 목록 pane 비율`).toBeCloseTo(0.38, 2);
    expect(await page.evaluate(() => window.localStorage.getItem("bidops.order-plans.listWidth"))).toBeNull();
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

test("legacy 발주계획 URL은 누적 목록의 선택 행으로 들어간다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/101");

  await expect(page).toHaveURL(/\/order-plans\?.*selected=101/);
  // 누적 목록 안에서 그 행을 고른다. 회차를 골라 URL에 박지 않는다.
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("공공데이터 통합");
  expect(new URL(page.url()).searchParams.has("source_run_id")).toBe(false);
  await expect(page.locator("header.topbar h1")).toHaveText("발주계획");
  await expect(page.locator(".c2l-page-header")).toHaveCount(0);
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("공공데이터 통합");
  await expect(page.locator(".c2l-detail-pane")).toContainText("공공데이터 통합");
  await expect(page.getByRole("link", { name: "전체 상세 열기", exact: true })).toHaveCount(0);
});

test("legacy URL은 필터에 가려진 not_relevant 대상의 선택을 보존한다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/103?qwen=relevant");

  await expect(page).toHaveURL(/\/order-plans\?.*selected=103/);
  await expect.poll(() => new URL(page.url()).searchParams.get("qwen")).toBe("");
  expect(new URL(page.url()).searchParams.has("source_run_id")).toBe(false);
  await expect(page.locator(".c2l-row-wrap.is-selected")).toContainText("시설관리 용역");
  await expect(page.locator(".c2l-detail-pane")).toContainText("시설관리 용역");
});

test("legacy URL의 알 수 없는 발주계획은 첫 행으로 대체하지 않는다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans/9999");

  await expect(page).toHaveURL(/\/order-plans\?.*selected=9999/);
  await expect(page.getByText("요청한 발주계획을 누적 목록에서 찾을 수 없습니다.", { exact: true })).toBeVisible();
  await expect(page.locator(".c2l-row-wrap.is-selected")).toHaveCount(0);
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
test("행 배지는 모델 판단을 상태 칩 줄에 두고 BM25 선정만 감춘다", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");

  const first = page.locator(".c2l-row").first();
  // ADR-0062 — 모델 판단 배지는 사전규격 행과 같이 상태 칩 줄에 있다.
  await expect(first.locator(".c2l-row-state .c2l-row-model")).toHaveText("모델 관련");
  await expect(first.locator(".c2l-row-badges")).not.toContainText("BM25");
  // 사람 피드백이 있는 행은 그 사실만 배지 줄에 남는다.
  await expect(first.locator(".c2l-row-badges")).toHaveText("피드백 수정본 1");
  // 그릴 배지가 하나도 없으면 줄 자체를 만들지 않는다(빈 줄이 행 높이를 흔든다).
  await expect(page.locator(".c2l-row").nth(1).locator(".c2l-row-badges")).toHaveCount(0);

  // ADR-0062 — 행의 차례는 사업명 → 발주기관 → metadata → 상태 칩이고, 발주 예정은
  // 오른쪽 열이다(사전규격 행과 같다).
  const geometry = await first.evaluate((row) => {
    const box = (selector: string) => {
      const element = row.querySelector<HTMLElement>(selector);
      if (!element) throw new Error(`${selector} 를 찾을 수 없습니다.`);
      return element.getBoundingClientRect();
    };
    const title = box(".c2l-row-title");
    const agency = box(".c2l-row-agency");
    const meta = box(".c2l-row-meta");
    const badge = box(".c2l-row-state .c2l-row-model");
    const planned = box(".c2l-row-planned");
    return {
      titleTop: title.top,
      agencyTop: agency.top,
      metaTop: meta.top,
      badgeTop: badge.top,
      badgeLeft: badge.left,
      titleLeft: title.left,
      plannedLeft: planned.left,
      titleRight: title.right,
    };
  });
  expect(geometry.titleTop).toBeLessThan(geometry.agencyTop);
  expect(geometry.agencyTop).toBeLessThan(geometry.metaTop);
  expect(geometry.metaTop).toBeLessThan(geometry.badgeTop);
  // 상태 칩 줄은 왼쪽 열 안에서 시작한다(제목과 같은 왼쪽 정렬).
  expect(Math.abs(geometry.badgeLeft - geometry.titleLeft)).toBeLessThanOrEqual(2);
  // 발주 예정은 오른쪽 열이다.
  expect(geometry.plannedLeft).toBeGreaterThan(geometry.titleRight);

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

const BT_REQUEST_ID = "7a9c9b7a-0c11-4a5e-9f34-000000000001";
const BT_AUDIT_ID = "f2f4d7c1-0a61-4f07-8d2e-000000000001";
const BT_IDS = [10, 20, 30, 40, 50] as const;

function bulkPreviewFixture(): OrderPlanBulkPreviewResponse {
  return {
    schema_version: "order-plan-bulk-preview-response.v1",
    selected_plan_count: 5,
    unique_owner_count: 3,
    eligible_plan_count: 2,
    eligible_owner_count: 1,
    excluded_by_status: {
      "계속 추적": { plan_count: 0, owner_count: 0 },
      "보류": { plan_count: 1, owner_count: 1 },
      "종료": { plan_count: 1, owner_count: 1 },
    },
    failure_plan_count: 1,
    items: [
      { order_plan_id: 10, opportunity_id: 100, tracking_status: "미선택", eligibility: "eligible", code: null },
      { order_plan_id: 20, opportunity_id: 100, tracking_status: "미선택", eligibility: "eligible", code: null },
      { order_plan_id: 30, opportunity_id: 200, tracking_status: "보류", eligibility: "excluded", code: null },
      { order_plan_id: 40, opportunity_id: 300, tracking_status: "종료", eligibility: "excluded", code: null },
      { order_plan_id: 50, opportunity_id: null, tracking_status: null, eligibility: "failed", code: "order_plan_not_found" },
    ],
  };
}

function bulkReceiptFixture(): OrderPlanBulkStartResponse {
  return {
    schema_version: "order-plan-bulk-start-response.v1",
    request_id: BT_REQUEST_ID,
    completed_at: "2026-09-02T01:00:00.123456+09:00",
    items: [
      { order_plan_id: 10, opportunity_id: 100, outcome: "succeeded", status_at_decision: "계속 추적", code: null, audit_event_id: BT_AUDIT_ID },
      { order_plan_id: 20, opportunity_id: 100, outcome: "succeeded", status_at_decision: "계속 추적", code: null, audit_event_id: BT_AUDIT_ID },
      { order_plan_id: 30, opportunity_id: 200, outcome: "excluded", status_at_decision: "보류", code: null, audit_event_id: null },
      { order_plan_id: 40, opportunity_id: 300, outcome: "excluded", status_at_decision: "종료", code: null, audit_event_id: null },
      { order_plan_id: 50, opportunity_id: null, outcome: "failed", status_at_decision: null, code: "order_plan_not_found", audit_event_id: null },
    ],
    summary: {
      selected_plan_count: 5,
      unique_owner_count: 3,
      succeeded_plan_count: 2,
      succeeded_owner_count: 1,
      excluded_plan_count: 2,
      excluded_by_status: {
        "계속 추적": { plan_count: 0, owner_count: 0 },
        "보류": { plan_count: 1, owner_count: 1 },
        "종료": { plan_count: 1, owner_count: 1 },
      },
      failed_plan_count: 1,
    },
  };
}

function expectUnconfirmed(run: () => unknown) {
  expect(run).toThrow(OrderPlanBulkTrackingResultUnconfirmedError);
}

test("BT-client-valid-mixed-receipt-preserves-UUID-aware-microsecond-values", () => {
  const parsed = parseOrderPlanBulkStartResponse(
    bulkReceiptFixture(),
    [50, 10, 20, 10, 40, 30],
    BT_REQUEST_ID,
  );

  expect(parsed.request_id).toBe(BT_REQUEST_ID);
  expect(parsed.completed_at).toBe("2026-09-02T01:00:00.123456+09:00");
  expect(parsed.items.map((item) => item.order_plan_id)).toEqual([...BT_IDS]);
  expect(parsed.items[0].audit_event_id).toBe(BT_AUDIT_ID);
  expect(parsed.items[1].audit_event_id).toBe(BT_AUDIT_ID);
  expect(parsed.items[4].opportunity_id).toBeNull();
  expect(parsed.items[4].status_at_decision).toBeNull();
  expect(parsed.items[4].audit_event_id).toBeNull();
});

test("BT-client-duplicate-requested-IDs-normalize-before-set-and-order-check", () => {
  const parsed = parseOrderPlanBulkPreviewResponse(
    bulkPreviewFixture(),
    [40, 10, 20, 10, 30, 50],
  );

  expect(parsed.items.map((item) => item.order_plan_id)).toEqual([...BT_IDS]);
  expect(parsed.selected_plan_count).toBe(new Set([40, 10, 20, 30, 50]).size);
  expect(parsed.items.filter((item) => item.eligibility === "eligible")).toHaveLength(2);
});

test("BT-client-response-order-must-match-exact-requested-ID-set", () => {
  const reversed = {
    ...bulkReceiptFixture(),
    items: [...bulkReceiptFixture().items].reverse(),
  };
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse(reversed, BT_IDS, BT_REQUEST_ID));

  const missing = {
    ...bulkPreviewFixture(),
    items: bulkPreviewFixture().items.slice(0, 4),
  };
  expectUnconfirmed(() => parseOrderPlanBulkPreviewResponse(missing, BT_IDS));

  const unexpectedId = {
    ...bulkReceiptFixture(),
    items: bulkReceiptFixture().items.map((item, index) => index === 4
      ? { ...item, order_plan_id: 999 }
      : item),
  };
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse(unexpectedId, BT_IDS, BT_REQUEST_ID));
});

test("BT-client-unknown-extra-and-missing-fields-fail-closed", () => {
  const preview = bulkPreviewFixture();
  expectUnconfirmed(() => parseOrderPlanBulkPreviewResponse({ ...preview, private_debug: true }, BT_IDS));

  const firstItem = preview.items[0];
  const { code: _removed, ...missingItemCode } = firstItem;
  expectUnconfirmed(() => parseOrderPlanBulkPreviewResponse({
    ...preview,
    items: [missingItemCode, ...preview.items.slice(1)],
  }, BT_IDS));

  const receipt = bulkReceiptFixture();
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...receipt,
    items: receipt.items.map((item, index) => index === 0 ? { ...item, private_debug: true } : item),
  }, BT_IDS, BT_REQUEST_ID));
});

test("BT-client-nullable-fields-are-only-valid-for-failure-results", () => {
  const receipt = bulkReceiptFixture();
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...receipt,
    items: receipt.items.map((item, index) => index === 0
      ? { ...item, opportunity_id: null, status_at_decision: null }
      : item),
  }, BT_IDS, BT_REQUEST_ID));

  const preview = bulkPreviewFixture();
  expectUnconfirmed(() => parseOrderPlanBulkPreviewResponse({
    ...preview,
    items: preview.items.map((item, index) => index === 0
      ? { ...item, opportunity_id: null, tracking_status: null }
      : item),
  }, BT_IDS));
});

test("BT-client-wrong-types-booleans-and-unknown-enums-fail-closed", () => {
  const preview = bulkPreviewFixture();
  expectUnconfirmed(() => parseOrderPlanBulkPreviewResponse({
    ...preview,
    selected_plan_count: true,
  }, BT_IDS));
  expectUnconfirmed(() => parseOrderPlanBulkPreviewResponse({
    ...preview,
    items: preview.items.map((item, index) => index === 0
      ? { ...item, opportunity_id: true }
      : item),
  }, BT_IDS));
  expectUnconfirmed(() => parseOrderPlanBulkPreviewResponse({
    ...preview,
    items: preview.items.map((item, index) => index === 2
      ? { ...item, eligibility: "unknown" }
      : item),
  }, BT_IDS));
});

test("BT-client-unsafe-integer-PK-and-count-values-fail-closed", () => {
  const preview = bulkPreviewFixture();
  const roundedPk = Number.MAX_SAFE_INTEGER + 1;
  expectUnconfirmed(() => parseOrderPlanBulkPreviewResponse({
    ...preview,
    items: preview.items.map((item, index) => index === 0
      ? { ...item, order_plan_id: roundedPk }
      : item),
  }, BT_IDS));
  expectUnconfirmed(() => parseOrderPlanBulkPreviewResponse({
    ...preview,
    selected_plan_count: roundedPk,
  }, BT_IDS));
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...bulkReceiptFixture(),
    summary: { ...bulkReceiptFixture().summary, unique_owner_count: roundedPk },
  }, BT_IDS, BT_REQUEST_ID));
});

test("BT-client-invalid-UUID-date-and-timezone-fail-closed", () => {
  const receipt = bulkReceiptFixture();
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...receipt,
    completed_at: "2026-09-02T01:00:00.123456",
  }, BT_IDS, BT_REQUEST_ID));
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...receipt,
    completed_at: "2026-02-30T01:00:00.123456Z",
  }, BT_IDS, BT_REQUEST_ID));
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...receipt,
    completed_at: "2026-09-02T01:00:00.123456+24:00",
  }, BT_IDS, BT_REQUEST_ID));
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...receipt,
    items: receipt.items.map((item, index) => index === 0
      ? { ...item, audit_event_id: "not-a-uuid" }
      : item),
  }, BT_IDS, BT_REQUEST_ID));
});

test("BT-client-invalid-summary-counts-and-excluded-status-counts-fail-closed", () => {
  const receipt = bulkReceiptFixture();
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...receipt,
    summary: { ...receipt.summary, succeeded_plan_count: 99 },
  }, BT_IDS, BT_REQUEST_ID));
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...receipt,
    summary: {
      ...receipt.summary,
      excluded_by_status: {
        ...receipt.summary.excluded_by_status,
        "보류": { plan_count: 2, owner_count: 1 },
      },
    },
  }, BT_IDS, BT_REQUEST_ID));
  const preview = bulkPreviewFixture();
  expectUnconfirmed(() => parseOrderPlanBulkPreviewResponse({
    ...preview,
    excluded_by_status: {
      ...preview.excluded_by_status,
      "종료": { plan_count: 0, owner_count: 0 },
    },
  }, BT_IDS));
});

test("BT-client-owner-fanout-and-audit-consistency-are-enforced", () => {
  const receipt = bulkReceiptFixture();
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...receipt,
    items: receipt.items.map((item, index) => index === 1
      ? { ...item, audit_event_id: "f2f4d7c1-0a61-4f07-8d2e-000000000002" }
      : item),
  }, BT_IDS, BT_REQUEST_ID));
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...receipt,
    items: receipt.items.map((item, index) => index === 0
      ? { ...item, outcome: "succeeded", audit_event_id: null }
      : item),
  }, BT_IDS, BT_REQUEST_ID));
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse({
    ...receipt,
    items: receipt.items.map((item, index) => index === 2
      ? { ...item, audit_event_id: BT_AUDIT_ID }
      : item),
  }, BT_IDS, BT_REQUEST_ID));
});

test("BT-client-request-ID-mismatch-is-result-unconfirmed", () => {
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse(
    bulkReceiptFixture(),
    BT_IDS,
    "7a9c9b7a-0c11-4a5e-9f34-000000000099",
  ));
  expectUnconfirmed(() => parseOrderPlanBulkStartResponse(
    { ...bulkReceiptFixture(), request_id: "7a9c9b7a-0c11-4a5e-9f34-000000000099" },
    BT_IDS,
    BT_REQUEST_ID,
  ));
});

test("BT-client-safe-server-envelope-and-FastAPI-422-remain-distinguishable", () => {
  const safeEnvelope = parseOrderPlanBulkTrackingError(new ApiError(
    409,
    "서버 원문은 사용하지 않음",
    { code: "idempotency_conflict", message: "내부 원문", details: null },
    BT_REQUEST_ID,
  ));
  expect(safeEnvelope).toEqual({
    status: 409,
    kind: "server",
    code: "idempotency_conflict",
    request_id: BT_REQUEST_ID,
  });

  const fastApi422 = parseOrderPlanBulkTrackingError(new ApiError(
    422,
    "요청 형식 오류",
    [{ type: "literal_error", loc: ["body", "schema_version"], msg: "invalid" }],
  ));
  expect(fastApi422).toEqual({
    status: 422,
    kind: "validation",
    code: "invalid_request",
    request_id: null,
  });
});

test("BT-client-transport-unconfirmed-and-conflict-messages-never-suggest-a-new-key", () => {
  const errors = [
    describeOrderPlanBulkTrackingError(new ApiError(0, "network")),
    describeOrderPlanBulkTrackingError(new OrderPlanBulkTrackingResultUnconfirmedError()),
    describeOrderPlanBulkTrackingError(new ApiError(
      409,
      "ignored",
      { code: "idempotency_conflict", message: "ignored", details: null },
      BT_REQUEST_ID,
    )),
  ];
  for (const description of errors) {
    expect(`${description.title} ${description.detail}`).not.toMatch(
      /새.*(request[_ -]?id|uuid|키|식별자).*(만들|생성|발급|사용)/i,
    );
  }
  expect(errors[0].action).toBe("retry");
  expect(errors[1].code).toBe("result_unconfirmed");
  expect(errors[2].action).toBe("reload");
});

test("LS-cross-page-selection-survives-refresh-and-clears-on-applied-filter-change", async ({ page }) => {
  await mockOrderPlans(page, "large");
  await page.goto("/order-plans");
  await expect(page.locator(".c2l-row")).toHaveCount(500);

  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page).toHaveURL(/offset=500/);
  await expect(page.locator(".c2l-row")).toHaveCount(400);
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 2건");

  await page.reload();
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 2건");
  await expect(page.locator('.c2l-row input[type="checkbox"][data-checked="true"]')).toHaveCount(1);

  await clickPreset(page, "전체");
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 0건");
  await expect(page.locator('.c2l-row input[type="checkbox"][data-checked="true"]')).toHaveCount(0);
});

test("LS-checkbox-space-and-input-events-remain-independent-from-active-row", async ({ page }) => {
  await mockOrderPlans(page);
  await page.goto("/order-plans");
  const rows = page.locator(".c2l-row");
  await rows.nth(1).click();
  const firstCheckbox = rows.first().locator('input[type="checkbox"]');
  await firstCheckbox.press("Space");
  await expect(firstCheckbox).toBeChecked();
  await expect(rows.nth(1)).toHaveClass(/is-selected/);
  await expect(rows.first()).not.toHaveClass(/is-selected/);

  const firstRow = rows.first();
  await firstRow.click();
  await firstRow.focus();
  await firstRow.press("Space");
  await expect(firstCheckbox).not.toBeChecked();
  // A held/repeated row Space must not toggle a second time.
  await firstRow.dispatchEvent("keydown", { key: " ", code: "Space", repeat: true, bubbles: true });
  await expect(firstCheckbox).not.toBeChecked();

  await page.getByLabel("담당자 이름 · 감사 표식").fill("키보드 담당자");
  await page.getByLabel("담당자 이름 · 감사 표식").press("Space");
  await expect(firstCheckbox).not.toBeChecked();
});

test("BT-confirmation-shows-owner-and-status-exclusions-and-does-not-run-single-patch", async ({ page }) => {
  const singleTrace = await mockOrderPlans(page);
  await mockOrderPlanBulkTracking(page, "mixed");
  await page.goto("/order-plans");
  await clickPreset(page, "전체");
  const rows = page.locator(".c2l-row");
  await rows.filter({ hasText: "인공지능 기반 공공데이터" }).locator('input[type="checkbox"]').check();
  await rows.filter({ hasText: "청사 시설관리" }).locator('input[type="checkbox"]').check();
  await rows.filter({ hasText: "복지서비스 운영" }).locator('input[type="checkbox"]').check();
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 3건");
  await selectReason(page, "후속 사전규격·공고 확인");
  await page.getByLabel("담당자 이름 · 감사 표식").fill("일괄 담당자");

  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await expect(dialog).toContainText("중복 제거한 소유 사업기회");
  await expect(dialog).toContainText("보류로 제외");
  await expect(dialog).toContainText("종료로 제외");
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("일괄 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("공통 검토 사유");
  await expect(dialog).toContainText("최종 건수는 달라질 수 있습니다");

  const confirm = dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true });
  await confirm.evaluate((button) => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await expect(dialog).toContainText("일괄 추적 결과를 확인했습니다");
  await expect(dialog).toContainText("상태 제외");
  expect(singleTrace.trackingPatches).toHaveLength(0);
  expect(await page.locator(".c2l-detail-head h4").textContent()).toContain("인공지능 기반");
  await expect(page.getByRole("combobox", { name: "선택 사유" })).toContainText("후속 사전규격·공고 확인");
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 0건");
});

test("BT-lost-response-keeps-identical-request-through-reload-and-manual-recovery", async ({ page }) => {
  await mockOrderPlans(page);
  const trace = await mockOrderPlanBulkTracking(page, "all-eligible");
  let attempts = 0;
  const lostRequests: Array<{ body: unknown; headers: Record<string, string> }> = [];
  await page.route("**/api/opportunities/order-plan-tracking/bulk-start", async (route) => {
    const request = route.request();
    lostRequests.push({ body: request.postDataJSON(), headers: request.headers() });
    attempts += 1;
    if (attempts === 1) {
      await route.abort("failed");
      return;
    }
    await route.fallback();
  });
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("응답 복구 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("응답 유실 확인");
  await dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true }).click();
  await expect(dialog).toContainText("결과를 확인할 수 없습니다");
  await page.reload();
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 1건");
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const recovered = page.getByTestId("order-plan-bulk-tracking-dialog");
  await expect(recovered).toContainText("저장된 요청 결과");
  await recovered.getByRole("button", { name: "저장된 요청 결과 확인", exact: true }).click();
  await expect(recovered).toContainText("일괄 추적 결과를 확인했습니다");
  expect(lostRequests).toHaveLength(2);
  expect(lostRequests[0].body).toEqual(lostRequests[1].body);
  expect(lostRequests[0].headers["x-bidops-actor-name"]).toBe(lostRequests[1].headers["x-bidops-actor-name"]);
  expect(trace.startPosts).toHaveLength(1);
});

test("BT-malformed-receipt-is-unconfirmed-and-preserves-selection", async ({ page }) => {
  await mockOrderPlans(page);
  await mockOrderPlanBulkTracking(page, "malformed-start");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("검증 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("receipt 형식 확인");
  await dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true }).click();
  await expect(dialog).toContainText("일괄 추적 결과를 확인할 수 없습니다");
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 1건");
  await expect(dialog.getByRole("button", { name: "같은 요청 결과 확인", exact: true })).toBeVisible();
});

test("BT-gateway-error-preserves-unknown-request-identity", async ({ page }) => {
  await mockOrderPlans(page);
  await mockOrderPlanBulkTracking(page, "all-eligible");
  const bodies: unknown[] = [];
  await page.route("**/api/opportunities/order-plan-tracking/bulk-start", async (route) => {
    bodies.push(route.request().postDataJSON());
    await route.fulfill({ status: 502, contentType: "text/plain", body: "Bad Gateway" });
  });
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().getByRole("checkbox").check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("검증 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("응답 유실 확인");
  await dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true }).click();
  const retry = dialog.getByRole("button", { name: "같은 요청 결과 확인", exact: true });
  await expect(retry).toBeVisible();
  await retry.click();
  await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1]).toEqual(bodies[0]);
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 1건");
});

test("BT-failed-only-retry-mints-a-new-key-only-after-human-confirmation", async ({ page }) => {
  await mockOrderPlans(page);
  await mockOrderPlanBulkTracking(page, "all-eligible");
  const requestIds: string[] = [];
  await page.route("**/api/opportunities/order-plan-tracking/bulk-start", async (route) => {
    const body = route.request().postDataJSON() as { request_id: string; order_plan_ids: number[] };
    requestIds.push(body.request_id);
    const id = body.order_plan_ids[0];
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "order-plan-bulk-start-response.v1",
        request_id: body.request_id,
        completed_at: "2026-09-02T01:00:00.123456Z",
        items: [{ order_plan_id: id, opportunity_id: null, outcome: "failed", status_at_decision: null, code: "order_plan_not_found", audit_event_id: null }],
        summary: {
          selected_plan_count: 1, unique_owner_count: 0, succeeded_plan_count: 0, succeeded_owner_count: 0,
          excluded_plan_count: 0, excluded_by_status: {
            "계속 추적": { plan_count: 0, owner_count: 0 }, "보류": { plan_count: 0, owner_count: 0 }, "종료": { plan_count: 0, owner_count: 0 },
          }, failed_plan_count: 1,
        },
      }),
    });
  });
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("실패 재시도 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("실패 건을 다시 확인");
  await dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true }).click();
  await expect(dialog).toContainText("실패 1건");
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 1건");
  await dialog.getByRole("button", { name: "실패 건 재시도 준비", exact: true }).click();
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true }).click();
  await expect(dialog).toContainText("실패 1건");
  const starts = await page.locator("body").evaluate(() => window.sessionStorage.getItem("bidops.order-plans.bulk-tracking.pending.v2"));
  expect(starts).toBeNull();
  expect(requestIds).toHaveLength(2);
  expect(requestIds[0]).not.toBe(requestIds[1]);
});

test("BT-storage-quota-refusal-does-not-send-bulk-request", async ({ page }) => {
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function setItem(key: string, value: string) {
      if (key === "bidops.order-plans.bulk-tracking.pending.v2") {
        throw new DOMException("quota", "QuotaExceededError");
      }
      original.call(this, key, value);
    };
  });
  await mockOrderPlans(page);
  const trace = await mockOrderPlanBulkTracking(page, "all-eligible");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("저장 실패 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("저장소 제한 확인");
  await dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true }).click();
  await expect(dialog).toContainText("일괄 요청을 저장하지 못했습니다");
  await expect(dialog).toContainText("단건 추적 경로를 사용하십시오");
  expect(trace.startPosts).toHaveLength(0);
});

test("BT-confirmation-invalid-actor-or-reason-is-disabled-without-start-request", async ({ page }) => {
  await mockOrderPlans(page);
  const trace = await mockOrderPlanBulkTracking(page, "all-eligible");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  // Preview intentionally remains available without attribution fields.
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  const confirm = dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true });
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("system");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("유효한 사유");
  await expect(confirm).toBeDisabled();
  await expect(dialog).toContainText("system을 사용할 수 없습니다");
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("정상 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("   ");
  await expect(confirm).toBeDisabled();
  await expect(dialog).toContainText("공통 추적 사유를 입력하십시오");
  expect(trace.previewPosts).toHaveLength(1);
  expect(trace.startPosts).toHaveLength(0);
});

test("BT-same-frame-double-confirm-keeps-one-persisted-request-identity", async ({ page }) => {
  await mockOrderPlans(page);
  const trace = await mockOrderPlanBulkTracking(page, "all-eligible");
  const wire: Array<{ body: unknown; actor: string }> = [];
  let releaseLost: (() => void) | null = null;
  const lostGate = new Promise<void>((resolve) => { releaseLost = resolve; });
  await page.route("**/api/opportunities/order-plan-tracking/bulk-start", async (route) => {
    const request = route.request();
    wire.push({ body: request.postDataJSON(), actor: request.headers()["x-bidops-actor-name"] ?? "" });
    if (wire.length === 1) {
      await lostGate;
      await route.abort("failed");
      return;
    }
    await route.fallback();
  });
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("중복 확인 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("같은 프레임 중복 확인");
  const confirm = dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true });
  await confirm.evaluate((button) => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await expect(dialog).toContainText("일괄 추적 저장 중");
  const pendingRaw = await page.evaluate(() => window.sessionStorage.getItem("bidops.order-plans.bulk-tracking.pending.v2"));
  expect(pendingRaw).not.toBeNull();
  const pending = JSON.parse(pendingRaw as string) as { request_id: string };
  expect(pending.request_id).toMatch(/^[0-9a-f-]{36}$/i);
  releaseLost?.();
  await expect(dialog).toContainText("결과를 확인할 수 없습니다");
  await dialog.getByRole("button", { name: "같은 요청 결과 확인", exact: true }).click();
  await expect(dialog).toContainText("일괄 추적 결과를 확인했습니다");
  expect(wire).toHaveLength(2);
  expect(wire[0].body).toEqual(wire[1].body);
  expect((wire[0].body as { request_id: string }).request_id).toBe(pending.request_id);
  expect(wire[0].actor).toBe(wire[1].actor);
  expect(trace.startPosts).toHaveLength(1);
});

test("BT-unknown-request-recovery-remains-reachable-after-filter-generation-clears-selection", async ({ page }) => {
  await mockOrderPlans(page);
  await mockOrderPlanBulkTracking(page, "all-eligible");
  await page.route("**/api/opportunities/order-plan-tracking/bulk-start", async (route) => {
    await route.abort("failed");
  });
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("복구 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("필터 전환 뒤 결과 확인");
  await dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true }).click();
  await expect(dialog).toContainText("결과를 확인할 수 없습니다");
  await dialog.getByRole("button", { name: "닫기", exact: true }).click();
  await clickPreset(page, "전체");
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 0건");
  await expect(page.getByRole("button", { name: "저장된 일괄 요청 확인", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "저장된 일괄 요청 확인", exact: true }).click();
  const recovery = page.getByTestId("order-plan-bulk-tracking-dialog");
  await expect(recovery).toContainText("저장된 요청 결과를 아직 확인하지 않았습니다");
  await expect(recovery.getByRole("button", { name: "저장된 요청 결과 확인", exact: true })).toBeVisible();
});

test("BT-late-preview-from-closed-dialog-cannot-overwrite-reopened-binding", async ({ page }) => {
  await mockOrderPlans(page);
  await mockOrderPlanBulkTracking(page, "all-eligible");
  let releaseFirst: (() => void) | null = null;
  let previewCalls = 0;
  const firstPreview = new Promise<void>((resolve) => { releaseFirst = resolve; });
  await page.route("**/api/opportunities/order-plan-tracking/preview", async (route) => {
    previewCalls += 1;
    if (previewCalls === 1) await firstPreview;
    await route.fallback();
  });
  await page.goto("/order-plans");
  const rows = page.locator(".c2l-row");
  await rows.nth(0).locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  let dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await expect(dialog).toContainText("선택 대상의 최신 상태");
  await dialog.getByRole("button", { name: "닫기", exact: true }).click();
  await rows.nth(0).locator('input[type="checkbox"]').uncheck();
  await rows.nth(1).locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await expect(dialog.locator('[data-testid="order-plan-bulk-preview"]')).toContainText("102");
  releaseFirst?.();
  await expect(dialog.locator('[data-testid="order-plan-bulk-preview"]')).toContainText("102");
  await expect(dialog.locator('[data-testid="order-plan-bulk-preview"]')).not.toContainText("101");
});

test("BT-preview-binding-refuses-confirm-after-browser-filter-generation-change", async ({ page }) => {
  await mockOrderPlans(page);
  const trace = await mockOrderPlanBulkTracking(page, "all-eligible");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await expect(dialog.locator('[data-testid="order-plan-bulk-preview"]')).toBeVisible();
  await page.evaluate(() => {
    window.history.pushState({}, "", "/order-plans?q=브라우저-뒤로앞으로");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  const confirm = dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true });
  await expect(confirm).toBeDisabled();
  await expect(dialog).toContainText("현재 선택과 미리보기의 기준이 다릅니다");
  expect(trace.startPosts).toHaveLength(0);
});

test("BT-bulk-actor-and-reason-drafts-do-not-mutate-single-drafts", async ({ page }) => {
  await mockOrderPlans(page);
  await mockOrderPlanBulkTracking(page, "all-eligible");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().click();
  await selectReason(page, "후속 사전규격·공고 확인");
  await page.getByLabel("담당자 이름 · 감사 표식").fill("단건 담당자");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("일괄 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("일괄 전용 사유");
  await dialog.getByRole("button", { name: "닫기", exact: true }).click();
  await expect(page.locator(".c2l-tracking").getByLabel("담당자 이름 · 감사 표식")).toHaveValue("단건 담당자");
  await expect(page.getByRole("combobox", { name: "선택 사유" })).toContainText("후속 사전규격·공고 확인");
});

test("BT-valid-receipt-stays-definitive-when-post-result-invalidation-fails", async ({ page }) => {
  await mockOrderPlans(page);
  await mockOrderPlanBulkTracking(page, "all-eligible");
  let listReads = 0;
  await page.route("**/api/order-plans**", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    listReads += 1;
    if (listReads > 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "service_unavailable", message: "ignored", details: null } }),
      });
      return;
    }
    await route.fallback();
  });
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("결과 담당자");
  await dialog.getByRole("textbox", { name: "공통 추적 사유" }).fill("결과 확정 후 목록 갱신");
  await dialog.getByRole("button", { name: "확인하고 일괄 추적 시작", exact: true }).click();
  await expect(dialog).toContainText("일괄 추적 결과를 확인했습니다");
  await expect(dialog).not.toContainText("일괄 추적 결과를 확인할 수 없습니다");
});

// ---- 일괄 추적 종료 (ADR-0063 / S4 A) ----

test("BE-select-three-end-tracking-confirm-and-result-hides-ended-plans-from-default-view", async ({ page }) => {
  await mockOrderPlans(page);
  const trace = await mockOrderPlanBulkTracking(page, "all-eligible");
  await page.goto("/order-plans");
  await clickPreset(page, "전체");
  const rows = page.locator(".c2l-row");
  await rows.filter({ hasText: "인공지능 기반 공공데이터" }).locator('input[type="checkbox"]').check();
  await rows.filter({ hasText: "지방공기업 업무혁신" }).locator('input[type="checkbox"]').check();
  await rows.filter({ hasText: "청사 시설관리" }).locator('input[type="checkbox"]').check();
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 3건");

  await page.getByRole("button", { name: "선택 항목 추적 종료", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await expect(dialog).toContainText("발주계획 일괄 추적 종료");
  await expect(dialog).toContainText("추적을 아직 정하지 않은 계획만 추적 종료로 저장합니다");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("종료 담당자");
  await dialog.getByRole("textbox", { name: "공통 종료 사유" }).fill("현재 범위와 맞지 않아 능동 추적을 종료함");
  await expect(dialog).toContainText("종료한 계획은 기본 보기(검토 대상)에서 사라집니다");
  await dialog.getByRole("button", { name: "확인하고 일괄 추적 종료", exact: true }).click();
  await expect(dialog).toContainText("일괄 추적 종료 결과를 확인했습니다");
  await expect(dialog).toContainText("추적 필터 '종료'와 사업 추적의 '추적 종료' 구역에서 볼 수 있습니다");

  expect(trace.endPosts).toHaveLength(1);
  const { body, headers } = trace.endPosts[0];
  expect(body).toMatchObject({
    schema_version: "order-plan-bulk-end-request.v1",
    order_plan_ids: [101, 102, 103],
    reason: "현재 범위와 맞지 않아 능동 추적을 종료함",
  });
  // 비ASCII 담당자 이름은 `UTF-8''<percent-encoded>` 형식으로 나간다(docs/contracts.md).
  expect(decodeURIComponent(headers["x-bidops-actor-name"].replace(/^UTF-8''/, ""))).toBe("종료 담당자");

  await dialog.getByRole("button", { name: "닫기", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "건을 추적 종료했습니다" }))
    .toContainText("3건을 추적 종료했습니다 · 추적 필터 '종료'에서 볼 수 있습니다");

  // 기본 보기(검토 대상)는 관련·불확실 AND 미선택만 보인다. 101·102는 이제 종료라 빠진다.
  // `검토 대상` 탭은 축 값을 URL에 그대로 적어 `isDefaultView`를 벗어나므로, 축이
  // 전혀 없는 진짜 기본 진입(빈 URL)으로 다시 들어가 확인한다.
  await page.goto("/order-plans");
  await expect(page.locator(".c2l-list-head")).toContainText("현재 필터 결과 0건");
  await expect(page.locator(".c2l-list-pane").getByText("검토할 발주계획이 없습니다")).toBeVisible();
  await expect(page.locator(".c2l-list-pane").getByText("추적을 정하지 않은 관련 건을 모두 처리했습니다.")).toBeVisible();
});

test("BE-blank-reason-blocks-confirm-and-sends-no-request", async ({ page }) => {
  await mockOrderPlans(page);
  const trace = await mockOrderPlanBulkTracking(page, "all-eligible");
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 종료", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await dialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("종료 담당자");
  const confirm = dialog.getByRole("button", { name: "확인하고 일괄 추적 종료", exact: true });
  await expect(confirm).toBeDisabled();
  await expect(dialog).toContainText("공통 종료 사유를 입력하십시오.");
  expect(trace.endPosts).toHaveLength(0);
  expect(trace.startPosts).toHaveLength(0);
});

test("BE-mixed-selection-preview-shows-eligible-and-status-exclusions", async ({ page }) => {
  await mockOrderPlans(page);
  await mockOrderPlanBulkTracking(page, "mixed");
  await page.goto("/order-plans");
  await clickPreset(page, "전체");
  const rows = page.locator(".c2l-row");
  await rows.filter({ hasText: "인공지능 기반 공공데이터" }).locator('input[type="checkbox"]').check();
  await rows.filter({ hasText: "청사 시설관리" }).locator('input[type="checkbox"]').check();
  await rows.filter({ hasText: "복지서비스 운영" }).locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 종료", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await dialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await expect(dialog).toContainText("미선택 · 종료 가능");
  await expect(dialog).toContainText("보류로 제외");
  await expect(dialog).toContainText("종료로 제외");
});

test("BE-over-200-selection-disables-end-but-keeps-start-enabled", async ({ page }) => {
  await mockOrderPlans(page);
  await mockOrderPlanBulkTracking(page, "all-eligible");
  await page.goto("/order-plans");
  // 목록 선택 hook이 수화(hydrate)해 빈 상태를 쓸 때까지 기다린다 — 그 전에 읽으면
  // sessionStorage 키가 아직 없다.
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 0건");
  const fingerprint = await page.evaluate(() => {
    const raw = window.sessionStorage.getItem("bidops.order-plans.selection.v1");
    return raw ? (JSON.parse(raw) as { filterFingerprint: string }).filterFingerprint : null;
  });
  expect(fingerprint).not.toBeNull();
  await page.evaluate((filterFingerprint) => {
    window.sessionStorage.setItem("bidops.order-plans.selection.v1", JSON.stringify({
      version: 1,
      filterFingerprint,
      selectionGeneration: 0,
      selectedIds: Array.from({ length: 201 }, (_, index) => 9000 + index),
      selectedSortMetadata: {},
      listSearch: "",
      activeId: null,
      listScrollTop: 0,
    }));
  }, fingerprint);
  await page.reload();
  await expect(page.getByTestId("order-plan-selection-toolbar")).toContainText("선택 201건");
  await expect(page.getByRole("button", { name: "선택 항목 추적 종료", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "선택 항목 추적 시작", exact: true })).toBeEnabled();
  await expect(page.locator("#c2l-selection-action-reason"))
    .toContainText("한 번에 200건까지 종료할 수 있습니다. 선택을 줄이십시오.");
});

test("BE-legacy-v1-pending-request-migrates-and-recovers-through-start-endpoint-only", async ({ page }) => {
  await mockOrderPlans(page);
  const trace = await mockOrderPlanBulkTracking(page, "all-eligible");
  await page.goto("/order-plans");
  await page.evaluate(() => {
    window.sessionStorage.setItem("bidops.order-plans.bulk-tracking.pending.v1", JSON.stringify({
      request_id: "11111111-1111-4111-8111-111111111111",
      order_plan_ids: [101],
      actor: "레거시 담당자",
      reason: "레거시 사유",
      selection_generation: 0,
      filter_fingerprint: "order-plans:{}",
    }));
  });
  await page.reload();
  // A2 마이그레이션: 열기 전에 이미 v2로 옮겨지고 action은 start로 채워진다.
  await expect.poll(() => page.evaluate(() => window.sessionStorage.getItem("bidops.order-plans.bulk-tracking.pending.v1")))
    .toBeNull();
  const migratedRaw = await page.evaluate(() => window.sessionStorage.getItem("bidops.order-plans.bulk-tracking.pending.v2"));
  expect(migratedRaw).not.toBeNull();
  expect(JSON.parse(migratedRaw as string)).toMatchObject({ action: "start", order_plan_ids: [101] });

  await expect(page.getByRole("button", { name: "저장된 일괄 요청 확인", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "저장된 일괄 요청 확인", exact: true }).click();
  const dialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await expect(dialog).toContainText("발주계획 일괄 추적");
  await expect(dialog).not.toContainText("발주계획 일괄 추적 종료");
  await dialog.getByRole("button", { name: "저장된 요청 결과 확인", exact: true }).click();
  await expect(dialog).toContainText("일괄 추적 결과를 확인했습니다");
  expect(trace.startPosts).toHaveLength(1);
  expect(trace.endPosts).toHaveLength(0);
});

test("BE-pending-end-request-recovers-through-end-endpoint-even-when-start-dialog-opens", async ({ page }) => {
  await mockOrderPlans(page);
  const trace = await mockOrderPlanBulkTracking(page, "all-eligible");
  let attempts = 0;
  await page.route("**/api/opportunities/order-plan-tracking/bulk-end", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.abort("failed");
      return;
    }
    await route.fallback();
  });
  await page.goto("/order-plans");
  await page.locator(".c2l-row").first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "선택 항목 추적 종료", exact: true }).click();
  const endDialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await endDialog.getByRole("button", { name: "선택 대상 미리보기", exact: true }).click();
  await endDialog.getByRole("textbox", { name: "공통 담당자 이름 · 감사 표식" }).fill("종료 유실 담당자");
  await endDialog.getByRole("textbox", { name: "공통 종료 사유" }).fill("응답 유실 확인");
  await endDialog.getByRole("button", { name: "확인하고 일괄 추적 종료", exact: true }).click();
  await expect(endDialog).toContainText("일괄 추적 종료 결과를 확인할 수 없습니다");
  await endDialog.getByRole("button", { name: "닫기", exact: true }).click();

  // 같은 선택 상태에서 시작 단추를 눌러도, 저장된 요청의 action(종료)이 이긴다.
  await page.getByRole("button", { name: "선택 항목 추적 시작", exact: true }).click();
  const startDialog = page.getByTestId("order-plan-bulk-tracking-dialog");
  await expect(startDialog).toContainText("발주계획 일괄 추적 종료");
  await expect(startDialog).toContainText("저장된 요청 결과를 아직 확인하지 않았습니다");
  await startDialog.getByRole("button", { name: "저장된 요청 결과 확인", exact: true }).click();
  await expect(startDialog).toContainText("일괄 추적 종료 결과를 확인했습니다");
  expect(trace.endPosts).toHaveLength(1);
  expect(trace.startPosts).toHaveLength(0);
});

// ---- 일일 운영: 누적 기본·회차 모드·판정 표식·행의 실행으로 저장·자동 실행 배너 (spec §7·§3.4·§11) ----

const ORDER_PLAN_RUN = {
  kind: "order_plans", run_id: TEST_ORDER_PLAN_SOURCE_RUN_ID, generated_at: "2026-09-01T00:30:00Z",
  window_from: "2026-08-31", window_to: "2026-08-31", timezone: "Asia/Seoul",
  screening_basis: null, status: "collected", superseded_by: null,
  counts: { notices: 0, judgments: 0, reviews: 0, collection: {} },
};

function dailyTriggerState(overrides: Record<string, unknown>) {
  return {
    schema_version: "daily-trigger-state-response.v1",
    producer: "daily-trigger-api",
    consumer: "human-review-client",
    effective_enabled: false,
    policy_version: null,
    policy_sha256: null,
    switch: null,
    reasons: ["env_cap_off", "no_active_policy"],
    ...overrides,
  };
}

async function mockDailyTrigger(page: import("@playwright/test").Page, state: Record<string, unknown>) {
  await page.route("**/api/order-plan-screening/daily-trigger", (route) => route.request().method() === "GET"
    ? route.fulfill({ json: state })
    : route.fallback());
}

/** 목록 요청의 query만 모은다. 누적/회차 모드는 `source_run_id` 유무로 갈린다. */
function recordListRequests(page: import("@playwright/test").Page): URLSearchParams[] {
  const requests: URLSearchParams[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/order-plans" && request.method() === "GET") requests.push(url.searchParams);
  });
  return requests;
}

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test.describe(`일일 운영 누적 화면 ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });

    test("회차를 고르지 않으면 누적으로 열고, 고르면 회차 모드, 비우면 다시 누적이다", async ({ page }) => {
      await mockOrderPlans(page);
      await page.route("**/api/runs", (route) => route.fulfill({ json: { items: [ORDER_PLAN_RUN], total: 1 } }));
      const listRequests = recordListRequests(page);
      await page.goto("/order-plans");

      // 누적: source_run_id 없이 부르고 URL에도 회차를 박지 않는다. 평상시 누적(활성
      // policy 판정 있음)의 범위 줄은 운영자용 감사 정보라 그리지 않는다(2026-09-21).
      const scope = page.getByTestId("order-plan-list-scope");
      await expect(page.locator(".c2l-row")).toHaveCount(2);
      await expect(scope).toHaveCount(0);
      await expect(page.locator(".c2l-row")).toHaveCount(2);
      expect(listRequests.length).toBeGreaterThan(0);
      expect(listRequests.every((params) => !params.has("source_run_id"))).toBe(true);
      expect(new URL(page.url()).searchParams.has("source_run_id")).toBe(false);
      const runSelector = page.locator(".c2l-filter-tools").getByRole("combobox", { name: "수집 회차" });
      await expect(runSelector).toContainText("누적 · 회차 선택 안 함");

      // 기본 보기 = 추적을 정하지 않은 관련 건. 조합 문장과 행의 판정 표식을 함께 밝힌다.
      await expect(page.locator(".c2l-list-scope").filter({ hasText: "기본 보기" }))
        .toHaveText("기본 보기 · 추적을 정하지 않은 관련 건 (모델 판단 관련·불확실 AND 추적 미선택)");
      await expect(presetTab(page, "검토 대상")).toHaveAttribute("aria-pressed", "true");
      // 첫 관측은 한국 날짜다(2026-09-01T01:00Z → 2026-09-01).
      await expect(page.locator(".c2l-row").first().locator(".c2l-row-verdict")).toHaveText("판정 policy c2-policy.v1 · 첫 관측 2026-09-01");
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);

      // 회차를 고르면 그 회차의 실행으로 좁힌다(감사용). 회차 모드의 범위를 말한다.
      await runSelector.click();
      await page.getByRole("option", { name: /2026-08-31~2026-08-31 수집/ }).click();
      await expect.poll(() => new URL(page.url()).searchParams.get("source_run_id")).toBe(TEST_ORDER_PLAN_SOURCE_RUN_ID);
      await expect(scope).toHaveText("회차 · 실행 a2f4d7c1 · 부분 성공 · 판정 policy c2-policy.v1");
      expect(listRequests.at(-1)?.get("source_run_id")).toBe(TEST_ORDER_PLAN_SOURCE_RUN_ID);

      // 비우면 누적 기본 보기로 돌아간다. 이미 읽은 누적 목록은 캐시에서 다시 쓸 수 있으므로
      // 새 요청이 없을 수도 있다 — 있다면 회차 없이 나가야 한다.
      const requestsBeforeClear = listRequests.length;
      await runSelector.click();
      await page.getByRole("option", { name: /누적 · 회차 선택 안 함/ }).click();
      await expect.poll(() => new URL(page.url()).searchParams.has("source_run_id")).toBe(false);
      await expect(page.locator(".c2l-row")).toHaveCount(2);
      // 회차 모드에서 보이던 범위 줄은 평상시 누적으로 돌아오면 다시 사라진다.
      await expect(scope).toHaveCount(0);
      expect(listRequests.slice(requestsBeforeClear).every((params) => !params.has("source_run_id"))).toBe(true);
    });

    test("active policy가 있는데 자동 실행이 꺼져 있으면 사유와 활성화 화면 링크를 보인다", async ({ page }) => {
      await mockOrderPlans(page);
      await mockDailyTrigger(page, dailyTriggerState({
        policy_version: "c2-policy.v3",
        policy_sha256: "c".repeat(64),
        switch: null,
        reasons: ["env_cap_off", "switch_bound_to_other_version", "quality_gate_not_passed", "execution_transport_not_allowed", "policy_file_missing", "future_reason"],
      }));
      await page.goto("/order-plans");
      await expect(page.locator(".c2l-row")).toHaveCount(2);

      const banner = page.getByRole("alert").filter({ hasText: "발주계획 자동 실행 꺼짐" });
      await expect(banner).toBeVisible();
      await expect(banner).toContainText("policy c2-policy.v3");
      const reasons = banner.getByRole("list", { name: "자동 실행이 꺼진 사유" }).getByRole("listitem");
      await expect(reasons).toHaveText([
        "운영자가 환경 설정을 켜야 합니다.",
        "policy를 교체하면 자동 실행이 멈춥니다. 새 버전에서 다시 켜야 합니다.",
        "현재 policy의 품질 게이트가 통과 상태가 아닙니다.",
        "모델 전송이 허용되지 않았습니다(환경 설정 또는 모델 연결의 전송 승인).",
        "digest가 일치하는 policy·모델 연결 파일이 컨테이너에 없습니다.",
        // 모르는 code는 바꾸거나 숨기지 않고 그대로 보인다.
        "future_reason",
      ]);
      await expect(banner.getByRole("link", { name: "활성화 화면에서 확인 →" })).toHaveAttribute("href", "/order-plan-policies");
      // 배너는 작업 영역 위에 있다.
      const bannerBottom = await banner.evaluate((element) => element.getBoundingClientRect().bottom);
      const workspaceTop = await page.locator(".c2l-workspace").evaluate((element) => element.getBoundingClientRect().top);
      expect(bannerBottom).toBeLessThanOrEqual(workspaceTop);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
    });
  });
}

test("자동 실행 배너는 active policy가 없거나 자동 실행이 켜져 있으면 두지 않는다", async ({ page }) => {
  // 공용 mock 기본값: active policy 없음(no_active_policy). 활성화 전에는 꺼져 있는 것이 정상이다.
  await mockOrderPlans(page);
  const triggerRequests: string[] = [];
  page.on("request", (request) => { if (request.url().includes("/api/order-plan-screening/daily-trigger")) triggerRequests.push(request.method()); });
  await page.goto("/order-plans");
  await expect(page.locator(".c2l-row")).toHaveCount(2);
  await expect.poll(() => triggerRequests).toEqual(["GET"]);
  await expect(page.getByText("발주계획 자동 실행 꺼짐", { exact: false })).toHaveCount(0);

  await mockDailyTrigger(page, dailyTriggerState({
    effective_enabled: true,
    policy_version: "c2-policy.v3",
    policy_sha256: "c".repeat(64),
    switch: { enabled: true, reason: null, set_by: "운영 담당", set_at: "2026-09-18T00:00:00Z" },
    reasons: [],
  }));
  await page.reload();
  await expect(page.locator(".c2l-row")).toHaveCount(2);
  await expect.poll(() => triggerRequests.length).toBe(2);
  await expect(page.getByText("발주계획 자동 실행 꺼짐", { exact: false })).toHaveCount(0);
});

test("누적 기본 보기는 추적을 이미 정한 건을 숨기고, 결과 없는 행은 판정 없음이며 사람 판단 수정을 막는다", async ({ page }) => {
  const decided = testOrderPlanItem(103, "relevant", "이미 계속 추적 중인 관련 사업");
  decided.tracking.tracking_status = "계속 추적";
  const items = [
    testOrderPlanItem(101, "relevant", "누적 관련 사업"),
    decided,
    testOrderPlanItem(104, null, "판정 결과가 없는 사업"),
  ];
  const trace = await mockReorderedOrderPlanList(page, items);
  await page.goto("/order-plans");

  // 기본 보기: 관련·불확실 AND 추적 미선택 → 101만 남는다.
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await expect(page.locator(".c2l-row")).toContainText("누적 관련 사업");
  await expect(presetTab(page, "검토 대상")).toContainText("1");

  await clickPreset(page, "전체");
  await expect(page.locator(".c2l-row")).toHaveCount(3);
  const noResult = page.locator(".c2l-row").filter({ hasText: "판정 결과가 없는 사업" });
  await expect(noResult.locator(".c2l-row-verdict")).toHaveText("판정 없음 · 첫 관측 2026-09-01");

  await noResult.click();
  await page.getByRole("button", { name: "사람 판단 수정 열기" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("이 발주계획에는 판정 결과가 없어 모델 판단에 대한 수정본을 저장할 수 없습니다.");
  await expect(dialog.getByRole("button", { name: "새 수정본 저장", exact: true })).toBeDisabled();
  await expect(dialog.getByLabel("memo")).toBeDisabled();
  await expect(dialog.getByLabel("사람 판단 담당자 이름")).toBeDisabled();
  expect(trace.feedbackPosts).toHaveLength(0);
});

test("사람 판단 수정은 화면의 최신 실행이 아니라 그 행의 execution_id로 저장하고 수정본 번호도 그 실행에서 센다", async ({ page }) => {
  // 101의 결과는 앞선 실행(083101)이 냈다. 공용 mock의 수정본 이력에는 최신 실행(010101)에
  // 붙은 revision 1이 있지만, 이 실행에는 수정본이 없으므로 expected_revision은 0이다.
  const olderRow = testOrderPlanItem(101, "relevant", "앞선 실행이 판정한 사업");
  olderRow.execution_id = TEST_OLDER_EXECUTION_ID;
  const trace = await mockReorderedOrderPlanList(page, [olderRow]);
  await page.goto("/order-plans");
  await expect(page.locator(".c2l-row")).toHaveCount(1);
  await page.locator(".c2l-row").first().click();

  // 실행 기록 탭도 이 행의 실행을 보인다.
  await page.getByRole("button", { name: "선별 신호와 실행 기록 열기" }).click();
  await page.getByRole("tab", { name: "실행 기록" }).click();
  await expect(page.locator("#c2l-panel-telemetry")).toContainText(TEST_OLDER_EXECUTION_ID);
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "사람 판단 수정 열기" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("수정본을 붙일 판정 · 실행 a2f4d7c1 · policy c2-policy.v1");
  await dialog.getByRole("radiogroup", { name: "사람 relevance 판단" }).getByRole("radio", { name: "not_relevant" }).click();
  await dialog.getByLabel("사람 판단 담당자 이름").fill("누적 검토자");
  await dialog.getByRole("button", { name: "새 수정본 저장", exact: true }).click();
  await expect(page.getByText("사람 피드백 수정본을 저장했습니다. 추적 상태는 바뀌지 않았습니다.")).toBeVisible();

  expect(trace.feedbackPosts).toHaveLength(1);
  expect(trace.feedbackPosts[0].body).toMatchObject({
    execution_id: TEST_OLDER_EXECUTION_ID,
    relevance: "not_relevant",
    expected_revision: 0,
  });
});
