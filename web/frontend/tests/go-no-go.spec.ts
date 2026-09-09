import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";
import { comparisonFor, mockGoNoGo, mockWorkspaceRecovery } from "./go-no-go-fixtures";

/**
 * 최종 Go/No-Go 결정 검토 목록.
 *
 * 승인된 시안(`design-previews/bidops-go-no-go-erp-20260907/`)의 첫 화면이다. 이
 * spec은 화면이 **업무 상태를 옳게 말하는가**를 본다: 계속 추적만 대상인지,
 * 미결정과 오래된 결정을 함께 검토 대상으로 두는지, 조회 중·실패·계산 대기·
 * 비교 없음을 변경 없음이나 미결정으로 접지 않는지, 집계가 받은 페이지 기준이라고
 * 밝히는지, 저장은 이 화면에서 하지 않는지.
 *
 * 공유 `api-mock.ts`는 고치지 않는다. 고정 입력은 `go-no-go-fixtures.ts`가 준다.
 */

const SLOW = { slowMs: 60_000 };

async function openList(page: Page, search = "", options = SLOW): Promise<void> {
  await mockApi(page);
  await mockGoNoGo(page, options);
  await page.goto(`/go-no-go${search}`);
  await expect(page.locator(".gng-row").first()).toBeVisible();
}

/** 목록 한 행. 사업명·발주기관 칸(`.gng-row`)과 사람 결정 칸이 한 줄이다. */
function rows(page: Page) {
  return page.locator(".gng-table-scroll tbody tr");
}

test("기본 검토 대상은 미결정과 오래된 결정·조회 미확인을 함께 남긴다", async ({ page }) => {
  await openList(page);

  // 미결정 5건 + stale Go 1건 + 조회 실패 1건 + 조회 중 1건 = 8건.
  await expect(page.locator(".gng-list-head")).toContainText("결정 검토 목록 · 8건");
  await expect(rows(page)).toHaveCount(8);

  // 오래된 Go 결정이 목록에서 사라지지 않는다. 미결정만 남기면 놓친다.
  const stale = rows(page).filter({ hasText: "교통정보 수집·제공 플랫폼 고도화" });
  await expect(stale).toContainText("Go · 재검토");

  // 이미 확정된 현재 결정은 기본 보기에 없다.
  await expect(rows(page).filter({ hasText: "문화시설 통합예약 서비스 구축" })).toHaveCount(0);
});

test("보기 탭은 검토 대상·재검토·결정 기록·전체를 서로 다르게 센다", async ({ page }) => {
  await openList(page);
  const tabs = page.locator(".gng-view-tabs");
  await expect(tabs.getByRole("button", { name: /검토 대상/ })).toContainText("8");
  await expect(tabs.getByRole("button", { name: /재검토/ })).toContainText("1");
  await expect(tabs.getByRole("button", { name: /결정 기록/ })).toContainText("3");
  await expect(tabs.getByRole("button", { name: /전체/ })).toContainText("10");

  await tabs.getByRole("button", { name: /재검토/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("show")).toBe("recheck");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("Go · 재검토");

  await tabs.getByRole("button", { name: /결정 기록/ }).click();
  await expect(rows(page)).toHaveCount(3);
});

test("집계와 검색 범위가 받은 페이지 기준이라고 밝힌다", async ({ page }) => {
  await openList(page);
  await expect(page.locator(".gng-summary")).toContainText("받은 10건 기준");
  await expect(page.locator(".gng-summary")).toContainText("전체 총계가 아닙니다");

  await page.getByPlaceholder("사업명·발주기관 검색").fill("교통");
  await expect(rows(page)).toHaveCount(1);
  await expect(page.locator(".gng-filter-context")).toContainText("검색은 받은 페이지 안에서만 좁힙니다");

  await page.getByPlaceholder("사업명·발주기관 검색").fill("없는사업");
  await expect(page.getByRole("heading", { name: "조건에 맞는 사업이 없습니다" })).toBeVisible();
  await expect(page.getByText("전체에 없다는 뜻은 아닙니다.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "필터 초기화", exact: true }).click();
  await expect(rows(page)).toHaveCount(8);
});

test("조회 중·조회 실패·비교 없음·계산 대기를 미결정이나 변경 없음으로 접지 않는다", async ({ page }) => {
  await openList(page, "?show=all");

  await expect(rows(page).filter({ hasText: "의료정보 연계 기반 구축" })).toContainText("조회 실패");
  await expect(rows(page).filter({ hasText: "관광데이터 분석 환경 구축" })).toContainText("조회 중");
  await expect(rows(page).filter({ hasText: "학교 통합정보서비스 운영 및 유지관리" })).toContainText("변경 비교 결과 없음");
  await expect(rows(page).filter({ hasText: "시설관리 업무시스템 구축" })).toContainText("계산 대기");

  // 조회 실패 행을 골라도 결정 상태를 단정하지 않는다.
  await rows(page).filter({ hasText: "의료정보 연계 기반 구축" }).click();
  await expect(page.getByRole("heading", { name: "결정 상태를 불러오지 못했습니다" })).toBeVisible();
  await expect(page.getByText("조회가 끝나기 전에는 미결정 또는 변경 없음으로 표시하지 않습니다.")).toBeVisible();
  await expect(page.locator(".gng-action-footer")).toContainText("미확인");
});

test("계산 대기·비교 없음 상세는 결정 화면으로만 데려가고 저장을 열지 않는다", async ({ page }) => {
  await openList(page, "?show=all&selected=902");
  await expect(page.getByRole("heading", { name: "변경 비교 계산을 기다리고 있습니다" })).toBeVisible();
  await expect(page.locator(".gng-action-footer")).toContainText("계산 완료 전에는 최종 결정을 기록할 수 없습니다");
  await expect(page.getByRole("button", { name: "비교 상태 확인" })).toBeVisible();
  await expect(page.getByRole("button", { name: "변경 검토·결정 열기" })).toHaveCount(0);

  await page.goto("/go-no-go?show=all&selected=904");
  await expect(page.getByRole("heading", { name: "변경 비교 결과가 아직 없습니다" })).toBeVisible();
  await expect(page.getByText("비교가 없다는 것은 변경이 없다는 뜻이 아닙니다.", { exact: false })).toBeVisible();
});

test("완료된 비교는 중요·비중요·확인 필요를 서로 다르게 세고 실제 0을 0으로 적는다", async ({ page }) => {
  await openList(page, "?show=all&selected=901");
  const counts = page.locator(".gng-delta-counts");
  await expect(counts).toBeVisible();
  await expect(counts.locator("> div").nth(0)).toContainText("중요 변경");
  await expect(counts.locator("> div").nth(0)).toContainText("2");
  await expect(counts.locator("> div").nth(1)).toContainText("비중요 변경");
  await expect(counts.locator("> div").nth(1)).toContainText("1");
  await expect(counts.locator("> div").nth(2)).toContainText("확인 필요");
  await expect(counts.locator("> div").nth(2)).toContainText("1");
  await expect(counts.locator("> div").nth(2)).toContainText("unknown·분석 실패");
  await expect(page.getByText("확인 필요를 변경 없음으로 읽지 않습니다.", { exact: false })).toBeVisible();

  // 결정 전에 볼 항목은 중요 변경과 확인 필요만 남긴다.
  const deltaRows = page.locator(".gng-delta-row");
  await expect(deltaRows).toHaveCount(3);
  await expect(deltaRows.filter({ hasText: "평가" })).toHaveCount(0);
  await expect(deltaRows.filter({ hasText: "참가자격" })).toContainText("양쪽 근거가 갖춰지지 않아");

  // 실제 0건은 0으로 적는다(전 범주 변경 없음).
  await page.goto("/go-no-go?show=all&selected=905");
  await expect(page.getByText("양쪽 근거로 확인한 범위에서 결정 전에 볼 변경 항목이 없습니다.")).toBeVisible();
  await expect(page.getByText("변경 없음은 입찰 참여에 대한 추천이 아닙니다.")).toBeVisible();
  await expect(page.locator(".gng-delta-counts").locator("> div").nth(0)).toContainText("0");
});

test("근거 대화상자는 양쪽 원문과 검증 상태를 그대로 보여 준다", async ({ page }) => {
  await openList(page, "?show=all&selected=901");
  await page.locator(".gng-delta-row").first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("기준 사전규격");
  await expect(dialog).toContainText("대상 입찰공고");
  await expect(dialog).toContainText("연계 대상 시스템 3개 (기준 원문 1)");
  await expect(dialog).toContainText("verified · 검증됨");
  await dialog.getByRole("button", { name: "닫기", exact: true }).click();

  // 양쪽 근거가 없는 항목은 변경 없음이나 요건 충족으로 해석하지 않는다.
  await page.locator(".gng-delta-row").filter({ hasText: "참가자격" }).click();
  await expect(page.getByRole("dialog")).toContainText("양쪽 근거가 갖춰지지 않았습니다.");
});

test("비교 문서 탭은 API가 준 양쪽 문서 스냅숏만 보여 준다", async ({ page }) => {
  await openList(page, "?show=all&selected=901");
  await page.getByRole("button", { name: "비교 문서", exact: true }).click();
  const documents = page.locator(".gng-documents");
  await expect(documents).toContainText("PS-2026-901");
  await expect(documents).toContainText("BN-2026-901");
  await expect(documents).toContainText("문서 버전 1");
  await expect(documents).toContainText("문서 버전 2");
  await expect(documents).toContainText("문서 쌍은 화면이 고르지 않습니다");

  // 비교가 없으면 문서가 없다고 단정하지 않는다.
  await page.goto("/go-no-go?show=all&selected=904");
  await page.getByRole("button", { name: "비교 문서", exact: true }).click();
  await expect(page.getByText("문서가 없다는 뜻은 아닙니다.", { exact: false })).toBeVisible();
});

test("결정 기록 탭은 마지막 결정만 보여 주고 이력을 지어내지 않는다", async ({ page }) => {
  await openList(page, "?show=all&selected=903");
  await page.getByRole("button", { name: "결정 기록", exact: true }).click();
  const history = page.locator(".gng-decision-history");
  await expect(history).toContainText("Go · 참여");
  await expect(history).toContainText("재검토 필요");
  await expect(history).toContainText("기존 검토자");
  await expect(history).toContainText("결정 이후 새 정정공고 문서 버전이 연결되었습니다.");
  await expect(history).toContainText("전체 이력은 결정 화면에 있습니다");
  await expect(page.locator(".gng-history-entry")).toHaveCount(1);

  // 결정이 없으면 없다고 적고 추적 상태를 결정으로 승격하지 않는다.
  await page.goto("/go-no-go?show=all&selected=901");
  await page.getByRole("button", { name: "결정 기록", exact: true }).click();
  await expect(page.getByText("아직 기록된 최종 결정이 없습니다.")).toBeVisible();
  await expect(page.getByText("추적 상태 ‘계속 추적’은 입찰 참여를 결정했다는 뜻이 아닙니다.")).toBeVisible();
});

test("오래된 결정은 상세에서 재검토로 보이고 현재 승인으로 읽히지 않는다", async ({ page }) => {
  await openList(page, "?show=all&selected=903");
  await expect(page.locator(".gng-review-notice")).toContainText("기존 Go 결정을 다시 검토해야 합니다");
  await expect(page.locator(".gng-review-notice")).toContainText("이전 결정 기록은 보존되며 새 결정은 덮어쓰지 않고 추가됩니다");
  await expect(page.locator(".gng-action-footer")).toContainText("Go · 재검토 필요");
});

test("결정 화면 열기는 선택한 비교와 돌아올 검색 조건을 함께 넘긴다", async ({ page }) => {
  await openList(page, "?show=all&selected=901");
  await page.getByRole("button", { name: "변경 검토·결정 열기" }).click();
  await expect(page).toHaveURL(/\/opportunities\/901\/bid-delta\?/);
  const url = new URL(page.url());
  expect(url.searchParams.get("comparison")).toBe(comparisonFor(0)?.id);
  expect(url.searchParams.get("back")).toContain("selected=901");

  // 돌아오는 길이 원래 보기와 선택을 되살린다.
  await page.getByRole("link", { name: "결정 목록으로" }).click();
  await expect(page).toHaveURL(/\/go-no-go\?/);
  await expect.poll(() => new URL(page.url()).searchParams.get("selected")).toBe("901");
});

test("추적 상태가 계속 추적인 사업기회만 조회한다", async ({ page }) => {
  const queries: Array<Record<string, string>> = [];
  await mockApi(page);
  await mockGoNoGo(page, SLOW);
  // 마지막에 등록한 handler 가 먼저 잡는다. 세기만 하고 고정 입력으로 넘긴다.
  await page.route(/\/api\/opportunities(\?|$)/, async (route) => {
    const url = new URL(route.request().url());
    queries.push(Object.fromEntries(url.searchParams.entries()));
    await route.fallback();
  });
  await page.goto("/go-no-go");
  await expect(page.locator(".gng-row").first()).toBeVisible();
  expect(queries[0]).toMatchObject({ tracking_status: "계속 추적", limit: "25", offset: "0" });
});

// 목록 4화면은 상단바가 제목을 그리고 페이지는 제목 줄을 두지 않는다(계획서 §1).
// 화면 안에 제목이 다시 생기면 세로 공간을 두 번 쓰고 h1/h2가 같은 말을 반복한다.
test("화면 제목과 페이지 액션은 상단바에 있고 경로·편집 범위는 그리지 않는다", async ({ page }) => {
  await openList(page);
  const topbar = page.locator("header.topbar");

  await expect(topbar).toHaveAttribute("data-topbar-mode", "title");
  await expect(topbar.locator("h1")).toHaveText("최종 Go/No-Go");
  await expect(topbar.locator(".topbar-breadcrumb")).toHaveCount(0);
  await expect(topbar.locator(".topbar-status")).toHaveCount(0);

  // 페이지에 남는 제목은 landmark 이름과 h1 → h2 위계를 위한 숨긴 제목 하나다.
  await expect(page.locator("#go-no-go-title")).toHaveClass(/visually-hidden/);

  // `데이터 현황`은 상단바 슬롯으로 올라가지만 대화상자는 여전히 이 화면이 연다.
  const dataAction = topbar.getByRole("button", { name: "데이터 현황", exact: true });
  await expect(dataAction).toBeVisible();
  await dataAction.click();
  await expect(page.getByRole("dialog")).toContainText("‘계속 추적’인 사업기회만 최종 Go/No-Go 대상입니다");
});

test("데이터 현황은 API 경계와 집계 범위를 기본 화면 밖에서 설명한다", async ({ page }) => {
  await openList(page);
  await page.getByRole("button", { name: "데이터 현황", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("‘계속 추적’인 사업기회만 최종 Go/No-Go 대상입니다");
  await expect(dialog).toContainText("전체 총계가 아닙니다");
  await expect(dialog).toContainText("변경 비교를 계산하는 프로그램은 아직 운영에 없습니다");
  await expect(dialog).toContainText("최종 결정 저장은 결정 화면에서만 합니다");
});

// 실패한 것은 사업기회 목록이 아니라 **이 행의 결정 상태 조회**다. 목록을 다시
// 받아 봐야 실패한 workspace 조회는 그대로 실패로 남는다.
test("결정 상태 조회 실패는 그 조회를 다시 불러 회복한다", async ({ page }) => {
  await mockApi(page);
  await mockGoNoGo(page, SLOW);
  const trace = await mockWorkspaceRecovery(page);
  await page.goto("/go-no-go?show=all&selected=909");

  const failedRow = rows(page).filter({ hasText: "의료정보 연계 기반 구축" });
  await expect(failedRow).toContainText("조회 실패");
  await expect(page.getByRole("heading", { name: "결정 상태를 불러오지 못했습니다" })).toBeVisible();
  const failedGets = trace.gets;
  expect(failedGets).toBeGreaterThan(0);

  trace.recover();
  await page.getByRole("button", { name: "다시 조회", exact: true }).click();

  // 같은 조회가 다시 나가고, 회복된 뒤에는 실제 상태를 말한다.
  await expect.poll(() => trace.gets).toBeGreaterThan(failedGets);
  await expect(failedRow).toContainText("미결정");
  await expect(page.getByRole("heading", { name: "결정 상태를 불러오지 못했습니다" })).toHaveCount(0);
  await expect(page.locator(".gng-delta-counts")).toBeVisible();
  await expect(page.getByRole("button", { name: "다시 조회", exact: true })).toHaveCount(0);
});
