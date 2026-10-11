import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockCompanyWorkspace, type CompanyWorkspaceMockTrace } from "./api-mock";
import { COMPANY_BY_SLUG, COMPANY_NOTICE_FIXTURES, companyFitAttempts } from "./fixtures/company-demo";

/*
 * DEMO-04 STEP-003 · spec T3(필터·정렬·쪽 이동을 서버가 적용, 핏 판정 이력의 unknown/null/실패)와
 * T6의 목록·상세 부분(주소 정본, 허용값 밖 복원).
 *
 * 고정 응답은 `tests/api-mock.ts`의 `mockCompanyWorkspace`이며 실제 백엔드에 연결하지 않는다.
 * 목록 조건이 서버로 갔는지는 mock이 남긴 요청 기록(`trace.requests`)으로 확인하고,
 * 브라우저가 이미 받은 쪽을 다시 거르지 않는다는 것은 서버 응답을 일부러 조건과 다르게 주어 확인한다.
 */

const company = COMPANY_BY_SLUG["demo-public-si"];
const listPath = `/companies/${company.company_id}/pre-specs`;
const selectionKey = `bidops.companies.${company.company_id}.pre-specs.selection.v1`;

async function installMocks(page: Page) {
  await mockApi(page);
  return mockCompanyWorkspace(page);
}

const table = (page: Page) => page.getByRole("table", { name: "회사별 사전규격 판정" });
const rows = (page: Page) => table(page).locator("tbody tr");
const rowIds = (page: Page) => rows(page).evaluateAll((items) => items.map((item) => item.getAttribute("data-notice-id")));
const fitSelect = (page: Page) => page.getByRole("combobox", { name: "핏 판정 필터" });
const trackingSelect = (page: Page) => page.getByRole("combobox", { name: "추적 결정 필터" });
const sortSelect = (page: Page) => page.getByRole("combobox", { name: "정렬" });
const searchBox = (page: Page) => page.getByRole("searchbox", { name: "사전규격 검색" });
const pager = (page: Page) => page.getByRole("navigation", { name: "회사 사전규격 페이지" });
const aside = (page: Page) => page.getByRole("complementary", { name: "선택한 사전규격" });
const row = (page: Page, noticeId: number) => table(page).locator(`tr[data-notice-id="${noticeId}"]`);
const select = (page: Page, noticeId: number) => row(page, noticeId).locator("button.cw-row-select");

/** 회사 목록 조회의 query 모음(상세 `…/pre-specs/{id}`는 제외). */
function listRequests(trace: CompanyWorkspaceMockTrace): Array<Record<string, string>> {
  return trace.requests
    .filter((entry) => entry.startsWith(`GET /api/companies/${company.company_id}/pre-specs?`))
    .map((entry) => Object.fromEntries(new URL(entry.split(" ")[1], "http://localhost").searchParams));
}

/** 가장 최근 목록 요청의 query. 요청이 아직 없으면 빈 객체다(호출자가 expect.poll로 기다린다). */
function lastListRequest(trace: CompanyWorkspaceMockTrace): Record<string, string> {
  const all = listRequests(trace);
  return all[all.length - 1] ?? {};
}

function urlParam(page: Page, name: string): string | null {
  return new URL(page.url()).searchParams.get(name);
}

function gate() {
  let release: () => void = () => {};
  const promise = new Promise<void>((resolve) => { release = resolve; });
  return { promise, release };
}

test("T3: 목록 기본 요청은 정렬·쪽 크기·offset만 서버로 보낸다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto(listPath);
  await expect(rows(page)).toHaveCount(4);
  await expect.poll(() => rowIds(page)).toEqual(["7101", "7102", "7103", "7104"]);
  await expect.poll(() => lastListRequest(trace)).toEqual({ sort: "posted_at_desc", limit: "20", offset: "0" });
  await expect(fitSelect(page)).toHaveValue("all");
  await expect(trackingSelect(page)).toHaveValue("all");
  await expect(sortSelect(page)).toHaveValue("posted_at_desc");
  await expect(searchBox(page)).toHaveValue("");
  await expect(pager(page)).toContainText("전체 4건");
  await expect(pager(page)).toContainText("1–4 / 4");
  // 게시·마감: 값이 있으면 날짜, null이면 '미확인'(7103의 마감일은 null).
  await expect(row(page, 7103).locator("[data-deadline-at]")).toHaveAttribute("data-deadline-at", "null");
  await expect(row(page, 7103)).toContainText("마감일 미확인");
  await expect(row(page, 7101)).toContainText("마감 ");
  await expect(row(page, 7101)).not.toContainText("마감일 미확인");
});

test("T3: 핏 필터는 주소와 서버 요청에 실리고, 서버가 준 행을 브라우저가 다시 거르지 않는다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto(listPath);
  await expect(rows(page)).toHaveCount(4);

  await fitSelect(page).selectOption("matched");
  await expect.poll(() => urlParam(page, "fit")).toBe("matched");
  await expect(rows(page)).toHaveCount(1);
  await expect.poll(() => lastListRequest(trace)).toMatchObject({ fit: "matched", offset: "0" });
  await expect(rows(page).first().locator("[data-fit-decision]")).toHaveAttribute("data-fit-decision", "matched");
  await expect(pager(page)).toContainText("전체 1건");

  await fitSelect(page).selectOption("unknown");
  await expect.poll(() => urlParam(page, "fit")).toBe("unknown");
  await expect(rows(page)).toHaveCount(1);
  await expect.poll(() => rowIds(page)).toEqual(["7102"]);
  await expect.poll(() => lastListRequest(trace).fit).toBe("unknown");

  await fitSelect(page).selectOption("mismatch");
  await expect.poll(() => rowIds(page)).toEqual(["7103"]);

  // 새로고침해도 주소가 정본이다: 선택값·요청이 같다.
  await page.reload();
  await expect(fitSelect(page)).toHaveValue("mismatch");
  await expect(rows(page)).toHaveCount(1);
  await expect.poll(() => lastListRequest(trace)).toMatchObject({ fit: "mismatch" });

  // 전체로 돌리면 fit 인자가 요청에서도 주소에서도 사라진다.
  await fitSelect(page).selectOption("all");
  await expect(rows(page)).toHaveCount(4);
  expect(urlParam(page, "fit")).toBeNull();
  await expect.poll(() => lastListRequest(trace).fit).toBeUndefined();

  // 서버가 조건과 다른 행을 줘도(요청에서 fit을 뺀 응답) 화면은 받은 그대로 그린다. 브라우저 쪽 필터가 없다.
  await page.route(/\/api\/companies\/[^/]+\/pre-specs\?/, async (route) => {
    const url = new URL(route.request().url());
    url.searchParams.delete("fit");
    await route.fallback({ url: url.toString() });
  });
  await fitSelect(page).selectOption("matched");
  await expect.poll(() => urlParam(page, "fit")).toBe("matched");
  await expect(rows(page)).toHaveCount(4);
  await expect(pager(page)).toContainText("전체 4건");
});

test("T3: 추적·검색·정렬 조건이 서버 요청과 주소에 실리고 마감일 없음은 서버 순서대로 뒤에 온다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto(listPath);
  await expect(rows(page)).toHaveCount(4);

  await trackingSelect(page).selectOption("계속 추적");
  await expect.poll(() => urlParam(page, "tracking_status")).toBe("계속 추적");
  await expect.poll(() => rowIds(page)).toEqual(["7101"]);
  await expect.poll(() => lastListRequest(trace)).toMatchObject({ tracking_status: "계속 추적", offset: "0" });
  await expect(rows(page).first().locator("[data-tracking-status]")).toHaveAttribute("data-tracking-status", "계속 추적");

  await trackingSelect(page).selectOption("미선택");
  await expect.poll(() => rowIds(page)).toEqual(["7102"]);
  await expect.poll(() => lastListRequest(trace).tracking_status).toBe("미선택");
  await trackingSelect(page).selectOption("all");
  await expect(rows(page)).toHaveCount(4);

  await searchBox(page).fill("클라우드");
  await searchBox(page).press("Enter");
  await expect.poll(() => urlParam(page, "q")).toBe("클라우드");
  await expect.poll(() => rowIds(page)).toEqual(["7103"]);
  await expect.poll(() => lastListRequest(trace)).toMatchObject({ q: "클라우드", offset: "0" });
  await page.getByRole("button", { name: "필터 초기화" }).click();
  await expect(rows(page)).toHaveCount(4);
  expect(urlParam(page, "q")).toBeNull();
  await expect(searchBox(page)).toHaveValue("");

  await sortSelect(page).selectOption("deadline_asc");
  await expect.poll(() => urlParam(page, "sort")).toBe("deadline_asc");
  // 마감 빠른 순, 마감일 없음(7103)은 맨 뒤. 순서는 서버가 정한다.
  await expect.poll(() => rowIds(page)).toEqual(["7102", "7101", "7104", "7103"]);
  await expect.poll(() => lastListRequest(trace).sort).toBe("deadline_asc");
  await expect(rows(page).last()).toContainText("마감일 미확인");

  await page.reload();
  await expect(sortSelect(page)).toHaveValue("deadline_asc");
  await expect.poll(() => rowIds(page)).toEqual(["7102", "7101", "7104", "7103"]);
});

test("T6: 허용값 밖의 주소 인자는 기본값으로 복원되고 서버로 가지 않는다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto(`${listPath}?fit=bogus&tracking_status=zz&sort=score_desc&limit=abc&offset=-3`);
  await expect(rows(page)).toHaveCount(4);
  await expect.poll(() => lastListRequest(trace)).toEqual({ sort: "posted_at_desc", limit: "20", offset: "0" });
  await expect(fitSelect(page)).toHaveValue("all");
  await expect(trackingSelect(page)).toHaveValue("all");
  await expect(sortSelect(page)).toHaveValue("posted_at_desc");

  // 쪽 크기 상한(100)을 넘기거나 0이면 기본값, 'all'은 허용값이 아니다.
  await page.goto(`${listPath}?limit=500&fit=all&offset=1.5`);
  await expect(rows(page)).toHaveCount(4);
  await expect.poll(() => lastListRequest(trace)).toEqual({ sort: "posted_at_desc", limit: "20", offset: "0" });
  await page.goto(`${listPath}?limit=0`);
  await expect(rows(page)).toHaveCount(4);
  await expect.poll(() => lastListRequest(trace).limit).toBe("20");

  // 너무 긴 검색어는 적용하지 않는다(서버로도 가지 않는다).
  await page.goto(`${listPath}?q=${"가".repeat(101)}`);
  await expect(rows(page)).toHaveCount(4);
  await expect.poll(() => lastListRequest(trace).q).toBeUndefined();
  await expect(searchBox(page)).toHaveValue("");
});

test("T3: 쪽 이동은 limit/offset을 서버로 보내고 주소에 남기며 쪽을 넘어도 선택을 지우지 않는다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto(`${listPath}?limit=2`);
  await expect(rows(page)).toHaveCount(2);
  await expect.poll(() => rowIds(page)).toEqual(["7101", "7102"]);
  await expect.poll(() => lastListRequest(trace)).toEqual({ sort: "posted_at_desc", limit: "2", offset: "0" });
  await expect(pager(page)).toContainText("1–2 / 4");
  await expect(pager(page).getByRole("button", { name: "이전" })).toBeDisabled();

  await select(page, 7102).click();
  await expect(select(page, 7102)).toHaveAttribute("aria-pressed", "true");

  await pager(page).getByRole("button", { name: "다음" }).click();
  await expect.poll(() => urlParam(page, "offset")).toBe("2");
  expect(urlParam(page, "limit")).toBe("2");
  await expect.poll(() => rowIds(page)).toEqual(["7103", "7104"]);
  await expect.poll(() => lastListRequest(trace)).toEqual({ sort: "posted_at_desc", limit: "2", offset: "2" });
  await expect(pager(page)).toContainText("3–4 / 4");
  await expect(pager(page).getByRole("button", { name: "다음" })).toBeDisabled();
  // 다른 쪽에 있는 선택은 지우지 않고 그 사실을 알린다.
  await expect(aside(page)).toContainText("선택했던 notice 7102가 이 쪽 목록에 없습니다.");

  await pager(page).getByRole("button", { name: "이전" }).click();
  await expect.poll(() => urlParam(page, "offset")).toBeNull();
  await expect.poll(() => rowIds(page)).toEqual(["7101", "7102"]);
  await expect(select(page, 7102)).toHaveAttribute("aria-pressed", "true");

  // 새로고침도 주소가 정본이다.
  await pager(page).getByRole("button", { name: "다음" }).click();
  await page.reload();
  await expect.poll(() => rowIds(page)).toEqual(["7103", "7104"]);
  await expect.poll(() => lastListRequest(trace)).toEqual({ sort: "posted_at_desc", limit: "2", offset: "2" });

  // 범위를 넘은 offset은 빈 목록을 성공처럼 그리지 않고 첫 쪽으로 돌아가는 길을 준다.
  await page.goto(`${listPath}?offset=40`);
  await expect(page.getByText("이 쪽에 표시할 항목이 없습니다.")).toBeVisible();
  await expect(table(page)).toHaveCount(0);
  await page.getByRole("button", { name: "첫 쪽으로" }).click();
  await expect(rows(page)).toHaveCount(4);
  expect(urlParam(page, "offset")).toBeNull();
});

test("T3: 의미 필터가 바뀌면 offset과 회사별 선택이 초기화되고, 정렬 변경은 선택을 유지한다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto(`${listPath}?limit=2&offset=2`);
  await expect.poll(() => rowIds(page)).toEqual(["7103", "7104"]);
  await select(page, 7103).click();
  await expect(select(page, 7103)).toHaveAttribute("aria-pressed", "true");
  const before = await page.evaluate((key) => JSON.parse(window.sessionStorage.getItem(key) ?? "null"), selectionKey);
  expect(before).toMatchObject({ activeId: 7103, selectionGeneration: 0 });

  // 정렬 변경은 선택을 유지한다(offset은 첫 쪽으로).
  await sortSelect(page).selectOption("deadline_asc");
  await expect.poll(() => urlParam(page, "offset")).toBeNull();
  await expect.poll(() => lastListRequest(trace)).toMatchObject({ sort: "deadline_asc", offset: "0", limit: "2" });
  const kept = await page.evaluate((key) => JSON.parse(window.sessionStorage.getItem(key) ?? "null"), selectionKey);
  expect(kept).toMatchObject({ activeId: 7103, selectionGeneration: 0 });
  await sortSelect(page).selectOption("posted_at_desc");
  await expect.poll(() => urlParam(page, "sort")).toBeNull();

  // 두 번째 쪽으로 가서 다시 선택하고 의미 필터를 바꾼다.
  await pager(page).getByRole("button", { name: "다음" }).click();
  await expect.poll(() => rowIds(page)).toEqual(["7103", "7104"]);
  await expect(select(page, 7103)).toHaveAttribute("aria-pressed", "true");
  await fitSelect(page).selectOption("mismatch");
  await expect.poll(() => urlParam(page, "fit")).toBe("mismatch");
  expect(urlParam(page, "offset")).toBeNull();
  expect(urlParam(page, "limit")).toBe("2");
  await expect.poll(() => lastListRequest(trace)).toMatchObject({ fit: "mismatch", offset: "0", limit: "2" });
  await expect.poll(() => rowIds(page)).toEqual(["7103"]);
  // 선택이 비워졌다: 화면·회사별 저장소 모두.
  await expect(rows(page).locator('button.cw-row-select[aria-pressed="true"]')).toHaveCount(0);
  await expect(aside(page)).toContainText("목록에서 사전규격을 고르십시오.");
  await expect.poll(async () => {
    const state = await page.evaluate((key) => JSON.parse(window.sessionStorage.getItem(key) ?? "null"), selectionKey);
    return state === null ? "missing" : state.activeId;
  }).toBeNull();
  const after = await page.evaluate((key) => JSON.parse(window.sessionStorage.getItem(key) ?? "null"), selectionKey);
  expect(after.selectionGeneration).toBe(1);
  expect(after.selectedIds).toEqual([]);
  expect(after.filterFingerprint).toContain("mismatch");
});

test("T3: 조건에 맞는 항목이 없는 것과 목록이 비어 있는 것을 다르게 안내한다", async ({ page }) => {
  await installMocks(page);
  await page.goto(`${listPath}?fit=matched&tracking_status=종료`);
  await expect(page.getByText("조건에 맞는 사전규격이 없습니다.")).toBeVisible();
  await expect(page.getByText("판정 결과가 없다는 뜻이 아닙니다", { exact: false })).toBeVisible();
  await expect(table(page)).toHaveCount(0);
  await expect(pager(page)).toContainText("전체 0건");
  await page.locator(".empty-state").getByRole("button", { name: "필터 초기화" }).click();
  await expect(rows(page)).toHaveCount(4);
  expect(urlParam(page, "fit")).toBeNull();
  expect(urlParam(page, "tracking_status")).toBeNull();
});

test("목록 오류는 빈 목록이 아니라 오류로 보이고 다시 시도하면 회복한다", async ({ page }) => {
  await installMocks(page);
  let failed = false;
  await page.route(/\/api\/companies\/[^/]+\/pre-specs\?/, async (route) => {
    if (!failed) {
      failed = true;
      await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "processing_failed", message: "합성 오류", details: null }, request_id: null }) });
      return;
    }
    await route.fallback();
  });
  await page.goto(listPath);
  await expect(page.getByRole("alert").filter({ hasText: "회사 사전규격을 불러오지 못했습니다." })).toBeVisible();
  await expect(table(page)).toHaveCount(0);
  await expect(page.getByText("이 회사에 표시할 사전규격이 없습니다.")).toHaveCount(0);
  await expect(pager(page)).toHaveCount(0);
  await page.getByRole("button", { name: "다시 시도" }).click();
  await expect(rows(page)).toHaveCount(4);
});

test("T6: 조건을 바꾼 직후에는 이전 조건의 행을 새 결과처럼 보여 주지 않는다", async ({ page }) => {
  await installMocks(page);
  await page.goto(listPath);
  await expect(rows(page)).toHaveCount(4);
  const held = gate();
  await page.route(/\/api\/companies\/[^/]+\/pre-specs\?/, async (route) => {
    await held.promise;
    await route.fallback();
  });
  await fitSelect(page).selectOption("matched");
  await expect(page.getByRole("status").filter({ hasText: "이 회사의 사전규격을 불러오는 중입니다." })).toBeVisible();
  await expect(table(page)).toHaveCount(0);
  await expect(pager(page)).toHaveCount(0);
  held.release();
  await expect(rows(page)).toHaveCount(1);
});

const detailPath = (slug: keyof typeof COMPANY_BY_SLUG, noticeId: number) => `/companies/${COMPANY_BY_SLUG[slug].company_id}/pre-specs/${noticeId}`;
const attempts = (page: Page) => page.getByTestId("company-fit").locator("li.cw-attempt");

test("T3: 핏 판정 이력은 최신순이고 완료·실패·이전 입력이 서로 다른 판정과 상태로 보인다", async ({ page }) => {
  await installMocks(page);
  await page.goto(detailPath("demo-public-si", 7101));
  await expect(attempts(page)).toHaveCount(3);
  const statuses = await attempts(page).evaluateAll((items) => items.map((item) => [item.getAttribute("data-attempt-status"), item.getAttribute("data-attempt-decision"), item.getAttribute("data-attempt-current")]));
  expect(statuses).toEqual([
    ["completed", "matched", "true"],
    ["failed", "null", "false"],
    ["completed", "mismatch", "false"],
  ]);

  const latest = attempts(page).nth(0);
  await expect(latest).toContainText("실행 완료");
  await expect(latest).toContainText("판정 부합");
  await expect(latest).toContainText("최신 실행");
  await expect(latest).toContainText("현재 입력 기준");
  await expect(latest).not.toContainText("현재 입력 기준 아님");
  await expect(latest.locator("[data-attempt-summary]")).toHaveText("행정업무 통합 구축 역량과 직접 연결됩니다.");
  await expect(latest).toContainText("참조 실행 · 품질 미측정");
  await expect(latest).toContainText("참조 실행이며 품질을 측정하지 않았습니다.");
  await expect(latest).not.toContainText("측정 통과");
  await expect(latest.locator("[data-input-sha]")).toHaveAttribute("title", /^[0-9a-f]{64}$/);
  await expect(latest.locator("[data-input-sha]")).toHaveText(/^[0-9a-f]{12}$/);

  const failed = attempts(page).nth(1);
  await expect(failed).toContainText("실행 실패");
  await expect(failed).toContainText("판정 없음");
  await expect(failed).toContainText("오류 코드 model_output_invalid");
  await expect(failed).toContainText("현재 입력 기준 아님(이전 입력)");
  await expect(failed).not.toContainText("부합");
  await expect(failed).not.toContainText("불일치");
  await expect(failed.locator("[data-attempt-summary]")).toHaveCount(0);
  await expect(failed).not.toContainText("최신 실행");

  const stale = attempts(page).nth(2);
  await expect(stale).toContainText("판정 불일치");
  await expect(stale).toContainText("현재 입력 기준 아님(이전 입력)");
  await expect(stale).toContainText("연결된 그래프 경로 없음");

  // 요약 칸의 최신 실행도 같다: 이전 완료 실행으로 대체하지 않는다.
  await expect(page.locator("dl.cw-facts [data-fit-status]")).toHaveAttribute("data-fit-status", "completed");
  await expect(page.locator("dl.cw-facts [data-fit-decision]")).toHaveAttribute("data-fit-decision", "matched");
});

test("T3: 사유마다 서버가 준 그래프 경로를 그대로 보여 주고 없는 경로를 만들지 않는다", async ({ page }) => {
  await installMocks(page);
  await page.goto(detailPath("demo-public-si", 7101));
  const latest = attempts(page).nth(0);
  const reasons = latest.getByRole("list", { name: "판정 사유" }).locator("li.cw-reason");
  await expect(reasons).toHaveCount(2);

  const match = reasons.nth(0);
  await expect(match).toHaveAttribute("data-reason-kind", "scope_match");
  await expect(match).toContainText("범위가 맞는 근거");
  const matchPaths = match.locator("li.cw-path");
  await expect(matchPaths).toHaveCount(2);
  await expect(matchPaths.nth(0)).toHaveAttribute("data-path-index", "0");
  await expect(matchPaths.nth(0)).toHaveAttribute("data-path-relation", "direct");
  await expect(matchPaths.nth(0)).toContainText("경로 0 · 직접 연결");
  await expect(matchPaths.nth(0)).toContainText("요구사항 req-001");
  await expect(matchPaths.nth(0).locator("[data-path-nodes]")).toHaveText("노드 company → capability.public_admin");
  await expect(matchPaths.nth(0).locator("[data-path-edges]")).toHaveText("관계 edge.has_capability.public_admin");
  await expect(matchPaths.nth(0)).toContainText("프로필 근거 1건");
  await expect(matchPaths.nth(1)).toHaveAttribute("data-path-relation", "partial");
  await expect(matchPaths.nth(1)).toContainText("경로 1 · 부분 연결");
  await expect(matchPaths.nth(1).locator("[data-path-nodes]")).toHaveText("노드 company → staff.developers");
  // 근거 참조는 서버가 준 공고 사실·회사 사실로 풀어 보여 준다.
  await expect(match.getByRole("list", { name: "공고 근거" })).toContainText("overview:req:0");
  await expect(match.getByRole("list", { name: "공고 근거" })).toContainText("(p.1)");
  await expect(match.getByRole("list", { name: "회사 근거" })).toContainText("capability.public_admin");

  const gap = reasons.nth(1);
  await expect(gap).toHaveAttribute("data-reason-kind", "information_gap");
  await expect(gap).toContainText("정보가 부족한 부분");
  const gapPath = gap.locator("li.cw-path");
  await expect(gapPath).toHaveCount(1);
  await expect(gapPath).toHaveAttribute("data-path-index", "2");
  await expect(gapPath).toHaveAttribute("data-path-relation", "unmapped");
  await expect(gapPath).toContainText("경로 2 · 연결 없음");
  await expect(gapPath).toContainText("서버가 연결된 노드를 주지 않았습니다.");
  await expect(gapPath.locator("[data-path-edges]")).toHaveCount(0);
  await expect(latest.getByRole("list", { name: "확인이 필요한 항목" })).toContainText("정보보호 관리체계 인증 보유 여부 확인");

  // 서버가 범위 밖 index를 주면 경로를 지어내지 않고 그 사실을 적는다.
  const served = companyFitAttempts(company, COMPANY_NOTICE_FIXTURES[0]);
  const first = served.attempts[0] as { result: { reasons: Array<{ graph_path_indexes: number[] }> } };
  first.result.reasons[0].graph_path_indexes = [7];
  await page.route(/\/api\/companies\/[^/]+\/pre-specs\/7101\/company-fit$/, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(served) });
  });
  await page.reload();
  const outOfRange = attempts(page).nth(0).locator("li.cw-reason").nth(0);
  await expect(outOfRange.locator("li.cw-path")).toHaveCount(1);
  await expect(outOfRange.locator("li.cw-path")).toHaveClass(/cw-path-missing/);
  await expect(outOfRange.locator("li.cw-path")).toContainText("서버가 가리킨 경로 7번이 이 실행의 경로 목록 범위 밖입니다.");
  await expect(outOfRange.locator("li.cw-path")).not.toContainText("capability.public_admin");
});

test("T3: unknown·대기·사람 검토 필요·실패는 판정으로 바뀌지 않고 이전 완료 실행이 대신하지 않는다", async ({ page }) => {
  await installMocks(page);

  // unknown(미확인) + 이전 입력(is_current=false)
  await page.goto(detailPath("demo-data-ai", 7104));
  await expect(attempts(page)).toHaveCount(1);
  const unknown = attempts(page).first();
  await expect(unknown).toHaveAttribute("data-attempt-decision", "unknown");
  await expect(unknown).toContainText("판정 미확인");
  await expect(unknown).toContainText("현재 입력 기준 아님(이전 입력)");
  await expect(unknown.getByRole("list", { name: "확인이 필요한 항목" })).toContainText("회사 근거 확인 필요");
  await expect(unknown).not.toContainText("판정 부합");
  await expect(unknown).not.toContainText("판정 불일치");

  // 최신이 실패이면 과거 완료 실행(미확인)이 있어도 요약은 실패 그대로다.
  await page.goto(detailPath("demo-data-ai", 7103));
  await expect(attempts(page)).toHaveCount(2);
  await expect(attempts(page).nth(0)).toHaveAttribute("data-attempt-status", "failed");
  await expect(attempts(page).nth(1)).toHaveAttribute("data-attempt-decision", "unknown");
  await expect(page.locator("dl.cw-facts [data-fit-status]")).toHaveAttribute("data-fit-status", "failed");
  await expect(page.locator("dl.cw-facts [data-fit-decision]")).toHaveAttribute("data-fit-decision", "null");
  await expect(page.getByTestId("company-pre-spec-title")).toBeVisible();
  await expect(page.locator("dd", { hasText: "notice 7103" })).toContainText("마감일 미확인");

  // 대기
  await page.goto(detailPath("demo-cloud-si", 7101));
  await expect(attempts(page)).toHaveCount(1);
  await expect(attempts(page).first()).toHaveAttribute("data-attempt-status", "queued");
  await expect(attempts(page).first()).toContainText("실행 대기");
  await expect(attempts(page).first()).toContainText("판정 없음");
  await expect(attempts(page).first()).toContainText("아직 끝나지 않은 실행입니다. 판정이 아닙니다.");
  await expect(attempts(page).first().getByRole("list", { name: "판정 사유" })).toHaveCount(0);

  // 사람 검토 필요
  await page.goto(detailPath("demo-cloud-si", 7104));
  await expect(attempts(page).first()).toHaveAttribute("data-attempt-status", "needs_human_review");
  await expect(attempts(page).first()).toContainText("실행 사람 검토 필요");
  await expect(attempts(page).first()).toContainText("판정 없음");
  await expect(attempts(page).first()).toContainText("판정으로 읽지 않습니다");

  // 기록 없음은 불일치가 아니다.
  await page.goto(detailPath("demo-public-si", 7104));
  await expect(page.getByTestId("company-fit-empty")).toContainText("핏 실행 기록이 없습니다.");
  await expect(page.getByTestId("company-fit-empty")).toContainText("불일치가 아닙니다");
  await expect(attempts(page)).toHaveCount(0);
});

test("T5 일부: 회사 핏은 CLI 전용이라 생성·승인 화면이 없고, 원문·비교로 가는 링크가 있다", async ({ page }) => {
  await installMocks(page);
  await page.goto(detailPath("demo-public-si", 7101));
  await expect(attempts(page)).toHaveCount(3);
  await expect(page.getByTestId("company-fit-cli-note")).toContainText("회사 핏은 CLI로만 실행합니다.");
  await expect(page.getByTestId("company-fit-cli-note")).toContainText("만들거나 승인하지 않고");
  await expect(page.getByTestId("company-fit").getByRole("button")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /핏.*(실행|생성|승인)/ })).toHaveCount(0);
  await expect(page.locator("main").getByRole("link", { name: "원문 사전규격 상세" })).toHaveAttribute("href", "/pre-specs/7101");
  const comparison = page.locator("main").getByRole("link", { name: "3사 비교" });
  await expect(comparison).toHaveAttribute("href", "/pre-specs/7101/company-comparison");
  await comparison.click();
  await expect(page).toHaveURL(/\/pre-specs\/7101\/company-comparison$/);
  await expect(page.getByRole("heading", { name: "notice 7101 · 가상회사 3사 비교" })).toBeVisible();
});

test("핏 판정 이력 오류는 빈 이력이 아니라 오류로 보이고 다시 시도하면 회복한다", async ({ page }) => {
  await installMocks(page);
  let failed = false;
  await page.route(/\/api\/companies\/[^/]+\/pre-specs\/7101\/company-fit$/, async (route) => {
    if (!failed) {
      failed = true;
      await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "processing_failed", message: "합성 오류", details: null }, request_id: null }) });
      return;
    }
    await route.fallback();
  });
  await page.goto(detailPath("demo-public-si", 7101));
  const fit = page.getByTestId("company-fit");
  await expect(fit.getByRole("alert")).toContainText("핏 판정 이력을 불러오지 못했습니다.");
  await expect(fit.getByTestId("company-fit-empty")).toHaveCount(0);
  await expect(attempts(page)).toHaveCount(0);
  // 오류가 나도 상세 본문(제목·추적)은 그대로 쓸 수 있다.
  await expect(page.getByTestId("company-pre-spec-title")).toBeVisible();
  await fit.getByRole("button", { name: "다시 시도" }).click();
  await expect(attempts(page)).toHaveCount(3);
});
