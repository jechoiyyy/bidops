import { expect, test, type Locator, type Page } from "@playwright/test";
import { engineReviewPreviewFixture, mockEngineReview, openProcessSectionFully, setSidebarActor } from "./api-mock";
import type { EngineReviewState } from "../src/lib/engineReviewApi";

const NOTICE_ID = 992;
const DETAIL = `/pre-specs/${NOTICE_ID}`;
const LIST = "/pre-specs?workspace=all&sw_only=false";
const START_NOTE = "추적을 시작하면 분석 요청이 함께 올라가요. 자료 전송은 확인한 뒤 따로 승인해요.";
const BULK_NOTE = "추적을 시작한 공고에 분석 요청을 올려요. 전송은 공고마다 따로 승인해요.";
const ACTOR = "검토 담당자";
const PREPARING_NOTE = "첨부 원문을 준비하고 있어요";
const REQUEST_PREPARATION_NOTE = "분석 요청으로 원문을 준비하고 있어요.";
const UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const footer = (page: Page) => page.locator("#page-footer");
const resultSummary = (page: Page) => page.getByRole("region", { name: "분석 결과 요약", exact: true });
const readButton = (scope: Locator) => scope.getByRole("button", { name: "읽음으로 표시", exact: true });
const previewBar = (page: Page) => page.locator("#pre-specs-tracking-target");
const row = (page: Page, id: number) => page.locator(`tr.pre-specs-row[data-row-key="${id}"]`);
const startButton = (scope: Locator) => scope.getByRole("button", { name: "추적 시작하기", exact: true });
const requestButton = (scope: Locator) => scope.getByRole("button", { name: "분석 요청", exact: true });
const sendButton = (scope: Locator) => scope.getByRole("button", { name: "전송 자료 확인", exact: true });
const primary = (scope: Locator) => scope.locator("button.astryx-button.primary");
const exclusivePrimary = async (scope: Locator, name: string) => {
  await expect(primary(scope)).toHaveCount(1);
  await expect(primary(scope)).toHaveAccessibleName(name);
};
const analysisChunk = (url: string) => /\/assets\/PreSpecAnalysisView-[^/]+\.(js|css)$/.test(new URL(url).pathname);

async function openBulk(page: Page, ids: number[]) {
  for (const id of ids) await row(page, id).getByRole("checkbox").check();
  await page.getByRole("button", { name: "일괄 추적 시작", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "선택한 사전규격 추적 시작" });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function openPreview(page: Page, scope = footer(page)) {
  await sendButton(scope).click();
  const dialog = page.getByRole("dialog", { name: "전송 자료 확인" });
  await expect(dialog).toBeVisible();
  return dialog;
}

test("1. off는 상세·목록 미리보기·일괄 추적·오늘 할 일의 기존 동작을 유지한다", async ({ page }) => {
  const { trace } = await mockEngineReview(page, { mode: "off" });
  const analysisAssets: string[] = [];
  page.on("request", (request) => { if (analysisChunk(request.url())) analysisAssets.push(request.url()); });

  await page.goto(DETAIL);
  await setSidebarActor(page, ACTOR);
  await expect(startButton(footer(page))).toBeEnabled();
  await expect(page.getByText(START_NOTE, { exact: true })).toHaveCount(0);
  await expect(page.locator("#pa-summary")).toHaveCount(0);

  await page.goto(LIST);
  await row(page, NOTICE_ID).click();
  await expect(startButton(previewBar(page))).toBeEnabled();
  await expect(page.getByText(START_NOTE, { exact: true })).toHaveCount(0);
  const dialog = await openBulk(page, [NOTICE_ID]);
  await expect(dialog.getByText("사업기회에 연결된 미선택 공고만 추적을 시작해요.")).toBeVisible();
  await expect(dialog.getByText(BULK_NOTE, { exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "취소", exact: true }).click();

  await startButton(previewBar(page)).click();
  await expect(previewBar(page)).toContainText("추적 상태를 계속 추적(으)로 기록했어요.");
  expect(trace.trackingPatches).toEqual([{ noticeId: NOTICE_ID, body: { tracking_status: "계속 추적" }, actor: ACTOR }]);

  await page.goto("/");
  const check = page.getByRole("list", { name: "확인할 것 건수" });
  await expect(check.getByRole("link", { name: /사전규격 확인 필요/ })).toBeVisible();
  await expect(check.getByRole("link", { name: /분석 승인 대기|결과 확인/ })).toHaveCount(0);
  expect(trace.calls).toEqual([]);
  if (!process.env.BIDOPS_MOCK_UI) expect(analysisAssets).toEqual([]);
});

const decisionCases: {
  state: EngineReviewState;
  label: string;
  reason?: string;
  primaryAction?: string;
  secondaryAction?: string;
  result?: boolean;
}[] = [
  { state: "not_requested", label: "분석 요청 없음", secondaryAction: "분석 요청" },
  { state: "preparing", label: "분석 준비 중", reason: PREPARING_NOTE },
  { state: "blocked", label: "분석할 수 없어요", reason: "HWP 또는 HWPX 원본을 준비해 주세요." },
  { state: "awaiting_approval", label: "분석 승인 대기", primaryAction: "전송 자료 확인" },
  { state: "queued", label: "분석 대기" },
  { state: "running", label: "분석 중" },
  { state: "result_ready", label: "결과 확인", primaryAction: "추적 결정 저장하기", secondaryAction: "읽음으로 표시", result: true },
  { state: "acknowledged", label: "결과 읽음", result: true },
  { state: "stale", label: "이전 입력 기준", secondaryAction: "분석 요청", result: true },
];

for (const entry of decisionCases) {
  test(`2. ${entry.state}의 상태 문구와 결정 행동`, async ({ page }) => {
    await mockEngineReview(page, { tracking: "계속 추적", initialState: entry.state });
    await page.goto(DETAIL);
    const bar = footer(page);
    const statusScope = entry.state === "result_ready" ? resultSummary(page) : bar;
    await expect(statusScope.getByText(entry.label, { exact: true })).toBeVisible();
    if (entry.reason) await expect(bar.getByText(entry.reason, { exact: true })).toBeVisible();
    if (entry.primaryAction) await exclusivePrimary(bar, entry.primaryAction);
    else await expect(primary(bar)).toHaveCount(0);

    const secondary = page.getByRole("button", { name: /^(분석 요청|읽음으로 표시)$/ });
    if (entry.secondaryAction) {
      await expect(secondary).toHaveCount(1);
      await expect(secondary).toHaveAccessibleName(entry.secondaryAction);
      await expect(secondary).toHaveClass(/\bsecondary\b/);
    } else await expect(secondary).toHaveCount(0);

    if (entry.result) await expect(page.locator("#pa-summary")).toBeVisible();
    else await expect(page.locator("#pa-summary")).toHaveCount(0);
    if (entry.state === "result_ready") {
      await expect(readButton(resultSummary(page))).toBeVisible();
      await expect(bar.getByRole("group", { name: "추적 결정" }).getByRole("button"))
        .toHaveText(["계속 추적", "보류", "종료"]);
    } else {
      await expect(bar.getByRole("button", { name: /^(계속 추적|보류|종료|추적 시작하기)$/ })).toHaveCount(0);
    }
    if (entry.state === "acknowledged") {
      await expect(bar.getByRole("link", { name: /사업 추적에서 상태 관리/ })).toHaveAttribute("href", "/opportunities/78");
    }
  });
}

test("2. 목록 미리보기에서 추적을 시작하고 이미 추적 중인 공고에서 수동으로 요청한다", async ({ page }) => {
  const { trace, setState } = await mockEngineReview(page, { autoPreparationOnRequest: true });
  await page.goto(LIST);
  await row(page, NOTICE_ID).click();
  await setSidebarActor(page, ACTOR);
  const bar = previewBar(page);
  await expect(page.getByText(START_NOTE, { exact: true })).toBeVisible();
  await startButton(bar).click();
  await expect(bar.getByText("분석 준비 중", { exact: true })).toBeVisible();
  expect(trace.order).toEqual(["tracking", "requests"]);
  setState(NOTICE_ID, "not_requested");
  await expect(requestButton(bar)).toBeVisible();
  await requestButton(bar).click();
  await expect(bar.getByText("분석 준비 중", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "선택한 사전규격", exact: true })
    .getByText(REQUEST_PREPARATION_NOTE, { exact: true })).toBeVisible();
  expect(trace.trackingPatches).toHaveLength(1);
  expect(trace.calls.filter((call) => call.command === "requests").map((call) => call.body?.origin))
    .toEqual(["tracking_start", "manual"]);
});

test("3. 추적 시작부터 자료 승인과 분석 결과를 거쳐 계속 추적을 저장하고 읽음을 남긴다", async ({ page }) => {
  const preview = engineReviewPreviewFixture(NOTICE_ID);
  const { trace, setState } = await mockEngineReview(page, { previewManifest: {
    sections: [...preview.manifest.sections, { id: "S002", heading: "참여 조건", page_start: null, page_end: null }],
  } });
  const assets: string[] = [];
  page.on("request", (request) => { if (analysisChunk(request.url())) assets.push(request.url()); });
  await page.goto(DETAIL);
  await setSidebarActor(page, ACTOR);
  const bar = footer(page);
  await expect(bar.getByText(START_NOTE, { exact: true })).toBeVisible();
  await exclusivePrimary(bar, "추적 시작하기");
  await startButton(bar).click();
  await expect(bar.getByText("분석 준비 중", { exact: true })).toBeVisible();
  await expect(bar.getByText(PREPARING_NOTE, { exact: true })).toBeVisible();
  expect(trace.order).toEqual(["tracking", "requests"]);
  expect(trace.calls.filter((call) => call.command === "requests")).toEqual([
    { command: "requests", noticeId: NOTICE_ID, body: { request_id: expect.stringMatching(UUID), origin: "tracking_start" }, actor: ACTOR },
  ]);
  expect(trace.trackingPatches).toEqual([{ noticeId: NOTICE_ID, body: { tracking_status: "계속 추적" }, actor: ACTOR }]);

  setState(NOTICE_ID, "awaiting_approval");
  const dialog = await openPreview(page);
  await expect(dialog.getByText("제안요청서.hwpx · 12쪽")).toBeVisible();
  await expect(dialog.getByText("사업 범위 · 2–4쪽")).toBeHidden();
  await dialog.getByText("절 2개 보기", { exact: true }).click();
  await expect(dialog.getByText("사업 범위 · 2–4쪽")).toBeVisible();
  await expect(dialog.getByText("참여 조건 · 쪽 범위 미확인")).toBeVisible();
  await expect(dialog.getByText("쪽 범위는 확인되지 않았어요", { exact: true })).toHaveCount(0);
  await expect(dialog.getByText(preview.manifest.company_bundle_sha256.slice(0, 12), { exact: true })).toBeVisible();
  for (const value of ["rootlab", "capabilities", "portfolio-extra", "1,250자", "mock_reference · mock_reference", "예정 0회 · 남은 상한 0회", "10:00 (KST)"]) {
    await expect(dialog).toContainText(value);
  }
  const mockMark = dialog.locator(".workbench-mark").filter({ hasText: "모의 실행이에요. 외부로 전송하지 않아요." });
  await expect(mockMark).toBeVisible();
  await expect(mockMark).toHaveAttribute("data-tone", "neutral");
  await exclusivePrimary(dialog, "승인");
  expect(trace.order).toEqual(["tracking", "requests", "previews"]);
  await dialog.getByRole("button", { name: "승인", exact: true }).click();

  await expect(dialog).toHaveCount(0);
  await expect(bar.getByText("분석 중", { exact: true })).toBeVisible();
  expect(trace.calls.filter((call) => call.command === "approvals")).toEqual([
    { command: "approvals", noticeId: NOTICE_ID, body: { preview_id: preview.preview_id, manifest_sha256: preview.manifest_sha256, request_id: expect.stringMatching(UUID) }, actor: ACTOR },
  ]);
  if (!process.env.BIDOPS_MOCK_UI) expect(assets).toEqual([]);
  setState(NOTICE_ID, "result_ready");
  await expect(page.locator("#pa-summary")).toBeVisible();
  await expect(page.getByText("mock 참조", { exact: true })).toBeVisible();
  if (!process.env.BIDOPS_MOCK_UI) expect(assets.some((url) => url.endsWith(".js"))).toBe(true);

  await bar.getByRole("button", { name: "계속 추적", exact: true }).click();
  await bar.getByRole("combobox", { name: "선택 사유", exact: true }).click();
  await page.getByRole("option", { name: "기타 · 직접 입력", exact: true }).click();
  await bar.getByRole("textbox", { name: "선택 사유 직접 입력 (필수)" }).fill("원문을 대조했고 계속 확인하기로 했어요.");
  await bar.getByRole("button", { name: "추적 결정 저장하기", exact: true }).click();
  await expect(bar.getByText("추적 상태를 계속 추적(으)로 기록했어요.")).toBeVisible();
  expect(trace.trackingPatches).toEqual([
    { noticeId: NOTICE_ID, body: { tracking_status: "계속 추적" }, actor: ACTOR },
    { noticeId: NOTICE_ID, body: { tracking_status: "계속 추적", reason: "원문을 대조했고 계속 확인하기로 했어요." }, actor: ACTOR },
  ]);
  await readButton(resultSummary(page)).click();
  await expect(bar.getByText("결과 읽음", { exact: true })).toBeVisible();
  await expect(readButton(resultSummary(page))).toHaveCount(0);
  await expect(page.locator("#pa-summary")).toBeVisible();
  expect(trace.order).toEqual(["tracking", "requests", "previews", "approvals", "tracking", "acknowledgments"]);
  expect(trace.calls.filter((call) => call.command === "acknowledgments")).toEqual([
    { command: "acknowledgments", noticeId: NOTICE_ID, body: { result_id: "5f0b9a7e-2c1d-4e8f-9a6b-000000000b01", request_id: expect.stringMatching(UUID) }, actor: ACTOR },
  ]);
});

test("4. 요청 503 뒤 추적을 유지하고 같은 요청 ID로 분석만 재시도한다", async ({ page }) => {
  const { trace, tracking } = await mockEngineReview(page, { failFirstRequest: true });
  await page.goto(DETAIL);
  await setSidebarActor(page, ACTOR);
  const bar = footer(page);
  await startButton(bar).click();
  await expect(bar.getByRole("alert")).toContainText("추적은 시작했어요. 분석 요청은 올리지 못했어요.");
  await expect(bar.getByRole("alert")).toContainText("엔진을 사용할 수 없어요.");
  expect(tracking.get(NOTICE_ID)).toBe("계속 추적");
  await expect(startButton(bar)).toHaveCount(0);
  await requestButton(bar).click();
  await expect(bar.getByText("분석 준비 중", { exact: true })).toBeVisible();
  await expect(bar.getByRole("alert")).toHaveCount(0);
  expect(trace.order).toEqual(["tracking", "requests", "requests"]);
  const requests = trace.calls.filter((call) => call.command === "requests");
  expect(requests[0].body?.request_id).toMatch(UUID);
  expect(requests[1]).toEqual(requests[0]);
});

test("4. 미결정 목록에서 빠진 공고도 상세 띠에서 같은 요청 ID로 재시도한다", async ({ page }) => {
  const { trace } = await mockEngineReview(page, { failFirstRequest: true });
  await page.goto("/pre-specs?workspace=needs_check");
  await row(page, NOTICE_ID).click();
  await setSidebarActor(page, ACTOR);
  await startButton(previewBar(page)).click();
  await expect(page).toHaveURL(/\/pre-specs\/992(?:\?|$)/);
  await expect(footer(page).getByRole("alert")).toContainText("추적은 시작했어요. 분석 요청은 올리지 못했어요.");
  await requestButton(footer(page)).click();
  await expect(footer(page).getByText("분석 준비 중", { exact: true })).toBeVisible();
  const commands = trace.calls.filter((call) => call.command === "requests");
  expect(commands).toHaveLength(2);
  expect(commands[1]).toEqual(commands[0]);
  expect(trace.trackingPatches).toHaveLength(1);
});

test("5. 자료 확인에서 Esc와 닫기는 초점을 복귀시키고 건너뛰기는 요청을 닫는다", async ({ page }) => {
  const { trace } = await mockEngineReview(page, { tracking: "계속 추적", initialState: "awaiting_approval" });
  await page.goto(DETAIL);
  await sendButton(footer(page)).click();
  const sidebar = page.locator("aside.sidebar");
  await expect(sidebar.getByLabel("담당자 이름")).toBeFocused();
  expect(trace.calls.filter((call) => call.command === "previews")).toEqual([]);
  await sidebar.getByLabel("담당자 이름").fill(ACTOR);
  await sidebar.getByRole("button", { name: "닫기", exact: true }).click();

  const trigger = sendButton(footer(page));
  const dialog = await openPreview(page);
  await expect(dialog.getByRole("button", { name: "승인", exact: true })).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await openPreview(page);
  await dialog.getByRole("button", { name: "닫기", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await openPreview(page);
  await dialog.getByRole("button", { name: "이번엔 보내지 않음", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(requestButton(footer(page))).toBeVisible();
  expect(trace.order).toEqual(["previews", "previews", "previews", "dismissals"]);
  expect(trace.calls.filter((call) => call.command === "dismissals")).toEqual([
    { command: "dismissals", noticeId: NOTICE_ID, body: { preview_id: engineReviewPreviewFixture(NOTICE_ID).preview_id, request_id: expect.stringMatching(UUID) }, actor: ACTOR },
  ]);
});

for (const conflict of ["preview_expired", "input_changed"] as const) {
  test(`5. ${conflict} 응답 후 새 미리보기와 새 해시를 승인한다`, async ({ page }) => {
    const { trace } = await mockEngineReview(page, { tracking: "계속 추적", initialState: "awaiting_approval", approvalConflict: conflict });
    await page.goto(DETAIL);
    await setSidebarActor(page, ACTOR);
    const dialog = await openPreview(page);
    await dialog.getByRole("button", { name: "승인", exact: true }).click();
    await expect(dialog.getByRole("alert")).toHaveText("자료가 바뀌었어요. 다시 확인해 주세요.");
    await expect(dialog.getByRole("button", { name: "승인", exact: true })).toHaveCount(0);
    await dialog.getByRole("button", { name: "다시 불러오기", exact: true }).click();
    await dialog.getByRole("button", { name: "승인", exact: true }).click();
    await expect(footer(page).getByText("분석 중", { exact: true })).toBeVisible();

    const previews = trace.calls.filter((call) => call.command === "previews");
    const approvals = trace.calls.filter((call) => call.command === "approvals");
    expect(previews).toHaveLength(2);
    expect(previews[0].body?.request_id).not.toBe(previews[1].body?.request_id);
    expect(approvals).toHaveLength(2);
    for (const [index, call] of approvals.entries()) {
      const preview = engineReviewPreviewFixture(NOTICE_ID, index > 0);
      expect(call.body).toEqual({ preview_id: preview.preview_id, manifest_sha256: preview.manifest_sha256, request_id: expect.stringMatching(UUID) });
    }
    expect(approvals[0].body?.request_id).not.toBe(approvals[1].body?.request_id);
  });
}

test("5. 보류 중인 사전규격의 승인 대기는 전송 자료 버튼 없이 표시한다", async ({ page }) => {
  const { trace } = await mockEngineReview(page, { tracking: "보류", initialState: "awaiting_approval" });
  await page.goto(DETAIL);
  const bar = footer(page);
  await expect(bar.getByText("분석 승인 대기", { exact: true })).toBeVisible();
  await expect(bar.getByText("보류 중에는 승인할 수 없어요", { exact: true })).toBeVisible();
  await expect(sendButton(bar)).toHaveCount(0);
  await expect(primary(bar)).toHaveCount(0);
  expect(trace.order).toEqual([]);
});

for (const [code, copy] of [
  ["engine_disabled", "이 환경에서는 엔진 분석이 꺼져 있어요."],
  ["engine_live_disabled", "이 환경에서는 실제 전송을 사용할 수 없어요."],
  ["engine_unavailable", "엔진을 사용할 수 없어요. 잠시 후 다시 시도해 주세요."],
] as const) {
  test(`5. 자료 확인의 503 ${code}는 원인과 재조회 행동을 표시한다`, async ({ page }) => {
    const { trace } = await mockEngineReview(page, { tracking: "계속 추적", initialState: "awaiting_approval", previewError: code });
    await page.goto(DETAIL);
    await setSidebarActor(page, ACTOR);
    const dialog = await openPreview(page);
    await expect(dialog.getByRole("alert")).toHaveText(copy);
    await expect(dialog.getByRole("button", { name: "승인", exact: true })).toHaveCount(0);
    await dialog.getByRole("button", { name: "다시 불러오기", exact: true }).click();
    await expect(dialog.getByRole("alert")).toHaveText(copy);
    expect(trace.order).toEqual(["previews", "previews"]);
    const previews = trace.calls.filter((call) => call.command === "previews");
    expect(previews[1]).toEqual(previews[0]);
  });
}

for (const batchError of [false, true]) {
  test(batchError ? "6. 일괄 요청 호출 실패에도 추적 결과를 유지한다" : "6. 일괄 추적에서 started만 요청하고 결과와 실패 사유를 요약한다", async ({ page }) => {
    const { trace, tracking } = await mockEngineReview(page, { batchItems: true, batchError, batchIneligible: 991 });
    await page.goto(LIST);
    const dialog = await openBulk(page, [991, 992, 993, 994]);
    await expect(dialog.getByText(BULK_NOTE, { exact: true })).toBeVisible();
    await dialog.getByRole("textbox", { name: "담당자 이름 · 감사 표식 (필수)", exact: true }).fill(ACTOR);
    await dialog.getByRole("button", { name: "4건 추적 시작", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const summary = page.locator(".pre-specs-selection-message");
    await expect(summary).toContainText("추적 시작 2건 · 기존 결정 유지 1건 · 연결 확인 필요 1건");
    if (batchError) await expect(summary).toContainText("분석 요청은 올리지 못했어요");
    else await expect(summary).toContainText("분석 요청 1건 · 요청 못 함 1건 (회사 자료 묶음의 구성과 검증 상태를 확인해 주세요. 1건)");
    expect(trace.order).toEqual(["bulk-start", "requests:batch"]);
    const [{ actor, body }] = trace.calls.filter((call) => call.command === "requests:batch");
    expect(actor).toBe(ACTOR);
    expect(body).toEqual({ request_id: expect.stringMatching(UUID), origin: "tracking_start", notice_ids: [991, 992] });
    expect(tracking.get(991)).toBe("계속 추적");
    expect(tracking.get(992)).toBe("계속 추적");
    expect(trace.trackingPatches).toEqual([]);
  });
}

test("7. 오늘 할 일의 분석 건수에서 기존 추적 중 보기로 이동한다", async ({ page }) => {
  await mockEngineReview(page, { workload: { approvals: 2, results: 1 } });
  await page.goto("/");
  const approval = page.getByRole("link", { name: /분석 승인 대기 2건/ });
  const result = page.getByRole("link", { name: /결과 확인 1건/ });
  await expect(approval).toHaveAttribute("href", "/pre-specs?workspace=tracking");
  await expect(result).toHaveAttribute("href", "/pre-specs?workspace=tracking");
  await result.click();
  await expect(page).toHaveURL(/\/pre-specs\?workspace=tracking$/);
});

test("7. 오늘 할 일에서 0건을 보이고 null인 분석 건수 칸은 숨긴다", async ({ page }) => {
  await mockEngineReview(page, { workload: { approvals: 0, results: null } });
  await page.goto("/");
  const check = page.getByRole("list", { name: "확인할 것 건수" });
  await expect(check.getByRole("link", { name: /분석 승인 대기 0건/ })).toBeVisible();
  await expect(check.getByRole("link", { name: /결과 확인/ })).toHaveCount(0);
});

async function expectBarFits(bar: Locator) {
  await expect(bar).toBeVisible();
  const geometry = await bar.evaluate((element) => ({
    height: Math.round(element.getBoundingClientRect().height),
    barFits: element.scrollWidth <= element.clientWidth,
    pageFits: document.documentElement.scrollWidth <= window.innerWidth,
  }));
  expect(geometry.height).toBeLessThanOrEqual(56);
  expect(geometry.barFits).toBe(true);
  expect(geometry.pageFits).toBe(true);
}

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
  test(`8. ${viewport.width}px에서 상세·목록의 결정 띠 높이와 가로 넘침 계약을 지킨다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const { tracking, setState } = await mockEngineReview(page);
    await page.goto(DETAIL);
    await expect(footer(page).getByText(START_NOTE, { exact: true })).toBeVisible();
    await expectBarFits(footer(page).locator(".ps-decision-bar"));
    await page.goto(LIST);
    await row(page, NOTICE_ID).click();
    await expect(page.getByText(START_NOTE, { exact: true })).toBeVisible();
    await expectBarFits(previewBar(page));

    tracking.set(NOTICE_ID, "계속 추적");
    setState(NOTICE_ID, "awaiting_approval");
    await page.reload();
    await row(page, NOTICE_ID).click();
    await expect(sendButton(previewBar(page))).toBeVisible();
    await expectBarFits(previewBar(page));

    setState(NOTICE_ID, "result_ready");
    await page.goto(DETAIL);
    await setSidebarActor(page, ACTOR);
    await expect(page.locator("#pa-summary")).toBeVisible();
    await footer(page).getByRole("button", { name: "계속 추적", exact: true }).click();
    await footer(page).getByRole("combobox", { name: "선택 사유", exact: true }).click();
    await page.getByRole("option", { name: "기타 · 직접 입력", exact: true }).click();
    const directReason = footer(page).getByRole("textbox", { name: "선택 사유 직접 입력 (필수)" });
    await directReason.fill("원문 확인 후 계속 추적");
    await expect(directReason).toBeInViewport();
    await expect(footer(page).getByRole("button", { name: "추적 결정 저장하기", exact: true })).toBeInViewport();
    await expectBarFits(footer(page).locator(".ps-decision-bar"));
  });
}

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`절 70개 미리보기 ${viewport.width}×${viewport.height}에서 회사 자료 요약과 승인 버튼을 첫 화면에 보여 준다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    const manifest = {
      sections: Array.from({ length: 70 }, (_, index) => ({
        id: `S${String(index + 1).padStart(3, "0")}`,
        heading: index < 2 ? "사업 개요" : `요구사항 ${index + 1}`,
        page_start: null,
        page_end: null,
      })),
      wiki_pages: Array.from({ length: 12 }, (_, index) => `wiki-selected-${index + 1}`),
      wiki_pages_skipped: Array.from({ length: 11 }, (_, index) => `wiki-skipped-${index + 1}`),
    };
    await mockEngineReview(page, { tracking: "계속 추적", initialState: "awaiting_approval", previewManifest: manifest });
    await page.goto(DETAIL);
    await setSidebarActor(page, ACTOR);
    const dialog = await openPreview(page);
    const controls = ["닫기", "이번엔 보내지 않음", "승인"].map((name) => dialog.getByRole("button", { name, exact: true }));
    const sections = dialog.getByText("절 70개 보기", { exact: true });
    const selected = dialog.getByText("선택한 위키 페이지 12개 보기", { exact: true });
    const skipped = dialog.getByText("빠진 위키 페이지 11개 보기", { exact: true });
    const sectionList = dialog.getByRole("list", { name: "절·쪽 범위", exact: true });
    const selectedList = dialog.getByRole("list", { name: "선택한 위키 페이지", exact: true });
    const skippedList = dialog.getByRole("list", { name: "빠진 위키 페이지", exact: true });
    const body = dialog.locator(".bulk-dialog-body");
    const digest = engineReviewPreviewFixture(NOTICE_ID).manifest.company_bundle_sha256.slice(0, 12);
    const fields = [
      dialog.getByText("모의 실행이에요. 외부로 전송하지 않아요.", { exact: true }),
      dialog.getByText("제안요청서.hwpx · 12쪽", { exact: true }),
      dialog.getByText(digest, { exact: true }),
      dialog.getByText("선택한 위키 12쪽 · 발췌 1,250자 · 분량 때문에 빠진 위키 11쪽", { exact: true }),
      dialog.getByText("mock_reference · mock_reference", { exact: true }),
      dialog.getByText("예정 0회 · 남은 상한 0회", { exact: true }),
      dialog.locator("time"),
      sections,
    ];
    const summaryPositions: number[] = [];
    for (const field of fields) {
      await expect(field).toBeInViewport({ ratio: 1 });
      summaryPositions.push((await field.boundingBox())!.y);
    }
    expect(summaryPositions).toEqual([...summaryPositions].sort((a, b) => a - b));
    for (const control of controls) await expect(control).toBeInViewport({ ratio: 1 });
    expect(await body.evaluate((element) => element.scrollTop)).toBe(0);
    await expect(sectionList).toBeHidden();
    await expect(selectedList).toBeHidden();
    await expect(skippedList).toBeHidden();

    await selected.click();
    await expect(selectedList.getByRole("listitem")).toHaveCount(12);
    await skipped.click();
    await expect(skippedList.getByRole("listitem")).toHaveCount(11);
    await sections.click();
    await expect(sectionList.getByRole("listitem")).toHaveCount(70);
    await expect(sectionList.getByRole("listitem").filter({ hasText: /^사업 개요$/ })).toHaveCount(2);
    await expect(dialog.getByText("쪽 범위는 확인되지 않았어요", { exact: true })).toHaveCount(1);
    await expect(sectionList).not.toContainText("쪽 범위 미확인");

    const beforeScroll = await Promise.all(controls.map(async (control) => (await control.boundingBox())!.y));
    const scrollTop = await body.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
      return element.scrollTop;
    });
    expect(scrollTop).toBeGreaterThan(0);
    for (const [index, control] of controls.entries()) {
      await expect(control).toBeInViewport({ ratio: 1 });
      expect((await control.boundingBox())!.y).toBeCloseTo(beforeScroll[index], 0);
    }
  });
}

test("부분 결과의 실행 경고는 업무 문장으로 한 번씩 보이고 원문은 접힌 기술 정보에 남는다", async ({ page }) => {
  const skipped = "knowledge: pages skipped by budget: wiki-a, wiki-b";
  const warnings = [
    "mock_reference_not_quality_evidence", "structure_projection_partial", skipped, skipped,
    "knowledge: pages skipped by budget: wiki-b, wiki-c",
    "structure_projection_partial", "future_warning_one", "future_warning_one", "future_warning_two",
  ];
  await mockEngineReview(page, { tracking: "계속 추적", initialState: "result_ready", partialResultWarnings: warnings });
  await page.goto(DETAIL);
  const summary = resultSummary(page);
  const notice = summary.getByRole("note").filter({ hasText: "부분 결과예요" });
  await expect(notice).toBeVisible();
  const copy = [
    "모의 실행 결과예요. 품질 근거로 쓰지 않아요.",
    "문서 구조의 일부만 반영됐어요.",
    "회사 위키 3쪽은 분량 때문에 빠졌어요.",
    "그 밖의 경고 2건",
  ];
  for (const message of copy) {
    await expect(notice).toContainText(message);
    expect((await notice.innerText()).split(message)).toHaveLength(2);
  }

  const details = summary.locator("details.pa-warning-details");
  const raw = [...new Set(warnings)];
  for (const warning of raw) {
    await expect(notice).not.toContainText(warning);
    await expect(details.getByText(warning, { exact: true })).toBeHidden();
  }
  await details.getByText("실행 경고 기술 정보", { exact: true }).click();
  await expect(details.getByRole("listitem")).toHaveCount(raw.length);
  for (const warning of raw) await expect(details.getByText(warning, { exact: true })).toBeVisible();
});

test("결과 요약의 읽음 버튼이 차단·자격 조건 본문과 겹치지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEngineReview(page, { tracking: "계속 추적", initialState: "result_ready" });
  await page.goto(DETAIL);
  const readLine = resultSummary(page).locator(".pa-summary-review");
  const gates = page.locator("#pa-gates");
  await expect(readButton(readLine)).toBeVisible();
  await expect(readButton(footer(page))).toHaveCount(0);
  await gates.scrollIntoViewIfNeeded();
  const readLineBox = (await readLine.boundingBox())!;
  const gatesBox = (await gates.boundingBox())!;
  expect(readLineBox.y + readLineBox.height).toBeLessThanOrEqual(gatesBox.y);
  await expectBarFits(footer(page).locator(".ps-decision-bar"));
});

test("결과 상태의 추적 결정 region은 하나이며 저장 동작을 포함한다", async ({ page }) => {
  await mockEngineReview(page, { tracking: "계속 추적", initialState: "result_ready" });
  await page.goto(DETAIL);
  const region = page.getByRole("region", { name: "추적 결정", exact: true });
  await expect(region.getByRole("button", { name: "추적 결정 저장하기", exact: true })).toBeVisible();
  await expect(region).toHaveCount(1);
});

test("1280px에서 추적 결정 저장 직후 결과 띠에 저장 문구만 한 줄로 보인다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  const { trace } = await mockEngineReview(page, { tracking: "계속 추적", initialState: "result_ready" });
  await page.goto(DETAIL);
  await setSidebarActor(page, ACTOR);
  const region = page.getByRole("region", { name: "추적 결정", exact: true });
  await region.getByRole("button", { name: "계속 추적", exact: true }).click();
  await region.getByRole("combobox", { name: "선택 사유", exact: true }).click();
  await page.getByRole("option", { name: "기타 · 직접 입력", exact: true }).click();
  await region.getByRole("textbox", { name: "선택 사유 직접 입력 (필수)" }).fill("원문 확인 후 계속 추적");
  await region.getByRole("button", { name: "추적 결정 저장하기", exact: true }).click();
  const saved = region.getByRole("status").filter({ hasText: "기록했어요" });
  await expect(saved).toHaveText("추적 상태를 계속 추적(으)로 기록했어요.");
  await expect(region.getByText("현재 추적 상태 계속 추적", { exact: true })).toHaveCount(0);
  const lineCount = await saved.evaluate((element) => {
    const range = document.createRange();
    range.selectNodeContents(element);
    return new Set(Array.from(range.getClientRects(), (rect) => rect.top)).size;
  });
  expect(lineCount).toBe(1);
  expect(trace.trackingPatches).toHaveLength(1);
  await expectBarFits(footer(page).locator(".ps-decision-bar"));
});

test("분석 요청 성공 뒤 상세 조회를 다시 하고 문서 준비 카드의 사유를 갱신한다", async ({ page }) => {
  const { trace } = await mockEngineReview(page, {
    tracking: "계속 추적", initialState: "not_requested", autoPreparationOnRequest: true,
  });
  await page.goto(DETAIL);
  await setSidebarActor(page, ACTOR);
  await openProcessSectionFully(page);
  const preparation = page.getByLabel("자동 준비 진행");
  await expect(preparation.getByText("자동 문서 준비 대상이 아니에요.", { exact: true })).toBeVisible();

  const [projection] = await Promise.all([
    page.waitForResponse((response) => {
      const url = new URL(response.url());
      return response.request().method() === "GET" && url.pathname === "/api/pre-specs"
        && url.searchParams.get("notice_pk") === String(NOTICE_ID);
    }),
    page.waitForResponse((response) => response.request().method() === "GET"
      && new URL(response.url()).pathname === `/api/notices/${NOTICE_ID}/document-bundles`),
    requestButton(footer(page)).click(),
  ]);
  expect(await projection.json()).toMatchObject({
    items: [{ notice_pk: NOTICE_ID, auto_preparation_status: "waiting_attachments", auto_preparation_reason: "engine_review_request" }],
  });
  await expect(preparation.getByText(REQUEST_PREPARATION_NOTE, { exact: true })).toBeVisible();
  await expect(preparation.getByText("자동 문서 준비 대상이 아니에요.", { exact: true })).toHaveCount(0);
  expect(trace.order).toEqual(["requests"]);
});

test("전송 자료 미리보기에서 쪽 수가 null인 문서는 쪽 수 미확인으로 표시한다", async ({ page }) => {
  const preview = engineReviewPreviewFixture(NOTICE_ID);
  await mockEngineReview(page, {
    tracking: "계속 추적", initialState: "awaiting_approval",
    previewManifest: { documents: preview.manifest.documents.map((document) => ({ ...document, page_count: null })) },
  });
  await page.goto(DETAIL);
  await setSidebarActor(page, ACTOR);
  const dialog = await openPreview(page);
  const documentRow = dialog.getByRole("listitem").filter({ hasText: "제안요청서.hwpx" });
  await expect(documentRow).toHaveText("제안요청서.hwpx · 쪽 수 미확인");
  await expect(documentRow).toBeVisible();
});
