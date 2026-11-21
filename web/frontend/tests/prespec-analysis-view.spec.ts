import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockEngineAnalysis, setSidebarActor } from "./api-mock";
import { engineAnalysisRunFixture } from "./fixtures/engine-analysis";
import { RL_COMPANY_ID } from "./fixtures/company-rl";
import { qualityStatusLabel } from "../src/lib/qualityStatus";

// 사전규격 상세 `분석 완료` 화면(2026-11-21 시안 b1~b3)은 **mock 빌드 전용**이다. `import.meta.env.BIDOPS_REVIEW_MOCK`이
// `vite` 개발 서버를 `BIDOPS_MOCK_API=1`로 띄울 때만 true이고, 운영 빌드·`npm run build`·`vite preview`에서는 false로 접혀
// 이 화면의 코드가 번들에 없다(`prespec-detail-layout.spec.ts`가 번들을 검사한다). 그래서 이 spec은 일반 preview 번들로는
// 돌지 못하고 개발 mock 서버가 있어야 한다. `mock-review-prototype.spec.ts`와 같은 약속이다:
//
//   BIDOPS_MOCK_API=1 npx vite --host 127.0.0.1 --port 5174 --strictPort
//   BIDOPS_MOCK_UI=1 PW_PORT=5174 node_modules/.bin/playwright test prespec-analysis-view --project=app --workers=2
//
// 응답은 route mock이 준다(`mockApi`·`mockEngineAnalysis`). 기대 건수는 fixture에서 세어 구한다(값을 따로 적지 않는다).
test.skip(!process.env.BIDOPS_MOCK_UI, "개발 MOCK 서버 전용: BIDOPS_MOCK_UI=1 PW_PORT=<mock 서버 port>로 실행");

const NOTICE_ID = 991;
const completed = engineAnalysisRunFixture("completed", RL_COMPANY_ID, NOTICE_ID);
const partial = engineAnalysisRunFixture("partial", RL_COMPANY_ID, NOTICE_ID);
const count = <T,>(items: readonly T[], predicate: (item: T) => boolean) => items.filter(predicate).length;

async function openAnalysis(page: Page, variant: "completed" | "partial" = "completed") {
  await mockApi(page);
  await mockEngineAnalysis(page, variant, NOTICE_ID);
  await page.goto(`/pre-specs/${NOTICE_ID}`);
  await expect(page.locator("#pa-summary")).toBeVisible();
}

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

for (const state of ["abstain", "ready"] as const) {
  test(`엔진 종합 권고는 화면에 표시한 의견과 다를 때만 보인다 · ${state}`, async ({ page }) => {
    await mockApi(page);
    const run = await mockEngineAnalysis(page, "completed", NOTICE_ID);
    const analysis = run.analysis!;
    const assessment = analysis.assessment!;
    assessment.state = state;
    assessment.decision = state === "ready" ? "NO_GO" : null;
    assessment.provisional!.decision = "CONDITIONAL_GO";
    analysis.recommendation.decision = "NO_GO";
    analysis.recommendation.why_not = ["상주 장소를 협의해야 합니다.", "두 번째 우려입니다."];
    await page.goto(`/pre-specs/${NOTICE_ID}`);
    const opinion = page.locator("#pa-summary .pa-opinion");
    await expect(opinion).toBeVisible();
    if (state === "abstain") {
      await expect(opinion.getByText(/엔진 종합 권고/)).toHaveText(
        "엔진 종합 권고 · 참여 비권장 · 참여 우려 · 상주 장소를 협의해야 합니다.",
      );
      await expect(opinion).not.toContainText("두 번째 우려입니다.");
    } else {
      await expect(opinion).not.toContainText("엔진 종합 권고");
    }
  });
}

test("분석 완료 화면: 구역 순서·건수 줄·충족 접힘·점수 없음", async ({ page }) => {
  await openAnalysis(page);
  const analysis = completed.analysis!;

  // 사실 줄 → 분석 결과 요약 → 자격 조건 → 확인할 일 → 요구사항 대응 → 리스크 → 인력·계약 → 개요 → 원문 → 처리 상태.
  // 회사 관련성 참고 구역은 이 화면 구성에 없다.
  const ids = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>(".ps-record > [id]")].map((element) => element.id));
  expect(ids).toEqual(["ps-summary", "pa-summary", "pa-gates", "pa-todos", "pa-reqs", "pa-risks", "pa-terms", "ps-tasks", "ps-evidence", "ps-process"]);
  // 사실 줄에 추적 상태가 더해진다. 헤더 탭 자리의 구역 이동 링크는 숨기지 않는 링크다(탭이 아니다).
  await expect(page.locator("#ps-summary dt", { hasText: "추적 상태" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "구역 이동" });
  await expect(nav.getByRole("link")).toHaveCount(7);
  await expect(page.getByRole("tab", { name: /요약|자격 조건/ })).toHaveCount(0);

  // 건수 세 줄은 fixture에서 센 값이다.
  const gates = analysis.gates;
  const fits = analysis.fits;
  const risks = analysis.risks ?? [];
  const counts = page.locator("#pa-summary .pa-counts");
  await expect(counts).toContainText(`자격 조건 ${gates.length}`);
  await expect(counts).toContainText(`차단 ${count(gates, (gate) => gate.verdict === "FAIL")}`);
  await expect(counts).toContainText(`위험 ${count(gates, (gate) => gate.verdict === "RISK")}`);
  await expect(counts).toContainText(`충족 ${count(gates, (gate) => gate.verdict === "PASS")}`);
  await expect(counts).toContainText(`요구사항 ${fits.length}`);
  await expect(counts).toContainText(`부족 ${count(fits, (fit) => fit.fit === "GAP")}`);
  await expect(counts).toContainText(`부분 ${count(fits, (fit) => fit.fit === "PARTIAL")}`);
  await expect(counts).toContainText(`리스크 ${risks.length}`);
  await expect(counts).toContainText(`상 ${count(risks, (risk) => risk.severity === "H")}`);
  // 0건 칸은 링크가 아니다.
  await expect(page.locator("#pa-summary .pa-count.is-zero a")).toHaveCount(0);

  // 엔진 참고 의견(점수 없음)과 판단 보류 + 잠정 의견, 품질 표식, 경계 문장.
  const opinion = page.locator("#pa-summary .pa-opinion");
  await expect(opinion).toContainText("엔진 참고 의견");
  await expect(opinion).toContainText("판단 보류");
  await expect(opinion).toContainText("잠정 의견");
  await expect(opinion).toContainText("입찰 참여는 최종 Go/No-Go에서 정해요.");
  await expect(page.locator("#pa-summary .pa-basis")).toContainText(qualityStatusLabel(completed.quality_status));
  const analysisText = (await page.locator("#pa-summary, #pa-gates, #pa-todos, #pa-reqs, #pa-risks, #pa-terms").allInnerTexts()).join("\n");
  expect(analysisText).not.toMatch(/점수|배점|fit_score|score/i);

  // 차단·위험·미확인 행만 먼저 보이고 충족은 접혀 있다. 눌러야 보인다.
  const fold = page.locator("#pa-gates details.pa-fold");
  const passCount = count(gates, (gate) => gate.verdict === "PASS");
  await expect(fold.locator("summary")).toHaveText(`충족 ${passCount}건 보기`);
  await expect(fold).not.toHaveAttribute("open", "");
  await expect(page.locator("#pa-gates table").first().locator("tbody tr")).toHaveCount(count(gates, (gate) => gate.verdict !== "PASS"));
  await fold.locator("summary").click();
  await expect(fold.locator("tbody tr")).toHaveCount(passCount);
  await expect(fold.locator("tbody tr").first()).toBeVisible();

  // 개요는 접혀 들어온다. 여는 것은 사람의 조작이다.
  const overviewToggle = page.locator("#ps-tasks .ps-fold-toggle");
  await expect(overviewToggle).toHaveAttribute("aria-expanded", "false");
});

test("분석 완료 화면: 엔진이 붙인 목적·확인 시점·요구사항 이름·분석 건수·원문 블록 위치를 그대로 보인다", async ({ page }) => {
  await openAnalysis(page);
  const analysis = completed.analysis!;
  const requests = analysis.review_actions?.requests ?? [];
  const conditions = analysis.assessment?.provisional?.conditions ?? [];
  const plan = count(requests, (request) => request.kind !== "company");
  const decisionCompany = count(requests, (request) => request.kind === "company" && request.purpose === "decision");
  const otherCompany = count(requests, (request) => request.kind === "company" && request.purpose !== "decision");
  expect(decisionCompany).toBeGreaterThan(0);

  // 추적 판단에 쓰이는 회사 확인은 접지 않고, 건수에 들어간다. 나머지 회사 확인만 접힌다.
  const todos = page.locator("#pa-todos");
  await expect(todos.locator(".ps-cnt")).toHaveText(`${conditions.length + plan + decisionCompany}건`);
  const decisionRows = todos.getByTestId("pa-company-decision").locator("tbody tr");
  await expect(decisionRows).toHaveCount(decisionCompany);
  await expect(decisionRows.first()).toContainText("상주 가능 지역·인원");
  await expect(decisionRows.first()).toContainText("지금 확인 가능");
  await expect(todos.locator("tr", { hasText: "공동수급 구성원 자격 조항" })).toContainText("새 분석 입력 필요");
  const fold = todos.locator("details.pa-fold");
  await expect(fold.locator("summary")).toHaveText(`그 밖의 회사 자료 확인 ${otherCompany}건 보기`);
  await fold.locator("summary").click();
  // 엔진이 준 제목은 글자로, 코드 글꼴은 옛 응답의 필드 키에만 쓴다.
  await expect(fold.locator("li")).toHaveCount(otherCompany);
  await expect(fold.locator("li code")).toHaveCount(0);

  // 필수 여부는 다루지 않는다(2026-11-21 결정). 요구 ID 칸에 표시를 붙이지 않고 화면 어디에도 적지 않는다.
  await page.locator("#pa-reqs .pa-pills").getByRole("button", { name: /^전체/ }).click();
  await expect(page.locator("#pa-reqs .pa-req-table td.pa-col-id .pa-sub")).toHaveCount(0);
  await expect(page.locator("#pa-reqs")).not.toContainText("필수");
  // 요구사항 칸은 엔진이 원문에서 옮긴 이름이다. 모든 행에 이름이 있으면 "원문 발췌로 보여요" 안내가 없다.
  const fits = analysis.fits;
  await expect(page.locator("#pa-reqs .pa-req-table thead th").nth(1)).toHaveText("요구사항");
  await expect(page.locator("#pa-reqs .pa-req-table tbody tr")).toHaveCount(fits.length);
  await expect(page.locator("#pa-reqs .pa-req-table tbody tr", { hasText: fits[0].req_id }).first()).toContainText(fits[0].name as string);
  await expect(page.locator("#pa-reqs > .pa-cap")).toHaveCount(0);
  // 분석 기준 줄은 원문 요구사항 수와 분석에 넣은 수를, 요약은 한자·외국어 혼입 경고 건수를 그대로 알린다.
  const counts = analysis.requirement_counts!;
  await expect(page.locator("#pa-summary .pa-basis")).toContainText(`원문 요구사항 ${counts.source_found}건 중 ${counts.analysis_input}건 분석`);
  await expect(page.getByTestId("pa-language-warning")).toContainText(`${analysis.language_warnings!.length}곳`);

  // 쪽 번호가 없어도 원문 블록 위치가 하나로 확인된 인용은 그 사실을 알린다(쪽 번호로 바꿔 적지 않는다).
  await page.locator("#pa-reqs [data-pa-ev]").first().click();
  await expect(page.locator("#pa-ev .pa-cap").first()).toContainText("원문 위치 확인");
  await expect(page.locator("#pa-ev .pa-cap").first()).not.toContainText("쪽");
});

test("부분 결과 화면: 새 필드가 없는 옛 응답은 회사 확인을 모두 접는다", async ({ page }) => {
  await openAnalysis(page, "partial");
  const analysis = partial.analysis!;
  const requests = analysis.review_actions?.requests ?? [];
  const company = count(requests, (request) => request.kind === "company");
  const todos = page.locator("#pa-todos");
  await expect(todos.getByTestId("pa-company-decision")).toHaveCount(0);
  const fold = todos.locator("details.pa-fold");
  await expect(fold.locator("summary")).toHaveText(`회사 자료 확인 ${company}건 보기`);
  await fold.locator("summary").click();
  await expect(fold.locator("li code")).toHaveCount(company);
  await expect(page.locator("#pa-reqs > .pa-cap")).toHaveText("엔진 결과에 요구사항 이름이 없어 원문 발췌로 요구를 보여요.");
  await expect(page.locator("#pa-reqs .pa-req-table thead th").nth(1)).toHaveText("원문 발췌");
  await expect(page.locator("#pa-summary .pa-basis")).not.toContainText("원문 요구사항");
  await expect(page.getByTestId("pa-language-warning")).toHaveCount(0);
});

test("분석 완료 화면: 요구사항 필터와 근거 패널(1440 옆 패널)이 열리고 Esc로 닫히며 초점이 돌아온다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openAnalysis(page);
  const fits = completed.analysis!.fits;
  const rows = page.locator("#pa-reqs .pa-req-table tbody tr");
  const pill = (name: RegExp) => page.locator("#pa-reqs .pa-pills").getByRole("button", { name });

  // 기본 필터는 부족·미확인이다. 필터를 바꾸면 행 수가 fixture의 대응 상태 건수와 같다.
  await expect(pill(/^부족·미확인/)).toHaveAttribute("aria-pressed", "true");
  await expect(rows).toHaveCount(count(fits, (fit) => fit.fit === "GAP" || fit.fit === "UNKNOWN"));
  await pill(/^충족/).click();
  await expect(rows).toHaveCount(count(fits, (fit) => fit.fit === "FULL"));
  await pill(/^부분/).click();
  await expect(rows).toHaveCount(count(fits, (fit) => fit.fit === "PARTIAL"));
  await pill(/^전체/).click();
  await expect(rows).toHaveCount(fits.length);
  await expect(pill(/^전체/)).toHaveText(`전체 ${fits.length}`);
  await pill(/^부족·미확인/).click();

  // 근거 보기: 1440에서는 표 옆 패널이다. 회사 근거·조치 열이 숨겨지고, Esc로 닫으면 초점이 그 단추로 돌아온다.
  const opener = page.locator("[data-pa-ev]").first();
  const reqId = await opener.getAttribute("data-pa-ev");
  await opener.click();
  const panel = page.locator("aside#pa-ev");
  await expect(panel).toBeVisible();
  await expect(panel).toHaveAttribute("aria-label", `${reqId} 근거`);
  await expect(panel).toHaveClass(/is-side/);
  await expect(panel).toContainText("원문 발췌");
  await expect(panel).toContainText("판단 사유");
  await expect(page.locator("#pa-reqs .pa-req-table th", { hasText: "회사 근거" })).toHaveCount(0);
  await expect(page.locator("#pa-reqs .pa-req-table th", { hasText: "부족을 메우려면" })).toHaveCount(0);
  await expect(opener).toHaveAttribute("aria-expanded", "true");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(opener).toBeFocused();
  await expect(opener).toHaveAttribute("aria-expanded", "false");

  // 같은 단추를 다시 누르면 닫힌다(토글).
  await opener.click();
  await expect(panel).toBeVisible();
  await opener.click();
  await expect(panel).toHaveCount(0);
});

test("분석 완료 화면: 1280에서는 근거가 오른쪽 서랍이고 하단 결정 띠를 덮지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await openAnalysis(page);
  const opener = page.locator("[data-pa-ev]").first();
  await opener.click();
  const drawer = page.locator(".pa-ev-drawer aside#pa-ev");
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveClass(/is-drawer/);
  // 근거를 보는 동안에도 결정 띠와 단추가 보인다(서랍은 띠 위까지만 덮는다).
  const geometry = await page.evaluate(() => {
    const drawerBox = document.querySelector(".pa-ev-drawer")!.getBoundingClientRect();
    const footerBox = document.getElementById("page-footer")!.getBoundingClientRect();
    return { drawerBottom: drawerBox.bottom, footerTop: footerBox.top, footerHeight: footerBox.height };
  });
  expect(geometry.footerHeight).toBeGreaterThan(0);
  expect(geometry.drawerBottom).toBeLessThanOrEqual(geometry.footerTop + 1);
  await expect(page.locator("#page-footer").getByRole("button", { name: "추적 결정 저장하기" })).toBeInViewport();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(opener).toBeFocused();
});

test("분석 완료 화면: 계속 추적·보류·종료를 고르고 종료는 확인 단계를 거친다", async ({ page }) => {
  const patches = await (async () => { await mockApi(page); return mockTrackingPatches(page); })();
  await mockEngineAnalysis(page, "completed", NOTICE_ID);
  await page.goto(`/pre-specs/${NOTICE_ID}`);
  await expect(page.locator("#pa-summary")).toBeVisible();
  await setSidebarActor(page, "분석 담당");

  const bar = page.locator("#page-footer");
  const choices = bar.getByRole("group", { name: "추적 결정" });
  await expect(choices.getByRole("button")).toHaveText(["계속 추적", "보류", "종료"]);
  await expect(choices.locator("[aria-pressed=true]")).toHaveCount(0);
  await expect(bar).not.toContainText("입찰 참여는 최종 Go/No-Go에서 정해요.");
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

test("부분 결과 화면: 읽지 못한 범위를 알리고 판정 건수·차단 건수·품질 표식을 그대로 보인다", async ({ page }) => {
  await openAnalysis(page, "partial");
  const analysis = partial.analysis!;
  const notice = page.locator("#pa-summary .pa-notice");
  await expect(notice).toContainText("부분 결과예요");
  await expect(notice).toContainText(`요구사항 ${analysis.assessment!.provisional!.fit_coverage!.total}건 중 ${analysis.assessment!.provisional!.fit_coverage!.judged}건 판정`);
  await expect(notice).toContainText(partial.warnings.join(", "));
  await expect(page.locator("#pa-summary .pa-counts")).toContainText(`차단 ${count(analysis.gates, (gate) => gate.verdict === "FAIL")}`);
  await expect(page.locator("#pa-summary .pa-basis")).toContainText(qualityStatusLabel(partial.quality_status));
  // 읽지 못한 요구사항은 충족으로 읽히지 않고 미확인으로 남는다.
  const unreadRows = page.locator("#pa-reqs .pa-req-table tbody tr").filter({ hasText: "원문 발췌 없음" });
  expect(await unreadRows.count()).toBeGreaterThan(0);
  await expect(unreadRows.first()).toContainText("미확인");
  // 부분 결과는 쪽 번호가 있는 근거라 단추가 쪽을 말한다.
  await expect(page.locator("#pa-reqs [data-pa-ev]").filter({ hasText: /^\d+쪽$/ }).first()).toBeVisible();
});

// 사실 줄은 5칸(추적 상태 칸이 더해짐)이어도 각 값이 한 줄이고, 하단 띠는 분석 전 띠와 같은 높이다(1280·1440).
for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`분석 완료 화면 ${viewport.width}: 사실 줄 값이 한 줄이고 하단 띠 높이가 분석 전과 같다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openAnalysis(page);
    const facts = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("#ps-summary .ps-fact-cell")].map((cell) => {
      const dd = cell.querySelector("dd")!;
      const text = [...dd.childNodes].find((node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? "").trim() !== "");
      const range = document.createRange();
      range.selectNodeContents(text!);
      return { label: cell.querySelector("dt")!.textContent, lines: new Set([...range.getClientRects()].map((rect) => Math.round(rect.top))).size, text: text!.textContent };
    }));
    expect(facts).toHaveLength(5);
    for (const fact of facts) expect(fact.lines, `${fact.label}: ${fact.text}`).toBe(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

    const afterHeight = await page.locator("#page-footer .ps-decision-bar").evaluate((element) => Math.round(element.getBoundingClientRect().height));
    // 분석 전 화면의 띠(같은 폭)와 같은 높이다. 비교 기준은 같은 폭의 분석 전 띠 실측이다.
    const before = await page.context().newPage();
    await before.setViewportSize(viewport);
    await mockApi(before);
    await mockEngineAnalysis(before, "completed", NOTICE_ID);
    await before.route(/\/api\/companies\/.*\/engine-runs/, (route) => route.fulfill({ json: { items: [], total: 0 } }));
    await before.goto("/pre-specs/992");
    await expect(before.locator("#page-footer .ps-decision-bar")).toBeVisible();
    const beforeHeight = await before.locator("#page-footer .ps-decision-bar").evaluate((element) => Math.round(element.getBoundingClientRect().height));
    await before.close();
    expect(afterHeight).toBe(beforeHeight);
    expect(afterHeight).toBeLessThanOrEqual(73);
    // 안내 문장은 화면 글줄이 아니라 저장 단추의 비활성 사유(낭독기)로 남는다.
    await expect(page.locator("#page-footer #pre-spec-tracking-save-disabled")).toHaveText("추적 상태(계속 추적·보류·종료)를 골라 주세요.");
    await expect(page.locator("#page-footer").getByRole("button", { name: "추적 결정 저장하기" })).toHaveAttribute("aria-describedby", "pre-spec-tracking-save-disabled");
  });
}
