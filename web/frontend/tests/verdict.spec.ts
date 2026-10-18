import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockBriefing, mockOpportunityRecord, type OpportunityRecordMockTrace } from "./api-mock";
import { BRIEFING_NOW, briefingFixture, briefingItemId } from "./fixtures/briefing";
import { RECORD_NOW } from "./fixtures/opportunity-record";
import {
  FORBIDDEN_VALUES,
  LONG_REASON,
  MODEL_NAME,
  POLICY_ID,
  POLICY_SHA,
  SOURCE_SHA,
  VERDICT_ATTEMPT_ID,
  VERDICT_COMPANY_ID,
  VERDICT_NOTICE_ID,
  VERDICT_STRUCTURE_ID,
  completedView,
  failedView,
  largeMatrix,
  legacyView,
  noneView,
  runningView,
  sampleMatrix,
} from "./fixtures/verdict";
import type { BriefingVerdictDisplay, PractitionerVerdictView } from "../src/lib/types";

/*
 * RL-03 STEP-009 · spec T7 — `/opportunities/:id/verdict` 사업기회 레코드 판정 탭.
 *
 * 고정 응답은 `mockApi`(미등록 경로는 404) 위에 건 `mockOpportunityRecord`의 판정 응답이며 실제 백엔드에
 * 연결하지 않는다. 판정 상태는 `trace.setVerdict`로 서버 쪽을 바꾼다. 화면 시계는 `RECORD_NOW`로 고정한다.
 * 기대값은 화면 코드를 가져오지 않고 fixture 값으로 직접 적었다(요구사항 표 구성은 fixtures/verdict.ts 머리말).
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// 정렬 후 순서: 부족(R3·R5) → 확인 필요(R2·R4·R7) → 충족(R1·R6), 동률은 서버(동결) 순서.
const R = {
  1: "클라우드 기반 통합 인증 체계를 제공해야 한다",
  2: "정보보호 전문 인력 3명 이상을 상주시켜야 한다",
  3: "직접생산 확인증명서(소프트웨어)를 보유해야 한다",
  4: "장애 발생 시 30분 이내 대응 체계를 갖추어야 한다",
  5: "성과물의 지식재산권은 발주기관에 귀속한다",
  6: "최근 3년 내 유사 사업 수행 실적 1건 이상",
  7: "개인정보 처리 시스템은 보안 인증을 받아야 한다",
} as const;
const SORTED = [R[3], R[5], R[2], R[4], R[7], R[1], R[6]];
const DEFAULT_ROWS = [R[3], R[5], R[2], R[4], R[7]];

async function openVerdict(
  page: Page,
  view: PractitionerVerdictView | null,
  path = "/opportunities/7101/verdict",
): Promise<OpportunityRecordMockTrace> {
  await page.clock.setFixedTime(new Date(RECORD_NOW));
  await mockApi(page);
  const trace = await mockOpportunityRecord(page);
  if (view) trace.setVerdict(7101, view);
  await page.goto(path);
  return trace;
}

const rows = (page: Page) => page.locator("tr.vd-row");
const rowTitles = (page: Page) => page.locator("tr.vd-row .vd-row-title").allTextContents();
const rowOf = (page: Page, text: string) => page.locator("tr.vd-row").filter({ hasText: text });
const headerPills = (page: Page) => page.locator('[data-testid="record-header"] .rec-pill').allTextContents();
const toast = (page: Page) => page.locator(".toast");
const panel = (page: Page) => page.getByTestId("source-panel");
const actorInput = (dialog: ReturnType<Page["getByRole"]>) => dialog.getByLabel(/기록자/);

async function chooseFilter(page: Page, label: string) {
  await page.getByRole("combobox", { name: "상태", exact: true }).click();
  await page.getByRole("option", { name: label, exact: true }).click();
}

async function waitTable(page: Page) {
  await expect(page.getByRole("table", { name: "요구사항 대조표" })).toBeVisible();
}

test("판정이 없으면 '아직 판정이 없습니다'와 다시 판정을 보이고 헤더는 분석 대기·판정 보기 비활성이다", async ({ page }) => {
  const trace = await openVerdict(page, null);
  const tabpanel = page.getByRole("tabpanel");
  await expect(tabpanel.getByText("아직 판정이 없습니다", { exact: true })).toBeVisible();
  await expect(tabpanel.getByRole("button", { name: "다시 판정", exact: true })).toBeEnabled();
  expect(await headerPills(page)).toEqual(["입찰공고", "D-4", "분석 대기", "계속 추적"]);
  // 판정 탭에서는 제안서 초안(판정이 없으면 비활성)·다시 판정·⋯가 헤더 액션이고 판정 보기는 없다.
  const header = page.locator('[data-testid="record-header"]');
  await expect(header.getByRole("button", { name: "제안서 초안", exact: true })).toBeDisabled();
  await expect(header.getByRole("button", { name: "다시 판정", exact: true })).toBeEnabled();
  await expect(header.getByRole("button", { name: "판정 보기" })).toHaveCount(0);
  // 판정이 없으면 좌측은 기존 사업 정보를 그대로 둔다(판정 요약은 판정이 있을 때만).
  await expect(page.locator(".rec-attribute")).toHaveCount(8);
  await expect(page.getByTestId("verdict-summary")).toHaveCount(0);
  // 오류 제보·실행 정보는 대상이 없어 비활성이고 이유를 말한다.
  await header.getByRole("button", { name: "사업기회 더보기" }).click();
  await expect(page.getByRole("menuitem", { name: /판정 오류 제보/ })).toBeDisabled();
  await expect(page.getByRole("menuitem", { name: /실행 정보/ })).toBeDisabled();
  await expect(page.getByRole("menu")).toContainText("제보할 판정이 없습니다");
  expect(trace.verdictGets.length).toBeGreaterThan(0);
  expect(trace.unhandled).toEqual([]);
});

test("완료 판정은 좌측에 판정 이름·사유·체크리스트 5행·다음 행동·고지를 그린다", async ({ page }) => {
  await openVerdict(page, completedView());
  const summary = page.getByTestId("verdict-summary");
  await expect(summary.getByRole("heading", { name: "조건부 진행" })).toBeVisible();
  await expect(summary.getByRole("heading", { name: "조건부 진행" })).toHaveClass(/is-warning/);
  const weight = await summary.getByRole("heading", { name: "조건부 진행" }).evaluate((node) => getComputedStyle(node).fontWeight);
  expect(Number(weight)).toBe(700);

  // 사유는 두 문장으로 자르지 않고 그대로다. 길면 접고 "더 보기"로 편다.
  const reason = page.locator("#vd-verdict-reason");
  await expect(reason).toHaveText(LONG_REASON);
  await expect(reason).toHaveAttribute("data-clamped", "true");
  const more = summary.getByRole("button", { name: "더 보기" });
  await expect(more).toHaveAttribute("aria-expanded", "false");
  await more.click();
  await expect(reason).not.toHaveAttribute("data-clamped", "true");
  await expect(summary.getByRole("button", { name: "접기" })).toHaveAttribute("aria-expanded", "true");

  // 체크리스트: 키 → 라벨, met → 충족 · gap → 부족 · unknown → 확인 필요(부족이 아니다).
  const checklist = page.getByTestId("verdict-checklist").locator(".vd-checklist-row");
  await expect(checklist).toHaveText(["자격·실적부족", "상주·인력확인 필요", "금액·기간충족", "기술충족", "운영·SLA확인 필요"]);
  await expect(checklist.nth(0).locator(".vd-pill")).toHaveClass(/is-error/);
  await expect(checklist.nth(1).locator(".vd-pill")).toHaveClass(/is-warning/);
  await expect(checklist.nth(1).locator(".vd-pill")).not.toHaveClass(/is-error/);
  await expect(checklist.nth(2).locator(".vd-pill")).toHaveClass(/is-success/);

  // 다음 행동: 담당 머리글자(아바타)·owner null은 "미지정".
  const actions = page.getByTestId("verdict-next-actions").locator(".rec-next-item");
  await expect(actions).toHaveCount(2);
  await expect(actions.nth(0).locator(".rec-avatar")).toHaveText("박");
  await expect(actions.nth(0).locator(".rec-avatar")).toHaveAttribute("title", "담당 박팀장");
  await expect(actions.nth(0)).toContainText("직접생산 확인증명서 품목을 발급기관에 확인한다");
  await expect(actions.nth(1).locator(".rec-avatar")).toHaveCount(0);
  await expect(actions.nth(1).locator('[data-owner="unassigned"]')).toHaveText("미지정");

  await expect(page.getByText("판정은 참고 의견입니다. 추적 여부와 참여 결정은 담당자가 정합니다.", { exact: true })).toBeVisible();
  // 판정은 추적 결정·Go/No-Go가 아니다: 그런 버튼이 없다.
  await expect(page.getByRole("button", { name: /Go\/No-Go|추적 시작|입찰/ })).toHaveCount(0);
});

test("원문에서 찾지 못한 영역이 있는 완료 판정은 그 영역을 한 줄로 알리고 없으면 알리지 않는다", async ({ page }) => {
  // 결정 B23: card-sections-v2는 영역이 빠져도 종합까지 가고 missing_sections를 기록한다.
  const trace = await openVerdict(page, completedView({ missing_sections: ["contract"] }));
  await waitTable(page);
  const note = page.getByTestId("missing-sections-note");
  await expect(note).toHaveText("원문에서 찾지 못한 영역: 계약조건 — 이 영역의 요구사항은 확인 필요입니다.");
  await expect(page.getByTestId("review-banner")).toHaveCount(0);

  trace.setVerdict(7101, completedView());
  await page.goto("/opportunities/7101/verdict");
  await waitTable(page);
  await expect(page.getByTestId("missing-sections-note")).toHaveCount(0);
});

test("헤더 판정 pill은 판정 이름이고 판정 보기는 결과가 있을 때만 열려 판정 탭으로 간다", async ({ page }) => {
  const trace = await openVerdict(page, completedView(), "/opportunities/7101/activity");
  await expect.poll(() => headerPills(page)).toEqual(["입찰공고", "D-4", "조건부 진행", "계속 추적"]);
  await expect(page.locator('.rec-pill[data-pill="verdict"]')).toHaveClass(/is-warning/);
  const open = page.getByRole("button", { name: "판정 보기", exact: true });
  await expect(open).toBeEnabled();
  await open.click();
  await expect(page).toHaveURL(/\/opportunities\/7101\/verdict$/);
  await expect(page.getByTestId("verdict-summary")).toBeVisible();

  // 같은 규칙의 다른 판정 이름: 진행 가능 success · 진행 어려움 error · 판단 불가 muted.
  for (const [verdict, tone] of [["진행 가능", "is-success"], ["진행 어려움", "is-error"], ["판단 불가", "is-muted"]] as const) {
    const view = completedView();
    view.result!.verdict = verdict;
    trace.setVerdict(7101, view);
    await page.goto("/opportunities/7101/verdict");
    await expect(page.getByTestId("verdict-summary").getByRole("heading", { name: verdict })).toHaveClass(new RegExp(tone));
    if (tone !== "is-muted") await expect(page.locator('.rec-pill[data-pill="verdict"]')).toHaveClass(new RegExp(tone));
    await expect(page.locator('.rec-pill[data-pill="verdict"]')).toHaveText(verdict);
  }
});

test("발주계획만 있는 레코드는 판정 pill이 연차 추적으로 남는다", async ({ page }) => {
  const trace = await openVerdict(page, null, "/opportunities/7102/verdict");
  await expect.poll(() => headerPills(page)).toEqual(["발주계획", "연차 추적", "미선택"]);
  const tabpanel = page.getByRole("tabpanel");
  await expect(tabpanel.getByText("아직 판정이 없습니다", { exact: true })).toBeVisible();
  // 사전규격이 없으면 서버는 `notice_id=null`을 준다(B14). 판정 대상이 없으므로 요청 버튼을 두지 않고
  // 이유를 말한다 — 0으로 접어 요청하지 않는다.
  await expect(tabpanel.getByText(/연결된 사전규격이 없어 판정 대상이 아닙니다/)).toBeVisible();
  await expect(tabpanel.getByRole("button", { name: "다시 판정", exact: true })).toHaveCount(0);
  const header = page.locator('[data-testid="record-header"]');
  await expect(header.getByRole("button", { name: "다시 판정", exact: true })).toBeDisabled();
  await expect(page.locator('.rec-action-hint[title="연결된 사전규격이 없습니다"]')).toHaveCount(1);
  expect(trace.verdictRequests).toEqual([]);
  expect(trace.unhandled).toEqual([]);
});

test("요구사항 표는 부족 → 확인 필요 → 충족으로 정렬하고 기본은 부족·확인 필요만 보인다", async ({ page }) => {
  await openVerdict(page, completedView());
  await waitTable(page);
  await expect(page.getByRole("heading", { name: "요구사항 7" })).toBeVisible();
  await expect(page.getByTestId("verdict-counts")).toHaveText("부족 2 · 확인 필요 3 · 충족 2");
  await expect(page.getByRole("combobox", { name: "상태", exact: true })).toContainText("부족·확인 필요만");
  await expect.poll(() => rowTitles(page)).toEqual(DEFAULT_ROWS);

  // 4열 머리.
  await expect(page.getByRole("table", { name: "요구사항 대조표" }).locator("thead th")).toHaveText(["요구사항", "대조", "회사 근거", "원문"]);

  // 보조 줄 "<유형> · 필수/조건부/미표기".
  await expect(rowOf(page, R[3]).locator(".vd-row-main .vd-row-sub")).toHaveText("자격 · 필수");
  await expect(rowOf(page, R[5]).locator(".vd-row-main .vd-row-sub")).toHaveText("계약 · 조건부");
  await expect(rowOf(page, R[4]).locator(".vd-row-main .vd-row-sub")).toHaveText("운영 · 미표기");

  // 대조 pill: 글자가 상태 이름이고 확인 필요는 부족(error)이 아니다.
  await expect(rowOf(page, R[3]).locator(".vd-pill")).toHaveText("부족");
  await expect(rowOf(page, R[3]).locator(".vd-pill")).toHaveClass(/is-error/);
  await expect(rowOf(page, R[2]).locator(".vd-pill")).toHaveText("확인 필요");
  await expect(rowOf(page, R[2]).locator(".vd-pill")).toHaveClass(/is-warning/);
  await expect(rowOf(page, R[2]).locator(".vd-pill")).not.toHaveClass(/is-error/);

  // 회사 근거: 첫 역할 의견의 이유 + 보조 fact label. 역할 의견이 없으면 그 사실을 적는다.
  await expect(rowOf(page, R[3]).locator(".vd-row-reason")).toHaveText("직접생산 확인 품목에 해당 소프트웨어가 없음");
  await expect(rowOf(page, R[3]).locator(".vd-row-company .vd-row-sub")).toHaveText("직접생산 확인");
  await expect(rowOf(page, R[2]).locator(".vd-row-company .vd-row-sub")).toHaveText("상주 인원 · 상주 지역");
  await expect(rowOf(page, R[7]).locator(".vd-row-company")).toHaveText("회사 근거 없음");

  // 원문: n쪽 링크 · 상속 쪽은 "(추정)" · 일부 매핑 · 쪽 미확인은 링크 없이 글자.
  await expect(rowOf(page, R[3]).locator(".vd-row-source")).toHaveText("3~4쪽");
  await expect(rowOf(page, R[3]).getByRole("button", { name: "3~4쪽" })).toBeVisible();
  await expect(rowOf(page, R[2]).locator(".vd-row-source")).toHaveText("12쪽(추정)");
  await expect(rowOf(page, R[2]).getByRole("button", { name: "12쪽" })).toBeVisible();
  await expect(rowOf(page, R[5]).locator(".vd-row-source")).toHaveText("7쪽(일부 매핑)");
  await expect(rowOf(page, R[4]).locator("td").last()).toHaveText("쪽 미확인");
  await expect(rowOf(page, R[4]).locator("td").last().getByRole("button")).toHaveCount(0);
  await expect(rowOf(page, R[4]).locator("td").last().getByRole("link")).toHaveCount(0);

  // 상태 select.
  await chooseFilter(page, "전체");
  await expect.poll(() => rowTitles(page)).toEqual(SORTED);
  await chooseFilter(page, "충족");
  await expect.poll(() => rowTitles(page)).toEqual([R[1], R[6]]);
  await chooseFilter(page, "부족");
  await expect.poll(() => rowTitles(page)).toEqual([R[3], R[5]]);
  await chooseFilter(page, "확인 필요");
  await expect.poll(() => rowTitles(page)).toEqual([R[2], R[4], R[7]]);

  // 필수만 토글: mandatory=true(R1·R2·R3)만. 미표기(null)와 조건부는 빠진다.
  await chooseFilter(page, "전체");
  const mandatory = page.getByRole("button", { name: "필수만", exact: true });
  await expect(mandatory).toHaveAttribute("aria-pressed", "false");
  await mandatory.click();
  await expect(mandatory).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => rowTitles(page)).toEqual([R[3], R[2], R[1]]);
  // 조건이 맞는 행이 없으면 빈 표 대신 이유를 말한다.
  await chooseFilter(page, "충족");
  await expect.poll(() => rowTitles(page)).toEqual([R[1]]);
  await mandatory.click();
  await chooseFilter(page, "부족");
  await mandatory.click();
  await chooseFilter(page, "충족");
  await expect.poll(() => rowTitles(page)).toEqual([R[1]]);
});

test("조건에 맞는 행이 없으면 표 대신 안내를 보이고 요구사항 수는 그대로다", async ({ page }) => {
  const allMet = sampleMatrix().filter((entry) => entry.fit_status === "met");
  await openVerdict(page, completedView({}, allMet));
  await expect(page.getByRole("heading", { name: "요구사항 2" })).toBeVisible();
  await expect(page.getByTestId("verdict-counts")).toHaveText("부족 0 · 확인 필요 0 · 충족 2");
  await expect(page.getByRole("status").filter({ hasText: "이 조건에 해당하는 요구사항이 없습니다" })).toBeVisible();
  await expect(rows(page)).toHaveCount(0);
  await chooseFilter(page, "전체");
  await expect(rows(page)).toHaveCount(2);
});

test("50행씩 보이고 'n건 더 보기'로 이어 붙인다", async ({ page }) => {
  await openVerdict(page, completedView({}, largeMatrix()));
  await waitTable(page);
  await expect(page.getByRole("heading", { name: "요구사항 60" })).toBeVisible();
  await expect(page.getByTestId("verdict-counts")).toHaveText("부족 20 · 확인 필요 20 · 충족 20");
  // 기본(부족·확인 필요만)은 40행이라 쪽이 나뉘지 않는다.
  await expect(rows(page)).toHaveCount(40);
  await expect(page.getByRole("button", { name: /건 더 보기/ })).toHaveCount(0);
  await chooseFilter(page, "전체");
  await expect(rows(page)).toHaveCount(50);
  const more = page.getByRole("button", { name: "10건 더 보기", exact: true });
  await expect(more).toBeVisible();
  await more.click();
  await expect(rows(page)).toHaveCount(60);
  await expect(page.getByRole("button", { name: /건 더 보기/ })).toHaveCount(0);
  // 조건을 바꾸면 처음 쪽으로 돌아간다.
  await chooseFilter(page, "충족");
  await expect(rows(page)).toHaveCount(20);
});

test("행을 고르면 원문 패널이 열려 인용 2개를 mark로 보이고 쪽 전체 보기는 쪽 블록을 읽는다", async ({ page }) => {
  const trace = await openVerdict(page, completedView());
  await waitTable(page);
  await expect(panel(page)).toHaveCount(0);

  await rowOf(page, R[3]).locator(".vd-row-main").click();
  await expect(rowOf(page, R[3])).toHaveAttribute("aria-selected", "true");
  await expect(panel(page)).toBeVisible();
  await expect(panel(page).getByRole("heading", { name: /^원문 · 3~4쪽/ })).toBeVisible();
  // 인용은 2개까지다(fixture는 3개를 준다).
  await expect(panel(page).locator("mark")).toHaveText(["직접생산 확인증명서 보유 업체", "공고일 현재 유효한 증명서"]);
  await expect(panel(page)).not.toContainText("세 번째 인용은 패널에 나오지 않는다");

  await panel(page).getByRole("button", { name: "쪽 전체 보기" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "원문 3쪽 전체" })).toBeVisible();
  await expect(dialog.getByRole("list", { name: "쪽 블록" }).getByRole("listitem")).toHaveCount(3);
  await expect(dialog).toContainText("3쪽 첫 문단 원문");
  expect(trace.pageGets).toEqual([{ structureId: VERDICT_STRUCTURE_ID, page: 3 }]);
  // 이 행의 인용이 가리키는 블록(b4·b5)은 이 쪽에 없으므로 표시가 없다.
  await expect(dialog.locator("mark")).toHaveCount(0);
  await dialog.getByRole("button", { name: "닫기", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // 상속 쪽: 제목 뒤 "(추정)", 인용이 가리키는 블록은 쪽 전체 보기에서 mark다.
  await rowOf(page, R[2]).locator(".vd-row-main").click();
  await expect(panel(page).getByRole("heading", { name: /^원문 · 12쪽/ })).toContainText("(추정)");
  await panel(page).getByRole("button", { name: "쪽 전체 보기" }).click();
  await expect(page.getByRole("dialog").getByRole("heading", { name: "원문 12쪽 전체" })).toBeVisible();
  await expect(page.getByRole("dialog").locator("mark")).toHaveText("정보보호 전문 인력 3명 이상 상주");
  expect(trace.pageGets[1]).toEqual({ structureId: VERDICT_STRUCTURE_ID, page: 12 });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // 쪽 미확인: 링크 없이 "쪽 미확인", 쪽 전체 보기는 막혀 있고 이유를 말한다.
  await rowOf(page, R[4]).locator(".vd-row-main").click();
  await expect(panel(page).getByRole("heading", { name: "원문 · 쪽 미확인" })).toBeVisible();
  await expect(panel(page).getByRole("button", { name: "쪽 전체 보기" })).toBeDisabled();
  await expect(panel(page)).toContainText("쪽을 알 수 없어 열 수 없습니다");

  // 인용이 없는 행.
  await rowOf(page, R[7]).locator(".vd-row-main").click();
  await expect(panel(page)).toContainText("서버가 연결한 원문 인용이 없습니다");
  await expect(panel(page).locator("mark")).toHaveCount(0);

  // 닫기 · 필터를 바꾸면 패널이 닫힌다.
  await panel(page).getByRole("button", { name: "원문 패널 닫기" }).click();
  await expect(panel(page)).toHaveCount(0);
  await rowOf(page, R[3]).locator(".vd-row-main").click();
  await expect(panel(page)).toBeVisible();
  await chooseFilter(page, "충족");
  await expect(panel(page)).toHaveCount(0);
  expect(trace.unhandled).toEqual([]);
});

test("원문 칸의 쪽 링크도 그 행을 골라 패널을 열고 행은 키보드로 고른다", async ({ page }) => {
  await openVerdict(page, completedView());
  await waitTable(page);
  await rowOf(page, R[2]).getByRole("button", { name: "12쪽" }).click();
  await expect(panel(page).getByRole("heading", { name: /^원문 · 12쪽/ })).toBeVisible();
  await rowOf(page, R[5]).locator(".vd-row-main").focus();
  await page.keyboard.press("Enter");
  await expect(rowOf(page, R[5])).toHaveAttribute("aria-selected", "true");
  await expect(panel(page).getByRole("heading", { name: /^원문 · 7쪽/ })).toBeVisible();
});

test("서버가 문서 구조 id를 주지 않으면 쪽 전체 보기를 열지 않고 이유를 말한다", async ({ page }) => {
  const view = completedView();
  view.source_binding!.document_versions = [{ document_version_id: view.source_binding!.document_versions[0].document_version_id, source_sha256: SOURCE_SHA }];
  const trace = await openVerdict(page, view);
  await waitTable(page);
  await rowOf(page, R[3]).locator(".vd-row-main").click();
  await expect(panel(page).getByRole("button", { name: "쪽 전체 보기" })).toBeDisabled();
  await expect(panel(page)).toContainText("문서 구조 정보가 없어 열 수 없습니다");
  expect(trace.pageGets).toEqual([]);
});

test("원문 패널 행동은 담당자 이름을 받아 오류 제보를 보내고 실패하면 같은 요청 식별자로 다시 보낸다", async ({ page }) => {
  const trace = await openVerdict(page, completedView());
  await waitTable(page);
  await rowOf(page, R[3]).locator(".vd-row-main").click();
  await panel(page).getByRole("button", { name: "요구사항 아님" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "판정 오류 제보" })).toBeVisible();
  await expect(dialog).toContainText(R[3]);
  // 요구사항 식별자(원문 hash를 포함한다)는 화면에 없다.
  await expect(dialog).not.toContainText(SOURCE_SHA);
  await expect(dialog).not.toContainText("card:");
  await expect(dialog.getByRole("combobox", { name: "제보 유형" })).toContainText("요구사항이 아닙니다");
  // 이름이 없으면 보내지 않고 이유를 말한다.
  const submit = dialog.getByRole("button", { name: "제보 보내기" });
  await expect(submit).toBeDisabled();
  await expect(dialog).toContainText("제보하려면 담당자 이름을 입력하십시오");
  await actorInput(dialog).fill("김담당");
  await dialog.getByLabel("메모 (선택)").fill("이 항목은 평가 배점 안내일 뿐 요구사항이 아닙니다");

  trace.failVerdictFeedbacks({ status: 503, code: "service_unavailable" });
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("입력한 내용은 그대로 남아 있습니다");
  await expect(dialog.getByLabel("메모 (선택)")).toHaveValue("이 항목은 평가 배점 안내일 뿐 요구사항이 아닙니다");

  trace.failVerdictFeedbacks(null);
  await submit.click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(toast(page)).toContainText("판정 오류 제보를 남겼습니다");
  expect(trace.verdictFeedbacks).toHaveLength(2);
  const [first, second] = trace.verdictFeedbacks;
  expect(second.body.request_id).toBe(first.body.request_id);
  expect(second.body).toEqual({
    attempt_id: VERDICT_ATTEMPT_ID,
    kind: "not_requirement",
    unit_id: `card:${SOURCE_SHA}:3:REQ-003`,
    note: "이 항목은 평가 배점 안내일 뿐 요구사항이 아닙니다",
    request_id: expect.stringMatching(UUID),
  });
  expect(second.companyId).toBe(VERDICT_COMPANY_ID);
  expect(second.noticeId).toBe(VERDICT_NOTICE_ID);
  expect(decodeURIComponent(second.headers["x-bidops-actor-name"].replace("UTF-8''", ""))).toBe("김담당");
  expect(second.headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");

  // 원문과 다름 → source_mismatch, 메모 없이도 보낸다. 새 대화상자는 새 요청 식별자다.
  await panel(page).getByRole("button", { name: "원문과 다름" }).click();
  const again = page.getByRole("dialog");
  await expect(again.getByRole("combobox", { name: "제보 유형" })).toContainText("원문과 다릅니다");
  await actorInput(again).fill("김담당");
  await again.getByRole("button", { name: "제보 보내기" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(trace.verdictFeedbacks).toHaveLength(3);
  expect(trace.verdictFeedbacks[2].body).toEqual({
    attempt_id: VERDICT_ATTEMPT_ID,
    kind: "source_mismatch",
    unit_id: `card:${SOURCE_SHA}:3:REQ-003`,
    request_id: expect.stringMatching(UUID),
  });
  expect(trace.verdictFeedbacks[2].body.request_id).not.toBe(first.body.request_id);
  // 제보는 판정·추적을 바꾸지 않는다: 헤더 pill이 그대로다.
  expect(await headerPills(page)).toEqual(["입찰공고", "D-4", "조건부 진행", "계속 추적"]);
});

test("⋯ 판정 오류 제보는 판정 전체(wrong_verdict)를 요구사항 식별자 없이 보낸다", async ({ page }) => {
  const trace = await openVerdict(page, completedView());
  await page.getByRole("button", { name: "사업기회 더보기" }).click();
  await expect(page.getByRole("menu").getByRole("menuitem")).toHaveText([/추적 상태 변경/, /추적 되돌리기/, /신호 확인/, /후보 연결/, /판정 오류 제보/, /실행 정보/]);
  await page.getByRole("menuitem", { name: /판정 오류 제보/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("이 판정 전체가 틀렸다고 제보합니다");
  await expect(dialog.getByRole("combobox")).toHaveCount(0);
  await actorInput(dialog).fill("김담당");
  await dialog.getByRole("button", { name: "제보 보내기" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(trace.verdictFeedbacks).toHaveLength(1);
  expect(trace.verdictFeedbacks[0].body).toEqual({ attempt_id: VERDICT_ATTEMPT_ID, kind: "wrong_verdict", request_id: expect.stringMatching(UUID) });
});

test("다시 판정은 담당자 이름과 함께 UUID 요청 식별자로 접수하고 분석 중으로 바뀐다", async ({ page }) => {
  const trace = await openVerdict(page, completedView());
  const header = page.locator('[data-testid="record-header"]');
  await header.getByRole("button", { name: "다시 판정", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "다시 판정" })).toBeVisible();
  await expect(dialog).toContainText("이전 판정은 지워지지 않고 남습니다");
  const submit = dialog.getByRole("button", { name: "판정 요청", exact: true });
  await expect(submit).toBeDisabled();
  await expect(dialog).toContainText("판정을 요청하려면 담당자 이름을 입력하십시오");
  await actorInput(dialog).fill("김담당");

  // 승인·한도 조건으로 막히면 그 안전한 코드의 문구를 말하고 입력을 남긴다.
  trace.failVerdictRequests({ status: 409, code: "policy_not_approved" });
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("분석 정책 전송 승인이 없습니다");
  await expect(dialog.getByRole("alert")).toContainText("policy_not_approved");
  await expect(actorInput(dialog)).toHaveValue("김담당");
  trace.failVerdictRequests({ status: 409, code: "daily_cap_reached" });
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("오늘 판정 한도에 도달했습니다");
  trace.failVerdictRequests({ status: 409, code: "bundle_not_ready" });
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("문서 준비가 끝나지 않았습니다");
  trace.failVerdictRequests({ status: 403, code: "effective_grade_ineligible" });
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("SW사업 공고가 아니라 판정 대상이 아닙니다");
  trace.failVerdictRequests({ status: 409, code: "active_attempt_exists" });
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("이미 분석 중인 판정이 있습니다");
  // 기존 서비스 gate 코드도 판정 문맥의 문구로 말한다(B14).
  trace.failVerdictRequests({ status: 503, code: "reference_mode_required" });
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("참조 실행 모드가 꺼져 있습니다");
  trace.failVerdictRequests({ status: 409, code: "company_input_invalid" });
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("판정 입력을 만들 수 없습니다");
  trace.failVerdictRequests({ status: 404, code: "not_found" });
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("판정할 사전규격을 찾을 수 없습니다");
  // 실패한 시도는 새 판정을 시작하지 않았다.
  await expect(header.getByRole("button", { name: "다시 판정", exact: true })).toBeEnabled();

  trace.failVerdictRequests(null);
  await submit.click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(toast(page)).toContainText("판정을 요청했습니다");
  expect(trace.verdictRequests).toHaveLength(9);
  // 같은 대화상자의 재시도는 같은 요청 식별자다(응답을 잃은 요청이 두 번 접수되지 않게).
  const ids = new Set(trace.verdictRequests.map((entry) => entry.body.request_id));
  expect(ids.size).toBe(1);
  expect(trace.verdictRequests[5].body).toEqual({ request_id: expect.stringMatching(UUID) });
  expect(decodeURIComponent(trace.verdictRequests[5].headers["x-bidops-actor-name"].replace("UTF-8''", ""))).toBe("김담당");

  // 접수되면 서버 상태(분석 중)를 다시 읽어 헤더 pill과 탭이 바뀐다. 진행 중에는 다시 판정이 막힌다.
  await expect.poll(() => headerPills(page)).toEqual(["입찰공고", "D-4", "분석 중", "계속 추적"]);
  await expect(page.getByTestId("running-banner")).toContainText("분석 중");
  await expect(header.getByRole("button", { name: "다시 판정", exact: true })).toBeDisabled();
  await expect(page.locator('.rec-action-hint[title="분석이 진행 중입니다"]')).toHaveCount(1);
  await expect(header.getByRole("button", { name: "판정 보기" })).toHaveCount(0);
  expect(trace.unhandled).toEqual([]);
});

test("판정이 없는 탭의 다시 판정 버튼도 같은 요청 대화상자를 연다", async ({ page }) => {
  const trace = await openVerdict(page, null);
  await page.getByRole("tabpanel").getByRole("button", { name: "다시 판정", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await actorInput(dialog).fill("김담당");
  await dialog.getByRole("button", { name: "판정 요청", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(trace.verdictRequests).toHaveLength(1);
  await expect(page.getByTestId("running-banner")).toBeVisible();
  // 새 대화상자는 새 요청 식별자다.
  const finished = completedView();
  trace.setVerdict(7101, finished);
  await page.reload();
  await page.locator('[data-testid="record-header"]').getByRole("button", { name: "다시 판정", exact: true }).click();
  await actorInput(page.getByRole("dialog")).fill("김담당");
  await page.getByRole("dialog").getByRole("button", { name: "판정 요청", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(trace.verdictRequests).toHaveLength(2);
  expect(trace.verdictRequests[1].body.request_id).not.toBe(trace.verdictRequests[0].body.request_id);
});

test("분석 중이면 안내와 검증이 끝난 부분표만 보이고 최종 판정은 없다", async ({ page }) => {
  const trace = await openVerdict(page, runningView("running"));
  await expect(page.getByTestId("running-banner")).toContainText("분석 중");
  await expect(page.getByTestId("running-banner")).toContainText("검증이 끝난 요구사항부터");
  await expect(page.getByTestId("verdict-summary")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "요구사항 2" })).toBeVisible();
  await expect(page.getByText("검증이 끝난 요구사항만 보입니다. 최종 판정은 아직 없습니다.")).toBeVisible();
  // 부분표도 같은 규칙으로 부족 → 확인 필요 순이다.
  await expect.poll(() => rowTitles(page)).toEqual([R[3], R[2]]);
  expect(await headerPills(page)).toEqual(["입찰공고", "D-4", "분석 중", "계속 추적"]);
  await expect(page.getByRole("button", { name: "판정 보기" })).toHaveCount(0);

  // pending은 아직 검증된 행이 없어 표 대신 안내다.
  trace.setVerdict(7101, runningView("pending"));
  await page.goto("/opportunities/7101/verdict");
  await expect(page.getByTestId("running-banner")).toContainText("분석 중");
  await expect(page.getByText("대조한 요구사항이 아직 없습니다.")).toBeVisible();
  await expect(rows(page)).toHaveCount(0);
});

test("분석 중 상태가 끝나면 주기적으로 다시 읽어 완료 판정으로 바뀐다", async ({ page }) => {
  const trace = await openVerdict(page, runningView("running"));
  await expect(page.getByTestId("running-banner")).toBeVisible();
  const reads = trace.verdictGets.length;
  trace.setVerdict(7101, completedView());
  await expect(page.getByTestId("verdict-summary")).toBeVisible({ timeout: 15_000 });
  expect(trace.verdictGets.length).toBeGreaterThan(reads);
  await expect(page.getByTestId("running-banner")).toHaveCount(0);
  expect(await headerPills(page)).toEqual(["입찰공고", "D-4", "조건부 진행", "계속 추적"]);
  // 완료 뒤에는 더 읽지 않는다.
  const after = trace.verdictGets.length;
  await page.waitForTimeout(6_000);
  expect(trace.verdictGets.length).toBe(after);
});

test("검증 실패·시간 초과는 사람 검토 필요로 부분표를 보이고 안전한 코드만 말하며 자동 보정하지 않는다", async ({ page }) => {
  const trace = await openVerdict(page, failedView("needs_human_review", "card_extract_invalid"));
  const banner = page.getByTestId("review-banner");
  await expect(banner).toContainText("사람 검토가 필요합니다");
  await expect(banner).toContainText("요구사항 추출 결과가 원문 검증을 통과하지 못했습니다");
  await expect(banner).toContainText("card_extract_invalid");
  await expect(banner).toContainText("찾지 못한 영역: 입찰참가자격, 평가기준");
  await expect(banner).toContainText("원문에 없다는 뜻은 아닙니다");
  await expect(banner).toContainText("자동으로 고치지 않습니다");
  // 부분표(검증이 끝난 행만)·최종 판정 없음·다시 판정.
  await expect(page.getByRole("heading", { name: "요구사항 1" })).toBeVisible();
  await expect.poll(() => rowTitles(page)).toEqual([R[3]]);
  await expect(page.getByTestId("verdict-summary")).toHaveCount(0);
  expect(await headerPills(page)).toEqual(["입찰공고", "D-4", "사람 검토 필요", "계속 추적"]);
  await expect(page.locator('.rec-pill[data-pill="verdict"]')).toHaveClass(/is-warning/);
  await expect(page.getByRole("button", { name: "판정 보기" })).toHaveCount(0);

  // 시간 초과 · 모르는 코드는 숨기지 않고 코드 그대로.
  trace.setVerdict(7101, failedView("failed", "card_review_timeout"));
  await page.goto("/opportunities/7101/verdict");
  await expect(page.getByTestId("review-banner")).toContainText("정해진 시간 안에 분석이 끝나지 않았습니다");
  trace.setVerdict(7101, failedView("failed", "card_future_code"));
  await page.goto("/opportunities/7101/verdict");
  await expect(page.getByTestId("review-banner")).toContainText("card_future_code");
  await expect(page.getByTestId("review-banner")).toContainText("분석 중 안전 오류가 기록됐습니다");

  // 실패 배너의 다시 판정은 같은 요청 대화상자다.
  await page.getByTestId("review-banner").getByRole("button", { name: "다시 판정" }).click();
  await expect(page.getByRole("dialog").getByRole("heading", { name: "다시 판정" })).toBeVisible();
});

test("legacy는 기존 보고서 링크를 주고 다시 판정을 둔다", async ({ page }) => {
  await openVerdict(page, legacyView());
  const tabpanel = page.getByRole("tabpanel");
  await expect(tabpanel.getByText("기존 보고서가 있습니다", { exact: true })).toBeVisible();
  await expect(tabpanel.getByRole("link", { name: "기존 보고서 보기" })).toHaveAttribute("href", `/pre-specs/${VERDICT_NOTICE_ID}`);
  await expect(tabpanel.getByRole("button", { name: "다시 판정" })).toBeVisible();
  await expect(page.getByTestId("verdict-summary")).toHaveCount(0);
  expect(await headerPills(page)).toEqual(["입찰공고", "D-4", "분석 대기", "계속 추적"]);
});

test("과거 기준 판정은 과거 기준 pill과 한글 사유를 보이고 모르는 사유는 코드 그대로 둔다", async ({ page }) => {
  const view = completedView({ is_current: false, stale_reasons: ["documents_changed", "superseded"] });
  const trace = await openVerdict(page, view);
  const banner = page.getByTestId("stale-banner");
  await expect(banner.locator(".vd-pill")).toHaveText("과거 기준");
  await expect(banner).toContainText("공고 문서가 그 뒤에 바뀌었습니다");
  await expect(banner).toContainText("더 새로운 판정이 있습니다");
  // 과거 기준이어도 결과는 그대로 보인다(없애지 않는다).
  await expect(page.getByTestId("verdict-summary")).toBeVisible();
  await waitTable(page);

  trace.setVerdict(7101, completedView({ is_current: false, stale_reasons: ["future_reason" as never] }));
  await page.goto("/opportunities/7101/verdict");
  await expect(page.getByTestId("stale-banner")).toContainText("future_reason");

  // 현재 기준이면 배너가 없다.
  trace.setVerdict(7101, completedView());
  await page.goto("/opportunities/7101/verdict");
  await expect(page.getByTestId("stale-banner")).toHaveCount(0);
});

test("판정을 읽지 못하면 오류와 다시 시도를 보이고 헤더는 기존 값으로 남는다", async ({ page }) => {
  await page.clock.setFixedTime(new Date(RECORD_NOW));
  await mockApi(page);
  const trace = await mockOpportunityRecord(page);
  trace.failVerdictGets({ status: 500, code: "processing_failed" });
  await page.goto("/opportunities/7101/verdict");
  const tabpanel = page.getByRole("tabpanel");
  await expect(tabpanel.getByRole("alert")).toContainText("판정을 불러오지 못했습니다");
  await expect(tabpanel.getByRole("alert")).toContainText("processing_failed");
  expect(await headerPills(page)).toEqual(["입찰공고", "D-4", "분석 대기", "계속 추적"]);
  await expect(page.getByRole("button", { name: "판정 보기" })).toHaveCount(0);

  trace.failVerdictGets(null);
  trace.setVerdict(7101, completedView());
  await tabpanel.getByRole("button", { name: "다시 시도" }).click();
  await expect(page.getByTestId("verdict-summary")).toBeVisible();
});

test("실무 화면 DOM에는 정책 id·모델명·해시·참조 실행 표식·요구사항 식별자가 없고 실행 정보 대화상자에서만 보인다", async ({ page }) => {
  await openVerdict(page, completedView());
  await waitTable(page);
  await rowOf(page, R[3]).locator(".vd-row-main").click();
  await expect(panel(page)).toBeVisible();

  const forbidden = /unmeasured_reference|mock_reference|policy_id|policy_sha|analysis-policy|gpt-\d|luna|qwen|run_id|card:[0-9a-f]{8}|[0-9a-f]{64}|인터뷰|\d+(\.\d+)?초/i;
  const assertClean = async (context: string) => {
    const html = await page.locator(".page-canvas").evaluate((node) => node.innerHTML);
    for (const value of FORBIDDEN_VALUES) expect(html, `${context}: ${value}`).not.toContain(value);
    expect(html, context).not.toMatch(forbidden);
    const top = await page.locator("header.topbar").innerText();
    for (const value of FORBIDDEN_VALUES) expect(top, `${context} 상단바: ${value}`).not.toContain(value);
  };
  await assertClean("원문 패널 열림");

  // 모든 탭에서도 같다.
  for (const tab of ["activity", "proposal", "documents", "source", "similar", "verdict"]) {
    await page.goto(`/opportunities/7101/${tab}`);
    await expect(page.locator(".rec-body")).toBeVisible();
    await expect(page.locator('[data-testid="record-title"]')).toBeVisible();
    await assertClean(`${tab} 탭`);
  }

  // ⋯ → 실행 정보에서만 보인다.
  await page.getByRole("button", { name: "사업기회 더보기" }).click();
  await page.getByRole("menuitem", { name: /실행 정보/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "실행 정보" })).toBeVisible();
  await expect(dialog).toContainText(POLICY_ID);
  await expect(dialog).toContainText(POLICY_SHA);
  await expect(dialog).toContainText(MODEL_NAME);
  await expect(dialog).toContainText("high");
  await expect(dialog).toContainText("0.162.1");
  await expect(dialog).toContainText("10월 16일 (금) 09:12");
  await expect(dialog).toContainText("10월 16일 (금) 09:51");
  // 품질 표식은 문구로 말하고 운영 완료로 보이지 않는다(AGENTS 네 상태).
  await expect(dialog).toContainText("참조 실행 · 품질 미측정");
  await expect(dialog).toContainText("운영 완료로 읽지 마십시오");
  await expect(dialog).toContainText("현재 기준");
  await dialog.getByRole("button", { name: "닫기", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await assertClean("실행 정보 닫은 뒤");
});

test("품질 표식이 없으면 표식 없음으로 말하고 미측정으로 바꾸지 않는다", async ({ page }) => {
  await openVerdict(page, completedView({ quality_status: null }));
  await page.getByRole("button", { name: "사업기회 더보기" }).click();
  await page.getByRole("menuitem", { name: /실행 정보/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("표식 없음");
  await expect(dialog).not.toContainText("품질 미측정");
  await expect(dialog).toContainText("없음을 미측정으로 바꾸지 않습니다");
});

test("브리핑 v2 판정 칸은 서버가 준 판정 이름 글자 그대로이고 의미 색을 쓴다", async ({ page }) => {
  await page.clock.setFixedTime(new Date(BRIEFING_NOW));
  await mockApi(page);
  const view = briefingFixture();
  view.schema_version = "bidops.briefing.v2";
  const verdicts: Record<number, BriefingVerdictDisplay> = {
    1: "진행 가능", 2: "진행 어려움", 3: "판단 불가", 4: "조건부 진행", 5: "사전규격 판정 참조", 6: "판정 대상 아님",
  };
  for (const entry of view.items) {
    const display = verdicts[Number(entry.item_id.slice(-2))];
    if (display) entry.verdict_display = display;
  }
  await mockBriefing(page, { briefings: { [view.briefing_date]: view } });
  const pill = (index: number) => page.locator(`tr[data-item-id="${briefingItemId(index)}"] .briefing-pill`).nth(1);

  await page.goto("/briefing");
  await expect(pill(1)).toHaveText("진행 가능");
  await expect(pill(1)).toHaveClass(/is-verdict-success/);
  await expect(pill(2)).toHaveText("진행 어려움");
  await expect(pill(2)).toHaveClass(/is-verdict-error/);
  await expect(pill(3)).toHaveText("판단 불가");
  await expect(pill(3)).toHaveClass(/is-verdict-muted/);
  await page.goto("/briefing?view=accepted");
  await expect(pill(4)).toHaveText("조건부 진행");
  await expect(pill(4)).toHaveClass(/is-verdict-warning/);
  await page.goto("/briefing?view=ignored");
  await expect(pill(5)).toHaveText("사전규격 판정 참조");
  await expect(pill(5)).toHaveClass(/is-verdict-muted/);
  await page.goto("/briefing?view=later");
  await expect(pill(6)).toHaveText("판정 대상 아님");
  await expect(pill(6)).toHaveClass(/is-verdict-muted/);
});

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`${viewport.width}px에서 가로로 넘치지 않고 좌측 280px·원문 패널 300~380px이며 긴 한글도 넘치지 않는다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const longWord = "클라우드기반통합정보시스템구축사업의세부요구사항을모두충족하여야하며".repeat(6);
    const matrix = sampleMatrix();
    matrix[2] = { ...matrix[2], normalized_requirement: longWord, role_findings: [{ ...matrix[2].role_findings[0], reason: longWord }] };
    await openVerdict(page, completedView({}, matrix));
    await waitTable(page);
    await rowOf(page, longWord.slice(0, 20)).locator(".vd-row-main").click();
    await expect(panel(page)).toBeVisible();

    const metrics = await page.evaluate(() => {
      const canvas = document.querySelector(".page-canvas") as HTMLElement;
      const side = document.querySelector(".rec-side") as HTMLElement;
      const source = document.querySelector(".vd-source") as HTMLElement;
      const header = document.querySelector(".rec-header") as HTMLElement;
      const actions = document.querySelector(".rec-actions") as HTMLElement;
      const center = document.querySelector(".vd-center") as HTMLElement;
      const scroll = document.querySelector(".vd-table-scroll") as HTMLElement;
      return {
        pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
        canvasOverflow: canvas.scrollWidth - canvas.clientWidth,
        side: side.getBoundingClientRect().width,
        source: source.getBoundingClientRect().width,
        center: center.getBoundingClientRect().width,
        centerOverflow: center.scrollWidth - center.clientWidth,
        scrollWidth: scroll.getBoundingClientRect().width,
        actionsRight: actions.getBoundingClientRect().right,
        headerRight: header.getBoundingClientRect().right,
        actionsTop: actions.getBoundingClientRect().top,
        headerBottom: header.getBoundingClientRect().bottom,
        headerTop: header.getBoundingClientRect().top,
      };
    });
    expect(metrics.pageOverflow).toBeLessThanOrEqual(0);
    expect(metrics.canvasOverflow).toBeLessThanOrEqual(0);
    expect(Math.round(metrics.side)).toBe(280);
    expect(metrics.source).toBeGreaterThanOrEqual(299);
    expect(metrics.source).toBeLessThanOrEqual(381);
    expect(metrics.centerOverflow).toBeLessThanOrEqual(0);
    expect(metrics.actionsRight).toBeLessThanOrEqual(metrics.headerRight + 1);
    expect(metrics.actionsTop).toBeGreaterThanOrEqual(metrics.headerTop);
    expect(metrics.actionsTop).toBeLessThan(metrics.headerBottom);
    await expect(page.getByTestId("verdict-summary")).toBeVisible();
    await expect(page.getByRole("button", { name: "다시 판정", exact: true }).first()).toBeVisible();
  });
}
