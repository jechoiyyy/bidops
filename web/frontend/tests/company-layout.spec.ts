import { expect, test, type Locator, type Page, type Route } from "@playwright/test";
import { mockApi, mockCompanyWorkspace } from "./api-mock";
import {
  COMPANY_BY_SLUG,
  COMPANY_FIXTURES,
  LONG_COMPANY_NAME_SUFFIX,
  LONG_NOTICE_TITLE,
  companyReviewEvidence,
  reviewIdFor,
} from "./fixtures/company-demo";

/*
 * DEMO-04 STEP-005 · 구조 층 — spec T6(1280/1440·긴 한글·HTTP origin·로딩을 완료로 표시하지 않음)과
 * T2/T3의 폭 의존 부분(관계 행·근거 패널이 들어가는가, 3사 비교 표가 비교 상태 열을 숨기지 않는가).
 *
 * 이 파일은 `playwright.config.ts`의 LAYOUT_SPECS라서 layout-laptop(1280x800)과
 * layout-desktop(1440x900)에서 돈다. 의미(업무 상태가 맞는가)는 폭과 무관한 앞 단계 spec이 본다:
 *   T1 company-workspace · T2 company-graph · T3 company-prespecs/company-comparison ·
 *   T4/T5 company-review. 여기는 "지원 폭 안에 들어가는가"만 잰다.
 *
 * 고정 응답은 `tests/api-mock.ts`의 `mockCompanyWorkspace({ longText: true })`이다. 제목·요약·사유·회사 이름이
 * 공백 없는 긴 한글이 되므로 줄바꿈 규칙이 빠지면 표·패널 밖으로 넘친다. 실제 백엔드에 연결하지 않는다.
 * 모든 측정은 구체적인 데이터 표식(행 수·긴 제목·보고서 본문)이 보인 뒤에 한다.
 * 로딩 셸은 로딩만 증명하므로 완료 화면의 근거로 쓰지 않는다(`expectSettled`와 "읽는 중" 검사).
 */

type Slug = keyof typeof COMPANY_BY_SLUG;

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DELIVERY_CLAIM_ID = "d797cdbf-520d-5e6d-b903-25f6319844fb";
/** 사람이 입력하는 긴 한글 사유(서버 응답이 아니라 입력 초안). 공백이 없어 줄바꿈 규칙이 없으면 넘친다. */
const LONG_SUMMARY_DRAFT =
  "내초안사유로데이터인력확인후보류하며공백없이길게이어지는한글문장이상세패널의칸을넘지않고줄바꿈되는지확인하는구조점검용긴사유입니다";

const id = (slug: Slug) => COMPANY_BY_SLUG[slug].company_id;
const listPath = (slug: Slug) => `/companies/${id(slug)}/pre-specs`;
const detailPath = (slug: Slug, noticeId: number) => `/companies/${id(slug)}/pre-specs/${noticeId}`;
const reviewPath = (slug: Slug, noticeId: number) => `/companies/${id(slug)}/deep-reviews/${reviewIdFor(COMPANY_BY_SLUG[slug], noticeId)}`;

test.beforeEach(async ({ page }) => {
  // 네트워크 글꼴에 기대지 않는다(design-shell과 같은 규칙).
  await page.route("**://fonts.googleapis.com/**", (route) => route.fulfill({ status: 200, contentType: "text/css", body: "" }));
  await page.route("**://fonts.gstatic.com/**", (route) => route.fulfill({ status: 204, body: "" }));
});

async function installMocks(page: Page, options: { longText?: boolean } = {}) {
  await mockApi(page);
  return mockCompanyWorkspace(page, options);
}

/** 테스트가 풀어 줄 때까지 다음 한 요청을 붙잡는다. 그 뒤 요청은 그대로 mock으로 간다. */
async function holdNext(page: Page, pattern: RegExp, method: string) {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let seen = false;
  let held = false;
  await page.route(pattern, async (route: Route) => {
    if (route.request().method() !== method || held) { await route.fallback(); return; }
    held = true;
    seen = true;
    await gate;
    await route.fallback();
  });
  return { release: () => release(), seen: () => seen };
}

// ---------------------------------------------------------------------------
// 측정

interface Region { left: number; right: number; overflow: number }
interface LayoutMeasure {
  viewport: number;
  documentOverflow: number;
  /** 셸 안에서 오른쪽/왼쪽 끝이 화면 밖으로 나간 보이는 요소. 안쪽 가로 스크롤 영역도 면제하지 않는다. */
  escaped: string[];
  /** 가로로 잘리거나 스크롤되는(overflow-x가 visible이 아니고 내용이 더 넓은) 요소. */
  clipped: string[];
  shell: { topbar: Region | null; sidebar: Region | null; canvas: Region | null };
}

async function measureLayout(page: Page): Promise<LayoutMeasure> {
  return page.evaluate(() => {
    const viewport = document.documentElement.clientWidth;
    const describe = (element: Element) => {
      const text = (element.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 28);
      const cls = typeof element.className === "string" ? element.className.split(/\s+/).filter(Boolean).slice(0, 2).join(".") : "";
      return `${element.tagName.toLowerCase()}${cls ? `.${cls}` : ""}「${text}」`;
    };
    const escaped: string[] = [];
    const clipped: string[] = [];
    const shell = document.querySelector<HTMLElement>(".app-shell");
    for (const element of shell ? Array.from(shell.querySelectorAll<HTMLElement>("*")) : []) {
      const style = getComputedStyle(element);
      if (style.display === "none" || style.visibility === "hidden") continue;
      const rect = element.getBoundingClientRect();
      if (rect.width <= 1 || rect.height <= 1) continue;
      if (rect.right > viewport + 1 || rect.left < -1) escaped.push(`${describe(element)} left=${Math.round(rect.left)} right=${Math.round(rect.right)}`);
      if (style.overflowX !== "visible" && element.scrollWidth > element.clientWidth + 1) {
        clipped.push(`${describe(element)} scrollWidth=${element.scrollWidth} clientWidth=${element.clientWidth}`);
      }
    }
    const region = (selector: string): Region | null => {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return { left: rect.left, right: rect.right, overflow: element.scrollWidth - element.clientWidth };
    };
    return {
      viewport,
      documentOverflow: document.documentElement.scrollWidth - viewport,
      escaped,
      clipped,
      shell: { topbar: region("header.topbar"), sidebar: region("aside.sidebar"), canvas: region("main.page-canvas") },
    };
  });
}

function expectFits(measure: LayoutMeasure, name: string) {
  expect(measure.documentOverflow, `${name}: 문서 가로 넘침`).toBeLessThanOrEqual(1);
  for (const key of ["topbar", "sidebar", "canvas"] as const) {
    const region = measure.shell[key];
    expect(region, `${name}: ${key} 영역이 없습니다`).not.toBeNull();
    expect(region!.left, `${name}: ${key} 왼쪽 끝`).toBeGreaterThanOrEqual(-1);
    expect(region!.right, `${name}: ${key} 오른쪽 끝(폭 ${measure.viewport})`).toBeLessThanOrEqual(measure.viewport + 1);
    expect(region!.overflow, `${name}: ${key} 안쪽 가로 넘침`).toBeLessThanOrEqual(1);
  }
  expect(measure.escaped, `${name}: 화면 밖으로 나간 요소`).toEqual([]);
  expect(measure.clipped, `${name}: 가로로 잘리거나 스크롤되는 요소`).toEqual([]);
}

/** 읽는 중인 영역이 남아 있으면 완료 화면이 아니다. 측정은 반드시 이 뒤에 한다. */
async function expectSettled(page: Page) {
  await expect(page.locator('.app-shell [aria-busy="true"]'), "읽는 중 표식(aria-busy)이 남아 있습니다").toHaveCount(0);
  await expect(page.locator("main [role='status']").filter({ hasText: /불러오는 중/ }), "읽는 중 문구가 남아 있습니다").toHaveCount(0);
  await expect(page.locator("main [data-skeleton], main .skeleton"), "스켈레톤이 남아 있습니다").toHaveCount(0);
  await page.waitForLoadState("networkidle");
}

async function expectInViewport(locator: Locator, name: string) {
  await expect(locator, `${name}: 보이지 않습니다`).toBeVisible();
  const box = await locator.boundingBox();
  expect(box, `${name}: 상자를 잴 수 없습니다`).not.toBeNull();
  const width = locator.page().viewportSize()!.width;
  expect(box!.x, `${name}: 왼쪽 끝`).toBeGreaterThanOrEqual(-1);
  expect(box!.x + box!.width, `${name}: 오른쪽 끝(폭 ${width})`).toBeLessThanOrEqual(width + 1);
}

/** 글자가 칸보다 넓어 잘리지 않았다(줄바꿈으로 칸 안에 들어간다). */
async function expectNotClipped(locator: Locator, name: string) {
  await expect(locator, `${name}: 보이지 않습니다`).toBeVisible();
  const overflow = await locator.evaluate((element) => element.scrollWidth - element.clientWidth);
  expect(overflow, `${name}: 글자가 칸보다 넓습니다`).toBeLessThanOrEqual(1);
}

/** 상단바의 회사 선택기·가상회사 표식과 사이드바가 폭 안에 있다. */
async function expectCompanyShell(page: Page, name: string) {
  const topbar = page.locator("header.topbar");
  await expectInViewport(topbar, `${name}: 상단바`);
  const marker = page.getByRole("note", { name: "가상회사 데모 화면" });
  await expectInViewport(marker, `${name}: 가상회사 표식`);
  await expect(marker).toHaveText("가상회사 데모");
  await expectNotClipped(marker, `${name}: 가상회사 표식`);
  const selector = page.getByRole("combobox", { name: "데모 회사 선택" });
  await expectInViewport(selector, `${name}: 회사 선택기`);
  const topbarBox = (await topbar.boundingBox())!;
  const selectorBox = (await selector.boundingBox())!;
  expect(selectorBox.x + selectorBox.width, `${name}: 회사 선택기가 상단바 밖으로 나갔습니다`).toBeLessThanOrEqual(topbarBox.x + topbarBox.width + 1);
  await expectInViewport(page.locator("aside.sidebar"), `${name}: 사이드바`);
  await expectInViewport(page.locator("aside.sidebar").getByRole("link", { name: "회사 선택" }), `${name}: 사이드바 회사 선택 링크`);
}

async function expectScreenFits(page: Page, name: string, testInfo: { outputPath: (file: string) => string }, shot: string) {
  await expectSettled(page);
  await expectCompanyShell(page, name);
  expectFits(await measureLayout(page), name);
  await page.screenshot({ path: testInfo.outputPath(`${shot}.png`) });
}

// ---------------------------------------------------------------------------
// 화면별 구조 검사

test("회사 선택(/companies): 긴 회사 이름 3행과 열기 링크가 폭 안에 있다", async ({ page }, info) => {
  await installMocks(page, { longText: true });
  await page.goto("/companies");
  const list = page.getByRole("list", { name: "가상회사 목록" });
  await expect(list.locator("li")).toHaveCount(COMPANY_FIXTURES.length);
  for (const company of COMPANY_FIXTURES) {
    const row = list.locator(`li[data-company-slug="${company.slug}"]`);
    await expect(row).toContainText(`${company.name}${LONG_COMPANY_NAME_SUFFIX}`);
    await expectInViewport(row, `${company.slug} 행`);
    await expectInViewport(row.getByRole("link", { name: /사전규격 열기/ }), `${company.slug} 사전규격 열기`);
    await expectInViewport(row.getByRole("link", { name: /프로필 열기/ }), `${company.slug} 프로필 열기`);
  }
  await expectScreenFits(page, "회사 선택", info, "company-picker");
});

test("회사 사전규격 목록: 긴 제목·요약과 판정·추적 열이 폭 안에 있고 선택한 공고 패널도 들어간다", async ({ page }, info) => {
  await installMocks(page, { longText: true });
  await page.goto(listPath("demo-public-si"));
  const table = page.getByRole("table", { name: "회사별 사전규격 판정" });
  await expect(table.locator("tbody tr")).toHaveCount(4);
  await expect(table.locator("tr[data-notice-id='7101']")).toContainText(LONG_NOTICE_TITLE);
  await expect(page.getByTestId("company-header").getByTestId("company-name")).toContainText(LONG_COMPANY_NAME_SUFFIX);
  // 판정·추적 열은 가장 오른쪽 열이라 폭이 모자라면 먼저 가려진다.
  for (const noticeId of [7101, 7102, 7103, 7104]) {
    const row = table.locator(`tr[data-notice-id='${noticeId}']`);
    await expectInViewport(row.locator("[data-fit-decision]"), `공고 ${noticeId} 핏 판정`);
    await expectInViewport(row.locator("[data-tracking-status]"), `공고 ${noticeId} 추적 결정`);
  }
  await expectInViewport(table.locator("thead th").last(), "표 마지막 머리글");
  await expectInViewport(page.getByTestId("company-header"), "회사 머리글");
  await expectScreenFits(page, "회사 사전규격 목록", info, "company-list");

  await table.locator("tr[data-notice-id='7101'] button.cw-row-select").click();
  const aside = page.getByRole("complementary", { name: "선택한 사전규격" });
  await expect(page.getByTestId("company-selected-title")).toHaveText(LONG_NOTICE_TITLE);
  await expect(aside).toContainText("직접연결되지만");
  await expectInViewport(aside, "선택한 사전규격 패널");
  await expectNotClipped(page.getByTestId("company-selected-title"), "선택한 공고 제목");
  await expectScreenFits(page, "회사 사전규격 목록(선택 패널)", info, "company-list-selected");
});

test("읽는 중 목록은 완료 화면으로 측정하지 않고, 완료된 뒤의 표가 폭 안에 있다", async ({ page }, info) => {
  await installMocks(page, { longText: true });
  const held = await holdNext(page, /\/api\/companies\/[^/]+\/pre-specs(?:\?.*)?$/, "GET");
  await page.goto(listPath("demo-data-ai"));
  await expect.poll(() => held.seen()).toBe(true);
  // 읽는 중에는 표도 행도 없고, 읽는 중 문구가 있다. 이 상태는 expectSettled가 완료로 받지 않는다.
  await expect(page.locator("main [role='status']").filter({ hasText: /불러오는 중/ })).toBeVisible();
  await expect(page.getByRole("table", { name: "회사별 사전규격 판정" })).toHaveCount(0);
  await expect(page.locator("main tr[data-notice-id]")).toHaveCount(0);
  await expect(expectSettled(page)).rejects.toThrow();
  held.release();
  await expect(page.getByRole("table", { name: "회사별 사전규격 판정" }).locator("tbody tr")).toHaveCount(4);
  await expect(page.locator("tr[data-notice-id='7101']")).toContainText(LONG_NOTICE_TITLE);
  await expectScreenFits(page, "읽기 완료 뒤 목록", info, "company-list-after-loading");
});

test("회사 사전규격 상세: 긴 제목, 핏 판정 이력 3건, 추적 컨트롤이 폭 안에 있다", async ({ page }, info) => {
  await installMocks(page, { longText: true });
  await page.goto(detailPath("demo-public-si", 7101));
  await expect(page.getByTestId("company-pre-spec-title")).toHaveText(LONG_NOTICE_TITLE);
  const fit = page.getByTestId("company-fit");
  await expect(fit.locator("li.cw-attempt")).toHaveCount(3);
  await expect(fit.locator("[data-attempt-summary]").first()).toContainText("행정업무통합구축역량");
  const tracking = page.getByTestId("company-tracking");
  await expect(tracking.getByTestId("company-tracking-current")).toContainText("현재 계속 추적");
  await expect(tracking.getByRole("radio")).toHaveCount(3);
  await expectNotClipped(page.getByTestId("company-pre-spec-title"), "상세 제목");
  await expectInViewport(fit, "핏 판정 이력");
  await expectInViewport(tracking, "추적 결정 컨트롤");
  for (const name of ["계속 추적", "보류", "종료"]) await expectInViewport(tracking.getByRole("radio", { name }), `추적 라디오 ${name}`);
  await expectInViewport(tracking.getByRole("button", { name: "추적 결정 저장" }), "추적 결정 저장 버튼");
  await expectScreenFits(page, "회사 사전규격 상세", info, "company-detail");
});

test("추적 409 version_conflict의 초안·최신값 비교 패널이 긴 사유와 함께 폭 안에 있다", async ({ page }, info) => {
  const trace = await installMocks(page, { longText: true });
  await page.goto(detailPath("demo-public-si", 7102));
  const control = page.getByTestId("company-tracking");
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 미선택");
  await control.getByRole("radio", { name: "보류" }).check();
  await control.getByLabel("추적 결정 사유").fill(LONG_SUMMARY_DRAFT);
  await control.getByLabel("추적 결정 담당자 이름").fill("업무SI담당자공백없는긴이름점검용");
  trace.externalTrackingUpdate(id("demo-public-si"), 8102, { tracking_status: "계속 추적", reason: "다른 담당자가 먼저 결정", selected_by: "다른 담당" });
  await control.getByRole("button", { name: "추적 결정 저장" }).click();
  const conflict = control.getByTestId("company-tracking-conflict");
  await expect(conflict).toBeVisible();
  await expect(conflict.getByTestId("company-tracking-conflict-draft")).toContainText(LONG_SUMMARY_DRAFT);
  await expect(conflict.getByTestId("company-tracking-conflict-latest")).toContainText("1회");
  await expectInViewport(conflict.getByTestId("company-tracking-conflict-draft"), "충돌 초안");
  await expectInViewport(conflict.getByTestId("company-tracking-conflict-latest"), "충돌 서버 최신값");
  await expectNotClipped(conflict.getByTestId("company-tracking-conflict-draft"), "충돌 초안");
  await expectInViewport(conflict.getByRole("button", { name: "최신값 기준으로 다시 저장 준비" }), "다시 저장 준비 버튼");
  await expectScreenFits(page, "추적 충돌 패널", info, "company-tracking-conflict");
});

test("Luna 외부 전송 승인 상자(미리보기 후)가 긴 회사 이름·범위와 함께 폭 안에 있다", async ({ page }, info) => {
  const trace = await installMocks(page, { longText: true });
  await page.goto(detailPath("demo-cloud-si", 7102));
  const request = page.getByTestId("company-deep-review-request");
  await request.getByLabel("심층 검토 요청 담당자 이름").fill("클라우드SI 담당");
  await request.getByRole("button", { name: "전송 내용 미리보기" }).click();
  const box = page.getByRole("region", { name: "외부 전송 승인" });
  await expect(box.getByTestId("company-approval-company")).toContainText(LONG_COMPANY_NAME_SUFFIX);
  await expect(box.getByTestId("company-approval-company")).toContainText("가상회사");
  await expect(box.getByTestId("company-approval-scope")).toContainText("notice 7102");
  await expect(box.getByTestId("company-approval-quality")).toContainText("참조 실행 · 품질 미측정");
  expect(trace.previewPosts).toHaveLength(1);
  expect(trace.reviewPosts).toEqual([]);
  await expectInViewport(box, "승인 상자");
  await expectNotClipped(box.getByTestId("company-approval-company"), "승인 상자 회사 줄");
  await expectInViewport(box.getByRole("button", { name: "전송 승인하고 심층검토 요청" }), "승인 버튼");
  await expectInViewport(box.locator('[aria-label="회사 지식 버전"]'), "회사 지식 버전");
  await expectScreenFits(page, "Luna 승인 상자", info, "company-luna-approval");
});

test("3사 비교 표: 긴 한글에서도 비교 상태 열이 숨지 않고 표가 가로 스크롤 없이 들어간다", async ({ page }, info) => {
  await installMocks(page, { longText: true });
  await page.goto("/pre-specs/7101/company-comparison");
  const table = page.getByRole("table", { name: /3사 비교/ });
  const rows = table.locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(page.locator("tr[data-company-slug='demo-public-si']")).toContainText(LONG_COMPANY_NAME_SUFFIX);
  await expect(page.locator("tr[data-company-slug='demo-data-ai'] [data-tracking-status]")).toContainText("행정업무통합구축역량");
  await expectInViewport(table, "비교 표");
  for (const header of await table.locator("thead th").all()) {
    await expectInViewport(header, `머리글 ${(await header.textContent())?.trim()}`);
  }
  // 비교 상태는 서버 값(`comparison_status`)이며 열이 사라지거나 좁은 폭에서 가려지지 않는다.
  const expected: Record<string, string> = { "demo-cloud-si": "missing", "demo-data-ai": "different_input", "demo-public-si": "comparable" };
  for (const [slug, status] of Object.entries(expected)) {
    const cell = page.locator(`tr[data-company-slug='${slug}'] td[data-comparison-status]`);
    await expect(cell).toHaveAttribute("data-comparison-status", status);
    await expectInViewport(cell, `${slug} 비교 상태 칸`);
    await expectInViewport(cell.locator(".badge"), `${slug} 비교 상태 배지`);
    await expectNotClipped(cell, `${slug} 비교 상태 칸`);
    for (const attr of ["data-fit-decision", "data-review-status", "data-tracking-status"]) {
      await expectInViewport(page.locator(`tr[data-company-slug='${slug}'] [${attr}]`), `${slug} ${attr}`);
    }
  }
  // 표는 안쪽 가로 스크롤 영역이 아니다: 표 상자가 부모 상자를 넘지 않는다.
  const containment = await table.evaluate((element) => {
    const parent = element.parentElement!;
    return { table: element.getBoundingClientRect().width, parent: parent.getBoundingClientRect().width, overflowX: getComputedStyle(parent).overflowX };
  });
  expect(containment.table, "비교 표가 부모 폭보다 넓습니다").toBeLessThanOrEqual(containment.parent + 1);
  await expectScreenFits(page, "3사 비교", info, "company-comparison");
});

test("읽는 중 3사 비교는 완료 화면으로 측정하지 않고, 완료 뒤에 폭 안에 있다", async ({ page }, info) => {
  await installMocks(page, { longText: true });
  const held = await holdNext(page, /\/api\/pre-specs\/\d+\/company-comparison$/, "GET");
  await page.goto("/pre-specs/7101/company-comparison");
  await expect.poll(() => held.seen()).toBe(true);
  await expect(page.getByText("3사 비교를 불러오는 중입니다.")).toBeVisible();
  await expect(page.getByRole("table", { name: /3사 비교/ })).toHaveCount(0);
  await expect(page.locator("tr[data-company-slug]")).toHaveCount(0);
  await expect(expectSettled(page)).rejects.toThrow();
  held.release();
  await expect(page.locator("tr[data-company-slug]")).toHaveCount(3);
  await expectScreenFits(page, "읽기 완료 뒤 3사 비교", info, "company-comparison-after-loading");
});

test("심층 검토 보고서: 회사 식별 줄과 NarrativeReportReader, 근거 패널이 폭 안에 있다", async ({ page }, info) => {
  await installMocks(page, { longText: true });
  await page.goto(reviewPath("demo-public-si", 7101));
  const reader = page.getByRole("article", { name: "심층검토 보고서 본문" });
  await expect(reader).toBeVisible();
  const identity = page.getByTestId("company-report-identity");
  await expect(identity.getByTestId("company-report-company")).toContainText(LONG_COMPANY_NAME_SUFFIX);
  await expect(identity.getByTestId("company-report-current")).toHaveAttribute("data-is-current", "true");
  await expectInViewport(identity, "보고서 식별 줄");
  await expectInViewport(reader, "보고서 본문");
  for (const testId of ["company-report-profile-version", "company-report-graph-version"]) {
    await expectInViewport(identity.getByTestId(testId), testId);
    await expectNotClipped(identity.getByTestId(testId), testId);
  }
  await expectScreenFits(page, "심층 검토 보고서", info, "company-report");

  await reader.locator(`[data-claim-id="${DELIVERY_CLAIM_ID}"]`).getByRole("button", { name: "근거 1 확인" }).click();
  const evidence = page.getByRole("complementary", { name: "선택한 원문 근거" });
  await expect(evidence.locator("blockquote")).toHaveText(companyReviewEvidence.quote);
  await expectInViewport(evidence, "원문 근거 패널");
  await expectNotClipped(evidence.locator("blockquote"), "원문 근거 인용문");
  await expectScreenFits(page, "심층 검토 보고서(근거 패널)", info, "company-report-evidence");
});

// ---------------------------------------------------------------------------
// T6 HTTP origin — 안전한 UUID

/*
 * `crypto.randomUUID`는 보안 컨텍스트(HTTPS 또는 localhost 계열)에서만 있다. Playwright의
 * 기본 origin `http://127.0.0.1`은 "신뢰할 수 있는 origin"이라 보안 컨텍스트로 취급되므로, 그
 * origin에서 도는 다른 spec의 UUID 검사는 비보안 origin을 증명하지 못한다. 여기서는 사내망 IP처럼
 * 비보안인 `http://bidops-insecure.test`로 문서와 자산을 실제 preview에서 가져와(route.fetch)
 * 같은 번들을 비보안 컨텍스트로 실행한다.
 */
test("비보안 HTTP origin에서도 회사 추적 저장과 Luna 생성은 UUID v4 request_id를 보낸다", async ({ page, baseURL }) => {
  const origin = "http://bidops-insecure.test";
  // 가장 먼저 등록해 우선순위가 가장 낮게 둔다. mock이 받지 않는 요청(문서·자산)만 여기로 온다.
  await page.route(`${origin}/**`, async (route) => {
    const url = new URL(route.request().url());
    try {
      const response = await route.fetch({ url: `${baseURL}${url.pathname}${url.search}` });
      await route.fulfill({ response });
    } catch {
      // 화면을 옮기며 취소된 이전 문서의 자산 요청이다(응답이 이미 폐기됨). 가져오지 못한 요청은 실패로 돌려
      // 페이지가 못 뜨면 아래 기대가 실패하게 한다. 조용히 성공으로 바꾸지 않는다.
      await route.abort().catch(() => undefined);
    }
  });
  const trace = await installMocks(page);
  await page.goto(`${origin}${detailPath("demo-public-si", 7102)}`);
  const context = await page.evaluate(() => ({
    secure: window.isSecureContext,
    origin: window.location.origin,
    randomUUID: typeof crypto.randomUUID,
    getRandomValues: typeof crypto.getRandomValues,
  }));
  expect(context).toEqual({ secure: false, origin, randomUUID: "undefined", getRandomValues: "function" });

  const control = page.getByTestId("company-tracking");
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 미선택");
  await control.getByRole("radio", { name: "보류" }).check();
  await control.getByLabel("추적 결정 사유").fill("비보안 origin에서 저장 확인");
  await control.getByLabel("추적 결정 담당자 이름").fill("업무SI 담당");
  await control.getByRole("button", { name: "추적 결정 저장" }).click();
  await expect(control.getByTestId("company-tracking-current")).toContainText("현재 보류");
  expect(trace.trackingPatches).toHaveLength(1);
  expect(String(trace.trackingPatches[0].body.request_id)).toMatch(UUID_V4);

  await page.goto(`${origin}${detailPath("demo-cloud-si", 7102)}`);
  expect(await page.evaluate(() => window.isSecureContext)).toBe(false);
  const request = page.getByTestId("company-deep-review-request");
  await request.getByLabel("심층 검토 요청 담당자 이름").fill("클라우드SI 담당");
  await request.getByRole("button", { name: "전송 내용 미리보기" }).click();
  await expect(page.getByRole("region", { name: "외부 전송 승인" })).toBeVisible();
  await page.getByRole("button", { name: "전송 승인하고 심층검토 요청" }).click();
  await expect(page).toHaveURL(new RegExp(`${reviewPath("demo-cloud-si", 7102)}$`));
  expect(trace.reviewPosts).toHaveLength(1);
  const body = trace.reviewPosts[0].body as Record<string, unknown>;
  expect(String(body.request_id)).toMatch(UUID_V4);
  expect(String(body.request_id)).not.toBe(String(trace.trackingPatches[0].body.request_id));
});
