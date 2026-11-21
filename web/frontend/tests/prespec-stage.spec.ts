import { expect, test } from "@playwright/test";
import { mockApi, mockFeatureFlags, openProcessSection } from "./api-mock";
import { completedView } from "./fixtures/verdict";

// 2026-11-19 사전규격 단계 수정안 §3 B — 검토할 항목·확인 필요·다음 행동 안내·참여 판정 열.
//
// 가짜 서버(`api-mock.ts`의 `preSpecListBody`)는 백엔드 술어를 그대로 옮겼다. 표본:
// 991(SW N·추적 예외·`종료` 결정·개요 `needs_human_review`), 992(SW Y·`미선택`·개요 `failed`·
// 마감 전), 993(SW N·연결 없음·개요 `completed`·마감 미확인).

function preSpecQueries(page: import("@playwright/test").Page): URLSearchParams[] {
  const queries: URLSearchParams[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/pre-specs" && !url.searchParams.has("notice_pk")) queries.push(url.searchParams);
  });
  return queries;
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("실패한 개요는 검토할 항목이 아니라 확인 필요 보기에 모이고 마감 구간을 같이 쓴다", async ({ page }) => {
  const queries = preSpecQueries(page);
  await page.goto("/pre-specs");

  const tabs = page.getByRole("group", { name: "사전규격 업무 화면" });
  // 기본 보기(검토할 항목, 마감 전·미확인, SW사업대상)에는 실패한 개요(992)가 없다.
  await expect(tabs.locator('[data-view-key="actionable"]')).toContainText("0");
  await expect(tabs.locator('[data-view-key="needs_check"]')).toContainText("확인 필요");
  await expect(tabs.locator('[data-view-key="needs_check"]')).toContainText("1");
  await expect(page.locator(".pre-specs-row").filter({ hasText: "신규 지능형 행정 지원 사전규격" })).toHaveCount(0);

  await tabs.locator('[data-view-key="needs_check"]').click();
  await expect.poll(() => new URL(page.url()).searchParams.get("workspace")).toBe("needs_check");
  await expect.poll(() => queries.at(-1)?.get("workspace")).toBe("needs_check");
  expect(queries.at(-1)?.get("deadline_scope")).toBe("current");
  const row = page.locator(".pre-specs-row").filter({ hasText: "신규 지능형 행정 지원 사전규격" });
  await expect(row).toBeVisible();
  // 마감 구간 전환은 확인 필요에서도 보이며 건수는 `needs_check_deadline_scope_counts`다.
  const scope = page.locator(".pre-specs-deadline-scope");
  await expect(scope).toContainText("마감 전·미확인 1");
  await expect(scope).toContainText("마감 경과 0");
  // 실패한 개요에는 다음 행동 안내가 없다 — 옛 "심층 검토 열기"로 올라오지 않는다.
  await expect(page.locator(".pre-specs-next-action")).toContainText("다음 행동 안내 없음");
  await expect(page.getByText("심층 검토 열기", { exact: true })).toHaveCount(0);
});

test("다음 행동 안내는 개요 확인과 개요 확인 필요 두 값이다", async ({ page }) => {
  await page.goto("/pre-specs?workspace=all&sw_only=false");
  const pane = page.locator(".pre-specs-detail-pane");

  await page.locator(".pre-specs-row").filter({ hasText: "독립 수집된 심층 검토 클릭 대기 사전규격" }).click();
  // 개요 `completed` ∧ 추적 결정 없음 → 개요를 읽고 추적을 정한다.
  await expect(pane.locator(".pre-specs-next-action")).toContainText("개요 확인");
  await expect(pane.locator(".pre-specs-next-action")).not.toContainText("개요 확인 필요");

  await page.locator(".pre-specs-row").filter({ hasText: "안전한 문서 준비 사전규격" }).click();
  // 개요 `needs_human_review`는 추적 결정(`종료`)과 무관하게 범위 확정이 남는다.
  await expect(pane.locator(".pre-specs-next-action")).toContainText("개요 확인 필요");
});

test("참여 판정 열은 RL이 꺼진 환경에서 꺼져 있다고 먼저 말하고 판정을 조회하지 않는다", async ({ page }) => {
  const verdictRequests: string[] = [];
  page.on("request", (request) => {
    if (/\/api\/opportunities\/\d+\/verdict$/.test(new URL(request.url()).pathname)) verdictRequests.push(request.url());
  });
  await mockFeatureFlags(page, { rl_analysis: false, prespec_overview: false });
  await page.goto("/pre-specs/991");
  // 2026-11-21: 값이 없는 열이라 `회사 관련성 참고` 구역은 그리지 않는다. 꺼짐 안내는 지우지 않고 접힌
  // `처리 상태·기술 정보` 안에 있고, 그 구역의 요약 한 줄도 꺼짐을 먼저 말한다.
  await expect(page.locator("#ps-conditions")).toHaveCount(0);
  await expect(page.getByTestId("pre-spec-process-summary")).toContainText("참여 판정(RL 분석) 꺼짐");
  await openProcessSection(page);
  const column = page.locator("#ps-process .ps-process-relevance");
  await expect(column.locator("#ps-conditions-list-title")).toHaveText("참여 판정");
  await expect(column).toContainText("참여 판정(RL 분석) · 이 환경에서 꺼져 있음");
  await expect(column).not.toContainText("심층 검토");
  expect(verdictRequests).toEqual([]);
});

test("참여 판정 열은 사업기회의 RL 판정 요약을 옮기고 판정 화면으로 잇는다", async ({ page }) => {
  await mockFeatureFlags(page, { rl_analysis: true, prespec_overview: true });
  const view = completedView({ opportunity_id: 202 });
  await page.route("**/api/opportunities/202/verdict", (route) => route.fulfill({ json: view }));
  await page.goto("/pre-specs/991");
  const column = page.locator("#ps-conditions");
  await expect(column).toContainText(view.result!.verdict);
  await expect(column).toContainText(`차단 조건 ${view.result!.blocking_condition_ids.length}건`);
  await expect(column.getByRole("link", { name: "판정 보기 →" })).toHaveAttribute("href", "/opportunities/202/verdict");
});

test("대시보드의 사전규격 확인 필요 칸은 그 보기의 total이고 같은 보기를 연다", async ({ page }) => {
  await page.goto("/");
  const cell = page.locator('.dash-count-item[data-count="pre-spec-needs-check"]');
  await expect(cell).toContainText("사전규격 확인 필요");
  await expect(cell).toContainText("1건");
  await expect(cell.getByRole("link")).toHaveAttribute("href", "/pre-specs?workspace=needs_check");
  const actionable = page.locator('.dash-count-item[data-count="pre-spec-actionable"]');
  await expect(actionable).toContainText("0건");
  await cell.getByRole("link").click();
  await expect(page.locator(".pre-specs-row").filter({ hasText: "신규 지능형 행정 지원 사전규격" })).toBeVisible();
});
