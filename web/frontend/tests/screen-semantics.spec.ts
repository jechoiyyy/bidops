import { expect, test } from "@playwright/test";
import { installScreenFixtures } from "./screen-fixtures";

// 의미 층 — 화면이 업무 상태를 어떻게 말하는지 본다. 값 없음·미확인·계산 불가·0의
// 구분, 감사 누락의 분모를 추정하지 않기, 승인 게이트가 담당자 없이 열리지 않기가
// 여기 있다. 폭과 무관하므로 한 폭에서만 돈다.
//
// 세 층의 구분과 게이트는 `docs/standards.md`에 있다.

const RUN_ID = "20260817-20260823--20260824T090927.138116Z";
const ACTIVE_POLICY = "screening-policy.v1.20260825";
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

test("대시보드의 마감 링크가 회차와 정렬을 함께 전달한다", async ({ page }) => {
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  await page.getByRole("link", { name: /전체 보기/ }).click();
  await expect.poll(() => new URL(page.url()).pathname).toMatch(/^\/queue(?:\/\d+)?$/);
  const params = new URL(page.url()).searchParams;
  expect(params.get("run")).toBe(RUN_ID);
  expect(params.get("sort")).toBe("deadline");
});

test("대시보드 퍼널은 단계별 건수와 직전 단계 잔존율을 함께 보여준다", async ({ page }) => {
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  const rows = page.locator(".dashboard-funnel-row");
  await expect(rows).toHaveCount(4);
  const widths = await rows.locator(".dashboard-funnel-bar").evaluateAll((bars) => bars.map((bar) => Number.parseFloat((bar as HTMLElement).style.width)));
  expect(widths[0]).toBeCloseTo(100, 3);
  expect(widths[1]).toBeCloseTo((327 / 2546) * 100, 3);
  expect(widths[2]).toBeCloseTo((40 / 327) * 100, 3);
  expect(widths[3]).toBeCloseTo((17 / 40) * 100, 3);
  expect(widths[3]).toBeGreaterThan(widths[2]);
  await expect(rows.nth(0)).toContainText("2,546건");
  await expect(rows.nth(0)).toContainText("기준");
  await expect(rows.nth(2)).toContainText("12.2%");
  await expect(rows.nth(2)).toContainText("40건");
  await expect(rows.nth(3)).toContainText("42.5%");
  await expect(rows.nth(3)).toContainText("17건");
  await expect(page.locator(".dashboard-funnel-axis")).toContainText("0%25%50%75%100%");
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
  await expect(page.locator("header.topbar h1")).toHaveText("검토 대기열");

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
  const toggle = page.getByRole("button", { name: /나머지/ });
  await expect(list.locator("li")).toHaveCount(3);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(toggle).toHaveText("나머지 접기");
  expect(await list.locator("li").count()).toBeGreaterThan(3);
});

test("담당자 확인 요청 프로필 링크가 선택한 회차를 보존한다", async ({ page }) => {
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  await page.getByRole("link", { name: /회사 프로필에서 확정하기/ }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/profile");
  expect(new URL(page.url()).searchParams.get("run")).toBe(RUN_ID);
});

test("감사 누락 수는 보존하고 확인할 수 없는 분모를 추정하지 않는다", async ({ page }) => {
  await page.goto(`/?run=${encodeURIComponent(RUN_ID)}`);
  const candidateKpi = page.getByRole("region", { name: "후보 풀" });
  await expect(candidateKpi).toContainText("327");
  await expect(candidateKpi).not.toContainText("감사 풀");
  const kpi = page.getByRole("region", { name: "1차 필터 누락" });
  await expect(kpi).toContainText("5 / 표본 미확인");
  await expect(kpi).toContainText("감사 표본 분모를 확인할 수 없어 누락률을 계산하지 않습니다.");
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
  await expect(page.locator(".profile-summary strong")).toHaveText(["미확인", "미확인", "미확인"]);
  await expect(page.locator(".profile-unknown-panel")).toContainText("미확인 항목을 표시할 수 없습니다.");
  await expect(page.locator(".profile-unknown-panel")).not.toContainText("0건");
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
  await expect(page.getByText("승인된 프로필 snapshot과 구조화 상태를 확인할 수 없습니다.", { exact: true })).toBeVisible();
});

test("진행 중인 전량 판정은 중복 실행할 수 없다", async ({ page }) => {
  await page.goto(`/runs?run=${encodeURIComponent(RUN_ID)}`);
  await expect(page.getByRole("heading", { name: "전체 후보 판정 실행" })).toBeVisible();
  await expect(page.getByRole("button", { name: "전량 판정 대기열에 넣기" })).toBeDisabled();
  await expect(page.getByText("진행 중인 전량 판정 실행이 있어 새 실행을 시작할 수 없습니다.")).toBeVisible();
});

test("정책 활성화는 최신 운영 게이트와 담당자 없이는 열리지 않는다", async ({ page }) => {
  await page.goto("/policies");
  const candidate = page.locator(".policy-version-card.policy-status-activation_candidate");
  const activate = candidate.getByRole("button", { name: "정책 활성화 확인" });
  const gateSelect = candidate.getByLabel("통과한 최신 운영 evaluation");
  await expect(activate).toBeDisabled();
  const options = await gateSelect.locator("option").allTextContents();
  expect(options.some((option) => option.includes("gate-model-comparison"))).toBe(false);
  await gateSelect.selectOption(CANDIDATE_GATE_EVALUATION);
  await candidate.getByLabel("활성화 담당자").fill("검증 담당자");
  await expect(activate).toBeEnabled();
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
  await expect(page.getByText(/repeated_notice_keys 0/)).toBeVisible();

  await page.goto("/profile");
  await expect(page.getByText("미확인", { exact: true }).first()).toBeVisible();

  await page.goto("/operations");
  await expect(page.getByText(/후보 값 없음/).first()).toBeVisible();
  await expect(page.getByText(/실패 0/).first()).toBeVisible();
});

test("평가 수치 누락은 0/10이 아니라 계산 불가로 남는다", async ({ page }) => {
  await page.goto("/quality-gates?gate=gate-model-comparison&state=null-review");
  const review = page.locator("section[aria-labelledby='quality-review-heading']");
  await expect(review.getByText("계산 불가/10 유효 리뷰", { exact: true })).toBeVisible();
  await expect(review.getByText("계산 불가/10 서로 다른 공고", { exact: true })).toBeVisible();
});

// docs/design/PLAN.md 3단계: 사전규격 목록에서 심층 추적 승인 패널을 연 상태는
// lifecycleVisualTargets의 단순 goto만으로 도달할 수 없는 새 상호작용이라
// 별도 타깃으로 기준선을 남긴다(기존 pre-specs-list 타깃은 패널이 닫힌
// 기본 상태만 찍는다).
