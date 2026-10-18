import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockOpportunityRecord, type OpportunityRecordMockTrace } from "./api-mock";
import { RECORD_NOW } from "./fixtures/opportunity-record";
import {
  PROPOSAL_DRAFT_ID,
  PROPOSAL_FORBIDDEN_VALUES,
  PROPOSAL_OLD_DRAFT_ID,
  completedDraft,
  completedSections,
  draftOf,
  failedDraft,
  partialDraft,
  reviewedDraft,
  runningDraft,
  supersededDraft,
} from "./fixtures/proposal";
import { FORBIDDEN_VALUES, completedView, runningView, sampleMatrix } from "./fixtures/verdict";
import type { PractitionerVerdictView, ProposalDraft } from "../src/lib/types";

/*
 * RL-04 STEP-008 · spec T8 — `/opportunities/:id/proposal` 사업기회 레코드 제안서 탭.
 *
 * 고정 응답은 `mockApi`(미등록 경로는 404) 위에 건 `mockOpportunityRecord`의 제안서 응답이며 실제 백엔드에
 * 연결하지 않는다. 서버 쪽 초안은 `trace.setProposal`로 바꾸고 생성 worker는 흉내 내지 않는다. 화면 시계는
 * `RECORD_NOW`로 고정한다. 기대값은 화면 코드를 가져오지 않고 fixture 값으로 직접 적었다(초안 구성은
 * fixtures/proposal.ts 머리말). fixture는 실제 데이터가 아니며 이 spec이 증명하는 것은 화면 연결이다 —
 * 실제 서버·Luna 결과 화면은 RL-04 T10·T11 기록에 결과가 적히기 전까지 하지 않은 것이다.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ACTOR = "박담당";

interface OpenOptions {
  verdict?: PractitionerVerdictView | null;
  drafts?: ProposalDraft | ProposalDraft[] | null;
  path?: string;
  viewport?: { width: number; height: number };
}

async function openProposal(page: Page, options: OpenOptions = {}): Promise<OpportunityRecordMockTrace> {
  if (options.viewport) await page.setViewportSize(options.viewport);
  await page.clock.setFixedTime(new Date(RECORD_NOW));
  await mockApi(page);
  const trace = await mockOpportunityRecord(page);
  if (options.verdict) trace.setVerdict(7101, options.verdict);
  if (options.drafts) trace.setProposal(7101, options.drafts);
  await page.goto(options.path ?? "/opportunities/7101/proposal");
  return trace;
}

const header = (page: Page) => page.locator('[data-testid="record-header"]');
const actorInput = (page: Page) => page.getByLabel("기록자", { exact: true });
const toast = (page: Page) => page.locator(".toast");
const panel = (page: Page) => page.locator("#pp-section-panel");
const card = (page: Page) => page.getByRole("article", { name: "절 본문" });
const sentence = (page: Page, text: string | RegExp) => card(page).locator(".pp-sentence").filter({ hasText: text });
const editor = (page: Page) => page.getByTestId("sentence-editor");

async function waitDraft(page: Page) {
  await expect(page.getByTestId("proposal-draft")).toBeVisible();
}

async function pickSection(page: Page, name: string) {
  await page.getByRole("tab", { name: new RegExp(`^${name}`) }).click();
  await expect(card(page).getByRole("heading", { name, level: 3 })).toBeVisible();
}

async function enterActor(page: Page, name = ACTOR) {
  await actorInput(page).fill(name);
}

async function confirm(page: Page, buttonName: string) {
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: buttonName, exact: true }).click();
}

const forbiddenText = /unmeasured_reference|mock_reference|policy_id|policy_sha|proposal-policy|analysis-policy|gpt-\d|luna|qwen|run_id|card:[0-9a-f]{8}|[0-9a-f]{64}|prompt_tokens|output_tokens/i;

async function assertClean(page: Page, context: string) {
  const html = await page.locator(".page-canvas").evaluate((node) => node.innerHTML);
  for (const value of [...FORBIDDEN_VALUES, ...PROPOSAL_FORBIDDEN_VALUES]) expect(html, `${context}: ${value}`).not.toContain(value);
  expect(html, context).not.toMatch(forbiddenText);
  // 최종 입찰 결정 표현은 이 탭의 본문·좌측에 없다(레코드의 다른 대화상자 문구는 이 검사 밖이다).
  const tab = await page.locator(".rec-body").evaluate((node) => node.innerHTML);
  expect(tab, context).not.toMatch(/Go\/No-Go|입찰 참여|최종 결정/i);
}

test("초안이 없고 판정도 없으면 안내 문장과 비활성 초안 만들기를 보이고 좌측은 사업 정보를 유지한다", async ({ page }) => {
  const trace = await openProposal(page);
  const empty = page.getByTestId("proposal-empty");
  await expect(empty.getByText("제안서 초안은 판정 뒤 만들 수 있습니다", { exact: true })).toBeVisible();
  await expect(empty).toContainText("아직 완료된 판정이 없습니다");
  const create = empty.getByRole("button", { name: "초안 만들기", exact: true });
  await expect(create).toBeDisabled();
  await expect(page.locator('.rec-action-hint[title="아직 완료된 판정이 없습니다"]')).toHaveCount(1);
  // 헤더: 초안이 없으면 내보내기·다시 만들기는 비활성이고 이유를 말한다.
  await expect(header(page).getByRole("button", { name: "PDF로 내보내기", exact: true })).toBeDisabled();
  await expect(header(page).getByRole("button", { name: "다시 만들기", exact: true })).toBeDisabled();
  await expect(page.locator('.rec-action-hint[title="아직 만든 초안이 없습니다"]')).toHaveCount(1);
  await expect(page.locator(".rec-attribute")).toHaveCount(8);
  await expect(page.getByTestId("proposal-status")).toHaveCount(0);
  expect(trace.proposalGets.length).toBeGreaterThan(0);
  expect(trace.proposalRequests).toEqual([]);
  expect(trace.unhandled).toEqual([]);
});

test("완료된 판정이 있으면 초안 만들기가 열리고 이름 없이는 요청하지 않으며 확인 뒤에야 요청한다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView() });
  const create = page.getByTestId("proposal-empty").getByRole("button", { name: "초안 만들기", exact: true });
  await expect(create).toBeEnabled();

  // 이름이 없으면 대화상자도 열지 않고 이름 칸으로 초점을 옮긴다.
  await create.click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(actorInput(page)).toBeFocused();
  await expect(page.getByRole("alert").filter({ hasText: "기록자 이름을 입력" })).toBeVisible();
  expect(trace.proposalRequests).toEqual([]);

  await enterActor(page);
  await create.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "제안서 초안 만들기" })).toBeVisible();
  await expect(dialog).toContainText("하루 생성 한도를 한 건 씁니다");
  // 취소하면 요청하지 않는다.
  await dialog.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(trace.proposalRequests).toEqual([]);

  await create.click();
  await confirm(page, "초안 만들기");
  await expect(page.getByTestId("draft-running-banner")).toBeVisible();
  expect(trace.proposalRequests).toHaveLength(1);
  expect(String(trace.proposalRequests[0].body.request_id)).toMatch(UUID);
  expect(Object.keys(trace.proposalRequests[0].body)).toEqual(["request_id"]);
  expect(trace.proposalRequests[0].headers["x-bidops-actor-name"]).toBe(`UTF-8''${encodeURIComponent(ACTOR)}`);
  await expect(toast(page)).toContainText("제안서 초안을 요청했습니다");
  expect(trace.unhandled).toEqual([]);
});

test("초안 요청이 실패하면 안전한 문구로 알리고 같은 입력의 재시도는 같은 요청 식별자를 쓴다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView() });
  await enterActor(page);
  trace.failProposal("request", { status: 409, code: "daily_cap_reached" });
  const create = page.getByTestId("proposal-empty").getByRole("button", { name: "초안 만들기", exact: true });
  await create.click();
  await confirm(page, "초안 만들기");
  const problem = page.getByRole("alert").filter({ hasText: "오늘 초안 생성 한도에 도달했습니다" });
  await expect(problem).toBeVisible();
  await expect(problem).toContainText("daily_cap_reached");
  await expect(page.getByTestId("draft-running-banner")).toHaveCount(0);

  // 다른 안전 코드도 각자 문구로 보인다.
  for (const [code, text] of [
    ["verdict_required", "완료된 판정이 없어 초안을 만들 수 없습니다"],
    ["policy_not_approved", "제안서 초안 전송 승인이 없습니다"],
    ["draft_in_progress", "이미 초안을 만드는 중입니다"],
    ["service_unavailable", "제안서 초안 생성이 꺼져 있습니다"],
  ] as const) {
    trace.failProposal("request", { status: 409, code });
    await create.click();
    await confirm(page, "초안 만들기");
    await expect(page.getByRole("alert").filter({ hasText: text })).toBeVisible();
  }

  trace.failProposal("request", null);
  await create.click();
  await confirm(page, "초안 만들기");
  await expect(page.getByTestId("draft-running-banner")).toBeVisible();
  const ids = trace.proposalRequests.map((entry) => String(entry.body.request_id));
  expect(ids.length).toBe(6);
  expect(new Set(ids).size).toBe(1);
  expect(trace.unhandled).toEqual([]);
});

test("생성 중 초안은 절별 진행을 보이고 만들어진 절은 바로 읽으며 5초마다 다시 읽어 갱신한다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: runningDraft("running") });
  const banner = page.getByTestId("draft-running-banner");
  await expect(banner.getByText("초안 생성 중", { exact: true })).toBeVisible();
  const progress = banner.getByRole("list", { name: "절별 진행" }).getByRole("listitem");
  await expect(progress).toHaveText([
    "제안 개요검토 전", "사업수행 실적생성 중", "수행 전략대기", "요구사항 수행방안대기", "운영·SLA대기", "수행조직대기",
  ]);
  // 만들어진 절은 바로 읽는다. 아직인 절은 안내만 한다.
  await expect(card(page)).toContainText("본 사업은 스마트 도시 통합플랫폼을 고도화하여");
  await pickSection(page, "사업수행 실적");
  await expect(page.getByTestId("section-progress")).toContainText("이 절을 만드는 중입니다");
  await pickSection(page, "수행 전략");
  await expect(page.getByTestId("section-progress")).toContainText("생성을 기다리고 있습니다");
  // 진행 중에는 내보내기·다시 만들기가 이유와 함께 비활성이다.
  await expect(header(page).getByRole("button", { name: "PDF로 내보내기", exact: true })).toBeDisabled();
  await expect(page.locator('.rec-action-hint[title="초안 생성이 끝난 뒤 내보낼 수 있습니다"]')).toHaveCount(1);
  await expect(header(page).getByRole("button", { name: "다시 만들기", exact: true })).toBeDisabled();
  await expect(page.locator('.rec-action-hint[title="초안을 만드는 중입니다"]')).toHaveCount(1);
  // 좌측 요약은 초안 상태를 그대로 읽는다(토큰·정책은 없다).
  await expect(page.getByTestId("proposal-draft-status")).toHaveText("초안 상태 · 생성 중");

  const before = trace.proposalGets.length;
  trace.setProposal(7101, completedDraft());
  await expect(page.getByTestId("draft-running-banner")).toHaveCount(0, { timeout: 12_000 });
  expect(trace.proposalGets.length).toBeGreaterThan(before);
  await expect(page.getByTestId("proposal-draft-status")).toHaveText("초안 상태 · 생성 완료");
  await expect(header(page).getByRole("button", { name: "PDF로 내보내기", exact: true })).toBeEnabled();
  expect(trace.unhandled).toEqual([]);
});

test("완료 초안 좌측은 단계 4·숫자·채워야 할 것·범례를 서버 값 그대로 그린다", async ({ page }) => {
  await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  const side = page.getByRole("complementary", { name: "초안 상태" });
  const steps = side.getByRole("list", { name: "초안 단계" }).getByRole("listitem");
  await expect(steps).toHaveText(["목차 · 완료", "초안 · 현재 단계", "검토 완료 · 대기", "제출 준비 · 대기"]);
  await expect(steps.nth(1)).toHaveAttribute("aria-current", "step");
  await expect(steps.nth(0)).toHaveAttribute("data-state", "done");
  await expect(steps.nth(2)).toHaveAttribute("data-state", "upcoming");

  const numbers = page.getByTestId("proposal-numbers");
  await expect(numbers.locator('[data-key="to-confirm"] dd')).toHaveText("6");
  await expect(numbers.locator('[data-key="placeholders"] dd')).toHaveText("4");
  await expect(numbers.locator('[data-key="volume"] dd')).toHaveText("17문장");
  await expect(numbers.locator('[data-key="coverage"] dd')).toHaveText("7 / 7");

  const needs = page.getByTestId("proposal-needs").locator(".pp-need");
  await expect(needs).toHaveText(["실적 금액·PM 경력1", "직접생산 세부품명1", "SLA 월간 보고 양식1", "투입 인력 수1"]);
  await expect(page.getByTestId("proposal-legend")).toContainText("주황 표시는 사람이 채우거나 확인할 자리입니다");
  await expect(page.getByTestId("proposal-legend")).toContainText("가격·투입 인력·전략은 초안에 넣지 않으며");
  await expect(side.getByText("확인할 문장", { exact: true })).toBeVisible();
  // 사업 정보 열은 초안이 있는 제안서 탭에서 이 열로 바뀐다.
  await expect(page.locator(".rec-attribute")).toHaveCount(0);
  // 참조 실행 표식은 문구로만 말하고 값 원문은 DOM에 없다.
  await expect(page.getByTestId("proposal-reference-badge")).toHaveText("참조 실행 · 품질 미측정");
  await assertClean(page, "완료 초안");
});

test("참조 표식은 mock 참조도 문구로 말하고 표식이 없으면 배지를 두지 않는다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: completedDraft({ quality_status: "mock_reference" }) });
  await expect(page.getByTestId("proposal-reference-badge")).toHaveText("mock 참조");
  trace.setProposal(7101, completedDraft({ quality_status: null }));
  await page.reload();
  await waitDraft(page);
  await expect(page.getByTestId("proposal-reference-badge")).toHaveCount(0);
  await assertClean(page, "표식 없음");
});

test("절 탭 6개 중 요구사항 수행방안에만 확인 건수 pill이 붙고 탭마다 본문이 바뀐다", async ({ page }) => {
  await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await expect(page.locator(".pp-section-tabs").getByRole("tab")).toContainText(["제안 개요", "사업수행 실적", "수행 전략", "요구사항 수행방안", "운영·SLA", "수행조직"]);
  // 확인 건수 pill은 요구사항 수행방안 탭 하나에만 있다.
  await expect(page.locator(".pp-section-tabs .pp-tab-count")).toHaveCount(1);
  await expect(page.locator("#pp-tab-requirements .pp-tab-count")).toHaveText("2");
  await expect(page.locator(".pp-section-tabs").getByRole("tab")).toHaveCount(6);
  await expect(page.getByTestId("requirements-confirm-count")).toHaveText("2");
  await expect(page.locator("#pp-tab-overview")).toHaveAttribute("aria-selected", "true");
  await expect(card(page).getByRole("heading", { name: "제안 개요", level: 3 })).toBeVisible();
  await expect(card(page)).toContainText("사업 배경");
  for (const [name, text] of [
    ["사업수행 실적", "ISO 9001 품질경영 인증"],
    ["수행 전략", "표준 프로토콜을 기반으로 설계한다"],
    ["요구사항 수행방안", "통합 인증 체계는 클라우드 기반으로 제공한다"],
    ["운영·SLA", "장애는 접수 즉시 등급별로 분류"],
    ["수행조직", "사업관리·개발·운영 역할"],
  ] as const) {
    await pickSection(page, name);
    await expect(card(page)).toContainText(text);
  }
});

test("문장 종류별로 빈 자리 슬롯·제안 수치 표식·위첨자 출처·수정됨을 다르게 그린다", async ({ page }) => {
  await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await pickSection(page, "사업수행 실적");
  // 빈 자리: 문장 본문 대신 "[채울 것: 힌트]" 슬롯. 출처가 없으니 위첨자도 없다.
  const slot = sentence(page, "실적 금액·PM 경력");
  await expect(slot).toHaveAttribute("data-kind", "placeholder");
  await expect(slot.getByTestId("placeholder-slot")).toHaveText("[채울 것: 실적 금액·PM 경력]");
  await expect(slot).not.toContainText("대표 실적의 계약 금액");
  await expect(slot.locator('[data-mark="source"]')).toHaveCount(0);
  await expect(slot.locator(".pp-gap")).toHaveCSS("background-color", /rgb\(255, 244, 229\)|rgba\(255, 244, 229/);
  // 일반 문장: 위첨자 "출처".
  const statement = sentence(page, "ISO 9001 품질경영 인증");
  await expect(statement).toHaveAttribute("data-kind", "statement");
  await expect(statement.locator('[data-mark="source"]')).toContainText("출처");
  await expect(statement.locator('[data-mark="figure"]')).toHaveCount(0);

  await pickSection(page, "수행 전략");
  const figure = sentence(page, "화면 응답시간은 3초 이내");
  await expect(figure).toHaveAttribute("data-kind", "proposed_figure");
  await expect(figure.locator('[data-mark="figure"]')).toHaveText("제안 수치");
  await expect(figure.locator('[data-mark="source"]')).toContainText("출처");
  await expect(figure.locator(".pp-text")).toHaveCSS("background-color", /rgb\(255, 244, 229\)|rgba\(255, 244, 229/);
  // 수정된 문장 표식은 아직 없다.
  await expect(card(page).locator('[data-mark="edited"]')).toHaveCount(0);
});

test("요구사항 수행방안 우측 표는 판정 표의 문장·근거와 서버 대조 상태를 읽고 unit id를 그리지 않는다", async ({ page }) => {
  await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await pickSection(page, "요구사항 수행방안");
  const section = page.getByTestId("requirement-links");
  await expect(section.getByRole("heading", { name: "이 절이 답하는 요구사항" })).toBeVisible();
  const table = section.getByRole("table", { name: "답하는 요구사항 표" });
  await expect(table.locator("tbody tr")).toHaveCount(7);
  const first = table.locator("tbody tr").nth(0);
  await expect(first).toContainText("클라우드 기반 통합 인증 체계를 제공해야 한다");
  await expect(first).toContainText("근거: 인증 구축 실적");
  await expect(first.locator(".vd-pill")).toHaveText("충족");
  await expect(first.locator(".vd-pill")).toHaveClass(/is-success/);
  const third = table.locator("tbody tr").nth(2);
  await expect(third).toContainText("직접생산 확인증명서(소프트웨어)를 보유해야 한다");
  await expect(third.locator(".vd-pill")).toHaveText("부족");
  await expect(third.locator(".vd-pill")).toHaveClass(/is-error/);
  // unknown은 부족이 아니라 확인 필요다.
  const second = table.locator("tbody tr").nth(1);
  await expect(second.locator(".vd-pill")).toHaveText("확인 필요");
  await expect(second.locator(".vd-pill")).toHaveClass(/is-warning/);
  await expect(second.locator(".vd-pill")).not.toHaveClass(/is-error/);
  expect(sampleMatrix().length).toBe(7);

  // 문단으로 이동: 그 문단이 표시된다.
  await first.getByRole("button", { name: "문단 1로 이동" }).click();
  await expect(card(page).locator('[data-paragraph-id="r1"]')).toHaveClass(/is-focused/);
  await assertClean(page, "요구사항 표");

  // 판정 표에서 찾지 못하는 요구사항은 문장을 지어내지 않는다.
  await page.getByRole("tab", { name: "제안 개요" }).click();
  await expect(page.getByTestId("requirement-links")).toContainText("이 절에 연결된 요구사항이 없습니다");
});

test("판정 표가 없으면 요구사항 문장을 지어내지 않고 서버 대조 상태만 보인다", async ({ page }) => {
  await openProposal(page, { verdict: runningView(), drafts: completedDraft() });
  await waitDraft(page);
  await pickSection(page, "요구사항 수행방안");
  const rows = page.getByTestId("requirement-links").locator("tbody tr");
  await expect(rows).toHaveCount(7);
  await expect(rows.nth(0)).toContainText("요구사항 문장 없음");
  await expect(rows.nth(0).locator(".vd-pill")).toHaveText("충족");
  await assertClean(page, "판정 표 없음");
});

test("문장을 누르면 수정 영역과 출처가 열리고 저장은 수정 기록을 남기며 수정됨 표식이 붙는다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await enterActor(page);
  const target = sentence(page, "본 사업은 스마트 도시 통합플랫폼");
  await target.click();
  await expect(target).toHaveAttribute("aria-pressed", "true");
  const box = editor(page);
  await expect(box).toBeVisible();
  // 출처: 종류 · 보조 표기 · 인용. 요구사항 원문은 id 없이 인용만.
  const sources = page.getByTestId("sentence-sources");
  await expect(sources).toContainText("공고 정보 · 공고명");
  await expect(sources).toContainText("스마트 도시 통합플랫폼 고도화 사업");
  const field = box.getByLabel("문장", { exact: true });
  await expect(field).toHaveValue("본 사업은 스마트 도시 통합플랫폼을 고도화하여 시민 서비스를 개선하는 것을 목적으로 한다.");
  // 바뀐 내용이 없으면 저장할 수 없다.
  await expect(box.getByRole("button", { name: "수정 저장", exact: true })).toBeDisabled();
  await expect(box).toContainText("바뀐 내용이 없습니다.");

  await field.fill("본 사업은 스마트 도시 통합플랫폼을 고도화하는 사업이다.");
  await box.getByRole("button", { name: "수정 저장", exact: true }).click();
  await expect(box).toHaveCount(0);
  expect(trace.proposalEdits).toHaveLength(1);
  expect(trace.proposalEdits[0].sentenceId).toBe("50000000-0000-4000-8000-000000000001");
  expect(trace.proposalEdits[0].body.text).toBe("본 사업은 스마트 도시 통합플랫폼을 고도화하는 사업이다.");
  expect(String(trace.proposalEdits[0].body.request_id)).toMatch(UUID);
  expect(Object.keys(trace.proposalEdits[0].body).sort()).toEqual(["request_id", "text"]);
  const edited = sentence(page, "고도화하는 사업이다");
  await expect(edited).toHaveAttribute("data-edited", "true");
  await expect(edited.locator('[data-mark="edited"]')).toHaveText("수정됨");
  await expect(toast(page)).toContainText("생성 원문은 바뀌지 않고");
  expect(trace.unhandled).toEqual([]);
});

test("빈 자리를 채우면 고친 글자와 수정됨으로 보이고 출처 없는 자리임을 편집 영역이 말한다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await enterActor(page);
  await pickSection(page, "수행조직");
  const slot = sentence(page, "투입 인력 수");
  await slot.click();
  await expect(page.getByTestId("editor-placeholder-note")).toContainText("채울 것: 투입 인력 수");
  await expect(page.getByTestId("sources-empty")).toContainText("출처가 없는 자리입니다");
  await editor(page).getByLabel("문장", { exact: true }).fill("투입 인력은 사업 착수 전 계약서에 따라 확정한다.");
  await editor(page).getByRole("button", { name: "수정 저장", exact: true }).click();
  await expect(sentence(page, "계약서에 따라 확정한다")).toHaveAttribute("data-kind", "placeholder");
  await expect(sentence(page, "계약서에 따라 확정한다").getByTestId("placeholder-slot")).toHaveCount(0);
  await expect(sentence(page, "계약서에 따라 확정한다").locator('[data-mark="edited"]')).toHaveText("수정됨");
  expect(trace.proposalEdits).toHaveLength(1);
});

test("문장 저장이 실패하면 입력을 그대로 두고 편집 영역에 안전한 문구를 보이며 같은 입력은 같은 요청 식별자를 쓴다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await enterActor(page);
  await sentence(page, "본 사업은 스마트 도시 통합플랫폼").click();
  const box = editor(page);
  const field = box.getByLabel("문장", { exact: true });
  await field.fill("수정한 문장입니다.");
  trace.failProposal("edit", { status: 404, code: "sentence_not_found" });
  await box.getByRole("button", { name: "수정 저장", exact: true }).click();
  await expect(box.getByRole("alert")).toContainText("고칠 문장을 찾을 수 없습니다");
  await expect(box.getByRole("alert")).toContainText("sentence_not_found");
  await expect(field).toHaveValue("수정한 문장입니다.");
  await expect(box).toBeVisible();

  trace.failProposal("edit", null);
  await box.getByRole("button", { name: "수정 저장", exact: true }).click();
  await expect(editor(page)).toHaveCount(0);
  const ids = trace.proposalEdits.map((entry) => String(entry.body.request_id));
  expect(ids).toHaveLength(2);
  expect(ids[0]).toBe(ids[1]);
});

test("문장 수정은 1~400자만 저장하고 이름이 없으면 이름을 요구한다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await sentence(page, "본 사업은 스마트 도시 통합플랫폼").click();
  const box = editor(page);
  const field = box.getByLabel("문장", { exact: true });
  const save = box.getByRole("button", { name: "수정 저장", exact: true });
  await field.fill("");
  await expect(save).toBeDisabled();
  await expect(box).toContainText("문장은 비워 둘 수 없습니다.");
  await field.fill("가".repeat(401));
  await expect(save).toBeDisabled();
  await expect(box).toContainText("문장은 400자까지입니다.");
  await field.fill("가".repeat(400));
  await expect(save).toBeEnabled();
  // 이름을 지우면 저장 요청 없이 이름 칸으로 안내한다.
  await actorInput(page).fill("");
  await save.click();
  await expect(box.getByRole("alert").filter({ hasText: "기록자 이름이 필요합니다" })).toBeVisible();
  await expect(actorInput(page)).toBeFocused();
  expect(trace.proposalEdits).toEqual([]);
});

test("문장 수정 버튼은 선택한 문장이 있을 때만 열리고 취소하면 닫힌다", async ({ page }) => {
  await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  const toolbar = page.getByTestId("section-toolbar");
  await expect(toolbar.getByRole("button", { name: "문장 수정", exact: true })).toBeDisabled();
  await expect(page.locator('.rec-action-hint[title="고칠 문장을 먼저 선택하십시오"]')).toHaveCount(1);
  const target = sentence(page, "발주기관은 클라우드 기반 통합 인증 체계");
  await target.focus();
  await page.keyboard.press("Enter");
  await expect(editor(page)).toBeVisible();
  await expect(page.getByTestId("sentence-sources")).toContainText("공고 요구사항 원문");
  await expect(page.getByTestId("sentence-sources")).toContainText("통합 인증 체계를 제공하여야 한다.");
  await expect(toolbar.getByRole("button", { name: "문장 수정", exact: true })).toBeEnabled();
  await toolbar.getByRole("button", { name: "문장 수정", exact: true }).click();
  await expect(editor(page).getByLabel("문장", { exact: true })).toBeFocused();
  await editor(page).getByRole("button", { name: "취소", exact: true }).click();
  await expect(editor(page)).toHaveCount(0);
  await expect(target).toHaveAttribute("aria-pressed", "false");
});

test("저장하지 않은 문장 수정이 있으면 탭을 떠날 때 확인을 요구한다", async ({ page }) => {
  await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await sentence(page, "본 사업은 스마트 도시 통합플랫폼").click();
  await editor(page).getByLabel("문장", { exact: true }).fill("저장하지 않은 수정");
  await page.getByRole("tab", { name: "활동", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toContainText("사업기회 레코드를 떠납니다");
});

test("절 검토 완료는 서버 전이를 따르고 여섯 절을 모두 마치면 단계가 검토 완료로 바뀐다", async ({ page }) => {
  const sections = completedSections().map((entry, index) => (index === 0 ? entry : { ...entry, status: "reviewed" as const }));
  const trace = await openProposal(page, { verdict: completedView(), drafts: draftOf(sections) });
  await waitDraft(page);
  await enterActor(page);
  const steps = page.getByRole("list", { name: "초안 단계" }).getByRole("listitem");
  await expect(steps.nth(1)).toHaveAttribute("data-state", "current");
  // 이미 검토한 절은 버튼이 비활성이고 이유를 말한다.
  await pickSection(page, "수행 전략");
  await expect(page.getByTestId("section-status")).toHaveText("검토 완료");
  await expect(page.getByTestId("section-toolbar").getByRole("button", { name: "검토 완료", exact: true })).toBeDisabled();
  await expect(page.locator('.rec-action-hint[title="이미 검토 완료로 표시했습니다"]')).toHaveCount(1);

  await pickSection(page, "제안 개요");
  await expect(page.getByTestId("section-status")).toHaveText("검토 전");
  await page.getByTestId("section-toolbar").getByRole("button", { name: "검토 완료", exact: true }).click();
  await expect(page.getByTestId("section-status")).toHaveText("검토 완료");
  expect(trace.proposalReviews).toHaveLength(1);
  expect(trace.proposalReviews[0].sectionKey).toBe("overview");
  expect(Object.keys(trace.proposalReviews[0].body)).toEqual(["request_id"]);
  await expect(toast(page)).toContainText("이 절을 검토 완료로 표시했습니다");
  await expect(steps.nth(2)).toHaveAttribute("data-state", "current");
  await expect(steps.nth(1)).toHaveAttribute("data-state", "done");
  expect(trace.unhandled).toEqual([]);
});

test("검토 완료가 거절되면 안전한 문구를 보이고 최신 상태를 다시 불러올 수 있다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await enterActor(page);
  trace.failProposal("review", { status: 409, code: "section_not_completed" });
  await page.getByTestId("section-toolbar").getByRole("button", { name: "검토 완료", exact: true }).click();
  const problem = page.getByRole("alert").filter({ hasText: "생성이 끝나지 않았거나 실패한 절은 검토 완료로 표시할 수 없습니다" });
  await expect(problem).toBeVisible();
  await expect(problem).toContainText("section_not_completed");
  trace.failProposal("review", null);
  await problem.getByRole("button", { name: "최신 상태 다시 불러오기" }).click();
  await expect(problem).toHaveCount(0);
});

test("제출 준비 표시는 검토 완료 단계에서만 열리고 확인 뒤 stage ready를 요청한다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await header(page).getByRole("button", { name: "사업기회 더보기" }).click();
  await expect(page.getByRole("menuitem", { name: /제출 준비로 표시/ })).toBeDisabled();
  await expect(page.getByRole("menu")).toContainText("모든 절을 검토 완료로 표시한 뒤 열립니다");
  await expect(page.getByRole("menuitem", { name: /HWP로 내보내기/ })).toBeDisabled();
  await expect(page.getByRole("menuitem", { name: /버전 비교/ })).toBeDisabled();
  await expect(page.getByRole("menu")).toContainText("후속 기능입니다");
  await page.keyboard.press("Escape");

  trace.setProposal(7101, reviewedDraft());
  await page.reload();
  await waitDraft(page);
  const steps = page.getByRole("list", { name: "초안 단계" }).getByRole("listitem");
  await expect(steps.nth(2)).toHaveAttribute("data-state", "current");
  await enterActor(page);
  // 결정 B50: 검토 완료 뒤에는 절 다시 쓰기가 이유와 함께 닫히고, 새 초안(헤더 다시 만들기)은 열려 있다.
  const rewrite = page.getByTestId("section-toolbar").getByRole("button", { name: "이 절 다시 쓰기", exact: true });
  await expect(rewrite).toBeDisabled();
  await expect(page.getByTestId("section-toolbar")).toContainText("검토 완료 뒤에는 새 초안으로 다시 만듭니다");
  await expect(header(page).getByRole("button", { name: "다시 만들기", exact: true })).toBeEnabled();
  await header(page).getByRole("button", { name: "사업기회 더보기" }).click();
  await page.getByRole("menuitem", { name: /제출 준비로 표시/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("되돌릴 수 없습니다");
  await expect(dialog).toContainText("서류 준비 상태일 뿐입니다");
  await dialog.getByRole("button", { name: "제출 준비로 표시", exact: true }).click();
  await expect(steps.nth(3)).toHaveAttribute("data-state", "done");
  expect(trace.proposalStages).toHaveLength(1);
  expect(trace.proposalStages[0].body).toMatchObject({ stage: "ready" });
  expect(String(trace.proposalStages[0].body.request_id)).toMatch(UUID);
  await expect(toast(page)).toContainText("제출 준비로 표시했습니다");
  // 제출 준비 뒤에도 절 다시 쓰기는 닫혀 있다(결정 B50).
  await expect(rewrite).toBeDisabled();
  expect(trace.proposalRegenerations).toHaveLength(0);
  // 이미 표시했으면 다시 열리지 않는다.
  await header(page).getByRole("button", { name: "사업기회 더보기" }).click();
  await expect(page.getByRole("menuitem", { name: /제출 준비로 표시/ })).toBeDisabled();
  await expect(page.getByRole("menu")).toContainText("이미 제출 준비로 표시했습니다");
  expect(trace.unhandled).toEqual([]);
});

test("이 절 다시 쓰기는 확인 뒤 요청하고 새 버전이 만들어지는 동안 안내하며 진행 중 중복은 안전한 문구로 막힌다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await pickSection(page, "수행 전략");
  await enterActor(page);
  const rewrite = page.getByTestId("section-toolbar").getByRole("button", { name: "이 절 다시 쓰기", exact: true });
  await rewrite.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "수행 전략 다시 쓰기" })).toBeVisible();
  await expect(dialog).toContainText("지금 버전은 지워지지 않고 기록으로 남지만");
  await dialog.getByRole("button", { name: "취소", exact: true }).click();
  expect(trace.proposalRegenerations).toEqual([]);

  await rewrite.click();
  await confirm(page, "다시 쓰기 요청");
  await expect(page.getByTestId("section-progress")).toContainText("생성을 기다리고 있습니다");
  expect(trace.proposalRegenerations).toHaveLength(1);
  expect(trace.proposalRegenerations[0]).toMatchObject({ draftId: PROPOSAL_DRAFT_ID, sectionKey: "strategy" });
  await expect(page.getByTestId("section-status")).toHaveText("대기");
  await expect(card(page)).toContainText("다시 쓴 버전 2");
  await expect(toast(page)).toContainText("다시 쓰도록 요청했습니다");

  // 한도·중복은 안전한 문구로 보인다.
  await pickSection(page, "제안 개요");
  trace.failProposal("regenerate", { status: 409, code: "section_in_progress" });
  await page.getByTestId("section-toolbar").getByRole("button", { name: "이 절 다시 쓰기", exact: true }).click();
  await confirm(page, "다시 쓰기 요청");
  await expect(page.getByRole("alert").filter({ hasText: "이 절을 이미 다시 쓰는 중입니다" })).toBeVisible();
  trace.failProposal("regenerate", { status: 409, code: "daily_cap_reached" });
  await page.getByTestId("section-toolbar").getByRole("button", { name: "이 절 다시 쓰기", exact: true }).click();
  await confirm(page, "다시 쓰기 요청");
  await expect(page.getByRole("alert").filter({ hasText: "오늘 초안 생성 한도에 도달했습니다" })).toBeVisible();
});

test("일부 절이 실패한 초안은 실패 카드에 사유·다시 쓰기를 보이고 나머지 절과 PDF는 그대로 쓸 수 있다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: partialDraft() });
  await waitDraft(page);
  const banner = page.getByTestId("draft-partial-banner");
  await expect(banner).toContainText("일부 절을 만들지 못했습니다");
  await expect(banner).toContainText("실패한 절 1개");
  await expect(page.getByTestId("proposal-draft-status")).toHaveText("초안 상태 · 일부 절 실패");
  await expect(page.locator("#pp-tab-operations_sla")).toContainText("생성 실패");
  // 다른 절은 그대로 읽는다.
  await expect(card(page)).toContainText("본 사업은 스마트 도시 통합플랫폼");
  await pickSection(page, "운영·SLA");
  const failed = page.getByTestId("section-failed");
  await expect(failed.getByText("생성 실패", { exact: true })).toBeVisible();
  await expect(failed).toContainText("가격·인력·일정 약속 검증을 통과하지 못했습니다");
  await expect(failed).toContainText("자동으로 고치지 않습니다");
  await expect(failed).toContainText("오류 코드 proposal_forbidden_content");
  await expect(page.getByTestId("section-status")).toHaveText("생성 실패");
  await expect(page.getByTestId("section-status")).toHaveClass(/is-error/);
  // 실패 절에는 검토·문장 수정 도구가 없고 카드의 "다시 쓰기"만 있다.
  await expect(page.getByTestId("section-toolbar")).toHaveCount(0);
  // PDF는 partial에서도 열린다.
  await expect(header(page).getByRole("button", { name: "PDF로 내보내기", exact: true })).toBeEnabled();

  await enterActor(page);
  await failed.getByRole("button", { name: "다시 쓰기", exact: true }).click();
  await confirm(page, "다시 쓰기 요청");
  await expect(page.getByTestId("section-progress")).toBeVisible();
  expect(trace.proposalRegenerations[0]).toMatchObject({ sectionKey: "operations_sla" });
  await assertClean(page, "partial 초안");
});

test("전체 실패 초안은 절별 사유를 한글로 보이고 모르는 코드는 코드 그대로 보이며 PDF는 막힌다", async ({ page }) => {
  await openProposal(page, { verdict: completedView(), drafts: failedDraft() });
  await waitDraft(page);
  await expect(page.getByTestId("draft-failed-banner")).toContainText("초안 생성에 실패했습니다");
  await expect(header(page).getByRole("button", { name: "PDF로 내보내기", exact: true })).toBeDisabled();
  await expect(page.locator('.rec-action-hint[title="내보낼 수 있는 초안이 없습니다"]')).toHaveCount(1);
  for (const [name, text, code] of [
    ["제안 개요", "출처·구조 검증을 통과하지 못했습니다", "proposal_section_invalid"],
    ["수행 전략", "정해진 시간 안에 초안 생성이 끝나지 않았습니다", "proposal_review_timeout"],
    ["요구사항 수행방안", "이 절의 입력이 분석 한도를 넘었습니다", "input_budget_exceeded"],
    ["운영·SLA", "요구사항을 빠짐없이 덮지 못했습니다", "proposal_coverage_incomplete"],
    ["수행조직", "초안 생성 중 안전 오류가 기록됐습니다", "mystery_code_zz"],
  ] as const) {
    await pickSection(page, name);
    await expect(page.getByTestId("section-failed")).toContainText(text);
    await expect(page.getByTestId("section-failed")).toContainText(`오류 코드 ${code}`);
  }
  // 모르는 코드에는 지어낸 문장을 붙이지 않는다.
  await expect(page.getByTestId("section-failed")).not.toContainText("자동으로 고치지 않습니다. 다시 쓰거나");
  await assertClean(page, "실패 초안");
});

test("이전 초안은 draft_id로만 열리고 읽기 전용이며 최신 초안 보기로 돌아간다", async ({ page }) => {
  const latest = completedDraft({ draft_id: "d4000000-0000-4000-8000-000000000002" });
  const trace = await openProposal(page, {
    verdict: completedView(),
    drafts: [supersededDraft(), latest],
    path: `/opportunities/7101/proposal?draft_id=${PROPOSAL_OLD_DRAFT_ID}`,
  });
  await waitDraft(page);
  expect(trace.proposalGets[0].params.get("draft_id")).toBe(PROPOSAL_OLD_DRAFT_ID);
  const banner = page.getByTestId("draft-superseded-banner");
  await expect(banner).toContainText("이전 초안");
  await expect(banner).toContainText("읽기만 할 수 있습니다");
  await expect(page.getByTestId("proposal-draft-status")).toHaveText("초안 상태 · 이전 초안");
  // 문장·검토·다시 쓰기·내보내기·제출 준비 모두 막힌다.
  await expect(sentence(page, "본 사업은 스마트 도시 통합플랫폼")).toBeDisabled();
  const toolbar = page.getByTestId("section-toolbar");
  await expect(toolbar.getByRole("button", { name: "이 절 다시 쓰기", exact: true })).toBeDisabled();
  await expect(toolbar.getByRole("button", { name: "검토 완료", exact: true })).toBeDisabled();
  await expect(header(page).getByRole("button", { name: "PDF로 내보내기", exact: true })).toBeDisabled();
  await header(page).getByRole("button", { name: "사업기회 더보기" }).click();
  await expect(page.getByRole("menuitem", { name: /제출 준비로 표시/ })).toBeDisabled();
  await page.keyboard.press("Escape");

  await banner.getByRole("button", { name: "최신 초안 보기" }).click();
  await expect(page).toHaveURL(/\/opportunities\/7101\/proposal$/);
  await expect(page.getByTestId("draft-superseded-banner")).toHaveCount(0);
  await expect(page.getByTestId("proposal-draft-status")).toHaveText("초안 상태 · 생성 완료");
  expect(trace.proposalGets.at(-1)?.params.get("draft_id")).toBeNull();
});

test("알 수 없는 draft_id는 초안을 찾을 수 없다고 알리고 최신 초안으로 돌아가게 한다", async ({ page }) => {
  await openProposal(page, {
    verdict: completedView(),
    drafts: completedDraft(),
    path: "/opportunities/7101/proposal?draft_id=d4999999-0000-4000-8000-000000000000",
  });
  await expect(page.getByText("초안을 찾을 수 없습니다", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "최신 초안 보기" }).click();
  await waitDraft(page);
  await expect(page).toHaveURL(/\/opportunities\/7101\/proposal$/);
});

test("PDF 내보내기는 POST로 만들고 GET으로 내려받으며 같은 내용은 기존 PDF를 다시 받는다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  const button = header(page).getByRole("button", { name: "PDF로 내보내기", exact: true });
  // 이름이 없으면 요청하지 않는다.
  await button.click();
  await expect(actorInput(page)).toBeFocused();
  expect(trace.proposalExports).toEqual([]);

  await enterActor(page);
  const [download] = await Promise.all([page.waitForEvent("download"), button.click()]);
  expect(download.suggestedFilename()).toBe("제안서-초안-7101.pdf");
  expect(trace.proposalExports).toHaveLength(1);
  expect(Object.keys(trace.proposalExports[0].body)).toEqual(["request_id"]);
  expect(trace.proposalPdfGets).toHaveLength(1);
  expect(trace.proposalPdfGets[0].draftId).toBe(PROPOSAL_DRAFT_ID);
  await expect(toast(page)).toContainText("PDF를 만들었습니다");
  // 가장 최근 PDF는 다시 내려받을 수 있는 링크로 남고 sha는 그리지 않는다.
  const latest = page.getByTestId("latest-export");
  await expect(latest).toContainText("최근 PDF");
  await expect(latest.getByRole("button", { name: "다시 내려받기" })).toBeEnabled();
  // 다시 내려받기는 새 PDF를 만들지 않고 같은 PDF를 GET으로 읽는다.
  const [redo] = await Promise.all([page.waitForEvent("download"), latest.getByRole("button", { name: "다시 내려받기" }).click()]);
  expect(redo.suggestedFilename()).toBe("제안서-초안-7101.pdf");
  expect(trace.proposalExports).toHaveLength(1);
  expect(trace.proposalPdfGets).toHaveLength(2);

  // 같은 내용이면 서버가 기존 PDF를 돌려준다(created=false).
  const [again] = await Promise.all([page.waitForEvent("download"), button.click()]);
  expect(again.suggestedFilename()).toBe("제안서-초안-7101.pdf");
  await expect(toast(page)).toContainText("내용이 같은 PDF가 이미 있어");
  expect(trace.proposalExports).toHaveLength(2);
  expect(trace.proposalExports[0].body.request_id).not.toBe(trace.proposalExports[1].body.request_id);
  expect(trace.proposalPdfGets).toHaveLength(3);
  expect(new Set(trace.proposalPdfGets.map((entry) => entry.exportId)).size).toBe(1);

  // 문장을 고치면 내용이 달라져 새 PDF가 만들어진다.
  await sentence(page, "본 사업은 스마트 도시 통합플랫폼").click();
  await editor(page).getByLabel("문장", { exact: true }).fill("새로 고친 문장이다.");
  await editor(page).getByRole("button", { name: "수정 저장", exact: true }).click();
  await expect(editor(page)).toHaveCount(0);
  const [third] = await Promise.all([page.waitForEvent("download"), button.click()]);
  expect(third.suggestedFilename()).toBe("제안서-초안-7101.pdf");
  await expect(toast(page)).toContainText("PDF를 만들었습니다");
  await assertClean(page, "내보내기 뒤");
  expect(trace.unhandled).toEqual([]);
});

test("PDF 렌더러가 없으면 503 pdf_unavailable을 안전한 문구로 알리고 다운로드를 시작하지 않는다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await enterActor(page);
  trace.failProposal("export", { status: 503, code: "pdf_unavailable" });
  await header(page).getByRole("button", { name: "PDF로 내보내기", exact: true }).click();
  const problem = page.getByRole("alert").filter({ hasText: "PDF를 만들 수 없습니다" });
  await expect(problem).toBeVisible();
  await expect(problem).toContainText("pdf_unavailable");
  await expect(problem).toContainText("초안은 그대로 남아 있습니다");
  expect(trace.proposalPdfGets).toEqual([]);
  // 초안은 그대로다.
  await expect(card(page)).toContainText("본 사업은 스마트 도시 통합플랫폼");
  // 다른 거절도 안전한 문구다.
  trace.failProposal("export", { status: 409, code: "draft_not_completed" });
  await header(page).getByRole("button", { name: "PDF로 내보내기", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "생성이 끝나지 않은 초안은 내보낼 수 없습니다" })).toBeVisible();
});

test("내려받는 GET이 실패하거나 해시가 기록과 다르면 저장하지 않고 안전한 문구로 알린다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await enterActor(page);
  let mode: "missing" | "unavailable" | "mismatch" = "missing";
  await page.route(/\/api\/proposals\/[^/]+\/exports\/[^/]+\.pdf$/, async (route) => {
    if (mode === "mismatch") {
      await route.fulfill({ status: 200, contentType: "application/pdf", headers: { "X-BidOps-Export-Sha256": "1".repeat(64) }, body: "%PDF-1.4" });
      return;
    }
    await route.fulfill({
      status: mode === "missing" ? 404 : 503,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: mode === "missing" ? "not_found" : "pdf_unavailable", message: "합성 오류", details: null }, request_id: null }),
    });
  });
  const button = header(page).getByRole("button", { name: "PDF로 내보내기", exact: true });
  let downloaded = 0;
  page.on("download", () => { downloaded += 1; });
  await button.click();
  await expect(page.getByRole("alert").filter({ hasText: "대상을 찾을 수 없습니다" })).toBeVisible();
  mode = "unavailable";
  await button.click();
  await expect(page.getByRole("alert").filter({ hasText: "PDF를 만들 수 없습니다" })).toBeVisible();
  mode = "mismatch";
  await button.click();
  await expect(page.getByRole("alert").filter({ hasText: "내려받은 PDF가 기록과 다릅니다" })).toBeVisible();
  expect(downloaded).toBe(0);
  // 내보내기 기록(POST)은 서버에 남아 있고 같은 내용이므로 두 번째부터 created=false다.
  expect(trace.proposalExports.length).toBe(3);
});

test("제안서를 읽지 못하면 오류 상태와 다시 시도를 보이고 헤더 액션은 서버 상태를 모르므로 닫혀 있다", async ({ page }) => {
  const trace = await openProposal(page, { verdict: completedView() });
  await expect(page.getByTestId("proposal-empty")).toBeVisible();
  trace.failProposal("get", { status: 500, code: "processing_failed" });
  await page.reload();
  const alert = page.getByRole("alert").filter({ hasText: "제안서 초안을 불러오지 못했습니다" });
  await expect(alert).toBeVisible();
  await expect(header(page).getByRole("button", { name: "PDF로 내보내기", exact: true })).toBeDisabled();
  await expect(page.locator('.rec-action-hint[title="초안을 불러오지 못했습니다"]')).toHaveCount(2);
  trace.failProposal("get", null);
  await alert.getByRole("button", { name: "다시 시도" }).click();
  await expect(page.getByTestId("proposal-empty")).toBeVisible();
});

test("판정 탭의 제안서 초안은 완료된 판정이 있을 때 제안서 탭으로 가고 없으면 이유와 함께 비활성이다", async ({ page }) => {
  await openProposal(page, { verdict: completedView(), path: "/opportunities/7101/verdict" });
  const button = header(page).getByRole("button", { name: "제안서 초안", exact: true });
  await expect(button).toBeEnabled();
  await button.click();
  await expect(page).toHaveURL(/\/opportunities\/7101\/proposal$/);
  await expect(page.getByTestId("proposal-empty")).toBeVisible();

  await page.goto("/opportunities/7101/activity");
  await expect(header(page).getByRole("button", { name: "제안서 초안", exact: true })).toBeEnabled();
  await page.getByRole("tab", { name: "제안서", exact: true }).click();
  // 제안서 탭에서는 헤더 액션이 PDF·다시 만들기로 바뀐다.
  await expect(header(page).getByRole("button", { name: "제안서 초안", exact: true })).toHaveCount(0);
  await expect(header(page).getByRole("button", { name: "PDF로 내보내기", exact: true })).toBeVisible();
});

test("제안서 탭은 최종 입찰 결정·가격·투입 인력 입력을 두지 않고 운영 정보를 그리지 않는다", async ({ page }) => {
  await openProposal(page, { verdict: completedView(), drafts: completedDraft() });
  await waitDraft(page);
  await expect(page.getByRole("button", { name: /Go\/No-Go|입찰 참여|추적 시작|가격/ })).toHaveCount(0);
  await expect(page.getByRole("textbox")).toHaveCount(1); // 기록자 이름 칸 하나뿐이다.
  for (const name of ["제안 개요", "사업수행 실적", "수행 전략", "요구사항 수행방안", "운영·SLA", "수행조직"]) {
    await pickSection(page, name);
    await assertClean(page, name);
  }
  const top = await page.locator("header.topbar").innerText();
  for (const value of [...FORBIDDEN_VALUES, ...PROPOSAL_FORBIDDEN_VALUES]) expect(top).not.toContain(value);
});

for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`${viewport.width}px에서 가로로 넘치지 않고 좌측이 280px이며 본문 카드는 620px를 넘지 않는다`, async ({ page }) => {
    await openProposal(page, { verdict: completedView(), drafts: completedDraft(), viewport });
    await waitDraft(page);
    await pickSection(page, "요구사항 수행방안");
    await expect(page.getByTestId("requirement-links").locator("tbody tr")).toHaveCount(7);
    const metrics = await page.evaluate(() => {
      const canvas = document.querySelector(".page-canvas") as HTMLElement;
      const side = document.querySelector(".rec-side") as HTMLElement;
      const body = document.querySelector(".pp-card") as HTMLElement;
      const req = document.querySelector(".pp-req") as HTMLElement;
      const styles = getComputedStyle(body);
      const bodyRect = body.getBoundingClientRect();
      const reqRect = req.getBoundingClientRect();
      return {
        pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
        canvasOverflow: canvas.scrollWidth - canvas.clientWidth,
        side: side.getBoundingClientRect().width,
        card: bodyRect.width,
        cardRight: bodyRect.right,
        reqLeft: reqRect.left,
        reqRight: reqRect.right,
        canvasRight: canvas.getBoundingClientRect().right,
        fontFamily: styles.fontFamily,
        ratio: Number.parseFloat(styles.lineHeight) / Number.parseFloat(styles.fontSize),
      };
    });
    expect(metrics.pageOverflow).toBeLessThanOrEqual(0);
    expect(metrics.canvasOverflow).toBeLessThanOrEqual(0);
    expect(Math.round(metrics.side)).toBe(280);
    expect(metrics.card).toBeLessThanOrEqual(621);
    expect(metrics.reqRight).toBeLessThanOrEqual(metrics.canvasRight + 1);
    expect(metrics.fontFamily.toLowerCase()).toContain("serif");
    expect(metrics.ratio).toBeCloseTo(1.8, 1);
    // 본문 카드와 표는 한 줄에 나란히 서거나(넓은 폭) 아래로 내려간다(좁은 폭) — 겹치지 않는다.
    const sideBySide = metrics.reqLeft >= metrics.cardRight - 1;
    const stacked = await page.evaluate(() => {
      const bodyRect = (document.querySelector(".pp-card") as HTMLElement).getBoundingClientRect();
      const reqRect = (document.querySelector(".pp-req") as HTMLElement).getBoundingClientRect();
      return reqRect.top >= bodyRect.bottom - 1;
    });
    expect(sideBySide || stacked).toBe(true);
    // 헤더 액션은 헤더 안에 머문다.
    const actions = await page.evaluate(() => {
      const headerBox = (document.querySelector(".rec-header") as HTMLElement).getBoundingClientRect();
      const actionsBox = (document.querySelector(".rec-actions") as HTMLElement).getBoundingClientRect();
      return { right: actionsBox.right <= headerBox.right + 1, inside: actionsBox.top >= headerBox.top && actionsBox.top < headerBox.bottom };
    });
    expect(actions).toEqual({ right: true, inside: true });
  });
}
