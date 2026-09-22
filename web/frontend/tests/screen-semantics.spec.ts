import { expect, test } from "@playwright/test";
import {
  mockDeepReviewQuality,
  mockOpportunity,
  mockPreSpecAutoDetail,
  mockPreSpecMatrix,
  mockWorkload,
} from "./api-mock";
import { installScreenFixtures } from "./screen-fixtures";

// 의미 층 — 화면이 업무 상태를 어떻게 말하는지 본다. 값 없음·미확인·계산 불가·0의
// 구분, 감사 누락의 분모를 추정하지 않기, 승인 게이트가 담당자 없이 열리지 않기가
// 여기 있다. 폭과 무관하므로 한 폭에서만 돈다.
//
// 세 층의 구분과 게이트는 `docs/standards.md`에 있다.

const RUN_ID = "20260817-20260823--20260824T090927.138116Z";
const ACTIVE_POLICY = "screening-policy.v1.20260825";
const CANDIDATE_POLICY = "screening-policy.v1.20260826";
const ACTIVE_GATE_EVALUATION = "gateeval-11111111111111111111111111111111";
const CANDIDATE_GATE_EVALUATION = "gateeval-22222222222222222222222222222222";

installScreenFixtures();

test("공통 셸이 로컬 글꼴과 기능 아이콘 접근성을 지킨다", async ({ page }) => {
  const remoteFontRequests: string[] = [];
  const localFontRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") remoteFontRequests.push(request.url());
    if (url.pathname.endsWith("/fonts/PretendardVariable.woff2")) localFontRequests.push(request.url());
  });
  await page.goto("/");
  await expect(page.locator("h1").first()).toBeVisible();
  await page.evaluate(async () => {
    await document.fonts.load('400 14px "Pretendard"');
    await document.fonts.ready;
  });

  expect(remoteFontRequests).toEqual([]);
  expect(localFontRequests.length).toBeGreaterThan(0);
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).fontFamily)).toContain("Pretendard");
  const exposedIcons = await page.locator("svg:not([aria-hidden='true'])").count();
  expect(exposedIcons).toBe(0);
  const unnamedButtons = await page.locator("button").evaluateAll((buttons) => buttons
    .filter((button) => !(button.getAttribute("aria-label") ?? button.textContent ?? "").replace(/\s+/g, "").trim())
    .map((button) => button.outerHTML));
  expect(unnamedButtons).toEqual([]);
});

test("대시보드의 마감 공고 링크가 상세와 회차를 함께 전달한다", async ({ page }) => {
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  const link = page.locator(".dash-notice-link").first();
  await expect(link).toBeVisible();
  const target = new URL(await link.getAttribute("href") ?? "", page.url());
  expect(target.pathname).toMatch(/^\/judgments\/\d+$/);
  expect(target.searchParams.get("run")).toBe(RUN_ID);
  await link.click();
  await expect.poll(() => new URL(page.url()).pathname).toBe(target.pathname);
});

test("대시보드 회차 요약이 API 집계와 별도 담당자 리뷰 수를 보여준다", async ({ page }) => {
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  await expect(page.getByRole("group", { name: "수집", exact: true })).toContainText("2,546건");
  await expect(page.getByRole("group", { name: "후보 풀", exact: true })).toContainText("327건");
  await expect(page.getByRole("group", { name: "판정 표본", exact: true })).toContainText("40건");
  await expect(page.getByRole("group", { name: "담당자 리뷰", exact: true })).toContainText("0건");
});

test("대시보드는 네 업무를 한 줄에 두고 미확인을 작은 주석으로 표시한다", async ({ page }) => {
  await mockWorkload(page, { generated_at: "2026-09-01T09:00:00Z", items: [
    { key: "order_plan_pending", count: 24, unavailable_reason: null },
    { key: "pre_spec_deep_review_ready", count: null, unavailable_reason: "provider_absent" },
    { key: "tracking_action_required", count: null, unavailable_reason: "no_completed_execution" },
    { key: "tracking_hold_review_due", count: 2, unavailable_reason: null },
    { key: "bid_final_decision_pending", count: null, unavailable_reason: null },
  ] });
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  const decisions = page.locator(".dash-journey-item");
  await expect(decisions).toHaveCount(4);
  const rows = await decisions.evaluateAll(items => items.map(item => Math.round(item.getBoundingClientRect().top)));
  expect(new Set(rows).size).toBe(1);
  const clipped = await decisions.locator(".dash-journey-title").evaluateAll(titles => titles
    .filter(title => title.scrollWidth - title.clientWidth > 1).map(title => title.textContent));
  expect(clipped).toEqual([]);
  const unavailable = decisions.locator(".dash-small").filter({ hasText: "미확인" });
  await expect(unavailable).toHaveCount(3);
  const sizes = await unavailable.evaluateAll(values => values.map(value => Number.parseFloat(getComputedStyle(value).fontSize)));
  for (const size of sizes) expect(size).toBe(10.8);
  const context = page.getByRole("region", { name: "회차 자료 범위" });
  expect(await context.evaluate(item => item.getBoundingClientRect().top)).toBeGreaterThan(rows[0]);
});

test("흡수한 마감·감사 경로가 기존 쿼리를 보존한다", async ({ page }) => {
  // docs/design/PLAN.md 2단계: 마감 추적은 검토 대기열의 저장된 뷰, 산출물 감사
  // 로그는 실행 상태의 탭으로 흡수됐다. 리다이렉트가 아니라 각 뷰의 주소이므로
  // 경로가 그대로 남고, 담당자가 들고 온 쿼리를 잃지 않아야 한다.
  await page.goto(`/deadlines?run=${encodeURIComponent(RUN_ID)}&from=dashboard`);
  // 전체 실행에서 400여 개가 동시에 붙으면 기본 5초 안에 이동이 끝나지 않아
  // 화면 결함 없이 깨졌다. 여유를 늘려 부하와 회귀를 구분한다.
  await expect.poll(() => new URL(page.url()).searchParams.get("sort"), { timeout: 15_000 }).toBe("deadline");
  let params = new URL(page.url()).searchParams;
  expect(params.get("run")).toBe(RUN_ID);
  expect(params.get("from")).toBe("dashboard");
  // `/deadlines` keeps the queue view but uses its shared route metadata, whose
  // topbar context is the read-only 공고 판정 이력 screen.
  await expect(page.locator("header.topbar h1")).toHaveText("공고 판정 이력");

  await page.goto(`/audit?run=${encodeURIComponent(RUN_ID)}&from=review`);
  await expect(page.locator("header.topbar h1")).toHaveText("실행 상태");
  await expect(page.getByRole("tab", { name: "산출물 감사 로그", exact: true })).toHaveAttribute("aria-selected", "true");
  params = new URL(page.url()).searchParams;
  expect(params.get("run")).toBe(RUN_ID);
  expect(params.get("from")).toBe("review");
});

test("담당자 확인 요청을 펼치고 접을 수 있다", async ({ page }) => {
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  const list = page.locator("#dashboard-verification-list");
  const toggle = page.locator("[aria-controls=dashboard-verification-list]");
  await expect(list.locator("li")).toHaveCount(3);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(toggle).toHaveText("접기");
  expect(await list.locator("li").count()).toBeGreaterThan(3);
});

test("담당자 확인 요청 프로필 링크가 선택한 회차를 보존한다", async ({ page }) => {
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  await page.getByRole("link", { name: "회사 프로필", exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/profile");
  expect(new URL(page.url()).searchParams.get("run")).toBe(RUN_ID);
});

test("감사 누락 수는 보존하고 확인할 수 없는 분모를 추정하지 않는다", async ({ page }) => {
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  const candidateKpi = page.getByRole("group", { name: "후보 풀", exact: true });
  await expect(candidateKpi).toContainText("327");
  await expect(candidateKpi).not.toContainText("감사 풀");
  const kpi = page.getByRole("group", { name: "1차 필터 누락" });
  await expect(kpi).toContainText("5건");
  await expect(kpi).toContainText("감사 표본 분모 미확인");
});

test("프로필의 불완전한 응답은 상태와 미확인을 0으로 확정하지 않는다", async ({ page }) => {
  await page.route("**/api/profile/sections", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "bidops.profile-projection.v1",
        profile_version: "company-profile.sha256:" + "a".repeat(64),
        profile_digest: "a".repeat(64),
        sections: [],
        status_counts: {},
        error_codes: ["profile_yaml_invalid"],
      }),
    });
  });
  await page.route("**/api/profile/unknowns", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "bidops.profile-projection.v1",
        profile_version: "company-profile.sha256:" + "a".repeat(64),
        profile_digest: "a".repeat(64),
        items: [],
        total: 0,
        reference_fields: [],
        error_codes: [],
      }),
    });
  });

  await page.goto("/profile");
  await expect(page.getByRole("alert")).toContainText("프로필 응답 확인 필요");
  await expect(page.locator(".crit-profile-summary strong")).toHaveText(["미확인", "미확인", "미확인"]);
  // 승인 시안의 요약·목록에서도 파싱 실패가 실제 미확인 0건으로 바뀌지 않는다.
  await expect(page.locator(".crit-summary")).not.toContainText(/미확인 항목 0(?:\D|$)/);
  await expect(page.getByText("미확인 항목이 없습니다. · 0건", { exact: true })).toHaveCount(0);
});

test("프로필 읽기 실패는 빈 정상 상태가 아니라 오류 상태로 표시한다", async ({ page }) => {
  await page.route("**/api/profile/sections", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "프로필 원문을 읽을 수 없습니다." }),
    });
  });

  await page.goto("/profile");
  await expect(page.getByText("회사 프로필을 불러오지 못했습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText(/^승인된 프로필 사본과 구조화 상태를 확인할 수 없습니다\./)).toBeVisible();
});

test("진행 중인 전량 판정은 중복 실행할 수 없다", async ({ page }) => {
  await page.goto(`/runs?run=${encodeURIComponent(RUN_ID)}`);
  await expect(page.getByRole("heading", { name: "전체 후보 판정 실행" })).toBeVisible();
  await expect(page.getByRole("button", { name: "전량 판정 대기열에 넣기" })).toBeDisabled();
  await expect(page.getByText("진행 중인 전량 판정 실행이 있어 새 실행을 시작할 수 없습니다.")).toBeVisible();
});

test("정책 활성화는 최신 운영 게이트와 담당자 없이는 열리지 않는다", async ({ page }) => {
  await page.goto(`/policies?policy=${CANDIDATE_POLICY}&ptab=approval`);
  const activate = page.locator(".crit-detail-foot").getByRole("button", { name: "정책 활성화 확인" });
  await expect(activate).toBeDisabled();
  await page.getByLabel("통과한 최신 운영 evaluation").click();
  await expect(page.getByRole("listbox")).not.toContainText("gate-model-comparison");
  await page.getByRole("option", { name: new RegExp(CANDIDATE_GATE_EVALUATION) }).click();
  await expect(activate).toBeEnabled();
  await activate.click();
  const dialog = page.getByRole("dialog");
  const confirm = dialog.getByRole("button", { name: "정책 활성화", exact: true });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel("활성화 담당자 · 필수").fill("검증 담당자");
  await expect(confirm).toBeEnabled();
});

test("상시 운영은 승인 조합 불일치 상태에서 켤 수 없다", async ({ page }) => {
  await page.goto("/operations");
  await expect(page.getByText("상시 운영이 거부되었습니다.")).toBeVisible();
  await expect(page.getByRole("alert", { name: "상시 운영 켜기 차단 사유" })).toContainText("켤 수 없는 상태입니다");
  await expect(page.getByRole("button", { name: "상시 운영 켜기" })).toHaveCount(0);
});

test("상시 운영 켜기는 대화상자에서 조합·담당자·결과 ID를 재확인한다", async ({ page }) => {
  const readyState = {
    configured_enabled: false,
    effective_enabled: false,
    environment_enabled: true,
    quality_gate_status: "통과",
    quality_gate_result_id: ACTIVE_GATE_EVALUATION,
    policy_version: ACTIVE_POLICY,
    model_name: "qwen3.8:27b",
    model_digest: "sha256:model-20260825-qwen",
    prompt_version: "screening-prompt.v1",
    company_profile_version: "company-profile.v1.20260825",
    company_profile_digest: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    updated_at: "2026-08-25T08:00:00+09:00",
    updated_by: "system:migration",
    rejection_reason: null,
  };
  let updatePayload: Record<string, unknown> | undefined;
  await page.route("**/api/schedule/always-on", async (route) => {
    if (route.request().method() === "PUT") {
      updatePayload = route.request().postDataJSON() as Record<string, unknown>;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(readyState) });
  });

  await page.goto("/operations");
  const trigger = page.getByRole("button", { name: "상시 운영 켜기" });
  await expect(trigger).toBeVisible();
  await trigger.click();

  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("기존 회차와 산출물은 바뀌지 않지만");
  await expect(dialog.getByRole("button", { name: "상시 운영 켜기" })).toBeDisabled();
  await dialog.getByLabel("변경 담당자").fill("운영 담당자");
  await dialog.getByLabel("게이트 결과 ID 확인").fill(ACTIVE_GATE_EVALUATION);
  await expect(dialog.getByRole("button", { name: "상시 운영 켜기" })).toBeEnabled();

  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement?.closest('[role="alertdialog"]') !== null)).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();

  await trigger.click();
  await dialog.getByLabel("변경 담당자").fill("운영 담당자");
  await dialog.getByLabel("게이트 결과 ID 확인").fill(ACTIVE_GATE_EVALUATION);
  await dialog.getByRole("button", { name: "상시 운영 켜기" }).click();
  await expect(dialog).toBeHidden();
  expect(updatePayload).toEqual({ enabled: true, confirmed_by: "운영 담당자", quality_gate_result_id: ACTIVE_GATE_EVALUATION });

  const overflow = await page.evaluate(() => ({ document: document.documentElement.scrollWidth - document.documentElement.clientWidth, body: document.body.scrollWidth - document.body.clientWidth }));
  expect(overflow.document).toBeLessThanOrEqual(1);
  expect(overflow.body).toBeLessThanOrEqual(1);
});

test("값 없음·미확인·계산 불가·0을 구분해 표시한다", async ({ page }) => {
  await page.goto("/metrics");
  await expect(page.getByText("계산 불가", { exact: true }).first()).toBeVisible();
  await page.getByText("세부 근거", { exact: true }).click();
  const repeatedKeys = page.getByRole("row").filter({ hasText: "repeated_notice_keys" });
  await expect(repeatedKeys.getByRole("cell", { name: "0", exact: true })).toBeVisible();

  await page.goto("/profile");
  await expect(page.getByText("미확인", { exact: true }).first()).toBeVisible();

  await page.goto("/operations?pane=history");
  await expect(page.getByText(/후보 값 없음/).first()).toBeVisible();
  await expect(page.getByText(/실패 0/).first()).toBeVisible();
});

test("평가 수치 누락은 0/10이 아니라 계산 불가로 남는다", async ({ page }) => {
  await page.goto("/quality-gates?gate=gate-model-comparison&state=null-review");
  await page.getByRole("tab", { name: "담당자 리뷰", exact: true }).click();
  const review = page.locator(".crit-stat-line");
  await expect(review).toContainText("유효 리뷰");
  await expect(review).toContainText("서로 다른 공고");
  await expect(review.getByText("계산 불가 / 10건", { exact: true })).toHaveCount(2);
  await expect(review).not.toContainText("0 / 10건");
});

// docs/design/PLAN.md 3단계: 사전규격 목록에서 심층 추적 승인 패널을 연 상태는
// lifecycleVisualTargets의 단순 goto만으로 도달할 수 없는 새 상호작용이라
// 별도 타깃으로 기준선을 남긴다(기존 pre-specs-list 타깃은 패널이 닫힌
// 기본 상태만 찍는다).

// 명세 §6.8 — 사전규격 등급·자동 준비 진행·참조 실행 배지·segment/inventory 표시.
// 이 층은 "화면이 업무 상태를 어떻게 말하는가"를 본다: 8값·3값+없음·4값+없음이
// 색이 아니라 **문자로** 나타나는지, 없음을 0이나 확인 완료로 바꾸지 않는지.

const AUTO_PREPARATION_LABELS = [
  "자동 준비 대상 아님",
  "첨부 취득 대기",
  "묶음 초안",
  "묶음 확정",
  "개요 검토 실행 중",
  "심층 검토 자동 시작됨",
  "심층 검토 클릭 대기",
  "자동 준비 중단",
];

test("사전규격 선택 상세가 등급 4값과 판정 없음, 자동 준비 8값을 문자로 보여준다", async ({ page }) => {
  await mockPreSpecMatrix(page);
  await page.goto("/pre-specs");
  const rows = page.locator(".pre-specs-row");
  await expect(rows).toHaveCount(8);
  const grades = ["판정 없음", "우선 검토", "우선 검토", "검토 권장", "검토 권장", "우선 검토", "관찰 대상", "제외"];
  for (let index = 0; index < AUTO_PREPARATION_LABELS.length; index += 1) {
    await rows.filter({ hasText: `자동 준비 표본 ${index + 1}` }).click();
    const detail = page.locator(".pre-specs-detail-pane");
    await expect(detail.locator(".pre-specs-detail-facts")).toContainText(grades[index]);
    // 자동 준비 8값의 진행 줄은 목록 우측 영역에서 빠졌다(spec §3.1). 상세 ⑥이 보여 준다.
  }
});

test("사전규격 등급 필터는 URL과 동기화되고 서버 전체 건수를 줄인다", async ({ page }) => {
  await mockPreSpecMatrix(page);
  await page.goto("/pre-specs");
  await expect(page.locator(".pre-specs-list").first()).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: "상세 필터", exact: true }).click();
  await page.getByRole("combobox", { name: /적합성 등급/ }).click();
  await page.getByRole("option", { name: "제외", exact: true }).click();
  // bda1288: 화면이 등급 필터 URL 인자를 `grade`에서 `display_grade`로 옮겼다
  // (구버전 `grade` URL은 별도로 정규화된다 — pre-specs.spec.ts).
  await expect.poll(() => new URL(page.url()).searchParams.get("display_grade")).toBe("제외");
  await expect(page.locator(".pre-specs-grade-filter-note")).toHaveCount(0);
  const rows = page.locator('.pre-specs-list [data-review-primitive="dense-list-row"]');
  await expect(rows).toHaveCount(1);
  await expect(page.locator(".pre-specs-list-head")).toContainText("1건");
  await expect(page.locator(".pre-specs-detail-facts")).toContainText("제외");

  // `판정 없음`은 다섯 번째 등급이 아니라 등급이 null인 건이다.
  await page.getByRole("combobox", { name: /적합성 등급/ }).click();
  await page.getByRole("option", { name: "판정 없음", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("display_grade")).toBe("판정 없음");
  await expect(rows).toHaveCount(1);

  await page.getByRole("button", { name: "기본값으로" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("display_grade")).toBeNull();
});

test("사전규격 상세가 등급 출처와 자동 준비 네 단계를 한 줄로 말한다", async ({ page }) => {
  await mockPreSpecAutoDetail(page, "started");
  await page.goto("/pre-specs/991");

  const steps = page.locator(".pre-spec-auto-steps");
  await expect(steps).toBeVisible({ timeout: 10_000 });
  // bda1288: PreSpecDetailPage가 "등급 출처 · {gradeSourceLabel}" 대신
  // "개요 기준 · {displayAssessmentSourceLabel}"을 그린다.
  await expect(page.locator(".pre-spec-detail-grade-row")).toContainText("개요 기준 · 기존 선별 판정");
  await expect(steps).toContainText("1 · 첨부 취득");
  await expect(steps).toContainText("완료 2 · 대기 1 · 진행 0 · 차단 0 · 실패 0");
  await expect(steps).toContainText("2 · 문서 묶음");
  await expect(steps).toContainText("확정 완료");
  await expect(steps).toContainText("3 · 개요 검토");
  await expect(steps).toContainText("4 · 심층 검토");
  await expect(steps).toContainText("심층 검토 자동 시작됨");

  const link = page.getByRole("link", { name: /자동 시작된 심층 검토 보고서 열기/ });
  await expect(link).toHaveAttribute("href", "/deep-reviews/fixture-review");
});

test("클릭 대기 상태는 보고서 링크 대신 기존 심층 검토 실행 동선을 준다", async ({ page }) => {
  await mockPreSpecAutoDetail(page, "ready_for_click");
  await page.goto("/pre-specs/991");

  const steps = page.locator(".pre-spec-auto-steps");
  await expect(steps).toBeVisible({ timeout: 10_000 });
  await expect(steps).toContainText("심층 검토 클릭 대기");
  // 사유 코드는 안전한 문구로 보이고, 없으면 아무것도 그리지 않는다.
  await expect(steps).toContainText("자동 확정 조건을 채우지 못한 묶음입니다.");
  await expect(page.getByRole("link", { name: /자동 시작된 심층 검토 보고서 열기/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /심층 검토 실행/ })).toHaveAttribute("href", "#document-preparation");
  // bda1288: "등급 출처 · 정정" → "개요 기준 · 사람 정정"(displayAssessmentSourceLabel).
  await expect(page.locator(".pre-spec-detail-grade-row")).toContainText("개요 기준 · 사람 정정");
});

// 명세 §6.2: 화면은 **현재 등급만** 보여 준다. 사람 정정이 있으면 정정된 값
// 하나만 보이고, notice의 판정 등급을 라벨 없이 함께 두지 않는다 — 어느 쪽이
// 현재 값인지 읽는 사람이 알 수 없게 되기 때문이다.
test("사전규격 상세는 정정된 현재 등급 하나만 보여준다", async ({ page }) => {
  await mockPreSpecAutoDetail(page, "corrected");
  await page.goto("/pre-specs/991");
  await expect(page.locator(".pre-spec-detail-grade-row")).toBeVisible({ timeout: 10_000 });

  // 문서 준비 패널까지 그려진 뒤에 센다. 등급을 그리는 자리가 늘어나면 여기서 잡힌다.
  await expect(page.locator("#document-preparation")).toBeVisible();

  const gradeTexts = await page.evaluate(() => {
    const labels = ["우선 검토", "검토 권장", "관찰 대상", "제외", "판정 없음"];
    return [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((element) => element.children.length === 0)
      .map((element) => (element.textContent ?? "").trim())
      .filter((text) => labels.includes(text));
  });
  // 정정된 값 하나뿐이다. notice의 판정 등급(`우선 검토`)은 화면에 없다.
  expect(gradeTexts).toEqual(["관찰 대상"]);
  // bda1288: "등급 출처 · 정정" → "개요 기준 · 사람 정정"(displayAssessmentSourceLabel).
  await expect(page.locator(".pre-spec-detail-grade-row")).toContainText("개요 기준 · 사람 정정");
  await expect(page.getByText("화면 참고 등급", { exact: false })).toHaveCount(0);

  // 현재 등급이 우선 검토가 아니므로 서버가 다시 본다는 안내는 남는다.
  await expect(page.locator(".document-preparation-gate")).toContainText("등급을 다시 확인합니다");
});

test("심층 보고서의 품질 표식 3값과 표식 없음이 카드와 의견 저장 위에 함께 나온다", async ({ page }) => {
  const cases: Array<[Parameters<typeof mockDeepReviewQuality>[1], string]> = [
    ["measured", "측정 통과"],
    ["unmeasured_reference", "참조 실행 · 품질 미측정"],
    ["mock_reference", "mock 참조"],
    [null, "표식 없음"],
  ];
  for (const [quality, label] of cases) {
    await mockDeepReviewQuality(page, quality);
    await page.goto(`/deep-reviews/fixture-review?quality=${quality ?? "none"}`);
    await expect(page.locator(".deep-review-quality-card")).toContainText(label, { timeout: 10_000 });
    await expect(page.locator(".deep-review-opinion-quality")).toContainText(label);
    // 표식이 무엇이든 최종 의견 저장을 막지 않는다.
    await expect(page.getByRole("button", { name: "심층검토 의견 추가" })).toBeVisible();
  }
});

test("심층 보고서 우측 열이 문서 inventory와 사람 확인 필요 segment를 보여준다", async ({ page }) => {
  await page.goto("/deep-reviews/fixture-review");
  const panel = page.locator(".deep-review-segment-panel");
  await expect(panel).toBeVisible({ timeout: 10_000 });

  const inventory = panel.locator(".deep-review-segment-inventory");
  await expect(inventory).toContainText("기대 ID 수");
  await expect(inventory).toContainText("중복 ID");
  await expect(inventory).toContainText("모호 항목");
  await expect(panel.locator(".deep-review-segment-coverage")).toContainText("사람 확인 필요 구간 3건");
  await expect(panel).toContainText("접두사 확인 안 됨");
  // 계약에 원문 text가 없으므로 제목을 만들어 내지 않는다.
  await expect(panel).toContainText("segment 제목을 제공하지 않습니다");

  const items = panel.locator(".deep-review-segment-list > li");
  await expect(items).toHaveCount(3);
  // 계약 순번·블록 키·요구사항 ID 나열은 접힌 `기술 정보` 안이고(ADR-0066),
  // 사람이 읽는 분류·건수·원문 조작은 밖에 남는다.
  const first = items.first();
  await expect(first).toContainText("2번째 구간");
  await expect(first).toContainText("기술·기능");
  await expect(first).toContainText("요구사항 ID 1개");
  await expect(first.getByRole("button", { name: "2쪽 원문 열기" })).toBeVisible();
  await expect(first.locator(".deep-review-technical-body")).toBeHidden();
  await first.getByText("기술 정보 · 2번째 구간").click();
  await expect(first.locator(".deep-review-technical-body")).toContainText("segment 2");
  await expect(first.locator(".deep-review-technical-body")).toContainText("SFR-3");
});

test("자동 심층 검토가 있어도 사업 추적 화면은 미선택을 그대로 보여준다", async ({ page }) => {
  await mockOpportunity(page);
  // §7.2: `미선택`은 더 이상 `조치 필요`(기본 탭)에 들지 않는다(`신규 입찰공고`·
  // `미결정`으로만 간다). `전체`로 이동해 `미선택` 표시가 여전히 그대로인지 본다.
  await page.goto("/opportunities?section=%EC%A0%84%EC%B2%B4");
  await expect(page.locator("header.topbar h1")).toHaveText("사업 추적", { timeout: 10_000 });
  await expect(page.getByText("미선택").first()).toBeVisible();
  // 자동 심층 검토를 위한 새 구역을 만들지 않는다.
  await expect(page.getByText("자동 심층 검토", { exact: false })).toHaveCount(0);
});
