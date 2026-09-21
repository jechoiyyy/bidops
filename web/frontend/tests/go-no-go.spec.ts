import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";
import { comparisonFor, mockGoNoGo, mockWorkspaceRecovery, queueItemFor, SCENARIOS } from "./go-no-go-fixtures";

/**
 * 최종 Go/No-Go 결정 검토 목록.
 *
 * 승인된 시안(`design-previews/bidops-go-no-go-erp-20260907/`)의 첫 화면이다. 이
 * spec은 화면이 **업무 상태를 옳게 말하는가**를 본다: 결정 대기열 한 번으로 그리는지,
 * 미결정과 오래된 결정을 함께 검토 대상으로 두는지, 조회 중·실패·계산 대기·
 * 비교 없음을 변경 없음이나 미결정으로 접지 않는지, 집계 범위를 밝히는지, 저장은
 * 이 화면에서 하지 않는지.
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

test("기본 검토 대상은 미결정·오래된 결정·효력 미확인을 함께 남기고 입찰공고 미연결은 뺀다", async ({ page }) => {
  await openList(page);

  // 입찰공고가 연결된 미결정 7건 + stale Go 1건 + 효력 미확인 No-Go 1건 = 9건.
  await expect(page.locator(".gng-list-head")).toContainText("최종 결정 목록 · 9건");
  await expect(rows(page)).toHaveCount(9);

  // 오래된 Go 결정이 목록에서 사라지지 않는다. 미결정만 남기면 놓친다.
  const stale = rows(page).filter({ hasText: "교통정보 수집·제공 플랫폼 고도화" });
  await expect(stale).toContainText("Go · 재검토");
  // 현재성을 모르는 결정도 끝난 것이 아니다.
  await expect(rows(page).filter({ hasText: "공고 조건 기준 결정 사업" })).toContainText("No-Go · 효력 미확인");

  // 이미 확정된 현재 결정과 결정할 입찰공고가 없는 사업은 기본 보기에 없다.
  await expect(rows(page).filter({ hasText: "문화시설 통합예약 서비스 구축" })).toHaveCount(0);
  await expect(rows(page).filter({ hasText: "입찰공고 미연결 추적 사업" })).toHaveCount(0);
});

test("보기 탭은 검토 대상·재검토·결정 기록·전체를 서로 다르게 센다", async ({ page }) => {
  await openList(page);
  const tabs = page.locator(".gng-view-tabs");
  await expect(tabs.getByRole("button", { name: /검토 대상/ })).toContainText("9");
  await expect(tabs.getByRole("button", { name: /재검토/ })).toContainText("2");
  await expect(tabs.getByRole("button", { name: /결정 기록/ })).toContainText("4");
  await expect(tabs.getByRole("button", { name: /전체/ })).toContainText(String(SCENARIOS.length));

  await tabs.getByRole("button", { name: /재검토/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("show")).toBe("recheck");
  await expect(rows(page)).toHaveCount(2);
  await expect(rows(page).filter({ hasText: "교통정보 수집·제공 플랫폼 고도화" })).toContainText("Go · 재검토");

  await tabs.getByRole("button", { name: /결정 기록/ }).click();
  await expect(rows(page)).toHaveCount(4);

  // 입찰공고가 없는 사업은 전체 보기에만 있고, 미결정이 아니라 미연결이라고 적는다.
  await tabs.getByRole("button", { name: /전체/ }).click();
  await expect(rows(page).filter({ hasText: "입찰공고 미연결 추적 사업" })).toContainText("입찰공고 미연결");
});

// spec §11.3: 목록은 결정 대기열 한 번으로 그린다. 행마다 workspace를 조회하던 N+1을
// 되살리지 않는다 — 상세는 선택한 사업 하나만 받는다.
test("목록은 결정 대기열 한 번으로 그리고 행마다 비교를 조회하지 않는다", async ({ page }) => {
  await mockApi(page);
  await mockGoNoGo(page, SLOW);
  const queueQueries: Array<Record<string, string>> = [];
  const workspaceIds: number[] = [];
  let opportunityListRequests = 0;
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/bid-delta/decision-queue") queueQueries.push(Object.fromEntries(url.searchParams.entries()));
    if (url.pathname === "/api/opportunities") opportunityListRequests += 1;
    const workspace = /^\/api\/opportunities\/(\d+)\/bid-delta$/.exec(url.pathname);
    if (workspace) workspaceIds.push(Number(workspace[1]));
  });

  await page.goto("/go-no-go?show=all&selected=903");
  await expect(rows(page)).toHaveCount(SCENARIOS.length);
  // 선택한 사업의 상세가 실제로 그려질 때까지 기다린 뒤 센다.
  await expect(page.getByRole("heading", { name: "변경 비교 계산을 기다리고 있습니다" })).toBeVisible();
  expect(queueQueries).toHaveLength(1);
  expect(queueQueries[0]).toMatchObject({ status: "all", limit: "500", offset: "0" });
  expect(opportunityListRequests).toBe(0);
  expect([...new Set(workspaceIds)]).toEqual([903]);

  // 다른 행을 골라도 대기열은 다시 받지 않고 그 행 하나만 조회한다.
  await rows(page).filter({ hasText: "학교 통합정보서비스 운영 및 유지관리" }).locator(".gng-row").click();
  await expect(page.getByRole("heading", { name: "변경 비교 결과가 아직 없습니다" })).toBeVisible();
  expect(queueQueries).toHaveLength(1);
  expect([...new Set(workspaceIds)].sort()).toEqual([903, 904]);
});

test("집계와 검색 범위를 밝히고 대기열이 넘치면 받은 범위 기준이라고 적는다", async ({ page }) => {
  await openList(page);
  await expect(page.locator(".gng-summary")).toContainText(`전체 ${SCENARIOS.length}건 기준`);
  await expect(page.locator(".gng-summary")).not.toContainText("일부");

  const input = page.getByPlaceholder("사업명·발주기관 검색");
  await input.fill("교통정보");
  await expect(rows(page)).toHaveCount(9);
  // 적용 대기 안내는 화면에 그리지 않고 입력칸의 접근 설명으로만 남긴다.
  await expect(input).toHaveAccessibleDescription("Enter로 적용 · 띄어쓰기 무시");
  await input.press("Enter");
  await expect(rows(page)).toHaveCount(1);
  await expect(page.locator(".gng-filter-context")).not.toContainText("받은 범위 안에서만");

  await input.fill("없는사업");
  await expect(rows(page)).toHaveCount(1);
  await input.press("Enter");
  await expect(page.getByText("조건에 맞는 사업이 없습니다", { exact: true })).toBeVisible();
  await expect(page.locator(".gng-list-empty")).toContainText('적용된 검색어 "없는사업"와 다른 활성 보기 조건에 맞는 사업이 없습니다.');
  await page.getByRole("button", { name: "검색어만 지우기", exact: true }).click();
  await expect(rows(page)).toHaveCount(9);

  // 서버 상한(500건)을 넘는 대기열은 받은 범위만 센다고 직접 밝히고 페이저를 둔다.
  await page.route("**/api/bid-delta/decision-queue**", async (route) => {
    const items = SCENARIOS.map((_, index) => queueItemFor(index));
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items, total: 600, limit: 500, offset: 0 }) });
  });
  await page.goto("/go-no-go?show=all&q=교통정보");
  await expect(rows(page)).toHaveCount(1);
  await expect(page.locator(".gng-summary")).toContainText(`받은 ${SCENARIOS.length}건 기준`);
  await expect(page.locator(".gng-summary")).toContainText("전체 600건 중 일부입니다");
  await expect(page.locator(".gng-filter-context")).toContainText("검색은 받은 범위 안에서만 좁힙니다");
  await expect(page.getByRole("navigation", { name: "결정 대기열 페이지" })).toContainText(`1–${SCENARIOS.length} / 600`);
});

test("상세 조회 중·조회 실패·비교 없음·계산 대기를 미결정이나 변경 없음으로 접지 않는다", async ({ page }) => {
  await openList(page, "?show=all");

  // 행의 비교 건수와 사람 결정은 대기열 값이다. 비교 0건은 값으로 적는다.
  await expect(rows(page).filter({ hasText: "학교 통합정보서비스 운영 및 유지관리" })).toContainText("변경 비교 결과 없음");
  await expect(rows(page).filter({ hasText: "시설관리 업무시스템 구축" })).toContainText("변경 비교 1건");

  // 상세 조회가 실패해도 대기열이 준 사람 결정은 그대로이고, 상세를 단정하지 않는다.
  await rows(page).filter({ hasText: "의료정보 연계 기반 구축" }).locator(".gng-row").click();
  await expect(page.getByRole("heading", { name: "비교·결정 상세를 불러오지 못했습니다" })).toBeVisible();
  await expect(rows(page).filter({ hasText: "의료정보 연계 기반 구축" })).toContainText("미결정");
  await expect(page.locator(".gng-action-footer")).toContainText("아직 결정하지 않음");

  await rows(page).filter({ hasText: "관광데이터 분석 환경 구축" }).locator(".gng-row").click();
  await expect(page.getByRole("heading", { name: "비교·결정 상세를 확인하고 있습니다" })).toBeVisible();
  await expect(page.getByText("조회가 끝나기 전에는 변경 없음으로 표시하지 않습니다.", { exact: false })).toBeVisible();
});

test("완료된 비교가 없으면 결정 화면의 공고 조건 근거로 안내하고 저장을 열지 않는다", async ({ page }) => {
  await openList(page, "?show=all&selected=902");
  await expect(page.getByRole("heading", { name: "변경 비교 계산을 기다리고 있습니다" })).toBeVisible();
  await expect(page.locator(".gng-action-footer")).toContainText("공고 조건을 근거로 기록합니다");
  await expect(page.getByRole("button", { name: "공고 조건 검토·결정 열기" })).toBeVisible();
  await expect(page.getByRole("button", { name: "변경 검토·결정 열기" })).toHaveCount(0);

  await page.goto("/go-no-go?show=all&selected=904");
  await expect(page.getByRole("heading", { name: "변경 비교 결과가 아직 없습니다" })).toBeVisible();
  await expect(page.getByText("비교가 없다는 것은 변경이 없다는 뜻이 아닙니다.", { exact: false })).toBeVisible();

  // 입찰공고가 없으면 결정할 공고가 없다고 적는다.
  await page.goto("/go-no-go?show=all&selected=911");
  await expect(page.getByRole("button", { name: "결정 화면 열기" })).toBeVisible();
  await expect(page.locator(".gng-action-footer")).toContainText("연결된 입찰공고가 없어 최종 결정을 기록할 수 없습니다");
  await expect(page.locator(".gng-detail-head")).toContainText("입찰공고 미연결");
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

test("결정 기록 탭은 마지막 결정과 근거 종류만 보여 주고 이력을 지어내지 않는다", async ({ page }) => {
  await openList(page, "?show=all&selected=903");
  await page.getByRole("button", { name: "결정 기록", exact: true }).click();
  const history = page.locator(".gng-decision-history");
  await expect(history).toContainText("Go · 참여");
  await expect(history).toContainText("재검토 필요");
  await expect(history).toContainText("기존 검토자");
  await expect(history).toContainText("결정 이후 새 정정공고 문서 버전이 연결되었습니다.");
  await expect(history).toContainText("비교 결과 기준 · 비교 버전 2");
  await expect(history).toContainText("이 목록은 사업기회의 마지막 결정만 보여 줍니다");
  await expect(page.locator(".gng-history-entry")).toHaveCount(1);

  // 공고 조건 근거 결정은 비교 필드 대신 기준 입찰공고와 관측 해시를 적는다.
  await page.goto("/go-no-go?show=all&selected=912");
  await page.getByRole("button", { name: "결정 기록", exact: true }).click();
  await expect(page.locator(".gng-decision-history")).toContainText("No-Go · 불참");
  await expect(page.locator(".gng-decision-history")).toContainText("공고 조건 기준 · 기준 입찰공고 ID 91200 · 관측 해시 ffffffffffff");
  await expect(page.locator(".gng-decision-history")).not.toContainText("비교 버전");

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

  // `목록 기준`은 상단바 슬롯으로 올라가지만 대화상자는 여전히 이 화면이 연다.
  const dataAction = topbar.getByRole("button", { name: "목록 기준", exact: true });
  await expect(dataAction).toBeVisible();
  await dataAction.click();
  await expect(page.getByRole("dialog")).toContainText("‘계속 추적’인 사업기회만 최종 Go/No-Go 대상입니다");
});

test("중복 페이지 머리말 없이 workspace가 화면의 남은 높이를 채운다", async ({ page }) => {
  await openList(page);

  // 제목·목록 기준은 상단바 하나에만 남고, 예전 페이지 머리말은 다시 생기지 않는다.
  await expect(page.locator("header.topbar[data-topbar-mode='title'] h1")).toHaveCount(1);
  await expect(page.locator(".gng-page-header")).toHaveCount(0);
  await expect(page.locator("#go-no-go-title")).toHaveClass(/visually-hidden/);

  const geometry = await page.locator(".gng-page").evaluate((pageRoot) => {
    // 틀은 이제 공용 `SplitWorkspace`다. 화면 전용 틀이 되살아나면 이 selector가 먼저 깨진다.
    const workspace = pageRoot.querySelector<HTMLElement>('[data-review-primitive="split-workspace"]');
    if (!workspace) throw new Error("missing Go/No-Go workspace");
    const pageRect = pageRoot.getBoundingClientRect();
    const workspaceRect = workspace.getBoundingClientRect();
    return {
      pageBottom: pageRect.bottom,
      workspaceBottom: workspaceRect.bottom,
      workspaceHeight: workspaceRect.height,
    };
  });

  // 필터 아래 workspace의 bottom edge가 page content edge에 붙어야 상세 footer가
  // 별도 페이지 스크롤 없이 화면 안에 남는다.
  expect(Math.abs(geometry.workspaceBottom - geometry.pageBottom)).toBeLessThanOrEqual(1);
  expect(geometry.workspaceHeight).toBeGreaterThan(0);
});

// ADR-0062·시안 M1c — 이 화면의 분할 틀·목록 머리·상세 머리는 발주계획·사전규격과
// 같은 공용 골격이다. 화면 전용 틀로 되돌아가면 네 화면의 목록 폭·머리 여백이 다시
// 따로 움직인다(`explore-workspace-consistency.spec.ts`가 그 값을 실측한다).
test("분할 틀·목록 머리·상세 머리·발주기관 블록이 공용 골격이다", async ({ page }) => {
  await openList(page, "?show=all&selected=901");

  const workspace = page.locator('[data-review-primitive="split-workspace"]');
  await expect(workspace).toHaveCount(1);
  await expect(workspace).toHaveClass(/gng-workspace/);

  // 목록·상세 pane은 공용 골격의 두 면이고 각자 접근 이름을 갖는다.
  const listPane = page.getByRole("region", { name: "최종 결정 검토 목록" });
  const detailPane = page.getByRole("region", { name: "선택한 결정 검토 사업" });
  await expect(listPane).toHaveClass(/review-split-list/);
  await expect(detailPane).toHaveClass(/review-split-detail/);
  await expect(listPane.locator(".review-list-head")).toContainText("최종 결정 목록 · ");
  // 페이저는 목록 pane 안쪽 바닥에만 있다(명세 §2.2).
  await expect(listPane.locator('[data-review-primitive="list-pager"]')).toHaveCount(1);
  await expect(page.locator('[data-review-primitive="list-pager"]')).toHaveCount(1);

  // 상세 머리는 공용 sticky 머리이고 발주기관은 공용 강조 블록으로 먼저 읽힌다.
  const detailHead = detailPane.locator('[data-review-primitive="sticky-decision-header"]');
  await expect(detailHead).toHaveClass(/gng-detail-head/);
  await expect(detailHead.locator('[data-review-primitive="agency-feature"]')).toContainText("해솔시청");
});

test("상세를 스크롤해도 상세 머리는 뷰포트 안에 남는다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await openList(page, "?show=all&selected=901");
  await expect(page.locator(".gng-delta-counts")).toBeVisible();

  const head = page.locator(".gng-detail-head");
  const scroller = page.locator(".gng-detail-scroll");
  const before = await head.boundingBox();
  if (!before) throw new Error("missing detail header box");

  // 본문이 실제로 스크롤되는 상태를 먼저 만든다. 스크롤이 없으면 아래 단언은
  // 머리가 붙어 있다는 것을 증명하지 못한다.
  const scrollable = await scroller.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
    return element.scrollHeight - element.clientHeight;
  });
  expect(scrollable).toBeGreaterThan(0);
  await expect.poll(() => scroller.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);

  const after = await head.boundingBox();
  if (!after) throw new Error("missing detail header box after scroll");
  expect(after.y).toBeCloseTo(before.y, 0);
  expect(after.y).toBeGreaterThanOrEqual(0);
  expect(after.y + after.height).toBeLessThanOrEqual(800);
  // 머리에 있던 사업명·발주기관은 스크롤 뒤에도 그대로 읽힌다.
  await expect(head).toContainText("공공데이터 통합관리체계 고도화");
  await expect(head).toContainText("해솔시청");
});

// 조회 중에 화면이 통째로 접혔다 펴지면 사람이 보던 자리를 잃는다(발주계획·사업
// 추적과 같은 규칙). 대기열이 아직 안 왔을 때 건수를 0건으로 적지도 않는다.
test("조회 중에도 분할 골격이 남고 건수를 0건으로 적지 않는다", async ({ page }) => {
  await mockApi(page);
  await mockGoNoGo(page, SLOW);
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/bid-delta/decision-queue**", async (route) => {
    await held;
    await route.fallback();
  });

  await page.goto("/go-no-go");

  const listPane = page.getByRole("region", { name: "최종 결정 검토 목록" });
  const detailPane = page.getByRole("region", { name: "선택한 결정 검토 사업" });
  await expect(listPane).toBeVisible();
  await expect(detailPane).toBeVisible();
  await expect(page.locator(".gng-list-head")).toContainText("최종 결정 목록 · 불러오는 중");
  await expect(listPane.getByRole("status")).toContainText("최종 결정 대기열을 불러오는 중");
  await expect(detailPane).toContainText("목록을 불러온 뒤 사업 상세를 표시합니다.");
  // 받지 못한 범위를 요약·페이저로 말하지 않는다.
  await expect(page.locator(".gng-summary")).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "결정 대기열 페이지" })).toHaveCount(0);

  release();
  await expect(page.locator(".gng-row").first()).toBeVisible();
  await expect(page.locator(".gng-list-head")).toContainText("최종 결정 목록 · 9건");
  await expect(page.locator(".gng-summary")).toBeVisible();
});

test("대기열 조회 실패도 분할 골격 안에서 말하고 건수를 0건으로 적지 않는다", async ({ page }) => {
  await mockApi(page);
  await mockGoNoGo(page, SLOW);
  await page.route("**/api/bid-delta/decision-queue**", async (route) => {
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "queue unavailable" }) });
  });

  await page.goto("/go-no-go");

  const listPane = page.getByRole("region", { name: "최종 결정 검토 목록" });
  await expect(listPane).toBeVisible();
  await expect(page.locator(".gng-list-head")).toContainText("최종 결정 목록 · 건수 확인 불가");
  await expect(page.locator(".gng-list-empty")).toContainText("최종 결정 대기열을 불러오지 못했습니다.");
  await expect(page.locator(".gng-list-empty")).toContainText("조회 실패를 결정 대기 없음으로 해석하지 않습니다.");
  await expect(page.getByRole("region", { name: "선택한 결정 검토 사업" }))
    .toContainText("목록을 불러오지 못해 상세를 표시할 수 없습니다.");
  await expect(page.locator(".gng-summary")).toHaveCount(0);
});

test("목록 기준은 API 경계와 집계 범위를 기본 화면 밖에서 설명한다", async ({ page }) => {
  await openList(page);
  await page.getByRole("button", { name: "목록 기준", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("‘계속 추적’인 사업기회만 최종 Go/No-Go 대상입니다");
  await expect(dialog).toContainText("최종 결정 대기열을 한 번 받아 그립니다");
  await expect(dialog).toContainText("입찰공고가 연결되지 않은 사업은 결정할 공고가 없어 전체 보기에만 둡니다");
  await expect(dialog).toContainText("변경 비교를 계산하는 프로그램은 아직 운영에 없습니다");
  await expect(dialog).toContainText("최종 결정 저장은 결정 화면에서만 합니다");
});

// 실패한 것은 결정 대기열이 아니라 **선택한 사업의 비교·결정 상세 조회**다. 대기열을
// 다시 받아 봐야 실패한 workspace 조회는 그대로 실패로 남는다.
test("선택한 사업의 상세 조회 실패는 그 조회를 다시 불러 회복한다", async ({ page }) => {
  await mockApi(page);
  await mockGoNoGo(page, SLOW);
  const trace = await mockWorkspaceRecovery(page);
  await page.goto("/go-no-go?show=all&selected=909");

  const failedRow = rows(page).filter({ hasText: "의료정보 연계 기반 구축" });
  await expect(page.getByRole("heading", { name: "비교·결정 상세를 불러오지 못했습니다" })).toBeVisible();
  // 행의 사람 결정은 대기열 값이라 상세 조회 실패와 무관하게 그대로다.
  await expect(failedRow).toContainText("미결정");
  const failedGets = trace.gets;
  expect(failedGets).toBeGreaterThan(0);

  trace.recover();
  await page.getByRole("button", { name: "다시 조회", exact: true }).click();

  // 같은 조회가 다시 나가고, 회복된 뒤에는 실제 상태를 말한다.
  await expect.poll(() => trace.gets).toBeGreaterThan(failedGets);
  await expect(page.getByRole("heading", { name: "비교·결정 상세를 불러오지 못했습니다" })).toHaveCount(0);
  await expect(page.locator(".gng-delta-counts")).toBeVisible();
  await expect(page.getByRole("button", { name: "다시 조회", exact: true })).toHaveCount(0);
});
