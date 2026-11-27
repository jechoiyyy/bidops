import { expect, test, type Page } from "@playwright/test";
import {
  mockApi,
  mockFeatureFlags,
  overviewEnvelopeFixture,
  overviewRangeReviewFixture,
  overviewRunFixture,
  preSpecListBody,
  settleProcessSection,
  visualBundle,
  visualPreSpecItems,
  visualPreSpecNotice,
} from "./api-mock";
import type { OverviewEnvelope, OverviewRun, PreSpecListItem } from "../src/lib/types";

// 2026-11-21 사전규격 상세 문제 상태 안내(시안 `docs/specs/1121_prespec-detail/` c1~c5, 근거 findings/model-review.md 첫 항목).
// 안내 문장 표와 고르는 규칙은 `src/lib/preSpecProblemNotice.ts` 한 곳이다. 여기서는 각 안내가 맞는 굵은 줄을 고르고
// 서버 값(쪽 범위·쪽수·실패 문장·건수)을 그대로 쓰는지, 처리 상태 구역이 닫혀 들어오고 요약이 멈춘 단계를 말하는지 본다.
// 고정값은 일부러 눈에 띄는 숫자(7~49쪽 · 전체 123쪽)를 쓴다.
// (api-mock.ts에서 `visualPreSpecItems`·`preSpecListBody`를 export해야 한다.)

const FUTURE_DEADLINE = "2099-12-31T14:59:00Z";
const PAST_DEADLINE = "2026-09-02T00:00:00Z";

interface ProblemFixture {
  item?: Partial<PreSpecListItem>;
  notice?: Record<string, unknown>;
  bundle: Record<string, unknown> | null;
  envelope: OverviewEnvelope;
  overviewFlag?: boolean;
}

/** 입력 가능한 하단 띠(사업기회 연결·미선택)를 가진 991 한 건. 상태마다 바뀌는 값만 덮는다. */
async function mockProblemDetail(page: Page, fixture: ProblemFixture) {
  await mockApi(page);
  await mockFeatureFlags(page, { rl_analysis: false, prespec_overview: fixture.overviewFlag ?? true });
  const item = {
    ...visualPreSpecItems[0],
    opportunity_id: 78,
    tracking_status: "미선택",
    kept_by_tracking: false,
    document: { attachments: 1, "완료": 1, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
    ...fixture.item,
  } as PreSpecListItem;
  await page.route((url) => url.pathname === "/api/pre-specs", async (route) => {
    if (route.request().method() !== "GET") { await route.fallback(); return; }
    await route.fulfill({ json: { ...preSpecListBody({
      items: [item], total: 1, limit: 50, offset: 0, statusItems: [item], unscoped: [item],
      search: new URL(route.request().url()).searchParams,
    }), workspace_counts: { actionable: 1, needs_check: 0, recent: 1, tracking: 0, all: 1 } } });
  });
  await page.route("**/api/notices/991", async (route) => {
    if (route.request().method() !== "GET") { await route.fallback(); return; }
    await route.fulfill({ json: { ...visualPreSpecNotice, ...fixture.notice } });
  });
  await page.route("**/api/notices/991/document-bundles", async (route) => {
    if (route.request().method() !== "GET") { await route.fallback(); return; }
    await route.fulfill({ json: { items: fixture.bundle ? [fixture.bundle] : [] } });
  });
  await page.route("**/api/pre-specs/991/overview", (route) => route.fulfill({ json: fixture.envelope }));
}

function pendingRange(run: OverviewRun, pages: number) {
  // 실행이 실패·보류면 서버는 범위 확인을 `pending`으로 연다. 범위 선택 사유는 비어 있다(운영 관측과 같다).
  return overviewRangeReviewFixture({ target_id: run.id, status: "pending", reason_code: null, pdf_page_count: pages });
}

const capacityRun = overviewRunFixture({
  id: "c1c1c1c1-0000-4000-8000-000000000001",
  status: "failed",
  reason_codes: ["input_capacity_exceeded"],
  range_source: "fallback",
  range_reason_codes: [],
  page_start: 7,
  page_end: 49,
  pdf_page_count: 123,
  reviewed_pages: [],
  call_count: 0,
});

const heldClaimText = "2026년 10월부터 2027년 12월까지 유지관리 용역 수행";
const heldRun = overviewRunFixture({
  id: "c2c2c2c2-0000-4000-8000-000000000002",
  status: "needs_human_review",
  reason_codes: ["semantic_review_failed"],
  verification_status: "needs_human_review",
  page_start: 3,
  page_end: 5,
  pdf_page_count: 117,
  reviewed_pages: [3, 4, 5],
  failed_claims: [{
    claim_id: "c4",
    section: "main_tasks",
    text: heldClaimText,
    reason_codes: ["insufficient_evidence"],
    evidence: [{ page: 5, quote: "유지관리 용역" }],
  }],
});

const settledItem = { auto_preparation_status: "overview_settled", auto_preparation_reason: null } as const;

const states = {
  c1: {
    item: { ...settledItem, overview_review_status: "failed" },
    bundle: visualBundle("ready"),
    envelope: overviewEnvelopeFixture(991, capacityRun, [capacityRun], { range_review: pendingRange(capacityRun, 123) }),
  },
  c2: {
    item: { ...settledItem, overview_review_status: "needs_human_review" },
    bundle: visualBundle("ready"),
    envelope: overviewEnvelopeFixture(991, heldRun, [heldRun], { range_review: pendingRange(heldRun, 117) }),
  },
  c3: {
    item: { auto_preparation_status: "blocked", auto_preparation_reason: "bundle_has_blocking_issues", overview_review_status: null },
    bundle: {
      ...visualBundle("blocked"),
      documents: [{ ...visualBundle("ready").documents[0], original_filename: "제안요청서-스캔본.pdf", structure_status: "failed" }],
      issues: [{
        issue_id: "ocr", code: "ocr_issue", severity: "차단", blocking: true,
        document_version_id: "20000000-0000-0000-0000-000000000991",
        message: "OCR 또는 page 구조화 확인이 필요합니다", locator_type: "none", locator: null,
      }],
    },
    envelope: overviewEnvelopeFixture(991, null),
  },
  c4: {
    item: {
      auto_preparation_status: "blocked", auto_preparation_reason: "attachments_failed", overview_review_status: null,
      document: { attachments: 3, "완료": 0, "대기": 0, "진행": 0, "차단": 2, "실패": 1 },
    },
    notice: {
      attachments: [{
        id: 7001, name: "첨부 1", url: "https://www.g2b.go.kr/fixture/attachment-7001", origin: "g2b",
        file_ext: null, size_bytes: null, extract_status: null, created_at: null, acquired_file: null,
      }],
    },
    bundle: null,
    envelope: overviewEnvelopeFixture(991, null),
  },
  c5: {
    item: { auto_preparation_status: "bundle_ready", auto_preparation_reason: null, overview_review_status: null, deadline_at: FUTURE_DEADLINE },
    notice: { deadline_at: FUTURE_DEADLINE },
    bundle: visualBundle("ready"),
    envelope: overviewEnvelopeFixture(991, null),
  },
} satisfies Record<string, ProblemFixture>;

const notice = (page: Page) => page.getByTestId("pre-spec-problem-notice");

async function expectClosedFold(page: Page, summary: string) {
  const toggle = await settleProcessSection(page);
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator("#ps-process-body")).toHaveCount(0);
  await expect(page.getByTestId("pre-spec-process-summary")).toContainText(summary);
  return toggle;
}

test("c1 범위 과대: 서버 쪽 범위로 이유를 말하고 범위 폼을 품으며 선택기 탓 문장이 없다", async ({ page }) => {
  await mockProblemDetail(page, states.c1);
  await page.goto("/pre-specs/991");
  const block = notice(page);
  await expect(block).toHaveAttribute("data-kind", "overview_range_too_wide");
  await expect(block.locator(".ps-problem-lead")).toContainText("개요 실패");
  await expect(block.locator(".ps-problem-lead strong")).toHaveText("개요를 만들지 못했어요. 읽을 범위가 너무 넓어요");
  await expect(page.getByTestId("pre-spec-problem-reason")).toHaveText(
    "자동으로 고른 범위 7~49쪽(전체 123쪽)이 한 번에 읽을 수 있는 분량보다 많았어요. 사업 개요 위치를 자동으로 찾지 못해 범위를 넓게 잡았어요.",
  );
  await expect(block).toContainText("이전 범위 7~49쪽 · 전체 123쪽");
  await expect(block.locator(".ps-problem-codes")).toHaveText("input_capacity_exceeded · range_source fallback");
  // 범위 폼은 안내 안에 있고 실제 폼(쪽 입력·담당자·확정·절 후보)이다.
  const form = block.getByRole("region", { name: "개요 범위 확인" });
  await expect(form.getByLabel("시작 쪽")).toBeVisible();
  await expect(form.getByRole("button", { name: "범위 확정" })).toBeVisible();
  await expect(form.getByRole("button", { name: /^절 제목에서 고르기 \(후보 \d+개\)$/ })).toBeVisible();
  // 실제 사유가 있는 건에 선택기 탓 문장을 적지 않는다. 종전 알림 줄도 없다.
  await expect(page.locator(".ps-record")).not.toContainText("사유 코드 없음");
  await expect(page.locator(".ps-record")).not.toContainText("결정적 선택기");
  await expect(page.locator("#ps-tasks .ps-notices")).toHaveCount(0);
  await expectClosedFold(page, "개요 실패 · 범위 확정 필요");
});

test("c1 범위 폼은 종전처럼 쪽 범위를 저장하고 개요를 다시 읽는다", async ({ page }) => {
  await mockProblemDetail(page, states.c1);
  const posts: unknown[] = [];
  let overviewCalls = 0;
  await page.route("**/api/pre-specs/991/overview", (route) => { overviewCalls += 1; return route.fulfill({ json: states.c1.envelope }); });
  await page.route("**/api/pre-specs/991/overview/range-confirmations", async (route) => {
    posts.push(route.request().postDataJSON());
    await route.fulfill({ status: 201, json: { run_id: "00000000-0000-0000-0000-000000000901", attempt_enqueued: true, page_start: 7, page_end: 12 } });
  });
  await page.goto("/pre-specs/991");
  const form = notice(page).getByRole("region", { name: "개요 범위 확인" });
  await form.getByLabel("시작 쪽").fill("7");
  await form.getByLabel("시작 쪽").press("Enter");
  await form.getByLabel("끝 쪽").fill("12");
  await form.getByLabel("끝 쪽").press("Enter");
  await form.getByLabel("담당자 이름 (필수)").fill("최정인");
  const before = overviewCalls;
  await form.getByRole("button", { name: "범위 확정" }).click();
  await expect(form.getByText("범위가 확정되었어요 · 그 범위로 개요 검토를 예약했어요")).toBeVisible();
  expect(posts).toEqual([{ page_start: 7, page_end: 12 }]);
  await expect.poll(() => overviewCalls).toBeGreaterThan(before);
});

test("c1 자동 선택 범위는 위치 문장 없이 '자동으로 고른 범위'라고 말한다", async ({ page }) => {
  const autoRun = { ...capacityRun, range_source: "auto" as const };
  await mockProblemDetail(page, { ...states.c1, envelope: overviewEnvelopeFixture(991, autoRun, [autoRun], { range_review: pendingRange(autoRun, 123) }) });
  await page.goto("/pre-specs/991");
  await expect(page.getByTestId("pre-spec-problem-reason")).toHaveText(
    "자동으로 고른 범위 7~49쪽(전체 123쪽)이 한 번에 읽을 수 있는 분량보다 많았어요.",
  );
});

test("c2 개요 보류: 실패 문장을 그대로 보이고 근거 쪽 PDF 링크와 다른 범위 폼 토글을 둔다", async ({ page }) => {
  await mockProblemDetail(page, states.c2);
  await page.goto("/pre-specs/991");
  const block = notice(page);
  await expect(block).toHaveAttribute("data-kind", "overview_draft_held");
  await expect(block.locator(".ps-problem-lead strong")).toHaveText("개요 초안을 보류했어요. 원문과 맞지 않는 문장이 있어요");
  await expect(page.getByTestId("pre-spec-problem-reason")).toHaveText(
    "3~5쪽을 읽고 초안을 만들었어요. 초안 문장을 원문과 대조했더니 맞지 않는 문장이 있었어요. 맞지 않는 문장은 1개예요.",
  );
  const claims = block.getByRole("list", { name: "원문과 맞지 않는 문장" });
  await expect(claims.locator("blockquote")).toHaveText(heldClaimText);
  await expect(claims).toContainText("근거로 든 쪽 5쪽 · 근거 부족 · 그 쪽에서 이 내용을 찾지 못했어요");
  // 완료 개요의 `PDF n페이지 ↗`와 같은 주소(이 run의 고정 스냅샷 PDF)다.
  await expect(block.getByRole("link", { name: "PDF 5페이지 열기 ↗" })).toHaveAttribute(
    "href", `/api/pre-specs/991/overview/runs/${heldRun.id}/pdf#page=5`,
  );
  // 범위 폼은 눌렀을 때만 열린다.
  const rerun = block.getByRole("button", { name: "다른 범위로 다시 실행하기" });
  await expect(rerun).toHaveAttribute("aria-expanded", "false");
  await expect(block.getByRole("region", { name: "개요 범위 확인" })).toHaveCount(0);
  await rerun.click();
  await expect(block.getByRole("region", { name: "개요 범위 확인" }).getByLabel("시작 쪽")).toBeVisible();
  await expect(block).toContainText("이전 범위 3~5쪽 · 전체 117쪽");
  await expect(block.locator(".ps-problem-codes")).toHaveText("semantic_review_failed · needs_human_review · insufficient_evidence");
  await expect(page.locator(".ps-record")).not.toContainText("결정적 선택기");
  await expectClosedFold(page, "개요 보류 · 원문 대조 확인 필요");
});

test("c2 실패 문장 목록이 비면 개수를 지어내지 않는다", async ({ page }) => {
  const emptyRun = { ...heldRun, failed_claims: [] };
  await mockProblemDetail(page, { ...states.c2, envelope: overviewEnvelopeFixture(991, emptyRun, [emptyRun], { range_review: pendingRange(emptyRun, 117) }) });
  await page.goto("/pre-specs/991");
  await expect(page.getByTestId("pre-spec-problem-reason")).toContainText("맞지 않는 문장 목록은 비어 있어요.");
  await expect(page.getByTestId("pre-spec-problem-reason")).not.toContainText(/맞지 않는 문장은 \d+개/);
  await expect(notice(page).getByRole("list", { name: "원문과 맞지 않는 문장" })).toHaveCount(0);
  await expect(notice(page).getByRole("link", { name: /PDF \d+페이지 열기/ })).toHaveCount(0);
});

for (const [code, sentence] of [
  ["provider_http_error", "모델 서버에 요청했지만 오류 응답을 받았어요."],
  ["brand_new_failure_code", "사유 코드 brand_new_failure_code."],
] as const) {
  test(`개요 실패 ${code}: 고정 문장 또는 코드 그대로, 다시 실행 단추는 없다`, async ({ page }) => {
    const run = { ...capacityRun, reason_codes: [code], range_source: "auto" as const, call_count: 1 };
    await mockProblemDetail(page, { ...states.c1, envelope: overviewEnvelopeFixture(991, run, [run], { range_review: pendingRange(run, 123) }) });
    await page.goto("/pre-specs/991");
    const block = notice(page);
    await expect(block).toHaveAttribute("data-kind", "overview_run_problem");
    await expect(block.locator(".ps-problem-lead strong")).toHaveText("개요를 만들지 못했어요");
    await expect(page.getByTestId("pre-spec-problem-reason")).toHaveText(sentence);
    await expect(block.locator(".ps-problem-codes")).toContainText(code);
    // 제품에 없는 재시도는 만들지 않는다. 다시 실행하는 길은 범위 확정 폼 하나다.
    await expect(page.getByRole("button", { name: /재시도|다시 시도|다시 실행$/ })).toHaveCount(0);
    await block.getByRole("button", { name: "다른 범위로 다시 실행하기" }).click();
    await expect(block.getByRole("region", { name: "개요 범위 확인" }).getByRole("button", { name: "범위 확정" })).toBeVisible();
    await expectClosedFold(page, "개요 실패 · 사유 확인 필요");
  });
}

test("c1 열린 처리 상태는 마지막 실행 블록이 먼저이고 나머지는 한 번 더 접혀 있다", async ({ page }) => {
  await mockProblemDetail(page, states.c1);
  await page.goto("/pre-specs/991");
  const toggle = await expectClosedFold(page, "개요 실패 · 범위 확정 필요");
  await toggle.click();
  const body = page.locator("#ps-process-body");
  await expect(body.locator("#ps-record-run").getByRole("region", { name: "현재 개요 검토" })).toContainText("입력 용량 초과로 미실행");
  const rest = body.getByRole("button", { name: "나머지 기술 정보 보기" });
  await expect(rest).toHaveAttribute("aria-expanded", "false");
  await expect(body.locator(".pre-spec-auto-steps, #ps-record-history, #ps-record-documents")).toHaveCount(0);
  await rest.click();
  // 지우지 않고 옮겼다: 자동 준비 단계·문서 준비·처리 이력·기술 정보가 그대로 있다.
  const restBody = page.locator("#ps-process-rest-body");
  await expect(restBody.locator(".pre-spec-auto-steps")).toBeVisible();
  await expect(restBody.getByRole("button", { name: /^문서 준비 (열기|닫기)$/ })).toBeVisible();
  await expect(restBody.locator("#ps-record-history")).toBeVisible();
  await expect(restBody.getByRole("button", { name: /^기술 정보 · / })).toBeVisible();
  // 현재 실행은 처리 이력에서 빠져 먼저 보이는 블록에만 있다(두 번 그리지 않는다).
  await expect(page.getByRole("region", { name: "현재 개요 검토" })).toHaveCount(1);
});

test("c3 문서 준비 막힘(OCR): 파일 이름과 고정 문장, `문서 준비 열기`가 구역을 열고 패널로 옮긴다", async ({ page }) => {
  await mockProblemDetail(page, states.c3);
  await page.goto("/pre-specs/991");
  const block = notice(page);
  await expect(block).toHaveAttribute("data-kind", "document_blocked");
  await expect(block.locator(".ps-problem-lead strong")).toHaveText("문서 준비가 멈췄어요. 첨부 문서를 사람이 확인해야 해요");
  await expect(page.getByTestId("pre-spec-problem-reason")).toHaveText(
    "제안요청서-스캔본.pdf에서 첨부 문서의 글자 인식(OCR)이나 쪽 구조를 자동으로 확정하지 못했어요.",
  );
  await expect(block.locator(".ps-problem-codes")).toHaveText("ocr_issue");
  await expect(page.locator("#ps-tasks .pre-spec-overview-waiting")).toHaveCount(0);
  await expectClosedFold(page, "문서 준비 막힘 · 문서 확인 필요");

  await block.getByRole("button", { name: "문서 준비 열기" }).click();
  await expect(page.locator("#ps-process > .ps-fold-head .ps-fold-toggle")).toHaveAttribute("aria-expanded", "true");
  const documents = page.locator("#ps-process-body #ps-record-documents");
  await expect(documents).toBeVisible();
  await expect(documents).toBeFocused();
  await expect(page.locator("#ps-process-body").getByRole("button", { name: "문서 준비 닫기" })).toHaveAttribute("aria-expanded", "true");
  await expect(documents.locator("*").first()).toBeVisible();
  await expect(page.locator("#ps-process-body").getByRole("button", { name: "나머지 기술 정보 보기" })).toBeVisible();
});

test("c3 받지 못한 첨부·모르는 차단 코드는 서버 건수·코드를 그대로 쓴다", async ({ page }) => {
  const missing = {
    ...states.c3,
    item: { ...states.c3.item, document: { attachments: 4, "완료": 2, "대기": 0, "진행": 0, "차단": 1, "실패": 1 } },
    bundle: { ...states.c3.bundle, issues: [
      { ...states.c3.bundle.issues[0], issue_id: "bytes", code: "attachment_bytes_missing", document_version_id: null },
      { ...states.c3.bundle.issues[0], issue_id: "odd", code: "brand_new_issue" },
    ] },
  };
  await mockProblemDetail(page, missing);
  await page.goto("/pre-specs/991");
  await expect(notice(page).locator(".ps-problem-lead strong")).toHaveText("문서 준비가 멈췄어요. 받지 못한 첨부가 있어요");
  await expect(page.getByTestId("pre-spec-problem-reason")).toHaveText(
    "문서 준비에는 모든 첨부의 원문이 필요한데 받지 못한 첨부가 있어요. 첨부 4건 · 완료 2 · 대기 0 · 진행 0 · 차단 1 · 실패 1. 그 밖에 막힌 이유가 1가지 더 있어요.",
  );
  await expect(notice(page).locator(".ps-problem-codes")).toHaveText("attachment_bytes_missing · brand_new_issue");

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockProblemDetail(page, { ...states.c3, bundle: { ...states.c3.bundle, issues: [{ ...states.c3.bundle.issues[0], code: "brand_new_issue" }] } });
  await page.goto("/pre-specs/991");
  await expect(notice(page).locator(".ps-problem-lead strong")).toHaveText("문서 준비가 멈췄어요");
  await expect(page.getByTestId("pre-spec-problem-reason")).toHaveText("문서 준비를 막는 이유가 있어요. 사유 코드 brand_new_issue.");
  await expectClosedFold(page, "문서 준비 막힘 · 사유 확인 필요");
});

test("c4 첨부 받기 실패: 서버 건수로 말하고 원본 주소가 하나면 그 원본을 연다", async ({ page }) => {
  await mockProblemDetail(page, states.c4);
  await page.goto("/pre-specs/991");
  const block = notice(page);
  await expect(block).toHaveAttribute("data-kind", "attachments_failed");
  await expect(block.locator(".ps-problem-lead strong")).toHaveText("첨부를 받지 못해 개요를 만들 수 없어요");
  await expect(page.getByTestId("pre-spec-problem-reason")).toHaveText(
    "나라장터에서 첨부 3건을 받으려 했지만 2건이 차단되고 1건이 실패했어요. 받은 첨부가 없어 문서를 준비하지 못했어요.",
  );
  await expect(page.getByTestId("pre-spec-problem-todo")).toHaveText(
    "원본 열기로 나라장터에서 첨부를 직접 확인해 주세요. 이 화면에서는 아직 첨부를 다시 받을 수 없어요.",
  );
  await expect(block.getByRole("link", { name: "원본 열기 ↗" })).toHaveAttribute("href", "https://www.g2b.go.kr/fixture/attachment-7001");
  await expect(block.locator(".ps-problem-codes")).toHaveText("attachments_failed · 첨부 3건 · 차단 2 · 실패 1");
  // 다시 받기 조작은 없다.
  await expect(page.getByRole("button", { name: /다시 받기/ })).toHaveCount(0);
  const toggle = await expectClosedFold(page, "첨부 받기 실패 · 3건 중 차단 2 · 실패 1");
  await toggle.click();
  // 먼저 보이는 것은 첨부 취득 단계와 집계다. 문서 준비 패널은 나머지 뒤에 있다.
  const body = page.locator("#ps-process-body");
  await expect(body.locator(".pre-spec-auto-steps")).toBeVisible();
  await expect(body.getByRole("heading", { name: "첨부 원문 취득 집계", exact: true })).toBeVisible();
  await expect(body.locator("#ps-record-documents")).toHaveCount(0);
});

test("c4 원본 주소가 여럿이면 원문·첨부 구역으로 안내한다", async ({ page }) => {
  const second = { ...states.c4.notice.attachments[0], id: 7002, url: "https://www.g2b.go.kr/fixture/attachment-7002" };
  await mockProblemDetail(page, { ...states.c4, notice: { attachments: [states.c4.notice.attachments[0], second] } });
  await page.goto("/pre-specs/991");
  await expect(notice(page).getByRole("link", { name: "원본 열기 ↗" })).toHaveCount(0);
  await expect(notice(page).getByRole("link", { name: "원문·첨부에서 첨부 보기" })).toHaveAttribute("href", "#ps-evidence");
});

test("c5 개요 대기: 확정 묶음·실행 없음·기능 켜짐·마감 전에만 대기라고 말한다", async ({ page }) => {
  await mockProblemDetail(page, states.c5);
  await page.goto("/pre-specs/991");
  const block = notice(page);
  await expect(block).toHaveAttribute("data-kind", "overview_waiting");
  await expect(block.locator(".ps-problem-lead")).toContainText("개요 대기");
  await expect(block.locator(".ps-problem-lead strong")).toHaveText("개요 실행을 기다리고 있어요");
  await expect(page.getByTestId("pre-spec-problem-reason")).toHaveText("원문 준비는 끝났고 개요는 아직 시작하지 않았어요.");
  await expect(page.getByTestId("pre-spec-problem-todo")).toHaveText(
    "따로 할 일은 없어요. 개요는 의견 마감 전이거나 추적 중인 사전규격에서 자동으로 진행해요. 마감이 지난 건은 추적을 시작하면 진행해요.",
  );
  await expect(block.locator("a, button")).toHaveCount(0);
  const toggle = await expectClosedFold(page, "원문 준비 완료 · 개요 대기");
  await toggle.click();
  await expect(page.locator("#ps-process-body .pre-spec-auto-steps")).toBeVisible();
  await expect(page.locator("#ps-process-body").getByRole("button", { name: "나머지 기술 정보 보기" })).toBeVisible();
});

for (const [label, change] of [
  ["의견 마감이 지난 건", { item: { ...states.c5.item, deadline_at: PAST_DEADLINE }, notice: { deadline_at: PAST_DEADLINE } }],
  ["개요 자동 검토가 꺼진 환경", { overviewFlag: false }],
] as const) {
  test(`c5가 확실하지 않은 ${label}은 종전 문구를 그대로 쓴다`, async ({ page }) => {
    await mockProblemDetail(page, { ...states.c5, ...change });
    await page.goto("/pre-specs/991");
    await expect(page.locator(".pre-spec-overview-waiting")).toBeVisible();
    await settleProcessSection(page);
    await expect(notice(page)).toHaveCount(0);
  });
}

for (const [key, fixture] of Object.entries(states)) {
  test(`${key}: 주 버튼 하나, 13px 미만 글자 없음, 1280·1440 가로 넘침 없음`, async ({ page }) => {
    await mockProblemDetail(page, fixture);
    for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
      await page.setViewportSize(viewport);
      await page.goto("/pre-specs/991");
      await expect(notice(page)).toBeVisible();
      await settleProcessSection(page);
      // c2·그 밖의 개요 문제는 접힌 범위 폼까지 열어 본다.
      const rerun = notice(page).getByRole("button", { name: "다른 범위로 다시 실행하기" });
      if (await rerun.count()) await rerun.click();
      // 굵은 줄·이유·할 일에 내부 용어를 쓰지 않는다(사유 코드 줄은 원 코드 그대로라 뺀다).
      const words = (await notice(page).locator(".ps-problem-lead, .ps-problem-line").allInnerTexts()).join(" ");
      for (const jargon of ["묶음", "issue", "bundle", "결정적 선택기"]) expect(words, `${key}: ${jargon}`).not.toContain(jargon);
      await expect(page.locator(".astryx-button.primary")).toHaveCount(1);
      await expect(page.locator(".astryx-button.primary")).toHaveText("추적 시작하기");
      const small = await notice(page).evaluate((root) => {
        const found: string[] = [];
        for (const element of [root, ...root.querySelectorAll("*")]) {
          const own = [...element.childNodes].some((child) => child.nodeType === Node.TEXT_NODE && child.textContent?.trim());
          if (!own || (element as HTMLElement).offsetParent === null) continue;
          const size = Number.parseFloat(getComputedStyle(element).fontSize);
          if (size < 13) found.push(`${size}px ${element.textContent?.trim().slice(0, 30)}`);
        }
        return found;
      });
      expect(small, `${key} @ ${viewport.width}`).toEqual([]);
      const overflow = await page.evaluate(() => ({
        root: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        canvas: (() => { const canvas = document.querySelector(".page-canvas"); return canvas ? canvas.scrollWidth - canvas.clientWidth : 0; })(),
      }));
      expect(overflow, `${key} @ ${viewport.width}`).toEqual({ root: 0, canvas: 0 });
    }
  });
}
