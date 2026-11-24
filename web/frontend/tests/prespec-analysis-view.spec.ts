import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockEngineAnalysis, overviewEnvelopeFixture, overviewNeedsHumanReviewRunFixture, setSidebarActor } from "./api-mock";
import { analysisOverviewResult, analysisWikiProject, engineAnalysisRunFixture, withWorkUnits } from "./fixtures/engine-analysis";
import { RL_COMPANY_ID } from "./fixtures/company-rl";

// 일반 운영 preview에는 워크벤치가 없다. BIDOPS_MOCK_API=1 개발 서버에서만 이 spec을 실행한다.
test.skip(!process.env.BIDOPS_MOCK_UI, "개발 MOCK 서버 전용: BIDOPS_MOCK_UI=1 PW_PORT=<mock 서버 port>로 실행");

const NOTICE_ID = 991;
const analysis = engineAnalysisRunFixture("completed", RL_COMPANY_ID, NOTICE_ID).analysis!;

async function openAnalysis(page: Page, hash = "", workUnits?: "classified" | "unavailable") {
  await mockApi(page);
  const run = await mockEngineAnalysis(page, "completed", NOTICE_ID);
  if (workUnits && run.analysis) run.analysis = withWorkUnits(run.analysis, workUnits);
  await page.goto(`/pre-specs/${NOTICE_ID}${hash}`);
  await expect(page.locator("#s-brief")).toBeVisible();
}

const tabs = (page: Page) => page.getByRole("navigation", { name: "분석 구역 이동" });

async function mockTrackingPatches(page: Page) {
  const patches: { opportunityId: number; status: string; reason: string; actor: string }[] = [];
  await page.route("**/api/opportunities/*/tracking-status", async (route) => {
    const request = route.request();
    if (request.method() !== "PATCH") { await route.fallback(); return; }
    const body = request.postDataJSON() as { tracking_status: string; reason: string };
    const opportunityId = Number(new URL(request.url()).pathname.split("/").at(-2));
    const actor = decodeURIComponent((request.headers()["x-bidops-actor-name"] ?? "").replace(/^UTF-8''/, ""));
    patches.push({ opportunityId, status: body.tracking_status, reason: body.reason, actor });
    await route.fulfill({ json: {
      id: opportunityId, tracking_status: body.tracking_status, tracking_reason: body.reason, tracking_selected_by: actor,
      tracking_selected_at: "2026-11-21T02:00:00Z", recheck_signal: false, recheck_signal_at: null, recheck_signal_link_id: null,
      first_registered_stage: "order_plan", links: [],
    } });
  });
  return patches;
}

test("1440 첫 화면에 사업 개요·금액 대조·과업·세 층·사유가 결정 띠 위에 보인다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openAnalysis(page);
  const panel = page.locator(".app-content");
  await expect(panel).toHaveAttribute("data-reading-width", "analysis");
  await expect(tabs(page).getByRole("link")).toHaveText([
    "한눈에", `쟁점${analysis.risks?.length}`, `요구사항${analysis.fits.length}`, `자격·계약${analysis.gates.length}`, "원문·처리 정보",
  ]);
  await expect(tabs(page).getByRole("link", { name: "한눈에" })).toHaveAttribute("aria-current", "location");
  await expect(page.getByTestId("page-header-facts").locator("dt")).toHaveText([
    "의견 마감", "수요기관", "공고기관", "게시", "사전규격번호", "구분", "본공고",
  ]);
  await expect(page.locator("#page-header-actions")).toContainText("참조");
  const brief = page.locator("#s-brief");
  await expect(brief.locator(".paw-bcmp")).toContainText("차이 10,000,000원 · 등록액이 더 커요");
  await expect(brief.getByRole("heading", { name: /^사업 개요/ })).toBeVisible();
  await expect(brief.locator(".paw-purpose > li > span:first-child")).toHaveText(analysisOverviewResult.business_overview.map(({ text }) => text));
  await expect(brief.locator(".paw-purpose").getByRole("link", { name: "4쪽", exact: true }))
    .toHaveAttribute("href", /\/overview\/runs\/[^/]+\/pdf#page=4$/);
  const footer = await page.locator("#page-footer").boundingBox();
  expect(footer).not.toBeNull();
  for (const selector of [".paw-purpose", ".paw-bcmp", ".paw-tasks", ".paw-layers", ".paw-why"]) {
    const box = await brief.locator(selector).boundingBox();
    expect(box).not.toBeNull();
    expect(box!.y + box!.height).toBeLessThanOrEqual(footer!.y);
  }
});

test("개요 검증이 보류된 상세에는 개요 확인 필요가 표시된다", async ({ page }) => {
  await mockApi(page);
  await mockEngineAnalysis(page, "completed", NOTICE_ID);
  await page.route(`**/api/pre-specs/${NOTICE_ID}/overview`, (route) => route.fulfill({
    json: overviewEnvelopeFixture(NOTICE_ID, overviewNeedsHumanReviewRunFixture),
  }));
  await page.goto(`/pre-specs/${NOTICE_ID}`);
  const brief = page.locator("#s-brief");
  await expect(brief.getByText("개요 확인 필요", { exact: true })).toBeVisible();
  await expect(brief.locator(".paw-purpose")).toHaveCount(0);
});

test("쟁점 필터·펼침과 사유 링크가 스크롤과 초점을 옮긴다", async ({ page }) => {
  await openAnalysis(page);
  const why = page.locator(".paw-why > li").nth(0);
  const quote = analysis.risks![0].evidence.quote;
  const jump = why.getByRole("button", { name: `쟁점: ${quote} →` });
  await jump.click();
  const row = page.locator("#issue-0");
  await expect(row.locator(".paw-rowbtn")).toBeFocused();
  await expect(row.getByRole("heading", { name: "엔진 설명" })).toBeVisible();
  await expect(row.locator("blockquote").filter({ hasText: quote })).toBeVisible();
  await expect(tabs(page).getByRole("link", { name: /^쟁점/ })).toHaveAttribute("aria-current", "location");
  await expect(page.locator(".app-content")).toHaveAttribute("data-header-compact", "true");
  await expect(page.getByTestId("page-header-facts").locator('[data-fact="announcer"]')).toBeHidden();
  const filters = page.getByRole("group", { name: "쟁점 보기" });
  await filters.getByRole("button", { name: /^심각도 상/ }).click();
  await expect(page.locator("#s-issues .paw-issue")).toHaveCount(analysis.risks!.filter((risk) => risk.severity === "H").length);
  await expect(row.locator(".paw-rowbtn")).toHaveAttribute("aria-expanded", "false");
  await row.locator(".paw-rowbtn").click();
  await expect(row.getByRole("heading", { name: "같은 원문 문장을 인용한 요구사항" })).toBeVisible();
  await row.getByRole("button", { name: /^MHR-002/ }).click();
  await expect(page).toHaveURL(/#req=MHR-002$/);
  await expect(tabs(page).getByRole("link", { name: /^요구사항/ })).toHaveAttribute("aria-current", "location");
});

test("요구사항 필터·검색·키 이동·주소와 원문/실적/보완 방안을 연결한다", async ({ page }) => {
  await openAnalysis(page, "#req=MPR-003");
  const list = page.getByRole("table", { name: "요구사항 대응 목록" });
  const detail = page.getByRole("complementary", { name: "선택한 요구사항" });
  const selected = list.locator("tr[aria-current=true]");
  await expect(selected).toHaveAttribute("data-row-key", "MPR-003");
  await expect(selected).toBeFocused();
  await expect(detail.getByRole("heading", { name: "장애처리 및 지연" })).toBeVisible();
  await expect(detail.locator("blockquote")).toHaveText(analysis.fits.find(({ req_id }) => req_id === "MPR-003")!.evidence!.quote);
  await expect(detail).toContainText("2시간 내 현장 도착 체계");
  await expect(detail.getByRole("link", { name: "회사 근거에서 이 실적 열기 ↗" })).toHaveAttribute("href", `/company?view=portfolio&project=${analysisWikiProject.id}`);
  await expect(detail).toContainText(analysisWikiProject.title!);
  await expect(page.locator(".paw-workbench")).not.toContainText("[[");
  await selected.press("ArrowDown");
  await expect(selected).toHaveAttribute("data-row-key", "MPR-004");
  await expect(page).toHaveURL(/#req=MPR-004$/);
  await detail.getByRole("button", { name: "이전 요구사항" }).click();
  await expect(page).toHaveURL(/#req=MPR-003$/);
  const fitFilters = page.getByRole("group", { name: "대응으로 거르기" });
  await fitFilters.getByRole("button", { name: /^부분/ }).click();
  await page.getByRole("combobox", { name: "분류로 거르기" }).selectOption("MPR");
  const search = page.getByRole("searchbox", { name: "요구사항 검색" });
  await search.fill(analysisWikiProject.title!);
  await expect(page.locator(".paw-count")).toHaveText("1건 표시");
  await expect(selected).toHaveAttribute("data-row-key", "MPR-003");
  await page.getByRole("checkbox", { name: "회사 근거 없는 것만" }).check();
  await expect(page.locator(".paw-count")).toHaveText("0건 표시");
  await expect(page.getByText("조건에 맞는 요구사항이 없어요.")).toBeVisible();
});

test("근거 쪽 링크는 제안요청서 PDF의 해당 쪽을 새 탭에서 연다", async ({ page }) => {
  await page.context().route("**/overview/runs/*/pdf", (route) => route.fulfill({
    contentType: "text/html",
    body: "동결 PDF 위치를 확인하는 응답 예시",
  }));
  await openAnalysis(page, "#req=MPR-003");
  const detail = page.getByRole("complementary", { name: "선택한 요구사항" });
  const link = detail.getByRole("link", { name: "14쪽", exact: true });
  await expect(link).toHaveAttribute("target", "_blank");
  const opening = page.waitForEvent("popup");
  await link.click();
  const pdf = await opening;
  await expect(pdf).toHaveURL(/\/overview\/runs\/[^/]+\/pdf#page=14$/);
  await expect(page).toHaveURL(/#req=MPR-003$/);
  await pdf.close();
});

test("다른 문서 버전의 엔진 인용에는 쪽을 붙이지 않는다", async ({ page }) => {
  await mockApi(page);
  const run = await mockEngineAnalysis(page, "completed", NOTICE_ID);
  run.documents[0].document_version_id = "다른 문서 버전";
  await page.goto(`/pre-specs/${NOTICE_ID}#req=MPR-003`);
  const detail = page.getByRole("complementary", { name: "선택한 요구사항" });
  await expect(detail.getByText("쪽 없음", { exact: true })).toBeVisible();
  await expect(detail.getByRole("link", { name: /^\d+쪽$/ })).toHaveCount(0);
});

test("쪽별 텍스트 읽기 실패 시 고정 PDF는 새 탭에서 연다", async ({ page }) => {
  await mockApi(page);
  await mockEngineAnalysis(page, "completed", NOTICE_ID);
  await page.route("**/overview/runs/*/page-text", (route) => route.fulfill({ status: 409, json: {
    error: { code: "page_text_unavailable", message: "고정된 쪽별 텍스트를 읽지 못했어요.", details: null }, request_id: null,
  } }));
  await page.goto(`/pre-specs/${NOTICE_ID}#req=MPR-003`);
  const detail = page.getByRole("complementary", { name: "선택한 요구사항" });
  await expect(detail.getByText("쪽 없음", { exact: true })).toBeVisible();
  await expect(detail.getByRole("link", { name: "PDF 새 탭에서 열기 ↗" })).toHaveAttribute("href", /\/overview\/runs\/[^/]+\/pdf$/);
});

test("자격 표와 원문·처리 정보의 여덟 항목을 보여 준다", async ({ page }) => {
  await openAnalysis(page);
  await tabs(page).getByRole("link", { name: /^자격·계약/ }).click();
  const terms = page.locator("#s-terms");
  await expect(terms.getByText("자격 판정에 쓰인 회사 값 가운데 1개는 데모 입력이에요.")).toBeVisible();
  await expect(terms.getByText("엔진 추출 값 100 · 단위·조건은 원문 확인")).toBeVisible();
  await tabs(page).getByRole("link", { name: "원문·처리 정보" }).click();
  await expect(tabs(page).getByRole("link", { name: "원문·처리 정보" })).toHaveAttribute("aria-current", "location");
  const source = page.locator("#s-source");
  await expect(source.locator("dt")).toHaveText([
    "분석한 원문", "사업 개요의 범위", "심층 분석의 범위", "엔진이 본 회사 자료",
    "엔진이 요청한 회사 정보", "수익성", "결과를 쓸 때 주의", "쪽 번호를 붙인 방법",
  ]);
  await expect(source).toContainText("제안요청서.hwpx");
  await expect(source).toContainText("뜻이 등록되지 않은 경고예요. new_warning");
  await expect(source).toContainText("현장 인력 운영");
  await expect(source).toContainText("보안 운영");
  await expect(page.locator("#s-reqs .paw-kn")).toContainText("1쪽은 분석 분량 제한으로 빠졌어요(보안 운영).");
  await expect(page.locator("#ps-process")).toHaveCount(0);
});

test("업무 근거 지도는 두 종류의 부족과 미확인을 구분하고 같은 ID를 순서대로 연결한다", async ({ page }) => {
  await openAnalysis(page, "#req=MHR-002%401", "classified");
  const requirements = page.locator("#s-reqs");
  const detail = requirements.getByRole("complementary", { name: "선택한 요구사항" });
  const evidence = detail.getByRole("region", { name: "업무 근거" });
  const row = (key: string) => requirements.locator(`tr[data-row-key="${key}"]`);
  const noRecord = "수행 기록 없음 · 업무 근거 지도 실적 7건 기준";
  const constrained = "회사 정보에서 확인된 제약";
  await expect(row("MHR-002@1")).toHaveAttribute("title", noRecord);
  await expect(row("MHR-002@2")).toHaveAttribute("title", constrained);
  await expect(row("MHR-002@3")).toHaveAttribute("title", constrained);
  await expect(row("MPR-005")).toHaveAttribute("title", "판단 자료 없음");
  await expect(row("MHR-002@1").getByText("부족", { exact: true })).toBeVisible();
  await expect(detail.getByText("부족", { exact: true })).toBeVisible();
  await expect(detail.getByText(noRecord, { exact: true })).toBeVisible();
  await expect(evidence).toContainText("단위에 들지 않는 부분 성남 상주 운영");

  const filters = requirements.getByRole("group", { name: "대응으로 거르기" });
  await filters.getByRole("button", { name: /^부족/ }).click();
  await row("MHR-002@2").click();
  await expect(detail.getByText(constrained, { exact: true })).toBeVisible();
  await expect(evidence).toContainText("work-staffing-schedule");
  await expect(evidence).toContainText("단위에 들지 않는 부분 성남 지정 근무지");
  await expect(evidence).toContainText(analysisWikiProject.title!);
  await expect(evidence).toContainText(analysisWikiProject.id);
  await row("MHR-002@3").click();
  await expect(evidence).toContainText("work-staffing-onsite");
  await expect(evidence.getByText("단위에 들지 않는 부분")).toHaveCount(0);

  await filters.getByRole("button", { name: /^미확인/ }).click();
  await row("MPR-005").click();
  await expect(detail.getByText("판단 자료 없음", { exact: true })).toBeVisible();
  await expect(evidence).toHaveCount(0);
  const notice = "요구사항마다 업무 근거 지도(실적 7건 기준)로 근거 실적을 연결했어요. 지도에 없는 실적은 판단에 들어가지 않았어요.";
  await expect(requirements.locator(".paw-kn")).toHaveText(notice);
  const source = page.locator("#s-source");
  await expect(source).toContainText(notice);
  await expect(source.getByText("업무 근거 지도", { exact: true })).toBeVisible();
  await expect(source).toContainText("요구사항 4건을 업무 단위로 분류했어요(지도 실적 7건 기준). 어느 단위에도 들지 않은 요구사항 1건은 ‘수행 기록 없음’으로 판정될 수 있어요.");
});

test("업무 근거 지도 분류 실패는 원래 사유 코드와 실제 읽은 쪽 수를 보여 준다", async ({ page }) => {
  await openAnalysis(page, "#req=MHR-002", "unavailable");
  const detail = page.getByRole("complementary", { name: "선택한 요구사항" });
  await expect(detail.getByText("회사 정보에서 확인된 제약", { exact: true })).toBeVisible();
  await expect(detail.getByRole("region", { name: "업무 근거" })).toHaveCount(0);
  const notice = "회사 근거 위키 2쪽과 관련 실적 1건을 읽었어요. ‘회사 근거 없음’이 실적이 없다는 뜻은 아니에요.";
  await expect(page.locator("#s-reqs .paw-kn")).toHaveText(notice);
  const source = page.locator("#s-source");
  await expect(source).toContainText(notice);
  await expect(source).toContainText("분류하지 못했어요(invalid_assignments). 이 분석의 ‘부족’은 회사 정보에서 확인된 제약에서만 나와요.");
  await expect(source).not.toContainText("분량 제한 때문에 0쪽");
});

test("분석 완료 화면: 계속 추적·보류·종료를 고르고 종료는 확인 단계를 거친다", async ({ page }) => {
  const patches = await (async () => { await mockApi(page); return mockTrackingPatches(page); })();
  await mockEngineAnalysis(page, "completed", NOTICE_ID);
  await page.goto(`/pre-specs/${NOTICE_ID}`);
  await expect(page.locator("#s-brief")).toBeVisible();
  await setSidebarActor(page, "분석 담당");

  const bar = page.locator("#page-footer");
  const choices = bar.getByRole("group", { name: "추적 결정" });
  await expect(choices.getByRole("button")).toHaveText(["계속 추적", "보류", "종료"]);
  await expect(choices.locator("[aria-pressed=true]")).toHaveCount(0);
  await expect(bar).not.toContainText("최종 Go/No-Go");
  // 분석 전 화면의 단추(`추적 시작하기`)는 이 화면에 없고, 화면의 주 버튼은 이 띠 하나다.
  await expect(bar.getByRole("button", { name: "추적 시작하기" })).toHaveCount(0);
  const save = bar.getByRole("button", { name: "추적 결정 저장하기" });
  await expect(page.locator(".astryx-button.primary")).toHaveCount(1);
  await expect(save).toBeDisabled();
  await expect(bar.locator("#pre-spec-tracking-save-disabled")).toContainText("추적 상태(계속 추적·보류·종료)를 골라 주세요.");

  // 상태만 골라서는 저장되지 않는다(사유 필요). 사유까지 있으면 저장되고 PATCH는 한 번이다.
  await choices.getByRole("button", { name: "보류" }).click();
  await expect(choices.getByRole("button", { name: "보류" })).toHaveAttribute("aria-pressed", "true");
  await expect(save).toBeDisabled();
  await bar.getByRole("combobox", { name: "선택 사유" }).click();
  await page.getByRole("option", { name: "기타 · 직접 입력" }).click();
  await bar.getByRole("textbox", { name: "선택 사유 직접 입력 (필수)" }).fill("자격 확인이 끝날 때까지 보류");
  await expect(save).toBeEnabled();
  await save.click();
  await expect.poll(() => patches.length).toBe(1);
  expect(patches[0]).toMatchObject({ status: "보류", reason: "자격 확인이 끝날 때까지 보류", actor: "분석 담당" });
  await expect(bar.getByText("추적 상태를 보류(으)로 기록했어요.")).toBeVisible();

  // 종료는 되돌릴 수 없어 확인 단계를 먼저 거친다. 취소하면 저장이 나가지 않는다.
  await choices.getByRole("button", { name: "종료" }).click();
  await bar.getByRole("combobox", { name: "선택 사유" }).click();
  await page.getByRole("option", { name: "기타 · 직접 입력" }).click();
  await bar.getByRole("textbox", { name: "선택 사유 직접 입력 (필수)" }).fill("자격 조건을 충족할 수 없어 종료");
  await save.click();
  const dialog = page.getByRole("alertdialog", { name: "추적을 종료해요" });
  await expect(dialog).toBeVisible();
  expect(patches).toHaveLength(1);
  await dialog.getByRole("button", { name: "취소" }).click();
  await expect(dialog).toHaveCount(0);
  expect(patches).toHaveLength(1);
  await save.click();
  await page.getByRole("alertdialog", { name: "추적을 종료해요" }).getByRole("button", { name: "종료 상태로 저장" }).click();
  await expect.poll(() => patches.length).toBe(2);
  expect(patches[1]).toMatchObject({ status: "종료", reason: "자격 조건을 충족할 수 없어 종료", actor: "분석 담당" });

  // 계속 추적도 같은 띠에서 고른다.
  await choices.getByRole("button", { name: "계속 추적" }).click();
  await expect(choices.getByRole("button", { name: "계속 추적" })).toHaveAttribute("aria-pressed", "true");
});


for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
  test(`${viewport.width}px에서 헤더·본문·결정 띠가 정렬되고 가로로 넘치지 않는다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openAnalysis(page);
    await tabs(page).getByRole("link", { name: /^요구사항/ }).click();
    await expect(tabs(page).getByRole("link", { name: /^요구사항/ })).toHaveAttribute("aria-current", "location");
    const geometry = await page.evaluate(() => {
      const left = (s: string) => document.querySelector(s)!.getBoundingClientRect().left;
      const canvas = document.querySelector(".page-canvas")!;
      const list = document.querySelector(".paw-reqlist")!;
      return {
        header: left(".topbar-record"), main: left(".paw-workbench"), footer: left(".ps-decision-bar-inner"),
        page: document.documentElement.scrollWidth - innerWidth,
        canvas: canvas.scrollWidth - canvas.clientWidth, list: list.scrollWidth - list.clientWidth,
      };
    });
    expect(Math.abs(geometry.header - geometry.main)).toBeLessThanOrEqual(1);
    expect(Math.abs(geometry.footer - geometry.main)).toBeLessThanOrEqual(1);
    expect(Math.max(geometry.page, geometry.canvas, geometry.list)).toBeLessThanOrEqual(1);
  });
}
