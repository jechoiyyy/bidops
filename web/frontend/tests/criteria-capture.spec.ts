import { test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";
import { BINDABLE_EVALUATION, POLICY_CANDIDATE, POLICY_DRAFT, mockCriteria, type CriteriaMockOptions } from "./criteria-fixtures";

/**
 * 승인된 시안과 대조하기 위한 상태 캡처.
 *
 * 게이트가 아니라 **대조용 캡처**다. 기준 이미지와 비교하지 않고 파일만 남긴다
 * (`docs/standards.md`의 픽셀 층은 게이트가 아니다). `CRITERIA_SHOTS` 환경 변수가
 * 있을 때만 돈다.
 */

const OUT = process.env.CRITERIA_SHOTS ?? "";
const WIDTHS = [
  { name: "1280", width: 1280, height: 800 },
  { name: "1440", width: 1440, height: 900 },
];

async function shot(page: Page, name: string, width: { name: string; width: number; height: number }) {
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/criteria-impl-${name}-${width.name}.png`, animations: "disabled" });
}

async function open(page: Page, path: string, options: CriteriaMockOptions = {}) {
  await mockApi(page);
  await mockCriteria(page, options);
  await page.goto(path);
}

test.skip(() => OUT === "", "CRITERIA_SHOTS 미설정");

for (const width of WIDTHS) {
  test(`판정 기준 상태 캡처 ${width.name}`, async ({ page }) => {
    await page.setViewportSize({ width: width.width, height: width.height });

    await open(page, "/profile");
    await page.getByText("사업·기술 역량").first().click();
    await shot(page, "profile", width);

    await open(page, "/profile?pstatus=unknown");
    await shot(page, "profile-unknown", width);

    await open(page, "/profile", { profile: "invalid" });
    await shot(page, "profile-invalid", width);

    await open(page, "/profile", { profile: "read-error" });
    await shot(page, "profile-error", width);

    await open(page, "/profile?pq=%EC%A1%B4%EC%9E%AC%ED%95%98%EC%A7%80+%EC%95%8A%EC%9D%8C");
    await shot(page, "profile-search-empty", width);

    await open(page, "/profile", { longTitle: true, slowMs: 4_000 });
    await shot(page, "profile-loading", width);

    await open(page, `/policies?policy=${encodeURIComponent(POLICY_CANDIDATE)}`);
    await shot(page, "policies", width);

    await open(page, `/policies?policy=${encodeURIComponent(POLICY_CANDIDATE)}&ptab=approval`);
    await shot(page, "policy-conditions", width);

    await open(page, "/policies");
    await page.locator(".crit-queue-tools").getByRole("button", { name: "새 정책 버전" }).click();
    await shot(page, "policy-create", width);

    await open(page, `/policies?policy=${encodeURIComponent(POLICY_CANDIDATE)}&ptab=approval`);
    await page.getByLabel("통과한 최신 운영 evaluation").click();
    await page.getByRole("option", { name: new RegExp(BINDABLE_EVALUATION) }).click();
    await page.locator(".crit-detail-foot").getByRole("button", { name: "정책 활성화 확인" }).click();
    await shot(page, "policy-activation-confirm", width);

    await open(page, `/policies?policy=${encodeURIComponent(POLICY_DRAFT)}&ptab=record`);
    await shot(page, "policy-record", width);

    await open(page, "/quality-gates?gate=gate-operational-held");
    await shot(page, "quality-gates", width);

    await open(page, "/quality-gates?gate=gate-model-comparison");
    await shot(page, "gate-model-comparison", width);

    await open(page, "/quality-gates?gate=gate-operational-pass&gtab=binding");
    await shot(page, "gate-binding", width);

    await open(page, "/quality-gates?gate=gate-operational-pass");
    await page.locator(".crit-detail-foot").getByRole("button", { name: "근거 리뷰 작성" }).click();
    await shot(page, "gate-review", width);

    await open(page, "/quality-gates");
    await page.locator(".crit-queue-tools").getByRole("button", { name: "새 품질 게이트" }).click();
    await page.getByLabel("검증 목적 · 필수").click();
    await shot(page, "gate-purpose-options", width);

    await open(page, "/quality-gates?gate=gate-operational-pass", { gateDetailError: "gate-operational-pass" });
    await shot(page, "gate-detail-error", width);

    await open(page, "/metrics");
    await shot(page, "metrics", width);

    await open(page, "/metrics?metric=human_agreement_rate");
    await shot(page, "metrics-unmeasured", width);

    await open(page, "/metrics", { metricsFailures: ["run-0903-a"] });
    await shot(page, "metrics-history-partial", width);

    await open(page, "/metrics");
    await page.locator(".crit-detail-foot").getByRole("button", { name: "회차 선택" }).click();
    await shot(page, "metrics-run-picker", width);
  });
}
