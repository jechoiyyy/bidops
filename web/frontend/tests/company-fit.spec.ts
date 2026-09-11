import { expect, test } from "@playwright/test";
import { mockApi } from "./api-mock";
import type { CompanyFitResponse } from "../src/lib/types";

const explanation = "공고는 감리 과업이며 회사 프로필의 구축 업무와 수행 역할이 다릅니다. 감리 대상 사업에 인공지능 플랫폼 구축과 개발이 포함되어 있어도 이번 계약의 수행 범위를 구축 업무로 해석할 수 없습니다. 인용된 회사 정보만으로 감리 수행 자격이나 실적의 유무까지 확정하지 않으며, 해당 항목은 별도 확인이 필요합니다.";

function response(): CompanyFitResponse {
  return { schema_version: "bidops.prespec-company-fit.v1", notice_id: 991, automation_enabled: true,
    auto_deep_review_reason: "company_fit_mismatch", deep_review_id: null,
    attempts: [{ id: "fit-1", notice_id: 991, status: "completed", error_code: null, is_current: true,
      overview_kind: "overview_run", overview_id: "overview-1", document_version_id: "document-1", overview_sha256: "a".repeat(64),
      profile_version_id: "profile-1", profile_sha256: "b".repeat(64), policy_digest: "c".repeat(64),
      model_name: "test-fit", model_revision: "d".repeat(64), prompt_version: "prespec-company-fit-v1", quality_status: "unmeasured_reference",
      created_at: "2026-09-08T00:00:00Z", completed_at: "2026-09-08T00:00:10Z", prompt_tokens: null, output_tokens: 0, latency_ms: 10000,
      notice_facts: [{ ref: "task:0", text: "본 계약의 과업은 정보시스템 감리입니다.", pages: [3], block_key: null }],
      company_facts: [{ ref: "company:0", fact_key: "업무 범위", status: "confirmed", value: "합성 기업의 업무 시스템 구축" }],
      result: { schema_version: "bidops.prespec-company-fit-result.v1", decision: "mismatch", summary: "실제 과업과 회사 업무 범위가 다릅니다.",
        reasons: [{ kind: "scope_mismatch", explanation, notice_refs: ["task:0"], company_refs: ["company:0"] }],
        verification_items: ["감리 수행 범위는 사람이 확인해야 합니다."] } }] };
}

for (const width of [1280, 1440]) {
  test(`fit mismatch reasons and frozen evidence on both details at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1280 ? 800 : 900 });
    await mockApi(page);
    await page.route("**/api/pre-specs/991/company-fit", route => route.fulfill({ json: response() }));
    for (const path of ["/pre-specs?notice_pk=991", "/pre-specs/991"]) {
      await page.goto(path);
      const section = page.getByRole("region", { name: "회사 업무 부합 여부" });
      // 상세는 판정 라벨·요약·품질을 `현재 판단` 카드에 두고, 사유·근거는 접힌 자리에 둔다.
      const isRecord = path === "/pre-specs/991";
      const verdict = isRecord ? page.locator(".ps-vbox").filter({ hasText: "회사 핏" }) : section;
      await expect(verdict.getByText("불일치", { exact: true })).toBeVisible();
      await expect(verdict.getByText("실제 과업과 회사 업무 범위가 다릅니다.")).toBeVisible();
      await expect(verdict.getByText("참조 실행 · 품질 미측정")).toBeVisible();
      if (isRecord) await section.getByText("판단 사유 1개와 근거 보기", { exact: true }).click();
      await expect(section.getByText(explanation)).toBeVisible();
      await expect(section.getByText("본 계약의 과업은 정보시스템 감리입니다.")).toBeVisible();
      await expect(section.getByRole("link", { name: "PDF 3페이지 ↗" })).toHaveAttribute("href", /\/overview\/runs\/overview-1\/pdf#page=3$/);
      const executionInfo = section.getByText("판정 기준과 실행 정보", { exact: true });
      await executionInfo.focus();
      await expect(executionInfo).toBeFocused();
      await executionInfo.press("Enter");
      await expect(section.getByText("입력 토큰 · 미측정 / 출력 토큰 · 0 / 소요 시간 · 10000ms")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      if (width === 1440 && path === "/pre-specs/991") await section.screenshot({ path: "/tmp/bidops-company-fit-1440.png" });
    }
  });
}

test("unknown, stale, no result and failed states stay distinct", async ({ page }) => {
  await mockApi(page);
  const data = response();
  data.attempts[0].result!.decision = "unknown";
  data.attempts[0].result!.summary = "회사 정보가 부족합니다.";
  data.attempts[0].result!.reasons[0].kind = "information_gap";
  data.attempts[0].result!.reasons[0].company_refs = [];
  data.attempts[0].is_current = false;
  data.auto_deep_review_reason = "company_fit_stale";
  data.deep_review_id = "review-existing";
  await page.route("**/api/pre-specs/991/company-fit", route => route.fulfill({ json: data }));
  await page.goto("/pre-specs/991");
  const section = page.getByRole("region", { name: "회사 업무 부합 여부" });
  // 상세는 판정 라벨·요약·stale 안내를 `현재 판단` 카드에 두고, 사유·근거는 접힌 자리에 둔다.
  const verdict = page.locator(".ps-vbox").filter({ hasText: "회사 핏" });
  await expect(verdict.getByText("판단 보류 · 정보 부족", { exact: true })).toBeVisible();
  await expect(verdict.getByText("이전 입력 기준의 판정입니다.", { exact: false })).toBeVisible();
  await section.getByText("판단 사유 1개와 근거 보기", { exact: true }).click();
  await expect(section.getByText("인용된 회사 정보가 없습니다. 역량이 없다는 뜻이 아닙니다.")).toBeVisible();
  await expect(section.getByRole("link", { name: "심층 검토 열기" })).toHaveAttribute("href", "/deep-reviews/review-existing");
  data.attempts[0].result!.decision = "matched";
  data.attempts[0].result!.summary = "공고 과업과 확인된 회사 업무가 부합합니다.";
  data.attempts[0].result!.reasons = [];
  data.attempts[0].is_current = true;
  await page.reload();
  await expect(verdict.getByText("부합", { exact: true })).toBeVisible();
  await section.getByText("판단 사유 0개와 근거 보기", { exact: true }).click();
  await expect(section.getByText("상세 사유가 저장되지 않았습니다.")).toBeVisible();
  data.attempts[0].result = null;
  data.attempts[0].status = "needs_human_review";
  await page.reload();
  await expect(verdict.getByText("검증 실패 · 사람 확인 필요", { exact: true })).toBeVisible();
  await expect(verdict.getByText("검증을 통과한 판정 근거가 없어 결과를 사용할 수 없습니다.")).toBeVisible();
  data.attempts[0].status = "failed";
  await page.reload();
  await expect(verdict.getByText("실행 실패", { exact: true })).toBeVisible();
  await expect(verdict.getByText("판정 결과가 생성되지 않았습니다. 불일치로 처리하지 않습니다.")).toBeVisible();
  data.attempts = [];
  await page.reload();
  await expect(section.getByText("저장된 회사 핏 판정이 없습니다. 불일치로 판단한 상태가 아닙니다.")).toBeVisible();
});

test("failed fetch and wrong notice response show safe errors", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/pre-specs/991/company-fit", route => route.fulfill({ status: 503, json: { error: { code: "unavailable" } } }));
  await page.goto("/pre-specs/991");
  await expect(page.getByText("회사 핏 판정을 불러오지 못했습니다.")).toBeVisible();
  const data = response(); data.notice_id = 992;
  await page.route("**/api/pre-specs/991/company-fit", route => route.fulfill({ json: data }));
  await page.getByRole("button", { name: "회사 핏 다시 불러오기" }).click();
  await expect(page.getByText("판정 응답의 공고 또는 구조가 일치하지 않아 표시하지 않습니다.")).toBeVisible();
});
