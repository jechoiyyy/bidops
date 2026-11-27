import { mkdir } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockPreSpecs } from "./api-mock";
import { CARD_SHA256, CARD_VERSION } from "./fixtures/company-fit-card";
import type { CompanyFitResponse } from "../src/lib/types";

const explanation = "공고는 감리 과업이며 회사 프로필의 구축 업무와 수행 역할이 달라요. 감리 대상 사업에 인공지능 플랫폼 구축과 개발이 포함되어 있어도 이번 계약의 수행 범위를 구축 업무로 해석할 수 없어요. 인용된 회사 정보만으로 감리 수행 자격이나 실적의 유무까지 확정하지 않으며, 해당 항목은 별도 확인이 필요해요.";

function response(): CompanyFitResponse {
  // v2(PS-01 C5): 프로필 lineage 판정은 카드 필드가 null이고 모드는 꺼져 있다.
  return { schema_version: "bidops.prespec-company-fit.v2", notice_id: 991, automation_enabled: true,
    mode: { mode: "off", effective: false, reason_code: "switch_off", card_version: null, card_sha256: null, prompt_version: "prespec-company-fit-v3.1" },
    engine_suggested: false,
    auto_deep_review_reason: "company_fit_mismatch", deep_review_id: null,
    attempts: [{ id: "fit-1", notice_id: 991, status: "completed", error_code: null, is_current: true,
      lineage: "profile", card_version: null, card_sha256: null, judged_by: null, company_fact_labels: null,
      overview_kind: "overview_run", overview_id: "overview-1", document_version_id: "document-1", overview_sha256: "a".repeat(64),
      profile_version_id: "profile-1", profile_sha256: "b".repeat(64), policy_digest: "c".repeat(64),
      model_name: "test-fit", model_revision: "d".repeat(64), prompt_version: "prespec-company-fit-v1", quality_status: "unmeasured_reference",
      created_at: "2026-09-08T00:00:00Z", completed_at: "2026-09-08T00:00:10Z", prompt_tokens: null, output_tokens: 0, latency_ms: 10000,
      notice_facts: [{ ref: "task:0", text: "본 계약의 과업은 정보시스템 감리예요.", pages: [3], block_key: null }],
      company_facts: [{ ref: "company:0", fact_key: "업무 범위", status: "confirmed", value: "합성 기업의 업무 시스템 구축" }],
      result: { schema_version: "bidops.prespec-company-fit-result.v1", decision: "mismatch", summary: "실제 과업과 회사 업무 범위가 달라요.",
        reasons: [{ kind: "scope_mismatch", explanation, notice_refs: ["task:0"], company_refs: ["company:0"] }],
        verification_items: ["감리 수행 범위는 사람이 확인해야 해요."] } }] };
}

for (const width of [1280, 1440]) {
  test(`fit mismatch reasons and frozen evidence on both details at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 900 });
    await mockApi(page);
    await page.route("**/api/pre-specs/991/company-fit", route => route.fulfill({ json: response() }));
    // 회사 적합성 구역은 상세만 소유한다(docs/0915_ui-redesign/spec.md §3.1·§4 ④).
    for (const path of ["/pre-specs/991"]) {
      await page.goto(path);
      // 상세 ④의 `회사 적합성` 열은 판정·사유·근거만 갖는다. 실행 정보는 ⑥의
      // 접힌 `기술 정보` 하나로 옮겼다(docs/0915_ui-redesign/spec.md:234, ADR-0066).
      const section = page.getByRole("region", { name: "회사 업무 부합 여부" });
      await expect(section.getByText("불일치", { exact: true })).toBeVisible();
      await expect(section.getByText("실제 과업과 회사 업무 범위가 달라요.")).toBeVisible();
      // 품질 표식은 접힘과 무관하게 ④에서 그대로 보인다(지우면 안 되는 경고 ①).
      await expect(section.getByText("참조 실행 · 품질 미측정")).toBeVisible();
      await expect(section.getByText(explanation)).toBeVisible();
      await expect(section.getByText("본 계약의 과업은 정보시스템 감리예요.")).toBeVisible();
      await expect(section.getByRole("link", { name: "PDF 3페이지 ↗" })).toHaveAttribute("href", /\/overview\/runs\/overview-1\/pdf#page=3$/);
      await expect(section.getByText("판정 기준과 실행 정보")).toHaveCount(0);

      // ⑥ 접힌 곳을 펴면 같은 값이 하나도 빠지지 않고 전문으로 보인다.
      const technical = page.locator(".ps-collapsed");
      const trigger = page.getByRole("button", { name: "기술 정보 · 주장 검증 진단, 고정 입력과 식별 해시, 회사 적합성 실행 정보" });
      await expect(technical.locator(".astryx-collapsible-content")).toBeHidden();
      await trigger.click();
      const facts = technical.locator('dl[aria-label="현재 판정 실행 정보"]');
      await expect(facts).toBeVisible();
      await expect(facts).toContainText("test-fit");
      await expect(facts).toContainText("prespec-company-fit-v1");
      await expect(facts).toContainText("overview-1");
      // 식별자·해시는 8자로 줄이지 않는다(ADR-0066 결정 2).
      await expect(facts).toContainText("a".repeat(64));
      await expect(facts).toContainText("b".repeat(64));
      await expect(facts).toContainText("c".repeat(64));
      await expect(facts).toContainText("d".repeat(64));
      // 미측정·실제 0·소요 시간은 서로 다른 값으로 남는다.
      await expect(facts.locator("dd").filter({ hasText: /^미측정$/ })).toHaveCount(1);
      await expect(facts.locator("dd").filter({ hasText: /^0$/ })).toHaveCount(1);
      await expect(facts).toContainText("10000ms");
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      if (width === 1440 && path === "/pre-specs/991") await section.screenshot({ path: "/tmp/bidops-company-fit-1440.png" });
    }
  });
}

test("unknown, stale, no result and failed states stay distinct", async ({ page }) => {
  await mockApi(page);
  const data = response();
  data.attempts[0].result!.decision = "unknown";
  data.attempts[0].result!.summary = "회사 정보가 부족해요.";
  data.attempts[0].result!.reasons[0].kind = "information_gap";
  data.attempts[0].result!.reasons[0].company_refs = [];
  data.attempts[0].is_current = false;
  data.auto_deep_review_reason = "company_fit_stale";
  data.deep_review_id = "review-existing";
  await page.route("**/api/pre-specs/991/company-fit", route => route.fulfill({ json: data }));
  await page.goto("/pre-specs/991");
  const section = page.getByRole("region", { name: "회사 업무 부합 여부" });
  await expect(section.getByText("판단 보류 · 정보 부족", { exact: true })).toBeVisible();
  await expect(section.getByText("이전 입력 기준의 판정이에요.", { exact: false })).toBeVisible();
  await expect(section.getByText("인용된 회사 정보가 없어요. 역량이 없다는 뜻이 아니에요.")).toBeVisible();
  // 2026-11-19: 응답에 기존 심층 검토 id가 있어도 그 진입점은 그리지 않는다(사전규격 단계 수정안 §3 B).
  await expect(section.getByRole("link", { name: "심층 검토 열기" })).toHaveCount(0);
  await expect(section.locator('a[href^="/deep-reviews/"]')).toHaveCount(0);
  data.attempts[0].result!.decision = "matched";
  data.attempts[0].result!.summary = "공고 과업과 확인된 회사 업무가 부합해요.";
  data.attempts[0].result!.reasons = [];
  data.attempts[0].is_current = true;
  await page.reload();
  await expect(section.getByText("부합", { exact: true })).toBeVisible();
  await expect(section.getByText("상세 사유가 저장되지 않았어요.")).toBeVisible();
  data.attempts[0].result = null;
  data.attempts[0].status = "needs_human_review";
  await page.reload();
  await expect(section.getByText("검증 실패 · 사람 확인 필요", { exact: true })).toBeVisible();
  await expect(section.getByText("검증을 통과한 판정 근거가 없어 결과를 사용할 수 없어요.")).toBeVisible();
  data.attempts[0].status = "failed";
  await page.reload();
  await expect(section.getByText("실행 실패", { exact: true })).toBeVisible();
  await expect(section.getByText("판정 결과가 생성되지 않았어요. 불일치로 처리하지 않아요.")).toBeVisible();
  data.attempts = [];
  await page.reload();
  // 문장은 짧아졌지만 `판정 없음 ≠ 불일치`라는 뜻은 그대로 남는다(ADR-0055 D8).
  await expect(section.getByText("회사 적합성 판정 없음 · 불일치 아님")).toBeVisible();
});

// 0915 spec §4 ⑥: 접힌 `기술 정보`는 실패·사람 확인 상태면 기본으로 열린다.
// 회사 적합성 실행 정보가 이 접힌 곳으로 들어왔으므로 회사 적합성의 실패·검증
// 실패도 같은 규칙을 그대로 따른다(ADR-0066 결정 5).
for (const status of ["failed", "needs_human_review"] as const) {
  test(`회사 적합성 ${status}이면 ⑥ 기술 정보가 기본으로 열린다`, async ({ page }) => {
    await mockApi(page);
    const data = response();
    data.attempts[0].status = status;
    data.attempts[0].result = null;
    data.attempts[0].error_code = "model_unavailable";
    await page.route("**/api/pre-specs/991/company-fit", route => route.fulfill({ json: data }));
    await page.goto("/pre-specs/991");
    const technical = page.locator(".ps-collapsed");
    await expect(technical.locator('dl[aria-label="현재 판정 실행 정보"]')).toBeVisible();
    // 처리 사유 코드는 서버가 정한 안전 코드다. 그대로 보여 준다.
    await expect(technical).toContainText("model_unavailable");
  });
}

test("failed fetch and wrong notice response show safe errors", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/pre-specs/991/company-fit", route => route.fulfill({ status: 503, json: { error: { code: "unavailable" } } }));
  await page.goto("/pre-specs/991");
  await expect(page.getByText("회사 적합성 판정을 불러오지 못했어요.")).toBeVisible();
  const data = response(); data.notice_id = 992;
  await page.route("**/api/pre-specs/991/company-fit", route => route.fulfill({ json: data }));
  await page.getByRole("button", { name: "회사 적합성 다시 불러오기" }).click();
  await expect(page.getByText("판정 응답의 공고 또는 구조가 일치하지 않아 표시하지 않아요.")).toBeVisible();
});

// ── T12: 사업 범위 카드 lineage(PS-01) 상세 ─────────────────────────────────
// mock 스위치 `?fit=`(tests/fixtures/company-fit-card.ts)가 카드 lineage 판정을 고른다.
const ENGINE_SUGGESTION = "엔진 분석 추천: 회사 사업 범위와 맞는 사업입니다. 분석 요청은 담당자가 정합니다.";
const VIEWPORTS = [{ width: 1280, height: 800 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }] as const;

async function openCardFit(page: Page, query: string) {
  await mockApi(page);
  await mockPreSpecs(page);
  await page.goto(`/pre-specs/991?${query}`);
  const section = page.getByRole("region", { name: "회사 업무 부합 여부" });
  // 로딩 자리(`불러오는 중`)가 아니라 판정이 그려진 뒤를 본다.
  await expect(section.locator(".company-fit-heading strong")).toBeVisible();
  return section;
}

async function expectNoHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
}

for (const viewport of VIEWPORTS) {
  test(`T12 카드 부합 판정은 범위·정책 이름·표식·추천을 보이고 기술 정보에 모드를 읽기로 둔다 (${viewport.width})`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const section = await openCardFit(page, "fit=matched");
    await expect(section.getByText("부합", { exact: true })).toBeVisible();
    await expect(section.getByText("공고 과업이 회사 사업 범위의 데이터 플랫폼 구축과 맞아요.")).toBeVisible();
    await expect(section.getByText("기존 데이터를 새 플랫폼으로 이관·검증하는 과업이 데이터 플랫폼 구축 범위에 들어요.")).toBeVisible();
    // 카드 근거는 이름만 보인다. value JSON(범위 summary)은 화면에 싣지 않는다.
    await expect(section.getByText("데이터 플랫폼 구축·운영", { exact: true })).toBeVisible();
    await expect(section.getByText("상주 조건", { exact: true })).toBeVisible();
    await expect(section).not.toContainText("공공 데이터 수집·이관·분석 플랫폼을 구축하고 운영한다.");
    await expect(section).not.toContainText("{");
    await expect(section.getByText("판정 시점에 고정한 사업 범위 카드 기준", { exact: true }).first()).toBeVisible();
    await expect(section.getByText("참조 실행 · 품질 미측정")).toBeVisible();
    await expect(section.getByText("Claude 판정 · 참조")).toHaveCount(0);
    // 추천은 한 줄 문장이고 버튼·링크가 없다.
    const suggestion = section.getByText(ENGINE_SUGGESTION, { exact: true });
    await expect(suggestion).toBeVisible();
    await expect(suggestion.locator("a, button")).toHaveCount(0);
    await expect(section.getByRole("button", { name: /분석/ })).toHaveCount(0);

    const technical = page.locator(".ps-collapsed");
    await page.getByRole("button", { name: "기술 정보 · 주장 검증 진단, 고정 입력과 식별 해시, 회사 적합성 실행 정보" }).click();
    const mode = technical.locator('dl[aria-label="회사 핏 모드"]');
    await expect(mode).toBeVisible();
    await expect(mode).toContainText("추천");
    await expect(mode).toContainText("적용 중");
    await expect(mode).toContainText(CARD_VERSION);
    await expect(mode).toContainText(CARD_SHA256);
    await expect(mode).toContainText("prespec-company-fit-v3.1");
    await expect(mode.getByRole("button")).toHaveCount(0);
    await expect(mode.locator("input, select")).toHaveCount(0);
    const facts = technical.locator('dl[aria-label="현재 판정 실행 정보"]');
    await expect(facts).toContainText("사업 범위 카드");
    await expect(facts).toContainText(CARD_SHA256);
    await expect(facts).not.toContainText("회사 프로필 버전");
    await expectNoHorizontalOverflow(page);

    const shotDir = process.env.FIT_SHOT_DIR;
    if (shotDir && viewport.width === 1280) {
      await mkdir(shotDir, { recursive: true });
      await page.evaluate(() => document.fonts.ready);
      // 본문은 셸 안쪽에서 스크롤한다. 회사 관련성 구역 머리를 화면 위쪽에 두고 찍는다.
      await section.evaluate((element) => element.closest("section.ps-tri-col, section")?.parentElement?.scrollIntoView({ block: "start" }));
      await page.screenshot({ path: `${shotDir}/detail-matched-1280.png` });
    }
  });

  test(`T12 판단 보류·불일치에는 추천이 없고 판정 전은 진행 상태만 보인다 (${viewport.width})`, async ({ page }) => {
    await page.setViewportSize(viewport);
    let section = await openCardFit(page, "fit=unknown");
    await expect(section.getByText("판단 보류 · 정보 부족", { exact: true })).toBeVisible();
    await expect(section.getByText("섞인 사업 판단", { exact: true })).toBeVisible();
    await expect(section.getByText(ENGINE_SUGGESTION)).toHaveCount(0);

    await page.goto("/pre-specs/991?fit=mismatch");
    section = page.getByRole("region", { name: "회사 업무 부합 여부" });
    await expect(section.getByText("불일치", { exact: true })).toBeVisible();
    await expect(section.getByText("수행하지 않는 사업", { exact: true })).toBeVisible();
    await expect(section.getByText(ENGINE_SUGGESTION)).toHaveCount(0);

    await page.goto("/pre-specs/991?fit=pending");
    section = page.getByRole("region", { name: "회사 업무 부합 여부" });
    await expect(section.getByText("판정 중", { exact: true })).toBeVisible();
    await expect(section.getByText("검증된 판정이 생성되면 과업과 회사 정보의 대조 근거를 표시해요.")).toBeVisible();
    await expect(section.locator(".company-fit-reasons")).toHaveCount(0);
    await expect(section.locator(".company-fit-summary")).toHaveCount(0);
    await expect(section.getByText(ENGINE_SUGGESTION)).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  });
}

test("T12 가져온 Claude 참조 판정은 품질 표식 옆에 `Claude 판정 · 참조`로 구분된다", async ({ page }) => {
  const section = await openCardFit(page, "fit=matched&judge=claude");
  const heading = section.locator(".company-fit-heading");
  await expect(heading.getByText("참조 실행 · 품질 미측정")).toBeVisible();
  await expect(heading.getByText("Claude 판정 · 참조", { exact: true })).toBeVisible();
  await expect(section.getByText("판단 사유 1 · Claude 참조 의견")).toBeVisible();
  await expect(section.getByText("모델 의견", { exact: false })).toHaveCount(0);
  await page.getByRole("button", { name: "기술 정보 · 주장 검증 진단, 고정 입력과 식별 해시, 회사 적합성 실행 정보" }).click();
  const facts = page.locator('.ps-collapsed dl[aria-label="현재 판정 실행 정보"]');
  await expect(facts).toContainText("claude-reference-judgment");
  await expect(facts).toContainText("Claude 판정 · 참조");
});

test("T12 스위치가 없으면 v2 기본 응답(판정 없음·자동 판정 비활성)을 그대로 읽는다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecs(page);
  await page.goto("/pre-specs/991");
  await expect(page.getByText("판정 응답의 공고 또는 구조가 일치하지 않아 표시하지 않아요.")).toHaveCount(0);
  await page.getByRole("button", { name: /^기술 정보/ }).click();
  const mode = page.locator('.ps-collapsed dl[aria-label="회사 핏 모드"]');
  await expect(mode).toContainText("꺼짐");
  await expect(mode).toContainText("적용 안 됨");
  await expect(mode).toContainText("company_fit_disabled");
});
