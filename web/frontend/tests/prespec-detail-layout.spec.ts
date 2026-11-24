import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import {
  mockApi,
  mockFeatureFlags,
  mockOpportunityRecord,
  mockPreSpecAutoDetail,
  openProcessSection,
  settleProcessSection,
} from "./api-mock";

// 2026-11-21 사전규격 상세 재구성(`docs/1121_prespec-detail/`, ADR-0076 결정 13)의 구조 검사.
// 추적 결정 띠의 상태·담당자·PATCH는 pre-specs.spec.ts, 개요 범위 폼은 page-overview.spec.ts, 읽기 폭 기하(1280·1440)는
// 두 폭 project가 도는 design-shell.spec.ts, 처리 상태 기본 열림 규칙 표는 document-panel-default-open.spec.ts가 갖는다.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("처리 상태·기술 정보는 정상 건에서 닫혀 있고 토글로 열리며 꺼짐 안내가 그 안에 있다", async ({ page }) => {
  await mockFeatureFlags(page, { rl_analysis: false, prespec_overview: false });
  await mockPreSpecAutoDetail(page, "settled");
  await page.goto("/pre-specs/991");

  const toggle = await settleProcessSection(page);
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator("#ps-process-body")).toHaveCount(0);
  // 브라우저 탭 제목은 레코드 제목이다(여러 건을 탭으로 열어도 구분된다). 목록은 화면 이름이다.
  const heading = (await page.locator(".topbar-title").textContent())?.trim() ?? "";
  expect(heading.length).toBeGreaterThan(0);
  await expect(page).toHaveTitle(`${heading} · BidOps`);
  // 발견 경로는 값만 두지 않고 이름을 붙인다.
  await expect(page.locator("#ps-summary dt:text-is('발견 경로') + dd")).toHaveText(/^(독립 발견|발주계획 연계|구분 미확인)$/);
  // 접혀 있어도 요약 한 줄이 상태와 꺼짐을 말한다(안내를 지우지 않았다).
  const summary = page.getByTestId("pre-spec-process-summary");
  await expect(summary).toContainText("원문 묶음 확정 완료");
  await expect(summary).toContainText("참여 판정(RL 분석) 꺼짐");
  // 꺼진 기능 안내는 본문 구역이 아니라 이 구역 안에 있다.
  await expect(page.locator("#ps-conditions")).toHaveCount(0);
  await expect(page.locator("#ps-tasks, #ps-evidence").getByText("이 환경에서 꺼져 있음")).toHaveCount(0);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  const body = page.locator("#ps-process-body");
  await expect(body).toBeVisible();
  await expect(body).toContainText("참여 판정(RL 분석) · 이 환경에서 꺼져 있음");
  // 자동 준비 단계·문서 준비 패널 토글·처리 이력은 지우지 않고 이 안에 있다.
  await expect(body.locator(".pre-spec-auto-steps")).toBeVisible();
  await expect(body.getByRole("button", { name: /^문서 준비 (열기|닫기)$/ })).toBeVisible();
  await expect(body.locator("#ps-record-history")).toBeVisible();

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator("#ps-process-body")).toHaveCount(0);
});

test("문제가 있는 건은 처리 상태·기술 정보가 열려 들어온다", async ({ page }) => {
  await mockPreSpecAutoDetail(page, "settled");
  // 묶음이 없으면 문서 준비를 사람이 시작해야 하므로 구역이 열려 있어야 한다.
  await page.route("**/api/notices/991/document-bundles", (route) => route.fulfill({ json: { items: [] } }));
  await page.goto("/pre-specs/991");
  const toggle = await settleProcessSection(page);
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("#ps-process-body")).toBeVisible();
  await expect(page.getByTestId("pre-spec-process-summary")).toContainText("원문 묶음 없음");
});

test("본문은 개요 → 원문·첨부 → 처리 상태 순이고 사실 목록과 원문 요약은 오른쪽 열에 있다", async ({ page }) => {
  await page.goto("/pre-specs/991");
  await openProcessSection(page);
  const order = await page.evaluate(() => {
    const top = (selector: string) => document.querySelector(selector)!.getBoundingClientRect().top;
    return ["#ps-tasks", "#ps-evidence", "#ps-process"].map(top);
  });
  expect([...order].sort((left, right) => left - right)).toEqual(order);
  const rail = page.locator(".workbench-record-rail");
  await expect(rail.locator("#ps-summary dt:nth-of-type(-n+5)")).toHaveText(["의견 마감", "사업 예산", "구분", "게시", "본공고"]);
  await expect(rail.getByRole("link", { name: /첨부 \d+건 보기/ })).toHaveAttribute("href", "#ps-evidence");
  await expect(page.locator(".workbench-record-main #ps-summary")).toHaveCount(0);
  // 결정 띠는 `.ps-record` 본문의 구역이 아니라 패널 아래 고정 슬롯 안에 있다.
  await expect(page.locator(".ps-record #ps-tracking-bar")).toHaveCount(0);
  await expect(page.locator("#page-footer #ps-tracking-bar")).toBeVisible();
  const pinned = await page.evaluate(() => {
    const footer = document.getElementById("page-footer")!.getBoundingClientRect();
    const content = document.querySelector(".app-content")!.getBoundingClientRect();
    return { footerHeight: footer.height, footerBottom: Math.round(footer.bottom), contentBottom: Math.round(content.bottom) };
  });
  expect(pinned.footerHeight).toBeGreaterThan(0);
  // 본문을 아래로 스크롤해도 띠는 같은 자리에 있다(패널 맨 아래에 붙는다).
  await page.locator(".page-canvas").evaluate((element) => { element.scrollTop = element.scrollHeight; });
  const after = await page.evaluate(() => Math.round(document.getElementById("page-footer")!.getBoundingClientRect().bottom));
  expect(after).toBe(pinned.footerBottom);
  expect(pinned.footerBottom).toBeLessThanOrEqual(pinned.contentBottom);
});

test("읽기 폭은 상세에 표시되고 고정 슬롯 #page-footer는 추적 결정 띠가 있을 때만 높이를 가진다", async ({ page }) => {
  for (const route of ["/order-plans", "/pre-specs", "/"]) {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await expect(page.locator("header.topbar h1")).toBeVisible();
    const slot = page.locator("#page-footer");
    await expect(slot).toBeAttached();
    await expect(slot).toBeEmpty();
    const height = await slot.evaluate((element) => element.getBoundingClientRect().height);
    expect(height, route).toBe(0);
    await expect(page.locator(".app-content[data-reading-width]"), route).toHaveCount(0);
  }
  await mockOpportunityRecord(page);
  await page.goto("/opportunities/7101/activity");
  await expect(page.locator(".app-content")).toHaveAttribute("data-reading-width", "detail");
  const decision = page.locator("#page-footer").getByRole("group", { name: "추적 결정" });
  await expect(decision.getByRole("button", { name: "추적 상태 바꾸기", exact: true })).toBeVisible();
  // 사전규격 상세로 가면 슬롯에 띠가 생기고 읽기 폭 표식이 붙는다. 다른 화면으로 돌아오면 다시 0이다.
  await page.goto("/pre-specs/991");
  await expect(page.locator(".app-content")).toHaveAttribute("data-reading-width", "detail");
  await expect(page.locator("#page-footer .ps-decision-bar")).toBeVisible();
  await page.locator("header.topbar").getByRole("navigation", { name: "현재 위치" })
    .getByRole("link", { name: "사전규격 목록으로", exact: true }).click();
  await expect(page).toHaveURL(/\/pre-specs$/);
  await expect(page.locator("#page-footer .ps-decision-bar")).toHaveCount(0);
  expect(await page.locator("#page-footer").evaluate((element) => element.getBoundingClientRect().height)).toBe(0);
});

// 운영 번들에는 분석 완료 화면이 들어가지 않는다(`BIDOPS_REVIEW_MOCK`이 false로 접혀 동적 import가 사라진다).
// 빌드 산출물의 JS·CSS에서 그 화면의 문구·선택자를 찾는다. 소스에 그 문구가 있음을 먼저 확인해 검사가 헛돌지 않게 한다.
test("운영 번들에 분석 완료 화면의 문구와 선택자가 없다", async () => {
  test.skip(Boolean(process.env.BIDOPS_MOCK_UI), "개발 mock 서버 실행에서는 운영 번들을 검사하지 않는다.");
  // 다른 화면(회사 사전규격 등)도 쓰는 문구(`요구사항 대응`)는 뺐다. 이 화면에만 있는 문구·선택자만 본다.
  const needles = ["엔진 참고 의견", "먼저 확인할 쟁점", "paw-tabs", "paw-workbench", "paw-issue-jump", "쪽 번호를 붙인 방법"];
  const source = readFileSync(join(process.cwd(), "src/components/pre-spec-analysis/PreSpecAnalysisWorkbench.tsx"), "utf8")
    + readFileSync(join(process.cwd(), "src/components/pre-spec-analysis/AnalysisSource.tsx"), "utf8")
    + readFileSync(join(process.cwd(), "src/styles/pre-spec-analysis-workbench.css"), "utf8");
  for (const needle of needles) expect(source, `소스에 있어야 하는 표지: ${needle}`).toContain(needle);

  const outDir = join(process.cwd(), process.env.PW_OUT_DIR ?? "dist");
  const files = readdirSync(join(outDir, "assets")).filter((name) => /\.(js|css)$/.test(name));
  expect(files.length, `${outDir}/assets에 빌드 산출물이 있어야 해요`).toBeGreaterThan(0);
  for (const name of files) {
    const text = readFileSync(join(outDir, "assets", name), "utf8");
    for (const needle of needles) expect(text.includes(needle), `${name}에 ${needle}`).toBe(false);
  }
});

test("운영 번들의 사전규격 상세에는 분석 완료 구역이 없다", async ({ page }) => {
  test.skip(Boolean(process.env.BIDOPS_MOCK_UI), "개발 mock 서버에서는 분석 완료 화면이 켜진다.");
  await page.goto("/pre-specs/991?analysis=completed");
  await expect(page.locator("#ps-summary")).toBeVisible();
  await expect(page.locator(".paw-workbench, .paw-tabs, .paw-drawer")).toHaveCount(0);
  // 분석 전 화면의 결정은 `추적 시작하기` 하나이고 계속 추적·보류·종료 선택 묶음은 없다.
  await expect(page.locator("#page-footer .ps-decision-bar-choices")).toHaveCount(0);
});

test("추적을 이어받은 상세의 하단 띠는 두 폭에서 56px 이내이고 상태 관리로 연결한다", async ({ page }) => {
  for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/pre-specs/991");
    const bar = page.locator("#page-footer .ps-decision-bar");
    await expect(bar).toBeVisible();
    await expect(bar.getByRole("link", { name: /사업 추적에서 상태 관리/ })).toBeVisible();
    expect(await bar.evaluate((element) => Math.round(element.getBoundingClientRect().height)), `${viewport.width}`).toBeLessThanOrEqual(56);
  }
});
