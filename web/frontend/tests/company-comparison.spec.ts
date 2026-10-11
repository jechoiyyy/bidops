import { expect, test, type Page, type Route } from "@playwright/test";
import { COMPARISON_ERROR_NOTICE_ID, mockApi, mockCompanyWorkspace } from "./api-mock";
import {
  COMPANY_BY_SLUG,
  COMPANY_FIXTURES,
  COMPANY_NOTICE_FIXTURES,
  LONG_NOTICE_TITLE,
  companyDto,
  fitSummary,
  reviewSummary,
} from "./fixtures/company-demo";

/*
 * DEMO-04 STEP-003 · spec T3(3사 비교 stale/missing/different_input/실패: 서버 상태 그대로,
 * 순위·보정값 없음)와 T6의 일부(긴 한글 overflow 0, 로딩을 완료로 표시하지 않음, 1440 폭).
 *
 * 고정 응답은 `tests/api-mock.ts`의 `mockCompanyWorkspace`이며 실제 백엔드에 연결하지 않는다.
 * 비교 상태는 fixture가 서버 규칙(다른 입력 > 이전 입력 > 결과 없음 > 비교 가능)대로 정해
 * 응답하고, 화면이 그 값을 다시 계산하지 않는다는 것은 "서버 값 그대로" 검사가 모순된 값을 주어 확인한다.
 * 두 폭(1280/1440) 구조 검사는 STEP-005 몫이며 여기는 app 프로젝트(1440x900)의 1440 폭이다.
 */

type Slug = keyof typeof COMPANY_BY_SLUG;

const STATUS_LABEL = {
  comparable: "비교 가능",
  stale: "이전 입력",
  missing: "결과 없음",
  different_input: "다른 입력",
} as const;

const STATUS_NOTE = {
  comparable: "핏과 심층 검토가 모두 있고 현재 입력 기준입니다.",
  stale: "이전 입력으로 만든 결과입니다.",
  missing: "실행 기록이 없습니다.",
  different_input: "다른 문서 버전을 입력으로 삼았습니다.",
} as const;

async function installMocks(page: Page, options: { longText?: boolean } = {}) {
  await mockApi(page);
  return mockCompanyWorkspace(page, options);
}

const comparisonRows = (page: Page) => page.getByRole("table", { name: /3사 비교/ }).locator("tbody tr");
const rowOf = (page: Page, slug: Slug) => page.locator(`tr[data-company-slug="${slug}"]`);

function gate() {
  let release: () => void = () => {};
  const promise = new Promise<void>((resolve) => { release = resolve; });
  return { promise, release };
}

/** 가로 넘침 0. 문서·본문·화면 안쪽 요소가 본문 오른쪽 끝을 넘지 않는다. */
async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const main = document.querySelector("main");
    const mainRight = main ? main.getBoundingClientRect().right : window.innerWidth;
    const escaped = Array.from(document.querySelectorAll<HTMLElement>(".cw-page td, .cw-page th, .cw-page code, .cw-page strong, .cw-page li, .cw-page p, .cw-page dd"))
      .filter((element) => element.getBoundingClientRect().right > mainRight + 1)
      .map((element) => `${element.tagName}:${(element.textContent ?? "").slice(0, 30)}`);
    return {
      document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      main: main ? main.scrollWidth - main.clientWidth : 0,
      pages: Array.from(document.querySelectorAll<HTMLElement>(".cw-page")).map((element) => element.scrollWidth - element.clientWidth),
      escaped,
    };
  });
  expect(overflow.document).toBeLessThanOrEqual(1);
  expect(overflow.main).toBeLessThanOrEqual(1);
  for (const value of overflow.pages) expect(value).toBeLessThanOrEqual(1);
  expect(overflow.escaped).toEqual([]);
}

test("T3: 3사 비교는 서버가 준 slug 순서와 비교 상태·각 실행 상태를 그대로, 따로 보여 준다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto("/pre-specs/7101/company-comparison");
  await expect(page.getByRole("heading", { name: "notice 7101 · 가상회사 3사 비교" })).toBeVisible();
  await expect(comparisonRows(page)).toHaveCount(3);
  // 서버 순서(slug 오름차순)를 그대로 쓴다. 비교 상태 순서(비교 가능 < 다른 입력 < 결과 없음)로 다시 정렬하면 이 순서가 깨진다.
  const slugs = await comparisonRows(page).evaluateAll((rows) => rows.map((row) => row.getAttribute("data-company-slug")));
  expect(slugs).toEqual(["demo-cloud-si", "demo-data-ai", "demo-public-si"]);

  const cloud = rowOf(page, "demo-cloud-si");
  await expect(cloud.locator("td[data-comparison-status]")).toHaveAttribute("data-comparison-status", "missing");
  await expect(cloud.locator("td[data-comparison-status] .badge")).toHaveText(STATUS_LABEL.missing);
  await expect(cloud.locator("td[data-comparison-status]")).toContainText(STATUS_NOTE.missing);
  // 결과 없음인 회사의 핏은 아직 끝나지 않은 실행(대기)이다. 판정이 아니고 불일치도 아니다.
  await expect(cloud.locator("[data-fit-status]")).toHaveAttribute("data-fit-status", "queued");
  await expect(cloud.locator("[data-fit-decision]")).toHaveAttribute("data-fit-decision", "null");
  await expect(cloud.locator("[data-fit-decision] .badge")).toHaveText("판정 없음");
  await expect(cloud.locator("[data-fit-decision]")).toContainText("실행 대기");
  await expect(cloud.locator("[data-review-status]")).toHaveAttribute("data-review-status", "none");
  await expect(cloud.locator("[data-tracking-status]")).toHaveAttribute("data-tracking-status", "미선택");

  const dataAi = rowOf(page, "demo-data-ai");
  await expect(dataAi.locator("td[data-comparison-status]")).toHaveAttribute("data-comparison-status", "different_input");
  await expect(dataAi.locator("td[data-comparison-status] .badge")).toHaveText(STATUS_LABEL.different_input);
  await expect(dataAi.locator("td[data-comparison-status]")).toContainText(STATUS_NOTE.different_input);
  await expect(dataAi.locator("[data-fit-decision] .badge")).toHaveText("불일치");
  await expect(dataAi.locator("[data-tracking-status]")).toHaveAttribute("data-tracking-status", "종료");
  // 추적 사유도 서버가 준 그대로 옮긴다.
  await expect(dataAi.locator("[data-tracking-status]")).toContainText("구축 실적 범위 밖");

  const publicSi = rowOf(page, "demo-public-si");
  await expect(publicSi.locator("td[data-comparison-status]")).toHaveAttribute("data-comparison-status", "comparable");
  await expect(publicSi.locator("td[data-comparison-status] .badge")).toHaveText(STATUS_LABEL.comparable);
  await expect(publicSi.locator("[data-fit-decision] .badge")).toHaveText("부합");
  await expect(publicSi.locator("[data-review-status]")).toHaveAttribute("data-review-status", "completed");
  await expect(publicSi.locator("[data-review-status]")).toContainText("심층 검토 완료");
  await expect(publicSi.locator("[data-graph-version]")).toHaveAttribute("data-graph-version", COMPANY_BY_SLUG["demo-public-si"].graph_version_id);

  // 읽기 화면이다: 비교 호출 한 번, 쓰기 호출은 없다.
  expect(trace.requests.filter((entry) => entry === "GET /api/pre-specs/7101/company-comparison")).toHaveLength(1);
  expect(trace.requests.filter((entry) => !entry.startsWith("GET "))).toEqual([]);
  expect(trace.trackingPatches).toEqual([]);
  expect(trace.reviewPosts).toEqual([]);
  expect(trace.previewPosts).toEqual([]);
});

test("T3: 이전 입력·결과 없음·사람 검토 필요가 서로 다른 표시로 구분된다(공고 7104)", async ({ page }) => {
  await installMocks(page);
  await page.goto("/pre-specs/7104/company-comparison");
  await expect(comparisonRows(page)).toHaveCount(3);

  const dataAi = rowOf(page, "demo-data-ai");
  await expect(dataAi.locator("td[data-comparison-status]")).toHaveAttribute("data-comparison-status", "stale");
  await expect(dataAi.locator("td[data-comparison-status] .badge")).toHaveText(STATUS_LABEL.stale);
  await expect(dataAi.locator("td[data-comparison-status]")).toContainText(STATUS_NOTE.stale);
  // 이전 입력의 판정(미확인)은 판정 값 그대로 두고 "현재 입력 기준 아님"을 덧붙인다. 성공/부적합으로 바꾸지 않는다.
  await expect(dataAi.locator("[data-fit-decision]")).toHaveAttribute("data-fit-decision", "unknown");
  await expect(dataAi.locator("[data-fit-decision] .badge")).toHaveText("미확인");
  await expect(dataAi.locator("[data-fit-decision]")).toContainText("현재 입력 기준 아님");

  const cloud = rowOf(page, "demo-cloud-si");
  await expect(cloud.locator("td[data-comparison-status]")).toHaveAttribute("data-comparison-status", "missing");
  await expect(cloud.locator("[data-fit-status]")).toHaveAttribute("data-fit-status", "needs_human_review");
  await expect(cloud.locator("[data-fit-decision]")).toContainText("실행 사람 검토 필요");
  await expect(cloud.locator("[data-fit-decision] .badge")).toHaveText("판정 없음");

  const publicSi = rowOf(page, "demo-public-si");
  await expect(publicSi.locator("td[data-comparison-status]")).toHaveAttribute("data-comparison-status", "missing");
  await expect(publicSi.locator("[data-fit-decision]")).toHaveAttribute("data-fit-decision", "none");
  await expect(publicSi.locator("[data-fit-decision]")).toContainText("핏 실행 기록 없음");
  await expect(publicSi.locator("[data-review-status]")).toHaveAttribute("data-review-status", "none");
  // 사업기회에 연결되지 않은 공고는 추적 칸에 그 사실을 적는다. 미선택과 다르다.
  await expect(publicSi.locator("[data-tracking-status]")).toHaveAttribute("data-tracking-status", "unlinked");
  // 실행이 하나도 없으면 그래프 버전도 정해지지 않는다(null).
  await expect(publicSi.locator("[data-graph-version]")).toHaveAttribute("data-graph-version", "null");
  await expect(publicSi.locator("[data-graph-version]")).toContainText("그래프 버전 없음");
  await expect(dataAi.locator("[data-graph-version]")).not.toHaveAttribute("data-graph-version", "null");

  // 같은 화면의 세 상태가 서로 다른 문구다.
  const labels = await page.locator("td[data-comparison-status] .badge").allTextContents();
  expect(labels).toEqual([STATUS_LABEL.missing, STATUS_LABEL.stale, STATUS_LABEL.missing]);
});

test("T3: 비교 상태가 '비교 가능'이어도 실패한 실행은 실패로 따로 보인다(공고 7103)", async ({ page }) => {
  await installMocks(page);
  await page.goto("/pre-specs/7103/company-comparison");
  const dataAi = rowOf(page, "demo-data-ai");
  await expect(dataAi.locator("td[data-comparison-status]")).toHaveAttribute("data-comparison-status", "comparable");
  await expect(dataAi.locator("td[data-comparison-status] .badge")).toHaveText(STATUS_LABEL.comparable);
  // 서버가 비교 가능이라 했어도 핏과 심층 검토는 모두 실패다. 비교 상태가 성공을 뜻한다고 읽지 않는다.
  await expect(dataAi.locator("[data-fit-status]")).toHaveAttribute("data-fit-status", "failed");
  await expect(dataAi.locator("[data-fit-decision]")).toHaveAttribute("data-fit-decision", "null");
  await expect(dataAi.locator("[data-fit-decision] .badge")).toHaveText("판정 없음");
  await expect(dataAi.locator("[data-fit-decision]")).toContainText("실행 실패");
  await expect(dataAi.locator("[data-review-status]")).toHaveAttribute("data-review-status", "failed");
  await expect(dataAi.locator("[data-review-status] .badge")).toHaveText("심층 검토 실패");
  await expect(dataAi.locator("td[data-comparison-status]")).toContainText("각 실행이 성공했다는 뜻은 아닙니다");
  await expect(dataAi.locator("[data-fit-decision]")).not.toContainText("불일치");
  await expect(dataAi.locator("[data-fit-decision]")).not.toContainText("부합");

  const publicSi = rowOf(page, "demo-public-si");
  await expect(publicSi.locator("td[data-comparison-status]")).toHaveAttribute("data-comparison-status", "missing");
  await expect(publicSi.locator("[data-fit-decision] .badge")).toHaveText("불일치");
});

test("T3: 화면은 서버의 비교 상태를 다시 계산하지 않고 값 그대로 쓴다", async ({ page }) => {
  await installMocks(page);
  const notice = COMPANY_NOTICE_FIXTURES.find((entry) => entry.notice_id === 7102)!;
  const [cloud, dataAi, publicSi] = ["demo-cloud-si", "demo-data-ai", "demo-public-si"].map((slug) => COMPANY_BY_SLUG[slug as Slug]);
  // 규칙대로라면 "결과 없음"(핏·검토가 없음)/"비교 가능"(둘 다 현재)이어야 할 값을 일부러 어긋나게 준다.
  const item = (company: typeof cloud, status: string, withRuns: boolean) => ({
    company: companyDto(company),
    fit: withRuns ? fitSummary(company, notice) : null,
    review: withRuns ? { review_id: "00000000-0000-4000-8000-0000000000aa", status: "completed", is_current: true } : null,
    tracking: null,
    graph_version_id: withRuns ? company.graph_version_id : null,
    comparison_status: status,
  });
  const served = {
    schema_version: "bidops.company-comparison.v1",
    notice_id: 7102,
    document_version_ids: [notice.document_version_id],
    items: [item(cloud, "comparable", false), item(dataAi, "stale", true), item(publicSi, "missing", true)],
  };
  await page.route("**/api/pre-specs/7102/company-comparison", async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(served) });
  });
  await page.goto("/pre-specs/7102/company-comparison");
  await expect(comparisonRows(page)).toHaveCount(3);
  await expect(rowOf(page, "demo-cloud-si").locator("td[data-comparison-status] .badge")).toHaveText(STATUS_LABEL.comparable);
  await expect(rowOf(page, "demo-data-ai").locator("td[data-comparison-status] .badge")).toHaveText(STATUS_LABEL.stale);
  await expect(rowOf(page, "demo-public-si").locator("td[data-comparison-status] .badge")).toHaveText(STATUS_LABEL.missing);
  // 서버가 준 순서도 그대로다(서버 순서가 곧 화면 순서).
  const slugs = await comparisonRows(page).evaluateAll((rows) => rows.map((row) => row.getAttribute("data-company-slug")));
  expect(slugs).toEqual(["demo-cloud-si", "demo-data-ai", "demo-public-si"]);
});

test("T3: 순위·종합 점수·보정값·재정렬 조작이 없다", async ({ page }) => {
  await installMocks(page);
  await page.goto("/pre-specs/7101/company-comparison");
  const table = page.getByRole("table", { name: /3사 비교/ });
  await expect(comparisonRows(page)).toHaveCount(3);
  const headers = await table.locator("thead th").allTextContents();
  expect(headers).toEqual(["회사", "비교 상태", "회사 핏", "심층 검토", "추적 결정", "그래프 버전"]);
  await expect(table.locator("[aria-sort]")).toHaveCount(0);
  await expect(table.locator("thead button, thead a")).toHaveCount(0);
  await expect(page.locator("main meter, main progress, main [data-rank], main [data-score]")).toHaveCount(0);
  // 숫자 순위("1위")·점수("85점")·"최고 회사:" 같은 표현이 본문에 없다.
  const text = (await page.locator("main").innerText());
  expect(text).not.toMatch(/\d+\s*위/);
  expect(text).not.toMatch(/\d+(\.\d+)?\s*점/);
  expect(text).not.toMatch(/최고\s*회사\s*[:：]/);
  expect(text).not.toMatch(/종합\s*점수\s*[:：]?\s*\d/);
  // 머리글을 눌러도 순서가 바뀌지 않는다.
  await table.locator("thead th", { hasText: "비교 상태" }).click();
  const slugs = await comparisonRows(page).evaluateAll((rows) => rows.map((row) => row.getAttribute("data-company-slug")));
  expect(slugs).toEqual(["demo-cloud-si", "demo-data-ai", "demo-public-si"]);
  await expect(page.getByText("회사 순위·종합 점수·최고 회사는 만들지 않습니다.", { exact: false })).toBeVisible();
});

test("T3: 네 가지 비교 상태가 서로 다른 한국어 문구와 설명으로 안내된다", async ({ page }) => {
  await installMocks(page);
  await page.goto("/pre-specs/7101/company-comparison");
  const legend = page.getByRole("region", { name: "비교 상태 안내" });
  await expect(legend).toBeVisible();
  await expect(legend).toContainText("다른 입력, 이전 입력, 결과 없음, 비교 가능 순");
  for (const status of ["comparable", "stale", "missing", "different_input"] as const) {
    await expect(legend.locator("dt", { hasText: STATUS_LABEL[status] })).toBeVisible();
    await expect(legend).toContainText(STATUS_NOTE[status]);
  }
  expect(new Set(Object.values(STATUS_LABEL)).size).toBe(4);
  // 화면에 나온 상태 값과 문구 연결을 공고 세 곳에서 모은다: 서버 값 → 문구가 항상 같다.
  const seen = new Map<string, string>();
  for (const noticeId of [7101, 7103, 7104]) {
    await page.goto(`/pre-specs/${noticeId}/company-comparison`);
    await expect(comparisonRows(page)).toHaveCount(3);
    const pairs = await page.locator("td[data-comparison-status]").evaluateAll((cells) => cells.map((cell) => [
      cell.getAttribute("data-comparison-status") ?? "",
      cell.querySelector(".badge")?.textContent ?? "",
    ]));
    for (const [status, label] of pairs) seen.set(status, label);
  }
  expect(Object.fromEntries(seen)).toEqual(STATUS_LABEL);
});

test("회사 이름 링크는 그 회사의 같은 공고 상세로 가고, 원문 공고 링크가 있다", async ({ page }) => {
  await installMocks(page);
  await page.goto("/pre-specs/7101/company-comparison");
  const link = rowOf(page, "demo-data-ai").getByRole("link", { name: "데모 데이터AI" });
  await expect(link).toHaveAttribute("href", `/companies/${COMPANY_BY_SLUG["demo-data-ai"].company_id}/pre-specs/7101`);
  await expect(page.locator("main").getByRole("link", { name: "원문 사전규격 상세" })).toHaveAttribute("href", "/pre-specs/7101");
  await link.click();
  await expect(page).toHaveURL(new RegExp(`/companies/${COMPANY_BY_SLUG["demo-data-ai"].company_id}/pre-specs/7101$`));
  await expect(page.getByTestId("company-header").getByTestId("company-name")).toHaveText("데모 데이터AI");
  await expect(page.getByTestId("company-pre-spec-title")).toHaveText(COMPANY_NOTICE_FIXTURES[0].title);
});

test("비교 오류: 없는 공고 404, 서버 오류 500, 잘못된 주소를 성공 화면으로 그리지 않는다", async ({ page }) => {
  const trace = await installMocks(page);
  await page.goto("/pre-specs/7999/company-comparison");
  const failure = page.getByRole("alert").filter({ hasText: "3사 비교를 불러오지 못했습니다." });
  await expect(failure).toBeVisible();
  await expect(page.getByRole("table", { name: /3사 비교/ })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "비교 상태 안내" })).toHaveCount(0);

  await page.goto(`/pre-specs/${COMPARISON_ERROR_NOTICE_ID}/company-comparison`);
  await expect(failure).toBeVisible();
  await expect(page.getByRole("table", { name: /3사 비교/ })).toHaveCount(0);
  const before = trace.requests.filter((entry) => entry.includes(`/${COMPARISON_ERROR_NOTICE_ID}/company-comparison`)).length;
  await page.getByRole("button", { name: "다시 시도" }).click();
  await expect.poll(() => trace.requests.filter((entry) => entry.includes(`/${COMPARISON_ERROR_NOTICE_ID}/company-comparison`)).length).toBeGreaterThan(before);
  await expect(failure).toBeVisible();

  const comparisonCallsBefore = trace.requests.filter((entry) => entry.includes("/company-comparison")).length;
  await page.goto("/pre-specs/abc/company-comparison");
  await expect(page.getByRole("alert").filter({ hasText: "사전규격 주소가 올바르지 않습니다." })).toBeVisible();
  // 주소가 잘못되면 비교 API를 부르지 않는다(회사 목록 같은 셸 조회와 다르다).
  expect(trace.requests.filter((entry) => entry.includes("/company-comparison")).length).toBe(comparisonCallsBefore);
});

test("T6: 비교를 읽는 중에는 완료 화면을 그리지 않는다", async ({ page }) => {
  await installMocks(page);
  const held = gate();
  await page.route("**/api/pre-specs/7101/company-comparison", async (route) => {
    await held.promise;
    await route.fallback();
  });
  await page.goto("/pre-specs/7101/company-comparison");
  await expect(page.getByRole("status")).toContainText("3사 비교를 불러오는 중입니다.");
  await expect(page.getByRole("table", { name: /3사 비교/ })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "비교 상태 안내" })).toHaveCount(0);
  await expect(page.locator("main")).not.toContainText(STATUS_LABEL.comparable);
  await expect(page.locator("main")).not.toContainText("공통 현재 문서 버전");
  held.release();
  await expect(comparisonRows(page)).toHaveCount(3);
  await expect(page.getByRole("status").filter({ hasText: "불러오는 중" })).toHaveCount(0);
});

test("T6: 사전규격 목록·상세의 읽는 중 상태도 완료로 보이지 않는다", async ({ page }) => {
  await installMocks(page);
  const company = COMPANY_BY_SLUG["demo-public-si"];
  const listGate = gate();
  const fitGate = gate();
  await page.route(/\/api\/companies\/[^/]+\/pre-specs\?/, async (route) => {
    await listGate.promise;
    await route.fallback();
  });
  await page.route(/\/api\/companies\/[^/]+\/pre-specs\/7101\/company-fit$/, async (route) => {
    await fitGate.promise;
    await route.fallback();
  });
  await page.goto(`/companies/${company.company_id}/pre-specs`);
  await expect(page.getByRole("status").filter({ hasText: "이 회사의 사전규격을 불러오는 중입니다." })).toBeVisible();
  await expect(page.getByRole("table", { name: "회사별 사전규격 판정" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "회사 사전규격 페이지" })).toHaveCount(0);
  await expect(page.locator("main")).not.toContainText("조건에 맞는 사전규격이 없습니다.");
  await expect(page.locator("main")).not.toContainText("이 회사에 표시할 사전규격이 없습니다.");
  listGate.release();
  await expect(page.getByRole("table", { name: "회사별 사전규격 판정" }).locator("tbody tr")).toHaveCount(4);

  await page.goto(`/companies/${company.company_id}/pre-specs/7101`);
  await expect(page.getByTestId("company-pre-spec-title")).toBeVisible();
  await expect(page.getByTestId("company-fit").getByRole("status")).toContainText("핏 판정 이력을 불러오는 중입니다.");
  await expect(page.getByTestId("company-fit").locator("li.cw-attempt")).toHaveCount(0);
  await expect(page.getByTestId("company-fit-empty")).toHaveCount(0);
  fitGate.release();
  await expect(page.getByTestId("company-fit").locator("li.cw-attempt")).toHaveCount(3);
});

test("T6: 1440 폭에서 공백 없는 긴 한글 제목·요약·사유·회사 이름이 목록·상세·비교에서 넘치지 않는다", async ({ page }) => {
  await installMocks(page, { longText: true });
  expect(page.viewportSize()).toEqual({ width: 1440, height: 900 });
  const company = COMPANY_BY_SLUG["demo-public-si"];

  await page.goto(`/companies/${company.company_id}/pre-specs`);
  const table = page.getByRole("table", { name: "회사별 사전규격 판정" });
  await expect(table.locator("tbody tr")).toHaveCount(4);
  await expect(table.locator("tr[data-notice-id='7101']")).toContainText(LONG_NOTICE_TITLE);
  await table.locator("tr[data-notice-id='7101'] button.cw-row-select").click();
  await expect(page.getByTestId("company-selected-title")).toHaveText(LONG_NOTICE_TITLE);
  await expect(page.getByRole("complementary", { name: "선택한 사전규격" })).toContainText("직접연결되지만");
  await expectNoHorizontalOverflow(page);

  await page.goto(`/companies/${company.company_id}/pre-specs/7101`);
  await expect(page.getByTestId("company-pre-spec-title")).toHaveText(LONG_NOTICE_TITLE);
  await expect(page.getByTestId("company-fit").locator("li.cw-attempt")).toHaveCount(3);
  await expect(page.getByTestId("company-fit").locator("[data-attempt-summary]").first()).toContainText("행정업무통합구축역량");
  await expect(page.getByTestId("company-header").getByTestId("company-name")).toContainText("공공정보화사업전담컨소시엄");
  await expectNoHorizontalOverflow(page);

  await page.goto("/pre-specs/7101/company-comparison");
  await expect(comparisonRows(page)).toHaveCount(3);
  await expect(rowOf(page, "demo-public-si")).toContainText("공공정보화사업전담컨소시엄");
  await expect(rowOf(page, "demo-public-si")).toContainText("행정업무통합구축역량");
  await expect(rowOf(page, "demo-data-ai").locator("[data-tracking-status]")).toContainText("행정업무통합구축역량");
  await expectNoHorizontalOverflow(page);
});

test("비교 화면 구조: 회사 수와 같은 행, 공통 문서 버전 수, 데모 표식", async ({ page }) => {
  await installMocks(page);
  await page.goto("/pre-specs/7101/company-comparison");
  await expect(comparisonRows(page)).toHaveCount(COMPANY_FIXTURES.length);
  await expect(page.getByTestId("company-comparison-inputs")).toContainText("공통 현재 문서 버전 1개");
  await expect(page.getByRole("note", { name: "가상회사 데모 화면" })).toHaveText("가상회사 데모");
});
